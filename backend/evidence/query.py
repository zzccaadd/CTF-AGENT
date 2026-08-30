"""Read-only challenge-scoped queries over the evidence store."""

from __future__ import annotations

from backend.evidence.models import EvidenceEvent, Intent
from backend.evidence.store import SQLiteEvidenceStore


class EvidenceQuery:
    def __init__(self, store: SQLiteEvidenceStore, challenge_name: str, run_id: str) -> None:
        self.store = store
        self.challenge_name = challenge_name
        self.run_id = run_id

    def events(self, *, kinds: list[str] | None = None, after_seq: int = 0) -> list[EvidenceEvent]:
        return self.store.events(self.challenge_name, self.run_id, kinds=kinds, after_seq=after_seq)

    def intents(self, *, active_only: bool = True) -> list[Intent]:
        return self.store.list_intents(self.challenge_name, self.run_id, active_only=active_only)

