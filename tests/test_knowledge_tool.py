"""Offline protocol-level tests for the Codex search_knowledge tool contract.

These tests drive `CodexSolver._exec_tool` directly (no app-server) and pin
the agent-facing contract: schema shape, parameter defaults, result JSON
shape with provenance, the empty-result message and failure isolation.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.agents.codex_solver import SANDBOX_TOOLS, CodexSolver
from backend.knowledge.service import KnowledgeService
from backend.knowledge.store import SQLiteKnowledgeBase


def _tool_schema() -> dict:
    tool = next(tool for tool in SANDBOX_TOOLS if tool["name"] == "search_knowledge")
    return tool["inputSchema"]


def _solver_with(service: KnowledgeService | None) -> CodexSolver:
    solver = object.__new__(CodexSolver)
    solver.knowledge_service = service
    solver._knowledge_queries = 0
    solver._knowledge_hits = 0
    solver._knowledge_chars = 0
    solver._knowledge_elapsed_ms = 0.0
    solver._knowledge_tool_calls = 0
    solver._knowledge_cache_hits = 0
    solver._knowledge_budget_rejections = 0
    solver._turn_knowledge_queries = 0
    solver._knowledge_cache = {}
    solver._knowledge_turn_budget = 1
    solver._knowledge_solver_budget = 8
    solver._knowledge_context_budget = 32_000
    solver._knowledge_challenge_budget = None
    solver._step_count = 0
    solver.settings = SimpleNamespace(knowledge_top_k=5)
    solver.tracer = SimpleNamespace(event=lambda *_args, **_kwargs: None)
    solver.evidence_board = None
    return solver


def test_tool_schema_contract() -> None:
    schema = _tool_schema()
    assert schema["type"] == "object"
    assert schema["required"] == ["query"]
    props = schema["properties"]
    assert props["top_k"] == {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}
    assert set(props) == {"query", "source_type", "metadata", "top_k"}


def test_tool_disabled_service_returns_readable_message() -> None:
    solver = _solver_with(None)
    import asyncio

    message = asyncio.run(solver._exec_tool("search_knowledge", {"query": "z3"}))
    assert message == "Knowledge search is disabled for this run."


def test_tool_success_returns_json_with_provenance(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    document = knowledge.ingest(
        title="ELF guide",
        text="# ELF\n\nThe e_entry field stores the entry address.",
        source_type="official",
        source_url="file:///docs/elf.md",
        metadata={"topic": "binary"},
    )
    service = KnowledgeService(knowledge)
    solver = _solver_with(service)
    import asyncio

    try:
        payload = json.loads(asyncio.run(solver._exec_tool("search_knowledge", {"query": "e_entry"})))
    finally:
        service.close()

    assert payload["diagnostic"]["status"] == "ok"
    assert solver._knowledge_queries == 1
    assert solver._knowledge_hits == 1
    assert solver._knowledge_chars > 0
    results = payload["results"]
    assert len(results) == 1
    provenance = results[0]["provenance"]
    assert provenance["document_id"] == document.document_id
    assert provenance["chunk_id"] == f"{document.document_id}:0"
    assert provenance["source_url"] == "file:///docs/elf.md"
    assert provenance["trust_level"] == "medium"
    assert provenance["line_start"] == 1
    assert results[0]["metadata"]["topic"] == "binary"


def test_tool_empty_result_returns_readable_message(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    service = KnowledgeService(knowledge)
    solver = _solver_with(service)
    import asyncio

    try:
        message = asyncio.run(solver._exec_tool("search_knowledge", {"query": "no-such-topic-xyz"}))
    finally:
        service.close()

    assert "no usable results" in message
    assert "Continue with sandbox analysis" in message
    assert solver._knowledge_queries == 1
    assert solver._knowledge_hits == 0


def test_tool_top_k_default_and_bounds_are_applied(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    for index in range(3):
        knowledge.ingest(
            title=f"Doc {index}",
            text=f"shared z3 knowledge #{index}",
            source_type="official",
            source_url=f"file:///docs/{index}.md",
        )
    service = KnowledgeService(knowledge)
    solver = _solver_with(service)
    import asyncio

    try:
        payload = json.loads(asyncio.run(solver._exec_tool("search_knowledge", {"query": "shared z3"})))
        assert len(payload["results"]) == 3

        solver._knowledge_queries = 0
        solver._knowledge_hits = 0
        solver._turn_knowledge_queries = 0  # fresh turn
        limited = json.loads(asyncio.run(solver._exec_tool("search_knowledge", {"query": "shared z3", "top_k": 2})))
        assert len(limited["results"]) == 2

        solver._turn_knowledge_queries = 0
        with pytest.raises(ValueError):
            asyncio.run(solver._exec_tool("search_knowledge", {"query": "shared z3", "top_k": 0}))
    finally:
        service.close()


def test_tool_failure_is_isolated_to_the_call(tmp_path) -> None:
    """Storage failure surfaces as an empty result + diagnostic; the caller
    (`_handle_tool_call`) converts remaining errors into readable text."""
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    service = KnowledgeService(knowledge)
    knowledge.close()  # simulate store loss after service creation

    solver = _solver_with(service)
    import asyncio

    message = asyncio.run(solver._exec_tool("search_knowledge", {"query": "anything"}))
    assert "no usable results" in message
    assert service.last_diagnostic["status"] == "error"


def test_tool_turn_budget_rejects_second_query_in_same_turn(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Guide", text="z3 guide", source_type="official")
    service = KnowledgeService(knowledge)
    solver = _solver_with(service)
    import asyncio

    try:
        asyncio.run(solver._exec_tool("search_knowledge", {"query": "z3"}))
        assert solver._knowledge_queries == 1
        # Same turn: second call must be budget-rejected, not executed.
        second = asyncio.run(solver._exec_tool("search_knowledge", {"query": "gdb"}))
        assert "budget exhausted" in second
        assert solver._knowledge_budget_rejections == 1
        assert solver._knowledge_queries == 1  # no new backend query
        # Next turn: budget resets and the query runs.
        solver._turn_knowledge_queries = 0
        third = asyncio.run(solver._exec_tool("search_knowledge", {"query": "guide"}))
        assert solver._knowledge_queries == 2
        assert "guide" in third
    finally:
        service.close()


def test_tool_solver_budget_rejects_after_limit(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    service = KnowledgeService(knowledge)
    solver = _solver_with(service)
    solver._knowledge_solver_budget = 2
    import asyncio

    try:
        for query in ("zz1", "zz2"):
            asyncio.run(solver._exec_tool("search_knowledge", {"query": query}))
            solver._turn_knowledge_queries = 0  # simulate fresh turns
        assert solver._knowledge_queries == 2
        solver._turn_knowledge_queries = 0
        message = asyncio.run(solver._exec_tool("search_knowledge", {"query": "zz3"}))
        assert "queries max per challenge" in message
        assert solver._knowledge_budget_rejections == 1
    finally:
        service.close()


def test_tool_same_query_is_cache_hit_not_second_query(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    knowledge.ingest(title="Guide", text="z3 guide", source_type="official")
    service = KnowledgeService(knowledge)
    solver = _solver_with(service)
    import asyncio

    try:
        asyncio.run(solver._exec_tool("search_knowledge", {"query": "z3", "top_k": 2}))
        assert solver._knowledge_queries == 1
        solver._turn_knowledge_queries = 0  # fresh turn
        second = asyncio.run(solver._exec_tool("search_knowledge", {"query": "z3", "top_k": 2}))
        payload = json.loads(second)
        assert payload["diagnostic"]["query_outcome"] == "cache_hit"
        assert solver._knowledge_queries == 1  # not counted as a backend query
        assert solver._knowledge_cache_hits == 1
        assert solver._knowledge_tool_calls == 2
        # A DIFFERENT query is not a cache hit.
        solver._turn_knowledge_queries = 0
        asyncio.run(solver._exec_tool("search_knowledge", {"query": "gdb", "top_k": 2}))
        assert solver._knowledge_queries == 2
    finally:
        service.close()


def test_tool_query_outcome_mapping(tmp_path) -> None:
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    service = KnowledgeService(knowledge)
    solver = _solver_with(service)
    import asyncio

    try:
        no_hit = asyncio.run(solver._exec_tool("search_knowledge", {"query": "qqqq-zzzz-nothing"}))
        assert "no usable results" in no_hit
        assert solver._knowledge_cache[(solver._knowledge_cache_key({"query": "qqqq-zzzz-nothing"}))][1]["query_outcome"] == "no_hit"
        solver._turn_knowledge_queries = 0
        invalid = asyncio.run(solver._exec_tool("search_knowledge", {"query": "   "}))
        assert "no usable results" in invalid
        outcome = solver._knowledge_cache[solver._knowledge_cache_key({"query": "   "})][1]["query_outcome"]
        assert outcome == "invalid_query"
    finally:
        service.close()


def test_shared_challenge_budget_is_consumed_across_solvers() -> None:
    from backend.knowledge.budget import KnowledgeBudget

    budget = KnowledgeBudget(2)
    assert budget.consume()
    assert budget.consume()
    assert not budget.consume()
    assert budget.remaining() == 0
    with pytest.raises(ValueError):
        KnowledgeBudget(0)


def test_tool_budget_rejection_records_trace_outcome(tmp_path) -> None:
    """Every refused call must leave a query_outcome=budget_exhausted trace
    event so the eval can reconstruct rejected knowledge calls (S3.1)."""
    events: list[dict] = []
    knowledge = SQLiteKnowledgeBase(tmp_path / "knowledge.sqlite3")
    service = KnowledgeService(knowledge)
    solver = _solver_with(service)
    solver.tracer = SimpleNamespace(event=lambda *_args, **kwargs: events.append(kwargs))
    solver._knowledge_solver_budget = 0  # force immediate rejection
    import asyncio

    try:
        message = asyncio.run(solver._exec_tool("search_knowledge", {"query": "z3"}))
        assert "budget exhausted" in message
        assert solver._knowledge_budget_rejections == 1
        assert any(e.get("query_outcome") == "budget_exhausted" for e in events)
    finally:
        service.close()


def test_assistant_reasoning_is_recorded_to_trace() -> None:
    """The model's commentary/final_answer text must land in the trace so the
    reasoning behind tool choices (incl. knowledge calls) is auditable."""
    events: list[dict] = []
    solver = _solver_with(None)
    solver.tracer = SimpleNamespace(event=lambda *_args, **kwargs: events.append(kwargs))

    solver._record_assistant_message("commentary", "I should check if this cipher pattern is known.")
    solver._record_assistant_message("final_answer", '{"type":"flag_found","flag":"CTF{x}"}')
    solver._record_assistant_message(None, "plain message")

    assert events[0]["phase"] == "commentary"
    assert "cipher pattern" in events[0]["text"]
    assert events[1]["phase"] == "final_answer"
    assert events[2]["phase"] == "message"
    # Long reasoning is truncated to keep traces bounded.
    solver._record_assistant_message("commentary", "x" * 5000)
    assert len(events[3]["text"]) == 4000
