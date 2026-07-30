"""
TSAR Risk Module — Deterministic risk management subsystem.

All components are rule-based. ZERO LLM calls. ZERO external API calls
(except Redis for kill switch state).

Components:
  - RiskGovernor:      Central orchestrator — 7-layer veto protocol
  - PositionSizer:     Half-Kelly sizing with 2% hard cap + fee-aware + micro-capital
  - DrawdownMonitor:   4-level circuit breaker (GREEN/YELLOW/ORANGE/RED)
  - AntiBehavioralGuards: Anti-revenge, anti-greed, anti-FOMO, anti-overconfidence
  - GuardStatePersistence: SQLite-backed guard state (survives restarts)
  - KillSwitch:        Dual-write emergency halt (Redis + file)
  - Watchdog:          External process health monitor for kill switch
  - Mandate:           Human-committed trading authorization boundary
  - MandateGate:       Pre-risk authorization gate for the pipeline
"""

from src.risk.drawdown import DrawdownConfig, DrawdownMonitor
from src.risk.governor import RiskGovernor
from src.risk.guard_state import GuardStatePersistence
from src.risk.guards import AntiBehavioralGuards, GuardDecision, GuardsConfig
from src.risk.kill_switch import KillSwitch
from src.risk.mandate import Mandate, MandateDecision, MandateRules, MandateState
from src.risk.mandate_gate import MandateGate
from src.risk.position_sizer import PositionSizer, SizingConfig
from src.risk.watchdog import Watchdog, WatchdogConfig

__all__ = [
    # Core orchestrator
    "RiskGovernor",
    # Components
    "PositionSizer",
    "DrawdownMonitor",
    "AntiBehavioralGuards",
    "KillSwitch",
    "Watchdog",
    "WatchdogConfig",
    "GuardStatePersistence",
    # Mandate
    "Mandate",
    "MandateGate",
    "MandateRules",
    "MandateState",
    "MandateDecision",
    # Configs
    "SizingConfig",
    "DrawdownConfig",
    "GuardsConfig",
    # Results
    "GuardDecision",
]
