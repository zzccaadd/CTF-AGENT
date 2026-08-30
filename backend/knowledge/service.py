"""Stable, bounded service facade for agent-facing knowledge search."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from backend.knowledge.models import SearchRequest, SearchResult
from backend.knowledge.store import SQLiteKnowledgeBase


class KnowledgeService:
    """Apply agent-safe limits and isolate storage failures from solver runs."""

    DEFAULT_TOP_K = 5
    MAX_TOP_K = 10
    DEFAULT_MAX_CHARS = 8_000
    DEFAULT_TIMEOUT_MS = 200
    ALLOWED_SOURCE_TYPES = frozenset({"official", "reference", "internal_notes"})

    def __init__(
        self,
        knowledge: SQLiteKnowledgeBase,
        *,
        max_chars: int = DEFAULT_MAX_CHARS,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be positive")
        self.knowledge = knowledge
        self.max_chars = max_chars
        self.timeout_ms = timeout_ms
        self.last_diagnostic: dict[str, Any] = {"status": "idle"}

    @classmethod
    def from_path(cls, path: str, **kwargs: Any) -> KnowledgeService:
        return cls(SQLiteKnowledgeBase(path), **kwargs)

    def close(self) -> None:
        self.knowledge.close()

    @staticmethod
    def _bounded_top_k(top_k: int | None) -> int:
        if top_k is None:
            return KnowledgeService.DEFAULT_TOP_K
        try:
            value = int(top_k)
        except (TypeError, ValueError) as exc:
            raise ValueError("top_k must be an integer") from exc
        if value < 1:
            raise ValueError("top_k must be at least 1")
        return min(value, KnowledgeService.MAX_TOP_K)

    def search(
        self,
        query: str,
        *,
        source_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[SearchResult]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            self.last_diagnostic = {"status": "invalid", "reason": "empty_query"}
            return []
        bounded_top_k = self._bounded_top_k(top_k)
        request = SearchRequest(
            query=normalized_query,
            source_type=source_type.strip().lower() if source_type else None,
            metadata=dict(metadata or {}),
            # Fetch a wider candidate set so policy filtering cannot consume
            # the caller's requested top-k slots.
            top_k=100,
        )
        started = time.perf_counter()
        try:
            results = self.knowledge.search(request, timeout_ms=self.timeout_ms)
        except Exception as exc:  # storage errors must not kill the solver
            if any(marker in str(exc).lower() for marker in ("timeout", "interrupted")):
                self.last_diagnostic = {
                    "status": "timeout",
                    "timeout_ms": self.timeout_ms,
                    "query_hash": self._query_hash(normalized_query),
                }
                return []
            self.last_diagnostic = {
                "status": "error",
                "reason": "knowledge_store_unavailable",
                "error_type": type(exc).__name__,
            }
            return []
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > self.timeout_ms:
            self.last_diagnostic = {
                "status": "timeout",
                "elapsed_ms": round(elapsed_ms, 3),
                "timeout_ms": self.timeout_ms,
                "query_hash": self._query_hash(normalized_query),
            }
            return []

        results = [result for result in results if result.source_type in self.ALLOWED_SOURCE_TYPES]
        bounded: list[SearchResult] = []
        chars = 0
        for result in results[:bounded_top_k]:
            remaining = self.max_chars - chars
            if remaining <= 0:
                break
            if len(result.text) > remaining:
                bounded.append(
                    replace(
                        result,
                        text=result.text[:remaining],
                        provenance={**result.provenance, "truncated": True},
                    )
                )
                chars = self.max_chars
                break
            bounded.append(result)
            chars += len(result.text)
        self.last_diagnostic = {
            "status": "ok",
            "elapsed_ms": round(elapsed_ms, 3),
            "query_hash": self._query_hash(normalized_query),
            "hit_count": len(bounded),
            "returned_chars": chars,
        }
        return bounded

    @staticmethod
    def _query_hash(query: str) -> str:
        import hashlib

        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
