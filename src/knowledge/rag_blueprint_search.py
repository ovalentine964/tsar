"""TSAR — RAG Blueprint Enhanced Knowledge Search.

Applies NVIDIA RAG Blueprint patterns to enhance TSAR's 5 knowledge stores:
- Semantic chunking for better retrieval
- Reranking for improved relevance
- Hybrid search weight tuning
- Query expansion and context enrichment

Integrates with existing FTS5 + ChromaDB infrastructure.
RAG Blueprint is optional — falls back to existing hybrid search.

Requires: nvidia-rag (pip install nvidia-rag) or NVIDIA NIM API
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)

# ── RAG Blueprint availability check ────────────────────────

try:
    # Try NVIDIA RAG Blueprint components
    from nvidia_rag import (
        Reranker,
        SemanticChunker,
    )

    RAG_BLUEPRINT_AVAILABLE = True
    logger.info("rag_blueprint_available", msg="NVIDIA RAG Blueprint enabled")
except ImportError:
    RAG_BLUEPRINT_AVAILABLE = False

    class _Stub:
        """Stub for missing RAG Blueprint classes."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "NVIDIA RAG Blueprint not installed. Install with: pip install nvidia-rag"
            )

    Reranker = _Stub  # type: ignore[assignment,misc]
    SemanticChunker = _Stub  # type: ignore[assignment,misc]


# ── Data classes ─────────────────────────────────────────────


@dataclass
class RerankedResult:
    """A search result after reranking."""

    store: str
    record_id: str
    original_score: float
    reranked_score: float
    snippet: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    context_window: str = ""  # Expanded context around the match

    def to_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "record_id": self.record_id,
            "original_score": round(self.original_score, 4),
            "reranked_score": round(self.reranked_score, 4),
            "snippet": self.snippet,
            "context_window": self.context_window[:500],
            "data": self.data,
        }


@dataclass
class EnhancedSearchResult:
    """Search results with RAG Blueprint enhancements."""

    results: list[RerankedResult]
    query_expansion: list[str] = field(default_factory=list)
    method: str = "rag_blueprint"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "query_expansion": self.query_expansion,
            "method": self.method,
            "count": len(self.results),
            "metadata": self.metadata,
        }


# ── Main RAG Blueprint Integration ──────────────────────────


