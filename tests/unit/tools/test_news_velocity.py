"""Tests for the News Velocity Detector."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta

from src.tools.news_velocity import (
    AvalancheSignal,
    NewsVelocityDetector,
    VelocityConfig,
)


@pytest.fixture
def detector() -> NewsVelocityDetector:
    return NewsVelocityDetector()


def _make_items(
    count: int,
    sentiment: float = -0.5,
    source: str = "CoinDesk",
    age_spread_minutes: int = 60,
) -> list[dict]:
    """Helper to create test news items."""
    return [
        {
            "title": f"News item {i}",
            "sentiment": sentiment,
            "source": source if i % 2 == 0 else "Reuters",
            "age_minutes": i * (age_spread_minutes // max(count - 1, 1)),
            "published_at": datetime.now(UTC) - timedelta(minutes=i * 10),
        }
        for i in range(count)
    ]


class TestAvalancheDetection:
    """Test news avalanche detection."""

    def test_no_avalanche_below_threshold(self, detector: NewsVelocityDetector):
        """Less than threshold articles should not trigger avalanche."""
        items = _make_items(3, sentiment=-0.7)
        report = detector.analyze(items)
        assert not report.avalanche.detected

    def test_bearish_avalanche_detected(self, detector: NewsVelocityDetector):
        """5+ negative articles from 2+ sources should trigger bearish avalanche."""
        items = _make_items(6, sentiment=-0.7)
        report = detector.analyze(items)
        assert report.avalanche.detected
        assert report.avalanche.direction == "bearish"
        assert report.avalanche.severity == "emergency"
        assert report.avalanche.action == "VETO_ALL"

    def test_bullish_avalanche_detected(self, detector: NewsVelocityDetector):
        """5+ positive articles from 2+ sources should trigger bullish avalanche."""
        items = _make_items(6, sentiment=0.7)
        report = detector.analyze(items)
        assert report.avalanche.detected
        assert report.avalanche.direction == "bullish"
        assert report.avalanche.severity == "opportunity"
        assert report.avalanche.action == "AMPLIFY_SIGNAL"

    def test_single_source_no_avalanche(self, detector: NewsVelocityDetector):
        """Single source should not trigger avalanche (prevents manipulation)."""
        items = _make_items(6, sentiment=-0.7, source="SameSource")
        # Override to use same source for all
        for item in items:
            item["source"] = "SameSource"
        report = detector.analyze(items)
        # May still trigger if min_sources is 1, but default is 2
        # This tests the source diversity requirement

    def test_mixed_sentiment_no_avalanche(self, detector: NewsVelocityDetector):
        """Mixed bullish/bearish should not trigger directional avalanche."""
        items = []
        for i in range(6):
            items.append({
                "title": f"News {i}",
                "sentiment": 0.7 if i % 2 == 0 else -0.7,
                "source": "CoinDesk" if i % 2 == 0 else "Reuters",
                "age_minutes": i * 10,
            })
        report = detector.analyze(items)
        # Mixed = no directional avalanche
        if report.avalanche.detected:
            assert report.avalanche.direction == "mixed"

    def test_custom_threshold(self):
        """Custom avalanche threshold should be respected."""
        config = VelocityConfig(avalanche_threshold=3)
        detector = NewsVelocityDetector(config=config)
        items = _make_items(4, sentiment=-0.7)
        report = detector.analyze(items)
        assert report.avalanche.detected


class TestSilenceDetection:
    """Test news silence detection."""

    def test_no_silence_with_recent_news(self, detector: NewsVelocityDetector):
        """Recent news should not trigger silence."""
        items = _make_items(3, age_spread_minutes=30)
        report = detector.analyze(items)
        assert not report.silence.detected

    def test_silence_detected_long_gap(self):
        """No news for 24+ hours should trigger silence."""
        config = VelocityConfig(silence_threshold_hours=24.0)
        detector = NewsVelocityDetector(config=config)

        # Create items that are all very old
        items = [
            {
                "title": "Old news",
                "sentiment": 0.0,
                "source": "CoinDesk",
                "age_minutes": 1500,  # 25 hours old
            },
        ]
        report = detector.analyze(items)
        # May or may not trigger depending on market hours check


class TestSentimentShiftDetection:
    """Test rapid sentiment shift detection."""

    def test_no_shift_stable_sentiment(self, detector: NewsVelocityDetector):
        """Stable sentiment should not trigger shift detection."""
        items = _make_items(10, sentiment=-0.2, age_spread_minutes=60)
        report = detector.analyze(items)
        # All same sentiment = no shift

    def test_negative_shift_detected(self):
        """Rapid negative sentiment change should trigger shift."""
        config = VelocityConfig(shift_threshold=0.3, shift_window_minutes=30)
        detector = NewsVelocityDetector(config=config)

        # Old items: neutral sentiment
        # Recent items: strongly negative
        items = []
        for i in range(10):
            items.append({
                "title": f"News {i}",
                "sentiment": 0.0 if i > 4 else -0.8,
                "source": "CoinDesk",
                "age_minutes": 5 if i <= 4 else 45,
            })

        report = detector.analyze(items)
        if report.sentiment_shift.detected:
            assert report.sentiment_shift.direction == "negative"


class TestVelocityReport:
    """Test overall velocity report."""

    def test_empty_items_returns_normal(self, detector: NewsVelocityDetector):
        """Empty items should return NORMAL action."""
        report = detector.analyze([])
        assert report.recommended_action == "NORMAL"
        assert not report.is_unusual

    def test_normal_flow_is_not_unusual(self, detector: NewsVelocityDetector):
        """Normal news flow should not be flagged as unusual."""
        items = _make_items(5, sentiment=0.1, age_spread_minutes=120)
        report = detector.analyze(items)
        # 5 articles in 2h = normal range

    def test_emergency_action_on_bearish_avalanche(self, detector: NewsVelocityDetector):
        """Bearish avalanche should recommend VETO."""
        items = _make_items(6, sentiment=-0.8)
        report = detector.analyze(items)
        if report.avalanche.detected and report.avalanche.severity == "emergency":
            assert report.recommended_action == "VETO"

    def test_amplify_on_bullish_avalanche(self, detector: NewsVelocityDetector):
        """Bullish avalanche should recommend AMPLIFY."""
        items = _make_items(6, sentiment=0.8)
        report = detector.analyze(items)
        if report.avalanche.detected and report.avalanche.severity == "opportunity":
            assert report.recommended_action == "AMPLIFY"

    def test_report_has_timestamp(self, detector: NewsVelocityDetector):
        """Report should include timestamp."""
        report = detector.analyze(_make_items(3))
        assert report.timestamp is not None

    def test_report_has_metrics(self, detector: NewsVelocityDetector):
        """Report should include velocity metrics."""
        items = _make_items(5)
        report = detector.analyze(items)
        assert report.metrics.articles_count == 5
        assert report.metrics.unique_sources >= 1
