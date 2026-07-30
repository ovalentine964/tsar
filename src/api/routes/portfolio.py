"""
Portfolio endpoints — Positions, P&L, risk state, and improvement metrics.

GET /api/v1/positions    — Current positions
GET /api/v1/pnl          — P&L summary
GET /api/v1/risk         — Risk state
GET /api/v1/improvement  — Improvement metrics
GET /api/v1/flywheel     — Flywheel health score
GET /api/v1/regime       — Current market regime
GET /api/v1/backends     — Backend registry status
"""

import os

from fastapi import APIRouter

router = APIRouter()


@router.get("/positions")
async def get_positions():
    """Get current open positions from TradeMemory and exchange gateway."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
    trade_mem = TradeMemory(db_path)
    open_trades = trade_mem.get_open_positions()

    return {
        "positions": [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.position_size_after,
                "entry_price": t.entry_price,
                "status": t.status,
                "strategy_id": t.strategy_id,
                "created_at": t.created_at,
            }
            for t in open_trades
        ]
    }


@router.get("/pnl")
async def get_pnl():
    """Get P&L summary from TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
    trade_mem = TradeMemory(db_path)
    stats = trade_mem.get_trade_stats()

    return {
        "total_pnl": stats["total_pnl"],
        "win_rate": stats["win_rate"],
        "avg_win": stats["avg_win"],
        "avg_loss": stats["avg_loss"],
        "profit_factor": stats["profit_factor"],
        "max_drawdown": stats["max_drawdown"],
        "total_trades": stats["trade_count"],
    }


@router.get("/risk")
async def get_risk():
    """Get current risk state from RiskEngine and KillSwitch."""
    from src.risk.kill_switch import KillSwitch
    from src.knowledge.trade_memory import TradeMemory

    db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
    trade_mem = TradeMemory(db_path)
    open_positions = trade_mem.get_open_positions()
    stats = trade_mem.get_trade_stats()

    ks = KillSwitch()
    ks_active = await ks.is_active()

    # Compute drawdown from stats
    max_dd = stats.get("max_drawdown", 0.0)

    # Determine risk level based on drawdown
    if max_dd >= 5.0:
        level = "RED"
    elif max_dd >= 3.0:
        level = "ORANGE"
    elif max_dd >= 2.0:
        level = "YELLOW"
    else:
        level = "GREEN"

    return {
        "drawdown_pct": max_dd,
        "level": level,
        "kill_switch_active": ks_active,
        "open_positions": len(open_positions),
    }


@router.get("/improvement")
async def get_improvement():
    """Get improvement metrics from TradeMemory strategy summaries."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
    trade_mem = TradeMemory(db_path)
    strategies = trade_mem.get_strategy_summary()
    regime_perf = trade_mem.get_performance_by_regime()

    return {
        "metrics": {
            "strategies": strategies,
            "by_regime": regime_perf,
        }
    }


@router.get("/flywheel")
async def get_flywheel():
    """Get flywheel health score."""
    from src.metrics.flywheel import FlywheelHealth
    fh = FlywheelHealth()
    return fh.compute({})


@router.get("/regime")
async def get_regime():
    """Get current market regime from TradeMemory performance data."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
    trade_mem = TradeMemory(db_path)
    regime_perf = trade_mem.get_performance_by_regime()

    # Determine dominant regime from trade data
    if regime_perf:
        best = max(regime_perf, key=lambda r: r.get("total_pnl", 0))
        return {
            "regime": best.get("regime_at_entry", "unknown"),
            "confidence": best.get("win_rate", 0.0),
            "trade_count": best.get("trade_count", 0),
        }
    return {"regime": "unknown", "confidence": 0.0, "trade_count": 0}


@router.get("/backends")
async def get_backends():
    """Get backend registry status."""
    from src.interfaces import get_backend_registry
    return get_backend_registry().get_backend_status()
