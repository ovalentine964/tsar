# TSAR Checkpoint 1 — Architecture Validation Review

**Reviewer:** Architecture Validator (Subagent)
**Date:** 2026-07-24
**Spec:** TSAR_ARCHITECTURE.md v3.0.0
**Codebase:** `/home/work/.openclaw/workspace/tsar/src/`
**Status:** ⚠️ CONDITIONAL PASS — Structure complete, interface signatures deviate from spec

---

## Executive Summary

The TSAR codebase demonstrates **strong structural alignment** with the v3.0.0 architecture spec. All 10 agents, 5 knowledge stores, 5 ABCs, risk/strategy/LLM/comms/metrics/resources/API/bot components, Rust crates, C++ modules, and config files exist. However, **interface method signatures deviate from the spec in meaningful ways** — the "interface-first" principle requires exact contract adherence. These are fixable but must be addressed before Checkpoint 2.

---

## 1. ABCs in `src/interfaces/` — ⚠️ SIGNATURE DEVIATIONS

All 5 ABCs exist with correct class names and docstrings. However, method signatures diverge from the spec.

### 1.1 ExchangeGateway — ⚠️ PARTIAL MATCH

| Spec Method | Code Method | Status |
|---|---|---|
| `connect()` | `connect()` | ✅ |
| `disconnect()` | `disconnect()` | ✅ |
| `connection_status` (property) | ❌ Missing | ❌ |
| `get_price(symbol) → float` | `get_price(symbol) → Price` | ⚠️ Return type differs |
| `get_ticker(symbol) → Ticker` | ❌ Missing | ❌ |
| `get_ohlcv(symbol, timeframe, limit, since)` | `get_ohlcv(symbol, timeframe, limit)` | ⚠️ Missing `since` param |
| `get_orderbook(symbol, depth)` | `get_orderbook(symbol, depth)` | ✅ |
| `get_recent_trades(symbol, limit) → list[Trade]` | ❌ Missing | ❌ |
| `subscribe(symbol, stream_type, callback) → StreamHandle` | `subscribe_ticker(symbol, callback)` | ⚠️ Simplified |
| `unsubscribe(handle)` | ❌ Missing | ❌ |
| `get_balance() → Balance` | ❌ Missing | ❌ |
| `get_positions() → list[Position]` | ❌ Missing | ❌ |
| `place_order(...)` | ❌ Missing (in ExecutionEngine) | ⚠️ By design? |
| `cancel_order(...)` | ❌ Missing | ❌ |
| `get_order(...)` | ❌ Missing | ❌ |
| `get_open_orders(...)` | ❌ Missing | ❌ |
| `health_check()` | `health_check()` | ✅ (not in spec but good) |

**Impact:** Agents cannot get balance, positions, ticker, recent trades, or manage orders through the gateway. The spec intends ExchangeGateway as the single entry point for ALL exchange operations.

### 1.2 PricingEngine — ⚠️ SIGNATURE DIFFERENCES

| Spec Method | Code Method | Status |
|---|---|---|
| `calculate_indicator(name, **params) → IndicatorResult` | ❌ Missing (individual methods instead) | ⚠️ Design choice |
| `calculate_greeks(option) → Greeks` | ❌ Missing | ❌ |
| `aggregate_ohlcv(ticks, target_timeframe) → list[OHLCVBar]` | ❌ Missing | ❌ |
| `calculate_rsi(closes, period)` (convenience) | `calculate_rsi(closes, period)` (abstract) | ✅ |
| `calculate_ema(closes, period)` (convenience) | `calculate_ema(data, period)` (abstract) | ✅ |
| `calculate_atr(highs, lows, closes, period)` (convenience) | `calculate_atr(highs, lows, closes, period)` (abstract) | ✅ |
| N/A | `calculate_macd(...)` | ✅ Extra |
| N/A | `calculate_bollinger(...)` | ✅ Extra |
| N/A | `detect_support_resistance(...)` | ✅ Extra |

**Impact:** Missing `calculate_indicator()` generic method, `calculate_greeks()`, and `aggregate_ohlcv()`. Individual indicator methods are fine for Day1 but the generic method is needed for extensibility.

### 1.3 ExecutionEngine — ⚠️ SIGNATURE DIFFERENCES

| Spec Method | Code Method | Status |
|---|---|---|
| `execute_order(request: OrderRequest)` | `execute_order(order: Order)` | ⚠️ Different param type |
| `cancel_order(order_id, symbol)` | `cancel_order(order_id)` | ⚠️ Missing symbol param |
| `get_fills(order_id, symbol)` | `get_fills(order_id)` | ⚠️ Missing symbol param |
| `calculate_slippage(expected_price, fills)` | ❌ Missing | ❌ |
| `execute_twap(...)` | ❌ Missing | ❌ (Day1 stub OK) |
| `execute_vwap(...)` | ❌ Missing | ❌ (Day1 stub OK) |
| `get_open_orders(symbol)` | `get_open_orders(symbol)` | ✅ |
| `get_order_status(order_id, symbol)` | `get_order_status(order_id)` | ⚠️ Missing symbol |

