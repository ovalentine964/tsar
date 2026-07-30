"""
TSAR Domain Tools — Pattern Recognition.

Dedicated pattern recognition module covering:
  - Chart Patterns: Head & Shoulders, Double Top/Bottom, Triangles, Wedges
  - Candlestick Patterns: Doji, Hammer, Engulfing, Morning/Evening Star, etc.

All detectors operate on OHLCV data (oldest first) and return
frozen dataclass results with confidence scores.

Usage:
    from src.tools.pattern_recognition import PatternRecognitionTools

    tools = PatternRecognitionTools()
    chart_patterns = tools.detect_chart_patterns(ohlcv)
    candle_patterns = tools.detect_candlestick_patterns(ohlcv)
    all_patterns = tools.full_scan(ohlcv)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.interfaces.types import OHLCV

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ChartPattern:
    """Detected chart (structural) pattern.

    Attributes:
        pattern: Pattern name (e.g. "head_and_shoulders", "double_top").
        direction: "bullish", "bearish", or "neutral".
        confidence: Detection confidence (0-1).
        target_price: Measured-move target price.
        entry_price: Suggested entry (breakout/breakdown level).
        stop_loss: Suggested stop-loss level.
        description: Human-readable explanation.
        bars_involved: Number of bars forming the pattern.
    """

    pattern: str
    direction: str
    confidence: float
    target_price: float
    entry_price: float
    stop_loss: float
    description: str
    bars_involved: int


@dataclass(frozen=True)
class CandlestickPattern:
    """Detected candlestick pattern.

    Attributes:
        pattern: Pattern name.
        direction: "bullish", "bearish", or "neutral".
        reliability: Historical reliability score (0-1).
        bar_index: Index of the trigger candle in the input array.
        description: Human-readable description.
    """

    pattern: str
    direction: str
    reliability: float
    bar_index: int
    description: str


@dataclass(frozen=True)
class PatternScanResult:
    """Combined result from a full pattern scan.

    Attributes:
        chart_patterns: Detected structural patterns.
        candlestick_patterns: Detected candlestick patterns.
        dominant_bias: Aggregated directional bias.
        confidence: Overall confidence in the dominant bias.
        summary: Human-readable summary.
    """

    chart_patterns: tuple[ChartPattern, ...]
    candlestick_patterns: tuple[CandlestickPattern, ...]
    dominant_bias: str
    confidence: float
    summary: str


# ═══════════════════════════════════════════════════════════════════════
# PATTERN RECOGNITION TOOLS
# ═══════════════════════════════════════════════════════════════════════


class PatternRecognitionTools:
    """Comprehensive pattern recognition for OHLCV data.

    Detects chart patterns (H&S, double top/bottom, triangles, wedges)
    and candlestick patterns (doji, hammer, engulfing, stars, etc.)
    with confidence scoring and measured-move targets.
    """

    description = (
        "Chart patterns (H&S, double top/bottom, triangles, wedges) "
        "and candlestick patterns (doji, hammer, engulfing, stars)"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    # ── Public API ───────────────────────────────────────────────────

    def detect_chart_patterns(
        self,
        ohlcv: list[OHLCV],
        min_pattern_bars: int = 20,
    ) -> list[ChartPattern]:
        """Detect chart patterns in OHLCV data.

        Scans for: Head & Shoulders (normal + inverse), Double Top,
        Double Bottom, Ascending/Descending/Symmetric Triangles,
        Rising/Falling Wedges, Bull/Bear Flags.

        Args:
            ohlcv: OHLCV candles, oldest first.
            min_pattern_bars: Minimum bars required for a pattern.

        Returns:
            List of detected ChartPattern (may be empty).
        """
        if len(ohlcv) < min_pattern_bars:
            return []

        closes = np.array([c.close for c in ohlcv], dtype=float)
        highs = np.array([c.high for c in ohlcv], dtype=float)
        lows = np.array([c.low for c in ohlcv], dtype=float)
        opens = np.array([c.open for c in ohlcv], dtype=float)

        swing_window = max(3, len(ohlcv) // 20)
        swing_highs = self._find_swing_points(highs, swing_window, "high")
        swing_lows = self._find_swing_points(lows, swing_window, "low")

        patterns: list[ChartPattern] = []

        # Double Top / Double Bottom
        dt = self._detect_double_top(swing_highs, closes, highs, lows)
        if dt:
            patterns.append(dt)
        db = self._detect_double_bottom(swing_lows, closes, highs, lows)
        if db:
            patterns.append(db)

        # Head & Shoulders / Inverse H&S
        hs = self._detect_head_shoulders(swing_highs, swing_lows, closes, highs, lows)
        if hs:
            patterns.append(hs)
        ihs = self._detect_inverse_head_shoulders(swing_highs, swing_lows, closes, highs, lows)
        if ihs:
            patterns.append(ihs)

        # Triangles
        for tri in self._detect_triangles(swing_highs, swing_lows, closes):
            patterns.append(tri)

        # Wedges
        for wedge in self._detect_wedges(swing_highs, swing_lows, closes):
            patterns.append(wedge)

        # Flags
        flag = self._detect_flag(ohlcv, closes, highs, lows)
        if flag:
            patterns.append(flag)

        return patterns

    def detect_candlestick_patterns(
        self,
        ohlcv: list[OHLCV],
    ) -> list[CandlestickPattern]:
        """Detect candlestick patterns in OHLCV data.

        Patterns: Doji, Hammer, Inverted Hammer, Bullish/Bearish
        Engulfing, Morning Star, Evening Star, Three White Soldiers,
        Three Black Crows, Piercing Line, Dark Cloud Cover, Harami.

        Args:
            ohlcv: OHLCV candles, oldest first.

        Returns:
            List of detected CandlestickPattern.
        """
        if len(ohlcv) < 3:
            return []

        patterns: list[CandlestickPattern] = []

        for i in range(2, len(ohlcv)):
            c = ohlcv[i]
            c_prev = ohlcv[i - 1]
            c_prev2 = ohlcv[i - 2]

            body = abs(c.close - c.open)
            total_range = c.high - c.low
            upper_shadow = c.high - max(c.open, c.close)
            lower_shadow = min(c.open, c.close) - c.low

            if total_range <= 0:
                continue

            prev_body = abs(c_prev.close - c_prev.open)
            prev_range = c_prev.high - c_prev.low

            # ── Doji ──
            if body / total_range < 0.1:
                # Long-legged doji
                if upper_shadow > body * 5 and lower_shadow > body * 5:
                    patterns.append(CandlestickPattern(
                        pattern="long_legged_doji",
                        direction="neutral",
                        reliability=0.55,
                        bar_index=i,
                        description="Long-legged doji — strong indecision",
                    ))
                # Dragonfly doji (long lower shadow, no upper)
                elif lower_shadow > body * 5 and upper_shadow < body:
                    patterns.append(CandlestickPattern(
                        pattern="dragonfly_doji",
                        direction="bullish",
                        reliability=0.6,
                        bar_index=i,
                        description="Dragonfly doji — bullish reversal signal",
                    ))
                # Gravestone doji (long upper shadow, no lower)
                elif upper_shadow > body * 5 and lower_shadow < body:
                    patterns.append(CandlestickPattern(
                        pattern="gravestone_doji",
                        direction="bearish",
                        reliability=0.6,
                        bar_index=i,
                        description="Gravestone doji — bearish reversal signal",
                    ))
                else:
                    patterns.append(CandlestickPattern(
                        pattern="doji",
                        direction="neutral",
                        reliability=0.5,
                        bar_index=i,
                        description="Doji — indecision, potential reversal",
                    ))

            # ── Hammer (bullish reversal) ──
            if (lower_shadow > body * 2 and upper_shadow < body * 0.5
                    and c_prev.close < c_prev.open):
                patterns.append(CandlestickPattern(
                    pattern="hammer",
                    direction="bullish",
                    reliability=0.65,
                    bar_index=i,
                    description="Hammer — bullish reversal after downtrend",
                ))

            # ── Inverted Hammer ──
            if (upper_shadow > body * 2 and lower_shadow < body * 0.5
                    and c_prev.close < c_prev.open):
                patterns.append(CandlestickPattern(
                    pattern="inverted_hammer",
                    direction="bullish",
                    reliability=0.55,
                    bar_index=i,
                    description="Inverted Hammer — potential bullish reversal",
                ))

            # ── Hanging Man (bearish, same shape as hammer but after uptrend) ──
            if (lower_shadow > body * 2 and upper_shadow < body * 0.5
                    and c_prev.close > c_prev.open):
                patterns.append(CandlestickPattern(
                    pattern="hanging_man",
                    direction="bearish",
                    reliability=0.6,
                    bar_index=i,
                    description="Hanging Man — bearish reversal after uptrend",
                ))

            # ── Shooting Star (bearish) ──
            if (upper_shadow > body * 2 and lower_shadow < body * 0.5
                    and c_prev.close > c_prev.open):
                patterns.append(CandlestickPattern(
                    pattern="shooting_star",
                    direction="bearish",
                    reliability=0.65,
                    bar_index=i,
                    description="Shooting Star — bearish reversal after uptrend",
                ))

            # ── Bullish Engulfing ──
            if (c_prev.close < c_prev.open
                    and c.close > c.open
                    and c.open <= c_prev.close
                    and c.close >= c_prev.open):
                patterns.append(CandlestickPattern(
                    pattern="bullish_engulfing",
                    direction="bullish",
                    reliability=0.7,
                    bar_index=i,
                    description="Bullish Engulfing — strong reversal signal",
                ))

            # ── Bearish Engulfing ──
            if (c_prev.close > c_prev.open
                    and c.close < c.open
                    and c.open >= c_prev.close
                    and c.close <= c_prev.open):
                patterns.append(CandlestickPattern(
                    pattern="bearish_engulfing",
                    direction="bearish",
                    reliability=0.7,
                    bar_index=i,
                    description="Bearish Engulfing — strong reversal signal",
                ))

            # ── Morning Star ──
            if (c_prev2.close < c_prev2.open
                    and prev_body < (c_prev2.high - c_prev2.low) * 0.3
                    and c.close > c.open
                    and c.close > (c_prev2.open + c_prev2.close) / 2):
                patterns.append(CandlestickPattern(
                    pattern="morning_star",
                    direction="bullish",
                    reliability=0.75,
                    bar_index=i,
                    description="Morning Star — strong bullish reversal",
                ))

            # ── Evening Star ──
            if (c_prev2.close > c_prev2.open
                    and prev_body < (c_prev2.high - c_prev2.low) * 0.3
                    and c.close < c.open
                    and c.close < (c_prev2.open + c_prev2.close) / 2):
                patterns.append(CandlestickPattern(
                    pattern="evening_star",
                    direction="bearish",
                    reliability=0.75,
                    bar_index=i,
                    description="Evening Star — strong bearish reversal",
                ))

            # ── Three White Soldiers ──
            if (i >= 2
                    and ohlcv[i - 2].close > ohlcv[i - 2].open
                    and ohlcv[i - 1].close > ohlcv[i - 1].open
                    and c.close > c.open
                    and ohlcv[i - 1].close > ohlcv[i - 2].close
                    and c.close > ohlcv[i - 1].close):
                patterns.append(CandlestickPattern(
                    pattern="three_white_soldiers",
                    direction="bullish",
                    reliability=0.7,
                    bar_index=i,
                    description="Three White Soldiers — strong bullish continuation",
                ))

            # ── Three Black Crows ──
            if (i >= 2
                    and ohlcv[i - 2].close < ohlcv[i - 2].open
                    and ohlcv[i - 1].close < ohlcv[i - 1].open
                    and c.close < c.open
                    and ohlcv[i - 1].close < ohlcv[i - 2].close
                    and c.close < ohlcv[i - 1].close):
                patterns.append(CandlestickPattern(
                    pattern="three_black_crows",
                    direction="bearish",
                    reliability=0.7,
                    bar_index=i,
                    description="Three Black Crows — strong bearish continuation",
                ))

            # ── Piercing Line ──
            if (c_prev.close < c_prev.open
                    and c.open < c_prev.low
                    and c.close > (c_prev.open + c_prev.close) / 2
                    and c.close < c_prev.open
                    and c.close > c.open):
                patterns.append(CandlestickPattern(
                    pattern="piercing_line",
                    direction="bullish",
                    reliability=0.65,
                    bar_index=i,
                    description="Piercing Line — bullish reversal",
                ))

            # ── Dark Cloud Cover ──
            if (c_prev.close > c_prev.open
                    and c.open > c_prev.high
                    and c.close < (c_prev.open + c_prev.close) / 2
                    and c.close > c_prev.open
                    and c.close < c.open):
                patterns.append(CandlestickPattern(
                    pattern="dark_cloud_cover",
                    direction="bearish",
                    reliability=0.65,
                    bar_index=i,
                    description="Dark Cloud Cover — bearish reversal",
                ))

            # ── Bullish Harami ──
            if (c_prev.close < c_prev.open
                    and c.close > c.open
                    and c.open > c_prev.close
                    and c.close < c_prev.open
                    and body < prev_body * 0.6):
                patterns.append(CandlestickPattern(
                    pattern="bullish_harami",
                    direction="bullish",
                    reliability=0.55,
                    bar_index=i,
                    description="Bullish Harami — potential reversal",
                ))

            # ── Bearish Harami ──
            if (c_prev.close > c_prev.open
                    and c.close < c.open
                    and c.open < c_prev.close
                    and c.close > c_prev.open
                    and body < prev_body * 0.6):
                patterns.append(CandlestickPattern(
                    pattern="bearish_harami",
                    direction="bearish",
                    reliability=0.55,
                    bar_index=i,
                    description="Bearish Harami — potential reversal",
                ))

        return patterns

    def full_scan(
        self,
        ohlcv: list[OHLCV],
        min_pattern_bars: int = 20,
    ) -> PatternScanResult:
        """Run a full pattern scan (chart + candlestick) and aggregate.

        Args:
            ohlcv: OHLCV candles, oldest first.
            min_pattern_bars: Minimum bars for chart pattern detection.

        Returns:
            PatternScanResult with all patterns and aggregated bias.
        """
        chart = self.detect_chart_patterns(ohlcv, min_pattern_bars)
        candle = self.detect_candlestick_patterns(ohlcv)

        # Aggregate directional bias
        bull_score = 0.0
        bear_score = 0.0

        for p in chart:
            if p.direction == "bullish":
                bull_score += p.confidence
            elif p.direction == "bearish":
                bear_score += p.confidence

        for p in candle:
            if p.direction == "bullish":
                bull_score += p.reliability
            elif p.direction == "bearish":
                bear_score += p.reliability

        total = bull_score + bear_score
        if total > 0:
            if bull_score > bear_score * 1.3:
                bias = "bullish"
                confidence = round(bull_score / total, 2)
            elif bear_score > bull_score * 1.3:
                bias = "bearish"
                confidence = round(bear_score / total, 2)
            else:
                bias = "neutral"
                confidence = round(1 - abs(bull_score - bear_score) / total, 2)
        else:
            bias = "neutral"
            confidence = 0.0

        summary_parts: list[str] = []
        if chart:
            summary_parts.append(f"{len(chart)} chart pattern(s)")
        if candle:
            summary_parts.append(f"{len(candle)} candlestick pattern(s)")
        if not summary_parts:
            summary_parts.append("No patterns detected")

        summary = f"Found {', '.join(summary_parts)}. Bias: {bias} ({confidence:.0%})"

        return PatternScanResult(
            chart_patterns=tuple(chart),
            candlestick_patterns=tuple(candle),
            dominant_bias=bias,
            confidence=confidence,
            summary=summary,
        )

    # ── Swing Point Detection ────────────────────────────────────────

    @staticmethod
    def _find_swing_points(
        data: np.ndarray,
        window: int,
        point_type: str,
    ) -> list[tuple[int, float]]:
        """Find swing highs or lows in price data.

        Args:
            data: Price array (highs or lows).
            window: Lookback window on each side.
            point_type: "high" or "low".

        Returns:
            List of (index, price) tuples for swing points.
        """
        points: list[tuple[int, float]] = []
        for i in range(window, len(data) - window):
            segment = data[i - window: i + window + 1]
            if point_type == "high":
                if data[i] == np.max(segment):
                    points.append((i, float(data[i])))
            else:
                if data[i] == np.min(segment):
                    points.append((i, float(data[i])))
        return points

    # ── Double Top ───────────────────────────────────────────────────

    @staticmethod
    def _detect_double_top(
        swing_highs: list[tuple[int, float]],
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> ChartPattern | None:
        """Detect double top (M-top) pattern.

        Two swing highs at similar price with a trough between.
        Confirmed when price breaks below the neckline.
        """
        if len(swing_highs) < 2:
            return None

        h1_idx, h1_price = swing_highs[-2]
        h2_idx, h2_price = swing_highs[-1]

        if h1_price <= 0:
            return None
        pct_diff = abs(h1_price - h2_price) / h1_price
        if pct_diff > 0.03:  # 3% tolerance
            return None

        # Neckline = lowest low between the two highs
        neckline = float(np.min(lows[h1_idx:h2_idx + 1]))
        current = float(closes[-1])
        pattern_height = h1_price - neckline

        if current < neckline:
            # Confirmed breakdown
            target = neckline - pattern_height
            return ChartPattern(
                pattern="double_top",
                direction="bearish",
                confidence=0.75,
                target_price=round(target, 8),
                entry_price=round(neckline, 8),
                stop_loss=round(max(h1_price, h2_price) * 1.005, 8),
                description=(
                    f"Double top at {h1_price:.2f}/{h2_price:.2f}, "
                    f"neckline {neckline:.2f} broken. Target {target:.2f}"
                ),
                bars_involved=h2_idx - h1_idx,
            )

        # Forming (not yet confirmed)
        if current > neckline * 0.99:
            return ChartPattern(
                pattern="double_top_forming",
                direction="bearish",
                confidence=0.4,
                target_price=round(neckline - pattern_height, 8),
                entry_price=round(neckline, 8),
                stop_loss=round(max(h1_price, h2_price) * 1.005, 8),
                description=(
                    f"Double top forming at {h1_price:.2f}/{h2_price:.2f}. "
                    f"Watch for neckline break at {neckline:.2f}"
                ),
                bars_involved=h2_idx - h1_idx,
            )

        return None

    # ── Double Bottom ────────────────────────────────────────────────

    @staticmethod
    def _detect_double_bottom(
        swing_lows: list[tuple[int, float]],
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> ChartPattern | None:
        """Detect double bottom (W-bottom) pattern."""
        if len(swing_lows) < 2:
            return None

        l1_idx, l1_price = swing_lows[-2]
        l2_idx, l2_price = swing_lows[-1]

        if l1_price <= 0:
            return None
        pct_diff = abs(l1_price - l2_price) / l1_price
        if pct_diff > 0.03:
            return None

        neckline = float(np.max(highs[l1_idx:l2_idx + 1]))
        current = float(closes[-1])
        pattern_height = neckline - l1_price

        if current > neckline:
            target = neckline + pattern_height
            return ChartPattern(
                pattern="double_bottom",
                direction="bullish",
                confidence=0.75,
                target_price=round(target, 8),
                entry_price=round(neckline, 8),
                stop_loss=round(min(l1_price, l2_price) * 0.995, 8),
                description=(
                    f"Double bottom at {l1_price:.2f}/{l2_price:.2f}, "
                    f"neckline {neckline:.2f} broken. Target {target:.2f}"
                ),
                bars_involved=l2_idx - l1_idx,
            )

        if current < neckline * 1.01:
            return ChartPattern(
                pattern="double_bottom_forming",
                direction="bullish",
                confidence=0.4,
                target_price=round(neckline + pattern_height, 8),
                entry_price=round(neckline, 8),
                stop_loss=round(min(l1_price, l2_price) * 0.995, 8),
                description=(
                    f"Double bottom forming at {l1_price:.2f}/{l2_price:.2f}. "
                    f"Watch for neckline break at {neckline:.2f}"
                ),
                bars_involved=l2_idx - l1_idx,
            )

        return None

    # ── Head & Shoulders ─────────────────────────────────────────────

    @staticmethod
    def _detect_head_shoulders(
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> ChartPattern | None:
        """Detect head and shoulders (top) pattern.

        Three swing highs where the middle (head) is highest,
        and the two shoulders are at similar levels.
        """
        if len(swing_highs) < 3:
            return None

        ls_idx, ls_price = swing_highs[-3]
        h_idx, h_price = swing_highs[-2]
        rs_idx, rs_price = swing_highs[-1]

        # Head must be highest
        if h_price <= ls_price or h_price <= rs_price:
            return None

        # Shoulders similar height (within 5%)
        if ls_price <= 0:
            return None
        shoulder_diff = abs(ls_price - rs_price) / ls_price
        if shoulder_diff > 0.05:
            return None

        # Neckline from swing lows between shoulders
        neckline_lows = [l for i, l in swing_lows if ls_idx <= i <= rs_idx]
        if not neckline_lows:
            return None
        neckline = float(np.mean(neckline_lows))

        current = float(closes[-1])
        head_height = h_price - neckline

        if current < neckline:
            target = neckline - head_height
            return ChartPattern(
                pattern="head_and_shoulders",
                direction="bearish",
                confidence=0.8,
                target_price=round(target, 8),
                entry_price=round(neckline, 8),
                stop_loss=round(rs_price * 1.005, 8),
                description=(
                    f"H&S: head={h_price:.2f}, shoulders={ls_price:.2f}/{rs_price:.2f}, "
                    f"neckline={neckline:.2f}. Target {target:.2f}"
                ),
                bars_involved=rs_idx - ls_idx,
            )

        return ChartPattern(
            pattern="head_and_shoulders_forming",
            direction="bearish",
            confidence=0.45,
            target_price=round(neckline - head_height, 8),
            entry_price=round(neckline, 8),
            stop_loss=round(h_price * 1.01, 8),
            description=(
                f"H&S forming: head={h_price:.2f}, shoulders={ls_price:.2f}/{rs_price:.2f}. "
                f"Neckline at {neckline:.2f}"
            ),
            bars_involved=rs_idx - ls_idx,
        )

    # ── Inverse Head & Shoulders ─────────────────────────────────────

    @staticmethod
    def _detect_inverse_head_shoulders(
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> ChartPattern | None:
        """Detect inverse (bullish) head and shoulders pattern."""
        if len(swing_lows) < 3:
            return None

        ls_idx, ls_price = swing_lows[-3]
        h_idx, h_price = swing_lows[-2]
        rs_idx, rs_price = swing_lows[-1]

        # Head must be lowest
        if h_price >= ls_price or h_price >= rs_price:
            return None

        # Shoulders similar depth (within 5%)
        if ls_price <= 0:
            return None
        shoulder_diff = abs(ls_price - rs_price) / ls_price
        if shoulder_diff > 0.05:
            return None

        # Neckline from swing highs between shoulders
        neckline_highs = [h for i, h in swing_highs if ls_idx <= i <= rs_idx]
        if not neckline_highs:
            return None
        neckline = float(np.mean(neckline_highs))

        current = float(closes[-1])
        head_depth = neckline - h_price

        if current > neckline:
            target = neckline + head_depth
            return ChartPattern(
                pattern="inverse_head_and_shoulders",
                direction="bullish",
                confidence=0.8,
                target_price=round(target, 8),
                entry_price=round(neckline, 8),
                stop_loss=round(rs_price * 0.995, 8),
                description=(
                    f"Inverse H&S: head={h_price:.2f}, shoulders={ls_price:.2f}/{rs_price:.2f}, "
                    f"neckline={neckline:.2f}. Target {target:.2f}"
                ),
                bars_involved=rs_idx - ls_idx,
            )

        return ChartPattern(
            pattern="inverse_head_and_shoulders_forming",
            direction="bullish",
            confidence=0.45,
            target_price=round(neckline + head_depth, 8),
            entry_price=round(neckline, 8),
            stop_loss=round(h_price * 0.99, 8),
            description=(
                f"Inverse H&S forming: head={h_price:.2f}, shoulders={ls_price:.2f}/{rs_price:.2f}. "
                f"Neckline at {neckline:.2f}"
            ),
            bars_involved=rs_idx - ls_idx,
        )

    # ── Triangles ────────────────────────────────────────────────────

    def _detect_triangles(
        self,
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        closes: np.ndarray,
    ) -> list[ChartPattern]:
        """Detect triangle patterns: ascending, descending, symmetric.

        Ascending:  flat resistance + rising support → bullish
        Descending: falling resistance + flat support → bearish
        Symmetric:  converging trendlines → neutral (breakout pending)
        """
        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return []

        results: list[ChartPattern] = []
        recent_highs = swing_highs[-3:]
        recent_lows = swing_lows[-3:]

        high_prices = [p for _, p in recent_highs]
        low_prices = [p for _, p in recent_lows]
        high_indices = [i for i, _ in recent_highs]
        low_indices = [i for i, _ in recent_lows]

        # Compute slopes (normalized)
        h_slope = self._compute_slope(high_indices, high_prices)
        l_slope = self._compute_slope(low_indices, low_prices)

        h_range = max(high_prices) - min(high_prices) if high_prices else 0
        l_range = max(low_prices) - min(low_prices) if low_prices else 0
        avg_price = float(closes[-1])

        # Ascending triangle: flat top, rising bottom
        if abs(h_slope) < 0.001 and l_slope > 0.001:
            resistance = float(np.mean(high_prices))
            target = resistance + (resistance - min(low_prices))
            results.append(ChartPattern(
                pattern="ascending_triangle",
                direction="bullish",
                confidence=0.65,
                target_price=round(target, 8),
                entry_price=round(resistance, 8),
                stop_loss=round(min(low_prices) * 0.995, 8),
                description=(
                    f"Ascending triangle: flat resistance {resistance:.2f}, "
                    f"rising support. Breakout target {target:.2f}"
                ),
                bars_involved=high_indices[-1] - high_indices[0],
            ))

        # Descending triangle: falling top, flat bottom
        if h_slope < -0.001 and abs(l_slope) < 0.001:
            support = float(np.mean(low_prices))
            target = support - (max(high_prices) - support)
            results.append(ChartPattern(
                pattern="descending_triangle",
                direction="bearish",
                confidence=0.65,
                target_price=round(target, 8),
                entry_price=round(support, 8),
                stop_loss=round(max(high_prices) * 1.005, 8),
                description=(
                    f"Descending triangle: flat support {support:.2f}, "
                    f"falling resistance. Breakdown target {target:.2f}"
                ),
                bars_involved=low_indices[-1] - low_indices[0],
            ))

        # Symmetric triangle: converging
        if h_slope < -0.001 and l_slope > 0.001:
            apex_price = (high_prices[-1] + low_prices[-1]) / 2
            results.append(ChartPattern(
                pattern="symmetric_triangle",
                direction="neutral",
                confidence=0.5,
                target_price=round(apex_price, 8),
                entry_price=round(avg_price, 8),
                stop_loss=round(min(low_prices) * 0.995, 8),
                description=(
                    f"Symmetric triangle: converging from "
                    f"{high_prices[0]:.2f}/{low_prices[0]:.2f}. Awaiting breakout"
                ),
                bars_involved=high_indices[-1] - high_indices[0],
            ))

        return results

    # ── Wedges ───────────────────────────────────────────────────────

    def _detect_wedges(
        self,
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        closes: np.ndarray,
    ) -> list[ChartPattern]:
        """Detect wedge patterns.

        Rising wedge (bearish): both trendlines rising, converging.
        Falling wedge (bullish): both trendlines falling, converging.
        """
        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return []

        results: list[ChartPattern] = []
        recent_highs = swing_highs[-3:]
        recent_lows = swing_lows[-3:]

        high_prices = [p for _, p in recent_highs]
        low_prices = [p for _, p in recent_lows]
        high_indices = [i for i, _ in recent_highs]
        low_indices = [i for i, _ in recent_lows]

        h_slope = self._compute_slope(high_indices, high_prices)
        l_slope = self._compute_slope(low_indices, low_prices)

        # Rising wedge: both slopes positive, converging (h_slope < l_slope is unusual,
        # typically both rise but highs rise slower → convergence)
        if h_slope > 0 and l_slope > 0 and h_slope < l_slope:
            # Converging upward → bearish
            support_level = low_prices[-1]
            target = support_level - (high_prices[-1] - low_prices[-1])
            results.append(ChartPattern(
                pattern="rising_wedge",
                direction="bearish",
                confidence=0.6,
                target_price=round(target, 8),
                entry_price=round(support_level, 8),
                stop_loss=round(high_prices[-1] * 1.005, 8),
                description=(
                    f"Rising wedge: both trendlines rising and converging. "
                    f"Bearish breakdown target {target:.2f}"
                ),
                bars_involved=high_indices[-1] - high_indices[0],
            ))

        # Falling wedge: both slopes negative, converging
        if h_slope < 0 and l_slope < 0 and h_slope > l_slope:
            # Converging downward → bullish
            resistance_level = high_prices[-1]
            target = resistance_level + (high_prices[-1] - low_prices[-1])
            results.append(ChartPattern(
                pattern="falling_wedge",
                direction="bullish",
                confidence=0.6,
                target_price=round(target, 8),
                entry_price=round(resistance_level, 8),
                stop_loss=round(low_prices[-1] * 0.995, 8),
                description=(
                    f"Falling wedge: both trendlines falling and converging. "
                    f"Bullish breakout target {target:.2f}"
                ),
                bars_involved=high_indices[-1] - high_indices[0],
            ))

        return results

    # ── Flags ────────────────────────────────────────────────────────

    @staticmethod
    def _detect_flag(
        ohlcv: list[OHLCV],
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> ChartPattern | None:
        """Detect bull/bear flag patterns.

        A flag is a sharp move (pole) followed by a small
        counter-trend consolidation (flag).
        """
        if len(ohlcv) < 15:
            return None

        # Use last 30 bars for detection
        lookback = min(30, len(ohlcv))
        recent_closes = closes[-lookback:]
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]

        # Split into pole (first half) and flag (second half)
        mid = lookback // 2
        pole_closes = recent_closes[:mid]
        flag_closes = recent_closes[mid:]

        if len(pole_closes) < 5 or len(flag_closes) < 5:
            return None

        pole_move = float(pole_closes[-1] - pole_closes[0])
        pole_range = float(np.max(recent_highs[:mid]) - np.min(recent_lows[:mid]))
        flag_range = float(np.max(recent_highs[mid:]) - np.min(recent_lows[mid:]))

        # Pole must be significant
        if abs(pole_move) < pole_range * 0.3:
            return None

        # Flag must be smaller than pole
        if flag_range > pole_range * 0.5:
            return None

        current = float(closes[-1])

        if pole_move > 0:
            # Bull flag: pole up, small pullback
            flag_high = float(np.max(recent_highs[mid:]))
            target = flag_high + abs(pole_move)
            return ChartPattern(
                pattern="bull_flag",
                direction="bullish",
                confidence=0.6,
                target_price=round(target, 8),
                entry_price=round(flag_high, 8),
                stop_loss=round(float(np.min(recent_lows[mid:])) * 0.995, 8),
                description=f"Bull flag: pole +{abs(pole_move):.2f}, flag consolidation. Target {target:.2f}",
                bars_involved=lookback,
            )
        else:
            # Bear flag: pole down, small bounce
            flag_low = float(np.min(recent_lows[mid:]))
            target = flag_low - abs(pole_move)
            return ChartPattern(
                pattern="bear_flag",
                direction="bearish",
                confidence=0.6,
                target_price=round(target, 8),
                entry_price=round(flag_low, 8),
                stop_loss=round(float(np.max(recent_highs[mid:])) * 1.005, 8),
                description=f"Bear flag: pole -{abs(pole_move):.2f}, flag consolidation. Target {target:.2f}",
                bars_involved=lookback,
            )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_slope(indices: list[int], prices: list[float]) -> float:
        """Compute normalized slope of a trendline through given points.

        Returns slope as price-change per bar, normalized by average price.
        """
        if len(indices) < 2 or len(prices) < 2:
            return 0.0
        x = np.array(indices, dtype=float)
        y = np.array(prices, dtype=float)
        avg_y = float(np.mean(y))
        if avg_y == 0:
            return 0.0
        # Simple linear regression slope
        n = len(x)
        denom = n * np.sum(x ** 2) - np.sum(x) ** 2
        if denom == 0:
            return 0.0
        slope = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / denom
        return slope / avg_y  # Normalize by price level
