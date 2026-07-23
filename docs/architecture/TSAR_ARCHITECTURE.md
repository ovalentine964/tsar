# TSAR — TRADING SUPER AGENT REGIME
## CONSOLIDATED ARCHITECTURE — SINGLE SOURCE OF TRUTH

**Version:** 2.0.0  
**Date:** 2026-07-24  
**Authority:** This document is the CANONICAL architecture. All engineering references this document. Where any prior document conflicts, this document wins.  
**Status:** FINAL — Approved for Engineering  
**Lead Architect Sign-off:** Pending

---

## 1. SYSTEM OVERVIEW

### 1.1 What TSAR Is

TSAR (Trading Super Agent Regime) is a **self-improving autonomous trading system** that:

1. Finds statistical edges in liquid markets
2. Sizes them correctly under strict risk constraints
3. Executes them flawlessly with minimal slippage
4. Gets measurably better at all three with every single trade

**One Sentence Thesis:** TSAR is not a bot that executes trades — it is a **self-improving market intelligence system** that accumulates proprietary knowledge about how markets behave, encodes that knowledge into executable strategies, and gets measurably better every time it runs.

### 1.2 The Super Agent Definition (Jensen Huang Standard)

A Super Agent is **domain-specific, built for ONE job**. It satisfies four criteria:

| Criterion | TSAR Implementation |
|-----------|-------------------|
| **Proprietary Knowledge** | 5 knowledge stores that compound over time (Trade Memory, Strategy Genomes, Pattern Library, Lesson Archive, Regime History) |
| **Learning Loop** | TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT cycle runs after every trade |
| **Flywheel** | Every trade generates data → data generates insights → insights improve strategies → better strategies generate better trades |
| **Harness** | Risk management, execution, and monitoring are deterministic subsystems that the intelligence layer cannot override |

### 1.3 Institutional Grade (8-Layer Coverage)

| Layer | Day1 Coverage | Full Architecture | Target |
|-------|-------------|-------------------|--------|
| 1. Market Analysis | 15% | 85% | 90%+ |
| 2. Strategy & Portfolio | 30% | 75% | 85%+ |
| 3. Execution | 40% | 80% | 90%+ |
| 4. Risk Management | 85% | 95% | 95%+ |
| 5. Data Infrastructure | 35% | 70% | 80%+ |
| 6. Operations | 25% | 65% | 80%+ |
| 7. Compliance | 30% | 60% | 80%+ |
| 8. Portfolio Management | 15% | 55% | 75%+ |

### 1.4 Capital & Scaling Path

| Stage | Capital | Agents | Strategies | Markets | Timeline |
|-------|---------|--------|------------|---------|----------|
| **Day1** | $10 | 3 | 1 (Mean Reversion) | BTC/USDT | Weeks 1-4 |
| **Level 2** | $10-100 | 4 | 2 (MR + Momentum) | BTC, ETH | Months 2-3 |
| **Level 3** | $100-1K | 4+ | 3-5 | Crypto + Forex | Months 4-6 |
| **Level 4** | $1K-10K | 4+ | 5+ | Multi-asset | Months 7-12 |

---

## 2. AGENTS — FULL SPECIFICATION

### 2.1 Agent Registry (Canonical)

| # | Agent | Role | Permission | Day1 | Level2 | Full |
|---|-------|------|------------|------|--------|------|
| 1 | **Signal Scout** | Scan markets for setups, generate signals | TRADE_PREVIEW | ✅ | ✅ | ✅ |
| 2 | **Risk Guardian** | Gatekeeper — approve/reject every trade | TRADE_ADMIN | ✅ | ✅ | ✅ |
| 3 | **Execution Sniper** | Place orders, manage positions | TRADE_EXECUTE | ✅ | ✅ | ✅ |
| 4 | **Macro Agent** | Macro regime, economic calendar, sentiment | ANALYSIS | — | ✅ | ✅ |
| 5 | **Regime Detector** | Classify market regime (HMM) | ANALYSIS | — | — | ✅ |
| 6 | **Trade Philosopher** | Post-trade reflection & lesson extraction | ANALYSIS | — | — | ✅ |
| 7 | **Strategy Geneticist** | Strategy evolution, backtesting, retirement | ANALYSIS | — | — | ✅ |
| 8 | **Market Cartographer** | Cross-asset correlation, structural analysis | ANALYSIS | — | — | ✅ |
| 9 | **Execution Tracker** | Position reconciliation, fill monitoring | TRADE_EXECUTE | — | — | ✅ |
| 10 | **Orchestrator** | Supervisor, health monitoring, alert routing | TRADE_ADMIN | ✅ (inline) | ✅ | ✅ |

### 2.2 Agent Communication Protocol

**Transport:** Redis Streams  
**Prefix:** `tsar:stream:*` (canonical)  
**Format:** MessagePack (binary) with JSON fallback for debugging  
**Envelope:** Every message wrapped in `MessageEnvelope`

```
MessageEnvelope:
  id: ULID                    # Globally unique, time-sortable
  timestamp_ns: int64         # Nanosecond precision
  trace_id: string            # End-to-end trace (propagated across agents)
  priority: int               # 0=low, 1=normal, 2=high, 3=critical
  source_agent: string        # Publishing agent name
  payload_type: string        # Type discriminator for deserialization
  payload: bytes              # Serialized payload (MessagePack or JSON)
```

### 2.3 Stream Topology (Canonical)

```
Stream Name                    Producers               Consumers
─────────────────────────────────────────────────────────────────────────
tsar:stream:regime             Regime Detector          Signal Scout, Risk Guardian,
                                                        Strategy Geneticist,
                                                        Market Cartographer

tsar:stream:signals            Signal Scout             Risk Guardian, Strategy
                                                        Geneticist

tsar:stream:risk_decisions     Risk Guardian            Execution Sniper, Trade
                                                        Philosopher

tsar:stream:orders             Execution Sniper         Execution Tracker

tsar:stream:fills              Execution Tracker        Trade Philosopher,
                                                        Risk Guardian,
                                                        Market Cartographer

tsar:stream:positions          Execution Tracker        Risk Guardian,
                                                        Trade Philosopher,
                                                        Strategy Geneticist

tsar:stream:analytics          Trade Philosopher        Strategy Geneticist,
                                                        Regime Detector

tsar:stream:cartography        Market Cartographer      Regime Detector,
                                                        Signal Scout, Risk Guardian

tsar:stream:strategy_mutations Strategy Geneticist      Signal Scout

tsar:stream:health             ALL agents               Orchestrator (supervisor)

tsar:stream:macro              Macro Agent              Signal Scout, Risk Guardian,
                                                        Regime Detector

tsar:stream:sentiment          Macro Agent              Signal Scout, Risk Guardian

tsar:stream:onchain            Macro Agent              Signal Scout

tsar:stream:risk_requests      Execution Sniper         Risk Guardian
tsar:stream:risk_reply:*       Risk Guardian            Execution Sniper
```

