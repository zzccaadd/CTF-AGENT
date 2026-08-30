"""Typed data objects for the Stage 1 evidence blackboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: str
    seq: int
    ts: float
    challenge_name: str
    run_id: str
    actor_id: str
    actor_type: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    artifact_id: str | None = None
    verified: bool = False
    dedupe_key: str | None = None
    schema_version: int = 1


@dataclass(frozen=True)
class Intent:
    intent_id: str
    challenge_name: str
    run_id: str
    goal: str
    acceptance: str = ""
    status: str = "open"
    worker_id: str | None = None
    lease_until: float | None = None
    attempt: int = 0
    created_event_id: str | None = None
    result_event_id: str | None = None
    result: str = ""


@dataclass(frozen=True)
class BoardSnapshot:
    challenge_name: str
    run_id: str
    facts: list[EvidenceEvent] = field(default_factory=list)
    hypotheses: list[EvidenceEvent] = field(default_factory=list)
    dead_ends: list[EvidenceEvent] = field(default_factory=list)
    intents: list[Intent] = field(default_factory=list)
    flag: str | None = None
    last_seq: int = 0
