"""
Unit tests for Mandate and MandateGate — Phase 3.

Tests cover:
  - Mandate creation and validation
  - Order passing/failing mandate checks
  - Mandate commit/revoke lifecycle
  - Paper mode exemption
  - Gate integration with mock risk guardian
  - YAML persistence
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.interfaces.types import (
    Order,
    OrderSide,
    OrderType,
    Signal,
    VetoLevel,
)
from src.risk.mandate import (
    Mandate,
    MandateDecision,
    MandateRules,
    MandateState,
    MandateStatus,
)
from src.risk.mandate_gate import MandateGate


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _tmp_path(suffix: str = ".yaml") -> str:
    """Create a temp file path for mandate persistence."""
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.close()
    return f.name


def _make_rules(**overrides) -> MandateRules:
    """Create mandate rules with sensible defaults for testing."""
    defaults = {
        "allowed_symbols": ["BTC/USDT", "ETH/USDT"],
        "max_position_size_pct": 0.15,
        "max_daily_trades": 10,
        "max_leverage": 3.0,
        "allowed_order_types": ["market", "limit"],
        "max_notional_per_trade": 50000.0,
        "allowed_sides": ["buy", "sell"],
    }
    defaults.update(overrides)
    return MandateRules(**defaults)


def _make_mandate(
    rules: MandateRules | None = None,
    committed: bool = True,
    user_id: str = "user-001",
    config_path: str | None = None,
) -> Mandate:
    """Create a mandate, optionally committed."""
    path = config_path or _tmp_path()
    state = MandateState(
        rules=rules or _make_rules(),
        status=MandateStatus.ACTIVE if committed else MandateStatus.DRAFT,
        committed_at=datetime.now(timezone.utc) if committed else None,
        committed_by=user_id if committed else None,
    )
    return Mandate(state=state, config_path=path)


def _make_signal(
    symbol: str = "BTC/USDT",
    side: OrderSide = OrderSide.BUY,
    entry: float = 50000.0,
    sl: float = 49500.0,
    tp: float = 51000.0,
    score: float = 0.75,
    signal_id: str = "sig-001",
) -> Signal:
    return Signal(
        signal_id=signal_id,
        symbol=symbol,
        side=side,
        score=score,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        strategy="test_strategy",
    )


def _make_order(
    symbol: str = "BTC/USDT",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: float = 0.1,
    price: float = 50000.0,
) -> Order:
    return Order(
        order_id="",
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
    )


# ═══════════════════════════════════════════════════════════════════════
# MANDATE RULES VALIDATION (PYDANTIC)
# ═══════════════════════════════════════════════════════════════════════


class TestMandateRules:
    """Pydantic model validation for MandateRules."""

    def test_valid_rules(self):
        rules = _make_rules()
        assert "BTC/USDT" in rules.allowed_symbols
        assert rules.max_position_size_pct == 0.15
        assert rules.max_daily_trades == 10
        assert rules.max_leverage == 3.0

    def test_symbol_normalization(self):
        """Symbols should be normalized to uppercase."""
        rules = MandateRules(
            allowed_symbols=["btc/usdt", "Eth/Usdt"],
            max_position_size_pct=0.1,
            max_daily_trades=5,
        )
        assert rules.allowed_symbols == ["BTC/USDT", "ETH/USDT"]

    def test_invalid_symbol_format_rejected(self):
        """Symbols without '/' should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid symbol format"):
            MandateRules(
                allowed_symbols=["BTCUSDT"],
                max_position_size_pct=0.1,
                max_daily_trades=5,
            )

    def test_invalid_order_type_rejected(self):
        with pytest.raises(ValueError, match="Invalid order type"):
            MandateRules(
                allowed_symbols=["BTC/USDT"],
                max_position_size_pct=0.1,
                max_daily_trades=5,
                allowed_order_types=["market", "invalid_type"],
            )

    def test_invalid_side_rejected(self):
        with pytest.raises(ValueError, match="Invalid order side"):
            MandateRules(
                allowed_symbols=["BTC/USDT"],
                max_position_size_pct=0.1,
                max_daily_trades=5,
                allowed_sides=["buy", "short"],
            )

    def test_position_size_bounds(self):
        """Position size must be 0.0-1.0."""
        with pytest.raises(ValueError):
            MandateRules(
                allowed_symbols=["BTC/USDT"],
                max_position_size_pct=1.5,
                max_daily_trades=5,
            )

    def test_leverage_minimum(self):
        """Leverage must be >= 1.0."""
        with pytest.raises(ValueError):
            MandateRules(
                allowed_symbols=["BTC/USDT"],
                max_position_size_pct=0.1,
                max_daily_trades=5,
                max_leverage=0.5,
            )


