"""
TSAR Domain Tools — News Aggregator.

Aggregates crypto news from multiple sources with sentiment scoring
and relevance filtering.

Data Sources:
  - CryptoPanic API (free tier: public posts, votes-based sentiment)
  - CoinDesk RSS feed
  - CoinTelegraph RSS feed
  - Decrypt RSS feed (supplementary)

All tools are async with caching and graceful degradation.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class NewsItem:
    """A single news item from any source.

    Attributes:
        title: News headline.
        source: News source (e.g. "CryptoPanic", "CoinDesk").
        url: Link to the full article.
        sentiment: Article sentiment (-1 to +1).
            Derived from CryptoPanic votes or keyword analysis.
        relevance: Relevance to the queried asset (0-1).
        published_at: When the article was published.
        categories: Article categories/tags.
        summary: Brief article summary (if available).
        is_breaking: Whether this is breaking news.
    """

    title: str
    source: str
    url: str = ""
    sentiment: float = 0.0
    relevance: float = 0.0
    published_at: datetime | None = None
    categories: tuple[str, ...] = ()
    summary: str = ""
    is_breaking: bool = False


@dataclass(frozen=True)
class NewsDigest:
    """Aggregated news digest from all sources.

    Attributes:
        symbol: Asset symbol (or "GENERAL" for market-wide news).
        items: All news items, sorted by relevance and recency.
        overall_sentiment: Aggregate sentiment across all items (-1 to +1).
        item_count: Total number of items.
        high_impact_count: Number of high-impact items (relevance > 0.7).
        breaking_count: Number of breaking news items.
        source_breakdown: Count of items per source.
        sentiment_by_source: Average sentiment per source.
        top_categories: Most frequent categories across items.
        timestamp: When the digest was compiled.
    """

    symbol: str
    items: tuple[NewsItem, ...]
    overall_sentiment: float
    item_count: int = 0
    high_impact_count: int = 0
    breaking_count: int = 0
    source_breakdown: dict[str, int] = field(default_factory=dict)
    sentiment_by_source: dict[str, float] = field(default_factory=dict)
    top_categories: tuple[str, ...] = ()
    timestamp: datetime | None = None


@dataclass(frozen=True)
class NewsSignal:
    """Trading signal derived from news analysis.

    Attributes:
        symbol: Asset symbol.
        signal: "bullish", "bearish", or "neutral".
        confidence: Signal confidence (0-1).
        reasoning: Human-readable explanation.
        supporting_articles: Number of articles supporting the signal.
        contradicting_articles: Number of articles contradicting.
        key_events: Key events driving the signal.
    """

    symbol: str
    signal: str
    confidence: float
    reasoning: str
    supporting_articles: int = 0
    contradicting_articles: int = 0
    key_events: tuple[str, ...] = ()


# ═══════════════════════════════════════════════════════════════════════
# NEWS SOURCE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

_RSS_FEEDS: dict[str, str] = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
}

_HIGH_IMPACT_KEYWORDS = frozenset({
    "sec", "etf", "regulation", "fed", "interest rate", "cpi",
    "hack", "exploit", "vulnerability", "bankruptcy", "insolvency",
    "partnership", "launch", "mainnet", "upgrade", "halving",
    "whale", "institutional", "adoption", "ban", "approval",
})


# ═══════════════════════════════════════════════════════════════════════
# NEWS AGGREGATOR TOOLS
# ═══════════════════════════════════════════════════════════════════════


class NewsAggregator:
    """Crypto news aggregation and analysis tools.

    Fetches news from CryptoPanic (votes-based), CoinDesk RSS,
    CoinTelegraph RSS, and Decrypt RSS. Provides sentiment scoring,
    relevance filtering, and trading signal derivation.
    """

    description = (
        "News aggregation: CryptoPanic, CoinDesk, CoinTelegraph, "
        "RSS feeds, sentiment scoring, news signals"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None

        # Cache
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 180)  # 3 min for news

        # API keys
        self._cryptopanic_key = self._config.get("cryptopanic_api_key", "")

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

    # ── News Digest ──────────────────────────────────────────────────

    async def get_news_digest(
        self,
        symbol: str,
        limit: int = 30,
        min_relevance: float = 0.3,
    ) -> NewsDigest:
        """Get aggregated news digest for a cryptocurrency.

        Fetches from all configured sources in parallel, scores
        sentiment and relevance, and filters by minimum relevance.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").
            limit: Maximum number of news items to return.
            min_relevance: Minimum relevance score to include (0-1).

        Returns:
            NewsDigest with filtered and scored news items.
        """
        cache_key = f"news:{symbol}:{limit}:{min_relevance}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base_symbol = symbol.split("/")[0].upper()

        # Fetch from all sources in parallel
        tasks = [
            self._fetch_cryptopanic_news(base_symbol, limit),
            self._fetch_rss_news("CoinDesk", base_symbol, limit),
            self._fetch_rss_news("CoinTelegraph", base_symbol, limit),
            self._fetch_rss_news("Decrypt", base_symbol, limit),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Combine all items
        all_items: list[NewsItem] = []
        for r in results:
            if isinstance(r, Exception):
                logger.debug("News fetch error: %s", r)
                continue
            all_items.extend(r)

        # Filter by relevance
        filtered = [item for item in all_items if item.relevance >= min_relevance]

        # Sort by relevance and recency
        filtered.sort(key=lambda x: (x.relevance, x.published_at or datetime.min), reverse=True)

        # Apply limit
        items = tuple(filtered[:limit])

        # Compute aggregates
        overall_sentiment = (
            sum(i.sentiment for i in items) / len(items) if items else 0.0
        )
        high_impact = sum(1 for i in items if i.relevance > 0.7)
        breaking = sum(1 for i in items if i.is_breaking)

        # Source breakdown
        source_counts: dict[str, int] = {}
        source_sentiments: dict[str, list[float]] = {}
        for item in items:
            source_counts[item.source] = source_counts.get(item.source, 0) + 1
            if item.source not in source_sentiments:
                source_sentiments[item.source] = []
            source_sentiments[item.source].append(item.sentiment)

        sentiment_by_source = {
            src: round(sum(s) / len(s), 4)
            for src, s in source_sentiments.items()
            if s
        }

        # Top categories
        category_counts: dict[str, int] = {}
        for item in items:
            for cat in item.categories:
                category_counts[cat] = category_counts.get(cat, 0) + 1
        top_cats = sorted(category_counts, key=category_counts.get, reverse=True)[:5]

        result = NewsDigest(
            symbol=base_symbol,
            items=items,
            overall_sentiment=round(overall_sentiment, 4),
            item_count=len(items),
            high_impact_count=high_impact,
            breaking_count=breaking,
            source_breakdown=source_counts,
            sentiment_by_source=sentiment_by_source,
            top_categories=tuple(top_cats),
            timestamp=datetime.now(UTC),
        )

        self._set_cached(cache_key, result)
        return result

    # ── News-Based Trading Signal ────────────────────────────────────

    async def get_news_signal(self, symbol: str) -> NewsSignal:
        """Derive a trading signal from news analysis.

        Analyzes the news digest to generate a directional signal
        based on sentiment, volume, and impact of recent news.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            NewsSignal with direction, confidence, and reasoning.
        """
        digest = await self.get_news_digest(symbol, limit=20)

        if digest.item_count == 0:
            return NewsSignal(
                symbol=symbol,
                signal="neutral",
                confidence=0.0,
                reasoning="No recent news available",
            )

        base_symbol = symbol.split("/")[0].upper()

        # Count supporting/contradicting articles
        bullish_count = sum(1 for i in digest.items if i.sentiment > 0.1)
        bearish_count = sum(1 for i in digest.items if i.sentiment < -0.1)
        neutral_count = digest.item_count - bullish_count - bearish_count

        # Signal direction
        if bullish_count > bearish_count * 1.5:
            signal = "bullish"
        elif bearish_count > bullish_count * 1.5:
            signal = "bearish"
        else:
            signal = "neutral"

        # Confidence based on agreement and impact
        agreement_ratio = max(bullish_count, bearish_count) / digest.item_count
        impact_boost = digest.high_impact_count / max(digest.item_count, 1)
        confidence = min(1.0, agreement_ratio * 0.6 + impact_boost * 0.4)

        # Key events from high-impact articles
        key_events = tuple(
            item.title for item in digest.items
            if item.relevance > 0.7
        )[:5]

        # Reasoning
        if signal == "bullish":
            reasoning = (
                f"{bullish_count}/{digest.item_count} articles bullish. "
                f"Sentiment: {digest.overall_sentiment:.2f}. "
                f"{digest.high_impact_count} high-impact articles."
            )
        elif signal == "bearish":
            reasoning = (
                f"{bearish_count}/{digest.item_count} articles bearish. "
                f"Sentiment: {digest.overall_sentiment:.2f}. "
                f"{digest.high_impact_count} high-impact articles."
            )
        else:
            reasoning = (
                f"Mixed signals: {bullish_count} bullish, {bearish_count} bearish, "
                f"{neutral_count} neutral out of {digest.item_count} articles."
            )

        return NewsSignal(
            symbol=base_symbol,
            signal=signal,
            confidence=round(confidence, 4),
            reasoning=reasoning,
            supporting_articles=bullish_count if signal == "bullish" else bearish_count,
            contradicting_articles=bearish_count if signal == "bullish" else bullish_count,
            key_events=key_events,
        )

    # ── Market-Wide News ─────────────────────────────────────────────

    async def get_market_news(
        self,
        limit: int = 20,
    ) -> NewsDigest:
        """Get market-wide crypto news (not asset-specific).

        Fetches general crypto market news from all sources.

        Args:
            limit: Maximum number of items.

        Returns:
            NewsDigest with general market news.
        """
        cache_key = f"market_news:{limit}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # Fetch from RSS feeds (CryptoPanic without currency filter)
        tasks = [
            self._fetch_cryptopanic_news("", limit),
            self._fetch_rss_news("CoinDesk", "", limit),
            self._fetch_rss_news("CoinTelegraph", "", limit),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[NewsItem] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            all_items.extend(r)

        # Sort by recency
        all_items.sort(
            key=lambda x: x.published_at or datetime.min,
            reverse=True,
        )
        items = tuple(all_items[:limit])

        overall = sum(i.sentiment for i in items) / len(items) if items else 0.0

        result = NewsDigest(
            symbol="GENERAL",
            items=items,
            overall_sentiment=round(overall, 4),
            item_count=len(items),
            timestamp=datetime.now(UTC),
        )

        self._set_cached(cache_key, result)
        return result

    # ── CryptoPanic API ──────────────────────────────────────────────

    async def _fetch_cryptopanic_news(
        self,
        symbol: str,
        limit: int,
    ) -> list[NewsItem]:
        """Fetch news from CryptoPanic API."""
        client = await self._get_client()
        items: list[NewsItem] = []

        try:
            params: dict[str, str] = {
                "kind": "news",
                "filter": "important",
                "public": "true",
            }
            if symbol:
                params["currencies"] = symbol
            if self._cryptopanic_key:
                params["auth_token"] = self._cryptopanic_key

            resp = await client.get(
                "https://cryptopanic.com/api/v1/posts/",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            for post in data.get("results", [])[:limit]:
                votes = post.get("votes", {})
                pos = votes.get("positive", 0)
                neg = votes.get("negative", 0)
                total = pos + neg
                sentiment = (pos - neg) / total if total > 0 else 0.0

                published = post.get("published_at", "")
                pub_dt = None
                if published:
                    try:
                        pub_dt = datetime.fromisoformat(
                            published.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        pass

                # Determine relevance
                kind = post.get("kind", "")
                is_important = "important" in kind
                relevance = 0.8 if is_important else 0.5

                # Check for high-impact keywords
                title = post.get("title", "").lower()
                if any(kw in title for kw in _HIGH_IMPACT_KEYWORDS):
                    relevance = min(1.0, relevance + 0.2)

                # Categories from tags
                categories = tuple(
                    tag.get("title", "")
                    for tag in post.get("tags", [])
                    if tag.get("title")
                )

                items.append(NewsItem(
                    title=post.get("title", ""),
                    source=post.get("source", {}).get("title", "CryptoPanic"),
                    url=post.get("url", ""),
                    sentiment=round(sentiment, 4),
                    relevance=relevance,
                    published_at=pub_dt,
                    categories=categories,
                    is_breaking=is_important and sentiment != 0,
                ))

        except Exception as exc:
            logger.debug("CryptoPanic fetch failed: %s", exc)

        return items

    # ── RSS Feed Parsing ─────────────────────────────────────────────

    async def _fetch_rss_news(
        self,
        source: str,
        symbol: str,
        limit: int,
    ) -> list[NewsItem]:
        """Fetch and parse news from an RSS feed."""
        url = _RSS_FEEDS.get(source)
        if not url:
            return []

        client = await self._get_client()
        items: list[NewsItem] = []

        try:
            resp = await client.get(url, timeout=10)
            resp.raise_for_status()

            # Parse RSS XML
            root = ET.fromstring(resp.text)

            # Handle both RSS 2.0 and Atom formats
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # RSS 2.0
            channel = root.find("channel")
            if channel is not None:
                for item_elem in channel.findall("item")[:limit * 2]:
                    item = self._parse_rss_item(item_elem, source, symbol)
                    if item:
                        items.append(item)
            else:
                # Atom feed
                for entry in root.findall("atom:entry", ns)[:limit * 2]:
                    item = self._parse_atom_entry(entry, source, symbol, ns)
                    if item:
                        items.append(item)

            # Filter by relevance if symbol specified
            if symbol:
                items = [i for i in items if i.relevance > 0.2]

            return items[:limit]

        except Exception as exc:
            logger.debug("RSS fetch failed for %s: %s", source, exc)
            return []

    def _parse_rss_item(
        self,
        elem: ET.Element,
        source: str,
        symbol: str,
    ) -> NewsItem | None:
        """Parse an RSS 2.0 item element."""
        title = self._get_text(elem, "title")
        if not title:
            return None

        link = self._get_text(elem, "link")
        description = self._get_text(elem, "description")
        pub_date = self._get_text(elem, "pubDate")

        # Parse categories
        categories = tuple(
            cat.text for cat in elem.findall("category") if cat.text
        )

        # Compute relevance to symbol
        relevance = self._compute_relevance(title, description, symbol)

        # Sentiment from keywords
        sentiment = self._analyze_headline_sentiment(title)

        # Parse date
        pub_dt = self._parse_rss_date(pub_date)

        return NewsItem(
            title=title,
            source=source,
            url=link or "",
            sentiment=round(sentiment, 4),
            relevance=round(relevance, 4),
            published_at=pub_dt,
            categories=categories,
            summary=self._strip_html(description)[:200] if description else "",
        )

    def _parse_atom_entry(
        self,
        elem: ET.Element,
        source: str,
        symbol: str,
        ns: dict[str, str],
    ) -> NewsItem | None:
        """Parse an Atom entry element."""
        title_elem = elem.find("atom:title", ns)
        title = title_elem.text if title_elem is not None and title_elem.text else ""
        if not title:
            return None

        link_elem = elem.find("atom:link", ns)
        link = link_elem.get("href", "") if link_elem is not None else ""

        summary_elem = elem.find("atom:summary", ns)
        summary = summary_elem.text if summary_elem is not None and summary_elem.text else ""

        published_elem = elem.find("atom:published", ns)
        pub_str = published_elem.text if published_elem is not None else ""

        relevance = self._compute_relevance(title, summary, symbol)
        sentiment = self._analyze_headline_sentiment(title)
        pub_dt = self._parse_iso_date(pub_str)

        return NewsItem(
            title=title,
            source=source,
            url=link,
            sentiment=round(sentiment, 4),
            relevance=round(relevance, 4),
            published_at=pub_dt,
            summary=self._strip_html(summary)[:200] if summary else "",
        )

    # ── Utility Methods ──────────────────────────────────────────────

    @staticmethod
    def _compute_relevance(title: str, description: str | None, symbol: str) -> float:
        """Compute relevance score of a news item to a symbol."""
        if not symbol:
            return 0.5  # General news

        text = f"{title} {description or ''}".lower()
        symbol_lower = symbol.lower()

        # Direct mention
        if symbol_lower in text:
            return 0.9

        # Common aliases
        aliases = {
            "btc": ["bitcoin", "sats", "satoshi"],
            "eth": ["ethereum", "ether", "vitalik"],
            "sol": ["solana"],
            "bnb": ["binance"],
            "xrp": ["ripple"],
            "ada": ["cardano"],
            "doge": ["dogecoin", "doge"],
            "dot": ["polkadot"],
            "avax": ["avalanche"],
            "matic": ["polygon"],
            "link": ["chainlink"],
            "uni": ["uniswap"],
        }

        for alias in aliases.get(symbol_lower, []):
            if alias in text:
                return 0.8

        # General crypto keywords (lower relevance)
        crypto_keywords = ["crypto", "blockchain", "defi", "web3", "token"]
        if any(kw in text for kw in crypto_keywords):
            return 0.3

        return 0.1

    @staticmethod
    def _analyze_headline_sentiment(title: str) -> float:
        """Simple keyword-based sentiment analysis for headlines."""
        title_lower = title.lower()

        bullish_words = {
            "surge", "rally", "bullish", "rise", "gain", "jump", "soar",
            "breakout", "record", "high", "adoption", "partnership",
            "approval", "launch", "upgrade", "milestone", "growth",
        }
        bearish_words = {
            "crash", "drop", "fall", "bearish", "plunge", "decline",
            "hack", "exploit", "ban", "regulation", "lawsuit", "fraud",
            "bankruptcy", "sell-off", "dump", "fear", "concern",
        }

        bullish_hits = sum(1 for w in bullish_words if w in title_lower)
        bearish_hits = sum(1 for w in bearish_words if w in title_lower)

        total = bullish_hits + bearish_hits
        if total == 0:
            return 0.0

        return (bullish_hits - bearish_hits) / total

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags from text."""
        return re.sub(r'<[^>]+>', '', text).strip()

    @staticmethod
    def _get_text(elem: ET.Element, tag: str) -> str:
        """Get text content of a child element."""
        child = elem.find(tag)
        return child.text.strip() if child is not None and child.text else ""

    @staticmethod
    def _parse_rss_date(date_str: str) -> datetime | None:
        """Parse RSS date format (RFC 2822)."""
        if not date_str:
            return None
        try:
            # Handle common RSS date formats
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z",
            ]:
                try:
                    return datetime.strptime(date_str.strip(), fmt)
                except ValueError:
                    continue
            # Last resort: try ISO format
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_iso_date(date_str: str) -> datetime | None:
        """Parse ISO 8601 date string."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
