# TRADING SUPER AGENT — BLUEPRINT v2.0
## "Built for ONE job: autonomous capital compounding under strict risk constraints"

> *"A company that is AI-native, the intelligence that's inside the company is proprietary. The skills that the company has is proprietary. You cannot outsource your intelligence. You cannot outsource your skills."* — Jensen Huang, 2025

> *"Super agent is domain-specific. Built for ONE job."* — Jensen Huang

**Blueprint Status:** Architecture Design v2.0
**Target:** 23-year-old developer, $10 starting capital, building from scratch
**Tech Stack:** Python 3.11+ / TA-Lib / AkShare / SQLite / Redis

---

## Part I: THE ONE JOB

### 1.1 Domain Boundary — What Is the Trading Super Agent?

The Trading Super Agent has **one job**:

```
Find statistical edges in liquid markets,
size them correctly,
execute them flawlessly,
and get measurably better at all three with every single trade.
```

**Domain Boundaries:**

| In Scope | Out of Scope |
|---|---|
| Signal generation & validation | Financial advice to humans |
| Position sizing & risk management | Tax optimization |
| Execution optimization | Accounting / bookkeeping |
| Strategy evolution & refinement | News commentary |
| Regime detection & adaptation | Social media / marketing |
| Trade journaling & pattern learning | Regulatory compliance filing |
| Multi-timeframe technical analysis | Fundamental valuation models |

### 1.2 The One-Sentence Thesis

> A Trading Super Agent is not a bot that executes trades — it is a **self-improving market intelligence system** that accumulates proprietary knowledge about how markets behave, encodes that knowledge into executable strategies, and gets measurably better every time it runs.

---

## Part II: THE PROPRIETARY KNOWLEDGE

### 2.1 What the Agent Accumulates (The Moat)

A trading bot has no memory. A super agent has **five proprietary knowledge stores:**

#### Store 1: Trade Memory (`trades.db`)

Every single trade — entry, exit, context, outcome, reflection — stored permanently. This is the raw material of intelligence.

```sql
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL,
    asset           TEXT NOT NULL,          -- 'BTC/USDT', 'AAPL', etc.
    direction       TEXT NOT NULL,          -- 'long' | 'short'
    timeframe       TEXT NOT NULL,          -- '1h', '4h', '1d'
    strategy_name   TEXT NOT NULL,          -- which strategy generated this
    signal_confidence REAL,                 -- 0.0 - 1.0
    regime_at_entry TEXT,                   -- 'trending_up' | 'ranging' | 'volatile'
    
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    position_size   REAL NOT NULL,          -- in quote currency
    stop_loss       REAL,
    take_profit     REAL,
    
    pnl_absolute    REAL,
    pnl_percent     REAL,
    hold_duration   INTEGER,               -- in minutes
    max_favorable   REAL,                   -- max unrealized profit
    max_adverse     REAL,                   -- max unrealized loss
    slippage        REAL,
    fees            REAL,
    
    exit_reason     TEXT,                   -- 'tp_hit' | 'sl_hit' | 'trailing' | 'time' | 'manual'
    was_correct     BOOLEAN,
    
    -- Context snapshot at entry
    market_context  JSON,                   -- full indicator state
    regime_context  JSON,                   -- regime probabilities
    catalyst        TEXT,                   -- what triggered the signal
    
    -- Post-trade (filled by Reflection Engine)
    reflection      TEXT,
    lesson          TEXT,
    error_category  TEXT,                   -- 'timing' | 'sizing' | 'regime' | 'execution' | 'none'
    
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trades_strategy ON trades(strategy_name);
CREATE INDEX idx_trades_regime ON trades(regime_at_entry);
CREATE INDEX idx_trades_asset ON trades(asset);
CREATE INDEX idx_trades_time ON trades(timestamp);
```

#### Store 2: Strategy Genome (`strategies/`)

Each strategy is a **living, evolving document** — not static config, but a self-modifying program with a changelog and performance stats.

```yaml
# strategies/momentum_breakout.yaml
strategy:
  name: momentum_breakout
  version: 3.2.1
  created: 2026-07-01
  last_evolved: 2026-07-24
  author: "super_agent_v1"
  
  thesis: |
    When price breaks above the 20-period high with volume confirmation,
    momentum tends to continue for 2-5 periods in trending regimes.
    This strategy exploits the tendency of breakout moves to attract
    follow-through buying from momentum participants.

  # Performance by regime (CRITICAL — this is what makes it adaptive)
  regime_performance:
    trending_up:
      win_rate: 0.61
      avg_win: 2.3
      avg_loss: 1.1
      expectancy: 0.42
      sample_size: 147
      status: active
    trending_down:
      win_rate: 0.44
      avg_win: 1.8
      avg_loss: 1.5
      expectancy: -0.08
      sample_size: 89
      status: disabled
    ranging:
      win_rate: 0.38
      avg_win: 1.2
      avg_loss: 1.4
      expectancy: -0.15
      sample_size: 203
      status: disabled
    volatile:
      win_rate: 0.52
      avg_win: 3.1
      avg_loss: 2.0
      expectancy: 0.21
      sample_size: 67
      status: active
    breakout:
      win_rate: 0.68
      avg_win: 4.2
      avg_loss: 1.8
      expectancy: 1.12
      sample_size: 34
      status: active

  # Executable entry rules
  entry_rules:
    - id: price_breakout
      description: "Price breaks above 20-period high"
      indicator: highest_high
      params: { period: 20 }
      condition: close > highest_high
      confidence_weight: 0.30
    
    - id: volume_confirmation
      description: "Volume exceeds 1.5x 20-period average"
      indicator: volume_sma
      params: { period: 20 }
      condition: volume > 1.5 * volume_sma
      confidence_weight: 0.25
    
    - id: rsi_filter
      description: "RSI between 55 and 75 (momentum but not overbought)"
      indicator: rsi
      params: { period: 14 }
      condition: rsi > 55 AND rsi < 75
      confidence_weight: 0.20
    
    - id: regime_match
      description: "Current regime is favorable"
      condition: regime IN [trending_up, volatile, breakout]
      confidence_weight: 0.25

  # Risk parameters
  risk:
    max_position_pct: 2.0
    stop_loss_atr_multiple: 1.5
    take_profit_atr_multiple: 3.0
    trailing_stop: { activate_at_atr: 2.0, trail_by_atr: 1.0 }
    max_hold_minutes: 480
    max_concurrent: 2

  # Evolution log
  changelog:
    - version: 3.2.1
      date: 2026-07-24
      change: "Tightened ATR stop from 2.0x to 1.5x after July drawdown analysis"
      evidence: "147 trades showed 23% of losses hit 1.8x ATR before reversing"
      impact: "+0.08 expectancy improvement in backtest"
    
    - version: 3.2.0
      date: 2026-07-15
      change: "Added RSI filter to prevent overbought entries"
      evidence: "Entries with RSI > 75 had 31% win rate vs 58% overall"
      impact: "Reduced trade frequency by 15%, improved win rate by 9%"
    
    - version: 3.1.0
      date: 2026-07-08
      change: "Disabled in ranging regime"
      evidence: "203 trades in ranging regime showed -0.15 expectancy"
      impact: "Eliminated ~40% of losing trades"
```

#### Store 3: Regime State (`regime_state.json`)

Real-time market regime classification — the agent's "sense" of what kind of market it's in.

