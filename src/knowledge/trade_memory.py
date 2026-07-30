"""TSAR — Trade Memory.

Knowledge Store #1: The canonical record of every trade decision, execution,
context, outcome, and post-trade reflection.  This is the system's episodic
memory — what happened, why, and what was learned.

Persistence: SQLite (WAL mode, tsar.db)
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Generator

logger = get_logger(__name__)


def _ulid() -> str:
    return uuid.uuid4().hex


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class TradeRecord:
    """Represents a single trade record (maps to trade_records table)."""
    trade_id: str = field(default_factory=_ulid)
    symbol: str = ""
    asset_class: str = "crypto"
    exchange: str | None = None
    strategy_id: str = ""
    signal_type: str = "entry"
    signal_score: float | None = None
    signal_source: str | None = None
    side: str = "buy"
    order_type: str = "market"
    quantity: float = 0.0
    limit_price: float | None = None
    stop_price: float | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    fill_quantity: float | None = None
    slippage_bps: float | None = None
    commission: float = 0.0
    fill_timestamp: str | None = None
    latency_ms: int | None = None
    position_size_before: float = 0.0
    position_size_after: float = 0.0
    portfolio_heat_before: float | None = None
    portfolio_heat_after: float | None = None
    regime_at_entry: str | None = None
    vix_level: float | None = None
    market_breadth: float | None = None
    sector_momentum: str | None = None
    volatility_regime: str | None = None
    liquidity_score: float | None = None
    expected_return: float | None = None
    expected_risk: float | None = None
    risk_reward_ratio: float | None = None
    confidence: float | None = None
    thesis: str | None = None
    key_levels: str | None = None
    status: str = "OPEN"
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0
    holding_period_hours: float | None = None
    max_drawdown_during: float | None = None
    max_favorable_excursion: float | None = None
    max_adverse_excursion: float | None = None
    outcome_grade: str | None = None
    execution_grade: str | None = None
    reflection: str | None = None
    lessons: str | None = None
    pattern_matches: str | None = None
    trading_mode: str = "paper"
    notes: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    is_deleted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class TradeSnapshot:
    """Market state snapshot at decision time."""
    snapshot_id: str = field(default_factory=_ulid)
    trade_id: str = ""
    snapshot_type: str = "decision"
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    last_price: float | None = None
    volume_24h: float | None = None
    rsi_14: float | None = None
    macd_signal: float | None = None
    bb_position: float | None = None
    atr_14: float | None = None
    obv_trend: str | None = None
    book_depth_bid: str | None = None
    book_depth_ask: str | None = None
    spread_bps: float | None = None
    news_sentiment: float | None = None
    social_sentiment: float | None = None
    fear_greed_index: float | None = None
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class TradeJournalEntry:
    """Free-form trade journal entry."""
    journal_id: str = field(default_factory=_ulid)
    trade_id: str = ""
    entry_type: str = "post_mortem"
    content: str = ""
    mood: str | None = None
    cognitive_biases: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class TradeMemory:
    """CRUD operations, FTS5 search, snapshots, and journal entries
    for the trade_records table in SQLite.

    Supports optional connection pooling via SQLitePool for production
    workloads. When ``pool`` is provided, connections are acquired from
    the pool instead of creating new ones.

    Usage::

        # Without pool (backward-compatible)
        mem = TradeMemory("/path/to/tsar.db")

        # With connection pool
        from src.knowledge.db_pool import SQLitePool
        pool = SQLitePool("/path/to/tsar.db", pool_size=5)
        mem = TradeMemory("/path/to/tsar.db", pool=pool)

        mem.insert_trade(trade)
        results = mem.search_thesis("mean reversion BTC oversold")
    """

    def __init__(
        self,
        db_path: str | Path,
        pool: Any | None = None,
        pool_size: int = 5,
        max_overflow: int = 3,
    ) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Connection pool (optional)
        if pool is not None:
            self._pool = pool
        else:
            self._pool = None
            # Pool can also be auto-created by importing get_pool
            # but we keep it opt-in for backward compatibility

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        if self._pool is not None:
            # Use connection pool
            with self._pool.connection() as conn:
                yield conn
        else:
            # Direct connection (backward-compatible)
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ── Trade CRUD ───────────────────────────────────────────

    def insert_trade(self, trade: TradeRecord) -> str:
        d = trade.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d)
        sql = f"INSERT INTO trade_records ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        logger.info("trade_inserted", trade_id=trade.trade_id, symbol=trade.symbol)
        return trade.trade_id

    def get_trade(self, trade_id: str) -> TradeRecord | None:
        sql = "SELECT * FROM trade_records WHERE trade_id = ? AND is_deleted = 0"
        with self._conn() as conn:
            row = conn.execute(sql, (trade_id,)).fetchone()
        return TradeRecord(**dict(row)) if row else None

    def update_trade(self, trade_id: str, **fields: Any) -> bool:
        if not fields:
            return False
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["trade_id"] = trade_id
        sql = f"UPDATE trade_records SET {sets} WHERE trade_id = :trade_id AND is_deleted = 0"
        with self._conn() as conn:
            cursor = conn.execute(sql, fields)
        if cursor.rowcount > 0:
            logger.info("trade_updated", trade_id=trade_id, fields=list(fields.keys()))
            return True
        return False

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        realized_pnl: float,
        realized_pnl_pct: float,
        holding_period_hours: float | None = None,
        outcome_grade: str | None = None,
        execution_grade: str | None = None,
        reflection: str | None = None,
        status: str = "CLOSED",
    ) -> bool:
        fields: dict[str, Any] = {
            "exit_price": exit_price,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "status": status,
        }
        if holding_period_hours is not None:
            fields["holding_period_hours"] = holding_period_hours
        if outcome_grade is not None:
            fields["outcome_grade"] = outcome_grade
        if execution_grade is not None:
            fields["execution_grade"] = execution_grade
        if reflection is not None:
            fields["reflection"] = reflection
        return self.update_trade(trade_id, **fields)

    def delete_trade(self, trade_id: str, hard: bool = False) -> bool:
        if hard:
            sql = "DELETE FROM trade_records WHERE trade_id = ?"
        else:
            sql = "UPDATE trade_records SET is_deleted = 1 WHERE trade_id = ? AND is_deleted = 0"
        with self._conn() as conn:
            cursor = conn.execute(sql, (trade_id,))
        if cursor.rowcount > 0:
            logger.info("trade_deleted", trade_id=trade_id, hard=hard)
            return True
        return False

    def list_trades(
        self,
        symbol: str | None = None,
        strategy_id: str | None = None,
        status: str | None = None,
        trading_mode: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TradeRecord]:
        clauses: list[str] = ["is_deleted = 0"]
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if strategy_id:
            clauses.append("strategy_id = ?")
            params.append(strategy_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if trading_mode:
            clauses.append("trading_mode = ?")
            params.append(trading_mode)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if until:
            clauses.append("created_at <= ?")
            params.append(until)
        where = " AND ".join(clauses)
        sql = f"SELECT * FROM trade_records WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [TradeRecord(**dict(r)) for r in rows]

    def get_open_positions(self) -> list[TradeRecord]:
        sql = """
            SELECT * FROM trade_records
            WHERE position_size_after != 0 AND is_deleted = 0
            ORDER BY created_at DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [TradeRecord(**dict(r)) for r in rows]

    def get_trade_count(self, since: str | None = None) -> int:
        if since:
            sql = "SELECT COUNT(*) FROM trade_records WHERE is_deleted = 0 AND created_at >= ?"
            params: tuple[Any, ...] = (since,)
        else:
            sql = "SELECT COUNT(*) FROM trade_records WHERE is_deleted = 0"
            params = ()
        with self._conn() as conn:
            row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def get_strategy_summary(self, since: str | None = None) -> list[dict[str, Any]]:
        clause = "AND created_at >= ?" if since else ""
        sql = f"""
            SELECT
                strategy_id,
                COUNT(*) AS trade_count,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                SUM(realized_pnl) AS total_pnl,
                AVG(realized_pnl_pct) AS avg_pnl_pct,
                AVG(slippage_bps) AS avg_slippage,
                AVG(CASE WHEN realized_pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
            FROM trade_records
            WHERE is_deleted = 0 {clause}
            GROUP BY strategy_id
            ORDER BY total_pnl DESC
        """
        params: tuple[Any, ...] = (since,) if since else ()
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── FTS5 search ──────────────────────────────────────────

    def search_thesis(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        fts_query = self._format_fts_query(query)
        sql = """
            SELECT t.*, rank AS bm25_score
            FROM trade_records_fts fts
            JOIN trade_records t ON t.rowid = fts.rowid
            WHERE trade_records_fts MATCH ?
                AND t.is_deleted = 0
            ORDER BY rank
            LIMIT ?
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (fts_query, limit)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _format_fts_query(query: str) -> str:
        import re
        clean = re.sub(r"[^\w\s]", "", query)
        terms = [t for t in clean.split() if len(t) > 2]
        if not terms:
            return '""'
        return " OR ".join(f'"{t}"' for t in terms)

    # ── Trade snapshots ──────────────────────────────────────

    def insert_snapshot(self, snapshot: TradeSnapshot) -> str:
        d = snapshot.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d)
        sql = f"INSERT INTO trade_snapshots ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        return snapshot.snapshot_id

    def get_snapshots(
        self, trade_id: str, snapshot_type: str | None = None
    ) -> list[TradeSnapshot]:
        if snapshot_type:
            sql = "SELECT * FROM trade_snapshots WHERE trade_id = ? AND snapshot_type = ? ORDER BY created_at"
            params: tuple[Any, ...] = (trade_id, snapshot_type)
        else:
            sql = "SELECT * FROM trade_snapshots WHERE trade_id = ? ORDER BY created_at"
            params = (trade_id,)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [TradeSnapshot(**dict(r)) for r in rows]

    # ── Trade journal ────────────────────────────────────────

    def insert_journal_entry(self, entry: TradeJournalEntry) -> str:
        d = entry.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d)
        sql = f"INSERT INTO trade_journal ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        return entry.journal_id

    def get_journal_entries(
        self,
        trade_id: str | None = None,
        entry_type: str | None = None,
        limit: int = 50,
    ) -> list[TradeJournalEntry]:
        clauses: list[str] = []
        params: list[Any] = []
        if trade_id:
            clauses.append("trade_id = ?")
            params.append(trade_id)
        if entry_type:
            clauses.append("entry_type = ?")
            params.append(entry_type)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM trade_journal {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [TradeJournalEntry(**dict(r)) for r in rows]

    # ── Trade ↔ Lesson junction table ───────────────────────

    def link_lesson(self, trade_id: str, lesson_id: str, relevance: float = 1.0) -> None:
        """Link a lesson to a trade via junction table."""
        sql = """
            INSERT OR IGNORE INTO trade_lessons (trade_id, lesson_id, relevance)
            VALUES (?, ?, ?)
        """
        with self._conn() as conn:
            conn.execute(sql, (trade_id, lesson_id, relevance))

    def unlink_lesson(self, trade_id: str, lesson_id: str) -> bool:
        """Remove a lesson link from a trade."""
        sql = "DELETE FROM trade_lessons WHERE trade_id = ? AND lesson_id = ?"
        with self._conn() as conn:
            cursor = conn.execute(sql, (trade_id, lesson_id))
        return cursor.rowcount > 0

    def get_trade_lessons(self, trade_id: str) -> list[dict[str, Any]]:
        """Get all lessons linked to a trade via junction table."""
        sql = """
            SELECT l.*, tl.relevance
            FROM trade_lessons tl
            JOIN lessons l ON l.lesson_id = tl.lesson_id
            WHERE tl.trade_id = ?
            ORDER BY tl.relevance DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (trade_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_lesson_trades(self, lesson_id: str) -> list[TradeRecord]:
        """Get all trades linked to a lesson via junction table."""
        sql = """
            SELECT t.*
            FROM trade_lessons tl
            JOIN trade_records t ON t.trade_id = tl.trade_id
            WHERE tl.lesson_id = ? AND t.is_deleted = 0
            ORDER BY t.created_at DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (lesson_id,)).fetchall()
        return [TradeRecord(**dict(r)) for r in rows]

    # ── Trade ↔ Pattern junction table ───────────────────────

    def link_pattern(self, trade_id: str, pattern_id: str, match_score: float = 0.0) -> None:
        """Link a pattern to a trade via junction table."""
        sql = """
            INSERT OR IGNORE INTO trade_patterns (trade_id, pattern_id, match_score)
            VALUES (?, ?, ?)
        """
        with self._conn() as conn:
            conn.execute(sql, (trade_id, pattern_id, match_score))

    def unlink_pattern(self, trade_id: str, pattern_id: str) -> bool:
        """Remove a pattern link from a trade."""
        sql = "DELETE FROM trade_patterns WHERE trade_id = ? AND pattern_id = ?"
        with self._conn() as conn:
            cursor = conn.execute(sql, (trade_id, pattern_id))
        return cursor.rowcount > 0

    def get_trade_patterns(self, trade_id: str) -> list[dict[str, Any]]:
        """Get all patterns linked to a trade via junction table."""
        sql = """
            SELECT p.*, tp.match_score
            FROM trade_patterns tp
            JOIN patterns p ON p.pattern_id = tp.pattern_id
            WHERE tp.trade_id = ?
            ORDER BY tp.match_score DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (trade_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_pattern_trades(self, pattern_id: str) -> list[TradeRecord]:
        """Get all trades linked to a pattern via junction table."""
        sql = """
            SELECT t.*
            FROM trade_patterns tp
            JOIN trade_records t ON t.trade_id = tp.trade_id
            WHERE tp.pattern_id = ? AND t.is_deleted = 0
            ORDER BY t.created_at DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (pattern_id,)).fetchall()
        return [TradeRecord(**dict(r)) for r in rows]

    # ── Regime-specific queries ──────────────────────────────

    def get_performance_by_regime(self, since: str | None = None) -> list[dict[str, Any]]:
        clause = "AND created_at >= ?" if since else ""
        sql = f"""
            SELECT
                regime_at_entry,
                COUNT(*) AS trade_count,
                SUM(realized_pnl) AS total_pnl,
                AVG(realized_pnl_pct) AS avg_pnl_pct,
                AVG(CASE WHEN realized_pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
            FROM trade_records
            WHERE is_deleted = 0 AND regime_at_entry IS NOT NULL {clause}
            GROUP BY regime_at_entry
            ORDER BY total_pnl DESC
        """
        params: tuple[Any, ...] = (since,) if since else ()
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_symbol_performance(self, symbol: str, since: str | None = None) -> dict[str, Any]:
        clause = "AND created_at >= ?" if since else ""
        sql = f"""
            SELECT
                COUNT(*) AS trade_count,
                SUM(realized_pnl) AS total_pnl,
                AVG(realized_pnl_pct) AS avg_pnl_pct,
                AVG(slippage_bps) AS avg_slippage,
                AVG(CASE WHEN realized_pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
                MAX(realized_pnl) AS best_trade,
                MIN(realized_pnl) AS worst_trade
            FROM trade_records
            WHERE symbol = ? AND is_deleted = 0 {clause}
        """
        params: list[Any] = [symbol]
        if since:
            params.append(since)
        with self._conn() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else {}

    # ── Trade statistics ──────────────────────────────────────

    def get_trade_stats(self, strategy_id: str | None = None, since: str | None = None) -> dict[str, Any]:
        """Compute aggregate trade statistics.

        Returns:
            Dict with keys: win_rate, total_pnl, avg_win, avg_loss,
            profit_factor, max_drawdown, trade_count.
        """
        clauses: list[str] = ["is_deleted = 0", "status = 'CLOSED'"]
        params: list[Any] = []
        if strategy_id:
            clauses.append("strategy_id = ?")
            params.append(strategy_id)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = " AND ".join(clauses)
        sql = f"""
            SELECT
                COUNT(*) AS trade_count,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                SUM(CASE WHEN realized_pnl <= 0 THEN 1 ELSE 0 END) AS losing_trades,
                AVG(CASE WHEN realized_pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
                SUM(realized_pnl) AS total_pnl,
                AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE NULL END) AS avg_win,
                AVG(CASE WHEN realized_pnl <= 0 THEN realized_pnl ELSE NULL END) AS avg_loss,
                SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) AS gross_profit,
                SUM(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE 0 END) AS gross_loss
            FROM trade_records
            WHERE {where}
        """
        with self._conn() as conn:
            row = conn.execute(sql, params).fetchone()

        if not row or row["trade_count"] == 0:
            return {
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "trade_count": 0,
            }

        gross_profit = row["gross_profit"] or 0.0
        gross_loss = row["gross_loss"] or 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

        # Compute max drawdown from cumulative P&L series
        max_drawdown = self._compute_max_drawdown(strategy_id, since)

        return {
            "win_rate": row["win_rate"] or 0.0,
            "total_pnl": row["total_pnl"] or 0.0,
            "avg_win": row["avg_win"] or 0.0,
            "avg_loss": row["avg_loss"] or 0.0,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "trade_count": row["trade_count"],
        }

    def _compute_max_drawdown(self, strategy_id: str | None = None, since: str | None = None) -> float:
        """Compute max drawdown from the cumulative P&L curve.

        Returns:
            Max drawdown as a positive float (e.g. 0.05 = 5% drawdown).
        """
        clauses: list[str] = ["is_deleted = 0", "status = 'CLOSED'"]
        params: list[Any] = []
        if strategy_id:
            clauses.append("strategy_id = ?")
            params.append(strategy_id)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = " AND ".join(clauses)
        sql = f"""
            SELECT realized_pnl FROM trade_records
            WHERE {where}
            ORDER BY created_at ASC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return 0.0

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for row in rows:
            cumulative += row["realized_pnl"]
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return max_dd
