"""
TSAR Domain Tools — Fee Calculator.

Binance fee structure calculator with support for:
  - Binance fee tiers (VIP0-VIP9, market maker tiers)
  - BNB discount (25% fee reduction when paying with BNB)
  - Fee-aware Kelly sizing integration
  - Round-trip fee cost calculation
  - Break-even analysis

All calculations are deterministic — no LLM, no external calls.

Usage:
    calc = FeeCalculator()
    fee = calc.calculate_fee(notional=10000, tier="vip0", is_taker=True)
    net_rr = calc.net_risk_reward(entry=50000, stop=49500, tp=51000, tier="vip0")
    kelly_adj = calc.fee_adjusted_kelly(base_kelly=0.15, entry=50000, stop=49500)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# BINANCE FEE TIERS (as of 2024)
# ═══════════════════════════════════════════════════════════════════════

# Spot trading fee tiers (maker, taker)
SPOT_FEE_TIERS: dict[str, tuple[float, float]] = {
    "vip0": (0.001000, 0.001000),  # 0.10% / 0.10%
    "vip1": (0.000900, 0.001000),  # 0.09% / 0.10%
    "vip2": (0.000800, 0.001000),  # 0.08% / 0.10%
    "vip3": (0.000420, 0.000600),  # 0.042% / 0.06%
    "vip4": (0.000420, 0.000540),  # 0.042% / 0.054%
    "vip5": (0.000360, 0.000480),  # 0.036% / 0.048%
    "vip6": (0.000300, 0.000400),  # 0.030% / 0.040%
    "vip7": (0.000240, 0.000320),  # 0.024% / 0.032%
    "vip8": (0.000180, 0.000240),  # 0.018% / 0.024%
    "vip9": (0.000120, 0.000180),  # 0.012% / 0.018%
}

# Futures trading fee tiers (maker, taker)
FUTURES_FEE_TIERS: dict[str, tuple[float, float]] = {
    "vip0": (0.000200, 0.000500),  # 0.02% / 0.05%
    "vip1": (0.000160, 0.000400),  # 0.016% / 0.04%
    "vip2": (0.000140, 0.000350),  # 0.014% / 0.035%
    "vip3": (0.000100, 0.000300),  # 0.010% / 0.03%
    "vip4": (0.000080, 0.000280),  # 0.008% / 0.028%
    "vip5": (0.000060, 0.000250),  # 0.006% / 0.025%
    "vip6": (0.000040, 0.000220),  # 0.004% / 0.022%
    "vip7": (0.000020, 0.000200),  # 0.002% / 0.020%
    "vip8": (0.000000, 0.000180),  # 0.000% / 0.018%
    "vip9": (0.000000, 0.000150),  # 0.000% / 0.015%
}

# BNB discount
BNB_DISCOUNT = 0.25  # 25% fee reduction when paying with BNB


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FeeResult:
    """Result of a fee calculation.

    Attributes:
        fee_amount: Fee amount in quote currency.
        fee_rate: Fee rate used (decimal).
        notional: Notional value of the trade.
        is_taker: Whether taker fee was applied.
        tier: Fee tier used.
        bnb_discount_applied: Whether BNB discount was applied.
        original_fee: Fee before BNB discount (if applied).
    """

    fee_amount: float
    fee_rate: float
    notional: float
    is_taker: bool
    tier: str
    bnb_discount_applied: bool = False
    original_fee: float = 0.0


@dataclass(frozen=True)
class RoundTripFeeResult:
    """Result of a round-trip fee calculation.

    Attributes:
        entry_fee: Fee for entry trade.
        exit_fee: Fee for exit trade.
        total_fee: Total round-trip fee cost.
        fee_pct_of_notional: Total fee as percentage of notional.
        tier: Fee tier used.
        bnb_discount_applied: Whether BNB discount was applied.
    """

    entry_fee: float
    exit_fee: float
    total_fee: float
    fee_pct_of_notional: float
    tier: str
    bnb_discount_applied: bool = False


@dataclass(frozen=True)
class NetRiskRewardResult:
    """Result of net R:R calculation after fees.

    Attributes:
        gross_rr: Gross risk-reward ratio (before fees).
        net_rr: Net risk-reward ratio (after fees).
        fee_cost: Total fee cost in quote currency.
        fee_drag: Fee drag on the trade (as fraction of risk).
        meets_min_rr: Whether net R:R meets minimum threshold.
        min_rr_threshold: Minimum R:R threshold used.
    """

    gross_rr: float
    net_rr: float
    fee_cost: float
    fee_drag: float
    meets_min_rr: bool
    min_rr_threshold: float


@dataclass(frozen=True)
class BreakEvenResult:
    """Break-even analysis result.

    Attributes:
        break_even_pct: Price movement needed to break even (decimal).
        break_even_price_long: Break-even price for long.
        break_even_price_short: Break-even price for short.
        fee_cost: Total fee cost.
    """

    break_even_pct: float
    break_even_price_long: float
    break_even_price_short: float
    fee_cost: float


# ═══════════════════════════════════════════════════════════════════════
# FEE CALCULATOR
# ═══════════════════════════════════════════════════════════════════════


class FeeCalculator:
    """Binance fee structure calculator.

    Supports:
    - Spot and futures fee tiers (VIP0-VIP9)
    - BNB discount (25% reduction)
    - Fee-aware Kelly sizing integration
    - Round-trip cost analysis
    - Net R:R after fees
    - Break-even analysis

    All calculations are deterministic — pure math, no external calls.
    """

    description = (
        "Fee calculator: Binance fee tiers, BNB discount, fee-aware Kelly sizing, net R:R analysis"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._default_tier = cfg.get("default_tier", "vip0")
        self._use_bnb = cfg.get("use_bnb_discount", True)
        self._market_type = cfg.get("market_type", "futures")  # "spot" or "futures"
        self._min_rr_after_fees = cfg.get("min_rr_ratio_after_fees", 1.5)

    # ── Single Fee Calculation ───────────────────────────────────────

    def calculate_fee(
        self,
        notional: float,
        tier: str | None = None,
        is_taker: bool = True,
        use_bnb: bool | None = None,
    ) -> FeeResult:
        """Calculate fee for a single trade.

        Args:
            notional: Trade notional value in quote currency.
            tier: Fee tier (e.g., "vip0"). Defaults to config.
            is_taker: True for taker fee, False for maker fee.
            use_bnb: Whether to apply BNB discount. Defaults to config.

        Returns:
            FeeResult with fee amount and details.
        """
        if notional <= 0:
            return FeeResult(
                fee_amount=0.0,
                fee_rate=0.0,
                notional=0.0,
                is_taker=is_taker,
                tier=tier or self._default_tier,
            )

        t = (tier or self._default_tier).lower()
        bnb = use_bnb if use_bnb is not None else self._use_bnb

        # Get fee rate
        fee_tiers = FUTURES_FEE_TIERS if self._market_type == "futures" else SPOT_FEE_TIERS
        if t not in fee_tiers:
            logger.warning(f"Unknown fee tier '{t}', falling back to vip0")
            t = "vip0"

        maker_rate, taker_rate = fee_tiers[t]
        fee_rate = taker_rate if is_taker else maker_rate

        # Calculate fee
        fee_amount = notional * fee_rate
        original_fee = fee_amount

        # Apply BNB discount
        if bnb:
            fee_amount *= 1.0 - BNB_DISCOUNT

        return FeeResult(
            fee_amount=round(fee_amount, 8),
            fee_rate=round(fee_rate, 8),
            notional=round(notional, 2),
            is_taker=is_taker,
            tier=t,
            bnb_discount_applied=bnb,
            original_fee=round(original_fee, 8),
        )

    # ── Round-Trip Fee ───────────────────────────────────────────────

    def calculate_round_trip_fee(
        self,
        notional: float,
        tier: str | None = None,
        entry_is_taker: bool = True,
        exit_is_taker: bool = True,
        use_bnb: bool | None = None,
    ) -> RoundTripFeeResult:
        """Calculate total round-trip fee (entry + exit).

        Args:
            notional: Trade notional value.
            tier: Fee tier.
            entry_is_taker: Whether entry is taker.
            exit_is_taker: Whether exit is taker.
            use_bnb: Whether to apply BNB discount.

        Returns:
            RoundTripFeeResult with entry, exit, and total fees.
        """
        entry = self.calculate_fee(notional, tier, entry_is_taker, use_bnb)
        exit_fee = self.calculate_fee(notional, tier, exit_is_taker, use_bnb)

        total = entry.fee_amount + exit_fee.fee_amount
        fee_pct = total / notional if notional > 0 else 0.0

        return RoundTripFeeResult(
            entry_fee=round(entry.fee_amount, 8),
            exit_fee=round(exit_fee.fee_amount, 8),
            total_fee=round(total, 8),
            fee_pct_of_notional=round(fee_pct, 8),
            tier=entry.tier,
            bnb_discount_applied=entry.bnb_discount_applied,
        )

    # ── Net Risk-Reward After Fees ───────────────────────────────────

    def net_risk_reward(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        tier: str | None = None,
        use_bnb: bool | None = None,
    ) -> NetRiskRewardResult:
        """Calculate net risk-reward ratio after accounting for fees.

        Fees reduce the effective reward and increase the effective risk.
        This gives the true R:R that accounts for execution costs.

        Args:
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.
            tier: Fee tier.
            use_bnb: Whether to apply BNB discount.

        Returns:
            NetRiskRewardResult with gross and net R:R.
        """
        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            return NetRiskRewardResult(
                gross_rr=0.0,
                net_rr=0.0,
                fee_cost=0.0,
                fee_drag=0.0,
                meets_min_rr=False,
                min_rr_threshold=self._min_rr_after_fees,
            )

        risk_per_unit = abs(entry_price - stop_loss)
        reward_per_unit = abs(take_profit - entry_price)

        if risk_per_unit == 0:
            return NetRiskRewardResult(
                gross_rr=0.0,
                net_rr=0.0,
                fee_cost=0.0,
                fee_drag=0.0,
                meets_min_rr=False,
                min_rr_threshold=self._min_rr_after_fees,
            )

        gross_rr = reward_per_unit / risk_per_unit

        # Calculate fee cost per unit (entry + exit)
        rt = self.calculate_round_trip_fee(entry_price, tier, use_bnb=use_bnb)
        fee_per_unit = rt.total_fee  # Fee on 1 unit of base asset

        # Net reward = gross reward - fee cost
        net_reward = reward_per_unit - fee_per_unit
        net_rr = max(0.0, net_reward / risk_per_unit)

        # Fee drag = fee as fraction of risk
        fee_drag = fee_per_unit / risk_per_unit if risk_per_unit > 0 else 0.0

        return NetRiskRewardResult(
            gross_rr=round(gross_rr, 4),
            net_rr=round(net_rr, 4),
            fee_cost=round(fee_per_unit, 8),
            fee_drag=round(fee_drag, 6),
            meets_min_rr=net_rr >= self._min_rr_after_fees,
            min_rr_threshold=self._min_rr_after_fees,
        )

    # ── Fee-Adjusted Kelly ───────────────────────────────────────────

    def fee_adjusted_kelly(
        self,
        base_kelly: float,
        entry_price: float,
        stop_loss: float,
        tier: str | None = None,
        use_bnb: bool | None = None,
    ) -> float:
        """Calculate fee-adjusted Kelly fraction.

        Fees reduce the effective edge of a strategy. This method
        adjusts the Kelly fraction downward to account for the
        round-trip fee cost relative to the risk per trade.

        Formula:
            fee_ratio = round_trip_fee / risk_per_unit
            adjusted_kelly = base_kelly * max(0, 1 - fee_ratio)

        Args:
            base_kelly: Raw Kelly fraction from win/loss statistics.
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            tier: Fee tier.
            use_bnb: Whether to apply BNB discount.

        Returns:
            Fee-adjusted Kelly fraction (>= 0).
        """
        if base_kelly <= 0 or entry_price <= 0 or stop_loss <= 0:
            return 0.0

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0

        # Calculate round-trip fee per unit
        rt = self.calculate_round_trip_fee(entry_price, tier, use_bnb=use_bnb)
        fee_per_unit = rt.total_fee

        # Fee ratio: how much of the risk is consumed by fees
        fee_ratio = fee_per_unit / risk_per_unit

        # Reduce Kelly by fee impact
        adjusted = base_kelly * max(0.0, 1.0 - fee_ratio)

        if adjusted < base_kelly:
            logger.debug(
                f"Fee-adjusted Kelly: {base_kelly:.4f} → {adjusted:.4f} "
                f"(fee_ratio={fee_ratio:.4f}, tier={rt.tier}, bnb={rt.bnb_discount_applied})"
            )

        return max(0.0, adjusted)

    # ── Break-Even Analysis ──────────────────────────────────────────

    def break_even(
        self,
        price: float,
        tier: str | None = None,
        use_bnb: bool | None = None,
    ) -> BreakEvenResult:
        """Calculate break-even price movement for a round-trip trade.

        Args:
            price: Current price.
            tier: Fee tier.
            use_bnb: Whether to apply BNB discount.

        Returns:
            BreakEvenResult with break-even percentages and prices.
        """
        if price <= 0:
            return BreakEvenResult(
                break_even_pct=0.0,
                break_even_price_long=0.0,
                break_even_price_short=0.0,
                fee_cost=0.0,
            )

        rt = self.calculate_round_trip_fee(price, tier, use_bnb=use_bnb)
        fee_pct = rt.fee_pct_of_notional

        return BreakEvenResult(
            break_even_pct=round(fee_pct, 8),
            break_even_price_long=round(price * (1.0 + fee_pct), 8),
            break_even_price_short=round(price * (1.0 - fee_pct), 8),
            fee_cost=round(rt.total_fee, 8),
        )

    # ── Tier Comparison ──────────────────────────────────────────────

    def compare_tiers(
        self,
        notional: float,
        is_taker: bool = True,
    ) -> dict[str, FeeResult]:
        """Compare fees across all Binance fee tiers.

        Useful for understanding the cost savings of higher tiers.

        Args:
            notional: Trade notional value.
            is_taker: Whether to use taker fees.

        Returns:
            Dict mapping tier name to FeeResult.
        """
        fee_tiers = FUTURES_FEE_TIERS if self._market_type == "futures" else SPOT_FEE_TIERS
        results = {}
        for tier in fee_tiers:
            results[tier] = self.calculate_fee(notional, tier, is_taker, use_bnb=False)
        return results

    # ── Utility ──────────────────────────────────────────────────────

    def get_fee_rate(
        self,
        tier: str | None = None,
        is_taker: bool = True,
        use_bnb: bool | None = None,
    ) -> float:
        """Get the effective fee rate for a tier.

        Args:
            tier: Fee tier.
            is_taker: True for taker, False for maker.
            use_bnb: Whether to apply BNB discount.

        Returns:
            Effective fee rate as decimal.
        """
        t = (tier or self._default_tier).lower()
        bnb = use_bnb if use_bnb is not None else self._use_bnb

        fee_tiers = FUTURES_FEE_TIERS if self._market_type == "futures" else SPOT_FEE_TIERS
        if t not in fee_tiers:
            t = "vip0"

        maker_rate, taker_rate = fee_tiers[t]
        rate = taker_rate if is_taker else maker_rate

        if bnb:
            rate *= 1.0 - BNB_DISCOUNT

        return round(rate, 8)
