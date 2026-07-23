# FIX F — Day1 Dependency Cleanup

**Author:** Dependency Specialist
**Date:** 2026-07-24
**Status:** READY FOR REVIEW
**Triggered by:** Chief Engineer Review — Condition 5

---

## Problem Summary

The original `requirements.txt` and `TECH_STACK.md` list 30+ Python packages for Day1. The Chief Engineer flagged:
- TA-Lib vs pandas-ta duplication (TA-Lib is a build-breaker)
- Celery is overkill for Day1
- litellm is a heavy meta-package (per FIX_01)
- chromadb is premature for Day1
- vectorbt belongs at Day30+
- sqlmodel version conflict with Pydantic v2

**Target:** ≤20 packages, each justified, zero build friction.

---

## Decision Log

### 1. TA-Lib vs pandas-ta → **pandas-ta WINS**

| Factor | TA-Lib | pandas-ta |
|--------|--------|-----------|
| Install | Requires `libta-lib0-dev` system package | `pip install pandas-ta` — done |
| Windows | Painful (pre-built wheels exist but fragile) | Works everywhere |
| Speed | Faster (C library) | Fast enough for 5-min scan cycles |
| Indicators | 200+ | 130+ (covers all Day1 needs: RSI, SMA, EMA, Bollinger, MACD) |
| Maintenance | C library + Python wrapper = 2 layers | Pure Python, one layer |

**Decision:** Use `pandas-ta` for Day1. TA-Lib can be added at Day30+ if measured performance warrants it.

### 2. Celery → **REMOVED**

Day1 uses a simple `while True` + `time.sleep()` loop (see `DAY1_ARCHITECTURE.md` orchestrator). APScheduler was in the original Day1 requirements but even that is unnecessary — the orchestrator loop handles scheduling. Celery requires a Redis broker, worker processes, and monitoring. None of that exists in Day1.

**Decision:** Remove Celery. Use the existing orchestrator loop. Add APScheduler at Day30 if cron-like scheduling is needed.

### 3. litellm → **REMOVED**

Per FIX_01, litellm is a meta-package that pulls in dependencies for every LLM provider (OpenAI, Anthropic, Cohere, etc.). Day1 only needs two LLM calls:
- Ollama (local) → `ollama` package
- DeepSeek-R1 via NVIDIA NIM → `openai` package (NIM is OpenAI-compatible)

**Decision:** Use `ollama` + `openai` directly. Build a simple router (~100 lines) in `src/llm/router.py`.

### 4. chromadb → **REMOVED**

Day1 has no vector search requirements. The pattern-matching feature that needs embeddings is a Level 3 concern. SQLite FTS5 handles any text search needs for Day1.

**Decision:** Remove chromadb. Add at Level 3 when pattern similarity search is implemented.

### 5. vectorbt → **REMOVED**

Day1 uses paper trading as its "backtest." vectorbt's heavy dependency tree (numba, plotly) adds 3-5 seconds to import time and significant Docker image size. Not needed until Day30.

**Decision:** Remove vectorbt. Add at Day30 for standalone backtesting.

### 6. sqlmodel version → **PIN >=0.0.18**

`sqlmodel==0.0.16` requires Pydantic v1. Day1 uses `pydantic>=2.6`. This is a hard conflict.

**Decision:** Pin `sqlmodel>=0.0.18` which supports Pydantic v2.

### 7. redis → **REMOVED from Day1**

Day1 has no caching layer, no pub/sub, no task queue. SQLite handles all state. Redis is a Day30+ dependency.

**Decision:** Remove redis. Add at Day30 for caching.

### 8. prometheus-client → **REMOVED from Day1**

Day1 logging goes to file + Telegram. Prometheus metrics are a Day30+ concern.

**Decision:** Remove prometheus-client. Add at Day30.

### 9. arq → **REMOVED**

Redundant with Celery (which is already removed). No async task queue needed for Day1.

---

## Final Day1 requirements.txt (19 packages)