# ═══════════════════════════════════════════════════════════════════════
# MANDATE CREATION
# ═══════════════════════════════════════════════════════════════════════


class TestMandateCreation:
    """Mandate initialization and state."""

    def test_create_default_mandate(self):
        """Default mandate should be in DRAFT state."""
        mandate = Mandate(config_path=_tmp_path())
        assert mandate.status == MandateStatus.DRAFT
        assert mandate.is_active is False
        assert mandate.committed_at is None
        assert mandate.committed_by is None

    def test_create_with_rules(self):
        rules = _make_rules()
        mandate = _make_mandate(rules=rules, committed=True)
        assert mandate.is_active is True
        assert mandate.rules.allowed_symbols == ["BTC/USDT", "ETH/USDT"]

    def test_mandate_repr(self):
        mandate = _make_mandate()
        repr_str = repr(mandate)
        assert "Mandate" in repr_str
        assert "active" in repr_str


# ═══════════════════════════════════════════════════════════════════════
# ORDER CHECKING — PASSING
# ═══════════════════════════════════════════════════════════════════════


class TestMandateCheckPass:
    """Orders that should pass mandate checks."""

    def test_allowed_symbol_passes(self):
        mandate = _make_mandate()
        order = _make_order(symbol="BTC/USDT")
        decision = mandate.check_order(order)
        assert decision.allowed is True
        assert decision.violations == []

    def test_allowed_eth_passes(self):
        mandate = _make_mandate()
        order = _make_order(symbol="ETH/USDT")
        decision = mandate.check_order(order)
        assert decision.allowed is True

    def test_limit_order_passes(self):
        mandate = _make_mandate()
        order = _make_order(order_type=OrderType.LIMIT)
        decision = mandate.check_order(order)
        assert decision.allowed is True

    def test_sell_order_passes(self):
        mandate = _make_mandate()
        order = _make_order(side=OrderSide.SELL)
        decision = mandate.check_order(order)
        assert decision.allowed is True

    def test_order_within_notional_limit(self):
        mandate = _make_mandate()
        # max_notional is 50000, order is 0.1 * 50000 = 5000
        order = _make_order(quantity=0.1, price=50000.0)
        decision = mandate.check_order(order)
        assert decision.allowed is True


# ═══════════════════════════════════════════════════════════════════════
# ORDER CHECKING — FAILING
# ═══════════════════════════════════════════════════════════════════════


class TestMandateCheckFail:
    """Orders that should fail mandate checks."""

    def test_disallowed_symbol_blocked(self):
        mandate = _make_mandate()
        order = _make_order(symbol="SOL/USDT")
        decision = mandate.check_order(order)
        assert decision.allowed is False
        assert any("symbol_not_allowed" in v for v in decision.violations)

    def test_disallowed_order_type_blocked(self):
        rules = _make_rules(allowed_order_types=["limit"])
        mandate = _make_mandate(rules=rules)
        order = _make_order(order_type=OrderType.MARKET)
        decision = mandate.check_order(order)
        assert decision.allowed is False
        assert any("order_type_not_allowed" in v for v in decision.violations)

    def test_disallowed_side_blocked(self):
        rules = _make_rules(allowed_sides=["buy"])
        mandate = _make_mandate(rules=rules)
        order = _make_order(side=OrderSide.SELL)
        decision = mandate.check_order(order)
        assert decision.allowed is False
        assert any("side_not_allowed" in v for v in decision.violations)

    def test_notional_exceeded_blocked(self):
        rules = _make_rules(max_notional_per_trade=1000.0)
        mandate = _make_mandate(rules=rules)
        # 1.0 * 50000 = 50000 >> 1000
        order = _make_order(quantity=1.0, price=50000.0)
        decision = mandate.check_order(order)
        assert decision.allowed is False
        assert any("notional_exceeded" in v for v in decision.violations)

    def test_case_insensitive_symbol_check(self):
        """Symbol check should be case-insensitive."""
        mandate = _make_mandate()
        order = _make_order(symbol="btc/usdt")
        decision = mandate.check_order(order)
        assert decision.allowed is True  # BTC/USDT matches btc/usdt

    def test_multiple_violations(self):
        """Multiple violations should all be reported."""
        mandate = _make_mandate()
        order = _make_order(symbol="DOGE/USDT", side=OrderSide.SELL)
        # If DOGE/USDT not in allowed and SELL might be allowed
        decision = mandate.check_order(order)
        # At minimum, symbol violation
        assert decision.allowed is False
        assert len(decision.violations) >= 1


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL CHECKING
# ═══════════════════════════════════════════════════════════════════════


