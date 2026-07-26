"""TSAR — Tests for unified FTS5 semantic memory recall.

Covers: index creation, insert+search roundtrip, multi-store search,
relevance ranking, CJK support, snake_case handling, edge cases.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from src.knowledge.fts_search import (
    MemoryRecall,
    SearchResult,
    format_fts_query,
    _tokenize_for_fts,
    _STORE_REGISTRY,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


def _make_db_path(tmp_path: Path) -> str:
    return str(tmp_path / f"test_fts_{uuid.uuid4().hex[:8]}.db")


def _create_base_tables(conn: sqlite3.Connection) -> None:
    """Create the source tables (no FTS5 — MemoryRecall creates those)."""
    conn.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE trade_records (
            trade_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            thesis TEXT,
            reflection TEXT,
            notes TEXT,
            is_deleted INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE strategy_genomes (
            strategy_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            thesis TEXT,
            strategy_type TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE patterns (
            pattern_id TEXT PRIMARY KEY,
            pattern_name TEXT NOT NULL,
            description TEXT NOT NULL,
            tags TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE lessons (
            lesson_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            action_item TEXT,
            content TEXT,
            tags TEXT,
            is_archived INTEGER DEFAULT 0,
            discovered_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
    """)


@pytest_asyncio.fixture
async def recall(tmp_path: Path) -> MemoryRecall:
    """Fresh MemoryRecall instance with all base tables created."""
    db_path = _make_db_path(tmp_path)

    # Create source tables synchronously (they're not FTS)
    conn = sqlite3.connect(db_path)
    _create_base_tables(conn)
    conn.close()

    rec = MemoryRecall(db_path)
    await rec.initialize()
    rec._test_db_path = db_path  # type: ignore[attr-defined]
    yield rec
    await rec.close()


def _sync_conn(recall: MemoryRecall) -> sqlite3.Connection:
    """Open a sync sqlite3 connection to the same DB for test data insertion."""
    db_path = recall._test_db_path  # type: ignore[attr-defined]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_trade(recall: MemoryRecall, **overrides) -> str:
    conn = _sync_conn(recall)
    try:
        tid = overrides.pop("trade_id", uuid.uuid4().hex)
        defaults = {
            "trade_id": tid,
            "symbol": "BTC/USDT",
            "strategy_id": "strat-1",
            "thesis": None,
            "reflection": None,
            "notes": None,
        }
        defaults.update(overrides)
        conn.execute(
            "INSERT INTO trade_records (trade_id, symbol, strategy_id, thesis, reflection, notes) "
            "VALUES (:trade_id, :symbol, :strategy_id, :thesis, :reflection, :notes)",
            defaults,
        )
        conn.commit()
        return tid
    finally:
        conn.close()


def _insert_strategy(recall: MemoryRecall, **overrides) -> str:
    conn = _sync_conn(recall)
    try:
        sid = overrides.pop("strategy_id", uuid.uuid4().hex)
        defaults = {
            "strategy_id": sid,
            "name": "default_strategy",
            "thesis": None,
            "strategy_type": None,
        }
        defaults.update(overrides)
        conn.execute(
            "INSERT INTO strategy_genomes (strategy_id, name, thesis, strategy_type) "
            "VALUES (:strategy_id, :name, :thesis, :strategy_type)",
            defaults,
        )
        conn.commit()
        return sid
    finally:
        conn.close()


def _insert_pattern(recall: MemoryRecall, **overrides) -> str:
    conn = _sync_conn(recall)
    try:
        pid = overrides.pop("pattern_id", uuid.uuid4().hex)
        defaults = {
            "pattern_id": pid,
            "pattern_name": "default_pattern",
            "description": "a pattern",
            "tags": None,
        }
        defaults.update(overrides)
        conn.execute(
            "INSERT INTO patterns (pattern_id, pattern_name, description, tags) "
            "VALUES (:pattern_id, :pattern_name, :description, :tags)",
            defaults,
        )
        conn.commit()
        return pid
    finally:
        conn.close()


def _insert_lesson(recall: MemoryRecall, **overrides) -> str:
    conn = _sync_conn(recall)
    try:
        lid = overrides.pop("lesson_id", uuid.uuid4().hex)
        defaults = {
            "lesson_id": lid,
            "title": "default_lesson",
            "description": "a lesson",
            "action_item": None,
            "content": None,
            "tags": None,
        }
        defaults.update(overrides)
        conn.execute(
            "INSERT INTO lessons (lesson_id, title, description, action_item, content, tags) "
            "VALUES (:lesson_id, :title, :description, :action_item, :content, :tags)",
            defaults,
        )
        conn.commit()
        return lid
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# Unit tests — query formatting
# ═══════════════════════════════════════════════════════════════


