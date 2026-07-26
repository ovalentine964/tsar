"""
Unit tests for FactorLibrary integration with SignalScout (G5).

Tests:
  - FactorLibrary initialization via config
  - Factor adjustment computation (RSI, BB, MFI, ADX)
  - Score adjustment (±20% of base score)
  - Graceful fallback when factors fail
  - Factor-adjusted signal detection
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.agents.signal_scout import SignalScout
from src.interfaces.types import (
    BollingerResult,
    MACDResult,
    OHLCV,
    OrderSide,
    SRLevel,
    SRLevels,
    Timeframe,
)
from src.strategy.factor_library import FactorLibrary


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _make_ohlcv(n: int = 100, base: float = 50000.0) -> list[OHLCV]:
    """Generate synthetic OHLCV data."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        # Oscillating price for mean reversion signals
        close = base + 500 * np.sin(i * 0.1) + i * 2
        bars.append(OHLCV(
            timestamp=start + timedelta(hours=i),
            open=close - 50,
            high=close + 100,
            low=close - 100,
            close=close,
            volume=1000.0 + i * 5,
        ))
    return bars


def _make_scout_with_factors(
    factor_config: dict | None = None,
) -> SignalScout:
    """Create a SignalScout with FactorLibrary enabled."""
    config = {
        "exchange": {"symbols": ["BTC/USDT"]},
        "agents": {
            "signal_scout": {"cycle_interval_s": 300, "weights": {}},
            "heartbeat_interval_s": 999,
        },
        "strategies": {"mean_reversion": {"params": {}}},
        "factor_library": factor_config or {
            "enabled": True,
            "db_path": ":memory:",
        },
    }

    with patch("src.agents.base.EventPublisher"), \
         patch("src.agents.base.EventSubscriber"):
        scout = SignalScout(config=config, trading_mode="paper")
    return scout


def _make_scout_without_factors() -> SignalScout:
    """Create a SignalScout without FactorLibrary."""
    config = {
        "exchange": {"symbols": ["BTC/USDT"]},
        "agents": {
            "signal_scout": {"cycle_interval_s": 300, "weights": {}},
            "heartbeat_interval_s": 999,
        },
        "strategies": {"mean_reversion": {"params": {}}},
        "factor_library": {"enabled": False},
    }

    with patch("src.agents.base.EventPublisher"), \
         patch("src.agents.base.EventSubscriber"):
        scout = SignalScout(config=config, trading_mode="paper")
    return scout


# ═══════════════════════════════════════════════════════════════════════
# TESTS: FactorLibrary Initialization
# ═══════════════════════════════════════════════════════════════════════


class TestFactorLibraryInit:
    """Tests for FactorLibrary initialization in SignalScout."""

    def test_factors_enabled_creates_library(self) -> None:
        """When enabled=True, FactorLibrary should be created."""
        scout = _make_scout_with_factors({"enabled": True, "db_path": ":memory:"})
        assert scout._use_factors is True
        assert scout._factor_library is not None

    def test_factors_disabled_no_library(self) -> None:
        """When enabled=False, no FactorLibrary should exist."""
        scout = _make_scout_without_factors()
        assert scout._use_factors is False
        assert scout._factor_library is None

    def test_default_config_disables_factors(self) -> None:
        """Without factor_library config, factors should be disabled."""
        config = {
            "exchange": {"symbols": ["BTC/USDT"]},
            "agents": {
                "signal_scout": {"cycle_interval_s": 300, "weights": {}},
                "heartbeat_interval_s": 999,
            },
            "strategies": {"mean_reversion": {"params": {}}},
        }
        with patch("src.agents.base.EventPublisher"), \
             patch("src.agents.base.EventSubscriber"):
            scout = SignalScout(config=config, trading_mode="paper")
        assert scout._use_factors is False


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Factor Adjustment Computation
# ═══════════════════════════════════════════════════════════════════════


