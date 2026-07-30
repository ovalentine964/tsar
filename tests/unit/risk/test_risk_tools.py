"""
Unit tests for Risk Tools — Stop-Loss, Take-Profit, Fee Calculator,
Exposure Tracker, and Position Sizer fee-aware integration.

Tests:
  - Stop-Loss Calculator: ATR, percentage, support methods
  - Take-Profit Calculator: R:R, resistance methods, min R:R enforcement
  - Fee Calculator: Binance tiers, BNB discount, fee-aware Kelly
  - Exposure Tracker: max limits enforcement
  - Position Sizer: fee-aware sizing at $10 micro-capital
"""

from __future__ import annotations

import pytest

from src.tools.stop_loss_calculator import StopLossCalculator
from src.tools.take_profit_calculator import TakeProfitCalculator
from src.tools.fee_calculator import FeeCalculator
from src.tools.risk_management import RiskManagementTools
from src.risk.position_sizer import PositionSizer, SizingConfig


# ═══════════════════════════════════════════════════════════════════════
# STOP-LOSS CALCULATOR TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestStopLossATR:
    """ATR-based stop-loss calculation."""

    def test_buy_stop_below_entry(self):
        calc = StopLossCalculator()
        result = calc.calculate_atr(entry_price=50000, atr=500, side="buy")
        assert result.stop_price < 50000
        assert result.method == "atr"

    def test_sell_stop_above_entry(self):
        calc = StopLossCalculator()
        result = calc.calculate_atr(entry_price=50000, atr=500, side="sell")
        assert result.stop_price > 50000

    def test_atr_multiplier_scales_distance(self):
        calc = StopLossCalculator()
        r1 = calc.calculate_atr(entry_price=50000, atr=500, side="buy", multiplier=1.0)
        r2 = calc.calculate_atr(entry_price=50000, atr=500, side="buy", multiplier=2.0)
        # Larger multiplier = wider stop = lower price for buy
        assert r2.stop_price < r1.stop_price
        assert r2.distance_pct > r1.distance_pct

    def test_default_multiplier_is_1_5(self):
        calc = StopLossCalculator()
        result = calc.calculate_atr(entry_price=50000, atr=500)
        # Default multiplier is 1.5, so stop = 50000 - 500*1.5 = 49250
        expected = 50000 - 500 * 1.5
        assert abs(result.stop_price - expected) < 0.01

    def test_max_stop_pct_cap(self):
        calc = StopLossCalculator({"max_stop_pct": 0.02})
        # ATR of 2000 with multiplier 2 → distance = 4000 (8%) → should cap at 2%
        result = calc.calculate_atr(entry_price=50000, atr=2000, side="buy", multiplier=2.0)
        assert result.distance_pct <= 0.0201
        assert result.capped is True

    def test_zero_atr_returns_zero(self):
        calc = StopLossCalculator()
        result = calc.calculate_atr(entry_price=50000, atr=0, side="buy")
        assert result.stop_price == 0.0

    def test_atr_from_ohlcv(self):
        highs = [100, 102, 105, 103, 108, 110, 107, 112, 115, 113, 118, 120, 117, 122, 125]
        lows = [98, 99, 101, 100, 104, 106, 103, 108, 111, 109, 114, 116, 113, 118, 121]
        closes = [99, 101, 103, 102, 106, 108, 105, 110, 113, 111, 116, 118, 115, 120, 123]
        result = StopLossCalculator.calculate_atr_from_ohlcv(highs, lows, closes, period=14)
        assert result.atr > 0
        assert result.atr_pct > 0
        assert len(result.true_ranges) == 14


