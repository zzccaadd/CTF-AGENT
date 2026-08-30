#!/usr/bin/env python3
"""Index local Markdown/text files into the Stage 2 lexical knowledge base."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.knowledge.store import SQLiteKnowledgeBase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing knowledge documents")
    parser.add_argument("--db", default="logs/knowledge.sqlite3")
    parser.add_argument("--source-type", required=True, help="Explicit corpus/source type")
    parser.add_argument("--trust-level", choices=("official", "high", "medium", "low"), default="medium")
    parser.add_argument("--pattern", default="*.md", help="File glob relative to root")
    parser.add_argument("--max-chars", type=int, default=1600)
    args = parser.parse_args()

    base = args.root.resolve()
    files = sorted(path for path in base.glob(args.pattern) if path.is_file())
    if not files:
        parser.error(f"no files matched {args.pattern!r} under {base}")
    knowledge = SQLiteKnowledgeBase(args.db)
    try:
        for path in files:
            knowledge.ingest(
                title=path.stem,
                text=path.read_text(encoding="utf-8"),
                source_type=args.source_type,
                source_url=str(path),
                trust_level=args.trust_level,
                metadata={"path": str(path), "format": path.suffix.lstrip(".")},
                max_chars=args.max_chars,
            )
    finally:
        knowledge.close()
    print(f"indexed {len(files)} document(s) into {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