### 2.4 Agent Specifications

#### Agent 1: Signal Scout

**Purpose:** Scan markets for mean reversion setups. Score each setup 0-1.  
**Cycle:** Every 5 minutes (configurable)  
**Model Tier:** T0 (math) + T2 (Ollama Qwen2.5-7B for nuanced analysis) + T3 (DeepSeek-R1 for ambiguous signals)

**Signal Scoring Weights (Canonical):**

| Factor | Weight | Source |
|--------|--------|--------|
| RSI extreme | 25% | Technical (T0) |
| Support/Resistance proximity | 20% | Technical (T0) |
| Volume confirmation | 10% | Technical (T0) |
| Sentiment (Fear & Greed) | 15% | Market Analysis (T2) |
| Macro alignment | 10% | Market Analysis (T0) |
| On-chain metrics | 5% | Market Analysis (T0) |
| Order flow | 5% | Market Analysis (T0) |
| Seasonal patterns | 5% | Market Analysis (T0) |
| Cross-asset alignment | 5% | Market Analysis (T0) |
| **Total** | **100%** | |

**Output Schema:**
```
Signal:
  signal: string              # BUY | SELL
  symbol: string              # BTC/USDT
  score: float                # 0.0 - 1.0
  entry_price: float
  stop_loss: float
  take_profit: float
  reasoning: string
  sentiment_score: float      # -1 to +1
  macro_alignment: float      # -1 to +1
  timestamp: datetime
```

**Subscribes to:** `tsar:stream:regime`, `tsar:stream:strategy_mutations`, `tsar:stream:cartography`  
**Publishes to:** `tsar:stream:signals`

#### Agent 2: Risk Guardian

**Purpose:** Gatekeeper. Approves or rejects every trade signal. Pure rule-based — no LLM. Deterministic.

**Evaluation Checklist (ALL must pass):**
1. Position size ≤ 5% of account balance
2. Daily P&L not below -2% loss limit (**CANONICAL**)
3. Open positions < 10 (**CANONICAL**, Day1: 3)
4. Stop-loss is set and reasonable (≤ 2% from entry)
5. Risk-reward ratio ≥ 2:1
6. Not trading same symbol within cooldown (30 min)
7. No conflicting positions
8. Economic calendar blackout check
9. Geopolitical risk check
10. Macro regime alignment check

**Position Sizing:** Half-Kelly (0.25 Kelly fraction)

**Risk Limits (Canonical):**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Daily loss kill switch | **-2%** of capital | Conservative for $10 |
| Max drawdown (HWM) | 5% | Halt all trading |
| Max open positions | **10** (Day1: 3) | Solo dev monitoring capacity |
| Max single position | 15% of capital | Concentration limit |
| Max sector concentration | 30% of capital | Sector limit |
| Max correlation | 0.7 | New trade correlation to portfolio |
| Kelly fraction | 0.25 (Half-Kelly) | Conservative sizing |
| Max daily trades | 30 | Prevent overtrading |
| Min risk-reward | 2:1 | Winners must be 2x losers |

**VETO Protocol:**
- Level 1 (SOFT): Reduce position size — macro/sentiment adjustment
- Level 2 (FIRM): Reject signal — risk limit breach
- Level 3 (HARD): Close existing position — drawdown circuit breaker
- Level 4 (NUCLEAR): Kill switch — halt ALL trading

**Circuit Breakers:**
```
GREEN:   Drawdown < 2%       → Normal operation
YELLOW:  Drawdown 2-3%       → Reduce position sizes 50%
ORANGE:  Drawdown 3-5%       → Close new trades only, no new entries
RED:     Drawdown > 5%       → KILL SWITCH — flatten everything
```

**Subscribes to:** `tsar:stream:signals`, `tsar:stream:fills`, `tsar:stream:positions`, `tsar:stream:macro`, `tsar:stream:cartography`  
**Publishes to:** `tsar:stream:risk_decisions`, `tsar:stream:risk_reply:*`

#### Agent 3: Execution Sniper

**Purpose:** Place orders, manage stop-losses, track positions, close trades.  
**Model Tier:** None. Pure execution logic. Speed and reliability matter, not intelligence.

**Order Lifecycle:**
1. RECEIVE approved signal from Risk Guardian
2. VALIDATE order parameters
3. PLACE market/limit order on exchange
4. PLACE stop-loss order immediately after fill
5. PLACE take-profit order
6. MONITOR position every 1 minute
7. CLOSE position → calculate P&L → log to DB
8. NOTIFY via Telegram

**Subscribes to:** `tsar:stream:risk_decisions`  
**Publishes to:** `tsar:stream:orders`, `tsar:stream:risk_requests`

#### Agent 4: Macro Agent (Level 2+)

**Purpose:** Analyze macroeconomic environment. Produce macro regime score.  
**Model Tier:** T0 (indicator computation) + T2 (Ollama for narrative) + T3 (DeepSeek-R1 for crisis detection)

**Macro Regime Classification:**
| Regime | Position Adjustment | Direction Bias |
|--------|-------------------|----------------|
| RISK_ON | 1.0x | LONG |
| TRANSITION | 0.75x | NEUTRAL |
| RISK_OFF | 0.50x | SHORT |
| CRISIS | 0.25x | NONE |

**Indicator Weights:**
| Indicator | Weight | Source |
|-----------|--------|--------|
| Fed stance | 30% | FRED, Fed Fund Futures |
| Inflation trend | 20% | CPI, PCE, TIPS breakeven |
| Growth trend | 20% | GDP, ISM PMI, Consumer Confidence |
| Employment | 15% | NFP, Unemployment, Initial Claims |
| Dollar strength | 15% | DXY, Yield curve |

**Subscribes to:** `tsar:stream:regime`  
**Publishes to:** `tsar:stream:macro`

#### Agent 5: Regime Detector (Level 3+)

**Purpose:** Classify market regime using Hidden Markov Model.  
**Model Tier:** T0 (HMM math) + T1 (scikit-learn)

**Regime States:** Trending Up, Trending Down, Ranging, Volatile, Breakout

**Subscribes to:** `tsar:stream:cartography`  
**Publishes to:** `tsar:stream:regime`

#### Agent 6: Trade Philosopher (Level 3+)

**Purpose:** Post-trade reflection. Generate lessons. Feed learning loop.  
**Model Tier:** T2 (Ollama Qwen2.5-7B)

**Reflection Prompt Template:**
```
Analyze this completed trade:
- Symbol, Side, Entry, Exit, P&L, Duration
- Signal score, Strategy, Regime at entry
- Max favorable excursion, Max adverse excursion

Answer:
1. What went right?
2. What went wrong?
3. What would I do differently?
4. What lesson should be extracted?
5. Error category: timing | sizing | regime | execution | none
```

