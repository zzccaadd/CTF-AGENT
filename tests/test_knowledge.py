from __future__ import annotations

from backend.knowledge.indexer import split_text
from backend.knowledge.models import SearchRequest
from backend.knowledge.store import SQLiteKnowledgeBase


def test_split_text_keeps_sections_code_and_line_ranges() -> None:
    chunks = split_text("# Recon\n\nRead the port.\n\n## Exploit\n\n```bash\ncurl target\n```")
    assert len(chunks) == 2
    assert chunks[0].section == "Recon"
    assert "Read the port." in chunks[0].text
    assert chunks[1].section == "Exploit"
    assert "curl target" in chunks[1].text
    assert chunks[1].line_start == 5
    assert chunks[1].line_end == 9


def test_ingest_search_filters_and_preserves_provenance(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    document = knowledge.ingest(
        title="Format guide",
        text="# ELF\n\nThe ELF header contains an e_entry virtual address.",
        source_type="official",
        source_url="https://example.test/elf",
        trust_level="official",
        metadata={"topic": "binary", "tool_name": "readelf"},
    )
    knowledge.ingest(
        title="Unrelated guide",
        text="HTTP cookies use a name and value.",
        source_type="writeup",
        trust_level="low",
        metadata={"topic": "web"},
    )

    results = knowledge.search(
        SearchRequest("ELF e_entry", source_type="official", metadata={"topic": "binary"})
    )
    assert len(results) == 1
    result = results[0]
    assert result.document_id == document.document_id
    assert result.provenance["source_url"] == "https://example.test/elf"
    assert result.provenance["line_start"] == 1
    assert result.metadata["tool_name"] == "readelf"
    knowledge.close()


def test_ingest_replaces_chunks_and_delete_removes_search_results(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    document = knowledge.ingest(
        title="Changing notes",
        text="The first route uses z3.",
        source_type="notes",
    )
    assert knowledge.search(SearchRequest("z3"))
    knowledge.ingest(
        title="Changing notes",
        text="The second route uses pwntools.",
        source_type="notes",
        document_id=document.document_id,
    )
    assert not knowledge.search(SearchRequest("z3"))
    assert knowledge.search(SearchRequest("pwntools"))[0].document_id == document.document_id
    assert knowledge.delete(document.document_id)
    assert not knowledge.search(SearchRequest("pwntools"))
    assert not knowledge.delete(document.document_id)
    knowledge.close()


def test_reindexing_same_source_url_updates_document(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    first = knowledge.ingest(
        title="Tool docs",
        text="Old command uses gdb.",
        source_type="official",
        source_url="file:///docs/tool.md",
    )
    second = knowledge.ingest(
        title="Tool docs",
        text="New command uses pwntools.",
        source_type="official",
        source_url="file:///docs/tool.md",
    )
    assert second.document_id == first.document_id
    assert not knowledge.search(SearchRequest("gdb"))
    assert knowledge.search(SearchRequest("pwntools"))[0].document_id == first.document_id
    knowledge.close()


def test_benchmark_sources_are_rejected(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    try:
        knowledge.ingest(title="Raw task", text="flag", source_type="benchmark")
    except ValueError as exc:
        assert "benchmark" in str(exc)
    else:
        raise AssertionError("benchmark corpus was accepted into the RAG index")
    knowledge.close()


def test_trust_level_adjusts_equal_lexical_matches(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Low", text="format string exploitation", source_type="writeup", trust_level="low")
    knowledge.ingest(title="Official", text="format string exploitation", source_type="official", trust_level="official")
    results = knowledge.search(SearchRequest("format string exploitation", top_k=2))
    assert len(results) == 2
    assert results[0].provenance["trust_level"] == "official"
    knowledge.close()
