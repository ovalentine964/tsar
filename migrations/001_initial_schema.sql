-- ============================================================
-- TSAR — Trading Super Agent Regime
-- Migration 001: Initial Schema
-- SQLite 3.40+ | WAL mode | page_size=4096
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- PRAGMA Configuration
-- ─────────────────────────────────────────────────────────────
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;          -- 64MB cache
PRAGMA mmap_size = 268435456;        -- 256MB mmap
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA page_size = 4096;

-- ─────────────────────────────────────────────────────────────
-- Migration tracking
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ============================================================
-- KNOWLEDGE STORE #1: TRADE MEMORY
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- Core trade record (30+ fields)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trade_records (
    trade_id            TEXT PRIMARY KEY,          -- ULID (time-sortable)
    symbol              TEXT NOT NULL,             -- e.g. "BTC/USDT"
    asset_class         TEXT NOT NULL DEFAULT 'crypto',  -- equity|crypto|fx|commodity|fixed_income
    exchange            TEXT,                      -- Binance, NYSE, etc.

    -- Decision context
    strategy_id         TEXT NOT NULL,             -- FK → strategy_genomes
    signal_type         TEXT NOT NULL DEFAULT 'entry',  -- entry|exit|scale_in|scale_out|stop_hit|take_profit
    signal_score        REAL CHECK(signal_score BETWEEN 0.0 AND 1.0),
    signal_source       TEXT,                      -- which sub-agent/model generated signal

    -- Order details
    side                TEXT NOT NULL CHECK(side IN ('buy','sell','short','cover')),
    order_type          TEXT NOT NULL DEFAULT 'market',  -- market|limit|stop|stop_limit|trailing_stop
    quantity            REAL NOT NULL,
    limit_price         REAL,
    stop_price          REAL,

    -- Execution
    entry_price         REAL,
    exit_price          REAL,
    fill_quantity       REAL,
    slippage_bps        REAL,                      -- basis points vs decision price
    commission          REAL DEFAULT 0.0,
    fill_timestamp      TEXT,                      -- ISO8601 UTC
    latency_ms          INTEGER,                   -- decision-to-fill latency

    -- Position context at time of trade
    position_size_before REAL DEFAULT 0.0,
    position_size_after  REAL DEFAULT 0.0,
    portfolio_heat_before REAL,                    -- % of portfolio at risk
    portfolio_heat_after  REAL,

    -- Market context snapshot
    regime_at_entry     TEXT,                      -- regime classification at entry
    vix_level           REAL,
    market_breadth      REAL,                      -- advance/decline ratio
    sector_momentum     TEXT,                      -- JSON: {sector: z_score}
    volatility_regime   TEXT,                      -- low|normal|high|extreme
    liquidity_score     REAL,                      -- 0-1 scale

    -- Pre-trade analysis
    expected_return     REAL,                      -- model's expected return
    expected_risk       REAL,                      -- model's expected vol
    risk_reward_ratio   REAL,
    confidence          REAL CHECK(confidence BETWEEN 0.0 AND 1.0),
    thesis              TEXT,                      -- human-readable trade thesis
    key_levels          TEXT,                      -- JSON: support/resistance levels

    -- Post-trade outcome (filled after exit)
    status              TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','FILLED','CLOSED','CANCELLED','EXPIRED')),
    realized_pnl        REAL DEFAULT 0.0,
    realized_pnl_pct    REAL DEFAULT 0.0,
    holding_period_hours REAL,
    max_drawdown_during REAL,                      -- worst unrealized loss %
    max_favorable_excursion REAL,                  -- best unrealized gain %
    max_adverse_excursion REAL,                    -- alias for max_drawdown_during

    -- Reflection (filled by Trade Philosopher)
    outcome_grade       TEXT CHECK(outcome_grade IN ('A','B','C','D','F')),
    execution_grade     TEXT CHECK(execution_grade IN ('A','B','C','D','F')),
    reflection          TEXT,                      -- what went right/wrong
    lessons             TEXT,                      -- JSON array of lesson IDs
    pattern_matches     TEXT,                      -- JSON array of pattern IDs

    -- Trading mode
    trading_mode        TEXT NOT NULL DEFAULT 'paper' CHECK(trading_mode IN ('paper','live')),

    -- Metadata
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_deleted          INTEGER DEFAULT 0,         -- soft delete

    FOREIGN KEY (strategy_id) REFERENCES strategy_genomes(strategy_id)
);

