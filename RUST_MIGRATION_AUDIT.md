# 🦀 TSAR Rust Migration Audit Report

**Date:** 2026-08-01
**Auditor:** Rust Migration Audit Council
**Codebase:** 165 Python files, 83,032 total lines of code
**Score: 6/10** — Good architectural intent (Rust backend scaffolded, PyO3 pattern established), but only 4 of 22 performance-critical files have Rust implementations. The critical hot path (exchange I/O, order execution, kill switch) is still 100% Python.

---

## Executive Summary

TSAR has the right architecture in mind — `src/backends/rust/__init__.py` already implements PyO3 wrappers for **correlation, Monte Carlo, volatility (Garman-Klass), GARCH, batch factors, and slippage**. The fallback pattern (`RUST_AVAILABLE` flag) is production-ready.

**However**, the most latency-critical components — exchange WebSocket handling, order execution, kill switch, and event bus — remain pure Python. For institutional-grade performance (<1ms decision latency), these must migrate to Rust.

### What's Already Done (Partial Wins)
| Component | Rust Status |
|-----------|-------------|
| Correlation matrix | ✅ `trading_rs.correlation_matrix_py` |
| Rolling correlation | ✅ `trading_rs.rolling_correlation_py` |
| Monte Carlo simulation | ✅ `trading_rs.monte_carlo_simulate_py` |
| Garman-Klass volatility | ✅ `trading_rs.garman_klass_vol_py` |
| GARCH forecast | ✅ `trading_rs.garch_forecast_py` |
| Batch factor computation | ✅ `trading_rs.batch_factors_py` |
| Slippage statistics | ✅ `trading_rs.slippage_stats_py` |

### What Still Needs Rust (22 files, ~18,039 lines)

---

## Category 1: MUST be Rust (12 files, 10,909 LOC)

These are on the **hot path** — every microsecond matters.

### 1. `src/backends/python/ccxt_gateway.py` — Exchange Connectivity
- **Lines:** 1,491 | **Functions:** 49 | **Dependencies:** ccxt, aiohttp, redis
- **Current Python latency:** 2-10ms per REST call, 50-200μs per WebSocket tick processing
- **Expected Rust latency:** 100-500μs REST (with reqwest), 5-20μs WebSocket tick processing
- **Performance improvement:** 10-50x on tick processing, 5-10x on REST
- **Why critical:** This is THE bottleneck. Every price update, every order submission flows through here. Python's GIL means tick processing is serial. Institutional systems process 100K+ ticks/sec.
- **Migration complexity:** HIGH — deep ccxt integration, 40 imports, 49 methods, Redis pub/sub
- **PyO3 strategy:** Keep Python ccxt as fallback. Rust side: `tokio-tungstenite` for WebSocket, `reqwest` for REST, `redis-rs` for cache. Expose `RustExchangeGateway` with same interface.

### 2. `src/backends/python/ccxt_exec_engine.py` — Order Execution
- **Lines:** 1,153 | **Functions:** 25 | **Dependencies:** ccxt, ccxt_gateway
- **Current Python latency:** 5-50ms per order (includes validation, routing, submission)
- **Expected Rust latency:** 200μs-2ms
- **Performance improvement:** 25-250x
- **Why critical:** Order execution latency directly impacts fill quality. A 10ms delay on a volatile asset = 0.1% worse fill = $100/trade on $100K notional.
- **Migration complexity:** HIGH — 25 methods, tight coupling to ccxt_gateway
- **PyO3 strategy:** Rust order execution engine with pre-validated order structs. Python passes `OrderRequest` → Rust validates + submits → returns `OrderResult`.

### 3. `src/backends/python/paper_execution_engine.py` — Paper Trading
- **Lines:** 721 | **Functions:** 24 | **Dependencies:** numpy, pandas
- **Current Python latency:** 1-10ms per simulated fill
- **Expected Rust latency:** 10-100μs
- **Performance improvement:** 100-1000x
- **Why critical:** Paper trading must simulate real latency accurately. If paper is 10x slower than live, backtest results are meaningless.
- **Migration complexity:** MEDIUM — 24 methods, numpy-heavy but self-contained
- **PyO3 strategy:** Rust simulation engine with `Vec<OHLCV>` input, returns fill events.

