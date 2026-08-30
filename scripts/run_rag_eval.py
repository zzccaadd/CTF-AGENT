#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from backend.benchmarks.models import BenchmarkLimits
from backend.benchmarks.providers import CybenchProvider, NYUProvider
from backend.benchmarks.runner import BenchmarkRunner

ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = ROOT / "benchmarks"
DEFAULT_MANIFESTS = [
    BENCH_ROOT / "rag_eval" / "main_100.json",
    BENCH_ROOT / "rag_eval" / "smoke_20.json",
    BENCH_ROOT / "rag_eval" / "rag_sensitive_100.json",
]


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def provider_impl(provider: str, image: str):
    if provider == "nyu":
        return NYUProvider(BENCH_ROOT / "NYU_CTF_Bench", image=image)
    if provider == "cybench":
        return CybenchProvider(BENCH_ROOT / "cybench", image=image)
    raise ValueError(f"Unsupported provider in manifest: {provider}")


def _aggregate(results: list[dict]) -> dict:
    """Aggregate per-challenge result dicts into comparable summary metrics."""
    total = len(results)
    solved = sum(1 for result in results if result.get("solved"))
    knowledge_chars = sum(result.get("knowledge_chars", 0) for result in results)
    return {
        "solved": solved,
        "total": total,
        "solve_rate": round(solved / total, 4) if total else 0,
        "timeouts": sum(1 for result in results if result.get("status") == "timeout"),
        "errors": sum(1 for result in results if result.get("status") == "error"),
        "tool_calls_avg": round(sum(result.get("tool_calls", 0) for result in results) / total, 3) if total else 0,
        "total_tokens": sum(result.get("total_tokens", 0) for result in results),
        "cost_usd": round(sum(result.get("cost_usd", 0) for result in results), 6),
        "elapsed_avg": round(sum(result.get("elapsed_seconds", 0) for result in results) / total, 3) if total else 0,
        "knowledge_queries": sum(result.get("knowledge_queries", 0) for result in results),
        "knowledge_hits": sum(result.get("knowledge_hits", 0) for result in results),
        "knowledge_chars": knowledge_chars,
        "knowledge_elapsed_ms": round(sum(result.get("knowledge_elapsed_ms", 0) for result in results), 3),
        "knowledge_tool_calls": sum(result.get("knowledge_tool_calls", 0) for result in results),
        "knowledge_cache_hits": sum(result.get("knowledge_cache_hits", 0) for result in results),
        "knowledge_budget_rejections": sum(result.get("knowledge_budget_rejections", 0) for result in results),
        # Rough estimate of the extra context tokens the knowledge tool paid
        # for (chars/4); exact accounting requires per-turn token deltas.
        "knowledge_est_extra_tokens": knowledge_chars // 4,
    }


def _incomplete_pairs(off_results: list[dict], on_results: list[dict]) -> list[dict]:
    """Challenges that ran on one side only — marked incomplete, not unsolved."""
    off_ids = {r.get("challenge_id") for r in off_results}
    on_ids = {r.get("challenge_id") for r in on_results}
    missing: list[dict] = []
    for challenge_id in sorted(off_ids - on_ids):
        missing.append({"challenge_id": challenge_id, "missing_side": "on"})
    for challenge_id in sorted(on_ids - off_ids):
        missing.append({"challenge_id": challenge_id, "missing_side": "off"})
    return missing


