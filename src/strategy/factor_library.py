"""
TSAR Factor Library — Factor Management & Persistence.

FactorLibrary manages factor registration, metadata, IC history, and decay
tracking. It delegates pure computation to factors.py functions.

Features:
  - Register/retrieve factors by name, category, or universe
  - Compute factor values from OHLCV DataFrames
  - Persist factor metadata, IC history, and decay to SQLite
  - Support custom factor registration

Usage:
    lib = FactorLibrary("factors.db")
    values = lib.compute("rsi", ohlcv_df)
    momentum_factors = lib.get_factors_by_category("momentum")
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from src.strategy.factors import FACTOR_REGISTRY

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FactorMeta:
    """Metadata for a registered factor."""

    name: str
    description: str
    category: str  # momentum | mean_reversion | volatility | volume | trend | pattern
    default_params: dict[str, Any]
    universe: list[str]
    custom: bool = False


@dataclass
class ICRecord:
    """A single Information Coefficient observation."""

    factor_name: str
    timestamp: str
    ic_value: float
    forward_period: int
    symbol: str = ""


# ═══════════════════════════════════════════════════════════════════════
# FACTOR LIBRARY
# ═══════════════════════════════════════════════════════════════════════


class FactorLibrary:
    """Manages a library of quantitative trading factors.

    Combines an in-memory registry of compute functions with SQLite
    persistence for factor metadata, IC history, and decay tracking.
    """

    VALID_CATEGORIES = {
        "momentum",       # Technical indicators: RSI, MACD, Stochastic, etc.
        "mean_reversion", # Mean reversion indicators: BB %B, Z-Score, etc.
        "volatility",     # Volatility indicators: ATR, BB width, etc.
        "volume",         # Volume indicators: OBV, CMF, etc.
        "trend",          # Trend indicators: ADX, Aroon, Ichimoku, etc.
        "pattern",        # Candlestick patterns: engulfing, pin bar, etc.
        "risk_factor",    # Risk factors: beta, correlation, drawdown, etc.
        "macro_factor",   # Macro factors: DXY sensitivity, rate sensitivity, etc.
    }

    # Category classification: which are pure indicators vs risk/macro factors
    INDICATOR_CATEGORIES = {"momentum", "mean_reversion", "volatility", "volume", "trend", "pattern"}
    RISK_FACTOR_CATEGORIES = {"risk_factor", "macro_factor"}

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Initialize the factor library.

        G13 NOTE: FactorLibrary intentionally uses a separate SQLite database
        (factors.db) from the main tsar.db.  This is a deliberate design
        decision — factors are a different concern from trade records,
        strategy genomes, and lessons.  The factor DB contains only
        factor metadata and IC history, which are computationally derived
        and can be regenerated from scratch.  Keeping them separate avoids
        coupling the factor benchmarking lifecycle to the core trading DB,
        simplifies backup/restore of the trading state, and allows the
        factor DB to be shared across environments without leaking trade data.

        Args:
            db_path: Path to SQLite database, or ":memory:" for in-memory.
        """
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row

        # In-memory registry: name -> compute function
        self._functions: dict[str, Callable[..., pd.Series]] = {}

        # In-memory metadata cache
        self._meta: dict[str, FactorMeta] = {}

        # Bootstrap: load built-in factors from FACTOR_REGISTRY
        self._init_db()
        self._load_builtin_factors()

    # ── Lifecycle ────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS factors (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                default_params TEXT NOT NULL DEFAULT '{}',
                universe TEXT NOT NULL DEFAULT '[]',
                custom INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS ic_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                ic_value REAL NOT NULL,
                forward_period INTEGER NOT NULL DEFAULT 1,
                symbol TEXT DEFAULT '',
                FOREIGN KEY (factor_name) REFERENCES factors(name)
            );

            CREATE INDEX IF NOT EXISTS idx_ic_factor ON ic_history(factor_name);
            CREATE INDEX IF NOT EXISTS idx_ic_timestamp ON ic_history(timestamp);
        """)
        self._conn.commit()

    def _load_builtin_factors(self) -> None:
        """Register all built-in factors from FACTOR_REGISTRY."""
        for name, entry in FACTOR_REGISTRY.items():
            meta = FactorMeta(
                name=name,
                description=str(entry["description"]),
                category=str(entry["category"]),
                default_params=dict(entry.get("default_params", {})),  # type: ignore[arg-type]
                universe=list(entry.get("universe", [])),  # type: ignore[arg-type]
                custom=False,
            )
            self._functions[name] = entry["func"]  # type: ignore[assignment]
            self._meta[name] = meta
            self._upsert_factor_db(meta)

    def _upsert_factor_db(self, meta: FactorMeta) -> None:
        """Insert or update factor metadata in SQLite."""
        self._conn.execute(
            """INSERT OR REPLACE INTO factors (name, description, category, default_params, universe, custom)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                meta.name,
                meta.description,
                meta.category,
                json.dumps(meta.default_params),
                json.dumps(meta.universe),
                int(meta.custom),
            ),
        )
        self._conn.commit()

    # ── Registration ─────────────────────────────────────────

    def register(
        self,
        name: str,
        func: Callable[..., pd.Series],
        category: str,
        description: str = "",
        default_params: dict[str, Any] | None = None,
        universe: list[str] | None = None,
    ) -> None:
        """Register a custom factor.

        Args:
            name: Unique factor name.
            func: Compute function (df, **kwargs) -> pd.Series.
            category: Factor category.
            description: Human-readable description.
            default_params: Default parameters for the factor.
            universe: Asset classes this factor applies to.

        Raises:
            ValueError: If category is invalid.
        """
        if category not in self.VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. Must be one of {self.VALID_CATEGORIES}"
            )

        meta = FactorMeta(
            name=name,
            description=description or f"Custom factor: {name}",
            category=category,
            default_params=default_params or {},
            universe=universe or ["crypto", "equity"],
            custom=True,
        )
        self._functions[name] = func
        self._meta[name] = meta
        self._upsert_factor_db(meta)
        logger.info("Registered custom factor: %s [%s]", name, category)

    # ── Retrieval ────────────────────────────────────────────

    def get_factor_meta(self, name: str) -> FactorMeta | None:
        """Get metadata for a factor by name."""
        return self._meta.get(name)

    def get_factors_by_category(self, category: str) -> list[FactorMeta]:
        """Get all factors in a category."""
        return [m for m in self._meta.values() if m.category == category]

    def get_factors_by_universe(self, symbol_type: str) -> list[FactorMeta]:
        """Get all factors applicable to a given asset class."""
        return [m for m in self._meta.values() if symbol_type in m.universe]

    def list_factors(self) -> list[FactorMeta]:
        """List all registered factors."""
        return list(self._meta.values())

    def get_categories(self) -> dict[str, int]:
        """Get factor counts by category."""
        counts: dict[str, int] = {}
        for m in self._meta.values():
            counts[m.category] = counts.get(m.category, 0) + 1
        return counts

    def get_indicators(self) -> list[FactorMeta]:
        """Get all technical indicator factors (momentum, mean_reversion, etc.)."""
        return [m for m in self._meta.values() if m.category in self.INDICATOR_CATEGORIES]

    def get_risk_factors(self) -> list[FactorMeta]:
        """Get all risk/macro factors (risk_factor, macro_factor)."""
        return [m for m in self._meta.values() if m.category in self.RISK_FACTOR_CATEGORIES]

    def is_indicator(self, name: str) -> bool:
        """Check if a factor is a technical indicator (vs risk factor)."""
        meta = self._meta.get(name)
        return meta is not None and meta.category in self.INDICATOR_CATEGORIES

    def is_risk_factor(self, name: str) -> bool:
        """Check if a factor is a risk/macro factor."""
        meta = self._meta.get(name)
        return meta is not None and meta.category in self.RISK_FACTOR_CATEGORIES

    # ── IC Decay Tracking ──────────────────────────────────

    def get_ic_decay(
        self,
        factor_name: str,
        window_count: int = 10,
    ) -> list[dict[str, Any]]:
        """Compute IC decay for a factor over rolling windows.

        IC decay measures how a factor's predictive power changes over time.
        A declining IC suggests the factor is losing alpha (alpha decay).

        Args:
            factor_name: Factor to analyze.
            window_count: Number of rolling windows to compute.

        Returns:
            List of dicts with window_start, window_end, ic_value, and decay_rate.
        """
        history = self.get_ic_history(factor_name, limit=1000)
        if len(history) < window_count:
            return []

        # Sort by timestamp
        history.sort(key=lambda r: r.timestamp)

        # Split into windows
        window_size = max(1, len(history) // window_count)
        windows: list[dict[str, Any]] = []

        for i in range(0, len(history), window_size):
            chunk = history[i:i + window_size]
            if not chunk:
                continue
            ic_mean = sum(r.ic_value for r in chunk) / len(chunk)
            windows.append({
                "window_index": len(windows),
                "window_start": chunk[0].timestamp,
                "window_end": chunk[-1].timestamp,
                "ic_mean": round(ic_mean, 6),
                "n_observations": len(chunk),
            })

        # Compute decay rate (IC change per window)
        if len(windows) >= 2:
            for i in range(1, len(windows)):
                decay = windows[i]["ic_mean"] - windows[i - 1]["ic_mean"]
                windows[i]["decay_rate"] = round(decay, 6)
            windows[0]["decay_rate"] = 0.0

            # Overall trend: linear regression slope of IC over windows
            ic_values = [w["ic_mean"] for w in windows]
            x = np.arange(len(ic_values), dtype=float)
            x_mean = x.mean()
            x_var = ((x - x_mean) ** 2).sum()
            if x_var > 0:
                y_mean = np.mean(ic_values)
                slope = float(((x - x_mean) * (np.array(ic_values) - y_mean)).sum() / x_var)
                for w in windows:
                    w["overall_decay_slope"] = round(slope, 6)

        return windows

    def get_factors_with_decay_alert(
        self,
        threshold: float = -0.01,
    ) -> list[dict[str, Any]]:
        """Find factors with significant IC decay.

        Args:
            threshold: Decay slope threshold. Factors with slope below this
                      are flagged as decaying.

        Returns:
            List of factors with their decay info.
        """
        alerts: list[dict[str, Any]] = []
        for meta in self.list_factors():
            decay = self.get_ic_decay(meta.name)
            if not decay:
                continue
            slope = decay[0].get("overall_decay_slope", 0.0) if decay else 0.0
            if slope < threshold:
                alerts.append({
                    "factor_name": meta.name,
                    "category": meta.category,
                    "decay_slope": slope,
                    "latest_ic": decay[-1]["ic_mean"] if decay else 0.0,
                    "n_windows": len(decay),
                })
        return alerts

    # ── Computation ──────────────────────────────────────────

    def compute(
        self,
        factor_name: str,
        ohlcv_data: pd.DataFrame,
        **override_params: Any,
    ) -> pd.Series:
        """Compute a factor's values from OHLCV data.

        Args:
            factor_name: Name of the factor to compute.
            ohlcv_data: DataFrame with columns [open, high, low, close, volume].
            **override_params: Override default parameters.

        Returns:
            pd.Series of factor values aligned to ohlcv_data index.

        Raises:
            KeyError: If factor_name is not registered.
        """
        if factor_name not in self._functions:
            raise KeyError(
                f"Factor '{factor_name}' not registered. "
                f"Available: {list(self._functions.keys())}"
            )

        # Merge default params with overrides
        meta = self._meta[factor_name]
        params = {**meta.default_params, **override_params}

        func = self._functions[factor_name]
        return func(ohlcv_data, **params)

    def compute_all(
        self,
        ohlcv_data: pd.DataFrame,
        category: str | None = None,
        **override_params: Any,
    ) -> pd.DataFrame:
        """Compute all factors (or a category) and return as DataFrame.

        Args:
            ohlcv_data: OHLCV DataFrame.
            category: If set, only compute factors in this category.
            **override_params: Override params for all factors.

        Returns:
            DataFrame with one column per factor.
        """
        targets = self.get_factors_by_category(category) if category else self.list_factors()
        results: dict[str, pd.Series] = {}
        for meta in targets:
            try:
                results[meta.name] = self.compute(meta.name, ohlcv_data, **override_params)
            except Exception as e:
                logger.warning("Failed to compute factor %s: %s", meta.name, e)
                results[meta.name] = pd.Series(dtype=float, index=ohlcv_data.index)
        return pd.DataFrame(results)

    # ── IC History Persistence ───────────────────────────────

    def record_ic(
        self,
        factor_name: str,
        timestamp: str,
        ic_value: float,
        forward_period: int = 1,
        symbol: str = "",
    ) -> None:
        """Record an IC observation for a factor.

        Args:
            factor_name: Factor name.
            timestamp: ISO timestamp of the observation.
            ic_value: Computed IC value.
            forward_period: Forward return period used.
            symbol: Symbol this IC was computed on.
        """
        self._conn.execute(
            """INSERT INTO ic_history (factor_name, timestamp, ic_value, forward_period, symbol)
               VALUES (?, ?, ?, ?, ?)""",
            (factor_name, timestamp, ic_value, forward_period, symbol),
        )
        self._conn.commit()

    def get_ic_history(
        self,
        factor_name: str,
        limit: int = 1000,
    ) -> list[ICRecord]:
        """Retrieve IC history for a factor.

        Args:
            factor_name: Factor name.
            limit: Max records to return.

        Returns:
            List of ICRecord instances.
        """
        rows = self._conn.execute(
            """SELECT factor_name, timestamp, ic_value, forward_period, symbol
               FROM ic_history WHERE factor_name = ? ORDER BY timestamp DESC LIMIT ?""",
            (factor_name, limit),
        ).fetchall()
        return [
            ICRecord(
                factor_name=r["factor_name"],
                timestamp=r["timestamp"],
                ic_value=r["ic_value"],
                forward_period=r["forward_period"],
                symbol=r["symbol"],
            )
            for r in rows
        ]

    def get_all_ic_records(self, limit: int = 10000) -> list[ICRecord]:
        """Retrieve all IC records across all factors."""
        rows = self._conn.execute(
            """SELECT factor_name, timestamp, ic_value, forward_period, symbol
               FROM ic_history ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            ICRecord(
                factor_name=r["factor_name"],
                timestamp=r["timestamp"],
                ic_value=r["ic_value"],
                forward_period=r["forward_period"],
                symbol=r["symbol"],
            )
            for r in rows
        ]

    # ── Multiple Testing Correction (M-013) ─────────────────

    def compute_deflated_sharpe_ratio(
        self,
        observed_sharpe: float,
        n_trials: int,
        n_observations: int,
        skewness: float = 0.0,
        kurtosis: float = 3.0,
    ) -> dict[str, Any]:
        """Compute the Deflated Sharpe Ratio (DSR) for multiple testing.

        The DSR adjusts an observed Sharpe ratio for the number of
        strategies/trials tested, using the approach of Bailey & López de Prado (2014).

        Args:
            observed_sharpe: The observed annualized Sharpe ratio.
            n_trials: Total number of strategies/trials tested.
            n_observations: Number of return observations.
            skewness: Return distribution skewness (default 0 = normal).
            kurtosis: Return distribution kurtosis (default 3 = normal).

        Returns:
            Dict with deflated_sharpe, p_value, is_significant, and expected_max_sharpe.
        """
        import math

        if n_trials <= 0 or n_observations <= 0:
            return {
                "deflated_sharpe": 0.0,
                "p_value": 1.0,
                "is_significant": False,
                "expected_max_sharpe": 0.0,
                "n_trials": n_trials,
            }

        # Expected maximum Sharpe ratio under null (no skill)
        # E[max(SR)] ≈ sqrt(2 * ln(n_trials)) * (1 - γ/ln(n_trials)) + γ/sqrt(2*ln(n_trials))
        # where γ = Euler-Mascheroni constant ≈ 0.5772
        euler_gamma = 0.5772156649
        log_n = math.log(n_trials) if n_trials > 1 else 1.0
        expected_max_sharpe = (
            math.sqrt(2 * log_n) * (1 - euler_gamma / log_n)
            + euler_gamma / math.sqrt(2 * log_n)
        )

        # Standard error of Sharpe ratio (with skewness/kurtosis correction)
        # SE(SR) = sqrt((1 + 0.5*SR² - γ₁*SR + (γ₂-3)/4*SR²) / (T-1))
        sr = observed_sharpe
        se_numerator = 1.0 + 0.5 * sr**2 - skewness * sr + (kurtosis - 3) / 4 * sr**2
        se_sr = math.sqrt(max(0, se_numerator) / max(1, n_observations - 1))

        if se_sr <= 0:
            return {
                "deflated_sharpe": 0.0,
                "p_value": 1.0,
                "is_significant": False,
                "expected_max_sharpe": round(expected_max_sharpe, 4),
                "n_trials": n_trials,
            }

        # Deflated Sharpe Ratio: PSR(expected_max_sharpe)
        # DSR = P[SR* > expected_max_sharpe | observed_sr, se_sr]
        z_score = (sr - expected_max_sharpe) / se_sr

        # Use normal CDF approximation
        # Φ(z) = 0.5 * (1 + erf(z / sqrt(2)))
        def _norm_cdf(z: float) -> float:
            return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))

        p_value = 1.0 - _norm_cdf(z_score)
        is_significant = p_value < 0.05  # 95% confidence

        return {
            "deflated_sharpe": round(observed_sharpe, 4),
            "p_value": round(p_value, 6),
            "is_significant": is_significant,
            "expected_max_sharpe": round(expected_max_sharpe, 4),
            "z_score": round(z_score, 4),
            "n_trials": n_trials,
            "n_observations": n_observations,
        }

    def apply_fdr_correction(
        self,
        p_values: dict[str, float],
        alpha: float = 0.05,
        method: str = "bh",
    ) -> dict[str, dict[str, Any]]:
        """Apply False Discovery Rate (FDR) correction for multiple factor testing.

        Implements the Benjamini-Hochberg (BH) procedure to control
        the false discovery rate when testing multiple factors.

        Args:
            p_values: Dict mapping factor name to raw p-value.
            alpha: Significance level (default 0.05).
            method: Correction method — 'bh' (Benjamini-Hochberg) or 'bonferroni'.

        Returns:
            Dict mapping factor name to result dict with:
                - raw_p: Original p-value
                - adjusted_p: FDR-adjusted p-value
                - significant: Whether factor passes FDR threshold
        """
        if not p_values:
            return {}

        n = len(p_values)
        results: dict[str, dict[str, Any]] = {}

        if method == "bonferroni":
            # Bonferroni: multiply each p-value by n
            for name, p in p_values.items():
                adjusted_p = min(1.0, p * n)
                results[name] = {
                    "raw_p": round(p, 6),
                    "adjusted_p": round(adjusted_p, 6),
                    "significant": adjusted_p < alpha,
                }
            return results

        # Benjamini-Hochberg procedure
        # 1. Sort p-values in ascending order
        sorted_items = sorted(p_values.items(), key=lambda x: x[1])

        # 2. Compute adjusted p-values
        adjusted: dict[str, float] = {}
        prev_adjusted = 1.0

        for i, (name, p) in enumerate(reversed(sorted_items)):
            rank = n - i  # Rank from largest to smallest
            # BH adjusted p = p * n / rank, bounded by 1.0 and monotonic
            raw_adjusted = min(1.0, p * n / rank)
            adjusted[name] = min(prev_adjusted, raw_adjusted)
            prev_adjusted = adjusted[name]

        # 3. Build results
        for name, p in p_values.items():
            adj_p = adjusted.get(name, 1.0)
            results[name] = {
                "raw_p": round(p, 6),
                "adjusted_p": round(adj_p, 6),
                "significant": adj_p < alpha,
            }

        return results

    def batch_factor_significance(
        self,
        ohlcv_data: pd.DataFrame,
        forward_returns: pd.Series,
        alpha: float = 0.05,
    ) -> dict[str, Any]:
        """Test all factors for significance with multiple-testing correction.

        Computes IC for each factor, derives p-values, and applies
        FDR correction to identify genuinely significant factors.

        Args:
            ohlcv_data: OHLCV DataFrame.
            forward_returns: Forward return series (same index as ohlcv_data).
            alpha: Significance level for FDR correction.

        Returns:
            Dict with factor rankings, FDR results, and significant factors.
        """
        import scipy.stats as stats

        p_values: dict[str, float] = {}
        ic_values: dict[str, float] = {}

        for meta in self.list_factors():
            try:
                factor_vals = self.compute(meta.name, ohlcv_data)
                # Align indices
                common_idx = factor_vals.dropna().index.intersection(
                    forward_returns.dropna().index
                )
                if len(common_idx) < 20:
                    continue

                f = factor_vals.loc[common_idx].values
                r = forward_returns.loc[common_idx].values

                # Pearson correlation = IC
                ic, p_val = stats.pearsonr(f, r)
                ic_values[meta.name] = float(ic)
                p_values[meta.name] = float(p_val)

            except Exception as e:
                logger.debug("Factor %s significance test failed: %s", meta.name, e)

        if not p_values:
            return {"significant_factors": [], "all_factors": {}}

        # Apply FDR correction
        fdr_results = self.apply_fdr_correction(p_values, alpha=alpha, method="bh")

        # Also apply Bonferroni for conservative comparison
        bonf_results = self.apply_fdr_correction(p_values, alpha=alpha, method="bonferroni")

        significant = [
            name for name, res in fdr_results.items()
            if res["significant"]
        ]

        return {
            "significant_factors": significant,
            "n_tested": len(p_values),
            "fdr_correction": fdr_results,
            "bonferroni_correction": bonf_results,
            "ic_values": {k: round(v, 4) for k, v in ic_values.items()},
        }
