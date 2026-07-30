"""
TSAR Domain Tools — Market Data Tools.

What the agent SEES. Provides deep market microstructure data beyond
simple price/ohlcv that agents need for informed decision-making.

Tools (9 total):
  1. Real-Time Price Feed     — WebSocket streaming, multi-symbol (BTC, ETH, SOL)
  2. Historical OHLCV         — Multi-timeframe candles with efficient storage
  3. Order Book Depth          — Bid/ask spread monitoring, liquidity wall detection
  4. Funding Rate Monitor      — Perpetual futures funding + arbitrage signals
  5. Open Interest Tracker     — OI data + leverage concentration detection
  6. Liquidation Feed          — Cascade detection (mass liquidations)
  7. Volume Profile            — Volume at price levels, POC detection
  8. Trade Feed                — Individual trades, large trade (whale) detection
  9. Spread Analysis           — Bid-ask spread over time, liquidity scoring

All tools are async and operate through the ExchangeGateway interface.
Data is cached to minimize API calls.
"""

from __future__ import annotations

import asyncio
import bisect
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

if TYPE_CHECKING:
    from src.interfaces.exchange_gateway import ExchangeGateway
    from src.interfaces.types import OrderBook, Trade

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Default symbols to track
DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

# Binance WebSocket endpoints
BINANCE_WS_BASE = "wss://fstream.binance.com/ws"
BINANCE_WS_STREAM = "wss://fstream.binance.com/stream"

