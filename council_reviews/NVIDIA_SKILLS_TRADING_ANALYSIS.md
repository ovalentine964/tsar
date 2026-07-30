# NVIDIA Agent Skills — Trading & Finance Analysis for TSAR

**Analyst:** NVIDIA Skills Trading & Finance Analyst (Council Role)
**Date:** 2026-07-30
**Target:** TSAR (Trading Super Agent for Returns)
**Scope:** All NVIDIA agent skills applicable to trading, portfolio optimization, risk management, and financial analysis

---

## Executive Summary

NVIDIA's agent skills catalog (`npx skills add nvidia/skills`) contains **13 skills across two categories** directly applicable to TSAR's trading mission. The crown jewel is **cuFOLIO** — a purpose-built GPU-accelerated portfolio optimization toolkit. Supporting it are **8 cuOpt skills** (optimization engine) and **5 cuPyNumeric/cuDF skills** (data infrastructure). Together, they form a complete GPU-accelerated pipeline from market data ingestion → portfolio optimization → risk management → execution.

**Bottom line for TSAR:** These skills transform TSAR from a CPU-bound trading bot into a GPU-accelerated quantitative fund engine. The speed advantage is not incremental — it's **100-1000x** for portfolio optimization problems, enabling real-time rebalancing and multi-scenario stress testing that would take minutes or hours on CPU.

---

## PART I: DECISION OPTIMIZATION SKILLS (8 Skills)

---

### 1. cuFOLIO — GPU-Accelerated Mean-CVaR Portfolio Optimization

**Source:** `npx skills add nvidia/skills --skill cufolio`
**License:** Apache-2.0
**GitHub:** github.com/NVIDIA-AI-Blueprints/portfolio-optimization

#### What It Does
cuFOLIO is NVIDIA's **purpose-built portfolio optimization toolkit**. It:
- Computes log returns from price data
- Generates KDE (Kernel Density Estimation) scenarios on GPU
- Solves Mean-CVaR portfolio allocation using NVIDIA cuOpt GPU solver
- Traces the efficient frontier (25+ risk-aversion points)
- Backtests optimized portfolios against benchmarks
- Runs rebalancing workflows (schedule-based or drift-triggered)

It supports S&P 500, S&P 100, Dow 30, or custom ticker universes.

#### Why It Matters for TSAR
This is **the single most important NVIDIA skill for TSAR**. Here's why:

1. **CVaR > Variance for crypto:** Traditional Mean-Variance (Markowitz) optimization assumes normal distributions. Crypto returns are fat-tailed and skewed. CVaR (Conditional Value at Risk) measures the expected loss in the worst X% of scenarios — exactly what TSAR needs for downside protection on volatile crypto assets.

2. **Real-time rebalancing:** With $10 starting capital scaling to billions, TSAR needs to rebalance frequently. cuFOLIO's GPU solver can re-optimize a 50-asset portfolio in **milliseconds** vs. seconds/minutes on CPU.

3. **Efficient frontier exploration:** Instead of picking one risk level, TSAR can trace the full efficient frontier and dynamically select the optimal risk-return point based on current market conditions.

4. **Scenario generation:** KDE-based scenario generation on GPU allows TSAR to model thousands of market scenarios in real-time, capturing tail risks that parametric models miss.

#### How to Integrate
| TSAR Module | Integration Point |
|---|---|
| **Portfolio Manager** | Core allocation engine — replaces any CPU-based optimizer |
| **Risk Engine** | CVaR computation for position sizing and stop-loss levels |
| **Rebalancer** | Drift-triggered and schedule-based rebalancing |
| **Backtester** | Historical performance analysis against benchmarks |
| **Strategy Selector** | Efficient frontier to pick optimal risk level per regime |

#### When to Adopt
- **Phase 1 ($10-$100):** Study the code, understand the API, test on historical crypto data
- **Phase 2 ($100-$1K):** Active use for crypto portfolio optimization (BTC, ETH, SOL, etc.)
- **Phase 3 ($1K+):** Full integration with automated rebalancing

#### Cost
- **Software:** Free (Apache-2.0)
- **Hardware:** Requires NVIDIA GPU with Compute Capability ≥ 7.0 (Volta+). RTX 3060 or better recommended.
- **Cloud alternative:** NVIDIA DGX Spark or any GPU cloud instance (~$0.50-2/hr)

