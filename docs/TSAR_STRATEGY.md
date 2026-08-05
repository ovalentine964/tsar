# TSAR Strategy — Complete Documentation

> The core trading strategy of the TSAR super agent. A 7-layer institutional pipeline that combines session awareness, fundamental bias, multi-timeframe trend analysis, support/resistance mapping, and structured entry confirmation.

---

## Table of Contents

1. [Overview](#overview)
2. [The 7-Layer Pipeline](#the-7-layer-pipeline)
3. [Session Awareness](#session-awareness)
4. [Fundamental Bias](#fundamental-bias)
5. [Multi-Timeframe Trend Detection](#multi-timeframe-trend-detection)
6. [Support/Resistance Level Mapping](#supportresistance-level-mapping)
7. [RSI Filter](#rsi-filter)
8. [Candlestick Pattern Recognition](#candlestick-pattern-recognition)
9. [Entry Pipeline Execution](#entry-pipeline-execution)
10. [Exit Rules](#exit-rules)
11. [Risk Management](#risk-management)
12. [Genome Parameters Reference](#genome-parameters-reference)
13. [Strategy Router & Regime Integration](#strategy-router--regime-integration)
14. [Rust Acceleration](#rust-acceleration)
15. [Backtesting Guide](#backtesting-guide)
16. [Testing](#testing)

---

## Overview

The TSAR Strategy is a multi-layer institutional trading strategy that aligns trades with session liquidity windows, fundamental bias, multi-timeframe trends, and key structural levels. It executes only when the full 7-layer pipeline confirms every condition.

**Design Principles:**

- **Confluence over conviction** — no single indicator triggers a trade; all layers must agree
- **Session-aware execution** — trades only during high-liquidity windows
- **Structure-based risk** — stops placed behind S/R levels with ATR buffers
- **Genome-evolvable** — all parameters are tunable via genetic evolution
- **Rust-accelerated** — critical hot paths use Rust via PyO3 bindings

**Registered as:** `tsar` in the StrategyRegistry
**Scored by:** SignalScout agent
**Validated by:** RiskGuardian agent
**Evolved by:** StrategyGeneticist agent

---

## The 7-Layer Pipeline

The pipeline is the heart of the TSAR Strategy. Each layer produces a weighted score. Critical layers short-circuit on failure — if news is blocked or trend is neutral, no signal is generated regardless of downstream scores.

```
┌─────────────────────────────────────────────────────────────────┐
│                    TSAR STRATEGY PIPELINE                       │
│                                                                 │
│  Layer 1: NEWS GATE ──────────────┐                            │
│  │ No high-impact news in 30 min  │ CRITICAL — blocks          │
│  │ Weight: 0.10                   │ pipeline on failure         │
│  └────────────────────────────────┘                            │
│           │ pass                                               │
│  Layer 2: TREND ALIGNMENT ────────┐                            │
│  │ D1/H4/H1 MAs agree on dir     │ CRITICAL — blocks          │
│  │ Weight: 0.25                   │ pipeline on failure         │
│  └────────────────────────────────┘                            │
│           │ pass                                               │
│  Layer 3: S/R PROXIMITY ──────────┐                            │
│  │ Price at mapped S/R level      │                            │
│  │ Weight: 0.20                   │                            │
│  └────────────────────────────────┘                            │
│           │ pass                                               │
│  Layer 4: RETEST CONFIRMATION ────┐                            │
│  │ Price retests with rejection   │                            │
│  │ Weight: 0.15                   │                            │
│  └────────────────────────────────┘                            │
│           │ pass                                               │
│  Layer 5: RSI FILTER ─────────────┐                            │
│  │ RSI supports direction         │                            │
│  │ Weight: 0.15                   │                            │
│  └────────────────────────────────┘                            │
│           │ pass                                               │
│  Layer 6: CANDLESTICK PATTERN ────┐                            │
│  │ Engulfing/pin bar/star         │                            │
│  │ Weight: 0.15                   │                            │
│  └────────────────────────────────┘                            │
│           │ pass                                               │
│  Layer 7: EXECUTE ────────────────┐                            │
│  │ Aggregate score ≥ threshold    │                            │
│  │ Validate R:R ratio             │                            │
│  └────────────────────────────────┘                            │
│           │                                                    │
│           ▼                                                    │
│     ┌──────────┐                                               │
│     │  SIGNAL  │  → RiskGuardian → ExecutionSniper             │
│     └──────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
```

### Stage Weights

| Stage | Weight | Critical | Failure Behavior |
|-------|--------|----------|-----------------|
| News Gate | 0.10 | Yes | Short-circuits pipeline |
| Trend Alignment | 0.25 | Yes | Short-circuits pipeline |
| S/R Proximity | 0.20 | No | Score = 0, pipeline continues |
| Retest | 0.15 | No | Score = 0, pipeline continues |
| RSI Filter | 0.15 | No | Score = 0, pipeline continues |
| Candlestick | 0.15 | No | Score = 0, pipeline continues |

**Minimum passing score:** 0.70 (configurable via `min_signal_score` genome parameter)

### Score Aggregation

Each stage produces a score in `[0.0, weight]`. The total is:

```
total_score = (sum of stage scores / sum of weights) × session_multiplier
```

The session multiplier ranges from 1.0 (normal) to 1.5 (London/NY overlap).

---

## Session Awareness

The SessionManager tracks four global trading sessions and their overlaps. Session awareness affects:

1. **Entry gating** — forex trades only during London/NY sessions
2. **Score multiplier** — overlap periods boost signal scores
3. **Sizing** — position size scales with liquidity
4. **Asian range** — sets S/R levels for the next session

### Sessions (UTC)

| Session | Open | Close | Liquidity | Focus Pairs |
|---------|------|-------|-----------|-------------|
| Sydney | 22:00 | 07:00 | Low | AUD/USD, NZD/USD |
| Tokyo | 00:00 | 09:00 | Moderate | USD/JPY, AUD/JPY |
| London | 07:00 | 16:00 | High | EUR/USD, GBP/USD |
| New York | 12:00 | 21:00 | High | EUR/USD, GBP/USD, USD/CAD |

### Overlaps

| Overlap | Window | Multiplier | Character |
|---------|--------|------------|-----------|
| London/New York | 12:00–16:00 | 1.5× | Peak liquidity — highest probability setups |
| Tokyo/London | 07:00–09:00 | 1.2× | Breakout zone — Asian range breakout |

### Crypto Adaptation

Crypto pairs trade 24/7. The session manager still applies overlap multipliers (London/NY overlap correlates with highest retail crypto volume) but does not gate entries by session.

---

## Fundamental Bias

The FundamentalAnalyzer integrates with TSAR's MarketCalendar and FundamentalScorer tools to produce a directional bias for each trading pair.

### Bias Components

| Component | Source | Weight |
|-----------|--------|--------|
| Economic events | FOMC, CPI, NFP, GDP calendar | High |
| Central bank decisions | Rate decisions, forward guidance | High |
| News veto | NewsGatekeeper signal | Critical |
| Macro regime | MacroAgent alignment score | Medium |

### Bias Output

```python
FundamentalBias(
    direction="bullish" | "bearish" | "neutral",
    confidence=0.0–1.0,
    news_clear=True | False,
    blackout_active=True | False,
    event_risk_score=0.0–1.0,
    macro_alignment=0.0–1.0,
)
```

### Economic Blackout

When a high-impact event (FOMC, CPI, NFP) is within 30 minutes, the news gate blocks all entries. The blackout window is configurable per event type.

---

## Multi-Timeframe Trend Detection

The TrendDetector analyzes trend across D1, H4, and H1 timeframes using:

- **50 SMA and 200 SMA** for trend direction on each timeframe
- **Higher-High / Higher-Low (HH/HL)** for uptrend confirmation
- **Lower-High / Lower-Low (LH/LL)** for downtrend confirmation
- **MA separation and slope** for trend strength scoring

### TrendState Output

```python
TrendState(
    direction="bullish" | "bearish" | "neutral",
    aligned=True | False,       # All timeframes agree
    strength=0.0–1.0,           # MA separation normalized
    confluence_score=0.0–1.0,   # Per-timeframe agreement score
    per_timeframe={             # Individual TF analysis
        "D1": TimeframeTrend(...),
        "H4": TimeframeTrend(...),
        "H1": TimeframeTrend(...),
    },
)
```

### Alignment Rules

- **Bullish aligned:** D1 50MA > 200MA, H4 50MA > 200MA, H1 50MA > 200MA
- **Bearish aligned:** All three inverted
- **Neutral:** Mixed signals across timeframes → pipeline rejects

### Swing Detection

The trend detector identifies swing points (HH, HL, LH, LL) to confirm structural trend. A bullish trend requires a sequence of HH → HL; bearish requires LH → LL.

---

## Support/Resistance Level Mapping

The LevelMapper maps S/R from multiple sources, each with a strength weight.

### Level Sources

| Source | Strength | Description |
|--------|----------|-------------|
| Order Blocks | 1.0 | Institutional supply/demand zones (large body candles) |
| Asian H/L | 0.9 | Sydney/Tokyo session high and low |
| Daily H/L | 0.8 | Previous day high, low, open |
| Weekly H/L | 0.7 | Previous week high, low, open |
| Monthly H/L | 0.6 | Previous month high, low |
| Yearly | 0.5 | Yearly open, high, low |
| Swing H/L | Varies | From TrendDetector swing analysis |

### Order Block Detection

Order blocks are identified by:

1. Large candle body (≥30% of total range)
2. Followed by directional move
3. Price must be within 0.3% proximity to qualify

### Proximity Scoring

```
proximity_score = (1.0 - distance_pct / sr_proximity_pct) × 0.6
                + level_strength × 0.4
```

Where `sr_proximity_pct` defaults to 0.3%.

---

## RSI Filter

RSI confirms direction without acting as a primary signal.

### RSI Rules

| Direction | Valid RSI Range | Rejection Condition |
|-----------|----------------|-------------------|
| Long | 30–55 | RSI > 70 (overbought) |
| Short | 45–70 | RSI < 30 (oversold) |

### RSI Scoring

- **In optimal range:** Full weight (0.15)
- **Near edge of range:** Reduced weight
- **Outside range but not rejected:** 30% weight
- **Overbought/oversold:** Pipeline rejects (score = 0)

### Divergence Detection

The RSI filter also detects:

- **Bullish divergence:** Price makes new low, RSI makes higher low
- **Bearish divergence:** Price makes new high, RSI makes lower high

---

## Candlestick Pattern Recognition

The pipeline's final confirmation layer. Patterns are detected from the most recent 3 candles.

### Bullish Patterns

| Pattern | Confidence | Description |
|---------|------------|-------------|
| Bullish Engulfing | 0.85 | Bearish candle followed by larger bullish candle |
| Bullish Pin Bar | 0.75 | Long lower wick, small body, closes bullish |
| Morning Star | 0.80 | 3-candle reversal: bearish → small → bullish |

### Bearish Patterns

| Pattern | Confidence | Description |
|---------|------------|-------------|
| Bearish Engulfing | 0.85 | Bullish candle followed by larger bearish candle |
| Bearish Pin Bar | 0.75 | Long upper wick, small body, closes bearish |
| Evening Star | 0.80 | 3-candle reversal: bullish → small → bearish |

### Pattern Scoring

```
candle_score = pattern_confidence × weight (0.15)
```

---

## Entry Pipeline Execution

When all 7 layers pass and the aggregate score ≥ `min_signal_score`, the pipeline generates a trade signal.

### Signal Output

```python
{
    "side": "buy" | "sell",
    "score": 0.70–1.0,
    "entry_price": current_price,
    "stop_loss": structure_based_sl,
    "take_profit": rr_multiple_tp,
    "atr": current_atr,
    "trailing_stop_atr_mult": 1.5,
    "reasoning": "news_clear | trend=bullish aligned=True | ...",
    "components": {
        "session_score": 1.5,
        "session": "london_new_york",
        "is_overlap": True,
        "trend_direction": "bullish",
        "trend_aligned": True,
        "trend_strength": 0.82,
        "fundamental_bias": "bullish",
        "nearest_level_type": "order_block",
        "candle_pattern": "bullish_engulfing",
        "pipeline_stages": [...]
    }
}
```

### Stop Loss Calculation

```
stop_loss = nearest_S/R_level - (ATR × atr_buffer_mult)
          = level_price - (ATR × 0.5)
```

Minimum stop: `price - (ATR × 0.5)` (hard floor)

### Take Profit Calculation

```
risk = entry_price - stop_loss
take_profit = entry_price + (risk × min_rr_ratio)
            = entry_price + (risk × 2.0)
```

---

## Exit Rules

### Exit Triggers (in priority order)

1. **Hard Stop Loss** — price hits structure-based stop
2. **Take Profit** — price hits TP level
3. **Trailing Stop** — after 1:1 R:R, trailing activates at `ATR × 1.5` distance
4. **Trend Reversal** — all MAs flip direction on D1/H4/H1
5. **Session End** — intra-session trades close at session close

### Partial Exit Schedule

| R:R Level | Close % | Cumulative |
|-----------|---------|------------|
| 1:1 | 40% | 40% |
| 2:1 | 30% | 70% |
| 3:1 | 30% | 100% |

### Breakeven Rule

At 1:1 R:R, the stop loss is moved to breakeven (entry price).

---

## Risk Management

### Position Sizing

- **Method:** Half-Kelly criterion
- **Kelly fraction:** 0.25 (conservative)
- **Max position:** 10% of capital
- **Risk per trade:** 1.5% of capital
- **Max open positions:** 3

### Risk Constraints

| Constraint | Value | Enforced By |
|-----------|-------|-------------|
| Max stop loss | 2% of capital | RiskGuardian |
| Min R:R ratio | 2.0 | EntryPipeline |
| Max correlation | 0.7 | RiskGuardian |
| Required stop loss | Yes (mandatory) | RiskGuardian |
| Session-aware sizing | Yes | SessionManager |
| Reduce size during news | Yes | FundamentalAnalyzer |

### Retirement Gates

If the strategy degrades, automatic safeguards activate:

| Gate | Threshold | Action |
|------|-----------|--------|
| Rolling Sharpe (30d) | < 0.5 | Warning |
| Max drawdown (pause) | 10% | Pause trading |
| Max drawdown (retire) | 15% | Retire strategy |
| Win rate (50 trades) | < 45% | Pause pending review |

---

## Genome Parameters Reference

All parameters below are evolvable by the StrategyGeneticist. Each has a current value, min/max bounds, and step size.

### Trend Parameters

| Parameter | Default | Min | Max | Step | Description |
|-----------|---------|-----|-----|------|-------------|
| `ma_fast_period` | 50 | 20 | 100 | 5 | Fast MA period |
| `ma_slow_period` | 200 | 100 | 300 | 10 | Slow MA period |

### RSI Parameters

| Parameter | Default | Min | Max | Step | Description |
|-----------|---------|-----|-----|------|-------------|
| `rsi_period` | 14 | 7 | 21 | 1 | RSI calculation period |
| `rsi_oversold` | 30 | 20 | 40 | 5 | Oversold threshold |
| `rsi_overbought` | 70 | 60 | 80 | 5 | Overbought threshold |

### S/R and Retest

| Parameter | Default | Min | Max | Step | Description |
|-----------|---------|-----|-----|------|-------------|
| `sr_proximity_pct` | 0.3 | 0.1 | 1.0 | 0.1 | Max distance from level (%) |
| `retest_candles` | 3 | 1 | 5 | 1 | Candles for retest check |

### Stop/Target

| Parameter | Default | Min | Max | Step | Description |
|-----------|---------|-----|-----|------|-------------|
| `atr_buffer_mult` | 0.5 | 0.25 | 1.5 | 0.25 | ATR buffer for SL |
| `min_rr_ratio` | 2.0 | 1.5 | 4.0 | 0.5 | Min R:R ratio |
| `trailing_stop_atr_mult` | 1.5 | 1.0 | 3.0 | 0.25 | Trailing stop ATR mult |
| `stop_loss_atr_mult` | 1.5 | 1.0 | 3.0 | 0.25 | SL ATR multiplier |
| `take_profit_atr_mult` | 4.0 | 2.5 | 6.0 | 0.5 | TP ATR multiplier |

### Pipeline Scoring

| Parameter | Default | Min | Max | Step | Description |
|-----------|---------|-----|-----|------|-------------|
| `min_signal_score` | 0.70 | 0.60 | 0.85 | 0.05 | Min pipeline score |
| `session_overlap_mult` | 1.5 | 1.0 | 2.0 | 0.1 | Overlap score mult |
| `volume_multiplier` | 1.2 | 1.0 | 2.5 | 0.1 | Volume vs avg mult |
| `min_confluence_score` | 55.0 | 40.0 | 75.0 | 5.0 | Min confluence (0-100) |

### Regime Routing Weights

| Parameter | Default | Min | Max | Step | Description |
|-----------|---------|-----|-----|------|-------------|
| `routing_strong_trend_up_tsar_weight` | 0.7 | 0.4 | 1.0 | 0.1 | Weight in strong uptrend |
| `routing_strong_trend_down_tsar_weight` | 0.7 | 0.4 | 1.0 | 0.1 | Weight in strong downtrend |
| `routing_ranging_tsar_weight` | 0.6 | 0.3 | 0.9 | 0.1 | Weight in ranging market |
| `routing_high_volatility_tsar_weight` | 0.5 | 0.2 | 0.8 | 0.1 | Weight in high volatility |

### Sizing Multipliers

| Parameter | Default | Min | Max | Step | Description |
|-----------|---------|-----|-----|------|-------------|
| `routing_strong_trend_up_sizing_mult` | 1.0 | 0.5 | 1.5 | 0.1 | Size in strong uptrend |
| `routing_ranging_sizing_mult` | 0.8 | 0.3 | 1.0 | 0.1 | Size in ranging market |
| `routing_high_volatility_sizing_mult` | 0.5 | 0.2 | 0.8 | 0.1 | Size in high volatility |

---

## Strategy Router & Regime Integration

The TSAR Strategy does not operate in isolation. The **TSARStrategyRouter** agent sits between SignalScout and RiskGuardian, routing signals through regime-aware logic.

### Regime Routing

| Regime | TSAR Weight | Secondary | Sizing Mult |
|--------|-------------|-----------|-------------|
| Strong Uptrend | 0.7 | Momentum (0.3) | 1.0 |
| Strong Downtrend | 0.7 | Momentum (0.3) | 1.0 |
| Ranging | 0.6 | MeanReversion (0.4) | 0.8 |
| High Volatility | 0.5 | — | 0.5 |
| Uncertain | Skip | — | 0.0 |

### Signal Blending

When a secondary strategy confirms, scores are blended:

```
final_score = (tsar_score × tsar_weight) + (secondary_score × secondary_weight)
```

---

## Rust Acceleration

Critical hot paths in the TSAR Strategy pipeline are accelerated via Rust PyO3 bindings:

| Component | Python | Rust | Speedup |
|-----------|--------|------|---------|
| RSI calculation | numpy | `tick-processor` crate | ~10× |
| ATR calculation | numpy | `tick-processor` crate | ~10× |
| MA computation | pandas | `tick-processor` crate | ~8× |
| Candlestick pattern scan | pure Python | `tick-processor` crate | ~15× |
| Level proximity check | pure Python | `core` crate | ~5× |
| Volume analysis | numpy | `tick-processor` crate | ~8× |

The Rust layer is optional. When `TSAR_RUST_BUILD=0` or the Rust toolchain is unavailable, the system falls back to pure Python implementations with identical behavior.

### Enabling Rust Acceleration

```bash
# Build Rust crates
cd rust && cargo build --release

# Verify PyO3 bindings
python3 -c "from src.backends.rust import tick_processor; print('Rust OK')"
```

---

## Backtesting Guide

### Walk-Forward Validation

The backtesting engine uses walk-forward validation:

| Set | Percentage | Purpose |
|-----|-----------|---------|
| Training | 70% | Parameter optimization |
| Validation | 15% | Out-of-sample confirmation |
| Test | 15% | Final performance estimate |

### Running a Backtest

```python
from src.strategy.backtest_engine import BacktestEngine
from src.strategy.tsar_strategy.strategy import TSARStrategy
from src.strategy.genome import StrategyGenome

# Load genome from YAML
genome = StrategyGenome.from_yaml("config/strategies/tsar.yaml")

# Create strategy instance
strategy = TSARStrategy(genome=genome)

# Run backtest
engine = BacktestEngine(
    strategy=strategy,
    fee_model="binance",
    slippage_model="realistic",
)
results = engine.run(
    data=historical_data,
    train_pct=70,
    validation_pct=15,
    test_pct=15,
)

print(f"Sharpe: {results.sharpe_ratio}")
print(f"Win Rate: {results.win_rate}")
print(f"Max Drawdown: {results.max_drawdown}")
print(f"Profit Factor: {results.profit_factor}")
```

### Monte Carlo Simulation

```python
from src.strategy.monte_carlo import MonteCarloSimulator

simulator = MonteCarloSimulator(strategy=strategy)
mc_results = simulator.run(
    data=historical_data,
    n_simulations=1000,
    confidence_level=0.95,
)

print(f"95% VaR: {mc_results.var_95}")
print(f"Expected Shortfall: {mc_results.expected_shortfall}")
```

### Fitness Evaluation

The StrategyGeneticist evaluates genome fitness using:

1. **Sharpe ratio** (primary)
2. **Profit factor** (secondary)
3. **Win rate** (tertiary)
4. **Max drawdown** (penalty)
5. **Trade count** (minimum threshold)

---

## Testing

The TSAR Strategy has **27 unit tests** covering all pipeline components:

| Test Area | Count | Coverage |
|-----------|-------|----------|
| Session Manager | 5 | Session detection, overlap, liquidity, pair alignment |
| Trend Detector | 4 | Uptrend, downtrend, insufficient data, swing detection |
| Level Mapper | 4 | Asian levels, daily levels, proximity, scoring |
| Entry Pipeline | 2 | News gate blocking, neutral trend blocking |
| Strategy Integration | 5 | Name, risk params, entry/exit, genome loading |
| Fundamental Analyzer | 3 | Crypto events, currency extraction, event risk |
| Full Pipeline | 1 | End-to-end with genome |
| Genome Loading | 1 | YAML parsing and parameter extraction |
| Pipeline Result | 2 | Result structure, score aggregation |

### Running Tests

```bash
# Run all TSAR Strategy tests
pytest tests/strategy/test_tsar.py -v

# Run with coverage
pytest tests/strategy/test_tsar.py -v --cov=src/strategy/tsar_strategy --cov=src/strategy/tsar

# Run specific test
pytest tests/strategy/test_tsar.py::TestTSARStrategy::test_full_pipeline_with_genome -v
```

---

## Configuration

The canonical genome file is at `config/strategies/tsar.yaml`. Key configuration sections:

| Section | Purpose |
|---------|---------|
| `symbols` | Trading pairs (forex + crypto) |
| `sessions` | Session times and overlap definitions |
| `entry_rules` | Pipeline stages, weights, and conditions |
| `exit_rules` | Stop loss, take profit, trailing, partial exits |
| `technical` | MA, RSI, ATR, volume parameters |
| `sr_levels` | S/R source configuration and weights |
| `sizing` | Kelly criterion and position limits |
| `risk_constraints` | Hard risk limits |
| `mutable_parameters` | Evolvable genome parameters |
| `backtesting` | Walk-forward and fee model settings |
| `retirement_gates` | Performance degradation thresholds |

---

## Related Documentation

- [Architecture Overview](ARCHITECTURE.md) — System architecture
- [Genome Evolution](../src/strategy/genome.py) — StrategyGenome implementation
- [Strategy Router](../src/agents/tsar_strategy_router.py) — Regime-aware routing
- [Risk Management](../config/risk.yaml) — Canonical risk parameters
- [Backtest Engine](../src/strategy/backtest_engine.py) — Walk-forward implementation

---

*TSAR Strategy v1.0.0 — Part of the TSAR Trading Super Agent system.*
