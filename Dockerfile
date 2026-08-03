# TSAR — Production Dockerfile (Render/Railway compatible)
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl tini ca-certificates && rm -rf /var/lib/apt/lists/* && apt-get clean

COPY --from=builder /install /usr/local

RUN groupadd --gid 1000 tsar && \
    useradd --uid 1000 --gid tsar --shell /bin/bash --create-home tsar

WORKDIR /app
COPY src/ ./src/
COPY config/ ./config/

RUN mkdir -p /app/data /app/logs && chown -R tsar:tsar /app
USER tsar

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TSAR_ENVIRONMENT=production \
    TSAR_TRADING_MODE=paper \
    TSAR_API_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

STOPSIGNAL SIGTERM
ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "src", "--api-only"]
