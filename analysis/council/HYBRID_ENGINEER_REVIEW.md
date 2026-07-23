# TSAR Council — Chief Engineer Review

**Reviewer:** Chief Engineer (Build & Implementation)
**Subject:** HYBRID Rust + C++ Architecture Decision
**Date:** 2026-07-24
**Verdict:** CONDITIONAL APPROVAL

---

## Executive Summary

The hybrid architecture is **technically sound but operationally expensive**. Each individual technology choice (Rust for systems, C++ for quant libraries, Python for orchestration) is defensible in isolation. The challenge is in the **seams** — build systems, CI pipelines, debugging workflows, and the cognitive load of maintaining three language ecosystems simultaneously.

The recommendation is to **approve conditionally**: proceed with Rust+Python immediately, and add C++ **incrementally** starting with a single, isolated component (QuantLib pricing models). Do NOT attempt to launch with all three languages fully integrated.

---

## 1. Build System Unification — Cargo + CMake + maturin

### Assessment: TRACTABLE WITH CONSTRAINTS

**maturin** is the right choice as the top-level build orchestrator. It handles Cargo→Python wheel packaging natively. The problem is C++.

**Three viable approaches:**

| Approach | Complexity | Recommended? |
|----------|-----------|-------------|
| **A. maturin + cmake in build.rs** | Medium | ✅ Yes for small C++ surface |
| **B. Separate pybind11 wheel, maturin wheel** | Low build, high integration | No — two wheels to manage |
| **C. scikit-build-core for C++, maturin for Rust** | High | No — two build frontends |

**Recommended: Approach A** — Use Cargo's `build.rs` to invoke CMake for C++ compilation, then link the static `.a` into the Rust binary. maturin packages the final wheel.

```rust
// build.rs — invoke CMake for C++ components
fn main() {
    let dst = cmake::build("cpp/");
    println!("cargo:rustc-link-search=native={}/lib", dst.display());
    println!("cargo:rustc-link-lib=static=tsar_quantlib");
}
```

**Key constraint:** C++ code must be compiled as a **static library** that Rust links against. This avoids shared library hell (`LD_LIBRARY_PATH`, version conflicts, symbol visibility issues).

**Risk:** CMake invoked from `build.rs` breaks cross-compilation and makes CI debugging harder. Mitigate by keeping C++ surface area minimal (see Section 8).

### Build Pipeline

```
pyproject.toml (maturin)
  └─ Cargo.toml
       └─ build.rs
            └─ cmake (C++ static lib)
                 ├── QuantLib (static)
                 └── QuickFIX (static)
```

---

## 2. C++ Crate Design

### Assessment: NO CRATE — USE DIRECT FFI

Rust does **not** need C++ crates. It needs **C-ABI wrappers** around C++ libraries.

**Architecture:**

```
┌─────────────────────────────────────────────┐
│  Rust Binary (maturin wheel)                │
│  ├── tick_processor    (pure Rust)          │
│  ├── websocket_server  (pure Rust)          │
│  ├── execution_engine  (pure Rust)          │
│  └── quant_ffi         (C ABI, links to ↓) │
└──────────┬──────────────────────────────────┘
           │ C FFI (extern "C" functions)
┌──────────▼──────────────────────────────────┐
│  C++ Static Library (built by CMake)        │
│  ├── quantlib_pricer  (QuantLib wrapper)    │
│  ├── fix_session      (QuickFIX wrapper)    │
│  └── cuda_kernels     (optional, cuBLAS)    │
└─────────────────────────────────────────────┘
```

**Do NOT try to use C++ crates in Cargo.** The `cxx` crate is excellent for Rust↔C++ interop but adds a third bridge layer. For the initial scope, plain `extern "C"` FFI is sufficient and simpler.

**Interface design for quant_ffi:**

```c
// quant_ffi.h — C ABI surface
extern "C" {
    typedef struct OptionResult {
        double price;
        double delta;
        double gamma;
        double vega;
        double theta;
    } OptionResult;

    OptionResult price_european_option(
        double spot, double strike, double rate,
        double vol, double time, int is_call
    );

    void* create_yield_curve(const double* dates, const double* rates, size_t n);
    double get_discount(void* curve, double t);
    void destroy_yield_curve(void* curve);
}
```

**Rule:** The C++ layer does computation and returns plain structs. No exceptions cross the FFI boundary. No C++ objects leak into Rust. No `std::shared_ptr` across the boundary.

---

## 3. PyO3 + pybind11 Coexistence

### Assessment: COMPATIBLE BUT AVOID IF POSSIBLE

**The short answer:** They coexist fine as separate Python extension modules (`.so`/`.pyd`). Python loads both, they don't interfere.

**The nuanced answer:** There are three concrete risks:

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **ABI conflicts** (different C++ stdlib linking) | Medium | Link both against same libstdc++; never mix libc++/libstdc++ |
| **Symbol collisions** (QuantLib, Boost symbols) | Medium-High | Link C++ deps statically; use `-fvisibility=hidden` |
| **Two `py::module_init` entry points** | Low | Fine — separate modules, separate `.so` files |

