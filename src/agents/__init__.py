"""
TSAR Agents — Autonomous trading agents.

Each agent is a specialized autonomous unit with a single responsibility:
  - Signal Scout:     Scan markets for setups (TRADE_PREVIEW)
  - Risk Guardian:    Gatekeeper — approve/reject trades (TRADE_ADMIN)
  - Execution Sniper: Place orders, manage positions (TRADE_EXECUTE)
  - Orchestrator:     Supervisor, health monitoring (TRADE_ADMIN)
  - Macro Agent:      Macro regime analysis (ANALYSIS)
  - Regime Detector:  Market regime classification (ANALYSIS)
  - Trade Philosopher: Post-trade reflection (ANALYSIS)
  - Strategy Geneticist: Strategy evolution (ANALYSIS)
  - Market Cartographer: Cross-asset correlation (ANALYSIS)
  - Execution Tracker: Position reconciliation (TRADE_EXECUTE)

Agents communicate via Redis Streams using CloudEvents v1.0 messages.
Agents NEVER import concrete backends — they use interface getters.

Event Flow:
  SignalScout → [tsar.signal.detected.v1] → RiskGuardian
    → [tsar.risk.approved.v1 / tsar.risk.vetoed.v1] → ExecutionSniper
    → [tsar.trade.executed.v1 / tsar.trade.failed.v1] → TradePhilosopher
"""

from src.agents.base import BaseAgent
from src.agents.execution_sniper import ExecutionSniper
from src.agents.orchestrator import Orchestrator
from src.agents.risk_guardian import RiskGuardian
from src.agents.signal_scout import SignalScout

__all__: list[str] = [
    "BaseAgent",
    "SignalScout",
    "RiskGuardian",
    "ExecutionSniper",
    "Orchestrator",
]
