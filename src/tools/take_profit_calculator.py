"""
TSAR Domain Tools — Take-Profit Calculator.

Deterministic take-profit level computation using two methods:
  1. R:R-based: TP at entry + (risk * target_R_ratio)
  2. Resistance-based: TP at nearest resistance level

Enforces minimum 1.5:1 R:R ratio after fees (per C-001).
All calculations are deterministic — no LLM, no external calls.

Usage:
    calc = TakeProfitCalculator()
    tp = calc.calculate_rr(entry=50000, stop=49500, side="buy", target_rr=2.0)
    tp = calc.calculate_resistance(entry=50000, resistances=[51000, 52000], side="buy")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TakeProfitResult:
    """Result of a take-profit calculation.

    Attributes:
        take_profit_price: Calculated take-profit price.
        reward_per_unit: Reward per unit (abs(tp - entry)).
        risk_per_unit: Risk per unit (abs(entry - stop)).
        rr_ratio: Actual risk-reward ratio achieved.
        distance_pct: Distance from entry as percentage.
        method: Calculation method used.
        meets_min_rr: Whether the result meets minimum R:R.
        capped: Whether the TP was adjusted.
        cap_reason: Reason for adjustment.
    """

    take_profit_price: float
    reward_per_unit: float
    risk_per_unit: float
    rr_ratio: float
    distance_pct: float
    method: str
    meets_min_rr: bool = True
    capped: bool = False
    cap_reason: str = ""


# ═══════════════════════════════════════════════════════════════════════
# TAKE-PROFIT CALCULATOR
# ═══════════════════════════════════════════════════════════════════════


class TakeProfitCalculator:
    """Deterministic take-profit level calculator.

    Two methods for computing take-profit levels:
    1. R:R-based: Set TP to achieve a target risk-reward ratio
    2. Resistance-based: Set TP at nearest resistance level

    Enforces minimum R:R ratio (default 1.5:1) to ensure
    trades have positive expected value after fees.
    """

    description = (
        "Take-profit calculator: R:R-based and resistance-based "
        "take-profit levels with minimum R:R enforcement"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._min_rr_ratio = cfg.get("min_rr_ratio", 1.5)
        self._default_target_rr = cfg.get("default_target_rr", 2.0)
        self._max_tp_pct = cfg.get("max_tp_pct", 0.10)  # 10% max TP distance

    # ── Method 1: R:R-based ──────────────────────────────────────────

    def calculate_rr(
        self,
        entry_price: float,
        stop_loss: float,
        side: str = "buy",
        target_rr: float | None = None,
    ) -> TakeProfitResult:
        """Calculate take-profit to achieve a target risk-reward ratio.

        R:R-based TP ensures the trade has a specific reward-to-risk
        ratio. This is the primary method for systematic trading.

        For buy:  TP = entry + (risk * target_rr)
        For sell: TP = entry - (risk * target_rr)

        Where risk = |entry - stop_loss|

        Args:
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            side: "buy" or "sell".
            target_rr: Target R:R ratio (default from config, typically 2.0).

        Returns:
            TakeProfitResult with calculated TP level.
        """
        if entry_price <= 0 or stop_loss <= 0:
            return self._zero_result("Invalid inputs (entry/stop <= 0)")

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return self._zero_result("Entry and stop-loss are identical")

        target = target_rr if target_rr is not None else self._default_target_rr
        target = max(target, self._min_rr_ratio)  # Enforce minimum

        reward_per_unit = risk_per_unit * target

        tp_price = entry_price + reward_per_unit if side == "buy" else entry_price - reward_per_unit

        # Ensure TP is positive
        tp_price = max(0.0001, tp_price)

        return self._build_result(
            tp_price=tp_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            side=side,
            method="risk_reward",
        )

    # ── Method 2: Resistance-based ───────────────────────────────────

    def calculate_resistance(
        self,
        entry_price: float,
        stop_loss: float,
        resistances: list[float],
        side: str = "buy",
        buffer_pct: float = 0.001,
    ) -> TakeProfitResult:
        """Calculate take-profit at nearest resistance level.

        Structure-aware TP that respects market levels:
        - Buy: TP just below nearest resistance above entry
        - Sell: TP just above nearest support below entry

        If the resulting R:R is below minimum, extends TP to
        meet the minimum ratio.

        Args:
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            resistances: List of resistance (for buy) or support (for sell) levels.
            side: "buy" or "sell".
            buffer_pct: Buffer before the level as decimal (default 0.1%).

        Returns:
            TakeProfitResult with calculated TP level.
        """
        if entry_price <= 0 or stop_loss <= 0:
            return self._zero_result("Invalid inputs (entry/stop <= 0)")

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return self._zero_result("Entry and stop-loss are identical")

        if not resistances:
            logger.warning("No resistance levels provided, falling back to R:R-based")
            return self.calculate_rr(entry_price, stop_loss, side)

        if side == "buy":
            # Find nearest resistance above entry
            valid = [r for r in resistances if r > entry_price]
            if not valid:
                logger.warning("No resistance above entry, falling back to R:R-based")
                return self.calculate_rr(entry_price, stop_loss, side)
            nearest = min(valid)
            tp_price = nearest * (1.0 - buffer_pct)
        else:
            # Find nearest support below entry
            valid = [r for r in resistances if r < entry_price]
            if not valid:
                logger.warning("No support below entry, falling back to R:R-based")
                return self.calculate_rr(entry_price, stop_loss, side)
            nearest = max(valid)
            tp_price = nearest * (1.0 + buffer_pct)

        return self._build_result(
            tp_price=tp_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            side=side,
            method="resistance",
        )

    # ── Adaptive: Best method selector ───────────────────────────────

    def calculate_adaptive(
        self,
        entry_price: float,
        stop_loss: float,
        side: str = "buy",
        resistances: list[float] | None = None,
        target_rr: float | None = None,
        preferred_method: str = "rr",
    ) -> TakeProfitResult:
        """Calculate take-profit using the best available method.

        Selection priority:
        1. R:R-based (if preferred) — systematic and predictable
        2. Resistance-based (if levels available) — structure-aware
        3. R:R-based (fallback) — always available

        Args:
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            side: "buy" or "sell".
            resistances: Resistance/support levels (optional).
            target_rr: Target R:R ratio (optional).
            preferred_method: Preferred method ("rr" or "resistance").

        Returns:
            TakeProfitResult using the best available method.
        """
        if preferred_method == "resistance" and resistances:
            return self.calculate_resistance(entry_price, stop_loss, resistances, side)
        elif preferred_method == "rr":
            return self.calculate_rr(entry_price, stop_loss, side, target_rr)
        elif resistances:
            return self.calculate_resistance(entry_price, stop_loss, resistances, side)
        else:
            return self.calculate_rr(entry_price, stop_loss, side, target_rr)

    # ── Multiple TP levels ───────────────────────────────────────────

    def calculate_scaled_tp(
        self,
        entry_price: float,
        stop_loss: float,
        side: str = "buy",
        levels: list[float] | None = None,
    ) -> list[TakeProfitResult]:
        """Calculate multiple take-profit levels for scaled exits.

        Scaled exits allow partial profit-taking at different levels.
        Default levels: 1.5R, 2R, 3R (three targets).

        Args:
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            side: "buy" or "sell".
            levels: Custom R:R levels (default [1.5, 2.0, 3.0]).

        Returns:
            List of TakeProfitResult, one per level.
        """
        if levels is None:
            levels = [1.5, 2.0, 3.0]

        results = []
        for rr in levels:
            result = self.calculate_rr(entry_price, stop_loss, side, target_rr=rr)
            results.append(result)

        return results

    # ── Internal helpers ─────────────────────────────────────────────

    def _build_result(
        self,
        tp_price: float,
        entry_price: float,
        stop_loss: float,
        side: str,
        method: str,
    ) -> TakeProfitResult:
        """Build a TakeProfitResult and validate R:R ratio."""
        risk_per_unit = abs(entry_price - stop_loss)
        reward_per_unit = abs(tp_price - entry_price)
        rr_ratio = reward_per_unit / risk_per_unit if risk_per_unit > 0 else 0.0
        distance_pct = reward_per_unit / entry_price if entry_price > 0 else 0.0

        meets_min_rr = rr_ratio >= self._min_rr_ratio
        capped = False
        cap_reason = ""

        # If R:R is below minimum, extend TP to meet it
        if not meets_min_rr:
            min_reward = risk_per_unit * self._min_rr_ratio
            tp_price = entry_price + min_reward if side == "buy" else entry_price - min_reward

            reward_per_unit = abs(tp_price - entry_price)
            rr_ratio = self._min_rr_ratio
            distance_pct = reward_per_unit / entry_price if entry_price > 0 else 0.0
            meets_min_rr = True
            capped = True
            cap_reason = f"Extended to meet minimum {self._min_rr_ratio:.1f}:1 R:R"

        # Apply max TP distance cap
        if distance_pct > self._max_tp_pct:
            if side == "buy":
                tp_price = entry_price * (1.0 + self._max_tp_pct)
            else:
                tp_price = entry_price * (1.0 - self._max_tp_pct)

            reward_per_unit = abs(tp_price - entry_price)
            rr_ratio = reward_per_unit / risk_per_unit if risk_per_unit > 0 else 0.0
            distance_pct = reward_per_unit / entry_price if entry_price > 0 else 0.0
            capped = True
            cap_reason = f"Capped at {self._max_tp_pct:.1%} max distance"

        return TakeProfitResult(
            take_profit_price=round(tp_price, 8),
            reward_per_unit=round(reward_per_unit, 8),
            risk_per_unit=round(risk_per_unit, 8),
            rr_ratio=round(rr_ratio, 4),
            distance_pct=round(distance_pct, 6),
            method=method,
            meets_min_rr=meets_min_rr,
            capped=capped,
            cap_reason=cap_reason,
        )

    @staticmethod
    def _zero_result(reason: str) -> TakeProfitResult:
        """Return a zero result with error reason."""
        return TakeProfitResult(
            take_profit_price=0.0,
            reward_per_unit=0.0,
            risk_per_unit=0.0,
            rr_ratio=0.0,
            distance_pct=0.0,
            method="none",
            meets_min_rr=False,
            capped=True,
            cap_reason=reason,
        )
