"""
TSAR Domain Tools — Cross-Chain & Intent Protocol Tools.

What the agent BRIDGES and INTENDS. Provides cross-chain token transfers
and intent-based trading execution that finds optimal routes automatically.

Tools:
  1. Bridge Tokens             — Execute cross-chain token transfers
  2. Get Bridge Quotes         — Compare bridge options (cheapest/fastest/most reliable)
  3. Get Bridge Status         — Monitor bridge transfer progress
  4. Execute Intent Swap       — Intent-based swap (MEV-protected, gasless)
  5. Compare Execution Methods — Compare direct DEX vs intent vs bridge routes

All tools are async and delegate to BridgeClient and IntentExecutor.
Results use shared types from the respective backends.

Usage:
    tools = CrossChainTools(config)
    quotes = await tools.get_bridge_quotes("ethereum", "arbitrum", "USDC", 1000)
    tx = await tools.bridge_tokens("ethereum", "arbitrum", "USDC", 1000, ...)
    result = await tools.execute_intent_swap("ETH/USDC", 1000, "ethereum")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.backends.defi.bridge_client import (
    BridgeClient,
    BridgeQuote,
    BridgeStatus,
    BridgeTx,
    BridgeTxStatus,
    Chain,
    RoutePreference,
)
from src.backends.defi.intent_executor import (
    ExecutionComparison,
    IntentExecutor,
    IntentQuote,
    IntentResult,
    SettlementVerificationResult,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BridgeTokensResult:
    """Result of executing a cross-chain bridge transfer.

    Attributes:
        success: Whether the bridge was initiated successfully.
        tx_hash: Source chain transaction hash.
        protocol: Bridge protocol used.
        from_chain: Source chain.
        to_chain: Destination chain.
        token: Token bridged.
        amount: Amount bridged.
        estimated_amount_out: Expected amount on destination.
        fee_amount: Bridge fee.
        estimated_time_s: Estimated completion time.
        explorer_url: Block explorer link.
        error: Error message if failed.
    """
    success: bool
    tx_hash: str
    protocol: str
    from_chain: str
    to_chain: str
    token: str
    amount: float
    estimated_amount_out: float
    fee_amount: float
    estimated_time_s: float
    explorer_url: str = ""
    error: str | None = None


@dataclass(frozen=True)
class BridgeQuotesResult:
    """Result of comparing bridge options.

    Attributes:
        from_chain: Source chain.
        to_chain: Destination chain.
        token: Token being bridged.
        amount: Amount to bridge.
        quotes: List of bridge quotes sorted by preference.
        best_quote: The top-ranked quote.
        savings_vs_worst_bps: Savings of best vs worst in bps.
        recommendation: Human-readable recommendation.
    """
    from_chain: str
    to_chain: str
    token: str
    amount: float
    quotes: list[BridgeQuote]
    best_quote: BridgeQuote | None = None
    savings_vs_worst_bps: float = 0.0
    recommendation: str = ""


@dataclass(frozen=True)
class BridgeStatusResult:
    """Result of checking bridge transfer status.

    Attributes:
        tx_hash: Source transaction hash.
        status: Current status.
        source_confirmed: Whether source chain confirmed.
        destination_confirmed: Whether destination chain confirmed.
        confirmations: Number of confirmations.
        estimated_remaining_s: Seconds until completion.
        dest_tx_hash: Destination tx hash (if complete).
        error_message: Error details if failed.
    """
    tx_hash: str
    status: str
    source_confirmed: bool
    destination_confirmed: bool
    confirmations: int
    estimated_remaining_s: float | None
    dest_tx_hash: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class IntentSwapResult:
    """Result of executing an intent-based swap.

    Attributes:
        success: Whether the swap was executed.
        order_id: Intent order ID.
        protocol: Intent protocol used.
        pair: Trading pair.
        side: Buy or sell.
        amount: Input amount.
        filled_amount: Amount received.
        execution_price: Actual execution price.
        price_impact_bps: Realized price impact.
        gas_paid_by_solver: Whether solver paid gas.
        tx_hash: Settlement transaction hash.
        mev_protected: Whether MEV protection was active.
        error: Error message if failed.
    """
    success: bool
    order_id: str
    protocol: str
    pair: str
    side: str
    amount: float
    filled_amount: float
    execution_price: float
    price_impact_bps: float
    gas_paid_by_solver: bool
    tx_hash: str
    mev_protected: bool = True
    error: str | None = None


@dataclass(frozen=True)
class ExecutionComparisonResult:
    """Result of comparing execution methods.

    Attributes:
        pair: Trading pair.
        amount: Input amount.
        chain: Chain.
        intent_quotes: Quotes from intent protocols.
        dex_quotes: Quotes from direct DEX routing.
        best_method: Best execution method.
        best_price: Best price found.
        savings_vs_worst_bps: Savings in bps.
        mev_protection_winner: Which approach has MEV protection.
        recommendation: Human-readable recommendation.
    """
    pair: str
    amount: float
    chain: str
    intent_quotes: list[IntentQuote]
    dex_quotes: list[dict[str, Any]]
    best_method: str
    best_price: float
    savings_vs_worst_bps: float
    mev_protection_winner: str
    recommendation: str = ""


# ═══════════════════════════════════════════════════════════════════════
# CROSS-CHAIN TOOLS
# ═══════════════════════════════════════════════════════════════════════


class CrossChainTools:
    """Cross-chain and intent protocol tools for TSAR agents.

    Provides a unified interface for:
    - Cross-chain token transfers (Wormhole, LayerZero, Axelar)
    - Intent-based swaps (CoW Protocol, UniswapX, 1inch Fusion)
    - Execution method comparison (intent vs DEX vs CEX)

    Usage:
        tools = CrossChainTools(config)

        # Cross-chain bridging
        quotes = await tools.get_bridge_quotes("ethereum", "arbitrum", "USDC", 1000)
        tx = await tools.bridge_tokens("ethereum", "arbitrum", "USDC", 1000, ...)
        status = await tools.get_bridge_status(tx.tx_hash)

        # Intent-based swaps
        result = await tools.execute_intent_swap("ETH/USDC", 1000, "ethereum")
        verified = await tools.verify_intent_settlement(result)

        # Comparison
        comparison = await tools.compare_execution_methods("ETH/USDC", 1000, "ethereum")
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        bridge_config = self._config.get("bridge", {})
        intent_config = self._config.get("intent", {})

        self._bridge_client = BridgeClient(bridge_config)
        self._intent_executor = IntentExecutor(intent_config)

    async def close(self):
        """Close underlying clients."""
        await self._bridge_client.close()
        await self._intent_executor.close()

    # ── Cross-Chain Bridging ──────────────────────────────────────────

    async def bridge_tokens(
        self,
        from_chain: str,
        to_chain: str,
        token: str,
        amount: float,
        sender_address: str = "0x0000000000000000000000000000000000000000",
        recipient_address: str = "0x0000000000000000000000000000000000000000",
        preference: str = "cheapest",
    ) -> BridgeTokensResult:
        """Execute a cross-chain token transfer.

        Finds the best bridge route based on preference and initiates
        the transfer. Supports Wormhole, LayerZero, and Axelar.

        Args:
            from_chain: Source chain (ethereum, solana, polygon, arbitrum, base, avalanche).
            to_chain: Destination chain.
            token: Token symbol (e.g., "USDC", "ETH").
            amount: Amount to transfer.
            sender_address: Sender wallet on source chain.
            recipient_address: Recipient wallet on destination chain.
            preference: Route preference — "cheapest", "fastest", or "most_reliable".

        Returns:
            BridgeTokensResult with transfer details.

        Example:
            result = await tools.bridge_tokens(
                from_chain="ethereum",
                to_chain="arbitrum",
                token="USDC",
                amount=1000,
                preference="cheapest",
            )
        """
        try:
            pref = RoutePreference(preference)
        except ValueError:
            pref = RoutePreference.CHEAPEST

        try:
            # Get best quote
            quotes = await self._bridge_client.get_bridge_quotes(
                from_chain, to_chain, token, amount, pref
            )
            if not quotes:
                return BridgeTokensResult(
                    success=False,
                    tx_hash="",
                    protocol="",
                    from_chain=from_chain,
                    to_chain=to_chain,
                    token=token,
                    amount=amount,
                    estimated_amount_out=0,
                    fee_amount=0,
                    estimated_time_s=0,
                    error=f"No bridge routes available for {from_chain} → {to_chain}",
                )

            best_quote = quotes[0]

            # Execute bridge
            tx = await self._bridge_client.bridge_tokens(
                from_chain=from_chain,
                to_chain=to_chain,
                token=token,
                amount=amount,
                sender_address=sender_address,
                recipient_address=recipient_address,
                quote=best_quote,
            )

            return BridgeTokensResult(
                success=True,
                tx_hash=tx.tx_hash,
                protocol=tx.protocol,
                from_chain=from_chain,
                to_chain=to_chain,
                token=token,
                amount=amount,
                estimated_amount_out=best_quote.estimated_amount_out,
                fee_amount=best_quote.fee_amount,
                estimated_time_s=best_quote.estimated_time_s,
                explorer_url=tx.source_explorer_url,
            )

        except Exception as e:
            logger.error("bridge_tokens_failed", error=str(e))
            return BridgeTokensResult(
                success=False,
                tx_hash="",
                protocol="",
                from_chain=from_chain,
                to_chain=to_chain,
                token=token,
                amount=amount,
                estimated_amount_out=0,
                fee_amount=0,
                estimated_time_s=0,
                error=str(e),
            )

    async def get_bridge_quotes(
        self,
        from_chain: str,
        to_chain: str,
        token: str,
        amount: float,
        preference: str = "cheapest",
    ) -> BridgeQuotesResult:
        """Compare bridge options across all supported protocols.

        Fetches quotes from Wormhole, LayerZero, and Axelar, then
        ranks them by the given preference.

        Args:
            from_chain: Source chain.
            to_chain: Destination chain.
            token: Token symbol.
            amount: Amount to bridge.
            preference: Ranking preference — "cheapest", "fastest", "most_reliable".

        Returns:
            BridgeQuotesResult with all quotes and recommendation.

        Example:
            result = await tools.get_bridge_quotes("ethereum", "arbitrum", "USDC", 1000)
            for quote in result.quotes:
                print(f"{quote.protocol}: {quote.estimated_amount_out} USDC, "
                      f"fee={quote.fee_amount}, time={quote.estimated_time_s}s")
        """
        try:
            pref = RoutePreference(preference)
        except ValueError:
            pref = RoutePreference.CHEAPEST

        try:
            quotes = await self._bridge_client.get_bridge_quotes(
                from_chain, to_chain, token, amount, pref
            )

            best_quote = quotes[0] if quotes else None
            worst_output = quotes[-1].estimated_amount_out if quotes else 0
            savings_bps = 0.0
            if best_quote and worst_output > 0:
                savings_bps = (best_quote.estimated_amount_out - worst_output) / worst_output * 10_000

            # Generate recommendation
            recommendation = ""
            if best_quote:
                recommendation = (
                    f"Use {best_quote.protocol} for {from_chain} → {to_chain} "
                    f"({token} {amount:,.2f}). "
                    f"Estimated output: {best_quote.estimated_amount_out:,.6f} {token}, "
                    f"fee: {best_quote.fee_amount:,.6f} {token} ({best_quote.fee_bps:.0f} bps), "
                    f"time: ~{best_quote.estimated_time_s:.0f}s, "
                    f"gas: ${best_quote.gas_cost_usd:.2f}"
                )

            return BridgeQuotesResult(
                from_chain=from_chain,
                to_chain=to_chain,
                token=token,
                amount=amount,
                quotes=quotes,
                best_quote=best_quote,
                savings_vs_worst_bps=round(savings_bps, 2),
                recommendation=recommendation,
            )

        except Exception as e:
            logger.error("get_bridge_quotes_failed", error=str(e))
            return BridgeQuotesResult(
                from_chain=from_chain,
                to_chain=to_chain,
                token=token,
                amount=amount,
                quotes=[],
            )

    async def get_bridge_status(self, tx_hash: str) -> BridgeStatusResult:
        """Monitor bridge transfer progress.

        Checks the status of a pending cross-chain transfer across
        all bridge protocols.

        Args:
            tx_hash: Source chain transaction hash.

        Returns:
            BridgeStatusResult with current progress.

        Example:
            status = await tools.get_bridge_status("0xabc123...")
            print(f"Status: {status.status}")
            if status.destination_confirmed:
                print(f"Completed! Dest tx: {status.dest_tx_hash}")
        """
        try:
            status = await self._bridge_client.get_bridge_status(tx_hash)

            return BridgeStatusResult(
                tx_hash=tx_hash,
                status=status.status,
                source_confirmed=status.source_confirmed,
                destination_confirmed=status.destination_confirmed,
                confirmations=status.confirmations,
                estimated_remaining_s=status.estimated_remaining_s,
                dest_tx_hash=status.dest_tx_hash,
                error_message=status.error_message,
            )

        except Exception as e:
            logger.error("get_bridge_status_failed", error=str(e))
            return BridgeStatusResult(
                tx_hash=tx_hash,
                status=BridgeTxStatus.FAILED,
                source_confirmed=False,
                destination_confirmed=False,
                confirmations=0,
                estimated_remaining_s=None,
                error_message=str(e),
            )

    # ── Intent-Based Execution ────────────────────────────────────────

    async def execute_intent_swap(
        self,
        pair: str,
        amount: float,
        chain: str = "ethereum",
        side: str = "buy",
        user_address: str = "0x0000000000000000000000000000000000000000",
        slippage_bps: float = 50,
    ) -> IntentSwapResult:
        """Execute an intent-based swap.

        Submits an intent to CoW Protocol, UniswapX, or 1inch Fusion.
        Solvers/resolvers compete to fill the order at the best price.
        Users get MEV protection and gasless execution.

        Args:
            pair: Trading pair (e.g., "ETH/USDC", "WBTC/ETH").
            amount: Input amount.
            chain: Chain to execute on (ethereum, arbitrum, base).
            side: Buy or sell direction.
            user_address: User's wallet address.
            slippage_bps: Maximum acceptable slippage in basis points.

        Returns:
            IntentSwapResult with execution details.

        Example:
            result = await tools.execute_intent_swap(
                pair="ETH/USDC",
                amount=1000,
                chain="ethereum",
                side="buy",
            )
            print(f"Filled: {result.filled_amount} ETH at {result.execution_price}")
            print(f"MEV protected: {result.mev_protected}")
        """
        try:
            # Get best quote first
            quotes = await self._intent_executor.get_intent_quotes(
                pair, amount, chain, side
            )
            if not quotes:
                return IntentSwapResult(
                    success=False,
                    order_id="",
                    protocol="",
                    pair=pair,
                    side=side,
                    amount=amount,
                    filled_amount=0,
                    execution_price=0,
                    price_impact_bps=0,
                    gas_paid_by_solver=False,
                    tx_hash="",
                    error=f"No intent quotes available for {pair} on {chain}",
                )

            best_quote = quotes[0]

            # Execute intent swap
            result = await self._intent_executor.execute_intent_swap(
                pair=pair,
                amount=amount,
                chain=chain,
                side=side,
                user_address=user_address,
                quote=best_quote,
                slippage_bps=slippage_bps,
            )

            return IntentSwapResult(
                success=True,
                order_id=result.order_id,
                protocol=result.protocol,
                pair=pair,
                side=side,
                amount=amount,
                filled_amount=result.filled_amount,
                execution_price=result.execution_price,
                price_impact_bps=result.price_impact_bps,
                gas_paid_by_solver=result.gas_paid_by_solver,
                tx_hash=result.tx_hash,
                mev_protected=True,
            )

        except Exception as e:
            logger.error("execute_intent_swap_failed", error=str(e))
            return IntentSwapResult(
                success=False,
                order_id="",
                protocol="",
                pair=pair,
                side=side,
                amount=amount,
                filled_amount=0,
                execution_price=0,
                price_impact_bps=0,
                gas_paid_by_solver=False,
                tx_hash="",
                error=str(e),
            )

    async def verify_intent_settlement(
        self,
        result: IntentResult,
        tolerance_bps: float = 100,
    ) -> SettlementVerificationResult:
        """Verify on-chain that an intent was fulfilled correctly.

        Checks the settlement transaction on-chain to confirm:
        1. The output amount matches the quote
        2. The solver fulfilled the order
        3. No price deviation beyond tolerance

        Args:
            result: IntentResult to verify.
            tolerance_bps: Acceptable deviation in basis points.

        Returns:
            SettlementVerificationResult with verification details.
        """
        return await self._intent_executor.verify_settlement(result, tolerance_bps)

    async def compare_execution_methods(
        self,
        pair: str,
        amount: float,
        chain: str = "ethereum",
        side: str = "buy",
    ) -> ExecutionComparisonResult:
        """Compare direct DEX vs intent-based vs CEX execution.

        Fetches quotes from:
        - Intent protocols (CoW, UniswapX, 1inch Fusion)
        - Direct DEX routing (Uniswap V2/V3, SushiSwap, Curve)

        And determines which offers the best execution, factoring in
        gas costs, MEV protection, and price improvement.

        Args:
            pair: Trading pair (e.g., "ETH/USDC").
            amount: Input amount.
            chain: Chain to execute on.
            side: Buy or sell direction.

        Returns:
            ExecutionComparisonResult with all quotes and analysis.

        Example:
            comparison = await tools.compare_execution_methods("ETH/USDC", 1000, "ethereum")
            print(f"Best method: {comparison.best_method}")
            print(f"Best price: {comparison.best_price}")
            print(f"Savings: {comparison.savings_vs_worst_bps:.1f} bps")
            print(f"Recommendation: {comparison.recommendation}")
        """
        try:
            comparison = await self._intent_executor.compare_execution_methods(
                pair, amount, chain, side
            )

            # Generate recommendation
            recommendation = ""
            if comparison.best_method:
                method_type = comparison.best_method.split(":")[0]
                if method_type == "intent":
                    recommendation = (
                        f"Intent-based execution recommended for {pair} ({amount:,.2f}). "
                        f"Best: {comparison.best_method} at {comparison.best_price}. "
                        f"Savings: {comparison.savings_vs_worst_bps:.1f} bps vs worst option. "
                        f"MEV protection: {comparison.mev_protection_winner}."
                    )
                else:
                    recommendation = (
                        f"Direct DEX routing may be sufficient for {pair} ({amount:,.2f}). "
                        f"Best: {comparison.best_method} at {comparison.best_price}. "
                        f"Consider intent protocols for MEV protection on larger orders."
                    )

            return ExecutionComparisonResult(
                pair=pair,
                amount=amount,
                chain=chain,
                intent_quotes=comparison.intent_quotes,
                dex_quotes=comparison.dex_quotes,
                best_method=comparison.best_method,
                best_price=comparison.best_price,
                savings_vs_worst_bps=comparison.savings_vs_worst_bps,
                mev_protection_winner=comparison.mev_protection_winner,
                recommendation=recommendation,
            )

        except Exception as e:
            logger.error("compare_execution_methods_failed", error=str(e))
            return ExecutionComparisonResult(
                pair=pair,
                amount=amount,
                chain=chain,
                intent_quotes=[],
                dex_quotes=[],
                best_method="error",
                best_price=0,
                savings_vs_worst_bps=0,
                mev_protection_winner="none",
                recommendation=f"Error comparing methods: {e}",
            )

    # ── Utility ───────────────────────────────────────────────────────

    def get_supported_chains(self) -> list[str]:
        """Get list of supported chains for bridging."""
        return self._bridge_client.get_supported_chains()

    def get_supported_bridge_routes(self) -> dict[str, list]:
        """Get all supported bridge routes by protocol."""
        return self._bridge_client.get_supported_routes()
