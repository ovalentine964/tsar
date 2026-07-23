# ENGINEERING SWARM PLAN
## TSAR Build Agent Coordination Design

**Author:** Chief Engineer, TSAR Council
**Date:** 2026-07-24
**Version:** 1.0.0
**Authority:** This document defines how AI agents coordinate to build TSAR from spec to running code.
**Reference:** TSAR_ARCHITECTURE.md v3.0.0

---

## TABLE OF CONTENTS

1. [Swarm Topology](#1-swarm-topology)
2. [Agent Specialization](#2-agent-specialization)
3. [File Ownership](#3-file-ownership)
4. [Build Pipeline](#4-build-pipeline)
5. [Verification Protocol](#5-verification-protocol)
6. [Execution Schedule](#6-execution-schedule)

---

## 1. SWARM TOPOLOGY

### 1.1 Decision: Hybrid — Hub-and-Spoke + Pipeline

TSAR's architecture has two distinct properties that demand a hybrid topology:

1. **Deep dependency chains** (interfaces → backends → agents → integration) — demands pipeline ordering
2. **Wide parallel modules** (5 knowledge stores, 10 agents, 35 tools) — demands parallel fan-out

Neither pure topology works alone:
- Pure pipeline: Wastes time serializing independent modules (e.g., 5 knowledge stores built sequentially)
- Pure parallel: Breaks on dependency chains (agents can't be built before interfaces exist)
- Pure hub-and-spoke: Single coordinator becomes bottleneck and single point of failure

### 1.2 The Hybrid Model: Phased Fan-Out

```
PHASE 0: SCAFFOLD (coordinator alone)
    │
    ▼
PHASE 1: FOUNDATIONS (hub dispatches to 3 parallel streams)
    │
    ├──► Stream A: Interfaces + Registry
    ├──► Stream B: Data Layer (models, DB schema, migrations)
    └──► Stream C: Config + Infrastructure (YAML configs, Docker skeleton)
    │
    ▼ (gate: all 3 streams complete)
    │
PHASE 2: BACKENDS (hub dispatches to 5 parallel agents)
    │
    ├──► Agent α: CcxtGateway + CcxtExecEngine
    ├──► Agent β: PandasTAEngine
    ├──► Agent γ: PyRiskEngine
    ├──► Agent δ: OllamaProvider + ModelRouter
    └──► Agent ε: CloudEvents + Redis transport
    │
    ▼ (gate: all backends import-clean + unit tests pass)
    │
PHASE 3: AGENTS (hub dispatches in 3 waves)
    │
    ├──► Wave 1 (parallel): Signal Scout, Risk Guardian, Execution Sniper
    ├──► Wave 2 (parallel): Orchestrator, Execution Tracker
    └──► Wave 3 (parallel): Macro Agent, Regime Detector, Trade Philosopher,
    │                       Strategy Geneticist, Market Cartographer
    │
    ▼ (gate: all agents instantiate + publish/subscribe verified)
    │
PHASE 4: KNOWLEDGE + RISK + STRATEGIES (parallel)
    │
    ├──► Agent κ: Knowledge stores (5 schemas + migrations + DAO layer)
    ├──► Agent λ: Risk engine hardening (kill switch, watchdog, circuit breakers)
    └──► Agent μ: Strategies (Mean Reversion + Momentum)
    │
    ▼ (gate: integration tests pass end-to-end)
    │
PHASE 5: INTEGRATION + DEPLOYMENT (pipeline)
    │
    Step 11: Integration tests (full trade lifecycle)
    Step 12: Docker + CI/CD + Monitoring
```

### 1.3 Coordination Protocol

| Mechanism | Purpose |
|-----------|---------|
| **Shared manifest** | `build/MANIFEST.json` — tracks step status, outputs, dependencies |
| **File-based handoffs** | Each agent writes outputs to its owned directories; downstream agents read |
| **Gate files** | `build/gates/step_N.complete` — created when a step passes verification |
| **No shared mutable state** | Agents never edit each other's files. Ever. |
| **Coordinator role** | Dispatches tasks, checks gates, resolves conflicts, triggers next phase |

### 1.4 Why Not a Single Agent?

A single agent building TSAR would:
- Hit context window limits (~200K tokens for the full architecture)
- Lose coherence across modules (risk engine vs. LLM routing vs. agents)
- Take 10-20x longer (serial execution)
- Produce inconsistent interfaces (drift between modules)

The swarm lets each agent hold its full domain in context, produce consistent output, and verify independently.

---

## 2. AGENT SPECIALIZATION

### 2.1 Agent Registry

Each build agent has a **scope** (what it owns), an **interface** (what it produces), and **dependencies** (what it needs from others).

---

#### AGENT 0: Scaffold Coordinator

| Attribute | Value |
|-----------|-------|
| **Scope** | Directory structure, `pyproject.toml`, `__init__.py` files, empty module stubs |
| **Produces** | Complete project skeleton with all directories and placeholder files |
| **Dependencies** | None (first agent) |
| **Files Owned** | `pyproject.toml`, `setup.cfg`, `ruff.toml`, `mypy.ini`, all `__init__.py` files, `.gitignore`, `Makefile` |

---

#### AGENT 1: Interface Architect

| Attribute | Value |
|-----------|-------|
| **Scope** | All ABCs + data types + BackendRegistry + convenience getters |
| **Produces** | `src/interfaces/` — complete interface layer with type annotations |
| **Dependencies** | AGENT 0 (skeleton exists) |
| **Files Owned** | `src/interfaces/**/*.py` (ALL files in interfaces/) |

**Specific outputs:**
- `src/interfaces/exchange.py` — ExchangeGateway ABC + data types (Ticker, OHLCV, OrderBook, etc.)
- `src/interfaces/pricing.py` — PricingEngine ABC + IndicatorResult, Greeks
- `src/interfaces/execution.py` — ExecutionEngine ABC + OrderRequest, Fill, SlippageReport
- `src/interfaces/risk.py` — RiskEngine ABC + RiskCheckResult, PositionSizeResult, DrawdownState
- `src/interfaces/llm.py` — BaseLLMProvider ABC + LLMRequest, LLMResponse, ModelCapabilities
- `src/interfaces/registry.py` — BackendRegistry + FallbackProxy + InstrumentedBackend
- `src/interfaces/__init__.py` — convenience getters (get_exchange_gateway, etc.)
- `src/interfaces/types.py` — shared enums (OrderSide, OrderType, OrderStatus, etc.)

---

#### AGENT 2: Data Layer Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | SQLite schema, migrations, Pydantic models, DAO layer |
| **Produces** | `src/data/` — database layer + all Pydantic data models |
| **Dependencies** | AGENT 0 (skeleton) |
| **Files Owned** | `src/data/**/*.py`, `migrations/` |

**Specific outputs:**
- `src/data/database.py` — SQLite connection manager, WAL mode, backup API
- `src/data/migrations.py` — schema migration runner
- `src/data/migrations/001_trade_tables.sql` — trade_records schema
- `src/data/migrations/002_strategy_tables.sql` — strategy_genomes, performance, mutations
- `src/data/migrations/003_pattern_tables.sql` — patterns, observations, relationships
- `src/data/migrations/004_lesson_tables.sql` — lessons, applications, violations + FTS5
- `src/data/migrations/005_regime_tables.sql` — regime_history
- `src/data/migrations/006_improvement_tables.sql` — baselines, snapshots, flywheel_health
- `src/data/models.py` — Pydantic models for all DB entities
- `src/data/dao.py` — Data Access Objects (TradeDAO, StrategyDAO, PatternDAO, LessonDAO, RegimeDAO)

---

#### AGENT 3: Config & Infrastructure Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | All YAML configs, Docker, docker-compose, Makefile targets, CI/CD |
| **Produces** | `config/`, `docker/`, `.github/`, deployment infrastructure |
| **Dependencies** | AGENT 0 (skeleton) |
| **Files Owned** | `config/**/*.yaml`, `docker/`, `.github/`, `Dockerfile`, `docker-compose.yml` |

**Specific outputs:**
- `config/backends.yaml` — interface-to-backend mapping (Day1 defaults)
- `config/models.yaml` — LLM providers, models, routing, budgets
- `config/resource_limits.yaml` — per-tool resource profiles
- `config/exchanges.yaml` — exchange credentials template
- `config/risk_limits.yaml` — risk parameters (canonical values)
- `docker/Dockerfile` — multi-stage Python 3.12 + Rust 1.79 build
- `docker/docker-compose.yml` — tsar-app, redis, prometheus, grafana
- `docker/watchdog.service` — systemd unit for Tier 3 watchdog
- `.github/workflows/ci.yml` — lint, typecheck, test, build

---

#### AGENT 4: Exchange Backend Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | CcxtGateway + CcxtExecEngine implementations |
| **Produces** | `src/backends/exchange/` — ccxt-based exchange connectivity |
| **Dependencies** | AGENT 1 (ExchangeGateway ABC), AGENT 2 (data models) |
| **Files Owned** | `src/backends/exchange/**/*.py` |

**Specific outputs:**
- `src/backends/exchange/ccxt_gateway.py` — full ExchangeGateway implementation
- `src/backends/exchange/ccxt_exec_engine.py` — full ExecutionEngine implementation
- `src/backends/exchange/ccxt_streaming.py` — polling-based streaming adapter
- `src/backends/exchange/__init__.py`

---

#### AGENT 5: Pricing & Analysis Backend Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | PandasTAEngine implementation |
| **Produces** | `src/backends/pricing/` — pandas-ta based quantitative engine |
| **Dependencies** | AGENT 1 (PricingEngine ABC) |
| **Files Owned** | `src/backends/pricing/**/*.py` |

**Specific outputs:**
- `src/backends/pricing/pandas_ta_engine.py` — full PricingEngine implementation
- `src/backends/pricing/indicators.py` — indicator wrapper functions
- `src/backends/pricing/__init__.py`

---

#### AGENT 6: Risk Backend Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | PyRiskEngine + kill switch + watchdog + circuit breakers + anti-behavioral guards |
| **Produces** | `src/backends/risk/` — complete risk subsystem |
| **Dependencies** | AGENT 1 (RiskEngine ABC), AGENT 2 (data models for drawdown tracking) |
| **Files Owned** | `src/backends/risk/**/*.py` |

**Specific outputs:**
- `src/backends/risk/py_risk_engine.py` — full RiskEngine implementation
- `src/backends/risk/kill_switch.py` — DualWriteKillSwitch (Redis + file)
- `src/backends/risk/watchdog.py` — three-tier watchdog
- `src/backends/risk/circuit_breaker.py` — drawdown circuit breakers (GREEN/YELLOW/ORANGE/RED)
- `src/backends/risk/anti_behavioral.py` — revenge trading, greed, FOMO, overconfidence guards
- `src/backends/risk/recovery.py` — gated recovery protocol
- `src/backends/risk/position_sizer.py` — half-Kelly + fixed fraction sizing
- `src/backends/risk/__init__.py`

---

#### AGENT 7: LLM & Messaging Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | LLM providers + ModelRouter + CloudEvents + Redis transport |
| **Produces** | `src/backends/llm/`, `src/messaging/` — intelligence + communication layers |
| **Dependencies** | AGENT 1 (BaseLLMProvider ABC), AGENT 3 (config/models.yaml) |
| **Files Owned** | `src/backends/llm/**/*.py`, `src/messaging/**/*.py` |

**Specific outputs:**
- `src/backends/llm/ollama_provider.py` — Ollama implementation
- `src/backends/llm/openai_provider.py` — OpenAI implementation
- `src/backends/llm/anthropic_provider.py` — Anthropic implementation
- `src/backends/llm/deepseek_provider.py` — DeepSeek implementation
- `src/backends/llm/model_router.py` — task_type → model routing with fallback chains
- `src/backends/llm/model_registry.py` — provider instances, circuit breakers, cost tracking
- `src/backends/llm/__init__.py`
- `src/messaging/cloudevents.py` — CloudEvents v1.0 envelope builder/parser
- `src/messaging/redis_transport.py` — Redis Streams transport (produce/consume)
- `src/messaging/serializer.py` — MessagePack serialization + JSON debug mode
- `src/messaging/__init__.py`

---

#### AGENT 8: Core Agent Builder (Wave 1 — Day1 Agents)

| Attribute | Value |
|-----------|-------|
| **Scope** | Signal Scout, Risk Guardian, Execution Sniper — the Day1 trading pipeline |
| **Produces** | `src/agents/` — 3 core agents that form the minimum viable trading loop |
| **Dependencies** | AGENT 1 (interfaces), AGENT 4 (exchange backend), AGENT 5 (pricing), AGENT 6 (risk), AGENT 7 (messaging) |
| **Files Owned** | `src/agents/signal_scout.py`, `src/agents/risk_guardian.py`, `src/agents/execution_sniper.py`, `src/agents/base.py` |

**Specific outputs:**
- `src/agents/base.py` — BaseAgent class (lifecycle, heartbeat, pub/sub, graceful shutdown)
- `src/agents/signal_scout.py` — market scanning, signal scoring (10-factor weighted), signal publishing
- `src/agents/risk_guardian.py` — 10-point checklist, VETO protocol, position sizing
- `src/agents/execution_sniper.py` — order lifecycle, SL/TP placement, position monitoring
- `src/agents/registry.py` — agent registry + permission matrix

---

#### AGENT 9: Support Agent Builder (Wave 2-3)

| Attribute | Value |
|-----------|-------|
| **Scope** | Orchestrator, Execution Tracker, Macro Agent, Regime Detector, Trade Philosopher, Strategy Geneticist, Market Cartographer |
| **Produces** | Remaining 7 agents |
| **Dependencies** | AGENT 8 (base agent class), AGENT 7 (messaging), AGENT 2 (data layer) |
| **Files Owned** | `src/agents/orchestrator.py`, `src/agents/execution_tracker.py`, `src/agents/macro_agent.py`, `src/agents/regime_detector.py`, `src/agents/trade_philosopher.py`, `src/agents/strategy_geneticist.py`, `src/agents/market_cartographer.py` |

**Specific outputs:**
- `src/agents/orchestrator.py` — health monitoring, alert routing, backup coordination
- `src/agents/execution_tracker.py` — position reconciliation, fill monitoring, slippage tracking
- `src/agents/macro_agent.py` — macro regime, economic calendar, sentiment analysis
- `src/agents/regime_detector.py` — HMM-based regime classification
- `src/agents/trade_philosopher.py` — post-trade reflection, lesson extraction
- `src/agents/strategy_geneticist.py` — strategy evolution, backtesting, retirement gates
- `src/agents/market_cartographer.py` — cross-asset correlation, structural analysis

---

#### AGENT 10: Knowledge & Strategy Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | Strategy implementations + improvement measurement + tool registry |
| **Produces** | `src/strategies/`, `src/improvement/`, `src/tools/` |
| **Dependencies** | AGENT 2 (data layer), AGENT 1 (interfaces), AGENT 6 (risk for position sizing) |
| **Files Owned** | `src/strategies/**/*.py`, `src/improvement/**/*.py`, `src/tools/**/*.py` |

**Specific outputs:**
- `src/strategies/base.py` — BaseStrategy ABC
- `src/strategies/mean_reversion.py` — Day1 strategy (RSI + support/resistance + volume)
- `src/strategies/momentum_funding.py` — Level 2 strategy (EMA + funding rate + ADX)
- `src/strategies/portfolio.py` — allocation methods (risk parity, Kelly, inverse vol)
- `src/strategies/backtester.py` — vectorbt integration (Level 2+)
- `src/improvement/metrics.py` — 10 core metrics computation
- `src/improvement/baseline.py` — baseline recording after 30 trades
- `src/improvement/flywheel.py` — flywheel health score
- `src/improvement/alerts.py` — improvement alert rules
- `src/tools/registry.py` — ToolRegistry + ResourceEnforcer + ResourceGuard
- `src/tools/exchange_tools.py` — exchange tool implementations
- `src/tools/analysis_tools.py` — analysis tool implementations
- `src/tools/risk_tools.py` — risk tool implementations
- `src/tools/memory_tools.py` — memory tool implementations

---

#### AGENT 11: Integration & Test Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | Integration tests, end-to-end trade lifecycle tests, stress tests |
| **Produces** | `tests/` — complete test suite |
| **Dependencies** | ALL prior agents (tests verify their outputs) |
| **Files Owned** | `tests/**/*.py`, `conftest.py`, `pytest.ini` |

**Specific outputs:**
- `tests/conftest.py` — shared fixtures (mock exchange, mock LLM, test DB)
- `tests/unit/test_interfaces.py` — ABC contract tests
- `tests/unit/test_registry.py` — BackendRegistry tests
- `tests/unit/test_risk_engine.py` — risk rules, kill switch, circuit breakers
- `tests/unit/test_cloudevents.py` — serialization/deserialization
- `tests/unit/test_position_sizer.py` — Kelly, fixed fraction
- `tests/unit/test_anti_behavioral.py` — guard tests
- `tests/integration/test_trade_lifecycle.py` — full signal → risk → execution → fill flow
- `tests/integration/test_messaging.py` — Redis Streams pub/sub
- `tests/integration/test_agent_startup.py` — all agents bootstrap
- `tests/stress/test_kill_switch.py` — kill switch under failure conditions
- `tests/stress/test_circuit_breakers.py` — drawdown scenarios

---

#### AGENT 12: Deployment Engineer

| Attribute | Value |
|-----------|-------|
| **Scope** | Docker build, CI/CD pipeline, monitoring setup, FastAPI endpoints |
| **Produces** | Working Docker deployment + CI/CD + monitoring |
| **Dependencies** | AGENT 3 (Docker skeleton), AGENT 11 (tests pass) |
| **Files Owned** | `src/api/**/*.py`, `docker/`, `.github/` (finalized) |

**Specific outputs:**
- `src/api/main.py` — FastAPI app with all endpoints
- `src/api/auth.py` — API key authentication
- `src/api/health.py` — health check endpoint
- `src/api/models.py` — API response models
- `docker/Dockerfile` — finalized multi-stage build
- `docker/docker-compose.yml` — finalized with all services
- `docker/prometheus.yml` — Prometheus scrape config
- `docker/grafana/` — dashboard provisioning
- `.github/workflows/ci.yml` — finalized CI pipeline

---

## 3. FILE OWNERSHIP

### 3.1 Ownership Principle

**One agent owns each file. No exceptions.**

If two agents need to contribute to the same file, the owning agent writes it and the other agent provides input via a handoff file (written to `build/handoffs/`).

### 3.2 Ownership Map

```
PROJECT ROOT
├── pyproject.toml                          [AGENT 0]
├── setup.cfg                               [AGENT 0]
├── ruff.toml                               [AGENT 0]
├── mypy.ini                                [AGENT 0]
├── Makefile                                [AGENT 0]
├── .gitignore                              [AGENT 0]
├── Dockerfile                              [AGENT 3 → AGENT 12 finalize]
├── docker-compose.yml                      [AGENT 3 → AGENT 12 finalize]
│
├── config/
│   ├── backends.yaml                       [AGENT 3]
│   ├── models.yaml                         [AGENT 3]
│   ├── resource_limits.yaml                [AGENT 3]
│   ├── exchanges.yaml                      [AGENT 3]
│   └── risk_limits.yaml                    [AGENT 3]
│
├── src/
│   ├── __init__.py                         [AGENT 0]
│   │
│   ├── interfaces/                         [AGENT 1 — ALL files]
│   │   ├── __init__.py
│   │   ├── types.py
│   │   ├── exchange.py
│   │   ├── pricing.py
│   │   ├── execution.py
│   │   ├── risk.py
│   │   ├── llm.py
│   │   └── registry.py
│   │
│   ├── data/                               [AGENT 2 — ALL files]
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── migrations.py
│   │   ├── models.py
│   │   ├── dao.py
│   │   └── migrations/
│   │       ├── 001_trade_tables.sql
│   │       ├── 002_strategy_tables.sql
│   │       ├── 003_pattern_tables.sql
│   │       ├── 004_lesson_tables.sql
│   │       ├── 005_regime_tables.sql
│   │       └── 006_improvement_tables.sql
│   │
│   ├── backends/
│   │   ├── __init__.py                     [AGENT 0]
│   │   ├── exchange/                       [AGENT 4 — ALL files]
│   │   │   ├── __init__.py
│   │   │   ├── ccxt_gateway.py
│   │   │   ├── ccxt_exec_engine.py
│   │   │   └── ccxt_streaming.py
│   │   ├── pricing/                        [AGENT 5 — ALL files]
│   │   │   ├── __init__.py
│   │   │   ├── pandas_ta_engine.py
│   │   │   └── indicators.py
│   │   ├── risk/                           [AGENT 6 — ALL files]
│   │   │   ├── __init__.py
│   │   │   ├── py_risk_engine.py
│   │   │   ├── kill_switch.py
│   │   │   ├── watchdog.py
│   │   │   ├── circuit_breaker.py
│   │   │   ├── anti_behavioral.py
│   │   │   ├── recovery.py
│   │   │   └── position_sizer.py
│   │   └── llm/                            [AGENT 7 — ALL files]
│   │       ├── __init__.py
│   │       ├── ollama_provider.py
│   │       ├── openai_provider.py
│   │       ├── anthropic_provider.py
│   │       ├── deepseek_provider.py
│   │       ├── model_router.py
│   │       └── model_registry.py
│   │
│   ├── messaging/                          [AGENT 7 — ALL files]
│   │   ├── __init__.py
│   │   ├── cloudevents.py
│   │   ├── redis_transport.py
│   │   └── serializer.py
│   │
│   ├── agents/                             [AGENT 8 + AGENT 9]
│   │   ├── __init__.py                     [AGENT 0]
│   │   ├── base.py                         [AGENT 8]
│   │   ├── registry.py                     [AGENT 8]
│   │   ├── signal_scout.py                 [AGENT 8]
│   │   ├── risk_guardian.py                [AGENT 8]
│   │   ├── execution_sniper.py             [AGENT 8]
│   │   ├── orchestrator.py                 [AGENT 9]
│   │   ├── execution_tracker.py            [AGENT 9]
│   │   ├── macro_agent.py                  [AGENT 9]
│   │   ├── regime_detector.py              [AGENT 9]
│   │   ├── trade_philosopher.py            [AGENT 9]
│   │   ├── strategy_geneticist.py          [AGENT 9]
│   │   └── market_cartographer.py          [AGENT 9]
│   │
│   ├── strategies/                         [AGENT 10 — ALL files]
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── mean_reversion.py
│   │   ├── momentum_funding.py
│   │   ├── portfolio.py
│   │   └── backtester.py
│   │
│   ├── improvement/                        [AGENT 10 — ALL files]
│   │   ├── __init__.py
│   │   ├── metrics.py
│   │   ├── baseline.py
│   │   ├── flywheel.py
│   │   └── alerts.py
│   │
│   ├── tools/                              [AGENT 10 — ALL files]
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   ├── exchange_tools.py
│   │   ├── analysis_tools.py
│   │   ├── risk_tools.py
│   │   └── memory_tools.py
│   │
│   └── api/                                [AGENT 12 — ALL files]
│       ├── __init__.py
│       ├── main.py
│       ├── auth.py
│       ├── health.py
│       └── models.py
│
├── tests/                                  [AGENT 11 — ALL files]
│   ├── conftest.py
│   ├── pytest.ini
│   ├── unit/
│   │   ├── test_interfaces.py
│   │   ├── test_registry.py
│   │   ├── test_risk_engine.py
│   │   ├── test_cloudevents.py
│   │   ├── test_position_sizer.py
│   │   └── test_anti_behavioral.py
│   ├── integration/
│   │   ├── test_trade_lifecycle.py
│   │   ├── test_messaging.py
│   │   └── test_agent_startup.py
│   └── stress/
│       ├── test_kill_switch.py
│       └── test_circuit_breakers.py
│
├── docker/                                 [AGENT 3 scaffold → AGENT 12 finalize]
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── prometheus.yml
│   └── grafana/
│       └── dashboards/
│
└── .github/workflows/                      [AGENT 3 scaffold → AGENT 12 finalize]
    └── ci.yml
```

### 3.3 Handoff Points

| From | To | Handoff Mechanism |
|------|----|--------------------|
| AGENT 0 | ALL | `build/gates/step_0.complete` — skeleton ready |
| AGENT 1 | AGENT 4,5,6,7,8 | Interfaces imported directly (AGENT 1 finishes first) |
| AGENT 2 | AGENT 6,8,9,10 | Data models imported directly |
| AGENT 3 | AGENT 7,12 | Config files read directly |
| AGENT 8 | AGENT 9 | `src/agents/base.py` + `registry.py` imported directly |
| ALL (Step N) | ALL (Step N+1) | `build/gates/step_N.complete` + verification report |

### 3.4 Merge Conflict Prevention Rules

1. **No agent edits another agent's files.** Period.
2. **Imports are read-only.** Agents import from completed modules but never modify them.
3. **Shared constants** go in `src/interfaces/types.py` (AGENT 1 owns). All other agents import from there.
4. **Config values** go in `config/*.yaml` (AGENT 3 owns). Agents read via config loader, never edit.
5. **Test fixtures** are in `tests/conftest.py` (AGENT 11 owns). No agent writes test files except AGENT 11.

---

## 4. BUILD PIPELINE

### 4.1 Overview

12 sequential steps. Steps within a phase can run in parallel. Gates enforce ordering.

```
Step  1: Scaffold                    [AGENT 0]  — Phase 0
Step  2: Interfaces + Registry       [AGENT 1]  — Phase 1 ─┐
Step  3: Data Layer + Schema         [AGENT 2]  — Phase 1  ├─ parallel
Step  4: Config + Docker Skeleton    [AGENT 3]  — Phase 1 ─┘
Step  5: Exchange Backend            [AGENT 4]  — Phase 2 ─┐
Step  6: Pricing Backend             [AGENT 5]  — Phase 2  │
Step  7: Risk Backend                [AGENT 6]  — Phase 2  ├─ parallel
Step  8: LLM + Messaging             [AGENT 7]  — Phase 2 ─┘
Step  9: Core Agents (Day1)          [AGENT 8]  — Phase 3 Wave 1
Step 10: Support Agents + Knowledge  [AGENT 9+10] — Phase 3 Wave 2-3 + Phase 4
Step 11: Tests                       [AGENT 11] — Phase 4
Step 12: Integration + Deployment    [AGENT 12] — Phase 5
```

### 4.2 Detailed Step Specifications

---

#### STEP 1: Scaffold [AGENT 0]

**Input:** TSAR_ARCHITECTURE.md v3.0.0
**Output:** Complete project skeleton

**Tasks:**
1. Create directory structure (all dirs from §3.2 ownership map)
2. Write `pyproject.toml` with all dependencies:
   - Python 3.12, ccxt, pandas, pandas-ta, numpy, ollama, openai, anthropic, redis, pydantic, vectorbt, msgpack, fastapi, uvicorn, pytest, ruff, mypy
3. Write `ruff.toml` (line-length=120, target=py312)
4. Write `mypy.ini` (strict mode, python_version=3.12)
5. Write `Makefile` with targets: `lint`, `typecheck`, `test`, `build`, `run`
6. Write all `__init__.py` files (empty or with `__all__`)
7. Write `.gitignore` (Python, Rust, Docker, IDE)
8. Create `build/` directory for gate files and handoffs

**Verification:**
- [ ] All directories exist
- [ ] `pip install -e .` succeeds
- [ ] `ruff check .` passes (no files to lint yet, but config is valid)
- [ ] `mypy --install-types` works

---

#### STEP 2: Interfaces + Registry [AGENT 1]

**Input:** Skeleton (Step 1 complete)
**Output:** Complete interface layer — 7 files, all ABCs + types + registry

**Tasks:**
1. `src/interfaces/types.py` — All shared enums and data types:
   - `OrderSide`, `OrderType`, `OrderStatus`, `TimeInForce`, `ConnectionStatus`
   - `Ticker`, `OHLCV`, `OrderBook`, `Trade`, `OrderResult`, `Position`, `Balance`, `StreamHandle`
   - `RiskCheckResult`, `PositionSizeResult`, `DrawdownState`, `StressTestResult`
   - `IndicatorResult`, `Greeks`, `OHLCVBar`, `OptionType`
   - `OrderRequest`, `Fill`, `SlippageReport`, `ExecutionResult`
   - `LLMRequest`, `LLMResponse`, `LLMChunk`, `ModelCapabilities`
   - All Pydantic `BaseModel` subclasses

2. `src/interfaces/exchange.py` — `ExchangeGateway(ABC)` with all methods from §2.4
3. `src/interfaces/pricing.py` — `PricingEngine(ABC)` with all methods from §2.5
4. `src/interfaces/execution.py` — `ExecutionEngine(ABC)` with all methods from §2.6
5. `src/interfaces/risk.py` — `RiskEngine(ABC)` with all methods from §2.7
6. `src/interfaces/llm.py` — `BaseLLMProvider(ABC)` with all methods from §2.8
7. `src/interfaces/registry.py` — `BackendRegistry`, `FallbackProxy`, `InstrumentedBackend`
8. `src/interfaces/__init__.py` — convenience getters

**Verification:**
- [ ] `mypy src/interfaces/` passes with zero errors
- [ ] All ABCs are instantiable via `BackendRegistry`
- [ ] `from src.interfaces import get_exchange_gateway` works
- [ ] `ruff check src/interfaces/` passes

---

#### STEP 3: Data Layer + Schema [AGENT 2]

**Input:** Skeleton (Step 1 complete)
**Output:** Database layer with all 6 migration files + Pydantic models + DAO

**Tasks:**
1. `src/data/database.py` — SQLite connection manager (WAL mode, backup API, thread-safe)
2. `src/data/migrations.py` — migration runner (tracks applied migrations in `schema_version` table)
3. Write all 6 SQL migration files matching §4.1-4.6 schemas exactly
4. `src/data/models.py` — Pydantic models mirroring all DB tables
5. `src/data/dao.py` — DAO classes: `TradeDAO`, `StrategyDAO`, `PatternDAO`, `LessonDAO`, `RegimeDAO`, `ImprovementDAO`
   - CRUD operations for each entity
   - FTS5 search for lessons
   - JSON field serialization/deserialization

**Verification:**
- [ ] `mypy src/data/` passes
- [ ] Creating a fresh `tsar.db` runs all migrations successfully
- [ ] DAO CRUD operations work (insert, read, update, delete)
- [ ] FTS5 search returns results

---

#### STEP 4: Config + Docker Skeleton [AGENT 3]

**Input:** Skeleton (Step 1 complete)
**Output:** All config YAML files + Docker skeleton + CI skeleton

**Tasks:**
1. `config/backends.yaml` — Day1 defaults (all Python backends, no Rust/C++)
2. `config/models.yaml` — Ollama-only Day1 config, all task types defined
3. `config/resource_limits.yaml` — all per-tool profiles from §10.3
4. `config/exchanges.yaml` — template with `${BINANCE_API_KEY}` placeholders
5. `config/risk_limits.yaml` — all canonical values from §6.1
6. `docker/Dockerfile` — multi-stage: Python 3.12 base, install deps, copy src
7. `docker/docker-compose.yml` — tsar-app + redis:7.0
8. `.github/workflows/ci.yml` — lint + typecheck + test skeleton

**Verification:**
- [ ] All YAML files parse without errors
- [ ] `docker build -f docker/Dockerfile .` succeeds
- [ ] `docker-compose -f docker/docker-compose.yml config` validates

---

#### STEP 5: Exchange Backend [AGENT 4]

**Input:** AGENT 1 (interfaces), AGENT 2 (data models)
**Output:** CcxtGateway + CcxtExecEngine

**Tasks:**
1. `src/backends/exchange/ccxt_gateway.py`:
   - Implement all `ExchangeGateway` methods using ccxt
   - Async wrappers around synchronous ccxt calls
   - Connection management (connect/disconnect/reconnect)
   - Error handling with retryable vs. fatal classification
   - Polling-based streaming (subscribe/unsubscribe with polling loop)
2. `src/backends/exchange/ccxt_exec_engine.py`:
   - Implement all `ExecutionEngine` methods
   - Delegates to ExchangeGateway for actual order placement
   - Slippage calculation
   - TWAP/VWAP Day1 fallbacks (simple implementations)
3. `src/backends/exchange/ccxt_streaming.py`:
   - Price streaming via polling
   - Orderbook streaming via polling

**Verification:**
- [ ] `mypy src/backends/exchange/` passes
- [ ] Unit tests with mocked ccxt pass
- [ ] `CcxtGateway` satisfies `ExchangeGateway` ABC (`isinstance` check)
- [ ] `CcxtExecEngine` satisfies `ExecutionEngine` ABC

---

#### STEP 6: Pricing Backend [AGENT 5]

**Input:** AGENT 1 (PricingEngine ABC)
**Output:** PandasTAEngine

**Tasks:**
1. `src/backends/pricing/pandas_ta_engine.py`:
   - Implement `calculate_indicator` dispatching to pandas-ta
   - Implement convenience methods (RSI, EMA, ATR, MACD, Bollinger)
   - `aggregate_ohlcv` for timeframe aggregation
   - `calculate_greeks` stub (Day1: Black-Scholes basic)
2. `src/backends/pricing/indicators.py`:
   - Wrapper functions for all indicators used by Signal Scout
   - Support for the 10 signal scoring factors

**Verification:**
- [ ] `mypy src/backends/pricing/` passes
- [ ] RSI calculation matches known values (test with sample data)
- [ ] EMA, ATR, MACD, Bollinger calculations verified
- [ ] `PandasTAEngine` satisfies `PricingEngine` ABC

---

#### STEP 7: Risk Backend [AGENT 6]

**Input:** AGENT 1 (RiskEngine ABC), AGENT 2 (data models)
**Output:** Complete risk subsystem — 7 files

**Tasks:**
1. `src/backends/risk/py_risk_engine.py`:
   - `check_risk()` — 10-point checklist from §3.4 Agent 2
   - `calculate_position_size()` — half-Kelly with 0.25 fixed fraction
   - `get_drawdown_state()` — circuit breaker state computation
2. `src/backends/risk/kill_switch.py`:
   - `DualWriteKillSwitch` — Redis + file dual-write
   - Read path: Redis → file → fail-safe (active)
   - All trigger conditions from §6.2
3. `src/backends/risk/watchdog.py`:
   - Three-tier architecture (Governor → Monitor → Watchdog)
   - Heartbeat production and monitoring
   - systemd integration for Tier 3
4. `src/backends/risk/circuit_breaker.py`:
   - GREEN/YELLOW/ORANGE/RED states
   - State transitions with logging
5. `src/backends/risk/anti_behavioral.py`:
   - Revenge trading detection (3 consecutive losses)
   - Greed detection (size increase after wins)
   - FOMO detection (low score trading)
   - Overconfidence detection (5+ wins, increasing size)
6. `src/backends/risk/recovery.py`:
   - Gated recovery protocol (ORANGE and RED paths)
   - Phase progression with validation gates
7. `src/backends/risk/position_sizer.py`:
   - Half-Kelly, fixed fraction, risk parity methods
   - Max position cap (15%), max sector concentration (30%)

**Verification:**
- [ ] `mypy src/backends/risk/` passes
- [ ] Kill switch dual-write works (Redis + file)
- [ ] Kill switch file fallback works when Redis is down
- [ ] Circuit breaker transitions correctly through GREEN → YELLOW → ORANGE → RED
- [ ] All 9 hard rules from §6.1 are enforced
- [ ] Anti-behavioral guards trigger at correct thresholds

---

#### STEP 8: LLM + Messaging [AGENT 7]

**Input:** AGENT 1 (BaseLLMProvider ABC), AGENT 3 (config)
**Output:** LLM providers + ModelRouter + CloudEvents + Redis transport

**Tasks:**
1. `src/backends/llm/ollama_provider.py`:
   - `generate()`, `stream()`, `count_tokens()`, `health_check()`
   - Async HTTP client to Ollama API
2. `src/backends/llm/openai_provider.py` — OpenAI SDK wrapper
3. `src/backends/llm/anthropic_provider.py` — Anthropic SDK wrapper
4. `src/backends/llm/deepseek_provider.py` — DeepSeek API wrapper
5. `src/backends/llm/model_router.py`:
   - Task-type → model mapping (from `config/models.yaml`)
   - Fallback chain execution
   - Circuit breaker per provider
6. `src/backends/llm/model_registry.py`:
   - Provider instance management
   - Cost tracking (daily/monthly)
   - Prometheus metrics
7. `src/messaging/cloudevents.py`:
   - CloudEvents v1.0 envelope builder
   - All TSAR extension attributes (traceid, priority, risklevel, etc.)
   - ULID generation
8. `src/messaging/redis_transport.py`:
   - Redis Streams producer (XADD)
   - Redis Streams consumer (XREADGROUP)
   - Consumer group management
   - Stream creation and trimming
9. `src/messaging/serializer.py`:
   - MessagePack encode/decode
   - JSON debug mode
   - CloudEvents field mapping (`ce_` prefix)

**Verification:**
- [ ] `mypy src/backends/llm/ src/messaging/` passes
- [ ] CloudEvents round-trip (build → serialize → deserialize → verify) passes
- [ ] Redis transport can produce and consume messages (integration test with Redis)
- [ ] ModelRouter correctly routes task_types to configured models
- [ ] OllamaProvider health check works against local Ollama

---

#### STEP 9: Core Agents (Day1) [AGENT 8]

**Input:** All interfaces (Step 2), backends (Steps 5-8), data layer (Step 3)
**Output:** BaseAgent + 3 Day1 agents + agent registry

**Tasks:**
1. `src/agents/base.py`:
   - `BaseAgent` class: lifecycle (start/stop), heartbeat, pub/sub wrapper
   - Graceful shutdown (SIGTERM handler)
   - Health stream publishing (`tsar:stream:health`)
   - Config loading
2. `src/agents/registry.py`:
   - Agent permission matrix (READ, ANALYSIS, TRADE_PREVIEW, TRADE_EXECUTE, TRADE_ADMIN)
   - Agent metadata (name, role, streams, tools)
3. `src/agents/signal_scout.py`:
   - 5-minute scan cycle
   - 10-factor weighted scoring from §3.4
   - Signal generation with entry/SL/TP
   - Publishes to `tsar:stream:signals`
   - Subscribes to: regime, strategy_mutations, cartography
4. `src/agents/risk_guardian.py`:
   - 10-point evaluation checklist
   - VETO protocol (SOFT/FIRM/HARD/NUCLEAR)
   - Position sizing (fixed 0.25, capped at 2%)
   - Subscribes to: signals, fills, positions, macro, cartography
   - Publishes to: risk_decisions, risk_reply:*
5. `src/agents/execution_sniper.py`:
   - Order lifecycle (receive → validate → place → SL → TP → monitor → close)
   - Position monitoring (1-minute cycle)
   - P&L calculation on close
   - Telegram notification
   - Subscribes to: risk_decisions
   - Publishes to: orders, risk_requests

**Verification:**
- [ ] `mypy src/agents/` passes
- [ ] All 3 agents can be instantiated
- [ ] Signal Scout produces valid `Signal` objects
- [ ] Risk Guardian correctly rejects signals that violate rules
- [ ] Execution Sniper completes a mock order lifecycle
- [ ] Agents publish to correct streams
- [ ] Heartbeats appear on `tsar:stream:health`

---

#### STEP 10: Support Agents + Knowledge + Strategies [AGENT 9 + AGENT 10]

**Input:** Core agents (Step 9), data layer (Step 3), all backends
**Output:** Remaining 7 agents + knowledge stores + strategies + tools + improvement

**AGENT 9 tasks (7 support agents):**
1. `src/agents/orchestrator.py` — health monitoring, alert routing, bootstrap coordination
2. `src/agents/execution_tracker.py` — position reconciliation (5-min), balance check (15-min), EOD snapshot
3. `src/agents/macro_agent.py` — macro regime scoring, economic calendar, sentiment analysis
4. `src/agents/regime_detector.py` — HMM-based regime classification (5 states)
5. `src/agents/trade_philosopher.py` — post-trade reflection, lesson extraction, error categorization
6. `src/agents/strategy_geneticist.py` — strategy evolution, backtesting, retirement gates
7. `src/agents/market_cartographer.py` — cross-asset correlation (8 pairs), anomaly detection

**AGENT 10 tasks (strategies + tools + improvement):**
1. `src/strategies/base.py` — BaseStrategy ABC
2. `src/strategies/mean_reversion.py` — RSI + support/resistance + volume + Fear & Greed
3. `src/strategies/momentum_funding.py` — EMA crossover + funding rate + ADX
4. `src/strategies/portfolio.py` — risk parity, Kelly-based, inverse volatility allocation
5. `src/strategies/backtester.py` — vectorbt integration stub
6. `src/improvement/metrics.py` — 10 core metrics from §9.2
7. `src/improvement/baseline.py` — baseline recording after 30 trades
8. `src/improvement/flywheel.py` — composite health score (0-1)
9. `src/improvement/alerts.py` — CRITICAL + WARNING alert rules
10. `src/tools/registry.py` — ToolRegistry + ResourceEnforcer + ResourceGuard
11. `src/tools/exchange_tools.py` — get_price, get_ohlcv, place_order, etc.
12. `src/tools/analysis_tools.py` — calculate_rsi, calculate_macd, etc.
13. `src/tools/risk_tools.py` — check_position_limits, calculate_position_size, etc.
14. `src/tools/memory_tools.py` — log_trade, search_trades, get_lesson, etc.

**Verification:**
- [ ] `mypy src/agents/ src/strategies/ src/improvement/ src/tools/` passes
- [ ] All 10 agents can be instantiated
- [ ] All 35 tools are registered in ToolRegistry
- [ ] Mean Reversion strategy produces valid entry/exit signals on sample data
- [ ] Improvement metrics compute correctly on sample trade data
- [ ] Flywheel health score returns value in [0, 1]

---

#### STEP 11: Tests [AGENT 11]

**Input:** ALL prior steps complete
**Output:** Complete test suite

**Tasks:**
1. `tests/conftest.py` — shared fixtures:
   - `mock_exchange_gateway` — returns canned data
   - `mock_llm_provider` — returns canned responses
   - `test_db` — in-memory SQLite with all migrations
   - `redis_fixture` — test Redis connection
   - `sample_signal` — valid Signal object
   - `sample_trade` — valid TradeRecord
2. Unit tests (6 files):
   - `test_interfaces.py` — ABC contract verification, BackendRegistry CRUD
   - `test_registry.py` — fallback, hot-swap, metrics, config loading
   - `test_risk_engine.py` — all 9 hard rules, all VETO levels, circuit breakers
   - `test_cloudevents.py` — serialization, all event types, Redis field mapping
   - `test_position_sizer.py` — Kelly, fixed fraction, caps
   - `test_anti_behavioral.py` — all 4 guards
3. Integration tests (3 files):
   - `test_trade_lifecycle.py` — signal → risk → execution → fill → philosopher
   - `test_messaging.py` — produce → consume via Redis Streams
   - `test_agent_startup.py` — all 10 agents boot and publish heartbeats
4. Stress tests (2 files):
   - `test_kill_switch.py` — Redis down, file fallback, dual-write
   - `test_circuit_breakers.py` — drawdown scenarios, recovery gates

**Verification:**
- [ ] `pytest tests/ -v` — ALL tests pass
- [ ] `pytest tests/ --cov=src --cov-report=term-missing` — coverage > 80%
- [ ] No test depends on external services (all mocked)

---

#### STEP 12: Integration + Deployment [AGENT 12]

**Input:** Tests pass (Step 11)
**Output:** Working Docker deployment + CI/CD + FastAPI + monitoring

**Tasks:**
1. `src/api/main.py` — FastAPI app with all 12 endpoints from §11.3
2. `src/api/auth.py` — API key authentication middleware
3. `src/api/health.py` — `/health` endpoint (checks Redis, DB, agents)
4. `src/api/models.py` — Pydantic response models for all endpoints
5. Finalize `docker/Dockerfile` — multi-stage build, Rust compilation, health check
6. Finalize `docker/docker-compose.yml` — all services with health checks
7. `docker/prometheus.yml` — scrape config for TSAR metrics
8. `docker/grafana/dashboards/` — JSON dashboard provisioning
9. Finalize `.github/workflows/ci.yml`:
   - Lint (ruff)
   - Type check (mypy)
   - Unit tests
   - Integration tests (with Redis service container)
   - Docker build
   - Optional: canary deploy

**Verification:**
- [ ] `docker-compose up` brings up all services
- [ ] `curl http://localhost:8000/health` returns 200
- [ ] CI pipeline runs green on a clean commit
- [ ] Prometheus scrapes TSAR metrics
- [ ] Grafana dashboards render

---

## 5. VERIFICATION PROTOCOL

### 5.1 Per-Step Verification Checklist

Every step MUST pass all applicable checks before the gate file is created.

| Check | Tool | Applies To | Threshold |
|-------|------|------------|-----------|
| **Linting** | `ruff check src/` | All steps | 0 errors, 0 warnings |
| **Type checking** | `mypy src/ --strict` | All steps | 0 errors |
| **Import check** | `python -c "from src.{module} import *"` | Steps 2-10 | No ImportError |
| **Unit tests** | `pytest tests/unit/ -v` | Steps 5-12 | 100% pass |
| **Integration tests** | `pytest tests/integration/ -v` | Steps 9-12 | 100% pass |
| **Stress tests** | `pytest tests/stress/ -v` | Steps 11-12 | 100% pass |
| **Coverage** | `pytest --cov=src --cov-fail-under=80` | Step 11 | ≥ 80% |
| **Docker build** | `docker build .` | Steps 4, 12 | Exit 0 |
| **ABC satisfaction** | `isinstance(impl, ABC)` | Steps 5-8 | True |

### 5.2 Gate File Protocol

After a step passes all verification checks:

1. Run the full verification checklist for that step
2. Generate a verification report (`build/reports/step_N_report.txt`)
3. Create gate file: `build/gates/step_N.complete`
4. Gate file contains: timestamp, verification results hash, agent ID

```json
// build/gates/step_2.complete
{
  "step": 2,
  "agent": "interface_architect",
  "timestamp": "2026-07-24T05:45:00Z",
  "checks": {
    "lint": {"pass": true, "errors": 0},
    "typecheck": {"pass": true, "errors": 0},
    "import_check": {"pass": true},
    "abc_satisfaction": {"pass": true, "interfaces": 5}
  },
  "hash": "sha256:abcdef1234567890"
}
```

### 5.3 Regression Prevention

When any step N completes:
1. Re-run verification for ALL steps that depend on step N
2. If any regression found: BLOCK step N+1, fix regression first
3. Dependency graph for regression checks:

```
Step 2 (interfaces) → Steps 5, 6, 7, 8, 9, 10
Step 3 (data)       → Steps 6, 9, 10
Step 4 (config)     → Steps 8, 12
Step 5 (exchange)   → Steps 9, 10
Step 6 (pricing)    → Steps 9, 10
Step 7 (risk)       → Steps 9, 10
Step 8 (llm+msg)    → Steps 9, 10
Step 9 (core agents) → Steps 10, 11
Step 10 (support)   → Step 11
Step 11 (tests)     → Step 12
```

### 5.4 Continuous Verification Command

```bash
# Full verification suite (run after each step)
make verify-step STEP=N

# Which expands to:
ruff check src/ && \
mypy src/ --strict && \
python -c "from src.interfaces import get_exchange_gateway" && \
pytest tests/unit/ -v --tb=short && \
echo "STEP $N VERIFIED"
```

---

## 6. EXECUTION SCHEDULE

### 6.1 Timeline Estimate

| Phase | Steps | Agents | Parallel? | Est. Duration |
|-------|-------|--------|-----------|---------------|
| Phase 0 | Step 1 | 1 | No | 10 min |
| Phase 1 | Steps 2-4 | 3 | Yes | 20 min |
| Phase 2 | Steps 5-8 | 4 | Yes | 30 min |
| Phase 3 | Steps 9-10 | 2-3 | Semi | 40 min |
| Phase 4 | Step 11 | 1 | No | 20 min |
| Phase 5 | Step 12 | 1 | No | 15 min |
| **Total** | **12 steps** | **12 agents** | | **~2.5 hours** |

### 6.2 Critical Path

```
Step 1 (scaffold)
  → Step 2 (interfaces) ← CRITICAL: blocks all backends
    → Step 5 (exchange) ← CRITICAL: blocks core agents
      → Step 9 (core agents) ← CRITICAL: blocks support agents
        → Step 10 (support agents)
          → Step 11 (tests)
            → Step 12 (deployment)
```

**Total critical path: 7 steps.** Steps 3, 4, 6, 7, 8 are off-critical-path and can absorb delays.

### 6.3 Failure Recovery

| Failure | Recovery |
|---------|----------|
| Agent produces code that fails typecheck | Agent retries with error context (max 3 retries) |
| Agent produces code that fails tests | Agent gets test output, fixes, retries (max 3) |
| Agent exceeds time limit | Coordinator reassigns to backup agent with narrowed scope |
| Dependency not ready | Agent waits at gate, polls every 30s, escalates after 5 min |
| Circular dependency detected | Coordinator restructures assignment |

### 6.4 Swarm Invocation Template

Each build agent is invoked with:

```
You are build agent "{AGENT_NAME}" building TSAR.

YOUR SCOPE:
{scope_description}

YOUR OUTPUT FILES:
{file_list}

YOUR DEPENDENCIES:
{dependency_list} — these are already complete. Import from them freely.

ARCHITECTURE REFERENCE:
Read /home/work/.openclaw/workspace/tsar/docs/architecture/TSAR_ARCHITECTURE.md
Focus on sections: {relevant_sections}

VERIFICATION:
After writing all files, run:
{verification_commands}

Write all files to the workspace. Do NOT edit files owned by other agents.
```

---

## APPENDIX: AGENT-TO-STEP MAPPING (QUICK REFERENCE)

| Agent | Step | Phase | Files | Key Deliverable |
|-------|------|-------|-------|-----------------|
| AGENT 0 | 1 | 0 | 7+ | Project skeleton |
| AGENT 1 | 2 | 1 | 8 | Interface layer (5 ABCs + registry) |
| AGENT 2 | 3 | 1 | 9 | Data layer (DB + models + DAO) |
| AGENT 3 | 4 | 1 | 8 | Config + Docker + CI |
| AGENT 4 | 5 | 2 | 4 | CcxtGateway + CcxtExecEngine |
| AGENT 5 | 6 | 2 | 3 | PandasTAEngine |
| AGENT 6 | 7 | 2 | 8 | Risk subsystem (7 components) |
| AGENT 7 | 8 | 2 | 13 | LLM (4 providers + router) + Messaging (CloudEvents + Redis) |
| AGENT 8 | 9 | 3 | 5 | BaseAgent + 3 Day1 agents + registry |
| AGENT 9 | 10 | 3 | 7 | 7 support agents |
| AGENT 10 | 10 | 4 | 14 | Strategies + tools + improvement |
| AGENT 11 | 11 | 4 | 11 | Complete test suite |
| AGENT 12 | 12 | 5 | 8 | FastAPI + Docker + CI/CD + monitoring |

---

*This plan defines how 12 specialized build agents coordinate to produce TSAR from architecture spec to running, tested, deployable code in approximately 2.5 hours of parallel work.*

*Each agent has a clear scope, clear ownership, and clear verification. No merge conflicts. No ambiguity. No wasted work.*

*— Chief Engineer, TSAR Council*
