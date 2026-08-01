"""
TSAR — Professional On-Chain Analytics Providers.

Tiered data sources with automatic fallback:
  Glassnode → CryptoQuant → CoinGecko (free)

Each provider exposes a common interface for exchange flows, whale data,
and fundamental on-chain metrics. The FallbackChain orchestrator tries
providers in priority order and degrades gracefully.

Providers:
  - GlassnodeClient: SOPR, MVRV, exchange flows, whale clustering
  - NansenClient: Smart money tracking, token god mode, whale wallets
  - CryptoQuantClient: Exchange reserves, miner flows, funding rates
  - DeFiLlamaClient: TVL tracking, yield pools, protocol revenue (free)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# SHARED RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ExchangeFlowData:
    """Standardised exchange flow data across providers."""

    symbol: str
    inflow_24h: float = 0.0
    outflow_24h: float = 0.0
    net_flow_24h: float = 0.0
    exchange_reserves: float = 0.0
    reserve_change_pct: float = 0.0
    whale_inflow_count: int = 0
    whale_outflow_count: int = 0
    funding_rate: float = 0.0
    open_interest: float = 0.0
    source: str = ""
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OnChainFundamentals:
    """Fundamental on-chain metrics: SOPR, MVRV, NVT, etc."""

    symbol: str
    sopr: float = 0.0  # Spent Output Profit Ratio
    mvrv: float = 0.0  # Market Value to Realized Value
    nvt_ratio: float = 0.0  # Network Value to Transactions
    nvt_signal: float = 0.0
    realized_cap: float = 0.0
    market_cap: float = 0.0
    active_addresses: int = 0
    new_addresses: int = 0
    tx_count_24h: int = 0
    tx_volume_usd: float = 0.0
    miner_revenue: float = 0.0
    fees_usd: float = 0.0
    puell_multiple: float = 0.0
    stock_to_flow: float = 0.0
    source: str = ""
    timestamp: datetime | None = None


@dataclass(frozen=True)
class SmartMoneyFlow:
    """Smart money / whale wallet activity."""

    symbol: str
    whale_balance_change_24h: float = 0.0
    whale_balance_change_7d: float = 0.0
    smart_money_direction: str = "neutral"  # "accumulating", "distributing", "neutral"
    top_holder_concentration: float = 0.0  # % of supply held by top wallets
    exchange_whale_ratio: float = 0.0  # whale deposits vs total exchange deposits
    stablecoin_supply_ratio: float = 0.0
    source: str = ""
    timestamp: datetime | None = None


@dataclass(frozen=True)
class YieldPool:
    """A DeFi yield pool opportunity."""

    protocol: str
    chain: str
    pool_id: str
    symbol: str
    tvl_usd: float = 0.0
    apy: float = 0.0
    apy_base: float = 0.0
    apy_reward: float = 0.0
    il_risk: str = "none"  # "none", "low", "medium", "high"
    stable_pool: bool = False
    exposure: str = "single"  # "single", "multi"
    pool_meta: str = ""
    source: str = "defillama"
    timestamp: datetime | None = None


@dataclass(frozen=True)
class ProtocolTVL:
    """Protocol TVL data."""

    protocol: str
    chain: str
    tvl_usd: float = 0.0
    tvl_change_1d: float = 0.0
    tvl_change_7d: float = 0.0
    tvl_change_30d: float = 0.0
    mcap_tvl_ratio: float = 0.0
    revenue_24h: float = 0.0
    fees_24h: float = 0.0
    source: str = "defillama"
    timestamp: datetime | None = None


@dataclass(frozen=True)
class MinerFlowData:
    """Miner-specific flow metrics."""

    symbol: str
    miner_outflow_24h: float = 0.0
    miner_inflow_24h: float = 0.0
    miner_net_flow: float = 0.0
    miner_balance: float = 0.0
    miner_revenue_usd: float = 0.0
    hash_rate: float = 0.0
    difficulty: float = 0.0
    source: str = ""
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# PROVIDER PROTOCOL
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class AnalyticsProvider(Protocol):
    """Protocol that all analytics providers must satisfy."""

    name: str
    priority: int  # Lower = tried first

    async def is_available(self) -> bool: ...
    async def get_exchange_flows(self, symbol: str) -> ExchangeFlowData | None: ...
    async def get_fundamentals(self, symbol: str) -> OnChainFundamentals | None: ...
    async def get_smart_money(self, symbol: str) -> SmartMoneyFlow | None: ...
    async def close(self) -> None: ...


# ═══════════════════════════════════════════════════════════════════════
# CACHE HELPER
# ═══════════════════════════════════════════════════════════════════════


class _TTLCache:
    """Simple in-memory TTL cache."""

    def __init__(self, default_ttl: int = 300) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = default_ttl

    def get(self, key: str) -> Any | None:
        if key in self._store:
            ts, val = self._store[key]
            if time.time() - ts < self._ttl:
                return val
            del self._store[key]
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._store[key] = (time.time(), value)

    def clear(self) -> None:
        self._store.clear()


# ═══════════════════════════════════════════════════════════════════════
# GLASSNODE CLIENT
# ═══════════════════════════════════════════════════════════════════════


class GlassnodeClient:
    """Glassnode API client — professional on-chain analytics.

    Provides: SOPR, MVRV, exchange flows, whale clustering, NVT,
    realized cap, miner revenue, and more.

    Requires API key (paid tier). Free tier has limited metrics.
    Docs: https://docs.glassnode.com/basic-api/api
    """

    name = "glassnode"
    priority = 1

    BASE_URL = "https://api.glassnode.com/v1/metrics"

    # Map our symbols to Glassnode asset codes
    _ASSET_MAP: dict[str, str] = {
        "BTC": "BTC", "ETH": "ETH", "LTC": "LTC",
        "BCH": "BCH", "XRP": "XRP", "ADA": "ADA",
        "DOT": "DOT", "SOL": "SOL", "DOGE": "DOGE",
        "AVAX": "AVAX", "MATIC": "MATIC", "LINK": "LINK",
    }

    def __init__(self, api_key: str, config: dict[str, Any] | None = None) -> None:
        self._api_key = api_key
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._cache = _TTLCache(self._config.get("cache_ttl_s", 600))

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=20.0,
                params={"api_key": self._api_key},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def is_available(self) -> bool:
        """Check if API key is set and endpoint responds."""
        if not self._api_key:
            return False
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.BASE_URL}/market/price_usd_close",
                params={"a": "BTC", "i": "24h", "s": int(time.time()) - 86400, "u": int(time.time())},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def get_exchange_flows(self, symbol: str) -> ExchangeFlowData | None:
        """Get exchange inflow/outflow from Glassnode."""
        asset = self._ASSET_MAP.get(symbol.upper())
        if not asset:
            return None

        cache_key = f"gn_flow:{asset}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        now = int(time.time())
        start = now - 86400 * 2  # 2 days for delta

        try:
            # Fetch multiple metrics in parallel
            metrics = {
                "inflow": "transactions/transfers_to_exchanges_sum",
                "outflow": "transactions/transfers_from_exchanges_sum",
                "reserves": "distribution/balance_exchanges",
                "supply": "supply/current",
            }

            results: dict[str, float] = {}
            for key, metric_path in metrics.items():
                try:
                    resp = await client.get(
                        f"{self.BASE_URL}/{metric_path}",
                        params={"a": asset, "i": "24h", "s": start, "u": now},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data:
                            results[key] = float(data[-1].get("v", 0))
                except Exception as exc:
                    logger.debug("Glassnode metric %s failed: %s", key, exc)

            inflow = results.get("inflow", 0.0)
            outflow = results.get("outflow", 0.0)
            reserves = results.get("reserves", 0.0)
            net_flow = inflow - outflow

            # Calculate reserve change
            reserve_pct = 0.0
            if reserves > 0 and "supply" in results:
                # Normalize reserves as % of supply
                reserve_pct = (reserves / results["supply"]) * 100 if results["supply"] > 0 else 0.0

            result = ExchangeFlowData(
                symbol=symbol.upper(),
                inflow_24h=inflow,
                outflow_24h=outflow,
                net_flow_24h=net_flow,
                exchange_reserves=reserves,
                reserve_change_pct=round(reserve_pct, 4),
                source="glassnode",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Glassnode exchange flows failed for %s: %s", symbol, exc)
            return None

    async def get_fundamentals(self, symbol: str) -> OnChainFundamentals | None:
        """Get SOPR, MVRV, NVT, realized cap from Glassnode."""
        asset = self._ASSET_MAP.get(symbol.upper())
        if not asset:
            return None

        cache_key = f"gn_fund:{asset}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        now = int(time.time())
        start = now - 86400

        try:
            metric_paths = {
                "sopr": "indicators/sopr",
                "mvrv": "market/mvrv",
                "nvt": "indicators/nvt",
                "nvt_signal": "indicators/nvts",
                "realized_cap": "market/marketcap_realized_usd",
                "market_cap": "market/marketcap_usd",
                "active": "addresses/active_count",
                "new": "addresses/new_non_zero_count",
                "tx_count": "transactions/count",
                "tx_volume": "transactions/transfers_volume_usd",
                "miner_rev": "revenue/block_reward",
                "fees": "fees_volume_usd_sum",
            }

            results: dict[str, float] = {}
            for key, path in metric_paths.items():
                try:
                    resp = await client.get(
                        f"{self.BASE_URL}/{path}",
                        params={"a": asset, "i": "24h", "s": start, "u": now},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data:
                            results[key] = float(data[-1].get("v", 0))
                except Exception:
                    pass

            result = OnChainFundamentals(
                symbol=symbol.upper(),
                sopr=results.get("sopr", 0.0),
                mvrv=results.get("mvrv", 0.0),
                nvt_ratio=results.get("nvt", 0.0),
                nvt_signal=results.get("nvt_signal", 0.0),
                realized_cap=results.get("realized_cap", 0.0),
                market_cap=results.get("market_cap", 0.0),
                active_addresses=int(results.get("active", 0)),
                new_addresses=int(results.get("new", 0)),
                tx_count_24h=int(results.get("tx_count", 0)),
                tx_volume_usd=results.get("tx_volume", 0.0),
                miner_revenue=results.get("miner_rev", 0.0),
                fees_usd=results.get("fees", 0.0),
                source="glassnode",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Glassnode fundamentals failed for %s: %s", symbol, exc)
            return None

    async def get_smart_money(self, symbol: str) -> SmartMoneyFlow | None:
        """Get whale clustering and exchange whale ratio from Glassnode."""
        asset = self._ASSET_MAP.get(symbol.upper())
        if not asset:
            return None

        cache_key = f"gn_smart:{asset}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        now = int(time.time())
        start = now - 86400 * 7

        try:
            metric_paths = {
                "whale_ratio": "distribution/balance_exchanges_relative",
                "top_holder": "distribution/balance_top_1_percent_relative",
            }

            results: dict[str, float] = {}
            for key, path in metric_paths.items():
                try:
                    resp = await client.get(
                        f"{self.BASE_URL}/{path}",
                        params={"a": asset, "i": "24h", "s": start, "u": now},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and len(data) >= 2:
                            latest = float(data[-1].get("v", 0))
                            week_ago = float(data[0].get("v", 0))
                            results[f"{key}_latest"] = latest
                            results[f"{key}_change"] = latest - week_ago
                except Exception:
                    pass

            # Determine smart money direction
            whale_change = results.get("whale_ratio_change", 0.0)
            if whale_change < -0.01:
                direction = "accumulating"
            elif whale_change > 0.01:
                direction = "distributing"
            else:
                direction = "neutral"

            result = SmartMoneyFlow(
                symbol=symbol.upper(),
                whale_balance_change_24h=results.get("whale_ratio_change", 0.0),
                whale_balance_change_7d=results.get("whale_ratio_change", 0.0),
                smart_money_direction=direction,
                top_holder_concentration=results.get("top_holder_latest", 0.0),
                exchange_whale_ratio=results.get("whale_ratio_latest", 0.0),
                source="glassnode",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Glassnode smart money failed for %s: %s", symbol, exc)
            return None

    async def get_miner_flows(self, symbol: str) -> MinerFlowData | None:
        """Get miner-specific metrics from Glassnode (BTC only)."""
        if symbol.upper() != "BTC":
            return None

        cache_key = "gn_miner_btc"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()
        now = int(time.time())
        start = now - 86400

        try:
            paths = {
                "hash_rate": "mining/hash_rate_mean",
                "difficulty": "mining/difficulty_latest",
                "revenue": "revenue/block_reward",
                "outflow": "transactions/transfers_from_miners_sum",
            }

            results: dict[str, float] = {}
            for key, path in paths.items():
                try:
                    resp = await client.get(
                        f"{self.BASE_URL}/{path}",
                        params={"a": "BTC", "i": "24h", "s": start, "u": now},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data:
                            results[key] = float(data[-1].get("v", 0))
                except Exception:
                    pass

            result = MinerFlowData(
                symbol="BTC",
                miner_outflow_24h=results.get("outflow", 0.0),
                miner_revenue_usd=results.get("revenue", 0.0),
                hash_rate=results.get("hash_rate", 0.0),
                difficulty=results.get("difficulty", 0.0),
                source="glassnode",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Glassnode miner flows failed: %s", exc)
            return None


# ═══════════════════════════════════════════════════════════════════════
# NANSEN CLIENT
# ═══════════════════════════════════════════════════════════════════════


class NansenClient:
    """Nansen API client — smart money tracking & token analytics.

    Provides: Smart money wallet tracking, token god mode,
    whale wallet labels, and DeFi protocol analytics.

    Requires API key (paid tier).
    Docs: https://docs.nansen.ai/
    """

    name = "nansen"
    priority = 2

    BASE_URL = "https://api.nansen.ai/v1"

    _CHAIN_MAP: dict[str, str] = {
        "ETH": "ethereum", "BSC": "bsc", "POLYGON": "polygon",
        "ARBITRUM": "arbitrum", "OPTIMISM": "optimism",
        "AVALANCHE": "avalanche", "FANTOM": "fantom",
        "SOLANA": "solana", "BASE": "base",
    }

    def __init__(self, api_key: str, config: dict[str, Any] | None = None) -> None:
        self._api_key = api_key
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._cache = _TTLCache(self._config.get("cache_ttl_s", 600))

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=20.0,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.BASE_URL}/health", timeout=10)
            return resp.status_code in (200, 401)  # 401 means key invalid but API is up
        except Exception:
            return False

    async def get_exchange_flows(self, symbol: str) -> ExchangeFlowData | None:
        """Nansen doesn't primarily do exchange flows — delegate to smart money."""
        return None

    async def get_fundamentals(self, symbol: str) -> OnChainFundamentals | None:
        """Nansen doesn't provide SOPR/MVRV — return None for fallback chain."""
        return None

    async def get_smart_money(self, symbol: str) -> SmartMoneyFlow | None:
        """Get smart money tracking data from Nansen.

        Uses Nansen's labelled wallet data to identify whale accumulation
        and distribution patterns.
        """
        cache_key = f"nansen_smart:{symbol}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            # Try token overview endpoint for whale metrics
            resp = await client.get(
                f"{self.BASE_URL}/token/{symbol.upper()}/whale-metrics",
                timeout=15,
            )

            if resp.status_code != 200:
                # Try alternative smart money endpoint
                resp = await client.get(
                    f"{self.BASE_URL}/smart-money/token/{symbol.upper()}",
                    timeout=15,
                )

            if resp.status_code != 200:
                return None

            data = resp.json()

            # Parse smart money signals
            whale_change = float(data.get("whale_balance_change_24h", 0))
            smart_money_net = float(data.get("smart_money_net_flow", 0))

            if smart_money_net > 0:
                direction = "accumulating"
            elif smart_money_net < 0:
                direction = "distributing"
            else:
                direction = "neutral"

            result = SmartMoneyFlow(
                symbol=symbol.upper(),
                whale_balance_change_24h=whale_change,
                whale_balance_change_7d=float(data.get("whale_balance_change_7d", 0)),
                smart_money_direction=direction,
                top_holder_concentration=float(data.get("top_holder_pct", 0)),
                exchange_whale_ratio=float(data.get("exchange_whale_ratio", 0)),
                source="nansen",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Nansen smart money failed for %s: %s", symbol, exc)
            return None

    async def get_whale_wallets(
        self, chain: str = "ethereum", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get top whale wallets with Nansen labels.

        Returns list of dicts with address, label, balance, and change.
        """
        cache_key = f"nansen_whales:{chain}:{limit}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                f"{self.BASE_URL}/whale-wallets",
                params={"chain": chain, "limit": limit},
                timeout=15,
            )

            if resp.status_code != 200:
                return []

            wallets = resp.json().get("wallets", [])
            self._cache.set(cache_key, wallets)
            return wallets

        except Exception as exc:
            logger.warning("Nansen whale wallets failed: %s", exc)
            return []

    async def get_token_god_mode(self, token_address: str, chain: str = "ethereum") -> dict[str, Any]:
        """Get Token God Mode data — comprehensive token analytics.

        Returns holder distribution, smart money activity, and flow analysis.
        """
        cache_key = f"nansen_tgm:{chain}:{token_address}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                f"{self.BASE_URL}/token-god-mode/{token_address}",
                params={"chain": chain},
                timeout=15,
            )

            if resp.status_code != 200:
                return {}

            data = resp.json()
            self._cache.set(cache_key, data)
            return data

        except Exception as exc:
            logger.warning("Nansen Token God Mode failed: %s", exc)
            return {}


# ═══════════════════════════════════════════════════════════════════════
# CRYPTOQUANT CLIENT
# ═══════════════════════════════════════════════════════════════════════


class CryptoQuantClient:
    """CryptoQuant API client — exchange reserves, miner flows, funding.

    Provides: Exchange reserves, miner outflows, funding rates,
    open interest, and derivatives data.

    Requires API key (paid tier). Some endpoints have free access.
    Docs: https://cryptoquant.com/developer/docs
    """

    name = "cryptoquant"
    priority = 2

    BASE_URL = "https://api.cryptoquant.com/v1"

    _ASSET_MAP: dict[str, str] = {
        "BTC": "btc", "ETH": "eth",
    }

    def __init__(self, api_key: str, config: dict[str, Any] | None = None) -> None:
        self._api_key = api_key
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._cache = _TTLCache(self._config.get("cache_ttl_s", 600))

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=20.0,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.BASE_URL}/btc/market-data/current",
                timeout=10,
            )
            return resp.status_code in (200, 401, 403)
        except Exception:
            return False

    async def get_exchange_flows(self, symbol: str) -> ExchangeFlowData | None:
        """Get exchange reserve and flow data from CryptoQuant."""
        asset = self._ASSET_MAP.get(symbol.upper())
        if not asset:
            return None

        cache_key = f"cq_flow:{asset}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            # Fetch exchange reserve
            reserve_resp = await client.get(
                f"{self.BASE_URL}/{asset}/exchange-reserve/current",
                timeout=10,
            )

            # Fetch exchange inflow/outflow
            flow_resp = await client.get(
                f"{self.BASE_URL}/{asset}/exchange-flows/current",
                timeout=10,
            )

            # Fetch funding rate
            funding_resp = await client.get(
                f"{self.BASE_URL}/{asset}/funding-rate/current",
                timeout=10,
            )

            reserves = 0.0
            inflow = 0.0
            outflow = 0.0
            funding = 0.0

            if reserve_resp.status_code == 200:
                rd = reserve_resp.json().get("result", {})
                reserves = float(rd.get("reserve", 0))

            if flow_resp.status_code == 200:
                fd = flow_resp.json().get("result", {})
                inflow = float(fd.get("inflow", 0))
                outflow = float(fd.get("outflow", 0))

            if funding_resp.status_code == 200:
                frd = funding_resp.json().get("result", {})
                funding = float(frd.get("funding_rate", 0))

            result = ExchangeFlowData(
                symbol=symbol.upper(),
                inflow_24h=inflow,
                outflow_24h=outflow,
                net_flow_24h=inflow - outflow,
                exchange_reserves=reserves,
                funding_rate=funding,
                source="cryptoquant",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("CryptoQuant exchange flows failed for %s: %s", symbol, exc)
            return None

    async def get_fundamentals(self, symbol: str) -> OnChainFundamentals | None:
        """CryptoQuant doesn't provide SOPR/MVRV — return None."""
        return None

    async def get_smart_money(self, symbol: str) -> SmartMoneyFlow | None:
        """CryptoQuant doesn't do smart money labels — return None."""
        return None

    async def get_miner_flows(self, symbol: str) -> MinerFlowData | None:
        """Get miner flow data from CryptoQuant (BTC/ETH)."""
        asset = self._ASSET_MAP.get(symbol.upper())
        if not asset:
            return None

        cache_key = f"cq_miner:{asset}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                f"{self.BASE_URL}/{asset}/miner-flows/current",
                timeout=10,
            )

            if resp.status_code != 200:
                return None

            data = resp.json().get("result", {})

            result = MinerFlowData(
                symbol=symbol.upper(),
                miner_outflow_24h=float(data.get("miner_outflow", 0)),
                miner_inflow_24h=float(data.get("miner_inflow", 0)),
                miner_net_flow=float(data.get("miner_net_flow", 0)),
                miner_balance=float(data.get("miner_balance", 0)),
                miner_revenue_usd=float(data.get("miner_revenue", 0)),
                source="cryptoquant",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("CryptoQuant miner flows failed for %s: %s", symbol, exc)
            return None

    async def get_funding_rates(self, symbol: str) -> dict[str, Any]:
        """Get funding rate data across exchanges."""
        asset = self._ASSET_MAP.get(symbol.upper())
        if not asset:
            return {}

        cache_key = f"cq_funding:{asset}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                f"{self.BASE_URL}/{asset}/funding-rate/current",
                timeout=10,
            )

            if resp.status_code != 200:
                return {}

            data = resp.json().get("result", {})
            self._cache.set(cache_key, data)
            return data

        except Exception as exc:
            logger.warning("CryptoQuant funding rates failed: %s", exc)
            return {}


# ═══════════════════════════════════════════════════════════════════════
# DEFILLAMA CLIENT (FREE — always available)
# ═══════════════════════════════════════════════════════════════════════


class DeFiLlamaClient:
    """DeFiLlama API client — TVL, yields, protocol revenue.

    FREE, no API key required. The most comprehensive DeFi data source.

    Provides:
    - Protocol TVL tracking across all chains
    - Yield pool data (APY, TVL, IL risk)
    - Protocol revenue and fees
    - Stablecoin metrics
    - Bridge TVL

    Docs: https://defillama.com/docs/api
    """

    name = "defillama"
    priority = 10  # Lowest priority — free fallback, but also primary for DeFi data

    BASE_URL = "https://api.llama.fi"
    YIELDS_URL = "https://yields.llama.fi"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._cache = _TTLCache(self._config.get("cache_ttl_s", 300))

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def is_available(self) -> bool:
        """DeFiLlama is always available (free, no key)."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.BASE_URL}/protocols", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    async def get_exchange_flows(self, symbol: str) -> ExchangeFlowData | None:
        """DeFiLlama doesn't do exchange flows — return None."""
        return None

    async def get_fundamentals(self, symbol: str) -> OnChainFundamentals | None:
        """DeFiLlama doesn't provide SOPR/MVRV — return None."""
        return None

    async def get_smart_money(self, symbol: str) -> SmartMoneyFlow | None:
        """DeFiLlama doesn't do smart money — return None."""
        return None

    # ── TVL Tracking ─────────────────────────────────────────────────

    async def get_protocol_tvl(self, protocol: str) -> ProtocolTVL | None:
        """Get TVL data for a specific protocol.

        Args:
            protocol: Protocol slug (e.g. "aave", "lido", "uniswap").

        Returns:
            ProtocolTVL with current TVL and changes.
        """
        cache_key = f"llama_tvl:{protocol}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                f"{self.BASE_URL}/protocol/{protocol}",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            current_tvl = float(data.get("tvl", 0) or 0)
            chain_tvls = data.get("currentChainTvls", {})

            # Get chain breakdown
            chain_tvl = 0.0
            for chain_name, tvl_val in chain_tvls.items():
                if not chain_name.endswith("-borrowed") and not chain_name.endswith("-staking"):
                    try:
                        chain_tvl = max(chain_tvl, float(tvl_val))
                    except (TypeError, ValueError):
                        pass

            # Calculate changes from historical
            try:
                tvl_change_1d = float(data.get("change_1d", 0) or 0)
            except (TypeError, ValueError):
                tvl_change_1d = 0.0
            try:
                tvl_change_7d = float(data.get("change_7d", 0) or 0)
            except (TypeError, ValueError):
                tvl_change_7d = 0.0
            try:
                tvl_change_30d = float(data.get("change_1m", 0) or 0)
            except (TypeError, ValueError):
                tvl_change_30d = 0.0

            # MCap/TVL ratio
            try:
                mcap = float(data.get("mcap", 0) or 0)
            except (TypeError, ValueError):
                mcap = 0.0
            mcap_tvl = mcap / current_tvl if current_tvl > 0 else 0.0

            result = ProtocolTVL(
                protocol=protocol,
                chain="multi",
                tvl_usd=current_tvl,
                tvl_change_1d=round(tvl_change_1d, 2),
                tvl_change_7d=round(tvl_change_7d, 2),
                tvl_change_30d=round(tvl_change_30d, 2),
                mcap_tvl_ratio=round(mcap_tvl, 4),
                source="defillama",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("DeFiLlama protocol TVL failed for %s: %s", protocol, exc)
            return None

    async def get_all_protocols_tvl(self, chain: str | None = None) -> list[ProtocolTVL]:
        """Get TVL for all protocols, optionally filtered by chain.

        Args:
            chain: Optional chain filter (e.g. "Ethereum", "Arbitrum").

        Returns:
            List of ProtocolTVL sorted by TVL descending.
        """
        cache_key = f"llama_all_tvl:{chain or 'all'}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(f"{self.BASE_URL}/protocols", timeout=20)
            resp.raise_for_status()
            protocols = resp.json()

            results: list[ProtocolTVL] = []
            for p in protocols:
                if chain and chain.lower() not in str(p.get("chains", [])).lower():
                    continue

                try:
                    tvl = float(p.get("tvl", 0) or 0)
                except (TypeError, ValueError):
                    tvl = 0.0
                if tvl < 100_000:  # Skip tiny protocols
                    continue

                try:
                    change_1d = float(p.get("change_1d", 0) or 0)
                except (TypeError, ValueError):
                    change_1d = 0.0
                try:
                    change_7d = float(p.get("change_7d", 0) or 0)
                except (TypeError, ValueError):
                    change_7d = 0.0
                try:
                    change_30d = float(p.get("change_1m", 0) or 0)
                except (TypeError, ValueError):
                    change_30d = 0.0
                try:
                    mcap = float(p.get("mcap", 0) or 0)
                except (TypeError, ValueError):
                    mcap = 0.0

                results.append(ProtocolTVL(
                    protocol=p.get("slug", p.get("name", "unknown")),
                    chain=", ".join(p.get("chains", [])[:3]),
                    tvl_usd=tvl,
                    tvl_change_1d=round(change_1d, 2),
                    tvl_change_7d=round(change_7d, 2),
                    tvl_change_30d=round(change_30d, 2),
                    mcap_tvl_ratio=round(mcap / tvl if tvl > 0 else 0, 4),
                    source="defillama",
                    timestamp=datetime.now(UTC),
                ))

            results.sort(key=lambda x: x.tvl_usd, reverse=True)
            self._cache.set(cache_key, results)
            return results

        except Exception as exc:
            logger.warning("DeFiLlama all protocols failed: %s", exc)
            return []

    # ── Yield Pool Data ──────────────────────────────────────────────

    async def get_yield_pools(
        self,
        chain: str | None = None,
        min_tvl: float = 100_000,
        min_apy: float = 0.0,
        max_apy: float = 500.0,
        stable_only: bool = False,
    ) -> list[YieldPool]:
        """Get yield pool opportunities from DeFiLlama.

        Args:
            chain: Filter by chain (e.g. "Ethereum", "Arbitrum").
            min_tvl: Minimum TVL in USD.
            min_apy: Minimum APY (%).
            max_apy: Maximum APY (%) — filters out suspiciously high yields.
            stable_only: Only return stablecoin pools.

        Returns:
            List of YieldPool sorted by APY descending.
        """
        cache_key = f"llama_yields:{chain}:{min_tvl}:{stable_only}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(f"{self.YIELDS_URL}/pools", timeout=20)
            resp.raise_for_status()
            data = resp.json()

            pools_data = data.get("data", [])
            results: list[YieldPool] = []

            for pool in pools_data:
                tvl = float(pool.get("tvlUsd", 0) or 0)
                if tvl < min_tvl:
                    continue

                apy = float(pool.get("apy", 0) or 0)
                if apy < min_apy or apy > max_apy:
                    continue

                pool_chain = pool.get("chain", "")
                if chain and chain.lower() != pool_chain.lower():
                    continue

                symbol = pool.get("symbol", "")
                stable = pool.get("stablecoin", False)
                if stable_only and not stable:
                    continue

                il_risk = "none"
                exposure = pool.get("exposure", "single")
                if exposure == "multi" and not stable:
                    il_risk = "medium"
                if exposure == "multi" and apy > 50:
                    il_risk = "high"
                elif exposure == "multi":
                    il_risk = "low"

                results.append(YieldPool(
                    protocol=pool.get("project", "unknown"),
                    chain=pool_chain,
                    pool_id=pool.get("pool", ""),
                    symbol=symbol,
                    tvl_usd=tvl,
                    apy=round(apy, 2),
                    apy_base=round(float(pool.get("apyBase", 0) or 0), 2),
                    apy_reward=round(float(pool.get("apyReward", 0) or 0), 2),
                    il_risk=il_risk,
                    stable_pool=stable,
                    exposure=exposure,
                    pool_meta=pool.get("poolMeta", ""),
                    source="defillama",
                    timestamp=datetime.now(UTC),
                ))

            results.sort(key=lambda x: x.apy, reverse=True)
            self._cache.set(cache_key, results)
            return results

        except Exception as exc:
            logger.warning("DeFiLlama yield pools failed: %s", exc)
            return []

    async def get_pool_history(self, pool_id: str) -> list[dict[str, Any]]:
        """Get historical APY and TVL for a specific pool.

        Returns list of dicts with timestamp, apy, tvl.
        """
        cache_key = f"llama_pool_hist:{pool_id}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                f"{self.YIELDS_URL}/chart/{pool_id}",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])

            history = [
                {
                    "timestamp": d.get("timestamp"),
                    "apy": float(d.get("apy", 0)),
                    "tvl": float(d.get("tvlUsd", 0)),
                }
                for d in data
            ]

            self._cache.set(cache_key, history)
            return history

        except Exception as exc:
            logger.warning("DeFiLlama pool history failed for %s: %s", pool_id, exc)
            return []

    # ── Protocol Revenue ─────────────────────────────────────────────

    async def get_protocol_revenue(self, protocol: str) -> dict[str, Any]:
        """Get protocol revenue and fees data.

        Returns dict with dailyRevenue, dailyFees, totalRevenue, etc.
        """
        cache_key = f"llama_rev:{protocol}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                f"{self.BASE_URL}/summary/fees/{protocol}",
                timeout=15,
            )

            if resp.status_code != 200:
                # Try revenue endpoint
                resp = await client.get(
                    f"{self.BASE_URL}/summary/revenue/{protocol}",
                    timeout=15,
                )

            if resp.status_code != 200:
                return {}

            data = resp.json()

            result = {
                "protocol": protocol,
                "total24h": float(data.get("total24h", 0) or 0),
                "total48hto24h": float(data.get("total48hto24h", 0) or 0),
                "total7d": float(data.get("total7d", 0) or 0),
                "total30d": float(data.get("total30d", 0) or 0),
                "totalAllTime": float(data.get("totalAllTime", 0) or 0),
                "change_1d": float(data.get("change_1d", 0) or 0),
                "change_7d": float(data.get("change_7d", 0) or 0),
                "change_1m": float(data.get("change_1m", 0) or 0),
            }

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("DeFiLlama protocol revenue failed for %s: %s", protocol, exc)
            return {}

    # ── Stablecoin Metrics ───────────────────────────────────────────

    async def get_stablecoin_metrics(self) -> list[dict[str, Any]]:
        """Get stablecoin supply and chain distribution data."""
        cache_key = "llama_stables"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                "https://stablecoins.llama.fi/stablecoins?includePrices=true",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("peggedAssets", [])

            results = []
            for s in data[:20]:  # Top 20 stablecoins
                chains = s.get("chainCirculating", {})
                total_circ = sum(
                    float(c.get("current", {}).get("peggedUSD", 0))
                    for c in chains.values()
                )

                results.append({
                    "name": s.get("name", ""),
                    "symbol": s.get("symbol", ""),
                    "circulating_usd": total_circ,
                    "price": float(s.get("price", 1.0) or 1.0),
                    "chains": list(chains.keys())[:5],
                })

            self._cache.set(cache_key, results)
            return results

        except Exception as exc:
            logger.warning("DeFiLlama stablecoin metrics failed: %s", exc)
            return []


# ═══════════════════════════════════════════════════════════════════════
# COINGECKO FALLBACK (FREE)
# ═══════════════════════════════════════════════════════════════════════


class CoinGeckoFallback:
    """CoinGecko free API as ultimate fallback for basic market data.

    Provides estimated exchange flows from volume patterns.
    No API key required (rate limited).
    """

    name = "coingecko"
    priority = 99  # Last resort

    BASE_URL = "https://api.coingecko.com/api/v3"

    _COIN_IDS: dict[str, str] = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
        "DOGE": "dogecoin", "DOT": "polkadot", "AVAX": "avalanche-2",
        "MATIC": "matic-network", "LINK": "chainlink", "UNI": "uniswap",
        "ATOM": "cosmos", "NEAR": "near", "ARB": "arbitrum",
        "OP": "optimism", "APT": "aptos", "SUI": "sui",
        "FIL": "filecoin", "LTC": "litecoin",
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._cache = _TTLCache(self._config.get("cache_ttl_s", 120))

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def is_available(self) -> bool:
        """CoinGecko is always available (free, rate-limited)."""
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.BASE_URL}/ping", timeout=10
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def get_exchange_flows(self, symbol: str) -> ExchangeFlowData | None:
        """Estimate exchange flows from CoinGecko volume data.

        Uses volume-to-flow heuristics based on price action patterns.
        """
        coin_id = self._COIN_IDS.get(symbol.upper())
        if not coin_id:
            return None

        cache_key = f"cg_flow:{symbol}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        client = await self._get_client()

        try:
            resp = await client.get(
                f"{self.BASE_URL}/coins/{coin_id}",
                params={"localization": "false", "tickers": "false"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            market = data.get("market_data", {})
            total_volume = float(market.get("total_volume", {}).get("usd", 0))
            price_change = float(market.get("price_change_percentage_24h", 0) or 0)

            # Heuristic: ~30% of volume touches exchanges
            base_inflow = total_volume * 0.30
            base_outflow = total_volume * 0.28

            if price_change > 5:
                inflow = base_inflow * 0.8
                outflow = base_outflow * 1.3
            elif price_change > 0:
                inflow = base_inflow * 0.9
                outflow = base_outflow * 1.1
            elif price_change > -5:
                inflow = base_inflow * 1.1
                outflow = base_outflow * 0.9
            else:
                inflow = base_inflow * 1.3
                outflow = base_outflow * 0.8

            net_flow = inflow - outflow

            result = ExchangeFlowData(
                symbol=symbol.upper(),
                inflow_24h=round(inflow, 2),
                outflow_24h=round(outflow, 2),
                net_flow_24h=round(net_flow, 2),
                source="coingecko_estimate",
                timestamp=datetime.now(UTC),
            )

            self._cache.set(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("CoinGecko fallback flow failed for %s: %s", symbol, exc)
            return None

    async def get_fundamentals(self, symbol: str) -> OnChainFundamentals | None:
        """CoinGecko doesn't provide on-chain fundamentals."""
        return None

    async def get_smart_money(self, symbol: str) -> SmartMoneyFlow | None:
        """CoinGecko doesn't do smart money tracking."""
        return None


# ═══════════════════════════════════════════════════════════════════════
# FALLBACK CHAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════


class FallbackChain:
    """Orchestrates multiple analytics providers with automatic fallback.

    Tries providers in priority order (lowest priority number first).
    Falls back to CoinGecko estimates when premium APIs are unavailable.

    Usage:
        chain = FallbackChain.from_config(config)
        flows = await chain.get_exchange_flows("BTC")
        fundamentals = await chain.get_fundamentals("BTC")
        smart_money = await chain.get_smart_money("ETH")
    """

    def __init__(self, providers: list[Any] | None = None) -> None:
        self._providers: list[Any] = providers or []
        self._providers.sort(key=lambda p: p.priority)
        self._available_cache: dict[str, bool] = {}

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> FallbackChain:
        """Build a FallbackChain from TSAR config.

        Expected config keys:
          - glassnode_api_key: str
          - nansen_api_key: str
          - cryptoquant_api_key: str
          - analytics_cache_ttl: int (seconds)
        """
        providers: list[Any] = []
        cache_ttl = config.get("analytics_cache_ttl", 600)
        provider_config = {"cache_ttl_s": cache_ttl}

        # Glassnode (priority 1)
        gn_key = config.get("glassnode_api_key", "")
        if gn_key:
            providers.append(GlassnodeClient(api_key=gn_key, config=provider_config))

        # Nansen (priority 2)
        nansen_key = config.get("nansen_api_key", "")
        if nansen_key:
            providers.append(NansenClient(api_key=nansen_key, config=provider_config))

        # CryptoQuant (priority 2)
        cq_key = config.get("cryptoquant_api_key", "")
        if cq_key:
            providers.append(CryptoQuantClient(api_key=cq_key, config=provider_config))

        # DeFiLlama (priority 10 — free, always added)
        providers.append(DeFiLlamaClient(config=provider_config))

        # CoinGecko fallback (priority 99 — always added)
        providers.append(CoinGeckoFallback(config=provider_config))

        return cls(providers=providers)

    async def close(self) -> None:
        """Close all provider clients."""
        for p in self._providers:
            try:
                await p.close()
            except Exception:
                pass

    # ── Exchange Flows ───────────────────────────────────────────────

    async def get_exchange_flows(self, symbol: str) -> ExchangeFlowData:
        """Get exchange flow data with automatic fallback.

        Tries: Glassnode → CryptoQuant → CoinGecko estimate.
        """
        for provider in self._providers:
            try:
                if not await self._check_available(provider):
                    continue
                result = await provider.get_exchange_flows(symbol)
                if result and (result.inflow_24h > 0 or result.outflow_24h > 0):
                    return result
            except Exception as exc:
                logger.debug("Provider %s failed for exchange flows: %s", provider.name, exc)

        # Ultimate empty fallback
        return ExchangeFlowData(
            symbol=symbol.upper(),
            source="none",
            timestamp=datetime.now(UTC),
        )

    # ── Fundamentals ─────────────────────────────────────────────────

    async def get_fundamentals(self, symbol: str) -> OnChainFundamentals:
        """Get on-chain fundamentals with automatic fallback.

        Tries: Glassnode → CoinGecko (limited).
        """
        for provider in self._providers:
            try:
                if not await self._check_available(provider):
                    continue
                result = await provider.get_fundamentals(symbol)
                if result and (result.sopr > 0 or result.mvrv > 0):
                    return result
            except Exception as exc:
                logger.debug("Provider %s failed for fundamentals: %s", provider.name, exc)

        return OnChainFundamentals(
            symbol=symbol.upper(),
            source="none",
            timestamp=datetime.now(UTC),
        )

    # ── Smart Money ──────────────────────────────────────────────────

    async def get_smart_money(self, symbol: str) -> SmartMoneyFlow:
        """Get smart money flow data with automatic fallback.

        Tries: Glassnode → Nansen → CoinGecko (limited).
        """
        for provider in self._providers:
            try:
                if not await self._check_available(provider):
                    continue
                result = await provider.get_smart_money(symbol)
                if result and result.source:
                    return result
            except Exception as exc:
                logger.debug("Provider %s failed for smart money: %s", provider.name, exc)

        return SmartMoneyFlow(
            symbol=symbol.upper(),
            source="none",
            timestamp=datetime.now(UTC),
        )

    # ── Miner Flows (BTC-specific) ──────────────────────────────────

    async def get_miner_flows(self, symbol: str = "BTC") -> MinerFlowData:
        """Get miner flow data with fallback.

        Tries: Glassnode → CryptoQuant.
        """
        for provider in self._providers:
            if not hasattr(provider, "get_miner_flows"):
                continue
            try:
                if not await self._check_available(provider):
                    continue
                result = await provider.get_miner_flows(symbol)
                if result and result.source:
                    return result
            except Exception as exc:
                logger.debug("Provider %s failed for miner flows: %s", provider.name, exc)

        return MinerFlowData(
            symbol=symbol.upper(),
            source="none",
            timestamp=datetime.now(UTC),
        )

    # ── DeFi-Specific (DeFiLlama) ───────────────────────────────────

    def get_defillama(self) -> DeFiLlamaClient | None:
        """Get the DeFiLlama client instance for DeFi-specific queries."""
        for p in self._providers:
            if isinstance(p, DeFiLlamaClient):
                return p
        return None

    # ── Internal ─────────────────────────────────────────────────────

    async def _check_available(self, provider: Any) -> bool:
        """Check provider availability with caching."""
        name = provider.name
        if name in self._available_cache:
            return self._available_cache[name]

        try:
            available = await provider.is_available()
            self._available_cache[name] = available
            return available
        except Exception:
            self._available_cache[name] = False
            return False

    def get_provider_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all configured providers."""
        status = {}
        for p in self._providers:
            status[p.name] = {
                "priority": p.priority,
                "cached_available": self._available_cache.get(p.name, "unknown"),
            }
        return status
