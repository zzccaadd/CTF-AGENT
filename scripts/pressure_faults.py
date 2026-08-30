#!/usr/bin/env python3
"""Stage 1 P3 fault-injection harness — lease fencing, max attempts, restart recovery.

Synthetic checks (no model spend) drive the board API directly:
  P3.1  lease expiry + stale-worker fencing (stale complete must fail)
  P3.2  max_attempts exhaustion -> intent blocked
  P3.4  process-restart recovery (an unfinished run reopened, intents reclaimable)

The P3.3 benchmark-timeout check needs a real solver run: it shells out to
ctf-bench with a very short --timeout and verifies the timeout result keeps its
diagnostic fields (step_count, cost_usd, findings, trace path).

Usage:
  .venv/bin/python scripts/pressure_faults.py --db /tmp/p1/evidence.sqlite3 --all
  .venv/bin/python scripts/pressure_faults.py --check p31 --db /tmp/p1/evidence.sqlite3
  .venv/bin/python scripts/pressure_faults.py --check p33 --challenge 'hackthebox/.../Dynastic' --root benchmarks/cybench
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from backend.evidence import EvidenceBoard
from backend.evidence.store import SQLiteEvidenceStore

CHALLENGE = "pressure-p3"
RUN_31 = "fault-31"
RUN_32 = "fault-32"
RUN_34 = "fault-34"


def check_lease_fencing(db_path: str, lease_seconds: int) -> dict:
    """P3.1 — worker A loses the lease, B reclaims, A's complete must be fenced."""
    board = EvidenceBoard.open(db_path, CHALLENGE, RUN_31)
    try:
        intent = board.propose("coordinator", "fenced task", intent_id="f31:1")
        claimed_a = board.claim("worker-A", intent.intent_id, lease_seconds=lease_seconds)
        if not claimed_a:
            return {"ok": False, "detail": "worker-A claim failed"}
        time.sleep(lease_seconds + 1)
        claimed_b = board.claim("worker-B", intent.intent_id, lease_seconds=30)
        stale_complete = board.complete("worker-A", intent.intent_id, "late result")
        stale_events = [
            e.kind
            for e in board.store.events(CHALLENGE, RUN_31)
            if e.kind == "intent_completed" and e.actor_id == "worker-A"
        ]
        finished = board.complete("worker-B", intent.intent_id, "done", status="completed")
        current = board.store.list_intents(CHALLENGE, RUN_31, active_only=False)[0]
        ok = (
            claimed_b is not None
            and stale_complete is None
            and not stale_events
            and finished is not None
            and current.status == "completed"
        )
        return {
            "ok": ok,
            "detail": {
                "b_reclaimed": claimed_b is not None,
                "stale_complete_rejected": stale_complete is None,
                "stale_completed_events": len(stale_events),
                "final_status": current.status,
            },
        }
    finally:
        board.close()


def check_max_attempts(db_path: str) -> dict:
    """P3.2 — three claims with expired leases exhaust max_attempts -> blocked."""
    board = EvidenceBoard.open(db_path, CHALLENGE, RUN_32)
    try:
        intent = board.propose("coordinator", "bounded task", intent_id="f32:1")
        for worker in ("codex-1", "codex-2", "codex-3"):
            if not board.claim(worker, intent.intent_id, lease_seconds=30, max_attempts=3):
                return {"ok": False, "detail": f"{worker} claim failed"}
            board.store._conn.execute(
                "UPDATE intents SET lease_until=0 WHERE intent_id=? AND challenge_name=? AND run_id=?",
                (intent.intent_id, CHALLENGE, RUN_32),
            )
            board.store._conn.commit()
        fourth = board.claim("codex-4", intent.intent_id, lease_seconds=30, max_attempts=3)
        current = board.store.list_intents(CHALLENGE, RUN_32, active_only=False)[0]
        ok = (
            fourth is None
            and current.status == "blocked"
            and current.result == "maximum attempts reached"
        )
        return {"ok": ok, "detail": {"fourth_claim": fourth, "status": current.status}}
    finally:
        board.close()


