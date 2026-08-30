"""Stable CLI return codes for the knowledge tooling (search/delete/index)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.knowledge.models import SearchRequest
from backend.knowledge.store import SQLiteKnowledgeBase

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SEARCH_CLI = SCRIPTS_DIR / "search_knowledge.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SEARCH_CLI), *args],
        capture_output=True,
        text=True,
        cwd=SCRIPTS_DIR.parent,
    )


def test_search_missing_db_has_stable_exit_code(tmp_path) -> None:
    proc = _run_cli("z3", "--db", str(tmp_path / "missing.sqlite3"))
    assert proc.returncode == 3
    assert "does not exist" in proc.stderr


def test_delete_contract_and_exit_codes(tmp_path) -> None:
    db = tmp_path / "knowledge.sqlite3"
    knowledge = SQLiteKnowledgeBase(db)
    document = knowledge.ingest(
        title="Guide", text="z3 guide", source_type="official", source_url="file:///docs/z3.md"
    )
    knowledge.close()

    proc = _run_cli("--delete", "doc-does-not-exist", "--db", str(db))
    assert proc.returncode == 1

    proc = _run_cli("--delete", document.document_id, "--db", str(db))
    assert proc.returncode == 0
    assert f'"deleted": "{document.document_id}"' in proc.stdout

    knowledge = SQLiteKnowledgeBase(db)
    assert not knowledge.search(SearchRequest("z3"))
    knowledge.close()


def test_invalid_parameters_have_stable_exit_code(tmp_path) -> None:
    db = tmp_path / "knowledge.sqlite3"
    knowledge = SQLiteKnowledgeBase(db)
    knowledge.ingest(title="Guide", text="z3 guide", source_type="official")
    knowledge.close()

    proc = _run_cli("z3", "--db", str(db), "--top-k", "0")
    assert proc.returncode == 2
    assert "invalid search request" in proc.stderr

    proc = _run_cli("z3", "--db", str(db), "--metadata", "broken")
    assert proc.returncode == 2
    assert "KEY=VALUE" in proc.stderr


def test_index_script_refuses_benchmark_corpus_root() -> None:
    from scripts.index_knowledge import REPO_ROOT, _validate_root

    benchmark_root = REPO_ROOT / "benchmarks"
    if not benchmark_root.exists():
        pytest.skip("benchmarks submodules not checked out")
    with pytest.raises(SystemExit, match="refusing to index benchmark corpus root"):
        _validate_root(benchmark_root)
    with pytest.raises(SystemExit, match="refusing to index benchmark corpus root"):
        _validate_root(benchmark_root / "cybench" / "benchmark")
