"""CLI for NYU CTF Bench and Cybench evaluation."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
from rich.console import Console

from backend.benchmarks.models import BenchmarkLimits
from backend.benchmarks.providers import CybenchProvider, NYUProvider
from backend.benchmarks.runner import BenchmarkRunner

console = Console()


@click.command()
@click.option("--provider", type=click.Choice(["nyu", "cybench"]), default="nyu", show_default=True)
@click.option("--root", type=click.Path(path_type=Path, exists=True, file_okay=False), required=True)
@click.option("--split", default="development", show_default=True)
@click.option("--challenge", "challenge_ids", multiple=True, help="Exact provider challenge ID")
@click.option("--limit", default=5, type=click.IntRange(min=1), show_default=True)
@click.option("--model", default="codex/gpt-5.5", show_default=True)
@click.option("--timeout", default=1_800, type=click.IntRange(min=1), show_default=True)
@click.option("--max-tokens", default=1_000_000, type=click.IntRange(min=1), show_default=True)
@click.option("--concurrency", default=1, type=click.IntRange(min=1), show_default=True, help="Challenges to run at once")
@click.option("--solvers-per-swarm", default=3, type=click.IntRange(min=1, max=3), show_default=True, help="Codex workers per challenge (max 3)")
@click.option("--allow-internet", is_flag=True, help="Allow solver internet access")
@click.option("--rag/--no-rag", "rag_enabled", default=True, show_default=True, help="Enable local knowledge search")
@click.option("--image", default="ctf-sandbox", show_default=True)
@click.option("--results", default="benchmark-results.json", type=click.Path(path_type=Path))
@click.option("-v", "--verbose", is_flag=True)
def main(
    provider: str,
    root: Path,
    split: str,
    challenge_ids: tuple[str, ...],
    limit: int,
    model: str,
    timeout: int,
    max_tokens: int,
    concurrency: int,
    solvers_per_swarm: int,
    allow_internet: bool,
    rag_enabled: bool,
    image: str,
    results: Path,
    verbose: bool,
) -> None:
    """Run a fixed-budget, single-model CTF benchmark."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%X",
        force=True,
    )
    provider_impl = NYUProvider(root, image=image) if provider == "nyu" else CybenchProvider(root, image=image)
    discovered = provider_impl.discover(split)
    if challenge_ids:
        requested = set(challenge_ids)
        selected = [challenge for challenge in discovered if challenge.challenge_id in requested]
        missing = requested - {challenge.challenge_id for challenge in selected}
        if missing:
            raise click.ClickException(f"Unknown challenge IDs: {', '.join(sorted(missing))}")
    else:
        selected = discovered[:limit]

    if not selected:
        raise click.ClickException(f"No challenges found for {provider}:{split}")

    limits = BenchmarkLimits(
        model=model,
        timeout_seconds=timeout,
        max_tokens=max_tokens,
        allow_internet=allow_internet,
        attempts=1,
        concurrency=concurrency,
        solvers_per_swarm=solvers_per_swarm,
        rag_enabled=rag_enabled,
    )
    console.print("[bold]CTF Agent Benchmark[/bold]")
    console.print(f"  Provider: {provider}")
    console.print(f"  Split: {split}")
    console.print(f"  Challenges: {len(selected)}")
    console.print(f"  Model: {model}")
    console.print(f"  Timeout: {timeout}s")
    console.print(f"  Token limit: {max_tokens}")
    console.print(f"  Concurrency: {concurrency}")
    console.print(f"  Solvers/swarm: {solvers_per_swarm}")
    console.print(f"  Internet: {'allowed' if allow_internet else 'blocked'}")
    console.print()

    runner = BenchmarkRunner(provider_impl, limits, image=image, results_path=results)
    run_results = asyncio.run(runner.run(selected))
    solved = sum(result.solved for result in run_results)
    console.print(f"\n[bold]Result:[/bold] {solved}/{len(run_results)} solved")
    console.print(f"Results written to {results.resolve()}")


if __name__ == "__main__":
    main()
