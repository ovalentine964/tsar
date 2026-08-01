"""
Adaptive Filter — Dynamically adjust signal quality thresholds.

Responds to performance by tightening/loosening filters:
  - Win rate drops below 70% → tighten (raise min_score, require more factors)
  - Win rate above 80% → loosen slightly
  - 3+ loss streak → emergency tighten
  - 5+ win streak → maintain (don't get greedy)
  - Signal type < 65% WR → disable that type
  - Symbol < 60% WR → blacklist for 24h

Adaptation is logged with full reasoning for audit trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.agents.signal_quality_db import SignalQualityDB

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveState:
    """Current adaptive filter parameters."""

    min_score: float = 0.60
    min_factors: int = 3
    last_adaptation: str | None = None
    adaptation_reason: str | None = None
    trades_since_adaptation: int = 0
    current_loss_streak: int = 0
    current_win_streak: int = 0

    # Disabled signal types (signal_type → disabled_until_timestamp)
    disabled_signal_types: dict[str, str] | None = None

    # Blacklisted symbols (symbol → blacklist_until_timestamp)
    blacklisted_symbols: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.disabled_signal_types is None:
            self.disabled_signal_types = {}
        if self.blacklisted_symbols is None:
            self.blacklisted_symbols = {}


class AdaptiveFilter:
    """Dynamic filter parameter adjustment based on trading performance.

    Monitors win rates and streaks, adjusts signal quality thresholds
    to maintain ≥75% win rate target.
    """

    def __init__(
        self,
        config: dict[str, Any],
        quality_db: SignalQualityDB,
    ) -> None:
        adaptive_config = config.get("signal_quality", {}).get("adaptive", {})

        self._enabled = adaptive_config.get("enabled", True)
        self._check_interval = adaptive_config.get("check_interval_trades", 10)
        self._tighten_below_wr = adaptive_config.get("tighten_below_wr", 0.70)
        self._loosen_above_wr = adaptive_config.get("loosen_above_wr", 0.80)
        self._loss_streak_emergency = adaptive_config.get("loss_streak_emergency", 3)
        self._win_streak_maintain = adaptive_config.get("win_streak_maintain", 5)
        self._disable_signal_type_below_wr = adaptive_config.get("disable_signal_type_below_wr", 0.65)
        self._blacklist_symbol_below_wr = adaptive_config.get("blacklist_symbol_below_wr", 0.60)
        self._blacklist_hours = adaptive_config.get("blacklist_symbol_hours", 24)
        self._absolute_min_score = adaptive_config.get("absolute_min_score", 0.50)
        self._absolute_min_factors = adaptive_config.get("absolute_min_factors", 2)
        self._min_trades_for_eval = adaptive_config.get("min_trades_for_eval", 10)

        self._db = quality_db
        self._state = AdaptiveState()

    async def load_state(self) -> None:
        """Load adaptive state from database."""
        state_dict = await self._db.get_adaptive_state()
        self._state = AdaptiveState(
            min_score=state_dict.get("min_score", 0.60),
            min_factors=state_dict.get("min_factors", 3),
            last_adaptation=state_dict.get("last_adaptation"),
            adaptation_reason=state_dict.get("adaptation_reason"),
            trades_since_adaptation=state_dict.get("trades_since_adaptation", 0),
            current_loss_streak=state_dict.get("current_loss_streak", 0),
            current_win_streak=state_dict.get("current_win_streak", 0),
        )
        logger.info(
            "AdaptiveFilter loaded: min_score=%.2f, min_factors=%d, streaks(L%d/W%d)",
            self._state.min_score,
            self._state.min_factors,
            self._state.current_loss_streak,
            self._state.current_win_streak,
        )

    async def get_current_state(self) -> AdaptiveState:
        """Get current adaptive filter state."""
        return self._state

    async def evaluate_and_adapt(self) -> None:
        """Evaluate performance and adapt filters if needed.

        Called after each trade outcome is recorded.
        """
        if not self._enabled:
            return

        # Increment trades counter
        await self._db.increment_trades_since_adaptation()

        # Get current streak
        streak_len, streak_type = await self._db.get_consecutive_streak()
        self._state.current_loss_streak = streak_len if streak_type == "loss" else 0
        self._state.current_win_streak = streak_len if streak_type == "win" else 0

        # Emergency tighten on loss streak (immediate, no interval check)
        if self._state.current_loss_streak >= self._loss_streak_emergency:
            await self._emergency_tighten()
            return

        # Win streak: maintain, don't get greedy
        if self._state.current_win_streak >= self._win_streak_maintain:
            logger.info(
                "AdaptiveFilter: Win streak %d — maintaining current filters",
                self._state.current_win_streak,
            )
            return

        # Check interval
        total_trades = await self._db.get_trade_count()
        if total_trades < self._min_trades_for_eval:
            return

        if self._state.trades_since_adaptation < self._check_interval:
            return

        # Evaluate overall win rate
        overall_wr, trade_count = await self._db.get_win_rate(window=50)

        if trade_count < self._min_trades_for_eval:
            return

        # Tighten if win rate dropped
        if overall_wr < self._tighten_below_wr:
            await self._tighten_filters(overall_wr, trade_count)
            return

        # Loosen if win rate is high
        if overall_wr > self._loosen_above_wr:
            await self._loosen_filters(overall_wr, trade_count)
            return

        # Check per-dimension win rates for disabling
        await self._check_dimension_win_rates()

        logger.info(
            "AdaptiveFilter: WR=%.1f%% (%d trades) — filters unchanged "
            "(min_score=%.2f, min_factors=%d)",
            overall_wr * 100, trade_count,
            self._state.min_score, self._state.min_factors,
        )

    async def _emergency_tighten(self) -> None:
        """Emergency filter tightening on consecutive losses.

        Raise min_score to 0.70, require 5/7 factors.
        """
        old_score = self._state.min_score
        old_factors = self._state.min_factors

        self._state.min_score = max(0.70, self._state.min_score)
        self._state.min_factors = max(5, self._state.min_factors)

        reason = (
            f"EMERGENCY: {self._state.current_loss_streak} consecutive losses. "
            f"Tightened: score {old_score:.2f}→{self._state.min_score:.2f}, "
            f"factors {old_factors}→{self._state.min_factors}"
        )

        await self._db.update_adaptive_state(
            self._state.min_score,
            self._state.min_factors,
            reason,
        )

        logger.warning("🚨 AdaptiveFilter: %s", reason)

    async def _tighten_filters(self, win_rate: float, trade_count: int) -> None:
        """Tighten filters when win rate drops below threshold.

        Raise min_score by 0.05, add 1 to min_factors.
        """
        old_score = self._state.min_score
        old_factors = self._state.min_factors

        self._state.min_score = min(0.85, self._state.min_score + 0.05)
        self._state.min_factors = min(7, self._state.min_factors + 1)

        # Respect absolute minimums
        self._state.min_score = max(self._state.min_score, self._absolute_min_score)
        self._state.min_factors = max(self._state.min_factors, self._absolute_min_factors)

        reason = (
            f"Win rate {win_rate*100:.1f}% below {self._tighten_below_wr*100:.0f}% "
            f"({trade_count} trades). Tightened: score {old_score:.2f}→{self._state.min_score:.2f}, "
            f"factors {old_factors}→{self._state.min_factors}"
        )

        await self._db.update_adaptive_state(
            self._state.min_score,
            self._state.min_factors,
            reason,
        )

        logger.warning("⚠️ AdaptiveFilter: %s", reason)

    async def _loosen_filters(self, win_rate: float, trade_count: int) -> None:
        """Slightly loosen filters when win rate is high.

        Lower min_score by 0.03 (conservative loosening).
        """
        old_score = self._state.min_score

        self._state.min_score = max(self._absolute_min_score, self._state.min_score - 0.03)

        reason = (
            f"Win rate {win_rate*100:.1f}% above {self._loosen_above_wr*100:.0f}% "
            f"({trade_count} trades). Loosened: score {old_score:.2f}→{self._state.min_score:.2f}"
        )

        await self._db.update_adaptive_state(
            self._state.min_score,
            self._state.min_factors,
            reason,
        )

        logger.info("📉 AdaptiveFilter: %s", reason)

    async def _check_dimension_win_rates(self) -> None:
        """Check per-dimension win rates and disable underperformers."""
        dimension_wr = await self._db.get_win_rate_by_dimension(window=50)

        # Check signal types
        for sig_type, (wr, count) in dimension_wr.get("signal_type", {}).items():
            if count >= 10 and wr < self._disable_signal_type_below_wr:
                if sig_type not in (self._state.disabled_signal_types or {}):
                    self._state.disabled_signal_types[sig_type] = "disabled"
                    logger.warning(
                        "🚫 AdaptiveFilter: Disabled signal type '%s' "
                        "(WR=%.1f%%, %d trades)",
                        sig_type, wr * 100, count,
                    )

        # Check symbols
        for symbol, (wr, count) in dimension_wr.get("symbol", {}).items():
            if count >= 10 and wr < self._blacklist_symbol_below_wr:
                if symbol not in (self._state.blacklisted_symbols or {}):
                    self._state.blacklisted_symbols[symbol] = "blacklisted"
                    logger.warning(
                        "🚫 AdaptiveFilter: Blacklisted symbol '%s' "
                        "(WR=%.1f%%, %d trades)",
                        symbol, wr * 100, count,
                    )

    def is_signal_type_disabled(self, signal_type: str) -> bool:
        """Check if a signal type has been disabled by adaptive filtering."""
        return signal_type in (self._state.disabled_signal_types or {})

    def is_symbol_blacklisted(self, symbol: str) -> bool:
        """Check if a symbol has been blacklisted by adaptive filtering."""
        return symbol in (self._state.blacklisted_symbols or {})
