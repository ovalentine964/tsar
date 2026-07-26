# TSAR Council — Chief Architect Review
## Hybrid Rust + C++ Architecture Assessment

**Reviewer:** Chief Architect, TSAR Council  
**Date:** 2026-07-24  
**Subject:** Proposal to add C++ layer alongside existing Rust performance layer  
**Verdict:** ⚠️ **CONDITIONAL APPROVAL** — with strict gating criteria  

---

## 1. Executive Summary

The proposal adds C++ to TSAR's performance layer for three specific use cases:
- **QuantLib** — derivatives pricing (options, futures, structured products)
- **FIX protocol** — institutional forex connectivity (OANDA, Interactive Brokers)
- **CUDA/GPU** — Monte Carlo simulation acceleration

**Bottom line:** The C++ additions are **architecturally justified** for Level 3+ capabilities, but **premature for Day1 through Level 2**. The hybrid approach introduces significant build complexity that must be gated behind clear capability triggers, not adopted wholesale upfront.

---

## 2. Integration Complexity Assessment

### 2.1 Can PyO3 (Rust) and pybind11 (C++) Coexist?

**Yes, but with caveats.**

| Concern | Risk | Mitigation |
|---------|------|------------|
| Two native extension modules loaded simultaneously | Low — Python handles multiple `.so`/`.pyd` imports natively | Each bridge is an independent module (`trading_rs` from Rust, `trading_cpp` from C++) |
| GIL contention | Medium — both bridges may hold GIL during long operations | Use `pyo3::allow_threads` (Rust) and `pybind11::gil_scoped_release` (C++) consistently |
| Symbol conflicts | Low — separate shared libraries, no symbol overlap | Static linking of internal deps within each bridge |
| Type marshaling inconsistency | Medium — PyO3 and pybind11 have different type conversion semantics | Define canonical Python-side dataclasses; bridges convert to/from these |
| Debugging across two FFI boundaries | High — stack traces span Rust↔Python↔C++ | Structured logging with `trace_id` propagation (already in TSAR architecture §2.2) |

**Verdict:** Coexistence is feasible. Python already manages multiple native extensions (numpy, pandas, etc.). The key discipline is **never passing raw pointers between Rust and C++** — all cross-language data flows through Python as the intermediary.

### 2.2 Recommended Integration Pattern

```
Python (orchestrator)
    │
    ├── trading_rs (PyO3)     ← Rust: WS, tick processing, order execution
    │       │
    │       └── Exposes: Python-callable functions, returns Python objects
    │
    └── trading_cpp (pybind11) ← C++: QuantLib pricing, FIX engine, CUDA Monte Carlo
            │
            └── Exposes: Python-callable functions, returns Python objects
```

**Critical rule:** Rust and C++ modules **never call each other directly**. Python mediates all cross-module communication. This eliminates the need for a Rust↔C++ FFI layer (which would be a maintenance nightmare).

---

## 3. Build System Unification

### 3.1 Current State

| Language | Build Tool | Package Manager | Artifact |
|----------|-----------|----------------|----------|
| Python | pip / maturin | pip / pyproject.toml | `.whl` / editable install |
| Rust | Cargo | crates.io | `trading_rs.so` via maturin |

### 3.2 Proposed State

| Language | Build Tool | Package Manager | Artifact |
|----------|-----------|----------------|----------|
| Python | pip / maturin | pip | `.whl` |
| Rust | Cargo | crates.io | `trading_rs.so` |
| C++ | CMake | FetchContent / vcpkg | `trading_cpp.so` |

### 3.3 Unification Strategy

**Do NOT try to unify Cargo + CMake into one build system.** This is a well-known anti-pattern. Instead:

```
Makefile (orchestrator)
├── make rust-build     → cd rust && maturin develop --release
├── make cpp-build      → cd cpp && cmake -B build && cmake --build build && pip install -e .
└── make build          → make rust-build && make cpp-build
```

**Maturin for Rust, scikit-build-core for C++.** Both produce Python wheels. The Makefile orchestrates.

**C++ Build with scikit-build-core (recommended over raw CMake):**

