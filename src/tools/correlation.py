"""
TSAR Domain Tools — Correlation Analysis.

Cross-asset correlation analysis for portfolio construction,
risk management, and regime detection.

Features:
  - Rolling Pearson correlation between asset pairs
  - Full correlation matrix computation
  - Cross-asset correlation with lag detection
  - Correlation regime classification (normal, crisis, decoupled)
  - Cointegration testing (Engle-Granger)
  - Correlation anomaly detection (regime shifts)

Usage:
    from src.tools.correlation import CorrelationAnalyzer

    analyzer = CorrelationAnalyzer()
    corr = analyzer.rolling_correlation(prices_a, prices_b, window=30)
    matrix = analyzer.correlation_matrix(price_dict)
    regime = analyzer.classify_regime(price_dict)
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
class CorrelationResult:
    """Correlation between two assets.

    Attributes:
        asset_a: First asset symbol.
        asset_b: Second asset symbol.
        correlation: Pearson correlation coefficient (-1 to 1).
        window: Lookback window used.
        p_value: Statistical significance (if computed).
        lag: Detected lag in periods (0 = contemporaneous).
        interpretation: Human-readable interpretation.
    """

    asset_a: str
    asset_b: str
    correlation: float
    window: int
    p_value: float
    lag: int
    interpretation: str


@dataclass(frozen=True)
class CorrelationMatrix:
    """Full correlation matrix between multiple assets.

    Attributes:
        assets: Ordered list of asset symbols.
        matrix: 2D numpy array of correlations.
        avg_correlation: Average pairwise correlation.
        max_correlation: Highest pairwise correlation.
        min_correlation: Lowest pairwise correlation.
        regime: Correlation regime classification.
    """

    assets: tuple[str, ...]
    matrix: np.ndarray
    avg_correlation: float
    max_correlation: float
    min_correlation: float
    regime: str


@dataclass(frozen=True)
class CorrelationAnomaly:
    """Detected correlation regime shift.

    Attributes:
        asset_a: First asset.
        asset_b: Second asset.
        current_corr: Current correlation.
        historical_mean: Historical mean correlation.
        historical_std: Historical standard deviation.
        z_score: How many std deviations from mean.
        direction: "increasing" or "decreasing".
        severity: "mild", "moderate", or "severe".
    """

    asset_a: str
    asset_b: str
    current_corr: float
    historical_mean: float
    historical_std: float
    z_score: float
    direction: str
    severity: str


@dataclass(frozen=True)
class CointegrationResult:
    """Engle-Granger cointegration test result.

    Attributes:
        asset_a: First asset.
        asset_b: Second asset.
        is_cointegrated: Whether the pair is cointegrated.
        adf_statistic: Augmented Dickey-Fuller test statistic.
        p_value: P-value of the test.
        hedge_ratio: Beta for dollar-neutral portfolio.
        half_life: Mean reversion half-life in periods.
    """

    asset_a: str
    asset_b: str
    is_cointegrated: bool
    adf_statistic: float
    p_value: float
    hedge_ratio: float
    half_life: float


# ═══════════════════════════════════════════════════════════════════════
# CORRELATION ANALYZER
# ═══════════════════════════════════════════════════════════════════════


class CorrelationAnalyzer:
    """Cross-asset correlation analysis engine.

    Computes rolling correlations, correlation matrices, regime
    classification, cointegration testing, and anomaly detection.
    Uses log returns for stable estimation across different price levels.
    """

    description = (
        "Cross-asset correlation: rolling Pearson, correlation matrix, "
        "regime detection, cointegration testing, anomaly detection"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    # ── Rolling Correlation ──────────────────────────────────────────

    def rolling_correlation(
        self,
        prices_a: list[float],
        prices_b: list[float],
        window: int = 30,
        use_log_returns: bool = True,
    ) -> CorrelationResult:
        """Compute rolling Pearson correlation between two price series.

        Uses log returns by default for stationarity.

        Args:
            prices_a: Price series for asset A (oldest first).
            prices_b: Price series for asset B (oldest first).
            window: Rolling window size in periods.
            use_log_returns: If True, compute on log returns.

        Returns:
            CorrelationResult with current correlation and stats.
        """
        if len(prices_a) < window + 1 or len(prices_b) < window + 1:
            return CorrelationResult(
                asset_a="",
                asset_b="",
                correlation=0.0,
                window=window,
                p_value=1.0,
                lag=0,
                interpretation="Insufficient data",
            )

        a = np.array(prices_a, dtype=float)
        b = np.array(prices_b, dtype=float)

        # Align lengths
        min_len = min(len(a), len(b))
        a = a[-min_len:]
        b = b[-min_len:]

        if use_log_returns:
            ret_a = np.diff(np.log(a))
            ret_b = np.diff(np.log(b))
        else:
            ret_a = np.diff(a) / a[:-1]
            ret_b = np.diff(b) / b[:-1]

        # Compute correlation on the window
        window_data_a = ret_a[-window:]
        window_data_b = ret_b[-window:]

        corr, p_val = self._pearson_corr(window_data_a, window_data_b)

        # Lag detection (cross-correlation at small lags)
        best_lag = 0
        best_corr = abs(corr)
        for lag in range(1, min(5, window // 4)):
            if len(ret_a) > lag + window:
                c, _ = self._pearson_corr(ret_a[-window - lag : -lag], ret_b[-window:])
                if abs(c) > best_corr:
                    best_corr = abs(c)
                    best_lag = lag

        interpretation = self._interpret_correlation(corr, p_val)

        return CorrelationResult(
            asset_a="",
            asset_b="",
            correlation=round(corr, 4),
            window=window,
            p_value=round(p_val, 4),
            lag=best_lag,
            interpretation=interpretation,
        )

    # ── Correlation Matrix ───────────────────────────────────────────

    def correlation_matrix(
        self,
        price_dict: dict[str, list[float]],
        window: int = 30,
        use_log_returns: bool = True,
    ) -> CorrelationMatrix:
        """Compute full pairwise correlation matrix.

        Args:
            price_dict: Dict of symbol → price series (oldest first).
            window: Rolling window for correlation computation.
            use_log_returns: Use log returns for stationarity.

        Returns:
            CorrelationMatrix with pairwise correlations and stats.
        """
        symbols = sorted(price_dict.keys())
        n = len(symbols)

        if n < 2:
            return CorrelationMatrix(
                assets=tuple(symbols),
                matrix=np.array([]),
                avg_correlation=0.0,
                max_correlation=0.0,
                min_correlation=0.0,
                regime="insufficient_data",
            )

        # Compute log returns for all assets
        returns: dict[str, np.ndarray] = {}
        for sym, prices in price_dict.items():
            p = np.array(prices, dtype=float)
            if use_log_returns:
                returns[sym] = np.diff(np.log(p))
            else:
                returns[sym] = np.diff(p) / p[:-1]

        # Build correlation matrix
        matrix = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                ret_i = returns[symbols[i]]
                ret_j = returns[symbols[j]]
                min_len = min(len(ret_i), len(ret_j))
                corr, _ = self._pearson_corr(ret_i[-min_len:], ret_j[-min_len:])
                matrix[i, j] = corr
                matrix[j, i] = corr

        # Stats
        upper = matrix[np.triu_indices(n, k=1)]
        avg_corr = float(np.mean(np.abs(upper))) if len(upper) > 0 else 0.0
        max_corr = float(np.max(upper)) if len(upper) > 0 else 0.0
        min_corr = float(np.min(upper)) if len(upper) > 0 else 0.0

        regime = self._classify_regime_from_corr(avg_corr, max_corr, min_corr)

        return CorrelationMatrix(
            assets=tuple(symbols),
            matrix=matrix,
            avg_correlation=round(avg_corr, 4),
            max_correlation=round(max_corr, 4),
            min_correlation=round(min_corr, 4),
            regime=regime,
        )

    # ── Regime Classification ────────────────────────────────────────

    def classify_regime(
        self,
        price_dict: dict[str, list[float]],
        window: int = 30,
    ) -> str:
        """Classify the current correlation regime.

        Regimes:
        - "crisis": High correlations across assets (risk-off, all move together)
        - "normal": Moderate correlations, diversified
        - "decoupled": Low correlations, assets move independently
        - "rotation": Mixed correlations, sector rotation

        Args:
            price_dict: Dict of symbol → price series.
            window: Lookback window.

        Returns:
            Regime string.
        """
        matrix = self.correlation_matrix(price_dict, window)
        return matrix.regime

    def detect_anomalies(
        self,
        price_dict: dict[str, list[float]],
        current_window: int = 20,
        history_window: int = 120,
        z_threshold: float = 2.0,
    ) -> list[CorrelationAnomaly]:
        """Detect correlation regime shifts.

        Compares current correlation to historical mean and flags
        pairs where the correlation deviates by > z_threshold std devs.

        Args:
            price_dict: Dict of symbol → price series.
            current_window: Window for current correlation.
            history_window: Window for historical baseline.
            z_threshold: Z-score threshold for anomaly flagging.

        Returns:
            List of CorrelationAnomaly (may be empty).
        """
        anomalies: list[CorrelationAnomaly] = []
        symbols = sorted(price_dict.keys())

        if len(symbols) < 2:
            return anomalies

        # Compute returns
        returns: dict[str, np.ndarray] = {}
        for sym, prices in price_dict.items():
            p = np.array(prices, dtype=float)
            returns[sym] = np.diff(np.log(p))

        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                ret_i = returns[symbols[i]]
                ret_j = returns[symbols[j]]
                min_len = min(len(ret_i), len(ret_j))
                ret_i = ret_i[-min_len:]
                ret_j = ret_j[-min_len:]

                if min_len < history_window:
                    continue

                # Current correlation
                curr_corr, _ = self._pearson_corr(ret_i[-current_window:], ret_j[-current_window:])

                # Historical rolling correlations
                hist_corrs: list[float] = []
                for k in range(history_window - current_window):
                    start = k
                    end = k + current_window
                    c, _ = self._pearson_corr(ret_i[start:end], ret_j[start:end])
                    hist_corrs.append(c)

                if not hist_corrs:
                    continue

                hist_mean = float(np.mean(hist_corrs))
                hist_std = float(np.std(hist_corrs))

                if hist_std < 0.001:
                    continue

                z = (curr_corr - hist_mean) / hist_std

                if abs(z) > z_threshold:
                    direction = "increasing" if z > 0 else "decreasing"
                    if abs(z) > 3.0:
                        severity = "severe"
                    elif abs(z) > 2.5:
                        severity = "moderate"
                    else:
                        severity = "mild"

                    anomalies.append(
                        CorrelationAnomaly(
                            asset_a=symbols[i],
                            asset_b=symbols[j],
                            current_corr=round(curr_corr, 4),
                            historical_mean=round(hist_mean, 4),
                            historical_std=round(hist_std, 4),
                            z_score=round(z, 2),
                            direction=direction,
                            severity=severity,
                        )
                    )

        return anomalies

    # ── Cointegration Testing ────────────────────────────────────────

    def test_cointegration(
        self,
        prices_a: list[float],
        prices_b: list[float],
        significance: float = 0.05,
    ) -> CointegrationResult:
        """Test for cointegration using the Engle-Granger method.

        Two series are cointegrated if a linear combination of them
        is stationary (mean-reverting). Useful for pairs trading.

        Args:
            prices_a: Price series for asset A.
            prices_b: Price series for asset B.
            significance: P-value threshold for cointegration.

        Returns:
            CointegrationResult with test statistics.
        """
        a = np.array(prices_a, dtype=float)
        b = np.array(prices_b, dtype=float)

        min_len = min(len(a), len(b))
        if min_len < 30:
            return CointegrationResult(
                asset_a="",
                asset_b="",
                is_cointegrated=False,
                adf_statistic=0.0,
                p_value=1.0,
                hedge_ratio=1.0,
                half_life=0.0,
            )

        a = a[-min_len:]
        b = b[-min_len:]

        # Step 1: OLS regression to find hedge ratio
        hedge_ratio = self._ols_beta(a, b)
        spread = a - hedge_ratio * b

        # Step 2: ADF test on the spread
        adf_stat, p_value = self._adf_test(spread)

        # Step 3: Half-life of mean reversion
        half_life = self._half_life(spread)

        is_coint = p_value < significance

        return CointegrationResult(
            asset_a="",
            asset_b="",
            is_cointegrated=is_coint,
            adf_statistic=round(adf_stat, 4),
            p_value=round(p_value, 4),
            hedge_ratio=round(hedge_ratio, 4),
            half_life=round(half_life, 1),
        )

    # ── Statistical Helpers ──────────────────────────────────────────

    @staticmethod
    def _pearson_corr(
        x: np.ndarray,
        y: np.ndarray,
    ) -> tuple[float, float]:
        """Compute Pearson correlation coefficient and approximate p-value.

        Returns:
            Tuple of (correlation, p_value).
        """
        n = len(x)
        if n < 3:
            return 0.0, 1.0

        x_mean = np.mean(x)
        y_mean = np.mean(y)

        cov = np.sum((x - x_mean) * (y - y_mean))
        std_x = np.sqrt(np.sum((x - x_mean) ** 2))
        std_y = np.sqrt(np.sum((y - y_mean) ** 2))

        if std_x == 0 or std_y == 0:
            return 0.0, 1.0

        corr = cov / (std_x * std_y)
        corr = float(np.clip(corr, -1.0, 1.0))

        # Approximate p-value using t-distribution
        if abs(corr) >= 1.0:
            return corr, 0.0

        t_stat = corr * np.sqrt((n - 2) / (1 - corr**2))
        # Approximate p-value (two-tailed)
        df = n - 2
        # Use a simple approximation for p-value
        p_value = 2.0 * min(
            _t_cdf_approx(t_stat, df),
            1 - _t_cdf_approx(t_stat, df),
        )
        p_value = float(np.clip(p_value, 0.0, 1.0))

        return corr, p_value

    @staticmethod
    def _ols_beta(y: np.ndarray, x: np.ndarray) -> float:
        """Simple OLS regression: y = alpha + beta * x. Returns beta."""
        n = len(x)
        if n < 2:
            return 1.0
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        cov_xy = np.sum((x - x_mean) * (y - y_mean))
        var_x = np.sum((x - x_mean) ** 2)
        if var_x == 0:
            return 1.0
        return float(cov_xy / var_x)

    @staticmethod
    def _adf_test(series: np.ndarray, max_lag: int = 5) -> tuple[float, float]:
        """Simplified Augmented Dickey-Fuller test.

        Tests the null hypothesis that the series has a unit root
        (is non-stationary).

        Returns:
            Tuple of (adf_statistic, approximate_p_value).
        """
        n = len(series)
        if n < max_lag + 3:
            return 0.0, 1.0

        # First differences
        diff = np.diff(series)
        lagged = series[max_lag:-1]

        # Build regressors: lagged level + lagged differences
        y = diff[max_lag:]
        X_parts = [np.ones(len(y)), lagged]
        for lag in range(1, max_lag + 1):
            X_parts.append(
                diff[max_lag - lag : -lag] if lag < len(diff) - max_lag else diff[max_lag - lag :]
            )

        min_len = min(len(y), min(len(x) for x in X_parts))
        y = y[:min_len]
        X = np.column_stack([x[:min_len] for x in X_parts])

        # OLS
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            residuals = y - X @ beta
            se = np.sqrt(np.sum(residuals**2) / (len(y) - len(beta)))
            XtX_inv = np.linalg.inv(X.T @ X)
            se_beta = se * np.sqrt(np.diag(XtX_inv))
            adf_stat = float(beta[1] / se_beta[1]) if se_beta[1] > 0 else 0.0
        except (np.linalg.LinAlgError, ZeroDivisionError):
            adf_stat = 0.0

        # Approximate p-value (MacKinnon critical values approximation)
        # These are rough approximations for common sample sizes
        if adf_stat < -3.43:
            p_value = 0.01
        elif adf_stat < -2.86:
            p_value = 0.05
        elif adf_stat < -2.57:
            p_value = 0.10
        else:
            p_value = 0.50

        return adf_stat, p_value

    @staticmethod
    def _half_life(spread: np.ndarray) -> float:
        """Estimate mean reversion half-life using OLS on lagged spread.

        Half-life = -ln(2) / ln(1 + theta)
        where spread_t = theta * spread_{t-1} + epsilon
        """
        n = len(spread)
        if n < 3:
            return 0.0

        y = np.diff(spread)
        x = spread[:-1]

        # OLS: y = alpha + beta * x
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        cov_xy = np.sum((x - x_mean) * (y - y_mean))
        var_x = np.sum((x - x_mean) ** 2)

        if var_x == 0:
            return 0.0

        theta = cov_xy / var_x
        if theta >= 0:
            return 0.0  # Not mean-reverting

        half_life = -np.log(2) / theta
        return float(max(0, half_life))

    # ── Regime Classification ────────────────────────────────────────

    @staticmethod
    def _classify_regime_from_corr(
        avg_corr: float,
        max_corr: float,
        min_corr: float,
    ) -> str:
        """Classify regime based on correlation statistics."""
        if avg_corr > 0.7:
            return "crisis"
        elif avg_corr > 0.4:
            return "normal"
        elif avg_corr < 0.15:
            return "decoupled"
        elif max_corr - min_corr > 0.5:
            return "rotation"
        else:
            return "normal"

    @staticmethod
    def _interpret_correlation(corr: float, p_value: float) -> str:
        """Generate human-readable correlation interpretation."""
        strength = ""
        if abs(corr) > 0.8:
            strength = "very strong"
        elif abs(corr) > 0.6:
            strength = "strong"
        elif abs(corr) > 0.4:
            strength = "moderate"
        elif abs(corr) > 0.2:
            strength = "weak"
        else:
            strength = "negligible"

        direction = "positive" if corr > 0 else "negative"
        sig = "statistically significant" if p_value < 0.05 else "not statistically significant"

        return f"{strength} {direction} correlation ({sig}, p={p_value:.3f})"


# ═══════════════════════════════════════════════════════════════════════
# HELPER: T-DISTRIBUTION CDF APPROXIMATION
# ═══════════════════════════════════════════════════════════════════════


def _t_cdf_approx(t: float, df: int) -> float:
    """Approximate the CDF of the t-distribution.

    Uses the regularized incomplete beta function approximation.
    """
    x = df / (df + t**2)
    # Simple approximation for the regularized incomplete beta function
    # This is a rough approximation sufficient for p-value estimation
    if x <= 0:
        return 1.0
    if x >= 1:
        return 0.0

    # Use the continued fraction approximation
    a = df / 2
    b = 0.5

    # Simple beta function approximation
    try:
        from math import lgamma

        lgamma(a) + lgamma(b) - lgamma(a + b)
        # Incomplete beta (very rough approximation)
        if t > 0:
            return 0.5 + 0.5 * min(1.0, t / (t**2 + df) ** 0.5)
        else:
            return 0.5 - 0.5 * min(1.0, abs(t) / (t**2 + df) ** 0.5)
    except (ValueError, OverflowError):
        return 0.5
