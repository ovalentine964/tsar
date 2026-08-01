"""
TSAR Domain Tools — Market Microstructure Analysis.

Sees what retail traders can't: the invisible hand of the market.
Order book imbalances, bid-ask spreads, volume profiles, liquidity
heatmaps, and tick-level analysis reveal where smart money is positioned.

This is the information edge that separates professional traders
from the 78% who lose.

Data Sources:
  - Exchange order books (Binance, Bybit, OKX — free WebSocket APIs)
  - Tick-level trade data from exchanges
  - Volume profile calculation from trade history
  - Liquidity cluster detection from order book snapshots

All tools are async with caching and graceful degradation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


class PressureType(str, Enum):
    """Order book pressure classification."""
    BUY_PRESSURE = "buy_pressure"
    SELL_PRESSURE = "sell_pressure"
    BALANCED = "balanced"


@dataclass(frozen=True)
class SpreadAnalysis:
    """Bid-ask spread analysis.

    Attributes:
        symbol: Asset symbol.
        bid: Best bid price.
        ask: Best ask price.
        spread: Absolute spread (ask - bid).
        spread_bps: Spread in basis points.
        spread_pct: Spread as percentage.
        mid_price: Midpoint of bid/ask.
        liquidity_score: How liquid the market is (0-1, higher = more liquid).
        is_widening: Whether the spread is widening (uncertainty signal).
        timestamp: When the data was captured.
    """

    symbol: str
    bid: float
    ask: float
    spread: float
    spread_bps: float
    spread_pct: float
    mid_price: float
    liquidity_score: float
    is_widening: bool = False
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OrderBookImbalance:
    """Order book imbalance — buying vs selling pressure.

    Attributes:
        symbol: Asset symbol.
        bid_volume: Total volume on bid side (top N levels).
        ask_volume: Total volume on ask side (top N levels).
        imbalance_ratio: bid_volume / ask_volume (>1 = more buying).
        pressure: What the order book suggests.
        pressure_strength: How strong the pressure is (0-1).
        bid_wall: Largest single bid order (potential support).
        ask_wall: Largest single ask order (potential resistance).
        levels_analyzed: How many order book levels were analyzed.
        timestamp: When the snapshot was taken.
    """

    symbol: str
    bid_volume: float
    ask_volume: float
    imbalance_ratio: float
    pressure: str  # PressureType value
    pressure_strength: float
    bid_wall: float = 0.0
    ask_wall: float = 0.0
    levels_analyzed: int = 10
    timestamp: datetime | None = None


@dataclass(frozen=True)
class VolumeLevel:
    """A single price level in the volume profile.

    Attributes:
        price: Price level.
        volume: Total volume at this level.
        buy_volume: Buy volume at this level.
        sell_volume: Sell volume at this level.
        num_trades: Number of trades at this level.
        is_support: Whether this level acts as support.
        is_resistance: Whether this level acts as resistance.
    """

    price: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    num_trades: int = 0
    is_support: bool = False
    is_resistance: bool = False


@dataclass(frozen=True)
class VolumeProfile:
    """Volume profile — identifies support/resistance from traded volume.

    Attributes:
        symbol: Asset symbol.
        poc_price: Point of Control — price with highest volume.
        poc_volume: Volume at the POC.
        vah: Value Area High — top of the value area (70% of volume).
        val: Value Area Low — bottom of the value area.
        levels: Individual price levels with volume.
        profile_shape: "normal", "bimodal", "skewed_high", "skewed_low".
        timeframe: Timeframe of the profile.
        timestamp: When the profile was calculated.
    """

    symbol: str
    poc_price: float
    poc_volume: float
    vah: float
    val: float
    levels: list[VolumeLevel] = field(default_factory=list)
    profile_shape: str = "normal"
    timeframe: str = "24h"
    timestamp: datetime | None = None


@dataclass(frozen=True)
class LiquidityCluster:
    """A cluster of liquidity (potential stop-loss or take-profit zones).

    Attributes:
        price: Center price of the cluster.
        volume: Total volume in the cluster.
        cluster_type: "stop_buy", "stop_sell", "take_profit", "limit_order".
        distance_pct: Distance from current price (%).
        significance: How significant this cluster is (0-1).
    """

    price: float
    volume: float
    cluster_type: str
    distance_pct: float
    significance: float = 0.0


@dataclass(frozen=True)
class LiquidityHeatmap:
    """Liquidity heatmap — where are the stops and clusters?

    Attributes:
        symbol: Asset symbol.
        current_price: Current market price.
        clusters: Detected liquidity clusters.
        buy_liquidity_depth: Total buy-side liquidity within 5%.
        sell_liquidity_depth: Total sell-side liquidity within 5%.
        imbalance: Whether there's more liquidity on one side.
        timestamp: When the heatmap was generated.
    """

    symbol: str
    current_price: float
    clusters: list[LiquidityCluster] = field(default_factory=list)
    buy_liquidity_depth: float = 0.0
    sell_liquidity_depth: float = 0.0
    imbalance: str = "balanced"
    timestamp: datetime | None = None


@dataclass(frozen=True)
class TickAnalysis:
    """Tick-level price action analysis.

    Attributes:
        symbol: Asset symbol.
        trades_per_second: Average trades per second.
        avg_trade_size: Average trade size in USD.
        buy_sell_ratio: Ratio of buy volume to sell volume.
        large_trade_pct: Percentage of volume from large trades.
        aggressive_buys: Market buy orders (takers).
        aggressive_sells: Market sell orders (takers).
        passive_buys: Limit buy orders (makers).
        passive_sells: Limit sell orders (makers).
        taker_buy_ratio: Ratio of taker buy volume to total.
        vwap: Volume-weighted average price.
        price_impact: Average price impact per $100k (slippage estimate).
        micro_trend: Short-term direction from tick data.
        timestamp: When the analysis was performed.
    """

    symbol: str
    trades_per_second: float = 0.0
    avg_trade_size: float = 0.0
    buy_sell_ratio: float = 1.0
    large_trade_pct: float = 0.0
    aggressive_buys: float = 0.0
    aggressive_sells: float = 0.0
    passive_buys: float = 0.0
    passive_sells: float = 0.0
    taker_buy_ratio: float = 0.5
    vwap: float = 0.0
    price_impact: float = 0.0
    micro_trend: str = "neutral"
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# MARKET MICROSTRUCTURE TOOLS
# ═══════════════════════════════════════════════════════════════════════


class MarketMicrostructureTools:
    """Market microstructure analysis tools.

    Reveals the invisible structure of the market that institutional
    traders exploit: order book dynamics, volume profiles, liquidity
    zones, and tick-level flow.

    Usage:
        tools = MarketMicrostructureTools()
        spread = await tools.analyze_spread("BTC/USDT")
        imbalance = await tools.detect_orderbook_imbalance("BTC/USDT")
        profile = await tools.compute_volume_profile("BTC/USDT")
    """

    def __init__(self, cache_ttl: int = 60) -> None:
        """Initialize microstructure tools.

        Args:
            cache_ttl: Cache time-to-live in seconds (short for real-time data).
        """
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = cache_ttl
        self._http: httpx.AsyncClient | None = None
        # Historical spread tracking for widening detection
        self._spread_history: dict[str, list[tuple[float, float]]] = defaultdict(list)

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        return self._http

    def _cache_get(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
        return None

    def _cache_set(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)

    # ─────────────────────────────────────────────────────────────────
    # Bid-Ask Spread Analysis
    # ─────────────────────────────────────────────────────────────────

    async def analyze_spread(self, symbol: str) -> SpreadAnalysis:
        """Analyze real-time bid-ask spread.

        Tight spreads = liquid, efficient market.
        Wide spreads = illiquid, uncertain, or volatile.
        Widening spreads often precede large moves.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT").

        Returns:
            SpreadAnalysis with liquidity score.
        """
        cache_key = f"spread:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        http = await self._get_http()
        pair = symbol.replace("/", "").upper()

        try:
            # Binance ticker for bid/ask
            url = "https://api.binance.com/api/v3/ticker/bookTicker"
            params = {"symbol": pair}
            resp = await http.get(url, params=params, timeout=5.0)

            if resp.status_code == 200:
                data = resp.json()
                bid = float(data["bidPrice"])
                ask = float(data["askPrice"])
                result = self._compute_spread(symbol, bid, ask)
                self._cache_set(cache_key, result)
                return result
        except Exception as e:
            logger.debug("Spread fetch failed for %s: %s", symbol, e)

        # Fallback: try Bybit
        try:
            url = "https://api.bybit.com/v5/market/tickers"
            params = {"category": "spot", "symbol": pair}
            resp = await http.get(url, params=params, timeout=5.0)
            if resp.status_code == 200:
                tickers = resp.json().get("result", {}).get("list", [])
                if tickers:
                    t = tickers[0]
                    bid = float(t["bid1Price"])
                    ask = float(t["ask1Price"])
                    result = self._compute_spread(symbol, bid, ask)
                    self._cache_set(cache_key, result)
                    return result
        except Exception as e:
            logger.debug("Bybit spread fallback failed: %s", e)

        # Return a placeholder if all sources fail
        return SpreadAnalysis(
            symbol=symbol, bid=0.0, ask=0.0, spread=0.0,
            spread_bps=0.0, spread_pct=0.0, mid_price=0.0,
            liquidity_score=0.0, timestamp=datetime.now(UTC),
        )

    def _compute_spread(self, symbol: str, bid: float, ask: float) -> SpreadAnalysis:
        """Compute spread metrics from bid/ask."""
        spread = ask - bid
        mid = (bid + ask) / 2
        spread_pct = (spread / mid * 100) if mid > 0 else 0
        spread_bps = spread_pct * 100

        # Liquidity score: tighter spread = more liquid
        # BTC typically has 0.01-0.05% spread
        # Score: 1.0 for < 0.01%, 0.5 for 0.1%, 0.0 for > 1%
        if spread_pct < 0.01:
            liquidity_score = 1.0
        elif spread_pct < 0.1:
            liquidity_score = 1.0 - (spread_pct - 0.01) / 0.09 * 0.5
        elif spread_pct < 1.0:
            liquidity_score = 0.5 - (spread_pct - 0.1) / 0.9 * 0.5
        else:
            liquidity_score = max(0.0, 0.1 - spread_pct / 100)

        # Track spread history for widening detection
        now = time.time()
        hist = self._spread_history[symbol]
        hist.append((now, spread_pct))
        # Keep last 60 data points
        if len(hist) > 60:
            self._spread_history[symbol] = hist[-60:]
            hist = self._spread_history[symbol]

        is_widening = False
        if len(hist) >= 5:
            recent_avg = sum(s for _, s in hist[-5:]) / 5
            older_avg = sum(s for _, s in hist[-10:-5]) / 5 if len(hist) >= 10 else recent_avg
            is_widening = recent_avg > older_avg * 1.3

        return SpreadAnalysis(
            symbol=symbol,
            bid=bid,
            ask=ask,
            spread=spread,
            spread_bps=spread_bps,
            spread_pct=spread_pct,
            mid_price=mid,
            liquidity_score=max(0.0, min(1.0, liquidity_score)),
            is_widening=is_widening,
            timestamp=datetime.now(UTC),
        )

    # ─────────────────────────────────────────────────────────────────
    # Order Book Imbalance
    # ─────────────────────────────────────────────────────────────────

    async def detect_orderbook_imbalance(
        self,
        symbol: str,
        levels: int = 20,
    ) -> OrderBookImbalance:
        """Detect buying vs selling pressure from order book.

        When there's more volume on the bid side, buyers are in control.
        When there's more on the ask side, sellers dominate.
        Large walls (single huge orders) indicate institutional interest.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT").
            levels: Number of order book levels to analyze.

        Returns:
            OrderBookImbalance with pressure classification.
        """
        cache_key = f"ob_imbalance:{symbol}:{levels}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        http = await self._get_http()
        pair = symbol.replace("/", "").upper()

        try:
            url = "https://api.binance.com/api/v3/depth"
            params = {"symbol": pair, "limit": levels}
            resp = await http.get(url, params=params, timeout=5.0)

            if resp.status_code == 200:
                data = resp.json()
                result = self._analyze_order_book(symbol, data, levels)
                self._cache_set(cache_key, result)
                return result
        except Exception as e:
            logger.debug("Order book fetch failed for %s: %s", symbol, e)

        # Fallback
        return OrderBookImbalance(
            symbol=symbol, bid_volume=0.0, ask_volume=0.0,
            imbalance_ratio=1.0, pressure="balanced",
            pressure_strength=0.0, timestamp=datetime.now(UTC),
        )

    def _analyze_order_book(
        self, symbol: str, data: dict, levels: int
    ) -> OrderBookImbalance:
        """Analyze raw order book data."""
        bids = [(float(p), float(q)) for p, q in data.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in data.get("asks", [])]

        bid_vol = sum(q for _, q in bids)
        ask_vol = sum(q for _, q in asks)

        # Imbalance ratio
        ratio = bid_vol / ask_vol if ask_vol > 0 else float("inf") if bid_vol > 0 else 1.0

        # Pressure classification
        if ratio > 1.5:
            pressure = "buy_pressure"
            strength = min((ratio - 1.0) / 2.0, 1.0)
        elif ratio < 0.67:
            pressure = "sell_pressure"
            strength = min((1.0 - ratio) / 0.5, 1.0)
        else:
            pressure = "balanced"
            strength = 0.0

        # Find walls (largest single orders)
        bid_wall = max(q for _, q in bids) if bids else 0.0
        ask_wall = max(q for _, q in asks) if asks else 0.0

        return OrderBookImbalance(
            symbol=symbol,
            bid_volume=bid_vol,
            ask_volume=ask_vol,
            imbalance_ratio=ratio,
            pressure=pressure,
            pressure_strength=strength,
            bid_wall=bid_wall,
            ask_wall=ask_wall,
            levels_analyzed=levels,
            timestamp=datetime.now(UTC),
        )

    # ─────────────────────────────────────────────────────────────────
    # Volume Profile
    # ─────────────────────────────────────────────────────────────────

    async def compute_volume_profile(
        self,
        symbol: str,
        interval: str = "1h",
        lookback_periods: int = 48,
    ) -> VolumeProfile:
        """Compute volume profile from historical trades.

        The volume profile shows where most trading occurred.
        The Point of Control (POC) is the price with the highest
        traded volume — a natural magnet for price.
        The Value Area (70% of volume) defines the "fair" range.

        Args:
            symbol: Trading pair.
            interval: Candle interval ("1m", "5m", "15m", "1h", "4h").
            lookback_periods: Number of periods to analyze.

        Returns:
            VolumeProfile with POC, value area, and level details.
        """
        cache_key = f"vol_profile:{symbol}:{interval}:{lookback_periods}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        http = await self._get_http()
        pair = symbol.replace("/", "").upper()

        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                "symbol": pair,
                "interval": interval,
                "limit": lookback_periods,
            }
            resp = await http.get(url, params=params, timeout=10.0)

            if resp.status_code == 200:
                klines = resp.json()
                result = self._build_volume_profile(symbol, klines, interval)
                self._cache_set(cache_key, result)
                return result
        except Exception as e:
            logger.debug("Volume profile fetch failed for %s: %s", symbol, e)

        return VolumeProfile(
            symbol=symbol, poc_price=0.0, poc_volume=0.0,
            vah=0.0, val=0.0, timeframe=interval,
            timestamp=datetime.now(UTC),
        )

    def _build_volume_profile(
        self, symbol: str, klines: list, interval: str
    ) -> VolumeProfile:
        """Build volume profile from kline data."""
        if not klines:
            return VolumeProfile(
                symbol=symbol, poc_price=0.0, poc_volume=0.0,
                vah=0.0, val=0.0, timeframe=interval,
                timestamp=datetime.now(UTC),
            )

        # Aggregate volume into price levels
        price_volumes: dict[float, dict[str, float]] = defaultdict(
            lambda: {"volume": 0.0, "buy": 0.0, "sell": 0.0, "trades": 0}
        )

        for k in klines:
            # kline: [open_time, open, high, low, close, volume, ...]
            high = float(k[2])
            low = float(k[3])
            close = float(k[4])
            volume = float(k[5])
            open_price = float(k[1])

            # Determine if candle was bullish or bearish
            if close >= open_price:
                buy_vol = volume * 0.6
                sell_vol = volume * 0.4
            else:
                buy_vol = volume * 0.4
                sell_vol = volume * 0.6

            # Bucket into price levels (round to 0.1% of price range)
            mid_price = (high + low) / 2
            tick = mid_price * 0.001  # 0.1% buckets
            if tick <= 0:
                tick = 1.0

            level = round(mid_price / tick) * tick
            price_volumes[level]["volume"] += volume
            price_volumes[level]["buy"] += buy_vol
            price_volumes[level]["sell"] += sell_vol
            price_volumes[level]["trades"] += 1

        # Build levels
        levels = []
        for price, data in sorted(price_volumes.items()):
            levels.append(VolumeLevel(
                price=price,
                volume=data["volume"],
                buy_volume=data["buy"],
                sell_volume=data["sell"],
                num_trades=int(data["trades"]),
            ))

        # Find POC (Point of Control)
        poc_level = max(levels, key=lambda l: l.volume)

        # Calculate Value Area (70% of total volume)
        total_volume = sum(l.volume for l in levels)
        target_volume = total_volume * 0.7

        # Start from POC and expand outward
        poc_idx = levels.index(poc_level)
        va_volume = poc_level.volume
        low_idx = poc_idx
        high_idx = poc_idx

        while va_volume < target_volume and (low_idx > 0 or high_idx < len(levels) - 1):
            # Expand to the side with more volume
            below_vol = levels[low_idx - 1].volume if low_idx > 0 else 0
            above_vol = levels[high_idx + 1].volume if high_idx < len(levels) - 1 else 0

            if below_vol >= above_vol and low_idx > 0:
                low_idx -= 1
                va_volume += levels[low_idx].volume
            elif high_idx < len(levels) - 1:
                high_idx += 1
                va_volume += levels[high_idx].volume
            else:
                break

        val = levels[low_idx].price
        vah = levels[high_idx].price

        # Determine profile shape
        if len(levels) >= 3:
            upper_vol = sum(l.volume for l in levels[len(levels)//2:])
            lower_vol = sum(l.volume for l in levels[:len(levels)//2])
            ratio = upper_vol / lower_vol if lower_vol > 0 else 2.0

            if 0.8 <= ratio <= 1.2:
                shape = "normal"
            elif ratio > 1.5:
                shape = "skewed_high"
            elif ratio < 0.67:
                shape = "skewed_low"
            else:
                shape = "normal"

            # Check for bimodal (two peaks)
            peaks = 0
            for i in range(1, len(levels) - 1):
                if (levels[i].volume > levels[i-1].volume and
                        levels[i].volume > levels[i+1].volume):
                    peaks += 1
            if peaks >= 2:
                shape = "bimodal"
        else:
            shape = "normal"

        # Mark support/resistance levels
        avg_vol = total_volume / len(levels) if levels else 0
        for level in levels:
            if level.volume > avg_vol * 2:
                if level.price < poc_level.price:
                    level = VolumeLevel(
                        price=level.price, volume=level.volume,
                        buy_volume=level.buy_volume, sell_volume=level.sell_volume,
                        num_trades=level.num_trades,
                        is_support=True, is_resistance=False,
                    )
                elif level.price > poc_level.price:
                    level = VolumeLevel(
                        price=level.price, volume=level.volume,
                        buy_volume=level.buy_volume, sell_volume=level.sell_volume,
                        num_trades=level.num_trades,
                        is_support=False, is_resistance=True,
                    )

        return VolumeProfile(
            symbol=symbol,
            poc_price=poc_level.price,
            poc_volume=poc_level.volume,
            vah=vah,
            val=val,
            levels=levels,
            profile_shape=shape,
            timeframe=interval,
            timestamp=datetime.now(UTC),
        )

    # ─────────────────────────────────────────────────────────────────
    # Liquidity Heatmap
    # ─────────────────────────────────────────────────────────────────

    async def generate_liquidity_heatmap(
        self,
        symbol: str,
        range_pct: float = 5.0,
    ) -> LiquidityHeatmap:
        """Generate a liquidity heatmap showing where stops and orders cluster.

        Liquidity clusters indicate:
        - Stop-loss clusters: Where stops are likely piled up (price magnets)
        - Take-profit zones: Where traders plan to exit
        - Limit order walls: Large standing orders

        Args:
            symbol: Trading pair.
            range_pct: Price range to analyze (±%).

        Returns:
            LiquidityHeatmap with detected clusters.
        """
        cache_key = f"liquidity:{symbol}:{range_pct}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        http = await self._get_http()
        pair = symbol.replace("/", "").upper()

        # Get order book for liquidity depth
        clusters: list[LiquidityCluster] = []
        current_price = 0.0
        bid_depth = 0.0
        ask_depth = 0.0

        try:
            url = "https://api.binance.com/api/v3/depth"
            params = {"symbol": pair, "limit": 100}
            resp = await http.get(url, params=params, timeout=5.0)

            if resp.status_code == 200:
                data = resp.json()
                bids = [(float(p), float(q)) for p, q in data.get("bids", [])]
                asks = [(float(p), float(q)) for p, q in data.get("asks", [])]

                if bids and asks:
                    current_price = (bids[0][0] + asks[0][0]) / 2
                    range_abs = current_price * range_pct / 100

                    # Calculate depth within range
                    bid_depth = sum(q for p, q in bids if p >= current_price - range_abs)
                    ask_depth = sum(q for p, q in asks if p <= current_price + range_abs)

                    # Find clusters (levels with unusually high volume)
                    all_levels = [(p, q, "bid") for p, q in bids] + \
                                 [(p, q, "ask") for p, q in asks]
                    avg_qty = sum(q for _, q, _ in all_levels) / len(all_levels) if all_levels else 0

                    for price, qty, side in all_levels:
                        if qty > avg_qty * 3:  # Cluster threshold
                            distance_pct = abs(price - current_price) / current_price * 100
                            if side == "bid":
                                cluster_type = "stop_sell"  # Stops below = sell stops
                            else:
                                cluster_type = "stop_buy"   # Stops above = buy stops

                            clusters.append(LiquidityCluster(
                                price=price,
                                volume=qty,
                                cluster_type=cluster_type,
                                distance_pct=distance_pct,
                                significance=min(qty / (avg_qty * 5), 1.0),
                            ))

                    # Sort by significance
                    clusters.sort(key=lambda c: c.significance, reverse=True)
                    clusters = clusters[:20]  # Top 20 clusters

        except Exception as e:
            logger.debug("Liquidity heatmap fetch failed for %s: %s", symbol, e)

        # Determine imbalance
        if bid_depth > ask_depth * 1.5:
            imbalance = "buy_heavy"
        elif ask_depth > bid_depth * 1.5:
            imbalance = "sell_heavy"
        else:
            imbalance = "balanced"

        result = LiquidityHeatmap(
            symbol=symbol,
            current_price=current_price,
            clusters=clusters,
            buy_liquidity_depth=bid_depth,
            sell_liquidity_depth=ask_depth,
            imbalance=imbalance,
            timestamp=datetime.now(UTC),
        )

        self._cache_set(cache_key, result)
        return result

    # ─────────────────────────────────────────────────────────────────
    # Tick-Level Analysis
    # ─────────────────────────────────────────────────────────────────

    async def analyze_ticks(
        self,
        symbol: str,
        limit: int = 1000,
    ) -> TickAnalysis:
        """Analyze tick-level (trade-by-trade) data.

        Reveals:
        - Whether buyers or sellers are more aggressive
        - Average trade size (institutional vs retail)
        - VWAP for fair value estimation
        - Price impact (slippage estimation)
        - Micro-trend direction

        Args:
            symbol: Trading pair.
            limit: Number of recent trades to analyze.

        Returns:
            TickAnalysis with microstructure insights.
        """
        cache_key = f"ticks:{symbol}:{limit}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        http = await self._get_http()
        pair = symbol.replace("/", "").upper()

        try:
            url = "https://api.binance.com/api/v3/trades"
            params = {"symbol": pair, "limit": min(limit, 1000)}
            resp = await http.get(url, params=params, timeout=10.0)

            if resp.status_code == 200:
                trades = resp.json()
                result = self._analyze_trades(symbol, trades)
                self._cache_set(cache_key, result)
                return result
        except Exception as e:
            logger.debug("Tick analysis fetch failed for %s: %s", symbol, e)

        return TickAnalysis(symbol=symbol, timestamp=datetime.now(UTC))

    def _analyze_trades(self, symbol: str, trades: list[dict]) -> TickAnalysis:
        """Analyze raw trade data."""
        if not trades:
            return TickAnalysis(symbol=symbol, timestamp=datetime.now(UTC))

        buy_volume = 0.0
        sell_volume = 0.0
        total_value = 0.0
        total_volume = 0.0
        trade_sizes: list[float] = []
        prices: list[float] = []

        for t in trades:
            price = float(t.get("price", 0))
            qty = float(t.get("qty", 0))
            is_buyer_maker = t.get("isBuyerMaker", False)

            value = price * qty
            total_value += value
            total_volume += qty
            trade_sizes.append(value)
            prices.append(price)

            if is_buyer_maker:
                # Seller is taker (market sell)
                sell_volume += value
            else:
                # Buyer is taker (market buy)
                buy_volume += value

        # VWAP
        vwap = total_value / total_volume if total_volume > 0 else 0

        # Trade size analysis
        avg_size = total_value / len(trades) if trades else 0
        large_threshold = avg_size * 5
        large_trade_value = sum(s for s in trade_sizes if s > large_threshold)
        large_pct = large_trade_value / total_value * 100 if total_value > 0 else 0

        # Taker buy ratio
        taker_buy_ratio = buy_volume / total_value if total_value > 0 else 0.5

        # Buy/sell ratio
        bs_ratio = buy_volume / sell_volume if sell_volume > 0 else float("inf")

        # Time span for trades per second
        if len(trades) >= 2:
            first_time = trades[0].get("time", 0)
            last_time = trades[-1].get("time", 0)
            time_span = (last_time - first_time) / 1000  # ms to seconds
            tps = len(trades) / time_span if time_span > 0 else 0
        else:
            tps = 0

        # Price impact estimate (slippage per $100k)
        if len(prices) >= 10:
            price_range = max(prices) - min(prices)
            mid = (max(prices) + min(prices)) / 2
            price_impact_pct = (price_range / mid * 100) if mid > 0 else 0
            # Normalize to per $100k
            price_impact = price_impact_pct * (100_000 / total_value) if total_value > 0 else 0
        else:
            price_impact = 0

        # Micro-trend
        if len(prices) >= 10:
            first_half_avg = sum(prices[:len(prices)//2]) / (len(prices)//2)
            second_half_avg = sum(prices[len(prices)//2:]) / (len(prices) - len(prices)//2)
            change_pct = (second_half_avg - first_half_avg) / first_half_avg * 100
            if change_pct > 0.05:
                micro_trend = "bullish"
            elif change_pct < -0.05:
                micro_trend = "bearish"
            else:
                micro_trend = "neutral"
        else:
            micro_trend = "neutral"

        return TickAnalysis(
            symbol=symbol,
            trades_per_second=tps,
            avg_trade_size=avg_size,
            buy_sell_ratio=bs_ratio if bs_ratio != float("inf") else 100.0,
            large_trade_pct=large_pct,
            aggressive_buys=buy_volume,
            aggressive_sells=sell_volume,
            passive_buys=sell_volume,  # Approximation
            passive_sells=buy_volume,  # Approximation
            taker_buy_ratio=taker_buy_ratio,
            vwap=vwap,
            price_impact=price_impact,
            micro_trend=micro_trend,
            timestamp=datetime.now(UTC),
        )

    # ─────────────────────────────────────────────────────────────────
    # Comprehensive Microstructure Summary
    # ─────────────────────────────────────────────────────────────────

    async def get_full_microstructure(self, symbol: str) -> dict[str, Any]:
        """Get comprehensive microstructure analysis for a symbol.

        Combines all microstructure tools into a single report.

        Args:
            symbol: Trading pair.

        Returns:
            Dict with spread, imbalance, profile, liquidity, and tick data.
        """
        spread, imbalance, profile, liquidity, ticks = await asyncio.gather(
            self.analyze_spread(symbol),
            self.detect_orderbook_imbalance(symbol),
            self.compute_volume_profile(symbol),
            self.generate_liquidity_heatmap(symbol),
            self.analyze_ticks(symbol),
            return_exceptions=True,
        )

        def safe(obj: Any) -> dict | None:
            if isinstance(obj, Exception):
                logger.warning("Microstructure component failed: %s", obj)
                return None
            if hasattr(obj, "__dict__"):
                return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
            return None

        return {
            "symbol": symbol,
            "spread": safe(spread),
            "order_book_imbalance": safe(imbalance),
            "volume_profile": safe(profile),
            "liquidity_heatmap": safe(liquidity),
            "tick_analysis": safe(ticks),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def close(self) -> None:
        """Clean up HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
