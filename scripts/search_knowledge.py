#!/usr/bin/env python3
"""Search the local Stage 2 FTS5 knowledge index and print provenance as JSON."""

from __future__ import annotations

import argparse
import json

from backend.knowledge.service import KnowledgeService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--db", default="logs/knowledge.sqlite3")
    parser.add_argument("--source-type")
    parser.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    metadata: dict[str, str] = {}
    for item in args.metadata:
        if "=" not in item:
            parser.error(f"metadata must use KEY=VALUE: {item!r}")
        key, value = item.split("=", 1)
        if not key:
            parser.error("metadata key cannot be empty")
        metadata[key] = value

    try:
        knowledge = KnowledgeService.from_path(args.db)
    except OSError as exc:
        parser.exit(2, f"knowledge database unavailable: {exc}\n")
    try:
        try:
            results = knowledge.search(
                args.query,
                source_type=args.source_type,
                metadata=metadata,
                top_k=args.top_k,
            )
        except ValueError as exc:
            parser.exit(2, f"invalid search request: {exc}\n")
        print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))
    finally:
        knowledge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