class TestStopLossPercentage:
    """Percentage-based stop-loss calculation."""

    def test_buy_stop_below_entry(self):
        calc = StopLossCalculator()
        result = calc.calculate_percentage(entry_price=50000, pct=0.02, side="buy")
        assert abs(result.stop_price - 49000) < 0.01

    def test_sell_stop_above_entry(self):
        calc = StopLossCalculator()
        result = calc.calculate_percentage(entry_price=50000, pct=0.02, side="sell")
        assert abs(result.stop_price - 51000) < 0.01

    def test_custom_percentage(self):
        calc = StopLossCalculator({"max_stop_pct": 0.10})  # Allow up to 10%
        result = calc.calculate_percentage(entry_price=50000, pct=0.05, side="buy")
        assert abs(result.stop_price - 47500) < 0.01
        assert abs(result.distance_pct - 0.05) < 0.001

    def test_default_uses_max_stop_pct(self):
        calc = StopLossCalculator({"max_stop_pct": 0.03})
        result = calc.calculate_percentage(entry_price=50000, side="buy")
        assert abs(result.distance_pct - 0.03) < 0.001


class TestStopLossSupport:
    """Support-based stop-loss calculation."""

    def test_buy_stop_below_nearest_support(self):
        calc = StopLossCalculator()
        result = calc.calculate_support(
            entry_price=50000, supports=[49500, 49000, 48000], side="buy"
        )
        # Nearest support below entry is 49500, with 0.1% buffer
        expected = 49500 * 0.999
        assert abs(result.stop_price - expected) < 0.1
        assert result.method == "support"

    def test_sell_stop_above_nearest_resistance(self):
        calc = StopLossCalculator()
        result = calc.calculate_support(
            entry_price=50000, supports=[50500, 51000, 52000], side="sell"
        )
        expected = 50500 * 1.001
        assert abs(result.stop_price - expected) < 0.1

    def test_no_support_below_falls_back_to_percentage(self):
        calc = StopLossCalculator()
        result = calc.calculate_support(
            entry_price=50000, supports=[51000, 52000], side="buy"
        )
        assert result.method == "percentage"

    def test_empty_supports_falls_back(self):
        calc = StopLossCalculator()
        result = calc.calculate_support(entry_price=50000, supports=[], side="buy")
        assert result.method == "percentage"


# ═══════════════════════════════════════════════════════════════════════
# TAKE-PROFIT CALCULATOR TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestTakeProfitRR:
    """R:R-based take-profit calculation."""

    def test_buy_tp_above_entry(self):
        calc = TakeProfitCalculator()
        result = calc.calculate_rr(entry_price=50000, stop_loss=49500, side="buy", target_rr=2.0)
        # risk = 500, reward = 500 * 2 = 1000, tp = 51000
        assert abs(result.take_profit_price - 51000) < 0.01
        assert result.method == "risk_reward"

    def test_sell_tp_below_entry(self):
        calc = TakeProfitCalculator()
        result = calc.calculate_rr(entry_price=50000, stop_loss=50500, side="sell", target_rr=2.0)
        assert abs(result.take_profit_price - 49000) < 0.01

    def test_min_rr_enforcement(self):
        """R:R below 1.5:1 should be extended to meet minimum."""
        calc = TakeProfitCalculator({"min_rr_ratio": 1.5})
        # Request 1.0:1 R:R → should be forced to 1.5:1
        result = calc.calculate_rr(entry_price=50000, stop_loss=49500, side="buy", target_rr=1.0)
        assert result.rr_ratio >= 1.5
        # The TP is extended but the method may set capped based on max_tp_pct

    def test_target_rr_above_min_passes(self):
        calc = TakeProfitCalculator({"min_rr_ratio": 1.5})
        result = calc.calculate_rr(entry_price=50000, stop_loss=49500, side="buy", target_rr=3.0)
        assert result.rr_ratio >= 3.0
        assert result.capped is False

    def test_rr_ratio_correct(self):
        calc = TakeProfitCalculator()
        result = calc.calculate_rr(entry_price=50000, stop_loss=49500, side="buy", target_rr=2.5)
        # risk = 500, reward = 500 * 2.5 = 1250
        assert abs(result.rr_ratio - 2.5) < 0.01