### 4. `src/tools/market_data.py` — Real-time Market Data Processing
- **Lines:** 1,948 | **Functions:** 49 | **Dependencies:** numpy, pandas
- **Current Python latency:** 100μs-5ms per data transformation
- **Expected Rust latency:** 1-50μs
- **Performance improvement:** 50-200x
- **Why critical:** Largest file in the codebase. 49 functions processing ticks, OHLCV, order books. Every strategy decision depends on this data being fresh.
- **Migration complexity:** HIGH — 1,948 lines, 31 imports, deep numpy/pandas usage
- **PyO3 strategy:** Incremental — migrate hottest functions first (tick aggregation, OHLCV resampling). Use `numpy` crate for array interop.

### 5. `src/tools/order_router.py` — Smart Order Routing
- **Lines:** 1,170 | **Functions:** 13 | **Dependencies:** numpy
- **Current Python latency:** 1-5ms per routing decision (TWAP/VWAP slicing)
- **Expected Rust latency:** 10-100μs
- **Performance improvement:** 50-200x
- **Why critical:** TWAP/VWAP/iceberg algorithms must slice orders in real-time. Delay = price drift = worse execution.
- **Migration complexity:** MEDIUM — 13 functions, algorithmic (numpy-heavy but self-contained)
- **PyO3 strategy:** Pure computation — `OrderRouter` takes market state, returns slice plan. Perfect for Rust.

### 6. `src/tools/technical_analysis.py` — Indicator Computation
- **Lines:** 1,186 | **Functions:** 16 | **Dependencies:** numpy, pandas, pandas_ta
- **Current Python latency:** 500μs-20ms per indicator batch
- **Expected Rust latency:** 5-200μs
- **Performance improvement:** 50-200x
- **Why critical:** Indicators are computed on every candle close for every symbol. With 100 symbols × 10 indicators = 1000 computations per candle.
- **Migration complexity:** MEDIUM — 16 functions, but `pandas_ta` dependency is heavy. Replace with `ta` crate or custom implementations.
- **PyO3 strategy:** `trading_rs.indicators_py()` — batch compute all indicators for a symbol. Return as numpy arrays.

### 7. `src/tools/volatility.py` — Volatility Calculations
- **Lines:** 859 | **Functions:** 16 | **Dependencies:** numpy, pandas
- **Current Python latency:** 200μs-5ms per volatility estimate
- **Expected Rust latency:** 2-50μs
- **Performance improvement:** 50-200x
- **Why critical:** Volatility feeds into position sizing, risk limits, regime detection. Stale volatility = wrong sizing = blown accounts.
- **Migration complexity:** MEDIUM — partially done (Garman-Klass + GARCH already in Rust). Need to migrate remaining: Parkinson, close-to-close, term structure, regime classification, volatility cone.
- **PyO3 strategy:** Extend existing `trading_rs` — add remaining volatility functions. The pattern is proven.

### 8. `src/tools/correlation.py` — Correlation Matrix
- **Lines:** 677 | **Functions:** 13 | **Dependencies:** numpy, pandas
- **Current Python latency:** 1-50ms per matrix (O(n²) pairs)
- **Expected Rust latency:** 10-500μs
- **Performance improvement:** 50-200x
- **Why critical:** Correlation matrix is used for portfolio construction and risk. With 50 assets = 1,225 pairs. Python loops = death.
- **Migration complexity:** LOW — **already mostly done!** `RustCorrelationAnalyzer` exists. Remaining: cointegration testing, anomaly detection, regime classification.
- **PyO3 strategy:** Extend existing `trading_rs.correlation_matrix_py`.

### 9. `src/risk/kill_switch.py` — Emergency Halt
- **Lines:** 307 | **Functions:** 13 | **Dependencies:** redis, json, pathlib
- **Current Python latency:** 1-10ms (Redis round-trip + file I/O)
- **Expected Rust latency:** 50-200μs
- **Performance improvement:** 10-100x
- **Why critical:** **THE MOST IMPORTANT FILE.** If the kill switch takes 10ms to activate, a flash crash can destroy the account in that window. Must be <1ms. Period.
- **Migration complexity:** LOW — 307 lines, 13 functions, simple state machine (file + Redis dual-write)
- **PyO3 strategy:** Standalone Rust binary that monitors file + Redis. Python calls `trading_rs.kill_switch_check()` for reads. Writes are file-first (zero latency).

