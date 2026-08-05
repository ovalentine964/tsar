"""
TSAR RSI Filter — RSI confirmation for entry signals.

RSI Confirmation Rules:
  - BUY:  RSI < 40 (oversold zone) OR RSI crossing above 30 from below
  - SELL: RSI > 60 (overbought zone) OR RSI crossing below 70 from above
  - Divergence detection: price makes new low but RSI makes higher low (bullish)
  - Divergence detection: price makes new high but RSI makes lower high (bearish)

RSI Parameters (genome-tunable):
  - period: 14 (default)
  - oversold: 30
  - overbought: 70
  - neutral_low: 40
  - neutral_high: 60
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class RSIState(StrEnum):
    """RSI condition state."""

    OVERSOLD = "oversold"
    NEAR_OVERSOLD = "near_oversold"
    NEUTRAL = "neutral"
    NEAR_OVERBOUGHT = "near_overbought"
    OVERBOUGHT = "overbought"


class RSISignal(StrEnum):
    """RSI confirmation signal."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    BULLISH_DIVERGENCE = "bullish_divergence"
    BEARISH_DIVERGENCE = "bearish_divergence"


@dataclass(frozen=True)
class RSIResult:
    """RSI analysis result."""

    value: float
    state: RSIState
    signal: RSISignal
    prev_value: float
    crossing_up: bool
    crossing_down: bool
    divergence: str | None  # "bullish", "bearish", None
    score: float  # 0.0 – 1.0 confirmation strength

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": round(self.value, 2),
            "state": self.state.value,
            "signal": self.signal.value,
            "prev_value": round(self.prev_value, 2),
            "crossing_up": self.crossing_up,
            "crossing_down": self.crossing_down,
            "divergence": self.divergence,
            "score": round(self.score, 3),
        }


