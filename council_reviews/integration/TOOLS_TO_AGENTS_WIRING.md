# Tools-to-Agents Wiring — Integration Summary

**Date:** 2026-07-30  
**Status:** ✅ COMPLETE  
**Scope:** 10 agents wired to 68+ domain tools across 11 files  

---

## Overview

All 10 TSAR agents now import, initialize, and use domain tools from `src/tools/`. The wiring replaces inline logic with structured tool calls where applicable, while preserving backward compatibility through fallback paths.

## Agent-to-Tool Mapping

### 1. Signal Scout (`signal_scout.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `MarketDataTools` | Order book depth, volume profile | Initialized in `on_initialize`, wraps `ExchangeGateway` |
| `TechnicalAnalysisTools` | ADX, Stochastic, VWAP, Ichimoku, Fibonacci, patterns, divergence | Advanced indicator analysis beyond basic RSI/MACD |
| `MultiTimeframeAnalyzer` | Cross-timeframe confluence zones | Replaces inline `_compute_mtf_confluence` for 4h/1h/15m analysis |
| `VolatilityAnalyzer` | Volatility regime classification | `classify_volatility_regime()` → position size factor in signal metadata |
| `CorrelationAnalyzer` | Cross-asset correlation | Available for correlation-aware signal scoring |
| `PatternRecognitionTools` | Chart + candlestick pattern detection | `detect_chart_patterns()` + `detect_candlestick_patterns()` → patterns in signal metadata |

**Changes:**
- Added 6 tool imports and constructor initialization
- `_scan_symbol()`: Added volatility regime analysis and pattern recognition scan after indicator calculation
- `_compute_mtf_confluence()`: Now tries `MultiTimeframeAnalyzer.analyze()` first, falls back to inline computation
- Signal metadata enriched with `volatility_regime`, `vol_position_factor`, `patterns_detected`

---

### 2. Risk Guardian (`risk_guardian.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `RiskManagementTools` | Exposure limits, VaR, stress testing | `check_exposure_limits()` added as Check 11 in risk evaluation |
| `StopLossCalculator` | ATR/percentage/support-based stop validation | Validates stop-loss in `_calculate_position_size()` |
| `TakeProfitCalculator` | R:R-based and resistance-based TP | Available for TP validation |
| `FeeCalculator` | Fee-adjusted R:R ratio | `net_risk_reward()` → fee-adjusted position sizing |

**Changes:**
- Added 4 tool imports and constructor initialization
- `on_initialize()`: Creates all 4 tool instances
- `_calculate_position_size()`: Now validates SL via `StopLossCalculator`, computes fee-adjusted R:R via `FeeCalculator`
- `_run_all_checks()`: Added Check 11 (exposure limits) via `RiskManagementTools.check_exposure_limits()`

---

### 3. Execution Sniper (`execution_sniper.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `ExecutionTools` | Order placement, slippage recording, fill quality | `record_slippage()` for persistent slippage tracking |
| `SmartOrderRouter` | TWAP/iceberg for large orders | `smart_route()` for orders > $10k notional |
| `MarketDataTools` | Order book depth for execution decisions | Available for spread analysis |

**Changes:**
- Added 3 tool imports and constructor initialization
- `on_initialize()`: Creates ExecutionTools, SmartOrderRouter, MarketDataTools
- `_execute_approved_signal()`: Large orders (> $10k) routed through `SmartOrderRouter.smart_route()` with fallback to direct execution
- Added `_place_entry_order_routed()` method for router-based execution
- Slippage now recorded via `ExecutionTools.record_slippage()` after each fill

---

### 4. Trade Philosopher (`trade_philosopher.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `KnowledgeTools` | Trade memory, lesson archive, pattern library | Auto-wires `trade_memory` and `lesson_archive` from KnowledgeTools |
| `PatternLibrary` | Pattern matching against reflections | `match_pattern()` after reflection generation |

**Changes:**
- Added `KnowledgeTools` import
- Constructor: Added `_knowledge_tools` and `_db_path`
- Added `on_initialize()`: Creates `KnowledgeTools`, wires `trade_memory` and `lesson_archive`
- `run_cycle()`: After lesson archive storage, matches pattern tags against `pattern_library`

