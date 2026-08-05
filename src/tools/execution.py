"""
TSAR Domain Tools — Execution Tools.

What the agent DOES. Covers the full order execution lifecycle:
placement, management, linked orders, slippage tracking, and fill
quality analysis.

Tools:
  1. Order Placement     — Market, limit, stop-loss, take-profit orders
  2. Order Management    — Modify, cancel, replace orders
  3. OCO Orders          — One-Cancels-Other (linked SL/TP)
  4. Slippage Tracker    — Per-trade slippage measurement & aggregation
  5. Fill Quality Analyzer — Fill rate, partial fills, time-to-fill

All tools are async and delegate to the ExecutionEngine interface.
Results use shared types from src.interfaces.types.

Usage:
    tools = ExecutionTools(engine, gateway)
    result = await tools.place_order(symbol="BTC/USDT", side="buy", ...)
    quality = await tools.analyze_fill_quality(order_id="...")
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from src.interfaces.exchange_gateway import ExchangeGateway
    from src.interfaces.execution_engine import ExecutionEngine

from src.interfaces.types import (
    Order as OrderType_Order,
)
from src.interfaces.types import (
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PlacementResult:
    """Result of placing an order.

    Attributes:
        order_id: Exchange-assigned order ID.
        symbol: Trading pair.
        side: Buy or sell.
        order_type: Type of order placed.
        quantity: Ordered quantity.
        price: Limit price (None for market).
        status: Current order status.
        filled_quantity: Quantity filled so far.
        average_price: Average fill price.
        slippage_bps: Slippage in basis points.
        total_fee: Total fees paid.
        timestamp: When the order was placed.
    """

    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float | None = None
    status: str = "pending"
    filled_quantity: float = 0.0
    average_price: float = 0.0
    slippage_bps: float = 0.0
    total_fee: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OCOGroup:
    """An OCO (One-Cancels-Other) order group.

    Links a stop-loss and take-profit order — when one fills,
    the other is automatically cancelled.

    Attributes:
        group_id: Unique OCO group identifier.
        entry_order_id: The entry order this OCO protects.
        sl_order_id: Stop-loss order ID.
        tp_order_id: Take-profit order ID.
        symbol: Trading pair.
        side: Direction of the exit orders.
        sl_quantity: Stop-loss order quantity.
        sl_price: Stop-loss trigger price.
        tp_quantity: Take-profit order quantity.
        tp_price: Take-profit limit price.
        status: Group status — active, sl_filled, tp_filled, cancelled.
        created_at: When the OCO group was created.
    """

    group_id: str
    entry_order_id: str
    sl_order_id: str
    tp_order_id: str
    symbol: str
    side: str
    sl_quantity: float
    sl_price: float
    tp_quantity: float
    tp_price: float
    status: str = "active"
    created_at: datetime | None = None


@dataclass(frozen=True)
class SlippageReport:
    """Slippage analysis for a single trade.

    Attributes:
        order_id: Order ID.
        symbol: Trading pair.
        side: Buy or sell.
        expected_price: Price at order submission time.
        actual_price: Actual volume-weighted average fill price.
        slippage_bps: Slippage in basis points (positive = adverse).
        slippage_usd: Absolute slippage in USD.
        quantity: Order quantity.
        timestamp: When the trade occurred.
    """

    order_id: str
    symbol: str
    side: str
    expected_price: float
    actual_price: float
    slippage_bps: float
    slippage_usd: float
    quantity: float
    timestamp: datetime | None = None


@dataclass(frozen=True)
class SlippageStats:
    """Aggregated slippage statistics.

    Attributes:
        symbol: Trading pair (None = all symbols).
        total_trades: Number of trades analyzed.
        avg_slippage_bps: Average absolute slippage in bps.
        median_slippage_bps: Median absolute slippage in bps.
        max_slippage_bps: Maximum adverse slippage in bps.
        total_slippage_usd: Cumulative slippage cost in USD.
        slippage_by_hour: Average slippage by hour of day (UTC).
        slippage_by_symbol: Average slippage per symbol.
    """

    symbol: str | None = None
    total_trades: int = 0
    avg_slippage_bps: float = 0.0
    median_slippage_bps: float = 0.0
    max_slippage_bps: float = 0.0
    total_slippage_usd: float = 0.0
    slippage_by_hour: dict[int, float] = field(default_factory=dict)
    slippage_by_symbol: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FillQualityReport:
    """Fill quality analysis for an order.

    Attributes:
        order_id: Order ID.
        symbol: Trading pair.
        side: Buy or sell.
        order_type: Type of order.
        requested_quantity: Quantity requested.
        filled_quantity: Quantity actually filled.
        fill_rate: Fill rate (0.0 to 1.0).
        num_fills: Number of individual fills.
        is_partial: Whether the order was partially filled.
        time_to_fill_ms: Time from placement to final fill (ms).
        avg_fill_size: Average fill size.
        fill_price_variance: Variance of fill prices (quality metric).
        average_fill_price: Volume-weighted average fill price.
        best_fill_price: Best (most favorable) fill price.
        worst_fill_price: Worst (least favorable) fill price.
        price_improvement_bps: Price improvement vs limit (bps).
        timestamp: When the analysis was performed.
    """

    order_id: str
    symbol: str
    side: str
    order_type: str
    requested_quantity: float
    filled_quantity: float
    fill_rate: float
    num_fills: int
    is_partial: bool
    time_to_fill_ms: float
    avg_fill_size: float
    fill_price_variance: float
    average_fill_price: float
    best_fill_price: float
    worst_fill_price: float
    price_improvement_bps: float = 0.0
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# EXECUTION TOOLS
# ═══════════════════════════════════════════════════════════════════════


class ExecutionTools:
    """Execution tools for order placement, management, and analysis.

    Provides the complete execution toolkit that TSAR agents use to
    interact with the market: placing orders, managing OCO groups,
    tracking slippage, and analyzing fill quality.

    All operations delegate to the ExecutionEngine for actual
    order placement and to the ExchangeGateway for market data.
    """

    description = (
        "Execution tools: order placement, management, OCO orders, "
        "slippage tracking, fill quality analysis"
    )

    def __init__(
        self,
        engine: ExecutionEngine,
        gateway: ExchangeGateway,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._engine = engine
        self._gateway = gateway
        self._config = config or {}

        # Slippage tracking history
        self._slippage_history: list[SlippageReport] = []

        # OCO group tracking
        self._oco_groups: dict[str, OCOGroup] = {}

        # Fill tracking for quality analysis
        self._fill_records: dict[str, list[dict[str, Any]]] = {}  # order_id -> fill data
        self._order_timestamps: dict[str, datetime] = {}  # order_id -> placement time

    # ── 1. Order Placement ──────────────────────────────────────────

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> PlacementResult:
        """Place a market order for immediate execution.

        Market orders execute at the best available price. They guarantee
        fill but not price — use for urgent entries/exits.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell".
            quantity: Order quantity in base asset units.

        Returns:
            PlacementResult with fill information.
        """
        return await self._place_order(
            symbol=symbol,
            side=side,
            order_type="market",
            quantity=quantity,
        )

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "gtc",
    ) -> PlacementResult:
        """Place a limit order at a specific price.

        Limit orders execute only at the specified price or better.
        They guarantee price but not fill — the order may rest unfilled.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell".
            quantity: Order quantity in base asset units.
            price: Limit price.
            time_in_force: "gtc" (good-till-cancel), "ioc" (immediate-or-cancel),
                          "fok" (fill-or-kill), "gtx" (post-only).

        Returns:
            PlacementResult with order status.
        """
        return await self._place_order(
            symbol=symbol,
            side=side,
            order_type="limit",
            quantity=quantity,
            price=price,
            time_in_force=time_in_force,
        )

    async def place_stop_loss_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        order_type: str = "stop_market",
        limit_price: float | None = None,
    ) -> PlacementResult:
        """Place a stop-loss order to limit downside risk.

        Stop-loss orders trigger when the market reaches the stop price.
        - stop_market: Triggers a market order at the stop price.
        - stop_limit: Triggers a limit order at limit_price when stop is hit.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell" (typically sell for long positions).
            quantity: Order quantity in base asset units.
            stop_price: Price that triggers the order.
            order_type: "stop_market" or "stop_limit".
            limit_price: Limit price for stop-limit orders (None for stop-market).

        Returns:
            PlacementResult with order status.
        """
        return await self._place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=limit_price,
            stop_price=stop_price,
        )

    async def place_take_profit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_price: float | None = None,
    ) -> PlacementResult:
        """Place a take-profit order to lock in gains.

        Take-profit orders execute when the market reaches the target price.
        Uses a limit order for precise price targeting.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell" (typically sell for long positions).
            quantity: Order quantity in base asset units.
            price: Take-profit limit price.
            stop_price: Optional stop trigger price (for stop-limit TP).

        Returns:
            PlacementResult with order status.
        """
        if stop_price is not None:
            return await self._place_order(
                symbol=symbol,
                side=side,
                order_type="stop_limit",
                quantity=quantity,
                price=price,
                stop_price=stop_price,
            )
        return await self._place_order(
            symbol=symbol,
            side=side,
            order_type="limit",
            quantity=quantity,
            price=price,
        )

    # ── 2. Order Management ─────────────────────────────────────────

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Args:
            order_id: Exchange-assigned order ID.

        Returns:
            True if the order was cancelled successfully.
        """
        # Clean up OCO groups if this order is part of one
        for group_id, group in list(self._oco_groups.items()):
            if group.status == "active" and (order_id in (group.sl_order_id, group.tp_order_id)):
                # Cancel the other leg
                other_id = group.tp_order_id if order_id == group.sl_order_id else group.sl_order_id
                try:
                    await self._engine.cancel_order(other_id)
                except Exception as exc:
                    logger.warning("Failed to cancel OCO partner %s: %s", other_id, exc)

                self._oco_groups[group_id] = OCOGroup(
                    group_id=group.group_id,
                    entry_order_id=group.entry_order_id,
                    sl_order_id=group.sl_order_id,
                    tp_order_id=group.tp_order_id,
                    symbol=group.symbol,
                    side=group.side,
                    sl_quantity=group.sl_quantity,
                    sl_price=group.sl_price,
                    tp_quantity=group.tp_quantity,
                    tp_price=group.tp_price,
                    status="cancelled",
                    created_at=group.created_at,
                )
                break

        return await self._engine.cancel_order(order_id)

    async def modify_order(
        self,
        order_id: str,
        new_quantity: float | None = None,
        new_price: float | None = None,
        new_stop_price: float | None = None,
    ) -> PlacementResult:
        """Modify an existing order's parameters.

        Cancel-and-replace strategy: cancels the existing order and
        places a new one with updated parameters. Preserves the
        original order's unfilled portion.

        Args:
            order_id: Order ID to modify.
            new_price: New limit price (None = keep original).
            new_quantity: New quantity (None = keep original).
            new_stop_price: New stop price (None = keep original).

        Returns:
            PlacementResult for the replacement order.
        """
        # Get current order status to extract original parameters
        status = await self._engine.get_order_status(order_id)
        if status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            raise ValueError(f"Cannot modify order {order_id} — status is {status.value}")

        # Get open orders to find the original
        open_orders = await self._engine.get_open_orders("")
        original = None
        for o in open_orders:
            if o.order_id == order_id:
                original = o
                break

        if original is None:
            raise ValueError(f"Order {order_id} not found in open orders")

        # Cancel the original
        await self._engine.cancel_order(order_id)

        # Place replacement with updated parameters
        return await self._place_order(
            symbol=original.symbol,
            side=original.side.value,
            order_type=original.order_type.value,
            quantity=new_quantity if new_quantity is not None else original.quantity,
            price=new_price if new_price is not None else original.price,
            stop_price=(new_stop_price if new_stop_price is not None else original.stop_price),
        )

    async def replace_order(
        self,
        order_id: str,
        new_symbol: str | None = None,
        new_side: str | None = None,
        new_order_type: str | None = None,
        new_quantity: float | None = None,
        new_price: float | None = None,
        new_stop_price: float | None = None,
    ) -> PlacementResult:
        """Replace an order with a completely new one.

        More flexible than modify_order — can change symbol, side,
        and order type as well as price and quantity.

        Args:
            order_id: Order ID to replace.
            new_symbol: New trading pair (None = keep original).
            new_side: New side (None = keep original).
            new_order_type: New order type (None = keep original).
            new_quantity: New quantity (None = keep original).
            new_price: New price (None = keep original).
            new_stop_price: New stop price (None = keep original).

        Returns:
            PlacementResult for the new order.
        """
        open_orders = await self._engine.get_open_orders("")
        original = None
        for o in open_orders:
            if o.order_id == order_id:
                original = o
                break

        if original is None:
            raise ValueError(f"Order {order_id} not found in open orders")

        await self._engine.cancel_order(order_id)

        return await self._place_order(
            symbol=new_symbol or original.symbol,
            side=new_side or original.side.value,
            order_type=new_order_type or original.order_type.value,
            quantity=new_quantity if new_quantity is not None else original.quantity,
            price=new_price if new_price is not None else original.price,
            stop_price=(new_stop_price if new_stop_price is not None else original.stop_price),
        )

    # ── 3. OCO Orders ──────────────────────────────────────────────

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss_price: float,
        take_profit_price: float,
        entry_order_id: str = "",
    ) -> OCOGroup:
        """Place a One-Cancels-Other order group.

        Links a stop-loss and take-profit order. When either fills,
        the other is automatically cancelled. Essential for risk-managed
        position management.

        The stop-loss is placed as a stop-market order and the
        take-profit as a limit order. Both are for the full quantity.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: Exit side — "sell" for long positions, "buy" for short.
            quantity: Quantity for both orders (typically position size).
            stop_loss_price: Stop-loss trigger price.
            take_profit_price: Take-profit limit price.
            entry_order_id: ID of the entry order this OCO protects.

        Returns:
            OCOGroup with both order IDs and tracking status.
        """
        # Place stop-loss order
        sl_result = await self._place_order(
            symbol=symbol,
            side=side,
            order_type="stop_market",
            quantity=quantity,
            stop_price=stop_loss_price,
        )

        # Place take-profit order
        tp_result = await self._place_order(
            symbol=symbol,
            side=side,
            order_type="limit",
            quantity=quantity,
            price=take_profit_price,
        )

        group_id = f"OCO-{uuid.uuid4().hex[:8]}"
        group = OCOGroup(
            group_id=group_id,
            entry_order_id=entry_order_id,
            sl_order_id=sl_result.order_id,
            tp_order_id=tp_result.order_id,
            symbol=symbol,
            side=side,
            sl_quantity=quantity,
            sl_price=stop_loss_price,
            tp_quantity=quantity,
            tp_price=take_profit_price,
            status="active",
            created_at=_utcnow(),
        )

        self._oco_groups[group_id] = group

        logger.info(
            "OCO group %s created: SL=%s @ %.2f, TP=%s @ %.2f",
            group_id,
            sl_result.order_id,
            stop_loss_price,
            tp_result.order_id,
            take_profit_price,
        )

        return group

    async def check_oco_status(self, group_id: str) -> OCOGroup | None:
        """Check the status of an OCO group.

        Polls both orders and updates the group status if one has filled.

        Args:
            group_id: OCO group identifier.

        Returns:
            Updated OCOGroup or None if not found.
        """
        group = self._oco_groups.get(group_id)
        if group is None or group.status != "active":
            return group

        try:
            sl_status = await self._engine.get_order_status(group.sl_order_id)
            tp_status = await self._engine.get_order_status(group.tp_order_id)
        except Exception:
            return group

        # Check if either leg filled
        if sl_status == OrderStatus.FILLED:
            # Cancel the TP leg
            try:
                await self._engine.cancel_order(group.tp_order_id)
            except Exception as exc:
                logger.warning("Failed to cancel TP after SL fill: %s", exc)

            group = OCOGroup(
                group_id=group.group_id,
                entry_order_id=group.entry_order_id,
                sl_order_id=group.sl_order_id,
                tp_order_id=group.tp_order_id,
                symbol=group.symbol,
                side=group.side,
                sl_quantity=group.sl_quantity,
                sl_price=group.sl_price,
                tp_quantity=group.tp_quantity,
                tp_price=group.tp_price,
                status="sl_filled",
                created_at=group.created_at,
            )
            self._oco_groups[group_id] = group

        elif tp_status == OrderStatus.FILLED:
            # Cancel the SL leg
            try:
                await self._engine.cancel_order(group.sl_order_id)
            except Exception as exc:
                logger.warning("Failed to cancel SL after TP fill: %s", exc)

            group = OCOGroup(
                group_id=group.group_id,
                entry_order_id=group.entry_order_id,
                sl_order_id=group.sl_order_id,
                tp_order_id=group.tp_order_id,
                symbol=group.symbol,
                side=group.side,
                sl_quantity=group.sl_quantity,
                sl_price=group.sl_price,
                tp_quantity=group.tp_quantity,
                tp_price=group.tp_price,
                status="tp_filled",
                created_at=group.created_at,
            )
            self._oco_groups[group_id] = group

        return group

    async def get_active_oco_groups(self) -> list[OCOGroup]:
        """Get all active OCO groups.

        Returns:
            List of active OCOGroup objects.
        """
        return [g for g in self._oco_groups.values() if g.status == "active"]

    # ── 4. Slippage Tracker ─────────────────────────────────────────

    def record_slippage(
        self,
        order_id: str,
        symbol: str,
        side: str,
        expected_price: float,
        actual_price: float,
        quantity: float,
    ) -> SlippageReport:
        """Record slippage for a completed trade.

        Called after each fill to build the slippage history.
        Slippage = (actual - expected) / expected * 10_000 bps.
        Positive slippage is adverse (bought higher / sold lower).

        Args:
            order_id: Order identifier.
            symbol: Trading pair.
            side: "buy" or "sell".
            expected_price: Price at order submission (mid or limit).
            actual_price: Actual volume-weighted average fill price.
            quantity: Filled quantity.

        Returns:
            SlippageReport for this trade.
        """
        if expected_price > 0:
            raw_slippage = (actual_price - expected_price) / expected_price
            if side == "sell":
                raw_slippage = -raw_slippage  # Flip for sells
            slippage_bps = raw_slippage * 10_000
        else:
            slippage_bps = 0.0

        slippage_usd = abs(actual_price - expected_price) * quantity

        report = SlippageReport(
            order_id=order_id,
            symbol=symbol,
            side=side,
            expected_price=expected_price,
            actual_price=actual_price,
            slippage_bps=round(slippage_bps, 4),
            slippage_usd=round(slippage_usd, 4),
            quantity=quantity,
            timestamp=_utcnow(),
        )

        self._slippage_history.append(report)
        return report

    def get_slippage_stats(
        self,
        symbol: str | None = None,
        last_n: int | None = None,
    ) -> SlippageStats:
        """Get aggregated slippage statistics.

        Computes average, median, max slippage and breakdowns by
        symbol and hour of day. Useful for execution quality
        monitoring and strategy optimization.

        Args:
            symbol: Filter by symbol (None = all symbols).
            last_n: Only consider last N trades (None = all).

        Returns:
            SlippageStats with full breakdown.
        """
        history = self._slippage_history
        if symbol:
            history = [r for r in history if r.symbol == symbol]
        if last_n:
            history = history[-last_n:]

        if not history:
            return SlippageStats(symbol=symbol)

        abs_slippages = [abs(r.slippage_bps) for r in history]
        usd_costs = [r.slippage_usd for r in history]

        # Per-symbol breakdown
        by_symbol: dict[str, list[float]] = defaultdict(list)
        for r in history:
            by_symbol[r.symbol].append(abs(r.slippage_bps))

        # Per-hour breakdown
        by_hour: dict[int, list[float]] = defaultdict(list)
        for r in history:
            if r.timestamp:
                by_hour[r.timestamp.hour].append(abs(r.slippage_bps))

        return SlippageStats(
            symbol=symbol,
            total_trades=len(history),
            avg_slippage_bps=round(float(np.mean(abs_slippages)), 4),
            median_slippage_bps=round(float(np.median(abs_slippages)), 4),
            max_slippage_bps=round(float(np.max(abs_slippages)), 4),
            total_slippage_usd=round(sum(usd_costs), 4),
            slippage_by_hour={h: round(float(np.mean(v)), 4) for h, v in sorted(by_hour.items())},
            slippage_by_symbol={s: round(float(np.mean(v)), 4) for s, v in by_symbol.items()},
        )

    # ── 5. Fill Quality Analyzer ────────────────────────────────────

    async def analyze_fill_quality(self, order_id: str) -> FillQualityReport:
        """Analyze the fill quality of a completed order.

        Examines fill rate, number of partial fills, time to fill,
        price variance across fills, and price improvement vs limit.
        Used for execution quality benchmarking.

        Args:
            order_id: Order ID to analyze.

        Returns:
            FillQualityReport with comprehensive fill metrics.
        """
        fills = await self._engine.get_fills(order_id)

        if not fills:
            return FillQualityReport(
                order_id=order_id,
                symbol="",
                side="",
                order_type="",
                requested_quantity=0,
                filled_quantity=0,
                fill_rate=0,
                num_fills=0,
                is_partial=True,
                time_to_fill_ms=0,
                avg_fill_size=0,
                fill_price_variance=0,
                average_fill_price=0,
                best_fill_price=0,
                worst_fill_price=0,
                timestamp=_utcnow(),
            )

        # Get order details from open orders or history
        open_orders = await self._engine.get_open_orders(fills[0].symbol)
        original_order = None
        for o in open_orders:
            if o.order_id == order_id:
                original_order = o
                break

        # Calculate metrics
        fill_prices = [f.price for f in fills]
        fill_quantities = [f.quantity for f in fills]
        total_filled = sum(fill_quantities)

        requested_qty = original_order.quantity if original_order else total_filled
        fill_rate = total_filled / requested_qty if requested_qty > 0 else 0.0

        # Volume-weighted average price
        total_cost = sum(p * q for p, q in zip(fill_prices, fill_quantities, strict=False))
        avg_price = total_cost / total_filled if total_filled > 0 else 0.0

        # Price variance
        price_variance = float(np.var(fill_prices)) if len(fill_prices) > 1 else 0.0

        # Time to fill
        placement_time = self._order_timestamps.get(order_id)
        if placement_time and fills:
            last_fill_time = max(f.timestamp for f in fills if f.timestamp)
            time_to_fill = (last_fill_time - placement_time).total_seconds() * 1000
        else:
            time_to_fill = 0.0

        # Price improvement (for limit orders)
        price_improvement = 0.0
        if original_order and original_order.price:
            if original_order.side == OrderSide.BUY:
                # For buys, lower is better
                price_improvement = (
                    (original_order.price - avg_price) / original_order.price * 10_000
                )
            else:
                # For sells, higher is better
                price_improvement = (
                    (avg_price - original_order.price) / original_order.price * 10_000
                )

        return FillQualityReport(
            order_id=order_id,
            symbol=fills[0].symbol,
            side=fills[0].side.value,
            order_type=original_order.order_type.value if original_order else "unknown",
            requested_quantity=requested_qty,
            filled_quantity=round(total_filled, 8),
            fill_rate=round(fill_rate, 4),
            num_fills=len(fills),
            is_partial=fill_rate < 1.0,
            time_to_fill_ms=round(time_to_fill, 2),
            avg_fill_size=round(total_filled / len(fills), 8) if fills else 0,
            fill_price_variance=round(price_variance, 8),
            average_fill_price=round(avg_price, 8),
            best_fill_price=round(min(fill_prices), 8) if fill_prices else 0,
            worst_fill_price=round(max(fill_prices), 8) if fill_prices else 0,
            price_improvement_bps=round(price_improvement, 4),
            timestamp=_utcnow(),
        )

    async def get_fill_quality_summary(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get aggregate fill quality metrics across multiple orders.

        Args:
            symbol: Filter by symbol (None = all).
            limit: Maximum orders to analyze.

        Returns:
            Dict with aggregate fill quality metrics.
        """
        # Collect order IDs from history
        order_ids = []
        for result in (
            self._engine._order_history if hasattr(self._engine, "_order_history") else []
        ):
            if symbol and result.symbol != symbol:
                continue
            order_ids.append(result.order_id)
            if len(order_ids) >= limit:
                break

        reports = []
        for oid in order_ids[-limit:]:
            try:
                report = await self.analyze_fill_quality(oid)
                if report.filled_quantity > 0:
                    reports.append(report)
            except Exception:
                continue

        if not reports:
            return {
                "total_orders": 0,
                "avg_fill_rate": 0,
                "avg_fills_per_order": 0,
                "avg_time_to_fill_ms": 0,
                "partial_fill_rate": 0,
            }

        return {
            "total_orders": len(reports),
            "avg_fill_rate": round(float(np.mean([r.fill_rate for r in reports])), 4),
            "avg_fills_per_order": round(float(np.mean([r.num_fills for r in reports])), 2),
            "avg_time_to_fill_ms": round(float(np.mean([r.time_to_fill_ms for r in reports])), 2),
            "partial_fill_rate": round(sum(1 for r in reports if r.is_partial) / len(reports), 4),
            "avg_price_improvement_bps": round(
                float(np.mean([r.price_improvement_bps for r in reports])), 4
            ),
        }

    # ── Internal Helpers ────────────────────────────────────────────

    async def _place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "gtc",
    ) -> PlacementResult:
        """Internal order placement method.

        Builds an Order object and delegates to the ExecutionEngine.
        Records timing for fill quality analysis.

        Includes Freqtrade-hardened pre-flight checks:
        - Exchange limit validation (min amount, min cost)
        - Precision adjustment via gateway
        """
        # ── Exchange Hardening: Pre-flight validation ──────────────
        # Check exchange limits before building the Order
        if hasattr(self._gateway, "validate_order_limits"):
            is_valid, err_msg = self._gateway.validate_order_limits(symbol, side, quantity, price)
            if not is_valid:
                raise ValueError(f"Order rejected by exchange limits: {err_msg}")

        # Apply precision via gateway if available
        if hasattr(self._gateway, "amount_to_precision"):
            quantity = self._gateway.amount_to_precision(symbol, quantity)
        if price is not None and hasattr(self._gateway, "price_to_precision"):
            price = self._gateway.price_to_precision(symbol, price)
        if stop_price is not None and hasattr(self._gateway, "price_to_precision"):
            stop_price = self._gateway.price_to_precision(symbol, stop_price)

        # Map string args to enums
        side_enum = OrderSide(side.lower())
        type_enum = OrderType(order_type.lower())
        TimeInForce(time_in_force.lower())

        order = OrderType_Order(
            order_id="",  # Assigned by engine
            symbol=symbol,
            side=side_enum,
            order_type=type_enum,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
        )

        # Record placement time
        placement_time = _utcnow()
        self._order_timestamps[order.order_id] = placement_time

        result = await self._engine.execute_order(order)

        # Record slippage if we have an expected price
        expected_price = price or 0.0
        if result.average_price > 0 and expected_price > 0:
            self.record_slippage(
                order_id=result.order_id,
                symbol=symbol,
                side=side,
                expected_price=expected_price,
                actual_price=result.average_price,
                quantity=result.filled_quantity,
            )

        return PlacementResult(
            order_id=result.order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=result.status.value,
            filled_quantity=result.filled_quantity,
            average_price=result.average_price,
            slippage_bps=result.slippage_bps,
            total_fee=result.total_fee,
            timestamp=placement_time,
        )
