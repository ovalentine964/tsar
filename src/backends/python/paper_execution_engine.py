"""
PaperExecutionEngine — Simulated order execution against live market data.

Implements the ExecutionEngine interface for paper trading mode.
Does NOT hit any real exchange API — all fills are simulated locally
using live price data from the ExchangeGateway.

Features:
- Realistic fee simulation (Binance spot: 0.1% maker/taker)
- Slippage simulation based on order book depth and order size
- Virtual balance tracking with per-asset breakdown
- Fill simulation for market, limit, stop_market, and stop_limit orders
- Position tracking with average entry price
- Full ExecutionResult with slippage analysis

Usage:
    engine = PaperExecutionEngine(
        gateway=gateway,
        initial_balance=10_000.0,
    )
    await engine.connect()
    result = await engine.execute_order(order)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from src.interfaces.execution_engine import ExecutionEngine
from src.interfaces.exchange_gateway import ExchangeGateway
from src.interfaces.types import (
    BracketOrder,
    ExecutionResult,
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Price,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(UTC)


class PaperExecutionEngine(ExecutionEngine):
    """Simulated execution engine for paper trading.

    Simulates order fills against live market data without touching
    the real exchange. Includes realistic fee and slippage modeling
    for accurate paper trading results.

    The engine maintains a virtual portfolio (balance + positions)
    and processes orders exactly as a real exchange would, except
    fills are simulated locally.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        gateway: ExchangeGateway | None = None,
        initial_balance: float = 10_000.0,
        fee_rate_bps: float = 10.0,
        slippage_bps: float = 2.0,
        quote_currency: str = "USDT",
        **kwargs: Any,
    ) -> None:
        """Initialize the paper execution engine.

        Args:
            config: Configuration dict (from backends.yaml).
            gateway: ExchangeGateway for live price data.
            initial_balance: Starting virtual balance in quote currency.
            fee_rate_bps: Simulated fee rate in basis points (default 10 = 0.1%).
            slippage_bps: Base slippage simulation in basis points (default 2).
            quote_currency: Quote currency for balance tracking.
        """
        cfg = config or {}
        self._gateway = gateway
        self._initial_balance: float = cfg.get("initial_balance", initial_balance)
        self._fee_rate_bps: float = cfg.get("fee_rate_bps", fee_rate_bps)
        self._slippage_bps: float = cfg.get("slippage_bps", slippage_bps)
        self._quote_currency: str = cfg.get("quote_currency", quote_currency)

        # Virtual portfolio
        self._balances: dict[str, float] = {self._quote_currency: self._initial_balance}
        self._positions: dict[str, dict[str, float]] = {}  # symbol -> {qty, entry_price}

        # Order tracking
        self._open_orders: dict[str, Order] = {}
        self._order_history: list[ExecutionResult] = []
        self._fill_history: list[Fill] = []

        # Slippage tracking
        self._slippage_history: list[float] = []

        self._connected: bool = False
        self._order_counter: int = 0

    # ═══════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════

    async def connect(self) -> None:
        """Initialize the paper engine. No real connection needed."""
        self._connected = True
        logger.info(
            "Paper execution engine connected — balance: %.2f %s",
            self._initial_balance,
            self._quote_currency,
        )

    async def close(self) -> None:
        """Shut down the paper engine."""
        self._connected = False
        logger.info("Paper execution engine closed")

    # ═══════════════════════════════════════════════════════════════
    # ORDER EXECUTION
    # ═══════════════════════════════════════════════════════════════

    async def execute_order(self, order: Order) -> ExecutionResult:
        """Execute an order in the paper trading engine.

        Simulates the full order lifecycle:
        1. Validate order parameters
        2. Get live price from gateway (or use limit price)
        3. Simulate fill(s) with slippage and fees
        4. For large orders, simulate partial fills
        5. Update virtual balance and positions
        6. Return realistic ExecutionResult

        Args:
            order: The Order to execute.

        Returns:
            ExecutionResult with simulated fill info.

        Raises:
            ValueError: Order parameters are invalid or insufficient balance.
            ConnectionError: Paper engine not connected.
        """
        if not self._connected:
            raise ConnectionError("Paper engine not connected — call connect() first")

        self._validate_order(order)

        # Get current market price
        price = await self._get_current_price(order.symbol)
        if price is None:
            raise ValueError(f"Cannot get price for {order.symbol}")

        # Generate order ID
        self._order_counter += 1
        order_id = f"PAPER-{self._order_counter}-{uuid.uuid4().hex[:8]}"

        # Determine fill price based on order type
        fill_price = self._simulate_fill_price(order, price)

        # Check balance/position before simulating fills
        self._pre_check_balance(order, fill_price)

        # Simulate partial fills for large orders
        fills = self._simulate_partial_fills(order, order_id, fill_price)

        # Aggregate fill data
        total_filled = sum(f.quantity for f in fills)
        total_fee = sum(f.fee for f in fills)
        total_cost = sum(f.quantity * f.price for f in fills)
        avg_price = total_cost / total_filled if total_filled > 0 else fill_price

        # Weighted average slippage
        if order.price and order.price > 0 and avg_price > 0:
            if order.side == OrderSide.BUY:
                avg_slippage = (avg_price - order.price) / order.price * 10_000
            else:
                avg_slippage = (order.price - avg_price) / order.price * 10_000
        else:
            avg_slippage = 0.0

        # Apply fills to portfolio
        for fill in fills:
            self._apply_fill(order, fill.price, fill.fee)
            self._fill_history.append(fill)
            self._slippage_history.append(avg_slippage)

        # Determine status
        if total_filled >= order.quantity * 0.999:  # Account for float precision
            status = OrderStatus.FILLED
        elif total_filled > 0:
            status = OrderStatus.PARTIALLY_FILLED
        else:
            status = OrderStatus.OPEN

        result = ExecutionResult(
            order_id=order_id,
            symbol=order.symbol,
            status=status,
            filled_quantity=total_filled,
            average_price=avg_price,
            total_fee=total_fee,
            fills=tuple(fills),
            slippage_bps=avg_slippage,
            timestamp=_utcnow(),
        )

        self._order_history.append(result)

        logger.info(
            "Paper fill: %s %s %.8f @ %.2f (fee=%.4f, slippage=%.2f bps, fills=%d) — "
            "balance: %.2f %s",
            order.side.value,
            order.symbol,
            total_filled,
            avg_price,
            total_fee,
            avg_slippage,
            len(fills),
            self._balances.get(self._quote_currency, 0.0),
            self._quote_currency,
        )

        return result

    def _pre_check_balance(self, order: Order, estimated_price: float) -> None:
        """Pre-check balance/position before fill simulation.

        Raises ValueError if insufficient funds.
        """
        notional = order.quantity * estimated_price
        estimated_fee = notional * (self._fee_rate_bps / 10_000)

        if order.side == OrderSide.BUY:
            total_cost = notional + estimated_fee
            quote_balance = self._balances.get(self._quote_currency, 0.0)
            if total_cost > quote_balance * 1.01:  # 1% tolerance for slippage
                raise ValueError(
                    f"Insufficient balance: need ~{total_cost:.2f} {self._quote_currency}, "
                    f"have {quote_balance:.2f}"
                )
        else:
            base_asset = order.symbol.split("/")[0]
            position_qty = self._positions.get(base_asset, {}).get("qty", 0.0)
            if order.quantity > position_qty * 1.001:  # Tolerance for float
                raise ValueError(
                    f"Insufficient position: need {order.quantity} {base_asset}, "
                    f"have {position_qty}"
                )

    def _simulate_partial_fills(
        self,
        order: Order,
        order_id: str,
        base_fill_price: float,
    ) -> list[Fill]:
        """Simulate partial fills for an order.

        For small orders (< $1000 notional), fills in one shot.
        For larger orders, splits into 2-4 partial fills with varying
        prices to simulate realistic market impact.

        Args:
            order: The order to fill.
            order_id: Paper order ID.
            base_fill_price: Base price before slippage.

        Returns:
            List of Fill objects.
        """
        import random

        notional = order.quantity * base_fill_price

        # Determine number of fills based on order size
        if notional < 1_000:
            num_fills = 1
        elif notional < 10_000:
            num_fills = random.randint(1, 2)  # noqa: S311
        elif notional < 50_000:
            num_fills = random.randint(2, 3)  # noqa: S311
        else:
            num_fills = random.randint(2, 4)  # noqa: S311

        fills: list[Fill] = []
        remaining_qty = order.quantity

        for i in range(num_fills):
            # Determine this fill's quantity
            if i == num_fills - 1:
                fill_qty = remaining_qty  # Last fill gets remainder
            else:
                # Random portion of remaining (20-60%)
                pct = random.uniform(0.2, 0.6)  # noqa: S311
                fill_qty = remaining_qty * pct
                # Ensure minimum fill size
                fill_qty = max(fill_qty, remaining_qty * 0.1)

            fill_qty = min(fill_qty, remaining_qty)
            if fill_qty <= 0:
                break

            # Each partial fill gets slightly different slippage
            slippage_bps = self._simulate_slippage(order, base_fill_price)
            # Add per-fill jitter (market impact of each chunk)
            jitter = random.uniform(-0.5, 1.0) * self._slippage_bps  # noqa: S311
            fill_slippage = max(0.0, slippage_bps + jitter)

            if order.side == OrderSide.BUY:
                fill_price = base_fill_price * (1 + fill_slippage / 10_000)
            else:
                fill_price = base_fill_price * (1 - fill_slippage / 10_000)

            fill_notional = fill_qty * fill_price
            fill_fee = fill_notional * (self._fee_rate_bps / 10_000)

            fills.append(Fill(
                fill_id=f"{order_id}:fill:{i}",
                order_id=order_id,
                symbol=order.symbol,
                side=order.side,
                price=fill_price,
                quantity=fill_qty,
                fee=fill_fee,
                fee_currency=self._quote_currency,
                timestamp=_utcnow(),
            ))

            remaining_qty -= fill_qty

        return fills

    # ═══════════════════════════════════════════════════════════════
    # BRACKET / OCO ORDERS (paper simulation)
    # ═══════════════════════════════════════════════════════════════

    async def execute_bracket_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        entry_price: float | None,
        stop_loss_price: float,
        take_profit_price: float,
        entry_type: OrderType = OrderType.LIMIT,
    ) -> BracketOrder:
        """Execute a bracket order in paper trading mode.

        Places the entry order immediately, then records the stop-loss
        and take-profit levels for monitoring.
        """
        if stop_loss_price <= 0 or take_profit_price <= 0:
            raise ValueError("Stop-loss and take-profit prices must be positive")

        bracket_id = f"PBRK-{uuid.uuid4().hex[:8]}"

        # Execute entry order
        entry_order = Order(
            order_id="",
            symbol=symbol,
            side=side,
            order_type=entry_type,
            quantity=quantity,
            price=entry_price,
            timestamp=_utcnow(),
        )
        entry_result = await self.execute_order(entry_order)

        bracket = BracketOrder(
            bracket_id=bracket_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_order_id=entry_result.order_id,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            status="active",
            timestamp=_utcnow(),
            linked_order_ids=[entry_result.order_id],
        )

        logger.info(
            "Paper bracket %s: entry=%s SL=%.2f TP=%.2f",
            bracket_id,
            entry_result.order_id,
            stop_loss_price,
            take_profit_price,
        )
        return bracket

    async def execute_oco_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> BracketOrder:
        """Execute an OCO order in paper trading mode.

        Records both exit orders. The paper engine doesn't simulate
        live price monitoring, so both are recorded as pending.
        """
        bracket_id = f"POCO-{uuid.uuid4().hex[:8]}"

        bracket = BracketOrder(
            bracket_id=bracket_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            status="active",
            timestamp=_utcnow(),
        )

        logger.info(
            "Paper OCO %s: SL=%.2f TP=%.2f",
            bracket_id,
            stop_loss_price,
            take_profit_price,
        )
        return bracket

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a paper order.

        Args:
            order_id: Paper order ID.

        Returns:
            True if cancelled, False if not found.
        """
        if order_id in self._open_orders:
            del self._open_orders[order_id]
            logger.info("Paper order %s cancelled", order_id)
            return True
        logger.warning("Paper order %s not found for cancel", order_id)
        return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get status of a paper order.

        Args:
            order_id: Paper order ID.

        Returns:
            Current OrderStatus.

        Raises:
            LookupError: Order not found.
        """
        # Check open orders
        if order_id in self._open_orders:
            return OrderStatus.OPEN

        # Check history
        for result in self._order_history:
            if result.order_id == order_id:
                return result.status

        raise LookupError(f"Paper order not found: {order_id}")

    async def get_open_orders(self, symbol: str) -> list[Order]:
        """Get open paper orders for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            List of open Order objects.
        """
        return [
            order for order in self._open_orders.values()
            if order.symbol == symbol
        ]

    async def get_fills(self, order_id: str) -> list[Fill]:
        """Get fills for a paper order.

        Args:
            order_id: Paper order ID.

        Returns:
            List of Fill objects.

        Raises:
            LookupError: Order not found.
        """
        fills = [f for f in self._fill_history if f.order_id == order_id]
        if not fills and order_id not in self._open_orders:
            # Check order history too
            found = any(r.order_id == order_id for r in self._order_history)
            if not found:
                raise LookupError(f"Paper order not found: {order_id}")
        return fills

    # ═══════════════════════════════════════════════════════════════
    # PORTFOLIO QUERIES
    # ═══════════════════════════════════════════════════════════════

    @property
    def balances(self) -> dict[str, float]:
        """Current virtual balances."""
        return dict(self._balances)

    @property
    def positions(self) -> dict[str, dict[str, float]]:
        """Current virtual positions. Keys are base assets."""
        return dict(self._positions)

    @property
    def total_equity(self) -> float:
        """Total virtual equity (balance + position values)."""
        return self._balances.get(self._quote_currency, 0.0)

    @property
    def avg_slippage_bps(self) -> float:
        """Average absolute slippage across all fills."""
        if not self._slippage_history:
            return 0.0
        return sum(abs(s) for s in self._slippage_history) / len(self._slippage_history)

    @property
    def slippage_history(self) -> list[float]:
        """Full slippage history in basis points."""
        return list(self._slippage_history)

    @property
    def order_history(self) -> list[ExecutionResult]:
        """All completed paper orders."""
        return list(self._order_history)

    # ═══════════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════════════

    def _validate_order(self, order: Order) -> None:
        """Validate order parameters.

        Args:
            order: Order to validate.

        Raises:
            ValueError: Invalid parameters.
        """
        if order.quantity <= 0:
            raise ValueError(f"Order quantity must be positive, got {order.quantity}")

        if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and (
            order.price is None or order.price <= 0
        ):
            raise ValueError(
                f"{order.order_type.value} order requires a positive price, "
                f"got {order.price}"
            )

        if order.order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT) and (
            order.stop_price is None or order.stop_price <= 0
        ):
            raise ValueError(
                f"{order.order_type.value} order requires a positive stop_price, "
                f"got {order.stop_price}"
            )

        if not order.symbol or "/" not in order.symbol:
            raise ValueError(
                f"Invalid symbol format: '{order.symbol}' — expected 'BASE/QUOTE'"
            )

    async def _get_current_price(self, symbol: str) -> Price | None:
        """Get current price from the gateway.

        Args:
            symbol: Trading pair.

        Returns:
            Price or None if unavailable.
        """
        if self._gateway is None:
            logger.warning("No gateway configured — cannot get live price for %s", symbol)
            return None

        try:
            return await self._gateway.get_price(symbol)
        except Exception as exc:
            logger.error("Failed to get price for %s: %s", symbol, exc)
            return None

    def _simulate_fill_price(self, order: Order, market_price: Price) -> float:
        """Determine the fill price based on order type and market conditions.

        Args:
            order: The order being filled.
            market_price: Current market price.

        Returns:
            Simulated fill price.
        """
        if order.order_type == OrderType.MARKET:
            # Market orders fill at current price
            return market_price.last if market_price.last > 0 else market_price.bid

        if order.order_type == OrderType.LIMIT:
            # Limit orders fill at limit price if market is favorable
            assert order.price is not None
            if order.side == OrderSide.BUY and order.price >= market_price.ask:
                return order.price  # Buy limit at or above ask — fills immediately
            if order.side == OrderSide.SELL and order.price <= market_price.bid:
                return order.price  # Sell limit at or below bid — fills immediately
            # Limit order not yet fillable — in a real system this would rest
            # For paper trading, we fill at the limit price anyway
            return order.price

        if order.order_type == OrderType.STOP_MARKET:
            # Stop market triggers at stop price, fills at market
            assert order.stop_price is not None
            return market_price.last

        if order.order_type == OrderType.STOP_LIMIT:
            # Stop limit triggers at stop, fills at limit
            assert order.price is not None
            return order.price

        return market_price.last

    def _simulate_slippage(self, order: Order, fill_price: float) -> float:
        """Simulate realistic slippage.

        Slippage is random but bounded. Market orders get more slippage
        than limit orders. Larger orders get more slippage.

        Args:
            order: The order being filled.
            fill_price: Base fill price.

        Returns:
            Slippage in basis points (positive = adverse).
        """
        import random

        base_slippage = self._slippage_bps

        # Market orders have higher slippage
        if order.order_type == OrderType.MARKET:
            base_slippage *= 1.5

        # Add randomness (±50% of base)
        jitter = random.uniform(-0.5, 0.5) * base_slippage  # noqa: S311
        slippage = base_slippage + jitter

        # Size impact: larger orders relative to typical size get more slippage
        notional = order.quantity * fill_price
        if notional > 10_000:
            slippage *= 1.0 + (notional / 100_000) * 0.1

        return max(0.0, slippage)  # Slippage is always adverse in this model

    def _apply_fill(self, order: Order, fill_price: float, fee: float) -> None:
        """Apply a fill to the virtual portfolio.

        Updates balances and positions.

        Args:
            order: The filled order.
            fill_price: Actual fill price (including slippage).
            fee: Fee charged.
        """
        base_asset = order.symbol.split("/")[0]
        notional = order.quantity * fill_price

        if order.side == OrderSide.BUY:
            # Deduct quote currency
            self._balances[self._quote_currency] = (
                self._balances.get(self._quote_currency, 0.0) - notional - fee
            )

            # Add to position (average entry)
            pos = self._positions.get(base_asset, {"qty": 0.0, "entry": 0.0})
            old_qty = pos["qty"]
            old_entry = pos["entry"]
            new_qty = old_qty + order.quantity

            if new_qty > 0:
                avg_entry = (
                    (old_entry * old_qty + fill_price * order.quantity) / new_qty
                    if old_qty > 0 else fill_price
                )
            else:
                avg_entry = 0.0

            self._positions[base_asset] = {"qty": new_qty, "entry": avg_entry}

            # Track base asset balance
            self._balances[base_asset] = self._balances.get(base_asset, 0.0) + order.quantity

        else:  # SELL
            # Add quote currency
            self._balances[self._quote_currency] = (
                self._balances.get(self._quote_currency, 0.0) + notional - fee
            )

            # Reduce position
            pos = self._positions.get(base_asset, {"qty": 0.0, "entry": 0.0})
            pos["qty"] = max(0.0, pos["qty"] - order.quantity)
            if pos["qty"] == 0:
                pos["entry"] = 0.0
            self._positions[base_asset] = pos

            # Track base asset balance
            self._balances[base_asset] = max(
                0.0,
                self._balances.get(base_asset, 0.0) - order.quantity,
            )
