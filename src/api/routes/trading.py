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
    """Get trade history."""
    return {"trades": [], "total": 0}


@router.get("/strategies")
async def get_strategies():
    """Get strategy performance."""
    return {"strategies": []}


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