#### Installation
```bash
# Install the skill
npx skills add nvidia/skills --skill cufolio --yes

# Install the package (in a Python env with CUDA)
pip install cufolio
# Or via the blueprint repo:
# git clone https://github.com/NVIDIA-AI-Blueprints/portfolio-optimization
# cd portfolio-optimization && uv sync --extra cuda12
```

#### Key API Pattern
```python
import cvxpy as cp
from cufolio.cvar_parameters import CvarParameters
from cufolio import cvar_optimizer, cvar_utils
from cufolio.utils import download_data, calculate_returns

# Load price data (CSV with date index, ticker columns)
prices = pd.read_csv("crypto_prices.csv", index_col=0, parse_dates=True)
returns = calculate_returns(prices)

# Generate GPU-accelerated scenarios
scenario_data = cvar_utils.generate_cvar_data(returns, device="GPU")

# Configure CVaR optimization
cvar_params = CvarParameters(
    w_min=0.0, w_max=0.3,  # Max 30% per asset
    c_min=0.0, c_max=0.0,  # Fully invested (no cash)
    risk_aversion=1.0,
    confidence=0.95,  # 95% CVaR
)

# Solve with GPU
optimizer = cvar_optimizer.CVaR(returns_dict, cvar_params)
result = optimizer.solve(solver=cp.CUOPT, solver_method="PDLP")

# Result: optimal weights, expected return, CVaR
```

---

### 2. cuopt-install — cuOpt Installation

**Source:** `npx skills add nvidia/skills --skill cuopt-install --yes`

#### What It Does
Provides installation guidance for NVIDIA cuOpt — the GPU-accelerated optimization engine that powers cuFOLIO and all numerical optimization. Covers Python (pip/conda), C API, REST server, and Docker deployments.

#### Why It Matters for TSAR
cuOpt is the **engine under cuFOLIO's hood**. Without it, no GPU-accelerated optimization. This skill ensures TSAR's optimization stack is correctly installed and verified.

#### How to Integrate
- **Infrastructure layer:** Install once during TSAR environment setup
- **Verification:** Run smoke tests before deploying any optimization code

#### When to Adopt
**Immediately** — this is a prerequisite for cuFOLIO and all cuOpt skills.

#### Cost
- **Software:** Free
- **Hardware:** NVIDIA GPU with Compute Capability ≥ 7.0, CUDA 12.x or 13.x

#### Installation
```bash
npx skills add nvidia/skills --skill cuopt-install --yes

# Python (CUDA 12):
pip install --extra-index-url=https://pypi.nvidia.com 'cuopt-cu12==26.2.*'

# Verify:
python -c "import cuopt; print(cuopt.__version__)"
```

---

### 3. cuopt-numerical-optimization-api — LP/MILP/QP Solver API

**Source:** `npx skills add nvidia/skills --skill cuopt-numerical-optimization-api --yes`

#### What It Does
Provides the Python, C, and CLI API for solving **Linear Programming (LP)**, **Mixed-Integer Linear Programming (MILP)**, and **Quadratic Programming (QP)** problems using cuOpt's GPU solver. Also works as a backend for CVXPY, Pyomo, PuLP, AMPL, and GAMS.

#### Why It Matters for TSAR

1. **LP for position sizing:** "Allocate capital across N assets with constraints" is a classic LP problem. cuOpt solves it on GPU in milliseconds.

2. **MILP for discrete decisions:** "Which assets to include (binary) and how much to allocate (continuous)" — MILP handles the combinatorial selection problem.

3. **QP for variance minimization:** Portfolio variance is `w'Σw` (quadratic). cuOpt's QP solver minimizes this directly.

4. **Custom optimization:** Beyond portfolio optimization, TSAR can use cuOpt for:
   - Optimal trade execution (minimize market impact)
   - Tax-loss harvesting optimization
   - Constraint-based strategy selection
   - Risk budget allocation

#### How to Integrate
| TSAR Module | Use Case |
|---|---|
| **Position Sizer** | LP: maximize return subject to risk/capital constraints |
| **Asset Selector** | MILP: select optimal subset of assets (binary inclusion) |
| **Variance Minimizer** | QP: minimize portfolio variance `w'Σw` |
| **Trade Executor** | LP: minimize transaction costs and market impact |
| **Risk Budgeter** | LP: allocate risk budget across strategies |

#### When to Adopt
- **Phase 1 ($10-$100):** Learn the API, test simple LP problems
- **Phase 2 ($100-$1K):** Use for position sizing and basic optimization
- **Phase 3 ($1K+):** Full integration with custom constraints

