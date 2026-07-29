"""
TSAR Interface Layer — Abstract Base Classes and Backend Registry.

This module defines THE CONTRACT between the Agent Layer and Backend Layer.
Agent code imports from here. Agents NEVER import concrete backends.
"""

from typing import Any

from src.interfaces.types import (
    Balance,
    BollingerResult,
    ConnectionStatus,
    DrawdownLevel,
    DrawdownState,
    ExecutionResult,
    Fill,
    LLMChunk,
    LLMResponse,
    MACDResult,
    ModelCapabilities,
    OHLCV,
    Order,
    OrderBook,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    PositionSizeResult,
    Price,
    RiskCheckResult,
    RiskDecision,
    SRLevels,
    Signal,
    Timeframe,
    TimeInForce,
    Trade,
    VetoLevel,
)

# ═══════════════════════════════════════════════════════════════════════
# BACKEND REGISTRY SINGLETON
# ═══════════════════════════════════════════════════════════════════════

_backend_registry: "BackendRegistry | None" = None


def _get_registry() -> "BackendRegistry":
    """Get or create the global BackendRegistry singleton."""
    global _backend_registry
    if _backend_registry is None:
        from src.interfaces.backend_registry import BackendRegistry
        _backend_registry = BackendRegistry()
        _backend_registry._register_defaults()
    return _backend_registry


# ═══════════════════════════════════════════════════════════════════════
# CONVENIENCE GETTERS
# ═══════════════════════════════════════════════════════════════════════

def get_backend_registry() -> "BackendRegistry":
    """Get the global BackendRegistry instance.

    Returns:
        The singleton BackendRegistry.
    """
    return _get_registry()


def get_exchange_gateway() -> Any:
    """Get the configured ExchangeGateway backend.

    Returns:
        An ExchangeGateway instance (e.g. CcxtGateway).
    """
    return _get_registry().create("exchange_gateway")


def get_execution_engine() -> Any:
    """Get the configured ExecutionEngine backend.

    Returns:
        An ExecutionEngine instance (e.g. CcxtExecEngine).
    """
    return _get_registry().create("execution_engine")


def get_pricing_engine() -> Any:
    """Get the configured PricingEngine backend.

    Returns:
        A PricingEngine instance (e.g. PandasTAEngine).
    """
    return _get_registry().create("pricing_engine")


def get_risk_engine() -> Any:
    """Get the configured RiskEngine backend.

    Returns:
        A RiskEngine instance (e.g. PythonRiskEngine).
    """
    return _get_registry().create("risk_engine")


def get_llm_provider() -> Any:
    """Get the configured LLMProvider backend.

    Returns:
        An LLMProvider instance (e.g. OllamaProvider).
    """
    return _get_registry().create("llm_provider")


__all__ = [
    # Enums
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "Timeframe",
    "ConnectionStatus",
    "TimeInForce",
    "VetoLevel",
    "DrawdownLevel",
    # Core data types
    "Price",
    "OHLCV",
    "OrderBook",
    "Trade",
    "Position",
    "Balance",
    "Order",
    "OrderRequest",
    "Fill",
    # Signal & Risk types
    "Signal",
    "RiskDecision",
    "Portfolio",
    "DrawdownState",
    "RiskCheckResult",
    "PositionSizeResult",
    # Execution types
    "ExecutionResult",
    # Pricing types
    "MACDResult",
    "BollingerResult",
    "SRLevels",
    # LLM types
    "LLMResponse",
    "LLMChunk",
    "ModelCapabilities",
    # Getter functions
    "get_backend_registry",
    "get_exchange_gateway",
    "get_execution_engine",
    "get_pricing_engine",
    "get_risk_engine",
    "get_llm_provider",
]
