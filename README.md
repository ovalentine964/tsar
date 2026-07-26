# TSAR — Trading Super Agent for Returns

> **Autonomous capital compounding under strict risk constraints.**

[![Architecture](https://img.shields.io/badge/Architecture-v3.0.0-green?style=for-badge)]()
[![Phases](https://img.shields.io/badge/Phases_1A--4-COMPLETE-green?style=for-badge)]()
[![Mobile](https://img.shields.io/badge/Mobile-Flutter-blue?style=for-badge)]()
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-badge)]()
[![Status](https://img.shields.io/badge/Status-Integration_Wiring_Complete-yellow?style=for-badge)]()

## What Is TSAR?

TSAR is a **self-improving market intelligence system** — not a trading bot, not a multi-agent system. It is a **super agent**: a single, deep, domain-specific intelligence wrapped in a harness that compounds knowledge through use.

**One job:** Autonomous capital compounding under strict risk constraints.

**The difference:** A trading bot is static code. A multi-agent system resets between tasks. TSAR compounds. Every trade generates proprietary data. Every reflection improves the system. Every adaptation makes the next trade better.

> *"You can copy a bot's code. You cannot copy a super agent's knowledge."*

## The Flywheel

```
TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE
  ↑                                                │
  └────────────────────────────────────────────────┘
```

## Status

```
 ✅ Phase 1A — FTS5 full-text search across all knowledge stores
 ✅ Phase 1B — Shadow Account (paper trading mirror with lesson extraction)
 ✅ Phase 2   — Backtest Engine (walk-forward, Monte Carlo, factor benchmarking)
 ✅ Phase 3   — Mandate Gate (human authorization boundary for live trading)
 ✅ Phase 4   — Factor Library (IC/IR scoring, category taxonomy, strategy factors)
 ✅ Integration Wiring — All components connected via CloudEvents + FastAPI
 ✅ Mobile App — Flutter app with full API integration (28+ endpoints)
 ⬜ Engineering — Production hardening, deployment
 ⬜ Live Trading — Paper validation → live with mandate
```

## Architecture (v3.0.0)

Future-ready from day one. Python + Rust + C++ via abstract interfaces.

```
┌─────────────────────────────────────────────────────────────────┐
│                    TSAR SUPER AGENT                             │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Signal   │  │ Risk     │  │ Execution│  │ Trade    │       │
│  │ Scout    │→ │ Guardian │→ │ Sniper   │  │ Philosopher│      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────────┘       │
│       │              │              │                           │
│  ┌────┴──────────────┴──────────────┴──────────────────────┐   │
│  │              INTERFACE LAYER (the contract)              │   │
│  │  ExchangeGateway · PricingEngine · ExecutionEngine      │   │
│  │  RiskEngine · LLMProvider · BackendRegistry             │   │
│  └────┬──────────────┬──────────────┬──────────────────────┘   │
│       │              │              │                           │
│  ┌────┴─────┐  ┌─────┴────┐  ┌─────┴──────┐                   │
│  │ 5 Knowledge│  │ CloudEvents│ │ Improvement│                  │
│  │ Stores    │  │ Messaging │  │ Measurement│                  │
│  └──────────┘  └──────────┘  └────────────┘                   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           BACKEND REGISTRY (config-driven)               │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                  │  │
│  │  │ Python  │  │  Rust   │  │  C++    │                  │  │
│  │  │ (Day 1) │  │ (Lv. 2) │  │ (Lv. 3+)│                  │  │
│  │  └─────────┘  └─────────┘  └─────────┘                  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE   │
└─────────────────────────────────────────────────────────────────┘
```

### The Interface Layer

5 abstract base classes. The interface is the contract. The backend is an implementation detail.

| Interface | Python (Day 1) | Rust (Level 2) | C++ (Level 3+) |
|-----------|---------------|----------------|----------------|
| ExchangeGateway | ccxt REST | WebSocket | FIX protocol |
| PricingEngine | pandas-ta | Tick processor | QuantLib |
| ExecutionEngine | ccxt REST | Order executor | FIX engine |
| RiskEngine | Python deterministic | Rust deterministic | GPU Monte Carlo |
| LLMProvider | Ollama + DeepSeek | — | — |

**Agent code calls the interface. YAML config selects the backend. No refactoring ever.**

## Components

### Core Systems

| Component | Description |
|-----------|-------------|
| **FTS5 Search** | Full-text search across trade memory, lessons, patterns, and genomes |
| **Shadow Account** | Paper trading mirror that extracts lessons from hypothetical trades |
| **Backtest Engine** | Walk-forward validation, Monte Carlo simulation, factor benchmarking |
| **Mandate Gate** | Human authorization boundary — no live trading without a committed mandate |
| **Factor Library** | IC/IR scoring, category taxonomy, alpha factor discovery and ranking |

### 10 Agents

| Agent | Role |
|-------|------|
| Orchestrator | Coordinates all agents, main loop |
| Signal Scout | Finds statistical edges |
| Risk Guardian | VETO power, deterministic risk checks |
| Execution Sniper | Places and monitors orders |
| Regime Detector | Classifies market regime |
| Trade Philosopher | Post-trade reflection and lessons |
| Strategy Geneticist | Evolves strategy genomes |
| Market Cartographer | Cross-asset correlation mapping |
| Execution Tracker | Fill quality and slippage analysis |
| Macro Agent | Economic context and sentiment |

### 5 Knowledge Stores

| Store | Purpose |
|-------|---------|
| Trade Memory | Every trade with context, outcome, reflection |
| Strategy Genomes | Evolving strategy parameters and rules |
| Regime State | Real-time market regime probabilities |
| Pattern Library | Discovered patterns with statistical validation |
| Lesson Archive | Distilled wisdom from failures and successes |

## Mobile App

A Flutter mobile app for monitoring and controlling TSAR from anywhere.

| Feature | Description |
|---------|-------------|
| Dashboard | Real-time P&L, win rate, equity curve, market regime, flywheel health |
| Trades | History with symbol/status filters, infinite scroll, detail sheets |
| Risk & Portfolio | Risk gauges, circuit breaker, open positions, alerts |
| Factors | Library browser with category filter, IC/IR rankings |
| Kill Switch | Floating action button with biometric confirmation |
| Knowledge Search | FTS5 search across all knowledge stores |

**Theme:** Dark terminal aesthetic — green (#00C853) for profit, red (#FF1744) for loss, JetBrains Mono for financial data.

```bash
cd mobile/
flutter pub get
flutter run
```

See [mobile/README.md](mobile/README.md) for full setup and API integration details.

### Download

Pre-built APK available on [GitHub Releases](../../releases).

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Brain | Python 3.12 | Agent orchestration, LLM, strategy, risk |
| Muscle | Rust 1.79 | WebSocket, tick processing, order execution |
| Specialist | C++ (Level 3+) | QuantLib derivatives, FIX protocol, CUDA |
| Bridge | PyO3 + C FFI | Python ↔ Rust ↔ C++ interop |
| Database | SQLite + FTS5 | Trade memory, lessons, patterns |
| Cache | Redis | Regime state, real-time cache |
| Vectors | ChromaDB | Pattern similarity search |
| Exchange | ccxt | 100+ exchanges |
| LLM | LiteLLM + Ollama + DeepSeek-R1 | Model-agnostic routing |
| API | FastAPI | REST + WebSocket (port 8000) |
| Mobile | Flutter + Dart | Cross-platform mobile app |
| Telegram | python-telegram-bot | Commands + alerts |
| Monitoring | Prometheus + Grafana | Metrics + dashboards |
| Messaging | CloudEvents v1.0 | Standard event protocol |
| Container | Docker Compose | Full stack orchestration |
| CI/CD | GitHub Actions | lint → test → build → deploy |

## Project Structure

```
tsar/
├── src/                          # Python source
│   ├── interfaces/              # Abstract base classes (THE CONTRACT)
│   ├── backends/                # Implementations (Python/Rust/C++)
│   ├── agents/                  # 10 agents
│   ├── knowledge/               # 5 knowledge stores + FTS5 + shadow account
│   ├── risk/                    # Risk engine + guards + mandate gate
│   ├── strategy/                # Strategies + backtest + factor library
│   ├── llm/                     # LLM routing
│   ├── comms/                   # CloudEvents messaging
│   ├── metrics/                 # Improvement measurement
│   ├── resources/               # Resource enforcement
│   ├── api/                     # FastAPI endpoints
│   └── bot/                     # Telegram commands
├── mobile/                       # Flutter mobile app
│   └── lib/
│       ├── models/              # Data models
│       ├── services/            # API client (28+ endpoints)
│       ├── providers/           # State management
│       ├── screens/             # Dashboard, Trades, Risk, Factors, Settings
│       └── widgets/             # Cards, charts, kill switch FAB
├── rust/                         # Rust performance layer
│   └── crates/
│       ├── ws-manager/          # WebSocket connections
│       ├── tick-processor/      # OHLCV aggregation
│       ├── order-executor/      # Low-latency execution
│       └── pyo3-bindings/       # Python bridge
├── cpp/                          # C++ specialist layer (Level 3+)
│   ├── quantlib-pricing/        # Derivatives pricing
│   ├── fix-engine/              # FIX protocol
│   └── cuda-kernels/            # GPU acceleration
├── config/                       # Configuration
│   ├── tsar.yaml                # Main config (working defaults)
│   ├── mandate.yaml             # Trading mandate (human authorization)
│   ├── backends.yaml            # Backend selection
│   ├── models.yaml              # LLM model config
│   ├── risk.yaml                # Risk parameters
│   └── strategies/              # Strategy genomes
├── tests/                        # Test suite
├── migrations/                   # Database migrations
├── grafana/                      # Dashboards
├── docs/                         # Documentation
│   ├── research/                # 14 research reports
│   ├── architecture/            # Architecture specs
│   ├── council/                 # Council reviews
│   └── reviews/                 # Architecture reviews
├── analysis/                     # Analysis & research
│   └── fixes/                   # Fix specs
├── docker-compose.yml
├── pyproject.toml
├── Makefile
└── README.md
```

## Quick Start

```bash
# Clone and setup
git clone <repo-url> && cd tsar
make setup          # Install deps, create DB, verify

# Run (paper mode)
python3 -m src --paper

# Run tests
make test

# Docker
docker-compose up -d
```

## Configuration

| File | Purpose |
|------|---------|
| `config/tsar.yaml` | Main config — exchange, risk, LLM, strategy defaults |
| `config/mandate.yaml` | Trading mandate — human authorization boundary |
| `config/risk.yaml` | Risk parameters — limits, guards, kill switch |
| `config/models.yaml` | LLM model routing and fallbacks |
| `config/backends.yaml` | Backend selection per interface |

## Documentation

- [TSAR Architecture v3.0.0](docs/architecture/TSAR_ARCHITECTURE.md) — Single source of truth
- [Research Analysis](analysis/RESEARCH_ANALYSIS.md) — 14 reports analyzed
- [Council Reviews](docs/council/) — 4 members, 55 issues fixed
- [Fix Reports](analysis/fixes/) — 7 fix specs (A through G)
- [Mobile App](mobile/README.md) — Flutter app setup and API docs
- [Changelog](CHANGELOG.md) — Build history

## Markets

- **Crypto:** Binance (BTC, ETH, SOL)
- **Gold:** OANDA via MT5 (XAU/USD)
- **Forex:** OANDA via MT5 (EUR/USD, GBP/USD)

## License

MIT — see [LICENSE](LICENSE)

---

*Built by Valentine Owuor. Powered by AI. Designed for retail traders.*
*Architecture reviewed against Jensen Huang's super agent vision — passes all 10 criteria.*
*Future-ready: Python + Rust + C++ from day one. No swapping later.*
