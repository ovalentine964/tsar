# Trading Super Agent — Deployment & Runtime Architecture

**Version:** 1.0.0
**Last Updated:** 2026-07-24
**Stack:** Python 3.12 + Rust 1.79 + Redis 7 + SQLite 3

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Docker Architecture](#2-docker-architecture)
3. [CI/CD Pipeline](#3-cicd-pipeline)
4. [Telegram Bot Integration](#4-telegram-bot-integration)
5. [Monitoring & Alerting](#5-monitoring--alerting)
6. [Security](#6-security)
7. [Kill Switch](#7-kill-switch)
8. [Backup & Recovery](#8-backup--recovery)
9. [Runtime Configuration](#9-runtime-configuration)
10. [Deployment Procedures](#10-deployment-procedures)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        VPS (Production)                          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Python Agent │  │  Rust Exec    │  │  Telegram Bot │          │
│  │  Runtime      │◄─┤  Engine       │  │  Gateway      │          │
│  │  (strategy,   │  │  (order mgmt, │  │  (commands,   │          │
│  │   signals,    │  │   execution,  │  │   alerts,     │          │
│  │   risk)       │  │   position    │  │   approvals)  │          │
│  └──────┬───────┘  │   tracking)   │  └──────┬───────┘          │
│         │          └──────┬───────┘          │                   │
│         │                 │                   │                   │
│         ▼                 ▼                   ▼                   │
│  ┌─────────────────────────────────────────────────┐            │
│  │                    Redis 7                        │            │
│  │  (pub/sub, cache, session state, kill signal)     │            │
│  └────────────────────────┬────────────────────────┘            │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────┐            │
│  │                   SQLite 3                        │            │
│  │  (trades, P&L, journal, config, audit log)       │            │
│  │               /data/trading.db                    │            │
│  └──────────────────────────────────────────────────┘            │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐                              │
│  │  Prometheus   │  │  Grafana      │  (optional, staging+)      │
│  │  (metrics)    │  │  (dashboards) │                             │
│  └──────────────┘  └──────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Signal Generation:** Python agent analyzes market data → generates signals
2. **Risk Check:** Python risk module validates against limits → approves/rejects
3. **Execution:** Signal sent to Rust engine via Redis pub/sub → Rust executes order
4. **Confirmation:** Rust publishes fill to Redis → Python updates state → Telegram alert
5. **Monitoring:** All components emit Prometheus metrics → scraped by monitor

### Inter-Process Communication

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `signals:execute` | Python → Rust | Trade signals to execute |
| `exec:fills` | Rust → Python | Order fill confirmations |
| `exec:positions` | Rust → Python | Position updates |
| `risk:alerts` | Python → Telegram | Risk warnings |
| `cmd:*` | Telegram → Python | User commands |
| `kill` | Any → All | Emergency kill signal |

---

## 2. Docker Architecture

### Container Inventory

| Container | Image Base | CPU | RAM | Purpose |
|-----------|-----------|-----|-----|---------|
| `agent` | `python:3.12-slim` | 0.5-1.0 | 512MB-1GB | Strategy, risk, signals |
| `executor` | `rust:1.79-slim` | 0.25-0.5 | 256MB | Order execution engine |
| `redis` | `redis:7-alpine` | 0.1-0.25 | 128-256MB | State, pub/sub, cache |
| `bot` | `python:3.12-slim` | 0.1-0.25 | 128MB | Telegram gateway |
| `monitor` | `prom/prometheus` | 0.1 | 128MB | Metrics collection |

### Dockerfile — Python Agent

```dockerfile
# docker/Dockerfile.agent
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/agent/ ./agent/
COPY config/ ./config/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "agent.main"]
```

### Dockerfile — Rust Executor

```dockerfile
# docker/Dockerfile.executor
FROM rust:1.79-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src/ ./src/

RUN cargo build --release --bin executor

# Runtime image
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/target/release/executor /usr/local/bin/executor

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

EXPOSE 8001

CMD ["executor"]
```

### docker-compose.yml (Development)

```yaml
# docker/docker-compose.yml
version: "3.9"

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes --save 60 1
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    restart: unless-stopped

  agent:
    build:
      context: ..
      dockerfile: docker/Dockerfile.agent
    ports:
      - "8000:8000"
    volumes:
      - ../src/agent:/app/agent          # hot reload in dev
      - ../config:/app/config:ro
      - trading-data:/data
    environment:
      - REDIS_URL=redis://redis:6379
      - DATABASE_PATH=/data/trading.db
      - ENV=development
      - LOG_LEVEL=DEBUG
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  executor:
    build:
      context: ..
      dockerfile: docker/Dockerfile.executor
    ports:
      - "8001:8001"
    volumes:
      - trading-data:/data
    environment:
      - REDIS_URL=redis://redis:6379
      - DATABASE_PATH=/data/trading.db
      - ENV=development
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  bot:
    build:
      context: ..
      dockerfile: docker/Dockerfile.agent
    command: ["python", "-m", "agent.telegram_bot"]
    volumes:
      - ../src/agent:/app/agent
      - ../config:/app/config:ro
    environment:
      - REDIS_URL=redis://redis:6379
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - ENV=development
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

volumes:
  redis-data:
  trading-data:
```

### docker-compose.prod.yml (Production)

```yaml
# docker/docker-compose.prod.yml
version: "3.9"

services:
  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    command: >
      redis-server
        --appendonly yes
        --save 60 1
        --maxmemory 256mb
        --maxmemory-policy allkeys-lru
        --requirepass ${REDIS_PASSWORD}
    networks:
      - internal
    deploy:
      resources:
        limits:
          cpus: "0.25"
          memory: 256M
        reservations:
          cpus: "0.1"
          memory: 128M
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    restart: always
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  agent:
    image: ghcr.io/${GITHUB_REPO}/agent:${IMAGE_TAG:-latest}
    volumes:
      - trading-data:/data
      - ./config.prod.yaml:/app/config/config.yaml:ro
    environment:
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379
      - DATABASE_PATH=/data/trading.db
      - ENV=production
      - LOG_LEVEL=INFO
    env_file:
      - .env.production
    networks:
      - internal
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 1G
        reservations:
          cpus: "0.5"
          memory: 512M
    restart: always
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  executor:
    image: ghcr.io/${GITHUB_REPO}/executor:${IMAGE_TAG:-latest}
    volumes:
      - trading-data:/data
    environment:
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379
      - DATABASE_PATH=/data/trading.db
      - ENV=production
    env_file:
      - .env.production
    networks:
      - internal
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 256M
        reservations:
          cpus: "0.25"
          memory: 128M
    restart: always
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  bot:
    image: ghcr.io/${GITHUB_REPO}/bot:${IMAGE_TAG:-latest}
    volumes:
      - ./config.prod.yaml:/app/config/config.yaml:ro
    environment:
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379
      - ENV=production
    env_file:
      - .env.production
    networks:
      - internal
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "0.25"
          memory: 128M
    restart: always
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  monitor:
    image: prom/prometheus:v2.53.0
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./monitoring/alert_rules.yml:/etc/prometheus/alert_rules.yml:ro
      - prometheus-data:/prometheus
    ports:
      - "127.0.0.1:9090:9090"
    networks:
      - internal
    deploy:
      resources:
        limits:
          cpus: "0.1"
          memory: 128M
    restart: always

networks:
  internal:
    driver: bridge
    internal: true   # no external access except exposed ports

volumes:
  redis-data:
  trading-data:
  prometheus-data:
```

### Resource Budget (Production $20-50/month VPS)

| Component | CPU | RAM | Disk |
|-----------|-----|-----|------|
| Agent | 0.5-1.0 | 512MB-1GB | 1GB |
| Executor | 0.25-0.5 | 128-256MB | 500MB |
| Redis | 0.1-0.25 | 128-256MB | 1GB |
| Bot | 0.1 | 128MB | 200MB |
| Monitor | 0.1 | 128MB | 2GB |
| OS overhead | 0.5 | 512MB | 5GB |
| **Total** | **~2 cores** | **~2GB** | **~10GB** |

**Recommended VPS:** 2 vCPU, 2GB RAM, 40GB SSD — fits $10-15/month tier.

---

## 3. CI/CD Pipeline

### GitHub Actions Workflow

```yaml
# .github/workflows/ci.yml
name: Trading Agent CI/CD

on:
  push:
    branches: [main, develop]
    tags: ["v*"]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  # ─── Python Lint & Type Check ───
  python-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install ruff mypy
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Ruff lint
        run: ruff check src/agent/

      - name: Ruff format check
        run: ruff format --check src/agent/

      - name: Mypy type check
        run: mypy src/agent/ --strict --ignore-missing-imports

  # ─── Rust Lint & Clippy ───
  rust-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: dtolnay/rust-toolchain@stable
        with:
          components: clippy, rustfmt

      - name: Rustfmt check
        run: cargo fmt --check

      - name: Clippy
        run: cargo clippy -- -D warnings

  # ─── Python Tests ───
  python-test:
    runs-on: ubuntu-latest
    needs: python-lint
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 3
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Unit tests
        run: pytest tests/unit/ -v --tb=short --cov=agent --cov-report=xml

      - name: Integration tests
        run: pytest tests/integration/ -v --tb=short
        env:
          REDIS_URL: redis://localhost:6379

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: coverage.xml
          fail_ci_if_error: false

  # ─── Rust Tests ───
  rust-test:
    runs-on: ubuntu-latest
    needs: rust-lint
    steps:
      - uses: actions/checkout@v4

      - uses: dtolnay/rust-toolchain@stable

      - name: Cache cargo
        uses: actions/cache@v4
        with:
          path: |
            ~/.cargo/registry
            ~/.cargo/git
            target/
          key: ${{ runner.os }}-cargo-${{ hashFiles('**/Cargo.lock') }}

      - name: Unit tests
        run: cargo test --all-features

      - name: Integration tests
        run: cargo test --all-features --test '*'

  # ─── Build Docker Images ───
  build-images:
    runs-on: ubuntu-latest
    needs: [python-test, rust-test]
    if: github.event_name == 'push'
    permissions:
      contents: read
      packages: write
    strategy:
      matrix:
        component: [agent, executor, bot]
        include:
          - component: agent
            dockerfile: docker/Dockerfile.agent
          - component: executor
            dockerfile: docker/Dockerfile.executor
          - component: bot
            dockerfile: docker/Dockerfile.agent
            build-args: "APP_MODULE=agent.telegram_bot"
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Docker meta
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}/${{ matrix.component }}
          tags: |
            type=ref,event=branch
            type=sha,prefix=
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: ${{ matrix.dockerfile }}
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: ${{ matrix.build-args }}

  # ─── Deploy to Staging (push to main) ───
  deploy-staging:
    runs-on: ubuntu-latest
    needs: build-images
    if: github.ref == 'refs/heads/main'
    environment: staging
    steps:
      - uses: actions/checkout@v4

      - name: Deploy to staging
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.STAGING_HOST }}
          username: deploy
          key: ${{ secrets.STAGING_SSH_KEY }}
          script: |
            cd /opt/trading-agent
            export IMAGE_TAG=${{ github.sha }}
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d --remove-orphans
            sleep 10
            docker compose -f docker-compose.prod.yml ps
            # Verify health
            curl -sf http://localhost:8000/health || exit 1
            echo "Staging deployment successful"

  # ─── Deploy to Production (tag push) ───
  deploy-production:
    runs-on: ubuntu-latest
    needs: build-images
    if: startsWith(github.ref, 'refs/tags/v')
    environment: production
    steps:
      - uses: actions/checkout@v4

      - name: Deploy to production
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PROD_HOST }}
          username: deploy
          key: ${{ secrets.PROD_SSH_KEY }}
          script: |
            cd /opt/trading-agent
            export IMAGE_TAG=${{ github.ref_name }}
            # Backup before deploy
            ./scripts/backup.sh pre-deploy
            # Pull and deploy
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d --remove-orphans
            sleep 15
            docker compose -f docker-compose.prod.yml ps
            # Verify all services healthy
            curl -sf http://localhost:8000/health || { echo "UNHEALTHY"; exit 1; }
            echo "Production deployment of ${{ github.ref_name }} successful"
```

---

## 4. Telegram Bot Integration

### Command Interface

| Command | Description | Example |
|---------|-------------|---------|
| `/status` | Current state: positions, P&L, regime | `/status` |
| `/positions` | Open positions detail | `/positions` |
| `/pnl` | P&L summary (today/week/month) | `/pnl 7d` |
| `/analyze <symbol>` | Run analysis on symbol | `/analyze BTCUSDT` |
| `/risk` | Current risk metrics | `/risk` |
| `/kill` | Emergency: flatten all positions | `/kill` |
| `/pause` | Pause new trades (keep positions) | `/pause` |
| `/resume` | Resume trading | `/resume` |
| `/config` | Show active config | `/config` |
| `/logs <n>` | Last N log lines | `/logs 20` |
| `/help` | Command list | `/help` |

### Approval Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Agent Signal │────▶│ Bot Alert   │────▶│ User sees   │
│ generated    │     │ with details│     │ trade card  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                          ┌────────────────────┤
                          ▼                    ▼
                   [✅ Approve]         [❌ Reject]
                          │                    │
                          ▼                    ▼
                   Signal → Redis         Signal dropped
                   → Executor             Logged to journal
```

### Alert Types

| Alert | Priority | When |
|-------|----------|------|
| Trade filled | Normal | Order executed |
| Stop hit | High | Stop loss triggered |
| Daily P&L | Low | End of trading day |
| Drawdown warning | Critical | DD > 50% of limit |
| Drawdown breach | Emergency | DD at limit (auto-kill) |
| API error | High | Exchange API failure |
| Connection lost | Critical | Redis/exchange disconnect |
| Regime change | Normal | Market regime shifts |

### Telegram Bot Spec

```python
# telegram/bot_spec.py — Bot command handlers

"""
Telegram Bot Implementation Spec

The bot runs as a separate container, communicating with the agent
via Redis pub/sub. It does NOT have direct access to exchange APIs.

Architecture:
  Telegram API ←→ Bot Container ←→ Redis ←→ Agent Container

Security:
  - Only authorized chat IDs can issue commands
  - /kill requires confirmation (inline keyboard)
  - All commands logged to audit trail
"""

COMMANDS = {
    "/status": {
        "description": "Show system status",
        "response": "positions + P&L + regime + uptime",
        "auth": "read",
    },
    "/positions": {
        "description": "List open positions",
        "response": "table of symbol/size/entry/unrealized_pnl",
        "auth": "read",
    },
    "/pnl": {
        "description": "P&L summary",
        "args": ["period: 1d|7d|30d|all"],
        "response": "realized + unrealized + fees + sharpe",
        "auth": "read",
    },
    "/analyze": {
        "description": "Analyze a symbol",
        "args": ["symbol"],
        "response": "signal + confidence + reasoning",
        "auth": "read",
    },
    "/risk": {
        "description": "Risk metrics",
        "response": "drawdown %, exposure, VaR, correlation",
        "auth": "read",
    },
    "/kill": {
        "description": "EMERGENCY: Flatten all positions",
        "requires_confirmation": True,
        "response": "confirmation of flattening",
        "auth": "admin",
    },
    "/pause": {
        "description": "Pause new trades",
        "response": "confirmation, existing positions held",
        "auth": "admin",
    },
    "/resume": {
        "description": "Resume trading",
        "response": "confirmation",
        "auth": "admin",
    },
}

# Kill switch confirmation flow
KILL_CONFIRMATION = {
    "inline_keyboard": [
        [
            {"text": "⚠️ CONFIRM KILL", "callback_data": "kill_confirm"},
            {"text": "Cancel", "callback_data": "kill_cancel"},
        ]
    ]
}
```

### Bot Container Entrypoint

```python
# src/agent/telegram_bot.py
"""
Telegram bot entrypoint.

Runs as standalone container. Communicates with agent via Redis.
"""

import asyncio
import json
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ["REDIS_URL"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AUTHORIZED_CHATS = set(os.environ.get("TELEGRAM_CHAT_ID", "").split(","))


class TradingBot:
    def __init__(self):
        self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        self.pending_kill_confirm: dict[str, bool] = {}

    async def start(self):
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        # Register command handlers
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("positions", self.cmd_positions))
        app.add_handler(CommandHandler("pnl", self.cmd_pnl))
        app.add_handler(CommandHandler("analyze", self.cmd_analyze))
        app.add_handler(CommandHandler("risk", self.cmd_risk))
        app.add_handler(CommandHandler("kill", self.cmd_kill))
        app.add_handler(CommandHandler("pause", self.cmd_pause))
        app.add_handler(CommandHandler("resume", self.cmd_resume))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CallbackQueryHandler(self.handle_callback))

        # Start alert listener in background
        asyncio.create_task(self.alert_listener())

        await app.run_polling(allowed_updates=Update.ALL_TYPES)

    async def _auth(self, update: Update) -> bool:
        """Check if user is authorized."""
        chat_id = str(update.effective_chat.id)
        if chat_id not in AUTHORIZED_CHATS:
            await update.message.reply_text("⛔ Unauthorized")
            return False
        return True

    async def _redis_cmd(self, channel: str, payload: dict, timeout: float = 5.0) -> dict:
        """Send command to agent via Redis and wait for response."""
        reply_channel = f"reply:{id(payload)}"
        payload["reply_to"] = reply_channel
        await self.redis.publish(channel, json.dumps(payload))

        # Wait for response
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(reply_channel)
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    return json.loads(msg["data"])
                await asyncio.sleep(0.1)
        except asyncio.TimeoutError:
            return {"error": "Timeout waiting for response"}
        finally:
            await pubsub.unsubscribe(reply_channel)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._auth(update):
            return
        resp = await self._redis_cmd("cmd:status", {"user": update.effective_user.id})
        await update.message.reply_text(
            self._format_status(resp), parse_mode="Markdown"
        )

    async def cmd_kill(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._auth(update):
            return
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚠️ CONFIRM KILL", callback_data="kill_confirm"),
                InlineKeyboardButton("Cancel", callback_data="kill_cancel"),
            ]
        ])
        await update.message.reply_text(
            "🚨 *KILL SWITCH*\n\n"
            "This will:\n"
            "• Flatten ALL open positions\n"
            "• Cancel ALL pending orders\n"
            "• Pause all trading\n\n"
            "Are you sure?",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data == "kill_confirm":
            await query.edit_message_text("🔴 Kill switch activated. Flattening all positions...")
            # Publish kill signal to ALL channels
            await self.redis.publish("kill", json.dumps({
                "source": "telegram",
                "user": query.from_user.id,
                "timestamp": asyncio.get_event_loop().time(),
            }))
            await query.message.reply_text("✅ Kill signal sent. All positions being flattened.")

        elif query.data == "kill_cancel":
            await query.edit_message_text("❌ Kill switch cancelled.")

    async def alert_listener(self):
        """Listen for alerts from agent and forward to Telegram."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("alerts:telegram")
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                alert = json.loads(msg["data"])
                await self._send_alert(alert)

    async def _send_alert(self, alert: dict):
        """Send alert to authorized Telegram chats."""
        priority_emoji = {
            "low": "ℹ️",
            "normal": "📢",
            "high": "⚠️",
            "critical": "🚨",
            "emergency": "🔴",
        }
        emoji = priority_emoji.get(alert.get("priority", "normal"), "📢")
        text = f"{emoji} *{alert.get('title', 'Alert')}*\n\n{alert.get('message', '')}"

        for chat_id in AUTHORIZED_CHATS:
            try:
                await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")

    @staticmethod
    def _format_status(data: dict) -> str:
        if "error" in data:
            return f"❌ Error: {data['error']}"
        return (
            f"📊 *Trading Status*\n\n"
            f"Regime: `{data.get('regime', 'unknown')}`\n"
            f"Positions: `{data.get('position_count', 0)}`\n"
            f"Unrealized P&L: `${data.get('unrealized_pnl', 0):,.2f}`\n"
            f"Today P&L: `${data.get('daily_pnl', 0):,.2f}`\n"
            f"Drawdown: `{data.get('drawdown_pct', 0):.1f}%`\n"
            f"Uptime: `{data.get('uptime', 'N/A')}`"
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bot = TradingBot()
    asyncio.run(bot.start())
```

---

## 5. Monitoring & Alerting

### Health Check Endpoint

```python
# src/agent/health.py
"""
Health check endpoint for Docker HEALTHCHECK and monitoring.

GET /health → 200 OK or 503 Service Unavailable
"""

from fastapi import FastAPI, Response
import redis.asyncio as aioredis
import sqlite3
import time

app = FastAPI()

CHECKS = {}


async def check_redis(redis_url: str) -> dict:
    try:
        r = aioredis.from_url(redis_url)
        start = time.monotonic()
        await r.ping()
        latency_ms = (time.monotonic() - start) * 1000
        await r.close()
        return {"status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_sqlite(db_path: str) -> dict:
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/health")
async def health(response: Response):
    redis_check = await check_redis(REDIS_URL)
    sqlite_check = check_sqlite(DB_PATH)

    healthy = all(
        c["status"] == "ok" for c in [redis_check, sqlite_check]
    )

    if not healthy:
        response.status_code = 503

    return {
        "status": "healthy" if healthy else "unhealthy",
        "timestamp": time.time(),
        "checks": {
            "redis": redis_check,
            "sqlite": sqlite_check,
        },
    }
```

### Prometheus Metrics

```python
# src/agent/metrics.py
"""
Prometheus metrics for the trading agent.
"""

from prometheus_client import Counter, Histogram, Gauge, Info, start_http_server

# ─── Trade Metrics ───
TRADES_TOTAL = Counter(
    "trading_trades_total",
    "Total number of trades executed",
    ["symbol", "side", "status"]  # status: filled, rejected, cancelled
)

TRADE_LATENCY = Histogram(
    "trading_execution_latency_seconds",
    "Time from signal to fill",
    ["symbol"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# ─── P&L Metrics ───
PNL_REALIZED = Gauge(
    "trading_pnl_realized_dollars",
    "Realized P&L in USD",
    ["period"]  # 1d, 7d, 30d, all
)

PNL_UNREALIZED = Gauge(
    "trading_pnl_unrealized_dollars",
    "Unrealized P&L in USD"
)

# ─── Risk Metrics ───
DRAWDOWN_CURRENT = Gauge(
    "trading_drawdown_current_pct",
    "Current drawdown percentage"
)

DRAWDOWN_MAX = Gauge(
    "trading_drawdown_max_pct",
    "Maximum drawdown percentage"
)

POSITIONS_OPEN = Gauge(
    "trading_positions_open",
    "Number of open positions"
)

EXPOSURE_GROSS = Gauge(
    "trading_exposure_gross_dollars",
    "Gross exposure in USD"
)

# ─── System Metrics ───
SIGNALS_GENERATED = Counter(
    "trading_signals_generated_total",
    "Signals generated by strategy",
    ["symbol", "signal_type"]
)

SIGNALS_APPROVED = Counter(
    "trading_signals_approved_total",
    "Signals approved by risk check",
    ["symbol"]
)

SIGNALS_REJECTED = Counter(
    "trading_signals_rejected_total",
    "Signals rejected by risk check",
    ["symbol", "reason"]
)

API_ERRORS = Counter(
    "trading_api_errors_total",
    "Exchange API errors",
    ["exchange", "error_type"]
)

API_LATENCY = Histogram(
    "trading_api_latency_seconds",
    "Exchange API call latency",
    ["exchange", "endpoint"]
)

REDIS_PUBSUB_LATENCY = Histogram(
    "trading_redis_pubsub_latency_seconds",
    "Redis pub/sub message latency"
)

# ─── Kill Switch ───
KILL_EVENTS = Counter(
    "trading_kill_events_total",
    "Kill switch activations",
    ["source"]  # telegram, auto_drawdown, auto_api_error, manual
)

# ─── System Info ───
SYSTEM_INFO = Info(
    "trading_system",
    "System information"
)


def start_metrics_server(port: int = 9100):
    """Start Prometheus metrics HTTP server."""
    start_http_server(port)
```

### Prometheus Configuration

```yaml
# monitoring/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "alert_rules.yml"

scrape_configs:
  - job_name: "trading-agent"
    static_configs:
      - targets: ["agent:9100"]
    scrape_interval: 10s

  - job_name: "trading-executor"
    static_configs:
      - targets: ["executor:9101"]
    scrape_interval: 10s

  - job_name: "redis"
    static_configs:
      - targets: ["redis:6379"]
    scrape_interval: 30s

  - job_name: "node"
    static_configs:
      - targets: ["host.docker.internal:9100"]
    scrape_interval: 30s
```

### Alert Rules

```yaml
# monitoring/alert_rules.yml
groups:
  - name: trading_alerts
    rules:
      # ─── Drawdown Alerts ───
      - alert: DrawdownWarning
        expr: trading_drawdown_current_pct > 3
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Drawdown at {{ $value }}%"
          description: "Current drawdown exceeds 3% warning threshold"

      - alert: DrawdownCritical
        expr: trading_drawdown_current_pct > 5
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Drawdown at {{ $value }}% — approaching kill threshold"
          description: "Auto-kill at 7%. Immediate review required."

      - alert: DrawdownBreach
        expr: trading_drawdown_current_pct >= 7
        for: 0s
        labels:
          severity: emergency
        annotations:
          summary: "DRAWDOWN LIMIT BREACHED — KILL SWITCH ACTIVATED"

      # ─── API Errors ───
      - alert: APIErrorSpike
        expr: rate(trading_api_errors_total[5m]) > 5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Exchange API errors spiking: {{ $value }}/sec"

      - alert: APIDown
        expr: up{job="trading-agent"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Trading agent is DOWN"

      # ─── Execution Latency ───
      - alert: HighExecutionLatency
        expr: histogram_quantile(0.95, rate(trading_execution_latency_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 execution latency above 2 seconds"

      # ─── System Health ───
      - alert: RedisDown
        expr: redis_up == 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Redis is DOWN"

      - alert: HighMemoryUsage
        expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Memory usage above 90%"
```

### Grafana Dashboard (JSON)

```json
{
  "dashboard": {
    "title": "Trading Agent",
    "panels": [
      {
        "title": "P&L Over Time",
        "type": "timeseries",
        "targets": [{"expr": "trading_pnl_realized_dollars"}]
      },
      {
        "title": "Open Positions",
        "type": "stat",
        "targets": [{"expr": "trading_positions_open"}]
      },
      {
        "title": "Drawdown %",
        "type": "gauge",
        "targets": [{"expr": "trading_drawdown_current_pct"}],
        "thresholds": [
          {"value": 3, "color": "yellow"},
          {"value": 5, "color": "orange"},
          {"value": 7, "color": "red"}
        ]
      },
      {
        "title": "Trade Execution Latency (P95)",
        "type": "timeseries",
        "targets": [{"expr": "histogram_quantile(0.95, rate(trading_execution_latency_seconds_bucket[5m]))"}]
      },
      {
        "title": "Trades per Hour",
        "type": "timeseries",
        "targets": [{"expr": "rate(trading_trades_total[1h])"}]
      },
      {
        "title": "API Errors",
        "type": "timeseries",
        "targets": [{"expr": "rate(trading_api_errors_total[5m])"}]
      }
    ]
  }
}
```

---

## 6. Security

### API Key Management

```yaml
# config/secrets_template.yaml
# NEVER commit actual keys. Use .env files or secret managers.

exchanges:
  binance:
    api_key: "${BINANCE_API_KEY}"      # from environment
    api_secret: "${BINANCE_API_SECRET}" # from environment
    permissions: ["trade", "read"]      # NO WITHDRAWAL
    ip_whitelist:
      - "YOUR.VPS.IP.ADDRESS"

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
```

### Environment File (.env.production)

```bash
# .env.production — deployed via CI/CD secrets, never committed
# Format: KEY=VALUE, no quotes needed

# Exchange
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Redis
REDIS_PASSWORD=

# Monitoring (optional)
GRAFANA_ADMIN_PASSWORD=
```

### VPS Hardening Script

```bash
#!/bin/bash
# scripts/harden_vps.sh — Run on fresh VPS before deployment

set -euo pipefail

echo "=== Hardening VPS ==="

# 1. System updates
apt-get update && apt-get upgrade -y

# 2. Create deploy user (no root login)
useradd -m -s /bin/bash deploy
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# 3. SSH hardening
cat >> /etc/ssh/sshd_config.d/hardened.conf << 'EOF'
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
AllowUsers deploy
Protocol 2
X11Forwarding no
EOF
systemctl restart sshd

# 4. Firewall (UFW)
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 9090/tcp comment "Prometheus (localhost only via nginx)" 
ufw --force enable

# 5. Fail2ban
apt-get install -y fail2ban
cat > /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600
findtime = 600
EOF
systemctl enable fail2ban
systemctl start fail2ban

# 6. Automatic security updates
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades

# 7. Docker installation
curl -fsSL https://get.docker.com | sh
systemctl enable docker

# 8. Create app directory
mkdir -p /opt/trading-agent
chown deploy:deploy /opt/trading-agent

# 9. Set up log rotation
cat > /etc/logrotate.d/trading-agent << 'EOF'
/var/log/trading-agent/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
}
EOF

echo "=== VPS hardening complete ==="
echo "Test SSH login as 'deploy' before closing this session!"
```

### Security Checklist

- [ ] API keys have **trade + read only** permissions (NO withdrawal)
- [ ] Exchange IP whitelisting enabled for VPS IP
- [ ] SSH key-only authentication (no passwords)
- [ ] Root SSH login disabled
- [ ] Fail2ban active on SSH
- [ ] UFW firewall enabled (only 22 + monitoring ports)
- [ ] Redis password set and not exposed externally
- [ ] `.env.production` deployed via CI secrets, never committed
- [ ] Docker containers run as non-root user
- [ ] TLS for any external-facing endpoints (use Caddy/nginx reverse proxy)

---

## 7. Kill Switch

### Kill Switch Architecture

```
                    ┌─────────────────────────────┐
                    │         KILL SOURCES          │
                    ├─────────────────────────────┤
                    │ 1. Telegram /kill command     │
                    │ 2. Drawdown limit breach      │
                    │ 3. API error threshold        │
                    │ 4. Unexpected exception       │
                    │ 5. Manual (SSH + redis-cli)   │
                    └──────────┬──────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │    Redis Channel: "kill"      │
                    │    Payload: {source, reason,  │
                    │              timestamp}        │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
       ┌──────────┐    ┌──────────┐    ┌──────────┐
       │  Agent    │    │ Executor │    │   Bot    │
       │          │    │          │    │          │
       │ Stop      │    │ Cancel   │    │ Notify   │
       │ generating│    │ all open │    │ user     │
       │ signals   │    │ orders   │    │          │
       └──────────┘    │ Flatten  │    └──────────┘
                       │ positions│
                       └──────────┘
```

### Kill Switch Implementation

```python
# src/agent/kill_switch.py
"""
Kill switch — the most important safety mechanism.

When activated:
1. Stops all signal generation
2. Cancels all pending orders
3. Flattens all open positions at market
4. Pauses all trading
5. Sends notification to Telegram
6. Logs to audit trail
7. Requires human review to resume
"""

import asyncio
import json
import logging
import time
from enum import Enum
from dataclasses import dataclass

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class KillReason(Enum):
    MANUAL_TELEGRAM = "manual_telegram"
    MANUAL_SSH = "manual_ssh"
    DRAWDOWN_BREACH = "drawdown_breach"
    API_ERROR_THRESHOLD = "api_error_threshold"
    UNEXPECTED_EXCEPTION = "unexpected_exception"
    CONNECTION_LOST = "connection_lost"


@dataclass
class KillEvent:
    reason: KillReason
    source: str
    timestamp: float
    details: str = ""
    requires_human_review: bool = True


class KillSwitch:
    """
    Publishes and subscribes to the kill channel.
    All components listen and react immediately.
    """

    KILL_CHANNEL = "kill"
    STATE_KEY = "system:kill_switch"

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self._active = False
        self._callbacks: list = []

    @property
    def is_active(self) -> bool:
        return self._active

    def on_kill(self, callback):
        """Register callback to run when kill is activated."""
        self._callbacks.append(callback)

    async def activate(self, event: KillEvent):
        """Activate the kill switch. Idempotent."""
        if self._active:
            logger.warning("Kill switch already active, ignoring")
            return

        self._active = True
        logger.critical(f"KILL SWITCH ACTIVATED: {event.reason.value} — {event.details}")

        # Persist state
        await self.redis.set(self.STATE_KEY, json.dumps({
            "active": True,
            "reason": event.reason.value,
            "source": event.source,
            "timestamp": event.timestamp,
            "details": event.details,
            "requires_human_review": event.requires_human_review,
        }))

        # Publish to all subscribers
        await self.redis.publish(self.KILL_CHANNEL, json.dumps({
            "reason": event.reason.value,
            "source": event.source,
            "timestamp": event.timestamp,
            "details": event.details,
        }))

        # Run callbacks
        for cb in self._callbacks:
            try:
                await cb(event)
            except Exception as e:
                logger.error(f"Kill callback error: {e}")

    async def listen(self):
        """Listen for kill signals from any source."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.KILL_CHANNEL)

        async for msg in pubsub.listen():
            if msg["type"] == "message":
                data = json.loads(msg["data"])
                if not self._active:
                    event = KillEvent(
                        reason=KillReason(data.get("reason", "manual_ssh")),
                        source=data.get("source", "unknown"),
                        timestamp=data.get("timestamp", time.time()),
                        details=data.get("details", ""),
                    )
                    await self.activate(event)

    async def check_auto_kill(self, drawdown_pct: float, api_errors: int):
        """Auto-kill checks, called on every tick."""
        if drawdown_pct >= 7.0:
            await self.activate(KillEvent(
                reason=KillReason.DRAWDOWN_BREACH,
                source="auto",
                timestamp=time.time(),
                details=f"Drawdown {drawdown_pct:.1f}% exceeded 7% limit",
            ))

        if api_errors >= 50:  # threshold in last 5 minutes
            await self.activate(KillEvent(
                reason=KillReason.API_ERROR_THRESHOLD,
                source="auto",
                timestamp=time.time(),
                details=f"{api_errors} API errors in last 5 minutes",
            ))

    async def recover(self, authorized_by: str):
        """
        Recovery protocol — requires explicit human authorization.
        Resets state but does NOT resume trading automatically.
        """
        if not self._active:
            return

        logger.warning(f"Kill switch recovery initiated by {authorized_by}")

        # Clear kill state
        self._active = False
        await self.redis.delete(self.STATE_KEY)

        # Notify
        await self.redis.publish("alerts:telegram", json.dumps({
            "title": "Kill Switch Reset",
            "message": f"Recovery initiated by {authorized_by}. Trading remains PAUSED. Use /resume to start.",
            "priority": "high",
        }))

        # Note: trading remains paused — human must explicitly /resume
```

### Manual Kill via SSH

```bash
# Emergency: kill from SSH if Telegram is down
ssh deploy@your-vps-ip

# Option 1: Publish kill signal via redis-cli
redis-cli -a "$REDIS_PASSWORD" PUBLISH kill '{"reason":"manual_ssh","source":"ssh","timestamp":0}'

# Option 2: Stop all containers
cd /opt/trading-agent
docker compose -f docker-compose.prod.yml stop agent executor

# Option 3: Nuclear option — stop everything
docker compose -f docker-compose.prod.yml down
```

---

## 8. Backup & Recovery

### Backup Script

```bash
#!/bin/bash
# scripts/backup.sh — Daily backup of trading data

set -euo pipefail

BACKUP_DIR="/opt/trading-agent/backups"
DATE=$(date +%Y%m%d_%H%M%S)
S3_BUCKET="${BACKUP_S3_BUCKET:-trading-agent-backups}"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting backup..."

# 1. SQLite backup (online-safe via .backup command)
echo "Backing up SQLite..."
sqlite3 /opt/trading-agent/data/trading.db ".backup '$BACKUP_DIR/trading_$DATE.db'"

# 2. Redis RDB snapshot
echo "Backing up Redis..."
docker exec trading-agent-redis-1 redis-cli -a "$REDIS_PASSWORD" BGSAVE
sleep 5
docker cp trading-agent-redis-1:/data/dump.rdb "$BACKUP_DIR/redis_$DATE.rdb"

# 3. Trade journal
echo "Backing up trade journal..."
tar czf "$BACKUP_DIR/journal_$DATE.tar.gz" /opt/trading-agent/data/journal/

# 4. Config
echo "Backing up config..."
tar czf "$BACKUP_DIR/config_$DATE.tar.gz" /opt/trading-agent/config/

# 5. Upload to cloud storage (if configured)
if command -v aws &> /dev/null && [ -n "${BACKUP_S3_BUCKET:-}" ]; then
    echo "Uploading to S3..."
    aws s3 sync "$BACKUP_DIR/" "s3://$S3_BUCKET/daily/$DATE/" \
        --exclude "*" \
        --include "trading_$DATE.db" \
        --include "redis_$DATE.rdb" \
        --include "journal_$DATE.tar.gz"
fi

# 6. Cleanup old local backups (keep 7 days)
find "$BACKUP_DIR" -name "*.db" -mtime +7 -delete
find "$BACKUP_DIR" -name "*.rdb" -mtime +7 -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +7 -delete

echo "[$(date)] Backup complete: $BACKUP_DIR"
```

### Backup Cron (add to crontab)

```cron
# Daily backup at 2 AM
0 2 * * * /opt/trading-agent/scripts/backup.sh >> /var/log/trading-agent/backup.log 2>&1

# Pre-deploy backup is triggered by CI/CD (see deploy-production job)
```

### Recovery Procedures

```bash
#!/bin/bash
# scripts/restore.sh — Restore from backup

set -euo pipefail

BACKUP_FILE="$1"  # e.g., /opt/trading-agent/backups/trading_20260724_020000.db

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup_file.db>"
    echo "Available backups:"
    ls -la /opt/trading-agent/backups/*.db 2>/dev/null
    exit 1
fi

echo "=== RECOVERY PROCEDURE ==="
echo "This will restore from: $BACKUP_FILE"
echo ""
echo "Steps:"
echo "1. Stop trading (kill switch)"
echo "2. Restore database"
echo "3. Verify data integrity"
echo "4. Restart services"
echo ""
read -p "Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# 1. Stop trading
echo "Activating kill switch..."
redis-cli -a "$REDIS_PASSWORD" PUBLISH kill '{"reason":"manual_ssh","source":"recovery"}'
sleep 5

# 2. Stop agent
echo "Stopping agent..."
cd /opt/trading-agent
docker compose -f docker-compose.prod.yml stop agent executor

# 3. Backup current DB
echo "Backing up current database..."
cp /opt/trading-agent/data/trading.db "/opt/trading-agent/data/trading.db.pre-recovery.$(date +%s)"

# 4. Restore
echo "Restoring database..."
cp "$BACKUP_FILE" /opt/trading-agent/data/trading.db

# 5. Verify
echo "Verifying database integrity..."
sqlite3 /opt/trading-agent/data/trading.db "PRAGMA integrity_check;"

# 6. Restart
echo "Restarting services..."
docker compose -f docker-compose.prod.yml up -d agent executor

echo "=== Recovery complete ==="
echo "IMPORTANT: Review positions manually. Use /status and /positions in Telegram."
echo "Do NOT resume trading until you've verified all positions match reality."
```

### Redis Persistence Config

```conf
# Redis persistence (in docker-compose.prod.yml command)
# RDB snapshots + AOF for durability

appendonly yes
appendfsync everysec
save 60 1         # snapshot if at least 1 key changed in 60 seconds
save 300 10       # snapshot if at least 10 keys changed in 300 seconds
save 600 10000    # snapshot if at least 10000 keys changed in 600 seconds
```

---

## 9. Runtime Configuration

### Config Structure

```yaml
# config/config.yaml — Main configuration file
# Non-secret configuration. Secrets come from environment variables.

system:
  env: production           # development | staging | production
  log_level: INFO           # DEBUG | INFO | WARNING | ERROR
  timezone: "UTC"

trading:
  mode: paper               # paper | live
  symbols:
    - BTCUSDT
    - ETHUSDT
  max_positions: 5
  position_size_pct: 2.0    # % of equity per position
  
risk:
  max_drawdown_pct: 7.0     # hard limit — triggers kill switch
  drawdown_warning_pct: 5.0 # warning alert
  max_daily_loss_pct: 3.0   # daily loss limit
  max_exposure_pct: 50.0    # max gross exposure as % of equity
  correlation_limit: 0.7    # max correlation between positions
  
strategy:
  genome: "v2.3.1"
  regime_detection: true
  rebalance_interval: 3600  # seconds
  
execution:
  max_slippage_bps: 10      # basis points
  order_timeout_sec: 30
  retry_attempts: 3
  
monitoring:
  metrics_port: 9100
  health_port: 8000
  
hot_reload:                 # these keys can be changed without restart
  - trading.symbols
  - trading.max_positions
  - risk.drawdown_warning_pct
  - strategy.rebalance_interval
  - system.log_level
```

### Hot-Reload Implementation

```python
# src/agent/config.py
"""
Configuration manager with hot-reload support.

Watches config.yaml for changes and reloads non-critical settings.
Critical settings require container restart.
"""

import yaml
import logging
import hashlib
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)

HOT_RELOADABLE = {
    "trading.symbols",
    "trading.max_positions",
    "trading.position_size_pct",
    "risk.drawdown_warning_pct",
    "strategy.rebalance_interval",
    "system.log_level",
}

RESTART_REQUIRED = {
    "risk.max_drawdown_pct",
    "risk.max_daily_loss_pct",
    "trading.mode",
    "system.env",
}


class ConfigManager:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = Path(config_path)
        self._config = {}
        self._load()
        self._start_watcher()

    def _load(self):
        with open(self.config_path) as f:
            self._config = yaml.safe_load(f)
        logger.info("Configuration loaded")

    def _start_watcher(self):
        self._observer = Observer()
        handler = ConfigFileHandler(self)
        self._observer.schedule(handler, str(self.config_path.parent), recursive=False)
        self._observer.daemon = True
        self._observer.start()

    def on_file_changed(self):
        old_config = self._config.copy()
        self._load()

        # Check if any restart-required keys changed
        for key in RESTART_REQUIRED:
            old_val = self._get_nested(old_config, key)
            new_val = self._get_nested(self._config, key)
            if old_val != new_val:
                logger.warning(f"Config key '{key}' changed — RESTART REQUIRED to apply")

        logger.info("Hot-reloadable config updated")

    def get(self, dotpath: str, default=None):
        return self._get_nested(self._config, dotpath, default)

    @staticmethod
    def _get_nested(d: dict, dotpath: str, default=None):
        keys = dotpath.split(".")
        for key in keys:
            if isinstance(d, dict):
                d = d.get(key, default)
            else:
                return default
        return d


class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, manager: ConfigManager):
        self.manager = manager
        self._last_hash = ""

    def on_modified(self, event):
        if event.src_path.endswith("config.yaml"):
            with open(event.src_path, "rb") as f:
                new_hash = hashlib.md5(f.read()).hexdigest()
            if new_hash != self._last_hash:
                self._last_hash = new_hash
                self.manager.on_file_changed()
```

---

## 10. Deployment Procedures

### Initial Setup (Staging)

```bash
# 1. Provision VPS (e.g., Hetzner CX21, DigitalOcean $12/mo)
# 2. Run hardening script
scp scripts/harden_vps.sh deploy@staging-ip:/tmp/
ssh deploy@staging-ip "bash /tmp/harden_vps.sh"

# 3. Clone repo
ssh deploy@staging-ip
cd /opt/trading-agent
git clone https://github.com/YOUR_ORG/trading-super-agent.git .

# 4. Set up secrets
cp .env.example .env.production
nano .env.production  # fill in secrets

# 5. Deploy
docker compose -f docker/docker-compose.prod.yml up -d

# 6. Verify
docker compose -f docker/docker-compose.prod.yml ps
curl http://localhost:8000/health
```

### Production Deploy (via CI/CD)

```bash
# Tag a release
git tag v1.0.0
git push origin v1.0.0

# CI/CD pipeline:
# 1. Lint + test (Python & Rust)
# 2. Build Docker images → push to ghcr.io
# 3. SSH to prod VPS
# 4. Pre-deploy backup
# 5. Pull new images
# 6. Rolling restart
# 7. Health check
# 8. Notify Telegram
```

### Rollback

```bash
# On the VPS
cd /opt/trading-agent

# Option 1: Roll back to previous image tag
export IMAGE_TAG=previous-tag-here
docker compose -f docker-compose.prod.yml up -d

# Option 2: Full restore from backup
./scripts/restore.sh /opt/trading-agent/backups/trading_YYYYMMDD_HHMMSS.db
```

---

## Appendix A: VPS Recommendations

| Provider | Plan | CPU | RAM | Disk | Price/mo |
|----------|------|-----|-----|------|----------|
| Hetzner | CX22 | 2 vCPU | 4GB | 40GB | €4.99 |
| DigitalOcean | Basic | 2 vCPU | 2GB | 50GB | $12 |
| Vultr | Cloud Compute | 2 vCPU | 2GB | 55GB | $12 |
| AWS Lightsail | $10 plan | 2 vCPU | 2GB | 60GB | $10 |
| Oracle Cloud | Free tier | 4 OCPU | 24GB | 200GB | **$0** |

**Recommended:** Hetzner CX22 for price/performance. Oracle Cloud free tier if cost is paramount.

## Appendix B: Quick Commands

```bash
# Status
docker compose -f docker-compose.prod.yml ps
curl http://localhost:8000/health

# Logs
docker compose -f docker-compose.prod.yml logs -f agent
docker compose -f docker-compose.prod.yml logs -f executor

# Restart single service
docker compose -f docker-compose.prod.yml restart agent

# Emergency stop
redis-cli -a "$REDIS_PASSWORD" PUBLISH kill '{"reason":"manual_ssh","source":"ops"}'

# Database query
sqlite3 /opt/trading-agent/data/trading.db "SELECT * FROM trades ORDER BY created_at DESC LIMIT 10;"

# Redis check
redis-cli -a "$REDIS_PASSWORD" INFO stats
```

## Appendix C: File Structure

```
trading-super-agent/
├── .github/
│   └── workflows/
│       └── ci.yml                    # CI/CD pipeline
├── docker/
│   ├── Dockerfile.agent              # Python agent image
│   ├── Dockerfile.executor           # Rust executor image
│   ├── docker-compose.yml            # Development
│   └── docker-compose.prod.yml       # Production
├── monitoring/
│   ├── prometheus.yml                # Prometheus config
│   ├── alert_rules.yml               # Alert rules
│   └── grafana-dashboard.json        # Grafana dashboard
├── config/
│   ├── config.yaml                   # Main config (non-secret)
│   └── secrets_template.yaml         # Secrets template
├── scripts/
│   ├── harden_vps.sh                 # VPS hardening
│   ├── backup.sh                     # Daily backup
│   └── restore.sh                    # Recovery procedure
├── src/
│   ├── agent/                        # Python agent code
│   │   ├── main.py                   # Agent entrypoint
│   │   ├── telegram_bot.py           # Telegram bot
│   │   ├── health.py                 # Health endpoint
│   │   ├── metrics.py                # Prometheus metrics
│   │   ├── kill_switch.py            # Kill switch
│   │   └── config.py                 # Config manager
│   └── executor/                     # Rust executor code
│       ├── Cargo.toml
│       └── src/
│           └── main.rs
├── tests/
│   ├── unit/
│   └── integration/
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .env.production                   # (gitignored)
└── DEPLOYMENT.md                     # This file
```
