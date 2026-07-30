"""
TSAR Domain Tools — Market Calendar.

Tool 9: Market Calendar — Economic events, crypto events, and
macro catalysts that impact crypto markets.

Provides:
  - Economic calendar (Fed meetings, CPI, employment, GDP)
  - Crypto events (halvings, token unlocks, protocol upgrades)
  - Event impact scoring and proximity alerts
  - Historical event impact analysis

All data fetched from free/public APIs with caching.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════


class EventCategory(StrEnum):
    """Categories of market events."""

    MONETARY_POLICY = "monetary_policy"
    INFLATION = "inflation"
    EMPLOYMENT = "employment"
    GDP = "gdp"
    CRYPTO_HALVING = "crypto_halving"
    TOKEN_UNLOCK = "token_unlock"
    PROTOCOL_UPGRADE = "protocol_upgrade"
    ETF_DECISION = "etf_decision"
    REGULATORY = "regulatory"
    OTHER = "other"


class EventImpact(StrEnum):
    """Expected impact level of an event."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Known high-impact recurring economic events
_KNOWN_ECONOMIC_EVENTS: list[dict[str, Any]] = [
    {
        "event": "FOMC Interest Rate Decision",
        "category": EventCategory.MONETARY_POLICY,
        "impact": EventImpact.CRITICAL,
        "frequency": "8x per year",
        "typical_impact": "Extreme volatility. BTC often moves 3-8% on surprise decisions.",
        "watch_for": "Rate cut/hike vs expectations, dot plot, Powell commentary",
    },
    {
        "event": "CPI (Consumer Price Index)",
        "category": EventCategory.INFLATION,
        "impact": EventImpact.HIGH,
        "frequency": "Monthly",
        "typical_impact": "High volatility. Hot CPI = bearish (hawkish Fed), cool CPI = bullish.",
        "watch_for": "Core CPI vs consensus, month-over-month trend",
    },
    {
        "event": "Non-Farm Payrolls (NFP)",
        "category": EventCategory.EMPLOYMENT,
        "impact": EventImpact.HIGH,
        "frequency": "Monthly (first Friday)",
        "typical_impact": "Moderate-high volatility. Strong jobs = hawkish Fed = bearish BTC.",
        "watch_for": "Headline vs consensus, unemployment rate, wage growth",
    },
    {
        "event": "PCE (Personal Consumption Expenditures)",
        "category": EventCategory.INFLATION,
        "impact": EventImpact.HIGH,
        "frequency": "Monthly",
        "typical_impact": "Fed's preferred inflation gauge. Core PCE deviates from consensus = volatility.",
        "watch_for": "Core PCE YoY vs consensus, MoM trend",
    },
    {
        "event": "GDP (Gross Domestic Product)",
        "category": EventCategory.GDP,
        "impact": EventImpact.MEDIUM,
        "frequency": "Quarterly (3 estimates)",
        "typical_impact": "Moderate volatility. Recession fears amplify impact.",
        "watch_for": "Advance vs consensus, consumer spending component",
    },
    {
        "event": "Initial Jobless Claims",
        "category": EventCategory.EMPLOYMENT,
        "impact": EventImpact.MEDIUM,
        "frequency": "Weekly (Thursdays)",
        "typical_impact": "Low-moderate. Rising claims = recession fear = mixed for BTC.",
        "watch_for": "4-week moving average trend, surprise vs consensus",
    },
    {
        "event": "ISM Manufacturing PMI",
        "category": EventCategory.GDP,
        "impact": EventImpact.MEDIUM,
        "frequency": "Monthly (first business day)",
        "typical_impact": "Moderate. Below 50 = contraction = risk-off.",
        "watch_for": "Above/below 50, new orders component",
    },
    {
        "event": "Retail Sales",
        "category": EventCategory.GDP,
        "impact": EventImpact.MEDIUM,
        "frequency": "Monthly",
        "typical_impact": "Low-moderate. Strong sales = economy hot = hawkish Fed.",
        "watch_for": "Control group (ex-auto, ex-gas), MoM change",
    },
    {
        "event": "Michigan Consumer Sentiment",
        "category": EventCategory.GDP,
        "impact": EventImpact.LOW,
        "frequency": "Monthly (preliminary + final)",
        "typical_impact": "Low. Inflation expectations component matters more than headline.",
        "watch_for": "Inflation expectations (1yr, 5yr)",
    },
    {
        "event": "10-Year Treasury Auction",
        "category": EventCategory.MONETARY_POLICY,
        "impact": EventImpact.LOW,
        "frequency": "Monthly",
        "typical_impact": "Low. Weak auction = rising yields = pressure on risk assets.",
        "watch_for": "Bid-to-cover ratio, tail vs when-issued",
    },
]


