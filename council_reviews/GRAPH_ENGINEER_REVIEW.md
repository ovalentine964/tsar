# GRAPH ENGINEER REVIEW — TSAR Knowledge Architecture

**Reviewer:** Graph Engineer (Council Member)  
**Date:** 2026-07-30  
**Scope:** Knowledge graph patterns, data relationships, information architecture  
**Codebase:** `/home/work/.openclaw/workspace/.openclaw/tmp/tsar/`

---

## Executive Summary

TSAR has a **surprisingly well-designed implicit knowledge graph** embedded within its five SQLite knowledge stores. The data model captures the essential entities (trades, strategies, patterns, lessons, regimes) and their relationships with reasonable fidelity. However, the system lacks **explicit graph traversal**, **cross-store provenance tracking**, and **temporal relationship modeling** — capabilities that become critical as the system scales and needs to perform multi-hop reasoning (e.g., "find all trades in regime X with strategy Y that resulted in lesson Z").

The current architecture is **adequate for Day 1 operations** but will become a bottleneck by Month 2-3 when pattern discovery, cross-asset correlation, and strategy evolution require graph-native queries.

---

## 1. Graph Architecture Score

### **7.0 / 10** — Strong implicit graph, weak explicit graph

**Justification:**
- **+2** for a well-normalized relational schema that naturally forms a graph (trades→strategies, patterns→observations, lessons→trades, strategies→mutations)
- **+1.5** for FTS5 full-text search across all stores with BM25 ranking
- **+1** for the pattern_relationships table (co_occurs, precedes, negates, enhances, requires) — this IS a graph edge table
- **+1** for strategy lineage via recursive CTE (get_lineage) — proper DAG traversal
- **+1** for ChromaDB vector store integration for semantic similarity
- **+0.5** for statistical validation with confidence decay
- **-1** for JSON-in-column anti-pattern (pattern_matches, lessons stored as JSON strings in trade_records)
- **-1** for no cross-store graph traversal API
- **-0.5** for no temporal graph modeling (regime transitions are a flat list)
- **-0.5** for no provenance tracking across knowledge stores

---

## 2. Top 5 Data Model Strengths

### 2.1 Natural Graph Topology in Relational Schema

The five knowledge stores form a clean entity-relationship graph:

```
trade_records ──FK──► strategy_genomes ──parent_id──► strategy_genomes (DAG)
     │                      │
     │                      ▼
     │               strategy_mutations (mutation lineage)
     │
     ├──regime_at_entry──► regime_state (Redis)
     │
     ├──FK──► pattern_observations ──FK──► patterns ──► pattern_relationships
     │
     └──FK──► lessons ──► lesson_applications
                    └──► lesson_violations
```

This is a textbook knowledge graph for trading systems. The relationships are well-typed with foreign keys, and the dataclasses are rich with domain-specific attributes.

### 2.2 Pattern Relationships as First-Class Graph Edges

`pattern_relationships` is the single best graph-engineered component in TSAR:

```sql
relationship CHECK(relationship IN ('co_occurs','precedes','negates','enhances','requires','contradicts'))
strength REAL  -- edge weight
sample_size INTEGER  -- statistical backing
```

This enables queries like "what patterns co-occur with X?" and "what patterns negate Y?" — exactly the kind of graph reasoning needed for signal generation. The `get_co_occurring_patterns()` method with strength filtering is proper graph traversal.

### 2.3 Strategy Lineage as DAG with Recursive CTE

`get_lineage()` uses SQLite's recursive CTE to traverse the strategy genome DAG:

```sql
WITH RECURSIVE lineage AS (
    SELECT strategy_id, parent_id, name, version, status, 0 AS depth
    FROM strategy_genomes WHERE strategy_id = ?
    UNION ALL
    SELECT sg.strategy_id, sg.parent_id, sg.name, sg.version, sg.status, l.depth + 1
    FROM strategy_genomes sg
    JOIN lineage l ON sg.parent_id = l.strategy_id
)
```

This is graph-native SQL. Combined with `get_mutation_effectiveness()` which JOINs parent and child genomes to measure mutation success, the strategy evolution subsystem is the most graph-mature component.

### 2.4 Comprehensive Entity Metadata for Graph Nodes

Each knowledge store entity carries rich metadata that would become graph node properties:

