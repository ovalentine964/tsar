"""
TSAR Domain Tools — MEV Protection & Oracle Verification.

Provides the agent-facing tool interface for MEV protection and
on-chain price verification.  Wraps the backend implementations
in ``src.backends.defi.mev_protection`` and
``src.backends.defi.oracle_client``.

Tools:
  - ``check_mev_risk(pair, amount)`` — Estimate MEV risk for a proposed swap
  - ``get_protected_quote(pair, amount)`` — Quote with MEV protection applied
  - ``verify_onchain_price(token)`` — Compare oracle price vs exchange price
  - ``get_gas_priority()`` — Recommended gas for fast/safe execution

Usage::

    from src.tools.mev_protection import MEVProtectionTools

    tools = MEVProtectionTools(rpc_url="https://eth-mainnet...")
    risk = await tools.check_mev_risk("WETH/USDC", 10.0)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from src.backends.defi.mev_protection import (
    MEVProtection,
    MEVRiskLevel,
)
from src.backends.defi.oracle_client import (
    OracleClient,
)
from src.tools import register_tool

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# TOOL RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MEVRiskResult:
    """Agent-facing result from check_mev_risk.

    Attributes:
        pair: Trading pair.
        amount: Swap amount.
        risk_level: Human-readable risk level.
        risk_score: Numeric risk 0-1.
        sandwich_detected: Whether sandwich attack is pending.
        bot_count: Number of detected MEV bots.
        recommended_method: How to submit the tx.
        estimated_loss_usd: Potential MEV loss if unprotected.
        priority_fee_gwei: Recommended priority fee.
        summary: One-line summary for the agent.
    """

    pair: str
    amount: float
    risk_level: str
    risk_score: float
    sandwich_detected: bool
    bot_count: int
    recommended_method: str
    estimated_loss_usd: float
    priority_fee_gwei: float
    summary: str


@dataclass(frozen=True)
class ProtectedQuoteResult:
    """Agent-facing result from get_protected_quote.

    Attributes:
        pair: Trading pair.
        input_amount: Input amount.
        output_amount: Expected output.
        price_impact_pct: Price impact.
        slippage_pct: Slippage tolerance.
        submission_method: How to submit.
        priority_fee_gwei: Priority fee.
        gas_estimate: Gas units.
        valid_for_seconds: Quote validity.
        summary: One-line summary.
    """

    pair: str
    input_amount: float
    output_amount: float
    price_impact_pct: float
    slippage_pct: float
    submission_method: str
    priority_fee_gwei: float
    gas_estimate: int
    valid_for_seconds: float
    summary: str


@dataclass(frozen=True)
class OnChainPriceResult:
    """Agent-facing result from verify_onchain_price.

    Attributes:
        token: Token/pair checked.
        oracle_price: Price from oracle.
        oracle_provider: Which oracle was used.
        exchange_price: Price from exchange (if provided).
        deviation_pct: Percentage deviation.
        deviation_severity: Severity level.
        is_stale: Whether oracle data is stale.
        recommendation: What the agent should do.
    """

    token: str
    oracle_price: float
    oracle_provider: str
    exchange_price: float | None
    deviation_pct: float | None
    deviation_severity: str | None
    is_stale: bool
    recommendation: str


@dataclass(frozen=True)
class GasPriorityResult:
    """Agent-facing result from get_gas_priority.

    Attributes:
        base_fee_gwei: Current base fee.
        low_gwei: Priority fee for non-urgent.
        medium_gwei: Priority fee for standard.
        high_gwei: Priority fee for fast.
        block_number: Current block.
        recommendation: Which tier to use and why.
    """

    base_fee_gwei: float
    low_gwei: float
    medium_gwei: float
    high_gwei: float
    block_number: int
    recommendation: str


# ═══════════════════════════════════════════════════════════════════════
# TOOL CLASS
# ═══════════════════════════════════════════════════════════════════════


class MEVProtectionTools:
    """Agent-facing MEV protection and oracle verification tools.

    Wraps the backend implementations into clean async methods that
    return structured, agent-friendly results.

    Args:
        rpc_url: Ethereum JSON-RPC endpoint.
        solana_rpc_url: Solana RPC endpoint (optional).
        flashbots_relay: Flashbots relay URL.
        jito_tip_lamports: Jito tip amount in lamports.
        chain: ``"ethereum"`` or ``"solana"``.
        pyth_hermes_url: Pyth Hermes API URL.
    """

    description = (
        "MEV protection, sandwich detection, oracle price verification, and gas optimization"
    )

    def __init__(
        self,
        rpc_url: str = "",
        solana_rpc_url: str = "",
        flashbots_relay: str = "https://relay.flashbots.net",
        jito_tip_lamports: int = 10_000,
        chain: str = "ethereum",
        pyth_hermes_url: str = "https://hermes.pyth.network",
    ) -> None:
        self._mev = MEVProtection(
            rpc_url=rpc_url,
            solana_rpc_url=solana_rpc_url,
            flashbots_relay=flashbots_relay,
            jito_tip_lamports=jito_tip_lamports,
            chain=chain,
        )
        self._oracle = OracleClient(
            rpc_url=rpc_url,
            pyth_hermes_url=pyth_hermes_url,
        )
        self._chain = chain

    async def close(self) -> None:
        """Clean up HTTP clients."""
        await self._mev.close()
        await self._oracle.close()

    # ── check_mev_risk ────────────────────────────────────────────────

    async def check_mev_risk(
        self,
        pair: str,
        amount: float,
    ) -> MEVRiskResult:
        """Estimate MEV risk for a proposed swap.

        Analyses the mempool for sandwich attacks, evaluates trade size,
        and recommends a submission method.

        Args:
            pair: Trading pair (e.g. "WETH/USDC").
            amount: Swap amount in base token.

        Returns:
            MEVRiskResult with risk assessment and recommendation.
        """
        assessment = await self._mev.check_mev_risk(pair, amount)

        if assessment.risk_level == MEVRiskLevel.CRITICAL:
            summary = (
                f"⚠️ CRITICAL MEV risk for {pair} swap of {amount}. "
                f"Sandwich attack detected ({assessment.sandwich_detected}). "
                f"Use {assessment.recommended_method.value} — estimated loss: "
                f"${assessment.estimated_mev_loss_usd:.2f}"
            )
        elif assessment.risk_level == MEVRiskLevel.HIGH:
            summary = (
                f"🔴 High MEV risk for {pair} swap of {amount}. "
                f"Use {assessment.recommended_method.value} to protect. "
                f"Estimated loss if unprotected: ${assessment.estimated_mev_loss_usd:.2f}"
            )
        elif assessment.risk_level == MEVRiskLevel.MEDIUM:
            summary = (
                f"🟡 Medium MEV risk for {pair} swap of {amount}. "
                f"Consider {assessment.recommended_method.value}."
            )
        else:
            summary = (
                f"🟢 Low MEV risk for {pair} swap of {amount}. Standard submission acceptable."
            )

        return MEVRiskResult(
            pair=assessment.pair,
            amount=assessment.amount,
            risk_level=assessment.risk_level.value,
            risk_score=assessment.risk_score,
            sandwich_detected=assessment.sandwich_detected,
            bot_count=len(assessment.pending_arbitrageurs),
            recommended_method=assessment.recommended_method.value,
            estimated_loss_usd=assessment.estimated_mev_loss_usd,
            priority_fee_gwei=assessment.gas_priority_gwei,
            summary=summary,
        )

    # ── get_protected_quote ───────────────────────────────────────────

    async def get_protected_quote(
        self,
        pair: str,
        amount: float,
        slippage_pct: float = 0.5,
    ) -> ProtectedQuoteResult:
        """Get a quote with MEV protection applied.

        Returns a slippage-adjusted quote with recommended submission
        method and gas parameters.

        Args:
            pair: Trading pair (e.g. "WETH/USDC").
            amount: Swap amount in base token.
            slippage_pct: Slippage tolerance (default 0.5%).

        Returns:
            ProtectedQuoteResult with the protected quote.
        """
        quote = await self._mev.get_protected_quote(pair, amount, slippage_pct)
        remaining = max(0, quote.valid_until - time.time())

        summary = (
            f"💱 {pair}: {amount} → {quote.output_amount:.6f} "
            f"(impact: {quote.price_impact_pct:.2f}%, "
            f"slippage: {slippage_pct}%, "
            f"via {quote.submission_method.value}, "
            f"valid {remaining:.0f}s)"
        )

        return ProtectedQuoteResult(
            pair=quote.pair,
            input_amount=quote.amount,
            output_amount=quote.output_amount,
            price_impact_pct=quote.price_impact_pct,
            slippage_pct=quote.slippage_tolerance_pct,
            submission_method=quote.submission_method.value,
            priority_fee_gwei=quote.priority_fee_gwei,
            gas_estimate=quote.gas_estimate,
            valid_for_seconds=remaining,
            summary=summary,
        )

    # ── verify_onchain_price ──────────────────────────────────────────

    async def verify_onchain_price(
        self,
        token: str,
        exchange_price: float | None = None,
    ) -> OnChainPriceResult:
        """Compare oracle price vs exchange price for a token.

        Fetches the best available oracle price (Chainlink or Pyth)
        and optionally compares it against a provided exchange price.

        Args:
            token: Token/pair (e.g. "ETH/USD", "BTC/USD").
            exchange_price: Optional CEX price to compare against.

        Returns:
            OnChainPriceResult with oracle price and deviation analysis.
        """
        # Normalize pair format
        pair = token.upper()
        if "/" not in pair:
            # Try common quote currencies
            for quote in ("USD", "USDT", "USDC"):
                candidate = f"{pair}/{quote}"
                if candidate in OracleClient.supported_pairs():
                    pair = candidate
                    break

        oracle_price = await self._oracle.get_best_price(pair)

        deviation_pct = None
        severity = None

        if exchange_price is not None:
            deviation = await self._oracle.check_price_deviation(pair, exchange_price)
            deviation_pct = deviation.deviation_pct
            severity = deviation.severity.value

        # Build recommendation
        if oracle_price.stale:
            recommendation = (
                f"⚠️ Oracle data for {pair} is stale "
                f"(last update: {time.time() - oracle_price.timestamp:.0f}s ago). "
                f"Consider using a different price source."
            )
        elif severity == "critical":
            recommendation = (
                f"🚨 CRITICAL deviation ({deviation_pct:.2f}%) between oracle "
                f"(${oracle_price.price:.2f}) and exchange (${exchange_price:.2f}). "
                f"Possible oracle manipulation or extreme market conditions. "
                f"DO NOT execute trade without investigation."
            )
        elif severity == "alert":
            recommendation = (
                f"⚠️ Significant deviation ({deviation_pct:.2f}%) between oracle "
                f"and exchange. Verify market conditions before trading."
            )
        elif severity == "warning":
            recommendation = (
                f"🟡 Minor deviation ({deviation_pct:.2f}%). Normal during volatile periods. "
                f"Proceed with caution."
            )
        else:
            recommendation = (
                f"✅ Oracle price ({oracle_price.provider.value}) is aligned with exchange."
            )

        return OnChainPriceResult(
            token=pair,
            oracle_price=oracle_price.price,
            oracle_provider=oracle_price.provider.value,
            exchange_price=exchange_price,
            deviation_pct=deviation_pct,
            deviation_severity=severity,
            is_stale=oracle_price.stale,
            recommendation=recommendation,
        )

    # ── get_gas_priority ──────────────────────────────────────────────

    async def get_gas_priority(self) -> GasPriorityResult:
        """Get recommended gas prices for different urgency levels.

        Returns EIP-1559 base fee and priority fee tiers for
        low/medium/high urgency transactions.

        Returns:
            GasPriorityResult with gas recommendations.
        """
        gas = await self._mev.get_gas_estimate()

        if gas.base_fee_gwei > 100:
            recommendation = (
                f"🔴 Very high base fee ({gas.base_fee_gwei} gwei). "
                f"Consider delaying non-urgent transactions. "
                f"For urgent txs, use {gas.high_priority_gwei} gwei priority."
            )
        elif gas.base_fee_gwei > 30:
            recommendation = (
                f"🟡 Elevated base fee ({gas.base_fee_gwei} gwei). "
                f"Standard: {gas.medium_priority_gwei} gwei, "
                f"Fast: {gas.high_priority_gwei} gwei."
            )
        else:
            recommendation = (
                f"🟢 Normal gas conditions. Base: {gas.base_fee_gwei} gwei. "
                f"Standard: {gas.medium_priority_gwei} gwei, "
                f"Fast: {gas.high_priority_gwei} gwei."
            )

        return GasPriorityResult(
            base_fee_gwei=gas.base_fee_gwei,
            low_gwei=gas.low_priority_gwei,
            medium_gwei=gas.medium_priority_gwei,
            high_gwei=gas.high_priority_gwei,
            block_number=gas.block_number,
            recommendation=recommendation,
        )


# ═══════════════════════════════════════════════════════════════════════
# REGISTER
# ═══════════════════════════════════════════════════════════════════════

register_tool("mev_protection", MEVProtectionTools)
