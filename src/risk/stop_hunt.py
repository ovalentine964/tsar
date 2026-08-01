"""
Stop Hunt Detector — Detect price spikes that trigger stop losses then reverse.

Stop hunting is a market manipulation pattern where price is pushed to a level
that triggers retail stop losses, then quickly reverses. This detector:

  1. Monitors for price spikes that hit stop-loss levels then recover
  2. Flags symbols with high stop-hunt frequency
  3. Suggests adjusted stop placement to avoid obvious hunt levels
  4. Tracks stop-hunt statistics per symbol for adaptive behavior

All logic is deterministic. No LLM calls. Thresholds from config/risk.yaml.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class HuntSeverity(StrEnum):
    """Severity of a detected stop hunt."""

    NONE = "NONE"
    SUSPECTED = "SUSPECTED"   # Pattern matches but not confirmed
    CONFIRMED = "CONFIRMED"   # Price hit stop then reversed within N candles
    SEVERE = "SEVERE"         # Multiple hunts in short period


@dataclass(frozen=True)
class StopHuntConfig:
    """Immutable configuration for stop hunt detection."""

    # Detection parameters
    recovery_candles: int = 5           # If price recovers within 5 candles → hunt
    hunt_spike_pct: float = 0.005      # 0.5% spike beyond stop level to qualify
    min_price_recovery_pct: float = 0.003  # Must recover at least 0.3% to count

    # Frequency tracking
    hunt_window_hours: float = 24.0    # Track hunts over 24h window
    high_frequency_threshold: int = 3  # 3+ hunts in window = high frequency
    severe_frequency_threshold: int = 5  # 5+ hunts = severe

    # Stop placement adjustment
    stop_buffer_pct: float = 0.002     # Add 0.2% buffer below obvious hunt levels
    hunt_level_lookback: int = 50      # Look back N candles for hunt levels

    # Cooldown
    symbol_cooldown_seconds: float = 600  # 10 min cooldown after confirmed hunt


@dataclass
class StopHit:
    """Record of a stop-loss being triggered."""

    symbol: str
    stop_price: float
    hit_price: float
    hit_timestamp: float
    direction: str  # "long" or "short" (the position that got stopped)


@dataclass
class StopHuntEvent:
    """A detected stop hunt event."""

    symbol: str
    stop_price: float
    spike_price: float
    recovery_price: float
    recovery_candles: int
    severity: HuntSeverity
    detected_at: float
    direction: str  # "long" or "short"


@dataclass
class HuntStatistics:
    """Stop hunt statistics for a symbol."""

    symbol: str
    total_hunts: int = 0
    hunts_24h: int = 0
    frequency: HuntSeverity = HuntSeverity.NONE
    last_hunt_at: float = 0.0
    avg_recovery_candles: float = 0.0
    common_hunt_zones: list[float] = field(default_factory=list)


class StopHuntDetector:
    """Detects stop hunt patterns and provides adaptive stop placement.

    Architecture:
      - Tracks stop-loss hits per symbol
      - When a stop is hit, monitors subsequent price action
      - If price reverses within N candles → confirmed stop hunt
      - Maintains hunt frequency statistics per symbol
      - Suggests adjusted stop levels to avoid common hunt zones

    Integration:
      - Call `on_stop_hit(symbol, stop_price, hit_price, direction)` when a stop triggers
      - Call `on_price_update(symbol, price, candle_close)` on each candle close
      - Call `get_hunt_risk(symbol)` before placing stops
      - Call `suggest_stop_adjustment(symbol, proposed_stop, direction)` for placement
    """

    def __init__(self, config: StopHuntConfig | None = None) -> None:
        self._config = config or StopHuntConfig()

        # Per-symbol pending stop hits (waiting to see if price reverses)
        self._pending_hits: dict[str, StopHit] = {}

        # Per-symbol confirmed hunt events
        self._hunt_events: dict[str, deque[StopHuntEvent]] = {}

        # Per-symbol candle count since stop hit
        self._candles_since_hit: dict[str, int] = {}

        # Per-symbol price at stop hit
        self._price_at_hit: dict[str, float] = {}

        # Per-symbol cooldown
        self._cooldown_until: dict[str, float] = {}

        # Common hunt zones (price levels where stops frequently get hunted)
        self._hunt_zones: dict[str, list[float]] = {}

        logger.info(
            f"StopHuntDetector initialized: "
            f"recovery_candles={self._config.recovery_candles}, "
            f"spike={self._config.hunt_spike_pct:.2%}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_stop_hit(
        self,
        symbol: str,
        stop_price: float,
        hit_price: float,
        direction: str,
        timestamp: float | None = None,
    ) -> None:
        """Notify the detector that a stop-loss was triggered.

        Call this when any stop-loss fires. The detector will then
        monitor subsequent price action to determine if it was a hunt.

        Args:
            symbol: Trading pair.
            stop_price: The stop-loss price that was set.
            hit_price: The actual price at which the stop was filled.
            direction: "long" or "short" (the position that was stopped).
            timestamp: Unix timestamp (defaults to time.time()).
        """
        now = timestamp or time.time()

        # Check cooldown
        if now < self._cooldown_until.get(symbol, 0.0):
            logger.debug(f"Stop hit on {symbol} ignored — cooldown active")
            return

        hit = StopHit(
            symbol=symbol,
            stop_price=stop_price,
            hit_price=hit_price,
            hit_timestamp=now,
            direction=direction,
        )

        self._pending_hits[symbol] = hit
        self._candles_since_hit[symbol] = 0
        self._price_at_hit[symbol] = hit_price

        logger.info(
            f"Stop hit registered for {symbol}: "
            f"stop={stop_price:.2f}, hit={hit_price:.2f}, dir={direction}"
        )

    def on_price_update(
        self,
        symbol: str,
        price: float,
        is_candle_close: bool = True,
        timestamp: float | None = None,
    ) -> HuntSeverity:
        """Update with new price data. Check for stop hunt patterns.

        Args:
            symbol: Trading pair.
            price: Current price.
            is_candle_close: True if this is a candle close (increment counter).
            timestamp: Unix timestamp.

        Returns:
            HuntSeverity if a hunt was detected, NONE otherwise.
        """
        now = timestamp or time.time()
        pending = self._pending_hits.get(symbol)

        if not pending:
            return HuntSeverity.NONE

        # Increment candle counter on candle close
        if is_candle_close:
            self._candles_since_hit[symbol] = (
                self._candles_since_hit.get(symbol, 0) + 1
            )

        candles = self._candles_since_hit.get(symbol, 0)
        hit_price = self._price_at_hit.get(symbol, pending.hit_price)

        # Check if price has reversed enough to constitute a hunt
        if self._is_hunt_pattern(pending, price, hit_price, candles):
            return self._confirm_hunt(symbol, pending, price, candles, now)

        # If too many candles passed without reversal, it wasn't a hunt
        if candles >= self._config.recovery_candles * 2:
            logger.debug(
                f"Stop hit on {symbol} after {candles} candles — "
                f"not a hunt (no reversal)"
            )
            self._pending_hits.pop(symbol, None)
            self._candles_since_hit.pop(symbol, None)
            self._price_at_hit.pop(symbol, None)

        return HuntSeverity.NONE

    def get_hunt_risk(self, symbol: str) -> HuntSeverity:
        """Get current stop hunt risk level for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            HuntSeverity indicating current risk level.
        """
        events = self._hunt_events.get(symbol)
        if not events:
            return HuntSeverity.NONE

        now = time.time()
        window_start = now - self._config.hunt_window_hours * 3600
        recent_hunts = [e for e in events if e.detected_at >= window_start]

        count = len(recent_hunts)
        if count >= self._config.severe_frequency_threshold:
            return HuntSeverity.SEVERE
        if count >= self._config.high_frequency_threshold:
            return HuntSeverity.CONFIRMED
        if count >= 1:
            return HuntSeverity.SUSPECTED

        return HuntSeverity.NONE

    def get_statistics(self, symbol: str) -> HuntStatistics:
        """Get stop hunt statistics for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            HuntStatistics with frequency and pattern data.
        """
        events = self._hunt_events.get(symbol, deque())
        now = time.time()
        window_start = now - self._config.hunt_window_hours * 3600

        recent = [e for e in events if e.detected_at >= window_start]
        all_events = list(events)

        avg_candles = 0.0
        if all_events:
            avg_candles = sum(e.recovery_candles for e in all_events) / len(all_events)

        return HuntStatistics(
            symbol=symbol,
            total_hunts=len(all_events),
            hunts_24h=len(recent),
            frequency=self.get_hunt_risk(symbol),
            last_hunt_at=all_events[-1].detected_at if all_events else 0.0,
            avg_recovery_candles=avg_candles,
            common_hunt_zones=self._hunt_zones.get(symbol, []),
        )

    def suggest_stop_adjustment(
        self,
        symbol: str,
        proposed_stop: float,
        direction: str,
    ) -> tuple[float, bool]:
        """Suggest an adjusted stop price to avoid common hunt zones.

        If the proposed stop is near a known hunt level, moves it further
        away to reduce the probability of being hunted.

        Args:
            symbol: Trading pair.
            proposed_stop: The originally planned stop-loss price.
            direction: "long" or "short".

        Returns:
            Tuple of (adjusted_stop, was_adjusted).
        """
        hunt_zones = self._hunt_zones.get(symbol, [])
        if not hunt_zones:
            return proposed_stop, False

        buffer = self._config.stop_buffer_pct

        for zone in hunt_zones:
            distance_pct = abs(proposed_stop - zone) / zone if zone else 1.0

            if distance_pct < buffer * 2:
                # Too close to a hunt zone — adjust
                if direction == "long":
                    # Move stop further below the hunt zone
                    adjusted = zone * (1 - buffer)
                    if adjusted < proposed_stop:
                        return adjusted, True
                else:
                    # Move stop further above the hunt zone
                    adjusted = zone * (1 + buffer)
                    if adjusted > proposed_stop:
                        return adjusted, True

        return proposed_stop, False

    def reset(self, symbol: str | None = None) -> None:
        """Reset state for a symbol or all symbols."""
        if symbol:
            self._pending_hits.pop(symbol, None)
            self._hunt_events.pop(symbol, None)
            self._candles_since_hit.pop(symbol, None)
            self._price_at_hit.pop(symbol, None)
            self._cooldown_until.pop(symbol, None)
            self._hunt_zones.pop(symbol, None)
        else:
            self._pending_hits.clear()
            self._hunt_events.clear()
            self._candles_since_hit.clear()
            self._price_at_hit.clear()
            self._cooldown_until.clear()
            self._hunt_zones.clear()

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------

    def _is_hunt_pattern(
        self,
        hit: StopHit,
        current_price: float,
        hit_price: float,
        candles_since: int,
    ) -> bool:
        """Check if current price action matches a stop hunt pattern.

        A stop hunt is when:
          1. Price spiked beyond the stop level by hunt_spike_pct
          2. Price has recovered by min_price_recovery_pct
          3. Recovery happened within recovery_candles
        """
        if candles_since > self._config.recovery_candles:
            return False

        if hit_price <= 0:
            return False

        # Calculate how far price moved beyond the stop
        if hit.direction == "long":
            # Long stopped out — price went below stop
            # Hunt if price then recovered above stop
            spike_below = (hit.stop_price - hit_price) / hit.stop_price
            recovery = (current_price - hit_price) / hit_price
        else:
            # Short stopped out — price went above stop
            # Hunt if price then dropped back below stop
            spike_above = (hit_price - hit.stop_price) / hit.stop_price
            recovery = (hit_price - current_price) / hit_price

        # Check recovery magnitude
        return recovery >= self._config.min_price_recovery_pct

    def _confirm_hunt(
        self,
        symbol: str,
        hit: StopHit,
        recovery_price: float,
        candles: int,
        now: float,
    ) -> HuntSeverity:
        """Confirm a stop hunt and record the event."""
        # Determine severity based on frequency
        existing_events = self._hunt_events.get(symbol, deque())
        window_start = now - self._config.hunt_window_hours * 3600
        recent_count = sum(
            1 for e in existing_events if e.detected_at >= window_start
        )

        if recent_count + 1 >= self._config.severe_frequency_threshold:
            severity = HuntSeverity.SEVERE
        elif recent_count + 1 >= self._config.high_frequency_threshold:
            severity = HuntSeverity.CONFIRMED
        else:
            severity = HuntSeverity.SUSPECTED

        event = StopHuntEvent(
            symbol=symbol,
            stop_price=hit.stop_price,
            spike_price=hit.hit_price,
            recovery_price=recovery_price,
            recovery_candles=candles,
            severity=severity,
            detected_at=now,
            direction=hit.direction,
        )

        # Record event
        if symbol not in self._hunt_events:
            self._hunt_events[symbol] = deque(maxlen=1000)
        self._hunt_events[symbol].append(event)

        # Record hunt zone
        if symbol not in self._hunt_zones:
            self._hunt_zones[symbol] = []
        zone = hit.stop_price
        if zone not in self._hunt_zones[symbol]:
            self._hunt_zones[symbol].append(zone)
            # Keep only recent zones
            if len(self._hunt_zones[symbol]) > self._config.hunt_level_lookback:
                self._hunt_zones[symbol] = self._hunt_zones[symbol][
                    -self._config.hunt_level_lookback:
                ]

        # Set cooldown
        self._cooldown_until[symbol] = now + self._config.symbol_cooldown_seconds

        # Clear pending
        self._pending_hits.pop(symbol, None)
        self._candles_since_hit.pop(symbol, None)
        self._price_at_hit.pop(symbol, None)

        logger.warning(
            f"🎯 STOP HUNT {severity.value} for {symbol}: "
            f"stop={hit.stop_price:.2f}, spike={hit.hit_price:.2f}, "
            f"recovery={recovery_price:.2f} in {candles} candles, "
            f"dir={hit.direction}"
        )

        return severity
