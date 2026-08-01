"""
Signal Scout — Scan markets for mean reversion setups.

Cycle: Every 5 minutes (configurable)
Role: TRADE_PREVIEW

Signal scoring weights (from task spec):
  RSI: 40% | S/R proximity: 30% | Volume: 15% | Trend: 15%

Entry logic (Mean Reversion strategy):
  - RSI(14) < 30 at support → BUY signal
  - RSI(14) > 70 at resistance → SELL signal

Subscribes to: tsar:stream:regime, tsar:stream:strategy_mutations
Publishes to: tsar:stream:signals
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from src.agents.base import BaseAgent
from src.interfaces.types import (
    OHLCV,
    BollingerResult,
    MACDResult,
    OrderSide,
    Signal,
    SRLevel,
    SRLevels,
    Timeframe,
)
from src.strategy.factor_library import FactorLibrary

# SECURITY (H-009): Import prompt sanitization for market data
from src.llm.prompts import sanitize_field, validate_llm_output

# ── Domain Tools (Tools-to-Agents Wiring) ──────────────────────────
from src.tools.market_data import MarketDataTools
from src.tools.technical_analysis import TechnicalAnalysisTools
from src.tools.multi_timeframe import MultiTimeframeAnalyzer
from src.tools.volatility import VolatilityAnalyzer
from src.tools.correlation import CorrelationAnalyzer
from src.tools.pattern_recognition import PatternRecognitionTools

if TYPE_CHECKING:
    from src.comms.events import CloudEvent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Scoring Configuration
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ScoringWeights:
    """Signal scoring weights — must sum to 1.0."""

    rsi: float = 0.30
    sr_proximity: float = 0.25
    volume: float = 0.10
    trend: float = 0.10
    multi_timeframe: float = 0.25

    def validate(self) -> None:
        total = self.rsi + self.sr_proximity + self.volume + self.trend + self.multi_timeframe
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total}")


# ═══════════════════════════════════════════════════════════════════════
# Signal Scout Agent
# ═══════════════════════════════════════════════════════════════════════


class SignalScout(BaseAgent):
    """Scan markets for trading signals using technical analysis.

    The SignalScout is the first agent in the trading pipeline.
    Every 5 minutes it:
    1. Fetches OHLCV data from the exchange
    2. Calculates RSI, MACD, Bollinger Bands, S/R levels
    3. Scores the setup using weighted indicators
    4. If score >= threshold, publishes a signal.detected event

    RSI < 30 at support → BUY signal
    RSI > 70 at resistance → SELL signal
    """

    AGENT_NAME = "signal_scout"
    ROLE = "TRADE_PREVIEW"

    PUBLISH_STREAM = "signals"
    SUBSCRIBE_STREAMS = ["regime", "strategy_mutations"]

    # Default scoring weights
    DEFAULT_WEIGHTS = ScoringWeights()

    # Default strategy parameters (can be mutated by Strategy Geneticist)
    DEFAULT_PARAMS = {
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "bb_period": 20,
        "bb_std_dev": 2.0,
        "sr_proximity_pct": 2.0,
        "volume_multiplier": 1.5,
        "volume_lookback": 20,
        "min_signal_score": 0.6,
        "atr_period": 14,
        "ema_trend_period": 50,
        "stop_loss_atr_mult": 1.5,
        "take_profit_atr_mult": 3.0,
        "mtf_enabled": True,
        "mtf_timeframes": ["4h", "1h", "15m"],
        "mtf_confluence_threshold": 0.6,
        # Entry optimization parameters
        "session_timing_enabled": True,
        "pullback_detection_enabled": True,
        "pullback_bounce_pct": 0.003,  # 0.3% bounce from low/high
        "volume_confirmation_candles": 2,  # Consecutive candles above avg
        "news_blackout_enabled": True,
        "limit_order_enabled": True,
        "limit_order_offset_pct": 0.001,  # 0.1% better than current price
    }

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)
        self._symbols = config.get("exchange", {}).get("symbols", ["BTC/USDT"])
        self._cycle_interval = config.get("agents", {}).get("signal_scout", {}).get(
            "cycle_interval_s", 300
        )
        self._last_scan_time: dict[str, float] = {}

        # Strategy parameters — mutable by Strategy Geneticist
        strategy_config = config.get("strategies", {}).get("mean_reversion", {})
        self._params = {**self.DEFAULT_PARAMS, **strategy_config.get("params", {})}

        # Scoring weights
        weights_config = config.get("agents", {}).get("signal_scout", {}).get("weights", {})
        self._weights = ScoringWeights(
            rsi=weights_config.get("rsi", self.DEFAULT_WEIGHTS.rsi),
            sr_proximity=weights_config.get("sr_proximity", self.DEFAULT_WEIGHTS.sr_proximity),
            volume=weights_config.get("volume", self.DEFAULT_WEIGHTS.volume),
            trend=weights_config.get("trend", self.DEFAULT_WEIGHTS.trend),
            multi_timeframe=weights_config.get("multi_timeframe", self.DEFAULT_WEIGHTS.multi_timeframe),
        )
        self._weights.validate()

        # Engine references (lazy-initialized)
        self._gateway = None
        self._pricing_engine = None

        # Factor library integration (G5)
        factor_config = config.get("factor_library", {})
        if factor_config.get("enabled", False):
            self._factor_library = FactorLibrary(
                db_path=factor_config.get("db_path", ":memory:")
            )
            self._use_factors = True
            logger.info(
                "FactorLibrary enabled with %d factors",
                len(self._factor_library.list_factors()),
            )
        else:
            self._factor_library = None
            self._use_factors = False

        # ── Domain Tools (initialized in on_initialize) ───────
        self._market_data_tools: MarketDataTools | None = None
        self._ta_tools: TechnicalAnalysisTools | None = None
        self._mtf_analyzer: MultiTimeframeAnalyzer | None = None
        self._volatility_analyzer: VolatilityAnalyzer | None = None
        self._correlation_analyzer: CorrelationAnalyzer | None = None
        self._pattern_tools: PatternRecognitionTools | None = None

        # LLM availability tracking (H-003)
        # If LLM is unavailable, signal generation degrades to pure
        # statistical/technical analysis — never blocks signal generation.
        self._llm_available: bool = True
        self._llm_failure_count: int = 0
        self._llm_max_failures: int = 3  # After this many failures, disable LLM
        self._statistical_only_mode: bool = False

    async def on_initialize(self) -> None:
        """Initialize exchange gateway, pricing engine, and domain tools."""
        from src.interfaces import get_exchange_gateway, get_pricing_engine

        self._gateway = get_exchange_gateway()
        self._pricing_engine = get_pricing_engine()

        # Initialize domain tools
        self._market_data_tools = MarketDataTools(
            gateway=self._gateway, config=self.config.get("market_data", {}),
        )
        self._ta_tools = TechnicalAnalysisTools(config=self.config)
        self._mtf_analyzer = MultiTimeframeAnalyzer(config=self.config)
        self._volatility_analyzer = VolatilityAnalyzer(config=self.config)
        self._correlation_analyzer = CorrelationAnalyzer(config=self.config)
        self._pattern_tools = PatternRecognitionTools(config=self.config)

        logger.info(
            "SignalScout initialized: symbols=%s, cycle_interval=%ds, "
            "tools=[market_data, ta, mtf, volatility, correlation, pattern_recognition]",
            self._symbols, self._cycle_interval,
        )

    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        """Handle incoming events from subscribed streams.

        - regime: Update internal regime state (affects scoring)
        - strategy_mutations: Update strategy parameters
        """
        if stream == "strategy_mutations" and event.type == "tsar.strategy.mutated.v1":
            params = event.data.get("params", {})
            self._params.update(params)
            logger.info("Strategy parameters updated: %s", list(params.keys()))

        elif stream == "regime" and event.type == "tsar.regime.changed.v1":
            regime = event.data.get("regime", "unknown")
            logger.info("Market regime changed to: %s", regime)

    async def run_cycle(self) -> None:
        """Scan configured symbols for trading setups.

        Only scans if enough time has elapsed since last scan for each symbol.
        """
        now = time.monotonic()

        for symbol in self._symbols:
            last_scan = self._last_scan_time.get(symbol, 0)
            if now - last_scan < self._cycle_interval:
                continue

            try:
                await self._scan_symbol(symbol)
                self._last_scan_time[symbol] = now
            except Exception:
                logger.exception("Error scanning %s", symbol)

    async def _scan_symbol(self, symbol: str) -> None:
        """Scan a single symbol for trading signals.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
        """
        logger.info("Scanning %s for signals...", symbol)

        # ── Entry Optimization: Session Timing Gate ──────────────
        if self._params.get("session_timing_enabled", True):
            from src.agents.trade_manager import SessionTiming
            session_allowed, session_reason = SessionTiming.is_entry_allowed()
            if not session_allowed:
                logger.info("  %s: Skipping — %s", symbol, session_reason)
                return

        # ── Entry Optimization: News Blackout Gate ───────────────
        if self._params.get("news_blackout_enabled", True):
            try:
                from src.tools.market_calendar import MarketCalendar
                calendar = MarketCalendar(config=self.config.get("market_calendar", {}))
                snapshot = await calendar.get_calendar(days_ahead=1)
                from src.agents.trade_manager import NewsProximity
                blocked, reason, risk_mult = NewsProximity.check_news_blackout(snapshot)
                if blocked:
                    logger.info("  %s: Skipping — %s", symbol, reason)
                    return
            except Exception:
                logger.debug("News blackout check failed for %s", symbol, exc_info=True)

        # Fetch OHLCV data (1h candles, 100 bars)
        ohlcv: list[OHLCV] = await self._gateway.get_ohlcv(
            symbol, Timeframe.H1, limit=100
        )
        if len(ohlcv) < 50:
            logger.warning("Insufficient data for %s: %d candles", symbol, len(ohlcv))
            return

        closes = [bar.close for bar in ohlcv]
        highs = [bar.high for bar in ohlcv]
        lows = [bar.low for bar in ohlcv]
        volumes = [bar.volume for bar in ohlcv]
        current_price = closes[-1]

        # ── Calculate Indicators (via pricing engine + domain tools) ──
        rsi = self._pricing_engine.calculate_rsi(closes, self._params["rsi_period"])
        macd: MACDResult = self._pricing_engine.calculate_macd(
            closes,
            self._params["macd_fast"],
            self._params["macd_slow"],
            self._params["macd_signal"],
        )
        bollinger: BollingerResult = self._pricing_engine.calculate_bollinger(
            closes, self._params["bb_period"], self._params["bb_std_dev"]
        )
        sr_levels: SRLevels = self._pricing_engine.detect_support_resistance(ohlcv)
        atr = self._pricing_engine.calculate_atr(
            highs, lows, closes, self._params["atr_period"]
        )
        ema_trend = self._pricing_engine.calculate_ema(
            closes, self._params["ema_trend_period"]
        )

        # ── Advanced Analysis via Domain Tools ──────────────────────
        # Volatility regime analysis
        vol_regime = None
        if self._volatility_analyzer:
            try:
                vol_regime = self._volatility_analyzer.classify_volatility_regime(ohlcv)
                logger.info(
                    "  %s: volatility regime=%s (factor=%.2f)",
                    symbol, vol_regime.regime, vol_regime.recommended_position_size_factor,
                )
            except Exception:
                logger.debug("Volatility regime analysis failed for %s", symbol, exc_info=True)

        # Pattern recognition scan
        patterns_detected: list[str] = []
        if self._pattern_tools:
            try:
                chart_patterns = self._pattern_tools.detect_chart_patterns(ohlcv)
                candle_patterns = self._pattern_tools.detect_candlestick_patterns(ohlcv)
                for p in chart_patterns:
                    if p.confidence > 0.6:
                        patterns_detected.append(f"chart:{p.pattern}({p.direction},{p.confidence:.2f})")
                for p in candle_patterns:
                    if p.reliability > 0.5:
                        patterns_detected.append(f"candle:{p.pattern}({p.direction},{p.reliability:.2f})")
                if patterns_detected:
                    logger.info("  %s: patterns detected: %s", symbol, patterns_detected)
            except Exception:
                logger.debug("Pattern recognition failed for %s", symbol, exc_info=True)

        logger.info(
            "  %s: price=%.2f rsi=%.1f atr=%.2f",
            symbol, current_price, rsi, atr,
        )

        # ── Determine Signal Direction ────────────────────────────
        # RSI < 30 at support → BUY
        # RSI > 70 at resistance → SELL
        signal_side: OrderSide | None = None
        reasoning_parts: list[str] = []

        if rsi < self._params["rsi_oversold"]:
            # Check if near support
            nearest_support = self._find_nearest_level(
                current_price, sr_levels.supports, "support"
            )
            if nearest_support:
                proximity_pct = abs(current_price - nearest_support.price) / current_price * 100
                if proximity_pct <= self._params["sr_proximity_pct"]:
                    signal_side = OrderSide.BUY
                    reasoning_parts.append(
                        f"RSI({self._params['rsi_period']})={rsi:.1f} < "
                        f"{self._params['rsi_oversold']} (oversold)"
                    )
                    reasoning_parts.append(
                        f"Near support at {nearest_support.price:.2f} "
                        f"({proximity_pct:.1f}% away, strength={nearest_support.strength:.2f})"
                    )

        elif rsi > self._params["rsi_overbought"]:
            # Check if near resistance
            nearest_resistance = self._find_nearest_level(
                current_price, sr_levels.resistances, "resistance"
            )
            if nearest_resistance:
                proximity_pct = abs(current_price - nearest_resistance.price) / current_price * 100
                if proximity_pct <= self._params["sr_proximity_pct"]:
                    signal_side = OrderSide.SELL
                    reasoning_parts.append(
                        f"RSI({self._params['rsi_period']})={rsi:.1f} > "
                        f"{self._params['rsi_overbought']} (overbought)"
                    )
                    reasoning_parts.append(
                        f"Near resistance at {nearest_resistance.price:.2f} "
                        f"({proximity_pct:.1f}% away, strength={nearest_resistance.strength:.2f})"
                    )

        if signal_side is None:
            logger.info("  %s: No signal (RSI=%.1f, no S/R proximity)", symbol, rsi)
            return

        # ── Entry Optimization: Pullback Confirmation ──────────────
        if self._params.get("pullback_detection_enabled", True):
            pullback_confirmed = self._check_pullback_confirmation(
                ohlcv=ohlcv,
                signal_side=signal_side,
                current_price=current_price,
                bounce_pct=self._params.get("pullback_bounce_pct", 0.003),
            )
            if not pullback_confirmed:
                logger.info("  %s: No pullback confirmation — waiting for bounce", symbol)
                return

        # ── Entry Optimization: Enhanced Volume Confirmation ─────────
        volume_score_adj = self._check_volume_confirmation(
            volumes=volumes,
            lookback=self._params["volume_lookback"],
            multiplier=self._params["volume_multiplier"],
            confirmation_candles=self._params.get("volume_confirmation_candles", 2),
        )
        if volume_score_adj < 0:
            logger.info("  %s: Volume too low (adj=%.2f) — skipping", symbol, volume_score_adj)
            return

        # ── Multi-Timeframe Confluence (via tool) ─────────────
        mtf_score = 0.0
        if self._params.get("mtf_enabled", True):
            try:
                if self._mtf_analyzer and self._gateway:
                    # Use MultiTimeframeAnalyzer tool
                    tf_data: dict[str, list[OHLCV]] = {}
                    for tf in self._params.get("mtf_timeframes", ["4h", "1h", "15m"]):
                        tf_ohlcv = await self._gateway.get_ohlcv(symbol, Timeframe(tf), limit=60)
                        if tf_ohlcv and len(tf_ohlcv) >= 30:
                            tf_data[tf] = tf_ohlcv
                    if tf_data:
                        mtf_result = await self._mtf_analyzer.analyze(symbol, tf_data)
                        # Confluence score: average signal strength weighted by timeframe
                        if mtf_result and mtf_result.confluence_zones:
                            mtf_score = min(1.0, len(mtf_result.confluence_zones) * 0.2)
                        logger.info("  %s: MTF tool confluence=%.3f", symbol, mtf_score)
                else:
                    # Fallback to inline computation
                    mtf_score = await self._compute_mtf_confluence(symbol, signal_side)
                    logger.info("  %s: MTF inline confluence=%.3f", symbol, mtf_score)
            except Exception:
                logger.debug("MTF computation failed for %s", symbol, exc_info=True)

        # ── Score the Setup ───────────────────────────────────────
        score, score_breakdown = self._score_setup(
            rsi=rsi,
            current_price=current_price,
            sr_levels=sr_levels,
            volumes=volumes,
            macd=macd,
            ema_trend=ema_trend,
            side=signal_side,
            mtf_score=mtf_score,
        )

        # ── Factor-Enhanced Scoring (G5) ───────────────────────────
        if self._use_factors and self._factor_library:
            try:
                ohlcv_df = pd.DataFrame([
                    {"open": b.open, "high": b.high, "low": b.low,
                     "close": b.close, "volume": b.volume}
                    for b in ohlcv
                ])
                factor_adj = self._compute_factor_adjustment(ohlcv_df, signal_side)
                adjusted_score = score * (1.0 + 0.2 * factor_adj)
                adjusted_score = max(0.0, min(1.0, adjusted_score))
                score_breakdown["factor_adjustment"] = round(factor_adj * 0.2, 4)
                score = adjusted_score
                logger.info(
                    "  %s: Factor adjustment=%.4f, score %.3f → %.3f",
                    symbol, factor_adj, score / (1.0 + 0.2 * factor_adj), score,
                )
            except Exception:
                logger.warning("Factor computation failed for %s", symbol, exc_info=True)

        logger.info(
            "  %s: Signal candidate %s score=%.3f breakdown=%s",
            symbol, signal_side.value, score, score_breakdown,
        )

        if score < self._params["min_signal_score"]:
            logger.info(
                "  %s: Score %.3f below threshold %.3f — skipping",
                symbol, score, self._params["min_signal_score"],
            )
            return

        # ── Calculate Entry, Stop-Loss, Take-Profit ───────────────
        if signal_side == OrderSide.BUY:
            entry_price = current_price
            stop_loss = entry_price - (atr * self._params["stop_loss_atr_mult"])
            take_profit = entry_price + (atr * self._params["take_profit_atr_mult"])
        else:
            entry_price = current_price
            stop_loss = entry_price + (atr * self._params["stop_loss_atr_mult"])
            take_profit = entry_price - (atr * self._params["take_profit_atr_mult"])

        # ── Build and Publish Signal ──────────────────────────────
        signal_id = f"sig-{uuid.uuid4().hex[:12]}"

        # SECURITY (H-009): Sanitize reasoning before storing/using in prompts.
        # Market data (symbol names, price strings) could contain injection payloads.
        sanitized_reasoning = " | ".join(sanitize_field(r) for r in reasoning_parts)
        sanitized_symbol = sanitize_field(symbol)

        # Validate: symbol must be a clean trading pair (alphanumeric + / + . only)
        if not re.match(r"^[A-Z0-9/.\-]{1,20}$", sanitized_symbol):
            logger.warning("Rejected signal with invalid symbol: %r", symbol)
            return

        signal = Signal(
            signal_id=signal_id,
            symbol=sanitized_symbol,
            side=signal_side,
            score=score,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy="mean_reversion",
            reasoning=sanitized_reasoning,
            metadata={
                "rsi": rsi,
                "atr": atr,
                "macd_histogram": macd.histogram[-1] if macd.histogram else 0,
                "bb_upper": bollinger.upper[-1] if bollinger.upper else 0,
                "bb_lower": bollinger.lower[-1] if bollinger.lower else 0,
                "score_breakdown": score_breakdown,
                "ema_trend": ema_trend[-1] if ema_trend else 0,
                "timeframe": "1h",
                "volatility_regime": vol_regime.regime if vol_regime else "unknown",
                "vol_position_factor": vol_regime.recommended_position_size_factor if vol_regime else 1.0,
                "patterns_detected": patterns_detected,
            },
            timestamp=datetime.now(UTC),
        )

        # ── Deterministic Validation (C-017) ─────────────────────
        validation = self._validate_signal(
            signal_side=signal_side,
            score=score,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rsi=rsi,
            closes=closes,
            volumes=volumes,
            atr=atr,
        )
        if not validation["passed"]:
            logger.warning(
                "  %s: Signal REJECTED by validation: %s",
                symbol, validation["reasons"],
            )
            return

        logger.info(
            "🎯 SIGNAL DETECTED: %s %s score=%.3f entry=%.2f sl=%.2f tp=%.2f",
            symbol, signal_side.value, score, entry_price, stop_loss, take_profit,
        )

        # Publish signal.detected event
        await self.publish_event(
            stream="signals",
            event_type="tsar.signal.detected.v1",
            data=self._signal_to_dict(signal),
            priority=1,  # High priority — trading signal
            risk_level="LOW",
        )

    def _score_setup(
        self,
        rsi: float,
        current_price: float,
        sr_levels: SRLevels,
        volumes: list[float],
        macd: MACDResult,
        ema_trend: list[float],
        side: OrderSide,
        mtf_score: float = 0.0,
    ) -> tuple[float, dict[str, float]]:
        """Score a potential setup 0-1 based on weighted indicators.

        Scoring breakdown:
        - RSI (30%): How extreme the RSI is
        - S/R proximity (25%): How close to a key level
        - Volume (10%): Volume confirmation
        - Trend (10%): MACD and EMA alignment
        - Multi-timeframe (25%): Cross-timeframe signal confluence

        Args:
            rsi: Current RSI value.
            current_price: Current market price.
            sr_levels: Detected support/resistance levels.
            volumes: Recent volume data.
            macd: MACD indicator result.
            ema_trend: EMA trend line values.
            side: Signal direction (BUY or SELL).

        Returns:
            Tuple of (total_score, score_breakdown_dict).
        """
        breakdown: dict[str, float] = {}

        # ── RSI Score (40%) ───────────────────────────────────────
        # More extreme RSI → higher score
        # BUY: RSI 30→0 maps to 0→1
        # SELL: RSI 70→100 maps to 0→1
        if side == OrderSide.BUY:
            rsi_score = max(0, min(1, (self._params["rsi_oversold"] - rsi) / self._params["rsi_oversold"]))
        else:
            rsi_score = max(0, min(1, (rsi - self._params["rsi_overbought"]) / (100 - self._params["rsi_overbought"])))
        breakdown["rsi"] = rsi_score * self._weights.rsi

        # ── S/R Proximity Score (30%) ─────────────────────────────
        # Closer to key level → higher score
        levels = sr_levels.supports if side == OrderSide.BUY else sr_levels.resistances

        best_sr_score = 0.0
        for level in levels:
            proximity_pct = abs(current_price - level.price) / current_price * 100
            if proximity_pct <= self._params["sr_proximity_pct"]:
                # Within threshold — score based on proximity and strength
                proximity_score = 1.0 - (proximity_pct / self._params["sr_proximity_pct"])
                sr_score = (proximity_score * 0.6) + (level.strength * 0.4)
                best_sr_score = max(best_sr_score, sr_score)

        breakdown["sr_proximity"] = best_sr_score * self._weights.sr_proximity

        # ── Volume Score (15%) ────────────────────────────────────
        # Volume > X times average → higher score
        volume_score = 0.0
        lookback = self._params["volume_lookback"]
        if len(volumes) >= lookback:
            avg_vol = sum(volumes[-lookback:]) / lookback
            if avg_vol > 0:
                vol_ratio = volumes[-1] / avg_vol
                if vol_ratio >= self._params["volume_multiplier"]:
                    # Score: 0 at multiplier, 1 at 2x multiplier
                    volume_score = min(1.0, (vol_ratio - self._params["volume_multiplier"]) / self._params["volume_multiplier"] + 0.5)
        breakdown["volume"] = volume_score * self._weights.volume

        # ── Trend Score (15%) ─────────────────────────────────────
        # MACD histogram direction + EMA alignment
        trend_score = 0.0

        # MACD histogram check
        if len(macd.histogram) >= 2:
            hist_current = macd.histogram[-1]
            hist_prev = macd.histogram[-2]
            if side == OrderSide.BUY:
                # Bullish: histogram turning up from negative
                if hist_current > hist_prev and hist_current < 0:
                    trend_score += 0.5
                elif hist_current > 0:
                    trend_score += 0.3
            else:
                # Bearish: histogram turning down from positive
                if hist_current < hist_prev and hist_current > 0:
                    trend_score += 0.5
                elif hist_current < 0:
                    trend_score += 0.3

        # EMA alignment
        if ema_trend:
            ema_val = ema_trend[-1]
            if side == OrderSide.BUY and current_price > ema_val:
                trend_score += 0.5  # Price above EMA for buy
            elif side == OrderSide.SELL and current_price < ema_val:
                trend_score += 0.5  # Price below EMA for sell

        trend_score = min(1.0, trend_score)
        breakdown["trend"] = trend_score * self._weights.trend

        # ── Multi-Timeframe Score ─────────────────────────────
        breakdown["multi_timeframe"] = mtf_score * self._weights.multi_timeframe

        # ── Total ─────────────────────────────────────────────────
        total = sum(breakdown.values())
        return min(total, 1.0), breakdown

    def _find_nearest_level(
        self,
        price: float,
        levels: tuple[SRLevel, ...],
        level_type: str,
    ) -> SRLevel | None:
        """Find the nearest S/R level to the current price.

        Args:
            price: Current price.
            levels: Available S/R levels.
            level_type: "support" or "resistance".

        Returns:
            Nearest SRLevel within proximity threshold, or None.
        """
        if not levels:
            return None

        best: SRLevel | None = None
        best_distance = float("inf")

        for level in levels:
            distance = abs(price - level.price)
            if distance < best_distance:
                best_distance = distance
                best = level

        return best

    async def _compute_mtf_confluence(
        self,
        symbol: str,
        side: OrderSide,
    ) -> float:
        """Compute multi-timeframe signal confluence.

        Analyzes multiple timeframes to confirm signal direction:
        - 4h: Context trend (is the higher TF aligned?)
        - 1h: Signal trend (is the entry TF trending correctly?)
        - 15m: Entry timing (is the lower TF showing momentum?)

        Returns a confluence score in [0, 1]:
        - 1.0: All timeframes strongly agree
        - 0.5: Mixed signals
        - 0.0: All timeframes disagree
        """
        timeframes = self._params.get("mtf_timeframes", ["4h", "1h", "15m"])
        tf_signals: dict[str, float] = {}

        for tf in timeframes:
            try:
                ohlcv = await self._gateway.get_ohlcv(symbol, Timeframe(tf), limit=60)
                if len(ohlcv) < 30:
                    continue

                closes = [bar.close for bar in ohlcv]

                # EMA trend direction
                ema_short = self._pricing_engine.calculate_ema(closes, 10)
                ema_long = self._pricing_engine.calculate_ema(closes, 30)

                # RSI for momentum
                rsi_val = self._pricing_engine.calculate_rsi(closes, 14)

                # Score this timeframe
                tf_score = 0.5  # Neutral baseline

                # EMA alignment (0.5 weight)
                if ema_short and ema_long and len(ema_short) > 0 and len(ema_long) > 0:
                    if side == OrderSide.BUY:
                        if ema_short[-1] > ema_long[-1]:
                            tf_score += 0.25  # Bullish EMA alignment
                        elif ema_short[-1] < ema_long[-1]:
                            tf_score -= 0.2  # Bearish divergence
                    else:
                        if ema_short[-1] < ema_long[-1]:
                            tf_score += 0.25  # Bearish EMA alignment
                        elif ema_short[-1] > ema_long[-1]:
                            tf_score -= 0.2  # Bullish divergence

                # EMA slope (0.2 weight)
                if ema_short and len(ema_short) >= 5:
                    prev = ema_short[-5]
                    if prev > 0:
                        slope = (ema_short[-1] - prev) / prev * 100
                        if side == OrderSide.BUY and slope > 0.1:
                            tf_score += 0.15
                        elif side == OrderSide.SELL and slope < -0.1:
                            tf_score += 0.15

                # RSI confirmation (0.3 weight)
                if rsi_val is not None:
                    if side == OrderSide.BUY:
                        if rsi_val < 40:
                            tf_score += 0.1  # Oversold on this TF
                        elif rsi_val > 60:
                            tf_score -= 0.1  # Overbought contradicts
                    else:
                        if rsi_val > 60:
                            tf_score += 0.1  # Overbought on this TF
                        elif rsi_val < 40:
                            tf_score -= 0.1  # Oversold contradicts

                tf_signals[tf] = max(0.0, min(1.0, tf_score))

            except Exception as e:
                logger.debug("MTF analysis failed for %s %s: %s", symbol, tf, e)

        if not tf_signals:
            return 0.0

        # Confluence: weighted average with higher TF getting more weight
        tf_weights = {"4h": 0.4, "1h": 0.35, "15m": 0.25}
        total_weight = sum(tf_weights.get(tf, 0.2) for tf in tf_signals)
        if total_weight == 0:
            return 0.0

        confluence = sum(
            tf_signals[tf] * tf_weights.get(tf, 0.2) for tf in tf_signals
        ) / total_weight

        # Bonus for agreement: if all timeframes agree, boost score
        all_bullish = all(v > 0.5 for v in tf_signals.values())
        all_bearish = all(v < 0.5 for v in tf_signals.values())
        if all_bullish or all_bearish:
            confluence = min(1.0, confluence * 1.15)  # 15% agreement bonus

        return round(confluence, 3)

    # ── Entry Optimization: Pullback Detection ─────────────────────

    def _check_pullback_confirmation(
        self,
        ohlcv: list[OHLCV],
        signal_side: OrderSide,
        current_price: float,
        bounce_pct: float = 0.003,
    ) -> bool:
        """Check if price has shown pullback confirmation.

        For BUY: Price must have bounced off recent low (close > low + bounce%)
        For SELL: Price must have rejected from recent high (close < high - bounce%)

        This avoids "catching a falling knife" — we wait for the bounce.

        Args:
            ohlcv: Recent OHLCV data.
            signal_side: Signal direction.
            current_price: Current price.
            bounce_pct: Minimum bounce percentage (default 0.3%).

        Returns:
            True if pullback confirmation detected.
        """
        if len(ohlcv) < 3:
            return True  # Not enough data, allow trade

        # Check last 3 candles for bounce pattern
        recent = ohlcv[-3:]

        if signal_side == OrderSide.BUY:
            # Look for bounce off low: current close > recent low * (1 + bounce_pct)
            recent_low = min(bar.low for bar in recent)
            bounce_threshold = recent_low * (1.0 + bounce_pct)
            confirmed = current_price >= bounce_threshold

            if confirmed:
                logger.info(
                    "  Pullback confirmed: low=%.2f, threshold=%.2f, price=%.2f",
                    recent_low, bounce_threshold, current_price,
                )
            return confirmed

        else:  # SELL
            # Look for rejection from high: current close < recent high * (1 - bounce_pct)
            recent_high = max(bar.high for bar in recent)
            bounce_threshold = recent_high * (1.0 - bounce_pct)
            confirmed = current_price <= bounce_threshold

            if confirmed:
                logger.info(
                    "  Pullback confirmed: high=%.2f, threshold=%.2f, price=%.2f",
                    recent_high, bounce_threshold, current_price,
                )
            return confirmed

    def _check_volume_confirmation(
        self,
        volumes: list[float],
        lookback: int = 20,
        multiplier: float = 1.5,
        confirmation_candles: int = 2,
    ) -> float:
        """Check volume confirmation with graduated scoring.

        Volume Score Ladder:
          - < 0.8x avg: REJECT (-1.0)
          - 0.8-1.0x avg: 0.0 score (weak)
          - 1.0-1.5x avg: 0.3 score (moderate)
          - 1.5-2.0x avg: 0.6 score (good)
          - 2.0-3.0x avg: 0.8 score (strong)
          - > 3.0x avg: 1.0 score (institutional)

        Also requires volume above average for N consecutive candles.

        Args:
            volumes: Recent volume data.
            lookback: Period for average calculation.
            multiplier: Minimum volume multiplier.
            confirmation_candles: Consecutive candles above avg required.

        Returns:
            Volume score (0-1) or -1 if rejected.
        """
        if len(volumes) < lookback:
            return 0.5  # Neutral if insufficient data

        avg_vol = sum(volumes[-lookback:]) / lookback
        if avg_vol <= 0:
            return 0.0

        # Check consecutive candles above average
        recent_vols = volumes[-confirmation_candles:]
        consecutive_above = all(v >= avg_vol for v in recent_vols)

        if not consecutive_above:
            logger.debug(
                "Volume not confirmed: need %d consecutive above avg, "
                "recent=%s, avg=%.2f",
                confirmation_candles,
                [f"{v:.2f}" for v in recent_vols],
                avg_vol,
            )
            return -1.0  # Reject

        # Graduated scoring
        current_vol = volumes[-1]
        vol_ratio = current_vol / avg_vol

        if vol_ratio < 0.8:
            return -1.0  # Reject — below average
        elif vol_ratio < 1.0:
            return 0.0  # Weak
        elif vol_ratio < 1.5:
            return 0.3  # Moderate
        elif vol_ratio < 2.0:
            return 0.6  # Good
        elif vol_ratio < 3.0:
            return 0.8  # Strong
        else:
            return 1.0  # Institutional

    def _compute_factor_adjustment(
        self,
        ohlcv_df: pd.DataFrame,
        side: OrderSide,
    ) -> float:
        """Compute factor-based signal adjustment in [-1, 1].

        Uses RSI, BB %B, MFI, and ADX from FactorLibrary.
        Positive adjustment = reinforces the signal direction.
        Negative adjustment = contradicts the signal.

        Args:
            ohlcv_df: OHLCV DataFrame for factor computation.
            side: Signal direction (BUY or SELL).

        Returns:
            Composite factor signal in [-1, 1].
        """
        lib = self._factor_library
        assert lib is not None

        # Compute key factors
        rsi_val = float(lib.compute("rsi", ohlcv_df).iloc[-1])
        bb_val = float(lib.compute("bb_pct_b", ohlcv_df).iloc[-1])
        mfi_val = float(lib.compute("mfi", ohlcv_df).iloc[-1])
        adx_val = float(lib.compute("adx", ohlcv_df).iloc[-1])

        # Normalize to [-1, 1]
        rsi_signal = (rsi_val - 50.0) / 50.0       # -1 oversold, +1 overbought
        bb_signal = (bb_val - 0.5) * 2.0            # -1 lower band, +1 upper band
        mfi_signal = (mfi_val - 50.0) / 50.0        # -1 oversold, +1 overbought

        # For mean reversion: contrarian signals are bullish for BUY
        # ADX > 25 means trending (bad for mean reversion) → penalize
        adx_penalty = max(0.0, (adx_val - 25.0) / 75.0)  # 0 at 25, 1 at 100

        # Composite: mean-reversion is contrarian
        # For BUY: low RSI/BB/MFI = good (negative values = positive signal)
        # For SELL: high RSI/BB/MFI = good (positive values = positive signal)
        raw_composite = -(rsi_signal * 0.4 + bb_signal * 0.3 + mfi_signal * 0.3)

        # Flip sign for SELL signals
        if side == OrderSide.SELL:
            raw_composite = -raw_composite

        # Penalize if market is trending (mean reversion works in ranges)
        composite = raw_composite * (1.0 - 0.5 * adx_penalty)

        return max(-1.0, min(1.0, composite))

    def _validate_signal(
        self,
        signal_side: OrderSide,
        score: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        rsi: float,
        closes: list[float],
        volumes: list[float],
        atr: float,
    ) -> dict[str, Any]:
        """Deterministic signal validation — catch hallucinated/invalid signals.

        Validates every signal against hard statistical bounds before publishing.
        This is the defense layer against LLM hallucinations and numerical errors.

        Returns:
            Dict with 'passed' (bool) and 'reasons' (list of failure reasons).
        """
        reasons: list[str] = []

        # 1. Score bounds [0, 1]
        if not (0.0 <= score <= 1.0):
            reasons.append(f"Score {score:.4f} outside [0, 1]")

        # 2. RSI bounds [0, 100]
        if not (0.0 <= rsi <= 100.0):
            reasons.append(f"RSI {rsi:.1f} outside [0, 100]")

        # 3. Entry price must be positive
        if entry_price <= 0:
            reasons.append(f"Entry price {entry_price} is non-positive")

        # 4. Stop-loss on correct side of entry
        if signal_side == OrderSide.BUY:
            if stop_loss >= entry_price:
                reasons.append(
                    f"BUY stop-loss {stop_loss:.2f} >= entry {entry_price:.2f}"
                )
            if take_profit <= entry_price:
                reasons.append(
                    f"BUY take-profit {take_profit:.2f} <= entry {entry_price:.2f}"
                )
        else:
            if stop_loss <= entry_price:
                reasons.append(
                    f"SELL stop-loss {stop_loss:.2f} <= entry {entry_price:.2f}"
                )
            if take_profit >= entry_price:
                reasons.append(
                    f"SELL take-profit {take_profit:.2f} >= entry {entry_price:.2f}"
                )

        # 5. Risk:Reward ratio must be >= 1.0
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        if risk > 0:
            rr_ratio = reward / risk
            if rr_ratio < 1.0:
                reasons.append(f"R:R ratio {rr_ratio:.2f} < 1.0 (risk={risk:.2f}, reward={reward:.2f})")

        # 6. Stop-loss/take-profit not unreasonably far (> 20% of price)
        if entry_price > 0:
            sl_pct = abs(entry_price - stop_loss) / entry_price
            tp_pct = abs(take_profit - entry_price) / entry_price
            if sl_pct > 0.20:
                reasons.append(f"Stop-loss {sl_pct*100:.1f}% from entry (max 20%)")
            if tp_pct > 0.50:
                reasons.append(f"Take-profit {tp_pct*100:.1f}% from entry (max 50%)")

        # 7. Statistical bound check — entry price within 3σ of recent mean
        if len(closes) >= 20:
            recent = closes[-20:]
            mean_price = float(np.mean(recent))
            std_price = float(np.std(recent))
            if std_price > 0:
                z_score = abs(entry_price - mean_price) / std_price
                if z_score > 3.0:
                    reasons.append(
                        f"Entry price z-score {z_score:.1f} > 3σ from 20-bar mean"
                    )

        # 8. ATR reasonableness — ATR shouldn't exceed 15% of price
        if entry_price > 0 and atr > 0:
            atr_pct = atr / entry_price
            if atr_pct > 0.15:
                reasons.append(f"ATR {atr_pct*100:.1f}% of price (max 15%)")

        return {"passed": len(reasons) == 0, "reasons": reasons}

    # ── LLM Fallback (H-003) ────────────────────────────────

    def check_llm_availability(self) -> bool:
        """Check if LLM is available for signal enhancement.

        Returns True if LLM is available, False if running in
        statistical-only mode.
        """
        return self._llm_available and not self._statistical_only_mode

    def report_llm_failure(self) -> None:
        """Report an LLM failure. After max failures, switch to statistical-only."""
        self._llm_failure_count += 1
        logger.warning(
            "LLM failure %d/%d — %s",
            self._llm_failure_count,
            self._llm_max_failures,
            "switching to statistical-only mode"
            if self._llm_failure_count >= self._llm_max_failures
            else "still attempting LLM",
        )
        if self._llm_failure_count >= self._llm_max_failures:
            self._llm_available = False
            self._statistical_only_mode = True
            logger.warning(
                "SignalScout: LLM unavailable after %d failures — "
                "running in PURE STATISTICAL mode (no LLM enhancement)",
                self._llm_failure_count,
            )

    def report_llm_success(self) -> None:
        """Report an LLM success — reset failure counter."""
        if self._llm_failure_count > 0:
            logger.info("LLM recovered — resetting failure counter")
        self._llm_failure_count = 0
        self._llm_available = True
        self._statistical_only_mode = False

    @property
    def signal_mode(self) -> str:
        """Current signal generation mode."""
        if self._statistical_only_mode:
            return "statistical_only"
        return "llm_enhanced"

    @staticmethod
    def _signal_to_dict(signal: Signal) -> dict[str, Any]:
        """Convert a Signal dataclass to a serializable dict.

        Args:
            signal: Signal instance.

        Returns:
            Dict suitable for CloudEvents data payload.
        """
        return {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "side": signal.side.value,
            "score": signal.score,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "strategy": signal.strategy,
            "reasoning": signal.reasoning,
            "metadata": signal.metadata,
            "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
        }
