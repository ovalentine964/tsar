# TSAR COUNCIL — HYBRID ARCHITECTURE RISK REVIEW

**Reviewer:** Chief Risk Officer (CRO)
**Date:** 2026-07-24
**Subject:** Proposed Hybrid Architecture — Python 3.12 + Rust (Execution Layer) + C++ (QuantLib, FIX, CUDA)
**Classification:** CRITICAL — Architecture Decision

---

## EXECUTIVE SUMMARY

The proposed hybrid architecture introduces **three language runtimes** into the critical path of a money-handling system. While each technology choice is individually defensible, the **composition risk** — the danger that arises from their interaction — is the primary concern. This review evaluates seven risk domains and renders a **CONDITIONAL APPROVAL** with specific, binding preconditions.

**Verdict: CONDITIONAL APPROVAL** — see Section 9 for mandatory conditions.

---

## 1. C++ MEMORY SAFETY RISKS

### Risk Level: 🔴 HIGH

C++ in a money-handling system is the single largest source of catastrophic failure risk.

**Specific Threats:**
- **Segfaults in the execution path** — A null dereference or use-after-free in the order routing code can crash the entire process mid-trade, leaving orders in an indeterminate state (sent but unconfirmed, or partially filled with no tracking).
- **Buffer overflows in FIX parsing** — FIX messages are length-delimited tag=value strings. A malformed message from an exchange or a malicious crafted message can trigger a buffer overflow in a C++ FIX engine (e.g., QuickFIX). This is not theoretical; CVEs exist for FIX parsers.
- **Data races in multi-threaded execution** — C++ offers no compile-time protection against data races. A race condition in the order book or position tracker can silently corrupt state — worse than a crash, because the system continues operating on wrong data.
- **Undefined behavior (UB)** — Integer overflow on position/P&L calculations, signed/unsigned mismatches on order quantities, or dangling references in callback chains can produce arbitrarily wrong results with no runtime signal.

**Mitigating Factors:**
- ASAN (AddressSanitizer), MSAN, TSAN, and UBSAN are mature and should be mandatory in CI.
- Modern C++ (C++20/23) offers `std::span`, `std::expected`, and RAII patterns that reduce — but do not eliminate — these risks.
- Databento and other firms successfully run C++ in production trading systems, proving it is viable with discipline.

**Residual Risk:** Even with sanitizers and modern idioms, C++ memory safety is a **human discipline problem**, not a tooling problem. One mistake by one developer in one code review can introduce a vulnerability that survives testing and detonates in production under load.

### CRO Recommendation
All C++ code in the execution path MUST pass ASAN+TSAN+UBSAN in CI with zero findings. No exceptions. Unsafe patterns (raw `new`/`delete`, C-style casts, `reinterpret_cast`) must be banned by `clang-tidy` rules enforced in CI.

---

## 2. DETERMINISTIC RISK CHECKS ACROSS RUST + C++ + PYTHON

### Risk Level: 🟡 MEDIUM-HIGH

**The Core Problem:** Risk checks must be **deterministic and consistent** — the same input must always produce the same risk decision, regardless of which language executes it. With three runtimes, this is hard.

**Specific Concerns:**

| Concern | Impact |
|---------|--------|
| **Floating-point non-determinism** | Rust and C++ may use different FP rounding modes, FMA instructions, or compiler optimizations. The same Black-Scholes price computed in Rust and C++ may differ in the last 2-3 ULPs. Over thousands of calculations, this drifts. |
| **Python GIL as serialization bottleneck** | If risk checks pass through Python, the GIL serializes execution. Under load, this creates a latency spike that could cause risk checks to be skipped or delayed past the execution window. |
| **FFI boundary data marshaling** | Passing complex structs (option Greeks, portfolio positions) across Rust↔C++ FFI requires careful memory layout agreement. A mismatched struct alignment silently corrupts data. |
| **Exception/error propagation** | C++ exceptions cannot cross the FFI boundary into Rust. Errors must be translated to error codes. A missed translation = silent failure. |