```txt
# ============================================================
# TSAR Day1 — requirements.txt
# ============================================================
# 19 packages. Each one earns its place.
# Python 3.12+ required.
# Install: pip install -r requirements.txt

# --- Exchange Connectivity ---
ccxt==4.4.50                    # Unified exchange API (Binance testnet)
                                # Justification: ONLY way to talk to exchanges.
                                # Battle-tested, covers 100+ exchanges.

# --- Data & Computation ---
pandas==2.2.3                   # DataFrame for OHLCV data, indicators
                                # Justification: Core data structure for all agents.
                                # RSI, S/R detection, price analysis all use DataFrames.

numpy==2.2.1                    # Numerical computation (pandas dependency + math)
                                # Justification: Required by pandas. Used for
                                # position sizing calculations.

pandas-ta==0.3.14b1             # Technical indicators (RSI, SMA, EMA, MACD, Bollinger)
                                # Justification: Day1 strategy needs RSI(14) + S/R.
                                # Pure Python — no system deps. TA-Lib deferred.

# --- LLM Integration ---
ollama==0.4.7                   # Local LLM client (Qwen2.5-7B via Ollama)
                                # Justification: Signal scoring, trade analysis,
                                # lesson generation. Talks to local Ollama instance.

openai==1.61.0                  # DeepSeek-R1 via NVIDIA NIM (OpenAI-compatible API)
                                # Justification: Complex reasoning for ambiguous signals.
                                # NIM endpoint uses OpenAI API format.

# --- Database ---
sqlalchemy==2.0.36              # Database ORM (SQLite)
                                # Justification: All DB operations go through SQLAlchemy.
                                # Abstraction layer for future PostgreSQL migration.

sqlmodel==0.0.22                # Pydantic v2 + SQLAlchemy integration
                                # Justification: Type-safe DB models with validation.
                                # PINNED >=0.0.18 for Pydantic v2 compatibility.

# --- Scheduling ---
apscheduler==3.10.4             # Job scheduling (scan cycles, daily reports)
                                # Justification: Replaces Celery. Handles timed tasks
                                # like "scan every 5 min" and "daily report at midnight".
                                # NOTE: Orchestrator loop may make this unnecessary.
                                # Include if cron-like scheduling is needed for
                                # daily reports; remove if orchestrator handles all timing.

# --- Telegram ---
python-telegram-bot==21.10      # Telegram bot (alerts + commands)
                                # Justification: User interface. /status, /stop, /start,
                                # trade notifications. No alternative for Telegram.

# --- Configuration ---
python-dotenv==1.1.0            # .env file loading
                                # Justification: Load API keys from .env. Standard practice.

pyyaml==6.0.2                   # YAML config parsing
                                # Justification: config/settings.yaml, exchanges.yaml,
                                # risk.yaml all use YAML format.

# --- HTTP Client ---
httpx==0.28.1                   # Async HTTP client
                                # Justification: NVIDIA NIM calls (if not using openai
                                # package), health checks, webhook testing.
                                # Also used by python-telegram-bot internally.

# --- Utilities ---
rich==13.9.4                    # Rich terminal output (logging, tables, progress)
                                # Justification: CLI output for development. Structured
                                # logging with colors. Debug tool — can remove for prod.

tenacity==8.5.0                 # Retry logic with backoff
                                # Justification: Exchange API calls fail. LLM calls timeout.
                                # Retries with exponential backoff prevent cascading failures.

orjson==3.10.13                 # Fast JSON serialization
                                # Justification: Trade data, API responses, DB cache.
                                # 10x faster than stdlib json. Used for all JSON ops.

structlog==24.4.0               # Structured logging
                                # Justification: JSON-formatted logs for debugging.
                                # Context binding (trade_id, symbol) for log correlation.

# --- Testing (dev only) ---
pytest==8.3.4                   # Test framework
                                # Justification: Unit tests for tools, agents, risk checks.
                                # Move to [dev] extras if using pyproject.toml.
```

### Package Count: 19 ✅ (target: ≤20)

---

## System-Level Dependencies

### apt packages (for Dockerfile)

```bash
# Required for Day1
build-essential    # C compiler (needed by some Python packages during install)
curl               # Health checks, debugging
ca-certificates    # HTTPS connections (exchange APIs, Telegram, NIM)
git                # Version control (if building from source)
```

### NOT needed for Day1

```bash
# libta-lib0-dev   # TA-Lib C library — NOT NEEDED (using pandas-ta)
# redis-server     # NOT NEEDED (no Redis in Day1)
# postgresql       # NOT NEEDED (SQLite in Day1)
# cmake            # NOT NEEDED (no native builds in Day1)
# pkg-config       # NOT NEEDED
```

---

## Day1 Dockerfile

No Rust. No TA-Lib. No Redis. Simple.

```dockerfile
# ============================================================
# TSAR Day1 — Dockerfile
# ============================================================
# Simple Python container. No Rust. No TA-Lib. No Redis.
# Build: docker build -t tsar-day1 .
# Run:   docker run --env-file .env -v $(pwd)/data:/app/data tsar-day1

FROM python:3.12-slim

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r tsar && useradd -r -g tsar -d /app tsar

WORKDIR /app

# Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY config/ ./config/
COPY agents/ ./agents/
COPY tools/ ./tools/
COPY strategies/ ./strategies/
COPY core/ ./core/
COPY notifications/ ./notifications/
COPY main.py .

# Data directories (mounted as volumes in production)
RUN mkdir -p data logs && chown -R tsar:tsar /app

USER tsar

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default: run the trading agent
CMD ["python", "main.py"]
```

### Docker Build Notes

- **No Rust compilation.** The `rust/` directory is not copied. Day1 is pure Python.
- **No TA-Lib.** No `libta-lib0-dev` in the image. pandas-ta is pure Python.
- **No Redis.** Single container, SQLite on a mounted volume.
- **No multi-stage build.** Not needed — the image is ~400MB (Python 3.12-slim + deps).
- **Non-root user.** Security best practice. The `tsar` user owns the data directory.

