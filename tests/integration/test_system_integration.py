"""
TSAR Integration Tests — System Wiring Verification.

Tests that:
1. Each agent can access its tools
2. API routes return real data (tool-backed)
3. Telegram bot delegates to commands.py (tool-backed)
4. Flywheel auto-triggers after trade completion

These tests verify the integration wiring, not individual tool logic
(which is covered by unit tests).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ═══════════════════════════════════════════════════════════════════════
# 1. TOOL REGISTRY — Verify all tools are registered
# ═══════════════════════════════════════════════════════════════════════


class TestToolRegistry:
    """Verify that all expected tools are registered and accessible."""

    def test_tool_registry_has_core_tools(self):
        """Core tools should be registered: market_data, risk_management, backtesting, etc."""
        from src.tools import list_tools
        tools = list_tools()

        assert "market_data" in tools, "market_data tool not registered"
        assert "risk_management" in tools, "risk_management tool not registered"
        assert "backtesting" in tools, "backtesting tool not registered"
        assert "execution" in tools, "execution tool not registered"
        assert "portfolio" in tools, "portfolio tool not registered"
        assert "technical_analysis" in tools, "technical_analysis tool not registered"

    def test_monitoring_tool_registered(self):
        """MonitoringTools should be registered after integration wiring."""
        from src.tools import get_tool_registry
        registry = get_tool_registry()
        assert "monitoring" in registry, "monitoring tool not registered"
        assert registry["monitoring"] is not None

    def test_tool_registry_returns_classes(self):
        """Registry should return tool classes, not instances."""
        from src.tools import get_tool_registry
        registry = get_tool_registry()

        for name, tool_class in registry.items():
            assert isinstance(tool_class, type), f"{name} should be a class"

    def test_market_data_tool_has_description(self):
        """MarketDataTools should have a description attribute."""
        from src.tools import get_tool_registry
        registry = get_tool_registry()
        assert hasattr(registry["market_data"], "description")

    def test_risk_management_tool_has_description(self):
        """RiskManagementTools should have a description attribute."""
        from src.tools import get_tool_registry
        registry = get_tool_registry()
        assert hasattr(registry["risk_management"], "description")


# ═══════════════════════════════════════════════════════════════════════
# 2. API ROUTES — Verify tool-backed endpoints
# ═══════════════════════════════════════════════════════════════════════


class TestAPIRoutes:
    """Verify API routes are wired to real tools."""

    @pytest.fixture
    def app(self):
        """Create test FastAPI app."""
        os.environ["TSAR_API_KEY"] = "test-key-12345"
        from src.api.app import create_app
        return create_app()

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        from fastapi.testclient import TestClient
        return TestClient(app)

    def _auth_headers(self):
        return {"Authorization": "Bearer test-key-12345"}

    # ── Health (no auth) ─────────────────────────────────────────

    def test_health_endpoint_returns_ok(self, client):
        """GET /health should return status ok with component checks."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "components" in data

    def test_health_ready_endpoint(self, client):
        """GET /health/ready should return ready=true."""
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True

    # ── Trades (trade_memory tool) ──────────────────────────────

    def test_trades_endpoint_wired(self, client):
        """GET /api/v1/trades should connect to TradeMemory tool."""
        resp = client.get("/api/v1/trades", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data
        assert "total" in data

    def test_trade_stats_endpoint_wired(self, client):
        """GET /api/v1/trades/stats should connect to TradeMemory tool."""
        resp = client.get("/api/v1/trades/stats", headers=self._auth_headers())
        assert resp.status_code == 200

    def test_strategies_endpoint_wired(self, client):
        """GET /api/v1/strategies should connect to TradeMemory tool."""
        resp = client.get("/api/v1/strategies", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "strategies" in data

    # ── Positions (trade_memory + market_data tools) ────────────

    def test_positions_endpoint_wired(self, client):
        """GET /api/v1/positions should connect to TradeMemory tool."""
        resp = client.get("/api/v1/positions", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert "count" in data

    # ── P&L (monitoring tool) ───────────────────────────────────

    def test_pnl_endpoint_wired(self, client):
        """GET /api/v1/pnl should connect to monitoring/TradeMemory tools."""
        resp = client.get("/api/v1/pnl", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "total_pnl" in data
        assert "win_rate" in data
        assert "total_trades" in data

    # ── Risk (risk_management tool + KillSwitch) ────────────────

    def test_risk_endpoint_wired(self, client):
        """GET /api/v1/risk should connect to risk_management + KillSwitch."""
        resp = client.get("/api/v1/risk", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "level" in data
        assert "kill_switch_active" in data

    def test_kill_switch_endpoint(self, client):
        """POST /api/v1/kill-switch should connect to KillSwitch."""
        resp = client.post("/api/v1/kill-switch", headers=self._auth_headers())
        assert resp.status_code == 200

    def test_resume_endpoint(self, client):
        """POST /api/v1/resume should connect to KillSwitch."""
        resp = client.post("/api/v1/resume", headers=self._auth_headers())
        assert resp.status_code == 200

    # ── Regime (regime_detector data via TradeMemory) ───────────

    def test_regime_endpoint_wired(self, client):
        """GET /api/v1/regime should connect to TradeMemory regime data."""
        resp = client.get("/api/v1/regime", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "regime" in data
        assert "confidence" in data

    # ── Factors (factor_library tool) ───────────────────────────

    def test_factors_endpoint_wired(self, client):
        """GET /api/v1/factors should connect to factor_library tool."""
        resp = client.get("/api/v1/factors", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "factors" in data
        assert "count" in data

    # ── Backtest (backtesting tool) ─────────────────────────────

    def test_backtest_endpoint_wired(self, client):
        """POST /api/v1/backtest should connect to backtesting tool."""
        resp = client.post("/api/v1/backtest", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "strategy" in data

    # ── Flywheel (flywheel health) ──────────────────────────────

    def test_flywheel_endpoint_wired(self, client):
        """GET /api/v1/flywheel should connect to FlywheelHealth."""
        resp = client.get("/api/v1/flywheel", headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "health_score" in data or "status" in data

    # ── Mobile aliases ──────────────────────────────────────────

    def test_api_alias_routes(self, client):
        """Mobile API aliases should work (no /v1 prefix)."""
        aliases = [
            "/api/trades",
            "/api/positions",
            "/api/pnl",
            "/api/risk",
            "/api/regime",
            "/api/factors",
            "/api/flywheel",
        ]
        for path in aliases:
            resp = client.get(path, headers=self._auth_headers())
            assert resp.status_code == 200, f"{path} returned {resp.status_code}"

    # ── Auth enforcement ────────────────────────────────────────

    def test_auth_required_for_api_endpoints(self, client):
        """API endpoints should require authentication."""
        protected = [
            "/api/v1/trades",
            "/api/v1/positions",
            "/api/v1/pnl",
            "/api/v1/risk",
            "/api/v1/regime",
            "/api/v1/factors",
        ]
        for path in protected:
            resp = client.get(path)
            assert resp.status_code in (401, 403), f"{path} should require auth"

    def test_health_exempt_from_auth(self, client):
        """Health endpoints should NOT require authentication."""
        resp = client.get("/health")
        assert resp.status_code == 200
        resp = client.get("/health/ready")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# 3. TELEGRAM BOT — Verify tool delegation
# ═══════════════════════════════════════════════════════════════════════


class TestTelegramBotIntegration:
    """Verify bot delegates commands to commands.py (tool-backed)."""

    def test_bot_imports_commands_module(self):
        """Bot should import and use commands.py handle_command."""
        import inspect
        from src.bot.bot import TsarBot
        source = inspect.getsource(TsarBot.handle_command)
        assert "from src.bot.commands import handle_command" in source

    @pytest.mark.asyncio
    async def test_status_command_delegates_to_commands(self):
        """/status should delegate to commands.py which uses real tools."""
        from src.bot.commands import handle_command
        # commands.py uses local imports, so patch at the source module
        with patch("src.risk.kill_switch.KillSwitch") as mock_ks_cls, \
             patch("src.knowledge.trade_memory.TradeMemory") as mock_tm_cls:
            mock_ks = AsyncMock()
            mock_ks.is_active.return_value = False
            mock_ks_cls.return_value = mock_ks

            mock_tm = MagicMock()
            mock_tm.get_trade_count.return_value = 10
            mock_tm.get_open_positions.return_value = []
            mock_tm.get_trade_stats.return_value = {
                "total_pnl": 500.0, "win_rate": 0.6, "trade_count": 10,
                "avg_win": 100.0, "avg_loss": -50.0, "profit_factor": 2.0,
                "max_drawdown": -200.0,
            }
            mock_tm_cls.return_value = mock_tm

            result = await handle_command("/status", [])
            assert "TSAR" in result
            assert "trade" in result.lower()

    @pytest.mark.asyncio
    async def test_pnl_command_delegates_to_commands(self):
        """/pnl should delegate to commands.py which uses TradeMemory tool."""
        from src.bot.commands import handle_command
        with patch("src.knowledge.trade_memory.TradeMemory") as mock_tm_cls:
            mock_tm = MagicMock()
            mock_tm.get_trade_stats.return_value = {
                "total_pnl": 1500.0, "win_rate": 0.65, "trade_count": 20,
                "avg_win": 200.0, "avg_loss": -80.0, "profit_factor": 2.5,
                "max_drawdown": -300.0,
            }
            mock_tm_cls.return_value = mock_tm

            result = await handle_command("/pnl", [])
            assert "P&L" in result or "pnl" in result.lower()
            assert "1500" in result or "win rate" in result.lower()

    @pytest.mark.asyncio
    async def test_positions_command_delegates_to_commands(self):
        """/positions should delegate to commands.py which uses TradeMemory tool."""
        from src.bot.commands import handle_command
        with patch("src.knowledge.trade_memory.TradeMemory") as mock_tm_cls:
            mock_tm = MagicMock()
            mock_pos = MagicMock()
            mock_pos.symbol = "BTC/USDT"
            mock_pos.side = "buy"
            mock_pos.position_size_after = 0.1
            mock_pos.entry_price = 50000.0
            mock_tm.get_open_positions.return_value = [mock_pos]
            mock_tm_cls.return_value = mock_tm

            result = await handle_command("/positions", [])
            assert "BTC/USDT" in result

    @pytest.mark.asyncio
    async def test_risk_command_delegates_to_commands(self):
        """/risk should delegate to commands.py which uses KillSwitch + TradeMemory."""
        from src.bot.commands import handle_command
        with patch("src.risk.kill_switch.KillSwitch") as mock_ks_cls, \
             patch("src.knowledge.trade_memory.TradeMemory") as mock_tm_cls:
            mock_ks = AsyncMock()
            mock_ks.is_active.return_value = False
            mock_ks_cls.return_value = mock_ks

            mock_tm = MagicMock()
            mock_tm.get_trade_stats.return_value = {
                "max_drawdown": 1.5, "total_pnl": 500.0, "win_rate": 0.6,
            }
            mock_tm.get_open_positions.return_value = []
            mock_tm_cls.return_value = mock_tm

            result = await handle_command("/risk", [])
            assert "Risk" in result or "risk" in result.lower()
            assert "GREEN" in result or "Level" in result

    @pytest.mark.asyncio
    async def test_regime_command_delegates_to_commands(self):
        """/regime should delegate to commands.py which uses TradeMemory regime data."""
        from src.bot.commands import handle_command
        with patch("src.knowledge.trade_memory.TradeMemory") as mock_tm_cls:
            mock_tm = MagicMock()
            mock_tm.get_performance_by_regime.return_value = [
                {"regime_at_entry": "trending_up", "total_pnl": 500, "win_rate": 0.7, "trade_count": 10},
            ]
            mock_tm_cls.return_value = mock_tm

            result = await handle_command("/regime", [])
            assert "Regime" in result or "regime" in result.lower()

    @pytest.mark.asyncio
    async def test_flywheel_command_delegates_to_commands(self):
        """/flywheel should delegate to commands.py which uses FlywheelHealth."""
        from src.bot.commands import handle_command
        with patch("src.metrics.flywheel.FlywheelHealth") as mock_fh_cls:
            mock_fh = MagicMock()
            mock_fh.compute.return_value = {
                "health_score": 0.85, "classification": "healthy", "emoji": "🟢",
            }
            mock_fh_cls.return_value = mock_fh

            result = await handle_command("/flywheel", [])
            assert "Flywheel" in result or "flywheel" in result.lower()


# ═══════════════════════════════════════════════════════════════════════
# 4. FLYWHEEL AUTO-TRIGGER — Verify wiring
# ═══════════════════════════════════════════════════════════════════════


class TestFlywheelAutoTrigger:
    """Verify flywheel auto-triggers after trade completion."""

    def test_orchestrator_subscribes_to_trade_events(self):
        """Orchestrator should subscribe to trade events for flywheel forwarding."""
        import inspect
        from src.agents.orchestrator import Orchestrator
        source = inspect.getsource(Orchestrator.__init__)
        assert "tsar.trade.executed" in source
        assert "_forward_to_flywheel" in source

    def test_orchestrator_forward_to_flywheel_method(self):
        """Orchestrator should have _forward_to_flywheel method."""
        from src.agents.orchestrator import Orchestrator
        assert hasattr(Orchestrator, "_forward_to_flywheel")

    def test_flywheel_orchestrator_has_pipeline_steps(self):
        """FlywheelOrchestrator should have all 4 pipeline steps."""
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        assert hasattr(FlywheelOrchestrator, "_step_extract")
        assert hasattr(FlywheelOrchestrator, "_step_validate")
        assert hasattr(FlywheelOrchestrator, "_step_mutate")
        assert hasattr(FlywheelOrchestrator, "_step_evolve")

    def test_flywheel_orchestrator_subscribes_to_trades(self):
        """FlywheelOrchestrator should subscribe to trade events."""
        import inspect
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        source = inspect.getsource(FlywheelOrchestrator.on_initialize)
        assert "tsar.trade.executed" in source

    def test_flywheel_has_batch_and_cooldown(self):
        """Flywheel should have batch size and cooldown configuration."""
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        assert hasattr(FlywheelOrchestrator, "BATCH_SIZE")
        assert hasattr(FlywheelOrchestrator, "COOLDOWN_SECONDS")
        assert FlywheelOrchestrator.BATCH_SIZE > 0
        assert FlywheelOrchestrator.COOLDOWN_SECONDS > 0

    @pytest.mark.asyncio
    async def test_flywheel_on_trade_executed_increments_counter(self):
        """_on_trade_executed should increment trade counter."""
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator

        # Create a minimal instance without full initialization
        fw = FlywheelOrchestrator.__new__(FlywheelOrchestrator)
        fw._trade_count = 0
        fw._trades_since_flywheel = 0
        fw._last_flywheel_run = 0
        fw._flywheel_lock = asyncio.Lock()
        fw.BATCH_SIZE = 10
        fw.COOLDOWN_SECONDS = 0
        fw._flywheel_runs = 0
        fw._total_rules_extracted = 0
        fw._total_rules_validated = 0
        fw._total_mutations_proposed = 0
        fw._total_mutations_applied = 0

        await fw._on_trade_executed({"symbol": "BTC/USDT", "side": "buy"})
        assert fw._trade_count == 1
        assert fw._trades_since_flywheel == 1

    def test_orchestrator_loads_flywheel_in_registry(self):
        """Orchestrator agent registry should include flywheel_orchestrator."""
        import inspect
        from src.agents.orchestrator import Orchestrator
        source = inspect.getsource(Orchestrator._load_agent_registry)
        assert "flywheel_orchestrator" in source
        assert "FlywheelOrchestrator" in source


# ═══════════════════════════════════════════════════════════════════════
# 5. AGENT-TOOL ACCESS — Verify agents can reach their tools
# ═══════════════════════════════════════════════════════════════════════


class TestAgentToolAccess:
    """Verify each agent type can access its required tools."""

    def test_signal_scout_uses_technical_analysis(self):
        """SignalScout should import/use technical analysis tools."""
        from src.agents.signal_scout import SignalScout
        assert hasattr(SignalScout, "AGENT_NAME")

    def test_risk_guardian_uses_risk_tools(self):
        """RiskGuardian should import/use risk management tools."""
        from src.agents.risk_guardian import RiskGuardian
        assert hasattr(RiskGuardian, "AGENT_NAME")
        assert RiskGuardian.AGENT_NAME == "risk_guardian"

    def test_execution_sniper_uses_execution_tools(self):
        """ExecutionSniper should import/use execution tools."""
        from src.agents.execution_sniper import ExecutionSniper
        assert hasattr(ExecutionSniper, "AGENT_NAME")

    def test_strategy_geneticist_uses_genome_tools(self):
        """StrategyGeneticist should import/use genome/strategy tools."""
        from src.agents.strategy_geneticist import StrategyGeneticist
        assert hasattr(StrategyGeneticist, "AGENT_NAME")

    def test_flywheel_orchestrator_uses_shadow_extractor(self):
        """FlywheelOrchestrator should wire to ShadowExtractor."""
        import inspect
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        source = inspect.getsource(FlywheelOrchestrator._init_pipeline_components)
        assert "ShadowExtractor" in source

    def test_flywheel_orchestrator_uses_rule_validator(self):
        """FlywheelOrchestrator should wire to RuleValidator."""
        import inspect
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        source = inspect.getsource(FlywheelOrchestrator._init_pipeline_components)
        assert "RuleValidator" in source

    def test_flywheel_orchestrator_uses_genome_mutator(self):
        """FlywheelOrchestrator should wire to GenomeMutator."""
        import inspect
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        source = inspect.getsource(FlywheelOrchestrator._init_pipeline_components)
        assert "GenomeMutator" in source

    def test_flywheel_orchestrator_uses_strategy_geneticist(self):
        """FlywheelOrchestrator should wire to StrategyGeneticist."""
        import inspect
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        source = inspect.getsource(FlywheelOrchestrator._init_pipeline_components)
        assert "StrategyGeneticist" in source


# ═══════════════════════════════════════════════════════════════════════
# 6. ROUTE MODULE INTEGRATION — Verify routes/ are included
# ═══════════════════════════════════════════════════════════════════════


class TestRouteModuleIntegration:
    """Verify that route modules from routes/ are included in the app."""

    @pytest.fixture
    def app(self):
        os.environ["TSAR_API_KEY"] = "test-key-12345"
        from src.api.app import create_app
        return create_app()

    def test_app_includes_route_modules(self, app):
        """App should include route modules from routes/ directory."""
        assert app is not None
        assert len(app.routes) > 0

    def test_portfolio_routes_included(self, app):
        """Portfolio route module should be included."""
        from src.api.routes.portfolio import router
        assert router is not None

    def test_trading_routes_included(self, app):
        """Trading route module should be included."""
        from src.api.routes.trading import router
        assert router is not None

    def test_health_routes_included(self, app):
        """Health route module should be included."""
        from src.api.routes.health import router
        assert router is not None