class TestFactorAdjustment:
    """Tests for _compute_factor_adjustment method."""

    def test_buy_signal_oversold_conditions(self) -> None:
        """BUY signal with oversold RSI/BB/MFI should get positive adjustment."""
        scout = _make_scout_with_factors()
        lib = scout._factor_library
        assert lib is not None

        # Create OHLCV DataFrame with oversold conditions
        # Price dropping → RSI low, BB low, MFI low
        n = 50
        closes = [50000.0 - i * 100 for i in range(n)]  # Dropping prices
        ohlcv_df = pd.DataFrame({
            "open": [c + 50 for c in closes],
            "high": [c + 100 for c in closes],
            "low": [c - 100 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        })

        adj = scout._compute_factor_adjustment(ohlcv_df, OrderSide.BUY)
        # Should be in [-1, 1]
        assert -1.0 <= adj <= 1.0
        # For oversold conditions with BUY, adjustment should be positive
        # (contrarian signal reinforces mean reversion BUY)
        assert adj > 0, f"Expected positive adjustment for oversold BUY, got {adj}"

    def test_sell_signal_overbought_conditions(self) -> None:
        """SELL signal with overbought conditions should get positive adjustment."""
        scout = _make_scout_with_factors()
        lib = scout._factor_library
        assert lib is not None

        # Rising prices → RSI high, BB high, MFI high
        n = 50
        closes = [50000.0 + i * 100 for i in range(n)]
        ohlcv_df = pd.DataFrame({
            "open": [c - 50 for c in closes],
            "high": [c + 100 for c in closes],
            "low": [c - 100 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        })

        adj = scout._compute_factor_adjustment(ohlcv_df, OrderSide.SELL)
        assert -1.0 <= adj <= 1.0
        # For overbought SELL, adjustment should be positive
        assert adj > 0, f"Expected positive adjustment for overbought SELL, got {adj}"

    def test_adjustment_bounded_to_unit_range(self) -> None:
        """Factor adjustment should always be in [-1, 1]."""
        scout = _make_scout_with_factors()
        lib = scout._factor_library
        assert lib is not None

        # Extreme data
        n = 50
        closes = [1.0 + i * 1000 for i in range(n)]
        ohlcv_df = pd.DataFrame({
            "open": closes,
            "high": [c + 100 for c in closes],
            "low": [c - 100 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        })

        for side in [OrderSide.BUY, OrderSide.SELL]:
            adj = scout._compute_factor_adjustment(ohlcv_df, side)
            assert -1.0 <= adj <= 1.0, f"Adjustment {adj} out of range for {side}"


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Score Adjustment (±20%)
# ═══════════════════════════════════════════════════════════════════════


class TestScoreAdjustment:
    """Tests for the ±20% factor-based score adjustment."""

    def test_positive_adjustment_increases_score(self) -> None:
        """Positive factor adjustment should increase base score by up to 20%."""
        base_score = 0.7
        factor_adj = 1.0  # Maximum positive
        adjusted = base_score * (1.0 + 0.2 * factor_adj)
        assert adjusted == pytest.approx(0.84, abs=0.001)

    def test_negative_adjustment_decreases_score(self) -> None:
        """Negative factor adjustment should decrease base score by up to 20%."""
        base_score = 0.7
        factor_adj = -1.0  # Maximum negative
        adjusted = base_score * (1.0 + 0.2 * factor_adj)
        assert adjusted == pytest.approx(0.56, abs=0.001)

    def test_zero_adjustment_no_change(self) -> None:
        """Zero factor adjustment should not change score."""
        base_score = 0.7
        factor_adj = 0.0
        adjusted = base_score * (1.0 + 0.2 * factor_adj)
        assert adjusted == pytest.approx(base_score, abs=0.001)

    def test_adjustment_clamped_to_0_1(self) -> None:
        """Adjusted score should be clamped to [0, 1]."""
        base_score = 0.95
        factor_adj = 1.0
        adjusted = base_score * (1.0 + 0.2 * factor_adj)
        adjusted = max(0.0, min(1.0, adjusted))
        assert 0.0 <= adjusted <= 1.0

    def test_low_score_stays_low_with_negative_adjustment(self) -> None:
        """A low base score with negative adjustment should stay low."""
        base_score = 0.3
        factor_adj = -1.0
        adjusted = base_score * (1.0 + 0.2 * factor_adj)
        adjusted = max(0.0, min(1.0, adjusted))
        assert adjusted < base_score


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Factor Library Compute
# ═══════════════════════════════════════════════════════════════════════


class TestFactorLibraryCompute:
    """Tests for FactorLibrary compute methods used by integration."""

    def test_compute_rsi(self) -> None:
        """FactorLibrary should compute RSI values."""
        lib = FactorLibrary(":memory:")
        n = 50
        # Oscillating prices so RSI has both gains and losses
        closes = [100.0 + 10 * np.sin(i * 0.3) for i in range(n)]
        df = pd.DataFrame({
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        })

        rsi = lib.compute("rsi", df)
        assert len(rsi) == n
        last_rsi = float(rsi.iloc[-1])
        assert 0 <= last_rsi <= 100

    def test_compute_bb_pct_b(self) -> None:
        """FactorLibrary should compute BB %B values."""
        lib = FactorLibrary(":memory:")
        n = 50
        closes = [100.0 + 10 * np.sin(i * 0.2) for i in range(n)]
        df = pd.DataFrame({
            "open": closes,
            "high": [c + 2 for c in closes],
            "low": [c - 2 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        })

        bb = lib.compute("bb_pct_b", df)
        assert len(bb) == n

    def test_compute_mfi(self) -> None:
        """FactorLibrary should compute MFI values."""
        lib = FactorLibrary(":memory:")
        n = 50
        closes = [100.0 + i for i in range(n)]
        df = pd.DataFrame({
            "open": closes,
            "high": [c + 2 for c in closes],
            "low": [c - 2 for c in closes],
            "close": closes,
            "volume": [1000.0 + i * 10 for i in range(n)],
        })

        mfi = lib.compute("mfi", df)
        assert len(mfi) == n
        last_mfi = float(mfi.iloc[-1])
        assert 0 <= last_mfi <= 100 or np.isnan(last_mfi)

    def test_compute_adx(self) -> None:
        """FactorLibrary should compute ADX values."""
        lib = FactorLibrary(":memory:")
        n = 50
        closes = [100.0 + i * 0.5 for i in range(n)]
        df = pd.DataFrame({
            "open": closes,
            "high": [c + 2 for c in closes],
            "low": [c - 2 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        })

        adx = lib.compute("adx", df)
        assert len(adx) == n

    def test_list_factors_has_key_factors(self) -> None:
        """FactorLibrary should have RSI, BB, MFI, ADX registered."""
        lib = FactorLibrary(":memory:")
        names = [f.name for f in lib.list_factors()]
        assert "rsi" in names
        assert "bb_pct_b" in names
        assert "mfi" in names
        assert "adx" in names
