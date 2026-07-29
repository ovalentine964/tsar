"""
TSAR Interface — RiskEngine Abstract Base Class.

Abstracts all risk computation — position sizing, drawdown tracking,
circuit breakers, and the kill switch. All risk rules are DETERMINISTIC.
No LLM involvement. This engine enforces the harness — the intelligence
layer cannot override it.

Day1: PyRiskEngine (Python deterministic rule-based)
Level 2: RustRiskEngine (Rust-accelerated via PyO3)
Level 5: GpuMonteCarloEngine (CUDA Monte Carlo for VaR)
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.interfaces.types import (
        DrawdownState,
        Portfolio,
        RiskDecision,
        Signal,
    )


class RiskEngine(abc.ABC):
    """Abstract interface for risk management computation.

    The Risk Guardian agent uses this engine to approve or reject
    every trade. All rules are deterministic — no LLM, no heuristics.

    Implements the canonical risk limits from TSAR_ARCHITECTURE.md §6.1:
    - Daily loss limit: -2% of capital
    - Max drawdown: 5% from HWM
    - Max open positions: 10 (Day1: 3)
    - Max single position: 15% of capital
    - Min risk-reward: 2:1
    - Kelly fraction: 0.25 (fixed)

    Day1: PyRiskEngine — Python rule-based risk checks.
    Level 2: RustRiskEngine — Rust-accelerated risk computation.
    Level 5: GpuMonteCarloEngine — CUDA Monte Carlo for VaR.
    """

    # ═══════════════════════════════════════════════════════════════
    # PRE-TRADE RISK CHECKS
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    def check_risk(
        self,
        signal: Signal,
        portfolio: Portfolio,
    ) -> RiskDecision:
        """Run all pre-trade risk checks on a proposed signal.

        This is THE GATEKEEPER. Every trade must pass this check.
        Implements the 10-point evaluation checklist and the 4-level
        VETO protocol from TSAR_ARCHITECTURE.md §3.4.

        Checks performed (all must pass):
        1. Position size ≤ max single position (15% of equity)
        2. Daily P&L not below -2% loss limit
        3. Open positions < max (10, Day1: 3)
        4. Stop-loss is set and reasonable (≤ 2% from entry)
        5. Risk-reward ratio ≥ 2:1
        6. Not trading same symbol within cooldown (30 min)
        7. No conflicting positions
        8. Signal score meets minimum threshold

        Args:
            signal: The trading signal to evaluate.
            portfolio: Current portfolio state.

        Returns:
            RiskDecision with approval status, recommended position size,
            and any rejection reasons or warnings.
        """
        ...

    # ═══════════════════════════════════════════════════════════════
    # POSITION SIZING
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    def calculate_position_size(
        self,
        signal: Signal,
        portfolio: Portfolio,
    ) -> float:
        """Calculate the recommended position size for a signal.

        Uses the canonical sizing method (Half-Kelly with 0.25 fraction,
        hard-capped at 2% risk per trade).

        Args:
            signal: The trading signal (provides entry, stop-loss).
            portfolio: Current portfolio state (provides equity).

        Returns:
            Recommended position quantity (in base asset units).
            Returns 0.0 if the signal does not pass basic sizing checks.
        """
        ...

    # ═══════════════════════════════════════════════════════════════
    # DRAWDOWN MONITORING
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    def get_drawdown_state(self, portfolio: Portfolio) -> DrawdownState:
        """Get the current drawdown state and circuit breaker level.

        Implements the circuit breaker protocol from TSAR_ARCHITECTURE.md §6.2::

            GREEN:   Drawdown < 2%       → Normal operation
            YELLOW:  Drawdown 2-3%       → Reduce position sizes 50%
            ORANGE:  Drawdown 3-5%       → Close new trades only, no new entries
            RED:     Drawdown > 5%       → KILL SWITCH — flatten everything

        Args:
            portfolio: Current portfolio state.

        Returns:
            DrawdownState with circuit breaker level, trading permissions,
            and position size multiplier.
        """
        ...

    # ═══════════════════════════════════════════════════════════════
    # KILL SWITCH
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    def get_kill_switch_status(self) -> bool:
        """Check if the kill switch is currently active.

        The kill switch is the single most critical piece of state in the
        system. When active, ALL trading is halted.

        Dual-write architecture: reads from Redis first, falls back to
        file (/tmp/tsar_kill_switch). File is primary safety net — survives
        Redis failure.

        Returns:
            True if the kill switch is active (trading halted), False otherwise.
        """
        ...

    @abc.abstractmethod
    def activate_kill_switch(self, reason: str) -> None:
        """Activate the kill switch — halt ALL trading immediately.

        Triggers:
        1. Write kill switch state to file (PRIMARY — survives Redis failure).
        2. Write kill switch state to Redis (SECONDARY).
        3. Cancel ALL open orders.
        4. Close ALL positions (market orders).
        5. Set system to HALTED state.
        6. Send notification alerts.

        Args:
            reason: Human-readable reason for activation (logged immutably).
        """
        ...

    @abc.abstractmethod
    def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch — resume trading.

        Requires manual trigger (e.g. Telegram /start command).
        Clears the kill switch state in both file and Redis.

        After deactivation, the Gated Recovery Protocol applies:
        position sizes ramp up gradually (10% → 25% → 50% → 100%)
        over 24-72 hours depending on the circuit breaker level that
        triggered the kill switch.
        """
        ...
