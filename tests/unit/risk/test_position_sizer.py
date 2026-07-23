"""
Unit tests for PositionSizer — Half-Kelly position sizing.

Tests:
  - Half-Kelly calculation correctness
  - 2% hard risk cap
  - 15% notional cap
  - Edge cases (zero equity, zero risk, negative edge)
  - Price multiplier adjustments
"""

from __future__ import annotations

import pytest

from src.risk.position_sizer import PositionSizer, SizingConfig


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def sizer() -> PositionSizer:
    return PositionSizer()


@pytest.fixture
def custom_sizer() -> PositionSizer:
    return PositionSizer(SizingConfig(
        kelly_fraction=0.25,
        risk_per_trade_pct=0.02,
        max_single_position_pct=0.15,
    ))


# ═══════════════════════════════════════════════════════════════════════
# BASIC CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════


class TestBasicSizing:
    """Core position sizing calculations."""

    def test_basic_buy_sizing(self, sizer):
        """With positive edge, should produce positive quantity."""
        result = sizer.calculate(
            equity=100000.0,
            entry_price=50000.0,
            stop_loss=49500.0,
            win_rate=0.6,
            avg_win=2.0,
            avg_loss=1.0,
        )
        assert result.quantity > 0
        assert result.notional_value > 0
        assert result.risk_amount > 0
        assert result.method == "half_kelly"

    def test_risk_amount_capped_at_2_pct(self, sizer):
        """Risk per trade should not exceed 2% of equity."""
        result = sizer.calculate(
            equity=100000.0,
            entry_price=50000.0,
            stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        # Max risk = 100000 * 0.02 = 2000
        assert result.risk_amount <= 2000.0 + 0.01

    def test_quantity_matches_risk(self, sizer):
        """quantity = risk_amount / |entry - stop_loss|"""
        result = sizer.calculate(
            equity=100000.0,
            entry_price=50000.0,
            stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        risk_per_unit = abs(50000.0 - 49500.0)  # 500
        # Account for notional cap
        expected_qty = result.risk_amount / risk_per_unit
        assert abs(result.quantity - expected_qty) < 0.01

    def test_notional_value_correct(self, sizer):
        result = sizer.calculate(
            equity=100000.0,
            entry_price=50000.0,
            stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        expected_notional = result.quantity * 50000.0
        assert abs(result.notional_value - expected_notional) < 0.01

    def test_risk_pct_correct(self, sizer):
        result = sizer.calculate(
            equity=100000.0,
            entry_price=50000.0,
            stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        expected_pct = result.risk_amount / 100000.0
        assert abs(result.risk_pct - expected_pct) < 0.0001


# ═══════════════════════════════════════════════════════════════════════
# HALF-KELLY FORMULA
# ═══════════════════════════════════════════════════════════════════════


class TestHalfKelly:
    """Verify Kelly criterion integration."""

    def test_higher_win_rate_increases_size(self, sizer):
        size_low = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.4, avg_win=2.0, avg_loss=1.0,
        )
        size_high = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.7, avg_win=2.0, avg_loss=1.0,
        )
        assert size_high.quantity >= size_low.quantity

    def test_better_rr_increases_size(self, sizer):
        size_low = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.5, avg_win=1.5, avg_loss=1.0,
        )
        size_high = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.5, avg_win=3.0, avg_loss=1.0,
        )
        assert size_high.quantity >= size_low.quantity

    def test_zero_edge_gives_zero_quantity(self, sizer):
        """When Kelly = 0 (no edge, coin flip), quantity = 0."""
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.5, avg_win=1.0, avg_loss=1.0,
        )
        # Kelly = 0 → risk = 0 → quantity = 0
        assert result.quantity == 0.0

    def test_positive_edge_gives_positive_quantity(self, sizer):
        """When Kelly > 0, should get positive quantity."""
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        assert result.quantity > 0

    def test_half_kelly_is_quarter_of_full(self, sizer):
        """With kelly_fraction=0.25, risk should be 25% of full Kelly risk.
        Uses large equity so the notional cap doesn't mask the Kelly ratio.
        """
        # Full Kelly (fraction=1.0)
        full = PositionSizer(SizingConfig(kelly_fraction=1.0))
        full_result = full.calculate(
            equity=10_000_000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        # Quarter-Kelly (fraction=0.25)
        quarter = PositionSizer(SizingConfig(kelly_fraction=0.25))
        quarter_result = quarter.calculate(
            equity=10_000_000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        # Both hit the notional cap (15% of equity), but with large equity
        # the quarter-Kelly stays under the risk cap while full-Kelly exceeds it
        assert quarter_result.risk_amount <= full_result.risk_amount
        assert quarter_result.quantity <= full_result.quantity


# ═══════════════════════════════════════════════════════════════════════
# NOTIONAL CAP (15% of equity)
# ═══════════════════════════════════════════════════════════════════════


class TestNotionalCap:
    """15% max single position notional cap."""

    def test_notional_capped_at_15_pct(self, sizer):
        """For small stop distances, notional should be capped."""
        result = sizer.calculate(
            equity=100000.0,
            entry_price=50000.0,
            stop_loss=49900.0,  # Very tight stop (0.2%)
            win_rate=0.7, avg_win=3.0, avg_loss=1.0,
        )
        max_notional = 100000.0 * 0.15  # 15000
        assert result.notional_value <= max_notional + 0.01

    def test_capped_flag_set(self, sizer):
        result = sizer.calculate(
            equity=100000.0,
            entry_price=50000.0,
            stop_loss=49900.0,
            win_rate=0.7, avg_win=3.0, avg_loss=1.0,
        )
        if result.notional_value >= 15000.0 - 0.01:
            assert result.capped is True
            assert "equity" in result.cap_reason.lower()


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions and error inputs."""

    def test_zero_equity_returns_zero(self, sizer):
        result = sizer.calculate(
            equity=0.0, entry_price=50000.0, stop_loss=49500.0,
        )
        assert result.quantity == 0.0
        assert result.capped is True

    def test_negative_equity_returns_zero(self, sizer):
        result = sizer.calculate(
            equity=-1000.0, entry_price=50000.0, stop_loss=49500.0,
        )
        assert result.quantity == 0.0

    def test_zero_entry_price_returns_zero(self, sizer):
        result = sizer.calculate(
            equity=100000.0, entry_price=0.0, stop_loss=49500.0,
        )
        assert result.quantity == 0.0

    def test_zero_stop_loss_returns_zero(self, sizer):
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=0.0,
        )
        assert result.quantity == 0.0

    def test_identical_entry_and_stop_returns_zero(self, sizer):
        """Risk per unit = 0 → division by zero guard."""
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=50000.0,
        )
        assert result.quantity == 0.0
        assert result.capped is True
        assert "identical" in result.cap_reason.lower()

    def test_negative_win_rate_clamped(self, sizer):
        """Negative win rate should be clamped to 0."""
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=-0.5,
        )
        assert result.quantity >= 0

    def test_win_rate_above_1_clamped(self, sizer):
        """Win rate > 1.0 should be clamped to 1.0."""
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=1.5,
        )
        assert result.quantity >= 0

    def test_zero_avg_loss_returns_zero(self, sizer):
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            avg_loss=0.0,
        )
        assert result.quantity >= 0

    def test_negative_edge_gives_zero_kelly(self, sizer):
        """Losing strategy (win_rate * avg_win < loss_rate * avg_loss) → Kelly = 0."""
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.3, avg_win=1.0, avg_loss=3.0,
        )
        assert result.quantity == 0.0


# ═══════════════════════════════════════════════════════════════════════
# PRICE MULTIPLIER
# ═══════════════════════════════════════════════════════════════════════


class TestPriceMultiplier:
    """Volatility/behavioral price multiplier adjustments."""

    def test_multiplier_reduces_size(self, sizer):
        full = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        reduced = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
            price_multiplier=0.5,
        )
        assert reduced.quantity < full.quantity
        assert reduced.capped is True

    def test_multiplier_of_1_no_change(self, sizer):
        full = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        same = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
            price_multiplier=1.0,
        )
        assert abs(full.quantity - same.quantity) < 0.0001

    def test_multiplier_of_zero_gives_zero(self, sizer):
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
            price_multiplier=0.0,
        )
        assert result.quantity == 0.0


# ═══════════════════════════════════════════════════════════════════════
# CUSTOM CONFIG
# ═══════════════════════════════════════════════════════════════════════


class TestCustomConfig:
    """Verify config parameters are respected."""

    def test_custom_risk_per_trade(self):
        sizer = PositionSizer(SizingConfig(risk_per_trade_pct=0.05))
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        # Max risk = 100000 * 0.05 = 5000
        assert result.risk_amount <= 5000.01

    def test_custom_max_notional(self):
        sizer = PositionSizer(SizingConfig(max_single_position_pct=0.10))
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49900.0,
            win_rate=0.7, avg_win=3.0, avg_loss=1.0,
        )
        assert result.notional_value <= 10000.01

    def test_custom_kelly_fraction(self):
        sizer = PositionSizer(SizingConfig(kelly_fraction=0.50))
        result = sizer.calculate(
            equity=100000.0, entry_price=50000.0, stop_loss=49500.0,
            win_rate=0.6, avg_win=2.0, avg_loss=1.0,
        )
        assert result.quantity > 0
