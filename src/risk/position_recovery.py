"""
Position Recovery — Verify stop-losses on startup + recovery integration.

On startup, checks all open positions have active stop-losses.
Missing stop-losses are placed automatically using the configured
max_stop_loss_pct from risk.yaml.

Also integrates with the Gated Recovery Protocol (C-016):
  After a kill switch deactivation, position sizes are progressively
  restored through the recovery phases defined in risk.yaml.

SAFETY:
  - Stop-loss verification runs BEFORE any new trades
  - Recovery allocation is applied as a multiplier to position sizing
  - All parameters read from risk.yaml (single source of truth)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.risk.governor import RiskGovernor

logger = logging.getLogger(__name__)


class PositionRecovery:
    """Position recovery and stop-loss verification.

    Handles:
      1. Startup stop-loss verification (ensure all positions are protected)
      2. Recovery protocol integration (phased re-entry after kill switch)

    The recovery allocation from RiskGovernor.get_recovery_allocation()
    is used as a position size multiplier during the recovery period.
    """

    def __init__(
        self,
        exchange_gateway: Any,
        risk_engine: RiskGovernor,
        max_stop_loss_pct: float = 0.02,
    ) -> None:
        """Initialize position recovery.

        Args:
            exchange_gateway: Exchange gateway for order placement.
            risk_engine: Risk governor for recovery allocation.
            max_stop_loss_pct: Max stop-loss distance from entry (default 2%).
        """
        self.exchange = exchange_gateway
        self.risk = risk_engine
        self._max_sl_pct = max_stop_loss_pct

    async def verify_stop_losses(self) -> dict[str, Any]:
        """On startup, check all open positions have active stop-losses.

        Returns:
            Dict with verification results:
              - positions_checked: Number of positions verified
              - stop_losses_placed: Number of missing stop-losses placed
              - errors: List of errors encountered
        """
        result = {
            "positions_checked": 0,
            "stop_losses_placed": 0,
            "errors": [],
        }

        try:
            positions = await self.exchange.get_positions()
            orders = await self.exchange.get_open_orders()
        except Exception as e:
            logger.error(f"Failed to fetch positions/orders for verification: {e}")
            result["errors"].append(str(e))
            return result

        # Build set of symbols with active stop-losses
        stop_symbols = set()
        for order in orders:
            if hasattr(order, 'type') and order.type == "stop_market":
                stop_symbols.add(order.symbol)
            elif hasattr(order, 'order_type') and str(order.order_type) == "stop_market":
                stop_symbols.add(order.symbol)

        for pos in positions:
            result["positions_checked"] += 1
            symbol = pos.symbol

            if symbol in stop_symbols:
                logger.debug(f"Stop-loss verified for {symbol}")
                continue

            # Missing stop-loss — place it
            logger.warning(f"Missing stop-loss for {symbol} — placing now")
            try:
                if pos.side == "buy" or str(pos.side) == "buy":
                    sl_price = pos.entry_price * (1 - self._max_sl_pct)
                    close_side = "sell"
                else:
                    sl_price = pos.entry_price * (1 + self._max_sl_pct)
                    close_side = "buy"

                await self.exchange.create_order(
                    symbol=symbol,
                    side=close_side,
                    type="stop_market",
                    amount=pos.amount if hasattr(pos, 'amount') else pos.quantity,
                    price=sl_price,
                )
                result["stop_losses_placed"] += 1
                logger.info(
                    f"Stop-loss placed for {symbol} at {sl_price:.2f} "
                    f"({self._max_sl_pct:.1%} from entry {pos.entry_price:.2f})"
                )
            except Exception as e:
                logger.error(f"Failed to place stop-loss for {symbol}: {e}")
                result["errors"].append(f"{symbol}: {e}")

        logger.info(
            f"Stop-loss verification complete: "
            f"{result['positions_checked']} checked, "
            f"{result['stop_losses_placed']} placed, "
            f"{len(result['errors'])} errors"
        )
        return result

    def get_recovery_multiplier(self, circuit_breaker_level: str) -> float:
        """Get the recovery allocation multiplier for position sizing.

        After a kill switch deactivation, position sizes ramp up
        gradually through the recovery phases defined in risk.yaml.

        Args:
            circuit_breaker_level: The level that triggered ("orange" or "red").

        Returns:
            Multiplier (0.0-1.0) to apply to position sizes.
            Returns 1.0 if no recovery is active.
        """
        return self.risk.get_recovery_allocation(circuit_breaker_level)
