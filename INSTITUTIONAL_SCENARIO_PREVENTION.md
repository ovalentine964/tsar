# Institutional Scenario Prevention Architecture — TSAR

**Institutional Scenario Prevention Council Report**
**Date:** 2026-08-01
**Score: 7.5/10**

---

## Executive Summary

TSAR's superagent architecture — built on Jensen Huang's blueprint of harness, flywheel, knowledge graph, AGI loop, quantum models, and blockchain — provides **multi-layered defense** against institutional-grade failure scenarios. The system's strength lies in its deterministic risk engine (zero LLM in critical path), dual-write kill switch, 7-layer veto protocol, and self-improving flywheel. However, several gaps exist in exchange-level resilience, cross-exchange failover, and real-time correlation regime adaptation.

**Key architectural strengths:**
- Deterministic risk governance — no LLM in kill path
- Dual-write kill switch (file primary, Redis secondary) with fail-safe defaults
- 12-agent superagent architecture with clear separation of concerns
- Self-improving flywheel: TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT
- HMM-based regime detection with rule-based fallback
- Smart order routing (TWAP/VWAP/iceberg) for institutional execution
- Phased recovery protocol after circuit breaker events

**Key architectural gaps:**
- No cross-exchange failover mechanism
- Correlation anomaly detection exists but lacks automated response triggers
- Exchange hack/black swan protocols are manual, not automated
- No MEV protection integration in CeFi execution path
- Model degradation detection relies on periodic evaluation, not real-time drift detection

---

## 1. Regime Change Mid-Trade

### The Institutional Problem

A momentum strategy entered during a trending market suddenly faces a ranging regime. BTC-ETH correlation breaks. ADX drops below 25 overnight. The strategy bleeds money on every false breakout.

### TSAR's Architecture Response

**Detection Layer: `RegimeDetector` (src/agents/regime_detector.py)**

```
┌─────────────────────────────────────────────────────────┐
│                    REGIME DETECTION PIPELINE             │
│                                                         │
│  OHLCV Data ──→ HMM Classifier ──→ Regime State Store  │
│       │              │                    │              │
│       │         (5 states:           Published to        │
│       │    TREND_UP, TREND_DOWN,    tsar:stream:regime   │
│       │    RANGING, HIGH_VOL,           │               │
│       │    UNCERTAIN)                   ▼               │
│       │                          SignalScout adjusts    │
│       └──→ Rule-Based Fallback    scoring weights       │
│            (ADX/ATR/BB/EMA)                             │
└─────────────────────────────────────────────────────────┘
```

**How it works:**

1. **HMM Classifier** (`HMMRegimeClassifier`): Fits a 5-state Gaussian HMM on features: log returns, normalized ATR, ADX, Bollinger Bandwidth. Retrains every 50 cycles. Maps states to regime labels via emission parameter heuristics.

2. **Rule-Based Fallback**: When HMM confidence < 0.3 or hmmlearn unavailable, deterministic rules apply:
   - ATR% > 3.0 → `HIGH_VOLATILITY`
   - ADX > 25 + DI+ > DI- → `STRONG_TREND_UP`
   - ADX > 25 + DI- > DI+ → `STRONG_TREND_DOWN`
   - ADX ≤ 25 + price in BB → `RANGING`
   - Otherwise → `UNCERTAIN`

3. **Correlation Break Detection** (`CorrelationAnalyzer` — src/tools/correlation.py):
   - `detect_anomalies()`: Compares current rolling correlation to historical baseline, flags z-score > 2.0
   - `classify_regime()`: Labels correlation state as "crisis", "normal", "decoupled", or "rotation"
   - Cointegration testing via Engle-Granger method for pairs trading validity

4. **Signal Adaptation**: SignalScout subscribes to `tsar:stream:regime`. When regime changes:
   - Scoring weights can shift (trend-following vs mean-reversion)
   - Factor adjustment penalizes mean-reversion signals in trending markets (ADX > 25 penalty)
   - Multi-timeframe confluence provides cross-timeframe regime confirmation