#### Cost
Free (Apache-2.0). Requires NVIDIA GPU.

#### Installation
```bash
npx skills add nvidia/skills --skill cuopt-numerical-optimization-api --yes
# cuOpt installed via cuopt-install skill
```

#### Key API Pattern
```python
from cuopt import linear_programming as lp

# LP: Maximize return subject to constraints
problem = lp.Problem()
problem.set_objective_sense(lp.ObjectiveSense.MAXIMIZE)

# Variables: weight per asset (continuous, 0-1)
for i in range(n_assets):
    problem.add_variable(f"w_{i}", lower_bound=0.0, upper_bound=1.0)

# Constraint: weights sum to 1
problem.add_constraint(sum(vars) == 1.0)

# Constraint: max 20% per asset
for w in weights:
    problem.add_constraint(w <= 0.2)

# Objective: maximize expected return
problem.set_objective(sum(w_i * expected_return_i for w_i, expected_return_i in zip(weights, returns)))

# Solve on GPU
result = lp.solve(problem)
```

---

### 4. cuopt-multi-objective-exploration — Pareto Frontier Analysis

**Source:** `npx skills add nvidia/skills --skill cuopt-multi-objective-exploration --yes`

#### What It Does
Traces the **Pareto frontier** across competing objectives using repeated single-objective cuOpt solves. Supports both weighted-sum and ε-constraint methods. Shows where you can't improve one objective without hurting another.

#### Why It Matters for TSAR

This is **critical for TSAR's risk-return tradeoff decisions**:

1. **Return vs. Risk frontier:** TSAR doesn't just want "the optimal portfolio" — it wants to see the full spectrum of risk-return tradeoffs and pick the right one for current market conditions.

2. **Return vs. Drawdown:** Maximize return while constraining maximum drawdown — a classic multi-objective problem.

3. **Sharpe vs. Concentration:** Higher Sharpe ratios often require concentrated positions. The Pareto frontier shows exactly where concentration risk starts hurting risk-adjusted returns.

4. **Regime-adaptive allocation:** In high-volatility regimes, TSAR can shift to the conservative end of the Pareto frontier. In trending markets, shift to the aggressive end.

5. **Dual values as "exchange rates":** The ε-constraint method's dual values tell TSAR exactly how much return it gains per unit of risk it accepts — invaluable for dynamic position sizing.

#### How to Integrate
- **Strategy Selector:** Use Pareto frontier to select risk level based on market regime
- **Risk Manager:** ε-constrain drawdown, maximize return
- **Portfolio Optimizer:** Multi-objective optimization with return, risk, and liquidity

#### When to Adopt
- **Phase 2 ($100-$1K):** Basic two-objective (return vs. risk) frontier
- **Phase 3 ($1K+):** Full multi-objective with 3+ objectives

#### Cost
Free. Requires cuOpt (GPU).

#### Installation
```bash
npx skills add nvidia/skills --skill cuopt-multi-objective-exploration --yes
```

#### Key Insight for TSAR
> "Do not collapse a multi-objective problem to a single weighted number and report its optimum as 'the answer' — that silently makes the tradeoff decision for the user. Trace the frontier and let them choose."

This means TSAR should **always explore the Pareto frontier** rather than blindly optimizing a single metric. The frontier IS the strategy.

---

### 5. cuopt-numerical-optimization-formulation — Problem Formulation Guide

**Source:** `npx skills add nvidia/skills --skill cuopt-numerical-optimization-formulation --yes`

#### What It Does
Conceptual guide for formulating LP, MILP, and QP problems. Covers decision variables, objectives, constraints, and how to translate natural language problem descriptions into mathematical formulations. Includes sensitivity analysis (dual values, reduced costs).

#### Why It Matters for TSAR
TSAR needs to **formulate trading problems correctly** before solving them. This skill teaches:
- How to express "maximize return subject to risk constraints" as LP/QP
- How to add binary variables for "include/exclude" asset decisions (MILP)
- How to read dual values as marginal prices (shadow prices of constraints)
- How to identify implicit constraints in trading rules

**Key insight:** Dual values on constraints tell TSAR the **marginal value of relaxing each constraint** — e.g., "if I could increase my max position size from 20% to 21%, my expected return would increase by X basis points." This is pure alpha.

