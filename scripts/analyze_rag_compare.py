#!/usr/bin/env python3
"""Summarize a RAG off/on comparison run for the labeled knowledge probe.

Reads `--results-dir/rag_comparison.json` (written by run_rag_eval --compare-rag)
and the labeled manifest, then prints:

- per-challenge table: off/on solved/status/cost/tokens + knowledge usage
- group aggregates: knowledge-needed vs not-needed (Recall@K proxy = hits per
  query; invalid-call rate = queries on not-needed challenges)
- three-way attribution hints: corpus (hits=0), recall (hits>0 but wrong
  content), solver usage (queries=0 despite tool available)

Usage:
  .venv/bin/python scripts/analyze_rag_compare.py \
      --results-dir results/rag_eval \
      --manifest benchmarks/rag_eval/knowledge_probe.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results" / "rag_eval")
    parser.add_argument("--manifest", type=Path, default=ROOT / "benchmarks" / "rag_eval" / "knowledge_probe.json")
    args = parser.parse_args()

    comparison = json.loads((args.results_dir / "rag_comparison.json").read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    labels = {item["challenge_id"]: item for item in manifest["items"]}

    # New format: {"manifests": [{manifest, replicates, aggregate}]}; old
    # format was a bare list of comparisons — wrap it as one replicate.
    if "manifests" in comparison:
        rows = comparison["manifests"]
    else:
        rows = [{"manifest": row["manifest"], "replicates": [row], "aggregate": None} for row in comparison]

    for manifest_row in rows:
        print(f"=== manifest: {manifest_row['manifest']} "
              f"(replicates={len(manifest_row['replicates'])})")
        aggregate = manifest_row.get("aggregate")
        if aggregate:
            off, on = aggregate["off"], aggregate["on"]
            print(f"  aggregate: off {off['solved']}/{off['total']} ($ {off['cost_usd']:.2f}, {off['total_tokens']} tok) "
                  f"on {on['solved']}/{on['total']} ($ {on['cost_usd']:.2f}, {on['total_tokens']} tok) "
                  f"delta_solved={aggregate['delta_solved_mean']:+.2f} "
                  f"delta_cost=${aggregate['delta_cost_usd_mean']:+.4f}")
            print(f"  knowledge(on): calls={on['knowledge_tool_calls']} queries={on['knowledge_queries']} "
                  f"hits={on['knowledge_hits']} cache={on['knowledge_cache_hits']} "
                  f"rejections={on['knowledge_budget_rejections']} chars={on['knowledge_chars']} "
                  f"elapsed_ms={on['knowledge_elapsed_ms']}")
            if aggregate["incomplete_pairs"]:
                print(f"  INCOMPLETE pairs: {aggregate['incomplete_pairs']}")

        for row in manifest_row["replicates"]:
            off, on = row["off"], row["on"]
            print(f"  rep{row.get('replicate', '?')} (order={row.get('order', 'off,on')}): "
                  f"off {off['solved']}/{off['total']} on {on['solved']}/{on['total']} "
                  f"delta={row['delta_solved']:+d} $delta={row['delta_cost_usd']:+.3f} "
                  f"kq={on['knowledge_queries']} kh={on['knowledge_hits']}")
            print("    per challenge:")
            needed_hits, needed_queries, not_needed_queries = 0, 0, 0
            for item in row["per_challenge"]:
                cid = item["challenge_id"]
                label = labels.get(cid, {})
                needed = label.get("knowledge_needed")
                expected = ",".join(label.get("expected_knowledge", [])) or "-"
                on_item, off_item = item["on"], item["off"]
                flag = " (timeout)" if on_item["status"] == "timeout" and not on_item["solved"] else ""
                if needed:
                    needed_queries += on_item["knowledge_queries"]
                    needed_hits += on_item["knowledge_hits"]
                else:
                    not_needed_queries += on_item["knowledge_queries"]
                print(
                    f"      {'KNOW' if needed else 'NONE':4s} {cid.split('/')[-1][:30]:30s} "
                    f"off:{'Y' if off_item['solved'] else 'N'}{off_item['status'][:6]:6s} "
                    f"on:{'Y' if on_item['solved'] else 'N'}{on_item['status'][:6]:6s} "
                    f"Δ={item['delta_solved']:+d} $on={on_item['cost_usd'] or 0:.3f} "
                    f"kq={on_item['knowledge_queries']} kh={on_item['knowledge_hits']} "
                    f"expect[{expected}]{flag}"
                )
            recall_proxy = (needed_hits / needed_queries) if needed_queries else 0.0
            print(
                f"    group: KNOW hits/queries={needed_hits}/{needed_queries} "
                f"(recall proxy {recall_proxy:.2f}); "
                f"NONE queries={not_needed_queries} (invalid-call rate)"
            )
        print()

    # Three-way attribution summary across all manifests
    print("=== attribution hints")
    print("  solver-usage: knowledge_queries==0 on knowledge-needed challenges -> model never uses the tool")
    print("  corpus/recall: queries>0 but hits==0 -> corpus missing the topic; queries>0, hits>0 -> check recall quality")
    print("  cost: delta_cost_usd quantifies the price of enabling RAG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
