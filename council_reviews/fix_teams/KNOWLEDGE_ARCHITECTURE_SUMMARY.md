# Knowledge Architecture Team — Implementation Summary

**Date:** 2026-07-30
**Team:** Knowledge Architecture
**Issues Addressed:** M-006, M-015, M-016, M-017, M-018

---

## M-018: ChromaDB Integration ✅

**File created:** `src/knowledge/chromadb_store.py`

- Created `ChromaVectorStore` class with graceful degradation if ChromaDB not installed
- Supports 4 collections: `tsar_patterns`, `tsar_trades`, `tsar_lessons`, `tsar_market_state`
- Pluggable `EmbeddingFunction` abstraction (ships with hash-based stub, replace with real model)
- Operations: `upsert_*`, `search_similar_*`, `batch_upsert`, `delete`, `get_stats`
- `is_chromadb_available()` utility for feature detection
- All writes are no-ops and all reads return empty results when ChromaDB is absent

---

## M-006: FTS5 + ChromaDB Hybrid Search ✅

**File modified:** `src/knowledge/fts_search.py`

- `MemoryRecall` now accepts optional `chromadb_dir` and `embedding_fn` parameters
- Added `semantic_search()` — vector similarity search via ChromaDB, falls back to FTS5
- Added `hybrid_search()` — combines FTS5 BM25 + ChromaDB vector similarity with configurable weights
- Score normalization to [0, 1] for fair merging across engines
- De-duplication by `(store, record_id)` with weighted re-ranking
- Existing FTS5 `search()` method unchanged — full backward compatibility
- ChromaDB auto-initializes if installed; no-op if not

---

## M-015: JSON-in-Column → Junction Tables ✅

**Migration created:** `migrations/002_junction_tables.sql`

Six new junction tables replacing JSON columns:

| Junction Table | Replaces | Source Table |
|---|---|---|
| `trade_lessons` | `trade_records.lessons` (JSON) | trade_memory.py |
| `trade_patterns` | `trade_records.pattern_matches` (JSON) | trade_memory.py |
| `pattern_example_trades` | `patterns.example_trade_ids` (JSON) | pattern_library.py |
| `lesson_regimes` | `lessons.applicable_regimes` (JSON) | lesson_archive.py |
| `lesson_symbols` | `lessons.applicable_symbols` (JSON) | lesson_archive.py |
| `lesson_strategies` | `lessons.applicable_strategies` (JSON) | lesson_archive.py |

All junction tables have:
- Composite primary keys
- Proper foreign keys with `ON DELETE CASCADE`
- Appropriate indexes for reverse lookups

**Code changes:**

- `trade_memory.py`: Added `link_lesson/unlink_lesson/get_trade_lessons/get_lesson_trades` and `link_pattern/unlink_pattern/get_trade_patterns/get_pattern_trades`
- `pattern_library.py`: Added `add_example_trade/remove_example_trade/get_example_trades`
- `lesson_archive.py`: Added `add_applicable_regime/symbol/strategy`, `remove_*`, `get_applicable_*`, `get_lessons_for_regime/symbol/strategy`

Existing JSON columns are preserved for backward compatibility. New code should use junction tables.

---

## M-016: Knowledge Graph Traversal API ✅

**File created:** `src/knowledge/knowledge_graph.py`

- `KnowledgeGraph` class with cross-store graph traversal
- **Direct queries:** `find_trades_by_regime_and_strategy()`, `get_lessons_for_pattern()`, `get_patterns_for_strategy()`, `get_strategies_for_regime()`, `get_regime_pattern_performance()`
- **Recursive CTE traversal:** `traverse()` — walks the graph up to `max_depth` hops with cycle detection
- **Graph edges** defined as CTE covering:
  - trade ↔ strategy (via `strategy_id`)
  - trade ↔ pattern (via `trade_patterns` junction)
  - trade ↔ lesson (via `trade_lessons` junction)
  - trade ↔ regime (via `regime_at_entry`)
  - pattern ↔ pattern (via `pattern_relationships`)
- **Neighborhood queries:** `get_neighbors()` for immediate adjacency
- **Node enrichment:** `enrich_node()` / `enrich_path()` to hydrate nodes with full data
- **Graph stats:** `get_graph_stats()` for node/edge counts
- Result types: `GraphNode`, `GraphEdge`, `GraphPath`

---

## M-017: Temporal Regime Graph ✅

**File modified:** `src/knowledge/regime_state.py`
**Migration created:** `migrations/003_temporal_regime_graph.sql`

- `TemporalRegimeGraph` class modeling "regime A → regime B with probability P in time T"
- Two new tables:
  - `regime_transitions` — raw transition observations
  - `regime_transition_edges` — aggregated Markov transition probabilities
- **Observation recording:** `record_observation()` with auto-computed probability
- **Transition queries:** `get_transitions_from/to()`, `get_transition_probability()`, `get_most_likely_transition()`
- **Path probability:** `compute_path_probability()` — P(r1→r2→r3) = P(r1→r2) × P(r2→r3)
- **Graph snapshot:** `compute_snapshot()` → `RegimeGraphSnapshot` with transition matrix
- **Steady-state:** `RegimeGraphSnapshot.steady_state()` — power iteration for long-run distribution
- **Prediction:** `predict_regime()` — regime probabilities after T hours using matrix exponentiation
- **Duration analysis:** `get_regime_durations()` — avg/min/max time in each regime
- Multi-asset support via `asset` column (default "GLOBAL")

---

## Files Modified/Created Summary

| File | Action | Issue |
|---|---|---|
| `src/knowledge/chromadb_store.py` | **Created** | M-018 |
| `src/knowledge/knowledge_graph.py` | **Created** | M-016 |
| `src/knowledge/fts_search.py` | Modified | M-006 |
| `src/knowledge/trade_memory.py` | Modified | M-015 |
| `src/knowledge/pattern_library.py` | Modified | M-015 |
| `src/knowledge/lesson_archive.py` | Modified | M-015 |
| `src/knowledge/regime_state.py` | Modified | M-017 |
| `src/knowledge/__init__.py` | Modified | All |
| `migrations/002_junction_tables.sql` | **Created** | M-015 |
| `migrations/003_temporal_regime_graph.sql` | **Created** | M-017 |

## Design Principles Followed

1. **ChromaDB is optional** — all operations degrade gracefully via `is_chromadb_available()`
2. **FTS5 unchanged** — existing `search()` method works identically
3. **Junction tables have proper FKs** — all with `ON DELETE CASCADE`
4. **Graph traversal uses recursive CTEs** — efficient for SQLite
5. **Backward compatible** — JSON columns preserved; new junction table methods are additive
6. **All files pass Python syntax validation**
