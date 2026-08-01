"""TSAR — ChromaDB Vector Store.

Provides vector similarity search for semantic pattern matching.
ChromaDB is optional — all operations degrade gracefully if not installed.

Capabilities:
- Store and query embeddings for patterns, trades, and lessons
- Semantic similarity search ("find patterns similar to current market condition")
- Hybrid search combining FTS5 keyword + vector similarity
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)

# ── ChromaDB availability check ─────────────────────────────

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    chromadb = None  # type: ignore[assignment]
    ChromaSettings = None  # type: ignore[assignment,misc]


def is_chromadb_available() -> bool:
    """Check if ChromaDB is installed and usable."""
    return CHROMADB_AVAILABLE


# ── Collection names ────────────────────────────────────────

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


# ── Result dataclass ────────────────────────────────────────


@dataclass
class VectorSearchResult:
    """A single vector similarity search hit."""

    id: str
    score: float  # distance (lower = more similar for L2/cosine)
    metadata: dict[str, Any] = field(default_factory=dict)
    document: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "score": self.score,
            "metadata": self.metadata,
            "document": self.document,
        }


# ── Embedding function abstraction ──────────────────────────


class EmbeddingFunction:
    """Pluggable embedding function. Defaults to a simple hash-based stub.

    In production, replace with OpenAI/sentence-transformers/etc.
    The stub produces deterministic 128-dim vectors from text so that
    the rest of the pipeline works without an API key.
    """

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._text_to_vector(text) for text in input]

    @staticmethod
    def _text_to_vector(text: str, dim: int = 128) -> list[float]:
        """Deterministic hash-based embedding stub.

        Produces a normalised vector from SHA-512 hash chunks.
        NOT suitable for real semantic search — replace with a real model.
        """
        h = hashlib.sha512(text.encode("utf-8")).hexdigest()
        # Repeat hash to fill dimension
        raw = h * (dim // len(h) + 1)
        values = []
        for i in range(dim):
            # Convert hex pairs to float in [-1, 1]
            byte_val = int(raw[i * 2 : i * 2 + 2], 16)
            values.append((byte_val - 127.5) / 127.5)
        # Normalize to unit vector
        mag = sum(v * v for v in values) ** 0.5
        if mag > 0:
            values = [v / mag for v in values]
        return values


# ── Main class ──────────────────────────────────────────────


class ChromaVectorStore:
    """Vector similarity search backed by ChromaDB.

    ChromaDB is optional. If not installed, all write operations are no-ops
    and all read operations return empty results.

    Usage::

        store = ChromaVectorStore("/path/to/chromadb")
        store.upsert_pattern(pattern_id, "double bottom reversal", metadata={...})
        results = store.search_similar_patterns("bearish reversal pattern", limit=5)
    """

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        embedding_fn: Any | None = None,
    ) -> None:
        self._available = CHROMADB_AVAILABLE
        self._client: Any = None
        self._collections: dict[str, Any] = {}
        self._embedding_fn = embedding_fn or EmbeddingFunction()

        if not self._available:
            logger.warning("chromadb_not_installed", msg="Vector search disabled. Install chromadb.")
            return

        try:
            persist_path = str(persist_dir) if persist_dir else None
            if persist_path:
                Path(persist_path).mkdir(parents=True, exist_ok=True)
                # Modern ChromaDB API (>=0.4): PersistentClient
                # Replaces deprecated duckdb+parquet Settings approach
                self._client = chromadb.PersistentClient(
                    path=persist_path,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            else:
                self._client = chromadb.Client(
                    ChromaSettings(anonymized_telemetry=False)
                )
            logger.info("chromadb_initialized", persist_dir=persist_path)
        except TypeError:
            # Fallback for older ChromaDB versions (<0.4) that lack PersistentClient
            try:
                if persist_path:
                    self._client = chromadb.Client(
                        ChromaSettings(
                            chroma_db_impl="duckdb+parquet",
                            persist_directory=persist_path,
                            anonymized_telemetry=False,
                        )
                    )
                else:
                    self._client = chromadb.Client(
                        ChromaSettings(anonymized_telemetry=False)
                    )
                logger.info("chromadb_initialized_legacy", persist_dir=persist_path)
            except Exception as exc:
                logger.error("chromadb_init_failed", error=str(exc))
                self._available = False
        except Exception as exc:
            logger.error("chromadb_init_failed", error=str(exc))
            self._available = False

    @property
    def available(self) -> bool:
        return self._available and self._client is not None

    def _get_collection(self, name: str) -> Any:
        """Get or create a ChromaDB collection."""
        if not self.available:
            return None
        if name not in self._collections:
            try:
                self._collections[name] = self._client.get_or_create_collection(
                    name=name,
                    embedding_function=self._embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as exc:
                logger.error("chromadb_collection_error", collection=name, error=str(exc))
                return None
        return self._collections[name]

    # ── Pattern operations ───────────────────────────────────

    def upsert_pattern(
        self,
        pattern_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store or update a pattern embedding."""
        collection = self._get_collection(COLLECTION_PATTERNS)
        if collection is None:
            return False
        try:
            meta = metadata or {}
            meta["store"] = "patterns"
            collection.upsert(
                ids=[pattern_id],
                documents=[document],
                metadatas=[meta],
            )
            return True
        except Exception as exc:
            logger.error("chromadb_upsert_error", id=pattern_id, error=str(exc))
            return False

    def search_similar_patterns(
        self,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Find patterns semantically similar to the query."""
        return self._search_collection(COLLECTION_PATTERNS, query, limit, where)

    # ── Trade operations ─────────────────────────────────────

    def upsert_trade(
        self,
        trade_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store or update a trade embedding."""
        collection = self._get_collection(COLLECTION_TRADES)
        if collection is None:
            return False
        try:
            meta = metadata or {}
            meta["store"] = "trades"
            collection.upsert(
                ids=[trade_id],
                documents=[document],
                metadatas=[meta],
            )
            return True
        except Exception as exc:
            logger.error("chromadb_upsert_error", id=trade_id, error=str(exc))
            return False

    def search_similar_trades(
        self,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Find trades semantically similar to the query."""
        return self._search_collection(COLLECTION_TRADES, query, limit, where)

    # ── Lesson operations ────────────────────────────────────

    def upsert_lesson(
        self,
        lesson_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store or update a lesson embedding."""
        collection = self._get_collection(COLLECTION_LESSONS)
        if collection is None:
            return False
        try:
            meta = metadata or {}
            meta["store"] = "lessons"
            collection.upsert(
                ids=[lesson_id],
                documents=[document],
                metadatas=[meta],
            )
            return True
        except Exception as exc:
            logger.error("chromadb_upsert_error", id=lesson_id, error=str(exc))
            return False

    def search_similar_lessons(
        self,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Find lessons semantically similar to the query."""
        return self._search_collection(COLLECTION_LESSONS, query, limit, where)

    # ── Market state operations ──────────────────────────────

    def upsert_market_state(
        self,
        state_id: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store a market state snapshot embedding."""
        collection = self._get_collection(COLLECTION_MARKET_STATE)
        if collection is None:
            return False
        try:
            meta = metadata or {}
            meta["store"] = "market_state"
            collection.upsert(
                ids=[state_id],
                documents=[document],
                metadatas=[meta],
            )
            return True
        except Exception as exc:
            logger.error("chromadb_upsert_error", id=state_id, error=str(exc))
            return False

    def search_similar_market_states(
        self,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Find market states semantically similar to the query."""
        return self._search_collection(COLLECTION_MARKET_STATE, query, limit, where)

    # ── Generic search ───────────────────────────────────────

    def _search_collection(
        self,
        collection_name: str,
        query: str,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Search a collection by text similarity."""
        collection = self._get_collection(collection_name)
        if collection is None:
            return []
        try:
            kwargs: dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(limit, collection.count() or limit),
            }
            if where:
                kwargs["where"] = where
            results = collection.query(**kwargs)
            return self._parse_results(results)
        except Exception as exc:
            logger.error("chromadb_search_error", collection=collection_name, error=str(exc))
            return []

    @staticmethod
    def _parse_results(results: dict[str, Any]) -> list[VectorSearchResult]:
        """Parse ChromaDB query results into VectorSearchResult list."""
        parsed: list[VectorSearchResult] = []
        if not results or not results.get("ids"):
            return parsed
        ids = results["ids"][0] if results["ids"] else []
        distances = results.get("distances", [[]])[0] if results.get("distances") else [0.0] * len(ids)
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else [{}] * len(ids)
        documents = results.get("documents", [[]])[0] if results.get("documents") else [""] * len(ids)
        for i, doc_id in enumerate(ids):
            parsed.append(
                VectorSearchResult(
                    id=doc_id,
                    score=distances[i] if i < len(distances) else 0.0,
                    metadata=metadatas[i] if i < len(metadatas) else {},
                    document=documents[i] if i < len(documents) else "",
                )
            )
        return parsed

    # ── Batch operations ─────────────────────────────────────

    def batch_upsert(
        self,
        collection_name: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> int:
        """Batch upsert documents into a collection.

        Returns the number of documents upserted.
        """
        collection = self._get_collection(collection_name)
        if collection is None:
            return 0
        try:
            kwargs: dict[str, Any] = {
                "ids": ids,
                "documents": documents,
            }
            if metadatas:
                kwargs["metadatas"] = metadatas
            collection.upsert(**kwargs)
            return len(ids)
        except Exception as exc:
            logger.error("chromadb_batch_upsert_error", collection=collection_name, error=str(exc))
            return 0

    # ── Delete operations ────────────────────────────────────

    def delete(self, collection_name: str, ids: list[str]) -> bool:
        """Delete documents by ID."""
        collection = self._get_collection(collection_name)
        if collection is None:
            return False
        try:
            collection.delete(ids=ids)
            return True
        except Exception as exc:
            logger.error("chromadb_delete_error", collection=collection_name, error=str(exc))
            return False

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return document counts per collection."""
        stats: dict[str, Any] = {"available": self.available}
        if not self.available:
            return stats
        for name in ALL_COLLECTIONS:
            collection = self._get_collection(name)
            if collection:
                stats[name] = collection.count()
            else:
                stats[name] = -1
        return stats

    # ── Persistence ──────────────────────────────────────────

    def persist(self) -> None:
        """Force persist to disk (ChromaDB persistent mode)."""
        if self.available and self._client:
            try:
                self._client.persist()
            except Exception:
                pass  # Not all ChromaDB modes support explicit persist

    def close(self) -> None:
        """Clean up resources."""
        self.persist()
        self._collections.clear()
