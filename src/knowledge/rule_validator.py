"""TSAR — Rule Validator.

Phase 1B: Shadow Account Loop — Validate extracted trading rules by
replaying them against historical OHLCV data. Computes Sharpe ratio,
win rate, profit factor, and max drawdown to produce ValidatedRule
objects with statistical confidence.

Persistence: SQLite (WAL mode, tsar.db)
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.knowledge.shadow_extractor import TradingRule

logger = get_logger(__name__)


def _ulid() -> str:
    return uuid.uuid4().hex


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ValidatedRule:
    """A TradingRule that has been backtested with statistical metrics.

    Extends TradingRule with performance statistics computed from
    historical replay. Only rules that pass minimum thresholds
    should be forwarded to the GenomeMutator.
    """
    # Identity
    rule_id: str = field(default_factory=_ulid)
    source_rule_id: str = ""

    # Rule content (copied from TradingRule for standalone use)
    conditions: list[dict[str, Any]] = field(default_factory=list)
    action: str = "buy"
    confidence: float = 0.5
    source_trade_ids: list[str] = field(default_factory=list)
    symbol: str | None = None
    strategy_id: str | None = None
    regime: str | None = None
    description: str = ""
    rationale: str = ""

    # Backtest results
    sharpe: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    avg_return_pct: float = 0.0
    sample_size: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_winner_pct: float = 0.0
    avg_loser_pct: float = 0.0
    expectancy: float = 0.0

    # Statistical confidence
    p_value: float = 1.0
    confidence_interval_low: float = 0.0
    confidence_interval_high: float = 0.0
    validation_status: str = "pending"  # pending | passed | failed | insufficient_data

    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @property
    def is_valid(self) -> bool:
        """Check if this rule passes minimum statistical thresholds."""
        return (
            self.validation_status == "passed"
            and self.sample_size >= 20
            and self.sharpe > 0.5
            and self.win_rate > 0.45
            and self.profit_factor > 1.1
            and self.max_drawdown < 0.20
        )


@dataclass
class OHLCVCandle:
    """A single OHLCV candle for backtesting."""
    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0


class OHLCVProvider(Protocol):
    """Protocol for providing historical OHLCV data."""

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
        since: str | None = None,
    ) -> list[OHLCVCandle]:
        """Fetch historical OHLCV candles."""
        ...


# ═══════════════════════════════════════════════════════════════════════
# RULE VALIDATOR
# ═══════════════════════════════════════════════════════════════════════


class RuleValidator:
    """Validate extracted trading rules via historical OHLCV replay.

    Takes TradingRules from ShadowExtractor, replays them against
    historical candle data, computes risk-adjusted performance metrics,
    and produces ValidatedRules with statistical confidence.

    Usage::

        validator = RuleValidator(ohlcv_provider, db_path="/path/to/tsar.db")
        validated = await validator.validate_batch(extracted_rules)
        passed = [r for r in validated if r.is_valid]
    """

    # Minimum thresholds for a rule to be considered "passed"
    MIN_SAMPLE_SIZE = 20
    MIN_SHARPE = 0.5
    MIN_WIN_RATE = 0.45
    MIN_PROFIT_FACTOR = 1.1
    MAX_DRAWDOWN = 0.20
    MIN_EXPECTANCY = 0.0

    def __init__(
        self,
        ohlcv_provider: OHLCVProvider,
        db_path: str | Path | None = None,
    ) -> None:
        self._provider = ohlcv_provider
        self._db_path = str(db_path) if db_path else None

    async def validate(
        self,
        rule: TradingRule,
        symbol: str | None = None,
        timeframe: str = "1h",
        lookback_candles: int = 500,
    ) -> ValidatedRule:
        """Validate a single TradingRule against historical data.

        Args:
            rule: The TradingRule to validate.
            symbol: Symbol to test against (defaults to rule.symbol).
            timeframe: Candle timeframe for backtest.
            lookback_candles: Number of candles to replay.

        Returns:
            ValidatedRule with backtest statistics.
        """
        test_symbol = symbol or rule.symbol or "BTC/USDT"

        # Fetch historical candles
        candles = await self._provider.get_candles(
            symbol=test_symbol,
            timeframe=timeframe,
            limit=lookback_candles,
        )

        if len(candles) < 50:
            logger.warning("rule_validate_insufficient_candles", count=len(candles))
            return ValidatedRule(
                source_rule_id=rule.rule_id,
                conditions=rule.conditions,
                action=rule.action,
                confidence=rule.confidence,
                source_trade_ids=rule.source_trade_ids,
                symbol=test_symbol,
                strategy_id=rule.strategy_id,
                regime=rule.regime,
                description=rule.description,
                rationale=rule.rationale,
                validation_status="insufficient_data",
            )

        # Replay the rule against candles
        trades = self._replay_rule(rule, candles)

        # Compute metrics
        metrics = self._compute_metrics(trades)

        # Statistical significance test
        p_value = self._compute_p_value(metrics["win_rate"], metrics["total_trades"])
        ci_low, ci_high = self._wilson_confidence_interval(
            metrics["win_rate"], metrics["total_trades"]
        )

        # Determine validation status
        status = self._determine_status(metrics, p_value)

        validated = ValidatedRule(
            source_rule_id=rule.rule_id,
            conditions=rule.conditions,
            action=rule.action,
            confidence=rule.confidence,
            source_trade_ids=rule.source_trade_ids,
            symbol=test_symbol,
            strategy_id=rule.strategy_id,
            regime=rule.regime,
            description=rule.description,
            rationale=rule.rationale,
            sharpe=metrics["sharpe"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            max_drawdown=metrics["max_drawdown"],
            avg_return_pct=metrics["avg_return_pct"],
            sample_size=metrics["total_trades"],
            total_trades=metrics["total_trades"],
            winning_trades=metrics["winning_trades"],
            losing_trades=metrics["losing_trades"],
            avg_winner_pct=metrics["avg_winner_pct"],
            avg_loser_pct=metrics["avg_loser_pct"],
            expectancy=metrics["expectancy"],
            p_value=p_value,
            confidence_interval_low=ci_low,
            confidence_interval_high=ci_high,
            validation_status=status,
        )

        # Persist if we have a DB
        if self._db_path:
            self._persist_validated_rule(validated)

        logger.info(
            "rule_validated",
            rule_id=rule.rule_id,
            status=status,
            sharpe=metrics["sharpe"],
            win_rate=metrics["win_rate"],
            sample_size=metrics["total_trades"],
        )
        return validated

    async def validate_batch(
        self,
        rules: list[TradingRule],
        symbol: str | None = None,
        timeframe: str = "1h",
        lookback_candles: int = 500,
    ) -> list[ValidatedRule]:
        """Validate a batch of TradingRules.

        Args:
            rules: List of TradingRules to validate.
            symbol: Symbol override for all rules.
            timeframe: Candle timeframe.
            lookback_candles: Number of candles to replay.

        Returns:
            List of ValidatedRules.
        """
        results: list[ValidatedRule] = []
        for rule in rules:
            try:
                validated = await self.validate(
                    rule, symbol=symbol, timeframe=timeframe,
                    lookback_candles=lookback_candles,
                )
                results.append(validated)
            except Exception as e:
                logger.error("rule_validate_error", rule_id=rule.rule_id, error=str(e))
                results.append(ValidatedRule(
                    source_rule_id=rule.rule_id,
                    conditions=rule.conditions,
                    action=rule.action,
                    validation_status="failed",
                ))
        return results

    # ── Replay Engine ────────────────────────────────────────

    def _replay_rule(
        self, rule: TradingRule, candles: list[OHLCVCandle]
    ) -> list[dict[str, Any]]:
        """Replay a rule against candle data, producing simulated trades.

        Walks through candles, checks if rule conditions are met,
        and simulates entry/exit with fixed holding period.
        """
        trades: list[dict[str, Any]] = []
        holding_period = 12  # candles (e.g., 12 hours for 1h candles)

        for i in range(len(candles) - holding_period):
            candle = candles[i]

            # Check if conditions are met at this candle
            if self._check_conditions(rule.conditions, candles, i):
                entry_price = candle.close
                exit_candle = candles[i + holding_period]
                exit_price = exit_candle.close

                if rule.action == "buy":
                    pnl_pct = (exit_price - entry_price) / entry_price
                else:  # sell
                    pnl_pct = (entry_price - exit_price) / entry_price

                trades.append({
                    "entry_idx": i,
                    "exit_idx": i + holding_period,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "holding_candles": holding_period,
                })

        return trades

    def _check_conditions(
        self,
        conditions: list[dict[str, Any]],
        candles: list[OHLCVCandle],
        idx: int,
    ) -> bool:
        """Check if rule conditions are met at a given candle index.

        Conditions are dicts with keys like:
          {"type": "rsi_below", "value": 30}
          {"type": "price_above_ma", "period": 20}
          {"type": "volume_above_avg", "multiplier": 1.5}
          {"type": "close_above_high", "lookback": 20}
        """
        if not conditions:
            return False

        return all(self._evaluate_condition(cond, candles, idx) for cond in conditions)

    def _evaluate_condition(
        self,
        cond: dict[str, Any],
        candles: list[OHLCVCandle],
        idx: int,
    ) -> bool:
        """Evaluate a single condition against candle data."""
        cond_type = cond.get("type", "")
        candle = candles[idx]

        try:
            if cond_type == "rsi_below":
                rsi = self._compute_rsi(candles, idx, period=14)
                return rsi is not None and rsi < cond.get("value", 30)

            elif cond_type == "rsi_above":
                rsi = self._compute_rsi(candles, idx, period=14)
                return rsi is not None and rsi > cond.get("value", 70)

            elif cond_type == "price_above_ma":
                period = cond.get("period", 20)
                ma = self._compute_sma(candles, idx, period)
                return ma is not None and candle.close > ma

            elif cond_type == "price_below_ma":
                period = cond.get("period", 20)
                ma = self._compute_sma(candles, idx, period)
                return ma is not None and candle.close < ma

            elif cond_type == "volume_above_avg":
                multiplier = cond.get("multiplier", 1.5)
                avg_vol = self._compute_avg_volume(candles, idx, period=20)
                return avg_vol is not None and candle.volume > avg_vol * multiplier

            elif cond_type == "close_above_high":
                lookback = cond.get("lookback", 20)
                start = max(0, idx - lookback)
                highest = max(c.high for c in candles[start:idx])
                return candle.close > highest

            elif cond_type == "close_below_low":
                lookback = cond.get("lookback", 20)
                start = max(0, idx - lookback)
                lowest = min(c.low for c in candles[start:idx])
                return candle.close < lowest

            elif cond_type == "price_change_above":
                pct = cond.get("pct", 0.02)
                if idx < 1:
                    return False
                change = abs(candle.close - candles[idx - 1].close) / candles[idx - 1].close
                return change > pct

            elif cond_type == "always":
                return True

            else:
                logger.debug("unknown_condition_type", cond_type=cond_type)
                return False

        except (IndexError, ZeroDivisionError):
            return False

    # ── Technical Indicators ─────────────────────────────────

    @staticmethod
    def _compute_rsi(
        candles: list[OHLCVCandle], idx: int, period: int = 14
    ) -> float | None:
        """Compute RSI at a given candle index."""
        if idx < period:
            return None
        gains: list[float] = []
        losses: list[float] = []
        for i in range(idx - period + 1, idx + 1):
            change = candles[i].close - candles[i - 1].close
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _compute_sma(
        candles: list[OHLCVCandle], idx: int, period: int
    ) -> float | None:
        """Compute Simple Moving Average at a given candle index."""
        if idx < period - 1:
            return None
        total = sum(candles[i].close for i in range(idx - period + 1, idx + 1))
        return total / period

    @staticmethod
    def _compute_avg_volume(
        candles: list[OHLCVCandle], idx: int, period: int = 20
    ) -> float | None:
        """Compute average volume over a lookback period."""
        if idx < period:
            return None
        total = sum(candles[i].volume for i in range(idx - period, idx))
        return total / period

    # ── Metric Computation ───────────────────────────────────

    @staticmethod
    def _compute_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute backtest performance metrics from simulated trades."""
        if not trades:
            return {
                "sharpe": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
                "max_drawdown": 0.0, "avg_return_pct": 0.0,
                "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                "avg_winner_pct": 0.0, "avg_loser_pct": 0.0, "expectancy": 0.0,
            }

        returns = [t["pnl_pct"] for t in trades]
        winners = [r for r in returns if r > 0]
        losers = [r for r in returns if r <= 0]

        total = len(returns)
        win_count = len(winners)
        lose_count = len(losers)
        win_rate = win_count / total if total > 0 else 0.0

        avg_return = sum(returns) / total if total > 0 else 0.0
        avg_winner = sum(winners) / win_count if win_count > 0 else 0.0
        avg_loser = sum(losers) / lose_count if lose_count > 0 else 0.0

        # Profit factor = gross_profit / gross_loss
        gross_profit = sum(winners) if winners else 0.0
        gross_loss = abs(sum(losers)) if losers else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            float("inf") if gross_profit > 0 else 0.0
        )

        # Sharpe ratio (annualized, assuming hourly candles → 8760 periods/year)
        if len(returns) > 1:
            mean_r = sum(returns) / len(returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
            std_r = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = (mean_r / std_r) * math.sqrt(8760) if std_r > 0 else 0.0
        else:
            sharpe = 0.0

        # Max drawdown (peak-to-trough on cumulative returns)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        # Expectancy = (win_rate * avg_winner) - ((1 - win_rate) * abs(avg_loser))
        expectancy = (win_rate * avg_winner) - ((1 - win_rate) * abs(avg_loser))

        return {
            "sharpe": round(sharpe, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "max_drawdown": round(max_dd, 4),
            "avg_return_pct": round(avg_return, 6),
            "total_trades": total,
            "winning_trades": win_count,
            "losing_trades": lose_count,
            "avg_winner_pct": round(avg_winner, 6),
            "avg_loser_pct": round(avg_loser, 6),
            "expectancy": round(expectancy, 6),
        }

    @staticmethod
    def _determine_status(metrics: dict[str, Any], p_value: float) -> str:
        """Determine validation status based on metrics and significance."""
        if metrics["total_trades"] < 20:
            return "insufficient_data"
        if p_value > 0.05:
            return "failed"  # Not statistically significant
        if (
            metrics["sharpe"] > 0.5
            and metrics["win_rate"] > 0.45
            and metrics["profit_factor"] > 1.1
            and metrics["max_drawdown"] < 0.20
        ):
            return "passed"
        return "failed"

    # ── Statistical Tests ────────────────────────────────────

    @staticmethod
    def _compute_p_value(win_rate: float, n: int) -> float:
        """Compute p-value using binomial test (H0: win_rate = 0.5).

        Uses normal approximation for large samples.
        """
        if n < 10:
            return 1.0
        p0 = 0.5  # null hypothesis
        se = math.sqrt(p0 * (1 - p0) / n)
        if se == 0:
            return 1.0
        z = (win_rate - p0) / se
        # Two-tailed p-value using normal CDF approximation
        p_value = 2 * (1 - _normal_cdf(abs(z)))
        return round(p_value, 6)

    @staticmethod
    def _wilson_confidence_interval(
        win_rate: float, n: int, z: float = 1.96
    ) -> tuple[float, float]:
        """Wilson score confidence interval for win rate."""
        if n == 0:
            return (0.0, 0.0)
        denominator = 1 + z * z / n
        center = (win_rate + z * z / (2 * n)) / denominator
        spread = z * math.sqrt((win_rate * (1 - win_rate) + z * z / (4 * n)) / n) / denominator
        return (
            round(max(0.0, center - spread), 4),
            round(min(1.0, center + spread), 4),
        )

    # ── Persistence ──────────────────────────────────────────

    def _persist_validated_rule(self, rule: ValidatedRule) -> None:
        """Persist a ValidatedRule to SQLite.

        G12 NOTE: The validated_rules table is created via
        CREATE TABLE IF NOT EXISTS, so this is safe to call on existing
        databases that don't have the table yet.  No separate migration
        step is required — the table will be created on first persist.
        """
        if not self._db_path:
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS validated_rules (
                    rule_id TEXT PRIMARY KEY,
                    source_rule_id TEXT,
                    conditions TEXT,
                    action TEXT,
                    confidence REAL,
                    source_trade_ids TEXT,
                    symbol TEXT,
                    strategy_id TEXT,
                    regime TEXT,
                    description TEXT,
                    rationale TEXT,
                    sharpe REAL,
                    win_rate REAL,
                    profit_factor REAL,
                    max_drawdown REAL,
                    avg_return_pct REAL,
                    sample_size INTEGER,
                    total_trades INTEGER,
                    winning_trades INTEGER,
                    losing_trades INTEGER,
                    avg_winner_pct REAL,
                    avg_loser_pct REAL,
                    expectancy REAL,
                    p_value REAL,
                    confidence_interval_low REAL,
                    confidence_interval_high REAL,
                    validation_status TEXT,
                    created_at TEXT
                )
            """)
            d = rule.to_dict()
            # Serialize list fields as JSON
            d["conditions"] = json.dumps(d["conditions"])
            d["source_trade_ids"] = json.dumps(d["source_trade_ids"])
            cols = ", ".join(d.keys())
            placeholders = ", ".join(f":{k}" for k in d)
            conn.execute(
                f"INSERT OR REPLACE INTO validated_rules ({cols}) VALUES ({placeholders})",
                d,
            )
            conn.commit()
        finally:
            conn.close()


# ── Helper functions ──────────────────────────────────────────


def _normal_cdf(x: float) -> float:
    """Approximate the standard normal CDF using the error function."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
