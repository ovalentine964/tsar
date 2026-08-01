"""Tests for the News Gatekeeper Agent."""

from __future__ import annotations

import time
import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.agents.news_gatekeeper import (
    GatekeeperDecision,
    NewsGatekeeper,
    VetoLevel,
    VetoRecord,
    _severity_rank,
)
from src.tools.news_classifier import NewsCategory, NewsSeverity


@pytest.fixture
def gatekeeper_config() -> dict:
    return {
        "news_gatekeeper": {
            "veto_durations": {
                "emergency": 60,
                "symbol_block": 30,
                "entry_block": 15,
                "alert": 5,
            },
            "velocity": {
                "avalanche_threshold": 5,
                "avalanche_window_minutes": 60,
                "silence_threshold_hours": 24,
                "sentiment_shift_threshold": 0.3,
            },
        },
    }


@pytest.fixture
def gatekeeper(gatekeeper_config: dict) -> NewsGatekeeper:
    gk = NewsGatekeeper(config=gatekeeper_config, trading_mode="paper")
    # Mock the publish_event to capture calls
    gk.publish_event = AsyncMock()
    return gk


class TestVetoRecord:
    """Test VetoRecord dataclass."""

    def test_active_veto(self):
        veto = VetoRecord(
            veto_id="test_1",
            symbol="BTC",
            level=VetoLevel.EMERGENCY,
            reason="Test",
            category=NewsCategory.EXCHANGE_COMPROMISE,
            severity=NewsSeverity.CRITICAL,
            issued_at=time.time(),
            expires_at=time.time() + 3600,
        )
        assert veto.is_active
        assert veto.remaining_seconds > 3500

    def test_expired_veto(self):
        veto = VetoRecord(
            veto_id="test_2",
            symbol="BTC",
            level=VetoLevel.ALERT,
            reason="Test",
            category=NewsCategory.MARKET_ANALYSIS,
            severity=NewsSeverity.MEDIUM,
            issued_at=time.time() - 600,
            expires_at=time.time() - 1,
        )
        assert not veto.is_active
        assert veto.remaining_seconds == 0

    def test_overridden_veto(self):
        veto = VetoRecord(
            veto_id="test_3",
            symbol="BTC",
            level=VetoLevel.EMERGENCY,
            reason="Test",
            category=NewsCategory.EXCHANGE_COMPROMISE,
            severity=NewsSeverity.CRITICAL,
            issued_at=time.time(),
            expires_at=time.time() + 3600,
            override_requested=True,
            override_approved=True,
        )
        assert not veto.is_active


class TestTradeAllowedCheck:
    """Test the check_trade_allowed API."""

    def test_no_vetoes_allows_trade(self, gatekeeper: NewsGatekeeper):
        decision = gatekeeper.check_trade_allowed("BTC/USDT", "buy")
        assert decision.allowed
        assert decision.veto_level == VetoLevel.CLEAR
        assert decision.reason == "No active news vetoes"

    def test_emergency_veto_blocks_all(self, gatekeeper: NewsGatekeeper):
        # Manually inject an emergency veto
        veto = VetoRecord(
            veto_id="emergency_1",
            symbol="ALL",
            level=VetoLevel.EMERGENCY,
            reason="Exchange hack detected",
            category=NewsCategory.EXCHANGE_COMPROMISE,
            severity=NewsSeverity.CRITICAL,
            issued_at=time.time(),
            expires_at=time.time() + 3600,
        )
        gatekeeper._active_vetoes["emergency_1"] = veto
        gatekeeper._global_vetoes.append("emergency_1")

        # Any symbol should be blocked
        decision = gatekeeper.check_trade_allowed("BTC/USDT", "buy")
        assert not decision.allowed
        assert decision.veto_level == VetoLevel.EMERGENCY

        decision2 = gatekeeper.check_trade_allowed("ETH/USDT", "sell")
        assert not decision2.allowed

    def test_symbol_veto_blocks_symbol(self, gatekeeper: NewsGatekeeper):
        # Inject symbol-specific veto
        veto = VetoRecord(
            veto_id="symbol_1",
            symbol="BTC",
            level=VetoLevel.SYMBOL_BLOCK,
            reason="BTC whale movement",
            category=NewsCategory.WHALE_MOVEMENT,
            severity=NewsSeverity.HIGH,
            issued_at=time.time(),
            expires_at=time.time() + 1800,
        )
        gatekeeper._active_vetoes["symbol_1"] = veto
        gatekeeper._symbol_vetoes["BTC"] = ["symbol_1"]

        # BTC should be blocked
        decision = gatekeeper.check_trade_allowed("BTC/USDT", "buy")
        assert not decision.allowed

        # ETH should be allowed
        decision2 = gatekeeper.check_trade_allowed("ETH/USDT", "buy")
        assert decision2.allowed

    def test_expired_veto_allows_trade(self, gatekeeper: NewsGatekeeper):
        # Inject expired veto
        veto = VetoRecord(
            veto_id="expired_1",
            symbol="ALL",
            level=VetoLevel.EMERGENCY,
            reason="Old hack news",
            category=NewsCategory.EXCHANGE_COMPROMISE,
            severity=NewsSeverity.CRITICAL,
            issued_at=time.time() - 7200,
            expires_at=time.time() - 1,  # Already expired
        )
        gatekeeper._active_vetoes["expired_1"] = veto
        gatekeeper._global_vetoes.append("expired_1")

        decision = gatekeeper.check_trade_allowed("BTC/USDT", "buy")
        assert decision.allowed  # Expired veto doesn't block

    def test_override_veto_allows_trade(self, gatekeeper: NewsGatekeeper):
        veto = VetoRecord(
            veto_id="override_1",
            symbol="ALL",
            level=VetoLevel.EMERGENCY,
            reason="False alarm",
            category=NewsCategory.EXCHANGE_COMPROMISE,
            severity=NewsSeverity.CRITICAL,
            issued_at=time.time(),
            expires_at=time.time() + 3600,
        )
        gatekeeper._active_vetoes["override_1"] = veto
        gatekeeper._global_vetoes.append("override_1")

        # Override
        result = gatekeeper.override_veto("override_1", "False alarm confirmed")
        assert result

        decision = gatekeeper.check_trade_allowed("BTC/USDT", "buy")
        assert decision.allowed