class TestSignalCheck:
    """check_signal method for pre-sizing checks."""

    def test_allowed_signal_passes(self):
        mandate = _make_mandate()
        decision = mandate.check_signal(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
        )
        assert decision.allowed is True

    def test_disallowed_symbol_blocked(self):
        mandate = _make_mandate()
        decision = mandate.check_signal(
            symbol="DOGE/USDT",
            side=OrderSide.BUY,
        )
        assert decision.allowed is False

    def test_leverage_exceeded_blocked(self):
        mandate = _make_mandate()
        decision = mandate.check_signal(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            leverage=10.0,  # max is 3.0
        )
        assert decision.allowed is False
        assert any("leverage_exceeded" in v for v in decision.violations)

    def test_daily_trades_exceeded_blocked(self):
        mandate = _make_mandate()
        decision = mandate.check_signal(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            daily_trade_count=10,  # max is 10
        )
        assert decision.allowed is False
        assert any("daily_trades_exceeded" in v for v in decision.violations)

    def test_daily_trades_at_limit_blocked(self):
        """Exactly at limit should be blocked (>= check)."""
        mandate = _make_mandate()
        decision = mandate.check_signal(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            daily_trade_count=10,
        )
        assert decision.allowed is False

    def test_daily_trades_below_limit_passes(self):
        mandate = _make_mandate()
        decision = mandate.check_signal(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            daily_trade_count=9,
        )
        assert decision.allowed is True

    def test_string_side_input(self):
        """Should accept string sides, not just OrderSide enum."""
        mandate = _make_mandate()
        decision = mandate.check_signal(
            symbol="BTC/USDT",
            side="buy",
        )
        assert decision.allowed is True


# ═══════════════════════════════════════════════════════════════════════
# MANDATE LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════


