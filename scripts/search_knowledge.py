#!/usr/bin/env python3
"""Search the local Stage 2 FTS5 knowledge index and print provenance as JSON."""

from __future__ import annotations

import argparse
import json

from backend.knowledge.models import SearchRequest
from backend.knowledge.store import SQLiteKnowledgeBase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--db", default="logs/knowledge.sqlite3")
    parser.add_argument("--source-type")
    parser.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    metadata: dict[str, str] = {}
    for item in args.metadata:
        if "=" not in item:
            parser.error(f"metadata must use KEY=VALUE: {item!r}")
        key, value = item.split("=", 1)
        if not key:
            parser.error("metadata key cannot be empty")
        metadata[key] = value

    knowledge = SQLiteKnowledgeBase(args.db)
    try:
        results = knowledge.search(
            SearchRequest(
                query=args.query,
                source_type=args.source_type,
                metadata=metadata,
                top_k=args.top_k,
            )
        )
        print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))
    finally:
        knowledge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
