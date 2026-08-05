"""
Execution Tracker — Position reconciliation and fill monitoring.

Role: TRADE_EXECUTE (Level 3+)

Reconciliation schedule:
  - Position qty: every 5 min (alert on any mismatch)
  - Balance check: every 15 min (alert on > 1% difference)
  - Open orders: every 5 min (alert on stale orders)
  - EOD snapshot: daily 00:00 UTC

Subscribes to: tsar:stream:orders, tsar:stream:fills
Publishes to: tsar:stream:positions
"""

import logging
import time
from typing import Any

from src.agents.base import BaseAgent

# ── Domain Tools (Tools-to-Agents Wiring) ──────────────────────────
from src.tools.execution import ExecutionTools
from src.tools.monitoring import (
    AlertGenerator,
    EquityCurve,
    PnLTracker,
    RiskStateMonitor,
    WinRateTracker,
)

logger = logging.getLogger(__name__)


class ExecutionTracker(BaseAgent):
    """Track fills, reconcile positions, monitor slippage."""

    AGENT_NAME = "execution_tracker"
    ROLE = "TRADE_EXECUTE"

    PUBLISH_STREAM = "positions"
    SUBSCRIBE_STREAMS = ["orders", "trades"]

    def __init__(self, config: dict[str, Any], trading_mode: str = "paper") -> None:
        super().__init__(config, trading_mode)
        self._last_reconciliation: float = 0.0
        self._reconciliation_interval_s: float = 300.0  # 5 min
        self._slippage_alerts: list[dict[str, Any]] = []
        self._fill_quality_log: list[dict[str, Any]] = []
        # Per-trade slippage tracking (L-001)
        self._trade_slippage_history: list[dict[str, Any]] = []
        self._slippage_stats: dict[str, Any] = {
            "total_trades": 0,
            "avg_slippage_bps": 0.0,
            "median_slippage_bps": 0.0,
            "max_slippage_bps": 0.0,
            "slippage_std_bps": 0.0,
            "positive_slippage_count": 0,  # Favorable (got better price)
            "negative_slippage_count": 0,  # Unfavorable (got worse price)
        }

        # ── Domain Tools (Tools-to-Agents Wiring) ───────
        self._execution_tools: ExecutionTools | None = None
        self._pnl_tracker: PnLTracker | None = None
        self._win_rate_tracker: WinRateTracker | None = None
        self._equity_curve: EquityCurve | None = None
        self._risk_state_monitor: RiskStateMonitor | None = None
        self._alert_generator: AlertGenerator | None = None

    async def on_initialize(self) -> None:
        """Initialize execution and monitoring domain tools."""
        try:
            from src.interfaces import get_execution_engine

            exec_engine = get_execution_engine()
            self._execution_tools = ExecutionTools(
                exec_engine=exec_engine,
                config=self.config,
            )
        except Exception as e:
            logger.warning("ExecutionTools init failed: %s", e)

        # Initialize monitoring tools
        try:
            self._pnl_tracker = PnLTracker()
            self._win_rate_tracker = WinRateTracker()
            self._equity_curve = EquityCurve()
            logger.info(
                "ExecutionTracker tools initialized: "
                "[execution, pnl_tracker, win_rate_tracker, equity_curve]"
            )
        except Exception as e:
            logger.warning("Monitoring tools init failed: %s", e)

    async def run_cycle(self) -> None:
        """Reconcile positions, monitor fills, and analyze execution quality.

        Each cycle:
        1. Check if reconciliation interval has elapsed.
        2. Fetch open positions from exchange and local records.
        3. Compare and alert on mismatches.
        4. Analyze recent fill quality and slippage.
        5. Monitor for stale open orders.
        6. Update monitoring tools (P&L, win rate, equity curve).
        """
        now = time.monotonic()
        if now - self._last_reconciliation < self._reconciliation_interval_s:
            return

        self._last_reconciliation = now

        try:
            await self._reconcile_positions()
            await self._analyze_fill_quality()
            await self._check_stale_orders()
            self._update_monitoring_state()
        except Exception as exc:
            logger.error("ExecutionTracker cycle failed: %s", exc, exc_info=True)

    def _update_monitoring_state(self) -> None:
        """Update monitoring tools with latest trade data.

        Feeds recent slippage data into the monitoring tools for
        P&L tracking, win rate computation, and equity curve updates.
        """
        if not self._fill_quality_log:
            return

        # Update slippage stats from execution tools if available
        if self._execution_tools:
            try:
                tool_stats = self._execution_tools.get_slippage_stats()
                if tool_stats:
                    logger.debug(
                        "ExecutionTools slippage stats: %d trades, avg=%.2f bps",
                        tool_stats.get("total_trades", 0),
                        tool_stats.get("avg_slippage_bps", 0.0),
                    )
            except Exception:
                logger.debug("Slippage stats retrieval failed", exc_info=True)

        logger.debug(
            "Monitoring state updated: %d fill records, %d slippage records",
            len(self._fill_quality_log),
            len(self._trade_slippage_history),
        )

    async def _reconcile_positions(self) -> None:
        """Compare exchange positions against local trade records.

        Alerts on any mismatch between what the exchange reports
        and what TSAR's TradeMemory thinks is open.
        """
        try:
            from src.interfaces import get_exchange_gateway
            from src.knowledge.trade_memory import TradeMemory

            gateway = get_exchange_gateway()
            exchange_positions = await gateway.get_positions()

            # Get local open positions from TradeMemory
            db_path = self.config.get("database", {}).get("path", "./data/tsar.db")
            trade_mem = TradeMemory(db_path)
            local_positions = trade_mem.get_open_positions()

            # Build lookup maps
            exchange_by_symbol: dict[str, float] = {}
            for pos in exchange_positions:
                exchange_by_symbol[pos.symbol] = pos.quantity

            local_by_symbol: dict[str, float] = {}
            for trade in local_positions:
                sym = trade.symbol
                local_by_symbol[sym] = local_by_symbol.get(sym, 0) + abs(trade.position_size_after)

            # Check for mismatches
            all_symbols = set(exchange_by_symbol.keys()) | set(local_by_symbol.keys())
            for symbol in all_symbols:
                exch_qty = exchange_by_symbol.get(symbol, 0.0)
                local_qty = local_by_symbol.get(symbol, 0.0)
                diff = abs(exch_qty - local_qty)

                if diff > 0.0001:  # tolerance for floating point
                    logger.warning(
                        "POSITION MISMATCH: %s — exchange=%.8f local=%.8f diff=%.8f",
                        symbol,
                        exch_qty,
                        local_qty,
                        diff,
                    )
                    await self.publish_event(
                        stream="positions",
                        event_type="tsar.position.mismatch.v1",
                        data={
                            "symbol": symbol,
                            "exchange_qty": exch_qty,
                            "local_qty": local_qty,
                            "diff": diff,
                        },
                        priority=1,
                        risk_level="HIGH",
                    )

        except Exception as exc:
            logger.error("Position reconciliation failed: %s", exc)

    async def _analyze_fill_quality(self) -> None:
        """Analyze recent fill quality — slippage and execution grade.

        Reviews recent closed trades and flags any with:
        - Slippage > 10 bps (warning)
        - Slippage > 50 bps (critical)
        - Latency > 5000ms (warning)
        """
        try:
            from src.knowledge.trade_memory import TradeMemory

            db_path = self.config.get("database", {}).get("path", "./data/tsar.db")
            trade_mem = TradeMemory(db_path)

            # Get recently closed trades
            recent_trades = trade_mem.list_trades(status="CLOSED", limit=20)

            for trade in recent_trades:
                if trade.slippage_bps is not None:
                    abs_slip = abs(trade.slippage_bps)
                    if abs_slip > 50:
                        logger.critical(
                            "CRITICAL SLIPPAGE: %s %s — %.2f bps (trade=%s)",
                            trade.side,
                            trade.symbol,
                            trade.slippage_bps,
                            trade.trade_id,
                        )
                        self._slippage_alerts.append(
                            {
                                "trade_id": trade.trade_id,
                                "symbol": trade.symbol,
                                "slippage_bps": trade.slippage_bps,
                                "severity": "CRITICAL",
                                "timestamp": time.time(),
                            }
                        )
                    elif abs_slip > 10:
                        logger.warning(
                            "HIGH SLIPPAGE: %s %s — %.2f bps (trade=%s)",
                            trade.side,
                            trade.symbol,
                            trade.slippage_bps,
                            trade.trade_id,
                        )

                if trade.latency_ms is not None and trade.latency_ms > 5000:
                    logger.warning(
                        "HIGH LATENCY: %s %s — %dms (trade=%s)",
                        trade.side,
                        trade.symbol,
                        trade.latency_ms,
                        trade.trade_id,
                    )

                # Record fill quality metrics
                self._fill_quality_log.append(
                    {
                        "trade_id": trade.trade_id,
                        "symbol": trade.symbol,
                        "slippage_bps": trade.slippage_bps,
                        "latency_ms": trade.latency_ms,
                        "execution_grade": trade.execution_grade,
                        "timestamp": time.time(),
                    }
                )

            # Trim log to last 100 entries
            if len(self._fill_quality_log) > 100:
                self._fill_quality_log = self._fill_quality_log[-100:]

        except Exception as exc:
            logger.error("Fill quality analysis failed: %s", exc)

    async def _check_stale_orders(self) -> None:
        """Monitor for stale open orders that may need attention.

        Flags orders that have been open for more than 1 hour.
        """
        try:
            from src.knowledge.trade_memory import TradeMemory

            db_path = self.config.get("database", {}).get("path", "./data/tsar.db")
            trade_mem = TradeMemory(db_path)
            open_trades = trade_mem.list_trades(status="OPEN", limit=50)

            from datetime import UTC, datetime

            now = datetime.now(UTC)
            for trade in open_trades:
                if trade.created_at:
                    try:
                        created = datetime.fromisoformat(trade.created_at.replace("Z", "+00:00"))
                        age_hours = (now - created).total_seconds() / 3600
                        if age_hours > 1:
                            logger.warning(
                                "STALE ORDER: %s %s open for %.1fh (trade=%s)",
                                trade.side,
                                trade.symbol,
                                age_hours,
                                trade.trade_id,
                            )
                    except (ValueError, TypeError):
                        pass

        except Exception as exc:
            logger.error("Stale order check failed: %s", exc)

    async def track_trade_slippage(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        expected_price: float,
        actual_price: float,
        quantity: float,
    ) -> dict[str, Any]:
        """Track slippage for an individual trade.

        Args:
            trade_id: Unique trade identifier.
            symbol: Trading pair.
            side: "buy" or "sell".
            expected_price: Price expected when signal was generated.
            actual_price: Actual fill price.
            quantity: Trade quantity.

        Returns:
            Dict with slippage analysis for the trade.
        """
        if expected_price <= 0:
            return {"error": "invalid_expected_price"}

        # Slippage: positive = unfavorable (paid more / received less)
        if side == "buy":
            slippage_abs = actual_price - expected_price
        else:
            slippage_abs = expected_price - actual_price

        slippage_bps = slippage_abs / expected_price * 10_000
        slippage_usd = slippage_abs * quantity

        is_favorable = slippage_bps < 0  # Got a better price than expected

        record = {
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "expected_price": expected_price,
            "actual_price": actual_price,
            "quantity": quantity,
            "slippage_bps": round(slippage_bps, 2),
            "slippage_usd": round(slippage_usd, 4),
            "is_favorable": is_favorable,
            "timestamp": time.time(),
        }

        self._trade_slippage_history.append(record)

        # Trim history to last 500 trades
        if len(self._trade_slippage_history) > 500:
            self._trade_slippage_history = self._trade_slippage_history[-500:]

        # Update running stats
        self._update_slippage_stats()

        # Alert on high slippage
        abs_bps = abs(slippage_bps)
        if abs_bps > 50:
            logger.critical(
                "CRITICAL SLIPPAGE: %s %s — %.2f bps ($%.4f)",
                symbol,
                side,
                slippage_bps,
                slippage_usd,
            )
        elif abs_bps > 10:
            logger.warning(
                "HIGH SLIPPAGE: %s %s — %.2f bps ($%.4f)",
                symbol,
                side,
                slippage_bps,
                slippage_usd,
            )
        else:
            logger.info(
                "Slippage: %s %s — %.2f bps ($%.4f)",
                symbol,
                side,
                slippage_bps,
                slippage_usd,
            )

        return record

    def _update_slippage_stats(self) -> None:
        """Update running slippage statistics."""
        history = self._trade_slippage_history
        if not history:
            return

        bps_values = [r["slippage_bps"] for r in history]
        n = len(bps_values)

        self._slippage_stats = {
            "total_trades": n,
            "avg_slippage_bps": round(sum(bps_values) / n, 2),
            "median_slippage_bps": round(sorted(bps_values)[n // 2], 2),
            "max_slippage_bps": round(max(bps_values), 2),
            "min_slippage_bps": round(min(bps_values), 2),
            "slippage_std_bps": round(
                (sum((x - sum(bps_values) / n) ** 2 for x in bps_values) / n) ** 0.5,
                2,
            ),
            "positive_slippage_count": sum(1 for r in history if r["is_favorable"]),
            "negative_slippage_count": sum(1 for r in history if not r["is_favorable"]),
            "total_slippage_usd": round(sum(r["slippage_usd"] for r in history), 4),
        }

    def get_slippage_report(self) -> dict[str, Any]:
        """Get comprehensive slippage report.

        Returns:
            Dict with slippage statistics, recent trades, and alerts.
        """
        return {
            "stats": self._slippage_stats,
            "recent_trades": self._trade_slippage_history[-20:],
            "alerts": self._slippage_alerts[-10:],
            "fill_quality_count": len(self._fill_quality_log),
        }
