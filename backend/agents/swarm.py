"""ChallengeSwarm — Parallel solvers racing on one challenge."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from backend.agents.solver import Solver
from backend.cost_tracker import CostTracker
from backend.message_bus import ChallengeMessageBus
from backend.models import DEFAULT_MODELS, provider_from_spec
from backend.prompts import ChallengeMeta
from backend.solver_base import (
    CANCELLED,
    ERROR,
    FLAG_FOUND,
    GAVE_UP,
    QUOTA_ERROR,
    SolverProtocol,
    SolverResult,
)
from backend.submission import FlagSubmitter

if TYPE_CHECKING:
    from backend.config import Settings

logger = logging.getLogger(__name__)


# Quota fallback: map subscription-backed providers to API-backed equivalents
QUOTA_FALLBACK: dict[str, str] = {
    "claude-sdk/claude-opus-4-6": "bedrock/us.anthropic.claude-opus-4-6-v1",
    "codex/gpt-5.4": "azure/gpt-5.4",
    "codex/gpt-5.4-mini": "azure/gpt-5.4-mini",
    "codex/gpt-5.3-codex-spark": "zen/gpt-5.3-codex-spark",
}


def _quota_fallback_spec(model_spec: str) -> str | None:
    return QUOTA_FALLBACK.get(model_spec)


@dataclass(frozen=True)
class SolverSlot:
    label: str
    model_spec: str


def build_solver_slots(
    model_specs: list[str],
    *,
    solvers_per_model: int = 1,
    max_solvers: int = 5,
) -> list[SolverSlot]:
    """Expand model specs into uniquely labelled solver slots."""
    replicas = max(1, solvers_per_model)
    limit = max(1, max_solvers)
    expanded = [
        spec
        for spec in model_specs
        for _ in range(replicas)
    ][:limit]
    totals = Counter(expanded)
    seen: defaultdict[str, int] = defaultdict(int)
    slots: list[SolverSlot] = []
    for spec in expanded:
        seen[spec] += 1
        label = spec if totals[spec] == 1 else f"{spec}#{seen[spec]}"
        slots.append(SolverSlot(label=label, model_spec=spec))
    return slots


@dataclass
class ChallengeSwarm:
    """Parallel solvers racing on one challenge."""

    challenge_dir: str
    meta: ChallengeMeta
    ctfd: FlagSubmitter
    cost_tracker: CostTracker
    settings: Settings
    model_specs: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))
    solvers_per_model: int = 1
    max_solvers: int = 5
    no_submit: bool = False
    coordinator_inbox: asyncio.Queue | None = None

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    solvers: dict[str, SolverProtocol] = field(default_factory=dict)
    findings: dict[str, str] = field(default_factory=dict)
    winner: SolverResult | None = None
    confirmed_flag: str | None = None
    _flag_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _submit_count: dict[str, int] = field(default_factory=dict)  # per-solver wrong submission count
    _submitted_flags: set[str] = field(default_factory=set)  # dedup exact flags
    _last_submit_time: dict[str, float] = field(default_factory=dict)  # per-solver last submit timestamp
    message_bus: ChallengeMessageBus = field(default_factory=ChallengeMessageBus)

    def _solver_slots(self) -> list[SolverSlot]:
        max_solvers = min(self.max_solvers, getattr(self.settings, "max_solvers_per_swarm", self.max_solvers))
        return build_solver_slots(
            self.model_specs,
            solvers_per_model=self.solvers_per_model,
            max_solvers=max_solvers,
        )

    def _create_solver(self, model_spec: str, solver_label: str):
        """Create the right solver type based on provider.

        - claude-sdk/* → ClaudeSolver (Claude Agent SDK, subscription-first)
        - codex/* → CodexSolver (Codex App Server, subscription-first)
        - bedrock/*, azure/*, zen/*, google/* → Pydantic AI Solver (API)
        """
        provider = provider_from_spec(model_spec)

        def _submit_fn(flag): return self.try_submit_flag(flag, solver_label)
        _notify = self._make_notify_fn(solver_label)

        if provider == "claude-sdk":
            from backend.agents.claude_solver import ClaudeSolver
            return ClaudeSolver(
                model_spec=model_spec,
                challenge_dir=self.challenge_dir,
                meta=self.meta,
                ctfd=self.ctfd,
                cost_tracker=self.cost_tracker,
                settings=self.settings,
                cancel_event=self.cancel_event,
                no_submit=self.no_submit,
                submit_fn=_submit_fn,
                message_bus=self.message_bus,
                notify_coordinator=_notify,
                solver_label=solver_label,
            )

        if provider == "codex":
            from backend.agents.codex_solver import CodexSolver
            return CodexSolver(
                model_spec=model_spec,
                challenge_dir=self.challenge_dir,
                meta=self.meta,
                ctfd=self.ctfd,
                cost_tracker=self.cost_tracker,
                settings=self.settings,
                cancel_event=self.cancel_event,
                no_submit=self.no_submit,
                submit_fn=_submit_fn,
                message_bus=self.message_bus,
                notify_coordinator=_notify,
                solver_label=solver_label,
            )

        return self._create_pydantic_solver(model_spec, solver_label=solver_label)

    def _make_notify_fn(self, solver_label: str):
        """Create a callback that pushes solver messages to the coordinator inbox."""
        async def _notify(message: str) -> None:
            if self.coordinator_inbox:
                self.coordinator_inbox.put_nowait(
                    f"[{self.meta.name}/{solver_label}] {message}"
                )
        return _notify

    def _create_pydantic_solver(
        self,
        model_spec: str,
        *,
        solver_label: str,
        sandbox=None,
        owns_sandbox: bool | None = None,
    ) -> Solver:
        """Create a Pydantic AI solver. Pass sandbox to reuse an existing container (quota fallback)."""
        solver = Solver(
            model_spec=model_spec,
            challenge_dir=self.challenge_dir,
            meta=self.meta,
            ctfd=self.ctfd,
            cost_tracker=self.cost_tracker,
            settings=self.settings,
            cancel_event=self.cancel_event,
            sandbox=sandbox,
            owns_sandbox=owns_sandbox,
            solver_label=solver_label,
        )
        solver.deps.message_bus = self.message_bus
        solver.deps.model_spec = solver_label
        solver.deps.no_submit = self.no_submit
        solver.deps.submit_fn = lambda flag: self.try_submit_flag(flag, solver_label)
        solver.deps.notify_coordinator = self._make_notify_fn(solver_label)
        return solver

    def _gather_sibling_insights(self, exclude_label: str) -> str:
        parts: list[str] = []
        for label, finding in self.findings.items():
            if label != exclude_label and finding:
                parts.append(f"[{label}]: {finding}")
        return "\n\n".join(parts) if parts else "No sibling insights available yet."

    # Escalating cooldowns after incorrect submissions (per solver)
    SUBMISSION_COOLDOWNS = [0, 30, 120, 300, 600]  # 0s, 30s, 2min, 5min, 10min

    async def try_submit_flag(self, flag: str, solver_label: str) -> tuple[str, bool]:
        """Cooldown-gated, deduplicated flag submission. Returns (display, is_confirmed)."""
        async with self._flag_lock:
            if self.confirmed_flag:
                return f"ALREADY SOLVED — flag already confirmed: {self.confirmed_flag}", True

            normalized = flag.strip()

            # Dedup exact flags across all models
            if normalized in self._submitted_flags:
                return "INCORRECT — already tried this exact flag.", False

            # Escalating cooldown after incorrect submissions
            wrong_count = self._submit_count.get(solver_label, 0)
            cooldown_idx = min(wrong_count, len(self.SUBMISSION_COOLDOWNS) - 1)
            cooldown = self.SUBMISSION_COOLDOWNS[cooldown_idx]
            if cooldown > 0:
                last_time = self._last_submit_time.get(solver_label, 0)
                elapsed = time.monotonic() - last_time
                if elapsed < cooldown:
                    remaining = int(cooldown - elapsed)
                    return (
                        f"COOLDOWN — wait {remaining}s before submitting again. "
                        f"You have {wrong_count} incorrect submissions. "
                        "Use this time to do deeper analysis and verify your flag.",
                        False,
                    )

            self._submitted_flags.add(normalized)

            from backend.tools.core import do_submit_flag
            display, is_confirmed = await do_submit_flag(self.ctfd, self.meta.name, flag)
            if is_confirmed:
                self.confirmed_flag = normalized
            else:
                self._submit_count[solver_label] = wrong_count + 1
                self._last_submit_time[solver_label] = time.monotonic()
            return display, is_confirmed

    async def _run_solver(self, slot: SolverSlot) -> SolverResult | None:
        solver = self._create_solver(slot.model_spec, slot.label)
        self.solvers[slot.label] = solver

        try:
            result, final_solver = await self._run_solver_loop(solver, slot.model_spec, slot.label)
            solver = final_solver
            return result
        except Exception as e:
            logger.error(f"[{self.meta.name}/{slot.label}] Fatal: {e}", exc_info=True)
            return None
        finally:
            await solver.stop()

    async def _run_solver_loop(
        self,
        solver,
        model_spec: str,
        solver_label: str,
    ) -> tuple[SolverResult, SolverProtocol]:
        """Inner loop: start → run → bump → run → ..."""
        bump_count = 0
        consecutive_errors = 0
        result = SolverResult(
            flag=None, status=CANCELLED, findings_summary="",
            step_count=0, cost_usd=0.0, log_path="",
        )
        await solver.start()

        while not self.cancel_event.is_set():
            result = await solver.run_until_done_or_gave_up()

            # Only broadcast useful findings — skip errors and broken solvers
            if (result.status not in (ERROR, QUOTA_ERROR)
                    and not (result.step_count == 0 and result.cost_usd == 0)
                    and result.findings_summary
                    and not result.findings_summary.startswith(("Error:", "Turn failed:"))):
                self.findings[solver_label] = result.findings_summary
                await self.message_bus.post(solver_label, result.findings_summary[:500])

            if result.status == FLAG_FOUND:
                self.cancel_event.set()
                self.winner = result
                logger.info(
                    f"[{self.meta.name}] Flag found by {solver_label}: {result.flag}"
                )
                return result, solver

            if result.status == CANCELLED:
                break

            # Quota exhaustion: fall back to API-backed Pydantic AI solver
            if result.status == QUOTA_ERROR:
                fallback_spec = _quota_fallback_spec(model_spec)
                if fallback_spec:
                    logger.warning(
                            f"[{self.meta.name}/{solver_label}] Quota exhausted — falling back to {fallback_spec}"
                        )
                    existing_sandbox = solver.sandbox
                    # Detach sandbox from old solver so stop() doesn't destroy it
                    cast(Any, solver).sandbox = None
                    await solver.stop()
                    solver = self._create_pydantic_solver(
                        fallback_spec,
                        solver_label=solver_label,
                        sandbox=existing_sandbox,
                        owns_sandbox=True,
                    )
                    model_spec = fallback_spec
                    self.solvers[solver_label] = solver
                    await solver.start()
                    continue
                # No fallback available, treat as error
                break

            if result.status in (GAVE_UP, ERROR):
                if result.step_count == 0 and result.cost_usd == 0:
                    logger.warning(
                            f"[{self.meta.name}/{solver_label}] Broken (0 steps, $0) — not bumping"
                        )
                    break

                # Track consecutive errors — stop after 3 in a row
                if result.status == ERROR:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        logger.warning(
                            f"[{self.meta.name}/{solver_label}] {consecutive_errors} consecutive errors — giving up"
                        )
                        break
                else:
                    consecutive_errors = 0

                bump_count += 1
                # Cooldown between bumps — check cancellation during wait
                try:
                    await asyncio.wait_for(
                        self.cancel_event.wait(),
                        timeout=min(bump_count * 30, 300),
                    )
                    break  # cancelled during cooldown
                except TimeoutError:
                    pass  # cooldown elapsed, proceed with bump
                insights = self._gather_sibling_insights(solver_label)
                solver.bump(insights)
                logger.info(
                    f"[{self.meta.name}/{solver_label}] Bumped ({bump_count}), resuming"
                )
                continue

        return result, solver

    async def run(self) -> SolverResult | None:
        """Run all solvers in parallel. Returns the winner's result or None."""
        tasks = [
            asyncio.create_task(self._run_solver(slot), name=f"solver-{slot.label}")
            for slot in self._solver_slots()
        ]

        try:
            while tasks:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                for task in done:
                    try:
                        result = task.result()
                    except Exception:
                        continue
                    if result and result.status == FLAG_FOUND:
                        self.cancel_event.set()
                        for p in pending:
                            p.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        return result

                tasks = list(pending)

            self.cancel_event.set()
            return self.winner
        except asyncio.CancelledError:
            self.cancel_event.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        except Exception as e:
            logger.error(f"[{self.meta.name}] Swarm error: {e}", exc_info=True)
            self.cancel_event.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return None

    def kill(self) -> None:
        """Cancel all agents for this challenge."""
        self.cancel_event.set()

    def get_status(self) -> dict:
        """Get per-agent progress and findings."""
        return {
            "challenge": self.meta.name,
            "cancelled": self.cancel_event.is_set(),
            "winner": self.winner.flag if self.winner else None,
            "agents": {
                slot.label: {
                    "model": slot.model_spec,
                    "findings": self.findings.get(slot.label, ""),
                    "status": "running" if slot.label in self.solvers and not self.cancel_event.is_set()
                             else ("won" if self.winner and self.winner.flag else "finished"),
                }
                for slot in self._solver_slots()
            },
        }