#### How to Integrate
- **Problem Translator:** Convert trading rules into mathematical formulations
- **Sensitivity Analyzer:** Use dual values to identify which constraints are binding
- **Strategy Designer:** Formulate new trading strategies as optimization problems

#### When to Adopt
**Immediately** — foundational knowledge for all optimization work.

#### Cost
Free. No GPU required (knowledge-only skill).

#### Installation
```bash
npx skills add nvidia/skills --skill cuopt-numerical-optimization-formulation --yes
```

---

### 6. cuopt-developer — cuOpt Developer Tools

**Source:** `npx skills add nvidia/skills --skill cuopt-developer --yes`

#### What It Does
Development environment for modifying, building, testing, and contributing to NVIDIA cuOpt itself. Covers C++/CUDA, Python bindings, server, and CI.

#### Why It Matters for TSAR
**Low priority for TSAR.** This is for contributing to cuOpt, not using it. However, if TSAR needs custom solver extensions or performance tuning at the cuOpt level, this skill provides the development workflow.

#### When to Adopt
**Phase 4+ ($10K+):** Only if TSAR needs custom cuOpt modifications.

#### Cost
Free. Requires CUDA development environment.

#### Installation
```bash
npx skills add nvidia/skills --skill cuopt-developer --yes
```

---

### 7. cuopt-routing-api-python — Vehicle Routing Optimization

**Source:** `npx skills add nvidia/skills --skill cuopt-routing-api-python --yes`

#### What It Does
Solves Vehicle Routing Problems (VRP), Traveling Salesman Problems (TSP), and Pickup-Delivery Problems (PDP) on GPU. Supports time windows, capacity constraints, precedence, and multi-depot routing.

#### Why It Matters for TSAR
**Indirect but relevant.** While TSAR doesn't route vehicles, the routing API's optimization patterns apply to:

1. **Trade execution routing:** Optimal order routing across multiple exchanges (Binance, Coinbase, DEXs) to minimize slippage and fees — analogous to VRP with time windows.

2. **Arbitrage path optimization:** Finding optimal sequences of trades across multiple markets — similar to TSP.

3. **Multi-strategy scheduling:** Optimal allocation of capital and attention across multiple trading strategies — capacity-constrained routing.

#### How to Integrate
- **Order Router:** Optimal execution routing across exchanges
- **Arbitrage Engine:** Path optimization for multi-hop arbitrage

#### When to Adopt
- **Phase 3 ($1K+):** For multi-exchange order routing
- **Phase 4 ($10K+):** For complex arbitrage path optimization

#### Cost
Free. Requires cuOpt (GPU).

#### Installation
```bash
npx skills add nvidia/skills --skill cuopt-routing-api-python --yes
```

---

### 8. cuopt-server-api-python — cuOpt REST Server

**Source:** `npx skills add nvidia/skills --skill cuopt-server-api-python --yes`

#### What It Does
Deploys cuOpt as a REST API server. Supports routing and LP/MILP problems via HTTP. Any language can call it.

#### Why It Matters for TSAR
Enables **microservice architecture** for TSAR's optimization:
- TSAR's trading engine (Python/Node) calls cuOpt via HTTP
- cuOpt server runs on a GPU machine, TSAR can run anywhere
- Enables scaling: multiple TSAR instances share one GPU optimizer
- Supports non-Python clients (if TSAR uses Go/Rust for execution)

#### How to Integrate
- **Optimization Microservice:** Deploy cuOpt server, TSAR calls it via REST
- **Multi-instance scaling:** Multiple TSAR strategies share one GPU optimizer

#### When to Adopt
- **Phase 3 ($1K+):** When TSAR needs distributed architecture
- **Phase 4 ($10K+):** When scaling to multiple strategies

#### Cost
Free. Requires GPU for server, any machine for client.

#### Installation
```bash
npx skills add nvidia/skills --skill cuopt-server-api-python --yes

# Start server:
docker run --gpus all -d -p 8000:8000 nvidia/cuopt:latest-cuda12.9-py3.13

# Or Python:
pip install --extra-index-url=https://pypi.nvidia.com cuopt-server-cu12 cuopt-sh-client
python -m cuopt_server.cuopt_service --ip 0.0.0.0 --port 8000
```

---

## PART II: DATA SCIENCE SKILLS (5 Skills)

---

### 9. accelerated-computing-cudf — GPU DataFrames (pandas on GPU)

