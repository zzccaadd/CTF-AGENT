"""Shared benchmark data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkLimits:
    model: str = "codex/gpt-5.5"
    timeout_seconds: int = 300
    max_tokens: int = 1_000_000
    allow_internet: bool = False
    attempts: int = 1
    concurrency: int = 1
    solvers_per_swarm: int = 3
    max_solvers_per_swarm: int = 3
    rag_enabled: bool = True
    knowledge_db_path: str = "logs/knowledge.sqlite3"
    knowledge_top_k: int = 5
    knowledge_max_chars: int = 8_000


@dataclass(frozen=True)
class BenchmarkChallenge:
    challenge_id: str
    provider: str
    source_dir: Path
    name: str
    category: str
    description: str
    expected_flags: tuple[str, ...]
    value: int = 0
    files: tuple[Path, ...] = ()
    connection_info: str = ""
    compose_file: Path | None = None
    init_script: Path | None = None
    start_script: Path | None = None
    stop_script: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparedChallenge:
    spec: BenchmarkChallenge
    challenge_dir: Path
    network_mode: str
    project_name: str = ""


@dataclass
class BenchmarkResult:
    challenge_id: str
    provider: str
    name: str
    category: str
    model: str
    solved: bool
    status: str
    flag: str | None
    elapsed_seconds: float
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    total_tokens: int
    cost_usd: float
    wrong_submissions: int
    tool_calls: int
    trace_path: str
    error: str = ""
    knowledge_queries: int = 0
    knowledge_hits: int = 0
    knowledge_chars: int = 0
    knowledge_elapsed_ms: float = 0.0
    knowledge_tool_calls: int = 0
    knowledge_cache_hits: int = 0
    knowledge_budget_rejections: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
