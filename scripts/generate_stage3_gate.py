#!/usr/bin/env python3
"""Generate the immutable Stage 3 S3.0 gate artifact (Stage 2 acceptance).

Collects everything needed to reproduce an evaluation conclusion:
git state, environment, corpus manifest + bootstrap report + DB hash,
static/test check results, the frozen publishing matrix and benchmark limits.

Usage:
  .venv/bin/python scripts/generate_stage3_gate.py [--output logs/stage3_gate_<ts>.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=600)


def _git(*args: str) -> str:
    proc = _run(["git", *args])
    return proc.stdout.strip()


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _db_summary(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    summary: dict = {"path": str(path), "exists": True, "sha256": digest}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        summary["schema_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
        summary["documents"] = conn.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0]
        summary["chunks"] = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        summary["error"] = str(exc)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "logs" / f"stage3_gate_{time.strftime('%Y%m%d-%H%M%S')}.json")
    args = parser.parse_args()

    pytest = _run([PY, "-m", "pytest", "-q"], cwd=ROOT)
    ruff = _run([PY, "-m", "ruff", "check", "backend", "tests", "scripts"], cwd=ROOT)
    compileall = _run([PY, "-m", "compileall", "-q", "backend", "scripts"], cwd=ROOT)

    status = _run(["git", "status", "--short"], cwd=ROOT).stdout.strip().splitlines()
    try:
        codex_version = _run(["codex", "--version"]).stdout.strip().splitlines()[:1]
    except FileNotFoundError:
        codex_version = ["not installed"]
    gate: dict = {
        "gate": "S3.0-stage2-acceptance",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": {
            "head": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": status,
            "diff_stat": _run(["git", "diff", "--stat"]).stdout.strip().splitlines(),
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "codex_cli": codex_version,
        },
        "corpus": {
            "policy_manifest": _load_json(ROOT / "knowledge" / "manifest.json"),
            "bootstrap_report": _load_json(ROOT / "logs" / "knowledge.manifest.json"),
            "db": _db_summary(ROOT / "logs" / "knowledge.sqlite3"),
            "doc_count": len(list((ROOT / "knowledge").rglob("*.md"))),
        },
        "checks": {
            "pytest": {"exit": pytest.returncode, "tail": pytest.stdout.strip().splitlines()[-3:]},
            "ruff": {"exit": ruff.returncode, "tail": ruff.stdout.strip().splitlines()[-3:]},
            "compileall": {"exit": compileall.returncode, "tail": compileall.stdout.strip().splitlines()[-3:]},
            "test_db_tmp": "pytest uses tmp_path for knowledge DBs; logs/ DBs are not written by tests",
        },
        "publishing_matrix": {
            "codex": "required — search_knowledge tool + budgets + provenance (Stage 3 must-pass)",
            "pydantic_ai": "disabled for RAG — no search_knowledge registration; keep out of release matrix until parity adapter lands",
            "claude_sdk": "disabled for RAG — bash-only solver path; keep out of release matrix until parity adapter lands",
        },
        "benchmark_defaults": {
            "model": "codex/gpt-5.5",
            "timeout_seconds": 1800,
            "max_tokens": 1000000,
            "concurrency": 1,
            "solvers_per_swarm": 3,
            "rag_enabled": True,
            "knowledge_db_path": "logs/knowledge.sqlite3",
            "knowledge_top_k": 5,
            "knowledge_max_chars": 8000,
            "knowledge_query_timeout_ms": 200,
            "knowledge_turn_budget": 1,
            "knowledge_solver_budget": 8,
            "knowledge_challenge_budget": 24,
            "knowledge_context_chars_budget": 32000,
        },
        "notes": [
            "Gate is a development gate; evaluation/release gates must re-run this script and archive the JSON with the run artifacts.",
            "Corpus version tracking: bump knowledge/manifest.json 'name' or add a version field on material corpus changes.",
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"gate artifact written: {args.output}")
    print(f"  pytest exit={pytest.returncode} | ruff exit={ruff.returncode} | compileall exit={compileall.returncode}")
    print(f"  corpus: {gate['corpus']['doc_count']} md files, "
          f"db docs={gate['corpus']['db'].get('documents')}, chunks={gate['corpus']['db'].get('chunks')}")
    return 0 if (pytest.returncode == 0 and ruff.returncode == 0 and compileall.returncode == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
