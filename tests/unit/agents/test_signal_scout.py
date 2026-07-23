"""
Unit tests for SignalScout — signal generation and scoring.

Tests:
  - RSI oversold → BUY signal
  - RSI overbought → SELL signal
  - Scoring breakdown (RSI, S/R, volume, trend)
  - S/R proximity detection
  - Signal construction
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.agents.signal_scout import SignalScout, ScoringWeights
from src.interfaces.types import (
    BollingerResult,
    MACDResult,
    OHLCV,
    OrderSide,
    SRLevel,
    SRLevels,
    Signal,
)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _make_scout(config_overrides: dict | None = None) -> SignalScout:
    """Create a SignalScout with mocked publisher/subscriber."""
    config = {
        "exchange": {"symbols": ["BTC/USDT"]},
        "agents": {
            "signal_scout": {
                "cycle_interval_s": 300,
                "weights": {},
            },
            "heartbeat_interval_s": 999,
        },
        "strategies": {
            "mean_reversion": {"params": {}},
        },
    }
    if config_overrides:
        _deep_merge(config, config_overrides)

    with patch("src.agents.base.EventPublisher"), \
         patch("src.agents.base.EventSubscriber"):
        scout = SignalScout(config=config, trading_mode="paper")
    return scout


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _make_macd(
    hist_values: tuple[float, ...] = (-10.0, 5.0, 20.0),
) -> MACDResult:
    return MACDResult(
        macd_line=tuple([-100.0] * len(hist_values)),
        signal_line=tuple([-90.0] * len(hist_values)),
        histogram=hist_values,
    )


def _make_sr_levels(
    support_price: float = 49000.0,
    resistance_price: float = 51000.0,
    strength: float = 0.8,
) -> SRLevels:
    return SRLevels(
        supports=(SRLevel(price=support_price, strength=strength, level_type="support", touches=3),),
        resistances=(SRLevel(price=resistance_price, strength=strength, level_type="resistance", touches=3),),
    )


# ═══════════════════════════════════════════════════════════════════════
# SCORING WEIGHTS
# ═══════════════════════════════════════════════════════════════════════


class TestScoringWeights:
    """Verify scoring weight validation."""

    def test_default_weights_sum_to_one(self):
        w = ScoringWeights()
        total = w.rsi + w.sr_proximity + w.volume + w.trend
        assert abs(total - 1.0) < 0.001

    def test_valid_weights_pass(self):
        w = ScoringWeights(rsi=0.5, sr_proximity=0.3, volume=0.1, trend=0.1)
        w.validate()  # Should not raise

    def test_invalid_weights_raise(self):
        w = ScoringWeights(rsi=0.5, sr_proximity=0.5, volume=0.5, trend=0.5)
        with pytest.raises(ValueError, match="sum to 1.0"):
            w.validate()


# ═══════════════════════════════════════════════════════════════════════
# SCORING LOGIC
# ═══════════════════════════════════════════════════════════════════════


class TestScoreSetup:
    """Test the _score_setup method directly."""

    def test_buy_oversold_rsi_high_score(self):
        scout = _make_scout()
        macd = _make_macd((-20.0, -10.0, 5.0))  # Turning up from negative
        sr = _make_sr_levels(support_price=48000.0)

        score, breakdown = scout._score_setup(
            rsi=15.0,
            current_price=48000.0,
            sr_levels=sr,
            volumes=[1000.0] * 20 + [2000.0],  # Above average
            macd=macd,
            ema_trend=[49000.0],
            side=OrderSide.BUY,
        )
        assert score > 0.5
        assert "rsi" in breakdown
        assert "sr_proximity" in breakdown
        assert "volume" in breakdown
        assert "trend" in breakdown

    def test_sell_overbought_rsi_high_score(self):
        scout = _make_scout()
        macd = _make_macd((20.0, 10.0, -5.0))  # Turning down from positive
        sr = _make_sr_levels(resistance_price=52000.0)

        score, breakdown = scout._score_setup(
            rsi=85.0,
            current_price=52000.0,
            sr_levels=sr,
            volumes=[1000.0] * 20 + [2000.0],
            macd=macd,
            ema_trend=[51000.0],
            side=OrderSide.SELL,
        )
        assert score > 0.5

    def test_neutral_rsi_low_score(self):
        """RSI near 50 should produce a low RSI component score."""
        scout = _make_scout()
        macd = _make_macd((0.0, 0.0, 0.0))
        sr = _make_sr_levels()

        score, breakdown = scout._score_setup(
            rsi=50.0,
            current_price=50000.0,
            sr_levels=sr,
            volumes=[1000.0] * 21,
            macd=macd,
            ema_trend=[50000.0],
            side=OrderSide.BUY,
        )
        # RSI component should be near 0 (RSI=50 is not oversold)
        assert breakdown["rsi"] < 0.1

    def test_rsi_score_range_buy(self):
        """RSI score for BUY: RSI 30→0 maps to 0→1."""
        scout = _make_scout()
        macd = _make_macd()
        sr = _make_sr_levels()

        _, bd_high = scout._score_setup(
            rsi=0.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd, ema_trend=[50000.0],
            side=OrderSide.BUY,
        )
        _, bd_low = scout._score_setup(
            rsi=30.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd, ema_trend=[50000.0],
            side=OrderSide.BUY,
        )
        assert bd_high["rsi"] > bd_low["rsi"]

    def test_rsi_score_range_sell(self):
        """RSI score for SELL: RSI 70→100 maps to 0→1."""
        scout = _make_scout()
        macd = _make_macd()
        sr = _make_sr_levels()

        _, bd_high = scout._score_setup(
            rsi=100.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd, ema_trend=[50000.0],
            side=OrderSide.SELL,
        )
        _, bd_low = scout._score_setup(
            rsi=70.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd, ema_trend=[50000.0],
            side=OrderSide.SELL,
        )
        assert bd_high["rsi"] > bd_low["rsi"]

    def test_sr_proximity_near_level(self):
        """Price near support should get high S/R score for BUY."""
        scout = _make_scout()
        macd = _make_macd()
        sr = _make_sr_levels(support_price=50000.0)

        _, breakdown = scout._score_setup(
            rsi=25.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd, ema_trend=[50000.0],
            side=OrderSide.BUY,
        )
        assert breakdown["sr_proximity"] > 0

    def test_sr_proximity_far_from_level(self):
        """Price far from any S/R level should get low S/R score."""
        scout = _make_scout()
        macd = _make_macd()
        sr = _make_sr_levels(support_price=40000.0, resistance_price=60000.0)

        _, breakdown = scout._score_setup(
            rsi=25.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd, ema_trend=[50000.0],
            side=OrderSide.BUY,
        )
        assert breakdown["sr_proximity"] == 0.0

    def test_volume_above_average_boosts_score(self):
        scout = _make_scout()
        macd = _make_macd()
        sr = _make_sr_levels()

        # Low volume
        _, bd_low = scout._score_setup(
            rsi=25.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd, ema_trend=[50000.0],
            side=OrderSide.BUY,
        )
        # High volume
        _, bd_high = scout._score_setup(
            rsi=25.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 20 + [5000.0], macd=macd, ema_trend=[50000.0],
            side=OrderSide.BUY,
        )
        assert bd_high["volume"] >= bd_low["volume"]

    def test_score_capped_at_one(self):
        """Total score should never exceed 1.0."""
        scout = _make_scout()
        macd = _make_macd((30.0, 20.0, 10.0))
        sr = _make_sr_levels(support_price=50000.0)

        score, _ = scout._score_setup(
            rsi=0.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 20 + [10000.0], macd=macd,
            ema_trend=[49000.0], side=OrderSide.BUY,
        )
        assert score <= 1.0

    def test_empty_sr_levels(self):
        """No S/R levels → S/R score is 0."""
        scout = _make_scout()
        macd = _make_macd()
        sr = SRLevels(supports=(), resistances=())

        _, breakdown = scout._score_setup(
            rsi=25.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd, ema_trend=[50000.0],
            side=OrderSide.BUY,
        )
        assert breakdown["sr_proximity"] == 0.0

    def test_short_volume_data(self):
        """Insufficient volume data → volume score is 0."""
        scout = _make_scout()
        macd = _make_macd()
        sr = _make_sr_levels()

        _, breakdown = scout._score_setup(
            rsi=25.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0, 2000.0],  # Only 2 data points
            macd=macd, ema_trend=[50000.0], side=OrderSide.BUY,
        )
        assert breakdown["volume"] == 0.0

    def test_macd_histogram_turning_up_for_buy(self):
        """MACD histogram turning up from negative → positive trend for BUY."""
        scout = _make_scout()
        sr = _make_sr_levels()

        macd_up = _make_macd((-20.0, -10.0, 5.0))
        _, bd_up = scout._score_setup(
            rsi=25.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd_up, ema_trend=[49000.0],
            side=OrderSide.BUY,
        )

        macd_flat = _make_macd((-10.0, -10.0, -10.0))
        _, bd_flat = scout._score_setup(
            rsi=25.0, current_price=50000.0, sr_levels=sr,
            volumes=[1000.0] * 21, macd=macd_flat, ema_trend=[49000.0],
            side=OrderSide.BUY,
        )
        assert bd_up["trend"] >= bd_flat["trend"]


# ═══════════════════════════════════════════════════════════════════════
# FIND NEAREST LEVEL
# ═══════════════════════════════════════════════════════════════════════


class TestFindNearestLevel:
    """Test the _find_nearest_level helper."""

    def test_finds_closest_level(self):
        scout = _make_scout()
        levels = (
            SRLevel(price=48000.0, strength=0.5, level_type="support"),
            SRLevel(price=49500.0, strength=0.8, level_type="support"),
            SRLevel(price=47000.0, strength=0.3, level_type="support"),
        )
        result = scout._find_nearest_level(50000.0, levels, "support")
        assert result is not None
        assert result.price == 49500.0

    def test_empty_levels_returns_none(self):
        scout = _make_scout()
        result = scout._find_nearest_level(50000.0, (), "support")
        assert result is None

    def test_single_level(self):
        scout = _make_scout()
        levels = (SRLevel(price=49000.0, strength=0.8, level_type="support"),)
        result = scout._find_nearest_level(50000.0, levels, "support")
        assert result is not None
        assert result.price == 49000.0


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL TO DICT
# ═══════════════════════════════════════════════════════════════════════


class TestSignalToDict:
    """Test signal serialization helper."""

    def test_serialization(self, fixed_ts):
        signal = Signal(
            signal_id="sig-001", symbol="BTC/USDT", side=OrderSide.BUY,
            score=0.75, entry_price=50000.0, stop_loss=49500.0,
            take_profit=51000.0, strategy="mean_reversion",
            reasoning="test reason", metadata={"rsi": 25.0},
            timestamp=fixed_ts,
        )
        d = SignalScout._signal_to_dict(signal)
        assert d["signal_id"] == "sig-001"
        assert d["side"] == "buy"
        assert d["score"] == 0.75
        assert d["metadata"]["rsi"] == 25.0
        assert d["timestamp"] is not None

    def test_serialization_no_timestamp(self):
        signal = Signal(
            signal_id="sig-002", symbol="BTC/USDT", side=OrderSide.SELL,
            score=0.8, entry_price=50000.0, stop_loss=50500.0,
            take_profit=49000.0, strategy="test",
        )
        d = SignalScout._signal_to_dict(signal)
        assert d["timestamp"] is None


# ═══════════════════════════════════════════════════════════════════════
# AGENT CONFIG
# ═══════════════════════════════════════════════════════════════════════


class TestAgentConfig:
    """Verify agent initialization from config."""

    def test_default_params(self):
        scout = _make_scout()
        assert scout._params["rsi_period"] == 14
        assert scout._params["rsi_oversold"] == 30
        assert scout._params["rsi_overbought"] == 70

    def test_custom_params(self):
        scout = _make_scout({
            "strategies": {"mean_reversion": {"params": {"rsi_period": 10}}},
        })
        assert scout._params["rsi_period"] == 10
        # Other defaults should remain
        assert scout._params["rsi_oversold"] == 30

    def test_agent_name(self):
        scout = _make_scout()
        assert scout.AGENT_NAME == "signal_scout"

    def test_agent_role(self):
        scout = _make_scout()
        assert scout.ROLE == "TRADE_PREVIEW"

    def test_symbols_from_config(self):
        scout = _make_scout({"exchange": {"symbols": ["ETH/USDT", "SOL/USDT"]}})
        assert scout._symbols == ["ETH/USDT", "SOL/USDT"]
