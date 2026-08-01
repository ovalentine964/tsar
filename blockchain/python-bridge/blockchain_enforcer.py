"""
TSAR Blockchain Rules Enforcement — Integration with RiskGovernor

This module shows how the on-chain enforcement layer integrates
with TSAR's existing off-chain RiskGovernor (7-layer veto protocol).

ARCHITECTURE:
  Python (off-chain) → PyO3 → Rust → ethers-rs → Polygon

DUAL ENFORCEMENT:
  1. Python RiskGovernor checks rules (fast path, ~0.1ms)
  2. Smart contract verifies enforcement (trust layer, ~2s)
  3. Both must agree for a trade to proceed
  4. On-chain has final authority (cannot be bypassed)

INTEGRATION POINTS:
  - Layer 1 (Kill Switch): On-chain kill switch is authoritative
  - Layer 6 (Circuit Breaker): On-chain circuit breaker levels
  - Layer 7 (Position Limits): On-chain position limit enforcement
  - All layers: Audit trail logging
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from .blockchain_client import (
    BlockchainClient,
    EnforcementAction,
    RiskCheckRecord,
    RiskCheckResult,
    RuleEnforcementRecord,
    TradeRecord,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════


@dataclass
class DualEnforcementResult:
    """Result of dual enforcement check (off-chain + on-chain)."""

    approved: bool
    off_chain_approved: bool
    on_chain_approved: bool
    reason: str
    veto_layer: str = ""


# ═══════════════════════════════════════════════════════════════════
# BLOCKCHAIN ENFORCER
# ═══════════════════════════════════════════════════════════════════


class BlockchainEnforcer:
    """
    On-chain rules enforcement bridge.

    Integrates with TSAR's existing RiskGovernor to add a trust layer.
    The enforcer ensures that risk rules are enforced BOTH off-chain
    (Python, fast) AND on-chain (Solidity, trustless).

    USAGE:
        enforcer = BlockchainEnforcer(
            client=blockchain_client,
            risk_governor=risk_governor,
        )

        # Pre-trade check (dual enforcement)
        result = await enforcer.pre_trade_check(signal, portfolio)
        if not result.approved:
            raise RiskViolationError(result.reason)

        # Post-trade recording (audit trail)
        await enforcer.record_trade_execution(trade)
    """

    def __init__(
        self,
        client: BlockchainClient,
        risk_governor: Any = None,
    ):
        """
        Initialize the blockchain enforcer.

        Args:
            client: BlockchainClient for on-chain interaction
            risk_governor: Existing RiskGovernor for off-chain checks
        """
        self.client = client
        self.risk_governor = risk_governor

        logger.info("BlockchainEnforcer initialized")

    # ── PRE-TRADE CHECKS ─────────────────────────────────────────

    async def pre_trade_check(
        self,
        signal: Any,
        portfolio: Any,
    ) -> DualEnforcementResult:
        """
        Dual enforcement check: off-chain + on-chain.

        BOTH must agree for a trade to proceed.
        On-chain has final authority (cannot be bypassed).

        Args:
            signal: Trading signal to check
            portfolio: Current portfolio state

        Returns:
            DualEnforcementResult with approval status
        """
        # 1. Off-chain check (fast path)
        off_chain_result = None
        if self.risk_governor:
            off_chain_result = await self.risk_governor.check_risk(signal, portfolio)
            off_chain_approved = off_chain_result.approved
        else:
            off_chain_approved = True

        # 2. On-chain check (trust layer)
        on_chain_approved = self.client.is_trading_allowed()

        # 3. On-chain mandate check
        if on_chain_approved:
            mandate_result = self.client.check_order(
                symbol=signal.symbol,
                order_type=0,  # MARKET
                side=0 if signal.side.value == "buy" else 1,
                notional_bps=int(signal.entry_price * 100),  # Simplified
                leverage_bps=100,
                daily_trade_count=signal.metadata.get("daily_trade_count", 0),
            )
            on_chain_approved = mandate_result.allowed

        # 4. On-chain position limit check
        if on_chain_approved:
            position_result = self.client.check_position_limit(
                symbol=signal.symbol,
                sector="crypto",  # Default sector
                notional=signal.entry_price * 0.1,  # Simplified
            )
            on_chain_approved = position_result.passed

        # 5. Determine final approval
        approved = off_chain_approved and on_chain_approved

        # 6. Log risk check to audit trail
        self.client.log_risk_check(
            RiskCheckRecord(
                signal_id=signal.signal_id,
                result=RiskCheckResult.PASS if approved else RiskCheckResult.VETO,
                action=EnforcementAction.NONE if approved else EnforcementAction.TRADE_BLOCKED,
                reason="" if approved else "Dual enforcement check failed",
            )
        )

        # 7. Build result
        if not approved:
            if not off_chain_approved:
                reason = off_chain_result.rejection_reasons[0] if off_chain_result and off_chain_result.rejection_reasons else "Off-chain check failed"
                veto_layer = off_chain_result.veto_level if off_chain_result else "unknown"
            else:
                reason = "On-chain enforcement check failed"
                veto_layer = "BLOCKCHAIN"

            return DualEnforcementResult(
                approved=False,
                off_chain_approved=off_chain_approved,
                on_chain_approved=on_chain_approved,
                reason=reason,
                veto_layer=veto_layer,
            )

        return DualEnforcementResult(
            approved=True,
            off_chain_approved=True,
            on_chain_approved=True,
            reason="All checks passed",
        )

    # ── POST-TRADE RECORDING ─────────────────────────────────────

    async def record_trade_execution(
        self,
        trade: TradeRecord,
    ) -> bool:
        """
        Record trade execution on-chain (immutable audit trail).

        Args:
            trade: TradeRecord with trade details

        Returns:
            True if recording was successful
        """
        return self.client.record_trade(trade)

    async def record_rule_enforcement(
        self,
        rule_id: str,
        trade_id: str,
        action: EnforcementAction,
        reason: str,
    ) -> bool:
        """
        Record rule enforcement action on-chain.

        Args:
            rule_id: Identifier for the rule that was enforced
            trade_id: Associated trade ID
            action: What action was taken
            reason: Why this action was taken

        Returns:
            True if recording was successful
        """
        return self.client.log_rule_enforcement(
            RuleEnforcementRecord(
                rule_id=rule_id,
                trade_id=trade_id,
                action=action,
                reason=reason,
            )
        )

    # ── STATE SYNCHRONIZATION ────────────────────────────────────

    async def sync_pnl_to_chain(self, daily_pnl_bps: int) -> bool:
        """
        Sync daily P&L to on-chain (auto-triggers kill switch if breached).

        Args:
            daily_pnl_bps: Current daily P&L in basis points

        Returns:
            True if sync was successful
        """
        return self.client.update_daily_pnl(daily_pnl_bps)

    async def sync_equity_to_chain(self, equity: float) -> bool:
        """
        Sync equity to on-chain (checks drawdown circuit breakers).

        Args:
            equity: Current portfolio equity in USDT

        Returns:
            True if sync was successful
        """
        return self.client.update_equity(equity)