**Subscribes to:** `tsar:stream:fills`, `tsar:stream:positions`, `tsar:stream:risk_decisions`  
**Publishes to:** `tsar:stream:analytics`

#### Agent 7: Strategy Geneticist (Level 3+)

**Purpose:** Evolve strategies. Run backtests. Retire underperformers.  
**Model Tier:** T0 (backtesting math) + T2 (Ollama for strategy analysis)

**Strategy Retirement Gates:**
| Gate | Threshold | Action |
|------|-----------|--------|
| Rolling Sharpe (30-day) | < 0.5 for 30 days | RETIRE |
| Drawdown | > 15% from HWM | PAUSE |
| Drawdown | > 20% from HWM | RETIRE |
| Win rate (50 trades) | < 40% | RETIRE |
| Regime fitness | Negative Sharpe in current regime | PAUSE |

**Subscribes to:** `tsar:stream:analytics`, `tsar:stream:regime`, `tsar:stream:fills`  
**Publishes to:** `tsar:stream:strategy_mutations`

#### Agent 8: Market Cartographer (Level 3+)

**Purpose:** Cross-asset correlation. Structural market analysis.  
**Model Tier:** T0 (correlation math) + T1 (PCA, cointegration)

**Correlation Pairs:**
- BTC ↔ DXY, BTC ↔ Gold, BTC ↔ VIX, BTC ↔ S&P 500
- BTC ↔ ETH, BTC ↔ Altcoins
- DXY ↔ Gold, VIX ↔ S&P

**Subscribes to:** `tsar:stream:regime`, `tsar:stream:fills`  
**Publishes to:** `tsar:stream:cartography`

#### Agent 9: Execution Tracker (Level 3+)

**Purpose:** Position reconciliation. Fill monitoring. Slippage tracking.  
**Model Tier:** None. Pure comparison logic.

**Reconciliation Schedule:**
| Check | Frequency | Alert Threshold |
|-------|-----------|-----------------|
| Position qty | Every 5 min | Any mismatch |
| Balance check | Every 15 min | > 1% difference |
| Open orders | Every 5 min | Stale orders |
| EOD snapshot | Daily 00:00 | Full report |

**Subscribes to:** `tsar:stream:orders`, `tsar:stream:fills`  
**Publishes to:** `tsar:stream:positions`

#### Agent 10: Orchestrator

**Purpose:** Supervisor. Health monitoring. Alert routing. Backup coordination.  
**Model Tier:** None. Pure orchestration.

**Responsibilities:**
- Monitor agent heartbeats via `tsar:stream:health`
- Route alerts (CRITICAL → Telegram + SMS, WARNING → Telegram, INFO → Grafana)
- Coordinate daily backup
- Manage bootstrap sequence
- Coordinate mode switches (paper ↔ live)

**Subscribes to:** `tsar:stream:health` (all agents)  
**Publishes to:** System alerts

---

## 3. TOOLS — FULL SPECIFICATION

### 3.1 Tool Registry (35 Tools Canonical)

| # | Tool | Category | Owner Agent | Params | Returns | Day1 |
|---|------|----------|-------------|--------|---------|------|
| 1 | `get_price` | Exchange | Signal Scout | `symbol: str` | `float` | ✅ |
| 2 | `get_ohlcv` | Exchange | Signal Scout | `symbol, timeframe, limit` | `DataFrame` | ✅ |
| 3 | `get_orderbook` | Exchange | Signal Scout | `symbol, depth` | `OrderBook` | — |
| 4 | `place_order` | Exchange | Execution Sniper | `symbol, side, qty, type, price?` | `OrderResult` | ✅ |
| 5 | `cancel_order` | Exchange | Execution Sniper | `order_id, symbol` | `bool` | ✅ |
| 6 | `get_positions` | Exchange | Execution Sniper | `exchange?` | `list[Position]` | ✅ |
| 7 | `get_balance` | Exchange | Execution Sniper | `exchange?` | `Balance` | ✅ |
| 8 | `get_funding_rate` | Exchange | Risk Guardian | `symbol` | `float` | — |
| 9 | `calculate_rsi` | Analysis | Signal Scout | `closes, period` | `float` | ✅ |
| 10 | `calculate_macd` | Analysis | Signal Scout | `closes, fast, slow, signal` | `MACDResult` | — |
| 11 | `calculate_bollinger` | Analysis | Signal Scout | `closes, period, std` | `BollingerBands` | — |
| 12 | `calculate_atr` | Analysis | Signal Scout | `highs, lows, closes, period` | `float` | — |
| 13 | `calculate_ema` | Analysis | Signal Scout | `closes, period` | `float` | — |
| 14 | `calculate_volume_profile` | Analysis | Signal Scout | `prices, volumes, bins` | `VolumeProfile` | — |
| 15 | `detect_patterns` | Analysis | Signal Scout | `ohlcv_df` | `list[Pattern]` | — |
| 16 | `stream_prices` | Data | Orchestrator | `symbol, callback` | `StreamHandle` | — |
| 17 | `stream_orderbook` | Data | Orchestrator | `symbol, depth, callback` | `StreamHandle` | — |
| 18 | `fetch_news` | Data | Macro Agent | `symbol, limit` | `list[NewsItem]` | — |
| 19 | `fetch_social_sentiment` | Data | Macro Agent | `symbol` | `SentimentScore` | — |
| 20 | `fetch_onchain_data` | Data | Macro Agent | `symbol, metrics` | `OnChainData` | — |
| 21 | `fetch_macro_calendar` | Data | Macro Agent | `days_ahead` | `list[EconomicEvent]` | — |
| 22 | `check_position_limits` | Risk | Risk Guardian | `trade_proposal` | `RiskCheck` | ✅ |
| 23 | `calculate_position_size` | Risk | Risk Guardian | `balance, risk_pct, entry, stop` | `float` | ✅ |
| 24 | `get_portfolio_exposure` | Risk | Risk Guardian | `—` | `Exposure` | — |
| 25 | `get_correlation_matrix` | Risk | Market Cartographer | `symbols, window` | `CorrelationMatrix` | — |
| 26 | `get_drawdown_stats` | Risk | Risk Guardian | `—` | `DrawdownStats` | — |
| 27 | `log_trade` | Memory | Execution Sniper | `trade_data` | `trade_id` | ✅ |
| 28 | `search_trades` | Memory | Trade Philosopher | `query, filters` | `list[Trade]` | — |
| 29 | `get_strategy_performance` | Memory | Strategy Geneticist | `strategy_name` | `Performance` | — |
| 30 | `get_lesson` | Memory | Trade Philosopher | `lesson_id` | `Lesson` | — |
| 31 | `update_regime_state` | Memory | Regime Detector | `regime_data` | `bool` | — |
| 32 | `smart_order_router` | Execution | Execution Sniper | `order, venues` | `RouteResult` | — |
| 33 | `calculate_slippage` | Execution | Execution Tracker | `expected, actual` | `SlippageReport` | — |
| 34 | `twap_execute` | Execution | Execution Sniper | `order, duration, slices` | `ExecutionResult` | — |
| 35 | `monitor_fills` | Execution | Execution Tracker | `order_id, callback` | `FillMonitor` | — |

