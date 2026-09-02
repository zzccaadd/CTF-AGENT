#!/usr/bin/env python3
"""Fine-grained offline RAG retrieval evaluation (ragas-style, zero API cost).

For every knowledge-tagged challenge in a manifest, generate probe queries
from its `expected_knowledge` terms and measure whether the corpus retrieval
returns the annotated `relevant_corpus_docs` (the qrels ground truth):

- recall@k:   fraction of relevant docs retrieved within top-k
- mrr:        mean reciprocal rank of the first relevant doc
- hit_docs:   which relevant docs actually surfaced (per query)
- probe_count / empty_hits:  queries with zero results (tool-surface / corpus gap)

This runs purely against logs/knowledge.sqlite3 — no model, no API cost — so
it can be looped during development to verify "does the knowledge base answer
the questions the challenge needs" before paying for full solve runs.

Usage:
  python scripts/eval_knowledge_recall.py [--manifest benchmarks/rag_eval/knowledge_probe_v4.json] [--db logs/knowledge.sqlite3] [--top-k 5]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.knowledge.service import KnowledgeService


def _probe_queries(expected_knowledge: list[str], name: str) -> list[str]:
    """Map expected-knowledge tags to concrete search terms the model would use."""
    queries: list[str] = []
    for tag in expected_knowledge:
        tag = tag.lower().strip()
        if not tag:
            continue
        queries.append(tag)
        # Slightly more specific variants that models actually issue.
        if tag in ("xor", "encodings", "custom-encoding"):
            queries.append(f"{tag} cipher variant")
        elif tag in ("pyc", "python-reversing"):
            queries.append("pyc reversing")
        elif tag == "matrix":
            queries.append("matrix python")
        elif tag == "reverse-engineering":
            queries.append("reverse engineering obfuscation")
        elif tag in ("sql-injection", "command-injection", "waf-bypass"):
            queries.append(f"{tag} bypass")
    # Always add the challenge name itself (models sometimes search it).
    queries.append(name)
    return queries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rag_eval/knowledge_probe_v4.json"))
    parser.add_argument("--db", default="logs/knowledge.sqlite3")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    service = KnowledgeService.from_path(args.db)

    total_queries = 0
    empty_queries = 0
    recall_hits = 0  # relevant docs found in top-k
    relevant_total = 0
    reciprocal_ranks: list[float] = []
    rows: list[dict] = []

    try:
        for item in manifest.get("items", []):
            name = item.get("name", "?")
            relevant = item.get("relevant_corpus_docs") or []
            expected = item.get("expected_knowledge") or []
            if not relevant and not expected:
                continue  # non-knowledge challenge
            queries = _probe_queries(expected, name)
            item_rank: list[float] = []
            item_recall_hits = 0
            for query in queries:
                total_queries += 1
                results = service.search(query, top_k=args.top_k)
                if not results:
                    empty_queries += 1
                    rows.append({"challenge": name, "query": query, "hits": 0, "relevant_in_top_k": [], "rr": 0.0})
                    continue
                urls = [r.provenance.get("source_url", "") for r in results]
                hit = [rel for rel in relevant if any(rel in u for u in urls)]
                rr = 0.0
                for i, u in enumerate(urls, start=1):
                    if any(rel in u for rel in relevant):
                        rr = 1.0 / i
                        break
                if hit:
                    item_recall_hits += 1
                if rr:
                    item_rank.append(rr)
                rows.append({
                    "challenge": name,
                    "query": query,
                    "hits": len(results),
                    "relevant_in_top_k": hit,
                    "rr": rr,
                })
            relevant_total += len(relevant) * len(queries)
            recall_hits += item_recall_hits
            if item_rank:
                reciprocal_ranks.extend(item_rank)

        mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
        recall_at_k = recall_hits / relevant_total if relevant_total else 0.0

        print("=== RAG retrieval quality (offline, zero API cost) ===")
        print(f"knowledge challenges probed: {len({r['challenge'] for r in rows})}")
        print(f"probe queries: {total_queries}  empty-result queries: {empty_queries} ({empty_queries/total_queries*100:.0f}%)")
        print(f"recall@k (relevant docs surfaced): {recall_hits}/{relevant_total} = {recall_at_k:.2f}")
        print(f"MRR (first relevant doc rank): {mrr:.3f}")
        print()
        for r in rows:
            mark = "  " if r["relevant_in_top_k"] else "!!"
            print(f"{mark} [{r['challenge']}] q={r['query']!r} hits={r['hits']} rr={r['rr']:.2f} relevant={r['relevant_in_top_k']}")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
