"""
Unit tests for AntiBehavioralGuards — anti-revenge, greed, FOMO, overconfidence.

Tests:
  - Anti-Revenge: 3 consecutive losses → cooldown
  - Anti-Greed: 5+ win streak → reduced sizing
  - Anti-FOMO: low signal score → block
  - Anti-Overconfidence: extended win streak → further size reduction
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.interfaces.types import OrderSide, Signal
from src.risk.guards import AntiBehavioralGuards, GuardDecision, GuardsConfig, GuardState


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _make_signal(score: float = 0.75) -> Signal:
    return Signal(
        signal_id="sig-test",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        score=score,
        entry_price=50000.0,
        stop_loss=49500.0,
        take_profit=51000.0,
        strategy="test",
    )


def _make_guards(
    config: GuardsConfig | None = None,
    state: GuardState | None = None,
) -> AntiBehavioralGuards:
    return AntiBehavioralGuards(config=config, state=state)


# ═══════════════════════════════════════════════════════════════════════
# ANTI-REVENGE
# ═══════════════════════════════════════════════════════════════════════


class TestAntiRevenge:
    """3 consecutive losses → 60-minute cooldown."""

    def test_no_losses_allows_trade(self):
        guards = _make_guards()
        decision = guards.check_all(_make_signal())
        assert decision.approved is True

    def test_two_losses_allows_trade(self):
        state = GuardState(consecutive_losses=2, last_loss_timestamp=time.time())
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.approved is True

    def test_three_losses_blocks_trade(self):
        state = GuardState(
            consecutive_losses=3,
            last_loss_timestamp=time.time(),
        )
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.approved is False
        assert "Anti-Revenge" in decision.veto_reason

    def test_four_losses_blocks_trade(self):
        state = GuardState(
            consecutive_losses=4,
            last_loss_timestamp=time.time(),
        )
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.approved is False

    def test_cooldown_elapses_allows_trade(self):
        """After 60 minutes, trading should be allowed again."""
        config = GuardsConfig(anti_revenge_cooldown_minutes=60)
        state = GuardState(
            consecutive_losses=3,
            last_loss_timestamp=time.time() - 3700,  # 61+ minutes ago
        )
        guards = _make_guards(config=config, state=state)
        decision = guards.check_all(_make_signal())
        assert decision.approved is True

    def test_cooldown_not_elapsed_blocks_trade(self):
        config = GuardsConfig(anti_revenge_cooldown_minutes=60)
        state = GuardState(
            consecutive_losses=3,
            last_loss_timestamp=time.time() - 60,  # 1 minute ago
        )
        guards = _make_guards(config=config, state=state)
        decision = guards.check_all(_make_signal())
        assert decision.approved is False

    def test_custom_loss_streak_threshold(self):
        config = GuardsConfig(anti_revenge_loss_streak=5)
        state = GuardState(
            consecutive_losses=4,
            last_loss_timestamp=time.time(),
        )
        guards = _make_guards(config=config, state=state)
        decision = guards.check_all(_make_signal())
        assert decision.approved is True  # 4 < threshold of 5

    def test_custom_cooldown_duration(self):
        config = GuardsConfig(anti_revenge_cooldown_minutes=30)
        state = GuardState(
            consecutive_losses=3,
            last_loss_timestamp=time.time() - 1800,  # 30 minutes ago
        )
        guards = _make_guards(config=config, state=state)
        decision = guards.check_all(_make_signal())
        # Right at boundary — should be allowed (elapsed >= cooldown)
        assert decision.approved is True

    def test_revenge_sets_size_multiplier_zero(self):
        state = GuardState(
            consecutive_losses=3,
            last_loss_timestamp=time.time(),
        )
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier == 0.0


# ═══════════════════════════════════════════════════════════════════════
# ANTI-GREED
# ═══════════════════════════════════════════════════════════════════════


class TestAntiGreed:
    """5+ win streak → 70% sizing."""

    def test_no_win_streak_full_size(self):
        guards = _make_guards()
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier == 1.0

    def test_four_wins_full_size(self):
        state = GuardState(consecutive_wins=4)
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier == 1.0

    def test_five_wins_reduced_size(self):
        state = GuardState(consecutive_wins=5)
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier == 0.7
        assert decision.approved is True  # Not blocked, just reduced
        assert any("Anti-Greed" in w for w in decision.warnings)

    def test_six_wins_reduced_size(self):
        state = GuardState(consecutive_wins=6)
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier <= 0.7

    def test_custom_win_streak_threshold(self):
        config = GuardsConfig(anti_greed_win_streak=3)
        state = GuardState(consecutive_wins=3)
        guards = _make_guards(config=config, state=state)
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier == 0.7

    def test_custom_sizing_factor(self):
        config = GuardsConfig(anti_greed_sizing_factor=0.5)
        state = GuardState(consecutive_wins=5)
        guards = _make_guards(config=config, state=state)
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier == 0.5


# ═══════════════════════════════════════════════════════════════════════
# ANTI-FOMO
# ═══════════════════════════════════════════════════════════════════════


class TestAntiFOMO:
    """Low signal score → block trade."""

    def test_low_score_blocked(self):
        guards = _make_guards()
        decision = guards.check_all(_make_signal(score=0.3))
        assert decision.approved is False
        assert "Anti-FOMO" in decision.veto_reason

    def test_score_at_threshold_passes(self):
        config = GuardsConfig(anti_fomo_min_signal_score=0.6)
        guards = _make_guards(config=config)
        decision = guards.check_all(_make_signal(score=0.6))
        assert decision.approved is True

    def test_score_above_threshold_passes(self):
        guards = _make_guards()
        decision = guards.check_all(_make_signal(score=0.9))
        assert decision.approved is True

    def test_custom_min_score(self):
        config = GuardsConfig(anti_fomo_min_signal_score=0.8)
        guards = _make_guards(config=config)
        decision = guards.check_all(_make_signal(score=0.7))
        assert decision.approved is False

    def test_fomo_veto_sets_zero_multiplier(self):
        guards = _make_guards()
        decision = guards.check_all(_make_signal(score=0.3))
        assert decision.size_multiplier == 0.0


# ═══════════════════════════════════════════════════════════════════════
# ANTI-OVERCONFIDENCE
# ═══════════════════════════════════════════════════════════════════════


class TestAntiOverconfidence:
    """Extended win streaks trigger progressive size caps."""

    def test_short_wins_no_overconfidence(self):
        state = GuardState(consecutive_wins=3)
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier == 1.0

    def test_five_wins_overconfidence_cap(self):
        state = GuardState(consecutive_wins=5)
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        # 5 wins triggers overconfidence (same threshold as greed)
        assert decision.size_multiplier <= 0.7

    def test_ten_wins_aggressive_cap(self):
        state = GuardState(consecutive_wins=10)
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.size_multiplier <= 0.5
        assert any("Overconfidence" in w for w in decision.warnings)

    def test_custom_overconfidence_threshold(self):
        config = GuardsConfig(anti_overconfidence_win_streak=8, anti_greed_win_streak=8)
        state = GuardState(consecutive_wins=7)
        guards = _make_guards(config=config, state=state)
        decision = guards.check_all(_make_signal())
        # Both greed and overconfidence thresholds are 8, 7 < 8 → no cap
        assert decision.size_multiplier == 1.0


# ═══════════════════════════════════════════════════════════════════════
# RECORD OUTCOME
# ═══════════════════════════════════════════════════════════════════════


class TestRecordOutcome:
    """Trade outcome recording updates streak counters."""

    def test_record_win_increments_streak(self):
        guards = _make_guards()
        guards.record_outcome(True)
        assert guards._state.consecutive_wins == 1
        assert guards._state.consecutive_losses == 0

    def test_record_loss_increments_streak(self):
        guards = _make_guards()
        guards.record_outcome(False)
        assert guards._state.consecutive_losses == 1
        assert guards._state.consecutive_wins == 0

    def test_win_resets_loss_streak(self):
        state = GuardState(consecutive_losses=2)
        guards = _make_guards(state=state)
        guards.record_outcome(True)
        assert guards._state.consecutive_wins == 1
        assert guards._state.consecutive_losses == 0

    def test_loss_resets_win_streak(self):
        state = GuardState(consecutive_wins=5)
        guards = _make_guards(state=state)
        guards.record_outcome(False)
        assert guards._state.consecutive_losses == 1
        assert guards._state.consecutive_wins == 0

    def test_outcome_history_capped(self):
        guards = _make_guards()
        for _ in range(150):
            guards.record_outcome(True)
        assert len(guards._state.trade_results) <= 100


# ═══════════════════════════════════════════════════════════════════════
# RESET
# ═══════════════════════════════════════════════════════════════════════


class TestReset:
    """Reset clears all guard state."""

    def test_reset_clears_state(self):
        state = GuardState(consecutive_losses=5, consecutive_wins=3)
        guards = _make_guards(state=state)
        guards.reset()
        assert guards._state.consecutive_losses == 0
        assert guards._state.consecutive_wins == 0
        assert guards._state.trade_results == []


# ═══════════════════════════════════════════════════════════════════════
# COMBINED GUARDS
# ═══════════════════════════════════════════════════════════════════════


class TestCombinedGuards:
    """Multiple guards interacting."""

    def test_revenge_takes_priority_over_greed(self):
        """Revenge is checked first — if it vetoes, greed doesn't matter."""
        state = GuardState(consecutive_losses=3, last_loss_timestamp=time.time())
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        assert decision.approved is False
        assert "Anti-Revenge" in decision.veto_reason

    def test_fomo_takes_priority_over_greed(self):
        """FOMO is checked after revenge but before greed."""
        state = GuardState(consecutive_wins=10)
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal(score=0.3))
        assert decision.approved is False
        assert "Anti-FOMO" in decision.veto_reason

    def test_greed_and_overconfidence_combine(self):
        """When both greed and overconfidence apply, take the lower multiplier."""
        state = GuardState(consecutive_wins=10)
        guards = _make_guards(state=state)
        decision = guards.check_all(_make_signal())
        # Greed cap: 0.7, Overconfidence cap: 0.5 → combined: min(0.7, 0.5) = 0.5
        assert decision.size_multiplier <= 0.5

    def test_all_clear_returns_full_size(self):
        """No guards triggered → size_multiplier = 1.0."""
        guards = _make_guards()
        decision = guards.check_all(_make_signal(score=0.9))
        assert decision.approved is True
        assert decision.size_multiplier == 1.0
        assert decision.veto_reason == ""
        assert len(decision.warnings) == 0
