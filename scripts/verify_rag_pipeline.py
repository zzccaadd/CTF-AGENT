#!/usr/bin/env python3
"""Three-layer RAG verification pipeline (fast, cheap by design).

Layer 1 — tool-call precision (rag_tool_probe.py): does the model actually
        invoke search_knowledge when instructed? (~$0.01, seconds)
Layer 2 — retrieval quality (eval_knowledge_recall.py): does the corpus
        answer the queries the challenges need? recall@k / MRR / empty-hit
        against manifest qrels. (zero API cost, instant)
Layer 3 — end-to-end fast probe (run_rag_eval.py on a fast challenge):
        solver + coordinator + RAG in one quick run. (~$1-2, few minutes)

Usage:
  python scripts/verify_rag_pipeline.py [--manifest benchmarks/rag_eval/knowledge_probe_v4.json]
                                        [--probe-query "ELF e_entry"]
                                        [--e2e-manifest /tmp/verify_v5_off.json]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], label: str) -> int:
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run([str(ROOT / ".venv" / "bin" / "python"), *cmd], cwd=ROOT)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=str, default="benchmarks/rag_eval/knowledge_probe_v4.json")
    parser.add_argument("--probe-query", type=str, default="ELF e_entry")
    parser.add_argument("--e2e-manifest", type=str, default="")
    parser.add_argument("--layers", type=str, default="1,2", help="comma list of layers to run (default 1,2)")
    args = parser.parse_args()

    layers = [int(x) for x in args.layers.split(",") if x.strip()]
    failures = 0

    if 1 in layers:
        failures += run(
            ["scripts/rag_tool_probe.py"],
            "Layer 1: tool-call precision (model invokes search_knowledge on instruction)",
        )
    if 2 in layers:
        failures += run(
            ["scripts/eval_knowledge_recall.py", "--manifest", args.manifest],
            "Layer 2: retrieval quality (recall@k / MRR / empty-hit, zero API cost)",
        )
    if 3 in layers:
        if not args.e2e_manifest:
            print("Layer 3 skipped: pass --e2e-manifest to run the end-to-end fast probe")
        else:
            failures += run(
                ["scripts/run_rag_eval.py", "--manifest", args.e2e_manifest,
                 "--timeout", "300", "--max-tokens", "1000000",
                 "--concurrency", "1", "--solvers-per-swarm", "3", "--rag",
                 "--results-dir", "results/rag_pipeline_probe"],
                "Layer 3: end-to-end fast probe (solver + coordinator + RAG)",
            )

    print("\n=== pipeline summary ===")
    print(f"layers run: {layers}  failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
