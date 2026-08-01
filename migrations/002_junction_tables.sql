-- ============================================================
-- TSAR — Migration 002: Junction Tables for JSON Columns
-- Normalizes JSON-in-column anti-pattern to proper junction tables
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────
-- trade ↔ lessons junction table
-- Replaces: trade_records.lessons (JSON array of lesson IDs)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trade_lessons (
    trade_id        TEXT NOT NULL,
    lesson_id       TEXT NOT NULL,
    relevance       REAL DEFAULT 1.0,       -- 0-1, how relevant this lesson is to this trade
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    PRIMARY KEY (trade_id, lesson_id),
    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id) ON DELETE CASCADE,
    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_trade_lessons_lesson ON trade_lessons(lesson_id);

-- ─────────────────────────────────────────────────────────────
-- trade ↔ patterns junction table
-- Replaces: trade_records.pattern_matches (JSON array of pattern IDs)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trade_patterns (
    trade_id        TEXT NOT NULL,
    pattern_id      TEXT NOT NULL,
    match_score     REAL DEFAULT 0.0,       -- confidence of the pattern match
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    PRIMARY KEY (trade_id, pattern_id),
    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id) ON DELETE CASCADE,
    FOREIGN KEY (pattern_id) REFERENCES patterns(pattern_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_trade_patterns_pattern ON trade_patterns(pattern_id);

-- ─────────────────────────────────────────────────────────────
-- pattern ↔ example trades junction table
-- Replaces: patterns.example_trade_ids (JSON array of trade_ids)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pattern_example_trades (
    pattern_id      TEXT NOT NULL,
    trade_id        TEXT NOT NULL,
    is_primary      INTEGER DEFAULT 0,      -- 1 if this is a canonical example
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    PRIMARY KEY (pattern_id, trade_id),
    FOREIGN KEY (pattern_id) REFERENCES patterns(pattern_id) ON DELETE CASCADE,
    FOREIGN KEY (trade_id) REFERENCES trade_records(trade_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pattern_example_trades_trade ON pattern_example_trades(trade_id);

-- ─────────────────────────────────────────────────────────────
-- lesson ↔ applicable regimes junction table
-- Replaces: lessons.applicable_regimes (JSON array)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lesson_regimes (
    lesson_id       TEXT NOT NULL,
    regime          TEXT NOT NULL,           -- e.g. "trending_up", "ranging", "volatile"
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    PRIMARY KEY (lesson_id, regime),
    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lesson_regimes_regime ON lesson_regimes(regime);

-- ─────────────────────────────────────────────────────────────
-- lesson ↔ applicable symbols junction table
-- Replaces: lessons.applicable_symbols (JSON array)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lesson_symbols (
    lesson_id       TEXT NOT NULL,
    symbol          TEXT NOT NULL,           -- e.g. "BTC/USDT" or "ALL"
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    PRIMARY KEY (lesson_id, symbol),
    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lesson_symbols_symbol ON lesson_symbols(symbol);

-- ─────────────────────────────────────────────────────────────
-- lesson ↔ applicable strategies junction table
-- Replaces: lessons.applicable_strategies (JSON array)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lesson_strategies (
    lesson_id       TEXT NOT NULL,
    strategy_type   TEXT NOT NULL,           -- e.g. "mean_reversion", "momentum"
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    PRIMARY KEY (lesson_id, strategy_type),
    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lesson_strategies_type ON lesson_strategies(strategy_type);


-- ============================================================
-- RECORD MIGRATION
-- ============================================================

INSERT INTO schema_migrations (version, name) VALUES (2, '002_junction_tables');

-- ============================================================
-- ROLLBACK (run manually: sqlite3 tsar.db < migrations/002_junction_tables.sql.rollback)
-- To rollback: reverse the migration by dropping junction tables.
-- Safe: these tables are additive and contain no irreplaceable data
--        (the JSON columns in the original tables still exist).
-- ============================================================
-- DROP TABLE IF EXISTS lesson_strategies;
-- DROP TABLE IF EXISTS lesson_symbols;
-- DROP TABLE IF EXISTS lesson_regimes;
-- DROP TABLE IF EXISTS pattern_example_trades;
-- DROP TABLE IF EXISTS trade_patterns;
-- DROP TABLE IF EXISTS trade_lessons;
-- DELETE FROM schema_migrations WHERE version = 2;
