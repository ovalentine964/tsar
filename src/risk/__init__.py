"""
TSAR Risk Module — Deterministic risk management subsystem.

All components are rule-based. ZERO LLM calls. ZERO external API calls
(except Redis for kill switch state).

Components:
  - RiskGovernor:      Central orchestrator — 7-layer veto protocol
  - PositionSizer:     Half-Kelly sizing with 2% hard cap
  - DrawdownMonitor:   4-level circuit breaker (GREEN/YELLOW/ORANGE/RED)
  - AntiBehavioralGuards: Anti-revenge, anti-greed, anti-FOMO, anti-overconfidence
  - KillSwitch:        Dual-write emergency halt (Redis + file)
"""

from src.risk.drawdown import DrawdownConfig, DrawdownMonitor
from src.risk.governor import RiskGovernor
from src.risk.guards import AntiBehavioralGuards, GuardDecision, GuardsConfig
from src.risk.kill_switch import KillSwitch
from src.risk.position_sizer import PositionSizer, SizingConfig

__all__ = [
    # Core orchestrator
    "RiskGovernor",
    # Components
    "PositionSizer",
    "DrawdownMonitor",
    "AntiBehavioralGuards",
    "KillSwitch",
    # Configs
    "SizingConfig",
    "DrawdownConfig",
    "GuardsConfig",
    # Results
    "GuardDecision",
]
