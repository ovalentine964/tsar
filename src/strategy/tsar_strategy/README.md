# TSAR — Valentine Money Printing Machine

## Overview

TSAR is a multi-layer institutional trading strategy for the TSAR trading system. It combines session awareness, fundamental bias, multi-timeframe trend analysis, support/resistance mapping, and a structured entry pipeline to identify high-probability trading setups.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    TSARStrategy                              │
│  (extends BaseStrategy — registered in StrategyRegistry)     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌───────────────────┐  ┌──────────────┐ │
│  │SessionManager│  │FundamentalAnalyzer│  │ TrendDetector│ │
│  │              │  │                   │  │              │ │
│  │• Session map │  │• Calendar events  │  │• 50/200 MA   │ │
│  │• Overlaps    │  │• News blackout    │  │• HH/HL/LH/LL│ │
│  │• Liquidity   │  │• Bias scoring     │  │• D1/H4/H1   │ │
│  │• Score mult  │  │• Event risk       │  │• Confluence  │ │
│  └──────┬───────┘  └────────┬──────────┘  └──────┬───────┘ │
│         │                   │                     │         │
│         └───────────┬───────┴─────────────────────┘         │
│                     ▼                                        │
│         ┌───────────────────────┐                           │
│         │     LevelMapper       │                           │
│         │                       │                           │
│         │ • Asian High/Low      │                           │
│         │ • Daily/Weekly/Monthly│                           │
│         │ • Order Blocks        │                           │
│         │ • Swing Structure     │                           │
│         └───────────┬───────────┘                           │
│                     ▼                                        │
│         ┌───────────────────────┐                           │
│         │    EntryPipeline      │                           │
│         │                       │                           │
│         │ 1. News Gate          │                           │
│         │ 2. Trend Alignment    │                           │
│         │ 3. S/R Proximity      │                           │
│         │ 4. Retest Confirm     │                           │
│         │ 5. RSI Filter         │                           │
│         │ 6. Candlestick Pattern│                           │
│         │ 7. Execute            │                           │
│         └───────────────────────┘                           │
└─────────────────────────────────────────────────────────────┘
```

## Pipeline Flow

```
News Clear? ──NO──▶ SKIP
    │
   YES
    ▼
Trend Aligned? ──NO──▶ SKIP
    │
   YES
    ▼
At S/R Level? ──NO──▶ SKIP
    │
   YES
    ▼
Retest Confirm? ──NO──▶ SKIP
    │
   YES
    ▼
RSI Supports? ──NO──▶ SKIP
    │
   YES
    ▼
Candlestick Pattern? ──NO──▶ SKIP
    │
   YES
    ▼
SCORE ≥ 0.70? ──NO──▶ SKIP
    │
   YES
    ▼
EXECUTE TRADE
```

## Components

### TSARSessionManager (`session_manager.py`)
Tracks the current trading session and its characteristics.

- **Sessions**: Sydney (22:00-07:00), Tokyo (00:00-09:00), London (07:00-16:00), New York (12:00-21:00 UTC)
- **Overlaps**: London/NY (12:00-16:00) = peak liquidity, Tokyo/London (07:00-09:00) = breakout zone
- **Score multiplier**: 1.5x during overlaps, 0.7x during low liquidity
- **Favored pairs**: Each session has pairs that are most active

### TSARFundamentalAnalyzer (`fundamental_analyzer.py`)
Economic calendar integration and directional bias scoring.

- Integrates with TSAR's `MarketCalendar` tool for event data
- Checks news blackout windows (60min for critical, 30min for high impact)
- Produces directional bias from consensus expectations
- Calculates event risk score (0-1) based on proximity and severity

### TSARTrendDetector (`trend_detector.py`)
Multi-timeframe trend analysis using 50/200 MA and swing structure.

- **MAs**: 50 SMA (fast) and 200 SMA (slow) on D1, H4, H1
- **Swing detection**: 5-bar window for swing highs/lows
- **Structure**: HH/HL (bullish), LH/LL (bearish), mixed (neutral)
- **Confluence**: Weighted score across timeframes (D1=0.5, H4=0.3, H1=0.2)

### TSARLevelMapper (`level_mapper.py`)
S/R level mapping from institutional-grade sources.

- **Asian session**: Daily high/low from Asian trading hours
- **Period levels**: Previous day/week/month/year OHLC
- **Order blocks**: Institutional supply/demand zones (last opposing candle before impulse)
- **Swing structure**: HH/HL/LH/LL levels from TrendDetector
- **Strength weighting**: Order blocks (1.0) > Asian (0.9) > Daily (0.8) > Weekly (0.7) > Monthly (0.6) > Yearly (0.5)

### TSAREntryPipeline (`entry_pipeline.py`)
The full entry logic sequence with scoring.

| Stage | Weight | Description |
|-------|--------|-------------|
| News Gate | 0.10 | No high-impact news in blackout window |
| Trend Align | 0.25 | D1/H4/H1 MAs agree on direction |
| S/R Proximity | 0.20 | Price at a mapped S/R level (within 0.3%) |
| Retest | 0.15 | Price retests level with rejection candle |
| RSI Filter | 0.15 | RSI supports direction (not overextended) |
| Candlestick | 0.15 | Engulfing, pin bar, or star pattern |

### TSARStrategy (`strategy.py`)
Main strategy class extending TSAR's `BaseStrategy`.

- Implements `check_entry()`, `check_exit()`, `get_risk_params()`
- Wired into `StrategyRegistry` for signal aggregation
- Genome-driven parameters for evolution by `StrategyGeneticist`
- Async API for live data fetching via `analyze_async()`

## Configuration

### Trading Pairs

**Forex Majors**: EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, NZD/USD, USD/CAD

**Crypto**: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT

### Risk Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| risk_per_trade | 1.5% | Max risk per trade |
| max_position | 10% | Max position as % of equity |
| min_rr_ratio | 2.0 | Minimum risk:reward |
| trailing_stop | 1.5x ATR | Trailing stop multiplier |
| max_stop_loss | 2% | Maximum stop-loss from entry |

### Mutable Parameters (Genome-Evolvable)

All parameters in `config/strategies/tsar.yaml` under `mutable_parameters` can be evolved by the `StrategyGeneticist`:

- `ma_fast_period` (20-100, default 50)
- `ma_slow_period` (100-300, default 200)
- `rsi_period` (7-21, default 14)
- `sr_proximity_pct` (0.1-1.0%, default 0.3%)
- `retest_candles` (1-5, default 3)
- `atr_buffer_mult` (0.25-1.5, default 0.5)
- `min_rr_ratio` (1.5-4.0, default 2.0)
- `trailing_stop_atr_mult` (1.0-3.0, default 1.5)
- `min_signal_score` (0.60-0.85, default 0.70)
- `session_overlap_mult` (1.0-2.0, default 1.5)

## TSAR Integration

### 1. Strategy Registry

```python
from src.strategy.registry import StrategyRegistry
from src.strategy.tsar.strategy import TSARStrategy
from src.strategy.genome import StrategyGenome

