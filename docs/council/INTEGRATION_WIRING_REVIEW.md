# TSAR Integration Wiring Review

**Council:** Integration Review Board
**Date:** 2026-07-27
**Scope:** Phases 1A–4 new components wiring into existing TSAR architecture
**Components Reviewed:** 12 new files across `knowledge/`, `strategy/`, `risk/`

---

## Table of Contents

1. [Wiring Map](#1-wiring-map)
2. [Import Graph](#2-import-graph)
3. [Data Flow — The Full Flywheel](#3-data-flow--the-full-flywheel)
4. [Integration Gaps](#4-integration-gaps)
5. [Agent Integration Points](#5-agent-integration-points)
6. [Stream Integration](#6-stream-integration)
7. [Config Integration](#7-config-integration)
8. [Risk Integration — MandateGate + Risk Guardian](#8-risk-integration--mandategate--risk-guardian)
9. [Priority Wiring Order](#9-priority-wiring-order)
10. [Code Snippets — Key Wiring Points](#10-code-snippets--key-wiring-points)

---

## 1. Wiring Map

### 1.1 `fts_search.py` — MemoryRecall (FTS5 Unified Search)

| Connects To | Direction | Mechanism |
|---|---|---|
| `trade_memory.py` (TradeMemory) | Reads | Shares same SQLite DB (`tsar.db`); reads `trade_records` table + `trade_records_fts` FTS5 virtual table |
| `strategy_genomes.py` (StrategyGenomes) | Reads | Same DB; reads `strategy_genomes` + `strategy_genomes_fts` |
| `pattern_library.py` (PatternLibrary) | Reads | Same DB; reads `patterns` + `patterns_fts` |
| `lesson_archive.py` (LessonArchive) | Reads | Same DB; reads `lessons` + `lessons_fts` |
| `regime_state.py` (RegimeStateStore) | **NOT connected** | RegimeState is Redis/dict-backed, not in SQLite — no FTS index |

**Connection method:** Direct SQLite queries against shared `tsar.db`. The `_STORE_REGISTRY` dict in `fts_search.py` hardcodes 4 of 5 knowledge stores. RegimeState is excluded because it uses a dict/Redis backend, not SQLite.

**Gap:** RegimeState has no FTS5 index. If regime transition notes are stored in SQLite in the future, a 5th store entry would be needed.

---

### 1.2 `shadow_extractor.py` — ShadowExtractor

| Connects To | Direction | Mechanism |
|---|---|---|
| `trade_memory.py` (TradeMemory) | Reads | Calls `self._memory.list_trades(status="CLOSED", ...)` |
| `interfaces/llm_provider.py` (LLMProvider) | Calls | Calls `self._llm.generate(prompt, system, json_mode, temperature)` |
| `llm/prompts.py` | Reads | Calls `get_prompt("t3_shadow_rule_extraction", ...)` and `get_system_prompt("t3_shadow_rule_extraction")` |
| `knowledge/rule_validator.py` | Produces for | Returns `ExtractionResult` containing `TradingRule` objects → fed to `RuleValidator` |

**Connection method:** Constructor injection (`trade_memory`, `llm_provider`). No direct imports of concrete implementations.

---

### 1.3 `rule_validator.py` — RuleValidator

| Connects To | Direction | Mechanism |
|---|---|---|
| `knowledge/shadow_extractor.py` | Consumes | Takes `TradingRule` objects as input |
| `interfaces/exchange_gateway.py` (via OHLCVProvider protocol) | Reads | Calls `self._provider.get_candles(symbol, timeframe, limit)` |
| SQLite (`tsar.db`) | Writes | Creates `validated_rules` table, persists `ValidatedRule` objects |
| `knowledge/genome_mutator.py` | Produces for | Returns `ValidatedRule` objects → fed to `GenomeMutator` |

**Connection method:** Constructor injection (`ohlcv_provider` implementing `OHLCVProvider` protocol). The `OHLCVProvider` is a `Protocol` — any object with `get_candles()` satisfies it. The existing `ExchangeGateway` can be adapted.

---

### 1.4 `genome_mutator.py` — GenomeMutator

| Connects To | Direction | Mechanism |
|---|---|---|
| `knowledge/rule_validator.py` | Consumes | Takes `ValidatedRule` objects as input |
| `knowledge/strategy_genomes.py` (StrategyGenomes) | Reads + Writes | Calls `get_genome()`, `get_active_strategies()`, `list_genomes()`, `record_mutation()` |
| `agents/strategy_geneticist.py` | Produces for | Returns `MutationProposal` objects → Strategy Geneticist decides |

**Connection method:** Constructor injection (`strategy_genomes`). Calls `self._genomes.record_mutation(mutation)` to persist mutation proposals.

---

### 1.5 `backtest_engine.py` — BacktestEngine

| Connects To | Direction | Mechanism |
|---|---|---|
| `strategy/base.py` (BaseStrategy) | Consumes | Takes `BaseStrategy` instance; calls `check_entry()` and `check_exit()` |
| `interfaces/types.py` (OHLCV) | Reads | Takes `list[OHLCV]` as input data |
| `strategy/walk_forward.py` | Produces for | Returns `BacktestResult` → used by `WalkForwardValidator` |
| `strategy/monte_carlo.py` | Produces for | Returns `BacktestResult` → used by `MonteCarloSimulator` |

**Connection method:** Constructor injection (`strategy: BaseStrategy`). Pure computation — no external dependencies beyond numpy.

---

### 1.6 `walk_forward.py` — WalkForwardValidator

| Connects To | Direction | Mechanism |
|---|---|---|
| `strategy/backtest_engine.py` | Calls | Creates `BacktestEngine` instances per window; calls `engine.run()` |
| `strategy/base.py` (BaseStrategy) | Creates | Uses `strategy_factory` callable to create strategy instances |
| `interfaces/types.py` (OHLCV) | Reads | Takes `list[OHLCV]` as input |

**Connection method:** Constructor injection (`strategy_factory`, `optimize_fn`). Delegates all backtesting to `BacktestEngine`.

---

### 1.7 `monte_carlo.py` — MonteCarloSimulator

| Connects To | Direction | Mechanism |
|---|---|---|
| `strategy/backtest_engine.py` | Consumes | Takes `BacktestResult` as input; extracts `trades` tuple |

**Connection method:** Takes `BacktestResult` in `run()` method. Pure computation with numpy. No external dependencies.

---

### 1.8 `factors.py` — Factor Library (Pure Computations)

| Connects To | Direction | Mechanism |
|---|---|---|
| `strategy/factor_library.py` | Referenced by | `FACTOR_REGISTRY` dict is imported by `FactorLibrary` |
| pandas/numpy | Depends on | All factor functions take `pd.DataFrame` with OHLCV columns |

**Connection method:** Pure functions, no side effects. `FACTOR_REGISTRY` is a module-level dict mapping factor names to compute functions and metadata.

---

### 1.9 `factor_library.py` — FactorLibrary (Management & Persistence)

| Connects To | Direction | Mechanism |
|---|---|---|
| `strategy/factors.py` | Imports | `from src.strategy.factors import FACTOR_REGISTRY` |
| `strategy/factor_bench.py` | Produces for | `FactorBenchmarker` takes `FactorLibrary` instance |
| SQLite (factors.db or :memory:) | Reads + Writes | Creates `factors` and `ic_history` tables |

**Connection method:** Constructor takes `db_path`. Bootstraps from `FACTOR_REGISTRY` on init. Separate DB from `tsar.db` — uses its own SQLite file or in-memory.

---

### 1.10 `factor_bench.py` — FactorBenchmarker

| Connects To | Direction | Mechanism |
|---|---|---|
| `strategy/factor_library.py` | Calls | `self._lib.compute()`, `self._lib.list_factors()`, `self._lib.record_ic()` |
| `interfaces/types.py` (OHLCV via DataFrame) | Reads | Takes `pd.DataFrame` with OHLCV columns |

**Connection method:** Constructor injection (`library: FactorLibrary`). Calls library for computation and IC persistence.

---

### 1.11 `mandate.py` — Mandate (Human Authorization)

| Connects To | Direction | Mechanism |
|---|---|---|
| `interfaces/types.py` (Order, OrderSide, OrderType) | Reads | Uses `Order`, `OrderSide`, `OrderType` for validation |
| `config/mandate.yaml` | Reads + Writes | Persists state to YAML file |
| `risk/mandate_gate.py` | Used by | `MandateGate` wraps `Mandate` |

**Connection method:** Standalone class. Reads/writes YAML. Uses Pydantic models for validation. No constructor injection needed.

---

### 1.12 `mandate_gate.py` — MandateGate

| Connects To | Direction | Mechanism |
|---|---|---|
| `risk/mandate.py` (Mandate) | Wraps | `self._mandate = mandate or Mandate(config_path=config_path)` |
| `interfaces/types.py` (Signal, RiskDecision, VetoLevel) | Reads + Produces | Takes `Signal`, returns `RiskDecision` |
| `agents/risk_guardian.py` | **Must be wired into** | Sits BEFORE Risk Guardian in pipeline |
| `agents/orchestrator.py` | **Must be wired into** | Orchestrator calls MandateGate before Risk Guardian |

**Connection method:** Constructor injection (`mandate: Mandate`). Returns `RiskDecision` for pipeline compatibility.

---

## 2. Import Graph

### 2.1 Full Import Dependency Tree

```
fts_search.py
  └─ aiosqlite
  └─ src.utils.logging

shadow_extractor.py
  └─ src.interfaces.llm_provider (LLMProvider)
  └─ src.knowledge.trade_memory (TradeMemory, TradeRecord)
  └─ src.llm.prompts (get_prompt, get_system_prompt)
  └─ src.utils.logging

rule_validator.py
  └─ src.knowledge.shadow_extractor (TradingRule)
  └─ src.utils.logging

genome_mutator.py
  └─ src.knowledge.rule_validator (ValidatedRule)
  └─ src.knowledge.strategy_genomes (StrategyGenome, StrategyGenomes, StrategyMutation)
  └─ src.utils.logging

backtest_engine.py
  └─ src.interfaces.types (OHLCV)
  └─ src.strategy.base (BaseStrategy)
  └─ numpy

walk_forward.py
  └─ src.interfaces.types (OHLCV)
  └─ src.strategy.backtest_engine (BacktestConfig, BacktestEngine, BacktestMetrics, BacktestResult)
  └─ src.strategy.base (BaseStrategy)
  └─ numpy

monte_carlo.py
  └─ src.strategy.backtest_engine (BacktestResult, TradeRecord)
  └─ numpy

factors.py
  └─ numpy
  └─ pandas

factor_library.py
  └─ src.strategy.factors (FACTOR_REGISTRY)
  └─ pandas

factor_bench.py
  └─ src.strategy.factor_library (FactorLibrary)
  └─ numpy
  └─ pandas

mandate.py
  └─ src.interfaces.types (Order, OrderSide, OrderType)
  └─ pydantic
  └─ yaml

mandate_gate.py
  └─ src.interfaces.types (Order, OrderSide, OrderType, RiskDecision, Signal, VetoLevel)
  └─ src.risk.mandate (Mandate, MandateDecision)
```

### 2.2 Circular Import Analysis

**No circular imports detected.** The dependency graph is a DAG:

```
Level 0 (leaf):     factors.py, mandate.py, types.py
Level 1:            factor_library.py, mandate_gate.py, base.py
Level 2:            factor_bench.py, backtest_engine.py, fts_search.py
Level 3:            walk_forward.py, monte_carlo.py, shadow_extractor.py
Level 4:            rule_validator.py
Level 5:            genome_mutator.py
```

**Risk assessment:** LOW. The knowledge chain (`shadow_extractor → rule_validator → genome_mutator`) is linear. The strategy chain (`backtest → walk_forward/monte_carlo`) is linear. The factor chain (`factors → library → bench`) is linear. No cross-chain circular dependencies exist.

**One watch item:** `shadow_extractor.py` imports from `llm.prompts` and `interfaces.llm_provider`. If `llm.prompts` ever imports from `knowledge/`, a cycle would form. Currently safe.

---

## 3. Data Flow — The Full Flywheel

### 3.1 The Shadow Account Loop (Phases 1A–1B)

```
TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE
  │         │         │         │         │         │
  │         │         │         │         │         └─ Signal Scout uses mutated params
  │         │         │         │         └─ GenomeMutator proposes mutations
  │         │         │         └─ ShadowExtractor finds implicit rules
  │         │         └─ TradePhilosopher reflects on outcomes
  │         └─ TradeMemory records closed trades
  └─ Execution Sniper executes
```

**Detailed data flow:**

1. **Trade Execution:** `Execution Sniper` executes trades → `TradeMemory.insert_trade()` records them
2. **Trade Closure:** When trades close, `TradeMemory.close_trade()` records PnL, outcome grade, reflection
3. **Rule Extraction:** `ShadowExtractor.extract()`:
   - Reads closed trades from `TradeMemory.list_trades(status="CLOSED")`
   - Groups winners by (symbol, strategy_id)
   - Sends trade summaries to LLM via `LLMProvider.generate()`
   - Parses LLM JSON output into `TradingRule` objects
4. **Rule Validation:** `RuleValidator.validate()`:
   - Takes `TradingRule` from ShadowExtractor
   - Fetches OHLCV candles via `OHLCVProvider.get_candles()`
   - Replays rule against candle history (bar-by-bar)
   - Computes Sharpe, win rate, profit factor, max drawdown, p-value
   - Produces `ValidatedRule` with `validation_status: "passed"|"failed"`
5. **Genome Mutation:** `GenomeMutator.propose_mutations()`:
   - Takes `ValidatedRule` list from RuleValidator
   - Filters by quality thresholds (min_confidence, min_sharpe, etc.)
   - Finds matching `StrategyGenome` via `StrategyGenomes.get_genome()`
   - Creates `MutationProposal` with proposed entry/exit rule changes
   - Records `StrategyMutation` in `StrategyGenomes.record_mutation()`
6. **Strategy Evolution:** `Strategy Geneticist` (agent):
   - Receives `MutationProposal` via CloudEvents stream
   - Evaluates proposal (LLM-assisted or automated)
   - Accepts/rejects → updates `StrategyGenome` status
7. **Parameter Update:** If accepted, new params flow to `Signal Scout` via `tsar:strategy_mutations` stream

### 3.2 The Factor Discovery Loop (Phases 2–3)

```
OHLCV Data → FactorLibrary.compute_all() → FactorBenchmarker.run()
    │              │                              │
    │              │                              └─ IC/IR rankings, decay analysis
    │              └─ 28 factors computed per bar
    └─ Exchange Gateway provides historical data
```

**Detailed data flow:**

1. **Factor Computation:** `FactorLibrary.compute_all(ohlcv_df)`:
   - Iterates all 28 registered factors from `FACTOR_REGISTRY`
   - Each factor function takes a DataFrame, returns a Series
   - Returns DataFrame with one column per factor
2. **IC Benchmarking:** `FactorBenchmarker.run(ohlcv_df)`:
   - Computes forward returns from close prices
   - For each factor: rank-transform values, compute Spearman IC vs forward returns
   - Calculates IC mean, IC std, IR (IC_mean/IC_std), IC-positive ratio
   - Ranks factors by |IR| descending
   - Persists IC observations to `FactorLibrary.record_ic()`
3. **Factor Selection:** Top factors (by IR) can be used by:
   - `Signal Scout` for enhanced signal scoring
   - `Strategy Geneticist` for genome optimization
   - `BacktestEngine` for strategy parameter tuning

### 3.3 The Backtest Validation Pipeline (Phase 2)

```
Strategy → BacktestEngine.run(ohlcv) → BacktestResult
    │                                        │
    │         ┌──────────────────────────────┤
    │         │                              │
    │    WalkForwardValidator.run()    MonteCarloSimulator.run()
    │         │                              │
    │    WalkForwardResult              MonteCarloResult
    │    (overfitting_score,            (confidence_intervals,
    │     consistency_score)             probability_of_profit)
    │
    └─ BaseStrategy.check_entry() / check_exit()
```

### 3.4 The Mandate Gate (Phase 4)

```
Signal → [MandateGate.check()] → Risk Guardian → Execution Sniper
              │
              ├─ Paper mode? → BYPASS (always approved)
              ├─ Mandate ACTIVE? → Check rules
              │   ├─ Symbol allowed?
              │   ├─ Order type allowed?
              │   ├─ Side allowed?
              │   ├─ Leverage within limit?
              │   └─ Daily trade count within limit?
              └─ Mandate NOT active? → BLOCK ALL LIVE TRADES
```

---

## 4. Integration Gaps

### 4.1 Critical Gaps (Must Wire Before Production)

| # | Gap | Impact | Required Action |
|---|---|---|---|
| G1 | **ShadowExtractor has no orchestrator trigger** | The shadow extraction loop never runs automatically | Add periodic trigger in `Orchestrator.run_cycle()` or create a cron job |
| G2 | **RuleValidator.OHLCVProvider not implemented** | `OHLCVProvider` is a Protocol; no concrete implementation exists | Create adapter wrapping `ExchangeGateway.get_ohlcv()` |
| G3 | **GenomeMutator → StrategyGeneticist not connected** | MutationProposals are created but never consumed | Wire `MutationProposal` delivery via CloudEvents stream |
| G4 | **MandateGate not wired into pipeline** | Risk Guardian never calls MandateGate | Insert MandateGate check before `_evaluate_signal()` in RiskGuardian |
| G5 | **FactorLibrary not used by Signal Scout** | 28 factors exist but Signal Scout uses only 4 indicators | Update SignalScout to optionally use FactorLibrary factors |
| G6 | **BacktestEngine not used by Strategy Geneticist** | StrategyGeneticist has empty `run_cycle()` | Implement backtest-based strategy evaluation |
| G7 | **WalkForwardValidator not integrated** | Overfitting detection exists but is never called | Wire into strategy evaluation pipeline |
| G8 | **MonteCarloSimulator not integrated** | Confidence intervals exist but are never computed | Wire into strategy evaluation pipeline |
| G9 | **FactorBenchmarker not scheduled** | IC/IR benchmarks never run automatically | Add periodic benchmarking to analytics pipeline |
| G10 | **`config/mandate.yaml` does not exist** | Mandate defaults to DRAFT, blocks all trades | Create initial mandate config or provide setup wizard |

### 4.2 Non-Critical Gaps (Can Wire Incrementally)

| # | Gap | Impact | Required Action |
|---|---|---|---|
| G11 | FTS5 indexes may not exist in existing DB | `MemoryRecall._ensure_fts_tables()` handles this, but needs verification | Run migration or let `MemoryRecall.initialize()` create them |
| G12 | `validated_rules` table not in existing schema | RuleValidator creates it on first use, but should be in migration | Add to DB migration script |
| G13 | FactorLibrary uses separate DB | Two SQLite files (`tsar.db` and `factors.db`) | Decide: merge or keep separate? |
| G14 | No CloudEvents event type for shadow extraction results | Extraction results not broadcast | Add `tsar.shadow.extracted.v1` event type |
| G15 | No CloudEvents event type for mutation proposals | Proposals not broadcast to Strategy Geneticist | Add `tsar.strategy.proposal.v1` event type |

---

## 5. Agent Integration Points

### 5.1 Orchestrator — Needs Major Update

**Current state:** Manages 3 agents (SignalScout, RiskGuardian, ExecutionSniper). Runs health checks.

**Required changes:**
- Add `ShadowExtractor` lifecycle management (periodic trigger)
- Add `FactorBenchmarker` scheduling
- Add `WalkForwardValidator` / `MonteCarloSimulator` triggering after sufficient trade history
- Add mandate lifecycle management (load on start, expose commit/revoke API)

### 5.2 Signal Scout — Needs Moderate Update

**Current state:** Uses RSI, MACD, Bollinger Bands, S/R levels. 4 hardcoded indicator weights.

**Required changes:**
- Optionally integrate `FactorLibrary` for enhanced factor computation
- Consume `tsar:strategy_mutations` stream for parameter updates (already subscribes, partially wired)
- Use factor IC rankings to weight signal components

### 5.3 Risk Guardian — Needs MandateGate Integration

**Current state:** 10-point checklist, no mandate awareness.

**Required changes:**
- Add `MandateGate` as Check 0 (before Kill Switch)
- Pass `is_live` flag based on `trading_mode`
- If MandateGate rejects → skip all other checks, return immediately

### 5.4 Strategy Geneticist — Needs Complete Implementation

**Current state:** Empty `run_cycle()`. Stub agent.

**Required changes:**
- Implement `run_cycle()` using:
  - `BacktestEngine` for strategy evaluation
  - `WalkForwardValidator` for overfitting detection
  - `MonteCarloSimulator` for confidence intervals
  - `GenomeMutator` for mutation proposals
  - `FactorBenchmarker` for factor selection
- Subscribe to `tsar:strategy_proposals` stream for MutationProposals
- Publish accepted mutations to `tsar:strategy_mutations` stream

### 5.5 Trade Philosopher — No Changes Required

The Trade Philosopher already handles post-trade reflection. `ShadowExtractor` reads from the same `TradeMemory` data that Trade Philosopher writes to. No direct wiring needed.

### 5.6 Other Agents — No Changes Required

- **Execution Sniper:** Unaffected by new components
- **Regime Detector:** Unaffected (RegimeState is separate from new components)
- **Market Cartographer:** Unaffected
- **Execution Tracker:** Unaffected
- **Macro Agent:** Unaffected

---

## 6. Stream Integration

### 6.1 Existing Streams (14 streams)

Based on the pub/sub topology documented in `comms/events.py` and agent code:

| Stream | Publisher | Subscriber(s) |
|---|---|---|
| `signals` | Signal Scout | Risk Guardian |
| `risk_decisions` | Risk Guardian | Execution Sniper, Orchestrator |
| `trades` | Execution Sniper | Orchestrator |
| `health` | All agents | Orchestrator |
| `commands` | Orchestrator | All agents |
| `regime` | Regime Detector | Signal Scout, others |
| `strategy_mutations` | Strategy Geneticist | Signal Scout |
| `analytics` | (Various) | Strategy Geneticist |
| `fills` | Execution Engine | Strategy Geneticist, Execution Tracker |
| Others | — | — |

### 6.2 New Event Types Required

| Event Type | Publisher | Subscriber(s) | Data Payload |
|---|---|---|---|
| `tsar.shadow.extracted.v1` | ShadowExtractor (via Orchestrator) | Strategy Geneticist, Orchestrator | `{rules: [...], source_trade_count, winning_trade_count}` |
| `tsar.rule.validated.v1` | RuleValidator (via Orchestrator) | Strategy Geneticist | `{validated_rule: {...}, status, sharpe, win_rate}` |
| `tsar.strategy.proposal.v1` | GenomeMutator (via Strategy Geneticist) | Strategy Geneticist (evaluator), Orchestrator | `{proposal_id, genome_id, mutation_type, confidence, change_description}` |
| `tsar.mandate.committed.v1` | Mandate | Orchestrator, Risk Guardian | `{status, version, committed_by, symbols}` |
| `tsar.mandate.revoked.v1` | Mandate | Orchestrator, Risk Guardian | `{status, revoked_by, reason}` |
| `tsar.factor.benchmark.v1` | FactorBenchmarker | Strategy Geneticist | `{rankings: [...], forward_period, n_factors}` |

### 6.3 Stream Wiring Code

Add to `comms/events.py` or a new `comms/event_types.py`:

```python
# New event type constants
TSAR_SHADOW_EXTRACTED = "tsar.shadow.extracted.v1"
TSAR_RULE_VALIDATED = "tsar.rule.validated.v1"
TSAR_STRATEGY_PROPOSAL = "tsar.strategy.proposal.v1"
TSAR_MANDATE_COMMITTED = "tsar.mandate.committed.v1"
TSAR_MANDATE_REVOKED = "tsar.mandate.revoked.v1"
TSAR_FACTOR_BENCHMARK = "tsar.factor.benchmark.v1"
```

---

## 7. Config Integration

### 7.1 New Config File: `config/mandate.yaml`

**Required.** The `Mandate` class reads from `config/mandate.yaml` by default. Without it, the mandate defaults to `DRAFT` status and blocks all live trades.

```yaml
# config/mandate.yaml
rules:
  allowed_symbols:
    - "BTC/USDT"
    - "ETH/USDT"
  max_position_size_pct: 0.15
  max_daily_trades: 10
  max_leverage: 1.0
  allowed_order_types:
    - "market"
    - "limit"
  max_notional_per_trade: 10000.0
  allowed_sides:
    - "buy"
    - "sell"
status: "draft"
version: 1
notes: "Initial mandate — commit via /mandate commit <user_id>"
```

### 7.2 Config Additions to `config/tsar.yaml`

```yaml
# Additions to existing config/tsar.yaml

# Shadow Account Loop
shadow_extractor:
  enabled: true
  cycle_interval_hours: 24
  min_trades: 10
  min_win_rate: 0.55
  lookback_days: 90

# Rule Validation
rule_validator:
  timeframe: "1h"
  lookback_candles: 500
  min_sample_size: 20
  min_sharpe: 0.5

# Genome Mutation
genome_mutator:
  min_confidence: 0.6
  min_sharpe: 0.5
  min_win_rate: 0.45
  min_profit_factor: 1.1
  max_proposals_per_run: 5
  allow_new_genomes: false

# Factor Library
factor_library:
  db_path: "data/factors.db"  # or ":memory:" for ephemeral
  benchmark_interval_hours: 168  # weekly
  forward_periods: [1, 5, 10]
  rolling_window: 50

# Walk-Forward Validation
walk_forward:
  n_windows: 5
  train_ratio: 0.70
  overfit_threshold: 3.0

# Monte Carlo
monte_carlo:
  n_simulations: 1000
  confidence_levels: [5.0, 25.0, 50.0, 75.0, 95.0]

# Backtest Defaults
backtest:
  initial_capital: 100000.0
  position_size_pct: 0.10
  commission_bps: 10.0
  slippage_bps: 5.0
  risk_free_rate: 0.04
```

### 7.3 Config Additions to `config/risk.yaml`

```yaml
# Mandate Gate config
mandate_gate:
  enabled: true
  config_path: "config/mandate.yaml"
  paper_mode_exempt: true
```

### 7.4 `src/utils/config.py` — TSARConfig Extensions

Add new Pydantic models:

```python
class ShadowExtractorConfig(BaseModel):
    enabled: bool = Field(default=True)
    cycle_interval_hours: int = Field(default=24)
    min_trades: int = Field(default=10)
    min_win_rate: float = Field(default=0.55)
    lookback_days: int = Field(default=90)

class GenomeMutatorConfig(BaseModel):
    min_confidence: float = Field(default=0.6)
    min_sharpe: float = Field(default=0.5)
    max_proposals_per_run: int = Field(default=5)
    allow_new_genomes: bool = Field(default=False)

class FactorLibraryConfig(BaseModel):
    db_path: str = Field(default="data/factors.db")
    benchmark_interval_hours: int = Field(default=168)

class TSARConfig(BaseModel):
    # ... existing fields ...
    shadow_extractor: ShadowExtractorConfig = Field(default=ShadowExtractorConfig())
    genome_mutator: GenomeMutatorConfig = Field(default=GenomeMutatorConfig())
    factor_library: FactorLibraryConfig = Field(default=FactorLibraryConfig())
```

---

## 8. Risk Integration — MandateGate + Risk Guardian

### 8.1 Architecture

The MandateGate sits BEFORE the Risk Guardian's 7-layer veto protocol:

```
Signal → [MandateGate] → RiskGovernor (7 layers) → Execution
            │
            ├─ Paper mode? → BYPASS
            ├─ Mandate DRAFT/REVOKED? → HARD VETO
            └─ Mandate ACTIVE? → Check rules → PASS/FAIL
```

**Key design decision:** MandateGate returns a `RiskDecision` (same type as RiskGuardian) for seamless pipeline integration. The `VetoLevel` is `HARD` for mandate violations — cannot be overridden.

### 8.2 Integration with RiskGuardian

The MandateGate should be integrated into the RiskGuardian's `_evaluate_signal()` method. Here's the exact wiring:

```python
# In src/agents/risk_guardian.py — add to __init__:
def __init__(self, config, trading_mode="paper", **kwargs):
    super().__init__(config, trading_mode, **kwargs)
    # ... existing code ...

    # NEW: Mandate Gate
    from src.risk.mandate_gate import MandateGate
    mandate_config = config.get("risk", {}).get("mandate_gate", {})
    self._mandate_gate = MandateGate(
        config_path=mandate_config.get("config_path", "config/mandate.yaml")
    )
    self._is_live = trading_mode == "live"

# In src/agents/risk_guardian.py — add to _evaluate_signal():
async def _evaluate_signal(self, event):
    # ... parse signal ...

    # NEW: Check 0 — Mandate Gate (before all other checks)
    if self._is_live:
        mandate_decision = self._mandate_gate.check(
            signal,
            is_live=True,
            daily_trade_count=signal.metadata.get("daily_trade_count", 0),
        )
        if not mandate_decision.approved:
            logger.warning(
                "🔒 MANDATE GATE REJECTED: %s — %s",
                signal.signal_id, mandate_decision.rejection_reasons,
            )
            await self.publish_event(
                stream="risk_decisions",
                event_type="tsar.risk.vetoed.v1",
                data=self._decision_to_dict(mandate_decision, signal),
                priority=2,
                risk_level="HARD",
                trace_id=trace_id,
            )
            return

    # ... existing 10-point checklist continues ...
```

### 8.3 Mandate Lifecycle in Orchestrator

```python
# In src/agents/orchestrator.py — add mandate management:
async def on_initialize(self):
    # ... existing code ...

    # Load mandate
    from src.risk.mandate import Mandate
    self._mandate = Mandate(config_path="config/mandate.yaml")

    if self.trading_mode == "live" and not self._mandate.is_active:
        logger.warning(
            "⚠️ Mandate is %s — live trading will be blocked until committed",
            self._mandate.status.value,
        )

# Expose API for bot commands:
async def commit_mandate(self, user_id: str):
    self._mandate.commit(user_id)
    await self.publish_event(
        stream="commands",
        event_type="tsar.mandate.committed.v1",
        data={"status": "active", "version": self._mandate.version, "committed_by": user_id},
    )

async def revoke_mandate(self, user_id: str):
    self._mandate.revoke(user_id)
    await self.publish_event(
        stream="commands",
        event_type="tsar.mandate.revoked.v1",
        data={"status": "revoked", "revoked_by": user_id},
    )
```

### 8.4 Mandate vs RiskGuardian — Responsibility Matrix

| Check | MandateGate | RiskGuardian | Notes |
|---|---|---|---|
| Symbol authorization | ✅ | ❌ | Mandate owns allowed symbols |
| Position size limits | ❌ | ✅ | Risk engine owns sizing |
| Daily trade count | ✅ | ✅ | Both check (defense in depth) |
| Leverage limits | ✅ | ❌ | Mandate owns leverage caps |
| Kill switch | ❌ | ✅ | Risk engine owns kill switch |
| Circuit breaker | ❌ | ✅ | Risk engine owns drawdown |
| Stop-loss validation | ❌ | ✅ | Risk engine owns SL checks |
| Behavioral guards | ❌ | ✅ | Risk engine owns anti-patterns |
| R:R ratio | ❌ | ✅ | Risk engine owns R:R |
| Order type validation | ✅ | ❌ | Mandate owns allowed types |

---

## 9. Priority Wiring Order

### Phase 1: Foundation (Week 1) — Wire MandateGate

**Why first:** Safety-critical. Without mandate, live trading has no human authorization boundary.

```
1. Create config/mandate.yaml
2. Wire MandateGate into RiskGuardian._evaluate_signal()
3. Add mandate lifecycle to Orchestrator
4. Add /mandate commands to Telegram bot
5. Test: paper mode exempt, live mode blocked without commit
```

**Dependencies:** None. MandateGate is self-contained.

### Phase 2: Shadow Loop Core (Week 2) — Wire ShadowExtractor + RuleValidator

**Why second:** Core flywheel improvement loop. Enables the system to learn from trades.

```
1. Create OHLCVProvider adapter (wraps ExchangeGateway)
2. Wire ShadowExtractor into Orchestrator periodic cycle
3. Wire RuleValidator into extraction pipeline
4. Add tsar.shadow.extracted.v1 and tsar.rule.validated.v1 events
5. Test: extract rules from paper trades, validate against history
```

**Dependencies:** Requires TradeMemory with closed trades (existing).

### Phase 3: Genome Evolution (Week 3) — Wire GenomeMutator + StrategyGeneticist

**Why third:** Completes the shadow loop. Mutations flow from validated rules to strategy params.

```
1. Implement StrategyGeneticist.run_cycle()
2. Wire GenomeMutator into geneticist
3. Subscribe to tsar.strategy.proposal.v1 stream
4. Publish accepted mutations to tsar.strategy_mutations
5. Test: mutation proposal → acceptance → Signal Scout param update
```

**Dependencies:** Requires Phase 2 (ValidatedRule objects).

### Phase 4: Factor Infrastructure (Week 4) — Wire FactorLibrary + FactorBenchmarker

**Why fourth:** Enhances signal quality. Non-blocking improvement.

```
1. Initialize FactorLibrary (decide: tsar.db or separate DB)
2. Wire FactorBenchmarker into analytics pipeline
3. Optionally enhance SignalScout with factor scores
4. Add periodic benchmarking schedule
5. Test: factor computation, IC ranking, decay detection
```

**Dependencies:** None. Independent of other phases.

### Phase 5: Backtest Validation (Week 5) — Wire BacktestEngine + WalkForward + MonteCarlo

**Why last:** Quality assurance for strategies. Requires trade history to be meaningful.

```
1. Wire BacktestEngine into StrategyGeneticist
2. Wire WalkForwardValidator for overfitting detection
3. Wire MonteCarloSimulator for confidence intervals
4. Add backtest results to strategy evaluation gates
5. Test: full strategy evaluation pipeline
```

**Dependencies:** Requires Phase 3 (StrategyGeneticist implementation).

### Dependency Graph

```
Phase 1 (MandateGate)     ─────────────────────────────────────┐
                                                               │
Phase 2 (Shadow + Validator) ──→ Phase 3 (Mutator + Geneticist) ──→ Phase 5 (Backtest)
                                                               │
Phase 4 (Factors)         ─────────────────────────────────────┘
```

---

## 10. Code Snippets — Key Wiring Points

### 10.1 Orchestrator Calls MandateGate

```python
# src/agents/orchestrator.py — Add to on_initialize()

from src.risk.mandate import Mandate
from src.risk.mandate_gate import MandateGate

async def on_initialize(self) -> None:
    """Initialize all agents and start the trading pipeline."""
    logger.info("🏰 TSAR Orchestrator initializing (mode=%s)", self.trading_mode)

    # Load mandate (Phase 4 integration)
    self._mandate = Mandate(config_path="config/mandate.yaml")
    self._mandate_gate = MandateGate(mandate=self._mandate)

    if self.trading_mode == "live":
        if self._mandate.is_active:
            logger.info(
                "✅ Mandate ACTIVE: %d symbols, v%d, committed by %s",
                len(self._mandate.rules.allowed_symbols),
                self._mandate.version,
                self._mandate.committed_by,
            )
        else:
            logger.warning(
                "⚠️ Mandate is %s — ALL LIVE TRADES WILL BE BLOCKED. "
                "Commit the mandate via /mandate commit <user_id>",
                self._mandate.status.value,
            )

    # ... rest of existing initialization ...
```

### 10.2 Signal Scout Uses FactorLibrary

```python
# src/agents/signal_scout.py — Enhanced scoring with factors

from src.strategy.factor_library import FactorLibrary
from src.strategy.factor_bench import FactorBenchmarker
import pandas as pd

class SignalScout(BaseAgent):
    def __init__(self, config, trading_mode="paper", **kwargs):
        super().__init__(config, trading_mode, **kwargs)
        # ... existing init ...

        # NEW: Factor library integration
        factor_config = config.get("factor_library", {})
        if factor_config.get("enabled", False):
            self._factor_library = FactorLibrary(
                db_path=factor_config.get("db_path", ":memory:")
            )
            self._factor_benchmarker = FactorBenchmarker(self._factor_library)
            self._use_factors = True
        else:
            self._factor_library = None
            self._use_factors = False

    async def _scan_symbol(self, symbol: str) -> None:
        """Scan a single symbol for trading signals."""
        # ... existing OHLCV fetch and indicator calculation ...

        # NEW: Factor-enhanced scoring
        if self._use_factors and self._factor_library:
            ohlcv_df = pd.DataFrame([
                {"open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume}
                for b in ohlcv
            ])

            # Compute top factors
            factor_scores = self._compute_factor_scores(ohlcv_df)

            # Blend factor score into existing score
            score, score_breakdown = self._score_setup(
                rsi=rsi,
                current_price=current_price,
                sr_levels=sr_levels,
                volumes=volumes,
                macd=macd,
                ema_trend=ema_trend,
                side=signal_side,
            )

            # Factor adjustment (±20%)
            factor_adjustment = factor_scores.get("composite", 0.0)
            adjusted_score = score * (1.0 + 0.2 * factor_adjustment)
            adjusted_score = max(0.0, min(1.0, adjusted_score))
            score_breakdown["factors"] = factor_adjustment * 0.2
            score = adjusted_score

    def _compute_factor_scores(self, ohlcv_df: pd.DataFrame) -> dict[str, float]:
        """Compute factor-based signal adjustments."""
        try:
            # Compute key factors
            rsi_factor = self._factor_library.compute("rsi", ohlcv_df).iloc[-1]
            bb_factor = self._factor_library.compute("bb_pct_b", ohlcv_df).iloc[-1]
            mfi_factor = self._factor_library.compute("mfi", ohlcv_df).iloc[-1]
            adx_factor = self._factor_library.compute("adx", ohlcv_df).iloc[-1]

            # Normalize to [-1, 1] range
            rsi_signal = (rsi_factor - 50) / 50  # -1 (oversold) to +1 (overbought)
            bb_signal = (bb_factor - 0.5) * 2     # -1 (lower band) to +1 (upper band)

            # Composite: mean-reversion signals are contrarian
            composite = -(rsi_signal * 0.4 + bb_signal * 0.3 + (mfi_factor - 50) / 50 * 0.3)

            return {"composite": composite, "rsi": rsi_factor, "bb": bb_factor}
        except Exception as e:
            logger.warning("Factor computation failed: %s", e)
            return {"composite": 0.0}
```

### 10.3 ShadowExtractor Orchestrator Integration

```python
# src/agents/orchestrator.py — Add shadow extraction cycle

from src.knowledge.shadow_extractor import ShadowExtractor
from src.knowledge.rule_validator import RuleValidator
from src.knowledge.genome_mutator import GenomeMutator, MutatorConfig

class Orchestrator(BaseAgent):
    def __init__(self, config, trading_mode="paper", **kwargs):
        super().__init__(config, trading_mode, **kwargs)
        # ... existing init ...

        # Shadow loop components (initialized in on_initialize)
        self._shadow_extractor = None
        self._rule_validator = None
        self._genome_mutator = None
        self._last_shadow_extraction = 0

    async def on_initialize(self) -> None:
        # ... existing code ...

        # Initialize shadow loop (Phase 1B integration)
        shadow_config = self.config.get("shadow_extractor", {})
        if shadow_config.get("enabled", False):
            from src.knowledge.trade_memory import TradeMemory
            from src.interfaces import get_llm_provider, get_exchange_gateway

            db_path = self.config.get("database", {}).get("db_path", "data/tsar.db")
            trade_memory = TradeMemory(db_path)
            llm_provider = get_llm_provider()

            self._shadow_extractor = ShadowExtractor(
                trade_memory=trade_memory,
                llm_provider=llm_provider,
            )

            # OHLCV provider adapter
            gateway = get_exchange_gateway()
            ohlcv_adapter = OHLCVProviderAdapter(gateway)
            self._rule_validator = RuleValidator(
                ohlcv_provider=ohlcv_adapter,
                db_path=db_path,
            )

            from src.knowledge.strategy_genomes import StrategyGenomes
            genomes = StrategyGenomes(db_path)
            self._genome_mutator = GenomeMutator(
                strategy_genomes=genomes,
                config=MutatorConfig(
                    min_confidence=shadow_config.get("min_confidence", 0.6),
                    max_proposals_per_run=shadow_config.get("max_proposals", 5),
                ),
            )

            logger.info("🔄 Shadow extraction loop initialized")

    async def run_cycle(self) -> None:
        # ... existing health monitoring ...

        # Shadow extraction cycle (runs every N hours)
        if self._shadow_extractor:
            shadow_interval = self.config.get("shadow_extractor", {}).get(
                "cycle_interval_hours", 24
            ) * 3600
            now = time.monotonic()
            if now - self._last_shadow_extraction >= shadow_interval:
                self._last_shadow_extraction = now
                await self._run_shadow_extraction()

    async def _run_shadow_extraction(self) -> None:
        """Run the full shadow extraction → validation → mutation pipeline."""
        logger.info("🔄 Starting shadow extraction cycle...")

        try:
            # Step 1: Extract rules from trade history
            extraction = await self._shadow_extractor.extract(
                min_trades=self.config.get("shadow_extractor", {}).get("min_trades", 10),
            )
            if not extraction.rules:
                logger.info("Shadow extraction: no rules found")
                return

            logger.info(
                "Shadow extraction: %d rules from %d trades (%d winners)",
                len(extraction.rules), extraction.source_trade_count,
                extraction.winning_trade_count,
            )

            # Step 2: Validate rules via backtest
            validated = await self._rule_validator.validate_batch(extraction.rules)
            passed = [r for r in validated if r.validation_status == "passed"]
            logger.info(
                "Rule validation: %d/%d passed",
                len(passed), len(validated),
            )

            if not passed:
                return

            # Step 3: Propose genome mutations
            proposals = await self._genome_mutator.propose_mutations(passed)
            logger.info(
                "Genome mutations: %d proposals from %d validated rules",
                len(proposals), len(passed),
            )

            # Step 4: Publish proposals for Strategy Geneticist
            for proposal in proposals:
                await self.publish_event(
                    stream="strategy_mutations",
                    event_type="tsar.strategy.proposal.v1",
                    data=proposal.to_dict(),
                    priority=2,
                    agent_role="ANALYSIS",
                )

        except Exception as e:
            logger.error("Shadow extraction cycle failed: %s", e)


# OHLCV Provider Adapter
class OHLCVProviderAdapter:
    """Adapter: ExchangeGateway → OHLCVProvider protocol."""

    def __init__(self, gateway):
        self._gateway = gateway

    async def get_candles(self, symbol, timeframe="1h", limit=500, since=None):
        from src.interfaces.types import Timeframe
        tf_map = {"1h": Timeframe.H1, "4h": Timeframe.H4, "1d": Timeframe.D1}
        tf = tf_map.get(timeframe, Timeframe.H1)
        ohlcv_list = await self._gateway.get_ohlcv(symbol, tf, limit=limit)
        from src.knowledge.rule_validator import OHLCVCandle
        return [
            OHLCVCandle(
                timestamp=str(b.timestamp),
                open=b.open, high=b.high,
                low=b.low, close=b.close,
                volume=b.volume,
            )
            for b in ohlcv_list
        ]
```

### 10.4 StrategyGeneticist Full Implementation

```python
# src/agents/strategy_geneticist.py — Full implementation

from src.strategy.backtest_engine import BacktestEngine, BacktestConfig
from src.strategy.walk_forward import WalkForwardValidator, WalkForwardConfig
from src.strategy.monte_carlo import MonteCarloSimulator, MonteCarloConfig
from src.knowledge.genome_mutator import GenomeMutator
from src.strategy.factor_bench import FactorBenchmarker
from src.strategy.factor_library import FactorLibrary

class StrategyGeneticist(BaseAgent):
    """Evolve strategies via backtest, walk-forward, Monte Carlo, and factor analysis."""

    AGENT_NAME = "strategy_geneticist"
    ROLE = "ANALYSIS"

    PUBLISH_STREAM = "strategy_mutations"
    SUBSCRIBE_STREAMS = ["analytics", "regime", "fills", "strategy_proposals"]

    def __init__(self, config, trading_mode="paper", **kwargs):
        super().__init__(config, trading_mode, **kwargs)
        self._config = config

        # Components initialized in on_initialize
        self._backtest_engine = None
        self._walk_forward = None
        self._monte_carlo = None
        self._genome_mutator = None
        self._factor_benchmarker = None

    async def on_initialize(self):
        """Initialize backtest and analysis components."""
        from src.knowledge.strategy_genomes import StrategyGenomes
        from src.strategy.mean_reversion import MeanReversionStrategy

        db_path = self._config.get("database", {}).get("db_path", "data/tsar.db")
        self._genomes = StrategyGenomes(db_path)

        # Factor library
        factor_config = self._config.get("factor_library", {})
        self._factor_library = FactorLibrary(
            db_path=factor_config.get("db_path", ":memory:")
        )
        self._factor_benchmarker = FactorBenchmarker(self._factor_library)

        # Monte Carlo
        mc_config = self._config.get("monte_carlo", {})
        self._monte_carlo = MonteCarloSimulator(
            config=MonteCarloConfig(
                n_simulations=mc_config.get("n_simulations", 1000),
            )
        )

        # Genome mutator
        self._genome_mutator = GenomeMutator(
            strategy_genomes=self._genomes,
        )

        logger.info("Strategy Geneticist initialized")

    async def handle_event(self, stream, event):
        """Handle incoming events."""
        if stream == "strategy_proposals" and event.type == "tsar.strategy.proposal.v1":
            await self._evaluate_proposal(event.data)

    async def run_cycle(self):
        """Periodic strategy evaluation."""
        # Evaluate active strategies
        active = self._genomes.get_active_strategies()
        for genome in active:
            await self._evaluate_strategy(genome)

    async def _evaluate_strategy(self, genome):
        """Evaluate a strategy with backtest + walk-forward + Monte Carlo."""
        from src.strategy.mean_reversion import MeanReversionStrategy

        strategy = MeanReversionStrategy()  # TODO: build from genome params

        # Get OHLCV data for backtesting
        # (would need gateway access — omitted for brevity)

        # Run backtest
        # result = backtest_engine.run(ohlcv_data)

        # Run walk-forward
        # wf_result = walk_forward.run(ohlcv_data)
        # if wf_result.is_overfit:
        #     logger.warning("Strategy %s is overfit! Score: %.2f", genome.name, wf_result.overfitting_score)

        # Run Monte Carlo
        # mc_result = monte_carlo.run(result)
        # if mc_result.probability_of_ruin > 0.1:
        #     logger.warning("Strategy %s has high ruin probability: %.2f", genome.name, mc_result.probability_of_ruin)

        # Update genome stats
        # self._genomes.update_genome_stats(genome.strategy_id, ...)

    async def _evaluate_proposal(self, proposal_data):
        """Evaluate a mutation proposal from GenomeMutator."""
        proposal_id = proposal_data.get("proposal_id", "unknown")
        logger.info("Evaluating mutation proposal: %s", proposal_id)

        # Decision logic: accept if confidence > threshold
        confidence = proposal_data.get("confidence_score", 0.0)
        if confidence > 0.7:
            # Accept: update genome
            genome_id = proposal_data.get("target_genome_id")
            if genome_id:
                self._genomes.update_genome(
                    genome_id,
                    entry_rules=proposal_data.get("proposed_entry_rules"),
                    exit_rules=proposal_data.get("proposed_exit_rules"),
                    last_evolved=_utcnow_iso(),
                )
                self._genomes.update_status(genome_id, "live")

                # Publish mutation
                await self.publish_event(
                    stream="strategy_mutations",
                    event_type="tsar.strategy.mutated.v1",
                    data={
                        "genome_id": genome_id,
                        "proposal_id": proposal_id,
                        "confidence": confidence,
                    },
                )
```

### 10.5 RiskGuardian MandateGate Integration

```python
# src/agents/risk_guardian.py — MandateGate integration (minimal diff)

class RiskGuardian(BaseAgent):
    def __init__(self, config, trading_mode="paper", **kwargs):
        super().__init__(config, trading_mode, **kwargs)
        # ... existing code ...

        # NEW: Mandate Gate (Phase 4)
        from src.risk.mandate_gate import MandateGate
        mandate_config = config.get("risk", {}).get("mandate_gate", {})
        if mandate_config.get("enabled", True):
            self._mandate_gate = MandateGate(
                config_path=mandate_config.get("config_path", "config/mandate.yaml")
            )
        else:
            self._mandate_gate = None

    async def _evaluate_signal(self, event):
        data = event.data
        trace_id = event.traceid

        signal = Signal(
            signal_id=data["signal_id"],
            symbol=data["symbol"],
            side=OrderSide(data["side"]),
            score=data["score"],
            entry_price=data["entry_price"],
            stop_loss=data["stop_loss"],
            take_profit=data["take_profit"],
            strategy=data.get("strategy", "unknown"),
            reasoning=data.get("reasoning", ""),
            metadata=data.get("metadata", {}),
        )

        # ── Check 0: Mandate Gate (NEW) ──────────────────────
        if self._mandate_gate and self.trading_mode == "live":
            mandate_decision = self._mandate_gate.check(
                signal,
                is_live=True,
                daily_trade_count=signal.metadata.get("daily_trade_count", 0),
            )
            if not mandate_decision.approved:
                logger.warning(
                    "🔒 MANDATE GATE REJECTED [%s]: %s %s — %s",
                    mandate_decision.veto_level,
                    signal.signal_id,
                    signal.symbol,
                    mandate_decision.rejection_reasons,
                )
                event_type = "tsar.risk.vetoed.v1"
                await self.publish_event(
                    stream="risk_decisions",
                    event_type=event_type,
                    data=self._decision_to_dict(mandate_decision, signal),
                    priority=2,
                    risk_level="HARD",
                    trace_id=trace_id,
                )
                return

        # ── Existing 10-point checklist continues ─────────────
        decision = self._run_all_checks(signal)
        # ... rest of existing code ...
```

---

## Summary

### Wiring Completeness Matrix

| Component | Imports | Constructor Wired | Agent Integrated | Stream Events | Config Added | Tests |
|---|---|---|---|---|---|---|
| MemoryRecall (FTS) | ✅ | ⚠️ Manual | ❌ Not triggered | N/A | ❌ | ❌ |
| ShadowExtractor | ✅ | ⚠️ Manual | ❌ No trigger | ❌ No events | ❌ | ❌ |
| RuleValidator | ✅ | ⚠️ Manual | ❌ No trigger | ❌ No events | ❌ | ❌ |
| GenomeMutator | ✅ | ⚠️ Manual | ❌ No consumer | ❌ No events | ❌ | ❌ |
| BacktestEngine | ✅ | ✅ Self-contained | ❌ Not used | N/A | ❌ | ❌ |
| WalkForwardValidator | ✅ | ✅ Self-contained | ❌ Not used | N/A | ❌ | ❌ |
| MonteCarloSimulator | ✅ | ✅ Self-contained | ❌ Not used | N/A | ❌ | ❌ |
| FactorLibrary | ✅ | ⚠️ Manual | ❌ Not used | N/A | ❌ | ❌ |
| FactorBenchmarker | ✅ | ⚠️ Manual | ❌ Not scheduled | ❌ No events | ❌ | ❌ |
| Mandate | ✅ | ⚠️ Manual | ❌ Not loaded | ❌ No events | ❌ No YAML | ❌ |
| MandateGate | ✅ | ⚠️ Manual | ❌ Not wired | N/A | ❌ | ❌ |

**Legend:** ✅ Done | ⚠️ Partially | ❌ Not done

### Critical Path

1. **Create `config/mandate.yaml`** — Without this, MandateGate blocks everything
2. **Wire MandateGate into RiskGuardian** — Safety-critical for live trading
3. **Create OHLCVProvider adapter** — Unblocks RuleValidator
4. **Wire ShadowExtractor into Orchestrator** — Starts the learning loop
5. **Implement StrategyGeneticist.run_cycle()** — Completes the evolution loop

### Risk Assessment

- **No circular import risks** — dependency graph is a clean DAG
- **No breaking changes** to existing code — all new components are additive
- **One config file missing** — `config/mandate.yaml` must be created
- **All new components are constructor-injectable** — easy to test and wire
- **Factor library uses separate DB** — decision needed on consolidation

---

*End of Integration Wiring Review*
