from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

from backend.evidence import EvidenceBoard
from backend.evidence.store import SQLiteEvidenceStore
from backend.message_bus import ChallengeMessageBus


def test_board_persists_and_replays(tmp_path) -> None:
    path = tmp_path / "evidence.sqlite3"
    board = EvidenceBoard.open(path, "demo", "run-1")
    board.start()
    intent = board.propose("coordinator", "inspect files")
    claimed = board.claim("codex-1", intent.intent_id, lease_seconds=30)
    assert claimed and claimed.worker_id == "codex-1"
    assert board.claim("codex-1", intent.intent_id).attempt == claimed.attempt
    fact = board.add_fact(
        "codex-1", "service 80 is open", verified=True,
        provenance={"source_kind": "trace", "trace_event_index": 3, "source_excerpt": "service 80 is open"},
    )
    completed = board.complete("codex-1", intent.intent_id, "completed", produced_event_ids=[fact.event_id])
    assert completed and board.complete("codex-1", intent.intent_id, "completed") == completed
    board.close()

    reopened = EvidenceBoard.open(path, "demo", "run-1")
    snapshot = reopened.snapshot()
    replayed = reopened.replay()
    assert snapshot.last_seq >= 5
    assert snapshot.facts[0].payload["fact"] == "service 80 is open"
    assert snapshot.facts[0].schema_version == 1
    assert snapshot.intents[0].status == "completed"
    assert replayed == snapshot
    # Replay must remain correct even if the fast intent projection is lost.
    reopened.store._conn.execute("DELETE FROM intents WHERE intent_id=?", (intent.intent_id,))
    reopened.store._conn.commit()
    projection_free = reopened.replay()
    assert projection_free.intents[0].status == "completed"
    reopened.close()


def test_unverified_fact_is_stored_as_hypothesis_and_verified_requires_provenance(tmp_path) -> None:
    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    event = board.add_fact("codex-1", "possible endpoint", verified=False, provenance={})
    assert event.kind == "hypothesis_added"
    try:
        board.add_fact("codex-1", "unsupported fact", verified=True, provenance={"source_kind": "trace"})
    except ValueError as exc:
        assert "source_excerpt" in str(exc)
    else:
        raise AssertionError("verified fact without provenance was accepted")
    board.close()


def test_message_bus_compatibility_reads_board_summary(tmp_path) -> None:
    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    board.start()
    bus = ChallengeMessageBus()
    bus.attach_board(board)
    first = board.add_fact(
        "codex-1", "port 80 is open", verified=True,
        provenance={"source_kind": "trace", "source_excerpt": "port 80 is open"},
    )

    async def read() -> tuple[list, list]:
        return await bus.check("codex-2"), await bus.check("codex-2")

    unread, repeated = asyncio.run(read())
    assert first.event_id
    assert unread and "port 80 is open" in unread[0].content
    assert repeated == []
    board.close()


def test_open_resumes_only_an_unfinished_run(tmp_path) -> None:
    path = tmp_path / "evidence.sqlite3"
    finished = EvidenceBoard.open(path, "demo", "finished-run")
    finished.start()
    finished.finish(reason="workers_exhausted")
    finished.close()

    fresh = EvidenceBoard.open(path, "demo")
    assert fresh.run_id != "finished-run"
    fresh.start()
    resumed = EvidenceBoard.open(path, "demo")
    assert resumed.run_id == fresh.run_id
    resumed.close()
    fresh.close()


