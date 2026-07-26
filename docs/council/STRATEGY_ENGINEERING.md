# STRATEGY ENGINEERING REQUIREMENTS
## Council Directive — Chief Strategist

**Version:** 1.0.0
**Date:** 2026-07-24
**Authority:** TSAR Council — Chief Strategist
**Status:** MANDATORY — Strategy Builder Agent must implement all requirements below
**References:**
- `TSAR_ARCHITECTURE.md` v3.0.0 §7 (Strategy Architecture), §4 (Knowledge Stores), §9 (Improvement Measurement)
- `FIX_E_STRATEGY.md` — All 8 fixes (E1–E8)

---

## 1. STRATEGY GENOME FORMAT

Every strategy in TSAR is defined by a **Strategy Genome** — a versioned, mutable YAML document stored in `strategy_genomes` (SQLite). The genome encodes everything: thesis, entry/exit rules, parameters, risk constraints, and regime affinities.

### 1.1 Canonical YAML Schema

```yaml
# Strategy Genome — Canonical Format v1
# Stored in: strategy_genomes table (entry_rules, exit_rules, risk_params as JSON)
# File location: strategies/genomes/{name}_v{version}.yaml

genome:
  # ── Identity (IMMUTABLE after creation) ──
  name: "mean_reversion"                    # Unique, snake_case
  version: "1.0.0"                          # SemVer
  thesis: >-
    BTC mean-reverts after RSI extremes.
    Buy oversold, sell overbought.
    Works in ranging regimes (~60% of time).
  created_at: "2026-07-24T05:30:00Z"
  parent_version: null                      # null for Day1 originals

  # ── Entry Rules (MUTABLE — subject to evolution) ──
  entry_rules:
    type: "mean_reversion"                  # mean_reversion | momentum
    direction: "both"                       # long | short | both
    conditions:
      - indicator: "rsi"
        period: 14
        threshold: 30                       # RSI < 30 for long entry
        operator: "lt"                      # lt | gt | eq | lte | gte | between
        weight: 0.25                        # Contribution to signal score

      - indicator: "support_resistance"
        lookback_periods: 48
        proximity_pct: 2.0                  # Within 2% of support
        operator: "near"
        weight: 0.20

      - indicator: "volume"
        lookback_periods: 20
        multiplier: 1.5                     # Volume > 1.5x average
        operator: "gt"
        weight: 0.10

      - indicator: "fear_greed"
        threshold: 30
        operator: "lt"
        weight: 0.15

      - indicator: "funding_rate"
        threshold: -0.0005                  # Crowded short → contrarian long
        operator: "lt"
        weight: 0.20

      - indicator: "adx"
        period: 14
        threshold: 25
        operator: "lt"                      # ADX < 25 = ranging (for MR)
        weight: 0.10

    min_signal_score: 0.6                   # Minimum weighted score to generate signal
    regime_filter:
      allowed: ["ranging", "low_volatility"]
      blocked: ["trending_up", "trending_down", "transition"]

  # ── Exit Rules (MUTABLE — subject to evolution) ──
  exit_rules:
    take_profit:
      method: "indicator"                   # indicator | fixed_pct | atr_multiple
      indicator: "rsi"
      threshold: 70                         # RSI > 70
      operator: "gt"
      fallback_pct: 2.0                     # OR +2% from entry

    stop_loss:
      method: "fixed_pct"                   # fixed_pct | atr_multiple | indicator
      pct: 1.0                              # -1% from entry (hard)

    trailing_stop:
      enabled: false
      method: "atr_multiple"
      atr_multiplier: 1.5

    time_stop:
      enabled: true
      max_hours: 4                          # Close after 4h if no TP/SL hit

    funding_rate_flip:
      enabled: true                         # Close if funding rate reverses sign

  # ── Risk Parameters (MUTABLE — subject to evolution) ──
  risk_params:
    max_position_pct: 15.0                  # % of capital
    risk_per_trade_pct: 2.0                 # % of capital at risk
    min_risk_reward: 2.0                    # Minimum R:R ratio
    sl_atr_multiple: 1.5                    # Stop-loss as ATR multiple
    tp_rr_ratio: 2.0                        # Take-profit as R:R multiple
    cooldown_minutes: 30                    # Same-symbol cooldown

  # ── Regime Performance (AUTO-UPDATED by Strategy Geneticist) ──
  regime_performance:
    trending_up:
      sharpe: null                          # Updated after sufficient trades
      win_rate: null
      trade_count: 0
      status: "blacklisted"                 # active | paused | blacklisted
    trending_down:
      sharpe: null
      win_rate: null
      trade_count: 0
      status: "blacklisted"
    ranging:
      sharpe: 0.89                          # Example: Day1 frozen baseline
      win_rate: 0.56
      trade_count: 0
      status: "active"
    volatile:
      sharpe: null
      win_rate: null
      trade_count: 0
      status: "paused"
    low_volatility:
      sharpe: null
      win_rate: null
      trade_count: 0
      status: "active"
    transition:
      sharpe: null
      win_rate: null
      trade_count: 0
      status: "paused"                      # Reduced position sizing in Transition

  # ── Metadata (IMMUTABLE + AUTO) ──
  status: "ACTIVE"                          # ACTIVE | PAUSED | RETIRED
  allocation_pct: 50.0                      # Portfolio allocation (Day1: equal weight)
  total_trades: 0
  last_evolved: null
  last_backtest_sharpe: null
  last_walk_forward_passed: null
```