```toml
# cpp/pyproject.toml
[build-system]
requires = ["scikit-build-core>=0.8", "pybind11>=2.12"]
build-backend = "scikit_build_core.build"
```

This integrates C++ into the Python packaging ecosystem cleanly — `pip install -e .` just works.

### 3.4 Dependency Management for C++

| Dependency | Source | Integration |
|-----------|--------|-------------|
| QuantLib | GitHub releases | CMake FetchContent or vcpkg |
| QuickFIX | GitHub | CMake FetchContent |
| CUDA Toolkit | NVIDIA | System install + CMake `find_package(CUDAToolkit)` |
| pybind11 | PyPI | scikit-build-core handles it |

**Risk:** QuantLib has Boost as a dependency, which is notoriously heavy. Consider building QuantLib as a static library with only the modules needed (pricing engines, stochastic processes, Monte Carlo framework).

---

## 4. Where C++ Adds Value vs Rust

### 4.1 Comparative Analysis

| Capability | Rust Option | C++ Option | Winner | Rationale |
|-----------|-------------|-----------|--------|-----------|
| **Derivatives pricing** | Write from scratch or FFI to QuantLib | QuantLib (mature, 25+ years) | **C++** | QuantLib is the industry standard. Reimplementing in Rust is 6-12 months of work for inferior results. |
| **FIX protocol** | `quickfix-rs` (immature) | QuickFIX (battle-tested, 20+ years) | **C++** | QuickFIX handles the full FIX spec including session management, resend requests, sequence number management. The Rust ecosystem has no equivalent. |
| **Monte Carlo on GPU** | No CUDA support | CUDA C++ (native) | **C++** | Rust has no production CUDA story. `rust-cuda` is experimental. CUDA C++ is the only viable path. |
| **WebSocket** | tokio-tungstenite (excellent) | Boost.Beast / libwebsockets | **Rust** | Already implemented, async-native, zero complaints. |
| **Tick processing** | Ring buffers, zero-copy (idiomatic Rust) | Possible but reinventing | **Rust** | Already implemented, memory-safe, fast. |
| **Order execution** | Serde + async (clean) | Possible but verbose | **Rust** | Already implemented, type-safe, ergonomic. |
| **FIX session mgmt** | Would need full implementation | QuickFIX handles it | **C++** | Non-negotiable for institutional forex. |

### 4.2 The Honest Assessment

**Rust is correct for:** WebSocket, tick processing, order execution, data structures, serialization. These are already built and working.

**C++ is correct for:** QuantLib derivatives pricing, FIX protocol, CUDA Monte Carlo. These leverage decades of institutional-grade C++ libraries with no viable Rust alternatives.

**The languages serve different purposes.** This is not "Rust vs C++" — it's "Rust for X, C++ for Y" where X and Y don't overlap.

---

## 5. C++ Module Architecture

### 5.1 Proposed C++ Crate Structure

```
tsar/cpp/
├── CMakeLists.txt              # Top-level CMake
├── pyproject.toml              # scikit-build-core config
├── src/
│   ├── bindings/
│   │   └── module.cpp          # pybind11 module entry point
│   ├── pricing/
│   │   ├── engine.h/cpp        # QuantLib pricing engine wrapper
│   │   ├── options.h/cpp       # Black-Scholes, Monte Carlo, Binomial
│   │   └── futures.h/cpp       # Futures pricing
│   ├── fix/
│   │   ├── session.h/cpp       # FIX session management
│   │   ├── application.h/cpp   # FIX application callbacks
│   │   └── adapter.h/cpp       # Exchange-specific FIX adapters
│   └── monte_carlo/
│       ├── simulator.h/cpp     # Monte Carlo engine
│       ├── gpu_kernel.cu       # CUDA kernels
│       └── cpu_fallback.h/cpp  # CPU fallback when no GPU
├── tests/
│   ├── test_pricing.cpp
│   ├── test_fix.cpp
│   └── test_monte_carlo.cpp
└── third_party/
    ├── quantlib/               # FetchContent
    ├── quickfix/               # FetchContent
    └── pybind11/               # FetchContent
```