---

### 5. Strategy Geneticist (`strategy_geneticist.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `KnowledgeTools` | Strategy genomes store | `strategy_genomes` wired from KnowledgeTools |
| `BacktestingTools` | Backtest execution, walk-forward, Monte Carlo | Available alongside existing BacktestEngine |

**Changes:**
- Added `KnowledgeTools` and `BacktestingTools` imports
- Constructor: Added `_knowledge_tools` and `_backtesting_tools`
- `on_initialize()`: Creates KnowledgeTools (wires genomes), creates BacktestingTools

---

### 6. Regime Detector (`regime_detector.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `MarketDataTools` | OHLCV data, order book | Wraps ExchangeGateway |
| `TechnicalAnalysisTools` | ADX, Stochastic, VWAP | Advanced indicator analysis |
| `VolatilityAnalyzer` | Volatility regime classification | `classify_volatility_regime()` → stored in regime indicators |
| `CorrelationAnalyzer` | Cross-asset correlation | Available for correlation-aware regime detection |

**Changes:**
- Added 4 tool imports and constructor initialization
- Added `on_initialize()`: Initializes pricing engine and all 4 tools
- `_classify_symbol()`: Added volatility regime analysis via `VolatilityAnalyzer.classify_volatility_regime()` before HMM classification
- Regime state indicators enriched with `volatility_regime` field

---

### 7. Market Cartographer (`market_cartographer.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `CorrelationAnalyzer` | Rolling correlation, cointegration | Available alongside inline CorrelationEngine |
| `MarketDataTools` | OHLCV data, order book | Wraps ExchangeGateway |
| `FundamentalAnalysisTools` | Project fundamentals, market structure | Available for fundamental context |

**Changes:**
- Added 3 tool imports and constructor initialization
- `on_initialize()`: Creates CorrelationAnalyzer, MarketDataTools, FundamentalAnalysisTools

---

### 8. Macro Agent (`macro_agent.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `FundamentalAnalysisTools` | Project fundamentals, TVL, GitHub activity | Available for fundamental analysis |
| `EconomicCalendarTools` | Economic event calendar | Available for macro event context |
| `SocialSentimentAnalyzer` | Social sentiment from multiple sources | Available for sentiment enrichment |
| `NewsAggregator` | News aggregation and analysis | Available for news context |

**Changes:**
- Added 4 tool imports and constructor initialization
- `on_initialize()`: Creates all 4 tools
- Added `_enrich_with_tools()` method for sentiment/news/calendar enrichment
- `run_cycle()`: Calls `_enrich_with_tools()` before regime classification

---

### 9. Execution Tracker (`execution_tracker.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `ExecutionTools` | Slippage stats, fill quality | `get_slippage_stats()` for monitoring state |
| `PnLTracker` | Real-time P&L tracking | Initialized for trade P&L monitoring |
| `WinRateTracker` | Running win rate computation | Initialized for win rate tracking |
| `EquityCurve` | Equity curve with drawdown | Initialized for equity visualization |
| `RiskStateMonitor` | Risk level monitoring | Available for risk state tracking |
| `AlertGenerator` | Trade/risk/system alerts | Available for alert generation |

**Changes:**
- Added 6 tool imports and constructor initialization
- Added `on_initialize()`: Creates ExecutionTools, PnLTracker, WinRateTracker, EquityCurve
- Added `_update_monitoring_state()` method called each reconciliation cycle
- `run_cycle()`: Now calls `_update_monitoring_state()` after reconciliation

---

### 10. Orchestrator (`orchestrator.py`)

| Tool | Usage | Integration Point |
|------|-------|-------------------|
| `KnowledgeTools` | Shadow extraction pipeline access | Strategy genomes, trade memory for flywheel |
| `PnLTracker` | System-wide P&L visibility | Initialized for pipeline monitoring |
| `WinRateTracker` | System-wide win rate | Initialized for pipeline monitoring |
| `AlertGenerator` | System-wide alerts | Initialized for pipeline monitoring |