**Impact:** `OrderRequest` type doesn't exist — code uses `Order` instead. Missing slippage calculation method.

### 1.4 RiskEngine — ⚠️ SIGNATURE DIFFERENCES

| Spec Method | Code Method | Status |
|---|---|---|
| `check_risk(symbol, side, entry_price, stop_loss, take_profit, signal_score, current_equity, open_positions, daily_pnl, **kwargs)` | `check_risk(signal: Signal, portfolio: Portfolio)` | ⚠️ Parameter objects |
| `calculate_position_size(equity, risk_pct, entry_price, stop_loss, method, **kwargs)` | `calculate_position_size(signal: Signal, portfolio: Portfolio)` | ⚠️ Parameter objects |
| `get_drawdown_state(current_equity, high_water_mark, daily_pnl, ...)` | `get_drawdown_state(portfolio: Portfolio)` | ⚠️ Parameter object |
| `run_stress_test(...)` | ❌ Missing | ❌ (Level 3+ OK) |
| N/A | `get_kill_switch_status()` | ✅ Extra |
| N/A | `activate_kill_switch(reason)` | ✅ Extra |
| N/A | `deactivate_kill_switch()` | ✅ Extra |

**Impact:** Using parameter objects (`Signal`, `Portfolio`) instead of scalar params is arguably cleaner but deviates from spec. Agents calling the engine must construct these objects.

### 1.5 LLMProvider — ⚠️ SIGNATURE DIFFERENCES

| Spec Method | Code Method | Status |
|---|---|---|
| `initialize()` | ❌ Missing | ❌ |
| `shutdown()` | ❌ Missing | ❌ |
| `generate(request: LLMRequest)` | `generate(prompt, **kwargs)` | ⚠️ Different signature |
| `stream(request: LLMRequest)` | `stream(prompt, **kwargs)` | ⚠️ Different signature |
| `count_tokens(text, model)` | `count_tokens(text)` | ⚠️ Missing model param |
| `get_capabilities(model)` | `get_capabilities()` | ⚠️ Missing model param |
| `health_check()` | `health_check()` | ✅ |

**Impact:** `LLMRequest` type doesn't exist. Missing lifecycle methods (`initialize`/`shutdown`). The `ModelRouter` in `src/llm/router.py` references `LLMRequest` which doesn't exist in types.py.

### 1.6 Missing Types

The following types are referenced in code but **do not exist** in `src/interfaces/types.py`:
- `OrderRequest` — used in `execution_sniper.py`
- `LLMRequest` — used in `src/llm/router.py`
- `Ticker` — referenced in spec
- `StreamHandle` — referenced in spec
- `Greeks` — referenced in spec
- `IndicatorResult` — referenced in spec
- `OHLCVBar` — referenced in spec

---

## 2. BackendRegistry — ⚠️ PARTIAL MATCH

**File:** `src/interfaces/backend_registry.py`

| Spec Method | Status | Notes |
|---|---|---|
| `register(interface_name, backend_class, priority, config, tags)` | ⚠️ | Code: `register(interface_name, backend_name, cls)` — different signature |
| `load_from_config(config_path)` | ✅ | Works with `config/backends.yaml` |
| `create(interface_name, **override_config)` | ✅ | Works |
| `create_with_fallback(interface_name, **override_config)` | ❌ Missing | No automatic failover |
| `swap(interface_name, new_backend_class)` | ❌ Missing | No hot-swap |
| `unswap(interface_name)` | ❌ Missing | |
| `record_call(interface_name, backend_path, latency_ms, error)` | ❌ Missing | No metrics recording |
| `get_metrics(interface_name)` | ❌ Missing | |
| `get_status()` | ✅ | `get_backend_status()` exists |

**Convenience getters** (spec says agents call these):
- `get_exchange_gateway()` — ❌ Not defined
- `get_pricing_engine()` — ❌ Not defined
- `get_execution_engine()` — ❌ Not defined
- `get_risk_engine()` — ❌ Not defined
- `get_llm_provider()` — ❌ Not defined

**Impact:** Agents import from `src.interfaces` but the convenience getters don't exist in `__init__.py`. The `RiskGuardian` agent calls `get_risk_engine()` which would fail at runtime. Missing fallback proxy and hot-swap capability.

---

## 3. All 10 Agents — ✅ PASS

