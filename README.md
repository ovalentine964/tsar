# TSAR — Trading Super Agent for Returns

> **Autonomous capital compounding under strict risk constraints.**

[![Architecture](https://img.shields.io/badge/Architecture-v3.0.0-green?style=for-badge)]()
[![Phases](https://img.shields.io/badge/Phases_1A--4-COMPLETE-green?style=for-badge)]()
[![Mobile](https://img.shields.io/badge/Mobile-Flutter-blue?style=for-badge)]()
[![NVIDIA](https://img.shields.io/badge/NVIDIA-Skills_Integrated-76B900?style=for-badge)]()
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-badge)]()
[![Status](https://img.shields.io/badge/Status-v0.6.0-green?style=for-badge)]()

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
 ✅ Engineering — Production hardening, deployment (v0.5.0)
 ✅ v0.6.0 — 72 issues fixed, 5 NVIDIA skills, 17 council reviews
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
│  ┌────┴─────┐  ┌─────┴─────┐  ┌────┴──────┐                   │
│  │ Flywheel │  │ Sentiment │  │ Regime    │                   │
│  │ Orch.    │  │ Agent     │  │ Detector  │                   │
│  └────┬─────┘  └─────┬─────┘  └────┬──────┘                   │
│       │              │              │                           │
│  ┌────┴──────────────┴──────────────┴──────────────────────┐   │
│  │              INTERFACE LAYER (the contract)              │   │
│  │  ExchangeGateway · PricingEngine · ExecutionEngine      │   │
│  │  RiskEngine · LLMProvider · BackendRegistry             │   │
│  └────┬──────────────┬──────────────┬──────────────────────┘   │
│       │              │              │                           │
│  ┌────┴─────┐  ┌─────┴────┐  ┌─────┴──────┐                   │
│  │ 6 Knowledge│  │ CloudEvents│ │ NVIDIA    │                   │
│  │ Stores    │  │ Messaging │  │ Skills    │                   │
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
| ExecutionEngine | ccxt REST + Paper | Order executor | FIX engine |
| RiskEngine | Python deterministic | Rust deterministic | GPU Monte Carlo |
| LLMProvider | Ollama + DeepSeek + NVIDIA NIM | — | — |

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
| **ChromaDB Store** | Vector similarity search for semantic pattern matching |
| **Knowledge Graph** | Cross-store graph traversal with recursive CTEs |
| **RAG Blueprint** | NVIDIA-enhanced retrieval with semantic chunking and reranking |

### 12 Agents

| Agent | Role |
|-------|------|
| Orchestrator | Coordinates all agents, main loop |
| **Flywheel Orchestrator** | Auto-triggers the self-improvement loop |
| Signal Scout | Finds statistical edges |
| Risk Guardian | VETO power, deterministic risk checks |
| Execution Sniper | Places and monitors orders |
| Regime Detector | Classifies market regime (HMM-based) |
| Trade Philosopher | Post-trade reflection and lessons |
| Strategy Geneticist | Evolves strategy genomes |
| Market Cartographer | Cross-asset correlation mapping |
| Execution Tracker | Fill quality and slippage analysis |
| Macro Agent | Economic context and sentiment |
| **Sentiment Agent** | Aggregates sentiment from CryptoPanic + Fear & Greed |

### 6 Knowledge Stores

| Store | Purpose |
|-------|---------|
| Trade Memory | Every trade with context, outcome, reflection |
| Strategy Genomes | Evolving strategy parameters and rules |
| Regime State | Real-time market regime probabilities |
| Pattern Library | Discovered patterns with statistical validation |
| Lesson Archive | Distilled wisdom from failures and successes |
| **ChromaDB** | Vector embeddings for semantic similarity search |

## NVIDIA Skills Integration (v0.6.0)

TSAR integrates 5 NVIDIA GPU-accelerated skills for enhanced trading intelligence:

| Skill | Purpose | Fallback |
|-------|---------|----------|
| **cuFOLIO** | GPU-accelerated portfolio optimization (Mean-CVaR, efficient frontier) | scipy |
| **cuOpt** | Multi-objective strategy parameter optimization | scipy.optimize |
| **RAG Blueprint** | Enhanced retrieval with semantic chunking + reranking | FTS5 + ChromaDB |
| **Nemo Evaluator** | LLM output quality scoring (factual accuracy, risk awareness) | Internal evaluator |
| **Nemotron Policy** | AI-generated adaptive risk policies | Static risk.yaml rules |

All skills degrade gracefully when GPU hardware is unavailable. See [`config/nvidia_skills.yaml`](config/nvidia_skills.yaml) for configuration.

## Security (v0.6.0)

- **JWT Authentication** — API endpoints protected with token-based auth
- **CORS Fix** — Strict origin validation via `TSAR_CORS_ORIGINS`
- **Telegram Auth** — Chat ID verification for bot commands
- **Watchdog** — External process health monitor for kill switch reliability
- **Kill Switch** — Dual-write (file + Redis) with stale-process detection

## Risk Management

- **Micro-capital mode** — Adjusted parameters for accounts under $50
- **Fee-aware sizing** — Kelly calculation accounts for exchange fees
- **Phased recovery** — Graduated re-entry after circuit breaker trips
- **Anti-behavioral guards** — Revenge, greed, FOMO, overconfidence protection
- **Economic blackout** — Auto-block trading around FOMC, CPI, NFP events

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

## Quick Start (5 Minutes)

```bash
# 1. Clone
git clone https://github.com/ovalentine964/tsar.git && cd tsar

# 2. Configure (fill in your API keys)
cp .env.example .env && nano .env

# 3. Start
./quickstart.sh

# 4. Open on your phone
# http://YOUR_SERVER:8000/app
```

**See [INSTALL.md](INSTALL.md) for detailed setup guide.**

## Access on Your Phone

| Method | How |
|--------|-----|
| 📱 **Web Dashboard** | Open `http://YOUR_SERVER:8000/app` in phone browser |
| 📲 **Flutter APK** | Download from [GitHub Releases](../../releases) |
| 💬 **Telegram** | Send `/status` to your bot |

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
| LLM | Ollama + DeepSeek + NVIDIA NIM | Multi-provider routing |
| ML | XGBoost / LightGBM | Signal scoring |
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
│   │   └── python/              # ccxt, paper engine, cuFOLIO, providers
│   ├── agents/                  # 12 agents (incl. flywheel, sentiment)
│   ├── knowledge/               # 6 stores + FTS5 + ChromaDB + knowledge graph
│   ├── risk/                    # Risk engine + guards + mandate + watchdog
│   ├── strategy/                # Strategies + backtest + cuOpt + ML scorer
│   ├── llm/                     # LLM routing + evaluation + token counting
│   ├── comms/                   # CloudEvents messaging
│   ├── metrics/                 # Prometheus export + improvement measurement
│   ├── resources/               # Resource enforcement
│   ├── api/                     # FastAPI endpoints + static dashboard
│   └── bot/                     # Telegram commands
├── config/                       # Configuration
│   ├── tsar.yaml                # Main config (working defaults)
│   ├── mandate.yaml             # Trading mandate (human authorization)
│   ├── risk.yaml                # Risk parameters (canonical)
│   ├── models.yaml              # LLM model routing (incl. NVIDIA NIM)
│   ├── nvidia_skills.yaml       # NVIDIA skills configuration
│   └── strategies/              # Strategy genomes
├── mobile/                       # Flutter mobile app
├── rust/                         # Rust performance layer
├── cpp/                          # C++ specialist layer (Level 3+)
├── tests/                        # Test suite
├── migrations/                   # Database migrations
├── grafana/                      # Grafana dashboards + provisioning
├── monitoring/                   # Prometheus config
├── scripts/                      # Utility scripts
├── docs/                         # Documentation
│   ├── architecture/            # Architecture specs
│   ├── council/                 # Original council reviews
│   ├── nvidia/                  # NVIDIA integration docs
│   └── research/                # 14 research reports
├── council_reviews/              # 17 council reviews + 12 fix team reports
│   └── fix_teams/               # Fix team summaries
├── analysis/                     # Analysis & fix specs
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
| `config/risk.yaml` | Risk parameters — limits, guards, kill switch (canonical) |
| `config/models.yaml` | LLM model routing and fallbacks (incl. NVIDIA NIM) |
| `config/nvidia_skills.yaml` | NVIDIA GPU skill configuration |
| `config/backends.yaml` | Backend selection per interface |

## Documentation

- [TSAR Architecture v3.0.0](docs/architecture/TSAR_ARCHITECTURE.md) — Single source of truth
- [Council Reviews](council_reviews/) — 17 council reviews, 72 issues fixed
- [Fix Team Reports](council_reviews/fix_teams/) — 12 fix team summaries
- [NVIDIA Integration](docs/nvidia/) — NVIDIA skills setup and evaluation
- [Research Analysis](analysis/RESEARCH_ANALYSIS.md) — 14 reports analyzed
- [Fix Reports](analysis/fixes/) — Fix specs (A through G)
- [Mobile App](mobile/README.md) — Flutter app setup and API docs
- [Changelog](CHANGELOG.md) — Build history

## Markets

- **Crypto:** Binance (BTC, ETH, SOL) — Live via ccxt + WebSocket

### Coming Soon

| Market | Integration | Status |
|--------|------------|--------|
| Futures | Binance Futures | 🚧 Planned |
| Options | Deribit | 🚧 Planned |

## License

MIT — see [LICENSE](LICENSE)

---

*Built by Valentine Owuor. Powered by AI. Designed for retail traders.*
*Architecture reviewed by 17 councils against Jensen Huang's super agent vision.*
*72 issues fixed. 5 NVIDIA skills integrated. System ready for paper trading.*
*Future-ready: Python + Rust + C++ from day one. No swapping later.*