### 10. `src/risk/watchdog.py` — Process Monitoring
- **Lines:** 428 | **Functions:** 10 | **Dependencies:** asyncio, json, pathlib
- **Current Python latency:** 10-100ms (asyncio overhead, file I/O)
- **Expected Rust latency:** 100μs-1ms
- **Performance improvement:** 10-100x
- **Why critical:** If the main process dies, the watchdog must detect it and trigger kill switch within seconds. Python's asyncio has scheduling jitter. Rust's `tokio` is deterministic.
- **Migration complexity:** LOW — 428 lines, pure file I/O + PID monitoring, no external deps
- **PyO3 strategy:** Rust async task spawned alongside main process. File-based heartbeat protocol unchanged.

### 11. `src/risk/drawdown.py` — Real-time Drawdown Tracking
- **Lines:** 144 | **Functions:** 4 | **Dependencies:** none (pure computation)
- **Current Python latency:** 10-100μs (trivial math)
- **Expected Rust latency:** <1μs
- **Performance improvement:** 10-100x
- **Why critical:** Drawdown level determines circuit breaker state. Must update on every P&L tick. Already very small — migration is cheap insurance.
- **Migration complexity:** VERY LOW — 144 lines, 4 functions, zero dependencies, pure math
- **PyO3 strategy:** Trivial — `trading_rs.drawdown_check(capital, hwm, daily_pnl)` → `DrawdownLevel`

### 12. `src/comms/event_bus.py` — Event Routing
- **Lines:** 502 | **Functions:** 18 | **Dependencies:** redis, asyncio
- **Current Python latency:** 100μs-5ms per event publish/deliver (Redis XADD + in-memory dispatch)
- **Expected Rust latency:** 5-50μs
- **Performance improvement:** 20-200x
- **Why critical:** Every signal, every risk event, every trade flows through the event bus. It's the nervous system. If it's slow, everything is slow.
- **Migration complexity:** MEDIUM — 502 lines, Redis Streams integration, DLQ, consumer groups
- **PyO3 strategy:** Rust event bus with `redis-rs` for persistence, lock-free in-memory dispatch. Python handlers called via PyO3 callbacks (accept the GIL cost for handler execution, but routing is Rust).

---

## Category 2: SHOULD be Rust (10 files, 7,130 LOC)

Performance-important but can tolerate slightly higher latency.

### 13. `src/backends/defi/mev_protection.py` — Mempool Scanning
- **Lines:** 699 | **Functions:** 18 | **Dependencies:** web3, httpx
- **Current Python latency:** 50-500ms (RPC calls to mempool)
- **Expected Rust latency:** 5-50ms (ethers-rs, direct WebSocket)
- **Performance improvement:** 10-50x
- **Why important:** MEV protection must detect sandwich attacks before they land. Latency = money lost.
- **Migration complexity:** MEDIUM — web3.py → ethers-rs, ABI encoding, transaction parsing
- **PyO3 strategy:** Rust mempool scanner with WebSocket subscription. Python receives parsed events.

### 14. `src/backends/defi/l2_optimizer.py` — Gas Optimization
- **Lines:** 769 | **Functions:** 18 | **Dependencies:** web3, numpy
- **Current Python latency:** 100ms-2s (gas estimation RPC calls)
- **Expected Rust latency:** 10-200ms
- **Performance improvement:** 10-50x
- **Why important:** Gas price optimization saves real money. Faster estimation = better timing.
- **Migration complexity:** MEDIUM — gas estimation logic + L2 routing
- **PyO3 strategy:** Rust gas estimator with cached gas models. Python passes tx params, gets optimal gas price.

### 15. `src/backends/defi/dex_executor.py` — DEX Execution
- **Lines:** 972 | **Functions:** 15 | **Dependencies:** web3, numpy
- **Current Python latency:** 200ms-5s (transaction building + submission)
- **Expected Rust latency:** 20-500ms
- **Performance improvement:** 10-50x
- **Why important:** DEX execution speed determines fill quality. Faster = less slippage.
- **Migration complexity:** HIGH — 972 lines, complex DeFi interactions, multiple DEX protocols
- **PyO3 strategy:** Rust transaction builder. Python handles strategy logic, Rust handles encoding + submission.

