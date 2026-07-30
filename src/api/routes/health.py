"""
Health endpoints — System health and readiness checks.

These are supplementary health endpoints. The primary /health endpoint
is defined in app.py with full tool integration.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health/detailed")
async def detailed_health():
    """Detailed health check with component status."""
    components = {}

    # Check TradeMemory
    try:
        from src.knowledge.trade_memory import TradeMemory
        import os
        db = TradeMemory(os.environ.get("TSAR_DB_PATH", "data/tsar.db"))
        count = db.get_trade_count()
        components["trade_memory"] = {"status": "healthy", "trade_count": count}
    except Exception as e:
        components["trade_memory"] = {"status": "unavailable", "error": str(e)}

    # Check KillSwitch
    try:
        from src.risk.kill_switch import KillSwitch
        import asyncio
        ks = KillSwitch()
        active = asyncio.get_event_loop().run_until_complete(ks.is_active())
        components["kill_switch"] = {"status": "active" if active else "inactive"}
    except Exception as e:
        components["kill_switch"] = {"status": "unknown", "error": str(e)}

    return {
        "status": "ok",
        "version": "0.5.0",
        "components": components,
    }
