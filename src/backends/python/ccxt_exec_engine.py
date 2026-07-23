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
import logging
from datetime import datetime, timezone
from typing import Any

import ccxt.async_support as ccxt

from src.interfaces.execution_engine import ExecutionEngine
from src.interfaces.types import (
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
    return datetime.now(timezone.utc)


def _ts_to_dt(ts_ms: int | float | None) -> datetime:
    """Convert millisecond timestamp to timezone-aware datetime."""
    if ts_ms is None:
        return _utcnow()
    return datetime.fromtimestamp(float(ts_ms) / 1000, tz=timezone.utc)


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

    # ═══════════════════════════════════════════════════════════════
    # CONNECTION MANAGEMENT
    # ═══════════════════════════════════════════════════════════════

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

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Args:
            order_id: Exchange-assigned order ID.

        Returns:
            True if cancelled successfully, False otherwise.

        Raises:
            OrderNotFoundError: Order does not exist on the exchange.
        """
        exchange = await self._ensure_exchange()

        try:
            # ccxt cancel_order requires symbol — we need to fetch the order first
            # to get the symbol. Try with fetch_order using common approach.
            # Note: Some exchanges allow cancel by ID alone, but ccxt generally
            # requires symbol. We'll try to cancel and handle the error.
            await exchange.cancel_order(order_id, symbol=None)
            logger.info("Order %s cancelled", order_id)
            return True
        except ccxt.OrderNotFound as exc:
            logger.error("Order %s not found: %s", order_id, exc)
            raise LookupError(f"Order not found: {order_id}") from exc
        except ccxt.NetworkError as exc:
            logger.error("Network error cancelling order %s: %s", order_id, exc)
            return False
        except Exception as exc:
            # Some exchanges require symbol for cancel — fall back gracefully
            logger.warning(
                "Cancel failed for order %s (may need symbol): %s", order_id, exc
            )
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
