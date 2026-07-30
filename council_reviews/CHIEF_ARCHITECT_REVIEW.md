# TSAR COUNCIL OF 5 — CHIEF ARCHITECT REVIEW (v2)
## Comprehensive Architecture Review

**Reviewer:** Chief Architect (Council Seat #2)
**Date:** 2026-07-30
**Scope:** Full codebase (97 Python, 28 Dart, 28 Rust, 19 C++ files) + architecture docs + prior reviews
**Framework:** System Architecture, Integration Integrity, Scalability, Knowledge Layer, Backend Swappability, Mobile App, Deployment, Jensen Huang Doctrine
**Prior Reviews:** CHIEF_ARCHITECT_REVIEW.md (8.4/10, 2026-07-24), SUPER_AGENT_ARCHITECTURE_REVIEW.md (8.1/10)
**Verdict:** **CONDITIONAL PASS** — Score: **7.8/10**

---

## EXECUTIVE SUMMARY

TSAR is an architecturally ambitious, well-documented trading super agent system. After reviewing the complete codebase (not just design docs — the actual implementation), I find a system that is **further along than most reviews suggest**, with real working code for the interface layer, risk engine, knowledge stores, flywheel health, backtest engine, LLM routing, and CloudEvents messaging. The architecture is sound. The implementation is substantive.

However, the codebase reveals gaps that the design documents gloss over. The most critical: **the flywheel is partially wired but not end-to-end verified**, the **backend swap promise has hidden coupling**, and the **mobile app covers ~70% of the API surface but lacks real-time capability**. The multi-language strategy (Python→Rust→C++) is aspirational — only Python backends exist, and the Rust/C++ directories contain scaffolding, not implementations.

This is not a design-only review. I reviewed every Python module in `src/`, the Flutter app, CI/CD pipelines, Docker config, and all 5 interface ABCs. The verdict reflects what exists, not what's planned.

---

## 1. SYSTEM ARCHITECTURE

### Score: 8.5/10

#### 1.1 Interface Layer — The Crown Jewel

The 5 abstract base classes in `src/interfaces/` are **exceptionally well-designed**:

| ABC | Lines | Quality | Assessment |
|-----|-------|---------|------------|
| `ExchangeGateway` | ~150 | Strong | Clean lifecycle (connect/disconnect/health), market data, streaming, account, and order management. Async throughout. |
| `PricingEngine` | ~80 | Good | Indicator calculation, Greeks, OHLCV aggregation. Concrete convenience methods (RSI, EMA, ATR) in the ABC — good design. |
| `ExecutionEngine` | ~100 | Good | Order execution, cancellation, fill tracking, slippage. TWAP/VWAP stubs for Level 2+. |
| `RiskEngine` | ~120 | Exceptional | 7-layer veto protocol, position sizing, drawdown monitoring, kill switch. All deterministic. Zero LLM. |
| `LLMProvider` | ~90 | Strong | Generate, stream, count_tokens, capabilities, health_check. Clean abstraction. |

**Key strength:** `src/interfaces/types.py` (450+ lines) defines ALL shared data types as frozen dataclasses with full docstrings. `Signal`, `RiskDecision`, `Portfolio`, `DrawdownState`, `LLMResponse`, `ModelCapabilities` — every type is immutable, typed, and documented. This is the contract that makes backend swappability real.

**Key strength:** The `BackendRegistry` (`src/interfaces/backend_registry.py`) has a clean API: `register()`, `create()`, `get_fallback_chain()`, `get_backend_status()`, `load_from_config()`. The `_register_defaults()` method hard-registers all Python backends. The `_import_class()` helper supports dotted-path imports from YAML config.

**Assessment:** The interface layer is architecturally sound and actually implemented. This is not a design doc — these are real Python ABCs with real implementations behind them.

#### 1.2 BackendRegistry — Config-Driven Swapping

`config/backends.yaml` maps interfaces to implementations:
```yaml
exchange_gateway:
  primary: "src.backends.python.ccxt_gateway.CcxtGateway"
  fallback:
    - path: "src.interfaces.exchange.rust_gateway.RustGateway"
      priority: 200
```

**However**, there's a hidden coupling issue: `_register_defaults()` in `backend_registry.py` imports ALL Python backends at init time, regardless of what's in `backends.yaml`. If you configure a Rust backend as primary, the Python backends still get imported (and will fail if their dependencies aren't installed). The YAML config loading (`load_from_config()`) registers additional backends but doesn't override the defaults.

**Fix required:** `_register_defaults()` should be conditional — only register backends that are actually configured, or make it lazy (register on first use).

#### 1.3 Multi-Language Strategy

| Language | Files | Status |
|----------|-------|--------|
| Python | 97 `.py` files | ✅ Complete — all backends, agents, knowledge, risk, API |
| Rust | 28 `.rs` files | ⚠️ Scaffolding — crate structure exists, PyO3 bindings stubbed |
| C++ | 19 `.cpp`/`.h` files | ⚠️ Scaffolding — directory structure only |

The Rust and C++ directories contain project structure (Cargo.toml, CMakeLists.txt, crate modules) but **not production-ready implementations**. The PyO3 bindings reference is in `pyproject.toml` (`maturin>=1.4` in `[project.optional-dependencies] rust`) but no actual compiled extension exists.

**This is fine for Day1** — the architecture explicitly states Python is the starting point, with Rust at Level 2 and C++ at Level 4. But the README and MASTER_BLUEPRINT give the impression that Rust/C++ code exists and is "future-ready from day one." It's not. It's future-ready in architecture only.

---

## 2. INTEGRATION INTEGRITY

### Score: 7.5/10

#### 2.1 CloudEvents Messaging — Properly Implemented

`src/comms/events.py` is a **complete, production-quality CloudEvents v1.0 implementation**:

- `CloudEvent` frozen dataclass with all standard + TSAR extension attributes
- `to_dict()`, `to_json()`, `to_msgpack()` serialization
- `from_dict()`, `from_json()`, `from_msgpack()` deserialization
- `to_redis_fields()` / `from_redis_fields()` for Redis Stream integration (ce_ prefix)
- ULID generation (Crockford Base32, 48-bit timestamp + 80-bit random)
- W3C trace ID generation
- `encode_event()` / `decode_event()` helpers

**This is real code that works.** The CloudEvents adoption identified in the SUPER_AGENT_ARCHITECTURE_REVIEW.md as a "Critical Gap" has been fully addressed.

However, `src/comms/event_bus.py` is a **simple in-process EventBus** (20 lines) that is separate from the Redis Streams-based `EventPublisher`/`EventSubscriber`. The orchestrator uses BOTH — `EventPublisher` for agent-to-agent comms and `EventBus` for the flywheel shadow extraction loop. This dual-transport is a code smell — the flywheel should use the same CloudEvents transport as everything else.

#### 2.2 Agent Communication Topology

`src/agents/base.py` provides a solid base class with:
- Lifecycle management (start/stop with graceful shutdown)
- CloudEvents publishing via `EventPublisher`
- CloudEvents subscribing via `EventSubscriber`
- Health heartbeat
- Structured logging
- Metrics tracking (events published/received, errors, cycle time)

The `Orchestrator` (`src/agents/orchestrator.py`) manages agent lifecycles, runs the trading pipeline, and handles the shadow extraction flywheel loop. It imports and starts `SignalScout`, `RiskGuardian`, and `ExecutionSniper` as sub-agents.

**Concern:** The agent registry in `Orchestrator._load_agent_registry()` only registers 3 agents (SignalScout, RiskGuardian, ExecutionSniper). The other 7 agents (Macro, Regime Detector, Trade Philosopher, Strategy Geneticist, Market Cartographer, Execution Tracker) are defined in separate files but NOT wired into the orchestrator. This means the full 10-agent system is not operational — only the Day1 3-agent core works.

#### 2.3 Single Points of Failure

| Component | SPOF Risk | Mitigation |
|-----------|-----------|------------|
| Redis | HIGH | Kill switch has file fallback. Agent comms depend on Redis — if Redis dies, agents can't communicate. |
| SQLite | MEDIUM | WAL mode, busy_timeout=5000. No replication. Single file = single point. |
| Ollama (local LLM) | LOW | Circuit breaker + fallback chain (Ollama → DeepSeek → OpenAI). |
| Orchestrator | HIGH | If orchestrator crashes, all agents stop. No watchdog for the orchestrator itself. |
| Kill Switch file | LOW | Dual-write (file + Redis). External kill via file write. |

**Critical gap:** The three-tier watchdog architecture described in TSAR_ARCHITECTURE.md §6.3 (Governor + Monitor + Watchdog) is **not implemented**. The `KillSwitch` class exists and works, but there's no `AutoKillDetector` process, no systemd watchdog service, and no heartbeat monitoring between tiers. The kill switch is single-process — if the main process hangs, the kill switch can't fire.

---

## 3. SCALABILITY

### Score: 7.0/10

#### 3.1 Capital Scaling Path

| Stage | Capital | What Breaks First |
|-------|---------|-------------------|
| **$10** | Day1 | Nothing — paper mode, single exchange, 1 strategy |
| **$100** | Level 2 | Exchange rate limits (ccxt REST polling), LLM latency |
| **$1K** | Level 3 | SQLite concurrent writes (WAL helps but not enough for 10 agents) |
| **$10K** | Level 4 | Need Rust WebSocket for real-time data, need multi-exchange |
| **$100K+** | Level 5 | Need GPU Monte Carlo for VaR, need FIX protocol, need PostgreSQL |

**What breaks first at scale:** SQLite. The system uses a single `tsar.db` file with WAL mode. With 10 agents all reading/writing, lock contention will become a bottleneck. The architecture correctly identifies the migration trigger (>100K trades or need concurrent access → PostgreSQL), but doesn't provide the migration path.

**What breaks second:** The polling-based exchange connectivity. ccxt REST API polling (every 5 minutes for Signal Scout) is fine for $10. At $1K+, you need real-time WebSocket data. The Rust WebSocket backend is the answer, but it's scaffolding, not code.

#### 3.2 Agent Scaling

The orchestrator dynamically manages agents via `add_agent()` / `remove_agent()`. This is good for scaling from 3 to 10 agents. However, all agents share a single `EventPublisher` and `EventSubscriber` instance — there's no connection pooling or per-agent Redis connections.

#### 3.3 LLM Scaling

The `ModelRouter` (`src/llm/router.py`) has proper circuit breakers per provider and cost tracking. The fallback chain works: primary → fallback1 → fallback2. This scales well — adding new providers is config-only.

**Concern:** The `CostTracker` only tracks cumulative costs in memory. No persistence. If the process restarts, cost history is lost. The `budget` config in `models.yaml` (daily_limit_usd, monthly_limit_usd) is specified but the router doesn't enforce it — there's no budget check before making LLM calls.

---

## 4. KNOWLEDGE LAYER

### Score: 8.0/10

#### 4.1 Five Knowledge Stores — Implemented

| Store | File | Tables | FTS5 | Status |
|-------|------|--------|------|--------|
| Trade Memory | `src/knowledge/trade_memory.py` | trade_records, trade_snapshots, trade_journal | ✅ trade_records_fts | ✅ Complete |
| Strategy Genomes | `src/knowledge/strategy_genomes.py` | strategy_genomes, strategy_performance, strategy_mutations | ✅ strategy_genomes_fts | ✅ Complete |
| Pattern Library | `src/knowledge/pattern_library.py` | patterns, pattern_observations, pattern_relationships | ✅ patterns_fts | ✅ Complete |
| Lesson Archive | `src/knowledge/lesson_archive.py` | lessons, lesson_applications, lesson_violations | ✅ lessons_fts | ✅ Complete |
| Regime State | `src/knowledge/regime_state.py` | regime_history | ❌ (not needed) | ✅ Complete |

**The FTS5 implementation is excellent.** `src/knowledge/fts_search.py` (`MemoryRecall` class) provides:
- Cross-store search across all 4 FTS5-indexed stores
- CJK/Thai/Arabic/Cyrillic support via unicode61 tokenizer + prefix matching
- LIKE fallback for CJK queries that FTS5 can't handle
- Snippet generation with `<b>` highlighting
- BM25 ranking
- Index rebuild and stats

This is the "Borrowing 2" from the MASTER_BLUEPRINT — and it's actually implemented, not just planned.

#### 4.2 Shadow Account Loop — Partially Wired

`src/knowledge/shadow_extractor.py` implements the EXTRACT phase:
- Reads closed trades from `TradeMemory`
- Groups by (symbol, strategy)
- Calls LLM to extract if-then rules
- Parses structured `TradingRule` objects

`src/knowledge/rule_validator.py` implements the validation phase (backtest extracted rules).

`src/knowledge/genome_mutator.py` implements the ADAPT phase (propose strategy mutations).

The orchestrator wires these together in `_initialize_shadow_loop()` and `_run_shadow_extraction()`.

**However:** The flywheel is not fully closed. The shadow extraction runs on a timer (every 24h by default, or every 10 trades). The mutation proposals are published to `tsar:stream:strategy_proposals`, but **no agent subscribes to this stream**. The `StrategyGeneticist` agent exists in code but is NOT wired into the orchestrator's agent registry. So mutations are proposed but never applied.

**This is the biggest gap in the flywheel:** TRADE → OBSERVE → REFLECT → EXTRACT → **[GAP]** → ADAPT. The EXTRACT step works. The ADAPT step doesn't connect back.

#### 4.3 Flywheel Health Score — Implemented

`src/metrics/flywheel.py` (`FlywheelHealthScore`) computes a composite health score from 10 weighted metrics. It supports:
- History tracking (last 500 entries)
- Trend computation (improving/stalling/declining)
- Component-level analysis (weakest 3 components)
- Persistence to JSON file
- Static builders from trade history and knowledge stats

This is well-implemented. The classification (healthy > 0.7, stalling 0.4-0.7, broken < 0.4) matches the architecture spec.

---

## 5. BACKEND SWAPPABILITY

### Score: 6.5/10

#### 5.1 The Promise vs Reality

**Promise:** "YAML config selects backend. No refactoring ever."

**Reality:** Mostly true, with caveats:

1. **Python backends work.** `CcxtGateway`, `PandasTAEngine`, `CcxtExecEngine`, `PythonRiskEngine`, `OllamaProvider`, `OpenAIProvider`, `DeepSeekProvider` — all registered and functional.

2. **Rust backends don't exist.** `config/backends.yaml` references `src.interfaces.exchange.rust_gateway.RustGateway` and `src.interfaces.pricing.rust_tick_engine.RustTick`, but these files don't exist. If you change the primary to a Rust backend, the system will crash on import.

3. **The registry has import-time coupling.** `_register_defaults()` imports ALL Python backends at module load. This means:
   - You can't run the system without ccxt installed, even if you're using a Rust gateway
   - You can't run without pandas-ta, even if you're using a Rust tick engine
   - The "swap via YAML" promise requires the old backend's dependencies to still be installed

4. **No interface conformance testing.** There's no test that verifies a new backend actually implements the ABC correctly. If `RustGateway` is registered but doesn't implement `subscribe_ticker()`, the error only surfaces at runtime.

#### 5.2 What Would Fix This

1. **Lazy registration:** Don't import backends until `create()` is called
2. **Interface conformance tests:** Abstract test suite that any backend must pass
3. **Dependency isolation:** Each backend should handle missing dependencies gracefully
4. **Backend verification on startup:** Validate that configured backends exist and implement required methods

---

## 6. MOBILE APP

### Score: 7.0/10

#### 6.1 Flutter App Architecture

The mobile app (`mobile/lib/`) has 28 Dart files organized into:

| Layer | Files | Purpose |
|-------|-------|---------|
| Models | 8 | Trade, Position, Risk, Factor, Knowledge, Mandate, Strategy |
| Providers | 10 | Dashboard, Trade, Portfolio, Risk, Factor, Knowledge, Mandate, Settings, Strategy |
| Screens | 6+ | Dashboard, Trades, Risk, Factors, Settings, Knowledge |
| Widgets | 4+ | Kill switch FAB, charts, cards |

#### 6.2 API Coverage

The app's `ApiService` connects to the FastAPI backend at port 8000. Based on the provider files, the app covers:

- ✅ Dashboard (P&L, win rate, equity curve, regime, flywheel health)
- ✅ Trade history (filters, infinite scroll, detail sheets)
- ✅ Risk gauges, circuit breaker status, open positions
- ✅ Factor library with category filter, IC/IR rankings
- ✅ Kill switch FAB with biometric confirmation
- ✅ Knowledge search (FTS5 across all stores)
- ✅ Mandate management (commit/revoke)
- ✅ Strategy monitoring

#### 6.3 Gaps

- **No real-time updates.** The app uses REST polling, not WebSocket. The architecture specifies WebSocket for real-time data, but the mobile app doesn't implement it. For a trading app, this is a significant UX gap — P&L updates will be delayed.
- **No offline mode.** If the server is unreachable, the app shows nothing. No cached data, no offline P&L.
- **No push notifications.** The app has no Firebase/APNs integration. Trade alerts only come through Telegram.

---

## 7. DEPLOYMENT

### Score: 7.5/10

#### 7.1 Docker Compose

`docker-compose.yml` is minimal but functional:
- Redis 7 with AOF persistence, memory limit (256MB), password auth
- TSAR app with health checks, volume mounts, config read-only
- Health check dependencies (app waits for Redis)
- Bridge network

**Missing:** No Prometheus, Grafana, Loki, or nginx containers. The architecture spec calls for a full monitoring stack, but Docker Compose only has Redis + app.

#### 7.2 CI/CD

`.github/workflows/ci.yml` has a solid 5-job pipeline:
1. **Lint** (ruff check + format)
2. **Type Check** (mypy --strict)
3. **Test** (pytest with Redis service, coverage)
4. **Security** (safety + bandit)
5. **Build** (Docker image, verify import)

**Good:** Tests run against a real Redis instance in CI. Coverage reports uploaded as artifacts.

**Missing:** No deployment step. The pipeline builds and verifies but doesn't deploy. No canary deployment, no staging environment.

#### 7.3 Production Readiness

| Aspect | Status | Assessment |
|--------|--------|------------|
| Docker | ✅ | Works for single-machine deployment |
| CI/CD | ✅ | Lint → Type → Test → Security → Build |
| Monitoring | ⚠️ | Prometheus metrics defined but no Grafana dashboards in Docker |
| Logging | ✅ | Structured logging (structlog), JSON format |
| Backup | ⚠️ | `make db-backup` exists but no automated backup schedule |
| Secrets | ⚠️ | `.env` file for API keys, no vault integration |
| Health checks | ✅ | `/health` endpoint, agent heartbeats |
| Graceful shutdown | ✅ | Signal handlers (SIGINT, SIGTERM), agent stop cascade |

---

## 8. JENSEN HUANG DOCTRINE ALIGNMENT

### 8.1 "The harness makes the model great" — **YES, mostly**

The harness IS the product. The 5 ABCs, BackendRegistry, Risk Governor, kill switch, anti-behavioral guards, drawdown circuit breakers — all deterministic, all LLM-free. The LLM enhances (narratives, reflections, rule extraction) but doesn't enable. The system works without any LLM — it just lacks narrative explanation.

**Gap:** The harness doesn't have an explicit "LLM-free mode" specification. What happens when ALL providers are down? The circuit breakers will trip, but the behavior isn't documented.

### 8.2 "Adjust the environment, not just the model" — **YES**

35 tools defined. 5 knowledge stores with FTS5 search. Deterministic risk guards. Anti-behavioral protections. The environment is shaped so the LLM can be brilliant within constraints.

**Gap:** The 35 tools are defined in the architecture spec but only ~15 are implemented in code. The tool registry isn't a runtime system — it's a specification.

### 8.3 "One job, not many" — **YES**

TSAR has ONE job: autonomous capital compounding under strict risk constraints. Every component serves this purpose. Not a chatbot. Not a general assistant. Not a multi-purpose trading platform.

### 8.4 "The flywheel compounds forever" — **PARTIALLY**

The flywheel is architecturally complete (TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT) but only partially wired:
- ✅ TRADE: Execution Sniper places orders
- ✅ OBSERVE: Trade Memory records everything
- ✅ REFLECT: Trade Philosopher generates reflections (but not wired into orchestrator)
- ✅ EXTRACT: Shadow Extractor extracts rules from trade history
- ❌ ADAPT: Genome Mutator proposes mutations, but Strategy Geneticist doesn't receive them

**The flywheel spins but doesn't close.** The EXTRACT → ADAPT gap means the system accumulates knowledge but doesn't automatically apply it.

### 8.5 "Open ecosystem = control" — **MOSTLY**

MIT license. Python + Rust + C++. SQLite local storage. YAML config. No vendor lock-in for core intelligence.

**Gap:** The multi-language promise is architectural, not actual. Only Python works. The Rust/C++ paths are scaffolding. Vendor independence is real for LLMs (Ollama, DeepSeek, OpenAI all supported) but not for execution backends (only ccxt works).

---

## 9. TOP 5 STRENGTHS

### 1. Interface Layer Design (9/10)
The 5 ABCs with frozen dataclass types are genuinely excellent. `types.py` alone is 450+ lines of well-typed, well-documented contracts. The `BackendRegistry` with YAML config loading, fallback chains, and hot-swap capability is production-quality architecture. This is the strongest part of the codebase.

### 2. Risk Engine (9/10)
The `RiskGovernor` implementing 7 deterministic layers (kill switch → validation → anti-FOMO → blackout → behavioral → drawdown → position limits) is institutional-grade. The `KillSwitch` with dual-write (file + Redis) and fail-safe defaults is exactly right for a trading system. The anti-behavioral guards (revenge, greed, FOMO, overconfidence) encode real trading psychology knowledge.

### 3. Knowledge Stores with FTS5 (8.5/10)
All 5 knowledge stores are implemented with real SQLite tables, FTS5 indexes, and cross-store search. The `MemoryRecall` class with CJK support, BM25 ranking, and LIKE fallback shows production-quality thinking. The shadow extraction pipeline (extract → validate → mutate) is real code, not just specs.

### 4. CloudEvents Messaging (8/10)
The CloudEvents v1.0 implementation in `events.py` is complete: ULID generation, MessagePack serialization, Redis Stream integration with `ce_` prefixed fields, W3C trace IDs. This replaces the proprietary `MessageEnvelope` format that was flagged in prior reviews.

### 5. LLM Routing with Circuit Breakers (8/10)
The `ModelRouter` with per-provider circuit breakers, cost tracking, fallback chains, and task-type routing is well-designed. Zero model names in agent code — all routing via `task_type`. The circuit breaker state machine (CLOSED → OPEN → HALF_OPEN → CLOSED) with configurable thresholds is correct.

---

## 10. TOP 5 RISKS/CONCERNS

### 1. Flywheel Not Fully Wired (CRITICAL)
The EXTRACT → ADAPT gap means the self-improvement loop doesn't close. `GenomeMutator` publishes to `tsar:stream:strategy_proposals`, but no agent subscribes. The `StrategyGeneticist` exists in code but isn't in the orchestrator's agent registry. **The flywheel accumulates knowledge but doesn't apply it.**

**File:** `src/agents/orchestrator.py` — `_load_agent_registry()` only registers 3 agents.

### 2. Backend Swap Promise Broken (HIGH)
`_register_defaults()` imports all Python backends at init time. Changing `backends.yaml` to use a Rust backend will crash because the Rust files don't exist AND the Python imports still happen. The "YAML config selects backend, no refactoring ever" promise is aspirational, not real.

**File:** `src/interfaces/backend_registry.py` — `_register_defaults()` method.

### 3. No Watchdog for Kill Switch (HIGH)
The three-tier watchdog architecture (Governor + Monitor + Watchdog) described in TSAR_ARCHITECTURE.md §6.3 is NOT implemented. The `KillSwitch` class works within a single process, but if that process hangs, the kill switch can't fire. For a trading system with real money, this is a safety gap.

**File:** `src/risk/kill_switch.py` — no `AutoKillDetector`, no systemd integration.

### 4. SQLite Scalability Ceiling (MEDIUM)
Single SQLite file with WAL mode for 10 agents reading/writing concurrently. Fine for Day1 ($10, paper mode). At Level 3 ($100-1K, 10 agents, multi-asset), lock contention will become a bottleneck. No migration path to PostgreSQL is implemented.

**File:** `src/knowledge/trade_memory.py` — `_conn()` uses `sqlite3.connect()` with busy_timeout=5000.

### 5. LLM Budget Not Enforced (MEDIUM)
The `CostTracker` in `ModelRouter` tracks cumulative costs but doesn't enforce the `budget` config from `models.yaml`. There's no check that prevents exceeding `daily_limit_usd` or `monthly_limit_usd`. An LLM runaway could burn through API credits without limit.

**File:** `src/llm/router.py` — `CostTracker` tracks but doesn't gate.

---

## 11. SPECIFIC ACTIONABLE RECOMMENDATIONS

### Priority 1 — Close the Flywheel Gap

**What:** Wire `StrategyGeneticist` into the orchestrator and subscribe it to `tsar:stream:strategy_proposals`.

**Files:**
- `src/agents/orchestrator.py` — Add `strategy_geneticist` to `AGENT_REGISTRY` and `enabled_agents`
- `src/agents/strategy_geneticist.py` — Ensure it subscribes to `tsar:stream:strategy_proposals`
- `config/default.yaml` — Add `strategy_geneticist` to `agents.enabled` list

**Effort:** 1-2 days

### Priority 2 — Fix Backend Registry Lazy Loading

**What:** Make `_register_defaults()` lazy — only import backends when `create()` is called, not at module load.

**Files:**
- `src/interfaces/backend_registry.py` — Replace eager imports with lazy class resolution

**Code sketch:**
```python
def _register_defaults(self) -> None:
    # Register by dotted path, not by import
    self.register("exchange_gateway", "ccxt", "src.backends.python.ccxt_gateway.CcxtGateway")
    self.register("execution_engine", "ccxt_exec", "src.backends.python.ccxt_exec_engine.CcxtExecEngine")
    # ... etc

def create(self, interface_name, config=None):
    chain = self._fallback_chains.get(interface_name, [])
    backend_name = chain[0]
    cls_or_path = self._backends[interface_name][backend_name]
    if isinstance(cls_or_path, str):
        cls = self._import_class(cls_or_path)
        self._backends[interface_name][backend_name] = cls  # Cache
    # ...
```

**Effort:** 1 day

### Priority 3 — Implement Kill Switch Watchdog

**What:** Add a separate watchdog process that monitors the main process heartbeat via file/Redis and fires the kill switch if the main process hangs.

**Files:**
- `src/risk/watchdog.py` — New file: WatchdogProcess class
- `config/risk.yaml` — Add watchdog config (heartbeat_interval, stale_threshold)
- `docker-compose.yml` — Add watchdog as a separate service

**Effort:** 2-3 days

### Priority 4 — Enforce LLM Budget

**What:** Add budget enforcement to `ModelRouter.generate()` — check cumulative cost against limits before making API calls.

**Files:**
- `src/llm/router.py` — Add `_check_budget()` method, call before each `provider.generate()`

**Code sketch:**
```python
def _check_budget(self, provider_name: str) -> None:
    budget = self._config.get("budget", {})
    daily_limit = budget.get("daily_limit_usd", 0)
    monthly_limit = budget.get("monthly_limit_usd", 0)
    if daily_limit > 0 and self.cost_tracker.daily_cost >= daily_limit:
        raise BudgetExceededError(f"Daily limit ${daily_limit} reached")
```

**Effort:** 0.5 days

### Priority 5 — Add WebSocket Real-Time to Mobile App

**What:** Add WebSocket connection to the FastAPI backend for real-time P&L, position, and regime updates.

**Files:**
- `mobile/lib/services/api_service.dart` — Add WebSocket client
- `mobile/lib/providers/dashboard_provider.dart` — Subscribe to real-time updates
- `src/api/app.py` — Add WebSocket endpoint for streaming updates

**Effort:** 3-5 days

### Priority 6 — Add Interface Conformance Tests

**What:** Create an abstract test suite that any backend implementation must pass to verify it correctly implements the ABC.

**Files:**
- `tests/interfaces/test_exchange_gateway.py` — Abstract tests for ExchangeGateway
- `tests/interfaces/test_risk_engine.py` — Abstract tests for RiskEngine
- `tests/test_backends/test_ccxt_gateway.py` — Concrete tests for CcxtGateway

**Effort:** 2 days

### Priority 7 — Wire Remaining Agents

**What:** Add Macro Agent, Regime Detector, Trade Philosopher, Market Cartographer, and Execution Tracker to the orchestrator.

**Files:**
- `src/agents/orchestrator.py` — Extend `_load_agent_registry()` and add to `enabled_agents`

**Effort:** 2-3 days (mostly testing)

---

## 12. VERDICT

### CONDITIONAL PASS — Score: 7.8/10

TSAR is a **genuine, implemented trading super agent system** — not a design document. The codebase has 97 Python files with real implementations of all 5 interface ABCs, 5 knowledge stores with FTS5, a 7-layer risk engine, CloudEvents messaging, LLM routing with circuit breakers, a backtest engine, a flywheel health score, and a Flutter mobile app. This is substantive engineering.

**What makes it pass:**
1. The interface layer is genuinely well-designed and implemented
2. The risk engine is institutional-grade (deterministic, zero LLM, kill switch)
3. The knowledge layer with FTS5 is production-quality
4. CloudEvents messaging is fully implemented
5. The codebase is coherent — no major contradictions between design and implementation

**What keeps it conditional:**
1. The flywheel doesn't close (EXTRACT → ADAPT gap)
2. The backend swap promise has hidden coupling
3. No kill switch watchdog (single-process safety gap)
4. LLM budget not enforced
5. Multi-language strategy is architectural only

**Conditions for unconditional pass:**
1. Wire StrategyGeneticist into orchestrator (close flywheel)
2. Fix BackendRegistry lazy loading (make swap real)
3. Implement kill switch watchdog (safety)
4. Enforce LLM budget (cost control)

**Estimated effort:** 8-12 engineering days

---

## APPENDIX: FILE REFERENCE

| Component | Primary File | Lines | Quality |
|-----------|-------------|-------|---------|
| ExchangeGateway ABC | `src/interfaces/exchange_gateway.py` | ~150 | Strong |
| PricingEngine ABC | `src/interfaces/pricing_engine.py` | ~80 | Good |
| ExecutionEngine ABC | `src/interfaces/execution_engine.py` | ~100 | Good |
| RiskEngine ABC | `src/interfaces/risk_engine.py` | ~120 | Exceptional |
| LLMProvider ABC | `src/interfaces/llm_provider.py` | ~90 | Strong |
| Shared Types | `src/interfaces/types.py` | ~450 | Exceptional |
| Backend Registry | `src/interfaces/backend_registry.py` | ~200 | Good (coupling issue) |
| CloudEvents | `src/comms/events.py` | ~250 | Strong |
| Event Bus | `src/comms/event_bus.py` | ~20 | Minimal (in-process only) |
| Base Agent | `src/agents/base.py` | ~250 | Strong |
| Orchestrator | `src/agents/orchestrator.py` | ~350 | Good (3/10 agents wired) |
| Risk Governor | `src/risk/governor.py` | ~350 | Exceptional |
| Kill Switch | `src/risk/kill_switch.py` | ~200 | Strong (no watchdog) |
| Mandate Gate | `src/risk/mandate_gate.py` | ~180 | Good |
| Trade Memory | `src/knowledge/trade_memory.py` | ~300 | Strong |
| FTS5 Search | `src/knowledge/fts_search.py` | ~300 | Strong |
| Shadow Extractor | `src/knowledge/shadow_extractor.py` | ~250 | Good |
| Model Router | `src/llm/router.py` | ~300 | Strong (no budget enforcement) |
| Flywheel Health | `src/metrics/flywheel.py` | ~250 | Strong |
| Backtest Engine | `src/strategy/backtest_engine.py` | ~400 | Strong |
| Docker Compose | `docker-compose.yml` | ~60 | Minimal |
| CI/CD | `.github/workflows/ci.yml` | ~100 | Good |
| Mobile App | `mobile/lib/` (28 files) | ~3000 | Good (no WebSocket) |

---

*Review completed: 2026-07-30 14:36 GMT+8*
*Files reviewed: 97 Python + 28 Dart + config + CI/CD + architecture docs*
*Framework: System Architecture + Integration + Scalability + Knowledge + Swappability + Mobile + Deployment + Jensen Huang Doctrine*
*Verdict: CONDITIONAL PASS — 7.8/10*
