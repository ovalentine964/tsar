"""
Position Sizer — Optimal position size calculation.

Uses Half-Kelly sizing (0.25 fraction) with a 2% hard risk cap per trade.
All calculations are deterministic — no LLM, no external calls.

Sizing formula:
  1. Half-Kelly: f* = 0.25 * (win_rate * avg_win - loss_rate * avg_loss) / avg_win
  2. Risk-based: risk_amount = equity * risk_per_trade_pct
  3. Position = risk_amount / |entry - stop_loss|
  4. Cap at 2% risk and 15% notional of equity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.interfaces.types import PositionSizeResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SizingConfig:
    """Immutable sizing configuration from risk.yaml."""

    kelly_fraction: float = 0.25
    risk_per_trade_pct: float = 0.02
    max_single_position_pct: float = 0.15


class PositionSizer:
    """Deterministic position size calculator.

    Implements Half-Kelly sizing with hard caps. All inputs are
    numeric — zero external calls, zero LLM involvement.
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

        # --- Step 1: Kelly fraction ---
        kelly_f = self._kelly_fraction(win_rate, avg_win, avg_loss)
        # Apply the conservative half-Kelly cap
        kelly_f *= self._config.kelly_fraction

        # --- Step 2: Risk-based cap ---
        max_risk_amount = equity * self._config.risk_per_trade_pct

        # --- Step 3: Kelly-sized risk amount ---
        kelly_risk = equity * kelly_f
        # Use the lesser of Kelly and hard cap
        risk_amount = min(kelly_risk, max_risk_amount)

        # --- Step 4: Convert risk to quantity ---
        quantity = risk_amount / risk_per_unit

        # --- Step 5: Notional cap (15% of equity) ---
        notional = quantity * entry_price
        max_notional = equity * self._config.max_single_position_pct
        capped = False
        cap_reason = ""

        if notional > max_notional:
            quantity = max_notional / entry_price
            notional = quantity * entry_price
            risk_amount = quantity * risk_per_unit
            capped = True
            cap_reason = f"Notional capped at {self._config.max_single_position_pct:.0%} of equity"

        # --- Step 6: Apply price/volatility multiplier ---
        if price_multiplier < 1.0:
            quantity *= price_multiplier
            notional = quantity * entry_price
            risk_amount = quantity * risk_per_unit
            if not capped:
                capped = True
                cap_reason = f"Size reduced by multiplier {price_multiplier:.2f}"

        risk_pct = risk_amount / equity if equity > 0 else 0.0

        logger.debug(
            f"PositionSizer: qty={quantity:.6f} notional={notional:.2f} "
            f"risk={risk_amount:.2f} ({risk_pct:.2%}) kelly_f={kelly_f:.4f} "
            f"capped={capped}"
        )

        return PositionSizeResult(
            quantity=round(quantity, 8),
            notional_value=round(notional, 2),
            risk_amount=round(risk_amount, 2),
            risk_pct=round(risk_pct, 6),
            method="half_kelly",
            capped=capped,
            cap_reason=cap_reason,
        )

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
