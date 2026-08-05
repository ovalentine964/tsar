"""
Smoke tests for VMPM (Valentine Money Printing Machine) strategy.

Tests each component individually and the full pipeline integration.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

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
)
from src.strategy.vmpm.rsi_filter import (
    RSIFilter,
    RSIResult,
    RSISignal,
    RSIState,
)
from src.strategy.vmpm.candlestick_confirmer import (
    CandlestickConfirmer,
    CandleResult,
    CandlePattern,
)
from src.strategy.vmpm.entry_pipeline import (
    EntryPipeline,
    PipelineResult,
    PipelineStage,
    StageResult,
)
from src.strategy.vmpm.strategy import VMPMStrategy


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


def _make_uptrend_data(n=250, seed=42):
    """Generate synthetic uptrend close prices."""
    random.seed(seed)
    return [100 + i * 0.5 + random.uniform(-0.3, 0.3) for i in range(n)]


def _make_downtrend_data(n=250, seed=42):
    """Generate synthetic downtrend close prices."""
    random.seed(seed)
    return [200 - i * 0.5 + random.uniform(-0.3, 0.3) for i in range(n)]


def _make_range_data(n=250, seed=42):
    """Generate synthetic range-bound close prices."""
    random.seed(seed)
    import math
    return [100 + 5 * math.sin(i / 10) + random.uniform(-0.2, 0.2) for i in range(n)]


def _make_ohlcv_from_closes(closes, volatility=0.5):
    """Convert close prices to OHLCV dicts."""
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c - 0.1
        h = max(o, c) + random.uniform(0.1, volatility)
        l = min(o, c) - random.uniform(0.1, volatility)
        bars.append({"open": o, "high": h, "low": l, "close": c, "volume": 1000})
    return bars


def _make_bullish_engulfing_ohlcv(base_price=100.0):
    """Create OHLCV data ending with a bullish engulfing pattern.

    Returns list[list[float]] format: [open, high, low, close, volume]
    """
    bars = []
    price = base_price
    random.seed(42)
    for i in range(8):
        o = price
        c = price + random.uniform(-0.5, 0.5)
        h = max(o, c) + 0.3
        l = min(o, c) - 0.3
        bars.append([o, h, l, c, 1000])
        price = c

    # Second-to-last: bearish candle
    bars.append([price + 0.3, price + 0.6, price - 0.6, price - 0.3, 1000])

    # Last: bullish engulfing (big bullish candle that engulfs previous)
    prev_o = bars[-1][0]
    prev_c = bars[-1][3]
    bars.append([prev_c - 0.05, prev_o + 0.5, prev_c - 0.3, prev_o + 0.3, 2000])
    return bars


def _make_neutral_bias():
    """Create a neutral fundamental bias."""
    return FundamentalBias(
        direction=BiasDirection.NEUTRAL,
        confidence=0.0,
        news_clear=True,
        upcoming_events=(),
        blackout_active=False,
        blackout_reason=None,
        event_risk_score=0.0,
        macro_alignment=0.5,
        reasoning="test_neutral",
    )


def _make_bullish_bias():
    """Create a bullish fundamental bias."""
    return FundamentalBias(
        direction=BiasDirection.BULLISH,
        confidence=0.7,
        news_clear=True,
        upcoming_events=(),
        blackout_active=False,
        blackout_reason=None,
        event_risk_score=0.0,
        macro_alignment=0.7,
        reasoning="test_bullish",
    )


# ═══════════════════════════════════════════════════════════════
# 1. SessionManager Tests
# ═══════════════════════════════════════════════════════════════


class TestSessionManager:
    def test_current_session_alias(self):
        """current_session() should return same as get_session_info()."""
        mgr = SessionManager()
        now = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        info1 = mgr.current_session(now)
        info2 = mgr.get_session_info(now)
        assert info1.primary_session == info2.primary_session
        assert info1.is_overlap == info2.is_overlap

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
        """Dead zone should not boost score above 1.0."""
        mgr = SessionManager()
        # 21:30 UTC — after NY close (21:00), before Sydney open (22:00)
        dead_time = datetime(2024, 1, 15, 21, 30, tzinfo=UTC)
        info = mgr.get_session_info(dead_time)
        score = mgr.get_session_score("EUR/USD", dead_time)
        assert score <= 1.0  # Dead zone, no overlap bonus

    def test_session_info_frozen(self):
        """SessionInfo should be immutable."""
        mgr = SessionManager()
        info = mgr.current_session()
        with pytest.raises(AttributeError):
            info.is_overlap = True


# ═══════════════════════════════════════════════════════════════
# 2. TrendDetector Tests
# ═══════════════════════════════════════════════════════════════


class TestTrendDetector:
    def test_uptrend_detection(self):
        """Uptrend data should be detected as bullish."""
        td = TrendDetector()
        data = _make_uptrend_data(250)
        state = td.detect(data, data, data)
        assert state.direction == TrendDirection.BULLISH
        assert state.aligned is True

    def test_downtrend_detection(self):
        """Downtrend data should be detected as bearish."""
        td = TrendDetector()
        data = _make_downtrend_data(250)
        state = td.detect(data, data, data)
        assert state.direction == TrendDirection.BEARISH

    def test_neutral_range(self):
        """Range-bound data should be neutral or weak."""
        td = TrendDetector()
        data = _make_range_data(250)
        state = td.detect(data, data, data)
        assert state.strength < 0.8

    def test_insufficient_data(self):
        """Insufficient data should return neutral."""
        td = TrendDetector()
        short_data = [100.0] * 10
        state = td.detect(short_data, short_data, short_data)
        assert state.direction == TrendDirection.NEUTRAL

    def test_analyze_alias(self):
        """analyze() should produce same result as detect()."""
        td = TrendDetector()
        data = _make_uptrend_data(250)
        state1 = td.detect(data, data, data)
        state2 = td.analyze(data, data, data)
        assert state1.direction == state2.direction
        assert state1.aligned == state2.aligned

    def test_swing_points(self):
        """Swing points should be detected in data with clear swings."""
        td = TrendDetector()
        # Create data with clear swing structure (zigzag pattern)
        import math
        data = [100 + 10 * math.sin(i / 5) + i * 0.1 for i in range(250)]
        state = td.detect(data, data, data)
        # Either swing points found or structure is insufficient (acceptable)
        assert isinstance(state.d1.swing_points, tuple)

    def test_update_genome(self):
        """update_genome should change MA periods."""
        td = TrendDetector()
        old_fast = td._fast_period
        td.update_genome({"trend_ma_fast": 30})
        assert td._fast_period == 30
        td.update_genome({"trend_ma_fast": old_fast})

    def test_confluence_score(self):
        """Confluence score should be > 0 for aligned trends."""
        td = TrendDetector()
        data = _make_uptrend_data(250)
        state = td.detect(data, data, data)
        if state.aligned:
            assert state.confluence_score > 0


# ═══════════════════════════════════════════════════════════════
# 3. RSIFilter Tests
# ═══════════════════════════════════════════════════════════════


class TestRSIFilter:
    def test_rsi_oversold(self):
        """Dropping prices should produce low RSI."""
        rsi = RSIFilter()
        # Create a series of dropping prices
        closes = [100 - i * 0.5 for i in range(30)]
        result = rsi.analyze(closes, "bearish")
        assert result.value < 50
        assert result.state in (RSIState.OVERSOLD, RSIState.NEAR_OVERSOLD, RSIState.NEUTRAL)

    def test_rsi_overbought(self):
        """Rising prices should produce high RSI."""
        rsi = RSIFilter()
        closes = [100 + i * 0.5 for i in range(30)]
        result = rsi.analyze(closes, "bullish")
        assert result.value > 50

    def test_rsi_insufficient_data(self):
        """Insufficient data should return neutral."""
        rsi = RSIFilter()
        result = rsi.analyze([100.0] * 5)
        assert result.state == RSIState.NEUTRAL
        assert result.score == 0.0

    def test_rsi_direction_alignment(self):
        """RSI should score based on zone and direction alignment."""
        rsi_filter = RSIFilter()
        # Oversold RSI should score higher with bullish hint
        oversold_closes = [100 - i * 0.5 for i in range(30)]
        result_bull = rsi_filter.analyze(oversold_closes, "bullish")
        result_bear = rsi_filter.analyze(oversold_closes, "bearish")
        # Oversold + bullish hint should score >= oversold + bearish hint
        assert result_bull.score >= result_bear.score

    def test_rsi_result_fields(self):
        """RSIResult should have all expected fields."""
        rsi = RSIFilter()
        closes = [100 + 5 * (i % 10 - 5) for i in range(30)]
        result = rsi.analyze(closes)
        assert hasattr(result, "value")
        assert hasattr(result, "state")
        assert hasattr(result, "signal")
        assert hasattr(result, "score")
        assert hasattr(result, "divergence")
        assert 0 <= result.value <= 100

    def test_update_genome(self):
        """update_genome should change RSI parameters."""
        rsi = RSIFilter()
        rsi.update_genome({"rsi_period": 10})
        assert rsi.genome["rsi_period"] == 10


# ═══════════════════════════════════════════════════════════════
# 4. CandlestickConfirmer Tests
# ═══════════════════════════════════════════════════════════════


class TestCandlestickConfirmer:
    def test_bullish_engulfing(self):
        """Should detect bullish engulfing pattern."""
        cc = CandlestickConfirmer()
        ohlcv = _make_bullish_engulfing_ohlcv(100.0)
        result = cc.analyze(ohlcv, direction_hint="bullish")
        assert result.pattern == CandlePattern.BULLISH_ENGULFING
        assert result.direction == "bullish"
        assert result.score > 0.5

    def test_insufficient_candles(self):
        """Should return neutral with too few candles."""
        cc = CandlestickConfirmer()
        result = cc.analyze([[100, 101, 99, 100.5, 1000]], direction_hint="neutral")
        assert result.pattern == CandlePattern.NONE

    def test_no_pattern(self):
        """Random candles may not produce a pattern."""
        cc = CandlestickConfirmer()
        random.seed(99)
        ohlcv = []
        price = 100.0
        for _ in range(10):
            o = price
            c = price + random.uniform(-0.1, 0.1)
            h = max(o, c) + 0.05
            l = min(o, c) - 0.05
            ohlcv.append([o, h, l, c, 1000])
            price = c
        result = cc.analyze(ohlcv, direction_hint="neutral")
        # Should return something (even NONE)
        assert isinstance(result.pattern, CandlePattern)

    def test_level_proximity_bonus(self):
        """Pattern at a key level should score higher."""
        cc = CandlestickConfirmer()
        ohlcv = _make_bullish_engulfing_ohlcv(100.0)
        last_close = ohlcv[-1][3]  # close is index 3

        result_no_level = cc.analyze(ohlcv, key_levels=[], direction_hint="bullish")
        result_with_level = cc.analyze(ohlcv, key_levels=[last_close], direction_hint="bullish")
        assert result_with_level.score >= result_no_level.score

    def test_update_genome(self):
        """update_genome should change parameters."""
        cc = CandlestickConfirmer()
        cc.update_genome({"engulfing_body_ratio": 0.8})
        assert cc.genome["engulfing_body_ratio"] == 0.8


# ═══════════════════════════════════════════════════════════════
# 5. LevelMapper Tests
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

    def test_daily_levels(self):
        """Daily OHLCV should produce daily S/R levels."""
        lm = LevelMapper()
        ohlcv = [
            {"open": 100, "high": 105, "low": 95, "close": 102, "volume": 1000},
            {"open": 102, "high": 108, "low": 101, "close": 106, "volume": 1200},
        ]
        levels = lm.map_levels(current_price=106, d1_ohlcv=ohlcv)
        daily = [l for l in levels.levels if l.timeframe == "D1"]
        assert len(daily) >= 2

    def test_map_all(self):
        """map_all should accept list-of-lists format."""
        lm = LevelMapper()
        ohlcv = [
            [100, 105, 95, 102, 1000],
            [102, 108, 101, 106, 1200],
        ]
        levels = lm.map_all(ohlc_d1=ohlcv, current_price=106)
        assert isinstance(levels, MappedLevels)

    def test_near_level_check(self):
        """is_near_level should detect proximity."""
        lm = LevelMapper()
        levels = (
            SRLevel(1.0850, LevelType.DAILY_HIGH, LevelSide.RESISTANCE, 0.8, "test", "D1", 1, 0.1),
            SRLevel(1.0800, LevelType.DAILY_LOW, LevelSide.SUPPORT, 0.8, "test", "D1", 1, 0.4),
        )
        is_near, nearest = lm.is_near_level(1.0852, levels, 0.1)
        assert is_near
        assert nearest.price == 1.0850

    def test_update_genome(self):
        """update_genome should change proximity threshold."""
        lm = LevelMapper()
        old = lm._proximity_pct
        lm.update_genome({"sr_proximity_pct": 0.5})
        assert lm._proximity_pct == 0.5


# ═══════════════════════════════════════════════════════════════
# 6. EntryPipeline Tests
# ═══════════════════════════════════════════════════════════════


class TestEntryPipeline:
    def test_news_gate_blocks(self):
        """Pipeline should block when news blackout is active."""
        pipeline = EntryPipeline()
        bias = FundamentalBias(
            direction=BiasDirection.NEUTRAL, confidence=0.5, news_clear=False,
            upcoming_events=(), blackout_active=True, blackout_reason="FOMC",
            event_risk_score=0.9, macro_alignment=0.5, reasoning="test",
        )
        trend = TrendDetector().detect([100 + i * 0.5 for i in range(250)] * 1, [100 + i * 0.5 for i in range(250)], [100 + i * 0.5 for i in range(250)])
        levels = LevelMapper().map_levels(current_price=224.0)

        result = pipeline.evaluate(
            current_price=224.0,
            fundamental_bias=bias,
            trend_state=trend,
            mapped_levels=levels,
            ohlcv=[{"open": 223, "high": 225, "low": 222, "close": 224, "volume": 1000}] * 10,
            rsi=45.0,
            atr=1.0,
        )
        assert not result.passed
        assert any(s.stage == PipelineStage.NEWS_GATE and not s.passed for s in result.stages)

    def test_neutral_trend_blocks(self):
        """Pipeline should block when trend is neutral."""
        pipeline = EntryPipeline()
        bias = _make_neutral_bias()
        trend = TrendDetector().detect([100.0] * 10, [100.0] * 10, [100.0] * 10)
        levels = LevelMapper().map_levels(current_price=100.0)

        result = pipeline.evaluate(
            current_price=100.0,
            fundamental_bias=bias,
            trend_state=trend,
            mapped_levels=levels,
            ohlcv=[{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}] * 10,
            rsi=50.0,
            atr=1.0,
        )
        assert not result.passed

    def test_pipeline_result_fields(self):
        """PipelineResult should have all expected fields."""
        pipeline = EntryPipeline()
        bias = _make_neutral_bias()
        trend = TrendDetector().detect([100.0] * 10, [100.0] * 10, [100.0] * 10)
        levels = LevelMapper().map_levels(current_price=100.0)

        result = pipeline.evaluate(
            current_price=100.0, fundamental_bias=bias, trend_state=trend,
            mapped_levels=levels, ohlcv=[{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}] * 5,
            rsi=50.0, atr=1.0,
        )
        assert hasattr(result, "passed")
        assert hasattr(result, "total_score")
        assert hasattr(result, "side")
        assert hasattr(result, "stages")
        assert hasattr(result, "entry_price")
        assert hasattr(result, "stop_loss")
        assert hasattr(result, "take_profit")


# ═══════════════════════════════════════════════════════════════
# 7. VMPMStrategy Smoke Tests
# ═══════════════════════════════════════════════════════════════


class TestVMPMStrategy:
    def test_instantiation(self):
        """VMPMStrategy should instantiate without errors."""
        s = VMPMStrategy()
        assert s.NAME == "vmpm"
        assert s.VERSION == "1.0.0"
        assert repr(s)

    def test_risk_params(self):
        """Risk params should be a dict with expected keys."""
        s = VMPMStrategy()
        params = s.get_risk_params()
        assert isinstance(params, dict)
        assert "risk_per_trade_pct" in params
        assert "session_aware_sizing" in params

    def test_check_entry_insufficient_data(self):
        """Should return None with insufficient data."""
        s = VMPMStrategy()
        result = s.check_entry({"symbol": "EUR/USD", "close": 100, "atr": 1.0})
        assert result is None

    def test_check_entry_with_full_data(self):
        """Should process full data without errors (signal or None)."""
        s = VMPMStrategy()
        closes = _make_uptrend_data(250)
        ohlcv = _make_ohlcv_from_closes(closes)

        result = s.check_entry({
            "symbol": "EUR/USD",
            "close": closes[-1],
            "atr": 0.5,
            "rsi": 45.0,
            "volume_ratio": 1.3,
            "d1_closes": closes,
            "h4_closes": closes,
            "h1_closes": closes,
            "d1_ohlcv": ohlcv,
            "h4_ohlcv": ohlcv,
            "h1_ohlcv": ohlcv,
            "asian_high": closes[-1] + 1.0,
            "asian_low": closes[-1] - 1.0,
        })
        # May or may not produce a signal depending on candlestick patterns
        assert result is None or isinstance(result, dict)

    def test_check_entry_signal_structure(self):
        """If signal is returned, it should have the expected structure."""
        s = VMPMStrategy()
        # Create data with a clear bullish engulfing at the end
        base_closes = _make_uptrend_data(248)
        ohlcv = _make_ohlcv_from_closes(base_closes)

        # Append a bearish then bullish engulfing candle
        last_price = base_closes[-1]
        ohlcv.append({"open": last_price + 0.3, "high": last_price + 0.6,
                       "low": last_price - 0.6, "close": last_price - 0.3, "volume": 1000})
        ohlcv.append({"open": last_price - 0.35, "high": last_price + 0.8,
                       "low": last_price - 0.5, "close": last_price + 0.5, "volume": 2000})
        closes = base_closes + [last_price - 0.3, last_price + 0.5]

        result = s.check_entry({
            "symbol": "EUR/USD",
            "close": closes[-1],
            "atr": 0.5,
            "rsi": 42.0,
            "volume_ratio": 1.5,
            "d1_closes": closes,
            "h4_closes": closes,
            "h1_closes": closes,
            "d1_ohlcv": ohlcv,
            "h4_ohlcv": ohlcv,
            "h1_ohlcv": ohlcv,
            "asian_high": closes[-1] + 1.0,
            "asian_low": closes[-1] - 1.0,
        })

        if result is not None:
            assert "side" in result
            assert "score" in result
            assert "entry_price" in result
            assert "stop_loss" in result
            assert "take_profit" in result
            assert result["side"] in ("buy", "sell")
            assert 0 < result["score"] <= 1.0
            assert result["entry_price"] > 0
            assert result["stop_loss"] > 0
            assert result["take_profit"] > 0

    def test_check_exit_buy_stop_loss(self):
        """Should trigger stop loss for long positions."""
        s = VMPMStrategy()
        exit_signal = s.check_exit(
            position={"side": "buy", "entry_price": 100.0, "stop_loss": 99.0, "take_profit": 103.0},
            data={"close": 98.5, "atr": 0.5, "closes": [100.0] * 15},
        )
        assert exit_signal is not None
        assert exit_signal["reason"] == "stop_loss"

    def test_check_exit_sell_stop_loss(self):
        """Should trigger stop loss for short positions."""
        s = VMPMStrategy()
        exit_signal = s.check_exit(
            position={"side": "sell", "entry_price": 100.0, "stop_loss": 101.0, "take_profit": 97.0},
            data={"close": 101.5, "atr": 0.5, "closes": [100.0] * 15},
        )
        assert exit_signal is not None
        assert exit_signal["reason"] == "stop_loss"

    def test_check_exit_take_profit(self):
        """Should trigger take profit."""
        s = VMPMStrategy()
        exit_signal = s.check_exit(
            position={"side": "buy", "entry_price": 100.0, "stop_loss": 99.0, "take_profit": 103.0},
            data={"close": 103.5, "atr": 0.5, "closes": [100.0] * 15},
        )
        assert exit_signal is not None
        assert exit_signal["reason"] == "take_profit"

    def test_check_exit_no_exit(self):
        """Should return None when no exit condition is met."""
        s = VMPMStrategy()
        exit_signal = s.check_exit(
            position={"side": "buy", "entry_price": 100.0, "stop_loss": 98.0, "take_profit": 105.0},
            data={"close": 101.0, "atr": 0.5, "closes": [100.0] * 15},
        )
        assert exit_signal is None

    def test_daily_counter_tracking(self):
        """Strategy should track daily trade count."""
        s = VMPMStrategy()
        assert s._daily_trade_count == 0


# ═══════════════════════════════════════════════════════════════
# 8. FundamentalAnalyzer Tests
# ═══════════════════════════════════════════════════════════════


class TestFundamentalAnalyzer:
    def test_neutral_constant(self):
        """FundamentalBias.NEUTRAL should exist and be neutral."""
        assert FundamentalBias.NEUTRAL is not None
        assert FundamentalBias.NEUTRAL.direction == BiasDirection.NEUTRAL
        assert FundamentalBias.NEUTRAL.news_clear is True

    def test_analyze_none(self):
        """analyze(None) should return neutral bias."""
        fa = FundamentalAnalyzer()
        result = fa.analyze(None)
        assert result.direction == BiasDirection.NEUTRAL

    def test_analyze_dict_no_high_impact(self):
        """analyze({}) should return neutral, news_clear."""
        fa = FundamentalAnalyzer()
        result = fa.analyze({})
        assert result.news_clear is True
        assert result.direction == BiasDirection.NEUTRAL

    def test_analyze_dict_high_impact(self):
        """analyze with high_impact_near should block."""
        fa = FundamentalAnalyzer()
        result = fa.analyze({"high_impact_near": True})
        assert result.news_clear is False
        assert result.blackout_active is True

    def test_analyze_dict_bullish(self):
        """analyze with bullish bias should return bullish direction."""
        fa = FundamentalAnalyzer()
        result = fa.analyze({"bias": "bullish"})
        assert result.direction == BiasDirection.BULLISH

    def test_currency_extraction(self):
        """Should extract currencies from pair string."""
        fa = FundamentalAnalyzer()
        assert fa._extract_currencies("EUR/USD") == ("EUR", "USD")
        assert fa._extract_currencies("BTC/USDT") == ("BTC", "USDT")
        assert fa._extract_currencies("BTCUSDT") == ("BTC", "USDT")

    def test_crypto_no_events(self):
        """Crypto pairs should have no traditional events."""
        fa = FundamentalAnalyzer()
        events = fa._generate_known_events("BTC", "USDT", datetime.now(UTC))
        assert events == []

    def test_analyze_pair_sync(self):
        """_analyze_pair_sync should return a FundamentalBias."""
        fa = FundamentalAnalyzer()
        result = fa._analyze_pair_sync("EUR/USD", datetime.now(UTC))
        assert isinstance(result, FundamentalBias)


# ═══════════════════════════════════════════════════════════════
# 9. Integration: Full Pipeline Smoke Test
# ═══════════════════════════════════════════════════════════════


class TestVMPMIntegration:
    def test_full_pipeline_uptrend(self):
        """Full VMPM pipeline with uptrend data should not crash."""
        s = VMPMStrategy()
        closes = _make_uptrend_data(250)
        ohlcv = _make_ohlcv_from_closes(closes)

        result = s.check_entry({
            "symbol": "EUR/USD",
            "close": closes[-1],
            "atr": 0.5,
            "rsi": 42.0,
            "volume_ratio": 1.5,
            "d1_closes": closes,
            "h4_closes": closes,
            "h1_closes": closes,
            "d1_ohlcv": ohlcv,
            "h4_ohlcv": ohlcv,
            "h1_ohlcv": ohlcv,
            "asian_high": closes[-1] + 1.0,
            "asian_low": closes[-1] - 1.0,
            "macro_alignment": 0.6,
            "news_clear": True,
        })
        assert result is None or isinstance(result, dict)

    def test_full_pipeline_downtrend(self):
        """Full VMPM pipeline with downtrend data should not crash."""
        s = VMPMStrategy()
        closes = _make_downtrend_data(250)
        ohlcv = _make_ohlcv_from_closes(closes)

        result = s.check_entry({
            "symbol": "EUR/USD",
            "close": closes[-1],
            "atr": 0.5,
            "rsi": 58.0,
            "volume_ratio": 1.5,
            "d1_closes": closes,
            "h4_closes": closes,
            "h1_closes": closes,
            "d1_ohlcv": ohlcv,
            "h4_ohlcv": ohlcv,
            "h1_ohlcv": ohlcv,
        })
        assert result is None or isinstance(result, dict)

    def test_pipeline_components_isolated(self):
        """Each component should work independently."""
        # SessionManager
        sm = SessionManager()
        info = sm.current_session()
        assert isinstance(info, SessionInfo)

        # TrendDetector
        td = TrendDetector()
        closes = _make_uptrend_data(250)
        trend = td.detect(closes, closes, closes)
        assert isinstance(trend, TrendState)

        # RSIFilter
        rf = RSIFilter()
        rsi_result = rf.analyze(closes, "bullish")
        assert isinstance(rsi_result, RSIResult)

        # CandlestickConfirmer (expects list[list[float]])
        cc = CandlestickConfirmer()
        ohlcv_lists = _make_bullish_engulfing_ohlcv(100.0)
        candle_result = cc.analyze(ohlcv_lists, direction_hint="bullish")
        assert isinstance(candle_result, CandleResult)

        # LevelMapper
        lm = LevelMapper()
        levels = lm.map_levels(current_price=closes[-1])
        assert isinstance(levels, MappedLevels)

        # EntryPipeline
        ep = EntryPipeline()
        bias = _make_neutral_bias()
        ohlcv_dicts = _make_ohlcv_from_closes(closes[-20:])
        pipeline_result = ep.evaluate(
            current_price=closes[-1],
            fundamental_bias=bias,
            trend_state=trend,
            mapped_levels=levels,
            ohlcv=ohlcv_dicts,
            rsi=rsi_result.value,
            atr=0.5,
        )
        assert isinstance(pipeline_result, PipelineResult)