**Mitigation:**
- Define **canonical data types** in a shared header/interface file. Both Rust and C++ must agree on struct layout, alignment, and endianness.
- Use **fixed-point arithmetic** for all monetary values and risk quantities — eliminates FP non-determinism entirely.
- Risk checks that are latency-critical must be implemented **in Rust only** (the execution layer), not delegated to Python.
- Implement **cross-language property-based testing**: generate random inputs, run through both Rust and C++ code paths, assert identical outputs.

### CRO Recommendation
The architecture MUST define a single source of truth for risk check logic. If a risk check exists in Rust, it must NOT also exist in C++ with a potential divergence. Create a **Risk Decision Matrix** documenting which language owns each check.

---

## 3. FIX PROTOCOL RISKS — MID-ORDER CONNECTION DROP

### Risk Level: 🔴 HIGH

This is a **money-losing scenario** that must be designed for, not hoped against.

**What Happens When FIX Drops Mid-Order:**

1. **Order sent, no ExecutionReport received** — The system does not know if the order reached the exchange matching engine. Possible outcomes:
   - Order was received and is live → **phantom position** if the system doesn't track it
   - Order was rejected → no problem, but the system doesn't know
   - Order was received and partially filled → **orphaned fills** arriving on reconnect

2. **Sequence number gap on reconnect** — FIX uses sequence numbers. On reconnect, if the initiator and acceptor disagree on the next sequence number, the session enters **resend request** mode. During this window, no new orders can be sent.

3. **Duplicate order risk** — If the system retransmits the order on reconnect without checking if it was already acknowledged, the exchange may reject it (best case) or accept it as a new order (worst case — **double execution**).

**FIX Protocol Built-in Mitigations:**
- Heartbeat monitoring (default 30s) detects dead connections
- `ResendRequest` (MsgType=2) allows recovery of missed messages
- `SequenceReset` (MsgType=4) handles gap fills
- `TestRequest` (MsgType=1) probes liveness
- QuickFIX stores messages in a MessageStore (file/DB) for replay

**What FIX Does NOT Solve:**
- It does not tell you the state of an order that was in-flight when the connection died
- It does not prevent duplicate orders — that's an application-level concern
- Resend recovery can take seconds — during which you cannot send new orders

**Required Architecture:**
```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│ Order Manager│───>│ FIX Engine   │───>│  Exchange   │
│ (Rust)       │<───│ (C++)        │<───│             │
└─────────────┘    └──────────────┘    └─────────────┘
       │
       ▼
┌─────────────┐
│ Pending Order│  ← All sent-but-unacked orders
│   Database   │     persisted BEFORE sending
└─────────────┘
```

**Non-Negotiable Requirements:**
- **Pre-send persistence**: Every order MUST be written to a durable store BEFORE the FIX `NewOrderSingle` is sent.
- **Execution reconciliation**: On reconnect, the system MUST query the exchange for the state of all pending orders (via `OrderStatusRequest` or exchange-specific API).
- **Idempotency**: Order submissions must carry a unique `ClOrdID` that the system checks before retransmitting.
- **Kill switch**: If FIX connectivity is lost for >N seconds, ALL trading must halt automatically.

### CRO Recommendation
FIX connection management in C++ is a **known risk amplifier**. The CRO requires a dedicated **FIX Recovery Test Suite** that simulates:
- Connection drop mid-send
- Partial fill followed by disconnect
- Sequence number reset with pending orders
- Reconnect with stale sequence numbers
All tests must run in CI before any deployment.

---

## 4. QUANTLIB RISKS — MODEL VALIDATION & BLACK SWAN HANDLING

### Risk Level: 🟡 MEDIUM

**QuantLib is a library, not a risk management system.** It provides implementations of financial models. It does NOT validate whether those models are appropriate for your use case.

**Specific Risks:**

- **Model risk**: QuantLib implements Black-Scholes, Heston, SABR, and dozens of other models. All of these assume **continuous markets** and **known distributions**. During a black swan event (flash crash, liquidity vacuum, market halt), these models produce **garbage outputs** — not because QuantLib is broken, but because the models themselves are invalid in extreme regimes.

- **Tail risk underestimation**: Standard models used in QuantLib (log-normal, even some jump-diffusion models) systematically underestimate the probability of 5σ+ events. The 2008 crisis, the 2010 Flash Crash, and the 2020 COVID crash all involved moves that were "impossible" under standard models.

