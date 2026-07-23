"""
Resource Profiles — Per-tool resource limit definitions.

Profiles define memory, CPU, wall time, and network limits per tool category.
Context-aware: tighter limits for live trading, looser for backtesting.
"""

from typing import Any

# Default resource limits
DEFAULT_LIMITS = {
    "max_memory_mb": 256,
    "max_wall_time_s": 30,
    "max_concurrent": 10,
    "max_calls_per_min": 1200,
    "max_cpu_seconds": 10,
    "max_network_requests": 100,
}

# Per-tool category profiles
TOOL_PROFILES: dict[str, dict[str, Any]] = {
    "exchange": {
        "max_memory_mb": 128,
        "max_cpu_seconds": 5,
        "max_wall_time_s": 15,
        "max_network_requests": 10,
    },
    "analysis": {
        "max_memory_mb": 256,
        "max_cpu_seconds": 10,
        "max_wall_time_s": 30,
        "max_network_requests": 100,
    },
    "risk": {
        "max_memory_mb": 128,
        "max_cpu_seconds": 5,
        "max_wall_time_s": 15,
        "max_network_requests": 0,
    },
    "heavy_compute": {
        "max_memory_mb": 512,
        "max_cpu_seconds": 30,
        "max_wall_time_s": 60,
        "max_network_requests": 100,
    },
    "execution": {
        "max_memory_mb": 256,
        "max_cpu_seconds": 15,
        "max_wall_time_s": 30,
        "max_network_requests": 200,
    },
}

# Context-aware adjustments
CONTEXT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "paper_trading": {},  # Standard limits
    "live_trading": {
        "max_wall_time_s": 0.7,  # Tighter timeouts
    },
    "backtesting": {
        "max_memory_mb": 2.0,  # More memory
        "max_cpu_seconds": 3.0,  # More CPU
    },
    "analysis_only": {},  # Standard limits
}


# Tool name -> category mapping
TOOL_CATEGORY_MAP: dict[str, str] = {
    # Exchange tools
    "place_order": "exchange",
    "cancel_order": "exchange",
    "get_order": "exchange",
    "get_balance": "exchange",
    "get_positions": "exchange",
    "get_orderbook": "exchange",
    "get_ticker": "exchange",
    "get_ohlcv": "exchange",
    # Analysis tools
    "compute_indicators": "analysis",
    "detect_patterns": "analysis",
    "analyze_sentiment": "analysis",
    "get_funding_rate": "analysis",
    "get_macro_data": "analysis",
    "search_patterns": "analysis",
    # Risk tools
    "check_risk": "risk",
    "position_size": "risk",
    "check_drawdown": "risk",
    "validate_signal": "risk",
    # Execution tools
    "execute_signal": "execution",
    "batch_execute": "execution",
    # Heavy compute
    "backtest": "heavy_compute",
    "optimize_genome": "heavy_compute",
    "train_model": "heavy_compute",
}


def get_tool_category(tool_name: str) -> str:
    """Resolve a tool name to its resource category.

    Args:
        tool_name: The tool/function name.

    Returns:
        Tool category string (exchange, analysis, risk, execution, heavy_compute).
        Defaults to "analysis" if unknown.
    """
    return TOOL_CATEGORY_MAP.get(tool_name, "analysis")


def get_limits(tool_category: str, context: str = "paper_trading") -> dict[str, Any]:
    """Get resource limits for a tool category in a given context.

    Args:
        tool_category: Tool category (exchange, analysis, risk, etc.)
        context: Trading context (paper_trading, live_trading, backtesting, etc.)

    Returns:
        Dict of resource limits.
    """
    base = {**DEFAULT_LIMITS}
    profile = TOOL_PROFILES.get(tool_category, {})
    base.update(profile)

    # Apply context multipliers
    multipliers = CONTEXT_MULTIPLIERS.get(context, {})
    for key, multiplier in multipliers.items():
        if key in base:
            base[key] = type(base[key])(base[key] * multiplier)

    return base
