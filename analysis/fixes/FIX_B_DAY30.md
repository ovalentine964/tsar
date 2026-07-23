# FIX_B — DAY30 ARCHITECTURE: The Bridge Between Day1 and Level 2

**Status:** PROPOSED
**Author:** Day30 Architecture Specialist
**Date:** 2026-07-24
**Authority:** Defines the intermediate build stage between Day1 and Level 2
**Supersedes:** Nothing — incremental addition to DAY1_ARCHITECTURE.md
**Build Time:** 4–6 weeks after Day1 is complete and running

---

## 0. WHY DAY30 EXISTS

The Chief Engineer review identified the critical gap:

> "The jump from Day1 (pure Python, 3 agents) to Level 2 (Redis Streams, Macro Agent, vectorbt backtesting, immutable audit logs) is massive. There is no intermediate step that is both useful and buildable in a reasonable time."

Day30 fills that gap. It adds **six concrete capabilities** to the Day1 system without changing the language, the agent count, the database, or the dependency budget. After Day30, the system can:

1. **Cache expensive data in Redis** (regime state, price snapshots, indicator values)
2. **Backtest strategies offline** using vectorbt (standalone, not wired into live trading)
3. **Run a second strategy** (Momentum: MACD + ADX) alongside Mean Reversion
4. **Respond to richer Telegram commands** (`/backtest`, `/strategy`, `/metrics`)
5. **Expose Prometheus metrics** for trade count, P&L, win rate, drawdown
6. **Validate strategies with walk-forward** before deploying them live

