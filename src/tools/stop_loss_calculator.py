"""
TSAR Domain Tools — Stop-Loss Calculator.

Deterministic stop-loss level computation using three methods:
  1. ATR-based: Stop at entry ± N * ATR (volatility-adaptive)
  2. Percentage-based: Stop at fixed % from entry
  3. Support-based: Stop below nearest support level

All calculations are deterministic — no LLM, no external calls.
Integrates with RiskGovernor's max_stop_loss_pct validation.

Usage:
    calc = StopLossCalculator()
    sl = calc.calculate_atr(entry=50000, atr=500, side="buy", multiplier=1.5)
    sl = calc.calculate_percentage(entry=50000, pct=0.02, side="buy")
    sl = calc.calculate_support(entry=50000, supports=[49500, 49000], side="buy")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StopLossResult:
    """Result of a stop-loss calculation.

    Attributes:
        stop_price: Calculated stop-loss price.
        distance_pct: Distance from entry as percentage.
        distance_usd: Absolute distance from entry in USD.
        risk_per_unit: Risk per unit (abs(entry - stop)).
        method: Calculation method used.
        atr_multiple: ATR multiple (for ATR method only).
        capped: Whether the stop was capped by max distance.
        cap_reason: Reason for capping.
    """

    stop_price: float
    distance_pct: float
    distance_usd: float
    risk_per_unit: float
    method: str
    atr_multiple: float = 0.0
    capped: bool = False
    cap_reason: str = ""


@dataclass(frozen=True)
class ATRResult:
    """ATR (Average True Range) calculation result.

    Attributes:
        atr: Current ATR value.
        atr_pct: ATR as percentage of current price.
        true_ranges: Individual true range values.
        period: ATR period used.
    """

    atr: float
    atr_pct: float
    true_ranges: tuple[float, ...]
    period: int


# ═══════════════════════════════════════════════════════════════════════
# STOP-LOSS CALCULATOR
# ═══════════════════════════════════════════════════════════════════════


class StopLossCalculator:
    """Deterministic stop-loss level calculator.

    Three methods for computing stop-loss levels:
    1. ATR-based: Adaptive to current volatility
    2. Percentage-based: Simple fixed-percentage stops
    3. Support-based: Structure-aware stops at support/resistance

    All methods respect the max_stop_pct cap (default 2%) from
    RiskGovernor configuration to prevent excessively wide stops.
    """

    description = (
        "Stop-loss calculator: ATR-based, percentage-based, "
        "and support/resistance-based stop-loss levels"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._max_stop_pct = cfg.get("max_stop_pct", 0.02)  # 2% default
        self._atr_period = cfg.get("atr_period", 14)
        self._default_atr_multiplier = cfg.get("default_atr_multiplier", 1.5)
        self._min_stop_pct = cfg.get("min_stop_pct", 0.001)  # 0.1% minimum

    # ── Method 1: ATR-based ──────────────────────────────────────────

    def calculate_atr(
        self,
        entry_price: float,
        atr: float,
        side: str = "buy",
        multiplier: float | None = None,
    ) -> StopLossResult:
        """Calculate stop-loss using ATR (Average True Range).

        ATR-based stops adapt to current market volatility:
        - Higher volatility → wider stop (avoids noise)
        - Lower volatility → tighter stop (locks in gains)

        For buy: stop = entry - (atr * multiplier)
        For sell: stop = entry + (atr * multiplier)

        Args:
            entry_price: Entry price.
            atr: Current ATR value.
            side: "buy" or "sell".
            multiplier: ATR multiplier (default from config, typically 1.5).

        Returns:
            StopLossResult with calculated stop level.
        """
        if entry_price <= 0 or atr <= 0:
            return self._zero_result("Invalid inputs (entry/atr <= 0)")

        mult = multiplier if multiplier is not None else self._default_atr_multiplier
        stop_distance = atr * mult

        if side == "buy":
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance

        # Ensure stop is positive
        stop_price = max(0.0001, stop_price)

        return self._build_result(
            stop_price=stop_price,
            entry_price=entry_price,
            side=side,
            method="atr",
            atr_multiple=mult,
        )

    @staticmethod
    def calculate_atr_from_ohlcv(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> ATRResult:
        """Calculate ATR from OHLCV data.

        True Range = max(high - low, |high - prev_close|, |low - prev_close|)
        ATR = SMA of True Range over period.

        Args:
            highs: High prices (oldest first).
            lows: Low prices (oldest first).
            closes: Close prices (oldest first).
            period: ATR period (default 14).

        Returns:
            ATRResult with ATR value and components.
        """
        if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
            return ATRResult(atr=0.0, atr_pct=0.0, true_ranges=(), period=period)

        h = np.array(highs, dtype=float)
        l = np.array(lows, dtype=float)
        c = np.array(closes, dtype=float)

        # True Range calculation
        prev_c = c[:-1]
        tr1 = h[1:] - l[1:]
        tr2 = np.abs(h[1:] - prev_c)
        tr3 = np.abs(l[1:] - prev_c)
        true_ranges = np.maximum(tr1, np.maximum(tr2, tr3))

        # ATR = SMA of last `period` true ranges
        if len(true_ranges) < period:
            return ATRResult(atr=0.0, atr_pct=0.0, true_ranges=(), period=period)

        atr = float(np.mean(true_ranges[-period:]))
        current_price = closes[-1]
        atr_pct = (atr / current_price * 100) if current_price > 0 else 0.0

        return ATRResult(
            atr=round(atr, 8),
            atr_pct=round(atr_pct, 4),
            true_ranges=tuple(round(float(tr), 8) for tr in true_ranges[-period:]),
            period=period,
        )

    # ── Method 2: Percentage-based ───────────────────────────────────

    def calculate_percentage(
        self,
        entry_price: float,
        pct: float | None = None,
        side: str = "buy",
    ) -> StopLossResult:
        """Calculate stop-loss at a fixed percentage from entry.

        Simple and predictable. Works well for:
        - Low-volatility assets
        - Tight risk management
        - Quick scalp trades

        For buy: stop = entry * (1 - pct)
        For sell: stop = entry * (1 + pct)

        Args:
            entry_price: Entry price.
            pct: Stop distance as decimal (e.g., 0.02 for 2%).
                 Defaults to max_stop_pct from config.
            side: "buy" or "sell".

        Returns:
            StopLossResult with calculated stop level.
        """
        if entry_price <= 0:
            return self._zero_result("Invalid entry price (<= 0)")

        stop_pct = pct if pct is not None else self._max_stop_pct
        stop_pct = max(self._min_stop_pct, min(stop_pct, 0.5))  # Clamp 0.1%-50%

        if side == "buy":
            stop_price = entry_price * (1.0 - stop_pct)
        else:
            stop_price = entry_price * (1.0 + stop_pct)

        return self._build_result(
            stop_price=stop_price,
            entry_price=entry_price,
            side=side,
            method="percentage",
        )

    # ── Method 3: Support-based ──────────────────────────────────────

    def calculate_support(
        self,
        entry_price: float,
        supports: list[float],
        side: str = "buy",
        buffer_pct: float = 0.001,
    ) -> StopLossResult:
        """Calculate stop-loss below nearest support level.

        Structure-aware stops that respect market levels:
        - Buy: Stop just below the nearest support below entry
        - Sell: Stop just above the nearest resistance above entry

        The buffer_pct adds a small cushion beyond the level to
        avoid getting stopped by noise at the exact level.

        Args:
            entry_price: Entry price.
            supports: List of support (for buy) or resistance (for sell) levels.
            side: "buy" or "sell".
            buffer_pct: Buffer beyond the level as decimal (default 0.1%).

        Returns:
            StopLossResult with calculated stop level.
        """
        if entry_price <= 0:
            return self._zero_result("Invalid entry price (<= 0)")

        if not supports:
            # Fallback to percentage-based
            logger.warning("No support levels provided, falling back to percentage-based")
            return self.calculate_percentage(entry_price, side=side)

        if side == "buy":
            # Find nearest support below entry
            valid_supports = [s for s in supports if s < entry_price]
            if not valid_supports:
                logger.warning("No support below entry, falling back to percentage-based")
                return self.calculate_percentage(entry_price, side=side)
            nearest = max(valid_supports)
            stop_price = nearest * (1.0 - buffer_pct)
        else:
            # Find nearest resistance above entry
            valid_resistances = [s for s in supports if s > entry_price]
            if not valid_resistances:
                logger.warning("No resistance above entry, falling back to percentage-based")
                return self.calculate_percentage(entry_price, side=side)
            nearest = min(valid_resistances)
            stop_price = nearest * (1.0 + buffer_pct)

        return self._build_result(
            stop_price=stop_price,
            entry_price=entry_price,
            side=side,
            method="support",
        )

    # ── Adaptive: Best method selector ───────────────────────────────

    def calculate_adaptive(
        self,
        entry_price: float,
        side: str = "buy",
        atr: float | None = None,
        supports: list[float] | None = None,
        preferred_method: str = "atr",
    ) -> StopLossResult:
        """Calculate stop-loss using the best available method.

        Selection priority:
        1. ATR-based (if ATR available) — most adaptive
        2. Support-based (if support levels available) — structure-aware
        3. Percentage-based (fallback) — simple and predictable

        Args:
            entry_price: Entry price.
            side: "buy" or "sell".
            atr: Current ATR value (optional).
            supports: Support/resistance levels (optional).
            preferred_method: Preferred method override.

        Returns:
            StopLossResult using the best available method.
        """
        if preferred_method == "atr" and atr is not None and atr > 0:
            return self.calculate_atr(entry_price, atr, side)
        elif preferred_method == "support" and supports:
            return self.calculate_support(entry_price, supports, side)
        elif atr is not None and atr > 0:
            return self.calculate_atr(entry_price, atr, side)
        elif supports:
            return self.calculate_support(entry_price, supports, side)
        else:
            return self.calculate_percentage(entry_price, side=side)

    # ── Internal helpers ─────────────────────────────────────────────

    def _build_result(
        self,
        stop_price: float,
        entry_price: float,
        side: str,
        method: str,
        atr_multiple: float = 0.0,
    ) -> StopLossResult:
        """Build a StopLossResult and apply max distance cap."""
        distance_usd = abs(entry_price - stop_price)
        distance_pct = distance_usd / entry_price if entry_price > 0 else 0.0

        capped = False
        cap_reason = ""

        # Apply max stop distance cap
        if distance_pct > self._max_stop_pct:
            if side == "buy":
                stop_price = entry_price * (1.0 - self._max_stop_pct)
            else:
                stop_price = entry_price * (1.0 + self._max_stop_pct)

            distance_usd = abs(entry_price - stop_price)
            distance_pct = distance_usd / entry_price if entry_price > 0 else 0.0
            capped = True
            cap_reason = f"Capped at {self._max_stop_pct:.1%} max distance"

        return StopLossResult(
            stop_price=round(stop_price, 8),
            distance_pct=round(distance_pct, 6),
            distance_usd=round(distance_usd, 8),
            risk_per_unit=round(distance_usd, 8),
            method=method,
            atr_multiple=round(atr_multiple, 2),
            capped=capped,
            cap_reason=cap_reason,
        )

    @staticmethod
    def _zero_result(reason: str) -> StopLossResult:
        """Return a zero result with error reason."""
        return StopLossResult(
            stop_price=0.0,
            distance_pct=0.0,
            distance_usd=0.0,
            risk_per_unit=0.0,
            method="none",
            capped=True,
            cap_reason=reason,
        )
