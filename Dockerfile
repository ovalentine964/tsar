# ============================================================
# TSAR — Dockerfile (Multi-stage build)
# ============================================================
# Stage 1: Build dependencies
# Stage 2: Lean production image

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

WORKDIR /build

# System dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# --- Stage 2: Production ---
FROM python:3.12-slim AS production

LABEL maintainer="TSAR Team"
LABEL description="TSAR — Trading Super Agent Regime"
LABEL version="0.5.0"

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd --gid 1000 tsar && \
    useradd --uid 1000 --gid tsar --shell /bin/bash --create-home tsar

WORKDIR /app

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create data and log directories with correct ownership
RUN mkdir -p /app/data /app/logs && \
    chown -R tsar:tsar /app

# Switch to non-root user
USER tsar

# Expose API port
EXPOSE 8000

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TSAR_ENVIRONMENT=production \
    TSAR_TRADING_MODE=paper

# Health check — hits the FastAPI /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use tini as PID 1 for proper signal handling
ENTRYPOINT ["tini", "--"]

# Default command: run the trading system
CMD ["python", "-m", "src"]
