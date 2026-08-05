"""
Signal Quality Database — Persistent win rate tracking and signal history.

SQLite-backed storage for:
  - Signal assessments (scores, factors, rejections)
  - Trade outcomes (win/loss, PnL)
  - Win rate computation per dimension (symbol, regime, signal type, hour)
  - Adaptive filter state

All operations are async-safe with connection pooling.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class SignalQualityDB:
    """Persistent storage for signal quality tracking.

    Tracks every signal assessment and trade outcome to compute
    win rates across multiple dimensions for adaptive filtering.
    """

    def __init__(self, db_path: str = "data/signal_quality.db") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS signal_assessments (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                composite_score REAL NOT NULL,
                factors_json TEXT,
                factors_confirmed INTEGER,
                tier TEXT,
                position_size_factor REAL,
                approved BOOLEAN,
                rejection_reasons_json TEXT,
                false_signal_flags_json TEXT,
                regime TEXT,
                adaptive_state_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trade_outcomes (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                composite_score REAL,
                regime TEXT,
                signal_type TEXT,
                hour_utc INTEGER,
                factors_confirmed INTEGER,
                entry_price REAL,
                exit_price REAL,
                pnl_pct REAL,
                win BOOLEAN,
                closed_at TEXT NOT NULL,
                FOREIGN KEY (signal_id) REFERENCES signal_assessments(signal_id)
            );

            CREATE TABLE IF NOT EXISTS adaptive_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                min_score REAL NOT NULL,
                min_factors INTEGER NOT NULL,
                last_adaptation TEXT,
                adaptation_reason TEXT,
                trades_since_adaptation INTEGER DEFAULT 0,
                current_loss_streak INTEGER DEFAULT 0,
                current_win_streak INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_outcomes_symbol
                ON trade_outcomes(symbol);
            CREATE INDEX IF NOT EXISTS idx_outcomes_signal_type
                ON trade_outcomes(signal_type);
            CREATE INDEX IF NOT EXISTS idx_outcomes_regime
                ON trade_outcomes(regime);
            CREATE INDEX IF NOT EXISTS idx_outcomes_timestamp
                ON trade_outcomes(closed_at);
            CREATE INDEX IF NOT EXISTS idx_assessments_approved
                ON signal_assessments(approved);
        """)

        # Ensure adaptive state row exists
        self._conn.execute("""
            INSERT OR IGNORE INTO adaptive_state
                (id, min_score, min_factors, last_adaptation, adaptation_reason)
            VALUES (1, 0.60, 3, NULL, NULL)
        """)
        self._conn.commit()

        logger.info("SignalQualityDB initialized at %s", self._db_path)

    async def record_signal_assessment(self, assessment: Any) -> None:
        """Record a signal quality assessment (approved or rejected)."""
        if not self._conn:
            await self.initialize()

        self._conn.execute(
            """
            INSERT OR REPLACE INTO signal_assessments
                (signal_id, symbol, side, composite_score, factors_json,
                 factors_confirmed, tier, position_size_factor, approved,
                 rejection_reasons_json, false_signal_flags_json, regime,
                 adaptive_state_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                assessment.signal_id,
                assessment.symbol,
                assessment.side,
                assessment.composite_score,
                json.dumps(
                    [
                        {
                            "name": f.name,
                            "score": f.score,
                            "weighted": f.weighted,
                            "reason": f.reason,
                            "confirmed": f.confirmed,
                        }
                        for f in assessment.factors
                    ]
                ),
                assessment.factors_confirmed,
                assessment.tier.value
                if hasattr(assessment.tier, "value")
                else str(assessment.tier),
                assessment.position_size_factor,
                assessment.approved,
                json.dumps(list(assessment.rejection_reasons)),
                json.dumps(list(assessment.false_signal_flags)),
                assessment.regime,
                json.dumps(assessment.adaptive_state),
                assessment.timestamp or datetime.now(UTC).isoformat(),
            ),
        )
        self._conn.commit()

    async def record_outcome(
        self,
        signal_id: str,
        pnl_pct: float,
        exit_price: float,
        win: bool,
    ) -> None:
        """Record a trade outcome (win/loss with PnL)."""
        if not self._conn:
            await self.initialize()

        # Get the original assessment
        row = self._conn.execute(
            "SELECT * FROM signal_assessments WHERE signal_id = ?",
            (signal_id,),
        ).fetchone()

        if not row:
            logger.warning("No assessment found for signal %s", signal_id)
            return

        now = datetime.now(UTC)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO trade_outcomes
                (signal_id, symbol, side, composite_score, regime,
                 signal_type, hour_utc, factors_confirmed, entry_price,
                 exit_price, pnl_pct, win, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                signal_id,
                row["symbol"],
                row["side"],
                row["composite_score"],
                row["regime"],
                self._extract_signal_type(row),
                now.hour,
                row["factors_confirmed"],
                0,  # entry_price from assessment if needed
                exit_price,
                pnl_pct,
                win,
                now.isoformat(),
            ),
        )
        self._conn.commit()

    async def get_trade_count(self) -> int:
        """Get total number of recorded trade outcomes."""
        if not self._conn:
            await self.initialize()
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM trade_outcomes").fetchone()
        return row["cnt"] if row else 0

    async def get_win_rate(
        self,
        dimension: str | None = None,
        value: str | None = None,
        window: int = 50,
    ) -> tuple[float, int]:
        """Compute win rate for a given dimension.

        Args:
            dimension: Column to filter on ("symbol", "regime", "signal_type", "hour_utc").
                       None = overall win rate.
            value: Value to filter by.
            window: Rolling window size.

        Returns:
            Tuple of (win_rate, trade_count).
        """
        if not self._conn:
            await self.initialize()

        if dimension and value:
            query = f"""
                SELECT win FROM trade_outcomes
                WHERE {dimension} = ?
                ORDER BY closed_at DESC
                LIMIT ?
            """
            rows = self._conn.execute(query, (value, window)).fetchall()
        else:
            query = """
                SELECT win FROM trade_outcomes
                ORDER BY closed_at DESC
                LIMIT ?
            """
            rows = self._conn.execute(query, (window,)).fetchall()

        if not rows:
            return 0.0, 0

        wins = sum(1 for r in rows if r["win"])
        return wins / len(rows), len(rows)

    async def get_consecutive_streak(self) -> tuple[int, str]:
        """Get current win/loss streak.

        Returns:
            Tuple of (streak_length, "win" or "loss").
        """
        if not self._conn:
            await self.initialize()

        rows = self._conn.execute("""
            SELECT win FROM trade_outcomes
            ORDER BY closed_at DESC
            LIMIT 20
        """).fetchall()

        if not rows:
            return 0, "none"

        first_win = rows[0]["win"]
        streak = 0
        for row in rows:
            if row["win"] == first_win:
                streak += 1
            else:
                break

        return streak, "win" if first_win else "loss"

    async def get_win_rate_by_dimension(
        self, window: int = 50
    ) -> dict[str, dict[str, tuple[float, int]]]:
        """Get win rates across all tracked dimensions.

        Returns:
            Dict mapping dimension → {value → (win_rate, count)}.
        """
        results: dict[str, dict[str, tuple[float, int]]] = {}

        for dimension in ["symbol", "regime", "signal_type"]:
            rows = self._conn.execute(f"""
                SELECT DISTINCT {dimension} FROM trade_outcomes
                WHERE {dimension} IS NOT NULL
            """).fetchall()

            dim_results: dict[str, tuple[float, int]] = {}
            for row in rows:
                val = row[dimension]
                if val:
                    wr, cnt = await self.get_win_rate(dimension, val, window)
                    if cnt >= 5:  # Only include with enough data
                        dim_results[val] = (wr, cnt)
            results[dimension] = dim_results

        # Hour dimension
        hour_results: dict[str, tuple[float, int]] = {}
        for hour in range(24):
            wr, cnt = await self.get_win_rate("hour_utc", str(hour), window)
            if cnt >= 5:
                hour_results[f"hour_{hour}"] = (wr, cnt)
        results["hour_utc"] = hour_results

        return results

    async def get_adaptive_state(self) -> dict[str, Any]:
        """Get current adaptive filter state."""
        if not self._conn:
            await self.initialize()

        row = self._conn.execute("SELECT * FROM adaptive_state WHERE id = 1").fetchone()
        if not row:
            return {"min_score": 0.60, "min_factors": 3}

        return {
            "min_score": row["min_score"],
            "min_factors": row["min_factors"],
            "last_adaptation": row["last_adaptation"],
            "adaptation_reason": row["adaptation_reason"],
            "trades_since_adaptation": row["trades_since_adaptation"],
            "current_loss_streak": row["current_loss_streak"],
            "current_win_streak": row["current_win_streak"],
        }

    async def update_adaptive_state(
        self,
        min_score: float,
        min_factors: int,
        reason: str,
    ) -> None:
        """Update adaptive filter parameters."""
        if not self._conn:
            await self.initialize()

        self._conn.execute(
            """
            UPDATE adaptive_state SET
                min_score = ?,
                min_factors = ?,
                last_adaptation = ?,
                adaptation_reason = ?,
                trades_since_adaptation = 0
            WHERE id = 1
        """,
            (min_score, min_factors, datetime.now(UTC).isoformat(), reason),
        )
        self._conn.commit()

    async def increment_trades_since_adaptation(self) -> None:
        """Increment the counter for trades since last adaptation."""
        if not self._conn:
            await self.initialize()

        self._conn.execute("""
            UPDATE adaptive_state
            SET trades_since_adaptation = trades_since_adaptation + 1
            WHERE id = 1
        """)
        self._conn.commit()

    async def update_streaks(self, win: bool) -> None:
        """Update win/loss streak counters."""
        if not self._conn:
            await self.initialize()

        if win:
            self._conn.execute("""
                UPDATE adaptive_state SET
                    current_win_streak = current_win_streak + 1,
                    current_loss_streak = 0
                WHERE id = 1
            """)
        else:
            self._conn.execute("""
                UPDATE adaptive_state SET
                    current_loss_streak = current_loss_streak + 1,
                    current_win_streak = 0
                WHERE id = 1
            """)
        self._conn.commit()

    @staticmethod
    def _extract_signal_type(row: sqlite3.Row) -> str:
        """Extract signal type from assessment metadata."""
        try:
            factors = json.loads(row["factors_json"]) if row["factors_json"] else []
            # Determine primary signal type from highest-scoring factor
            if factors:
                best = max(factors, key=lambda f: f.get("weighted", 0))
                return best.get("name", "unknown")
        except (json.JSONDecodeError, TypeError):
            pass
        return "unknown"
