"""
VMPM Candlestick Confirmer — Candlestick pattern confirmation for entries.

Patterns Detected:
  REVERSAL (high score):
    - Engulfing (bullish/bearish)
    - Pin bar / Hammer / Shooting star
    - Morning/Evening star (3-candle)
    - Doji at key level

  CONTINUATION (medium score):
    - Three white soldiers / Three black crows
    - Rising/Falling three methods

  WEAK (low score):
    - Spinning top
    - Inside bar (breakout dependent)

Each pattern returns a score 0.0 – 1.0 based on reliability
and alignment with the expected direction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class CandlePattern(StrEnum):
    """Detected candlestick patterns."""

    BULLISH_ENGULFING = "bullish_engulfing"
    BEARISH_ENGULFING = "bearish_engulfing"
    BULLISH_PIN_BAR = "bullish_pin_bar"
    BEARISH_PIN_BAR = "bearish_pin_bar"
    HAMMER = "hammer"
    SHOOTING_STAR = "shooting_star"
    MORNING_STAR = "morning_star"
    EVENING_STAR = "evening_star"
    BULLISH_DOJI = "bullish_doji"
    BEARISH_DOJI = "bearish_doji"
    THREE_WHITE_SOLDIERS = "three_white_soldiers"
    THREE_BLACK_CROWS = "three_black_crows"
    INSIDE_BAR = "inside_bar"
    NONE = "none"


@dataclass(frozen=True)
class CandleResult:
    """Candlestick analysis result."""

    pattern: CandlePattern
    direction: str  # "bullish", "bearish", "neutral"
    score: float  # 0.0 – 1.0
    at_key_level: bool  # Whether candle is at a S/R level
    body_ratio: float  # Body size relative to range
    wick_ratio: float  # Wick ratio for pin bars

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern.value,
            "direction": self.direction,
            "score": round(self.score, 3),
            "at_key_level": self.at_key_level,
            "body_ratio": round(self.body_ratio, 3),
            "wick_ratio": round(self.wick_ratio, 3),
        }


class CandlestickConfirmer:
    """Candlestick pattern confirmation for VMPM entry pipeline.

    Analyzes recent candles for reversal and continuation patterns.
    Score is boosted when pattern appears at a key S/R level.
    """

    DEFAULT_GENOME = {
        "engulfing_body_ratio": 0.6,
        "pin_bar_wick_ratio": 0.6,
        "doji_body_threshold": 0.1,
        "star_body_ratio": 0.3,
        "level_proximity_atr_mult": 0.5,
        "min_candles": 5,
    }

    # Pattern base scores (reliability ratings)
    PATTERN_SCORES = {
        CandlePattern.BULLISH_ENGULFING: 0.85,
        CandlePattern.BEARISH_ENGULFING: 0.85,
        CandlePattern.BULLISH_PIN_BAR: 0.80,
        CandlePattern.BEARISH_PIN_BAR: 0.80,
        CandlePattern.HAMMER: 0.75,
        CandlePattern.SHOOTING_STAR: 0.75,
        CandlePattern.MORNING_STAR: 0.90,
        CandlePattern.EVENING_STAR: 0.90,
        CandlePattern.BULLISH_DOJI: 0.50,
        CandlePattern.BEARISH_DOJI: 0.50,
        CandlePattern.THREE_WHITE_SOLDIERS: 0.70,
        CandlePattern.THREE_BLACK_CROWS: 0.70,
        CandlePattern.INSIDE_BAR: 0.40,
        CandlePattern.NONE: 0.0,
    }

    def __init__(self, genome: dict[str, Any] | None = None) -> None:
        self.genome = {**self.DEFAULT_GENOME, **(genome or {})}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        ohlcv: list[list[float]],
        key_levels: list[float] | None = None,
        direction_hint: str = "neutral",
    ) -> CandleResult:
        """Analyze recent candles for confirming patterns.

        Args:
            ohlcv: List of [open, high, low, close, volume] candles (most recent last)
            key_levels: List of S/R price levels to check proximity
            direction_hint: Expected direction from trend layer

        Returns:
            CandleResult with pattern and confirmation score.
        """
        if len(ohlcv) < self.genome["min_candles"]:
            return self._neutral_result()

        candles = np.array(ohlcv[-10:], dtype=float)  # Last 10 candles
        o, h, l, c = candles[:, 0], candles[:, 1], candles[:, 2], candles[:, 3]

        # Check if current candle is at a key level
        at_level = self._check_level_proximity(c[-1], key_levels, h, l)

        # Detect all patterns
        patterns = self._detect_all_patterns(o, h, l, c)

        # Pick best pattern aligned with direction
        best_pattern, best_score = self._select_best_pattern(
            patterns,
            direction_hint,
            at_level,
        )

        # Compute body/wick ratios for the last candle
        body_ratio = self._body_ratio(o[-1], h[-1], l[-1], c[-1])
        wick_ratio = self._wick_ratio(o[-1], h[-1], l[-1], c[-1])

        # Determine direction
        direction = "neutral"
        if best_pattern in (
            CandlePattern.BULLISH_ENGULFING,
            CandlePattern.BULLISH_PIN_BAR,
            CandlePattern.HAMMER,
            CandlePattern.MORNING_STAR,
            CandlePattern.BULLISH_DOJI,
            CandlePattern.THREE_WHITE_SOLDIERS,
        ):
            direction = "bullish"
        elif best_pattern in (
            CandlePattern.BEARISH_ENGULFING,
            CandlePattern.BEARISH_PIN_BAR,
            CandlePattern.SHOOTING_STAR,
            CandlePattern.EVENING_STAR,
            CandlePattern.BEARISH_DOJI,
            CandlePattern.THREE_BLACK_CROWS,
        ):
            direction = "bearish"

        result = CandleResult(
            pattern=best_pattern,
            direction=direction,
            score=best_score,
            at_key_level=at_level,
            body_ratio=body_ratio,
            wick_ratio=wick_ratio,
        )

        logger.debug(
            "Candlestick: pattern=%s direction=%s score=%.2f at_level=%s",
            best_pattern.value,
            direction,
            best_score,
            at_level,
        )
        return result

    def update_genome(self, new_genome: dict[str, Any]) -> None:
        """Update genome parameters (from StrategyGeneticist)."""
        self.genome.update(new_genome)

    # ------------------------------------------------------------------
    # Pattern Detection
    # ------------------------------------------------------------------

    def _detect_all_patterns(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
    ) -> list[tuple[CandlePattern, float]]:
        """Detect all candlestick patterns and return with raw scores."""
        patterns: list[tuple[CandlePattern, float]] = []

        # Single candle patterns
        patterns.extend(self._detect_pin_bars(o, h, l, c))
        patterns.extend(self._detect_doji(o, h, l, c))
        patterns.extend(self._detect_hammer_shooting_star(o, h, l, c))

        # Two candle patterns
        patterns.extend(self._detect_engulfing(o, h, l, c))
        patterns.extend(self._detect_inside_bar(o, h, l, c))

        # Three candle patterns
        patterns.extend(self._detect_stars(o, h, l, c))
        patterns.extend(self._detect_soldiers_crows(o, h, l, c))

        return patterns

    def _detect_engulfing(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
    ) -> list[tuple[CandlePattern, float]]:
        """Detect bullish/bearish engulfing patterns."""
        patterns: list[tuple[CandlePattern, float]] = []
        body_threshold = self.genome["engulfing_body_ratio"]

        if len(o) < 2:
            return patterns

        # Current and previous candle
        prev_o, prev_c = o[-2], c[-2]
        curr_o, curr_c = o[-1], c[-1]
        prev_body = abs(prev_c - prev_o)
        curr_body = abs(curr_c - curr_o)

        if curr_body < prev_body * body_threshold:
            return patterns

        # Bullish engulfing: prev bearish, curr bullish, curr body engulfs prev
        if prev_c < prev_o and curr_c > curr_o and curr_o <= prev_c and curr_c >= prev_o:
            patterns.append((CandlePattern.BULLISH_ENGULFING, 0.85))

        # Bearish engulfing: prev bullish, curr bearish, curr body engulfs prev
        if prev_c > prev_o and curr_c < curr_o and curr_o >= prev_c and curr_c <= prev_o:
            patterns.append((CandlePattern.BEARISH_ENGULFING, 0.85))

        return patterns

    def _detect_pin_bars(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
    ) -> list[tuple[CandlePattern, float]]:
        """Detect pin bars (long wick, small body)."""
        patterns: list[tuple[CandlePattern, float]] = []
        wick_threshold = self.genome["pin_bar_wick_ratio"]

        range_val = h[-1] - l[-1]
        if range_val == 0:
            return patterns

        body = abs(c[-1] - o[-1])
        upper_wick = h[-1] - max(o[-1], c[-1])
        lower_wick = min(o[-1], c[-1]) - l[-1]

        # Bullish pin bar: long lower wick
        if lower_wick / range_val >= wick_threshold and body / range_val < 0.3:
            patterns.append((CandlePattern.BULLISH_PIN_BAR, 0.80))

        # Bearish pin bar: long upper wick
        if upper_wick / range_val >= wick_threshold and body / range_val < 0.3:
            patterns.append((CandlePattern.BEARISH_PIN_BAR, 0.80))

        return patterns

    def _detect_doji(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
    ) -> list[tuple[CandlePattern, float]]:
        """Detect doji candles (very small body)."""
        patterns: list[tuple[CandlePattern, float]] = []
        threshold = self.genome["doji_body_threshold"]

        range_val = h[-1] - l[-1]
        if range_val == 0:
            return patterns

        body = abs(c[-1] - o[-1])
        if body / range_val <= threshold:
            # Direction based on preceding candles
            if len(c) >= 3 and c[-3] > c[-2]:
                patterns.append((CandlePattern.BULLISH_DOJI, 0.50))
            elif len(c) >= 3 and c[-3] < c[-2]:
                patterns.append((CandlePattern.BEARISH_DOJI, 0.50))

        return patterns

    def _detect_hammer_shooting_star(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
    ) -> list[tuple[CandlePattern, float]]:
        """Detect hammer (bullish) and shooting star (bearish)."""
        patterns: list[tuple[CandlePattern, float]] = []

        range_val = h[-1] - l[-1]
        if range_val == 0:
            return patterns

        body = abs(c[-1] - o[-1])
        upper_wick = h[-1] - max(o[-1], c[-1])
        lower_wick = min(o[-1], c[-1]) - l[-1]

        # Hammer: small body at top, long lower wick (2x+ body)
        if lower_wick >= body * 2 and upper_wick < body * 0.5:
            patterns.append((CandlePattern.HAMMER, 0.75))

        # Shooting star: small body at bottom, long upper wick (2x+ body)
        if upper_wick >= body * 2 and lower_wick < body * 0.5:
            patterns.append((CandlePattern.SHOOTING_STAR, 0.75))

        return patterns

    def _detect_inside_bar(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
    ) -> list[tuple[CandlePattern, float]]:
        """Detect inside bar (current range within previous range)."""
        patterns: list[tuple[CandlePattern, float]] = []

        if len(o) < 2:
            return patterns

        if h[-1] <= h[-2] and l[-1] >= l[-2]:
            patterns.append((CandlePattern.INSIDE_BAR, 0.40))

        return patterns

    def _detect_stars(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
    ) -> list[tuple[CandlePattern, float]]:
        """Detect morning star (bullish) and evening star (bearish) 3-candle patterns."""
        patterns: list[tuple[CandlePattern, float]] = []
        body_threshold = self.genome["star_body_ratio"]

        if len(o) < 3:
            return patterns

        # Candle ranges
        ranges = h[-3:] - l[-3:]
        if any(r == 0 for r in ranges):
            return patterns

        # Morning star: big bearish, small body, big bullish
        abs(c[-3] - o[-3])
        c1_body = abs(c[-2] - o[-2])
        abs(c[-1] - o[-1])

        if (
            c[-3] < o[-3]  # First candle bearish
            and c1_body / ranges[1] < body_threshold  # Middle candle small
            and c[-1] > o[-1]  # Third candle bullish
            and c[-1] > (o[-3] + c[-3]) / 2
        ):  # Closes above midpoint of first
            patterns.append((CandlePattern.MORNING_STAR, 0.90))

        # Evening star: big bullish, small body, big bearish
        if (
            c[-3] > o[-3]  # First candle bullish
            and c1_body / ranges[1] < body_threshold  # Middle candle small
            and c[-1] < o[-1]  # Third candle bearish
            and c[-1] < (o[-3] + c[-3]) / 2
        ):  # Closes below midpoint of first
            patterns.append((CandlePattern.EVENING_STAR, 0.90))

        return patterns

    def _detect_soldiers_crows(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
    ) -> list[tuple[CandlePattern, float]]:
        """Detect three white soldiers (bullish) and three black crows (bearish)."""
        patterns: list[tuple[CandlePattern, float]] = []

        if len(o) < 3:
            return patterns

        # Three white soldiers: 3 consecutive bullish candles, each closing higher
        if all(c[-i] > o[-i] for i in range(1, 4)) and c[-1] > c[-2] > c[-3]:
            patterns.append((CandlePattern.THREE_WHITE_SOLDIERS, 0.70))

        # Three black crows: 3 consecutive bearish candles, each closing lower
        if all(c[-i] < o[-i] for i in range(1, 4)) and c[-1] < c[-2] < c[-3]:
            patterns.append((CandlePattern.THREE_BLACK_CROWS, 0.70))

        return patterns

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_level_proximity(
        self,
        price: float,
        key_levels: list[float] | None,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> bool:
        """Check if current price is near a key S/R level."""
        if not key_levels:
            return False

        # Use ATR as proximity threshold
        atr = float(np.mean(highs[-5:] - lows[-5:])) if len(highs) >= 5 else 0.0
        threshold = atr * self.genome["level_proximity_atr_mult"]

        return any(abs(price - level) <= threshold for level in key_levels)

    def _select_best_pattern(
        self,
        patterns: list[tuple[CandlePattern, float]],
        direction_hint: str,
        at_level: bool,
    ) -> tuple[CandlePattern, float]:
        """Select best pattern aligned with direction hint."""
        if not patterns:
            return CandlePattern.NONE, 0.0

        # Filter by direction alignment
        bullish_patterns = {
            CandlePattern.BULLISH_ENGULFING,
            CandlePattern.BULLISH_PIN_BAR,
            CandlePattern.HAMMER,
            CandlePattern.MORNING_STAR,
            CandlePattern.BULLISH_DOJI,
            CandlePattern.THREE_WHITE_SOLDIERS,
        }
        bearish_patterns = {
            CandlePattern.BEARISH_ENGULFING,
            CandlePattern.BEARISH_PIN_BAR,
            CandlePattern.SHOOTING_STAR,
            CandlePattern.EVENING_STAR,
            CandlePattern.BEARISH_DOJI,
            CandlePattern.THREE_BLACK_CROWS,
        }

        # Prefer direction-aligned patterns
        aligned: list[tuple[CandlePattern, float]] = []
        for pattern, base_score in patterns:
            if (
                direction_hint == "bullish"
                and pattern in bullish_patterns
                or direction_hint == "bearish"
                and pattern in bearish_patterns
                or direction_hint == "neutral"
            ):
                aligned.append((pattern, base_score))

        # Fall back to all patterns if none aligned
        candidates = aligned if aligned else patterns

        # Pick highest scoring
        best = max(candidates, key=lambda x: x[1])
        score = best[1]

        # Level proximity bonus
        if at_level:
            score = min(1.0, score + 0.15)

        return best[0], score

    @staticmethod
    def _body_ratio(o: float, h: float, l: float, c: float) -> float:
        """Body size relative to total range."""
        range_val = h - l
        if range_val == 0:
            return 0.0
        return abs(c - o) / range_val

    @staticmethod
    def _wick_ratio(o: float, h: float, l: float, c: float) -> float:
        """Lower wick relative to total range (for pin bar detection)."""
        range_val = h - l
        if range_val == 0:
            return 0.0
        return (min(o, c) - l) / range_val

    def _neutral_result(self) -> CandleResult:
        """Return neutral result when insufficient data."""
        return CandleResult(
            pattern=CandlePattern.NONE,
            direction="neutral",
            score=0.0,
            at_key_level=False,
            body_ratio=0.0,
            wick_ratio=0.0,
        )