### 1.2 Required Fields

These fields are **mandatory** for every strategy genome. The strategy builder agent must not produce a genome missing any of them.

| Field | Type | Description |
|-------|------|-------------|
| `genome.name` | string | Unique identifier, snake_case |
| `genome.version` | string | SemVer format |
| `genome.thesis` | string | Human-readable thesis (2-3 sentences) |
| `genome.entry_rules.type` | enum | `mean_reversion` or `momentum` |
| `genome.entry_rules.direction` | enum | `long`, `short`, or `both` |
| `genome.entry_rules.conditions[]` | list | At least 3 conditions with indicator, threshold, operator, weight |
| `genome.entry_rules.conditions[].indicator` | string | Must reference a calculable indicator |
| `genome.entry_rules.conditions[].threshold` | float | Numeric threshold |
| `genome.entry_rules.conditions[].operator` | enum | `lt`, `gt`, `eq`, `lte`, `gte`, `between`, `near` |
| `genome.entry_rules.conditions[].weight` | float | 0-1, all weights must sum to 1.0 |
| `genome.entry_rules.min_signal_score` | float | 0-1 minimum weighted score |
| `genome.entry_rules.regime_filter` | object | `allowed` and `blocked` lists of regime states |
| `genome.exit_rules.take_profit` | object | Method and parameters |
| `genome.exit_rules.stop_loss` | object | Method and parameters (MANDATORY — no strategy without stop-loss) |
| `genome.risk_params.max_position_pct` | float | ≤ 15 (canonical max) |
| `genome.risk_params.risk_per_trade_pct` | float | ≤ 2 (canonical max) |
| `genome.risk_params.min_risk_reward` | float | ≥ 2.0 (canonical min) |
| `genome.regime_performance` | object | All 6 regimes must be present |
| `genome.status` | enum | `ACTIVE`, `PAUSED`, or `RETIRED` |

### 1.3 Mutable Fields (Subject to Evolution)

The strategy builder agent (and LLM-guided optimizer) may propose changes to these fields only:

| Field | Mutation Constraint |
|-------|-------------------|
| `entry_rules.conditions[].threshold` | ±50% of current value per mutation |
| `entry_rules.conditions[].weight` | ±20% per mutation; must re-sum to 1.0 |
| `entry_rules.min_signal_score` | Range: 0.5–0.8 |
| `exit_rules.take_profit.*` | Must maintain min R:R ≥ 2:1 |
| `exit_rules.stop_loss.*` | Must maintain ≤ 2% from entry |
| `exit_rules.trailing_stop.*` | Free mutation |
| `exit_rules.time_stop.max_hours` | Range: 1–24 |
| `risk_params.sl_atr_multiple` | Range: 0.5–3.0 |
| `risk_params.tp_rr_ratio` | Range: 2.0–5.0 |
| `regime_performance.*.status` | Updated by backtest results only |
| `allocation_pct` | Rebalanced by portfolio engine (weekly) |

### 1.4 Immutable Fields (Never Mutated)

| Field | Reason |
|-------|--------|
| `name` | Identity anchor for all tables |
| `version` | Only incremented, never changed retroactively |
| `thesis` | Thesis changes = new strategy, not a mutation |
| `entry_rules.type` | Type changes = new strategy |
| `created_at` | Audit trail |
| `parent_version` | Lineage tracking |

### 1.5 Day1 Genome: Mean Reversion