**Which agent detects it?** `RegimeDetector` (HMM + rules), `CorrelationAnalyzer` (anomaly detection)
**Which guard prevents it?** `RiskGovernor` Layer 6 (drawdown circuit breaker catches the bleed)
**Which tool provides data?** `VolatilityAnalyzer.classify_volatility_regime()`, `CorrelationAnalyzer.detect_anomalies()`
**Which risk component activates?** Drawdown circuit breaker (GREEN→YELLOW→ORANGE→RED)
**Recovery protocol:** Automatic — regime change reduces position sizes via volatility regime factor

### Gap Analysis

| Capability | Status | Notes |
|---|---|---|
| Regime detection (trend↔range) | ✅ Strong | HMM + rule-based fallback |
| Correlation break detection | ✅ Present | Z-score anomaly detection |
| Automatic strategy switching | ⚠️ Partial | Geneticist can retire strategies, but no real-time strategy swap |
| Real-time regime-triggered position adjustment | ⚠️ Partial | Volatility regime factor in metadata, but not yet wired to position sizer |
| Cross-asset correlation response | ❌ Gap | Anomaly detected but no automated hedging/reduction |

**Score: 7/10** — Detection is strong; automated response to correlation breaks needs work.

---

## 2. Liquidity Crisis

### The Institutional Problem

March 2020: BTC drops 50% in hours. Everyone sells. Your stop-loss at $7,000 gets filled at $4,000 because there are no buyers. Exchange goes down during the crash. Your position is unprotected.

### TSAR's Architecture Response

**Multi-Layer Defense:**

```
┌───────────────────────────────────────────────────────────────┐
│                 LIQUIDITY CRISIS DEFENSE                       │
│                                                               │
│  Layer 1: Drawdown Monitor (src/risk/drawdown.py)             │
│    GREEN(<2%) → YELLOW(2-3%) → ORANGE(3-5%) → RED(>5%)       │
│    Position multiplier: 1.0  → 0.5    → 0.0      → KILL      │
│                                                               │
│  Layer 2: Kill Switch (src/risk/kill_switch.py)               │
│    Dual-write: FILE (primary) + Redis (secondary)             │
│    Read path: Redis → File → FAIL-SAFE (assume active)        │
│    Triggers: -2% daily, -5% drawdown, auth failure, manual    │
│                                                               │
│  Layer 3: Connection Monitor (src/risk/connection_monitor.py) │
│    Pings exchange every 30s                                    │
│    3 consecutive failures → Kill Switch ACTIVATE              │
│                                                               │
│  Layer 4: Watchdog (src/risk/watchdog.py)                     │
│    Separate process monitors main process heartbeat            │
│    Heartbeat stale 30s → Kill Switch ACTIVATE                 │
│    Survives main process crash (file-based)                   │
│                                                               │
│  Layer 5: Position Recovery (src/risk/position_recovery.py)   │
│    On startup: verify ALL positions have active stop-losses   │
│    Missing SL → auto-place at max_stop_loss_pct               │
└───────────────────────────────────────────────────────────────┘
```

**The Kill Switch — The Nuclear Option:**

```python
# From src/risk/kill_switch.py
# Activation order: FILE first (survives Redis failure), then Redis
async def activate(self, reason: str = "manual") -> None:
    # 1. Write to file (PRIMARY — survives Redis failure)
    self._write_file(payload)
    # 2. Write to Redis (SECONDARY)
    await self._write_redis(payload)
    # 3. Invoke callback: cancel ALL orders, close ALL positions
    if self._on_activate:
        await self._on_activate(reason)
```

**Critical design decisions:**
- **File is PRIMARY, not Redis.** If Redis crashes during a liquidity crisis, the kill switch still works. The file persists on disk.
- **Fail-safe defaults.** If both Redis and file are unreadable, `is_active()` returns `True`. The system halts by default when uncertain.
- **External kill supported.** `echo '{"active":true,"reason":"external"}' > $TSAR_KILL_SWITCH_PATH` — anyone with file access can halt trading.

