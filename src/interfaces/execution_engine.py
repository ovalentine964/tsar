"""
TSAR Interface — ExecutionEngine Abstract Base Class.

Abstracts order execution — from simple REST orders to smart order routing
to institutional FIX protocol. Handles the full order lifecycle:
place → fill → track → analyze.

Day1: CcxtExecEngine (delegates to ExchangeGateway)
Level 2: RustExecEngine (Rust order executor via PyO3)
Level 4: FixExecEngine (C++ QuickFIX)
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.interfaces.types import (
        ExecutionResult,
        Fill,
        Order,
        OrderStatus,
    )


class ExecutionEngine(abc.ABC):
    """Abstract interface for order execution.

    Handles the full lifecycle: place → fill → track → analyze.

    Day1: CcxtExecEngine — simple ccxt REST orders via ExchangeGateway.
    Level 2: RustExecEngine — low-latency order placement via PyO3.
    Level 4: FixExecEngine — institutional FIX protocol execution.

    All methods are async. Backends may be sync internally but must
    expose async interfaces for consistency.
    """

    # ═══════════════════════════════════════════════════════════════
    # ORDER EXECUTION
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def execute_order(self, order: Order) -> ExecutionResult:
        """Execute an order on the exchange.

        This is the primary execution method. It handles:
        - Order placement on the exchange.
        - Fill tracking and aggregation.
        - Slippage calculation.
        - Error handling.

        Args:
            order: The Order to execute (symbol, side, type, quantity, price).

        Returns:
            ExecutionResult with fill information, average price, and slippage.

        Raises:
            InsufficientFundsError: Not enough balance for the order.
            InvalidOrderError: Order parameters are invalid.
            ExchangeError: The exchange rejected the order.
        """
        ...

    @abc.abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Args:
            order_id: Exchange-assigned order ID.

        Returns:
            True if the order was cancelled successfully, False otherwise.

        Raises:
            OrderNotFoundError: Order does not exist on the exchange.
        """
        ...

    @abc.abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the current status of an order.

        Args:
            order_id: Exchange-assigned order ID.

        Returns:
            Current OrderStatus enum value.

        Raises:
            OrderNotFoundError: Order does not exist on the exchange.
        """
        ...

    @abc.abstractmethod
    async def get_open_orders(self, symbol: str) -> list[Order]:
        """Get all open orders for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").

        Returns:
            List of open Order objects, sorted by timestamp descending.
        """
        ...

    @abc.abstractmethod
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
        ...
