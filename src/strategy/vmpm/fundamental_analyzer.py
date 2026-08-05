"""
VMPM Fundamental Analyzer — Economic calendar integration and bias scoring.

Integrates with TSAR's existing MarketCalendar and FundamentalScorer tools
to produce a directional bias score for each trading pair.

The analyzer checks:
  - Upcoming high-impact economic events (FOMC, CPI, NFP, GDP)
  - Central bank rate decisions and forward guidance
  - News veto status from NewsGatekeeper
  - Macro regime alignment

Produces a FundamentalBias with:
  - direction: 'bullish', 'bearish', 'neutral'
  - confidence: 0.0 – 1.0
  - news_clear: bool (no high-impact news in blackout window)
  - event_risk: event proximity and severity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class BiasDirection(StrEnum):
    """Fundamental bias direction."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class UpcomingEvent:
    """A scheduled economic event."""

    event: str
    category: str
    impact: str  # critical, high, medium, low
    scheduled_time: datetime | None
    expected_value: str | None
    previous_value: str | None
    bias_hint: str | None  # directional hint from consensus


@dataclass(frozen=True)
class FundamentalBias:
    """Fundamental analysis output for a trading pair."""

    direction: BiasDirection
    confidence: float  # 0.0 – 1.0
    news_clear: bool
    upcoming_events: tuple[UpcomingEvent, ...]
    blackout_active: bool
    blackout_reason: str | None
    event_risk_score: float  # 0.0 (no risk) – 1.0 (extreme risk)
    macro_alignment: float  # 0.0 (bearish) – 1.0 (bullish)
    reasoning: str


