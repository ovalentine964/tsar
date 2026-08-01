# TSAR — Installation Guide

## Prerequisites

| Requirement | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.12+ | Core runtime |
| **Docker** | 24.0+ | Container orchestration (recommended) |
| **Docker Compose** | 2.20+ | Multi-service deployment |
| **Redis** | 7.0+ | State cache, regime data, event bus (auto-configured in Docker) |
| **Git** | 2.30+ | Source control |
| **Binance Account** | — | Exchange access (testnet or live) |

### Optional

| Tool | Version | Purpose |
|------|---------|---------|
| Rust | 1.79+ | Performance layer (14 crates — MEV scanner, gas optimizer, tick processor) |
| CMake + g++ | — | C++ specialist layer (Level 3+ backends) |
| Flutter SDK | 3.16+ | Mobile app development |
| NVIDIA GPU | — | GPU-accelerated skills (cuFOLIO, cuOpt) |
| Foundry / Hardhat | — | Smart contract compilation (blockchain rules) |
| Node.js | 18+ | Smart contract tooling |

> **Note:** TSAR works without Rust or C++ — Python fallbacks exist for all backends. The system degrades gracefully.

---

## Quick Start (5 Minutes)

### 1. Get API Keys

| Key | Where | Cost |
|-----|-------|------|
| **Binance API** | [testnet.binance.vision](https://testnet.binance.vision) → Generate API Key | Free |
| **NVIDIA API** | [build.nvidia.com](https://build.nvidia.com) → Get API Key | Free |

### 2. Clone & Configure

```bash
git clone https://github.com/ovalentine964/tsar.git
cd tsar
cp .env.example .env
```

Edit `.env` and fill in your keys:

```bash
# Required
EXCHANGE_API_KEY=your_binance_key
EXCHANGE_SECRET=your_binance_secret
EXCHANGE_SANDBOX=true
NVIDIA_API_KEY=your_nvidia_key

# Required (generate a strong key)
TSAR_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Optional (for Telegram alerts)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### 3. Start

**Docker (recommended):**

```bash
./quickstart.sh
```

**Local install:**

```bash
make setup
make run-dry
```

### 4. Verify

```bash
curl http://localhost:8000/health
```

---

## Step-by-Step Installation

### Option A: Docker (Recommended)

Docker handles all dependencies automatically.

```bash
# Build images (includes Rust compilation)
make docker-build

# Start services (TSAR + Redis)
make docker-up

# View logs
make docker-logs

# Stop services
make docker-down
```

**Services started:**
- `tsar-app` — Trading system on port 8000
- `tsar-redis` — Redis cache on port 6379

**Optional monitoring stack:**

```bash
docker compose --profile monitoring up -d
```

This adds:
- `tsar-prometheus` — Metrics on port 9090
- `tsar-grafana` — Dashboards on port 3000 (admin/tsar_grafana)

### Option B: Local Install

```bash
# Install Python dependencies
make install-dev

# Create data directory
mkdir -p data

# Run setup wizard
python scripts/setup.py

# Run tests to verify
make test

# Start paper trading
make run-dry
```

### Option C: Manual Install

```bash
# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"

# Copy and edit config
cp .env.example .env
nano .env

# Initialize database
make migrate

# Run
python3 -m src --paper
```

### Option D: With Rust Performance Layer

```bash
# Install Rust (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

# Build Rust crates
cd rust && cargo build --release && cd ..

# Install with Rust backend
pip install -e ".[dev,rust]"
```

### Option E: With Blockchain Rules

```bash
# Install Foundry (for Solidity contracts)
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Compile contracts
cd blockchain/contracts && forge build && cd ../..

# Deploy to testnet (requires PRIVATE_KEY in .env)
./scripts/deploy-contracts.sh --network sepolia
```

---

## Environment Variables

All variables are documented in `.env.example`. Here's the full reference:

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `EXCHANGE_API_KEY` | Binance API key | `abc123...` |
| `EXCHANGE_SECRET` | Binance API secret | `def456...` |
| `EXCHANGE_SANDBOX` | Use testnet (`true`) or live (`false`) | `true` |
| `NVIDIA_API_KEY` | NVIDIA NIM API key | `nvapi-...` |
| `TSAR_API_KEY` | API authentication key (generate with `secrets.token_urlsafe(48)`) | `random-48-char-string` |
| `REDIS_PASSWORD` | Redis authentication password | `random-32-char-string` |

### Optional — Telegram

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | *(empty)* |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID | *(empty)* |

### Optional — Server

| Variable | Description | Default |
|----------|-------------|---------|
| `TSAR_API_PORT` | API server port | `8000` |
| `TSAR_TRADING_MODE` | `paper` or `live` | `paper` |
| `TSAR_CORS_ORIGINS` | Comma-separated allowed origins | *(empty — denies all)* |
| `REDIS_HOST` | Redis hostname | `redis` (Docker) / `localhost` |
| `REDIS_PORT` | Redis port | `6379` |

### Optional — Blockchain

| Variable | Description | Default |
|----------|-------------|---------|
| `ETH_RPC_URL` | Ethereum RPC endpoint | `https://sepolia.infura.io/v3/...` |
| `POLYGON_RPC_URL` | Polygon RPC endpoint | *(empty)* |
| `ARBITRUM_RPC_URL` | Arbitrum RPC endpoint | *(empty)* |
| `SOLANA_RPC_URL` | Solana RPC endpoint | `https://api.devnet.solana.com` |
| `PRIVATE_KEY` | Deployer wallet private key (testnet only!) | *(empty)* |

### Security Notes

- `TSAR_API_KEY` — TSAR **refuses to start** if this is empty or uses a known weak value
- `REDIS_PASSWORD` — Generate a strong random password; don't use defaults
- `EXCHANGE_API_KEY` / `EXCHANGE_SECRET` — Use testnet keys until you've validated with 50+ paper trades and 75% win rate
- `PRIVATE_KEY` — **Never use a mainnet private key.** Testnet only. All secrets are validated at startup (see `src/__main__.py` — `_validate_secrets()`)

---

## First Trade Checklist

```
[ ] Binance testnet API keys configured in .env
[ ] NVIDIA API key configured in .env
[ ] TSAR_API_KEY generated and set
[ ] REDIS_PASSWORD generated and set
[ ] TSAR running (curl http://localhost:8000/health)
[ ] Paper mode enabled (TSAR_TRADING_MODE=paper)
[ ] Telegram bot connected (optional)
[ ] Wait for first signal — check /status endpoint
[ ] Monitor for 24 hours
[ ] Run for 7 days in paper mode
[ ] Achieve 75% win rate over 50+ trades
[ ] Only then consider switching to live mode
```

---

## Trading Modes

| Mode | Risk | How to Enable |
|------|------|---------------|
| `paper` | $0 — simulated orders | `TSAR_TRADING_MODE=paper` (default) |
| `live` | Real money | `TSAR_TRADING_MODE=live` + active mandate in `config/mandate.yaml` |

**Live trading requires:**
1. An active mandate (`config/mandate.yaml` — `status: ACTIVE`)
2. 50+ paper trades
3. 7+ days of paper trading
4. 75%+ win rate
5. Manual approval via the Mandate Gate

---

## Accessing TSAR

### Web Dashboard

Open `http://YOUR_SERVER:8000/app` in any browser. Enter your `TSAR_API_KEY` when prompted.

### Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token
2. Message your bot → visit `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy your `chat_id`
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
4. Restart TSAR
5. Send `/status` to your bot

### Mobile App

1. Download APK from [GitHub Releases](../../releases)
2. Install (allow unknown sources on Android)
3. Enter your server URL and `TSAR_API_KEY`

### API

```bash
# Health check
curl http://localhost:8000/health

# API documentation
open http://localhost:8000/docs

# Portfolio status (authenticated)
curl -H "Authorization: Bearer YOUR_API_KEY" http://localhost:8000/api/portfolio
```

---

## Troubleshooting

### TSAR won't start — "SECURITY VALIDATION FAILED"

Your `TSAR_API_KEY` or `REDIS_PASSWORD` is empty or uses a known weak value.

```bash
# Generate strong secrets
python3 -c "import secrets; print('TSAR_API_KEY=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(32))"
```

### Redis connection refused

```bash
# Check if Redis is running
docker compose ps

# Check Redis logs
docker compose logs redis

# Restart Redis
docker compose restart redis
```

### Database errors

```bash
# Run migrations
make migrate

# Check database integrity
sqlite3 data/tsar.db "PRAGMA integrity_check;"
```

### Port already in use

```bash
# Find what's using port 8000
lsof -i :8000

# Change port in .env
TSAR_API_PORT=8001
```

### Exchange connection errors

1. Verify API keys are correct
2. Check `EXCHANGE_SANDBOX=true` for testnet
3. Ensure your IP is whitelisted on Binance
4. Check rate limits: `config/default.yaml` → `exchanges.rate_limit_per_minute`

### LLM not responding

```bash
# If using Ollama (local)
ollama list
ollama pull qwen2.5:7b

# If using DeepSeek
# Verify DEEPSEEK_API_KEY in .env

# Check LLM config
cat config/models.yaml
```

### Rust build fails

```bash
# Check Rust version (need 1.79+)
rustc --version

# Update Rust
rustup update stable

# Build with verbose output
cd rust && cargo build --release -vv

# Fallback: TSAR works without Rust (Python backends only)
pip install -e ".[dev]"  # without rust extras
```

### Smart contract deployment fails

```bash
# Check Foundry installation
forge --version

# Verify .env has PRIVATE_KEY set
grep PRIVATE_KEY .env

# Check RPC URL is accessible
curl -X POST $ETH_RPC_URL -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'

# Compile contracts locally
cd blockchain/contracts && forge build
```

### Tests failing

```bash
# Clean and reinstall
make clean
pip install -e ".[dev]"
make test
```

---

## Uninstall

```bash
# Stop Docker services
make docker-down

# Remove Docker volumes (deletes all data)
docker compose down -v

# Remove local data
rm -rf data/ logs/ .env

# Remove Python packages
pip uninstall tsar
```
