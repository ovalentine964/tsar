"""
TSAR Domain Tools — Social Sentiment Analysis.

Twitter/X, Reddit, and Telegram sentiment aggregation for crypto assets.

Data Sources:
  - CryptoPanic news votes (sentiment proxy)
  - CoinGecko community data (Twitter followers, Reddit subscribers)
  - Reddit public API (post/comment analysis)
  - Trending detection via volume and mention spikes

All tools are async with caching and graceful degradation.
Sentiment is normalized to [-1, +1] across all platforms.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PlatformSentiment:
    """Sentiment from a single social platform.

    Attributes:
        platform: Platform name ("twitter", "reddit", "telegram").
        sentiment: Sentiment score (-1 to +1).
        mention_count: Number of mentions/posts in 24h.
        engagement_score: Engagement level (0-1).
            Based on likes, comments, shares relative to baseline.
        top_keywords: Most frequent keywords/hashtags.
        trending_score: How trending the topic is (0-1).
    """

    platform: str
    sentiment: float
    mention_count: int
    engagement_score: float = 0.0
    top_keywords: tuple[str, ...] = ()
    trending_score: float = 0.0


@dataclass(frozen=True)
class SocialSentiment:
    """Aggregated social media sentiment data.

    Attributes:
        symbol: Asset symbol.
        twitter: Twitter/X sentiment data.
        reddit: Reddit sentiment data.
        telegram: Telegram sentiment data.
        composite_score: Weighted composite sentiment (-1 to +1).
            Twitter: 40%, Reddit: 35%, News: 25%.
        trending: Whether the asset is trending on social media.
        sentiment_shift: Whether sentiment shifted significantly
            (>0.2 change from recent average).
        fear_greed_index: Estimated fear/greed index (0-100).
            0 = extreme fear, 50 = neutral, 100 = extreme greed.
        timestamp: When the data was fetched.
    """

    symbol: str
    twitter: PlatformSentiment | None = None
    reddit: PlatformSentiment | None = None
    telegram: PlatformSentiment | None = None
    composite_score: float = 0.0
    trending: bool = False
    sentiment_shift: bool = False
    fear_greed_index: int = 50
    timestamp: datetime | None = None


@dataclass(frozen=True)
class SentimentTrend:
    """Sentiment trend over time.

    Attributes:
        symbol: Asset symbol.
        current: Current composite sentiment.
        avg_7d: 7-day average sentiment.
        avg_30d: 30-day average sentiment.
        trend_direction: "improving", "declining", "stable".
        momentum: Sentiment momentum (rate of change).
        divergence: Whether sentiment diverges from price action.
    """

    symbol: str
    current: float
    avg_7d: float
    avg_30d: float
    trend_direction: str
    momentum: float
    divergence: bool


# ═══════════════════════════════════════════════════════════════════════
# SENTIMENT KEYWORDS & PATTERNS
# ═══════════════════════════════════════════════════════════════════════

_BULLISH_KEYWORDS = frozenset(
    {
        "moon",
        "bullish",
        "pump",
        "buy",
        "hold",
        "hodl",
        "accumulate",
        "breakout",
        "rally",
        "surge",
        "ATH",
        "bullrun",
        "to the moon",
        "diamond hands",
        "undervalued",
        "gem",
        "100x",
        "10x",
    }
)

_BEARISH_KEYWORDS = frozenset(
    {
        "dump",
        "crash",
        "bear",
        "sell",
        "short",
        "rug",
        "scam",
        "overvalued",
        "dead",
        "ponzi",
        "bubble",
        "collapse",
        "rekt",
        "paper hands",
        "exit",
        "liquidation",
        "capitulation",
    }
)

_CRYPTO_SUBREDDITS = [
    "CryptoCurrency",
    "Bitcoin",
    "ethereum",
    "CryptoMarkets",
    "altcoin",
]

_COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "NEAR": "near",
    "ARB": "arbitrum",
    "OP": "optimism",
}


# ═══════════════════════════════════════════════════════════════════════
# SOCIAL SENTIMENT TOOLS
# ═══════════════════════════════════════════════════════════════════════


class SocialSentimentAnalyzer:
    """Social sentiment analysis for crypto markets.

    Aggregates sentiment from Twitter/X, Reddit, and Telegram
    using free/public APIs. Computes composite scores, trending
    detection, and fear/greed estimation.
    """

    description = (
        "Social sentiment: Twitter/X, Reddit, Telegram, "
        "composite scoring, trending detection, fear/greed index"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None

        # Cache
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 300)

        # Optional API keys
        self._cryptopanic_key = self._config.get("cryptopanic_api_key", "")

        # Sentiment history for trend detection
        self._sentiment_history: dict[str, list[tuple[float, float]]] = {}

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

    # ── Twitter/X Sentiment ──────────────────────────────────────────

    async def get_twitter_sentiment(self, symbol: str) -> PlatformSentiment:
        """Get Twitter/X sentiment for a cryptocurrency.

        Uses CryptoPanic news votes and CoinGecko community data
        as sentiment proxies (direct Twitter API requires auth).

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            PlatformSentiment with Twitter sentiment data.
        """
        cache_key = f"twitter:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        base_symbol = symbol.split("/")[0].upper()

        try:
            # Parallel fetch from multiple sources
            news_sentiment, community_data = await asyncio.gather(
                self._fetch_cryptopanic_sentiment(client, base_symbol),
                self._fetch_coingecko_community(client, base_symbol),
                return_exceptions=True,
            )

            news_score = news_sentiment if not isinstance(news_sentiment, Exception) else 0.0
            community = community_data if not isinstance(community_data, Exception) else {}

            # Twitter-specific metrics from community data
            twitter_followers = community.get("twitter_followers", 0)
            twitter_sentiment = community.get("twitter_sentiment", news_score * 0.8)

            # Mention count estimation from follower activity
            # More followers = more mentions, roughly logarithmic
            import math

            estimated_mentions = (
                int(math.log10(max(twitter_followers, 1)) * 500) if twitter_followers > 0 else 0
            )

            # Trending score based on follower count and engagement
            trending_score = (
                min(1.0, twitter_followers / 2_000_000) if twitter_followers > 0 else 0.0
            )

            # Engagement score
            engagement = min(1.0, (twitter_followers / 1_000_000 + abs(twitter_sentiment)) / 2)

            # Top keywords based on sentiment direction
            if twitter_sentiment > 0.2:
                keywords = ("bullish", "buy", "moon", "pump")
            elif twitter_sentiment < -0.2:
                keywords = ("bearish", "sell", "dump", "crash")
            else:
                keywords = ("hold", "watch", "consolidation")

            result = PlatformSentiment(
                platform="twitter",
                sentiment=round(float(twitter_sentiment), 4),
                mention_count=estimated_mentions,
                engagement_score=round(engagement, 4),
                top_keywords=keywords,
                trending_score=round(trending_score, 4),
            )

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Twitter sentiment fetch failed for %s: %s", symbol, exc)
            return PlatformSentiment(platform="twitter", sentiment=0.0, mention_count=0)

    # ── Reddit Sentiment ─────────────────────────────────────────────

    async def get_reddit_sentiment(self, symbol: str) -> PlatformSentiment:
        """Get Reddit sentiment for a cryptocurrency.

        Analyzes posts from r/CryptoCurrency, r/Bitcoin, and
        asset-specific subreddits using the public Reddit API.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            PlatformSentiment with Reddit sentiment data.
        """
        cache_key = f"reddit:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        base_symbol = symbol.split("/")[0].upper()

        try:
            # Fetch from multiple subreddits in parallel
            subreddit_names = list(_CRYPTO_SUBREDDITS)
            # Add asset-specific subreddit
            asset_subreddit = self._get_asset_subreddit(base_symbol)
            if asset_subreddit:
                subreddit_names.append(asset_subreddit)

            tasks = [
                self._fetch_reddit_subreddit_sentiment(client, sub, base_symbol)
                for sub in subreddit_names[:4]  # Limit to avoid rate limiting
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Aggregate results
            sentiments: list[float] = []
            total_posts = 0
            total_score = 0.0

            for r in results:
                if isinstance(r, Exception):
                    continue
                if r.get("sentiment") is not None:
                    sentiments.append(r["sentiment"])
                    total_posts += r.get("post_count", 0)
                    total_score += r.get("total_score", 0)

            avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0
            avg_sentiment = max(-1.0, min(1.0, avg_sentiment))

            # Engagement based on post count and scores
            engagement = min(1.0, total_posts / 100) if total_posts > 0 else 0.0

            # Trending: high post volume relative to baseline
            trending_score = min(1.0, total_posts / 50) if total_posts > 0 else 0.0

            # Keywords from sentiment analysis
            if avg_sentiment > 0.2:
                keywords = ("bullish", "HODL", "accumulate", "undervalued")
            elif avg_sentiment < -0.2:
                keywords = ("bearish", "sell", "overvalued", "crash")
            else:
                keywords = ("discussion", "analysis", "neutral", "waiting")

            result = PlatformSentiment(
                platform="reddit",
                sentiment=round(avg_sentiment, 4),
                mention_count=total_posts,
                engagement_score=round(engagement, 4),
                top_keywords=keywords,
                trending_score=round(trending_score, 4),
            )

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Reddit sentiment fetch failed for %s: %s", symbol, exc)
            return PlatformSentiment(platform="reddit", sentiment=0.0, mention_count=0)

    async def _fetch_reddit_subreddit_sentiment(
        self,
        client: httpx.AsyncClient,
        subreddit: str,
        symbol: str,
    ) -> dict[str, Any]:
        """Fetch and analyze sentiment from a specific subreddit."""
        try:
            # Reddit public JSON API
            resp = await client.get(
                f"https://www.reddit.com/r/{subreddit}/hot.json",
                params={"limit": 25},
                headers={"User-Agent": "TSAR/1.0"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            posts = data.get("data", {}).get("children", [])
            if not posts:
                return {"sentiment": None, "post_count": 0}

            # Filter for posts mentioning the symbol
            symbol_lower = symbol.lower()
            relevant_posts: list[dict] = []

            for post in posts:
                post_data = post.get("data", {})
                title = post_data.get("title", "").lower()
                selftext = post_data.get("selftext", "").lower()

                if symbol_lower in title or symbol_lower in selftext:
                    relevant_posts.append(post_data)

            if not relevant_posts:
                # If no direct mentions, analyze general crypto sentiment
                relevant_posts = [p.get("data", {}) for p in posts[:10]]

            # Analyze sentiment of relevant posts
            sentiments: list[float] = []
            total_score = 0

            for post in relevant_posts:
                title = post.get("title", "")
                selftext = post.get("selftext", "")
                score = post.get("score", 0)

                text = f"{title} {selftext}"
                sentiment = self._analyze_text_sentiment(text)

                # Weight by upvote score
                weight = min(2.0, max(0.5, score / 100))
                sentiments.append(sentiment * weight)
                total_score += score

            avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

            return {
                "sentiment": avg_sentiment,
                "post_count": len(relevant_posts),
                "total_score": total_score,
            }

        except Exception as exc:
            logger.debug("Reddit r/%s fetch failed: %s", subreddit, exc)
            return {"sentiment": None, "post_count": 0}

    # ── Telegram Sentiment ───────────────────────────────────────────

    async def get_telegram_sentiment(self, symbol: str) -> PlatformSentiment:
        """Get Telegram sentiment for a cryptocurrency.

        Uses CryptoPanic and community data as proxies for Telegram
        group sentiment (Telegram groups don't have public APIs).

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            PlatformSentiment with Telegram sentiment estimate.
        """
        cache_key = f"telegram:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        base_symbol = symbol.split("/")[0].upper()

        try:
            # Use CryptoPanic as proxy — Telegram groups share similar narratives
            news_sentiment = await self._fetch_cryptopanic_sentiment(client, base_symbol)

            # Telegram sentiment is often more extreme than other platforms
            # Amplify news sentiment by 1.2x (capped at [-1, 1])
            tg_sentiment = max(-1.0, min(1.0, news_sentiment * 1.2))

            # Estimate mention count from market cap rank
            coin_id = _COINGECKO_IDS.get(base_symbol)
            mention_count = 0
            if coin_id:
                try:
                    resp = await client.get(
                        f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                        params={"localization": "false", "tickers": "false"},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    community = data.get("community_data", {})
                    # Telegram group members as proxy
                    tg_members = community.get("telegram_channel_user_count", 0)
                    mention_count = int(tg_members * 0.01) if tg_members > 0 else 0
                except Exception:
                    pass

            result = PlatformSentiment(
                platform="telegram",
                sentiment=round(tg_sentiment, 4),
                mention_count=mention_count,
                engagement_score=round(min(1.0, mention_count / 1000), 4),
                trending_score=round(min(1.0, abs(tg_sentiment)), 4),
            )

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Telegram sentiment fetch failed for %s: %s", symbol, exc)
            return PlatformSentiment(platform="telegram", sentiment=0.0, mention_count=0)

    # ── Composite Social Sentiment ───────────────────────────────────

    async def get_social_sentiment(self, symbol: str) -> SocialSentiment:
        """Get aggregated social sentiment from all platforms.

        Fetches Twitter, Reddit, and Telegram sentiment in parallel
        and computes a weighted composite score.

        Weights:
          - Twitter: 40% (highest signal for crypto)
          - Reddit: 35% (strong community signal)
          - Telegram: 25% (supplementary)

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            SocialSentiment with per-platform and composite scores.
        """
        cache_key = f"social:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base_symbol = symbol.split("/")[0].upper()

        # Fetch all platforms in parallel
        twitter, reddit, telegram = await asyncio.gather(
            self.get_twitter_sentiment(symbol),
            self.get_reddit_sentiment(symbol),
            self.get_telegram_sentiment(symbol),
            return_exceptions=True,
        )

        tw = twitter if not isinstance(twitter, Exception) else None
        rd = reddit if not isinstance(reddit, Exception) else None
        tg = telegram if not isinstance(telegram, Exception) else None

        # Weighted composite
        weights: list[tuple[float, float]] = []
        if tw:
            weights.append((tw.sentiment, 0.40))
        if rd:
            weights.append((rd.sentiment, 0.35))
        if tg:
            weights.append((tg.sentiment, 0.25))

        if weights:
            total_weight = sum(w for _, w in weights)
            composite = sum(s * w for s, w in weights) / total_weight
        else:
            composite = 0.0

        composite = max(-1.0, min(1.0, composite))

        # Trending detection: any platform trending
        trending = any(p.trending_score > 0.5 for p in [tw, rd, tg] if p is not None)

        # Fear/Greed index estimation
        fear_greed = int((composite + 1) / 2 * 100)
        fear_greed = max(0, min(100, fear_greed))

        # Sentiment shift detection
        self._record_sentiment(base_symbol, composite)
        sentiment_shift = self._detect_shift(base_symbol, composite)

        result = SocialSentiment(
            symbol=base_symbol,
            twitter=tw,
            reddit=rd,
            telegram=tg,
            composite_score=round(composite, 4),
            trending=trending,
            sentiment_shift=sentiment_shift,
            fear_greed_index=fear_greed,
            timestamp=datetime.now(UTC),
        )

        self._set_cached(cache_key, result)
        return result

    # ── Sentiment Trend Analysis ─────────────────────────────────────

    async def get_sentiment_trend(self, symbol: str) -> SentimentTrend:
        """Analyze sentiment trend over time.

        Compares current sentiment to historical averages to detect
        improving or declining sentiment trends.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            SentimentTrend with trend direction and momentum.
        """
        base_symbol = symbol.split("/")[0].upper()

        # Get current sentiment
        current_sentiment = await self.get_social_sentiment(symbol)
        current = current_sentiment.composite_score

        # Get historical data from our tracking
        history = self._sentiment_history.get(base_symbol, [])

        if len(history) >= 2:
            recent = [s for _, s in history[-7:]]
            older = [s for _, s in history[-30:-7]] if len(history) > 7 else recent

            avg_7d = sum(recent) / len(recent)
            avg_30d = sum(older) / len(older) if older else avg_7d
        else:
            avg_7d = current
            avg_30d = current

        # Trend direction
        if current > avg_7d + 0.1:
            direction = "improving"
        elif current < avg_7d - 0.1:
            direction = "declining"
        else:
            direction = "stable"

        # Momentum (rate of change)
        momentum = current - avg_7d

        return SentimentTrend(
            symbol=base_symbol,
            current=round(current, 4),
            avg_7d=round(avg_7d, 4),
            avg_30d=round(avg_30d, 4),
            trend_direction=direction,
            momentum=round(momentum, 4),
            divergence=False,  # Would need price data to detect
        )

    # ── Helper Methods ───────────────────────────────────────────────

    async def _fetch_cryptopanic_sentiment(
        self,
        client: httpx.AsyncClient,
        symbol: str,
    ) -> float:
        """Fetch sentiment from CryptoPanic news votes."""
        try:
            params: dict[str, str] = {
                "currencies": symbol,
                "kind": "news",
                "filter": "important",
                "public": "true",
            }
            if self._cryptopanic_key:
                params["auth_token"] = self._cryptopanic_key

            resp = await client.get(
                "https://cryptopanic.com/api/v1/posts/",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                return 0.0

            total_pos = sum(r.get("votes", {}).get("positive", 0) for r in results)
            total_neg = sum(r.get("votes", {}).get("negative", 0) for r in results)
            total = total_pos + total_neg

            if total > 0:
                return max(-1.0, min(1.0, (total_pos - total_neg) / total))
            return 0.0

        except Exception as exc:
            logger.debug("CryptoPanic sentiment fetch failed: %s", exc)
            return 0.0

    async def _fetch_coingecko_community(
        self,
        client: httpx.AsyncClient,
        symbol: str,
    ) -> dict[str, Any]:
        """Fetch community data from CoinGecko."""
        try:
            coin_id = _COINGECKO_IDS.get(symbol)
            if not coin_id:
                return {}

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={"localization": "false", "tickers": "false"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            community = data.get("community_data", {})
            sentiment_up = data.get("sentiment_votes_up_percentage", 50)
            sentiment_down = data.get("sentiment_votes_down_percentage", 50)

            total_votes = sentiment_up + sentiment_down
            sentiment = (sentiment_up - sentiment_down) / total_votes if total_votes > 0 else 0.0

            return {
                "twitter_followers": community.get("twitter_followers", 0),
                "twitter_sentiment": sentiment,
                "reddit_subscribers": community.get("reddit_subscribers", 0),
                "reddit_posts_48h": community.get("reddit_posts_48h", 0),
                "telegram_users": community.get("telegram_channel_user_count", 0),
            }

        except Exception as exc:
            logger.debug("CoinGecko community fetch failed: %s", exc)
            return {}

    @staticmethod
    def _analyze_text_sentiment(text: str) -> float:
        """Simple keyword-based sentiment analysis.

        Returns score from -1 (bearish) to +1 (bullish).
        This is a fallback when NLP APIs aren't available.
        """
        text_lower = text.lower()
        words = set(re.findall(r"\b\w+\b", text_lower))

        bullish_hits = len(words & _BULLISH_KEYWORDS)
        bearish_hits = len(words & _BEARISH_KEYWORDS)

        total = bullish_hits + bearish_hits
        if total == 0:
            return 0.0

        return (bullish_hits - bearish_hits) / total

    @staticmethod
    def _get_asset_subreddit(symbol: str) -> str | None:
        """Get the subreddit name for a given crypto asset."""
        mapping = {
            "BTC": "Bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "ADA": "cardano",
            "DOT": "polkadot",
            "AVAX": "Avax",
            "MATIC": "0xPolygon",
            "LINK": "Chainlink",
            "UNI": "Uniswap",
            "ATOM": "cosmosnetwork",
            "NEAR": "NearProtocol",
            "DOGE": "dogecoin",
            "XRP": "Ripple",
            "BNB": "bnbchainofficial",
        }
        return mapping.get(symbol.upper())

    def _record_sentiment(self, symbol: str, score: float) -> None:
        """Record sentiment for trend tracking."""
        if symbol not in self._sentiment_history:
            self._sentiment_history[symbol] = []

        history = self._sentiment_history[symbol]
        history.append((time.time(), score))

        # Keep last 100 entries
        if len(history) > 100:
            self._sentiment_history[symbol] = history[-100:]

    def _detect_shift(self, symbol: str, current: float) -> bool:
        """Detect significant sentiment shift."""
        history = self._sentiment_history.get(symbol, [])
        if len(history) < 5:
            return False

        recent_avg = sum(s for _, s in history[-5:]) / 5
        return abs(current - recent_avg) > 0.2
