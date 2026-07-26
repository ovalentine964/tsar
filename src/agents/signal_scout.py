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
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.agents.base import BaseAgent
from src.comms.events import CloudEvent
from src.interfaces.types import (
    BollingerResult,
    MACDResult,
    OHLCV,
    OrderSide,
    SRLevel,
    SRLevels,
    Signal,
    Timeframe,
)
from src.strategy.factor_library import FactorLibrary

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Scoring Configuration
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ScoringWeights:
    """Signal scoring weights — must sum to 1.0."""

    rsi: float = 0.40
    sr_proximity: float = 0.30
    volume: float = 0.15
    trend: float = 0.15

    def validate(self) -> None:
        total = self.rsi + self.sr_proximity + self.volume + self.trend
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

    async def on_initialize(self) -> None:
        """Initialize exchange gateway and pricing engine."""
        from src.interfaces import get_exchange_gateway, get_pricing_engine

        self._gateway = get_exchange_gateway()
        self._pricing_engine = get_pricing_engine()
        logger.info(
            "SignalScout initialized: symbols=%s, cycle_interval=%ds",
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

        # ── Calculate Indicators ──────────────────────────────────
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

        # ── Score the Setup ───────────────────────────────────────
        score, score_breakdown = self._score_setup(
            rsi=rsi,
            current_price=current_price,
            sr_levels=sr_levels,
            volumes=volumes,
            macd=macd,
            ema_trend=ema_trend,
            side=signal_side,
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
        signal = Signal(
            signal_id=signal_id,
            symbol=symbol,
            side=signal_side,
            score=score,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy="mean_reversion",
            reasoning=" | ".join(reasoning_parts),
            metadata={
                "rsi": rsi,
                "atr": atr,
                "macd_histogram": macd.histogram[-1] if macd.histogram else 0,
                "bb_upper": bollinger.upper[-1] if bollinger.upper else 0,
                "bb_lower": bollinger.lower[-1] if bollinger.lower else 0,
                "score_breakdown": score_breakdown,
                "ema_trend": ema_trend[-1] if ema_trend else 0,
                "timeframe": "1h",
            },
            timestamp=datetime.now(timezone.utc),
        )

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
    ) -> tuple[float, dict[str, float]]:
        """Score a potential setup 0-1 based on weighted indicators.

        Scoring breakdown:
        - RSI (40%): How extreme the RSI is
        - S/R proximity (30%): How close to a key level
        - Volume (15%): Volume confirmation
        - Trend (15%): MACD and EMA alignment

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
        if side == OrderSide.BUY:
            levels = sr_levels.supports
        else:
            levels = sr_levels.resistances

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

    def _compute_factor_adjustment(
        self,
        ohlcv_df: "pd.DataFrame",
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