**Source:** `npx skills add nvidia/skills --skill accelerated-computing-cudf --yes`
**License:** CC-BY-4.0 AND Apache-2.0

#### What It Does
NVIDIA cuDF provides **GPU-accelerated DataFrames** — a drop-in replacement for pandas that runs on GPU. Features:
- `cudf.pandas` accelerator: zero-code-change pandas acceleration
- Explicit cuDF API for full control
- dask-cuDF for datasets larger than GPU memory
- GPU-accelerated CSV/Parquet I/O, joins, groupby, rolling windows
- 100K+ row sweet spot for GPU speedup

#### Why It Matters for TSAR

**This is the data backbone for TSAR's entire pipeline.**

1. **Market data processing:** TSAR processes millions of candlestick records across hundreds of assets. cuDF accelerates this 10-100x over pandas.

2. **Feature engineering:** Technical indicators (RSI, MACD, Bollinger Bands) computed on rolling windows — cuDF's GPU rolling operations are dramatically faster.

3. **Real-time data pipeline:** Process live order book data, trade feeds, and market data streams on GPU without CPU bottlenecks.

4. **ETL for backtesting:** Loading, cleaning, and transforming years of historical data for backtesting — cuDF's Parquet I/O is 10x faster than pandas.

5. **Multi-asset correlation:** Computing correlation matrices across hundreds of assets — cuDF handles this on GPU.

#### How to Integrate
| TSAR Module | cuDF Use |
|---|---|
| **Data Ingestion** | GPU-accelerated CSV/Parquet loading |
| **Feature Engine** | Rolling window calculations (RSI, MACD, etc.) |
| **Correlation Matrix** | Asset correlation computation |
| **Backtester** | Historical data processing |
| **Live Data Pipeline** | Real-time order book and trade processing |

#### When to Adopt
- **Phase 1 ($10-$100):** Use `cudf.pandas` accelerator for zero-code-change speedup
- **Phase 2 ($100-$1K):** Explicit cuDF API for hot-path optimization
- **Phase 3 ($1K+):** dask-cuDF for multi-GPU, larger-than-memory datasets

#### Cost
- **Software:** Free (RAPIDS)
- **Hardware:** NVIDIA GPU with Compute Capability ≥ 7.0, CUDA 12.x

#### Installation
```bash
npx skills add nvidia/skills --skill accelerated-computing-cudf --yes

# conda (recommended):
conda install -c rapidsai -c conda-forge -c nvidia cudf

# Zero-code-change acceleration:
python -m cudf.pandas my_script.py
# Or in Jupyter:
# %load_ext cudf.pandas
# import pandas as pd  # now GPU-backed!
```

#### Key Insight for TSAR
> "Size gate: 100K rows minimum. Below that, GPU transfer overhead usually beats the speedup."

For TSAR's market data (typically millions of rows), cuDF is a clear win. For small lookups or config data, keep using pandas.

---

### 10. cupynumeric-hdf5 — HDF5 Data I/O on GPU

**Source:** `npx skills add nvidia/skills --skill cupynumeric-hdf5 --yes`

#### What It Does
Read and write large cuPyNumeric arrays to HDF5 files using Legate's parallel, distributed I/O. Each rank reads/writes its own tile in parallel. Supports GPUDirect Storage (GDS) for maximum I/O throughput.

#### Why It Matters for TSAR

1. **Historical data storage:** HDF5 is the standard format for large-scale financial time series. TSAR can store years of tick data, order books, and derived features in HDF5.

2. **Parallel loading:** When backtesting across multiple assets simultaneously, cuPyNumeric loads data in parallel across GPUs — no single-process bottleneck.

3. **GPUDirect Storage:** Bypass CPU entirely for data loading — data flows directly from NVMe SSD to GPU memory. Critical for high-frequency backtesting.

4. **Feature store:** Store pre-computed features (technical indicators, embeddings) in HDF5 for fast retrieval during live trading.

#### How to Integrate
- **Data Store:** Store historical market data in HDF5 format
- **Backtester:** Parallel loading of multi-asset historical data
- **Feature Store:** Pre-computed features for live trading

#### When to Adopt
- **Phase 2 ($100-$1K):** When TSAR has enough data to warrant HDF5 storage
- **Phase 3 ($1K+):** With GPUDirect Storage for high-frequency backtesting

#### Cost
Free. Requires cuPyNumeric + Legate + h5py.

