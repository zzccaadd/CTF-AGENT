"""Local lexical knowledge base for RAG Stage 2."""

from backend.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    SearchRequest,
    SearchResult,
)
from backend.knowledge.service import KnowledgeService
from backend.knowledge.store import SQLiteKnowledgeBase

__all__ = [
    "KnowledgeChunk",
    "KnowledgeDocument",
    "SQLiteKnowledgeBase",
    "KnowledgeService",
    "SearchRequest",
    "SearchResult",
]