### 3.2 Tool Permission Matrix

| Role | Exchange | Analysis | Data | Risk | Memory | Execution |
|------|----------|----------|------|------|--------|-----------|
| **READ** | get_price, get_balance, get_positions | All | All | get_drawdown_stats | search_trades, get_lesson, get_strategy_performance | calculate_slippage |
| **ANALYSIS** | READ + get_ohlcv, get_orderbook, get_funding_rate | All | All | All READ | All | calculate_slippage |
| **TRADE_PREVIEW** | ANALYSIS + (no writes) | All | All | All | All | calculate_slippage |
| **TRADE_EXECUTE** | All | All | All | All | All | All |
| **TRADE_ADMIN** | All | All | All | All | All | All |

### 3.3 Dual-Language Architecture

**Python (3.12):** Exchange communication (ccxt), technical analysis (pandas-ta), risk calculations, memory tools, sentiment analysis, MCP tool server

**Rust (1.79):** WebSocket streaming (tokio-tungstenite), smart order routing, TWAP/VWAP execution, slippage calculation, fill monitoring

**Inter-Layer Communication:**
| Method | Use Case | Latency |
|--------|----------|---------|
| PyO3 | Python → Rust function calls | ~1μs |
| gRPC (localhost) | Rust streaming → Python consumer | ~100μs |
| Redis PubSub | Cross-process events | ~500μs |
| Shared Memory (mmap) | Ultra-low-latency price cache | ~10ns |

---

## 4. KNOWLEDGE STORES — FULL SPECIFICATION

### 4.1 Store 1: Trade Memory (`trade_*` tables in tsar.db)

**Purpose:** Every trade — entry, exit, context, outcome, reflection — stored permanently.

**Schema:**
```
trade_records:
  id: INTEGER PRIMARY KEY
  trade_id: TEXT UNIQUE NOT NULL         -- UUID
  symbol: TEXT NOT NULL                  -- BTC/USDT
  side: TEXT NOT NULL                    -- BUY | SELL
  entry_price: REAL
  exit_price: REAL
  quantity: REAL NOT NULL
  stop_loss: REAL NOT NULL
  take_profit: REAL NOT NULL
  status: TEXT DEFAULT 'OPEN'            -- OPEN | CLOSED | CANCELLED
  pnl: REAL DEFAULT 0.0
  pnl_pct: REAL DEFAULT 0.0
  signal_score: REAL
  risk_approved: INTEGER DEFAULT 0
  strategy: TEXT NOT NULL
  exchange_order_id: TEXT
  trading_mode: TEXT DEFAULT 'paper'     -- paper | live
  regime_at_entry: TEXT
  max_favorable_excursion: REAL
  max_adverse_excursion: REAL
  slippage_bps: REAL
  commission: REAL
  notes: TEXT
  opened_at: TIMESTAMP
  closed_at: TIMESTAMP
```

**Indexes:** status, symbol, opened_at, strategy, trading_mode  
**Retention:** Permanent (7+ years)  
**Flow:** Execution Sniper writes → Trade Philosopher reads → Strategy Geneticist analyzes

### 4.2 Store 2: Strategy Genomes (`strategy_*` tables in tsar.db)

**Purpose:** Living, evolving strategy definitions with performance stats per regime.

**Schema:**
```
strategy_genomes:
  id: INTEGER PRIMARY KEY
  name: TEXT UNIQUE NOT NULL             -- 'mean_reversion_btc'
  version: TEXT NOT NULL                 -- '3.2.1'
  thesis: TEXT                           -- Why this strategy works
  entry_rules: TEXT (JSON)               -- Executable rule set
  exit_rules: TEXT (JSON)
  risk_params: TEXT (JSON)
  regime_performance: TEXT (JSON)        -- Per-regime stats
  status: TEXT DEFAULT 'ACTIVE'          -- ACTIVE | PAUSED | RETIRED
  created_at: TIMESTAMP
  last_evolved: TIMESTAMP

strategy_performance:
  id: INTEGER PRIMARY KEY
  strategy_name: TEXT NOT NULL
  total_trades: INTEGER DEFAULT 0
  winning_trades: INTEGER DEFAULT 0
  total_pnl: REAL DEFAULT 0.0
  win_rate: REAL DEFAULT 0.0
  sharpe_ratio: REAL DEFAULT 0.0
  max_drawdown: REAL DEFAULT 0.0
  rolling_sharpe_30d: REAL
  last_updated: TIMESTAMP

strategy_mutations:
  id: INTEGER PRIMARY KEY
  strategy_name: TEXT NOT NULL
  version_from: TEXT
  version_to: TEXT
  change_description: TEXT
  rationale: TEXT
  performance_before: TEXT (JSON)
  performance_after: TEXT (JSON)
  created_at: TIMESTAMP
```

**Flow:** Strategy Geneticist writes → Signal Scout reads

### 4.3 Store 3: Pattern Library (`pattern_*` tables in tsar.db)

**Purpose:** Discovered market patterns with occurrence counts and success rates.

**Schema:**
```
patterns:
  id: INTEGER PRIMARY KEY
  pattern_type: TEXT NOT NULL            -- 'candlestick', 'structural', 'regime'
  description: TEXT NOT NULL
  conditions: TEXT (JSON)                -- Detection conditions
  occurrences: INTEGER DEFAULT 0
  success_rate: REAL
  avg_pnl_impact: REAL
  confidence: REAL
  discovered_at: TIMESTAMP
  last_seen: TIMESTAMP

pattern_observations:
  id: INTEGER PRIMARY KEY
  pattern_id: INTEGER FK
  trade_id: TEXT FK
  outcome: TEXT                          -- WIN | LOSS
  pnl_impact: REAL
  observed_at: TIMESTAMP

pattern_relationships:
  id: INTEGER PRIMARY KEY
  pattern_a_id: INTEGER FK
  pattern_b_id: INTEGER FK
  relationship: TEXT                     -- 'co-occurs', 'precedes', 'contradicts'
  strength: REAL
```

**Flow:** Trade Philosopher discovers → Signal Scout uses for scoring

### 4.4 Store 4: Lesson Archive (`lesson_*` tables in tsar.db)

**Purpose:** Extracted lessons from trade outcomes. Searchable via FTS5.

