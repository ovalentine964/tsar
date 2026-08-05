"""
Tests for VMPM (Valentine Money Printing Machine) strategy components.

Run with: pytest tests/strategy/test_vmpm.py -v
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, time as dt_time, timedelta

import pytest

from src.strategy.vmpm.session_manager import (
    SessionManager,
    SessionInfo,
    Session,
    LiquidityLevel,
)
from src.strategy.vmpm.fundamental_analyzer import (
    FundamentalAnalyzer,
    FundamentalBias,
    BiasDirection,
    UpcomingEvent,
)
from src.strategy.vmpm.trend_detector import (
    TrendDetector,
    TrendState,
    TrendDirection,
    SwingType,
)
from src.strategy.vmpm.level_mapper import (
    LevelMapper,
    SRLevel,
    LevelType,
    LevelSide,
    MappedLevels,
    OrderBlock,
)
from src.strategy.vmpm.entry_pipeline import (
    EntryPipeline,
    PipelineResult,
    PipelineStage,
    CandlePattern,
)
from src.strategy.vmpm.strategy import VMPMStrategy
from src.strategy.genome import StrategyGenome


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def uptrend_closes() -> list[float]:
    """Generate synthetic uptrend data."""
    random.seed(42)
    return [100 + i * 0.5 + random.uniform(-0.3, 0.3) for i in range(250)]


@pytest.fixture
def downtrend_closes() -> list[float]:
    """Generate synthetic downtrend data."""
    random.seed(42)
    return [200 - i * 0.5 + random.uniform(-0.3, 0.3) for i in range(250)]


@pytest.fixture
def sample_ohlcv() -> list[dict[str, float]]:
    """Generate sample OHLCV data."""
    random.seed(42)
    bars = []
    price = 100.0
    for i in range(50):
        o = price
        h = price + random.uniform(0.5, 2.0)
        l = price - random.uniform(0.5, 2.0)
        c = price + random.uniform(-1.0, 1.0)
        v = random.uniform(1000, 5000)
        bars.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        price = c
    return bars


@pytest.fixture
def genome() -> StrategyGenome:
    """Create a test genome."""
    return StrategyGenome(
        name="vmpm",
        params={
            "ma_fast_period": 50,
            "ma_slow_period": 200,
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "sr_proximity_pct": 0.3,
            "retest_candles": 3,
            "atr_buffer_mult": 0.5,
            "min_rr_ratio": 2.0,
            "trailing_stop_atr_mult": 1.5,
            "min_signal_score": 0.70,
            "session_overlap_mult": 1.5,
            "volume_multiplier": 1.2,
        },
        mutable_params={},
        metadata={
            "sessions": {},
            "sr_levels": {},
            "technical": {
                "moving_averages": {"fast_period": 50, "slow_period": 200},
                "rsi": {"period": 14, "oversold": 30, "overbought": 70, "long_range": [30, 55], "short_range": [45, 70]},
                "atr": {"period": 14},
            },
            "entry_rules": {"min_signal_score": 0.70},
            "mutable_parameters": {
                "sr_proximity_pct": {"current": 0.3},
                "retest_candles": {"current": 3},
                "atr_buffer_mult": {"current": 0.5},
                "min_rr_ratio": {"current": 2.0},
                "trailing_stop_atr_mult": {"current": 1.5},
            },
        },
    )


# ═══════════════════════════════════════════════════════════════
# SessionManager Tests
# ═══════════════════════════════════════════════════════════════


class TestSessionManager:
    def test_london_session(self):
        """London session should be detected at 10:00 UTC."""
        mgr = SessionManager()
        now = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        info = mgr.get_session_info(now)
        assert Session.LONDON in info.active_sessions
        assert info.liquidity in (LiquidityLevel.HIGH, LiquidityLevel.PEAK)

    def test_london_ny_overlap(self):
        """London/NY overlap should be detected at 13:00 UTC."""
        mgr = SessionManager()
        now = datetime(2024, 1, 15, 13, 0, tzinfo=UTC)
        info = mgr.get_session_info(now)
        assert info.is_overlap
        assert info.overlap_name == "london_new_york"
        assert info.liquidity == LiquidityLevel.PEAK

    def test_sydney_session(self):
        """Sydney session at 23:00 UTC."""
        mgr = SessionManager()
        now = datetime(2024, 1, 15, 23, 0, tzinfo=UTC)
        info = mgr.get_session_info(now)
        assert Session.SYDNEY in info.active_sessions

    def test_session_score_pair_alignment(self):
        """EUR/USD should score higher during London session."""
        mgr = SessionManager()
        london_time = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        score = mgr.get_session_score("EUR/USD", london_time)
        assert score >= 1.0

    def test_low_liquidity_penalty(self):
        """Low liquidity sessions should reduce score."""
        mgr = SessionManager()
        # 21:30 UTC — after NY close (21:00), before Sydney (22:00)
        dead_time = datetime(2024, 1, 15, 21, 30, tzinfo=UTC)
        info = mgr.get_session_info(dead_time)
        score = mgr.get_session_score("EUR/USD", dead_time)
        # Dead zone should have lower score than peak hours
        peak_time = datetime(2024, 1, 15, 13, 0, tzinfo=UTC)
        peak_score = mgr.get_session_score("EUR/USD", peak_time)
        assert score < peak_score


# ═══════════════════════════════════════════════════════════════
# TrendDetector Tests
# ═══════════════════════════════════════════════════════════════


class TestTrendDetector:
    def test_uptrend_detection(self, uptrend_closes):
        """Uptrend data should be detected as bullish."""
        td = TrendDetector()
        state = td.detect(uptrend_closes, uptrend_closes[-100:], uptrend_closes[-60:])
        bullish_count = sum(1 for tf in [state.d1, state.h4, state.h1]
                           if tf.direction == TrendDirection.BULLISH)
        assert bullish_count >= 1

    def test_downtrend_detection(self, downtrend_closes):
        """Downtrend data should be detected as bearish."""
        td = TrendDetector()
        state = td.detect(downtrend_closes, downtrend_closes[-100:], downtrend_closes[-60:])
        bearish_count = sum(1 for tf in [state.d1, state.h4, state.h1]
                           if tf.direction == TrendDirection.BEARISH)
        assert bearish_count >= 1

    def test_insufficient_data(self):
        """Insufficient data should return neutral."""
        td = TrendDetector()
        short_data = [100.0] * 10
        state = td.detect(short_data, short_data, short_data)
        assert state.direction == TrendDirection.NEUTRAL

    def test_swing_detection(self, uptrend_closes):
        """Swing points should be detected."""
        td = TrendDetector()
        state = td.detect(uptrend_closes, uptrend_closes[-100:], uptrend_closes[-60:])
        assert len(state.d1.swing_points) > 0 or state.d1.structure == "insufficient"


# ═══════════════════════════════════════════════════════════════
# LevelMapper Tests
# ═══════════════════════════════════════════════════════════════


class TestLevelMapper:
    def test_asian_levels(self):
        """Asian high/low should map to S/R levels."""
        lm = LevelMapper()
        levels = lm.map_levels(
            current_price=1.0850,
            asian_high=1.0880,
            asian_low=1.0820,
        )
        assert levels.asian_high == 1.0880
        assert levels.asian_low == 1.0820
        assert len(levels.levels) >= 2

    def test_daily_levels(self, sample_ohlcv):
        """Daily OHLCV should produce daily S/R levels."""
        lm = LevelMapper()
        levels = lm.map_levels(
            current_price=sample_ohlcv[-1]["close"],
            d1_ohlcv=sample_ohlcv,
        )
        daily_levels = [l for l in levels.levels if l.timeframe == "D1"]
        assert len(daily_levels) >= 2

    def test_near_level_check(self):
        """is_near_level should detect proximity."""
        lm = LevelMapper({"sr_levels": {}, "mutable_parameters": {"sr_proximity_pct": {"current": 0.5}}})
        levels = (
            SRLevel(1.0850, LevelType.DAILY_HIGH, LevelSide.RESISTANCE, 0.8, "test", "D1", 1, 0.1),
            SRLevel(1.0800, LevelType.DAILY_LOW, LevelSide.SUPPORT, 0.8, "test", "D1", 1, 0.4),
        )
        is_near, nearest = lm.is_near_level(1.0852, levels, 0.1)
        assert is_near
        assert nearest.price == 1.0850

    def test_level_scoring(self):
        """Level score should reflect strength and proximity."""
        lm = LevelMapper({"sr_levels": {}, "mutable_parameters": {"sr_proximity_pct": {"current": 0.3}}})
        level = SRLevel(1.0850, LevelType.ORDER_BLOCK, LevelSide.SUPPORT, 0.9, "test", "H4", 3, 0.05)
        score = lm.get_level_score(1.0852, level)
        assert score > 0.5


# ═══════════════════════════════════════════════════════════════
# EntryPipeline Tests
# ═══════════════════════════════════════════════════════════════


class TestEntryPipeline:
    def _make_bias(self, news_clear=True, direction=BiasDirection.BULLISH):
        return FundamentalBias(
            direction=direction,
            confidence=0.7,
            news_clear=news_clear,
            upcoming_events=(),
            blackout_active=not news_clear,
            blackout_reason="test event" if not news_clear else None,
            event_risk_score=0.0 if news_clear else 0.8,
            macro_alignment=0.7 if direction == BiasDirection.BULLISH else 0.3,
            reasoning="test",
        )

    def _make_trend(self, direction=TrendDirection.BULLISH, aligned=True):
        from src.strategy.vmpm.trend_detector import TimeframeTrend
        tf = TimeframeTrend(
            timeframe="D1", direction=direction, ma_fast=1.09, ma_slow=1.08,
            ma_spread_pct=0.9, ma_slope=0.1, price_vs_ma="above_fast",
            swing_points=(), structure="hh_hl" if direction == TrendDirection.BULLISH else "lh_ll",
            strength=0.8,
        )
        return TrendState(
            direction=direction, aligned=aligned, strength=0.8,
            d1=tf, h4=tf, h1=tf, confluence_score=0.8,
            reasoning="test",
        )

    def _make_levels(self, price=1.0850):
        return MappedLevels(
            levels=(
                SRLevel(price - 0.001, LevelType.DAILY_LOW, LevelSide.SUPPORT, 0.8, "test", "D1", 2, 0.1),
            ),
            order_blocks=(),
            supports=(
                SRLevel(price - 0.001, LevelType.DAILY_LOW, LevelSide.SUPPORT, 0.8, "test", "D1", 2, 0.1),
            ),
            resistances=(),
            nearest_support=SRLevel(price - 0.001, LevelType.DAILY_LOW, LevelSide.SUPPORT, 0.8, "test", "D1", 2, 0.1),
            nearest_resistance=None,
            asian_high=price + 0.003,
            asian_low=price - 0.003,
            daily_open=price,
        )

    def _make_ohlcv(self, price=1.0850, bullish=True):
        bars = []
        for i in range(10):
            if bullish:
                o = price - 0.001 + i * 0.0001
                c = price + 0.001 + i * 0.0001
            else:
                o = price + 0.001 - i * 0.0001
                c = price - 0.001 - i * 0.0001
            bars.append({
                "open": o,
                "high": max(o, c) + 0.0005,
                "low": min(o, c) - 0.0005,
                "close": c,
                "volume": 1000,
            })
        return bars

    def test_news_gate_blocks(self):
        """Pipeline should block when news blackout is active."""
        pipeline = EntryPipeline()
        bias = self._make_bias(news_clear=False)
        trend = self._make_trend()
        levels = self._make_levels()

        result = pipeline.evaluate(
            current_price=1.0850,
            fundamental_bias=bias,
            trend_state=trend,
            mapped_levels=levels,
            ohlcv=self._make_ohlcv(),
            rsi=45.0,
            atr=0.0020,
        )
        assert not result.passed
        assert any(s.stage == PipelineStage.NEWS_GATE and not s.passed for s in result.stages)

    def test_neutral_trend_blocks(self):
        """Pipeline should block when trend is neutral."""
        pipeline = EntryPipeline()
        bias = self._make_bias()
        trend = self._make_trend(direction=TrendDirection.NEUTRAL)
        levels = self._make_levels()

        result = pipeline.evaluate(
            current_price=1.0850,
            fundamental_bias=bias,
            trend_state=trend,
            mapped_levels=levels,
            ohlcv=self._make_ohlcv(),
            rsi=45.0,
            atr=0.0020,
        )
        assert not result.passed

    def test_pipeline_returns_result(self):
        """Pipeline should return a PipelineResult."""
        pipeline = EntryPipeline({
            "entry_rules": {"min_signal_score": 0.50},
            "technical": {
                "rsi": {"period": 14, "oversold": 30, "overbought": 70, "long_range": [30, 55], "short_range": [45, 70]},
            },
            "mutable_parameters": {
                "sr_proximity_pct": {"current": 1.0},
                "retest_candles": {"current": 3},
                "atr_buffer_mult": {"current": 0.5},
                "min_rr_ratio": {"current": 2.0},
                "trailing_stop_atr_mult": {"current": 1.5},
            },
        })
        bias = self._make_bias()
        trend = self._make_trend()
        levels = self._make_levels(price=1.0850)
        ohlcv = self._make_ohlcv(price=1.0850, bullish=True)

        result = pipeline.evaluate(
            current_price=1.0849,
            fundamental_bias=bias,
            trend_state=trend,
            mapped_levels=levels,
            ohlcv=ohlcv,
            rsi=42.0,
            atr=0.0020,
            session_score=1.5,
        )
        assert isinstance(result, PipelineResult)
        assert result.side in ("buy", "sell", "none")


# ═══════════════════════════════════════════════════════════════
# VMPMStrategy Tests
# ═══════════════════════════════════════════════════════════════


class TestVMPMStrategy:
    def test_strategy_name(self, genome):
        """Strategy should have correct name."""
        strat = VMPMStrategy(genome=genome)
        assert strat.NAME == "vmpm"
        assert strat.VERSION == "1.0.0"

    def test_risk_params(self, genome):
        """Risk params should be properly configured."""
        strat = VMPMStrategy(genome=genome)
        params = strat.get_risk_params()
        assert params["risk_per_trade_pct"] == 0.015
        assert params["min_score"] == 0.70
        assert params["max_position_pct"] == 0.10
        assert params["session_aware_sizing"] is True

    def test_check_entry_insufficient_data(self, genome):
        """Should return None with insufficient data."""
        strat = VMPMStrategy(genome=genome)
        result = strat.check_entry({"close": 100, "atr": 1.0})
        assert result is None

    def test_check_entry_with_full_data(self, genome):
        """Should process full data without errors."""
        strat = VMPMStrategy(genome=genome)
        random.seed(42)
        closes = [100 + i * 0.5 + random.uniform(-0.3, 0.3) for i in range(250)]
        ohlcv = [
            {"open": p - 0.1, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 1000}
            for p in closes
        ]

        result = strat.check_entry({
            "symbol": "EUR/USD",
            "close": closes[-1],
            "atr": 0.5,
            "rsi": 45.0,
            "volume_ratio": 1.3,
            "d1_closes": closes,
            "h4_closes": closes[-100:],
            "h1_closes": closes[-60:],
            "d1_ohlcv": ohlcv,
            "h4_ohlcv": ohlcv[-100:],
            "h1_ohlcv": ohlcv[-60:],
            "asian_high": closes[-1] + 1.0,
            "asian_low": closes[-1] - 1.0,
        })
        assert result is None or isinstance(result, dict)

    def test_check_exit_long_stop_loss(self, genome):
        """Should trigger stop loss for long positions."""
        strat = VMPMStrategy(genome=genome)
        exit_signal = strat.check_exit(
            position={"side": "buy", "entry_price": 100.0, "stop_loss": 99.0},
            data={"close": 98.5, "atr": 0.5, "d1_closes": [100.0] * 250},
        )
        assert exit_signal is not None
        assert exit_signal["reason"] == "stop_loss"

    def test_check_exit_short_stop_loss(self, genome):
        """Should trigger stop loss for short positions."""
        strat = VMPMStrategy(genome=genome)
        exit_signal = strat.check_exit(
            position={"side": "sell", "entry_price": 100.0, "stop_loss": 101.0},
            data={"close": 101.5, "atr": 0.5, "d1_closes": [100.0] * 250},
        )
        assert exit_signal is not None
        assert exit_signal["reason"] == "stop_loss"

    def test_genome_from_yaml(self):
        """Should load genome from YAML config."""
        import os
        yaml_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "config", "strategies", "vmpm.yaml",
        )
        if os.path.exists(yaml_path):
            genome = StrategyGenome.from_yaml(yaml_path)
            assert genome.name == "vmpm"
            assert "ma_fast_period" in genome.params
            assert "min_signal_score" in genome.params


# ═══════════════════════════════════════════════════════════════
# FundamentalAnalyzer Tests
# ═══════════════════════════════════════════════════════════════


class TestFundamentalAnalyzer:
    def test_crypto_no_events(self):
        """Crypto pairs should have no traditional events."""
        analyzer = FundamentalAnalyzer()
        events = analyzer._generate_known_events("BTC", "USDT", datetime.now(UTC))
        assert events == []

    def test_currency_extraction(self):
        """Should extract currencies from pair string."""
        analyzer = FundamentalAnalyzer()
        assert analyzer._extract_currencies("EUR/USD") == ("EUR", "USD")
        assert analyzer._extract_currencies("BTC/USDT") == ("BTC", "USDT")

    def test_event_risk_score(self):
        """Event risk should decay with time."""
        analyzer = FundamentalAnalyzer()
        now = datetime.now(UTC)
        events = [
            UpcomingEvent(
                event="FOMC", category="monetary_policy", impact="critical",
                scheduled_time=now + timedelta(minutes=30),
                expected_value=None, previous_value=None, bias_hint=None,
            ),
        ]
        risk = analyzer._calculate_event_risk(events, now)
        assert risk > 0.5


# ═══════════════════════════════════════════════════════════════
# Integration Test
# ═══════════════════════════════════════════════════════════════


class TestVMPMIntegration:
    def test_full_pipeline_with_genome(self, genome):
        """Test the full VMPM pipeline from genome to signal."""
        strat = VMPMStrategy(genome=genome)

        random.seed(42)
        closes = [100 + i * 0.3 + random.uniform(-0.1, 0.1) for i in range(250)]
        ohlcv = [
            {"open": p - 0.05, "high": p + 0.3, "low": p - 0.3, "close": p, "volume": 2000}
            for p in closes
        ]

        data = {
            "symbol": "EUR/USD",
            "close": closes[-1],
            "atr": 0.3,
            "rsi": 42.0,
            "volume_ratio": 1.5,
            "d1_closes": closes,
            "h4_closes": closes[-100:],
            "h1_closes": closes[-60:],
            "d1_ohlcv": ohlcv,
            "h4_ohlcv": ohlcv[-100:],
            "h1_ohlcv": ohlcv[-60:],
            "asian_high": closes[-1] + 0.5,
            "asian_low": closes[-1] - 0.5,
            "macro_alignment": 0.6,
            "news_clear": True,
        }

        result = strat.check_entry(data)
        if result is not None:
            assert result["side"] in ("buy", "sell")
            assert 0 < result["score"] <= 1.0
            assert result["entry_price"] > 0
            assert result["stop_loss"] > 0
            assert result["take_profit"] > 0
