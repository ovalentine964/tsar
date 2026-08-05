"""
VMPM Trend Detector — Multi-timeframe trend analysis with HH/HL/LH/LL detection.

Analyzes trend across D1, H4, and H1 timeframes using:
  - 50 MA and 200 MA (SMA) for trend direction
  - Higher-High / Higher-Low (HH/HL) for uptrend confirmation
  - Lower-High / Lower-Low (LH/LL) for downtrend confirmation
  - Trend strength via MA separation and slope

Produces a TrendState with:
  - direction: 'bullish', 'bearish', 'neutral'
  - alignment: bool (all timeframes agree)
  - strength: 0.0 – 1.0
  - per-timeframe breakdown
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class TrendDirection(StrEnum):
    """Trend direction."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SwingType(StrEnum):
    """Swing point type."""

    HH = "higher_high"
    HL = "higher_low"
    LH = "lower_high"
    LL = "lower_low"


@dataclass(frozen=True)
class SwingPoint:
    """A detected swing high or low."""

    price: float
    index: int
    swing_type: SwingType


@dataclass(frozen=True)
class TimeframeTrend:
    """Trend analysis for a single timeframe."""

    timeframe: str
    direction: TrendDirection
    ma_fast: float  # 50 MA
    ma_slow: float  # 200 MA
    ma_spread_pct: float  # (fast - slow) / slow * 100
    ma_slope: float  # Slope of fast MA (rate of change)
    price_vs_ma: str  # "above_fast", "between", "below_slow"
    swing_points: tuple[SwingPoint, ...]
    structure: str  # "hh_hl" (bullish), "lh_ll" (bearish), "mixed"
    strength: float  # 0.0 – 1.0


@dataclass(frozen=True)
class TrendState:
    """Multi-timeframe trend analysis output."""

    direction: TrendDirection
    aligned: bool  # All timeframes agree
    strength: float  # 0.0 – 1.0
    d1: TimeframeTrend
    h4: TimeframeTrend
    h1: TimeframeTrend
    confluence_score: float
    reasoning: str