### 5.2 Module Specifications

#### 5.2.1 Pricing Module (`tsar.pricing`)

```python
# Python interface (what agents call)
from trading_cpp.pricing import (
    black_scholes_price,
    monte_carlo_price,
    implied_volatility,
    greeks,
)

# Example usage
result = black_scholes_price(
    option_type="call",
    spot=65000.0,        # BTC price
    strike=66000.0,
    rate=0.05,
    volatility=0.80,
    time_to_expiry=30/365  # 30 days
)
# Returns: {"price": 2150.42, "delta": 0.48, "gamma": 0.0001, ...}
```

**QuantLib integration:** Wrap only the engines needed. Do NOT expose all of QuantLib.

#### 5.2.2 FIX Module (`tsar.fix`)

```python
# Python interface
from trading_cpp.fix import FIXSession, FIXConfig

config = FIXConfig(
    sender_comp_id="TSAR",
    target_comp_id="OANDA",
    host="fix.oanda.com",
    port=9876,
    heartbeat_interval=30,
)

session = FIXSession(config)
session.connect()
session.send_new_order(symbol="EUR/USD", side="buy", quantity=100000)
```

**QuickFIX integration:** Wrap the Application class, expose session lifecycle and order management to Python.

#### 5.2.3 Monte Carlo Module (`tsar.monte_carlo`)

```python
# Python interface
from trading_cpp.monte_carlo import simulate_paths, price_derivative

paths = simulate_paths(
    spot=65000.0,
    drift=0.0001,
    volatility=0.80,
    steps=252,
    num_paths=100_000,
    use_gpu=True,  # Falls back to CPU if no GPU
)
```

**CUDA strategy:** Write GPU kernels for path generation and payoff computation. CPU fallback uses OpenMP for parallelism. The Python interface is identical regardless of backend.

---

## 6. Complexity Cost Analysis

### 6.1 What the Hybrid Adds

| Dimension | Impact | Severity |
|-----------|--------|----------|
| Build system complexity | +1 build tool (CMake), +1 package manager (vcpkg/FetchContent) | Medium |
| CI/CD pipeline | Need CUDA-capable runners for GPU tests, QuantLib build (~10 min) | Medium |
| Developer skill requirement | Team needs Rust + C++ + Python proficiency | High |
| Debugging | Stack traces span 3 languages, need unified logging | Medium |
| Dependency management | QuantLib pulls Boost (~200MB), CUDA toolkit (~5GB) | Medium |
| Testing surface | 3 language test suites, cross-language integration tests | High |
| Deployment | Larger Docker images, GPU runtime dependency for CUDA | Medium |

### 6.2 What the Hybrid Enables

| Capability | Value | When Needed |
|-----------|-------|-------------|
| Institutional derivatives pricing | Enables options/futures strategies | Level 3+ ($100-1K capital) |
| FIX protocol connectivity | Direct institutional forex access (OANDA, IBKR) | Level 3+ |
| GPU Monte Carlo | 100-1000x speedup on path simulation | Level 4 ($1K-10K capital) |
| Cross-asset derivatives | BTC options, ETH perpetuals with Greeks | Level 3+ |

### 6.3 The Critical Question

**Is the complexity worth it at Day1?** No. Absolutely not.

**Is it worth it at Level 3?** Yes, if the trading capital and strategy sophistication demand it.

---

## 7. Verdict: CONDITIONAL APPROVAL

### 7.1 Conditions for Approval

The hybrid Rust + C++ architecture is **approved** subject to the following gating criteria:

#### Gate 1: Day1 and Level 2 — C++ is BANNED

- Python + Rust only, as currently architected
- No QuantLib, no FIX, no CUDA
- All derivatives pricing uses simple Black-Scholes in Python (numpy)
- Forex connectivity uses ccxt REST API
- Monte Carlo uses numpy vectorized operations

**Rationale:** At $10-100 capital, the complexity cost vastly exceeds the capability benefit.

#### Gate 2: Level 3 Readiness — C++ Modules Introduced

