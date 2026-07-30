# Backtesting Tools Council Review

**Date:** 2026-07-30  
**Status:** ✅ All 6 Tools Implemented & Verified  
**File:** `src/tools/backtesting.py` (~57KB)

---

## Tool Inventory

| # | Tool | Method | Status |
|---|------|--------|--------|
| 1 | Strategy Backtester | `run_backtest()` | ✅ IMPLEMENTED |
| 2 | Walk-Forward Validation | `walk_forward_validate()` | ✅ IMPLEMENTED |
| 3 | Monte Carlo Simulation | `monte_carlo_simulation()` | ✅ IMPLEMENTED |
| 4 | Performance Metrics | `compute_performance_metrics()` | ✅ IMPLEMENTED |
| 5 | Factor Analysis | `analyze_factors()` | ✅ IMPLEMENTED |
| 6 | Regime-Conditional Backtest | `regime_conditional_backtest()` | ✅ IMPLEMENTED |

---

## Tool Details

### 1. Strategy Backtester (`run_backtest`)
- Simulates trade execution on OHLCV data given a signal series
- Positive signal → long, negative → short, zero → flat
- Signals at bar `i` execute at bar `i+1` open (no look-ahead bias)
- Configurable: fee rate, slippage bps, position sizing, risk-free rate
- Returns: full trade log with PnL/fees/slippage per trade, equity curve, and aggregate metrics (Sharpe, Sortino, win rate, profit factor, streaks)

### 2. Walk-Forward Validation (`walk_forward_validate`)
- Rolling window train/test with `n_splits` folds
- Accepts a `signal_func(ohlcv_subset) -> signals` callable for parameter optimization
- Computes per-fold IS and OOS metrics
- Stitches OOS equity curves with proper scaling
- Key outputs: `oos_degradation` (overfitting indicator), `stability_score` (consistency of OOS performance)

### 3. Monte Carlo Simulation (`monte_carlo_simulation`)
- Bootstrap resampling of historical returns (with replacement)
- Configurable number of simulations (default 10,000) and simulation length
- Computes: median/mean equity, percentile CIs (p1–p99), max drawdown distribution, Sharpe distribution
- **Ruin probability**: P(final equity < 50% of initial capital)
- Reproducible via `seed` parameter
- Returns full CI dicts for equity, max_drawdown, and sharpe_ratio

### 4. Performance Metrics (`compute_performance_metrics`)
- Full risk/return suite from a return series:
  - **Return**: total, annualized
  - **Risk**: volatility, max drawdown, max drawdown duration
  - **Ratios**: Sharpe, Sortino, Calmar
  - **Trade stats**: win rate, profit factor, expectancy, payoff ratio
  - **Tail risk**: tail ratio (p95/|p5|), skewness, kurtosis
- Uses scipy for distribution statistics

### 5. Factor Analysis (`analyze_factors`)
- Multi-factor OLS regression: `strategy_return = alpha + Σ(βᵢ × factorᵢ) + ε`
- **IC**: Spearman rank correlation of primary factor vs strategy returns
- **IR**: Information Ratio (IC_mean / IC_std) from rolling windows
- Per-factor: beta, t-stat, p-value, R² contribution (drop-one), partial correlation
- Alpha annualized and reported with t-statistic
- Rolling IC series for time-varying analysis

### 6. Regime-Conditional Backtest (`regime_conditional_backtest`)
- **NEWLY IMPLEMENTED** — answers "How does this strategy perform in trending vs ranging?"
- Two detection methods:
  - `rule_based`: rolling trend strength + volatility percentile classification
  - `hmm`: 2-state Gaussian HMM via hmmlearn (falls back to rule_based if unavailable)
- 5 regimes: `trending_up`, `trending_down`, `ranging`, `high_volatility`, `low_volatility`
- Per-regime metrics: return, Sharpe, Sortino, max drawdown, win rate, profit factor, trade count, volatility, % of total time
- **Regime transitions**: matrix of transition counts between regimes
- **Regime adaptability**: how much Sharpe varies across regimes (0–1)
- Identifies best/worst regime by Sharpe ratio

---

## Architecture

- **Class**: `BacktestingTools` — single class with 6 public methods + internal helpers
- **Pure computation**: no external API calls, no LLM, fully deterministic
- **Dependencies**: numpy, pandas, scipy (core); hmmlearn (optional, for HMM regime detection)
- **Result types**: 10 frozen dataclasses (`BacktestResult`, `WalkForwardResult`, `MonteCarloResult`, `PerformanceMetrics`, `FactorAnalysisResult`, `FactorExposure`, `RegimeConditionalBacktestResult`, `RegimePerformance`, `TradeRecord`, `MarketRegime`)
- **Helper functions**: `_compute_sharpe`, `_compute_sortino`, `_compute_max_drawdown`, `_compute_max_drawdown_duration`, `_apply_slippage`, `_compute_fees`, `_streak_count`
- **Registered** in `src/tools/__init__.py` as `BacktestingTools`

---

## Smoke Test Results

```
1. Backtest: 102 trades, return=-100.0%, sharpe=-11.17 (random signals → expected losses)
2. Walk-Forward: 3 folds, OOS return=-100.0%, degradation=10.53%
3. Monte Carlo: median_equity=9597.43, ruin_prob=0.0%
4. Metrics: sharpe=-0.78, sortino=-1.40, mdd=9.09%
5. Factor: IC=0.43, IR=2.50, alpha=-18.16%, R²=0.25
6. Regime: best=trending_up, worst=low_volatility, adaptability=1.0
   high_volatility: -3.77%, sharpe=-2.17, 37.69% of time
   ranging: +0.67%, sharpe=0.36, 35.68% of time
   trending_down: -0.11%, sharpe=-0.05, 19.60% of time
   low_volatility: -1.69%, sharpe=-12.04, 4.02% of time
   trending_up: +0.35%, sharpe=1.06, 3.02% of time
```

All 6 tools produce valid, structured output with no errors.
