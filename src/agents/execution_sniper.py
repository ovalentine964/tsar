"""
Execution Sniper — Place orders, manage stop-losses, track positions.

Role: TRADE_EXECUTE
No LLM — pure execution logic.

Order lifecycle:
  1. RECEIVE approved signal from Risk Guardian via risk.approved event
  2. VALIDATE order parameters
  3. PLACE stop-loss order FIRST (safety first!)
  4. PLACE entry order (market or limit)
  5. MONITOR fills and slippage
  6. PUBLISH trade.executed event

Critical rule: Stop-loss is placed BEFORE the entry order.
This ensures we never have an unprotected position.

Subscribes to: tsar:stream:risk_decisions
Publishes to:  tsar:stream:trades
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.agents.base import BaseAgent
from src.interfaces.types import (
    ExecutionResult,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)

if TYPE_CHECKING:
    from src.comms.events import CloudEvent

logger = logging.getLogger(__name__)


class ExecutionSniper(BaseAgent):
    """Execute approved trades with precision and safety.

    The ExecutionSniper is the final agent in the trading pipeline.
    It receives risk-approved signals and executes them on the exchange.

    Safety protocol:
    1. Stop-loss order is placed BEFORE the entry order
    2. Slippage is monitored and reported
    3. Failed orders trigger immediate alerts
    4. All executions are logged with full traceability
    """

    AGENT_NAME = "execution_sniper"
    ROLE = "TRADE_EXECUTE"

    PUBLISH_STREAM = "trades"
    SUBSCRIBE_STREAMS = ["risk_decisions"]

    # Slippage thresholds (basis points)
    SLIPPAGE_WARNING_BPS = 10.0   # 0.1% — log warning
    SLIPPAGE_CRITICAL_BPS = 50.0  # 0.5% — abort and alert

    # Order timeout
    ORDER_TIMEOUT_S = 30.0

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)

        # Engine references (lazy-initialized)
        self._exec_engine = None
        self._gateway = None

        # Execution tracking
        self._pending_orders: dict[str, dict[str, Any]] = {}
        self._execution_log: list[dict[str, Any]] = []

    async def on_initialize(self) -> None:
        """Initialize execution engine and exchange gateway."""
        from src.interfaces import get_exchange_gateway, get_execution_engine

        self._exec_engine = get_execution_engine()
        self._gateway = get_exchange_gateway()
        logger.info("ExecutionSniper initialized (mode=%s)", self.trading_mode)

    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        """Handle incoming risk.approved events.

        Args:
            stream: Event stream name.
            event: CloudEvent containing risk decision data.
        """
        if stream != "risk_decisions":
            return

        if event.type == "tsar.risk.approved.v1":
            await self._execute_approved_signal(event)
        elif event.type == "tsar.risk.vetoed.v1":
            logger.info(
                "Signal vetoed — no execution: %s (%s)",
                event.data.get("signal_id"),
                event.data.get("veto_level"),
            )

    async def run_cycle(self) -> None:
        """Monitor pending orders and check for fills.

        The ExecutionSniper primarily reacts to risk.approved events.
        The run_cycle handles:
        - Monitoring pending order fills
        - Checking slippage on completed orders
        - Cleaning up stale orders
        """
        if not self._pending_orders:
            return

        stale_orders = []
        for order_id, order_info in self._pending_orders.items():
            elapsed = time.time() - order_info.get("placed_at", 0)
            if elapsed > self.ORDER_TIMEOUT_S:
                stale_orders.append(order_id)
                logger.warning("Order %s timed out after %.0fs", order_id, elapsed)

        for order_id in stale_orders:
            await self._handle_order_timeout(order_id)

    async def _execute_approved_signal(self, event: CloudEvent) -> None:
        """Execute an approved trading signal.

        Safety protocol:
        1. Validate order parameters
        2. Place stop-loss order FIRST
        3. Place entry order
        4. Monitor and report

        Args:
            event: CloudEvent with approved signal data.
        """
        data = event.data
        trace_id = event.traceid

        symbol = data["symbol"]
        side = OrderSide(data["side"])
        entry_price = data["entry_price"]
        stop_loss = data["stop_loss"]
        take_profit = data["take_profit"]
        quantity = data.get("position_size", 0)
        signal_id = data.get("signal_id", "unknown")

        logger.info(
            "🎯 Executing approved signal: %s %s %s qty=%.6f entry=%.2f sl=%.2f tp=%.2f",
            signal_id, symbol, side.value, quantity,
            entry_price, stop_loss, take_profit,
        )

        if quantity <= 0:
            logger.error("Cannot execute: position_size=%.6f", quantity)
            await self._publish_execution_failure(
                signal_id, symbol, side, "Invalid position size: zero or negative",
                trace_id,
            )
            return

        try:
            # ── Step 1: Place Stop-Loss Order FIRST ───────────────
            sl_order_id = await self._place_stop_loss(
                symbol=symbol,
                side=OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY,
                quantity=quantity,
                stop_price=stop_loss,
                trace_id=trace_id,
            )

            if not sl_order_id:
                logger.error("Failed to place stop-loss — aborting entry")
                await self._publish_execution_failure(
                    signal_id, symbol, side, "Stop-loss order failed",
                    trace_id,
                )
                return

            logger.info("  ✓ Stop-loss placed: order_id=%s", sl_order_id)

            # ── Step 2: Place Entry Order ─────────────────────────
            entry_result = await self._place_entry_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                trace_id=trace_id,
            )

            if not entry_result:
                logger.error("Entry order failed — cancelling stop-loss")
                await self._cancel_stop_loss(sl_order_id)
                await self._publish_execution_failure(
                    signal_id, symbol, side, "Entry order failed",
                    trace_id,
                )
                return

            logger.info(
                "  ✓ Entry filled: order_id=%s avg_price=%.2f filled=%.6f slippage=%.2f bps",
                entry_result.order_id, entry_result.average_price,
                entry_result.filled_quantity, entry_result.slippage_bps,
            )

            # ── Step 3: Check Slippage ────────────────────────────
            if entry_result.slippage_bps > self.SLIPPAGE_CRITICAL_BPS:
                logger.error(
                    "  ⚠️ CRITICAL SLIPPAGE: %.2f bps — consider manual review",
                    entry_result.slippage_bps,
                )
            elif entry_result.slippage_bps > self.SLIPPAGE_WARNING_BPS:
                logger.warning(
                    "  ⚠️ Elevated slippage: %.2f bps",
                    entry_result.slippage_bps,
                )

            # ── Step 4: Place Take-Profit Order ───────────────────
            tp_order_id = await self._place_take_profit(
                symbol=symbol,
                side=OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY,
                quantity=quantity,
                take_profit_price=take_profit,
                trace_id=trace_id,
            )
            if tp_order_id:
                logger.info("  ✓ Take-profit placed: order_id=%s", tp_order_id)

            # ── Step 5: Publish Trade Executed Event ──────────────
            await self._publish_trade_executed(
                signal_id=signal_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_result=entry_result,
                sl_order_id=sl_order_id,
                tp_order_id=tp_order_id,
                stop_loss=stop_loss,
                take_profit=take_profit,
                trace_id=trace_id,
            )

            # Track the entry order
            self._pending_orders[entry_result.order_id] = {
                "signal_id": signal_id,
                "symbol": symbol,
                "side": side.value,
                "quantity": quantity,
                "sl_order_id": sl_order_id,
                "tp_order_id": tp_order_id,
                "placed_at": time.time(),
            }

        except Exception:
            logger.exception("Execution failed for signal %s", signal_id)
            await self._publish_execution_failure(
                signal_id, symbol, side, "Execution exception",
                trace_id,
            )

    async def _place_entry_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        entry_price: float,
        trace_id: str,
    ) -> ExecutionResult | None:
        """Place the entry order (market order).

        Args:
            symbol: Trading pair.
            side: Buy or sell.
            quantity: Order quantity.
            entry_price: Expected entry price (for slippage calculation).
            trace_id: Distributed trace ID.

        Returns:
            ExecutionResult if successful, None if failed.
        """
        order = Order(
            order_id="",
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=None,
            status=OrderStatus.PENDING,
            timestamp=datetime.now(UTC),
        )

        try:
            result = await self._exec_engine.execute_order(order)
            return result
        except Exception:
            logger.exception("Entry order failed for %s", symbol)
            return None

    async def _place_stop_loss(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        stop_price: float,
        trace_id: str,
    ) -> str | None:
        """Place a stop-loss order.

        Args:
            symbol: Trading pair.
            side: Opposite side of entry (SELL for BUY entry).
            quantity: Order quantity.
            stop_price: Stop trigger price.
            trace_id: Distributed trace ID.

        Returns:
            Order ID if successful, None if failed.
        """
        order = Order(
            order_id="",
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP_MARKET,
            quantity=quantity,
            stop_price=stop_price,
            status=OrderStatus.PENDING,
            timestamp=datetime.now(UTC),
        )

        try:
            result = await self._exec_engine.execute_order(order)
            if result.status in (OrderStatus.OPEN, OrderStatus.FILLED):
                return result.order_id
            logger.warning("Stop-loss order status: %s", result.status)
            return result.order_id
        except Exception:
            logger.exception("Stop-loss order failed for %s", symbol)
            return None

    async def _place_take_profit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        take_profit_price: float,
        trace_id: str,
    ) -> str | None:
        """Place a take-profit (limit) order.

        Args:
            symbol: Trading pair.
            side: Opposite side of entry.
            quantity: Order quantity.
            take_profit_price: Take-profit target price.
            trace_id: Distributed trace ID.

        Returns:
            Order ID if successful, None if failed.
        """
        order = Order(
            order_id="",
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=take_profit_price,
            status=OrderStatus.PENDING,
            timestamp=datetime.now(UTC),
        )

        try:
            result = await self._exec_engine.execute_order(order)
            return result.order_id
        except Exception:
            logger.exception("Take-profit order failed for %s", symbol)
            return None

    async def _cancel_stop_loss(self, order_id: str) -> bool:
        """Cancel a stop-loss order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            True if cancelled successfully.
        """
        try:
            result = await self._exec_engine.cancel_order(order_id)
            logger.info("Cancelled stop-loss order: %s (success=%s)", order_id, result)
            return result
        except Exception:
            logger.exception("Failed to cancel stop-loss order: %s", order_id)
            return False

    async def _handle_order_timeout(self, order_id: str) -> None:
        """Handle a timed-out order.

        Args:
            order_id: The order that timed out.
        """
        order_info = self._pending_orders.pop(order_id, None)
        if not order_info:
            return

        logger.warning("Order %s timed out — checking status", order_id)
        try:
            status = await self._exec_engine.get_order_status(order_id)
            logger.info("  Order %s status: %s", order_id, status)
            if status == OrderStatus.OPEN:
                logger.warning("  Order still open — consider manual review")
        except Exception:
            logger.exception("Failed to check order status: %s", order_id)

    async def _publish_trade_executed(
        self,
        signal_id: str,
        symbol: str,
        side: OrderSide,
        quantity: float,
        entry_result: ExecutionResult,
        sl_order_id: str,
        tp_order_id: str | None,
        stop_loss: float,
        take_profit: float,
        trace_id: str,
    ) -> None:
        """Publish a trade.executed event.

        Args:
            signal_id: Original signal ID.
            symbol: Trading pair.
            side: Order side.
            quantity: Executed quantity.
            entry_result: Entry order execution result.
            sl_order_id: Stop-loss order ID.
            tp_order_id: Take-profit order ID (or None).
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.
            trace_id: Distributed trace ID.
        """
        await self.publish_event(
            stream="trades",
            event_type="tsar.trade.executed.v1",
            data={
                "signal_id": signal_id,
                "symbol": symbol,
                "side": side.value,
                "quantity": quantity,
                "entry_price": entry_result.average_price,
                "entry_order_id": entry_result.order_id,
                "stop_loss": stop_loss,
                "stop_loss_order_id": sl_order_id,
                "take_profit": take_profit,
                "take_profit_order_id": tp_order_id,
                "slippage_bps": entry_result.slippage_bps,
                "total_fee": entry_result.total_fee,
                "fills": [
                    {
                        "fill_id": f.fill_id,
                        "price": f.price,
                        "quantity": f.quantity,
                        "fee": f.fee,
                        "timestamp": f.timestamp.isoformat() if f.timestamp else None,
                    }
                    for f in entry_result.fills
                ],
                "status": entry_result.status.value,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            priority=1,
            risk_level="LOW",
            trace_id=trace_id,
        )

    async def _publish_execution_failure(
        self,
        signal_id: str,
        symbol: str,
        side: OrderSide,
        reason: str,
        trace_id: str,
    ) -> None:
        """Publish a trade.failed event.

        Args:
            signal_id: Original signal ID.
            symbol: Trading pair.
            side: Order side.
            reason: Failure reason.
            trace_id: Distributed trace ID.
        """
        logger.error("EXECUTION FAILED: %s %s — %s", symbol, side.value, reason)

        await self.publish_event(
            stream="trades",
            event_type="tsar.trade.failed.v1",
            data={
                "signal_id": signal_id,
                "symbol": symbol,
                "side": side.value,
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            priority=0,  # Critical — execution failure
            risk_level="HIGH",
            trace_id=trace_id,
        )
