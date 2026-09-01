"""Swarm parallelism fixes: per-slot seed intents + intent wait-before-giveup.

Regression coverage for the v4 finding that a single seed intent left all but
one solver with nothing to claim → 0-step gave_up traces and a silently
degraded "3-solver" swarm.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from backend.agents.swarm import ChallengeSwarm


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        evidence_db_path=":memory:",
        coordinator_enabled=False,
        coordinator_model="gpt-5.5",
        coordinator_turn_timeout_s=120,
        knowledge_challenge_budget=24,
        max_solvers_per_swarm=3,
    )


def _swarm(max_solvers: int = 3, solvers_per_model: int = 3) -> ChallengeSwarm:
    swarm = object.__new__(ChallengeSwarm)
    swarm.meta = SimpleNamespace(name="seed-test")
    swarm.run_id = ""
    swarm.settings = _settings()
    swarm.max_solvers = max_solvers
    swarm.solvers_per_model = solvers_per_model
    swarm.model_specs = ["codex/gpt-5.5"]
    swarm.coordinator_inbox = None
    swarm.message_bus = SimpleNamespace(attach_board=lambda board: None)
    swarm.__post_init__()
    return swarm


def test_seed_intent_per_solver_slot() -> None:
    """Every parallel solver gets its own non-overlapping seed intent."""
    swarm = _swarm(max_solvers=3, solvers_per_model=3)
    assert swarm.evidence_board is not None
    seeds = [
        i for i in swarm.evidence_board.open_intents()
        if i.intent_id.startswith("bootstrap:")
    ]
    assert len(seeds) == 3
    goals = {i.goal for i in seeds}
    assert len(goals) == 3, "seed goals must be distinct so workers do not duplicate work"
    swarm.evidence_board.close()


def test_single_solver_gets_single_seed() -> None:
    """solvers_per_swarm=1 keeps the old single-seed behaviour."""
    swarm = _swarm(max_solvers=1, solvers_per_model=1)
    seeds = [
        i for i in swarm.evidence_board.open_intents()
        if i.intent_id.startswith("bootstrap:")
    ]
    assert len(seeds) == 1
    swarm.evidence_board.close()


def test_run_id_is_fresh_every_swarm() -> None:
    """No reuse of the last unfinished run (v4: stale intents from an 8/31
    demo run leaked into the 9/1 run via EvidenceBoard.open fallback)."""
    first = _swarm()
    second = _swarm()
    assert first.run_id and second.run_id
    assert first.run_id != second.run_id
    first.evidence_board.close()
    second.evidence_board.close()


def test_wait_for_open_intent_polls_until_claimable() -> None:
    """A worker with nothing open waits for a follow-up intent instead of
    exiting with 0 steps."""
    from backend.agents.codex_solver import CodexSolver

    solver = object.__new__(CodexSolver)
    solver.settings = SimpleNamespace(blackboard_intent_wait_seconds=30)
    solver.tracer = SimpleNamespace(event=lambda *a, **k: None)

    class Board:
        def __init__(self) -> None:
            self.calls = 0

        def open_intents(self) -> list[Any]:
            return ["intent-1"]

    board = Board()
    solver.evidence_board = board

    claimed: list[str] = []

    def fake_claim() -> str:
        board.calls += 1
        if board.calls == 1:
            return ""  # first poll: nothing claimable
        claimed.append("intent-1")
        return "intent-1"

    solver._claim_next_intent = fake_claim  # type: ignore[method-assign]

    async def fake_sleep(_: float) -> None:
        return None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("backend.agents.codex_solver.asyncio.sleep", fake_sleep)
        result = asyncio.run(solver._wait_for_open_intent())

    assert result == "intent-1"
    assert board.calls == 2


def test_wait_for_open_intent_gives_up_after_budget() -> None:
    from backend.agents.codex_solver import CodexSolver

    solver = object.__new__(CodexSolver)
    solver.settings = SimpleNamespace(blackboard_intent_wait_seconds=1)
    solver.tracer = SimpleNamespace(event=lambda *a, **k: None)
    solver.evidence_board = SimpleNamespace(open_intents=lambda: [])

    def fake_claim() -> str:
        return ""

    solver._claim_next_intent = fake_claim  # type: ignore[method-assign]

    async def fake_sleep(_: float) -> None:
        return None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("backend.agents.codex_solver.asyncio.sleep", fake_sleep)
        result = asyncio.run(solver._wait_for_open_intent())

    assert result == ""


def test_run_solver_loops_after_gave_up_to_claim_next_intent() -> None:
    """A worker that finished one intent (GAVE_UP) must loop back and claim
    the next follow-up intent instead of exiting — otherwise follow-up and
    coordinator-proposed intents are never executed (regression from the
    bump-loop removal)."""
    from backend.agents.swarm import ChallengeSwarm
    from backend.solver_base import FLAG_FOUND, GAVE_UP, SolverResult

    swarm = object.__new__(ChallengeSwarm)
    swarm.meta = SimpleNamespace(name="loop-test")
    swarm.settings = _settings()
    swarm.cancel_event = asyncio.Event()
    swarm.findings = {}
    swarm.message_bus = SimpleNamespace(post=lambda *a, **k: asyncio.sleep(0))
    swarm.evidence_board = None  # no board → no hypothesis recording
    swarm.winner = None
    swarm.confirmed_flag = None
    swarm._flag_winner_label = ""
    swarm._next_intent_index = 4

    calls = {"n": 0}

    class FakeSolver:
        intent_id = None
        sandbox = None

        async def start(self) -> None:
            return None

        async def run_until_done_or_gave_up(self) -> SolverResult:
            calls["n"] += 1
            if calls["n"] == 1:
                return SolverResult(
                    flag=None, status=GAVE_UP, findings_summary="checked files",
                    step_count=5, cost_usd=0.1, log_path="",
                )
            return SolverResult(
                flag="FLAG{ok}", status=FLAG_FOUND, findings_summary="found",
                step_count=6, cost_usd=0.2, log_path="",
            )

    async def fake_ensure(source: str) -> None:
        return None

    swarm._ensure_followup_intent = fake_ensure  # type: ignore[method-assign]

    async def main() -> None:
        result, _solver = await swarm._run_solver_loop(FakeSolver(), "codex/gpt-5.5", "#1")
        assert result.status == FLAG_FOUND
        assert calls["n"] == 2, "solver must run a second round after GAVE_UP"

    asyncio.run(main())


def test_plan_with_retry_retries_empty_plan() -> None:
    """Empty (no raw) plans are retried up to the configured budget; a plan
    with content returns immediately; repeated empties give up after budget."""
    from backend.agents.coordinator import CoordinatorPlan
    from backend.agents.swarm import ChallengeSwarm

    swarm = object.__new__(ChallengeSwarm)
    swarm.meta = SimpleNamespace(name="retry-test")
    swarm.settings = SimpleNamespace(coordinator_plan_retries=2)

    class Planner:
        def __init__(self, results: list[object]) -> None:
            self.results = results
            self.calls = 0

        async def plan(self, summary: str) -> object:
            self.calls += 1
            return self.results.pop(0)

    # first two empty → retried, third has content → returned
    swarm.coordinator = Planner([CoordinatorPlan(raw=""), CoordinatorPlan(raw=""), CoordinatorPlan(raw="json")])
    plan = asyncio.run(swarm._plan_with_retry("summary"))
    assert plan.raw == "json"
    assert swarm.coordinator.calls == 3

    # all empty → stops after budget (retries + 1 initial call)
    swarm.coordinator = Planner([CoordinatorPlan(raw=""), CoordinatorPlan(raw=""), CoordinatorPlan(raw="")])
    plan = asyncio.run(swarm._plan_with_retry("summary"))
    assert plan.raw == ""
    assert swarm.coordinator.calls == 3

    # content on first attempt → single call, no retry
    swarm.coordinator = Planner([CoordinatorPlan(raw="ok")])
    plan = asyncio.run(swarm._plan_with_retry("summary"))
    assert plan.raw == "ok"
    assert swarm.coordinator.calls == 1


def test_run_solver_loop_stops_when_no_new_work_after_gave_up() -> None:
    """GAVE_UP with no new steps (intent-wait timeout) must stop the worker —
    otherwise it spins forever re-waiting for intents that never appear."""
    from backend.agents.swarm import ChallengeSwarm
    from backend.solver_base import GAVE_UP, SolverResult

    swarm = object.__new__(ChallengeSwarm)
    swarm.meta = SimpleNamespace(name="loop-stop-test")
    swarm.settings = _settings()
    swarm.cancel_event = asyncio.Event()
    swarm.findings = {}
    swarm.message_bus = SimpleNamespace(post=lambda *a, **k: asyncio.sleep(0))
    swarm.evidence_board = None
    swarm.winner = None
    swarm.confirmed_flag = None
    swarm._flag_winner_label = ""
    swarm._next_intent_index = 4

    calls = {"n": 0}

    class StuckSolver:
        intent_id = None
        sandbox = None

        async def start(self) -> None:
            return None

        async def run_until_done_or_gave_up(self) -> SolverResult:
            calls["n"] += 1
            return SolverResult(
                flag=None, status=GAVE_UP, findings_summary="checked files",
                step_count=5, cost_usd=0.1, log_path="",
            )

    async def fake_ensure(source: str) -> None:
        return None

    swarm._ensure_followup_intent = fake_ensure  # type: ignore[method-assign]

    async def main() -> None:
        result, _solver = await swarm._run_solver_loop(StuckSolver(), "codex/gpt-5.5", "#1")
        assert result.status == GAVE_UP
        # round 1 did work (continue), round 2 had no new steps → stop, not spin.
        assert calls["n"] == 2

    asyncio.run(main())
