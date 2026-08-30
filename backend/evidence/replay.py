"""Replay helpers for verifying that persisted events reconstruct board state."""

from __future__ import annotations

from backend.evidence.models import BoardSnapshot
from backend.evidence.query import EvidenceQuery
from backend.evidence.state import fold_events


def replay(query: EvidenceQuery) -> BoardSnapshot:
    return fold_events(
        query.challenge_name,
        query.run_id,
        query.events(),
    )