```json
{
  "timestamp": "2026-07-24T00:30:00+08:00",
  "current_regime": "trending_up",
  "confidence": 0.82,
  "time_in_regime_minutes": 1440,
  "regime_probabilities": {
    "trending_up": 0.82,
    "ranging": 0.10,
    "volatile": 0.05,
    "breakout": 0.02,
    "trending_down": 0.01
  },
  "volatility_state": "expanding",
  "correlation_state": "risk_on",
  "transition_signals": {
    "trending_to_ranging": 0.15,
    "trending_to_volatile": 0.08,
    "trending_to_breakout": 0.03
  },
  "regime_history": [
    {"regime": "ranging", "start": "2026-07-20T10:00:00", "end": "2026-07-22T14:00:00", "duration_hours": 52},
    {"regime": "trending_up", "start": "2026-07-22T14:00:00", "end": null, "duration_hours": 58}
  ]
}
```

#### Store 4: Pattern Library (`patterns/`)

Novel patterns discovered by the agent through trade analysis — patterns not in any textbook, learned from YOUR market experience.

```yaml
# patterns/discovered/volume_spike_reversal.yaml
pattern:
  name: volume_spike_reversal
  discovered_by: super_agent_v1
  discovered_date: 2026-08-15
  discovery_context: "Noticed in trade #847 reflection — volume spike preceded reversal 78% of time"
  
  description: |
    When a 15m candle shows 3x+ volume above the 20-period average
    without a corresponding price move (close within 30% of candle range),
    the move tends to reverse within 2-3 candles.
  
  detection_rules:
    - volume > 3.0 * volume_sma(20)
    - abs(close - open) / (high - low) < 0.3
    - timeframe == '15m'
  
  action: "Fade the move with tight stop beyond spike high"
  
  stats:
    times_seen: 34
    times_exploitable: 28
    avg_pnl_pct: 0.82
    win_rate: 0.71
    false_positive_rate: 0.18
  
  status: active  # active | monitoring | retired
```

#### Store 5: Lesson Archive (`lessons/`)

Distilled insights from trade reflections — the agent's "wisdom."

```yaml
# lessons/2026-07.md
lessons:
  - id: L-0847
    date: 2026-07-24
    from_trade: T-847
    category: timing
    lesson: "In trending regimes, waiting for a pullback to VWAP before entry
             improves average entry price by 0.4% — worth the 15% of signals
             we miss by waiting."
    confidence: 0.78
    applied_to: [momentum_breakout, trend_following]
    times_applied: 12
    impact: "+0.06 expectancy since adoption"
    
  - id: L-0852
    date: 2026-07-23
    from_trade: T-852
    category: regime
    lesson: "Volume expansion without price expansion in a trending market
             often precedes a range transition. Reduce position sizes by 50%
             when this pattern appears."
    confidence: 0.65
    applied_to: [risk_engine]
    times_applied: 3
    impact: "Avoided 2 potential losses totaling -1.2%"
```

### 2.2 Knowledge Accumulation Timeline

| Timeframe | Knowledge Volume | Quality |
|---|---|---|
| Week 1-2 | 50-100 trades | Raw data, no patterns yet |
| Month 1 | 200-400 trades | First regime correlations visible |
| Month 3 | 1000+ trades | Strategy performance by regime is reliable |
| Month 6 | 3000+ trades | Pattern library has 10+ discovered patterns |
| Year 1 | 10,000+ trades | Knowledge base IS the competitive edge |

---

## Part III: THE HARNESS

### 3.1 What Is the "Harness" for Trading?

The harness is the **infrastructure layer** that wraps around "intelligence that's good enough" to produce frontier-level trading capabilities. It consists of:

```
┌──────────────────────────────────────────────────────────────────────┐
│                        TRADING SUPER AGENT                           │
│                         (The Harness)                                │
│                                                                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────┐  │
│  │   SIGNAL    │  │    RISK    │  │  EXECUTION │  │  REFLECTION  │  │
│  │   ENGINE    │→ │   ENGINE   │→ │   ENGINE   │→ │   ENGINE     │  │
│  │             │  │  (VETO)    │  │            │  │              │  │
│  └────────────┘  └────────────┘  └────────────┘  └──────────────┘  │
│       ↑              ↑                ↑                │            │
│       │              │                │                │            │
│       └──────────────┴────────────────┴────────────────┘            │
│                         FLYWHEEL LOOP                                │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                      KNOWLEDGE LAYER                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  Trade Memory │  │ Regime State │  │ Strategy     │              │
│  │  (SQLite)     │  │ (Redis)      │  │ Genome (YAML)│              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│  ┌──────────────┐  ┌──────────────┐                                │
│  │ Pattern Lib   │  │ Lesson Archive│                                │
│  │ (YAML)        │  │ (YAML/MD)    │                                │
│  └──────────────┘  └──────────────┘                                │
├──────────────────────────────────────────────────────────────────────┤
│                        DATA LAYER                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ Market Data   │  │  Technical   │  │ Alternative  │              │
│  │ (OHLCV/Tick)  │  │  Indicators  │  │ Data         │              │
│  │ AkShare/CCXT  │  │  (TA-Lib)    │  │ (Sentiment)  │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 Harness Component Deep Dive

#### A. Signal Engine — "The Scout"

**Job:** Scan all configured assets and timeframes for strategy matches.

**Technical Indicator Arsenal** (using `ta` / `ta-lib`):

| Category | Indicators | Purpose |
|---|---|---|
| Trend | SMA, EMA, MACD, ADX, Ichimoku, SuperTrend | Direction & strength |
| Momentum | RSI, Stochastic, Williams %R, CCI, ROC | Overbought/oversold |
| Volatility | Bollinger Bands, ATR, Keltner Channels, Donchian | Range & expansion |
| Volume | OBV, VWAP, MFI, CMF, Volume Profile | Confirmation |
| Support/Resistance | Pivot Points, Fibonacci, Volume-at-Price | Key levels |

**Multi-Timeframe Analysis:**

```
Timeframe Hierarchy:
  Monthly (1M)  → Macro trend direction
  Weekly  (1W)  → Intermediate trend
  Daily   (1D)  → Primary trading timeframe
  4H            → Swing entry/exit
  1H            → Intraday signals
  15m           → Precise entry timing
  5m            → Scalping (if applicable)
  1m            → Execution timing only (not signal generation)

