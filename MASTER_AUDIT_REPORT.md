# TSAR — Master Audit Report
## 12-Council Validation | Date: 2025-07-31

### Overall Score: 6.9/10

The skeleton is solid. The organs are all there. The nervous system — the wiring — is broken.

---

## Executive Summary

TSAR has 63K lines of Python + 32 Rust files + 20 C++ files across 514 files. 13 agents, 23 tool files (257 methods), knowledge system, risk layer, strategy evolution, multi-language backends. The code is real — not stubs. But critical wiring issues prevent it from functioning as a superagent.

---

## Council Scores

| # | Council | Score | Key Finding |
|---|---------|-------|-------------|
| 1 | Architecture | 7/10 | 3 EventBus instances, flywheel disconnected |
| 2 | Security | 6.5/10 | No rate limiting, single-factor kill switch |
| 3 | Risk Systems | 7.5/10 | Watchdog never started, callbacks unwired |
| 4 | Market Connectivity | 6.5/10 | Binance-only WS, no OANDA/MT5 |
| 5 | Superagent Loop | 5/10 | Loop not closed, dead stores |
| 6 | Code Quality | 7.2/10 | EventBus dual-system, silent error swallowing |
| 7 | Strategy Engine | 7.5/10 | Backtest broken, genome bridge missing |
| 8 | Tools Completeness | 7.5/10 | 4 orphaned tools, zero tests |
| 9 | Infrastructure | 7.2/10 | No migration runner, CI security decorative |
| 10 | Knowledge Architecture | 7/10 | ChromaDB broken, SQL injection, DB pool leak |
| 11 | NVIDIA Integration | 6.5/10 | No SDK deps, GPU paths dead code |
| 12 | Agent System | 7.5/10 | "fills" ghost stream, 6 agents not started |

---

## CRITICAL ISSUES (P0 — Must Fix)

### C-01: EventBus Fragmentation [Architecture + Code Quality]
**Problem:** 3 separate EventBus instances that don't communicate. Orchestrator and FlywheelOrchestrator each create isolated buses. Events never cross between them.
**Impact:** Flywheel never triggers. Learning loop dead.
**Fix:** Unify on single shared EventBus instance, or bridge EventBus↔EventPublisher/Subscriber.
**Council:** Architecture (7/10), Code Quality (7.2/10)

### C-02: Event Type Mismatch [Code Quality]
**Problem:** Sniper publishes `tsar.trade.executed.v1` but subscribers listen for `tsar.trade.executed` (missing `.v1` suffix).
**Impact:** Events silently dropped. No trade processing.
**Fix:** Standardize event type strings — either all use `.v1` or none.
**Council:** Code Quality (7.2/10)

### C-03: Watchdog Never Started [Risk Systems]
**Problem:** Watchdog exists but no process calls `write_heartbeat()`. If TSAR crashes, no protection.
**Impact:** Crash = unmanaged positions.
**Fix:** Start watchdog as background task in `__main__.py`. Wire heartbeat into main loop.
**Council:** Risk Systems (7.5/10)

### C-04: Kill Switch Callbacks Not Wired [Risk Systems]
**Problem:** Kill switch writes state to file/Redis but never calls callbacks to cancel orders or flatten positions.
**Impact:** Kill switch is a boolean flag, not an execution command.
**Fix:** Wire `on_activate` callbacks in `__main__.py`.
**Council:** Risk Systems (7.5/10)

### C-05: Backtest Engine Missing Indicators [Strategy Engine]
**Problem:** `_build_bar_data()` only provides raw OHLCV. Strategies expect `ema_fast`, `rsi`, `adx`, `atr`.
**Impact:** Backtests never trigger signals. Evolution meaningless.
**Fix:** Compute indicators in backtest engine or pass strategy-computed indicators.
**Council:** Strategy Engine (7.5/10)

### C-06: Genome→Strategy Bridge Missing [Strategy Engine]
**Problem:** Geneticist can mutate genomes but mutations never reach strategy code. `momentum.py` hardcodes weights.
**Impact:** Evolution has no effect on trading.
**Fix:** Make strategies read weights from genome at runtime.
**Council:** Strategy Engine (7.5/10)

### C-07: "fills" Ghost Stream [Agent System]
**Problem:** MarketCartographer and StrategyGeneticist subscribe to `"fills"` but no agent publishes to it.
**Impact:** These agents never receive trade events.
**Fix:** Either publish fills from ExecutionSniper, or change subscriptions to `"trades"`.
**Council:** Agent System (7.5/10)

### C-08: Watchdog Heartbeat Never Written [Risk Systems]
**Problem:** Main loop doesn't write heartbeat file. Watchdog checks for stale heartbeat.
**Impact:** Watchdog always detects "stale" or never detects anything.
**Fix:** Add heartbeat write to main loop tick.
**Council:** Risk Systems (7.5/10)

---

## HIGH ISSUES (P1 — Should Fix Soon)

