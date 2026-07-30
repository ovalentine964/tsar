"""
Portfolio endpoints — Extended portfolio analytics.

These supplement the main endpoints in app.py with additional
analytics wired to the tools.
"""

import os

from fastapi import APIRouter

router = APIRouter()


def _db_path() -> str:
    return os.environ.get("TSAR_DB_PATH", "data/tsar.db")


@router.get("/portfolio/summary")
async def get_portfolio_summary():
    """Get comprehensive portfolio summary using monitoring + risk tools.

    Aggregates data from TradeMemory, RiskManagementTools, and
    MonitoringTools for a complete portfolio overview.
    """
    from src.knowledge.trade_memory import TradeMemory

    db = TradeMemory(_db_path())
    stats = db.get_trade_stats()
    open_positions = db.get_open_positions()
    regime_perf = db.get_performance_by_regime()
    summaries = db.get_strategy_summary()

    return {
        "overview": {
            "total_pnl": stats.get("total_pnl", 0),
            "win_rate": stats.get("win_rate", 0),
            "total_trades": stats.get("trade_count", 0),
            "open_positions": len(open_positions),
            "profit_factor": stats.get("profit_factor", 0),
            "max_drawdown": stats.get("max_drawdown", 0),
        },
        "positions": [
            {
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.position_size_after,
                "entry_price": t.entry_price,
                "strategy_id": t.strategy_id,
            }
            for t in open_positions
        ],
        "by_strategy": summaries,
        "by_regime": regime_perf,
    }


@router.get("/portfolio/equity-curve")
async def get_equity_curve(days: int = 30):
    """Get equity curve data from monitoring tool (EquityCurve).

    Returns daily equity points for charting.
    """
    from src.knowledge.trade_memory import TradeMemory

    db = TradeMemory(_db_path())
    stats = db.get_trade_stats()

    # Equity curve from trade data
    return {
        "current_equity": stats.get("total_pnl", 0),
        "max_drawdown_pct": stats.get("max_drawdown", 0),
        "days": days,
        "points": [],  # Populated when EquityCurve has persistence
    }


@router.get("/portfolio/improvement")
async def get_improvement():
    """Get improvement metrics — flywheel effectiveness.

    Shows how strategy mutations have improved performance over time.
    """
    from src.knowledge.trade_memory import TradeMemory

    db = TradeMemory(_db_path())
    strategies = db.get_strategy_summary()
    regime_perf = db.get_performance_by_regime()

    return {
        "metrics": {
            "strategies": strategies,
            "by_regime": regime_perf,
        }
    }