Rule: Higher timeframe trend MUST agree with signal direction
      (e.g., don't go short on 15m if daily is strongly uptrending)
```

**Signal Output:**

```python
@dataclass
class Signal:
    id: str
    timestamp: datetime
    asset: str
    direction: str          # 'long' | 'short'
    timeframe: str
    strategy_name: str
    confidence: float       # 0.0 - 1.0
    
    # Entry
    entry_price: float
    entry_type: str         # 'market' | 'limit'
    
    # Risk
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    
    # Context
    catalyst: str           # Human-readable reason
    indicators: dict        # Snapshot of all indicator values
    multi_tf_alignment: dict # Agreement across timeframes
    
    # Falsification (CRITICAL)
    falsification_condition: str  # "I'm wrong if..."
    max_hold_time: int     # Minutes
    
    def is_valid(self) -> bool:
        """Self-validation before submission to risk engine"""
        return (
            self.confidence >= 0.5 and
            self.risk_reward_ratio >= 1.5 and
            self.stop_loss > 0 and
            self.take_profit > 0 and
            self.falsification_condition != ""
        )
```

#### B. Risk Engine — "The Immune System"

**Job:** Evaluate every signal against risk rules BEFORE execution. Has **absolute veto power.**

**Hard Rules (Non-Negotiable — encoded in code, not config):**

```python
class RiskEngine:
    # HARD LIMITS — Cannot be overridden by agent or config
    MAX_SINGLE_TRADE_RISK = 0.02      # 2% of capital per trade
    MAX_DAILY_DRAWDOWN = 0.03         # 3% daily drawdown limit
    MAX_PORTFOLIO_HEAT = 0.06         # 6% total open risk
    MAX_OPEN_POSITIONS = 5
    MAX_CORRELATED_POSITIONS = 3      # Max positions in correlated assets
    REQUIRE_STOP_LOSS = True          # Every position MUST have a stop
    
    def evaluate(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        """
        Returns APPROVED (with sizing) or REJECTED (with reason).
        This function CANNOT be modified by the agent.
        """
        checks = [
            self._check_drawdown(signal, portfolio),
            self._check_position_size(signal, portfolio),
            self._check_correlation(signal, portfolio),
            self._check_portfolio_heat(signal, portfolio),
            self._check_regime_match(signal),
            self._check_strategy_allowed(signal),
            self._check_max_positions(portfolio),
            self._check_stop_loss(signal),
        ]
        
        for check in checks:
            if not check.passed:
                return RiskDecision.rejected(
                    signal=signal,
                    reason=check.reason,
                    check_name=check.name
                )
        
        # Calculate optimal position size (Kelly Criterion, fractional)
        optimal_size = self._kelly_size(signal, portfolio)
        max_size = portfolio.equity * self.MAX_SINGLE_TRADE_RISK
        
        return RiskDecision.approved(
            signal=signal,
            position_size=min(optimal_size, max_size),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit
        )
```

**Position Sizing — Fractional Kelly:**

```
Kelly % = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win

Fractional Kelly (conservative): actual_size = kelly_pct * 0.25

Example:
  Win rate: 58%, Avg win: 2.3%, Avg loss: 1.1%
  Kelly = (0.58 * 2.3 - 0.42 * 1.1) / 2.3 = 37.8%
  Fractional Kelly = 37.8% * 0.25 = 9.5%
  
  With $10 capital: position size = $0.95
```

#### C. Execution Engine — "The Hands"

**Job:** Get the best possible fill on approved orders.

```python
class ExecutionEngine:
    """
    Execution modes based on capital level:
    
    $10-100:    Paper trading → Micro-lots (crypto: Binance min $5)
    $100-1000:  Small positions, market orders
    $1000+:     Smart order routing, limit orders, TWAP
    """
    
    def execute(self, decision: RiskDecision) -> Execution:
        # 1. Pre-flight check
        assert decision.status == 'approved'
        assert decision.stop_loss is not None
        
        # 2. Choose execution method
        if self.mode == 'paper':
            return self._paper_execute(decision)
        elif self.mode == 'live':
            return self._live_execute(decision)
    
    def _live_execute(self, decision: RiskDecision) -> Execution:
        # Place stop-loss FIRST (before entry — safety net)
        self._place_stop_loss(decision)
        
        # Place entry order
        order = self._place_entry(decision)
        
        # Verify fill
        if order.status == 'filled':
            return Execution(
                signal_id=decision.signal.id,
                entry_price=order.avg_price,
                fill_time=order.timestamp,
                slippage=order.avg_price - decision.signal.entry_price,
                fees=order.fee,
                stop_loss_ticket=self.stop_loss_ticket
            )
```

**Execution Quality Tracking:**

```sql
CREATE TABLE execution_quality (
    id INTEGER PRIMARY KEY,
    signal_id TEXT,
    expected_price REAL,
    actual_price REAL,
    slippage REAL,
    slippage_pct REAL,
    fill_time_ms INTEGER,
    order_type TEXT,
    asset TEXT,
    timestamp DATETIME,
    
    -- Aggregate stats
    avg_slippage_by_asset TEXT,  -- computed periodically
    avg_slippage_by_hour TEXT    -- best/worst execution times
);
```

#### D. Reflection Engine — "The Philosopher"

**Job:** Post-trade analysis — extract lessons from EVERY trade. This is what makes it a super agent, not a bot.

```python
class ReflectionEngine:
    """
    Uses LLM to analyze completed trades and extract actionable lessons.
    This is where "intelligence that's good enough" + harness = frontier.
    """
    
    REFLECTION_PROMPT = """
    You are a trading analyst reviewing a completed trade.
    
    TRADE DETAILS:
    - Asset: {asset}
    - Direction: {direction}
    - Entry: {entry_price} at {entry_time}
    - Exit: {exit_price} at {exit_time}
    - P&L: {pnl_pct}%
    - Strategy: {strategy_name}
    - Signal confidence: {confidence}
    - Regime at entry: {regime}
    - Stop loss: {stop_loss}
    - Take profit: {take_profit}
    - Max favorable excursion: {max_favorable}%
    - Max adverse excursion: {max_adverse}%
    
    MARKET CONTEXT AT ENTRY:
    {indicators_snapshot}
    
    MARKET CONTEXT AT EXIT:
    {exit_indicators_snapshot}
    
    ANALYZE:
    1. Was the thesis correct? Why or why not?
    2. Was the timing right? Could entry/exit have been better?
    3. Was the position size appropriate for this setup?
    4. Was the stop loss correctly placed?
    5. What was the regime? Did the regime change during the trade?
    6. What ONE lesson can be extracted from this trade?
    7. What specific adjustment would improve this strategy?
    
    RESPOND IN JSON:
    {
        "thesis_correct": true/false,
        "analysis": "detailed analysis...",
        "timing_assessment": "early/late/optimal",
        "sizing_assessment": "too_big/just_right/too_small",
        "stop_assessment": "too_tight/optimal/too_wide",
        "regime_match": true/false,
        "lesson": "ONE actionable lesson",
        "lesson_confidence": 0.0-1.0,
        "strategy_adjustment": "specific parameter change or rule addition",
        "error_category": "timing/sizing/regime/execution/none"
    }
    """
    
    def reflect(self, trade: Trade) -> Reflection:
        # Use lightweight LLM for routine reflections
        # Use frontier model for losing trades and novel situations
        model = self._select_model(trade)
        
        reflection = llm.complete(
            model=model,
            prompt=self.REFLECTION_PROMPT.format(**trade.to_dict()),
            response_format="json"
        )
        
        # Store reflection
        self.db.update_trade_reflection(trade.id, reflection)
        
        # If lesson is high-confidence, add to lesson archive
        if reflection['lesson_confidence'] > 0.7:
            self.lesson_archive.add(reflection['lesson'], trade.id)
        
        # If strategy adjustment is actionable, queue for review
        if reflection['strategy_adjustment']:
            self.strategy_evolution.queue_proposal(
                strategy=trade.strategy_name,
                adjustment=reflection['strategy_adjustment'],
                evidence=trade.id
            )
        
        return reflection
```

### 3.3 Data Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DATA PIPELINE                               │
│                                                                  │
│  EXTERNAL SOURCES              PROCESSING            STORAGE     │
│  ┌──────────────┐             ┌──────────┐          ┌────────┐  │
│  │ Sina Finance  │────────────→│          │          │        │  │
│  │ (A-shares)    │             │  Data    │          │ SQLite │  │
│  └──────────────┘             │  Normal- │          │ (OHLCV)│  │
│  ┌──────────────┐             │  ization │          │        │  │
│  │ Eastmoney     │────────────→│  Engine  │────────→│ Redis  │  │
│  │ (Fund flows)  │             │          │          │(State) │  │
│  └──────────────┘             │  - Clean │          │        │  │
│  ┌──────────────┐             │  - Align │          │ Parquet│  │
│  │ AkShare       │────────────→│  - Fill  │          │(History│  │
│  │ (Multi-source)│             │  - Cache │          │        │  │
│  └──────────────┘             └──────────┘          └────────┘  │
│  ┌──────────────┐                  │                            │
│  │ Binance API   │────────────→    ↓                            │
│  │ (Crypto)      │           ┌──────────┐                      │
│  └──────────────┘            │Indicator │                      │
│  ┌──────────────┐            │ Engine   │                      │
│  │ CoinGecko     │──────────→│(TA-Lib)  │                      │
│  │ (Crypto meta) │           └──────────┘                      │
│  └──────────────┘                                              │
└─────────────────────────────────────────────────────────────────┘
```

**Data Refresh Schedule:**

| Data Type | Source | Frequency | Latency |
|---|---|---|---|
| A-share realtime | Sina API | Every 3s (trading hours) | ~3s |
| A-share daily | Eastmoney | 16:00 daily | EOD |
| Crypto tick | Binance WS | Real-time | <100ms |
| Crypto OHLCV | Binance REST | Every candle close | <1s |
| Fund flows | AkShare | Hourly | ~1h |
| Macro indicators | AkShare | Daily | ~1d |
| Technical indicators | TA-Lib (local) | Every data update | <10ms |

---

## Part IV: THE FLYWHEEL

### 4.1 The Trading Flywheel

```
     ┌─────────────────────────────────────────────────────┐
     │                                                     │
     │    ┌──────────┐                                     │
     │    │  TRADE   │ ← Execute strategy with conviction  │
     │    └────┬─────┘                                     │
     │         │                                           │
     │         ▼                                           │
     │    ┌──────────┐                                     │
     │    │ OBSERVE  │ ← Record outcome + market context   │
     │    └────┬─────┘                                     │
     │         │                                           │
     │         ▼                                           │
     │    ┌──────────┐                                     │
     │    │ REFLECT  │ ← LLM analyzes: why win/loss?       │
     │    └────┬─────┘                                     │
     │         │                                           │
     │         ▼                                           │
     │    ┌──────────┐                                     │
     │    │ EXTRACT  │ ← Distill into actionable lesson    │
     │    └────┬─────┘                                     │
     │         │                                           │
     │         ▼                                           │
     │    ┌──────────┐                                     │
     │    │  ADAPT   │ ← Adjust strategy genome            │
     │    └────┬─────┘                                     │
     │         │                                           │
     │         ▼                                           │
     │    ┌──────────┐                                     │
     │    │IMPROVED  │ ← Better signal, sizing, timing     │
     │    │  TRADE   │                                      │
     │    └──────────┘                                      │
     │                                                     │
     └─────────────────────────────────────────────────────┘
     
     COMPOUNDING EFFECT:
     
     Trade 1:    Basic strategy, generic sizing, no regime awareness
     Trade 100:  Strategy tuned to 2 regimes, lessons applied
     Trade 500:  5+ strategies active, regime detection calibrated
     Trade 1000: Pattern library has novel discoveries, strategy genome evolved 3+ times
     Trade 5000: Knowledge base is the moat — cannot be replicated
```

### 4.2 Flywheel Metrics (Track These)

| Metric | What It Measures | Target | How to Compute |
|---|---|---|---|
| `expectancy_trend` | Is avg PnL per trade improving? | Positive slope over 50-trade rolling window | Linear regression on trade PnL |
| `regime_accuracy` | How often regime detection matches reality? | >70% | Compare predicted vs actual regime transitions |
| `strategy_retirement_rate` | Are bad strategies killed promptly? | >80% retired within 30 losing trades | Count retired vs total strategies |
| `lesson_application_rate` | Are lessons actually changing behavior? | >60% | Lessons applied / lessons generated |
| `time_to_adapt` | How fast does system adjust to regime change? | <20 trades | Trades from regime change to strategy adjustment |
| `knowledge_density` | Useful knowledge per trade? | Increasing | Lessons + patterns / total trades |
| `sharpe_trend` | Risk-adjusted returns improving? | >1.5 over rolling 90 days | Rolling Sharpe calculation |
| `max_drawdown_recovery` | How fast does it recover from drawdowns? | <14 days | Days from drawdown low to new equity high |

### 4.3 The Flywheel in Practice

```
MONTH 1 ($10, paper trading):
├── 200-400 paper trades
├── First regime correlations visible
├── 3-5 basic strategies running
├── ~100 trade reflections completed
└── Key learning: "Which indicators actually predict in this market?"

MONTH 3 ($10-50, micro live):
├── 1000+ trades (paper + live)
├── Strategy performance by regime is statistically reliable
├── First strategy retirements (killing losers)
├── 500+ lessons extracted
└── Key learning: "What regime am I in, and what works in it?"

MONTH 6 ($50-200):
├── 3000+ trades
├── Pattern library has 5-10 discovered patterns
├── Strategy genomes evolved 2-3 times each
├── Regime detection accuracy >65%
└── Key learning: "The knowledge base is becoming the edge."

YEAR 1 ($200-1000):
├── 10,000+ trades
├── 5-8 active strategies, 3-5 retired
├── Sharpe ratio >1.2 on live trades
├── Knowledge base is proprietary and non-replicable
└── Key learning: "The flywheel is compounding."
```

---

## Part V: SPECIALIZED SUB-AGENTS

### 5.1 Sub-Agent Architecture

Not generic "research agent" or "analysis agent." These are **domain-specific trading sub-agents**, each with a single, well-defined job:

```
┌─────────────────────────────────────────────────────────────────┐
│                    SUB-AGENT ORCHESTRA                           │
│                                                                  │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────────────────┐  │
│  │   REGIME     │   │   SIGNAL    │   │   RISK GUARDIAN      │  │
│  │   DETECTOR   │──→│   SCOUT     │──→│   (VETO POWER)       │  │
│  │              │   │             │   │                      │  │
│  │ "What kind   │   │ "What       │   │ "Should we do this?" │  │
│  │  of market?" │   │  opportunities│  │                      │  │
│  └─────────────┘   │  exist?"     │   └──────────┬───────────┘  │
│                     └─────────────┘              │              │
│                                                   ▼              │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────────────────┐  │
│  │   TRADE      │   │  EXECUTION  │   │   EXECUTION          │  │
│  │   PHILOSOPHER│←──│  TRACKER    │←──│   SNIPER             │  │
│  │              │   │             │   │                      │  │
│  │ "What did    │   │ "What       │   │ "Get the best fill"  │  │
│  │  we learn?"  │   │  happened?" │   │                      │  │
│  └──────┬──────┘   └─────────────┘   └──────────────────────┘  │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────┐   ┌─────────────┐                              │
│  │  STRATEGY    │   │   MARKET    │                              │
│  │  GENETICIST  │   │ CARTOGRAPHER│                              │
│  │              │   │             │                              │
│  │ "How should  │   │ "What does  │                              │
│  │  we evolve?" │   │  the map    │                              │
│  │              │   │  look like?"│                              │
│  └─────────────┘   └─────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Sub-Agent Specifications

#### 5.2.1 Regime Detector — "What kind of market are we in?"

```yaml
name: regime_detector
job: "Classify current market regime with confidence level"
runs: Every candle close (or every 5 minutes for intraday)

inputs:
  - Price data (OHLCV) across multiple timeframes
  - Volatility calculations (ATR, Bollinger Band width)
  - Correlation matrix (cross-asset)
  - Volume profile

outputs:
  - regime_label: trending_up | trending_down | ranging | volatile | breakout
  - confidence: 0.0 - 1.0
  - expected_duration: estimated time in this regime
  - transition_probabilities: probability of moving to each other regime

methods:
  - Hidden Markov Model (statistical regime detection)
  - K-means clustering on volatility + trend strength
  - Rule-based overlays (ADX > 25 = trending, BB width expanding = volatile)
  
why_separate: |
  Regime detection is a distinct cognitive task that requires different
  "thinking" than signal generation. A signal scout looking for breakouts
  will be biased toward seeing breakout regimes. Separation prevents
  confirmation bias.
```

#### 5.2.2 Signal Scout — "What opportunities exist?"

```yaml
name: signal_scout
job: "Scan all assets/timeframes for strategy matches, score confidence"
runs: Continuously (streaming) or on schedule

inputs:
  - Market data + indicators for all configured assets
  - Current regime state (from Regime Detector)
  - Strategy genomes (which strategies are active in this regime)
  - Multi-timeframe alignment data

outputs:
  - List of raw signals, each with:
    - asset, direction, timeframe, strategy
    - confidence score (0.0 - 1.0)
    - entry/stop/target levels
    - rationale (human-readable)
    - falsification condition

methods:
  - Rule matching against strategy genome entry rules
  - Multi-timeframe confirmation scoring
  - Indicator confluence counting
  - Historical pattern matching

why_separate: |
  Signal generation should be exhaustive and unbiased. A dedicated agent
  scans everything without being distracted by portfolio concerns or
  recent trade outcomes. It's a pure pattern-matching machine.
```

#### 5.2.3 Risk Guardian — "Should we do this?"

```yaml
name: risk_guardian
job: "Evaluate every signal against risk rules. Has ABSOLUTE VETO power."
runs: On every signal (synchronous — blocks execution)

inputs:
  - Raw signal from Signal Scout
  - Current portfolio state
  - Correlation matrix
  - Drawdown history
  - Regime state

outputs:
  - APPROVED: signal + position_size + stop_loss + take_profit
  - REJECTED: signal + reason + which rule was violated

hard_rules:
  - max_single_trade_risk: 2% of capital
  - max_daily_drawdown: 3% of capital
  - max_portfolio_heat: 6% of capital
  - max_open_positions: 5
  - max_correlated_positions: 3
  - require_stop_loss: true
  
kelly_sizing: |
  Uses fractional Kelly Criterion (0.25x) based on strategy's
  historical performance in current regime.

why_separate: |
  Risk management MUST be independent. If the signal scout generates
  a signal, the risk guardian evaluates it without bias. The guardian
  cannot be "convinced" by a high-confidence signal to violate rules.
  This separation is a safety feature.
```

#### 5.2.4 Execution Sniper — "Get the best fill"

```yaml
name: execution_sniper
job: "Execute approved orders with minimal slippage"
runs: On every approved signal

inputs:
  - Risk-approved signal with sizing
  - Order book depth (Level 2 data)
  - Historical slippage data for this asset/time
  - Current spread and liquidity

outputs:
  - Filled order with execution quality metrics
  - Slippage measurement
  - Fill time

methods:
  - Market orders for small sizes (<$100)
  - Limit orders with smart pricing for larger sizes
  - TWAP for very large orders (future)
  - Stop-loss placed BEFORE entry (safety net)

execution_quality_tracking:
  - Slippage by asset
  - Slippage by time of day
  - Slippage by order size
  - Best/worst execution windows

why_separate: |
  Execution is a craft. Timing, order types, and slippage minimization
  require specialized focus. A separate agent can track execution
  quality patterns and optimize over time.
```

#### 5.2.5 Execution Tracker — "What happened?"

```yaml
name: execution_tracker
job: "Track open positions, manage stops, record outcomes"
runs: Continuously while positions are open

inputs:
  - Open positions with stops/targets
  - Real-time price data
  - Time limits from strategy

outputs:
  - Position updates (P&L, MFE, MAE)
  - Exit triggers (stop hit, target hit, trailing stop, time limit)
  - Trade completion records

actions:
  - Monitor stop-loss levels
  - Activate trailing stops when conditions met
  - Close positions at time limits
  - Record max favorable/adverse excursion
  - Trigger Reflection Engine on trade close
```

#### 5.2.6 Trade Philosopher — "What did we learn?"

```yaml
name: trade_philosopher
job: "Post-trade analysis — extract ONE actionable lesson per trade"
runs: After every trade closes

inputs:
  - Completed trade record
  - Market context at entry and exit
  - Strategy that generated the trade
  - Regime at entry and exit

outputs:
  - Trade reflection (analysis of what happened and why)
  - ONE actionable lesson (not 5, not 10 — ONE)
  - Strategy adjustment recommendation (if any)
  - Error categorization (if loss)

methods:
  - LLM-powered analysis (Tier 2 for wins, Tier 3 for losses)
  - Comparison with similar historical trades
  - Regime transition analysis
  - Excursion analysis (was the stop too tight? target too ambitious?)

why_separate: |
  Reflection requires a different "mindset" than signal generation.
  The philosopher must be brutally honest and cannot be biased by
  wanting to justify past decisions. Separation from the signal
  scout prevents post-hoc rationalization.
```

#### 5.2.7 Strategy Geneticist — "How should we evolve?"

```yaml
name: strategy_geneticist
job: "Evolve strategy genomes based on accumulated evidence"
runs: Weekly or after every 50 trades

inputs:
  - Strategy performance stats (by regime)
  - Trade reflections and lessons
  - Pattern library
  - Historical backtest results

outputs:
  - Strategy mutation proposals (parameter adjustments)
  - New strategy hypotheses (from pattern library)
  - Strategy retirement recommendations
  - A/B test designs (compare old vs new version)

evolution_process:
  1. COLLECT: Gather 30+ trades for strategy in specific regime
  2. ANALYZE: Calculate win rate, avg win, avg loss, expectancy
  3. HYPOTHESIZE: LLM proposes adjustments based on reflections
  4. BACKTEST: Test on historical data
  5. PAPER TRADE: Run mutation in parallel (1 week)
  6. COMPARE: Statistical significance test
  7. ADOPT/REJECT: Update genome if improvement is significant
  8. DOCUMENT: Record what changed, why, evidence

why_separate: |
  Strategy evolution is a slow, deliberate process. It should NOT
  happen in real-time. A separate agent with its own cadence
  (weekly/monthly) prevents over-optimization and ensures changes
  are evidence-based.
```

#### 5.2.8 Market Cartographer — "What does the map look like?"

```yaml
name: market_cartographer
job: "Map market structure — support/resistance, liquidity, key levels"
runs: Daily + on significant price moves

inputs:
  - Historical price data
  - Volume profile
  - Order book depth
  - Key psychological levels

outputs:
  - Support/resistance levels (with strength scores)
  - Liquidity zones (where stops cluster)
  - Key price levels (round numbers, previous highs/lows)
  - Market structure narrative

methods:
  - Volume-at-price analysis
  - Pivot point calculations
  - Fibonacci retracements
  - Historical level detection
  - Order book imbalance analysis

why_separate: |
  Market structure understanding is foundational context that ALL
  other agents need. A dedicated cartographer provides this context
  as a service, rather than each agent computing it independently.
```

### 5.3 Inter-Agent Communication Protocol

```python
# Message format between agents
@dataclass
class AgentMessage:
    from_agent: str
    to_agent: str
    message_type: str    # 'signal' | 'risk_decision' | 'execution' | 'reflection' | 'update'
    payload: dict
    timestamp: datetime
    priority: str        # 'normal' | 'high' | 'critical'
    requires_response: bool
```

**Communication Flow — One Complete Trade:**

```
1. Market Cartographer → broadcast
   "BTC at major resistance $68,500. Volume declining. Key support at $66,200."

2. Regime Detector → broadcast
   "Current regime: ranging (72% confidence). Volatility contracting."

3. Signal Scout → Risk Guardian
   "Found: BTC momentum breakout signal. Confidence: 0.68.
    Entry: $68,550. Stop: $67,800. Target: $70,000.
    Falsification: Wrong if price closes below $68,000 within 4 hours."

4. Risk Guardian → Signal Scout (REJECTION)
   "REJECTED: Strategy 'momentum_breakout' is DISABLED in 'ranging' regime.
    Per genome v3.1.0, this strategy has -0.15 expectancy in ranging markets."

5. (No trade executed. System correctly avoided a bad setup.)

--- vs. ---

3'. Signal Scout → Risk Guardian
    "Found: BTC mean_reversion signal at support. Confidence: 0.74.
     Entry: $66,250. Stop: $65,500. Target: $68,000.
     Falsification: Wrong if price breaks below $65,500."

4'. Risk Guardian → Execution Sniper
    "APPROVED: Position size $0.50 (1.5% of $33 portfolio).
     Stop: $65,500. Target: $68,000. RR: 2.3:1."

5'. Execution Sniper → Execution Tracker
    "FILLED: $66,260. Slippage: +$10 (0.015%). Good fill."

6'. Execution Tracker monitors... price reaches $68,000...
    "TARGET HIT: Exit at $68,000. PnL: +$13.10 (+2.6%)."

7'. Trade Philosopher
    "Reflection: Mean reversion at support worked well in ranging regime.
     Lesson: Volume confirmation at support increased win rate from 52% to 67%.
     Suggestion: Add volume filter to mean_reversion entry rules."

8'. Strategy Geneticist (weekly review)
    "Proposal: Add volume > 1.2x average filter to mean_reversion strategy.
     Evidence: 12 trades with volume confirmation, 8 wins (67%) vs
     23 trades without, 12 wins (52%). Statistically significant (p<0.05)."
```

---

## Part VI: INTELLIGENCE THRESHOLD

### 6.1 When to Use What

Not every task needs a frontier model. Most trading decisions are **structured and rule-based.**

```
┌─────────────────────────────────────────────────────────────────┐
│              INTELLIGENCE TIER SYSTEM                            │
│                                                                  │
│  TIER 0 — PURE MATH (No AI, near-zero cost)                    │
│  ├── Position sizing (Kelly Criterion)                           │
│  ├── Stop-loss / take-profit calculations                        │
│  ├── PnL tracking and statistics                                 │
│  ├── Correlation calculations                                    │
│  ├── Moving averages, RSI, MACD (standard indicators)           │
│  └── Cost: ~$0 (runs locally on numpy/pandas)                   │
│                                                                  │
│  TIER 1 — STATISTICAL ML (Classical, low cost)                  │
│  ├── Regime classification (Hidden Markov Models)                │
│  ├── Volatility forecasting (GARCH)                              │
│  ├── Anomaly detection (Isolation Forests)                       │
│  ├── Clustering (K-means for pattern grouping)                   │
│  └── Cost: ~$0 (runs locally on scikit-learn)                   │
│                                                                  │
│  TIER 2 — LIGHTWEIGHT LLM (Local or cheap API)                  │
│  ├── Signal narrative generation                                 │
│  ├── Market commentary                                           │
│  ├── Simple trade reflections (winners)                          │
│  ├── Pattern descriptions                                        │
│  └── Cost: ~$0.01-0.05 per call (GPT-4o-mini / Haiku)          │
│                                                                  │
│  TIER 3 — FRONTIER LLM (Expensive, used sparingly)              │
│  ├── Deep trade reflection (losers, novel situations)            │
│  ├── Strategy genome evolution proposals                         │
│  ├── Cross-strategy insight extraction                           │
│  ├── Novel pattern hypothesis generation                         │
│  └── Cost: ~$0.10-0.50 per call (GPT-4o / Sonnet)              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Model Selection Logic

```python
def select_intelligence_tier(task_type: str, trade: Trade = None) -> str:
    """
    Route tasks to appropriate intelligence tier.
    Goal: Minimize cost while maintaining quality.
    """
    
    if task_type in ['indicator_calc', 'position_sizing', 'pnl', 'correlation']:
        return 'tier_0'  # Pure math
    
    elif task_type in ['regime_detection', 'volatility_forecast', 'anomaly']:
        return 'tier_1'  # Statistical ML
    
    elif task_type == 'trade_reflection':
        if trade and trade.pnl_percent > 0:
            return 'tier_2'  # Winners: lightweight analysis
        elif trade and trade.pnl_percent < -1.0:
            return 'tier_3'  # Big losers: deep analysis
        else:
            return 'tier_2'  # Small losers: standard analysis
    
    elif task_type == 'strategy_evolution':
        return 'tier_3'  # Always frontier for evolution
    
    elif task_type in ['signal_narrative', 'commentary']:
        return 'tier_2'  # Lightweight LLM
    
    else:
        return 'tier_2'  # Default to lightweight
```

### 6.3 Cost Optimization for $10 Capital

```
Daily Operations:
  Tier 0 + Tier 1:     ~$0.00 (local computation)
  5-10 Tier 2 calls:   ~$0.05-0.10/day
  0-1 Tier 3 calls:    ~$0.00-0.10/day
  
  Daily total:          ~$0.05-0.20/day

Monthly Budget:
  Daily operations:     ~$1.50-6.00/month
  Weekly evolution:     ~$0.40-2.00/month
  Monthly deep review:  ~$0.50-2.00/month
  
  Monthly total:        ~$2.40-10.00/month

With $10 capital, keep LLM costs under $3/month.
That's achievable with Tier 2 for 90% of tasks.
```

---

## Part VII: POST-TRAINING — Strategy Refinement

### 7.1 What "Post-Training" Means for Trading

In the Jensen Huang framework, "post-training the model inside the harness against the harness" means:

> **The agent doesn't just use strategies — it trains itself to be better at USING strategies.**

| AI Concept | Trading Equivalent |
|---|---|
| Fine-tuning | Adjusting strategy parameters based on live results |
| RLHF | Human reviewing and approving strategy mutations |
| Reward model | Expectancy + Sharpe as the reward signal |
| Curriculum learning | Start simple, add complexity as data grows |
| Self-play | Paper trading new strategy variants against each other |
| Distillation | Extracting general principles from specific trade outcomes |

### 7.2 The Strategy Mutation Pipeline

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   COLLECT    │    │   ANALYZE    │    │ HYPOTHESIZE  │
│              │    │              │    │              │
│ 30+ trades   │──→│ Stats by     │──→│ LLM proposes │
│ in regime    │    │ regime       │    │ adjustment   │
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
                                               ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   ADOPT /    │    │   COMPARE    │    │  BACKTEST    │
│   REJECT     │    │              │    │              │
│              │←──│ New vs old   │←──│ Test on      │
│ Update genome│    │ (p<0.05?)    │    │ historical   │
│ if better    │    │              │    │ data         │
└──────┬───────┘    └──────────────┘    └──────────────┘
       │
       ▼
┌──────────────┐
│  DOCUMENT    │
│              │
│ Record what  │
│ changed, why,│
│ and evidence │
└──────────────┘
```

### 7.3 The "Harness Against Harness" Principle

The harness itself is optimized — not just the strategies:

```
COMPONENT OPTIMIZATION:

Risk Engine:
├── Is 2% risk per trade optimal? Test 1%, 1.5%, 2%, 3%
├── Which produces best risk-adjusted returns?
├── Does optimal risk vary by regime?
└── Result: Calibrated risk parameters per regime

Execution Engine:
├── Which order types produce least slippage?
├── What are the best execution windows?
├── Does slippage vary by asset? By time of day?
└── Result: Optimized execution strategy per asset

Reflection Engine:
├── Which reflection prompts produce most actionable lessons?
├── Are lessons actually being applied?
├── What reflection depth produces best strategy adjustments?
└── Result: Optimized reflection prompts

Regime Detector:
├── Which indicators are most predictive of regime changes?
├── What lookback periods work best?
├── How far ahead can we predict regime transitions?
└── Result: Calibrated regime detection model
```

---

## Part VIII: OPEN CONTROL — Autonomy with Guardrails

### 8.1 Control Hierarchy

```
LEVEL 0 — HARD STOPS (NEVER OVERRIDE — encoded in code)
│
├── Maximum daily drawdown: 3%
├── Maximum single trade risk: 2%
├── Stop-loss mandatory on every trade
├── No trading in untested strategies
├── No trading without risk engine approval
├── No withdrawal permissions for API keys
└── Manual kill switch always available
│
LEVEL 1 — SOFT LIMITS (Override with justification + human approval)
│
├── Strategy allocation weights
├── Regime transition thresholds
├── Signal confidence minimums
├── Time-of-day restrictions
└── Asset universe expansion
│
LEVEL 2 — AUTONOMOUS (Agent decides, logs everything)
│
├── Which signals to generate
├── Execution timing within approved window
├── Trade reflection analysis
├── Pattern discovery
└── Routine data collection
│
LEVEL 3 — HUMAN APPROVAL REQUIRED
│
├── Strategy mutations (propose → human approves)
├── New strategy creation
├── Capital allocation changes
├── Risk parameter modifications
└── API key changes
```

### 8.2 Configuration Files (Human-Owned)

```yaml
# config/risk_limits.yaml — YOU edit this, the agent CANNOT
hard_limits:
  max_daily_drawdown_pct: 3.0
  max_single_trade_risk_pct: 2.0
  max_portfolio_heat_pct: 6.0
  max_open_positions: 5
  require_stop_loss: true
  
  allowed_assets:
    - BTC/USDT
    - ETH/USDT
  
  allowed_timeframes:
    - 15m
    - 1h
    - 4h
    - 1d
  
  # Capital limits
  max_total_capital: 10.0  # Start with $10
  
# config/agent_permissions.yaml — what the agent CAN do
autonomous_actions:
  - generate_signals
  - execute_approved_trades
  - write_trade_reflections
  - collect_market_data
  - calculate_indicators
  - detect_regime
  - discover_patterns

requires_approval:
  - adopt_strategy_mutation
  - add_new_strategy
  - retire_strategy
  - change_risk_parameters
  - expand_asset_universe
  - increase_position_limits

# config/notifications.yaml — when to alert you
alerts:
  - event: trade_executed
    channel: telegram
    priority: normal
  
  - event: daily_drawdown_exceeded
    channel: telegram
    priority: urgent
  
  - event: strategy_mutation_proposed
    channel: telegram
    priority: normal
  
  - event: regime_changed
    channel: telegram
    priority: low
  
  - event: position_stop_hit
    channel: telegram
    priority: high
```

### 8.3 Daily Human Touchpoints

```
MORNING (5 min):
├── Review overnight trades
├── Check current regime
└── Glance at P&L

MIDDAY (2 min):
├── Check for alerts
└── Review any open positions

EVENING (10 min):
├── Read trade reflections
├── Approve/reject strategy mutations
└── Note any observations

WEEKLY (30 min):
├── Deep strategy performance review
├── Read pattern library updates
├── Approve pending mutations
└── Adjust risk parameters if needed

MONTHLY (1 hour):
├── Full system performance review
├── Evaluate flywheel metrics
├── Plan next month's improvements
└── Decide on capital allocation
```

---

## Part IX: RUNTIME / SECURITY / SANDBOXING

### 9.1 What Trading Needs (and ONLY What Trading Needs)

```
┌─────────────────────────────────────────────────────────────┐
│                  RUNTIME REQUIREMENTS                        │
│                                                              │
│  DATA ACCESS                                                │
│  ├── Exchange APIs (read market data) — READ-ONLY key       │
│  ├── Exchange APIs (execute trades) — TRADING key (no withdraw) │
│  ├── AkShare (A-share data) — no key needed                 │
│  └── On-chain data (optional) — public APIs                 │
│                                                              │
│  COMPUTATION                                                │
│  ├── Python 3.11+ with pandas, numpy, scikit-learn          │
│  ├── TA-Lib (technical indicators)                          │
│  ├── SQLite (trade memory, <100MB/year)                     │
│  ├── Redis (regime state, fast cache)                       │
│  └── LLM API (reflection engine)                            │
│                                                              │
│  STORAGE                                                    │
│  ├── Trade database (SQLite)                                │
│  ├── Strategy genomes (YAML, version controlled)            │
│  ├── Pattern library (YAML)                                 │
│  ├── Lesson archive (Markdown)                              │
│  ├── Logs (JSON, rotate weekly)                             │
│  └── Backups (daily, encrypted)                             │
│                                                              │
│  NETWORK                                                    │
│  ├── Exchange WebSocket (market data stream)                │
│  ├── Exchange REST API (order management)                   │
│  ├── LLM API (reflection engine)                            │
│  └── Notification channel (Telegram)                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 Security Architecture

```
API KEY MANAGEMENT:
├── Market data key: READ-ONLY, IP whitelisted
├── Trading key: TRADE-ONLY (no withdrawal), IP whitelisted
├── Daily loss limit on trading key: $5 (50% of $10 capital)
├── Keys stored in encrypted vault (NOT in code or config files)
└── Key rotation: every 90 days

NETWORK SECURITY:
├── All API calls over HTTPS only
├── WebSocket connections authenticated
├── No inbound connections (agent initiates all)
└── DNS-over-HTTPS for privacy

DATA SECURITY:
├── Trade database encrypted at rest
├── Backups encrypted with separate key
├── Logs scrubbed of sensitive data (no API keys in logs)
└── Strategy genomes in private git repository

OPERATIONAL SECURITY:
├── Agent runs as non-root user
├── Process isolation (Docker container)
├── Resource limits (CPU, memory, network)
├── Automated health checks every 5 minutes
└── Dead man's switch: alert if no heartbeat for 30 minutes
```

### 9.3 The Kill Switch

```bash
# Emergency stop — kills ALL trading activity immediately
./agent kill --reason "manual_override"
# Effect: Cancels all pending orders, keeps existing positions with stops

# Graceful stop — close all positions, then stop
./agent stop --close-positions --reason "end_of_day"
# Effect: Closes all positions at market, then shuts down

# Pause — stop new trades, keep existing
./agent pause --reason "reviewing_strategy"
# Effect: No new signals processed, existing positions managed normally

# Resume
./agent start --mode=paper   # Paper trading
./agent start --mode=live    # Live trading
```

### 9.4 Sandboxing Rules

```
1. NEVER store API keys in source code or config files
2. NEVER allow the agent to modify its own risk limits
3. NEVER allow the agent to whitelist new withdrawal addresses
4. NEVER run the agent with withdrawal permissions
5. ALWAYS use paper trading before live deployment
6. ALWAYS have a manual kill switch
7. ALWAYS log every decision with full context
8. NEVER let the agent access the internet except for approved APIs
9. NEVER let the agent install packages without human approval
10. ALWAYS backup the knowledge base daily
```

---

## Part X: WHAT MAKES THIS DIFFERENT FROM A TRADING BOT

### 10.1 The Fundamental Difference

| Dimension | Trading Bot | Trading Super Agent |
|---|---|---|
| **Intelligence** | Static rules written by human | Evolving rules refined by evidence |
| **Memory** | None (or basic trade log) | Rich: trades + reflections + lessons + patterns |
| **Adaptation** | Manual parameter tweaking | Autonomous strategy evolution |
| **Regime Awareness** | None or basic | Deep: regime-specific strategy selection |
| **Self-Improvement** | None | Continuous: every trade makes it better |
| **Risk Management** | Fixed rules | Adaptive: calibrated to current conditions |
| **Knowledge** | In the human's head | In the system's memory (proprietary) |
| **Failure Mode** | Breaks when market changes | Adapts to market changes |
| **Scalability** | More capital = same performance | More capital = better performance (more data) |
| **Value** | The code | The knowledge |

### 10.2 The Core Insight

> A trading bot is a **static program** that follows rules written by a human. A Trading Super Agent is a **living system** that accumulates proprietary market knowledge, encodes that knowledge into evolving strategies, and gets measurably better at its one job — autonomous capital compounding — with every trade it makes.

**You can copy a bot's code. You cannot copy a super agent's knowledge.**

### 10.3 The Jensen Huang Test

Does this system pass the Jensen Huang criteria?

```
✅ "Super agent is domain-specific. Built for ONE job."
   → One job: autonomous capital compounding under risk constraints.

✅ "Intelligence that's good enough + harness around it = frontier capabilities"
   → Tier 0-2 intelligence for 90% of tasks, wrapped in trading harness.

✅ "Proprietary knowledge, proprietary skills"
   → Trade memory, strategy genomes, pattern library — all proprietary.

✅ "Flywheel: use it → smarter → more useful → use it even more"
   → Every trade improves the system. Measurable compounding.

✅ "Companies will be built on harnesses, not business processes"
   → The harness IS the product. Strategies evolve, harness persists.

✅ "Post-training the model inside the harness against the harness"
   → Strategy mutation pipeline. Harness components self-optimize.

✅ "Super sub-agents connected to specialized tools"
   → 8 domain-specific sub-agents, each with specialized tools.

✅ "Open harness — you need to control it, improve it, refine it"
   → 4-level control hierarchy. Human approves mutations. Full transparency.
```

---

## Part XI: IMPLEMENTATION ROADMAP

### Phase 1: Foundation (Weeks 1-4) — Paper Trading

```
[ ] Set up project structure (Python, SQLite, YAML configs)
[ ] Build data pipeline (AkShare + Binance, normalize, store)
[ ] Implement 3 simple strategies (MA crossover, RSI reversal, breakout)
[ ] Build Risk Engine with hard limits
[ ] Build Execution Engine (paper trading mode)
[ ] Set up trade memory database
[ ] Deploy and let it paper trade for 2 weeks
[ ] Cost: $0
```

### Phase 2: Reflection (Weeks 5-8) — First Intelligence

```
[ ] Build Reflection Engine (LLM-powered trade analysis)
[ ] Implement Regime Detector (start with volatility + ADX)
[ ] Add strategy genome files (YAML format)
[ ] Build Trade Philosopher sub-agent
[ ] Implement lesson extraction and storage
[ ] Review first 50 paper trades — what did we learn?
[ ] Cost: ~$5/month for LLM API
```

### Phase 3: Evolution (Weeks 9-12) — The Flywheel Starts

```
[ ] Build Strategy Geneticist sub-agent
[ ] Implement strategy mutation pipeline
[ ] Add regime-aware strategy selection
[ ] Build Market Cartographer sub-agent
[ ] Optimize LLM usage (tier system)
[ ] Paper trade with evolved strategies
[ ] Cost: ~$10/month
```

### Phase 4: Live Trading (Weeks 13+) — Real Money

```
[ ] Switch to live trading with MINIMUM position sizes ($1-2)
[ ] Build Execution Sniper sub-agent
[ ] Add real-time regime detection
[ ] Build monitoring dashboard (Streamlit)
[ ] Weekly strategy review cadence
[ ] Scale capital ONLY as strategy proves itself
[ ] Cost: ~$10-15/month
```

### Phase 5: Scale (Month 6+) — Compound

```
[ ] Add more assets (expand allowed_assets)
[ ] Add more timeframes
[ ] Implement cross-asset correlation strategies
[ ] Build automated backtesting framework
[ ] Add more capital based on proven track record
[ ] Consider building a web dashboard
[ ] Cost: ~$15-25/month
```

---

## Part XII: TECH STACK

```yaml
core:
  language: Python 3.11+
  package_manager: uv
  
data:
  a_shares: AkShare (free, no API key)
  crypto: CCXT (unified exchange API)
  storage: SQLite (trades) + Redis (state) + Parquet (history)
  
indicators:
  library: ta (pandas-ta) or TA-Lib
  custom: numpy/pandas for proprietary indicators
  
ml_classical:
  regime_detection: hmmlearn (Hidden Markov Models)
  clustering: scikit-learn (K-means)
  volatility: arch (GARCH models)
  anomaly: scikit-learn (Isolation Forest)
  
llm:
  tier2: GPT-4o-mini / Claude Haiku (~$0.01/call)
  tier3: GPT-4o / Claude Sonnet (~$0.10/call)
  
infrastructure:
  scheduler: APScheduler
  cache: Redis
  messaging: python-telegram-bot
  config: YAML + Pydantic
  logging: Python logging → JSON files
  
monitoring:
  dashboard: Streamlit (free, local)
  alerting: Telegram bot
  
deployment:
  local: Docker Compose
  cloud: Railway / Fly.io ($5/month when ready)
  
version_control:
  code: Git (private repository)
  strategies: Git (version tracked)
  knowledge: Git (daily backup)
```

---

## Part XIII: FIRST PRINCIPLES

1. **Start stupid, get smart.** Your first strategies should be embarrassingly simple. Complexity is earned through data.

2. **Every trade is a lesson.** If the reflection engine isn't running, you're building a bot, not a super agent.

3. **Risk management is non-negotiable.** The risk engine has veto power. Always. No exceptions.

4. **The knowledge base IS the product.** Code can be copied. Your trade memory, strategy genomes, and pattern library cannot.

5. **Measure everything.** If you can't measure it, you can't improve it. If you can't improve it, it's not a super agent.

6. **The flywheel is the moat.** Every trade makes the next trade better. This compounds.

7. **Human in the loop, not human on the loop.** The agent proposes, you approve. Over time, trust builds.

8. **Open harness, not black box.** Every decision, every rationale, every lesson must be readable.

9. **$10 is tuition, not investment capital.** The real investment is your time and the knowledge the system accumulates.

10. **The code is free. The knowledge is priceless.** Build accordingly.

---

## Appendix: What "Good" Looks Like

### After 6 Months

```
Trade memory:        3,000+ trades analyzed
Strategy genome:     5-8 active strategies, 3-5 retired (killed by evidence)
Regime accuracy:     70%+ (up from ~50% random)
Expectancy:          Positive (even if small)
Lessons learned:     500+ documented insights
Pattern library:     5-10 discovered patterns
System uptime:       99%+ (automated, reliable)
Sharpe ratio:        >1.0 on live trades
Max drawdown:        <10% (risk engine doing its job)
Your knowledge:      You understand market microstructure better than 95% of retail traders
```

### The Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│           TRADING SUPER AGENT — LIVE DASHBOARD                  │
├─────────────────────────────────────────────────────────────────┤
│ Portfolio Value:    $XX.XX  (+X.X% today)                       │
│ Current Regime:     Trending Up (82% conf)                      │
│ Open Positions:     2/5                                         │
│ Daily P&L:          +$X.XX                                      │
│ Weekly P&L:         +$X.XX                                      │
│ Drawdown Today:     0.X% / 3.0% max                            │
├─────────────────────────────────────────────────────────────────┤
│ STRATEGY PERFORMANCE (last 30 days)                             │
│ momentum_breakout:  WR 61% | Exp +0.42 | N=47                  │
│ mean_reversion:     WR 54% | Exp +0.18 | N=33                  │
│ volume_spike_fade:  WR 48% | Exp -0.05 | N=21 ⚠️               │
├─────────────────────────────────────────────────────────────────┤
│ FLYWHEEL HEALTH                                                 │
│ Expectancy trend:   ↗ Improving                                 │
│ Lessons applied:    12/18 (67%)                                 │
│ Strategies retired: 3 this month                                │
│ Knowledge density:  0.8 lessons/trade (target: 1.0)             │
├─────────────────────────────────────────────────────────────────┤
│ PENDING ACTIONS (require your approval)                         │
│ [ ] Review strategy mutation: breakout_v3.3.0                   │
│ [ ] Approve new strategy: order_flow_divergence                 │
│ [ ] Review 3 trade reflections from today                       │
└─────────────────────────────────────────────────────────────────┘
```

---

*"The companies of the future will be built on harnesses, not business processes."*

**Your Trading Super Agent is a harness for market intelligence.**
**The code is free. The knowledge it builds is priceless.**

---

**Version:** 2.0
**Last Updated:** 2026-07-24
**License:** Build it. Own it. Improve it. Never sell the knowledge.
