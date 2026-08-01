"""
TSAR — Fundamental & Macro Scoring Bridge.

Converts outputs from domain tools (news, fundamental, economic_calendar,
sentiment) into normalized factor scores for Signal Scout's 9-factor
confirmation system.

This module is the MISSING PIECE between the existing data-gathering
tools and the signal scoring engine.

9-Factor System:
  Technical (5): RSI, S/R, Volume, Trend, Multi-TF
  Fundamental (4): Macro, News, Fundamental, Sentiment

Minimum 5/9 factors must confirm for trade entry.
Dynamic weight adjustment during high-impact macro events.

Subscribes to: (none — called by SignalScout)
Publishes to:  (none — returns scores to caller)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.tools.economic_calendar import (
    EconomicCalendar,
    EconomicCalendarTools,
    EconomicEvent,
)
from src.tools.fundamental import (
    FundamentalAnalysisTools,
    ProjectFundamentals,
)
from src.tools.news import NewsAggregator, NewsDigest
from src.tools.sentiment import SocialSentiment, SocialSentimentAnalyzer

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# FACTOR SCORE RESULT
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FundamentalFactors:
    """Computed fundamental/macro factor scores for a symbol.

    Each factor is normalized to [-1, +1]:
      - Positive = bullish signal
      - Negative = bearish signal
      - 0 = neutral / no signal

    Attributes:
        macro_score: Economic calendar impact (-1 to +1).
        news_score: News sentiment & velocity (-1 to +1).
        fundamental_score: Project health (-1 to +1).
        sentiment_score: Social sentiment, contrarian (-1 to +1).
        factors_confirming_buy: Number of factors bullish for BUY.
        factors_confirming_sell: Number of factors bearish for SELL.
        event_position_multiplier: Position size multiplier from events (0-1.5).
        event_restriction: Event-driven restriction reason, or None.
        is_restricted: Whether an event blocks trading.
        computed_at: Timestamp.
    """

    macro_score: float = 0.0
    news_score: float = 0.0
    fundamental_score: float = 0.0
    sentiment_score: float = 0.0

    factors_confirming_buy: int = 0
    factors_confirming_sell: int = 0

    event_position_multiplier: float = 1.0
    event_restriction: str | None = None
    is_restricted: bool = False

    computed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "macro": round(self.macro_score, 4),
            "news": round(self.news_score, 4),
            "fundamental": round(self.fundamental_score, 4),
            "sentiment": round(self.sentiment_score, 4),
            "confirming_buy": self.factors_confirming_buy,
            "confirming_sell": self.factors_confirming_sell,
            "event_multiplier": self.event_position_multiplier,
            "event_restriction": self.event_restriction,
            "is_restricted": self.is_restricted,
        }


# ═══════════════════════════════════════════════════════════════════════
# SCORING WEIGHTS (9-Factor)
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FactorWeights:
    """9-factor scoring weights — must sum to 1.0."""

    # Technical factors (55% total)
    rsi: float = 0.15
    sr_proximity: float = 0.12
    volume: float = 0.08
    trend: float = 0.08
    multi_timeframe: float = 0.12

    # Fundamental/Macro factors (45% total)
    macro: float = 0.15
    news: float = 0.12
    fundamental: float = 0.10
    sentiment: float = 0.08

    def validate(self) -> None:
        total = (
            self.rsi + self.sr_proximity + self.volume + self.trend
            + self.multi_timeframe + self.macro + self.news
            + self.fundamental + self.sentiment
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")

    def to_dict(self) -> dict[str, float]:
        return {
            "rsi": self.rsi,
            "sr_proximity": self.sr_proximity,
            "volume": self.volume,
            "trend": self.trend,
            "multi_timeframe": self.multi_timeframe,
            "macro": self.macro,
            "news": self.news,
            "fundamental": self.fundamental,
            "sentiment": self.sentiment,
        }


# Default weights
DEFAULT_WEIGHTS = FactorWeights()

# Weights during high-impact macro events (FOMC, CPI)
HIGH_IMPACT_WEIGHTS = FactorWeights(
    rsi=0.10,
    sr_proximity=0.08,
    volume=0.05,
    trend=0.05,
    multi_timeframe=0.07,
    macro=0.25,       # BOOSTED
    news=0.18,        # BOOSTED
    fundamental=0.07,
    sentiment=0.15,   # Slightly boosted
)

# Weights during medium-impact events (NFP, GDP)
MEDIUM_IMPACT_WEIGHTS = FactorWeights(
    rsi=0.13,
    sr_proximity=0.11,
    volume=0.07,
    trend=0.07,
    multi_timeframe=0.09,
    macro=0.20,       # Moderately boosted
    news=0.15,        # Moderately boosted
    fundamental=0.08,
    sentiment=0.10,
)


# ═══════════════════════════════════════════════════════════════════════
# EVENT-DRIVEN RULES
# ═══════════════════════════════════════════════════════════════════════


class EventDrivenRules:
    """Hard rules that override normal trading logic during macro events.

    These are non-negotiable safety rules:
    - FOMC ±2h: BLOCK all new trades
    - CPI day: 50% position reduction
    - Halving: 150% position boost
    - Token unlock: AVOID specific token
    - Major hack: PAUSE that asset
    """

    @staticmethod
    def check_fomc_blackout(
        calendar: EconomicCalendar,
        blackout_hours: float = 2.0,
    ) -> tuple[bool, str]:
        """Check if within FOMC blackout window.

        Returns:
            (is_blocked, reason)
        """
        now = datetime.now(UTC)

        for event in calendar.fed_events:
            if event.days_until > 0:
                continue
            if not event.time:
                continue

            try:
                event_dt = datetime.strptime(
                    f"{event.date} {event.time}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=UTC)
                hours_diff = abs((now - event_dt).total_seconds()) / 3600

                if hours_diff < blackout_hours:
                    return True, (
                        f"FOMC blackout: {event.event} at {event.time} "
                        f"({hours_diff:.1f}h away)"
                    )
            except (ValueError, TypeError):
                continue

        return False, ""

    @staticmethod
    def check_cpi_reduction(
        calendar: EconomicCalendar,
    ) -> tuple[bool, float, str]:
        """Check if CPI day — reduce position size.

        Returns:
            (is_cpi_day, multiplier, reason)
        """
        for event in calendar.inflation_events:
            if event.days_until == 0 and "cpi" in event.event.lower():
                return True, 0.5, f"CPI day: position reduced to 50%"

        return False, 1.0, ""

    @staticmethod
    def check_halving_boost(
        calendar: EconomicCalendar,
    ) -> tuple[bool, float, str]:
        """Check if near Bitcoin halving — boost position.

        Returns:
            (is_near_halving, multiplier, reason)
        """
        for event in calendar.crypto_events:
            if "halving" in event.event.lower() and event.days_until <= 30:
                return True, 1.5, f"Halving proximity ({event.days_until}d): 1.5x boost"

        return False, 1.0, ""

    @staticmethod
    def check_token_unlock(
        symbol: str,
        calendar: EconomicCalendar,
    ) -> tuple[bool, str]:
        """Check if token unlock imminent for this symbol.

        Returns:
            (should_avoid, reason)
        """
        base_symbol = symbol.split("/")[0].upper()

        for event in calendar.crypto_events:
            if "unlock" in event.event.lower() and event.days_until <= 1:
                if base_symbol in event.event.upper():
                    return True, f"Token unlock: avoiding {base_symbol}"

        return False, ""

    @staticmethod
    def check_security_event(
        symbol: str,
        news: NewsDigest | None,
    ) -> tuple[bool, str]:
        """Check for hack/exploit news affecting this symbol.

        Returns:
            (should_pause, reason)
        """
        if not news:
            return False, ""

        security_keywords = ["hack", "exploit", "vulnerability", "breach", "stolen"]

        for item in news.items:
            title_lower = item.title.lower()
            if any(kw in title_lower for kw in security_keywords):
                if item.relevance > 0.7 and item.sentiment < -0.3:
                    return True, f"Security event: {item.title[:80]}"

        return False, ""

    @classmethod
    def evaluate_all(
        cls,
        symbol: str,
        calendar: EconomicCalendar,
        news: NewsDigest | None,
    ) -> tuple[bool, str, float]:
        """Evaluate all event-driven rules.

        Returns:
            (is_allowed, reason, position_multiplier)
            - is_allowed: False = BLOCK trade, True = trade with multiplier
            - reason: Human-readable explanation
            - position_multiplier: 0.0-1.5 (applied to position size)
        """
        # Rule 1: FOMC blackout — hard block
        blocked, reason = cls.check_fomc_blackout(calendar)
        if blocked:
            return False, reason, 0.0

        # Rule 2: Token unlock — avoid specific token
        avoid, reason = cls.check_token_unlock(symbol, calendar)
        if avoid:
            return False, reason, 0.0

        # Rule 3: Security event — pause asset
        pause, reason = cls.check_security_event(symbol, news)
        if pause:
            return False, reason, 0.0

        # Rule 4: CPI day — reduce position
        is_cpi, cpi_mult, cpi_reason = cls.check_cpi_reduction(calendar)
        if is_cpi:
            return True, cpi_reason, cpi_mult

        # Rule 5: Halving proximity — boost position
        is_halving, halving_mult, halving_reason = cls.check_halving_boost(calendar)
        if is_halving:
            return True, halving_reason, halving_mult

        return True, "No event restrictions", 1.0


# ═══════════════════════════════════════════════════════════════════════
# FUNDAMENTAL SCORER
# ═══════════════════════════════════════════════════════════════════════


class FundamentalScorer:
    """Bridge between domain tools and Signal Scout's scoring engine.

    Computes the 4 fundamental/macro factors and integrates them
    with the 5 technical factors for 9-factor confirmation.

    Usage:
        scorer = FundamentalScorer(config)
        factors = await scorer.compute_factors("BTC/USDT")
        # Use factors.macro_score, factors.news_score, etc.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

        # Initialize tools (lightweight — lazy HTTP clients)
        self._economic_calendar = EconomicCalendarTools(config=self._config)
        self._news_aggregator = NewsAggregator(config=self._config)
        self._fundamental_tools = FundamentalAnalysisTools(config=self._config)
        self._sentiment_analyzer = SocialSentimentAnalyzer(config=self._config)

        # Cache for factor results
        self._factor_cache: dict[str, tuple[float, FundamentalFactors]] = {}
        self._cache_ttl = 120  # 2 min cache for factor scores

        # Cached macro state (populated by MacroAgent)
        self._cached_calendar: EconomicCalendar | None = None
        self._cached_sentiment: dict[str, SocialSentiment] = {}

    async def close(self) -> None:
        """Close all tool HTTP clients."""
        await self._economic_calendar.close()
        await self._news_aggregator.close()
        await self._fundamental_tools.close()
        await self._sentiment_analyzer.close()

    # ── Main Entry Point ─────────────────────────────────────────────

    async def compute_factors(self, symbol: str) -> FundamentalFactors:
        """Compute all 4 fundamental/macro factors for a symbol.

        This is the main method called by SignalScout.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").

        Returns:
            FundamentalFactors with all scores and event rules applied.
        """
        # Check cache
        cache_key = f"factors:{symbol}"
        if cache_key in self._factor_cache:
            ts, cached = self._factor_cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return cached

        # Fetch all data in parallel
        import asyncio

        calendar_task = asyncio.create_task(self._get_calendar())
        news_task = asyncio.create_task(self._news_aggregator.get_news_digest(symbol, limit=20))
        fundamental_task = asyncio.create_task(self._fundamental_tools.get_project_fundamentals(symbol))
        sentiment_task = asyncio.create_task(self._sentiment_analyzer.get_social_sentiment(symbol))

        results = await asyncio.gather(
            calendar_task, news_task, fundamental_task, sentiment_task,
            return_exceptions=True,
        )

        calendar = results[0] if not isinstance(results[0], Exception) else None
        news = results[1] if not isinstance(results[1], Exception) else None
        fundamentals = results[2] if not isinstance(results[2], Exception) else None
        sentiment = results[3] if not isinstance(results[3], Exception) else None

        # Compute individual factor scores
        macro_score = self._compute_macro_score(calendar)
        news_score = self._compute_news_score(news)
        fundamental_score = self._compute_fundamental_score(fundamentals)
        sentiment_score = self._compute_sentiment_score(sentiment)

        # Count confirming factors
        buy_count = sum(1 for s in [macro_score, news_score, fundamental_score, sentiment_score] if s > 0.0)
        sell_count = sum(1 for s in [macro_score, news_score, fundamental_score, sentiment_score] if s < 0.0)

        # Event-driven rules
        is_allowed, event_reason, event_multiplier = True, "No event restrictions", 1.0
        if calendar:
            is_allowed, event_reason, event_multiplier = EventDrivenRules.evaluate_all(
                symbol, calendar, news,
            )

        result = FundamentalFactors(
            macro_score=round(macro_score, 4),
            news_score=round(news_score, 4),
            fundamental_score=round(fundamental_score, 4),
            sentiment_score=round(sentiment_score, 4),
            factors_confirming_buy=buy_count,
            factors_confirming_sell=sell_count,
            event_position_multiplier=event_multiplier,
            event_restriction=event_reason,
            is_restricted=not is_allowed,
            computed_at=time.time(),
        )

        self._factor_cache[cache_key] = (time.time(), result)
        return result

    def get_weights_for_context(
        self,
        calendar: EconomicCalendar | None = None,
    ) -> FactorWeights:
        """Get scoring weights adjusted for current macro context.

        During high-impact events, fundamental factors get higher weight.
        """
        if not calendar or not calendar.risk_window:
            return DEFAULT_WEIGHTS

        max_impact = max(
            (e.impact_score for e in calendar.risk_events),
            default=0.0,
        )

        if max_impact > 0.8:
            logger.info("High-impact event imminent — using boosted fundamental weights")
            return HIGH_IMPACT_WEIGHTS
        elif max_impact > 0.6:
            logger.info("Medium-impact event imminent — using moderate fundamental weights")
            return MEDIUM_IMPACT_WEIGHTS

        return DEFAULT_WEIGHTS

    # ── Macro Factor ─────────────────────────────────────────────────

    def _compute_macro_score(self, calendar: EconomicCalendar | None) -> float:
        """Compute macro factor from economic calendar.

        Scoring:
        - FOMC rate cut expected → +0.5 to +0.8
        - FOMC rate hike expected → -0.5 to -0.8
        - CPI falling → +0.3 to +0.5
        - CPI rising → -0.3 to -0.5
        - NFP strong → -0.2 to -0.4 (hawkish)
        - NFP weak → +0.2 to +0.4 (dovish)
        - Halving → +0.7
        - Token unlock → -0.3

        Returns: -1.0 to +1.0
        """
        if not calendar:
            return 0.0

        scores: list[tuple[float, float]] = []  # (score, weight)

        # Analyze each high-impact event
        for event in calendar.high_impact_events:
            if event.days_until > 7:
                continue  # Skip events > 7 days out

            # Decay by proximity: 1 day out = full weight, 7 days = 1/7
            decay = 1.0 / max(event.days_until, 1)
            weight = event.impact_score * decay

            event_score = self._score_macro_event(event)
            if event_score != 0.0:
                scores.append((event_score, weight))

        if not scores:
            return 0.0

        total_weight = sum(w for _, w in scores)
        if total_weight == 0:
            return 0.0

        return max(-1.0, min(1.0, sum(s * w for s, w in scores) / total_weight))

    @staticmethod
    def _score_macro_event(event: EconomicEvent) -> float:
        """Score a single macro event's crypto impact."""
        cat = event.category
        title_lower = event.event.lower()

        if cat == "fed":
            # Rate direction from forecast vs previous
            if event.forecast and event.previous:
                try:
                    forecast = float(event.forecast.replace("%", ""))
                    prev = float(event.previous.replace("%", ""))
                    if forecast < prev:
                        return 0.6   # Rate cut = bullish
                    elif forecast > prev:
                        return -0.6  # Rate hike = bearish
                except ValueError:
                    pass
            # Default: FOMC = uncertainty = slight bearish
            return -0.1

        elif cat == "inflation":
            if event.forecast and event.previous:
                try:
                    forecast = float(event.forecast.replace("%", ""))
                    prev = float(event.previous.replace("%", ""))
                    if forecast < prev:
                        return 0.4   # Cooling inflation = bullish
                    elif forecast > prev:
                        return -0.4  # Rising inflation = bearish
                except ValueError:
                    pass
            return 0.0

        elif cat == "employment":
            if event.forecast and event.previous:
                try:
                    forecast = float(event.forecast.replace("K", "").replace(",", ""))
                    prev = float(event.previous.replace("K", "").replace(",", ""))
                    if forecast > prev:
                        return -0.3  # Strong jobs = hawkish = bearish
                    elif forecast < prev:
                        return 0.3   # Weak jobs = dovish = bullish
                except ValueError:
                    pass
            return 0.0

        elif cat == "crypto":
            if "halving" in title_lower:
                return 0.7
            elif "unlock" in title_lower:
                return -0.3
            elif "etf" in title_lower and "approval" in title_lower:
                return 0.8

        return 0.0

    # ── News Factor ──────────────────────────────────────────────────

    def _compute_news_score(self, news: NewsDigest | None) -> float:
        """Compute news factor from aggregated news digest.

        Factors in:
        - Base sentiment (from votes/keywords)
        - News velocity (rapid news = strong signal)
        - Breaking news amplification
        - Source agreement

        Returns: -1.0 to +1.0
        """
        if not news or news.item_count == 0:
            return 0.0

        # Base sentiment (already -1 to +1)
        base = news.overall_sentiment

        # Velocity multiplier
        velocity = 1.0
        if news.high_impact_count >= 5:
            velocity = 1.3  # Breaking surge
        elif news.high_impact_count >= 3:
            velocity = 1.15  # Rapid
        elif news.item_count >= 10:
            velocity = 1.05  # Elevated

        # Breaking news amplification
        if news.breaking_count > 0:
            velocity *= 1.1

        # Source agreement boost
        source_sents = list(news.sentiment_by_source.values())
        if len(source_sents) >= 2:
            all_bullish = all(s > 0.1 for s in source_sents)
            all_bearish = all(s < -0.1 for s in source_sents)
            if all_bullish or all_bearish:
                velocity *= 1.1

        # Contrarian check: if news extremely positive AND we're at extreme greed,
        # it might be a top signal (handled by sentiment factor)
        # Here we just report raw news direction

        raw = base * velocity
        return max(-1.0, min(1.0, raw))

    # ── Fundamental Factor ───────────────────────────────────────────

    def _compute_fundamental_score(
        self,
        fundamentals: ProjectFundamentals | None,
    ) -> float:
        """Compute fundamental factor from project health.

        Components:
        - GitHub activity (25%): developer engagement
        - TVL growth (25%): DeFi adoption
        - Tokenomics (25%): supply dynamics
        - Valuation (25%): mcap/FDV, volume

        Returns: -1.0 to +1.0
        """
        if not fundamentals:
            return 0.0

        scores: list[tuple[float, float]] = []  # (score, weight)

        # GitHub Activity
        if fundamentals.github and fundamentals.github.repo:
            github = fundamentals.github
            # activity_score is 0-1, map to -1 to +1
            github_signal = (github.activity_score - 0.5) * 2.0
            scores.append((github_signal, 0.25))

        # TVL Growth (DeFi only)
        if fundamentals.tvl and fundamentals.tvl.tvl > 0:
            tvl = fundamentals.tvl
            tvl_signal = 0.0

            # 7-day TVL change
            if tvl.tvl_change_7d > 5:
                tvl_signal += 0.5
            elif tvl.tvl_change_7d > 0:
                tvl_signal += 0.2
            elif tvl.tvl_change_7d < -5:
                tvl_signal -= 0.5
            elif tvl.tvl_change_7d < 0:
                tvl_signal -= 0.2

            # mcap/TVL ratio
            if tvl.mcap_to_tvl > 0:
                if tvl.mcap_to_tvl < 1.0:
                    tvl_signal += 0.3  # Undervalued
                elif tvl.mcap_to_tvl > 5.0:
                    tvl_signal -= 0.3  # Overvalued

            scores.append((max(-1.0, min(1.0, tvl_signal)), 0.25))

        # Tokenomics
        if fundamentals.market_structure and fundamentals.market_structure.tokenomics:
            tokenomics = fundamentals.market_structure.tokenomics
            token_signal = (tokenomics.tokenomics_score - 0.5) * 2.0
            scores.append((token_signal, 0.25))

        # Valuation
        if fundamentals.market_structure:
            ms = fundamentals.market_structure
            val_signal = 0.0

            if ms.valuation_signal == "undervalued":
                val_signal = 0.5
            elif ms.valuation_signal == "fair":
                val_signal = 0.0
            elif ms.valuation_signal == "overvalued":
                val_signal = -0.5

            # FDV/mcap dilution risk
            if ms.fully_diluted_valuation > 0 and ms.market_cap > 0:
                fdv_ratio = ms.fully_diluted_valuation / ms.market_cap
                if fdv_ratio > 3:
                    val_signal -= 0.3
                elif fdv_ratio < 1.5:
                    val_signal += 0.1

            scores.append((max(-1.0, min(1.0, val_signal)), 0.25))

        if not scores:
            return 0.0

        total_weight = sum(w for _, w in scores)
        return max(-1.0, min(1.0, sum(s * w for s, w in scores) / total_weight))

    # ── Sentiment Factor (CONTRARIAN) ────────────────────────────────

    def _compute_sentiment_score(
        self,
        sentiment: SocialSentiment | None,
    ) -> float:
        """Compute sentiment factor using CONTRARIAN logic.

        Extreme fear = BUY signal (+1.0)
        Extreme greed = SELL signal (-1.0)

        The crowd is usually wrong at extremes. We fade them.

        Returns: -1.0 (extreme greed/sell) to +1.0 (extreme fear/buy)
        """
        if not sentiment:
            return 0.0

        # Fear & Greed contrarian mapping
        fg = sentiment.fear_greed_index

        if fg <= 10:
            fg_signal = 0.9   # Extreme fear → strong buy
        elif fg <= 25:
            fg_signal = 0.6   # Fear → buy
        elif fg <= 40:
            fg_signal = 0.3   # Cautious → mild buy
        elif fg <= 60:
            fg_signal = 0.0   # Neutral
        elif fg <= 75:
            fg_signal = -0.3  # Greed → mild sell
        elif fg <= 90:
            fg_signal = -0.6  # High greed → sell
        else:
            fg_signal = -0.9  # Extreme greed → strong sell

        # Social composite (contrarian: invert crowd sentiment)
        social = sentiment.composite_score
        social_signal = -social * 0.5

        # Trending amplification
        trending_bonus = 0.0
        if sentiment.trending and abs(fg_signal) > 0.5:
            trending_bonus = 0.2 if fg_signal > 0 else -0.2

        # Sentiment shift at extreme = reversal opportunity
        shift_bonus = 0.0
        if sentiment.sentiment_shift and (fg < 30 or fg > 70):
            shift_bonus = 0.15 if fg < 50 else -0.15

        raw = fg_signal * 0.6 + social_signal * 0.3 + trending_bonus + shift_bonus
        return max(-1.0, min(1.0, raw))

    # ── Helper ───────────────────────────────────────────────────────

    async def _get_calendar(self) -> EconomicCalendar:
        """Get economic calendar (with caching from MacroAgent if available)."""
        if self._cached_calendar:
            return self._cached_calendar
        calendar = await self._economic_calendar.get_economic_calendar(days_ahead=14)
        self._cached_calendar = calendar
        return calendar

    def update_cached_calendar(self, calendar: EconomicCalendar) -> None:
        """Update cached calendar from MacroAgent."""
        self._cached_calendar = calendar

    def update_cached_sentiment(self, symbol: str, sentiment: SocialSentiment) -> None:
        """Update cached sentiment from SentimentAgent."""
        self._cached_sentiment[symbol] = sentiment


