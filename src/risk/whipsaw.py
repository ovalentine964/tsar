"""
Whipsaw Filter — Detect and mitigate rapid price oscillation.

Whipsaws occur when price rapidly alternates direction (up-down-up-down),
generating false signals and causing repeated stop-outs. This module:

  1. Detects rapid directional changes in price
  2. Pauses trading during whipsaw conditions (cooldown)
  3. Tracks whipsaw frequency per symbol and timeframe
  4. Adjusts entry sensitivity during whipsaw-prone conditions

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


class WhipsawState(StrEnum):
    """Current whipsaw state."""

    CALM = "CALM"             # Normal market conditions
    CHOPPY = "CHOPPY"         # Some oscillation, reduced confidence
    WHIPSAW = "WHIPSAW"       # Active whipsaw — pause trading
    COOLDOWN = "COOLDOWN"     # Post-whipsaw cooldown period


@dataclass(frozen=True)
class WhipsawConfig:
    """Immutable configuration for whipsaw detection."""

    # Detection thresholds
    min_direction_changes: int = 4       # 4+ direction changes = whipsaw
    detection_window_seconds: int = 300  # Within 5 minutes
    min_price_move_pct: float = 0.001   # 0.1% min move to count as direction change

    # Cooldown
    cooldown_seconds: int = 180          # 3 min pause after whipsaw detected
    choppy_cooldown_seconds: int = 60    # 1 min reduced trading in choppy

    # Entry sensitivity adjustment
    choppy_score_multiplier: float = 0.7   # 70% signal score in choppy
    whipsaw_score_multiplier: float = 0.0  # Block all entries in whipsaw

    # Frequency tracking
    frequency_window_hours: float = 24.0
    high_frequency_threshold: int = 5    # 5+ whipsaws in 24h = high frequency


@dataclass
class DirectionChange:
    """A single direction change in price."""

    timestamp: float
    price: float
    direction: str  # "up" or "down"
    magnitude_pct: float


@dataclass
class WhipsawEvent:
    """A detected whipsaw event."""

    symbol: str
    timeframe: str
    direction_changes: int
    price_range_pct: float
    detected_at: float
    cooldown_until: float


@dataclass
class WhipsawStatistics:
    """Whipsaw statistics for a symbol/timeframe pair."""

    symbol: str
    timeframe: str
    total_whipsaws: int = 0
    whipsaws_24h: int = 0
    state: WhipsawState = WhipsawState.CALM
    last_whipsaw_at: float = 0.0
    entry_sensitivity: float = 1.0


class WhipsawFilter:
    """Detects and mitigates whipsaw conditions.

    Architecture:
      - Tracks directional changes per symbol+timeframe
      - When direction changes exceed threshold → WHIPSAW state
      - Trading is paused during whipsaw (cooldown period)
      - Signal scores are reduced during choppy conditions
      - Frequency tracking enables adaptive behavior

    Integration:
      - Call `on_price_change(symbol, timeframe, price, direction)` on each tick
      - Call `get_state(symbol, timeframe)` to check current conditions
      - Call `get_score_multiplier(symbol, timeframe)` for signal adjustment
    """

    def __init__(self, config: WhipsawConfig | None = None) -> None:
        self._config = config or WhipsawConfig()

        # Per symbol+timeframe direction change history
        # Key: (symbol, timeframe)
        self._direction_changes: dict[tuple[str, str], deque[DirectionChange]] = {}

        # Per symbol+timeframe state
        self._states: dict[tuple[str, str], WhipsawState] = {}

        # Per symbol+timeframe cooldown
        self._cooldown_until: dict[tuple[str, str], float] = {}

        # Per symbol+timeframe whipsaw events
        self._events: dict[tuple[str, str], deque[WhipsawEvent]] = {}

        # Last known direction per symbol+timeframe
        self._last_direction: dict[tuple[str, str], str | None] = {}
        self._last_price: dict[tuple[str, str], float] = {}

        logger.info(
            f"WhipsawFilter initialized: "
            f"min_changes={self._config.min_direction_changes}, "
            f"window={self._config.detection_window_seconds}s, "
            f"cooldown={self._config.cooldown_seconds}s"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_price_change(
        self,
        symbol: str,
        timeframe: str,
        price: float,
        timestamp: float | None = None,
    ) -> WhipsawState:
        """Update with a new price. Returns current whipsaw state.

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe (e.g. "1m", "5m").
            price: Current price.
            timestamp: Unix timestamp.

        Returns:
            Current WhipsawState for this symbol+timeframe.
        """
        now = timestamp or time.time()
        key = (symbol, timeframe)

        # Initialize if needed
        if key not in self._direction_changes:
            self._direction_changes[key] = deque(maxlen=100)
            self._states[key] = WhipsawState.CALM
            self._cooldown_until[key] = 0.0
            self._events[key] = deque(maxlen=500)
            self._last_direction[key] = None
            self._last_price[key] = price

        last_price = self._last_price[key]
        last_dir = self._last_direction[key]

        # Calculate direction
        if last_price > 0:
            change_pct = (price - last_price) / last_price
        else:
            change_pct = 0.0

        if abs(change_pct) >= self._config.min_price_move_pct:
            new_dir = "up" if change_pct > 0 else "down"

            # Check for direction change
            if last_dir is not None and new_dir != last_dir:
                self._direction_changes[key].append(
                    DirectionChange(
                        timestamp=now,
                        price=price,
                        direction=new_dir,
                        magnitude_pct=abs(change_pct),
                    )
                )

            self._last_direction[key] = new_dir

        self._last_price[key] = price

        # Evaluate state
        state = self._evaluate(key, now)
        self._states[key] = state
        return state

    def get_state(self, symbol: str, timeframe: str) -> WhipsawState:
        """Get current whipsaw state without updating.

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe.

        Returns:
            Current WhipsawState (CALM if unknown).
        """
        key = (symbol, timeframe)
        state = self._states.get(key, WhipsawState.CALM)

        # Check if cooldown has expired
        if state == WhipsawState.COOLDOWN:
            now = time.time()
            if now >= self._cooldown_until.get(key, 0.0):
                self._states[key] = WhipsawState.CALM
                return WhipsawState.CALM

        return state

    def get_score_multiplier(self, symbol: str, timeframe: str) -> float:
        """Get signal score multiplier for current conditions.

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe.

        Returns:
            Multiplier 0.0-1.0 (0.0 = block all entries).
        """
        state = self.get_state(symbol, timeframe)

        if state == WhipsawState.WHIPSAW:
            return self._config.whipsaw_score_multiplier
        if state == WhipsawState.CHOPPY:
            return self._config.choppy_score_multiplier
        if state == WhipsawState.COOLDOWN:
            return self._config.choppy_score_multiplier
        return 1.0

    def get_statistics(self, symbol: str, timeframe: str) -> WhipsawStatistics:
        """Get whipsaw statistics for a symbol+timeframe.

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe.

        Returns:
            WhipsawStatistics with frequency and state data.
        """
        key = (symbol, timeframe)
        events = self._events.get(key, deque())
        now = time.time()
        window_start = now - self._config.frequency_window_hours * 3600

        recent = [e for e in events if e.detected_at >= window_start]

        return WhipsawStatistics(
            symbol=symbol,
            timeframe=timeframe,
            total_whipsaws=len(events),
            whipsaws_24h=len(recent),
            state=self.get_state(symbol, timeframe),
            last_whipsaw_at=events[-1].detected_at if events else 0.0,
            entry_sensitivity=self.get_score_multiplier(symbol, timeframe),
        )

    def reset(self, symbol: str | None = None, timeframe: str | None = None) -> None:
        """Reset state for specific or all symbol+timeframe pairs."""
        if symbol and timeframe:
            key = (symbol, timeframe)
            self._direction_changes.pop(key, None)
            self._states.pop(key, None)
            self._cooldown_until.pop(key, None)
            self._events.pop(key, None)
            self._last_direction.pop(key, None)
            self._last_price.pop(key, None)
        elif symbol:
            keys_to_remove = [k for k in self._states if k[0] == symbol]
            for key in keys_to_remove:
                self._direction_changes.pop(key, None)
                self._states.pop(key, None)
                self._cooldown_until.pop(key, None)
                self._events.pop(key, None)
                self._last_direction.pop(key, None)
                self._last_price.pop(key, None)
        else:
            self._direction_changes.clear()
            self._states.clear()
            self._cooldown_until.clear()
            self._events.clear()
            self._last_direction.clear()
            self._last_price.clear()

    # ------------------------------------------------------------------
    # Internal evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, key: tuple[str, str], now: float) -> WhipsawState:
        """Evaluate whipsaw state for a symbol+timeframe."""
        symbol, timeframe = key
        current_state = self._states.get(key, WhipsawState.CALM)

        # Check cooldown expiry
        if current_state == WhipsawState.COOLDOWN:
            if now >= self._cooldown_until.get(key, 0.0):
                logger.info(f"Whipsaw cooldown expired for {symbol}/{timeframe}")
                return WhipsawState.CALM
            return WhipsawState.COOLDOWN

        # Count recent direction changes
        window_start = now - self._config.detection_window_seconds
        changes = self._direction_changes.get(key, deque())
        recent_changes = [c for c in changes if c.timestamp >= window_start]
        change_count = len(recent_changes)

        # Determine state
        if change_count >= self._config.min_direction_changes:
            # Calculate price range during whipsaw
            if recent_prices := [c.price for c in recent_changes]:
                price_range = (max(recent_prices) - min(recent_prices))
                mid_price = sum(recent_prices) / len(recent_prices)
                range_pct = price_range / mid_price if mid_price > 0 else 0.0
            else:
                range_pct = 0.0

            # Trigger whipsaw
            event = WhipsawEvent(
                symbol=symbol,
                timeframe=timeframe,
                direction_changes=change_count,
                price_range_pct=range_pct,
                detected_at=now,
                cooldown_until=now + self._config.cooldown_seconds,
            )

            if key not in self._events:
                self._events[key] = deque(maxlen=500)
            self._events[key].append(event)

            # Set cooldown
            self._cooldown_until[key] = event.cooldown_until

            logger.warning(
                f"🔄 WHIPSAW detected for {symbol}/{timeframe}: "
                f"{change_count} direction changes in "
                f"{self._config.detection_window_seconds}s, "
                f"range={range_pct:.2%}. "
                f"Cooldown {self._config.cooldown_seconds}s."
            )

            return WhipsawState.WHIPSAW

        # Check for choppy conditions (half the whipsaw threshold)
        if change_count >= self._config.min_direction_changes // 2:
            if current_state != WhipsawState.CHOPPY:
                logger.info(
                    f"Choppy conditions for {symbol}/{timeframe}: "
                    f"{change_count} direction changes"
                )
            return WhipsawState.CHOPPY

        return WhipsawState.CALM