#### Installation
```bash
npx skills add nvidia/skills --skill cupynumeric-hdf5 --yes

# Prerequisites:
conda install -c conda-forge h5py
conda install -c conda-forge -c legate cupynumeric
```

---

### 11. cupynumeric-install — cuPyNumeric Installation

**Source:** `npx skills add nvidia/skills --skill cupynumeric-install --yes`

#### What It Does
Installs and verifies cuPyNumeric — a GPU-accelerated NumPy replacement that scales across multiple GPUs and nodes via the Legate runtime.

#### Why It Matters for TSAR
cuPyNumeric is the **numerical compute layer** for TSAR's GPU pipeline. It provides:
- Drop-in NumPy replacement running on GPU
- Multi-GPU scaling for large array operations
- Distributed computing via Legate runtime

Key TSAR use cases:
- Matrix operations for covariance computation
- Linear algebra for factor models
- Statistical calculations across large datasets

#### When to Adopt
- **Phase 2 ($100-$1K):** Install alongside cuDF for numerical operations

#### Cost
Free. Requires NVIDIA GPU (CC ≥ 7.0), CUDA 12.2+.

#### Installation
```bash
npx skills add nvidia/skills --skill cupynumeric-install --yes

# conda:
conda create -n tsar-gpu -c conda-forge -c legate cupynumeric
conda activate tsar-gpu

# Verify:
legate -c "import cupynumeric as np; a = np.arange(10); print(a.sum())"
```

---

### 12. cupynumeric-migration-readiness — NumPy → cuPyNumeric Assessment

**Source:** `npx skills add nvidia/skills --skill cupynumeric-migration-readiness --yes`

#### What It Does
Pre-migration readiness assessor for porting NumPy code to cuPyNumeric. Inspects source code, classifies NumPy idioms by GPU scalability, and produces a verdict: READY, LIGHT REFACTOR, SIGNIFICANT REFACTOR, or NOT RECOMMENDED.

#### Why It Matters for TSAR
If TSAR has existing NumPy-based trading code, this skill tells TSAR **exactly what will scale on GPU and what needs refactoring** before committing to migration. Identifies:
- Unsupported APIs
- Scalar synchronization bottlenecks
- Host round-trips
- Python-heavy control flow
- Shape-dependent branching

#### How to Integrate
- **Migration Planner:** Assess existing TSAR code before GPU migration
- **Refactoring Guide:** Identify specific patterns that need changing

#### When to Adopt
- **Phase 1 ($10-$100):** Assess existing code before GPU migration
- **Phase 2 ($100-$1K):** Plan migration of hot-path code

#### Cost
Free. No GPU required (static analysis).

#### Installation
```bash
npx skills add nvidia/skills --skill cupynumeric-migration-readiness --yes
```

---

### 13. cupynumeric-parallel-data-load — Parallel Sharded Data Loading

**Source:** `npx skills add nvidia/skills --skill cupynumeric-parallel-data-load --yes`

#### What It Does
Loads sharded, on-disk datasets (sharded .npy, Parquet/Arrow, raw binary, custom layouts) into distributed cuPyNumeric arrays. Uses manual partition + Legate task launch for maximum parallelism. Handles per-shard row count differences.

#### Why It Matters for TSAR

1. **Multi-asset backtesting:** Load historical data for 100+ assets in parallel across GPUs — each GPU processes its own shard.

2. **Parquet data pipeline:** TSAR's market data is likely stored in Parquet (common for financial data). This skill handles parallel Parquet loading into GPU arrays.

3. **Distributed feature engineering:** Load and process data shards in parallel for feature computation.

#### How to Integrate
- **Data Loader:** Parallel loading for multi-asset datasets
- **Backtester:** Distributed data loading for large-scale backtests

#### When to Adopt
- **Phase 3 ($1K+):** When TSAR processes multi-asset datasets across multiple GPUs

#### Cost
Free. Requires cuPyNumeric + Legate.

#### Installation
```bash
npx skills add nvidia/skills --skill cupynumeric-parallel-data-load --yes
```

---

## PART III: INTEGRATION ARCHITECTURE

### TSAR GPU Pipeline with NVIDIA Skills