- **Numerical stability**: QuantLib uses numerical methods (finite differences, Monte Carlo, FFT) that can produce NaN/Inf for extreme inputs (very high vol, very short expiry, very deep OTM). If these propagate into the execution path without checking, orders can be sent with nonsensical prices.

- **Version pinning**: QuantLib releases occasionally fix bugs that change pricing outputs. An untested upgrade can silently change all your risk calculations.

**Mitigations:**
- **Implement explicit model bounds**: If implied vol > 500% or option price < 0 or Greeks contain NaN, HALT and alert.
- **Stress testing**: Run all models against historical crisis scenarios (1987, 2008, 2010, 2020) and verify outputs are bounded.
- **Circuit breakers**: Position-level and portfolio-level loss limits that are **independent of model output**. If P&L exceeds threshold, kill positions regardless of what the model says.
- **Pin QuantLib version** and run regression tests against known reference outputs.

### CRO Recommendation
QuantLib must be treated as a **numerical computation engine**, not an oracle. Every output must be bounds-checked before use. The CRO requires a **Model Validation Document** proving that each model used has been tested against extreme scenarios and that outputs are bounded.

---

## 5. GPU/CUDA RISKS — SILENT COMPUTATION FAILURE

### Risk Level: 🔴 HIGH

GPU computation failure is the most insidious risk in this architecture because **it can fail silently**.

**Specific Threats:**

- **Silent Data Corruption (SDC)**: Research published by IEEE (2026) confirms that GPUs can produce incorrect results without raising errors. This is especially common in consumer/prosumer GPUs without ECC memory. A cosmic ray bit flip in a GPU register can change a risk calculation result by orders of magnitude — and the CUDA kernel returns "success."

- **CUDA kernel launch failures**: `cudaGetLastError()` only catches the LAST error. If a kernel launch fails but the code doesn't check after every launch, subsequent kernels may succeed using corrupted state from the failed one.

- **GPU memory exhaustion**: Under heavy load (many concurrent portfolio valuations), GPU memory can be exhausted. `cudaMalloc` returns `cudaErrorMemoryAllocation`, but if unchecked, subsequent kernel launches operate on null pointers — producing zeros or garbage.

- **Driver bugs**: NVIDIA driver updates can introduce subtle numerical changes. A driver update that changes the order of floating-point operations in a reduction kernel can change portfolio VaR calculations.

- **Thermal throttling**: Under sustained load, GPUs throttle. A kernel that normally takes 1ms may suddenly take 10ms. If the system has a timeout, it may cancel the computation and use stale results.

**Architecture Implication:**
If CUDA is used for risk calculations (VaR, Monte Carlo, portfolio Greeks), a silent failure means the system makes trading decisions based on **wrong risk numbers**. This is existential.

**Mitigations:**
- **ECC memory mandatory** — No trading system should run on GPUs without ECC.
- **Checksum validation**: After every critical GPU computation, compute a lightweight checksum (e.g., sum of outputs) and compare against a CPU-side sanity check.
- **Result bounds checking**: Every GPU output must be checked for NaN, Inf, and range violations before use.
- **CUDA error checking macro**: Every CUDA call MUST go through an error-checking macro. No exceptions.
- **CPU fallback**: If GPU computation fails OR produces suspect results, fall back to CPU computation. Slower but correct.

### CRO Recommendation
GPU computation MUST NOT be the sole path for any critical risk calculation. Every GPU result must have a CPU-side validation or bounds check. The CRO requires a **GPU Reliability Test** that runs daily: inject known inputs, verify outputs match reference values within tolerance.

---

## 6. TESTING STRATEGY FOR MULTI-LANGUAGE SYSTEM

### Risk Level: 🟡 MEDIUM

Testing a three-language system is significantly harder than testing a monolingual one. Each boundary is a potential source of bugs that only emerge in integration.

**Required Testing Layers:**

### Layer 1: Unit Tests (Per Language)
| Language | Framework | Coverage Target |
|----------|-----------|----------------|
| Rust | `cargo test` + `proptest` | 90%+ line coverage |
| C++ | Google Test + ASAN/TSAN/UBSAN | 85%+ line coverage |
| Python | pytest + hypothesis | 90%+ line coverage |

