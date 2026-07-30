"""
Position Sizer — Optimal position size calculation.

Uses Half-Kelly sizing (0.25 fraction) with a 2% hard risk cap per trade.
All calculations are deterministic — no LLM, no external calls.

SIZING FORMULA:
  1. Half-Kelly: f* = 0.25 * (win_rate * avg_win - loss_rate * avg_loss) / avg_win
  2. Fee-adjusted: reduce edge by round-trip fee cost
  3. Risk-based: risk_amount = equity * risk_per_trade_pct
  4. Position = risk_amount / |entry - stop_loss|
  5. Cap at 2% risk and 15% notional of equity
  6. Micro-capital mode: relaxed caps for equity < $50

FEE-AWARE SIZING (C-001):
  Binance charges 0.1% maker/taker. For a round-trip trade:
    total_fee = entry_notional * taker_fee + exit_notional * taker_fee
  This reduces the effective edge in the Kelly calculation.
  The min R:R check also accounts for fees.

MICRO-CAPITAL MODE (H-005):
  When equity < $50, standard risk controls produce position sizes
  too small for exchange minimums. Micro-capital mode relaxes:
    - Kelly fraction: 0.25 → 0.40 (more aggressive, absolute risk is tiny)
    - Risk per trade: 2% → 5%
    - Max single position: 15% → 30%
  Minimum notional enforcement ensures orders meet exchange minimums.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.interfaces.types import PositionSizeResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SizingConfig:
    """Immutable sizing configuration — sourced from risk.yaml.

    C-015: These are CODE DEFAULTS. RiskGovernor overrides them
    with values from risk.yaml. If risk.yaml is missing, these apply.
    """

    # Standard parameters
    kelly_fraction: float = 0.25
    risk_per_trade_pct: float = 0.02
    max_single_position_pct: float = 0.15

    # Fee parameters (C-001)
    maker_fee_pct: float = 0.001    # 0.1% Binance default
    taker_fee_pct: float = 0.001    # 0.1% Binance default
    fee_adjusted_kelly: bool = True
    min_rr_ratio_after_fees: float = 1.5

    # Micro-capital parameters (H-005)
    micro_capital_enabled: bool = True
    micro_capital_threshold_usd: float = 50.0
    micro_kelly_fraction: float = 0.40
    micro_risk_per_trade_pct: float = 0.05
    micro_max_single_position_pct: float = 0.30
    micro_min_notional_usd: float = 5.0
    micro_min_quantity_step: float = 0.00001


class PositionSizer:
    """Deterministic position size calculator.

    Implements Half-Kelly sizing with hard caps. All inputs are
    numeric — zero external calls, zero LLM involvement.

    Supports:
      - Standard sizing (equity >= $50)
      - Fee-adjusted Kelly (C-001) — reduces edge by round-trip fees
      - Micro-capital mode (H-005) — relaxed parameters for small accounts
      - Minimum notional enforcement — meets exchange minimums
    """

    def __init__(self, config: SizingConfig | None = None) -> None:
        self._config = config or SizingConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        win_rate: float = 0.5,
        avg_win: float = 1.0,
        avg_loss: float = 1.0,
        price_multiplier: float = 1.0,
    ) -> PositionSizeResult:
        """Calculate position size using Half-Kelly with hard caps.

        Supports fee-aware sizing (C-001) and micro-capital mode (H-005).

        Args:
            equity: Current portfolio equity (USDT).
            entry_price: Proposed entry price.
            stop_loss: Proposed stop-loss price.
            win_rate: Historical win rate (0.0-1.0). Default 0.5.
            avg_win: Average winning trade R-multiple. Default 1.0.
            avg_loss: Average losing trade R-multiple (positive). Default 1.0.
            price_multiplier: Volatility/behavioral adjustment (0.0-1.0).

        Returns:
            PositionSizeResult with quantity, notional, risk, and cap info.
        """
        if equity <= 0 or entry_price <= 0 or stop_loss <= 0:
            return self._zero_result("Invalid inputs (equity/price/stop ≤ 0)")

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return self._zero_result("Entry and stop-loss are identical")

        # --- Determine if micro-capital mode applies (H-005) ---
        cfg = self._config
        is_micro = (
            cfg.micro_capital_enabled
            and equity < cfg.micro_capital_threshold_usd
        )

        # Select parameters based on mode
        if is_micro:
            kelly_frac = cfg.micro_kelly_fraction
            risk_pct = cfg.micro_risk_per_trade_pct
            max_single_pct = cfg.micro_max_single_position_pct
            min_notional = cfg.micro_min_notional_usd
            min_qty_step = cfg.micro_min_quantity_step
            logger.info(
                f"MICRO-CAPITAL MODE active (equity=${equity:.2f} < "
                f"${cfg.micro_capital_threshold_usd}): "
                f"kelly={kelly_frac}, risk={risk_pct:.1%}, "
                f"max_single={max_single_pct:.1%}"
            )
        else:
            kelly_frac = cfg.kelly_fraction
            risk_pct = cfg.risk_per_trade_pct
            max_single_pct = cfg.max_single_position_pct
            min_notional = cfg.micro_min_notional_usd  # Still enforce minimum
            min_qty_step = cfg.micro_min_quantity_step

        # --- Step 1: Fee-adjusted Kelly fraction (C-001) ---
        kelly_f = self._kelly_fraction(win_rate, avg_win, avg_loss)

        # Apply fee adjustment to Kelly edge
        if cfg.fee_adjusted_kelly:
            kelly_f = self._fee_adjusted_kelly(
                kelly_f, entry_price, risk_per_unit, cfg.taker_fee_pct
            )

        # Apply the conservative half-Kelly cap (or micro Kelly)
        kelly_f *= kelly_frac

        # --- Step 2: Risk-based cap ---
        max_risk_amount = equity * risk_pct

        # --- Step 3: Kelly-sized risk amount ---
        kelly_risk = equity * kelly_f
        risk_amount = min(kelly_risk, max_risk_amount)

        # --- Step 4: Convert risk to quantity ---
        quantity = risk_amount / risk_per_unit

        # --- Step 5: Notional cap ---
        notional = quantity * entry_price
        max_notional = equity * max_single_pct
        capped = False
        cap_reason = ""

        if notional > max_notional:
            quantity = max_notional / entry_price
            notional = quantity * entry_price
            risk_amount = quantity * risk_per_unit
            capped = True
            cap_reason = f"Notional capped at {max_single_pct:.0%} of equity"

        # --- Step 6: Apply price/volatility multiplier ---
        if price_multiplier < 1.0:
            quantity *= price_multiplier
            notional = quantity * entry_price
            risk_amount = quantity * risk_per_unit
            if not capped:
                capped = True
                cap_reason = f"Size reduced by multiplier {price_multiplier:.2f}"

        # --- Step 7: Fee cost check (C-001) ---
        # Calculate round-trip fee cost and verify trade is still profitable
        round_trip_fee = self._round_trip_fee(notional, cfg.taker_fee_pct)
        net_risk_reward = self._net_risk_reward(
            entry_price, stop_loss, notional, cfg.taker_fee_pct
        )

        if net_risk_reward < cfg.min_rr_ratio_after_fees:
            # After fees, R:R is too low — don't trade
            return self._zero_result(
                f"Net R:R after fees ({net_risk_reward:.2f}:1) < "
                f"minimum ({cfg.min_rr_ratio_after_fees}:1). "
                f"Round-trip fee: ${round_trip_fee:.4f}"
            )

        # --- Step 8: Minimum notional enforcement (H-005) ---
        if notional < min_notional and notional > 0:
            # Try to meet minimum by increasing quantity
            needed_qty = min_notional / entry_price
            if needed_qty * risk_per_unit <= max_risk_amount:
                quantity = needed_qty
                notional = quantity * entry_price
                risk_amount = quantity * risk_per_unit
                capped = True
                cap_reason = (
                    f"Increased to meet minimum notional ${min_notional:.2f}"
                )
            else:
                # Can't meet minimum without exceeding risk cap
                return self._zero_result(
                    f"Notional ${notional:.2f} below exchange minimum "
                    f"${min_notional:.2f} and increasing would exceed "
                    f"risk cap of {risk_pct:.1%}"
                )

        # --- Step 9: Minimum quantity step enforcement ---
        if min_qty_step > 0 and quantity > 0:
            # Round down to nearest valid quantity step
            quantity = int(quantity / min_qty_step) * min_qty_step
            if quantity <= 0:
                return self._zero_result(
                    f"Quantity rounded to zero (min step={min_qty_step})"
                )
            notional = quantity * entry_price
            risk_amount = quantity * risk_per_unit

        risk_pct_final = risk_amount / equity if equity > 0 else 0.0

        # Build method label
        method = "half_kelly"
        if is_micro:
            method = "micro_capital_kelly"
        if cfg.fee_adjusted_kelly:
            method = f"fee_adjusted_{method}"

        logger.debug(
            f"PositionSizer: qty={quantity:.8f} notional={notional:.2f} "
            f"risk={risk_amount:.2f} ({risk_pct_final:.2%}) kelly_f={kelly_f:.4f} "
            f"capped={capped} micro={is_micro} "
            f"fee_cost={round_trip_fee:.4f} net_rr={net_risk_reward:.2f}"
        )

        return PositionSizeResult(
            quantity=round(quantity, 8),
            notional_value=round(notional, 2),
            risk_amount=round(risk_amount, 2),
            risk_pct=round(risk_pct_final, 6),
            method=method,
            capped=capped,
            cap_reason=cap_reason,
        )

    # ------------------------------------------------------------------
    # Fee-aware helpers (C-001)
    # ------------------------------------------------------------------

    @staticmethod
    def _fee_adjusted_kelly(
        base_kelly: float,
        entry_price: float,
        risk_per_unit: float,
        taker_fee_pct: float,
    ) -> float:
        """Adjust Kelly fraction to account for round-trip trading fees.

        The fee reduces the effective edge of the strategy.
        For a trade with risk_per_unit R and fee cost F:
          adjusted_edge = base_edge - (2 * F / R)

        This is conservative — it assumes worst-case (taker fees both ways).

        Args:
            base_kelly: Raw Kelly fraction from win/loss statistics.
            entry_price: Entry price for fee calculation.
            risk_per_unit: |entry - stop_loss| in price terms.
            taker_fee_pct: Taker fee as decimal (e.g., 0.001 for 0.1%).

        Returns:
            Fee-adjusted Kelly fraction (>= 0).
        """
        if risk_per_unit <= 0 or base_kelly <= 0:
            return 0.0

        # Round-trip fee as fraction of risk
        # fee_per_unit = entry_price * taker_fee_pct (entry fee)
        # + entry_price * taker_fee_pct (exit fee, approximate)
        round_trip_fee_per_unit = 2 * entry_price * taker_fee_pct

        # Fee impact on Kelly: reduce edge proportional to fee/risk ratio
        fee_ratio = round_trip_fee_per_unit / risk_per_unit

        # Reduce Kelly by fee impact (but never below 0)
        adjusted = base_kelly * max(0.0, 1.0 - fee_ratio)

        if adjusted < base_kelly:
            logger.debug(
                f"Fee-adjusted Kelly: {base_kelly:.4f} → {adjusted:.4f} "
                f"(fee_ratio={fee_ratio:.4f})"
            )

        return max(0.0, adjusted)

    @staticmethod
    def _round_trip_fee(notional: float, taker_fee_pct: float) -> float:
        """Calculate round-trip fee cost for a trade.

        Args:
            notional: Trade notional value.
            taker_fee_pct: Taker fee rate.

        Returns:
            Total fee cost for entry + exit.
        """
        return 2 * notional * taker_fee_pct

    @staticmethod
    def _net_risk_reward(
        entry_price: float,
        stop_loss: float,
        notional: float,
        taker_fee_pct: float,
    ) -> float:
        """Calculate net risk-reward ratio after fees.

        Args:
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            notional: Trade notional value.
            taker_fee_pct: Taker fee rate.

        Returns:
            Net R:R ratio after subtracting round-trip fees.
            Returns 0 if risk is zero.
        """
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return 0.0

        # Assume 2:1 R:R target (reward = 2 * risk)
        raw_reward_per_unit = 2 * risk_per_unit

        # Subtract round-trip fee from reward
        fee_per_unit = 2 * entry_price * taker_fee_pct
        net_reward_per_unit = raw_reward_per_unit - fee_per_unit

        if risk_per_unit == 0:
            return 0.0

        return max(0.0, net_reward_per_unit / risk_per_unit)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _kelly_fraction(
        win_rate: float, avg_win: float, avg_loss: float
    ) -> float:
        """Pure Kelly criterion: f* = (p*b - q) / b.

        Where p=win_rate, q=1-p, b=avg_win/avg_loss.
        Returns 0 if the edge is negative (no bet).
        """
        if avg_loss <= 0 or avg_win <= 0:
            return 0.0

        p = max(0.0, min(1.0, win_rate))
        q = 1.0 - p
        b = avg_win / avg_loss

        kelly = (p * b - q) / b if b > 0 else 0.0
        # Never negative — if edge is negative, don't trade
        return max(0.0, kelly)

    @staticmethod
    def _zero_result(reason: str) -> PositionSizeResult:
        """Return a zero-size result with a cap reason."""
        return PositionSizeResult(
            quantity=0.0,
            notional_value=0.0,
            risk_amount=0.0,
            risk_pct=0.0,
            method="half_kelly",
            capped=True,
            cap_reason=reason,
        )
