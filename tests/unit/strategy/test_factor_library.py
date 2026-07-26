"""
Unit tests for Factor Library — Phase 4.

Tests:
  - Factor registration and retrieval
  - Each of 28 factors computes without errors on mock OHLCV data
  - Factor benchmarking (IC, IR computation)
  - Edge cases: insufficient data, NaN handling, custom factors
"""

from __future__ import annotations

import sqlite3
import tempfile
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.strategy.factor_bench import FactorBenchmarker, FactorBenchmarkResult
from src.strategy.factor_library import FactorLibrary, FactorMeta
from src.strategy.factors import FACTOR_REGISTRY

TOTAL_BUILTIN_FACTORS = 28  # 9 momentum + 4 mean_reversion + 4 volatility + 4 volume + 4 trend + 3 pattern


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════


def make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame with realistic structure."""
    rng = np.random.RandomState(seed)
    base = 100.0
    returns = rng.normal(0.0005, 0.02, n)
    close = base * np.cumprod(1 + returns)
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    opn = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.uniform(1000, 50000, n)

    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """200-bar synthetic OHLCV data."""
    return make_ohlcv(200)


@pytest.fixture
def small_ohlcv_df() -> pd.DataFrame:
    """10-bar OHLCV (insufficient for most factors)."""
    return make_ohlcv(10)


@pytest.fixture
def library() -> FactorLibrary:
    """In-memory FactorLibrary."""
    return FactorLibrary(":memory:")


@pytest.fixture
def benchmarker(library: FactorLibrary) -> FactorBenchmarker:
    """FactorBenchmarker with in-memory library."""
    return FactorBenchmarker(library)


# ═══════════════════════════════════════════════════════════════════════
# FACTOR REGISTRATION & RETRIEVAL
# ═══════════════════════════════════════════════════════════════════════


class TestFactorRegistration:
    """Tests for FactorLibrary registration and retrieval."""

    def test_builtin_factors_loaded(self, library: FactorLibrary) -> None:
        """All built-in factors should be registered on init."""
        factors = library.list_factors()
        assert len(factors) == TOTAL_BUILTIN_FACTORS

    def test_all_categories_present(self, library: FactorLibrary) -> None:
        """All 6 categories should have factors."""
        counts = library.get_categories()
        assert counts["momentum"] == 9
        assert counts["mean_reversion"] == 4
        assert counts["volatility"] == 4
        assert counts["volume"] == 4
        assert counts["trend"] == 4
        assert counts["pattern"] == 3

    def test_get_factors_by_category(self, library: FactorLibrary) -> None:
        """get_factors_by_category returns correct factors."""
        momentum = library.get_factors_by_category("momentum")
        names = {f.name for f in momentum}
        assert "rsi" in names
        assert "macd" in names
        assert "cci" in names
        assert "mfi" in names

    def test_get_factors_by_universe(self, library: FactorLibrary) -> None:
        """get_factors_by_universe filters correctly."""
        crypto_factors = library.get_factors_by_universe("crypto")
        assert len(crypto_factors) == TOTAL_BUILTIN_FACTORS

        commodity_factors = library.get_factors_by_universe("commodity")
        assert len(commodity_factors) == 1
        assert commodity_factors[0].name == "cci"

    def test_get_factor_meta(self, library: FactorLibrary) -> None:
        """get_factor_meta returns correct metadata."""
        meta = library.get_factor_meta("rsi")
        assert meta is not None
        assert meta.name == "rsi"
        assert meta.category == "momentum"
        assert meta.default_params["period"] == 14
        assert not meta.custom

    def test_get_factor_meta_nonexistent(self, library: FactorLibrary) -> None:
        """get_factor_meta returns None for unknown factors."""
        assert library.get_factor_meta("nonexistent") is None

    def test_register_custom_factor(self, library: FactorLibrary) -> None:
        """Custom factors can be registered and retrieved."""

        def my_factor(df: pd.DataFrame, **kwargs: object) -> pd.Series:
            return df["close"].pct_change()

        library.register(
            name="custom_momentum",
            func=my_factor,
            category="momentum",
            description="Custom test factor",
        )
        meta = library.get_factor_meta("custom_momentum")
        assert meta is not None
        assert meta.custom is True
        assert meta.category == "momentum"
        assert len(library.list_factors()) == TOTAL_BUILTIN_FACTORS + 1

    def test_register_invalid_category(self, library: FactorLibrary) -> None:
        """Registering with invalid category raises ValueError."""
        with pytest.raises(ValueError, match="Invalid category"):
            library.register(
                name="bad",
                func=lambda df: df["close"],
                category="invalid_category",
            )

    def test_custom_factor_persists_in_db(self) -> None:
        """Custom factor metadata persists to SQLite."""

        db_path = os.path.join(tempfile.mkdtemp(), "test.db")

        def my_func(df: pd.DataFrame, **kwargs: object) -> pd.Series:
            return df["close"]

        lib1 = FactorLibrary(db_path)
        lib1.register("persist_test", my_func, "trend", description="Persist test")
        lib1.close()

        # Verify raw SQLite row exists
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT name, custom FROM factors WHERE name = 'persist_test'").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "persist_test"
        assert row[1] == 1  # custom=True


# ═══════════════════════════════════════════════════════════════════════
# FACTOR COMPUTATION (each factor)
# ═══════════════════════════════════════════════════════════════════════


class TestFactorComputation:
    """Each factor computes without errors and returns a valid Series."""

    ALL_FACTORS = [
        "rsi", "macd", "stochastic_k", "stochastic_d", "williams_r",
        "roc", "momentum", "cci", "mfi",
        "bb_pct_b", "zscore", "vwap_distance", "keltner_position",
        "atr_normalized", "bb_bandwidth", "historical_volatility", "atr_ratio",
        "obv_slope", "volume_roc", "accumulation_distribution", "chaikin_money_flow",
        "adx", "aroon_oscillator", "ichimoku", "supertrend",
        "engulfing", "pin_bar", "inside_bar",
    ]

    @pytest.mark.parametrize("factor_name", ALL_FACTORS)
    def test_factor_computes(
        self, factor_name: str, library: FactorLibrary, ohlcv_df: pd.DataFrame
    ) -> None:
        """Each factor returns a Series with same index as input."""
        result = library.compute(factor_name, ohlcv_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)
        assert result.index.equals(ohlcv_df.index)

    @pytest.mark.parametrize("factor_name", ALL_FACTORS)
    def test_factor_no_all_nan(
        self, factor_name: str, library: FactorLibrary, ohlcv_df: pd.DataFrame
    ) -> None:
        """Each factor should produce some non-NaN values on 200 bars."""
        result = library.compute(factor_name, ohlcv_df)
        non_nan = result.dropna()
        assert len(non_nan) > 0, f"Factor {factor_name} returned all NaN"

    def test_rsi_range(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """RSI should be in [0, 100]."""
        rsi = library.compute("rsi", ohlcv_df).dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all()

    def test_williams_r_range(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """Williams %R should be in [-100, 0]."""
        wr = library.compute("williams_r", ohlcv_df).dropna()
        assert (wr >= -100).all() and (wr <= 0).all()

    def test_stochastic_k_range(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """Stochastic %K should be in [0, 100]."""
        k = library.compute("stochastic_k", ohlcv_df).dropna()
        assert (k >= 0).all() and (k <= 100).all()

    def test_supertrend_direction(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """Supertrend should return only +1 or -1."""
        st = library.compute("supertrend", ohlcv_df).dropna()
        assert set(st.unique()).issubset({1.0, -1.0})

    def test_engulfing_values(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """Engulfing should return only -1, 0, or 1."""
        eng = library.compute("engulfing", ohlcv_df).dropna()
        assert set(eng.unique()).issubset({-1.0, 0.0, 1.0})

    def test_inside_bar_values(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """Inside bar should return only 0 or 1."""
        ib = library.compute("inside_bar", ohlcv_df).dropna()
        assert set(ib.unique()).issubset({0.0, 1.0})

    def test_mfi_range(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """MFI should be in [0, 100]."""
        mfi = library.compute("mfi", ohlcv_df).dropna()
        assert (mfi >= 0).all() and (mfi <= 100).all()

    def test_compute_with_param_override(
        self, library: FactorLibrary, ohlcv_df: pd.DataFrame
    ) -> None:
        """Parameters can be overridden at compute time."""
        rsi_14 = library.compute("rsi", ohlcv_df, period=14)
        rsi_7 = library.compute("rsi", ohlcv_df, period=7)
        assert not rsi_14.dropna().equals(rsi_7.dropna())

    def test_compute_unknown_factor(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """Computing unknown factor raises KeyError."""
        with pytest.raises(KeyError, match="not registered"):
            library.compute("nonexistent", ohlcv_df)

    def test_compute_all(self, library: FactorLibrary, ohlcv_df: pd.DataFrame) -> None:
        """compute_all returns DataFrame with one column per factor."""
        result = library.compute_all(ohlcv_df)
        assert isinstance(result, pd.DataFrame)
        assert len(result.columns) == TOTAL_BUILTIN_FACTORS

    def test_compute_all_category(
        self, library: FactorLibrary, ohlcv_df: pd.DataFrame
    ) -> None:
        """compute_all with category filter returns only that category."""
        result = library.compute_all(ohlcv_df, category="momentum")
        assert len(result.columns) == 9


# ═══════════════════════════════════════════════════════════════════════
# FACTOR BENCHMARKING
# ═══════════════════════════════════════════════════════════════════════


class TestFactorBenchmarking:
    """Tests for IC, IR, and benchmark result computation."""

    def test_run_returns_result(
        self, benchmarker: FactorBenchmarker, ohlcv_df: pd.DataFrame
    ) -> None:
        """Benchmarker.run returns a FactorBenchmarkResult."""
        result = benchmarker.run(ohlcv_df)
        assert isinstance(result, FactorBenchmarkResult)
        assert result.n_factors > 0
        assert result.n_observations == 200

    def test_result_ranked_by_ir(
        self, benchmarker: FactorBenchmarker, ohlcv_df: pd.DataFrame
    ) -> None:
        """Rankings should be sorted by |IR| descending."""
        result = benchmarker.run(ohlcv_df)
        for i in range(len(result.rankings) - 1):
            assert abs(result.rankings[i].ir) >= abs(result.rankings[i + 1].ir)

    def test_factor_score_fields(
        self, benchmarker: FactorBenchmarker, ohlcv_df: pd.DataFrame
    ) -> None:
        """Each FactorScore has all required fields."""
        result = benchmarker.run(ohlcv_df)
        for score in result.rankings:
            assert score.factor_name
            assert score.category
            assert isinstance(score.ic_mean, float)
            assert isinstance(score.ic_std, float)
            assert isinstance(score.ir, float)
            assert 0.0 <= score.ic_positive_ratio <= 1.0
            assert score.forward_period == 1
            assert score.n_observations > 0

    def test_benchmark_with_forward_periods(
        self, benchmarker: FactorBenchmarker, ohlcv_df: pd.DataFrame
    ) -> None:
        """Benchmark supports different forward periods."""
        result = benchmarker.run(ohlcv_df, forward_periods=[5])
        assert result.forward_period == 5
        for score in result.rankings:
            assert score.forward_period == 5

    def test_benchmark_category_filter(
        self, benchmarker: FactorBenchmarker, ohlcv_df: pd.DataFrame
    ) -> None:
        """Benchmark with category filter only returns that category."""
        result = benchmarker.run(ohlcv_df, category="volatility")
        for score in result.rankings:
            assert score.category == "volatility"

    def test_benchmark_records_ic_to_library(
        self, benchmarker: FactorBenchmarker,
        library: FactorLibrary,
        ohlcv_df: pd.DataFrame,
    ) -> None:
        """Benchmarker persists IC records to the library database."""
        benchmarker.run(ohlcv_df)
        records = library.get_all_ic_records()
        assert len(records) > 0
        factor_names = {r.factor_name for r in records}
        assert len(factor_names) > 0

    def test_compute_single_ic(
        self, benchmarker: FactorBenchmarker, ohlcv_df: pd.DataFrame
    ) -> None:
        """compute_single_ic returns a float IC value."""
        ic = benchmarker.compute_single_ic("rsi", ohlcv_df, forward_period=1)
        assert isinstance(ic, float)
        assert -1.0 <= ic <= 1.0

    def test_compute_rolling_ic(
        self, benchmarker: FactorBenchmarker, ohlcv_df: pd.DataFrame
    ) -> None:
        """compute_rolling_ic returns a Series of IC values."""
        rolling = benchmarker.compute_rolling_ic(
            "rsi", ohlcv_df, forward_period=1, window=50
        )
        assert isinstance(rolling, pd.Series)
        assert len(rolling) > 0

    def test_rolling_window_decay(
        self, benchmarker: FactorBenchmarker, ohlcv_df: pd.DataFrame
    ) -> None:
        """Rolling window parameter produces decay data."""
        result = benchmarker.run(ohlcv_df, rolling_window=50)
        has_decay = any(len(v) > 0 for v in result.decay.values())
        assert has_decay


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases: insufficient data, NaN handling, boundary conditions."""

    def test_insufficient_data_skips_factor(
        self, benchmarker: FactorBenchmarker, small_ohlcv_df: pd.DataFrame
    ) -> None:
        """Factors with insufficient data are skipped, not crashed."""
        result = benchmarker.run(small_ohlcv_df, min_observations=20)
        assert result.n_factors < TOTAL_BUILTIN_FACTORS

    def test_compute_with_nan_ohlcv(self, library: FactorLibrary) -> None:
        """Factors handle NaN values in input gracefully."""
        df = make_ohlcv(100)
        df.loc[df.index[50:55], "close"] = np.nan
        result = library.compute("rsi", df)
        assert isinstance(result, pd.Series)

    def test_compute_with_zero_volume(self, library: FactorLibrary) -> None:
        """Factors handle zero volume gracefully."""
        df = make_ohlcv(100)
        df["volume"] = 0.0
        for name in ["mfi", "obv_slope", "volume_roc", "chaikin_money_flow"]:
            result = library.compute(name, df)
            assert isinstance(result, pd.Series)

    def test_compute_with_constant_price(self, library: FactorLibrary) -> None:
        """Factors handle constant price (zero volatility)."""
        df = make_ohlcv(100)
        df["close"] = 100.0
        df["open"] = 100.0
        df["high"] = 100.0
        df["low"] = 100.0
        for name in FACTOR_REGISTRY:
            result = library.compute(name, df)
            assert isinstance(result, pd.Series)

    def test_ic_history_roundtrip(self, library: FactorLibrary) -> None:
        """IC records can be written and read back."""
        library.record_ic("rsi", "2024-01-01T00:00:00", 0.05, forward_period=1, symbol="BTC")
        library.record_ic("rsi", "2024-01-02T00:00:00", -0.02, forward_period=1, symbol="BTC")
        records = library.get_ic_history("rsi")
        assert len(records) == 2
        assert records[0].ic_value == -0.02
        assert records[1].ic_value == 0.05

    def test_empty_ohlcv(self, library: FactorLibrary) -> None:
        """Empty DataFrame doesn't crash computation."""
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        for name in ["rsi", "adx", "engulfing"]:
            result = library.compute(name, df)
            assert isinstance(result, pd.Series)
            assert len(result) == 0

    def test_very_short_data(self, library: FactorLibrary) -> None:
        """2-3 bars don't crash any factor."""
        df = make_ohlcv(3)
        for name in FACTOR_REGISTRY:
            result = library.compute(name, df)
            assert isinstance(result, pd.Series)
            assert len(result) == 3

    def test_library_close_reopen(self) -> None:
        """Library can be closed and reopened."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        lib = FactorLibrary(db_path)
        assert len(lib.list_factors()) == TOTAL_BUILTIN_FACTORS
        lib.close()

        lib2 = FactorLibrary(db_path)
        assert len(lib2.list_factors()) == TOTAL_BUILTIN_FACTORS
        lib2.close()