| # | Agent | File | Status |
|---|---|---|---|
| 1 | Signal Scout | `src/agents/signal_scout.py` | ✅ Correct weights, streams |
| 2 | Risk Guardian | `src/agents/risk_guardian.py` | ✅ Gatekeeper logic |
| 3 | Execution Sniper | `src/agents/execution_sniper.py` | ✅ Order lifecycle |
| 4 | Macro Agent | `src/agents/macro_agent.py` | ✅ Level 2+ |
| 5 | Regime Detector | `src/agents/regime_detector.py` | ✅ Level 3+ |
| 6 | Trade Philosopher | `src/agents/trade_philosopher.py` | ✅ Level 3+ |
| 7 | Strategy Geneticist | `src/agents/strategy_geneticist.py` | ✅ Level 3+ |
| 8 | Market Cartographer | `src/agents/market_cartographer.py` | ✅ Level 3+ |
| 9 | Execution Tracker | `src/agents/execution_tracker.py` | ✅ Level 3+ |
| 10 | Orchestrator | `src/agents/orchestrator.py` | ✅ Supervisor |

All agents inherit from `BaseAgent` with correct `AGENT_NAME` and `ROLE` attributes. Stream subscriptions match spec (documented in docstrings).

---

## 4. All 5 Knowledge Stores — ✅ PASS

| # | Store | File | Status |
|---|---|---|---|
| 1 | Trade Memory | `src/knowledge/trade_memory.py` | ✅ Full CRUD + FTS5 |
| 2 | Strategy Genomes | `src/knowledge/strategy_genomes.py` | ✅ Full CRUD + mutations |
| 3 | Pattern Library | `src/knowledge/pattern_library.py` | ✅ Full CRUD + validation |
| 4 | Lesson Archive | `src/knowledge/lesson_archive.py` | ✅ Full CRUD + FTS5 |
| 5 | Regime State | `src/knowledge/regime_state.py` | ✅ Dict + Redis backends |

All stores use SQLite with WAL mode, proper schema, and comprehensive CRUD operations. Regime State has a clean Protocol-based backend abstraction (dict for Day1, Redis for Level 2+).

---

## 5. Risk Engine Components — ✅ PASS

| Component | File | Status |
|---|---|---|
| Kill Switch | `src/risk/kill_switch.py` | ✅ Dual-write (Redis + file) |
| Risk Governor | `src/risk/governor.py` | ✅ Stub (Day1) |
| Behavioral Guards | `src/risk/guards.py` | ✅ All 4 guards implemented |
| Drawdown Tracker | `src/risk/drawdown.py` | ✅ Circuit breaker levels |
| Position Sizer | `src/risk/position_sizer.py` | ✅ Stub (Day1) |

Kill switch correctly implements dual-write with file as primary. Circuit breaker levels match spec (GREEN/YELLOW/ORANGE/RED).

---

## 6. Strategy Components — ✅ PASS

| Component | File | Status |
|---|---|---|
| Base Strategy | `src/strategy/base.py` | ✅ ABC with entry/exit/risk |
| Mean Reversion | `src/strategy/mean_reversion.py` | ✅ Day1 strategy |
| Momentum | `src/strategy/momentum.py` | ✅ Level 2 strategy |
| Strategy Registry | `src/strategy/registry.py` | ✅ Register/unregister/list |
| Strategy Genome | `src/strategy/genome.py` | ✅ Mutation logic |

---

## 7. LLM Components — ✅ PASS

| Component | File | Status |
|---|---|---|
| Model Router | `src/llm/router.py` | ✅ Task-type routing |
| Prompts | `src/llm/prompts.py` | ✅ Exists |
| Cache | `src/llm/cache.py` | ✅ Exists |

Router correctly implements task-type-based routing with zero model names in agent code.

---

## 8. CloudEvents Components — ✅ PASS

| Component | File | Status |
|---|---|---|
| Events | `src/comms/events.py` | ✅ Full CloudEvents v1.0 |
| Publisher | `src/comms/publisher.py` | ✅ Redis Streams |
| Subscriber | `src/comms/subscriber.py` | ✅ Consumer groups |

CloudEvents implementation includes all TSAR extensions (traceid, priority, risklevel, agentrole, tradingmode, schemaver). MessagePack encoding with `ce_` prefixed Redis fields matches spec exactly.

---

## 9. Metrics Components — ✅ PASS

| Component | File | Status |
|---|---|---|
| Metric Tracker | `src/metrics/tracker.py` | ✅ Counters + gauges |
| Flywheel Health | `src/metrics/flywheel.py` | ✅ All 10 weights match spec |
| Dashboard | `src/metrics/dashboard.py` | ✅ FastAPI endpoints |

Flywheel weights exactly match spec (expectancy_trend: 0.15, sharpe_trend: 0.15, etc.).

---

## 10. Resource Components — ✅ PASS

| Component | File | Status |
|---|---|---|
| Resource Enforcer | `src/resources/enforcer.py` | ✅ Pre/post checks |
| Resource Profiles | `src/resources/profiles.py` | ✅ All 5 categories + context multipliers |