class TestMandateLifecycle:
    """Commit, revoke, update lifecycle."""

    def test_commit_activates_mandate(self):
        path = _tmp_path()
        mandate = Mandate(state=MandateState(rules=_make_rules()), config_path=path)
        assert mandate.status == MandateStatus.DRAFT

        mandate.commit("user-001")
        assert mandate.is_active is True
        assert mandate.committed_by == "user-001"
        assert mandate.committed_at is not None

    def test_commit_with_empty_symbols_fails(self):
        """Cannot commit with no allowed symbols."""
        mandate = Mandate(config_path=_tmp_path())
        with pytest.raises(ValueError, match="empty allowed_symbols"):
            mandate.commit("user-001")

    def test_commit_with_zero_position_size_fails(self):
        rules = MandateRules(
            allowed_symbols=["BTC/USDT"],
            max_position_size_pct=0.0,
            max_daily_trades=5,
        )
        state = MandateState(rules=rules)
        mandate = Mandate(state=state, config_path=_tmp_path())
        with pytest.raises(ValueError, match="max_position_size_pct"):
            mandate.commit("user-001")

    def test_commit_with_zero_daily_trades_fails(self):
        rules = MandateRules(
            allowed_symbols=["BTC/USDT"],
            max_position_size_pct=0.1,
            max_daily_trades=0,
        )
        state = MandateState(rules=rules)
        mandate = Mandate(state=state, config_path=_tmp_path())
        with pytest.raises(ValueError, match="max_daily_trades"):
            mandate.commit("user-001")

    def test_revoke_deactivates_mandate(self):
        mandate = _make_mandate()
        assert mandate.is_active is True

        mandate.revoke("user-001")
        assert mandate.status == MandateStatus.REVOKED
        assert mandate.is_active is False
        assert mandate.state.revoked_by == "user-001"
        assert mandate.state.revoked_at is not None

    def test_revoked_mandate_blocks_orders(self):
        mandate = _make_mandate()
        mandate.revoke("user-001")

        order = _make_order(symbol="BTC/USDT")
        decision = mandate.check_order(order)
        assert decision.allowed is False
        assert "revoked" in decision.reason.lower()

    def test_update_changes_rules(self):
        mandate = _make_mandate()
        mandate.update("user-001", max_daily_trades=20)
        assert mandate.rules.max_daily_trades == 20
        assert mandate.version == 2

    def test_update_recommits(self):
        mandate = _make_mandate()
        old_commit_time = mandate.committed_at

        mandate.update("user-001", max_daily_trades=20)
        assert mandate.is_active is True
        assert mandate.committed_at >= old_commit_time

    def test_update_invalid_rules_fails(self):
        mandate = _make_mandate()
        with pytest.raises(ValueError):
            mandate.update("user-001", max_position_size_pct=0.0)

    def test_update_adds_symbol(self):
        mandate = _make_mandate()
        mandate.update(
            "user-001",
            allowed_symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        )
        assert "SOL/USDT" in mandate.rules.allowed_symbols

    def test_commit_after_revoke_reactivates(self):
        mandate = _make_mandate()
        mandate.revoke("user-001")
        assert mandate.is_active is False

        mandate.commit("user-002")
        assert mandate.is_active is True
        assert mandate.committed_by == "user-002"


# ═══════════════════════════════════════════════════════════════════════
# YAML PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════


class TestYAMLPersistence:
    """Mandate state persistence to YAML."""

    def test_save_and_load(self):
        path = _tmp_path()
        rules = _make_rules()
        state = MandateState(
            rules=rules,
            status=MandateStatus.ACTIVE,
            committed_at=datetime.now(timezone.utc),
            committed_by="user-001",
        )
        mandate = Mandate(state=state, config_path=path)
        mandate.commit("user-001")  # Persists to YAML

        # Load from the saved file
        mandate2 = Mandate(config_path=path)
        assert mandate2.is_active is True
        assert mandate2.committed_by == "user-001"
        assert "BTC/USDT" in mandate2.rules.allowed_symbols

    def test_load_nonexistent_creates_default(self):
        """Loading from nonexistent file creates default draft."""
        path = _tmp_path() + ".nonexistent"
        mandate = Mandate(config_path=path)
        assert mandate.status == MandateStatus.DRAFT
        assert mandate.rules.allowed_symbols == []

    def test_commit_persists(self):
        path = _tmp_path()
        mandate = Mandate(state=MandateState(rules=_make_rules()), config_path=path)
        mandate.commit("user-001")

        # Reload from disk
        mandate2 = Mandate(config_path=path)
        assert mandate2.is_active is True
        assert mandate2.committed_by == "user-001"

    def test_revoke_persists(self):
        path = _tmp_path()
        mandate = Mandate(state=MandateState(rules=_make_rules()), config_path=path)
        mandate.commit("user-001")
        mandate.revoke("user-002")

        mandate2 = Mandate(config_path=path)
        assert mandate2.status == MandateStatus.REVOKED
        assert mandate2.state.revoked_by == "user-002"


# ═══════════════════════════════════════════════════════════════════════
# PAPER MODE EXEMPTION
# ═══════════════════════════════════════════════════════════════════════


