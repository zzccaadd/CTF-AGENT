#!/usr/bin/env python3
"""Index local Markdown/text files into the Stage 2 lexical knowledge base."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.knowledge.store import SQLiteKnowledgeBase

ALLOWED_SOURCE_TYPES = ("official", "reference", "internal_notes")
# Benchmark corpus must never be indexed as RAG knowledge: the policy guard
# lives at the store layer (source_type) AND here at the path layer, so an
# accidental `--root benchmarks/...` run is rejected before ingestion.
REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOTS = tuple(
    root.resolve() for root in (REPO_ROOT / "benchmarks",) if (REPO_ROOT / "benchmarks").exists()
)


def _validate_root(root: Path) -> None:
    resolved = root.resolve()
    if any(resolved == bench or bench in resolved.parents for bench in BENCHMARK_ROOTS):
        raise SystemExit(
            f"refusing to index benchmark corpus root: {root}\n"
            "benchmark challenges, attachments and flags must never enter the RAG corpus"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing knowledge documents")
    parser.add_argument("--db", default="logs/knowledge.sqlite3")
    parser.add_argument("--source-type", required=True, choices=ALLOWED_SOURCE_TYPES, help="Controlled corpus/source type")
    parser.add_argument("--trust-level", choices=("official", "high", "medium", "low"), default="medium")
    parser.add_argument("--pattern", default="*.md", help="File glob relative to root")
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--report", type=Path, help="JSON build report path")
    args = parser.parse_args()

    base = args.root.resolve()
    _validate_root(base)
    files = sorted(path for path in base.glob(args.pattern) if path.is_file())
    if not files:
        parser.error(f"no files matched {args.pattern!r} under {base}")
    knowledge = SQLiteKnowledgeBase(args.db)
    report = {"root": str(base), "source_type": args.source_type, "files": [], "failed": [], "chunks": 0, "deleted_documents": 0}
    try:
        for path in files:
            try:
                document = knowledge.ingest(
                    title=path.stem,
                    text=path.read_text(encoding="utf-8"),
                    source_type=args.source_type,
                    source_url=str(path),
                    trust_level=args.trust_level,
                    # Relative path keeps manifests comparable across machines;
                    # source_url keeps the absolute path for stale-doc cleanup.
                    metadata={"path": str(path.relative_to(base)), "format": path.suffix.lstrip(".")},
                    max_chars=args.max_chars,
                )
                chunks = knowledge.chunk_count(document.document_id)
                report["files"].append({"path": str(path), "document_id": document.document_id, "content_hash": document.content_hash, "chunks": chunks})
                report["chunks"] += chunks
            except (OSError, UnicodeError, ValueError) as exc:
                report["failed"].append({"path": str(path), "error": str(exc)})
        report["deleted_documents"] = knowledge.delete_source_except(
            args.source_type, {str(path) for path in files}, source_prefix=str(base) + "/"
        )
    finally:
        knowledge.close()
    report_path = args.report or Path(args.db).with_suffix(".manifest.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if report["failed"]:
        print(f"indexed {len(report['files'])} document(s), failed {len(report['failed'])}; report={report_path}")
        return 2
    print(f"indexed {len(files)} document(s) into {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
