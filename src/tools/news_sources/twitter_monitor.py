"""
TSAR — Twitter/X Crypto News Monitor.

Monitors crypto-focused Twitter/X accounts for breaking news,
market commentary, and signal-rich tweets.

Uses Nitter (privacy-respecting Twitter frontend) as primary source
with Twitter API v2 as fallback.

Key accounts monitored:
  - @whale_alert — Large transactions
  - @PeckShieldAlert — Security alerts
  - @zaborowski — Market analysis
  - @CoinDesk — Breaking news
  - @WatcherGuru — Market alerts
  - @Bitcoin — Official Bitcoin account
"""

from __future__ import annotations

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
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Tweet:
    """A parsed crypto-relevant tweet.

    Attributes:
        author: Twitter handle of the author.
        text: Tweet text content.
        url: Direct link to the tweet.
        published_at: When the tweet was posted.
        sentiment: Derived sentiment (-1 to +1).
        relevance: Relevance to crypto market (0-1).
        mentioned_assets: Crypto assets mentioned.
        is_retweet: Whether this is a retweet.
        engagement_score: Approximate engagement (likes + retweets).
    """

    author: str
    text: str
    url: str = ""
    published_at: datetime | None = None
    sentiment: float = 0.0
    relevance: float = 0.0
    mentioned_assets: tuple[str, ...] = ()
    is_retweet: bool = False
    engagement_score: int = 0


@dataclass
class TwitterDigest:
    """Aggregated Twitter digest.

    Attributes:
        symbol: Asset symbol queried (or "GENERAL").
        tweets: All relevant tweets.
        overall_sentiment: Aggregate sentiment (-1 to +1).
        tweet_count: Total number of tweets.
        top_authors: Most active authors.
        mentioned_assets: All assets mentioned across tweets.
        timestamp: When the digest was compiled.
    """

    symbol: str
    tweets: list[Tweet] = field(default_factory=list)
    overall_sentiment: float = 0.0
    tweet_count: int = 0
    top_authors: list[str] = field(default_factory=list)
    mentioned_assets: list[str] = field(default_factory=list)
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

_NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
]

# Crypto-focused Twitter accounts to monitor
_DEFAULT_MONITORED_ACCOUNTS = [
    "whale_alert",
    "PeckShieldAlert",
    "CertiKAlert",
    "WatcherGuru",
    "CoinDesk",
    "Bitcoin",
    "ethereum",
    "Solana",
    "VitalikButerin",
    "CZ_binance",
]

# Known crypto asset patterns
_ASSET_PATTERNS: dict[str, str] = {
    "BTC": r"\b(bitcoin|btc|#btc)\b",
    "ETH": r"\b(ethereum|ether|eth|#eth)\b",
    "SOL": r"\b(solana|sol|#sol)\b",
    "BNB": r"\b(binance|bnb|#bnb)\b",
    "XRP": r"\b(ripple|xrp|#xrp)\b",
    "ADA": r"\b(cardano|ada|#ada)\b",
    "DOGE": r"\b(dogecoin|doge|#doge)\b",
    "DOT": r"\b(polkadot|dot|#dot)\b",
    "AVAX": r"\b(avalanche|avax|#avax)\b",
    "MATIC": r"\b(polygon|matic|#matic)\b",
    "LINK": r"\b(chainlink|link|#link)\b",
    "UNI": r"\b(uniswap|uni|#uni)\b",
    "AAVE": r"\b(aave)\b",
}

# Sentiment keywords
_BULLISH_KEYWORDS = frozenset({
    "bullish", "pump", "moon", "rally", "breakout", "surge",
    "accumulate", "buy", "long", "uptrend", "adoption", "partnership",
    "upgrade", "launch", "milestone", "all-time high", "ath",
})

_BEARISH_KEYWORDS = frozenset({
    "bearish", "dump", "crash", "sell", "short", "downtrend",
    "hack", "exploit", "ban", "regulation", "fear", "panic",
    "rug", "scam", "bankruptcy", "liquidation", "correction",
})


