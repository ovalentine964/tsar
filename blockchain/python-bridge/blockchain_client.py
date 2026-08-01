"""
TSAR Blockchain Rules Enforcement — Python Bridge (PyO3)

This module provides Python bindings for interacting with TSAR's
on-chain smart contracts via the Rust blockchain client.

ARCHITECTURE:
  Python (off-chain) → PyO3 (this module) → Rust → ethers-rs → Polygon

DESIGN:
  - Off-chain: Python checks rules (fast path, ~0.1ms)
  - On-chain: Smart contract verifies enforcement (trust layer, ~2s)
  - Both must agree for a trade to proceed
  - On-chain has final authority (cannot be bypassed)

USAGE:
  from tsar.blockchain import BlockchainClient

  client = BlockchainClient(
      rpc_url="https://polygon-rpc.com",
      private_key="0x...",
      chain_id=137,
      contracts={...}
  )

  # Check if trading is allowed (THE authoritative check)
  if not client.is_trading_allowed():
      raise KillSwitchActiveError("Trading halted by on-chain kill switch")

  # Check order compliance with mandate
  result = client.check_order(symbol="BTC/USDT", order_type=0, side=0, ...)
  if not result["allowed"]:
      raise MandateViolationError(result["reason"])

  # Record trade on-chain (immutable audit trail)
  client.record_trade(symbol="BTC/USDT", side="BUY", quantity=0.1, price=50000)
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════


class CircuitBreakerLevel(Enum):
    """On-chain circuit breaker levels."""
    GREEN = 0
    YELLOW = 1
    ORANGE = 2
    RED = 3


class RiskCheckResult(Enum):
    """On-chain risk check result."""
    PASS = 0
    FAIL = 1
    VETO = 2


class EnforcementAction(Enum):
    """On-chain enforcement action."""
    NONE = 0
    SIZE_REDUCED = 1
    TRADE_BLOCKED = 2
    KILL_SWITCH = 3
    CIRCUIT_BREAKER = 4


@dataclass
class KillSwitchStatus:
    """On-chain kill switch status."""
    active: bool
    reason: str
    activated_at: int
    daily_pnl_bps: int
    circuit_breaker_level: CircuitBreakerLevel
    drawdown_bps: int


@dataclass
class OrderCheckResult:
    """Result of on-chain order check."""
    allowed: bool
    reason: str


@dataclass
class PositionCheckResult:
    """Result of on-chain position limit check."""
    passed: bool
    reason: str


@dataclass
class TradeRecord:
    """Trade record for on-chain audit trail."""
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: int
    trade_id: str = ""


@dataclass
class RiskCheckRecord:
    """Risk check record for on-chain audit trail."""
    signal_id: str
    result: RiskCheckResult
    action: EnforcementAction
    reason: str


@dataclass
class RuleEnforcementRecord:
    """Rule enforcement record for on-chain audit trail."""
    rule_id: str
    trade_id: str
    action: EnforcementAction
    reason: str


# ═══════════════════════════════════════════════════════════════════
# BLOCKCHAIN CLIENT (PYTHON)
# ═══════════════════════════════════════════════════════════════════


class BlockchainClient:
    """
    Python client for TSAR's on-chain rules enforcement.

    This is the bridge between Python (brain) and Solidity (trust layer).
    All calls go through Rust (ethers-rs) for performance and safety.

    INTEGRATION WITH TSAR:
      - Used by RiskGovernor to verify on-chain state
      - Used by ExecutionEngine to record trades
      - Used by AuditLogger to log risk checks
    """

    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        chain_id: int,
        contracts: dict[str, str],
    ):
        """
        Initialize the blockchain client.

        Args:
            rpc_url: Polygon RPC endpoint
            private_key: Operator wallet private key
            chain_id: Chain ID (137 for mainnet, 80001 for testnet)
            contracts: Contract addresses (kill_switch, mandate, position_limits, audit_trail)
        """
        self._rpc_url = rpc_url
        self._private_key = private_key
        self._chain_id = chain_id
        self._contracts = contracts

        # Rust client (initialized lazily)
        self._rust_client = None

        logger.info(
            f"BlockchainClient initialized: chain={chain_id}, "
            f"contracts={list(contracts.keys())}"
        )

    def _get_rust_client(self):
        """Get or create the Rust client (lazy initialization)."""
        if self._rust_client is None:
            try:
                # Import the Rust bindings (compiled via PyO3)
                from tsar_blockchain import TSARBlockchainClient

                self._rust_client = TSARBlockchainClient(
                    rpc_url=self._rpc_url,
                    private_key=self._private_key,
                    chain_id=self._chain_id,
                    kill_switch_address=self._contracts["kill_switch"],
                    mandate_address=self._contracts["mandate"],
                    position_limits_address=self._contracts["position_limits"],
                    audit_trail_address=self._contracts["audit_trail"],
                )
            except ImportError:
                logger.warning(
                    "Rust blockchain bindings not available. "
                    "Using mock implementation for development."
                )
                self._rust_client = MockRustClient()

        return self._rust_client

    # ── KILL SWITCH ──────────────────────────────────────────────

    def is_trading_allowed(self) -> bool:
        """
        Check if trading is allowed on-chain.

        This is THE authoritative check. Returns False if kill switch is active.
        Python RiskGovernor should check this before every trade.

        Returns:
            True if trading is allowed, False if kill switch is active.
        """
        try:
            client = self._get_rust_client()
            return client.is_trading_allowed()
        except Exception as e:
            logger.error(f"Failed to check kill switch: {e}")
            # FAIL-SAFE: If we can't check, assume active (halt trading)
            return False

    def get_kill_switch_status(self) -> KillSwitchStatus:
        """
        Get full kill switch status from on-chain.

        Returns:
            KillSwitchStatus with all relevant state.
        """
        try:
            client = self._get_rust_client()
            status = client.get_kill_switch_status()

            return KillSwitchStatus(
                active=status["active"],
                reason=status["reason"],
                activated_at=status["activated_at"],
                daily_pnl_bps=status["daily_pnl_bps"],
                circuit_breaker_level=CircuitBreakerLevel(status["circuit_breaker_level"]),
                drawdown_bps=status["drawdown_bps"],
            )
        except Exception as e:
            logger.error(f"Failed to get kill switch status: {e}")
            # FAIL-SAFE: Return active status
            return KillSwitchStatus(
                active=True,
                reason=f"Status check failed: {e}",
                activated_at=0,
                daily_pnl_bps=0,
                circuit_breaker_level=CircuitBreakerLevel.RED,
                drawdown_bps=0,
            )

    def update_daily_pnl(self, daily_pnl_bps: int) -> bool:
        """
        Update daily P&L on-chain.

        If daily loss exceeds -2% (threshold), kill switch activates AUTOMATICALLY.
        This cannot be prevented by any code path — it's enforced by the smart contract.

        Args:
            daily_pnl_bps: Current daily P&L in basis points (negative = loss)

        Returns:
            True if transaction was successful.
        """
        try:
            client = self._get_rust_client()
            client.update_daily_pnl(daily_pnl_bps)
            return True
        except Exception as e:
            logger.error(f"Failed to update daily P&L: {e}")
            return False

    def update_equity(self, equity: float) -> bool:
        """
        Update equity on-chain.

        Checks drawdown circuit breakers. If drawdown exceeds -15%,
        kill switch activates automatically.

        Args:
            equity: Current portfolio equity in USDT.

        Returns:
            True if transaction was successful.
        """
        try:
            # Convert to wei (18 decimals)
            equity_wei = int(equity * 1e18)
            client = self._get_rust_client()
            client.update_equity(equity_wei)
            return True
        except Exception as e:
            logger.error(f"Failed to update equity: {e}")
            return False

    # ── MANDATE ──────────────────────────────────────────────────

    def check_order(
        self,
        symbol: str,
        order_type: int,
        side: int,
        notional_bps: int,
        leverage_bps: int = 100,
        daily_trade_count: int = 0,
    ) -> OrderCheckResult:
        """
        Check if an order complies with the on-chain mandate.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            order_type: 0=MARKET, 1=LIMIT, 2=STOP_MARKET, 3=STOP_LIMIT
            side: 0=BUY, 1=SELL
            notional_bps: Trade notional as basis points of equity
            leverage_bps: Requested leverage in basis points (100 = 1x)
            daily_trade_count: Current daily trade count

        Returns:
            OrderCheckResult with allowed and reason.
        """
        try:
            client = self._get_rust_client()
            result = client.check_order(
                symbol=symbol,
                order_type=order_type,
                side=side,
                notional_bps=notional_bps,
                leverage_bps=leverage_bps,
                daily_trade_count=daily_trade_count,
            )

            return OrderCheckResult(
                allowed=result["allowed"],
                reason=result["reason"],
            )
        except Exception as e:
            logger.error(f"Failed to check order: {e}")
            # FAIL-SAFE: Reject if can't verify
            return OrderCheckResult(
                allowed=False,
                reason=f"Order check failed: {e}",
            )

    # ── POSITION LIMITS ──────────────────────────────────────────

    def check_position_limit(
        self,
        symbol: str,
        sector: str,
        notional: float,
    ) -> PositionCheckResult:
        """
        Check if a position is within on-chain limits.

        Args:
            symbol: Trading pair
            sector: Sector category
            notional: Position notional value in USDT

        Returns:
            PositionCheckResult with passed and reason.
        """
        try:
            # Convert to wei
            notional_wei = int(notional * 1e18)
            client = self._get_rust_client()
            result = client.check_position_limit(
                symbol=symbol,
                sector=sector,
                notional=notional_wei,
            )

            return PositionCheckResult(
                passed=result["passed"],
                reason=result["reason"],
            )
        except Exception as e:
            logger.error(f"Failed to check position limit: {e}")
            # FAIL-SAFE: Reject if can't verify
            return PositionCheckResult(
                passed=False,
                reason=f"Position check failed: {e}",
            )

    # ── AUDIT TRAIL ──────────────────────────────────────────────

    def record_trade(self, trade: TradeRecord) -> bool:
        """
        Record a trade on-chain (immutable audit trail).

        Args:
            trade: TradeRecord with symbol, side, quantity, price, timestamp.

        Returns:
            True if transaction was successful.
        """
        try:
            # Create trade hash
            trade_hash = self._hash_trade(trade)

            client = self._get_rust_client()
            client.record_trade(
                trade_hash=trade_hash,
                symbol=trade.symbol,
                side=trade.side,
                quantity=trade.quantity,
                price=trade.price,
                timestamp=trade.timestamp,
                trade_id=trade.trade_id,
            )

            logger.info(f"Trade recorded on-chain: {trade_hash[:16]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to record trade: {e}")
            return False

    def log_risk_check(self, check: RiskCheckRecord) -> bool:
        """
        Log a risk check result on-chain.

        Args:
            check: RiskCheckRecord with signal_id, result, action, reason.

        Returns:
            True if transaction was successful.
        """
        try:
            # Create check hash
            check_hash = self._hash_risk_check(check)

            client = self._get_rust_client()
            client.log_risk_check(
                check_hash=check_hash,
                signal_id=check.signal_id,
                result=check.result.value,
                action=check.action.value,
                reason=check.reason,
            )

            logger.info(f"Risk check logged on-chain: {check_hash[:16]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to log risk check: {e}")
            return False

    def log_rule_enforcement(self, enforcement: RuleEnforcementRecord) -> bool:
        """
        Log a rule enforcement action on-chain.

        Args:
            enforcement: RuleEnforcementRecord with rule_id, trade_id, action, reason.

        Returns:
            True if transaction was successful.
        """
        try:
            # Create rule hash
            rule_hash = self._hash_rule_enforcement(enforcement)

            client = self._get_rust_client()
            client.log_rule_enforcement(
                rule_hash=rule_hash,
                rule_id=enforcement.rule_id,
                trade_id=enforcement.trade_id,
                action=enforcement.action.value,
                reason=enforcement.reason,
            )

            logger.info(f"Rule enforcement logged on-chain: {rule_hash[:16]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to log rule enforcement: {e}")
            return False

    # ── HASHING HELPERS ──────────────────────────────────────────

    @staticmethod
    def _hash_trade(trade: TradeRecord) -> str:
        """Create a deterministic hash of trade details."""
        data = f"{trade.symbol}:{trade.side}:{trade.quantity}:{trade.price}:{trade.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def _hash_risk_check(check: RiskCheckRecord) -> str:
        """Create a deterministic hash of risk check details."""
        data = f"{check.signal_id}:{check.result.value}:{check.action.value}:{check.reason}"
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def _hash_rule_enforcement(enforcement: RuleEnforcementRecord) -> str:
        """Create a deterministic hash of rule enforcement details."""
        data = f"{enforcement.rule_id}:{enforcement.trade_id}:{enforcement.action.value}:{enforcement.reason}"
        return hashlib.sha256(data.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# MOCK CLIENT (FOR DEVELOPMENT/TESTING)
# ═══════════════════════════════════════════════════════════════════


class MockRustClient:
    """
    Mock Rust client for development and testing.

    Simulates on-chain behavior without actual blockchain interaction.
    Useful for unit tests and local development.
    """

    def __init__(self):
        self._trading_allowed = True
        self._daily_pnl_bps = 0
        self._circuit_breaker_level = 0
        self._trades: list[dict] = []
        self._risk_checks: list[dict] = []

    def is_trading_allowed(self) -> bool:
        return self._trading_allowed

    def get_kill_switch_status(self) -> dict:
        return {
            "active": not self._trading_allowed,
            "reason": "Mock: normal operation",
            "activated_at": 0,
            "daily_pnl_bps": self._daily_pnl_bps,
            "circuit_breaker_level": self._circuit_breaker_level,
            "drawdown_bps": 0,
        }

    def update_daily_pnl(self, daily_pnl_bps: int):
        self._daily_pnl_bps = daily_pnl_bps
        # Auto-activate kill switch if loss exceeds -2%
        if daily_pnl_bps <= -200:
            self._trading_allowed = False
            logger.warning(f"MOCK: Kill switch activated — daily P&L {daily_pnl_bps} bps")

    def update_equity(self, equity_wei: int):
        pass  # Mock: no-op

    def check_order(self, **kwargs) -> dict:
        # Mock: always allow
        return {"allowed": True, "reason": ""}

    def check_position_limit(self, **kwargs) -> dict:
        # Mock: always pass
        return {"passed": True, "reason": ""}

    def record_trade(self, **kwargs):
        self._trades.append(kwargs)
        logger.info(f"MOCK: Trade recorded: {kwargs.get('trade_hash', 'unknown')[:16]}...")

    def log_risk_check(self, **kwargs):
        self._risk_checks.append(kwargs)
        logger.info(f"MOCK: Risk check logged: {kwargs.get('check_hash', 'unknown')[:16]}...")

    def log_rule_enforcement(self, **kwargs):
        logger.info(f"MOCK: Rule enforcement logged: {kwargs.get('rule_hash', 'unknown')[:16]}...")