### Layer 2: FFI Boundary Tests
- **Rust↔C++**: Test every FFI function with:
  - Valid inputs (expected behavior)
  - Null pointers (must return error, not crash)
  - Out-of-range values (must return error, not UB)
  - Concurrent calls (must not race)
- **Python↔Rust**: Test PyO3/maturin bindings with the same categories
- **Python↔C++**: Test pybind11/cffi bindings with the same categories

### Layer 3: Integration Tests
- End-to-end order flow: Python signal → Rust risk check → C++ FIX send → mock exchange response → C++ FIX receive → Rust position update → Python P&L
- Kill the FIX connection mid-order and verify recovery
- Inject NaN/Inf at each boundary and verify it's caught
- Run under ASAN+TSAN for the C++ components

### Layer 4: Chaos Testing
- Randomly crash the C++ process and verify the system recovers
- Introduce network latency/jitter on the FIX connection
- Exhaust GPU memory and verify CPU fallback
- Corrupt a FIX message and verify the parser rejects it

### Layer 5: Production Monitoring
- **Cross-language correlation IDs**: Every order must carry a UUID that appears in Rust, C++, and Python logs
- **Latency histograms per boundary**: Track P50/P99/P999 latency at each FFI crossing
- **Error rate dashboards**: Monitor error rates from each language component independently

### CRO Recommendation
The testing strategy must include a dedicated **FFI Integration Test Suite** that runs in CI on every commit. The chaos testing layer must run weekly in a staging environment that mirrors production.

---

## 7. WORST-CASE SCENARIO: C++ CRASH IN THE EXECUTION PATH

### Risk Level: 🔴 CRITICAL

**Scenario:** The C++ FIX engine process crashes (segfault, OOM, unhandled exception) while orders are in flight.

**Cascade of Failures:**

```
T+0ms    C++ FIX engine crashes (segfault in FIX parser)
T+0ms    All in-flight orders: UNKNOWN STATE
T+0ms    All pending ExecutionReports: LOST
T+1ms    Rust execution layer detects connection loss (heartbeat timeout)
T+1ms    Rust layer CANNOT send new orders (FIX engine is down)
T+1ms    Rust layer DOES NOT KNOW the state of pending orders
T+100ms  System restarts C++ process (supervisor)
T+200ms  FIX session reconnects with new sequence numbers
T+200ms  Exchange may reject reconnect (sequence number mismatch)
T+500ms  ResendRequest sent, awaiting response
T+500ms  During this window: NO NEW ORDERS CAN BE SENT
T+1000ms Exchange responds with missed messages
T+1000ms System must reconcile: which orders filled? which rejected? which still live?
T+1500ms Reconciliation complete (optimistic)
T+1500ms Trading resumes
```

**Total downtime: ~1.5 seconds** (optimistic). During this window:
- Market can move significantly
- Existing positions are unhedged
- Stop losses are not being monitored
- If the crash happened during a volatile event, losses can be catastrophic

**Worse Scenario:** The crash corrupts the FIX engine's message store. On restart, the engine replays corrupted messages, sending duplicate orders or orders with wrong parameters.

**Even Worse Scenario:** The crash is not a clean segfault but a **hang** — the C++ process is alive but not responding (deadlock, infinite loop). The Rust layer may not detect this for 30+ seconds (heartbeat interval). During this time, the system believes it's connected but no orders are actually being sent.

### Required Mitigations:

1. **Supervisor process**: A separate watchdog process (not Rust, not C++) that monitors the FIX engine. If it crashes, restart it. If it hangs (no heartbeat response), kill and restart it.

2. **Pending order database**: All orders in flight MUST be tracked in a persistent store (SQLite or Redis with AOF). On crash recovery, the system MUST reconcile against the exchange before resuming.

3. **Automatic trading halt**: If the FIX engine crashes, ALL trading MUST halt immediately. No "graceful degradation" — stop everything, reconcile, then resume.

4. **Position snapshot**: Before restarting, take a snapshot of all positions. After restart, verify positions match. If they don't, halt and alert.

5. **Kill switch**: An external, language-independent kill switch (e.g., a Redis key or a file on disk) that any component can set to halt all trading. This must be independent of all three language runtimes.