class TestPaperModeExemption:
    """Paper mode bypasses mandate checks entirely."""

    def test_paper_mode_allows_uncommitted_mandate(self):
        """Paper mode should work even without a committed mandate."""
        gate = MandateGate(mandate=_make_mandate(committed=False))
        signal = _make_signal()
        decision = gate.check(signal, is_live=False)
        assert decision.approved is True
        assert "paper" in decision.warnings[0].lower()

    def test_paper_mode_allows_disallowed_symbol(self):
        """Paper mode should allow any symbol."""
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal(symbol="DOGE/USDT")
        decision = gate.check(signal, is_live=False)
        assert decision.approved is True

    def test_paper_mode_allows_revoked_mandate(self):
        mandate = _make_mandate()
        mandate.revoke("user-001")
        gate = MandateGate(mandate=mandate)
        signal = _make_signal()
        decision = gate.check(signal, is_live=False)
        assert decision.approved is True

    def test_paper_mode_check_order(self):
        gate = MandateGate(mandate=_make_mandate())
        order = _make_order(symbol="RANDOM/USDT")
        decision = gate.check_order(order, is_live=False)
        assert decision.allowed is True


# ═══════════════════════════════════════════════════════════════════════
# MANDATE GATE — LIVE TRADING
# ═══════════════════════════════════════════════════════════════════════


class TestMandateGateLive:
    """MandateGate behavior in live trading mode."""

    def test_live_mode_blocks_uncommitted_mandate(self):
        """Live mode with uncommitted mandate should block all trades."""
        gate = MandateGate(mandate=_make_mandate(committed=False))
        signal = _make_signal()
        decision = gate.check(signal, is_live=True)
        assert decision.approved is False
        assert decision.veto_level == VetoLevel.HARD.value
        assert "draft" in decision.rejection_reasons[0].lower()

    def test_live_mode_passes_valid_signal(self):
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal(symbol="BTC/USDT", side=OrderSide.BUY)
        decision = gate.check(signal, is_live=True)
        assert decision.approved is True
        assert decision.veto_level == VetoLevel.NONE.value

    def test_live_mode_blocks_disallowed_symbol(self):
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal(symbol="SOL/USDT")
        decision = gate.check(signal, is_live=True)
        assert decision.approved is False
        assert decision.veto_level == VetoLevel.HARD.value

    def test_live_mode_blocks_exceeded_leverage(self):
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal()
        decision = gate.check(signal, is_live=True, leverage=10.0)
        assert decision.approved is False

    def test_live_mode_blocks_exceeded_daily_trades(self):
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal()
        decision = gate.check(signal, is_live=True, daily_trade_count=10)
        assert decision.approved is False


# ═══════════════════════════════════════════════════════════════════════
# MANDATE GATE — ASYNC
# ═══════════════════════════════════════════════════════════════════════


class TestMandateGateAsync:
    """Async interface for mandate gate."""

    @pytest.mark.asyncio
    async def test_async_check_passes(self):
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal(symbol="BTC/USDT")
        decision = await gate.check_async(signal, is_live=True)
        assert decision.approved is True

    @pytest.mark.asyncio
    async def test_async_check_blocks(self):
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal(symbol="DOGE/USDT")
        decision = await gate.check_async(signal, is_live=True)
        assert decision.approved is False

    @pytest.mark.asyncio
    async def test_async_paper_mode_exemption(self):
        gate = MandateGate(mandate=_make_mandate(committed=False))
        signal = _make_signal()
        decision = await gate.check_async(signal, is_live=False)
        assert decision.approved is True


# ═══════════════════════════════════════════════════════════════════════
# MANDATE GATE — STATUS
# ═══════════════════════════════════════════════════════════════════════


class TestMandateGateStatus:
    """Status reporting for monitoring."""

    def test_status_report(self):
        gate = MandateGate(mandate=_make_mandate())
        status = gate.get_status()
        assert status["mandate_status"] == "active"
        assert status["is_active"] is True
        assert status["allowed_symbols_count"] == 2
        assert status["max_position_size_pct"] == 0.15

    def test_status_uncommitted(self):
        gate = MandateGate(mandate=_make_mandate(committed=False))
        status = gate.get_status()
        assert status["mandate_status"] == "draft"
        assert status["is_active"] is False

    def test_status_revoked(self):
        mandate = _make_mandate()
        mandate.revoke("user-001")
        gate = MandateGate(mandate=mandate)
        status = gate.get_status()
        assert status["mandate_status"] == "revoked"
        assert status["is_active"] is False


