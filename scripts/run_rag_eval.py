#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
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


async def run_manifest(
    manifest_path: Path,
    *,
    model: str,
    timeout: int,
    max_tokens: int,
    concurrency: int,
    image: str,
    allow_internet: bool,
    results_dir: Path,
) -> dict:
    manifest = load_manifest(manifest_path)
    grouped: dict[str, list[str]] = {}
    for item in manifest["items"]:
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
            solvers_per_swarm=1,
            max_solvers_per_swarm=1,
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
        "total": len(manifest_results),
        "solved": sum(1 for result in manifest_results if result.get("solved")),
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
    parser.add_argument("--model", default="codex/gpt-5.6-luna")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--max-tokens", type=int, default=500_000)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--image", default="ctf-sandbox")
    parser.add_argument("--allow-internet", action="store_true")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results" / "rag_eval")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    manifests = args.manifest or DEFAULT_MANIFESTS
    for manifest in manifests:
        await run_manifest(
            manifest,
            model=args.model,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            concurrency=args.concurrency,
            image=args.image,
            allow_internet=args.allow_internet,
            results_dir=args.results_dir,
        )


if __name__ == "__main__":
    asyncio.run(main())