**Schema:**
```
lessons:
  id: INTEGER PRIMARY KEY
  trade_id: TEXT FK
  lesson_type: TEXT NOT NULL             -- WIN | LOSS | MISTAKE | INSIGHT
  category: TEXT                         -- ENTRY | EXIT | SIZING | TIMING | REGIME
  description: TEXT NOT NULL
  action_item: TEXT                      -- Concrete change to make
  applied: INTEGER DEFAULT 0            -- 1 = incorporated into strategy
  confidence: REAL DEFAULT 0.5
  created_at: TIMESTAMP

lesson_applications:
  id: INTEGER PRIMARY KEY
  lesson_id: INTEGER FK
  strategy_name: TEXT
  parameter_changed: TEXT
  old_value: TEXT
  new_value: TEXT
  impact_measured: TEXT
  applied_at: TIMESTAMP

lesson_violations:
  id: INTEGER PRIMARY KEY
  lesson_id: INTEGER FK
  trade_id: TEXT FK
  violation_description: TEXT
  occurred_at: TIMESTAMP
```

**FTS5 Index:** `lessons_fts` on description, action_item  
**Flow:** Trade Philosopher writes → Strategy Geneticist applies → Signal Scout benefits

### 4.5 Store 5: Regime History (`regime_history` table in tsar.db)

**Purpose:** Historical regime classifications for backtesting and analysis.

**Schema:**
```
regime_history:
  snapshot_id: TEXT PRIMARY KEY
  snapshot_date: TEXT NOT NULL
  regime_probs: TEXT NOT NULL (JSON)     -- {trending_up: 0.6, ranging: 0.3, ...}
  dominant_regime: TEXT
  confidence: REAL
  indicators: TEXT (JSON)                -- Snapshot of indicators used
  created_at: TIMESTAMP
```

**Flow:** Regime Detector writes → Strategy Geneticist uses for backtesting

### 4.6 Knowledge Flow Diagram

```
TRADE EXECUTES
      │
      ▼
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│ Trade Memory │───▶│ Trade        │───▶│ Lesson       │
│ (raw data)   │    │ Philosopher  │    │ Archive      │
└─────────────┘    │ (reflect)    │    │ (extract)    │
                   └──────────────┘    └──────┬───────┘
                                              │
                                              ▼
                   ┌──────────────┐    ┌──────────────┐
                   │ Strategy     │◀───│ Pattern      │
                   │ Geneticist   │    │ Library      │
                   │ (adapt)      │    │ (discover)   │
                   └──────┬───────┘    └──────────────┘
                          │
                          ▼
                   ┌──────────────┐
                   │ Signal Scout │
                   │ (improve)    │
                   └──────────────┘
                          │
                          ▼
                   NEXT TRADE (better than last)
```

---

## 5. LAYER SPECIFICATIONS

### 5.1 Layer 1: Market Analysis

**Components:** Macro Agent, Sentiment Analysis, On-Chain Analytics, Economic Calendar, Geopolitical Analysis, Cross-Asset Correlation, Order Flow Analysis, Seasonal Analysis

**Data Sources (All Free):**

| Source | API | Cost | Metrics |
|--------|-----|------|---------|
| FRED | fredapi | $0 | Rates, GDP, employment, inflation |
| Yahoo Finance | yfinance | $0 | DXY, VIX, bonds, equities, gold |
| Alternative.me | REST | $0 | Fear & Greed Index |
| CoinGecko | REST | $0 | Price, volume, market cap |
| CryptoQuant | REST | $0 (limited) | Exchange flow, reserves |
| Whale Alert | REST | $0 (free tier) | Large transactions |
| DeFiLlama | REST | $0 | DeFi TVL, yields |
| CoinMetrics | REST | $0 (community) | MVRV, NVT, supply |
| ForexFactory | HTML scrape | $0 | Economic calendar |
| CryptoPanic | REST | $0 | Crypto news |
| Binance | WS + REST | $0 | Order book, trades, OHLCV |

**Economic Calendar Blackout Rules (Canonical):**

| Event | Before | After | Size Multiplier |
|-------|--------|-------|-----------------|
| FOMC Rate Decision | 60 min | 60 min | 0% (block) |
| CPI | 30 min | 30 min | 0% (block) |
| NFP | 30 min | 30 min | 0% (block) |
| FOMC Minutes | 30 min | 30 min | 50% |
| ECB/BOJ | 30 min | 30 min | 50% |
| GDP | 15 min | 15 min | 50% |
| PCE | 30 min | 30 min | 50% |

### 5.2 Layer 2: Strategy & Portfolio

**Backtesting Engine:**
- Library: vectorbt (Python, vectorized)
- Fee model: Exchange-accurate (Binance 0.1% maker/taker)
- Slippage model: Configurable (zero, fixed, realistic with mean 3bps, std 2bps)
- Walk-forward: Train 70% / Validation 15% / Test 15%
- Statistical significance: t-test p < 0.05 required

**Strategy Portfolio Allocation:**
- Methods: Risk Parity (default), Kelly-Based, Inverse Volatility
- Rebalance trigger: Drift > 10% from target
- Rebalance frequency: Weekly on rolling 30-day Sharpe
- Max single strategy: 50% of capital
- Min strategies for diversification: 2

### 5.3 Layer 3: Execution

**Order Types (Day1):** Market orders, Stop-market (stop-loss), Limit (take-profit)  
**Order Types (Full):** + TWAP, VWAP, Iceberg, Smart Order Routing

**Exchange Failover:**
| Failure | Response | Timeout |
|---------|----------|---------|
| REST API timeout | Retry 3x exponential backoff | 1s/2s/4s |
| REST API 429 | Respect Retry-After | Per header |
| REST API 5xx | Retry 3x, then backup exchange | 2s/4s/8s |
| WebSocket disconnect | Auto-reconnect 5x backoff | 1s/2s/4s/8s/16s |
| Exchange maintenance | Switch to backup | Immediate |
| API key revoked | HALT all trading | Immediate |

### 5.4 Layer 4: Risk Management

**Pre-Trade Checks (7-Layer Veto Protocol):**
1. Position sizing (Half-Kelly + hard cap at 15%)
2. Daily loss limit (-2% canonical)
3. Max drawdown (5% from HWM)
4. Max open positions (10 canonical, Day1: 3)
5. Correlation check (max 0.7 to portfolio)
6. Regime alignment
7. Anti-behavioral guards (revenge, greed, FOMO, overconfidence)

**VaR (Level 3+):**
- Method: Historical simulation
- Confidence: 95% and 99%
- Horizon: 1-day
- Stress scenarios: Flash crash (-30%), Exchange halt (24h), LUNA collapse (-95%), FOMC shock, Liquidity crisis

**Counterparty Risk (Level 2+):**
- Exchange health score: API latency, error rate, withdrawal processing
- Proof-of-reserves verification: Monthly
- Exposure limits: Max 50% per exchange, min 2 exchanges at scale

### 5.5 Layer 5: Data Infrastructure

**Database:** 1 unified SQLite database: `tsar.db`  
- Mode: WAL, page_size=4096, mmap=256MB  
- Schema separation: Table prefixes (`trade_*`, `strategy_*`, `pattern_*`, `lesson_*`, `market_*`)  
- FTS5 indexes: lessons, trade thesis, pattern descriptions, strategy text  