```yaml
genome:
  name: "mean_reversion"
  version: "1.0.0"
  thesis: >-
    BTC mean-reverts after RSI extremes. Buy oversold, sell overbought.
    Works in ranging regimes (~60% of time). Complements Momentum strategy.
  entry_rules:
    type: "mean_reversion"
    direction: "both"
    conditions:
      - { indicator: "rsi", period: 14, threshold: 30, operator: "lt", weight: 0.25 }
      - { indicator: "support_resistance", lookback_periods: 48, proximity_pct: 2.0, operator: "near", weight: 0.20 }
      - { indicator: "volume", lookback_periods: 20, multiplier: 1.5, operator: "gt", weight: 0.10 }
      - { indicator: "fear_greed", threshold: 30, operator: "lt", weight: 0.15 }
      - { indicator: "funding_rate", threshold: -0.0005, operator: "lt", weight: 0.20 }
      - { indicator: "adx", period: 14, threshold: 25, operator: "lt", weight: 0.10 }
    min_signal_score: 0.6
    regime_filter:
      allowed: ["ranging", "low_volatility"]
      blocked: ["trending_up", "trending_down", "transition"]
  exit_rules:
    take_profit: { method: "indicator", indicator: "rsi", threshold: 70, operator: "gt", fallback_pct: 2.0 }
    stop_loss: { method: "fixed_pct", pct: 1.0 }
    trailing_stop: { enabled: false }
    time_stop: { enabled: true, max_hours: 4 }
    funding_rate_flip: { enabled: true }
  risk_params:
    max_position_pct: 15.0
    risk_per_trade_pct: 2.0
    min_risk_reward: 2.0
    sl_atr_multiple: 1.5
    tp_rr_ratio: 2.0
    cooldown_minutes: 30
  regime_performance:
    trending_up:   { sharpe: null, win_rate: null, trade_count: 0, status: "blacklisted" }
    trending_down: { sharpe: null, win_rate: null, trade_count: 0, status: "blacklisted" }
    ranging:       { sharpe: null, win_rate: null, trade_count: 0, status: "active" }
    volatile:      { sharpe: null, win_rate: null, trade_count: 0, status: "paused" }
    low_volatility:{ sharpe: null, win_rate: null, trade_count: 0, status: "active" }
    transition:    { sharpe: null, win_rate: null, trade_count: 0, status: "paused" }
  status: "ACTIVE"
  allocation_pct: 50.0
```

### 1.6 Day1 Genome: Momentum

```yaml
genome:
  name: "momentum"
  version: "1.0.0"
  thesis: >-
    BTC exhibits strong momentum in trending regimes (~40% of time).
    Enters on trend continuation signals when ADX confirms directional strength.
    Complements Mean Reversion: MR works in ranging, Momentum works in trending.
  entry_rules:
    type: "momentum"
    direction: "both"
    conditions:
      - { indicator: "macd_crossover", fast: 12, slow: 26, signal: 9, operator: "crossover", weight: 0.30 }
      - { indicator: "adx", period: 14, threshold: 25, operator: "gt", weight: 0.25 }
      - { indicator: "rsi", period: 14, range_low: 50, range_high: 70, operator: "between", weight: 0.15 }
      - { indicator: "volume", lookback_periods: 20, multiplier: 1.1, operator: "gt", weight: 0.10 }
      - { indicator: "funding_rate", threshold: 0.0, operator: "directional", weight: 0.20 }
    min_signal_score: 0.65
    regime_filter:
      allowed: ["trending_up", "trending_down"]
      blocked: ["ranging", "transition"]
  exit_rules:
    take_profit: { method: "atr_multiple", multiplier: 3.0 }
    stop_loss: { method: "atr_multiple", multiplier: 2.0 }
    trailing_stop: { enabled: true, method: "atr_multiple", atr_multiplier: 1.5 }
    time_stop: { enabled: true, max_hours: 12 }
    funding_rate_flip: { enabled: true }
  risk_params:
    max_position_pct: 15.0
    risk_per_trade_pct: 2.0
    min_risk_reward: 2.5
    sl_atr_multiple: 2.0
    tp_rr_ratio: 2.5
    cooldown_minutes: 30
  regime_performance:
    trending_up:   { sharpe: null, win_rate: null, trade_count: 0, status: "active" }
    trending_down: { sharpe: null, win_rate: null, trade_count: 0, status: "active" }
    ranging:       { sharpe: null, win_rate: null, trade_count: 0, status: "blacklisted" }
    volatile:      { sharpe: null, win_rate: null, trade_count: 0, status: "paused" }
    low_volatility:{ sharpe: null, win_rate: null, trade_count: 0, status: "paused" }
    transition:    { sharpe: null, win_rate: null, trade_count: 0, status: "paused" }
  status: "ACTIVE"
  allocation_pct: 50.0
```

---

## 2. STRATEGY INTERFACE

Every strategy must implement a common interface. The Signal Scout agent, Risk Guardian, and backtesting engine all consume strategies through this interface — never directly accessing strategy internals.

### 2.1 BaseStrategy ABC

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class Signal:
    """Output of strategy.generate_signals()."""
    direction: str              # "long" | "short"
    entry_price: float
    stop_loss: float
    take_profit: float
    signal_score: float         # 0-1 weighted composite
    strategy_name: str
    strategy_version: str
    regime_at_signal: str
    reasoning: str              # Human-readable rationale
    timestamp: str              # ISO 8601
    funding_rate_score: float   # 0-1 funding rate component
    confidence: float           # 0-1 overall confidence


