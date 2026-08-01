"""
Tests for Trade Manager — Entry/Exit Optimization System.

Tests cover:
  1. Session timing gates
  2. News proximity/blackout
  3. Trailing stop stages
  4. Partial exit scheduling
  5. Break-even triggers
  6. Time stops
  7. Stale trade detection
  8. Regime-change exits
  9. Weekend management
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.trade_manager import (
    ExitReason,
    ManagedPosition,
    NewsProximity,
    SessionTiming,
    TradeAction,
    TradeManager,
    TrailingStage,
)


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def buy_position() -> ManagedPosition:
    """Standard buy position for testing."""
    return ManagedPosition(
        position_id="test-001",
        symbol="BTC/USDT",
        side="buy",
        entry_price=50000.0,
        quantity=0.1,
        remaining_quantity=0.1,
        stop_loss=49250.0,  # 1.5% stop
        take_profit=51500.0,  # 3% TP (2:1 R:R)
        atr=500.0,
        entry_time=datetime.now(UTC) - timedelta(hours=1),
        strategy="mean_reversion",
    )


@pytest.fixture
def sell_position() -> ManagedPosition:
    """Standard sell position for testing."""
    return ManagedPosition(
        position_id="test-002",
        symbol="BTC/USDT",
        side="sell",
        entry_price=50000.0,
        quantity=0.1,
        remaining_quantity=0.1,
        stop_loss=50750.0,  # 1.5% stop
        take_profit=48500.0,  # 3% TP
        atr=500.0,
        entry_time=datetime.now(UTC) - timedelta(hours=1),
        strategy="mean_reversion",
    )


@pytest.fixture
def trade_manager() -> TradeManager:
    """Trade manager instance for testing."""
    config = {
        "trade_manager": {
            "trailing_enabled": True,
            "partial_exits_enabled": True,
            "time_stop_enabled": True,
            "regime_exit_enabled": True,
            "weekend_close_enabled": True,
        }
    }
    return TradeManager(config=config, trading_mode="paper")


# ═══════════════════════════════════════════════════════════════════════
# SESSION TIMING TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestSessionTiming:
    """Test session timing gates."""

    def test_session_quality_varies_by_time(self):
        """Session quality should vary based on time of day."""
        quality = SessionTiming.get_session_quality()
        assert 0.0 <= quality <= 1.0

    def test_is_entry_allowed_returns_tuple(self):
        """is_entry_allowed returns (bool, str) tuple."""
        result = SessionTiming.is_entry_allowed()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_should_close_for_weekend_returns_tuple(self):
        """should_close_for_weekend returns (bool, str) tuple."""
        result = SessionTiming.should_close_for_weekend()
        assert isinstance(result, tuple)
        assert len(result) == 2

    @patch("src.agents.trade_manager.datetime")
    def test_friday_evening_closes(self, mock_dt):
        """Friday after 20:00 UTC should trigger weekend close."""
        # Mock Friday 21:00 UTC
        friday = datetime(2026, 7, 31, 21, 0, 0, tzinfo=UTC)
        mock_dt.now.return_value = friday
        mock_dt.UTC = UTC

        should_close, reason = SessionTiming.should_close_for_weekend()
        assert should_close is True
        assert "Friday" in reason or "weekend" in reason.lower()

    @patch("src.agents.trade_manager.datetime")
    def test_tuesday_no_weekend_close(self, mock_dt):
        """Tuesday should not trigger weekend close."""
        tuesday = datetime(2026, 8, 4, 14, 0, 0, tzinfo=UTC)
        mock_dt.now.return_value = tuesday
        mock_dt.UTC = UTC

        should_close, reason = SessionTiming.should_close_for_weekend()
        assert should_close is False


# ═══════════════════════════════════════════════════════════════════════
# NEWS PROXIMITY TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestNewsProximity:
    """Test news proximity gates."""

    def test_no_calendar_returns_not_blocked(self):
        """No calendar data should not block trading."""
        blocked, reason, mult = NewsProximity.check_news_blackout(None)
        assert blocked is False
        assert mult == 1.0

    def test_should_exit_for_news_returns_tuple(self):
        """should_exit_for_news returns (bool, str) tuple."""
        result = NewsProximity.should_exit_for_news(None, 1.5)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_blackout_windows_defined(self):
        """Blackout windows should be defined for all impact levels."""
        assert "critical" in NewsProximity.BLACKOUT_WINDOWS
        assert "high" in NewsProximity.BLACKOUT_WINDOWS
        assert "medium" in NewsProximity.BLACKOUT_WINDOWS
        assert NewsProximity.BLACKOUT_WINDOWS["critical"] > NewsProximity.BLACKOUT_WINDOWS["high"]


# ═══════════════════════════════════════════════════════════════════════
# TRAILING STOP TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestTrailingStop:
    """Test trailing stop logic."""

    def test_initial_stage(self, buy_position):
        """New position should be in INITIAL stage."""
        assert buy_position.trailing_stage == TrailingStage.INITIAL

    def test_no_trailing_below_trigger_rr(self, trade_manager, buy_position):
        """Should not trail below trigger R:R."""
        # Price slightly above entry (low R:R)
        action = trade_manager._check_trailing_stop(
            buy_position, current_price=50200.0, current_rr=0.27
        )
        assert action is None

    def test_breakeven_at_1r(self, trade_manager, buy_position):
        """Should trigger break-even at 1:1 R:R."""
        # At 1:1 R:R: reward = risk = 750
        current_price = 50000.0 + 750.0  # 50750
        action = trade_manager._check_trailing_stop(
            buy_position, current_price=current_price, current_rr=1.0
        )
        assert action is not None
        assert action.action == "update_stop"
        # Stop should be near entry (break-even)
        assert action.new_stop >= 49950  # Within break-even buffer

    def test_trailing_at_1_5r(self, trade_manager, buy_position):
        """Should start trailing at 1.5:1 R:R."""
        current_price = 50000.0 + 750.0 * 1.5  # 51125
        action = trade_manager._check_trailing_stop(
            buy_position, current_price=current_price, current_rr=1.5
        )
        assert action is not None
        assert buy_position.trailing_stage == TrailingStage.TRAILING

    def test_tight_trail_at_2r(self, trade_manager, buy_position):
        """Should tighten trail at 2:1 R:R."""
        buy_position.highest_price = 51500.0
        current_price = 51500.0
        action = trade_manager._check_trailing_stop(
            buy_position, current_price=current_price, current_rr=2.0
        )
        assert action is not None
        assert buy_position.trailing_stage == TrailingStage.TIGHT_TRAIL

    def test_sell_position_trailing(self, trade_manager, sell_position):
        """Trailing should work for sell positions."""
        # Price drops in our favor
        current_price = 49000.0  # 1000 profit on sell
        action = trade_manager._check_trailing_stop(
            sell_position, current_price=current_price, current_rr=1.33
        )
        # At RR=1.33, breakeven trigger (1.0) is met, so we get a break-even action
        assert action is not None
        assert action.action == "update_stop"
        # Stop should move toward entry (break-even for sell)
        assert action.new_stop <= sell_position.entry_price * 1.001

    def test_stop_never_moves_wrong_direction(self, trade_manager, buy_position):
        """Stop should never move further from price (only tighten)."""
        # First, set a tight stop
        buy_position.stop_loss = 50500.0

        # Try to trail with lower price (should not move stop down)
        action = trade_manager._check_trailing_stop(
            buy_position, current_price=50100.0, current_rr=0.13
        )
        # Either no action or stop stays above 50500
        if action:
            assert action.new_stop >= 50500.0


# ═══════════════════════════════════════════════════════════════════════
# PARTIAL EXIT TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestPartialExit:
    """Test partial exit scheduling."""

    def test_no_partial_exit_below_level(self, trade_manager, buy_position):
        """Should not take partial exit below target R:R."""
        action = trade_manager._check_partial_exit(
            buy_position, current_price=50200.0, current_rr=0.27
        )
        assert action is None

    def test_first_partial_at_1r(self, trade_manager, buy_position):
        """Should take 40% partial exit at 1:1 R:R."""
        current_price = 50750.0  # 1:1 R:R
        action = trade_manager._check_partial_exit(
            buy_position, current_price=current_price, current_rr=1.0
        )
        assert action is not None
        assert action.action == "partial_exit"
        assert action.reason == ExitReason.PARTIAL_EXIT
        # Note: partial_exits_taken is incremented by _execute_action, not _check_partial_exit
        # The check method returns the action; execution handles state updates

    def test_second_partial_at_2r(self, trade_manager, buy_position):
        """Should take 30% partial exit at 2:1 R:R."""
        buy_position.partial_exits_taken = 1  # Simulate first exit already taken
        current_price = 51500.0  # 2:1 R:R
        action = trade_manager._check_partial_exit(
            buy_position, current_price=current_price, current_rr=2.0
        )
        assert action is not None
        # Note: partial_exits_taken is incremented by _execute_action, not _check_partial_exit

    def test_no_more_partials_after_all_taken(self, trade_manager, buy_position):
        """Should not take partial exit after all scheduled exits."""
        buy_position.partial_exits_taken = 3
        action = trade_manager._check_partial_exit(
            buy_position, current_price=52000.0, current_rr=2.67
        )
        assert action is None


# ═══════════════════════════════════════════════════════════════════════
# TIME STOP TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestTimeStop:
    """Test time-based exit logic."""

    def test_no_time_stop_within_limit(self, trade_manager, buy_position):
        """Should not time-stop within strategy time limit."""
        # Position held for 2 hours (limit is 4 for mean_reversion)
        buy_position.entry_time = datetime.now(UTC) - timedelta(hours=2)
        action = trade_manager._check_time_stop(buy_position, current_price=50100.0)
        assert action is None

    def test_time_stop_after_limit(self, trade_manager, buy_position):
        """Should time-stop after strategy time limit."""
        # Position held for 5 hours (limit is 4 for mean_reversion)
        buy_position.entry_time = datetime.now(UTC) - timedelta(hours=5)
        action = trade_manager._check_time_stop(buy_position, current_price=50100.0)
        assert action is not None
        assert action.action == "close"
        assert action.reason == ExitReason.TIME_STOP

    def test_no_time_stop_for_winners(self, trade_manager, buy_position):
        """Should not time-stop profitable positions."""
        buy_position.entry_time = datetime.now(UTC) - timedelta(hours=5)
        # Price 1% above entry (winner)
        action = trade_manager._check_time_stop(buy_position, current_price=50600.0)
        assert action is None


# ═══════════════════════════════════════════════════════════════════════
# STALE TRADE TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestStaleTrade:
    """Test stale trade detection."""

    def test_no_stale_within_hours(self, trade_manager, buy_position):
        """Should not flag as stale within stale_trade_hours."""
        buy_position.entry_time = datetime.now(UTC) - timedelta(hours=2)
        action = trade_manager._check_stale_trade(buy_position, current_price=50100.0)
        assert action is None

    def test_stale_with_no_movement(self, trade_manager, buy_position):
        """Should flag as stale with no price movement."""
        buy_position.entry_time = datetime.now(UTC) - timedelta(hours=5)
        # Price barely moved (0.1%)
        action = trade_manager._check_stale_trade(buy_position, current_price=50050.0)
        assert action is not None
        assert action.reason == ExitReason.STALE_TRADE

    def test_not_stale_with_movement(self, trade_manager, buy_position):
        """Should not flag as stale if price moved enough."""
        buy_position.entry_time = datetime.now(UTC) - timedelta(hours=5)
        # Price moved 1%
        action = trade_manager._check_stale_trade(buy_position, current_price=50500.0)
        assert action is None


# ═══════════════════════════════════════════════════════════════════════
# REGIME CHANGE TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestRegimeChange:
    """Test regime-change exit logic."""

    def test_crisis_closes_all(self, trade_manager, buy_position):
        """Crisis regime should close all positions."""
        action = trade_manager._evaluate_regime_exit(
            buy_position, old_regime="trending", new_regime="crisis"
        )
        assert action is not None
        assert action.action == "close"
        assert action.reason == ExitReason.REGIME_CHANGE

    def test_trending_to_ranging_closes_momentum(self, trade_manager):
        """Trending→Ranging should close momentum positions."""
        pos = ManagedPosition(
            position_id="mom-001",
            symbol="BTC/USDT",
            side="buy",
            entry_price=50000.0,
            quantity=0.1,
            remaining_quantity=0.1,
            stop_loss=49000.0,
            take_profit=52000.0,
            atr=500.0,
            entry_time=datetime.now(UTC),
            strategy="momentum",
        )
        action = trade_manager._evaluate_regime_exit(
            pos, old_regime="trending", new_regime="ranging"
        )
        assert action is not None
        assert action.action == "close"

    def test_trending_to_ranging_keeps_mr(self, trade_manager, buy_position):
        """Trending→Ranging should keep mean reversion positions."""
        action = trade_manager._evaluate_regime_exit(
            buy_position, old_regime="trending", new_regime="ranging"
        )
        # Mean reversion should be kept (it works in ranges)
        assert action is None

    def test_high_volatility_tightens_stops(self, trade_manager, buy_position):
        """High volatility should tighten stops."""
        action = trade_manager._evaluate_regime_exit(
            buy_position, old_regime="ranging", new_regime="high_volatility"
        )
        assert action is not None
        assert action.action == "update_stop"


# ═══════════════════════════════════════════════════════════════════════
# R:R CALCULATION TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestRiskReward:
    """Test R:R calculation."""

    def test_buy_position_rr(self, trade_manager, buy_position):
        """R:R for buy position at 1:1."""
        # Risk = 50000 - 49250 = 750
        # At 50750: reward = 750, RR = 1.0
        rr = trade_manager._calculate_current_rr(buy_position, 50750.0)
        assert abs(rr - 1.0) < 0.01

    def test_buy_position_2r(self, trade_manager, buy_position):
        """R:R for buy position at 2:1."""
        # At 51500: reward = 1500, RR = 2.0
        rr = trade_manager._calculate_current_rr(buy_position, 51500.0)
        assert abs(rr - 2.0) < 0.01

    def test_sell_position_rr(self, trade_manager, sell_position):
        """R:R for sell position at 1:1."""
        # Risk = 50750 - 50000 = 750
        # At 49250: reward = 750, RR = 1.0
        rr = trade_manager._calculate_current_rr(sell_position, 49250.0)
        assert abs(rr - 1.0) < 0.01

    def test_losing_position_negative_rr(self, trade_manager, buy_position):
        """Losing position should have negative R:R."""
        rr = trade_manager._calculate_current_rr(buy_position, 49000.0)
        assert rr < 0


# ═══════════════════════════════════════════════════════════════════════
# POSITION REGISTRATION TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestPositionRegistration:
    """Test position registration and management."""

    def test_managed_position_defaults(self, buy_position):
        """ManagedPosition should have sensible defaults."""
        assert buy_position.trailing_stage == TrailingStage.INITIAL
        assert buy_position.breakeven_triggered is False
        assert buy_position.partial_exits_taken == 0
        assert buy_position.risk_per_unit == 750.0  # 50000 - 49250

    def test_partial_exit_levels_calculated(self, buy_position):
        """Partial exit levels should be auto-calculated."""
        assert len(buy_position.partial_exit_levels) == 3
        # At 1:1, 2:1, 3:1 R:R
        assert buy_position.partial_exit_levels[0] == 50750.0  # 1:1
        assert buy_position.partial_exit_levels[1] == 51500.0  # 2:1
        assert buy_position.partial_exit_levels[2] == 52250.0  # 3:1

    def test_sell_partial_exit_levels(self, sell_position):
        """Partial exit levels for sell should be below entry."""
        assert sell_position.partial_exit_levels[0] == 49250.0  # 1:1
        assert sell_position.partial_exit_levels[1] == 48500.0  # 2:1
        assert sell_position.partial_exit_levels[2] == 47750.0  # 3:1


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestIntegration:
    """Integration tests for trade management flow."""

    def test_full_trade_lifecycle_buy(self, trade_manager, buy_position):
        """Test full lifecycle: entry → partial exits → trailing → close."""
        # Register position
        trade_manager._positions[buy_position.position_id] = buy_position

        # Simulate price movement
        # 1. Price moves to 1:1 R:R → partial exit + break-even
        rr = trade_manager._calculate_current_rr(buy_position, 50750.0)
        assert abs(rr - 1.0) < 0.01

        partial = trade_manager._check_partial_exit(buy_position, 50750.0, rr)
        assert partial is not None
        assert partial.action == "partial_exit"

        # 2. Price moves to 2:1 R:R → second partial + trailing
        buy_position.highest_price = 51500.0
        rr = trade_manager._calculate_current_rr(buy_position, 51500.0)
        partial = trade_manager._check_partial_exit(buy_position, 51500.0, rr)
        assert partial is not None

        # 3. Verify trailing stage updated
        trail = trade_manager._check_trailing_stop(buy_position, 51500.0, rr)
        assert trail is not None

    def test_weekend_close_integration(self, trade_manager, buy_position):
        """Test weekend close integration."""
        trade_manager._positions[buy_position.position_id] = buy_position

        # Mock Friday evening
        with patch("src.agents.trade_manager.SessionTiming") as mock_st:
            mock_st.should_close_for_weekend.return_value = (True, "Friday 20:00+ UTC")
            action = trade_manager._check_weekend_close(buy_position)
            assert action is not None
            assert action.action == "close"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