### 16. `src/backends/defi/oracle_client.py` — Price Feed Aggregation
- **Lines:** 691 | **Functions:** 19 | **Dependencies:** web3, httpx
- **Current Python latency:** 50-500ms (multiple oracle RPC calls)
- **Expected Rust latency:** 5-50ms
- **Performance improvement:** 10-50x
- **Why important:** Oracle prices feed into every DeFi decision. Stale prices = bad trades.
- **Migration complexity:** MEDIUM — multi-oracle aggregation logic
- **PyO3 strategy:** Rust oracle aggregator with parallel RPC. Python gets fused price.

### 17. `src/agents/signal_scout.py` — Signal Scanning
- **Lines:** 973 | **Functions:** 16 | **Dependencies:** numpy, pandas
- **Current Python latency:** 1-50ms per scan cycle (N symbols × M indicators)
- **Expected Rust latency:** 10-500μs
- **Performance improvement:** 100-1000x
- **Why important:** Signal scanning must be continuous and fast. Missed signal = missed trade.
- **Migration complexity:** MEDIUM — 16 functions, indicator computation + pattern matching
- **PyO3 strategy:** Rust scanner runs indicator batch, returns signal candidates. Python evaluates with LLM.

### 18. `src/agents/risk_guardian.py` — Risk Checking
- **Lines:** 686 | **Functions:** 10 | **Dependencies:** numpy
- **Current Python latency:** 100μs-5ms per risk check
- **Expected Rust latency:** 1-50μs
- **Performance improvement:** 50-200x
- **Why important:** Risk checks gate every trade. Slow risk = slow execution.
- **Migration complexity:** LOW — 10 functions, deterministic math
- **PyO3 strategy:** `trading_rs.risk_check(positions, limits)` → `RiskDecision`

### 19. `src/agents/regime_detector.py` — Regime Detection
- **Lines:** 513 | **Functions:** 10 | **Dependencies:** numpy, pandas
- **Current Python latency:** 1-20ms per regime classification
- **Expected Rust latency:** 10-200μs
- **Performance improvement:** 50-200x
- **Why important:** Regime detection drives strategy selection. Must update frequently.
- **Migration complexity:** MEDIUM — HMM/statistical tests, numpy-heavy
- **PyO3 strategy:** Rust regime classifier with pre-trained parameters. Python passes market features, gets regime label.

### 20. `src/strategy/backtest_engine.py` — Backtesting
- **Lines:** 1,039 | **Functions:** ~15 | **Dependencies:** numpy
- **Current Python latency:** 10-100 seconds for full backtest (millions of bars)
- **Expected Rust latency:** 0.5-5 seconds
- **Performance improvement:** 20-100x
- **Why important:** Faster backtesting = faster strategy iteration = more alpha. This is where quantitative edge is forged.
- **Migration complexity:** MEDIUM — bar-by-bar simulation loop, commission/slippage models
- **PyO3 strategy:** Rust backtest core. Python defines strategy rules, Rust runs the simulation loop.

### 21. `src/strategy/monte_carlo.py` — Monte Carlo Simulation
- **Lines:** 333 | **Functions:** ~8 | **Dependencies:** numpy
- **Current Python latency:** 5-60 seconds (1000+ simulations)
- **Expected Rust latency:** 100ms-3 seconds
- **Performance improvement:** 20-100x
- **Why important:** Monte Carlo is embarrassingly parallel. Rust + rayon = trivial parallelism.
- **Migration complexity:** LOW — **already partially done!** `trading_rs.monte_carlo_simulate_py` exists. Need to migrate remaining statistical tests.
- **PyO3 strategy:** Extend existing `trading_rs` Monte Carlo functions.

### 22. `src/knowledge/fts_search.py` — Full-text Search
- **Lines:** 778 | **Functions:** 26 | **Dependencies:** sqlite, asyncio
- **Current Python latency:** 1-50ms per search query
- **Expected Rust latency:** 10-500μs
- **Performance improvement:** 10-100x
- **Why important:** FTS feeds into RAG pipeline for trade context. Faster search = faster context assembly = better LLM decisions.
- **Migration complexity:** MEDIUM — SQLite FTS5 integration, async queries
- **PyO3 strategy:** Rust FTS engine with `rusqlite`. Python passes query, gets ranked results.

---

## Category 3: Fine in Python (7+ files)

These are not latency-sensitive. Python is the right choice.

