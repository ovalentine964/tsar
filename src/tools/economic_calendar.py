"""
TSAR Domain Tools — Economic Calendar.

Tracks macroeconomic events that impact crypto markets:
  - FOMC meetings (interest rate decisions)
  - CPI releases (inflation data)
  - Non-Farm Payrolls (employment data)
  - GDP releases
  - PCE, PPI, retail sales
  - Crypto-specific events (halvings, unlocks, token releases)

Data Sources:
  - ForexFactory calendar (free JSON API)
  - Investing.com-style public endpoints
  - Hardcoded known event dates (Fed schedule)

Impact scoring: each event is scored 0-1 based on historical
market reaction magnitude.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EconomicEvent:
    """A single economic calendar event.

    Attributes:
        event: Event name (e.g. "FOMC Rate Decision").
        category: Event category ("fed", "inflation", "employment",
            "gdp", "crypto", "other").
        date: Event date (YYYY-MM-DD).
        time: Event time (HH:MM or empty if all-day).
        impact: Impact level ("high", "medium", "low").
        impact_score: Numeric impact score (0-1).
            0 = negligible, 0.5 = moderate, 1.0 = extreme.
            Based on historical crypto market reaction.
        previous: Previous value (as string, e.g. "5.25%").
        forecast: Forecasted value.
        actual: Actual value (if released).
        currency: Affected currency ("USD", "EUR", "CRYPTO").
        market_impact: Expected market impact description.
        is_released: Whether the actual value has been released.
        days_until: Days until the event (negative if past).
    """

    event: str
    category: str = "other"
    date: str = ""
    time: str = ""
    impact: str = "medium"
    impact_score: float = 0.5
    previous: str = ""
    forecast: str = ""
    actual: str = ""
    currency: str = "USD"
    market_impact: str = ""
    is_released: bool = False
    days_until: int = 0


@dataclass(frozen=True)
class EconomicCalendar:
    """Economic calendar with upcoming events.

    Attributes:
        events: All upcoming economic events.
        high_impact_events: Filtered high-impact events only.
        fed_events: FOMC/Fed-related events.
        inflation_events: CPI, PCE, PPI events.
        employment_events: NFP, unemployment events.
        crypto_events: Crypto-specific events (halvings, unlocks).
        next_fed_meeting: Date of next Fed meeting.
        days_until_fed: Days until next Fed meeting.
        risk_window: Whether a high-impact event is within 48h.
        risk_events: Events within the 48h risk window.
        timestamp: When the calendar was fetched.
    """

    events: tuple[EconomicEvent, ...]
    high_impact_events: tuple[EconomicEvent, ...] = ()
    fed_events: tuple[EconomicEvent, ...] = ()
    inflation_events: tuple[EconomicEvent, ...] = ()
    employment_events: tuple[EconomicEvent, ...] = ()
    crypto_events: tuple[EconomicEvent, ...] = ()
    next_fed_meeting: str = ""
    days_until_fed: int = 0
    risk_window: bool = False
    risk_events: tuple[EconomicEvent, ...] = ()
    timestamp: datetime | None = None


@dataclass(frozen=True)
class EventImpactAnalysis:
    """Analysis of an event's expected market impact.

    Attributes:
        event: The economic event.
        crypto_impact: Expected impact on crypto (-1 to +1).
            Positive = bullish for crypto, negative = bearish.
        volatility_expected: Expected volatility increase (0-1).
        historical_reaction: Average historical crypto reaction.
        recommendation: Trading recommendation around this event.
    """

    event: EconomicEvent
    crypto_impact: float
    volatility_expected: float
    historical_reaction: str
    recommendation: str


# ═══════════════════════════════════════════════════════════════════════
# EVENT IMPACT SCORES
# Based on historical crypto market reactions
# ═══════════════════════════════════════════════════════════════════════

_EVENT_IMPACT_SCORES: dict[str, tuple[float, str]] = {
    # Fed events — highest impact
    "fomc": (0.95, "fed"),
    "federal reserve": (0.90, "fed"),
    "interest rate": (0.90, "fed"),
    "fed chair": (0.85, "fed"),
    "powell": (0.85, "fed"),
    "fomc minutes": (0.80, "fed"),
    "fomc press": (0.85, "fed"),
    # Inflation — very high impact
    "cpi": (0.90, "inflation"),
    "consumer price": (0.85, "inflation"),
    "core cpi": (0.85, "inflation"),
    "pce": (0.80, "inflation"),
    "ppi": (0.70, "inflation"),
    "inflation": (0.75, "inflation"),
    # Employment — high impact
    "non-farm": (0.85, "employment"),
    "nonfarm": (0.85, "employment"),
    "nfp": (0.85, "employment"),
    "unemployment": (0.75, "employment"),
    "jobless claims": (0.60, "employment"),
    "jobs report": (0.80, "employment"),
    "payroll": (0.80, "employment"),
    # GDP — moderate-high impact
    "gdp": (0.75, "gdp"),
    "gross domestic": (0.70, "gdp"),
    # Other macro — moderate impact
    "retail sales": (0.60, "other"),
    "consumer confidence": (0.55, "other"),
    "housing starts": (0.40, "other"),
    "ism manufacturing": (0.55, "other"),
    "durable goods": (0.45, "other"),
    # Crypto-specific
    "halving": (0.90, "crypto"),
    "bitcoin halving": (0.95, "crypto"),
    "token unlock": (0.65, "crypto"),
    "token release": (0.60, "crypto"),
    "etf": (0.85, "crypto"),
    "sec": (0.80, "crypto"),
    "regulation": (0.70, "crypto"),
}

# FOMC meeting dates for 2024-2026 (hardcoded for reliability)
_FOMC_DATES = [
    "2025-01-29",
    "2025-03-19",
    "2025-05-07",
    "2025-06-18",
    "2025-07-30",
    "2025-09-17",
    "2025-10-29",
    "2025-12-17",
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-16",
]

# Known crypto events (example — would be updated dynamically)
_CRYPTO_EVENTS: list[dict[str, str]] = [
    # These are examples; in production, fetch from token unlock APIs
]


# ═══════════════════════════════════════════════════════════════════════
# ECONOMIC CALENDAR TOOLS
# ═══════════════════════════════════════════════════════════════════════


class EconomicCalendarTools:
    """Economic calendar tools for crypto trading.

    Tracks macroeconomic events that impact crypto markets,
    with impact scoring and risk window detection. Combines
    live data from ForexFactory with known Fed meeting dates.
    """

    description = (
        "Economic calendar: FOMC, CPI, NFP, GDP, impact scoring, risk windows, crypto events"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None

        # Cache
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 3600)  # 1h for calendar

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_cached(self, key: str) -> Any | None:
        """Get from cache if not expired."""
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        """Store in cache."""
        self._cache[key] = (time.time(), value)

    # ── Full Economic Calendar ───────────────────────────────────────

    async def get_economic_calendar(
        self,
        days_ahead: int = 14,
    ) -> EconomicCalendar:
        """Get comprehensive economic calendar for crypto trading.

        Fetches from ForexFactory and supplements with hardcoded
        Fed meeting dates. Categorizes events and computes impact
        scores based on historical crypto market reactions.

        Args:
            days_ahead: Number of days to look ahead.

        Returns:
            EconomicCalendar with categorized events and risk analysis.
        """
        cache_key = f"calendar:{days_ahead}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        now = datetime.now(UTC)

        # Fetch from ForexFactory
        ff_events = await self._fetch_forexfactory_events(client)

        # Add hardcoded FOMC dates
        fomc_events = self._generate_fomc_events(now, days_ahead)

        # Add crypto-specific events
        crypto_events = self._generate_crypto_events(now, days_ahead)

        # Combine all events
        all_events = ff_events + fomc_events + crypto_events

        # Compute days_until and filter
        processed: list[EconomicEvent] = []
        for event in all_events:
            try:
                event_date = datetime.strptime(event.date, "%Y-%m-%d").replace(tzinfo=UTC)
                days_until = (event_date - now).days
            except (ValueError, TypeError):
                days_until = 0

            if days_until < -1:  # Allow 1 day grace for "today's" events
                continue
            if days_until > days_ahead:
                continue

            processed.append(
                EconomicEvent(
                    event=event.event,
                    category=event.category,
                    date=event.date,
                    time=event.time,
                    impact=event.impact,
                    impact_score=event.impact_score,
                    previous=event.previous,
                    forecast=event.forecast,
                    actual=event.actual,
                    currency=event.currency,
                    market_impact=event.market_impact,
                    is_released=bool(event.actual),
                    days_until=max(0, days_until),
                )
            )

        # Sort by date
        processed.sort(key=lambda e: (e.date, e.time))

        # Categorize
        high_impact = tuple(e for e in processed if e.impact == "high")
        fed_events = tuple(e for e in processed if e.category == "fed")
        inflation = tuple(e for e in processed if e.category == "inflation")
        employment = tuple(e for e in processed if e.category == "employment")
        crypto = tuple(e for e in processed if e.category == "crypto")

        # Risk window: high-impact event within 48 hours
        now + timedelta(hours=48)
        risk_events = tuple(e for e in high_impact if e.days_until <= 2)

        # Next Fed meeting
        future_fed = [e for e in fed_events if e.days_until >= 0]
        next_fed = future_fed[0].date if future_fed else ""
        days_until_fed = future_fed[0].days_until if future_fed else 0

        result = EconomicCalendar(
            events=tuple(processed),
            high_impact_events=high_impact,
            fed_events=fed_events,
            inflation_events=inflation,
            employment_events=employment,
            crypto_events=crypto,
            next_fed_meeting=next_fed,
            days_until_fed=days_until_fed,
            risk_window=bool(risk_events),
            risk_events=risk_events,
            timestamp=now,
        )

        self._set_cached(cache_key, result)
        return result

    # ── Event Impact Analysis ────────────────────────────────────────

    async def analyze_event_impact(
        self,
        event: EconomicEvent,
    ) -> EventImpactAnalysis:
        """Analyze the expected market impact of an economic event.

        Evaluates how the event is likely to affect crypto markets
        based on the event type, expected vs actual values, and
        historical patterns.

        Args:
            event: The economic event to analyze.

        Returns:
            EventImpactAnalysis with impact score and recommendation.
        """
        # Base impact from event type
        base_impact = event.impact_score

        # Determine crypto impact direction
        crypto_impact = 0.0
        volatility = base_impact * 0.8
        historical = ""
        recommendation = ""

        if event.category == "fed":
            # Fed rate decisions
            if "rate" in event.event.lower() or "interest" in event.event.lower():
                # Higher rates = bearish for crypto (risk-off)
                # Lower rates = bullish for crypto (risk-on)
                if event.forecast:
                    try:
                        forecast_val = float(event.forecast.replace("%", ""))
                        if event.previous:
                            prev_val = float(event.previous.replace("%", ""))
                            if forecast_val < prev_val:
                                crypto_impact = 0.5  # Rate cut = bullish
                                historical = "Rate cuts historically bullish for crypto"
                            elif forecast_val > prev_val:
                                crypto_impact = -0.5  # Rate hike = bearish
                                historical = "Rate hikes historically bearish for crypto"
                    except ValueError:
                        pass

                volatility = 0.9  # Fed decisions always high volatility
                recommendation = "Reduce position size before FOMC, trade breakout after"

            elif "minutes" in event.event.lower():
                crypto_impact = 0.0  # Direction depends on content
                volatility = 0.6
                historical = "FOMC minutes cause moderate volatility"
                recommendation = "Wait for minutes release, trade reaction"

        elif event.category == "inflation":
            # Higher inflation = more hawkish Fed = bearish for crypto
            if event.forecast:
                try:
                    forecast_val = float(event.forecast.replace("%", ""))
                    if event.previous:
                        prev_val = float(event.previous.replace("%", ""))
                        if forecast_val < prev_val:
                            crypto_impact = 0.4  # Falling inflation = bullish
                            historical = "Cooling inflation historically bullish"
                        elif forecast_val > prev_val:
                            crypto_impact = -0.4  # Rising inflation = bearish
                            historical = "Rising inflation historically bearish"
                except ValueError:
                    pass

            volatility = 0.8
            recommendation = "High volatility expected, use wider stops"

        elif event.category == "employment":
            # Strong employment = more hawkish = bearish for crypto
            if event.forecast and event.previous:
                try:
                    forecast_val = float(event.forecast.replace("K", "").replace("M", ""))
                    prev_val = float(event.previous.replace("K", "").replace("M", ""))
                    if forecast_val > prev_val:
                        crypto_impact = -0.3  # Strong jobs = hawkish
                    elif forecast_val < prev_val:
                        crypto_impact = 0.3  # Weak jobs = dovish
                except ValueError:
                    pass

            volatility = 0.7
            historical = "NFP releases cause 2-5% BTC moves"
            recommendation = "Wait for data release, trade momentum"

        elif event.category == "crypto":
            crypto_impact = 0.0  # Depends on specific event
            volatility = 0.6
            if "halving" in event.event.lower():
                crypto_impact = 0.7
                historical = "Bitcoin halvings historically preceded bull runs"
                recommendation = "Accumulate before halving, hold through"
            elif "unlock" in event.event.lower():
                crypto_impact = -0.3
                historical = "Token unlocks create selling pressure"
                recommendation = "Expect short-term selling pressure"

        return EventImpactAnalysis(
            event=event,
            crypto_impact=round(crypto_impact, 4),
            volatility_expected=round(volatility, 4),
            historical_reaction=historical or "Limited historical data",
            recommendation=recommendation or "Monitor event closely",
        )

    # ── Risk Window Detection ────────────────────────────────────────

    async def check_risk_window(
        self,
        hours: int = 48,
    ) -> tuple[bool, tuple[EconomicEvent, ...]]:
        """Check if any high-impact events are within the risk window.

        Trading during high-impact economic events carries elevated
        risk due to increased volatility and potential for large
        unexpected moves.

        Args:
            hours: Risk window in hours.

        Returns:
            Tuple of (is_risky, risk_events).
        """
        calendar = await self.get_economic_calendar(days_ahead=7)

        cutoff_days = hours / 24
        risk_events = tuple(e for e in calendar.high_impact_events if e.days_until <= cutoff_days)

        return bool(risk_events), risk_events

    # ── ForexFactory API ─────────────────────────────────────────────

    async def _fetch_forexfactory_events(
        self,
        client: httpx.AsyncClient,
    ) -> list[EconomicEvent]:
        """Fetch economic events from ForexFactory free JSON API."""
        events: list[EconomicEvent] = []

        try:
            resp = await client.get(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data:
                title = item.get("title", "")
                impact_str = item.get("impact", "").lower()
                if impact_str not in ("high", "medium", "low"):
                    impact_str = "medium"

                # Classify category and compute impact score
                category, impact_score = self._classify_event(title)

                # Compute market impact description
                market_impact = self._describe_market_impact(title, category, impact_str)

                events.append(
                    EconomicEvent(
                        event=title,
                        category=category,
                        date=item.get("date", ""),
                        time=item.get("time", ""),
                        impact=impact_str,
                        impact_score=impact_score,
                        previous=str(item.get("previous", "")),
                        forecast=str(item.get("forecast", "")),
                        actual=str(item.get("actual", "")),
                        currency=item.get("country", "USD"),
                        market_impact=market_impact,
                    )
                )

        except Exception as exc:
            logger.warning("ForexFactory fetch failed: %s", exc)

        return events

    # ── FOMC Event Generation ────────────────────────────────────────

    def _generate_fomc_events(
        self,
        now: datetime,
        days_ahead: int,
    ) -> list[EconomicEvent]:
        """Generate FOMC meeting events from hardcoded dates."""
        events: list[EconomicEvent] = []

        for date_str in _FOMC_DATES:
            try:
                event_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
                days_until = (event_date - now).days

                if days_until < -1 or days_until > days_ahead:
                    continue

                events.append(
                    EconomicEvent(
                        event="FOMC Interest Rate Decision",
                        category="fed",
                        date=date_str,
                        time="14:00",
                        impact="high",
                        impact_score=0.95,
                        currency="USD",
                        market_impact=(
                            "Extreme volatility expected. BTC typically moves 3-8% "
                            "on FOMC decisions. Risk-off if hawkish, risk-on if dovish."
                        ),
                        days_until=max(0, days_until),
                    )
                )

                # Add FOMC press conference (same day, 30 min later)
                events.append(
                    EconomicEvent(
                        event="FOMC Press Conference",
                        category="fed",
                        date=date_str,
                        time="14:30",
                        impact="high",
                        impact_score=0.85,
                        currency="USD",
                        market_impact=(
                            "Powell's tone determines follow-through. "
                            "Watch for forward guidance clues."
                        ),
                        days_until=max(0, days_until),
                    )
                )

            except ValueError:
                continue

        return events

    # ── Crypto Event Generation ──────────────────────────────────────

    def _generate_crypto_events(
        self,
        now: datetime,
        days_ahead: int,
    ) -> list[EconomicEvent]:
        """Generate known crypto-specific events."""
        events: list[EconomicEvent] = []

        # Bitcoin halving (known date)
        halving_date = "2028-04-20"  # Next estimated halving
        try:
            halving_dt = datetime.strptime(halving_date, "%Y-%m-%d").replace(tzinfo=UTC)
            days_until = (halving_dt - now).days
            if 0 <= days_until <= days_ahead:
                events.append(
                    EconomicEvent(
                        event="Bitcoin Halving",
                        category="crypto",
                        date=halving_date,
                        impact="high",
                        impact_score=0.90,
                        currency="CRYPTO",
                        market_impact=(
                            "Block reward reduction from 6.25 to 3.125 BTC. "
                            "Historically preceded major bull runs."
                        ),
                        days_until=days_until,
                    )
                )
        except ValueError:
            pass

        # Add any dynamically configured crypto events
        for evt in _CRYPTO_EVENTS:
            try:
                evt_date = datetime.strptime(evt["date"], "%Y-%m-%d").replace(tzinfo=UTC)
                days_until = (evt_date - now).days
                if 0 <= days_until <= days_ahead:
                    events.append(
                        EconomicEvent(
                            event=evt.get("name", "Crypto Event"),
                            category="crypto",
                            date=evt["date"],
                            impact=evt.get("impact", "medium"),
                            impact_score=float(evt.get("impact_score", 0.5)),
                            currency="CRYPTO",
                            market_impact=evt.get("description", ""),
                            days_until=days_until,
                        )
                    )
            except (ValueError, KeyError):
                continue

        return events

    # ── Event Classification ─────────────────────────────────────────

    @staticmethod
    def _classify_event(title: str) -> tuple[str, float]:
        """Classify an event by category and compute impact score.

        Args:
            title: Event title.

        Returns:
            Tuple of (category, impact_score).
        """
        title_lower = title.lower()

        for keyword, (score, category) in _EVENT_IMPACT_SCORES.items():
            if keyword in title_lower:
                return category, score

        return "other", 0.3

    @staticmethod
    def _describe_market_impact(
        title: str,
        category: str,
        impact: str,
    ) -> str:
        """Generate market impact description for an event."""
        if category == "fed":
            return (
                "Fed decisions directly impact risk appetite. "
                "Crypto typically shows 3-8% moves on FOMC days."
            )
        elif category == "inflation":
            return (
                "Inflation data influences Fed policy expectations. "
                "Higher-than-expected = hawkish = bearish for crypto."
            )
        elif category == "employment":
            return (
                "Employment data affects rate expectations. "
                "Strong jobs = hawkish Fed = pressure on risk assets."
            )
        elif category == "gdp":
            return (
                "GDP data provides macro context. "
                "Strong GDP can be hawkish (bearish) or risk-on (bullish)."
            )
        elif category == "crypto":
            return "Crypto-native event with direct market impact."

        if impact == "high":
            return "High-impact event — expect increased volatility."
        elif impact == "medium":
            return "Moderate impact — may cause short-term moves."
        return "Low impact — minimal expected market reaction."
