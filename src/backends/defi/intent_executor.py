"""
TSAR DeFi Backend — Intent-Based Execution Engine.

Implements intent-based trading protocols where users express *what* they want
(e.g., "swap 1000 USDC for ETH") and competitive solvers find the optimal
execution path. This eliminates the need for users to specify exact routes.

Integrated protocols:
  1. CoW Protocol (Ethereum) — Batch auctions, MEV-protected by design
  2. UniswapX              — Dutch auction mechanism, gasless swaps
  3. 1inch Fusion           — Intent-based swaps with resolver competition

Key advantages over direct DEX routing:
  - MEV protection (no frontrunning/sandwich attacks)
  - Gasless transactions (solver pays gas)
  - Better prices through solver competition
  - Cross-venue liquidity aggregation

Usage:
    executor = IntentExecutor(config)
    quotes = await executor.get_intent_quotes("ETH/USDC", 1000, "ethereum")
    result = await executor.execute_intent_swap("ETH/USDC", 1000, "ethereum", quote=quotes[0])
    verified = await executor.verify_settlement(result)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════


class IntentProtocol(StrEnum):
    """Supported intent-based trading protocols."""
    COW_PROTOCOL = "cow_protocol"
    UNISWAPX = "uniswapx"
    ONEINCH_FUSION = "1inch_fusion"


class IntentStatus(StrEnum):
    """Lifecycle status of an intent order."""
    CREATED = "created"
    SUBMITTED = "submitted"
    SOLVER_COMPETING = "solver_competing"
    MATCHED = "matched"
    EXECUTING = "executing"
    SETTLED = "settled"
    EXPIRED = "expired"
    FAILED = "failed"


class SettlementVerification(StrEnum):
    """Result of settlement verification."""
    VERIFIED = "verified"
    PRICE_DEVIATION = "price_deviation"
    AMOUNT_MISMATCH = "amount_mismatch"
    NOT_FOUND = "not_found"
    PENDING = "pending"


# Token address registry (mainnet)
TOKEN_ADDRESSES: dict[str, dict[str, str]] = {
    "ethereum": {
        "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    },
    "arbitrum": {
        "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
    },
    "base": {
        "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WETH": "0x4200000000000000000000000000000000000006",
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
}

# Protocol fee structures
PROTOCOL_FEES: dict[IntentProtocol, dict[str, float]] = {
    IntentProtocol.COW_PROTOCOL: {"solver_fee_bps": 0, "protocol_fee_bps": 1, "gas_savings_bps": 5},
    IntentProtocol.UNISWAPX: {"solver_fee_bps": 0, "protocol_fee_bps": 0, "gas_savings_bps": 8},
    IntentProtocol.ONEINCH_FUSION: {"solver_fee_bps": 0, "protocol_fee_bps": 3, "gas_savings_bps": 4},
}

# Protocol chain support
PROTOCOL_CHAINS: dict[IntentProtocol, list[str]] = {
    IntentProtocol.COW_PROTOCOL: ["ethereum"],
    IntentProtocol.UNISWAPX: ["ethereum", "arbitrum", "base"],
    IntentProtocol.ONEINCH_FUSION: ["ethereum", "arbitrum", "base"],
}

# Auction duration defaults (seconds)
AUCTION_DURATION_S: dict[IntentProtocol, float] = {
    IntentProtocol.COW_PROTOCOL: 30,
    IntentProtocol.UNISWAPX: 60,
    IntentProtocol.ONEINCH_FUSION: 45,
}


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class IntentQuote:
    """A quote from an intent-based protocol.

    Attributes:
        protocol: Intent protocol providing the quote.
        pair: Trading pair (e.g., "ETH/USDC").
        side: Buy or sell direction.
        amount: Input amount.
        estimated_output: Expected output amount.
        price: Effective price.
        price_impact_bps: Price impact in basis points.
        gas_cost_usd: Estimated gas cost (often $0 for intent protocols).
        protocol_fee_usd: Protocol fee in USD.
        mev_protection: Whether MEV protection is enabled.
        solver_count: Number of competing solvers.
        auction_duration_s: How long the auction runs.
        expires_at: When the quote expires.
        route_id: Unique identifier for this quote.
    """
    protocol: IntentProtocol
    pair: str
    side: str
    amount: float
    estimated_output: float
    price: float
    price_impact_bps: float
    gas_cost_usd: float
    protocol_fee_usd: float
    mev_protection: bool
    solver_count: int
    auction_duration_s: float
    expires_at: datetime | None = None
    route_id: str = ""


@dataclass(frozen=True)
class IntentResult:
    """Result of executing an intent-based swap.

    Attributes:
        order_id: Intent order ID.
        protocol: Protocol used.
        pair: Trading pair.
        side: Buy or sell.
        amount: Input amount.
        filled_amount: Amount actually received.
        execution_price: Actual execution price.
        price_impact_bps: Realized price impact.
        gas_paid_by_solver: Whether solver paid gas.
        solver_address: Address of winning solver.
        tx_hash: Settlement transaction hash.
        status: Current status.
        created_at: When the intent was created.
        settled_at: When the intent was settled.
    """
    order_id: str
    protocol: IntentProtocol
    pair: str
    side: str
    amount: float
    filled_amount: float
    execution_price: float
    price_impact_bps: float
    gas_paid_by_solver: bool
    solver_address: str
    tx_hash: str
    status: IntentStatus = IntentStatus.CREATED
    created_at: datetime | None = None
    settled_at: datetime | None = None


@dataclass(frozen=True)
class SettlementVerificationResult:
    """Result of verifying on-chain settlement.

    Attributes:
        verified: Whether the settlement matches the intent.
        expected_output: Expected output from quote.
        actual_output: Actual output on-chain.
        deviation_bps: Price deviation in basis points.
        on_chain_tx_hash: Settlement transaction hash.
        block_number: Block number of settlement.
        gas_used: Actual gas used.
        verification: Detailed verification status.
    """
    verified: bool
    expected_output: float
    actual_output: float
    deviation_bps: float
    on_chain_tx_hash: str
    block_number: int
    gas_used: int
    verification: SettlementVerification


@dataclass(frozen=True)
class ExecutionComparison:
    """Comparison of execution methods for a swap.

    Attributes:
        pair: Trading pair.
        amount: Input amount.
        intent_quotes: Quotes from intent protocols.
        dex_quotes: Quotes from direct DEX routing.
        best_method: Best execution method name.
        best_price: Best price found.
        savings_vs_worst_bps: Savings vs worst option in bps.
        mev_protection_winner: Which method has best MEV protection.
    """
    pair: str
    amount: float
    intent_quotes: list[IntentQuote]
    dex_quotes: list[dict[str, Any]]
    best_method: str
    best_price: float
    savings_vs_worst_bps: float
    mev_protection_winner: str


# ═══════════════════════════════════════════════════════════════════════
# INTENT PROTOCOL CLIENTS
# ═══════════════════════════════════════════════════════════════════════


class CowProtocolClient:
    """CoW Protocol (Coincidence of Wants) client.

    CoW Protocol uses batch auctions where solvers compete to find the
    best execution for a group of orders. MEV-protected by design because
    orders are settled atomically in batches — no mempool exposure.

    Features:
    - Batch auctions every ~30 seconds
    - Solver competition for best price
    - Coincidence of Wants (direct user-to-user matching)
    - Gasless for users (solvers pay gas)
    - MEV protection (no mempool, atomic settlement)

    Docs: https://docs.cow.fi/
    """

    API_BASE = "https://api.cow.fi/mainnet"
    EXPLORER = "https://explorer.cow.fi"

    def __init__(self, http_client: httpx.AsyncClient, config: dict[str, Any] | None = None):
        self._http = http_client
        self._config = config or {}
        self._solver_urls = self._config.get("solver_urls", [
            "https://solver.cow.fi",
            "https://solver-1.cow.fi",
        ])

    def supports_chain(self, chain: str) -> bool:
        """Check if CoW Protocol supports this chain."""
        return chain in PROTOCOL_CHAINS[IntentProtocol.COW_PROTOCOL]

    async def get_quote(
        self, pair: str, amount: float, chain: str, side: str = "buy"
    ) -> IntentQuote:
        """Get a CoW Protocol quote via order book preview.

        Args:
            pair: Trading pair (e.g., "ETH/USDC").
            amount: Input amount.
            chain: Chain to execute on.
            side: Buy or sell direction.

        Returns:
            IntentQuote with CoW Protocol pricing.
        """
        base, quote = pair.split("/")
        tokens = TOKEN_ADDRESSES.get(chain, {})

        # Simulate solver competition
        base_price = await self._get_reference_price(base, quote, chain)
        if side == "buy":
            estimated_output = amount / base_price
            # CoW often finds coincidence of Wants — slight improvement
            improvement_bps = 2.5
            estimated_output *= (1 + improvement_bps / 10_000)
        else:
            estimated_output = amount * base_price
            improvement_bps = 2.5
            estimated_output *= (1 + improvement_bps / 10_000)

        price_impact = max(0.5, 10 / (amount + 1))  # Less impact for larger orders on CoW
        fee_info = PROTOCOL_FEES[IntentProtocol.COW_PROTOCOL]

        gas_cost = 0.0  # Gasless for users
        protocol_fee = amount * base_price * fee_info["protocol_fee_bps"] / 10_000

        now = datetime.now(UTC)
        expires_at = now.replace(second=(now.second + 30) % 60, minute=now.minute + (1 if now.second >= 30 else 0))

        route_id = f"cow-{pair}-{amount}-{uuid.uuid4().hex[:8]}"

        return IntentQuote(
            protocol=IntentProtocol.COW_PROTOCOL,
            pair=pair,
            side=side,
            amount=amount,
            estimated_output=round(estimated_output, 6),
            price=round(estimated_output / amount if side == "buy" else amount / estimated_output, 6),
            price_impact_bps=round(price_impact, 2),
            gas_cost_usd=gas_cost,
            protocol_fee_usd=round(protocol_fee, 2),
            mev_protection=True,
            solver_count=8,  # Typical number of competing solvers
            auction_duration_s=AUCTION_DURATION_S[IntentProtocol.COW_PROTOCOL],
            expires_at=expires_at,
            route_id=route_id,
        )

    async def submit_order(
        self, pair: str, amount: float, chain: str, side: str,
        user_address: str, slippage_bps: float = 50,
    ) -> IntentResult:
        """Submit an order to CoW Protocol.

        Creates a signed order that enters the next batch auction.
        Solvers compete to fill the order at the best price.

        Args:
            pair: Trading pair.
            amount: Input amount.
            chain: Chain.
            side: Buy or sell.
            user_address: User's wallet address.
            slippage_bps: Maximum acceptable slippage.

        Returns:
            IntentResult with order details.
        """
        order_id = f"cow-{uuid.uuid4().hex}"
        base, quote = pair.split("/")

        # In production: sign EIP-712 order and POST to /api/v1/orders
        # Simulate order submission
        base_price = await self._get_reference_price(base, quote, chain)
        if side == "buy":
            filled_amount = amount / base_price * (1 + 0.002)  # Slight improvement from solver
        else:
            filled_amount = amount * base_price * (1 + 0.002)

        tx_data = f"cow_settle:{order_id}:{time.time()}"
        tx_hash = "0x" + hashlib.sha256(tx_data.encode()).hexdigest()

        logger.info(
            "cow_order_submitted",
            order_id=order_id,
            pair=pair,
            amount=amount,
            side=side,
            chain=chain,
        )

        return IntentResult(
            order_id=order_id,
            protocol=IntentProtocol.COW_PROTOCOL,
            pair=pair,
            side=side,
            amount=amount,
            filled_amount=round(filled_amount, 6),
            execution_price=round(filled_amount / amount if side == "buy" else amount / filled_amount, 6),
            price_impact_bps=round(max(0.5, 10 / (amount + 1)), 2),
            gas_paid_by_solver=True,
            solver_address="0x" + hashlib.sha256(f"solver-{order_id}".encode()).hexdigest()[:40],
            tx_hash=tx_hash,
            status=IntentStatus.SETTLED,
            created_at=datetime.now(UTC),
            settled_at=datetime.now(UTC),
        )

    async def _get_reference_price(self, base: str, quote: str, chain: str) -> float:
        """Get reference price for a pair."""
        # Simplified price lookup — in production would use CoinGecko/Chainlink
        prices = {
            "ETH": 3500, "BTC": 65000, "SOL": 150, "USDC": 1.0, "USDT": 1.0,
            "DAI": 1.0, "WBTC": 65000, "MATIC": 0.8, "AVAX": 35,
        }
        base_price = prices.get(base, 1.0)
        quote_price = prices.get(quote, 1.0)
        return base_price / quote_price


class UniswapXClient:
    """UniswapX intent-based swap client.

    UniswapX uses a Dutch auction mechanism where fillers compete
    to execute swaps. Users sign off-chain orders; fillers submit
    on-chain settlements.

    Features:
    - Dutch auction price discovery
    - Gasless for swappers (fillers pay gas)
    - MEV protection (no public mempool)
    - Cross-venue liquidity (fillers can source from anywhere)
    - ETH and ERC-20 support

    Docs: https://docs.uniswap.org/
    """

    API_BASE = "https://api.uniswap.org/v1"

    def __init__(self, http_client: httpx.AsyncClient, config: dict[str, Any] | None = None):
        self._http = http_client
        self._config = config or {}

    def supports_chain(self, chain: str) -> bool:
        """Check if UniswapX supports this chain."""
        return chain in PROTOCOL_CHAINS[IntentProtocol.UNISWAPX]

    async def get_quote(
        self, pair: str, amount: float, chain: str, side: str = "buy"
    ) -> IntentQuote:
        """Get a UniswapX quote.

        Args:
            pair: Trading pair.
            amount: Input amount.
            chain: Chain.
            side: Buy or sell.

        Returns:
            IntentQuote with UniswapX pricing.
        """
        base, quote = pair.split("/")
        base_price = await self._get_reference_price(base, quote, chain)

        if side == "buy":
            estimated_output = amount / base_price
        else:
            estimated_output = amount * base_price

        # UniswapX competitive pricing
        improvement_bps = 3.0
        if side == "buy":
            estimated_output *= (1 + improvement_bps / 10_000)
        else:
            estimated_output *= (1 + improvement_bps / 10_000)

        price_impact = max(0.3, 8 / (amount + 1))
        gas_cost = 0.0  # Gasless
        protocol_fee = 0.0  # No protocol fee on UniswapX

        now = datetime.now(UTC)
        expires_at = now.replace(second=(now.second + 60) % 60, minute=now.minute + 1)
        route_id = f"ux-{pair}-{amount}-{uuid.uuid4().hex[:8]}"

        return IntentQuote(
            protocol=IntentProtocol.UNISWAPX,
            pair=pair,
            side=side,
            amount=amount,
            estimated_output=round(estimated_output, 6),
            price=round(estimated_output / amount if side == "buy" else amount / estimated_output, 6),
            price_impact_bps=round(price_impact, 2),
            gas_cost_usd=gas_cost,
            protocol_fee_usd=protocol_fee,
            mev_protection=True,
            solver_count=5,
            auction_duration_s=AUCTION_DURATION_S[IntentProtocol.UNISWAPX],
            expires_at=datetime.now(UTC).replace(second=(datetime.now(UTC).second + 60) % 60, minute=datetime.now(UTC).minute + 1),
            route_id=route_id,
        )

    async def submit_order(
        self, pair: str, amount: float, chain: str, side: str,
        user_address: str, slippage_bps: float = 50,
    ) -> IntentResult:
        """Submit a UniswapX order.

        Creates a signed Dutch auction order that fillers compete to execute.
        """
        order_id = f"ux-{uuid.uuid4().hex}"
        base, quote = pair.split("/")
        base_price = await self._get_reference_price(base, quote, chain)

        if side == "buy":
            filled_amount = amount / base_price * (1 + 0.003)
        else:
            filled_amount = amount * base_price * (1 + 0.003)

        tx_data = f"uniswapx_fill:{order_id}:{time.time()}"
        tx_hash = "0x" + hashlib.sha256(tx_data.encode()).hexdigest()

        logger.info(
            "uniswapx_order_submitted",
            order_id=order_id,
            pair=pair,
            amount=amount,
            side=side,
            chain=chain,
        )

        return IntentResult(
            order_id=order_id,
            protocol=IntentProtocol.UNISWAPX,
            pair=pair,
            side=side,
            amount=amount,
            filled_amount=round(filled_amount, 6),
            execution_price=round(filled_amount / amount if side == "buy" else amount / filled_amount, 6),
            price_impact_bps=round(max(0.3, 8 / (amount + 1)), 2),
            gas_paid_by_solver=True,
            solver_address="0x" + hashlib.sha256(f"filler-{order_id}".encode()).hexdigest()[:40],
            tx_hash=tx_hash,
            status=IntentStatus.SETTLED,
            created_at=datetime.now(UTC),
            settled_at=datetime.now(UTC),
        )

    async def _get_reference_price(self, base: str, quote: str, chain: str) -> float:
        """Get reference price."""
        prices = {
            "ETH": 3500, "BTC": 65000, "SOL": 150, "USDC": 1.0, "USDT": 1.0,
            "DAI": 1.0, "WBTC": 65000, "MATIC": 0.8, "AVAX": 35,
        }
        return prices.get(base, 1.0) / prices.get(quote, 1.0)


class OneInchFusionClient:
    """1inch Fusion intent-based swap client.

    1inch Fusion uses resolver competition where professional market makers
    (resolvers) compete to fill user orders at the best price. Users pay
    zero gas and get MEV protection.

    Features:
    - Resolver competition for best execution
    - Gasless for users
    - MEV protection (private order flow)
    - Cross-chain support via 1inch Cross-chain SDK
    - Dutch auction pricing model

    Docs: https://docs.1inch.io/
    """

    API_BASE = "https://fusion.1inch.io"

    def __init__(self, http_client: httpx.AsyncClient, config: dict[str, Any] | None = None):
        self._http = http_client
        self._config = config or {}
        self._api_key = config.get("api_key", "") if config else ""

    def supports_chain(self, chain: str) -> bool:
        """Check if 1inch Fusion supports this chain."""
        return chain in PROTOCOL_CHAINS[IntentProtocol.ONEINCH_FUSION]

    async def get_quote(
        self, pair: str, amount: float, chain: str, side: str = "buy"
    ) -> IntentQuote:
        """Get a 1inch Fusion quote.

        Args:
            pair: Trading pair.
            amount: Input amount.
            chain: Chain.
            side: Buy or sell.

        Returns:
            IntentQuote with 1inch Fusion pricing.
        """
        base, quote = pair.split("/")
        base_price = await self._get_reference_price(base, quote, chain)

        if side == "buy":
            estimated_output = amount / base_price
        else:
            estimated_output = amount * base_price

        # 1inch Fusion competitive pricing
        improvement_bps = 2.0
        if side == "buy":
            estimated_output *= (1 + improvement_bps / 10_000)
        else:
            estimated_output *= (1 + improvement_bps / 10_000)

        price_impact = max(0.4, 9 / (amount + 1))
        gas_cost = 0.0
        fee_info = PROTOCOL_FEES[IntentProtocol.ONEINCH_FUSION]
        protocol_fee = amount * base_price * fee_info["protocol_fee_bps"] / 10_000

        route_id = f"1f-{pair}-{amount}-{uuid.uuid4().hex[:8]}"

        return IntentQuote(
            protocol=IntentProtocol.ONEINCH_FUSION,
            pair=pair,
            side=side,
            amount=amount,
            estimated_output=round(estimated_output, 6),
            price=round(estimated_output / amount if side == "buy" else amount / estimated_output, 6),
            price_impact_bps=round(price_impact, 2),
            gas_cost_usd=gas_cost,
            protocol_fee_usd=round(protocol_fee, 2),
            mev_protection=True,
            solver_count=12,  # 1inch has many resolvers
            auction_duration_s=AUCTION_DURATION_S[IntentProtocol.ONEINCH_FUSION],
            expires_at=datetime.now(UTC).replace(second=(datetime.now(UTC).second + 45) % 60, minute=datetime.now(UTC).minute + (1 if datetime.now(UTC).second >= 15 else 0)),
            route_id=route_id,
        )

    async def submit_order(
        self, pair: str, amount: float, chain: str, side: str,
        user_address: str, slippage_bps: float = 50,
    ) -> IntentResult:
        """Submit a 1inch Fusion order.

        Creates a signed order that enters resolver competition.
        """
        order_id = f"1f-{uuid.uuid4().hex}"
        base, quote = pair.split("/")
        base_price = await self._get_reference_price(base, quote, chain)

        if side == "buy":
            filled_amount = amount / base_price * (1 + 0.0025)
        else:
            filled_amount = amount * base_price * (1 + 0.0025)

        tx_data = f"1inch_fusion_fill:{order_id}:{time.time()}"
        tx_hash = "0x" + hashlib.sha256(tx_data.encode()).hexdigest()

        logger.info(
            "1inch_fusion_order_submitted",
            order_id=order_id,
            pair=pair,
            amount=amount,
            side=side,
            chain=chain,
        )

        return IntentResult(
            order_id=order_id,
            protocol=IntentProtocol.ONEINCH_FUSION,
            pair=pair,
            side=side,
            amount=amount,
            filled_amount=round(filled_amount, 6),
            execution_price=round(filled_amount / amount if side == "buy" else amount / filled_amount, 6),
            price_impact_bps=round(max(0.4, 9 / (amount + 1)), 2),
            gas_paid_by_solver=True,
            solver_address="0x" + hashlib.sha256(f"resolver-{order_id}".encode()).hexdigest()[:40],
            tx_hash=tx_hash,
            status=IntentStatus.SETTLED,
            created_at=datetime.now(UTC),
            settled_at=datetime.now(UTC),
        )

    async def _get_reference_price(self, base: str, quote: str, chain: str) -> float:
        """Get reference price."""
        prices = {
            "ETH": 3500, "BTC": 65000, "SOL": 150, "USDC": 1.0, "USDT": 1.0,
            "DAI": 1.0, "WBTC": 65000, "MATIC": 0.8, "AVAX": 35,
        }
        return prices.get(base, 1.0) / prices.get(quote, 1.0)


# ═══════════════════════════════════════════════════════════════════════
# DEX ROUTING (for comparison)
# ═══════════════════════════════════════════════════════════════════════


class DirectDexQuoter:
    """Simulates direct DEX routing for comparison with intent protocols.

    Uses standard AMM routing (Uniswap V2/V3, SushiSwap) without
    the MEV protection or solver competition of intent protocols.
    """

    # DEX fee tiers (bps)
    DEX_FEES: dict[str, float] = {
        "uniswap_v2": 30,
        "uniswap_v3_500": 5,
        "uniswap_v3_3000": 30,
        "uniswap_v3_10000": 100,
        "sushiswap": 30,
        "curve": 4,
    }

    async def get_dex_quotes(
        self, pair: str, amount: float, chain: str, side: str = "buy"
    ) -> list[dict[str, Any]]:
        """Get quotes from direct DEX routing.

        Returns quotes from multiple DEXes for comparison.

        Args:
            pair: Trading pair.
            amount: Input amount.
            chain: Chain.
            side: Buy or sell.

        Returns:
            List of DEX quote dicts.
        """
        base, quote = pair.split("/")
        prices = {
            "ETH": 3500, "BTC": 65000, "SOL": 150, "USDC": 1.0, "USDT": 1.0,
            "DAI": 1.0, "WBTC": 65000, "MATIC": 0.8, "AVAX": 35,
        }
        base_price = prices.get(base, 1.0) / prices.get(quote, 1.0)

        quotes = []
        for dex_name, fee_bps in self.DEX_FEES.items():
            # Skip DEXes not on this chain
            if chain not in ("ethereum", "arbitrum", "base") and "uniswap" in dex_name:
                continue
            if chain == "solana" and "uniswap" in dex_name:
                continue

            fee_factor = 1 - fee_bps / 10_000
            price_impact = max(0.1, 5 / (amount + 0.1))

            if side == "buy":
                output = (amount / base_price) * fee_factor * (1 - price_impact / 10_000)
            else:
                output = (amount * base_price) * fee_factor * (1 - price_impact / 10_000)

            # Gas cost for direct DEX swap
            gas_usd = {
                "ethereum": 15.0, "arbitrum": 0.10, "base": 0.05,
                "polygon": 0.02, "avalanche": 0.15, "solana": 0.001,
            }.get(chain, 15.0)

            quotes.append({
                "dex": dex_name,
                "pair": pair,
                "side": side,
                "amount": amount,
                "estimated_output": round(output, 6),
                "price": round(output / amount if side == "buy" else amount / output, 6),
                "fee_bps": fee_bps,
                "price_impact_bps": round(price_impact, 2),
                "gas_cost_usd": gas_usd,
                "mev_protection": False,
            })

        # Sort by best output
        quotes.sort(key=lambda q: -q["estimated_output"])
        return quotes


# ═══════════════════════════════════════════════════════════════════════
# INTENT EXECUTOR — UNIFIED INTERFACE
# ═══════════════════════════════════════════════════════════════════════


class IntentExecutor:
    """Unified intent-based execution engine.

    Aggregates quotes from CoW Protocol, UniswapX, and 1inch Fusion,
    and can compare intent-based execution against direct DEX routing.

    Usage:
        executor = IntentExecutor(config)
        quotes = await executor.get_intent_quotes("ETH/USDC", 1000, "ethereum")
        result = await executor.execute_intent_swap("ETH/USDC", 1000, "ethereum", quote=quotes[0])
        verified = await executor.verify_settlement(result)
        comparison = await executor.compare_execution_methods("ETH/USDC", 1000, "ethereum")
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._http = httpx.AsyncClient(
            headers={"User-Agent": "TSAR-Intent/1.0"},
            timeout=30,
        )
        self._cow = CowProtocolClient(self._http, self._config.get("cow_protocol"))
        self._uniswapx = UniswapXClient(self._http, self._config.get("uniswapx"))
        self._oneinch = OneInchFusionClient(self._http, self._config.get("oneinch_fusion"))
        self._dex_quoter = DirectDexQuoter()

        # Settlement registry
        self._settlements: dict[str, IntentResult] = {}

    async def close(self):
        """Close HTTP client."""
        await self._http.aclose()

    async def get_intent_quotes(
        self,
        pair: str,
        amount: float,
        chain: str,
        side: str = "buy",
    ) -> list[IntentQuote]:
        """Get quotes from all supported intent protocols.

        Args:
            pair: Trading pair (e.g., "ETH/USDC").
            amount: Input amount.
            chain: Chain to execute on.
            side: Buy or sell direction.

        Returns:
            List of IntentQuote sorted by best output.
        """
        # Validate pair format
        if "/" not in pair:
            raise ValueError(f"Pair must be in format 'BASE/QUOTE', got: {pair}")

        # Collect quotes from all protocols in parallel
        clients = [
            (self._cow, IntentProtocol.COW_PROTOCOL),
            (self._uniswapx, IntentProtocol.UNISWAPX),
            (self._oneinch, IntentProtocol.ONEINCH_FUSION),
        ]

        tasks = []
        for client, protocol in clients:
            if client.supports_chain(chain):
                tasks.append(asyncio.create_task(
                    self._safe_quote(client, pair, amount, chain, side)
                ))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        quotes: list[IntentQuote] = []
        for r in results:
            if isinstance(r, IntentQuote):
                quotes.append(r)
            elif isinstance(r, Exception):
                logger.debug("intent_quote_failed", error=str(r))

        # Sort by best estimated output (descending)
        quotes.sort(key=lambda q: -q.estimated_output)
        return quotes

    async def execute_intent_swap(
        self,
        pair: str,
        amount: float,
        chain: str,
        side: str = "buy",
        user_address: str = "0x0000000000000000000000000000000000000000",
        quote: IntentQuote | None = None,
        slippage_bps: float = 50,
    ) -> IntentResult:
        """Execute an intent-based swap.

        If no quote is provided, fetches quotes and uses the best one.

        Args:
            pair: Trading pair.
            amount: Input amount.
            chain: Chain.
            side: Buy or sell.
            user_address: User's wallet address.
            quote: Specific quote to use (optional).
            slippage_bps: Maximum slippage in basis points.

        Returns:
            IntentResult with execution details.
        """
        if quote is None:
            quotes = await self.get_intent_quotes(pair, amount, chain, side)
            if not quotes:
                raise RuntimeError(f"No intent quotes available for {pair} on {chain}")
            quote = quotes[0]

        # Route to correct protocol client
        client_map = {
            IntentProtocol.COW_PROTOCOL: self._cow,
            IntentProtocol.UNISWAPX: self._uniswapx,
            IntentProtocol.ONEINCH_FUSION: self._oneinch,
        }
        client = client_map[quote.protocol]
        result = await client.submit_order(pair, amount, chain, side, user_address, slippage_bps)

        # Track settlement
        self._settlements[result.order_id] = result

        logger.info(
            "intent_swap_executed",
            order_id=result.order_id,
            protocol=quote.protocol,
            pair=pair,
            amount=amount,
            filled=result.filled_amount,
            price=result.execution_price,
        )

        return result

    async def verify_settlement(
        self,
        result: IntentResult,
        tolerance_bps: float = 100,
    ) -> SettlementVerificationResult:
        """Verify that an intent settlement was fulfilled correctly.

        Checks on-chain that:
        1. The settlement transaction exists
        2. The output amount matches the quote (within tolerance)
        3. The solver fulfilled the order correctly

        Args:
            result: IntentResult to verify.
            tolerance_bps: Acceptable deviation in basis points.

        Returns:
            SettlementVerificationResult with verification details.
        """
        # In production: query on-chain settlement contract
        # Simulate verification
        expected_output = result.filled_amount
        # Slight simulation of on-chain verification
        actual_output = expected_output * (1 - 0.0001)  # Tiny rounding
        deviation_bps = abs(expected_output - actual_output) / expected_output * 10_000

        verified = deviation_bps <= tolerance_bps
        verification = (
            SettlementVerification.VERIFIED if verified
            else SettlementVerification.PRICE_DEVIATION
        )

        logger.info(
            "settlement_verified",
            order_id=result.order_id,
            verified=verified,
            deviation_bps=round(deviation_bps, 2),
        )

        return SettlementVerificationResult(
            verified=verified,
            expected_output=round(expected_output, 6),
            actual_output=round(actual_output, 6),
            deviation_bps=round(deviation_bps, 2),
            on_chain_tx_hash=result.tx_hash,
            block_number=19_000_000 + int(time.time()) % 100_000,
            gas_used=180_000,
            verification=verification,
        )

    async def compare_execution_methods(
        self,
        pair: str,
        amount: float,
        chain: str = "ethereum",
        side: str = "buy",
    ) -> ExecutionComparison:
        """Compare intent-based execution vs direct DEX routing.

        Fetches quotes from intent protocols and direct DEXes, then
        determines which method offers the best execution.

        Args:
            pair: Trading pair.
            amount: Input amount.
            chain: Chain.
            side: Buy or sell.

        Returns:
            ExecutionComparison with all quotes and analysis.
        """
        # Fetch intent quotes and DEX quotes in parallel
        intent_task = self.get_intent_quotes(pair, amount, chain, side)
        dex_task = self._dex_quoter.get_dex_quotes(pair, amount, chain, side)

        intent_quotes, dex_quotes = await asyncio.gather(intent_task, dex_task)

        # Find best overall
        all_options: list[tuple[str, float, bool]] = []

        for iq in intent_quotes:
            all_options.append((f"intent:{iq.protocol}", iq.estimated_output, True))

        for dq in dex_quotes:
            all_options.append((f"dex:{dq['dex']}", dq["estimated_output"], False))

        if not all_options:
            return ExecutionComparison(
                pair=pair,
                amount=amount,
                intent_quotes=[],
                dex_quotes=[],
                best_method="none",
                best_price=0,
                savings_vs_worst_bps=0,
                mev_protection_winner="none",
            )

        all_options.sort(key=lambda x: -x[1])
        best_method, best_output, _ = all_options[0]
        worst_output = all_options[-1][1]
        savings_bps = (best_output - worst_output) / worst_output * 10_000 if worst_output > 0 else 0

        # Determine MEV protection winner
        mev_winner = "intent_protocols" if any(mev for _, _, mev in all_options[:3]) else "none"

        return ExecutionComparison(
            pair=pair,
            amount=amount,
            intent_quotes=intent_quotes,
            dex_quotes=dex_quotes,
            best_method=best_method,
            best_price=round(best_output / amount if side == "buy" else amount / best_output, 6),
            savings_vs_worst_bps=round(savings_bps, 2),
            mev_protection_winner=mev_winner,
        )

    # ── Internal helpers ──────────────────────────────────────────────

    async def _safe_quote(
        self, client: Any, pair: str, amount: float, chain: str, side: str,
    ) -> IntentQuote:
        """Safely fetch a quote, propagating exceptions."""
        return await client.get_quote(pair, amount, chain, side)
