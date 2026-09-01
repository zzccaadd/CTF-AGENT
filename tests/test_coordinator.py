"""Coordinator planner unit tests (scripted plans, no API key needed)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.agents.coordinator import (
    VERDICT_COMPLETE,
    VERDICT_COURSE_CORRECT,
    VERDICT_EXPLORE,
    Coordinator,
    CoordinatorPlan,
)


def _coordinator() -> Coordinator:
    settings = SimpleNamespace(coordinator_model="gpt-5.5", coordinator_turn_timeout_s=120)
    return Coordinator(settings, "demo", "run-1")


def test_parse_plan_extracts_verdict_intents_audit() -> None:
    text = (
        "Here is my reasoning.\n"
        '{"verdict": "course_correct", "intents": ['
        '{"goal": "Audit the binary for format-string", "rationale": "verified fact shows printf on stack", "depends_on": [], "from_facts": ["f1"]},'
        '{"goal": "Try padding oracle on the oracle service", "rationale": "CBC oracle confirmed", "depends_on": ["x"], "from_facts": ["f2"]}'
        '], "audit": ["intent 2 is based on verified fact f2", "ignored hypothesis h3"]}'
    )
    plan = Coordinator._parse_plan(text)
    assert plan.verdict == VERDICT_COURSE_CORRECT
    assert [i["goal"] for i in plan.intents] == [
        "Audit the binary for format-string",
        "Try padding oracle on the oracle service",
    ]
    assert plan.intents[0]["from_facts"] == ["f1"]
    assert len(plan.audit) == 2


def test_parse_plan_handles_garbage_and_bad_verdict() -> None:
    bad = Coordinator._parse_plan("no json here")
    assert bad.verdict == VERDICT_EXPLORE and bad.intents == [] and bad.raw

    wrong_verdict = Coordinator._parse_plan('{"verdict": "banana", "intents": []}')
    assert wrong_verdict.verdict == VERDICT_EXPLORE

    empty_goals = Coordinator._parse_plan(
        '{"verdict": "explore", "intents": [{"goal": "  "}, {"goal": "real task", "rationale": "r"}]}'
    )
    assert [i["goal"] for i in empty_goals.intents] == ["real task"]


def test_parse_plan_complete_verdict() -> None:
    plan = Coordinator._parse_plan('{"verdict": "complete", "intents": [], "audit": ["flag proven"]}')
    assert plan.verdict == VERDICT_COMPLETE


def test_propose_skips_empty_and_duplicate_intents() -> None:
    coordinator = _coordinator()

    class Board:
        def __init__(self) -> None:
            self.proposed: list[tuple[str, str]] = []

        def propose(self, actor: str, goal: str, *, acceptance: str = "", intent_id: str | None = None) -> None:
            self.proposed.append((goal, intent_id or ""))

    board = Board()
    plan = CoordinatorPlan(
        verdict=VERDICT_EXPLORE,
        intents=[
            {"goal": "Recon the service", "rationale": "", "depends_on": [], "from_facts": []},
            {"goal": "Recon the service", "rationale": "duplicate", "depends_on": [], "from_facts": []},
            {"goal": "  ", "rationale": "empty", "depends_on": [], "from_facts": []},
            {"goal": "New direction", "rationale": "x", "depends_on": [], "from_facts": []},
        ],
    )
    proposed = coordinator.propose(board, plan, existing_goals={"Recon the service"})
    assert proposed == ["coord:run-1:1"]
    assert [goal for goal, _ in board.proposed] == ["New direction"]


def test_reason_prompt_formats_with_json_example_braces() -> None:
    """The prompt's JSON example contains literal braces that must be escaped
    for str.format — otherwise Coordinator.plan() dies with
    KeyError: '"verdict"' the first time the coordinator actually triggers
    (regression: v4-era coordinator traces were all empty, and the first
    post-fix run surfaced this crash in the coordinator loop)."""
    from backend.agents.coordinator import REASON_PROMPT

    rendered = REASON_PROMPT.format(summary="## Blackboard: x\n\n### Active intents\n- none")
    assert "{\"verdict\": \"explore" in rendered
    assert "Blackboard summary:" in rendered
    assert "## Blackboard: x" in rendered


def test_evidence_signature_counts_facts_dead_ends_and_hypotheses() -> None:
    """Trigger alignment: any blackboard growth (facts, dead ends OR the
    auto-recorded hypotheses from each solver round) changes the signature —
    verified-only facts would never fire because the fact tool requires
    verbatim output matches."""
    from backend.agents.swarm import ChallengeSwarm
    from backend.evidence import EvidenceBoard

    swarm = object.__new__(ChallengeSwarm)
    swarm.meta = SimpleNamespace(name="sig-test")
    swarm.run_id = "run-sig"
    board = EvidenceBoard.open(":memory:", "sig-test", "run-sig")
    swarm.evidence_board = board
    import asyncio

    async def main() -> None:
        assert await swarm._evidence_signature() == (0, 0, 0)
        board.add_hypothesis("w1", "unverified guess")
        assert await swarm._evidence_signature() == (0, 0, 1)  # hypothesis triggers
        board.add_fact(
            "w1", "the service echoes input", verified=True,
            provenance={"source_kind": "tool_result", "source_excerpt": "bash output"},
        )
        assert await swarm._evidence_signature() == (1, 0, 1)  # fact triggers
        board.add_dead_end("w1", "not a buffer overflow")
        assert await swarm._evidence_signature() == (1, 1, 1)  # dead end triggers

    asyncio.run(main())
    board.close()
