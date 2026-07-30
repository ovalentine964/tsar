"""
TSAR Domain Tools — Multi-Timeframe Confluence Analysis.

Weighted analysis across 4h/1h/15m timeframes to detect confluence
zones where signals agree across multiple timeframes.

Features:
  - Weighted signal aggregation across timeframes
  - Confluence zone detection (support/resistance alignment)
  - Cross-timeframe trend agreement scoring
  - Timeframe hierarchy weighting (higher TF = more weight)
  - Signal conflict detection and resolution

Usage:
    from src.tools.multi_timeframe import MultiTimeframeAnalyzer

    analyzer = MultiTimeframeAnalyzer()
    result = await analyzer.analyze("BTC/USDT", {"4h": ohlcv_4h, "1h": ohlcv_1h, "15m": ohlcv_15m})
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.interfaces.types import OHLCV

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TimeframeSignal:
    """Signal from a single timeframe.

    Attributes:
        timeframe: The timeframe analyzed (e.g. "4h", "1h", "15m").
        direction: "buy", "sell", or "neutral".
        strength: Signal strength (0-1).
        rsi: RSI value for this timeframe.
        macd_histogram: MACD histogram value.
        trend: Trend direction ("up", "down", "flat").
        key_levels: Support/resistance levels detected on this TF.
        weight: Inherited weight from timeframe hierarchy.
    """

    timeframe: str
    direction: str
    strength: float
    rsi: float
    macd_histogram: float
    trend: str
    key_levels: dict[str, float]
    weight: float


@dataclass(frozen=True)
class ConfluenceZone:
    """A price zone where multiple timeframes agree on support/resistance.

    Attributes:
        zone_type: "support" or "resistance".
        price_low: Low end of the zone.
        price_high: High end of the zone.
        center: Zone center price.
        strength: Confluence strength (0-1), higher = more TFs agree.
        timeframes_involved: Which timeframes contribute to this zone.
        touches: Number of price touches in this zone.
    """

    zone_type: str
    price_low: float
    price_high: float
    center: float
    strength: float
    timeframes_involved: tuple[str, ...]
    touches: int


@dataclass(frozen=True)
class MultiTimeframeResult:
    """Aggregated multi-timeframe analysis result.

    Attributes:
        symbol: Trading pair analyzed.
        signals: Per-timeframe signal details.
        confluence_score: Overall confluence score (0-1).
        weighted_direction: Weighted consensus direction.
        weighted_strength: Weighted consensus strength.
        confluence_zones: Price zones with multi-TF agreement.
        conflicts: Timeframes that disagree with consensus.
        summary: Human-readable analysis summary.
    """

    symbol: str
    signals: dict[str, TimeframeSignal]
    confluence_score: float
    weighted_direction: str
    weighted_strength: float
    confluence_zones: tuple[ConfluenceZone, ...]
    conflicts: tuple[str, ...]
    summary: str


# ═══════════════════════════════════════════════════════════════════════
# DEFAULT TIMEFRAME WEIGHTS
# ═══════════════════════════════════════════════════════════════════════

# Higher timeframe = more weight (institutional hierarchy)
DEFAULT_TF_WEIGHTS: dict[str, float] = {
    "1w": 1.0,
    "1d": 0.9,
    "4h": 0.8,
    "1h": 0.6,
    "30m": 0.4,
    "15m": 0.3,
    "5m": 0.2,
    "1m": 0.1,
}


# ═══════════════════════════════════════════════════════════════════════
# MULTI-TIMEFRAME ANALYZER
# ═══════════════════════════════════════════════════════════════════════


class MultiTimeframeAnalyzer:
    """Multi-timeframe confluence analysis engine.

    Analyzes the same asset across multiple timeframes using weighted
    scoring. Higher timeframes carry more weight per institutional
    hierarchy. Detects confluence zones where support/resistance
    levels align across timeframes.
    """

    description = (
        "Multi-timeframe confluence: 4h/1h/15m weighted analysis, "
        "confluence zone detection, cross-TF trend agreement"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._tf_weights = dict(DEFAULT_TF_WEIGHTS)

    @property
    def timeframe_weights(self) -> dict[str, float]:
        """Current timeframe weight configuration."""
        return dict(self._tf_weights)

    def set_timeframe_weights(self, weights: dict[str, float]) -> None:
        """Override default timeframe weights.

        Args:
            weights: Dict of timeframe → weight (0-1).
        """
        self._tf_weights.update(weights)

    # ── Main Analysis ────────────────────────────────────────────────

    async def analyze(
        self,
        symbol: str,
        timeframe_data: dict[str, list[OHLCV]],
        current_price: float | None = None,
    ) -> MultiTimeframeResult:
        """Run multi-timeframe confluence analysis.

        Computes RSI, MACD, trend, and key levels for each timeframe,
        then aggregates with weighted scoring.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            timeframe_data: Dict of timeframe → OHLCV candles.
            current_price: Current price for level analysis.

        Returns:
            MultiTimeframeResult with per-TF signals and confluence.
        """
        signals: dict[str, TimeframeSignal] = {}

        for tf, ohlcv in timeframe_data.items():
            try:
                sig = self._analyze_single_tf(tf, ohlcv, current_price)
                signals[tf] = sig
            except Exception as exc:
                logger.debug("MTF analysis failed for %s %s: %s", symbol, tf, exc)
                signals[tf] = TimeframeSignal(
                    timeframe=tf, direction="neutral", strength=0.0,
                    rsi=50.0, macd_histogram=0.0, trend="flat",
                    key_levels={}, weight=self._tf_weights.get(tf, 0.5),
                )

        # Weighted aggregation
        weighted_dir, weighted_str = self._weighted_aggregate(signals)

        # Confluence zones
        zones = self._detect_confluence_zones(signals, current_price)

        # Conflict detection
        conflicts = self._detect_conflicts(signals, weighted_dir)

        # Confluence score
        if signals:
            agree_count = sum(
                1 for s in signals.values()
                if s.direction == weighted_dir or s.direction == "neutral"
            )
            confluence = agree_count / len(signals)
        else:
            confluence = 0.0

        summary = self._build_summary(symbol, signals, weighted_dir, weighted_str, confluence, zones)

        return MultiTimeframeResult(
            symbol=symbol,
            signals=signals,
            confluence_score=round(confluence, 3),
            weighted_direction=weighted_dir,
            weighted_strength=round(weighted_str, 3),
            confluence_zones=tuple(zones),
            conflicts=tuple(conflicts),
            summary=summary,
        )

    # ── Single Timeframe Analysis ────────────────────────────────────

    def _analyze_single_tf(
        self,
        tf: str,
        ohlcv: list[OHLCV],
        current_price: float | None = None,
    ) -> TimeframeSignal:
        """Analyze a single timeframe for trend, momentum, and levels.

        Args:
            tf: Timeframe string.
            ohlcv: OHLCV candles for this timeframe.
            current_price: Current price.

        Returns:
            TimeframeSignal with direction, strength, and levels.
        """
        if len(ohlcv) < 26:
            return TimeframeSignal(
                timeframe=tf, direction="neutral", strength=0.0,
                rsi=50.0, macd_histogram=0.0, trend="flat",
                key_levels={}, weight=self._tf_weights.get(tf, 0.5),
            )

        closes = np.array([c.close for c in ohlcv], dtype=float)
        highs = np.array([c.high for c in ohlcv], dtype=float)
        lows = np.array([c.low for c in ohlcv], dtype=float)

        # RSI (14-period)
        rsi = self._calculate_rsi(closes, 14)

        # MACD (12, 26, 9)
        macd_line, signal_line, histogram = self._calculate_macd(closes)

        # Trend via EMA crossover
        ema_20 = self._ema(closes, 20)
        ema_50 = self._ema(closes, 50) if len(closes) >= 50 else ema_20

        trend = "flat"
        if float(ema_20[-1]) > float(ema_50[-1]) * 1.002:
            trend = "up"
        elif float(ema_20[-1]) < float(ema_50[-1]) * 0.998:
            trend = "down"

        # Key levels (pivot points)
        key_levels = self._compute_key_levels(highs, lows, closes)

        # Direction scoring
        bull_score = 0.0
        bear_score = 0.0

        # RSI contribution
        if rsi < 30:
            bull_score += 0.3
        elif rsi < 40:
            bull_score += 0.15
        elif rsi > 70:
            bear_score += 0.3
        elif rsi > 60:
            bear_score += 0.15

        # MACD contribution
        if histogram > 0:
            bull_score += 0.3
            if len(macd_line) >= 2 and macd_line[-2] < signal_line[-2] and macd_line[-1] > signal_line[-1]:
                bull_score += 0.1  # Bullish crossover
        elif histogram < 0:
            bear_score += 0.3
            if len(macd_line) >= 2 and macd_line[-2] > signal_line[-2] and macd_line[-1] < signal_line[-1]:
                bear_score += 0.1  # Bearish crossover

        # Trend contribution
        if trend == "up":
            bull_score += 0.3
        elif trend == "down":
            bear_score += 0.3

        # Price vs VWAP-like (using SMA50 as proxy)
        price = current_price or float(closes[-1])
        sma_50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else float(np.mean(closes))
        if price > sma_50 * 1.01:
            bull_score += 0.1
        elif price < sma_50 * 0.99:
            bear_score += 0.1

        total = bull_score + bear_score
        if total > 0:
            if bull_score > bear_score * 1.2:
                direction = "buy"
                strength = bull_score / total
            elif bear_score > bull_score * 1.2:
                direction = "sell"
                strength = bear_score / total
            else:
                direction = "neutral"
                strength = 1 - abs(bull_score - bear_score) / total
        else:
            direction = "neutral"
            strength = 0.0

        return TimeframeSignal(
            timeframe=tf,
            direction=direction,
            strength=round(strength, 3),
            rsi=round(rsi, 2),
            macd_histogram=round(float(histogram), 8),
            trend=trend,
            key_levels=key_levels,
            weight=self._tf_weights.get(tf, 0.5),
        )

    # ── Weighted Aggregation ─────────────────────────────────────────

    def _weighted_aggregate(
        self,
        signals: dict[str, TimeframeSignal],
    ) -> tuple[str, float]:
        """Compute weighted direction and strength across timeframes.

        Uses timeframe hierarchy weights to prioritize higher TFs.

        Returns:
            Tuple of (direction, strength).
        """
        if not signals:
            return "neutral", 0.0

        bull_weight = 0.0
        bear_weight = 0.0
        total_weight = 0.0

        for sig in signals.values():
            w = sig.weight * sig.strength
            total_weight += sig.weight
            if sig.direction == "buy":
                bull_weight += w
            elif sig.direction == "sell":
                bear_weight += w

        if total_weight == 0:
            return "neutral", 0.0

        if bull_weight > bear_weight * 1.1:
            return "buy", round(bull_weight / total_weight, 3)
        elif bear_weight > bull_weight * 1.1:
            return "sell", round(bear_weight / total_weight, 3)
        else:
            return "neutral", round(1 - abs(bull_weight - bear_weight) / total_weight, 3)

    # ── Confluence Zone Detection ────────────────────────────────────

    def _detect_confluence_zones(
        self,
        signals: dict[str, TimeframeSignal],
        current_price: float | None = None,
    ) -> list[ConfluenceZone]:
        """Detect price zones where multiple timeframes agree.

        Looks for overlapping support/resistance levels across TFs.
        """
        zones: list[ConfluenceZone] = []

        # Collect all S/R levels with their TF source
        all_levels: list[tuple[str, str, float]] = []  # (tf, level_type, price)
        for tf, sig in signals.items():
            for level_name, level_price in sig.key_levels.items():
                level_type = "support" if "support" in level_name or "pivot" in level_name else "resistance"
                all_levels.append((tf, level_type, level_price))

        if not all_levels:
            return zones

        # Cluster nearby levels (within 1% of each other)
        used: set[int] = set()
        for i, (tf_a, type_a, price_a) in enumerate(all_levels):
            if i in used:
                continue
            cluster_tfs = [tf_a]
            cluster_prices = [price_a]
            cluster_type = type_a

            for j, (tf_b, type_b, price_b) in enumerate(all_levels):
                if j == i or j in used:
                    continue
                if price_a > 0 and abs(price_a - price_b) / price_a < 0.01:
                    cluster_tfs.append(tf_b)
                    cluster_prices.append(price_b)
                    used.add(j)

            if len(cluster_tfs) >= 2:
                used.add(i)
                low_p = min(cluster_prices)
                high_p = max(cluster_prices)
                center = float(np.mean(cluster_prices))
                strength = min(1.0, len(cluster_tfs) / max(len(signals), 1))

                zones.append(ConfluenceZone(
                    zone_type=cluster_type,
                    price_low=round(low_p, 8),
                    price_high=round(high_p, 8),
                    center=round(center, 8),
                    strength=round(strength, 3),
                    timeframes_involved=tuple(cluster_tfs),
                    touches=len(cluster_tfs),
                ))

        # Sort by strength descending
        zones.sort(key=lambda z: z.strength, reverse=True)
        return zones

    # ── Conflict Detection ───────────────────────────────────────────

    @staticmethod
    def _detect_conflicts(
        signals: dict[str, TimeframeSignal],
        consensus: str,
    ) -> list[str]:
        """Identify timeframes that disagree with the consensus.

        Returns list of timeframe names that conflict.
        """
        conflicts: list[str] = []
        for tf, sig in signals.items():
            if sig.direction != "neutral" and sig.direction != consensus:
                conflicts.append(tf)
        return conflicts

    # ── Technical Indicators (local, no external deps) ───────────────

    @staticmethod
    def _calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
        """Compute RSI from close prices."""
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = float(np.mean(gains[-period:]))
        avg_loss = float(np.mean(losses[-period:]))

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - 100 / (1 + rs))

    @staticmethod
    def _calculate_macd(
        closes: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal_period: int = 9,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute MACD line, signal line, and histogram."""
        ema_fast = MultiTimeframeAnalyzer._ema(closes, fast)
        ema_slow = MultiTimeframeAnalyzer._ema(closes, slow)

        # Pad shorter EMA to match length
        if len(ema_fast) < len(ema_slow):
            pad = len(ema_slow) - len(ema_fast)
            ema_fast = np.concatenate([np.full(pad, ema_fast[0]), ema_fast])
        elif len(ema_slow) < len(ema_fast):
            pad = len(ema_fast) - len(ema_slow)
            ema_slow = np.concatenate([np.full(pad, ema_slow[0]), ema_slow])

        macd_line = ema_fast - ema_slow
        signal_line = MultiTimeframeAnalyzer._ema(macd_line, signal_period)

        # Align lengths
        min_len = min(len(macd_line), len(signal_line))
        macd_line = macd_line[-min_len:]
        signal_line = signal_line[-min_len:]
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        """Compute Exponential Moving Average."""
        if len(data) < period:
            return data.copy()
        alpha = 2 / (period + 1)
        ema = np.zeros(len(data))
        ema[:period] = np.mean(data[:period])
        for i in range(period, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema[period - 1:]

    @staticmethod
    def _compute_key_levels(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> dict[str, float]:
        """Compute pivot-based support/resistance levels.

        Uses classic pivot point formula:
            Pivot = (H + L + C) / 3
            R1 = 2*Pivot - L
            S1 = 2*Pivot - H
            R2 = Pivot + (H - L)
            S2 = Pivot - (H - L)
        """
        if len(highs) < 2:
            return {}

        # Use last complete bar for pivot
        h = float(highs[-2])
        l = float(lows[-2])
        c = float(closes[-2])

        pivot = (h + l + c) / 3
        r1 = 2 * pivot - l
        s1 = 2 * pivot - h
        r2 = pivot + (h - l)
        s2 = pivot - (h - l)

        return {
            "pivot": round(pivot, 8),
            "resistance_1": round(r1, 8),
            "resistance_2": round(r2, 8),
            "support_1": round(s1, 8),
            "support_2": round(s2, 8),
        }

    # ── Summary Builder ──────────────────────────────────────────────

    @staticmethod
    def _build_summary(
        symbol: str,
        signals: dict[str, TimeframeSignal],
        direction: str,
        strength: float,
        confluence: float,
        zones: list[ConfluenceZone],
    ) -> str:
        """Build a human-readable analysis summary."""
        parts: list[str] = []
        parts.append(f"📊 Multi-TF Analysis for {symbol}")

        # Per-TF summary
        for tf, sig in sorted(signals.items()):
            arrow = "🟢" if sig.direction == "buy" else "🔴" if sig.direction == "sell" else "⚪"
            parts.append(f"  {arrow} {tf}: {sig.direction.upper()} (str={sig.strength:.2f}, RSI={sig.rsi:.1f}, trend={sig.trend})")

        # Consensus
        emoji = "🟢" if direction == "buy" else "🔴" if direction == "sell" else "⚪"
        parts.append(f"\n{emoji} Consensus: {direction.upper()} (strength={strength:.2f}, confluence={confluence:.0%})")

        # Confluence zones
        if zones:
            parts.append(f"\n📍 {len(zones)} confluence zone(s):")
            for z in zones[:3]:
                parts.append(
                    f"  • {z.zone_type} @ {z.center:.2f} ({z.price_low:.2f}-{z.price_high:.2f}), "
                    f"strength={z.strength:.2f}, TFs={','.join(z.timeframes_involved)}"
                )

        return "\n".join(parts)
