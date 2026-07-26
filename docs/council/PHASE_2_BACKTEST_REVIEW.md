# Phase 2: Backtest Engine — Council Review

**Date:** 2026-07-27
**Reviewer:** Automated Council Review
**Status:** ✅ COMPLETE — All deliverables implemented and tested

---

## Executive Summary

Phase 2 delivers the backtest validation pipeline for TSAR's Strategy Geneticist. The backtest engine replays historical OHLCV data through strategy rules, walk-forward validation detects overfitting, and Monte Carlo simulation assesses statistical robustness. All three components are fully implemented, tested (46 tests, all passing), and integrated.

## Deliverables

### 1. `src/strategy/backtest_engine.py` — BacktestEngine

**Status:** ✅ Complete

| Feature | Implementation |
|---------|---------------|
| Bar-by-bar simulation | Iterates OHLCV, calls `check_entry()` / `check_exit()` on each bar |
| Commission model | Configurable basis points per trade (one-way), applied at entry and exit |
| Slippage model | Configurable basis points, direction-aware (buy pays more, sell receives less) |
| Position sizing | Fraction of capital per trade (`position_size_pct`) |
| Signal-level SL/TP | Stop-loss and take-profit from signal dict are enforced alongside strategy exit rules |
| Force close at end | Open positions are closed at the final bar's close |
| Mark-to-market | Equity curve reflects unrealized PnL on open positions |
| Metrics computed | Sharpe, Sortino, Calmar, CAGR, max drawdown, win rate, profit factor, expectancy |

**Key design decisions:**
- Dataclass results (`BacktestResult`, `BacktestMetrics`, `TradeRecord`) — frozen, typed, immutable
- `BacktestConfig` is frozen dataclass with sensible defaults (10 bps commission, 5 bps slippage)
- Equity curve has N+1 entries (initial capital + one per bar)
- Strategy receives a data dict with OHLCV + rolling close history for indicator computation
- Single position at a time (configurable via `max_open_positions`)

### 2. `src/strategy/walk_forward.py` — WalkForwardValidator

**Status:** ✅ Complete

| Feature | Implementation |
|---------|---------------|
| Rolling windows | N sliding or anchored train/test windows |
| Train ratio | Configurable split (default 70/30) |
| Optimization hook | Optional `optimize_fn` called per window on train data |
| Overfitting detection | Compares median train Sharpe vs median test Sharpe |
| Consistency score | Fraction of windows with positive test Sharpe |
| Aggregate metrics | Averaged across all windows (train and test separately) |

**Overfitting formula:**
```
overfit_score = abs(median_train_sharpe) / abs(median_test_sharpe)
is_overfit = overfit_score > overfit_threshold (default 3.0)
```

**Key design decisions:**
- `StrategyFactory` callable pattern — allows parameter injection per window
- Anchored mode supported (train always starts from bar 0)
- Minimum bar requirements prevent degenerate windows
- Each `WindowResult` preserves both train and test `BacktestResult` for drill-down

### 3. `src/strategy/monte_carlo.py` — MonteCarloSimulator

**Status:** ✅ Complete

| Feature | Implementation |
|---------|---------------|
| Trade permutation | N random shuffles of trade PnL sequence |
| Confidence intervals | Configurable percentiles (5, 25, 50, 75, 95 default) |
| Metrics tracked | Total return, Sharpe, max drawdown, win rate, profit factor, Calmar |
| P(profit) | Fraction of simulations with positive return |
| P(ruin) | Fraction of simulations dropping below 50% of initial capital |
| Reproducibility | Optional random seed for deterministic results |

**Key design decisions:**
- Uses `numpy.random.default_rng` (modern, seedable RNG)
- Handles edge cases: inf profit_factor, empty finite arrays, single trade
- Each distribution stores the original backtest value for comparison
- Equity curve simulated by compounding shuffled returns

### 4. `tests/unit/strategy/test_backtest_engine.py`

**Status:** ✅ 46 tests, all passing (0.55s)

| Test Class | Count | Coverage |
|------------|-------|----------|
| TestBacktestEngineBasic | 7 | Core simulation, uptrend/downtrend, commission/slippage |
| TestBacktestMetrics | 8 | Metric types, ranges, finiteness, consistency |
| TestBacktestEdgeCases | 6 | No signals, all losers, single trade, minimal data |
| TestBacktestStopLoss | 1 | SL triggering on downtrend |
| TestShortSelling | 1 | Short trades on downtrend |
| TestWalkForwardValidator | 9 | Splits, overfitting, anchored, optimizer, too-short data |
| TestMonteCarloSimulator | 12 | Distributions, percentiles, seeds, edge cases |
| TestMonteCarloIntegration | 1 | MC on real backtest output |
| TestFullPipeline | 1 | End-to-end: walk-forward → Monte Carlo |

## Architecture Compliance

| Constraint | Status |
|------------|--------|
| Follow existing patterns in `src/strategy/` | ✅ Uses BaseStrategy ABC, dataclass results, same naming |
| Use `src/interfaces/types.py` for OHLCV | ✅ Imports OHLCV from interfaces |
| Use dataclasses for result types | ✅ All results are frozen dataclasses |
| Synchronous (CPU-bound) | ✅ No async, no I/O |
| No external deps beyond numpy/pandas | ✅ Only numpy used (pandas not needed) |
| Type hints throughout | ✅ Full annotations |

## Known Limitations & Future Work

1. **Single-asset only** — Engine simulates one symbol. Multi-asset correlation backtesting is future work.
2. **Bar-level granularity** — SL/TP are checked at bar close, not intra-bar. For crypto (24/7), this is acceptable. For intraday strategies, tick-level simulation would be needed.
3. **No partial fills** — Positions are fully filled at one price. Real slippage varies with size.
4. **Walk-forward optimizer is a hook** — The `optimize_fn` is user-provided. A grid search or genetic optimizer should be implemented by the Strategy Geneticist.
5. **Monte Carlo assumes i.i.d.** — Shuffling trades assumes independence. Strategies with regime-dependent performance may show misleading confidence intervals.

## Files Changed

| File | Action |
|------|--------|
| `src/strategy/backtest_engine.py` | **Created** (21KB) |
| `src/strategy/walk_forward.py` | **Created** (15KB) |
| `src/strategy/monte_carlo.py` | **Created** (11KB) |
| `src/strategy/__init__.py` | **Modified** — Added exports for new modules |
| `tests/unit/strategy/test_backtest_engine.py` | **Created** (35KB, 46 tests) |
| `analysis/council/PHASE_2_BACKTEST_REVIEW.md` | **Created** (this file) |

## Verification

```
$ python3 -m pytest tests/unit/strategy/test_backtest_engine.py -v
46 passed in 0.55s

$ python3 -m pytest tests/unit/strategy/test_mean_reversion.py -v
39 passed in 0.29s  (existing tests unbroken)
```

## Council Decision

**APPROVE** — Phase 2 delivers a complete, well-tested backtest validation pipeline. The Strategy Geneticist can now validate strategy genomes before going live by running them through historical simulation, walk-forward validation, and Monte Carlo robustness testing.
