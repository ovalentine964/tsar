"""
VMPM Strategy — Main strategy class extending TSAR's BaseStrategy.

The Valentine Money Printing Machine is a multi-layer institutional
strategy that combines:
  1. Session awareness (Sydney, Tokyo, London, New York overlaps)
  2. Fundamental bias (economic calendar, central bank decisions)
  3. Multi-timeframe trend (D1, H4, H1) using 50/200 MA
  4. Support/Resistance mapping (Asian H/L, Daily/Weekly/Monthly/Yearly, OBs)
  5. Entry pipeline: News → Trend → S/R → Retest → RSI → Candlestick → Execute

This module wires all VMPM components together and implements the
BaseStrategy interface for registration in TSAR's StrategyRegistry.
"""

from __future__ import annotations

import logging
from typing import Any

from src.strategy.base import BaseStrategy
from src.strategy.genome import StrategyGenome
from src.strategy.vmpm.session_manager import SessionManager
from src.strategy.vmpm.fundamental_analyzer import FundamentalAnalyzer, FundamentalBias, BiasDirection
from src.strategy.vmpm.trend_detector import TrendDetector, TrendDirection, TrendState
from src.strategy.vmpm.level_mapper import LevelMapper, MappedLevels
from src.strategy.vmpm.entry_pipeline import EntryPipeline, PipelineResult

logger = logging.getLogger(__name__)


