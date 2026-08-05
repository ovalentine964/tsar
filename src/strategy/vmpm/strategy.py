"""
VMPM Strategy — Main strategy class extending TSAR's BaseStrategy.

Wires all VMPM components into a single strategy that plugs into
TSAR's SignalScout → RiskGuardian → ExecutionSniper pipeline.

The strategy:
  1. Receives market data from SignalScout
  2. Runs the 7-layer entry pipeline
  3. Returns a signal with entry/SL/TP for RiskGuardian
  4. Manages exits with trailing stops and partial profits
  5. Feeds outcomes to TradePhilosopher for flywheel learning

Integration with TSAR:
  - Registered in StrategyRegistry
  - Scored by SignalScout
  - Risk-checked by RiskGuardian
  - Executed by ExecutionSniper
  - Reflected on by TradePhilosopher
  - Evolved by StrategyGeneticist
"""

from __future__ import annotations

import logging
from typing import Any

from src.strategy.base import BaseStrategy
from src.strategy.vmpm.candlestick_confirmer import CandlestickConfirmer
from src.strategy.vmpm.entry_pipeline import EntryPipeline, PipelineResult
from src.strategy.vmpm.fundamental_analyzer import FundamentalAnalyzer
from src.strategy.vmpm.level_mapper import LevelMapper
from src.strategy.vmpm.rsi_filter import RSIFilter
from src.strategy.vmpm.session_manager import SessionManager
from src.strategy.vmpm.trend_detector import TrendDetector

logger = logging.getLogger(__name__)