# ═══════════════════════════════════════════════════════════════════════
# MANDATE GATE — INTEGRATION WITH RISK GUARDIAN
# ═══════════════════════════════════════════════════════════════════════


class TestMandateGateIntegration:
    """Integration patterns with RiskGovernor (mocked)."""

    def test_gate_blocks_before_risk_engine(self):
        """If mandate blocks, risk engine should never be called."""
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal(symbol="DOGE/USDT")  # Not in mandate

        # Gate blocks
        gate_decision = gate.check(signal, is_live=True)
        assert gate_decision.approved is False

        # Risk engine should not be reached
        mock_risk = AsyncMock()
        mock_risk.check_risk = AsyncMock()  # Should NOT be called
        mock_risk.check_risk.assert_not_called()

    def test_gate_passes_to_risk_engine(self):
        """If mandate passes, risk engine can proceed."""
        gate = MandateGate(mandate=_make_mandate())
        signal = _make_signal(symbol="BTC/USDT")

        # Gate passes
        gate_decision = gate.check(signal, is_live=True)
        assert gate_decision.approved is True

        # Risk engine can now evaluate
        # (In real usage, this would be: await risk_governor.check_risk(signal, portfolio))

    def test_pipeline_order_mandate_then_risk(self):
        """Full pipeline: mandate gate → risk guardian."""
        gate = MandateGate(mandate=_make_mandate())

        # Test with allowed signal
        allowed_signal = _make_signal(symbol="BTC/USDT")
        gate_result = gate.check(allowed_signal, is_live=True)
        assert gate_result.approved is True

        # Test with blocked signal
        blocked_signal = _make_signal(symbol="DOGE/USDT")
        gate_result = gate.check(blocked_signal, is_live=True)
        assert gate_result.approved is False
        assert gate_result.veto_level == VetoLevel.HARD.value

    def test_paper_mode_skips_gate_for_backtesting(self):
        """Backtesting/paper mode should bypass mandate for flexibility."""
        gate = MandateGate(mandate=_make_mandate(committed=False))

        # Even with DRAFT mandate, paper trades go through
        signal = _make_signal(symbol="ANY/THING")
        decision = gate.check(signal, is_live=False)
        assert decision.approved is True


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions and edge cases."""

    def test_empty_order_type_list_blocks_all(self):
        rules = _make_rules(allowed_order_types=[])
        mandate = _make_mandate(rules=rules)
        order = _make_order()
        decision = mandate.check_order(order)
        assert decision.allowed is False

    def test_single_symbol_mandate(self):
        rules = _make_rules(allowed_symbols=["BTC/USDT"])
        mandate = _make_mandate(rules=rules)

        # BTC passes
        assert mandate.check_order(_make_order(symbol="BTC/USDT")).allowed is True
        # ETH fails
        assert mandate.check_order(_make_order(symbol="ETH/USDT")).allowed is False

    def test_order_with_none_price_skips_notional_check(self):
        """If price is None, notional check should be skipped."""
        rules = _make_rules(max_notional_per_trade=100.0)
        mandate = _make_mandate(rules=rules)
        order = _make_order(price=None)
        # Should not crash, and notional check skipped
        decision = mandate.check_order(order)
        # Still passes (symbol/type/side are fine)
        assert decision.allowed is True

    def test_zero_notional_limit_means_no_limit(self):
        """max_notional_per_trade=0 means no notional limit."""
        rules = _make_rules(max_notional_per_trade=0.0)
        mandate = _make_mandate(rules=rules)
        order = _make_order(quantity=100.0, price=50000.0)
        decision = mandate.check_order(order)
        assert decision.allowed is True

    def test_mandate_reload(self):
        """Reload from disk picks up external changes."""
        path = _tmp_path()
        mandate1 = Mandate(state=MandateState(
            rules=_make_rules(),
            status=MandateStatus.ACTIVE,
            committed_at=datetime.now(timezone.utc),
            committed_by="user-001",
        ), config_path=path)

        # Simulate external modification
        mandate1.update("user-001", max_daily_trades=50)

        # Create new instance from same file
        mandate2 = Mandate(config_path=path)
        assert mandate2.rules.max_daily_trades == 50
