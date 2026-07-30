"""
Trading endpoints — Extended trade analytics.

These supplement the main /api/v1/trades endpoint in app.py
with additional analytics wired to the tools.
"""

import os

from fastapi import APIRouter

router = APIRouter()


def _db_path() -> str:
    return os.environ.get("TSAR_DB_PATH", "data/tsar.db")


@router.get("/trades/by-strategy")
async def get_trades_by_strategy(strategy_id: str = "", limit: int = 50):
    """Get trades filtered by strategy from TradeMemory tool."""
    from src.knowledge.trade_memory import TradeMemory

    db = TradeMemory(_db_path())
    trades = db.list_trades(limit=limit)
    if strategy_id:
        trades = [t for t in trades if hasattr(t, "strategy_id") and t.strategy_id == strategy_id]
    return {
        "trades": [t.to_dict() if hasattr(t, "to_dict") else t for t in trades],
        "strategy_id": strategy_id,
        "count": len(trades),
    }


@router.get("/trades/by-symbol")
async def get_trades_by_symbol(symbol: str = "", limit: int = 50):
    """Get trades filtered by symbol from TradeMemory tool."""
    from src.knowledge.trade_memory import TradeMemory

    db = TradeMemory(_db_path())
    trades = db.list_trades(symbol=symbol, limit=limit)
    return {
        "trades": [t.to_dict() if hasattr(t, "to_dict") else t for t in trades],
        "symbol": symbol,
        "count": len(trades),
    }


@router.get("/trades/performance")
async def get_trade_performance():
    """Get strategy performance summary from TradeMemory tool."""
    from src.knowledge.trade_memory import TradeMemory

    db = TradeMemory(_db_path())
    stats = db.get_trade_stats()
    summaries = db.get_strategy_summary()
    regime_perf = db.get_performance_by_regime()
    return {
        "overall": stats,
        "by_strategy": summaries,
        "by_regime": regime_perf,
    }