class TrendDetector:
    """Multi-timeframe trend detector for VMPM.

    Uses 50/200 MA and swing structure (HH/HL/LH/LL) to determine
    trend direction and strength across D1, H4, and H1.

    Usage::

        detector = TrendDetector(config)
        state = detector.detect(d1_closes, h4_closes, h1_closes)
        if state.aligned and state.direction == TrendDirection.BULLISH:
            # All timeframes bullish — high probability setup
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        tech = self._config.get("technical", {}).get("moving_averages", {})
        self._fast_period = tech.get("fast_period", 50)
        self._slow_period = tech.get("slow_period", 200)

        # Mutable params from genome
        mutable = self._config.get("mutable_parameters", {})
        if "ma_fast_period" in mutable:
            self._fast_period = mutable["ma_fast_period"].get("current", self._fast_period)
        if "ma_slow_period" in mutable:
            self._slow_period = mutable["ma_slow_period"].get("current", self._slow_period)

    def detect(
        self,
        d1_closes: list[float],
        h4_closes: list[float],
        h1_closes: list[float],
    ) -> TrendState:
        """Detect multi-timeframe trend state.

        Args:
            d1_closes: Daily close prices (need at least 200+ bars).
            h4_closes: 4-hour close prices.
            h1_closes: 1-hour close prices.

        Returns:
            TrendState with per-timeframe and aggregated analysis.
        """
        d1 = self._analyze_timeframe(d1_closes, "D1")
        h4 = self._analyze_timeframe(h4_closes, "H4")
        h1 = self._analyze_timeframe(h1_closes, "H1")

        # Determine overall direction
        directions = [d1.direction, h4.direction, h1.direction]
        aligned = len(set(directions)) == 1

        # Count bullish vs bearish
        bullish_count = sum(1 for d in directions if d == TrendDirection.BULLISH)
        bearish_count = sum(1 for d in directions if d == TrendDirection.BEARISH)

        if bullish_count >= 2:
            overall = TrendDirection.BULLISH
        elif bearish_count >= 2:
            overall = TrendDirection.BEARISH
        else:
            overall = TrendDirection.NEUTRAL

        # Confluence score: weighted by timeframe importance
        tf_weights = {"D1": 0.5, "H4": 0.3, "H1": 0.2}
        tf_map = {"D1": d1, "H4": h4, "H1": h1}

        confluence = 0.0
        total_weight = 0.0
        for tf_name, tf_trend in tf_map.items():
            w = tf_weights.get(tf_name, 0.2)
            if tf_trend.direction == overall:
                confluence += tf_trend.strength * w
            total_weight += w

        confluence_score = confluence / total_weight if total_weight > 0 else 0.0

        # Aggregate strength
        avg_strength = (d1.strength + h4.strength + h1.strength) / 3.0
        if aligned:
            avg_strength = min(1.0, avg_strength * 1.2)  # Alignment bonus

        reasoning_parts = [
            f"D1={d1.direction.value}({d1.strength:.2f})",
            f"H4={h4.direction.value}({h4.strength:.2f})",
            f"H1={h1.direction.value}({h1.strength:.2f})",
            f"aligned={aligned}",
            f"confluence={confluence_score:.2f}",
        ]

        return TrendState(
            direction=overall,
            aligned=aligned,
            strength=avg_strength,
            d1=d1,
            h4=h4,
            h1=h1,
            confluence_score=confluence_score,
            reasoning=", ".join(reasoning_parts),
        )

    def _analyze_timeframe(
        self, closes: list[float], timeframe: str
    ) -> TimeframeTrend:
        """Analyze trend for a single timeframe."""
        if len(closes) < self._slow_period + 10:
            return self._neutral_trend(timeframe)

        # Calculate MAs
        ma_fast = self._sma(closes, self._fast_period)
        ma_slow = self._sma(closes, self._slow_period)

        if ma_fast is None or ma_slow is None or ma_slow == 0:
            return self._neutral_trend(timeframe)

        ma_spread_pct = (ma_fast - ma_slow) / ma_slow * 100

        # MA slope (5-bar rate of change of fast MA)
        ma_fast_prev = self._sma(closes[:-5], self._fast_period)
        ma_slope = 0.0
        if ma_fast_prev and ma_fast_prev > 0:
            ma_slope = (ma_fast - ma_fast_prev) / ma_fast_prev * 100

        # Price position relative to MAs
        current_price = closes[-1]
        if current_price > ma_fast:
            price_vs_ma = "above_fast"
        elif current_price < ma_slow:
            price_vs_ma = "below_slow"
        else:
            price_vs_ma = "between"

        # Detect swing points
        swing_points = self._detect_swings(closes[-60:], timeframe)

        # Determine swing structure
        structure = self._analyze_structure(swing_points)

        # Determine direction from MA + structure
        direction = self._determine_direction(
            ma_spread_pct, price_vs_ma, structure
        )

        # Calculate strength
        strength = self._calculate_strength(
            ma_spread_pct, ma_slope, structure, swing_points
        )

        return TimeframeTrend(
            timeframe=timeframe,
            direction=direction,
            ma_fast=ma_fast,
            ma_slow=ma_slow,
            ma_spread_pct=ma_spread_pct,
            ma_slope=ma_slope,
            price_vs_ma=price_vs_ma,
            swing_points=tuple(swing_points),
            structure=structure,
            strength=strength,
        )

    def _sma(self, data: list[float], period: int) -> float | None:
        """Calculate Simple Moving Average."""
        if len(data) < period:
            return None
        return sum(data[-period:]) / period

    def _detect_swings(
        self, closes: list[float], timeframe: str
    ) -> list[SwingPoint]:
        """Detect swing highs and lows using a 5-bar window.

        A swing high is a bar whose high is higher than the 2 bars
        on each side. A swing low is the mirror.
        """
        if len(closes) < 5:
            return []

        swings: list[SwingPoint] = []
        for i in range(2, len(closes) - 2):
            # Swing high
            if (closes[i] > closes[i - 1] and closes[i] > closes[i - 2] and
                    closes[i] > closes[i + 1] and closes[i] > closes[i + 2]):
                swings.append(SwingPoint(
                    price=closes[i], index=i, swing_type=SwingType.HH
                ))
            # Swing low
            elif (closes[i] < closes[i - 1] and closes[i] < closes[i - 2] and
                  closes[i] < closes[i + 1] and closes[i] < closes[i + 2]):
                swings.append(SwingPoint(
                    price=closes[i], index=i, swing_type=SwingType.HL
                ))

        # Classify swings as HH/HL/LH/LL
        classified: list[SwingPoint] = []
        last_high: float | None = None
        last_low: float | None = None

        for swing in swings:
            if swing.swing_type == SwingType.HH:  # It's a high
                if last_high is not None:
                    st = SwingType.HH if swing.price > last_high else SwingType.LH
                else:
                    st = SwingType.HH
                last_high = swing.price
                classified.append(SwingPoint(
                    price=swing.price, index=swing.index, swing_type=st
                ))
            else:  # It's a low
                if last_low is not None:
                    st = SwingType.HL if swing.price > last_low else SwingType.LL
                else:
                    st = SwingType.HL
                last_low = swing.price
                classified.append(SwingPoint(
                    price=swing.price, index=swing.index, swing_type=st
                ))

        return classified

    def _analyze_structure(self, swings: list[SwingPoint]) -> str:
        """Analyze swing structure to determine market structure."""
        if len(swings) < 4:
            return "insufficient"

        recent = swings[-4:]
        types = [s.swing_type for s in recent]

        hh_count = types.count(SwingType.HH)
        hl_count = types.count(SwingType.HL)
        lh_count = types.count(SwingType.LH)
        ll_count = types.count(SwingType.LL)

        bullish = hh_count + hl_count
        bearish = lh_count + ll_count

        if bullish >= 3:
            return "hh_hl"
        elif bearish >= 3:
            return "lh_ll"
        else:
            return "mixed"

    def _determine_direction(
        self,
        ma_spread_pct: float,
        price_vs_ma: str,
        structure: str,
    ) -> TrendDirection:
        """Determine trend direction from MA and structure signals."""
        bullish_signals = 0
        bearish_signals = 0

        # MA spread
        if ma_spread_pct > 0.5:
            bullish_signals += 1
        elif ma_spread_pct < -0.5:
            bearish_signals += 1

        # Price vs MA
        if price_vs_ma == "above_fast":
            bullish_signals += 1
        elif price_vs_ma == "below_slow":
            bearish_signals += 1

        # Structure
        if structure == "hh_hl":
            bullish_signals += 1
        elif structure == "lh_ll":
            bearish_signals += 1

        if bullish_signals > bearish_signals:
            return TrendDirection.BULLISH
        elif bearish_signals > bullish_signals:
            return TrendDirection.BEARISH
        return TrendDirection.NEUTRAL

    def _calculate_strength(
        self,
        ma_spread_pct: float,
        ma_slope: float,
        structure: str,
        swings: list[SwingPoint],
    ) -> float:
        """Calculate trend strength 0.0 – 1.0."""
        score = 0.0

        # MA separation (up to 0.3)
        abs_spread = abs(ma_spread_pct)
        if abs_spread > 2.0:
            score += 0.3
        elif abs_spread > 1.0:
            score += 0.2
        elif abs_spread > 0.5:
            score += 0.1

        # MA slope (up to 0.3)
        abs_slope = abs(ma_slope)
        if abs_slope > 1.0:
            score += 0.3
        elif abs_slope > 0.5:
            score += 0.2
        elif abs_slope > 0.1:
            score += 0.1

        # Structure consistency (up to 0.2)
        if structure in ("hh_hl", "lh_ll"):
            score += 0.2
        elif structure == "mixed":
            score += 0.05

        # Recent swing count (more swings = more data = more reliable)
        if len(swings) >= 6:
            score += 0.2
        elif len(swings) >= 4:
            score += 0.1

        return min(1.0, score)

    def _neutral_trend(self, timeframe: str) -> TimeframeTrend:
        """Return a neutral trend when data is insufficient."""
        return TimeframeTrend(
            timeframe=timeframe,
            direction=TrendDirection.NEUTRAL,
            ma_fast=0.0,
            ma_slow=0.0,
            ma_spread_pct=0.0,
            ma_slope=0.0,
            price_vs_ma="between",
            swing_points=(),
            structure="insufficient",
            strength=0.0,
        )
