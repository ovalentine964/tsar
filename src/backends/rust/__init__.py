"""
Rust backends — Level 2 implementations via PyO3.

Provides Python wrappers around the `trading_rs` native extension module.
These backends are drop-in replacements for the Python implementations
in `src/backends/python/` — swap via config/backends.yaml.

Architecture:
  Python (AI/ML, strategy, risk decisions)
    ↓ calls
  trading_rs (Rust via PyO3)
    ↓ calls
  Rust crates (WebSocket, tick processing, order execution, compute)

Usage:
    from src.backends.rust import RustCorrelationAnalyzer
    analyzer = RustCorrelationAnalyzer()
    matrix = analyzer.correlation_matrix(price_dict)

Note: If `trading_rs` is not built, all classes fall back to the
Python implementations transparently.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

import os

# TSAR_RUST_BUILD=0 forces pure-Python fallback (e.g. free-tier / no Rust toolchain)
_force_python = os.environ.get("TSAR_RUST_BUILD", "1").strip() in ("0", "false", "no")

if _force_python:
    RUST_AVAILABLE = False
    trading_rs = None  # type: ignore[assignment]
    logger.info("TSAR_RUST_BUILD=0 — Rust backends disabled by config, using pure Python")
else:
    # Try to import the Rust extension module
    try:
        import trading_rs
        RUST_AVAILABLE = True
        logger.info("trading_rs v%s loaded — Rust backends available", trading_rs.version())
    except ImportError:
        RUST_AVAILABLE = False
        trading_rs = None  # type: ignore[assignment]
        logger.warning(
            "trading_rs not available — Rust backends disabled. "
            "Build with: cd rust && maturin develop --release"
        )


# ═══════════════════════════════════════════════════════════════════════
# CORRELATION ANALYZER (Rust-accelerated)
# ═══════════════════════════════════════════════════════════════════════


class RustCorrelationAnalyzer:
    """Rust-accelerated correlation analysis.

    Drop-in replacement for `src.tools.correlation.CorrelationAnalyzer`.
    Falls back to Python if trading_rs is not available.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._fallback = None

    def _get_fallback(self):
        if self._fallback is None:
            from src.tools.correlation import CorrelationAnalyzer
            self._fallback = CorrelationAnalyzer(self._config)
        return self._fallback

    def correlation_matrix(
        self,
        price_dict: dict[str, list[float]],
        window: int = 30,
        use_log_returns: bool = True,
    ) -> Any:
        """Compute full pairwise correlation matrix."""
        if not RUST_AVAILABLE:
            return self._get_fallback().correlation_matrix(price_dict, window, use_log_returns)

        import numpy as np

        symbols = sorted(price_dict.keys())
        n = len(symbols)
        if n < 2:
            from src.tools.correlation import CorrelationMatrix
            return CorrelationMatrix(
                assets=tuple(symbols), matrix=np.array([]),
                avg_correlation=0.0, max_correlation=0.0,
                min_correlation=0.0, regime="insufficient_data",
            )

        # Compute log returns in Python, then pass to Rust for matrix computation
        returns_list = []
        for sym in symbols:
            p = np.array(price_dict[sym], dtype=float)
            if use_log_returns:
                ret = np.diff(np.log(p))
            else:
                ret = np.diff(p) / p[:-1]
            returns_list.append(ret.tolist())

        # Rust-accelerated correlation matrix
        flat_matrix = trading_rs.correlation_matrix_py(returns_list, window)

        # Reconstruct numpy matrix
        matrix = np.array(flat_matrix).reshape(n, n)

        # Stats
        upper = matrix[np.triu_indices(n, k=1)]
        avg_corr = float(np.mean(np.abs(upper))) if len(upper) > 0 else 0.0
        max_corr = float(np.max(upper)) if len(upper) > 0 else 0.0
        min_corr = float(np.min(upper)) if len(upper) > 0 else 0.0

        regime = self._classify_regime(avg_corr, max_corr, min_corr)

        from src.tools.correlation import CorrelationMatrix
        return CorrelationMatrix(
            assets=tuple(symbols),
            matrix=matrix,
            avg_correlation=round(avg_corr, 4),
            max_correlation=round(max_corr, 4),
            min_correlation=round(min_corr, 4),
            regime=regime,
        )

    def rolling_correlation(
        self,
        prices_a: list[float],
        prices_b: list[float],
        window: int = 30,
        use_log_returns: bool = True,
    ) -> Any:
        """Compute rolling Pearson correlation between two price series."""
        if not RUST_AVAILABLE:
            return self._get_fallback().rolling_correlation(
                prices_a, prices_b, window, use_log_returns
            )

        result = trading_rs.rolling_correlation_py(
            prices_a, prices_b, window, use_log_returns
        )

        from src.tools.correlation import CorrelationResult
        return CorrelationResult(
            asset_a="",
            asset_b="",
            correlation=result["correlation"],
            window=window,
            p_value=result["p_value"],
            lag=result["lag"],
            interpretation=self._interpret(result["correlation"], result["p_value"]),
        )

    @staticmethod
    def _classify_regime(avg_corr: float, max_corr: float, min_corr: float) -> str:
        if avg_corr > 0.7:
            return "crisis"
        elif avg_corr > 0.4:
            return "normal"
        elif avg_corr < 0.15:
            return "decoupled"
        elif max_corr - min_corr > 0.5:
            return "rotation"
        return "normal"

    @staticmethod
    def _interpret(corr: float, p_value: float) -> str:
        strength = (
            "very strong" if abs(corr) > 0.8 else
            "strong" if abs(corr) > 0.6 else
            "moderate" if abs(corr) > 0.4 else
            "weak" if abs(corr) > 0.2 else
            "negligible"
        )
        direction = "positive" if corr > 0 else "negative"
        sig = "statistically significant" if p_value < 0.05 else "not statistically significant"
        return f"{strength} {direction} correlation ({sig}, p={p_value:.3f})"


