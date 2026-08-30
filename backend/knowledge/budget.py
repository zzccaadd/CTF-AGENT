"""Shared, per-run knowledge query budget (Stage 3 S3.1)."""

from __future__ import annotations


class KnowledgeBudget:
    """Swarm-wide knowledge query budget shared by all solvers of one challenge.

    The runner is asyncio single-threaded, so no lock is required: solvers
    interleave on one event loop and `consume()` is atomic between awaits.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("knowledge challenge budget must be at least 1")
        self.limit = limit
        self.used = 0

    def consume(self, amount: int = 1) -> bool:
        """Reserve `amount` queries; False when the budget is exhausted."""
        if self.used + amount > self.limit:
            return False
        self.used += amount
        return True

    def remaining(self) -> int:
        return max(0, self.limit - self.used)
