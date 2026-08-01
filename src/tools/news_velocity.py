"""
TSAR — News Velocity Detector.

Detects rapid changes in news flow that signal market-moving events:
  - Avalanche: 5+ articles in 1h with same sentiment direction
  - Silence: No news for 24h during active market hours
  - Sentiment Shift: Rapid sentiment change (>0.3 in 30 minutes)
  - Source Divergence: Single-source story gaining traction

Velocity detection is the early-warning system between raw news
ingestion and the NewsGatekeeper decision engine.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class VelocityMetrics:
    """Raw velocity metrics for a time window."""

    articles_count: int
    window_minutes: int
    articles_per_hour: float
    bullish_count: int
    bearish_count: int
    neutral_count: int
    avg_sentiment: float
    sentiment_std: float
    unique_sources: int
    oldest_article_minutes: int
    newest_article_minutes: int


@dataclass(frozen=True)
class AvalancheSignal:
    """Detected news avalanche."""

    detected: bool
    direction: str = ""        # "bullish", "bearish", "mixed"
    severity: str = ""         # "emergency", "opportunity", "watch"
    article_count: int = 0
    window_minutes: int = 0
    avg_sentiment: float = 0.0
    unique_sources: int = 0
    action: str = ""           # "VETO_ALL", "AMPLIFY_SIGNAL", "MONITOR"
    description: str = ""


@dataclass(frozen=True)
class SilenceSignal:
    """Detected news silence."""

    detected: bool
    hours_silent: float = 0.0
    is_market_hours: bool = False
    action: str = ""           # "INVESTIGATE", "MONITOR"
    description: str = ""


@dataclass(frozen=True)
class SentimentShiftSignal:
    """Detected rapid sentiment shift."""

    detected: bool
    shift_magnitude: float = 0.0
    direction: str = ""        # "positive", "negative"
    window_minutes: int = 0
    action: str = ""
    description: str = ""


@dataclass(frozen=True)
class NewsVelocityReport:
    """Complete velocity analysis report."""

    symbol: str
    metrics: VelocityMetrics
    avalanche: AvalancheSignal
    silence: SilenceSignal
    sentiment_shift: SentimentShiftSignal
    is_unusual: bool
    recommended_action: str    # "NORMAL", "ALERT", "VETO", "INVESTIGATE"
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class VelocityConfig:
    """Configuration for velocity detection thresholds."""

    # Avalanche detection
    avalanche_threshold: int = 5          # Min articles for avalanche
    avalanche_window_minutes: int = 60    # Time window
    avalanche_min_sources: int = 2        # Min unique sources

    # Silence detection
    silence_threshold_hours: float = 24.0  # Hours of no news
    silence_market_hours_only: bool = True

    # Sentiment shift
    shift_threshold: float = 0.3          # Min sentiment change
    shift_window_minutes: int = 30        # Time window

    # Normal ranges (for "unusual" detection)
    normal_articles_per_hour_low: float = 1.0
    normal_articles_per_hour_high: float = 10.0
    normal_source_diversity: int = 3      # Min sources for "normal"


# ═══════════════════════════════════════════════════════════════════════
# VELOCITY DETECTOR
# ═══════════════════════════════════════════════════════════════════════


class NewsVelocityDetector:
    """Detect unusual patterns in news flow velocity.

    Analyzes the rate, direction, and diversity of news publication
    to identify market-moving events before they fully unfold.
    """

    def __init__(self, config: VelocityConfig | None = None) -> None:
        self._config = config or VelocityConfig()

    def analyze(
        self,
        items: list[dict[str, Any]],
        symbol: str = "GENERAL",
    ) -> NewsVelocityReport:
        """Analyze news velocity from a list of classified news items.

        Args:
            items: List of dicts with keys: sentiment, source, published_at,
                   age_minutes, severity.
            symbol: Asset symbol being analyzed.

        Returns:
            NewsVelocityReport with all velocity signals.
        """
        if not items:
            return self._empty_report(symbol)

        # Compute raw metrics
        metrics = self._compute_metrics(items)

        # Run detectors
        avalanche = self._detect_avalanche(items, metrics)
        silence = self._detect_silence(items, metrics)
        shift = self._detect_sentiment_shift(items, metrics)

        # Determine if unusual
        is_unusual = (
            avalanche.detected
            or silence.detected
            or shift.detected
            or metrics.articles_per_hour > self._config.normal_articles_per_hour_high
            or metrics.articles_per_hour < self._config.normal_articles_per_hour_low
            or metrics.unique_sources < self._config.normal_source_diversity
        )

        # Recommended action
        action = self._determine_action(avalanche, silence, shift)

        return NewsVelocityReport(
            symbol=symbol,
            metrics=metrics,
            avalanche=avalanche,
            silence=silence,
            sentiment_shift=shift,
            is_unusual=is_unusual,
            recommended_action=action,
            timestamp=datetime.now(UTC),
        )

    # ── Metric Computation ───────────────────────────────────────────

    def _compute_metrics(self, items: list[dict[str, Any]]) -> VelocityMetrics:
        """Compute raw velocity metrics from news items."""
        now = datetime.now(UTC)

        ages = []
        sentiments = []
        sources = set()
        bullish = 0
        bearish = 0
        neutral = 0

        for item in items:
            # Age in minutes
            age = item.get("age_minutes")
            if age is None:
                pub = item.get("published_at")
                if isinstance(pub, datetime):
                    age = (now - pub).total_seconds() / 60
                else:
                    age = 999  # Unknown age
            ages.append(age)

            # Sentiment
            sent = item.get("sentiment", 0.0)
            sentiments.append(sent)
            if sent > 0.1:
                bullish += 1
            elif sent < -0.1:
                bearish += 1
            else:
                neutral += 1

            # Source
            sources.add(item.get("source", "Unknown"))

        # Window: consider items within the avalanche window
        window = self._config.avalanche_window_minutes
        in_window = [a for a in ages if a <= window]
        window_count = len(in_window)

        # Articles per hour
        if window > 0 and window_count > 0:
            articles_per_hour = window_count / (window / 60)
        else:
            articles_per_hour = 0.0

        # Sentiment stats
        avg_sent = sum(sentiments) / len(sentiments) if sentiments else 0.0
        if len(sentiments) > 1:
            variance = sum((s - avg_sent) ** 2 for s in sentiments) / len(sentiments)
            std = variance ** 0.5
        else:
            std = 0.0

        return VelocityMetrics(
            articles_count=len(items),
            window_minutes=window,
            articles_per_hour=round(articles_per_hour, 2),
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            avg_sentiment=round(avg_sent, 4),
            sentiment_std=round(std, 4),
            unique_sources=len(sources),
            oldest_article_minutes=int(max(ages)) if ages else 0,
            newest_article_minutes=int(min(ages)) if ages else 0,
        )

    # ── Avalanche Detection ──────────────────────────────────────────

    def _detect_avalanche(
        self,
        items: list[dict[str, Any]],
        metrics: VelocityMetrics,
    ) -> AvalancheSignal:
        """Detect news avalanche: rapid accumulation of same-direction news.

        Triggers:
          - N+ articles within window with same sentiment direction
          - At least M unique sources (prevents single-source manipulation)
        """
        threshold = self._config.avalanche_threshold
        window = self._config.avalanche_window_minutes
        min_sources = self._config.avalanche_min_sources

        # Count directional articles in window
        in_window = [
            i for i in items
            if i.get("age_minutes", 999) <= window
        ]

        if len(in_window) < threshold:
            return AvalancheSignal(detected=False)

        bullish = [i for i in in_window if i.get("sentiment", 0) > 0.2]
        bearish = [i for i in in_window if i.get("sentiment", 0) < -0.2]

        # Check source diversity for each direction
        bull_sources = {i.get("source", "") for i in bullish}
        bear_sources = {i.get("source", "") for i in bearish}

        # Bearish avalanche → EMERGENCY
        if len(bearish) >= threshold and len(bear_sources) >= min_sources:
            avg_sent = sum(i.get("sentiment", 0) for i in bearish) / len(bearish)
            return AvalancheSignal(
                detected=True,
                direction="bearish",
                severity="emergency",
                article_count=len(bearish),
                window_minutes=window,
                avg_sentiment=round(avg_sent, 4),
                unique_sources=len(bear_sources),
                action="VETO_ALL",
                description=(
                    f"Bearish avalanche: {len(bearish)} negative articles "
                    f"from {len(bear_sources)} sources in {window}min"
                ),
            )

        # Bullish avalanche → OPPORTUNITY
        if len(bullish) >= threshold and len(bull_sources) >= min_sources:
            avg_sent = sum(i.get("sentiment", 0) for i in bullish) / len(bullish)
            return AvalancheSignal(
                detected=True,
                direction="bullish",
                severity="opportunity",
                article_count=len(bullish),
                window_minutes=window,
                avg_sentiment=round(avg_sent, 4),
                unique_sources=len(bull_sources),
                action="AMPLIFY_SIGNAL",
                description=(
                    f"Bullish avalanche: {len(bullish)} positive articles "
                    f"from {len(bull_sources)} sources in {window}min"
                ),
            )

        return AvalancheSignal(detected=False)

    # ── Silence Detection ────────────────────────────────────────────

    def _detect_silence(
        self,
        items: list[dict[str, Any]],
        metrics: VelocityMetrics,
    ) -> SilenceSignal:
        """Detect news silence: extended period with no news.

        During active market hours, prolonged silence can indicate:
        - Market participants are uncertain (precedes volatility)
        - News is being embargoed (precedes major announcement)
        - API/source issues (false silence)
        """
        threshold_hours = self._config.silence_threshold_hours
        threshold_minutes = threshold_hours * 60

        # Find the most recent article
        newest_age = metrics.newest_article_minutes

        if newest_age < threshold_minutes:
            return SilenceSignal(detected=False)

        # Check if we're in market hours (crypto is 24/7, but
        # traditional market hours affect macro-sensitive assets)
        now = datetime.now(UTC)
        is_market_hours = now.weekday() < 5 and 13 <= now.hour <= 21  # UTC market hours

        if self._config.silence_market_hours_only and not is_market_hours:
            return SilenceSignal(detected=False)

        hours_silent = newest_age / 60

        return SilenceSignal(
            detected=True,
            hours_silent=round(hours_silent, 1),
            is_market_hours=is_market_hours,
            action="INVESTIGATE",
            description=(
                f"News silence: no articles for {hours_silent:.1f}h "
                f"({'during' if is_market_hours else 'outside'} market hours)"
            ),
        )

    # ── Sentiment Shift Detection ────────────────────────────────────

    def _detect_sentiment_shift(
        self,
        items: list[dict[str, Any]],
        metrics: VelocityMetrics,
    ) -> SentimentShiftSignal:
        """Detect rapid sentiment shift.

        A large change in average sentiment over a short period
        indicates a sudden change in market narrative.
        """
        threshold = self._config.shift_threshold
        window = self._config.shift_window_minutes

        # Split items into recent and older
        recent = [i for i in items if i.get("age_minutes", 999) <= window]
        older = [i for i in items if i.get("age_minutes", 999) > window]

        if len(recent) < 2 or len(older) < 2:
            return SentimentShiftSignal(detected=False)

        recent_avg = sum(i.get("sentiment", 0) for i in recent) / len(recent)
        older_avg = sum(i.get("sentiment", 0) for i in older) / len(older)

        shift = recent_avg - older_avg

        if abs(shift) < threshold:
            return SentimentShiftSignal(detected=False)

        direction = "positive" if shift > 0 else "negative"
        action = "AMPLIFY_SIGNAL" if shift > 0 else "ALERT"

        return SentimentShiftSignal(
            detected=True,
            shift_magnitude=round(abs(shift), 4),
            direction=direction,
            window_minutes=window,
            action=action,
            description=(
                f"Sentiment shift: {direction} change of {abs(shift):.3f} "
                f"over {window}min (recent={recent_avg:.3f}, older={older_avg:.3f})"
            ),
        )

    # ── Action Determination ─────────────────────────────────────────

    @staticmethod
    def _determine_action(
        avalanche: AvalancheSignal,
        silence: SilenceSignal,
        shift: SentimentShiftSignal,
    ) -> str:
        """Determine recommended action from all velocity signals."""
        # Priority: avalanche > shift > silence
        if avalanche.detected and avalanche.severity == "emergency":
            return "VETO"
        if avalanche.detected and avalanche.severity == "opportunity":
            return "AMPLIFY"
        if shift.detected and shift.direction == "negative":
            return "ALERT"
        if silence.detected:
            return "INVESTIGATE"
        if shift.detected and shift.direction == "positive":
            return "AMPLIFY"
        return "NORMAL"

    # ── Helpers ──────────────────────────────────────────────────────

    def _empty_report(self, symbol: str) -> NewsVelocityReport:
        """Return an empty report when no data is available."""
        empty_metrics = VelocityMetrics(
            articles_count=0,
            window_minutes=0,
            articles_per_hour=0.0,
            bullish_count=0,
            bearish_count=0,
            neutral_count=0,
            avg_sentiment=0.0,
            sentiment_std=0.0,
            unique_sources=0,
            oldest_article_minutes=0,
            newest_article_minutes=0,
        )
        return NewsVelocityReport(
            symbol=symbol,
            metrics=empty_metrics,
            avalanche=AvalancheSignal(detected=False),
            silence=SilenceSignal(detected=False),
            sentiment_shift=SentimentShiftSignal(detected=False),
            is_unusual=False,
            recommended_action="NORMAL",
            timestamp=datetime.now(UTC),
        )
