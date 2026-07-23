"""
Health endpoints — System health and readiness checks.

GET /health — No auth required. Returns system status.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """System health check."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "components": {
            "api": "healthy",
            "redis": "unknown",  # TODO: check Redis
            "exchange": "unknown",  # TODO: check exchange connection
        },
    }


@router.get("/ready")
async def readiness_check():
    """Readiness check — is the system ready to trade?"""
    return {"ready": True}