**Drawdown Circuit Breaker (4-level progressive):**
- **GREEN** (<2% DD): Normal operation, full sizing
- **YELLOW** (2-3% DD): Position sizes halved (×0.5)
- **ORANGE** (3-5% DD): No new entries allowed (×0.0)
- **RED** (>5% DD): Kill switch, flatten everything

**Daily P&L Monitoring:**
- `-2%` daily loss → ORANGE (halt new trades)
- `-3%` daily loss → RED (flatten all positions)

**Gap-down Protection:**
The stop-loss will fill at market price, which may be far from the stop price. TSAR's defense:
1. Position sizing caps risk at 2% per trade (PositionSizer)
2. Max single position: 15% of equity
3. Kill switch activates before catastrophic loss (5% drawdown threshold)
4. Connection monitor catches exchange outages within 90 seconds

**Which agent detects it?** `RiskGuardian` (Check 1-2), `ConnectionMonitor`
**Which guard prevents it?** Kill Switch, Drawdown Monitor, Connection Monitor, Watchdog
**Which tool provides data?** `DrawdownMonitor.evaluate()`, exchange ping
**Which risk component activates?** Kill Switch → on_activate callback (cancel orders, flatten)
**Recovery protocol:** Gated Recovery Protocol — phased re-entry after deactivation

### Gap Analysis

| Capability | Status | Notes |
|---|---|---|
| Stop-loss on every position | ✅ Strong | Verified on startup, placed before entry |
| Exchange outage detection | ✅ Strong | ConnectionMonitor + Watchdog |
| Slippage on gap-down | ⚠️ Accepted Risk | Stop-loss fills at market; mitigated by position sizing |
| Multi-exchange failover | ❌ Gap | No automatic failover to backup exchange |
| Liquidity-aware order sizing | ⚠️ Partial | SmartOrderRouter checks order book depth |
| Cross-exchange liquidity aggregation | ❌ Gap | Single exchange per trade |

**Score: 8/10** — Excellent kill switch design and progressive circuit breakers. Gap-down and multi-exchange gaps are accepted limitations.

---

## 3. Black Swan Events

### The Institutional Problem

Exchange hack (Mt. Gox, FTX). Regulatory ban (China 2021). Stablecoin depeg (UST/Luna). Your funds are frozen. Your stablecoin is worth zero. There's no one to call.

### TSAR's Architecture Response

**Emergency Protocol Chain:**

```
┌────────────────────────────────────────────────────────────────┐
│                  BLACK SWAN RESPONSE CHAIN                      │
│                                                                │
│  1. Information Agent (src/agents/information_agent.py)        │
│     → Monitors news feeds, social sentiment                    │
│     → Sentiment Agent detects extreme negative sentiment       │
│                                                                │
│  2. Regime Detector                                            │
│     → HIGH_VOLATILITY regime detected                          │
│     → ATR% spikes, BB width expands                            │
│                                                                │
│  3. Drawdown Monitor                                           │
│     → Rapid equity decline triggers circuit breaker            │
│     → GREEN → YELLOW → ORANGE → RED in minutes                 │
│                                                                │
│  4. Kill Switch                                                │
│     → -3% daily loss → RED → Kill Switch ACTIVATED             │
│     → All positions flattened, all orders cancelled             │
│                                                                │
│  5. Manual Override                                            │
│     → Telegram /stop command                                   │
│     → External file write                                      │
│     → Both bypass all logic, immediate halt                    │
│                                                                │
│  6. MandateGate (src/risk/mandate_gate.py)                     │
│     → Can restrict trading to specific symbols                 │
│     → Can block all live trading instantly                     │
└────────────────────────────────────────────────────────────────┘
```

**Exchange Hack Scenario:**

1. **Detection**: ConnectionMonitor loses connection to exchange (3 consecutive pings fail)
2. **Response**: Kill switch activates within 90 seconds
3. **Position protection**: All positions have pre-placed stop-losses on the exchange
4. **Fund protection**: TSAR doesn't hold funds on exchange beyond active positions (architectural assumption)

**Regulatory Ban Scenario:**

