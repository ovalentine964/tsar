"""
TSAR Blockchain Backend — On-chain rule enforcement.

Provides Python bindings for interacting with TSAR smart contracts:
- KillSwitch: Auto-halt on daily loss breach
- Mandate: Allowed symbols, leverage, position limits
- AuditTrail: Immutable trade and rule enforcement logging
- Governance: Multi-sig + timelock admin
"""

from .rules_enforcer import RulesEnforcer

__all__ = ["RulesEnforcer"]
