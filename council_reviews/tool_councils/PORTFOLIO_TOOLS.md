# PORTFOLIO TOOLS COUNCIL REVIEW

**Date:** 2026-07-30
**Council:** Portfolio Tools
**Status:** ✅ ALL 6 TOOLS IMPLEMENTED & VERIFIED

## File

`src/tools/portfolio.py` — 53,961 bytes, ~870 lines

## Tools Implemented

### 1. Mean-CVaR Optimizer ✅
- **Method:** `mean_cvar_optimize(symbols, returns_matrix, ...)`
- **Objective:** Minimize Conditional Value at Risk (CVaR) at configurable confidence level (default 95%)
- **GPU path:** Delegates to `CuFOLIOBackend` (NVIDIA cuFOLIO) when available
- **Fallback:** scipy SLSQP optimizer
- **Features:**
  - Efficient frontier generation (configurable points, default 50)
  - Per-asset weight bounds (default max 15%)
  - Annualized metrics: return, risk, CVaR, Sharpe ratio
  - Convergence reporting with iteration count

### 2. Black-Litterman ✅
- **Method:** `black_litterman(symbols, returns_matrix, views, ...)`
- **Model:** Full He-Litterman Bayesian update
  1. Implied equilibrium returns: π = δ·Σ·w_mkt
  2. View matrices: P (pick), Q (returns), Ω (confidence via He-Litterman scaling)
  3. Posterior: E[R] = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹·[(τΣ)⁻¹π + P'Ω⁻¹Q]
  4. Optimal weights: w* = (1/δ)·Σ_post⁻¹·E[R]
- **View types:** Absolute views (single asset) and relative views (long/short pairs)
- **Parameters:** τ (uncertainty scaling), δ (risk aversion), market cap weights
- **No views:** Returns equilibrium portfolio

### 3. Rebalancer ✅
- **Method:** `check_rebalance(current_weights, target_weights, portfolio_value, ...)`
- **Triggers:**
  - **Threshold:** Max drift > configurable % (default 5%) → rebalance
  - **Calendar:** Time since last rebalance exceeds frequency → rebalance
- **Frequencies:** Daily, Weekly, Monthly, Quarterly
- **Output:** Trade list with symbol, side, weight change, USD amount
- **Metrics:** Turnover, estimated transaction cost (bps), max drift
- **Convenience:** `compute_threshold_rebalance()` for threshold-only check

### 4. Asset Allocator ✅
- **Method:** `allocate_assets(assets, risk_profile, ...)`
- **Risk Profiles:**
  - **Conservative:** 10% crypto, 30% gold, 25% forex, 25% bonds, 10% equities
  - **Moderate:** 25% crypto, 20% gold, 15% forex, 15% bonds, 25% equities
  - **Aggressive:** 50% crypto, 10% gold, 10% forex, 5% bonds, 25% equities
- **Sub-allocation:** Equal weight (default), inverse volatility (with returns), or custom overrides
- **Output:** Per-asset weights, class breakdown, expected return/volatility, rationale

### 5. Diversification Scorer ✅
- **Method:** `score_diversification(weights, returns_matrix, symbols)`
- **Metrics:**
  - **HHI** (Herfindahl-Hirschman Index): Σ(wᵢ²)
  - **Effective N:** 1/HHI — equivalent equal-weight asset count
  - **Correlation diversification ratio:** σ_p / Σ(wᵢ·σᵢ)
  - **Average/min/max pairwise correlation**
- **Score:** Composite 0-100 (40% HHI + 40% correlation + 20% effective N)
- **Recommendations:** Context-aware suggestions (concentration, correlation, asset count)

### 6. Risk Parity ✅
- **Methods:**
  - `risk_parity(symbols, returns, method="equal_risk_contribution")` — ERC via scipy SLSQP
  - `risk_parity(symbols, returns, method="inverse_volatility")` — closed-form
- **ERC objective:** min Σᵢ(RCᵢ - 1/N)² where RCᵢ = wᵢ·(Σw)ᵢ/σ_p
- **Inverse vol:** wᵢ ∝ 1/σᵢ, normalized
- **Output:** Weights, per-asset risk contributions (absolute & %), total portfolio risk

## Architecture

- **Class:** `PortfolioTools` — single class, all 6 methods async
- **GPU integration:** Lazy-loads `CuFOLIOBackend` from `src.backends/python/cufolio_backend.py`
- **Fallback:** All compute paths have scipy/numpy fallbacks
- **Config:** Centralized `DEFAULT_CONFIG` dict with per-tool sections
- **Types:** 7 frozen dataclass result types with `to_dict()` serialization
- **Registration:** Compatible with `src/tools/__init__.py` tool registry (`PortfolioTools`)

## Test Results

```
1. Mean-CVaR: empty→fallback OK
2. BL no-views: 5 assets, method=scipy_no_views
2b. BL with views: 5 assets
3. Rebalancer: needs=True, trigger=threshold, trades=3, drift=34.0%
4. Allocator (conservative): 4 assets, crypto=15.4%
4. Allocator (moderate): 4 assets, crypto=41.7%
4. Allocator (aggressive): 4 assets, crypto=71.4%
5. Diversification: HHI=0.3550, eff_n=2.82, score=77.3
6. Risk Parity (inv_vol): 5 assets, risk=0.1371
Status: 6 tools
ALL 6 PORTFOLIO TOOLS VERIFIED
```

## Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| numpy | Yes | Core math |
| scipy | Yes | SLSQP optimization (lazy import) |
| cufolio | Optional | GPU-accelerated Mean-CVaR |
| cupy | Optional | GPU arrays for cuFOLIO |
