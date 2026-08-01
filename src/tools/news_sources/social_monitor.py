"""
TSAR — Social Channel Monitor (Reddit / Discord).

Monitors crypto community channels for sentiment shifts,
breaking news, and early signals:

  Reddit:
    - r/cryptocurrency, r/bitcoin, r/ethereum, r/solana
    - r/wallstreetbets (crypto threads)
    - Uses Reddit JSON API (no auth required for public subreddits)

  Discord:
    - Configurable webhook/channel monitoring
    - Requires bot token or webhook URL in config

Social signals are lower confidence than news feeds but provide
early detection of sentiment shifts and emerging narratives.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


class SocialPlatform(StrEnum):
    """Social platform identifiers."""

    REDDIT = "reddit"
    DISCORD = "discord"


@dataclass(frozen=True)
class SocialPost:
    """A single social media post.

    Attributes:
        platform: Which platform.
        title: Post title (Reddit) or first line (Discord).
        content: Post body/content.
        author: Author username.
        url: Direct link to the post.
        score: Upvotes (Reddit) or reactions (Discord).
        comment_count: Number of comments/replies.
        sentiment: Derived sentiment (-1 to +1).
        relevance: Crypto relevance (0-1).
        mentioned_assets: Crypto assets mentioned.
        published_at: When the post was created.
        subreddit: Reddit subreddit (if from Reddit).
    """

    platform: SocialPlatform
    title: str
    content: str = ""
    author: str = ""
    url: str = ""
    score: int = 0
    comment_count: int = 0
    sentiment: float = 0.0
    relevance: float = 0.0
    mentioned_assets: tuple[str, ...] = ()
    published_at: datetime | None = None
    subreddit: str = ""


@dataclass
class SocialDigest:
    """Aggregated social digest.

    Attributes:
        symbol: Asset symbol queried (or "GENERAL").
        posts: All relevant posts.
        overall_sentiment: Aggregate sentiment (-1 to +1).
        post_count: Total number of posts.
        platform_breakdown: Count of posts per platform.
        top_subreddits: Most active subreddits.
        trending_assets: Most mentioned assets.
        engagement_total: Total engagement (upvotes + comments).
        timestamp: When the digest was compiled.
    """

    symbol: str
    posts: list[SocialPost] = field(default_factory=list)
    overall_sentiment: float = 0.0
    post_count: int = 0
    platform_breakdown: dict[str, int] = field(default_factory=dict)
    top_subreddits: list[str] = field(default_factory=list)
    trending_assets: list[str] = field(default_factory=list)
    engagement_total: int = 0
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

_DEFAULT_SUBREDDITS = [
    "cryptocurrency",
    "bitcoin",
    "ethereum",
    "solana",
    "CryptoMarkets",
]

# Asset patterns for detection
_ASSET_PATTERNS: dict[str, str] = {
    "BTC": r"\b(bitcoin|btc)\b",
    "ETH": r"\b(ethereum|ether|eth)\b",
    "SOL": r"\b(solana|sol)\b",
    "BNB": r"\b(binance|bnb)\b",
    "XRP": r"\b(ripple|xrp)\b",
    "ADA": r"\b(cardano|ada)\b",
    "DOGE": r"\b(dogecoin|doge)\b",
    "DOT": r"\b(polkadot|dot)\b",
    "AVAX": r"\b(avalanche|avax)\b",
    "MATIC": r"\b(polygon|matic)\b",
    "LINK": r"\b(chainlink|link)\b",
    "UNI": r"\b(uniswap|uni)\b",
}

_BULLISH_KEYWORDS = frozenset({
    "bullish", "moon", "pump", "rally", "buy", "accumulate",
    "breakout", "surge", "hodl", "diamond hands", "to the moon",
    "undervalued", "gem", "early", "adoption",
})

_BEARISH_KEYWORDS = frozenset({
    "bearish", "dump", "crash", "sell", "short", "rug",
    "scam", "hack", "exploit", "fear", "panic", "overvalued",
    "bubble", "dead", "exit scam", "ponzi",
})


# ═══════════════════════════════════════════════════════════════════════
# SOCIAL CHANNEL MONITOR
# ═══════════════════════════════════════════════════════════════════════


class SocialChannelMonitor:
    """Monitors Reddit and Discord crypto channels.

    Aggregates posts from configured subreddits and Discord channels,
    computes sentiment and relevance, and identifies trending assets.

    Usage:
        monitor = SocialChannelMonitor()
        digest = await monitor.get_social_digest("BTC")
        print(digest.overall_sentiment, digest.post_count)
    """

    description = (
        "Social monitoring: Reddit crypto subreddits, Discord channels, "
        "community sentiment, trending asset detection"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._discord_webhook = self._config.get("discord_webhook_url", "")
        self._discord_bot_token = self._config.get("discord_bot_token", "")

        # Subreddits to monitor
        self._subreddits = self._config.get("subreddits", _DEFAULT_SUBREDDITS)

        # Cache
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 300)  # 5 min

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={
                    "User-Agent": "TSAR/1.0 (Crypto Social Monitor)",
                },
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

    async def get_social_digest(
        self,
        symbol: str = "GENERAL",
        limit: int = 30,
    ) -> SocialDigest:
        """Get aggregated social media digest.

        Args:
            symbol: Asset symbol to filter by (or "GENERAL" for all).
            limit: Max posts to return.

        Returns:
            SocialDigest with classified posts.
        """
        base_symbol = symbol.split("/")[0].upper() if symbol else "GENERAL"

        cache_key = f"social:{base_symbol}:{limit}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # Fetch from all platforms in parallel
        import asyncio
        tasks = [
            self._fetch_reddit_posts(),
            self._fetch_discord_posts(),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_posts: list[SocialPost] = []
        for r in results:
            if isinstance(r, Exception):
                logger.debug("Social fetch error: %s", r)
                continue
            all_posts.extend(r)

        # Filter by symbol
        if base_symbol and base_symbol != "GENERAL":
            all_posts = [
                p for p in all_posts
                if base_symbol in p.mentioned_assets or p.relevance > 0.7
            ]

        # Sort by score and relevance
        all_posts.sort(
            key=lambda x: (x.score * x.relevance, x.published_at or datetime.min),
            reverse=True,
        )
        all_posts = all_posts[:limit]

        # Build digest
        if all_posts:
            sentiment = sum(p.sentiment for p in all_posts) / len(all_posts)
        else:
            sentiment = 0.0

        # Platform breakdown
        platform_counts: dict[str, int] = {}
        for p in all_posts:
            platform_counts[p.platform.value] = platform_counts.get(p.platform.value, 0) + 1

        # Top subreddits
        subreddit_counts: dict[str, int] = {}
        for p in all_posts:
            if p.subreddit:
                subreddit_counts[p.subreddit] = subreddit_counts.get(p.subreddit, 0) + 1
        top_subs = sorted(subreddit_counts, key=subreddit_counts.get, reverse=True)[:5]

        # Trending assets
        asset_counts: dict[str, int] = {}
        for p in all_posts:
            for asset in p.mentioned_assets:
                asset_counts[asset] = asset_counts.get(asset, 0) + 1
        trending = sorted(asset_counts, key=asset_counts.get, reverse=True)[:10]

        total_engagement = sum(p.score + p.comment_count for p in all_posts)

        digest = SocialDigest(
            symbol=base_symbol,
            posts=all_posts,
            overall_sentiment=round(sentiment, 4),
            post_count=len(all_posts),
            platform_breakdown=platform_counts,
            top_subreddits=top_subs,
            trending_assets=trending,
            engagement_total=total_engagement,
            timestamp=datetime.now(UTC),
        )

        self._set_cached(cache_key, digest)
        return digest

    async def get_trending_assets(self) -> list[tuple[str, int, float]]:
        """Get trending assets from social channels.

        Returns:
            List of (asset_symbol, mention_count, avg_sentiment) tuples.
        """
        digest = await self.get_social_digest(symbol="GENERAL", limit=100)

        asset_data: dict[str, list[float]] = {}
        for post in digest.posts:
            for asset in post.mentioned_assets:
                if asset not in asset_data:
                    asset_data[asset] = []
                asset_data[asset].append(post.sentiment)

        trending = []
        for asset, sentiments in asset_data.items():
            count = len(sentiments)
            avg_sent = sum(sentiments) / count if count > 0 else 0.0
            trending.append((asset, count, round(avg_sent, 4)))

        trending.sort(key=lambda x: x[1], reverse=True)
        return trending[:20]

    # ── Reddit Fetching ──────────────────────────────────────────────

    async def _fetch_reddit_posts(self) -> list[SocialPost]:
        """Fetch posts from Reddit crypto subreddits."""
        import asyncio

        tasks = [
            self._fetch_subreddit(sub)
            for sub in self._subreddits
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_posts: list[SocialPost] = []
        for r in results:
            if isinstance(r, Exception):
                logger.debug("Reddit fetch error: %s", r)
                continue
            all_posts.extend(r)

        return all_posts

    async def _fetch_subreddit(self, subreddit: str) -> list[SocialPost]:
        """Fetch hot posts from a single subreddit."""
        client = await self._get_client()
        posts: list[SocialPost] = []

        try:
            # Reddit JSON API — no auth required for public subreddits
            url = f"https://www.reddit.com/r/{subreddit}/hot.json"
            resp = await client.get(
                url,
                params={"limit": 25, "raw_json": 1},
                headers={"User-Agent": "TSAR/1.0"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            for child in data.get("data", {}).get("children", []):
                post_data = child.get("data", {})
                post = self._parse_reddit_post(post_data, subreddit)
                if post:
                    posts.append(post)

        except Exception as exc:
            logger.debug("Reddit r/%s fetch failed: %s", subreddit, exc)

        return posts

    def _parse_reddit_post(self, data: dict[str, Any], subreddit: str) -> SocialPost | None:
        """Parse a Reddit post JSON into a SocialPost."""
        title = data.get("title", "")
        selftext = data.get("selftext", "")

        if not title:
            return None

        # Combine title and body for analysis
        full_text = f"{title} {selftext}"

        # Check relevance
        relevance = self._compute_relevance(full_text)
        if relevance < 0.2:
            return None

        # Sentiment
        sentiment = self._analyze_sentiment(full_text)

        # Assets
        assets = self._extract_assets(full_text)

        # Score (upvotes - downvotes)
        score = data.get("score", 0)
        comments = data.get("num_comments", 0)

        # Author
        author = data.get("author", "unknown")

        # URL
        permalink = data.get("permalink", "")
        url = f"https://reddit.com{permalink}" if permalink else ""

        # Timestamp
        created_utc = data.get("created_utc")
        pub_dt = None
        if created_utc:
            try:
                pub_dt = datetime.fromtimestamp(float(created_utc), tz=UTC)
            except (ValueError, TypeError, OSError):
                pass

        return SocialPost(
            platform=SocialPlatform.REDDIT,
            title=title[:300],
            content=selftext[:500],
            author=author,
            url=url,
            score=score,
            comment_count=comments,
            sentiment=round(sentiment, 4),
            relevance=round(relevance, 4),
            mentioned_assets=tuple(assets),
            published_at=pub_dt,
            subreddit=subreddit,
        )

    # ── Discord Fetching ─────────────────────────────────────────────

    async def _fetch_discord_posts(self) -> list[SocialPost]:
        """Fetch posts from configured Discord channels.

        Requires either:
        - discord_bot_token: For bot-based channel access
        - discord_webhook_url: For webhook-based monitoring (read-only)
        """
        if not self._discord_bot_token and not self._discord_webhook:
            return []

        # Placeholder for Discord integration
        # In production, this would use the Discord API or webhook
        logger.debug("Discord fetching not yet configured")
        return []

    # ── Text Analysis ────────────────────────────────────────────────

    @staticmethod
    def _compute_relevance(text: str) -> float:
        """Compute crypto relevance of a social post."""
        text_lower = text.lower()

        crypto_keywords = [
            "crypto", "bitcoin", "ethereum", "blockchain", "defi",
            "token", "coin", "binance", "web3", "nft", "altcoin",
            "hodl", "mining", "staking", "wallet", "exchange",
        ]

        hits = sum(1 for kw in crypto_keywords if kw in text_lower)
        if hits >= 3:
            return 0.9
        elif hits >= 2:
            return 0.7
        elif hits >= 1:
            return 0.5

        # Check for asset mentions
        for pattern in _ASSET_PATTERNS.values():
            if re.search(pattern, text_lower):
                return 0.6

        return 0.1

    @staticmethod
    def _analyze_sentiment(text: str) -> float:
        """Analyze sentiment of social post."""
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

        return found