# ═══════════════════════════════════════════════════════════════════════
# MONTE CARLO SIMULATOR (Rust-accelerated)
# ═══════════════════════════════════════════════════════════════════════


class RustMonteCarloSimulator:
    """Rust-accelerated Monte Carlo simulation.

    Drop-in replacement for `src.strategy.monte_carlo.MonteCarloSimulator`.
    Runs N random permutations of trade order to compute confidence intervals.
    """

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._fallback = None

    def _get_fallback(self):
        if self._fallback is None:
            from src.strategy.monte_carlo import MonteCarloSimulator
            self._fallback = MonteCarloSimulator(self._config)
        return self._fallback

    def run(self, backtest_result: Any) -> Any:
        """Run Monte Carlo simulation on backtest trade results."""
        if not RUST_AVAILABLE:
            return self._get_fallback().run(backtest_result)

        import numpy as np
        from src.strategy.monte_carlo import (
            MonteCarloConfig,
            MonteCarloResult,
            PercentileDistribution,
        )

        config = self._config or MonteCarloConfig()
        trades = list(backtest_result.trades)
        if not trades:
            raise ValueError("Cannot run Monte Carlo on backtest with no trades")

        pnl_pcts = [t.pnl_pct for t in trades]

        # Call Rust Monte Carlo
        result = trading_rs.monte_carlo_simulate_py(
            pnl_pcts=pnl_pcts,
            n_simulations=config.n_simulations,
            initial_capital=config.initial_capital,
            risk_free_rate=config.risk_free_rate,
            trading_days=config.trading_days_per_year,
            seed=config.random_seed or 0,
        )

        # Reconstruct PercentileDistribution objects
        distributions = {}
        confidence_intervals = {}

        for metric_name, pct_data in result["percentile_distributions"].items():
            percentiles = {float(k): v for k, v in pct_data.items()
                          if k not in ("mean", "std", "min", "max")}
            dist = PercentileDistribution(
                metric_name=metric_name,
                percentiles=percentiles,
                mean=pct_data["mean"],
                std=pct_data["std"],
                min_val=pct_data["min"],
                max_val=pct_data["max"],
                original=round(getattr(backtest_result.metrics, metric_name, 0.0), 6),
            )
            distributions[metric_name] = dist
            confidence_intervals[metric_name] = percentiles

        logger.info(
            "Rust Monte Carlo complete: %d simulations, "
            "P(profit)=%.2f%%, P(ruin)=%.2f%%",
            result["n_simulations"],
            result["probability_of_profit"] * 100,
            result["probability_of_ruin"] * 100,
        )

        return MonteCarloResult(
            distributions=distributions,
            confidence_intervals=confidence_intervals,
            n_simulations=result["n_simulations"],
            n_trades=result["n_trades"],
            original_result=backtest_result,
            probability_of_profit=result["probability_of_profit"],
            probability_of_ruin=result["probability_of_ruin"],
        )


# ═══════════════════════════════════════════════════════════════════════
# VOLATILITY ANALYZER (Rust-accelerated)
# ═══════════════════════════════════════════════════════════════════════