-- Indices for common query patterns
CREATE INDEX idx_trades_symbol_time ON trade_records(symbol, created_at DESC);
CREATE INDEX idx_trades_strategy ON trade_records(strategy_id, created_at DESC);
CREATE INDEX idx_trades_regime ON trade_records(regime_at_entry);
CREATE INDEX idx_trades_outcome ON trade_records(outcome_grade, realized_pnl_pct);
CREATE INDEX idx_trades_signal ON trade_records(signal_type, created_at DESC);
CREATE INDEX idx_trades_status ON trade_records(status, created_at DESC);
CREATE INDEX idx_trades_active ON trade_records(is_deleted, position_size_after)
    WHERE position_size_after != 0;
CREATE INDEX idx_trades_date ON trade_records(date(created_at));
CREATE INDEX idx_trades_mode ON trade_records(trading_mode, created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- FTS5 virtual table for trade thesis/reflection search
-- ─────────────────────────────────────────────────────────────
CREATE VIRTUAL TABLE trade_records_fts USING fts5(
    thesis,
    reflection,
    notes,
    content=trade_records,
    content_rowid=rowid,
    tokenize='porter unicode61 remove_diacritics 2'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER trg_trade_records_fts_insert AFTER INSERT ON trade_records BEGIN
    INSERT INTO trade_records_fts(rowid, thesis, reflection, notes)
    VALUES (new.rowid, new.thesis, new.reflection, new.notes);
END;

CREATE TRIGGER trg_trade_records_fts_delete AFTER DELETE ON trade_records BEGIN
    INSERT INTO trade_records_fts(trade_records_fts, rowid, thesis, reflection, notes)
    VALUES ('delete', old.rowid, old.thesis, old.reflection, old.notes);
END;

CREATE TRIGGER trg_trade_records_fts_update AFTER UPDATE ON trade_records BEGIN
    INSERT INTO trade_records_fts(trade_records_fts, rowid, thesis, reflection, notes)
    VALUES ('delete', old.rowid, old.thesis, old.reflection, old.notes);
    INSERT INTO trade_records_fts(rowid, thesis, reflection, notes)
    VALUES (new.rowid, new.thesis, new.reflection, new.notes);
END;

-- ─────────────────────────────────────────────────────────────
-- Trade snapshots — market state at decision time
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trade_snapshots (
    snapshot_id         TEXT PRIMARY KEY,
    trade_id            TEXT NOT NULL,
    snapshot_type       TEXT NOT NULL,              -- decision|entry|exit|periodic

    -- Price data
    bid                 REAL,
    ask                 REAL,
    mid                 REAL,
    last_price          REAL,
    volume_24h          REAL,

    -- Technical indicators
    rsi_14              REAL,
    macd_signal         REAL,
    bb_position         REAL,                      -- position within Bollinger Bands
    atr_14              REAL,
    obv_trend           TEXT,                      -- rising|falling|flat

    -- Order book (Level 2)
    book_depth_bid      TEXT,                      -- JSON: [{price, size}, ...]
    book_depth_ask      TEXT,
    spread_bps          REAL,

    -- Sentiment
    news_sentiment      REAL,                      -- -1 to 1
    social_sentiment    REAL,
    fear_greed_index    REAL,

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id) ON DELETE CASCADE
);

CREATE INDEX idx_snapshots_trade ON trade_snapshots(trade_id, snapshot_type);
CREATE INDEX idx_snapshots_time ON trade_snapshots(created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Trade journal entries — free-form reflection
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trade_journal (
    journal_id          TEXT PRIMARY KEY,
    trade_id            TEXT NOT NULL,
    entry_type          TEXT NOT NULL,              -- pre_thesis|post_mortem|mid_trade|weekly_review
    content             TEXT NOT NULL,              -- markdown content
    mood                TEXT,                       -- confident|uncertain|fearful|greedy|neutral
    cognitive_biases    TEXT,                       -- JSON array of detected biases

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id) ON DELETE CASCADE
);

CREATE INDEX idx_journal_trade ON trade_journal(trade_id);
CREATE INDEX idx_journal_type ON trade_journal(entry_type, created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Audit log for trade change tracking
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trade_audit_log (
    audit_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id            TEXT NOT NULL,
    field_name          TEXT NOT NULL,
    old_value           TEXT,
    new_value           TEXT,
    changed_by          TEXT,                       -- agent name or 'system'
    changed_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_audit_trade ON trade_audit_log(trade_id, changed_at);

-- Trigger: audit critical field changes
CREATE TRIGGER trg_trades_update_audit
AFTER UPDATE ON trade_records
WHEN OLD.realized_pnl IS NOT NEW.realized_pnl
   OR OLD.outcome_grade IS NOT NEW.outcome_grade
   OR OLD.reflection IS NOT NEW.reflection
   OR OLD.execution_grade IS NOT NEW.execution_grade
   OR OLD.status IS NOT NEW.status
BEGIN
    INSERT INTO trade_audit_log (trade_id, field_name, old_value, new_value, changed_by)
    SELECT NEW.trade_id, 'realized_pnl', CAST(OLD.realized_pnl AS TEXT), CAST(NEW.realized_pnl AS TEXT), 'system'
    WHERE OLD.realized_pnl IS NOT NEW.realized_pnl;

    INSERT INTO trade_audit_log (trade_id, field_name, old_value, new_value, changed_by)
    SELECT NEW.trade_id, 'outcome_grade', OLD.outcome_grade, NEW.outcome_grade, 'system'
    WHERE OLD.outcome_grade IS NOT NEW.outcome_grade;

    INSERT INTO trade_audit_log (trade_id, field_name, old_value, new_value, changed_by)
    SELECT NEW.trade_id, 'reflection', OLD.reflection, NEW.reflection, 'system'
    WHERE OLD.reflection IS NOT NEW.reflection;

    INSERT INTO trade_audit_log (trade_id, field_name, old_value, new_value, changed_by)
    SELECT NEW.trade_id, 'execution_grade', OLD.execution_grade, NEW.execution_grade, 'system'
    WHERE OLD.execution_grade IS NOT NEW.execution_grade;

    INSERT INTO trade_audit_log (trade_id, field_name, old_value, new_value, changed_by)
    SELECT NEW.trade_id, 'status', OLD.status, NEW.status, 'system'
    WHERE OLD.status IS NOT NEW.status;
END;

-- Trigger: auto-update updated_at
CREATE TRIGGER trg_trades_updated_at
AFTER UPDATE ON trade_records
BEGIN
    UPDATE trade_records SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
    WHERE trade_id = NEW.trade_id;
END;


-- ============================================================
-- KNOWLEDGE STORE #2: STRATEGY GENOMES
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- Strategy genomes — living strategy definitions
-- ─────────────────────────────────────────────────────────────
CREATE TABLE strategy_genomes (
    strategy_id         TEXT PRIMARY KEY,           -- matches YAML genome.id
    name                TEXT NOT NULL,
    parent_id           TEXT,                       -- parent genome for lineage
    version             INTEGER NOT NULL DEFAULT 1,

    -- Genome content
    thesis              TEXT,                       -- strategy thesis/description
    genome_yaml         TEXT,                       -- full YAML genome (immutable once created)
    genome_hash         TEXT,                       -- SHA-256 of genome_yaml for integrity

    -- Classification
    asset_class         TEXT NOT NULL DEFAULT 'crypto',
    symbols             TEXT,                       -- JSON array
    strategy_type       TEXT,                       -- mean_reversion|momentum|breakout|pairs|stat_arb

    -- Rules
    entry_rules         TEXT,                       -- JSON: entry conditions
    exit_rules          TEXT,                       -- JSON: exit conditions
    risk_params         TEXT,                       -- JSON: risk parameters

    -- Lifecycle
    status              TEXT NOT NULL DEFAULT 'candidate'
                        CHECK(status IN ('candidate','paper','live','paused','retired','dead')),
    activated_at        TEXT,
    retired_at          TEXT,
    retirement_reason   TEXT,

    -- Performance gates tracking
    total_trades        INTEGER DEFAULT 0,
    winning_trades      INTEGER DEFAULT 0,
    total_pnl           REAL DEFAULT 0.0,
    max_drawdown        REAL DEFAULT 0.0,
    profit_factor       REAL DEFAULT 0.0,
    sharpe_ratio        REAL DEFAULT 0.0,
    rolling_sharpe_30d  REAL DEFAULT 0.0,
    win_rate            REAL DEFAULT 0.0,
    avg_holding_hours   REAL DEFAULT 0.0,
    consecutive_losses  INTEGER DEFAULT 0,
    max_consecutive_losses INTEGER DEFAULT 0,

    -- Regime performance
    regime_performance  TEXT,                       -- JSON: {regime: {trades, pnl, win_rate, sharpe}}

    -- Gate status
    gates_passed        INTEGER DEFAULT 0,          -- bitmask of which gates are passing
    gates_evaluated_at  TEXT,

    -- Metadata
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_evolved        TEXT,

    FOREIGN KEY (parent_id) REFERENCES strategy_genomes(strategy_id)
);

CREATE INDEX idx_strat_status ON strategy_genomes(status);
CREATE INDEX idx_strat_parent ON strategy_genomes(parent_id);
CREATE INDEX idx_strat_type ON strategy_genomes(strategy_type, status);
CREATE INDEX idx_strat_sharpe ON strategy_genomes(sharpe_ratio DESC) WHERE status IN ('live', 'paper');

-- FTS5 for strategy search
CREATE VIRTUAL TABLE strategy_genomes_fts USING fts5(
    name,
    thesis,
    strategy_type,
    content=strategy_genomes,
    content_rowid=rowid,
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER trg_strategy_genomes_fts_insert AFTER INSERT ON strategy_genomes BEGIN
    INSERT INTO strategy_genomes_fts(rowid, name, thesis, strategy_type)
    VALUES (new.rowid, new.name, new.thesis, new.strategy_type);
END;

CREATE TRIGGER trg_strategy_genomes_fts_delete AFTER DELETE ON strategy_genomes BEGIN
    INSERT INTO strategy_genomes_fts(strategy_genomes_fts, rowid, name, thesis, strategy_type)
    VALUES ('delete', old.rowid, old.name, old.thesis, old.strategy_type);
END;

CREATE TRIGGER trg_strategy_genomes_fts_update AFTER UPDATE ON strategy_genomes BEGIN
    INSERT INTO strategy_genomes_fts(strategy_genomes_fts, rowid, name, thesis, strategy_type)
    VALUES ('delete', old.rowid, old.name, old.thesis, old.strategy_type);
    INSERT INTO strategy_genomes_fts(rowid, name, thesis, strategy_type)
    VALUES (new.rowid, new.name, new.thesis, new.strategy_type);
END;

-- ─────────────────────────────────────────────────────────────
-- Performance snapshots — periodic performance recording
-- ─────────────────────────────────────────────────────────────
CREATE TABLE strategy_performance (
    snapshot_id         TEXT PRIMARY KEY,
    strategy_id         TEXT NOT NULL,
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,

    -- Returns
    total_return        REAL,
    annualized_return   REAL,
    excess_return       REAL,                      -- vs benchmark

    -- Risk
    volatility          REAL,
    max_drawdown        REAL,
    var_95              REAL,                      -- Value at Risk 95%
    cvar_95             REAL,                      -- Conditional VaR
    sortino_ratio       REAL,
    calmar_ratio        REAL,
    sharpe_ratio        REAL,

    -- Execution quality
    avg_slippage_bps    REAL,
    avg_latency_ms      REAL,
    fill_rate           REAL,                      -- % of signals that filled
    total_trades        INTEGER,
    winning_trades      INTEGER,
    total_pnl           REAL,
    win_rate            REAL,

    -- Attribution
    regime_performance  TEXT,                      -- JSON: {regime: return}
    signal_accuracy     TEXT,                      -- JSON: {signal_type: accuracy}

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (strategy_id) REFERENCES strategy_genomes(strategy_id)
);

CREATE INDEX idx_perf_strategy ON strategy_performance(strategy_id, period_end DESC);

-- ─────────────────────────────────────────────────────────────
-- Mutation history — track evolution
-- ─────────────────────────────────────────────────────────────
CREATE TABLE strategy_mutations (
    mutation_id         TEXT PRIMARY KEY,
    strategy_name       TEXT NOT NULL,              -- human-readable strategy name
    parent_id           TEXT NOT NULL,              -- parent strategy
    child_id            TEXT,                       -- resulting strategy (if spawned)
    version_from        INTEGER NOT NULL,
    version_to          INTEGER NOT NULL,
    mutation_type       TEXT NOT NULL,              -- param_tweak|rule_add|rule_remove|threshold_shift
    change_description  TEXT NOT NULL,              -- what changed
    mutation_detail     TEXT,                       -- JSON: detailed change log
    rationale           TEXT,                       -- why this mutation was attempted
    performance_before  TEXT,                       -- JSON: parent performance snapshot
    performance_after   TEXT,                       -- JSON: child performance snapshot (filled later)
    parent_fitness      REAL,                       -- parent's fitness score at mutation time
    outcome             TEXT,                       -- pending|promoted|retired|rejected

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (parent_id) REFERENCES strategy_genomes(strategy_id),
    FOREIGN KEY (child_id) REFERENCES strategy_genomes(strategy_id)
);

CREATE INDEX idx_mutation_parent ON strategy_mutations(parent_id);
CREATE INDEX idx_mutation_child ON strategy_mutations(child_id);
CREATE INDEX idx_mutation_name ON strategy_mutations(strategy_name, created_at DESC);
CREATE INDEX idx_mutation_type ON strategy_mutations(mutation_type, created_at DESC);


-- ============================================================
-- KNOWLEDGE STORE #4: PATTERN LIBRARY
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- Patterns — discovered market patterns
-- ─────────────────────────────────────────────────────────────
CREATE TABLE patterns (
    pattern_id          TEXT PRIMARY KEY,           -- ULID
    pattern_name        TEXT NOT NULL,              -- human-readable name
    pattern_type        TEXT NOT NULL
                        CHECK(pattern_type IN (
                            'setup', 'failure_mode', 'regime_behavior',
                            'correlation', 'anomaly', 'seasonal',
                            'microstructure', 'sentiment_divergence',
                            'candlestick', 'structural'
                        )),

    -- Pattern definition
    description         TEXT NOT NULL,              -- detailed description
    conditions          TEXT NOT NULL,              -- JSON: structured conditions

    -- Statistical validation
    sample_size         INTEGER DEFAULT 0,          -- how many times observed
    success_rate        REAL,                       -- historical win rate (alias: win_rate)
    avg_return          REAL,                       -- average return when pattern triggers
    avg_pnl_impact      REAL,                       -- average P&L impact
    avg_duration_hours  REAL,                       -- average time to target
    risk_reward         REAL,                       -- average R:R
    expectancy          REAL,                       -- win_rate * avg_win - loss_rate * avg_loss
    sharpe_contribution REAL,                       -- contribution to portfolio Sharpe

    -- Confidence and decay
    confidence          REAL DEFAULT 0.5,           -- 0-1, increases with more samples
    last_validated      TEXT,                       -- last time pattern was confirmed
    last_seen           TEXT,                       -- last time pattern was observed
    decay_rate          REAL DEFAULT 0.01,          -- confidence decay per day without validation
    min_sample_size     INTEGER DEFAULT 10,         -- minimum observations before usable

    -- Visual/embedding
    example_trade_ids   TEXT,                       -- JSON array of trade_ids showing this pattern
    chart_embedding_id  TEXT,                       -- ChromaDB vector ID for chart patterns

    -- Lifecycle
    status              TEXT DEFAULT 'candidate'
                        CHECK(status IN ('candidate','validated','active','deprecated','archived')),
    discovered_by       TEXT,                       -- agent or method that found it
    discovered_at       TEXT NOT NULL,

    -- Metadata
    tags                TEXT,                       -- JSON array of tags
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_patterns_type ON patterns(pattern_type, status);
CREATE INDEX idx_patterns_status ON patterns(status, confidence DESC);
CREATE INDEX idx_patterns_expectancy ON patterns(expectancy DESC) WHERE status = 'active';
CREATE INDEX idx_patterns_last_seen ON patterns(last_seen DESC);

-- FTS5 for pattern search
CREATE VIRTUAL TABLE patterns_fts USING fts5(
    pattern_name,
    description,
    tags,
    content=patterns,
    content_rowid=rowid,
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER trg_patterns_fts_insert AFTER INSERT ON patterns BEGIN
    INSERT INTO patterns_fts(rowid, pattern_name, description, tags)
    VALUES (new.rowid, new.pattern_name, new.description, new.tags);
END;

CREATE TRIGGER trg_patterns_fts_delete AFTER DELETE ON patterns BEGIN
    INSERT INTO patterns_fts(patterns_fts, rowid, pattern_name, description, tags)
    VALUES ('delete', old.rowid, old.pattern_name, old.description, old.tags);
END;

CREATE TRIGGER trg_patterns_fts_update AFTER UPDATE ON patterns BEGIN
    INSERT INTO patterns_fts(patterns_fts, rowid, pattern_name, description, tags)
    VALUES ('delete', old.rowid, old.pattern_name, old.description, old.tags);
    INSERT INTO patterns_fts(rowid, pattern_name, description, tags)
    VALUES (new.rowid, new.pattern_name, new.description, new.tags);
END;

-- ─────────────────────────────────────────────────────────────
-- Pattern observations — individual instances of a pattern
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pattern_observations (
    observation_id      TEXT PRIMARY KEY,
    pattern_id          TEXT NOT NULL,
    trade_id            TEXT,                       -- associated trade (if any)

    -- Observation context
    symbol              TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    timeframe           TEXT,                       -- timeframe where pattern was detected

    -- Market state at observation
    price_at_trigger    REAL,
    regime_at_trigger   TEXT,
    volatility_at_trigger REAL,
    volume_at_trigger   REAL,

    -- Outcome
    outcome             TEXT CHECK(outcome IN ('win','loss','breakeven','pending')),
    pnl_impact          REAL,                       -- P&L impact of this observation
    return_pct          REAL,
    duration_hours      REAL,
    max_adverse         REAL,                       -- max drawdown during trade
    max_favorable       REAL,                       -- max gain during trade

    -- Embedding reference
    embedding_id        TEXT,                       -- ChromaDB vector ID

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (pattern_id) REFERENCES patterns(pattern_id),
    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id)
);

CREATE INDEX idx_obs_pattern ON pattern_observations(pattern_id, observed_at DESC);
CREATE INDEX idx_obs_outcome ON pattern_observations(outcome, return_pct);
CREATE INDEX idx_obs_trade ON pattern_observations(trade_id);

-- ─────────────────────────────────────────────────────────────
-- Pattern relationships
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pattern_relationships (
    relationship_id     TEXT PRIMARY KEY,
    pattern_a_id        TEXT NOT NULL,
    pattern_b_id        TEXT NOT NULL,
    relationship        TEXT NOT NULL
                        CHECK(relationship IN ('co_occurs','precedes','negates','enhances','requires','contradicts')),
    strength            REAL,                       -- correlation strength
    sample_size         INTEGER,

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (pattern_a_id) REFERENCES patterns(pattern_id),
    FOREIGN KEY (pattern_b_id) REFERENCES patterns(pattern_id)
);

CREATE INDEX idx_rel_a ON pattern_relationships(pattern_a_id);
CREATE INDEX idx_rel_b ON pattern_relationships(pattern_b_id);


-- ============================================================
-- KNOWLEDGE STORE #5: LESSON ARCHIVE
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- Lessons — distilled wisdom from trade outcomes
-- ─────────────────────────────────────────────────────────────
CREATE TABLE lessons (
    lesson_id           TEXT PRIMARY KEY,           -- ULID
    trade_id            TEXT,                       -- source trade (FK)
    title               TEXT NOT NULL,              -- concise lesson title

    -- Classification
    lesson_type         TEXT NOT NULL
                        CHECK(lesson_type IN (
                            'WIN', 'LOSS', 'MISTAKE', 'INSIGHT',
                            'trade_mistake', 'strategy_insight', 'market_observation',
                            'risk_lesson', 'execution_improvement', 'psychological',
                            'system_improvement', 'regime_insight', 'pattern_insight'
                        )),
    category            TEXT
                        CHECK(category IN (
                            'ENTRY', 'EXIT', 'SIZING', 'TIMING', 'REGIME',
                            NULL
                        )),
    severity            TEXT DEFAULT 'moderate'
                        CHECK(severity IN ('critical','important','moderate','minor')),

    -- Content
    description         TEXT NOT NULL,              -- full lesson description
    action_item         TEXT,                       -- actionable takeaway
    content             TEXT,                       -- full lesson in markdown (alias)

    -- Source context
    source_strategy_id  TEXT,                       -- related strategy
    source_pattern_id   TEXT,                       -- related pattern
    source_event        TEXT,                       -- what triggered this lesson

    -- Applicability
    applicable_regimes  TEXT,                       -- JSON array of regimes where relevant
    applicable_symbols  TEXT,                       -- JSON array of symbols (or 'ALL')
    applicable_strategies TEXT,                     -- JSON array of strategy types

    -- Actionability
    action_required     INTEGER DEFAULT 0,          -- does this require a system change?
    action_taken        TEXT,                       -- what was done about it
    action_status       TEXT DEFAULT 'pending'
                        CHECK(action_status IN ('pending','in_progress','completed','dismissed')),

    -- Reinforcement
    applied             INTEGER DEFAULT 0,          -- has this lesson been applied?
    times_applied       INTEGER DEFAULT 0,          -- how many times lesson was referenced
    times_violated      INTEGER DEFAULT 0,          -- how many times lesson was ignored
    last_applied        TEXT,
    last_violated       TEXT,
    violation_impact    REAL,                       -- total P&L impact of violations

    -- Confidence and decay
    confidence          REAL DEFAULT 0.8,           -- how confident we are in this lesson
    validated_count     INTEGER DEFAULT 1,          -- times independently confirmed

    -- Metadata
    discovered_by       TEXT,                       -- which agent discovered this
    discovered_at       TEXT NOT NULL,
    tags                TEXT,                       -- JSON array
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_archived         INTEGER DEFAULT 0,

    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id)
);

CREATE INDEX idx_lessons_type ON lessons(lesson_type, severity);
CREATE INDEX idx_lessons_category ON lessons(category);
CREATE INDEX idx_lessons_source_strategy ON lessons(source_strategy_id);
CREATE INDEX idx_lessons_action ON lessons(action_status) WHERE action_required = 1;
CREATE INDEX idx_lessons_applied ON lessons(times_applied DESC);
CREATE INDEX idx_lessons_violated ON lessons(times_violated DESC, violation_impact);
CREATE INDEX idx_lessons_discovered ON lessons(discovered_at DESC);

-- ─────────────────────────────────────────────────────────────
-- FTS5 full-text search index for lessons
-- ─────────────────────────────────────────────────────────────
CREATE VIRTUAL TABLE lessons_fts USING fts5(
    title,
    description,
    action_item,
    content,
    tags,
    content=lessons,
    content_rowid=rowid,
    tokenize='porter unicode61 remove_diacritics 2'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER trg_lessons_fts_insert AFTER INSERT ON lessons BEGIN
    INSERT INTO lessons_fts(rowid, title, description, action_item, content, tags)
    VALUES (new.rowid, new.title, new.description, new.action_item, new.content, new.tags);
END;

CREATE TRIGGER trg_lessons_fts_delete AFTER DELETE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, title, description, action_item, content, tags)
    VALUES ('delete', old.rowid, old.title, old.description, old.action_item, old.content, old.tags);
END;

CREATE TRIGGER trg_lessons_fts_update AFTER UPDATE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, title, description, action_item, content, tags)
    VALUES ('delete', old.rowid, old.title, old.description, old.action_item, old.content, old.tags);
    INSERT INTO lessons_fts(rowid, title, description, action_item, content, tags)
    VALUES (new.rowid, new.title, new.description, new.action_item, new.content, new.tags);
END;

-- ─────────────────────────────────────────────────────────────
-- Lesson applications — when lessons are referenced
-- ─────────────────────────────────────────────────────────────
CREATE TABLE lesson_applications (
    application_id      TEXT PRIMARY KEY,
    lesson_id           TEXT NOT NULL,
    trade_id            TEXT,                       -- trade where lesson was applied
    strategy_name       TEXT,                       -- strategy that applied it
    context             TEXT NOT NULL,              -- how the lesson was used
    parameter_changed   TEXT,                       -- what parameter was changed
    old_value           TEXT,                       -- previous value
    new_value           TEXT,                       -- new value
    outcome             TEXT,                       -- what happened
    impact_measured     REAL,                       -- measured impact of application
    agent               TEXT,                       -- which agent applied it

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    applied_at          TEXT,                       -- when the lesson was actually applied

    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id),
    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id)
);

CREATE INDEX idx_app_lesson ON lesson_applications(lesson_id, created_at DESC);
CREATE INDEX idx_app_trade ON lesson_applications(trade_id);

-- ─────────────────────────────────────────────────────────────
-- Lesson violations — when lessons were ignored
-- ─────────────────────────────────────────────────────────────
CREATE TABLE lesson_violations (
    violation_id        TEXT PRIMARY KEY,
    lesson_id           TEXT NOT NULL,
    trade_id            TEXT NOT NULL,
    violation_description TEXT NOT NULL,             -- what was violated
    pnl_impact          REAL,                       -- impact of the violation
    reason_given        TEXT,                       -- why the lesson was ignored
    occurred_at         TEXT NOT NULL,

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id),
    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id)
);

