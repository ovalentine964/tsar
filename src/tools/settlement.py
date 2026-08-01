"""
TSAR Domain Tools — Settlement & L2 Optimization Tools.

What the agent USES for on-chain settlement and gas optimization.
Provides the tool interface for escrow settlement, chain selection,
gas monitoring, and transaction batching.

Tools:
  1. Create Escrow Trade       — Initiate on-chain escrow settlement
  2. Verify Settlement         — Confirm on-chain settlement execution
  3. Estimate Settlement Cost  — Gas + protocol fee estimation
  4. Get Optimal Chain         — Recommend L2 for execution
  5. Get Gas Prices            — Real-time gas across all chains
  6. Batch Transactions        — Combine multiple txs for gas savings
  7. Get Gas Trend             — EIP-1559 base fee trend analysis
  8. Optimize Priority Fee     — Dynamic priority fee recommendation
  9. Estimate Bridge Cost      — Cross-chain bridge cost analysis
  10. Compare Chains           — Full chain comparison with scoring

Usage:
    tools = SettlementTools()
    result = await tools.create_escrow_trade("ETH/USDT", 1.5, "0x...")
    chain = await tools.get_optimal_chain(10000, "medium")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from src.tools import register_tool

logger = logging.getLogger(__name__)


class SettlementTools:
    """
    Settlement & L2 optimization tool interface.

    Wraps SettlementEngine and L2Optimizer into a clean async API
    for agent consumption.
    """

    description = "On-chain settlement and L2 gas optimization tools"
    version = "1.0.0"

    def __init__(self):
        self._settlement_engine = None
        self._l2_optimizer = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Lazy initialization of backend engines."""
        if self._initialized:
            return

        try:
            from src.backends.defi.settlement import SettlementEngine
            from src.backends.defi.l2_optimizer import L2Optimizer

            self._settlement_engine = SettlementEngine()
            self._l2_optimizer = L2Optimizer()
            self._initialized = True
        except ImportError as e:
            logger.warning("Settlement backends not available: %s", e)

    # ───────────────────────────────────────────────────────────────────
    # Tool 1: Create Escrow Trade
    # ───────────────────────────────────────────────────────────────────

    async def create_escrow_trade(
        self,
        pair: str,
        amount: float,
        counterparty: str,
        price: float = 0.0,
        chain: str = "arbitrum",
    ) -> dict[str, Any]:
        """
        Create an escrow settlement for a trade.

        Initiates an atomic settlement via smart contract escrow.
        For large trades (>$100k), automatically requires multi-sig approval.

        Args:
            pair: Trading pair (e.g., "ETH/USDT", "BTC/USDT")
            amount: Trade amount in base asset units
            counterparty: Counterparty wallet address (0x...)
            price: Execution price in quote asset (for USD value calc)
            chain: Target chain: ethereum, polygon, arbitrum, optimism, base

        Returns:
            Dict with trade_id, tx_hash, status, chain, gas cost info

        Example:
            result = await tools.create_escrow_trade(
                "ETH/USDT", 5.0, "0x742d35Cc6634C0532925a3b844Bc9e7595f..."
            )
        """
        await self._ensure_initialized()

        if not self._settlement_engine:
            return {
                "success": False,
                "error": "Settlement engine not available",
            }

        try:
            from src.backends.defi.settlement import Chain

            chain_enum = Chain(chain.lower())
            result = await self._settlement_engine.create_escrow(
                pair=pair,
                amount=amount,
                counterparty=counterparty,
                price=price,
                chain=chain_enum,
            )

            return {
                "success": result.success,
                "trade_id": result.trade_id,
                "tx_hash": result.tx_hash,
                "status": result.status.value,
                "chain": chain,
                "confirmations": result.confirmations,
                "gas_used": result.gas_used,
                "error": result.error if not result.success else None,
            }

        except Exception as e:
            logger.error("create_escrow_trade failed: %s", e)
            return {"success": False, "error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 2: Verify Settlement
    # ───────────────────────────────────────────────────────────────────

    async def verify_settlement(self, tx_hash: str) -> dict[str, Any]:
        """
        Verify a settlement on-chain.

        Confirms the transaction was included and the escrow state
        matches expectations.

        Args:
            tx_hash: Transaction hash to verify (0x...)

        Returns:
            Dict with verification status, confirmations, block info

        Example:
            result = await tools.verify_settlement("0xabc123...")
        """
        await self._ensure_initialized()

        if not self._settlement_engine:
            return {"success": False, "error": "Settlement engine not available"}

        try:
            result = await self._settlement_engine.verify_settlement(tx_hash)
            return {
                "success": result.success,
                "trade_id": result.trade_id,
                "tx_hash": result.tx_hash,
                "status": result.status.value,
                "confirmations": result.confirmations,
                "escrow_valid": result.metadata.get("escrow_valid"),
                "error": result.error if not result.success else None,
            }

        except Exception as e:
            logger.error("verify_settlement failed: %s", e)
            return {"success": False, "error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 3: Estimate Settlement Cost
    # ───────────────────────────────────────────────────────────────────

    async def estimate_settlement_cost(
        self,
        chain: str = "arbitrum",
        trade_size: float = 0.0,
        gas_limit: int = 0,
    ) -> dict[str, Any]:
        """
        Estimate the full cost of a settlement on a chain.

        Returns gas cost, protocol fees, and cost as percentage of trade.

        Args:
            chain: Target chain
            trade_size: Trade size in USD (for percentage calculation)
            gas_limit: Custom gas limit (uses default if 0)

        Returns:
            Dict with gas cost breakdown in ETH and USD

        Example:
            cost = await tools.estimate_settlement_cost("arbitrum", 50000)
        """
        await self._ensure_initialized()

        if not self._l2_optimizer:
            return {"error": "L2 optimizer not available"}

        try:
            from src.backends.defi.l2_optimizer import Chain

            chain_enum = Chain(chain.lower())
            result = await self._l2_optimizer.estimate_transaction_cost(
                chain=chain_enum,
                gas_limit=gas_limit,
                trade_size_usd=trade_size,
            )
            return result

        except Exception as e:
            logger.error("estimate_settlement_cost failed: %s", e)
            return {"error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 4: Get Optimal Chain
    # ───────────────────────────────────────────────────────────────────

    async def get_optimal_chain(
        self,
        trade_size: float = 0.0,
        urgency: str = "medium",
        include_bridge_cost: bool = True,
    ) -> dict[str, Any]:
        """
        Recommend the optimal L2 chain for trade execution.

        Scores chains on cost, speed, and reliability weighted by urgency.
        Factors in bridge costs when assets need to move between chains.

        Args:
            trade_size: Trade size in USD
            urgency: "low" (minimize cost), "medium" (balanced),
                     "high" (speed matters), "critical" (fastest)
            include_bridge_cost: Include L1→L2 bridge costs

        Returns:
            Dict with recommended chain, score, costs, and reasoning

        Example:
            rec = await tools.get_optimal_chain(10000, "medium")
            print(rec["chain"])  # "arbitrum"
        """
        await self._ensure_initialized()

        if not self._l2_optimizer:
            return {"error": "L2 optimizer not available"}

        try:
            result = await self._l2_optimizer.get_optimal_chain(
                trade_size=trade_size,
                urgency=urgency,
                include_bridge_cost=include_bridge_cost,
            )

            return {
                "chain": result.chain.value,
                "score": result.score,
                "estimated_cost_usd": result.estimated_cost_usd,
                "estimated_time_s": result.estimated_time_s,
                "bridge_cost_usd": result.bridge_cost_usd,
                "total_cost_usd": result.total_cost_usd,
                "reason": result.reason,
            }

        except Exception as e:
            logger.error("get_optimal_chain failed: %s", e)
            return {"error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 5: Get Gas Prices
    # ───────────────────────────────────────────────────────────────────

    async def get_gas_prices(self) -> dict[str, Any]:
        """
        Get real-time gas prices across all supported chains.

        Returns base fee, priority fee, max fee, and USD cost estimates
        for Ethereum, Polygon, Arbitrum, Optimism, and Base.

        Returns:
            Dict mapping chain names to gas price info

        Example:
            prices = await tools.get_gas_prices()
            print(prices["arbitrum"]["estimated_cost_usd"])  # 0.12
        """
        await self._ensure_initialized()

        if not self._l2_optimizer:
            return {"error": "L2 optimizer not available"}

        try:
            all_prices = await self._l2_optimizer.get_all_gas_prices()
            result = {}
            for chain, gas in all_prices.items():
                result[chain.value] = {
                    "base_fee_gwei": round(gas.base_fee / 1e9, 4),
                    "priority_fee_gwei": round(gas.priority_fee / 1e9, 4),
                    "max_fee_gwei": round(gas.max_fee / 1e9, 4),
                    "gas_price_legacy_gwei": round(gas.gas_price_legacy / 1e9, 4),
                    "estimated_cost_usd": gas.estimated_cost_usd,
                    "utilization_pct": round(gas.utilization * 100, 1),
                    "block_number": gas.block_number,
                }
            return result

        except Exception as e:
            logger.error("get_gas_prices failed: %s", e)
            return {"error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 6: Batch Transactions
    # ───────────────────────────────────────────────────────────────────

    async def batch_transactions(
        self,
        transactions: list[dict[str, Any]],
        chain: str = "",
    ) -> dict[str, Any]:
        """
        Combine multiple transactions into a single batch for gas savings.

        Uses Multicall3 or custom batch contract to reduce per-tx overhead
        by ~35%. Auto-selects cheapest chain if not specified.

        Args:
            transactions: List of tx dicts with 'to', 'data', 'value' keys
            chain: Target chain (auto-selected if empty)

        Returns:
            Dict with batch_id, chain, gas estimate, savings info

        Example:
            batch = await tools.batch_transactions([
                {"to": "0x...", "data": "0x...", "value": 0},
                {"to": "0x...", "data": "0x...", "value": 1000},
            ])
        """
        await self._ensure_initialized()

        if not self._l2_optimizer:
            return {"error": "L2 optimizer not available"}

        try:
            from src.backends.defi.l2_optimizer import Chain as L2Chain

            chain_enum = L2Chain(chain.lower()) if chain else None
            result = await self._l2_optimizer.batch_transactions(
                transactions=transactions,
                chain=chain_enum,
            )

            return {
                "batch_id": result.batch_id,
                "chain": result.chain.value,
                "transaction_count": len(result.transactions),
                "total_gas_estimate": result.total_gas_estimate,
                "estimated_cost_usd": result.estimated_cost_usd,
                "gas_savings_pct": result.gas_savings_pct,
            }

        except Exception as e:
            logger.error("batch_transactions failed: %s", e)
            return {"error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 7: Get Gas Trend (bonus)
    # ───────────────────────────────────────────────────────────────────

    async def get_gas_trend(
        self, chain: str = "ethereum"
    ) -> dict[str, Any]:
        """
        Get EIP-1559 base fee trend for a chain.

        Returns current, average, and percentile base fees
        plus a trend direction (rising/falling/stable).

        Args:
            chain: Chain to query

        Returns:
            Dict with base fee stats and trend direction
        """
        await self._ensure_initialized()

        if not self._l2_optimizer:
            return {"error": "L2 optimizer not available"}

        try:
            from src.backends.defi.l2_optimizer import Chain as L2Chain

            chain_enum = L2Chain(chain.lower())
            return await self._l2_optimizer.get_base_fee_trend(chain_enum)

        except Exception as e:
            logger.error("get_gas_trend failed: %s", e)
            return {"error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 8: Optimize Priority Fee (bonus)
    # ───────────────────────────────────────────────────────────────────

    async def optimize_priority_fee(
        self, chain: str = "ethereum", urgency: str = "medium"
    ) -> dict[str, Any]:
        """
        Calculate optimal priority fee based on network congestion.

        Adjusts the priority fee dynamically based on current block
        utilization and desired confirmation speed.

        Args:
            chain: Target chain
            urgency: "low", "medium", "high", "critical"

        Returns:
            Dict with suggested priority fee and congestion info
        """
        await self._ensure_initialized()

        if not self._l2_optimizer:
            return {"error": "L2 optimizer not available"}

        try:
            return await self._l2_optimizer.optimize_priority_fee(
                chain=chain, urgency=urgency
            )

        except Exception as e:
            logger.error("optimize_priority_fee failed: %s", e)
            return {"error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 9: Estimate Bridge Cost (bonus)
    # ───────────────────────────────────────────────────────────────────

    async def estimate_bridge_cost(
        self,
        source: str = "ethereum",
        destination: str = "arbitrum",
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """
        Estimate the cost of bridging assets between chains.

        Includes source gas, bridge protocol fee, and destination claim gas.

        Args:
            source: Source chain
            destination: Destination chain
            amount_usd: Amount being bridged (for fee % calculation)

        Returns:
            Dict with cost breakdown for the bridge operation
        """
        await self._ensure_initialized()

        if not self._l2_optimizer:
            return {"error": "L2 optimizer not available"}

        try:
            from src.backends.defi.l2_optimizer import Chain as L2Chain

            src = L2Chain(source.lower())
            dst = L2Chain(destination.lower())
            return await self._l2_optimizer.estimate_bridge_cost(
                source=src, destination=dst, amount_usd=amount_usd
            )

        except Exception as e:
            logger.error("estimate_bridge_cost failed: %s", e)
            return {"error": str(e)}

    # ───────────────────────────────────────────────────────────────────
    # Tool 10: Compare Chains (bonus)
    # ───────────────────────────────────────────────────────────────────

    async def compare_chains(
        self,
        trade_size: float = 0.0,
        urgency: str = "medium",
    ) -> dict[str, Any]:
        """
        Compare all supported chains with detailed scoring.

        Returns a ranked list of chains with cost, speed, and
        reliability scores weighted by urgency.

        Args:
            trade_size: Trade size in USD
            urgency: "low", "medium", "high", "critical"

        Returns:
            Dict with ranked chain comparisons
        """
        await self._ensure_initialized()

        if not self._l2_optimizer:
            return {"error": "L2 optimizer not available"}

        try:
            from src.backends.defi.l2_optimizer import Urgency

            urgency_enum = Urgency(urgency.lower())
            recs = await self._l2_optimizer.compare_chains(
                trade_size=trade_size, urgency=urgency_enum
            )

            return {
                "chains": [
                    {
                        "chain": r.chain.value,
                        "score": r.score,
                        "estimated_cost_usd": r.estimated_cost_usd,
                        "estimated_time_s": r.estimated_time_s,
                        "bridge_cost_usd": r.bridge_cost_usd,
                        "total_cost_usd": r.total_cost_usd,
                        "reason": r.reason,
                    }
                    for r in recs
                ],
                "recommended": recs[0].chain.value if recs else None,
            }

        except Exception as e:
            logger.error("compare_chains failed: %s", e)
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# REGISTER
# ═══════════════════════════════════════════════════════════════════════

try:
    register_tool("settlement", SettlementTools)
except Exception:
    pass  # Will be registered via __init__.py lazy import
