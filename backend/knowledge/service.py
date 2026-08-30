"""Stable, bounded service facade for agent-facing knowledge search.

Failure contract:

- Invalid *parameters* (top_k, oversized metadata) raise ``ValueError``; the
  CLI maps this to a stable error code and the agent tool path surfaces it as
  a readable "Tool error". The diagnostic is recorded before raising so every
  rejection is auditable.
- Invalid *query content* (empty or over-long query) returns an empty list and
  records a structured diagnostic; the agent tool converts "no usable
  results" into a readable message.
- Storage failures and in-query timeouts are isolated: they return an empty
  list with a structured diagnostic and never kill the solver main chain.
- A query that *completes* after the deadline is still returned: the in-query
  progress handler enforces the hard deadline, and post-hoc latency is
  diagnostic-only, so cold caches cannot silently disable RAG.
"""

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
    # Bounds for model-supplied inputs. The FTS tokenizer output is bounded by
    # the progress handler, but Python-level dict/list work is not, so cap the
    # request surface before it reaches the store.
    MAX_QUERY_CHARS = 512
    MAX_METADATA_ITEMS = 8
    MAX_METADATA_VALUE_CHARS = 256

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

    @staticmethod
    def _validated_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        """Return a flat metadata filter or raise ValueError for oversized input."""
        if not metadata:
            return {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be a flat object")
        if len(metadata) > KnowledgeService.MAX_METADATA_ITEMS:
            raise ValueError(
                f"metadata must have at most {KnowledgeService.MAX_METADATA_ITEMS} keys"
            )
        oversized = [
            (key, len(str(value)))
            for key, value in metadata.items()
            if len(str(key)) > KnowledgeService.MAX_METADATA_VALUE_CHARS
            or len(str(value)) > KnowledgeService.MAX_METADATA_VALUE_CHARS
        ]
        if oversized:
            raise ValueError(
                f"metadata keys/values must be at most {KnowledgeService.MAX_METADATA_VALUE_CHARS} chars"
            )
        return dict(metadata)

    @staticmethod
    def _normalized_source_type(source_type: Any) -> str | None:
        """Return a whitelisted source_type or None.

        Model-supplied values outside the allowed set (e.g. "all",
        "ctf_pattern") are IGNORED, not used as an exact-match filter: a
        non-whitelisted filter would silently zero out every result."""
        if isinstance(source_type, str) and source_type.strip():
            normalized = source_type.strip().lower()
            if normalized in KnowledgeService.ALLOWED_SOURCE_TYPES:
                return normalized
        return None

    def search(
        self,
        query: str,
        *,
        source_type: Any = None,
        metadata: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[SearchResult]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            self.last_diagnostic = {"status": "invalid", "reason": "empty_query"}
            return []
        if len(normalized_query) > self.MAX_QUERY_CHARS:
            self.last_diagnostic = {
                "status": "invalid",
                "reason": "query_too_long",
                "max_chars": self.MAX_QUERY_CHARS,
            }
            return []
        try:
            bounded_top_k = self._bounded_top_k(top_k)
        except ValueError:
            self.last_diagnostic = {"status": "invalid", "reason": "invalid_top_k"}
            raise
        try:
            metadata = self._validated_metadata(metadata)
        except ValueError:
            self.last_diagnostic = {"status": "invalid", "reason": "invalid_metadata"}
            raise
        request = SearchRequest(
            query=normalized_query,
            source_type=self._normalized_source_type(source_type),
            metadata=metadata,
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
        diagnostic: dict[str, Any] = {
            "status": "ok",
            "elapsed_ms": round(elapsed_ms, 3),
            "query_hash": self._query_hash(normalized_query),
            "hit_count": len(bounded),
            "returned_chars": chars,
        }
        if elapsed_ms > self.timeout_ms:
            # Completed results are never discarded for being slow: the
            # in-query progress handler enforces the hard deadline. Record the
            # overshoot so evaluation can track cold-cache impact.
            diagnostic["exceeded_timeout_ms"] = round(elapsed_ms - self.timeout_ms, 3)
        self.last_diagnostic = diagnostic
        return bounded

    @staticmethod
    def _query_hash(query: str) -> str:
        import hashlib

        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
