"""
Python fallback implementations for DeFi Rust crates.

These classes provide the same interface as the Rust-backed PyO3 classes,
but execute in pure Python. Used when `trading_rs` is not built or
the DeFi modules are not yet compiled.

Architecture:
  Python (this file) — identical API to Rust PyO3 bindings
    ↓ optional
  trading_rs (Rust via PyO3) — preferred when available
    ↓
  Rust crates (mev-scanner, gas-optimizer, dex-aggregator, price-feed)
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

import os

# TSAR_RUST_BUILD=0 forces pure-Python fallback
_force_python = os.environ.get("TSAR_RUST_BUILD", "1").strip() in ("0", "false", "no")

if _force_python:
    RUST_DEFI_AVAILABLE = False
    trading_rs = None
else:
    # Try to import the Rust extension module
    try:
        import trading_rs

        RUST_DEFI_AVAILABLE = hasattr(trading_rs, "MEVScanner")
    except ImportError:
        RUST_DEFI_AVAILABLE = False
        trading_rs = None


# ═══════════════════════════════════════════════════════════════════════
# MEV SCANNER (Python fallback)
# ═══════════════════════════════════════════════════════════════════════


class MEVScanner:
    """MEV scanner with Rust acceleration and Python fallback.

    Drop-in replacement for trading_rs.MEVScanner.
    Falls back to Python if Rust is not available.
    """

    def __init__(
        self,
        ws_rpc_url: str = "",
        http_rpc_url: str = "",
        max_pending: int = 10000,
    ) -> None:
        self._ws_rpc_url = ws_rpc_url
        self._http_rpc_url = http_rpc_url
        self._max_pending = max_pending
        self._running = False
        self._pending: dict[str, dict] = {}
        self._patterns: list[dict] = []

        # Use Rust if available
        if RUST_DEFI_AVAILABLE:
            self._rust = trading_rs.MEVScanner(ws_rpc_url, http_rpc_url, max_pending)
        else:
            self._rust = None
            logger.info("MEVScanner: using Python fallback")

    def start(self) -> int:
        """Start the mempool scanner. Returns number of monitored routers."""
        if self._rust:
            return self._rust.start()
        self._running = True
        return 5  # Number of known routers

    def stop(self) -> None:
        """Stop the mempool scanner."""
        if self._rust:
            return self._rust.stop()
        self._running = False

    def pending_count(self) -> int:
        """Get number of tracked pending swaps."""
        if self._rust:
            return self._rust.pending_count()
        return len(self._pending)

    def check_sandwich(self, tx_hash: str) -> list[dict]:
        """Check for sandwich patterns involving a transaction."""
        if self._rust:
            return self._rust.check_sandwich(tx_hash)
        return [p for p in self._patterns if p.get("victim_tx") == tx_hash]

    def detected_sandwiches(self) -> list[dict]:
        """Get all detected sandwich patterns."""
        if self._rust:
            return self._rust.detected_sandwiches()
        return self._patterns

    def assess_risk(self, pair: str, amount: float) -> dict:
        """Assess MEV risk for a proposed swap."""
        if self._rust:
            return self._rust.assess_risk(pair, amount)

        # Python fallback: simplified risk scoring
        base_risk = 0.7 if amount > 100 else (0.4 if amount > 10 else 0.1)
        sandwich_risk = 0.3 if self._patterns else 0.0
        risk_score = min(base_risk + sandwich_risk, 1.0)

        risk_level = (
            "critical"
            if risk_score >= 0.8
            else "high"
            if risk_score >= 0.5
            else "medium"
            if risk_score >= 0.2
            else "low"
        )

        return {
            "pair": pair,
            "amount": amount,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "sandwich_detected": bool(self._patterns),
            "pending_arbitrageurs": [],
            "estimated_mev_loss_usd": amount * risk_score * 0.01,
            "gas_priority_gwei": 2.0,
        }

    def __repr__(self) -> str:
        return f"MEVScanner(pending={self.pending_count()}, sandwiches={len(self._patterns)})"


# ═══════════════════════════════════════════════════════════════════════
# GAS OPTIMIZER (Python fallback)
# ═══════════════════════════════════════════════════════════════════════


class GasOptimizer:
    """Gas optimizer with Rust acceleration and Python fallback.

    Drop-in replacement for trading_rs.GasOptimizer.
    """

    def __init__(
        self,
        eth_rpc_url: str = "",
        eth_price_usd: float = 2000.0,
    ) -> None:
        self._eth_rpc_url = eth_rpc_url
        self._eth_price_usd = eth_price_usd
        self._history: list[float] = []

        if RUST_DEFI_AVAILABLE:
            self._rust = trading_rs.GasOptimizer(eth_rpc_url, eth_price_usd)
        else:
            self._rust = None
            logger.info("GasOptimizer: using Python fallback")

    def get_recommendation(self, strategy: str = "standard") -> dict:
        """Get a gas price recommendation."""
        if self._rust:
            return self._rust.get_recommendation(strategy)

        # Python fallback: fetch from RPC
        return asyncio.get_event_loop().run_until_complete(self._fetch_recommendation(strategy))

    async def _fetch_recommendation(self, strategy: str) -> dict:
        """Fetch gas recommendation via HTTP RPC."""
        if not self._eth_rpc_url:
            return self._default_recommendation(strategy)

        async with httpx.AsyncClient() as client:
            try:
                # Get gas price
                resp = await client.post(
                    self._eth_rpc_url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "eth_gasPrice", "params": []},
                )
                gas_price_hex = resp.json().get("result", "0x0")
                gas_price_wei = int(gas_price_hex, 16)
                gas_price_gwei = gas_price_wei / 1e9

                self._history.append(gas_price_gwei)
            except Exception as e:
                logger.warning("Failed to fetch gas price: %s", e)
                gas_price_gwei = 30.0

        strategy_mult = {
            "economy": (1.0, 120),
            "standard": (1.1, 30),
            "fast": (1.25, 15),
            "aggressive": (1.5, 6),
        }
        mult, est_secs = strategy_mult.get(strategy, (1.1, 30))
        max_fee = gas_price_gwei * mult
        gas_limit = 150_000
        cost_eth = (max_fee * gas_limit) / 1e9
        cost_usd = cost_eth * self._eth_price_usd

        return {
            "strategy": strategy,
            "max_fee_gwei": round(max_fee, 2),
            "max_priority_fee_gwei": round(max_fee * 0.1, 2),
            "gas_price_gwei": round(gas_price_gwei, 2),
            "gas_limit": gas_limit,
            "estimated_cost_eth": round(cost_eth, 8),
            "estimated_cost_usd": round(cost_usd, 4),
            "est_confirmation_secs": est_secs,
            "best_chain": "ethereum",
        }

    def _default_recommendation(self, strategy: str) -> dict:
        """Return a default recommendation when RPC is unavailable."""
        defaults = {
            "economy": {"max_fee": 20.0, "priority": 1.0, "secs": 120},
            "standard": {"max_fee": 30.0, "priority": 1.5, "secs": 30},
            "fast": {"max_fee": 40.0, "priority": 2.5, "secs": 15},
            "aggressive": {"max_fee": 60.0, "priority": 5.0, "secs": 6},
        }
        d = defaults.get(strategy, defaults["standard"])
        gas_limit = 150_000
        cost_eth = (d["max_fee"] * gas_limit) / 1e9
        return {
            "strategy": strategy,
            "max_fee_gwei": d["max_fee"],
            "max_priority_fee_gwei": d["priority"],
            "gas_price_gwei": d["max_fee"],
            "gas_limit": gas_limit,
            "estimated_cost_eth": round(cost_eth, 8),
            "estimated_cost_usd": round(cost_eth * self._eth_price_usd, 4),
            "est_confirmation_secs": d["secs"],
            "best_chain": "ethereum",
        }

    def compare_chains(self) -> list[dict]:
        """Compare gas costs across L2 chains."""
        if self._rust:
            return self._rust.compare_chains()

        # Python fallback: static estimates
        chains = [
            {"chain": "ethereum", "chain_id": 1, "swap_cost_usd": 5.0, "security_level": 1},
            {"chain": "arbitrum", "chain_id": 42161, "swap_cost_usd": 0.10, "security_level": 2},
            {"chain": "base", "chain_id": 8453, "swap_cost_usd": 0.05, "security_level": 2},
            {"chain": "optimism", "chain_id": 10, "swap_cost_usd": 0.08, "security_level": 2},
            {"chain": "polygon", "chain_id": 137, "swap_cost_usd": 0.01, "security_level": 2},
        ]
        for c in chains:
            c["swap_cost_native"] = c["swap_cost_usd"] / self._eth_price_usd
            c["native_token_price_usd"] = self._eth_price_usd
            c["est_confirmation_secs"] = 12
            c["is_eip1559"] = True
        return sorted(chains, key=lambda c: c["swap_cost_usd"])

    def trend(self) -> float:
        """Get gas price trend (positive = rising)."""
        if self._rust:
            return self._rust.trend()
        if len(self._history) < 2:
            return 0.0
        recent = sum(self._history[-5:]) / min(5, len(self._history))
        older = sum(self._history[:5]) / min(5, len(self._history))
        return recent - older

    def predict_next_base_fee(self) -> float:
        """Predict next block's base fee."""
        if self._rust:
            return self._rust.predict_next_base_fee()
        if not self._history:
            return 0.0
        current = self._history[-1]
        trend = self.trend()
        max_change = current * 0.125
        return max(0.0, current + max(-max_change, min(max_change, trend)))

    def __repr__(self) -> str:
        return f"GasOptimizer(trend={self.trend():.2f})"


