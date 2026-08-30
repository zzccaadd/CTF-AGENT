"""SQLite event store with Muteki-style append/replay and atomic intent claims."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.evidence.models import EvidenceEvent, Intent

SCHEMA_VERSION = 1


class SQLiteEvidenceStore:
    """One process-safe connection over a shared SQLite evidence database."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', '1');
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT UNIQUE NOT NULL,
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                challenge_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                kind TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                payload TEXT NOT NULL,
                provenance TEXT NOT NULL,
                artifact_id TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                dedupe_key TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_events_challenge_seq
                ON events(challenge_name, run_id, seq);
            CREATE INDEX IF NOT EXISTS idx_events_kind
                ON events(challenge_name, run_id, kind, seq);
            CREATE TABLE IF NOT EXISTS intents (
                challenge_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                intent_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                acceptance TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                worker_id TEXT,
                lease_until REAL,
                attempt INTEGER NOT NULL DEFAULT 0,
                created_event_id TEXT NOT NULL,
                result_event_id TEXT,
                result TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (challenge_name, run_id, intent_id)
            );
            CREATE INDEX IF NOT EXISTS idx_intents_claimable
                ON intents(challenge_name, run_id, status, lease_until, attempt);
            CREATE TABLE IF NOT EXISTS event_links (
                source_event_id TEXT NOT NULL,
                target_event_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                PRIMARY KEY(source_event_id, target_event_id, relation)
            );
            """
        )
        # CREATE TABLE IF NOT EXISTS does not add columns to databases created
        # by an earlier Stage 1 revision. Keep this migration deliberately small
        # and idempotent so a running installation can be upgraded in place.
        # The whole migration runs under BEGIN IMMEDIATE so concurrent first
        # connections cannot race on ALTER TABLE / table rebuild.
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            event_columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(events)").fetchall()
            }
            if "schema_version" not in event_columns:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1"
                )
            self._migrate_intents_table()
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '2')"
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def latest_run_id(self, challenge_name: str) -> str | None:
        """Return the most recently active run for restart recovery."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT run_id
                FROM events
                WHERE challenge_name=?
                GROUP BY run_id
                HAVING SUM(CASE WHEN kind='challenge_started' THEN 1 ELSE 0 END)
                     > SUM(CASE WHEN kind='challenge_finished' THEN 1 ELSE 0 END)
                ORDER BY MAX(seq) DESC
                LIMIT 1
                """,
                (challenge_name,),
            ).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _fingerprint(
        challenge_name: str,
        run_id: str,
        actor_id: str,
        kind: str,
        payload: dict[str, Any],
    ) -> str:
        raw = json.dumps(
            [challenge_name, run_id, actor_id, kind, payload],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode()
        return "auto:" + hashlib.sha256(raw).hexdigest()

    def _append_event_locked(
        self,
        *,
        challenge_name: str,
        run_id: str,
        actor_id: str,
        actor_type: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        artifact_id: str | None = None,
        verified: bool = False,
        dedupe_key: str | None = None,
        links: list[tuple[str, str]] | None = None,
    ) -> EvidenceEvent:
        """Insert or retrieve an event while the caller owns the DB lock/transaction."""
        payload = dict(payload or {})
        provenance = dict(provenance or {})
        dedupe_key = dedupe_key or self._fingerprint(
            challenge_name, run_id, actor_id, kind, payload
        )
        legacy_dedupe_key = dedupe_key
        # Dedupe is scoped to one challenge run. This prevents a caller-supplied
        # short key from colliding with an unrelated challenge in the global DB.
        dedupe_key = f"{challenge_name}:{run_id}:{dedupe_key}"
        # Read old unscoped rows during an in-place upgrade. Restrict the lookup
        # by challenge/run so a legacy collision cannot leak another run's event.
        legacy = self._conn.execute(
            "SELECT * FROM events WHERE dedupe_key=? AND challenge_name=? AND run_id=?",
            (legacy_dedupe_key, challenge_name, run_id),
        ).fetchone()
        if legacy is not None:
            return self._event(legacy)
        event_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT OR IGNORE INTO events
            (event_id, ts, challenge_name, run_id, actor_id, actor_type,
             kind, schema_version, payload, provenance, artifact_id, verified, dedupe_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                time.time(),
                challenge_name,
                run_id,
                actor_id,
                actor_type,
                kind,
                SCHEMA_VERSION,
                self._json(payload),
                self._json(provenance),
                artifact_id,
                int(verified),
                dedupe_key,
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM events WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
        if row is None:
            raise RuntimeError("event insert was ignored without an existing dedupe record")
        if row["event_id"] == event_id:
            for target_id, relation in links or []:
                self._conn.execute(
                    "INSERT OR IGNORE INTO event_links(source_event_id, target_event_id, relation) VALUES (?, ?, ?)",
                    (event_id, target_id, relation),
                )
        return self._event(row)

    def append_event(
        self,
        *,
        challenge_name: str,
        run_id: str,
        actor_id: str,
        actor_type: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        artifact_id: str | None = None,
        verified: bool = False,
        dedupe_key: str | None = None,
        links: list[tuple[str, str]] | None = None,
    ) -> EvidenceEvent:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                event = self._append_event_locked(
                    challenge_name=challenge_name,
                    run_id=run_id,
                    actor_id=actor_id,
                    actor_type=actor_type,
                    kind=kind,
                    payload=payload,
                    provenance=provenance,
                    artifact_id=artifact_id,
                    verified=verified,
                    dedupe_key=dedupe_key,
                    links=links,
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return event

    def _migrate_intents_table(self) -> None:
        """Rebuild the intents projection with a (challenge_name, run_id, intent_id)
        primary key when the database still has the legacy intent_id-only key.

        Must be called while the caller owns the write lock (BEGIN IMMEDIATE).
        The old table is renamed, the new table is created, rows are copied,
        and the old table is dropped — all inside the same transaction.
        """
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='intents'"
        ).fetchone()
        if row is None:
            return
        if "PRIMARY KEY (challenge_name, run_id, intent_id)" in str(row[0]):
            return
        self._conn.execute("DROP INDEX IF EXISTS idx_intents_claimable")
        self._conn.execute("ALTER TABLE intents RENAME TO intents_legacy")
        self._conn.execute(
            """CREATE TABLE intents (
                challenge_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                intent_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                acceptance TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                worker_id TEXT,
                lease_until REAL,
                attempt INTEGER NOT NULL DEFAULT 0,
                created_event_id TEXT NOT NULL,
                result_event_id TEXT,
                result TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (challenge_name, run_id, intent_id)
            )"""
        )
        self._conn.execute(
            """INSERT OR IGNORE INTO intents
            (challenge_name, run_id, intent_id, goal, acceptance, status, worker_id,
             lease_until, attempt, created_event_id, result_event_id, result)
            SELECT challenge_name, run_id, intent_id, goal, acceptance, status, worker_id,
                   lease_until, attempt, created_event_id, result_event_id, result
            FROM intents_legacy"""
        )
        self._conn.execute("DROP TABLE intents_legacy")
        self._conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_intents_claimable
            ON intents(challenge_name, run_id, status, lease_until, attempt)"""
        )

    def _event(self, row: sqlite3.Row) -> EvidenceEvent:
        return EvidenceEvent(
            event_id=row["event_id"],
            seq=int(row["seq"]),
            ts=float(row["ts"]),
            challenge_name=row["challenge_name"],
            run_id=row["run_id"],
            actor_id=row["actor_id"],
            actor_type=row["actor_type"],
            kind=row["kind"],
            schema_version=int(row["schema_version"]),
            payload=json.loads(row["payload"]),
            provenance=json.loads(row["provenance"]),
            artifact_id=row["artifact_id"],
            verified=bool(row["verified"]),
            dedupe_key=row["dedupe_key"],
        )

    def events(
        self,
        challenge_name: str,
        run_id: str,
        *,
        kinds: list[str] | None = None,
        after_seq: int = 0,
    ) -> list[EvidenceEvent]:
        with self._lock:
            params: list[Any] = [challenge_name, run_id, int(after_seq)]
            where = "challenge_name = ? AND run_id = ? AND seq > ?"
            if kinds:
                where += " AND kind IN (" + ",".join("?" for _ in kinds) + ")"
                params.extend(kinds)
            rows = self._conn.execute(
                f"SELECT * FROM events WHERE {where} ORDER BY seq", tuple(params)
            ).fetchall()
        return [self._event(row) for row in rows]

    def propose_intent(
        self,
        *,
        challenge_name: str,
        run_id: str,
        actor_id: str,
        intent_id: str,
        goal: str,
        acceptance: str = "",
        from_event_ids: list[str] | None = None,
    ) -> Intent:
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM intents WHERE intent_id=? AND challenge_name=? AND run_id=?",
                (intent_id, challenge_name, run_id),
            ).fetchone()
            if existing:
                return self._intent(existing)
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                event = self._append_event_locked(
                    challenge_name=challenge_name,
                    run_id=run_id,
                    actor_id=actor_id,
                    actor_type="coordinator",
                    kind="intent_proposed",
                    payload={"intent_id": intent_id, "goal": goal, "acceptance": acceptance},
                    links=[(eid, "supports") for eid in from_event_ids or []],
                    dedupe_key=f"intent:{challenge_name}:{run_id}:{intent_id}",
                )
                self._conn.execute(
                    """INSERT OR IGNORE INTO intents
                    (intent_id, challenge_name, run_id, goal, acceptance, created_event_id)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (intent_id, challenge_name, run_id, goal, acceptance, event.event_id),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            row = self._conn.execute(
                "SELECT * FROM intents WHERE intent_id=? AND challenge_name=? AND run_id=?",
                (intent_id, challenge_name, run_id),
            ).fetchone()
        assert row is not None
        return self._intent(row)

    def _intent(self, row: sqlite3.Row) -> Intent:
        return Intent(
            intent_id=row["intent_id"],
            challenge_name=row["challenge_name"],
            run_id=row["run_id"],
            goal=row["goal"],
            acceptance=row["acceptance"],
            status=row["status"],
            worker_id=row["worker_id"],
            lease_until=row["lease_until"],
            attempt=int(row["attempt"]),
            created_event_id=row["created_event_id"],
            result_event_id=row["result_event_id"],
            result=row["result"],
        )

    def list_intents(self, challenge_name: str, run_id: str, *, active_only: bool = True) -> list[Intent]:
        now = time.time()
        with self._lock:
            if active_only:
                rows = self._conn.execute(
                    """SELECT * FROM intents WHERE challenge_name=? AND run_id=?
                    AND (status='open' OR (status='claimed' AND lease_until < ?))
                    ORDER BY attempt, intent_id""",
                    (challenge_name, run_id, now),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM intents WHERE challenge_name=? AND run_id=? ORDER BY intent_id",
                    (challenge_name, run_id),
                ).fetchall()
        return [self._intent(row) for row in rows]

    def claim_intent(self, *, challenge_name: str, run_id: str, worker_id: str, intent_id: str, lease_seconds: int = 300, max_attempts: int = 3) -> Intent | None:
        now = time.time()
        lease_until = now + max(1, int(lease_seconds))
        max_attempts = max(1, int(max_attempts))
        with self._lock:
            current = self._conn.execute(
                """SELECT * FROM intents
                WHERE intent_id=? AND challenge_name=? AND run_id=?""",
                (intent_id, challenge_name, run_id),
            ).fetchone()
            if (
                current is not None
                and current["status"] == "claimed"
                and current["worker_id"] == worker_id
                and (current["lease_until"] or 0) >= now
            ):
                return self._intent(current)
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                expired = self._conn.execute(
                    """SELECT * FROM intents WHERE intent_id=? AND challenge_name=? AND run_id=?
                       AND status='claimed' AND lease_until < ? AND attempt >= ?""",
                    (intent_id, challenge_name, run_id, now, max_attempts),
                ).fetchone()
                if expired is not None:
                    event = self._append_event_locked(
                        challenge_name=challenge_name,
                        run_id=run_id,
                        actor_id="coordinator",
                        actor_type="coordinator",
                        kind="intent_completed",
                        payload={"intent_id": intent_id, "result": "maximum attempts reached", "status": "blocked"},
                        dedupe_key=f"max-attempts:{intent_id}:{max_attempts}",
                    )
                    self._conn.execute(
                        "UPDATE intents SET status='blocked', result=?, result_event_id=?, worker_id=NULL, lease_until=NULL "
                        "WHERE intent_id=? AND challenge_name=? AND run_id=?",
                        ("maximum attempts reached", event.event_id, intent_id, challenge_name, run_id),
                    )
                    self._conn.commit()
                    return None
                cur = self._conn.execute(
                    """UPDATE intents SET status='claimed', worker_id=?, lease_until=?, attempt=attempt+1
                    WHERE intent_id=? AND challenge_name=? AND run_id=?
                    AND (status='open' OR (status='claimed' AND lease_until < ?))""",
                    (worker_id, lease_until, intent_id, challenge_name, run_id, now),
                )
                if cur.rowcount != 1:
                    self._conn.rollback()
                    return None
                self._append_event_locked(
                    challenge_name=challenge_name,
                    run_id=run_id,
                    actor_id=worker_id,
                    actor_type="worker",
                    kind="intent_claimed",
                    payload={"intent_id": intent_id, "lease_until": lease_until},
                    dedupe_key=f"claim:{intent_id}:{worker_id}:{int(lease_until)}",
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            row = self._conn.execute(
                "SELECT * FROM intents WHERE intent_id=? AND challenge_name=? AND run_id=?",
                (intent_id, challenge_name, run_id),
            ).fetchone()
        if not row:
            return None
        return self._intent(row)

    def heartbeat(
        self,
        *,
        challenge_name: str,
        run_id: str,
        intent_id: str,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> bool:
        """Renew the lease only while the intent is still owned by worker_id and
        the current lease has not expired yet (fencing guard), scoped to one run."""
        with self._lock:
            cur = self._conn.execute(
                """UPDATE intents SET lease_until=?
                WHERE intent_id=? AND challenge_name=? AND run_id=?
                  AND status='claimed' AND worker_id=? AND lease_until >= ?""",
                (
                    time.time() + max(1, int(lease_seconds)),
                    intent_id,
                    challenge_name,
                    run_id,
                    worker_id,
                    time.time(),
                ),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def complete_intent(
        self,
        *,
        challenge_name: str,
        run_id: str,
        worker_id: str,
        intent_id: str,
        result: str,
        status: str = "completed",
        produced_event_ids: list[str] | None = None,
    ) -> Intent | None:
        if status not in {"completed", "failed", "blocked"}:
            raise ValueError(f"invalid intent terminal status: {status}")
        with self._lock:
            now = time.time()
            existing = self._conn.execute(
                """SELECT * FROM intents
                WHERE intent_id=? AND challenge_name=? AND run_id=?""",
                (intent_id, challenge_name, run_id),
            ).fetchone()
            if existing is not None and existing["status"] in {"completed", "failed", "blocked"}:
                if existing["status"] == status and existing["result"] == result[:2000]:
                    return self._intent(existing)
                return None
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                current = self._conn.execute(
                    """SELECT * FROM intents
                    WHERE intent_id=? AND challenge_name=? AND run_id=?
                      AND status='claimed' AND worker_id=? AND lease_until >= ?""",
                    (intent_id, challenge_name, run_id, worker_id, now),
                ).fetchone()
                if current is None:
                    self._conn.rollback()
                    return None
                event = self._append_event_locked(
                    challenge_name=challenge_name,
                    run_id=run_id,
                    actor_id=worker_id,
                    actor_type="worker",
                    kind="intent_completed",
                    payload={"intent_id": intent_id, "result": result, "status": status},
                    links=[(eid, "produces") for eid in produced_event_ids or []],
                    dedupe_key=f"complete:{intent_id}:{worker_id}:{status}:{result[:200]}",
                )
                self._conn.execute(
                    """UPDATE intents SET status=?, result=?, result_event_id=?, worker_id=NULL, lease_until=NULL
                    WHERE intent_id=? AND challenge_name=? AND run_id=? AND worker_id=?""",
                    (status, result[:2000], event.event_id, intent_id, challenge_name, run_id, worker_id),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            row = self._conn.execute(
                "SELECT * FROM intents WHERE intent_id=? AND challenge_name=? AND run_id=?",
                (intent_id, challenge_name, run_id),
            ).fetchone()
        return self._intent(row) if row else None