---

## What Was Removed and Why

| Package | Original Justification | Why Removed | When to Add Back |
|---------|----------------------|-------------|-----------------|
| `TA-Lib` | C-based indicators (faster) | System C lib build-breaker. pandas-ta covers Day1 needs. | Day30 — if measured bottleneck on indicator calc |
| `vectorbt` | Backtesting engine | Heavy deps (numba, plotly). Paper trading IS Day1 backtest. | Day30 — standalone backtesting phase |
| `litellm` | LLM router abstraction | Meta-package pulling all providers. FIX_01 replaces with direct calls. | Never — use direct provider packages |
| `celery[redis]` | Background task queue | Overkill. Orchestrator loop handles scheduling. | Level 2 — when multi-process tasks needed |
| `chromadb` | Vector database | No vector search in Day1. SQLite FTS5 sufficient. | Level 3 — pattern similarity search |
| `redis` | Caching / pub/sub | No caching in Day1. SQLite is the single state store. | Day30 — caching + pub/sub |
| `arq` | Async task queue | Redundant with Celery (which is also removed). | Never — use Celery at Level 2 if needed |
| `prometheus-client` | Metrics export | Logging to file + Telegram is sufficient. | Day30 — when Grafana dashboards added |
| `python-json-logger` | JSON log formatting | structlog handles JSON output natively. | Never — structlog covers this |
| `websockets` | WebSocket client | ccxt handles exchange WS internally if needed. REST polling for Day1. | Level 2 — when persistent WS needed |
| `tiktoken` | Token counting | Free-tier models = no budget tracking needed. | Level 2 — when cost tracking added |
| `cachetools` | In-memory caching | No caching layer in Day1. | Day30 — when caching added |
| `aiofiles` | Async file I/O | Day1 is synchronous. No async file ops needed. | Level 2 — when async architecture adopted |
| `uvicorn` | ASGI server | Day1 has no API server. Telegram is the interface. | Day30 — when REST API added |
| `fastapi` | REST API framework | No HTTP API in Day1. Telegram + CLI only. | Day30 — when API endpoints needed |
| `python-jose` | JWT authentication | No API = no auth tokens. | Day30 — when API with auth added |
| `typer` | CLI framework | Day1 uses `python main.py`. No complex CLI. | Day30 — when CLI tools added |
| `pydantic-settings` | Settings management | python-dotenv + dict config is sufficient. | Day30 — when complex config validation needed |

---

## Dependency Tree Visualization

```
tsar-day1 (19 packages)
│
├── ccxt 4.4.50
│   ├── requests
│   ├── cryptography
│   └── ... (transitive, ~15 deps)
│
├── pandas 2.2.3
│   └── numpy 2.2.1
│
├── pandas-ta 0.3.14b1
│   └── numpy (shared)
│
├── ollama 0.4.7
│   └── httpx (shared)
│
├── openai 1.61.0
│   ├── httpx (shared)
│   └── pydantic (shared)
│
├── sqlalchemy 2.0.36
│
├── sqlmodel 0.0.22
│   ├── sqlalchemy (shared)
│   └── pydantic 2.x (shared)
│
├── apscheduler 3.10.4
│   └── pytz
│
├── python-telegram-bot 21.10
│   ├── httpx (shared)
│   └── pydantic (shared)
│
├── python-dotenv 1.1.0
├── pyyaml 6.0.2
├── httpx 0.28.1
├── rich 13.9.4
├── tenacity 8.5.0
├── orjson 3.10.13
├── structlog 24.4.0
└── pytest 8.3.4 (dev)

Estimated total (with transitive): ~60-70 packages
Image size: ~400MB (python:3.12-slim base)
```

---

## Validation Checklist

- [x] ≤20 packages in requirements.txt (19 total)
- [x] Each package has explicit justification
- [x] No TA-Lib (pure Python with pandas-ta)
- [x] No Celery (orchestrator loop)
- [x] No litellm (direct ollama + openai)
- [x] No chromadb (Level 3)
- [x] No vectorbt (Day30)
- [x] sqlmodel >=0.0.18 (Pydantic v2 compat)
- [x] No Rust in Dockerfile
- [x] No system C libraries beyond build-essential
- [x] Non-root Docker user
- [x] All removed packages mapped to re-add timeline

---

## Migration Path

### Day30 additions (when ready)
```
+ redis>=5.0          # Caching + pub/sub
+ vectorbt>=0.26      # Backtesting
+ uvicorn[standard]   # REST API
+ fastapi             # REST API
+ prometheus-client   # Metrics
+ pydantic-settings   # Config validation
```

### Level 2 additions
```
+ celery[redis]       # Task queue (if multi-process needed)
+ tiktoken            # Token counting for cost tracking
+ websockets          # Persistent WS connections
```

### Level 3 additions
```
+ chromadb            # Vector search for pattern matching
+ TA-Lib              # If pandas-ta is too slow (measure first)
```

---

*Ship these 19 packages. Build Day1. Measure. Then add what's actually needed.*
