"""
TSAR Domain Tools — Knowledge Stores.

Eight knowledge tools that give agents persistent memory, pattern matching,
lesson learning, strategy evolution, regime classification, factor analysis,
full-text search, and vector similarity search.

Tools:
  1. Trade Memory     — Store/retrieve every trade with full context
  2. Pattern Library  — Discover, store, match chart/candlestick patterns
  3. Lesson Archive   — Extract, store, apply lessons from trade outcomes
  4. Strategy Genomes — Evolve, mutate, select strategy parameters
  5. Regime State     — Classify, store, query market regimes
  6. Factor Library   — Compute, rank, track factor IC decay
  7. FTS5 Search      — Full-text search across all knowledge stores
  8. Vector Similarity — ChromaDB semantic search across stores

Usage::

    tools = KnowledgeTools("/path/to/tsar.db")

    # Tool 1: Trade Memory
    trade_id = tools.trade_memory.insert_trade(trade)
    trades = tools.trade_memory.list_trades(limit=50)

    # Tool 2: Pattern Library
    patterns = tools.pattern_library.get_active_patterns()

    # Tool 7: FTS5 Search (async)
    await tools.init_fts()
    results = await tools.fts_search.search("bearish reversal")

    tools.close()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.knowledge.chromadb_store import ChromaVectorStore, VectorSearchResult, is_chromadb_available
from src.knowledge.fts_search import MemoryRecall, SearchResult
from src.knowledge.lesson_archive import LessonArchive
from src.knowledge.pattern_library import PatternLibrary
from src.knowledge.regime_state import (
    RegimeGraphSnapshot,
    RegimeState,
    RegimeStateStore,
    RegimeTransition,
    RegimeTransitionEdge,
    TemporalRegimeGraph,
)
from src.knowledge.strategy_genomes import StrategyGenomes
from src.knowledge.trade_memory import (
    TradeJournalEntry,
    TradeMemory,
    TradeRecord,
    TradeSnapshot,
)
from src.strategy.factor_library import FactorLibrary

logger = get_logger = logging.getLogger

__all__ = ["KnowledgeTools"]


class KnowledgeTools:
    """Unified knowledge tools for TSAR agents.

    Wraps eight knowledge subsystems behind a single interface:

    1. trade_memory     — episodic trade memory (CRUD, FTS, snapshots, journal)
    2. pattern_library  — pattern discovery, storage, matching, relationships
    3. lesson_archive   — lesson extraction, application tracking, violations
    4. strategy_genomes — strategy genome evolution, mutation, selection
    5. regime_state     — regime classification, transitions, temporal graph
    6. factor_library   — factor registration, IC tracking, decay analysis
    7. fts_search       — full-text search across all stores (async)
    8. vector_search    — ChromaDB semantic similarity search

    All tools share the same SQLite database at ``db_path``.

    Attributes:
        trade_memory: TradeMemory instance.
        pattern_library: PatternLibrary instance.
        lesson_archive: LessonArchive instance.
        strategy_genomes: StrategyGenomes instance.
        regime_store: RegimeStateStore instance.
        regime_graph: TemporalRegimeGraph instance.
        factor_library: FactorLibrary instance.
        vector_store: ChromaVectorStore instance (may be unavailable).
    """

    description = (
        "Knowledge tools: trade memory, pattern library, lesson archive, "
        "strategy genomes, regime state, factor library, FTS5 search, "
        "vector similarity"
    )

    def __init__(
        self,
        db_path: str | Path = "tsar.db",
        redis_client: Any | None = None,
        chromadb_dir: str | Path | None = None,
        factor_db_path: str | Path | None = None,
    ) -> None:
        """Initialize all knowledge stores.

        Args:
            db_path: Path to the main SQLite database.
            redis_client: Optional Redis client for RegimeStateStore.
            chromadb_dir: Optional ChromaDB persistence directory.
            factor_db_path: Optional separate DB for factor library.
        """
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Tool 1: Trade Memory
        self.trade_memory = TradeMemory(self._db_path)
        logger(__name__).info("knowledge_tool_init", tool="trade_memory", db=self._db_path)

        # Tool 2: Pattern Library
        self.pattern_library = PatternLibrary(self._db_path)
        logger(__name__).info("knowledge_tool_init", tool="pattern_library")

        # Tool 3: Lesson Archive
        self.lesson_archive = LessonArchive(self._db_path)
        logger(__name__).info("knowledge_tool_init", tool="lesson_archive")

        # Tool 4: Strategy Genomes
        self.strategy_genomes = StrategyGenomes(self._db_path)
        logger(__name__).info("knowledge_tool_init", tool="strategy_genomes")

        # Tool 5: Regime State (in-memory or Redis)
        self.regime_store = RegimeStateStore(redis_client=redis_client)
        self.regime_graph = TemporalRegimeGraph(self._db_path)
        logger(__name__).info("knowledge_tool_init", tool="regime_state")

        # Tool 6: Factor Library (separate or shared DB)
        fpath = str(factor_db_path) if factor_db_path else self._db_path
        self.factor_library = FactorLibrary(fpath)
        logger(__name__).info("knowledge_tool_init", tool="factor_library", db=fpath)

        # Tool 7: FTS5 Search (async — must call init_fts() first)
        self._fts_recall: MemoryRecall | None = None
        self._fts_db_path = self._db_path

        # Tool 8: Vector Similarity
        self._chromadb_dir = str(chromadb_dir) if chromadb_dir else None
        self.vector_store: ChromaVectorStore | None = None
        if is_chromadb_available():
            try:
                self.vector_store = ChromaVectorStore(
                    persist_dir=chromadb_dir,
                )
                logger(__name__).info("knowledge_tool_init", tool="vector_search", available=True)
            except Exception as exc:
                logger(__name__).warning("vector_search_init_failed", error=str(exc))
        else:
            logger(__name__).info("knowledge_tool_init", tool="vector_search", available=False)

    # ── Tool 7: FTS5 Search (async lifecycle) ────────────────

    async def init_fts(self) -> None:
        """Initialize the async FTS5 search engine.

        Must be called before using ``fts_search``.
        """
        if self._fts_recall is None:
            self._fts_recall = MemoryRecall(
                db_path=self._fts_db_path,
                chromadb_dir=self._chromadb_dir,
            )
            await self._fts_recall.initialize()
            logger(__name__).info("fts5_initialized")

    @property
    def fts_search(self) -> MemoryRecall:
        """Access the FTS5 search engine.

        Raises:
            RuntimeError: If ``init_fts()`` has not been called.
        """
        if self._fts_recall is None:
            raise RuntimeError("FTS5 search not initialized. Call await init_fts() first.")
        return self._fts_recall

    async def search(
        self,
        query: str,
        stores: list[str] | None = None,
        limit: int = 20,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Unified search across all knowledge stores.

        Args:
            query: Search query string.
            stores: Optional list of store names to search.
                    Defaults to all stores.
            limit: Maximum results per store.
            mode: "fts" for full-text only, "semantic" for vector only,
                  "hybrid" for combined FTS5 + vector.

        Returns:
            List of search result dicts.
        """
        await self.init_fts()
        recall = self.fts_search

        if mode == "fts":
            results = await recall.search(query, stores=stores, limit=limit)
        elif mode == "semantic":
            results = await recall.semantic_search(query, stores=stores, limit=limit)
        else:  # hybrid
            results = await recall.hybrid_search(query, stores=stores, limit=limit)

        return [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in results]

    # ── Convenience wrappers ─────────────────────────────────

    # Tool 1: Trade Memory shortcuts

    def record_trade(self, trade: TradeRecord) -> str:
        """Insert a trade record. Returns trade_id."""
        return self.trade_memory.insert_trade(trade)

    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        """Retrieve a trade by ID."""
        t = self.trade_memory.get_trade(trade_id)
        return t.to_dict() if t else None

    def list_trades(
        self,
        strategy_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List trades with optional filters."""
        trades = self.trade_memory.list_trades(
            strategy_id=strategy_id,
            symbol=symbol,
            status=status,
            since=since,
            limit=limit,
            offset=offset,
        )
        return [t.to_dict() for t in trades]

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Get all open positions."""
        return [t.to_dict() for t in self.trade_memory.get_open_positions()]

    def get_strategy_summary(self, since: str | None = None) -> list[dict[str, Any]]:
        """Get per-strategy performance summary."""
        return self.trade_memory.get_strategy_summary(since=since)

    def record_snapshot(self, snapshot: TradeSnapshot) -> str:
        """Record a market state snapshot for a trade."""
        return self.trade_memory.insert_snapshot(snapshot)

    def record_journal(self, entry: TradeJournalEntry) -> str:
        """Record a trade journal entry."""
        return self.trade_memory.insert_journal_entry(entry)

    def link_trade_lesson(self, trade_id: str, lesson_id: str, relevance: float = 1.0) -> None:
        """Link a lesson to a trade."""
        self.trade_memory.link_lesson(trade_id, lesson_id, relevance)

    def link_trade_pattern(self, trade_id: str, pattern_id: str, match_score: float = 0.0) -> None:
        """Link a pattern to a trade."""
        self.trade_memory.link_pattern(trade_id, pattern_id, match_score)

    # Tool 2: Pattern Library shortcuts

    def discover_pattern(self, pattern: Any) -> str:
        """Store a newly discovered pattern. Returns pattern_id."""
        return self.pattern_library.insert_pattern(pattern)

    def get_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        """Retrieve a pattern by ID."""
        p = self.pattern_library.get_pattern(pattern_id)
        return p.to_dict() if p else None

    def search_patterns(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search patterns by name/description."""
        return self.pattern_library.search_patterns(query, limit=limit)

    def get_active_patterns(self) -> list[dict[str, Any]]:
        """Get all active patterns."""
        return [p.to_dict() for p in self.pattern_library.get_active_patterns()]

    def get_top_patterns(self, limit: int = 10, metric: str = "expectancy") -> list[dict[str, Any]]:
        """Get top-performing patterns by metric."""
        return [p.to_dict() for p in self.pattern_library.get_top_patterns(limit, metric)]

    def match_pattern(self, pattern_id: str, trade_id: str, match_score: float = 0.0) -> str:
        """Record a pattern observation/match."""
        from src.knowledge.pattern_library import PatternObservation
        obs = PatternObservation(
            pattern_id=pattern_id,
            trade_id=trade_id,
            match_score=match_score,
        )
        return self.pattern_library.record_observation(obs)

    def get_co_occurring_patterns(self, pattern_id: str, min_strength: float = 0.5) -> list[dict[str, Any]]:
        """Find patterns that co-occur with the given pattern."""
        return self.pattern_library.get_co_occurring_patterns(pattern_id, min_strength)

    # Tool 3: Lesson Archive shortcuts

    def store_lesson(self, lesson: Any) -> str:
        """Store a new lesson. Returns lesson_id."""
        return self.lesson_archive.insert_lesson(lesson)

    def get_lesson(self, lesson_id: str) -> dict[str, Any] | None:
        """Retrieve a lesson by ID."""
        l = self.lesson_archive.get_lesson(lesson_id)
        return l.to_dict() if l else None

    def list_lessons(
        self,
        lesson_type: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List lessons with optional filters."""
        return [l.to_dict() for l in self.lesson_archive.list_lessons(
            lesson_type=lesson_type, severity=severity, limit=limit,
        )]

    def get_critical_lessons(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get critical-severity lessons."""
        return [l.to_dict() for l in self.lesson_archive.get_critical_lessons(limit)]

    def get_recent_lessons(self, days: int = 7, limit: int = 50) -> list[dict[str, Any]]:
        """Get recently discovered lessons."""
        return [l.to_dict() for l in self.lesson_archive.get_recent_lessons(days, limit)]

    def get_most_violated(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get most frequently violated lessons."""
        return self.lesson_archive.get_most_violated(limit)

    def apply_lesson(self, lesson_id: str, trade_id: str, outcome: str = "followed") -> str:
        """Record a lesson application event."""
        from src.knowledge.lesson_archive import LessonApplication
        app = LessonApplication(
            lesson_id=lesson_id,
            trade_id=trade_id,
            outcome=outcome,
        )
        return self.lesson_archive.record_application(app)

    def record_violation(self, lesson_id: str, trade_id: str, severity: str = "minor", reason: str = "") -> str:
        """Record a lesson violation."""
        from src.knowledge.lesson_archive import LessonViolation
        v = LessonViolation(
            lesson_id=lesson_id,
            trade_id=trade_id,
            severity=severity,
            reason=reason,
        )
        return self.lesson_archive.record_violation(v)

    def get_lessons_for_regime(self, regime: str) -> list[dict[str, Any]]:
        """Get lessons applicable to a specific regime."""
        return [l.to_dict() for l in self.lesson_archive.get_lessons_for_regime(regime)]

    def get_lessons_for_symbol(self, symbol: str) -> list[dict[str, Any]]:
        """Get lessons applicable to a specific symbol."""
        return [l.to_dict() for l in self.lesson_archive.get_lessons_for_symbol(symbol)]

    # Tool 4: Strategy Genomes shortcuts

    def evolve_strategy(self, genome: Any) -> str:
        """Store a new strategy genome. Returns strategy_id."""
        return self.strategy_genomes.insert_genome(genome)

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        """Retrieve a strategy genome by ID."""
        g = self.strategy_genomes.get_genome(strategy_id)
        return g.to_dict() if g else None

    def get_active_strategies(self) -> list[dict[str, Any]]:
        """Get all active strategy genomes."""
        return [g.to_dict() for g in self.strategy_genomes.get_active_strategies()]

    def mutate_strategy(self, strategy_id: str, mutation: Any) -> str:
        """Record a mutation on a strategy genome."""
        return self.strategy_genomes.record_mutation(mutation)

    def get_mutations(self, strategy_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get mutation history for a strategy."""
        return [m.to_dict() for m in self.strategy_genomes.get_mutations(strategy_id, limit=limit)]

    def get_lineage(self, strategy_id: str) -> list[dict[str, Any]]:
        """Get the evolutionary lineage of a strategy."""
        return self.strategy_genomes.get_lineage(strategy_id)

    def record_performance(self, perf: Any) -> str:
        """Record a strategy performance observation."""
        return self.strategy_genomes.insert_performance(perf)

    def evaluate_gates(self, strategy_id: str) -> dict[str, Any]:
        """Evaluate promotion/demotion gates for a strategy."""
        return self.strategy_genomes.evaluate_gates(strategy_id)

    def get_mutation_effectiveness(self) -> list[dict[str, Any]]:
        """Rank mutations by their effectiveness."""
        return self.strategy_genomes.get_mutation_effectiveness()

    # Tool 5: Regime State shortcuts

    def classify_regime(self, state: RegimeState) -> None:
        """Update the global regime classification."""
        self.regime_store.update_global_regime(state)

    def get_global_regime(self) -> dict[str, Any] | None:
        """Get the current global regime."""
        s = self.regime_store.get_global_regime()
        return s.to_dict() if s else None

    def get_asset_regime(self, symbol: str) -> dict[str, Any] | None:
        """Get the regime for a specific asset."""
        s = self.regime_store.get_asset_regime(symbol)
        return s.to_dict() if s else None

    def get_effective_regime(self, symbol: str) -> dict[str, Any]:
        """Get the effective regime (asset-specific or global fallback)."""
        return self.regime_store.get_effective_regime(symbol).to_dict()

    def record_regime_transition(self, transition: RegimeTransition) -> None:
        """Record a regime transition event."""
        self.regime_store.record_transition(transition)

    def get_recent_transitions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent regime transitions."""
        return [t.to_dict() for t in self.regime_store.get_recent_transitions(limit)]

    def list_asset_regimes(self) -> list[str]:
        """List all assets with regime data."""
        return self.regime_store.list_asset_regimes()

    def get_regime_snapshot(self) -> dict[str, Any]:
        """Get a full snapshot of all regime state."""
        return self.regime_store.snapshot_to_dict()

    def get_transition_graph(self, asset: str = "GLOBAL") -> dict[str, Any]:
        """Get the temporal regime transition graph snapshot."""
        snapshot = self.regime_graph.compute_snapshot(asset)
        return snapshot.to_dict()

    def get_transition_matrix(self, asset: str = "GLOBAL") -> dict[str, dict[str, float]]:
        """Get the regime transition probability matrix."""
        snapshot = self.regime_graph.compute_snapshot(asset)
        return snapshot.get_transition_matrix()

    def get_steady_state(self, asset: str = "GLOBAL") -> dict[str, float]:
        """Compute the long-run regime distribution."""
        snapshot = self.regime_graph.compute_snapshot(asset)
        return snapshot.steady_state()

    # Tool 6: Factor Library shortcuts

    def compute_factor(self, name: str, ohlcv_df: Any, **params: Any) -> Any:
        """Compute a single factor on OHLCV data."""
        return self.factor_library.compute(name, ohlcv_df, **params)

    def compute_all_factors(self, ohlcv_df: Any, category: str | None = None) -> dict[str, Any]:
        """Compute all registered factors (or a category) on OHLCV data."""
        return self.factor_library.compute_all(ohlcv_df, category=category)

    def record_ic(self, factor_name: str, ic_value: float, forward_period: int = 1, symbol: str = "") -> str:
        """Record an Information Coefficient observation."""
        return self.factor_library.record_ic(factor_name, ic_value, forward_period, symbol)

    def get_ic_history(self, factor_name: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get IC history for a factor."""
        return [r.__dict__ for r in self.factor_library.get_ic_history(factor_name, limit)]

    def get_ic_decay(self, factor_name: str, window_days: int = 30) -> dict[str, Any]:
        """Get IC decay analysis for a factor."""
        return self.factor_library.get_ic_decay(factor_name, window_days)

    def get_factors_with_decay_alert(self, threshold: float = 0.5) -> list[dict[str, Any]]:
        """Get factors whose IC has decayed below threshold."""
        return self.factor_library.get_factors_with_decay_alert(threshold)

    def list_factors(self, category: str | None = None) -> list[dict[str, Any]]:
        """List registered factors."""
        if category:
            factors = self.factor_library.get_factors_by_category(category)
        else:
            factors = self.factor_library.list_factors()
        return [f.__dict__ for f in factors]

    def get_factor_categories(self) -> dict[str, int]:
        """Get factor category counts."""
        return self.factor_library.get_categories()

    def batch_factor_significance(self, ohlcv_df: Any, forward_returns: Any) -> list[dict[str, Any]]:
        """Run significance tests on all factors."""
        return self.factor_library.batch_factor_significance(ohlcv_df, forward_returns)

    # Tool 8: Vector Similarity shortcuts

    def vector_upsert_pattern(self, pattern_id: str, document: str, metadata: dict[str, Any] | None = None) -> bool:
        """Store/update a pattern embedding."""
        if self.vector_store is None:
            return False
        return self.vector_store.upsert_pattern(pattern_id, document, metadata)

    def vector_search_patterns(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Semantic search for similar patterns."""
        if self.vector_store is None:
            return []
        results = self.vector_store.search_similar_patterns(query, limit)
        return [r.to_dict() for r in results]

    def vector_upsert_trade(self, trade_id: str, document: str, metadata: dict[str, Any] | None = None) -> bool:
        """Store/update a trade embedding."""
        if self.vector_store is None:
            return False
        return self.vector_store.upsert_trade(trade_id, document, metadata)

    def vector_search_trades(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Semantic search for similar trades."""
        if self.vector_store is None:
            return []
        results = self.vector_store.search_similar_trades(query, limit)
        return [r.to_dict() for r in results]

    def vector_upsert_lesson(self, lesson_id: str, document: str, metadata: dict[str, Any] | None = None) -> bool:
        """Store/update a lesson embedding."""
        if self.vector_store is None:
            return False
        return self.vector_store.upsert_lesson(lesson_id, document, metadata)

    def vector_search_lessons(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Semantic search for similar lessons."""
        if self.vector_store is None:
            return []
        results = self.vector_store.search_similar_lessons(query, limit)
        return [r.to_dict() for r in results]

    def vector_upsert_market_state(self, state_id: str, document: str, metadata: dict[str, Any] | None = None) -> bool:
        """Store/update a market state embedding."""
        if self.vector_store is None:
            return False
        return self.vector_store.upsert_market_state(state_id, document, metadata)

    def vector_search_market_states(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Semantic search for similar market states."""
        if self.vector_store is None:
            return []
        results = self.vector_store.search_similar_market_states(query, limit)
        return [r.to_dict() for r in results]

    def vector_stats(self) -> dict[str, Any]:
        """Get vector store statistics."""
        if self.vector_store is None:
            return {"available": False}
        stats = self.vector_store.get_stats()
        stats["available"] = True
        return stats

    # ── Lifecycle ────────────────────────────────────────────

    def close(self) -> None:
        """Close all stores and release resources."""
        self.factor_library.close()
        if self.vector_store is not None:
            self.vector_store.close()
        logger(__name__).info("knowledge_tools_closed")

    async def async_close(self) -> None:
        """Close async stores (FTS5)."""
        if self._fts_recall is not None:
            await self._fts_recall.close()
            self._fts_recall = None

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics across all knowledge stores."""
        return {
            "trade_count": self.trade_memory.get_trade_count(),
            "open_positions": len(self.trade_memory.get_open_positions()),
            "pattern_count": len(self.pattern_library.list_patterns()),
            "active_patterns": len(self.pattern_library.get_active_patterns()),
            "lesson_count": len(self.lesson_archive.list_lessons()),
            "strategy_count": len(self.strategy_genomes.list_genomes()),
            "active_strategies": len(self.strategy_genomes.get_active_strategies()),
            "asset_regimes": self.regime_store.list_asset_regimes(),
            "factor_count": len(self.factor_library.list_factors()),
            "factor_categories": self.factor_library.get_categories(),
            "vector_store": self.vector_stats(),
        }