```
┌─────────────────────────────────────────────────────────────────┐
│                    TSAR GPU PIPELINE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ Market Data   │───▶│ cuDF/cuPyNum │───▶│ Feature      │      │
│  │ (Binance API) │    │ (GPU ETL)    │    │ Engineering  │      │
│  └──────────────┘    └──────────────┘    └──────┬───────┘      │
│                                                  │              │
│                                                  ▼              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ Trade        │◀───│ cuFOLIO      │◀───│ cuOpt        │      │
│  │ Execution    │    │ (Portfolio)  │    │ (Optimizer)  │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                    │                    │              │
│         ▼                    ▼                    ▼              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ Exchange     │    │ Backtester   │    │ Multi-Obj    │      │
│  │ API          │    │ (cuDF)       │    │ (Pareto)     │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐      │
│  │ Data Layer: HDF5 (cuPyNumeric) + Parquet (cuDF)      │      │
│  └──────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Skill Priority Matrix for TSAR

| Priority | Skill | Phase | Impact |
|:--------:|-------|:-----:|--------|
| 🔴 P0 | **cuFOLIO** | Phase 1 | Core portfolio optimization engine |
| 🔴 P0 | **cuopt-install** | Phase 1 | Prerequisite for all cuOpt skills |
| 🔴 P0 | **cuopt-numerical-optimization-api** | Phase 1 | LP/MILP/QP solver for all optimization |
| 🟠 P1 | **accelerated-computing-cudf** | Phase 1 | Data processing backbone |
| 🟠 P1 | **cuopt-numerical-optimization-formulation** | Phase 1 | Problem formulation knowledge |
| 🟠 P1 | **cuopt-multi-objective-exploration** | Phase 2 | Pareto frontier for risk-return |
| 🟡 P2 | **cupynumeric-install** | Phase 2 | Numerical compute layer |
| 🟡 P2 | **cupynumeric-migration-readiness** | Phase 2 | Migration planning |
| 🟡 P2 | **cuopt-server-api-python** | Phase 3 | Microservice architecture |
| 🟢 P3 | **cupynumeric-hdf5** | Phase 3 | Large-scale data storage |
| 🟢 P3 | **cupynumeric-parallel-data-load** | Phase 3 | Multi-GPU data loading |
| 🟢 P3 | **cuopt-routing-api-python** | Phase 3 | Order routing optimization |
| ⚪ P4 | **cuopt-developer** | Phase 4 | Custom cuOpt modifications |

---

## PART IV: CAPITAL MILESTONE ROADMAP

### Phase 1: $10 → $100 (Foundation)

**Skills to install:**
```bash
npx skills add nvidia/skills --skill cuopt-install --yes
npx skills add nvidia/skills --skill cuopt-numerical-optimization-api --yes
npx skills add nvidia/skills --skill cuopt-numerical-optimization-formulation --yes
npx skills add nvidia/skills --skill cufolio --yes
npx skills add nvidia/skills --skill accelerated-computing-cudf --yes
```

**What TSAR does:**
- Installs and verifies GPU optimization stack
- Uses cuFOLIO for crypto portfolio optimization (3-5 assets)
- Uses cuDF for market data processing
- Learns problem formulation patterns
- Backtests optimized portfolios against equal-weight benchmarks

**Hardware needed:** Any NVIDIA GPU with CC ≥ 7.0 (RTX 3060 or better)

### Phase 2: $100 → $1,000 (Scaling)

**Additional skills:**
```bash
npx skills add nvidia/skills --skill cuopt-multi-objective-exploration --yes
npx skills add nvidia/skills --skill cupynumeric-install --yes
npx skills add nvidia/skills --skill cupynumeric-migration-readiness --yes
```

**What TSAR does:**
- Expands to 10-20 crypto assets
- Traces Pareto frontier for risk-return optimization
- Implements multi-objective optimization (return vs. risk vs. liquidity)
- Migrates hot-path NumPy code to cuPyNumeric
- Dynamic regime-based allocation using Pareto frontier

### Phase 3: $1,000 → $10,000 (Production)

**Additional skills:**
```bash
npx skills add nvidia/skills --skill cuopt-server-api-python --yes
npx skills add nvidia/skills --skill cupynumeric-hdf5 --yes
npx skills add nvidia/skills --skill cupynumeric-parallel-data-load --yes
npx skills add nvidia/skills --skill cuopt-routing-api-python --yes
```

**What TSAR does:**
- Deploys cuOpt as microservice for multi-instance scaling
- Stores historical data in HDF5 with GPUDirect Storage
- Loads multi-asset datasets in parallel across GPUs
- Optimizes order routing across multiple exchanges
- Expands to Gold/Forex markets

### Phase 4: $10,000+ (Institutional)

**Additional skills:**
```bash
npx skills add nvidia/skills --skill cuopt-developer --yes
```

**What TSAR does:**
- Custom cuOpt solver extensions for proprietary strategies
- Multi-node GPU scaling with dask-cuDF
- Full institutional-grade optimization infrastructure

---

## PART V: COST ANALYSIS

### Software Costs

| Component | Cost | License |
|-----------|------|---------|
| cuFOLIO | Free | Apache-2.0 |
| cuOpt | Free | Apache-2.0 |
| cuDF (RAPIDS) | Free | Apache-2.0 |
| cuPyNumeric | Free | Apache-2.0 / CC-BY-4.0 |
| All NVIDIA Skills | Free | Apache-2.0 / CC-BY-4.0 |

**Total software cost: $0**

### Hardware Options

| Option | Cost | GPU | Best For |
|--------|------|-----|----------|
| Consumer GPU (RTX 3060) | ~$300 one-time | 12GB VRAM | Phase 1-2 |
| Consumer GPU (RTX 4070) | ~$500 one-time | 12GB VRAM | Phase 2-3 |
| Cloud GPU (A10G) | ~$0.50/hr | 24GB VRAM | Flexible scaling |
| Cloud GPU (A100) | ~$2/hr | 40/80GB VRAM | Phase 3-4 |
| NVIDIA DGX Spark | ~$3,000 | GB10 | Edge deployment |

### Total Cost of Ownership (Phase 1)

| Item | Monthly Cost |
|------|-------------|
| Software | $0 |
| Cloud GPU (4hrs/day) | ~$60 |
| **Total** | **~$60/month** |

Or with a one-time GPU purchase (~$300-500), monthly cost drops to just electricity (~$5-10).

---

## PART VI: COMPETITIVE ADVANTAGE

### Why GPU Optimization Matters for Trading

1. **Speed:** cuOpt solves LP problems **100-1000x faster** than CPU solvers (CPLEX, Gurobi). For a 50-asset portfolio, this means millisecond re-optimization vs. seconds.

2. **Scenario density:** GPU allows TSAR to evaluate **10,000+ scenarios** in the time CPU evaluates 100. Better risk estimation.

3. **Real-time rebalancing:** With GPU speed, TSAR can re-optimize on every price tick, not just hourly/daily.

4. **Multi-objective exploration:** GPU enables tracing the full Pareto frontier in real-time, not just picking one point.

5. **Backtesting throughput:** GPU-accelerated data processing allows backtesting across years of data in minutes, enabling rapid strategy iteration.

### TSAR's Edge

Most retail trading bots use CPU-based optimization with simple heuristics. TSAR with NVIDIA skills operates at **institutional-grade optimization speed** with:
- CVaR-based risk management (not just variance)
- Pareto frontier exploration (not single-point optimization)
- Real-time scenario generation (not historical-only)
- GPU-accelerated data pipeline (not CPU-bound ETL)

This is the same technology stack used by quantitative hedge funds, available for free.

---

## Appendix: Quick Reference Commands

```bash
# Install all trading-relevant NVIDIA skills at once:
npx skills add nvidia/skills --skill cuopt-install --yes
npx skills add nvidia/skills --skill cuopt-numerical-optimization-api --yes
npx skills add nvidia/skills --skill cuopt-numerical-optimization-formulation --yes
npx skills add nvidia/skills --skill cuopt-multi-objective-exploration --yes
npx skills add nvidia/skills --skill cuopt-routing-api-python --yes
npx skills add nvidia/skills --skill cuopt-server-api-python --yes
npx skills add nvidia/skills --skill cuopt-developer --yes
npx skills add nvidia/skills --skill cufolio --yes
npx skills add nvidia/skills --skill accelerated-computing-cudf --yes
npx skills add nvidia/skills --skill cupynumeric-install --yes
npx skills add nvidia/skills --skill cupynumeric-hdf5 --yes
npx skills add nvidia/skills --skill cupynumeric-migration-readiness --yes
npx skills add nvidia/skills --skill cupynumeric-parallel-data-load --yes

# Or install everything interactively:
npx skills add nvidia/skills
```

---

*Analysis complete. All 13 NVIDIA skills have been evaluated for TSAR's trading mission. The recommended Phase 1 stack (cuFOLIO + cuOpt + cuDF) provides institutional-grade GPU-accelerated portfolio optimization at zero software cost.*
