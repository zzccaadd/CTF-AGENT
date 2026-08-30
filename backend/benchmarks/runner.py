"""Concurrent, fixed-budget benchmark runner."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from backend.agents.swarm import ChallengeSwarm
from backend.benchmarks.models import BenchmarkChallenge, BenchmarkLimits, BenchmarkResult
from backend.benchmarks.providers.base import BenchmarkProvider
from backend.config import Settings
from backend.cost_tracker import CostTracker
from backend.prompts import ChallengeMeta
from backend.sandbox import cleanup_orphan_containers, configure_semaphore
from backend.solver_base import FLAG_FOUND, SolverResult
from backend.submission import LocalFlagVerifier

logger = logging.getLogger(__name__)


def _solver_step_count(solver: object) -> int:
    value = getattr(solver, "_step_count", 0)
    if isinstance(value, list):
        value = value[0] if value else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _swarm_knowledge_metrics(swarm: ChallengeSwarm) -> dict:
    """Sum knowledge counters across ALL solvers of a swarm.

    The winner's SolverResult only carries the winner's counters; with
    solvers_per_swarm > 1 that under-counts the challenge's real knowledge
    usage, so results are patched with swarm totals."""
    solver_list = list(swarm.solvers.values())
    return {
        "knowledge_queries": sum(int(getattr(solver, "_knowledge_queries", 0)) for solver in solver_list),
        "knowledge_hits": sum(int(getattr(solver, "_knowledge_hits", 0)) for solver in solver_list),
        "knowledge_chars": sum(int(getattr(solver, "_knowledge_chars", 0)) for solver in solver_list),
        "knowledge_elapsed_ms": round(
            sum(float(getattr(solver, "_knowledge_elapsed_ms", 0.0)) for solver in solver_list), 3
        ),
        "knowledge_tool_calls": sum(int(getattr(solver, "_knowledge_tool_calls", 0)) for solver in solver_list),
        "knowledge_cache_hits": sum(int(getattr(solver, "_knowledge_cache_hits", 0)) for solver in solver_list),
        "knowledge_budget_rejections": sum(
            int(getattr(solver, "_knowledge_budget_rejections", 0)) for solver in solver_list
        ),
    }


def _no_result_result(swarm: ChallengeSwarm, tracker: CostTracker) -> SolverResult:
    """Diagnostic result when the swarm ran but produced no winner/flag.

    Preserves the real trace path, tool-call count and cost instead of the
    empty `no_result` row that previously hid what actually happened."""
    solver_list = list(swarm.solvers.values())
    trace_path = next(
        (getattr(getattr(solver, "tracer", None), "path", "") for solver in solver_list
         if getattr(getattr(solver, "tracer", None), "path", "")),
        "",
    )
    return SolverResult(
        flag=None,
        status="no_result",
        findings_summary="Swarm finished without a winner or confirmed flag; see solver traces.",
        step_count=sum(_solver_step_count(solver) for solver in solver_list),
        cost_usd=tracker.total_cost_usd,
        log_path=trace_path,
        **_swarm_knowledge_metrics(swarm),
    )


def _timeout_result(swarm: ChallengeSwarm, tracker: CostTracker) -> SolverResult:
    """Preserve useful diagnostics when the benchmark deadline cancels a swarm."""
    solver_list = list(swarm.solvers.values())
    findings = "\n\n".join(
        value for value in swarm.findings.values() if value
    )[:2000]
    trace_path = next(
        (getattr(getattr(solver, "tracer", None), "path", "") for solver in solver_list
         if getattr(getattr(solver, "tracer", None), "path", "")),
        "",
    )
    return SolverResult(
        flag=swarm.confirmed_flag,
        status="timeout",
        findings_summary=findings or "Benchmark timeout; inspect blackboard and solver traces.",
        step_count=sum(_solver_step_count(solver) for solver in solver_list),
        cost_usd=tracker.total_cost_usd,
        log_path=trace_path,
        **_swarm_knowledge_metrics(swarm),
    )


class BenchmarkRunner:
    def __init__(
        self,
        provider: BenchmarkProvider,
        limits: BenchmarkLimits,
        *,
        image: str = "ctf-sandbox",
        results_path: str | Path = "benchmark-results.json",
    ) -> None:
        self.provider = provider
        self.limits = limits
        self.image = image
        self.results_path = Path(results_path)
        self.results: list[BenchmarkResult] = []

    async def run(self, challenges: list[BenchmarkChallenge]) -> list[BenchmarkResult]:
        max_containers = self.limits.concurrency * self.limits.solvers_per_swarm
        configure_semaphore(max(1, max_containers))
        await cleanup_orphan_containers()
        semaphore = asyncio.Semaphore(self.limits.concurrency)
        write_lock = asyncio.Lock()

        async def _run_and_record(challenge: BenchmarkChallenge) -> None:
            async with semaphore:
                result = await self.run_one(challenge)
            async with write_lock:
                self.results.append(result)
                self._write_results()

        await asyncio.gather(*(_run_and_record(challenge) for challenge in challenges))
        return self.results

    async def run_one(self, challenge: BenchmarkChallenge) -> BenchmarkResult:
        started = time.monotonic()
        verifier = LocalFlagVerifier(challenge.name, challenge.expected_flags)
        tracker = CostTracker()
        prepared = None
        solver_result = None
        error = ""
        status = "error"

        with tempfile.TemporaryDirectory(prefix="ctf-bench-") as tmp:
            try:
                prepared = await self.provider.prepare(challenge, Path(tmp) / "challenge")
                await self.provider.start(prepared)
                settings = Settings(
                    sandbox_image=self.image,
                    sandbox_network=prepared.network_mode,
                    allow_internet=self.limits.allow_internet,
                    max_tokens_per_challenge=self.limits.max_tokens,
                    challenge_timeout_seconds=self.limits.timeout_seconds,
                    max_concurrent_challenges=self.limits.concurrency,
                    max_solvers_per_swarm=self.limits.max_solvers_per_swarm,
                    knowledge_enabled=self.limits.rag_enabled,
                    knowledge_db_path=self.limits.knowledge_db_path,
                    knowledge_top_k=self.limits.knowledge_top_k,
                    knowledge_max_chars=self.limits.knowledge_max_chars,
                )
                meta = ChallengeMeta.from_yaml(prepared.challenge_dir / "metadata.yml")
                swarm = ChallengeSwarm(
                    challenge_dir=str(prepared.challenge_dir),
                    meta=meta,
                    ctfd=verifier,
                    cost_tracker=tracker,
                    settings=settings,
                    model_specs=[self.limits.model],
                    solvers_per_model=self.limits.solvers_per_swarm,
                    max_solvers=self.limits.max_solvers_per_swarm,
                    no_submit=False,
                )
                task = asyncio.create_task(swarm.run(), name=f"bench-{challenge.challenge_id}")
                try:
                    solver_result = await asyncio.wait_for(task, timeout=self.limits.timeout_seconds)
                except TimeoutError:
                    swarm.kill()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    solver_result = _timeout_result(swarm, tracker)
                    status = "timeout"
                else:
                    if solver_result is None:
                        # Swarm finished without a winner and without a
                        # confirmed flag (e.g. all solvers cancelled on token
                        # budget). Never discard what actually ran: build a
                        # diagnostic result from the swarm instead of losing
                        # the trace/cost/step info.
                        solver_result = _no_result_result(swarm, tracker)
                    status = solver_result.status
                    # Patch winner-only knowledge counters with swarm totals
                    # so multi-solver runs report the challenge's real usage.
                    solver_result = replace(solver_result, **_swarm_knowledge_metrics(swarm))
            except Exception as exc:
                error = str(exc)
                logger.exception("Benchmark challenge failed: %s", challenge.challenge_id)
            finally:
                if prepared:
                    try:
                        await self.provider.stop(prepared)
                    except Exception as exc:
                        logger.warning("Challenge cleanup failed: %s", exc)
                        if not error:
                            error = f"cleanup failed: {exc}"

        model_usage = tracker.get_usage_by_model()
        usage = model_usage.get(self.limits.model.split("/", 1)[-1], {})
        input_tokens = int(usage.get("input", 0))
        output_tokens = int(usage.get("output", 0))
        cached_tokens = int(usage.get("cached", 0))
        solved = bool(
            solver_result
            and solver_result.status == FLAG_FOUND
            and verifier.accepted_flag
        )
        wrong_submissions = len(verifier.submitted_flags) - (1 if verifier.accepted_flag else 0)
        return BenchmarkResult(
            challenge_id=challenge.challenge_id,
            provider=challenge.provider,
            name=challenge.name,
            category=challenge.category,
            model=self.limits.model,
            solved=solved,
            status=status,
            flag=verifier.accepted_flag,
            elapsed_seconds=round(time.monotonic() - started, 3),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=round(tracker.total_cost_usd, 6),
            wrong_submissions=max(0, wrong_submissions),
            tool_calls=solver_result.step_count if solver_result else 0,
            trace_path=solver_result.log_path if solver_result else "",
            error=error,
            knowledge_queries=solver_result.knowledge_queries if solver_result else 0,
            knowledge_hits=solver_result.knowledge_hits if solver_result else 0,
            knowledge_chars=solver_result.knowledge_chars if solver_result else 0,
            knowledge_elapsed_ms=solver_result.knowledge_elapsed_ms if solver_result else 0.0,
            knowledge_tool_calls=solver_result.knowledge_tool_calls if solver_result else 0,
            knowledge_cache_hits=solver_result.knowledge_cache_hits if solver_result else 0,
            knowledge_budget_rejections=solver_result.knowledge_budget_rejections if solver_result else 0,
        )

    def _write_results(self) -> None:
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "config": {
                "model": self.limits.model,
                "timeout_seconds": self.limits.timeout_seconds,
                "max_tokens": self.limits.max_tokens,
                "allow_internet": self.limits.allow_internet,
                "attempts": self.limits.attempts,
                "concurrency": self.limits.concurrency,
                "solvers_per_swarm": self.limits.solvers_per_swarm,
                "max_solvers_per_swarm": self.limits.max_solvers_per_swarm,
                "rag_enabled": self.limits.rag_enabled,
                "knowledge_db_path": self.limits.knowledge_db_path,
            },
            "summary": {
                "total": len(self.results),
                "solved": sum(result.solved for result in self.results),
                "cost_usd": round(sum(result.cost_usd for result in self.results), 6),
                "knowledge_queries": sum(result.knowledge_queries for result in self.results),
                "knowledge_hits": sum(result.knowledge_hits for result in self.results),
                "knowledge_chars": sum(result.knowledge_chars for result in self.results),
                "knowledge_elapsed_ms": round(
                    sum(result.knowledge_elapsed_ms for result in self.results), 3
                ),
                "knowledge_tool_calls": sum(result.knowledge_tool_calls for result in self.results),
                "knowledge_cache_hits": sum(result.knowledge_cache_hits for result in self.results),
                "knowledge_budget_rejections": sum(result.knowledge_budget_rejections for result in self.results),
            },
            "results": [result.to_dict() for result in self.results],
        }
        self.results_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
