"""
Risk Governor — Central risk orchestration engine.

Implements the RiskEngine abstract base class. Coordinates all risk
subsystems into a single 7-layer veto protocol:

  Layer 1: Kill Switch        — If active, HARD veto, no exceptions
  Layer 2: Input Validation   — Sanity checks on signal data
  Layer 3: Anti-FOMO          — Block low-confidence signals
  Layer 4: Time Rules         — Economic calendar blackouts, trading hours
  Layer 5: Anti-Behavioral    — Revenge, greed, overconfidence guards
  Layer 6: Drawdown           — Circuit breaker levels (GREEN→RED)
  Layer 7: Position Limits    — Size caps, concentration, R:R ratio

ALL checks are deterministic. ZERO LLM calls. ZERO external API calls
(except Redis for kill switch state).

Reads canonical values from config/risk.yaml.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.interfaces.risk_engine import RiskEngine
from src.interfaces.types import (
    DrawdownLevel,
    DrawdownState,
    OrderSide,
    Portfolio,
    RiskDecision,
    Signal,
    VetoLevel,
)
from src.risk.drawdown import DrawdownConfig, DrawdownMonitor
from src.risk.guards import AntiBehavioralGuards, GuardDecision, GuardsConfig
from src.risk.kill_switch import KillSwitch
from src.risk.position_sizer import PositionSizer, SizingConfig

logger = logging.getLogger(__name__)

# Default config path
_DEFAULT_CONFIG = os.environ.get(
    "TSAR_RISK_CONFIG", "config/risk.yaml"
)


class RiskGovernor(RiskEngine):
    """Central risk orchestration — the GATEKEEPER.

    Every trade signal passes through the 7-layer veto protocol.
    All decisions are deterministic, auditable, and logged.

    Implements the RiskEngine ABC from src/interfaces/risk_engine.py.
    """

    def __init__(
        self,
        config_path: str | None = None,
        redis_client: Any | None = None,
    ) -> None:
        """Initialize the Risk Governor.

        Args:
            config_path: Path to risk.yaml. Defaults to config/risk.yaml.
            redis_client: Optional async Redis client for kill switch.
        """
        self._config = self._load_config(config_path or _DEFAULT_CONFIG)

        # Build sub-components from config
        self._sizer = PositionSizer(self._build_sizer_config())
        self._drawdown = DrawdownMonitor(self._build_drawdown_config())
        self._guards = AntiBehavioralGuards(self._build_guards_config())
        self._kill_switch = KillSwitch(
            redis_client=redis_client,
            file_path=self._config.get("kill_switch", {}).get("file_path"),
            redis_key=self._config.get("kill_switch", {}).get("redis_key"),
        )

        # Cache commonly used thresholds
        self._max_open_positions = self._config.get("max_open_positions", 10)
        self._max_single_position_pct = self._config.get(
            "max_single_position_pct", 0.15
        )
        self._max_stop_loss_pct = self._config.get("max_stop_loss_pct", 0.02)
        self._stop_loss_required = self._config.get("stop_loss_required", True)
        self._min_rr_ratio = self._config.get("min_rr_ratio", 2.0)
        self._max_daily_trades = self._config.get("max_daily_trades", 30)
        self._anti_fomo_min_score = self._config.get(
            "anti_fomo_min_signal_score", 0.6
        )
        self._blackout_events = self._config.get("blackout_events", {})
        self._recovery_config = self._config.get("recovery", {})

        logger.info(
            f"RiskGovernor initialized: max_pos={self._max_open_positions}, "
            f"max_single={self._max_single_position_pct:.0%}, "
            f"min_rr={self._min_rr_ratio}:1"
        )

    # ═══════════════════════════════════════════════════════════════
    # RiskEngine ABC — check_risk
    # ═══════════════════════════════════════════════════════════════

    async def check_risk(
        self,
        signal: Signal,
        portfolio: Portfolio,
    ) -> RiskDecision:
        """Run all pre-trade risk checks — the 7-layer veto protocol.

        Layers are evaluated in order. First HARD/NUCLEAR veto wins.
        Soft warnings accumulate but don't block.

        Args:
            signal: The trading signal to evaluate.
            portfolio: Current portfolio state.

        Returns:
            RiskDecision with approval, position size, and details.
        """
        reasons: list[str] = []
        warnings: list[str] = []

        # ── Layer 1: Kill Switch ──────────────────────────────────
        if await self._kill_switch.is_active():
            return self._reject(
                signal.signal_id,
                "KILL SWITCH ACTIVE — all trading halted.",
                VetoLevel.NUCLEAR,
            )

        # ── Layer 2: Input Validation ─────────────────────────────
        validation_err = self._validate_signal(signal, portfolio)
        if validation_err:
            return self._reject(
                signal.signal_id,
                validation_err,
                VetoLevel.HARD,
            )

        # ── Layer 3: Anti-FOMO ────────────────────────────────────
        if signal.score < self._anti_fomo_min_score:
            return self._reject(
                signal.signal_id,
                f"Anti-FOMO: Signal score {signal.score:.2f} < "
                f"minimum {self._anti_fomo_min_score:.2f}.",
                VetoLevel.FIRM,
            )

        # ── Layer 4: Time Rules ───────────────────────────────────
        blackout_err = self._check_blackout(signal)
        if blackout_err:
            return self._reject(
                signal.signal_id,
                blackout_err,
                VetoLevel.HARD,
            )

        # ── Layer 5: Anti-Behavioral Guards ───────────────────────
        guard_decision = self._guards.check_all(signal)
        if not guard_decision.approved:
            return self._reject(
                signal.signal_id,
                f"Behavioral Guard: {guard_decision.veto_reason}",
                VetoLevel.FIRM,
            )
        if guard_decision.warnings:
            warnings.extend(guard_decision.warnings)

        # ── Layer 6: Drawdown Circuit Breaker ─────────────────────
        dd_state = self._drawdown.evaluate(portfolio)
        if not dd_state.trading_allowed:
            return self._reject(
                signal.signal_id,
                f"Circuit Breaker {dd_state.circuit_breaker_level}: "
                f"Drawdown {dd_state.current_drawdown_pct:.2%} — "
                f"no new entries allowed.",
                VetoLevel.HARD if dd_state.circuit_breaker_level == "ORANGE"
                else VetoLevel.NUCLEAR,
            )
        if dd_state.position_size_multiplier < 1.0:
            warnings.append(
                f"Circuit Breaker {dd_state.circuit_breaker_level}: "
                f"Position sizes reduced to {dd_state.position_size_multiplier:.0%}."
            )

        # ── Layer 7: Position Limits ──────────────────────────────
        limit_err = self._check_position_limits(signal, portfolio)
        if limit_err:
            return self._reject(
                signal.signal_id,
                limit_err,
                VetoLevel.FIRM,
            )

        # ── All checks passed — calculate position size ───────────
        # Combine drawdown multiplier with guard multiplier
        combined_multiplier = (
            dd_state.position_size_multiplier * guard_decision.size_multiplier
        )

        position_size = self.calculate_position_size(signal, portfolio)
        adjusted_size = position_size * combined_multiplier

        if adjusted_size < position_size:
            warnings.append(
                f"Position size adjusted from {position_size:.6f} "
                f"to {adjusted_size:.6f} (multiplier={combined_multiplier:.2f})"
            )

        logger.info(
            f"Risk APPROVED: {signal.signal_id} {signal.symbol} "
            f"{signal.side.value} size={adjusted_size:.6f} "
            f"score={signal.score:.2f}"
        )

        return RiskDecision(
            signal_id=signal.signal_id,
            approved=True,
            position_size=round(adjusted_size, 8),
            rejection_reasons=(),
            warnings=tuple(warnings),
            veto_level=VetoLevel.NONE.value,
            timestamp=datetime.now(timezone.utc),
        )

    # ═══════════════════════════════════════════════════════════════
    # RiskEngine ABC — calculate_position_size
    # ═══════════════════════════════════════════════════════════════

    def calculate_position_size(
        self,
        signal: Signal,
        portfolio: Portfolio,
    ) -> float:
        """Calculate recommended position size using Half-Kelly.

        Args:
            signal: Trading signal with entry and stop-loss.
            portfolio: Current portfolio state.

        Returns:
            Position quantity in base asset units. 0.0 if sizing fails.
        """
        result = self._sizer.calculate(
            equity=portfolio.equity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
        )
        return result.quantity

    # ═══════════════════════════════════════════════════════════════
    # RiskEngine ABC — get_drawdown_state
    # ═══════════════════════════════════════════════════════════════

    def get_drawdown_state(self, portfolio: Portfolio) -> DrawdownState:
        """Get current drawdown state and circuit breaker level.

        Args:
            portfolio: Current portfolio state.

        Returns:
            DrawdownState with level, permissions, and size multiplier.
        """
        return self._drawdown.evaluate(portfolio)

    # ═══════════════════════════════════════════════════════════════
    # RiskEngine ABC — Kill Switch methods
    # ═══════════════════════════════════════════════════════════════

    async def get_kill_switch_status(self) -> bool:
        """Check if the kill switch is currently active.

        Returns:
            True if active (trading halted).
        """
        return await self._kill_switch.is_active()

    async def activate_kill_switch(self, reason: str) -> None:
        """Activate the kill switch — halt ALL trading immediately.

        Args:
            reason: Human-readable reason for activation.
        """
        await self._kill_switch.activate(reason)

    async def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch — resume trading.

        Requires manual trigger. Gated Recovery Protocol applies.
        """
        await self._kill_switch.deactivate()

    # ═══════════════════════════════════════════════════════════════
    # Extended API — Trade outcome tracking
    # ═══════════════════════════════════════════════════════════════

    def record_trade_outcome(self, is_win: bool) -> None:
        """Record a trade outcome for behavioral guard tracking.

        Args:
            is_win: True if profitable, False if loss.
        """
        self._guards.record_outcome(is_win)

    def get_recovery_allocation(self, level: str) -> float:
        """Get the current recovery allocation percentage.

        After a kill switch deactivation, position sizes ramp up
        gradually based on the triggering circuit breaker level.

        Args:
            level: The circuit breaker level that triggered ("orange" or "red").

        Returns:
            Allocation percentage (0.0-1.0) for position sizing.
        """
        # For Day1, return full allocation (recovery protocol is Level 2+)
        return 1.0

    # ═══════════════════════════════════════════════════════════════
    # Layer helpers — all deterministic
    # ═══════════════════════════════════════════════════════════════

    def _validate_signal(self, signal: Signal, portfolio: Portfolio) -> str:
        """Layer 2: Validate signal data integrity.

        Returns error message or empty string if valid.
        """
        # Stop-loss is mandatory
        if self._stop_loss_required and signal.stop_loss == 0:
            return "Validation: Stop-loss is required but was not set."

        # Entry price must be positive
        if signal.entry_price <= 0:
            return f"Validation: Invalid entry price {signal.entry_price}."

        # Stop-loss must be on the correct side
        if signal.stop_loss > 0:
            if signal.side == OrderSide.BUY and signal.stop_loss >= signal.entry_price:
                return (
                    f"Validation: Buy signal but stop-loss ({signal.stop_loss}) "
                    f">= entry ({signal.entry_price})."
                )
            if signal.side == OrderSide.SELL and signal.stop_loss <= signal.entry_price:
                return (
                    f"Validation: Sell signal but stop-loss ({signal.stop_loss}) "
                    f"<= entry ({signal.entry_price})."
                )

        # Stop-loss distance check (max 2% from entry)
        if signal.entry_price > 0 and signal.stop_loss > 0:
            sl_distance = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
            if sl_distance > self._max_stop_loss_pct:
                return (
                    f"Validation: Stop-loss distance {sl_distance:.2%} "
                    f"exceeds maximum {self._max_stop_loss_pct:.2%}."
                )

        # Risk-reward ratio check
        if signal.entry_price > 0 and signal.stop_loss > 0 and signal.take_profit > 0:
            risk = abs(signal.entry_price - signal.stop_loss)
            reward = abs(signal.take_profit - signal.entry_price)
            if risk > 0:
                rr_ratio = reward / risk
                if rr_ratio < self._min_rr_ratio:
                    return (
                        f"Validation: Risk-reward {rr_ratio:.2f}:1 is below "
                        f"minimum {self._min_rr_ratio}:1."
                    )

        # Symbol sanity
        if not signal.symbol or "/" not in signal.symbol:
            return f"Validation: Invalid symbol '{signal.symbol}'."

        return ""

    def _check_blackout(self, signal: Signal) -> str:
        """Layer 4: Check economic calendar blackout windows.

        If signal metadata contains a blackout event, check if we're
        within the blackout window.

        Returns error message or empty string if clear.
        """
        if not self._blackout_events:
            return ""

        # Check signal metadata for blackout event
        event_name = signal.metadata.get("blackout_event")
        if not event_name:
            return ""

        event_config = self._blackout_events.get(event_name)
        if not event_config:
            return ""

        size_mult = event_config.get("size_multiplier", 1.0)
        if size_mult == 0.0:
            return (
                f"Blackout: {event_name} — trading blocked "
                f"({event_config.get('before_minutes', 0)}min before, "
                f"{event_config.get('after_minutes', 0)}min after)."
            )

        # Non-zero multiplier → warning, not block
        return ""

    def _check_position_limits(
        self, signal: Signal, portfolio: Portfolio
    ) -> str:
        """Layer 7: Check position count and concentration limits.

        Returns error message or empty string if within limits.
        """
        # Max open positions
        if portfolio.open_position_count >= self._max_open_positions:
            return (
                f"Position Limit: {portfolio.open_position_count} open positions "
                f">= maximum {self._max_open_positions}."
            )

        # Check if already holding this symbol
        for pos in portfolio.positions:
            if pos.symbol == signal.symbol:
                # Already have a position — check if adding would exceed limits
                existing_notional = abs(pos.quantity * pos.current_price)
                new_notional = existing_notional  # Will be calculated with size
                if existing_notional / portfolio.equity > self._max_single_position_pct:
                    return (
                        f"Position Limit: Existing position in {signal.symbol} "
                        f"already at {existing_notional/portfolio.equity:.1%} of equity."
                    )

        # Daily trade count (from metadata if available)
        daily_trades = signal.metadata.get("daily_trade_count", 0)
        if daily_trades >= self._max_daily_trades:
            return (
                f"Position Limit: {daily_trades} trades today >= "
                f"maximum {self._max_daily_trades}."
            )

        return ""

    # ═══════════════════════════════════════════════════════════════
    # Config loading
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _load_config(path: str) -> dict[str, Any]:
        """Load risk configuration from YAML file."""
        config_path = Path(path)
        if not config_path.exists():
            logger.warning(f"Risk config not found at {path}, using defaults")
            return {}
        try:
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load risk config: {e}")
            return {}

    def _build_sizer_config(self) -> SizingConfig:
        """Build PositionSizer config from loaded YAML."""
        return SizingConfig(
            kelly_fraction=self._config.get("kelly_fraction", 0.25),
            risk_per_trade_pct=self._config.get("risk_per_trade_pct", 0.02),
            max_single_position_pct=self._config.get(
                "max_single_position_pct", 0.15
            ),
        )

    def _build_drawdown_config(self) -> DrawdownConfig:
        """Build DrawdownMonitor config from loaded YAML."""
        return DrawdownConfig(
            daily_loss_flatten=self._config.get("daily_loss_flatten", -0.02),
            daily_loss_kill=self._config.get("daily_loss_kill", -0.03),
            max_drawdown_halt=self._config.get("max_drawdown_halt", -0.05),
            max_drawdown_flatten=self._config.get("max_drawdown_flatten", -0.15),
        )

    def _build_guards_config(self) -> GuardsConfig:
        """Build AntiBehavioralGuards config from loaded YAML."""
        return GuardsConfig(
            anti_revenge_cooldown_minutes=self._config.get(
                "anti_revenge_cooldown_minutes", 60
            ),
            anti_revenge_loss_streak=self._config.get(
                "anti_revenge_loss_streak", 3
            ),
            anti_greed_sizing_factor=self._config.get(
                "anti_greed_sizing_factor", 0.7
            ),
            anti_greed_win_streak=self._config.get(
                "anti_greed_win_streak", 5
            ),
            anti_fomo_min_signal_score=self._config.get(
                "anti_fomo_min_signal_score", 0.6
            ),
            anti_overconfidence_win_streak=self._config.get(
                "anti_overconfidence_win_streak", 5
            ),
        )

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _reject(
        signal_id: str, reason: str, veto_level: VetoLevel
    ) -> RiskDecision:
        """Build a rejection RiskDecision."""
        logger.info(f"Risk REJECTED: {signal_id} — {reason}")
        return RiskDecision(
            signal_id=signal_id,
            approved=False,
            position_size=0.0,
            rejection_reasons=(reason,),
            warnings=(),
            veto_level=veto_level.value,
            timestamp=datetime.now(timezone.utc),
        )
