from __future__ import annotations

import asyncio
import threading
import time

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
