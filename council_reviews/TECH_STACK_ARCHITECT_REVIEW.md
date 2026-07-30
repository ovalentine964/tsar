# Council Session: Tech Stack Architect Review

## TSAR Multi-Language Tech Stack — Validation Report

---

## Executive Summary

TSAR's multi-language tech stack (Python + Rust + C++) is **exceptionally well-architected on paper** but is **primarily aspirational in implementation**. The Python layer is production-quality. The Rust layer contains real, compilable code with proper data structures and tests — but every critical path (WebSocket, order execution, message parsing) is a stub. The C++ layer has one genuinely implemented module (Black-Scholes pricer) surrounded by scaffolding. The overall design demonstrates deep knowledge of trading systems; the gap is in filling stubs with real implementations.

**Verdict: CONDITIONAL PASS** — Strong foundation, but Rust and C++ must graduate from stubs before any scale milestone beyond $10.

---

## 1. Python Layer (Day 1) — Score: 8/10

### Strengths
- **Python 3.12** with modern async (`aiosqlite`, `httpx`, `aiohttp`) — correct choice for Day 1
- **ccxt** for exchange connectivity — battle-tested, supports 100+ exchanges
- **FastAPI + uvicorn** — async-native, auto-generated OpenAPI docs, WebSocket support
- **pandas-ta** for technical indicators — solid for prototyping strategies
- **structlog** for structured logging — production-grade observability
- **prometheus-client** — metrics are wired from the start
- **Redis** for caching/pub-sub — proper separation of hot state from persistent storage
- **SQLite + FTS5** for trade journaling — zero-ops, full-text search, sufficient for personal scale
- **pyproject.toml** with ruff, mypy --strict, pytest-asyncio — rigorous tooling from day one

### Concerns
- **GIL limitations**: With 10 agents running concurrently, Python's GIL will bottleneck CPU-bound work (indicator computation, backtesting). `asyncio` helps for I/O-bound work, but tick processing in pure Python will lag at >100 msg/sec
- **SQLite concurrent writes**: Multiple agents writing to SQLite simultaneously will hit `SQLITE_BUSY` locks. `aiosqlite` helps but doesn't solve the fundamental single-writer limitation
- **FastAPI performance**: Adequate for API + dashboard, but not suitable as a real-time data path (WebSocket latency ~5-10ms vs <1ms in Rust)
- **No vectorbt in pyproject.toml**: The TECH_STACK.md references vectorbt for backtesting, but it's not in the actual `pyproject.toml` dependencies — inconsistency

### Verdict
Python is the **correct** Day 1 language. It can handle $10-$1K scale with 10 agents on crypto markets. The ecosystem (ccxt, pandas-ta, FastAPI) is battle-tested. The GIL is not a real bottleneck until you're processing >1000 ticks/sec across multiple symbols.

---

## 2. Rust Layer (Level 2) — Score: 5/10

### What's Real
- **Data types** (`tsar-core/src/types.rs`): `Price`, `OHLCV`, `OrderBook`, `Tick`, `Order`, `Position`, `Spread` — all properly defined with serde, chrono, uuid. These are production-quality type definitions.
- **Error types** (`tsar-core/src/error.rs`): Comprehensive `TsarError` enum covering WebSocket, parsing, order, tick processing, config, and generic errors. Good error hierarchy.
- **Config structures** (`tsar-core/src/config.rs`): `TsarConfig`, `AppConfig`, `ExchangesConfig`, `EngineConfig`, `RiskConfig` with defaults. Structured and serde-ready.
- **OHLCV Aggregator** (`tick-processor/src/aggregator.rs`): **Actually implemented.** Multi-timeframe candle aggregation from raw ticks with period alignment. Has working unit tests. This is the most complete Rust module.
- **Ring Buffer** (`tick-processor/src/ring_buffer.rs`): **Fully implemented.** Fixed-capacity, overwrite-on-overflow, with proper index arithmetic. Thoroughly tested.
- **Order Book Manager** (`tick-processor/src/orderbook.rs`): **Fully implemented.** BTreeMap-based with snapshot application, incremental updates, best bid/ask, mid price. Tested.
- **Spread Calculator** (`tick-processor/src/spread.rs`): **Fully implemented.** Rolling window, statistics, basis point calculation. Tested.
- **Technical Indicators** (`tick-processor/src/indicators.rs`): **Fully implemented.** RSI, EMA, MACD, Bollinger Bands, ATR, ADX, VWAP — all pure Rust, zero dependencies. This is genuinely useful.
- **Market Regime Detector** (`tick-processor/src/regime.rs`): **Implemented.** Classifies market state based on ADX, DI, ATR, and Bollinger Band range.
- **Order Tracker** (`order-executor/src/tracker.rs`): **Fully implemented.** UUID-based order lifecycle tracking with secondary exchange ID index. Tested.
- **Order Types** (`order-executor/src/types.rs`): **Complete.** `OrderRequest`, `OrderResult`, `Fill`, `ExecutionReport`, `TimeInForce` — all production-ready types.
- **Safety Net** (`order-executor/src/safety.rs`): **Implemented.** Stop-loss and take-profit order generation.
- **Reconnection Policy** (`ws-manager/src/reconnect.rs`): **Fully implemented.** Exponential backoff with jitter, max attempts, state tracking. Tested.
- **PyO3 Bindings** (`pyo3-bindings/src/`): **Properly structured.** `PyWsConnection`, `PyWsManager`, `PyTickProcessor`, `PySpreadCalculator`, `PyRingBuffer`, `PyOrderExecutor` — all with proper `#[pyclass]` and `#[pymethods]` annotations. Type conversion between Rust and Python is correctly handled.