### H-01: No API Rate Limiting [Security]
**Impact:** Brute force, DoS, kill switch abuse.
**Fix:** Add `slowapi` middleware. 10 req/min for state-changing POST endpoints.

### H-02: Single-Factor Telegram Kill Switch [Security]
**Impact:** Compromised Telegram = instant halt or resume of all trading.
**Fix:** Add confirmation step (PIN or second `/confirm` within 30s).

### H-03: CORS Wildcard in Config [Security]
**Impact:** `config/default.yaml` sets `cors_origins: ["*"]`. Code defaults to empty but config contradicts.
**Fix:** Change to `cors_origins: []`.

### H-04: ChromaDB Broken [Knowledge Architecture]
**Impact:** Uses deprecated `duckdb+parquet` setting. ChromaDB ≥0.4 won't initialize. Graceful fallback to FTS5-only.
**Fix:** Update to modern ChromaDB API or remove and rely on FTS5.

### H-05: SQL Injection in Knowledge Graph [Knowledge Architecture]
**Impact:** `start_id`, `start_type` etc. interpolated directly into SQL via f-string.
**Fix:** Use parameterized queries.

### H-06: DB Connection Pool Leak [Knowledge Architecture]
**Impact:** `_conn()` puts connections back in pool even after exceptions. Closed connections may be reused.
**Fix:** Don't return failed connections to pool. Add health check before reuse.

### H-07: Guard State In-Memory Only [Risk Systems]
**Impact:** Guards reset on restart. Anti-revenge guard loses memory.
**Fix:** Persist guard state to file/DB.

### H-08: Orchestrator Only Manages 5/13 Agents [Agent System]
**Impact:** 6 agents (regime_detector, sentiment_agent, macro_agent, market_cartographer, trade_philosopher, execution_tracker) never started.
**Fix:** Add all agents to orchestrator registry.

### H-09: TradePhilosopher Orphaned [Agent System]
**Impact:** No event input. Only reads from DB on cycle.
**Fix:** Subscribe to `"trades"` stream.

### H-10: 4 Orphaned Tools [Tools]
**Impact:** PortfolioTools, KnowledgeGraphTools, OnChainAnalytics, MarketCalendar — complete implementations, no consumer.
**Fix:** Wire into agents or create new agents.

### H-11: No NVIDIA SDK Dependencies [NVIDIA]
**Impact:** cuFOLIO, RAG Blueprint, Nemo Evaluator all fall back to CPU/scipy/rule-based.
**Fix:** Add to `pyproject.toml` or mark as optional with clear documentation.

### H-12: Silent Error Swallowing [Code Quality]
**Impact:** ~20 `except: pass` locations in exchange/DB layers mask critical failures.
**Fix:** Log, emit alert, re-raise or return error result.

### H-13: MacroAgent Enrichment Stub [Agent System]
**Impact:** `_enrich_with_tools()` only logs, never calls tools.
**Fix:** Implement actual tool calls.

### H-14: RegimeDetector Circular Dependency [Agent System]
**Impact:** `run_cycle()` checks `if self.regime_state is None: return` but never sets it.
**Fix:** Initialize regime_state in `on_initialize()`.

### H-15: No Test Coverage [Infrastructure + Tools]
**Impact:** Zero unit tests for 257 tool methods. Zero tests for agents.
**Fix:** Add tests for critical paths (execution, risk, order routing).

---

## MEDIUM ISSUES (P2 — Should Fix)

### M-01: Two Parallel Event Systems [Code Quality]
EventBus (in-process) vs EventPublisher/Subscriber (Redis-backed). Need unification.

### M-02: `_get_api_key()` Defined But Never Called [Security]
Dead code in `app.py:32-38`. Startup validation only via `__main__.py`.

### M-03: API Key Not Constant-Time Comparison [Security]
`credentials.credentials != expected` vulnerable to timing attacks. Use `secrets.compare_digest()`.

### M-04: OpenAPI Docs Exposed [Security]
`/docs` and `/redoc` publicly accessible. Disable in production.

### M-05: Error Messages Leak Internals [Security]
`str(e)` returned in API responses. Replace with generic messages.

### M-06: No Input Validation on API [Security]
`limit` has no upper bound. `symbol` and `status` passed directly to queries.

### M-07: Backtest Doesn't Generate Signals [Strategy Engine]
No SignalScout equivalent in backtest. Bar-by-bar scan not implemented.

### M-08: Hardcoded Strategy Weights [Strategy Engine]
`momentum.py` hardcodes weights instead of reading from genome.

### M-09: `market_calendar.py` Dead Code [Tools]
Exists on disk, never imported, never registered.

### M-10: `knowledge.py` God Class [Tools]
68 methods in one class. Should be split into 8 separate tool classes.

### M-11: `market_calendar.py` vs `economic_calendar.py` Overlap [Tools]
Both provide economic calendar. Consolidate.

