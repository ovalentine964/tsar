"""
Trading endpoints — Trade execution, history, and control.

GET  /api/v1/trades      — Trade history
GET  /api/v1/strategies  — Strategy performance
POST /api/v1/kill-switch — Emergency halt (TRADE_ADMIN)
POST /api/v1/resume      — Resume trading (TRADE_ADMIN)
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/trades")
async def get_trades(limit: int = 100, symbol: str | None = None):
    """Get trade history from TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory
    import os

    db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
    trade_mem = TradeMemory(db_path)
    trades = trade_mem.list_trades(symbol=symbol, limit=limit)
    return {
        "trades": [t.to_dict() for t in trades],
        "total": trade_mem.get_trade_count(),
    }


@router.get("/strategies")
async def get_strategies():
    """Get strategy performance from TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory
    import os

    db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
    trade_mem = TradeMemory(db_path)
    summaries = trade_mem.get_strategy_summary()
    return {"strategies": summaries}


@router.post("/kill-switch")
async def activate_kill_switch(reason: str = "manual"):
    """Emergency halt — stop all trading immediately."""
    from src.risk.kill_switch import KillSwitch
    ks = KillSwitch()
    await ks.activate(reason)
    return {"status": "activated", "reason": reason}


@router.post("/resume")
async def resume_trading():
    """Resume trading after kill switch."""
    from src.risk.kill_switch import KillSwitch
    ks = KillSwitch()
    await ks.deactivate()
    return {"status": "resumed"}
