"""
TSAR Domain Tools — On-Chain Analytics.

Whale wallet tracking, exchange inflow/outflow, active addresses,
transaction counts, and network health metrics.

Data Sources:
  - Blockchain.com public API (BTC metrics)
  - Etherscan public API (ETH metrics)
  - CoinGecko (cross-chain market data, volume-based flow estimation)
  - Whale Alert-style heuristics (large transfer detection)

All tools are async with caching and graceful degradation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from ..backends.defi.analytics_providers import FallbackChain

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class WhaleMovement:
    """A detected whale transaction.

    Attributes:
        symbol: Asset symbol.
        amount: Transaction amount in native token.
        amount_usd: Estimated USD value.
        direction: "exchange_inflow", "exchange_outflow", "transfer", "unknown".
        from_address: Sender address (truncated).
        to_address: Receiver address (truncated).
        timestamp: When the transaction occurred.
        significance: How significant this movement is (0-1).
            Based on amount relative to typical daily volume.
    """

    symbol: str
    amount: float
    amount_usd: float
    direction: str
    from_address: str = ""
    to_address: str = ""
    timestamp: datetime | None = None
    significance: float = 0.0


@dataclass(frozen=True)
class ExchangeFlow:
    """Exchange inflow/outflow data.

    Attributes:
        symbol: Asset symbol.
        inflow_24h: 24-hour exchange inflow in USD.
        outflow_24h: 24-hour exchange outflow in USD.
        net_flow_24h: Net flow (positive = net inflow, negative = net outflow).
        flow_signal: Derived trading signal.
            Large inflow → potential selling pressure (bearish).
            Large outflow → accumulation / cold storage (bullish).
        reserve_change_pct: Change in exchange reserves (%).
        whale_inflow_count: Number of whale-sized inflows detected.
        whale_outflow_count: Number of whale-sized outflows detected.
        timestamp: When the data was fetched.
    """

    symbol: str
    inflow_24h: float
    outflow_24h: float
    net_flow_24h: float
    flow_signal: str  # "bullish", "bearish", "neutral"
    reserve_change_pct: float = 0.0
    whale_inflow_count: int = 0
    whale_outflow_count: int = 0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class ActiveAddresses:
    """Active address metrics.

    Attributes:
        symbol: Asset symbol.
        active_addresses_24h: Unique active addresses in last 24h.
        active_addresses_7d: Unique active addresses in last 7 days.
        new_addresses_24h: Newly created addresses in 24h.
        address_growth_rate: Daily address growth rate (%).
        network_activity_score: Overall network activity score (0-1).
            Based on address count relative to historical norms.
        timestamp: When the data was fetched.
    """

    symbol: str
    active_addresses_24h: int = 0
    active_addresses_7d: int = 0
    new_addresses_24h: int = 0
    address_growth_rate: float = 0.0
    network_activity_score: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class TransactionMetrics:
    """Transaction-level metrics.

    Attributes:
        symbol: Asset symbol.
        transaction_count_24h: Number of transactions in 24h.
        transaction_volume_usd_24h: Total transaction volume in USD (24h).
        avg_transaction_size_usd: Average transaction size in USD.
        median_transaction_size_usd: Median transaction size in USD.
        large_tx_count_24h: Transactions > $100k in 24h.
        large_tx_volume_pct: Percentage of volume from large transactions.
        timestamp: When the data was fetched.
    """

    symbol: str
    transaction_count_24h: int = 0
    transaction_volume_usd_24h: float = 0.0
    avg_transaction_size_usd: float = 0.0
    median_transaction_size_usd: float = 0.0
    large_tx_count_24h: int = 0
    large_tx_volume_pct: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class NetworkHealth:
    """Network health indicators.

    Attributes:
        symbol: Asset symbol.
        hash_rate: Current hash rate (PoW chains).
        hash_rate_change_30d: 30-day hash rate change (%).
        difficulty: Current mining difficulty (PoW chains).
        block_time_avg: Average block time in seconds.
        mempool_size: Pending transaction count in mempool.
        mempool_size_bytes: Mempool size in bytes.
        fee_rate_avg: Average fee rate (sat/vB or gwei).
        network_utilization: Network capacity utilization (%).
        timestamp: When the data was fetched.
    """

    symbol: str
    hash_rate: float = 0.0
    hash_rate_change_30d: float = 0.0
    difficulty: float = 0.0
    block_time_avg: float = 0.0
    mempool_size: int = 0
    mempool_size_bytes: int = 0
    fee_rate_avg: float = 0.0
    network_utilization: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OnChainMetrics:
    """Comprehensive on-chain metrics for a cryptocurrency.

    Combines whale tracking, exchange flows, address activity,
    transaction data, and network health into a single snapshot.

    Attributes:
        symbol: Asset symbol.
        active_addresses: Active address metrics.
        transactions: Transaction metrics.
        network_health: Network health indicators.
        whale_alerts: Recent whale movements.
        exchange_flow: Exchange flow data.
        composite_score: Aggregate on-chain health score (0-1).
            Weighted combination of all sub-metrics.
        timestamp: When the metrics were fetched.
    """

    symbol: str
    active_addresses: ActiveAddresses | None = None
    transactions: TransactionMetrics | None = None
    network_health: NetworkHealth | None = None
    whale_alerts: tuple[WhaleMovement, ...] = ()
    exchange_flow: ExchangeFlow | None = None
    composite_score: float = 0.0
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# COINGECKO ID MAPPING
# ═══════════════════════════════════════════════════════════════════════

_COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "NEAR": "near",
    "ARB": "arbitrum",
    "OP": "optimism",
    "APT": "aptos",
    "SUI": "sui",
    "FIL": "filecoin",
    "LTC": "litecoin",
}


# ═══════════════════════════════════════════════════════════════════════
# ON-CHAIN ANALYTICS TOOLS
# ═══════════════════════════════════════════════════════════════════════


class OnChainAnalytics:
    """On-chain analytics tools for crypto markets.

    Provides whale wallet tracking, exchange inflow/outflow analysis,
    active address monitoring, transaction metrics, and network health.

    Data is sourced from free/public APIs with caching and rate limiting.
    When specialized APIs (Glassnode, CryptoQuant) are unavailable,
    estimates are derived from CoinGecko volume data and heuristics.
    """

    description = (
        "On-chain analytics: whale tracking, exchange flows, "
        "active addresses, transaction metrics, network health"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None

        # Cache with TTL
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 300)

        # Whale threshold (USD) — transactions above this are flagged
        self._whale_threshold_usd = self._config.get("whale_threshold_usd", 1_000_000)

        # Optional API keys for enhanced data
        self._etherscan_key = self._config.get("etherscan_api_key", "")
        self._blockchain_key = self._config.get("blockchain_api_key", "")

        # Professional analytics providers (Glassnode, CryptoQuant, etc.)
        # with automatic fallback to CoinGecko estimates
        self._analytics_chain: FallbackChain | None = None
        self._analytics_initialized = False

    def _init_analytics_chain(self) -> FallbackChain:
        """Lazy-initialize the professional analytics fallback chain."""
        if not self._analytics_initialized:
            self._analytics_initialized = True
            self._analytics_chain = FallbackChain.from_config(self._config)
        return self._analytics_chain

    async def close(self) -> None:
        """Close HTTP client and analytics providers."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        if self._analytics_chain:
            await self._analytics_chain.close()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    def _get_cached(self, key: str) -> Any | None:
        """Get from cache if not expired."""
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        """Store in cache."""
        self._cache[key] = (time.time(), value)

    # ── Whale Wallet Tracking ────────────────────────────────────────

    async def get_whale_movements(
        self,
        symbol: str,
        limit: int = 20,
    ) -> tuple[WhaleMovement, ...]:
        """Track large (whale) transactions for a cryptocurrency.

        Detects transfers above the configured whale threshold and
        classifies them as exchange inflow, outflow, or transfer.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").
            limit: Maximum number of whale movements to return.

        Returns:
            Tuple of WhaleMovement objects, newest first.
        """
        cache_key = f"whales:{symbol}:{limit}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        base_symbol = symbol.split("/")[0].upper()

        movements: list[WhaleMovement] = []

        # Fetch recent large transactions from blockchain explorers
        if base_symbol == "BTC":
            movements = await self._fetch_btc_whale_moves(client, limit)
        elif base_symbol == "ETH":
            movements = await self._fetch_eth_whale_moves(client, limit)
        else:
            # For other chains, estimate from CoinGecko volume data
            movements = await self._estimate_whale_moves(client, base_symbol, limit)

        result = tuple(movements)
        self._set_cached(cache_key, result)
        return result

    async def _fetch_btc_whale_moves(
        self,
        client: httpx.AsyncClient,
        limit: int,
    ) -> list[WhaleMovement]:
        """Fetch large BTC transactions from Blockchain.com API."""
        movements: list[WhaleMovement] = []
        try:
            # Blockchain.com unconfirmed transactions
            resp = await client.get(
                "https://blockchain.info/unconfirmed-transactions?format=json",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            for tx in data.get("txs", [])[:100]:
                # Calculate total output value in BTC
                total_out_btc = sum(
                    o.get("value", 0) / 1e8 for o in tx.get("out", [])
                )

                # Get BTC price for USD conversion
                if total_out_btc * 50_000 < self._whale_threshold_usd:
                    continue

                # Estimate USD value (approximate BTC price)
                btc_price = await self._get_btc_price(client)
                amount_usd = total_out_btc * btc_price

                # Classify direction (heuristic: if many outputs, likely exchange)
                out_count = len(tx.get("out", []))
                if out_count > 10:
                    direction = "exchange_inflow"
                elif out_count == 1:
                    direction = "exchange_outflow"
                else:
                    direction = "transfer"

                from_addr = tx.get("inputs", [{}])[0].get("prev_out", {}).get("addr", "")
                to_addr = tx.get("out", [{}])[0].get("addr", "")

                significance = min(1.0, amount_usd / (self._whale_threshold_usd * 10))

                movements.append(WhaleMovement(
                    symbol="BTC",
                    amount=round(total_out_btc, 8),
                    amount_usd=round(amount_usd, 2),
                    direction=direction,
                    from_address=from_addr[:12] + "..." if len(from_addr) > 12 else from_addr,
                    to_address=to_addr[:12] + "..." if len(to_addr) > 12 else to_addr,
                    timestamp=datetime.fromtimestamp(tx.get("time", 0), tz=UTC),
                    significance=round(significance, 4),
                ))

                if len(movements) >= limit:
                    break

        except Exception as exc:
            logger.debug("BTC whale fetch failed: %s", exc)

        return movements

    async def _fetch_eth_whale_moves(
        self,
        client: httpx.AsyncClient,
        limit: int,
    ) -> list[WhaleMovement]:
        """Fetch large ETH transactions from Etherscan public API."""
        movements: list[WhaleMovement] = []
        try:
            # Etherscan public API — latest blocks' internal transactions
            # This is a simplified approach; full tracking needs a dedicated node
            resp = await client.get(
                "https://api.etherscan.io/api",
                params={
                    "module": "proxy",
                    "action": "eth_getBlockByNumber",
                    "tag": "latest",
                    "boolean": "true",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            block = data.get("result", {})
            eth_price = await self._get_eth_price(client)

            for tx in block.get("transactions", [])[:limit]:
                value_wei = int(tx.get("value", "0x0"), 16)
                value_eth = value_wei / 1e18
                amount_usd = value_eth * eth_price

                if amount_usd < self._whale_threshold_usd:
                    continue

                from_addr = tx.get("from", "")
                to_addr = tx.get("to", "")

                # Heuristic: contracts are likely exchanges
                if to_addr and len(to_addr) == 42:
                    direction = "exchange_inflow"
                else:
                    direction = "transfer"

                significance = min(1.0, amount_usd / (self._whale_threshold_usd * 10))

                movements.append(WhaleMovement(
                    symbol="ETH",
                    amount=round(value_eth, 8),
                    amount_usd=round(amount_usd, 2),
                    direction=direction,
                    from_address=from_addr[:12] + "..." if len(from_addr) > 12 else from_addr,
                    to_address=to_addr[:12] + "..." if len(to_addr) > 12 else to_addr,
                    timestamp=datetime.now(UTC),
                    significance=round(significance, 4),
                ))

                if len(movements) >= limit:
                    break

        except Exception as exc:
            logger.debug("ETH whale fetch failed: %s", exc)

        return movements

    async def _estimate_whale_moves(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        limit: int,
    ) -> list[WhaleMovement]:
        """Estimate whale movements from CoinGecko volume data.

        When direct on-chain data isn't available, we estimate
        whale activity from volume patterns and price movements.
        """
        movements: list[WhaleMovement] = []
        try:
            coin_id = _COINGECKO_IDS.get(symbol)
            if not coin_id:
                return []

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={"localization": "false", "tickers": "false"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            market = data.get("market_data", {})
            total_volume = float(market.get("total_volume", {}).get("usd", 0))
            price = float(market.get("current_price", {}).get("usd", 0))
            price_change = float(market.get("price_change_percentage_24h", 0))

            if price <= 0 or total_volume <= 0:
                return []

            # Estimate whale activity: ~5-10% of volume is whale-sized
            whale_volume_pct = 0.075
            estimated_whale_volume = total_volume * whale_volume_pct

            # Generate synthetic whale movements based on volume patterns
            num_whales = min(limit, max(3, int(estimated_whale_volume / self._whale_threshold_usd)))

            for i in range(num_whales):
                # Distribute whale volume with decreasing sizes
                amount_usd = estimated_whale_volume / (i + 1) * 0.5
                if amount_usd < self._whale_threshold_usd:
                    break

                amount_token = amount_usd / price

                # Direction based on price movement
                if price_change > 2:
                    direction = "exchange_outflow"  # Bullish accumulation
                elif price_change < -2:
                    direction = "exchange_inflow"  # Bearish selling
                else:
                    direction = "transfer"

                significance = min(1.0, amount_usd / (self._whale_threshold_usd * 10))

                movements.append(WhaleMovement(
                    symbol=symbol,
                    amount=round(amount_token, 8),
                    amount_usd=round(amount_usd, 2),
                    direction=direction,
                    from_address="estimated",
                    to_address="estimated",
                    timestamp=datetime.now(UTC),
                    significance=round(significance, 4),
                ))

        except Exception as exc:
            logger.debug("Whale estimation failed for %s: %s", symbol, exc)

        return movements

    # ── Exchange Inflow/Outflow ───────────────────────────────────────

    async def get_exchange_flow(self, symbol: str) -> ExchangeFlow:
        """Get exchange inflow/outflow data for a cryptocurrency.

        Large inflows to exchanges suggest selling pressure (bearish).
        Large outflows from exchanges suggest accumulation (bullish).

        Uses professional providers (Glassnode, CryptoQuant) when API keys
        are configured, falling back to CoinGecko volume-based estimation.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            ExchangeFlow with inflow, outflow, net flow, and signal.
        """
        cache_key = f"exchange_flow:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base_symbol = symbol.split("/")[0].upper()

        # Try professional analytics providers first (Glassnode → CryptoQuant → CoinGecko)
        analytics = self._init_analytics_chain()
        pro_flow = await analytics.get_exchange_flows(base_symbol)

        if pro_flow.source and pro_flow.source != "none" and (pro_flow.inflow_24h > 0 or pro_flow.outflow_24h > 0):
            # Derive signal from professional data
            net_flow = pro_flow.net_flow_24h
            total_volume = pro_flow.inflow_24h + pro_flow.outflow_24h
            flow_ratio = abs(net_flow) / total_volume if total_volume > 0 else 0

            if net_flow > 0 and flow_ratio > 0.05:
                signal = "bearish"
            elif net_flow < 0 and flow_ratio > 0.05:
                signal = "bullish"
            else:
                signal = "neutral"

            result = ExchangeFlow(
                symbol=base_symbol,
                inflow_24h=round(pro_flow.inflow_24h, 2),
                outflow_24h=round(pro_flow.outflow_24h, 2),
                net_flow_24h=round(net_flow, 2),
                flow_signal=signal,
                reserve_change_pct=pro_flow.reserve_change_pct,
                whale_inflow_count=pro_flow.whale_inflow_count,
                whale_outflow_count=pro_flow.whale_outflow_count,
                timestamp=datetime.now(UTC),
            )

            self._set_cached(cache_key, result)
            return result

        # Fallback: CoinGecko volume-based estimation (original logic)
        return await self._exchange_flow_coingecko_fallback(base_symbol)

    async def _exchange_flow_coingecko_fallback(self, base_symbol: str) -> ExchangeFlow:
        """CoinGecko-based exchange flow estimation (fallback when pro APIs unavailable)."""
        cache_key = f"exchange_flow:{base_symbol}"
        client = await self._get_client()

        try:
            coin_id = _COINGECKO_IDS.get(base_symbol)
            if not coin_id:
                return self._default_exchange_flow(base_symbol)

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={"localization": "false", "tickers": "false"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            market = data.get("market_data", {})
            total_volume = float(market.get("total_volume", {}).get("usd", 0))
            price_change_pct = float(market.get("price_change_percentage_24h", 0))

            # Estimate exchange flows from volume and price patterns
            base_inflow = total_volume * 0.30
            base_outflow = total_volume * 0.28

            if price_change_pct > 5:
                inflow = base_inflow * 0.8
                outflow = base_outflow * 1.3
            elif price_change_pct > 0:
                inflow = base_inflow * 0.9
                outflow = base_outflow * 1.1
            elif price_change_pct > -5:
                inflow = base_inflow * 1.1
                outflow = base_outflow * 0.9
            else:
                inflow = base_inflow * 1.3
                outflow = base_outflow * 0.8

            net_flow = inflow - outflow

            flow_ratio = abs(net_flow) / total_volume if total_volume > 0 else 0
            if net_flow > 0 and flow_ratio > 0.05:
                signal = "bearish"
            elif net_flow < 0 and flow_ratio > 0.05:
                signal = "bullish"
            else:
                signal = "neutral"

            whale_threshold = self._whale_threshold_usd
            whale_inflow_count = max(0, int(inflow / whale_threshold * 0.1))
            whale_outflow_count = max(0, int(outflow / whale_threshold * 0.1))

            result = ExchangeFlow(
                symbol=base_symbol,
                inflow_24h=round(inflow, 2),
                outflow_24h=round(outflow, 2),
                net_flow_24h=round(net_flow, 2),
                flow_signal=signal,
                whale_inflow_count=whale_inflow_count,
                whale_outflow_count=whale_outflow_count,
                timestamp=datetime.now(UTC),
            )

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Exchange flow fetch failed for %s: %s", base_symbol, exc)
            return self._default_exchange_flow(base_symbol)

    @staticmethod
    def _default_exchange_flow(symbol: str) -> ExchangeFlow:
        """Return default ExchangeFlow when data is unavailable."""
        return ExchangeFlow(
            symbol=symbol,
            inflow_24h=0.0,
            outflow_24h=0.0,
            net_flow_24h=0.0,
            flow_signal="neutral",
            timestamp=datetime.now(UTC),
        )

    # ── Active Addresses ─────────────────────────────────────────────

    async def get_active_addresses(self, symbol: str) -> ActiveAddresses:
        """Get active address metrics for a cryptocurrency.

        Active address count is a key network health indicator:
        - Rising addresses = growing adoption
        - Falling addresses = declining usage
        - Spikes often precede major price moves

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            ActiveAddresses with 24h/7d counts and activity score.
        """
        cache_key = f"active_addr:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        base_symbol = symbol.split("/")[0].upper()

        try:
            if base_symbol == "BTC":
                result = await self._fetch_btc_active_addresses(client)
            elif base_symbol == "ETH":
                result = await self._fetch_eth_active_addresses(client)
            else:
                result = await self._estimate_active_addresses(client, base_symbol)

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Active address fetch failed for %s: %s", symbol, exc)
            return ActiveAddresses(symbol=base_symbol, timestamp=datetime.now(UTC))

    async def _fetch_btc_active_addresses(
        self,
        client: httpx.AsyncClient,
    ) -> ActiveAddresses:
        """Fetch BTC active addresses from Blockchain.com charts API."""
        try:
            resp = await client.get(
                "https://api.blockchain.info/charts/n-active-addresses",
                params={"timespan": "7days", "format": "json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            values = data.get("values", [])
            if not values:
                return ActiveAddresses(symbol="BTC", timestamp=datetime.now(UTC))

            latest = int(values[-1].get("y", 0))
            week_ago = int(values[0].get("y", 0)) if len(values) > 1 else latest

            # Estimate 24h from latest data point
            active_24h = latest
            active_7d = max(latest, week_ago)

            # Growth rate
            if week_ago > 0:
                growth = (latest - week_ago) / week_ago * 100
            else:
                growth = 0.0

            # Activity score: normalize against typical BTC ranges
            # ~800k-1.2M active addresses/day is healthy for BTC
            activity_score = min(1.0, active_24h / 1_000_000)

            return ActiveAddresses(
                symbol="BTC",
                active_addresses_24h=active_24h,
                active_addresses_7d=active_7d,
                address_growth_rate=round(growth, 2),
                network_activity_score=round(activity_score, 4),
                timestamp=datetime.now(UTC),
            )

        except Exception as exc:
            logger.debug("BTC active address fetch failed: %s", exc)
            return ActiveAddresses(symbol="BTC", timestamp=datetime.now(UTC))

    async def _fetch_eth_active_addresses(
        self,
        client: httpx.AsyncClient,
    ) -> ActiveAddresses:
        """Fetch ETH active addresses from Etherscan-style public data."""
        try:
            # Use Etherscan stats API (public, rate-limited)
            resp = await client.get(
                "https://api.etherscan.io/api",
                params={
                    "module": "stats",
                    "action": "ethsupply",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            # Etherscan doesn't directly expose active addresses on free tier
            # Fall back to CoinGecko community data for estimation
            return await self._estimate_active_addresses(client, "ETH")

        except Exception as exc:
            logger.debug("ETH active address fetch failed: %s", exc)
            return ActiveAddresses(symbol="ETH", timestamp=datetime.now(UTC))

    async def _estimate_active_addresses(
        self,
        client: httpx.AsyncClient,
        symbol: str,
    ) -> ActiveAddresses:
        """Estimate active addresses from CoinGecko community data."""
        try:
            coin_id = _COINGECKO_IDS.get(symbol)
            if not coin_id:
                return ActiveAddresses(symbol=symbol, timestamp=datetime.now(UTC))

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={"localization": "false", "tickers": "false"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            market = data.get("market_data", {})
            community = data.get("community_data", {})
            total_volume = float(market.get("total_volume", {}).get("usd", 0))

            # Rough estimation: active addresses correlate with volume
            # BTC ~800k-1.2M at ~$30B daily volume
            volume_ratio = total_volume / 30_000_000_000 if total_volume > 0 else 0
            estimated_active = int(900_000 * volume_ratio)
            estimated_active = max(1000, estimated_active)

            activity_score = min(1.0, estimated_active / 1_000_000)

            return ActiveAddresses(
                symbol=symbol,
                active_addresses_24h=estimated_active,
                active_addresses_7d=int(estimated_active * 6.5),
                address_growth_rate=0.0,
                network_activity_score=round(activity_score, 4),
                timestamp=datetime.now(UTC),
            )

        except Exception as exc:
            logger.debug("Active address estimation failed for %s: %s", symbol, exc)
            return ActiveAddresses(symbol=symbol, timestamp=datetime.now(UTC))

    # ── Transaction Metrics ──────────────────────────────────────────

    async def get_transaction_metrics(self, symbol: str) -> TransactionMetrics:
        """Get transaction-level metrics for a cryptocurrency.

        Transaction count and volume patterns reveal network usage:
        - Rising tx count + rising price = healthy uptrend
        - Rising tx count + falling price = distribution
        - Falling tx count = declining interest

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            TransactionMetrics with counts, volumes, and large tx data.
        """
        cache_key = f"tx_metrics:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        base_symbol = symbol.split("/")[0].upper()

        try:
            if base_symbol == "BTC":
                result = await self._fetch_btc_tx_metrics(client)
            else:
                result = await self._estimate_tx_metrics(client, base_symbol)

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Transaction metrics fetch failed for %s: %s", symbol, exc)
            return TransactionMetrics(symbol=base_symbol, timestamp=datetime.now(UTC))

    async def _fetch_btc_tx_metrics(
        self,
        client: httpx.AsyncClient,
    ) -> TransactionMetrics:
        """Fetch BTC transaction metrics from Blockchain.com."""
        try:
            # Fetch n-transactions chart
            resp = await client.get(
                "https://api.blockchain.info/charts/n-transactions",
                params={"timespan": "1days", "format": "json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            values = data.get("values", [])
            tx_count = int(values[-1].get("y", 0)) if values else 0

            # Fetch estimated transaction volume
            resp2 = await client.get(
                "https://api.blockchain.info/charts/estimated-transaction-volume-usd",
                params={"timespan": "1days", "format": "json"},
                timeout=10,
            )
            resp2.raise_for_status()
            vol_data = resp2.json()

            vol_values = vol_data.get("values", [])
            tx_volume = float(vol_values[-1].get("y", 0)) if vol_values else 0.0

            avg_size = tx_volume / tx_count if tx_count > 0 else 0.0

            return TransactionMetrics(
                symbol="BTC",
                transaction_count_24h=tx_count,
                transaction_volume_usd_24h=round(tx_volume * 1e6, 2),  # Often in millions
                avg_transaction_size_usd=round(avg_size, 2),
                timestamp=datetime.now(UTC),
            )

        except Exception as exc:
            logger.debug("BTC tx metrics fetch failed: %s", exc)
            return TransactionMetrics(symbol="BTC", timestamp=datetime.now(UTC))

    async def _estimate_tx_metrics(
        self,
        client: httpx.AsyncClient,
        symbol: str,
    ) -> TransactionMetrics:
        """Estimate transaction metrics from CoinGecko data."""
        try:
            coin_id = _COINGECKO_IDS.get(symbol)
            if not coin_id:
                return TransactionMetrics(symbol=symbol, timestamp=datetime.now(UTC))

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={"localization": "false", "tickers": "false"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            market = data.get("market_data", {})
            total_volume = float(market.get("total_volume", {}).get("usd", 0))
            price = float(market.get("current_price", {}).get("usd", 0))

            # Estimate tx count from volume
            # Average tx size varies by chain
            avg_tx_sizes = {
                "ETH": 2000, "SOL": 500, "BNB": 1000,
                "XRP": 100, "ADA": 200, "DOT": 300,
            }
            avg_tx = avg_tx_sizes.get(symbol, 1000)
            estimated_tx_count = int(total_volume / avg_tx) if avg_tx > 0 else 0

            # Large tx: ~10% of volume from transactions > $100k
            large_tx_pct = 0.10
            large_tx_volume = total_volume * large_tx_pct
            large_tx_count = int(large_tx_volume / 200_000)  # avg large tx ~$200k

            return TransactionMetrics(
                symbol=symbol,
                transaction_count_24h=estimated_tx_count,
                transaction_volume_usd_24h=round(total_volume, 2),
                avg_transaction_size_usd=round(avg_tx, 2),
                large_tx_count_24h=large_tx_count,
                large_tx_volume_pct=round(large_tx_pct * 100, 2),
                timestamp=datetime.now(UTC),
            )

        except Exception as exc:
            logger.debug("Tx metrics estimation failed for %s: %s", symbol, exc)
            return TransactionMetrics(symbol=symbol, timestamp=datetime.now(UTC))

    # ── Network Health ───────────────────────────────────────────────

    async def get_network_health(self, symbol: str) -> NetworkHealth:
        """Get network health indicators for a cryptocurrency.

        Monitors hash rate, block times, mempool, and fees to assess
        network operational status.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            NetworkHealth with hash rate, block time, mempool, fees.
        """
        cache_key = f"network_health:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        base_symbol = symbol.split("/")[0].upper()

        try:
            if base_symbol == "BTC":
                result = await self._fetch_btc_network_health(client)
            elif base_symbol == "ETH":
                result = await self._fetch_eth_network_health(client)
            else:
                result = NetworkHealth(symbol=base_symbol, timestamp=datetime.now(UTC))

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Network health fetch failed for %s: %s", symbol, exc)
            return NetworkHealth(symbol=base_symbol, timestamp=datetime.now(UTC))

    async def _fetch_btc_network_health(
        self,
        client: httpx.AsyncClient,
    ) -> NetworkHealth:
        """Fetch BTC network health from Blockchain.com."""
        try:
            # Hash rate
            hr_resp = await client.get(
                "https://api.blockchain.info/charts/hash-rate",
                params={"timespan": "30days", "format": "json"},
                timeout=10,
            )
            hr_resp.raise_for_status()
            hr_data = hr_resp.json()

            hr_values = hr_data.get("values", [])
            current_hr = float(hr_values[-1].get("y", 0)) if hr_values else 0.0
            old_hr = float(hr_values[0].get("y", 0)) if len(hr_values) > 1 else current_hr
            hr_change = ((current_hr - old_hr) / old_hr * 100) if old_hr > 0 else 0.0

            # Mempool
            mempool_resp = await client.get(
                "https://blockchain.info/q/unconfirmedcount",
                timeout=10,
            )
            mempool_resp.raise_for_status()
            mempool_size = int(mempool_resp.text.strip())

            return NetworkHealth(
                symbol="BTC",
                hash_rate=current_hr,
                hash_rate_change_30d=round(hr_change, 2),
                mempool_size=mempool_size,
                block_time_avg=600.0,  # ~10 min target
                timestamp=datetime.now(UTC),
            )

        except Exception as exc:
            logger.debug("BTC network health fetch failed: %s", exc)
            return NetworkHealth(symbol="BTC", timestamp=datetime.now(UTC))

    async def _fetch_eth_network_health(
        self,
        client: httpx.AsyncClient,
    ) -> NetworkHealth:
        """Fetch ETH network health from Etherscan."""
        try:
            resp = await client.get(
                "https://api.etherscan.io/api",
                params={"module": "proxy", "action": "eth_gasPrice"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            gas_price_wei = int(data.get("result", "0x0"), 16)
            gas_price_gwei = gas_price_wei / 1e9

            return NetworkHealth(
                symbol="ETH",
                fee_rate_avg=round(gas_price_gwei, 2),
                block_time_avg=12.0,  # ~12 sec post-merge
                timestamp=datetime.now(UTC),
            )

        except Exception as exc:
            logger.debug("ETH network health fetch failed: %s", exc)
            return NetworkHealth(symbol="ETH", timestamp=datetime.now(UTC))

    # ── Comprehensive On-Chain Metrics ───────────────────────────────

    async def get_on_chain_metrics(self, symbol: str) -> OnChainMetrics:
        """Get comprehensive on-chain metrics for a cryptocurrency.

        Combines all on-chain sub-tools into a single snapshot:
        - Active addresses
        - Transaction metrics
        - Network health
        - Whale movements
        - Exchange flows

        Also computes a composite score (0-1) aggregating all metrics.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            OnChainMetrics with all sub-metrics and composite score.
        """
        cache_key = f"onchain_full:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base_symbol = symbol.split("/")[0].upper()

        # Fetch all sub-metrics in parallel
        results = await asyncio.gather(
            self.get_active_addresses(symbol),
            self.get_transaction_metrics(symbol),
            self.get_network_health(symbol),
            self.get_whale_movements(symbol, limit=10),
            self.get_exchange_flow(symbol),
            return_exceptions=True,
        )

        active_addr = results[0] if not isinstance(results[0], Exception) else ActiveAddresses(symbol=base_symbol)
        tx_metrics = results[1] if not isinstance(results[1], Exception) else TransactionMetrics(symbol=base_symbol)
        net_health = results[2] if not isinstance(results[2], Exception) else NetworkHealth(symbol=base_symbol)
        whale_moves = results[3] if not isinstance(results[3], Exception) else ()
        exchange_flow = results[4] if not isinstance(results[4], Exception) else None

        # Compute composite score
        scores: list[float] = []
        if active_addr.network_activity_score > 0:
            scores.append(active_addr.network_activity_score)
        if net_health.hash_rate > 0:
            scores.append(min(1.0, net_health.hash_rate / 1e9))  # Normalize
        if exchange_flow and exchange_flow.flow_signal == "bullish":
            scores.append(0.7)
        elif exchange_flow and exchange_flow.flow_signal == "bearish":
            scores.append(0.3)
        else:
            scores.append(0.5)

        composite = sum(scores) / len(scores) if scores else 0.5

        result = OnChainMetrics(
            symbol=base_symbol,
            active_addresses=active_addr,
            transactions=tx_metrics,
            network_health=net_health,
            whale_alerts=whale_moves if isinstance(whale_moves, tuple) else (),
            exchange_flow=exchange_flow,
            composite_score=round(composite, 4),
            timestamp=datetime.now(UTC),
        )

        self._set_cached(cache_key, result)
        return result

    # ── Price Helpers ────────────────────────────────────────────────

    async def _get_btc_price(self, client: httpx.AsyncClient) -> float:
        """Get current BTC price in USD."""
        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "usd"},
                timeout=5,
            )
            resp.raise_for_status()
            return float(resp.json().get("bitcoin", {}).get("usd", 50_000))
        except Exception:
            return 50_000.0

    async def _get_eth_price(self, client: httpx.AsyncClient) -> float:
        """Get current ETH price in USD."""
        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "ethereum", "vs_currencies": "usd"},
                timeout=5,
            )
            resp.raise_for_status()
            return float(resp.json().get("ethereum", {}).get("usd", 3_000))
        except Exception:
            return 3_000.0
