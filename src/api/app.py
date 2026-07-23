"""
FastAPI application factory.

Creates and configures the FastAPI app with all routes, middleware,
and lifecycle events. Security-hardened per CP1 Security Chief review.
"""

import logging
import os
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import health, trading, portfolio

logger = logging.getLogger(__name__)


def _get_api_key() -> str:
    """Get API key from environment. Raises error if not set."""
    key = os.environ.get("TSAR_API_KEY", "")
    if not key:
        raise ValueError(
            "TSAR_API_KEY environment variable is required. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    return key


def _get_cors_origins() -> list[str]:
    """Get CORS origins from environment."""
    origins_str = os.environ.get("TSAR_CORS_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in origins_str.split(",") if o.strip()]


def _get_api_host() -> str:
    """Get API bind host from environment. Defaults to localhost only."""
    return os.environ.get("TSAR_API_HOST", "127.0.0.1")


async def _api_key_middleware(request: Request, call_next: Any) -> Response:
    """Require X-API-Key header on all non-health endpoints."""
    # Health endpoints are exempt (for monitoring/load balancers)
    if request.url.path in ("/health", "/health/ready", "/health/detailed"):
        return await call_next(request)

    # Docs endpoints are exempt in dev
    if request.url.path in ("/docs", "/redoc", "/openapi.json"):
        if os.environ.get("TSAR_ENV", "development") == "development":
            return await call_next(request)

    api_key = request.headers.get("X-API-Key", "")
    expected_key = os.environ.get("TSAR_API_KEY", "")

    if not expected_key:
        logger.error("TSAR_API_KEY not configured — rejecting all requests")
        return JSONResponse(
            status_code=503,
            content={"detail": "API key not configured on server"},
        )

    if api_key != expected_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing X-API-Key header"},
        )

    return await call_next(request)


def create_app(config: dict[str, Any] | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Application configuration dict

    Returns:
        Configured FastAPI instance.
    """
    config = config or {}
    api_config = config.get("api", {})

    app = FastAPI(
        title="TSAR — Trading Super Agent Regime",
        description="Self-improving autonomous trading system API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware — configurable origins, NOT wildcard
    cors_origins = api_config.get("cors_origins", _get_cors_origins())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )

    # API key authentication middleware
    app.middleware("http")(_api_key_middleware)

    # Include routers
    app.include_router(health.router, tags=["health"])
    app.include_router(trading.router, prefix="/api/v1", tags=["trading"])
    app.include_router(portfolio.router, prefix="/api/v1", tags=["portfolio"])

    @app.on_event("startup")
    async def startup():
        host = api_config.get("host", _get_api_host())
        logger.info(f"TSAR API starting up on {host}")
        # Validate API key is set
        try:
            _get_api_key()
        except ValueError as e:
            logger.warning(f"Security warning: {e}")

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("TSAR API shutting down")

    return app


def run_server(config: dict[str, Any] | None = None) -> None:
    """Run the API server. Host defaults to 127.0.0.1 (localhost only)."""
    import uvicorn

    config = config or {}
    api_config = config.get("api", {})
    host = api_config.get("host", _get_api_host())
    port = api_config.get("port", int(os.environ.get("TSAR_API_PORT", "8000")))

    app = create_app(config)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