class RustVolatilityAnalyzer:
    """Rust-accelerated volatility analysis.

    Drop-in replacement for `src.tools.volatility.VolatilityAnalyzer`.
    Accelerates Garman-Klass volatility and GARCH forecasting.
    """

    ANNUALIZATION_FACTOR = 365.0

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._annualization = self._config.get("annualization_factor", self.ANNUALIZATION_FACTOR)
        self._fallback = None

    def _get_fallback(self):
        if self._fallback is None:
            from src.tools.volatility import VolatilityAnalyzer
            self._fallback = VolatilityAnalyzer(self._config)
        return self._fallback

    def historical_volatility_ohlcv(
        self,
        ohlcv: list,
        period: int = 30,
        method: str = "garman_klass",
    ) -> Any:
        """Compute historical volatility using OHLCV data."""
        if not RUST_AVAILABLE or method != "garman_klass":
            return self._get_fallback().historical_volatility_ohlcv(ohlcv, period, method)

        import numpy as np

        recent = ohlcv[-period:]
        opens = [c.open for c in recent]
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        closes = [c.close for c in recent]

        daily_vol = trading_rs.garman_klass_vol_py(opens, highs, lows, closes)
        annualized = daily_vol * (self._annualization ** 0.5)

        # Percentile (requires full history)
        from src.tools.volatility import VolatilityResult
        if len(ohlcv) > period * 3:
            all_closes = [c.close for c in ohlcv]
            percentile = self._get_fallback()._volatility_percentile(
                all_closes, period, daily_vol
            )
        else:
            percentile = 50.0

        return VolatilityResult(
            volatility=round(annualized, 4),
            daily_volatility=round(daily_vol, 4),
            method=method,
            period=period,
            percentile=round(percentile, 1),
            interpretation=self._get_fallback()._interpret_volatility(annualized, percentile),
        )

    def garch_forecast(self, closes: list[float], horizon: int = 10) -> Any:
        """Fit GARCH(1,1) and forecast volatility."""
        if not RUST_AVAILABLE:
            return self._get_fallback().garch_forecast(closes, horizon)

        result = trading_rs.garch_forecast_py(closes, self._annualization)

        from src.tools.volatility import GARCHForecast
        return GARCHForecast(
            current_variance=result["current_variance"],
            forecast_1d=result["forecast_1d"],
            forecast_5d=result["forecast_5d"],
            forecast_10d=result["forecast_10d"],
            annualized_vol=result["annualized_vol"],
            omega=result["omega"],
            alpha=result["alpha"],
            beta=result["beta"],
            persistence=result["persistence"],
        )


# ═══════════════════════════════════════════════════════════════════════
# FACTOR COMPUTATION (Rust-accelerated)
# ═══════════════════════════════════════════════════════════════════════


class RustFactorComputer:
    """Rust-accelerated batch factor computation.

    Computes all 8 core technical indicator factors in a single Rust call,
    avoiding Python loop overhead and GIL contention.
    """

    def compute_all(
        self,
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float],
        **kwargs: Any,
    ) -> dict[str, list[float]]:
        """Batch-compute all technical indicator factors."""
        if not RUST_AVAILABLE:
            return self._fallback_compute(opens, highs, lows, closes, volumes)

        return trading_rs.batch_factors_py(
            opens, highs, lows, closes, volumes,
            rsi_period=kwargs.get("rsi_period", 14),
            macd_fast=kwargs.get("macd_fast", 12),
            macd_slow=kwargs.get("macd_slow", 26),
            macd_signal=kwargs.get("macd_signal", 9),
            bb_period=kwargs.get("bb_period", 20),
            bb_std=kwargs.get("bb_std", 2.0),
            atr_period=kwargs.get("atr_period", 14),
            adx_period=kwargs.get("adx_period", 14),
        )

    @staticmethod
    def _fallback_compute(
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float],
    ) -> dict[str, list[float]]:
        """Fallback to pandas-based computation."""
        import pandas as pd
        from src.strategy import factors

        df = pd.DataFrame({
            "open": opens, "high": highs, "low": lows,
            "close": closes, "volume": volumes,
        })

        result = {}
        for name, entry in factors.FACTOR_REGISTRY.items():
            if entry["category"] in factors.FactorLibrary.INDICATOR_CATEGORIES:
                try:
                    result[name] = entry["func"](df).fillna(0.0).tolist()
                except Exception:
                    result[name] = [0.0] * len(closes)
        return result


# ═══════════════════════════════════════════════════════════════════════
# SLIPPAGE TRACKER (Rust-accelerated)
# ═══════════════════════════════════════════════════════════════════════


class RustSlippageTracker:
    """Rust-accelerated slippage statistics computation."""

    @staticmethod
    def get_slippage_stats(slippage_bps: list[float]) -> dict[str, Any]:
        """Compute slippage statistics from a history of slippage values."""
        if not RUST_AVAILABLE:
            import numpy as np
            if not slippage_bps:
                return {"total_trades": 0, "avg_slippage_bps": 0.0,
                        "median_slippage_bps": 0.0, "max_slippage_bps": 0.0}
            abs_s = [abs(s) for s in slippage_bps]
            return {
                "total_trades": len(abs_s),
                "avg_slippage_bps": round(float(np.mean(abs_s)), 4),
                "median_slippage_bps": round(float(np.median(abs_s)), 4),
                "max_slippage_bps": round(float(np.max(abs_s)), 4),
            }

        return trading_rs.slippage_stats_py(slippage_bps)


__all__ = [
    "RUST_AVAILABLE",
    "RustCorrelationAnalyzer",
    "RustMonteCarloSimulator",
    "RustVolatilityAnalyzer",
    "RustFactorComputer",
    "RustSlippageTracker",
]
