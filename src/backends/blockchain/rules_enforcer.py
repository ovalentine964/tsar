"""
TSAR Rules Enforcer — On-chain rule enforcement via smart contracts.

This module provides a Python interface for interacting with TSAR's on-chain
rule enforcement system. It can operate in two modes:

1. **Rust Bridge Mode** (preferred): Uses the native `trading_rs` Rust extension
   for high-performance contract interaction via ethers-rs.

2. **Pure Python Mode** (fallback): Uses `web3.py` for direct contract interaction
   when the Rust extension is not available.

Usage:
    from src.backends.blockchain.rules_enforcer import RulesEnforcer

    config = {
        "rpc_url": "wss://polygon-mumbai.g.alchemy.com/v2/YOUR_KEY",
        "chain_id": 80001,
        "private_key": "...",
        "kill_switch_address": "0x...",
        "mandate_address": "0x...",
        "audit_trail_address": "0x...",
        "governance_address": "0x...",
    }

    enforcer = RulesEnforcer(config)
    enforcer.connect()

    # Pre-trade check
    if enforcer.is_trading_allowed():
        result = enforcer.check_order("BTC/USDT", order_type=0, side=0, ...)
        if result["allowed"]:
            # Execute trade...
            enforcer.log_trade(...)

    # Monitor events
    enforcer.on_kill_switch_activated(lambda status: alert(status))
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class RuleCheckResult:
    """Result of an on-chain rule check."""

    allowed: bool
    reason: str
    rule_id: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "timestamp": self.timestamp,
        }


@dataclass
class KillSwitchStatus:
    """Kill switch status from on-chain."""

    active: bool
    reason: str
    activated_at: int
    daily_pnl_bps: int
    circuit_breaker_level: int
    drawdown_bps: int

    @property
    def circuit_breaker_name(self) -> str:
        names = {0: "GREEN", 1: "YELLOW", 2: "ORANGE", 3: "RED"}
        return names.get(self.circuit_breaker_level, "UNKNOWN")

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "reason": self.reason,
            "activated_at": self.activated_at,
            "daily_pnl_bps": self.daily_pnl_bps,
            "circuit_breaker_level": self.circuit_breaker_level,
            "circuit_breaker_name": self.circuit_breaker_name,
            "drawdown_bps": self.drawdown_bps,
        }


@dataclass
class TradeRecord:
    """Trade record for on-chain logging."""

    symbol: str
    side: int  # 0=BUY, 1=SELL
    notional: int  # in wei
    price: int  # 18 decimals
    quantity: int  # 18 decimals
    leverage_bps: int
    realized_pnl: int  # in wei, negative = loss
    order_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "notional": self.notional,
            "price": self.price,
            "quantity": self.quantity,
            "leverage_bps": self.leverage_bps,
            "realized_pnl": self.realized_pnl,
            "order_id": self.order_id,
        }


class RulesEnforcer:
    """
    On-chain rule enforcement for TSAR.

    Checks rules before trades, logs trades after execution,
    monitors rule enforcement events, and alerts on violations.

    Supports both Rust bridge mode and pure Python fallback.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the rules enforcer.

        Args:
            config: Blockchain configuration dict with keys:
                - rpc_url: WebSocket RPC endpoint
                - chain_id: Chain ID (137=Polygon, 80001=Mumbai)
                - private_key: Signing key (hex, no 0x prefix)
                - kill_switch_address: KillSwitch contract address
                - mandate_address: Mandate contract address
                - audit_trail_address: AuditTrail contract address
                - governance_address: Governance contract address
                - gas_price_gwei: Gas price (default: 30)
                - gas_limit: Gas limit (default: 500000)
        """
        self.config = config
        self._connected = False
        self._rust_client = None
        self._web3 = None

        # Event callbacks
        self._on_kill_switch_activated: list[Callable] = []
        self._on_kill_switch_deactivated: list[Callable] = []
        self._on_circuit_breaker_changed: list[Callable] = []
        self._on_order_blocked: list[Callable] = []
        self._on_enforcement_action: list[Callable] = []

        # Monitoring state
        self._monitoring = False
        self._monitor_task = None

        # Try to load Rust bridge
        self._rust_available = self._try_load_rust()

    def _try_load_rust(self) -> bool:
        """Try to load the Rust bridge."""
        try:
            import trading_rs  # noqa: F401

            logger.info("Rust bridge available — using native performance")
            return True
        except ImportError:
            logger.info("Rust bridge not available — using pure Python fallback")
            return False

    def connect(self) -> None:
        """Connect to the blockchain and initialize contracts."""
        if self._rust_available:
            self._connect_rust()
        else:
            self._connect_web3()
        self._connected = True
        logger.info("Rules enforcer connected")

    def _connect_rust(self) -> None:
        """Connect via Rust bridge."""
        import trading_rs

        self._rust_client = trading_rs.RulesEnforcer(self.config)
        self._rust_client.connect()
        logger.info("Rust bridge connected: %s", self._rust_client.signer_address())

    def _connect_web3(self) -> None:
        """Connect via web3.py fallback."""
        try:
            from web3 import Web3
            from web3.middleware import geth_poa_middleware
        except ImportError:
            raise RuntimeError(
                "Neither Rust bridge nor web3.py available. "
                "Install with: pip install web3"
            ) from None

        rpc_url = self.config.get("rpc_url", "")
        if rpc_url.startswith("wss://"):
            from web3 import WebsocketProvider
            self._web3 = Web3(WebsocketProvider(rpc_url))
        else:
            from web3 import HTTPProvider
            self._web3 = Web3(HTTPProvider(rpc_url.replace("wss://", "https://")))

        # Inject PoA middleware for Polygon
        self._web3.middleware_onion.inject(geth_poa_middleware, layer=0)

        if not self._web3.is_connected():
            raise ConnectionError(f"Failed to connect to {rpc_url}")

        logger.info("web3.py connected: chain_id=%s", self._web3.eth.chain_id)

    @property
    def is_connected(self) -> bool:
        """Whether the enforcer is connected to the blockchain."""
        return self._connected

    # ═══════════════════════════════════════════════════════════
    # PRE-TRADE RULE CHECKING
    # ═══════════════════════════════════════════════════════════

    def is_trading_allowed(self) -> bool:
        """
        Check if trading is allowed by the kill switch.

        FAIL-SAFE: Returns False (block trading) if:
          - Not connected
          - Rust unavailable AND web3 not functional
          - Any unexpected error

        Returns:
            True if trading is allowed, False if kill switch is active
            or if the check cannot be performed.
        """
        try:
            self._ensure_connected()
        except RuntimeError:
            # Not connected — fail-safe: block trading
            logger.error("is_trading_allowed: not connected — FAIL-SAFE: blocking trading")
            return False

        if self._rust_available:
            try:
                return self._rust_client.is_trading_allowed()
            except Exception as exc:
                logger.error("is_trading_allowed: Rust call failed — FAIL-SAFE: blocking trading: %s", exc)
                return False

        # Pure Python: call contract view function
        try:
            return self._web3_call("kill_switch", "isTradingAllowed")
        except (NotImplementedError, Exception) as exc:
            # FAIL-SAFE: If we can't verify kill switch status, assume trading is BLOCKED
            logger.error(
                "is_trading_allowed: web3 call failed — FAIL-SAFE: blocking trading: %s", exc,
            )
            return False

    def get_kill_switch_status(self) -> KillSwitchStatus:
        """
        Get full kill switch status.

        Returns:
            KillSwitchStatus with all fields.
        """
        self._ensure_connected()

        if self._rust_available:
            data = self._rust_client.get_kill_switch_status()
            return KillSwitchStatus(**data)

        # Pure Python fallback
        result = self._web3_call("kill_switch", "getStatus")
        return KillSwitchStatus(
            active=result[0],
            reason=result[1],
            activated_at=result[2],
            daily_pnl_bps=result[3],
            circuit_breaker_level=result[4],
            drawdown_bps=result[5],
        )

    def check_order(
        self,
        symbol: str,
        order_type: int = 0,
        side: int = 0,
        notional_bps: int = 0,
        leverage_bps: int = 100,
        daily_trade_count: int = 0,
    ) -> RuleCheckResult:
        """
        Check if an order complies with on-chain rules.

        Performs two checks:
        1. Kill switch — is trading allowed at all?
        2. Mandate — does this specific order comply?

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            order_type: 0=MARKET, 1=LIMIT, 2=STOP_MARKET, 3=STOP_LIMIT
            side: 0=BUY, 1=SELL
            notional_bps: Trade notional as basis points of equity
            leverage_bps: Requested leverage in basis points
            daily_trade_count: Current daily trade count

        Returns:
            RuleCheckResult with allowed, reason, rule_id.
        """
        self._ensure_connected()

        # Check kill switch first
        if not self.is_trading_allowed():
            status = self.get_kill_switch_status()
            result = RuleCheckResult(
                allowed=False,
                reason=f"Kill switch active: {status.reason}",
                rule_id="kill_switch",
            )
            for cb in self._on_kill_switch_activated:
                try:
                    cb(status)
                except Exception as e:
                    logger.error("Kill switch callback error: %s", e)
            return result

        # Check mandate on-chain
        if self._rust_available:
            # Rust bridge handles the full check
            data = self._rust_client.check_order(
                symbol, order_type, side, notional_bps, leverage_bps, daily_trade_count
            )
            result = RuleCheckResult(**data)
        else:
            result = self._check_order_web3(
                symbol, order_type, side, notional_bps, leverage_bps, daily_trade_count
            )

        # Fire callbacks if blocked
        if not result.allowed:
            for cb in self._on_order_blocked:
                try:
                    cb(result)
                except Exception as e:
                    logger.error("Order blocked callback error: %s", e)

        return result

    def _check_order_web3(
        self,
        symbol: str,
        order_type: int,
        side: int,
        notional_bps: int,
        leverage_bps: int,
        daily_trade_count: int,
    ) -> RuleCheckResult:
        """Check order via web3.py.

        FAIL-SAFE: Returns allowed=False on any error.
        """
        symbol_hash = self._hash_symbol(symbol)

        try:
            result = self._web3_transact(
                "mandate",
                "checkOrder",
                symbol_hash,
                order_type,
                side,
                notional_bps,
                leverage_bps,
                daily_trade_count,
            )
            return RuleCheckResult(
                allowed=result[0],
                reason=result[1] if not result[0] else "",
                rule_id="mandate",
            )
        except NotImplementedError:
            # FAIL-SAFE: web3 not implemented — REJECT trade
            logger.error("Mandate check: web3 not implemented — FAIL-SAFE: rejecting order")
            return RuleCheckResult(
                allowed=False,
                reason="On-chain enforcement unavailable (web3 not implemented) — trade rejected for safety",
                rule_id="mandate_unavailable",
            )
        except Exception as e:
            logger.error("Mandate check failed: %s", e)
            return RuleCheckResult(
                allowed=False,
                reason=f"On-chain check failed: {e}",
                rule_id="mandate_error",
            )

    # ═══════════════════════════════════════════════════════════
    # POST-TRADE LOGGING
    # ═══════════════════════════════════════════════════════════

    def log_trade(self, trade: TradeRecord) -> int:
        """
        Log a trade execution on-chain.

        Args:
            trade: TradeRecord with all trade details.

        Returns:
            Trade ID (on-chain trade count).
        """
        self._ensure_connected()

        if self._rust_available:
            return self._rust_client.log_trade(
                trade.symbol,
                trade.side,
                trade.notional,
                trade.price,
                trade.quantity,
                trade.leverage_bps,
                trade.realized_pnl,
                trade.order_id,
            )

        # Pure Python fallback
        symbol_hash = self._hash_symbol(trade.symbol)
        order_hash = self._hash_symbol(trade.order_id)

        self._web3_transact(
            "audit_trail",
            "logTrade",
            symbol_hash,
            trade.side,
            trade.notional,
            trade.price,
            trade.quantity,
            trade.leverage_bps,
            trade.realized_pnl,
            order_hash,
        )

        return self._web3_call("audit_trail", "tradeCount")

    def log_rule_check(
        self,
        rule_id: str,
        symbol: str,
        passed: bool,
        reason: str,
    ) -> None:
        """
        Log a rule check result on-chain.

        Args:
            rule_id: Identifier for the rule checked.
            symbol: Symbol being checked.
            passed: Whether the check passed.
            reason: Human-readable reason.
        """
        self._ensure_connected()

        if self._rust_available:
            self._rust_client.log_rule_check(rule_id, symbol, passed, reason)
            return

        rule_hash = self._hash_symbol(rule_id)
        symbol_hash = self._hash_symbol(symbol)
        self._web3_transact(
            "audit_trail", "logRuleCheck", rule_hash, symbol_hash, passed, reason
        )

    def log_enforcement_action(
        self,
        action_type: int,
        rule_id: str,
        details: str,
    ) -> None:
        """
        Log an enforcement action on-chain.

        Args:
            action_type: 0=KILL_SWITCH, 1=MANDATE_BLOCK, 2=POSITION_LIMIT, 3=LEVERAGE_BLOCK
            rule_id: The rule that triggered enforcement.
            details: Human-readable details.
        """
        self._ensure_connected()

        if self._rust_available:
            self._rust_client.log_enforcement_action(action_type, rule_id, details)
            return

        rule_hash = self._hash_symbol(rule_id)
        self._web3_transact(
            "audit_trail", "logEnforcementAction", action_type, rule_hash, details
        )

    # ═══════════════════════════════════════════════════════════
    # EQUITY & P&L UPDATES
    # ═══════════════════════════════════════════════════════════

    def update_daily_pnl(self, pnl_bps: int) -> None:
        """
        Update daily P&L on the kill switch contract.

        If daily loss exceeds threshold, kill switch activates automatically.

        Args:
            pnl_bps: Current daily P&L in basis points (negative = loss).
        """
        self._ensure_connected()

        if self._rust_available:
            self._rust_client.update_daily_pnl(pnl_bps)
            return

        self._web3_transact("kill_switch", "updateDailyPnl", pnl_bps)

    def update_equity(self, equity: int) -> None:
        """
        Update equity on the kill switch contract.

        Updates high water mark and checks drawdown circuit breakers.

        Args:
            equity: Current portfolio equity in wei.
        """
        self._ensure_connected()

        if self._rust_available:
            self._rust_client.update_equity(equity)
            return

        self._web3_transact("kill_switch", "updateEquity", equity)

    # ═══════════════════════════════════════════════════════════
    # EVENT MONITORING
    # ═══════════════════════════════════════════════════════════

    def on_kill_switch_activated(self, callback: Callable[[KillSwitchStatus], None]) -> None:
        """Register a callback for kill switch activation events."""
        self._on_kill_switch_activated.append(callback)

    def on_kill_switch_deactivated(self, callback: Callable) -> None:
        """Register a callback for kill switch deactivation events."""
        self._on_kill_switch_deactivated.append(callback)

    def on_circuit_breaker_changed(self, callback: Callable) -> None:
        """Register a callback for circuit breaker level changes."""
        self._on_circuit_breaker_changed.append(callback)

    def on_order_blocked(self, callback: Callable[[RuleCheckResult], None]) -> None:
        """Register a callback for blocked orders."""
        self._on_order_blocked.append(callback)

    def on_enforcement_action(self, callback: Callable) -> None:
        """Register a callback for enforcement actions."""
        self._on_enforcement_action.append(callback)

    def start_monitoring(self) -> None:
        """
        Start monitoring on-chain events in the background.

        Events are dispatched to registered callbacks.
        """
        if self._monitoring:
            logger.warning("Monitoring already started")
            return

        self._monitoring = True
        logger.info("Starting on-chain event monitoring")

        # In production, this would use WebSocket event subscriptions
        # via the Rust bridge or web3.py event filters

    def stop_monitoring(self) -> None:
        """Stop monitoring on-chain events."""
        self._monitoring = False
        logger.info("Stopped on-chain event monitoring")

    # ═══════════════════════════════════════════════════════════
    # CONVENIENCE METHODS
    # ═══════════════════════════════════════════════════════════

    def get_daily_summary(self, epoch_day: int) -> dict[str, Any]:
        """
        Get daily trade summary from the audit trail.

        Args:
            epoch_day: Epoch day (int(time.time()) // 86400).

        Returns:
            Dict with 'trades' and 'pnl' keys.
        """
        self._ensure_connected()

        if self._rust_available:
            return self._rust_client.get_daily_summary(epoch_day)

        result = self._web3_call("audit_trail", "getDailySummary", epoch_day)
        return {"trades": result[0], "pnl": result[1]}

    def get_symbol_summary(self, symbol: str) -> dict[str, Any]:
        """
        Get symbol trade summary from the audit trail.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Dict with 'trades', 'pnl', 'latest_trade_id' keys.
        """
        self._ensure_connected()

        symbol_hash = self._hash_symbol(symbol)

        if self._rust_available:
            return self._rust_client.get_symbol_summary(symbol)

        result = self._web3_call("audit_trail", "getSymbolSummary", symbol_hash)
        return {
            "trades": result[0],
            "pnl": result[1],
            "latest_trade_id": result[2],
        }

    def check_position_limit(self, notional_bps: int, max_position_bps: int = 1500) -> bool:
        """
        Check if a position size is within limits.

        FAIL-SAFE: Returns False (reject) if check cannot be performed.

        Args:
            notional_bps: Trade notional as basis points of equity.
            max_position_bps: Maximum allowed position in bps (default: 1500 = 15%).

        Returns:
            True if within limits, False if exceeded or check fails.
        """
        try:
            self._ensure_connected()
        except RuntimeError:
            logger.error("check_position_limit: not connected — FAIL-SAFE: rejecting")
            return False

        if not self.is_trading_allowed():
            return False

        if self._rust_available:
            try:
                return self._rust_client.check_position_limit(notional_bps, max_position_bps)
            except Exception as exc:
                logger.error("check_position_limit: Rust failed — FAIL-SAFE: rejecting: %s", exc)
                return False

        try:
            return self._web3_call(
                "kill_switch", "checkPositionLimit", notional_bps, max_position_bps
            )
        except (NotImplementedError, Exception) as exc:
            logger.error("check_position_limit: web3 failed — FAIL-SAFE: rejecting: %s", exc)
            return False

    # ═══════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _hash_symbol(symbol: str) -> bytes:
        """Hash a symbol string to bytes32 (keccak256)."""
        try:
            from web3 import Web3
            return Web3.keccak(text=symbol)
        except ImportError:
            # Fallback: use sha256 (not keccak256, but functional for testing)
            return hashlib.sha256(symbol.encode()).digest()

    def _ensure_connected(self) -> None:
        """Ensure the enforcer is connected."""
        if not self._connected:
            raise RuntimeError("Rules enforcer not connected. Call connect() first.")

    def _web3_call(self, contract: str, method: str, *args: Any) -> Any:
        """Call a contract view function via web3.py."""
        # Placeholder — in production, load ABI and call contract
        raise NotImplementedError("Pure Python web3 calls not yet implemented")

    def _web3_transact(self, contract: str, method: str, *args: Any) -> Any:
        """Submit a contract transaction via web3.py."""
        # Placeholder — in production, load ABI and submit tx
        raise NotImplementedError("Pure Python web3 transactions not yet implemented")

    def __repr__(self) -> str:
        mode = "rust" if self._rust_available else "python"
        status = "connected" if self._connected else "disconnected"
        return f"<RulesEnforcer mode={mode} status={status}>"
