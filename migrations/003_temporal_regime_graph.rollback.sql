-- ============================================================
-- TSAR — Rollback Migration 003: Temporal Regime Transition Graph
-- Run: sqlite3 data/tsar.db < migrations/003_temporal_regime_graph.rollback.sql
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS regime_transition_edges;
DROP TABLE IF EXISTS regime_transitions;

DELETE FROM schema_migrations WHERE version = 3;
