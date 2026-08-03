"""
Health endpoints — System health and readiness checks.

These are supplementary health endpoints. The primary /health endpoint
is defined in app.py with full tool integration.
"""

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

router = APIRouter()
_security = HTTPBearer(auto_error=False)


def _require_api_key_for_detailed(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> str:
    """Enforce API key on /health/detailed to prevent info disclosure."""
    expected = os.environ.get("TSAR_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="API key not configured.")
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Use: Bearer <TSAR_API_KEY>",
        )
    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return credentials.credentials


@router.get("/health/detailed")
async def detailed_health(api_key: str = Depends(_require_api_key_for_detailed)):
    """Detailed health check with component status (auth required)."""
    components = {}

    # Check TradeMemory
    try:
        from src.knowledge.trade_memory import TradeMemory
        db = TradeMemory(os.environ.get("TSAR_DB_PATH", "data/tsar.db"))
        count = db.get_trade_count()
        components["trade_memory"] = {"status": "healthy", "trade_count": count}
    except Exception as e:
        components["trade_memory"] = {"status": "unavailable", "error": str(e)}

    # Check KillSwitch
    try:
        from src.risk.kill_switch import KillSwitch
        ks = KillSwitch()
        active = await ks.is_active()
        components["kill_switch"] = {"status": "active" if active else "inactive"}
    except Exception as e:
        components["kill_switch"] = {"status": "unknown", "error": str(e)}

    return {
        "status": "ok",
        "version": "0.5.0",
        "components": components,
    }