# ═══════════════════════════════════════════════════════════════════════
# DEX AGGREGATOR (Python fallback)
# ═══════════════════════════════════════════════════════════════════════


class DexAggregator:
    """DEX aggregator with Rust acceleration and Python fallback.

    Drop-in replacement for trading_rs.DexAggregator.
    """

    def __init__(
        self,
        chain: str = "ethereum",
        rpc_url: str = "",
        oneinch_api_key: str | None = None,
    ) -> None:
        self._chain = chain
        self._rpc_url = rpc_url
        self._oneinch_api_key = oneinch_api_key

        if RUST_DEFI_AVAILABLE:
            self._rust = trading_rs.DexAggregator(chain, rpc_url, oneinch_api_key)
        else:
            self._rust = None
            logger.info("DexAggregator: using Python fallback")

    def get_quotes(self, token_in: str, token_out: str, amount_in: float) -> dict:
        """Get quotes from all configured DEX sources."""
        if self._rust:
            return self._rust.get_quotes(token_in, token_out, amount_in)

        return asyncio.get_event_loop().run_until_complete(
            self._fetch_quotes(token_in, token_out, amount_in)
        )

    async def _fetch_quotes(self, token_in: str, token_out: str, amount_in: float) -> dict:
        """Fetch quotes from multiple DEX APIs in parallel."""
        start = time.monotonic()
        quotes = []
        failed = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []

            # 1inch
            if self._chain != "solana":
                tasks.append(self._fetch_oneinch(client, token_in, token_out, amount_in))

            # Jupiter
            if self._chain == "solana":
                tasks.append(self._fetch_jupiter(client, token_in, token_out, amount_in))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    failed.append(str(result))
                elif result:
                    quotes.append(result)

        fetch_time_ms = int((time.monotonic() - start) * 1000)

        if not quotes:
            return {
                "best_single": None,
                "all_quotes": [],
                "optimal_route": None,
                "failed_sources": failed,
                "fetch_time_ms": fetch_time_ms,
            }

        # Sort by net output
        quotes.sort(key=lambda q: q.get("net_output_usd", 0), reverse=True)

        return {
            "best_single": quotes[0],
            "all_quotes": quotes,
            "optimal_route": None,
            "failed_sources": failed,
            "fetch_time_ms": fetch_time_ms,
        }

    async def _fetch_oneinch(
        self, client: httpx.AsyncClient, token_in: str, token_out: str, amount_in: float
    ) -> dict | None:
        """Fetch quote from 1inch API."""
        chain_ids = {"ethereum": 1, "polygon": 137, "arbitrum": 42161, "base": 8453}
        chain_id = chain_ids.get(self._chain)
        if not chain_id:
            return None

        url = f"https://api.1inch.dev/swap/v6.0/{chain_id}/quote"
        headers = {}
        if self._oneinch_api_key:
            headers["Authorization"] = f"Bearer {self._oneinch_api_key}"

        try:
            resp = await client.get(
                url,
                params={"src": token_in, "dst": token_out, "amount": str(int(amount_in * 1e18))},
                headers=headers,
            )
            data = resp.json()
            amount_out = float(data.get("dstAmount", 0)) / 1e18
            return {
                "source": "1inch",
                "amount_out": amount_out,
                "price_impact_pct": 0.0,
                "gas_cost_usd": 5.0,
                "net_output_usd": amount_out,
            }
        except Exception as e:
            logger.warning("1inch quote failed: %s", e)
            return None

    async def _fetch_jupiter(
        self, client: httpx.AsyncClient, token_in: str, token_out: str, amount_in: float
    ) -> dict | None:
        """Fetch quote from Jupiter API (Solana)."""
        amount_int = int(amount_in * 1e9)
        url = "https://quote-api.jup.ag/v6/quote"
        try:
            resp = await client.get(
                url,
                params={"inputMint": token_in, "outputMint": token_out, "amount": str(amount_int)},
            )
            data = resp.json()
            amount_out = float(data.get("outAmount", 0)) / 1e9
            price_impact = float(data.get("priceImpactPct", 0))
            return {
                "source": "jupiter",
                "amount_out": amount_out,
                "price_impact_pct": price_impact,
                "gas_cost_usd": 0.01,
                "net_output_usd": amount_out,
            }
        except Exception as e:
            logger.warning("Jupiter quote failed: %s", e)
            return None

    def __repr__(self) -> str:
        return f"DexAggregator(chain={self._chain!r})"


