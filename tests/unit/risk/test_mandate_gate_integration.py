"""
Unit tests for MandateGate integration into RiskGuardian.

Tests cover:
  - MandateGate initialized in RiskGuardian.__init__
  - MandateGate as Check 0 in _evaluate_signal
  - Paper mode bypasses mandate checks
  - Mandate DRAFT blocks live trades
  - Mandate ACTIVE allows live trades
  - MandateGate rejection skips remaining risk checks
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.agents.risk_guardian import RiskGuardian
from src.comms.events import CloudEvent
from src.interfaces.types import (
    OrderSide,
    RiskDecision,
    Signal,
    VetoLevel,
)
from src.risk.mandate import Mandate, MandateRules, MandateState, MandateStatus
from src.risk.mandate_gate import MandateGate


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _tmp_yaml(data: dict) -> str:
    """Write a dict to a temp YAML file and return the path."""
    f = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w")
    yaml.dump(data, f, default_flow_style=False)
    f.close()
    return f.name


def _make_mandate_yaml(
    allowed_symbols: list[str] | None = None,
    max_daily_trades: int = 10,
    status: str = "active",
    committed_by: str = "test-user",
) -> str:
    """Create a mandate YAML file with the given rules."""
    if allowed_symbols is None:
        allowed_symbols = ["BTC/USDT", "ETH/USDT"]
    data = {
        "rules": {
            "allowed_symbols": allowed_symbols,
            "max_position_size_pct": 0.15,
            "max_daily_trades": max_daily_trades,
            "max_leverage": 1.0,
            "allowed_order_types": ["market", "limit"],
            "max_notional_per_trade": 10000.0,
            "allowed_sides": ["buy", "sell"],
        },
        "status": status,
        "committed_at": "2025-01-01T00:00:00Z" if status == "active" else None,
        "committed_by": committed_by if status == "active" else None,
        "revoked_at": None,
        "revoked_by": None,
        "version": 1,
        "notes": "test mandate",
    }
    return _tmp_yaml(data)


def _make_signal(
    symbol: str = "BTC/USDT",
    side: OrderSide = OrderSide.BUY,
    score: float = 0.75,
    entry_price: float = 50000.0,
    stop_loss: float = 49500.0,
    take_profit: float = 51000.0,
    metadata: dict[str, Any] | None = None,
) -> Signal:
    """Create a test signal."""
    return Signal(
        signal_id="sig-integration-001",
        symbol=symbol,
        side=side,
        score=score,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        strategy="test_strategy",
        reasoning="Integration test signal",
        metadata=metadata or {},
    )


def _make_cloud_event(signal: Signal) -> CloudEvent:
    """Wrap a signal in a CloudEvent."""
    return CloudEvent(
        type="tsar.signal.detected.v1",
        source="test",
        data={
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "side": signal.side.value,
            "score": signal.score,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "strategy": signal.strategy,
            "reasoning": signal.reasoning,
            "metadata": signal.metadata,
        },
        traceid="test-trace-001",
    )


def _make_risk_guardian(
    trading_mode: str = "live",
    mandate_config_path: str | None = None,
    mandate_enabled: bool = True,
) -> RiskGuardian:
    """Create a RiskGuardian with MandateGate configured."""
    config: dict[str, Any] = {
        "risk": {
            "mandate_gate": {
                "enabled": mandate_enabled,
                "config_path": mandate_config_path or _make_mandate_yaml(),
            }
        }
    }
    guardian = RiskGuardian(config=config, trading_mode=trading_mode)
    return guardian


# ═══════════════════════════════════════════════════════════════════════
# G4: MandateGate Wiring Tests
# ═══════════════════════════════════════════════════════════════════════


class TestMandateGateInitialization:
    """Test MandateGate is properly initialized in RiskGuardian."""

    def test_mandate_gate_created_when_enabled(self):
        """MandateGate should be created when mandate_gate.enabled=True."""
        guardian = _make_risk_guardian(mandate_enabled=True)
        assert guardian._mandate_gate is not None
        assert isinstance(guardian._mandate_gate, MandateGate)

    def test_mandate_gate_none_when_disabled(self):
        """MandateGate should be None when mandate_gate.enabled=False."""
        config: dict[str, Any] = {"risk": {"mandate_gate": {"enabled": False}}}
        guardian = RiskGuardian(config=config, trading_mode="live")
        assert guardian._mandate_gate is None

    def test_mandate_gate_default_enabled(self):
        """MandateGate should be enabled by default when no config given."""
        config: dict[str, Any] = {"risk": {}}
        guardian = RiskGuardian(config=config, trading_mode="live")
        assert guardian._mandate_gate is not None

    def test_is_live_set_correctly_for_live_mode(self):
        """_is_live should be True when trading_mode='live'."""
        guardian = _make_risk_guardian(trading_mode="live")
        assert guardian._is_live is True

    def test_is_live_set_correctly_for_paper_mode(self):
        """_is_live should be False when trading_mode='paper'."""
        guardian = _make_risk_guardian(trading_mode="paper")
        assert guardian._is_live is False


class TestPaperModeBypass:
    """Test that paper mode bypasses mandate checks entirely."""

    @pytest.mark.asyncio
    async def test_paper_mode_allows_signal(self):
        """In paper mode, MandateGate should not block any signal."""
        # Use a DRAFT mandate (would block in live mode)
        draft_yaml = _make_mandate_yaml(status="draft", allowed_symbols=[])
        guardian = _make_risk_guardian(trading_mode="paper", mandate_config_path=draft_yaml)

        # Mock risk engine to avoid initialization errors
        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal()
        event = _make_cloud_event(signal)

        # Track published events
        published = []
        guardian.publish_event = AsyncMock(side_effect=lambda **kw: published.append(kw))

        # Mock _run_all_checks to return approved (we only care about mandate gate)
        with patch.object(
            guardian, "_run_all_checks",
            return_value=RiskDecision(
                signal_id=signal.signal_id,
                approved=True,
                position_size=0.1,
                rejection_reasons=(),
                warnings=(),
                veto_level=VetoLevel.NONE.value,
                timestamp=datetime.now(timezone.utc),
            ),
        ):
            await guardian._evaluate_signal(event)

        # Should have published an approval (not a mandate veto)
        assert len(published) == 1
        assert published[0]["event_type"] == "tsar.risk.approved.v1"

    @pytest.mark.asyncio
    async def test_paper_mode_does_not_call_mandate_check(self):
        """In paper mode, MandateGate.check should NOT be called at all."""
        guardian = _make_risk_guardian(trading_mode="paper")

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal()
        event = _make_cloud_event(signal)

        guardian.publish_event = AsyncMock()
        with patch.object(
            guardian, "_run_all_checks",
            return_value=RiskDecision(
                signal_id=signal.signal_id,
                approved=True,
                position_size=0.1,
                rejection_reasons=(),
                warnings=(),
                veto_level=VetoLevel.NONE.value,
                timestamp=datetime.now(timezone.utc),
            ),
        ):
            with patch.object(guardian._mandate_gate, "check") as mock_check:
                await guardian._evaluate_signal(event)
                mock_check.assert_not_called()


class TestMandateDraftBlocksLiveTrades:
    """Test that a DRAFT mandate blocks all live trades."""

    @pytest.mark.asyncio
    async def test_draft_mandate_blocks_live_signal(self):
        """A DRAFT mandate should produce a HARD veto for live trades."""
        draft_yaml = _make_mandate_yaml(status="draft", allowed_symbols=[])
        guardian = _make_risk_guardian(trading_mode="live", mandate_config_path=draft_yaml)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal()
        event = _make_cloud_event(signal)

        published = []
        guardian.publish_event = AsyncMock(side_effect=lambda **kw: published.append(kw))

        await guardian._evaluate_signal(event)

        # Should have published a mandate veto
        assert len(published) == 1
        assert published[0]["event_type"] == "tsar.risk.vetoed.v1"
        assert published[0]["risk_level"] == "HARD"

    @pytest.mark.asyncio
    async def test_draft_mandate_skips_risk_checks(self):
        """When mandate rejects, _run_all_checks should NOT be called."""
        draft_yaml = _make_mandate_yaml(status="draft", allowed_symbols=[])
        guardian = _make_risk_guardian(trading_mode="live", mandate_config_path=draft_yaml)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal()
        event = _make_cloud_event(signal)

        guardian.publish_event = AsyncMock()

        with patch.object(guardian, "_run_all_checks") as mock_checks:
            await guardian._evaluate_signal(event)
            mock_checks.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoked_mandate_blocks_live_signal(self):
        """A REVOKED mandate should also block live trades."""
        revoked_yaml = _make_mandate_yaml(status="revoked")
        # Overwrite with revoked state
        data = yaml.safe_load(open(revoked_yaml))
        data["status"] = "revoked"
        data["revoked_at"] = "2025-01-15T00:00:00Z"
        data["revoked_by"] = "admin"
        with open(revoked_yaml, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        guardian = _make_risk_guardian(trading_mode="live", mandate_config_path=revoked_yaml)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal()
        event = _make_cloud_event(signal)

        published = []
        guardian.publish_event = AsyncMock(side_effect=lambda **kw: published.append(kw))

        await guardian._evaluate_signal(event)

        assert len(published) == 1
        assert published[0]["event_type"] == "tsar.risk.vetoed.v1"
        assert published[0]["risk_level"] == "HARD"


class TestMandateActiveAllowsLiveTrades:
    """Test that an ACTIVE mandate allows compliant live trades."""

    @pytest.mark.asyncio
    async def test_active_mandate_allows_compliant_signal(self):
        """An ACTIVE mandate should allow a signal that passes all checks."""
        active_yaml = _make_mandate_yaml(
            status="active",
            allowed_symbols=["BTC/USDT", "ETH/USDT"],
            max_daily_trades=10,
        )
        guardian = _make_risk_guardian(trading_mode="live", mandate_config_path=active_yaml)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal(symbol="BTC/USDT")
        event = _make_cloud_event(signal)

        published = []
        guardian.publish_event = AsyncMock(side_effect=lambda **kw: published.append(kw))

        with patch.object(
            guardian, "_run_all_checks",
            return_value=RiskDecision(
                signal_id=signal.signal_id,
                approved=True,
                position_size=0.1,
                rejection_reasons=(),
                warnings=(),
                veto_level=VetoLevel.NONE.value,
                timestamp=datetime.now(timezone.utc),
            ),
        ):
            await guardian._evaluate_signal(event)

        # Should have published an approval (mandate passed, risk checks passed)
        assert len(published) == 1
        assert published[0]["event_type"] == "tsar.risk.approved.v1"

    @pytest.mark.asyncio
    async def test_active_mandate_blocks_disallowed_symbol(self):
        """An ACTIVE mandate should block a symbol not in allowed_symbols."""
        active_yaml = _make_mandate_yaml(
            status="active",
            allowed_symbols=["ETH/USDT"],  # BTC not allowed
        )
        guardian = _make_risk_guardian(trading_mode="live", mandate_config_path=active_yaml)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal(symbol="BTC/USDT")
        event = _make_cloud_event(signal)

        published = []
        guardian.publish_event = AsyncMock(side_effect=lambda **kw: published.append(kw))

        await guardian._evaluate_signal(event)

        # Should be blocked by mandate
        assert len(published) == 1
        assert published[0]["event_type"] == "tsar.risk.vetoed.v1"
        assert published[0]["risk_level"] == "HARD"

    @pytest.mark.asyncio
    async def test_active_mandate_proceeds_to_risk_checks(self):
        """When mandate approves, _run_all_checks SHOULD be called."""
        active_yaml = _make_mandate_yaml(status="active")
        guardian = _make_risk_guardian(trading_mode="live", mandate_config_path=active_yaml)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal()
        event = _make_cloud_event(signal)

        guardian.publish_event = AsyncMock()

        with patch.object(
            guardian, "_run_all_checks",
            return_value=RiskDecision(
                signal_id=signal.signal_id,
                approved=True,
                position_size=0.1,
                rejection_reasons=(),
                warnings=(),
                veto_level=VetoLevel.NONE.value,
                timestamp=datetime.now(timezone.utc),
            ),
        ) as mock_checks:
            await guardian._evaluate_signal(event)
            mock_checks.assert_called_once()


class TestMandateGateDisabled:
    """Test behavior when MandateGate is explicitly disabled."""

    @pytest.mark.asyncio
    async def test_disabled_gate_skips_mandate_check(self):
        """When disabled, mandate check should be skipped even in live mode."""
        guardian = _make_risk_guardian(trading_mode="live", mandate_enabled=False)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        assert guardian._mandate_gate is None

        signal = _make_signal()
        event = _make_cloud_event(signal)

        guardian.publish_event = AsyncMock()

        with patch.object(
            guardian, "_run_all_checks",
            return_value=RiskDecision(
                signal_id=signal.signal_id,
                approved=True,
                position_size=0.1,
                rejection_reasons=(),
                warnings=(),
                veto_level=VetoLevel.NONE.value,
                timestamp=datetime.now(timezone.utc),
            ),
        ) as mock_checks:
            await guardian._evaluate_signal(event)
            # _run_all_checks should be called (mandate didn't block)
            mock_checks.assert_called_once()


class TestMandateVetoLevel:
    """Test that mandate rejections use HARD veto level."""

    @pytest.mark.asyncio
    async def test_mandate_rejection_is_hard_veto(self):
        """MandateGate rejection should always use VetoLevel.HARD."""
        draft_yaml = _make_mandate_yaml(status="draft")
        guardian = _make_risk_guardian(trading_mode="live", mandate_config_path=draft_yaml)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal()
        event = _make_cloud_event(signal)

        published = []
        guardian.publish_event = AsyncMock(side_effect=lambda **kw: published.append(kw))

        await guardian._evaluate_signal(event)

        assert len(published) == 1
        assert published[0]["risk_level"] == "HARD"

    @pytest.mark.asyncio
    async def test_mandate_rejection_contains_reasons(self):
        """MandateGate rejection data should contain rejection reasons."""
        draft_yaml = _make_mandate_yaml(status="draft")
        guardian = _make_risk_guardian(trading_mode="live", mandate_config_path=draft_yaml)

        with patch("src.interfaces.get_risk_engine", return_value=None):
            await guardian.on_initialize()

        signal = _make_signal()
        event = _make_cloud_event(signal)

        published = []
        guardian.publish_event = AsyncMock(side_effect=lambda **kw: published.append(kw))

        await guardian._evaluate_signal(event)

        data = published[0]["data"]
        assert "rejection_reasons" in data
        assert len(data["rejection_reasons"]) > 0
        # Should mention mandate
        assert any("Mandate" in r or "mandate" in r for r in data["rejection_reasons"])
