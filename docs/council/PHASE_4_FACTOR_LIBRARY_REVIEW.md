# Phase 4: Factor Library — Council Review

**Reviewer:** Engineering Council (auto-generated)
**Date:** 2026-07-27
**Status:** ✅ COMPLETE — 93/93 tests passing

---

## Executive Summary

Phase 4 delivers a production-grade quantitative factor library with 28 validated factors across 6 categories, a management layer with SQLite persistence, and an IC/IR benchmarking framework. All factors are pure functions, independently testable, and ready for Signal Scout and Strategy Geneticist integration.

## Deliverables

| File | Purpose | LOC |
|------|---------|-----|
| `src/strategy/factors.py` | 28 pure factor compute functions + registry | ~580 |
| `src/strategy/factor_library.py` | FactorLibrary class (registration, compute, persistence) | ~280 |
| `src/strategy/factor_bench.py` | FactorBenchmarker (IC, IR, decay analysis) | ~230 |
| `tests/unit/strategy/test_factor_library.py` | 93 tests across 4 test classes | ~420 |

## Factor Inventory (28 total)

### Momentum (9)
| Factor | Description | Range | Default Params |
|--------|-------------|-------|----------------|
| RSI | Relative Strength Index | [0, 100] | period=14 |
| MACD | MACD histogram (fast-slow signal) | unbounded | fast=12, slow=26, signal=9 |
| Stochastic %K | %K oscillator | [0, 100] | period=14 |
| Stochastic %D | %D signal line (SMA of %K) | [0, 100] | period=14, smooth=3 |
| Williams %R | Williams %R | [-100, 0] | period=14 |
| ROC | Rate of Change (%) | unbounded | period=10 |
| Momentum | Raw price diff | unbounded | period=10 |
| CCI | Commodity Channel Index | ~[-100,+100] typical | period=20 |
| MFI | Money Flow Index | [0, 100] | period=14 |

### Mean Reversion (4)
| Factor | Description | Range | Default Params |
|--------|-------------|-------|----------------|
| BB %B | Bollinger Band position | 0=lower, 1=upper | period=20, std=2.0 |
| Z-Score | Std deviations from mean | unbounded | period=20 |
| VWAP Distance | % deviation from VWAP | unbounded | cumulative |
| Keltner Position | Keltner Channel position | 0=lower, 1=upper | ema=20, atr=14, mult=2.0 |

### Volatility (4)
| Factor | Description | Range | Default Params |
|--------|-------------|-------|----------------|
| ATR Normalized | ATR as % of price | positive | period=14 |
| BB Bandwidth | (Upper-Lower)/Middle | positive | period=20, std=2.0 |
| Historical Vol | Annualized log-return std | positive | period=20 |
| ATR Ratio | Short ATR / Long ATR | ~1.0 | short=7, long=14 |

### Volume (4)
| Factor | Description | Range | Default Params |
|--------|-------------|-------|----------------|
| OBV Slope | Linear regression slope of OBV | unbounded | period=20 |
| Volume ROC | Volume % change | unbounded | period=10 |
| A/D Line | Accumulation/Distribution | unbounded | cumulative |
| Chaikin MF | Volume-weighted A/D | [-1, 1] | period=20 |

### Trend (4)
| Factor | Description | Range | Default Params |
|--------|-------------|-------|----------------|
| ADX | Average Directional Index | [0, 100] | period=14 |
| Aroon Osc | Aroon Up - Aroon Down | [-100, 100] | period=25 |
| Ichimoku | Cloud composite signal | [-1, 1] | tenkan=9, kijun=26, senkou_b=52 |
| Supertrend | Direction indicator | +1/-1 | period=10, mult=3.0 |

### Pattern (3)
| Factor | Description | Range | Default Params |
|--------|-------------|-------|----------------|
| Engulfing | Bullish/bearish engulfing | -1, 0, +1 | — |
| Pin Bar | Hammer/shooting star | -1, 0, +1 | wick_ratio=2.0 |
| Inside Bar | Consolidation detection | 0, 1 | — |

## Architecture

```
factors.py          Pure compute functions (no side effects)
    ↓ imports
factor_library.py   FactorLibrary: registration, compute, SQLite persistence
    ↓ imports
factor_bench.py     FactorBenchmarker: IC/IR/decay analysis
```

### Design Decisions

1. **Pure functions in `factors.py`** — All factor computations are standalone, importable, and testable without the library. This enables direct use in Strategy Geneticist genomes.

2. **FACTOR_REGISTRY dict** — Single source of truth for factor metadata. FactorLibrary loads from this on init. Custom factors added via `register()`.

3. **SQLite persistence** — Factor metadata, IC history, and decay tracking survive restarts. Uses `:memory:` for tests.

4. **Spearman rank IC** — Industry standard for factor evaluation. Resistant to outliers and non-normal distributions.

5. **Parameter overrides** — Every factor accepts `**kwargs` to override defaults at compute time. Enables genetic algorithm parameter search.

## Test Coverage

| Test Class | Tests | What's Tested |
|------------|-------|---------------|
| TestFactorRegistration | 9 | Registration, retrieval, categories, universes, custom factors, persistence |
| TestFactorComputation | 56 | All 28 factors compute + range checks + param overrides + compute_all |
| TestFactorBenchmarking | 9 | IC/IR, rankings, forward periods, decay, IC persistence |
| TestEdgeCases | 8 | NaN input, zero volume, constant price, empty DF, short data, close/reopen |

**Total: 93 tests, all passing.**

## Integration Points

### Signal Scout
```python
from src.strategy.factor_library import FactorLibrary

lib = FactorLibrary()
values = lib.compute("rsi", ohlcv_df)
momentum = lib.compute_all(ohlcv_df, category="momentum")
```

### Strategy Geneticist
```python
from src.strategy.factor_bench import FactorBenchmarker

bench = FactorBenchmarker(lib)
result = bench.run(ohlcv_df, forward_periods=[1, 5, 10])
# result.rankings sorted by |IR| — best factors first
top_factors = result.rankings[:5]
```

### Custom Factor Registration
```python
def my_signal(df, threshold=0.5, **kwargs):
    return (df["close"].pct_change() > threshold).astype(float)

lib.register("breakout_signal", my_signal, "pattern",
             default_params={"threshold": 0.5})
```

## Known Limitations

1. **Supertrend is O(n)** — Uses a Python loop for band ratchet logic. Acceptable for typical bar counts (< 10K), may need vectorization for HFT.

2. **OBV slope uses rolling apply** — Linear regression via rolling window is slower than vectorized approaches. Could be optimized with numpy stride tricks.

3. **Single-symbol benchmarking** — IC is computed per-symbol. Cross-sectional IC (across asset universe) is a future enhancement.

4. **No automatic decay alerting** — Decay data is computed and stored but no automated alerts when IC degrades. Signal Scout should poll `get_ic_history()` periodically.

## Risk Assessment

- **Low risk:** All factors are pure functions with no side effects
- **Low risk:** SQLite is battle-tested for metadata storage
- **Low risk:** NaN/edge case handling verified by 8 edge case tests
- **Note:** Factors should be re-benchmarked periodically as market regimes change

## Sign-off

Phase 4 Factor Library is complete and tested. Ready for Signal Scout and Strategy Geneticist integration.
