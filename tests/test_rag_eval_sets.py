from __future__ import annotations

import json
from pathlib import Path

from scripts.run_rag_eval import (
    _aggregate,
    _aggregate_replicates,
    _incomplete_pairs,
    build_comparison,
)


def _load(name: str) -> dict:
    path = Path("benchmarks/rag_eval") / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_rag_eval_manifests_are_fixed_and_nested() -> None:
    main = _load("main_100")
    smoke = _load("smoke_20")
    sensitive = _load("rag_sensitive_100")

    assert len(main["items"]) == 100
    assert len(smoke["items"]) == 20
    assert len(sensitive["items"]) == 100
    assert main["default_model"] == "codex/gpt-5.5"
    assert smoke["default_model"] == "codex/gpt-5.5"
    assert sensitive["default_model"] == "codex/gpt-5.5"

    main_keys = {(item["provider"], item["challenge_id"]) for item in main["items"]}
    smoke_keys = {(item["provider"], item["challenge_id"]) for item in smoke["items"]}
    assert smoke_keys <= main_keys

    sensitive_counts = sensitive["summary"]["by_provider"]
    assert sensitive_counts["cybench"] == 37
    assert sensitive_counts["nyu"] == 63


def test_knowledge_probe_subset_is_labeled_and_contained_in_smoke_20() -> None:
    probe = _load("knowledge_probe")
    smoke = _load("smoke_20")

    assert len(probe["items"]) == 6
    smoke_keys = {(item["provider"], item["challenge_id"]) for item in smoke["items"]}
    for item in probe["items"]:
        assert isinstance(item["knowledge_needed"], bool)
        assert isinstance(item["expected_knowledge"], list)
        if item["knowledge_needed"]:
            assert item["expected_knowledge"], "knowledge-needed items must list expected topics"
        else:
            assert item["expected_knowledge"] == []
        assert (item["provider"], item["challenge_id"]) in smoke_keys

    needed = [item for item in probe["items"] if item["knowledge_needed"]]
    not_needed = [item for item in probe["items"] if not item["knowledge_needed"]]
    assert len(needed) == 3 and len(not_needed) == 3


def test_knowledge_probe_v2_is_corpus_anchored() -> None:
    """v2 probe rules: knowledge-needed items must point at existing corpus
    docs; controls must not; ids must exist in the candidate pools."""
    probe = _load("knowledge_probe_v2")
    pool = {}
    for name in ("smoke_20", "main_100", "rag_sensitive_100"):
        for item in _load(name)["items"]:
            pool[(item["provider"], item["challenge_id"])] = item

    items = probe["items"]
    assert len(items) == 11
    needed = [item for item in items if item["knowledge_needed"]]
    controls = [item for item in items if not item["knowledge_needed"]]
    assert len(needed) == 8 and len(controls) == 3

    corpus_dir = Path("knowledge")
    for item in items:
        assert (item["provider"], item["challenge_id"]) in pool, item["challenge_id"]
        assert isinstance(item["relevant_corpus_docs"], list)
        if item["knowledge_needed"]:
            assert item["expected_knowledge"]
            assert item["relevant_corpus_docs"], "knowledge-needed items must cite corpus docs"
            for doc in item["relevant_corpus_docs"]:
                assert (corpus_dir / doc).is_file(), f"missing corpus doc: {doc}"
        else:
            assert item["expected_knowledge"] == []
            assert item["relevant_corpus_docs"] == []

    # Topic spread sanity: no two knowledge-needed items should share the same
    # primary corpus doc (each probes a different corpus area).
    primary = [item["relevant_corpus_docs"][0] for item in needed]
    assert len(set(primary)) == len(primary)


