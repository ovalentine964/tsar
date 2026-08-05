"""
TSAR Domain Tools — Technical Analysis Tools.

What the agent CALCULATES. Provides advanced technical analysis
beyond basic RSI/MACD/BB that the PricingEngine already handles.

Tools:
  - ADX (Average Directional Index) — trend strength
  - Stochastic Oscillator — overbought/oversold with %K/%D
  - VWAP (Volume Weighted Average Price) — institutional benchmark
  - Volume Profile — price-level volume distribution
  - Multi-Timeframe Confluence — cross-TF signal agreement
  - Chart Pattern Recognition — H&S, double top/bottom, triangles
  - Ichimoku Cloud — trend, support, resistance, momentum
  - Fibonacci Retracements — key retracement levels
  - Candlestick Patterns — doji, hammer, engulfing, etc.
  - Momentum Divergence — price vs indicator divergence detection

All tools are pure computational — no exchange calls, no side effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from src.interfaces.types import OHLCV

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ADXResult:
    """ADX indicator output.

    Attributes:
        adx: Average Directional Index (0-100). >25 = trending.
        plus_di: +DI line (bullish directional indicator).
        minus_di: -DI line (bearish directional indicator).
        trend_strength: Categorized trend strength.
            "no_trend" (<20), "weak" (20-25), "moderate" (25-40),
            "strong" (40-60), "very_strong" (>60).
    """

    adx: float
    plus_di: float
    minus_di: float
    trend_strength: str


@dataclass(frozen=True)
class StochasticResult:
    """Stochastic oscillator output.

    Attributes:
        k_line: %K line values (fast stochastic).
        d_line: %D line values (slow stochastic, SMA of %K).
        current_k: Latest %K value.
        current_d: Latest %D value.
        signal: "overbought" (>80), "oversold" (<20), "neutral".
        crossover: "bullish" (K crosses above D), "bearish", or "none".
    """

    k_line: tuple[float, ...]
    d_line: tuple[float, ...]
    current_k: float
    current_d: float
    signal: str
    crossover: str


@dataclass(frozen=True)
class VWAPResult:
    """VWAP indicator output.

    Attributes:
        vwap: Volume Weighted Average Price.
        upper_band: VWAP + 1 standard deviation.
        lower_band: VWAP - 1 standard deviation.
        upper_band_2: VWAP + 2 standard deviations.
        lower_band_2: VWAP - 2 standard deviations.
        price_position: Where price is relative to VWAP.
            "above" (>VWAP), "below" (<VWAP), "at" (within 0.1%).
    """

    vwap: float
    upper_band: float
    lower_band: float
    upper_band_2: float
    lower_band_2: float
    price_position: str


@dataclass(frozen=True)
class IchimokuResult:
    """Ichimoku Cloud output.

    Attributes:
        tenkan_sen: Conversion line (9-period).
        kijun_sen: Base line (26-period).
        senkou_span_a: Leading span A (cloud top/bottom).
        senkou_span_b: Leading span B (cloud top/bottom).
        chikou_span: Lagging span.
        cloud_color: "bullish" (green), "bearish" (red), or "thin".
        price_vs_cloud: "above", "below", or "inside".
        signal: "strong_buy", "buy", "neutral", "sell", "strong_sell".
    """

    tenkan_sen: float
    kijun_sen: float
    senkou_span_a: float
    senkou_span_b: float
    chikou_span: float
    cloud_color: str
    price_vs_cloud: str
    signal: str


@dataclass(frozen=True)
class FibonacciLevels:
    """Fibonacci retracement levels.

    Attributes:
        swing_high: The high of the swing.
        swing_low: The low of the swing.
        direction: "uptrend" or "downtrend".
        levels: Dict of fib level name → price.
            Includes 0.236, 0.382, 0.5, 0.618, 0.786.
        nearest_level: The fib level nearest to current price.
        nearest_level_name: Name of the nearest level.
    """

    swing_high: float
    swing_low: float
    direction: str
    levels: dict[str, float]
    nearest_level: float
    nearest_level_name: str


@dataclass(frozen=True)
class PatternResult:
    """Detected chart pattern.

    Attributes:
        pattern: Pattern name.
        direction: "bullish", "bearish", or "neutral".
        confidence: Pattern confidence (0-1).
        target_price: Measured move target price.
        description: Human-readable pattern description.
    """

    pattern: str
    direction: str
    confidence: float
    target_price: float
    description: str


@dataclass(frozen=True)
class DivergenceResult:
    """Momentum divergence detection.

    Attributes:
        divergence_type: "bullish", "bearish", or "none".
        indicator: Which indicator showed divergence.
        price_action: Description of price action.
        indicator_action: Description of indicator action.
        strength: Divergence strength (0-1).
    """

    divergence_type: str
    indicator: str
    price_action: str
    indicator_action: str
    strength: float


@dataclass(frozen=True)
class MultiTimeframeResult:
    """Multi-timeframe confluence analysis.

    Attributes:
        timeframes: Timeframes analyzed.
        signals: Per-timeframe signal details.
        confluence_score: Overall confluence score (0-1).
        direction: Consensus direction ("buy", "sell", "neutral").
        agreement: Number of timeframes agreeing.
        total: Total timeframes analyzed.
    """

    timeframes: tuple[str, ...]
    signals: dict[str, dict[str, Any]]
    confluence_score: float
    direction: str
    agreement: int
    total: int


@dataclass(frozen=True)
class CandlestickPattern:
    """Detected candlestick pattern.

    Attributes:
        pattern: Pattern name.
        direction: "bullish", "bearish", or "neutral".
        reliability: Pattern reliability score (0-1).
        bar_index: Index of the candle where pattern was detected.
        description: Human-readable description.
    """

    pattern: str
    direction: str
    reliability: float
    bar_index: int
    description: str


# ═══════════════════════════════════════════════════════════════════════
# TECHNICAL ANALYSIS TOOLS
# ═══════════════════════════════════════════════════════════════════════


class TechnicalAnalysisTools:
    """Advanced technical analysis beyond basic indicators.

    Provides ADX, Stochastic, VWAP, Ichimoku Cloud, Fibonacci levels,
    chart pattern recognition, candlestick patterns, divergence detection,
    and multi-timeframe confluence analysis.
    """

    description = "Advanced technical analysis: ADX, Stochastic, VWAP, Ichimoku, Fibonacci, patterns, divergence"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    # ── ADX (Average Directional Index) ──────────────────────────────

    def calculate_adx(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> ADXResult:
        """Calculate ADX with +DI and -DI.

        ADX measures trend strength regardless of direction.
        +DI/-DI indicate trend direction.

        Args:
            highs: High prices, oldest first.
            lows: Low prices, oldest first.
            closes: Close prices, oldest first.
            period: Lookback period (default 14).

        Returns:
            ADXResult with ADX, +DI, -DI, and trend strength.
        """
        if len(highs) < period + 1:
            return ADXResult(adx=0, plus_di=0, minus_di=0, trend_strength="no_trend")

        h = pd.Series(highs, dtype=float)
        l = pd.Series(lows, dtype=float)
        c = pd.Series(closes, dtype=float)

        import pandas_ta as ta

        adx_df = ta.adx(h, l, c, length=period)

        if adx_df is None or adx_df.dropna(how="all").empty:
            return ADXResult(adx=0, plus_di=0, minus_di=0, trend_strength="no_trend")

        adx_val = float(adx_df.iloc[-1, 0])  # ADX column
        plus_di = float(adx_df.iloc[-1, 1])  # +DI column
        minus_di = float(adx_df.iloc[-1, 2])  # -DI column

        # Categorize trend strength
        if adx_val >= 60:
            strength = "very_strong"
        elif adx_val >= 40:
            strength = "strong"
        elif adx_val >= 25:
            strength = "moderate"
        elif adx_val >= 20:
            strength = "weak"
        else:
            strength = "no_trend"

        return ADXResult(
            adx=round(adx_val, 2),
            plus_di=round(plus_di, 2),
            minus_di=round(minus_di, 2),
            trend_strength=strength,
        )

    # ── Stochastic Oscillator ────────────────────────────────────────

    def calculate_stochastic(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        k_period: int = 14,
        d_period: int = 3,
        smooth_k: int = 3,
    ) -> StochasticResult:
        """Calculate Stochastic Oscillator with %K and %D.

        The stochastic measures where the close is relative to the
        high-low range over a period.

        Args:
            highs: High prices, oldest first.
            lows: Low prices, oldest first.
            closes: Close prices, oldest first.
            k_period: %K lookback period (default 14).
            d_period: %D smoothing period (default 3).
            smooth_k: %K smoothing period (default 3).

        Returns:
            StochasticResult with %K, %D, signal, and crossover.
        """
        if len(highs) < k_period:
            return StochasticResult(
                k_line=(),
                d_line=(),
                current_k=50,
                current_d=50,
                signal="neutral",
                crossover="none",
            )

        h = pd.Series(highs, dtype=float)
        l = pd.Series(lows, dtype=float)
        c = pd.Series(closes, dtype=float)

        import pandas_ta as ta

        stoch = ta.stoch(h, l, c, k=k_period, d=d_period, smooth_k=smooth_k)

        if stoch is None or stoch.dropna(how="all").empty:
            return StochasticResult(
                k_line=(),
                d_line=(),
                current_k=50,
                current_d=50,
                signal="neutral",
                crossover="none",
            )

        k_values = tuple(stoch.iloc[:, 0].dropna().tolist())
        d_values = tuple(stoch.iloc[:, 1].dropna().tolist())

        current_k = k_values[-1] if k_values else 50
        current_d = d_values[-1] if d_values else 50

        # Signal
        if current_k > 80:
            signal = "overbought"
        elif current_k < 20:
            signal = "oversold"
        else:
            signal = "neutral"

        # Crossover detection
        crossover = "none"
        if len(k_values) >= 2 and len(d_values) >= 2:
            if k_values[-2] < d_values[-2] and k_values[-1] > d_values[-1]:
                crossover = "bullish"
            elif k_values[-2] > d_values[-2] and k_values[-1] < d_values[-1]:
                crossover = "bearish"

        return StochasticResult(
            k_line=k_values,
            d_line=d_values,
            current_k=round(current_k, 2),
            current_d=round(current_d, 2),
            signal=signal,
            crossover=crossover,
        )

    # ── VWAP ─────────────────────────────────────────────────────────

    def calculate_vwap(
        self,
        ohlcv: list[OHLCV],
        current_price: float | None = None,
    ) -> VWAPResult:
        """Calculate Volume Weighted Average Price with standard deviation bands.

        VWAP is the institutional benchmark price — the average price
        weighted by volume. Price above VWAP = bullish, below = bearish.

        Args:
            ohlcv: OHLCV candles, oldest first.
            current_price: Current price for position detection.

        Returns:
            VWAPResult with VWAP and bands.
        """
        if not ohlcv:
            return VWAPResult(
                vwap=0,
                upper_band=0,
                lower_band=0,
                upper_band_2=0,
                lower_band_2=0,
                price_position="at",
            )

        # Typical price * volume
        tp = np.array([(c.high + c.low + c.close) / 3 for c in ohlcv])
        vol = np.array([c.volume for c in ohlcv])

        cum_tp_vol = np.cumsum(tp * vol)
        cum_vol = np.cumsum(vol)

        vwap_values = cum_tp_vol / np.where(cum_vol > 0, cum_vol, 1)

        # Standard deviation bands
        squared_diffs = (tp - vwap_values) ** 2
        cum_sq = np.cumsum(squared_diffs * vol)
        variance = cum_sq / np.where(cum_vol > 0, cum_vol, 1)
        std = np.sqrt(np.maximum(variance, 0))

        vwap = float(vwap_values[-1])
        std_val = float(std[-1])

        upper_1 = vwap + std_val
        lower_1 = vwap - std_val
        upper_2 = vwap + 2 * std_val
        lower_2 = vwap - 2 * std_val

        price = current_price or float(ohlcv[-1].close)
        if vwap > 0:
            pct_diff = (price - vwap) / vwap
            if pct_diff > 0.001:
                position = "above"
            elif pct_diff < -0.001:
                position = "below"
            else:
                position = "at"
        else:
            position = "at"

        return VWAPResult(
            vwap=round(vwap, 8),
            upper_band=round(upper_1, 8),
            lower_band=round(lower_1, 8),
            upper_band_2=round(upper_2, 8),
            lower_band_2=round(lower_2, 8),
            price_position=position,
        )

    # ── Ichimoku Cloud ───────────────────────────────────────────────

    def calculate_ichimoku(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_b_period: int = 52,
    ) -> IchimokuResult:
        """Calculate Ichimoku Cloud components.

        The Ichimoku Cloud is a comprehensive trend-following system
        that shows support/resistance, trend direction, and momentum.

        Args:
            highs: High prices, oldest first.
            lows: Low prices, oldest first.
            closes: Close prices, oldest first.
            tenkan_period: Tenkan-sen period (default 9).
            kijun_period: Kijun-sen period (default 26).
            senkou_b_period: Senkou Span B period (default 52).

        Returns:
            IchimokuResult with all components and signals.
        """
        if len(highs) < senkou_b_period:
            price = closes[-1] if closes else 0
            return IchimokuResult(
                tenkan_sen=price,
                kijun_sen=price,
                senkou_span_a=price,
                senkou_span_b=price,
                chikou_span=price,
                cloud_color="thin",
                price_vs_cloud="inside",
                signal="neutral",
            )

        h = np.array(highs, dtype=float)
        l = np.array(lows, dtype=float)
        c = np.array(closes, dtype=float)

        # Tenkan-sen (Conversion Line): (9-period high + low) / 2
        def _mid(high: np.ndarray, low: np.ndarray, period: int) -> float:
            return (float(np.max(high[-period:])) + float(np.min(low[-period:]))) / 2

        tenkan = _mid(h, l, tenkan_period)
        kijun = _mid(h, l, kijun_period)
        senkou_a = (tenkan + kijun) / 2
        senkou_b = _mid(h, l, senkou_b_period)
        chikou = float(c[-1])

        # Cloud color and price position
        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)

        if senkou_a > senkou_b:
            cloud_color = "bullish"
        elif senkou_b > senkou_a:
            cloud_color = "bearish"
        else:
            cloud_color = "thin"

        price = float(c[-1])
        if price > cloud_top:
            price_vs_cloud = "above"
        elif price < cloud_bottom:
            price_vs_cloud = "below"
        else:
            price_vs_cloud = "inside"

        # Signal generation
        bullish_conditions = 0
        if price > cloud_top:
            bullish_conditions += 1
        if tenkan > kijun:
            bullish_conditions += 1
        if chikou > float(c[-26]) if len(c) >= 26 else False:
            bullish_conditions += 1
        if cloud_color == "bullish":
            bullish_conditions += 1

        if bullish_conditions >= 4:
            signal = "strong_buy"
        elif bullish_conditions >= 3:
            signal = "buy"
        elif bullish_conditions <= 1:
            bearish_conditions = 4 - bullish_conditions
            signal = "strong_sell" if bearish_conditions >= 3 else "sell"
        else:
            signal = "neutral"

        return IchimokuResult(
            tenkan_sen=round(tenkan, 8),
            kijun_sen=round(kijun, 8),
            senkou_span_a=round(senkou_a, 8),
            senkou_span_b=round(senkou_b, 8),
            chikou_span=round(chikou, 8),
            cloud_color=cloud_color,
            price_vs_cloud=price_vs_cloud,
            signal=signal,
        )

    # ── Fibonacci Retracements ───────────────────────────────────────

    def calculate_fibonacci(
        self,
        ohlcv: list[OHLCV],
        lookback: int = 50,
        current_price: float | None = None,
    ) -> FibonacciLevels:
        """Calculate Fibonacci retracement levels from recent swing.

        Identifies the most recent swing high/low and computes key
        Fibonacci retracement levels (23.6%, 38.2%, 50%, 61.8%, 78.6%).

        Args:
            ohlcv: OHLCV candles, oldest first.
            lookback: Number of candles to look back for swing detection.
            current_price: Current price for nearest level detection.

        Returns:
            FibonacciLevels with retracement levels.
        """
        if len(ohlcv) < 5:
            return FibonacciLevels(
                swing_high=0,
                swing_low=0,
                direction="neutral",
                levels={},
                nearest_level=0,
                nearest_level_name="",
            )

        recent = ohlcv[-lookback:] if len(ohlcv) > lookback else ohlcv
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]

        swing_high = max(highs)
        swing_low = min(lows)

        # Determine direction based on recent price action
        mid_idx = len(recent) // 2
        first_half_high = max(highs[:mid_idx])
        second_half_high = max(highs[mid_idx:])
        first_half_low = min(lows[:mid_idx])
        second_half_low = min(lows[mid_idx:])

        if second_half_high > first_half_high:
            direction = "uptrend"
        elif second_half_low < first_half_low:
            direction = "downtrend"
        else:
            direction = "neutral"

        diff = swing_high - swing_low

        # Fibonacci levels
        fib_ratios = {
            "0.0": 0.0,
            "0.236": 0.236,
            "0.382": 0.382,
            "0.5": 0.5,
            "0.618": 0.618,
            "0.786": 0.786,
            "1.0": 1.0,
        }

        if direction == "uptrend":
            # Retracement from high
            levels = {name: swing_high - diff * ratio for name, ratio in fib_ratios.items()}
        else:
            # Retracement from low
            levels = {name: swing_low + diff * ratio for name, ratio in fib_ratios.items()}

        # Find nearest level to current price
        price = current_price or float(ohlcv[-1].close)
        nearest_name = ""
        nearest_price = 0.0
        min_dist = float("inf")

        for name, level_price in levels.items():
            dist = abs(price - level_price)
            if dist < min_dist:
                min_dist = dist
                nearest_name = name
                nearest_price = level_price

        return FibonacciLevels(
            swing_high=round(swing_high, 8),
            swing_low=round(swing_low, 8),
            direction=direction,
            levels={k: round(v, 8) for k, v in levels.items()},
            nearest_level=round(nearest_price, 8),
            nearest_level_name=nearest_name,
        )

    # ── Chart Pattern Recognition ────────────────────────────────────

    def detect_chart_patterns(
        self,
        ohlcv: list[OHLCV],
        min_pattern_bars: int = 20,
    ) -> list[PatternResult]:
        """Detect common chart patterns in OHLCV data.

        Patterns detected:
        - Double Top / Double Bottom
        - Head and Shoulders / Inverse H&S
        - Ascending/Descending/Symmetric Triangle
        - Bull/Bear Flag

        Args:
            ohlcv: OHLCV candles, oldest first.
            min_pattern_bars: Minimum bars for pattern detection.

        Returns:
            List of detected PatternResult (may be empty).
        """
        if len(ohlcv) < min_pattern_bars:
            return []

        patterns: list[PatternResult] = []

        closes = np.array([c.close for c in ohlcv])
        highs = np.array([c.high for c in ohlcv])
        lows = np.array([c.low for c in ohlcv])

        # Find swing points
        swing_window = max(3, len(ohlcv) // 20)
        swing_highs = self._find_swing_points(highs, swing_window, "high")
        swing_lows = self._find_swing_points(lows, swing_window, "low")

        # Double Top detection
        dt = self._detect_double_top(swing_highs, closes)
        if dt:
            patterns.append(dt)

        # Double Bottom detection
        db = self._detect_double_bottom(swing_lows, closes)
        if db:
            patterns.append(db)

        # Head and Shoulders detection
        hs = self._detect_head_shoulders(swing_highs, swing_lows, closes)
        if hs:
            patterns.append(hs)

        # Triangle detection
        triangle = self._detect_triangle(swing_highs, swing_lows, closes)
        if triangle:
            patterns.append(triangle)

        return patterns

    @staticmethod
    def _find_swing_points(
        data: np.ndarray,
        window: int,
        point_type: str,
    ) -> list[tuple[int, float]]:
        """Find swing highs or lows in price data."""
        points: list[tuple[int, float]] = []
        for i in range(window, len(data) - window):
            if point_type == "high":
                if data[i] == max(data[i - window : i + window + 1]):
                    points.append((i, float(data[i])))
            else:
                if data[i] == min(data[i - window : i + window + 1]):
                    points.append((i, float(data[i])))
        return points

    @staticmethod
    def _detect_double_top(
        swing_highs: list[tuple[int, float]],
        closes: np.ndarray,
    ) -> PatternResult | None:
        """Detect double top pattern."""
        if len(swing_highs) < 2:
            return None

        # Look at last two swing highs
        h1_idx, h1_price = swing_highs[-2]
        h2_idx, h2_price = swing_highs[-1]

        # Similar height (within 2%)
        if h1_price > 0:
            pct_diff = abs(h1_price - h2_price) / h1_price
        else:
            return None

        if pct_diff > 0.02:
            return None

        # Neckline support between the two highs
        neckline = float(np.min(closes[h1_idx : h2_idx + 1]))
        current = float(closes[-1])

        # Breakdown below neckline
        if current < neckline:
            target = neckline - (h1_price - neckline)
            return PatternResult(
                pattern="double_top",
                direction="bearish",
                confidence=0.7,
                target_price=round(target, 8),
                description=f"Double top at {h1_price:.2f}/{h2_price:.2f}, "
                f"neckline {neckline:.2f}, target {target:.2f}",
            )

        return PatternResult(
            pattern="double_top_forming",
            direction="bearish",
            confidence=0.4,
            target_price=round(neckline - (h1_price - neckline), 8),
            description=f"Double top forming at {h1_price:.2f}/{h2_price:.2f}",
        )

    @staticmethod
    def _detect_double_bottom(
        swing_lows: list[tuple[int, float]],
        closes: np.ndarray,
    ) -> PatternResult | None:
        """Detect double bottom pattern."""
        if len(swing_lows) < 2:
            return None

        l1_idx, l1_price = swing_lows[-2]
        l2_idx, l2_price = swing_lows[-1]

        if l1_price > 0:
            pct_diff = abs(l1_price - l2_price) / l1_price
        else:
            return None

        if pct_diff > 0.02:
            return None

        neckline = float(np.max(closes[l1_idx : l2_idx + 1]))
        current = float(closes[-1])

        if current > neckline:
            target = neckline + (neckline - l1_price)
            return PatternResult(
                pattern="double_bottom",
                direction="bullish",
                confidence=0.7,
                target_price=round(target, 8),
                description=f"Double bottom at {l1_price:.2f}/{l2_price:.2f}, "
                f"neckline {neckline:.2f}, target {target:.2f}",
            )

        return PatternResult(
            pattern="double_bottom_forming",
            direction="bullish",
            confidence=0.4,
            target_price=round(neckline + (neckline - l1_price), 8),
            description=f"Double bottom forming at {l1_price:.2f}/{l2_price:.2f}",
        )

    @staticmethod
    def _detect_head_shoulders(
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        closes: np.ndarray,
    ) -> PatternResult | None:
        """Detect head and shoulders pattern."""
        if len(swing_highs) < 3:
            return None

        # Last three swing highs: left shoulder, head, right shoulder
        ls_idx, ls_price = swing_highs[-3]
        h_idx, h_price = swing_highs[-2]
        rs_idx, rs_price = swing_highs[-1]

        # Head must be highest
        if h_price <= ls_price or h_price <= rs_price:
            return None

        # Shoulders should be similar height
        if ls_price > 0:
            shoulder_diff = abs(ls_price - rs_price) / ls_price
        else:
            return None

        if shoulder_diff > 0.05:
            return None

        # Neckline
        neckline_lows = [l for i, l in swing_lows if ls_idx <= i <= rs_idx]
        if not neckline_lows:
            return None

        neckline = float(np.mean(neckline_lows))
        current = float(closes[-1])

        if current < neckline:
            head_height = h_price - neckline
            target = neckline - head_height
            return PatternResult(
                pattern="head_and_shoulders",
                direction="bearish",
                confidence=0.75,
                target_price=round(target, 8),
                description=f"H&S: head={h_price:.2f}, shoulders={ls_price:.2f}/{rs_price:.2f}, "
                f"neckline={neckline:.2f}, target={target:.2f}",
            )

        return PatternResult(
            pattern="head_and_shoulders_forming",
            direction="bearish",
            confidence=0.45,
            target_price=round(neckline - (h_price - neckline), 8),
            description=f"H&S forming: head={h_price:.2f}, shoulders={ls_price:.2f}/{rs_price:.2f}",
        )

    @staticmethod
    def _detect_triangle(
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        closes: np.ndarray,
    ) -> PatternResult | None:
        """Detect triangle patterns (ascending, descending, symmetric)."""
        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return None

        recent_highs = swing_highs[-3:]
        recent_lows = swing_lows[-3:]

        # Check for ascending triangle (flat top, rising bottom)
        high_prices = [p for _, p in recent_highs]
        low_prices = [p for _, p in recent_lows]

        high_slope = (high_prices[-1] - high_prices[0]) / max(high_prices[0], 1)
        low_slope = (low_prices[-1] - low_prices[0]) / max(low_prices[0], 1)

        # Ascending: flat highs, rising lows
        if abs(high_slope) < 0.02 and low_slope > 0.02:
            return PatternResult(
                pattern="ascending_triangle",
                direction="bullish",
                confidence=0.6,
                target_price=round(high_prices[-1] + (high_prices[-1] - low_prices[0]), 8),
                description=f"Ascending triangle: resistance={high_prices[-1]:.2f}, "
                f"rising support from {low_prices[0]:.2f} to {low_prices[-1]:.2f}",
            )

        # Descending: falling highs, flat bottom
        if high_slope < -0.02 and abs(low_slope) < 0.02:
            return PatternResult(
                pattern="descending_triangle",
                direction="bearish",
                confidence=0.6,
                target_price=round(low_prices[-1] - (high_prices[0] - low_prices[-1]), 8),
                description=f"Descending triangle: support={low_prices[-1]:.2f}, "
                f"falling resistance from {high_prices[0]:.2f} to {high_prices[-1]:.2f}",
            )

        # Symmetric: converging highs and lows
        if high_slope < -0.01 and low_slope > 0.01:
            return PatternResult(
                pattern="symmetric_triangle",
                direction="neutral",
                confidence=0.5,
                target_price=round((high_prices[-1] + low_prices[-1]) / 2, 8),
                description=f"Symmetric triangle: converging from "
                f"{high_prices[0]:.2f}/{low_prices[0]:.2f} to "
                f"{high_prices[-1]:.2f}/{low_prices[-1]:.2f}",
            )

        return None

    # ── Candlestick Patterns ─────────────────────────────────────────

    def detect_candlestick_patterns(
        self,
        ohlcv: list[OHLCV],
    ) -> list[CandlestickPattern]:
        """Detect candlestick patterns in OHLCV data.

        Patterns detected:
        - Doji (indecision)
        - Hammer / Inverted Hammer (reversal)
        - Engulfing (bullish/bearish)
        - Morning Star / Evening Star (reversal)
        - Three White Soldiers / Three Black Crows (continuation)

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

            # Doji
            if body / total_range < 0.1:
                patterns.append(
                    CandlestickPattern(
                        pattern="doji",
                        direction="neutral",
                        reliability=0.5,
                        bar_index=i,
                        description="Doji — indecision, potential reversal",
                    )
                )

            # Hammer (bullish reversal)
            if lower_shadow > body * 2 and upper_shadow < body * 0.5 and c_prev.close < c_prev.open:
                patterns.append(
                    CandlestickPattern(
                        pattern="hammer",
                        direction="bullish",
                        reliability=0.65,
                        bar_index=i,
                        description="Hammer — bullish reversal signal after downtrend",
                    )
                )

            # Inverted Hammer
            if upper_shadow > body * 2 and lower_shadow < body * 0.5 and c_prev.close < c_prev.open:
                patterns.append(
                    CandlestickPattern(
                        pattern="inverted_hammer",
                        direction="bullish",
                        reliability=0.55,
                        bar_index=i,
                        description="Inverted Hammer — potential bullish reversal",
                    )
                )

            # Bullish Engulfing
            if (
                c_prev.close < c_prev.open  # Previous bearish
                and c.close > c.open  # Current bullish
                and c.open <= c_prev.close  # Open below prev close
                and c.close >= c_prev.open
            ):  # Close above prev open
                patterns.append(
                    CandlestickPattern(
                        pattern="bullish_engulfing",
                        direction="bullish",
                        reliability=0.7,
                        bar_index=i,
                        description="Bullish Engulfing — strong reversal signal",
                    )
                )

            # Bearish Engulfing
            if (
                c_prev.close > c_prev.open  # Previous bullish
                and c.close < c.open  # Current bearish
                and c.open >= c_prev.close  # Open above prev close
                and c.close <= c_prev.open
            ):  # Close below prev open
                patterns.append(
                    CandlestickPattern(
                        pattern="bearish_engulfing",
                        direction="bearish",
                        reliability=0.7,
                        bar_index=i,
                        description="Bearish Engulfing — strong reversal signal",
                    )
                )

            # Morning Star (bullish reversal, 3-candle)
            if (
                c_prev2.close < c_prev2.open  # First bearish
                and abs(c_prev.close - c_prev.open)
                < (c_prev2.high - c_prev2.low) * 0.3  # Middle small
                and c.close > c.open  # Third bullish
                and c.close > (c_prev2.open + c_prev2.close) / 2
            ):
                patterns.append(
                    CandlestickPattern(
                        pattern="morning_star",
                        direction="bullish",
                        reliability=0.75,
                        bar_index=i,
                        description="Morning Star — strong bullish reversal",
                    )
                )

            # Evening Star (bearish reversal, 3-candle)
            if (
                c_prev2.close > c_prev2.open  # First bullish
                and abs(c_prev.close - c_prev.open)
                < (c_prev2.high - c_prev2.low) * 0.3  # Middle small
                and c.close < c.open  # Third bearish
                and c.close < (c_prev2.open + c_prev2.close) / 2
            ):
                patterns.append(
                    CandlestickPattern(
                        pattern="evening_star",
                        direction="bearish",
                        reliability=0.75,
                        bar_index=i,
                        description="Evening Star — strong bearish reversal",
                    )
                )

        return patterns

    # ── Divergence Detection ─────────────────────────────────────────

    def detect_divergence(
        self,
        prices: list[float],
        indicator_values: list[float],
        indicator_name: str = "RSI",
        lookback: int = 20,
    ) -> DivergenceResult:
        """Detect momentum divergence between price and indicator.

        Divergence occurs when price makes a new high/low but the
        indicator doesn't confirm — often a leading reversal signal.

        Args:
            prices: Price series, oldest first.
            indicator_values: Indicator values, oldest first.
            indicator_name: Name of the indicator for labeling.
            lookback: Number of bars to look back for divergence.

        Returns:
            DivergenceResult with type and strength.
        """
        if len(prices) < lookback or len(indicator_values) < lookback:
            return DivergenceResult(
                divergence_type="none",
                indicator=indicator_name,
                price_action="",
                indicator_action="",
                strength=0,
            )

        p = np.array(prices[-lookback:])
        ind = np.array(indicator_values[-lookback:])

        # Find recent swing highs and lows in price
        window = max(2, lookback // 10)
        price_highs: list[tuple[int, float]] = []
        price_lows: list[tuple[int, float]] = []

        for i in range(window, len(p) - window):
            if p[i] == max(p[i - window : i + window + 1]):
                price_highs.append((i, float(p[i])))
            if p[i] == min(p[i - window : i + window + 1]):
                price_lows.append((i, float(p[i])))

        # Check for bearish divergence: higher price high, lower indicator high
        if len(price_highs) >= 2:
            h1_idx, h1_price = price_highs[-2]
            h2_idx, h2_price = price_highs[-1]

            if h2_price > h1_price:  # Higher high in price
                ind_h1 = float(ind[h1_idx])
                ind_h2 = float(ind[h2_idx])

                if ind_h2 < ind_h1:  # Lower high in indicator
                    strength = min(1.0, (h2_price - h1_price) / h1_price * 10 + 0.3)
                    return DivergenceResult(
                        divergence_type="bearish",
                        indicator=indicator_name,
                        price_action=f"Higher high: {h1_price:.2f} → {h2_price:.2f}",
                        indicator_action=f"Lower high: {ind_h1:.2f} → {ind_h2:.2f}",
                        strength=round(strength, 2),
                    )

        # Check for bullish divergence: lower price low, higher indicator low
        if len(price_lows) >= 2:
            l1_idx, l1_price = price_lows[-2]
            l2_idx, l2_price = price_lows[-1]

            if l2_price < l1_price:  # Lower low in price
                ind_l1 = float(ind[l1_idx])
                ind_l2 = float(ind[l2_idx])

                if ind_l2 > ind_l1:  # Higher low in indicator
                    strength = min(1.0, (l1_price - l2_price) / l1_price * 10 + 0.3)
                    return DivergenceResult(
                        divergence_type="bullish",
                        indicator=indicator_name,
                        price_action=f"Lower low: {l1_price:.2f} → {l2_price:.2f}",
                        indicator_action=f"Higher low: {ind_l1:.2f} → {ind_l2:.2f}",
                        strength=round(strength, 2),
                    )

        return DivergenceResult(
            divergence_type="none",
            indicator=indicator_name,
            price_action="",
            indicator_action="",
            strength=0,
        )

    # ── Multi-Timeframe Confluence ───────────────────────────────────

    async def analyze_multi_timeframe(
        self,
        symbol: str,
        timeframes: list[str],
        indicator_fn: Any,
    ) -> MultiTimeframeResult:
        """Analyze multiple timeframes for signal confluence.

        Computes the same indicator across multiple timeframes and
        checks for agreement. Strong confluence = higher confidence.

        Args:
            symbol: Trading pair.
            timeframes: List of timeframes to analyze.
            indicator_fn: Async function that returns a signal dict for
                a given (symbol, timeframe) pair.

        Returns:
            MultiTimeframeResult with per-TF signals and confluence.
        """
        signals: dict[str, dict[str, Any]] = {}

        for tf in timeframes:
            try:
                result = await indicator_fn(symbol, tf)
                signals[tf] = result
            except Exception as exc:
                logger.debug("MTF analysis failed for %s %s: %s", symbol, tf, exc)
                signals[tf] = {"direction": "neutral", "score": 0.5, "error": str(exc)}

        # Count agreements
        directions = [s.get("direction", "neutral") for s in signals.values()]
        buy_count = directions.count("buy")
        sell_count = directions.count("sell")
        total = len(directions)

        if buy_count > sell_count and buy_count > total / 3:
            consensus = "buy"
            agreement = buy_count
        elif sell_count > buy_count and sell_count > total / 3:
            consensus = "sell"
            agreement = sell_count
        else:
            consensus = "neutral"
            agreement = total - buy_count - sell_count

        confluence = agreement / total if total > 0 else 0

        return MultiTimeframeResult(
            timeframes=tuple(timeframes),
            signals=signals,
            confluence_score=round(confluence, 3),
            direction=consensus,
            agreement=agreement,
            total=total,
        )