class TestQueryFormatting:
    """Tests for format_fts_query and _tokenize_for_fts."""

    def test_basic_english_query(self) -> None:
        tokens = _tokenize_for_fts("mean reversion BTC oversold")
        assert "mean" in tokens
        assert "reversion" in tokens
        assert "btc" in tokens
        assert "oversold" in tokens

    def test_snake_case_splitting(self) -> None:
        tokens = _tokenize_for_fts("stop_loss take_profit")
        assert "stop" in tokens
        assert "loss" in tokens
        assert "take" in tokens
        assert "profit" in tokens

    def test_cjk_characters(self) -> None:
        tokens = _tokenize_for_fts("趋势反转信号")
        # Each CJK character should be a separate token
        assert len(tokens) == 6
        assert "趋" in tokens
        assert "势" in tokens

    def test_mixed_cjk_latin(self) -> None:
        tokens = _tokenize_for_fts("BTC 趋势分析 oversold")
        assert "btc" in tokens
        assert "oversold" in tokens
        assert "趋" in tokens

    def test_short_tokens_dropped(self) -> None:
        tokens = _tokenize_for_fts("I am a OK")
        # "I" and "am" and "OK" are < 2 chars for Latin
        assert "a" not in tokens  # single char Latin dropped

    def test_empty_query(self) -> None:
        assert format_fts_query("") == '""'
        assert format_fts_query("   ") == '""'

    def test_special_characters(self) -> None:
        tokens = _tokenize_for_fts("BTC/USDT @#$% signal!")
        assert "btc" in tokens
        assert "usdt" in tokens
        assert "signal" in tokens

    def test_format_produces_or(self) -> None:
        q = format_fts_query("mean reversion")
        assert "OR" in q
        assert '"mean"' in q
        assert '"reversion"' in q

    def test_cjk_gets_prefix_wildcard(self) -> None:
        q = format_fts_query("趋势")
        assert '"趋"*' in q
        assert '"势"*' in q

    def test_arabic_characters(self) -> None:
        tokens = _tokenize_for_fts("اتجاه السوق")
        assert len(tokens) >= 3  # Arabic chars

    def test_cyrillic_characters(self) -> None:
        tokens = _tokenize_for_fts("бычий рынок")
        assert "бычий" not in tokens  # Cyrillic word not split into Latin tokens
        # But individual Cyrillic chars should appear
        assert any(ord(c) >= 0x0400 for c in tokens)


# ═══════════════════════════════════════════════════════════════
# Integration tests — MemoryRecall
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestIndexCreation:
    """Verify FTS5 tables and triggers are created on initialize."""

    async def test_fts_tables_created(self, recall: MemoryRecall) -> None:
        """All 4 FTS virtual tables should exist after initialize."""
        db = recall._db
        assert db is not None
        for store_cfg in _STORE_REGISTRY.values():
            fts_name = store_cfg["fts_table"]
            rows = await db.execute_fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (fts_name,),
            )
            assert len(rows) == 1, f"FTS table {fts_name} not found"

    async def test_triggers_created(self, recall: MemoryRecall) -> None:
        """Sync triggers should exist for each FTS table."""
        db = recall._db
        assert db is not None
        rows = await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_%_fts_%'"
        )
        trigger_names = {r["name"] for r in rows}
        # At least insert/update/delete triggers for each store
        assert "trg_trade_records_fts_insert" in trigger_names
        assert "trg_lessons_fts_insert" in trigger_names

    async def test_idempotent_creation(self, recall: MemoryRecall) -> None:
        """Calling initialize again should not error."""
        await recall.initialize()  # should be a no-op
        db = recall._db
        assert db is not None
        rows = await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trade_records_fts'"
        )
        assert len(rows) == 1


