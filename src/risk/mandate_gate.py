"""
MandateGate — Pre-risk authorization gate for the Risk Guardian.

Sits BEFORE the 7-layer veto protocol in the trade pipeline.
Checks orders against the human-committed mandate before any
risk evaluation occurs.

Pipeline order:
  Signal → [MandateGate] → RiskGovernor (7-layer) → Execution

If the mandate gate blocks a trade, it never reaches the risk engine.
This ensures that even if a trade is "safe" (risk-approved), it must
also be "authorized" (mandate-approved).

Paper mode is exempt — mandate checks only apply to live trading.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from src.interfaces.types import (
    Order,
    OrderType,
    RiskDecision,
    Signal,
    VetoLevel,
)
from src.risk.mandate import Mandate, MandateDecision

logger = logging.getLogger(__name__)


class MandateGate:
    """Authorization gate that wraps the Mandate for pipeline integration.

    Checks orders against the mandate BEFORE risk evaluation.
    Returns MandateDecision for the caller to act on.

    The gate is designed to be composable with the RiskGovernor:
        gate_decision = mandate_gate.check(signal, portfolio, is_live=True)
        if not gate_decision.approved:
            return gate_decision  # Blocked by mandate
        risk_decision = await risk_governor.check_risk(signal, portfolio)
    """

    def __init__(
        self,
        mandate: Mandate | None = None,
        config_path: str | None = None,
    ) -> None:
        """Initialize the MandateGate.

        Args:
            mandate: Pre-built Mandate instance. Takes precedence.
            config_path: Path to mandate YAML (used if mandate is None).
        """
        self._mandate = mandate or Mandate(config_path=config_path)
        logger.info(
            f"MandateGate initialized: mandate_status={self._mandate.status.value}"
        )

    @property
    def mandate(self) -> Mandate:
        """Access the underlying mandate."""
        return self._mandate

    def check(
        self,
        signal: Signal,
        is_live: bool = True,
        daily_trade_count: int = 0,
        leverage: float = 1.0,
        order_type: OrderType = OrderType.MARKET,
    ) -> RiskDecision:
        """Check a signal against the mandate — synchronous version.

        This is the primary gate interface. Wraps the mandate check
        in a RiskDecision for seamless integration with the pipeline.

        Paper mode (is_live=False) is EXEMPT — always approved.

        Args:
            signal: Trading signal to check.
            is_live: Whether this is a live trade (False = paper mode).
            daily_trade_count: Current daily trade count.
            leverage: Requested leverage.
            order_type: Order type for this trade.

        Returns:
            RiskDecision — approved=True if mandate allows, False if blocked.
        """
        # Paper mode exemption
        if not is_live:
            logger.debug(
                f"MandateGate: paper mode — signal {signal.signal_id} exempt"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=True,
                position_size=0.0,
                rejection_reasons=(),
                warnings=("Paper mode — mandate checks bypassed.",),
                veto_level=VetoLevel.NONE.value,
                timestamp=datetime.now(UTC),
            )

        # Check against mandate
        decision = self._mandate.check_signal(
            symbol=signal.symbol,
            side=signal.side,
            quantity=0.0,  # Quantity not yet determined at gate stage
            price=signal.entry_price,
            order_type=order_type,
            daily_trade_count=daily_trade_count,
            leverage=leverage,
        )

        if decision.allowed:
            logger.info(
                f"MandateGate APPROVED: {signal.signal_id} {signal.symbol} "
                f"{signal.side.value}"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=True,
                position_size=0.0,  # Sizing happens in risk engine
                rejection_reasons=(),
                warnings=(),
                veto_level=VetoLevel.NONE.value,
                timestamp=datetime.now(UTC),
            )

        # Mandate blocked
        logger.info(
            f"MandateGate REJECTED: {signal.signal_id} — {decision.reason}"
        )
        return RiskDecision(
            signal_id=signal.signal_id,
            approved=False,
            position_size=0.0,
            rejection_reasons=(
                f"Mandate Gate: {decision.reason}",
                *decision.violations,
            ),
            warnings=(),
            veto_level=VetoLevel.HARD.value,
            timestamp=datetime.now(UTC),
        )

    async def check_async(
        self,
        signal: Signal,
        is_live: bool = True,
        daily_trade_count: int = 0,
        leverage: float = 1.0,
        order_type: OrderType = OrderType.MARKET,
    ) -> RiskDecision:
        """Check a signal against the mandate — async version.

        Delegates to the synchronous check in a thread pool to avoid
        blocking the event loop (mandate checks are fast but we want
        to be safe for async pipelines).

        Args:
            signal: Trading signal to check.
            is_live: Whether this is a live trade.
            daily_trade_count: Current daily trade count.
            leverage: Requested leverage.
            order_type: Order type.

        Returns:
            RiskDecision with mandate authorization result.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self.check,
            signal,
            is_live,
            daily_trade_count,
            leverage,
            order_type,
        )

    def check_order(self, order: Order, is_live: bool = True) -> MandateDecision:
        """Check a full Order object against the mandate.

        Use this when you have a concrete Order (post-sizing).
        For pre-sizing checks, use check() with a Signal.

        Args:
            order: The order to validate.
            is_live: Whether this is a live trade.

        Returns:
            MandateDecision with authorization result.
        """
        if not is_live:
            return MandateDecision(
                allowed=True,
                reason="Paper mode — mandate checks bypassed.",
                violations=[],
            )

        return self._mandate.check_order(order)

    def get_status(self) -> dict[str, Any]:
        """Get mandate gate status for monitoring/health checks.

        Returns:
            Dict with mandate status, version, committed_by, etc.
        """
        state = self._mandate.state
        return {
            "mandate_status": state.status.value,
            "is_active": self._mandate.is_active,
            "version": state.version,
            "committed_at": state.committed_at.isoformat() if state.committed_at else None,
            "committed_by": state.committed_by,
            "revoked_at": state.revoked_at.isoformat() if state.revoked_at else None,
            "allowed_symbols_count": len(state.rules.allowed_symbols),
            "max_position_size_pct": state.rules.max_position_size_pct,
            "max_daily_trades": state.rules.max_daily_trades,
            "max_leverage": state.rules.max_leverage,
        }