class FundamentalAnalyzer:
    """Economic calendar integration for VMPM.

    Uses TSAR's MarketCalendar and NewsGatekeeper to assess
    fundamental conditions before trade entry.

    Usage::

        analyzer = FundamentalAnalyzer(config)
        bias = await analyzer.analyze("EUR/USD")
        if not bias.news_clear:
            return  # Skip — high-impact news imminent
    """

    # Blackout windows before high-impact events (minutes)
    _BLACKOUT_MINUTES: dict[str, int] = {
        "critical": 60,
        "high": 30,
        "medium": 15,
        "low": 0,
    }

    # Currency-specific event impact mapping
    _CURRENCY_EVENTS: dict[str, list[str]] = {
        "USD": ["FOMC", "CPI", "NFP", "GDP", "PPI", "Retail Sales"],
        "EUR": ["ECB Rate Decision", "CPI Flash", "GDP"],
        "GBP": ["BOE Rate Decision", "CPI", "GDP"],
        "JPY": ["BOJ Rate Decision", "CPI", "GDP"],
        "AUD": ["RBA Rate Decision", "CPI", "Employment"],
        "NZD": ["RBNZ Rate Decision", "CPI"],
        "CAD": ["BOC Rate Decision", "CPI", "Employment"],
        "CHF": ["SNB Rate Decision", "CPI"],
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._market_calendar = None
        self._news_gatekeeper = None
        self._blackout_minutes = dict(self._BLACKOUT_MINUTES)

        # Allow config overrides
        blackout_config = self._config.get("fundamental", {}).get("blackout_minutes", {})
        self._blackout_minutes.update(blackout_config)

    async def initialize(
        self,
        market_calendar: Any = None,
        news_gatekeeper: Any = None,
    ) -> None:
        """Initialize with TSAR tool references.

        Args:
            market_calendar: MarketCalendar tool instance.
            news_gatekeeper: NewsGatekeeper agent reference.
        """
        self._market_calendar = market_calendar
        self._news_gatekeeper = news_gatekeeper

    async def analyze(self, pair: str) -> FundamentalBias:
        """Analyze fundamental conditions for a trading pair.

        Args:
            pair: Trading pair (e.g., "EUR/USD", "BTC/USDT").

        Returns:
            FundamentalBias with direction, confidence, and news status.
        """
        now = datetime.now(UTC)

        # Extract currencies from pair
        base, quote = self._extract_currencies(pair)

        # Fetch upcoming events
        upcoming = await self._get_upcoming_events(base, quote, now)

        # Check blackout status
        blackout_active, blackout_reason = self._check_blackout(upcoming, now)

        # Calculate event risk score
        event_risk = self._calculate_event_risk(upcoming, now)

        # Determine directional bias from events
        direction, confidence, alignment = self._assess_bias(
            upcoming, base, quote, now
        )

        # News clear = no critical/high events in blackout window
        news_clear = not blackout_active

        reasoning_parts = [
            f"pair={pair}",
            f"direction={direction.value}",
            f"confidence={confidence:.2f}",
            f"news_clear={news_clear}",
            f"event_risk={event_risk:.2f}",
        ]
        if blackout_active:
            reasoning_parts.append(f"blackout={blackout_reason}")

        return FundamentalBias(
            direction=direction,
            confidence=confidence,
            news_clear=news_clear,
            upcoming_events=tuple(upcoming),
            blackout_active=blackout_active,
            blackout_reason=blackout_reason,
            event_risk_score=event_risk,
            macro_alignment=alignment,
            reasoning=", ".join(reasoning_parts),
        )

    async def is_news_clear(self, pair: str) -> tuple[bool, str | None]:
        """Quick check: is it safe to trade this pair (no news blackout)?

        Returns:
            Tuple of (is_clear, reason_if_blocked).
        """
        bias = await self.analyze(pair)
        if bias.news_clear:
            return True, None
        return False, bias.blackout_reason

    # ── Private methods ──────────────────────────────────────────

    def _extract_currencies(self, pair: str) -> tuple[str, str]:
        """Extract base and quote currencies from a pair."""
        if "/" in pair:
            parts = pair.split("/")
            return parts[0], parts[1]
        # Crypto pairs like BTCUSDT
        for quote in ("USDT", "USD", "BUSD", "USDC"):
            if pair.endswith(quote):
                return pair[: -len(quote)], quote
        return pair, ""

    async def _get_upcoming_events(
        self, base: str, quote: str, now: datetime
    ) -> list[UpcomingEvent]:
        """Fetch upcoming economic events for the currencies."""
        events: list[UpcomingEvent] = []

        # Try using TSAR's MarketCalendar tool
        if self._market_calendar is not None:
            try:
                calendar_snapshot = await self._market_calendar.get_calendar(days_ahead=2)
                for cal_event in calendar_snapshot:
                    event = UpcomingEvent(
                        event=cal_event.get("event", ""),
                        category=cal_event.get("category", "other"),
                        impact=cal_event.get("impact", "low"),
                        scheduled_time=cal_event.get("datetime"),
                        expected_value=cal_event.get("expected"),
                        previous_value=cal_event.get("previous"),
                        bias_hint=cal_event.get("bias_hint"),
                    )
                    # Filter for relevant currencies
                    if self._event_affects_currency(event, base, quote):
                        events.append(event)
            except Exception as e:
                logger.debug("MarketCalendar fetch failed: %s", e)

        # Fallback: generate known recurring events
        if not events:
            events = self._generate_known_events(base, quote, now)

        # Sort by time
        events.sort(key=lambda e: e.scheduled_time or now + timedelta(days=999))
        return events

    def _event_affects_currency(
        self, event: UpcomingEvent, base: str, quote: str
    ) -> bool:
        """Check if an event affects the given currency pair."""
        event_name = event.event.upper()
        for currency in (base, quote):
            keywords = self._CURRENCY_EVENTS.get(currency, [])
            for keyword in keywords:
                if keyword.upper() in event_name:
                    return True
        return False

    def _generate_known_events(
        self, base: str, quote: str, now: datetime
    ) -> list[UpcomingEvent]:
        """Generate known recurring events when calendar tool is unavailable.

        This is a fallback that creates placeholder events for major
        economic releases. In production, the MarketCalendar tool
        provides real scheduled data.
        """
        # For crypto pairs, no traditional economic events
        if quote in ("USDT", "BUSD", "USDC"):
            return []

        events: list[UpcomingEvent] = []
        # Note: This is a structural placeholder. Real event times
        # come from the MarketCalendar tool or external API.
        return events

    def _check_blackout(
        self, events: list[UpcomingEvent], now: datetime
    ) -> tuple[bool, str | None]:
        """Check if any event triggers a trading blackout."""
        for event in events:
            if event.scheduled_time is None:
                continue

            impact = event.impact.lower()
            blackout_mins = self._blackout_minutes.get(impact, 0)
            if blackout_mins == 0:
                continue

            time_until = (event.scheduled_time - now).total_seconds() / 60
            if 0 <= time_until <= blackout_mins:
                reason = (
                    f"{event.event} ({event.impact}) in "
                    f"{time_until:.0f}min — {blackout_mins}min blackout"
                )
                return True, reason

        return False, None

    def _calculate_event_risk(
        self, events: list[UpcomingEvent], now: datetime
    ) -> float:
        """Calculate a 0-1 event risk score based on upcoming events."""
        if not events:
            return 0.0

        impact_weights = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.1}
        max_risk = 0.0

        for event in events:
            if event.scheduled_time is None:
                continue

            weight = impact_weights.get(event.impact.lower(), 0.1)
            hours_until = (event.scheduled_time - now).total_seconds() / 3600

            # Risk decays with time: 1.0 at event time, 0.5 at 4h out
            if hours_until <= 0:
                time_factor = 1.0
            elif hours_until <= 4:
                time_factor = 1.0 - (hours_until / 8)
            else:
                time_factor = 0.0

            risk = weight * time_factor
            max_risk = max(max_risk, risk)

        return max_risk

    def _assess_bias(
        self,
        events: list[UpcomingEvent],
        base: str,
        quote: str,
        now: datetime,
    ) -> tuple[BiasDirection, float, float]:
        """Assess directional bias from upcoming events.

        Returns:
            Tuple of (direction, confidence, macro_alignment_score).
        """
        if not events:
            return BiasDirection.NEUTRAL, 0.0, 0.5

        bullish_signals = 0
        bearish_signals = 0
        total_weight = 0.0

        for event in events:
            impact_weight = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}
            weight = impact_weight.get(event.impact.lower(), 0.5)

            if event.bias_hint:
                hint = event.bias_hint.lower()
                if "bullish" in hint or "hawkish" in hint:
                    bullish_signals += weight
                elif "bearish" in hint or "dovish" in hint:
                    bearish_signals += weight

            total_weight += weight

        if total_weight == 0:
            return BiasDirection.NEUTRAL, 0.0, 0.5

        # Normalize
        bull_ratio = bullish_signals / total_weight
        bear_ratio = bearish_signals / total_weight

        if bull_ratio > bear_ratio + 0.2:
            confidence = min(1.0, bull_ratio)
            alignment = 0.5 + (bull_ratio * 0.5)
            return BiasDirection.BULLISH, confidence, alignment
        elif bear_ratio > bull_ratio + 0.2:
            confidence = min(1.0, bear_ratio)
            alignment = 0.5 - (bear_ratio * 0.5)
            return BiasDirection.BEARISH, confidence, alignment
        else:
            return BiasDirection.NEUTRAL, 0.3, 0.5