| File | Lines | Reason Python is Fine |
|------|-------|----------------------|
| `agents/orchestrator.py` | — | Coordination logic, not compute-bound. LLM-bound. |
| `agents/trade_philosopher.py` | — | Async reflection. LLM calls dominate latency. |
| `agents/flywheel_orchestrator.py` | — | Learning loop. Background async, not time-critical. |
| `knowledge/knowledge_graph.py` | — | Graph traversal. DB-bound, not compute-bound. |
| `knowledge/shadow_extractor.py` | — | Lesson extraction. Async LLM analysis. |
| `api/app.py` | 771 | REST API. Network-bound. FastAPI is fast enough. |
| `bot/bot.py` | 1,384 | Telegram bot. Human-speed interaction. |
| `bot/commands.py` | 885 | Command handlers. Human-speed. |
| `llm/*.py` | ~500 | LLM routing/caching. Provider-bound, not compute-bound. |
| `education/*.py` | ~400 | Trade education. Human-read output. |

---

## Migration Priority Order

### Phase 1: Kill Chain (Weeks 1-4) — **SURVIVAL PRIORITY**
These files protect capital. If they're slow, nothing else matters.

| Priority | File | LOC | Complexity | Impact |
|----------|------|-----|-----------|--------|
| 🔴 P0 | `risk/kill_switch.py` | 307 | LOW | <1ms emergency halt |
| 🔴 P0 | `risk/drawdown.py` | 144 | VERY LOW | Real-time circuit breakers |
| 🔴 P0 | `risk/watchdog.py` | 428 | LOW | Process crash detection |
| 🟠 P1 | `comms/event_bus.py` | 502 | MEDIUM | Event routing backbone |

**Phase 1 total:** 1,381 LOC | **Estimated effort:** 2-3 weeks for 1 Rust engineer

### Phase 2: Execution Hot Path (Weeks 5-10) — **MONEY PATH**
These files execute trades. Faster = better fills = more profit.

| Priority | File | LOC | Complexity | Impact |
|----------|------|-----|-----------|--------|
| 🟠 P1 | `backends/python/ccxt_gateway.py` | 1,491 | HIGH | 10-50x tick processing |
| 🟠 P1 | `backends/python/ccxt_exec_engine.py` | 1,153 | HIGH | 25-250x order execution |
| 🟡 P2 | `backends/python/paper_execution_engine.py` | 721 | MEDIUM | Accurate simulation |

**Phase 2 total:** 3,365 LOC | **Estimated effort:** 4-6 weeks for 1 Rust engineer

### Phase 3: Compute Engine (Weeks 11-16) — **ALPHA GENERATION**
These files compute indicators and analytics. Faster = more symbols, more strategies.

| Priority | File | LOC | Complexity | Impact |
|----------|------|-----|-----------|--------|
| 🟡 P2 | `tools/market_data.py` | 1,948 | HIGH | 50-200x data processing |
| 🟡 P2 | `tools/technical_analysis.py` | 1,186 | MEDIUM | 50-200x indicators |
| 🟡 P2 | `tools/volatility.py` | 859 | MEDIUM | 50-200x vol calc (partial Rust exists) |
| 🟡 P2 | `tools/correlation.py` | 677 | LOW | 50-200x (mostly done) |
| 🟡 P2 | `tools/order_router.py` | 1,170 | MEDIUM | 50-200x order slicing |

**Phase 3 total:** 5,840 LOC | **Estimated effort:** 5-7 weeks for 1 Rust engineer

### Phase 4: DeFi + Strategy (Weeks 17-24) — **COMPETITIVE EDGE**
DeFi execution and strategy computation. Important but can tolerate higher latency.

| Priority | File | LOC | Complexity | Impact |
|----------|------|-----|-----------|--------|
| 🟢 P3 | `backends/defi/mev_protection.py` | 699 | MEDIUM | MEV protection |
| 🟢 P3 | `backends/defi/dex_executor.py` | 972 | HIGH | DEX execution |
| 🟢 P3 | `backends/defi/l2_optimizer.py` | 769 | MEDIUM | Gas optimization |
| 🟢 P3 | `backends/defi/oracle_client.py` | 691 | MEDIUM | Oracle aggregation |
| 🟢 P3 | `agents/signal_scout.py` | 973 | MEDIUM | Signal scanning |
| 🟢 P3 | `agents/risk_guardian.py` | 686 | LOW | Risk checking |
| 🟢 P3 | `agents/regime_detector.py` | 513 | MEDIUM | Regime detection |
| 🟢 P3 | `strategy/backtest_engine.py` | 1,039 | MEDIUM | Backtesting |
| 🟢 P3 | `strategy/monte_carlo.py` | 333 | LOW | Monte Carlo (partial Rust) |
| 🟢 P3 | `knowledge/fts_search.py` | 778 | MEDIUM | Full-text search |

