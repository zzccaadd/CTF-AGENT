#!/usr/bin/env python3
"""Build the reviewed Stage 2 corpus from the knowledge/ directory tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from backend.knowledge.store import SCHEMA_VERSION, SQLiteKnowledgeBase

SOURCE_TYPES = ("official", "reference", "internal_notes")
PROVENANCE_KEYS = {
    "source_url",
    "source_title",
    "source_version",
    "publisher",
    "license",
    "retrieved_at",
    "topic",
    "tool_name",
    "cwe_id",
}


def read_markdown(path: Path) -> tuple[str, dict[str, str], int]:
    """Read optional YAML front matter and preserve body line numbers."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return text, {}, 0
    lines = text.splitlines(keepends=True)
    end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() in {"---", "..."}),
        None,
    )
    if end is None:
        raise ValueError("front matter starts with '---' but has no closing delimiter")
    raw = yaml.safe_load("".join(lines[1:end])) or {}
    if not isinstance(raw, dict):
        raise ValueError("front matter must be a mapping")
    provenance: dict[str, str] = {}
    for key in PROVENANCE_KEYS:
        value = raw.get(key)
        if value is not None:
            if isinstance(value, (dict, list, tuple, set)):
                raise ValueError(f"front matter field {key!r} must be scalar")
            provenance[key] = str(value)
    # Keep leading blank lines so indexer line_start/line_end refer to the source file.
    return "".join(lines[end + 1 :]), provenance, end + 1


def build_corpus(root: Path, database: str, *, max_chars: int = 1600) -> dict[str, Any]:
    root = root.resolve()
    knowledge = SQLiteKnowledgeBase(database)
    report: dict[str, Any] = {
        "root": str(root),
        "schema_version": SCHEMA_VERSION,
        "files": [],
        "failed": [],
        "chunks": 0,
        "deleted_documents": 0,
    }
    try:
        for source_type in SOURCE_TYPES:
            source_root = root / source_type
            source_root.mkdir(parents=True, exist_ok=True)
            files = sorted(
                path for path in source_root.rglob("*.md")
                if path.is_file() and path.name != "README.md" and not path.name.startswith("_")
            )
            keep_source_urls: set[str] = set()
            for path in files:
                try:
                    relative = path.relative_to(source_root)
                    category = relative.parts[0] if len(relative.parts) > 1 else "general"
                    text, provenance, line_offset = read_markdown(path)
                except (OSError, UnicodeError, ValueError) as exc:
                    report["failed"].append(
                        {"path": str(path.relative_to(root)), "source_type": source_type, "error": str(exc)}
                    )
                    continue
                # Files that parse keep their previous index even if ingest
                # fails below; only files we can no longer read are dropped.
                keep_source_urls.add(provenance.get("source_url", "") or str(path))
                try:
                    metadata = {
                        "path": str(path.relative_to(root)),
                        "format": path.suffix.lstrip("."),
                        "category": category,
                        **provenance,
                    }
                    document = knowledge.ingest(
                        title=provenance.get("source_title", path.stem),
                        text=text,
                        source_type=source_type,
                        source_url=provenance.get("source_url", str(path)),
                        trust_level="official" if source_type == "official" else "medium",
                        metadata=metadata,
                        max_chars=max_chars,
                        line_offset=line_offset,
                    )
                    chunks = knowledge.chunk_count(document.document_id)
                    report["files"].append(
                        {
                            "path": str(path.relative_to(root)),
                            "source_type": source_type,
                            "source_url": document.source_url,
                            "provenance": provenance,
                            "document_id": document.document_id,
                            "content_hash": document.content_hash,
                            "chunks": chunks,
                        }
                    )
                    report["chunks"] += chunks
                except (OSError, UnicodeError, ValueError) as exc:
                    report["failed"].append(
                        {"path": str(path.relative_to(root)), "source_type": source_type, "error": str(exc)}
                    )
            # Stale-doc cleanup must match the STORED source_url (frontmatter
            # URL or local path), not only local paths: use pure set membership
            # without a path prefix, otherwise removing a frontmatter-URL file
            # would leave its old document searchable forever.
            report["deleted_documents"] += knowledge.delete_source_except(
                source_type, keep_source_urls
            )
    finally:
        knowledge.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("knowledge"))
    parser.add_argument("--db", default="logs/knowledge.sqlite3")
    parser.add_argument("--report", type=Path, default=Path("logs/knowledge.manifest.json"))
    parser.add_argument("--max-chars", type=int, default=1600)
    args = parser.parse_args()
    report = build_corpus(args.root, args.db, max_chars=args.max_chars)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"indexed {len(report['files'])} document(s), chunks={report['chunks']}, report={args.report}")
    return 2 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
