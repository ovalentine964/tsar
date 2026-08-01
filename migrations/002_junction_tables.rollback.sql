-- ============================================================
-- TSAR — Rollback Migration 002: Junction Tables
-- Run: sqlite3 data/tsar.db < migrations/002_junction_tables.rollback.sql
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS lesson_strategies;
DROP TABLE IF EXISTS lesson_symbols;
DROP TABLE IF EXISTS lesson_regimes;
DROP TABLE IF EXISTS pattern_example_trades;
DROP TABLE IF EXISTS trade_patterns;
DROP TABLE IF EXISTS trade_lessons;

DELETE FROM schema_migrations WHERE version = 2;