1. **Detection**: SentimentAgent/MacroAgent detects extreme negative news flow
2. **Response**: RegimeDetector shifts to HIGH_VOLATILITY, circuit breakers tighten
3. **Manual intervention**: MandateGate can block specific symbols/regions
4. **Kill switch**: Manual /stop via Telegram for immediate halt

**Stablecoin Depeg Scenario:**

1. **Detection**: CorrelationAnalyzer detects correlation anomaly (USDT/USDC breaking peg)
2. **Response**: Price feeds show deviation, regime shifts to HIGH_VOLATILITY
3. **Limitation**: TSAR relies on exchange price feeds — if the exchange itself shows wrong prices, detection is delayed

**The Watchdog — Surviving Process Death:**

```python
# From src/risk/watchdog.py
# Separate process monitors the main TSAR process
# If main process dies (crash, OOM, kill -9):
#   → Heartbeat file goes stale
#   → Watchdog detects after 30 seconds (configurable)
#   → Activates kill switch directly via file write
#   → Survives main process death entirely
```

**Which agent detects it?** `SentimentAgent`, `MacroAgent`, `RegimeDetector`, `ConnectionMonitor`
**Which guard prevents it?** Kill Switch, MandateGate, Watchdog
**Which tool provides data?** News feeds, sentiment analysis, exchange connectivity
**Which risk component activates?** Kill Switch (NUCLEAR veto), circuit breakers
**Recovery protocol:** Manual deactivation required. Gated Recovery Protocol (5% → 10% → 25% → 50% → 100% over 24-192h)

### Gap Analysis

| Capability | Status | Notes |
|---|---|---|
| Exchange hack detection | ⚠️ Indirect | Connection loss detected; no direct hack detection |
| Regulatory ban response | ⚠️ Manual | MandateGate can block, but requires human trigger |
| Stablecoin depeg detection | ⚠️ Partial | Correlation anomaly can flag, but no specific depeg monitor |
| Fund recovery protocol | ❌ Gap | No automated fund recovery across exchanges |
| Emergency communication | ✅ Strong | Telegram alerts, file-based external kill |
| Process crash recovery | ✅ Strong | Watchdog survives main process death |

**Score: 6/10** — Good detection and halt mechanisms, but black swan response is largely reactive/manual. No automated cross-exchange recovery.

---

## 4. Execution Failures

### The Institutional Problem

Your order is rejected (insufficient balance). Your $100 order moves the market (slippage). By the time your order reaches the exchange, the price has moved 50 bps (latency). Your stop-loss triggers but the exchange is overloaded.

### TSAR's Architecture Response

**Execution Pipeline with Safety Nets:**

```
┌──────────────────────────────────────────────────────────────────┐
│                    EXECUTION SAFETY PIPELINE                      │
│                                                                  │
│  ExecutionSniper (src/agents/execution_sniper.py)                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. VALIDATE order parameters                             │    │
│  │ 2. PLACE stop-loss FIRST (safety before entry!)          │    │
│  │ 3. Smart routing decision:                               │    │
│  │    ├─ < $10k notional → direct market order              │    │
│  │    └─ > $10k notional → SmartOrderRouter                 │    │
│  │         ├─ < 1% of book → direct                         │    │
│  │         ├─ 1-5% of book → sliced execution               │    │
│  │         ├─ 5-15% of book → TWAP                          │    │
│  │         └─ > 15% of book → VWAP or TWAP                  │    │
│  │ 4. MONITOR fills and slippage                            │    │
│  │ 5. Place take-profit                                     │    │
│  │ 6. Publish trade.executed event                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  Slippage Thresholds:                                            │
│    10 bps (0.1%) → LOG WARNING                                  │
│    50 bps (0.5%) → ABORT AND ALERT                              │
│                                                                  │
│  Order Timeout: 30 seconds → check status, alert if stuck       │
└──────────────────────────────────────────────────────────────────┘
```

**Smart Order Router — Institutional Execution (src/tools/order_router.py):**

The SmartOrderRouter implements three institutional-grade execution strategies:

1. **TWAP (Time-Weighted Average Price)**:
   - Splits large orders into equal slices over time
   - Auto-calculates slice count based on order book depth (target: 2% of visible liquidity per slice)
   - Price limit support (skip slices if price moves beyond limit)
   - Monitors fill quality per slice

2. **VWAP (Volume-Weighted Average Price)**:
   - Distributes order proportional to historical volume
   - Fetches 1m OHLCV data to build volume profile
   - Higher-volume periods get larger slices
   - Exponential smoothing to avoid extreme concentration

3. **Iceberg Orders**:
   - Shows only `visible_qty` at a time
   - Auto-refreshes child orders as each fills
   - Prevents detection of large order flow

**Market Impact Estimation:**
```python
# Square-root market impact model
impact = coefficient * sqrt(order_size / avg_daily_volume)

# Order book walk simulation
# Walks the book to estimate average fill price vs mid-price
```

**Execution Failure Handling:**

| Failure Type | Response |
|---|---|
| Order rejected (balance) | `_publish_execution_failure()` → `tsar.trade.failed.v1` |
| Stop-loss placement fails | Entry order ABORTED — no unprotected position |
| Entry order fails | Stop-loss CANCELLED — clean state |
| Slippage > 50 bps | CRITICAL alert, consider manual review |
| Order timeout (30s) | Check status, alert if stuck |
| Entry fails after SL placed | Cancel SL, publish failure event |

**Which agent detects it?** `ExecutionSniper` (monitors fills), `ExecutionTracker`
**Which guard prevents it?** Stop-loss-before-entry protocol, slippage thresholds
**Which tool provides data?** `SmartOrderRouter`, `ExecutionTools`, `MarketDataTools`
**Which risk component activates?** Slippage alerts, order timeout handling
**Recovery protocol:** Automatic — failed orders cancel protective orders, publish failure event

### Gap Analysis

| Capability | Status | Notes |
|---|---|---|
| Order rejection handling | ✅ Strong | Clean failure path, cancel protective orders |
| Slippage monitoring | ✅ Strong | BPS tracking, warning/critical thresholds |
| Large order execution | ✅ Strong | TWAP, VWAP, iceberg, adaptive routing |
| Market impact estimation | ✅ Strong | Square-root model + order book walk |
| Order timeout handling | ✅ Present | 30s timeout, status check |
| Latency compensation | ⚠️ Partial | Price limit checks in TWAP/VWAP, but no predictive latency model |
| Exchange overload handling | ⚠️ Partial | ConnectionMonitor detects outage; no queue/retry logic |

**Score: 8/10** — Excellent institutional-grade execution with smart routing. Latency compensation is the main gap.

---

## 5. Model/Strategy Failures

### The Institutional Problem

Your strategy worked in backtest but fails live (overfitting). Market structure changed (new regulations, new participants). Your edge disappeared because everyone discovered it. Your model degrades silently.

### TSAR's Architecture Response

**The Flywheel — Self-Improving Architecture:**

```
┌────────────────────────────────────────────────────────────────────┐
│              FLYWHEEL: TRADE → OBSERVE → REFLECT → ADAPT          │
│                                                                    │
│  FlywheelOrchestrator (src/agents/flywheel_orchestrator.py)        │
│                                                                    │
│  Every N trades (batch_size=10, cooldown=5min):                    │
│                                                                    │
│  Step 1: EXTRACT — ShadowExtractor                                 │
│    → Analyzes closed trade history                                  │
│    → Extracts implicit rules from winning trades                    │
│    → Uses LLM to identify patterns human traders used              │
│                                                                    │
│  Step 2: VALIDATE — RuleValidator                                  │
│    → Backtests extracted rules against OHLCV data                  │
│    → Filters rules with win_rate < 55% or insufficient data        │
│                                                                    │
│  Step 3: MUTATE — GenomeMutator                                    │
│    → Proposes strategy parameter changes                            │
│    → Confidence-weighted proposals (min_confidence=0.6)             │
│                                                                    │
│  Step 4: EVOLVE — StrategyGeneticist                               │
│    → BacktestEngine (G6): Historical validation                    │
│    → WalkForwardValidator (G7): Overfitting detection               │
│    → MonteCarloSimulator (G8): Confidence intervals                │
│    → FactorBenchmarker (G9): IC/IR benchmarks                      │
│                                                                    │
│  If accepted → Strategy parameters updated in SignalScout          │
│  If rejected → Logged, no change                                   │
└────────────────────────────────────────────────────────────────────┘
```

