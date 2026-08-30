"""Concurrent, fixed-budget benchmark runner."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path

from backend.agents.swarm import ChallengeSwarm
from backend.benchmarks.models import BenchmarkChallenge, BenchmarkLimits, BenchmarkResult
from backend.benchmarks.providers.base import BenchmarkProvider
from backend.config import Settings
from backend.cost_tracker import CostTracker
from backend.prompts import ChallengeMeta
from backend.sandbox import cleanup_orphan_containers, configure_semaphore
from backend.solver_base import FLAG_FOUND
from backend.submission import LocalFlagVerifier

logger = logging.getLogger(__name__)


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
                    status = "timeout"
                else:
                    status = solver_result.status if solver_result else "no_result"
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
            },
            "summary": {
                "total": len(self.results),
                "solved": sum(result.solved for result in self.results),
                "cost_usd": round(sum(result.cost_usd for result in self.results), 6),
            },
            "results": [result.to_dict() for result in self.results],
        }
        self.results_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
