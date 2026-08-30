#!/usr/bin/env python3
"""Search the local Stage 2 FTS5 knowledge index and print provenance as JSON.

Exit codes (stable contract):
  0  success (search printed results / document deleted)
  1  --delete target document not found
  2  invalid request parameters or unreadable database
  3  database file does not exist (build it first with
     scripts/bootstrap_knowledge.py or scripts/index_knowledge.py)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.knowledge.service import KnowledgeService
from backend.knowledge.store import SQLiteKnowledgeBase

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_INVALID = 2
EXIT_NO_DB = 3


def _require_db(db: str) -> Path:
    """Fail fast with a stable code when the knowledge DB has never been built."""
    path = Path(db)
    if not path.exists():
        raise FileNotFoundError(db)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", help="search query (required unless --delete is used)")
    parser.add_argument("--db", default="logs/knowledge.sqlite3")
    parser.add_argument("--source-type")
    parser.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--delete", metavar="DOCUMENT_ID", help="delete one document and exit")
    args = parser.parse_args()

    if args.delete and args.query:
        parser.error("--delete cannot be combined with a search query")
    if not args.delete and not args.query:
        parser.error("a search query or --delete is required")

    try:
        db_path = _require_db(args.db)
    except FileNotFoundError:
        print(
            f"knowledge database does not exist: {args.db}\n"
            "build it first: .venv/bin/python scripts/bootstrap_knowledge.py",
            file=sys.stderr,
        )
        return EXIT_NO_DB

    metadata: dict[str, str] = {}
    for item in args.metadata:
        if "=" not in item:
            parser.error(f"metadata must use KEY=VALUE: {item!r}")
        key, value = item.split("=", 1)
        if not key:
            parser.error("metadata key cannot be empty")
        metadata[key] = value

    if args.delete:
        try:
            knowledge = SQLiteKnowledgeBase(db_path)
        except OSError as exc:
            parser.exit(EXIT_INVALID, f"knowledge database unavailable: {exc}\n")
        try:
            deleted = knowledge.delete(args.delete)
        finally:
            knowledge.close()
        if not deleted:
            return EXIT_NOT_FOUND
        print(json.dumps({"deleted": args.delete}, ensure_ascii=False))
        return EXIT_OK

    try:
        knowledge = KnowledgeService.from_path(db_path)
    except OSError as exc:
        parser.exit(EXIT_INVALID, f"knowledge database unavailable: {exc}\n")
    try:
        try:
            results = knowledge.search(
                args.query,
                source_type=args.source_type,
                metadata=metadata,
                top_k=args.top_k,
            )
        except ValueError as exc:
            parser.exit(EXIT_INVALID, f"invalid search request: {exc}\n")
        print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))
    finally:
        knowledge.close()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