**The real problem is operational, not technical:**

Having **two separate FFI bridges** means:
- Two sets of type conversions to maintain
- Two places where Python types ↔ native types must be manually kept in sync
- Two build pipelines that must produce compatible wheels
- Debugging requires understanding both PyO3 and pybind11 semantics

**Recommendation:** If C++ surface area is small (pricing models, 10-20 functions), **wrap C++ via Rust FFI (extern "C") and expose everything through PyO3 only.** Eliminate pybind11 entirely. This cuts the bridge surface in half.

```
Python ←→ PyO3 ←→ Rust ←→ C FFI ←→ C++
        (one bridge)       (internal)
```

vs.

```
Python ←→ PyO3 ←→ Rust
Python ←→ pybind11 ←→ C++
        (two bridges)
```

**Only use pybind11** if C++ components need to be usable independently (e.g., backtesting in C++ without Rust, or sharing with a quant team that only writes C++). If TSAR is a single system, prefer the single-bridge architecture.

---

## 4. CI/CD for 3 Languages

### Assessment: MODERATE COMPLEXITY — SOLVABLE

**GitHub Actions matrix for 3-language build:**

```yaml
# Simplified — real config needs ~150 lines
strategy:
  matrix:
    os: [ubuntu-22.04, macos-14, windows-2022]
    python: ["3.12"]

steps:
  # Rust toolchain
  - uses: dtolnay/rust-toolchain@stable

  # C++ toolchain + CMake
  - uses: lukka/get-cmake@latest

  # Build C++ static libs
  - run: cmake -B build -DCMAKE_BUILD_TYPE=Release
  - run: cmake --build build

  # Build Rust + Python wheel (maturin)
  - run: pip install maturin
  - run: maturin build --release

  # Test
  - run: pip install target/wheels/*.whl
  - run: pytest tests/
```

**Pain points:**
- **Dependency caching:** QuantLib + Boost compilation takes 10-20 minutes. Cache aggressively.
- **Windows MSVC:** Different compiler, different ABI. Test early.
- **CUDA:** GitHub-hosted runners don't have GPUs. Need self-hosted runners or skip GPU tests in CI.
- **Build matrix explosion:** 3 OS × multiple Python versions × optional CUDA = many jobs.

**Mitigation:** Use `ccache` for C++, `sccache` for Rust, and Docker-based builds for reproducibility. The CI config is ~200 lines, not ~2000. It's work, but it's not a blocker.

---

## 5. Developer Experience — Debugging Across Languages

### Assessment: THIS IS THE BIGGEST RISK

**The honest truth:** Debugging across Python→Rust→C++ is painful. Tools exist, but the workflow is significantly slower than single-language debugging.

**What works:**
- **Rust panics → Python tracebacks:** PyO3 converts panics to Python exceptions. Works well.
- **C++ assertions → SIGABRT → core dump:** Need to read core dumps. Familiar to C++ devs, alien to Python devs.
- **`gdb`/`lldb` multi-language:** Can step through Python→Rust→C++ in a single session. But requires debug symbols in all three layers.

**What hurts:**
- **Type mismatches at FFI boundaries** are the #1 bug source. A `usize` vs `int` mismatch, a struct padding difference, a string encoding mismatch — these crash or corrupt silently.
- **Error handling across boundaries:** Rust uses `Result`, C++ uses exceptions (QuantLib throws heavily), Python uses exceptions. Each boundary needs explicit translation.
- **Build errors:** A C++ template instantiation failure from deep inside QuantLib, triggered by a Cargo build, produces an inscrutable error message.

**Mitigations:**
1. **Extensive FFI boundary tests.** Every `extern "C"` function gets a round-trip test: Rust calls C++, verifies result. Not optional.
2. **`bindgen` / `cbindgen`** for auto-generating FFI headers. Don't hand-write struct layouts.
3. **ASAN/UBSAN in CI** for C++ code. Undefined behavior across FFI is a nightmare.
4. **One developer who knows all three languages** for the first 6 months. After that, team can specialize.

---

## 6. C++ Library Choices

### QuickFIX vs Custom FIX Engine

| Factor | QuickFIX | Custom |
|--------|----------|--------|
| **Maturity** | 20+ years, battle-tested | Zero |
| **FIX 4.4 support** | Complete | Must build |
| **Performance** | Adequate (not HFT-grade) | Can be optimal |
| **Maintenance burden** | Low (community) | High |
| **C++ dependency weight** | Boost, STL | Minimal |

**Verdict: Use QuickFIX.** The FIX protocol is complex enough that a custom engine is a multi-year project. QuickFIX handles session management, message parsing, resend requests, and sequence numbers. For an HFT system targeting <1μs latency, you'd eventually replace it. For initial launch, QuickFIX is correct.

**Caveat:** QuickFIX is C++ with Boost dependencies. It will increase build times and wheel size. Accept this.

### QuantLib-Python vs Native QuantLib