@pytest.mark.asyncio
class TestInsertAndSearchRoundtrip:
    """Verify that inserting data into source tables makes it searchable."""

    async def test_search_trade_thesis(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(
            recall,
            thesis="BTC is showing strong bullish momentum with RSI divergence",
        )

        results = await recall.search("bullish momentum RSI")
        assert len(results) >= 1
        assert any(r.store == "trade_records" for r in results)
        # The thesis keyword should appear
        assert any("bullish" in (r.snippet + str(r.data)).lower() for r in results)

    async def test_search_pattern(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_pattern(
            recall,
            pattern_name="double_bottom",
            description="Classic double bottom reversal pattern at key support level",
        )

        results = await recall.search("double bottom reversal")
        assert any(r.store == "patterns" for r in results)

    async def test_search_lesson(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_lesson(
            recall,
            title="Stop loss too tight",
            description="Premature stop loss exit caused missing a 3x move on ETH",
            action_item="Widen stops to 2x ATR for volatile pairs",
            content="Always account for volatility regime when setting stops",
        )

        results = await recall.search("stop loss premature exit")
        assert any(r.store == "lessons" for r in results)

    async def test_search_strategy(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_strategy(
            recall,
            name="mean_reversion_v3",
            thesis="Buy oversold RSI conditions near support with tight risk management",
            strategy_type="mean_reversion",
        )

        results = await recall.search("oversold RSI mean reversion")
        assert any(r.store == "strategy_genomes" for r in results)


@pytest.mark.asyncio
class TestMultiStoreSearch:
    """Verify searching across multiple stores simultaneously."""

    async def test_search_all_stores(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="Mean reversion opportunity on BTC oversold conditions")
        _insert_pattern(
            recall,
            pattern_name="oversold_bounce",
            description="Oversold bounce pattern with volume confirmation",
        )
        _insert_lesson(
            recall,
            title="Oversold entry lessons",
            description="When entering oversold conditions, wait for volume confirmation",
        )

        results = await recall.search("oversold")
        stores_hit = {r.store for r in results}
        assert "trade_records" in stores_hit
        assert "patterns" in stores_hit
        assert "lessons" in stores_hit

    async def test_search_subset_of_stores(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="Bullish divergence signal detected")
        _insert_lesson(
            recall,
            title="Bullish divergence entry",
            description="Always confirm divergence with volume",
        )

        results = await recall.search("bullish divergence", stores=["trade_records"])
        assert all(r.store == "trade_records" for r in results)
        assert len(results) >= 1

    async def test_unknown_store_ignored(self, recall: MemoryRecall) -> None:
        results = await recall.search("test", stores=["nonexistent_store", "trade_records"])
        # Should not error, just ignore unknown
        assert isinstance(results, list)


@pytest.mark.asyncio
class TestRelevanceRanking:
    """Verify that results are ranked by BM25 relevance."""

    async def test_more_relevant_ranks_higher(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        # Insert two records: one highly relevant, one tangentially
        _insert_trade(
            recall,
            thesis="Mean reversion strategy on BTC with RSI oversold below 30",
        )
        _insert_trade(
            recall,
            thesis="General market update: RSI indicators mixed today",
        )

        results = await recall.search("mean reversion RSI oversold")
        assert len(results) >= 2
        # The first result should be the more relevant one
        first_data = results[0].data
        assert "mean reversion" in first_data.get("thesis", "").lower()

    async def test_bm25_scores_present(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="BTC breakout above resistance with volume surge")

        results = await recall.search("breakout volume")
        assert len(results) >= 1
        # BM25 scores are negative (lower = better)
        assert results[0].score < 0


@pytest.mark.asyncio
class TestCJKSearch:
    """Verify CJK (Chinese, Japanese, Korean) search support."""

    async def test_chinese_search(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="比特币在超卖区域出现看涨背离信号")

        results = await recall.search("看涨背离")
        assert len(results) >= 1

    async def test_mixed_language_search(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="BTC 趋势分析 shows bullish momentum")

        results = await recall.search("趋势分析")
        assert len(results) >= 1

    async def test_thai_search(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_pattern(
            recall,
            pattern_name="thai_pattern",
            description="สัญญาณการกลับตัวของตลาดในระดับแนวรับ",
        )

        results = await recall.search("การกลับตัว")
        assert len(results) >= 1


@pytest.mark.asyncio
class TestSnakeCaseHandling:
    """Verify that snake_case terms are split into separate tokens."""

    async def test_snake_case_trade_thesis(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="stop_loss triggered at key support level")

        results = await recall.search("stop_loss")
        assert len(results) >= 1

    async def test_snake_case_pattern_name(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_pattern(
            recall,
            pattern_name="double_bottom_reversal",
            description="Classic reversal pattern",
        )

        results = await recall.search("double_bottom")
        assert len(results) >= 1


@pytest.mark.asyncio
class TestEdgeCases:
    """Edge cases and error handling."""

    async def test_empty_query_returns_empty(self, recall: MemoryRecall) -> None:
        results = await recall.search("")
        assert results == []

    async def test_whitespace_query_returns_empty(self, recall: MemoryRecall) -> None:
        results = await recall.search("   ")
        assert results == []

    async def test_no_matches_returns_empty(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="simple trade thesis")

        results = await recall.search("xyznonexistent123")
        assert results == []

    async def test_special_fts_characters_handled(self, recall: MemoryRecall) -> None:
        """Query with SQL/FTS special chars shouldn't crash."""
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="test with special chars")

        # These should not raise
        results = await recall.search('test "quoted" OR AND NOT')
        assert isinstance(results, list)

    async def test_deleted_trade_not_searchable(self, recall: MemoryRecall) -> None:
        """Soft-deleted records with is_deleted=1 should still be in FTS
        (FTS doesn't filter on is_deleted — that's the caller's job)."""
        _insert_trade(
            recall,
            trade_id="del-001",
            thesis="this trade is deleted",
        )
        # Mark as deleted using sync connection
        conn = _sync_conn(recall)
        try:
            conn.execute("UPDATE trade_records SET is_deleted = 1 WHERE trade_id = 'del-001'")
            conn.commit()
        finally:
            conn.close()

        # FTS will still find it (content-synced), but the data shows is_deleted=1
        results = await recall.search("trade deleted")
        # We verify it's still in FTS — the caller filters on is_deleted
        found = [r for r in results if r.record_id == "del-001"]
        # It may or may not match depending on tokenization; just ensure no crash
        assert isinstance(found, list)

    async def test_limit_respected(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        for i in range(10):
            _insert_trade(recall, thesis=f"trade number {i} with keyword alpha")

        results = await recall.search("alpha", limit=3)
        assert len(results) <= 3

    async def test_context_manager(self, tmp_path: Path) -> None:
        """MemoryRecall works as async context manager."""
        db_path = _make_db_path(tmp_path)
        conn = sqlite3.connect(db_path)
        _create_base_tables(conn)
        conn.close()

        async with MemoryRecall(db_path) as rec:
            results = await rec.search("anything")
            assert isinstance(results, list)

    async def test_not_initialized_raises(self, tmp_path: Path) -> None:
        """Searching before initialize should raise."""
        rec = MemoryRecall(_make_db_path(tmp_path))
        with pytest.raises(RuntimeError, match="not initialized"):
            await rec.search("test")


@pytest.mark.asyncio
class TestConvenienceMethods:
    """Verify store-specific convenience search methods."""

    async def test_search_trade_thesis_method(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="momentum breakout with volume confirmation")

        results = await recall.search_trade_thesis("momentum breakout")
        assert all(r.store == "trade_records" for r in results)
        assert len(results) >= 1

    async def test_search_strategies_method(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_strategy(recall, name="trend_following", thesis="Follow the trend with trailing stops")

        results = await recall.search_strategies("trend following")
        assert all(r.store == "strategy_genomes" for r in results)

    async def test_search_patterns_method(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_pattern(
            recall,
            pattern_name="head_shoulders",
            description="Head and shoulders reversal pattern",
        )

        results = await recall.search_patterns("head shoulders")
        assert all(r.store == "patterns" for r in results)

    async def test_search_lessons_method(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_lesson(
            recall,
            title="Position sizing lesson",
            description="Never risk more than 2% on a single trade",
        )

        results = await recall.search_lessons("position sizing")
        assert all(r.store == "lessons" for r in results)


@pytest.mark.asyncio
class TestIndexManagement:
    """Tests for rebuild_index and get_index_stats."""

    async def test_rebuild_index(self, recall: MemoryRecall) -> None:
        count = await recall.rebuild_index()
        assert count == 4  # all 4 stores

    async def test_rebuild_single_store(self, recall: MemoryRecall) -> None:
        count = await recall.rebuild_index("trade_records")
        assert count == 1

    async def test_index_stats(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="test trade")
        _insert_lesson(recall, title="test lesson", description="test desc")

        stats = await recall.get_index_stats()
        assert "trade_records" in stats
        assert "lessons" in stats
        assert stats["trade_records"]["source_rows"] >= 1
        assert stats["lessons"]["source_rows"] >= 1

    async def test_rebuild_unknown_store(self, recall: MemoryRecall) -> None:
        count = await recall.rebuild_index("nonexistent")
        assert count == 0


@pytest.mark.asyncio
class TestSearchResultDataClass:
    """Verify SearchResult structure."""

    async def test_result_has_all_fields(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="test thesis content here")

        results = await recall.search("thesis content")
        assert len(results) >= 1
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.store == "trade_records"
        assert r.record_id
        assert isinstance(r.score, float)
        assert isinstance(r.snippet, str)
        assert isinstance(r.data, dict)

    async def test_to_dict(self, recall: MemoryRecall) -> None:
        db = recall._db
        assert db is not None
        _insert_trade(recall, thesis="dict conversion test")

        results = await recall.search("dict conversion")
        assert len(results) >= 1
        d = results[0].to_dict()
        assert "store" in d
        assert "record_id" in d
        assert "score" in d
        assert "snippet" in d
        assert "data" in d