# Supported timeframes for historical OHLCV
TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RealtimePrice:
    """Real-time price tick from WebSocket stream.

    Attributes:
        symbol: Trading pair.
        last: Last traded price.
        bid: Best bid price.
        ask: Best ask price.
        volume_24h: 24-hour volume in base asset.
        quote_volume_24h: 24-hour volume in quote (USDT).
        price_change_pct: 24-hour price change percentage.
        timestamp: Time of the price observation (UTC).
    """

    symbol: str
    last: float
    bid: float
    ask: float
    volume_24h: float = 0.0
    quote_volume_24h: float = 0.0
    price_change_pct: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OHLCVCandle:
    """A single OHLCV candle with metadata.

    Attributes:
        timestamp: Candle open time (UTC).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Base asset volume.
        quote_volume: Quote asset volume.
        trades: Number of trades in the candle.
        is_closed: Whether this candle is finalized.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = 0.0
    trades: int = 0
    is_closed: bool = True


@dataclass(frozen=True)
class OHLCVStore:
    """Stored OHLCV data with metadata.

    Attributes:
        symbol: Trading pair.
        timeframe: Candle timeframe.
        candles: Tuple of candles, oldest first.
        count: Number of candles.
        first_ts: Timestamp of oldest candle.
        last_ts: Timestamp of newest candle.
    """

    symbol: str
    timeframe: str
    candles: tuple[OHLCVCandle, ...]
    count: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None


@dataclass(frozen=True)
class OrderBookDepth:
    """Deep order book analysis.

    Attributes:
        symbol: Trading pair.
        best_bid: Highest bid price.
        best_ask: Lowest ask price.
        mid_price: Midpoint of best bid/ask.
        spread_bps: Bid-ask spread in basis points.
        bid_depth_usd: Total bid-side liquidity in USD.
        ask_depth_usd: Total ask-side liquidity in USD.
        imbalance: Bid/ask imbalance ratio (-1 to +1).
        bid_wall_price: Price of largest bid wall (if any).
        bid_wall_size_usd: Size of largest bid wall in USD.
        ask_wall_price: Price of largest ask wall (if any).
        ask_wall_size_usd: Size of largest ask wall in USD.
        wall_imbalance: Wall imbalance (positive = bid wall dominance).
        levels_analyzed: Number of book levels analyzed.
        timestamp: When the analysis was performed.
    """

    symbol: str
    best_bid: float
    best_ask: float
    mid_price: float
    spread_bps: float
    bid_depth_usd: float
    ask_depth_usd: float
    imbalance: float  # -1 to +1
    bid_wall_price: float | None = None
    bid_wall_size_usd: float = 0.0
    ask_wall_price: float | None = None
    ask_wall_size_usd: float = 0.0
    wall_imbalance: float = 0.0
    levels_analyzed: int = 0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class FundingRate:
    """Perpetual futures funding rate data.

    Attributes:
        symbol: Trading pair.
        current_rate: Current funding rate (positive = longs pay shorts).
        predicted_rate: Predicted next funding rate.
        annualized_rate: Annualized funding rate.
        sentiment: Derived sentiment (-1 to +1).
        funding_arb_signal: Arbitrage signal description.
        funding_arb_score: Arbitrage opportunity score (0-1).
        next_funding_time: When the next funding settlement occurs.
        timestamp: When the data was fetched.
    """

    symbol: str
    current_rate: float
    predicted_rate: float
    annualized_rate: float
    sentiment: float
    funding_arb_signal: str = ""
    funding_arb_score: float = 0.0
    next_funding_time: datetime | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OpenInterest:
    """Open interest data for perpetual futures.

    Attributes:
        symbol: Trading pair.
        open_interest: Total open interest in base asset.
        open_interest_usd: Total open interest in USD.
        change_1h: 1-hour change in open interest.
        change_1h_pct: 1-hour percentage change.
        change_24h: 24-hour change in open interest.
        change_24h_pct: 24-hour percentage change.
        oi_to_volume_ratio: Open interest / 24h volume ratio.
        leverage_concentration: Estimated leverage concentration (0-1).
            High = heavy leveraged positions (squeeze risk).
        leverage_signal: Derived leverage signal.
        timestamp: When the data was fetched.
    """

    symbol: str
    open_interest: float
    open_interest_usd: float
    change_1h: float = 0.0
    change_1h_pct: float = 0.0
    change_24h: float = 0.0
    change_24h_pct: float = 0.0
    oi_to_volume_ratio: float = 0.0
    leverage_concentration: float = 0.0
    leverage_signal: str = ""
    timestamp: datetime | None = None


@dataclass(frozen=True)
class LiquidationEvent:
    """A single liquidation event.

    Attributes:
        symbol: Trading pair.
        side: Liquidated side (BUY = long liquidated, SELL = short liquidated).
        price: Liquidation price.
        quantity: Liquidated quantity in base asset.
        quantity_usd: Liquidated quantity in USD.
        timestamp: When the liquidation occurred.
    """

    symbol: str
    side: str  # "buy" or "sell"
    price: float
    quantity: float
    quantity_usd: float
    timestamp: datetime | None = None


@dataclass(frozen=True)
class LiquidationSummary:
    """Aggregated liquidation data over a time window.

    Attributes:
        symbol: Trading pair.
        window_minutes: Aggregation window in minutes.
        total_long_liqs: Total long liquidations in USD.
        total_short_liqs: Total short liquidations in USD.
        net_liq: Net liquidation (positive = more longs liquidated).
        long_liq_count: Number of long liquidation events.
        short_liq_count: Number of short liquidation events.
        largest_liq: Largest single liquidation in USD.
        cascade_risk: Estimated cascade risk (0-1).
        cascade_detected: Whether a cascade is actively occurring.
        cascade_direction: Direction of cascade ("long", "short", "none").
        avg_liq_interval_s: Average seconds between liquidations in densest window.
        timestamp: When the summary was computed.
    """

    symbol: str
    window_minutes: int
    total_long_liqs: float
    total_short_liqs: float
    net_liq: float
    long_liq_count: int = 0
    short_liq_count: int = 0
    largest_liq: float = 0.0
    cascade_risk: float = 0.0
    cascade_detected: bool = False
    cascade_direction: str = "none"
    avg_liq_interval_s: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class TradeFlowAnalysis:
    """Trade flow analysis — buy vs sell pressure.

    Attributes:
        symbol: Trading pair.
        window_minutes: Analysis window in minutes.
        buy_volume: Total buy volume in base asset.
        sell_volume: Total sell volume in base asset.
        buy_volume_usd: Total buy volume in USD.
        sell_volume_usd: Total sell volume in USD.
        net_flow: Net buy volume (positive = buying pressure).
        net_flow_usd: Net buy volume in USD.
        large_trade_count: Number of trades > threshold.
        large_trade_bias: Net bias of large trades (-1 to +1).
        whale_detected: Whether a whale trade was detected.
        whale_trades: List of whale trade details.
        vwap: Volume-weighted average price over the window.
        timestamp: When the analysis was performed.
    """

    symbol: str
    window_minutes: int
    buy_volume: float
    sell_volume: float
    buy_volume_usd: float
    sell_volume_usd: float
    net_flow: float
    net_flow_usd: float
    large_trade_count: int = 0
    large_trade_bias: float = 0.0
    whale_detected: bool = False
    whale_trades: tuple[dict[str, Any], ...] = ()
    vwap: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class VolumeProfileLevel:
    """A single price level in the volume profile.

    Attributes:
        price: Price level.
        volume: Total volume at this level.
        volume_pct: Volume as percentage of total.
        buy_volume: Buy volume at this level.
        sell_volume: Sell volume at this level.
        is_poc: Whether this is the Point of Control (highest volume).
        is_value_area: Whether this is in the value area (70% of volume).
    """

    price: float
    volume: float
    volume_pct: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    is_poc: bool = False
    is_value_area: bool = False


@dataclass(frozen=True)
class VolumeProfile:
    """Volume profile — price-level volume distribution.

    Attributes:
        symbol: Trading pair.
        timeframe: Candle timeframe used.
        levels: Volume profile levels sorted by price.
        poc_price: Point of Control (highest volume level).
        poc_volume: Volume at POC.
        value_area_high: Upper bound of value area.
        value_area_low: Lower bound of value area.
        total_volume: Total volume across all levels.
        timestamp: When the profile was computed.
    """

    symbol: str
    timeframe: str = ""
    levels: tuple[VolumeProfileLevel, ...] = ()
    poc_price: float = 0.0
    poc_volume: float = 0.0
    value_area_high: float = 0.0
    value_area_low: float = 0.0
    total_volume: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class SpreadAnalysis:
    """Bid-ask spread analysis over time.

    Attributes:
        symbol: Trading pair.
        window_minutes: Analysis window.
        current_spread_bps: Current spread in basis points.
        avg_spread_bps: Average spread over window.
        min_spread_bps: Minimum spread over window.
        max_spread_bps: Maximum spread over window.
        spread_volatility: Standard deviation of spread.
        liquidity_score: Overall liquidity score (0-1).
        is_widening: Whether spread is currently widening.
        timestamp: When the analysis was performed.
    """

    symbol: str
    window_minutes: int
    current_spread_bps: float
    avg_spread_bps: float
    min_spread_bps: float
    max_spread_bps: float
    spread_volatility: float
    liquidity_score: float
    is_widening: bool = False
    timestamp: datetime | None = None


@dataclass(frozen=True)
class FundingArbOpportunity:
    """A funding rate arbitrage opportunity.

    Attributes:
        symbol: Trading pair.
        spot_exchange: Exchange with spot price.
        futures_exchange: Exchange with futures price.
        funding_rate: Current funding rate.
        annualized_yield: Annualized yield from the arb.
        direction: "long_spot_short_perp" or "short_spot_long_perp".
        confidence: Confidence in the opportunity (0-1).
        notes: Additional context.
    """

    symbol: str
    spot_exchange: str = "binance"
    futures_exchange: str = "binance"
    funding_rate: float = 0.0
    annualized_yield: float = 0.0
    direction: str = ""
    confidence: float = 0.0
    notes: str = ""


# ═══════════════════════════════════════════════════════════════════════
# REAL-TIME PRICE FEED — WebSocket Streaming
# ═══════════════════════════════════════════════════════════════════════


class RealtimePriceFeed:
    """WebSocket-based real-time price feed for Binance Futures.

    Streams ticker data for multiple symbols simultaneously.
    Supports BTC, ETH, SOL and any other Binance Futures pair.

    Usage::

        feed = RealtimePriceFeed(["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        await feed.start()

        # Get latest price
        price = feed.get_latest_price("BTC/USDT")

        # Register callback for price updates
        feed.on_price_update(lambda p: print(f"{p.symbol}: {p.last}"))

        await feed.stop()
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        on_price: Callable[[RealtimePrice], Any] | None = None,
    ) -> None:
        self._symbols = symbols or list(DEFAULT_SYMBOLS)
        self._callbacks: list[Callable[[RealtimePrice], Any]] = []
        if on_price:
            self._callbacks.append(on_price)

        self._latest_prices: dict[str, RealtimePrice] = {}
        self._price_history: dict[str, deque[RealtimePrice]] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._ws_task: asyncio.Task | None = None
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

    def on_price_update(self, callback: Callable[[RealtimePrice], Any]) -> None:
        """Register a callback for price updates."""
        self._callbacks.append(callback)

    def get_latest_price(self, symbol: str) -> RealtimePrice | None:
        """Get the most recent price for a symbol."""
        return self._latest_prices.get(symbol)

    def get_all_latest(self) -> dict[str, RealtimePrice]:
        """Get latest prices for all tracked symbols."""
        return dict(self._latest_prices)

    def get_price_history(self, symbol: str, limit: int = 100) -> list[RealtimePrice]:
        """Get recent price history for a symbol."""
        history = self._price_history.get(symbol, deque())
        return list(history)[-limit:]

    @property
    def is_running(self) -> bool:
        """Whether the WebSocket feed is active."""
        return self._running

    @property
    def tracked_symbols(self) -> list[str]:
        """Symbols being tracked."""
        return list(self._symbols)

    async def start(self) -> None:
        """Start the WebSocket price feed."""
        if self._running:
            return
        self._running = True
        self._ws_task = asyncio.create_task(self._run_loop())
        logger.info("Price feed started for %d symbols", len(self._symbols))

    async def stop(self) -> None:
        """Stop the WebSocket price feed."""
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
        logger.info("Price feed stopped")

    async def add_symbol(self, symbol: str) -> None:
        """Add a symbol to the feed (requires restart)."""
        if symbol not in self._symbols:
            self._symbols.append(symbol)
            if self._running:
                await self.stop()
                await self.start()

    async def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from the feed (requires restart)."""
        if symbol in self._symbols:
            self._symbols.remove(symbol)
            if self._running:
                await self.stop()
                await self.start()

    async def _run_loop(self) -> None:
        """Main WebSocket loop with reconnection."""
        delay = self._reconnect_delay
        while self._running:
            try:
                await self._connect_and_stream()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Price feed connection error: %s", exc)
                if self._running:
                    logger.info("Reconnecting in %.1fs...", delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._max_reconnect_delay)

    async def _connect_and_stream(self) -> None:
        """Connect to Binance WebSocket and stream prices."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed — falling back to REST polling")
            await self._poll_fallback()
            return

        # Build stream names: btcusdt@ticker, ethusdt@ticker, ...
        streams = []
        for sym in self._symbols:
            binance_sym = sym.replace("/", "").lower()
            streams.append(f"{binance_sym}@ticker")

        url = f"{BINANCE_WS_STREAM}?streams={'/'.join(streams)}"
        delay = self._reconnect_delay

        async with websockets.connect(url, ping_interval=20) as ws:
            logger.info("Connected to Binance WebSocket: %d streams", len(streams))
            delay = self._reconnect_delay  # Reset on success

            async for raw_msg in ws:
                if not self._running:
                    break

                try:
                    msg = json.loads(raw_msg)
                    data = msg.get("data", msg)
                    await self._process_ticker(data)
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.debug("Failed to parse WS message: %s", exc)

    async def _process_ticker(self, data: dict[str, Any]) -> None:
        """Process a Binance ticker WebSocket message."""
        try:
            symbol_raw = data.get("s", "")  # e.g. "BTCUSDT"
            # Convert back to slash format
            for tracked in self._symbols:
                if tracked.replace("/", "") == symbol_raw:
                    symbol = tracked
                    break
            else:
                return

            now = datetime.now(UTC)
            price = RealtimePrice(
                symbol=symbol,
                last=float(data.get("c", 0)),        # close = last price
                bid=float(data.get("b", 0)),          # best bid
                ask=float(data.get("a", 0)),          # best ask
                volume_24h=float(data.get("v", 0)),   # base volume
                quote_volume_24h=float(data.get("q", 0)),  # quote volume
                price_change_pct=float(data.get("P", 0)),  # price change %
                timestamp=now,
            )

            self._latest_prices[symbol] = price
            self._price_history[symbol].append(price)

            for cb in self._callbacks:
                try:
                    result = cb(price)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:
                    logger.debug("Price callback error: %s", exc)

        except (ValueError, KeyError) as exc:
            logger.debug("Failed to process ticker: %s", exc)

    async def _poll_fallback(self) -> None:
        """REST polling fallback when websockets is not installed."""
        import httpx

        while self._running:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    for sym in self._symbols:
                        binance_sym = sym.replace("/", "")
                        resp = await client.get(
                            "https://fapi.binance.com/fapi/v1/ticker/24hr",
                            params={"symbol": binance_sym},
                        )
                        resp.raise_for_status()
                        data = resp.json()

                        now = datetime.now(UTC)
                        price = RealtimePrice(
                            symbol=sym,
                            last=float(data.get("lastPrice", 0)),
                            bid=float(data.get("bidPrice", 0) or 0),
                            ask=float(data.get("askPrice", 0) or 0),
                            volume_24h=float(data.get("volume", 0)),
                            quote_volume_24h=float(data.get("quoteVolume", 0)),
                            price_change_pct=float(data.get("priceChangePercent", 0)),
                            timestamp=now,
                        )
                        self._latest_prices[sym] = price
                        self._price_history[sym].append(price)

                        for cb in self._callbacks:
                            try:
                                result = cb(price)
                                if asyncio.iscoroutine(result):
                                    await result
                            except Exception:
                                pass

            except Exception as exc:
                logger.debug("Poll fallback error: %s", exc)

            await asyncio.sleep(2)  # Poll every 2 seconds


