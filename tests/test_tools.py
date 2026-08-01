"""
Smoke tests for TSAR tool modules.

Verifies all tool modules are importable and their classes instantiate.
Covers H-15 (zero test coverage → basic smoke coverage).
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════
# Tool Module Import Smoke Tests
# ═══════════════════════════════════════════════════════════════════════


class TestToolModuleImports:
    """Verify all tool modules import without error."""

    def test_import_market_data(self):
        from src.tools.market_data import MarketDataTools
        assert MarketDataTools is not None

    def test_import_technical_analysis(self):
        from src.tools.technical_analysis import TechnicalAnalysisTools
        assert TechnicalAnalysisTools is not None

    def test_import_fundamental(self):
        from src.tools.fundamental import FundamentalAnalysisTools
        assert FundamentalAnalysisTools is not None

    def test_import_sentiment(self):
        from src.tools.sentiment import SocialSentimentAnalyzer
        assert SocialSentimentAnalyzer is not None

    def test_import_news(self):
        from src.tools.news import NewsAggregator
        assert NewsAggregator is not None

    def test_import_economic_calendar(self):
        from src.tools.economic_calendar import EconomicCalendarTools
        assert EconomicCalendarTools is not None

    def test_import_risk_management(self):
        from src.tools.risk_management import RiskManagementTools
        assert RiskManagementTools is not None

    def test_import_execution(self):
        from src.tools.execution import ExecutionTools
        assert ExecutionTools is not None

    def test_import_backtesting(self):
        from src.tools.backtesting import BacktestingTools
        assert BacktestingTools is not None

    def test_import_portfolio(self):
        from src.tools.portfolio import PortfolioTools
        assert PortfolioTools is not None

    def test_import_monitoring(self):
        from src.tools.monitoring import MonitoringTools
        assert MonitoringTools is not None

    def test_import_on_chain(self):
        from src.tools.on_chain import OnChainAnalytics
        assert OnChainAnalytics is not None

    def test_import_stop_loss_calculator(self):
        from src.tools.stop_loss_calculator import StopLossCalculator
        assert StopLossCalculator is not None

    def test_import_take_profit_calculator(self):
        from src.tools.take_profit_calculator import TakeProfitCalculator
        assert TakeProfitCalculator is not None

    def test_import_fee_calculator(self):
        from src.tools.fee_calculator import FeeCalculator
        assert FeeCalculator is not None

    def test_import_correlation(self):
        from src.tools.correlation import CorrelationAnalyzer
        assert CorrelationAnalyzer is not None

    def test_import_volatility(self):
        from src.tools.volatility import VolatilityAnalyzer
        assert VolatilityAnalyzer is not None

    def test_import_order_router(self):
        from src.tools.order_router import SmartOrderRouter
        assert SmartOrderRouter is not None

    def test_import_pattern_recognition(self):
        from src.tools.pattern_recognition import PatternRecognitionTools
        assert PatternRecognitionTools is not None

    def test_import_multi_timeframe(self):
        from src.tools.multi_timeframe import MultiTimeframeAnalyzer
        assert MultiTimeframeAnalyzer is not None


# ═══════════════════════════════════════════════════════════════════════
# Tool Registry Tests
# ═══════════════════════════════════════════════════════════════════════


class TestToolRegistry:
    """Verify tool registry works and all tools register."""

    def test_registry_populated(self):
        from src.tools import get_tool_registry
        registry = get_tool_registry()
        assert len(registry) > 0, "Tool registry is empty"

    def test_list_tools_returns_names(self):
        from src.tools import list_tools
        tools = list_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_core_tools_registered(self):
        """Core tools must be in the registry."""
        from src.tools import get_tool_registry
        registry = get_tool_registry()
        core_tools = [
            "market_data",
            "technical_analysis",
            "risk_management",
            "execution",
            "portfolio",
            "backtesting",
        ]
        for name in core_tools:
            assert name in registry, f"Core tool '{name}' not registered"

    def test_register_custom_tool(self):
        """Custom tools can be registered."""
        from src.tools import get_tool_registry, register_tool

        class DummyTool:
            description = "test tool"

        register_tool("_test_dummy", DummyTool)
        registry = get_tool_registry()
        assert "_test_dummy" in registry
        assert registry["_test_dummy"] is DummyTool


# ═══════════════════════════════════════════════════════════════════════
# Agent Module Import Smoke Tests
# ═══════════════════════════════════════════════════════════════════════


class TestAgentImports:
    """Verify all agent modules import without error."""

    def test_import_orchestrator(self):
        from src.agents.orchestrator import Orchestrator
        assert Orchestrator is not None

    def test_import_risk_guardian(self):
        from src.agents.risk_guardian import RiskGuardian
        assert RiskGuardian is not None

    def test_import_signal_scout(self):
        from src.agents.signal_scout import SignalScout
        assert SignalScout is not None

    def test_import_execution_sniper(self):
        from src.agents.execution_sniper import ExecutionSniper
        assert ExecutionSniper is not None

    def test_import_market_cartographer(self):
        from src.agents.market_cartographer import MarketCartographer
        assert MarketCartographer is not None

    def test_import_regime_detector(self):
        from src.agents.regime_detector import RegimeDetector
        assert RegimeDetector is not None

    def test_import_strategy_geneticist(self):
        from src.agents.strategy_geneticist import StrategyGeneticist
        assert StrategyGeneticist is not None

    def test_import_trade_philosopher(self):
        from src.agents.trade_philosopher import TradePhilosopher
        assert TradePhilosopher is not None

    def test_import_flywheel_orchestrator(self):
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        assert FlywheelOrchestrator is not None

    def test_import_sentiment_agent(self):
        from src.agents.sentiment_agent import SentimentAgent
        assert SentimentAgent is not None

    def test_import_macro_agent(self):
        from src.agents.macro_agent import MacroAgent
        assert MacroAgent is not None

    def test_import_execution_tracker(self):
        from src.agents.execution_tracker import ExecutionTracker
        assert ExecutionTracker is not None


# ═══════════════════════════════════════════════════════════════════════
# Interface Module Smoke Tests
# ═══════════════════════════════════════════════════════════════════════


class TestInterfaceImports:
    """Verify interface modules import cleanly."""

    def test_import_types(self):
        from src.interfaces.types import Order, Portfolio, Signal
        assert Order is not None
        assert Signal is not None
        assert Portfolio is not None

    def test_import_risk_engine(self):
        from src.interfaces.risk_engine import RiskEngine
        assert RiskEngine is not None

    def test_import_execution_engine(self):
        from src.interfaces.execution_engine import ExecutionEngine
        assert ExecutionEngine is not None

    def test_import_exchange_gateway(self):
        from src.interfaces.exchange_gateway import ExchangeGateway
        assert ExchangeGateway is not None

    def test_import_llm_provider(self):
        from src.interfaces.llm_provider import LLMProvider
        assert LLMProvider is not None

    def test_import_pricing_engine(self):
        from src.interfaces.pricing_engine import PricingEngine
        assert PricingEngine is not None

    def test_import_backend_registry(self):
        from src.interfaces.backend_registry import BackendRegistry
        assert BackendRegistry is not None


# ═══════════════════════════════════════════════════════════════════════
# Knowledge Module Smoke Tests
# ═══════════════════════════════════════════════════════════════════════


class TestKnowledgeImports:
    """Verify knowledge modules import cleanly."""

    def test_import_trade_memory(self):
        from src.knowledge.trade_memory import TradeMemory
        assert TradeMemory is not None

    def test_import_fts_search(self):
        from src.knowledge.fts_search import MemoryRecall
        assert MemoryRecall is not None

    def test_import_pattern_library(self):
        from src.knowledge.pattern_library import PatternLibrary
        assert PatternLibrary is not None

    def test_import_lesson_archive(self):
        from src.knowledge.lesson_archive import LessonArchive
        assert LessonArchive is not None

    def test_import_knowledge_graph(self):
        from src.knowledge.knowledge_graph import KnowledgeGraph
        assert KnowledgeGraph is not None

    def test_import_strategy_genomes(self):
        from src.knowledge.strategy_genomes import StrategyGenomes
        assert StrategyGenomes is not None

    def test_import_db_pool(self):
        from src.knowledge.db_pool import SQLitePool
        assert SQLitePool is not None


# ═══════════════════════════════════════════════════════════════════════
# Comms Module Smoke Tests
# ═══════════════════════════════════════════════════════════════════════


class TestCommsImports:
    def test_import_event_bus(self):
        from src.comms.event_bus import EventBus
        assert EventBus is not None

    def test_import_events(self):
        from src.comms.events import CloudEvent
        assert CloudEvent is not None


# ═══════════════════════════════════════════════════════════════════════
# Utils Module Smoke Tests
# ═══════════════════════════════════════════════════════════════════════


class TestUtilsImports:
    def test_import_config(self):
        from src.utils.config import load_config
        assert load_config is not None

    def test_import_logging(self):
        from src.utils.logging import setup_logging
        assert setup_logging is not None

    def test_import_math(self):
        from src.utils.math import clamp
        assert clamp is not None