- **TradeRecord:** 40+ fields including regime_at_entry, pattern_matches, signal_score, confidence
- **Pattern:** conditions (JSON), success_rate, expectancy, decay_rate, chart_embedding_id
- **StrategyGenome:** genome_yaml, regime_performance, gates_passed (bitmask)
- **Lesson:** applicable_regimes, applicable_strategies, times_applied, times_violated, violation_impact

This metadata richness means a migration to a property graph model (Neo4j, Apache TinkerPop) would be straightforward — every field maps naturally to a node/edge property.

### 2.5 FTS5 + Vector Search Dual-Track Recall

The architecture plans both:
- **FTS5** (implemented): BM25 full-text search across trade theses, pattern descriptions, lesson content
- **ChromaDB** (designed): Vector similarity for chart patterns, market contexts, trade theses

This dual-track approach (keyword + semantic) is exactly what modern knowledge systems need. The `MemoryRecall` class provides a unified search API across all stores.

---

## 3. Top 5 Data Model Gaps

### 3.1 JSON-in-Column Anti-Pattern (Critical)

The most significant structural weakness. Multiple columns store structured data as JSON strings:

| Table | Column | Problem |
|-------|--------|---------|
| `trade_records` | `pattern_matches` | JSON array of pattern IDs — can't JOIN |
| `trade_records` | `lessons` | JSON array of lesson IDs — can't JOIN |
| `trade_records` | `key_levels` | JSON of support/resistance — can't query |
| `trade_records` | `sector_momentum` | JSON of sector z-scores — can't aggregate |
| `strategy_genomes` | `regime_performance` | JSON of per-regime stats — can't JOIN |
| `strategy_genomes` | `symbols` | JSON array — can't index |
| `patterns` | `conditions` | JSON of entry conditions — can't query structurally |
| `patterns` | `example_trade_ids` | JSON array — can't JOIN |

**Impact:** The query "find all trades in regime X with strategy Y that resulted in lesson Z" requires scanning all trade_records, JSON-parsing `lessons` column, and filtering — O(n) instead of O(log n) with a proper junction table.

**Research validation:** Entity-relationship modeling literature (Chen 1976, extended) is clear: multi-valued attributes should be normalized into separate relations. The property graph model (Apache TinkerPop) stores properties as primitive types, not nested structures.

### 3.2 No Cross-Store Graph Traversal API

Each knowledge store has its own CRUD class (TradeMemory, PatternLibrary, StrategyGenomes, LessonArchive, RegimeStateStore) but there is no unified graph traversal layer. You cannot:

- Start from a trade, traverse to its patterns, then find co-occurring patterns, then find strategies that use those patterns
- Start from a lesson, find all trades that violated it, find the regime at the time, find what patterns were active
- Start from a strategy mutation, trace back to the trades that motivated it, forward to the patterns it discovered

The `MemoryRecall` class provides text search but not structural graph queries.

### 3.3 No Temporal Graph Modeling

Regime transitions are stored as a flat Redis list (`_TRANSITION_MAX = 1000`) with no temporal graph structure:

```python
def record_transition(self, transition: RegimeTransition) -> None:
    payload = json.dumps(transition.to_dict())
    self._backend.lpush_trim(self._key("transitions"), payload, self._TRANSITION_MAX)
```

There is no:
- Transition probability matrix (P(trending→ranging) = 0.3)
- Transition timing distribution (average time in regime before transition)
- Regime sequence patterns (trending→high_vol→ranging is common)
- Temporal correlation between regime transitions and pattern activation

**Research validation:** Temporal knowledge graphs (TKGs) are the state-of-the-art for financial data modeling. Research by Xu et al. (2020) on "Temporal Knowledge Graphs for Financial Markets" shows that modeling regime transitions as temporal edges with timestamps and probabilities significantly improves prediction accuracy. The recent paper "Regime-Dependent Graph Neural Networks" (MDPI, 2026) demonstrates that GNNs operating on regime-aware graphs outperform static models by 15-25% in volatility prediction.

### 3.4 No Provenance Tracking Across Stores

When a pattern is discovered, there is no edge linking it to the specific trades, regime states, and market conditions that produced it. When a lesson is created, there is no graph path from the original trade through the pattern matches, regime context, and strategy decisions that led to the lesson.