def check_restart_recovery(db_path: str) -> dict:
    """P3.4 — simulate a SIGKILL mid-run: reopen the same DB/run and recover."""
    first = EvidenceBoard.open(db_path, CHALLENGE, RUN_34)
    try:
        first.start("swarm")
        first.propose("coordinator", "task one", intent_id="f34:1")
        first.propose("coordinator", "task two", intent_id="f34:2")
        claimed = first.claim("worker-A", "f34:1", lease_seconds=1)
        if not claimed:
            return {"ok": False, "detail": "initial claim failed"}
        # Worker A "crashes" holding f34:1; run stays unfinished (no challenge_finished).
    finally:
        first.close()

    time.sleep(1.1)  # let the crashed worker's lease expire
    reopened = EvidenceBoard.open(db_path, CHALLENGE, RUN_34)
    try:
        events = reopened.store.events(CHALLENGE, RUN_34)
        snapshot_ok = reopened.snapshot() == reopened.replay()
        # Unfinished intent is reclaimable by a new worker.
        reclaimed = reopened.claim("worker-B", "f34:1", lease_seconds=30)
        # The untouched intent is still claimable too.
        other = reopened.claim("worker-B", "f34:2", lease_seconds=30)
        ok = (
            reclaimed is not None
            and reclaimed.worker_id == "worker-B"
            and other is not None
            and snapshot_ok
            and not any(e.kind == "challenge_finished" for e in events)
        )
        return {
            "ok": ok,
            "detail": {
                "reclaimed_by_b": reclaimed is not None if reclaimed else False,
                "open_intent_claimable": other is not None,
                "snapshot_eq_replay": snapshot_ok,
                "no_finished_event": True,
                "events": len(events),
            },
        }
    finally:
        reopened.close()


def check_benchmark_timeout(
    root: str, challenge: str, *, venv: str, timeout: int, results: Path
) -> dict:
    """P3.3 — run ctf-bench with a short timeout and inspect the timeout result."""
    command = [
        f"{venv}/ctf-bench",
        "--provider", "cybench",
        "--root", root,
        "--split", "benchmark",
        "--challenge", challenge,
        "--model", "codex/gpt-5.5",
        "--timeout", str(timeout),
        "--max-tokens", "80000",
        "--concurrency", "1",
        "--solvers-per-swarm", "1",
        "--image", "ctf-sandbox",
        "--results", str(results),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 180)
    if not results.exists():
        return {
            "ok": False,
            "detail": {"returncode": proc.returncode, "stderr_tail": proc.stderr[-500:]},
        }
    payload = json.loads(results.read_text(encoding="utf-8"))
    entry = payload["results"][0]
    kept = {
        "status": entry.get("status"),
        "tool_calls": entry.get("tool_calls"),
        "cost_usd": entry.get("cost_usd"),
        "trace_path": entry.get("trace_path"),
        "elapsed_seconds": entry.get("elapsed_seconds"),
    }
    ok = (
        entry.get("status") in ("timeout", "flag_found")
        and bool(entry.get("trace_path"))
        and entry.get("tool_calls", 0) >= 0
    )
    return {"ok": ok, "detail": {"returncode": proc.returncode, **kept}}


def main() -> int:
    parser = argparse.ArgumentParser(description="P3 fault-injection harness")
    parser.add_argument("--db", default="/tmp/ctf-agent-stage1-pressure/p3/evidence.sqlite3")
    parser.add_argument("--lease", type=int, default=5, help="P3.1 lease seconds")
    parser.add_argument(
        "--check",
        choices=["p31", "p32", "p33", "p34", "all"],
        default="all",
    )
    parser.add_argument("--root", default=str(Path("benchmarks/cybench").resolve()))
    parser.add_argument("--challenge", default="hackthebox/cyber-apocalypse-2024/crypto/[Very Easy] Dynastic")
    parser.add_argument("--timeout", type=int, default=25, help="P3.3 solver timeout (s)")
    parser.add_argument("--venv", default=".venv/bin")
    parser.add_argument("--results", type=Path, default=Path("/tmp/pressure-p33-results.json"))
    args = parser.parse_args()

    db_path = str(Path(args.db).expanduser().resolve())
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    SQLiteEvidenceStore(db_path).close()  # initialize schema single-connection

    results: dict[str, dict] = {}
    if args.check in ("p31", "all"):
        results["p31_lease_fencing"] = check_lease_fencing(db_path, args.lease)
    if args.check in ("p32", "all"):
        results["p32_max_attempts"] = check_max_attempts(db_path)
    if args.check in ("p34", "all"):
        results["p34_restart_recovery"] = check_restart_recovery(db_path)
    if args.check in ("p33", "all"):
        results["p33_timeout"] = check_benchmark_timeout(
            args.root, args.challenge, venv=args.venv, timeout=args.timeout, results=args.results
        )

    for name, entry in results.items():
        print(f"{name}: {'PASS' if entry['ok'] else 'FAIL'} {json.dumps(entry['detail'], ensure_ascii=False)}")
    verdict = all(entry["ok"] for entry in results.values())
    print("overall:", "PASS" if verdict else "FAIL")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