def test_build_comparison_aggregates_and_pairs_by_challenge_id() -> None:
    off_results = [
        {
            "challenge_id": "a", "solved": True, "status": "flag_found",
            "tool_calls": 10, "total_tokens": 1000, "cost_usd": 0.1,
            "elapsed_seconds": 60, "knowledge_queries": 0,
        },
        {
            "challenge_id": "b", "solved": False, "status": "timeout",
            "tool_calls": 3, "total_tokens": 800, "cost_usd": 0.08,
            "elapsed_seconds": 120, "knowledge_queries": 0,
        },
    ]
    on_results = [
        # Reordered on purpose: pairing must be by challenge_id, not position.
        {
            "challenge_id": "b", "solved": True, "status": "flag_found",
            "tool_calls": 5, "total_tokens": 900, "cost_usd": 0.09,
            "elapsed_seconds": 90, "knowledge_queries": 2,
            "knowledge_hits": 1, "knowledge_chars": 400, "knowledge_elapsed_ms": 0.5,
        },
        {
            "challenge_id": "a", "solved": True, "status": "flag_found",
            "tool_calls": 12, "total_tokens": 1100, "cost_usd": 0.11,
            "elapsed_seconds": 70, "knowledge_queries": 3,
            "knowledge_hits": 3, "knowledge_chars": 900, "knowledge_elapsed_ms": 0.7,
        },
    ]
    comparison = build_comparison(Path("benchmarks/rag_eval/knowledge_probe.json"), {
        "results": off_results,
    }, {
        "results": on_results,
    })

    assert comparison["delta_solved"] == 1  # b flipped timeout -> solved
    assert comparison["off"]["solve_rate"] == 0.5
    assert comparison["on"]["knowledge_queries"] == 5
    assert comparison["on"]["knowledge_hits"] == 4
    assert comparison["on"]["knowledge_chars"] == 1300
    assert comparison["on"]["knowledge_elapsed_ms"] == 1.2
    assert comparison["on"]["knowledge_est_extra_tokens"] == 325  # 1300 // 4
    assert comparison["delta_tokens"] == 200
    assert comparison["delta_cost_usd"] == 0.02

    rows = {row["challenge_id"]: row for row in comparison["per_challenge"]}
    assert rows["a"]["delta_solved"] == 0
    assert rows["b"]["delta_solved"] == 1
    assert rows["b"]["on"]["knowledge_queries"] == 2


def test_aggregate_is_empty_safe() -> None:
    summary = _aggregate([])
    assert summary["solve_rate"] == 0
    assert summary["tool_calls_avg"] == 0
    assert summary["elapsed_avg"] == 0
    assert summary["knowledge_est_extra_tokens"] == 0


def _run(challenge_id: str, solved: bool, status: str = "flag_found", kq: int = 0) -> dict:
    return {
        "challenge_id": challenge_id, "solved": solved, "status": status,
        "tool_calls": 3, "total_tokens": 100, "cost_usd": 0.1,
        "elapsed_seconds": 60, "knowledge_queries": kq,
    }


def test_incomplete_pairs_detects_missing_sides() -> None:
    off = [_run("a", True)]
    on = [_run("a", True), _run("b", False)]
    missing = _incomplete_pairs(off, on)
    # b ran only in the rag-on run: the off side of its pair is missing.
    assert missing == [{"challenge_id": "b", "missing_side": "off"}]


def test_aggregate_replicates_means_and_incomplete() -> None:
    # rep1: a solved off+on, b unsolved off / solved on (delta +1)
    # rep2: a solved both, b solved off / timeout on (delta -1) -> mean delta 0
    pairs = [
        (
            {"results": [_run("a", True), _run("b", False, "timeout")]},
            {"results": [_run("a", True), _run("b", True, "flag_found", kq=2)]},
        ),
        (
            {"results": [_run("a", True), _run("b", True)]},
            {"results": [_run("a", True), _run("b", False, "timeout", kq=1)]},
        ),
    ]
    agg = _aggregate_replicates(pairs)
    assert agg["replicates"] == 2
    assert agg["off"]["solved"] == 3 and agg["on"]["solved"] == 3
    assert agg["delta_solved_mean"] == 0.0
    rows = {row["challenge_id"]: row for row in agg["per_challenge"]}
    assert rows["b"]["on_solved_replicates"] == 1
    assert rows["b"]["on_total_replicates"] == 2
    assert rows["b"]["knowledge_queries_total"] == 3
    assert rows["b"]["incomplete"] is False
    assert agg["incomplete_pairs"] == []


def test_aggregate_replicates_marks_missing_side_not_unsolved() -> None:
    """A challenge that ran only on one side must be incomplete, and the
    missing side must NOT count toward its solved/total replicate counts."""
    pairs = [
        (
            {"results": [_run("a", True)]},
            {"results": [_run("a", True), _run("b", True, "flag_found", kq=1)]},
        ),
    ]
    agg = _aggregate_replicates(pairs)
    rows = {row["challenge_id"]: row for row in agg["per_challenge"]}
    assert rows["b"]["incomplete"] is True
    assert rows["b"]["off_total_replicates"] == 0
    assert rows["b"]["on_total_replicates"] == 1
    assert rows["b"]["on_solved_replicates"] == 1
    assert agg["incomplete_pairs"] == [{"challenge_id": "b", "missing_side": "off"}]
    # Solve-rate aggregates only count rows that actually ran.
    assert agg["on"]["total"] == 2 and agg["off"]["total"] == 1


def test_build_comparison_marks_incomplete_pairs() -> None:
    comparison = build_comparison(
        Path("benchmarks/rag_eval/knowledge_probe_v2.json"),
        {"results": [_run("a", True)]},
        {"results": [_run("a", True), _run("b", True)]},
    )
    assert comparison["incomplete"] == [{"challenge_id": "b", "missing_side": "off"}]