**Changes:**
- Added KnowledgeTools, PnLTracker, WinRateTracker, AlertGenerator imports
- Constructor: Added 4 tool references
- Added `_initialize_orchestrator_tools()` method called during `on_initialize()`
- `on_initialize()`: Calls `_initialize_orchestrator_tools()` before shadow loop init

---

## Tools Registry Update (`src/tools/__init__.py`)

Added registrations for:
- `multi_timeframe` → `MultiTimeframeAnalyzer`
- `pnl_tracker` → `PnLTracker`
- `win_rate_tracker` → `WinRateTracker`
- `equity_curve` → `EquityCurve`
- `risk_state_monitor` → `RiskStateMonitor`
- `alert_generator` → `AlertGenerator`

**Total registered tools:** 24 (up from 18)

---

## Wiring Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                              │
│  KnowledgeTools · PnLTracker · WinRateTracker · AlertGenerator  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ SIGNAL SCOUT │→ │RISK GUARDIAN │→ │  EXECUTION SNIPER    │  │
│  │ MarketData   │  │ RiskMgmt     │  │  Execution           │  │
│  │ TA           │  │ StopLoss     │  │  OrderRouter         │  │
│  │ MultiTF      │  │ TakeProfit   │  │  MarketData          │  │
│  │ Volatility   │  │ FeeCalc      │  │                      │  │
│  │ Correlation  │  │              │  │                      │  │
│  │ PatternRecog │  │              │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │TRADE PHIL.   │  │STRATEGY GEN. │  │  REGIME DETECTOR     │  │
│  │ Knowledge    │  │ Knowledge    │  │  MarketData          │  │
│  │ (memory,     │  │ (genomes)    │  │  TA                  │  │
│  │  lessons,    │  │ Backtesting  │  │  Volatility          │  │
│  │  patterns)   │  │              │  │  Correlation         │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │MARKET CARTO. │  │ MACRO AGENT  │  │ EXECUTION TRACKER    │  │
│  │ Correlation  │  │ Fundamental  │  │  Execution           │  │
│  │ MarketData   │  │ EconCalendar │  │  PnLTracker          │  │
│  │ Fundamental  │  │ Sentiment    │  │  WinRateTracker      │  │
│  │              │  │ News         │  │  EquityCurve         │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Files Modified

| File | Changes |
|------|---------|
| `src/agents/signal_scout.py` | +6 tool imports, +6 constructor refs, +on_initialize tools, +volatility/pattern analysis, +MTF tool usage, +metadata enrichment |
| `src/agents/risk_guardian.py` | +4 tool imports, +4 constructor refs, +on_initialize tools, +fee-adjusted sizing, +exposure check |
| `src/agents/execution_sniper.py` | +3 tool imports, +3 constructor refs, +on_initialize tools, +smart routing, +slippage recording |
| `src/agents/trade_philosopher.py` | +1 tool import, +2 constructor refs, +on_initialize, +pattern matching |
| `src/agents/strategy_geneticist.py` | +2 tool imports, +2 constructor refs, +on_initialize tools |
| `src/agents/regime_detector.py` | +4 tool imports, +4 constructor refs, +on_initialize, +volatility regime |
| `src/agents/market_cartographer.py` | +3 tool imports, +3 constructor refs, +on_initialize tools |
| `src/agents/macro_agent.py` | +4 tool imports, +4 constructor refs, +on_initialize tools, +enrichment method |
| `src/agents/execution_tracker.py` | +6 tool imports, +6 constructor refs, +on_initialize, +monitoring state update |
| `src/agents/orchestrator.py` | +3 tool imports, +4 constructor refs, +orchestrator tools init |
| `src/tools/__init__.py` | +6 tool registrations (multi_timeframe, monitoring tools) |

## Design Principles

1. **Lazy initialization**: All tools created in `on_initialize()`, not `__init__()`, to avoid import-time failures
2. **Graceful degradation**: Tool failures are caught and logged; agents fall back to inline logic
3. **No breaking changes**: Existing agent APIs preserved; tools are additive
4. **Constructor injection ready**: Tool references stored as instance variables for testing/mocking
5. **Backward compatible**: Inline logic preserved as fallback when tools unavailable