class VMPMStrategy(BaseStrategy):
    """Valentine Money Printing Machine — Multi-layer institutional strategy.

    Implements the full VMPM pipeline:
      News → Trend → S/R → Retest → RSI → Candlestick → Execute

    Registered in StrategyRegistry as 'vmpm'.
    Scored by SignalScout. Validated by RiskGuardian.
    Evolved by StrategyGeneticist via genome.
    """

    NAME = "vmpm"
    VERSION = "1.0.0"

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        """Initialize VMPM with optional genome for parameter-driven behavior.

        Args:
            genome: StrategyGenome from YAML. If None, uses defaults.
        """
        if genome is not None:
            self._genome = genome
            self._params = genome.params
            self._config = {
                **genome.metadata,
                "mutable_parameters": {
                    k: {"current": v} for k, v in genome.params.items()
                },
            }
        else:
            self._genome = None
            self._params = {}
            self._config = {}

        # Initialize VMPM components
        self._session_mgr = SessionManager(self._config)
        self._fundamental = FundamentalAnalyzer(self._config)
        self._trend_detector = TrendDetector(self._config)
        self._level_mapper = LevelMapper(self._config)
        self._entry_pipeline = EntryPipeline(self._config)

        logger.info(
            "VMPMStrategy initialized: %d params, %s",
            len(self._params),
            f"genome={genome.name}" if genome else "default config",
        )

    # -- BaseStrategy interface --

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Check VMPM entry conditions.

        Args:
            data: Market data dict expected to contain:
                - symbol (str): Trading pair
                - close (float): Current price
                - atr (float): ATR value
                - rsi (float): RSI value
                - volume_ratio (float): Volume / average
                - d1_closes, h4_closes, h1_closes: Multi-TF close arrays
                - d1_ohlcv, h4_ohlcv, h1_ohlcv: Multi-TF OHLCV bars
                - asian_high, asian_low (optional): Asian session H/L
                - swing_highs, swing_lows (optional): Recent swings

        Returns:
            Signal dict with score, entry_price, stop_loss, take_profit, or None.
        """
        symbol = data.get("symbol", "")
        price = data.get("close", 0.0)
        atr = data.get("atr", 0.0)
        rsi = data.get("rsi", 50.0)
        volume_ratio = data.get("volume_ratio", 1.0)

        if price <= 0 or atr <= 0:
            return None

        try:
            # 1. Session Score
            session_score = self._session_mgr.get_session_score(symbol)
            session_info = self._session_mgr.get_session_info()

            if session_info.liquidity.value == "low" and not session_info.is_overlap:
                logger.debug("VMPM %s: Skipping — low liquidity session", symbol)
                return None

            # 2. Fundamental Bias
            fundamental_bias = self._get_fundamental_bias(data)

            # 3. Multi-Timeframe Trend
            d1_closes = data.get("d1_closes", [])
            h4_closes = data.get("h4_closes", [])
            h1_closes = data.get("h1_closes", [])

            if not d1_closes or not h4_closes or not h1_closes:
                logger.debug("VMPM %s: Insufficient multi-TF data", symbol)
                return None

            trend_state = self._trend_detector.detect(d1_closes, h4_closes, h1_closes)

            if trend_state.direction == TrendDirection.NEUTRAL:
                logger.debug("VMPM %s: Trend neutral — no signal", symbol)
                return None

            # 4. Level Mapping
            d1_ohlcv = data.get("d1_ohlcv", [])
            h4_ohlcv = data.get("h4_ohlcv", [])
            h1_ohlcv = data.get("h1_ohlcv", [])

            mapped_levels = self._level_mapper.map_levels(
                current_price=price,
                d1_ohlcv=d1_ohlcv,
                h4_ohlcv=h4_ohlcv,
                h1_ohlcv=h1_ohlcv,
                asian_high=data.get("asian_high"),
                asian_low=data.get("asian_low"),
                swing_highs=data.get("swing_highs"),
                swing_lows=data.get("swing_lows"),
            )

            # 5. Run Entry Pipeline
            pipeline_result = self._entry_pipeline.evaluate(
                current_price=price,
                fundamental_bias=fundamental_bias,
                trend_state=trend_state,
                mapped_levels=mapped_levels,
                ohlcv=h1_ohlcv if h1_ohlcv else d1_ohlcv,
                rsi=rsi,
                atr=atr,
                session_score=session_score,
                volume_ratio=volume_ratio,
            )

            if not pipeline_result.passed:
                logger.info(
                    "VMPM %s: Pipeline REJECTED (score=%.3f) — %s",
                    symbol, pipeline_result.total_score, pipeline_result.reasoning,
                )
                return None

            # Build Signal
            side = pipeline_result.side
            signal = {
                "side": side,
                "score": round(pipeline_result.total_score, 4),
                "entry_price": pipeline_result.entry_price,
                "stop_loss": pipeline_result.stop_loss,
                "take_profit": pipeline_result.take_profit,
                "atr": atr,
                "trailing_stop_atr_mult": self._get_param("trailing_stop_atr_mult", 1.5),
                "reasoning": pipeline_result.reasoning,
                "components": {
                    "session_score": session_score,
                    "session": session_info.primary_session.value if session_info.primary_session else "none",
                    "is_overlap": session_info.is_overlap,
                    "trend_direction": trend_state.direction.value,
                    "trend_aligned": trend_state.aligned,
                    "trend_strength": round(trend_state.strength, 3),
                    "trend_confluence": round(trend_state.confluence_score, 3),
                    "fundamental_bias": fundamental_bias.direction.value,
                    "fundamental_confidence": round(fundamental_bias.confidence, 3),
                    "nearest_level_type": pipeline_result.nearest_level.level_type.value if pipeline_result.nearest_level else "none",
                    "nearest_level_price": pipeline_result.nearest_level.price if pipeline_result.nearest_level else 0,
                    "candle_pattern": pipeline_result.candle_pattern.value,
                    "pipeline_stages": [
                        {"stage": s.stage.value, "passed": s.passed, "score": round(s.score, 4)}
                        for s in pipeline_result.stages
                    ],
                },
            }

            logger.info(
                "VMPM SIGNAL: %s %s score=%.3f entry=%.5f sl=%.5f tp=%.5f | %s",
                symbol, side, pipeline_result.total_score,
                pipeline_result.entry_price, pipeline_result.stop_loss,
                pipeline_result.take_profit, pipeline_result.reasoning,
            )

            return signal

        except Exception:
            logger.exception("VMPM check_entry failed for %s", symbol)
            return None

    def check_exit(
        self,
        position: dict[str, Any],
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check VMPM exit conditions.

        Exit rules:
          - Hard stop loss
          - Take profit
          - Trailing stop after 1:1 R:R
          - Trend reversal (all MAs flip)

        Args:
            position: Current position data.
            data: Current market data.

        Returns:
            Exit signal dict or None.
        """
        entry_price = position.get("entry_price", 0.0)
        current_price = data.get("close", 0.0)
        atr = data.get("atr", 0.0)
        side = position.get("side", "buy")

        if entry_price <= 0 or atr <= 0:
            return None

        stop_loss = position.get("stop_loss", 0.0)
        take_profit = position.get("take_profit", 0.0)
        trailing_mult = self._get_param("trailing_stop_atr_mult", 1.5)

        if side == "buy":
            risk = entry_price - stop_loss if stop_loss > 0 else atr
            reward = current_price - entry_price

            if stop_loss > 0 and current_price <= stop_loss:
                return {"reason": "stop_loss", "action": "close", "level": stop_loss}

            if take_profit > 0 and current_price >= take_profit:
                return {"reason": "take_profit", "action": "close", "level": take_profit}

            if risk > 0 and reward >= risk:
                highest = position.get("highest_price", current_price)
                trailing_stop = highest - (atr * trailing_mult)
                if current_price <= trailing_stop:
                    return {"reason": "trailing_stop", "action": "close", "level": trailing_stop}

            d1_closes = data.get("d1_closes", [])
            if len(d1_closes) >= 200:
                trend = self._trend_detector.detect(
                    d1_closes,
                    data.get("h4_closes", d1_closes),
                    data.get("h1_closes", d1_closes),
                )
                if trend.direction == TrendDirection.BEARISH and trend.aligned:
                    return {"reason": "trend_reversal", "action": "close", "new_trend": "bearish"}

        if side == "sell":
            risk = stop_loss - entry_price if stop_loss > 0 else atr
            reward = entry_price - current_price

            if stop_loss > 0 and current_price >= stop_loss:
                return {"reason": "stop_loss", "action": "close", "level": stop_loss}

            if take_profit > 0 and current_price <= take_profit:
                return {"reason": "take_profit", "action": "close", "level": take_profit}

            if risk > 0 and reward >= risk:
                lowest = position.get("lowest_price", current_price)
                trailing_stop = lowest + (atr * trailing_mult)
                if current_price >= trailing_stop:
                    return {"reason": "trailing_stop", "action": "close", "level": trailing_stop}

            d1_closes = data.get("d1_closes", [])
            if len(d1_closes) >= 200:
                trend = self._trend_detector.detect(
                    d1_closes,
                    data.get("h4_closes", d1_closes),
                    data.get("h1_closes", d1_closes),
                )
                if trend.direction == TrendDirection.BULLISH and trend.aligned:
                    return {"reason": "trend_reversal", "action": "close", "new_trend": "bullish"}

        return None

    def get_risk_params(self) -> dict[str, Any]:
        """Return risk parameters for this strategy."""
        return {
            "stop_loss_type": "structure_based",
            "stop_loss_atr_buffer": self._get_param("atr_buffer_mult", 0.5),
            "take_profit_rr_ratio": self._get_param("min_rr_ratio", 2.0),
            "trailing_stop_atr_multiple": self._get_param("trailing_stop_atr_mult", 1.5),
            "trailing_trigger_rr": 1.0,
            "breakeven_trigger_rr": 1.0,
            "min_score": self._get_param("min_signal_score", 0.70),
            "max_position_pct": 0.10,
            "risk_per_trade_pct": 0.015,
            "method": "half_kelly",
            "session_aware_sizing": True,
            "partial_exit_enabled": True,
            "partial_exit_schedule": [0.4, 0.3, 0.3],
            "partial_exit_rr_levels": [1.0, 2.0, 3.0],
            "trend_reversal_exit": True,
            "session_end_exit": True,
        }

    # -- Internal helpers --

    def _get_param(self, name: str, default: Any) -> Any:
        """Get parameter from genome params, falling back to default."""
        return self._params.get(name, default)

    def _get_fundamental_bias(self, data: dict[str, Any]) -> FundamentalBias:
        """Get fundamental bias from data or defaults."""
        if "fundamental_bias" in data:
            fb = data["fundamental_bias"]
            if isinstance(fb, FundamentalBias):
                return fb

        macro_score = data.get("macro_alignment", 0.5)

        if macro_score >= 0.6:
            direction = BiasDirection.BULLISH
        elif macro_score <= 0.4:
            direction = BiasDirection.BEARISH
        else:
            direction = BiasDirection.NEUTRAL

        return FundamentalBias(
            direction=direction,
            confidence=abs(macro_score - 0.5) * 2,
            news_clear=data.get("news_clear", True),
            upcoming_events=(),
            blackout_active=False,
            blackout_reason=None,
            event_risk_score=data.get("event_risk_score", 0.0),
            macro_alignment=macro_score,
            reasoning=f"macro_score={macro_score:.2f}",
        )

    # -- Async API (for agent-layer integration) --

    async def analyze_async(
        self,
        symbol: str,
        gateway: Any,
        pricing_engine: Any,
    ) -> dict[str, Any] | None:
        """Full async analysis with live data fetching.

        Used by the agent layer (SignalScout) when it has access
        to the exchange gateway and pricing engine.
        """
        from src.interfaces.types import Timeframe

        try:
            d1_ohlcv = await gateway.get_ohlcv(symbol, Timeframe.D1, limit=250)
            h4_ohlcv = await gateway.get_ohlcv(symbol, Timeframe.H4, limit=100)
            h1_ohlcv = await gateway.get_ohlcv(symbol, Timeframe.H1, limit=100)

            if not d1_ohlcv or len(d1_ohlcv) < 50:
                return None

            d1_closes = [b.close for b in d1_ohlcv]
            h4_closes = [b.close for b in h4_ohlcv] if h4_ohlcv else d1_closes
            h1_closes = [b.close for b in h1_ohlcv] if h1_ohlcv else d1_closes

            current_price = h1_closes[-1]

            rsi = pricing_engine.calculate_rsi(h1_closes, 14)
            atr = pricing_engine.calculate_atr(
                [b.high for b in h1_ohlcv],
                [b.low for b in h1_ohlcv],
                h1_closes,
                14,
            )

            volumes = [b.volume for b in h1_ohlcv]
            avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
            volume_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

            bias = await self._fundamental.analyze(symbol)
            session_score = self._session_mgr.get_session_score(symbol)

            def ohlcv_to_dicts(bars):
                return [
                    {"open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
                    for b in bars
                ]

            trend_state = self._trend_detector.detect(d1_closes, h4_closes, h1_closes)

            mapped_levels = self._level_mapper.map_levels(
                current_price=current_price,
                d1_ohlcv=ohlcv_to_dicts(d1_ohlcv),
                h4_ohlcv=ohlcv_to_dicts(h4_ohlcv),
                h1_ohlcv=ohlcv_to_dicts(h1_ohlcv),
            )

            pipeline_result = self._entry_pipeline.evaluate(
                current_price=current_price,
                fundamental_bias=bias,
                trend_state=trend_state,
                mapped_levels=mapped_levels,
                ohlcv=ohlcv_to_dicts(h1_ohlcv),
                rsi=rsi,
                atr=atr,
                session_score=session_score,
                volume_ratio=volume_ratio,
            )

            if not pipeline_result.passed:
                return None

            return {
                "side": pipeline_result.side,
                "score": round(pipeline_result.total_score, 4),
                "entry_price": pipeline_result.entry_price,
                "stop_loss": pipeline_result.stop_loss,
                "take_profit": pipeline_result.take_profit,
                "atr": atr,
                "symbol": symbol,
                "strategy": self.NAME,
                "reasoning": pipeline_result.reasoning,
                "components": {
                    "session_score": session_score,
                    "trend_direction": trend_state.direction.value,
                    "trend_aligned": trend_state.aligned,
                    "fundamental_bias": bias.direction.value,
                    "candle_pattern": pipeline_result.candle_pattern.value,
                },
            }

        except Exception:
            logger.exception("VMPM analyze_async failed for %s", symbol)
            return None
