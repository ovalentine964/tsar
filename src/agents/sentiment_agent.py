"""TSAR — Sentiment Agent (H-011).

Aggregates sentiment signals from free data sources:
- CryptoPanic API: Crypto news sentiment (free tier: 20 req/min)
- Fear & Greed Index: alternative.me (free, no auth)
- Funding Rates: Binance futures (free, public endpoint)

All data is cached to avoid API rate limits. Sentiment scores are
published as CloudEvents on the sentiment stream.

Subscribes to: (none — runs on a timer)
Publishes to: tsar:stream:sentiment
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class SentimentSnapshot:
    """Composite sentiment from all sources.

    Attributes:
        fear_greed_index: Fear & Greed Index (0-100, 0=extreme fear).
        fear_greed_label: Human-readable label.
        news_sentiment: CryptoPanic news sentiment (-1 to +1).
        news_count: Number of news items analyzed.
        funding_rate: Current Binance funding rate (positive = longs pay).
        funding_sentiment: Derived sentiment from funding (-1 to +1).
        composite_score: Weighted composite sentiment (-1 to +1).
        timestamp: When this snapshot was taken.
    """
    fear_greed_index: int = 50
    fear_greed_label: str = "neutral"
    news_sentiment: float = 0.0
    news_count: int = 0
    funding_rate: float = 0.0
    funding_sentiment: float = 0.0
    composite_score: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fear_greed": {
                "index": self.fear_greed_index,
                "label": self.fear_greed_label,
            },
            "news": {
                "sentiment": round(self.news_sentiment, 4),
                "count": self.news_count,
            },
            "funding": {
                "rate": round(self.funding_rate, 6),
                "sentiment": round(self.funding_sentiment, 4),
            },
            "composite_score": round(self.composite_score, 4),
            "timestamp": self.timestamp,
        }


@dataclass
class SentimentCache:
    """Simple TTL cache for sentiment data."""

    _data: dict[str, tuple[float, Any]] = field(default_factory=dict)
    _ttl: int = 300  # 5 minutes default

    def get(self, key: str) -> Any | None:
        if key in self._data:
            ts, val = self._data[key]
            if time.time() - ts < self._ttl:
                return val
            del self._data[key]
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._data[key] = (time.time(), value)


# ═══════════════════════════════════════════════════════════════════════
# SENTIMENT AGENT
# ═══════════════════════════════════════════════════════════════════════


class SentimentAgent(BaseAgent):
    """Aggregate sentiment from free data sources and publish sentiment events.

    Cycle: Every 15 minutes (configurable).
    Sources: CryptoPanic, Fear & Greed Index, Binance Funding Rates.
    """

    AGENT_NAME = "sentiment_agent"
    ROLE = "ANALYSIS"
    PUBLISH_STREAM = "sentiment"
    SUBSCRIBE_STREAMS: list[str] = []

    # Composite weights
    WEIGHT_FEAR_GREED = 0.40
    WEIGHT_NEWS = 0.35
    WEIGHT_FUNDING = 0.25

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)
        self._cycle_interval = config.get("agents", {}).get("sentiment_agent", {}).get(
            "cycle_interval_s", 900  # 15 minutes
        )
        self._last_scan = 0.0

        # Config
        sentiment_cfg = config.get("agents", {}).get("sentiment_agent", {})
        self._cryptopanic_key = sentiment_cfg.get("cryptopanic_api_key", "")
        self._symbols = sentiment_cfg.get("symbols", ["BTC"])
        self._funding_symbols = sentiment_cfg.get("funding_symbols", ["BTCUSDT"])

        # Cache
        self._cache = SentimentCache(_ttl=sentiment_cfg.get("cache_ttl_s", 300))

        # HTTP client (lazy)
        self._client: httpx.AsyncClient | None = None

    async def on_initialize(self) -> None:
        self._client = httpx.AsyncClient(timeout=15.0)
        logger.info("SentimentAgent initialized: symbols=%s", self._symbols)

    async def on_shutdown(self) -> None:
        if self._client:
            await self._client.aclose()

    async def run_cycle(self) -> None:
        now = time.monotonic()
        if now - self._last_scan < self._cycle_interval:
            return
        self._last_scan = now

        try:
            snapshot = await self._gather_sentiment()
            await self._publish_sentiment(snapshot)
        except Exception:
            logger.exception("Sentiment cycle failed")

    async def _gather_sentiment(self) -> SentimentSnapshot:
        """Fetch all sentiment sources concurrently."""
        assert self._client is not None

        # Fetch all three sources in parallel
        fg_task = asyncio.create_task(self._fetch_fear_greed())
        news_task = asyncio.create_task(self._fetch_news_sentiment())
        funding_task = asyncio.create_task(self._fetch_funding_rates())

        fg_index, fg_label = await fg_task
        news_sent, news_count = await news_task
        funding_rate = await funding_task

        # Derive funding sentiment: positive rate = longs pay shorts = bullish crowding
        # Extreme positive funding = contrarian bearish signal
        # Range: -0.01 to +0.01 typical, map to -1 to +1
        funding_sentiment = max(-1.0, min(1.0, -funding_rate * 100))  # Inverted: high funding = bearish

        # Composite score
        fg_normalized = (fg_index - 50) / 50.0  # -1 to +1

        composite = (
            self.WEIGHT_FEAR_GREED * fg_normalized
            + self.WEIGHT_NEWS * news_sent
            + self.WEIGHT_FUNDING * funding_sentiment
        )
        composite = max(-1.0, min(1.0, composite))

        snapshot = SentimentSnapshot(
            fear_greed_index=fg_index,
            fear_greed_label=fg_label,
            news_sentiment=news_sent,
            news_count=news_count,
            funding_rate=funding_rate,
            funding_sentiment=funding_sentiment,
            composite_score=composite,
            timestamp=datetime.now(UTC).isoformat(),
        )

        logger.info(
            "Sentiment: fg=%d(%s) news=%.2f(%d) funding=%.4f composite=%.3f",
            fg_index, fg_label, news_sent, news_count, funding_rate, composite,
        )
        return snapshot

    # ── Fear & Greed Index (alternative.me) ───────────────────────────

    async def _fetch_fear_greed(self) -> tuple[int, str]:
        """Fetch Crypto Fear & Greed Index from alternative.me.

        Free, no auth required. Returns (index, label).
        """
        cached = self._cache.get("fear_greed")
        if cached:
            return cached

        assert self._client is not None
        try:
            resp = await self._client.get(
                "https://api.alternative.me/fng/?limit=1&format=json"
            )
            resp.raise_for_status()
            data = resp.json()
            entry = data["data"][0]
            index = int(entry["value"])
            label = entry["value_classification"].lower()
            self._cache.set("fear_greed", (index, label))
            return index, label
        except Exception:
            logger.warning("Failed to fetch Fear & Greed Index", exc_info=True)
            return 50, "neutral"

    # ── CryptoPanic News Sentiment ────────────────────────────────────

    async def _fetch_news_sentiment(self) -> tuple[float, int]:
        """Fetch news sentiment from CryptoPanic API.

        Free tier: 20 requests/minute, public posts only.
        Returns (sentiment_score, news_count).
        """
        cached = self._cache.get("news_sentiment")
        if cached:
            return cached

        assert self._client is not None
        try:
            symbol = self._symbols[0] if self._symbols else "BTC"
            url = "https://cryptopanic.com/api/v1/posts/"
            params: dict[str, str] = {
                "auth_token": self._cryptopanic_key,
                "currencies": symbol,
                "kind": "news",
                "filter": "important",
                "public": "true",
            }
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                self._cache.set("news_sentiment", (0.0, 0))
                return 0.0, 0

            # Aggregate votes: positive - negative / total
            total_positive = 0
            total_negative = 0
            for item in results:
                votes = item.get("votes", {})
                total_positive += votes.get("positive", 0)
                total_negative += votes.get("negative", 0)

            total_votes = total_positive + total_negative
            if total_votes > 0:
                sentiment = (total_positive - total_negative) / total_votes
            else:
                sentiment = 0.0

            sentiment = max(-1.0, min(1.0, sentiment))
            self._cache.set("news_sentiment", (sentiment, len(results)))
            return sentiment, len(results)

        except Exception:
            logger.warning("Failed to fetch CryptoPanic sentiment", exc_info=True)
            return 0.0, 0

    # ── Binance Funding Rates ────────────────────────────────────────

    async def _fetch_funding_rates(self) -> float:
        """Fetch current funding rate from Binance Futures.

        Free, no auth required. Returns the current funding rate.
        """
        cached = self._cache.get("funding_rate")
        if cached is not None:
            return cached

        assert self._client is not None
        try:
            symbol = self._funding_symbols[0] if self._funding_symbols else "BTCUSDT"
            resp = await self._client.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": symbol, "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                rate = float(data[0]["fundingRate"])
                self._cache.set("funding_rate", rate)
                return rate
            return 0.0
        except Exception:
            logger.warning("Failed to fetch Binance funding rate", exc_info=True)
            return 0.0

    # ── Publishing ────────────────────────────────────────────────────

    async def _publish_sentiment(self, snapshot: SentimentSnapshot) -> None:
        """Publish sentiment snapshot as a CloudEvent."""
        await self.publish_event(
            stream="sentiment",
            event_type="tsar.sentiment.update.v1",
            data=snapshot.to_dict(),
            priority=2,
            risk_level="NONE",
        )
        logger.info("Published sentiment: composite=%.3f", snapshot.composite_score)
