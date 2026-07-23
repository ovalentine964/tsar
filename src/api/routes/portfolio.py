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

from fastapi import APIRouter

router = APIRouter()


@router.get("/positions")
async def get_positions():
    """Get current open positions."""
    return {"positions": []}


@router.get("/pnl")
async def get_pnl():
    """Get P&L summary."""
    return {
        "total_pnl": 0.0,
        "daily_pnl": 0.0,
        "win_rate": 0.0,
        "total_trades": 0,
    }


@router.get("/risk")
async def get_risk():
    """Get current risk state."""
    return {
        "drawdown_pct": 0.0,
        "level": "GREEN",
        "kill_switch_active": False,
        "open_positions": 0,
    }


@router.get("/improvement")
async def get_improvement():
    """Get improvement metrics."""
    return {"metrics": {}}


@router.get("/flywheel")
async def get_flywheel():
    """Get flywheel health score."""
    from src.metrics.flywheel import FlywheelHealth
    fh = FlywheelHealth()
    return fh.compute({})


@router.get("/regime")
async def get_regime():
    """Get current market regime."""
    return {"regime": "unknown", "confidence": 0.0}


@router.get("/backends")
async def get_backends():
    """Get backend registry status."""
    from src.interfaces import get_backend_registry
    return get_backend_registry().get_backend_status()