class TestTakeProfitResistance:
    """Resistance-based take-profit calculation."""

    def test_buy_tp_below_nearest_resistance(self):
        calc = TakeProfitCalculator()
        result = calc.calculate_resistance(
            entry_price=50000, stop_loss=49500,
            resistances=[51000, 52000, 53000], side="buy"
        )
        # Nearest resistance is 51000, with 0.1% buffer
        expected = 51000 * 0.999
        assert abs(result.take_profit_price - expected) < 1.0
        assert result.method == "resistance"

    def test_min_rr_enforcement_on_resistance(self):
        """If resistance-based TP gives R:R < 1.5, should extend."""
        calc = TakeProfitCalculator({"min_rr_ratio": 1.5})
        # Entry=50000, SL=49900 (risk=100), resistance at 50050 (reward=50 → 0.5:1)
        result = calc.calculate_resistance(
            entry_price=50000, stop_loss=49900,
            resistances=[50050], side="buy"
        )
        assert result.rr_ratio >= 1.5

    def test_no_resistance_falls_back(self):
        calc = TakeProfitCalculator()
        result = calc.calculate_resistance(
            entry_price=50000, stop_loss=49500, resistances=[], side="buy"
        )
        assert result.method == "risk_reward"


class TestScaledTP:
    """Multiple take-profit levels for scaled exits."""

    def test_scaled_tp_returns_multiple_levels(self):
        calc = TakeProfitCalculator()
        results = calc.calculate_scaled_tp(
            entry_price=50000, stop_loss=49500, side="buy"
        )
        assert len(results) == 3
        # Each level should have increasing R:R
        for i in range(1, len(results)):
            assert results[i].rr_ratio >= results[i - 1].rr_ratio

    def test_custom_levels(self):
        calc = TakeProfitCalculator()
        results = calc.calculate_scaled_tp(
            entry_price=50000, stop_loss=49500, side="buy",
            levels=[1.5, 2.0, 3.0, 5.0]
        )
        assert len(results) == 4


# ═══════════════════════════════════════════════════════════════════════
# FEE CALCULATOR TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestFeeCalculator:
    """Binance fee tier calculations."""

    def test_vip0_taker_fee(self):
        calc = FeeCalculator()
        result = calc.calculate_fee(notional=10000, tier="vip0", is_taker=True, use_bnb=False)
        # Futures VIP0 taker: 0.05%
        assert abs(result.fee_amount - 5.0) < 0.01

    def test_vip0_maker_fee(self):
        calc = FeeCalculator()
        result = calc.calculate_fee(notional=10000, tier="vip0", is_taker=False, use_bnb=False)
        # Futures VIP0 maker: 0.02%
        assert abs(result.fee_amount - 2.0) < 0.01

    def test_bnb_discount(self):
        calc = FeeCalculator({"use_bnb_discount": True})
        result = calc.calculate_fee(notional=10000, tier="vip0", is_taker=True, use_bnb=True)
        # 0.05% * 0.75 = 0.0375%
        expected = 10000 * 0.0005 * 0.75
        assert abs(result.fee_amount - expected) < 0.01
        assert result.bnb_discount_applied is True

    def test_no_bnb_discount(self):
        calc = FeeCalculator()
        result = calc.calculate_fee(notional=10000, tier="vip0", is_taker=True, use_bnb=False)
        assert result.bnb_discount_applied is False

    def test_higher_tier_lower_fee(self):
        calc = FeeCalculator()
        vip0 = calc.calculate_fee(notional=10000, tier="vip0", is_taker=True, use_bnb=False)
        vip5 = calc.calculate_fee(notional=10000, tier="vip5", is_taker=True, use_bnb=False)
        assert vip5.fee_amount < vip0.fee_amount

    def test_round_trip_fee(self):
        calc = FeeCalculator()
        result = calc.calculate_round_trip_fee(notional=10000, tier="vip0", use_bnb=False)
        # Entry 0.05% + exit 0.05% = 0.1%
        expected = 10000 * 0.0005 * 2
        assert abs(result.total_fee - expected) < 0.01

    def test_zero_notional(self):
        calc = FeeCalculator()
        result = calc.calculate_fee(notional=0)
        assert result.fee_amount == 0.0