@dataclass
class BacktestResult:
    """Output of strategy backtest."""
    strategy_name: str
    strategy_version: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    profit_factor: float
    calmar_ratio: float
    avg_hold_hours: float
    avg_pnl_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    total_pnl: float
    regime_performance: dict    # Per-regime Sharpe, win rate
    overfitting_ratio: float    # test_sharpe / train_sharpe

    @property
    def passed(self) -> bool:
        """Minimum quality thresholds for deployment."""
        return (
            self.sharpe_ratio >= 0.5 and
            self.max_drawdown_pct <= 20.0 and
            self.total_trades >= 100 and      # FIX E5: 100 trades minimum
            self.win_rate >= 0.40 and
            self.profit_factor >= 1.1
        )

    @property
    def live_ready(self) -> bool:
        """Stricter thresholds for live capital."""
        return (
            self.sharpe_ratio >= 1.0 and
            self.max_drawdown_pct <= 15.0 and
            self.total_trades >= 100 and
            self.win_rate >= 0.45 and
            self.profit_factor >= 1.3 and
            self.overfitting_ratio >= 0.5
        )


class BaseStrategy(ABC):
    """
    Abstract base class for all TSAR strategies.
    
    Every strategy must implement:
    - generate_signals() — core signal generation
    - get_parameters() — current parameter state
    - get_optimization_grid() — parameter ranges for optimization
    - validate() — self-consistency check
    - get_genome() — full genome as dict
    - apply_mutation() — apply a parameter mutation
    
    The strategy builder agent produces concrete implementations of this class.
    """

    name: str                   # Unique strategy name
    version: str                # SemVer
    params: dict                # Current parameters

    @abstractmethod
    def generate_signals(
        self,
        data: pd.DataFrame,     # OHLCV data
        regime: Optional[str] = None  # Current regime classification
    ) -> tuple[pd.Series, pd.Series]:
        """
        Generate entry and exit signals from market data.
        
        Args:
            data: DataFrame with columns [open, high, low, close, volume]
                  Index is DatetimeIndex.
            regime: Current market regime (trending_up, trending_down,
                    ranging, volatile, low_volatility, transition)
        
        Returns:
            (entries, exits): Boolean Series aligned to data.index.
                entries[i] = True means BUY signal at bar i.
                exits[i] = True means CLOSE signal at bar i.
        
        Rules:
        - Must handle NaN/missing data gracefully (return empty signals)
        - Must NOT look ahead — no future data leakage
        - Must respect regime_filter from genome
        - Must return empty signals if regime is blocked
        """
        ...

    @abstractmethod
    def get_parameters(self) -> dict:
        """
        Return current parameter state as a flat dict.
        
        Returns:
            Dict of parameter_name → value. Used for:
            - Serialization to database
            - Comparison across mutations
            - LLM context for optimization
        """
        ...

    @abstractmethod
    def get_optimization_grid(self) -> dict:
        """
        Return parameter ranges for walk-forward optimization.
        
        Returns:
            Dict of parameter_name → list of values to test.
            Example: {'rsi_period': [10, 14, 18], 'adx_threshold': [20, 25, 30]}
        """
        ...

    @abstractmethod
    def validate(self) -> tuple[bool, list[str]]:
        """
        Self-consistency check. Returns (is_valid, list_of_errors).
        
        Must verify:
        - All required parameters exist
        - All parameter values are within legal ranges
        - Entry condition weights sum to 1.0 (±0.01)
        - Stop-loss is set
        - Risk-reward ≥ 2:1
        - Regime filter has at least 1 allowed regime
        - min_signal_score is in [0.5, 0.8]
        """
        ...

    @abstractmethod
    def get_genome(self) -> dict:
        """
        Return full genome as dict (for serialization to strategy_genomes table).
        Must match the YAML schema in §1.1.
        """
        ...

    @abstractmethod
    def apply_mutation(self, mutations: dict) -> 'BaseStrategy':
        """
        Apply parameter mutations and return a new strategy instance.
        
        Args:
            mutations: Dict of parameter_name → new_value
        
        Returns:
            New BaseStrategy instance with mutated parameters.
            Original instance is NOT modified (immutable pattern).
        
        Rules:
        - Only mutable fields may be changed (see §1.3)
        - Version must be incremented (patch bump)
        - parent_version must reference the pre-mutation version
        - Must call validate() on the new instance; raise if invalid
        """
        ...