class RSIFilter:
    """RSI confirmation filter for TSAR entry pipeline.

    Genome-tunable parameters control sensitivity.
    """

    DEFAULT_GENOME = {
        "rsi_period": 14,
        "oversold": 30.0,
        "overbought": 70.0,
        "neutral_low": 40.0,
        "neutral_high": 60.0,
        "divergence_lookback": 20,
        "crossing_threshold": 5.0,
    }

    def __init__(self, genome: dict[str, Any] | None = None) -> None:
        self.genome = {**self.DEFAULT_GENOME, **(genome or {})}
        self._rsi_history: list[float] = []
        self._price_history: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        closes: list[float],
        direction_hint: str = "neutral",
    ) -> RSIResult:
        """Analyze RSI and return confirmation signal.

        Args:
            closes: Close prices (need at least rsi_period + 1)
            direction_hint: Expected direction from trend layer ("bullish"/"bearish"/"neutral")

        Returns:
            RSIResult with confirmation score.
        """
        period = int(self.genome["rsi_period"])
        if len(closes) < period + 1:
            return self._neutral_result()

        rsi_values = self._compute_rsi(closes, period)
        current_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2] if len(rsi_values) >= 2 else current_rsi

        # Track history for divergence
        self._rsi_history.append(current_rsi)
        self._price_history.append(closes[-1])
        max_history = int(self.genome["divergence_lookback"]) * 2
        self._rsi_history = self._rsi_history[-max_history:]
        self._price_history = self._price_history[-max_history:]

        # Determine state
        state = self._classify_state(current_rsi)

        # Detect crossings
        crossing_up = self._detect_crossing_up(prev_rsi, current_rsi)
        crossing_down = self._detect_crossing_down(prev_rsi, current_rsi)

        # Detect divergence
        divergence = self._detect_divergence(closes)

        # Generate signal and score
        signal, score = self._generate_signal(
            current_rsi,
            state,
            crossing_up,
            crossing_down,
            divergence,
            direction_hint,
        )

        result = RSIResult(
            value=current_rsi,
            state=state,
            signal=signal,
            prev_value=prev_rsi,
            crossing_up=crossing_up,
            crossing_down=crossing_down,
            divergence=divergence,
            score=score,
        )

        logger.debug(
            "RSI filter: value=%.1f state=%s signal=%s score=%.2f hint=%s",
            current_rsi,
            state.value,
            signal.value,
            score,
            direction_hint,
        )
        return result

    def update_genome(self, new_genome: dict[str, Any]) -> None:
        """Update genome parameters (from StrategyGeneticist)."""
        self.genome.update(new_genome)
        logger.info("RSI filter genome updated: %s", new_genome)

    # ------------------------------------------------------------------
    # RSI Computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_rsi(closes: list[float], period: int) -> list[float]:
        """Compute RSI series using exponential moving average method."""
        arr = np.array(closes, dtype=float)
        deltas = np.diff(arr)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # Wilder's smoothing (EMA with alpha = 1/period)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        rsi_values: list[float] = []
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

        return rsi_values

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_state(self, rsi: float) -> RSIState:
        """Classify RSI into a state bucket."""
        if rsi <= self.genome["oversold"]:
            return RSIState.OVERSOLD
        if rsi <= self.genome["neutral_low"]:
            return RSIState.NEAR_OVERSOLD
        if rsi >= self.genome["overbought"]:
            return RSIState.OVERBOUGHT
        if rsi >= self.genome["neutral_high"]:
            return RSIState.NEAR_OVERBOUGHT
        return RSIState.NEUTRAL

    def _detect_crossing_up(self, prev: float, current: float) -> bool:
        """Detect RSI crossing up through oversold level."""
        self.genome["oversold"] + self.genome["crossing_threshold"]
        return prev <= self.genome["oversold"] and current > self.genome["oversold"]

    def _detect_crossing_down(self, prev: float, current: float) -> bool:
        """Detect RSI crossing down through overbought level."""
        self.genome["overbought"] - self.genome["crossing_threshold"]
        return prev >= self.genome["overbought"] and current < self.genome["overbought"]

    # ------------------------------------------------------------------
    # Divergence Detection
    # ------------------------------------------------------------------

    def _detect_divergence(self, closes: list[float]) -> str | None:
        """Detect RSI-price divergence.

        Bullish divergence: price makes lower low, RSI makes higher low.
        Bearish divergence: price makes higher high, RSI makes lower high.
        """
        lookback = int(self.genome["divergence_lookback"])
        if len(self._price_history) < lookback or len(self._rsi_history) < lookback:
            return None

        prices = self._price_history[-lookback:]
        rsis = self._rsi_history[-lookback:]

        # Find recent lows/highs
        price_lows = self._find_local_extremes(prices, mode="low")
        price_highs = self._find_local_extremes(prices, mode="high")
        rsi_lows = self._find_local_extremes(rsis, mode="low")
        rsi_highs = self._find_local_extremes(rsis, mode="high")

        # Bullish divergence: price lower low + RSI higher low
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            if price_lows[-1] < price_lows[-2] and rsi_lows[-1] > rsi_lows[-2]:
                return "bullish"

        # Bearish divergence: price higher high + RSI lower high
        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            if price_highs[-1] > price_highs[-2] and rsi_highs[-1] < rsi_highs[-2]:
                return "bearish"

        return None

    @staticmethod
    def _find_local_extremes(
        values: list[float], mode: str = "low", window: int = 3
    ) -> list[float]:
        """Find local minima or maxima in a series."""
        extremes: list[float] = []
        for i in range(window, len(values) - window):
            segment = values[i - window : i + window + 1]
            if (
                mode == "low"
                and values[i] == min(segment)
                or mode == "high"
                and values[i] == max(segment)
            ):
                extremes.append(values[i])
        return extremes

    # ------------------------------------------------------------------
    # Signal Generation
    # ------------------------------------------------------------------

    def _generate_signal(
        self,
        rsi: float,
        state: RSIState,
        crossing_up: bool,
        crossing_down: bool,
        divergence: str | None,
        direction_hint: str,
    ) -> tuple[RSISignal, float]:
        """Generate RSI signal and confirmation score."""
        score = 0.0
        signal = RSISignal.NEUTRAL

        # Base score from RSI zone
        if state == RSIState.OVERSOLD:
            score += 0.4
            signal = RSISignal.BULLISH
        elif state == RSIState.NEAR_OVERSOLD:
            score += 0.2
            signal = RSISignal.BULLISH
        elif state == RSIState.OVERBOUGHT:
            score += 0.4
            signal = RSISignal.BEARISH
        elif state == RSIState.NEAR_OVERBOUGHT:
            score += 0.2
            signal = RSISignal.BEARISH

        # Crossing bonus
        if crossing_up:
            score += 0.3
            signal = RSISignal.BULLISH
        if crossing_down:
            score += 0.3
            signal = RSISignal.BEARISH

        # Divergence bonus
        if divergence == "bullish":
            score += 0.3
            signal = RSISignal.BULLISH_DIVERGENCE
        elif divergence == "bearish":
            score += 0.3
            signal = RSISignal.BEARISH_DIVERGENCE

        # Direction alignment bonus
        if (
            direction_hint == "bullish"
            and signal
            in (
                RSISignal.BULLISH,
                RSISignal.BULLISH_DIVERGENCE,
            )
            or direction_hint == "bearish"
            and signal
            in (
                RSISignal.BEARISH,
                RSISignal.BEARISH_DIVERGENCE,
            )
        ):
            score += 0.1

        # Mismatch penalty
        if (
            direction_hint == "bullish"
            and signal
            in (
                RSISignal.BEARISH,
                RSISignal.BEARISH_DIVERGENCE,
            )
            or direction_hint == "bearish"
            and signal
            in (
                RSISignal.BULLISH,
                RSISignal.BULLISH_DIVERGENCE,
            )
        ):
            score -= 0.3

        score = max(0.0, min(1.0, score))
        return signal, score

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _neutral_result(self) -> RSIResult:
        """Return a neutral RSIResult when insufficient data."""
        return RSIResult(
            value=50.0,
            state=RSIState.NEUTRAL,
            signal=RSISignal.NEUTRAL,
            prev_value=50.0,
            crossing_up=False,
            crossing_down=False,
            divergence=None,
            score=0.0,
        )
