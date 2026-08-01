"""
Tests for execution tools: order placement, OCO, slippage, fill quality.

Covers H-15 (critical path tests) for the execution lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.interfaces.types import (
    ExecutionResult,
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.tools.execution import (
    ExecutionTools,
    FillQualityReport,
    OCOGroup,
    PlacementResult,
    SlippageReport,
    SlippageStats,
)

# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.execute_order = AsyncMock(
        return_value=ExecutionResult(
            order_id="ord-001",
            symbol="BTC/USDT",
            status=OrderStatus.FILLED,
            filled_quantity=0.1,
            average_price=50000.0,
            total_fee=5.0,
            fills=(
                Fill(
                    fill_id="fill-001",
                    order_id="ord-001",
                    symbol="BTC/USDT",
                    side=OrderSide.BUY,
                    price=50000.0,
                    quantity=0.1,
                    fee=5.0,
                    fee_currency="USDT",
                    timestamp=datetime.now(UTC),
                ),
            ),
            slippage_bps=0.5,
        )
    )
    engine.cancel_order = AsyncMock(return_value=True)
    engine.get_order_status = AsyncMock(return_value=OrderStatus.OPEN)
    engine.get_open_orders = AsyncMock(return_value=[])
    engine.get_fills = AsyncMock(return_value=[])
    return engine


@pytest.fixture
def mock_gateway():
    gw = AsyncMock()
    gw.validate_order_limits = MagicMock(return_value=(True, ""))
    gw.amount_to_precision = MagicMock(side_effect=lambda s, q: q)
    gw.price_to_precision = MagicMock(side_effect=lambda s, p: p)
    return gw


@pytest.fixture
def tools(mock_engine, mock_gateway):
    return ExecutionTools(engine=mock_engine, gateway=mock_gateway)


# ═══════════════════════════════════════════════════════════════════════
# Order Placement Tests
# ═══════════════════════════════════════════════════════════════════════


class TestOrderPlacement:
    async def test_place_market_order(self, tools, mock_engine):
        """Market order delegates to engine.execute_order."""
        result = await tools.place_market_order("BTC/USDT", "buy", 0.1)
        assert isinstance(result, PlacementResult)
        assert result.order_id == "ord-001"
        assert result.symbol == "BTC/USDT"
        assert result.side == "buy"
        assert result.order_type == "market"
        mock_engine.execute_order.assert_called_once()

    async def test_place_limit_order(self, tools, mock_engine):
        """Limit order includes price in the call."""
        result = await tools.place_limit_order("BTC/USDT", "buy", 0.1, 50000.0)
        assert result.order_type == "limit"
        assert result.price == 50000.0

    async def test_place_stop_loss_order(self, tools):
        """Stop-loss order passes stop_price."""
        result = await tools.place_stop_loss_order(
            "BTC/USDT", "sell", 0.1, stop_price=49000.0
        )
        assert result.order_type == "stop_market"

    async def test_place_take_profit_order(self, tools):
        """Take-profit order as limit order."""
        result = await tools.place_take_profit_order(
            "BTC/USDT", "sell", 0.1, price=52000.0
        )
        assert result.order_type == "limit"

    async def test_place_take_profit_with_stop(self, tools):
        """Take-profit with stop_price becomes stop_limit."""
        result = await tools.place_take_profit_order(
            "BTC/USDT", "sell", 0.1, price=52000.0, stop_price=51500.0
        )
        assert result.order_type == "stop_limit"

    async def test_exchange_limit_rejection(self, tools, mock_gateway):
        """Order rejected by exchange limits raises ValueError."""
        mock_gateway.validate_order_limits = MagicMock(
            return_value=(False, "Below minimum")
        )
        with pytest.raises(ValueError, match="exchange limits"):
            await tools.place_market_order("BTC/USDT", "buy", 0.0001)

    async def test_precision_applied(self, tools, mock_gateway):
        """Gateway precision methods are called."""
        mock_gateway.amount_to_precision = MagicMock(return_value=0.12345)
        await tools.place_market_order("BTC/USDT", "buy", 0.123456)
        mock_gateway.amount_to_precision.assert_called()


# ═══════════════════════════════════════════════════════════════════════
# OCO Order Tests
# ═══════════════════════════════════════════════════════════════════════


class TestOCOOrders:
    async def test_place_oco_creates_group(self, tools, mock_engine):
        """OCO placement creates both SL and TP orders."""
        group = await tools.place_oco_order(
            symbol="BTC/USDT",
            side="sell",
            quantity=0.1,
            stop_loss_price=49000.0,
            take_profit_price=52000.0,
            entry_order_id="entry-001",
        )
        assert isinstance(group, OCOGroup)
        assert group.status == "active"
        assert group.symbol == "BTC/USDT"
        assert mock_engine.execute_order.call_count == 2

    async def test_get_active_oco_groups(self, tools, mock_engine):
        """Active OCO groups are tracked."""
        await tools.place_oco_order(
            "BTC/USDT", "sell", 0.1, 49000.0, 52000.0, "entry-001"
        )
        active = await tools.get_active_oco_groups()
        assert len(active) == 1

    async def test_cancel_order_cancels_oco_partner(self, tools, mock_engine):
        """Cancelling one OCO leg cancels the other."""
        group = await tools.place_oco_order(
            "BTC/USDT", "sell", 0.1, 49000.0, 52000.0, "entry-001"
        )
        await tools.cancel_order(group.sl_order_id)
        # Both orders should have been cancelled
        assert mock_engine.cancel_order.call_count >= 2


# ═══════════════════════════════════════════════════════════════════════
# Slippage Tracker Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSlippageTracker:
    def test_record_slippage_buy(self, tools):
        """Buy slippage: adverse = positive bps."""
        report = tools.record_slippage(
            "ord-001", "BTC/USDT", "buy", 50000.0, 50010.0, 0.1
        )
        assert isinstance(report, SlippageReport)
        assert report.slippage_bps > 0  # Adverse for buy

    def test_record_slippage_sell(self, tools):
        """Sell slippage: adverse = positive bps."""
        report = tools.record_slippage(
            "ord-002", "BTC/USDT", "sell", 50000.0, 49990.0, 0.1
        )
        assert report.slippage_bps > 0  # Adverse for sell

    def test_slippage_stats_empty(self, tools):
        """Empty history returns zero stats."""
        stats = tools.get_slippage_stats()
        assert stats.total_trades == 0
        assert stats.avg_slippage_bps == 0.0

    def test_slippage_stats_with_data(self, tools):
        """Stats computed from recorded slippage."""
        tools.record_slippage("o1", "BTC/USDT", "buy", 50000.0, 50010.0, 0.1)
        tools.record_slippage("o2", "BTC/USDT", "buy", 50000.0, 49990.0, 0.1)
        stats = tools.get_slippage_stats()
        assert stats.total_trades == 2
        assert stats.avg_slippage_bps > 0

    def test_slippage_stats_by_symbol(self, tools):
        """Per-symbol breakdown is computed."""
        tools.record_slippage("o1", "BTC/USDT", "buy", 50000.0, 50010.0, 0.1)
        tools.record_slippage("o2", "ETH/USDT", "buy", 3000.0, 3001.0, 1.0)
        stats = tools.get_slippage_stats()
        assert "BTC/USDT" in stats.slippage_by_symbol
        assert "ETH/USDT" in stats.slippage_by_symbol


# ═══════════════════════════════════════════════════════════════════════
# Fill Quality Tests
# ═══════════════════════════════════════════════════════════════════════


class TestFillQuality:
    async def test_analyze_fill_quality_no_fills(self, tools, mock_engine):
        """Empty fills returns zeroed report."""
        mock_engine.get_fills = AsyncMock(return_value=[])
        report = await tools.analyze_fill_quality("ord-001")
        assert isinstance(report, FillQualityReport)
        assert report.fill_rate == 0
        assert report.num_fills == 0
        assert report.is_partial is True

    async def test_analyze_fill_quality_with_fills(self, tools, mock_engine):
        """Fill quality computed from actual fills."""
        now = datetime.now(UTC)
        mock_engine.get_fills = AsyncMock(
            return_value=[
                Fill(
                    fill_id="f1",
                    order_id="ord-001",
                    symbol="BTC/USDT",
                    side=OrderSide.BUY,
                    price=50000.0,
                    quantity=0.05,
                    fee=2.5,
                    fee_currency="USDT",
                    timestamp=now,
                ),
                Fill(
                    fill_id="f2",
                    order_id="ord-001",
                    symbol="BTC/USDT",
                    side=OrderSide.BUY,
                    price=50005.0,
                    quantity=0.05,
                    fee=2.5,
                    fee_currency="USDT",
                    timestamp=now,
                ),
            ]
        )
        mock_engine.get_open_orders = AsyncMock(
            return_value=[
                Order(
                    order_id="ord-001",
                    symbol="BTC/USDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=0.1,
                )
            ]
        )
        report = await tools.analyze_fill_quality("ord-001")
        assert report.num_fills == 2
        assert report.filled_quantity == pytest.approx(0.1)
        assert report.fill_rate == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════
# Smoke Tests
# ═══════════════════════════════════════════════════════════════════════


class TestExecutionSmoke:
    def test_import_execution_tools(self):
        from src.tools.execution import ExecutionTools
        assert ExecutionTools is not None

    def test_import_result_types(self):
        from src.tools.execution import (
            FillQualityReport,
            OCOGroup,
            PlacementResult,
            SlippageReport,
        )
        assert PlacementResult is not None
        assert OCOGroup is not None
        assert SlippageReport is not None
        assert SlippageStats is not None
        assert FillQualityReport is not None