**Redis:** Single instance, `tsar:*` key prefix  
- Streams: Inter-agent communication  
- Hashes: Real-time state (positions, P&L, risk, regime)  
- PubSub: Event broadcasting  

**ChromaDB:** Optional — skip for v1, add when portfolio > $1,000

**Data Quality Pipeline (6 Checks):**
1. Gap detection (missing candles)
2. OHLC integrity (H≥L, H≥O,C, L≤O,C)
3. No zero-volume candles
4. Price outlier detection (>5σ from rolling mean)
5. Timestamp monotonicity
6. Duplicate detection

### 5.6 Layer 6: Operations

**Backup (3-Tier):**
| Tier | Frequency | Retention | Storage |
|------|-----------|-----------|---------|
| Hot | Every 15 min | 24 hours | Local (SQLite backup API) |
| Warm | Daily 00:00 UTC | 30 days | Local + cloud |
| Cold | Weekly | 1 year | Cloud (S3/R2) |

**Monitoring:**
- Prometheus metrics: trade_count, pnl, drawdown, latency, error_rate, agent_health
- Grafana dashboards: Trading Overview, System Health, Risk Monitor
- Alert routing: CRITICAL → Telegram + SMS, WARNING → Telegram, INFO → Grafana

**Structured Logging:**
- Format: JSON with timestamp, level, agent, trace_id, message
- Rotation: Daily
- Retention: 30 days hot, 90 days warm, 7 years cold

### 5.7 Layer 7: Compliance

**Immutable Audit Log:**
- Layer 1: SQLite (mutable, queryable)
- Layer 2: Append-only JSONL with SHA-256 hash chain
- Layer 3: Remote copy with object lock (S3 versioning)

**Audit Event Types:**
```
trade.decision, trade.order_placed, trade.order_filled, trade.order_cancel,
risk.limit_hit, risk.kill_switch, system.startup, system.shutdown,
system.config_change, data.feed_gap, data.anomaly, recon.mismatch,
counterparty.alert
```

**Record Retention:**
| Record | Retention |
|--------|-----------|
| Trade executions | 7 years |
| Order history | 7 years |
| Risk limit breaches | 7 years |
| Strategy decisions | 3 years |
| Configuration changes | 7 years |
| Market data | 3 years |

**Position Reconciliation (Level 2+):**
- Frequency: Every 5 minutes
- Tolerance: 0.01%
- Action on mismatch: Alert + halt if > $100 difference

### 5.8 Layer 8: Portfolio Management

**Multi-Asset Support (Level 3+):**
| Asset Class | Exchange | API |
|-------------|----------|-----|
| Crypto | Binance | ccxt |
| Forex | OANDA | ccxt / REST |
| Gold | OANDA | ccxt / REST |

**Allocation Constraints:**
- Max single asset class: 40% of portfolio
- Min diversification: 2 asset classes
- Rebalance trigger: Drift > 10%

**Performance Attribution:**
- By strategy (SQL view)
- By asset class (SQL view)
- By regime (SQL view)

**Benchmark Comparison:**
- Primary: Buy-and-hold BTC
- Alpha calculation: Strategy return - Benchmark return
- Risk-adjusted: Sharpe ratio comparison

---

## 6. RISK MANAGEMENT — DETERMINISTIC RULES

### 6.1 Hard Rules (NEVER Violate)

| Rule | Value | Action on Violation |
|------|-------|---------------------|
| Max position | 15% of balance | Reject trade |
| Risk per trade | 2% of balance (Half-Kelly) | Reduce size |
| Daily loss limit | -2% of balance | Stop trading for the day |
| Max drawdown | 5% from HWM | Halt ALL trading |
| Stop-loss required | Every trade | Reject if missing |
| Max open positions | 10 (Day1: 3) | Wait for close |
| Min R:R ratio | 2:1 | Reject trade |
| Max correlation | 0.7 to portfolio | Reject trade |
| Max daily trades | 30 | Wait for tomorrow |

### 6.2 Kill Switch Protocol

**Trigger Conditions:**
- Daily loss ≥ -2% of capital
- Max drawdown ≥ 5% from HWM
- Exchange API auth failure
- Manual trigger via Telegram `/stop`

**Kill Switch Actions:**
1. Cancel ALL open orders
2. Close ALL positions (market orders)
3. Set system to HALTED state
4. Send Telegram alert
5. Log to immutable audit log
6. Require manual `/start` to resume

### 6.3 Anti-Behavioral Guards

| Guard | Detection | Action |
|-------|-----------|--------|
| Revenge trading | 3 consecutive losses | 60-min cooldown |
| Greed | Position size increase after wins | Cap at base size |
| FOMO | Signal score < 0.6, still trying to trade | Block |
| Overconfidence | 5+ consecutive wins, increasing size | Warn + cap |

---

## 7. PAPER TRADING MODE

### 7.1 Architecture

The system boots in paper mode by default. All risk rules, position tracking, and P&L calculations apply identically. Only the execution backend differs.

**Paper Engine:** Simulated fills with realistic slippage (mean 3bps, std 2bps), partial fill probability (10%), rejection probability (1%)

**Configuration:**
```
[trading]
mode = "paper"                    # "paper" | "live"
paper_initial_capital = 10000.0

[trading.paper]
fill_latency_ms = 50
slippage_model = "realistic"
slippage_bps_mean = 3.0
slippage_bps_std = 2.0
fee_model = "exchange_accurate"
```

### 7.2 Paper → Live Transition Criteria

| Metric | Minimum | Target |
|--------|---------|--------|
| Paper trades completed | 100 | 500 |
| Sharpe ratio | > 1.0 | > 2.0 |
| Max drawdown | < 10% | < 5% |
| Win rate | > 50% | > 55% |
| Profit factor | > 1.2 | > 2.0 |
| System uptime | > 99% | > 99.9% |
| Kill switch tested | Yes | — |

**Requires explicit human approval to switch to live.**

---

## 8. SCALING STRATEGY

### 8.1 Day1 → Level 2 Migration

**What Changes:**
1. Add Macro Agent (4th agent)
2. Add backtesting engine (vectorbt)
3. Add walk-forward validation
4. Add strategy retirement gates
5. Add immutable audit log (JSONL hash chain)
6. Add data quality pipeline (6 checks)
7. Add counterparty risk monitoring
8. Add position reconciliation
9. Add Fear & Greed + CryptoPanic sentiment
10. Add ForexFactory economic calendar

**Migration Steps:**
1. Backup tsar.db
2. Run migration scripts (add `market_*` tables)
3. Deploy new agent code
4. Start Macro Agent
5. Verify health
6. If issues → rollback to backup

### 8.2 Level 2 → Level 3

**What Changes:**
1. Add Regime Detector, Trade Philosopher, Strategy Geneticist, Market Cartographer, Execution Tracker (5 more agents)
2. Add VaR / stress testing
3. Add strategy portfolio + allocation
4. Add multi-asset support (forex, gold)
5. Add Prometheus + Grafana monitoring
6. Add structured logging + Loki
7. Add on-chain analytics (full suite)