```

### 2.2 Required Methods Summary

| Method | Returns | Called By | Frequency |
|--------|---------|-----------|-----------|
| `generate_signals(data, regime)` | `(entries, exits)` Series | Signal Scout, Backtester | Every 5 min (live), per fold (backtest) |
| `get_parameters()` | `dict` | LLM optimizer, DB serializer | On mutation, on checkpoint |
| `get_optimization_grid()` | `dict` | Grid search optimizer | On optimization run |
| `validate()` | `(bool, list[str])` | Genome loader, mutation gate | On load, on mutation |
| `get_genome()` | `dict` | Strategy Geneticist, DB | On save, on snapshot |
| `apply_mutation(mutations)` | `BaseStrategy` | LLM optimizer, Strategy Geneticist | On evolution |

### 2.3 Additional Interface Requirements

The strategy builder agent must also ensure:

1. **Deterministic output** — Same input data + same parameters = same signals. No randomness, no external state.
2. **No look-ahead bias** — `generate_signals()` at bar `i` must only use data `data[0:i+1]`.
3. **Regime awareness** — If `regime` is provided and is in `blocked` list, return empty signals.
4. **Funding rate integration** — Every strategy must incorporate the `funding_rate` indicator (FIX E3).
5. **Transition regime handling** — When regime is `"transition"`, reduce signal confidence by 50% (FIX E4).

---

## 3. BACKTESTING REQUIREMENTS

The backtesting engine is the quality gate. No strategy deploys without passing all requirements below.

### 3.1 Fee-Aware Simulation

```python
@dataclass
class BacktestConfig:
    """Canonical backtest configuration."""
    # Fees — must match exchange reality
    maker_fee_pct: float = 0.0010         # 0.10% Binance spot
    taker_fee_pct: float = 0.0010         # 0.10% Binance spot
    
    # Slippage — realistic model
    slippage_model: str = "realistic"     # "zero" | "fixed" | "realistic"
    slippage_mean_bps: float = 3.0        # 3 basis points mean
    slippage_std_bps: float = 2.0         # 2 basis points std dev
    
    # Capital
    initial_capital: float = 100.0        # $100 Day1
    
    # Risk (must match RiskEngine canonical limits)
    max_position_pct: float = 15.0
    risk_per_trade_pct: float = 2.0
    max_open_positions: int = 3           # Day1
    max_daily_loss_pct: float = 2.0
    max_drawdown_pct: float = 5.0
    
    # Execution
    fill_rate: float = 0.95               # 95% of signals get filled
    partial_fill_threshold: float = 0.5   # Partial fill below 50%
```

**Rules:**
- Fees must be exchange-accurate. No zero-fee backtests allowed.
- Slippage model `"realistic"` is mandatory for all deployment decisions.
- Slippage `"zero"` is allowed only for debugging/development.
- Commission is applied per-trade (entry + exit).

### 3.2 Walk-Forward Validation (Mandatory from Day1 — FIX E7)

```
┌─────────────────────────────────────────────────────────────────┐
│                 WALK-FORWARD VALIDATION                          │
│                                                                  │
│  Day1 (3-fold):                                                  │
│  ├── Fold 1: Train [0%-70%] → Test [70%-100%]                   │
│  ├── Fold 2: Train [0%-60%] → Test [60%-70%]                    │
│  └── Fold 3: Train [0%-50%] → Test [50%-60%]                    │
│                                                                  │
│  Level 2+ (5-fold):                                              │
│  ├── Fold 1: Train [0%-80%] → Validation [80%-90%] → Test [90%-100%] │
│  ├── Fold 2: ...                                                 │
│  └── Fold 5: ...                                                 │
│                                                                  │
│  Rules:                                                          │
│  - NO parameter optimization in train → apply to test (Day1)     │
│  - Same parameters used in both train and test                   │
│  - Test set must be strictly after train set (no shuffling)      │
│  - Minimum 100 bars per test fold                                │
└─────────────────────────────────────────────────────────────────┘
```

**Day1 Walk-Forward Pass Criteria:**

| Criterion | Threshold |
|-----------|-----------|
| Passed folds | ≥ 2 of 3 |
| Average test Sharpe | ≥ 0.3 |
| Overfitting ratio (test/train) | ≥ 0.3 |
| Total trades across test folds | ≥ 50 |
| Test Sharpe std dev | ≤ 1.0 |

**Level 2+ Walk-Forward Pass Criteria (stricter):**

| Criterion | Threshold |
|-----------|-----------|
| Passed folds | ≥ 4 of 5 |
| Average test Sharpe | ≥ 0.5 |
| Overfitting ratio | ≥ 0.5 |
| Total trades across test folds | ≥ 100 |
| Statistical significance (p-value) | < 0.05 |

### 3.3 Statistical Significance Requirements

| Metric | Minimum Sample | Test | Threshold |
|--------|---------------|------|-----------|
| Sharpe ratio | 100 trades | Welch's t-test vs 0 | p < 0.05 |
| Win rate | 100 trades | Binomial test vs 50% | p < 0.05 |
| Profit factor | 100 trades | Bootstrap CI | Lower bound > 1.0 |
| Regime-specific Sharpe | 30 trades per regime | Welch's t-test | p < 0.10 (relaxed per-regime) |

**No strategy deploys if statistical significance is not met.**

### 3.4 Regime-Specific Performance

The backtester must produce per-regime performance breakdowns:

```python
@dataclass
class RegimeBacktestResult:
    """Per-regime performance from a single backtest run."""
    regime: str                     # trending_up, trending_down, etc.
    trade_count: int
    win_rate: float
    sharpe_ratio: float
    avg_pnl_pct: float
    max_drawdown_pct: float
    profit_factor: float
    
    @property
    def viable(self) -> bool:
        """Is this strategy viable in this regime?"""
        return (
            self.trade_count >= 10 and
            self.sharpe_ratio >= 0.0 and
            self.win_rate >= 0.35
        )