class TestNetRiskReward:
    """Net R:R after fees."""

    def test_fees_reduce_rr(self):
        calc = FeeCalculator()
        result = calc.net_risk_reward(
            entry_price=50000, stop_loss=49500, take_profit=51000,
            tier="vip0", use_bnb=False
        )
        # Gross R:R = 2.0, net should be less
        assert result.gross_rr == 2.0
        assert result.net_rr < 2.0
        assert result.net_rr > 0

    def test_high_fee_tier_reduces_rr_more(self):
        calc = FeeCalculator()
        vip0 = calc.net_risk_reward(
            entry_price=50000, stop_loss=49500, take_profit=51000,
            tier="vip0", use_bnb=False
        )
        vip9 = calc.net_risk_reward(
            entry_price=50000, stop_loss=49500, take_profit=51000,
            tier="vip9", use_bnb=False
        )
        # VIP9 has lower fees → higher net R:R
        assert vip9.net_rr > vip0.net_rr

    def test_min_rr_check(self):
        calc = FeeCalculator({"min_rr_ratio_after_fees": 1.5})
        result = calc.net_risk_reward(
            entry_price=50000, stop_loss=49500, take_profit=51000,
            tier="vip0", use_bnb=False
        )
        # With 2:1 gross R:R, net should still be above 1.5
        assert result.meets_min_rr is True


class TestFeeAdjustedKelly:
    """Fee-adjusted Kelly fraction."""

    def test_fees_reduce_kelly(self):
        calc = FeeCalculator()
        base_kelly = 0.20
        adjusted = calc.fee_adjusted_kelly(
            base_kelly=base_kelly,
            entry_price=50000,
            stop_loss=49500,
            tier="vip0",
            use_bnb=False,
        )
        assert adjusted < base_kelly
        assert adjusted > 0

    def test_zero_kelly_stays_zero(self):
        calc = FeeCalculator()
        adjusted = calc.fee_adjusted_kelly(
            base_kelly=0.0, entry_price=50000, stop_loss=49500
        )
        assert adjusted == 0.0

    def test_bnb_discount_preserves_more_kelly(self):
        calc = FeeCalculator()
        with_bnb = calc.fee_adjusted_kelly(
            base_kelly=0.20, entry_price=50000, stop_loss=49500,
            tier="vip0", use_bnb=True
        )
        without_bnb = calc.fee_adjusted_kelly(
            base_kelly=0.20, entry_price=50000, stop_loss=49500,
            tier="vip0", use_bnb=False
        )
        assert with_bnb > without_bnb


class TestBreakEven:
    """Break-even analysis."""

    def test_break_even_positive(self):
        calc = FeeCalculator()
        result = calc.break_even(price=50000, tier="vip0", use_bnb=False)
        assert result.break_even_pct > 0
        assert result.break_even_price_long > 50000
        assert result.break_even_price_short < 50000

    def test_break_even_with_bnb(self):
        calc = FeeCalculator()
        with_bnb = calc.break_even(price=50000, tier="vip0", use_bnb=True)
        without_bnb = calc.break_even(price=50000, tier="vip0", use_bnb=False)
        assert with_bnb.break_even_pct < without_bnb.break_even_pct


class TestTierComparison:
    """Compare fees across tiers."""

    def test_compare_all_tiers(self):
        calc = FeeCalculator()
        results = calc.compare_tiers(notional=10000, is_taker=True)
        assert len(results) == 10  # VIP0-VIP9
        # Fees should decrease with higher tiers (vip0 highest, vip9 lowest)
        fees = [r.fee_amount for r in results.values()]
        assert fees == sorted(fees, reverse=True)  # Descending order


# ═══════════════════════════════════════════════════════════════════════
# EXPOSURE TRACKER TESTS (Max Limits Enforcement)
# ═══════════════════════════════════════════════════════════════════════