class RAGBlueprintSearch:
    """Enhanced knowledge search using NVIDIA RAG Blueprint patterns.

    Improves upon TSAR's existing FTS5 + ChromaDB hybrid search by:
    1. Semantic chunking — splits documents at meaningful boundaries
    2. Reranking — reorders results using cross-encoder models
    3. Query expansion — generates related queries for better recall
    4. Context enrichment — expands snippets with surrounding context

    Falls back to existing MemoryRecall hybrid search if unavailable.

    Usage::

        rag = RAGBlueprintSearch(memory_recall, config)
        results = await rag.enhanced_search(
            query="mean reversion oversold RSI",
            stores=["trade_records", "patterns"],
        )
        for r in results.results:
            print(f"{r.store}/{r.record_id}: {r.reranked_score:.3f}")
    """

    def __init__(
        self,
        memory_recall: Any,  # MemoryRecall instance
        config: dict[str, Any] | None = None,
    ) -> None:
        self._recall = memory_recall
        self._config = config or {}
        self._available = RAG_BLUEPRINT_AVAILABLE
        self._reranker: Any = None
        self._chunker: Any = None
        self._fallback = self._config.get("fallback", "fts5_chromadb")

        # Initialize reranker if available
        if self._available:
            try:
                rerank_cfg = self._config.get("reranking", {})
                model_name = rerank_cfg.get("model", "nvidia/nv-rerankqa-mistral-4b-v3")
                self._reranker = Reranker(model=model_name)
                logger.info("rag_reranker_initialized", model=model_name)
            except Exception as exc:
                logger.warning("rag_reranker_init_failed", error=str(exc))
                self._reranker = None

            try:
                chunk_cfg = self._config.get("chunking", {})
                self._chunker = SemanticChunker(
                    max_tokens=chunk_cfg.get("max_chunk_tokens", 512),
                    overlap=chunk_cfg.get("overlap_tokens", 64),
                )
                logger.info("rag_chunker_initialized")
            except Exception as exc:
                logger.warning("rag_chunker_init_failed", error=str(exc))
                self._chunker = None

        if not self._available:
            logger.warning(
                "rag_blueprint_not_available",
                msg=f"RAG Blueprint not installed. Using {self._fallback} fallback.",
            )

    @property
    def available(self) -> bool:
        """Check if RAG Blueprint is available."""
        return self._available and self._reranker is not None

    # ── Enhanced Search ──────────────────────────────────────

    async def enhanced_search(
        self,
        query: str,
        stores: list[str] | None = None,
        limit: int = 20,
    ) -> EnhancedSearchResult:
        """Run enhanced search with RAG Blueprint patterns.

        Pipeline:
        1. Query expansion (generate related queries)
        2. Hybrid search (FTS5 + vector, existing infrastructure)
        3. Reranking (cross-encoder relevance scoring)
        4. Context enrichment (expand snippets)

        Falls back to existing hybrid search if RAG Blueprint unavailable.

        Args:
            query: Natural language search query.
            stores: Restrict to these knowledge stores.
            limit: Maximum results to return.

        Returns:
            EnhancedSearchResult with reranked results.
        """
        if not query or not query.strip():
            return EnhancedSearchResult(results=[], method="empty_query")

        # Step 1: Query expansion
        expanded_queries = await self._expand_query(query)

        # Step 2: Run searches (original + expanded)
        all_raw_results = []
        for q in [query] + expanded_queries:
            raw = await self._recall.hybrid_search(
                q,
                stores=stores,
                limit=limit,
            )
            all_raw_results.extend(raw)

        # Deduplicate by (store, record_id)
        seen: set[tuple[str, str]] = set()
        deduped = []
        for r in all_raw_results:
            key = (r.store, r.record_id)
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        # Step 3: Rerank
        if self.available and self._reranker:
            reranked = await self._rerank_results(query, deduped, limit)
        else:
            reranked = self._fallback_rerank(query, deduped, limit)

        # Step 4: Context enrichment
        enriched = await self._enrich_context(reranked)

        return EnhancedSearchResult(
            results=enriched,
            query_expansion=expanded_queries,
            method="rag_blueprint" if self.available else f"fallback_{self._fallback}",
            metadata={
                "original_query": query,
                "raw_result_count": len(all_raw_results),
                "deduped_count": len(deduped),
                "reranked_available": self.available,
            },
        )

    # ── Query Expansion ──────────────────────────────────────

    async def _expand_query(self, query: str) -> list[str]:
        """Generate related queries for better recall.

        Uses simple heuristic expansion (no LLM call needed).
        Returns 2-3 related queries.
        """
        expansions: list[str] = []

        # Strategy-specific expansions
        strategy_terms = {
            "mean reversion": ["oversold bounce", "Bollinger squeeze", "RSI reversal"],
            "momentum": ["trend following", "breakout", "moving average crossover"],
            "breakout": ["resistance break", "volume spike", "range expansion"],
            "scalping": ["quick profit", "tight stop", "high frequency"],
        }

        query_lower = query.lower()
        for key, expansions_list in strategy_terms.items():
            if key in query_lower:
                expansions.extend(expansions_list[:2])
                break

        # Add technical indicator expansions
        indicator_terms = {
            "rsi": ["overbought oversold", "momentum divergence"],
            "macd": ["moving average convergence", "signal line crossover"],
            "bollinger": ["volatility bands", "standard deviation channel"],
            "atr": ["average true range", "volatility measure"],
        }

        for key, terms in indicator_terms.items():
            if key in query_lower:
                expansions.extend(terms[:1])
                break

        # Limit to 3 expansions
        return expansions[:3]

    # ── Reranking ────────────────────────────────────────────

    async def _rerank_results(
        self,
        query: str,
        results: list[Any],
        limit: int,
    ) -> list[RerankedResult]:
        """Rerank results using NVIDIA cross-encoder model."""
        assert self._reranker is not None

        def _run() -> list[RerankedResult]:
            # Prepare documents for reranking
            documents = []
            for r in results:
                doc_text = r.snippet or ""
                if r.data:
                    # Add key fields to document text
                    for key in ["thesis", "description", "title", "content"]:
                        if key in r.data and r.data[key]:
                            doc_text += f" {r.data[key]}"
                documents.append(doc_text[:1000])  # Limit doc length

            # Rerank
            rerank_cfg = self._config.get("reranking", {})
            top_k = rerank_cfg.get("top_k", limit)
            reranked_scores = self._reranker.rerank(
                query=query,
                documents=documents,
                top_k=min(top_k, len(documents)),
            )

            # Build reranked results
            reranked = []
            for idx, score in reranked_scores:
                if idx < len(results):
                    r = results[idx]
                    reranked.append(
                        RerankedResult(
                            store=r.store,
                            record_id=r.record_id,
                            original_score=r.score,
                            reranked_score=float(score),
                            snippet=r.snippet,
                            data=r.data,
                        )
                    )

            return reranked[:limit]

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    def _fallback_rerank(
        self,
        query: str,
        results: list[Any],
        limit: int,
    ) -> list[RerankedResult]:
        """Simple fallback reranking using keyword overlap."""
        query_tokens = set(query.lower().split())

        reranked = []
        for r in results:
            # Compute keyword overlap score
            doc_text = (r.snippet or "").lower()
            if r.data:
                for val in r.data.values():
                    if isinstance(val, str):
                        doc_text += f" {val.lower()}"

            doc_tokens = set(doc_text.split())
            overlap = len(query_tokens & doc_tokens)
            keyword_score = overlap / max(len(query_tokens), 1)

            # Combine with original score (normalized)
            combined = 0.6 * keyword_score + 0.4 * (1.0 / max(abs(r.score), 0.001))

            reranked.append(
                RerankedResult(
                    store=r.store,
                    record_id=r.record_id,
                    original_score=r.score,
                    reranked_score=combined,
                    snippet=r.snippet,
                    data=r.data,
                )
            )

        reranked.sort(key=lambda x: x.reranked_score, reverse=True)
        return reranked[:limit]

    # ── Context Enrichment ───────────────────────────────────

    async def _enrich_context(
        self,
        results: list[RerankedResult],
    ) -> list[RerankedResult]:
        """Expand result snippets with surrounding context.

        For trade records, includes the trade thesis and reflection.
        For lessons, includes the full content.
        """
        if not self._recall._db:
            return results

        enriched = []
        for r in results:
            try:
                context = await self._fetch_context(r.store, r.record_id)
                r.context_window = context
            except Exception:
                pass  # Keep original snippet if enrichment fails
            enriched.append(r)

        return enriched

    async def _fetch_context(self, store: str, record_id: str) -> str:
        """Fetch expanded context for a record from the database."""
        assert self._recall._db is not None

        # Map store to table and ID column
        store_map = {
            "trade_records": ("trade_records", "trade_id"),
            "strategy_genomes": ("strategy_genomes", "strategy_id"),
            "patterns": ("patterns", "pattern_id"),
            "lessons": ("lessons", "lesson_id"),
        }

        if store not in store_map:
            return ""

        table, id_col = store_map[store]

        try:
            row = await self._recall._db.execute_fetchall(
                f"SELECT * FROM {table} WHERE {id_col} = ?",
                (record_id,),
            )
            if row:
                # Concatenate all text fields
                context_parts = []
                for key, val in dict(row[0]).items():
                    if isinstance(val, str) and val and key != id_col:
                        context_parts.append(f"{key}: {val}")
                return " | ".join(context_parts)
        except Exception as exc:
            logger.debug("context_fetch_error", store=store, error=str(exc))

        return ""

    # ── Status ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return RAG Blueprint status."""
        return {
            "available": self.available,
            "reranker_loaded": self._reranker is not None,
            "chunker_loaded": self._chunker is not None,
            "fallback": self._fallback,
            "method": "rag_blueprint" if self.available else f"fallback_{self._fallback}",
        }