```

**Regime routing rules:**
- If strategy has negative Sharpe in a regime → set `status: "blacklisted"` for that regime
- If strategy has Sharpe 0-0.3 in a regime → set `status: "paused"` (reduce allocation)
- If strategy has Sharpe > 0.5 in a regime → set `status: "active"` (full allocation)
- Transition regime always starts at `"paused"` with 50% position reduction

### 3.5 Full Backtest Pass/Fail Matrix

| Metric | Paper Trade Gate | Live Trading Gate | Institutional Gate |
|--------|-----------------|-------------------|-------------------|
| Sharpe Ratio | ≥ 0.5 | ≥ 1.0 | ≥ 1.5 |
| Sortino Ratio | ≥ 0.7 | ≥ 1.2 | ≥ 2.0 |
| Max Drawdown | ≤ 20% | ≤ 15% | ≤ 10% |
| **Total Trades** | **≥ 100** | **≥ 100** | **≥ 100** |
| Win Rate | ≥ 40% | ≥ 45% | ≥ 50% |
| Profit Factor | ≥ 1.1 | ≥ 1.3 | ≥ 1.5 |
| Calmar Ratio | ≥ 0.5 | ≥ 1.0 | ≥ 2.0 |
| WF Overfitting Ratio | ≥ 0.3 | ≥ 0.5 | ≥ 0.7 |
| Statistical Significance | p < 0.10 | p < 0.05 | p < 0.01 |

### 3.6 Frozen Baseline Requirement (FIX E6)

For alpha attribution, every deployed strategy must have a **frozen baseline copy**:

1. When strategy `mean_reversion` is created, simultaneously create `mean_reversion_v1_frozen`
2. The frozen copy uses Day1 parameters permanently — it never mutates
3. Both strategies run on the same data simultaneously
4. Alpha = evolved Sharpe − frozen Sharpe
5. If alpha is negative for 30+ days → investigate; if negative for 60+ days → consider reverting

---

## 4. IMPROVEMENT METRICS

The strategy builder agent must track and report the following metrics for every strategy it produces or evolves.

### 4.1 Per-Strategy Metrics

| # | Metric | Calculation | Update Frequency | Alert Threshold |
|---|--------|-------------|------------------|-----------------|
| 1 | **Sharpe Trend** | 30-day rolling annualized Sharpe | Daily | Sharpe < 0.5 for 30 days → RETIRE |
| 2 | **Win Rate Trend** | 50-trade rolling win rate | Per trade | < 40% over 50 trades → RETIRE |
| 3 | **Profit Factor Trend** | 50-trade rolling profit factor | Per trade | < 1.0 for 30 days → PAUSE |
| 4 | **Max Drawdown** | HWM to trough | Per trade | > 15% → PAUSE; > 20% → RETIRE |
| 5 | **Avg Hold Duration** | Mean time in trade | Per trade | Monitor for drift |
| 6 | **Expectancy** | Avg P&L per trade (30-day rolling) | Per trade | Negative for 14 days → PAUSE |

### 4.2 Per-Regime Metrics

| # | Metric | Calculation | Purpose |
|---|--------|-------------|---------|
| 7 | **Regime Sharpe** | Sharpe within each regime | Which regimes does the strategy work in? |
| 8 | **Regime Win Rate** | Win rate within each regime | Regime-specific reliability |
| 9 | **Regime Trade Count** | Trades per regime | Is the regime filter working? |
| 10 | **Regime Fitness Score** | Composite of 7+8+9 | Overall regime suitability |

### 4.3 Evolution Metrics

| # | Metric | Calculation | Purpose |
|---|--------|-------------|---------|
| 11 | **Lesson Application Rate** | % of trades where lessons were applied | Is the learning loop working? |
| 12 | **Lesson Violation Rate** | % of trades violating known lessons | Are we repeating mistakes? |
| 13 | **Mutation Success Rate** | % of mutations that improved Sharpe | Is evolution productive? |
| 14 | **Alpha Attribution** | Evolved Sharpe − Frozen Baseline Sharpe | Is the learning loop adding value? |
| 15 | **Overfitting Ratio** | Test Sharpe / Train Sharpe | Are we curve-fitting? |

### 4.4 Alpha Attribution Tracking (FIX E6)

```python
@dataclass
class AlphaAttribution:
    """
    Tracks whether the learning loop is generating genuine alpha.
    
    Maintains a frozen baseline (Day1 parameters, never mutated).
    Compares evolved strategy performance against frozen baseline.
    """
    baseline_strategy: str          # e.g., "mean_reversion_v1_frozen"
    baseline_sharpe: float
    baseline_pnl: float
    baseline_trades: int
    
    current_strategy: str           # e.g., "mean_reversion"
    current_sharpe: float
    current_pnl: float
    current_trades: int
    
    @property
    def alpha_sharpe(self) -> float:
        return self.current_sharpe - self.baseline_sharpe
    
    @property
    def alpha_pnl(self) -> float:
        return self.current_pnl - self.baseline_pnl
    
    @property
    def is_positive_alpha(self) -> bool:
        return self.alpha_sharpe > 0
    
    @property
    def confidence(self) -> str:
        min_trades = min(self.baseline_trades, self.current_trades)
        if min_trades < 50:
            return "LOW"
        elif min_trades < 100:
            return "MEDIUM"
        return "HIGH"
