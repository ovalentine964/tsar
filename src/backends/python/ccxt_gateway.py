"""
CcxtGateway — Exchange connectivity via ccxt REST API.

Day1 implementation of ExchangeGateway. Uses ccxt async_support for all
exchange I/O with proper error handling, retry logic, rate limiting,
and sandbox/testnet support.

Swappable to Rust WebSocket (Level 2) or C++ FIX (Level 4) via config.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import ccxt.async_support as ccxt

from src.interfaces.exchange_gateway import ExchangeGateway
from src.interfaces.types import (
    OHLCV,
    ConnectionStatus,
    OrderBook,
    OrderBookLevel,
    Price,
    Timeframe,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# ccxt exception hierarchy for structured error handling
_CCXT_NETWORK_ERRORS = (
    ccxt.NetworkError,
    ccxt.ExchangeNotAvailable,
    ccxt.RequestTimeout,
)
_CCXT_AUTH_ERRORS = (
    ccxt.AuthenticationError,
    ccxt.PermissionDenied,
)
_CCXT_RATE_LIMIT_ERRORS = (ccxt.RateLimitExceeded,)
_CCXT_NOT_FOUND_ERRORS = (ccxt.ExchangeError,)


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(UTC)


def _ts_to_dt(ts_ms: int | float | None) -> datetime:
    """Convert millisecond timestamp to timezone-aware datetime."""
    if ts_ms is None:
        return _utcnow()
    return datetime.fromtimestamp(float(ts_ms) / 1000, tz=UTC)


class CcxtGateway(ExchangeGateway):
    """Exchange gateway using ccxt REST API.

    Implements the full ExchangeGateway interface with:
    - Async ccxt operations via ccxt.async_support
    - Automatic retry with exponential backoff on transient errors
    - Rate limiting (ccxt built-in + local tracking)
    - Sandbox/testnet support
    - Polling-based ticker subscription (Day1)
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        exchange_id: str = "binance",
        sandbox: bool = True,
        rate_limit_per_minute: int = 1200,
        timeout_s: int = 15,
        max_retries: int = 3,
        api_key: str = "",
        api_secret: str = "",
        **kwargs: Any,
    ) -> None:
        # Accept config dict (from backends.yaml) or explicit kwargs
        cfg = config or {}
        self._exchange_id: str = cfg.get("exchange_id", exchange_id)
        self._sandbox: bool = cfg.get("sandbox", sandbox)
        self._rate_limit_per_minute: int = cfg.get("rate_limit_per_minute", rate_limit_per_minute)
        self._timeout_s: int = cfg.get("timeout_s", timeout_s)
        self._max_retries: int = cfg.get("max_retries", max_retries)
        self._api_key: str = cfg.get("api_key", api_key)
        self._api_secret: str = cfg.get("api_secret", api_secret)

        self._exchange: ccxt.Exchange | None = None
        self._status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self._markets_loaded: bool = False

        # Rate limiting: sliding window counter
        self._request_timestamps: list[float] = []
        self._rate_limit_lock = asyncio.Lock()

        # Ticker subscriptions (polling-based Day1)
        self._ticker_tasks: dict[str, asyncio.Task[None]] = {}
        self._ticker_cancel_events: dict[str, asyncio.Event] = {}

    # ═══════════════════════════════════════════════════════════════
    # PROPERTIES
    # ═══════════════════════════════════════════════════════════════

    @property
    def connection_status(self) -> ConnectionStatus:
        """Current connection status."""
        return self._status

    @property
    def is_connected(self) -> bool:
        """Whether the gateway is currently connected."""
        return self._status == ConnectionStatus.CONNECTED

    # ═══════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════

    async def connect(self) -> None:
        """Establish connection to the exchange.

        Creates the ccxt exchange instance, configures sandbox mode,
        authenticates if credentials are provided, and loads markets.

        Raises:
            ConnectionError: Cannot reach the exchange.
            AuthenticationError: Invalid API credentials.
        """
        if self._status == ConnectionStatus.CONNECTED and self._exchange is not None:
            logger.warning("Already connected — skipping connect()")
            return

        self._status = ConnectionStatus.CONNECTING
        logger.info(
            "Connecting to %s (sandbox=%s, timeout=%ds)",
            self._exchange_id,
            self._sandbox,
            self._timeout_s,
        )

        try:
            # Build ccxt exchange instance
            exchange_class = getattr(ccxt, self._exchange_id, None)
            if exchange_class is None:
                raise ConnectionError(
                    f"Exchange '{self._exchange_id}' not found in ccxt. "
                    f"Available: {', '.join(ccxt.exchanges[:10])}..."
                )

            config: dict[str, Any] = {
                "enableRateLimit": True,
                "timeout": self._timeout_s * 1000,
            }
            if self._api_key:
                config["apiKey"] = self._api_key
                config["secret"] = self._api_secret

            self._exchange = exchange_class(config)

            # Enable sandbox/testnet if configured
            if self._sandbox:
                self._exchange.set_sandbox_mode(True)
                logger.info("Sandbox/testnet mode enabled")

            # Load markets to verify connectivity and populate symbol info
            await self._retry_on_transient(self._exchange.load_markets)
            self._markets_loaded = True
            self._status = ConnectionStatus.CONNECTED
            logger.info(
                "Connected to %s — %d markets loaded",
                self._exchange_id,
                len(self._exchange.markets),
            )

        except ccxt.AuthenticationError as exc:
            self._status = ConnectionStatus.ERROR
            logger.error("Authentication failed: %s", exc)
            raise ConnectionError(f"Authentication failed: {exc}") from exc
        except (_CCXT_NETWORK_ERRORS, OSError) as exc:
            self._status = ConnectionStatus.ERROR
            logger.error("Network error connecting to %s: %s", self._exchange_id, exc)
            raise ConnectionError(f"Cannot reach {self._exchange_id}: {exc}") from exc
        except Exception as exc:
            self._status = ConnectionStatus.ERROR
            logger.error("Unexpected error during connect: %s", exc, exc_info=True)
            raise

    async def disconnect(self) -> None:
        """Gracefully disconnect from the exchange.

        Cancels all ticker subscriptions, closes the exchange connection,
        and resets internal state. Idempotent — safe to call multiple times.
        """
        # Cancel all active ticker subscriptions
        for symbol in list(self._ticker_tasks.keys()):
            await self._unsubscribe_ticker(symbol)

        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception as exc:
                logger.warning("Error closing exchange connection: %s", exc)
            finally:
                self._exchange = None
                self._markets_loaded = False

        self._status = ConnectionStatus.DISCONNECTED
        logger.info("Disconnected from %s", self._exchange_id)

    async def health_check(self) -> bool:
        """Check if the exchange connection is healthy.

        Performs a lightweight API call (fetch server time) to verify
        the connection is alive and responsive.

        Returns:
            True if healthy, False otherwise.
        """
        if self._exchange is None or self._status != ConnectionStatus.CONNECTED:
            return False
        try:
            await asyncio.wait_for(
                self._exchange.fetch_time(),
                timeout=5.0,
            )
            return True
        except Exception as exc:
            logger.warning("Health check failed: %s", exc)
            return False

    # ═══════════════════════════════════════════════════════════════
    # MARKET DATA (READ)
    # ═══════════════════════════════════════════════════════════════

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
        self._ensure_connected()
        assert self._exchange is not None

        try:
            raw = await self._retry_on_transient(
                self._exchange.fetch_ticker, symbol
            )
            return Price(
                symbol=symbol,
                last=float(raw["last"] or 0),
                bid=float(raw.get("bid") or 0),
                ask=float(raw.get("ask") or 0),
                timestamp=_ts_to_dt(raw.get("timestamp")),
            )
        except ccxt.BadSymbol as exc:
            raise LookupError(f"Symbol not found: {symbol}") from exc

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
        self._ensure_connected()
        assert self._exchange is not None

        try:
            raw = await self._retry_on_transient(
                self._exchange.fetch_ohlcv,
                symbol,
                timeframe.value,
                limit=limit,
            )
            return [
                OHLCV(
                    timestamp=_ts_to_dt(bar[0]),
                    open=float(bar[1]),
                    high=float(bar[2]),
                    low=float(bar[3]),
                    close=float(bar[4]),
                    volume=float(bar[5]),
                )
                for bar in raw
            ]
        except ccxt.BadSymbol as exc:
            raise LookupError(f"Symbol not found: {symbol}") from exc

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
        self._ensure_connected()
        assert self._exchange is not None

        try:
            raw = await self._retry_on_transient(
                self._exchange.fetch_order_book, symbol, limit=depth
            )
            return OrderBook(
                symbol=symbol,
                bids=tuple(
                    OrderBookLevel(price=float(b[0]), quantity=float(b[1]))
                    for b in raw.get("bids", [])
                ),
                asks=tuple(
                    OrderBookLevel(price=float(a[0]), quantity=float(a[1]))
                    for a in raw.get("asks", [])
                ),
                timestamp=_utcnow(),
            )
        except ccxt.BadSymbol as exc:
            raise LookupError(f"Symbol not found: {symbol}") from exc

    # ═══════════════════════════════════════════════════════════════
    # STREAMING (REAL-TIME)
    # �══════════════════════════════════════════════════════════════

    async def subscribe_ticker(
        self,
        symbol: str,
        callback: Callable[[Price], Any],
    ) -> None:
        """Subscribe to real-time price updates for a symbol.

        Day1 implementation: polling-based. Fetches the ticker at a
        configurable interval and invokes the callback with each update.
        Level 2 will use true WebSocket streams.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            callback: Async or sync callable invoked with each Price update.

        Raises:
            SymbolNotFoundError: Symbol does not exist on the exchange.
            ConnectionError: Not connected to the exchange.
        """
        self._ensure_connected()

        if symbol in self._ticker_tasks:
            logger.warning("Already subscribed to %s ticker — ignoring", symbol)
            return

        # Validate symbol exists before starting poll loop
        try:
            await self.get_price(symbol)
        except LookupError:
            raise
        except Exception:
            # If the first fetch fails, still raise — but the symbol validation
            # is the primary concern here
            raise

        cancel_event = asyncio.Event()
        self._ticker_cancel_events[symbol] = cancel_event

        task = asyncio.create_task(
            self._ticker_poll_loop(symbol, callback, cancel_event),
            name=f"ticker-poll:{symbol}",
        )
        self._ticker_tasks[symbol] = task
        logger.info("Subscribed to %s ticker (polling mode)", symbol)

    async def _ticker_poll_loop(
        self,
        symbol: str,
        callback: Callable[[Price], Any],
        cancel: asyncio.Event,
    ) -> None:
        """Polling loop for ticker subscription (Day1 implementation)."""
        poll_interval = max(1.0, 60.0 / self._rate_limit_per_minute)
        # Cap at reasonable interval for polling
        poll_interval = min(poll_interval, 5.0)

        while not cancel.is_set():
            try:
                price = await self.get_price(symbol)
                result = callback(price)
                # Support async callbacks
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Ticker poll error for %s: %s", symbol, exc)

            try:
                await asyncio.wait_for(cancel.wait(), timeout=poll_interval)
                break  # Cancelled during wait
            except TimeoutError:
                continue  # Normal timeout — poll again

        logger.info("Ticker poll loop stopped for %s", symbol)

    async def _unsubscribe_ticker(self, symbol: str) -> None:
        """Cancel a ticker subscription."""
        cancel_event = self._ticker_cancel_events.pop(symbol, None)
        task = self._ticker_tasks.pop(symbol, None)

        if cancel_event is not None:
            cancel_event.set()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        logger.debug("Unsubscribed from %s ticker", symbol)

    # ═══════════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════════════

    def _ensure_connected(self) -> None:
        """Raise ConnectionError if not connected."""
        if self._exchange is None or self._status != ConnectionStatus.CONNECTED:
            raise ConnectionError(
                f"Not connected to {self._exchange_id} "
                f"(status={self._status.value})"
            )

    async def _retry_on_transient(self, coro_func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a ccxt call with retry on transient errors.

        Retries on network errors, timeouts, and rate limits with
        exponential backoff. Does NOT retry on auth or symbol errors.

        Args:
            coro_func: Async callable (e.g. self._exchange.fetch_ticker).
            *args: Positional args to pass to coro_func.
            **kwargs: Keyword args to pass to coro_func.

        Returns:
            The result of coro_func.

        Raises:
            The last exception if all retries are exhausted.
        """
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                # Rate limit check
                await self._enforce_rate_limit()

                # Track request timestamp
                async with self._rate_limit_lock:
                    self._request_timestamps.append(time.monotonic())

                return await coro_func(*args, **kwargs)

            except _CCXT_RATE_LIMIT_ERRORS as exc:
                last_exc = exc
                # Respect Retry-After header if available
                retry_after = getattr(exc, "retry_after", None)
                wait_s = float(retry_after) if retry_after else min(2.0 ** (attempt + 1), 30.0)
                logger.warning(
                    "Rate limited (attempt %d/%d), waiting %.1fs: %s",
                    attempt + 1,
                    self._max_retries + 1,
                    wait_s,
                    exc,
                )
                await asyncio.sleep(wait_s)

            except _CCXT_NETWORK_ERRORS as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    wait_s = min(2.0 ** attempt, 10.0)
                    logger.warning(
                        "Network error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        self._max_retries + 1,
                        wait_s,
                        exc,
                    )
                    await asyncio.sleep(wait_s)
                else:
                    logger.error(
                        "Network error after %d retries: %s",
                        self._max_retries + 1,
                        exc,
                    )

            except (ccxt.AuthenticationError, ccxt.BadSymbol, ccxt.InvalidOrder):
                # Don't retry auth errors, bad symbols, or invalid orders
                raise

        # All retries exhausted
        assert last_exc is not None
        raise last_exc

    async def _enforce_rate_limit(self) -> None:
        """Enforce local rate limiting as a safety net over ccxt's built-in."""
        async with self._rate_limit_lock:
            now = time.monotonic()
            window = 60.0  # 1-minute sliding window

            # Prune timestamps outside the window
            self._request_timestamps = [
                ts for ts in self._request_timestamps if now - ts < window
            ]

            if len(self._request_timestamps) >= self._rate_limit_per_minute:
                # Calculate how long to wait for the oldest request to expire
                oldest = self._request_timestamps[0]
                wait_s = window - (now - oldest) + 0.01
                if wait_s > 0:
                    logger.debug("Rate limit approaching, waiting %.2fs", wait_s)
                    await asyncio.sleep(wait_s)
