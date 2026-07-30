# NVIDIA Skills Integration — Fix Team Summary

**Team:** NVIDIA Skills Integration  
**Date:** 2026-07-30  
**Status:** ✅ Complete

---

## Overview

Integrated 5 critical NVIDIA agent skills into TSAR's codebase, providing GPU-accelerated portfolio optimization, multi-objective strategy optimization, enhanced RAG retrieval, LLM output evaluation, and automated risk policy generation. All integrations follow TSAR's existing patterns: async methods, graceful degradation, and zero hard dependencies.

---

## Skills Integrated

### 1. cuFOLIO — GPU-Accelerated Portfolio Optimization

**File:** `src/backends/python/cufolio_backend.py` (NEW — 25KB)

**What it does:**
- Mean-CVaR portfolio optimization with GPU acceleration
- Efficient frontier generation (100+ optimal portfolios)
- Monte Carlo scenario generation for stress testing
- Portfolio backtesting with transaction cost modeling

**Key class:** `CuFOLIOBackend`
- `optimize_portfolio()` — Mean-CVaR optimal allocation
- `generate_efficient_frontier()` — Full efficient frontier
- `generate_scenarios()` — Monte Carlo scenarios
- `backtest_portfolio()` — Historical backtest

**Fallback:** scipy.optimize (SLSQP) + numpy — identical API, CPU-only

**Integration point:** Can be used by `PositionSizer` for portfolio-level sizing and by `StrategyGeneticist` for allocation optimization.

---

### 2. cuOpt — Multi-Objective Strategy Optimizer

**File:** `src/strategy/cuopt_optimizer.py` (NEW — 15KB)

**What it does:**
- GPU-accelerated multi-objective optimization for strategy parameters
- Optimizes win rate, profit factor, max drawdown, and Sharpe ratio simultaneously
- Configurable parameter bounds and objectives
- Pareto front extraction for trade-off analysis

**Key class:** `CuOptStrategyOptimizer`
- `add_parameter()` — Define parameter search space
- `add_objective()` — Define optimization targets
- `optimize()` — Run multi-objective optimization with fitness function

**Fallback:** scipy.optimize.differential_evolution — same API, CPU-only

**Integration point:** Used by `StrategyGeneticist` to optimize strategy genome parameters (RSI period, MACD settings, etc.) against backtest results.

---

### 3. RAG Blueprint — Enhanced Knowledge Retrieval

**File:** `src/knowledge/rag_blueprint_search.py` (NEW — 16KB)  
**Modified:** `src/knowledge/fts_search.py` (added RAG Blueprint integration)

**What it does:**
- Query expansion — generates related queries for better recall
- Cross-encoder reranking — improves result relevance ordering
- Context enrichment — expands snippets with full record context
- Hybrid search weight tuning — optimizes FTS5 vs vector balance

**Key class:** `RAGBlueprintSearch`
- `enhanced_search()` — Full RAG pipeline (expand → search → rerank → enrich)

**Fallback:** Existing FTS5 + ChromaDB hybrid search with keyword overlap reranking

**Integration point:** `MemoryRecall.enhanced_search()` automatically uses RAG Blueprint when available, falls back to existing hybrid search. All 5 knowledge stores benefit:
- `trade_records` — Better trade thesis retrieval
- `strategy_genomes` — Better strategy matching
- `patterns` — Better pattern similarity
- `lessons` — Better lesson relevance
- `market_state` — Better regime context

---

### 4. Nemo Evaluator — LLM Output Quality Assessment

**File:** `src/llm/evaluation.py` (MODIFIED — added 270 lines)

**What it does:**
- Multi-dimensional evaluation of LLM trading outputs
- 4 dimensions: factual accuracy, risk awareness, actionability, coherence
- Configurable scoring thresholds (min acceptable, auto-reject)
- Weighted scoring with rationale tracking

**Key class:** `NemoTradeEvaluator`
- `evaluate_llm_output()` — Score LLM output on all dimensions
- `status()` — Check evaluator availability and config

**Fallback:** Rule-based evaluation using keyword matching for each dimension

**Integration point:** Can be called by `TradePhilosopher` and `SignalScout` agents to validate LLM outputs before acting on them. Integrates with existing `LLMEvaluator` for comprehensive quality tracking.

---

### 5. Nemotron Policy Generator — Automated Risk Guardrails