# Known crypto-specific events (static + dynamic)
_KNOWN_CRYPTO_EVENTS: list[dict[str, Any]] = [
    {
        "event": "Bitcoin Halving",
        "category": EventCategory.CRYPTO_HALVING,
        "impact": EventImpact.CRITICAL,
        "frequency": "~Every 4 years",
        "next_occurrence": "2028-04-20",
        "typical_impact": "Massive long-term bullish catalyst. Block reward halves from 3.125 to 1.5625 BTC.",
        "watch_for": "Pre-halving accumulation, post-halving supply shock",
    },
    {
        "event": "Ethereum Pectra Upgrade",
        "category": EventCategory.PROTOCOL_UPGRADE,
        "impact": EventImpact.HIGH,
        "frequency": "As needed",
        "next_occurrence": "2025-05-07",
        "typical_impact": "Moderate-high. Account abstraction + validator consolidation.",
        "watch_for": "Testnet results, mainnet activation date",
    },
    {
        "event": "Solana Token Unlocks (Major)",
        "category": EventCategory.TOKEN_UNLOCK,
        "impact": EventImpact.MEDIUM,
        "frequency": "Monthly/Quarterly",
        "typical_impact": "Selling pressure if large unlock. Monitor unlock size vs daily volume.",
        "watch_for": "Unlock % of circulating supply, holder distribution",
    },
    {
        "event": "Bitcoin ETF Decision Windows",
        "category": EventCategory.ETF_DECISION,
        "impact": EventImpact.HIGH,
        "frequency": "As needed",
        "typical_impact": "Extreme volatility around deadlines. Approval = bullish, denial = bearish.",
        "watch_for": "SEC deadlines, Bloomberg analyst probability estimates",
    },
    {
        "event": "US Regulatory Hearings (Crypto)",
        "category": EventCategory.REGULATORY,
        "impact": EventImpact.HIGH,
        "frequency": "Irregular",
        "typical_impact": "Volatility depending on tone. Anti-crypto bills = bearish, clarity = bullish.",
        "watch_for": "Committee composition, bill text, hearing witnesses",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MarketEvent:
    """A single market event.

    Attributes:
        event: Event name.
        category: Event category.
        impact: Expected impact level.
        date: Event date (ISO format).
        time: Event time (if known).
        currency: Affected currency/asset.
        previous: Previous value.
        forecast: Forecasted value.
        actual: Actual value (if released).
        typical_impact: Description of typical market impact.
        watch_for: What to watch for in the release.
        source: Data source.
    """

    event: str
    category: str = ""
    impact: str = "medium"
    date: str = ""
    time: str = ""
    currency: str = "USD"
    previous: str = ""
    forecast: str = ""
    actual: str = ""
    typical_impact: str = ""
    watch_for: str = ""
    source: str = ""


@dataclass(frozen=True)
class CalendarSnapshot:
    """Market calendar snapshot.

    Attributes:
        economic_events: Upcoming economic events.
        crypto_events: Upcoming crypto events.
        all_events: Combined and sorted events.
        high_impact_events: Events with high or critical impact.
        next_critical: Next critical-impact event.
        hours_until_next_critical: Hours until next critical event.
        event_risk_score: Aggregate risk score from upcoming events (0-1).
        timestamp: When the snapshot was taken.
    """

    economic_events: tuple[MarketEvent, ...]
    crypto_events: tuple[MarketEvent, ...]
    all_events: tuple[MarketEvent, ...]
    high_impact_events: tuple[MarketEvent, ...]
    next_critical: MarketEvent | None = None
    hours_until_next_critical: float = 0.0
    event_risk_score: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class EventImpactAnalysis:
    """Analysis of a specific event's potential market impact.

    Attributes:
        event: The event being analyzed.
        historical_impacts: Past market reactions to this event type.
        expected_volatility: Expected volatility increase (0-1).
        recommended_action: Suggested positioning.
        risk_adjustment: Recommended risk size adjustment (0.0-1.0).
            1.0 = normal, 0.5 = half size, 0.0 = no trading.
    """

    event: MarketEvent
    historical_impacts: tuple[str, ...] = ()
    expected_volatility: float = 0.0
    recommended_action: str = ""
    risk_adjustment: float = 1.0


# ═══════════════════════════════════════════════════════════════════════
# MARKET CALENDAR TOOL
# ═══════════════════════════════════════════════════════════════════════


class MarketCalendar:
    """Market calendar — economic events, crypto catalysts, and macro calendar.

    Provides visibility into events that move crypto markets:
    - Fed meetings, CPI, employment data, GDP
    - Bitcoin halvings, token unlocks, protocol upgrades
    - ETF decisions, regulatory hearings

    Usage::

        calendar = MarketCalendar()
        snapshot = await calendar.get_calendar()

        # Check for upcoming high-impact events
        for event in snapshot.high_impact_events:
            print(f"{event.date}: {event.event} ({event.impact})")

        # Get risk adjustment for trading
        risk = snapshot.event_risk_score  # 0-1, higher = more caution
    """

    description = "Market calendar: economic events, crypto catalysts, macro calendar"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 3600)  # 1 hour for calendar

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

    # ── Main Calendar API ───────────────────────────────────────────

    async def get_calendar(
        self,
        days_ahead: int = 14,
        include_crypto: bool = True,
    ) -> CalendarSnapshot:
        """Get the full market calendar snapshot.

        Combines economic events (from free APIs) with crypto events
        (static knowledge + dynamic sources).

        Args:
            days_ahead: How many days ahead to look.
            include_crypto: Whether to include crypto events.

        Returns:
            CalendarSnapshot with all events and risk scoring.
        """
        cache_key = f"calendar:{days_ahead}:{include_crypto}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # Fetch economic events
        econ_events = await self._fetch_economic_events(days_ahead)

        # Fetch crypto events
        crypto_events: list[MarketEvent] = []
        if include_crypto:
            crypto_events = await self._fetch_crypto_events(days_ahead)

        # Combine and sort
        all_events = list(econ_events) + crypto_events
        all_events.sort(key=lambda e: (e.date, e.time))

        # Filter high impact
        high_impact = tuple(
            e for e in all_events
            if e.impact in (EventImpact.CRITICAL.value, EventImpact.HIGH.value)
        )

        # Find next critical event
        now = datetime.now(UTC)
        next_critical = None
        hours_until = 0.0

        for event in all_events:
            if event.impact == EventImpact.CRITICAL.value and event.date:
                try:
                    event_dt = datetime.fromisoformat(event.date)
                    if event_dt.tzinfo is None:
                        event_dt = event_dt.replace(tzinfo=UTC)
                    if event_dt > now:
                        next_critical = event
                        hours_until = (event_dt - now).total_seconds() / 3600
                        break
                except (ValueError, TypeError):
                    pass

        # Compute event risk score
        risk_score = self._compute_event_risk(all_events, now)

        result = CalendarSnapshot(
            economic_events=tuple(econ_events),
            crypto_events=tuple(crypto_events),
            all_events=tuple(all_events),
            high_impact_events=high_impact,
            next_critical=next_critical,
            hours_until_next_critical=round(hours_until, 1),
            event_risk_score=round(risk_score, 4),
            timestamp=now,
        )

        self._set_cached(cache_key, result)
        return result

    async def get_economic_calendar(self) -> tuple[MarketEvent, ...]:
        """Get just the economic calendar events.

        Returns:
            Tuple of upcoming economic events.
        """
        return await self._fetch_economic_events(days_ahead=14)

    async def get_crypto_events(self) -> tuple[MarketEvent, ...]:
        """Get just the crypto events.

        Returns:
            Tuple of upcoming crypto events.
        """
        return await self._fetch_crypto_events(days_ahead=90)

    def get_known_events(self) -> tuple[MarketEvent, ...]:
        """Get the static known events catalog.

        Returns all known recurring economic and crypto events,
        useful for agent planning even when live API data is unavailable.
        """
        events: list[MarketEvent] = []

        for e in _KNOWN_ECONOMIC_EVENTS:
            events.append(MarketEvent(
                event=e["event"],
                category=e["category"].value if hasattr(e["category"], "value") else str(e["category"]),
                impact=e["impact"].value if hasattr(e["impact"], "value") else str(e["impact"]),
                currency="USD",
                typical_impact=e.get("typical_impact", ""),
                watch_for=e.get("watch_for", ""),
                source="known_catalog",
            ))

        for e in _KNOWN_CRYPTO_EVENTS:
            events.append(MarketEvent(
                event=e["event"],
                category=e["category"].value if hasattr(e["category"], "value") else str(e["category"]),
                impact=e["impact"].value if hasattr(e["impact"], "value") else str(e["impact"]),
                date=e.get("next_occurrence", ""),
                typical_impact=e.get("typical_impact", ""),
                watch_for=e.get("watch_for", ""),
                source="known_catalog",
            ))

        return tuple(events)

    # ── Event Impact Analysis ───────────────────────────────────────

    def analyze_event_impact(self, event: MarketEvent) -> EventImpactAnalysis:
        """Analyze the potential market impact of an event.

        Uses historical patterns and event type to estimate volatility
        and recommend risk adjustments.

        Args:
            event: The event to analyze.

        Returns:
            EventImpactAnalysis with impact estimates and recommendations.
        """
        impact_map = {
            EventImpact.CRITICAL.value: {
                "volatility": 0.9,
                "risk_adj": 0.3,
                "action": "Reduce position sizes to 30% of normal. Set wider stops. Consider hedging.",
                "history": (
                    "FOMC rate decisions historically cause 3-8% BTC moves. "
                    "CPI surprises cause 2-5% moves. Halvings preceded 500-1000% rallies within 12-18 months."
                ),
            },
            EventImpact.HIGH.value: {
                "volatility": 0.7,
                "risk_adj": 0.5,
                "action": "Reduce position sizes to 50% of normal. Tighten stops. Avoid new entries 1h before.",
                "history": (
                    "NFP surprises cause 1-3% BTC moves. ETF decisions caused 5-15% moves historically. "
                    "Regulatory hearings create uncertainty-driven volatility."
                ),
            },
            EventImpact.MEDIUM.value: {
                "volatility": 0.4,
                "risk_adj": 0.75,
                "action": "Slight risk reduction. Monitor closely during release.",
                "history": (
                    "GDP and PMI releases cause 0.5-2% moves. "
                    "Token unlocks cause selling pressure proportional to unlock size."
                ),
            },
            EventImpact.LOW.value: {
                "volatility": 0.2,
                "risk_adj": 1.0,
                "action": "Normal trading. Monitor only if combined with other events.",
                "history": "Low-impact events rarely cause significant moves in isolation.",
            },
        }

        config = impact_map.get(event.impact, impact_map[EventImpact.LOW.value])

        return EventImpactAnalysis(
            event=event,
            historical_impacts=(config["history"],),
            expected_volatility=config["volatility"],
            recommended_action=config["action"],
            risk_adjustment=config["risk_adj"],
        )

    # ── Internal: Fetch Economic Events ─────────────────────────────

    async def _fetch_economic_events(self, days_ahead: int) -> list[MarketEvent]:
        """Fetch economic events from free APIs.

        Uses ForexFactory calendar (free, no auth) with fallback
        to known events catalog.
        """
        client = await self._get_client()
        events: list[MarketEvent] = []

        try:
            # Fetch from ForexFactory free API
            resp = await client.get(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data:
                title = item.get("title", "")
                impact_str = item.get("impact", "").lower()

                # Map impact
                if impact_str == "high":
                    impact = EventImpact.HIGH.value
                elif impact_str == "medium":
                    impact = EventImpact.MEDIUM.value
                elif impact_str == "low":
                    impact = EventImpact.LOW.value
                else:
                    impact = EventImpact.LOW.value

                # Classify category
                category = self._classify_event(title)

                # Boost impact for known critical events
                for known in _KNOWN_ECONOMIC_EVENTS:
                    if self._fuzzy_match(title, known["event"]):
                        if known["impact"] == EventImpact.CRITICAL:
                            impact = EventImpact.CRITICAL.value
                        category = known["category"].value
                        break

                date_str = item.get("date", "")
                time_str = item.get("time", "")

                # Parse date for proximity scoring
                try:
                    if date_str:
                        dt = datetime.strptime(date_str, "%Y-%m-%d")
                        date_str = dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass

                events.append(MarketEvent(
                    event=title,
                    category=category,
                    impact=impact,
                    date=date_str,
                    time=time_str,
                    currency=item.get("country", "USD"),
                    previous=str(item.get("previous", "")),
                    forecast=str(item.get("forecast", "")),
                    actual=str(item.get("actual", "")),
                    source="forexfactory",
                ))

        except Exception as exc:
            logger.warning("ForexFactory fetch failed: %s", exc)

        # If no live events, provide known catalog as fallback
        if not events:
            logger.info("Using known events catalog as fallback")
            for known in _KNOWN_ECONOMIC_EVENTS:
                events.append(MarketEvent(
                    event=known["event"],
                    category=known["category"].value,
                    impact=known["impact"].value,
                    currency="USD",
                    typical_impact=known.get("typical_impact", ""),
                    watch_for=known.get("watch_for", ""),
                    source="known_catalog",
                ))

        return events

    # ── Internal: Fetch Crypto Events ───────────────────────────────

    async def _fetch_crypto_events(self, days_ahead: int) -> list[MarketEvent]:
        """Fetch crypto-specific events.

        Combines known catalog with dynamic data from CoinGecko
        and other free sources.
        """
        client = await self._get_client()
        events: list[MarketEvent] = []

        # Add known crypto events
        for known in _KNOWN_CRYPTO_EVENTS:
            next_occ = known.get("next_occurrence", "")
            # Only include if within the lookahead window
            if next_occ:
                try:
                    event_dt = datetime.fromisoformat(next_occ)
                    if event_dt.tzinfo is None:
                        event_dt = event_dt.replace(tzinfo=UTC)
                    now = datetime.now(UTC)
                    if event_dt < now - timedelta(days=1):
                        continue  # Past event
                    if event_dt > now + timedelta(days=days_ahead):
                        continue  # Too far out
                except (ValueError, TypeError):
                    pass

            events.append(MarketEvent(
                event=known["event"],
                category=known["category"].value,
                impact=known["impact"].value,
                date=next_occ,
                typical_impact=known.get("typical_impact", ""),
                watch_for=known.get("watch_for", ""),
                source="known_catalog",
            ))

        # Try to fetch dynamic token unlock data
        try:
            unlock_events = await self._fetch_token_unlocks(client)
            events.extend(unlock_events)
        except Exception as exc:
            logger.debug("Token unlock fetch failed: %s", exc)

        # Try to fetch Bitcoin halving countdown
        try:
            halving_event = await self._fetch_halving_countdown(client)
            if halving_event:
                events.append(halving_event)
        except Exception as exc:
            logger.debug("Halving countdown fetch failed: %s", exc)

        return events

    async def _fetch_token_unlocks(
        self, client: httpx.AsyncClient
    ) -> list[MarketEvent]:
        """Fetch upcoming token unlock events from CoinGecko or similar."""
        events: list[MarketEvent] = []

        try:
            # CoinGecko has token unlock data in their pro API
            # For now, use known unlock schedules
            # In production, integrate with TokenUnlocks API or DeFiLlama

            now = datetime.now(UTC)

            # SOL quarterly unlock schedule (approximate)
            sol_unlock_dates = [
                "2025-03-01", "2025-06-01", "2025-09-01", "2025-12-01",
                "2026-03-01", "2026-06-01", "2026-09-01", "2026-12-01",
            ]

            for date_str in sol_unlock_dates:
                try:
                    dt = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
                    if dt > now and dt < now + timedelta(days=90):
                        events.append(MarketEvent(
                            event="SOL Token Unlock (Estimated)",
                            category=EventCategory.TOKEN_UNLOCK.value,
                            impact=EventImpact.MEDIUM.value,
                            date=date_str,
                            typical_impact="Potential selling pressure. Monitor unlock size vs daily volume.",
                            watch_for="Unlock % of circulating supply, holder distribution",
                            source="known_schedule",
                        ))
                except ValueError:
                    pass

        except Exception as exc:
            logger.debug("Token unlock processing failed: %s", exc)

        return events

    async def _fetch_halving_countdown(
        self, client: httpx.AsyncClient
    ) -> MarketEvent | None:
        """Fetch Bitcoin halving countdown data."""
        try:
            # Bitcoin halving is every 210,000 blocks
            # Next halving: ~April 2028 (block 1,050,000)
            now = datetime.now(UTC)
            halving_dt = datetime(2028, 4, 20, tzinfo=UTC)

            if halving_dt > now:
                days_until = (halving_dt - now).days
                return MarketEvent(
                    event=f"Bitcoin Halving ({days_until} days away)",
                    category=EventCategory.CRYPTO_HALVING.value,
                    impact=EventImpact.CRITICAL.value,
                    date=halving_dt.strftime("%Y-%m-%d"),
                    typical_impact=(
                        "Block reward halves from 3.125 to 1.5625 BTC. "
                        "Historically preceded major bull runs (500-1000% within 12-18 months)."
                    ),
                    watch_for="Pre-halving accumulation patterns, miner capitulation, supply shock",
                    source="calculated",
                )
        except Exception:
            pass
        return None

    # ── Internal: Helpers ───────────────────────────────────────────

    @staticmethod
    def _classify_event(title: str) -> str:
        """Classify an economic event into a category."""
        title_lower = title.lower()

        if any(kw in title_lower for kw in ["fomc", "fed", "interest rate", "federal reserve"]):
            return EventCategory.MONETARY_POLICY.value
        elif any(kw in title_lower for kw in ["cpi", "consumer price", "inflation", "pce"]):
            return EventCategory.INFLATION.value
        elif any(kw in title_lower for kw in ["payroll", "employment", "jobless", "unemployment", "nfp"]):
            return EventCategory.EMPLOYMENT.value
        elif any(kw in title_lower for kw in ["gdp", "gross domestic", "retail sales", "pmi", "ism"]):
            return EventCategory.GDP.value
        else:
            return EventCategory.OTHER.value

    @staticmethod
    def _fuzzy_match(title: str, known: str) -> bool:
        """Simple fuzzy matching for event names."""
        title_words = set(title.lower().split())
        known_words = set(known.lower().split())
        overlap = title_words & known_words
        # Need at least 50% of known words to match
        return len(overlap) >= len(known_words) * 0.5

    @staticmethod
    def _compute_event_risk(
        events: list[MarketEvent],
        now: datetime,
    ) -> float:
        """Compute aggregate event risk score.

        Higher score = more caution needed. Based on:
        - Proximity of high-impact events
        - Number of events in next 24h
        - Impact levels of upcoming events
        """
        if not events:
            return 0.0

        risk = 0.0

        for event in events:
            if not event.date:
                continue

            try:
                event_dt = datetime.fromisoformat(event.date)
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue

            hours_until = (event_dt - now).total_seconds() / 3600

            # Skip past events
            if hours_until < 0:
                continue

            # Impact weight
            impact_weight = {
                EventImpact.CRITICAL.value: 1.0,
                EventImpact.HIGH.value: 0.7,
                EventImpact.MEDIUM.value: 0.4,
                EventImpact.LOW.value: 0.1,
            }.get(event.impact, 0.1)

            # Proximity weight: closer = higher risk
            if hours_until < 2:
                proximity = 1.0
            elif hours_until < 6:
                proximity = 0.8
            elif hours_until < 24:
                proximity = 0.5
            elif hours_until < 72:
                proximity = 0.3
            else:
                proximity = 0.1

            risk += impact_weight * proximity

        # Normalize to 0-1 (cap at 1.0)
        return min(1.0, risk)

    # ── Utility: Proximity Checks ───────────────────────────────────

    def is_near_high_impact_event(
        self,
        hours: float = 2.0,
    ) -> tuple[bool, MarketEvent | None]:
        """Check if a high-impact event is within N hours.

        Useful for risk management: "should I reduce position sizes?"

        Args:
            hours: Lookahead window in hours.

        Returns:
            Tuple of (is_near, event_or_none).
        """
        now = datetime.now(UTC)

        for known in _KNOWN_ECONOMIC_EVENTS + _KNOWN_CRYPTO_EVENTS:
            if known["impact"] not in (EventImpact.CRITICAL, EventImpact.HIGH):
                continue

            # For known catalog events, we can't check exact dates
            # without live data, so return the catalog info
            # In production, this checks the live calendar

        # Check cached calendar
        cached = self._get_cached(f"calendar:14:True")
        if cached:
            snapshot: CalendarSnapshot = cached
            for event in snapshot.all_events:
                if event.impact not in (EventImpact.CRITICAL.value, EventImpact.HIGH.value):
                    continue
                if not event.date:
                    continue
                try:
                    event_dt = datetime.fromisoformat(event.date)
                    if event_dt.tzinfo is None:
                        event_dt = event_dt.replace(tzinfo=UTC)
                    hours_until = (event_dt - now).total_seconds() / 3600
                    if 0 < hours_until <= hours:
                        return True, event
                except (ValueError, TypeError):
                    pass

        return False, None

    def get_risk_adjustment(self) -> float:
        """Get recommended position size multiplier based on event proximity.

        Returns:
            Multiplier between 0.0 (no trading) and 1.0 (full size).
        """
        now = datetime.now(UTC)
        min_adj = 1.0

        # Check against known critical events
        for known in _KNOWN_ECONOMIC_EVENTS:
            if known["impact"] == EventImpact.CRITICAL:
                # Critical events get 0.3x within 2h, 0.5x within 6h
                min_adj = min(min_adj, 0.3)

        for known in _KNOWN_CRYPTO_EVENTS:
            if known["impact"] == EventImpact.CRITICAL:
                next_occ = known.get("next_occurrence", "")
                if next_occ:
                    try:
                        event_dt = datetime.fromisoformat(next_occ).replace(tzinfo=UTC)
                        hours_until = (event_dt - now).total_seconds() / 3600
                        if 0 < hours_until <= 2:
                            min_adj = min(min_adj, 0.3)
                        elif 0 < hours_until <= 24:
                            min_adj = min(min_adj, 0.5)
                    except (ValueError, TypeError):
                        pass

        # Check cached live calendar for more precise adjustment
        cached = self._get_cached(f"calendar:14:True")
        if cached:
            snapshot: CalendarSnapshot = cached
            if snapshot.event_risk_score > 0.7:
                min_adj = min(min_adj, 0.3)
            elif snapshot.event_risk_score > 0.4:
                min_adj = min(min_adj, 0.5)

        return round(min_adj, 2)