class VMPMStrategy(BaseStrategy):
    """Valentine Money Printing Machine — Institutional-grade trading strategy.

    Implements BaseStrategy interface for TSAR integration.
    Uses the 7-layer entry pipeline for signal generation.
    """

    NAME = "vmpm"
    VERSION = "1.0.0"

    # Default genome — evolved by StrategyGeneticist over time
    DEFAULT_GENOME = {
        # Session filters
        "enabled_sessions": ["london", "new_york", "tokyo"],
        "overlap_bonus": 1.2,
        # Trend
        "trend_ma_fast": 50,
        "trend_ma_slow": 200,
        "trend_min_strength": 0.3,
        # S/R
        "sr_proximity_pct": 0.02,
        "order_block_lookback": 50,
        # RSI
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        # Candlestick
        "engulfing_body_ratio": 0.6,
        "pin_bar_wick_ratio": 0.6,
        # Risk
        "risk_per_trade_pct": 2.0,
        "max_daily_trades": 3,
        "max_concurrent_positions": 1,
        "min_rr_ratio": 2.0,
        "default_rr_ratio": 2.5,
        # Trailing stop
        "trailing_stop_atr_mult": 2.0,
        "breakeven_atr_mult": 1.0,
        "partial_profit_pct": 50.0,
        "partial_atr_mult": 1.5,
        # News
        "news_blackout_minutes": 30,
        "high_impact_cooldown_minutes": 60,
        # Filters
        "min_pipeline_score": 0.55,
        "max_spread_pips": 5.0,
    }

    def __init__(self, genome: dict[str, Any] | None = None) -> None:
        self.genome = {**self.DEFAULT_GENOME, **(genome or {})}

        # Initialize sub-components
        self.session_mgr = SessionManager(genome=self.genome)
        self.fundamental = FundamentalAnalyzer(genome=self.genome)
        self.trend = TrendDetector(genome=self.genome)
        self.levels = LevelMapper(genome=self.genome)
        self.rsi = RSIFilter(genome=self.genome)
        self.candlestick = CandlestickConfirmer(genome=self.genome)

        # Entry pipeline (wires all layers)
        self.pipeline = EntryPipeline(
            genome=self.genome,
            session_manager=self.session_mgr,
            fundamental_analyzer=self.fundamental,
            trend_detector=self.trend,
            level_mapper=self.levels,
            rsi_filter=self.rsi,
            candlestick_confirmer=self.candlestick,
        )

        # State tracking
        self._daily_trade_count = 0
        self._last_signal_time = 0
        self._positions: dict[str, dict[str, Any]] = {}

        logger.info(
            "VMPM Strategy v%s initialized with genome: %s",
            self.VERSION, self.genome,
        )

    # ------------------------------------------------------------------
    # BaseStrategy Interface
    # ------------------------------------------------------------------

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Check if entry conditions are met.

        Called by SignalScout with market data. Returns signal dict or None.

        Args:
            data: Market data dict with keys:
                - symbol: str (e.g. "BTC/USDT")
                - ohlcv: dict[str, list] keyed by timeframe
                - closes: list[float] (H1 closes)
                - news: dict (optional)
                - spread: float (optional)

        Returns:
            Signal dict with score, entry, SL, TP, or None.
        """
        symbol = data.get("symbol", "UNKNOWN")
        ohlcv_by_tf = data.get("ohlcv", {})
        closes = data.get("closes", [])
        news_data = data.get("news")
        spread = data.get("spread", 0.0)

        if not closes or len(closes) < 50:
            logger.debug("VMPM: Insufficient data for %s", symbol)
            return None

        # Session filter
        session = self.session_mgr.current_session()
        if session.session.value not in self.genome["enabled_sessions"]:
            logger.debug("VMPM: Session %s not enabled", session.session.value)
            return None

        # Spread filter
        if spread > self.genome["max_spread_pips"]:
            logger.debug("VMPM: Spread %.1f too wide", spread)
            return None

        # Daily trade limit
        if self._daily_trade_count >= self.genome["max_daily_trades"]:
            logger.debug("VMPM: Daily trade limit reached")
            return None

        # Run the 7-layer pipeline
        result = self.pipeline.run(
            symbol=symbol,
            ohlcv_by_tf=ohlcv_by_tf,
            closes=closes,
            news_data=news_data,
        )

        if not result.passed:
            logger.debug(
                "VMPM: Pipeline rejected %s at %s — %s",
                symbol, result.stage_reached.value, result.rejection_reason,
            )
            return None

        # Apply session overlap bonus
        score = result.signal_score
        if session.is_overlap:
            score = min(1.0, score * self.genome["overlap_bonus"])

        # Build signal dict for TSAR
        signal = {
            "strategy": self.NAME,
            "version": self.VERSION,
            "symbol": symbol,
            "direction": result.direction,
            "score": score,
            "entry_price": result.entry_price,
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            "rr_ratio": self.genome["default_rr_ratio"],
            "confidence": self._compute_confidence(result),
            "session": session.session.value,
            "trend_alignment": result.trend.alignment,
            "pipeline_stages": result.layer_scores,
            "metadata": {
                "trend_direction": result.trend.direction.value,
                "trend_strength": result.trend.strength,
                "rsi_value": result.rsi.value,
                "rsi_signal": result.rsi.signal.value,
                "candle_pattern": result.candle.pattern.value,
                "fundamental_bias": result.fundamental.value,
                "session_liquidity": session.liquidity.value,
                "is_overlap": session.is_overlap,
            },
        }

        self._daily_trade_count += 1
        logger.info(
            "VMPM SIGNAL: %s %s @ %.2f score=%.3f confidence=%.2f",
            result.direction.upper(), symbol, result.entry_price, score, signal["confidence"],
        )

        return signal

    def check_exit(
        self, position: dict[str, Any], data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check if exit conditions are met.

        Manages:
          - Trailing stop (move SL to breakeven after 1 ATR profit)
          - Partial profit (close 50% at 1.5 ATR)
          - Full exit at TP or trailing stop hit

        Args:
            position: Current position data
            data: Current market data

        Returns:
            Exit signal dict or None.
        """
        symbol = position.get("symbol", "UNKNOWN")
        entry = position.get("entry_price", 0.0)
        current_sl = position.get("stop_loss", 0.0)
        tp = position.get("take_profit", 0.0)
        direction = position.get("direction", "buy")
        current_price = data.get("closes", [0.0])[-1] if data.get("closes") else 0.0

        if not current_price or not entry:
            return None

        closes = data.get("closes", [])
        atr = self._calculate_atr(closes)

        # Calculate P&L
        if direction == "buy":
            pnl_pips = current_price - entry
        else:
            pnl_pips = entry - current_price

        atr_in_profit = pnl_pips / atr if atr > 0 else 0

        # ── Breakeven: Move SL to entry after 1 ATR profit ────────
        breakeven_threshold = self.genome["breakeven_atr_mult"]
        if atr_in_profit >= breakeven_threshold and current_sl != entry:
            new_sl = entry + (atr * 0.1) if direction == "buy" else entry - (atr * 0.1)
            logger.info("VMPM: Moving SL to breakeven for %s", symbol)
            return {
                "action": "modify_stop",
                "new_stop_loss": new_sl,
                "reason": "breakeven",
            }

        # ── Partial profit: Close 50% at 1.5 ATR ─────────────────
        partial_threshold = self.genome["partial_atr_mult"]
        if atr_in_profit >= partial_threshold and not position.get("partial_taken"):
            logger.info("VMPM: Taking partial profit on %s", symbol)
            return {
                "action": "partial_close",
                "close_pct": self.genome["partial_profit_pct"],
                "reason": "partial_profit",
            }

        # ── Full exit at TP ───────────────────────────────────────
        if direction == "buy" and current_price >= tp:
            return {"action": "close", "reason": "take_profit_hit"}
        if direction == "bearish" and current_price <= tp:
            return {"action": "close", "reason": "take_profit_hit"}

        # ── Trailing stop check ───────────────────────────────────
        trailing_atr = self.genome["trailing_stop_atr_mult"]
        if direction == "buy":
            trailing_sl = current_price - (atr * trailing_atr)
            if trailing_sl > current_sl:
                return {
                    "action": "modify_stop",
                    "new_stop_loss": trailing_sl,
                    "reason": "trailing_stop",
                }
        else:
            trailing_sl = current_price + (atr * trailing_atr)
            if trailing_sl < current_sl:
                return {
                    "action": "modify_stop",
                    "new_stop_loss": trailing_sl,
                    "reason": "trailing_stop",
                }

        return None

    def get_risk_params(self) -> dict[str, Any]:
        """Get risk parameters for this strategy.

        Used by RiskGuardian for position sizing and limits.
        """
        return {
            "strategy_name": self.NAME,
            "risk_per_trade_pct": self.genome["risk_per_trade_pct"],
            "max_daily_trades": self.genome["max_daily_trades"],
            "max_concurrent_positions": self.genome["max_concurrent_positions"],
            "min_rr_ratio": self.genome["min_rr_ratio"],
            "max_spread_pips": self.genome["max_spread_pips"],
            "trailing_stop": True,
            "partial_profits": True,
            "news_blackout_minutes": self.genome["news_blackout_minutes"],
            "session_filter": self.genome["enabled_sessions"],
        }

    # ------------------------------------------------------------------
    # Genome Management (for StrategyGeneticist)
    # ------------------------------------------------------------------

    def get_genome(self) -> dict[str, Any]:
        """Get current genome for mutation."""
        return dict(self.genome)

    def set_genome(self, new_genome: dict[str, Any]) -> None:
        """Apply mutated genome from StrategyGeneticist."""
        self.genome.update(new_genome)
        self.pipeline.update_genome(new_genome)
        logger.info("VMPM genome updated with %d mutations", len(new_genome))

    def get_genome_schema(self) -> dict[str, tuple[float, float]]:
        """Get genome parameter ranges for mutation.

        Returns:
            Dict of param_name → (min_value, max_value)
        """
        return {
            "risk_per_trade_pct": (0.5, 5.0),
            "max_daily_trades": (1, 10),
            "min_rr_ratio": (1.5, 4.0),
            "default_rr_ratio": (2.0, 5.0),
            "rsi_period": (7, 21),
            "rsi_oversold": (20, 40),
            "rsi_overbought": (60, 80),
            "trailing_stop_atr_mult": (1.0, 4.0),
            "breakeven_atr_mult": (0.5, 2.0),
            "partial_atr_mult": (1.0, 3.0),
            "trend_ma_fast": (20, 100),
            "trend_ma_slow": (100, 300),
            "min_pipeline_score": (0.4, 0.8),
            "max_spread_pips": (1.0, 10.0),
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _compute_confidence(self, result: PipelineResult) -> float:
        """Compute confidence score (0.0 – 1.0) for the signal."""
        base = result.signal_score

        # Trend alignment bonus
        if result.trend.alignment:
            base = min(1.0, base + 0.1)

        # RSI divergence bonus
        if result.rsi.divergence:
            base = min(1.0, base + 0.1)

        # Strong candlestick pattern bonus
        if result.candle.score >= 0.8:
            base = min(1.0, base + 0.05)

        return round(base, 3)

    @staticmethod
    def _calculate_atr(closes: list[float], period: int = 14) -> float:
        """Simple ATR approximation from closes."""
        if len(closes) < period + 1:
            return 0.0
        changes = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        return sum(changes[-period:]) / period

    def reset_daily_counter(self) -> None:
        """Reset daily trade counter (called at session start)."""
        self._daily_trade_count = 0

    def __repr__(self) -> str:
        return f"VMPMStrategy(v{self.VERSION}, genome_keys={len(self.genome)})"