```

**Reporting cadence:**
- Alpha attribution reported weekly
- If alpha is negative for 30 days → WARNING alert
- If alpha is negative for 60 days → investigate evolution pipeline
- If alpha is negative for 90 days → consider reverting to frozen baseline

### 4.5 Composite Flywheel Health (Per-Strategy)

```python
def strategy_health_score(strategy_name: str) -> float:
    """
    Composite health score (0-1) for a single strategy.
    
    Weights:
    - Sharpe trend:           0.25
    - Regime fitness:         0.20
    - Alpha attribution:      0.20
    - Lesson application rate: 0.15
    - Overfitting ratio:      0.10
    - Win rate trend:         0.10
    """
    metrics = get_strategy_metrics(strategy_name)
    
    scores = {
        'sharpe_trend': normalize(metrics.sharpe_trend, min=0.0, max=2.0),
        'regime_fitness': normalize(metrics.regime_fitness, min=0.0, max=1.0),
        'alpha_attribution': normalize(metrics.alpha_sharpe, min=-1.0, max=1.0),
        'lesson_rate': metrics.lesson_application_rate,
        'overfitting': normalize(metrics.overfitting_ratio, min=0.0, max=1.0),
        'win_rate': normalize(metrics.win_rate, min=0.3, max=0.7),
    }
    
    weights = {
        'sharpe_trend': 0.25,
        'regime_fitness': 0.20,
        'alpha_attribution': 0.20,
        'lesson_rate': 0.15,
        'overfitting': 0.10,
        'win_rate': 0.10,
    }
    
    return sum(scores[k] * weights[k] for k in weights)
```

**Classification:**

| Score | Status | Action |
|-------|--------|--------|
| > 0.7 | 🟢 Healthy | Continue monitoring |
| 0.4–0.7 | 🟡 Stalling | Investigate; check regime shifts |
| < 0.4 | 🔴 Failing | Pause strategy; audit genome |

### 4.6 Strategy Retirement Gates (Canonical)

| Gate | Threshold | Action |
|------|-----------|--------|
| Rolling Sharpe (30-day) | < 0.5 for 30 days | RETIRE |
| Max Drawdown | > 15% from HWM | PAUSE |
| Max Drawdown | > 20% from HWM | RETIRE |
| Win Rate (50 trades) | < 40% | RETIRE |
| Regime Fitness | Negative Sharpe in current regime | PAUSE for that regime |
| Alpha Attribution | Negative for 90 days | REVERT to frozen baseline |
| Overfitting Ratio | < 0.3 on walk-forward | REJECT deployment |

### 4.7 Database Schema for Metrics

```sql
-- Strategy performance snapshots (daily)
CREATE TABLE IF NOT EXISTS strategy_performance_snapshots (
    snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    
    -- Rolling metrics
    sharpe_30d      REAL,
    win_rate_50t    REAL,
    profit_factor_50t REAL,
    expectancy_30d  REAL,
    max_drawdown_pct REAL,
    avg_hold_hours  REAL,
    
    -- Regime metrics (JSON)
    regime_sharpe   TEXT,       -- {"ranging": 0.89, "trending_up": 1.2, ...}
    regime_win_rate TEXT,
    regime_fitness  TEXT,
    
    -- Evolution metrics
    lesson_application_rate REAL,
    lesson_violation_rate   REAL,
    alpha_sharpe    REAL,
    alpha_pnl       REAL,
    overfitting_ratio REAL,
    
    -- Composite
    health_score    REAL,
    health_status   TEXT,       -- "healthy" | "stalling" | "failing"
    
    computed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(strategy_name, computed_at)
);

