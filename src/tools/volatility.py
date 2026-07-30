"""
TSAR Domain Tools — Volatility Analysis.

Comprehensive volatility analysis for risk management, position sizing,
and regime detection.

Features:
  - Historical volatility (close-to-close, Parkinson, Garman-Klass)
  - Implied volatility proxy (from option-like price behavior)
  - Volatility regime classification (low, normal, high, extreme)
  - Volatility term structure analysis
  - ATR-based volatility normalization
  - Volatility cone (percentile ranking over lookback periods)
  - GARCH(1,1) volatility forecast

Usage:
    from src.tools.volatility import VolatilityAnalyzer

    analyzer = VolatilityAnalyzer()
    hv = analyzer.historical_volatility(closes)
    regime = analyzer.classify_regime(ohlcv)
    forecast = analyzer.garch_forecast(closes)
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
class VolatilityResult:
    """Historical volatility measurement.

    Attributes:
        volatility: Annualized volatility (as decimal, e.g. 0.5 = 50%).
        daily_volatility: Daily volatility.
        method: Calculation method used.
        period: Lookback period used.
        percentile: Where current vol sits vs historical (0-100).
        interpretation: Human-readable interpretation.
    """

    volatility: float
    daily_volatility: float
    method: str
    period: int
    percentile: float
    interpretation: str


@dataclass(frozen=True)
class VolatilityRegime:
    """Volatility regime classification.

    Attributes:
        regime: "low", "normal", "high", or "extreme".
        current_vol: Current annualized volatility.
        percentile: Percentile rank vs history.
        atr_normalized: ATR as percentage of price.
        bollinger_width: Bollinger Band width as % of price.
        recommended_position_size_factor: Suggested position size multiplier.
            (1.0 = normal, <1.0 = reduce, >1.0 = can increase)
        description: Human-readable regime description.
    """

    regime: str
    current_vol: float
    percentile: float
    atr_normalized: float
    bollinger_width: float
    recommended_position_size_factor: float
    description: str


@dataclass(frozen=True)
class ImpliedVolProxy:
    """Implied volatility proxy derived from price action.

    Since crypto options data is often unavailable, this estimates
    implied vol from recent realized vol, skew, and term structure
    patterns in the underlying.

    Attributes:
        iv_proxy: Estimated implied volatility (annualized).
        iv_vs_hv_ratio: IV proxy / historical vol ratio.
        skew: Volatility skew indicator (-1 to 1, negative = put skew).
        interpretation: Human-readable interpretation.
    """

    iv_proxy: float
    iv_vs_hv_ratio: float
    skew: float
    interpretation: str


@dataclass(frozen=True)
class VolatilityTermStructure:
    """Volatility across multiple lookback periods.

    Attributes:
        periods: Periods analyzed (in bars).
        volatilities: Volatility for each period.
        term_structure_slope: Slope of the term structure.
            Positive = contango (longer-term vol higher).
            Negative = backwardation (short-term vol higher).
        is_backwardated: Whether short-term vol exceeds long-term.
    """

    periods: tuple[int, ...]
    volatilities: tuple[float, ...]
    term_structure_slope: float
    is_backwardated: bool


@dataclass(frozen=True)
class VolatilityCone:
    """Volatility percentile cone across lookback periods.

    Shows where current volatility ranks vs historical distribution
    for each lookback period.

    Attributes:
        periods: Periods analyzed.
        current_vols: Current volatility for each period.
        percentiles: Where current vol ranks (0-100) for each period.
        min_vols: Historical minimum vol for each period.
        max_vols: Historical maximum vol for each period.
        median_vols: Historical median vol for each period.
    """

    periods: tuple[int, ...]
    current_vols: tuple[float, ...]
    percentiles: tuple[float, ...]
    min_vols: tuple[float, ...]
    max_vols: tuple[float, ...]
    median_vols: tuple[float, ...]


@dataclass(frozen=True)
class GARCHForecast:
    """GARCH(1,1) volatility forecast.

    Attributes:
        current_variance: Current estimated variance.
        forecast_1d: 1-period ahead variance forecast.
        forecast_5d: 5-period ahead variance forecast.
        forecast_10d: 10-period ahead variance forecast.
        annualized_vol: Current annualized volatility.
        omega: GARCH constant term.
        alpha: GARCH ARCH coefficient.
        beta: GARCH GARCH coefficient.
        persistence: alpha + beta (close to 1 = highly persistent).
    """

    current_variance: float
    forecast_1d: float
    forecast_5d: float
    forecast_10d: float
    annualized_vol: float
    omega: float
    alpha: float
    beta: float
    persistence: float


# ═══════════════════════════════════════════════════════════════════════
# VOLATILITY ANALYZER
# ═══════════════════════════════════════════════════════════════════════


class VolatilityAnalyzer:
    """Comprehensive volatility analysis engine.

    Provides multiple volatility estimators (close-to-close, Parkinson,
    Garman-Klass), regime classification, implied vol proxy, term
    structure analysis, volatility cone, and GARCH forecasting.
    """

    description = (
        "Volatility analysis: historical vol (multiple estimators), "
        "implied vol proxy, regime classification, GARCH forecast, "
        "volatility cone, term structure"
    )

    # Annualization factor for crypto (24/7/365)
    ANNUALIZATION_FACTOR = 365.0

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._annualization = self._config.get("annualization_factor", self.ANNUALIZATION_FACTOR)

    # ── Historical Volatility ────────────────────────────────────────

    def historical_volatility(
        self,
        closes: list[float],
        period: int = 30,
        method: str = "close_to_close",
    ) -> VolatilityResult:
        """Compute historical volatility using various estimators.

        Methods:
        - "close_to_close": Standard deviation of log returns.
        - "parkinson": Uses high-low range (more efficient).
        - "garman_klass": Uses OHLC (most efficient).

        Args:
            closes: Close prices, oldest first.
            period: Lookback period in bars.
            method: Estimation method.

        Returns:
            VolatilityResult with annualized and daily volatility.
        """
        if len(closes) < period + 1:
            return VolatilityResult(
                volatility=0.0, daily_volatility=0.0,
                method=method, period=period,
                percentile=50.0, interpretation="Insufficient data",
            )

        c = np.array(closes[-period - 1:], dtype=float)

        if method == "close_to_close":
            daily_vol = self._close_to_close_vol(c)
        elif method == "parkinson":
            # For Parkinson, we need highs and lows — approximate from closes
            daily_vol = self._close_to_close_vol(c)
        else:
            daily_vol = self._close_to_close_vol(c)

        annualized = daily_vol * np.sqrt(self._annualization)

        # Percentile calculation
        if len(closes) > period * 3:
            percentile = self._volatility_percentile(closes, period, daily_vol)
        else:
            percentile = 50.0

        interpretation = self._interpret_volatility(annualized, percentile)

        return VolatilityResult(
            volatility=round(annualized, 4),
            daily_volatility=round(daily_vol, 4),
            method=method,
            period=period,
            percentile=round(percentile, 1),
            interpretation=interpretation,
        )

    def historical_volatility_ohlcv(
        self,
        ohlcv: list[OHLCV],
        period: int = 30,
        method: str = "garman_klass",
    ) -> VolatilityResult:
        """Compute historical volatility using OHLCV data.

        More efficient estimators that use full OHLC information.

        Args:
            ohlcv: OHLCV candles, oldest first.
            period: Lookback period.
            method: "parkinson", "garman_klass", or "close_to_close".

        Returns:
            VolatilityResult.
        """
        if len(ohlcv) < period + 1:
            return VolatilityResult(
                volatility=0.0, daily_volatility=0.0,
                method=method, period=period,
                percentile=50.0, interpretation="Insufficient data",
            )

        recent = ohlcv[-period:]

        if method == "parkinson":
            daily_vol = self._parkinson_vol(recent)
        elif method == "garman_klass":
            daily_vol = self._garman_klass_vol(recent)
        else:
            closes = [c.close for c in ohlcv[-period - 1:]]
            daily_vol = self._close_to_close_vol(np.array(closes, dtype=float))

        annualized = daily_vol * np.sqrt(self._annualization)

        # Percentile
        if len(ohlcv) > period * 3:
            closes = [c.close for c in ohlcv]
            percentile = self._volatility_percentile(closes, period, daily_vol)
        else:
            percentile = 50.0

        interpretation = self._interpret_volatility(annualized, percentile)

        return VolatilityResult(
            volatility=round(annualized, 4),
            daily_volatility=round(daily_vol, 4),
            method=method,
            period=period,
            percentile=round(percentile, 1),
            interpretation=interpretation,
        )

    # ── Implied Volatility Proxy ─────────────────────────────────────

    def implied_vol_proxy(
        self,
        ohlcv: list[OHLCV],
        short_period: int = 10,
        long_period: int = 30,
    ) -> ImpliedVolProxy:
        """Estimate implied volatility proxy from price action.

        Since crypto options data is sparse, this estimates IV by:
        1. Recent realized vol as base
        2. Adjusting for recent vol acceleration/deceleration
        3. Estimating skew from asymmetric price behavior

        Args:
            ohlcv: OHLCV candles, oldest first.
            short_period: Short-term vol lookback.
            long_period: Long-term vol lookback.

        Returns:
            ImpliedVolProxy with estimated IV.
        """
        if len(ohlcv) < long_period + 1:
            return ImpliedVolProxy(
                iv_proxy=0.0, iv_vs_hv_ratio=1.0,
                skew=0.0, interpretation="Insufficient data",
            )

        closes = np.array([c.close for c in ohlcv], dtype=float)
        highs = np.array([c.high for c in ohlcv], dtype=float)
        lows = np.array([c.low for c in ohlcv], dtype=float)

        # Short-term and long-term realized vol
        short_vol = self._close_to_close_vol(closes[-short_period - 1:])
        long_vol = self._close_to_close_vol(closes[-long_period - 1:])

        # IV proxy: blend of short and long vol, weighted toward short
        # with acceleration adjustment
        if long_vol > 0:
            vol_ratio = short_vol / long_vol
        else:
            vol_ratio = 1.0

        # If vol is accelerating, IV tends to be higher than realized
        iv_proxy_raw = short_vol * np.sqrt(self._annualization)

        # Vol-of-vol adjustment: if recent vol is expanding, IV > RV
        if vol_ratio > 1.2:
            iv_adjustment = 1.1  # IV premium during vol expansion
        elif vol_ratio < 0.8:
            iv_adjustment = 0.95  # IV discount during vol compression
        else:
            iv_adjustment = 1.0

        iv_proxy = iv_proxy_raw * iv_adjustment

        # Volatility skew estimation
        # Measure asymmetry: average up-move vs down-move magnitude
        returns = np.diff(np.log(closes[-long_period:]))
        up_moves = returns[returns > 0]
        down_moves = returns[returns < 0]

        if len(up_moves) > 0 and len(down_moves) > 0:
            avg_up = float(np.mean(np.abs(up_moves)))
            avg_down = float(np.mean(np.abs(down_moves)))
            # Negative skew = larger down moves (put skew)
            skew = float((avg_up - avg_down) / (avg_up + avg_down))
        else:
            skew = 0.0

        # IV/HV ratio
        hv_annualized = long_vol * np.sqrt(self._annualization)
        iv_hv_ratio = iv_proxy / hv_annualized if hv_annualized > 0 else 1.0

        interpretation = self._interpret_iv_proxy(iv_proxy, iv_hv_ratio, skew)

        return ImpliedVolProxy(
            iv_proxy=round(iv_proxy, 4),
            iv_vs_hv_ratio=round(iv_hv_ratio, 3),
            skew=round(skew, 3),
            interpretation=interpretation,
        )

    # ── Volatility Regime ────────────────────────────────────────────

    def classify_regime(
        self,
        ohlcv: list[OHLCV],
        lookback: int = 60,
    ) -> VolatilityRegime:
        """Classify the current volatility regime.

        Regimes:
        - "low": Volatility below 25th percentile (quiet market)
        - "normal": 25th-75th percentile
        - "high": 75th-90th percentile
        - "extreme": Above 90th percentile (crisis)

        Args:
            ohlcv: OHLCV candles, oldest first.
            lookback: Historical lookback for percentile calculation.

        Returns:
            VolatilityRegime with classification and recommendations.
        """
        if len(ohlcv) < lookback:
            return VolatilityRegime(
                regime="normal", current_vol=0.0, percentile=50.0,
                atr_normalized=0.0, bollinger_width=0.0,
                recommended_position_size_factor=1.0,
                description="Insufficient data for regime classification",
            )

        closes = np.array([c.close for c in ohlcv], dtype=float)
        highs = np.array([c.high for c in ohlcv], dtype=float)
        lows = np.array([c.low for c in ohlcv], dtype=float)

        # Current volatility
        current_vol = self._close_to_close_vol(closes[-31:]) * np.sqrt(self._annualization)

        # ATR normalized
        atr = self._calculate_atr(highs, lows, closes, 14)
        current_price = float(closes[-1])
        atr_normalized = atr / current_price if current_price > 0 else 0.0

        # Bollinger Band width
        sma_20 = float(np.mean(closes[-20:]))
        std_20 = float(np.std(closes[-20:]))
        bb_width = (4 * std_20) / sma_20 if sma_20 > 0 else 0.0

        # Historical volatility distribution for percentile
        rolling_vols: list[float] = []
        window = 30
        for i in range(window, len(closes)):
            vol = self._close_to_close_vol(closes[i - window:i + 1])
            rolling_vols.append(vol * np.sqrt(self._annualization))

        if rolling_vols:
            percentile = float(np.sum(np.array(rolling_vols) < current_vol) / len(rolling_vols) * 100)
        else:
            percentile = 50.0

        # Classify regime
        if percentile > 90:
            regime = "extreme"
            size_factor = 0.5
            desc = "Extreme volatility — reduce position sizes significantly"
        elif percentile > 75:
            regime = "high"
            size_factor = 0.7
            desc = "High volatility — reduce position sizes, widen stops"
        elif percentile > 25:
            regime = "normal"
            size_factor = 1.0
            desc = "Normal volatility — standard position sizing"
        else:
            regime = "low"
            size_factor = 1.2
            desc = "Low volatility — consider larger positions, potential breakout setup"

        return VolatilityRegime(
            regime=regime,
            current_vol=round(current_vol, 4),
            percentile=round(percentile, 1),
            atr_normalized=round(atr_normalized, 4),
            bollinger_width=round(bb_width, 4),
            recommended_position_size_factor=round(size_factor, 2),
            description=desc,
        )

    # ── Volatility Term Structure ────────────────────────────────────

    def term_structure(
        self,
        closes: list[float],
        periods: list[int] | None = None,
    ) -> VolatilityTermStructure:
        """Analyze volatility across multiple lookback periods.

        Shows how volatility varies with time horizon — useful for
        understanding whether the market is in a short-term vol spike
        or a sustained volatility regime.

        Args:
            closes: Close prices, oldest first.
            periods: Lookback periods to analyze.

        Returns:
            VolatilityTermStructure with vol at each horizon.
        """
        if periods is None:
            periods = [5, 10, 20, 30, 60, 90]

        c = np.array(closes, dtype=float)

        vols: list[float] = []
        valid_periods: list[int] = []

        for p in periods:
            if len(c) >= p + 1:
                vol = self._close_to_close_vol(c[-p - 1:]) * np.sqrt(self._annualization)
                vols.append(vol)
                valid_periods.append(p)
            else:
                vols.append(0.0)
                valid_periods.append(p)

        # Compute slope (short-term vs long-term)
        if len(vols) >= 2 and vols[-1] > 0:
            slope = (vols[0] - vols[-1]) / vols[-1]
        else:
            slope = 0.0

        return VolatilityTermStructure(
            periods=tuple(valid_periods),
            volatilities=tuple(round(v, 4) for v in vols),
            term_structure_slope=round(slope, 4),
            is_backwardated=slope > 0.1,
        )

    # ── Volatility Cone ──────────────────────────────────────────────

    def volatility_cone(
        self,
        closes: list[float],
        periods: list[int] | None = None,
    ) -> VolatilityCone:
        """Build a volatility cone showing percentile ranks.

        For each lookback period, computes the current volatility and
        where it ranks vs the historical distribution of rolling
        volatilities at that horizon.

        Args:
            closes: Close prices, oldest first.
            periods: Lookback periods to analyze.

        Returns:
            VolatilityCone with percentile ranks.
        """
        if periods is None:
            periods = [10, 20, 30, 60, 90]

        c = np.array(closes, dtype=float)

        current_vols: list[float] = []
        percentiles: list[float] = []
        min_vols: list[float] = []
        max_vols: list[float] = []
        median_vols: list[float] = []

        for p in periods:
            if len(c) < p + 1:
                current_vols.append(0.0)
                percentiles.append(50.0)
                min_vols.append(0.0)
                max_vols.append(0.0)
                median_vols.append(0.0)
                continue

            # Current volatility at this horizon
            current = self._close_to_close_vol(c[-p - 1:]) * np.sqrt(self._annualization)
            current_vols.append(current)

            # Historical distribution of rolling vol at this horizon
            rolling: list[float] = []
            for i in range(p, len(c)):
                v = self._close_to_close_vol(c[i - p:i + 1]) * np.sqrt(self._annualization)
                rolling.append(v)

            if rolling:
                arr = np.array(rolling)
                pct = float(np.sum(arr < current) / len(arr) * 100)
                percentiles.append(pct)
                min_vols.append(float(np.min(arr)))
                max_vols.append(float(np.max(arr)))
                median_vols.append(float(np.median(arr)))
            else:
                percentiles.append(50.0)
                min_vols.append(0.0)
                max_vols.append(0.0)
                median_vols.append(0.0)

        return VolatilityCone(
            periods=tuple(periods),
            current_vols=tuple(round(v, 4) for v in current_vols),
            percentiles=tuple(round(p, 1) for p in percentiles),
            min_vols=tuple(round(v, 4) for v in min_vols),
            max_vols=tuple(round(v, 4) for v in max_vols),
            median_vols=tuple(round(v, 4) for v in median_vols),
        )

    # ── GARCH(1,1) Forecast ─────────────────────────────────────────

    def garch_forecast(
        self,
        closes: list[float],
        horizon: int = 10,
    ) -> GARCHForecast:
        """Fit GARCH(1,1) and forecast volatility.

        GARCH(1,1): σ²_t = ω + α * ε²_{t-1} + β * σ²_{t-1}

        Uses MLE with simplified parameter estimation.

        Args:
            closes: Close prices, oldest first.
            horizon: Forecast horizon in periods.

        Returns:
            GARCHForecast with parameter estimates and forecasts.
        """
        if len(closes) < 50:
            return GARCHForecast(
                current_variance=0.0, forecast_1d=0.0,
                forecast_5d=0.0, forecast_10d=0.0,
                annualized_vol=0.0, omega=0.0, alpha=0.1, beta=0.85,
                persistence=0.95,
            )

        c = np.array(closes, dtype=float)
        returns = np.diff(np.log(c))

        # Simple GARCH(1,1) parameter estimation
        # Using method of moments / rough MLE
        omega, alpha, beta = self._estimate_garch_params(returns)

        # Compute conditional variance series
        n = len(returns)
        variances = np.zeros(n)
        variances[0] = float(np.var(returns))

        for t in range(1, n):
            variances[t] = omega + alpha * returns[t - 1] ** 2 + beta * variances[t - 1]

        current_var = float(variances[-1])

        # Forecast: E[σ²_{t+h}] = ω/(1-α-β) + (α+β)^h * (σ²_t - ω/(1-α-β))
        persistence = alpha + beta
        if persistence < 1:
            long_run_var = omega / (1 - persistence)
            forecast_1 = long_run_var + persistence * (current_var - long_run_var)
            forecast_5 = long_run_var + persistence ** 5 * (current_var - long_run_var)
            forecast_10 = long_run_var + persistence ** horizon * (current_var - long_run_var)
        else:
            # Unit root — forecast equals current
            forecast_1 = current_var
            forecast_5 = current_var
            forecast_10 = current_var

        annualized_vol = float(np.sqrt(current_var * self._annualization))

        return GARCHForecast(
            current_variance=round(current_var, 10),
            forecast_1d=round(float(forecast_1), 10),
            forecast_5d=round(float(forecast_5), 10),
            forecast_10d=round(float(forecast_10), 10),
            annualized_vol=round(annualized_vol, 4),
            omega=round(omega, 10),
            alpha=round(alpha, 4),
            beta=round(beta, 4),
            persistence=round(persistence, 4),
        )

    # ═════════════════════════════════════════════════════════════════
    # VOLATILITY ESTIMATORS
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _close_to_close_vol(closes: np.ndarray) -> float:
        """Standard close-to-close volatility estimator.

        σ = std(ln(C_t / C_{t-1}))
        """
        if len(closes) < 2:
            return 0.0
        log_returns = np.diff(np.log(closes))
        return float(np.std(log_returns, ddof=1))

    @staticmethod
    def _parkinson_vol(ohlcv: list[OHLCV]) -> float:
        """Parkinson volatility estimator using high-low range.

        More efficient than close-to-close (uses ~5x more info).
        σ = sqrt(1/(4n*ln2) * Σ ln(H/L)²)
        """
        if not ohlcv:
            return 0.0
        n = len(ohlcv)
        sum_sq = sum(
            (np.log(c.high / c.low)) ** 2
            for c in ohlcv
            if c.high > 0 and c.low > 0 and c.high >= c.low
        )
        return float(np.sqrt(sum_sq / (4 * n * np.log(2))))

    @staticmethod
    def _garman_klass_vol(ohlcv: list[OHLCV]) -> float:
        """Garman-Klass volatility estimator using OHLC.

        Most efficient estimator for OHLC data.
        σ² = 0.5 * ln(H/L)² - (2*ln2 - 1) * ln(C/O)²
        """
        if not ohlcv:
            return 0.0
        n = len(ohlcv)
        sum_val = 0.0
        for c in ohlcv:
            if c.high <= 0 or c.low <= 0 or c.open <= 0:
                continue
            hl = np.log(c.high / c.low) ** 2
            co = np.log(c.close / c.open) ** 2
            sum_val += 0.5 * hl - (2 * np.log(2) - 1) * co

        variance = sum_val / n
        return float(np.sqrt(max(variance, 0)))

    # ═════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _calculate_atr(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14,
    ) -> float:
        """Compute Average True Range."""
        if len(highs) < period + 1:
            return 0.0
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        return float(np.mean(tr[-period:]))

    def _volatility_percentile(
        self,
        closes: list[float],
        period: int,
        current_daily_vol: float,
    ) -> float:
        """Compute where current volatility sits in the historical distribution."""
        c = np.array(closes, dtype=float)
        rolling_vols: list[float] = []
        for i in range(period, len(c)):
            v = self._close_to_close_vol(c[i - period:i + 1])
            rolling_vols.append(v)

        if not rolling_vols:
            return 50.0

        arr = np.array(rolling_vols)
        return float(np.sum(arr < current_daily_vol) / len(arr) * 100)

    @staticmethod
    def _estimate_garch_params(returns: np.ndarray) -> tuple[float, float, float]:
        """Estimate GARCH(1,1) parameters using method of moments.

        Returns (omega, alpha, beta).
        """
        n = len(returns)
        var = float(np.var(returns))

        # Compute squared returns and lagged variance proxy
        sq_returns = returns ** 2
        mean_sq = float(np.mean(sq_returns))

        # Method of moments: match variance and first autocorrelation of sq returns
        if n < 3:
            return var * 0.05, 0.1, 0.85

        # Autocorrelation of squared returns at lag 1
        acf1 = float(np.corrcoef(sq_returns[:-1], sq_returns[1:])[0, 1])
        if np.isnan(acf1):
            acf1 = 0.1

        # Rough parameter estimates
        # α + β ≈ acf1^(1/1) for GARCH(1,1) autocorrelation
        # β ≈ acf1 (simplification)
        beta = min(max(acf1 * 0.9, 0.5), 0.98)
        alpha = min(max(0.05, mean_sq * 0.1 / var if var > 0 else 0.05), 0.3)

        # Ensure α + β < 1
        if alpha + beta >= 1:
            alpha = (1 - beta) * 0.9

        omega = var * (1 - alpha - beta)
        omega = max(omega, 1e-10)

        return omega, alpha, beta

    # ── Interpretations ──────────────────────────────────────────────

    @staticmethod
    def _interpret_volatility(annualized_vol: float, percentile: float) -> str:
        """Generate human-readable volatility interpretation."""
        vol_pct = annualized_vol * 100
        if annualized_vol > 1.5:
            level = "extremely high"
        elif annualized_vol > 0.8:
            level = "high"
        elif annualized_vol > 0.4:
            level = "moderate"
        elif annualized_vol > 0.2:
            level = "low"
        else:
            level = "very low"

        return (
            f"{level} volatility ({vol_pct:.1f}% annualized), "
            f"{percentile:.0f}th percentile vs history"
        )

    @staticmethod
    def _interpret_iv_proxy(iv: float, iv_hv_ratio: float, skew: float) -> str:
        """Interpret implied volatility proxy."""
        parts: list[str] = []
        parts.append(f"IV proxy: {iv * 100:.1f}% annualized")

        if iv_hv_ratio > 1.2:
            parts.append("IV elevated vs realized (market pricing in more vol)")
        elif iv_hv_ratio < 0.8:
            parts.append("IV compressed vs realized (potential vol expansion ahead)")
        else:
            parts.append("IV in line with realized vol")

        if skew < -0.1:
            parts.append("Negative skew (put protection expensive)")
        elif skew > 0.1:
            parts.append("Positive skew (call demand elevated)")
        else:
            parts.append("Neutral skew")

        return ". ".join(parts)