# Load genome from YAML
genome = StrategyGenome.from_yaml("config/strategies/tsar.yaml")

# Register
registry = StrategyRegistry()
registry.register(TSARStrategy(genome=genome))
```

### 2. SignalScout Integration

SignalScout calls `registry.generate_signals(data)` which invokes `TSARStrategy.check_entry(data)` for each symbol.

The data dict must include:
- `symbol`, `close`, `atr`, `rsi`, `volume_ratio`
- `d1_closes`, `h4_closes`, `h1_closes` (multi-TF close arrays)
- `d1_ohlcv`, `h4_ohlcv`, `h1_ohlcv` (multi-TF OHLCV bars)
- `asian_high`, `asian_low` (optional, from session data)
- `swing_highs`, `swing_lows` (optional, from trend analysis)

For live async analysis:
```python
signal = await strategy.analyze_async(symbol, gateway, pricing_engine)
```

### 3. RiskGuardian Validation

TSAR signals pass through the standard RiskGuardian pipeline:

1. Kill switch check
2. Position size validation (max 10% of equity)
3. Daily P&L limit (-2%)
4. Open positions limit (3)
5. Stop-loss reasonableness (≤ 2% from entry)
6. R:R ratio validation (≥ 2:1)
7. Symbol cooldown (30 min)
8. Signal score threshold (≥ 0.70)

TSAR's `get_risk_params()` returns all parameters the RiskGuardian needs.

### 4. Flywheel Integration

The `FlywheelOrchestrator` improves TSAR through the evolution loop:

1. **TRADE**: TSAR generates signals → RiskGuardian approves → ExecutionSniper executes
2. **OBSERVE**: Trade outcomes are tracked (win/loss, P&L, hold time)
3. **REFLECT**: `ShadowExtractor` identifies patterns in winning vs losing trades
4. **EXTRACT**: Rules are extracted (e.g., "TSAR performs better during London/NY overlap")
5. **ADAPT**: `StrategyGeneticist` mutates the TSAR genome parameters
6. **BETTER TRADE**: Updated genome is applied via `registry.apply_genome_weights()`

Key flywheel targets for TSAR:
- `min_signal_score` threshold (too high = missed trades, too low = bad trades)
- `sr_proximity_pct` (tighter = fewer but better entries)
- `session_overlap_mult` (boost/reduce overlap bias)
- MA periods (optimize for current market regime)
- ATR buffer (tighter stops = more winners but more stops hit)

## Exit Rules

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| Hard Stop | Price hits stop-loss | Full close |
| Take Profit | Price hits TP | Full close |
| Partial TP | R:R = 1:1, 2:1, 3:1 | Close 40%, 30%, 30% |
| Trailing Stop | After 1:1 R:R | 1.5x ATR trailing |
| Breakeven | After 1:1 R:R | Move stop to entry |
| Trend Reversal | All MAs flip | Full close |
| Session End | Session closes | Close intra-session trades |

## File Structure

```
src/strategy/tsar/
├── __init__.py              # Module exports
├── session_manager.py       # Session awareness & liquidity
├── fundamental_analyzer.py  # Economic calendar & bias
├── trend_detector.py        # Multi-TF trend with HH/HL/LH/LL
├── level_mapper.py          # S/R mapping (Asian, OBs, etc.)
├── entry_pipeline.py        # Full entry pipeline logic
└── strategy.py              # Main TSARStrategy class

config/strategies/
└── tsar.yaml                # Strategy genome config
```
