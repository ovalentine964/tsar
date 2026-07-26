# TSAR ENGINEERING TEAM PLAN
## Council Document — Chief Architect

**Version:** 1.0.0
**Date:** 2026-07-24
**Authority:** Chief Architect (Council Seat)
**Status:** APPROVED — Ready for Co-Founder Execution
**Reference:** TSAR_ARCHITECTURE.md v3.0.0

---

## TABLE OF CONTENTS

1. [Team Structure](#1-team-structure)
2. [Hierarchy & Command Chain](#2-hierarchy--command-chain)
3. [Task Assignment Protocol](#3-task-assignment-protocol)
4. [Quality Gates](#4-quality-gates)
5. [Build Order](#5-build-order)
6. [Risk & Mitigation](#6-risk--mitigation)

---

## 1. TEAM STRUCTURE

### 1.1 Agent Registry

The TSAR engineering team consists of **13 specialist agents**, each owning a discrete domain of the architecture. Every agent has a clear mandate, deliverables, and dependencies.

| # | Agent Codename | Mandate | Architecture Domain | Day1 Deliverables |
|---|---------------|---------|-------------------|-------------------|
| 1 | **Interface Builder** | Build all 5 ABCs + BackendRegistry | §2 Interface Layer | `src/interfaces/` — all 5 ABCs, data types, registry, convenience getters |
| 2 | **Backend Implementer** | Python backends for Day1 | §2.4–2.8 (Day1 impl) | CcxtGateway, PandasTAEngine, CcxtExecEngine, PyRiskEngine, OllamaProvider |
| 3 | **Agent Builder** | Build all 10 agents | §3 Agent Architecture | Agent classes, tool bindings, stream subscriptions, heartbeat logic |
| 4 | **Knowledge Store Builder** | Build all 5 knowledge stores | §4 Knowledge Stores | SQLite schemas, ORM models, CRUD operations, FTS5 index |
| 5 | **Risk Builder** | Build risk engine + guards + kill switch | §6 Risk Architecture | RiskEngine impl, circuit breakers, kill switch, anti-behavioral guards, watchdog |
| 6 | **Strategy Builder** | Build strategies + backtesting | §7 Strategy Architecture | Mean Reversion strategy, signal scoring, strategy genome storage |
| 7 | **LLM Builder** | Build LLM routing layer | §8 LLM Architecture | BaseLLMProvider, ModelRouter, ModelRegistry, OllamaProvider, config/models.yaml |
| 8 | **Comms Builder** | CloudEvents messaging + Redis Streams | §5 Communication Protocol | CloudEvents envelope, MessagePack serialization, Redis Streams pub/sub |
| 9 | **Test Builder** | Unit + integration tests | All domains | Test harness, mock backends, integration test suite, stress tests |
| 10 | **Config Builder** | All YAML configs + env management | §2.3, §8.4, §10, §11 | backends.yaml, models.yaml, resource_limits.yaml, exchanges.yaml, risk_limits.yaml |
| 11 | **Deploy Builder** | Docker, FastAPI, monitoring | §11 Deployment | Dockerfile, docker-compose.yml, FastAPI endpoints, Prometheus metrics |
| 12 | **DB Builder** | Database schema, migrations, backup | §4, §9 | tsar.db schema, migration scripts, backup automation, improvement tables |
| 13 | **Resource Builder** | Resource enforcer + tool registry | §10 Resource Management | ResourceEnforcer, per-tool profiles, circuit breaker, Prometheus metrics |

### 1.2 Agent Mandates — Detailed

#### Agent 1: Interface Builder

**Owns:** `src/interfaces/`
**Does NOT touch:** Backend implementations, agent code, configs

**Deliverables:**
- `src/interfaces/__init__.py` — convenience getters (`get_exchange_gateway()`, etc.)
- `src/interfaces/exchange.py` — `ExchangeGateway` ABC with all methods from §2.4
- `src/interfaces/pricing.py` — `PricingEngine` ABC with convenience methods from §2.5
- `src/interfaces/execution.py` — `ExecutionEngine` ABC from §2.6
- `src/interfaces/risk.py` — `RiskEngine` ABC from §2.7
- `src/interfaces/llm.py` — `BaseLLMProvider` ABC from §2.8
- `src/interfaces/registry.py` — `BackendRegistry` with `register()`, `create()`, `create_with_fallback()`, `swap()`, `record_call()`, `get_status()`
- `src/interfaces/types.py` — All data types: `Ticker`, `OHLCV`, `OrderBook`, `Trade`, `OrderResult`, `Position`, `Balance`, `StreamHandle`, `OrderSide`, `OrderType`, `OrderStatus`, `TimeInForce`, `ConnectionStatus`, `RiskCheckResult`, `PositionSizeResult`, `DrawdownState`, `LLMRequest`, `LLMResponse`, `LLMChunk`, `ModelCapabilities`, `IndicatorResult`, `Greeks`, `OHLCVBar`, `OrderRequest`, `Fill`, `SlippageReport`, `ExecutionResult`, `OptionType`, `Signal`
- `src/interfaces/proxy.py` — `FallbackProxy`, `InstrumentedBackend`

**Acceptance criteria:**
- All 5 ABCs importable and instantiable (abstract)
- All data types are Pydantic models with validation
- BackendRegistry can load from YAML, create with fallback, hot-swap
- Zero imports of concrete libraries (ccxt, pandas-ta, etc.)

---

#### Agent 2: Backend Implementer

**Owns:** `src/backends/`
**Depends on:** Interface Builder (ABCs must exist first)

**Deliverables:**
- `src/backends/exchange/ccxt_gateway.py` — CcxtGateway implementing ExchangeGateway
- `src/backends/pricing/pandas_ta_engine.py` — PandasTAEngine implementing PricingEngine
- `src/backends/execution/ccxt_exec_engine.py` — CcxtExecEngine implementing ExecutionEngine
- `src/backends/risk/py_risk_engine.py` — PyRiskEngine implementing RiskEngine
- `src/backends/llm/ollama_provider.py` — OllamaProvider implementing BaseLLMProvider

**Acceptance criteria:**
- Each backend passes its ABC's interface contract
- `CcxtGateway`: connects to Binance sandbox, fetches OHLCV, places paper orders
- `PandasTAEngine`: calculates RSI, EMA, ATR correctly against known values
- `CcxtExecEngine`: delegates to ExchangeGateway, calculates slippage
- `PyRiskEngine`: enforces all 9 hard rules from §6.1
- `OllamaProvider`: generates text via local Ollama, counts tokens

---

#### Agent 3: Agent Builder

**Owns:** `src/agents/`
**Depends on:** Interface Builder, Comms Builder, Knowledge Store Builder

**Deliverables (Day1 — 4 agents):**
- `src/agents/signal_scout.py` — Market scanning, signal scoring (10-factor model from §3.4.1)
- `src/agents/risk_guardian.py` — Trade gating, 10-point checklist, VETO protocol
- `src/agents/execution_sniper.py` — Order lifecycle, stop-loss management, P&L calculation
- `src/agents/orchestrator.py` — Health monitoring, alert routing, bootstrap coordination

**Deliverables (Level 2+ — 6 more agents):**
- `src/agents/macro_agent.py` — Macro regime, economic calendar, sentiment
- `src/agents/regime_detector.py` — HMM regime classification
- `src/agents/trade_philosopher.py` — Post-trade reflection, lesson extraction
- `src/agents/strategy_geneticist.py` — Strategy evolution, backtesting, retirement
- `src/agents/market_cartographer.py` — Cross-asset correlation
- `src/agents/execution_tracker.py` — Position reconciliation, fill monitoring

**Acceptance criteria:**
- Each agent subscribes to correct Redis streams per §3.3
- Each agent publishes CloudEvents with correct event types per §5.3
- Signal Scout produces signals with all 10 scoring factors
- Risk Guardian enforces all 10 checklist items
- Execution Sniper follows full order lifecycle (§3.4.3)

---

#### Agent 4: Knowledge Store Builder

**Owns:** `src/stores/`
**Depends on:** DB Builder (schemas must exist)

**Deliverables:**
- `src/stores/trade_memory.py` — CRUD for trade_records table
- `src/stores/strategy_genomes.py` — CRUD for strategy_genomes, strategy_performance, strategy_mutations
- `src/stores/pattern_library.py` — CRUD for patterns, pattern_observations, pattern_relationships
- `src/stores/lesson_archive.py` — CRUD + FTS5 search for lessons, lesson_applications, lesson_violations
- `src/stores/regime_history.py` — CRUD for regime_history

**Acceptance criteria:**
- All stores use parameterized SQL (no injection)
- Trade Memory: stores full trade lifecycle with all fields from §4.1
- Lesson Archive: FTS5 full-text search returns ranked results
- Pattern Library: tracks occurrences, success rates, relationships

---

#### Agent 5: Risk Builder

**Owns:** `src/risk/`
**Depends on:** Interface Builder, Comms Builder, Config Builder

**Deliverables:**
- `src/risk/guard.py` — Risk evaluation engine (10-point checklist implementation)
- `src/risk/position_sizer.py` — Half-Kelly position sizing, 2% per-trade cap
- `src/risk/circuit_breaker.py` — GREEN/YELLOW/ORANGE/RED state machine
- `src/risk/kill_switch.py` — Dual-write kill switch (Redis + file)
- `src/risk/watchdog.py` — Three-tier watchdog (Governor + Monitor + systemd)
- `src/risk/anti_behavioral.py` — Revenge trading, greed, FOMO, overconfidence guards
- `src/risk/recovery.py` — Gated recovery protocol (ORANGE + RED paths)
- `src/risk/stress_test.py` — Historical scenario replay (7 scenarios from §6.7)

**Acceptance criteria:**
- Kill switch survives Redis failure (file fallback works)
- Circuit breaker transitions correctly through all states
- Anti-behavioral guards trigger at correct thresholds
- Stress tests pass all 7 historical scenarios
- All risk rules are deterministic — zero LLM involvement

---

#### Agent 6: Strategy Builder

**Owns:** `src/strategies/`
**Depends on:** Interface Builder, Knowledge Store Builder, LLM Builder

**Deliverables:**
- `src/strategies/base.py` — Base strategy interface
- `src/strategies/mean_reversion.py` — Day1 Mean Reversion strategy (§7.1)
- `src/strategies/signal_scorer.py` — 10-factor signal scoring (§3.4.1)
- `src/strategies/evolution.py` — Strategy evolution pipeline (§7.5)
- `src/strategies/backtest.py` — Backtesting engine wrapper (Level 2+, vectorbt)
- `src/strategies/portfolio.py` — Strategy portfolio allocation (§7.3)

**Acceptance criteria:**
- Mean Reversion: entry/exit rules match §7.1 exactly
- Signal scoring: weights sum to 100%, all 10 factors implemented
- Strategy genomes persist to database correctly
- Evolution pipeline: propose → backtest → paper → live flow works

---

#### Agent 7: LLM Builder

**Owns:** `src/llm/`
**Depends on:** Config Builder

**Deliverables:**
- `src/llm/provider.py` — BaseLLMProvider abstract (if not handled by Interface Builder)
- `src/llm/ollama_provider.py` — Ollama implementation
- `src/llm/openai_provider.py` — OpenAI implementation (Level 2+)
- `src/llm/anthropic_provider.py` — Anthropic implementation (Level 2+)
- `src/llm/deepseek_provider.py` — DeepSeek implementation
- `src/llm/router.py` — ModelRouter (task_type → provider/model)
- `src/llm/registry.py` — ModelRegistry (provider instances, fallback chains, circuit breakers)
- `src/llm/cost_tracker.py` — Per-model cost tracking, budget enforcement
- `config/models.yaml` — Complete model configuration

**Acceptance criteria:**
- Zero model names in agent code — only task_type references
- Router correctly routes all 12 task types from §8.3
- Fallback chain works: primary fails → fallback activates
- Circuit breaker: opens after 5 failures, recovers after 60s
- Cost tracker: enforces daily/monthly limits

---

#### Agent 8: Comms Builder

**Owns:** `src/comms/`
**Depends on:** None (foundational)

**Deliverables:**
- `src/comms/cloud_event.py` — CloudEvents v1.0 envelope (§5.2)
- `src/comms/serializer.py` — MessagePack encoder/decoder
- `src/comms/redis_streams.py` — Redis Streams producer/consumer
- `src/comms/stream_manager.py` — Stream topology manager (all 13 streams from §3.3)
- `src/comms/types.py` — All event types from §5.3

**Acceptance criteria:**
- CloudEvents envelope passes CNCF v1.0 spec validation
- MessagePack serialization: round-trip encode/decode preserves all fields
- Redis Streams: produce/consume works with `ce_` prefixed fields
- All 13 stream names from §3.3 are registered
- All event types from §5.3 are defined as constants

---

#### Agent 9: Test Builder

**Owns:** `tests/`
**Depends on:** All other agents (tests their code)

**Deliverables:**
- `tests/conftest.py` — Shared fixtures, mock backends, test database
- `tests/unit/` — Unit tests for every module
- `tests/integration/` — Integration tests for agent pipelines
- `tests/stress/` — Stress tests (kill switch, circuit breakers, resource limits)
- `tests/backtest/` — Strategy backtest validation
- `tests/fixtures/` — Test data (OHLCV samples, trade records, etc.)

**Acceptance criteria:**
- Unit test coverage ≥ 80% for all modules
- Integration tests cover full trade lifecycle (signal → risk → execution → reflection)
- Stress tests verify kill switch under Redis failure
- All 7 historical stress scenarios pass (§6.7)

---

#### Agent 10: Config Builder

**Owns:** `config/`
**Depends on:** None (foundational)

**Deliverables:**
- `config/backends.yaml` — Interface-to-backend mapping (§2.3)
- `config/models.yaml` — LLM model routing (§8.4)
- `config/resource_limits.yaml` — Per-tool resource limits (§10.3)
- `config/exchanges.yaml` — Exchange credentials and endpoints
- `config/risk_limits.yaml` — Risk parameters (§6.1 canonical values)
- `config/streams.yaml` — Redis stream topology
- `config/agents.yaml` — Agent configuration (cycle times, model tiers)
- `.env.example` — Environment variable template

**Acceptance criteria:**
- All configs are valid YAML with Pydantic validation
- No secrets in configs — all via environment variables
- backends.yaml: default points to Day1 Python backends
- models.yaml: all 12 task types configured per §8.3
- risk_limits.yaml: all canonical values from §6.1

---

#### Agent 11: Deploy Builder

**Owns:** `deploy/`, `src/api/`
**Depends on:** All other agents

**Deliverables:**
- `Dockerfile` — Multi-stage build (Python 3.12 + Rust 1.79)
- `docker-compose.yml` — All services (app, redis, prometheus, grafana)
- `src/api/main.py` — FastAPI application with all endpoints from §11.3
- `src/api/auth.py` — API key authentication
- `src/metrics/` — Prometheus metric definitions
- `deploy/prometheus.yml` — Prometheus scrape config
- `deploy/grafana/` — Dashboard JSON exports
- `deploy/systemd/` — Watchdog systemd service file

**Acceptance criteria:**
- `docker-compose up` brings up all services
- FastAPI serves all 12 endpoints from §11.3
- Prometheus scrapes TSAR metrics correctly
- Watchdog systemd service restarts on crash

---

#### Agent 12: DB Builder

**Owns:** Database schemas, migrations, backup
**Depends on:** Config Builder

**Deliverables:**
- `src/db/schema.sql` — Complete SQLite schema (all tables from §4 + §9)
- `src/db/migrations/` — Migration scripts (versioned)
- `src/db/connection.py` — Database connection manager (WAL mode, pragmas)
- `src/db/backup.py` — 3-tier backup automation (§11.5)
- `src/db/audit.py` — Immutable audit log (JSONL hash chain)

**Acceptance criteria:**
- Schema creates all tables from §4.1–4.5 + §9.5
- FTS5 index on lessons works
- WAL mode enabled, foreign keys enforced
- Backup: hot (15min), warm (daily), cold (weekly) automated
- Audit log: append-only JSONL with SHA-256 chain

---

#### Agent 13: Resource Builder

**Owns:** `src/resources/`
**Depends on:** Config Builder, Comms Builder

**Deliverables:**
- `src/resources/enforcer.py` — ResourceEnforcer (pre/post execution monitoring)
- `src/resources/guard.py` — ResourceGuard (per-tool profiles from §10.3)
- `src/resources/circuit_breaker.py` — Resource-aware circuit breaker (§10.5)
- `src/resources/metrics.py` — Prometheus metrics for resource usage
- `src/resources/process_limits.py` — Process-level RLIMIT enforcement (§10.7)

**Acceptance criteria:**
- Enforcer kills tools exceeding memory (256MB) or wall time (30s)
- Circuit breaker opens after 3 consecutive violations
- Process limits enforce RSS 512MB, CPU 60s, FD 256
- Prometheus metrics report per-tool resource usage

---

## 2. HIERARCHY & COMMAND CHAIN

### 2.1 Organizational Chart

```
                    ┌─────────────────────┐
                    │     CO-FOUNDER       │
                    │   (Orchestrator)     │
                    │  Final authority     │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   CHIEF ARCHITECT    │
                    │  (This document)     │
                    │  Design authority    │
                    └──────────┬──────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
    ┌─────▼─────┐      ┌──────▼──────┐      ┌─────▼─────┐
    │  TIER 1   │      │   TIER 2    │      │  TIER 3   │
    │ Foundation│      │   Core      │      │  Support  │
    └─────┬─────┘      └──────┬──────┘      └─────┬─────┘
          │                    │                    │
    ┌─────┴─────┐      ┌──────┴──────┐      ┌─────┴─────┐
    │           │      │             │      │           │
  Config    Comms   Interface    DB     Test      Deploy
  Builder   Builder  Builder   Builder  Builder   Builder
                         │
           ┌─────────────┼─────────────┐
           │             │             │
        Backend      Agent        Knowledge
        Implementer  Builder      Store Builder
           │             │             │
           │        ┌────┴────┐        │
           │        │         │        │
        LLM      Risk      Strategy  Resource
        Builder  Builder   Builder   Builder
```

### 2.2 Tier Definitions

| Tier | Agents | Rationale | Parallelizable? |
|------|--------|-----------|-----------------|
| **Tier 1 — Foundation** | Config Builder, Comms Builder | Zero dependencies. Everything else needs configs and comms. | ✅ Fully |
| **Tier 2 — Core** | Interface Builder, DB Builder | Depend only on Tier 1. All business logic depends on these. | ✅ Fully |
| **Tier 3 — Domain** | Backend Implementer, Agent Builder, Knowledge Store Builder | Depend on Tier 2. Build the actual trading system. | ✅ Mostly (some cross-deps) |
| **Tier 4 — Specialized** | LLM Builder, Risk Builder, Strategy Builder, Resource Builder | Depend on Tier 3 interfaces. Build specific subsystems. | ✅ Fully |
| **Tier 5 — Support** | Test Builder, Deploy Builder | Depend on all above. Validate and package. | ⚠️ Sequential (test after code) |

### 2.3 Approval Chain

```
Agent completes task
       │
       ▼
Agent self-reviews against acceptance criteria
       │
       ▼
Agent reports completion to Chief Architect
       │
       ▼
Chief Architect reviews:
  1. Does code match architecture doc?
  2. Do interfaces match ABCs?
  3. Are configs valid?
  4. Do tests pass?
       │
       ├── PASS → Mark complete, unblock dependents
       │
       └── FAIL → Return with specific feedback
              │
              ▼
         Agent fixes and resubmits
```

**Escalation:** If an agent cannot resolve an architectural conflict, escalate to Chief Architect. If Chief Architect cannot resolve, escalate to Co-Founder.

### 2.4 Authority Matrix

| Decision | Who Decides |
|----------|-------------|
| Architecture design | Chief Architect |
| Build order / priorities | Chief Architect |
| Code implementation details | Individual Agent |
| Interface contracts | Chief Architect (immutable once set) |
| Config values | Config Builder (validated by Chief Architect) |
| Test pass/fail | Test Builder (criteria set by Chief Architect) |
| Deploy to production | Co-Founder only |
| Risk parameter changes | Co-Founder only (canonical values are locked) |
| Agent additions/removals | Chief Architect + Co-Founder |

---

## 3. TASK ASSIGNMENT PROTOCOL

### 3.1 Task Creation

Tasks are created by the Chief Architect and assigned to agents. Each task has a unique ID and clear boundaries.

**Task ID Format:** `TSAR-{AGENT_NUM}-{SEQ}` (e.g., `TSAR-1-001`)

**Task Card Template:**
```yaml
task_id: TSAR-1-001
agent: Interface Builder
title: "Implement ExchangeGateway ABC"
priority: P0  # P0=critical, P1=high, P2=normal, P3=low
phase: 1  # Build phase (see §5)
depends_on: []  # Task IDs this blocks on
blocks: [TSAR-2-001, TSAR-3-001]  # Tasks this blocks
files:
  - src/interfaces/exchange.py
  - src/interfaces/types.py
acceptance_criteria:
  - "ExchangeGateway ABC has all methods from §2.4"
  - "All data types are Pydantic models"
  - "Zero concrete imports"
estimated_complexity: M  # S/M/L/XL
```

### 3.2 File Locking Protocol

**Problem:** Two agents working on the same file = merge conflicts, lost work, corruption.

**Solution:** Explicit file ownership. No two agents may edit the same file simultaneously.

**Rules:**
1. Each task card declares its `files` list — the files it will create or modify
2. Before starting work, an agent MUST check that no other active task claims the same files
3. If a conflict exists, the lower-priority task waits
4. Shared files (e.g., `src/interfaces/__init__.py`) are owned by one agent and modified via pull request to that agent

**File Ownership Registry:**

| Directory | Owner Agent | Other Agents May... |
|-----------|-------------|-------------------|
| `src/interfaces/` | Interface Builder | Read only. Submit changes via Interface Builder. |
| `src/backends/` | Backend Implementer | Read only. |
| `src/agents/` | Agent Builder | Read only. |
| `src/stores/` | Knowledge Store Builder | Read only. |
| `src/risk/` | Risk Builder | Read only. |
| `src/strategies/` | Strategy Builder | Read only. |
| `src/llm/` | LLM Builder | Read only. |
| `src/comms/` | Comms Builder | Read only. |
| `src/db/` | DB Builder | Read only. |
| `src/resources/` | Resource Builder | Read only. |
| `src/api/` | Deploy Builder | Read only. |
| `src/metrics/` | Deploy Builder | Read only. |
| `config/` | Config Builder | Read only. Submit changes via Config Builder. |
| `tests/` | Test Builder | Read only. Submit test requests via Test Builder. |
| `deploy/` | Deploy Builder | Read only. |
| `data/` | DB Builder | Read only. |

### 3.3 Dependency Tracking

Dependencies are tracked via the task card's `depends_on` and `blocks` fields.

**Dependency Graph Rules:**
1. An agent cannot start a task until ALL `depends_on` tasks are marked COMPLETE
2. When a task is marked COMPLETE, the Chief Architect notifies all agents whose tasks are `blocked` by it
3. Circular dependencies are forbidden — the Chief Architect validates the DAG before assignment

**Critical Path:** The longest chain of dependent tasks determines minimum build time. See §5.4.

### 3.4 Task Lifecycle

```
CREATED → ASSIGNED → IN_PROGRESS → REVIEW → COMPLETE
                  ↓                        ↓
              BLOCKED                   REJECTED → IN_PROGRESS
```

| Status | Meaning | Who Sets |
|--------|---------|----------|
| CREATED | Task defined, not yet assigned | Chief Architect |
| ASSIGNED | Agent notified, waiting for dependencies | Chief Architect |
| IN_PROGRESS | Agent actively working | Agent |
| BLOCKED | Waiting on dependency | Chief Architect |
| REVIEW | Agent claims complete, awaiting review | Agent |
| COMPLETE | Reviewed and accepted | Chief Architect |
| REJECTED | Review failed, needs rework | Chief Architect |

### 3.5 Communication Protocol Between Agents

Agents do NOT talk to each other directly. All coordination goes through the Chief Architect.

```
Agent A needs something from Agent B
       │
       ▼
Agent A submits request to Chief Architect
       │
       ▼
Chief Architect evaluates:
  - Is this a legitimate cross-dependency?
  - Can it be resolved via interface contract?
  - Does Agent B need to modify their deliverable?
       │
       ├── Interface contract resolves it → Chief Architect clarifies the spec
       │
       └── Agent B must change → Chief Architect creates new task for Agent B
```

---

## 4. QUALITY GATES

### 4.1 Gate 1: Interface Compliance

**Applies to:** All agents that implement interfaces
**Checked by:** Chief Architect + Test Builder

| Check | Criteria | Pass/Fail |
|-------|----------|-----------|
| ABC compliance | All abstract methods implemented | Must pass |
| Type safety | All parameters and returns match type hints | Must pass |
| Pydantic validation | All data models validate correctly | Must pass |
| No concrete imports | Backend code never imports ccxt, pandas-ta, etc. directly | Must pass |
| Registry integration | Backend registers correctly with BackendRegistry | Must pass |

### 4.2 Gate 2: Code Quality

**Applies to:** All agents
**Checked by:** Test Builder

| Check | Criteria | Tool |
|-------|----------|------|
| Linting | Zero errors, zero warnings | `ruff` |
| Type checking | Zero errors | `mypy --strict` |
| Docstrings | All public methods documented | `ruff` + manual |
| No hardcoded values | All magic numbers in configs | Manual review |
| No secrets | No API keys, passwords in code | `detect-secrets` |

### 4.3 Gate 3: Test Coverage

**Applies to:** All agents
**Checked by:** Test Builder

| Component | Unit Test Coverage | Integration Tests | Stress Tests |
|-----------|-------------------|-------------------|--------------|
| Interfaces | 90% | ABC contract tests | — |
| Backends | 80% | Live exchange tests (sandbox) | Failover tests |
| Agents | 80% | Full pipeline tests | Load tests |
| Stores | 90% | CRUD + FTS5 tests | Concurrent access |
| Risk | 95% | Kill switch tests | All 7 stress scenarios |
| Strategies | 80% | Backtest validation | Edge cases |
| LLM | 80% | Fallback chain tests | Circuit breaker |
| Comms | 85% | Stream pub/sub tests | Message loss |
| Resources | 85% | Enforcer integration | Limit breach |
| DB | 90% | Migration tests | Corruption recovery |

### 4.4 Gate 4: Risk System Validation

**Applies to:** Risk Builder
**Checked by:** Chief Architect (personally — this is the safety system)

| Check | Criteria | Priority |
|-------|----------|----------|
| Kill switch dual-write | Redis down → file activates kill switch | P0 — BLOCKING |
| Kill switch file fallback | File written before Redis | P0 — BLOCKING |
| Circuit breaker states | All 4 states (GREEN/YELLOW/ORANGE/RED) transition correctly | P0 — BLOCKING |
| Anti-behavioral guards | All 4 guards trigger at correct thresholds | P1 |
| Recovery protocol | ORANGE and RED recovery paths work | P1 |
| Stress scenarios | All 7 historical scenarios trigger kill switch | P0 — BLOCKING |
| Watchdog Tier 3 | systemd restarts watchdog on crash | P0 — BLOCKING |
| Risk rules deterministic | Same input → same output, always | P0 — BLOCKING |

**Gate 4 is the ONLY gate that blocks all other work if it fails.**

### 4.5 Gate 5: Integration Validation

**Applies to:** System-wide
**Checked by:** Test Builder + Chief Architect

| Test | Description | Pass Criteria |
|------|-------------|---------------|
| **Trade Lifecycle** | Signal → Risk → Execution → Reflection | Full cycle completes, trade logged |
| **Kill Switch Cascade** | Daily loss exceeds -2% | Kill switch fires within 5s |
| **Backend Failover** | Primary backend fails | Fallback activates within 1s |
| **LLM Fallback** | Primary model fails | Fallback model responds |
| **Redis Failure** | Redis goes down | Kill switch via file, system halts |
| **Agent Recovery** | Agent crashes | Orchestrator detects, restarts |
| **Config Reload** | Change backends.yaml | New backend loaded on restart |

### 4.6 Gate 6: Deployment Validation

**Applies to:** Deploy Builder
**Checked by:** Chief Architect

| Check | Criteria |
|-------|----------|
| Docker build | Builds without errors |
| docker-compose up | All services start |
| FastAPI health | `/health` returns 200 |
| Prometheus scrape | All TSAR metrics visible |
| Grafana dashboards | All dashboards load |
| Backup automation | Hot backup runs correctly |

---

## 5. BUILD ORDER

### 5.1 Phase Map

The build proceeds in **6 phases**, each with clear entry/exit criteria.

```
Phase 1: FOUNDATION          (Config + Comms + DB)
    │
    ▼
Phase 2: INTERFACES          (ABCs + Registry + Types)
    │
    ▼
Phase 3: BACKENDS + STORES   (Day1 implementations + Knowledge stores)
    │
    ├─── Phase 3A: Backends (Python)
    ├─── Phase 3B: Knowledge Stores
    └─── Phase 3C: LLM Layer
    │
    ▼
Phase 4: AGENTS + RISK       (Day1 agents + Risk system)
    │
    ├─── Phase 4A: Comms integration (Streams + CloudEvents)
    ├─── Phase 4B: Risk system (kill switch, guards, watchdog)
    └─── Phase 4C: Agents (Signal Scout, Risk Guardian, Execution Sniper, Orchestrator)
    │
    ▼
Phase 5: STRATEGIES + RESOURCES (Mean Reversion + Resource enforcer)
    │
    ▼
Phase 6: TEST + DEPLOY       (Full test suite + Docker + FastAPI)
```

### 5.2 Detailed Phase Breakdown

#### Phase 1: FOUNDATION (Parallel)

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-10-001 | Config Builder | Create all YAML configs | — | All Phase 2+ |
| TSAR-8-001 | Comms Builder | CloudEvents envelope + serializer | — | All Phase 4+ |
| TSAR-8-002 | Comms Builder | Redis Streams producer/consumer | TSAR-8-001 | All Phase 4+ |
| TSAR-12-001 | DB Builder | SQLite schema (all tables) | — | All Phase 3+ |
| TSAR-12-002 | DB Builder | Connection manager + migrations | TSAR-12-001 | All Phase 3+ |
| TSAR-12-003 | DB Builder | Backup automation | TSAR-12-002 | Phase 6 |

**Exit criteria:** All configs valid, comms layer functional, database created with all tables.

#### Phase 2: INTERFACES (Parallel)

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-1-001 | Interface Builder | Data types (Pydantic models) | TSAR-10-001 | All Phase 3+ |
| TSAR-1-002 | Interface Builder | ExchangeGateway ABC | TSAR-1-001 | TSAR-2-001 |
| TSAR-1-003 | Interface Builder | PricingEngine ABC | TSAR-1-001 | TSAR-2-002 |
| TSAR-1-004 | Interface Builder | ExecutionEngine ABC | TSAR-1-001 | TSAR-2-003 |
| TSAR-1-005 | Interface Builder | RiskEngine ABC | TSAR-1-001 | TSAR-2-004 |
| TSAR-1-006 | Interface Builder | BaseLLMProvider ABC | TSAR-1-001 | TSAR-7-001 |
| TSAR-1-007 | Interface Builder | BackendRegistry + proxy | TSAR-1-001 | All Phase 3+ |
| TSAR-1-008 | Interface Builder | Convenience getters (__init__) | TSAR-1-002..6 | All Phase 3+ |

**Exit criteria:** All 5 ABCs importable, BackendRegistry functional, all data types validated.

#### Phase 3: BACKENDS + STORES (Parallel Streams)

##### Phase 3A: Backends

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-2-001 | Backend Implementer | CcxtGateway | TSAR-1-002, TSAR-1-007 | TSAR-3-001, TSAR-3-003 |
| TSAR-2-002 | Backend Implementer | PandasTAEngine | TSAR-1-003, TSAR-1-007 | TSAR-3-001 |
| TSAR-2-003 | Backend Implementer | CcxtExecEngine | TSAR-1-004, TSAR-1-007 | TSAR-3-003 |
| TSAR-2-004 | Backend Implementer | PyRiskEngine | TSAR-1-005, TSAR-1-007 | TSAR-5-002 |
| TSAR-2-005 | Backend Implementer | OllamaProvider | TSAR-1-006, TSAR-1-007 | TSAR-7-001 |

##### Phase 3B: Knowledge Stores

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-4-001 | Knowledge Store Builder | Trade Memory store | TSAR-12-001 | TSAR-3-001 |
| TSAR-4-002 | Knowledge Store Builder | Strategy Genomes store | TSAR-12-001 | TSAR-6-001 |
| TSAR-4-003 | Knowledge Store Builder | Pattern Library store | TSAR-12-001 | TSAR-3-001 |
| TSAR-4-004 | Knowledge Store Builder | Lesson Archive store (FTS5) | TSAR-12-001 | TSAR-3-001 |
| TSAR-4-005 | Knowledge Store Builder | Regime History store | TSAR-12-001 | TSAR-3-001 |

##### Phase 3C: LLM Layer

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-7-001 | LLM Builder | ModelRouter + ModelRegistry | TSAR-1-006, TSAR-2-005, TSAR-10-001 | TSAR-3-001, TSAR-6-001 |
| TSAR-7-002 | LLM Builder | Cost tracker + circuit breaker | TSAR-7-001 | Phase 6 |

**Exit criteria:** All Day1 backends pass ABC contract tests. All stores CRUD-functional. LLM routing works.

#### Phase 4: AGENTS + RISK (Parallel Streams)

##### Phase 4A: Comms Integration

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-8-003 | Comms Builder | Stream topology (all 13 streams) | TSAR-8-002, TSAR-10-001 | TSAR-3-001..4 |
| TSAR-8-004 | Comms Builder | Event type constants | TSAR-8-001 | TSAR-3-001..4 |

##### Phase 4B: Risk System

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-5-001 | Risk Builder | Risk evaluation (10-point checklist) | TSAR-1-005, TSAR-2-004 | TSAR-3-002 |
| TSAR-5-002 | Risk Builder | Kill switch (dual-write) | TSAR-8-002, TSAR-10-001 | TSAR-3-002 |
| TSAR-5-003 | Risk Builder | Circuit breaker (4 states) | TSAR-5-001 | TSAR-3-002 |
| TSAR-5-004 | Risk Builder | Anti-behavioral guards | TSAR-5-001 | TSAR-3-002 |
| TSAR-5-005 | Risk Builder | Three-tier watchdog | TSAR-5-002 | Phase 6 |
| TSAR-5-006 | Risk Builder | Stress test suite | TSAR-5-001..4 | Phase 6 |
| TSAR-5-007 | Risk Builder | Recovery protocol | TSAR-5-003 | Phase 6 |

##### Phase 4C: Day1 Agents

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-3-001 | Agent Builder | Signal Scout | TSAR-2-001, TSAR-2-002, TSAR-4-001..5, TSAR-7-001, TSAR-8-003 | TSAR-6-001, Phase 6 |
| TSAR-3-002 | Agent Builder | Risk Guardian | TSAR-5-001..4, TSAR-8-003 | TSAR-3-003, Phase 6 |
| TSAR-3-003 | Agent Builder | Execution Sniper | TSAR-2-001, TSAR-2-003, TSAR-3-002, TSAR-8-003 | Phase 6 |
| TSAR-3-004 | Agent Builder | Orchestrator | TSAR-8-003 | Phase 6 |

**Exit criteria:** All 4 Day1 agents operational. Risk system passes Gate 4. Kill switch tested.

#### Phase 5: STRATEGIES + RESOURCES (Parallel)

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-6-001 | Strategy Builder | Mean Reversion strategy | TSAR-1-003, TSAR-4-002, TSAR-3-001 | Phase 6 |
| TSAR-6-002 | Strategy Builder | Signal scorer (10-factor) | TSAR-1-003, TSAR-4-001 | TSAR-3-001 (already done, integrates) |
| TSAR-13-001 | Resource Builder | ResourceEnforcer | TSAR-10-001, TSAR-8-002 | Phase 6 |
| TSAR-13-002 | Resource Builder | Per-tool profiles + circuit breaker | TSAR-13-001 | Phase 6 |
| TSAR-13-003 | Resource Builder | Process-level limits | TSAR-13-001 | Phase 6 |

**Exit criteria:** Mean Reversion strategy functional. Resource enforcer enforces limits.

#### Phase 6: TEST + DEPLOY (Sequential)

| Task ID | Agent | Task | Depends On | Blocks |
|---------|-------|------|------------|--------|
| TSAR-9-001 | Test Builder | Unit test suite (all modules) | All Phase 3-5 | TSAR-11-001 |
| TSAR-9-002 | Test Builder | Integration test suite | TSAR-9-001 | TSAR-11-001 |
| TSAR-9-003 | Test Builder | Stress test suite | TSAR-9-001 | TSAR-11-001 |
| TSAR-11-001 | Deploy Builder | Dockerfile + docker-compose | TSAR-9-001..3 | TSAR-11-002 |
| TSAR-11-002 | Deploy Builder | FastAPI endpoints | TSAR-11-001 | TSAR-11-003 |
| TSAR-11-003 | Deploy Builder | Prometheus + Grafana | TSAR-11-002 | DONE |

**Exit criteria:** All tests pass. Docker deployment works. FastAPI serves all endpoints. Monitoring operational.

### 5.3 Critical Path

The minimum time to complete TSAR Day1 is determined by the **critical path** — the longest chain of dependent tasks:

```
TSAR-10-001 (configs)
    → TSAR-1-001 (data types)
    → TSAR-1-002..6 (ABCs)
    → TSAR-2-001 (CcxtGateway)
    → TSAR-3-001 (Signal Scout)
    → TSAR-6-001 (Mean Reversion)
    → TSAR-9-001 (tests)
    → TSAR-11-001 (deploy)
```

**Critical path length: 8 tasks, sequential.**

### 5.4 Parallelization Opportunities

| Phase | What Runs in Parallel | Agents Active |
|-------|----------------------|---------------|
| Phase 1 | Config + Comms + DB | Config Builder, Comms Builder, DB Builder (3 agents) |
| Phase 2 | All 5 ABCs + Registry | Interface Builder (1 agent, but tasks are parallelizable) |
| Phase 3 | Backends + Stores + LLM | Backend Impl, Store Builder, LLM Builder (3 agents) |
| Phase 4 | Risk + Agents + Comms integration | Risk Builder, Agent Builder, Comms Builder (3 agents) |
| Phase 5 | Strategy + Resources | Strategy Builder, Resource Builder (2 agents) |
| Phase 6 | Tests → Deploy | Test Builder then Deploy Builder (2 agents, sequential) |

**Maximum parallelism: 3 agents working simultaneously.**

### 5.5 Gantt-Style Overview

```
Week 1:  [Config][Comms  ][DB    ]  ← Phase 1 (parallel)
         [Types][ABC x5  ][Reg   ]  ← Phase 2 (parallel)
Week 2:  [CcxtGW][PandTA][CcxtEx]  ← Phase 3A
         [TradeM][StratG][PatLib]  ← Phase 3B (parallel)
         [LLM Router       ]      ← Phase 3C (parallel)
Week 3:  [Risk eval][KillSw][CB ]  ← Phase 4B
         [Streams][Events  ]       ← Phase 4A
Week 4:  [Signal Scout][RiskG]    ← Phase 4C
         [Exec Sniper][Orch]      ← Phase 4C (parallel)
Week 5:  [Mean Rev][SignalSc]     ← Phase 5
         [ResourceEnforcer]        ← Phase 5 (parallel)
Week 6:  [Unit Tests]             ← Phase 6
         [Integration Tests]       ← Phase 6
         [Stress Tests]            ← Phase 6
Week 7:  [Docker][FastAPI]        ← Phase 6
         [Prometheus][Grafana]     ← Phase 6
```

**Estimated timeline: 7 weeks for Day1 with 3 parallel agents.**

---

## 6. RISK & MITIGATION

### 6.1 Build Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Agent produces non-compliant code | High | Medium | Gate 1 (interface compliance) catches early |
| Circular dependency between tasks | High | Low | Chief Architect validates DAG before assignment |
| File conflict between agents | High | Medium | File ownership registry (§3.2) prevents this |
| Risk system has bugs | Critical | Low | Gate 4 (personally reviewed by Chief Architect) |
| LLM provider unavailable for testing | Medium | Medium | Ollama is local — always available |
| ccxt API changes mid-build | Low | Low | Pin ccxt version in requirements.txt |
| Redis not available for testing | Medium | Low | Docker Compose provides Redis |
| Scope creep (Level 2+ features in Day1) | High | High | Chief Architect enforces Day1 scope strictly |

### 6.2 Scope Control

**Day1 scope is LOCKED to:**
- 4 agents (Signal Scout, Risk Guardian, Execution Sniper, Orchestrator)
- 5 backends (all Python)
- 1 strategy (Mean Reversion)
- 1 market (BTC/USDT)
- 1 LLM provider (Ollama)
- $10 capital

**Anything else is Level 2+.** The Chief Architect will reject any Day1 task that introduces Level 2+ features.

### 6.3 Contingency: What If an Agent Fails?

| Scenario | Response |
|----------|----------|
| Agent produces wrong code | Chief Architect rejects, provides specific feedback, agent reworks |
| Agent cannot complete task | Chief Architect reassigns to another agent or simplifies scope |
| Architecture change needed | Chief Architect updates architecture doc, reassigns affected tasks |
| Dependency delayed | Downstream agents work on non-blocked tasks; blocked tasks wait |
| Multiple agents fail | Chief Architect escalates to Co-Founder for resource/priority decisions |

---

## APPENDIX: AGENT QUICK REFERENCE

```
┌─────────────────────────────────────────────────────────────────┐
│                    TSAR ENGINEERING TEAM                         │
│                                                                  │
│  TIER 1 (Foundation)                                             │
│  ├── Config Builder      → config/*.yaml                        │
│  └── Comms Builder       → src/comms/                           │
│                                                                  │
│  TIER 2 (Core)                                                   │
│  ├── Interface Builder   → src/interfaces/                       │
│  └── DB Builder          → src/db/                               │
│                                                                  │
│  TIER 3 (Domain)                                                 │
│  ├── Backend Implementer → src/backends/                         │
│  ├── Agent Builder       → src/agents/                           │
│  └── Knowledge Store     → src/stores/                           │
│                                                                  │
│  TIER 4 (Specialized)                                            │
│  ├── LLM Builder         → src/llm/                              │
│  ├── Risk Builder        → src/risk/                             │
│  ├── Strategy Builder    → src/strategies/                       │
│  └── Resource Builder    → src/resources/                        │
│                                                                  │
│  TIER 5 (Support)                                                │
│  ├── Test Builder        → tests/                                │
│  └── Deploy Builder      → deploy/, src/api/                     │
│                                                                  │
│  TOTAL: 13 agents | 6 phases | ~7 weeks | 3 parallel max        │
└─────────────────────────────────────────────────────────────────┘
```

---

*This document defines the TSAR engineering team structure, task assignment protocol, quality gates, and build order.*
*All engineering work references this plan alongside TSAR_ARCHITECTURE.md v3.0.0.*

*Chief Architect — 2026-07-24*
