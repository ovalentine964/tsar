"""
TSAR Factor Benchmarker — Information Coefficient Analysis.

Computes IC (Information Coefficient), IR (Information Ratio), and
IC-positive ratio for each factor against forward returns. Supports
rolling IC for decay detection.

Usage:
    bench = FactorBenchmarker(library)
    result = bench.run(ohlcv_df, forward_periods=[1, 5, 10])
    print(result.rankings)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.strategy.factor_library import FactorLibrary

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FactorScore:
    """Benchmark score for a single factor."""

    factor_name: str
    category: str
    ic_mean: float
    ic_std: float
    ir: float  # Information Ratio = IC_mean / IC_std
    ic_positive_ratio: float  # % of periods where IC > 0
    ic_abs_mean: float  # Mean of |IC|
    forward_period: int
    n_observations: int


@dataclass
class DecayRow:
    """Rolling IC at a specific window for decay analysis."""

    factor_name: str
    window_start: int
    window_end: int
    ic_mean: float


@dataclass
class FactorBenchmarkResult:
    """Full benchmark results."""

    rankings: list[FactorScore]
    decay: dict[str, list[DecayRow]]  # factor_name -> rolling IC values
    forward_period: int
    n_factors: int
    n_observations: int
    timestamp: str


# ═══════════════════════════════════════════════════════════════════════
# BENCHMARKER
# ═══════════════════════════════════════════════════════════════════════


class FactorBenchmarker:
    """Benchmarks factors using Information Coefficient analysis.

    IC = rank correlation between factor values and forward returns.
    IR = IC_mean / IC_std (signal-to-noise ratio).
    IC-positive ratio = % of time IC > 0 (consistency).
    """

    def __init__(self, library: FactorLibrary) -> None:
        """Initialize with a FactorLibrary instance.

        Args:
            library: FactorLibrary with registered factors.
        """
        self._lib = library

    def run(
        self,
        ohlcv_data: pd.DataFrame,
        forward_periods: list[int] | None = None,
        category: str | None = None,
        min_observations: int = 20,
        rolling_window: int | None = None,
    ) -> FactorBenchmarkResult:
        """Run full benchmark on all factors.

        Args:
            ohlcv_data: OHLCV DataFrame.
            forward_periods: List of forward return periods. Default [1].
            category: If set, only benchmark this category.
            min_observations: Minimum data points required.
            rolling_window: If set, compute rolling IC with this window size.

        Returns:
            FactorBenchmarkResult with ranked factors.
        """
        if forward_periods is None:
            forward_periods = [1]

        fp = forward_periods[0]  # Primary period for ranking
        close = ohlcv_data["close"]

        # Forward returns
        fwd_ret = close.pct_change(periods=fp).shift(-fp)

        # Get factors to benchmark
        if category:
            factors = self._lib.get_factors_by_category(category)
        else:
            factors = self._lib.list_factors()

        scores: list[FactorScore] = []
        decay_data: dict[str, list[DecayRow]] = {}

        for meta in factors:
            try:
                factor_vals = self._lib.compute(meta.name, ohlcv_data)
            except Exception as e:
                logger.warning("Skipping factor %s: %s", meta.name, e)
                continue

            # Align and drop NaN
            combined = pd.DataFrame({"factor": factor_vals, "fwd_ret": fwd_ret}).dropna()

            if len(combined) < min_observations:
                logger.info(
                    "Factor %s: only %d observations (need %d), skipping",
                    meta.name, len(combined), min_observations,
                )
                continue

            # Rank IC (Spearman correlation)
            factor_rank = combined["factor"].rank()
            ret_rank = combined["fwd_ret"].rank()
            ic_series = self._rolling_ic(factor_rank, ret_rank, window=1)

            # Full-sample statistics
            ic_vals = ic_series.dropna()
            if len(ic_vals) == 0:
                continue

            ic_mean = float(ic_vals.mean())
            ic_std = float(ic_vals.std()) if len(ic_vals) > 1 else 0.0
            ir = ic_mean / ic_std if ic_std > 0 else 0.0
            ic_pos_ratio = float((ic_vals > 0).mean())
            ic_abs_mean = float(ic_vals.abs().mean())

            score = FactorScore(
                factor_name=meta.name,
                category=meta.category,
                ic_mean=round(ic_mean, 6),
                ic_std=round(ic_std, 6),
                ir=round(ir, 4),
                ic_positive_ratio=round(ic_pos_ratio, 4),
                ic_abs_mean=round(ic_abs_mean, 6),
                forward_period=fp,
                n_observations=len(ic_vals),
            )
            scores.append(score)

            # Rolling IC for decay detection
            if rolling_window and rolling_window < len(combined):
                decay_rows = self._compute_decay(factor_rank, ret_rank, rolling_window)
                decay_data[meta.name] = decay_rows

            # Persist IC to library DB
            ts = datetime.now(timezone.utc).isoformat()
            self._lib.record_ic(
                factor_name=meta.name,
                timestamp=ts,
                ic_value=ic_mean,
                forward_period=fp,
            )

        # Sort by |IR| descending (best predictive signal first)
        scores.sort(key=lambda s: abs(s.ir), reverse=True)

        return FactorBenchmarkResult(
            rankings=scores,
            decay=decay_data,
            forward_period=fp,
            n_factors=len(scores),
            n_observations=len(ohlcv_data),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def compute_single_ic(
        self,
        factor_name: str,
        ohlcv_data: pd.DataFrame,
        forward_period: int = 1,
    ) -> float:
        """Compute IC for a single factor.

        Args:
            factor_name: Factor name.
            ohlcv_data: OHLCV DataFrame.
            forward_period: Forward return period.

        Returns:
            Spearman rank IC value.
        """
        close = ohlcv_data["close"]
        fwd_ret = close.pct_change(periods=forward_period).shift(-forward_period)
        factor_vals = self._lib.compute(factor_name, ohlcv_data)

        combined = pd.DataFrame({"factor": factor_vals, "fwd_ret": fwd_ret}).dropna()
        if len(combined) < 5:
            return 0.0

        factor_rank = combined["factor"].rank()
        ret_rank = combined["fwd_ret"].rank()
        return float(factor_rank.corr(ret_rank))

    def compute_rolling_ic(
        self,
        factor_name: str,
        ohlcv_data: pd.DataFrame,
        forward_period: int = 1,
        window: int = 50,
    ) -> pd.Series:
        """Compute rolling IC for decay analysis.

        Args:
            factor_name: Factor name.
            ohlcv_data: OHLCV DataFrame.
            forward_period: Forward return period.
            window: Rolling window size.

        Returns:
            pd.Series of rolling IC values.
        """
        close = ohlcv_data["close"]
        fwd_ret = close.pct_change(periods=forward_period).shift(-forward_period)
        factor_vals = self._lib.compute(factor_name, ohlcv_data)

        combined = pd.DataFrame({"factor": factor_vals, "fwd_ret": fwd_ret}).dropna()
        factor_rank = combined["factor"].rank()
        ret_rank = combined["fwd_ret"].rank()

        return self._rolling_ic(factor_rank, ret_rank, window=window)

    # ── Internal ─────────────────────────────────────────────

    @staticmethod
    def _rolling_ic(
        factor_rank: pd.Series,
        ret_rank: pd.Series,
        window: int = 1,
    ) -> pd.Series:
        """Compute rolling Spearman rank correlation.

        For window=1, this is equivalent to per-period rank alignment.
        For larger windows, computes correlation over rolling windows.
        """
        if window <= 1:
            # Per-bar rank "IC": just the correlation of ranks at each point
            # For point-wise, we use the full-series correlation
            return pd.Series(
                factor_rank.corr(ret_rank),
                index=factor_rank.index,
            )

        # Rolling windowed correlation of ranks
        return factor_rank.rolling(window=window).corr(ret_rank)

    @staticmethod
    def _compute_decay(
        factor_rank: pd.Series,
        ret_rank: pd.Series,
        window: int,
    ) -> list[DecayRow]:
        """Compute rolling IC at fixed windows for decay detection."""
        rows: list[DecayRow] = []
        n = len(factor_rank)
        step = max(1, window // 2)  # 50% overlap

        for start in range(0, n - window + 1, step):
            end = start + window
            fr = factor_rank.iloc[start:end]
            rr = ret_rank.iloc[start:end]
            ic = float(fr.corr(rr))
            rows.append(DecayRow(
                factor_name="",
                window_start=start,
                window_end=end,
                ic_mean=round(ic, 6),
            ))
        return rows