### M-12: WebSocket Hardcoded to Binance [Market Connectivity]
`_ws_base_url` hardcoded. Not configurable for other exchanges.

### M-13: OCO/Bracket Orders Monkey-Patched [Market Connectivity]
Methods patched onto class at runtime, not in ABC.

### M-14: Paper Engine No Partial Fills [Market Connectivity]
Always fills fully. Slippage is random, not orderbook-based.

### M-15: Only `001` Migration Has Rollback [Infrastructure]
`002` and `003` are forward-only.

### M-16: No Automated Migration Runner [Infrastructure]
Raw SQL files, no `make migrate`, no Alembic.

### M-17: Grafana No Alert Rules [Infrastructure]
Dashboards view-only. No proactive alerting.

### M-18: No Log Aggregation [Infrastructure]
No Loki, ELK, or Fluentd.

### M-19: cuOpt Configured But No Implementation [NVIDIA]
YAML config exists, no Python backend.

### M-20: Nemotron Availability Check Weak [NVIDIA]
Only checks for `httpx` import, not actual NIM connectivity.

### M-21: RegimeDetector Docstring/Code Mismatch [Agent System]
Weights refactored but docstring not updated.

### M-22: SignalScout Docstring/Code Mismatch [Agent System]
RSI weight documented as 40%, actually 30%.

---

## LOW ISSUES (P3 — Nice to Have)

### L-01: Kill Switch `/tmp` Fallback World-Readable
### L-02: Telegram Bot Token in URL Construction
### L-03: `TSAR_DB_PATH` Defaults to Relative Path
### L-04: ExecutionTracker Missing PUBLISH_STREAM
### L-05: Duplicate Imports in trade_memory.py
### L-06: FTS5 sqlite_master Check Only First Row
### L-07: No `.dockerignore`
### L-08: Dockerfile Rust Build Silently Skipped
### L-09: Flutter Test Failures Silently Swallowed
### L-10: No Dependency Vulnerability Scanning (trivy/grype)
### L-11: No Node Exporter for System Metrics
### L-12: Rule Validator Uses Direct sqlite3 Instead of Pool

---

## FIX TEAM PLAN

### Fix Team 1: EventBus Unification (C-01, C-02, M-01)
**Mandate:** Unify EventBus into single shared instance. Fix event type strings. Bridge EventBus↔EventPublisher if needed.

### Fix Team 2: Risk Wiring (C-03, C-04, C-08, H-07)
**Mandate:** Start watchdog, wire kill switch callbacks, add heartbeat to main loop, persist guard state.

### Fix Team 3: Strategy Engine Fix (C-05, C-06, M-07, M-08)
**Mandate:** Fix backtest indicator computation. Make strategies read from genome. Add signal generation to backtest.

### Fix Team 4: Agent Wiring (C-07, H-08, H-09, H-13, H-14)
**Mandate:** Fix "fills" stream, register all agents in orchestrator, wire TradePhilosopher, implement MacroAgent enrichment, fix RegimeDetector init.

### Fix Team 5: Security Hardening (H-01, H-02, H-03, M-03, M-04, M-05, M-06)
**Mandate:** Add rate limiting, fix CORS, constant-time comparison, disable docs in prod, sanitize errors, validate inputs.

### Fix Team 6: Knowledge & Tools (H-04, H-05, H-06, H-10, M-09, M-10, M-11)
**Mandate:** Fix ChromaDB, SQL injection, DB pool leak, wire orphaned tools, consolidate calendars, split knowledge.py.

### Fix Team 7: Infrastructure (H-15, M-15, M-16, M-17, M-18, L-07, L-08, L-09)
**Mandate:** Add migration runner, add critical tests, fix CI, add Grafana alerts, add log aggregation.

### Fix Team 8: NVIDIA & Market (H-11, M-12, M-13, M-14, M-19, M-20)
**Mandate:** Make NVIDIA deps optional with clear docs, parameterize WS, fix OCO interface, improve paper engine.

---

## JENSEN'S SUPERAGENT BLUEPRINT — MAPPING

| Jensen's Concept | TSAR Component | Status | Fix Team |
|---|---|---|---|
| **Model** (Nemotron Ultra) | LLM router, NIM config | ✅ Configured | — |
| **Harness** (LangChain-style) | Agents + Tools + Knowledge | ⚠️ Built, unwired | Teams 1,4,6 |
| **Domain Knowledge** | ChromaDB, trade memory, patterns | ⚠️ Built, disconnected | Team 6 |
| **Flywheel** (use → learn → improve) | FlywheelOrchestrator | ❌ Never triggers | Teams 1,3 |
| **Safeguards** | Risk guards, kill switch, mandate | ⚠️ Built, unwired | Team 2 |
| **Runtime** (OpenShell) | Docker, CI/CD, monitoring | ⚠️ Partial | Team 7 |
| **Post-training** | Not started | ❌ Future phase | — |
