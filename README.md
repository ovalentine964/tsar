# TSAR — Trading Super Agent for Returns

> **Self-improving autonomous trading system that compounds knowledge through use.**

[![CI](https://img.shields.io/github/actions/workflow/status/ovalentine964/tsar/ci.yml?branch=main&label=CI&logo=github)](https://github.com/ovalentine964/tsar/actions)
[![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-orange)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/status-alpha-yellow)](#current-status)

---

## What Is TSAR?

TSAR is **not a trading bot**. It's a **self-improving market intelligence** — a single, deep, domain-specific super agent that compounds knowledge with every trade.

**One job:** Autonomous capital compounding under strict risk constraints.

**The difference:** A trading bot is static code. A multi-agent system resets between tasks. TSAR **compounds**. Every trade generates proprietary data. Every reflection improves the system. Every adaptation makes the next trade better.

> *"You can copy a bot's code. You cannot copy a super agent's knowledge."*

### The Flywheel

```
TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE
  ↑                                                │
  └────────────────────────────────────────────────┘
```

---

## Architecture Overview

TSAR uses a **layered architecture** with abstract interfaces, making the backend an implementation detail. Python for orchestration, Rust for performance, C++ for specialist workloads.

```
┌──────────────────────────────────────────────────────────────────┐
│                     TSAR SUPER AGENT                             │
│                                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│   │ Signal   │  │ Risk     │  │ Execution│  │ Trade        │   │
│   │ Scout    │→ │ Guardian │→ │ Sniper   │  │ Philosopher  │   │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────────────┘   │
│        │              │              │                            │
│   ┌────┴─────┐  ┌─────┴─────┐  ┌────┴──────┐                    │
│   │ Flywheel │  │ Sentiment │  │ Regime    │                    │
│   │ Orch.    │  │ Agent     │  │ Detector  │                    │
│   └────┬─────┘  └─────┬─────┘  └────┬──────┘                    │
│        │              │              │                            │
│   ┌────┴──────────────┴──────────────┴───────────────────────┐   │
│   │          INTERFACE LAYER (the contract)                   │   │
│   │  ExchangeGateway · PricingEngine · ExecutionEngine        │   │
│   │  RiskEngine · LLMProvider · BackendRegistry               │   │
│   └────┬──────────────┬──────────────┬───────────────────────┘   │
│        │              │              │                            │
│   ┌────┴─────┐  ┌─────┴────┐  ┌─────┴──────┐                    │
│   │ 6 Knowl. │  │ EventBus │  │ DeFi +     │                    │
│   │ Stores   │  │ (Redis)  │  │ Telegram   │                    │
│   └──────────┘  └──────────┘  └────────────┘                    │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │          BACKEND REGISTRY (config-driven)                │   │
│   │   Python (Day 1)  │  Rust (Level 2)  │  C++ (Level 3+)  │   │
│   └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Agent Pipeline

| Agent | Role |
|-------|------|
| **SignalScout** | Finds statistical edges across markets |
| **RiskGuardian** | VETO power — deterministic risk checks before every trade |
| **ExecutionSniper** | Places, monitors, and manages orders |
| **TradePhilosopher** | Post-trade reflection and lesson extraction |
| **FlywheelOrchestrator** | Auto-triggers the self-improvement loop |
| **RegimeDetector** | HMM-based market regime classification |
| **SentimentAgent** | Aggregates CryptoPanic + Fear & Greed sentiment |
| **StrategyGeneticist** | Evolves strategy genomes through mutation |
| **MarketCartographer** | Cross-asset correlation mapping |
| **MacroAgent** | Economic context and event awareness |

### Risk System

- **Kill Switch** — dual-write (file + Redis) with watchdog monitoring
- **Mandate Gate** — human authorization boundary for live trading
- **Anti-behavioral guards** — revenge, greed, FOMO, overconfidence protection
- **Economic blackout** — auto-block trading around FOMC, CPI, NFP events
- **Fee-aware sizing** — Kelly criterion accounts for exchange fees

### DeFi Integration

On-chain execution across EVM chains (ETH, Polygon, Arbitrum, Base) and Solana:

| Component | Purpose |
|-----------|---------|
| **DexExecutor** | 1inch (EVM) + Jupiter (Solana) swap execution |
| **IntentExecutor** | CoW Protocol, UniswapX, 1inch Fusion intent-based trades |
| **BridgeClient** | Cross-chain bridging via Wormhole, LayerZero, Axelar |
| **L2Optimizer** | Gas optimization, chain comparison, batch transactions |
| **SettlementEngine** | Smart contract escrow with multi-sig support |
| **WalletManager** | Encrypted wallet storage with Fernet encryption |

### Telegram Bot

Interactive trading partner — not just notifications:

- **Conversational setup** — configure credentials without touching a terminal
- **Trade proposals** — inline keyboard approve/reject/modify before execution
- **Post-trade reports** — detailed analysis with lessons and flywheel updates
- **Market discussion** — `/discuss`, `/why`, `/performance`, `/regime` commands

---

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (recommended)
- Binance testnet API keys ([testnet.binance.vision](https://testnet.binance.vision))
- NVIDIA API key ([build.nvidia.com](https://build.nvidia.com) — free tier)

### Install & Run

```bash
# 1. Clone
git clone https://github.com/ovalentine964/tsar.git && cd tsar

# 2. Configure
cp .env.example .env
nano .env    # Fill in your API keys

# 3. Start (Docker)
./quickstart.sh

# OR — local install
make setup
make run-dry
```

### Access

| Method | How |
|--------|-----|
| 📱 **Web Dashboard** | `http://localhost:8000/app` |
| 📲 **Mobile APK** | [GitHub Releases](../../releases) |
| 💬 **Telegram** | Send `/status` to your bot |
| 📖 **API Docs** | `http://localhost:8000/docs` |

See **[INSTALL.md](INSTALL.md)** for detailed setup instructions.

---

## Components

### Knowledge Stores (6)

| Store | Purpose |
|-------|---------|
| Trade Memory | Every trade with context, outcome, reflection |
| Strategy Genomes | Evolving strategy parameters and rules |
| Regime State | Real-time market regime probabilities |
| Pattern Library | Discovered patterns with statistical validation |
| Lesson Archive | Distilled wisdom from failures and successes |
| ChromaDB | Vector embeddings for semantic similarity search |

### Interface Layer

5 abstract base classes. The interface is the contract. The backend is an implementation detail.

| Interface | Python (Day 1) | Rust (Level 2) | C++ (Level 3+) |
|-----------|----------------|----------------|-----------------|
| ExchangeGateway | ccxt REST | WebSocket | FIX protocol |
| PricingEngine | pandas-ta | Tick processor | QuantLib |
| ExecutionEngine | ccxt REST + Paper | Order executor | FIX engine |
| RiskEngine | Python deterministic | Rust deterministic | GPU Monte Carlo |
| LLMProvider | Ollama + DeepSeek + NVIDIA NIM | — | — |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Brain | Python 3.12 — agents, LLM, strategy, risk |
| Muscle | Rust 1.79 — WebSocket, tick processing, order execution |
| Specialist | C++ — QuantLib derivatives, FIX protocol, CUDA |
| Database | SQLite + FTS5 — trade memory, lessons, patterns |
| Cache | Redis — regime state, real-time cache |
| Vectors | ChromaDB — pattern similarity search |
| Exchange | ccxt — 100+ exchanges |
| LLM | Ollama + DeepSeek + NVIDIA NIM |
| API | FastAPI — REST + WebSocket |
| Mobile | Flutter — cross-platform app |
| Telegram | python-telegram-bot — interactive bot |
| Messaging | CloudEvents v1.0 — event protocol |
| Monitoring | Prometheus + Grafana |
| Container | Docker Compose |

---

## Project Structure

```
tsar/
├── src/                    # Python source
│   ├── agents/            # 10 agents (orchestrator, signal, risk, execution...)
│   ├── backends/          # Implementations
│   │   ├── python/        # ccxt, paper engine, LLM providers
│   │   └── defi/          # DEX execution, bridging, wallets, settlement
│   ├── bot/               # Telegram interactive bot
│   ├── comms/             # CloudEvents event bus
│   ├── interfaces/        # Abstract base classes (THE CONTRACT)
│   ├── knowledge/         # 6 stores + FTS5 + ChromaDB + knowledge graph
│   ├── risk/              # Risk engine, guards, mandate, watchdog, kill switch
│   ├── strategy/          # Strategies, backtest, factor library, ML scorer
│   ├── llm/               # LLM routing, evaluation, token counting
│   ├── metrics/           # Prometheus export, improvement measurement
│   └── api/               # FastAPI REST + static dashboard
├── config/                 # YAML configuration
├── rust/                   # Rust performance layer (4 crates)
├── cpp/                    # C++ specialist layer
├── mobile/                 # Flutter mobile app
├── tests/                  # Test suite (unit + integration)
├── migrations/             # SQLite migrations
├── deploy/                 # Azure deployment configs
├── docs/                   # Architecture, council, research docs
├── grafana/                # Pre-built dashboards
├── monitoring/             # Prometheus config
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── pyproject.toml
```

---

## Configuration

| File | Purpose |
|------|---------|
| `.env` | Secrets and environment variables |
| `config/tsar.yaml` | Main app config (exchange, risk, LLM, strategy) |
| `config/risk.yaml` | Canonical risk parameters |
| `config/mandate.yaml` | Trading mandate — human authorization boundary |
| `config/models.yaml` | LLM model routing and fallbacks |
| `config/nvidia_skills.yaml` | NVIDIA GPU skill configuration |
| `config/backends.yaml` | Backend selection per interface |
| `config/default.yaml` | Application defaults (Redis, logging, API) |

---

## Trading Modes

| Mode | Risk | Use |
|------|------|-----|
| `paper` | $0 | Test strategies safely — simulated orders against live data |
| `live` | Real money | Only after 30+ profitable paper trades and active mandate |

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System architecture deep dive |
| [Deployment](docs/DEPLOYMENT.md) | Azure, Docker, and local deployment |
| [Installation](INSTALL.md) | Step-by-step setup guide |
| [Changelog](CHANGELOG.md) | Version history |
| [Mobile App](mobile/README.md) | Flutter app setup |
| [Council Reviews](docs/council/) | Architecture and quality reviews |
| [Research](docs/research/) | AI trading research reports |

---

## Current Status

```
 ✅ v0.1.0 — Core system, 12 agents, 6 knowledge stores, NVIDIA skills
 ✅ v0.2.0 — Full superagent wiring, DeFi integration, anti-loss system, Telegram bot
 ⬜ v0.3.0 — Paper trading validation, live mandate activation
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-thing`)
3. Run tests (`make test`)
4. Run linter (`make lint`)
5. Commit with conventional messages (`feat:`, `fix:`, `docs:`)
6. Open a pull request

### Development Setup

```bash
make setup          # Install deps, create DB, verify
make test           # Run tests with coverage
make lint           # Run ruff linter
make format         # Auto-format code
```

---

## License

[MIT](LICENSE) — Copyright © 2026 Valentine Owuor

---

*Built by Valentine Owuor. Architecture reviewed by 17 councils. Designed for retail traders.*