CREATE INDEX idx_violation_lesson ON lesson_violations(lesson_id, created_at DESC);
CREATE INDEX idx_violation_trade ON lesson_violations(trade_id);


-- ============================================================
-- IMPROVEMENT MEASUREMENT
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- Improvement baselines — recorded after first 30 trades
-- ─────────────────────────────────────────────────────────────
CREATE TABLE improvement_baselines (
    metric_name         TEXT PRIMARY KEY,
    value               REAL NOT NULL,
    std_dev             REAL,
    ci_lower            REAL,                       -- 95% confidence interval lower
    ci_upper            REAL,                       -- 95% confidence interval upper
    sample_size         INTEGER NOT NULL,
    recorded_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    raw_values_json     TEXT                        -- JSON array of raw metric values
);

-- ─────────────────────────────────────────────────────────────
-- Improvement snapshots — daily metric tracking
-- ─────────────────────────────────────────────────────────────
CREATE TABLE improvement_snapshots (
    snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name         TEXT NOT NULL,
    value               REAL NOT NULL,
    trend               TEXT,                       -- improving|stable|declining
    trend_slope         REAL,
    baseline_value      REAL,
    delta_from_baseline REAL,
    p_value             REAL,                       -- Welch's t-test p-value
    is_significant      INTEGER DEFAULT 0,          -- p < 0.05
    verdict             TEXT,                       -- significant_improvement|no_change|significant_decline
    computed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    UNIQUE(metric_name, computed_at)
);

CREATE INDEX idx_imp_snapshot_metric ON improvement_snapshots(metric_name, computed_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Flywheel health history — composite health tracking
-- ─────────────────────────────────────────────────────────────
CREATE TABLE flywheel_health_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    health_score        REAL NOT NULL,              -- 0-1 composite score
    classification      TEXT NOT NULL,              -- healthy|stalling|broken
    component_scores_json TEXT,                     -- JSON: per-metric scores
    recommendation      TEXT,                       -- actionable recommendation
    computed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_flywheel_time ON flywheel_health_history(computed_at DESC);


-- ============================================================
-- REGIME HISTORY
-- ============================================================

CREATE TABLE regime_history (
    snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date       TEXT NOT NULL,
    regime_probs        TEXT NOT NULL,              -- JSON: {regime: probability}
    dominant_regime     TEXT NOT NULL,
    confidence          REAL,
    indicators          TEXT,                       -- JSON: raw indicator values
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_regime_date ON regime_history(snapshot_date DESC);
CREATE INDEX idx_regime_dominant ON regime_history(dominant_regime, snapshot_date DESC);


-- ============================================================
-- RECORD MIGRATION
-- ============================================================

INSERT INTO schema_migrations (version, name) VALUES (1, '001_initial_schema');
