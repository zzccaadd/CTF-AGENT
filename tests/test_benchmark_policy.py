from __future__ import annotations

from backend.agents.codex_solver import sandbox_tools
from backend.agents.swarm import build_solver_slots
from backend.benchmarks.models import BenchmarkLimits
from backend.prompts import ChallengeMeta, build_prompt


def test_default_benchmark_limits_are_fixed_and_offline() -> None:
    limits = BenchmarkLimits()
    assert limits.model == "codex/gpt-5.6-luna"
    assert limits.timeout_seconds == 1_800
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


def test_offline_prompt_states_network_policy() -> None:
    prompt = build_prompt(ChallengeMeta(name="demo"), [], allow_internet=False)
    assert "General internet and external webhooks are disabled" in prompt