**What Day30 does NOT do:**
- No Redis Streams (that's Level 2)
- No new agents (still 3: Signal, Risk, Execution)
- No Rust (still pure Python)
- No new database (still tsar.db)
- No new packages beyond the Day30 allowance (≤25 total)

---

## 1. INCREMENTAL FILE LIST

All paths relative to project root. Files marked `NEW` are added by Day30. Files marked `MODIFY` are changed in place. Everything else from Day1 is untouched.

```
trading-super-agent/
├── config/
│   ├── settings.py                  # MODIFY — add Redis, Prometheus, backtest configs
│   ├── .env                         # MODIFY — add REDIS_URL
│   └── strategies/                  # NEW directory
│       ├── mean_reversion.yaml      # NEW — genome file for MR strategy
│       └── momentum.yaml            # NEW — genome file for Momentum strategy
├── agents/
│   ├── __init__.py                  # (unchanged)
│   ├── signal_agent.py              # MODIFY — load strategy genomes, support multi-strategy
│   ├── risk_agent.py                # MODIFY — strategy-aware risk checks
│   └── execution_agent.py           # MODIFY — tag trades with strategy name
├── tools/
│   ├── __init__.py                  # (unchanged)
│   ├── market_tools.py              # MODIFY — add MACD, ADX, EMA calculations
│   ├── order_tools.py               # (unchanged)
│   ├── account_tools.py             # (unchanged)
│   ├── risk_tools.py                # (unchanged)
│   ├── db_tools.py                  # MODIFY — add backtest result logging
│   └── cache_tools.py               # NEW — Redis cache layer (get/set/invalidate)
├── strategies/
│   ├── __init__.py                  # MODIFY — strategy registry
│   ├── mean_reversion.py            # MODIFY — load params from YAML genome
│   └── momentum.py                  # NEW — MACD + ADX momentum strategy
├── backtest/
│   ├── __init__.py                  # NEW
│   ├── engine.py                    # NEW — vectorbt wrapper, run_backtest()
│   ├── walk_forward.py              # NEW — walk-forward validation framework
│   ├── data_loader.py               # NEW — fetch & cache historical OHLCV for backtesting
│   └── report.py                    # NEW — generate backtest reports (text + Telegram)
├── cache/
│   ├── __init__.py                  # NEW
│   ├── redis_client.py              # NEW — connection singleton, health check
│   ├── price_cache.py               # NEW — TTL-based price & OHLCV cache
│   └── regime_cache.py              # NEW — regime state cache (for future regime detector)
├── metrics/
│   ├── __init__.py                  # NEW
│   └── prometheus.py                # NEW — Prometheus gauges, counters, registry
├── notifications/
│   ├── __init__.py                  # (unchanged)
│   └── telegram_bot.py              # MODIFY — add /backtest, /strategy, /metrics commands
├── core/
│   ├── __init__.py                  # (unchanged)
│   ├── orchestrator.py              # MODIFY — multi-strategy scanning, Prometheus metrics
│   ├── learning_loop.py             # (unchanged)
│   └── daily_report.py              # MODIFY — include per-strategy breakdown
├── data/
│   ├── tsar.db                      # (unchanged — same database)
│   └── backtest_cache/              # NEW — cached historical data for backtesting
├── tests/
│   ├── test_tools.py                # MODIFY — add tests for MACD, ADX, cache
│   ├── test_risk.py                 # (unchanged)
│   ├── test_strategy.py             # MODIFY — add momentum strategy tests
│   ├── test_backtest.py             # NEW — backtest engine tests
│   ├── test_cache.py                # NEW — Redis cache tests
│   └── test_walk_forward.py         # NEW — walk-forward validation tests
├── main.py                          # MODIFY — init Redis, Prometheus, strategy registry
├── prometheus_server.py             # NEW — standalone Prometheus HTTP exporter (:9090)
├── requirements.txt                 # MODIFY — add redis, vectorbt, prometheus-client
├── .env.example                     # MODIFY — add REDIS_URL
└── README.md                        # MODIFY — document Day30 features
```

### File Count Summary

| Category | Day1 | Day30 (incremental) | Day30 (total) |
|----------|------|---------------------|---------------|
| Config | 2 | +2 | 4 |
| Agents | 3 | 0 (modify only) | 3 |
| Tools | 5 | +1 | 6 |
| Strategies | 1 | +1 | 2 |
| Backtest | 0 | +4 | 4 |
| Cache | 0 | +3 | 3 |
| Metrics | 0 | +1 | 1 |
| Notifications | 1 | 0 (modify only) | 1 |
| Core | 3 | 0 (modify only) | 3 |
| Tests | 3 | +3 | 6 |
| Entry points | 1 | +1 | 2 |
| **Total** | **~20** | **+16 new, 8 modified** | **~36** |

---

## 2. NEW DEPENDENCIES

Day30 adds exactly **4 new packages** to the Day1 requirements. Total stays under 25.

### Day1 Packages (unchanged, ~18)
```
ccxt==4.4.50
pandas==2.2.3
numpy==2.2.1
ollama==0.4.7
openai==1.61.0
python-telegram-bot==21.10
apscheduler==3.11.0
python-dotenv==1.1.0
pytest==8.3.4
matplotlib==3.10.1
(+ their transitive deps)
```

### Day30 Additions (4 packages)
```
redis==5.2.1                  # Redis client (caching only, no Streams)
vectorbt==0.26.3              # Backtesting engine
prometheus-client==0.21.1     # Prometheus metrics exporter
pyyaml==6.0.2                 # Strategy genome YAML parsing
```

### Package Budget

| Stage | Direct Packages | Notes |
|-------|----------------|-------|
| Day1 | ~18 | Pure Python, no Redis |
| Day30 | ~22 | + redis, vectorbt, prometheus-client, pyyaml |
| Limit | 25 | Chief Engineer constraint |
| Headroom | 3 | For future Level 2 additions |

### Why These Four

| Package | Justification | Risk |
|---------|--------------|------|
| `redis` | Cache regime state, price data, indicator values. Eliminates redundant API calls. | 🟢 Low — battle-tested |
| `vectorbt` | Vectorized backtesting. 100x faster than loop-based. Industry standard for Python quant. | 🟡 Medium — heavy dep tree (numba, plotly). Import ~3s. Pin carefully. |
| `prometheus-client` | Zero-config metrics. Expose gauges on HTTP. Grafana reads them. | 🟢 Low — minimal, well-maintained |
| `pyyaml` | Parse strategy genome YAML files. Tiny, stable. | 🟢 Low — ubiquitous |

### What We Explicitly Do NOT Add

| Package | Why Not |
|---------|---------|
| `celery` | APScheduler handles scheduling. Celery adds broker complexity. |
| `chromadb` | No vector search needed at Day30. Level 3 concern. |
| `TA-Lib` | System C library build friction. pandas-ta is sufficient. |
| `litellm` | Direct provider calls per FIX_01. No meta-package. |
| `sqlmodel` | Direct sqlite3 is fine for Day1-Day30. ORM adds abstraction we don't need yet. |

---

## 3. DETAILED COMPONENT SPECIFICATIONS

### 3.1 Redis Cache Layer (cache/)

**Purpose:** Eliminate redundant API calls and computation by caching frequently-read data.

**Architecture:**
```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Signal Agent │────▶│  Cache Layer │────▶│    Redis     │
│  Risk Agent   │     │  (read/write)│     │  (in-memory) │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │ cache miss
                            ▼
                     ┌──────────────┐
                     │  Exchange /  │
                     │  Computation │
                     └──────────────┘
```

**Key Design Decisions:**
- **Cache-only, NOT Streams.** Redis is used purely as a key-value cache with TTL. No pub/sub, no consumer groups, no message envelopes. This keeps Redis usage simple and avoids the complexity of the Level 2 stream topology.
- **Graceful degradation.** If Redis is unavailable, all cache reads return `None` and the system falls back to live data. The system works identically without Redis — it's just faster with it.
- **Key prefix:** All keys use `tsar:` prefix for namespacing.

**Cache Key Schema:**

| Key Pattern | TTL | Contents | Writer |
|-------------|-----|----------|--------|
| `tsar:price:{symbol}` | 30s | Last price float | market_tools |
| `tsar:ohlcv:{symbol}:{timeframe}` | 60s | OHLCV DataFrame (msgpack) | market_tools |
| `tsar:rsi:{symbol}:{period}` | 60s | RSI float | market_tools |
| `tsar:macd:{symbol}` | 60s | MACD dict (macd, signal, histogram) | market_tools |
| `tsar:adx:{symbol}:{period}` | 60s | ADX float | market_tools |
| `tsar:regime:{symbol}` | 300s | Regime dict (state, confidence) | (future: regime detector) |
| `tsar:balance` | 15s | Balance dict | account_tools |
| `tsar:sr_levels:{symbol}` | 120s | Support/resistance list | market_tools |

**Implementation — `cache/redis_client.py`:**
```python
"""
Redis connection singleton with graceful degradation.
If Redis is unavailable, all operations are no-ops.
"""
import os
import logging
import redis

logger = logging.getLogger(__name__)

_client = None

def get_client() -> redis.Redis | None:
    """Get or create Redis client. Returns None if unavailable."""
    global _client
    if _client is not None:
        return _client
    
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        _client = redis.from_url(redis_url, decode_responses=False)
        _client.ping()
        logger.info(f"Redis connected: {redis_url}")
        return _client
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.warning(f"Redis unavailable ({e}). Caching disabled.")
        _client = None
        return None
```

**Implementation — `cache/price_cache.py`:**
```python
"""
Price and indicator caching with TTL.
All operations are no-ops if Redis is unavailable.
"""
import json
import pickle
from cache.redis_client import get_client

PREFIX = "tsar:"

def cache_get(key: str):
    """Get value from cache. Returns None on miss or if Redis unavailable."""
    client = get_client()
    if client is None:
        return None
    try:
        data = client.get(f"{PREFIX}{key}")
        if data is None:
            return None
        return pickle.loads(data)
    except Exception:
        return None

def cache_set(key: str, value, ttl: int = 60):
    """Set value in cache with TTL (seconds). No-op if Redis unavailable."""
    client = get_client()
    if client is None:
        return
    try:
        client.setex(f"{PREFIX}{key}", ttl, pickle.dumps(value))
    except Exception:
        pass  # Cache writes are best-effort

def cache_invalidate(pattern: str):
    """Delete all keys matching pattern. No-op if Redis unavailable."""
    client = get_client()
    if client is None:
        return
    try:
        keys = client.keys(f"{PREFIX}{pattern}")
        if keys:
            client.delete(*keys)
    except Exception:
        pass
```

### 3.2 Momentum Strategy (strategies/momentum.py)

**Purpose:** Second strategy alongside Mean Reversion. Captures trend-following moves using MACD + ADX.

**Entry Rules (LONG):**
```
WHEN ALL conditions are true:
    1. MACD line crosses ABOVE signal line (bullish crossover)
    2. ADX(14) > 25 (trending market, not ranging)
    3. +DI > -DI (bullish directional bias)
    4. Price above EMA(50) (uptrend confirmation)
    5. No open SHORT position on same symbol

THEN:
    → Generate BUY signal
    → Entry: current market price
    → Stop-loss: 1.5 × ATR(14) below entry
    → Take-profit: 3 × ATR(14) above entry (2:1 R:R)
```

**Entry Rules (SHORT):**
```
WHEN ALL conditions are true:
    1. MACD line crosses BELOW signal line (bearish crossover)
    2. ADX(14) > 25 (trending market)
    3. -DI > +DI (bearish directional bias)
    4. Price below EMA(50) (downtrend confirmation)
    5. No open LONG position on same symbol

THEN:
    → Generate SELL signal
    → Entry: current market price
    → Stop-loss: 1.5 × ATR(14) above entry
    → Take-profit: 3 × ATR(14) below entry (2:1 R:R)
```

**Exit Rules:**
| Exit Type | Condition | Action |
|-----------|-----------|--------|
| Stop-loss hit | Price crosses stop | Market close, log loss |
| Take-profit hit | Price crosses target | Market close, log win |
| MACD reversal | MACD crosses back against position | Close 50%, trail rest |
| ADX collapse | ADX drops below 20 | Close at market (trend ended) |
| Time-based | Position open > 48 hours | Close at market |

**Scoring:**
| Factor | Weight | Max Score |
|--------|--------|-----------|
| MACD crossover strength | 30% | 0.30 |
| ADX magnitude (>25 = stronger) | 25% | 0.25 |
| Directional index spread | 20% | 0.20 |
| EMA trend alignment | 15% | 0.15 |
| Volume confirmation | 10% | 0.10 |
| **Total** | **100%** | **1.00** |

**Model Usage:** None. Pure technical. Momentum signals are mathematically defined — no LLM ambiguity.

### 3.3 Strategy Genome Files (config/strategies/)

**Purpose:** Externalize all strategy parameters into YAML files. Strategies become data, not code. This enables:
- Parameter tuning without code changes
- Backtesting different parameter sets
- Future strategy evolution (Level 3 Strategy Geneticist)

**Format — `config/strategies/mean_reversion.yaml`:**
```yaml
# Mean Reversion Strategy Genome
# TSAR Day30 — Strategy Definition File
---
genome:
  name: mean_reversion
  version: "1.0.0"
  thesis: >
    Price reverts to mean after extreme RSI readings at
    support/resistance levels. Works best in ranging markets.
  
  # Market parameters
  symbol: BTC/USDT
  timeframe: 1h
  
  # Entry conditions
  entry:
    rsi_period: 14
    rsi_oversold: 30
    rsi_overbought: 70
    sr_lookback: 48           # Candles for S/R detection
    sr_proximity_pct: 0.5     # Within 0.5% of level
    volume_multiplier: 1.2    # Volume must be 1.2x average
  
  # Exit rules
  exit:
    max_hold_hours: 24
    trailing_stop: false      # Not yet implemented
  
  # Scoring weights (must sum to 1.0)
  scoring:
    rsi_extreme: 0.40
    sr_proximity: 0.30
    volume_confirmation: 0.15
    trend_alignment: 0.15
  
  # Regime fitness (which regimes this strategy works in)
  regime_fitness:
    ranging: 0.9              # Works best in ranging markets
    trending_up: 0.4          # Poor in trends
    trending_down: 0.4
    volatile: 0.3             # Dangerous in volatile
    breakout: 0.2
  
  # Risk overrides (optional, falls back to global config)
  risk:
    max_position_pct: 5.0
    stop_loss_max_pct: 2.0
    min_risk_reward: 2.0
```

**Format — `config/strategies/momentum.yaml`:**
```yaml
# Momentum Strategy Genome (MACD + ADX)
# TSAR Day30 — Strategy Definition File
---
genome:
  name: momentum
  version: "1.0.0"
  thesis: >
    Trend-following using MACD crossovers confirmed by ADX.
    Works best in trending markets. Avoids ranging/choppy conditions.
  
  symbol: BTC/USDT
  timeframe: 1h
  
  entry:
    macd_fast: 12
    macd_slow: 26
    macd_signal: 9
    adx_period: 14
    adx_threshold: 25         # Minimum ADX for trend confirmation
    ema_period: 50            # Trend filter
    atr_period: 14            # For stop/take-profit sizing
    atr_stop_multiplier: 1.5  # Stop-loss = 1.5 × ATR
    atr_tp_multiplier: 3.0    # Take-profit = 3.0 × ATR
  
  exit:
    max_hold_hours: 48
    macd_reversal_close_pct: 50  # Close 50% on MACD reversal
    adx_collapse_threshold: 20   # Close all if ADX drops below
  
  scoring:
    macd_crossover_strength: 0.30
    adx_magnitude: 0.25
    directional_spread: 0.20
    ema_alignment: 0.15
    volume_confirmation: 0.10
  
  regime_fitness:
    trending_up: 0.9
    trending_down: 0.8
    ranging: 0.2              # Bad in ranges
    volatile: 0.5
    breakout: 0.7
  
  risk:
    max_position_pct: 5.0
    stop_loss_max_pct: 3.0    # Wider stops for momentum
    min_risk_reward: 2.0
```

**Loading — in `strategies/__init__.py`:**
```python
"""
Strategy registry. Loads genome YAML files at startup.
"""
import os
import yaml
from pathlib import Path

STRATEGY_DIR = Path(__file__).parent.parent / "config" / "strategies"

_registry = {}

def load_genome(yaml_path: str) -> dict:
    """Load a strategy genome from YAML."""
    with open(yaml_path) as f:
        return yaml.safe_load(f)["genome"]

def load_all_strategies():
    """Load all .yaml genomes from the strategies config directory."""
    global _registry
    for yaml_file in STRATEGY_DIR.glob("*.yaml"):
        genome = load_genome(str(yaml_file))
        name = genome["name"]
        _registry[name] = genome
    return _registry

def get_strategy(name: str) -> dict:
    """Get a loaded strategy genome by name."""
    return _registry.get(name)

def list_strategies() -> list[str]:
    """List all loaded strategy names."""
    return list(_registry.keys())
```

### 3.4 Backtesting Engine (backtest/)

**Purpose:** Validate strategies against historical data BEFORE deploying them live. Standalone module — does not integrate with the live trading loop.

**Architecture:**
```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  /backtest   │────▶│  Backtest    │────▶│   vectorbt   │
│  Telegram cmd │     │  Engine      │     │  (compute)   │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                     ┌──────▼───────┐
                     │  Walk-Forward │
                     │  Validator    │
                     └──────┬───────┘
                            │
                     ┌──────▼───────┐
                     │   Report     │
                     │  (text/tg)   │
                     └──────────────┘
```

**Implementation — `backtest/engine.py`:**
```python
"""
vectorbt-based backtesting engine.
Runs strategies against historical OHLCV data.
"""
import pandas as pd
import vectorbt as vbt
from dataclasses import dataclass

@dataclass
class BacktestResult:
    strategy_name: str
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_duration: float
    equity_curve: pd.Series
    trades: pd.DataFrame

def run_backtest(
    strategy_name: str,
    genome: dict,
    ohlcv: pd.DataFrame,
    initial_capital: float = 10000.0,
    fees: float = 0.001,        # Binance 0.1%
    slippage: float = 0.0003,   # 3 bps realistic
) -> BacktestResult:
    """
    Run a backtest for the given strategy genome against OHLCV data.
    
    Supports:
    - mean_reversion: RSI + S/R entry, fixed TP/SL exit
    - momentum: MACD + ADX entry, ATR-based TP/SL
    """
    entries = pd.Series(False, index=ohlcv.index)
    exits = pd.Series(False, index=ohlcv.index)
    
    if strategy_name == "mean_reversion":
        entries, exits = _generate_mr_signals(genome, ohlcv)
    elif strategy_name == "momentum":
        entries, exits = _generate_momentum_signals(genome, ohlcv)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    
    # Run through vectorbt
    pf = vbt.Portfolio.from_signals(
        close=ohlcv["close"],
        entries=entries,
        exits=exits,
        init_cash=initial_capital,
        fees=fees,
        slippage=slippage,
        freq="1h",
    )
    
    return BacktestResult(
        strategy_name=strategy_name,
        total_return=pf.total_return(),
        sharpe_ratio=pf.sharpe_ratio(),
        max_drawdown=pf.max_drawdown(),
        win_rate=pf.trades.win_rate(),
        profit_factor=pf.trades.profit_factor(),
        total_trades=pf.trades.count(),
        avg_trade_duration=pf.trades.duration.mean(),
        equity_curve=pf.value(),
        trades=pf.trades.records_readable,
    )

def _generate_mr_signals(genome, ohlcv):
    """Generate mean reversion entry/exit signals."""
    import pandas_ta as ta
    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]
    volume = ohlcv["volume"]
    
    e = genome["entry"]
    rsi = ta.rsi(close, length=e["rsi_period"])
    
    # Simplified S/R: use rolling min/max
    support = low.rolling(e["sr_lookback"]).min()
    resistance = high.rolling(e["sr_lookback"]).max()
    proximity = e["sr_proximity_pct"] / 100
    
    vol_avg = volume.rolling(20).mean()
    
    entries = (
        (rsi < e["rsi_oversold"]) &
        (close <= support * (1 + proximity)) &
        (volume > vol_avg * e["volume_multiplier"])
    )
    
    exits = (
        (rsi > e["rsi_overbought"]) |
        (close >= resistance * (1 - proximity))
    )
    
    return entries, exits

def _generate_momentum_signals(genome, ohlcv):
    """Generate momentum entry/exit signals."""
    import pandas_ta as ta
    close = ohlcv["close"]
    e = genome["entry"]
    
    # MACD
    macd = ta.macd(close, fast=e["macd_fast"], slow=e["macd_slow"], signal=e["macd_signal"])
    macd_line = macd[f"MACD_{e['macd_fast']}_{e['macd_slow']}_{e['macd_signal']}"]
    signal_line = macd[f"MACDs_{e['macd_fast']}_{e['macd_slow']}_{e['macd_signal']}"]
    
    # ADX
    adx_data = ta.adx(ohlcv["high"], ohlcv["low"], close, length=e["adx_period"])
    adx = adx_data[f"ADX_{e['adx_period']}"]
    plus_di = adx_data[f"DMP_{e['adx_period']}"]
    minus_di = adx_data[f"DMN_{e['adx_period']}"]
    
    # EMA trend filter
    ema = ta.ema(close, length=e["ema_period"])
    
    # Entry: MACD bullish cross + ADX trending + above EMA
    macd_cross_up = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
    entries = macd_cross_up & (adx > e["adx_threshold"]) & (plus_di > minus_di) & (close > ema)
    
    # Exit: MACD bearish cross or ADX collapse
    macd_cross_down = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))
    exits = macd_cross_down | (adx < genome["exit"]["adx_collapse_threshold"])
    
    return entries, exits
```

**Implementation — `backtest/walk_forward.py`:**
```python
"""
Walk-forward validation framework.
Split data into train/validation/test windows.
Validate that strategy parameters don't overfit.
"""
import pandas as pd
from backtest.engine import run_backtest, BacktestResult

def walk_forward_validate(
    strategy_name: str,
    genome: dict,
    ohlcv: pd.DataFrame,
    train_pct: float = 0.70,
    validation_pct: float = 0.15,
    test_pct: float = 0.15,
    min_trades: int = 10,
) -> dict:
    """
    Walk-forward validation: train → validate → test.
    
    Returns dict with results for each window plus a pass/fail verdict.
    """
    n = len(ohlcv)
    train_end = int(n * train_pct)
    val_end = int(n * (train_pct + validation_pct))
    
    train_data = ohlcv.iloc[:train_end]
    val_data = ohlcv.iloc[train_end:val_end]
    test_data = ohlcv.iloc[val_end:]
    
    # Run on each window
    train_result = run_backtest(strategy_name, genome, train_data)
    val_result = run_backtest(strategy_name, genome, val_data)
    test_result = run_backtest(strategy_name, genome, test_data)
    
    # Verdict: strategy passes if test window meets minimums
    passed = (
        test_result.total_trades >= min_trades and
        test_result.sharpe_ratio > 0.5 and
        test_result.max_drawdown < 0.20 and
        test_result.win_rate > 0.45
    )
    
    return {
        "strategy": strategy_name,
        "verdict": "PASS" if passed else "FAIL",
        "train": _summarize(train_result),
        "validation": _summarize(val_result),
        "test": _summarize(test_result),
        "reasons": _failure_reasons(test_result, min_trades) if not passed else [],
    }

def _summarize(r: BacktestResult) -> dict:
    return {
        "total_return": f"{r.total_return:.2%}",
        "sharpe": f"{r.sharpe_ratio:.2f}",
        "max_drawdown": f"{r.max_drawdown:.2%}",
        "win_rate": f"{r.win_rate:.2%}",
        "trades": r.total_trades,
    }

def _failure_reasons(r: BacktestResult, min_trades: int) -> list:
    reasons = []
    if r.total_trades < min_trades:
        reasons.append(f"Too few trades: {r.total_trades} < {min_trades}")
    if r.sharpe_ratio <= 0.5:
        reasons.append(f"Low Sharpe: {r.sharpe_ratio:.2f} <= 0.5")
    if r.max_drawdown >= 0.20:
        reasons.append(f"High drawdown: {r.max_drawdown:.2%} >= 20%")
    if r.win_rate <= 0.45:
        reasons.append(f"Low win rate: {r.win_rate:.2%} <= 45%")
    return reasons
```

**Implementation — `backtest/data_loader.py`:**
```python
"""
Fetch and cache historical OHLCV data for backtesting.
Uses ccxt to download, caches to disk as parquet.
"""
import os
import pandas as pd
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "data" / "backtest_cache"

def load_historical_data(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    days: int = 90,
    exchange_name: str = "binance",
) -> pd.DataFrame:
    """
    Load historical OHLCV. Uses disk cache if available and fresh.
    Falls back to ccxt download.
    """
    import ccxt
    cache_file = CACHE_DIR / f"{symbol.replace('/', '_')}_{timeframe}_{days}d.parquet"
    
    # Check cache freshness (< 1 hour old)
    if cache_file.exists():
        age_hours = (pd.Timestamp.now() - pd.Timestamp(cache_file.stat().st_mtime)).total_seconds() / 3600
        if age_hours < 1:
            return pd.read_parquet(cache_file)
    
    # Download from exchange
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    exchange = getattr(ccxt, exchange_name)()
    
    since = exchange.parse8601(
        (pd.Timestamp.now() - pd.Timedelta(days=days)).isoformat()
    )
    
    all_ohlcv = []
    while since < exchange.milliseconds():
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not ohlcv:
            break
        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1
    
    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = df[~df.index.duplicated(keep="first")]
    
    df.to_parquet(cache_file)
    return df
```

### 3.5 Prometheus Metrics (metrics/)

**Purpose:** Expose trading metrics for scraping by Prometheus. Enables Grafana dashboards.

**Metrics Defined:**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `tsar_trades_total` | Counter | strategy, side, status | Total trades placed |
| `tsar_pnl_total` | Gauge | strategy | Cumulative P&L in USD |
| `tsar_pnl_today` | Gauge | — | Today's P&L in USD |
| `tsar_win_rate` | Gauge | strategy | Rolling win rate (0-1) |
| `tsar_balance` | Gauge | — | Current account balance |
| `tsar_open_positions` | Gauge | — | Number of open positions |
| `tsar_drawdown` | Gauge | — | Current drawdown from HWM (0-1) |
| `tsar_sharpe_30d` | Gauge | strategy | Rolling 30-day Sharpe ratio |
| `tsar_signals_generated` | Counter | strategy, signal | Signals produced |
| `tsar_risk_rejections` | Counter | — | Signals rejected by risk agent |
| `tsar_last_trade_timestamp` | Gauge | — | Unix timestamp of last trade |
| `tsar_uptime_seconds` | Gauge | — | System uptime |

**Implementation — `metrics/prometheus.py`:**
```python
"""
Prometheus metrics for TSAR trading system.
"""
from prometheus_client import Counter, Gauge, start_http_server

# Trade metrics
TRADES_TOTAL = Counter(
    "tsar_trades_total", "Total trades placed",
    ["strategy", "side", "status"]
)
PNL_TOTAL = Gauge("tsar_pnl_total", "Cumulative P&L (USD)", ["strategy"])
PNL_TODAY = Gauge("tsar_pnl_today", "Today's P&L (USD)")
WIN_RATE = Gauge("tsar_win_rate", "Rolling win rate", ["strategy"])
BALANCE = Gauge("tsar_balance", "Current account balance (USD)")
OPEN_POSITIONS = Gauge("tsar_open_positions", "Number of open positions")
DRAWDOWN = Gauge("tsar_drawdown", "Current drawdown from HWM")
SHARPE_30D = Gauge("tsar_sharpe_30d", "Rolling 30-day Sharpe ratio", ["strategy"])

# System metrics
SIGNALS_GENERATED = Counter(
    "tsar_signals_generated", "Signals produced",
    ["strategy", "signal"]
)
RISK_REJECTIONS = Counter("tsar_risk_rejections", "Signals rejected by risk agent")
LAST_TRADE_TS = Gauge("tsar_last_trade_timestamp", "Unix timestamp of last trade")
UPTIME = Gauge("tsar_uptime_seconds", "System uptime in seconds")

_start_time = None

def init_metrics(port: int = 9090):
    """Start Prometheus HTTP server and initialize uptime tracking."""
    global _start_time
    import time
    _start_time = time.time()
    start_http_server(port)
    return port

def update_uptime():
    """Update uptime gauge. Call periodically."""
    if _start_time:
        UPTIME.set(time.time() - _start_time)
```

**Prometheus Scrape Config (`prometheus.yml` addition):**
```yaml
scrape_configs:
  - job_name: 'tsar'
    static_configs:
      - targets: ['localhost:9090']
    scrape_interval: 15s
```

### 3.6 Improved Telegram Bot (notifications/telegram_bot.py)

**Purpose:** Add `/backtest`, `/strategy`, and `/metrics` commands to the existing bot.

**New Commands:**

| Command | Description | Example Output |
|---------|-------------|----------------|
| `/backtest <strategy> [days]` | Run backtest for a strategy | Sharpe: 1.34, WR: 56%, DD: -8.2%, Trades: 47 |
| `/backtest_wf <strategy> [days]` | Walk-forward validation | Train PASS / Val PASS / Test PASS ✅ |
| `/strategy` | List all loaded strategies with status | `mean_reversion v1.0.0 ACTIVE` / `momentum v1.0.0 ACTIVE` |
| `/strategy <name>` | Show strategy genome details | Thesis, params, regime fitness, performance |
| `/metrics` | Show Prometheus metrics summary | Trades: 47, P&L: +$12.34, WR: 56%, DD: -3.2% |

**Command Implementations:**

```python
# In telegram_bot.py — add these handlers

async def cmd_backtest(update, context):
    """Run backtest: /backtest momentum 90"""
    args = context.args
    strategy_name = args[0] if args else "mean_reversion"
    days = int(args[1]) if len(args) > 1 else 90
    
    await update.message.reply_text(f"⏳ Running {strategy_name} backtest ({days}d)...")
    
    from backtest.engine import run_backtest
    from backtest.data_loader import load_historical_data
    from strategies import get_strategy
    
    genome = get_strategy(strategy_name)
    if not genome:
        await update.message.reply_text(f"❌ Strategy '{strategy_name}' not found")
        return
    
    ohlcv = load_historical_data(days=days)
    result = run_backtest(strategy_name, genome, ohlcv)
    
    msg = (
        f"📊 Backtest: {strategy_name} ({days}d)\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📈 Return: {result.total_return:.2%}\n"
        f"📐 Sharpe: {result.sharpe_ratio:.2f}\n"
        f"📉 Max DD: {result.max_drawdown:.2%}\n"
        f"🎯 Win Rate: {result.win_rate:.2%}\n"
        f"⚖️  PF: {result.profit_factor:.2f}\n"
        f"🔢 Trades: {result.total_trades}\n"
        f"⏱  Avg Duration: {result.avg_trade_duration:.1f}h"
    )
    await update.message.reply_text(msg)

async def cmd_backtest_wf(update, context):
    """Walk-forward validation: /backtest_wf momentum 90"""
    args = context.args
    strategy_name = args[0] if args else "mean_reversion"
    days = int(args[1]) if len(args) > 1 else 180  # Need more data for WF
    
    await update.message.reply_text(f"⏳ Running walk-forward validation for {strategy_name}...")
    
    from backtest.walk_forward import walk_forward_validate
    from backtest.data_loader import load_historical_data
    from strategies import get_strategy
    
    genome = get_strategy(strategy_name)
    if not genome:
        await update.message.reply_text(f"❌ Strategy '{strategy_name}' not found")
        return
    
    ohlcv = load_historical_data(days=days)
    result = walk_forward_validate(strategy_name, genome, ohlcv)
    
    verdict_emoji = "✅" if result["verdict"] == "PASS" else "❌"
    msg = (
        f"🔬 Walk-Forward: {strategy_name}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Train:      {result['train']['sharpe']} Sharpe, {result['train']['win_rate']} WR\n"
        f"Validation: {result['validation']['sharpe']} Sharpe, {result['validation']['win_rate']} WR\n"
        f"Test:       {result['test']['sharpe']} Sharpe, {result['test']['win_rate']} WR\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Verdict: {verdict_emoji} {result['verdict']}"
    )
    if result["reasons"]:
        msg += "\n⚠️ " + "\n⚠️ ".join(result["reasons"])
    
    await update.message.reply_text(msg)

async def cmd_strategy(update, context):
    """Show strategy info: /strategy [name]"""
    from strategies import list_strategies, get_strategy
    
    args = context.args
    if not args:
        names = list_strategies()
        msg = "📋 Loaded Strategies:\n" + "\n".join(f"• {n}" for n in names)
        await update.message.reply_text(msg)
        return
    
    genome = get_strategy(args[0])
    if not genome:
        await update.message.reply_text(f"❌ Strategy '{args[0]}' not found")
        return
    
    regime = genome.get("regime_fitness", {})
    msg = (
        f"📊 Strategy: {genome['name']} v{genome['version']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📝 {genome['thesis']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Symbol: {genome['symbol']}\n"
        f"Timeframe: {genome['timeframe']}\n"
        f"Regime Fitness:\n"
    )
    for r, score in sorted(regime.items(), key=lambda x: -x[1]):
        bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
        msg += f"  {r}: {bar} {score:.1f}\n"
    
    await update.message.reply_text(msg)

async def cmd_metrics(update, context):
    """Show current metrics summary."""
    from metrics.prometheus import (
        PNL_TODAY, WIN_RATE, BALANCE, OPEN_POSITIONS,
        DRAWDOWN, TRADES_TOTAL, RISK_REJECTIONS
    )
    
    # Read current gauge values
    msg = (
        f"📡 TSAR Metrics\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: ${BALANCE._value.get():.2f}\n"
        f"📈 P&L Today: ${PNL_TODAY._value.get():.2f}\n"
        f"📊 Open Positions: {int(OPEN_POSITIONS._value.get())}\n"
        f"📉 Drawdown: {DRAWDOWN._value.get():.2%}\n"
        f"🔢 Risk Rejections: {int(RISK_REJECTIONS._value.get())}\n"
        f"\nPrometheus: http://localhost:9090"
    )
    await update.message.reply_text(msg)
```

### 3.7 Walk-Forward Validation Framework (backtest/walk_forward.py)

**Purpose:** Ensure strategy parameters are not overfit to historical data. Split data into three windows and verify the strategy generalizes.

**Walk-Forward Protocol:**

```
|←── Train (70%) ──→|←── Validation (15%) ──→|←── Test (15%) ──→|
|   Optimize here    |   Check doesn't break  |   Final verdict   |
```

**Pass Criteria (test window must meet ALL):**

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Minimum trades | ≥ 10 | Statistical relevance |
| Sharpe ratio | > 0.5 | Positive risk-adjusted return |
| Max drawdown | < 20% | Survivable drawdown |
| Win rate | > 45% | Better than coin flip |

**Failure Modes Detected:**

| Failure | Diagnosis | Action |
|---------|-----------|--------|
| Train PASS, Test FAIL | Overfit to training data | Adjust parameters, re-validate |
| All windows FAIL | Strategy has no edge | Retire or redesign |
| Train FAIL | Parameters too restrictive | Widen entry conditions |
| High trades but low Sharpe | Many small losses | Tighten stop-loss |

---

## 4. MODIFICATIONS TO EXISTING DAY1 FILES

### 4.1 `config/settings.py` — Add Day30 Config Sections

```python
# ============================================
# REDIS (Day30 — caching only)
# ============================================
REDIS_CONFIG = {
    "url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    "enabled": True,  # Set False to disable caching (system works without it)
    "prefix": "tsar:",
}

# ============================================
# PROMETHEUS (Day30)
# ============================================
PROMETHEUS_CONFIG = {
    "enabled": True,
    "port": 9090,
}

# ============================================
# BACKTEST (Day30)
# ============================================
BACKTEST_CONFIG = {
    "default_days": 90,
    "cache_dir": "data/backtest_cache",
    "default_capital": 10000.0,
    "fees": 0.001,        # Binance 0.1%
    "slippage": 0.0003,   # 3 bps
    "walk_forward": {
        "train_pct": 0.70,
        "validation_pct": 0.15,
        "test_pct": 0.15,
        "min_trades": 10,
    }
}
```

### 4.2 `agents/signal_agent.py` — Multi-Strategy Scanning

**Change:** Instead of hardcoding Mean Reversion logic, the Signal Agent iterates over all loaded strategy genomes and runs each strategy's scan logic.

```python
# Key change in scan() method:
def scan(self) -> list[dict]:
    """Scan all active strategies. Returns list of signals."""
    from strategies import list_strategies, get_strategy
    
    signals = []
    for strategy_name in list_strategies():
        genome = get_strategy(strategy_name)
        if genome.get("status", "ACTIVE") != "ACTIVE":
            continue
        
        signal = self._scan_strategy(genome)
        if signal and signal["score"] > 0.6:
            signals.append(signal)
    
    return signals

def _scan_strategy(self, genome: dict) -> dict | None:
    """Scan a single strategy. Dispatches to strategy-specific logic."""
    name = genome["name"]
    if name == "mean_reversion":
        return self._scan_mean_reversion(genome)
    elif name == "momentum":
        return self._scan_momentum(genome)
    return None
```

### 4.3 `tools/market_tools.py` — Add MACD, ADX, EMA

```python
def calculate_macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Calculate MACD. Returns dict with macd, signal, histogram."""
    import pandas_ta as ta
    import pandas as pd
    series = pd.Series(closes)
    result = ta.macd(series, fast=fast, slow=slow, signal=signal)
    return {
        "macd": result.iloc[-1, 0],
        "signal": result.iloc[-1, 1],
        "histogram": result.iloc[-1, 2],
    }

def calculate_adx(highs: list, lows: list, closes: list, period: int = 14) -> dict:
    """Calculate ADX with +DI and -DI."""
    import pandas_ta as ta
    import pandas as pd
    h = pd.Series(highs)
    l = pd.Series(lows)
    c = pd.Series(closes)
    result = ta.adx(h, l, c, length=period)
    return {
        "adx": result.iloc[-1, 0],
        "plus_di": result.iloc[-1, 1],
        "minus_di": result.iloc[-1, 2],
    }

def calculate_ema(closes: list, period: int = 50) -> float:
    """Calculate Exponential Moving Average."""
    import pandas_ta as ta
    import pandas as pd
    return float(ta.ema(pd.Series(closes), length=period).iloc[-1])

def calculate_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """Calculate Average True Range."""
    import pandas_ta as ta
    import pandas as pd
    h = pd.Series(highs)
    l = pd.Series(lows)
    c = pd.Series(closes)
    return float(ta.atr(h, l, c, length=period).iloc[-1])
```

### 4.4 `main.py` — Initialize Day30 Components

```python
def main():
    logger = logging.getLogger(__name__)
    
    # ... existing setup ...
    
    # Day30: Initialize Redis (graceful — works without it)
    from cache.redis_client import get_client
    redis_ok = get_client() is not None
    logger.info(f"Redis: {'connected' if redis_ok else 'unavailable (caching disabled)'}")
    
    # Day30: Load strategy genomes
    from strategies import load_all_strategies
    genomes = load_all_strategies()
    logger.info(f"Strategies loaded: {list(genomes.keys())}")
    
    # Day30: Start Prometheus metrics server
    from metrics.prometheus import init_metrics
    from config.settings import PROMETHEUS_CONFIG
    if PROMETHEUS_CONFIG["enabled"]:
        init_metrics(PROMETHEUS_CONFIG["port"])
        logger.info(f"Prometheus metrics on :{PROMETHEUS_CONFIG['port']}")
    
    # ... existing orchestrator run ...
```

---

## 5. DATABASE CHANGES

**No schema changes.** Day30 reuses the existing Day1 `tsar.db` schema. Backtest results are NOT stored in the database — they're reported via Telegram and discarded. This keeps the database clean and avoids schema migration complexity.

**One optional addition** (if desired): a `backtest_runs` table to log backtest history.

```sql
-- Optional: Log backtest runs for historical reference
CREATE TABLE IF NOT EXISTS backtest_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT NOT NULL,
    parameters      TEXT,              -- JSON snapshot of genome params
    data_range      TEXT,              -- '2026-04-01 to 2026-07-01'
    total_return    REAL,
    sharpe_ratio    REAL,
    max_drawdown    REAL,
    win_rate        REAL,
    total_trades    INTEGER,
    verdict         TEXT,              -- PASS or FAIL
    run_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

This table is optional. The system works without it. It's useful for tracking which parameter sets have been tested over time.

---

## 6. BUILD PLAN — 2-WEEK SPRINTS

### Sprint 1: Cache + Genome Foundation (Weeks 1–2)

**Goal:** Redis caching works. Strategy genomes load. Momentum strategy exists.

| Day | Task | Deliverable |
|-----|------|-------------|
| 1 | Install Redis (Docker or local). Add `redis` to requirements.txt. | Redis running locally |
| 2 | Write `cache/redis_client.py` with graceful degradation | Redis client that works or fails silently |
| 3 | Write `cache/price_cache.py` — price, OHLCV, indicator caching | get/set/invalidate with TTL |
| 4 | Integrate cache into `market_tools.py` (get_price, get_ohlcv) | Cached price lookups |
| 5 | Write `config/strategies/mean_reversion.yaml` genome | MR strategy as YAML |
| 6 | Write `config/strategies/momentum.yaml` genome | Momentum strategy as YAML |
| 7 | Write `strategies/__init__.py` registry (load_all, get, list) | Genome loader |
| 8 | Write MACD, ADX, EMA, ATR functions in `market_tools.py` | New indicators available |
| 9 | Write `strategies/momentum.py` — MACD + ADX signal logic | Momentum strategy code |
| 10 | Modify `signal_agent.py` for multi-strategy scanning | Iterates over all strategies |
| 11 | Unit tests for cache layer (`test_cache.py`) | Cache tests pass |
| 12 | Unit tests for momentum strategy | Momentum tests pass |
| 13–14 | Integration test: 2-strategy scan → risk → notify | Both strategies produce signals |

**Sprint 1 Exit Criteria:**
- [ ] Redis caches price data (30s TTL)
- [ ] Both strategy genomes load from YAML
- [ ] Momentum strategy generates valid signals
- [ ] Signal Agent scans both strategies per cycle
- [ ] All existing Day1 tests still pass

### Sprint 2: Backtest + Metrics + Bot (Weeks 3–4)

**Goal:** Backtest engine works. Walk-forward validates. Prometheus exposes metrics. Telegram has new commands.

| Day | Task | Deliverable |
|-----|------|-------------|
| 15 | Install `vectorbt` and `prometheus-client`. Pin versions. | Dependencies added |
| 16 | Write `backtest/data_loader.py` — fetch & cache historical OHLCV | Data downloader with parquet cache |
| 17 | Write `backtest/engine.py` — vectorbt wrapper for MR strategy | Can backtest MR |
| 18 | Extend `backtest/engine.py` — add momentum strategy support | Can backtest Momentum |
| 19 | Write `backtest/walk_forward.py` — train/val/test split | Walk-forward framework |
| 20 | Write `backtest/report.py` — text + Telegram-friendly output | Formatted backtest reports |
| 21 | Write `metrics/prometheus.py` — all gauges and counters | Prometheus metrics defined |
| 22 | Write `prometheus_server.py` — standalone HTTP exporter | Metrics on :9090 |
| 23 | Integrate metrics into `orchestrator.py` (update on trade) | Metrics update automatically |
| 24 | Add `/backtest`, `/backtest_wf`, `/strategy`, `/metrics` commands to Telegram bot | New bot commands work |
| 25 | Write `test_backtest.py` — backtest engine tests | Backtest tests pass |
| 26 | Write `test_walk_forward.py` — WF validation tests | WF tests pass |
| 27 | End-to-end test: Telegram `/backtest momentum 90` | Returns formatted results |
| 28 | Documentation update, README Day30 section | Docs complete |

**Sprint 2 Exit Criteria:**
- [ ] `/backtest mean_reversion 90` returns Sharpe, WR, DD, trades
- [ ] `/backtest_wf momentum 180` returns train/val/test verdict
- [ ] `/strategy` lists both genomes with parameters
- [ ] Prometheus metrics scrapeable at :9090
- [ ] Grafana can connect and show tsar_* metrics
- [ ] All Day1 + Sprint 1 tests still pass

### Sprint 3: Polish + Validation (Weeks 5–6, optional buffer)

**Goal:** Validate everything works together. Fix edge cases. Prepare for Level 2.

| Day | Task | Deliverable |
|-----|------|-------------|
| 29 | Walk-forward validate BOTH strategies on 180d data | Both strategies validated |
| 30 | Run live paper trading with 2 strategies for 3 days | 2-strategy paper trading works |
| 31 | Review backtest vs live performance gap | Gap analysis documented |
| 32 | Tune genome parameters based on backtest/live comparison | Updated YAML genomes |
| 33 | Load test: Prometheus under 1000+ trades | Metrics don't lag |
| 34 | Redis failure test: kill Redis, verify system continues | Graceful degradation confirmed |
| 35 | Security review: no secrets in logs, cache, or Telegram | Security pass |
| 36 | Final integration test, all Day30 features | Everything green |
| 37–42 | Buffer for bugs, edge cases, documentation | Ship-ready |

---

## 7. SUCCESS CRITERIA

Day30 is **DONE** when ALL of the following are true:

### Functional Criteria

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | Two strategies loaded from YAML genomes | `/strategy` shows both |
| 2 | Momentum strategy generates valid signals | Paper trade with momentum for 3 days |
| 3 | Backtest engine produces results for both strategies | `/backtest momentum 90` returns data |
| 4 | Walk-forward validation runs and produces verdict | `/backtest_wf mean_reversion 180` returns PASS/FAIL |
| 5 | Redis caches price data (reduces API calls) | Monitor ccxt call count with vs without Redis |
| 6 | Prometheus metrics scrapeable | `curl localhost:9090` returns metrics |
| 7 | All 4 new Telegram commands work | Manual test each command |
| 8 | System works identically without Redis (graceful degradation) | Kill Redis, verify no errors |
| 9 | All existing Day1 tests still pass | `pytest` green |
| 10 | ≤25 direct Python packages | `pip list \| wc -l` ≤ 25 + transitive |

### Performance Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Price lookup latency (cached) | < 5ms | Time cache hit |
| Price lookup latency (uncached) | < 500ms | Time ccxt call |
| Backtest 90d MR strategy | < 30 seconds | Time `/backtest` command |
| Backtest 90d Momentum strategy | < 30 seconds | Time `/backtest` command |
| Walk-forward 180d | < 90 seconds | Time `/backtest_wf` command |
| Prometheus scrape latency | < 10ms | Prometheus scrape duration |
| Memory overhead (Redis) | < 50MB | `redis-cli info memory` |
| Signal scan cycle (2 strategies) | < 10 seconds | Log timestamp delta |

### Quality Criteria

| Criterion | Threshold |
|-----------|-----------|
| Unit test coverage (new code) | > 80% |
| Integration tests | ≥ 3 (cache, backtest, multi-strategy) |
| No regressions in Day1 tests | 0 failures |
| No new security findings (bandit) | 0 high/critical |
| Documentation complete | README updated, all new commands documented |

---

## 8. WHAT DAY30 ENABLES FOR LEVEL 2

After Day30, the path to Level 2 becomes incremental rather than a cliff:

| Level 2 Feature | Day30 Foundation | Gap to Close |
|-----------------|------------------|--------------|
| Redis Streams | Already have Redis client + connection management | Add Streams (pub/sub, consumer groups) |
| Macro Agent | Strategy genome pattern established | Add 4th agent + macro data sources |
| vectorbt backtesting | Engine exists, walk-forward validated | Wire into live strategy rotation |
| Walk-forward validation | Framework exists | Automate periodic re-validation |
| Prometheus + Grafana | Metrics exported | Add Grafana dashboards + alerting |
| Strategy retirement | Genome + performance tracking exists | Add automated retirement gates |
| Immutable audit log | Trade logging exists | Add JSONL hash chain layer |
| Position reconciliation | Execution Agent tracks positions | Add periodic reconciliation loop |
| Data quality pipeline | Data loader exists | Add 6 quality checks |
| Counterparty risk | Single exchange baseline | Add multi-exchange health scoring |

**Key insight:** Day30 eliminates 60% of Level 2's novel code. The remaining 40% is additive, not foundational.

---

## 9. RISK REGISTER

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| vectorbt version conflicts with pandas | Medium | High | Pin exact versions. Test import on Day 1 of Sprint 2. |
| Redis unavailable in production | Low | Low | Graceful degradation — system works without it |
| Overfitting in backtests | High | Medium | Walk-forward validation catches this. Require test window pass. |
| Momentum strategy underperforms | Medium | Low | It's a second strategy, not a replacement. MR still runs. |
| Prometheus port conflicts | Low | Low | Configurable port. Default 9090, change in settings.py. |
| Memory pressure from vectorbt | Medium | Medium | vectorbt imports numba (heavy). Import lazily, not at startup. |
| Scope creep into Level 2 | High | High | Hard constraint: no Redis Streams, no new agents, no Rust. |

---

## 10. CONSTRAINT COMPLIANCE CHECKLIST

| Constraint | Day30 Compliance | Evidence |
|------------|-----------------|----------|
| Still pure Python | ✅ | No Rust files. All `.py`. |
| Still ≤25 packages | ✅ | 22 direct packages (4 new: redis, vectorbt, prometheus-client, pyyaml) |
| Still 3 agents | ✅ | Signal, Risk, Execution — unchanged count |
| Still 1 database | ✅ | `tsar.db` — same file, same schema |
| Buildable in 4-6 weeks | ✅ | 3 sprints × 2 weeks = 6 weeks (with 2-week buffer) |
| Incremental from Day1 | ✅ | 16 new files, 8 modified, 0 deleted |
| No Redis Streams | ✅ | Redis used for cache only (GET/SET with TTL) |
| No new agents | ✅ | 3 agents, same as Day1 |

---

## APPENDIX A: COMPLETE requirements.txt (Day30)

```txt
# requirements.txt — TSAR Day30
# Total direct packages: 22

# Exchange connectivity
ccxt==4.4.50

# Data & computation
pandas==2.2.3
numpy==2.2.1
pandas-ta==0.3.14b1

# LLM integration
ollama==0.4.7
openai==1.61.0

# Notifications
python-telegram-bot==21.10

# Scheduling
apscheduler==3.11.0

# Environment
python-dotenv==1.1.0

# Testing
pytest==8.3.4

# Plotting (local analysis)
matplotlib==3.10.1

# === DAY30 ADDITIONS ===

# Redis caching
redis==5.2.1

# Backtesting engine
vectorbt==0.26.3

# Prometheus metrics
prometheus-client==0.21.1

# Strategy genome YAML
pyyaml==6.0.2
```

---

## APPENDIX B: ROLLBACK PLAN

If Day30 introduces instability, rollback is safe because:

1. **Redis is optional.** Kill Redis → system falls back to live data. No data loss.
2. **Strategy genomes are additive.** Delete `momentum.yaml` → only MR runs.
3. **Backtest is standalone.** Delete `backtest/` directory → live trading unaffected.
4. **Prometheus is optional.** Disable in config → no metrics, no impact.
5. **Telegram commands are additive.** New commands don't change existing ones.

**Rollback steps:**
```bash
# Nuclear rollback to Day1
git checkout day1-stable
# Selective rollback (keep Day30 code, disable features)
# In config/settings.py:
REDIS_CONFIG["enabled"] = False
PROMETHEUS_CONFIG["enabled"] = False
# Remove momentum.yaml from config/strategies/
```

---

*Day30 exists to make Level 2 achievable. It adds real capabilities (backtesting, multi-strategy, metrics, caching) without adding architectural complexity. Build it after Day1 is stable. Ship it. Then Level 2 becomes a series of small steps instead of a giant leap.*

*The Chief Engineer was right: the gap between Day1 and Level 2 is too wide. Day30 is the bridge.*
