# TSAR — Trading Super Agent for Returns

> **Self-improving autonomous trading system that compounds knowledge through use.**

[![CI](https://img.shields.io/github/actions/workflow/status/ovalentine964/tsar/ci.yml?branch=main&label=CI&logo=github)](https://github.com/ovalentine964/tsar/actions)
[![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Rust](https://img.shields.io/badge/rust-1.79+-orange?logo=rust&logoColor=white)](https://www.rust-lang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.2-orange)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/status-alpha-yellow)](#current-status)

---

## What Is TSAR?

TSAR is **not a trading bot**. It's a **self-improving market intelligence** — a single, deep, domain-specific super agent that compounds knowledge with every trade.

**One job:** Autonomous capital compounding under strict risk constraints.

**The difference:** A trading bot is static code. A multi-agent system resets between tasks. TSAR **compounds**. Every trade generates proprietary data. Every reflection improves the system. Every adaptation makes the next trade better.

> *"You can copy a bot's code. You cannot copy a super agent's knowledge."*

### Jensen's Superagent Blueprint

TSAR implements the [superagent blueprint](https://www.jensen.ai/) — a single, deep, domain-specific agent that owns the entire vertical. Not a swarm of shallow agents. One agent with:

- **Full-stack ownership** — from signal discovery to settlement
- **Knowledge compounding** — every trade makes the next one better
- **Self-improvement flywheel** — OBSERVE → REFLECT → EXTRACT → ADAPT
- **Multi-runtime** — Python brain, Rust muscles, blockchain settlement

### The Flywheel

```
TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE
  ↑                                                │
  └────────────────────────────────────────────────┘
```

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                        TSAR SUPER AGENT                                │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      AGENT LAYER                                 │  │
│  │  SignalScout → RiskGuardian → ExecutionSniper → TradePhilosopher │  │
│  │  FlywheelOrch · SentimentAgent · RegimeDetector · StrategyGen    │  │
│  │  MarketCartographer · MacroAgent · InformationAgent · NewsGate   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    OPENHARNESS AGENT LOOP                        │  │
│  │  LLM Stream → Tool Execute → Result Merge → Retry w/Backoff     │  │
│  │  Token counting · Cost tracking · Parallel tool execution        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   43 TOOLS (News + DeFi + Analysis)              │  │
│  │  News Sources: Whale Alert · SEC/CFTC · Exploits · Twitter ·    │  │
│  │                Reddit/Discord · CryptoPanic · Fear & Greed       │  │
│  │  DeFi: DEX exec · Intent trading · Bridging · Settlement         │  │
│  │  Analysis: Technical · Fundamental · On-chain · Order flow        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   SCENARIO PREVENTION                            │  │
│  │  Flash Crash · Stop Hunt · Whipsaw · Liquidity · Correlation     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   BLOCKCHAIN RULES LAYER                         │  │
│  │  Solidity: KillSwitch · Mandate · AuditTrail · Governance        │  │
│  │  Rust: EVM bindings · Position limits · Kill switch client        │  │
│  │  Python: Blockchain enforcer · Dual enforcement                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   INTERFACE LAYER (the contract)                  │  │
│  │  ExchangeGateway · PricingEngine · ExecutionEngine                │  │
│  │  RiskEngine · LLMProvider · BackendRegistry                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   BACKEND REGISTRY (config-driven)                │  │
│  │    Python (Day 1)  │  Rust (14 crates)  │  C++ (Level 3+)        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
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
| **InformationAgent** | News aggregation and impact analysis |
| **NewsGatekeeper** | News signal gating and verification |

### Risk System

- **Kill Switch** — dual-write (file + Redis) with watchdog monitoring
- **Mandate Gate** — human authorization boundary for live trading
- **Anti-behavioral guards** — revenge, greed, FOMO, overconfidence protection
- **Scenario prevention** — flash crash, stop hunt, whipsaw, liquidity, correlation detection
- **Economic blackout** — auto-block trading around FOMC, CPI, NFP events
- **Fee-aware sizing** — Kelly criterion accounts for exchange fees
- **Blockchain rules** — on-chain kill switch, mandate, audit trail (dual enforcement)
- **75% win rate gate** — requires 50 trades + 7 days + 75% win rate before live

### News & Intelligence

5 new intelligence sources with LLM verification:

| Source | Data |
|--------|------|
| **Whale Alert** | Large on-chain transfers |
| **SEC/CFTC** | Regulatory filings and enforcement |
| **Exploit Alerts** | Security incidents and hacks |
| **Twitter/X** | Crypto influencer sentiment |
| **Reddit/Discord** | Community sentiment shifts |

All news signals pass through LLM verification and source accuracy tracking.

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
| **MEV Scanner** | Mempool monitoring, sandwich detection (Rust) |
| **Gas Optimizer** | Multi-chain gas comparison and optimization (Rust) |
| **DEX Aggregator** | Cross-DEX route optimization (Rust) |

### Blockchain Rules (Smart Contracts)

On-chain governance for trustless risk enforcement:

| Contract | Purpose |
|----------|---------|
| **TSARKillSwitch.sol** | Emergency halt with on-chain state |
| **TSARMandate.sol** | Trading mandate authorization |
| **TSARAuditTrail.sol** | Immutable trade audit log |
| **TSARGovernance.sol** | Multi-sig governance decisions |
| **TSARPositionLimits.sol** | On-chain position limit enforcement |

Dual enforcement: off-chain (fast, Python) + on-chain (trustless, Solidity).

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

### Rust Performance Layer (14 Crates)

| Crate | Purpose |
|-------|---------|
| `tick-processor` | Real-time tick data processing |
| `order-executor` | Low-latency order execution |
| `ws-manager` | WebSocket connection management |
| `mev-scanner` | Mempool monitoring and sandwich detection |
| `gas-optimizer` | Multi-chain gas comparison |
| `dex-aggregator` | Cross-DEX route optimization |
| `price-feed` | Aggregated price feed with staleness detection |
| `evm-client` | Ethereum/EVM chain interaction |
| `solana-client` | Solana chain interaction |
| `oracle-client` | Price oracle integration |
| `mev-client` | MEV protection and private mempool |
| `rules-enforcer` | On-chain rules enforcement |
| `core` | Shared types and utilities |
| `pyo3-bindings` | Python ↔ Rust bridge |

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
| Brain | Python 3.12 — agents, LLM, strategy, risk, news, tools |
| Muscle | Rust 1.79 — WebSocket, tick processing, order execution, MEV, gas |
| Specialist | C++ — QuantLib derivatives, FIX protocol, CUDA |
| Settlement | Solidity — On-chain kill switch, mandate, audit, governance |
| Database | SQLite + FTS5 — trade memory, lessons, patterns |
| Cache | Redis — regime state, real-time cache, event bus |
| Vectors | ChromaDB — pattern similarity search |
| Exchange | ccxt — 100+ exchanges |
| LLM | Ollama + DeepSeek + NVIDIA NIM |
| Agent Loop | OpenHarness — streaming tool-call cycle |
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
│   ├── agents/            # 12 agents (orchestrator, signal, risk, execution, news...)
│   ├── backends/          # Implementations
│   │   ├── python/        # ccxt, paper engine, LLM providers
│   │   ├── rust/          # Rust backend bindings
│   │   ├── defi/          # DEX execution, bridging, wallets, settlement
│   │   └── blockchain/    # On-chain rules enforcement
│   ├── bot/               # Telegram interactive bot
│   ├── comms/             # CloudEvents event bus
│   ├── education/         # Trade education module
│   ├── harness/           # OpenHarness agent loop
│   ├── interfaces/        # Abstract base classes (THE CONTRACT)
│   ├── knowledge/         # 6 stores + FTS5 + ChromaDB + knowledge graph
│   ├── news/              # News detection (Rust modules)
│   ├── risk/              # Risk engine, guards, mandate, watchdog, kill switch
│   ├── strategy/          # Strategies, backtest, factor library, ML scorer
│   ├── tools/             # 43 tools (news, DeFi, analysis, monitoring)
│   ├── llm/               # LLM routing, evaluation, token counting
│   ├── metrics/           # Prometheus export, improvement measurement
│   └── api/               # FastAPI REST + static dashboard
├── config/                 # YAML configuration
│   ├── tsar.yaml          # Main app config
│   ├── risk.yaml          # Risk parameters
│   ├── mandate.yaml       # Trading mandate
│   ├── models.yaml        # LLM model routing
│   ├── blockchain.yaml    # Blockchain rules config
│   └── signal_quality.yaml# Signal quality thresholds
├── rust/                   # Rust performance layer (14 crates)
│   └── crates/            # tick-processor, order-executor, mev-scanner, etc.
├── blockchain/             # On-chain settlement
│   ├── contracts/         # Solidity smart contracts (5 contracts)
│   ├── python-bridge/     # Python ↔ blockchain bridge
│   └── rust-bindings/     # Rust EVM bindings
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
| `.env.template` | Production environment template |
| `config/tsar.yaml` | Main app config (exchange, risk, LLM, strategy) |
| `config/risk.yaml` | Canonical risk parameters |
| `config/mandate.yaml` | Trading mandate — human authorization boundary |
| `config/models.yaml` | LLM model routing and fallbacks |
| `config/blockchain.yaml` | Blockchain rules and chain config |
| `config/signal_quality.yaml` | Signal quality thresholds |
| `config/backends.yaml` | Backend selection per interface |
| `config/default.yaml` | Application defaults (Redis, logging, API) |

---

## Trading Modes

| Mode | Risk | Use |
|------|------|-----|
| `paper` | $0 | Test strategies safely — simulated orders against live data |
| `live` | Real money | Only after 50+ paper trades, 7 days, 75% win rate, and active mandate |

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System architecture deep dive |
| [Deployment](docs/DEPLOYMENT.md) | Azure, Docker, and local deployment |
| [Installation](INSTALL.md) | Step-by-step setup guide |
| [Changelog](CHANGELOG.md) | Version history |
| [Telegram Architecture](docs/TELEGRAM_INTEGRATION_ARCHITECTURE.md) | Bot design and security |
| [News Detection](docs/NEWS_DETECTION_SYSTEM.md) | News pipeline architecture |
| [Blockchain Rules](blockchain/BLOCKCHAIN_RULES_REPORT.md) | On-chain governance design |
| [Mobile App](mobile/README.md) | Flutter app setup |
| [Council Reviews](docs/council/) | Architecture and quality reviews |
| [Research](docs/research/) | AI trading research reports |

---

## Current Status

```
 ✅ v0.1.0 — Core system, 12 agents, 6 knowledge stores, NVIDIA skills
 ✅ v0.2.0 — Full superagent wiring, DeFi integration, anti-loss system, Telegram bot
 ✅ v0.2.1 — Scenario prevention, paper trading gate, 14 Rust crates, win rate councils
 ✅ v0.2.2 — News gaps, on-chain rules, backend deployment, OpenHarness
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
