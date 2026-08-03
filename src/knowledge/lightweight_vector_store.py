"""TSAR — Lightweight Vector Store (numpy-only fallback).

Provides cosine similarity search without ChromaDB dependency.
Uses numpy for vector operations and JSON for persistence.
Designed for free-tier / low-memory deployments where ChromaDB is too heavy.

Drop-in replacement for ChromaVectorStore with identical public API.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VectorDocument:
    """A stored document with its embedding vector."""
    id: str
    document: str
    embedding: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)


class LightweightVectorStore:
    """In-memory vector store with cosine similarity search and JSON persistence.

    Uses numpy for fast vector operations. Stores are persisted as JSON files
    containing documents + embeddings. Suitable for up to ~100k documents.

    Same public API as ChromaVectorStore — drop-in replacement.
    """

    COLLECTION_PATTERNS = "tsar_patterns"
    COLLECTION_TRADES = "tsar_trades"
    COLLECTION_LESSONS = "tsar_lessons"
    COLLECTION_MARKET_STATE = "tsar_market_state"

    ALL_COLLECTIONS = [
        COLLECTION_PATTERNS,
        COLLECTION_TRADES,
        COLLECTION_LESSONS,
        COLLECTION_MARKET_STATE,
    ]

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        embedding_fn: Any | None = None,
    ) -> None:
        self._persist_dir = Path(persist_dir) if persist_dir else None
        self._embedding_fn = embedding_fn or self._default_embed
        # collection_name -> list of VectorDocument
        self._collections: dict[str, list[VectorDocument]] = {name: [] for name in self.ALL_COLLECTIONS}

        if self._persist_dir:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

        logger.info(
            "lightweight_vector_store_initialized",
            persist_dir=str(self._persist_dir),
            collections={name: len(docs) for name, docs in self._collections.items()},
        )

    @property
    def available(self) -> bool:
        """Always available (only requires numpy)."""
        return True

    # ── Default embedding (TF-IDF-like character n-gram hash) ────

    @staticmethod
    def _default_embed(texts: list[str], dim: int = 128) -> list[np.ndarray]:
        """Deterministic embedding using character n-gram hashing.

        Better than raw SHA-512 hashing — captures character-level similarity.
        Uses 3-gram features hashed into a fixed-dim vector.
        Not as good as a real model, but captures lexical similarity.
        """
        embeddings = []
        for text in texts:
            vec = np.zeros(dim, dtype=np.float32)
            text_lower = text.lower().strip()
            # Character 3-grams
            for i in range(len(text_lower) - 2):
                trigram = text_lower[i:i+3]
                h = hash(trigram) % dim
                vec[h] += 1.0
            # Word-level features
            words = text_lower.split()
            for word in words:
                h = hash(word) % dim
                vec[h] += 2.0  # Words weighted higher than trigrams
            # Normalize to unit vector
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            embeddings.append(vec)
        return embeddings

    def _embed(self, texts: list[str]) -> list[np.ndarray]:
        """Compute embeddings for a list of texts."""
        if hasattr(self._embedding_fn, '__call__'):
            result = self._embedding_fn(texts)
            # Ensure numpy arrays
            return [np.asarray(r, dtype=np.float32) for r in result]
        return self._default_embed(texts)

    # ── Collection management ────────────────────────────────────

    def _get_collection(self, name: str) -> list[VectorDocument]:
        """Get or create a collection."""
        if name not in self._collections:
            self._collections[name] = []
        return self._collections[name]

    # ── Pattern operations ───────────────────────────────────────

    def upsert_pattern(
        self,
        pattern_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store or update a pattern embedding."""
        return self._upsert(self.COLLECTION_PATTERNS, pattern_id, document, metadata)

    def search_similar_patterns(
        self,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Find patterns semantically similar to the query."""
        return self._search(self.COLLECTION_PATTERNS, query, limit, where)

    # ── Trade operations ─────────────────────────────────────────

    def upsert_trade(
        self,
        trade_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store or update a trade embedding."""
        return self._upsert(self.COLLECTION_TRADES, trade_id, document, metadata)

    def search_similar_trades(
        self,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Find trades semantically similar to the query."""
        return self._search(self.COLLECTION_TRADES, query, limit, where)

    # ── Lesson operations ────────────────────────────────────────

    def upsert_lesson(
        self,
        lesson_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store or update a lesson embedding."""
        return self._upsert(self.COLLECTION_LESSONS, lesson_id, document, metadata)

    def search_similar_lessons(
        self,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Find lessons semantically similar to the query."""
        return self._search(self.COLLECTION_LESSONS, query, limit, where)

    # ── Market state operations ──────────────────────────────────

    def upsert_market_state(
        self,
        state_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store a market state snapshot embedding."""
        return self._upsert(self.COLLECTION_MARKET_STATE, state_id, document, metadata)

    def search_similar_market_states(
        self,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Find market states semantically similar to the query."""
        return self._search(self.COLLECTION_MARKET_STATE, query, limit, where)

    # ── Core upsert/search ───────────────────────────────────────

    def _upsert(
        self,
        collection_name: str,
        doc_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Insert or update a document in a collection."""
        collection = self._get_collection(collection_name)
        embedding = self._embed([document])[0]
        meta = metadata or {}
        meta["store"] = collection_name

        # Update existing
        for i, doc in enumerate(collection):
            if doc.id == doc_id:
                collection[i] = VectorDocument(
                    id=doc_id, document=document, embedding=embedding, metadata=meta,
                )
                self._save_to_disk()
                return True

        # Insert new
        collection.append(VectorDocument(
            id=doc_id, document=document, embedding=embedding, metadata=meta,
        ))
        self._save_to_disk()
        return True

    def _search(
        self,
        collection_name: str,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search a collection using cosine similarity."""
        collection = self._get_collection(collection_name)
        if not collection:
            return []

        query_embedding = self._embed([query])[0]

        # Compute cosine similarities
        scores: list[tuple[float, VectorDocument]] = []
        for doc in collection:
            # Apply metadata filter if provided
            if where:
                match = all(doc.metadata.get(k) == v for k, v in where.items())
                if not match:
                    continue

            # Cosine similarity = dot(a, b) / (||a|| * ||b||)
            norm_q = np.linalg.norm(query_embedding)
            norm_d = np.linalg.norm(doc.embedding)
            if norm_q == 0 or norm_d == 0:
                sim = 0.0
            else:
                sim = float(np.dot(query_embedding, doc.embedding) / (norm_q * norm_d))
            scores.append((sim, doc))

        # Sort by similarity (highest first)
        scores.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, doc in scores[:limit]:
            results.append({
                "id": doc.id,
                "score": score,  # similarity (higher = more similar)
                "metadata": doc.metadata,
                "document": doc.document,
            })

        return results

    # ── Batch operations ─────────────────────────────────────────

    def batch_upsert(
        self,
        collection_name: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> int:
        """Batch upsert documents into a collection."""
        embeddings = self._embed(documents)
        collection = self._get_collection(collection_name)

        count = 0
        for i, (doc_id, doc_text) in enumerate(zip(ids, documents)):
            embedding = embeddings[i]
            meta = (metadatas[i] if metadatas and i < len(metadatas) else {})
            meta["store"] = collection_name

            # Update or insert
            found = False
            for j, existing in enumerate(collection):
                if existing.id == doc_id:
                    collection[j] = VectorDocument(
                        id=doc_id, document=doc_text, embedding=embedding, metadata=meta,
                    )
                    found = True
                    break
            if not found:
                collection.append(VectorDocument(
                    id=doc_id, document=doc_text, embedding=embedding, metadata=meta,
                ))
            count += 1

        self._save_to_disk()
        return count

    # ── Delete ───────────────────────────────────────────────────

    def delete(self, collection_name: str, ids: list[str]) -> bool:
        """Delete documents by ID."""
        collection = self._get_collection(collection_name)
        id_set = set(ids)
        before = len(collection)
        self._collections[collection_name] = [d for d in collection if d.id not in id_set]
        if len(self._collections[collection_name]) < before:
            self._save_to_disk()
            return True
        return False

    # ── Stats ────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return document counts per collection."""
        stats: dict[str, Any] = {"available": True, "backend": "lightweight_numpy"}
        for name in self.ALL_COLLECTIONS:
            stats[name] = len(self._collections.get(name, []))
        return stats

    # ── Persistence ──────────────────────────────────────────────

    def _save_to_disk(self) -> None:
        """Persist all collections to JSON files."""
        if not self._persist_dir:
            return
        for name, docs in self._collections.items():
            path = self._persist_dir / f"{name}.json"
            data = []
            for doc in docs:
                data.append({
                    "id": doc.id,
                    "document": doc.document,
                    "embedding": doc.embedding.tolist(),
                    "metadata": doc.metadata,
                })
            try:
                with open(path, "w") as f:
                    json.dump(data, f)
            except Exception as exc:
                logger.error("vector_store_save_error", collection=name, error=str(exc))

    def _load_from_disk(self) -> None:
        """Load collections from JSON files."""
        for name in self.ALL_COLLECTIONS:
            path = self._persist_dir / f"{name}.json"
            if not path.exists():
                continue
            try:
                with open(path) as f:
                    data = json.load(f)
                docs = []
                for item in data:
                    docs.append(VectorDocument(
                        id=item["id"],
                        document=item["document"],
                        embedding=np.array(item["embedding"], dtype=np.float32),
                        metadata=item.get("metadata", {}),
                    ))
                self._collections[name] = docs
                logger.info("vector_store_loaded", collection=name, count=len(docs))
            except Exception as exc:
                logger.error("vector_store_load_error", collection=name, error=str(exc))

    def persist(self) -> None:
        """Force persist to disk."""
        self._save_to_disk()

    def close(self) -> None:
        """Clean up resources."""
        self._save_to_disk()
