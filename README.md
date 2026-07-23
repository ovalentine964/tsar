# TSAR — Trading Super Agent for Returns

> **Autonomous capital compounding under strict risk constraints.**

[![Architecture](https://img.shields.io/badge/Architecture-Complete-green?style=for-badge)]()
[![Super Agent](https://img.shields.io/badge/Super%20Agent-PASS_8.8/10-green?style=for-badge)]()
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-badge)]()
[![Status](https://img.shields.io/badge/Status-Ready_for_Engineering-yellow?style=for-badge)]()

## What Is TSAR?

TSAR is a **self-improving market intelligence system** — not a trading bot, not a multi-agent system. It is a **super agent**: a single, deep, domain-specific intelligence wrapped in a harness that compounds knowledge through use.

**One job:** Autonomous capital compounding under strict risk constraints.

**The difference:** A trading bot is static code. A multi-agent system resets between tasks. TSAR compounds. Every trade generates proprietary data. Every reflection improves the system. Every adaptation makes the next trade better. After 10,000 trades, the knowledge base IS the edge.

> *"You can copy a bot's code. You cannot copy a super agent's knowledge."*

## The Flywheel

```
TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE
  ↑                                                │
  └────────────────────────────────────────────────┘
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    TSAR SUPER AGENT                      │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Signal   │  │ Risk     │  │ Execution│             │
│  │ Scout    │→ │ Guardian │→ │ Sniper   │             │
│  │          │  │ (VETO)   │  │          │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│       │              │              │                   │
│  ┌────┴──────────────┴──────────────┴──────────────┐   │
│  │              HARNESS (the product)               │   │
│  │  Iteration Loop · Context Management · Tools     │   │
│  │  Session Persistence · Safeguards · Permissions  │   │
│  └────┬──────────────┬──────────────┬──────────────┘   │
│       │              │              │                   │
│  ┌────┴─────┐  ┌─────┴────┐  ┌─────┴──────┐           │
│  │ 5 Knowledge│  │ LLM     │  │ Rust      │           │
│  │ Stores    │  │ Router   │  │ Performance│           │
│  └──────────┘  └──────────┘  └────────────┘           │
│                                                         │
│  TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → REPEAT  │
└─────────────────────────────────────────────────────────┘
```

### 10 Agents

| Agent | Role | Language |
|-------|------|----------|
| Orchestrator | Coordinates all agents, main loop | Python |
| Signal Scout | Finds statistical edges | Python |
| Risk Guardian | VETO power, deterministic risk checks | Python |
| Execution Sniper | Places and monitors orders | Rust/Python |
| Regime Detector | Classifies market regime | Python/Rust |
| Trade Philosopher | Post-trade reflection and lessons | Python (LLM) |
| Strategy Geneticist | Evolves strategy genomes | Python (LLM) |
| Market Cartographer | Cross-asset correlation mapping | Python |
| Execution Tracker | Fill quality and slippage analysis | Rust |
| Macro Agent | Economic context and sentiment | Python (LLM) |

### 5 Knowledge Stores

| Store | Purpose | Format |
|-------|---------|--------|
| Trade Memory | Every trade with context, outcome, reflection | SQLite + FTS5 |
| Strategy Genomes | Evolving strategy parameters and rules | YAML |
| Regime State | Real-time market regime probabilities | Redis |
| Pattern Library | Discovered patterns with statistical validation | SQLite + ChromaDB |
| Lesson Archive | Distilled wisdom from failures and successes | SQLite + FTS5 |

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Brain | Python 3.12 | Agent orchestration, LLM, strategy, risk |
| Muscle | Rust 1.79 | WebSocket, tick processing, order execution |
| Bridge | PyO3 | Python ↔ Rust zero-copy interop |
| Database | SQLite + FTS5 | Trade memory, lessons, patterns |
| Cache | Redis | Regime state, real-time cache |
| Vectors | ChromaDB | Pattern similarity search |
| Exchange | ccxt | 100+ exchanges |
| LLM | LiteLLM + Ollama + DeepSeek-R1 | Model-agnostic routing |
| API | FastAPI | REST + WebSocket (port 8000) |
| Telegram | python-telegram-bot | Commands + alerts |
| Monitoring | Prometheus + Grafana | Metrics + dashboards |
| Container | Docker Compose | 5 services |
| CI/CD | GitHub Actions | lint → test → build → deploy |

## Super Agent Scorecard

Reviewed against Jensen Huang's super agent vision (10 capabilities):

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

TSAR passes all 10 criteria of the Super Agent Test.

## Council Verdict

4 specialized council members reviewed the architecture:

| Member | Verdict | Score |
|--------|---------|-------|
| Chief Architect | CONDITIONAL PASS | 8.4/10 |
| Chief Risk Officer | CONDITIONAL PASS | 7.5/10 |
| Chief Strategist | CONDITIONAL PASS | — |
| Chief Engineer | CONDITIONAL PASS | — |

**55 issues found. All addressed by fixing team.**

## Tech Stack (Final)

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
| Container | Docker Compose | Full stack orchestration |
| CI/CD | GitHub Actions | lint → test → build → deploy |

### Hybrid Architecture Path

```
Python (Day1) → +Rust (Level 2) → +C++ (Level 3+)
```

C++ enters when capital reaches $10K+ (QuantLib for derivatives, FIX for forex).

## Project Structure

```
tsar/
├── docs/                         # Documentation
│   ├── research/                 # 14 research reports
│   ├── architecture/             # 17 architecture specs
│   └── reviews/                  # 3 architect reviews
├── analysis/                     # Analysis & fix reports
│   ├── RESEARCH_ANALYSIS.md     # 14-file research deep-dive
│   ├── ARCHITECTURE_ANALYSIS.md # 20-file architecture analysis
│   ├── SUPER_AGENT_CAPABILITY_REPORT.md
│   ├── SUPER_AGENT_ARCHITECTURE_REVIEW.md
│   ├── ARCHITECTURE_FIXES.md    # Consolidated fix report
│   └── fixes/                   # 5 detailed fix specs
│       ├── FIX_01_LLM_ABSTRACTION.md
│       ├── FIX_02_CONFIGURABLE_MODELS.md
│       ├── FIX_03_CLOUDEVENTS.md
│       ├── FIX_04_IMPROVEMENT_MEASUREMENT.md
│       └── FIX_05_RESOURCE_LIMITS.md
├── src/                          # Source code (ready for engineering)
│   ├── core/                    # Engine, events, state, types
│   ├── exchange/                # ccxt adapters
│   ├── strategy/                # 5 strategies + custom indicators
│   ├── risk/                    # Position sizer, drawdown, exposure
│   ├── backtest/                # vectorbt engine
│   ├── llm/                     # Model-agnostic router
│   ├── data/                    # SQLite, Redis, ChromaDB
│   ├── api/                     # FastAPI routes
│   ├── bot/                     # Telegram commands
│   ├── tasks/                   # Background jobs
│   ├── monitoring/              # Prometheus metrics
│   └── utils/                   # Config, logging, math
├── rust/                         # Rust performance layer
│   └── crates/
│       ├── core/                # Shared types
│       ├── ws-manager/          # WebSocket connections
│       ├── tick-processor/      # OHLCV aggregation
│       ├── order-executor/      # Low-latency execution
│       └── pyo3-bindings/       # Python bridge
├── config/                       # Configuration files
│   ├── default.yaml
│   ├── models.yaml              # LLM provider config
│   ├── risk.yaml                # Risk management rules
│   └── strategies/              # Strategy definitions
├── tests/                        # Test suite
├── migrations/                   # Database migrations
├── grafana/                      # Grafana dashboards
├── scripts/                      # Utility scripts
├── pyproject.toml                # Python dependencies
├── Cargo.toml                    # Rust dependencies
├── docker-compose.yml            # Full stack orchestration
├── Makefile                      # Common commands
└── README.md                     # This file
```

## Markets

- **Crypto:** Binance (BTC, ETH, SOL)
- **Gold:** OANDA via MT5 (XAU/USD)
- **Forex:** OANDA via MT5 (EUR/USD, GBP/USD)

## Documentation

### Research (14 reports)
- [Research Analysis](analysis/RESEARCH_ANALYSIS.md) — Consolidated research findings
- [Validation Complete](docs/research/VALIDATION_COMPLETE.md) — Executive summary

### Architecture (17 specs)
- [Architecture Analysis](analysis/ARCHITECTURE_ANALYSIS.md) — Consolidated architecture review
- [TSAR Architecture](docs/architecture/TSAR_ARCHITECTURE.md) — Canonical source of truth
- [Architecture Consolidation](docs/architecture/ARCHITECTURE_CONSOLIDATION.md) — Canonical values
- [Risk Architecture](docs/architecture/RISK_ARCHITECTURE.md) — Risk governor (most critical)

### Super Agent Review
- [Super Agent Capability Report](analysis/SUPER_AGENT_CAPABILITY_REPORT.md) — 10-capability definition
- [Super Agent Architecture Review](analysis/SUPER_AGENT_ARCHITECTURE_REVIEW.md) — 8.1/10 → 8.8/10

### Architecture Fixes
- [Architecture Fixes](analysis/ARCHITECTURE_FIXES.md) — Consolidated fix report
- [Fix 01: LLM Abstraction](analysis/fixes/FIX_01_LLM_ABSTRACTION.md) — Model-agnostic provider layer
- [Fix 02: Configurable Models](analysis/fixes/FIX_02_CONFIGURABLE_MODELS.md) — YAML-driven model config
- [Fix 03: CloudEvents](analysis/fixes/FIX_03_CLOUDEVENTS.md) — Standard messaging protocol
- [Fix 04: Improvement Measurement](analysis/fixes/FIX_04_IMPROVEMENT_MEASUREMENT.md) — Flywheel health tracking
- [Fix 05: Resource Limits](analysis/fixes/FIX_05_RESOURCE_LIMITS.md) — Tool resource enforcement

### Council Reviews
- [Council Issues](analysis/council/COUNCIL_ISSUES.md) — 55 issues catalogued
- [Chief Architect Review](analysis/council/CHIEF_ARCHITECT_REVIEW.md) — System design assessment
- [Chief Risk Officer Review](analysis/council/CHIEF_RISK_OFFICER_REVIEW.md) — Safety assessment
- [Chief Strategist Review](analysis/council/CHIEF_STRATEGIST_REVIEW.md) — Trading alpha assessment
- [Chief Engineer Review](analysis/council/CHIEF_ENGINEER_REVIEW.md) — Buildability assessment

### Hybrid Architecture Reviews
- [Hybrid Architect Review](analysis/council/HYBRID_ARCHITECT_REVIEW.md) — Rust + C++ integration
- [Hybrid Risk Review](analysis/council/HYBRID_RISK_REVIEW.md) — C++ safety in money systems
- [Hybrid Strategy Review](analysis/council/HYBRID_STRATEGY_REVIEW.md) — QuantLib/FIX/CUDA value
- [Hybrid Engineer Review](analysis/council/HYBRID_ENGINEER_REVIEW.md) — Build system complexity

### Council Fix Reports
- [Fix A: Parameters](analysis/fixes/FIX_A_PARAMETERS.md) — 18 cross-doc conflicts resolved
- [Fix B: Day30 Architecture](analysis/fixes/FIX_B_DAY30.md) — Intermediate build stage
- [Fix C: Day1 Simplified](analysis/fixes/FIX_C_DAY1_SIMPLE.md) — 25 files, zero Rust
- [Fix D: Risk Hardening](analysis/fixes/FIX_D_RISK_HARDENING.md) — Kill switch fallback, stress tests
- [Fix E: Strategy Updates](analysis/fixes/FIX_E_STRATEGY.md) — Momentum, funding rates, walk-forward
- [Fix F: Dependencies](analysis/fixes/FIX_F_DEPENDENCIES.md) — 19 packages, each justified

## Status

```
1. ✅ VALIDATE    — COMPLETE (14 research reports)
2. ✅ ARCHITECT   — COMPLETE (17 specs + 3 reviews)
3. ✅ REVIEW      — COMPLETE (Super Agent Test: PASS 8.8/10)
4. ✅ COUNCIL     — COMPLETE (4 members, 55 issues found & fixed)
5. ✅ FIX GAPS    — COMPLETE (6 fix specs + hybrid architecture approved)
6. ⬜ ENGINEER    — Ready to start
7. ⬜ REVIEW & TEST
8. ⬜ DEPLOY
```

## License

MIT

---

*Built by Valentine Owuor. Powered by AI. Designed for retail traders.*
*Architecture reviewed against Jensen Huang's super agent vision — passes all 10 criteria.*
