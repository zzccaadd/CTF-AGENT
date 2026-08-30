from __future__ import annotations

from backend.agents.codex_solver import sandbox_tools
from backend.agents.swarm import build_solver_slots
from backend.benchmarks.models import BenchmarkLimits
from backend.benchmarks.runner import _timeout_result
from backend.cost_tracker import CostTracker
from backend.prompts import ChallengeMeta, build_prompt


def test_default_benchmark_limits_are_fixed_and_offline() -> None:
    limits = BenchmarkLimits()
    assert limits.model == "codex/gpt-5.5"
    assert limits.timeout_seconds == 300
    assert limits.max_tokens == 1_000_000
    assert limits.allow_internet is False
    assert limits.attempts == 1
    assert limits.concurrency == 1
    assert limits.solvers_per_swarm == 3
    assert limits.max_solvers_per_swarm == 3


def test_single_model_solver_replicas_get_unique_labels_and_cap_at_three() -> None:
    slots = build_solver_slots(["codex/gpt-5.5"], solvers_per_model=7, max_solvers=3)
    assert [slot.model_spec for slot in slots] == ["codex/gpt-5.5"] * 3
    assert [slot.label for slot in slots] == [
        "codex/gpt-5.5#1",
        "codex/gpt-5.5#2",
        "codex/gpt-5.5#3",
    ]


def test_offline_codex_tools_hide_host_network_helpers() -> None:
    names = {tool["name"] for tool in sandbox_tools(False)}
    assert "web_fetch" not in names
    assert "webhook_create" not in names
    assert "webhook_get_requests" not in names
    assert {"bash", "submit_flag", "read_file"} <= names


def test_codex_knowledge_tool_can_be_disabled() -> None:
    assert "search_knowledge" in {tool["name"] for tool in sandbox_tools(False)}
    assert "search_knowledge" not in {tool["name"] for tool in sandbox_tools(False, False)}


def test_offline_prompt_states_network_policy() -> None:
    prompt = build_prompt(ChallengeMeta(name="demo"), [], allow_internet=False)
    assert "General internet and external webhooks are disabled" in prompt


def test_prompt_knowledge_section_follows_knowledge_enabled() -> None:
    enabled = build_prompt(
        ChallengeMeta(name="demo"), [], allow_internet=False, knowledge_enabled=True
    )
    assert "## Knowledge Base" in enabled
    assert "search_knowledge" in enabled
    assert "ONE knowledge query per turn" in enabled

    disabled = build_prompt(ChallengeMeta(name="demo"), [], allow_internet=False)
    assert "## Knowledge Base" not in disabled


def test_timeout_result_preserves_solver_diagnostics() -> None:
    class Tracer:
        path = "/tmp/demo-trace.jsonl"

    class Solver:
        _step_count = [7]
        tracer = Tracer()

    swarm = type(
        "SwarmStub",
        (),
        {
            "solvers": {"codex/gpt-5.5#1": Solver()},
            "findings": {"codex/gpt-5.5#1": "inspected source.py"},
            "confirmed_flag": None,
        },
    )()
    tracker = CostTracker()
    result = _timeout_result(swarm, tracker)

    assert result.status == "timeout"
    assert result.step_count == 7
    assert result.findings_summary == "inspected source.py"
    assert result.log_path == "/tmp/demo-trace.jsonl"


def test_swarm_knowledge_metrics_sums_all_solvers_not_just_winner() -> None:
    from backend.benchmarks.runner import _swarm_knowledge_metrics

    class SolverA:
        _knowledge_queries = 3
        _knowledge_hits = 4
        _knowledge_chars = 500
        _knowledge_elapsed_ms = 1.2
        _knowledge_tool_calls = 3
        _knowledge_cache_hits = 1
        _knowledge_budget_rejections = 1

    class SolverB:
        _knowledge_queries = 2
        _knowledge_hits = 2
        _knowledge_chars = 300
        _knowledge_elapsed_ms = 0.8
        _knowledge_tool_calls = 2
        _knowledge_cache_hits = 0
        _knowledge_budget_rejections = 0

    swarm = type("SwarmStub", (), {"solvers": {"#1": SolverA(), "#2": SolverB()}})()
    metrics = _swarm_knowledge_metrics(swarm)

    assert metrics["knowledge_queries"] == 5
    assert metrics["knowledge_hits"] == 6
    assert metrics["knowledge_chars"] == 800
    assert metrics["knowledge_elapsed_ms"] == 2.0
    assert metrics["knowledge_tool_calls"] == 5
    assert metrics["knowledge_cache_hits"] == 1
    assert metrics["knowledge_budget_rejections"] == 1