-- Alpha attribution records
CREATE TABLE IF NOT EXISTS alpha_attribution (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT NOT NULL,
    trade_id        TEXT,
    pnl             REAL,
    pnl_pct         REAL,
    sharpe_running  REAL,
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alpha_strategy ON alpha_attribution(strategy_name);
CREATE INDEX IF NOT EXISTS idx_alpha_ts ON alpha_attribution(timestamp);
```

---

## 5. STRATEGY BUILDER AGENT OUTPUT CONTRACT

The strategy builder agent (Strategy Geneticist at Level 3+, or the Orchestrator inline at Day1) must produce the following outputs:

### 5.1 On Strategy Creation

| Output | Format | Destination |
|--------|--------|-------------|
| Strategy Genome | YAML (§1.1) | `strategy_genomes` table |
| Frozen Baseline | YAML (genome copy) | `strategy_genomes` table (name: `{name}_v1_frozen`) |
| Strategy Class | Python (BaseStrategy impl) | `strategies/{name}.py` |
| Optimization Grid | dict (§2.1 `get_optimization_grid`) | `strategy_genomes.optimization_grid` JSON |
| Walk-Forward Result | BacktestResult | `backtest_results` table |
| Initial Health Score | float | `strategy_performance_snapshots` |

### 5.2 On Strategy Mutation

| Output | Format | Destination |
|--------|--------|-------------|
| Updated Genome | YAML (new version) | `strategy_genomes` table |
| Mutation Record | JSON | `strategy_mutations` table |
| Walk-Forward Result | BacktestResult | `backtest_results` table |
| Performance Before/After | JSON | `strategy_mutations.performance_before/after` |
| LLM Rationale | string | `strategy_mutations.rationale` |

### 5.3 On Strategy Retirement

| Output | Format | Destination |
|--------|--------|-------------|
| Status Update | enum | `strategy_genomes.status = "RETIRED"` |
| Retirement Reason | string | `strategy_genomes.retirement_reason` |
| Final Performance Snapshot | JSON | `strategy_performance_snapshots` |
| CloudEvent | `tsar.strategy.retired.v1` | `tsar:stream:strategy_mutations` |

### 5.4 Output Validation Checklist

Before any strategy output is accepted, the builder must verify:

- [ ] Genome passes all required fields (§1.2)
- [ ] `validate()` returns `(True, [])`
- [ ] Walk-forward validation passed (§3.2)
- [ ] Statistical significance met (§3.3)
- [ ] Frozen baseline created (§3.6)
- [ ] Regime performance populated for at least 1 regime (§3.4)
- [ ] All risk params within canonical limits (§1.3)
- [ ] No look-ahead bias in signal generation (verified by walk-forward)
- [ ] Fee-aware simulation used (§3.1)
- [ ] Backtest had ≥ 100 trades (FIX E5)

---

## Appendix: Quick Reference

### Canonical Risk Limits (from TSAR_ARCHITECTURE.md §6.1)

| Parameter | Value |
|-----------|-------|
| Daily loss limit | -2% of capital |
| Max drawdown | 5% from HWM |
| Max open positions | 3 (Day1), 10 (Level 2+) |
| Max single position | 15% of capital |
| Kelly fraction | 0.25 (fixed) |
| Max correlation | 0.7 |
| Min risk-reward | 2:1 |
| Max daily trades | 30 |

### Regime States (FIX E4)

| Regime | Position Scale | Strategy Affinity |
|--------|---------------|-------------------|
| `trending_up` | 1.0x | Momentum (active), MR (blacklisted) |
| `trending_down` | 1.0x | Momentum (active), MR (blacklisted) |
| `ranging` | 1.0x | MR (active), Momentum (blacklisted) |
| `volatile` | 0.75x | Both (paused — reduce size) |
| `low_volatility` | 1.0x | MR (active), Momentum (paused) |
| `transition` | 0.1–0.5x | Both (paused — confidence-scaled) |

### Evolution Pipeline (TSAR_ARCHITECTURE.md §7.5)

```
Trade Philosopher discovers patterns
        ↓
Strategy Geneticist proposes mutations (LLM-guided, not genetic — FIX E2)
        ↓
Grid search around LLM suggestions + walk-forward validation
        ↓
    PASS → Deploy to paper trading
              ↓
         30+ paper trades with Sharpe > 1.0
              ↓
          PASS → Deploy to live (25% size)
          FAIL → Retire mutation
    FAIL → Archive, try different mutation
```

---

*This document defines what the strategy builder agent must produce. All strategy engineering references this document. Where prior documents conflict, this document wins alongside TSAR_ARCHITECTURE.md v3.0.0.*

*Issued by: Chief Strategist, TSAR Council*
*Date: 2026-07-24 05:35 GMT+8*
