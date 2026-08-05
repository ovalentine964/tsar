"""
VMPM Session Manager — Tracks current trading session and liquidity behavior.

Sessions (UTC):
  Sydney:    22:00 – 07:00
  Tokyo:     00:00 – 09:00
  London:    07:00 – 16:00
  New York:  12:00 – 21:00

Overlaps:
  London/New York: 12:00 – 16:00  (peak liquidity)
  Tokyo/London:    07:00 – 09:00  (breakout zone)

The session manager determines:
  - Which session(s) are currently active
  - Liquidity characteristics (low/moderate/high/peak)
  - Whether it's an overlap period (score multiplier)
  - Which pairs are favored in the current session
  - Session-specific behavioral biases
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, time as dt_time
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class Session(StrEnum):
    """Trading sessions."""

    SYDNEY = "sydney"
    TOKYO = "tokyo"
    LONDON = "london"
    NEW_YORK = "new_york"


class LiquidityLevel(StrEnum):
    """Market liquidity levels."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    PEAK = "peak"


@dataclass(frozen=True)
class SessionInfo:
    """Current session state."""

    active_sessions: tuple[Session, ...]
    primary_session: Session | None
    is_overlap: bool
    overlap_name: str | None
    liquidity: LiquidityLevel
    score_multiplier: float
    favored_pairs: tuple[str, ...]
    behavioral_bias: str
    timestamp: datetime


# ── Session definitions ────────────────────────────────────────────

_SESSION_TIMES: dict[Session, tuple[dt_time, dt_time]] = {
    Session.SYDNEY:   (dt_time(22, 0), dt_time(7, 0)),
    Session.TOKYO:    (dt_time(0, 0),  dt_time(9, 0)),
    Session.LONDON:   (dt_time(7, 0),  dt_time(16, 0)),
    Session.NEW_YORK: (dt_time(12, 0), dt_time(21, 0)),
}

_SESSION_PAIRS: dict[Session, tuple[str, ...]] = {
    Session.SYDNEY:   ("AUD/USD", "NZD/USD"),
    Session.TOKYO:    ("USD/JPY", "AUD/JPY"),
    Session.LONDON:   ("EUR/USD", "GBP/USD", "EUR/GBP"),
    Session.NEW_YORK: ("EUR/USD", "GBP/USD", "USD/CAD"),
}

_SESSION_LIQUIDITY: dict[Session, LiquidityLevel] = {
    Session.SYDNEY:   LiquidityLevel.LOW,
    Session.TOKYO:    LiquidityLevel.MODERATE,
    Session.LONDON:   LiquidityLevel.HIGH,
    Session.NEW_YORK: LiquidityLevel.HIGH,
}

_SESSION_BIAS: dict[Session, str] = {
    Session.SYDNEY: "range_bound",
    Session.TOKYO: "range_bound_with_jpy_momentum",
    Session.LONDON: "trend_breakout",
    Session.NEW_YORK: "continuation_or_reversal",
}


def _time_in_range(current: dt_time, start: dt_time, end: dt_time) -> bool:
    """Check if current time falls within a session range (handles midnight wrap)."""
    if start <= end:
        return start <= current < end
    # Wraps midnight (e.g., Sydney 22:00–07:00)
    return current >= start or current < end


