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
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiohttp
import ccxt.async_support as ccxt
try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None  # type: ignore[assignment]

from src.interfaces.exchange_gateway import ExchangeGateway
from src.interfaces.types import (
    OHLCV,
    Balance,
    ConnectionStatus,
    OrderBook,
    OrderBookLevel,
    OrderSide,
    Position,
    Price,
    Timeframe,
    Trade,
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
# ═══════════════════════════════════════════════════════════════════════
# REDIS MARKET DATA CACHE (H-020)
# ═══════════════════════════════════════════════════════════════════════
class MarketDataCache:
    """Redis-based cache for market data with TTL support.

    Caches OHLCV, ticker (Price), and order book data to reduce
    redundant REST API calls. Each data type has a configurable TTL.

    Falls back to a no-op in-memory dict if Redis is unavailable.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        *,
        ticker_ttl_s: float = 2.0,
        ohlcv_ttl_s: float = 30.0,
        orderbook_ttl_s: float = 5.0,
    ) -> None:
        self._redis_url = redis_url
        self._ticker_ttl_s = ticker_ttl_s
        self._ohlcv_ttl_s = ohlcv_ttl_s
        self._orderbook_ttl_s = orderbook_ttl_s
        self._redis: Any = None
        self._connected = False
        # Fallback in-memory cache when Redis is unavailable
        self._mem_cache: dict[str, tuple[float, Any]] = {}

    async def connect(self) -> None:
        """Connect to Redis. Silently falls back to in-memory on failure."""
        if aioredis is None:
            logger.warning("redis package not installed — using in-memory cache")
            return
        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
            )
            await self._redis.ping()
            self._connected = True
            logger.info("MarketDataCache connected to Redis")
        except Exception as exc:
            logger.warning("Redis unavailable, using in-memory cache: %s", exc)
            self._redis = None
            self._connected = False

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:
                pass
            finally:
                self._redis = None
                self._connected = False
        self._mem_cache.clear()

    # ── Ticker (Price) ──────────────────────────────────────────────

    async def get_ticker(self, symbol: str) -> Price | None:
        """Get cached ticker price for a symbol."""
        key = f"tsar:ticker:{symbol}"
        data = await self._get(key)
        if data is None:
            return None
        try:
            return Price(
                symbol=data["symbol"],
                last=float(data["last"]),
                bid=float(data["bid"]),
                ask=float(data["ask"]),
                timestamp=datetime.fromisoformat(data["timestamp"]),
            )
        except (KeyError, ValueError):
            return None

    async def set_ticker(self, price: Price) -> None:
        """Cache a ticker price."""
        key = f"tsar:ticker:{price.symbol}"
        data = {
            "symbol": price.symbol,
            "last": price.last,
            "bid": price.bid,
            "ask": price.ask,
            "timestamp": price.timestamp.isoformat(),
        }
        await self._set(key, data, self._ticker_ttl_s)

    # ── OHLCV ───────────────────────────────────────────────────────

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV] | None:
        """Get cached OHLCV data."""
        key = f"tsar:ohlcv:{symbol}:{timeframe}:{limit}"
        data = await self._get(key)
        if data is None:
            return None
        try:
            return [
                OHLCV(
                    timestamp=datetime.fromisoformat(bar["t"]),
                    open=float(bar["o"]),
                    high=float(bar["h"]),
                    low=float(bar["l"]),
                    close=float(bar["c"]),
                    volume=float(bar["v"]),
                )
                for bar in data
            ]
        except (KeyError, ValueError):
            return None

    async def set_ohlcv(self, symbol: str, timeframe: str, limit: int, candles: list[OHLCV]) -> None:
        """Cache OHLCV data."""
        key = f"tsar:ohlcv:{symbol}:{timeframe}:{limit}"
        data = [
            {
                "t": c.timestamp.isoformat(),
                "o": c.open,
                "h": c.high,
                "l": c.low,
                "c": c.close,
                "v": c.volume,
            }
            for c in candles
        ]
        await self._set(key, data, self._ohlcv_ttl_s)

    # ── Order Book ──────────────────────────────────────────────────

    async def get_orderbook(self, symbol: str, depth: int) -> OrderBook | None:
        """Get cached order book."""
        key = f"tsar:ob:{symbol}:{depth}"
        data = await self._get(key)
        if data is None:
            return None
        try:
            return OrderBook(
                symbol=data["symbol"],
                bids=tuple(
                    OrderBookLevel(price=float(b[0]), quantity=float(b[1]))
                    for b in data["bids"]
                ),
                asks=tuple(
                    OrderBookLevel(price=float(a[0]), quantity=float(a[1]))
                    for a in data["asks"]
                ),
                timestamp=datetime.fromisoformat(data["timestamp"]),
            )
        except (KeyError, ValueError):
            return None

    async def set_orderbook(self, book: OrderBook, depth: int) -> None:
        """Cache order book data."""
        key = f"tsar:ob:{book.symbol}:{depth}"
        data = {
            "symbol": book.symbol,
            "bids": [[b.price, b.quantity] for b in book.bids],
            "asks": [[a.price, a.quantity] for a in book.asks],
            "timestamp": book.timestamp.isoformat(),
        }
        await self._set(key, data, self._orderbook_ttl_s)

    # ── Internal ────────────────────────────────────────────────────

    async def _get(self, key: str) -> Any:
        """Read from Redis or fallback cache."""
        now = time.monotonic()
        if self._connected and self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw is not None:
                    return json.loads(raw)
            except Exception as exc:
                logger.debug("Redis get error for %s: %s", key, exc)

        # Fallback to in-memory
        entry = self._mem_cache.get(key)
        if entry is not None:
            expires_at, value = entry
            if now < expires_at:
                return value
            del self._mem_cache[key]
        return None

    async def _set(self, key: str, value: Any, ttl_s: float) -> None:
        """Write to Redis and in-memory fallback."""
        serialized = json.dumps(value, default=str)
        if self._connected and self._redis is not None:
            try:
                await self._redis.set(key, serialized, ex=max(1, int(ttl_s)))
            except Exception as exc:
                logger.debug("Redis set error for %s: %s", key, exc)

        # Always write to in-memory fallback
        self._mem_cache[key] = (time.monotonic() + ttl_s, value)

        # Prune stale entries from memory cache (keep max 500)
        if len(self._mem_cache) > 500:
            now = time.monotonic()
            stale = [k for k, (exp, _) in self._mem_cache.items() if now >= exp]
            for k in stale:
                del self._mem_cache[k]
class CcxtGateway(ExchangeGateway):
    """Exchange gateway using ccxt REST API + WebSocket streaming.

    Implements the full ExchangeGateway interface with:
    - Async ccxt operations via ccxt.async_support
    - aiohttp WebSocket for real-time Binance price streaming (H-019)
    - Redis-based market data caching (H-020)
    - Automatic retry with exponential backoff on transient errors
    - Rate limiting (ccxt built-in + local tracking)
    - Sandbox/testnet support
    - Polling-based ticker subscription (Day1 fallback)
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
        redis_url: str = "redis://localhost:6379/0",
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

        # Ticker subscriptions (polling-based Day1 fallback)
        self._ticker_tasks: dict[str, asyncio.Task[None]] = {}
        self._ticker_cancel_events: dict[str, asyncio.Event] = {}

        # WebSocket streaming (H-019)
        self._ws_session: aiohttp.ClientSession | None = None
        self._ws_tasks: dict[str, asyncio.Task[None]] = {}
        self._ws_cancel_events: dict[str, asyncio.Event] = {}
        self._ws_base_url: str = "wss://stream.binance.com:9443/ws"

        # Market data cache (H-020)
        redis_url_cfg = cfg.get("redis_url", redis_url)
        self._cache = MarketDataCache(redis_url=redis_url_cfg)

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

            # Initialize market data cache (H-020)
            await self._cache.connect()

            # Initialize aiohttp session for WebSocket streaming (H-019)
            if self._ws_session is None or self._ws_session.closed:
                self._ws_session = aiohttp.ClientSession()

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

        Cancels all ticker and WebSocket subscriptions, closes the
        exchange connection, cache, and aiohttp session.
        Idempotent — safe to call multiple times.
        """
        # Cancel all active ticker subscriptions (polling)
        for symbol in list(self._ticker_tasks.keys()):
            await self._unsubscribe_ticker(symbol)

        # Cancel all active WebSocket subscriptions
        for symbol in list(self._ws_tasks.keys()):
            await self._unsubscribe_ws_ticker(symbol)

        # Close aiohttp session
        if self._ws_session is not None and not self._ws_session.closed:
            try:
                await self._ws_session.close()
            except Exception as exc:
                logger.warning("Error closing aiohttp session: %s", exc)
            finally:
                self._ws_session = None

        # Disconnect cache
        await self._cache.disconnect()

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

        # Check cache first (H-020)
        cached = await self._cache.get_ticker(symbol)
        if cached is not None:
            return cached

        try:
            raw = await self._retry_on_transient(
                self._exchange.fetch_ticker, symbol
            )
            price = Price(
                symbol=symbol,
                last=float(raw["last"] or 0),
                bid=float(raw.get("bid") or 0),
                ask=float(raw.get("ask") or 0),
                timestamp=_ts_to_dt(raw.get("timestamp")),
            )
            await self._cache.set_ticker(price)
            return price
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

        # Check cache first (H-020)
        cached = await self._cache.get_ohlcv(symbol, timeframe.value, limit)
        if cached is not None:
            return cached

        try:
            raw = await self._retry_on_transient(
                self._exchange.fetch_ohlcv,
                symbol,
                timeframe.value,
                limit=limit,
            )
            candles = [
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
            await self._cache.set_ohlcv(symbol, timeframe.value, limit, candles)
            return candles
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

        # Check cache first (H-020)
        cached = await self._cache.get_orderbook(symbol, depth)
        if cached is not None:
            return cached

        try:
            raw = await self._retry_on_transient(
                self._exchange.fetch_order_book, symbol, limit=depth
            )
            book = OrderBook(
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
            await self._cache.set_orderbook(book, depth)
            return book
        except ccxt.BadSymbol as exc:
            raise LookupError(f"Symbol not found: {symbol}") from exc

    # ═══════════════════════════════════════════════════════════════

    # ACCOUNT (READ)

    async def get_balance(self) -> dict[str, Balance]:
        """Get account balances for all assets.

        Returns:
            Dict mapping asset symbol to Balance (free, used, total).

        Raises:
            ConnectionError: Not connected to the exchange.
        """
        self._ensure_connected()
        assert self._exchange is not None

        raw = await self._retry_on_transient(self._exchange.fetch_balance)
        per_currency: dict[str, dict[str, float]] = {}

        # Build per_currency from ccxt standard format
        for asset, balance_info in raw.items():
            if isinstance(balance_info, dict) and "total" in balance_info:
                per_currency[asset] = {
                    "free": float(balance_info.get("free", 0) or 0),
                    "used": float(balance_info.get("used", 0) or 0),
                    "total": float(balance_info.get("total", 0) or 0),
                }

        usdt = per_currency.get("USDT", per_currency.get("usdt", {}))
        result: dict[str, Balance] = {}
        result["USDT"] = Balance(
            total=usdt.get("total", 0.0),
            free=usdt.get("free", 0.0),
            used=usdt.get("used", 0.0),
            currency="USDT",
            per_currency=per_currency,
        )
        return result

    async def get_positions(self) -> list[Position]:
        """Get all open positions.

        Returns:
            List of Position objects with symbol, side, size, entry price, PnL.

        Raises:
            ConnectionError: Not connected to the exchange.
        """
        

        self._ensure_connected()
        assert self._exchange is not None

        try:
            raw_positions = await self._retry_on_transient(
                self._exchange.fetch_positions
            )
        except Exception as exc:
            logger.warning("fetch_positions failed, returning empty: %s", exc)
            return []

        positions: list[Position] = []
        for raw in raw_positions:
            size = float(raw.get("contracts", 0) or 0)
            if size == 0:
                continue

            side_str = raw.get("side", "long")
            side = OrderSide.BUY if side_str == "long" else OrderSide.SELL

            positions.append(Position(
                symbol=raw.get("symbol", ""),
                side=side,
                quantity=size,
                entry_price=float(raw.get("entryPrice", 0) or 0),
                current_price=float(raw.get("markPrice", 0) or raw.get("lastPrice", 0) or 0),
                unrealized_pnl=float(raw.get("unrealizedPnl", 0) or 0),
                leverage=float(raw.get("leverage", 1) or 1),
                liquidation_price=(
                    float(raw["liquidationPrice"])
                    if raw.get("liquidationPrice") else None
                ),
                timestamp=_ts_to_dt(raw.get("timestamp")),
            ))

        return positions

    async def get_ticker(self, symbol: str) -> Price:
        """Get full ticker for a symbol (alias for get_price).

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").

        Returns:
            Price with last, bid, ask, volume, and timestamp.
        """
        return await self.get_price(symbol)

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> list[Trade]:
        """Get recent trades for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            limit: Number of trades to return (default 50).

        Returns:
            List of Trade objects, most recent first.
        """
        self._ensure_connected()
        assert self._exchange is not None

        try:
            raw_trades = await self._retry_on_transient(
                self._exchange.fetch_trades, symbol, limit=limit
            )
        except ccxt.BadSymbol as exc:
            raise LookupError(f"Symbol not found: {symbol}") from exc

        trades: list[Trade] = []
        for raw in raw_trades:
            side_str = raw.get("side", "buy")
            side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL
            trades.append(Trade(
                id=str(raw.get("id", "")),
                symbol=raw.get("symbol", symbol),
                side=side,
                price=float(raw.get("price", 0) or 0),
                quantity=float(raw.get("amount", 0) or 0),
                cost=float(raw.get("cost", 0) or 0),
                fee=float((raw.get("fee", {}) or {}).get("cost", 0) or 0),
                fee_currency=(raw.get("fee", {}) or {}).get("currency", ""),
                timestamp=_ts_to_dt(raw.get("timestamp")),
            ))

        return trades

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an open order.

        Args:
            order_id: Exchange-assigned order ID.
            symbol: Trading pair (required by most exchanges).

        Returns:
            True if cancelled successfully.
        """
        self._ensure_connected()
        assert self._exchange is not None

        try:
            await self._retry_on_transient(
                self._exchange.cancel_order, order_id, symbol
            )
            logger.info("Order %%s cancelled on %%s", order_id, symbol)
            return True
        except ccxt.OrderNotFound as exc:
            raise LookupError(f"Order not found: {order_id}") from exc

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
    # WEBSOCKET STREAMING (C-023 / H-019)
    # ═══════════════════════════════════════════════════════════════

    async def subscribe_ticker_ws(
        self,
        symbol: str,
        callback: Callable[[Price], Any],
    ) -> None:
        """Subscribe to real-time price updates via Binance WebSocket.

        Uses aiohttp WebSocket to connect to Binance's streaming API.
        Falls back to polling if WebSocket fails.

        The Binance WS stream format: wss://stream.binance.com:9443/ws/<symbol>@ticker
        Sends JSON with 'c' (last price), 'b' (best bid), 'a' (best ask).

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            callback: Async or sync callable invoked with each Price update.

        Raises:
            ConnectionError: Not connected to the exchange.
        """
        if self._status != ConnectionStatus.CONNECTED:
            raise ConnectionError(
                f"Not connected to {self._exchange_id} "
                f"(status={self._status.value})"
            )

        if symbol in self._ws_tasks:
            logger.warning("Already subscribed to %s WS ticker — ignoring", symbol)
            return

        cancel_event = asyncio.Event()
        self._ws_cancel_events[symbol] = cancel_event

        task = asyncio.create_task(
            self._ws_ticker_loop(symbol, callback, cancel_event),
            name=f"ws-ticker:{symbol}",
        )
        self._ws_tasks[symbol] = task
        logger.info("Subscribed to %s ticker (WebSocket mode)", symbol)

    async def _ws_ticker_loop(
        self,
        symbol: str,
        callback: Callable[[Price], Any],
        cancel: asyncio.Event,
    ) -> None:
        """WebSocket loop for real-time ticker streaming.

        Connects to Binance WebSocket, parses ticker messages, and
        invokes the callback with Price objects. Reconnects on failure
        with exponential backoff.
        """
        # Binance uses lowercase symbol without slash: BTC/USDT -> btcusdt
        ws_symbol = symbol.replace("/", "").lower()
        ws_url = f"{self._ws_base_url}/{ws_symbol}@ticker"

        backoff_s = 1.0
        max_backoff_s = 60.0

        while not cancel.is_set():
            if self._ws_session is None or self._ws_session.closed:
                logger.warning("aiohttp session closed — stopping WS for %s", symbol)
                break

            try:
                async with self._ws_session.ws_connect(
                    ws_url,
                    heartbeat=30.0,
                    timeout=aiohttp.ClientWSTimeout(ws_close=10),
                ) as ws:
                    logger.info("WebSocket connected for %s", symbol)
                    backoff_s = 1.0  # Reset backoff on successful connect

                    async for msg in ws:
                        if cancel.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                price = Price(
                                    symbol=symbol,
                                    last=float(data.get("c", 0)),
                                    bid=float(data.get("b", 0)),
                                    ask=float(data.get("a", 0)),
                                    timestamp=_utcnow(),
                                )
                                # Update cache
                                await self._cache.set_ticker(price)

                                result = callback(price)
                                if asyncio.iscoroutine(result):
                                    await result
                            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                                logger.debug("WS parse error for %s: %s", symbol, exc)
                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSED,
                        ):
                            logger.warning("WS closed/error for %s, reconnecting...", symbol)
                            break

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "WS error for %s (%s), reconnecting in %.1fs: %s",
                    symbol,
                    type(exc).__name__,
                    backoff_s,
                    exc,
                )
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, max_backoff_s)

        logger.info("WebSocket ticker loop stopped for %s", symbol)

    async def _unsubscribe_ws_ticker(self, symbol: str) -> None:
        """Cancel a WebSocket ticker subscription."""
        cancel_event = self._ws_cancel_events.pop(symbol, None)
        task = self._ws_tasks.pop(symbol, None)

        if cancel_event is not None:
            cancel_event.set()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        logger.debug("Unsubscribed from %s WS ticker", symbol)

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

    # ═══════════════════════════════════════════════════════════════
    # LIQUIDITY MODELING (M-004)
    # ═══════════════════════════════════════════════════════════════

    async def estimate_slippage(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
    ) -> dict[str, Any]:
        """Estimate slippage for a given order based on order book depth.

        Walks the order book to estimate the average fill price and
        slippage relative to the best bid/ask.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: Order side (BUY or SELL).
            quantity: Order quantity in base asset.

        Returns:
            Dict with:
                - best_price: Best bid (sell) or ask (buy)
                - avg_fill_price: Volume-weighted average fill price
                - slippage_bps: Estimated slippage in basis points
                - book_depth_usd: Total depth consumed in USD
                - levels_consumed: Number of order book levels consumed
                - sufficient_liquidity: Whether book has enough depth
        """
        self._ensure_connected()

        # Fetch order book with enough depth
        book = await self.get_orderbook(symbol, depth=50)

        if side == OrderSide.BUY:
            # Buys consume asks (ascending price)
            levels = book.asks
            best_price = levels[0].price if levels else 0.0
        else:
            # Sells consume bids (descending price)
            levels = book.bids
            best_price = levels[0].price if levels else 0.0

        if not levels or best_price <= 0:
            return {
                "best_price": 0.0,
                "avg_fill_price": 0.0,
                "slippage_bps": 0.0,
                "book_depth_usd": 0.0,
                "levels_consumed": 0,
                "sufficient_liquidity": False,
            }

        # Walk the book to fill the quantity
        remaining_qty = quantity
        total_cost = 0.0
        levels_consumed = 0
        total_depth_usd = 0.0

        for level in levels:
            if remaining_qty <= 0:
                break

            available_qty = level.quantity
            fill_qty = min(remaining_qty, available_qty)
            total_cost += fill_qty * level.price
            total_depth_usd += fill_qty * level.price
            remaining_qty -= fill_qty
            levels_consumed += 1

        filled_qty = quantity - remaining_qty
        avg_fill_price = total_cost / filled_qty if filled_qty > 0 else best_price

        # Slippage in basis points
        if best_price > 0:
            slippage_bps = abs(avg_fill_price - best_price) / best_price * 10_000
        else:
            slippage_bps = 0.0

        sufficient_liquidity = remaining_qty <= 0

        if not sufficient_liquidity:
            logger.warning(
                "Insufficient liquidity for %s %s %.6f — %.6f unfilled (%d levels consumed)",
                symbol, side.value, quantity, remaining_qty, levels_consumed,
            )

        return {
            "best_price": round(best_price, 8),
            "avg_fill_price": round(avg_fill_price, 8),
            "slippage_bps": round(slippage_bps, 2),
            "book_depth_usd": round(total_depth_usd, 2),
            "levels_consumed": levels_consumed,
            "sufficient_liquidity": sufficient_liquidity,
            "unfilled_quantity": round(remaining_qty, 8),
        }

    async def get_liquidity_summary(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        """Get a summary of order book liquidity for a symbol.

        Returns:
            Dict with bid/ask depth, spread, and liquidity score.
        """
        self._ensure_connected()

        book = await self.get_orderbook(symbol, depth=20)

        if not book.bids or not book.asks:
            return {
                "symbol": symbol,
                "spread_bps": 0.0,
                "bid_depth_usd": 0.0,
                "ask_depth_usd": 0.0,
                "total_depth_usd": 0.0,
                "liquidity_score": 0.0,
            }

        best_bid = book.bids[0].price
        best_ask = book.asks[0].price
        mid_price = (best_bid + best_ask) / 2

        # Spread in bps
        spread_bps = (best_ask - best_bid) / mid_price * 10_000 if mid_price > 0 else 0.0

        # Depth: sum of (price * qty) for top 20 levels
        bid_depth_usd = sum(l.price * l.quantity for l in book.bids)
        ask_depth_usd = sum(l.price * l.quantity for l in book.asks)
        total_depth = bid_depth_usd + ask_depth_usd

        # Liquidity score: 0-1 based on spread and depth
        # Tight spread + high depth = high score
        spread_score = max(0, 1.0 - spread_bps / 50.0)  # 50bps = 0 score
        depth_score = min(1.0, total_depth / 1_000_000)  # $1M = max score
        liquidity_score = (spread_score * 0.4 + depth_score * 0.6)

        return {
            "symbol": symbol,
            "spread_bps": round(spread_bps, 2),
            "bid_depth_usd": round(bid_depth_usd, 2),
            "ask_depth_usd": round(ask_depth_usd, 2),
            "total_depth_usd": round(total_depth, 2),
            "liquidity_score": round(liquidity_score, 4),
        }