**Overfitting Detection (G7 — Walk-Forward Validation):**

```python
# From src/agents/strategy_geneticist.py
# WalkForwardValidator: Rolling train/test windows
# Detects overfitting when train performance >> test performance

wf_config = WalkForwardConfig(
    n_windows=5,           # 5 rolling windows
    train_ratio=0.70,      # 70% train, 30% test
    overfit_threshold=3.0, # Train Sharpe / Test Sharpe > 3.0 = overfit
)

# If overfitting_score > 3.0 → REJECT strategy
# If consistency_score < 0.4 → REJECT (too few profitable windows)
```

**Strategy Retirement Gates:**

| Condition | Action |
|---|---|
| Rolling Sharpe < 0.5 for 30 days | Consider retirement |
| Drawdown > 15% | PAUSE strategy |
| Drawdown > 20% | RETIRE strategy |
| Win rate < 40% over 50 trades | RETIRE strategy |

**Monte Carlo Confidence (G8):**
- 1,000 simulations per strategy evaluation
- Probability of ruin > 10% → REJECT
- Probability of profit < 50% → REJECT
- Sharpe ratio confidence intervals computed

**Factor Benchmarking (G9):**
- Periodic IC/IR benchmarks on factor library
- Tracks factor decay over time
- Identifies when factors lose predictive power

**Knowledge Graph Integration:**
- `TradeMemory` (src/knowledge/trade_memory.py): SQLite WAL-mode canonical record of every trade
- `KnowledgeGraph` (src/knowledge/knowledge_graph.py): Entity relationships
- `LessonArchive` (src/knowledge/lesson_archive.py): Post-trade reflections
- `PatternLibrary` (src/knowledge/pattern_library.py): Detected pattern catalog

**Which agent detects it?** `StrategyGeneticist` (evaluation pipeline), `FlywheelOrchestrator` (triggers)
**Which guard prevents it?** Walk-forward overfitting gate, Monte Carlo ruin probability gate
**Which tool provides data?** `BacktestEngine`, `WalkForwardValidator`, `MonteCarloSimulator`, `FactorBenchmarker`
**Which risk component activates?** Strategy retirement (genome status update)
**Recovery protocol:** Flywheel auto-proposes mutations; Geneticist evaluates and applies

### Gap Analysis

| Capability | Status | Notes |
|---|---|---|
| Overfitting detection | ✅ Strong | Walk-forward validation (G7) |
| Strategy degradation detection | ✅ Strong | Rolling Sharpe, drawdown gates |
| Confidence intervals | ✅ Strong | Monte Carlo simulation (G8) |
| Factor decay tracking | ✅ Present | Factor benchmarking (G9) |
| Real-time model drift detection | ⚠️ Gap | Evaluation is periodic, not per-trade |
| Edge competition detection | ❌ Gap | No monitoring of strategy crowding |
| Automated strategy rotation | ⚠️ Partial | Can retire/pause, but no auto-rotation to new regime-appropriate strategy |

**Score: 7/10** — Strong backtesting and overfitting detection. Real-time drift and competition monitoring are gaps.

---

## 6. Coordination Failures

### The Institutional Problem

Multiple strategies conflict: momentum says buy, mean-reversion says sell. Risk guards disagree: position sizer approves, leverage guard vetoes. Agents send contradictory signals. The system oscillates.

### TSAR's Architecture Response

**Orchestrator — The Conductor (src/agents/orchestrator.py):**