# ═══════════════════════════════════════════════════════════════════════
# PRICE FEED (Python fallback)
# ═══════════════════════════════════════════════════════════════════════


class PriceFeed:
    """Price feed with Rust acceleration and Python fallback.

    Drop-in replacement for trading_rs.PriceFeed.
    """

    def __init__(
        self,
        coingecko_api_key: str | None = None,
        coinmarketcap_api_key: str | None = None,
    ) -> None:
        self._coingecko_key = coingecko_api_key
        self._coinmarketcap_key = coinmarketcap_api_key
        self._observations: dict[str, list[dict]] = {}

        if RUST_DEFI_AVAILABLE:
            self._rust = trading_rs.PriceFeed(coingecko_api_key, coinmarketcap_api_key)
        else:
            self._rust = None
            logger.info("PriceFeed: using Python fallback")

    def get_price(self, symbol: str) -> dict:
        """Fetch and aggregate price from all sources."""
        if self._rust:
            return self._rust.get_price(symbol)

        return asyncio.get_event_loop().run_until_complete(self._fetch_and_aggregate(symbol))

    async def _fetch_and_aggregate(self, symbol: str) -> dict:
        """Fetch prices from multiple sources and aggregate."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = [
                self._fetch_coingecko(client, symbol),
                self._fetch_binance(client, symbol),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        observations = []
        for r in results:
            if isinstance(r, dict):
                observations.append(r)

        if not observations:
            raise RuntimeError(f"Failed to fetch price for {symbol}")

        # Store observations
        self._observations.setdefault(symbol, []).extend(observations)

        # Aggregate (median)
        prices = [o["price_usd"] for o in observations]
        prices.sort()
        n = len(prices)
        median = prices[n // 2] if n % 2 == 1 else (prices[n // 2 - 1] + prices[n // 2]) / 2
        mean = sum(prices) / n
        variance = sum((p - mean) ** 2 for p in prices) / n

        return {
            "symbol": symbol,
            "price_usd": median,
            "mean_price_usd": mean,
            "min_price_usd": min(prices),
            "max_price_usd": max(prices),
            "std_dev_usd": variance**0.5,
            "source_count": len(observations),
            "confidence": min(1.0, len(observations) / 3),
            "sources": observations,
        }

    async def _fetch_coingecko(self, client: httpx.AsyncClient, symbol: str) -> dict | None:
        """Fetch price from CoinGecko."""
        coin_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "BNB": "binancecoin",
            "MATIC": "matic-network",
            "USDC": "usd-coin",
            "USDT": "tether",
        }
        coin_id = coin_map.get(symbol.upper(), symbol.lower())
        url = "https://api.coingecko.com/api/v3/simple/price"
        try:
            resp = await client.get(
                url,
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_24hr_vol": "true",
                    "include_24hr_change": "true",
                },
            )
            data = resp.json()
            price = data[coin_id]["usd"]
            return {
                "source": "coingecko",
                "price_usd": price,
                "volume_24h_usd": data[coin_id].get("usd_24h_vol"),
                "change_24h_pct": data[coin_id].get("usd_24h_change"),
            }
        except Exception as e:
            logger.warning("CoinGecko fetch failed for %s: %s", symbol, e)
            return None

    async def _fetch_binance(self, client: httpx.AsyncClient, symbol: str) -> dict | None:
        """Fetch price from Binance."""
        binance_symbol = f"{symbol.upper()}USDT"
        url = "https://api.binance.com/api/v3/ticker/24hr"
        try:
            resp = await client.get(url, params={"symbol": binance_symbol})
            data = resp.json()
            return {
                "source": "binance",
                "price_usd": float(data["lastPrice"]),
                "volume_24h_usd": float(data.get("quoteVolume", 0)),
                "change_24h_pct": float(data.get("priceChangePercent", 0)),
            }
        except Exception as e:
            logger.warning("Binance fetch failed for %s: %s", symbol, e)
            return None

    def detect_deviations(self, symbol: str) -> list[dict]:
        """Detect price deviations across sources."""
        if self._rust:
            return self._rust.detect_deviations(symbol)

        obs = self._observations.get(symbol, [])
        if len(obs) < 2:
            return []

        prices = [o["price_usd"] for o in obs]
        median = sorted(prices)[len(prices) // 2]
        deviations = []

        for o in obs:
            if median > 0:
                dev_bps = abs(o["price_usd"] - median) / median * 10_000
                if dev_bps > 500:  # 5% threshold
                    deviations.append(
                        {
                            "symbol": symbol,
                            "source": o["source"],
                            "deviating_price_usd": o["price_usd"],
                            "median_price_usd": median,
                            "deviation_bps": dev_bps,
                        }
                    )

        return deviations

    def twap(self, symbol: str, window_secs: int) -> float | None:
        """Compute TWAP over a time window."""
        if self._rust:
            return self._rust.twap(symbol, window_secs)

        obs = self._observations.get(symbol, [])
        if not obs:
            return None

        # Simplified: just return the average of recent observations
        prices = [o["price_usd"] for o in obs[-10:]]
        return sum(prices) / len(prices) if prices else None

    def __repr__(self) -> str:
        return f"PriceFeed(symbols={len(self._observations)})"


__all__ = [
    "RUST_DEFI_AVAILABLE",
    "MEVScanner",
    "GasOptimizer",
    "DexAggregator",
    "PriceFeed",
]