def _aggregate_replicates(pairs: list[tuple[dict, dict]]) -> dict:
    """Cross-replicate aggregation: mean solve rates/costs/tokens and
    per-challenge solved counts, plus incomplete-pair accounting.

    `pairs` is a list of (off_run, on_run) raw run outputs, one per replicate.
    A challenge missing on one side is marked incomplete and its missing side
    is NOT counted as unsolved (Stage 3 §6.2)."""
    n = max(1, len(pairs))
    off_rows = [row for off, _ in pairs for row in off["results"]]
    on_rows = [row for _, on in pairs for row in on["results"]]
    agg_off = _aggregate(off_rows)
    agg_on = _aggregate(on_rows)
    challenges: dict[str, dict] = {}
    for off, on in pairs:
        off_by_id = {result.get("challenge_id"): result for result in off["results"]}
        on_by_id = {result.get("challenge_id"): result for result in on["results"]}
        for cid in set(off_by_id) | set(on_by_id):
            entry = challenges.setdefault(
                cid,
                {"off_solved": 0, "off_total": 0, "on_solved": 0, "on_total": 0,
                 "knowledge_queries": 0, "incomplete": False},
            )
            off_result = off_by_id.get(cid)
            on_result = on_by_id.get(cid)
            if off_result is not None:
                entry["off_total"] += 1
                entry["off_solved"] += int(bool(off_result.get("solved")))
            if on_result is not None:
                entry["on_total"] += 1
                entry["on_solved"] += int(bool(on_result.get("solved")))
                entry["knowledge_queries"] += int(on_result.get("knowledge_queries", 0))
            if off_result is None or on_result is None:
                entry["incomplete"] = True
    return {
        "replicates": len(pairs),
        "off": agg_off,
        "on": agg_on,
        "delta_solved_mean": round(agg_on["solved"] / n - agg_off["solved"] / n, 4) if agg_off["total"] else 0,
        "delta_cost_usd_mean": round(agg_on["cost_usd"] / n - agg_off["cost_usd"] / n, 6),
        "delta_tokens_mean": round(agg_on["total_tokens"] / n - agg_off["total_tokens"] / n, 3),
        "per_challenge": [
            {
                "challenge_id": cid,
                "off_solved_replicates": entry["off_solved"],
                "off_total_replicates": entry["off_total"],
                "on_solved_replicates": entry["on_solved"],
                "on_total_replicates": entry["on_total"],
                "incomplete": entry["incomplete"],
                "knowledge_queries_total": entry["knowledge_queries"],
            }
            for cid, entry in sorted(challenges.items())
        ],
        "incomplete_pairs": [p for off, on in pairs for p in _incomplete_pairs(off["results"], on["results"])],
    }


def build_comparison(manifest_path: Path, off: dict, on: dict) -> dict:
    """Compare one manifest's rag-off run against its rag-on run.

    Per-challenge rows are matched by challenge_id so provider reordering can
    never misalign the off/on pair."""
    on_by_id = {result.get("challenge_id"): result for result in on["results"]}
    off_agg = _aggregate(off["results"])
    on_agg = _aggregate(on["results"])
    per_challenge = []
    for off_result in off["results"]:
        challenge_id = off_result.get("challenge_id")
        on_result = on_by_id.get(challenge_id) or {}
        off_solved = bool(off_result.get("solved"))
        on_solved = bool(on_result.get("solved"))
        per_challenge.append(
            {
                "challenge_id": challenge_id,
                "off": {
                    "solved": off_solved,
                    "status": off_result.get("status"),
                    "tool_calls": off_result.get("tool_calls"),
                    "tokens": off_result.get("total_tokens"),
                    "cost_usd": off_result.get("cost_usd"),
                },
                "on": {
                    "solved": on_solved,
                    "status": on_result.get("status"),
                    "tool_calls": on_result.get("tool_calls"),
                    "tokens": on_result.get("total_tokens"),
                    "cost_usd": on_result.get("cost_usd"),
                    "knowledge_queries": on_result.get("knowledge_queries", 0),
                    "knowledge_hits": on_result.get("knowledge_hits", 0),
                },
                "delta_solved": int(on_solved) - int(off_solved),
                "incomplete": challenge_id not in on_by_id,
            }
        )
    return {
        "manifest": manifest_path.as_posix(),
        "off": off_agg,
        "on": on_agg,
        "delta_solved": on_agg["solved"] - off_agg["solved"],
        "delta_cost_usd": round(on_agg["cost_usd"] - off_agg["cost_usd"], 6),
        "delta_tokens": on_agg["total_tokens"] - off_agg["total_tokens"],
        "per_challenge": per_challenge,
        "incomplete": _incomplete_pairs(off["results"], on["results"]),
    }


def _active_items(manifest: dict) -> tuple[list[dict], list[str]]:
    """Split manifest items into runnable ones and environment-unavailable
    ones (docker image build failures etc.), so those never waste a run."""
    skipped = [
        item["challenge_id"]
        for item in manifest["items"]
        if item.get("environment_unavailable")
    ]
    active = [item for item in manifest["items"] if not item.get("environment_unavailable")]
    return active, skipped