**Trigger:** Capital reaches $100+ AND at least 3 active strategies AND forex/gold trading begins.

**What to build:**
1. FIX module (QuickFIX wrapper) — enables institutional forex
2. Pricing module (QuantLib wrapper) — enables derivatives strategies
3. Build system integration (scikit-build-core + CMake)

**What NOT to build yet:**
- CUDA/GPU Monte Carlo (CPU is sufficient at this scale)

#### Gate 3: Level 4 — GPU Acceleration

**Trigger:** Capital reaches $1K+ AND Monte Carlo simulations are a bottleneck (>30 min per backtest).

**What to build:**
1. CUDA Monte Carlo module
2. GPU path generation kernels
3. CPU fallback for non-GPU environments

### 7.2 Architecture Invariants (Must Preserve)

Regardless of C++ additions:

1. **Python is the brain.** All strategy logic, risk management, and orchestration stays in Python.
2. **Rust is the muscle for hot paths.** WebSocket, tick processing, order execution remain in Rust.
3. **C++ is the specialist.** QuantLib, FIX, CUDA — domain-specific capabilities with no viable alternatives.
4. **No direct Rust↔C++ calls.** Python mediates all cross-language communication.
5. **Single `trace_id` across all layers.** Structured logging must work across Python↔Rust↔C++ boundaries.
6. **The harness is inviolable.** Risk management (Python) overrides everything. No C++ module can bypass Risk Guardian.

### 7.3 Recommended Implementation Sequence

```
Phase 1 (NOW): Ship Python + Rust. No C++. Validate the core architecture.
    │
Phase 2 (Level 2): Add Macro Agent, backtesting, strategy evolution. Still no C++.
    │
Phase 3 (Level 3): Introduce C++ FIX module first (highest value, lowest complexity).
    │                  Then QuantLib pricing module.
    │                  Build system: scikit-build-core + Makefile orchestration.
    │
Phase 4 (Level 4): Add CUDA Monte Carlo if profiling shows it's needed.
```

### 7.4 Risk Mitigation

| Risk | Mitigation |
|------|------------|
| C++ module crashes bring down Python process | Run C++ modules in separate process, communicate via gRPC/Redis |
| QuantLib build complexity | Pre-build static libraries in CI, cache aggressively |
| CUDA unavailable in production | CPU fallback is the default; GPU is opt-in |
| Two FFI layers increase bug surface | Comprehensive integration tests at Python↔Rust and Python↔C++ boundaries |
| Developer velocity drops | Gate C++ behind Level 3; don't slow down Day1 delivery |

---

## 8. Final Assessment

| Criterion | Score | Notes |
|-----------|-------|-------|
| Technical soundness | **8/10** | Hybrid is justified; each language has a clear, non-overlapping role |
| Build complexity | **6/10** | Manageable with scikit-build-core, but adds CI/CD overhead |
| Timing appropriateness | **5/10** | Premature for Day1; correct for Level 3+ |
| Ecosystem maturity | **9/10** | QuantLib and QuickFIX are industry standards |
| Risk/reward ratio | **7/10** | High value at scale, but unnecessary complexity early |
| **Overall** | **7/10** | **Conditionally approved with strict gating** |

---

## 9. Directives to Engineering

1. **Do NOT add C++ to the Day1 build.** Ship Python + Rust first.
2. **Do NOT create the `cpp/` directory yet.** Premature code is technical debt.
3. **DO design Python interfaces for future C++ modules now.** Abstract base classes in `src/pricing/`, `src/fix/` with Python-only implementations. Swap to C++ later without changing agent code.
4. **DO add C++ build to the Makefile roadmap** (commented out or in docs).
5. **DO profile before adding CUDA.** If numpy Monte Carlo runs in <5 minutes for 100K paths, GPU is unnecessary.

**The hybrid architecture is the right long-term answer. It's just the wrong time to build it.**

---

*Reviewed by: Chief Architect, TSAR Council*  
*Date: 2026-07-24*  
*Status: CONDITIONAL APPROVAL — Gate behind Level 3 readiness*