# ═══════════════════════════════════════════════════════════════════════
# HISTORICAL OHLCV — Multi-Timeframe Storage
# ═══════════════════════════════════════════════════════════════════════


class HistoricalOHLCVStore:
    """Efficient historical OHLCV storage and retrieval.

    Stores candles in memory with sorted timestamps for fast lookup.
    Supports multiple timeframes and symbols.

    Usage::

        store = HistoricalOHLCVStore(gateway)

        # Fetch and store candles
        data = await store.fetch_and_store("BTC/USDT", "1h", limit=500)

        # Retrieve stored candles
        candles = store.get_candles("BTC/USDT", "1h")

        # Get candles for a time range
        subset = store.get_candles_range("BTC/USDT", "1h", start, end)
    """

    def __init__(
        self,
        gateway: ExchangeGateway,
        max_candles_per_key: int = 5000,
    ) -> None:
        self._gateway = gateway
        self._max_candles = max_candles_per_key

        # Storage: (symbol, timeframe) -> sorted list of OHLCVCandle
        self._store: dict[tuple[str, str], list[OHLCVCandle]] = {}
        # Timestamp index for fast bisect lookups
        self._ts_index: dict[tuple[str, str], list[float]] = {}

    async def fetch_and_store(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
    ) -> OHLCVStore:
        """Fetch candles from exchange and store them.

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe (e.g. "1h", "4h", "1d").
            limit: Number of candles to fetch.

        Returns:
            OHLCVStore with the fetched candles.
        """
        from src.interfaces.types import Timeframe

        tf = Timeframe(timeframe)
        ohlcv_list = await self._gateway.get_ohlcv(symbol, tf, limit=limit)

        candles = []
        for o in ohlcv_list:
            candles.append(OHLCVCandle(
                timestamp=o.timestamp,
                open=o.open,
                high=o.high,
                low=o.low,
                close=o.close,
                volume=o.volume,
                is_closed=True,
            ))

        key = (symbol, timeframe)
        self._merge_candles(key, candles)

        stored = self._store.get(key, [])
        return OHLCVStore(
            symbol=symbol,
            timeframe=timeframe,
            candles=tuple(stored),
            count=len(stored),
            first_ts=stored[0].timestamp if stored else None,
            last_ts=stored[-1].timestamp if stored else None,
        )

    def add_candle(self, symbol: str, timeframe: str, candle: OHLCVCandle) -> None:
        """Add a single candle to the store (e.g., from WebSocket stream)."""
        key = (symbol, timeframe)
        if key not in self._store:
            self._store[key] = []
            self._ts_index[key] = []

        store = self._store[key]
        ts_idx = self._ts_index[key]
        ts = candle.timestamp.timestamp()

        # Check if candle already exists (update if so)
        pos = bisect.bisect_left(ts_idx, ts)
        if pos < len(ts_idx) and abs(ts_idx[pos] - ts) < 1.0:
            store[pos] = candle
        else:
            store.insert(pos, candle)
            ts_idx.insert(pos, ts)

        # Trim to max size
        if len(store) > self._max_candles:
            excess = len(store) - self._max_candles
            del store[:excess]
            del ts_idx[:excess]

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int | None = None,
    ) -> list[OHLCVCandle]:
        """Get stored candles for a symbol and timeframe.

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe.
            limit: Max candles to return (newest first, then reversed to oldest first).

        Returns:
            List of OHLCVCandle, oldest first.
        """
        key = (symbol, timeframe)
        candles = self._store.get(key, [])
        if limit:
            candles = candles[-limit:]
        return list(candles)

    def get_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVCandle]:
        """Get candles within a time range.

        Uses bisect for O(log n) range lookup.

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe.
            start: Start timestamp (inclusive).
            end: End timestamp (inclusive).

        Returns:
            List of OHLCVCandle in the range, oldest first.
        """
        key = (symbol, timeframe)
        store = self._store.get(key, [])
        ts_idx = self._ts_index.get(key, [])

        if not store:
            return []

        start_ts = start.timestamp()
        end_ts = end.timestamp()

        left = bisect.bisect_left(ts_idx, start_ts)
        right = bisect.bisect_right(ts_idx, end_ts)

        return list(store[left:right])

    def get_latest(self, symbol: str, timeframe: str) -> OHLCVCandle | None:
        """Get the most recent candle for a symbol/timeframe."""
        key = (symbol, timeframe)
        store = self._store.get(key, [])
        return store[-1] if store else None

    def get_all_symbols(self) -> list[str]:
        """Get all symbols with stored data."""
        return list({k[0] for k in self._store})

    def get_stored_timeframes(self, symbol: str) -> list[str]:
        """Get all timeframes stored for a symbol."""
        return [k[1] for k in self._store if k[0] == symbol]

    def candle_count(self, symbol: str, timeframe: str) -> int:
        """Get the number of stored candles for a symbol/timeframe."""
        return len(self._store.get((symbol, timeframe), []))

    def _merge_candles(self, key: tuple[str, str], new_candles: list[OHLCVCandle]) -> None:
        """Merge new candles into existing store, deduplicating by timestamp."""
        if key not in self._store:
            self._store[key] = []
            self._ts_index[key] = []

        store = self._store[key]
        ts_idx = self._ts_index[key]

        for candle in new_candles:
            ts = candle.timestamp.timestamp()
            pos = bisect.bisect_left(ts_idx, ts)
            if pos < len(ts_idx) and abs(ts_idx[pos] - ts) < 1.0:
                # Update existing
                store[pos] = candle
            else:
                store.insert(pos, candle)
                ts_idx.insert(pos, ts)

        # Trim
        if len(store) > self._max_candles:
            excess = len(store) - self._max_candles
            del store[:excess]
            del ts_idx[:excess]


