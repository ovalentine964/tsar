"""
TSAR DeFi Backend — L2 Gas Optimization Engine.

Real-time gas price monitoring, L2 chain comparison, batch transaction
support, and intelligent chain selection for optimal execution cost
and speed.

L2 Comparison Matrix:
  ┌──────────────┬────────────┬───────────┬──────────┬──────────────┐
  │ Chain        │ Avg Gas $  │ Finality  │ TPS      │ Bridge Cost  │
  ├──────────────┼────────────┼───────────┼──────────┼──────────────┤
  │ Ethereum L1  │ $5-50      │ ~12 min   │ ~15      │ N/A          │
  │ Arbitrum     │ $0.10-0.50 │ ~1 sec    │ ~4,000   │ ~$3-8        │
  │ Optimism     │ $0.10-0.50 │ ~2 sec    │ ~2,000   │ ~$3-8        │
  │ Base         │ $0.05-0.20 │ ~2 sec    │ ~2,000   │ ~$2-5        │
  │ Polygon      │ $0.01-0.05 │ ~2 sec    │ ~7,000   │ ~$5-15       │
  └──────────────┴────────────┴───────────┴──────────┴──────────────┘

Usage:
    optimizer = L2Optimizer(config)
    best = await optimizer.get_optimal_chain(trade_size=10000, urgency="medium")
    prices = await optimizer.get_all_gas_prices()
    batched = await optimizer.batch_transactions([tx1, tx2, tx3])
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

class Chain(Enum):
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"


class Urgency(Enum):
    LOW = "low"         # willing to wait, minimize cost
    MEDIUM = "medium"   # balanced cost/speed
    HIGH = "high"       # speed matters, pay more
    CRITICAL = "critical"  # fastest possible


# Default L2 RPC endpoints
DEFAULT_RPC_URLS: dict[Chain, str] = {
    Chain.ETHEREUM: "https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY",
    Chain.POLYGON: "https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY",
    Chain.ARBITRUM: "https://arb-mainnet.g.alchemy.com/v2/YOUR_KEY",
    Chain.OPTIMISM: "https://opt-mainnet.g.alchemy.com/v2/YOUR_KEY",
    Chain.BASE: "https://base-mainnet.g.alchemy.com/v2/YOUR_KEY",
}

# Chain IDs
CHAIN_IDS: dict[Chain, int] = {
    Chain.ETHEREUM: 1,
    Chain.POLYGON: 137,
    Chain.ARBITRUM: 42161,
    Chain.OPTIMISM: 10,
    Chain.BASE: 8453,
}

# Typical bridge costs in USD (L1→L2)
BRIDGE_COSTS_USD: dict[Chain, float] = {
    Chain.ETHEREUM: 0.0,  # native
    Chain.POLYGON: 8.0,
    Chain.ARBITRUM: 5.0,
    Chain.OPTIMISM: 5.0,
    Chain.BASE: 3.0,
}

# Typical finality times in seconds
FINALITY_SECONDS: dict[Chain, float] = {
    Chain.ETHEREUM: 768.0,   # 12 min
    Chain.POLYGON: 2.0,
    Chain.ARBITRUM: 1.0,
    Chain.OPTIMISM: 2.0,
    Chain.BASE: 2.0,
}

# Max throughput (TPS)
MAX_TPS: dict[Chain, int] = {
    Chain.ETHEREUM: 15,
    Chain.POLYGON: 7000,
    Chain.ARBITRUM: 4000,
    Chain.OPTIMISM: 2000,
    Chain.BASE: 2000,
}

# EIP-1559 parameters
EIP1559_CHAINS = {Chain.ETHEREUM, Chain.POLYGON, Chain.ARBITRUM, Chain.OPTIMISM, Chain.BASE}


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class L2Config:
    """Configuration for the L2 optimizer."""
    rpc_urls: dict[str, str] = field(default_factory=dict)
    eth_price_usd: float = 3000.0  # updated via oracle in production
    gas_limit_default: int = 200_000
    priority_fee_gwei: float = 1.5
    max_fee_multiplier: float = 1.5  # multiplier on base fee
    cache_ttl_s: int = 12  # cache gas prices for 12 seconds
    bridge_enabled: bool = True
    batch_max_size: int = 50
    batch_max_gas: int = 5_000_000


@dataclass
class GasPrice:
    """Gas price information for a chain."""
    chain: Chain
    base_fee: int = 0  # wei, EIP-1559 base fee
    priority_fee: int = 0  # wei, suggested priority fee
    max_fee: int = 0  # wei, max fee per gas
    gas_price_legacy: int = 0  # wei, legacy gas price
    estimated_cost_usd: float = 0.0  # cost for default gas limit
    block_number: int = 0
    utilization: float = 0.0  # 0.0-1.0, block gas utilization
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChainRecommendation:
    """Recommendation for chain selection."""
    chain: Chain
    score: float  # 0-100, higher is better
    estimated_cost_usd: float
    estimated_time_s: float
    bridge_cost_usd: float
    total_cost_usd: float  # gas + bridge
    reason: str
    gas_price: GasPrice | None = None


@dataclass
class BatchTransaction:
    """A batched set of transactions."""
    batch_id: str
    transactions: list[dict[str, Any]]
    chain: Chain
    total_gas_estimate: int = 0
    estimated_cost_usd: float = 0.0
    gas_savings_pct: float = 0.0  # savings vs individual submission


@dataclass
class GasHistory:
    """Historical gas price data for a chain."""
    chain: Chain
    samples: list[tuple[float, int]] = field(default_factory=list)  # (timestamp, gas_price_wei)
    window_s: int = 3600  # 1 hour window

    def add_sample(self, gas_price: int) -> None:
        now = time.time()
        self.samples.append((now, gas_price))
        # Prune old samples
        cutoff = now - self.window_s
        self.samples = [(t, p) for t, p in self.samples if t > cutoff]

    def percentile(self, p: float) -> int:
        """Get the p-th percentile of recent gas prices."""
        if not self.samples:
            return 0
        sorted_prices = sorted(p for _, p in self.samples)
        idx = int(len(sorted_prices) * p / 100)
        return sorted_prices[min(idx, len(sorted_prices) - 1)]

    @property
    def average(self) -> int:
        if not self.samples:
            return 0
        return sum(p for _, p in self.samples) // len(self.samples)


# ═══════════════════════════════════════════════════════════════════════
# L2 OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════

class L2Optimizer:
    """
    L2 gas optimization engine.

    Provides real-time gas monitoring, chain comparison, batch support,
    and intelligent chain selection for optimal DeFi execution.
    """

    def __init__(self, config: L2Config | None = None):
        self.config = config or L2Config()
        self._gas_cache: dict[Chain, GasPrice] = {}
        self._gas_history: dict[Chain, GasHistory] = {
            chain: GasHistory(chain=chain) for chain in Chain
        }
        self._cache_time: float = 0
        self._supported_chains = list(Chain)
        logger.info("L2Optimizer initialized")

    # ───────────────────────────────────────────────────────────────────
    # Public API: Gas Prices
    # ───────────────────────────────────────────────────────────────────

    async def get_gas_price(self, chain: Chain) -> GasPrice:
        """
        Get current gas price for a specific chain.

        Returns cached data if within TTL, otherwise fetches fresh data.
        """
        if self._is_cache_valid() and chain in self._gas_cache:
            return self._gas_cache[chain]

        gas_price = await self._fetch_gas_price(chain)
        self._gas_cache[chain] = gas_price
        self._cache_time = time.time()
        self._gas_history[chain].add_sample(gas_price.gas_price_legacy)

        return gas_price

    async def get_all_gas_prices(self) -> dict[Chain, GasPrice]:
        """Get gas prices across all supported chains."""
        prices = {}
        for chain in self._supported_chains:
            try:
                prices[chain] = await self.get_gas_price(chain)
            except Exception as e:
                logger.warning(
                    "Failed to get gas price",
                    extra={"chain": chain.value, "error": str(e)},
                )
        return prices

    async def get_gas_history(
        self, chain: Chain, window_s: int = 3600
    ) -> GasHistory:
        """Get gas price history for a chain."""
        return self._gas_history.get(chain, GasHistory(chain=chain))

    # ───────────────────────────────────────────────────────────────────
    # Public API: Chain Selection
    # ───────────────────────────────────────────────────────────────────

    async def get_optimal_chain(
        self,
        trade_size: float,
        urgency: str = "medium",
        include_bridge_cost: bool = True,
    ) -> ChainRecommendation:
        """
        Recommend the optimal L2 chain for execution.

        Considers gas cost, bridge cost, finality time, and urgency.

        Args:
            trade_size: Trade size in USD
            urgency: "low", "medium", "high", or "critical"
            include_bridge_cost: Whether to factor in bridge costs

        Returns:
            ChainRecommendation with the best chain and reasoning
        """
        urgency_enum = Urgency(urgency.lower())
        recommendations = await self.compare_chains(
            trade_size, urgency_enum, include_bridge_cost
        )

        if not recommendations:
            # Fallback to Ethereum
            return ChainRecommendation(
                chain=Chain.ETHEREUM,
                score=50.0,
                estimated_cost_usd=0.0,
                estimated_time_s=FINALITY_SECONDS[Chain.ETHEREUM],
                bridge_cost_usd=0.0,
                total_cost_usd=0.0,
                reason="No chains available, defaulting to Ethereum",
            )

        best = recommendations[0]
        logger.info(
            "Optimal chain selected",
            extra={
                "chain": best.chain.value,
                "score": best.score,
                "total_cost_usd": best.total_cost_usd,
                "urgency": urgency,
            },
        )
        return best

    async def compare_chains(
        self,
        trade_size: float,
        urgency: Urgency = Urgency.MEDIUM,
        include_bridge_cost: bool = True,
    ) -> list[ChainRecommendation]:
        """
        Compare all chains and return sorted recommendations.

        Scoring factors by urgency:
          LOW:      70% cost, 20% speed, 10% reliability
          MEDIUM:   50% cost, 30% speed, 20% reliability
          HIGH:     20% cost, 60% speed, 20% reliability
          CRITICAL: 10% cost, 70% speed, 20% reliability
        """
        weights = {
            Urgency.LOW: (0.70, 0.20, 0.10),
            Urgency.MEDIUM: (0.50, 0.30, 0.20),
            Urgency.HIGH: (0.20, 0.60, 0.20),
            Urgency.CRITICAL: (0.10, 0.70, 0.20),
        }
        w_cost, w_speed, w_reliability = weights[urgency]

        recommendations = []
        all_prices = await self.get_all_gas_prices()

        for chain in self._supported_chains:
            if chain not in all_prices:
                continue

            gas = all_prices[chain]
            bridge_cost = BRIDGE_COSTS_USD.get(chain, 0.0) if include_bridge_cost else 0.0
            finality = FINALITY_SECONDS.get(chain, 600.0)

            # Cost score (0-100, lower cost = higher score)
            max_cost = 50.0  # reference max cost in USD
            cost_score = max(0, 100 - (gas.estimated_cost_usd + bridge_cost) / max_cost * 100)

            # Speed score (0-100, faster = higher score)
            max_finality = 900.0  # 15 min reference
            speed_score = max(0, 100 - finality / max_finality * 100)

            # Reliability score (based on TPS headroom)
            tps = MAX_TPS.get(chain, 100)
            reliability_score = min(100, tps / 50)  # 50 TPS = score 100 for L2s

            total_score = (
                w_cost * cost_score
                + w_speed * speed_score
                + w_reliability * reliability_score
            )

            total_cost = gas.estimated_cost_usd + bridge_cost

            reason = self._build_recommendation_reason(
                chain, gas, bridge_cost, finality, total_score, urgency
            )

            recommendations.append(ChainRecommendation(
                chain=chain,
                score=round(total_score, 1),
                estimated_cost_usd=gas.estimated_cost_usd,
                estimated_time_s=finality,
                bridge_cost_usd=bridge_cost,
                total_cost_usd=round(total_cost, 4),
                reason=reason,
                gas_price=gas,
            ))

        # Sort by score descending
        recommendations.sort(key=lambda r: r.score, reverse=True)
        return recommendations

    # ───────────────────────────────────────────────────────────────────
    # Public API: Gas Estimation
    # ───────────────────────────────────────────────────────────────────

    async def estimate_transaction_cost(
        self,
        chain: Chain,
        gas_limit: int = 0,
        trade_size_usd: float = 0.0,
    ) -> dict[str, Any]:
        """
        Estimate the full cost of a transaction on a chain.

        Returns gas cost in USD, ETH/native token, and wei.
        """
        gas_limit = gas_limit or self.config.gas_limit_default
        gas = await self.get_gas_price(chain)

        total_fee_wei = gas.max_fee * gas_limit
        total_fee_eth = total_fee_wei / 1e18
        total_fee_usd = total_fee_eth * self.config.eth_price_usd

        # For Polygon, use MATIC price (roughly $0.50-1.00)
        if chain == Chain.POLYGON:
            total_fee_usd = total_fee_eth * 0.75  # rough MATIC price

        return {
            "chain": chain.value,
            "gas_limit": gas_limit,
            "base_fee_gwei": gas.base_fee / 1e9,
            "priority_fee_gwei": gas.priority_fee / 1e9,
            "max_fee_gwei": gas.max_fee / 1e9,
            "total_fee_wei": total_fee_wei,
            "total_fee_eth": round(total_fee_eth, 8),
            "total_fee_usd": round(total_fee_usd, 4),
            "trade_size_usd": trade_size_usd,
            "cost_as_pct": round(
                total_fee_usd / trade_size_usd * 100, 4
            ) if trade_size_usd > 0 else None,
        }

    async def estimate_bridge_cost(
        self,
        source: Chain,
        destination: Chain,
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """
        Estimate the cost of bridging assets between chains.

        Includes gas on source chain, bridge fee, and gas on destination.
        """
        source_gas = await self.get_gas_price(source)
        dest_gas = await self.get_gas_price(destination)

        # Bridge contract interaction gas (typical)
        bridge_gas_limit = 150_000
        source_cost_eth = source_gas.max_fee * bridge_gas_limit / 1e18
        source_cost_usd = source_cost_eth * self.config.eth_price_usd

        # Bridge protocol fee (varies by bridge, using estimates)
        bridge_fee_pct = 0.001  # 0.1%
        bridge_fee_usd = amount_usd * bridge_fee_pct if amount_usd > 0 else 0.0

        # Destination claim gas
        claim_gas_limit = 100_000
        dest_cost_eth = dest_gas.max_fee * claim_gas_limit / 1e18
        dest_cost_usd = dest_cost_eth * self.config.eth_price_usd

        total_usd = source_cost_usd + bridge_fee_usd + dest_cost_usd

        return {
            "source_chain": source.value,
            "destination_chain": destination.value,
            "source_gas_usd": round(source_cost_usd, 4),
            "bridge_fee_usd": round(bridge_fee_usd, 4),
            "destination_gas_usd": round(dest_cost_usd, 4),
            "total_cost_usd": round(total_usd, 4),
            "amount_usd": amount_usd,
            "cost_as_pct": round(
                total_usd / amount_usd * 100, 4
            ) if amount_usd > 0 else None,
        }

    # ───────────────────────────────────────────────────────────────────
    # Public API: EIP-1559 Base Fee Tracking
    # ───────────────────────────────────────────────────────────────────

    async def get_base_fee_trend(
        self, chain: Chain | str, samples: int = 10
    ) -> dict[str, Any]:
        """
        Get EIP-1559 base fee trend for a chain.

        Returns current, average, and percentile base fees,
        plus a trend direction indicator.
        """
        if isinstance(chain, str):
            chain = Chain(chain.lower())
        history = self._gas_history.get(chain)
        if not history or not history.samples:
            gas = await self.get_gas_price(chain)
            return {
                "chain": chain.value,
                "current_base_fee_gwei": gas.base_fee / 1e9,
                "average_gwei": gas.base_fee / 1e9,
                "p25_gwei": gas.base_fee / 1e9,
                "p75_gwei": gas.base_fee / 1e9,
                "p95_gwei": gas.base_fee / 1e9,
                "trend": "stable",
                "samples": 0,
            }

        current = history.samples[-1][1] if history.samples else 0
        avg = history.average
        p25 = history.percentile(25)
        p75 = history.percentile(75)
        p95 = history.percentile(95)

        # Determine trend
        if len(history.samples) >= 3:
            recent = [p for _, p in history.samples[-3:]]
            if recent[-1] > recent[0] * 1.1:
                trend = "rising"
            elif recent[-1] < recent[0] * 0.9:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return {
            "chain": chain.value,
            "current_base_fee_gwei": round(current / 1e9, 2),
            "average_gwei": round(avg / 1e9, 2),
            "p25_gwei": round(p25 / 1e9, 2),
            "p75_gwei": round(p75 / 1e9, 2),
            "p95_gwei": round(p95 / 1e9, 2),
            "trend": trend,
            "samples": len(history.samples),
        }

    # ───────────────────────────────────────────────────────────────────
    # Public API: Priority Fee Optimization
    # ───────────────────────────────────────────────────────────────────

    async def optimize_priority_fee(
        self, chain: Chain | str, urgency: str = "medium"
    ) -> dict[str, Any]:
        """
        Calculate optimal priority fee based on network congestion.

        Returns suggested priority fee in gwei with reasoning.
        """
        if isinstance(chain, str):
            chain = Chain(chain.lower())
        gas = await self.get_gas_price(chain)
        utilization = gas.utilization

        # Base priority fee by urgency
        base_priority = {
            "low": 0.5,
            "medium": 1.5,
            "high": 3.0,
            "critical": 5.0,
        }
        base = base_priority.get(urgency, 1.5)

        # Adjust for congestion
        if utilization > 0.9:
            multiplier = 2.0
            congestion_label = "very_high"
        elif utilization > 0.7:
            multiplier = 1.5
            congestion_label = "high"
        elif utilization > 0.5:
            multiplier = 1.0
            congestion_label = "moderate"
        else:
            multiplier = 0.8
            congestion_label = "low"

        suggested_gwei = base * multiplier

        return {
            "chain": chain.value,
            "urgency": urgency,
            "congestion": congestion_label,
            "utilization": round(utilization * 100, 1),
            "base_priority_gwei": base,
            "multiplier": multiplier,
            "suggested_priority_fee_gwei": round(suggested_gwei, 2),
            "suggested_priority_fee_wei": int(suggested_gwei * 1e9),
        }

    # ───────────────────────────────────────────────────────────────────
    # Public API: Batch Transactions
    # ───────────────────────────────────────────────────────────────────

    async def batch_transactions(
        self,
        transactions: list[dict[str, Any]],
        chain: Chain | None = None,
    ) -> BatchTransaction:
        """
        Combine multiple transactions into a single batch for gas savings.

        Args:
            transactions: List of transaction dicts with 'to', 'data', 'value' keys
            chain: Target chain (auto-selected if None)

        Returns:
            BatchTransaction with combined gas estimate and savings
        """
        if not transactions:
            raise ValueError("No transactions to batch")

        if len(transactions) > self.config.batch_max_size:
            raise ValueError(
                f"Batch size {len(transactions)} exceeds max {self.config.batch_max_size}"
            )

        # Auto-select cheapest chain if not specified
        if chain is None:
            rec = await self.get_optimal_chain(
                trade_size=0, urgency="low", include_bridge_cost=False
            )
            chain = rec.chain

        # Estimate individual gas costs
        individual_gas = sum(
            tx.get("gas_limit", self.config.gas_limit_default)
            for tx in transactions
        )

        # Batched gas: base overhead + reduced per-tx cost
        # Multicall3 or custom batch contract saves ~30-40% gas
        batch_overhead = 50_000  # contract dispatch overhead
        per_tx_gas = int(
            self.config.gas_limit_default * 0.65
        )  # 35% savings per tx in batch
        batched_gas = batch_overhead + per_tx_gas * len(transactions)

        # Cap at max batch gas
        batched_gas = min(batched_gas, self.config.batch_max_gas)

        savings_pct = (
            (individual_gas - batched_gas) / individual_gas * 100
            if individual_gas > 0
            else 0
        )

        gas = await self.get_gas_price(chain)
        cost_eth = batched_gas * gas.max_fee / 1e18
        cost_usd = cost_eth * self.config.eth_price_usd

        batch_id = f"batch_{int(time.time())}_{len(transactions)}"

        logger.info(
            "Batch created",
            extra={
                "batch_id": batch_id,
                "chain": chain.value,
                "tx_count": len(transactions),
                "gas_savings_pct": round(savings_pct, 1),
            },
        )

        return BatchTransaction(
            batch_id=batch_id,
            transactions=transactions,
            chain=chain,
            total_gas_estimate=batched_gas,
            estimated_cost_usd=round(cost_usd, 4),
            gas_savings_pct=round(savings_pct, 1),
        )

    # ───────────────────────────────────────────────────────────────────
    # Internal: Gas Price Fetching
    # ───────────────────────────────────────────────────────────────────

    async def _fetch_gas_price(self, chain: Chain) -> GasPrice:
        """Fetch fresh gas price data for a chain."""
        # In production: call eth_feeHistory or eth_gasPrice via RPC
        # Using realistic default values for development

        defaults = {
            Chain.ETHEREUM: GasPrice(
                chain=Chain.ETHEREUM,
                base_fee=25_000_000_000,  # 25 gwei
                priority_fee=1_500_000_000,  # 1.5 gwei
                max_fee=39_000_000_000,  # ~39 gwei
                gas_price_legacy=30_000_000_000,
                estimated_cost_usd=2.34,  # 200k gas at 25 gwei, ETH=$3000
                utilization=0.65,
            ),
            Chain.POLYGON: GasPrice(
                chain=Chain.POLYGON,
                base_fee=40_000_000_000,  # 40 gwei
                priority_fee=30_000_000_000,  # 30 gwei
                max_fee=90_000_000_000,
                gas_price_legacy=50_000_000_000,
                estimated_cost_usd=0.008,
                utilization=0.45,
            ),
            Chain.ARBITRUM: GasPrice(
                chain=Chain.ARBITRUM,
                base_fee=100_000_000,  # 0.1 gwei
                priority_fee=100_000,  # 0.0001 gwei
                max_fee=200_000_000,
                gas_price_legacy=100_000_000,
                estimated_cost_usd=0.12,
                utilization=0.30,
            ),
            Chain.OPTIMISM: GasPrice(
                chain=Chain.OPTIMISM,
                base_fee=100_000_000,
                priority_fee=1_000_000,  # 0.001 gwei
                max_fee=200_000_000,
                gas_price_legacy=100_000_000,
                estimated_cost_usd=0.15,
                utilization=0.35,
            ),
            Chain.BASE: GasPrice(
                chain=Chain.BASE,
                base_fee=50_000_000,  # 0.05 gwei
                priority_fee=100_000,
                max_fee=100_000_000,
                gas_price_legacy=50_000_000,
                estimated_cost_usd=0.06,
                utilization=0.25,
            ),
        }

        return defaults.get(chain, GasPrice(chain=chain))

    def _is_cache_valid(self) -> bool:
        """Check if gas price cache is still valid."""
        return (time.time() - self._cache_time) < self.config.cache_ttl_s

    # ───────────────────────────────────────────────────────────────────
    # Internal: Helpers
    # ───────────────────────────────────────────────────────────────────

    def _build_recommendation_reason(
        self,
        chain: Chain,
        gas: GasPrice,
        bridge_cost: float,
        finality: float,
        score: float,
        urgency: Urgency,
    ) -> str:
        """Build a human-readable recommendation reason."""
        parts = []

        if chain == Chain.ETHEREUM:
            parts.append("Ethereum L1 — highest security, no bridge needed")
        elif chain == Chain.ARBITRUM:
            parts.append("Arbitrum — lowest L2 costs, fast finality")
        elif chain == Chain.BASE:
            parts.append("Base — cheapest L2, backed by Coinbase")
        elif chain == Chain.OPTIMISM:
            parts.append("Optimism — strong ecosystem, moderate costs")
        elif chain == Chain.POLYGON:
            parts.append("Polygon — very cheap, high throughput")

        total = gas.estimated_cost_usd + bridge_cost
        parts.append(f"Est. total cost: ${total:.4f}")

        if urgency in (Urgency.HIGH, Urgency.CRITICAL):
            parts.append(f"Finality: {finality:.0f}s")

        return " — ".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# CONVENIENCE FACTORY
# ═══════════════════════════════════════════════════════════════════════

def create_l2_optimizer(
    rpc_urls: dict[str, str] | None = None,
    eth_price_usd: float = 3000.0,
    priority_fee_gwei: float = 1.5,
) -> L2Optimizer:
    """Create an L2Optimizer from simple parameters."""
    config = L2Config(
        rpc_urls=rpc_urls or {},
        eth_price_usd=eth_price_usd,
        priority_fee_gwei=priority_fee_gwei,
    )
    return L2Optimizer(config)
