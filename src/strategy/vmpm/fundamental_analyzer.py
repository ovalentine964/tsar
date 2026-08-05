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


# Pre-built neutral instance for convenience
FundamentalBias.NEUTRAL = FundamentalBias(
    direction=BiasDirection.NEUTRAL,
    confidence=0.0,
    news_clear=True,
    upcoming_events=(),
    blackout_active=False,
    blackout_reason=None,
    event_risk_score=0.0,
    macro_alignment=0.5,
    reasoning="neutral",
)


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

    def __init__(
        self, config: dict[str, Any] | None = None, *, genome: dict[str, Any] | None = None
    ) -> None:
        self._config = config or genome or {}
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

    def analyze(self, news_data: dict[str, Any] | str | None = None) -> FundamentalBias:
        """Synchronous analysis from news data dict or pair string.

        Used by EntryPipeline which runs synchronously.
        """
        if news_data is None:
            return self._neutral_bias()

        now = datetime.now(UTC)

        # If passed a string, treat as pair name
        if isinstance(news_data, str):
            return self._analyze_pair_sync(news_data, now)

        # If passed a dict, extract bias from it
        return self._analyze_from_dict(news_data, now)

    def _analyze_from_dict(self, data: dict[str, Any], now: datetime) -> FundamentalBias:
        """Analyze from a news_data dict passed by the pipeline."""
        high_impact = data.get("high_impact_near", False)
        direction_hint = data.get("bias", "neutral")

        direction = BiasDirection.NEUTRAL
        if "bullish" in str(direction_hint).lower():
            direction = BiasDirection.BULLISH
        elif "bearish" in str(direction_hint).lower():
            direction = BiasDirection.BEARISH

        return FundamentalBias(
            direction=direction,
            confidence=0.5,
            news_clear=not high_impact,
            upcoming_events=(),
            blackout_active=high_impact,
            blackout_reason="high_impact_news" if high_impact else None,
            event_risk_score=0.8 if high_impact else 0.0,
            macro_alignment=0.5,
            reasoning=f"from_dict: direction={direction.value}, high_impact={high_impact}",
        )

    def _analyze_pair_sync(self, pair: str, now: datetime) -> FundamentalBias:
        """Synchronous pair analysis (no external tool calls)."""
        base, quote = self._extract_currencies(pair)
        events = self._generate_known_events(base, quote, now)
        blackout_active, blackout_reason = self._check_blackout(events, now)
        event_risk = self._calculate_event_risk(events, now)
        direction, confidence, alignment = self._assess_bias(events, base, quote, now)

        return FundamentalBias(
            direction=direction,
            confidence=confidence,
            news_clear=not blackout_active,
            upcoming_events=tuple(events),
            blackout_active=blackout_active,
            blackout_reason=blackout_reason,
            event_risk_score=event_risk,
            macro_alignment=alignment,
            reasoning=f"sync: pair={pair}, direction={direction.value}",
        )

    def _neutral_bias(self) -> FundamentalBias:
        """Return a neutral bias when no data is available."""
        return FundamentalBias(
            direction=BiasDirection.NEUTRAL,
            confidence=0.0,
            news_clear=True,
            upcoming_events=(),
            blackout_active=False,
            blackout_reason=None,
            event_risk_score=0.0,
            macro_alignment=0.5,
            reasoning="no_data",
        )

    async def analyze_async(self, pair: str) -> FundamentalBias:
        """Async analysis with external tool integration.

        Original async interface for when MarketCalendar/NewsGatekeeper are available.
        """
        now = datetime.now(UTC)
        base, quote = self._extract_currencies(pair)
        upcoming = await self._get_upcoming_events(base, quote, now)
        blackout_active, blackout_reason = self._check_blackout(upcoming, now)
        event_risk = self._calculate_event_risk(upcoming, now)
        direction, confidence, alignment = self._assess_bias(upcoming, base, quote, now)
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
        bias = await self.analyze_async(pair)
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

    def _event_affects_currency(self, event: UpcomingEvent, base: str, quote: str) -> bool:
        """Check if an event affects the given currency pair."""
        event_name = event.event.upper()
        for currency in (base, quote):
            keywords = self._CURRENCY_EVENTS.get(currency, [])
            for keyword in keywords:
                if keyword.upper() in event_name:
                    return True
        return False

    def _generate_known_events(self, base: str, quote: str, now: datetime) -> list[UpcomingEvent]:
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

    def _calculate_event_risk(self, events: list[UpcomingEvent], now: datetime) -> float:
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