# ═══════════════════════════════════════════════════════════════════════
# 9-FACTOR CONFIRMATION
# ═══════════════════════════════════════════════════════════════════════


def count_confirming_factors(
    technical_scores: dict[str, float],
    fundamental_factors: FundamentalFactors,
    side: str,
    threshold: float = 0.0,
) -> tuple[int, dict[str, bool]]:
    """Count how many of 9 factors confirm the trade direction.

    Args:
        technical_scores: Dict with keys rsi, sr_proximity, volume, trend, multi_timeframe.
        fundamental_factors: FundamentalFactors from FundamentalScorer.
        side: "BUY" or "SELL".
        threshold: Minimum score to count as confirming (default 0.0).

    Returns:
        (count, breakdown_dict)
    """
    all_scores = {
        "rsi": technical_scores.get("rsi", 0.0),
        "sr_proximity": technical_scores.get("sr_proximity", 0.0),
        "volume": technical_scores.get("volume", 0.0),
        "trend": technical_scores.get("trend", 0.0),
        "multi_timeframe": technical_scores.get("multi_timeframe", 0.0),
        "macro": fundamental_factors.macro_score,
        "news": fundamental_factors.news_score,
        "fundamental": fundamental_factors.fundamental_score,
        "sentiment": fundamental_factors.sentiment_score,
    }

    breakdown: dict[str, bool] = {}
    count = 0

    for name, score in all_scores.items():
        if side == "BUY":
            confirms = score > threshold
        else:  # SELL
            confirms = score < -threshold

        breakdown[name] = confirms
        if confirms:
            count += 1

    return count, breakdown