def test_claim_is_single_winner(tmp_path) -> None:
    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    intent = board.propose("coordinator", "one task")
    wins: list[bool] = []

    def claim(worker: str) -> None:
        wins.append(board.claim(worker, intent.intent_id) is not None)

    threads = [threading.Thread(target=claim, args=(f"codex-{i}",)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(wins) == 1
    board.close()


def test_expired_lease_can_be_reclaimed(tmp_path) -> None:
    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    intent = board.propose("coordinator", "reclaim me")
    assert board.claim("codex-1", intent.intent_id, lease_seconds=1)
    time.sleep(1.05)
    reclaimed = board.claim("codex-2", intent.intent_id, lease_seconds=30)
    assert reclaimed and reclaimed.worker_id == "codex-2"
    board.close()


def test_stale_worker_cannot_complete_reclaimed_intent(tmp_path) -> None:
    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    intent = board.propose("coordinator", "fenced task")
    assert board.claim("codex-1", intent.intent_id, lease_seconds=1)
    time.sleep(1.05)
    assert board.claim("codex-2", intent.intent_id, lease_seconds=30)
    assert board.complete("codex-1", intent.intent_id, "stale") is None
    current = board.store.list_intents("demo", "run-1", active_only=False)[0]
    assert current.status == "claimed"
    assert current.worker_id == "codex-2"
    assert not any(
        event.kind == "intent_completed"
        for event in board.store.events("demo", "run-1")
    )
    board.close()


def test_expired_worker_cannot_complete_without_reclaim(tmp_path) -> None:
    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    intent = board.propose("coordinator", "lease fenced task")
    assert board.claim("codex-1", intent.intent_id, lease_seconds=30)
    board.store._conn.execute(
        "UPDATE intents SET lease_until=0 WHERE intent_id=?", (intent.intent_id,)
    )
    board.store._conn.commit()
    assert board.complete("codex-1", intent.intent_id, "late result") is None
    assert not any(
        event.kind == "intent_completed"
        for event in board.store.events("demo", "run-1")
    )
    board.close()


def test_intent_is_blocked_after_max_attempts(tmp_path) -> None:
    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    intent = board.propose("coordinator", "bounded task")
    for worker in ("codex-1", "codex-2", "codex-3"):
        assert board.claim(worker, intent.intent_id, lease_seconds=30, max_attempts=3)
        board.store._conn.execute(
            "UPDATE intents SET lease_until=0 WHERE intent_id=?", (intent.intent_id,)
        )
        board.store._conn.commit()
    assert board.claim("codex-4", intent.intent_id, lease_seconds=30, max_attempts=3) is None
    current = board.store.list_intents("demo", "run-1", active_only=False)[0]
    assert current.status == "blocked"
    assert current.result == "maximum attempts reached"
    board.close()


def test_deduped_events_do_not_duplicate(tmp_path) -> None:
    store = SQLiteEvidenceStore(tmp_path / "evidence.sqlite3")
    first = store.append_event(
        challenge_name="demo", run_id="run-1", actor_id="codex-1", actor_type="worker",
        kind="fact_added", payload={"fact": "same"}, dedupe_key="same-event",
    )
    second = store.append_event(
        challenge_name="demo", run_id="run-1", actor_id="codex-1", actor_type="worker",
        kind="fact_added", payload={"fact": "same"}, dedupe_key="same-event",
    )
    assert first.event_id == second.event_id
    assert len(store.events("demo", "run-1")) == 1
    store.close()


def test_custom_dedupe_keys_are_scoped_to_run(tmp_path) -> None:
    store = SQLiteEvidenceStore(tmp_path / "evidence.sqlite3")
    first = store.append_event(
        challenge_name="demo", run_id="run-1", actor_id="worker", actor_type="worker",
        kind="fact_added", payload={"fact": "one"}, dedupe_key="shared-key",
    )
    second = store.append_event(
        challenge_name="demo", run_id="run-2", actor_id="worker", actor_type="worker",
        kind="fact_added", payload={"fact": "two"}, dedupe_key="shared-key",
    )
    assert first.event_id != second.event_id
    assert len(store.events("demo", "run-1")) == 1
    assert len(store.events("demo", "run-2")) == 1
    store.close()


def test_summary_respects_character_limit(tmp_path) -> None:
    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    board.add_hypothesis("worker", "x" * 5000)
    summary = board.summary(max_chars=180)
    assert len(summary) <= 180
    assert "truncated" in summary
    assert len(board.summary(max_items=0)) < 200
    assert len(board.summary(max_chars=10)) == 10
    board.close()


def test_followup_index_restores_after_restart(tmp_path) -> None:
    from backend.agents.swarm import ChallengeSwarm

    board = EvidenceBoard.open(tmp_path / "evidence.sqlite3", "demo", "run-1")
    board.propose("coordinator", "followup", intent_id="followup:demo:run-1:9")
    swarm = object.__new__(ChallengeSwarm)
    swarm.evidence_board = board
    swarm.meta = SimpleNamespace(name="demo")
    swarm.run_id = "run-1"
    swarm._next_intent_index = 4
    swarm._restore_followup_index()
    assert swarm._next_intent_index == 10
    board.close()


def test_intent_status_aliases_are_normalized() -> None:
    from backend.agents.codex_solver import CodexSolver

    aliases = {
        "done": "completed",
        "complete": "completed",
        "success": "completed",
        "succeeded": "completed",
        "error": "failed",
        "gave_up": "blocked",
        "give_up": "blocked",
    }
    for source, expected in aliases.items():
        assert CodexSolver._normalize_intent_status(source) == expected
    assert CodexSolver._normalize_intent_status("unexpected") == "failed"
    assert CodexSolver._normalize_intent_status(None) == "completed"


def test_swarm_confirmed_flag_fallback_result() -> None:
    from backend.agents.swarm import ChallengeSwarm
    from backend.solver_base import FLAG_FOUND

    swarm = object.__new__(ChallengeSwarm)
    swarm.confirmed_flag = "CTF{ok}"
    swarm._flag_winner_label = "codex/gpt-5.5#1"
    swarm.solvers = {}
    swarm.cost_tracker = SimpleNamespace(total_cost_usd=0.42)
    result = swarm._confirmed_flag_result()
    assert result is not None
    assert result.status == FLAG_FOUND
    assert result.flag == "CTF{ok}"
    assert result.cost_usd == 0.42

    empty = object.__new__(ChallengeSwarm)
    empty.confirmed_flag = ""
    assert empty._confirmed_flag_result() is None


def test_codex_submission_stores_normalized_flag() -> None:
    from backend.agents.codex_solver import CodexSolver

    async def submit(flag: str) -> tuple[str, bool]:
        assert flag == " flag{ok} "
        return "CORRECT", True

    solver = object.__new__(CodexSolver)
    solver.no_submit = False
    solver.submit_fn = submit
    solver.evidence_board = None
    solver.intent_id = None
    solver._confirmed = False
    solver._flag = None
    result = asyncio.run(solver._exec_tool("submit_flag", {"flag": " flag{ok} "}))

    assert result == "CORRECT"
    assert solver._confirmed is True
    assert solver._flag == "flag{ok}"


def test_same_intent_id_is_scoped_to_run(tmp_path) -> None:
    store = SQLiteEvidenceStore(tmp_path / "evidence.sqlite3")
    first = store.propose_intent(
        challenge_name="demo", run_id="run-1", actor_id="coordinator",
        intent_id="shared-id", goal="one",
    )
    second = store.propose_intent(
        challenge_name="demo", run_id="run-2", actor_id="coordinator",
        intent_id="shared-id", goal="two",
    )
    assert first.intent_id == second.intent_id == "shared-id"
    assert first.run_id == "run-1" and second.run_id == "run-2"
    # Claiming in run-2 must not touch the run-1 row (composite PK scoping).
    assert store.claim_intent(
        challenge_name="demo", run_id="run-2", worker_id="w", intent_id="shared-id"
    )
    second_now = store.list_intents("demo", "run-2", active_only=False)[0]
    assert second_now.status == "claimed"
    first_now = store.list_intents("demo", "run-1", active_only=False)[0]
    assert first_now.status == "open"
    store.close()


def test_heartbeat_is_scoped_to_run_and_lease_guarded(tmp_path) -> None:
    store = SQLiteEvidenceStore(tmp_path / "evidence.sqlite3")
    store.propose_intent(
        challenge_name="demo", run_id="run-1", actor_id="coordinator",
        intent_id="beat-1", goal="beat",
    )
    assert store.claim_intent(
        challenge_name="demo", run_id="run-1", worker_id="w1",
        intent_id="beat-1", lease_seconds=1,
    )
    # Same-run heartbeat renews the lease.
    assert store.heartbeat(
        challenge_name="demo", run_id="run-1", intent_id="beat-1",
        worker_id="w1", lease_seconds=30,
    )
    # Wrong run or wrong worker cannot renew.
    assert not store.heartbeat(
        challenge_name="demo", run_id="run-2", intent_id="beat-1",
        worker_id="w1", lease_seconds=30,
    )
    assert not store.heartbeat(
        challenge_name="demo", run_id="run-1", intent_id="beat-1",
        worker_id="w2", lease_seconds=30,
    )
    # Expired lease cannot be renewed by the stale owner (fencing guard).
    store._conn.execute("UPDATE intents SET lease_until=0 WHERE intent_id=?", ("beat-1",))
    store._conn.commit()
    assert not store.heartbeat(
        challenge_name="demo", run_id="run-1", intent_id="beat-1",
        worker_id="w1", lease_seconds=30,
    )
    store.close()


def test_max_attempts_blocked_is_scoped_to_run(tmp_path) -> None:
    store = SQLiteEvidenceStore(tmp_path / "evidence.sqlite3")
    for run_id in ("run-1", "run-2"):
        store.propose_intent(
            challenge_name="demo", run_id=run_id, actor_id="coordinator",
            intent_id="bounded", goal="bounded task",
        )
    for worker in ("w1", "w2", "w3"):
        assert store.claim_intent(
            challenge_name="demo", run_id="run-1", worker_id=worker,
            intent_id="bounded", lease_seconds=30, max_attempts=3,
        )
        store._conn.execute(
            "UPDATE intents SET lease_until=0 WHERE intent_id=? AND challenge_name=? AND run_id=?",
            ("bounded", "demo", "run-1"),
        )
        store._conn.commit()
    # run-1 hits max attempts and blocks...
    assert store.claim_intent(
        challenge_name="demo", run_id="run-1", worker_id="w4",
        intent_id="bounded", lease_seconds=30, max_attempts=3,
    ) is None
    run_one = store.list_intents("demo", "run-1", active_only=False)[0]
    assert run_one.status == "blocked"
    # ...while the same intent id in run-2 stays claimable (blocked UPDATE was scoped).
    assert store.claim_intent(
        challenge_name="demo", run_id="run-2", worker_id="w4",
        intent_id="bounded", lease_seconds=30, max_attempts=3,
    ) is not None
    store.close()


def test_intents_table_migrates_to_scoped_pk(tmp_path) -> None:
    import sqlite3 as std_sqlite3

    path = tmp_path / "evidence.sqlite3"
    conn = std_sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE intents (
            intent_id TEXT PRIMARY KEY,
            challenge_name TEXT NOT NULL,
            run_id TEXT NOT NULL,
            goal TEXT NOT NULL,
            acceptance TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            worker_id TEXT,
            lease_until REAL,
            attempt INTEGER NOT NULL DEFAULT 0,
            created_event_id TEXT NOT NULL,
            result_event_id TEXT,
            result TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO intents VALUES
            ('legacy-1', 'demo', 'run-1', 'goal', '', 'open', NULL, NULL, 0, 'evt-1', NULL, ''),
            ('legacy-2', 'demo', 'run-2', 'goal2', '', 'open', NULL, NULL, 0, 'evt-2', NULL, '');
        """
    )
    conn.commit()
    conn.close()

    store = SQLiteEvidenceStore(path)
    row = store._conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='intents'"
    ).fetchone()
    assert "PRIMARY KEY (challenge_name, run_id, intent_id)" in str(row[0])
    rows = store._conn.execute("SELECT * FROM intents").fetchall()
    assert len(rows) == 2
    # The migrated table now allows the same intent_id in another run
    # (impossible under the legacy intent_id-only primary key).
    extra = store.propose_intent(
        challenge_name="demo", run_id="run-2", actor_id="coordinator",
        intent_id="legacy-1", goal="cross-run",
    )
    assert extra.run_id == "run-2" and extra.intent_id == "legacy-1"
    assert len(store.list_intents("demo", "run-2", active_only=False)) == 2
    # Legacy rows are claimable after migration.
    claimed = store.claim_intent(
        challenge_name="demo", run_id="run-1", worker_id="w", intent_id="legacy-1"
    )
    assert claimed is not None and claimed.status == "claimed"
    store.close()
