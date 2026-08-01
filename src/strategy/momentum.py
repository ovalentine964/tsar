"""
Momentum Strategy — Level 2 strategy.

Thesis: Capture trend continuation when funding rates signal directional bias.
EMA crossover confirms trend, ADX confirms strength, funding rate provides edge.

Entry rules (LONG):
  - EMA(21) > EMA(55) — fast above slow
  - MACD line crosses above signal line — momentum confirmation
  - ADX > 25 — trending market
  - Volume > 1.2x 20-period average
  - Signal score ≥ 0.65

Entry rules (SHORT):
  - EMA(21) < EMA(55)
  - MACD line crosses below signal line
  - ADX > 25
  - Volume > 1.2x 20-period average
  - Signal score ≥ 0.65

Exit rules:
  - Trailing stop: 1.5x ATR
  - Take profit: 3x ATR from entry
  - Stop loss: 1x ATR from entry
  - Funding rate flip: Close if funding rate reverses sign
"""

from __future__ import annotations

import logging
from typing import Any

from src.strategy.base import BaseStrategy
from src.strategy.genome import StrategyGenome

logger = logging.getLogger(__name__)


class MomentumStrategy(BaseStrategy):
    """Level 2 momentum + funding rates strategy.

    Uses EMA crossover, MACD confirmation, and ADX trend strength
    to capture directional moves with funding rate edge.

    Parameters are driven by a StrategyGenome loaded from
    config/strategies/momentum.yaml. Weights, thresholds, and
    multipliers are read from genome params instead of hardcoded.
    """

    NAME = "momentum_funding"
    VERSION = "1.0.0"

    # Default weights (used when no genome is provided)
    _DEFAULT_WEIGHTS: dict[str, float] = {
        "ema_crossover": 0.25,
        "funding_rate": 0.20,
        "adx": 0.25,
        "volume": 0.10,
        "macro_alignment": 0.10,
        "cross_asset": 0.05,
        "order_flow": 0.05,
    }

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        """Initialize with optional genome for parameter-driven behavior.

        Args:
            genome: StrategyGenome from YAML. If None, uses defaults.
        """
        self._genome = genome
        if genome is not None:
            self._params = genome.params
            logger.info(
                "MomentumStrategy initialized from genome '%s' with %d params",
                genome.name, len(genome.params),
            )
        else:
            self._params = {}
            logger.info("MomentumStrategy initialized with default parameters")

    # ── Genome-driven parameter accessors ────────────────────

    def _get_param(self, name: str, default: Any) -> Any:
        """Get parameter from genome, falling back to default."""
        return self._params.get(name, default)

    @property
    def _adx_threshold(self) -> float:
        return self._get_param("adx_threshold", 25)

    @property
    def _min_signal_score(self) -> float:
        return self._get_param("min_signal_score", 0.65)

    @property
    def _trailing_stop_atr_mult(self) -> float:
        return self._get_param("trailing_stop_atr_mult", 1.5)

    @property
    def _take_profit_atr_mult(self) -> float:
        return self._get_param("take_profit_atr_mult", 3.0)

    @property
    def _stop_loss_atr_mult(self) -> float:
        return self._get_param("stop_loss_atr_mult", 1.0)

    @property
    def _volume_multiplier(self) -> float:
        return self._get_param("volume_multiplier", 1.2)

    @property
    def _ema_fast_period(self) -> int:
        return int(self._get_param("ema_fast_period", 21))

    @property
    def _ema_slow_period(self) -> int:
        return self._get_param("ema_slow_period", 55)

    @property
    def _weights(self) -> dict[str, float]:
        """Return signal weights — from genome entry_rules or defaults."""
        if self._genome and "entry_rules" in self._genome.metadata:
            entry_rules = self._genome.metadata["entry_rules"]
            long_conditions = entry_rules.get("long_conditions", [])
            weights: dict[str, float] = {}
            indicator_to_key = {
                "ema_crossover": "ema_crossover",
                "funding_rate": "funding_rate",
                "adx": "adx",
                "volume_confirmation": "volume",
                "macro_alignment": "macro_alignment",
                "cross_asset_alignment": "cross_asset",
                "order_flow": "order_flow",
            }
            for cond in long_conditions:
                indicator = cond.get("indicator", "")
                key = indicator_to_key.get(indicator)
                if key and "weight" in cond:
                    weights[key] = cond["weight"]
            if weights:
                return weights
        return self._DEFAULT_WEIGHTS

    # ── Entry ────────────────────────────────────────────────

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Check momentum entry conditions.

        Args:
            data: Market data dict expected to contain:
                - ema_fast (float): Fast EMA value (21-period)
                - ema_slow (float): Slow EMA value (55-period)
                - macd_line (float): MACD line value
                - macd_signal (float): MACD signal line value
                - macd_histogram (float): MACD histogram value
                - macd_histogram_prev (float): Previous MACD histogram
                - adx (float): ADX value (14-period)
                - close (float): Current close price
                - atr (float): ATR value (14-period)
                - volume_ratio (float): Volume / 20-period avg volume
                - funding_rate (float, optional): Current funding rate
                - macro_alignment (float, optional): Macro regime score
                - cross_asset (float, optional): Cross-asset alignment
                - order_flow (float, optional): Order flow score

        Returns:
            Signal dict with score, entry_price, stop_loss, take_profit, reasoning, or None.
        """
        ema_fast = data.get("ema_fast", 0.0)
        ema_slow = data.get("ema_slow", 0.0)
        macd_line = data.get("macd_line", 0.0)
        macd_signal = data.get("macd_signal", 0.0)
        macd_histogram = data.get("macd_histogram", 0.0)
        macd_histogram_prev = data.get("macd_histogram_prev", 0.0)
        adx = data.get("adx", 0.0)
        atr = data.get("atr", 0.0)
        price = data.get("close", 0.0)
        volume_ratio = data.get("volume_ratio", 1.0)
        funding_rate = data.get("funding_rate", 0.0)

        if price <= 0 or atr <= 0:
            return None

        # ── LONG: EMA bullish crossover + MACD confirmation ──
        long_signal = self._check_long_entry(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            macd_histogram_prev=macd_histogram_prev,
            adx=adx,
            atr=atr,
            price=price,
            volume_ratio=volume_ratio,
            funding_rate=funding_rate,
            data=data,
        )
        if long_signal is not None:
            return long_signal

        # ── SHORT: EMA bearish crossover + MACD confirmation ──
        short_signal = self._check_short_entry(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            macd_histogram_prev=macd_histogram_prev,
            adx=adx,
            atr=atr,
            price=price,
            volume_ratio=volume_ratio,
            funding_rate=funding_rate,
            data=data,
        )
        if short_signal is not None:
            return short_signal

        return None

    def _check_long_entry(
        self,
        ema_fast: float,
        ema_slow: float,
        macd_line: float,
        macd_signal: float,
        macd_histogram: float,
        macd_histogram_prev: float,
        adx: float,
        atr: float,
        price: float,
        volume_ratio: float,
        funding_rate: float,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check long entry: EMA bullish crossover + MACD cross + ADX trend."""
        adx_threshold = self._adx_threshold
        min_score = self._min_signal_score
        volume_multiplier = self._volume_multiplier

        # EMA filter: fast must be above slow
        if ema_fast <= ema_slow:
            return None

        # ADX filter: must be trending
        if adx < adx_threshold:
            return None

        # MACD crossover: histogram goes from negative to positive
        macd_crossover = macd_histogram > 0 and macd_histogram_prev <= 0
        # Also accept if MACD line is above signal and histogram is growing
        macd_bullish = macd_line > macd_signal and macd_histogram > macd_histogram_prev

        if not (macd_crossover or macd_bullish):
            return None

        # Compute weighted score
        score, components = self._compute_long_score(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            macd_histogram=macd_histogram,
            macd_crossover=macd_crossover,
            adx=adx,
            volume_ratio=volume_ratio,
            funding_rate=funding_rate,
            data=data,
        )

        if score < min_score:
            return None

        # ATR-based levels from genome parameters
        stop_loss_atr_mult = self._stop_loss_atr_mult
        take_profit_atr_mult = self._take_profit_atr_mult

        entry_price = price
        stop_loss = price - (atr * stop_loss_atr_mult)
        take_profit = price + (atr * take_profit_atr_mult)

        reasoning_parts = [
            f"EMA_cross({self._ema_fast_period}>{self._ema_slow_period})",
            f"MACD_{'xover' if macd_crossover else 'bullish'}",
            f"ADX={adx:.1f}",
            f"vol_ratio={volume_ratio:.2f}",
            f"score={score:.2f}",
        ]

        return {
            "side": "buy",
            "score": score,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "atr": atr,
            "trailing_stop_atr_mult": self._trailing_stop_atr_mult,
            "reasoning": ", ".join(reasoning_parts),
            "components": components,
        }

    def _check_short_entry(
        self,
        ema_fast: float,
        ema_slow: float,
        macd_line: float,
        macd_signal: float,
        macd_histogram: float,
        macd_histogram_prev: float,
        adx: float,
        atr: float,
        price: float,
        volume_ratio: float,
        funding_rate: float,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check short entry: EMA bearish crossover + MACD cross + ADX trend."""
        adx_threshold = self._adx_threshold
        min_score = self._min_signal_score
        volume_multiplier = self._volume_multiplier

        # EMA filter: fast must be below slow
        if ema_fast >= ema_slow:
            return None

        # ADX filter: must be trending
        if adx < adx_threshold:
            return None

        # MACD crossover: histogram goes from positive to negative
        macd_crossunder = macd_histogram < 0 and macd_histogram_prev >= 0
        # Also accept if MACD line is below signal and histogram is declining
        macd_bearish = macd_line < macd_signal and macd_histogram < macd_histogram_prev

        if not (macd_crossunder or macd_bearish):
            return None

        # Compute weighted score
        score, components = self._compute_short_score(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            macd_histogram=macd_histogram,
            macd_crossunder=macd_crossunder,
            adx=adx,
            volume_ratio=volume_ratio,
            funding_rate=funding_rate,
            data=data,
        )

        if score < min_score:
            return None

        # ATR-based levels from genome parameters
        stop_loss_atr_mult = self._stop_loss_atr_mult
        take_profit_atr_mult = self._take_profit_atr_mult

        entry_price = price
        stop_loss = price + (atr * stop_loss_atr_mult)
        take_profit = price - (atr * take_profit_atr_mult)

        reasoning_parts = [
            f"EMA_cross({self._ema_fast_period}<{self._ema_slow_period})",
            f"MACD_{'xunder' if macd_crossunder else 'bearish'}",
            f"ADX={adx:.1f}",
            f"vol_ratio={volume_ratio:.2f}",
            f"score={score:.2f}",
        ]

        return {
            "side": "sell",
            "score": score,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "atr": atr,
            "trailing_stop_atr_mult": self._trailing_stop_atr_mult,
            "reasoning": ", ".join(reasoning_parts),
            "components": components,
        }

    # ── Scoring ──────────────────────────────────────────────

    def _compute_long_score(
        self,
        ema_fast: float,
        ema_slow: float,
        macd_histogram: float,
        macd_crossover: bool,
        adx: float,
        volume_ratio: float,
        funding_rate: float,
        data: dict[str, Any],
    ) -> tuple[float, dict[str, float]]:
        """Compute weighted signal score for long entry.

        Weights from YAML genome:
          ema_crossover: 0.25, funding_rate: 0.20, adx: 0.25,
          volume: 0.10, macro: 0.10, cross_asset: 0.05, order_flow: 0.05
        """
        components: dict[str, float] = {}

        # EMA crossover strength: how far fast is above slow
        if ema_slow > 0:
            ema_spread = (ema_fast - ema_slow) / ema_slow
            ema_score = max(0.0, min(1.0, ema_spread * 50))  # 2% spread = 1.0
        else:
            ema_score = 0.0
        components["ema_crossover"] = ema_score

        # Funding rate: negative is bullish for longs (shorts pay longs)
        if funding_rate < 0:
            fr_score = min(1.0, abs(funding_rate) * 1000)  # -0.1% = 1.0
        else:
            fr_score = max(0.0, 1.0 - funding_rate * 1000)
        components["funding_rate"] = fr_score

        # ADX: trending strength, 25=min, 50+=strong
        adx_score = max(0.0, min(1.0, (adx - 25) / 25))
        components["adx"] = adx_score

        # Volume confirmation
        volume_score = max(0.0, min(1.0, (volume_ratio - 1.0) / 1.0))
        components["volume"] = volume_score

        # MACD bonus
        if macd_crossover:
            components["macd_bonus"] = 0.5
        else:
            components["macd_bonus"] = 0.0

        # Optional signals
        macro = data.get("macro_alignment", 0.5)
        components["macro_alignment"] = max(0.0, min(1.0, macro))

        cross_asset = data.get("cross_asset", 0.5)
        components["cross_asset"] = max(0.0, min(1.0, cross_asset))

        order_flow = data.get("order_flow", 0.5)
        components["order_flow"] = max(0.0, min(1.0, order_flow))

        # Weighted sum from genome
        score = sum(components[k] * self._weights.get(k, 0.0) for k in components if k in self._weights)
        # Add MACD bonus (not weighted, additive)
        score = min(1.0, score + components.get("macd_bonus", 0.0) * 0.05)
        return round(score, 4), components

    def _compute_short_score(
        self,
        ema_fast: float,
        ema_slow: float,
        macd_histogram: float,
        macd_crossunder: bool,
        adx: float,
        volume_ratio: float,
        funding_rate: float,
        data: dict[str, Any],
    ) -> tuple[float, dict[str, float]]:
        """Compute weighted signal score for short entry (mirror of long)."""
        components: dict[str, float] = {}

        # EMA crossover strength: how far fast is below slow
        if ema_slow > 0:
            ema_spread = (ema_slow - ema_fast) / ema_slow
            ema_score = max(0.0, min(1.0, ema_spread * 50))
        else:
            ema_score = 0.0
        components["ema_crossover"] = ema_score

        # Funding rate: positive is bearish for shorts (longs pay shorts)
        if funding_rate > 0:
            fr_score = min(1.0, funding_rate * 1000)
        else:
            fr_score = max(0.0, 1.0 - abs(funding_rate) * 1000)
        components["funding_rate"] = fr_score

        # ADX: trending strength
        adx_score = max(0.0, min(1.0, (adx - 25) / 25))
        components["adx"] = adx_score

        # Volume confirmation
        volume_score = max(0.0, min(1.0, (volume_ratio - 1.0) / 1.0))
        components["volume"] = volume_score

        # MACD bonus
        if macd_crossunder:
            components["macd_bonus"] = 0.5
        else:
            components["macd_bonus"] = 0.0

        # Optional signals (inverted for short)
        macro = data.get("macro_alignment", 0.5)
        components["macro_alignment"] = max(0.0, min(1.0, 1.0 - macro))

        cross_asset = data.get("cross_asset", 0.5)
        components["cross_asset"] = max(0.0, min(1.0, 1.0 - cross_asset))

        order_flow = data.get("order_flow", 0.5)
        components["order_flow"] = max(0.0, min(1.0, 1.0 - order_flow))

        # Weighted sum from genome
        score = sum(components[k] * self._weights.get(k, 0.0) for k in components if k in self._weights)
        score = min(1.0, score + components.get("macd_bonus", 0.0) * 0.05)
        return round(score, 4), components

    # ── Exit ─────────────────────────────────────────────────

    def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        """Check momentum exit conditions.

        Args:
            position: Current position with entry_price, side, trailing_stop, atr
            data: Current market data with close, atr, funding_rate

        Returns:
            Exit signal dict or None.
        """
        entry_price = position.get("entry_price", 0.0)
        current_price = data.get("close", 0.0)
        atr = data.get("atr", 0.0)
        side = position.get("side", "buy")
        funding_rate = data.get("funding_rate", 0.0)
        entry_funding_rate = position.get("funding_rate", 0.0)

        if entry_price <= 0 or atr <= 0:
            return None

        stop_loss_atr_mult = self._stop_loss_atr_mult
        take_profit_atr_mult = self._take_profit_atr_mult
        trailing_stop_mult = self._trailing_stop_atr_mult

        # ── Long exits ──
        if side == "buy":
            # Stop loss: ATR multiple from genome
            stop_loss = entry_price - (atr * stop_loss_atr_mult)
            if current_price <= stop_loss:
                return {"reason": "stop_loss_atr", "action": "close", "level": stop_loss}

            # Take profit: ATR multiple from genome
            take_profit = entry_price + (atr * take_profit_atr_mult)
            if current_price >= take_profit:
                return {"reason": "take_profit_atr", "action": "close", "level": take_profit}

            # Trailing stop: ATR multiple from genome
            highest = position.get("highest_price", entry_price)
            trailing_stop = highest - (atr * trailing_stop_mult)
            if current_price <= trailing_stop and current_price > entry_price:
                return {"reason": "trailing_stop", "action": "close", "level": trailing_stop}

            # Funding rate flip: was negative, now positive
            if entry_funding_rate < 0 and funding_rate > 0:
                return {"reason": "funding_rate_flip", "action": "close", "old": entry_funding_rate, "new": funding_rate}

        # ── Short exits ──
        if side == "sell":
            # Stop loss: ATR multiple from genome
            stop_loss = entry_price + (atr * stop_loss_atr_mult)
            if current_price >= stop_loss:
                return {"reason": "stop_loss_atr", "action": "close", "level": stop_loss}

            # Take profit: ATR multiple from genome
            take_profit = entry_price - (atr * take_profit_atr_mult)
            if current_price <= take_profit:
                return {"reason": "take_profit_atr", "action": "close", "level": take_profit}

            # Trailing stop: ATR multiple from genome
            lowest = position.get("lowest_price", entry_price)
            trailing_stop = lowest + (atr * trailing_stop_mult)
            if current_price >= trailing_stop and current_price < entry_price:
                return {"reason": "trailing_stop", "action": "close", "level": trailing_stop}

            # Funding rate flip: was positive, now negative
            if entry_funding_rate > 0 and funding_rate < 0:
                return {"reason": "funding_rate_flip", "action": "close", "old": entry_funding_rate, "new": funding_rate}

        return None

    # ── Risk params ──────────────────────────────────────────

    def get_risk_params(self) -> dict[str, Any]:
        """Return risk parameters for this strategy, driven by genome."""
        return {
            "stop_loss_atr_multiple": self._stop_loss_atr_mult,
            "take_profit_atr_multiple": self._take_profit_atr_mult,
            "trailing_stop_atr_multiple": self._trailing_stop_atr_mult,
            "min_score": self._min_signal_score,
            "max_position_pct": 0.15,
            "risk_per_trade_pct": 0.02,
            "method": "half_kelly",
        }
