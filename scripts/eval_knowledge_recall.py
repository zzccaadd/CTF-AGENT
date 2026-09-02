#!/usr/bin/env python3
"""Fine-grained offline RAG retrieval evaluation (ragas-style, zero API cost).

For every knowledge-tagged challenge in a manifest, generate probe queries
from its `expected_knowledge` terms and measure whether the corpus retrieval
returns the annotated `relevant_corpus_docs` (the qrels ground truth):

- recall@k:   fraction of relevant docs retrieved within top-k
- mrr:        mean reciprocal rank of the first relevant doc
- hit_docs:   which relevant docs actually surfaced (per query)
- probe_count / empty_hits:  queries with zero results (tool-surface / corpus gap)

Anchors may be plain strings ("reference/crypto/xor-variants.md") or dicts
{"doc": "...", "section": "..."} for chunk-level anchoring (a section hint
requires the retrieved chunk's section to match). Per-anchor status grouping
(curated / reused / inferred / gap) reports how reliable each metric slice is.

This runs purely against logs/knowledge.sqlite3 — no model, no API cost — so
it can be looped during development to verify "does the knowledge base answer
the questions the challenge needs" before paying for full solve runs.

Usage:
  python scripts/eval_knowledge_recall.py [--manifest benchmarks/rag_eval/qrels_v1.json] [--db logs/knowledge.sqlite3] [--top-k 5]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from backend.knowledge.service import KnowledgeService

DIFFICULTY_PREFIX_RE = re.compile(r"^\[\s*[^\]]*\]\s*")


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
    # Drop difficulty prefixes like "[Very Easy]" so the query stays clean.
    queries.append(DIFFICULTY_PREFIX_RE.sub("", name).strip())
    return queries


def _normalize_anchor(anchor: str | dict) -> dict:
    if isinstance(anchor, str):
        return {"doc": anchor, "section": None}
    return {"doc": str(anchor.get("doc", "")), "section": anchor.get("section")}


def _anchor_matches(result, anchor: dict) -> bool:
    """A result matches an anchor if its doc path contains the anchor doc and,
    when a section hint is given, its chunk section overlaps the hint."""
    url = result.provenance.get("source_url") or ""
    if anchor["doc"] not in url:
        return False
    section = anchor.get("section")
    if section:
        result_section = result.provenance.get("section") or ""
        if section not in result_section and result_section not in section:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rag_eval/qrels_v1.json"))
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
    # Per anchor_status aggregates (curated/reused/inferred/gap).
    status_agg: dict[str, dict] = defaultdict(
        lambda: {"queries": 0, "empty": 0, "recall_hits": 0, "relevant_total": 0, "rr": []}
    )
    gap_items: list[str] = []

    try:
        for item in manifest.get("items", []):
            name = item.get("name", "?")
            status = item.get("anchor_status", "?")
            relevant_raw = item.get("relevant_corpus_docs") or []
            anchors = [_normalize_anchor(a) for a in relevant_raw]
            expected = item.get("expected_knowledge") or []
            if not anchors and not expected:
                continue  # non-knowledge challenge
            if not anchors:
                gap_items.append(name)  # corpus gap: knowledge needed, no anchor
            queries = _probe_queries(expected, name)
            item_rank: list[float] = []
            item_recall_hits = 0
            agg = status_agg[status]
            for query in queries:
                total_queries += 1
                agg["queries"] += 1
                results = service.search(query, top_k=args.top_k)
                if not results:
                    empty_queries += 1
                    agg["empty"] += 1
                    rows.append({"challenge": name, "status": status, "query": query, "hits": 0, "relevant_in_top_k": [], "rr": 0.0})
                    continue
                hit_anchors = []
                rr = 0.0
                for i, result in enumerate(results, start=1):
                    matched = [a["doc"] for a in anchors if _anchor_matches(result, a)]
                    if matched:
                        hit_anchors.extend(matched)
                        if not rr:
                            rr = 1.0 / i
                if hit_anchors:
                    item_recall_hits += 1
                if rr:
                    item_rank.append(rr)
                    agg["rr"].append(rr)
                rows.append({
                    "challenge": name,
                    "status": status,
                    "query": query,
                    "hits": len(results),
                    "relevant_in_top_k": sorted(set(hit_anchors)),
                    "rr": rr,
                })
            item_relevant_total = len(anchors) * len(queries)
            relevant_total += item_relevant_total
            agg["relevant_total"] += item_relevant_total
            recall_hits += item_recall_hits
            agg["recall_hits"] += item_recall_hits
            if item_rank:
                reciprocal_ranks.extend(item_rank)

        mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
        recall_at_k = recall_hits / relevant_total if relevant_total else 0.0

        print("=== RAG retrieval quality (offline, zero API cost) ===")
        print(f"manifest: {args.manifest}  top_k={args.top_k}")
        print(f"knowledge challenges probed: {len({r['challenge'] for r in rows})}")
        print(f"probe queries: {total_queries}  empty-result queries: {empty_queries} ({empty_queries/total_queries*100:.0f}%)")
        print(f"recall@k (relevant docs surfaced): {recall_hits}/{relevant_total} = {recall_at_k:.2f}")
        print(f"MRR (first relevant doc rank): {mrr:.3f}")
        print()
        print("--- per anchor_status ---")
        for status in ("curated", "reused", "inferred", "gap"):
            agg = status_agg.get(status)
            if not agg or not agg["queries"]:
                continue
            s_mrr = sum(agg["rr"]) / len(agg["rr"]) if agg["rr"] else 0.0
            s_recall = agg["recall_hits"] / agg["relevant_total"] if agg["relevant_total"] else 0.0
            print(
                f"  {status:<9} queries={agg['queries']:<3} empty={agg['empty']:>2} "
                f"recall@k={s_recall:.2f} MRR={s_mrr:.3f}"
            )
        if gap_items:
            print()
            print(f"--- corpus gaps ({len(gap_items)} challenges need knowledge with no anchor) ---")
            for name in gap_items:
                print(f"  !! {name}")
        print()
        for r in rows:
            mark = "  " if r["relevant_in_top_k"] else "!!"
            print(f"{mark} [{r['status'][:4]}|{r['challenge']}] q={r['query']!r} hits={r['hits']} rr={r['rr']:.2f} relevant={r['relevant_in_top_k']}")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