```
┌──────────────────────────────────────────────────────────────────┐
│                    SIGNAL FLOW ARCHITECTURE                       │
│                                                                  │
│  SignalScout ──→ signal.detected ──→ RiskGuardian ──→ ExecSniper │
│       │                                  │                  │     │
│       │                                  │                  │     │
│  (detect)                          (evaluate)          (execute)  │
│       │                                  │                  │     │
│       ▼                                  ▼                  ▼     │
│  tsar:stream:signals            tsar:stream:risk_decisions        │
│                                                                  │
│  CONFLICT RESOLUTION:                                            │
│  1. SignalScout: ONE signal per symbol per cycle                 │
│  2. RiskGuardian: Sequential evaluation, first HARD veto wins    │
│  3. Orchestrator: Event-driven, no concurrent evaluations        │
│  4. Symbol cooldown: 30 minutes between trades per symbol        │
│  5. Conflicting positions: BLOCKED (opposite direction check)    │
└──────────────────────────────────────────────────────────────────┘
```

**The 7-Layer Veto Protocol (RiskGovernor):**

Every signal must pass ALL layers. First HARD/NUCLEAR veto wins.

| Layer | Check | Veto Level |
|---|---|---|
| 1 | Kill Switch | NUCLEAR |
| 2 | Input Validation | HARD |
| 3 | Anti-FOMO (score ≥ 0.6) | FIRM |
| 4 | Time Rules (blackout windows) | HARD |
| 5 | Anti-Behavioral Guards | FIRM |
| 6 | Drawdown Circuit Breaker | HARD/NUCLEAR |
| 7 | Position Limits | FIRM |

**Anti-Behavioral Guards (src/risk/guards.py) — Deterministic:**

| Guard | Trigger | Response |
|---|---|---|
| Anti-Revenge | 3 consecutive losses | 60-minute cooldown |
| Anti-Greed | 5+ win streak | 70% position sizing |
| Anti-FOMO | Score < 0.6 | Signal blocked |
| Anti-Overconfidence | 5+ win streak | 70% sizing (10+: 50%) |

**Conflict Resolution Mechanisms:**

1. **Single Signal Source**: SignalScout produces ONE signal per symbol per scan cycle. No conflicting signals from the same source.

2. **Sequential Risk Evaluation**: RiskGuardian evaluates signals sequentially. First HARD/NUCLEAR veto terminates evaluation. No ambiguity.

3. **Symbol Cooldown**: 30-minute cooldown per symbol prevents rapid conflicting trades.

4. **Conflicting Position Check**: RiskGuardian Check 8 blocks signals that would create opposite positions on the same symbol.

5. **Orchestrator Coordination**: The Orchestrator manages agent lifecycle and ensures event-driven flow (scan → signal → risk → execute → reflect). No concurrent evaluations of the same signal.

6. **MandateGate Pre-Filter**: Before any risk evaluation, MandateGate checks if the trade is authorized by the human mandate. This prevents even "safe" but unauthorized trades.

**Agent Health Monitoring:**

```python
# Orchestrator monitors all agent heartbeats
heartbeat_timeout = heartbeat_interval * 3
# Agents that miss heartbeats get logged as warnings
# No automatic agent restart (yet) — manual intervention needed
```

**Which agent detects it?** `Orchestrator` (coordination), `RiskGuardian` (evaluation)
**Which guard prevents it?** 7-layer veto protocol, symbol cooldown, conflicting position check
**Which tool provides data?** Guard state persistence, portfolio state
**Which risk component activates?** Veto at appropriate level (SOFT/FIRM/HARD/NUCLEAR)
**Recovery protocol:** N/A — conflicts are prevented, not recovered from

### Gap Analysis

| Capability | Status | Notes |
|---|---|---|
| Single signal source | ✅ Strong | One signal per symbol per cycle |
| Sequential risk evaluation | ✅ Strong | First veto wins, no ambiguity |
| Symbol cooldown | ✅ Present | 30-minute cooldown |
| Conflicting position prevention | ✅ Strong | Opposite direction check |
| Multi-strategy coordination | ⚠️ Partial | Current design: one strategy (mean reversion). Multiple strategies would need orchestration |
| Agent disagreement resolution | ✅ Strong | RiskGuardian has absolute veto power |
| Agent health monitoring | ⚠️ Partial | Heartbeat monitoring exists, no auto-restart |

