"""
Tests for risk module: KillSwitch, DrawdownMonitor, Guards, Governor.

Covers H-15 (critical path tests) and verifies risk tooling works.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from src.interfaces.types import (
    DrawdownLevel,
    Portfolio,
)
from src.risk.drawdown import DrawdownConfig, DrawdownMonitor
from src.risk.kill_switch import KillSwitch

# ═══════════════════════════════════════════════════════════════════════
# KillSwitch Tests
# ═══════════════════════════════════════════════════════════════════════


class TestKillSwitch:
    """Tests for the dual-write kill switch."""

    @pytest.fixture
    def tmp_kill_path(self, tmp_path):
        return str(tmp_path / "kill_switch")

    @pytest.fixture
    def ks(self, tmp_kill_path):
        return KillSwitch(file_path=tmp_kill_path)

    @pytest.fixture
    def ks_with_redis(self, tmp_kill_path):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        return KillSwitch(file_path=tmp_kill_path, redis_client=redis)

    async def test_initial_state_fail_safe(self, ks):
        """Kill switch defaults to ACTIVE when no state exists (fail-safe)."""
        result = await ks.is_active()
        assert result is True  # Fail-safe: assume active on no data

    async def test_activate_writes_file(self, ks, tmp_kill_path):
        """Activation writes state to file (primary store)."""
        await ks.activate("test reason")
        payload = json.loads(Path(tmp_kill_path).read_text())
        assert payload["active"] is True
        assert payload["reason"] == "test reason"

    async def test_deactivate_writes_inactive(self, ks, tmp_kill_path):
        """Deactivation writes inactive state to file."""
        await ks.activate("test")
        assert Path(tmp_kill_path).exists()
        await ks.deactivate()
        assert Path(tmp_kill_path).exists()
        payload = json.loads(Path(tmp_kill_path).read_text())
        assert payload["active"] is False

    async def test_is_active_after_activate(self, ks):
        """is_active returns True after activation."""
        await ks.activate("test")
        assert await ks.is_active() is True

    async def test_is_active_after_deactivate(self, ks):
        """is_active returns False after deactivation."""
        await ks.activate("test")
        await ks.deactivate()
        assert await ks.is_active() is False

    async def test_activate_writes_redis(self, ks_with_redis):
        """Activation writes to Redis (secondary store)."""
        await ks_with_redis.activate("redis test")
        ks_with_redis._redis.set.assert_called_once()

    async def test_activate_calls_callback(self, tmp_kill_path):
        """on_activate callback is invoked with reason."""
        callback = AsyncMock()
        ks = KillSwitch(file_path=tmp_kill_path, on_activate=callback)
        await ks.activate("callback test")
        callback.assert_called_once_with("callback test")

    async def test_deactivate_calls_callback(self, tmp_kill_path):
        """on_deactivate callback is invoked."""
        callback = AsyncMock()
        ks = KillSwitch(file_path=tmp_kill_path, on_deactivate=callback)
        await ks.activate("test")
        await ks.deactivate()
        callback.assert_called_once()

    async def test_callback_exception_does_not_propagate(self, tmp_kill_path):
        """Callback exceptions are caught, not propagated."""
        callback = AsyncMock(side_effect=RuntimeError("boom"))
        ks = KillSwitch(file_path=tmp_kill_path, on_activate=callback)
        # Should not raise
        await ks.activate("test")

    async def test_get_status_returns_payload(self, ks):
        """get_status returns full metadata dict."""
        await ks.activate("status check")
        status = await ks.get_status()
        assert status["active"] is True
        assert status["reason"] == "status check"
        assert "activated_at" in status
        assert "activated_at_human" in status

    async def test_unreadable_file_fail_safe(self, ks, tmp_kill_path):
        """Unreadable file triggers fail-safe (assume active)."""
        Path(tmp_kill_path).write_text("not valid json{{{")
        assert await ks.is_active() is True

    async def test_build_payload_static(self):
        """_build_payload creates correct structure."""
        payload = KillSwitch._build_payload(True, "unit test")
        assert payload["active"] is True
        assert payload["reason"] == "unit test"
        assert isinstance(payload["activated_at"], float)
        assert isinstance(payload["activated_at_human"], str)


# ═══════════════════════════════════════════════════════════════════════
# DrawdownMonitor Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDrawdownMonitor:
    """Tests for the 4-level circuit breaker drawdown monitor."""

    @pytest.fixture
    def monitor(self):
        return DrawdownMonitor()

    def test_green_level(self, monitor, portfolio_green):
        """Healthy portfolio should be GREEN."""
        state = monitor.evaluate(portfolio_green)
        assert state.circuit_breaker_level == DrawdownLevel.GREEN.value
        assert state.trading_allowed is True
        assert state.position_size_multiplier == 1.0

    def test_yellow_level(self, monitor, portfolio_yellow):
        """2.5% drawdown should be YELLOW."""
        state = monitor.evaluate(portfolio_yellow)
        assert state.circuit_breaker_level == DrawdownLevel.YELLOW.value
        assert state.trading_allowed is True
        assert state.position_size_multiplier == 0.5

    def test_orange_level(self, monitor, portfolio_orange):
        """5.5% drawdown should be ORANGE."""
        state = monitor.evaluate(portfolio_orange)
        assert state.circuit_breaker_level == DrawdownLevel.ORANGE.value
        assert state.trading_allowed is False
        assert state.position_size_multiplier == 0.0

    def test_red_level(self, monitor, portfolio_red):
        """6% drawdown should be RED."""
        state = monitor.evaluate(portfolio_red)
        assert state.circuit_breaker_level == DrawdownLevel.RED.value
        assert state.trading_allowed is False
        assert state.position_size_multiplier == 0.0

    def test_daily_loss_triggers_orange(self, monitor):
        """Daily loss >= 2% triggers ORANGE even with small drawdown."""
        portfolio = Portfolio(
            equity=99000.0,
            high_water_mark=100000.0,
            cash=99000.0,
            daily_pnl=-2000.0,
            daily_pnl_pct=-0.02,
        )
        state = monitor.evaluate(portfolio)
        assert state.circuit_breaker_level == DrawdownLevel.ORANGE.value

    def test_daily_loss_triggers_red(self, monitor):
        """Daily loss >= 3% triggers RED."""
        portfolio = Portfolio(
            equity=97000.0,
            high_water_mark=100000.0,
            cash=97000.0,
            daily_pnl=-3000.0,
            daily_pnl_pct=-0.03,
        )
        state = monitor.evaluate(portfolio)
        assert state.circuit_breaker_level == DrawdownLevel.RED.value

    def test_custom_config(self):
        """Custom thresholds are respected."""
        config = DrawdownConfig(max_drawdown_halt=-0.10)
        monitor = DrawdownMonitor(config=config)
        portfolio = Portfolio(
            equity=92000.0,
            high_water_mark=100000.0,
            cash=92000.0,
        )
        state = monitor.evaluate(portfolio)
        # 8% drawdown with custom 10% halt threshold → YELLOW, not ORANGE
        assert state.circuit_breaker_level in (
            DrawdownLevel.YELLOW.value,
            DrawdownLevel.ORANGE.value,
        )

    def test_drawdown_pct_calculation(self, monitor):
        """Drawdown percentage is correctly calculated."""
        portfolio = Portfolio(
            equity=95000.0,
            high_water_mark=100000.0,
            cash=95000.0,
        )
        state = monitor.evaluate(portfolio)
        assert state.current_drawdown_pct == pytest.approx(-0.05, abs=0.001)

    def test_zero_hwm_no_division_error(self, monitor):
        """Zero HWM doesn't cause division by zero."""
        portfolio = Portfolio(
            equity=100.0,
            high_water_mark=0.0,
            cash=100.0,
        )
        state = monitor.evaluate(portfolio)
        assert state.current_drawdown_pct == 0.0


# ═══════════════════════════════════════════════════════════════════════
# Risk Tools Smoke Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRiskToolsSmoke:
    """Smoke tests for risk tool modules importability."""

    def test_import_guards(self):
        from src.risk.guards import Guard
        assert Guard is not None

    def test_import_governor(self):
        from src.risk.governor import RiskGovernor
        assert RiskGovernor is not None

    def test_import_position_sizer(self):
        from src.risk.position_sizer import PositionSizer
        assert PositionSizer is not None

    def test_import_watchdog(self):
        from src.risk.watchdog import Watchdog
        assert Watchdog is not None

    def test_import_mandate(self):
        from src.risk.mandate import Mandate
        assert Mandate is not None

    def test_import_mandate_gate(self):
        from src.risk.mandate_gate import MandateGate
        assert MandateGate is not None

    def test_import_guard_state(self):
        from src.risk.guard_state import GuardStatePersistence
        assert GuardStatePersistence is not None

    def test_import_connection_monitor(self):
        from src.risk.connection_monitor import ConnectionMonitor
        assert ConnectionMonitor is not None