All 5 tool categories match spec (exchange, analysis, risk, heavy_compute, execution). Context multipliers correct (live_trading: 0.7x timeout, backtesting: 2x memory, 3x CPU).

---

## 11. API Components — ✅ PASS

| Component | File | Status |
|---|---|---|
| FastAPI App | `src/api/app.py` | ✅ Factory pattern |
| Health Routes | `src/api/routes/health.py` | ✅ |
| Trading Routes | `src/api/routes/trading.py` | ✅ |
| Portfolio Routes | `src/api/routes/portfolio.py` | ✅ |

---

## 12. Bot Components — ✅ PASS

| Component | File | Status |
|---|---|---|
| Bot | `src/bot/bot.py` | ✅ Telegram alerts |
| Commands | `src/bot/commands.py` | ✅ All 8 commands |

Commands include /start, /stop, /status, /pnl, /positions, /risk, /regime, /flywheel — matching spec.

---

## 13. Rust Crates — ✅ PASS

**Workspace:** `rust/Cargo.toml` — Rust 1.79, edition 2021

| Crate | Status | Dependencies |
|---|---|---|
| `core` | ✅ | tokio, serde, chrono |
| `ws-manager` | ✅ | tokio-tungstenite |
| `tick-processor` | ✅ | |
| `order-executor` | ✅ | |
| `pyo3-bindings` | ✅ | pyo3 0.21 |

All 5 crates match spec. Workspace dependencies include tokio, tokio-tungstenite, pyo3, serde.

---

## 14. C++ Modules — ✅ PASS

| Module | Files | Status |
|---|---|---|
| `quantlib-pricing` | `include/tsar/pricing/` + `src/` | ✅ |
| `fix-engine` | `include/tsar/fix/` + `src/` | ✅ |
| `cuda-kernels` | `include/tsar/gpu/` + `src/` | ✅ |
| `cffi-bindings` | `include/tsar/cffi/` + `src/` | ✅ |
| `tests/` | test_fix, test_monte_carlo, test_pricing | ✅ |

CMakeLists.txt present at `cpp/` root.

---

## 15. Config Files — ✅ PASS

| Config | File | Status |
|---|---|---|
| Backends | `config/backends.yaml` | ✅ All 5 interfaces configured |
| Models | `config/models.yaml` | ✅ All task types, providers, budgets |
| Risk | `config/risk.yaml` | ✅ All canonical limits, recovery protocol |
| Default | `config/default.yaml` | ✅ App, DB, Redis, logging, API, watchdog |
| Mean Reversion | `config/strategies/mean_reversion.yaml` | ✅ |
| Momentum | `config/strategies/momentum.yaml` | ✅ |

`backends.yaml` correctly maps all 5 interfaces with primary + fallback chains. `models.yaml` includes all 12 task types with correct routing. `risk.yaml` includes all canonical limits, anti-behavioral guards, blackout events, recovery protocol, and leverage limits.

---

## Critical Findings Summary

### 🔴 Must Fix (Blocks Checkpoint 2)

1. **Missing convenience getters** — `get_exchange_gateway()`, `get_pricing_engine()`, etc. are not exported from `src/interfaces/__init__.py`. Agents call them but they don't exist.

2. **Missing types** — `OrderRequest`, `LLMRequest`, `Ticker`, `StreamHandle` are referenced but undefined. Code will fail at import time.

3. **ExchangeGateway missing methods** — `get_balance()`, `get_positions()`, `get_ticker()`, `get_recent_trades()` are critical for agent operation.

### 🟡 Should Fix (Before Level 2)

4. **BackendRegistry missing methods** — `create_with_fallback()`, `swap()`, `unswap()`, `record_call()` are needed for the hot-swap and observability promises.

5. **LLMProvider missing lifecycle** — `initialize()` and `shutdown()` are needed for proper resource management.

6. **PricingEngine missing generic method** — `calculate_indicator(name, **params)` enables extensibility without modifying the ABC.

### 🟢 Nice to Have

7. **ExecutionEngine missing slippage** — `calculate_slippage()` method referenced in spec.
8. **RiskEngine parameter style** — Using `Signal`/`Portfolio` objects vs scalar params is a valid design choice but deviates from spec.

---

## Verdict

**CONDITIONAL PASS** — The codebase is structurally complete and well-organized. All major components exist with correct file locations, class names, and architectural patterns. The interface layer has signature deviations that must be resolved to honor the "interface-first" principle. The 3 critical findings (#1-3) are straightforward to fix — add convenience getters to `__init__.py`, define missing types, and add missing ExchangeGateway methods.

**Recommended next action:** Fix the 3 critical findings, then proceed to Checkpoint 2 (Agent Implementation).