**Score: 8/10** — Excellent conflict prevention in current single-strategy design. Multi-strategy coordination is the main gap for future scaling.

---

## Overall Score Summary

| Scenario | Score | Key Strength | Key Gap |
|---|---|---|---|
| 1. Regime Change | 7/10 | HMM + rule-based dual detection | Automated correlation break response |
| 2. Liquidity Crisis | 8/10 | Dual-write kill switch, fail-safe defaults | Multi-exchange failover |
| 3. Black Swan | 6/10 | Watchdog, external kill, progressive circuit breakers | Automated response (largely manual) |
| 4. Execution Failures | 8/10 | Smart routing (TWAP/VWAP/iceberg), slippage monitoring | Latency compensation |
| 5. Model Failures | 7/10 | Walk-forward + Monte Carlo overfitting gates | Real-time drift detection |
| 6. Coordination Failures | 8/10 | 7-layer veto, symbol cooldown, sequential evaluation | Multi-strategy orchestration |
| **OVERALL** | **7.5/10** | | |

---

## Architectural Recommendations

### Priority 1 (Critical)
1. **Cross-exchange failover**: Add exchange gateway abstraction with automatic failover to backup exchange during outages
2. **Automated black swan response**: Wire sentiment/regime alerts to automatic position reduction (not just halt)
3. **Real-time model drift detection**: Add per-trade Sharpe tracking with rolling window alerts

### Priority 2 (Important)
4. **Correlation break → position reduction**: When `CorrelationAnalyzer.detect_anomalies()` finds severe anomalies, automatically reduce exposure to affected pairs
5. **Liquidity-aware position sizing**: Integrate order book depth into `PositionSizer` calculation
6. **Agent auto-restart**: Orchestrator should restart unhealthy agents automatically

### Priority 3 (Enhancement)
7. **Edge competition detection**: Monitor order book patterns for signs of strategy crowding
8. **Multi-strategy orchestration**: Design explicit conflict resolution for when multiple active strategies generate opposing signals
9. **Predictive latency model**: Use exchange response time history to adjust order timing

---

## TSAR's Institutional Superpowers

What makes TSAR architecturally superior to typical retail trading bots:

1. **Deterministic Risk Engine**: Zero LLM calls in the critical path. Kill switch, circuit breakers, position sizing — all pure math. LLMs can hallucinate; math can't.

2. **Dual-Write Kill Switch**: File-primary, Redis-secondary. Survives Redis failure, supports external kill, fails safe when uncertain. This is institutional-grade state management.

3. **Watchdog Process**: Separate process monitors the main process. If TSAR crashes (OOM, kill -9, unhandled exception), the watchdog detects the stale heartbeat and halts trading. This is how safety-critical systems are built.

4. **Self-Improving Flywheel**: Every trade feeds back into the system. ShadowExtractor mines rules from history, RuleValidator backtests them, GenomeMutator proposes improvements, StrategyGeneticist evaluates with overfitting gates. The system gets smarter with every trade.

5. **7-Layer Veto Protocol**: Every signal must pass through kill switch, input validation, anti-FOMO, time rules, behavioral guards, circuit breakers, AND position limits. No single point of failure.

6. **Phased Recovery Protocol**: After a kill switch event, position sizes don't jump back to 100%. They ramp through 5% → 10% → 25% → 50% → 100% over 24-192 hours, with gates at each phase requiring positive P&L, win rate, and Sharpe validation.

7. **Mandate-Based Authorization**: The MandateGate sits before the risk engine. Even if a trade is "safe" (risk-approved), it must also be "authorized" (mandate-approved). This separates "can we trade?" from "should we trade?"

---

*Report prepared by the Institutional Scenario Prevention Council for TSAR Superagent Architecture Review.*
*Source files analyzed: 25+ Python modules across agents/, risk/, tools/, strategy/, knowledge/.*
