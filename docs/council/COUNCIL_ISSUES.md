# TSAR Council of 5 — Consolidated Issue List

**Compiled by:** Chief Fixer  
**Date:** 2026-07-24  
**Sources:** Chief Architect, Chief Risk Officer, Chief Strategist, Chief Engineer reviews  
**Canonical Reference:** ARCHITECTURE_CONSOLIDATION.md, DAY1_ARCHITECTURE.md  

---

## Summary

| Severity | Count |
|----------|-------|
| **CRITICAL** | 8 |
| **HIGH** | 18 |
| **MEDIUM** | 21 |
| **LOW** | 8 |
| **TOTAL** | **55** |

| Fix Category | Count |
|--------------|-------|
| FIX_A: Parameter reconciliation | 14 |
| FIX_B: Day30 architecture spec | 5 |
| FIX_C: Day1 scope adjustment | 12 |
| FIX_D: Risk hardening | 12 |
| FIX_E: Strategy updates | 7 |
| FIX_F: Dependency cleanup | 5 |

---

## CRITICAL Issues (8)

### C1 — Cross-Document Risk Parameter Inconsistency
- **Source:** Chief Risk Officer (Critical #1), Chief Architect (§7.2 #5)
- **Description:** Risk parameters differ across RISK_ARCHITECTURE.md, TSAR_ARCHITECTURE.md, and trading-super-agent-spec.md. Daily loss kill: -4% vs -2%. Max drawdown: -20% vs -5%. Max positions: 20 vs 10. Kelly: half vs quarter. Min R:R: 1.5:1 vs 2:1.
- **Impact:** Implementation team could build to wrong thresholds. At $10K leverage, -2% vs -4% = $200 difference before intervention.
- **Fix:** **FIX_A** — Reconcile ALL parameters to canonical values in ARCHITECTURE_CONSOLIDATION.md §1.3. Update RISK_ARCHITECTURE.md and all other docs.
- **Canonical Values:** Daily loss -2%, max DD 5%, max positions 10, max position 15%, Kelly 0.25, min R:R 2:1.

### C2 — Circuit Breaker Threshold Conflicts
- **Source:** Chief Risk Officer (Critical #3)
- **Description:** YELLOW/ORANGE/RED thresholds differ between RISK_ARCHITECTURE.md and TSAR_ARCHITECTURE.md. RISK_ARCHITECTURE says RED at -4% daily; canonical says -2%.
- **Impact:** Same as C1 — wrong kill switch trigger level.
- **Fix:** **FIX_A** — Update RISK_ARCHITECTURE.md circuit breaker table to match ARCHITECTURE_CONSOLIDATION.md canonical values.

### C3 — Redis Single Point of Failure for Risk Engine
- **Source:** Chief Risk Officer (Critical #2), Chief Architect (§6.2)
- **Description:** Entire risk engine depends on Redis. If Redis dies: kill switch flag unreadable, Risk Governor can't evaluate, position state lost. Worst case: system "fail-open" could execute trades without risk checks.
- **Impact:** Unlimited loss exposure during Redis outage if fail-open behavior.
- **Fix:** **FIX_D** — Add dead man's switch: Risk Governor writes heartbeat every 5s; if monitor doesn't see heartbeat for 15s, activate kill switch. Enforce "fail-closed" (VETO on state read failure) across ALL risk check paths.

### C4 — Kill Switch Monitor Has No Watchdog
- **Source:** Chief Risk Officer (High #1), Chief Architect (§6.5)
- **Description:** The `AutoKillDetector` runs as a separate process checking every 5s. Nothing monitors it. If it crashes, no automatic kill switch on drawdown breach, exchange connectivity loss, or data feed staleness.
- **Impact:** System has no safety net if monitor process crashes.
- **Fix:** **FIX_D** — Add watchdog process that monitors the kill switch monitor. If monitor doesn't check in every 10s, watchdog activates kill switch directly via Redis. Implement "dead man's switch" pattern.

### C5 — Day1 Architecture Gap (No Codebase Exists)
- **Source:** Chief Architect (§5.2, §7.2 #1), Chief Engineer (§1)
- **Description:** The architecture is comprehensive documentation (~500KB+) but no code exists. Full architecture (131+ files, 10 agents, 8 Rust crates) is unrealistic for a solo developer.
- **Fix:** **FIX_C** — Day1 architecture (20 files, 3 agents, 0 Rust) is the only build target for first 4 weeks. Full architecture docs should be marked "FUTURE — DO NOT IMPLEMENT YET."

### C6 — Day1 Scope Over-Engineering
- **Source:** Chief Engineer (§1, §3, §4), Chief Strategist (§9 #1-4)
- **Description:** Day1 spec includes: 10 agents (should be 3), Rust execution engine (unnecessary), 35+ dependencies (should be ~18), Prometheus+Grafana (overkill), compliance layer (unnecessary), 15+ DB tables (should be 5).
- **Fix:** **FIX_C** — Reduce Day1 to: 3 agents (Signal Scout, Risk Guardian, Execution Sniper), pure Python, ~20 files, ~18 dependencies, 5 DB tables, Telegram-only monitoring.

### C7 — LLM Provider Integration Still a Proposal
- **Source:** Chief Architect (§4.4)
- **Description:** BaseLLMProvider abstract class exists only in ARCHITECTURE_FIXES.md, not integrated into canonical architecture. Provider implementations, config-driven routing, and cost tracking are proposals, not specs.
- **Fix:** **FIX_C** (Day1) + **FIX_A** (full). Day1: use simple 100-line LLM router with Ollama + DeepSeek NIM. Level 2+: integrate full BaseLLMProvider abstraction into canonical architecture.

### C8 — FIX_01 and FIX_02 Have Overlapping Type Definitions
- **Source:** Chief Engineer (§9)
- **Description:** FIX_01 defines `ModelRegistry`, `ModelRouter`, `ModelSpec`. FIX_02 defines `ModelsConfig`, `ModelRouter` (different class), `ModelInstance`. Two `ModelRouter` classes with different interfaces.
- **Fix:** **FIX_A** — Reconcile into single `ModelRouter` class before implementation. Merge overlapping types.

---

## HIGH Issues (18)

### H1 — Rust↔Python Interface Contract Underspecified
- **Source:** Chief Architect (§1.4 #2, §4.7)
- **Description:** PyO3 bridge described conceptually (~1μs latency) but actual function signatures, error handling protocol, and GIL management strategy are not defined.
- **Fix:** **FIX_C** — Remove Rust from Day1 entirely (pure Python). Specify PyO3 interface contract at Level 2+ when Rust is actually needed.

### H2 — Kelly Fraction Inconsistency (Half vs Quarter)
- **Source:** Chief Risk Officer (High #2)
- **Description:** RISK_ARCHITECTURE.md says `kelly/2` (dynamic Half-Kelly). TSAR_ARCHITECTURE.md says "0.25 Kelly fraction" which is Quarter-Kelly if full Kelly = 0.5. These are different approaches.
- **Fix:** **FIX_A** — Canonical: dynamic `kelly_result / 2.0` with hard cap at 2% (from RISK_ARCHITECTURE.md implementation). Update TSAR_ARCHITECTURE.md to clarify.

### H3 — Recovery Protocol Lacks Regime/Performance Validation
- **Source:** Chief Risk Officer (High #3)
- **Description:** After drawdown, system resumes at reduced sizing after cooldown but doesn't check if market conditions changed or if system is profitable during reduced period.
- **Fix:** **FIX_D** — Add regime-aware recovery gates: (1) check if regime changed, (2) require positive P&L during reduced-sizing period, (3) gradual ramp-up (5%→10%→25%→50%→100%).

### H4 — No Negative Balance Protection for Leveraged Products
- **Source:** Chief Risk Officer (High #4)
- **Description:** With leveraged futures, stop-losses can gap. 20 positions × 2% risk × 1.5 gap factor = 60% portfolio loss. No explicit max loss calculation exists.
- **Fix:** **FIX_D** — Add `max_loss = min(portfolio_value, sum(position_risk_with_gap))`. For leveraged products, add "maximum acceptable loss" parameter that triggers kill switch BEFORE exchange auto-liquidation.

### H5 — No Stress Testing Specification for Day1
- **Source:** Chief Risk Officer (High #5, Medium #5)
- **Description:** Stress testing deferred to Level 2+. Day1 should have minimum: backtest risk engine against historical crashes (March 2020, May 2021, FTX collapse), max historical drawdown calculation, "break the system" test.
- **Fix:** **FIX_D** — Add Day1 stress test spec: (1) historical crash backtest, (2) max drawdown calculation, (3) kill switch verification test.

### H6 — DATA_ARCHITECTURE.md Still References 4 Separate Databases
- **Source:** Chief Architect (§1.3, §1.4 #1)
- **Description:** Canonical is 1 unified `tsar.db` (per ARCHITECTURE_CONSOLIDATION.md §2.3). DATA_ARCHITECTURE.md §15 Implementation Roadmap still references `trades.db`, `strategies.db`, `patterns.db`, `lessons.db`.
- **Fix:** **FIX_A** — Update DATA_ARCHITECTURE.md to reference single `tsar.db` with table prefixes throughout.

### H7 — Momentum Strategy Should Be Day1 (Not Just Mean Reversion)
- **Source:** Chief Strategist (§1)
- **Description:** Mean reversion alone is insufficient for BTC (momentum-driven asset). Momentum strategy already specified in STRATEGY_LAYER.md §8.3. Two strategies from Day1 provides immediate diversification and regime data.
- **Fix:** **FIX_E** — Add Momentum strategy to Day1 alongside Mean Reversion. Minimal implementation effort since code exists in docs.

### H8 — Funding Rate Should Be Day1 Signal
- **Source:** Chief Strategist (§2)
- **Description:** Funding rate is free (Binance API), real-time, and one of the most predictive crypto-specific signals. When funding is extremely positive (>0.05%/8h), crowded long = contrarian short signal.
- **Fix:** **FIX_E** — Add funding rate as Day1 signal source. 5-line API call via ccxt.

### H9 — Genetic Programming Should Be Replaced
- **Source:** Chief Strategist (§6)
- **Description:** Genetic programming for strategy mutation is unrealistic for solo developer: thousands of backtests needed, overfitting risk, implementation complexity, no edge over simple parameter grid search.
- **Fix:** **FIX_E** — Replace genetic programming with LLM-guided parameter optimization + grid search + walk-forward validation. Walk-forward mandatory for ALL strategy changes from Day1.

### H10 — Improvement Baseline 30 Trades Is Too Small
- **Source:** Chief Strategist (§8)
- **Description:** 30 trades is not statistically significant for trading metrics. Random noise dominates any signal at this sample size.
- **Fix:** **FIX_E** — Change improvement baseline from 30 to 100 trades in FIX_04.

### H11 — No Alpha Attribution Metric
- **Source:** Chief Strategist (§8)
- **Description:** 10 metrics measure what is happening but not why. No metric answers: "Is improvement from learning loop or favorable market conditions?"
- **Fix:** **FIX_E** — Add metric 11: `alpha_vs_baseline_strategy`. Maintain frozen Day1 strategy, compare evolved version against it.

### H12 — TA-Lib vs pandas-ta Conflict
- **Source:** Chief Engineer (§2)
- **Description:** Both TA-Lib and pandas-ta listed in requirements. TA-Lib requires system-level C library (`libta-lib0-dev`) — common build-breaker, especially on Windows. pandas-ta is pure Python.
- **Fix:** **FIX_F** — Pick one. Recommendation: pandas-ta for Day1 (zero build friction), TA-Lib for production if performance needed. Remove the other from requirements.

### H13 — Celery Should Be Removed from Day1
- **Source:** Chief Engineer (§2), ARCHITECTURE_CONSOLIDATION.md §1.7
- **Description:** Celery adds Redis broker complexity. Redis Streams already provides async task queuing with consumer groups. APScheduler (already in Day1 requirements) is sufficient.
- **Fix:** **FIX_F** — Remove `celery[redis]` from Day1 requirements. Use APScheduler.

### H14 — litellm Should Be Removed from Day1
- **Source:** Chief Engineer (§2)
- **Description:** LiteLLM is a meta-package depending on many providers. FIX_01 correctly identifies it as problematic. Direct provider calls (Ollama + DeepSeek NIM) are simpler.
- **Fix:** **FIX_F** — Remove `litellm` from Day1 requirements. Use direct `ollama` and `openai` client packages.

### H15 — chromadb Should Be Removed from Day1
- **Source:** Chief Engineer (§2), ARCHITECTURE_CONSOLIDATION.md §1.2
- **Description:** ChromaDB is over-engineered for $10 capital. SQLite FTS5 is sufficient for Day1. Add when portfolio > $1,000.
- **Fix:** **FIX_F** — Remove `chromadb` from Day1 requirements. Add at Level 3.

### H16 — sqlmodel Version Incompatibility
- **Source:** Chief Engineer (§2)
- **Description:** `sqlmodel>=0.0.16` requires Pydantic v1. Architecture specifies `pydantic>=2.6`. Must use `sqlmodel>=0.0.18` for Pydantic v2 compatibility.
- **Fix:** **FIX_F** — Pin `sqlmodel>=0.0.18` in requirements.

### H17 — No Security Scanning in CI
- **Source:** Chief Engineer (§6)
- **Description:** No `safety`, `bandit`, or `trivy` for dependency vulnerability scanning. Critical for a system handling money.
- **Fix:** **FIX_D** — Add `safety check` and `bandit -r src/` to CI pipeline. CI must fail on critical/high vulnerabilities.

### H18 — No Walk-Forward Validation for Strategy Changes
- **Source:** Chief Strategist (§5, Failure Mode 2)
- **Description:** Walk-forward validation is specified but deferred to Level 3+. Without it, strategy mutations are likely overfitting. Should be mandatory for ANY strategy change from Day1.
- **Fix:** **FIX_E** — Make walk-forward validation mandatory for all strategy changes from Day1. Even basic 3-fold WF prevents overfitting.

---

## MEDIUM Issues (21)

### M1 — Anti-Revenge Doesn't Weight by Loss Magnitude
- **Source:** Chief Risk Officer (Medium #1)
- **Description:** Three -0.1% losses trigger same cooldown as three -2% losses. May be too aggressive for small losses, too lenient for large.
- **Fix:** **FIX_D** — Consider weighted anti-revenge guard factoring cumulative loss magnitude.

### M2 — Anti-Greed Streak Expiry Too Generous (48h)
- **Source:** Chief Risk Officer (Medium #2)
- **Description:** 48-hour streak expiry means 5 wins Monday + 48h wait + 3 wins Wednesday = no greed guard. Psychological overconfidence persists beyond 48h.
- **Fix:** **FIX_D** — Consider rolling window approach (7-day win rate > 70% triggers reduced sizing).

### M3 — ATR Multiplier Hardcoded, Not Regime-Dependent
- **Source:** Chief Risk Officer (Medium #4)
- **Description:** `max(stop_distance, 1.5 * ATR)` uses fixed 1.5x multiplier. In high-vol regimes, too tight; in low-vol, too wide.
- **Fix:** **FIX_A** — Make ATR multiplier regime-dependent (1.0x compressed vol, 2.0x extreme vol).

### M4 — Resource Limits Spec Not Yet Implemented
- **Source:** Chief Risk Officer (Medium #6)
- **Description:** FIX_05 is specification only. Until Phase 1 complete, system has NO per-tool resource limits. A runaway tool could crash the Risk Guardian agent.
- **Fix:** **FIX_D** — Implement Resource Limits Phase 1 before any live capital deployment.

### M5 — Risk Tools Could Use Tighter Resource Limits
- **Source:** Chief Risk Officer (Medium #7)
- **Description:** `check_position_limits` should complete in <1ms but has 5s CPU limit (5000x too generous).
- **Fix:** **FIX_D** — Add "sub-millisecond" tier for critical risk checks (64MB, 100ms CPU, 1s wall, 0 network).

### M6 — Mean Reversion Exit Logic Under-Specified
- **Source:** Chief Strategist (§1)
- **Description:** `generate_signals` sets `exits = pd.Series(False)` — relies entirely on backtest engine for stops. Strategy should generate own exit signals (RSI returning to 50, price at VWAP, time-based at 24 candles).
- **Fix:** **FIX_E** — Add explicit exit signal generation to mean reversion strategy.

### M7 — S/R Detection Is Naive
- **Source:** Chief Strategist (§1)
- **Description:** Swing high/low with 48-bar lookback misses volume-weighted S/R, round-number levels, higher-timeframe S/R, and VWAP as dynamic S/R.
- **Fix:** **FIX_E** — Enhance S/R detection: add volume-weighted nodes, round-number levels, VWAP integration.

### M8 — No Volume Profile Integration
- **Source:** Chief Strategist (§1)
- **Description:** Volume multiplier filter (1.2x average) is a blunt instrument. Volume profile analysis (where volume clusters at price levels) would significantly improve S/R identification.
- **Fix:** **FIX_E** — Add basic volume profile analysis for S/R identification at Day30.

### M9 — Behavioral Guards Don't Detect Root Cause
- **Source:** Chief Risk Officer (Medium #3)
- **Description:** Guards detect patterns after they occur (3 losses in a row) but don't prevent conditions leading to them (trading in unfavorable regime).
- **Fix:** **FIX_D** — Acceptable for v1. Note for future: integrate regime awareness into behavioral guards.

### M10 — Day1 ↔ Full Architecture 10x Scope Gap
- **Source:** Chief Engineer (§1, §10 Debt #1)
- **Description:** Day1 is ~20 files; full architecture is 131+ files. No intermediate step. Jump from Day1 to Level 2 is massive.
- **Fix:** **FIX_B** — Define Day30 architecture between Day1 and Level 2.

### M11 — No Horizontal Scaling Story for Agents
- **Source:** Chief Architect (§2.3 #1)
- **Description:** If you need 2 instances of Signal Scout (BTC + ETH), architecture doesn't address this. Consumer groups on Redis Streams would handle it but not specified.
- **Fix:** **FIX_B** — Specify agent multi-instance pattern using Redis consumer groups in Day30 spec.

### M12 — Level 3 Adds 5 Agents Simultaneously
- **Source:** Chief Architect (§2.3 #2)
- **Description:** Adding 5 agents at once is risky. Should be phased within Level 3 (Regime Detector first, then Trade Philosopher, etc.).
- **Fix:** **FIX_B** — Specify phased agent addition ordering within Level 3.

### M13 — ChromaDB Scaling Hand-Waved
- **Source:** Chief Architect (§2.3 #3)
- **Description:** "Add when portfolio > $1,000" but embedding pipeline, collection design, and query patterns are specified in DATA_ARCHITECTURE.md §10. Gap between "deferred" and "fully specified" creates ambiguity.
- **Fix:** **FIX_B** — Clarify ChromaDB integration spec for when it's actually needed (Day30 or Level 2).

### M14 — Agent ↔ Knowledge Store Integration Partially Specified
- **Source:** Chief Architect (§4.3)
- **Description:** Data flow is clear but actual SQL queries each agent uses are not specified. DATA_ARCHITECTURE.md provides examples but not integration contracts.
- **Fix:** **FIX_A** — Specify key SQL query patterns per agent as integration contracts.

### M15 — External API Integration Missing Rate Limits
- **Source:** Chief Architect (§4.6)
- **Description:** 11 data sources (FRED, Yahoo, CoinGecko, etc.) don't specify rate limiting per source, error handling per source, or data freshness requirements.
- **Fix:** **FIX_A** — Add rate limit, error handling, and freshness spec per data source.

### M16 — Prometheus + Grafana Overkill for Day1
- **Source:** Chief Strategist (§9 #4)
- **Description:** Telegram alerts sufficient for solo developer at $10 scale. Add Prometheus at Level 3+ when multiple strategies need dashboards.
- **Fix:** **FIX_C** — Remove Prometheus/Grafana from Day1. Use Telegram-only monitoring.

### M17 — Compliance Layer Unnecessary at Day1 Scale
- **Source:** Chief Strategist (§9 #5)
- **Description:** Immutable audit log, JSONL hash chain is unnecessary for $10. Append to SQLite with timestamp. Add compliance at $10K+.
- **Fix:** **FIX_C** — Remove compliance layer from Day1. Simple SQLite audit trail sufficient.

### M18 — Database Schema Over-Normalized for Day1
- **Source:** Chief Strategist (§9 #3)
- **Description:** 15+ tables for $10 trading system. DAY1_ARCHITECTURE.md already has 5 tables which is correct.
- **Fix:** **FIX_C** — Day1 uses 5 tables (trades, strategies, lessons, daily_snapshots + index). Add complexity as data volume demands.

### M19 — Docker Compose Issues
- **Source:** Chief Engineer (§8)
- **Description:** Port conflict (both trading-agent and api-server expose 8000). No Ollama service. Dockerfile.python builds Rust in-container (10+ min).
- **Fix:** **FIX_C** — Fix port allocation (8000=FastAPI, 8001=agent health). Add Ollama as optional service. Multi-stage Docker build.

### M20 — No Property-Based Testing Strategy
- **Source:** Chief Engineer (§5)
- **Description:** `hypothesis` in dev dependencies but never used. Financial calculations need property-based tests: position size ≤ max, P&L always correct, risk checks monotonic.
- **Fix:** **FIX_D** — Add property-based tests for risk calculations and position sizing.

### M21 — Lesson Effectiveness Not Tracked
- **Source:** Chief Strategist (§5, Failure Mode 3)
- **Description:** FIX_04 tracks application rate and violation rate but not: did applying the lesson actually improve outcomes? What's P&L impact of applied vs non-applied?
- **Fix:** **FIX_E** — Add `lesson_effectiveness` metric comparing P&L of trades where lesson was applied vs not.

---

## LOW Issues (8)

### L1 — Bootstrap Sequence Has No Error Recovery
- **Source:** Chief Architect (§1.4 #3)
- **Description:** If Phase 2 (Data Acquisition) fails partway through, no recovery procedure defined.
- **Fix:** **FIX_B** — Add error recovery to bootstrap sequence (retry failed downloads, skip non-critical data, resume from checkpoint).

### L2 — No TLS Specification for FastAPI Endpoints
- **Source:** Chief Architect (§5.2 #4)
- **Description:** FastAPI endpoints are HTTP, not HTTPS. Kill switch endpoint needs TLS. Architecture mentions "use Caddy/nginx" but doesn't specify.
- **Fix:** **FIX_D** — Add TLS specification (Caddy reverse proxy config) for production deployment.

### L3 — No Rate Limiting on API Endpoints
- **Source:** Chief Architect (§5.2 #5)
- **Description:** FastAPI endpoints have API key auth but no rate limiting. `/kill-switch` should have strict rate limiting.
- **Fix:** **FIX_D** — Add rate limiting specification for FastAPI endpoints.

### L4 — Rust Version Discrepancy
- **Source:** ARCHITECTURE_CONSOLIDATION.md §3 Contradiction #6
- **Description:** Tools Spec says Rust 1.78, Deployment says 1.79. Already resolved in consolidation doc.
- **Fix:** **FIX_A** — Already resolved. Verify all docs reference Rust 1.79.

### L5 — Port Allocation Discrepancy
- **Source:** ARCHITECTURE_CONSOLIDATION.md §3 Contradiction #5
- **Description:** Deployment spec says port 8000 for agent, TECH_STACK says 8000 for FastAPI. Already resolved in consolidation doc.
- **Fix:** **FIX_A** — Already resolved. Verify all docs reference canonical ports.

### L6 — CloudEvents Migration Deferred
- **Source:** Chief Engineer (§10 Debt #5)
- **Description:** FIX_03 adds 32 days of work for messaging protocol change with no user-facing benefit at Day1. Use simple JSON messages on Redis PubSub for Day1.
- **Fix:** **FIX_C** — Defer CloudEvents to Level 2. Use simple JSON on Redis PubSub for Day1.

### L7 — Config File Proliferation
- **Source:** Chief Engineer (§10 Debt #6)
- **Description:** 12+ config files (default.yaml, exchanges.yaml, risk.yaml, model_routing.yaml, models.yaml, alerts.yaml, etc.). Overwhelming for Day1.
- **Fix:** **FIX_C** — Consolidate to 3 files for Day1: settings.yaml, exchanges.yaml, risk.yaml.

### L8 — Paper Trading Slippage Model Accuracy
- **Source:** Chief Engineer (§10 Debt #9)
- **Description:** Paper engine uses mean 3bps slippage, std 2bps. Real slippage varies wildly by market conditions.
- **Fix:** **FIX_D** — Log actual vs simulated slippage from Day1, tune model over time.

---

## Fix Category Assignments Summary

### FIX_A: Parameter Reconciliation (14 issues)
Resolve all cross-document inconsistencies. Update every document to match ARCHITECTURE_CONSOLIDATION.md canonical values.

| Issue | Action |
|-------|--------|
| C1 | Reconcile all risk parameters to canonical values |
| C2 | Update circuit breaker thresholds in RISK_ARCHITECTURE.md |
| C8 | Merge FIX_01/FIX_02 into single ModelRouter |
| H2 | Clarify Kelly fraction: dynamic kelly/2 with 2% cap |
| H6 | Update DATA_ARCHITECTURE.md to single tsar.db |
| M3 | Make ATR multiplier regime-dependent |
| M14 | Specify key SQL query patterns per agent |
| M15 | Add rate limit/error handling spec per data source |
| L4 | Verify Rust 1.79 in all docs |
| L5 | Verify canonical ports in all docs |
| + 4 minor doc alignment items |

### FIX_B: Day30 Architecture Spec (5 issues)
Define the intermediate build stage between Day1 and Level 2.

| Issue | Action |
|-------|--------|
| M10 | Define Day30 architecture (Redis caching, vectorbt, momentum strategy, basic metrics) |
| M11 | Specify agent multi-instance pattern |
| M12 | Specify phased agent addition ordering for Level 3 |
| M13 | Clarify ChromaDB integration timing |
| L1 | Add error recovery to bootstrap sequence |

### FIX_C: Day1 Scope Adjustment (12 issues)
Remove Rust, simplify LLM, reduce packages, trim to buildable scope.

| Issue | Action |
|-------|--------|
| C5 | Mark full architecture as "FUTURE — DO NOT IMPLEMENT YET" |
| C6 | Reduce to 3 agents, pure Python, ~20 files, ~18 deps |
| C7 | Simple 100-line LLM router for Day1 |
| H1 | Remove Rust from Day1 (pure Python) |
| M16 | Remove Prometheus/Grafana from Day1 |
| M17 | Remove compliance layer from Day1 |
| M18 | Use 5 DB tables for Day1 |
| M19 | Fix Docker Compose port/service issues |
| L6 | Defer CloudEvents to Level 2 |
| L7 | Consolidate to 3 config files |
| + 2 minor scope items |

### FIX_D: Risk Hardening (12 issues)
Redis fallback, kill switch watchdog, stress testing, safety mechanisms.

| Issue | Action |
|-------|--------|
| C3 | Add dead man's switch for Redis failure |
| C4 | Add watchdog process for kill switch monitor |
| H3 | Add regime-aware recovery protocol |
| H4 | Add negative balance protection |
| H5 | Add Day1 stress test specification |
| H17 | Add security scanning to CI |
| M1 | Weighted anti-revenge by loss magnitude |
| M2 | Rolling window for anti-greed |
| M4 | Implement Resource Limits Phase 1 |
| M5 | Sub-millisecond tier for risk checks |
| M9 | Note regime-aware behavioral guards for future |
| L2-L3 | TLS and rate limiting specs |
| L8 | Slippage model tuning |
| M20 | Property-based testing for risk calcs |

### FIX_E: Strategy Updates (7 issues)
Add momentum, remove genetic programming, adjust baselines, improve signals.

| Issue | Action |
|-------|--------|
| H7 | Add Momentum strategy to Day1 |
| H8 | Add funding rate as Day1 signal |
| H9 | Replace genetic programming with LLM-guided optimization + grid search |
| H10 | Change improvement baseline from 30 to 100 trades |
| H11 | Add alpha_vs_baseline_strategy metric |
| H18 | Make walk-forward validation mandatory from Day1 |
| M6-M8 | Improve exit logic, S/R detection, volume profile |
| M21 | Track lesson effectiveness |

### FIX_F: Dependency Cleanup (5 issues)
Remove unnecessary packages, resolve version conflicts.

| Issue | Action |
|-------|--------|
| H12 | Pick TA-Lib OR pandas-ta (not both) |
| H13 | Remove celery from Day1 |
| H14 | Remove litellm from Day1 |
| H15 | Remove chromadb from Day1 |
| H16 | Pin sqlmodel>=0.0.18 |

---

## Execution Priority

### Phase 1 — Immediate (Before Any Code)
1. **FIX_A** — Reconcile all parameters. This is the foundation. Wrong params = wrong system.
2. **FIX_F** — Clean up dependencies. Get requirements.txt right before `pip install`.
3. **FIX_C** — Define exact Day1 scope. What are we building?

### Phase 2 — Week 1-2 (During Build)
4. **FIX_D** — Implement risk hardening alongside risk engine code.
5. **FIX_E** — Add momentum strategy and funding rate signal during strategy implementation.

### Phase 3 — Week 3-4 (Before Deployment)
6. **FIX_B** — Define Day30 architecture before starting Level 2 work.

---

*Compilation completed: 2026-07-24 04:59 GMT+8*  
*Chief Fixer, TSAR Council of 5*