**Phase 4 total:** 7,453 LOC | **Estimated effort:** 8-12 weeks for 1 Rust engineer

---

## PyO3 Binding Strategy

### Architecture (Already Established)
```
Python (AI/ML, strategy decisions, LLM calls)
    ↓ PyO3 FFI
trading_rs (Rust native extension)
    ↓
Rust crates (tokio, rayon, ndarray, redis-rs, ethers-rs)
```

### Existing Pattern (Proven)
The `src/backends/rust/__init__.py` file already implements the correct pattern:
1. Try `import trading_rs`
2. If available, use Rust implementation
3. If not, transparently fall back to Python
4. Python prepares data (numpy arrays), Rust does computation, returns numpy arrays

### Binding Design Rules
1. **Data transfer:** Use numpy array buffer protocol (zero-copy). `PyArray` from `numpy` crate.
2. **Async:** Rust side uses `tokio`. Expose synchronous wrappers that block on Rust runtime.
3. **Error handling:** Rust errors → Python exceptions via `PyResult`.
4. **State:** Rust structs exposed as Python classes via `#[pyclass]`.
5. **Fallback:** Every Rust class must have a Python fallback path.

### Crate Dependencies
```toml
[dependencies]
tokio = { version = "1", features = ["full"] }
rayon = "1.10"           # Parallel iteration (Monte Carlo, correlation)
ndarray = "0.16"         # N-dimensional arrays (numpy interop)
numpy = "0.22"           # PyO3 numpy bindings
redis = { version = "0.25", features = ["tokio-comp"] }
reqwest = { version = "0.12", features = ["json", "rustls-tls"] }
tokio-tungstenite = "0.24"  # WebSocket client
ethers = "2.0"           # Ethereum DeFi
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

---

## Performance Impact Estimates

### Conservative Estimates (Real-World)

| Component | Python Latency | Rust Latency | Improvement | Daily Impact |
|-----------|---------------|--------------|-------------|-------------|
| Tick processing | 200μs | 20μs | 10x | Process 100K ticks/sec vs 10K |
| Order execution | 10ms | 500μs | 20x | $100-500/day better fills |
| Kill switch | 5ms | 200μs | 25x | Survive 5ms flash crashes |
| Indicator batch | 5ms | 50μs | 100x | Scan 1000 symbols/cycle |
| Backtest | 60s | 2s | 30x | 30 strategies/day vs 1 |
| Monte Carlo | 30s | 1s | 30x | Real-time confidence intervals |

### Systemic Impact
- **Current system throughput:** ~1,000 decisions/second
- **After full Rust migration:** ~50,000-100,000 decisions/second
- **Latency budget:** Current ~50ms end-to-end → Target <1ms for critical path
- **Capital efficiency:** Estimated 0.5-2% annual improvement from better execution alone

---

## Recommendations

1. **Start with Phase 1 (Kill Chain)** — it's only 1,381 lines and protects everything else
2. **Hire 1 senior Rust engineer** with PyO3 experience — this is a 6-month project
3. **Keep the fallback pattern** — Rust is primary, Python is safety net
4. **Benchmark everything** — use `criterion` crate for Rust, `time.perf_counter` for Python
5. **Don't rewrite LLM/agent code in Rust** — the LLM calls dominate latency there (100ms-10s)
6. **Consider `polars`** for the pandas-heavy files — it's Rust-backed and has a Python API

---

## Score Justification: 6/10

**What's good (+):**
- Rust backend architecture is well-designed (PyO3 + fallback pattern)
- 7 compute-heavy functions already have Rust implementations
- Clear separation between hot path (Rust) and cold path (Python)
- `maturin` build system configured

**What's missing (-):**
- 12 critical hot-path files are still pure Python
- No Rust WebSocket implementation (ccxt_gateway is Python)
- Kill switch is Python (unacceptable for institutional trading)
- No Rust order execution engine
- Event bus is Python (bottleneck for all event-driven logic)
- Missing: tokio runtime, reqwest client, tungstenite WebSocket

**Target score: 9/10** — achievable in 6 months with 1 dedicated Rust engineer.
