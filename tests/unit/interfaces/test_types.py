"""
Unit tests for src.interfaces.types — dataclasses and enums.

Verifies:
  - All enums have correct values
  - All dataclasses can be instantiated with required fields
  - Frozen dataclasses are truly immutable
  - Default values are correct
  - Field types match expectations
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.interfaces.types import (
    Balance,
    BollingerResult,
    ConnectionStatus,
    DrawdownLevel,
    DrawdownState,
    ExecutionResult,
    Fill,
    LLMChunk,
    LLMResponse,
    MACDResult,
    ModelCapabilities,
    OHLCV,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    PositionSizeResult,
    Price,
    RiskCheckResult,
    RiskDecision,
    SRLevel,
    SRLevels,
    Signal,
    Timeframe,
    TimeInForce,
    Trade,
    VetoLevel,
)


# ═══════════════════════════════════════════════════════════════════════
# ENUM VALUE TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestEnums:
    """Verify all enums have the expected member values."""

    def test_order_side_values(self):
        assert OrderSide.BUY == "buy"
        assert OrderSide.SELL == "sell"
        assert len(OrderSide) == 2

    def test_order_type_values(self):
        assert OrderType.MARKET == "market"
        assert OrderType.LIMIT == "limit"
        assert OrderType.STOP_MARKET == "stop_market"
        assert OrderType.STOP_LIMIT == "stop_limit"
        assert len(OrderType) == 4

    def test_order_status_values(self):
        expected = ["pending", "open", "filled", "partially_filled",
                    "cancelled", "rejected", "expired"]
        for name, val in zip(
            ["PENDING", "OPEN", "FILLED", "PARTIALLY_FILLED",
             "CANCELLED", "REJECTED", "EXPIRED"],
            expected,
        ):
            assert OrderStatus[name] == val
        assert len(OrderStatus) == 7

    def test_timeframe_values(self):
        expected = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
                    "H1": "1h", "H4": "4h", "D1": "1d", "W1": "1w"}
        for name, val in expected.items():
            assert Timeframe[name] == val
        assert len(Timeframe) == 8

    def test_connection_status_values(self):
        expected = {"DISCONNECTED": "disconnected", "CONNECTING": "connecting",
                    "CONNECTED": "connected", "RECONNECTING": "reconnecting",
                    "ERROR": "error"}
        for name, val in expected.items():
            assert ConnectionStatus[name] == val
        assert len(ConnectionStatus) == 5

    def test_time_in_force_values(self):
        assert TimeInForce.GTC == "gtc"
        assert TimeInForce.IOC == "ioc"
        assert TimeInForce.FOK == "fok"
        assert TimeInForce.GTX == "gtx"
        assert len(TimeInForce) == 4

    def test_veto_level_values(self):
        assert VetoLevel.NONE == "NONE"
        assert VetoLevel.SOFT == "SOFT"
        assert VetoLevel.FIRM == "FIRM"
        assert VetoLevel.HARD == "HARD"
        assert VetoLevel.NUCLEAR == "NUCLEAR"
        assert len(VetoLevel) == 5

    def test_drawdown_level_values(self):
        assert DrawdownLevel.GREEN == "GREEN"
        assert DrawdownLevel.YELLOW == "YELLOW"
        assert DrawdownLevel.ORANGE == "ORANGE"
        assert DrawdownLevel.RED == "RED"
        assert len(DrawdownLevel) == 4

    def test_enums_are_str_enums(self):
        """All enums inherit from str, so they can be compared to strings."""
        assert OrderSide.BUY == "buy"
        assert OrderStatus.FILLED == "filled"
        assert Timeframe.H1 == "1h"
        assert VetoLevel.HARD == "HARD"


# ═══════════════════════════════════════════════════════════════════════
# DATACLASS INSTANTIATION TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestDataclasses:
    """Verify all dataclasses can be created and have correct defaults."""

    def test_price_creation(self, fixed_ts):
        p = Price(symbol="BTC/USDT", last=50000.0, bid=49999.0, ask=50001.0, timestamp=fixed_ts)
        assert p.symbol == "BTC/USDT"
        assert p.last == 50000.0
        assert p.bid == 49999.0
        assert p.ask == 50001.0

    def test_ohlcv_creation(self, fixed_ts):
        c = OHLCV(timestamp=fixed_ts, open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0)
        assert c.open == 100.0
        assert c.high == 110.0
        assert c.low == 90.0
        assert c.close == 105.0
        assert c.volume == 1000.0

    def test_order_book_level(self):
        level = OrderBookLevel(price=50000.0, quantity=1.5)
        assert level.price == 50000.0
        assert level.quantity == 1.5

    def test_order_book_creation(self, fixed_ts):
        bids = (OrderBookLevel(49999.0, 1.0), OrderBookLevel(49998.0, 2.0))
        asks = (OrderBookLevel(50001.0, 1.0), OrderBookLevel(50002.0, 2.0))
        ob = OrderBook(symbol="BTC/USDT", bids=bids, asks=asks, timestamp=fixed_ts)
        assert len(ob.bids) == 2
        assert len(ob.asks) == 2

    def test_trade_creation(self, fixed_ts):
        t = Trade(
            id="t1", symbol="BTC/USDT", side=OrderSide.BUY,
            price=50000.0, quantity=0.1, cost=5000.0,
            fee=5.0, fee_currency="USDT", timestamp=fixed_ts,
        )
        assert t.id == "t1"
        assert t.side == OrderSide.BUY

    def test_position_defaults(self):
        pos = Position(
            symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.1,
            entry_price=50000.0, current_price=50500.0, unrealized_pnl=50.0,
        )
        assert pos.leverage == 1.0
        assert pos.liquidation_price is None
        assert pos.timestamp is None

    def test_balance_defaults(self):
        b = Balance(total=100000.0, free=80000.0, used=20000.0)
        assert b.currency == "USDT"
        assert b.per_currency == {}

    def test_order_defaults(self):
        o = Order(
            order_id="o1", symbol="BTC/USDT", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=0.1,
        )
        assert o.price is None
        assert o.stop_price is None
        assert o.filled_quantity == 0.0
        assert o.status == OrderStatus.PENDING
        assert o.fee == 0.0

    def test_order_request_defaults(self):
        req = OrderRequest(
            symbol="BTC/USDT", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=0.1,
        )
        assert req.price is None
        assert req.time_in_force == TimeInForce.GTC

    def test_fill_creation(self, fixed_ts):
        f = Fill(
            fill_id="f1", order_id="o1", symbol="BTC/USDT",
            side=OrderSide.BUY, price=50000.0, quantity=0.1,
            fee=5.0, fee_currency="USDT", timestamp=fixed_ts,
        )
        assert f.fill_id == "f1"

    def test_execution_result_defaults(self, fixed_ts):
        er = ExecutionResult(
            order_id="o1", symbol="BTC/USDT", status=OrderStatus.FILLED,
            filled_quantity=0.1, average_price=50000.0, total_fee=5.0,
            timestamp=fixed_ts,
        )
        assert er.fills == ()
        assert er.slippage_bps == 0.0

    def test_signal_defaults(self, fixed_ts):
        s = Signal(
            signal_id="s1", symbol="BTC/USDT", side=OrderSide.BUY,
            score=0.8, entry_price=50000.0, stop_loss=49500.0,
            take_profit=51000.0, strategy="test",
        )
        assert s.reasoning == ""
        assert s.metadata == {}
        assert s.timestamp is None

    def test_risk_decision_defaults(self):
        rd = RiskDecision(signal_id="s1", approved=True)
        assert rd.position_size == 0.0
        assert rd.rejection_reasons == ()
        assert rd.warnings == ()
        assert rd.veto_level == "NONE"

    def test_portfolio_defaults(self):
        p = Portfolio(equity=100000.0, high_water_mark=100000.0, cash=90000.0)
        assert p.positions == ()
        assert p.daily_pnl == 0.0
        assert p.open_position_count == 0

    def test_drawdown_state_creation(self):
        ds = DrawdownState(
            current_drawdown_pct=-0.01, high_water_mark=100000.0,
            current_equity=99000.0, daily_pnl=-100.0, daily_pnl_pct=-0.001,
            circuit_breaker_level="GREEN", trading_allowed=True,
        )
        assert ds.position_size_multiplier == 1.0

    def test_risk_check_result_defaults(self):
        rcr = RiskCheckResult(approved=True)
        assert rcr.veto_level is None
        assert rcr.reason == ""
        assert rcr.checks_passed == ()
        assert rcr.checks_failed == ()

    def test_position_size_result_defaults(self):
        psr = PositionSizeResult(
            quantity=0.1, notional_value=5000.0,
            risk_amount=100.0, risk_pct=0.01,
        )
        assert psr.method == "half_kelly"
        assert psr.capped is False
        assert psr.cap_reason == ""

    def test_macd_result(self):
        macd = MACDResult(
            macd_line=(1.0, 2.0), signal_line=(0.5, 1.5), histogram=(0.5, 0.5),
        )
        assert len(macd.macd_line) == 2

    def test_bollinger_result(self):
        bb = BollingerResult(
            upper=(100.0,), middle=(90.0,), lower=(80.0,), bandwidth=(0.22,),
        )
        assert bb.upper == (100.0,)

    def test_sr_level(self):
        level = SRLevel(price=50000.0, strength=0.9, level_type="support", touches=5)
        assert level.price == 50000.0
        assert level.touches == 5

    def test_sr_levels_defaults(self):
        sr = SRLevels()
        assert sr.supports == ()
        assert sr.resistances == ()

    def test_llm_response_defaults(self):
        resp = LLMResponse(content="hello")
        assert resp.model == ""
        assert resp.total_tokens == 0
        assert resp.finish_reason == "stop"

    def test_llm_chunk_defaults(self):
        chunk = LLMChunk(content="hello")
        assert chunk.chunk_index == 0
        assert chunk.finish_reason is None

    def test_model_capabilities_defaults(self):
        mc = ModelCapabilities(model="gpt-4")
        assert mc.max_context_tokens == 4096
        assert mc.supports_streaming is True
        assert mc.supports_vision is False


# ═══════════════════════════════════════════════════════════════════════
# FROZEN (IMMUTABILITY) TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestFrozen:
    """Verify frozen dataclasses reject mutation."""

    def test_price_is_frozen(self, fixed_ts):
        p = Price(symbol="BTC/USDT", last=50000.0, bid=49999.0, ask=50001.0, timestamp=fixed_ts)
        with pytest.raises(AttributeError):
            p.last = 99999.0  # type: ignore[misc]

    def test_ohlcv_is_frozen(self, fixed_ts):
        c = OHLCV(timestamp=fixed_ts, open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0)
        with pytest.raises(AttributeError):
            c.close = 200.0  # type: ignore[misc]

    def test_position_is_frozen(self):
        pos = Position(
            symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.1,
            entry_price=50000.0, current_price=50500.0, unrealized_pnl=50.0,
        )
        with pytest.raises(AttributeError):
            pos.quantity = 1.0  # type: ignore[misc]

    def test_signal_is_frozen(self):
        s = Signal(
            signal_id="s1", symbol="BTC/USDT", side=OrderSide.BUY,
            score=0.8, entry_price=50000.0, stop_loss=49500.0,
            take_profit=51000.0, strategy="test",
        )
        with pytest.raises(AttributeError):
            s.score = 0.9  # type: ignore[misc]

    def test_order_is_frozen(self):
        o = Order(
            order_id="o1", symbol="BTC/USDT", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=0.1,
        )
        with pytest.raises(AttributeError):
            o.quantity = 1.0  # type: ignore[misc]

    def test_risk_decision_is_frozen(self):
        rd = RiskDecision(signal_id="s1", approved=True)
        with pytest.raises(AttributeError):
            rd.approved = False  # type: ignore[misc]

    def test_portfolio_is_frozen(self):
        p = Portfolio(equity=100000.0, high_water_mark=100000.0, cash=90000.0)
        with pytest.raises(AttributeError):
            p.equity = 0.0  # type: ignore[misc]