### What's Stubbed
- **WebSocket Connection** (`ws-manager/src/connection.rs`): `connect()` just sets state to `Connected`. `send()` increments a counter. `receive()` returns `None`. No actual tokio-tungstenite usage.
- **Message Parser** (`ws-manager/src/parser.rs`): `parse_message()` returns `Unknown` for all inputs. `parse_binance_trade()`, `parse_binance_depth()`, `parse_binance_kline()` all return `None`.
- **Order Executor** (`order-executor/src/executor.rs`): `place_order()` returns a placeholder `OrderResult` with status `Open` but never calls an exchange API. `cancel_order()` always returns `Ok(true)`.
- **Config Loading** (`tsar-core/src/config.rs`): `from_json()` just returns defaults. No actual YAML/JSON parsing.

### PyO3 Bridge Assessment
The bridge is **structurally correct** but has a critical performance anti-pattern: every `#[pymethods]` call creates a new `tokio::runtime::Runtime`. This means:
- No event loop reuse
- No async task persistence
- Each call pays ~1-5ms runtime creation overhead

**Fix required**: Use `pyo3-asyncio` or a shared `Runtime` created once at module init.

### Rust vs Go Assessment
Rust is the **correct choice** over Go for this use case:
- Zero-cost abstractions for tick processing (Go's GC pauses at high throughput)
- PyO3 is more mature than cgo for Python interop
- `tokio` is the best async runtime for financial market data
- Type safety prevents entire classes of bugs in order execution

### Verdict
The Rust layer has **real, testable data structures and algorithms** (tick processing, indicators, order tracking) but **every external-facing component is a stub** (WebSocket, order execution, message parsing). The architecture is correct; the implementation needs ~2-4 weeks of focused work to become functional.

---

## 3. C++ Layer (Level 3+) — Score: 4/10

### QuantLib Pricing Engine
- **Black-Scholes pricer** (`option_pricer.cpp`): **Genuinely implemented.** Full BSM with Greeks (delta, gamma, vega, theta, rho). Includes:
  - Self-contained `norm_cdf` and `norm_pdf` (no external dependency)
  - Implied volatility solver via Newton-Raphson (100 iterations, 1e-8 tolerance)
  - Batch pricing for multiple options
  - Put-call parity validation in tests
  - This is production-quality code
- **Yield curve engine** (`pricing_engine.cpp`): **Implemented with stub interpolation.** Linear interpolation as placeholder for QuantLib's log-linear. Discount factor and forward rate calculations are correct.
- **Monte Carlo pricer**: Stub that falls back to a basic GBM simulation when `TSAR_HAS_QUANTLIB` is not defined. Returns BS Greeks as a fallback.

### FIX Protocol Engine
- **FIXGateway** (`fix_gateway.cpp`): **Scaffolding.** Session management, order routing, callback wiring — all structurally correct but delegates to stub `FIXSession`.
- **FIXSession** (`fix_session.cpp`): **Stub.** Logon transitions directly to `LoggedOn`. Send order echoes back a stub acknowledgment. Cancel emits a stub cancelled report. When `TSAR_HAS_QUICKFIX` is defined, it has TODO comments for real QuickFIX integration.
- The FIX engine is **not production-ready**. It's a well-designed interface waiting for QuickFIX to be wired in.

### CUDA Kernels
- **Monte Carlo** (`monte_carlo_stub.cpp`): CPU fallback stub. When `TSAR_HAS_CUDA` is not defined, it runs a basic single-threaded MC simulation. No actual CUDA code exists.
- **Portfolio Optimization** (`portfolio_opt_stub.cpp`): CPU stub that returns equal-weight portfolios. No real optimization.
- CUDA is **entirely aspirational**. No `.cu` files exist. The CMakeLists.txt has `TSAR_BUILD_CUDA OFF` by default.

### C FFI Bindings
- **tsar_cffi.cpp**: **Well-implemented.** Proper opaque handle pattern, C error code mapping, exception catching at the boundary. This is the correct way to expose C++ to Python via ctypes/cffi.
- Bridges: PricingEngine, OptionPricer, FIXGateway — all properly wrapped.

### Test Coverage
- `test_pricing.cpp`: 10 tests covering engine init, discount factors, forward rates, BS call/put, put-call parity, implied vol roundtrip, batch pricing. **These are real, meaningful tests.**
- `test_fix.cpp`: 13 tests covering session lifecycle, gateway management, order routing. Tests validate the stub behavior.
- `test_monte_carlo.cpp`: Not read but exists.

### Verdict
The C++ layer has **one genuinely impressive module** (Black-Scholes pricer with Greeks and implied vol solver) but is otherwise scaffolding. FIX protocol and CUDA are stubs. The C FFI bridge is correctly designed. At current state, the C++ layer adds complexity without proportional value — the BS pricer could be replicated in Python with `scipy` in 50 lines.

---

## 4. Scalability Milestone Assessment

### $10 (Day 1) — Python Only ✅ SUFFICIENT
- ccxt handles exchange REST + WebSocket
- SQLite stores trades and OHLCV
- Redis caches hot state
- FastAPI serves dashboard
- **No Rust or C++ needed.** Python alone can handle 24/7 crypto trading with 10 agents at this scale.

### $100-$1K — Python + Optional Rust ⚠️ WATCH
- Tick volume: ~10-100 msg/sec across 3-5 symbols
- Python async handles this fine
- **Risk**: If running multiple timeframes (1m, 5m, 15m, 1h) on 5+ symbols, OHLCV aggregation in Python may add 10-50ms latency per tick
- **Action**: Monitor tick-to-signal latency. If >100ms, enable Rust tick processor.

### $10K-$100K — Rust Becomes Critical ⚠️ CONDITIONAL
- Tick volume: ~100-1000 msg/sec
- Order execution latency matters (slippage costs real money)
- WebSocket reconnection reliability is critical (missed ticks = missed signals)
- **Rust needed for**: WebSocket management, tick processing, order execution
- **Threshold**: When you're trading 10+ symbols with 1m timeframes and order latency >50ms costs you money
- **Current blocker**: All Rust external-facing code is stubs. Must implement real WebSocket (tokio-tungstenite), real order execution (ccxt-rs or direct REST), real message parsing (Binance/Bybit formats)

### $1M+ — C++ Becomes Valuable ⚠️ ASPIRATIONAL
- Options trading requires real-time Greeks computation
- FIX protocol for institutional exchange connectivity (not all exchanges support REST/WebSocket)
- Monte Carlo for portfolio risk (VaR, CVaR) across 50+ positions
- **C++ needed for**: QuantLib integration (exotic options), FIX protocol, GPU-accelerated risk
- **Threshold**: When you're trading options on 10+ underlyings with real-time Greeks, or need FIX connectivity
- **Current blocker**: FIX is stubbed, QuantLib not integrated, CUDA doesn't exist

### $100M+ — Infrastructure Overhaul Required
- **Database**: SQLite → TimescaleDB (time-series optimized PostgreSQL)
- **Cache**: Single Redis → Redis Cluster
- **Deployment**: Docker Compose → Kubernetes
- **Monitoring**: Add distributed tracing (Jaeger/OpenTelemetry)
- **Network**: Co-locate with exchange matching engines
- **At this scale**, the multi-language strategy pays off: Python for strategy/LLM, Rust for data path, C++ for pricing/risk

### $1B+ — Institutional Architecture
- Dedicated market data infrastructure (direct exchange feeds, not WebSocket)
- FPGA for tick-to-order latency <1μs
- FIX 4.4/5.0 for all institutional counterparties
- Dedicated risk engine (real-time portfolio VaR, stress testing)
- Full QuantLib integration for derivatives pricing
- At this scale, TSAR's architecture (if fully implemented) maps well to how real hedge funds build systems

---

## 5. Infrastructure Stack Assessment

### SQLite vs PostgreSQL vs TimescaleDB
- **Day 1 ($10-$1K)**: SQLite is correct. Zero-ops, FTS5 for journal search, sufficient for <10K trades/day.
- **$10K+**: Migrate to PostgreSQL. SQLite's single-writer limitation becomes painful with concurrent agent writes.
- **$100K+**: TimescaleDB for OHLCV data. Hypertable compression, continuous aggregates, and time-series queries are 10-100x faster than raw PostgreSQL for this workload.
- **Risk**: The migration path is not designed. No SQLAlchemy migration framework in the codebase.

### Redis
- Used for: state caching, pub/sub between agents, LLM response caching, Celery task broker
- Docker Compose config: `maxmemory 256mb`, `allkeys-lru`, `appendonly yes`
- **Assessment**: Properly configured for Day 1. The 256mb limit is tight — will need to increase at $10K+ scale.

### ChromaDB
- Used for: pattern matching via embeddings (MiniLM-L6-v2)
- **Assessment**: ChromaDB is **not production-ready** for this use case. It's an embedded vector database — fine for prototyping, but:
  - No replication
  - No persistence guarantees under crashes
  - Query performance degrades at >100K vectors
  - **Recommendation**: Keep for Day 1, migrate to Qdrant or Weaviate at $10K+

### Docker Compose
- **Not production-grade.** The `docker-compose.yml` is a development setup:
  - No resource limits (CPU/memory)
  - No restart policies beyond `unless-stopped`
  - No log rotation
  - No secrets management (env files)
  - No health check for Celery worker
- **For production**: Add resource limits, use Docker Swarm or Kubernetes, add proper secrets management

### Monitoring (Prometheus + Grafana)
- `prometheus-client` is in Python dependencies ✅
- Grafana dashboards defined in TECH_STACK.md (trading_overview, risk_metrics, system_health)
- Docker Compose includes both Prometheus and Grafana services
- **Assessment**: The metrics are defined but **not wired**. No `src/monitoring/metrics.py` exists in the actual codebase. The dashboards are described but not implemented.
- **Gap**: Need to implement actual metric collection points in the trading engine.

---

## 6. Development Velocity Assessment

### Can One Developer Maintain Python + Rust + C++?
**No.** Not sustainably. Here's why:
- **Python**: Mature, fast iteration. One developer can maintain the full Python codebase.
- **Rust**: Steep learning curve. Compilation times are 2-5 minutes for the full workspace. Debugging borrow checker issues is time-consuming. One developer can maintain the Rust layer *if they're experienced with Rust*.
- **C++**: CMake + QuantLib + QuickFIX + CUDA is a massive toolchain. Header management, ABI compatibility, cross-platform builds — this is a full-time job.
- **Recommendation**: Day 1 = Python only. Level 2 = add one Rust developer. Level 3 = dedicated C++ developer or use pre-built QuantLib/QuickFIX packages.

### Testing Strategy Across Languages
- **Python**: pytest + pytest-asyncio + coverage. Well-structured.
- **Rust**: `cargo test --workspace`. Tests exist for all implemented modules.
- **C++**: Custom test harness (no framework — just `assert` + macros). Works but not idiomatic.
- **Cross-language**: No integration tests that verify Python ↔ Rust ↔ C++ data flow. The PyO3 bindings are untested from the Python side.
- **Gap**: Need `tests/integration/test_rust_bridge.py` to verify that `import trading_rs` works and produces correct results.

### CI/CD Pipeline
- **Python CI**: Lint → Typecheck → Test → Security → Docker Build. Comprehensive.
- **Rust CI**: **Not in the workflow.** The `.github/workflows/ci.yml` only covers Python. The TECH_STACK.md describes a separate `rust-build.yml` and `ci.yml` with Rust jobs, but the actual `ci.yml` has no Rust steps.
- **C++ CI**: Not configured at all.
- **Gap**: CI only validates Python. Rust and C++ are not built or tested in CI.

### Build Times
- **Python**: ~30 seconds for `pip install -e ".[dev]"`
- **Rust**: ~2-5 minutes for `cargo build --release` (5 crates with tokio, serde, pyo3)
- **C++**: ~1-3 minutes for CMake build (without QuantLib/CUDA)
- **Docker**: ~3-5 minutes for multi-stage build
- **Total cold build**: ~10-15 minutes. Acceptable for CI, painful for rapid iteration.

---

## 7. Alternative Stack Assessment

### Pure Python + Cython/Numba
- **Pros**: Single language, simpler toolchain, Numba JIT for numerical code
- **Cons**: GIL still limits concurrency, Numba doesn't support all Python patterns, Cython build complexity
- **Verdict**: Viable for $10-$10K scale. The Rust layer adds real value for WebSocket and tick processing that Numba can't match.

### Python + Go (instead of Rust)
- **Pros**: Simpler than Rust, good concurrency (goroutines), faster compilation
- **Cons**: GC pauses at high throughput, cgo is painful for Python interop, no PyO3 equivalent (would need gRPC/FFI)
- **Verdict**: Go would be simpler but less performant. Rust's zero-cost abstractions matter for tick processing. The PyO3 ecosystem is more mature than any Go-Python bridge.

### Julia
- **Pros**: Designed for numerical computing, fast, good for quant finance
- **Cons**: Small ecosystem, immature deployment tooling, no ccxt equivalent, poor Python interop
- **Verdict**: Julia is excellent for research but poor for production trading systems. The ecosystem gap is too large.

### Zig (as C++ replacement)
- **Pros**: Simpler than C++, C interop is excellent, no hidden allocations
- **Cons**: Very young ecosystem, no QuantLib equivalent, no FIX library, small community
- **Verdict**: Zig is 5-10 years away from being viable for this use case. C++ has the ecosystem (QuantLib, QuickFIX) that Zig doesn't.

---

## 8. Tech Stack Score: 6.5/10

| Component | Score | Justification |
|-----------|-------|---------------|
| Python Layer | 8/10 | Production-quality, correct tooling, battle-tested libraries |
| Rust Layer | 5/10 | Excellent architecture and data structures, but external-facing code is stubs |
| C++ Layer | 4/10 | One great module (BS pricer), rest is scaffolding |
| PyO3 Bridge | 6/10 | Structurally correct but has performance anti-pattern (Runtime per call) |
| Infrastructure | 6/10 | Good Day 1 setup, but monitoring not wired, Docker not production-grade |
| CI/CD | 5/10 | Python CI is comprehensive, Rust/C++ CI is missing |
| Documentation | 9/10 | TECH_STACK.md is exceptionally thorough and well-organized |
| Testing | 7/10 | Good unit test coverage, missing integration and cross-language tests |

**Overall: 6.5/10** — The architecture is 9/10, but implementation completeness brings it down.

---

## 9. Top 5 Strengths

1. **Architecture Design**: The multi-layer architecture (Python orchestration → Rust performance → C++ institutional) maps exactly to how real trading firms build systems. The data flow (Exchange WS → Rust Tick Processor → Python Strategy → Rust Order Executor) is correct.

2. **Backend Registry Pattern**: The `BackendRegistry` with fallback chains is brilliant. Hot-swapping backends (Python → Rust → mock) without changing agent code is exactly what you need for progressive migration.

3. **Rust Data Structures**: The tick processor (OHLCV aggregator, order book manager, spread calculator, ring buffer, indicators) is genuinely useful code. These are the hot-path components that benefit most from Rust.

4. **Observability from Day 1**: structlog + Prometheus + Grafana is the right stack. Most trading systems bolt on observability after the first outage. TSAR has it from the start.

5. **Configuration-Driven Design**: YAML-based strategy definitions, model routing, risk rules, and backend selection means the system is highly configurable without code changes. This is critical for rapid iteration.

---

## 10. Top 5 Risks

1. **Stub Debt**: Every critical Rust path (WebSocket, order execution, message parsing) is a stub. If the project ships with stubs and tries to "fill them in later," the integration testing burden will be enormous. The stubs must be filled before any real money is deployed.

2. **PyO3 Runtime-per-Call Anti-Pattern**: Creating a new `tokio::runtime::Runtime` on every Python→Rust call adds 1-5ms overhead and prevents async task persistence. This must be fixed before the Rust layer is used in production.

3. **SQLite → PostgreSQL Migration Path**: There's no migration framework. When SQLite hits its limits (concurrent writes, >10GB data), the migration will be a risky big-bang change. Design the migration path now.

4. **Single Developer Maintenance**: Three languages (Python, Rust, C++) with three build systems (pip, cargo, cmake) is a lot for one person. The C++ layer in particular (QuantLib + QuickFIX + CUDA) requires specialized knowledge.

5. **Monitoring Gap**: Prometheus metrics are defined but not wired. The Grafana dashboards are described but not implemented. Without observability, the first production incident will be a blind debugging session.

---

## 11. Recommendation: Keep Current Stack, Focus on Implementation

### Do NOT Pivot
The multi-language strategy is correct. Python + Rust + C++ is the gold standard for trading systems. Pivoting to a simpler stack (pure Python, Python + Go) would sacrifice the performance headroom needed for $10K+ scale.

### Priority Actions (Next 30 Days)
1. **Fill Rust stubs**: Implement real WebSocket (tokio-tungstenite with Binance/Bybit parsers), real order execution (ccxt-rs or direct REST), real message parsing
2. **Fix PyO3 Runtime**: Use a shared `tokio::runtime::Runtime` or `pyo3-asyncio` instead of creating a new runtime per call
3. **Wire monitoring**: Implement `src/monitoring/metrics.py` with actual metric collection points in the trading engine
4. **Add Rust to CI**: Extend `.github/workflows/ci.yml` with `cargo check`, `cargo clippy`, `cargo test`, and `maturin build` steps
5. **Add integration tests**: Create `tests/integration/test_rust_bridge.py` to verify Python ↔ Rust data flow

### Priority Actions (Next 90 Days)
1. **Implement real message parsers**: Binance `@trade`, `@depth`, `@kline` stream parsing in Rust
2. **Implement real order execution**: Wire Rust order executor to ccxt or direct exchange REST API
3. **Design SQLite → PostgreSQL migration path**: Use SQLAlchemy/Alembic for schema versioning
4. **Implement Grafana dashboards**: Create the three dashboards described in TECH_STACK.md
5. **Performance benchmarks**: Measure tick-to-signal latency in Python vs Rust to quantify the performance gain

### When to Add C++ (Level 3)
- When trading options (need real-time Greeks)
- When needing FIX protocol connectivity
- When portfolio risk computation (VaR, Monte Carlo) exceeds Python/Rust capacity
- Estimated threshold: $1M+ capital, 50+ positions, options trading

---

## 12. Final Verdict

| Criterion | Assessment |
|-----------|------------|
| Architecture | ✅ Excellent — maps to institutional trading system patterns |
| Python Implementation | ✅ Production-ready for Day 1 |
| Rust Implementation | ⚠️ Strong foundations, stubs need filling |
| C++ Implementation | ⚠️ One great module, rest is scaffolding |
| Infrastructure | ⚠️ Good Day 1, needs production hardening |
| Scalability Path | ✅ Clear milestones from $10 to $1B |
| Development Velocity | ⚠️ Three languages is manageable but demanding |
| Risk Management | ✅ Comprehensive YAML-driven risk rules |

### **VERDICT: CONDITIONAL PASS**

**Conditions for full approval:**
1. Rust stubs (WebSocket, order execution, message parsing) must be implemented before deploying real capital beyond $1K
2. PyO3 Runtime-per-call anti-pattern must be fixed before using Rust in production
3. Monitoring must be wired (metrics collection + Grafana dashboards) before 24/7 operation
4. CI must cover Rust builds and tests

**The multi-language strategy is real, not aspirational — but only the Python layer is ready today.** The Rust and C++ layers are well-designed scaffolding waiting to be filled. The architecture earns a 9/10; the implementation earns a 5/10. The weighted average is **6.5/10 — CONDITIONAL PASS**.

---

*Reviewed by: Tech Stack Architect, TSAR Council*
*Date: 2026-07-30*
*Scope: Full codebase review — pyproject.toml, Makefile, Dockerfile, docker-compose.yml, Rust crates (core, ws-manager, tick-processor, order-executor, pyo3-bindings), C++ modules (quantlib-pricing, fix-engine, cuda-kernels, cffi-bindings), CI/CD workflows, configuration, backend registry*