### 8.3 Level 3 → Level 4

**What Changes:**
1. Multi-exchange execution
2. Advanced execution algorithms (TWAP, VWAP)
3. Full compliance layer
4. Performance attribution
5. Portfolio rebalancing
6. Kubernetes deployment

### 8.4 Component Upgrade Triggers

| Component | Upgrade When |
|-----------|-------------|
| SQLite → PostgreSQL | > 100K trades or need concurrent access |
| 3 → 4 agents | 3 agents proven, need macro specialization |
| 10 → 20 tools | Need advanced order types, multiple timeframes |
| Laptop → VPS | Need 24/7 uptime |
| Telegram → + Dashboard | Need visual analytics |
| Basic risk → Full risk | Capital > $1,000 |

---

## 9. TECH STACK

### 9.1 Languages & Versions

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | **3.12** | Primary language |
| Rust | **1.79** | Execution engine, streaming |
| SQLite | 3.40+ | Primary database |
| Redis | 7.0+ | State, cache, streams |
| Node.js | 22 LTS | OpenClaw gateway |

### 9.2 Key Dependencies

**Python:**
- ccxt (exchange connectivity)
- pandas + pandas-ta (data + indicators)
- ollama (local LLM)
- openai (DeepSeek-R1 via NIM)
- python-telegram-bot (notifications)
- apscheduler (scheduling)
- vectorbt (backtesting, Level 2+)
- aiohttp (async HTTP)
- redis (state management)

**Rust:**
- tokio (async runtime)
- tokio-tungstenite (WebSocket)
- pyo3 (Python bindings)
- serde (serialization)
- tonic (gRPC)

### 9.3 Infrastructure

| Service | Port | Protocol |
|---------|------|----------|
| Redis | 6379 | TCP |
| FastAPI (REST API) | **8000** | HTTP |
| Agent Supervisor | **8001** | HTTP |
| Prometheus | 9090 | HTTP |
| Grafana | 3000 | HTTP |
| Ollama | 11434 | HTTP |

---

## 10. DEPLOYMENT ARCHITECTURE

### 10.1 Day1 Deployment

```
Single machine (laptop or VPS)
├── Docker Compose
│   ├── tsar-app (Python + Rust)
│   ├── redis:7.0
│   ├── prometheus (optional)
│   └── grafana (optional)
├── data/
│   ├── tsar.db
│   ├── backups/
│   └── audit/
└── config/
    ├── settings.py
    ├── exchanges.yaml
    └── risk_limits.yaml
```

### 10.2 Full Deployment

```
VPS or Cloud Instance
├── Docker Compose / Kubernetes
│   ├── tsar-agents (4+ containers)
│   ├── redis:7.0 (with AOF)
│   ├── prometheus
│   ├── grafana
│   ├── loki (log aggregation)
│   └── nginx (reverse proxy)
├── CI/CD: GitHub Actions
│   ├── Lint + Type check
│   ├── Unit tests
│   ├── Integration tests
│   ├── Docker build
│   └── Canary deploy (5% → 100%)
└── Monitoring
    ├── Prometheus metrics
    ├── Grafana dashboards
    └── Telegram alerts
```

### 10.3 FastAPI Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/health` | GET | None | System health |
| `/positions` | GET | API Key | Current positions |
| `/pnl` | GET | API Key | P&L summary |
| `/risk` | GET | API Key | Risk state |
| `/kill-switch` | POST | TRADE_ADMIN | Emergency halt |
| `/resume` | POST | TRADE_ADMIN | Resume trading |
| `/strategies` | GET | API Key | Strategy performance |
| `/regime` | GET | API Key | Current regime |
| `/trades` | GET | API Key | Trade history |

---

## 11. BOOTSTRAP SEQUENCE

```
Phase 1: INFRASTRUCTURE (0-10s)
  1. Start Redis
  2. Initialize tsar.db (run migrations)
  3. Verify disk space, memory, network

Phase 2: DATA ACQUISITION (10s - 5min)
  4. Download historical OHLCV (90 days 1H, 252 days 1D)
  5. Fetch economic calendar (ForexFactory)
  6. Fetch Fear & Greed index
  7. Compute initial correlation matrix

Phase 3: MODEL CALIBRATION (5min - 15min)
  8. Calibrate HMM regime model (if Level 3+)
  9. Calculate indicator baselines
  10. Load strategy genomes from YAML

Phase 4: STATE RECONSTRUCTION (15min - 20min)
  11. Rebuild Redis state from tsar.db
  12. Verify FTS5 index integrity

Phase 5: VALIDATION (20min - 25min)
  13. System self-tests (Redis, DB, exchange connectivity)
  14. Publish bootstrap_complete

Phase 6: WARM-UP TRADING (25min+)
  15. Start agents in dependency order
  16. Risk Guardian starts in VETO_ALL until validation passes
  17. First regime classification published
  18. Trading begins after first Risk Guardian approval
```

---

## 12. TELEGRAM INTERFACE

### Commands

| Command | Description | Auth |
|---------|-------------|------|
| `/status` | Current positions, balance, regime | All |
| `/pnl` | Today's P&L | All |
| `/history` | Last 10 trades | All |
| `/stop` | Emergency stop — close all positions | TRADE_ADMIN |
| `/start` | Resume trading | TRADE_ADMIN |
| `/lessons` | Recent learnings | All |
| `/strategy_status` | All strategies + health gates | All |
| `/retire <name>` | Manual strategy retirement | TRADE_ADMIN |
| `/risk` | Current risk state | All |

---

## 13. LLM PROVIDER ABSTRACTION

### 13.1 Architecture

All LLM calls go through a `BaseLLMProvider` abstract class. No direct provider SDK calls anywhere in the codebase. Providers are discovered via `ProviderRegistry` and configured via `config/llm_providers.yaml`.

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  BaseLLMProvider │◄───│  ProviderRegistry│───►│  ModelRouter     │
│  (abstract)      │    │  (discovery)     │    │  (config-driven  │
│                  │    └──────────────────┘    │   fallback chains)│
│  • OllamaProvider│                             └──────────┬───────┘
│  • OpenAIProvider│                                        │
│  • AnthropicProv │                                        ▼
└──────────────────┘                             ┌──────────────────┐
                                                 │  All Agents      │
                                                 │  (via task_type) │
                                                 └──────────────────┘
```

### 13.2 Provider Interface

```python
class BaseLLMProvider(ABC):
    def descriptor(self) -> ModelDescriptor: ...
    async def generate(self, prompt, **kwargs) -> LLMResponse: ...
    async def stream(self, prompt, **kwargs) -> AsyncIterator[str]: ...
    async def count_tokens(self, text) -> int: ...
    async def health_check(self) -> bool: ...