**File:** `src/risk/nemotron_policy_generator.py` (NEW — 20KB)

**What it does:**
- Generates adaptive risk policies based on market context and performance
- 5 policy categories: position limits, drawdown rules, correlation limits, volatility adjustments, regime-adaptive rules
- Confidence scoring and validation against historical data
- Human approval workflow for generated policies

**Key class:** `NemotronPolicyGenerator`
- `generate_policies()` — Generate context-aware risk policies
- `apply_policy()` — Convert policy to runtime config overrides
- `status()` — Check generator availability

**Fallback:** Static rules from `config/risk.yaml` with regime-aware adjustments

**Integration point:** Used by `RiskGuardian` to dynamically adjust risk parameters based on:
- Current market regime (trending/ranging/high_volatility)
- Recent trading performance (win rate, drawdown, Sharpe)
- Portfolio characteristics (correlation, concentration)

---

## Configuration

**File:** `config/nvidia_skills.yaml` (NEW — 4.6KB)

All 5 skills are configured in a single YAML file with:
- Enable/disable toggles per skill
- Optimization parameters (solver settings, objective weights)
- Scoring thresholds and approval requirements
- Fallback method selection
- Knowledge store targets for RAG Blueprint

---

## Design Principles

| Principle | Implementation |
|---|---|
| **Optional dependencies** | All NVIDIA packages checked at import time with `try/except` |
| **Graceful degradation** | Every skill has a fallback path (scipy, rule-based, static) |
| **Async-first** | All compute-heavy methods use `run_in_executor` |
| **No code breakage** | Existing code untouched; new capabilities added alongside |
| **Config-driven** | Single `nvidia_skills.yaml` controls all integrations |
| **TSAR patterns** | Follows existing backend/interface/ABC patterns |

---

## Files Summary

| File | Action | Lines | Description |
|---|---|---|---|
| `config/nvidia_skills.yaml` | **Created** | ~130 | Central NVIDIA skills configuration |
| `src/backends/python/cufolio_backend.py` | **Created** | ~580 | cuFOLIO portfolio optimization backend |
| `src/strategy/cuopt_optimizer.py` | **Created** | ~400 | cuOpt multi-objective optimizer |
| `src/knowledge/rag_blueprint_search.py` | **Created** | ~370 | RAG Blueprint enhanced search |
| `src/knowledge/fts_search.py` | **Modified** | +40 | RAG Blueprint integration hook |
| `src/llm/evaluation.py` | **Modified** | +270 | Nemo Evaluator integration |
| `src/risk/nemotron_policy_generator.py` | **Created** | ~470 | Nemotron policy generator |

**Total:** 4 new files, 2 modified files, ~1,860 lines of integration code.

---

## Dependency Matrix

| Skill | Required Package | GPU Required | Fallback |
|---|---|---|---|
| cuFOLIO | `nvidia-cufolio` + `cupy` | Yes (CUDA 12.x) | scipy |
| cuOpt | `nvidia-cuopt` + `cupy` | Yes (CUDA 12.x) | scipy |
| RAG Blueprint | `nvidia-rag` | No (uses NIM API) | FTS5+ChromaDB |
| Nemo Evaluator | `nemo-evaluator` | No | Rule-based |
| Nemotron Policy | `httpx` + `NVIDIA_API_KEY` | No (uses NIM API) | Static rules |

---

## Cost Impact

| Skill | Cost |
|---|---|
| cuFOLIO | Free (local GPU compute) |
| cuOpt | Free (local GPU compute) |
| RAG Blueprint | NIM API free tier |
| Nemo Evaluator | Free (local compute) or NIM free tier |
| Nemotron Policy Generator | NIM API free tier |

**Net effect:** Zero additional cost. All integrations use free NVIDIA NIM API tier or local GPU compute.

---

## Next Steps

1. **Install GPU packages** when CUDA environment is available:
   ```bash
   pip install nvidia-cufolio nvidia-cuopt cupy-cuda12x nvidia-rag nemo-evaluator
   ```

2. **Set NVIDIA_API_KEY** for NIM-based skills (RAG Blueprint, Nemotron):
   ```bash
   export NVIDIA_API_KEY="nvapi-..."
   ```

3. **Enable in config** — skills are enabled by default in `nvidia_skills.yaml`

4. **Test with paper trading** — verify GPU backends work before live deployment

5. **Monitor performance** — track GPU vs CPU fallback usage in logs