class TestExposureLimits:
    """Exposure limit enforcement."""

    def test_within_limits(self):
        tools = RiskManagementTools({
            "max_leverage": 3.0,
            "max_single_asset_pct": 1.0,  # Allow 100% single asset
            "max_sector_pct": 1.0,
        })
        exposure = tools.calculate_exposure(
            positions=[
                {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.1, "current_price": 50000},
            ],
            equity=100000,
        )
        result = tools.check_exposure_limits(exposure)
        assert result["within_limits"] is True

    def test_leverage_violation(self):
        tools = RiskManagementTools({"max_leverage": 1.0})
        exposure = tools.calculate_exposure(
            positions=[
                {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.5, "current_price": 50000},
            ],
            equity=10000,
        )
        result = tools.check_exposure_limits(exposure)
        # Gross exposure = 25000, equity = 10000 → leverage = 2.5x > 1.0x
        assert result["within_limits"] is False
        assert any("Leverage" in v for v in result["violations"])

    def test_concentration_violation(self):
        tools = RiskManagementTools({"max_single_asset_pct": 0.20})
        exposure = tools.calculate_exposure(
            positions=[
                {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.5, "current_price": 50000},
            ],
            equity=100000,
        )
        result = tools.check_exposure_limits(exposure)
        # BTC = 25000 / 25000 = 100% > 20%
        assert result["within_limits"] is False


# ═══════════════════════════════════════════════════════════════════════
# POSITION SIZER — FEE-AWARE AT $10 MICRO-CAPITAL
# ═══════════════════════════════════════════════════════════════════════


class TestPositionSizerFeeAwareMicroCapital:
    """Fee-aware sizing works at $10 micro-capital level."""

    def test_micro_capital_mode_active_at_10(self):
        sizer = PositionSizer(SizingConfig(
            micro_capital_enabled=True,
            micro_capital_threshold_usd=50.0,
        ))
        result = sizer.calculate(
            equity=10.0,
            entry_price=50000.0,
            stop_loss=49500.0,
            win_rate=0.6,
            avg_win=2.0,
            avg_loss=1.0,
        )
        assert "micro" in result.method

    def test_fee_aware_at_10(self):
        """At $10, fee-aware Kelly should still produce a valid result."""
        sizer = PositionSizer(SizingConfig(
            fee_adjusted_kelly=True,
            taker_fee_pct=0.001,
            micro_capital_enabled=True,
            micro_capital_threshold_usd=50.0,
        ))
        result = sizer.calculate(
            equity=10.0,
            entry_price=50000.0,
            stop_loss=49500.0,
            win_rate=0.6,
            avg_win=2.0,
            avg_loss=1.0,
        )
        # Should produce a result (may be 0 if net R:R after fees < 1.5)
        assert isinstance(result.quantity, float)
        assert result.quantity >= 0

    def test_micro_capital_relaxed_caps(self):
        """Micro-capital mode should use relaxed caps."""
        sizer = PositionSizer(SizingConfig(
            micro_capital_enabled=True,
            micro_capital_threshold_usd=50.0,
            micro_kelly_fraction=0.40,
            micro_risk_per_trade_pct=0.05,
            micro_max_single_position_pct=0.30,
        ))
        result = sizer.calculate(
            equity=10.0,
            entry_price=100.0,
            stop_loss=99.0,
            win_rate=0.6,
            avg_win=2.0,
            avg_loss=1.0,
        )
        # With micro caps, risk can be up to 5% of $10 = $0.50
        if result.quantity > 0:
            assert result.risk_amount <= 10.0 * 0.05 + 0.01

    def test_min_notional_enforcement(self):
        """Very small positions should be bumped to meet exchange minimums."""
        sizer = PositionSizer(SizingConfig(
            micro_capital_enabled=True,
            micro_capital_threshold_usd=50.0,
            micro_min_notional_usd=5.0,
        ))
        result = sizer.calculate(
            equity=10.0,
            entry_price=50000.0,
            stop_loss=49500.0,
            win_rate=0.6,
            avg_win=2.0,
            avg_loss=1.0,
        )
        # If quantity > 0, notional should be >= $5
        if result.quantity > 0:
            assert result.notional_value >= 5.0 - 0.01
