#!/usr/bin/env python3
"""Stage 1 P1 pressure harness — SQLite evidence board contention without model spend.

Drives N synthetic intents through M concurrent worker connections with R claim
attempts and K tool events per successfully claimed intent, then verifies the
Stage 1 board contracts (single winner, replay consistency, seq monotonicity,
dedupe idempotency, cross-run scoping, max-attempts blocking) and reports
append/claim/complete latency percentiles.

Rounds (from docs/STAGE1_PRESURE_plan.md, P1 workload table):
  --light   intents=100   workers=3   tool-events=10  claims=300
  --target  intents=1000  workers=9   tool-events=20  claims=3000
  --max     intents=10000 workers=30  tool-events=20  claims=30000

Every worker uses its own SQLiteEvidenceStore connection to exercise real
SQLite lock contention. The schema is initialized once through a single
connection before the worker fan-out, avoiding the ALTER TABLE migration race
described in the pressure plan.

Usage:
  .venv/bin/python scripts/pressure_board.py --target \
      --db /tmp/ctf-agent-stage1-pressure/p1/evidence.sqlite3
  .venv/bin/python scripts/pressure_board.py --intents 200 --workers 4 \
      --tool-events 10 --claims 500 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from backend.evidence import EvidenceBoard

CHALLENGE = "pressure-p1"
LOAD_RUN_PREFIX = "load"  # main-load run id prefix, suffixed per round
RACE_RUN = "race"
CROSS_RUNS = ("cross-1", "cross-2")
ATTEMPTS_RUN = "attempts"

PRESETS = {
    "light": {"intents": 100, "workers": 3, "tool_events": 10, "claims": 300},
    "target": {"intents": 1000, "workers": 9, "tool_events": 20, "claims": 3000},
    "max": {"intents": 10000, "workers": 30, "tool_events": 20, "claims": 30000},
}


@dataclass
class LoadStats:
    """Per-worker counters and latency samples (ns). Not shared between threads."""

    attempts: int = 0
    succeeded: int = 0
    failed: int = 0
    append: list[int] = field(default_factory=list)
    claim: list[int] = field(default_factory=list)
    complete: list[int] = field(default_factory=list)
    locked_errors: int = 0
    exceptions: list[str] = field(default_factory=list)


def _run_worker(
    worker_id: int,
    db_path: str,
    run_id: str,
    tool_events: int,
    claim_quota: int,
    n_intents: int,
    rng: random.Random,
    stats: LoadStats,
) -> None:
    """Claim intents, record tool events, complete — one connection per worker."""
    board = EvidenceBoard.open(db_path, CHALLENGE, run_id)
    try:
        for _ in range(claim_quota):
            try:
                open_intents = board.list_open_intents()
                if open_intents:
                    target = rng.choice(open_intents).intent_id
                else:
                    # Everything is terminal: hit a random intent to exercise the
                    # repeated-claim rejection path.
                    target = f"pressure:{run_id}:{rng.randrange(n_intents):05d}"
                t0 = time.perf_counter_ns()
                claimed = board.claim(worker_id, target, lease_seconds=30)
                stats.claim.append(time.perf_counter_ns() - t0)
                if not claimed:
                    stats.failed += 1
                    stats.attempts += 1
                    continue
                stats.succeeded += 1
                stats.attempts += 1
                for step in range(tool_events):
                    kind = "tool_call" if step % 2 == 0 else "tool_result"
                    t1 = time.perf_counter_ns()
                    board.record(
                        worker_id,
                        "worker",
                        kind,
                        {"intent_id": target, "step": step},
                        provenance={
                            "source_kind": "trace",
                            "source_excerpt": f"synthetic step {step}",
                        },
                    )
                    stats.append.append(time.perf_counter_ns() - t1)
                t2 = time.perf_counter_ns()
                board.complete(worker_id, target, "done", status="completed")
                stats.complete.append(time.perf_counter_ns() - t2)
            except Exception as exc:  # noqa: BLE001 - harness must not die on one worker
                message = f"{type(exc).__name__}: {exc}"
                if "database is locked" in str(exc):
                    stats.locked_errors += 1
                stats.exceptions.append(f"worker-{worker_id}: {message}")
    finally:
        board.close()


def _merge_stats(worker_stats: list[LoadStats]) -> LoadStats:
    merged = LoadStats()
    for stats in worker_stats:
        merged.attempts += stats.attempts
        merged.succeeded += stats.succeeded
        merged.failed += stats.failed
        merged.locked_errors += stats.locked_errors
        merged.exceptions.extend(stats.exceptions)
        merged.append.extend(stats.append)
        merged.claim.extend(stats.claim)
        merged.complete.extend(stats.complete)
    return merged


def _percentile(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    index = min(len(sorted_vals) - 1, int(p / 100 * (len(sorted_vals) - 1)))
    return sorted_vals[index]


def _latency_summary(values: list[int]) -> dict:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": round(_percentile(ordered, 50) / 1_000_000, 3),
        "p95_ms": round(_percentile(ordered, 95) / 1_000_000, 3),
        "max_ms": round(ordered[-1] / 1_000_000, 3) if ordered else 0,
    }


def run_main_load(
    db_path: str,
    *,
    intents: int,
    workers: int,
    tool_events: int,
    claims: int,
    run_id: str,
    seed: int,
) -> tuple[LoadStats, dict]:
    """Phase 0: single-connection schema init + propose; Phase 1: concurrent workers."""
    # Phase 0 — one connection only, so the ALTER TABLE migration race cannot fire.
    init_board = EvidenceBoard.open(db_path, CHALLENGE, run_id)
    try:
        # Intent ids embed the run id (production pattern): the intents
        # projection PK is intent_id alone, so unscoped ids would silently
        # collide across runs (INSERT OR IGNORE hides the collision).
        for index in range(intents):
            init_board.propose(
                "coordinator",
                f"synthetic task {index}",
                intent_id=f"pressure:{run_id}:{index:05d}",
            )
    finally:
        init_board.close()

    # Phase 1 — M independent connections, real SQLite write contention.
    baseline_threads = threading.active_count()
    quota = claims // workers
    remainder = claims % workers
    worker_stats: list[LoadStats] = []
    threads: list[threading.Thread] = []
    for worker_id in range(workers):
        stats = LoadStats()
        worker_stats.append(stats)
        threads.append(
            threading.Thread(
                target=_run_worker,
                args=(
                    worker_id,
                    db_path,
                    run_id,
                    tool_events,
                    quota + (1 if worker_id < remainder else 0),
                    intents,
                    random.Random(seed + worker_id * 7919),
                    stats,
                ),
                name=f"p1-worker-{worker_id}",
            )
        )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # No leaked worker threads: active count must return to the baseline.
    threads_joined = threading.active_count() == baseline_threads
    merged = _merge_stats(worker_stats)
    checks = verify_main_load(db_path, run_id, intents, tool_events, merged)
    checks["threads_joined"] = bool(threads_joined)
    return merged, checks


def verify_main_load(
    db_path: str,
    run_id: str,
    intents: int,
    tool_events: int,
    stats: LoadStats,
) -> dict:
    """Verify the Stage 1 board contracts on the main-load run."""
    board = EvidenceBoard.open(db_path, CHALLENGE, run_id)
    try:
        events = board.store.events(CHALLENGE, run_id)
        proposed = sum(1 for e in events if e.kind == "intent_proposed")
        claimed = sum(1 for e in events if e.kind == "intent_claimed")
        completed = sum(1 for e in events if e.kind == "intent_completed")
        tool_events_seen = sum(1 for e in events if e.kind in ("tool_call", "tool_result"))

        seq_ok = all(b.seq > a.seq for a, b in pairwise(events))
        claimed_per_intent = Counter(
            e.payload.get("intent_id", "") for e in events if e.kind == "intent_claimed"
        )
        single_winner_ok = all(count <= 1 for count in claimed_per_intent.values())
        counts_ok = (
            proposed == intents
            and claimed == completed
            and claimed == stats.succeeded
            and tool_events_seen == stats.succeeded * tool_events
        )
        snapshot_ok = board.snapshot() == board.replay()
        intents_projection = board.store.list_intents(CHALLENGE, run_id, active_only=False)
        residual_claimed = [
            intent.intent_id for intent in intents_projection if intent.status == "claimed"
        ]
        no_half_written_ok = not residual_claimed
        return {
            "seq_strictly_increasing": bool(seq_ok),
            "single_winner": bool(single_winner_ok),
            "event_counts_match": bool(counts_ok),
            "snapshot_eq_replay": bool(snapshot_ok),
            "no_half_written_intents": bool(no_half_written_ok),
            "events_total": len(events),
            "max_claims_per_intent": max(claimed_per_intent.values(), default=0),
            "residual_claimed_intents": len(residual_claimed),
        }
    finally:
        board.close()


def check_dedupe_race(db_path: str, workers: int) -> tuple[bool, int]:
    """Concurrent writers with the same dedupe_key must yield exactly one event."""
    n = min(16, max(2, workers))
    barrier = threading.Barrier(n)
    results: list[int] = []
    errors: list[str] = []

    def writer(index: int) -> None:
        board = EvidenceBoard.open(db_path, CHALLENGE, RACE_RUN)
        try:
            barrier.wait()
            board.record(
                f"racer-{index}",
                "worker",
                "fact_added",
                {"fact": "same"},
                dedupe_key="race-key",
            )
            results.append(
                len(board.store.events(CHALLENGE, RACE_RUN, kinds=["fact_added"]))
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            board.close()

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    count = max(results) if results else 0
    return count == 1 and not errors, count


def check_cross_run_dedupe(db_path: str) -> tuple[bool, str, str]:
    """The same caller-supplied dedupe_key must not leak across challenge runs."""
    first = EvidenceBoard.open(db_path, CHALLENGE, CROSS_RUNS[0])
    second = EvidenceBoard.open(db_path, CHALLENGE, CROSS_RUNS[1])
    try:
        event_one = first.record("worker", "worker", "fact_added", {"fact": "x"}, dedupe_key="shared-key")
        event_two = second.record("worker", "worker", "fact_added", {"fact": "x"}, dedupe_key="shared-key")
        return event_one.event_id != event_two.event_id, event_one.event_id, event_two.event_id
    finally:
        first.close()
        second.close()


def check_max_attempts(db_path: str) -> tuple[bool, str]:
    """After max_attempts exhausted claims, the intent must be blocked."""
    board = EvidenceBoard.open(db_path, CHALLENGE, ATTEMPTS_RUN)
    try:
        intent = board.propose("coordinator", "bounded task", intent_id="attempts:1")
        for worker in ("codex-1", "codex-2", "codex-3"):
            assert board.claim(worker, intent.intent_id, lease_seconds=30, max_attempts=3)
            board.store._conn.execute(
                "UPDATE intents SET lease_until=0 WHERE intent_id=?", (intent.intent_id,)
            )
            board.store._conn.commit()
        late = board.claim("codex-4", intent.intent_id, lease_seconds=30, max_attempts=3)
        current = board.store.list_intents(CHALLENGE, ATTEMPTS_RUN, active_only=False)[0]
        ok = (
            late is None
            and current.status == "blocked"
            and current.result == "maximum attempts reached"
        )
        return ok, current.status
    finally:
        board.close()


def _file_sizes(db_path: str) -> dict:
    sizes: dict[str, int] = {}
    for candidate in (db_path, db_path + "-wal"):
        path = Path(candidate)
        sizes[candidate.rsplit("/", 1)[-1]] = path.stat().st_size if path.exists() else 0
    return sizes


def run_round(config: dict, db_path: str, round_index: int, seed: int) -> dict:
    run_id = f"{LOAD_RUN_PREFIX}-{round_index}"
    stats, checks = run_main_load(
        db_path,
        intents=int(config["intents"]),
        workers=int(config["workers"]),
        tool_events=int(config["tool_events"]),
        claims=int(config["claims"]),
        run_id=run_id,
        seed=seed,
    )
    # Only boolean contract fields participate in the verdict; the numeric
    # informational fields (events_total, max_claims_per_intent, ...) must not.
    bool_checks = {key: value for key, value in checks.items() if isinstance(value, bool)}
    load_ok = (
        all(bool_checks.values())
        and stats.locked_errors == 0
        and not stats.exceptions
    )
    return {
        "config": {
            **config,
            "round": round_index,
            "seed": seed,
            "db": db_path,
            "run_id": run_id,
        },
        "stats": {
            "attempts": stats.attempts,
            "succeeded": stats.succeeded,
            "failed": stats.failed,
            "success_rate": round(stats.succeeded / stats.attempts, 4) if stats.attempts else 0,
            "locked_errors": stats.locked_errors,
            "uncaught_errors": len(stats.exceptions),
            "append": _latency_summary(stats.append),
            "claim": _latency_summary(stats.claim),
            "complete": _latency_summary(stats.complete),
        },
        "checks": checks,
        "db_sizes": _file_sizes(db_path),
        "verdict": "PASS" if load_ok else "FAIL",
    }


def run_contract_checks(db_path: str, workers: int) -> dict:
    """Contract checks that must run exactly once per invocation — their run ids
    and intent ids are fixed, so repeating them across rounds is not idempotent."""
    race_ok, race_count = check_dedupe_race(db_path, workers)
    cross_ok, cross_one, cross_two = check_cross_run_dedupe(db_path)
    attempts_ok, attempts_status = check_max_attempts(db_path)
    return {
        "dedupe_race_single_event": race_ok,
        "dedupe_cross_run_scoped": cross_ok,
        "max_attempts_blocked": attempts_ok,
        "detail": {
            "dedupe_race_count": race_count,
            "cross_run_event_ids": [cross_one, cross_two],
            "attempts_status": attempts_status,
        },
    }


def build_config(args: argparse.Namespace) -> dict:
    preset = PRESETS[args.preset] if args.preset else {}
    return {
        "intents": args.intents if args.intents is not None else preset.get("intents", PRESETS["target"]["intents"]),
        "workers": args.workers if args.workers is not None else preset.get("workers", PRESETS["target"]["workers"]),
        "tool_events": args.tool_events if args.tool_events is not None else preset.get("tool_events", PRESETS["target"]["tool_events"]),
        "claims": args.claims if args.claims is not None else preset.get("claims", PRESETS["target"]["claims"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="P1 blackboard contention harness")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--light", dest="preset", action="store_const", const="light")
    group.add_argument("--target", dest="preset", action="store_const", const="target")
    group.add_argument("--max", dest="preset", action="store_const", const="max")
    parser.add_argument("--intents", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--tool-events", type=int, default=None)
    parser.add_argument("--claims", type=int, default=None)
    parser.add_argument(
        "--db",
        default="/tmp/ctf-agent-stage1-pressure/p1/evidence.sqlite3",
        help="temporary SQLite WAL database (default: /tmp/.../p1/evidence.sqlite3)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rounds", type=int, default=1, help="repeat the main load with fresh run ids")
    parser.add_argument("--json-out", type=Path, default=None, help="write the report as JSON")
    args = parser.parse_args()

    db_path = str(Path(args.db).expanduser().resolve())
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    config = build_config(args)

    rounds: list[dict] = []
    for index in range(max(1, args.rounds)):
        rounds.append(run_round(config, db_path, index + 1, args.seed))

    contracts = run_contract_checks(db_path, int(config["workers"]))
    verdicts = [report["verdict"] for report in rounds]
    contracts_ok = all(
        contracts[key]
        for key in ("dedupe_race_single_event", "dedupe_cross_run_scoped", "max_attempts_blocked")
    )
    overall = "PASS" if all(v == "PASS" for v in verdicts) and contracts_ok else "FAIL"
    report = {"overall": overall, "contracts": contracts, "rounds": rounds}
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    for index, single in enumerate(rounds, 1):
        print(f"=== P1 round {index} ===")
        print("config:", single["config"])
        print("stats:", json.dumps(single["stats"], ensure_ascii=False))
        print("checks:", json.dumps(single["checks"], ensure_ascii=False))
        print("db_sizes:", single["db_sizes"])
        print("verdict:", single["verdict"])
    print("contracts:", json.dumps(contracts, ensure_ascii=False))
    print("overall:", overall)
    if args.json_out:
        print("report written to:", args.json_out)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