class SessionManager:
    """Tracks the current trading session and liquidity characteristics.

    Usage::

        manager = SessionManager(config)
        info = manager.get_session_info()
        if info.is_overlap:
            # Boost score during peak liquidity
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._session_config = self._config.get("sessions", {})
        self._overlap_mult = self._config.get("mutable_parameters", {}).get(
            "session_overlap_mult", {}
        ).get("current", 1.5)

    def get_session_info(self, now: datetime | None = None) -> SessionInfo:
        """Get the current session state.

        Args:
            now: Current datetime (UTC). Defaults to now().

        Returns:
            SessionInfo with active sessions, liquidity, and bias.
        """
        if now is None:
            now = datetime.now(UTC)
        current_time = now.time()

        # Find active sessions
        active: list[Session] = []
        for session, (start, end) in _SESSION_TIMES.items():
            if _time_in_range(current_time, start, end):
                active.append(session)

        # Determine primary session (highest liquidity)
        primary: Session | None = None
        if active:
            priority = {Session.LONDON: 4, Session.NEW_YORK: 3,
                        Session.TOKYO: 2, Session.SYDNEY: 1}
            primary = max(active, key=lambda s: priority.get(s, 0))

        # Check overlaps
        overlap_name, is_overlap = self._detect_overlap(active)

        # Liquidity level
        liquidity = self._determine_liquidity(active, is_overlap)

        # Score multiplier
        score_mult = self._overlap_mult if is_overlap else 1.0

        # Favored pairs (union of active session pairs)
        favored: list[str] = []
        seen: set[str] = set()
        for session in active:
            for pair in _SESSION_PAIRS.get(session, ()):
                if pair not in seen:
                    favored.append(pair)
                    seen.add(pair)

        # Behavioral bias
        bias = self._determine_bias(active, is_overlap)

        return SessionInfo(
            active_sessions=tuple(active),
            primary_session=primary,
            is_overlap=is_overlap,
            overlap_name=overlap_name,
            liquidity=liquidity,
            score_multiplier=score_mult,
            favored_pairs=tuple(favored),
            behavioral_bias=bias,
            timestamp=now,
        )

    def is_session_active(self, session: Session, now: datetime | None = None) -> bool:
        """Check if a specific session is active."""
        if now is None:
            now = datetime.now(UTC)
        start, end = _SESSION_TIMES[session]
        return _time_in_range(now.time(), start, end)

    def is_high_liquidity(self, now: datetime | None = None) -> bool:
        """Check if current time has high or peak liquidity."""
        info = self.get_session_info(now)
        return info.liquidity in (LiquidityLevel.HIGH, LiquidityLevel.PEAK)

    def get_session_score(self, pair: str, now: datetime | None = None) -> float:
        """Get a session-based score for a specific pair.

        Returns a multiplier in [0.5, 2.0]:
          - 1.5–2.0: Peak overlap, pair is in favored set
          - 1.0–1.5: Active session, pair is favored
          - 0.8–1.0:  Active session, pair not specifically favored
          - 0.5–0.8:  Low liquidity session
        """
        info = self.get_session_info(now)
        base = 1.0

        # Overlap bonus
        if info.is_overlap:
            base *= info.score_multiplier

        # Pair-session alignment
        if pair in info.favored_pairs:
            base *= 1.1

        # Liquidity penalty
        if info.liquidity == LiquidityLevel.LOW:
            base *= 0.7
        elif info.liquidity == LiquidityLevel.MODERATE:
            base *= 0.9

        return max(0.5, min(2.0, base))

    # ── Private helpers ──────────────────────────────────────────

    def _detect_overlap(self, active: list[Session]) -> tuple[str | None, bool]:
        """Detect if current sessions form an overlap."""
        if len(active) < 2:
            return None, False

        active_set = set(active)
        if {Session.LONDON, Session.NEW_YORK}.issubset(active_set):
            return "london_new_york", True
        if {Session.TOKYO, Session.LONDON}.issubset(active_set):
            return "tokyo_london", True
        if {Session.SYDNEY, Session.TOKYO}.issubset(active_set):
            return "sydney_tokyo", True

        return None, False

    def _determine_liquidity(
        self, active: list[Session], is_overlap: bool
    ) -> LiquidityLevel:
        """Determine the current liquidity level."""
        if is_overlap:
            # London/NY overlap = peak
            if Session.LONDON in active and Session.NEW_YORK in active:
                return LiquidityLevel.PEAK
            return LiquidityLevel.HIGH

        if not active:
            return LiquidityLevel.LOW

        # Use the highest liquidity among active sessions
        levels = [_SESSION_LIQUIDITY.get(s, LiquidityLevel.LOW) for s in active]
        priority = {LiquidityLevel.PEAK: 4, LiquidityLevel.HIGH: 3,
                    LiquidityLevel.MODERATE: 2, LiquidityLevel.LOW: 1}
        return max(levels, key=lambda l: priority.get(l, 0))

    def _determine_bias(
        self, active: list[Session], is_overlap: bool
    ) -> str:
        """Determine behavioral bias from active sessions."""
        if is_overlap:
            if Session.LONDON in active and Session.NEW_YORK in active:
                return "peak_trend"
            return "transitional_breakout"

        if not active:
            return "dead_zone"

        # Use the highest-priority session's bias
        priority = [Session.LONDON, Session.NEW_YORK, Session.TOKYO, Session.SYDNEY]
        for session in priority:
            if session in active:
                return _SESSION_BIAS.get(session, "neutral")

        return "neutral"
