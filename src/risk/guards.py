"""
Anti-Behavioral Guards — Detect and prevent trading biases.

Four guards, all deterministic:
  1. Anti-Revenge:  3 consecutive losses → 60-min cooldown
  2. Anti-Greed:    5+ win streak → 70% sizing
  3. Anti-FOMO:     Only registered setup types, min signal score
  4. Anti-Overconfidence: High conviction cap after win streak

All thresholds from config/risk.yaml. No LLM, no external calls.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from src.interfaces.types import Signal

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Guard Base Classes (for extensible guard system)
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class GuardResult:
    """Result of a single guard check."""
    passed: bool = True
    guard_name: str = ""
    reason: str = ""
    severity: str = "INFO"  # INFO, WARNING, HIGH, CRITICAL


class Guard:
    """Base class for pluggable risk guards."""

    def __init__(self, name: str) -> None:
        self.name = name

    def check(self, order: Any) -> GuardResult:
        """Check an order against this guard. Override in subclasses."""
        return GuardResult(passed=True, guard_name=self.name)



@dataclass(frozen=True)
class GuardsConfig:
    """Immutable guards configuration from risk.yaml."""

    anti_revenge_cooldown_minutes: int = 60
    anti_revenge_loss_streak: int = 3
    anti_greed_sizing_factor: float = 0.7
    anti_greed_win_streak: int = 5
    anti_fomo_min_signal_score: float = 0.6
    anti_overconfidence_win_streak: int = 5


@dataclass
class GuardState:
    """Mutable state tracked by the guards."""

    consecutive_losses: int = 0
    consecutive_wins: int = 0
    last_loss_timestamp: float = 0.0
    trade_results: list[bool] = field(default_factory=list)


@dataclass(frozen=True)
class GuardDecision:
    """Result of all guard checks combined."""

    approved: bool = True
    veto_reason: str = ""
    size_multiplier: float = 1.0
    warnings: tuple[str, ...] = ()


class AntiBehavioralGuards:
    """Deterministic anti-behavioral bias guards.

    Tracks trade outcomes and applies progressive restrictions.
    All logic is rule-based — zero LLM involvement.
    """

    def __init__(
        self,
        config: GuardsConfig | None = None,
        state: GuardState | None = None,
    ) -> None:
        self._config = config or GuardsConfig()
        self._state = state or GuardState()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self, signal: Signal) -> GuardDecision:
        """Run all four guards on a proposed signal.

        Returns the first hard veto, or combines soft restrictions.
        """
        warnings: list[str] = []
        size_multiplier = 1.0

        # --- 1. Anti-Revenge ---
        revenge = self._check_revenge()
        if revenge is not None:
            return GuardDecision(
                approved=False,
                veto_reason=revenge,
                size_multiplier=0.0,
                warnings=tuple(warnings),
            )

        # --- 2. Anti-FOMO ---
        fomo = self._check_fomo(signal)
        if fomo is not None:
            return GuardDecision(
                approved=False,
                veto_reason=fomo,
                size_multiplier=0.0,
                warnings=tuple(warnings),
            )

        # --- 3. Anti-Greed ---
        greed_mult, greed_warn = self._check_greed()
        if greed_mult < 1.0:
            size_multiplier = min(size_multiplier, greed_mult)
            if greed_warn:
                warnings.append(greed_warn)

        # --- 4. Anti-Overconfidence ---
        oc_mult, oc_warn = self._check_overconfidence()
        if oc_mult < 1.0:
            size_multiplier = min(size_multiplier, oc_mult)
            if oc_warn:
                warnings.append(oc_warn)

        return GuardDecision(
            approved=True,
            veto_reason="",
            size_multiplier=size_multiplier,
            warnings=tuple(warnings),
        )

    def record_outcome(self, is_win: bool) -> None:
        """Record a trade outcome and update streak counters.

        Args:
            is_win: True if the trade was profitable, False otherwise.
        """
        state = self._state

        if is_win:
            state.consecutive_wins += 1
            state.consecutive_losses = 0
        else:
            state.consecutive_losses += 1
            state.consecutive_wins = 0
            state.last_loss_timestamp = time.time()

        state.trade_results.append(is_win)

        # Keep last 100 outcomes for analysis
        if len(state.trade_results) > 100:
            state.trade_results = state.trade_results[-100:]

        logger.debug(
            f"Guards: recorded {'WIN' if is_win else 'LOSS'} — "
            f"streak: W{state.consecutive_wins}/L{state.consecutive_losses}"
        )

    def reset(self) -> None:
        """Reset all guard state (e.g., after kill switch recovery)."""
        self._state = GuardState()

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _check_revenge(self) -> str | None:
        """Anti-Revenge: block trading after consecutive losses + cooldown."""
        cfg = self._config
        state = self._state

        if state.consecutive_losses < cfg.anti_revenge_loss_streak:
            return None

        # Check if cooldown has elapsed
        if state.last_loss_timestamp > 0:
            elapsed_seconds = time.time() - state.last_loss_timestamp
            cooldown_seconds = cfg.anti_revenge_cooldown_minutes * 60

            if elapsed_seconds < cooldown_seconds:
                remaining = int((cooldown_seconds - elapsed_seconds) / 60) + 1
                return (
                    f"Anti-Revenge: {state.consecutive_losses} consecutive losses. "
                    f"Cooldown active — {remaining} min remaining."
                )
            else:
                # Cooldown elapsed, allow trading
                return None

        # Losses but no timestamp (shouldn't happen, but be safe)
        return (
            f"Anti-Revenge: {state.consecutive_losses} consecutive losses. "
            f"Cooldown of {cfg.anti_revenge_cooldown_minutes} min required."
        )

    def _check_fomo(self, signal: Signal) -> str | None:
        """Anti-FOMO: block low-confidence signals."""
        cfg = self._config

        if signal.score < cfg.anti_fomo_min_signal_score:
            return (
                f"Anti-FOMO: Signal score {signal.score:.2f} is below "
                f"minimum threshold {cfg.anti_fomo_min_signal_score:.2f}."
            )

        return None

    def _check_greed(self) -> tuple[float, str]:
        """Anti-Greed: cap sizing during win streaks.

        Returns (size_multiplier, warning_message).
        """
        cfg = self._config
        state = self._state

        if state.consecutive_wins >= cfg.anti_greed_win_streak:
            return (
                cfg.anti_greed_sizing_factor,
                f"Anti-Greed: {state.consecutive_wins}-win streak detected. "
                f"Position size capped at {cfg.anti_greed_sizing_factor:.0%}.",
            )

        return 1.0, ""

    def _check_overconfidence(self) -> tuple[float, str]:
        """Anti-Overconfidence: warn and cap after extended win streaks.

        Returns (size_multiplier, warning_message).
        """
        cfg = self._config
        state = self._state

        if state.consecutive_wins >= cfg.anti_overconfidence_win_streak:
            # More aggressive cap at higher streaks
            if state.consecutive_wins >= 10:
                return (
                    0.5,
                    f"Anti-Overconfidence: {state.consecutive_wins}-win streak! "
                    f"Position size capped at 50%.",
                )
            return (
                0.7,
                f"Anti-Overconfidence: {state.consecutive_wins}-win streak. "
                f"Position size capped at 70%.",
            )

        return 1.0, ""
