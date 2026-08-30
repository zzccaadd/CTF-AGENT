from __future__ import annotations

from backend.knowledge.models import SearchRequest
from backend.knowledge.store import SQLiteKnowledgeBase
from scripts.bootstrap_knowledge import build_corpus


def test_bootstrap_indexes_only_controlled_source_directories(tmp_path) -> None:
    root = tmp_path / "knowledge"
    (root / "official" / "elf").mkdir(parents=True)
    (root / "reference").mkdir()
    (root / "internal_notes").mkdir()
    (root / "official" / "elf" / "headers.md").write_text(
        "# ELF\n\nThe e_entry field stores the entry address.", encoding="utf-8"
    )
    (root / "secret.md").write_text("flag should not be indexed", encoding="utf-8")

    report = build_corpus(root, str(tmp_path / "knowledge.sqlite3"))

    assert report["failed"] == []
    assert [item["path"] for item in report["files"]] == ["official/elf/headers.md"]
    assert report["chunks"] == 1


def test_bootstrap_preserves_front_matter_provenance_and_body_lines(tmp_path) -> None:
    root = tmp_path / "knowledge"
    source = root / "official" / "elf"
    source.mkdir(parents=True)
    (source / "headers.md").write_text(
        "---\n"
        "source_url: https://example.test/elf\n"
        "source_title: ELF specification notes\n"
        "source_version: 1.2\n"
        "publisher: Example Foundation\n"
        "license: CC-BY-4.0\n"
        "retrieved_at: 2026-08-31\n"
        "---\n"
        "# ELF\n\nThe e_entry field stores the entry address.\n",
        encoding="utf-8",
    )

    database = str(tmp_path / "knowledge.sqlite3")
    report = build_corpus(root, database)

    assert report["failed"] == []
    assert report["files"][0]["chunks"] == 1
    assert report["files"][0]["source_url"] == "https://example.test/elf"
    assert report["files"][0]["provenance"]["license"] == "CC-BY-4.0"
    store = SQLiteKnowledgeBase(database)
    try:
        result = store.search(SearchRequest(query="entry address"))
        assert result[0].provenance["source_url"] == "https://example.test/elf"
        assert result[0].metadata["source_version"] == "1.2"
        assert result[0].provenance["line_start"] == 9
    finally:
        store.close()


def test_bootstrap_removes_stale_url_documents(tmp_path) -> None:
    """Removing a frontmatter-URL file must drop its old document: cleanup
    matches the STORED source_url (the URL), not the local file path."""
    root = tmp_path / "knowledge"
    source = root / "official" / "elf"
    source.mkdir(parents=True)
    (source / "a.md").write_text(
        "---\nsource_url: https://example.test/a\n---\n\n# A\n\nA content.\n",
        encoding="utf-8",
    )
    (source / "b.md").write_text(
        "---\nsource_url: https://example.test/b\n---\n\n# B\n\nB content.\n",
        encoding="utf-8",
    )
    database = str(tmp_path / "knowledge.sqlite3")

    first = build_corpus(root, database)
    assert [item["path"] for item in first["files"]] == ["official/elf/a.md", "official/elf/b.md"]

    (source / "b.md").unlink()
    second = build_corpus(root, database)

    assert [item["path"] for item in second["files"]] == ["official/elf/a.md"]
    assert second["deleted_documents"] == 1
    store = SQLiteKnowledgeBase(database)
    try:
        assert [hit.provenance["source_url"] for hit in store.search(SearchRequest("content"))] == [
            "https://example.test/a"
        ]
    finally:
        store.close()


def test_bootstrap_keeps_previous_doc_when_reingest_fails(tmp_path) -> None:
    """A file that parses but fails to re-ingest keeps its previous index so a
    transient build error cannot silently wipe searchable knowledge."""
    root = tmp_path / "knowledge"
    source = root / "official" / "elf"
    source.mkdir(parents=True)
    target = source / "guide.md"
    target.write_text(
        "---\nsource_url: https://example.test/guide\n---\n\n# Guide\n\nUseful z3 content.\n",
        encoding="utf-8",
    )
    database = str(tmp_path / "knowledge.sqlite3")
    build_corpus(root, database)

    target.write_text("---\nsource_url: https://example.test/guide\n---\n", encoding="utf-8")
    report = build_corpus(root, database)

    assert report["failed"] and report["failed"][0]["path"] == "official/elf/guide.md"
    assert report["deleted_documents"] == 0
    store = SQLiteKnowledgeBase(database)
    try:
        assert store.search(SearchRequest("z3"))
    finally:
        store.close()