| Factor | QuantLib-Python (SWIG) | Native QuantLib via FFI |
|--------|----------------------|------------------------|
| **Integration effort** | Minimal (`pip install QuantLib`) | Significant (CMake build, FFI wrappers) |
| **Performance** | Same (C++ under the hood) | Same |
| **Debuggability** | SWIG layer obscures errors | Direct stack traces |
| **Customization** | Can't modify C++ side | Full control |
| **Maintenance** | SWIG bindings lag releases | You maintain wrappers |

**Verdict: Use QuantLib-Python for prototyping, native QuantLib for production.**

In practice: start with `pip install QuantLib-SWIG` for rapid development. Write the pricing logic in Python. Once validated, write C++ wrappers for the hot path and replace via FFI. This is the **incremental approach** (Section 8).

---

## 7. Realistic Timeline

### For a solo developer or very small team (2-3 engineers):

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| **Phase 1: Rust+Python core** | 3-4 months | WebSocket server, tick processing, order execution, basic strategy engine |
| **Phase 2: FIX connectivity** | 1-2 months | QuickFIX integration, order routing to exchange |
| **Phase 3: QuantLib pricing** | 2-3 months | Options pricing, yield curves, Greeks calculation |
| **Phase 4: CUDA (if needed)** | 2-3 months | GPU-accelerated risk/pricing (only if CPU is bottleneck) |
| **Phase 5: Hardening** | 2-3 months | CI/CD, load testing, failover, monitoring |

**Total: 10-15 months to production-ready hybrid system.**

**Phase 1 alone (Rust+Python) is 3-4 months and delivers a functional trading system.** C++ adds 4-8 months on top.

### For a funded startup team (5-8 engineers, mixed skills):

| Phase | Duration |
|-------|----------|
| Phase 1-2 (Rust+Python+FIX) | 3-4 months |
| Phase 3 (QuantLib) | 1-2 months |
| Phase 4-5 (CUDA+Hardening) | 2-3 months |

**Total: 6-9 months.**

---

## 8. Incremental C++ Integration — Recommended Order

**DO NOT build the full hybrid from day one.** Add C++ components incrementally, in this order:

### Step 1: QuantLib Pricing Models (Month 4-6)
**Why first:** Most isolated. Pricing is a pure function (inputs → price). Easy to test, easy to swap. Use QuantLib-Python initially, then write C++ wrappers for hot-path models.

```
Python strategy → calls pricing function → QuantLib-Python → returns price
                                                                    ↓
                                              (later: replace with C++ FFI)
```

### Step 2: FIX Engine (Month 5-7)
**Why second:** QuickFIX is self-contained. It handles one thing (FIX sessions). The interface is well-defined (send/receive messages). Can be wrapped as a standalone service or as a Rust FFI module.

### Step 3: CUDA Kernels (Month 8+)
**Why last:** Only needed if you have measurable CPU bottlenecks in pricing or risk. Most trading systems don't need GPU for pricing unless doing massive Monte Carlo or real-time portfolio-wide risk. **This may never be needed.** Don't build it until profiling proves it's necessary.

### Decision gate at each step:

After each C++ integration, ask: **"Did this justify the complexity cost?"** If QuantLib-Python is fast enough (and for most strategies, it is), don't bother with native QuantLib FFI. The hybrid architecture should be a tool, not a religion.

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| FFI bugs cause production crashes | High | Critical | Extensive boundary testing, ASAN in CI |
| Build system breaks on OS update | Medium | High | Docker-based builds, pin toolchain versions |
| QuantLib upgrade breaks C++ wrappers | Medium | Medium | Pin QuantLib version, test on upgrade |
| Developer turnover (need 3-language expertise) | Medium | High | Document FFI boundaries, keep C++ surface small |
| CI build times exceed 30 minutes | Medium | Low | ccache, incremental builds, separate C++ lib builds |
| CUDA adds complexity with no measurable benefit | Medium | Medium | Profile first, defer indefinitely if CPU is sufficient |

---

## Verdict: CONDITIONAL APPROVAL

### Conditions:

1. **Start with Rust + Python only.** No C++ in Phase 1. Deliver a working system first.
2. **Use QuantLib-Python** (SWIG bindings) for initial pricing. Do NOT build native QuantLib FFI until profiling shows it's necessary.
3. **If/when adding C++, use the single-bridge architecture** (C++ → C FFI → Rust → PyO3 → Python). Avoid pybind11 unless there's a compelling reason.
4. **Defer CUDA indefinitely** until you have real workloads proving CPU is the bottleneck.
5. **Budget 2x the timeline** you think you need for C++ integration. It always takes longer than expected.
6. **One engineer must own the FFI boundary layer** — someone who understands all three languages and can debug across them.

### The uncomfortable truth:

The hybrid architecture is **correct for the problem domain** (quant trading needs both systems performance and quant library access). But it **triples your operational surface area**. Every dependency update, every CI failure, every debugging session is 3x harder.

The winning strategy is to **earn the right to use C++** by first proving the Rust+Python system works, then surgically adding C++ only where it provides measurable value.

**Build the monolith first. Make it fast. Then — and only then — add the complexity that the performance data justifies.**

---

*— Chief Engineer, TSAR Council*
