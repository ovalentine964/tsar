"""
CcxtExecEngine — Order execution engine via ccxt REST API.

Day1 implementation of ExecutionEngine. Delegates to the configured
ExchangeGateway for order placement, fill tracking, and slippage analysis.

Features:
- Full order lifecycle: place → fill → track → analyze
- Pre-execution order validation
- Slippage calculation and tracking
- Proper error handling with structured exceptions

Level 2: RustExecEngine (low-latency via PyO3)
Level 4: FixExecEngine (institutional FIX protocol)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import ccxt.async_support as ccxt
from ccxt import (
    DECIMAL_PLACES,
    ROUND,
    ROUND_DOWN,
    ROUND_UP,
    SIGNIFICANT_DIGITS,
    TICK_SIZE,
    TRUNCATE,
    decimal_to_precision,
)

from src.interfaces.execution_engine import ExecutionEngine
from src.interfaces.types import (
    BracketOrder,
    ExecutionResult,
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(UTC)


def _ts_to_dt(ts_ms: int | float | None) -> datetime:
    """Convert millisecond timestamp to timezone-aware datetime."""
    if ts_ms is None:
        return _utcnow()
    return datetime.fromtimestamp(float(ts_ms) / 1000, tz=UTC)


class CcxtExecEngine(ExecutionEngine):
    """Execution engine using ccxt REST API for order management.

    Handles the full order lifecycle:
    - Pre-execution validation (symbol, quantity, price, balance)
    - Order placement with proper ccxt parameter mapping
    - Fill tracking and aggregation
    - Slippage calculation vs expected price
    - Error handling with structured exceptions

    Uses its own ccxt connection (independent of the gateway) for
    clean separation of concerns. Can also accept an injected gateway.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        exchange_id: str = "binance",
        sandbox: bool = True,
        timeout_s: int = 15,
        api_key: str = "",
        api_secret: str = "",
        max_slippage_bps: float = 100.0,
        **kwargs: Any,
    ) -> None:
        cfg = config or {}
        self._exchange_id: str = cfg.get("exchange_id", exchange_id)
        self._sandbox: bool = cfg.get("sandbox", sandbox)
        self._timeout_s: int = cfg.get("timeout_s", timeout_s)
        self._api_key: str = cfg.get("api_key", api_key)
        self._api_secret: str = cfg.get("api_secret", api_secret)
        self._max_slippage_bps: float = cfg.get("max_slippage_bps", max_slippage_bps)

        self._exchange: ccxt.Exchange | None = None
        self._connected: bool = False
        self._markets_loaded: bool = False

        # Slippage tracking
        self._slippage_history: list[float] = []

        # OCO/Bracket order tracking (H-021)
        self._bracket_orders: dict[str, BracketOrder] = {}
        self._bracket_monitor_tasks: dict[str, asyncio.Task[None]] = {}

    # ═══════════════════════════════════════════════════════════════
    # CONNECTION MANAGEMENT

    async def _ensure_exchange(self) -> ccxt.Exchange:
        """Lazy-init the ccxt exchange connection."""
        if self._exchange is not None and self._connected:
            return self._exchange

        exchange_class = getattr(ccxt, self._exchange_id, None)
        if exchange_class is None:
            raise ConnectionError(f"Exchange '{self._exchange_id}' not found in ccxt")

        config: dict[str, Any] = {
            "enableRateLimit": True,
            "timeout": self._timeout_s * 1000,
        }
        if self._api_key:
            config["apiKey"] = self._api_key
            config["secret"] = self._api_secret

        self._exchange = exchange_class(config)

        if self._sandbox:
            self._exchange.set_sandbox_mode(True)

        if not self._markets_loaded:
            await self._exchange.load_markets()
            self._markets_loaded = True

        self._connected = True
        return self._exchange

    async def close(self) -> None:
        """Close the exchange connection."""
        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception as exc:
                logger.warning("Error closing exec engine exchange: %s", exc)
            finally:
                self._exchange = None
                self._connected = False

    # ═══════════════════════════════════════════════════════════════
    # ORDER VALIDATION
    # ═══════════════════════════════════════════════════════════════

    def _validate_order(self, order: Order) -> None:
        """Validate order parameters before execution.

        Checks:
        1. Basic parameter validation (quantity, price, symbol format)
        2. Exchange-level limits (min/max amount, min/max cost)
        3. Amount and price precision

        Args:
            order: The Order to validate.

        Raises:
            ValueError: If order parameters are invalid.
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

        # Exchange-level validation (requires loaded markets)
        if self._exchange is not None and self._markets_loaded:
            self._validate_exchange_limits(order)

    def _validate_exchange_limits(self, order: Order) -> None:
        """Validate order against exchange-enforced limits.

        Checks minimum/maximum amount and cost from market data.
        Mirrors Freqtrade's get_min_pair_stake_amount() pattern.

        Args:
            order: The Order to validate.

        Raises:
            ValueError: If order violates exchange limits.
        """
        assert self._exchange is not None
        market = self._exchange.markets.get(order.symbol)
        if market is None:
            return  # Can't validate without market data

        limits = market.get("limits", {})

        # Check amount limits
        min_amount = limits.get("amount", {}).get("min")
        if min_amount is not None and order.quantity < min_amount:
            raise ValueError(
                f"Order quantity {order.quantity} below exchange minimum "
                f"{min_amount} for {order.symbol}"
            )

        max_amount = limits.get("amount", {}).get("max")
        if max_amount is not None and order.quantity > max_amount:
            raise ValueError(
                f"Order quantity {order.quantity} above exchange maximum "
                f"{max_amount} for {order.symbol}"
            )

        # Check cost limits (requires price)
        price = order.price or order.stop_price
        if price is not None and price > 0:
            cost = order.quantity * price
            min_cost = limits.get("cost", {}).get("min")
            if min_cost is not None and cost < min_cost:
                raise ValueError(
                    f"Order cost {cost:.2f} below exchange minimum "
                    f"{min_cost} for {order.symbol}"
                )

            max_cost = limits.get("cost", {}).get("max")
            if max_cost is not None and cost > max_cost:
                raise ValueError(
                    f"Order cost {cost:.2f} above exchange maximum "
                    f"{max_cost} for {order.symbol}"
                )

    def _apply_precision(self, order: Order) -> Order:
        """Apply exchange precision to order amount and price.

        Truncates amount and rounds price to exchange-accepted precision.
        Creates a new Order with corrected values.

        Args:
            order: Original order.

        Returns:
            New Order with precision-adjusted values.
        """
        if self._exchange is None or not self._markets_loaded:
            return order

        market = self._exchange.markets.get(order.symbol)
        if market is None:
            return order

        precision = market.get("precision", {})
        amount_prec = precision.get("amount")
        price_prec = precision.get("price")
        prec_mode = self._exchange.precisionMode

        # Apply amount precision (truncate)
        new_quantity = order.quantity
        if amount_prec is not None and prec_mode is not None:
            prec = int(amount_prec) if prec_mode != TICK_SIZE else amount_prec
            new_quantity = float(
                decimal_to_precision(order.quantity, TRUNCATE, prec, prec_mode)
            )

        # Apply price precision (round)
        new_price = order.price
        if order.price is not None and price_prec is not None and prec_mode is not None:
            new_price = float(
                decimal_to_precision(
                    order.price,
                    ROUND,
                    int(price_prec) if prec_mode != TICK_SIZE else price_prec,
                    prec_mode,
                )
            )

        # Apply stop price precision
        new_stop_price = order.stop_price
        if order.stop_price is not None and price_prec is not None and prec_mode is not None:
            new_stop_price = float(
                decimal_to_precision(
                    order.stop_price,
                    ROUND,
                    int(price_prec) if prec_mode != TICK_SIZE else price_prec,
                    prec_mode,
                )
            )

        if (
            new_quantity == order.quantity
            and new_price == order.price
            and new_stop_price == order.stop_price
        ):
            return order

        logger.debug(
            "Precision adjusted %s: qty %.8f->%.8f, price %s->%s",
            order.symbol,
            order.quantity,
            new_quantity,
            order.price,
            new_price,
        )

        return Order(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=new_quantity,
            price=new_price,
            stop_price=new_stop_price,
            filled_quantity=order.filled_quantity,
            status=order.status,
            fee=order.fee,
            fee_currency=order.fee_currency,
            timestamp=order.timestamp,
        )

    # ═══════════════════════════════════════════════════════════════
    # ORDER EXECUTION
    # ═══════════════════════════════════════════════════════════════

    async def execute_order(self, order: Order) -> ExecutionResult:
        """Execute an order on the exchange.

        Full lifecycle: validate → place → track fills → calculate slippage.

        Args:
            order: The Order to execute.

        Returns:
            ExecutionResult with fill info, average price, and slippage.

        Raises:
            ValueError: Order parameters are invalid.
            ConnectionError: Not connected to the exchange.
            ccxt.InsufficientFunds: Not enough balance.
            ccxt.InvalidOrder: Exchange rejected the order.
        """
        # Pre-execution validation
        self._validate_order(order)

        # Apply exchange precision to amount/price (Freqtrade pattern)
        order = self._apply_precision(order)

        exchange = await self._ensure_exchange()

        # Map TSAR types to ccxt parameters
        ccxt_side = order.side.value  # "buy" or "sell"
        ccxt_type = self._map_order_type(order.order_type)

        params: dict[str, Any] = {}
        if order.order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT):
            params["stopPrice"] = order.stop_price

        logger.info(
            "Executing %s %s %s: qty=%.8f price=%s stop=%s",
            ccxt_side,
            ccxt_type,
            order.symbol,
            order.quantity,
            order.price,
            order.stop_price,
        )

        try:
            raw = await exchange.create_order(
                symbol=order.symbol,
                type=ccxt_type,
                side=ccxt_side,
                amount=order.quantity,
                price=order.price if ccxt_type == "limit" else None,
                params=params,
            )
        except ccxt.InsufficientFunds as exc:
            logger.error("Insufficient funds for %s order: %s", order.symbol, exc)
            raise
        except ccxt.InvalidOrder as exc:
            logger.error("Invalid order rejected by exchange: %s", exc)
            raise
        except ccxt.NetworkError as exc:
            logger.error("Network error placing order: %s", exc)
            raise ConnectionError(f"Network error: {exc}") from exc

        # Parse exchange response
        order_id = str(raw.get("id", ""))
        filled_qty = float(raw.get("filled", 0) or 0)
        avg_price = float(raw.get("average", 0) or 0)
        status = self._map_order_status(raw.get("status", ""))

        # Build fills from the response
        fills = self._extract_fills(raw, order_id, order.symbol, order.side)

        # Calculate total fee
        fee_info = raw.get("fee", {}) or {}
        total_fee = float(fee_info.get("cost", 0) or 0)

        # Calculate slippage if we have an expected price and fills
        slippage_bps = 0.0
        if order.price and order.price > 0 and avg_price > 0:
            slippage_bps = self._calc_slippage_bps(
                expected=order.price,
                actual=avg_price,
                side=order.side,
            )
            self._slippage_history.append(slippage_bps)
            if abs(slippage_bps) > self._max_slippage_bps:
                logger.warning(
                    "High slippage detected: %.2f bps (max: %.2f) for %s %s",
                    slippage_bps,
                    self._max_slippage_bps,
                    order.side.value,
                    order.symbol,
                )

        result = ExecutionResult(
            order_id=order_id,
            symbol=order.symbol,
            status=status,
            filled_quantity=filled_qty,
            average_price=avg_price,
            total_fee=total_fee,
            fills=tuple(fills),
            slippage_bps=slippage_bps,
            timestamp=_utcnow(),
        )

        logger.info(
            "Order %s executed: %s %s %s — status=%s filled=%.8f @ %.2f slippage=%.2f bps",
            order_id,
            order.side.value,
            order.quantity,
            order.symbol,
            status.value,
            filled_qty,
            avg_price,
            slippage_bps,
        )

        return result

    async def cancel_order(self, order_id: str, symbol: str | None = None) -> bool:
        """Cancel an open order.

        Args:
            order_id: Exchange-assigned order ID.
            symbol: Trading pair. If None, attempts to discover from open orders.

        Returns:
            True if cancelled successfully, False otherwise.

        Raises:
            OrderNotFoundError: Order does not exist on the exchange.
        """
        exchange = await self._ensure_exchange()

        # If symbol not provided, try to find it from open orders
        if symbol is None:
            try:
                # Try fetching the order across common symbols by checking open orders
                raw = await exchange.fetch_order(order_id, symbol=None)
                symbol = raw.get("symbol", "")
            except Exception:
                logger.warning(
                    "Cannot determine symbol for order %s — cancel requires symbol",
                    order_id,
                )
                return False

        try:
            await exchange.cancel_order(order_id, symbol=symbol)
            logger.info("Order %s cancelled", order_id)
            return True
        except ccxt.OrderNotFound as exc:
            logger.error("Order %s not found: %s", order_id, exc)
            raise LookupError(f"Order not found: {order_id}") from exc
        except ccxt.NetworkError as exc:
            logger.error("Network error cancelling order %s: %s", order_id, exc)
            return False
        except Exception as exc:
            logger.warning("Cancel failed for order %s: %s", order_id, exc)
            return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the current status of an order.

        Args:
            order_id: Exchange-assigned order ID.

        Returns:
            Current OrderStatus enum value.

        Raises:
            OrderNotFoundError: Order does not exist on the exchange.
        """
        exchange = await self._ensure_exchange()

        try:
            # fetch_order requires symbol on most exchanges.
            # Try fetching open orders first to find the symbol.
            raw = await exchange.fetch_order(order_id, symbol=None)
            return self._map_order_status(raw.get("status", ""))
        except ccxt.OrderNotFound as exc:
            raise LookupError(f"Order not found: {order_id}") from exc
        except ccxt.NetworkError as exc:
            raise ConnectionError(f"Network error: {exc}") from exc

    async def get_open_orders(self, symbol: str) -> list[Order]:
        """Get all open orders for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").

        Returns:
            List of open Order objects, sorted by timestamp descending.
        """
        exchange = await self._ensure_exchange()

        try:
            raw_orders = await exchange.fetch_open_orders(symbol)
        except ccxt.BadSymbol as exc:
            raise LookupError(f"Symbol not found: {symbol}") from exc
        except ccxt.NetworkError as exc:
            raise ConnectionError(f"Network error: {exc}") from exc

        orders: list[Order] = []
        for raw in raw_orders:
            order = Order(
                order_id=str(raw.get("id", "")),
                symbol=symbol,
                side=OrderSide.BUY if raw.get("side") == "buy" else OrderSide.SELL,
                order_type=self._parse_order_type(raw.get("type", "")),
                quantity=float(raw.get("amount", 0) or 0),
                price=float(raw.get("price", 0) or None) if raw.get("price") else None,
                stop_price=(
                    float(raw["stopPrice"])
                    if raw.get("stopPrice") else None
                ),
                filled_quantity=float(raw.get("filled", 0) or 0),
                status=OrderStatus.OPEN,
                fee=float((raw.get("fee", {}) or {}).get("cost", 0) or 0),
                fee_currency=(raw.get("fee", {}) or {}).get("currency", ""),
                timestamp=_ts_to_dt(raw.get("timestamp")),
            )
            orders.append(order)

        # Sort by timestamp descending
        orders.sort(key=lambda o: o.timestamp or _utcnow(), reverse=True)
        return orders

    async def get_fills(self, order_id: str) -> list[Fill]:
        """Get all fills for an order.

        A single order may result in multiple partial fills.

        Args:
            order_id: Exchange-assigned order ID.

        Returns:
            List of Fill objects, ordered by timestamp ascending.

        Raises:
            OrderNotFoundError: Order does not exist on the exchange.
        """
        exchange = await self._ensure_exchange()

        try:
            # Fetch the order to get fill details
            raw = await exchange.fetch_order(order_id, symbol=None)
        except ccxt.OrderNotFound as exc:
            raise LookupError(f"Order not found: {order_id}") from exc
        except ccxt.NetworkError as exc:
            raise ConnectionError(f"Network error: {exc}") from exc

        symbol = raw.get("symbol", "")
        side = OrderSide.BUY if raw.get("side") == "buy" else OrderSide.SELL

        # Try to extract individual trades/fills from the order
        fills: list[Fill] = []

        # Some exchanges provide 'trades' array in the order response
        raw_trades = raw.get("trades", []) or []
        if raw_trades:
            for i, trade in enumerate(raw_trades):
                fills.append(Fill(
                    fill_id=str(trade.get("id", f"{order_id}:fill:{i}")),
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    price=float(trade.get("price", 0) or 0),
                    quantity=float(trade.get("amount", 0) or 0),
                    fee=float((trade.get("fee", {}) or {}).get("cost", 0) or 0),
                    fee_currency=(trade.get("fee", {}) or {}).get("currency", ""),
                    timestamp=_ts_to_dt(trade.get("timestamp")),
                ))
        else:
            # Synthesize a single fill from order data
            filled_qty = float(raw.get("filled", 0) or 0)
            if filled_qty > 0:
                avg_price = float(raw.get("average", 0) or 0)
                fee_info = raw.get("fee", {}) or {}
                fills.append(Fill(
                    fill_id=f"{order_id}:fill:0",
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    price=avg_price,
                    quantity=filled_qty,
                    fee=float(fee_info.get("cost", 0) or 0),
                    fee_currency=fee_info.get("currency", ""),
                    timestamp=_ts_to_dt(raw.get("timestamp")),
                ))

        # Sort by timestamp ascending
        fills.sort(key=lambda f: f.timestamp)
        return fills

    # ═══════════════════════════════════════════════════════════════
    # SLIPPAGE ANALYSIS
    # ═══════════════════════════════════════════════════════════════

    @property
    def avg_slippage_bps(self) -> float:
        """Average absolute slippage across all tracked executions."""
        if not self._slippage_history:
            return 0.0
        return sum(abs(s) for s in self._slippage_history) / len(self._slippage_history)

    @property
    def slippage_history(self) -> list[float]:
        """Full slippage history in basis points."""
        return list(self._slippage_history)

    @staticmethod
    def _calc_slippage_bps(
        expected: float,
        actual: float,
        side: OrderSide,
    ) -> float:
        """Calculate slippage in basis points.

        For BUY orders: positive slippage means you paid more (bad).
        For SELL orders: positive slippage means you received less (bad).

        Args:
            expected: Expected/limit price.
            actual: Actual fill price.
            side: Order side.

        Returns:
            Slippage in basis points (positive = adverse).
        """
        if expected <= 0:
            return 0.0

        if side == OrderSide.BUY:
            slippage = (actual - expected) / expected
        else:
            slippage = (expected - actual) / expected

        return slippage * 10_000  # Convert to basis points

    # ═══════════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _map_order_type(order_type: OrderType) -> str:
        """Map TSAR OrderType to ccxt order type string."""
        mapping = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP_MARKET: "stop_market",
            OrderType.STOP_LIMIT: "stop_limit",
        }
        return mapping.get(order_type, "market")

    @staticmethod
    def _parse_order_type(ccxt_type: str) -> OrderType:
        """Parse ccxt order type string to TSAR OrderType."""
        mapping = {
            "market": OrderType.MARKET,
            "limit": OrderType.LIMIT,
            "stop_market": OrderType.STOP_MARKET,
            "stop_limit": OrderType.STOP_LIMIT,
        }
        return mapping.get(ccxt_type.lower(), OrderType.MARKET)

    @staticmethod
    def _map_order_status(ccxt_status: str) -> OrderStatus:
        """Map ccxt order status string to TSAR OrderStatus."""
        mapping = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.EXPIRED,
            "rejected": OrderStatus.REJECTED,
        }
        status = mapping.get(ccxt_status.lower())
        if status is not None:
            return status

        # Partial fill detection
        if ccxt_status and "partial" in ccxt_status.lower():
            return OrderStatus.PARTIALLY_FILLED

        return OrderStatus.PENDING

    @staticmethod
    def _extract_fills(
        raw: dict[str, Any],
        order_id: str,
        symbol: str,
        side: OrderSide,
    ) -> list[Fill]:
        """Extract Fill objects from an order response.

        Args:
            raw: Raw ccxt order response.
            order_id: Order ID.
            symbol: Trading pair.
            side: Order side.

        Returns:
            List of Fill objects.
        """
        fills: list[Fill] = []
        raw_trades = raw.get("trades", []) or []

        if raw_trades:
            for i, trade in enumerate(raw_trades):
                fills.append(Fill(
                    fill_id=str(trade.get("id", f"{order_id}:fill:{i}")),
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    price=float(trade.get("price", 0) or 0),
                    quantity=float(trade.get("amount", 0) or 0),
                    fee=float((trade.get("fee", {}) or {}).get("cost", 0) or 0),
                    fee_currency=(trade.get("fee", {}) or {}).get("currency", ""),
                    timestamp=_ts_to_dt(trade.get("timestamp")),
                ))
        else:
            # Single fill from order summary
            filled_qty = float(raw.get("filled", 0) or 0)
            if filled_qty > 0:
                avg_price = float(raw.get("average", 0) or 0)
                fee_info = raw.get("fee", {}) or {}
                fills.append(Fill(
                    fill_id=f"{order_id}:fill:0",
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    price=avg_price,
                    quantity=filled_qty,
                    fee=float(fee_info.get("cost", 0) or 0),
                    fee_currency=fee_info.get("currency", ""),
                    timestamp=_ts_to_dt(raw.get("timestamp")),
                ))

        return fills

    # ═══════════════════════════════════════════════════════════════
    # BRACKET / OCO ORDER SUPPORT (H-021)
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
        """Execute a bracket order: entry + linked stop-loss + take-profit.

        Places three linked orders:
        1. Entry order (limit or market)
        2. Stop-loss order (opposite side, triggers at stop_loss_price)
        3. Take-profit order (opposite side, limit at take_profit_price)

        A background monitor cancels the remaining exit order when one fills.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: Direction of the entry (BUY or SELL).
            quantity: Position size.
            entry_price: Entry price for limit orders (None for market).
            stop_loss_price: Stop-loss trigger price.
            take_profit_price: Take-profit limit price.
            entry_type: Entry order type (LIMIT or MARKET).

        Returns:
            BracketOrder with all linked order IDs.

        Raises:
            ValueError: Invalid parameters.
            ConnectionError: Not connected.
        """
        if stop_loss_price <= 0 or take_profit_price <= 0:
            raise ValueError("Stop-loss and take-profit prices must be positive")

        if side == OrderSide.BUY:
            if entry_price and stop_loss_price >= entry_price:
                raise ValueError("BUY stop-loss must be below entry price")
            if entry_price and take_profit_price <= entry_price:
                raise ValueError("BUY take-profit must be above entry price")
        else:
            if entry_price and stop_loss_price <= entry_price:
                raise ValueError("SELL stop-loss must be above entry price")
            if entry_price and take_profit_price >= entry_price:
                raise ValueError("SELL take-profit must be below entry price")

        bracket_id = f"BRK-{uuid.uuid4().hex[:12]}"
        exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

        bracket = BracketOrder(
            bracket_id=bracket_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            timestamp=_utcnow(),
        )

        # 1. Place entry order
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
        bracket.entry_order_id = entry_result.order_id

        logger.info(
            "Bracket %s: entry %s placed (%s %s @ %.2f)",
            bracket_id,
            entry_result.order_id,
            side.value,
            symbol,
            entry_result.average_price,
        )

        # 2. Place stop-loss order
        sl_order = Order(
            order_id="",
            symbol=symbol,
            side=exit_side,
            order_type=OrderType.STOP_MARKET,
            quantity=quantity,
            stop_price=stop_loss_price,
            timestamp=_utcnow(),
        )
        try:
            sl_result = await self.execute_order(sl_order)
            bracket.stop_loss_order_id = sl_result.order_id
            bracket.linked_order_ids.append(sl_result.order_id)
        except Exception as exc:
            logger.error("Failed to place stop-loss for bracket %s: %s", bracket_id, exc)
            try:
                await self.cancel_order(entry_result.order_id)
            except Exception:
                pass
            bracket.status = "cancelled"
            raise

        # 3. Place take-profit order
        tp_order = Order(
            order_id="",
            symbol=symbol,
            side=exit_side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=take_profit_price,
            timestamp=_utcnow(),
        )
        try:
            tp_result = await self.execute_order(tp_order)
            bracket.take_profit_order_id = tp_result.order_id
            bracket.linked_order_ids.append(tp_result.order_id)
        except Exception as exc:
            logger.error("Failed to place take-profit for bracket %s: %s", bracket_id, exc)
            try:
                await self.cancel_order(bracket.stop_loss_order_id)
                await self.cancel_order(entry_result.order_id)
            except Exception:
                pass
            bracket.status = "cancelled"
            raise

        bracket.status = "active"
        self._bracket_orders[bracket_id] = bracket

        # Start background monitor
        monitor_task = asyncio.create_task(
            self._monitor_bracket(bracket_id),
            name=f"bracket-monitor:{bracket_id}",
        )
        self._bracket_monitor_tasks[bracket_id] = monitor_task

        logger.info(
            "Bracket %s active: entry=%s SL=%.2f TP=%.2f",
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
        """Execute an OCO (One-Cancels-Other) order.

        Uses the exchange's native OCO order type when available (e.g. Binance).
        Falls back to two linked limit orders with a monitor if OCO is not
        supported by the exchange.

        Args:
            symbol: Trading pair.
            side: Exit direction (opposite of the position).
            quantity: Order quantity.
            stop_loss_price: Stop-loss trigger price.
            take_profit_price: Take-profit limit price.

        Returns:
            BracketOrder tracking the OCO.
        """
        exchange = await self._ensure_exchange()
        bracket_id = f"OCO-{uuid.uuid4().hex[:12]}"

        bracket = BracketOrder(
            bracket_id=bracket_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            timestamp=_utcnow(),
        )

        # Try native OCO via Binance-specific endpoint
        if self._exchange_id == "binance":
            try:
                params: dict[str, Any] = {
                    "stopPrice": stop_loss_price,
                    "type": "OCO",
                }
                raw = await exchange.create_order(
                    symbol=symbol,
                    type="limit",
                    side=side.value,
                    amount=quantity,
                    price=take_profit_price,
                    params=params,
                )
                bracket.entry_order_id = str(raw.get("id", ""))
                bracket.status = "active"
                bracket.linked_order_ids = [bracket.entry_order_id]
                self._bracket_orders[bracket_id] = bracket
                logger.info(
                    "OCO %s placed on Binance: SL=%.2f TP=%.2f",
                    bracket_id,
                    stop_loss_price,
                    take_profit_price,
                )
                return bracket
            except Exception as exc:
                logger.warning(
                    "Native OCO failed (%s), falling back to linked orders",
                    exc,
                )

        # Fallback: place two linked orders with a monitor
        exit_side = side

        # Stop-loss (stop-market)
        sl_order = Order(
            order_id="",
            symbol=symbol,
            side=exit_side,
            order_type=OrderType.STOP_MARKET,
            quantity=quantity,
            stop_price=stop_loss_price,
            timestamp=_utcnow(),
        )
        sl_result = await self.execute_order(sl_order)
        bracket.stop_loss_order_id = sl_result.order_id
        bracket.linked_order_ids.append(sl_result.order_id)

        # Take-profit (limit)
        tp_order = Order(
            order_id="",
            symbol=symbol,
            side=exit_side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=take_profit_price,
            timestamp=_utcnow(),
        )
        tp_result = await self.execute_order(tp_order)
        bracket.take_profit_order_id = tp_result.order_id
        bracket.linked_order_ids.append(tp_result.order_id)

        bracket.status = "active"
        self._bracket_orders[bracket_id] = bracket

        # Start monitor to cancel the other when one fills
        monitor_task = asyncio.create_task(
            self._monitor_bracket(bracket_id),
            name=f"oco-monitor:{bracket_id}",
        )
        self._bracket_monitor_tasks[bracket_id] = monitor_task

        logger.info(
            "OCO %s active (linked orders): SL=%s TP=%s",
            bracket_id,
            sl_result.order_id,
            tp_result.order_id,
        )

        return bracket

    async def _monitor_bracket(self, bracket_id: str) -> None:
        """Monitor a bracket/OCO order and cancel the other side when one fills.

        Polls order status for both exit orders. When one fills or cancels,
        cancels the other.
        """
        bracket = self._bracket_orders.get(bracket_id)
        if bracket is None:
            return

        poll_interval = 2.0  # seconds
        max_wait = 86400  # 24 hours
        elapsed = 0.0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            bracket = self._bracket_orders.get(bracket_id)
            if bracket is None or bracket.status != "active":
                return

            sl_id = bracket.stop_loss_order_id
            tp_id = bracket.take_profit_order_id

            try:
                if sl_id:
                    sl_status = await self.get_order_status(sl_id)
                    if sl_status == OrderStatus.FILLED:
                        logger.info("Bracket %s: stop-loss filled, cancelling take-profit", bracket_id)
                        if tp_id:
                            try:
                                await self.cancel_order(tp_id)
                            except Exception:
                                pass
                        bracket.status = "closed"
                        return

                if tp_id:
                    tp_status = await self.get_order_status(tp_id)
                    if tp_status == OrderStatus.FILLED:
                        logger.info("Bracket %s: take-profit filled, cancelling stop-loss", bracket_id)
                        if sl_id:
                            try:
                                await self.cancel_order(sl_id)
                            except Exception:
                                pass
                        bracket.status = "closed"
                        return

            except Exception as exc:
                logger.debug("Bracket monitor poll error for %s: %s", bracket_id, exc)

        logger.warning("Bracket %s monitor timed out after %ds", bracket_id, max_wait)

    async def cancel_bracket_order(self, bracket_id: str) -> bool:
        """Cancel all orders in a bracket.

        Args:
            bracket_id: Bracket identifier.

        Returns:
            True if all orders were cancelled.
        """
        bracket = self._bracket_orders.get(bracket_id)
        if bracket is None:
            logger.warning("Bracket %s not found", bracket_id)
            return False

        cancelled = True
        for order_id in bracket.linked_order_ids:
            try:
                await self.cancel_order(order_id)
            except Exception as exc:
                logger.warning("Failed to cancel %s in bracket %s: %s", order_id, bracket_id, exc)
                cancelled = False

        # Stop monitor
        monitor_task = self._bracket_monitor_tasks.pop(bracket_id, None)
        if monitor_task is not None:
            monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor_task

        bracket.status = "cancelled"
        logger.info("Bracket %s cancelled", bracket_id)
        return cancelled

    async def get_bracket_status(self, bracket_id: str) -> BracketOrder | None:
        """Get the current status of a bracket order.

        Args:
            bracket_id: Bracket identifier.

        Returns:
            BracketOrder or None if not found.
        """
        return self._bracket_orders.get(bracket_id)
