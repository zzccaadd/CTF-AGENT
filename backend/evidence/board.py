"""High-level blackboard operations used by coordinator and Codex workers."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from backend.evidence.models import BoardSnapshot, EvidenceEvent, Intent
from backend.evidence.query import EvidenceQuery
from backend.evidence.replay import replay
from backend.evidence.state import fold_events
from backend.evidence.store import SQLiteEvidenceStore


class EvidenceBoard:
    def __init__(self, store: SQLiteEvidenceStore, challenge_name: str, run_id: str) -> None:
        self.store = store
        self.challenge_name = challenge_name
        self.run_id = run_id

    @classmethod
    def open(cls, path: str | Path, challenge_name: str, run_id: str | None = None) -> EvidenceBoard:
        store = SQLiteEvidenceStore(path)
        resolved_run_id = run_id or store.latest_run_id(challenge_name) or uuid.uuid4().hex
        return cls(store, challenge_name, resolved_run_id)

    def close(self) -> None:
        self.store.close()

    def record(self, actor_id: str, actor_type: str, kind: str, payload: dict[str, Any] | None = None, *, provenance: dict[str, Any] | None = None, artifact_id: str | None = None, verified: bool = False, dedupe_key: str | None = None, links: list[tuple[str, str]] | None = None) -> EvidenceEvent:
        return self.store.append_event(
            challenge_name=self.challenge_name,
            run_id=self.run_id,
            actor_id=actor_id,
            actor_type=actor_type,
            kind=kind,
            payload=payload,
            provenance=provenance,
            artifact_id=artifact_id,
            verified=verified,
            dedupe_key=dedupe_key,
            links=links,
        )

    def start(self, actor_id: str = "swarm") -> EvidenceEvent:
        return self.record(actor_id, "swarm", "challenge_started", dedupe_key=f"start:{self.challenge_name}:{self.run_id}")

    def finish(self, actor_id: str = "swarm", reason: str = "") -> EvidenceEvent:
        return self.record(actor_id, "swarm", "challenge_finished", {"reason": reason}, dedupe_key=f"finish:{self.challenge_name}:{self.run_id}")

    def propose(self, actor_id: str, goal: str, acceptance: str = "", intent_id: str | None = None, from_event_ids: list[str] | None = None) -> Intent:
        return self.store.propose_intent(
            challenge_name=self.challenge_name,
            run_id=self.run_id,
            actor_id=actor_id,
            intent_id=intent_id or f"intent:{uuid.uuid4().hex[:12]}",
            goal=goal,
            acceptance=acceptance,
            from_event_ids=from_event_ids,
        )

    def claim(self, worker_id: str, intent_id: str, lease_seconds: int = 300, max_attempts: int = 3) -> Intent | None:
        return self.store.claim_intent(
            challenge_name=self.challenge_name,
            run_id=self.run_id,
            worker_id=worker_id,
            intent_id=intent_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
        )

    def open_intents(self) -> list[Intent]:
        return self.store.list_intents(self.challenge_name, self.run_id)

    # Explicit names used by coordinator/worker integrations.
    def list_open_intents(self) -> list[Intent]:
        return self.open_intents()

    def read_board_summary(self, max_items: int = 16, max_chars: int = 12000) -> str:
        return self.summary(max_items=max_items, max_chars=max_chars)

    def complete(self, worker_id: str, intent_id: str, result: str, status: str = "completed", produced_event_ids: list[str] | None = None) -> Intent | None:
        return self.store.complete_intent(
            challenge_name=self.challenge_name,
            run_id=self.run_id,
            worker_id=worker_id,
            intent_id=intent_id,
            result=result,
            status=status,
            produced_event_ids=produced_event_ids,
        )

    def add_fact(self, actor_id: str, fact: str, *, verified: bool, provenance: dict[str, Any], intent_id: str | None = None, artifact_id: str | None = None) -> EvidenceEvent:
        provenance = dict(provenance or {})
        if verified:
            allowed_sources = {"trace", "tool_result", "submission", "command", "file", "service"}
            source_kind = provenance.get("source_kind")
            if source_kind not in allowed_sources or not provenance.get("source_excerpt"):
                raise ValueError("verified facts require an allowed source_kind and source_excerpt")
        if verified:
            return self.record(
                actor_id, "worker", "fact_added", {"fact": fact, "intent_id": intent_id or ""},
                provenance=provenance, artifact_id=artifact_id, verified=True,
                dedupe_key=f"fact:{self.challenge_name}:{self.run_id}:{actor_id}:{fact.strip().lower()}",
            )
        return self.record(
            actor_id, "worker", "hypothesis_added", {"hypothesis": fact, "intent_id": intent_id or ""},
            provenance=provenance, artifact_id=artifact_id, verified=False,
            dedupe_key=f"hyp:{self.challenge_name}:{self.run_id}:{actor_id}:{fact.strip().lower()}",
        )

    def add_hypothesis(self, actor_id: str, text: str, *, intent_id: str | None = None) -> EvidenceEvent:
        return self.record(actor_id, "worker", "hypothesis_added", {"hypothesis": text, "intent_id": intent_id or ""}, verified=False, dedupe_key=f"hyp:{self.challenge_name}:{self.run_id}:{actor_id}:{text.strip().lower()}")

    def add_dead_end(self, actor_id: str, reason: str, *, intent_id: str | None = None) -> EvidenceEvent:
        return self.record(actor_id, "worker", "dead_end_added", {"reason": reason, "intent_id": intent_id or ""}, dedupe_key=f"dead:{self.challenge_name}:{self.run_id}:{reason.strip().lower()}")

    def verify_flag(self, actor_id: str, flag: str, *, provenance: dict[str, Any], intent_id: str | None = None) -> EvidenceEvent:
        return self.record(actor_id, "worker", "flag_verified", {"flag": flag.strip(), "intent_id": intent_id or ""}, provenance=provenance, verified=True, dedupe_key=f"flag:{self.challenge_name}:{self.run_id}:{flag.strip()}")

    def summary(self, max_items: int = 16, max_chars: int = 12000) -> str:
        events = self.store.events(self.challenge_name, self.run_id)
        facts = [e for e in events if e.kind == "fact_added" and e.verified][-max_items:]
        hypotheses = [e for e in events if e.kind == "hypothesis_added"][-max_items:]
        dead_ends = [e for e in events if e.kind == "dead_end_added"][-max_items:]
        intents = self.open_intents()
        lines = [f"## Blackboard: {self.challenge_name}"]
        if facts:
            lines.append("\n### Verified facts")
            lines.extend(f"- [{e.seq}] {e.payload.get('fact', '')}" for e in facts)
        if hypotheses:
            lines.append("\n### Hypotheses (unverified)")
            lines.extend(f"- [{e.seq}] {e.payload.get('hypothesis', '')}" for e in hypotheses)
        if dead_ends:
            lines.append("\n### Dead ends")
            lines.extend(f"- {e.payload.get('reason', '')}" for e in dead_ends)
        lines.append("\n### Active intents")
        lines.extend(f"- {i.intent_id}: {i.goal} ({i.status})" for i in intents)
        summary = "\n".join(lines)
        if max_chars < 1:
            return ""
        if len(summary) <= max_chars:
            return summary
        marker = "\n... [blackboard summary truncated]"
        return summary[: max(0, max_chars - len(marker))] + marker

    def snapshot(self) -> BoardSnapshot:
        events = self.store.events(self.challenge_name, self.run_id)
        return fold_events(
            self.challenge_name,
            self.run_id,
            events,
        )

    def replay(self) -> BoardSnapshot:
        """Rebuild the current view from the append-only event stream."""
        return replay(EvidenceQuery(self.store, self.challenge_name, self.run_id))
