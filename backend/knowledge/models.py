"""Typed models for the lexical knowledge base."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    title: str
    text: str
    source_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    trust_level: str = "medium"
    content_hash: str = ""


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    text: str
    ordinal: int
    section: str = ""
    line_start: int | None = None
    line_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchRequest:
    query: str
    source_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    top_k: int = 10


@dataclass(frozen=True)
class SearchResult:
    text: str
    source_type: str
    metadata: dict[str, Any]
    score: float
    provenance: dict[str, Any]
    document_id: str
    chunk_id: str