# ═══════════════════════════════════════════════════════════════════════
# MARKET DATA TOOLS — Main Class
# ═══════════════════════════════════════════════════════════════════════


class MarketDataTools:
    """Deep market microstructure analysis tools.

    Provides all 9 market intelligence tools:
    1. Real-Time Price Feed (WebSocket streaming)
    2. Historical OHLCV (multi-timeframe storage)
    3. Order Book Depth (spread monitoring, wall detection)
    4. Funding Rate Monitor (arbitrage signals)
    5. Open Interest Tracker (leverage concentration)
    6. Liquidation Feed (cascade detection)
    7. Volume Profile (POC detection)
    8. Trade Feed (whale alerts)
    9. Spread Analysis (liquidity scoring)
    """

    description = (
        "Market data tools: real-time price feed, historical OHLCV, "
        "order book depth, funding rates, OI, liquidations, "
        "volume profile, trade flow, spread analysis"
    )

    def __init__(
        self,
        gateway: ExchangeGateway,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config or {}

        # Tool 1: Real-time price feed
        symbols = self._config.get("symbols", list(DEFAULT_SYMBOLS))
        self._price_feed = RealtimePriceFeed(symbols=symbols)

        # Tool 2: Historical OHLCV store
        self._ohlcv_store = HistoricalOHLCVStore(
            gateway=gateway,
            max_candles_per_key=self._config.get("max_candles", 5000),
        )

        # Caches with TTL
        self._funding_cache: dict[str, tuple[float, FundingRate]] = {}
        self._oi_cache: dict[str, tuple[float, OpenInterest]] = {}
        self._oi_history: dict[str, list[tuple[float, float]]] = {}  # symbol -> [(ts, oi_usd)]
        self._spread_history: dict[str, list[tuple[float, float]]] = {}
        self._liq_buffer: dict[str, list[LiquidationEvent]] = defaultdict(list)
        self._cache_ttl_s = self._config.get("cache_ttl_s", 30)

    # ── Tool 1: Real-Time Price Feed ────────────────────────────────

    async def start_price_feed(self) -> None:
        """Start the real-time WebSocket price feed."""
        await self._price_feed.start()

    async def stop_price_feed(self) -> None:
        """Stop the real-time WebSocket price feed."""
        await self._price_feed.stop()

    def get_realtime_price(self, symbol: str) -> RealtimePrice | None:
        """Get latest real-time price for a symbol."""
        return self._price_feed.get_latest_price(symbol)

    def get_all_realtime_prices(self) -> dict[str, RealtimePrice]:
        """Get latest prices for all tracked symbols."""
        return self._price_feed.get_all_latest()

    def get_price_history(self, symbol: str, limit: int = 100) -> list[RealtimePrice]:
        """Get recent price tick history for a symbol."""
        return self._price_feed.get_price_history(symbol, limit)

    @property
    def price_feed(self) -> RealtimePriceFeed:
        """Access the underlying price feed instance."""
        return self._price_feed

    # ── Tool 2: Historical OHLCV ────────────────────────────────────

    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
    ) -> OHLCVStore:
        """Fetch and store historical OHLCV candles.

        Supports multiple timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w.

        Candles are stored in memory with sorted timestamps for efficient
        range queries and retrieval.

        Args:
            symbol: Trading pair.
            timeframe: Candle interval.
            limit: Number of candles to fetch.

        Returns:
            OHLCVStore with fetched candles and metadata.
        """
        return await self._ohlcv_store.fetch_and_store(symbol, timeframe, limit)

    def get_stored_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int | None = None,
    ) -> list[OHLCVCandle]:
        """Get stored candles without fetching from exchange.

        Args:
            symbol: Trading pair.
            timeframe: Candle interval.
            limit: Max candles to return.

        Returns:
            List of OHLCVCandle, oldest first.
        """
        return self._ohlcv_store.get_candles(symbol, timeframe, limit)

    def get_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVCandle]:
        """Get candles in a time range from the store.

        Uses bisect for O(log n) lookup.

        Args:
            symbol: Trading pair.
            timeframe: Candle interval.
            start: Start time (inclusive).
            end: End time (inclusive).

        Returns:
            List of OHLCVCandle in range, oldest first.
        """
        return self._ohlcv_store.get_candles_range(symbol, timeframe, start, end)

    @property
    def ohlcv_store(self) -> HistoricalOHLCVStore:
        """Access the underlying OHLCV store."""
        return self._ohlcv_store

    # ── Tool 3: Order Book Depth Analysis ───────────────────────────

    async def get_orderbook_depth(
        self,
        symbol: str,
        levels: int = 50,
        wall_threshold_usd: float = 50_000,
    ) -> OrderBookDepth:
        """Analyze order book depth with wall detection and spread monitoring.

        Walks the order book to compute total bid/ask depth, imbalance,
        and detects large walls (limit orders significantly larger than
        surrounding levels). Also tracks spread over time.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            levels: Number of book levels to analyze.
            wall_threshold_usd: Minimum USD size to flag as a wall.

        Returns:
            OrderBookDepth with full analysis.
        """
        book = await self._gateway.get_orderbook(symbol, depth=levels)

        if not book.bids or not book.asks:
            return OrderBookDepth(
                symbol=symbol, best_bid=0, best_ask=0, mid_price=0,
                spread_bps=0, bid_depth_usd=0, ask_depth_usd=0,
                imbalance=0, levels_analyzed=0,
            )

        best_bid = book.bids[0].price
        best_ask = book.asks[0].price
        mid_price = (best_bid + best_ask) / 2
        spread_bps = (best_ask - best_bid) / mid_price * 10_000 if mid_price > 0 else 0

        # Compute depth
        bid_depth_usd = sum(l.price * l.quantity for l in book.bids)
        ask_depth_usd = sum(l.price * l.quantity for l in book.asks)
        total_depth = bid_depth_usd + ask_depth_usd

        # Imbalance: +1 = all bids, -1 = all asks
        if total_depth > 0:
            imbalance = (bid_depth_usd - ask_depth_usd) / total_depth
        else:
            imbalance = 0.0

        # Detect walls
        bid_wall_price, bid_wall_size = self._detect_wall(book.bids, wall_threshold_usd)
        ask_wall_price, ask_wall_size = self._detect_wall(book.asks, wall_threshold_usd)

        # Wall imbalance: positive = bid wall dominance (support)
        wall_total = bid_wall_size + ask_wall_size
        wall_imbalance = (
            (bid_wall_size - ask_wall_size) / wall_total
            if wall_total > 0 else 0.0
        )

        # Track spread for historical analysis
        now = time.time()
        if symbol not in self._spread_history:
            self._spread_history[symbol] = []
        self._spread_history[symbol].append((now, spread_bps))
        # Prune to 1 hour
        cutoff = now - 3600
        self._spread_history[symbol] = [
            (ts, s) for ts, s in self._spread_history[symbol] if ts > cutoff
        ]

        return OrderBookDepth(
            symbol=symbol,
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid_price,
            spread_bps=round(spread_bps, 2),
            bid_depth_usd=round(bid_depth_usd, 2),
            ask_depth_usd=round(ask_depth_usd, 2),
            imbalance=round(imbalance, 4),
            bid_wall_price=bid_wall_price,
            bid_wall_size_usd=round(bid_wall_size, 2),
            ask_wall_price=ask_wall_price,
            ask_wall_size_usd=round(ask_wall_size, 2),
            wall_imbalance=round(wall_imbalance, 4),
            levels_analyzed=len(book.bids) + len(book.asks),
            timestamp=datetime.now(UTC),
        )

    @staticmethod
    def _detect_wall(
        levels: tuple,
        threshold_usd: float,
    ) -> tuple[float | None, float]:
        """Detect a large wall order in the book.

        A wall is a level with significantly more depth than its neighbors.
        """
        if not levels:
            return None, 0.0

        best_wall_price = None
        best_wall_size = 0.0

        for level in levels:
            size_usd = level.price * level.quantity
            if size_usd >= threshold_usd and size_usd > best_wall_size:
                best_wall_price = level.price
                best_wall_size = size_usd

        return best_wall_price, best_wall_size

    # ── Tool 4: Funding Rate Monitor ────────────────────────────────

    async def get_funding_rate(self, symbol: str) -> FundingRate:
        """Get current funding rate with arbitrage signal analysis.

        Funding rates indicate market sentiment:
        - Positive rate: Longs pay shorts (crowded longs)
        - Negative rate: Shorts pay longs (crowded shorts)
        - Extreme rates (>0.1% or <-0.1%) signal potential reversals

        Arbitrage signals:
        - High positive funding → earn by going long spot + short perp
        - High negative funding → earn by going short spot + long perp
        - Score > 0.6 indicates actionable opportunity

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").

        Returns:
            FundingRate with current rate, arbitrage signal, and sentiment.
        """
        cached = self._funding_cache.get(symbol)
        if cached and time.time() - cached[0] < self._cache_ttl_s:
            return cached[1]

        import httpx

        try:
            futures_symbol = symbol.replace("/", "")

            async with httpx.AsyncClient(timeout=10) as client:
                # Get funding rate history
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/fundingRate",
                    params={"symbol": futures_symbol, "limit": 1},
                )
                resp.raise_for_status()
                data = resp.json()

                if not data:
                    return self._default_funding_rate(symbol)

                rate = float(data[0]["fundingRate"])
                next_funding_ms = int(data[0].get("fundingTime", 0))

                # Get predicted funding rate from premium index
                try:
                    resp2 = await client.get(
                        "https://fapi.binance.com/fapi/v1/premiumIndex",
                        params={"symbol": futures_symbol},
                    )
                    resp2.raise_for_status()
                    premium_data = resp2.json()
                    predicted = float(premium_data.get("lastFundingRate", rate))
                except Exception:
                    predicted = rate

            # Annualize: funding is every 8h → 3x daily → 1095x yearly
            annualized = rate * 3 * 365

            # Sentiment: extreme positive = bearish (crowded longs)
            sentiment = max(-1.0, min(1.0, -rate * 100))

            # Arbitrage signal analysis
            arb_signal, arb_score = self._compute_funding_arb(rate, annualized)

            next_funding = (
                datetime.fromtimestamp(next_funding_ms / 1000, tz=UTC)
                if next_funding_ms > 0 else None
            )

            result = FundingRate(
                symbol=symbol,
                current_rate=rate,
                predicted_rate=predicted,
                annualized_rate=annualized,
                sentiment=sentiment,
                funding_arb_signal=arb_signal,
                funding_arb_score=arb_score,
                next_funding_time=next_funding,
                timestamp=datetime.now(UTC),
            )

            self._funding_cache[symbol] = (time.time(), result)
            return result

        except Exception as exc:
            logger.warning("Failed to fetch funding rate for %s: %s", symbol, exc)
            return self._default_funding_rate(symbol)

    @staticmethod
    def _compute_funding_arb(rate: float, annualized: float) -> tuple[str, float]:
        """Compute funding rate arbitrage signal and score.

        Strategy: When funding is positive and high, go long spot + short perp
        to earn the funding payment. When negative, reverse.
        """
        abs_rate = abs(rate)
        abs_annual = abs(annualized)

        # Score: 0 at 0.01% funding, 1 at 0.1%+ funding
        score = min(1.0, max(0.0, (abs_rate - 0.0001) / 0.0009))

        if abs_rate < 0.0001:
            return "neutral — funding too low for arb", 0.0
        elif abs_rate < 0.0005:
            if rate > 0:
                return f"mild opportunity — long spot + short perp (earn {abs_annual:.1f}% APY)", score
            else:
                return f"mild opportunity — short spot + long perp (earn {abs_annual:.1f}% APY)", score
        elif abs_rate < 0.001:
            if rate > 0:
                return f"good opportunity — long spot + short perp (earn {abs_annual:.1f}% APY)", score
            else:
                return f"good opportunity — short spot + long perp (earn {abs_annual:.1f}% APY)", score
        else:
            if rate > 0:
                return f"strong opportunity — long spot + short perp (earn {abs_annual:.1f}% APY)", score
            else:
                return f"strong opportunity — short spot + long perp (earn {abs_annual:.1f}% APY)", score

    @staticmethod
    def _default_funding_rate(symbol: str) -> FundingRate:
        """Return a default FundingRate when data is unavailable."""
        return FundingRate(
            symbol=symbol,
            current_rate=0.0,
            predicted_rate=0.0,
            annualized_rate=0.0,
            sentiment=0.0,
            funding_arb_signal="unavailable",
            timestamp=datetime.now(UTC),
        )

    # ── Tool 5: Open Interest Tracker ───────────────────────────────

    async def get_open_interest(self, symbol: str) -> OpenInterest:
        """Get open interest with leverage concentration detection.

        Open interest tracks outstanding derivative contracts:
        - Rising OI + rising price = trend strengthening
        - Rising OI + falling price = new shorts entering
        - Falling OI + rising price = short covering
        - Falling OI + falling price = long liquidation

        Leverage concentration:
        - High OI/volume ratio = heavy leverage (squeeze risk)
        - Rapid OI growth = leverage buildup (cascade risk)

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").

        Returns:
            OpenInterest with OI data, changes, and leverage analysis.
        """
        cached = self._oi_cache.get(symbol)
        if cached and time.time() - cached[0] < self._cache_ttl_s:
            return cached[1]

        import httpx

        try:
            futures_symbol = symbol.replace("/", "")

            async with httpx.AsyncClient(timeout=10) as client:
                # Get current OI
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/openInterest",
                    params={"symbol": futures_symbol},
                )
                resp.raise_for_status()
                data = resp.json()

                oi = float(data.get("openInterest", 0))

                # Get ticker for price and volume
                ticker_resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/ticker/24hr",
                    params={"symbol": futures_symbol},
                )
                ticker_resp.raise_for_status()
                ticker = ticker_resp.json()

                price = float(ticker.get("lastPrice", 0))
                volume_24h = float(ticker.get("quoteVolume", 0))

                # Get OI history for change calculation
                try:
                    oi_hist_resp = await client.get(
                        "https://fapi.binance.com/futures/data/openInterestHist",
                        params={"symbol": futures_symbol, "period": "1h", "limit": 25},
                    )
                    oi_hist_resp.raise_for_status()
                    oi_hist = oi_hist_resp.json()
                except Exception:
                    oi_hist = []

            oi_usd = oi * price
            oi_volume_ratio = oi_usd / volume_24h if volume_24h > 0 else 0

            # Track OI history for leverage concentration
            now = time.time()
            if symbol not in self._oi_history:
                self._oi_history[symbol] = []
            self._oi_history[symbol].append((now, oi_usd))
            # Keep 24 hours
            self._oi_history[symbol] = [
                (ts, v) for ts, v in self._oi_history[symbol]
                if now - ts < 86400
            ]

            # Compute changes from history
            change_1h = 0.0
            change_1h_pct = 0.0
            change_24h = 0.0
            change_24h_pct = 0.0

            if oi_hist and len(oi_hist) >= 2:
                latest_oi = float(oi_hist[-1].get("sumOpenInterestValue", 0))
                hour_ago_oi = float(oi_hist[-2].get("sumOpenInterestValue", 0)) if len(oi_hist) >= 2 else latest_oi
                day_ago_oi = float(oi_hist[0].get("sumOpenInterestValue", 0))

                change_1h = latest_oi - hour_ago_oi
                change_1h_pct = (change_1h / hour_ago_oi * 100) if hour_ago_oi > 0 else 0
                change_24h = latest_oi - day_ago_oi
                change_24h_pct = (change_24h / day_ago_oi * 100) if day_ago_oi > 0 else 0

            # Leverage concentration detection
            lev_concentration, lev_signal = self._compute_leverage_concentration(
                oi_volume_ratio, change_1h_pct, change_24h_pct
            )

            result = OpenInterest(
                symbol=symbol,
                open_interest=oi,
                open_interest_usd=round(oi_usd, 2),
                change_1h=round(change_1h, 2),
                change_1h_pct=round(change_1h_pct, 4),
                change_24h=round(change_24h, 2),
                change_24h_pct=round(change_24h_pct, 4),
                oi_to_volume_ratio=round(oi_volume_ratio, 4),
                leverage_concentration=round(lev_concentration, 4),
                leverage_signal=lev_signal,
                timestamp=datetime.now(UTC),
            )

            self._oi_cache[symbol] = (time.time(), result)
            return result

        except Exception as exc:
            logger.warning("Failed to fetch open interest for %s: %s", symbol, exc)
            return OpenInterest(
                symbol=symbol, open_interest=0, open_interest_usd=0,
                timestamp=datetime.now(UTC),
            )

    @staticmethod
    def _compute_leverage_concentration(
        oi_volume_ratio: float,
        change_1h_pct: float,
        change_24h_pct: float,
    ) -> tuple[float, str]:
        """Compute leverage concentration score and signal.

        High OI/volume ratio + rapid OI growth = high leverage concentration.
        """
        # Base score from OI/volume ratio
        # Ratio > 1.0 means more OI than daily volume = heavy positioning
        ratio_score = min(1.0, oi_volume_ratio / 2.0)

        # Boost for rapid OI growth (>5% in 1h or >20% in 24h)
        growth_score = 0.0
        if abs(change_1h_pct) > 5:
            growth_score += 0.3
        elif abs(change_1h_pct) > 2:
            growth_score += 0.15

        if abs(change_24h_pct) > 20:
            growth_score += 0.3
        elif abs(change_24h_pct) > 10:
            growth_score += 0.15

        concentration = min(1.0, ratio_score * 0.6 + growth_score * 0.4)

        if concentration > 0.7:
            signal = "HIGH — heavy leverage buildup, squeeze/cascade risk"
        elif concentration > 0.4:
            signal = "MODERATE — elevated leverage, monitor for exits"
        else:
            signal = "LOW — normal leverage levels"

        return concentration, signal

    # ── Tool 6: Liquidation Feed ────────────────────────────────────

    async def get_liquidation_summary(
        self,
        symbol: str,
        window_minutes: int = 60,
    ) -> LiquidationSummary:
        """Get aggregated liquidation data with cascade detection.

        Cascade detection identifies mass liquidation events:
        - Monitors clustering of liquidations in time
        - Detects feedback loops (price drop → liquidation → more drop)
        - Classifies cascade direction (long squeeze vs short squeeze)

        Args:
            symbol: Trading pair.
            window_minutes: Aggregation window in minutes.

        Returns:
            LiquidationSummary with cascade risk and direction.
        """
        import httpx

        try:
            futures_symbol = symbol.replace("/", "")
            cutoff = time.time() - (window_minutes * 60)

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/allForceOrders",
                    params={"symbol": futures_symbol, "limit": 100},
                )
                resp.raise_for_status()
                data = resp.json()

            long_liqs = 0.0
            short_liqs = 0.0
            long_count = 0
            short_count = 0
            largest = 0.0
            timestamps: list[float] = []
            long_timestamps: list[float] = []
            short_timestamps: list[float] = []

            for liq in data:
                ts = float(liq.get("time", 0)) / 1000
                if ts < cutoff:
                    continue

                price = float(liq.get("price", 0))
                qty = float(liq.get("origQty", 0))
                usd = price * qty
                side = liq.get("side", "").lower()

                if side == "sell":
                    # Sell = long liquidated
                    long_liqs += usd
                    long_count += 1
                    long_timestamps.append(ts)
                else:
                    # Buy = short liquidated
                    short_liqs += usd
                    short_count += 1
                    short_timestamps.append(ts)

                largest = max(largest, usd)
                timestamps.append(ts)

            # Enhanced cascade detection
            cascade_risk, cascade_dir, avg_interval = self._detect_cascade(
                timestamps, long_timestamps, short_timestamps, window_minutes
            )

            cascade_detected = cascade_risk > 0.6

            return LiquidationSummary(
                symbol=symbol,
                window_minutes=window_minutes,
                total_long_liqs=round(long_liqs, 2),
                total_short_liqs=round(short_liqs, 2),
                net_liq=round(long_liqs - short_liqs, 2),
                long_liq_count=long_count,
                short_liq_count=short_count,
                largest_liq=round(largest, 2),
                cascade_risk=round(cascade_risk, 4),
                cascade_detected=cascade_detected,
                cascade_direction=cascade_dir,
                avg_liq_interval_s=round(avg_interval, 2),
                timestamp=datetime.now(UTC),
            )

        except Exception as exc:
            logger.warning("Failed to fetch liquidations for %s: %s", symbol, exc)
            return LiquidationSummary(
                symbol=symbol, window_minutes=window_minutes,
                total_long_liqs=0, total_short_liqs=0, net_liq=0,
                timestamp=datetime.now(UTC),
            )

    @staticmethod
    def _detect_cascade(
        all_timestamps: list[float],
        long_timestamps: list[float],
        short_timestamps: list[float],
        window_minutes: int,
    ) -> tuple[float, str, float]:
        """Detect liquidation cascades with direction classification.

        Returns:
            (cascade_risk, direction, avg_interval_seconds)
        """
        if len(all_timestamps) < 3:
            return 0.0, "none", 0.0

        sorted_all = sorted(all_timestamps)

        # Find the densest 5-minute window (sliding window)
        window_s = 300  # 5 minutes
        max_count = 0
        densest_start = 0
        densest_end = 0
        j = 0

        for i in range(len(sorted_all)):
            while j < len(sorted_all) and sorted_all[j] - sorted_all[i] <= window_s:
                j += 1
            count = j - i
            if count > max_count:
                max_count = count
                densest_start = i
                densest_end = j

        # Normalize: 5+ liquidations in 5 min = high risk
        cascade_risk = min(1.0, max_count / 5.0)

        # Average interval in densest window
        if max_count >= 2:
            densest_ts = sorted_all[densest_start:densest_end]
            intervals = [densest_ts[i+1] - densest_ts[i] for i in range(len(densest_ts)-1)]
            avg_interval = sum(intervals) / len(intervals)
        else:
            avg_interval = 0.0

        # Direction: which side is getting liquidated more in the densest window?
        densest_window = sorted_all[densest_start:densest_end]
        densest_start_ts = densest_window[0]
        densest_end_ts = densest_window[-1]

        long_in_window = sum(
            1 for t in long_timestamps
            if densest_start_ts <= t <= densest_end_ts
        )
        short_in_window = sum(
            1 for t in short_timestamps
            if densest_start_ts <= t <= densest_end_ts
        )

        if long_in_window > short_in_window * 1.5:
            direction = "long"  # Long liquidation cascade
        elif short_in_window > long_in_window * 1.5:
            direction = "short"  # Short liquidation cascade
        else:
            direction = "mixed"

        return cascade_risk, direction, avg_interval

    # ── Tool 7: Volume Profile ──────────────────────────────────────

    async def get_volume_profile(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        num_bins: int = 50,
        value_area_pct: float = 0.70,
    ) -> VolumeProfile:
        """Compute volume profile with POC and value area detection.

        The volume profile shows how much volume traded at each price
        level. Key concepts:
        - POC (Point of Control): Price with highest volume (fair value)
        - Value Area: Price range containing 70% of volume
        - Price above POC with low volume = potential resistance
        - Price below POC with low volume = potential support

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe.
            limit: Number of candles to use.
            num_bins: Number of price bins for the profile.
            value_area_pct: Percentage of volume for value area (default 70%).

        Returns:
            VolumeProfile with level-by-level breakdown and POC.
        """
        from src.interfaces.types import Timeframe

        ohlcv = await self._gateway.get_ohlcv(symbol, Timeframe(timeframe), limit=limit)

        if not ohlcv:
            return VolumeProfile(
                symbol=symbol, timeframe=timeframe,
                levels=(), poc_price=0, poc_volume=0,
                value_area_high=0, value_area_low=0, total_volume=0,
                timestamp=datetime.now(UTC),
            )

        # Build price-volume distribution
        prices = np.array([c.close for c in ohlcv])
        highs = np.array([c.high for c in ohlcv])
        lows = np.array([c.low for c in ohlcv])
        volumes = np.array([c.volume for c in ohlcv])

        price_min = float(np.min(lows))
        price_max = float(np.max(highs))
        total_volume = float(np.sum(volumes))

        if price_max <= price_min or total_volume <= 0:
            return VolumeProfile(
                symbol=symbol, timeframe=timeframe,
                levels=(), poc_price=0, poc_volume=0,
                value_area_high=0, value_area_low=0, total_volume=0,
                timestamp=datetime.now(UTC),
            )

        # Create bins
        bin_edges = np.linspace(price_min, price_max, num_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        bin_volumes = np.zeros(num_bins)

        # Distribute volume across bins based on price range overlap
        for i in range(len(ohlcv)):
            low = lows[i]
            high = highs[i]
            vol = volumes[i]

            for j in range(num_bins):
                bin_low = bin_edges[j]
                bin_high = bin_edges[j + 1]

                overlap_low = max(low, bin_low)
                overlap_high = min(high, bin_high)

                if overlap_high > overlap_low:
                    candle_range = high - low
                    if candle_range > 0:
                        fraction = (overlap_high - overlap_low) / candle_range
                        bin_volumes[j] += vol * fraction

        # Find POC (Point of Control)
        poc_idx = int(np.argmax(bin_volumes))
        poc_price = float(bin_centers[poc_idx])
        poc_volume = float(bin_volumes[poc_idx])

        # Compute value area (70% of volume, centered on POC)
        sorted_indices = np.argsort(-bin_volumes)
        cumulative = 0.0
        va_indices: list[int] = []
        for idx in sorted_indices:
            cumulative += bin_volumes[idx]
            va_indices.append(idx)
            if cumulative >= total_volume * value_area_pct:
                break

        va_indices_sorted = sorted(va_indices)
        va_low = float(bin_edges[va_indices_sorted[0]])
        va_high = float(bin_edges[va_indices_sorted[-1] + 1])

        # Build levels
        levels: list[VolumeProfileLevel] = []
        for j in range(num_bins):
            vol = float(bin_volumes[j])
            if vol <= 0:
                continue
            levels.append(VolumeProfileLevel(
                price=round(float(bin_centers[j]), 8),
                volume=round(vol, 8),
                volume_pct=round(vol / total_volume * 100, 2) if total_volume > 0 else 0,
                is_poc=(j == poc_idx),
                is_value_area=(j in va_indices),
            ))

        return VolumeProfile(
            symbol=symbol,
            timeframe=timeframe,
            levels=tuple(levels),
            poc_price=round(poc_price, 8),
            poc_volume=round(poc_volume, 8),
            value_area_high=round(va_high, 8),
            value_area_low=round(va_low, 8),
            total_volume=round(total_volume, 8),
            timestamp=datetime.now(UTC),
        )

    # ── Tool 8: Trade Feed (Whale Detection) ────────────────────────

    async def get_trade_flow(
        self,
        symbol: str,
        limit: int = 200,
        whale_threshold_usd: float = 10_000,
    ) -> TradeFlowAnalysis:
        """Analyze recent trade flow with whale detection.

        Examines the trade tape to determine:
        - Net buy/sell volume imbalance
        - Large trade detection (whale activity)
        - VWAP over the window
        - Whale trade details (price, size, direction)

        Args:
            symbol: Trading pair.
            limit: Number of recent trades to analyze.
            whale_threshold_usd: Minimum USD value to flag as whale trade.

        Returns:
            TradeFlowAnalysis with flow metrics and whale alerts.
        """
        trades = await self._gateway.get_recent_trades(symbol, limit=limit)

        if not trades:
            return TradeFlowAnalysis(
                symbol=symbol, window_minutes=0,
                buy_volume=0, sell_volume=0,
                buy_volume_usd=0, sell_volume_usd=0,
                net_flow=0, net_flow_usd=0,
                timestamp=datetime.now(UTC),
            )

        buy_vol = 0.0
        sell_vol = 0.0
        buy_usd = 0.0
        sell_usd = 0.0
        large_trades = 0
        large_buy_usd = 0.0
        large_sell_usd = 0.0
        total_cost = 0.0
        total_qty = 0.0
        whale_details: list[dict[str, Any]] = []

        for trade in trades:
            cost = trade.price * trade.quantity
            if trade.side.value == "buy":
                buy_vol += trade.quantity
                buy_usd += cost
            else:
                sell_vol += trade.quantity
                sell_usd += cost

            if cost >= whale_threshold_usd:
                large_trades += 1
                if trade.side.value == "buy":
                    large_buy_usd += cost
                else:
                    large_sell_usd += cost

                whale_details.append({
                    "side": trade.side.value,
                    "price": trade.price,
                    "quantity": trade.quantity,
                    "cost_usd": round(cost, 2),
                    "timestamp": trade.timestamp.isoformat() if trade.timestamp else None,
                })

            total_cost += cost
            total_qty += trade.quantity

        # VWAP
        vwap = total_cost / total_qty if total_qty > 0 else 0

        # Time window
        if len(trades) >= 2:
            time_span = (trades[0].timestamp - trades[-1].timestamp).total_seconds() / 60
        else:
            time_span = 0

        # Large trade bias
        large_total = large_buy_usd + large_sell_usd
        if large_total > 0:
            large_bias = (large_buy_usd - large_sell_usd) / large_total
        else:
            large_bias = 0.0

        return TradeFlowAnalysis(
            symbol=symbol,
            window_minutes=max(1, int(abs(time_span))),
            buy_volume=round(buy_vol, 8),
            sell_volume=round(sell_vol, 8),
            buy_volume_usd=round(buy_usd, 2),
            sell_volume_usd=round(sell_usd, 2),
            net_flow=round(buy_vol - sell_vol, 8),
            net_flow_usd=round(buy_usd - sell_usd, 2),
            large_trade_count=large_trades,
            large_trade_bias=round(large_bias, 4),
            whale_detected=len(whale_details) > 0,
            whale_trades=tuple(whale_details),
            vwap=round(vwap, 2),
            timestamp=datetime.now(UTC),
        )

    # ── Tool 9: Spread Analysis ─────────────────────────────────────

    async def analyze_spread(
        self,
        symbol: str,
    ) -> SpreadAnalysis:
        """Analyze bid-ask spread and liquidity conditions.

        Tracks spread over time to detect widening (liquidity withdrawal)
        and compute a liquidity score based on spread tightness and depth.

        Args:
            symbol: Trading pair.

        Returns:
            SpreadAnalysis with current and historical spread metrics.
        """
        depth = await self.get_orderbook_depth(symbol, levels=20)

        current_spread = depth.spread_bps
        now = time.time()

        # Ensure spread history exists (get_orderbook_depth adds to it)
        if symbol not in self._spread_history:
            self._spread_history[symbol] = []

        history = self._spread_history[symbol]

        if len(history) > 1:
            spreads = [s for _, s in history]
            avg_spread = float(np.mean(spreads))
            min_spread = float(np.min(spreads))
            max_spread = float(np.max(spreads))
            std_spread = float(np.std(spreads))

            # Widening: current > avg + 1 std
            is_widening = current_spread > avg_spread + std_spread
        else:
            avg_spread = current_spread
            min_spread = current_spread
            max_spread = current_spread
            std_spread = 0.0
            is_widening = False

        # Liquidity score: tight spread + high depth = high score
        spread_score = max(0, 1.0 - current_spread / 50.0)
        depth_score = min(1.0, (depth.bid_depth_usd + depth.ask_depth_usd) / 1_000_000)
        liquidity_score = spread_score * 0.4 + depth_score * 0.6

        return SpreadAnalysis(
            symbol=symbol,
            window_minutes=60,
            current_spread_bps=round(current_spread, 2),
            avg_spread_bps=round(avg_spread, 2),
            min_spread_bps=round(min_spread, 2),
            max_spread_bps=round(max_spread, 2),
            spread_volatility=round(std_spread, 2),
            liquidity_score=round(liquidity_score, 4),
            is_widening=is_widening,
            timestamp=datetime.now(UTC),
        )

    # ── Convenience: Multi-symbol snapshot ──────────────────────────

    async def get_market_snapshot(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Get a comprehensive market snapshot for multiple symbols.

        Returns order book depth, funding rate, OI, and latest price
        for each symbol in a single call.

        Args:
            symbols: Symbols to snapshot (defaults to tracked symbols).

        Returns:
            Dict mapping symbol to snapshot data.
        """
        syms = symbols or self._price_feed.tracked_symbols
        results: dict[str, dict[str, Any]] = {}

        for sym in syms:
            try:
                depth, funding, oi = await asyncio.gather(
                    self.get_orderbook_depth(sym),
                    self.get_funding_rate(sym),
                    self.get_open_interest(sym),
                    return_exceptions=True,
                )

                snapshot: dict[str, Any] = {
                    "price": self.get_realtime_price(sym),
                }

                if not isinstance(depth, Exception):
                    snapshot["orderbook"] = depth
                if not isinstance(funding, Exception):
                    snapshot["funding"] = funding
                if not isinstance(oi, Exception):
                    snapshot["open_interest"] = oi

                results[sym] = snapshot

            except Exception as exc:
                logger.warning("Snapshot failed for %s: %s", sym, exc)
                results[sym] = {"error": str(exc)}

        return results