async def run_manifest(
    manifest_path: Path,
    *,
    model: str,
    timeout: int,
    max_tokens: int,
    concurrency: int,
    solvers_per_swarm: int = 1,
    image: str,
    allow_internet: bool,
    rag_enabled: bool,
    results_dir: Path,
) -> dict:
    manifest = load_manifest(manifest_path)
    items, skipped = _active_items(manifest)
    grouped: dict[str, list[str]] = {}
    for item in items:
        grouped.setdefault(item["provider"], []).append(item["challenge_id"])

    manifest_results = []
    for provider_name, challenge_ids in grouped.items():
        impl = provider_impl(provider_name, image=image)
        split = "test" if provider_name == "nyu" else "benchmark"
        discovered = impl.discover(split)
        selected = [ch for ch in discovered if ch.challenge_id in set(challenge_ids)]
        selected_by_id = {ch.challenge_id: ch for ch in selected}
        ordered = [selected_by_id[cid] for cid in challenge_ids if cid in selected_by_id]

        limits = BenchmarkLimits(
            model=model,
            timeout_seconds=timeout,
            max_tokens=max_tokens,
            allow_internet=allow_internet,
            attempts=1,
            concurrency=concurrency,
            solvers_per_swarm=solvers_per_swarm,
            max_solvers_per_swarm=solvers_per_swarm,
            rag_enabled=rag_enabled,
        )
        provider_results_path = results_dir / f"{manifest_path.stem}.{provider_name}.json"
        runner = BenchmarkRunner(impl, limits, image=image, results_path=provider_results_path)
        results = await runner.run(ordered)
        manifest_results.extend(result.to_dict() for result in results)

    output = {
        "manifest": manifest_path.as_posix(),
        "default_model": model,
        "timeout_seconds": timeout,
        "max_tokens": max_tokens,
        "concurrency": concurrency,
        "allow_internet": allow_internet,
        "rag_enabled": rag_enabled,
        "total": len(manifest_results),
        "solved": sum(1 for result in manifest_results if result.get("solved")),
        "skipped_environment_unavailable": skipped,
        "results": manifest_results,
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{manifest_path.stem}.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run curated RAG evaluation manifests.")
    parser.add_argument(
        "--manifest",
        action="append",
        type=Path,
        help="Manifest JSON path. May be repeated. Defaults to all three curated manifests.",
    )
    parser.add_argument("--model", default="codex/gpt-5.5")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--max-tokens", type=int, default=500_000)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--solvers-per-swarm", type=int, default=1, help="Codex workers per challenge (default 1)")
    parser.add_argument("--image", default="ctf-sandbox")
    parser.add_argument("--allow-internet", action="store_true")
    parser.add_argument("--rag", dest="rag_enabled", default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument("--compare-rag", action="store_true", help="Run the same manifests with RAG off and on")
    parser.add_argument("--repeats", type=int, default=1, help="Number of off/on replicates per manifest (default 1)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for off/on execution-order randomization")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results" / "rag_eval")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    manifests = args.manifest or DEFAULT_MANIFESTS
    if args.compare_rag:
        if args.repeats < 1:
            raise SystemExit("--repeats must be at least 1")
        import random

        output = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "seed": args.seed,
            "repeats": args.repeats,
            "manifests": [],
        }
        for manifest in manifests:
            comparisons = []
            pairs: list[tuple[dict, dict]] = []
            rng = random.Random(args.seed)
            for replicate in range(1, args.repeats + 1):
                # Randomize off/on execution order per replicate (Stage 3 §6.2)
                # so fixed-order time/cache/service drift cannot bias results.
                order = rng.sample(["off", "on"], 2)
                runs: dict[str, dict] = {}
                for side in order:
                    enabled = side == "on"
                    if args.repeats > 1:
                        run_dir = args.results_dir / f"rep{replicate}" / ("rag_on" if enabled else "rag_off")
                    else:
                        run_dir = args.results_dir / ("rag_on" if enabled else "rag_off")
                    runs[side] = await run_manifest(
                        manifest,
                        model=args.model,
                        timeout=args.timeout,
                        max_tokens=args.max_tokens,
                        concurrency=args.concurrency,
                        solvers_per_swarm=args.solvers_per_swarm,
                        image=args.image,
                        allow_internet=args.allow_internet,
                        rag_enabled=enabled,
                        results_dir=run_dir,
                    )
                comparison = build_comparison(manifest, runs["off"], runs["on"])
                comparison["replicate"] = replicate
                comparison["order"] = order
                comparisons.append(comparison)
                pairs.append((runs["off"], runs["on"]))
            output["manifests"].append(
                {
                    "manifest": manifest.as_posix(),
                    "replicates": comparisons,
                    "aggregate": _aggregate_replicates(pairs),
                }
            )
        args.results_dir.mkdir(parents=True, exist_ok=True)
        (args.results_dir / "rag_comparison.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return
    for manifest in manifests:
        await run_manifest(
            manifest,
            model=args.model,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            concurrency=args.concurrency,
            solvers_per_swarm=args.solvers_per_swarm,
            image=args.image,
            allow_internet=args.allow_internet,
            rag_enabled=args.rag_enabled,
            results_dir=args.results_dir,
        )


if __name__ == "__main__":
    asyncio.run(main())
