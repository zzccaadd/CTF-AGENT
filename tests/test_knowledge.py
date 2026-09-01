from __future__ import annotations

from backend.knowledge.indexer import split_text
from backend.knowledge.models import SearchRequest
from backend.knowledge.service import KnowledgeService
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


def test_service_applies_bounds_and_records_diagnostics(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Guide", text="z3 " * 300, source_type="official")
    service = KnowledgeService(knowledge, max_chars=40)

    results = service.search("z3", top_k=100)

    assert len(results) == 1
    assert len(results[0].text) == 40
    assert results[0].provenance["truncated"] is True
    assert service.last_diagnostic["status"] == "ok"
    assert service.last_diagnostic["returned_chars"] == 40
    assert service.search("   ") == []
    assert service.last_diagnostic["reason"] == "empty_query"
    service.close()


def test_service_isolates_storage_failure(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    service = KnowledgeService(knowledge)
    knowledge.close()

    assert service.search("anything") == []
    assert service.last_diagnostic["status"] == "error"


def test_service_excludes_unapproved_source_types(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Approved", text="shared z3 guide", source_type="official")
    knowledge.ingest(title="Fixture", text="shared z3 writeup", source_type="writeup")
    service = KnowledgeService(knowledge)

    results = service.search("shared z3")

    assert [result.source_type for result in results] == ["official"]
    service.close()


def test_schema_version_is_recorded(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    version = knowledge._conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 2
    knowledge.close()


def test_schema_migration_v1_to_v2_reindexes_cjk(tmp_path) -> None:
    """A v1 database (CJK runs as single tokens) must be rebuilt on open so
    per-character Chinese queries keep working after the upgrade."""
    db = tmp_path / "knowledge.sqlite3"
    knowledge = SQLiteKnowledgeBase(db)
    knowledge.ingest(title="指南", text="格式化字符串利用", source_type="official")
    chunk_id = knowledge._conn.execute("SELECT chunk_id FROM knowledge_chunks LIMIT 1").fetchone()[0]
    with knowledge._conn:
        # Simulate v1 FTS content: the whole CJK run is ONE token.
        knowledge._conn.execute("DELETE FROM knowledge_fts")
        knowledge._conn.execute(
            "INSERT INTO knowledge_fts(chunk_id, title, section, text) VALUES (?, ?, ?, ?)",
            (chunk_id, "指南", "", "格式化字符串利用"),
        )
        knowledge._conn.execute("PRAGMA user_version = 1")
    knowledge.close()

    knowledge = SQLiteKnowledgeBase(db)
    try:
        assert knowledge._conn.execute("PRAGMA user_version").fetchone()[0] == 2
        hits = knowledge.search(SearchRequest("格式化"))
        assert [hit.provenance["title"] for hit in hits] == ["指南"]
    finally:
        knowledge.close()


def test_service_returns_completed_slow_results_instead_of_fake_timeout(tmp_path) -> None:
    """A query that finishes after the deadline must still return results.

    The in-query progress handler enforces the hard deadline; post-hoc latency
    is diagnostic-only so cold caches cannot silently disable RAG."""
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Guide", text="slow but completed z3 guide", source_type="official")
    service = KnowledgeService(knowledge, timeout_ms=1)

    real_search = knowledge.search
    import time as _time

    def slow_search(request, *, timeout_ms=None):
        _time.sleep(0.05)
        return real_search(request, timeout_ms=timeout_ms)

    knowledge.search = slow_search  # type: ignore[method-assign]
    try:
        results = service.search("z3", top_k=5)
    finally:
        service.close()

    assert len(results) == 1
    assert service.last_diagnostic["status"] == "ok"
    assert "exceeded_timeout_ms" in service.last_diagnostic


def test_service_rejects_oversized_query_and_metadata(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    service = KnowledgeService(knowledge)

    assert service.search("z" * (KnowledgeService.MAX_QUERY_CHARS + 1)) == []
    assert service.last_diagnostic["reason"] == "query_too_long"

    try:
        service.search("z3", metadata={f"key{i}": "v" for i in range(KnowledgeService.MAX_METADATA_ITEMS + 1)})
    except ValueError:
        assert service.last_diagnostic["reason"] == "invalid_metadata"
    else:
        raise AssertionError("oversized metadata must be rejected")

    service.close()


def test_service_records_diagnostic_for_invalid_top_k(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    service = KnowledgeService(knowledge)
    try:
        service.search("z3", top_k=0)
    except ValueError:
        assert service.last_diagnostic["reason"] == "invalid_top_k"
    else:
        raise AssertionError("top_k=0 must be rejected")
    service.close()


def test_service_ignores_non_string_source_type(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Guide", text="z3 guide", source_type="official")
    service = KnowledgeService(knowledge)

    results = service.search("z3", source_type=123)  # model garbage must not crash
    assert len(results) == 1
    service.close()


def test_service_ignores_non_whitelisted_source_type_filter(tmp_path) -> None:
    """A model-supplied source_type outside the whitelist (e.g. "all",
    "ctf_pattern") must NOT zero out results: it is ignored, not treated as
    an exact-match filter. This was the root cause of 11 no_hit knowledge
    calls across the eval runs."""
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Guide", text="z3 guide", source_type="official")
    service = KnowledgeService(knowledge)

    for bad in ("all", "ctf_pattern", "ctf-technique-pattern", "ctf"):
        results = service.search("z3", source_type=bad)
        assert len(results) == 1, f"source_type={bad!r} must be ignored, got {len(results)}"

    # A whitelisted filter that yields zero hits falls back to all sources
    # (a plausible-but-wrong source_type, e.g. "internal_notes" for a
    # technique query, must not zero out results — v5 regression).
    fallback = service.search("z3", source_type="reference")
    assert len(fallback) == 1
    assert service.last_diagnostic.get("status") == "ok"
    assert service.last_diagnostic.get("fallback") is True
    assert service.last_diagnostic.get("requested_source_type") == "reference"
    service.close()


def test_fts_cjk_query_uses_per_character_prefix_recall(tmp_path) -> None:
    """unicode61 groups a contiguous CJK run into one index token, so the query
    side expands CJK into per-character prefix terms. This pins the documented
    Chinese query 口径: 格式化字符串 must recall 格式化字符串利用, and must not
    recall unrelated runs (字节对齐)."""
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="指南", text="格式化字符串利用", source_type="official")
    knowledge.ingest(title="对齐", text="字节对齐", source_type="reference")

    hits = knowledge.search(SearchRequest("格式化字符串"))
    assert [hit.provenance["title"] for hit in hits] == ["指南"]

    # A space inside the CJK run must not break recall.
    spaced = knowledge.search(SearchRequest("格式化 字符串"))
    assert [hit.provenance["title"] for hit in spaced] == ["指南"]

    assert [hit.provenance["title"] for hit in knowledge.search(SearchRequest("对齐"))] == ["对齐"]
    knowledge.close()


def test_fts_special_characters_are_sanitized_not_crashed(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Asm", text="x86-64 assembly calling convention", source_type="official")

    results = knowledge.search(SearchRequest('C++ "quoted" x86-64!?/'))
    assert len(results) == 1
    assert results[0].provenance["title"] == "Asm"
    # Pure punctuation queries yield no tokens and no crash.
    assert knowledge.search(SearchRequest("!!! ??? ###")) == []
    knowledge.close()
