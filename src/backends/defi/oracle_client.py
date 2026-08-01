"""
TSAR — Oracle Integration Module.

Provides on-chain price verification via multiple oracle providers:

  - **Chainlink Price Feeds**: Read aggregator contracts via web3.py
  - **Pyth Network**: Real-time price feeds via Pyth HTTP/hermes API
  - **TWAP**: Time-Weighted Average Price computation from on-chain data
  - **Price Deviation Alerts**: Detect when CEX and DEX prices diverge

All public methods are async.  Synchronous wrappers are provided for tool-layer
compatibility.

Usage::

    from src.backends.defi.oracle_client import OracleClient

    oracle = OracleClient(rpc_url="https://eth-mainnet.g.alchemy.com/v2/...")
    price = await oracle.get_chainlink_price("ETH/USD")
    twap = await oracle.compute_twap("ETH/USD", window_seconds=3600)
    deviation = await oracle.check_price_deviation("ETH/USD", exchange_price=1995.0)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Chainlink Price Feed aggregator addresses (Ethereum mainnet)
CHAINLINK_FEEDS: dict[str, dict[str, Any]] = {
    "ETH/USD": {
        "address": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
        "decimals": 8,
    },
    "BTC/USD": {
        "address": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",
        "decimals": 8,
    },
    "USDC/USD": {
        "address": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",
        "decimals": 8,
    },
    "USDT/USD": {
        "address": "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D",
        "decimals": 8,
    },
    "SOL/USD": {
        "address": "0x4ffC43a60e009B551865A93d232E33Fce9f01507",
        "decimals": 8,
    },
    "LINK/USD": {
        "address": "0x2c1d072e956AFFC0D435Cb7AC38EF18d24d9127c",
        "decimals": 8,
    },
    "UNI/USD": {
        "address": "0x553303d460EE0afB37EdFf9bE42922D8FF63220e",
        "decimals": 8,
    },
    "AAVE/USD": {
        "address": "0x547a514d5e3769680Ce22B2361c10Ea13619e8a9",
        "decimals": 8,
    },
}

# Chainlink Aggregator V3 ABI — latestRoundData()
AGGREGATOR_ABI_LATEST = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Pyth Network Hermes API
PYTH_HERMES_URL = "https://hermes.pyth.network"
PYTH_PRICE_IDS: dict[str, str] = {
    "ETH/USD": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "BTC/USD": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "SOL/USD": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    "USDC/USD": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e1c5b0",
    "USDT/USD": "0x2b89b9dc8fdf9f34709a5b106b472f0f39bb6ca9ce04b0fd7f2e971688e2e53b",
    "LINK/USD": "0x8ac0c70fff57e9aefdf5edf44b51d62c2d433653cbb2cf5cc06bb115af04d221",
    "UNI/USD": "0x78d185a741d07edb3d5ef4a7caf84b74eb595e96dba4c7f0f4791eb4884b9cef",
    "AAVE/USD": "0x2b9ab1e972a281585084148ba1389800799bd4be63b957507db1349314e47445",
}


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


class OracleProvider(StrEnum):
    """Supported oracle providers."""
    CHAINLINK = "chainlink"
    PYTH = "pyth"
    ONCHAIN_TWAP = "onchain_twap"


class DeviationSeverity(StrEnum):
    """Price deviation severity levels."""
    NORMAL = "normal"        # < 1%
    WARNING = "warning"      # 1-3%
    ALERT = "alert"          # 3-5%
    CRITICAL = "critical"    # > 5%


@dataclass(frozen=True)
class OraclePrice:
    """A price fetched from an oracle.

    Attributes:
        pair: Price pair (e.g. "ETH/USD").
        price: Current price.
        decimals: Oracle decimals for the price.
        raw_answer: Raw int256 answer from the contract.
        timestamp: When the price was last updated (epoch seconds).
        provider: Which oracle provided this price.
        stale: Whether the price data is considered stale.
        round_id: Chainlink round ID (0 for non-Chainlink).
    """
    pair: str
    price: float
    decimals: int
    raw_answer: int
    timestamp: float
    provider: OracleProvider
    stale: bool = False
    round_id: int = 0


@dataclass(frozen=True)
class TWAPResult:
    """Time-Weighted Average Price computation result.

    Attributes:
        pair: Price pair.
        twap: Computed TWAP value.
        window_seconds: Observation window used.
        samples: Number of price samples used.
        min_price: Minimum price in window.
        max_price: Maximum price in window.
        std_dev: Standard deviation of prices.
        timestamp: When the TWAP was computed.
    """
    pair: str
    twap: float
    window_seconds: int
    samples: int
    min_price: float
    max_price: float
    std_dev: float
    timestamp: float


@dataclass(frozen=True)
class PriceDeviation:
    """Result of a CEX vs DEX price deviation check.

    Attributes:
        pair: Price pair.
        oracle_price: Price from the oracle.
        exchange_price: Price from the CEX.
        deviation_pct: Percentage deviation (oracle vs exchange).
        severity: How severe the deviation is.
        direction: Whether oracle is "above" or "below" exchange.
        timestamp: When the check was performed.
    """
    pair: str
    oracle_price: float
    exchange_price: float
    deviation_pct: float
    severity: DeviationSeverity
    direction: str
    timestamp: float


# ═══════════════════════════════════════════════════════════════════════
# ORACLE CLIENT
# ═══════════════════════════════════════════════════════════════════════


class OracleClient:
    """Multi-provider oracle client for on-chain price verification.

    Supports Chainlink (web3.py), Pyth Network (Hermes API), and
    on-chain TWAP computation.

    Args:
        rpc_url: Ethereum JSON-RPC endpoint.
        pyth_hermes_url: Pyth Hermes API URL.
        staleness_threshold: Seconds before a price is considered stale (default: 3600).
        http_client: Optional pre-configured httpx.AsyncClient.
    """

    def __init__(
        self,
        rpc_url: str = "",
        pyth_hermes_url: str = PYTH_HERMES_URL,
        staleness_threshold: int = 3600,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.rpc_url = rpc_url.rstrip("/")
        self.pyth_hermes_url = pyth_hermes_url.rstrip("/")
        self.staleness_threshold = staleness_threshold
        self._client = http_client
        self._owns_client = http_client is None

        # TWAP history buffer: pair → [(timestamp, price), ...]
        self._price_history: dict[str, list[tuple[float, float]]] = {}
        self._max_history = 1000  # keep last N samples per pair

    # ── lifecycle ─────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── JSON-RPC helper ───────────────────────────────────────────────

    async def _eth_call(self, method: str, params: list[Any] | None = None) -> Any:
        client = await self._get_client()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
        resp = await client.post(self.rpc_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data.get("result")

    async def _eth_call_contract(
        self,
        to: str,
        data: str,
    ) -> str:
        """Execute an eth_call to a contract."""
        result = await self._eth_call(
            "eth_call",
            [{"to": to, "data": data}, "latest"],
        )
        return result or "0x"

    @staticmethod
    def _encode_function_call(function_name: str) -> str:
        """Encode a simple no-arg function call selector.

        Uses the first 4 bytes of keccak256 of the function signature.
        """
        import hashlib
        sig = f"{function_name}()"
        selector = hashlib.sha3_256(sig.encode()).digest()[:4].hex()
        return f"0x{selector}"

    @staticmethod
    def _decode_int256(hex_data: str) -> int:
        """Decode a hex-encoded int256 return value."""
        if not hex_data or hex_data == "0x":
            return 0
        clean = hex_data.replace("0x", "")
        value = int(clean, 16)
        # Handle negative values (two's complement for 256-bit)
        if value >= 2**255:
            value -= 2**256
        return value

    @staticmethod
    def _decode_uint8(hex_data: str) -> int:
        """Decode a uint8 return value."""
        if not hex_data or hex_data == "0x":
            return 0
        return int(hex_data.replace("0x", ""), 16)

    # ── Chainlink Price Feeds ─────────────────────────────────────────

    async def get_chainlink_price(self, pair: str) -> OraclePrice:
        """Fetch the latest price from a Chainlink aggregator contract.

        Args:
            pair: Price pair (e.g. "ETH/USD"). Must be in CHAINLINK_FEEDS.

        Returns:
            OraclePrice with the latest round data.

        Raises:
            ValueError: If the pair is not supported.
            RuntimeError: If the RPC call fails.
        """
        pair_upper = pair.upper()
        feed = CHAINLINK_FEEDS.get(pair_upper)
        if feed is None:
            raise ValueError(
                f"Chainlink feed not found for {pair}. "
                f"Available: {', '.join(CHAINLINK_FEEDS.keys())}"
            )

        address = feed["address"]
        expected_decimals = feed["decimals"]

        # Call latestRoundData()
        selector = self._encode_function_call("latestRoundData")
        result = await self._eth_call_contract(address, selector)

        # Decode: roundId (uint80), answer (int256), startedAt (uint256),
        #         updatedAt (uint256), answeredInRound (uint80)
        # Each is 32 bytes = 64 hex chars
        clean = result.replace("0x", "").zfill(320)  # 5 * 64 = 320

        round_id = int(clean[0:64], 16)
        answer = self._decode_int256("0x" + clean[64:128])
        started_at = int(clean[128:192], 16)
        updated_at = int(clean[192:256], 16)
        answered_in_round = int(clean[256:320], 16)

        price = answer / (10 ** expected_decimals)
        now = time.time()
        stale = (now - updated_at) > self.staleness_threshold

        # Record for TWAP
        self._record_price(pair_upper, now, price)

        oracle_price = OraclePrice(
            pair=pair_upper,
            price=round(price, 8),
            decimals=expected_decimals,
            raw_answer=answer,
            timestamp=updated_at,
            provider=OracleProvider.CHAINLINK,
            stale=stale,
            round_id=round_id,
        )

        logger.info(
            "chainlink_price",
            pair=pair_upper,
            price=price,
            updated_at=updated_at,
            stale=stale,
        )
        return oracle_price

    # ── Pyth Network ──────────────────────────────────────────────────

    async def get_pyth_price(self, pair: str) -> OraclePrice:
        """Fetch a real-time price from Pyth Network via Hermes API.

        Args:
            pair: Price pair (e.g. "ETH/USD"). Must be in PYTH_PRICE_IDS.

        Returns:
            OraclePrice with the latest Pyth price.

        Raises:
            ValueError: If the pair is not supported.
        """
        pair_upper = pair.upper()
        price_id = PYTH_PRICE_IDS.get(pair_upper)
        if price_id is None:
            raise ValueError(
                f"Pyth price ID not found for {pair}. "
                f"Available: {', '.join(PYTH_PRICE_IDS.keys())}"
            )

        client = await self._get_client()
        url = f"{self.pyth_hermes_url}/api/latest_price_feeds"
        resp = await client.get(url, params={"ids[]": price_id, "verbose": "true"})
        resp.raise_for_status()
        data = resp.json()

        feeds = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(feeds, list) and len(feeds) > 0:
            feed = feeds[0]
        elif isinstance(feeds, dict):
            feed = feeds
        else:
            raise RuntimeError(f"Unexpected Pyth response format: {data}")

        # Parse price and confidence
        price_obj = feed.get("price", {})
        price_raw = int(price_obj.get("price", 0))
        expo = int(price_obj.get("expo", 0))
        publish_time = int(price_obj.get("publishTime", time.time()))

        price = price_raw * (10 ** expo)
        now = time.time()
        stale = (now - publish_time) > self.staleness_threshold

        # Record for TWAP
        self._record_price(pair_upper, now, price)

        oracle_price = OraclePrice(
            pair=pair_upper,
            price=round(price, 8),
            decimals=abs(expo),
            raw_answer=price_raw,
            timestamp=publish_time,
            provider=OracleProvider.PYTH,
            stale=stale,
        )

        logger.info(
            "pyth_price",
            pair=pair_upper,
            price=price,
            publish_time=publish_time,
            stale=stale,
        )
        return oracle_price

    # ── Best price (aggregated) ───────────────────────────────────────

    async def get_best_price(self, pair: str) -> OraclePrice:
        """Fetch the best available price from multiple oracle providers.

        Tries Chainlink first, falls back to Pyth. Returns whichever is
        fresher (or non-stale).
        """
        prices: list[OraclePrice] = []

        try:
            cl = await self.get_chainlink_price(pair)
            prices.append(cl)
        except Exception as exc:
            logger.debug("chainlink_failed", pair=pair, error=str(exc))

        try:
            pyth = await self.get_pyth_price(pair)
            prices.append(pyth)
        except Exception as exc:
            logger.debug("pyth_failed", pair=pair, error=str(exc))

        if not prices:
            raise RuntimeError(f"No oracle price available for {pair}")

        # Prefer non-stale, then newest
        non_stale = [p for p in prices if not p.stale]
        candidates = non_stale if non_stale else prices
        best = max(candidates, key=lambda p: p.timestamp)
        return best

    # ── TWAP computation ──────────────────────────────────────────────

    def _record_price(self, pair: str, timestamp: float, price: float) -> None:
        """Record a price sample for TWAP computation."""
        history = self._price_history.setdefault(pair, [])
        history.append((timestamp, price))
        # Trim to max size
        if len(history) > self._max_history:
            self._price_history[pair] = history[-self._max_history:]

    async def compute_twap(
        self,
        pair: str,
        window_seconds: int = 3600,
    ) -> TWAPResult:
        """Compute a Time-Weighted Average Price from collected samples.

        The TWAP is computed as:
            TWAP = Σ(price_i × Δt_i) / Σ(Δt_i)

        where Δt_i is the time between consecutive samples.

        Args:
            pair: Price pair.
            window_seconds: How far back to look for samples.

        Returns:
            TWAPResult with the computed TWAP and statistics.

        Raises:
            ValueError: If insufficient samples are available.
        """
        pair_upper = pair.upper()
        history = self._price_history.get(pair_upper, [])

        if len(history) < 2:
            # Try to fetch a fresh price to seed the history
            try:
                await self.get_best_price(pair_upper)
                history = self._price_history.get(pair_upper, [])
            except Exception:
                pass

        if len(history) < 2:
            raise ValueError(
                f"Insufficient price samples for {pair} TWAP. "
                f"Need at least 2, got {len(history)}. "
                f"Call get_chainlink_price/get_pyth_price multiple times first."
            )

        now = time.time()
        cutoff = now - window_seconds

        # Filter to window
        window = [(ts, p) for ts, p in history if ts >= cutoff]
        if len(window) < 2:
            window = history[-2:]  # use whatever we have

        # Compute time-weighted average
        total_weighted = 0.0
        total_time = 0.0
        prices = [p for _, p in window]

        for i in range(1, len(window)):
            dt = window[i][0] - window[i - 1][0]
            # Use the price at the start of each interval
            total_weighted += window[i - 1][1] * dt
            total_time += dt

        if total_time == 0:
            twap = prices[-1]
        else:
            twap = total_weighted / total_time

        import math
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std_dev = math.sqrt(variance)

        result = TWAPResult(
            pair=pair_upper,
            twap=round(twap, 8),
            window_seconds=window_seconds,
            samples=len(window),
            min_price=round(min(prices), 8),
            max_price=round(max(prices), 8),
            std_dev=round(std_dev, 8),
            timestamp=now,
        )

        logger.info(
            "twap_computed",
            pair=pair_upper,
            twap=twap,
            samples=len(window),
            window=window_seconds,
        )
        return result

    # ── Price deviation alerts ────────────────────────────────────────

    async def check_price_deviation(
        self,
        pair: str,
        exchange_price: float,
        warning_threshold_pct: float = 1.0,
        alert_threshold_pct: float = 3.0,
        critical_threshold_pct: float = 5.0,
    ) -> PriceDeviation:
        """Compare oracle price against an exchange price.

        Detects significant divergence that may indicate:
        - Oracle manipulation
        - Exchange price lag
        - Arbitrage opportunity
        - Stale oracle data

        Args:
            pair: Price pair.
            exchange_price: Price from the CEX/exchange.
            warning_threshold_pct: % deviation for warning level.
            alert_threshold_pct: % deviation for alert level.
            critical_threshold_pct: % deviation for critical level.

        Returns:
            PriceDeviation with the comparison result.
        """
        oracle = await self.get_best_price(pair)
        oracle_price = oracle.price

        if exchange_price == 0:
            deviation_pct = 0.0
        else:
            deviation_pct = abs(oracle_price - exchange_price) / exchange_price * 100

        if deviation_pct >= critical_threshold_pct:
            severity = DeviationSeverity.CRITICAL
        elif deviation_pct >= alert_threshold_pct:
            severity = DeviationSeverity.ALERT
        elif deviation_pct >= warning_threshold_pct:
            severity = DeviationSeverity.WARNING
        else:
            severity = DeviationSeverity.NORMAL

        direction = "above" if oracle_price > exchange_price else "below"

        result = PriceDeviation(
            pair=pair.upper(),
            oracle_price=oracle_price,
            exchange_price=exchange_price,
            deviation_pct=round(deviation_pct, 4),
            severity=severity,
            direction=direction,
            timestamp=time.time(),
        )

        if severity != DeviationSeverity.NORMAL:
            logger.warning(
                "price_deviation_detected",
                pair=pair,
                oracle=oracle_price,
                exchange=exchange_price,
                deviation_pct=deviation_pct,
                severity=severity,
                provider=oracle.provider,
            )

        return result

    # ── Batch price fetch ─────────────────────────────────────────────

    async def get_multiple_prices(
        self,
        pairs: list[str],
        provider: OracleProvider | None = None,
    ) -> dict[str, OraclePrice]:
        """Fetch prices for multiple pairs concurrently.

        Args:
            pairs: List of price pairs.
            provider: Preferred provider (None = best available).

        Returns:
            Dict mapping pair → OraclePrice (skips failures).
        """
        async def _fetch_one(p: str) -> tuple[str, OraclePrice | None]:
            try:
                if provider == OracleProvider.CHAINLINK:
                    price = await self.get_chainlink_price(p)
                elif provider == OracleProvider.PYTH:
                    price = await self.get_pyth_price(p)
                else:
                    price = await self.get_best_price(p)
                return p, price
            except Exception as exc:
                logger.warning("batch_price_failed", pair=p, error=str(exc))
                return p, None

        results = await asyncio.gather(*[_fetch_one(p) for p in pairs])
        return {p: pr for p, pr in results if pr is not None}

    # ── Supported feeds ───────────────────────────────────────────────

    @staticmethod
    def supported_chainlink_pairs() -> list[str]:
        """List all supported Chainlink price feed pairs."""
        return list(CHAINLINK_FEEDS.keys())

    @staticmethod
    def supported_pyth_pairs() -> list[str]:
        """List all supported Pyth price feed pairs."""
        return list(PYTH_PRICE_IDS.keys())

    @staticmethod
    def supported_pairs() -> list[str]:
        """List all supported price pairs (union of all providers)."""
        return sorted(set(CHAINLINK_FEEDS.keys()) | set(PYTH_PRICE_IDS.keys()))
