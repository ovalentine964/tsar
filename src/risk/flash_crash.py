"""
Flash Crash Detector — Monitor price velocity and detect sudden drops.

Detects flash crashes by tracking price change rate (price change per second).
When a crash is detected, the kill switch is activated. When price stabilizes,
a recovery signal is emitted so trading can resume.

Pattern matching against historical flash crash signatures provides
early warning before full crash conditions are met.

All thresholds from config/risk.yaml. No LLM calls. Deterministic.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class FlashCrashState(StrEnum):
    """Current state of the flash crash detector."""

    NORMAL = "NORMAL"
    WARNING = "WARNING"  # Price velocity elevated, approaching threshold
    CRASH_DETECTED = "CRASH"  # Flash crash confirmed — kill switch
    RECOVERING = "RECOVERING"  # Price stabilizing after crash


@dataclass(frozen=True)
class FlashCrashConfig:
    """Immutable configuration for flash crash detection."""

    # Core thresholds
    price_drop_pct: float = 0.05  # 5% drop triggers crash
    price_drop_window_seconds: int = 60  # ...within 60 seconds
    warning_threshold_pct: float = 0.03  # 3% drop triggers warning

    # Recovery detection
    recovery_stability_seconds: int = 120  # Price stable for 2 min = recovered
    recovery_max_volatility_pct: float = 0.01  # <1%波动 during recovery window

    # Historical pattern matching
    pattern_window_size: int = 10  # Track last N price points for pattern
    velocity_smoothing_window: int = 5  # Rolling window for velocity smoothing

    # Cooldown after crash recovery
    post_crash_cooldown_seconds: int = 300  # 5 min cooldown after recovery


@dataclass
class PricePoint:
    """A single price observation with timestamp."""

    price: float
    timestamp: float  # Unix timestamp


@dataclass
class FlashCrashEvent:
    """Record of a detected flash crash."""

    symbol: str
    trigger_price: float
    low_price: float
    drop_pct: float
    velocity: float  # price change per second
    detected_at: float
    recovered_at: float | None = None
    recovery_price: float | None = None


class FlashCrashDetector:
    """Detects flash crashes via price velocity monitoring.

    Architecture:
      - Maintains a rolling window of price observations per symbol
      - Calculates price velocity (Δprice / Δtime) on each update
      - If velocity exceeds threshold → CRASH_DETECTED → kill switch
      - Monitors for price stabilization → RECOVERING → resume
      - Historical pattern matching for early warning

    Integration points:
      - Call `update(symbol, price)` on every price tick
      - Call `check()` to get current state
      - Subscribe to state changes for kill switch activation
    """

    def __init__(self, config: FlashCrashConfig | None = None) -> None:
        self._config = config or FlashCrashConfig()

        # Per-symbol price history: symbol → deque of PricePoint
        self._price_history: dict[str, deque[PricePoint]] = {}

        # Per-symbol state
        self._states: dict[str, FlashCrashState] = {}

        # Per-symbol crash events
        self._crash_events: dict[str, FlashCrashEvent | None] = {}

        # Per-symbol recovery tracking
        self._recovery_start: dict[str, float | None] = {}

        # Per-symbol cooldown
        self._cooldown_until: dict[str, float] = {}

        # Historical crash patterns (velocity profiles)
        self._crash_patterns: list[list[float]] = []

        logger.info(
            f"FlashCrashDetector initialized: "
            f"drop={self._config.price_drop_pct:.1%} in "
            f"{self._config.price_drop_window_seconds}s"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, symbol: str, price: float, timestamp: float | None = None) -> FlashCrashState:
        """Update with a new price observation. Returns current state.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            price: Current price.
            timestamp: Unix timestamp (defaults to time.time()).

        Returns:
            Current FlashCrashState for this symbol.
        """
        now = timestamp or time.time()
        point = PricePoint(price=price, timestamp=now)

        # Initialize tracking for new symbols
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=self._config.pattern_window_size * 10)
            self._states[symbol] = FlashCrashState.NORMAL
            self._crash_events[symbol] = None
            self._recovery_start[symbol] = None
            self._cooldown_until[symbol] = 0.0

        history = self._price_history[symbol]
        history.append(point)

        # Check cooldown
        if now < self._cooldown_until.get(symbol, 0.0):
            return self._states[symbol]

        # Calculate velocity and evaluate
        state = self._evaluate(symbol, price, now)
        self._states[symbol] = state
        return state

    def check(self, symbol: str) -> FlashCrashState:
        """Get current state for a symbol without updating.

        Args:
            symbol: Trading pair.

        Returns:
            Current FlashCrashState (NORMAL if symbol unknown).
        """
        return self._states.get(symbol, FlashCrashState.NORMAL)

    def get_velocity(self, symbol: str) -> float:
        """Get current smoothed price velocity for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            Price change per second (negative = dropping).
            0.0 if insufficient data.
        """
        history = self._price_history.get(symbol)
        if not history or len(history) < 2:
            return 0.0
        return self._smoothed_velocity(symbol)

    def get_crash_event(self, symbol: str) -> FlashCrashEvent | None:
        """Get the most recent crash event for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            FlashCrashEvent if a crash was detected, None otherwise.
        """
        return self._crash_events.get(symbol)

    def match_historical_pattern(self, symbol: str) -> float:
        """Check if current price action matches historical crash patterns.

        Returns:
            Match score 0.0-1.0 (1.0 = perfect match to known crash pattern).
            0.0 if no patterns registered or insufficient data.
        """
        if not self._crash_patterns:
            return 0.0

        history = self._price_history.get(symbol)
        if not history or len(history) < self._config.velocity_smoothing_window:
            return 0.0

        # Build current velocity profile
        recent = list(history)[-self._config.velocity_smoothing_window :]
        current_profile = []
        for i in range(1, len(recent)):
            dt = recent[i].timestamp - recent[i - 1].timestamp
            if dt > 0:
                dp = recent[i].price - recent[i - 1].price
                current_profile.append(dp / dt)

        if not current_profile:
            return 0.0

        # Compare against known crash patterns using normalized correlation
        best_score = 0.0
        for pattern in self._crash_patterns:
            score = self._pattern_similarity(current_profile, pattern)
            best_score = max(best_score, score)

        return best_score

    def register_crash_pattern(self, velocity_profile: list[float]) -> None:
        """Register a historical crash velocity pattern for matching.

        Args:
            velocity_profile: List of velocity values from a known crash.
        """
        if velocity_profile:
            self._crash_patterns.append(velocity_profile)
            logger.info(
                f"Registered crash pattern with {len(velocity_profile)} points. "
                f"Total patterns: {len(self._crash_patterns)}"
            )

    def reset(self, symbol: str | None = None) -> None:
        """Reset state for a symbol or all symbols.

        Args:
            symbol: Specific symbol to reset, or None for all.
        """
        if symbol:
            self._states.pop(symbol, None)
            self._price_history.pop(symbol, None)
            self._crash_events.pop(symbol, None)
            self._recovery_start.pop(symbol, None)
            self._cooldown_until.pop(symbol, None)
        else:
            self._states.clear()
            self._price_history.clear()
            self._crash_events.clear()
            self._recovery_start.clear()
            self._cooldown_until.clear()

    # ------------------------------------------------------------------
    # Internal evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, symbol: str, price: float, now: float) -> FlashCrashState:
        """Core evaluation logic — determine state from price data."""
        current_state = self._states.get(symbol, FlashCrashState.NORMAL)

        # If recovering, check for stabilization
        if current_state == FlashCrashState.RECOVERING:
            return self._check_recovery(symbol, price, now)

        # If in crash, check for recovery start
        if current_state == FlashCrashState.CRASH_DETECTED:
            return self._check_recovery(symbol, price, now)

        # Calculate price drop over window
        drop_pct = self._price_drop_over_window(symbol, now)
        velocity = self._smoothed_velocity(symbol)

        # Check for crash condition
        if drop_pct >= self._config.price_drop_pct:
            return self._trigger_crash(symbol, price, drop_pct, velocity, now)

        # Check for warning condition
        if drop_pct >= self._config.warning_threshold_pct:
            # Also check historical pattern matching
            pattern_score = self.match_historical_pattern(symbol)
            if pattern_score > 0.7:
                logger.warning(
                    f"Flash crash WARNING for {symbol}: "
                    f"drop={drop_pct:.2%}, velocity={velocity:.4f}, "
                    f"pattern_match={pattern_score:.2f}"
                )
                return FlashCrashState.WARNING

            if velocity < 0 and abs(velocity) > 0:
                logger.warning(
                    f"Flash crash WARNING for {symbol}: "
                    f"drop={drop_pct:.2%}, velocity={velocity:.4f}"
                )
                return FlashCrashState.WARNING

        return FlashCrashState.NORMAL

    def _trigger_crash(
        self,
        symbol: str,
        price: float,
        drop_pct: float,
        velocity: float,
        now: float,
    ) -> FlashCrashState:
        """Handle flash crash detection."""
        event = FlashCrashEvent(
            symbol=symbol,
            trigger_price=price,
            low_price=price,
            drop_pct=drop_pct,
            velocity=velocity,
            detected_at=now,
        )
        self._crash_events[symbol] = event
        self._recovery_start[symbol] = None

        logger.critical(
            f"⚡ FLASH CRASH DETECTED for {symbol}: "
            f"drop={drop_pct:.2%}, velocity={velocity:.4f}/s, "
            f"price={price:.2f}"
        )

        return FlashCrashState.CRASH_DETECTED

    def _check_recovery(self, symbol: str, price: float, now: float) -> FlashCrashState:
        """Check if price has stabilized after a crash.

        Recovery criteria:
          - Price volatility < recovery_max_volatility_pct for
            recovery_stability_seconds
        """
        recovery_start = self._recovery_start.get(symbol)

        # Get the crash event's low price
        event = self._crash_events.get(symbol)
        if not event:
            return FlashCrashState.NORMAL

        # Update low price if we're making new lows
        if price < event.low_price:
            event = FlashCrashEvent(
                symbol=event.symbol,
                trigger_price=event.trigger_price,
                low_price=price,
                drop_pct=event.drop_pct,
                velocity=event.velocity,
                detected_at=event.detected_at,
            )
            self._crash_events[symbol] = event
            # Reset recovery — new low means crash is still active
            self._recovery_start[symbol] = None
            return FlashCrashState.CRASH_DETECTED

        # Check if price is stabilizing
        volatility = self._recent_volatility(symbol, now)

        if volatility < self._config.recovery_max_volatility_pct:
            # Price is stable
            if recovery_start is None:
                self._recovery_start[symbol] = now
                return FlashCrashState.RECOVERING

            # Check if stable long enough
            stable_duration = now - recovery_start
            if stable_duration >= self._config.recovery_stability_seconds:
                # Recovery complete!
                logger.info(
                    f"✅ Flash crash RECOVERY for {symbol}: "
                    f"price stabilized at {price:.2f} "
                    f"(was {event.low_price:.2f})"
                )

                # Update crash event with recovery info
                self._crash_events[symbol] = FlashCrashEvent(
                    symbol=event.symbol,
                    trigger_price=event.trigger_price,
                    low_price=event.low_price,
                    drop_pct=event.drop_pct,
                    velocity=event.velocity,
                    detected_at=event.detected_at,
                    recovered_at=now,
                    recovery_price=price,
                )

                # Set cooldown
                self._cooldown_until[symbol] = now + self._config.post_crash_cooldown_seconds
                self._recovery_start[symbol] = None
                return FlashCrashState.NORMAL

            return FlashCrashState.RECOVERING
        else:
            # Volatility spiked again — reset recovery
            self._recovery_start[symbol] = None
            return FlashCrashState.CRASH_DETECTED

    # ------------------------------------------------------------------
    # Price analysis helpers
    # ------------------------------------------------------------------

    def _price_drop_over_window(self, symbol: str, now: float) -> float:
        """Calculate price drop percentage over the detection window.

        Returns:
            Drop as positive fraction (0.05 = 5% drop). 0.0 if no drop.
        """
        history = self._price_history.get(symbol)
        if not history or len(history) < 2:
            return 0.0

        window_start = now - self._config.price_drop_window_seconds
        current_price = history[-1].price

        # Find the highest price within the window
        max_price = current_price
        for point in history:
            if point.timestamp >= window_start:
                max_price = max(max_price, point.price)

        if max_price <= 0:
            return 0.0

        drop = (max_price - current_price) / max_price
        return max(0.0, drop)

    def _smoothed_velocity(self, symbol: str) -> float:
        """Calculate smoothed price velocity (change per second).

        Uses a rolling window to smooth out noise.

        Returns:
            Velocity in price units per second. Negative = dropping.
        """
        history = self._price_history.get(symbol)
        if not history or len(history) < 2:
            return 0.0

        window = min(self._config.velocity_smoothing_window, len(history))
        recent = list(history)[-window:]

        velocities = []
        for i in range(1, len(recent)):
            dt = recent[i].timestamp - recent[i - 1].timestamp
            if dt > 0:
                dp = recent[i].price - recent[i - 1].price
                velocities.append(dp / dt)

        if not velocities:
            return 0.0

        return sum(velocities) / len(velocities)

    def _recent_volatility(self, symbol: str, now: float) -> float:
        """Calculate recent price volatility (as fraction).

        Uses the recovery stability window to measure price oscillation.

        Returns:
            Volatility as fraction (0.01 = 1%).
        """
        history = self._price_history.get(symbol)
        if not history or len(history) < 2:
            return 0.0

        window_start = now - self._config.recovery_stability_seconds
        recent_prices = [p.price for p in history if p.timestamp >= window_start]

        if len(recent_prices) < 2:
            return 0.0

        min_p = min(recent_prices)
        max_p = max(recent_prices)
        mid_p = (min_p + max_p) / 2

        if mid_p <= 0:
            return 0.0

        return (max_p - min_p) / mid_p

    @staticmethod
    def _pattern_similarity(current: list[float], pattern: list[float]) -> float:
        """Calculate similarity between two velocity profiles.

        Uses normalized dot product (cosine similarity) for shape matching.

        Returns:
            Similarity score 0.0-1.0.
        """
        if not current or not pattern:
            return 0.0

        # Align lengths (use shorter one)
        min_len = min(len(current), len(pattern))
        c = current[:min_len]
        p = pattern[:min_len]

        # Cosine similarity
        dot = sum(a * b for a, b in zip(c, p, strict=True))
        mag_c = sum(a * a for a in c) ** 0.5
        mag_p = sum(b * b for b in p) ** 0.5

        if mag_c == 0 or mag_p == 0:
            return 0.0

        return max(0.0, dot / (mag_c * mag_p))
