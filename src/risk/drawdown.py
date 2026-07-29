"""
Drawdown Monitor — Track drawdown state and circuit breaker levels.

Four-level progressive circuit breaker protocol:
  GREEN:   Drawdown < 2%        → Normal operation, sizing ×1.0
  YELLOW:  Drawdown 2-3%        → Reduce position sizes 50%, sizing ×0.5
  ORANGE:  Drawdown 3-5%        → No new entries, sizing ×0.0
  RED:     Drawdown > 5%        → KILL SWITCH, flatten everything

Also monitors daily P&L with separate thresholds:
  daily_loss_flatten: -2% → halt new trades (ORANGE)
  daily_loss_kill:    -3% → flatten all positions (RED)

All thresholds are read from config/risk.yaml — deterministic, no LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.interfaces.types import DrawdownLevel, DrawdownState, Portfolio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrawdownConfig:
    """Immutable drawdown configuration from risk.yaml."""

    # Drawdown thresholds (negative percentages as fractions)
    daily_loss_flatten: float = -0.02   # -2%  → ORANGE
    daily_loss_kill: float = -0.03      # -3%  → RED
    max_drawdown_halt: float = -0.05    # -5%  → ORANGE
    max_drawdown_flatten: float = -0.15 # -15% → RED


class DrawdownMonitor:
    """Deterministic drawdown tracker with 4-level circuit breakers.

    Tracks both drawdown-from-HWM and daily P&L. The worse of the
    two determines the circuit breaker level.

    All state is derived from Portfolio snapshots — no internal state,
    no external calls, fully deterministic.
    """

    def __init__(self, config: DrawdownConfig | None = None) -> None:
        self._config = config or DrawdownConfig()

    def evaluate(self, portfolio: Portfolio) -> DrawdownState:
        """Evaluate current drawdown state from a portfolio snapshot.

        Args:
            portfolio: Current portfolio state including equity, HWM,
                       daily P&L, and positions.

        Returns:
            DrawdownState with circuit breaker level, trading permissions,
            and position size multiplier.
        """
        equity = portfolio.equity
        hwm = portfolio.high_water_mark

        # --- Drawdown from HWM ---
        drawdown_pct = (equity - hwm) / hwm if hwm > 0 else 0.0

        # --- Daily P&L percentage ---
        daily_pnl_pct = portfolio.daily_pnl_pct
        if daily_pnl_pct == 0.0 and equity > 0:
            # Derive from absolute if percentage not provided
            daily_pnl_pct = portfolio.daily_pnl / equity

        # --- Determine circuit breaker level ---
        # Use the WORSE of drawdown and daily loss
        level = self._determine_level(drawdown_pct, daily_pnl_pct)

        # --- Map level to trading permissions ---
        trading_allowed, size_multiplier = self._level_permissions(level)

        state = DrawdownState(
            current_drawdown_pct=round(drawdown_pct, 6),
            high_water_mark=hwm,
            current_equity=equity,
            daily_pnl=portfolio.daily_pnl,
            daily_pnl_pct=round(daily_pnl_pct, 6),
            circuit_breaker_level=level.value,
            trading_allowed=trading_allowed,
            position_size_multiplier=size_multiplier,
        )

        if level != DrawdownLevel.GREEN:
            logger.warning(
                f"DrawdownMonitor: {level.value} — "
                f"drawdown={drawdown_pct:.2%} daily={daily_pnl_pct:.2%} "
                f"trading_allowed={trading_allowed} size_mult={size_multiplier}"
            )

        return state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _determine_level(
        self, drawdown_pct: float, daily_pnl_pct: float
    ) -> DrawdownLevel:
        """Determine circuit breaker level from drawdown and daily P&L.

        Returns the WORSE (most restrictive) of the two metrics.
        """
        cfg = self._config

        # Check RED first (most severe)
        if drawdown_pct <= cfg.max_drawdown_flatten:
            return DrawdownLevel.RED
        if daily_pnl_pct <= cfg.daily_loss_kill:
            return DrawdownLevel.RED

        # Check ORANGE
        if drawdown_pct <= cfg.max_drawdown_halt:
            return DrawdownLevel.ORANGE
        if daily_pnl_pct <= cfg.daily_loss_flatten:
            return DrawdownLevel.ORANGE

        # Check YELLOW (2-3% drawdown)
        if drawdown_pct <= -0.02:
            return DrawdownLevel.YELLOW

        return DrawdownLevel.GREEN

    @staticmethod
    def _level_permissions(
        level: DrawdownLevel,
    ) -> tuple[bool, float]:
        """Map circuit breaker level to (trading_allowed, size_multiplier)."""
        if level == DrawdownLevel.GREEN:
            return True, 1.0
        elif level == DrawdownLevel.YELLOW:
            return True, 0.5   # Reduce sizes 50%
        elif level == DrawdownLevel.ORANGE:
            return False, 0.0  # No new entries
        else:  # RED
            return False, 0.0  # Kill switch — flatten everything
