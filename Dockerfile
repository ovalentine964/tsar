# ============================================================
# TSAR — Dockerfile (Multi-stage Production Build)
# ============================================================
# Optimized for Azure Free Tier (1 vCPU, 1 GB RAM)
#
# Features:
#   - Multi-stage build (builder → production) for minimal image size
#   - Non-root user (tsar:1000) for security
#   - tini as PID 1 for proper signal forwarding & zombie reaping
#   - Health check via /health endpoint
#   - Graceful shutdown (SIGTERM → SIGKILL after 30s)
#   - All secrets via environment variables (never baked in)
#   - Memory-optimized for constrained environments
#
# Build:
#   docker build -t tsar:latest .
#   docker build --build-arg TSAR_RUST_BUILD=1 -t tsar:latest .  # with Rust
#
# Run:
#   docker run --env-file .env -p 8000:8000 tsar:latest
# ============================================================

# ── Stage 1: Rust Builder (optional) ────────────────────────
ARG TSAR_RUST_BUILD=0
FROM rust:1.79-slim AS rust-builder
ARG TSAR_RUST_BUILD
WORKDIR /build/rust
COPY rust/ ./
RUN if [ "$TSAR_RUST_BUILD" = "1" ]; then \
        echo "🦀 Building Rust crates..." && \
        cargo build --release && \
        echo "✅ Rust build succeeded"; \
    else \
        echo "⏭️  TSAR_RUST_BUILD=0 — Rust build explicitly skipped"; \
    fi

# ── Stage 2: Python Builder ─────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (cached layer — only rebuilds on pyproject.toml change)
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# Copy Rust release artifacts if available
COPY --from=rust-builder /build/rust/target/release/ /build/rust-binaries/ 2>/dev/null || true

# ── Stage 3: Production ─────────────────────────────────────
FROM python:3.12-slim AS production

LABEL maintainer="TSAR Team"
LABEL description="TSAR — Trading Super Agent Regime"
LABEL version="0.3.0"
LABEL org.opencontainers.image.source="https://github.com/tsar/trading-system"

# Runtime system dependencies — minimal footprint
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tini \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd --gid 1000 tsar && \
    useradd --uid 1000 --gid tsar --shell /bin/bash --create-home tsar

WORKDIR /app

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY migrations/ ./migrations/

# Create data and log directories with correct ownership
RUN mkdir -p /app/data /app/logs /app/data/backups && \
    chown -R tsar:tsar /app

# Switch to non-root user
USER tsar

# Expose API port
EXPOSE 8000

# ── Environment defaults ─────────────────────────────────────
# All secrets (TSAR_API_KEY, REDIS_PASSWORD, etc.) MUST be
# injected at runtime via --env-file or orchestrator secrets.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TSAR_ENVIRONMENT=production \
    TSAR_TRADING_MODE=paper \
    TSAR_API_PORT=8000 \
    # Memory optimization for Azure free tier
    MALLOC_ARENA_MAX=2 \
    PYTHONMALLOC=malloc \
    # Reduce Python startup overhead
    PYTHONDONTWRITEBYTECODE=1

# Health check — hits the FastAPI /health endpoint
# Azure ACI also supports HTTP probes in YAML; this is the Docker-native fallback
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:${TSAR_API_PORT:-8000}/health || exit 1

# Graceful shutdown:
#   - STOPSIGNAL tells Docker/ACI to send SIGTERM first
#   - tini (PID 1) forwards SIGTERM to the Python process
#   - Python receives SIGTERM → triggers asyncio shutdown handlers
#   - 30s grace period before SIGKILL (Docker default)
STOPSIGNAL SIGTERM

# Use tini as PID 1 for proper signal handling and zombie reaping
ENTRYPOINT ["tini", "--"]

# Default command: run the trading system
CMD ["python", "-m", "src"]
