"""
Governance — OpenHarness permission system adapted for TSAR risk guards.

Adapts OpenHarness's governance pattern:
  - Permission system for tool access
  - Pre-execution hooks (can this tool run?)
  - Post-execution hooks (what happened?)

TSAR-specific mapping:
  - Permission system → Risk Governor's 7-layer veto protocol
  - Pre-trade hooks → RiskGuardian check, mandate gate, kill switch
  - Post-trade hooks → Trade logging, flywheel trigger, guard state update
  - Role-based access → Agent role permissions (READ, ANALYSIS, TRADE_*)

Permission Model:
  ┌──────────────────────────────────────────────────────────┐
  │  OpenHarness          →  TSAR                           │
  │  ─────────────────────────────────────────────────────── │
  │  tool_permission      →  risk_check(signal, portfolio)  │
  │  pre_execute_hook     →  RiskGuardian + MandateGate     │
  │  post_execute_hook    →  TradeMemory + Flywheel         │
  │  role_permission      →  Agent.ROLE mapping             │
  │  audit_log            →  Blockchain audit trail         │
  └──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Permission Model
# ═══════════════════════════════════════════════════════════════


class Permission(Enum):
    """Tool access permissions mapped to TSAR agent roles."""

    READ = "read"  # Market data, analysis — no side effects
    ANALYSIS = "analysis"  # Technical analysis, sentiment — read-heavy
    TRADE_PREVIEW = "preview"  # Trade proposals — shows intent, no execution
    TRADE_EXECUTE = "execute"  # Order placement — real side effects
    TRADE_ADMIN = "admin"  # Kill switch, mandate, system control


# Role → allowed permissions
ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "READ": {Permission.READ},
    "ANALYSIS": {Permission.READ, Permission.ANALYSIS},
    "TRADE_PREVIEW": {Permission.READ, Permission.ANALYSIS, Permission.TRADE_PREVIEW},
    "TRADE_EXECUTE": {
        Permission.READ,
        Permission.ANALYSIS,
        Permission.TRADE_PREVIEW,
        Permission.TRADE_EXECUTE,
    },
    "TRADE_ADMIN": {
        Permission.READ,
        Permission.ANALYSIS,
        Permission.TRADE_PREVIEW,
        Permission.TRADE_EXECUTE,
        Permission.TRADE_ADMIN,
    },
}

# Tool → required permission
TOOL_PERMISSIONS: dict[str, Permission] = {
    # Read-only tools
    "market_data": Permission.READ,
    "technical_analysis": Permission.READ,
    "fundamental": Permission.READ,
    "on_chain": Permission.READ,
    "sentiment": Permission.READ,
    "news": Permission.READ,
    "economic_calendar": Permission.READ,
    "market_calendar": Permission.READ,
    "knowledge": Permission.READ,
    "knowledge_graph": Permission.READ,
    "volatility": Permission.READ,
    "correlation": Permission.READ,
    "pattern_recognition": Permission.READ,
    "multi_timeframe": Permission.READ,
    "order_flow": Permission.READ,
    "market_microstructure": Permission.READ,
    # Analysis tools
    "backtesting": Permission.ANALYSIS,
    "monitoring": Permission.ANALYSIS,
    "pnl_tracker": Permission.ANALYSIS,
    "win_rate_tracker": Permission.ANALYSIS,
    "equity_curve": Permission.ANALYSIS,
    "risk_state_monitor": Permission.ANALYSIS,
    "flywheel_health": Permission.ANALYSIS,
    # Trade preview (sizing, proposals)
    "risk_management": Permission.TRADE_PREVIEW,
    "stop_loss_calculator": Permission.TRADE_PREVIEW,
    "take_profit_calculator": Permission.TRADE_PREVIEW,
    "fee_calculator": Permission.TRADE_PREVIEW,
    "portfolio": Permission.TRADE_PREVIEW,
    # Trade execution
    "execution": Permission.TRADE_EXECUTE,
    "order_router": Permission.TRADE_EXECUTE,
    "defi_execution": Permission.TRADE_EXECUTE,
    "dex_executor": Permission.TRADE_EXECUTE,
    "intent_executor": Permission.TRADE_EXECUTE,
    "cross_chain": Permission.TRADE_EXECUTE,
    "settlement": Permission.TRADE_EXECUTE,
    "mev_protection": Permission.TRADE_EXECUTE,
    # Admin tools
    "kill_switch": Permission.TRADE_ADMIN,
    "mandate_gate": Permission.TRADE_ADMIN,
}


@dataclass
class GovernanceConfig:
    """Configuration for the governance system."""

    # Pre-trade checks
    enable_risk_check: bool = True
    enable_mandate_gate: bool = True
    enable_kill_switch_check: bool = True
    enable_blackout_check: bool = True

    # Post-trade hooks
    enable_trade_logging: bool = True
    enable_flywheel_trigger: bool = True
    enable_guard_update: bool = True
    enable_audit_trail: bool = True

    # Limits
    max_trade_value_usd: float = 10000.0
    max_daily_trades: int = 30
    require_stop_loss: bool = True

    # Paper trading bypass
    paper_bypass_execution: bool = True  # Don't block paper trades


@dataclass
class GovernanceDecision:
    """Result of a governance check."""

    approved: bool
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))


@dataclass
class AuditEntry:
    """Audit log entry for governance decisions."""

    timestamp: str
    tool_name: str
    agent_role: str
    permission_required: str
    approved: bool
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""


# ═══════════════════════════════════════════════════════════════
# Governance
# ═══════════════════════════════════════════════════════════════


class Governance:
    """
    OpenHarness-compatible governance adapted for TSAR.

    Maps OpenHarness's permission system to TSAR's risk guards:
      1. Permission check: Does this agent role have access to this tool?
      2. Pre-trade hook: RiskGuardian + MandateGate + Kill Switch
      3. Post-trade hook: Log trade, trigger flywheel, update guards
      4. Audit trail: Every decision logged for compliance
    """

    def __init__(
        self,
        config: GovernanceConfig | None = None,
        risk_governor: Any = None,
        mandate_gate: Any = None,
        trade_memory: Any = None,
        flywheel: Any = None,
        trading_mode: str = "paper",
    ) -> None:
        self._config = config or GovernanceConfig()
        self._risk_governor = risk_governor
        self._mandate_gate = mandate_gate
        self._trade_memory = trade_memory
        self._flywheel = flywheel
        self._trading_mode = trading_mode

        # Audit log
        self._audit_log: list[AuditEntry] = []
        self._trade_count_today: int = 0
        self._last_trade_date: str = ""

    # ── Permission Check (OpenHarness pattern) ────────────────────

    def check_permission(
        self,
        tool_name: str,
        agent_role: str,
    ) -> GovernanceDecision:
        """Check if an agent role has permission to use a tool.

        Maps OpenHarness's permission model to TSAR's role system.

        Args:
            tool_name: Name of the tool to check.
            agent_role: Agent's role (READ, ANALYSIS, etc.).

        Returns:
            GovernanceDecision with approval status.
        """
        required_perm = TOOL_PERMISSIONS.get(tool_name)
        if required_perm is None:
            # Unknown tool — default to ANALYSIS permission
            required_perm = Permission.ANALYSIS

        role_perms = ROLE_PERMISSIONS.get(agent_role, set())

        if required_perm in role_perms:
            return GovernanceDecision(approved=True)

        return GovernanceDecision(
            approved=False,
            reason=(
                f"Permission denied: tool '{tool_name}' requires "
                f"{required_perm.value} but agent role '{agent_role}' "
                f"only has {[p.value for p in role_perms]}"
            ),
        )

    # ── Pre-Trade Hook (TSAR Risk Integration) ────────────────────

    async def pre_trade_check(
        self,
        tool_calls: list[Any],
    ) -> bool:
        """Pre-trade governance hook — runs before trade execution.

        Checks (in order):
          1. Permission check (role-based access)
          2. Kill switch status
          3. Mandate gate (human authorization)
          4. Risk Governor 7-layer veto
          5. Daily trade count limit

        Args:
            tool_calls: List of tool calls about to be executed.

        Returns:
            True if all checks pass, False to block execution.
        """
        for tc in tool_calls:
            # 1. Permission check
            perm = self.check_permission(tc.name, getattr(tc, "agent_role", "TRADE_EXECUTE"))
            if not perm.approved:
                self._log_audit(tc, perm.approved, perm.reason)
                logger.warning("Governance BLOCKED: %s — %s", tc.name, perm.reason)
                return False

        # 2. Kill switch check
        if self._config.enable_kill_switch_check and self._risk_governor:
            try:
                if await self._risk_governor.get_kill_switch_status():
                    reason = "Kill switch is ACTIVE — all trading halted"
                    self._log_audit(tool_calls[0], False, reason)
                    logger.warning("Governance BLOCKED: %s", reason)
                    return False
            except Exception as e:
                logger.warning("Kill switch check failed: %s", e)

        # 3. Mandate gate (only for live trading)
        if self._config.enable_mandate_gate and self._trading_mode == "live" and self._mandate_gate:
            try:
                mandate_ok = await self._mandate_gate.check()
                if not mandate_ok:
                    reason = "Mandate gate: live trading not authorized"
                    self._log_audit(tool_calls[0], False, reason)
                    logger.warning("Governance BLOCKED: %s", reason)
                    return False
            except Exception as e:
                logger.warning("Mandate gate check failed: %s", e)

        # 4. Daily trade count
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._last_trade_date:
            self._trade_count_today = 0
            self._last_trade_date = today

        if self._trade_count_today >= self._config.max_daily_trades:
            reason = f"Daily trade limit reached ({self._config.max_daily_trades})"
            self._log_audit(tool_calls[0], False, reason)
            logger.warning("Governance BLOCKED: %s", reason)
            return False

        # 5. Paper trading bypass
        if self._trading_mode == "paper" and self._config.paper_bypass_execution:
            logger.debug("Paper mode: bypassing execution governance checks")
            return True

        return True

    # ── Post-Trade Hook ───────────────────────────────────────────

    async def post_trade_hook(
        self,
        tool_calls: list[Any],
        results: list[Any],
    ) -> None:
        """Post-trade governance hook — runs after trade execution.

        Actions:
          1. Log trade to TradeMemory
          2. Trigger flywheel self-improvement
          3. Update behavioral guard state
          4. Write audit trail

        Args:
            tool_calls: The tool calls that were executed.
            results: The results from execution.
        """
        for tc, result in zip(tool_calls, results, strict=False):
            if not self._is_trade_tool(tc.name):
                continue

            self._trade_count_today += 1

            # 1. Log to TradeMemory
            if self._config.enable_trade_logging and self._trade_memory:
                await self._log_trade(tc, result)

            # 2. Trigger flywheel
            if self._config.enable_flywheel_trigger and self._flywheel:
                await self._trigger_flywheel(tc, result)

            # 3. Update guard state
            if self._config.enable_guard_update:
                await self._update_guards(tc, result)

            # 4. Audit trail
            if self._config.enable_audit_trail:
                self._log_audit(tc, True, "Trade executed", result)

    # ── Trade Logging ─────────────────────────────────────────────

    async def _log_trade(self, tc: Any, result: Any) -> None:
        """Log a trade to TradeMemory."""
        if not self._trade_memory:
            return

        try:
            from src.knowledge.trade_memory import TradeRecord

            record = TradeRecord(
                symbol=tc.arguments.get("symbol", ""),
                side=tc.arguments.get("side", "buy"),
                quantity=tc.arguments.get("quantity", 0),
                entry_price=tc.arguments.get("price", 0),
                status="EXECUTED"
                if not isinstance(result, dict) or "error" not in result
                else "FAILED",
                strategy_id=tc.arguments.get("strategy_id", "harness"),
            )
            self._trade_memory.record_trade(record)
            logger.info("Trade logged: %s %s", record.symbol, record.side)
        except Exception as e:
            logger.error("Failed to log trade: %s", e)

    async def _trigger_flywheel(self, tc: Any, result: Any) -> None:
        """Trigger the flywheel self-improvement loop."""
        if not self._flywheel:
            return

        try:
            if hasattr(self._flywheel, "on_trade_executed"):
                await self._flywheel.on_trade_executed(
                    {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result": result,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
                logger.debug("Flywheel triggered for %s", tc.name)
        except Exception as e:
            logger.warning("Flywheel trigger failed: %s", e)

    async def _update_guards(self, tc: Any, result: Any) -> None:
        """Update behavioral guard state after a trade."""
        if not self._risk_governor:
            return

        try:
            if hasattr(self._risk_governor, "record_trade_outcome"):
                # Determine win/loss from result
                is_win = False
                if isinstance(result, dict):
                    pnl = result.get("pnl", result.get("realized_pnl", 0))
                    is_win = pnl > 0 if isinstance(pnl, (int, float)) else False
                self._risk_governor.record_trade_outcome(is_win)
                logger.debug("Guard state updated: %s", "WIN" if is_win else "LOSS")
        except Exception as e:
            logger.warning("Guard update failed: %s", e)

    # ── Audit Trail ───────────────────────────────────────────────

    def _log_audit(
        self,
        tc: Any,
        approved: bool,
        reason: str,
        result: Any = None,
    ) -> None:
        """Log a governance decision to the audit trail."""
        entry = AuditEntry(
            timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            tool_name=getattr(tc, "name", str(tc)),
            agent_role=getattr(tc, "agent_role", "unknown"),
            permission_required=TOOL_PERMISSIONS.get(
                getattr(tc, "name", ""), Permission.ANALYSIS
            ).value,
            approved=approved,
            reason=reason,
            arguments=getattr(tc, "arguments", {}),
            result_summary=str(result)[:200] if result else "",
        )
        self._audit_log.append(entry)

        # Trim audit log
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    def get_audit_log(
        self,
        limit: int = 100,
        tool_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent audit log entries.

        Args:
            limit: Maximum entries to return.
            tool_name: Filter by tool name.

        Returns:
            List of audit entry dicts.
        """
        entries = self._audit_log
        if tool_name:
            entries = [e for e in entries if e.tool_name == tool_name]

        return [
            {
                "timestamp": e.timestamp,
                "tool": e.tool_name,
                "role": e.agent_role,
                "approved": e.approved,
                "reason": e.reason,
            }
            for e in entries[-limit:]
        ]

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _is_trade_tool(tool_name: str) -> bool:
        """Check if a tool is trade-related."""
        return tool_name in {
            "execution",
            "order_router",
            "defi_execution",
            "dex_executor",
            "intent_executor",
            "cross_chain",
            "settlement",
        }

    def get_status(self) -> dict[str, Any]:
        """Get governance system status."""
        return {
            "trading_mode": self._trading_mode,
            "trades_today": self._trade_count_today,
            "max_daily_trades": self._config.max_daily_trades,
            "audit_entries": len(self._audit_log),
            "risk_governor_active": self._risk_governor is not None,
            "mandate_gate_active": self._mandate_gate is not None,
            "flywheel_active": self._flywheel is not None,
            "checks_enabled": {
                "risk_check": self._config.enable_risk_check,
                "mandate_gate": self._config.enable_mandate_gate,
                "kill_switch": self._config.enable_kill_switch_check,
                "blackout": self._config.enable_blackout_check,
            },
        }
