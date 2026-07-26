# Integration Team 3 Review: Strategy Evolution Wiring

**Team:** Integration Team 3 — Strategy Evolution Wiring
**Date:** 2026-07-27
**Scope:** Gaps G5–G9, new event types, tests

---

## Summary

All assigned gaps have been resolved. The FactorLibrary is now wired into SignalScout for factor-enhanced signal scoring, and the StrategyGeneticist has been fully implemented with a complete backtest → walk-forward → Monte Carlo evaluation pipeline plus periodic factor benchmarking.

---

## Gaps Resolved

### G5: FactorLibrary → SignalScout ✅

**File:** `src/agents/signal_scout.py`

**Changes:**
- Added `FactorLibrary` import and optional initialization via `config.factor_library.enabled`
- New method `_compute_factor_adjustment(ohlcv_df, side)` computes a composite signal from RSI, BB %B, MFI, and ADX factors
- Factor adjustment applied as ±20% modifier to base signal score after all existing scoring
- Mean-reversion contrarian logic: oversold factors reinforce BUY, overbought reinforce SELL
- ADX penalty: trending markets (ADX > 25) reduce factor confidence (mean reversion works in ranges)
- Graceful fallback: if factor computation fails, scoring proceeds without adjustment

**Score formula:**
```
adjusted_score = base_score * (1.0 + 0.2 * factor_adjustment)
```
Where `factor_adjustment ∈ [-1, 1]` is a weighted composite of normalized RSI (40%), BB %B (30%), MFI (30%), penalized by ADX trend strength.

### G6: BacktestEngine → StrategyGeneticist ✅

**File:** `src/agents/strategy_geneticist.py`

**Changes:**
- `evaluate_strategy()` runs BacktestEngine as Stage 1 of the pipeline
- Configurable via `config.backtest` (capital, position size, commission, slippage)
- Quality gates at backtest stage:
  - Minimum 5 trades required
  - Negative Sharpe → reject
  - Max drawdown > 30% → reject

### G7: WalkForwardValidator → StrategyGeneticist ✅

**File:** `src/agents/strategy_geneticist.py`

**Changes:**
- Stage 2 of `evaluate_strategy()`: WalkForwardValidator runs after backtest passes
- Configurable via `config.walk_forward` (n_windows, train_ratio, overfit_threshold)
- Quality gates:
  - Overfitting score > threshold → reject
  - Consistency score < 40% → reject

### G8: MonteCarloSimulator → StrategyGeneticist ✅

**File:** `src/agents/strategy_geneticist.py`

**Changes:**
- Stage 3 of `evaluate_strategy()`: MonteCarloSimulator runs after walk-forward passes
- Configurable via `config.monte_carlo` (n_simulations, confidence_levels)
- Quality gates:
  - Probability of ruin > 10% → reject
  - Probability of profit < 50% → reject

### G9: FactorBenchmarker Scheduling ✅

**File:** `src/agents/strategy_geneticist.py`

**Changes:**
- Periodic factor benchmarking in `run_cycle()` with configurable interval (default: 168h = weekly)
- `_run_factor_benchmark()` computes IC/IR for all factors via FactorBenchmarker
- Publishes `tsar.factor.benchmark.v1` event with top-10 factor rankings
- Requires OHLCV provider for data (gracefully skips if unavailable)

---

## New Event Types

**File:** `src/comms/events.py`

Already present (verified):
- `TSAR_MANDATE_COMMITTED = "tsar.mandate.committed.v1"` ✅
- `TSAR_MANDATE_REVOKED = "tsar.mandate.revoked.v1"` ✅
- `TSAR_FACTOR_BENCHMARK = "tsar.factor.benchmark.v1"` ✅

---

## Tests

### `tests/unit/agents/test_strategy_geneticist.py` — 14 tests

| Test Class | Tests | Description |
|---|---|---|
| TestStrategyEvaluation | 3 | Data class structure, summary format |
| TestEvaluateStrategy | 4 | Full pipeline execution, rejection at each stage |
| TestFactorBenchmarking | 2 | Scheduling, interval respect |
| TestRetirementGates | 3 | Drawdown retire/pause, Sharpe warning |
| TestProposalEvaluation | 2 | Confidence gate, acceptance flow |

### `tests/unit/strategy/test_factor_integration.py` — 16 tests

| Test Class | Tests | Description |
|---|---|---|
| TestFactorLibraryInit | 3 | Enabled/disabled/default config |
| TestFactorAdjustment | 3 | Oversold BUY, overbought SELL, bounds |
| TestScoreAdjustment | 5 | ±20% formula, clamping, edge cases |
| TestFactorLibraryCompute | 5 | RSI, BB %B, MFI, ADX computation, factor registry |

**Total: 30 new tests, all passing. 574 total suite tests pass (0 failures).**

---

## Architecture Decisions

1. **Factor adjustment is additive, not replacing.** The existing 4-indicator scoring (RSI 40%, S/R 30%, Volume 15%, Trend 15%) remains unchanged. Factor adjustment is a ±20% modifier applied after base scoring. This preserves backward compatibility.

2. **Pipeline gates are sequential and early-exit.** Backtest → WalkForward → MonteCarlo. If any stage fails, evaluation stops immediately. This saves computation on clearly bad strategies.

3. **Factor benchmarking is fire-and-forget.** Runs on a configurable schedule (default weekly), publishes results to the analytics stream. Other agents can subscribe for factor selection.

4. **StrategyGeneticist accepts injected dependencies.** Constructor takes optional `backtest_engine`, `walk_forward`, `monte_carlo`, `factor_library`, `factor_benchmarker`, `strategy_factory`, `ohlcv_provider`. This enables full unit testing without external dependencies.

5. **Retirement gates are conservative.** Auto-retire at 20% drawdown, auto-pause at 15%. Low Sharpe logs warning but doesn't auto-retire (needs human judgment).

---

## Remaining Work (Out of Scope)

| Item | Owner | Notes |
|---|---|---|
| G1: ShadowExtractor orchestrator trigger | Team 1 | Not in our scope |
| G2: OHLCVProvider adapter | Team 1 | Not in our scope |
| G3: GenomeMutator → StrategyGeneticist stream | Team 1 | Events defined, needs stream wiring |
| G4: MandateGate → RiskGuardian | Team 2 | Not in our scope |
| G10: config/mandate.yaml | Team 2 | Not in our scope |

---

## Files Modified

| File | Change |
|---|---|
| `src/agents/signal_scout.py` | Added FactorLibrary integration (G5) |
| `src/agents/strategy_geneticist.py` | Full rewrite with BacktestEngine/WF/MC/FactorBench (G6-G9) |
| `src/comms/events.py` | No changes needed (event types already present) |

## Files Created

| File | Purpose |
|---|---|
| `tests/unit/agents/test_strategy_geneticist.py` | 14 tests for StrategyGeneticist |
| `tests/unit/strategy/test_factor_integration.py` | 16 tests for FactorLibrary integration |

---

*Integration Team 3 — Strategy Evolution Wiring — Complete.*
