# Knowledge Tools Council — Review & Sign-Off

**Council:** Knowledge Tools
**Date:** 2026-07-30
**Status:** ✅ COMPLETE — All 9 tools implemented

---

## Summary

The Knowledge Tools Council implements TSAR's persistent memory and intelligence layer —
nine tools that give agents the ability to remember, learn, evolve, and connect knowledge
across the entire trading system.

## Tools Delivered

### File: `src/tools/knowledge.py` (8 tools)

| # | Tool | Store | Description |
|---|------|-------|-------------|
| 1 | **Trade Memory** | `TradeMemory` | Store/retrieve every trade with full context: entry/exit prices, regime, thesis, snapshots, journal entries. FTS5 search on trade thesis. |
| 2 | **Pattern Library** | `PatternLibrary` | Discover, store, match chart/candlestick patterns. Track success rates, co-occurrence, example trades. Confidence decay over time. |
| 3 | **Lesson Archive** | `LessonArchive` | Extract, store, apply lessons from trade outcomes. Track applications and violations. Regime/symbol applicability. |
| 4 | **Strategy Genomes** | `StrategyGenomes` | Evolve, mutate, select strategy parameters. Track lineage, mutation effectiveness, promotion/demotion gates. Shadow lesson application. |
| 5 | **Regime State** | `RegimeStateStore` + `TemporalRegimeGraph` | Classify market regimes (global + per-asset). Record transitions. Compute transition matrices and steady-state distributions. |
| 6 | **Factor Library** | `FactorLibrary` | Compute quantitative factors from OHLCV data. Track IC (Information Coefficient) history and decay. Deflated Sharpe ratio, FDR correction. |
| 7 | **FTS5 Search** | `MemoryRecall` (async) | Full-text search across all stores using SQLite FTS5. Supports fts, semantic, and hybrid search modes. |
| 8 | **Vector Similarity** | `ChromaVectorStore` | ChromaDB semantic search for patterns, trades, lessons, and market states. Graceful degradation when ChromaDB unavailable. |

### File: `src/tools/knowledge_graph.py` (1 tool)

| # | Tool | Store | Description |
|---|------|-------|-------------|
| 9 | **Knowledge Graph** | `KnowledgeGraph` | Cross-store traversal using recursive CTEs. Pattern→Regime→Strategy→Lesson relationships. Neighborhood queries, path finding, enrichment. |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Agent Layer                        │
│  (execution_tracker, trade_philosopher, etc.)        │
└──────────────┬──────────────────────┬───────────────┘
               │                      │
    ┌──────────▼──────────┐  ┌────────▼────────────┐
    │  KnowledgeTools      │  │ KnowledgeGraphTools  │
    │  (8 unified tools)   │  │ (graph traversal)    │
    └──────────┬──────────┘  └────────┬────────────┘
               │                      │
    ┌──────────▼──────────────────────▼───────────────┐
    │              Knowledge Stores (SQLite)            │
    │  ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
    │  │TradeMemory │ │PatternLib  │ │LessonArchive │ │
    │  └────────────┘ └────────────┘ └──────────────┘ │
    │  ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
    │  │Strategy    │ │RegimeState │ │FactorLibrary │ │
    │  │Genomes     │ │+ Temporal  │ │              │ │
    │  └────────────┘ └────────────┘ └──────────────┘ │
    │  ┌────────────┐ ┌────────────────────────────┐  │
    │  │FTS5 Indexes│ │ ChromaDB (vector store)    │  │
    │  └────────────┘ └────────────────────────────┘  │
    └─────────────────────────────────────────────────┘
```

## Key Design Decisions

1. **Shared SQLite database**: All stores share one `tsar.db` with WAL mode, enabling cross-store JOINs in the knowledge graph.

2. **Graceful degradation**: ChromaDB and Redis are optional. When unavailable, vector search returns empty results and regime state falls back to in-memory dict.

3. **Async FTS5**: The FTS5 search engine uses `aiosqlite` for non-blocking search. Agents must call `await init_fts()` before first use.

4. **Convenience wrappers**: `KnowledgeTools` provides both direct store access (e.g., `tools.trade_memory.insert_trade()`) and shorthand methods (e.g., `tools.record_trade()`).

5. **Graph enrichment**: Knowledge graph nodes can be enriched with full data from source tables, enabling rich context for multi-hop queries.

6. **Factor IC decay tracking**: Factor library tracks Information Coefficient over time, alerting when factors lose predictive power.

## Tool Count Verification

| Category | Count | Status |
|----------|-------|--------|
| Knowledge store tools (1-6) | 6 | ✅ |
| Search tools (7-8) | 2 | ✅ |
| Graph tool (9) | 1 | ✅ |
| **Total** | **9** | **✅** |

## Integration Points

- **Registry**: Both tools registered in `src/tools/__init__.py` as `knowledge` and `knowledge_graph`
- **Types**: Uses `TradeRecord`, `TradeSnapshot`, `TradeJournalEntry` from `src.knowledge.trade_memory`
- **Factor types**: Uses `FactorMeta`, `ICRecord` from `src.strategy.factor_library`
- **Graph types**: Uses `GraphNode`, `GraphEdge`, `GraphPath` from `src.knowledge.knowledge_graph`

## File Manifest

| File | Size | Lines | Purpose |
|------|------|-------|---------|
| `src/tools/knowledge.py` | ~25KB | ~530 | 8 knowledge tools unified interface |
| `src/tools/knowledge_graph.py` | ~17KB | ~340 | Knowledge graph traversal tools |
| `src/tools/__init__.py` | updated | — | Registry updated with both tools |

---

**Council verdict:** All 9 knowledge tools implemented and registered. The knowledge layer is complete.
