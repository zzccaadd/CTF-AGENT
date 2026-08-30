"""SQLite FTS5 lexical knowledge base with provenance-preserving search."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.knowledge.indexer import split_text
from backend.knowledge.models import KnowledgeDocument, SearchRequest, SearchResult

TRUST_WEIGHT = {"official": 1.20, "high": 1.10, "medium": 1.00, "low": 0.80}
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
SCHEMA_VERSION = 1
_INIT_LOCK = threading.Lock()


@contextmanager
def _schema_lock(path: str):
    """Serialize first-time schema work across processes on local files."""
    if path == ":memory:":
        yield
        return
    try:
        import fcntl
    except ImportError:
        yield
        return
    lock_path = f"{path}.init.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class SQLiteKnowledgeBase:
    """A small local FTS5 index suitable for offline RAG MVP use."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        with _INIT_LOCK, _schema_lock(self.path):
            self._conn.executescript(
                """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                document_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_url TEXT,
                metadata TEXT NOT NULL,
                trust_level TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                text TEXT NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                line_start INTEGER,
                line_end INTEGER,
                metadata TEXT NOT NULL,
                UNIQUE(document_id, ordinal)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                chunk_id UNINDEXED,
                title,
                section,
                text,
                tokenize='unicode61'
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_documents_source
                ON knowledge_documents(source_type, trust_level);
            CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
                ON knowledge_chunks(document_id, ordinal);
                """
            )
            version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"unsupported knowledge schema version: {version}")
            if version < SCHEMA_VERSION:
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def chunk_count(self, document_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=?", (document_id,)
        ).fetchone()
        return int(row[0])

    @staticmethod
    def document_id_for(text: str, *, source_type: str, source_url: str | None = None) -> str:
        # A stable source URL makes re-indexing an edited file update one
        # document. Content-only documents remain content-addressed.
        identity = [source_type, source_url] if source_url else [source_type, text]
        raw = json.dumps(identity, ensure_ascii=False).encode()
        return "doc-" + hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def ingest(
        self,
        *,
        title: str,
        text: str,
        source_type: str,
        metadata: dict[str, Any] | None = None,
        source_url: str | None = None,
        trust_level: str = "medium",
        document_id: str | None = None,
        max_chars: int = 1600,
    ) -> KnowledgeDocument:
        source_type = source_type.strip().lower()
        if not source_type:
            raise ValueError("source_type is required to prevent corpus mixing")
        if source_type in {"benchmark", "benchmark_corpus"}:
            raise ValueError("benchmark corpus must not be indexed as RAG knowledge")
        if trust_level not in TRUST_WEIGHT:
            raise ValueError(f"unsupported trust_level: {trust_level}")
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized_text:
            raise ValueError("knowledge document cannot be empty")
        doc_id = document_id or self.document_id_for(
            normalized_text, source_type=source_type, source_url=source_url
        )
        content_hash = hashlib.sha256(normalized_text.encode()).hexdigest()
        now = time.time()
        chunks = split_text(normalized_text, max_chars=max_chars)
        if not chunks:
            raise ValueError("knowledge document produced no chunks")
        metadata = dict(metadata or {})
        with self._conn:
            self._conn.execute(
                """INSERT INTO knowledge_documents
                (document_id, title, source_type, source_url, metadata, trust_level, content_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    title=excluded.title, source_type=excluded.source_type, source_url=excluded.source_url,
                    metadata=excluded.metadata, trust_level=excluded.trust_level,
                    content_hash=excluded.content_hash, updated_at=excluded.updated_at""",
                (doc_id, title, source_type, source_url, self._json(metadata), trust_level, content_hash, now, now),
            )
            old_ids = [row[0] for row in self._conn.execute(
                "SELECT chunk_id FROM knowledge_chunks WHERE document_id=?", (doc_id,)
            ).fetchall()]
            for chunk_id in old_ids:
                self._conn.execute("DELETE FROM knowledge_fts WHERE chunk_id=?", (chunk_id,))
            self._conn.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (doc_id,))
            for chunk in chunks:
                chunk_id = f"{doc_id}:{chunk.ordinal}"
                chunk_metadata = {**metadata, "section": chunk.section}
                self._conn.execute(
                    """INSERT INTO knowledge_chunks
                    (chunk_id, document_id, ordinal, text, section, line_start, line_end, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (chunk_id, doc_id, chunk.ordinal, chunk.text, chunk.section, chunk.line_start, chunk.line_end, self._json(chunk_metadata)),
                )
                self._conn.execute(
                    "INSERT INTO knowledge_fts(chunk_id, title, section, text) VALUES (?, ?, ?, ?)",
                    (chunk_id, title, chunk.section, chunk.text),
                )
        return KnowledgeDocument(
            document_id=doc_id,
            title=title,
            text=normalized_text,
            source_type=source_type,
            metadata=metadata,
            source_url=source_url,
            trust_level=trust_level,
            content_hash=content_hash,
        )

    def ingest_many(self, documents: Iterable[dict[str, Any]]) -> list[KnowledgeDocument]:
        return [self.ingest(**document) for document in documents]

    def delete(self, document_id: str) -> bool:
        with self._conn:
            self._conn.execute(
                "DELETE FROM knowledge_fts WHERE chunk_id IN (SELECT chunk_id FROM knowledge_chunks WHERE document_id=?)",
                (document_id,),
            )
            cur = self._conn.execute("DELETE FROM knowledge_documents WHERE document_id=?", (document_id,))
        return cur.rowcount == 1

    def delete_source_except(self, source_type: str, source_urls: set[str], *, source_prefix: str | None = None) -> int:
        rows = self._conn.execute(
            "SELECT document_id, source_url FROM knowledge_documents WHERE source_type=?",
            (source_type.strip().lower(),),
        ).fetchall()
        removed = 0
        for row in rows:
            if row[1] not in source_urls and (
                source_prefix is None or str(row[1] or "").startswith(source_prefix)
            ):
                removed += int(self.delete(row[0]))
        return removed

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = TOKEN_RE.findall(query)
        return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)

    @staticmethod
    def _matches_metadata(metadata: dict[str, Any], expected: dict[str, Any]) -> bool:
        return all(metadata.get(key) == value for key, value in expected.items())

    def search(self, request: SearchRequest, *, timeout_ms: int | None = None) -> list[SearchResult]:
        query = self._fts_query(request.query)
        if not query:
            return []
        top_k = max(1, min(int(request.top_k), 100))
        candidate_limit = max(100, top_k * 10)
        deadline = time.monotonic() + timeout_ms / 1000 if timeout_ms else None
        if deadline:
            self._conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        try:
            rows = self._conn.execute(
                """SELECT f.chunk_id, f.text, f.section, bm25(knowledge_fts, 1.0, 0.7, 1.2) AS rank,
                          d.document_id, d.title, d.source_type, d.source_url, d.metadata AS doc_metadata,
                          d.trust_level, c.line_start, c.line_end, c.metadata AS chunk_metadata
                   FROM knowledge_fts AS f
                   JOIN knowledge_chunks AS c ON c.chunk_id=f.chunk_id
                   JOIN knowledge_documents AS d ON d.document_id=c.document_id
                   WHERE knowledge_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, candidate_limit),
            ).fetchall()
        finally:
            if deadline:
                self._conn.set_progress_handler(None, 0)
        results: list[SearchResult] = []
        for row in rows:
            if request.source_type and row["source_type"] != request.source_type:
                continue
            doc_metadata = json.loads(row["doc_metadata"])
            chunk_metadata = json.loads(row["chunk_metadata"])
            merged_metadata = {**doc_metadata, **chunk_metadata}
            if not self._matches_metadata(merged_metadata, request.metadata):
                continue
            lexical_score = max(0.0, -float(row["rank"]))
            score = lexical_score * TRUST_WEIGHT.get(row["trust_level"], 1.0)
            results.append(
                SearchResult(
                    text=row["text"],
                    source_type=row["source_type"],
                    metadata=merged_metadata,
                    raw_score=lexical_score,
                    score=score,
                    provenance={
                        "document_id": row["document_id"],
                        "chunk_id": row["chunk_id"],
                        "title": row["title"],
                        "source_url": row["source_url"],
                        "section": row["section"],
                        "line_start": row["line_start"],
                        "line_end": row["line_end"],
                        "trust_level": row["trust_level"],
                    },
                    document_id=row["document_id"],
                    chunk_id=row["chunk_id"],
                )
            )
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:top_k]
