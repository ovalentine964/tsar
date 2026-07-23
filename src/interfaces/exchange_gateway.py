"""
TSAR Interface — ExchangeGateway Abstract Base Class.

Abstracts all exchange connectivity. Day1 uses ccxt (Python).
Level 2 swaps in Rust WebSocket. Level 4 swaps in C++ FIX.

Agent code calls:
    gateway = get_exchange_gateway()
    price = await gateway.get_price("BTC/USDT")

Whether the backend is ccxt, Rust WebSocket, or C++ FIX — the call is identical.
The interface is the contract. The backend is an implementation detail.
"""

from __future__ import annotations

import abc
from typing import Any, Callable

from src.interfaces.types import (
    Balance,
    ConnectionStatus,
    OHLCV,
    OrderBook,
    OrderSide,
    OrderType,
    Position,
    Price,
    Timeframe,
    Trade,
)


class ExchangeGateway(abc.ABC):
    """Abstract interface for exchange connectivity.

    All exchange communication flows through this interface.
    Agents NEVER import ccxt, Rust crates, or C++ modules directly.

    Lifecycle::

        gateway = ConcreteGateway(config)
        await gateway.connect()
        price = await gateway.get_price("BTC/USDT")
        await gateway.disconnect()

    Day1 Implementation: CcxtGateway (ccxt REST API)
    Level 2 Implementation: RustWsGateway (Rust tokio-tungstenite WebSocket)
    Level 4 Implementation: FixGateway (C++ QuickFIX)
    """

    # ═══════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish connection to the exchange.

        Must:
        - Authenticate with the exchange (if credentials provided).
        - Verify connectivity with a lightweight API call.
        - Update internal connection status to CONNECTED.

        Must NOT:
        - Block for more than 10 seconds.
        - Subscribe to data streams (use subscribe methods for that).

        Raises:
            ConnectionError: Cannot reach the exchange.
            AuthenticationError: Invalid API credentials.
        """
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the exchange.

        Must:
        - Close all open network connections.
        - Cancel all active stream subscriptions.
        - Update internal connection status to DISCONNECTED.

        Safe to call multiple times (idempotent).
        """
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Check if the exchange connection is healthy.

        Performs a lightweight API call to verify the connection is alive
        and responsive. Used by the watchdog and orchestrator.

        Returns:
            True if the connection is healthy and responsive, False otherwise.
        """
        ...

    # ═══════════════════════════════════════════════════════════════
    # MARKET DATA (READ)
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def get_price(self, symbol: str) -> Price:
        """Get the current price snapshot for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").

        Returns:
            Price with last, bid, ask, and timestamp.

        Raises:
            SymbolNotFoundError: Symbol does not exist on the exchange.
            ConnectionError: Not connected to the exchange.
        """
        ...

    @abc.abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 100,
    ) -> list[OHLCV]:
        """Get OHLCV candlestick data.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            timeframe: Candle interval (e.g. Timeframe.H1).
            limit: Number of candles to return (default 100).

        Returns:
            List of OHLCV candles, oldest first.

        Raises:
            SymbolNotFoundError: Symbol does not exist on the exchange.
            ConnectionError: Not connected to the exchange.
        """
        ...

    @abc.abstractmethod
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """Get the current order book snapshot.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            depth: Number of price levels per side (default 20).

        Returns:
            OrderBook with bids and asks.

        Raises:
            SymbolNotFoundError: Symbol does not exist on the exchange.
            ConnectionError: Not connected to the exchange.
        """
        ...

    # ═══════════════════════════════════════════════════════════════
    # STREAMING (REAL-TIME)
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def subscribe_ticker(
        self,
        symbol: str,
        callback: Callable[[Price], Any],
    ) -> None:
        """Subscribe to real-time price updates for a symbol.

        The callback is invoked each time a new price tick arrives.
        On Day1 (ccxt) this may be implemented as polling.
        On Level 2 (Rust WebSocket) this is a true WebSocket stream.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            callback: Async or sync callable invoked with each Price update.

        Raises:
            SymbolNotFoundError: Symbol does not exist on the exchange.
            ConnectionError: Not connected to the exchange.
        """
        ...

    # ═══════════════════════════════════════════════════════════════
    # ACCOUNT (READ)
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def get_balance(self) -> dict[str, Balance]:
        """Get account balances for all assets.

        Returns:
            Dict mapping asset symbol to Balance (free, used, total).

        Raises:
            ConnectionError: Not connected to the exchange.
        """
        ...

    @abc.abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get all open positions.

        Returns:
            List of Position objects with symbol, side, size, entry price, PnL.

        Raises:
            ConnectionError: Not connected to the exchange.
        """
        ...

    @abc.abstractmethod
    async def get_ticker(self, symbol: str) -> Price:
        """Get full ticker for a symbol (alias for get_price).

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").

        Returns:
            Price with last, bid, ask, volume, and timestamp.
        """
        ...

    @abc.abstractmethod
    async def get_recent_trades(
        self,
        symbol: str,
        limit: int = 50,
    ) -> list[Trade]:
        """Get recent trades for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            limit: Number of trades to return (default 50).

        Returns:
            List of Trade objects, most recent first.
        """
        ...
