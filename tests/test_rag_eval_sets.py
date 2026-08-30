from __future__ import annotations

import json
from pathlib import Path


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