```

### 13.3 Task-Type Routing

No model names in agent code. Agents call `router.generate(task_type="trade_narrative", prompt=...)` and the router selects the best available provider from the config-defined fallback chain.

### 13.4 Configuration

All model names, API keys, and fallback chains defined in `config/llm_providers.yaml`. **No model names in Python source code.**

---

## 14. CLOUDEVENTS MESSAGING PROTOCOL

### 14.1 Standard

All inter-agent messages use **CloudEvents v1.0** (CNCF standard) as the envelope format.

### 14.2 Envelope Format

```
CloudEvent:
  specversion: "1.0"              # CloudEvents version
  id: ULID                        # Globally unique, time-sortable
  source: "tsar/agent/{name}"     # Event source
  type: "tsar.{domain}.{action}.v1"  # Event type
  time: RFC3339                   # Event timestamp
  datacontenttype: "application/json"
  data: dict                      # Event payload
  trace_id: string                # Distributed tracing (TSAR extension)
  priority: int                   # 0=critical, 1=high, 2=normal, 3=low
  agent: string                   # Publishing agent name
```

### 14.3 Canonical Event Types

| Domain | Event Types |
|--------|-------------|
| Regime | `tsar.regime.change.v1`, `tsar.regime.update.v1` |
| Signal | `tsar.signal.generated.v1`, `tsar.signal.validated.v1` |
| Risk | `tsar.risk.decision.v1`, `tsar.risk.veto_all.v1`, `tsar.risk.kill_switch.v1` |
| Order | `tsar.order.placed.v1`, `tsar.order.filled.v1`, `tsar.order.cancelled.v1` |
| Position | `tsar.position.opened.v1`, `tsar.position.closed.v1`, `tsar.portfolio.snapshot.v1` |
| Analytics | `tsar.analytics.trade_analysis.v1`, `tsar.analytics.lesson_created.v1` |
| Strategy | `tsar.strategy.mutation.v1`, `tsar.strategy.retired.v1` |
| Health | `tsar.health.heartbeat.v1`, `tsar.health.dying.v1` |

### 14.4 Serialization

- **Wire format:** MessagePack (binary, 30-50% smaller than JSON)
- **Debug format:** JSON (via `redis-cli`)
- **Transport:** Redis Streams (unchanged)

---

## 15. IMPROVEMENT MEASUREMENT FRAMEWORK

### 15.1 Purpose

Prove the system is getting better with every trade. Baseline metrics recorded after first 30 trades, daily snapshots track trends.

### 15.2 Core Metrics

| Metric | Description | Target Direction |
|--------|-------------|-----------------|
| Sharpe Ratio (30d) | Rolling risk-adjusted return | ↑ Increasing |
| Win Rate (30d) | Rolling win percentage | ↑ Increasing |
| Lesson Application Rate | % of trades where lessons were applied | ↑ Increasing |
| Knowledge Density | Total patterns + lessons + mutations | ↑ Growing |
| Strategy Fitness | Average Sharpe of active strategies | ↑ Increasing |

### 15.3 Baseline Recording

After 30 trades, record baseline metrics. All future improvement is measured against this baseline.

### 15.4 Daily Snapshots

Daily snapshot stored in `improvement_snapshots` table. Includes:
- Performance metrics (Sharpe, win rate, profit factor, drawdown)
- Learning metrics (lessons created/applied/violated, patterns)
- Strategy metrics (active, retired, mutations, diversity)
- Knowledge density (total items, growth rate)
- Delta from baseline

### 15.5 Verdict Engine

The system produces an **IMPROVING / STABLE / DECLINING** verdict based on trend analysis across all metrics.

---

## 16. TOOL RESOURCE LIMITS

### 16.1 Enforcement

Every tool invocation passes through `ResourceGuard` before execution. Limits enforced via:
- **Wall-clock timeout** — automatic kill after configured seconds
- **Memory cap** — monitored per invocation
- **Concurrency limit** — semaphore per tool
- **Rate limit** — calls per minute per tool
- **Circuit breaker** — disabled after repeated violations

### 16.2 Configuration

Resource limits defined in `config/tool_resources.yaml`. Per-tool overrides supported.

### 16.3 Default Limits

| Limit | Default | Rationale |
|-------|---------|----------|
| Max memory per tool | 512MB | Prevent runaway allocations |
| Max wall time | 60s | Prevent hung tools |
| Max concurrent | 10 | Prevent resource exhaustion |
| Max calls/min | 1200 | Match exchange rate limits |

### 16.4 Violation Handling

| Violations | Action |
|-----------|--------|
| 1-2 | Log warning |
| 3-4 | Log error, alert |
| 5+ | Circuit breaker: disable tool |

---

## APPENDIX A: CANONICAL VALUES REFERENCE

| Parameter | Canonical Value | Source |
|-----------|----------------|--------|
| Stream prefix | `tsar:` | This document |
| Database file | `tsar.db` | This document |
| Daily loss limit | -2% | This document |
| Max drawdown | 5% from HWM | This document |
| Max positions | 10 (Day1: 3) | This document |
| Kelly fraction | 0.25 (Half-Kelly) | This document |
| Max correlation | 0.7 | This document |
| Message format | MessagePack (JSON fallback) | This document |
| Message envelope | CloudEvents v1.0 | This document §14 |
| LLM provider | BaseLLMProvider abstract class | This document §13 |
| Model config | config/llm_providers.yaml | This document §13.4 |
| Improvement baseline | After 30 trades | This document §15.3 |
| Tool resource guard | ResourceGuard + ToolExecutor | This document §16 |
| Rust version | 1.79 | This document |
| Python version | 3.12 | This document |
| FastAPI port | 8000 | This document |
| Supervisor port | 8001 | This document |
| Redis port | 6379 | This document |

---

## APPENDIX B: GLOSSARY

| Term | Definition |
|------|-----------|
| **TSAR** | Trading Super Agent Regime |
| **VETO_ALL** | Emergency halt: all trading stopped until manual clearance |
| **Kill switch** | Automatic VETO_ALL triggered when daily loss exceeds -2% |
| **HMM** | Hidden Markov Model — regime detection |
| **Half-Kelly** | Position sizing using half the Kelly criterion optimal fraction |
| **HWM** | High Water Mark — peak portfolio value |
| **Paper mode** | Simulated execution; no real money at risk |
| **Live mode** | Real exchange execution; real money at risk |
| **Bootstrap** | First-start data acquisition and model calibration |
| **Flywheel** | Self-reinforcing cycle: trade → learn → improve → trade better |
| **Harness** | Deterministic subsystems (risk, execution) that intelligence cannot override |
| **Regime** | Market state classification (trending, ranging, volatile, breakout) |

---

*This document is the SINGLE SOURCE OF TRUTH for the TSAR Trading Super Agent architecture.*  
*All engineering must reference this document. Where prior documents conflict, this document wins.*

*Consolidated: 2026-07-24 02:27 GMT+8*