# ═══════════════════════════════════════════════════════════════════════
# TWITTER MONITOR
# ═══════════════════════════════════════════════════════════════════════


class TwitterCryptoMonitor:
    """Monitors crypto Twitter/X for breaking news and sentiment.

    Uses Nitter RSS feeds as primary source (no API key required),
    with Twitter API v2 as optional fallback.

    Usage:
        monitor = TwitterCryptoMonitor()
        digest = await monitor.get_twitter_digest("BTC")
        print(digest.overall_sentiment, digest.tweet_count)
    """

    description = (
        "Twitter/X crypto monitoring: breaking news, whale alerts, "
        "security alerts, sentiment from key crypto accounts"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._twitter_bearer = self._config.get("twitter_bearer_token", "")

        # Accounts to monitor
        self._accounts = self._config.get(
            "twitter_accounts",
            _DEFAULT_MONITORED_ACCOUNTS,
        )

        # Cache
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 180)  # 3 min

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={"User-Agent": "TSAR/1.0 (Twitter Monitor)"},
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

    async def get_twitter_digest(
        self,
        symbol: str = "GENERAL",
        limit: int = 30,
    ) -> TwitterDigest:
        """Get aggregated Twitter digest.

        Args:
            symbol: Asset symbol to filter by (or "GENERAL" for all).
            limit: Max tweets to return.

        Returns:
            TwitterDigest with classified tweets.
        """
        base_symbol = symbol.split("/")[0].upper() if symbol else "GENERAL"

        cache_key = f"twitter:{base_symbol}:{limit}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # Fetch tweets from Nitter feeds
        tweets = await self._fetch_nitter_tweets()

        # Filter by symbol
        if base_symbol and base_symbol != "GENERAL":
            tweets = [
                t for t in tweets
                if base_symbol in t.mentioned_assets or self._is_relevant_tweet(t, base_symbol)
            ]

        # Sort by relevance and recency
        tweets.sort(
            key=lambda x: (x.relevance, x.published_at or datetime.min),
            reverse=True,
        )
        tweets = tweets[:limit]

        # Compute aggregates
        if tweets:
            sentiment = sum(t.sentiment for t in tweets) / len(tweets)
        else:
            sentiment = 0.0

        # Top authors
        author_counts: dict[str, int] = {}
        for t in tweets:
            author_counts[t.author] = author_counts.get(t.author, 0) + 1
        top_authors = sorted(author_counts, key=author_counts.get, reverse=True)[:5]

        # All mentioned assets
        all_assets: set[str] = set()
        for t in tweets:
            all_assets.update(t.mentioned_assets)

        digest = TwitterDigest(
            symbol=base_symbol,
            tweets=tweets,
            overall_sentiment=round(sentiment, 4),
            tweet_count=len(tweets),
            top_authors=top_authors,
            mentioned_assets=sorted(all_assets),
            timestamp=datetime.now(UTC),
        )

        self._set_cached(cache_key, digest)
        return digest

    async def get_breaking_tweets(self, limit: int = 10) -> list[Tweet]:
        """Get the most recent breaking/relevant tweets.

        Args:
            limit: Max tweets to return.

        Returns:
            List of high-relevance recent tweets.
        """
        digest = await self.get_twitter_digest(symbol="GENERAL", limit=50)

        # Filter for breaking/high-impact
        breaking = [
            t for t in digest.tweets
            if t.relevance > 0.7 or abs(t.sentiment) > 0.5
        ]

        return breaking[:limit]

    # ── Nitter Fetching ──────────────────────────────────────────────

    async def _fetch_nitter_tweets(self) -> list[Tweet]:
        """Fetch tweets from all monitored accounts via Nitter."""
        import asyncio

        tasks = [
            self._fetch_account_nitter(account)
            for account in self._accounts
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_tweets: list[Tweet] = []
        for r in results:
            if isinstance(r, Exception):
                logger.debug("Nitter fetch error: %s", r)
                continue
            all_tweets.extend(r)

        return all_tweets

    async def _fetch_account_nitter(self, account: str) -> list[Tweet]:
        """Fetch recent tweets from a single account via Nitter RSS."""
        client = await self._get_client()

        for nitter_base in _NITTER_INSTANCES:
            try:
                url = f"{nitter_base}/{account}/rss"
                resp = await client.get(url, timeout=10)
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.text)
                channel = root.find("channel")
                if channel is None:
                    continue

                tweets: list[Tweet] = []
                for item_elem in channel.findall("item"):
                    tweet = self._parse_tweet_item(item_elem, account)
                    if tweet:
                        tweets.append(tweet)

                if tweets:
                    return tweets

            except Exception as exc:
                logger.debug("Nitter %s@%s failed: %s", account, nitter_base, exc)
                continue

        return []

    def _parse_tweet_item(self, elem: ET.Element, author: str) -> Tweet | None:
        """Parse a Nitter RSS item into a Tweet."""
        title = self._get_text(elem, "title")
        if not title:
            return None

        link = self._get_text(elem, "link")
        pub_date = self._get_text(elem, "pubDate")
        description = self._get_text(elem, "description")

        # Clean the text
        text = self._clean_tweet_text(title)

        # Check crypto relevance
        relevance = self._compute_relevance(text)
        if relevance < 0.2:
            return None

        # Sentiment
        sentiment = self._analyze_sentiment(text)

        # Mentioned assets
        assets = self._extract_assets(text)

        # Parse date
        pub_dt = self._parse_date(pub_date)

        return Tweet(
            author=author,
            text=text[:500],
            url=link,
            published_at=pub_dt,
            sentiment=round(sentiment, 4),
            relevance=round(relevance, 4),
            mentioned_assets=tuple(assets),
            is_retweet=text.startswith("RT @"),
        )

    # ── Text Analysis ────────────────────────────────────────────────

    @staticmethod
    def _clean_tweet_text(text: str) -> str:
        """Clean tweet text for analysis."""
        # Remove HTML
        text = re.sub(r'<[^>]+>', '', text)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def _compute_relevance(text: str) -> float:
        """Compute crypto relevance of a tweet."""
        text_lower = text.lower()

        # Direct crypto keywords
        crypto_keywords = [
            "crypto", "bitcoin", "ethereum", "blockchain", "defi",
            "token", "coin", "binance", "coinbase", "web3", "nft",
        ]

        hits = sum(1 for kw in crypto_keywords if kw in text_lower)
        if hits >= 3:
            return 0.9
        elif hits >= 2:
            return 0.7
        elif hits >= 1:
            return 0.5

        # Check for asset symbols
        for pattern in _ASSET_PATTERNS.values():
            if re.search(pattern, text_lower):
                return 0.6

        # Check for $-prefixed tokens
        if re.search(r'\$[A-Z]{2,6}\b', text):
            return 0.5

        return 0.1

    @staticmethod
    def _analyze_sentiment(text: str) -> float:
        """Analyze tweet sentiment."""
        text_lower = text.lower()

        bullish = sum(1 for kw in _BULLISH_KEYWORDS if kw in text_lower)
        bearish = sum(1 for kw in _BEARISH_KEYWORDS if kw in text_lower)

        total = bullish + bearish
        if total == 0:
            return 0.0

        return (bullish - bearish) / total

    @staticmethod
    def _extract_assets(text: str) -> list[str]:
        """Extract mentioned crypto assets."""
        text_lower = text.lower()
        found: list[str] = []

        for symbol, pattern in _ASSET_PATTERNS.items():
            if re.search(pattern, text_lower):
                found.append(symbol)

        # Also check $SYMBOL patterns
        dollar_tokens = re.findall(r'\$([A-Z]{2,6})\b', text)
        for token in dollar_tokens:
            if token not in found:
                found.append(token)

        return found

    @staticmethod
    def _is_relevant_tweet(tweet: Tweet, symbol: str) -> bool:
        """Check if a tweet is relevant to a specific symbol."""
        if symbol in tweet.mentioned_assets:
            return True
        if tweet.relevance > 0.7:
            return True
        return False

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
        ]:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