The `discovered_by` field on patterns is a string (agent name), not a structured provenance chain. The GRAPH_ENGINEERING_ANALYSIS.md already identifies this gap:

> "Every important output can be traced to an objective, a plan, an artifact, a source, a graph path, an evaluator decision, and a bounded execution record."

This provenance chain does not exist in the current schema.

### 3.5 ChromaDB Integration Is Incomplete

While the architecture document specifies ChromaDB collections (chart_patterns, market_contexts, trade_theses), the actual implementation in the knowledge store modules shows:

- `chart_embedding_id` on Pattern — field exists but no code to populate it
- `embedding_id` on PatternObservation — field exists but no embedding pipeline
- No ChromaDB client initialization in any knowledge store module
- No vector similarity queries in PatternLibrary or TradeMemory

The FTS5 search is implemented and working. The vector search is designed but not built.

---

## 4. Should TSAR Adopt a Graph Database?

### **Maybe — Not Yet, But Prepare for It**

**Current state (Day 1-30):** SQLite is the right choice. The data volume is low (<10K trades), queries are simple (filtered lists, FTS5 search), and the team needs to ship, not optimize.

**Month 2-3 transition point:** When the system needs to answer questions like:
- "Find all trades in regime X with strategy Y that resulted in lesson Z" (3-hop query)
- "What patterns co-occur with pattern A in regime B, and which strategies use them?" (4-hop query)
- "Trace the provenance of this lesson back through patterns, trades, and market conditions" (variable-depth query)

At this point, consider:

**Option A: SQLite + Application-Layer Graph (Recommended for Month 2)**
- Build a `KnowledgeGraph` Python class that wraps the existing SQLite stores
- Implement BFS/DFS traversal over FK relationships
- Cache frequently-accessed subgraphs in Redis
- Use recursive CTEs for known-depth traversals

**Option B: Neo4j or Memgraph (Consider for Month 3+)**
- Migrate entities and relationships to a property graph
- Use Cypher for multi-hop queries
- Keep SQLite as the source of truth; sync to graph DB
- Use graph algorithms (PageRank, community detection) for pattern discovery

**Option C: SQLite with Graph Extensions (Lightweight)**
- Use the `sqlite3` recursive CTE capability more aggressively
- Pre-compute and materialize common graph paths
- Build a graph query DSL on top of SQL

**Research validation:** The Reddit thread on graph databases notes that "most trading systems don't need a graph DB until they have millions of edges." PostgreSQL 19's SQL/PGQ standard brings property graph queries to relational databases. SQLite's recursive CTE is sufficient for graphs with <100K edges.

---

## 5. Research-Backed Recommendations

### 5.1 Normalize JSON Columns into Junction Tables (Priority: HIGH)

Replace JSON-in-column with proper many-to-many tables:

```sql
-- Trade ↔ Pattern junction
CREATE TABLE trade_pattern_links (
    trade_id TEXT REFERENCES trade_records(trade_id),
    pattern_id TEXT REFERENCES patterns(pattern_id),
    match_strength REAL,
    matched_at TEXT,
    PRIMARY KEY (trade_id, pattern_id)
);

-- Trade ↔ Lesson junction  
CREATE TABLE trade_lesson_links (
    trade_id TEXT REFERENCES trade_records(trade_id),
    lesson_id TEXT REFERENCES lessons(lesson_id),
    relevance REAL,
    PRIMARY KEY (trade_id, lesson_id)
);

-- Strategy ↔ Regime performance
CREATE TABLE strategy_regime_stats (
    strategy_id TEXT REFERENCES strategy_genomes(strategy_id),
    regime TEXT,
    trades INTEGER,
    win_rate REAL,
    pnl REAL,
    sharpe REAL,
    PRIMARY KEY (strategy_id, regime)
);
```

This enables O(log n) indexed JOINs instead of O(n) JSON parsing.

### 5.2 Build a KnowledgeGraph Traversal API (Priority: HIGH)

Create `src/knowledge/graph.py`:

```python
class KnowledgeGraph:
    """Unified graph traversal across all knowledge stores."""
    
    def neighbors(self, entity_type: str, entity_id: str, 
                  edge_type: str = None, depth: int = 1) -> list[Entity]:
        """Get neighboring entities in the knowledge graph."""
    
    def shortest_path(self, start: EntityRef, end: EntityRef, 
                      max_depth: int = 5) -> list[Edge]:
        """Find shortest path between two entities."""
    
    def subgraph(self, center: EntityRef, depth: int = 2, 
                 edge_types: list[str] = None) -> Graph:
        """Extract a subgraph around an entity."""
    
    def query(self, cypher_like: str) -> list[dict]:
        """Execute a graph query (implemented via recursive CTEs)."""
```

### 5.3 Model Regime Transitions as Temporal Graph (Priority: MEDIUM)

Replace the flat Redis list with a SQLite table:

```sql
CREATE TABLE regime_transitions (
    transition_id TEXT PRIMARY KEY,
    from_regime TEXT NOT NULL,
    to_regime TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    probability_shift REAL,
    trigger TEXT,
    asset TEXT DEFAULT 'GLOBAL',
    duration_in_previous_hours REAL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_regime_trans_time ON regime_transitions(timestamp);
CREATE INDEX idx_regime_trans_from ON regime_transitions(from_regime, to_regime);
```

Add transition probability computation:

```python
def get_transition_matrix(self, lookback_days: int = 90) -> dict[str, dict[str, float]]:
    """Compute P(to_regime | from_regime) from historical transitions."""
```

### 5.4 Consider SQLite-Native Property Graph Layer (Priority: MEDIUM)

Recent research (dev.to 2026, Velr 2026) demonstrates that SQLite can serve as a property graph substrate with recursive CTEs for traversal and openCypher-like query translation. Before adopting Neo4j, evaluate:

- **Velr** — embedded property-graph database on SQLite with openCypher queries (Rust, zero-dependency)
- **sqlite-graph** — lightweight graph layer using recursive CTEs
- **Custom implementation** — a `KnowledgeGraph` class that translates graph queries to recursive CTEs

This approach gives TSAR graph query capabilities without operational overhead of a separate database.

### 5.5 Wire ChromaDB for Pattern Similarity (Priority: MEDIUM)

The architecture is designed but not implemented. Build:

```python
class PatternEmbeddingPipeline:
    """Generate and store embeddings for patterns."""
    
    def embed_pattern(self, pattern: Pattern) -> str:
        """Generate embedding from pattern description + conditions."""
    
    def find_similar(self, query: str, n: int = 5) -> list[Pattern]:
        """Semantic similarity search for patterns."""
    
    def find_similar_chart(self, chart_embedding: list[float], n: int = 5) -> list[Pattern]:
        """Visual similarity search for chart patterns."""
```

### 5.6 Add Provenance Edges (Priority: LOW for Day 1, HIGH for Month 2)

Every knowledge store entry should carry provenance:

```sql
CREATE TABLE provenance_edges (
    edge_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,  -- trade, pattern, lesson, strategy
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship TEXT NOT NULL,  -- discovered_from, validated_by, caused_by
    confidence REAL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

---

## 6. Cross-Asset Correlation Analysis

The `MarketCartographer` agent is currently a stub (`async def run_cycle(self) -> None: pass`). This is the component most in need of graph engineering.

**What it should build:**

A correlation graph where:
- **Nodes** = assets (BTC, ETH, DXY, Gold, VIX, S&P500)
- **Edges** = correlation strength (Pearson, Spearman, or DCC-GARCH conditional correlation)
- **Edge properties** = rolling correlation, lead/lag relationship, regime-conditional correlation

**Graph queries this enables:**
- "If BTC is in regime X, what regime is ETH likely in?" (regime propagation)
- "What assets are most correlated with BTC right now?" (portfolio construction)
- "Has the BTC-Gold correlation broken down?" (regime change detection)

**Research validation:** The paper "Forecasting Equity Correlations with Hybrid Transformer Graph Networks" (arXiv, 2026) shows that GNNs operating on cross-asset correlation graphs outperform traditional methods by 18% in correlation prediction. "Dynamic Graph Neural Networks for Enhanced Volatility Prediction" (arXiv, 2024) demonstrates that regime-aware correlation graphs improve volatility forecasting.

---

## 7. Temporal Relationship Analysis

The system has weak temporal modeling:

| Component | Temporal Data | Graph Structure |
|-----------|--------------|-----------------|
| Trade records | `created_at`, `fill_timestamp` | Sequential (ordered by time) |
| Regime transitions | Flat Redis list (1000 max) | No graph structure |
| Pattern observations | `observed_at` | Sequential per pattern |
| Strategy mutations | `created_at` | DAG via parent_id |
| Lessons | `discovered_at`, `last_applied` | No temporal edges |

**What's missing:**
1. **Temporal edges** — "event A happened before event B and may have caused it"
2. **Temporal aggregation** — "what patterns are active in the last 4 hours?"
3. **Causal inference** — "did this regime change cause this pattern to fail?"
4. **Sequence mining** — "what sequence of events typically precedes a winning trade?"

**Research validation:** The paper "Integrating Event Information and Multi-Dimensional Relationships" (Nature, 2025) introduces event-driven temporal pattern extractors for financial knowledge graphs, demonstrating that temporal edges between events (regime changes, pattern activations, trade outcomes) significantly improve prediction accuracy.

---

## 8. Component-by-Component Analysis

### 8.1 pattern_library.py — Score: 8/10

**Strengths:**
- `PatternRelationship` with typed relationships (co_occurs, precedes, negates, enhances, requires)
- `PatternObservation` links patterns to trades with market context
- Statistical validation with sample size, confidence decay
- `get_co_occurring_patterns()` is proper graph traversal

**Gaps:**
- `conditions` stored as JSON string — can't query structurally
- `example_trade_ids` stored as JSON — can't JOIN
- No embedding pipeline for `chart_embedding_id`
- FTS5 search works but no vector similarity

### 8.2 strategy_genomes.py — Score: 7.5/10

**Strengths:**
- Recursive CTE lineage traversal
- Mutation history with parent/child tracking
- Performance snapshots with regime attribution
- Gate evaluation with bitmask

**Gaps:**
- `regime_performance` stored as JSON — can't JOIN or aggregate
- `symbols` stored as JSON — can't index by symbol
- No graph-based fitness function (only scalar metrics)
- `get_lineage()` only traverses parent→child, not child→parent

### 8.3 regime_state.py — Score: 5/10

**Strengths:**
- Clean backend abstraction (Dict → Redis)
- Per-asset regime overrides
- Transition recording
- Indicator storage

**Gaps:**
- Transitions stored as flat list, not graph
- No transition probability matrix
- No temporal graph structure
- No regime-conditional pattern/strategy linking
- `_TRANSITION_MAX = 1000` — history is lost after 1000 transitions
- Regime state is ephemeral (Redis) — no durable graph

### 8.4 trade_memory.py — Score: 7/10

**Strengths:**
- Rich TradeRecord (40+ fields) with market context
- TradeSnapshot for market state at decision time
- TradeJournalEntry for free-form reflection
- FTS5 search on thesis/reflection/notes
- Regime-specific performance queries

**Gaps:**
- `pattern_matches` and `lessons` as JSON arrays — can't JOIN
- No graph traversal from trade to related entities
- No provenance chain (trade → patterns → lessons → mutations)
- Soft delete works but audit trail could be richer

### 8.5 market_cartographer.py — Score: 1/10 (Stub)

**Status:** `run_cycle()` is `pass`. No implementation exists.

**What's needed:**
- Cross-asset correlation graph construction
- Rolling correlation computation
- Lead/lag relationship detection
- Regime-conditional correlation analysis

### 8.6 regime_detector.py — Score: 6/10

**Strengths:**
- Uses ADX, ATR, Bollinger Bands, EMA slope
- Classifies into 5 regimes with confidence
- Stores per-symbol regime state

**Gaps:**
- No regime transition detection (just classification)
- No transition probability computation
- No regime sequence pattern mining
- Single-symbol analysis, no cross-asset regime propagation

### 8.7 trade_philosopher.py — Score: 6/10

**Strengths:**
- LLM-based post-trade reflection
- Lesson creation with severity classification
- Integration with lesson archive

**Gaps:**
- No pattern-lesson linking (lessons don't reference patterns)
- No regime-conditional lesson applicability
- No graph-based lesson recommendation ("what lessons are relevant given current regime and patterns?")

---

## 9. Verdict

### **CONDITIONAL PASS**

**TSAR's knowledge architecture is well-designed for a Day 1 system.** The five-store model, FTS5 search, recursive CTE lineage traversal, and pattern relationship table demonstrate genuine graph engineering thinking. The data model naturally forms a graph even though it's stored relationally.

**Conditions for full production readiness:**

| # | Condition | Priority | Timeline |
|---|-----------|----------|----------|
| 1 | Normalize JSON columns into junction tables | HIGH | Week 1-2 |
| 2 | Build KnowledgeGraph traversal API | HIGH | Week 2-3 |
| 3 | Model regime transitions as temporal graph | MEDIUM | Week 3-4 |
| 4 | Wire ChromaDB for pattern/lesson similarity | MEDIUM | Week 3-4 |
| 5 | Implement MarketCartographer correlation graph | MEDIUM | Week 4-6 |
| 6 | Add provenance edges across stores | LOW | Month 2 |

**The system does NOT need a graph database today.** SQLite with recursive CTEs and a Python graph traversal layer is sufficient for the first 30-60 days. When multi-hop queries become a performance bottleneck (likely Month 2-3), the normalized junction tables and traversal API will make migration to Neo4j or similar straightforward.

---

## Appendix A: Research References

1. **Financial Knowledge Graph Construction** — "FinKario: Event-Enhanced Automated Construction of Financial Knowledge Graphs" (arXiv 2508.00961, Aug 2025) — demonstrates LLM-based KG construction for financial domains with event-driven entity extraction
2. **Temporal Knowledge Graphs** — "Integrating Event Information and Multi-Dimensional Relationships" (Nature Scientific Reports, Oct 2025) — event-driven temporal pattern extractors for financial KGs; addresses "pattern confusion" in time-series models
3. **GNN for Financial Markets** — "Dynamic Graph Neural Networks for Enhanced Volatility Prediction" (arXiv 2410.16858, Oct 2024) — regime-aware correlation graphs improve volatility forecasting
4. **Cross-Asset Correlation** — "Forecasting Equity Correlations with Hybrid Transformer Graph Networks" (arXiv 2601.04602, Jan 2026) — GNNs on correlation graphs outperform traditional methods by 18%
5. **Regime-Dependent GNNs** — "Regime-Dependent Graph Neural Networks for Enhanced Volatility Prediction" (MDPI Mathematics 14(2):289, 2026) — regime-aware graphs outperform static models by 15-25%
6. **SQLite as Graph Database** — "SQLite as a Graph Database: Recursive CTEs, Semantic Search, and Why We Ditched Neo4j" (dev.to, Mar 2026) — validates SQLite recursive CTEs for graph traversal at moderate scale; cites performance parity with Neo4j for <100K edges
7. **Embedded Property Graph on SQLite** — Velr: embedded property-graph database written in Rust on SQLite with openCypher (LinkedIn, 2026) — demonstrates that SQLite can serve as a property graph substrate with proper query translation
8. **Graph Engineering** — "Graph Engineering: From Karpathy's Loop to Anthropic's Agent Infrastructure" (2026) — the ratchet loop and knowledge graph as shared memory; identifies provenance tracking as critical gap
9. **Systemic Risk via Temporal KG** — "Research on Systemic Risk Measurement Based on Temporal Knowledge Graphs" (ScienceDirect, 2025) — incorporates market data into temporal KG for risk measurement in financial institutions
10. **Financial KG with LLMs** — "Knowledge Graph Construction for Stock Markets with LLM-Based" (arXiv 2601.11528, Nov 2025) — combines KGs with LLMs for investment analysis; validates entity-relationship modeling for trading

## Appendix B: Key Queries the Current Schema Cannot Answer Efficiently

| Query | Hops | Current Approach | Graph Approach |
|-------|------|-----------------|----------------|
| "Find trades in regime X with strategy Y" | 2 | Filtered SQL scan | Graph traversal with index |
| "Find patterns that co-occur with X in regime Y" | 3 | JSON parse + JOIN | 3-hop Cypher |
| "Trace lesson provenance to trades and patterns" | 4 | No path exists | 4-hop traversal |
| "What regime transitions correlate with pattern failures?" | 3 | No temporal edges | Temporal graph query |
| "Find strategies evolved from lessons about regime X" | 4 | No cross-store path | 4-hop with filter |
| "What patterns are active given current regime and recent trades?" | 3 | Manual aggregation | Real-time subgraph |

---

*Review complete. The Graph Engineer recommends CONDITIONAL PASS with priority on junction table normalization and graph traversal API.*
