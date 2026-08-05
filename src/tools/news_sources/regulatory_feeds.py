"""
TSAR — Regulatory Feed Monitor.

Monitors regulatory enforcement actions and policy changes from:
  - SEC (Securities and Exchange Commission) — EDGAR, press releases
  - CFTC (Commodity Futures Trading Commission) — enforcement actions
  - Ripple/XRP case developments (ongoing precedent-setting case)
  - DOJ crypto task force announcements
  - International regulators (FCA, MAS, ESMA highlights)

Regulatory news is classified as CRITICAL or HIGH severity because
enforcement actions can immediately impact token prices and exchange operations.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


class Regulator(StrEnum):
    """Regulatory body identifiers."""

    SEC = "SEC"
    CFTC = "CFTC"
    DOJ = "DOJ"
    FCA = "FCA"  # UK Financial Conduct Authority
    MAS = "MAS"  # Monetary Authority of Singapore
    ESMA = "ESMA"  # European Securities and Markets Authority
    RIPPLE_CASE = "RIPPLE_CASE"  # SEC v. Ripple special tracking
    OTHER = "OTHER"


class RegulatorySeverity(StrEnum):
    """Severity of regulatory action."""

    CRITICAL = "critical"  # Enforcement action against major entity
    HIGH = "high"  # New regulation, policy change, lawsuit filing
    MEDIUM = "medium"  # Guidance, commentary, proposed rules
    LOW = "low"  # General commentary, speeches


@dataclass(frozen=True)
class RegulatoryItem:
    """A single regulatory news item.

    Attributes:
        regulator: Which regulatory body.
        title: Title of the action/release.
        url: Link to official source.
        severity: Severity classification.
        summary: Brief summary of the action.
        affected_assets: Tokens/projects potentially affected.
        published_at: Publication timestamp.
        is_enforcement: Whether this is an enforcement action.
    """

    regulator: Regulator
    title: str
    url: str = ""
    severity: RegulatorySeverity = RegulatorySeverity.LOW
    summary: str = ""
    affected_assets: tuple[str, ...] = ()
    published_at: datetime | None = None
    is_enforcement: bool = False


@dataclass
class RegulatoryDigest:
    """Aggregated regulatory digest.

    Attributes:
        items: All regulatory items found.
        critical_count: Number of CRITICAL items.
        enforcement_count: Number of enforcement actions.
        affected_symbols: All symbols potentially affected.
        sentiment: Aggregate regulatory sentiment (-1 = hostile, 0 = neutral).
        timestamp: When the digest was compiled.
    """

    items: list[RegulatoryItem] = field(default_factory=list)
    critical_count: int = 0
    enforcement_count: int = 0
    affected_symbols: list[str] = field(default_factory=list)
    sentiment: float = 0.0
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# FEED URLS
# ═══════════════════════════════════════════════════════════════════════

_FEEDS: dict[str, str] = {
    "SEC_LITIGATION": "https://www.sec.gov/rss/litigation/litreleases.xml",
    "SEC_PRESS": "https://www.sec.gov/rss/news/press.xml",
    "CFTC_ENFORCEMENT": "https://www.cftc.gov/rss/PressReleases",
}

# Keywords that indicate crypto-related enforcement
_CRYPTO_ENFORCEMENT_KEYWORDS = frozenset(
    {
        "crypto",
        "cryptocurrency",
        "digital asset",
        "virtual asset",
        "bitcoin",
        "ethereum",
        "blockchain",
        "token",
        "defi",
        "stablecoin",
        "binance",
        "coinbase",
        "ripple",
        "xrp",
        "securities fraud",
        "unregistered",
        "exchange",
        "ico",
        "staking",
        "lending",
        "mining",
        "nft",
    }
)

# Keywords that indicate severity
_CRITICAL_KEYWORDS = frozenset(
    {
        "charges filed",
        "enforcement action",
        "emergency order",
        "asset freeze",
        "temporary restraining order",
        "fraud",
        "ponzi",
        "manipulation",
        "insider trading",
    }
)

_HIGH_KEYWORDS = frozenset(
    {
        "proposed rule",
        "final rule",
        "guidance",
        "framework",
        "settlement",
        "consent order",
        "penalty",
        "fine",
        "lawsuit",
        "complaint",
        "investigation",
    }
)


# ═══════════════════════════════════════════════════════════════════════
# REGULATORY FEED MONITOR
# ═══════════════════════════════════════════════════════════════════════


class RegulatoryFeedMonitor:
    """Monitors regulatory feeds for crypto-relevant enforcement actions.

    Aggregates RSS feeds from SEC, CFTC, and tracks the Ripple case.
    Classifies items by severity and identifies affected tokens/projects.

    Usage:
        monitor = RegulatoryFeedMonitor()
        digest = await monitor.get_regulatory_digest()
        for item in digest.items:
            if item.severity == "critical":
                print(f"ALERT: {item.title}")
    """

    description = (
        "Regulatory monitoring: SEC/CFTC enforcement, Ripple case tracking, "
        "crypto regulation updates, affected asset identification"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None

        # Cache
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 300)  # 5 min

        # Ripple case tracking state
        self._ripple_last_check: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={"User-Agent": "TSAR/1.0 (Crypto Regulatory Monitor)"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)

    # ── Public API ───────────────────────────────────────────────────

    async def get_regulatory_digest(
        self,
        symbol: str | None = None,
    ) -> RegulatoryDigest:
        """Get aggregated regulatory digest.

        Args:
            symbol: Optional symbol to filter by relevance.

        Returns:
            RegulatoryDigest with classified items.
        """
        cache_key = f"reg_digest:{symbol or 'all'}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # Fetch from all sources in parallel
        items: list[RegulatoryItem] = []

        feeds = await self._fetch_all_feeds()
        items.extend(feeds)

        # Filter by symbol relevance if specified
        if symbol:
            base = symbol.split("/")[0].upper()
            items = [i for i in items if self._is_relevant(i, base)]

        # Sort by severity and recency
        severity_order = {
            RegulatorySeverity.CRITICAL: 0,
            RegulatorySeverity.HIGH: 1,
            RegulatorySeverity.MEDIUM: 2,
            RegulatorySeverity.LOW: 3,
        }
        items.sort(
            key=lambda x: (
                severity_order.get(x.severity, 99),
                x.published_at or datetime.min,
            ),
        )

        # Build digest
        critical_count = sum(1 for i in items if i.severity == RegulatorySeverity.CRITICAL)
        enforcement_count = sum(1 for i in items if i.is_enforcement)

        affected_symbols: set[str] = set()
        for item in items:
            affected_symbols.update(item.affected_assets)

        # Regulatory sentiment (enforcement = bearish, approvals = bullish)
        if items:
            sentiments = []
            for item in items:
                if item.severity == RegulatorySeverity.CRITICAL:
                    sentiments.append(-0.8)
                elif item.severity == RegulatorySeverity.HIGH:
                    sentiments.append(-0.4)
                elif item.is_enforcement:
                    sentiments.append(-0.6)
                else:
                    sentiments.append(-0.1)
            sentiment = sum(sentiments) / len(sentiments)
        else:
            sentiment = 0.0

        digest = RegulatoryDigest(
            items=items,
            critical_count=critical_count,
            enforcement_count=enforcement_count,
            affected_symbols=sorted(affected_symbols),
            sentiment=round(sentiment, 4),
            timestamp=datetime.now(UTC),
        )

        self._set_cached(cache_key, digest)
        return digest

    async def check_ripple_case(self) -> RegulatoryItem | None:
        """Check for latest Ripple/XRP case developments.

        Returns the most recent Ripple case item, or None if no updates.
        """
        cache_key = "ripple_case"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        try:
            # Search SEC press releases for Ripple mentions
            resp = await client.get(
                "https://www.sec.gov/rss/news/press.xml",
                timeout=10,
            )
            resp.raise_for_status()

            root = ET.fromstring(resp.text)
            channel = root.find("channel")
            if channel is None:
                return None

            for item_elem in channel.findall("item"):
                title = self._get_text(item_elem, "title")
                desc = self._get_text(item_elem, "description")
                combined = f"{title} {desc}".lower()

                if "ripple" in combined or "xrp" in combined:
                    link = self._get_text(item_elem, "link")
                    pub_date = self._get_text(item_elem, "pubDate")

                    result = RegulatoryItem(
                        regulator=Regulator.RIPPLE_CASE,
                        title=title,
                        url=link,
                        severity=RegulatorySeverity.HIGH,
                        summary=desc[:300],
                        affected_assets=("XRP",),
                        published_at=self._parse_date(pub_date),
                        is_enforcement="charges" in combined or "enforcement" in combined,
                    )

                    self._set_cached(cache_key, result)
                    return result

        except Exception as exc:
            logger.debug("Ripple case check failed: %s", exc)

        return None

    # ── Feed Fetching ────────────────────────────────────────────────

    async def _fetch_all_feeds(self) -> list[RegulatoryItem]:
        """Fetch from all regulatory RSS feeds in parallel."""
        import asyncio

        tasks = [
            self._fetch_sec_feed(),
            self._fetch_cftc_feed(),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[RegulatoryItem] = []
        for r in results:
            if isinstance(r, Exception):
                logger.debug("Regulatory feed error: %s", r)
                continue
            all_items.extend(r)

        return all_items

    async def _fetch_sec_feed(self) -> list[RegulatoryItem]:
        """Fetch SEC press releases and litigation releases."""
        client = await self._get_client()
        items: list[RegulatoryItem] = []

        for feed_name, feed_url in [
            ("SEC_PRESS", _FEEDS["SEC_PRESS"]),
            ("SEC_LITIGATION", _FEEDS["SEC_LITIGATION"]),
        ]:
            try:
                resp = await client.get(feed_url, timeout=10)
                resp.raise_for_status()

                root = ET.fromstring(resp.text)
                channel = root.find("channel")
                if channel is None:
                    continue

                for item_elem in channel.findall("item"):
                    parsed = self._parse_rss_item(
                        item_elem,
                        Regulator.SEC,
                        is_litigation="LITIGATION" in feed_name,
                    )
                    if parsed:
                        items.append(parsed)

            except Exception as exc:
                logger.debug("SEC feed %s failed: %s", feed_name, exc)

        return items

    async def _fetch_cftc_feed(self) -> list[RegulatoryItem]:
        """Fetch CFTC enforcement press releases."""
        client = await self._get_client()
        items: list[RegulatoryItem] = []

        try:
            resp = await client.get(_FEEDS["CFTC_ENFORCEMENT"], timeout=10)
            resp.raise_for_status()

            root = ET.fromstring(resp.text)
            channel = root.find("channel")
            if channel is None:
                return items

            for item_elem in channel.findall("item"):
                parsed = self._parse_rss_item(item_elem, Regulator.CFTC)
                if parsed:
                    items.append(parsed)

        except Exception as exc:
            logger.debug("CFTC feed failed: %s", exc)

        return items

    def _parse_rss_item(
        self,
        elem: ET.Element,
        regulator: Regulator,
        is_litigation: bool = False,
    ) -> RegulatoryItem | None:
        """Parse a regulatory RSS item."""
        title = self._get_text(elem, "title")
        if not title:
            return None

        desc = self._get_text(elem, "description")
        link = self._get_text(elem, "link")
        pub_date = self._get_text(elem, "pubDate")

        # Check if crypto-related
        combined = f"{title} {desc}".lower()
        is_crypto = any(kw in combined for kw in _CRYPTO_ENFORCEMENT_KEYWORDS)

        # Classify severity
        severity = self._classify_severity(title, desc, is_litigation, is_crypto)

        # Identify affected assets
        affected = self._identify_affected_assets(combined)

        # Is this an enforcement action?
        is_enforcement = (
            is_litigation
            or any(kw in combined for kw in _CRITICAL_KEYWORDS)
            or "enforcement" in combined
        )

        return RegulatoryItem(
            regulator=regulator,
            title=title,
            url=link,
            severity=severity,
            summary=desc[:300] if desc else "",
            affected_assets=tuple(affected),
            published_at=self._parse_date(pub_date),
            is_enforcement=is_enforcement,
        )

    # ── Classification ───────────────────────────────────────────────

    @staticmethod
    def _classify_severity(
        title: str,
        description: str,
        is_litigation: bool,
        is_crypto: bool,
    ) -> RegulatorySeverity:
        """Classify regulatory item severity."""
        combined = f"{title} {description}".lower()

        if is_litigation and is_crypto:
            return RegulatorySeverity.CRITICAL

        if any(kw in combined for kw in _CRITICAL_KEYWORDS):
            return RegulatorySeverity.CRITICAL if is_crypto else RegulatorySeverity.HIGH

        if any(kw in combined for kw in _HIGH_KEYWORDS):
            return RegulatorySeverity.HIGH

        return RegulatorySeverity.LOW

    @staticmethod
    def _identify_affected_assets(text: str) -> list[str]:
        """Identify crypto assets mentioned in text."""
        asset_patterns = {
            "BTC": r"\b(bitcoin|btc)\b",
            "ETH": r"\b(ethereum|ether|eth)\b",
            "XRP": r"\b(ripple|xrp)\b",
            "SOL": r"\b(solana|sol)\b",
            "BNB": r"\b(binance|bnb)\b",
            "ADA": r"\b(cardano|ada)\b",
            "DOGE": r"\b(dogecoin|doge)\b",
            "USDT": r"\b(tether|usdt)\b",
            "USDC": r"\b(usdc|circle)\b",
        }

        found: list[str] = []
        for symbol, pattern in asset_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                found.append(symbol)

        return found

    @staticmethod
    def _is_relevant(item: RegulatoryItem, symbol: str) -> bool:
        """Check if a regulatory item is relevant to a symbol."""
        if symbol in item.affected_assets:
            return True
        # CRITICAL items are always relevant
        return item.severity == RegulatorySeverity.CRITICAL

    # ── Utilities ────────────────────────────────────────────────────

    @staticmethod
    def _get_text(elem: ET.Element, tag: str) -> str:
        child = elem.find(tag)
        return child.text.strip() if child is not None and child.text else ""

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        for fmt in [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%Y-%m-%dT%H:%M:%S%z",
        ]:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
