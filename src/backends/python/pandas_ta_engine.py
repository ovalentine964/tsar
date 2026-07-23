"""
PandasTAEngine — Technical indicators via pandas-ta + numpy.

Day1 implementation of PricingEngine. Uses pandas-ta for RSI, EMA,
MACD, Bollinger Bands, ATR, and pivot-based support/resistance detection.

Level 2: RustTickEngine (Rust tick processor via PyO3)
Level 3: QuantLibEngine (C++ QuantLib via pybind11)
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from src.interfaces.pricing_engine import PricingEngine
from src.interfaces.types import (
    BollingerResult,
    MACDResult,
    OHLCV,
    SRLevel,
    SRLevels,
)

logger = logging.getLogger(__name__)


class PandasTAEngine(PricingEngine):
    """Pricing engine using pandas-ta for technical indicators.

    All methods are stateless — they convert input lists to pandas Series,
    call the appropriate pandas-ta function, and return typed results.
    """

    def __init__(self, **kwargs: Any) -> None:
        pass

    # ═══════════════════════════════════════════════════════════════
    # TECHNICAL INDICATORS
    # ═══════════════════════════════════════════════════════════════

    def calculate_rsi(self, closes: list[float], period: int = 14) -> float:
        """Calculate Relative Strength Index (RSI).

        Args:
            closes: List of closing prices, oldest first.
            period: Lookback period (default 14).

        Returns:
            Latest RSI value (0-100). Returns 50.0 if insufficient data.

        Raises:
            ValueError: If closes is empty or period < 1.
        """
        if not closes:
            raise ValueError("closes must not be empty")
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")

        import pandas_ta as ta

        series = pd.Series(closes, dtype=float)
        rsi = ta.rsi(series, length=period)

        if rsi is not None and not rsi.dropna().empty:
            return float(rsi.iloc[-1])

        logger.warning("RSI returned no data (len=%d, period=%d), defaulting to 50.0", len(closes), period)
        return 50.0

    def calculate_macd(
        self,
        closes: list[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> MACDResult:
        """Calculate MACD (Moving Average Convergence Divergence).

        Args:
            closes: List of closing prices, oldest first.
            fast: Fast EMA period (default 12).
            slow: Slow EMA period (default 26).
            signal: Signal line EMA period (default 9).

        Returns:
            MACDResult with macd_line, signal_line, and histogram tuples.

        Raises:
            ValueError: If closes is empty or period parameters are invalid.
        """
        if not closes:
            raise ValueError("closes must not be empty")
        if fast < 1 or slow < 1 or signal < 1:
            raise ValueError("fast, slow, and signal must all be >= 1")
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be less than slow ({slow})")

        import pandas_ta as ta

        series = pd.Series(closes, dtype=float)
        macd_df = ta.macd(series, fast=fast, slow=slow, signal=signal)

        if macd_df is not None and not macd_df.dropna(how="all").empty:
            # pandas-ta MACD columns: MACD_{fast}_{slow}_{signal},
            # MACDh_{fast}_{slow}_{signal}, MACDs_{fast}_{slow}_{signal}
            macd_line = tuple(macd_df.iloc[:, 0].fillna(0.0).tolist())
            histogram = tuple(macd_df.iloc[:, 1].fillna(0.0).tolist())
            signal_line = tuple(macd_df.iloc[:, 2].fillna(0.0).tolist())
            return MACDResult(
                macd_line=macd_line,
                signal_line=signal_line,
                histogram=histogram,
            )

        logger.warning("MACD returned no data (len=%d), returning zeros", len(closes))
        zeros = tuple(0.0 for _ in closes)
        return MACDResult(macd_line=zeros, signal_line=zeros, histogram=zeros)

    def calculate_bollinger(
        self,
        closes: list[float],
        period: int = 20,
        std_dev: float = 2.0,
    ) -> BollingerResult:
        """Calculate Bollinger Bands.

        Args:
            closes: List of closing prices, oldest first.
            period: SMA lookback period (default 20).
            std_dev: Number of standard deviations for bands (default 2.0).

        Returns:
            BollingerResult with upper, middle, lower, and bandwidth tuples.

        Raises:
            ValueError: If closes is empty or period < 1.
        """
        if not closes:
            raise ValueError("closes must not be empty")
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")

        import pandas_ta as ta

        series = pd.Series(closes, dtype=float)
        bb = ta.bbands(series, length=period, std=std_dev)

        if bb is not None and not bb.dropna(how="all").empty:
            # pandas-ta bbands columns: BBL, BBM, BBU, BBB, BBP
            lower = tuple(bb.iloc[:, 0].fillna(0.0).tolist())
            mid = tuple(bb.iloc[:, 1].fillna(0.0).tolist())
            upper = tuple(bb.iloc[:, 2].fillna(0.0).tolist())
            bandwidth = tuple(bb.iloc[:, 3].fillna(0.0).tolist())
            return BollingerResult(
                upper=upper,
                middle=mid,
                lower=lower,
                bandwidth=bandwidth,
            )

        logger.warning("Bollinger returned no data (len=%d), returning zeros", len(closes))
        zeros = tuple(0.0 for _ in closes)
        return BollingerResult(upper=zeros, middle=zeros, lower=zeros, bandwidth=zeros)

    def calculate_atr(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> float:
        """Calculate Average True Range (ATR).

        Args:
            highs: List of high prices, oldest first.
            lows: List of low prices, oldest first.
            closes: List of closing prices, oldest first.
            period: Lookback period (default 14).

        Returns:
            Latest ATR value. Returns 0.0 if insufficient data.

        Raises:
            ValueError: If price lists are empty, have different lengths,
                or period < 1.
        """
        if not highs or not lows or not closes:
            raise ValueError("highs, lows, and closes must not be empty")
        if not (len(highs) == len(lows) == len(closes)):
            raise ValueError(
                f"Price lists must have equal length, got "
                f"highs={len(highs)}, lows={len(lows)}, closes={len(closes)}"
            )
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")

        import pandas_ta as ta

        h = pd.Series(highs, dtype=float)
        l = pd.Series(lows, dtype=float)
        c = pd.Series(closes, dtype=float)
        atr = ta.atr(h, l, c, length=period)

        if atr is not None and not atr.dropna().empty:
            return float(atr.iloc[-1])

        logger.warning("ATR returned no data (len=%d, period=%d), defaulting to 0.0", len(closes), period)
        return 0.0

    def calculate_ema(self, data: list[float], period: int = 20) -> list[float]:
        """Calculate Exponential Moving Average (EMA).

        Args:
            data: List of values, oldest first.
            period: EMA lookback period (default 20).

        Returns:
            List of EMA values (shorter than input by period-1 elements).

        Raises:
            ValueError: If data is empty or period < 1.
        """
        if not data:
            raise ValueError("data must not be empty")
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")

        import pandas_ta as ta

        series = pd.Series(data, dtype=float)
        ema = ta.ema(series, length=period)

        if ema is not None and not ema.dropna().empty:
            return [float(v) for v in ema.dropna().tolist()]

        # Fallback: return last value repeated if EMA can't be computed
        logger.warning("EMA returned no data (len=%d, period=%d), returning fallback", len(data), period)
        return [data[-1]]

    def detect_support_resistance(
        self,
        ohlcv: list[OHLCV],
    ) -> SRLevels:
        """Detect support and resistance levels from OHLCV data.

        Uses a combination of pivot point detection and volume clustering
        to identify key price levels.

        Algorithm:
        1. Find local pivot highs and lows (swing points)
        2. Cluster nearby levels within a tolerance band
        3. Score each cluster by number of touches and volume
        4. Classify as support (below current price) or resistance (above)

        Args:
            ohlcv: List of OHLCV candles, oldest first.

        Returns:
            SRLevels with supports and resistances as SRLevel tuples.

        Raises:
            ValueError: If ohlcv is empty.
        """
        if not ohlcv:
            raise ValueError("ohlcv must not be empty")

        # Need at least 5 candles for pivot detection
        if len(ohlcv) < 5:
            current_price = ohlcv[-1].close
            return SRLevels(
                supports=(SRLevel(price=current_price * 0.98, strength=0.3, level_type="support", touches=1),),
                resistances=(SRLevel(price=current_price * 1.02, strength=0.3, level_type="resistance", touches=1),),
            )

        highs = np.array([c.high for c in ohlcv], dtype=float)
        lows = np.array([c.low for c in ohlcv], dtype=float)
        closes = np.array([c.close for c in ohlcv], dtype=float)
        volumes = np.array([c.volume for c in ohlcv], dtype=float)
        current_price = closes[-1]

        # ── Step 1: Find pivot points ───────────────────────────
        pivot_window = max(2, len(ohlcv) // 20)  # adaptive window
        pivot_highs: list[tuple[int, float]] = []
        pivot_lows: list[tuple[int, float]] = []

        for i in range(pivot_window, len(ohlcv) - pivot_window):
            # Pivot high: highest high in window
            if highs[i] == max(highs[i - pivot_window: i + pivot_window + 1]):
                pivot_highs.append((i, highs[i]))
            # Pivot low: lowest low in window
            if lows[i] == min(lows[i - pivot_window: i + pivot_window + 1]):
                pivot_lows.append((i, lows[i]))

        # ── Step 2: Cluster nearby levels ───────────────────────
        avg_range = float(np.mean(highs - lows))
        tolerance = avg_range * 1.5  # cluster tolerance

        def _cluster_levels(
            points: list[tuple[int, float]],
        ) -> list[dict[str, Any]]:
            """Cluster nearby price points into levels."""
            if not points:
                return []

            sorted_pts = sorted(points, key=lambda x: x[1])
            clusters: list[dict[str, Any]] = []
            current_cluster: list[tuple[int, float]] = [sorted_pts[0]]

            for pt in sorted_pts[1:]:
                if pt[1] - current_cluster[-1][1] <= tolerance:
                    current_cluster.append(pt)
                else:
                    clusters.append(_summarize_cluster(current_cluster))
                    current_cluster = [pt]
            clusters.append(_summarize_cluster(current_cluster))
            return clusters

        def _summarize_cluster(
            points: list[tuple[int, float]],
        ) -> dict[str, Any]:
            """Create a summary for a cluster of points."""
            prices = [p[1] for p in points]
            indices = [p[0] for p in points]
            avg_price = float(np.mean(prices))
            total_vol = float(sum(volumes[i] for i in indices))
            return {
                "price": avg_price,
                "touches": len(points),
                "volume": total_vol,
            }

        high_clusters = _cluster_levels(pivot_highs)
        low_clusters = _cluster_levels(pivot_lows)

        # ── Step 3: Score and classify ──────────────────────────
        max_touches = max(
            (c["touches"] for c in high_clusters + low_clusters),
            default=1,
        )
        total_vol = float(np.sum(volumes)) or 1.0

        supports: list[SRLevel] = []
        resistances: list[SRLevel] = []

        for cluster in high_clusters:
            # Strength: weighted by touches and volume
            touch_score = cluster["touches"] / max_touches
            vol_score = min(cluster["volume"] / total_vol * 10, 1.0)
            strength = min(touch_score * 0.6 + vol_score * 0.4, 1.0)

            level = SRLevel(
                price=round(cluster["price"], 8),
                strength=round(strength, 4),
                level_type="resistance" if cluster["price"] > current_price else "support",
                touches=cluster["touches"],
            )
            if level.level_type == "resistance":
                resistances.append(level)
            else:
                supports.append(level)

        for cluster in low_clusters:
            touch_score = cluster["touches"] / max_touches
            vol_score = min(cluster["volume"] / total_vol * 10, 1.0)
            strength = min(touch_score * 0.6 + vol_score * 0.4, 1.0)

            level = SRLevel(
                price=round(cluster["price"], 8),
                strength=round(strength, 4),
                level_type="resistance" if cluster["price"] > current_price else "support",
                touches=cluster["touches"],
            )
            if level.level_type == "resistance":
                resistances.append(level)
            else:
                supports.append(level)

        # Deduplicate nearby levels (keep strongest)
        supports = _dedupe_levels(supports, tolerance)
        resistances = _dedupe_levels(resistances, tolerance)

        # Sort: supports ascending, resistances ascending
        supports = tuple(sorted(supports, key=lambda x: x.price))
        resistances = tuple(sorted(resistances, key=lambda x: x.price))

        return SRLevels(supports=supports, resistances=resistances)


def _dedupe_levels(levels: list[SRLevel], tolerance: float) -> tuple[SRLevel, ...]:
    """Remove duplicate levels within tolerance, keeping the strongest."""
    if not levels:
        return ()

    sorted_levels = sorted(levels, key=lambda x: x.price)
    result: list[SRLevel] = [sorted_levels[0]]

    for level in sorted_levels[1:]:
        if level.price - result[-1].price <= tolerance:
            # Keep the one with more touches / higher strength
            if level.strength > result[-1].strength:
                result[-1] = level
        else:
            result.append(level)

    return tuple(result)
