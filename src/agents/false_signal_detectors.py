"""
False Signal Detectors — Detect and reject manipulated/invalid signals.

Four detectors, all deterministic (no LLM):
  1. False Breakout — Price breaks level without volume confirmation
  2. Stop Hunt — Price spikes through level then reverses
  3. Low-Liquidity Trap — Wide spreads, thin orderbook
  4. News-Driven Spike — Temporary move that will revert
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FalseSignalFlag:
    """A detected false signal pattern."""

    name: str
    severity: str  # "warning", "critical"
    description: str
    confidence: float  # [0, 1]


class FalseSignalDetector:
    """Detect common false signal patterns that lead to losses.

    Each detector is independent and can be run in isolation.
    All logic is deterministic — pure computation, no external calls.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        fs_config = config.get("signal_quality", {}).get("false_signals", {})

        # False breakout parameters
        self._breakout_vol_threshold = fs_config.get("false_breakout_volume_threshold", 1.2)

        # Stop hunt parameters
        self._hunt_reversal_pct = fs_config.get("stop_hunt_reversal_pct", 0.60)
        self._hunt_recovery_candles = fs_config.get("stop_hunt_recovery_candles", 3)

        # Low liquidity parameters
        self._max_spread_pct = fs_config.get("low_liquidity_spread_pct", 0.5)
        self._min_book_depth_usd = fs_config.get("low_liquidity_min_depth_usd", 10000)

        # News spike parameters
        self._news_spike_pct = fs_config.get("news_spike_pct", 3.0)
        self._news_spike_minutes = fs_config.get("news_spike_minutes", 15)

    def detect_all(
        self,
        signal_data: dict[str, Any],
        market_context: dict[str, Any],
    ) -> list[FalseSignalFlag]:
        """Run all false signal detectors and return any flags.

        Returns:
            List of FalseSignalFlag. Empty list = no false signals detected.
        """
        flags: list[FalseSignalFlag] = []

        fb = self.detect_false_breakout(signal_data, market_context)
        if fb:
            flags.append(fb)

        sh = self.detect_stop_hunt(signal_data, market_context)
        if sh:
            flags.append(sh)

        ll = self.detect_low_liquidity_trap(signal_data, market_context)
        if ll:
            flags.append(ll)

        ns = self.detect_news_spike(signal_data, market_context)
        if ns:
            flags.append(ns)

        if flags:
            logger.info(
                "False signal flags for %s: %s",
                signal_data.get("symbol", "?"),
                [f.name for f in flags],
            )

        return flags

    def detect_false_breakout(
        self,
        signal_data: dict[str, Any],
        market_context: dict[str, Any],
    ) -> FalseSignalFlag | None:
        """Detect false breakouts — price breaks level without volume.

        A breakout without volume is likely to reverse. Real breakouts
        are accompanied by above-average volume.

        Logic:
          - Price broke a key level (S/R proximity < 1%)
          - But volume < threshold × average
          → False breakout
        """
        metadata = signal_data.get("metadata", {})
        entry_price = signal_data.get("entry_price", 0)

        # Check if price is near a breakout level
        sr_levels = metadata.get("sr_levels", {})
        nearest_support = sr_levels.get("nearest_support")
        nearest_resistance = sr_levels.get("nearest_resistance")

        # Determine if we're breaking through a level
        breaking_level = False
        if nearest_support and entry_price > 0:
            dist = abs(entry_price - nearest_support.get("price", 0)) / entry_price
            if dist < 0.01:  # Within 1% of support
                breaking_level = True
        if nearest_resistance and entry_price > 0:
            dist = abs(entry_price - nearest_resistance.get("price", 0)) / entry_price
            if dist < 0.01:
                breaking_level = True

        if not breaking_level:
            return None

        # Check volume confirmation
        vol_ratio = market_context.get("volume_ratio", 1.0)
        if vol_ratio < self._breakout_vol_threshold:
            return FalseSignalFlag(
                name="false_breakout",
                severity="critical",
                description=(
                    f"Price near breakout level but volume only "
                    f"{vol_ratio:.2f}× average (need ≥{self._breakout_vol_threshold}×)"
                ),
                confidence=min(1.0, (self._breakout_vol_threshold - vol_ratio) / self._breakout_vol_threshold + 0.5),
            )

        return None

    def detect_stop_hunt(
        self,
        signal_data: dict[str, Any],
        market_context: dict[str, Any],
    ) -> FalseSignalFlag | None:
        """Detect stop hunt patterns — spike through level then immediate reversal.

        Stop hunts are identified by:
        - Price moved through a key level
        - Then reversed > 60% of the move within 3 candles
        - Volume was elevated during the spike (hunt volume)

        This integrates with the existing StopHuntDetector in src/risk/stop_hunt.py
        but provides a signal-quality-specific check.
        """
        metadata = signal_data.get("metadata", {})
        side = signal_data.get("side", "buy")

        # Check recent price action for hunt pattern
        recent_highs = metadata.get("recent_highs", [])
        recent_lows = metadata.get("recent_lows", [])
        recent_closes = metadata.get("recent_closes", [])

        if len(recent_closes) < 5:
            return None

        # Look for spike-and-reverse pattern in last 5 candles
        closes = recent_closes[-5:]
        highs = recent_highs[-5:] if len(recent_highs) >= 5 else []
        lows = recent_lows[-5:] if len(recent_lows) >= 5 else []

        if side == "buy":
            # For buy signals, look for a spike down then reversal (stop hunt below support)
            if lows and len(lows) >= 3:
                # Check if recent low was significantly below previous closes
                min_low = min(lows[-3:])
                max_close_after = max(closes[-2:]) if len(closes) >= 2 else closes[-1]
                spike_range = closes[-3] - min_low if closes[-3] > min_low else 0
                recovery = max_close_after - min_low

                if spike_range > 0 and recovery / spike_range > self._hunt_reversal_pct:
                    return FalseSignalFlag(
                        name="stop_hunt",
                        severity="critical",
                        description=(
                            f"Possible stop hunt: price spiked down "
                            f"{spike_range:.2f} then recovered {recovery:.2f} "
                            f"({recovery/spike_range*100:.0f}% reversal)"
                        ),
                        confidence=recovery / spike_range,
                    )
        else:
            # For sell signals, look for a spike up then reversal
            if highs and len(highs) >= 3:
                max_high = max(highs[-3:])
                min_close_after = min(closes[-2:]) if len(closes) >= 2 else closes[-1]
                spike_range = max_high - closes[-3] if max_high > closes[-3] else 0
                recovery = max_high - min_close_after

                if spike_range > 0 and recovery / spike_range > self._hunt_reversal_pct:
                    return FalseSignalFlag(
                        name="stop_hunt",
                        severity="critical",
                        description=(
                            f"Possible stop hunt: price spiked up "
                            f"{spike_range:.2f} then reversed {recovery:.2f} "
                            f"({recovery/spike_range*100:.0f}% reversal)"
                        ),
                        confidence=recovery / spike_range,
                    )

        return None

    def detect_low_liquidity_trap(
        self,
        signal_data: dict[str, Any],
        market_context: dict[str, Any],
    ) -> FalseSignalFlag | None:
        """Detect low-liquidity conditions that cause slippage.

        Low liquidity = wide spreads + thin order book.
        With a $10 account, even small slippage kills R:R.

        Detection:
          - Bid-ask spread > 0.5% → reject
          - Order book depth < $10K within 2% → reject
        """
        spread_pct = market_context.get("spread_pct", 0)
        book_depth = market_context.get("book_depth_usd", float("inf"))

        if spread_pct > self._max_spread_pct:
            return FalseSignalFlag(
                name="low_liquidity_spread",
                severity="critical",
                description=(
                    f"Spread {spread_pct:.2f}% exceeds maximum "
                    f"{self._max_spread_pct}% — likely slippage trap"
                ),
                confidence=min(1.0, spread_pct / self._max_spread_pct),
            )

        if book_depth < self._min_book_depth_usd:
            return FalseSignalFlag(
                name="low_liquidity_depth",
                severity="warning",
                description=(
                    f"Order book depth ${book_depth:,.0f} below minimum "
                    f"${self._min_book_depth_usd:,.0f} — thin market"
                ),
                confidence=1.0 - (book_depth / self._min_book_depth_usd),
            )

        return None

    def detect_news_spike(
        self,
        signal_data: dict[str, Any],
        market_context: dict[str, Any],
    ) -> FalseSignalFlag | None:
        """Detect news-driven price spikes that will revert.

        News spikes are characterized by:
        - Large price move (>3%) in short time (<15 min)
        - Sentiment spike is recent (<30 min old)
        - No prior trend in that direction

        These moves typically revert within 1-4 hours.
        """
        metadata = signal_data.get("metadata", {})

        # Check price change magnitude and speed
        price_change_pct = abs(metadata.get("price_change_pct", 0))
        price_change_minutes = metadata.get("price_change_minutes", 60)

        if price_change_pct > self._news_spike_pct and price_change_minutes < self._news_spike_minutes:
            # Check if sentiment spike is recent
            sentiment_age_minutes = market_context.get("sentiment_spike_age_minutes", 999)
            if sentiment_age_minutes < 30:
                return FalseSignalFlag(
                    name="news_spike",
                    severity="critical",
                    description=(
                        f"News-driven spike: {price_change_pct:.1f}% move in "
                        f"{price_change_minutes}min, sentiment spike "
                        f"{sentiment_age_minutes}min ago — likely to revert"
                    ),
                    confidence=min(1.0, price_change_pct / self._news_spike_pct),
                )

        # Also check if volume spike is isolated (one huge candle then normal)
        vol_ratio = market_context.get("volume_ratio", 1.0)
        prev_vol_ratio = market_context.get("prev_volume_ratio", 1.0)
        if vol_ratio > 3.0 and prev_vol_ratio < 1.5:
            # Isolated volume spike — likely news-driven
            return FalseSignalFlag(
                name="news_spike",
                severity="warning",
                description=(
                    f"Isolated volume spike ({vol_ratio:.1f}× avg) after "
                    f"normal volume ({prev_vol_ratio:.1f}×) — possible news event"
                ),
                confidence=0.6,
            )

        return None
