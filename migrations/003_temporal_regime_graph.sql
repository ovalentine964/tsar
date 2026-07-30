-- ============================================================
-- TSAR — Migration 003: Temporal Regime Transition Graph
-- Adds tables for regime transition observations and aggregated edges
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────
-- Raw regime transition observations
-- Each row = one observed transition from regime A → regime B
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS regime_transitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_regime     TEXT NOT NULL,
    to_regime       TEXT NOT NULL,
    duration_hours  REAL DEFAULT 0.0,       -- time spent in from_regime before transition
    asset           TEXT NOT NULL DEFAULT 'GLOBAL',
    observed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_rt_from ON regime_transitions(from_regime, asset);
CREATE INDEX IF NOT EXISTS idx_rt_to ON regime_transitions(to_regime, asset);
CREATE INDEX IF NOT EXISTS idx_rt_asset ON regime_transitions(asset);
CREATE INDEX IF NOT EXISTS idx_rt_time ON regime_transitions(observed_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Aggregated regime transition edges (Markov chain)
-- Pre-computed probabilities from raw observations
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS regime_transition_edges (
    from_regime         TEXT NOT NULL,
    to_regime           TEXT NOT NULL,
    probability         REAL NOT NULL DEFAULT 0.0,  -- P(to | from, asset)
    observation_count   INTEGER NOT NULL DEFAULT 0,
    avg_duration_hours  REAL DEFAULT 0.0,
    min_duration_hours  REAL DEFAULT 0.0,
    max_duration_hours  REAL DEFAULT 0.0,
    last_observed       TEXT,
    asset               TEXT NOT NULL DEFAULT 'GLOBAL',

    PRIMARY KEY (from_regime, to_regime, asset)
);

CREATE INDEX IF NOT EXISTS idx_rte_from ON regime_transition_edges(from_regime, asset);
CREATE INDEX IF NOT EXISTS idx_rte_to ON regime_transition_edges(to_regime, asset);


-- ============================================================
-- RECORD MIGRATION
-- ============================================================

INSERT INTO schema_migrations (version, name) VALUES (3, '003_temporal_regime_graph');
