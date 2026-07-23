# Trading Super Agent — Data Architecture

> **Status:** Architecture Blueprint v1.0  
> **Date:** 2026-07-24  
> **Stack:** Python (orchestration, reads, ML) + Rust (hot-path ingestion, risk math)  
> **Storage:** SQLite (durable state) · Redis (real-time) · ChromaDB (vectors)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Knowledge Store #1: Trade Memory (SQLite)](#2-trade-memory)
3. [Knowledge Store #2: Strategy Genomes (YAML + SQLite)](#3-strategy-genomes)
4. [Knowledge Store #3: Regime State (Redis)](#4-regime-state)
5. [Knowledge Store #4: Pattern Library (SQLite + ChromaDB)](#5-pattern-library)
6. [Knowledge Store #5: Lesson Archive (SQLite + FTS5)](#6-lesson-archive)
7. [Session Memory Architecture](#7-session-memory-architecture)
8. [Trade Journal Format](#8-trade-journal-format)
9. [FTS5 Search Configuration](#9-fts5-search-configuration)
10. [Vector Embedding Pipeline](#10-vector-embedding-pipeline)
11. [Data Compaction Rules](#11-data-compaction-rules)
12. [Redis Key Design](#12-redis-key-design)
13. [Cross-Cutting Concerns](#13-cross-cutting-concerns)
14. [Data Flow Diagrams](#14-data-flow-diagrams)
15. [Implementation Roadmap](#15-implementation-roadmap)

---

## 1. System Overview

### 1.1 Data Tier Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      TRADING SUPER AGENT                        │
│                                                                 │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────────┐ │
│  │ Strategy  │  │ Execution │  │  Risk     │  │  Learning    │ │
│  │ Agent     │  │ Agent     │  │  Governor │  │  Agent       │ │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └──────┬───────┘ │
│        │              │              │               │          │
│  ┌─────▼──────────────▼──────────────▼───────────────▼───────┐  │
│  │                   DATA ACCESS LAYER (Python)              │  │
│  │  Read: all agents  |  Write: owner-per-store             │  │
│  └───────┬──────────────┬──────────────┬──────────────┬──────┘  │
│          │              │              │              │          │
│  ┌───────▼───────┐ ┌────▼────┐ ┌──────▼──────┐ ┌────▼──────┐  │
│  │  SQLite       │ │  Redis  │ │  ChromaDB   │ │  WAL      │  │
│  │  (Durable)    │ │  (RT)   │ │  (Vectors)  │ │  (Audit)  │  │
│  │               │ │         │ │             │ │           │  │
│  │ trade_memory  │ │ regime  │ │ patterns    │ │ audit_log │  │
│  │ strategy_db   │ │ state   │ │ embeddings  │ │ events    │  │
│  │ pattern_lib   │ │ risk    │ │             │ │           │  │
│  │ lesson_archive│ │ pos     │ │             │ │           │  │
│  └───────────────┘ └─────────┘ └─────────────┘ └───────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Language Boundary

| Concern | Language | Rationale |
|---------|----------|-----------|
| Trade ingestion, order matching, tick processing | **Rust** | Sub-ms latency, zero-GC |
| Risk calculations (VaR, position sizing) | **Rust** | Deterministic timing |
| Strategy logic, ML inference, reflection | **Python** | Ecosystem, flexibility |
| Agent orchestration, LLM calls | **Python** | LangChain/LlamaIndex native |
| FTS5 indexing, SQLite writes | **Python** (via `rusqlite` bindings or direct) | Adequate throughput |
| Vector embedding generation | **Python** (sentence-transformers) | ML model hosting |

### 1.3 Concurrency Model

```
Single-writer per SQLite database (WAL mode allows concurrent readers)
Redis: atomic operations, no contention
ChromaDB: single writer thread, async reads
Rust ingestion → writes to WAL file → Python compacts into SQLite
```

---

## 2. Knowledge Store #1: Trade Memory (SQLite)

### 2.1 Purpose

The canonical record of every trade decision, execution, context, outcome, and post-trade reflection. This is the system's episodic memory — what happened, why, and what was learned.

### 2.2 SQL Schema

```sql
-- ============================================================
-- TRADE MEMORY — trades.db
-- SQLite 3.40+ | WAL mode | page_size=4096
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;          -- 64MB cache
PRAGMA mmap_size = 268435456;        -- 256MB mmap
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ─────────────────────────────────────────────────────────────
-- Core trade record
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trades (
    trade_id        TEXT PRIMARY KEY,          -- ULID (time-sortable)
    symbol          TEXT NOT NULL,             -- e.g. "AAPL", "BTC/USD"
    asset_class     TEXT NOT NULL,             -- equity|crypto|fx|commodity|fixed_income
    exchange        TEXT,                      -- NYSE, NASDAQ, Binance, etc.
    
    -- Decision context
    strategy_id     TEXT NOT NULL,             -- FK → strategy_genomes
    signal_type     TEXT NOT NULL,             -- entry|exit|scale_in|scale_out|stop_hit|take_profit
    signal_strength REAL CHECK(signal_strength BETWEEN 0.0 AND 1.0),
    signal_source   TEXT,                      -- which sub-agent/model generated signal
    
    -- Order details
    side            TEXT NOT NULL CHECK(side IN ('buy','sell','short','cover')),
    order_type      TEXT NOT NULL,             -- market|limit|stop|stop_limit|trailing_stop
    quantity         REAL NOT NULL,
    limit_price     REAL,
    stop_price      REAL,
    
    -- Execution
    fill_price      REAL,
    fill_quantity   REAL,
    slippage_bps    REAL,                      -- basis points vs decision price
    commission      REAL DEFAULT 0.0,
    fill_timestamp  TEXT,                      -- ISO8601 UTC
    latency_ms      INTEGER,                  -- decision-to-fill latency
    
    -- Position context at time of trade
    position_size_before REAL DEFAULT 0.0,
    position_size_after  REAL DEFAULT 0.0,
    portfolio_heat_before REAL,               -- % of portfolio at risk
    portfolio_heat_after  REAL,
    
    -- Market context snapshot
    regime_id       TEXT,                      -- FK → regime_states
    vix_level       REAL,
    market_breadth  REAL,                      -- advance/decline ratio
    sector_momentum TEXT,                      -- JSON: {sector: z_score}
    volatility_regime TEXT,                    -- low|normal|high|extreme
    liquidity_score REAL,                      -- 0-1 scale
    
    -- Pre-trade analysis
    expected_return REAL,                      -- model's expected return
    expected_risk   REAL,                      -- model's expected vol
    risk_reward_ratio REAL,
    confidence      REAL CHECK(confidence BETWEEN 0.0 AND 1.0),
    thesis          TEXT,                      -- human-readable trade thesis
    key_levels      TEXT,                      -- JSON: support/resistance levels
    
    -- Post-trade outcome (filled after exit)
    realized_pnl    REAL,
    realized_pnl_pct REAL,
    holding_period_hours REAL,
    max_drawdown_during REAL,                  -- worst unrealized loss %
    max_favorable_excursion REAL,              -- best unrealized gain %
    
    -- Reflection (filled by learning agent)
    outcome_grade   TEXT CHECK(outcome_grade IN ('A','B','C','D','F')),
    execution_grade TEXT CHECK(execution_grade IN ('A','B','C','D','F')),
    reflection      TEXT,                      -- what went right/wrong
    lessons         TEXT,                      -- JSON array of lesson IDs
    pattern_matches TEXT,                      -- JSON array of pattern IDs
    
    -- Metadata
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_deleted      INTEGER DEFAULT 0,        -- soft delete
    
    FOREIGN KEY (strategy_id) REFERENCES strategy_genomes(strategy_id)
);

-- Indices for common query patterns
CREATE INDEX idx_trades_symbol_time ON trades(symbol, created_at DESC);
CREATE INDEX idx_trades_strategy ON trades(strategy_id, created_at DESC);
CREATE INDEX idx_trades_regime ON trades(regime_id);
CREATE INDEX idx_trades_outcome ON trades(outcome_grade, realized_pnl_pct);
CREATE INDEX idx_trades_signal ON trades(signal_type, created_at DESC);
CREATE INDEX idx_trades_active ON trades(is_deleted, position_size_after) 
    WHERE position_size_after != 0;
CREATE INDEX idx_trades_date ON trades(date(created_at));

-- ─────────────────────────────────────────────────────────────
-- Trade snapshots — market state at decision time
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trade_snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    trade_id        TEXT NOT NULL,
    snapshot_type   TEXT NOT NULL,              -- decision|entry|exit|periodic
    
    -- Price data
    bid             REAL,
    ask             REAL,
    mid             REAL,
    last_price      REAL,
    volume_24h      REAL,
    
    -- Technical indicators
    rsi_14          REAL,
    macd_signal     REAL,
    bb_position     REAL,                      -- position within Bollinger Bands
    atr_14          REAL,
    obv_trend       TEXT,                      -- rising|falling|flat
    
    -- Order book (Level 2)
    book_depth_bid  TEXT,                      -- JSON: [{price, size}, ...]
    book_depth_ask  TEXT,
    spread_bps      REAL,
    
    -- Sentiment
    news_sentiment  REAL,                      -- -1 to 1
    social_sentiment REAL,
    fear_greed_index REAL,
    
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id) ON DELETE CASCADE
);

CREATE INDEX idx_snapshots_trade ON trade_snapshots(trade_id, snapshot_type);

-- ─────────────────────────────────────────────────────────────
-- Trade journal entries — free-form reflection
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trade_journal (
    journal_id      TEXT PRIMARY KEY,
    trade_id        TEXT NOT NULL,
    entry_type      TEXT NOT NULL,              -- pre_thesis|post_mortem|mid_trade|weekly_review
    content         TEXT NOT NULL,              -- markdown content
    mood            TEXT,                       -- confident|uncertain|fearful|greedy|neutral
    cognitive_biases TEXT,                      -- JSON array of detected biases
    
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id) ON DELETE CASCADE
);

CREATE INDEX idx_journal_trade ON trade_journal(trade_id);

-- ─────────────────────────────────────────────────────────────
-- Audit trigger for change tracking
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trades_audit_log (
    audit_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT NOT NULL,
    field_name      TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    changed_by      TEXT,                       -- agent name or 'system'
    changed_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_audit_trade ON trades_audit_log(trade_id, changed_at);

CREATE TRIGGER trg_trades_update_audit
AFTER UPDATE ON trades
WHEN OLD.realized_pnl != NEW.realized_pnl
   OR OLD.outcome_grade != NEW.outcome_grade
   OR OLD.reflection != NEW.reflection
   OR OLD.execution_grade != NEW.execution_grade
BEGIN
    INSERT INTO trades_audit_log (trade_id, field_name, old_value, new_value, changed_by)
    SELECT NEW.trade_id, 'realized_pnl', CAST(OLD.realized_pnl AS TEXT), CAST(NEW.realized_pnl AS TEXT), 'system'
    WHERE OLD.realized_pnl != NEW.realized_pnl;
    
    INSERT INTO trades_audit_log (trade_id, field_name, old_value, new_value, changed_by)
    SELECT NEW.trade_id, 'outcome_grade', OLD.outcome_grade, NEW.outcome_grade, 'system'
    WHERE OLD.outcome_grade != NEW.outcome_grade;
    
    INSERT INTO trades_audit_log (trade_id, field_name, old_value, new_value, changed_by)
    SELECT NEW.trade_id, 'reflection', OLD.reflection, NEW.reflection, 'system'
    WHERE OLD.reflection IS NOT NEW.reflection;
END;
```

### 2.3 Data Flow

```
                    WRITE PATH (Rust → Python)
                    ───────────────────────────
Market Data Feed ──► Rust Ingestion Engine
                         │
                         ├─► Parse tick/order data
                         ├─► Match fills against orders
                         ├─► Compute slippage, latency
                         │
                         ▼
                    WAL Buffer (Rust)
                    trades.wal (append-only binary)
                         │
                         ▼ (every 100ms or 1000 events)
                    Python Compaction Worker
                         │
                         ├─► Read WAL entries
                         ├─► Enrich with regime state (Redis)
                         ├─► Write to trades.db
                         └─► Trigger reflection agent (async)


                    READ PATH (Python)
                    ───────────────────
Strategy Agent ─────► query recent trades for symbol
Learning Agent ─────► scan all trades for pattern extraction
Risk Governor ──────► current open positions
Journal Agent ──────► generate daily/weekly summaries
Reflection Agent ───► grade outcomes, write reflections
```

### 2.4 Retention Policy

| Data | Retention | Action |
|------|-----------|--------|
| Full trade records | 7 years (regulatory) | Never delete, archive to cold storage after 2y |
| Trade snapshots | 90 days full, then compressed | Aggregate to OHLCV after 90d |
| Journal entries | 3 years | Archive after 1y |
| Audit log | 7 years | Compress after 1y |
| Soft-deleted trades | 30 days | Hard delete after 30d |

### 2.5 Query Patterns

```python
# Pattern 1: Recent trades for a symbol (hot, ~100/day)
SELECT * FROM trades WHERE symbol = ? AND is_deleted = 0 
ORDER BY created_at DESC LIMIT 50;

# Pattern 2: Open positions (hot, every risk check ~1/sec)
SELECT * FROM trades WHERE position_size_after != 0 AND is_deleted = 0;

# Pattern 3: Strategy performance (warm, hourly)
SELECT strategy_id, 
       COUNT(*) as trade_count,
       AVG(realized_pnl_pct) as avg_return,
       SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
       AVG(slippage_bps) as avg_slippage
FROM trades 
WHERE created_at > ? AND is_deleted = 0
GROUP BY strategy_id;

# Pattern 4: Historical context for reflection (cold, post-trade)
SELECT t.*, tj.content, tj.cognitive_biases
FROM trades t
LEFT JOIN trade_journal tj ON t.trade_id = tj.trade_id
WHERE t.symbol = ? AND t.outcome_grade IN ('D', 'F')
ORDER BY t.created_at DESC LIMIT 20;

# Pattern 5: Regime-specific performance (warm, weekly)
SELECT regime_id, volatility_regime,
       COUNT(*), AVG(realized_pnl_pct), AVG(sharpe_contribution)
FROM trades WHERE created_at > ? GROUP BY regime_id, volatility_regime;
```

### 2.6 Performance Requirements

| Metric | Target | Notes |
|--------|--------|-------|
| Write latency (single trade) | < 5ms (Rust WAL), < 20ms (Python SQLite) | WAL mode, batch writes |
| Read latency (point query) | < 1ms | Indexed, mmap'd |
| Read latency (range scan) | < 10ms for 1000 rows | Cache warm |
| Throughput (writes) | 10,000 trades/sec (WAL), 2,000/sec (SQLite) | Rust WAL is the bottleneck limiter |
| Throughput (reads) | Unlimited concurrent (WAL mode) | Multiple readers, single writer |
| Database size | ~500MB/year at 1000 trades/day | With vacuum after compaction |

---

## 3. Knowledge Store #2: Strategy Genomes (YAML + SQLite)

### 3.1 Purpose

Strategies are living organisms. Each has a "genome" — a set of parameters, rules, and conditions that define its behavior. Genomes evolve through mutation (parameter adjustment) and selection (performance-based survival). YAML files are the human-readable source of truth; SQLite tracks performance and lineage.

### 3.2 YAML Strategy Genome Format

```yaml
# strategy_genomes/aapl_mean_reversion_v3.yaml
# Strategy Genome — versioned, immutable once created

genome:
  id: "strat_aapl_mr_v3_20260724"
  name: "AAPL Mean Reversion v3"
  parent_id: "strat_aapl_mr_v2_20260701"      # lineage tracking
  version: 3
  created_at: "2026-07-24T00:30:00Z"
  created_by: "learning_agent_mutation"
  
  # What markets this strategy trades
  universe:
    symbols: ["AAPL"]
    asset_class: "equity"
    exchanges: ["NYSE", "NASDAQ"]
    
  # Entry/exit conditions (the DNA)
  signals:
    entry:
      - condition: "z_score < -2.0"
        timeframe: "15m"
        indicator: "bollinger_band_position"
      - condition: "volume > 1.5x_20d_avg"
        timeframe: "15m"
      - condition: "rsi_14 < 30"
        timeframe: "15m"
      - condition: "regime_prob_trending < 0.3"
        source: "regime_state"
        
    exit:
      - condition: "z_score > 0.5"
        action: "close_full"
      - condition: "holding_period > 48h"
        action: "close_full"
      - condition: "unrealized_pnl < -2%"
        action: "stop_loss"
      - condition: "regime_prob_trending > 0.7"
        action: "close_full"
        reason: "regime_shift"
        
  # Position sizing rules
  sizing:
    method: "kelly_fractional"
    kelly_fraction: 0.25                    # quarter Kelly
    max_position_pct: 5.0                   # max 5% of portfolio
    min_position_usd: 1000
    scale_in_steps: 2
    scale_in_threshold_pct: 1.0             # add if moves 1% against
    
  # Risk constraints
  risk:
    max_loss_per_trade_pct: 2.0
    max_daily_loss_pct: 5.0
    max_correlated_exposure: 3              # max 3 correlated positions
    max_drawdown_pause_pct: 10.0            # pause strategy at 10% DD
    
  # Required market conditions
  conditions:
    min_volume_24h: 1000000
    max_spread_bps: 10
    required_regime: ["mean_reverting", "low_volatility"]
    blacklisted_events: ["earnings", "fomc", "opex"]
    
  # Performance gates — strategy is disabled if it fails these
  gates:
    min_trades: 30                          # need 30 trades to evaluate
    min_win_rate: 0.45
    max_consecutive_losses: 7
    min_profit_factor: 1.2
    evaluation_period_days: 90
    
  # Mutation parameters — what the learning agent can change
  mutable_params:
    - path: "signals.entry[0].condition"
      type: "float_range"
      min: -3.0
      max: -1.0
      step: 0.1
    - path: "sizing.kelly_fraction"
      type: "float_range"
      min: 0.1
      max: 0.5
      step: 0.05
    - path: "signals.exit[1].condition"
      type: "duration"
      min: "12h"
      max: "168h"
```

### 3.3 SQL Schema

```sql
-- ============================================================
-- STRATEGY GENOMES — strategies.db
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE strategy_genomes (
    strategy_id     TEXT PRIMARY KEY,          -- matches YAML genome.id
    name            TEXT NOT NULL,
    parent_id       TEXT,                      -- parent genome for lineage
    version         INTEGER NOT NULL DEFAULT 1,
    
    -- Genome content
    genome_yaml     TEXT NOT NULL,             -- full YAML genome (immutable once created)
    genome_hash     TEXT NOT NULL,             -- SHA-256 of genome_yaml for integrity
    
    -- Classification
    asset_class     TEXT NOT NULL,
    symbols         TEXT NOT NULL,             -- JSON array
    strategy_type   TEXT,                      -- mean_reversion|momentum|breakout|pairs|stat_arb
    
    -- Lifecycle
    status          TEXT NOT NULL DEFAULT 'candidate'
                    CHECK(status IN ('candidate','paper','live','paused','retired','dead')),
    activated_at    TEXT,
    retired_at      TEXT,
    retirement_reason TEXT,
    
    -- Performance gates tracking
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    total_pnl       REAL DEFAULT 0.0,
    max_drawdown    REAL DEFAULT 0.0,
    profit_factor   REAL DEFAULT 0.0,
    sharpe_ratio    REAL DEFAULT 0.0,
    win_rate        REAL DEFAULT 0.0,
    avg_holding_hours REAL DEFAULT 0.0,
    consecutive_losses INTEGER DEFAULT 0,
    max_consecutive_losses INTEGER DEFAULT 0,
    
    -- Gate status
    gates_passed    INTEGER DEFAULT 0,        -- bitmask of which gates are passing
    gates_evaluated_at TEXT,
    
    -- Metadata
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (parent_id) REFERENCES strategy_genomes(strategy_id)
);

CREATE INDEX idx_strat_status ON strategy_genomes(status);
CREATE INDEX idx_strat_parent ON strategy_genomes(parent_id);
CREATE INDEX idx_strat_type ON strategy_genomes(strategy_type, status);

-- ─────────────────────────────────────────────────────────────
-- Performance snapshots — periodic performance recording
-- ─────────────────────────────────────────────────────────────
CREATE TABLE strategy_performance (
    snapshot_id     TEXT PRIMARY KEY,
    strategy_id     TEXT NOT NULL,
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    
    -- Returns
    total_return    REAL,
    annualized_return REAL,
    excess_return   REAL,                     -- vs benchmark
    
    -- Risk
    volatility      REAL,
    max_drawdown    REAL,
    var_95          REAL,                     -- Value at Risk 95%
    cvar_95         REAL,                     -- Conditional VaR
    sortino_ratio   REAL,
    calmar_ratio    REAL,
    
    -- Execution quality
    avg_slippage_bps REAL,
    avg_latency_ms  REAL,
    fill_rate       REAL,                     -- % of signals that filled
    
    -- Attribution
    regime_performance TEXT,                  -- JSON: {regime: return}
    signal_accuracy TEXT,                     -- JSON: {signal_type: accuracy}
    
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (strategy_id) REFERENCES strategy_genomes(strategy_id)
);

CREATE INDEX idx_perf_strategy ON strategy_performance(strategy_id, period_end DESC);

-- ─────────────────────────────────────────────────────────────
-- Mutation history — track evolution
-- ─────────────────────────────────────────────────────────────
CREATE TABLE strategy_mutations (
    mutation_id     TEXT PRIMARY KEY,
    parent_id       TEXT NOT NULL,             -- parent strategy
    child_id        TEXT NOT NULL,             -- resulting strategy
    mutation_type   TEXT NOT NULL,             -- param_tweak|rule_add|rule_remove|threshold_shift
    mutation_detail TEXT NOT NULL,             -- JSON: what changed
    mutation_reason TEXT,                      -- why this mutation was attempted
    parent_fitness  REAL,                      -- parent's fitness score at mutation time
    
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (parent_id) REFERENCES strategy_genomes(strategy_id),
    FOREIGN KEY (child_id) REFERENCES strategy_genomes(strategy_id)
);

CREATE INDEX idx_mutation_parent ON strategy_mutations(parent_id);
CREATE INDEX idx_mutation_child ON strategy_mutations(child_id);
```

### 3.4 Data Flow

```
Strategy Lifecycle:
━━━━━━━━━━━━━━━━━━

[YAML Created] ──► [Validated] ──► [Candidate] ──► [Paper Trading]
       │                                    │              │
       │              Learning Agent         │     30 trades min
       │              mutates genome         │              │
       │                                    │         [Gates Check]
       │                                    │         ┌────┴────┐
       │                                    │      Pass│         │Fail
       │                                    │         ▼         ▼
       │                              [Retired] ◄── [Live]   [Dead]
       │                                    ▲
       │                                    │
       └──── New mutation ──────────────────┘
             (from retired/dead)

Performance Update Flow:
━━━━━━━━━━━━━━━━━━━━━━━
trades.db (new fill) ──► Rust aggregator ──► strategies.db
                             │                (update stats)
                             ▼
                    performance snapshot
                    (hourly/daily)
```

### 3.5 Retention Policy

| Data | Retention | Action |
|------|-----------|--------|
| Active genomes (YAML) | Permanent | Version-controlled in git |
| Retired genomes | 2 years | Archive YAML to cold storage |
| Performance snapshots | 5 years | Compress after 1y |
| Mutation history | Permanent | Critical for understanding evolution |
| Dead strategies | 1 year | Archive, keep for anti-pattern learning |

### 3.6 Query Patterns

```python
# Get all live strategies
SELECT * FROM strategy_genomes WHERE status = 'live';

# Performance comparison across strategies
SELECT s.name, s.sharpe_ratio, s.win_rate, s.profit_factor, s.total_pnl
FROM strategy_genomes s
WHERE s.status IN ('live', 'paper')
ORDER BY s.sharpe_ratio DESC;

# Evolution tree for a strategy
WITH RECURSIVE lineage AS (
    SELECT strategy_id, parent_id, name, version, 0 as depth
    FROM strategy_genomes WHERE strategy_id = ?
    UNION ALL
    SELECT sg.strategy_id, sg.parent_id, sg.name, sg.version, l.depth + 1
    FROM strategy_genomes sg
    JOIN lineage l ON sg.parent_id = l.strategy_id
)
SELECT * FROM lineage ORDER BY depth;

# Mutation effectiveness
SELECT m.mutation_type, 
       AVG(child.sharpe_ratio - parent.sharpe_ratio) as avg_sharpe_improvement,
       COUNT(*) as count
FROM strategy_mutations m
JOIN strategy_genomes parent ON m.parent_id = parent.strategy_id
JOIN strategy_genomes child ON m.child_id = child.strategy_id
GROUP BY m.mutation_type;
```

---

## 4. Knowledge Store #3: Regime State (Redis)

### 4.1 Purpose

Real-time market regime probabilities and state. Updated every tick or on regime change. This is the system's "mood ring" — it tells all agents what kind of market we're in right now.

### 4.2 Redis Key Design

```
# ─────────────────────────────────────────────────────────────
# REGIME STATE KEYS
# Prefix: tsar: (Trading Super Agent Regime)
# ─────────────────────────────────────────────────────────────

# Current regime probabilities (HMM output)
tsar:regime:current                     # Hash
    trending_bull      "0.15"           # probability
    trending_bear      "0.05"
    mean_reverting     "0.60"
    high_volatility    "0.12"
    low_volatility     "0.08"
    regime_change      "0.00"           # transition state
    dominant_regime    "mean_reverting"  # highest probability
    confidence         "0.85"           # how certain is the classification
    last_updated       "2026-07-24T00:45:00.000Z"
    model_version      "hmm_v2.1"
    lookback_hours     "72"

# Per-asset regime overrides
tsar:regime:asset:{symbol}              # Hash
    regime_probs       '{"trending": 0.2, "mean_reverting": 0.7, ...}'
    correlation_to_market "0.85"
    idiosyncratic_regime "breakout"
    last_updated       "..."

# Regime history (last 1000 transitions)
tsar:regime:transitions                 # List (LPUSH, LTRIM 0 999)
    # Each entry: JSON
    {
        "timestamp": "2026-07-24T00:30:00Z",
        "from_regime": "mean_reverting",
        "to_regime": "trending_bull",
        "probability_shift": 0.45,
        "trigger": "breakout_above_resistance"
    }

# Regime indicators (raw signals feeding the HMM)
tsar:regime:indicators                  # Hash
    vix                 "18.5"
    vix_change_1d       "-1.2"
    market_breadth      "1.8"            # advance/decline
    sector_dispersion   "0.15"
    correlation_matrix  "{...}"          # JSON of cross-asset correlations
    volume_profile      "above_average"
    term_structure      "contango"       # futures term structure
    credit_spread       "125"            # bps
    dollar_index        "104.2"
    realized_vol_20d    "14.2"
    implied_vol_skew    "0.85"


# ─────────────────────────────────────────────────────────────
# POSITION STATE KEYS
# ─────────────────────────────────────────────────────────────

# Current positions (flat hash for fast reads)
tsar:positions:current                  # Hash
    AAPL               '{"qty": 100, "side": "long", "avg_cost": 185.50, "unrealized_pnl": 250.00, "strategy_id": "..."}'
    BTC                '{"qty": 0.5, "side": "long", "avg_cost": 42000, "unrealized_pnl": 1500.00, "strategy_id": "..."}'
    # ... per symbol

# Position risk metrics
tsar:positions:risk                     # Hash
    total_exposure      "125000.00"      # total USD exposure
    net_exposure        "75000.00"       # net long/short
    gross_exposure      "200000.00"      # absolute sum
    portfolio_heat      "0.035"          # 3.5% at risk
    var_95_1d           "4500.00"        # 1-day 95% VaR in USD
    max_drawdown        "0.08"           # current drawdown from peak
    concentration_risk  '{"AAPL": 0.25, "BTC": 0.15}'  # % of portfolio per position
    correlated_exposure "3"              # number of correlated positions
    margin_used_pct     "0.45"           # % of available margin

# P&L tracking
tsar:pnl:daily                          # Hash
    realized            "1250.00"
    unrealized          "1750.00"
    total               "3000.00"
    fees                "45.00"
    net                 "2955.00"
    timestamp           "2026-07-24T00:45:00Z"

tsar:pnl:weekly                         # String (JSON, updated on heartbeat)
    '{"start": "2026-07-21", "realized": 5200, "unrealized": 1750, "trades": 45, "win_rate": 0.62}'

tsar:pnl:monthly                        # String (JSON, updated daily)
    '{"start": "2026-07-01", "realized": 18500, "unrealized": 1750, "trades": 180, "sharpe": 1.8}'


# ─────────────────────────────────────────────────────────────
# RISK LIMIT KEYS (Governor uses these)
# ─────────────────────────────────────────────────────────────

tsar:risk:limits                        # Hash
    max_daily_loss      "5000.00"        # hard stop
    max_position_size   "50000.00"       # per position
    max_portfolio_heat  "0.05"           # 5% max
    max_correlation     "0.7"            # max correlation between positions
    max_leverage        "2.0"            # 2x max leverage
    max_open_positions  "10"
    max_order_frequency "100"            # orders per minute
    drawdown_pause      "0.10"           # pause all at 10% DD

tsar:risk:state                         # Hash
    is_paused           "false"
    pause_reason        ""
    pause_timestamp     ""
    daily_loss_remaining "2045.00"
    remaining_capacity   "75000.00"
    last_risk_check      "2026-07-24T00:45:00Z"
    violations           "[]"            # JSON array of current violations
    circuit_breaker      "green"         # green|yellow|red


# ─────────────────────────────────────────────────────────────
# STRATEGY STATE (real-time)
# ─────────────────────────────────────────────────────────────

tsar:strategy:{strategy_id}:state       # Hash
    status              "live"
    active_signals      "2"
    last_trade_at       "2026-07-24T00:30:00Z"
    daily_pnl           "350.00"
    daily_trades        "3"
    current_regime_fit  "0.85"           # how well strategy fits current regime
    cooldown_until      ""               # if strategy hit loss limit

tsar:strategy:leaderboard               # Sorted Set (by sharpe_ratio)
    # Members: strategy_id, Scores: sharpe_ratio (rolling 30d)


# ─────────────────────────────────────────────────────────────
# MARKET DATA CACHE (hot data)
# ─────────────────────────────────────────────────────────────

tsar:market:{symbol}:latest             # Hash
    price               "187.25"
    bid                 "187.24"
    ask                 "187.26"
    volume_24h          "52000000"
    change_1d           "1.25"
    change_1d_pct       "0.67"
    last_update         "2026-07-24T00:45:00.000Z"

tsar:market:{symbol}:ohlcv:{timeframe}  # List (capped)
    # 1m, 5m, 15m, 1h, 4h, 1d
    # Each entry: JSON {"t": unix_ts, "o": ..., "h": ..., "l": ..., "c": ..., "v": ...}
    # LTRIM to keep last 1000 bars

# ─────────────────────────────────────────────────────────────
# AGENT COORDINATION
# ─────────────────────────────────────────────────────────────

tsar:agents:heartbeat                   # Hash
    strategy_agent      "2026-07-24T00:45:00Z"
    execution_agent     "2026-07-24T00:45:00Z"
    risk_governor       "2026-07-24T00:45:00Z"
    learning_agent      "2026-07-24T00:44:30Z"

tsar:signals:pending                    # List (LPUSH/BRPOP for work queue)
    # Each entry: JSON signal to process
    {
        "signal_id": "sig_ulid",
        "strategy_id": "strat_...",
        "symbol": "AAPL",
        "action": "buy",
        "urgency": "normal",
        "created_at": "..."
    }

tsar:signals:processed                  # List (capped at 10000)
    # Processed signals for audit trail
```

### 4.3 Redis Data Structures Summary

| Key Pattern | Type | Access Pattern | TTL |
|-------------|------|---------------|-----|
| `tsar:regime:*` | Hash | Read: all agents (1-60s), Write: regime engine (1-5min) | No TTL (explicit update) |
| `tsar:positions:*` | Hash | Read: risk gov (100ms), Write: execution (on fill) | No TTL |
| `tsar:pnl:*` | Hash/String | Read: all agents (10s), Write: aggregator (on fill) | Daily rollover |
| `tsar:risk:*` | Hash | Read: execution (pre-trade), Write: risk gov (continuous) | No TTL |
| `tsar:market:*` | Hash/List | Read: all agents (1s), Write: market feed (tick) | 24h for OHLCV |
| `tsar:signals:*` | List | Write: strategy agents, Read: execution agent | 7d processed |
| `tsar:agents:*` | Hash | Read: orchestrator (30s), Write: each agent (heartbeat) | 5min expiry per key |

### 4.4 Performance Requirements

| Metric | Target | Notes |
|--------|--------|-------|
| Read latency | < 0.1ms | Single key, local Redis |
| Write latency | < 0.5ms | Single key |
| Throughput | 500K ops/sec | Redis single instance |
| Memory usage | < 512MB total | All regime + position state |
| Regime update frequency | Every 5 min or on regime change | HMM recalculation |
| Position update frequency | On every fill | Rust writes directly |

---

## 5. Knowledge Store #4: Pattern Library (SQLite + ChromaDB)

### 5.1 Purpose

Discovered market patterns extracted from trade history. Patterns are the system's "intuition" — recurring setups, failure modes, and market behaviors that have been observed and validated. ChromaDB enables semantic search ("find patterns similar to current market conditions").

### 5.2 SQL Schema

```sql
-- ============================================================
-- PATTERN LIBRARY — patterns.db
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE patterns (
    pattern_id      TEXT PRIMARY KEY,          -- ULID
    pattern_name    TEXT NOT NULL,             -- human-readable name
    pattern_type    TEXT NOT NULL
                    CHECK(pattern_type IN (
                        'setup', 'failure_mode', 'regime_behavior',
                        'correlation', 'anomaly', 'seasonal',
                        'microstructure', 'sentiment_divergence'
                    )),
    
    -- Pattern definition
    description     TEXT NOT NULL,             -- detailed description
    conditions      TEXT NOT NULL,             -- JSON: structured conditions
    -- Example conditions:
    -- {
    --   "price_action": {"pattern": "double_bottom", "timeframe": "4h"},
    --   "volume": {"condition": "declining_on_second_test", "threshold": 0.7},
    --   "indicators": {"rsi": {"min": 25, "max": 35}, "macd": "bullish_cross"},
    --   "regime": ["mean_reverting", "low_volatility"],
    --   "context": {"market_cap": "large", "sector": "technology"}
    -- }
    
    -- Statistical validation
    sample_size     INTEGER DEFAULT 0,         -- how many times observed
    win_rate        REAL,                      -- historical win rate
    avg_return      REAL,                      -- average return when pattern triggers
    avg_duration_hours REAL,                   -- average time to target
    risk_reward     REAL,                      -- average R:R
    expectancy      REAL,                      -- win_rate * avg_win - loss_rate * avg_loss
    sharpe_contribution REAL,                  -- contribution to portfolio Sharpe
    
    -- Confidence and decay
    confidence      REAL DEFAULT 0.5,          -- 0-1, increases with more samples
    last_validated  TEXT,                      -- last time pattern was confirmed
    decay_rate      REAL DEFAULT 0.01,         -- confidence decay per day without validation
    min_sample_size INTEGER DEFAULT 10,        -- minimum observations before pattern is usable
    
    -- Visual/embedding
    example_trade_ids TEXT,                    -- JSON array of trade_ids showing this pattern
    chart_embedding TEXT,                      -- ChromaDB vector ID for chart patterns
    
    -- Lifecycle
    status          TEXT DEFAULT 'candidate'
                    CHECK(status IN ('candidate','validated','active','deprecated','archived')),
    discovered_by   TEXT,                      -- agent or method that found it
    discovered_at   TEXT NOT NULL,
    
    -- Metadata
    tags            TEXT,                      -- JSON array of tags
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_patterns_type ON patterns(pattern_type, status);
CREATE INDEX idx_patterns_status ON patterns(status, confidence DESC);
CREATE INDEX idx_patterns_expectancy ON patterns(expectancy DESC) WHERE status = 'active';

-- ─────────────────────────────────────────────────────────────
-- Pattern observations — individual instances of a pattern
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pattern_observations (
    observation_id  TEXT PRIMARY KEY,
    pattern_id      TEXT NOT NULL,
    trade_id        TEXT,                      -- associated trade (if any)
    
    -- Observation context
    symbol          TEXT NOT NULL,
    observed_at     TEXT NOT NULL,
    timeframe       TEXT,                      -- timeframe where pattern was detected
    
    -- Market state at observation
    price_at_trigger REAL,
    regime_at_trigger TEXT,
    volatility_at_trigger REAL,
    volume_at_trigger REAL,
    
    -- Outcome
    outcome         TEXT CHECK(outcome IN ('win','loss','breakeven','pending')),
    return_pct      REAL,
    duration_hours  REAL,
    max_adverse     REAL,                      -- max drawdown during trade
    max_favorable   REAL,                      -- max gain during trade
    
    -- Embedding reference
    embedding_id    TEXT,                      -- ChromaDB vector ID
    
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (pattern_id) REFERENCES patterns(pattern_id),
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);

CREATE INDEX idx_obs_pattern ON pattern_observations(pattern_id, observed_at DESC);
CREATE INDEX idx_obs_outcome ON pattern_observations(outcome, return_pct);

-- ─────────────────────────────────────────────────────────────
-- Pattern relationships
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pattern_relationships (
    relationship_id TEXT PRIMARY KEY,
    pattern_a_id    TEXT NOT NULL,
    pattern_b_id    TEXT NOT NULL,
    relationship    TEXT NOT NULL
                    CHECK(relationship IN ('co_occurs','precedes','negates','enhances','requires')),
    strength        REAL,                      -- correlation strength
    sample_size     INTEGER,
    
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (pattern_a_id) REFERENCES patterns(pattern_id),
    FOREIGN KEY (pattern_b_id) REFERENCES patterns(pattern_id)
);

CREATE INDEX idx_rel_a ON pattern_relationships(pattern_a_id);
CREATE INDEX idx_rel_b ON pattern_relationships(pattern_b_id);
```

### 5.3 ChromaDB Collection Design

```python
# ChromaDB collections for pattern embeddings

# Collection 1: Chart Pattern Embeddings
# Embedding: visual representation of price action
chart_patterns = chroma_client.get_or_create_collection(
    name="chart_patterns",
    metadata={
        "description": "Visual chart pattern embeddings for similarity search",
        "hnsw:space": "cosine",
        "hnsw:M": 16,
        "hnsw:ef_construction": 200,
    }
)
# Each document contains:
# {
#   "id": pattern_id,
#   "embedding": [float x 384],  # from sentence-transformers or custom CNN
#   "metadata": {
#       "pattern_type": "setup",
#       "symbol": "AAPL",
#       "timeframe": "4h",
#       "regime": "mean_reverting",
#       "win_rate": 0.65,
#       "expectancy": 0.02,
#       "sample_size": 45,
#       "status": "active"
#   },
#   "document": "Double bottom on AAPL 4h chart with declining volume..."
# }

# Collection 2: Market Context Embeddings
# Embedding: textual description of market conditions
market_contexts = chroma_client.get_or_create_collection(
    name="market_contexts",
    metadata={
        "description": "Market condition descriptions for regime-pattern matching",
        "hnsw:space": "cosine",
    }
)
# Each document is a natural language description of market conditions
# that led to a pattern observation

# Collection 3: Trade Thesis Embeddings
# Embedding: the reasoning behind trades
trade_theses = chroma_client.get_or_create_collection(
    name="trade_theses",
    metadata={
        "description": "Trade reasoning for similarity-based learning",
        "hnsw:space": "cosine",
    }
)
```

### 5.4 Data Flow

```
Pattern Discovery Pipeline:
━━━━━━━━━━━━━━━━━━━━━━━━━━

trades.db (completed trades)
    │
    ▼
Learning Agent (Python)
    │
    ├─► Statistical clustering (sklearn)
    │   └─► Find recurring price/volume/regime combinations
    │
    ├─► Sequence mining (prefix-span)
    │   └─► Find recurring event sequences before wins/losses
    │
    ├─► Chart pattern recognition (CNN)
    │   └─► Detect visual patterns in OHLCV data
    │
    └─► LLM analysis
        └─► Natural language pattern descriptions
    
    │
    ▼
Pattern Candidate (SQLite: patterns.db)
    │
    ├─► Generate embedding (sentence-transformers)
    │   └─► Store in ChromaDB
    │
    └─► Backtest against history
        └─► Update win_rate, expectancy, confidence
            │
            ▼
        If confidence > 0.7 AND sample_size > 30:
            status → 'active'
            └─► Available to Strategy Agent for signal generation


Pattern Matching (Real-time):
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Current market state
    │
    ├─► Exact match: query patterns.db conditions
    │
    └─► Semantic match: embed current state → ChromaDB query
        └─► Top-K similar patterns
            └─► Filter by confidence > 0.6
                └─► Return pattern predictions to Strategy Agent
```

### 5.5 Retention Policy

| Data | Retention | Action |
|------|-----------|--------|
| Active patterns | Permanent | Continuously revalidated |
| Observations | 2 years | Aggregate stats before archive |
| Deprecated patterns | 1 year | Keep for anti-pattern learning |
| ChromaDB embeddings | Match SQLite lifecycle | Delete when pattern archived |

---

## 6. Knowledge Store #5: Lesson Archive (SQLite + FTS5)

### 6.1 Purpose

Distilled wisdom from failures and successes. This is the system's "book of lessons" — not raw data, but processed insights that can be searched and applied to future decisions. FTS5 enables full-text search across all lessons.

### 6.2 SQL Schema

```sql
-- ============================================================
-- LESSON ARCHIVE — lessons.db
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────
-- Core lessons table
-- ─────────────────────────────────────────────────────────────
CREATE TABLE lessons (
    lesson_id       TEXT PRIMARY KEY,          -- ULID
    title           TEXT NOT NULL,             -- concise lesson title
    content         TEXT NOT NULL,             -- full lesson in markdown
    
    -- Classification
    lesson_type     TEXT NOT NULL
                    CHECK(lesson_type IN (
                        'trade_mistake', 'strategy_insight', 'market_observation',
                        'risk_lesson', 'execution_improvement', 'psychological',
                        'system_improvement', 'regime_insight', 'pattern_insight'
                    )),
    severity        TEXT NOT NULL
                    CHECK(severity IN ('critical','important','moderate','minor')),
    category        TEXT,                      -- free-form category
    
    -- Source context
    source_trade_ids TEXT,                     -- JSON array of related trades
    source_strategy_id TEXT,                   -- related strategy
    source_pattern_id TEXT,                    -- related pattern
    source_event     TEXT,                     -- what triggered this lesson
    
    -- Applicability
    applicable_regimes TEXT,                   -- JSON array of regimes where relevant
    applicable_symbols TEXT,                   -- JSON array of symbols (or 'ALL')
    applicable_strategies TEXT,                -- JSON array of strategy types
    
    -- Actionability
    action_required INTEGER DEFAULT 0,         -- does this require a system change?
    action_taken    TEXT,                      -- what was done about it
    action_status   TEXT DEFAULT 'pending'
                    CHECK(action_status IN ('pending','in_progress','completed','dismissed')),
    
    -- Reinforcement
    times_applied   INTEGER DEFAULT 0,         -- how many times lesson was referenced
    times_violated  INTEGER DEFAULT 0,         -- how many times lesson was ignored
    last_applied    TEXT,
    last_violated   TEXT,
    violation_impact REAL,                     -- total P&L impact of violations
    
    -- Confidence and decay
    confidence      REAL DEFAULT 0.8,          -- how confident we are in this lesson
    validated_count INTEGER DEFAULT 1,         -- times independently confirmed
    
    -- Metadata
    discovered_by   TEXT,                      -- which agent discovered this
    discovered_at   TEXT NOT NULL,
    tags            TEXT,                      -- JSON array
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_archived     INTEGER DEFAULT 0
);

CREATE INDEX idx_lessons_type ON lessons(lesson_type, severity);
CREATE INDEX idx_lessons_source_strategy ON lessons(source_strategy_id);
CREATE INDEX idx_lessons_action ON lessons(action_status) WHERE action_required = 1;
CREATE INDEX idx_lessons_applied ON lessons(times_applied DESC);
CREATE INDEX idx_lessons_violated ON lessons(times_violated DESC, violation_impact);

-- ─────────────────────────────────────────────────────────────
-- FTS5 full-text search index
-- ─────────────────────────────────────────────────────────────
CREATE VIRTUAL TABLE lessons_fts USING fts5(
    title,
    content,
    lesson_type,
    category,
    tags,
    
    content=lessons,
    content_rowid=rowid,
    
    tokenize='porter unicode61 remove_diacritics 2',
    
    -- Column weights for ranking
    rank='bm25(10.0, 5.0, 2.0, 3.0, 1.0)'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER lessons_ai AFTER INSERT ON lessons BEGIN
    INSERT INTO lessons_fts(rowid, title, content, lesson_type, category, tags)
    VALUES (new.rowid, new.title, new.content, new.lesson_type, new.category, new.tags);
END;

CREATE TRIGGER lessons_ad AFTER DELETE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, title, content, lesson_type, category, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.lesson_type, old.category, old.tags);
END;

CREATE TRIGGER lessons_au AFTER UPDATE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, title, content, lesson_type, category, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.lesson_type, old.category, old.tags);
    INSERT INTO lessons_fts(rowid, title, content, lesson_type, category, tags)
    VALUES (new.rowid, new.title, new.content, new.lesson_type, new.category, new.tags);
END;

-- ─────────────────────────────────────────────────────────────
-- Lesson application log — when lessons are referenced
-- ─────────────────────────────────────────────────────────────
CREATE TABLE lesson_applications (
    application_id  TEXT PRIMARY KEY,
    lesson_id       TEXT NOT NULL,
    trade_id        TEXT,                      -- trade where lesson was applied
    context         TEXT NOT NULL,             -- how the lesson was used
    outcome         TEXT,                      -- what happened
    agent           TEXT,                      -- which agent applied it
    
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id),
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);

CREATE INDEX idx_app_lesson ON lesson_applications(lesson_id, created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Lesson violations — when lessons were ignored
-- ─────────────────────────────────────────────────────────────
CREATE TABLE lesson_violations (
    violation_id    TEXT PRIMARY KEY,
    lesson_id       TEXT NOT NULL,
    trade_id        TEXT NOT NULL,
    violation_desc  TEXT NOT NULL,             -- what was violated
    pnl_impact      REAL,                     -- impact of the violation
    reason_given    TEXT,                      -- why the lesson was ignored
    
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    
    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id),
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);

CREATE INDEX idx_violation_lesson ON lesson_violations(lesson_id, created_at DESC);
```

### 6.3 FTS5 Search Patterns

```python
# Search 1: Find lessons relevant to current situation
# Natural language query against all lesson content
SELECT l.*, rank
FROM lessons_fts fts
JOIN lessons l ON l.rowid = fts.rowid
WHERE lessons_fts MATCH 'mean reversion stop loss premature exit'
    AND l.is_archived = 0
ORDER BY rank
LIMIT 10;

# Search 2: Find critical lessons for a specific strategy type
SELECT l.*, rank
FROM lessons_fts fts
JOIN lessons l ON l.rowid = fts.rowid
WHERE lessons_fts MATCH 'momentum breakout'
    AND l.severity = 'critical'
    AND l.is_archived = 0
ORDER BY rank
LIMIT 5;

# Search 3: Find lessons about a specific market condition
SELECT l.*, rank
FROM lessons_fts fts
JOIN lessons l ON l.rowid = fts.rowid
WHERE lessons_fts MATCH '"high volatility" OR "regime change"'
    AND l.applicable_regimes LIKE '%high_volatility%'
ORDER BY rank
LIMIT 10;

# Search 4: Most violated lessons (learning opportunities)
SELECT l.title, l.lesson_type, l.times_violated, l.violation_impact,
       l.content, GROUP_CONCAT(lv.violation_desc, ' | ') as violations
FROM lessons l
LEFT JOIN lesson_violations lv ON l.lesson_id = lv.lesson_id
WHERE l.times_violated > 0
GROUP BY l.lesson_id
ORDER BY l.violation_impact DESC
LIMIT 20;

# Search 5: Recently discovered lessons (context for reflection)
SELECT * FROM lessons
WHERE discovered_at > datetime('now', '-7 days')
    AND is_archived = 0
ORDER BY severity, discovered_at DESC;
```

### 6.4 Data Flow

```
Lesson Discovery Pipeline:
━━━━━━━━━━━━━━━━━━━━━━━━━

[Post-Trade Reflection Agent]
    │
    ├─► Analyze trade outcome
    │   ├─► What went right?
    │   ├─► What went wrong?
    │   └─► What would I do differently?
    │
    ├─► Cross-reference with existing lessons
    │   ├─► FTS5 search for similar past mistakes
    │   └─► Check if lesson already exists
    │
    ├─► Create or reinforce lesson
    │   ├─► New lesson → INSERT
    │   └─► Existing → UPDATE (increment validated_count, confidence)
    │
    └─► Generate embedding for semantic search
        └─► Store in ChromaDB (optional, for cross-store search)

[Periodic Lesson Review Agent] (weekly)
    │
    ├─► Review violated lessons
    │   └─► Why are we repeating mistakes?
    │
    ├─► Review unused lessons
    │   └─► Are they still relevant?
    │
    └─► Decay confidence on unvalidated lessons
        └─► Archive lessons with confidence < 0.3
```

### 6.5 Retention Policy

| Data | Retention | Action |
|------|-----------|--------|
| Critical lessons | Permanent | Never archive |
| Important lessons | 3 years | Archive after 2y if not applied |
| Moderate/minor lessons | 1 year | Archive after 6mo if not applied |
| Application log | 2 years | Compress after 1y |
| Violations | 2 years | Critical for learning |
| FTS index | Auto-maintained | Rebuild on corruption |

---

## 7. Session Memory Architecture

### 7.1 Problem

LLM agents have bounded context windows. They need to remember relevant information from past sessions without loading everything. This is the "working memory" layer.

### 7.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    SESSION MEMORY LAYERS                        │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ LAYER 1: Hot Context (in-prompt, < 2K tokens)          │   │
│  │ ─────────────────────────────────────────────────────   │   │
│  │ • Current positions                                      │   │
│  │ • Active signals pending                                 │   │
│  │ • Current regime + confidence                            │   │
│  │ • Today's P&L                                            │   │
│  │ • Risk limits remaining                                  │   │
│  │ • Last 3 trades (summary)                                │   │
│  │ • Active lessons (top 5 by severity)                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ LAYER 2: Warm Context (retrieved on-demand, < 8K tokens)│   │
│  │ ─────────────────────────────────────────────────────   │   │
│  │ • Recent trade history (last 20 trades, summary)        │   │
│  │ • Strategy performance snapshot                          │   │
│  │ • Pattern matches for current setup                      │   │
│  │ • Relevant lessons (FTS5 search)                         │   │
│  │ • Regime transition history (last 10)                    │   │
│  │ • Weekly P&L and metrics                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ LAYER 3: Cold Context (database queries, unlimited)      │   │
│  │ ─────────────────────────────────────────────────────   │   │
│  │ • Full trade history (trades.db)                         │   │
│  │ • All patterns (patterns.db + ChromaDB)                  │   │
│  │ • All lessons (lessons.db + FTS5)                        │   │
│  │ • Strategy evolution tree (strategies.db)                │   │
│  │ • Audit trail (audit_log)                                │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 Forced Prioritization Protocol

When context window is constrained, agents must prioritize:

```python
class SessionMemoryManager:
    """Manages bounded context for agent sessions."""
    
    # Priority order (higher = more important)
    PRIORITIES = {
        'risk_violations': 100,          # always include
        'active_stop_losses': 95,        # always include
        'current_positions': 90,         # always include
        'regime_state': 85,              # always include
        'pending_signals': 80,           # always include
        'today_pnl': 75,
        'critical_lessons': 70,
        'recent_trades': 60,
        'pattern_matches': 50,
        'strategy_performance': 40,
        'weekly_summary': 30,
        'historical_context': 20,
        'metadata': 10,
    }
    
    def build_context(self, max_tokens: int = 8000) -> str:
        """Build prioritized context within token budget."""
        context_items = []
        remaining_tokens = max_tokens
        
        # Always include critical items first
        for item in self._get_items_by_priority():
            tokens = self._count_tokens(item)
            if tokens <= remaining_tokens:
                context_items.append(item)
                remaining_tokens -= tokens
            else:
                # Truncate or summarize to fit
                truncated = self._summarize_to_fit(item, remaining_tokens)
                if truncated:
                    context_items.append(truncated)
                break
        
        return self._format_context(context_items)
    
    def _get_items_by_priority(self) -> list:
        """Fetch and sort all context items by priority."""
        items = []
        
        # Risk state (always first)
        items.append((100, self._get_risk_state()))
        items.append((95, self._get_active_stops()))
        items.append((90, self._get_current_positions()))
        items.append((85, self._get_regime_state()))
        items.append((80, self._get_pending_signals()))
        
        # Conditional items
        items.append((70, self._get_critical_lessons()))
        items.append((60, self._get_recent_trades(limit=10)))
        items.append((50, self._get_pattern_matches()))
        
        return sorted(items, key=lambda x: x[0], reverse=True)
```

### 7.4 Session State File Format

```yaml
# session_state.yaml — persisted between agent turns
# Loaded at session start, updated on each turn

session:
  id: "session_ulid"
  started_at: "2026-07-24T00:00:00Z"
  agent: "strategy_agent"
  context_tokens_used: 3200
  context_tokens_budget: 8000
  
  # Hot state (always in context)
  hot:
    regime:
      dominant: "mean_reverting"
      confidence: 0.85
      probabilities: {trending_bull: 0.15, trending_bear: 0.05, mean_reverting: 0.60, high_vol: 0.12}
    
    positions:
      count: 3
      total_exposure: 125000
      net_exposure: 75000
      portfolio_heat: 0.035
    
    pnl:
      daily_realized: 1250
      daily_unrealized: 1750
      daily_fees: 45
    
    risk:
      daily_loss_remaining: 2045
      circuit_breaker: "green"
      active_violations: []
    
    recent_trades:
      - {symbol: "AAPL", side: "buy", pnl: 150, grade: "B"}
      - {symbol: "TSLA", side: "sell", pnl: -50, grade: "C"}
      - {symbol: "BTC", side: "buy", pnl: 300, grade: "A"}
  
  # Warm state (retrieved on demand)
  warm:
    last_retrieval: "2026-07-24T00:30:00Z"
    cached_patterns: 3
    cached_lessons: 5
```

---

## 8. Trade Journal Format

### 8.1 Daily Journal

```markdown
# Daily Trading Journal — 2026-07-24

## Summary
- **Trades:** 12 | **Win Rate:** 67% | **P&L:** +$2,955
- **Best:** AAPL long +$450 | **Worst:** TSLA short -$120
- **Regime:** Mean Reverting (confidence: 85%)
- **Emotional State:** Disciplined, slight FOMO on TSLA missed entry

## Performance Metrics
| Metric | Today | 7d Avg | 30d Avg |
|--------|-------|--------|---------|
| Sharpe | 2.1 | 1.8 | 1.5 |
| Win Rate | 67% | 62% | 58% |
| Avg Win | $320 | $280 | $250 |
| Avg Loss | -$95 | -$110 | -$130 |
| Profit Factor | 3.4 | 2.5 | 2.0 |
| Max Drawdown | -$180 | -$350 | -$800 |

## Trade Log
### Trade 1: AAPL Long ✅
- **Time:** 09:45 | **Entry:** $185.50 | **Exit:** $187.25 | **P&L:** +$450
- **Thesis:** Double bottom on 15m, RSI oversold, mean reversion regime
- **Execution:** Clean entry, held through minor pullback, exited at resistance
- **Grade:** A (execution) / A (outcome)
- **Lesson:** Patience on entry paid off — waited for volume confirmation

### Trade 2: TSLA Short ❌
- **Time:** 10:30 | **Entry:** $245.00 | **Exit:** $246.20 | **P&L:** -$120
- **Thesis:** Overextended after earnings, expected pullback
- **Execution:** Entry was fine, but stopped out on momentum continuation
- **Grade:** B (execution) / D (outcome)
- **Lesson:** Don't fade momentum in trending regime — regime check was stale

## Lessons Learned
1. **[REINFORCED]** Always check regime before counter-trend trades
2. **[NEW]** TSLA has higher idiosyncratic volatility — adjust position size

## Tomorrow's Focus
- Watch for regime transition signals (VIX approaching 20)
- AAPL may set up again at $186 support
- Review TSLA pattern — is shorting after earnings systematically unprofitable?
```

### 8.2 Weekly Journal

```markdown
# Weekly Trading Summary — Week 30 (2026-07-21 to 2026-07-25)

## Weekly Performance
- **Total Trades:** 52 | **Win Rate:** 62% | **Net P&L:** +$8,450
- **Best Strategy:** Mean Reversion v3 (+$5,200)
- **Worst Strategy:** Momentum Breakout v1 (-$1,100)
- **Regime:** Transitioned from Mean Reverting → Trending Bull (Thursday)

## Strategy Performance
| Strategy | Trades | Win Rate | P&L | Sharpe | Status |
|----------|--------|----------|-----|--------|--------|
| MR v3 | 28 | 68% | +$5,200 | 2.3 | ✅ Live |
| Momentum v1 | 15 | 53% | -$1,100 | 0.4 | ⚠️ Review |
| Pairs Trade v2 | 9 | 67% | +$4,350 | 2.1 | ✅ Live |

## Key Observations
1. Regime transition on Thursday caused Momentum v1 losses — strategy not designed for regime shifts
2. Mean Reversion v3 performed exceptionally in low-vol environment
3. Pairs Trade v2 benefited from sector rotation

## Evolution Actions
- [ ] Mutate Momentum v1: add regime transition filter
- [ ] Test Mean Reversion v3 with tighter stops (current: -2%, test: -1.5%)
- [ ] Review Pairs Trade v2 for capacity constraints

## Lesson Review
- 3 new lessons created
- 1 lesson violated (TSLA counter-trend) — impact: -$120
- 0 lessons deprecated
```

### 8.3 Monthly Journal

```markdown
# Monthly Trading Report — July 2026

## Executive Summary
July was a strong month with net P&L of +$32,150 across 180 trades.
The portfolio navigated a regime transition from mean reverting to trending
mid-month, with the learning agent successfully adapting strategy allocations.

## Performance Attribution
### By Strategy
| Strategy | Allocation | Trades | Return | Sharpe | Max DD |
|----------|-----------|--------|--------|--------|--------|
| MR v3 | 40% | 72 | +8.2% | 2.1 | -3.2% |
| Momentum v2 | 25% | 45 | +3.1% | 1.2 | -5.1% |
| Pairs v2 | 20% | 38 | +6.5% | 1.9 | -2.8% |
| Stat Arb v1 | 15% | 25 | +2.8% | 1.5 | -2.1% |

### By Regime
| Regime | Days | Return | Best Strategy |
|--------|------|--------|---------------|
| Mean Reverting | 12 | +$18,200 | MR v3 |
| Trending Bull | 8 | +$12,400 | Momentum v2 |
| High Volatility | 3 | +$1,550 | Pairs v2 |

## Evolution Summary
- 5 new strategy mutations tested
- 2 promoted to paper trading
- 1 retired (mean reversion v2 — superseded by v3)
- 12 new patterns discovered
- 8 new lessons created
- 2 lessons violated (total impact: -$340)

## Risk Metrics
- Max drawdown: -4.2% (within -10% limit)
- Worst day: -$1,800 (July 15 — regime transition)
- Best day: +$4,200 (July 22 — trending breakout)
- 95% VaR: $2,100/day
- Sharpe ratio (monthly): 2.4
```

---

## 9. FTS5 Search Configuration

### 9.1 Index Design

```sql
-- Main lessons FTS5 index (already defined in §6.2)
-- Additional FTS5 indexes for cross-store search

-- Trade thesis search (in trades.db)
CREATE VIRTUAL TABLE trade_thesis_fts USING fts5(
    thesis,
    reflection,
    content=trades,
    content_rowid=rowid,
    tokenize='porter unicode61 remove_diacritics 2'
);

-- Pattern description search (in patterns.db)
CREATE VIRTUAL TABLE pattern_desc_fts USING fts5(
    pattern_name,
    description,
    content=patterns,
    content_rowid=rowid,
    tokenize='porter unicode61 remove_diacritics 2'
);

-- Strategy genome search (in strategies.db)
CREATE VIRTUAL TABLE strategy_text_fts USING fts5(
    name,
    strategy_type,
    content=strategy_genomes,
    content_rowid=rowid,
    tokenize='porter unicode61 remove_diacritics 2'
);
```

### 9.2 Search API Design

```python
class TradingSearchEngine:
    """Unified search across all knowledge stores."""
    
    def __init__(self, trades_db, strategies_db, patterns_db, lessons_db):
        self.trades = trades_db
        self.strategies = strategies_db
        self.patterns = patterns_db
        self.lessons = lessons_db
    
    def search(self, query: str, stores: list[str] = None, limit: int = 20) -> list:
        """
        Search across all stores with relevance ranking.
        
        Args:
            query: Natural language search query
            stores: Which stores to search (default: all)
            limit: Max results per store
        """
        stores = stores or ['lessons', 'trades', 'patterns', 'strategies']
        results = []
        
        if 'lessons' in stores:
            results.extend(self._search_lessons(query, limit))
        if 'trades' in stores:
            results.extend(self._search_trades(query, limit))
        if 'patterns' in stores:
            results.extend(self._search_patterns(query, limit))
        if 'strategies' in stores:
            results.extend(self._search_strategies(query, limit))
        
        # Global relevance ranking
        return sorted(results, key=lambda x: x['relevance'], reverse=True)[:limit]
    
    def _search_lessons(self, query, limit):
        """FTS5 search on lessons with BM25 ranking."""
        sql = """
            SELECT l.*, 
                   rank as bm25_score,
                   'lesson' as source_type
            FROM lessons_fts fts
            JOIN lessons l ON l.rowid = fts.rowid
            WHERE lessons_fts MATCH ?
                AND l.is_archived = 0
            ORDER BY rank
            LIMIT ?
        """
        return self.lessons.execute(sql, (self._format_query(query), limit)).fetchall()
    
    def _search_trades(self, query, limit):
        """FTS5 search on trade theses and reflections."""
        sql = """
            SELECT t.trade_id, t.symbol, t.side, t.realized_pnl,
                   t.thesis, t.reflection, t.outcome_grade,
                   rank as bm25_score,
                   'trade' as source_type
            FROM trade_thesis_fts fts
            JOIN trades t ON t.rowid = fts.rowid
            WHERE trade_thesis_fts MATCH ?
                AND t.is_deleted = 0
            ORDER BY rank
            LIMIT ?
        """
        return self.trades.execute(sql, (self._format_query(query), limit)).fetchall()
    
    def _format_query(self, query: str) -> str:
        """Format natural language query for FTS5."""
        # Remove special FTS5 characters
        clean = re.sub(r'[^\w\s]', '', query)
        # Add OR between terms for broader matching
        terms = clean.split()
        return ' OR '.join(f'"{t}"' for t in terms if len(t) > 2)
```

### 9.3 FTS5 Tokenizer Configuration

```
Tokenizer: porter unicode61 remove_diacritics 2
─────────────────────────────────────────────────

porter            — Stemming (running → run, losses → loss)
unicode61         — Unicode-aware tokenization
remove_diacritics — Normalize accented characters (café → cafe)
2                 — Minimum token length of 2 characters

Custom additions:
• Trading-specific synonyms handled at query time:
  - "stop loss" → "stop_loss OR stoploss OR stop-loss"
  - "take profit" → "take_profit OR takeprofit OR target"
  - "DD" → "drawdown OR due_diligence" (context-dependent)
  
• Symbol normalization:
  - "SPX" → "SPX OR S&P500 OR SP500"
  - "BTC" → "BTC OR Bitcoin OR BTCUSD"
```

---

## 10. Vector Embedding Pipeline

### 10.1 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                VECTOR EMBEDDING PIPELINE                        │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ Raw Text     │    │ Embedding    │    │ ChromaDB         │  │
│  │ Sources      │───►│ Model        │───►│ Collections      │  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
│                                                                 │
│  Sources:                                                       │
│  • Trade theses (trades.db)                                     │
│  • Trade reflections (trades.db)                                │
│  • Pattern descriptions (patterns.db)                           │
│  • Lesson content (lessons.db)                                  │
│  • Market context snapshots (Redis)                             │
│  • OHLCV chart images (rendered → CNN embedding)                │
│                                                                 │
│  Model: sentence-transformers/all-MiniLM-L6-v2 (384-dim)       │
│  Batch size: 64                                                 │
│  Update frequency: On new content (event-driven)                │
│  Full reindex: Weekly (Sunday 02:00 UTC)                        │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Embedding Generation

```python
from sentence_transformers import SentenceTransformer
import chromadb
from typing import Optional
import hashlib

class EmbeddingPipeline:
    """Generates and stores embeddings for trading knowledge."""
    
    def __init__(self, chroma_client: chromadb.ClientAPI):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.chroma = chroma_client
        
        # Collections
        self.chart_patterns = chroma_client.get_or_create_collection(
            name="chart_patterns",
            metadata={"hnsw:space": "cosine", "hnsw:M": 16}
        )
        self.trade_theses = chroma_client.get_or_create_collection(
            name="trade_theses",
            metadata={"hnsw:space": "cosine"}
        )
        self.lessons = chroma_client.get_or_create_collection(
            name="lessons",
            metadata={"hnsw:space": "cosine"}
        )
        self.market_contexts = chroma_client.get_or_create_collection(
            name="market_contexts",
            metadata={"hnsw:space": "cosine"}
        )
    
    def embed_trade_thesis(self, trade_id: str, thesis: str, metadata: dict):
        """Embed a trade thesis for similarity search."""
        embedding = self.model.encode(thesis)
        self.trade_theses.upsert(
            ids=[trade_id],
            embeddings=[embedding.tolist()],
            documents=[thesis],
            metadatas=[metadata]
        )
    
    def embed_lesson(self, lesson_id: str, title: str, content: str, metadata: dict):
        """Embed a lesson for semantic search."""
        # Combine title and content for richer embedding
        text = f"{title}: {content}"
        embedding = self.model.encode(text)
        self.lessons.upsert(
            ids=[lesson_id],
            embeddings=[embedding.tolist()],
            documents=[text],
            metadatas=[metadata]
        )
    
    def embed_pattern(self, pattern_id: str, description: str, 
                      chart_image: Optional[bytes] = None, metadata: dict = None):
        """Embed a pattern description (and optionally its chart image)."""
        # Text embedding
        text_embedding = self.model.encode(description)
        
        # If chart image provided, combine with CNN embedding
        if chart_image:
            chart_embedding = self._get_chart_embedding(chart_image)
            # Average text and chart embeddings (weighted)
            combined = 0.6 * text_embedding + 0.4 * chart_embedding
        else:
            combined = text_embedding
        
        self.chart_patterns.upsert(
            ids=[pattern_id],
            embeddings=[combined.tolist()],
            documents=[description],
            metadatas=[metadata or {}]
        )
    
    def embed_market_context(self, context_id: str, description: str, metadata: dict):
        """Embed current market conditions for similarity matching."""
        embedding = self.model.encode(description)
        self.market_contexts.upsert(
            ids=[context_id],
            embeddings=[embedding.tolist()],
            documents=[description],
            metadatas=[metadata]
        )
    
    def find_similar_patterns(self, current_conditions: str, n_results: int = 5,
                               filters: dict = None) -> list:
        """Find patterns similar to current market conditions."""
        embedding = self.model.encode(current_conditions)
        
        where = filters or {}
        where["status"] = "active"  # only active patterns
        
        results = self.chart_patterns.query(
            query_embeddings=[embedding.tolist()],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"]
        )
        return results
    
    def find_similar_lessons(self, situation: str, n_results: int = 5) -> list:
        """Find lessons relevant to current situation."""
        embedding = self.model.encode(situation)
        results = self.lessons.query(
            query_embeddings=[embedding.tolist()],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        return results
    
    def _get_chart_embedding(self, image_bytes: bytes):
        """Generate embedding from chart image using CNN."""
        # Placeholder — would use a trained CNN or vision model
        # For now, use a simple approach
        pass
```

### 10.3 Embedding Update Strategy

| Event | Action | Priority |
|-------|--------|----------|
| New trade completed | Embed thesis + reflection | High |
| New pattern discovered | Embed description + chart | High |
| New lesson created | Embed title + content | High |
| Trade outcome updated | Re-embed thesis (outcome changes context) | Medium |
| Weekly reindex | Full re-embed all active content | Low (background) |
| Pattern deprecated | Remove from ChromaDB | Medium |

---

## 11. Data Compaction Rules

### 11.1 Compaction Schedule

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMPACTION SCHEDULE                          │
│                                                                 │
│  MINUTE:                                                        │
│  • Redis: no compaction needed (TTL handles expiry)             │
│  • WAL buffer: flush to SQLite if > 1000 entries               │
│                                                                 │
│  HOURLY:                                                        │
│  • trades.db: VACUUM ANALYZE (if > 100 new rows)               │
│  • strategies.db: update performance aggregates                 │
│  • patterns.db: decay confidence on unvalidated patterns        │
│                                                                 │
│  DAILY (02:00 UTC):                                             │
│  • trades.db: archive snapshots > 90 days                       │
│  • patterns.db: deprecate patterns with confidence < 0.3       │
│  • lessons.db: archive lessons with confidence < 0.3            │
│  • ChromaDB: remove embeddings for archived items               │
│  • Generate daily journal                                       │
│                                                                 │
│  WEEKLY (Sunday 03:00 UTC):                                     │
│  • Full VACUUM on all SQLite databases                          │
│  • Re-embed all active content (ChromaDB full reindex)          │
│  • Generate weekly journal                                      │
│  • Rebuild FTS5 indexes if needed                               │
│  • Redis: snapshot regime history to SQLite                     │
│                                                                 │
│  MONTHLY (1st of month, 04:00 UTC):                             │
│  • Generate monthly report                                      │
│  • Archive trades > 2 years to cold storage                     │
│  • Archive lessons > 1 year (non-critical)                      │
│  • Compress audit log > 1 year                                  │
│  • Full backup of all databases                                 │
│                                                                 │
│  QUARTERLY:                                                     │
│  • Review and prune strategy genomes                            │
│  • Archive dead strategies > 1 year                             │
│  • Full ChromaDB rebuild from source                            │
└─────────────────────────────────────────────────────────────────┘
```

### 11.2 Compaction Survival Rules

```python
class CompactionEngine:
    """Determines what survives compaction."""
    
    def compact_trades(self, db, cutoff_date):
        """Trades: full records survive, snapshots are compressed."""
        # Keep full trade records (regulatory requirement)
        # Compress snapshots: aggregate to OHLCV
        db.execute("""
            INSERT INTO trade_snapshots_compressed 
                (trade_id, snapshot_type, open, high, low, close, volume, timestamp)
            SELECT trade_id, snapshot_type, 
                   MIN(mid), MAX(mid), MIN(mid), 
                   (SELECT mid FROM trade_snapshots ts2 
                    WHERE ts2.trade_id = ts1.trade_id 
                    ORDER BY created_at DESC LIMIT 1),
                   SUM(volume_24h), MIN(created_at)
            FROM trade_snapshots ts1
            WHERE created_at < ?
            GROUP BY trade_id, snapshot_type
        """, (cutoff_date,))
        
        # Delete raw snapshots after compression
        db.execute("DELETE FROM trade_snapshots WHERE created_at < ?", (cutoff_date,))
    
    def compact_patterns(self, db):
        """Patterns: keep if validated, decay if not."""
        # Decay confidence on patterns not observed in 30 days
        db.execute("""
            UPDATE patterns 
            SET confidence = MAX(0, confidence - decay_rate * 30)
            WHERE last_validated < datetime('now', '-30 days')
                AND status = 'active'
        """)
        
        # Deprecate patterns below threshold
        db.execute("""
            UPDATE patterns 
            SET status = 'deprecated'
            WHERE confidence < 0.3 AND status = 'active'
        """)
        
        # Archive deprecated patterns older than 1 year
        db.execute("""
            UPDATE patterns 
            SET status = 'archived'
            WHERE status = 'deprecated' 
                AND updated_at < datetime('now', '-1 year')
        """)
    
    def compact_lessons(self, db):
        """Lessons: keep critical, archive unused."""
        # Critical lessons always survive
        # Non-critical lessons that haven't been applied in 1 year → archive
        db.execute("""
            UPDATE lessons 
            SET is_archived = 1
            WHERE severity != 'critical'
                AND times_applied = 0
                AND discovered_at < datetime('now', '-1 year')
        """)
    
    def compact_redis(self, r):
        """Redis: snapshot to SQLite, let TTL handle cleanup."""
        # Snapshot current regime to SQLite
        regime_data = r.hgetall('tsar:regime:current')
        # Store in regime_history table
        
        # Snapshot positions to SQLite
        positions = r.hgetall('tsar:positions:current')
        # Store in position_snapshots table
        
        # Redis keys with TTL expire naturally
        # No manual deletion needed
```

### 11.3 Compaction Impact Matrix

| Store | What Survives | What's Pruned | What's Archived |
|-------|---------------|---------------|-----------------|
| trades.db | All trade records, journal entries | Raw snapshots (compressed) | Records > 2y to cold storage |
| strategies.db | Active genomes, mutation history | Performance snapshots > 5y | Dead strategies > 1y |
| patterns.db | Active/validated patterns | Deprecated < 0.3 confidence | Archived > 1y |
| lessons.db | Critical lessons, recent lessons | Unused non-critical > 1y | Archived to cold storage |
| ChromaDB | Active embeddings | Orphaned embeddings | Rebuilt from source |
| Redis | Current state only | Everything (TTL) | Snapshot to SQLite daily |

---

## 12. Redis Key Design (Complete Reference)

### 12.1 Key Naming Convention

```
tsar:{domain}:{entity}:{identifier}:{field}

Domains:
  regime     — Market regime state
  positions  — Current positions
  pnl        — Profit/loss tracking
  risk       — Risk limits and state
  market     — Market data cache
  strategy   — Strategy state
  signals    — Signal queue
  agents     — Agent coordination
  system     — System metadata
```

### 12.2 Complete Key Map

```
# ═══════════════════════════════════════════════════════════════
# REGIME DOMAIN
# ═══════════════════════════════════════════════════════════════

tsar:regime:current                     # Hash — global regime probabilities
tsar:regime:asset:{symbol}              # Hash — per-asset regime overrides
tsar:regime:transitions                 # List — recent regime changes (capped 1000)
tsar:regime:indicators                  # Hash — raw regime indicators
tsar:regime:history:{YYYY-MM-DD}        # String — daily regime snapshot (JSON)

# ═══════════════════════════════════════════════════════════════
# POSITIONS DOMAIN
# ═══════════════════════════════════════════════════════════════

tsar:positions:current                  # Hash — {symbol: position_json}
tsar:positions:risk                     # Hash — aggregate risk metrics
tsar:positions:history:{YYYY-MM-DD}     # String — end-of-day positions snapshot

# ═══════════════════════════════════════════════════════════════
# P&L DOMAIN
# ═══════════════════════════════════════════════════════════════

tsar:pnl:daily                          # Hash — today's P&L
tsar:pnl:weekly                         # String — weekly summary (JSON)
tsar:pnl:monthly                        # String — monthly summary (JSON)
tsar:pnl:ytd                            # String — year-to-date (JSON)
tsar:pnl:by_strategy:{strategy_id}      # Hash — per-strategy P&L

# ═══════════════════════════════════════════════════════════════
# RISK DOMAIN
# ═══════════════════════════════════════════════════════════════

tsar:risk:limits                        # Hash — configured risk limits
tsar:risk:state                         # Hash — current risk state
tsar:risk:violations                    # List — current violations
tsar:risk:circuit_breaker               # String — green|yellow|red
tsar:risk:daily_loss:{YYYY-MM-DD}       # String — daily loss tracking

# ═══════════════════════════════════════════════════════════════
# MARKET DATA DOMAIN
# ═══════════════════════════════════════════════════════════════

tsar:market:{symbol}:latest             # Hash — latest tick
tsar:market:{symbol}:ohlcv:1m           # List — 1-min bars (capped 1000)
tsar:market:{symbol}:ohlcv:5m           # List — 5-min bars (capped 1000)
tsar:market:{symbol}:ohlcv:15m          # List — 15-min bars (capped 1000)
tsar:market:{symbol}:ohlcv:1h           # List — 1-hour bars (capped 1000)
tsar:market:{symbol}:ohlcv:4h           # List — 4-hour bars (capped 1000)
tsar:market:{symbol}:ohlcv:1d           # List — daily bars (capped 1000)
tsar:market:{symbol}:book               # Hash — order book snapshot
tsar:market:{symbol}:trades             # List — recent trades (capped 100)

# ═══════════════════════════════════════════════════════════════
# STRATEGY DOMAIN
# ═══════════════════════════════════════════════════════════════

tsar:strategy:{strategy_id}:state       # Hash — live strategy state
tsar:strategy:{strategy_id}:signals     # List — recent signals (capped 100)
tsar:strategy:leaderboard               # Sorted Set — by sharpe_ratio
tsar:strategy:allocations               # Hash — current capital allocation

# ═══════════════════════════════════════════════════════════════
# SIGNALS DOMAIN (Work Queue)
# ═══════════════════════════════════════════════════════════════

tsar:signals:pending                    # List — pending signals (LPUSH/BRPOP)
tsar:signals:processing                 # Hash — signals being processed
tsar:signals:processed                  # List — completed signals (capped 10000)
tsar:signals:rejected                   # List — rejected signals (capped 1000)

# ═══════════════════════════════════════════════════════════════
# AGENTS DOMAIN
# ═══════════════════════════════════════════════════════════════

tsar:agents:heartbeat                   # Hash — last heartbeat per agent
tsar:agents:errors                      # List — recent errors (capped 100)
tsar:agents:config:{agent_name}         # Hash — agent-specific config

# ═══════════════════════════════════════════════════════════════
# SYSTEM DOMAIN
# ═══════════════════════════════════════════════════════════════

tsar:system:status                      # Hash — system-wide status
tsar:system:version                     # String — current system version
tsar:system:maintenance                 # String — maintenance mode flag
```

### 12.3 TTL Policy

```python
REDIS_TTL_POLICY = {
    # No TTL — managed explicitly
    'tsar:regime:current': None,
    'tsar:positions:current': None,
    'tsar:risk:limits': None,
    'tsar:risk:state': None,
    
    # Agent heartbeats — expire if agent dies
    'tsar:agents:heartbeat': 300,  # 5 minutes
    
    # Market data — keep fresh
    'tsar:market:*:latest': 60,    # 1 minute
    'tsar:market:*:ohlcv:*': None,  # managed by LTRIM
    
    # Signals — auto-cleanup
    'tsar:signals:processing': 300,  # 5 min timeout for stuck signals
    
    # Daily snapshots — keep for 7 days
    'tsar:regime:history:*': 604800,
    'tsar:positions:history:*': 604800,
    'tsar:pnl:daily': 86400,  # replaced daily
}
```

---

## 13. Cross-Cutting Concerns

### 13.1 Shared State Access Without Contention

```
READ CONTENTION STRATEGY:
━━━━━━━━━━━━━━━━━━━━━━━━

SQLite (WAL mode):
• Multiple concurrent readers — no blocking
• Single writer — uses WAL for non-blocking writes
• Write queue in Rust WAL buffer — batched to SQLite

Redis:
• All operations are atomic
• No contention — each key is independent
• Position updates use HSET (atomic field update)

ChromaDB:
• Single writer thread (Python)
• Async reads via query API
• Write queue with backpressure

AGENT ACCESS PATTERNS:
━━━━━━━━━━━━━━━━━━━━━

┌─────────────────┬─────────────────────────────────────────────┐
│ Agent           │ Access Pattern                              │
├─────────────────┼─────────────────────────────────────────────┤
│ Strategy Agent  │ READ: regime (Redis), patterns (SQLite),    │
│                 │        lessons (FTS5), positions (Redis)     │
│                 │ WRITE: signals (Redis queue)                 │
│                 │                                               │
│ Execution Agent │ READ: signals (Redis queue), risk (Redis),  │
│                 │        positions (Redis)                      │
│                 │ WRITE: fills (Rust WAL → SQLite),            │
│                 │        positions (Redis), P&L (Redis)         │
│                 │                                               │
│ Risk Governor   │ READ: positions (Redis), risk limits (Redis),│
│                 │        regime (Redis), recent trades (SQLite) │
│                 │ WRITE: risk state (Redis), circuit breaker    │
│                 │                                               │
│ Learning Agent  │ READ: trades (SQLite), patterns (SQLite+Chroma),│
│                 │        lessons (SQLite+FTS5)                  │
│                 │ WRITE: patterns (SQLite+Chroma),              │
│                 │        lessons (SQLite+FTS5),                 │
│                 │        strategy mutations (SQLite)            │
│                 │                                               │
│ Reflection Agent│ READ: recent trades (SQLite),                │
│                 │        lessons (FTS5 search)                  │
│                 │ WRITE: trade reflections (SQLite),            │
│                 │        new lessons (SQLite+FTS5)              │
└─────────────────┴─────────────────────────────────────────────┘
```

### 13.2 Learning Loop: Trade History → Pattern Extraction

```
LEARNING LOOP ARCHITECTURE:
━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────────────────────────────────────────┐
│                    LEARNING LOOP                                │
│                                                                 │
│  ┌──────────┐     ┌──────────────┐     ┌──────────────────┐   │
│  │ trades.db│────►│ Feature      │────►│ Pattern          │   │
│  │ (source) │     │ Extraction   │     │ Discovery        │   │
│  └──────────┘     │ (Python)     │     │ (Python)         │   │
│                   └──────────────┘     └────────┬─────────┘   │
│                                                 │              │
│                   ┌──────────────┐              │              │
│                   │ Backtest     │◄─────────────┘              │
│                   │ Validation   │                             │
│                   │ (Python)     │                             │
│                   └──────┬───────┘                             │
│                          │                                     │
│              ┌───────────┼───────────┐                         │
│              ▼           ▼           ▼                         │
│        ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
│        │patterns.db│ │ChromaDB  │ │lessons.db│                 │
│        │(new)     │ │(embed)   │ │(insights)│                 │
│        └──────────┘ └──────────┘ └──────────┘                 │
│                                                                 │
│  TRIGGER: Every 100 new trades OR daily at 03:00 UTC           │
│                                                                 │
│  STEPS:                                                         │
│  1. Query trades with outcomes (last 100 or since last run)    │
│  2. Extract features:                                           │
│     • Price action before/after entry                           │
│     • Volume profile                                            │
│     • Indicator values at entry                                 │
│     • Regime state at entry                                     │
│     • Time of day, day of week                                  │
│  3. Cluster similar trades (DBSCAN, K-means)                   │
│  4. Validate clusters as patterns:                              │
│     • Minimum 10 observations                                   │
│     • Win rate significantly > 50% (or < 50% for failure modes)│
│     • Sharpe contribution > 0.1                                 │
│  5. Generate embedding for pattern description                  │
│  6. Store in patterns.db + ChromaDB                             │
│  7. Extract lessons from losing clusters                        │
│  8. Store lessons in lessons.db + FTS5 index                    │
└─────────────────────────────────────────────────────────────────┘
```

### 13.3 Risk Governor: Real-Time Position Access

```
RISK GOVERNOR DATA ACCESS:
━━━━━━━━━━━━━━━━━━━━━━━━━

Pre-Trade Check (< 1ms):
──────────────────────────
1. READ tsar:risk:state (Redis) → is_paused? circuit_breaker?
2. READ tsar:positions:current (Redis) → current exposure
3. READ tsar:risk:limits (Redis) → check against proposed trade
4. READ tsar:regime:current (Redis) → regime-appropriate limits?
5. DECISION: approve/reject/modify

Continuous Monitoring (every 100ms):
─────────────────────────────────────
1. READ tsar:positions:current → recalculate risk metrics
2. READ tsar:market:*:latest → update unrealized P&L
3. WRITE tsar:positions:risk → updated risk metrics
4. CHECK against tsar:risk:limits
5. IF violation → WRITE tsar:risk:violations, tsar:risk:circuit_breaker
6. IF critical → PAUSE all strategies

Position Update (on every fill):
────────────────────────────────
Rust fills order
    → WRITE tsar:positions:current (HSET atomic update)
    → WRITE tsar:pnl:daily (HINCRBY)
    → WRITE tsar:signals:processed (LPUSH)
    → Risk Governor reads updated state on next cycle
```

### 13.4 Audit Trail Architecture

```
AUDIT TRAIL:
━━━━━━━━━━━━

Every state-changing operation is logged:

┌─────────────────────────────────────────────────────────────────┐
│ AUDIT EVENT TYPES                                               │
│                                                                 │
│ TRADE_EVENTS:                                                   │
│   trade.signal_generated    — Strategy agent creates signal     │
│   trade.signal_received     — Execution agent picks up signal   │
│   trade.order_placed        — Order sent to exchange            │
│   trade.order_filled        — Fill received                     │
│   trade.order_rejected      — Order rejected                    │
│   trade.position_updated    — Position changed                  │
│   trade.reflection_added    — Post-trade reflection             │
│   trade.outcome_graded      — Outcome grade assigned            │
│                                                                 │
│ RISK_EVENTS:                                                    │
│   risk.limit_set            — Risk limit configured             │
│   risk.limit_breached       — Limit was hit                     │
│   risk.circuit_breaker      — Circuit breaker triggered         │
│   risk.pause_activated      — Trading paused                    │
│   risk.pause_released       — Trading resumed                   │
│                                                                 │
│ STRATEGY_EVENTS:                                                │
│   strategy.created          — New strategy genome               │
│   strategy.activated        — Moved to live                     │
│   strategy.retired          — Strategy retired                  │
│   strategy.mutated          — Genome mutated                    │
│   strategy.gate_checked     — Performance gate evaluated        │
│                                                                 │
│ LEARNING_EVENTS:                                                │
│   pattern.discovered        — New pattern found                 │
│   pattern.validated         — Pattern confirmed                 │
│   pattern.deprecated        — Pattern retired                   │
│   lesson.created            — New lesson                        │
│   lesson.applied            — Lesson used in decision           │
│   lesson.violated           — Lesson ignored                    │
│                                                                 │
│ SYSTEM_EVENTS:                                                  │
│   system.startup            — System started                    │
│   system.shutdown           — System stopped                    │
│   system.config_changed     — Configuration updated             │
│   system.backup_completed   — Backup finished                   │
│   system.compaction_run     — Data compaction executed           │
└─────────────────────────────────────────────────────────────────┘

AUDIT STORAGE:
• SQLite: trades_audit_log table (trades.db)
• Redis: tsar:signals:processed (recent signal audit)
• File: daily audit log rotation (audit/YYYY-MM-DD.jsonl)

AUDIT ENTRY FORMAT (JSONL):
{
    "event_id": "evt_ulid",
    "timestamp": "2026-07-24T00:45:00.000Z",
    "event_type": "trade.order_filled",
    "agent": "execution_agent",
    "trade_id": "trade_ulid",
    "details": {
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 100,
        "fill_price": 185.50,
        "slippage_bps": 2.5
    },
    "state_before": {...},
    "state_after": {...},
    "checksum": "sha256:..."
}
```

### 13.5 Backup and Recovery Strategy

```
BACKUP STRATEGY:
━━━━━━━━━━━━━━━

┌─────────────────────────────────────────────────────────────────┐
│ BACKUP TIERS                                                    │
│                                                                 │
│ TIER 1: Real-time (every write)                                 │
│ • SQLite WAL mode — WAL file is the backup                      │
│ • Rust WAL buffer — append-only, replayable                     │
│ • Redis AOF (append-only file) — enabled                        │
│                                                                 │
│ TIER 2: Hourly snapshots                                        │
│ • SQLite: .backup command (online, non-blocking)                │
│ • Redis: BGSAVE (background fork)                               │
│ • ChromaDB: data directory snapshot                             │
│ • Location: local /backups/hourly/                              │
│ • Retention: 24 hours                                           │
│                                                                 │
│ TIER 3: Daily backups                                           │
│ • Full database backup (all SQLite files)                       │
│ • Redis RDB snapshot                                            │
│ • ChromaDB full export                                          │
│ • YAML genome files                                             │
│ • Location: local /backups/daily/ + remote S3                   │
│ • Retention: 30 days local, 1 year remote                       │
│                                                                 │
│ TIER 4: Weekly full backups                                     │
│ • Complete system state                                         │
│ • All databases, configs, genomes                               │
│ • Location: remote S3 + secondary region                        │
│ • Retention: 1 year                                             │
└─────────────────────────────────────────────────────────────────┘

RECOVERY PROCEDURES:
━━━━━━━━━━━━━━━━━━━

Scenario 1: SQLite corruption
─────────────────────────────
1. Stop all writers
2. .recover command on corrupted database
3. If recovery fails, restore from latest hourly backup
4. Replay WAL entries from Rust buffer since backup
5. Verify data integrity (row counts, checksums)
6. Resume operations

Scenario 2: Redis data loss
──────────────────────────
1. Redis loads from AOF on restart (automatic)
2. If AOF corrupted, load from latest RDB snapshot
3. Rebuild real-time state from SQLite:
   - Regime: re-run HMM on latest market data
   - Positions: rebuild from trades.db (open positions)
   - P&L: recalculate from trades.db
4. Verify state consistency

Scenario 3: ChromaDB loss
─────────────────────────
1. ChromaDB is rebuildable from SQLite source data
2. Run full re-embedding pipeline:
   - Embed all active patterns from patterns.db
   - Embed all active lessons from lessons.db
   - Embed recent trade theses from trades.db
3. Verify vector counts match SQLite counts

Scenario 4: Complete system recovery
────────────────────────────────────
1. Restore SQLite databases from weekly backup
2. Restore Redis from RDB snapshot
3. Restore ChromaDB from data directory backup
4. Replay any available WAL entries
5. Run consistency checks across all stores
6. Rebuild any missing FTS5 indexes
7. Resume with conservative risk limits for 24h

INTEGRITY CHECKS:
━━━━━━━━━━━━━━━━
• Daily: PRAGMA integrity_check on all SQLite databases
• Daily: Redis PING + key count verification
• Weekly: Cross-store consistency check (trade counts match across stores)
• Monthly: Full backup restoration test (on staging)
```

---

## 14. Data Flow Diagrams

### 14.1 Trade Lifecycle

```
TRADE LIFECYCLE — END TO END:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Market Data ──────────────────────────────────────────────────────┐
    │                                                             │
    ▼                                                             │
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐    │
│ Regime Engine│───►│ Strategy     │───►│ Risk Governor    │    │
│ (Rust→Redis) │    │ Agent        │    │ (pre-trade)      │    │
│              │    │ (Python)     │    │                  │    │
│ HMM model    │    │              │    │ Check:           │    │
│ updates      │    │ Reads:       │    │ • Position limits│    │
│ tsar:regime: │    │ • regime     │    │ • Daily loss     │    │
│ current      │    │ • patterns   │    │ • Correlation    │    │
│              │    │ • lessons    │    │ • Regime fit     │    │
│              │    │ • positions  │    │                  │    │
│              │    │              │    │ APPROVE/REJECT   │    │
│              │    │ Writes:      │    │                  │    │
│              │    │ • signal     │    │ Writes:          │    │
│              │    │   to Redis   │    │ • risk:state     │    │
│              │    │   queue      │    │                  │    │
└──────────────┘    └──────────────┘    └────────┬─────────┘    │
                                                 │               │
                                          APPROVED│               │
                                                 ▼               │
                                    ┌──────────────────┐         │
                                    │ Execution Agent   │         │
                                    │ (Rust)           │         │
                                    │                  │         │
                                    │ Places order     │         │
                                    │ Monitors fills   │         │
                                    │ Computes slippage│         │
                                    └────────┬─────────┘         │
                                             │                   │
                                      FILL RECEIVED              │
                                             │                   │
                          ┌──────────────────┼────────────┐      │
                          ▼                  ▼            ▼      │
                   ┌────────────┐    ┌────────────┐ ┌─────────┐ │
                   │ trades.db  │    │ Redis      │ │ Audit   │ │
                   │ (SQLite)   │    │ positions  │ │ Log     │ │
                   │            │    │ pnl        │ │         │ │
                   │ • trade    │    │ risk       │ │         │ │
                   │   record   │    │            │ │         │ │
                   │ • snapshot │    └────────────┘ └─────────┘ │
                   └──────┬─────┘                               │
                          │                                      │
                   POST-TRADE                                   │
                          │                                      │
                          ▼                                      │
                   ┌────────────┐    ┌────────────┐             │
                   │ Reflection │───►│ Learning   │             │
                   │ Agent      │    │ Agent      │             │
                   │            │    │            │             │
                   │ • Grade    │    │ • Pattern  │             │
                   │ • Reflect  │    │   extract  │             │
                   │ • Lessons  │    │ • Lesson   │             │
                   │            │    │   distill  │             │
                   └────────────┘    └──────┬─────┘             │
                                           │                    │
                                    ┌──────┼──────┐             │
                                    ▼      ▼      ▼             │
                              ┌────────┐┌─────┐┌──────┐        │
                              │patterns││lessons││ChromaDB│      │
                              │.db     ││.db   ││(embed)│       │
                              └────────┘└─────┘└──────┘        │
                                                               │
Market Data ──────────────────────────────────────────────────────┘
```

### 14.2 Strategy Evolution

```
STRATEGY EVOLUTION CYCLE:
━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐               │
│  │ Candidate│────►│ Paper    │────►│ Live     │               │
│  │          │     │ Trading  │     │          │               │
│  └──────────┘     └────┬─────┘     └────┬─────┘               │
│                        │                 │                      │
│                   Gates fail        Underperforms               │
│                        │                 │                      │
│                        ▼                 ▼                      │
│                   ┌──────────┐     ┌──────────┐               │
│                   │ Dead     │     │ Retired  │               │
│                   │          │     │          │               │
│                   └──────────┘     └────┬─────┘               │
│                                         │                      │
│                                    Mutation                   │
│                                    by Learning Agent           │
│                                         │                      │
│                                         ▼                      │
│                                    ┌──────────┐               │
│                                    │ New      │               │
│                                    │ Candidate│               │
│                                    │ (child)  │               │
│                                    └──────────┘               │
│                                                                 │
│  DATA STORES INVOLVED:                                          │
│  • strategies.db: genome YAML, performance, mutations          │
│  • trades.db: trade outcomes per strategy                      │
│  • Redis tsar:strategy:*:state: real-time performance          │
│  • Redis tsar:strategy:leaderboard: ranking                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 15. Implementation Roadmap

### Phase 1: Foundation (Week 1-2)

```
□ SQLite databases (all 5 schemas)
  □ trades.db with full schema + triggers
  □ strategies.db with genome + performance tables
  □ patterns.db with pattern + observation tables
  □ lessons.db with FTS5 indexes
  □ Set WAL mode, configure pragmas
  
□ Redis key structure
  □ Initialize all key prefixes
  □ Set up TTL policies
  □ Test atomic operations
  
□ Rust ingestion engine
  □ WAL buffer implementation
  □ Trade ingestion pipeline
  □ Position state management
  
□ Python data access layer
  □ Database connection pooling
  □ Read/write abstractions
  □ Transaction management
```

### Phase 2: Intelligence (Week 3-4)

```
□ ChromaDB setup
  □ Collection creation
  □ Embedding pipeline
  □ Query API
  
□ Pattern discovery pipeline
  □ Feature extraction
  □ Clustering algorithms
  □ Backtest validation
  
□ Lesson archive system
  □ Lesson creation from reflections
  □ FTS5 search integration
  □ Violation tracking
  
□ Session memory manager
  □ Context prioritization
  □ Hot/warm/cold layer loading
  □ Token budget management
```

### Phase 3: Operations (Week 5-6)

```
□ Compaction engine
  □ Scheduled compaction jobs
  □ Survival rules implementation
  □ Archive pipeline
  
□ Backup system
  □ Tier 1-4 backup procedures
  □ Recovery testing
  □ Integrity checks
  
□ Audit trail
  □ Event logging system
  □ Cross-store consistency checks
  □ Audit query API
  
□ Monitoring
  □ Database health checks
  □ Redis memory monitoring
  □ ChromaDB collection stats
  □ Query performance tracking
```

---

## Appendix A: File Layout

```
trading-agent/
├── data/
│   ├── trades.db                    # Trade Memory
│   ├── strategies.db                # Strategy Genomes
│   ├── patterns.db                  # Pattern Library
│   ├── lessons.db                   # Lesson Archive
│   ├── chromadb/                    # Vector store
│   └── backups/
│       ├── hourly/
│       ├── daily/
│       └── weekly/
│
├── strategy_genomes/                # YAML genome files
│   ├── aapl_mean_reversion_v3.yaml
│   ├── momentum_breakout_v2.yaml
│   └── ...
│
├── journals/                        # Trade journals
│   ├── daily/
│   │   └── 2026-07-24.md
│   ├── weekly/
│   │   └── 2026-W30.md
│   └── monthly/
│       └── 2026-07.md
│
├── audit/                           # Audit logs
│   └── 2026-07-24.jsonl
│
├── src/
│   ├── rust/
│   │   ├── ingestion/               # Market data ingestion
│   │   ├── risk/                    # Risk calculations
│   │   └── wal/                     # Write-ahead log
│   │
│   └── python/
│       ├── db/                      # Database access layer
│       ├── agents/                  # Agent implementations
│       ├── learning/                # Pattern discovery, lessons
│       ├── search/                  # FTS5 + vector search
│       └── compaction/              # Data compaction
│
└── architecture/
    └── DATA_ARCHITECTURE.md         # This document
```

---

## Appendix B: Technology Versions

| Component | Version | Notes |
|-----------|---------|-------|
| SQLite | 3.40+ | Required for FTS5, WAL2 |
| Redis | 7.0+ | For hash field TTL, list operations |
| ChromaDB | 0.4+ | Vector store |
| sentence-transformers | 2.2+ | Embedding generation |
| Python | 3.11+ | Performance, typing |
| Rust | 1.70+ | Latest stable |
| rusqlite | 0.31+ | SQLite bindings for Rust |

---

*End of Data Architecture Document*