### CRO Recommendation
A C++ crash in the execution path is the **single most dangerous failure mode** in this architecture. The CRO requires:
- A documented **Crash Recovery Runbook** tested quarterly
- **Automated crash recovery tests** in CI (inject SIGSEGV into the C++ process, verify system recovers correctly)
- **Maximum recovery time SLA**: System must recover and reconcile within 5 seconds of a crash
- If the SLA cannot be met, the CRO will recommend migrating FIX to Rust (e.g., `ferrumfix` crate)

---

## 8. RISK SUMMARY MATRIX

| Risk Domain | Severity | Likelihood | Risk Level | Mitigation Status |
|-------------|----------|------------|------------|-------------------|
| C++ memory safety | Critical | Medium | 🔴 HIGH | Requires mandatory sanitizers |
| Cross-language determinism | High | Medium | 🟡 MED-HIGH | Requires fixed-point arithmetic |
| FIX mid-order disconnect | Critical | Medium | 🔴 HIGH | Requires pre-send persistence |
| QuantLib model validity | High | Low | 🟡 MED | Requires bounds checking |
| GPU silent failure | Critical | Low-Med | 🔴 HIGH | Requires ECC + checksums |
| Multi-language testing gaps | Medium | High | 🟡 MED | Requires FFI test suite |
| C++ crash in execution path | Critical | Low | 🔴 CRITICAL | Requires crash recovery runbook |

---

## 9. VERDICT

# CONDITIONAL APPROVAL

The CRO does NOT reject this architecture. The hybrid Rust + C++ approach is used in production by firms like Databento and is architecturally sound. However, the **conditions below are binding** — the architecture must not proceed to production without meeting all of them.

### Mandatory Conditions (Must be met before production)

| # | Condition | Owner | Deadline |
|---|-----------|-------|----------|
| 1 | All C++ code in the execution path passes ASAN+TSAN+UBSAN with zero findings in CI | C++ Lead | Pre-production |
| 2 | Pre-send order persistence implemented and tested (no order sent without durable write) | Rust Lead | Pre-production |
| 3 | FIX Crash Recovery Runbook documented and tested | SRE | Pre-production |
| 4 | Cross-language property-based tests for all FFI boundaries | QA Lead | Pre-production |
| 5 | GPU ECC memory requirement documented and enforced in infrastructure | Infra Lead | Pre-production |
| 6 | GPU result checksum validation implemented for all critical computations | Quant Lead | Pre-production |
| 7 | Automatic trading halt on FIX disconnection (kill switch) implemented | Rust Lead | Pre-production |
| 8 | QuantLib outputs bounds-checked for NaN/Inf/range before use | Quant Lead | Pre-production |
| 9 | Fixed-point arithmetic for all monetary values across all three languages | Architecture | Pre-production |
| 10 | Cross-language correlation IDs in all log messages | SRE | Pre-production |

### Recommended Conditions (Should be met within 90 days of production)

| # | Condition | Owner | Deadline |
|---|-----------|-------|----------|
| 11 | Chaos testing suite (random C++ crash, network jitter, GPU exhaustion) running weekly | QA Lead | Production + 90d |
| 12 | Evaluate `ferrumfix` (Rust FIX engine) as potential C++ FIX replacement | Architecture | Production + 90d |
| 13 | Model Validation Document for all QuantLib models used | Quant Lead | Production + 90d |
| 14 | Latency histograms at every FFI boundary in production monitoring | SRE | Production + 90d |

---

## 10. CLOSING NOTE

The founder's choice of a hybrid architecture is **strategically reasonable** — Rust provides memory safety for the critical execution path, C++ provides access to battle-tested libraries (QuantLib, QuickFIX) and GPU computing, and Python provides rapid strategy development. The risk is not in the individual choices but in the **composition**.

The ten mandatory conditions above transform this from a risky architecture into a **defensible** one. They are not optional suggestions — they are the minimum bar for operating a money-handling system with three language runtimes in the critical path.

The CRO will re-review after conditions 1-10 are met and will escalate to the founder if any condition is waived without alternative mitigation.

---

*Signed: Chief Risk Officer, TSAR Council*
*Date: 2026-07-24*
*Next Review: Upon completion of conditions 1-10*