class TestVetoExpiry:
    """Test automatic veto expiry."""

    def test_expire_removes_old_vetoes(self, gatekeeper: NewsGatekeeper):
        # Add expired veto
        veto = VetoRecord(
            veto_id="old_1",
            symbol="ALL",
            level=VetoLevel.ALERT,
            reason="Old alert",
            category=NewsCategory.MARKET_ANALYSIS,
            severity=NewsSeverity.MEDIUM,
            issued_at=time.time() - 600,
            expires_at=time.time() - 1,
        )
        gatekeeper._active_vetoes["old_1"] = veto
        gatekeeper._global_vetoes.append("old_1")

        gatekeeper._expire_vetoes()

        assert "old_1" not in gatekeeper._active_vetoes
        assert "old_1" not in gatekeeper._global_vetoes

    def test_expire_keeps_active_vetoes(self, gatekeeper: NewsGatekeeper):
        veto = VetoRecord(
            veto_id="active_1",
            symbol="ALL",
            level=VetoLevel.EMERGENCY,
            reason="Active emergency",
            category=NewsCategory.EXCHANGE_COMPROMISE,
            severity=NewsSeverity.CRITICAL,
            issued_at=time.time(),
            expires_at=time.time() + 3600,
        )
        gatekeeper._active_vetoes["active_1"] = veto
        gatekeeper._global_vetoes.append("active_1")

        gatekeeper._expire_vetoes()

        assert "active_1" in gatekeeper._active_vetoes


class TestDeduplication:
    """Test veto deduplication."""

    def test_no_duplicate_vetoes(self, gatekeeper: NewsGatekeeper):
        """Same category+symbol should not create duplicate vetoes."""
        # First veto
        veto1 = VetoRecord(
            veto_id="v1",
            symbol="BTC",
            level=VetoLevel.SYMBOL_BLOCK,
            reason="Whale movement",
            category=NewsCategory.WHALE_MOVEMENT,
            severity=NewsSeverity.HIGH,
            issued_at=time.time(),
            expires_at=time.time() + 1800,
        )
        gatekeeper._active_vetoes["v1"] = veto1
        gatekeeper._symbol_vetoes["BTC"] = ["v1"]

        # Find existing veto for same category
        existing = gatekeeper._find_active_veto("BTC", NewsCategory.WHALE_MOVEMENT)
        assert existing is not None
        assert existing.veto_id == "v1"


class TestSeverityRank:
    """Test severity ranking."""

    def test_critical_highest(self):
        assert _severity_rank(NewsSeverity.CRITICAL) > _severity_rank(NewsSeverity.HIGH)

    def test_high_above_medium(self):
        assert _severity_rank(NewsSeverity.HIGH) > _severity_rank(NewsSeverity.MEDIUM)

    def test_medium_above_low(self):
        assert _severity_rank(NewsSeverity.MEDIUM) > _severity_rank(NewsSeverity.LOW)


class TestSentimentComputation:
    """Test news sentiment computation for SQF integration."""

    def test_no_classifications_returns_zero(self, gatekeeper: NewsGatekeeper):
        sentiment = gatekeeper.get_news_sentiment_for_symbol("BTC")
        assert sentiment == 0.0

    def test_decision_includes_sentiment(self, gatekeeper: NewsGatekeeper):
        decision = gatekeeper.check_trade_allowed("BTC/USDT")
        assert hasattr(decision, "news_sentiment")
        assert -1.0 <= decision.news_sentiment <= 1.0

    def test_decision_includes_velocity_action(self, gatekeeper: NewsGatekeeper):
        decision = gatekeeper.check_trade_allowed("BTC/USDT")
        assert hasattr(decision, "velocity_action")
        assert decision.velocity_action in [
            "NORMAL", "ALERT", "VETO", "AMPLIFY", "INVESTIGATE",
        ]
