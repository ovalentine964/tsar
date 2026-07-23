# TSAR — Trading Super Agent for Returns

> **Autonomous capital compounding under strict risk constraints.**

[![Architecture](https://img.shields.io/badge/Architecture-v3.0.0-green?style=for-badge)]()
[![Super Agent](https://img.shields.io/badge/Super%20Agent-PASS_8.8/10-green?style=for-badge)]()
[![Future Ready](https://img.shields.io/badge/Future%20Ready-Python%2BRust%2BC++-blue?style=for-badge)]()
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-badge)]()
[![Status](https://img.shields.io/badge/Status-Ready_for_Engineering-yellow?style=for-badge)]()

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
| Telegram | python-telegram-bot | Commands + alerts |
| Monitoring | Prometheus + Grafana | Metrics + dashboards |
| Messaging | CloudEvents v1.0 | Standard event protocol |
| Container | Docker Compose | Full stack orchestration |
| CI/CD | GitHub Actions | lint → test → build → deploy |

## Super Agent Scorecard

| Capability | Score | Status |
|-----------|-------|--------|
| Harness | 9/10 | ✅ Strong |
| Knowledge Grounding | 9/10 | ✅ Strong |
| Tool Use | 9/10 | ✅ Strong |
| Memory Management | 9/10 | ✅ Strong |
| Safeguards | 9.5/10 | ✅ Exceptional |
| Iteration | 8/10 | ✅ Good |
| Domain Expertise | 8.5/10 | ✅ Strong |
| Self-Improvement | 9/10 | ✅ Strong |
| Model Agnosticism | 8.5/10 | ✅ Fixed |
| Open Ecosystem | 7.5/10 | ✅ Fixed |
| **Overall** | **8.8/10** | **PASS** |

## Council Verdict

| Member | Verdict | Score |
|--------|---------|-------|
| Chief Architect | CONDITIONAL PASS | 8.4/10 |
| Chief Risk Officer | CONDITIONAL PASS | 7.5/10 |
| Chief Strategist | CONDITIONAL PASS | — |
| Chief Engineer | CONDITIONAL PASS | — |

**55 issues found. All addressed.**

## Markets

- **Crypto:** Binance (BTC, ETH, SOL)
- **Gold:** OANDA via MT5 (XAU/USD)
- **Forex:** OANDA via MT5 (EUR/USD, GBP/USD)

## Project Structure

```
tsar/
├── src/                          # Python source
│   ├── interfaces/              # Abstract base classes (THE CONTRACT)
│   │   ├── exchange_gateway.py
│   │   ├── pricing_engine.py
│   │   ├── execution_engine.py
│   │   ├── risk_engine.py
│   │   ├── llm_provider.py
│   │   └── backend_registry.py
│   ├── backends/                # Implementations
│   │   ├── python/              # Day 1 backends
│   │   ├── rust/                # Level 2 backends (via PyO3)
│   │   └── cpp/                 # Level 3+ backends (via C FFI)
│   ├── agents/                  # 10 agents
│   ├── knowledge/               # 5 knowledge stores
│   ├── risk/                    # Risk engine + guards
│   ├── strategy/                # Strategies + evolution
│   ├── llm/                     # LLM routing
│   ├── comms/                   # CloudEvents messaging
│   ├── metrics/                 # Improvement measurement
│   ├── resources/               # Resource enforcement
│   ├── api/                     # FastAPI endpoints
│   └── bot/                     # Telegram commands
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
│   └── reviews/                 # Council reviews
├── analysis/                     # Analysis & fixes
│   ├── council/                 # Council reviews
│   └── fixes/                   # Fix specs
├── docker-compose.yml
├── pyproject.toml
├── Cargo.toml
├── Makefile
└── README.md
```

## Documentation

- [TSAR Architecture v3.0.0](docs/architecture/TSAR_ARCHITECTURE.md) — Single source of truth
- [Research Analysis](analysis/RESEARCH_ANALYSIS.md) — 14 reports analyzed
- [Super Agent Capability Report](analysis/SUPER_AGENT_CAPABILITY_REPORT.md) — 10-criteria test
- [Council Reviews](analysis/council/) — 4 members, 55 issues fixed
- [Fix Reports](analysis/fixes/) — 7 fix specs (A through G)

## Status

```
1. ✅ VALIDATE    — COMPLETE (14 research reports)
2. ✅ ARCHITECT   — COMPLETE (v3.0.0 — future-ready, Python+Rust+C++)
3. ✅ REVIEW      — COMPLETE (Super Agent Test: PASS 8.8/10)
4. ✅ COUNCIL     — COMPLETE (4 members, 55 issues found & fixed)
5. ✅ FIX GAPS    — COMPLETE (7 fix specs + hybrid architecture approved)
6. ✅ INTERFACES  — COMPLETE (5 ABCs, BackendRegistry, config-driven)
7. ⬜ ENGINEER    — Council designing engineering team
8. ⬜ REVIEW & TEST
9. ⬜ DEPLOY
```

## License

MIT

---

*Built by Valentine Owuor. Powered by AI. Designed for retail traders.*
*Architecture reviewed against Jensen Huang's super agent vision — passes all 10 criteria.*
*Future-ready: Python + Rust + C++ from day one. No swapping later.*
