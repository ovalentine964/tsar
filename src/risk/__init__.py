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
  - FlashCrashDetector:    Price velocity monitoring & crash detection
  - StopHuntDetector:      Stop-loss spike reversal detection
  - WhipsawFilter:         Rapid price oscillation detection & cooldown
  - LiquidityMonitor:      Order book depth & spread monitoring
  - CorrelationBreakDetector: BTC/ETH correlation regime monitoring
"""

from src.risk.correlation_break import (
    CorrelationBreakDetector,
    CorrelationConfig,
    CorrelationMetrics,
    CorrelationRegime,
)
from src.risk.drawdown import DrawdownConfig, DrawdownMonitor
from src.risk.flash_crash import FlashCrashConfig, FlashCrashDetector, FlashCrashState
from src.risk.governor import RiskGovernor
from src.risk.guard_state import GuardStatePersistence
from src.risk.guards import AntiBehavioralGuards, GuardDecision, GuardsConfig
from src.risk.kill_switch import KillSwitch
from src.risk.liquidity_monitor import (
    LiquidityConfig,
    LiquidityMetrics,
    LiquidityMonitor,
    LiquidityState,
)
from src.risk.mandate import Mandate, MandateDecision, MandateRules, MandateState
from src.risk.mandate_gate import MandateGate
from src.risk.position_sizer import PositionSizer, SizingConfig
from src.risk.stop_hunt import (
    HuntSeverity,
    HuntStatistics,
    StopHuntConfig,
    StopHuntDetector,
)
from src.risk.watchdog import Watchdog, WatchdogConfig
from src.risk.whipsaw import (
    WhipsawConfig,
    WhipsawFilter,
    WhipsawState,
    WhipsawStatistics,
)

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
    # Retail trap prevention
    "FlashCrashDetector",
    "FlashCrashConfig",
    "FlashCrashState",
    "StopHuntDetector",
    "StopHuntConfig",
    "HuntSeverity",
    "HuntStatistics",
    "WhipsawFilter",
    "WhipsawConfig",
    "WhipsawState",
    "WhipsawStatistics",
    "LiquidityMonitor",
    "LiquidityConfig",
    "LiquidityState",
    "LiquidityMetrics",
    # Institutional scenario prevention
    "CorrelationBreakDetector",
    "CorrelationConfig",
    "CorrelationRegime",
    "CorrelationMetrics",
]
