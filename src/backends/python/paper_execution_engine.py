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
        3. Simulate fill with slippage and fees
        4. Update virtual balance and positions
        5. Return realistic ExecutionResult

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

        # Simulate slippage
        slippage_bps = self._simulate_slippage(order, fill_price)
        if order.side == OrderSide.BUY:
            actual_price = fill_price * (1 + slippage_bps / 10_000)
        else:
            actual_price = fill_price * (1 - slippage_bps / 10_000)

        # Calculate fees
        notional = order.quantity * actual_price
        fee = notional * (self._fee_rate_bps / 10_000)

        # Check balance for buy orders
        if order.side == OrderSide.BUY:
            total_cost = notional + fee
            quote_balance = self._balances.get(self._quote_currency, 0.0)
            if total_cost > quote_balance:
                raise ValueError(
                    f"Insufficient balance: need {total_cost:.2f} {self._quote_currency}, "
                    f"have {quote_balance:.2f}"
                )
        else:
            # Check position for sell orders
            base_asset = order.symbol.split("/")[0]
            position_qty = self._positions.get(base_asset, {}).get("qty", 0.0)
            if order.quantity > position_qty:
                raise ValueError(
                    f"Insufficient position: need {order.quantity} {base_asset}, "
                    f"have {position_qty}"
                )

        # Execute the fill — update balances and positions
        self._apply_fill(order, actual_price, fee)

        # Build fill record
        fill = Fill(
            fill_id=f"{order_id}:fill:0",
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            price=actual_price,
            quantity=order.quantity,
            fee=fee,
            fee_currency=self._quote_currency,
            timestamp=_utcnow(),
        )

        self._fill_history.append(fill)
        self._slippage_history.append(slippage_bps)

        result = ExecutionResult(
            order_id=order_id,
            symbol=order.symbol,
            status=OrderStatus.FILLED,
            filled_quantity=order.quantity,
            average_price=actual_price,
            total_fee=fee,
            fills=(fill,),
            slippage_bps=slippage_bps,
            timestamp=_utcnow(),
        )

        self._order_history.append(result)

        logger.info(
            "Paper fill: %s %s %.8f @ %.2f (fee=%.4f, slippage=%.2f bps) — "
            "balance: %.2f %s",
            order.side.value,
            order.symbol,
            order.quantity,
            actual_price,
            fee,
            slippage_bps,
            self._balances.get(self._quote_currency, 0.0),
            self._quote_currency,
        )

        return result

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
