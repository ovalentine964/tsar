"""
TSAR Blockchain Rules Enforcement — Python Bridge

This package provides Python bindings for interacting with TSAR's
on-chain smart contracts via the Rust blockchain client.

Usage:
    from tsar.blockchain import BlockchainClient, KillSwitchStatus

    client = BlockchainClient(
        rpc_url="https://polygon-rpc.com",
        private_key="0x...",
        chain_id=137,
        contracts={
            "kill_switch": "0x...",
            "mandate": "0x...",
            "position_limits": "0x...",
            "audit_trail": "0x...",
        }
    )

    # Check if trading is allowed
    if not client.is_trading_allowed():
        raise KillSwitchActiveError("Trading halted by on-chain kill switch")
"""

from .blockchain_client import (
    BlockchainClient,
    CircuitBreakerLevel,
    EnforcementAction,
    KillSwitchStatus,
    MockRustClient,
    OrderCheckResult,
    PositionCheckResult,
    RiskCheckRecord,
    RiskCheckResult,
    RuleEnforcementRecord,
    TradeRecord,
)

__all__ = [
    "BlockchainClient",
    "CircuitBreakerLevel",
    "EnforcementAction",
    "KillSwitchStatus",
    "MockRustClient",
    "OrderCheckResult",
    "PositionCheckResult",
    "RiskCheckRecord",
    "RiskCheckResult",
    "RuleEnforcementRecord",
    "TradeRecord",
]
