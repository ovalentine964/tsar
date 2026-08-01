"""
TSAR Domain-Specific Tools — Tool Registry & Discovery.

This module provides the unified interface for all trading tools
that TSAR agents use. Tools are organized by domain:

  1. Market Data Tools       — What the agent SEES
  2. Technical Analysis      — What the agent CALCULATES
  3. On-Chain Analytics      — What the chain REVEALS
  4. Social Sentiment        — What the crowd THINKS
  5. News Aggregation        — What is HAPPENING
  6. Economic Calendar       — What is COMING
  7. Project Fundamentals    — What the project IS
  8. Market Structure        — How the market is VALUED
  9. Risk Management         — What the agent PROTECTS
 10. Execution Tools         — What the agent DOES
 11. Backtesting Tools       — What the agent LEARNS FROM
 12. Portfolio Management    — What the agent OPTIMIZES
 13. Knowledge Tools         — What the agent REMEMBERS
 14. Knowledge Graph         — What the agent CONNECTS

Each tool category is a self-contained module with a clean async API.
Tools operate on the shared types from src.interfaces.types.

Usage:
    from src.tools import get_tool_registry
    registry = get_tool_registry()

    # List all available tools
    for name, tool in registry.items():
        print(f"{name}: {tool.description}")

    # Use a specific tool
    market_data = registry["market_data"]
    depth = await market_data.get_orderbook_depth("BTC/USDT")
"""

from __future__ import annotations

from typing import Any

# Tool registry — maps tool name → tool class
_TOOL_REGISTRY: dict[str, type] = {}


def register_tool(name: str, tool_class: type) -> None:
    """Register a tool class in the global registry."""
    _TOOL_REGISTRY[name] = tool_class


def get_tool_registry() -> dict[str, type]:
    """Get the complete tool registry."""
    return dict(_TOOL_REGISTRY)


def list_tools() -> list[str]:
    """List all registered tool names."""
    return list(_TOOL_REGISTRY.keys())


# Lazy imports to avoid circular dependencies
def _ensure_registered() -> None:
    """Ensure all tool modules are imported and registered."""
    if _TOOL_REGISTRY:
        return

    from src.tools.market_data import MarketDataTools
    from src.tools.technical_analysis import TechnicalAnalysisTools
    from src.tools.fundamental import FundamentalAnalysisTools
    from src.tools.on_chain import OnChainAnalytics
    from src.tools.sentiment import SocialSentimentAnalyzer
    from src.tools.news import NewsAggregator
    from src.tools.economic_calendar import EconomicCalendarTools
    from src.tools.risk_management import RiskManagementTools
    from src.tools.execution import ExecutionTools
    from src.tools.backtesting import BacktestingTools
    from src.tools.portfolio import PortfolioTools
    from src.tools.market_calendar import MarketCalendar

    register_tool("market_data", MarketDataTools)
    register_tool("technical_analysis", TechnicalAnalysisTools)
    register_tool("fundamental", FundamentalAnalysisTools)
    register_tool("on_chain", OnChainAnalytics)
    register_tool("sentiment", SocialSentimentAnalyzer)
    register_tool("news", NewsAggregator)
    register_tool("economic_calendar", EconomicCalendarTools)
    register_tool("market_calendar", MarketCalendar)
    register_tool("risk_management", RiskManagementTools)
    register_tool("execution", ExecutionTools)
    register_tool("backtesting", BacktestingTools)
    register_tool("portfolio", PortfolioTools)

    # Monitoring tools
    try:
        from src.tools.monitoring import MonitoringTools
        register_tool("monitoring", MonitoringTools)
    except ImportError:
        pass

    # Knowledge tools (may have unmet dependencies)
    try:
        from src.tools.knowledge import KnowledgeTools
        register_tool("knowledge", KnowledgeTools)
    except ImportError:
        pass

    try:
        from src.tools.knowledge_graph import KnowledgeGraphTools
        register_tool("knowledge_graph", KnowledgeGraphTools)
    except ImportError:
        pass

    # Risk tool extensions
    try:
        from src.tools.stop_loss_calculator import StopLossCalculator
        register_tool("stop_loss_calculator", StopLossCalculator)
    except ImportError:
        pass

    try:
        from src.tools.take_profit_calculator import TakeProfitCalculator
        register_tool("take_profit_calculator", TakeProfitCalculator)
    except ImportError:
        pass

    try:
        from src.tools.fee_calculator import FeeCalculator
        register_tool("fee_calculator", FeeCalculator)
    except ImportError:
        pass

    try:
        from src.tools.correlation import CorrelationAnalyzer
        register_tool("correlation", CorrelationAnalyzer)
    except ImportError:
        pass

    try:
        from src.tools.volatility import VolatilityAnalyzer
        register_tool("volatility", VolatilityAnalyzer)
    except ImportError:
        pass

    try:
        from src.tools.order_router import SmartOrderRouter
        register_tool("order_router", SmartOrderRouter)
    except ImportError:
        pass

    # MEV Protection tools
    try:
        from src.tools.mev_protection import MEVProtectionTools
        register_tool("mev_protection", MEVProtectionTools)
    except ImportError:
        pass

    try:
        from src.tools.pattern_recognition import PatternRecognitionTools
        register_tool("pattern_recognition", PatternRecognitionTools)
    except ImportError:
        pass

    try:
        from src.tools.multi_timeframe import MultiTimeframeAnalyzer
        register_tool("multi_timeframe", MultiTimeframeAnalyzer)
    except ImportError:
        pass

    # Settlement & L2 optimization tools
    try:
        from src.tools.settlement import SettlementTools
        register_tool("settlement", SettlementTools)
    except ImportError:
        pass

    # Information Asymmetry Tools (Anti-Loss: breaks the 78% retail disadvantage)
    try:
        from src.tools.order_flow import OrderFlowTools
        register_tool("order_flow", OrderFlowTools)
    except ImportError:
        pass

    try:
        from src.tools.market_microstructure import MarketMicrostructureTools
        register_tool("market_microstructure", MarketMicrostructureTools)
    except ImportError:
        pass

    # DeFi execution tools (requires web3, solana, cryptography)
    try:
        from src.tools.defi_execution import DeFiExecutionTools
        register_tool("defi_execution", DeFiExecutionTools)
    except ImportError:
        pass

    try:
        from src.tools.monitoring import PnLTracker, WinRateTracker, EquityCurve, RiskStateMonitor, AlertGenerator
        register_tool("pnl_tracker", PnLTracker)
        register_tool("win_rate_tracker", WinRateTracker)
        register_tool("equity_curve", EquityCurve)
        register_tool("risk_state_monitor", RiskStateMonitor)
        register_tool("alert_generator", AlertGenerator)
    except ImportError:
        pass

    # Flywheel health monitoring
    try:
        from src.tools.flywheel_health import FlywheelHealthTool
        register_tool("flywheel_health", FlywheelHealthTool)
    except ImportError:
        pass

    # Cross-chain tools (bridge + intent execution)
    try:
        from src.tools.cross_chain import CrossChainTools
        register_tool("cross_chain", CrossChainTools)
    except ImportError:
        pass

    # DeFi yield optimization tools
    try:
        from src.tools.defi_yield import DeFiYieldTools
        register_tool("defi_yield", DeFiYieldTools)
    except ImportError:
        pass


# Auto-register on first access
_ensure_registered()

__all__ = [
    "get_tool_registry",
    "list_tools",
    "register_tool",
]
