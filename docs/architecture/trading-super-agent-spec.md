# Trading Super Agent — Complete Sub-Agent Specification

**Version:** 1.0.0
**Date:** 2026-07-24
**Architecture:** Python 3.12 Orchestration · Rust Execution · PyO3 Bridge
**Classification:** Institutional-Grade Autonomous Trading System

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Communication Layer](#2-communication-layer)
3. [Agent Specifications](#3-agent-specifications)
   - 3.1 [Regime Detector](#31-regime-detector)
   - 3.2 [Signal Scout](#32-signal-scout)
   - 3.3 [Risk Guardian](#33-risk-guardian)
   - 3.4 [Execution Sniper](#34-execution-sniper)
   - 3.5 [Execution Tracker](#35-execution-tracker)
   - 3.6 [Trade Philosopher](#36-trade-philosopher)
   - 3.7 [Strategy Geneticist](#37-strategy-geneticist)
   - 3.8 [Market Cartographer](#38-market-cartographer)
4. [Model Routing Strategy](#4-model-routing-strategy)
5. [Risk Guardian VETO Protocol](#5-risk-guardian-veto-protocol)
6. [Error Handling & Graceful Degradation](#6-error-handling--graceful-degradation)
7. [Testing Strategy](#7-testing-strategy)
8. [Performance Budgets](#8-performance-budgets)
9. [PyO3 Bridge Interface](#9-pyo3-bridge-interface)
10. [Deployment Topology](#10-deployment-topology)

---

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PYTHON ORCHESTRATION LAYER                       │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │ Regime       │  │ Signal       │  │ Strategy     │                  │
│  │ Detector     │──│ Scout        │──│ Geneticist   │                  │
│  │ (T2/T3)      │  │ (T1/T2)      │  │ (T3)         │                  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘                  │
│         │                 │                                             │
│         ▼                 ▼                                             │
│  ┌─────────────────────────────────────────────┐                       │
│  │            RISK GUARDIAN (T0/T1)             │  ◄── VETO POWER      │
│  │              [GATEKEEPER NODE]               │                       │
│  └──────────────────────┬──────────────────────┘                       │
│                         │ APPROVE / VETO                                │
│                         ▼                                               │
│  ┌──────────────┐  ┌──────────────┐                                    │
│  │ Execution    │  │ Execution    │                                    │
│  │ Sniper       │──│ Tracker      │                                    │
│  │ (T0 Rust)    │  │ (T0 Rust)    │                                    │
│  └──────────────┘  └──────────────┘                                    │
│         │                 │                                             │
│         ▼                 ▼                                             │
│  ┌──────────────┐  ┌──────────────┐                                    │
│  │ Trade        │  │ Market       │                                    │
│  │ Philosopher  │  │ Cartographer │                                    │
│  │ (T2/T3)      │  │ (T1/T2)      │                                    │
│  └──────────────┘  └──────────────┘                                    │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  REDIS STREAMS EVENT BUS                                                │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ streams: regime | signals | risk | orders | fills | analytics  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│  RUST EXECUTION LAYER (via PyO3)                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │
│  │ Order Router  │  │ Market Data  │  │ Position     │                 │
│  │ Engine        │  │ Normalizer   │  │ Calculator   │                 │
│  └──────────────┘  └──────────────┘  └──────────────┘                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### Core Principles

| Principle | Enforcement |
|-----------|-------------|
| **No trade without Risk Guardian approval** | Hard gate — orders rejected at bus level if missing `risk_approved: true` |
| **Every agent is independently killable** | Each runs in its own process/container with health checks |
| **Rust for anything touching money or latency** | Order sizing, execution, P&L calculation — all Rust |
| **LLMs only for reasoning, never for math** | Model output is always post-validated by Tier 0/1 code |
| **Free-tier models first** | Frontier models only when free-tier cannot handle the task |

---

## 2. Communication Layer

### 2.1 Event Bus: Redis Streams

**Why Redis Streams over NATS:**
- Redis is already required for caching market data state
- Consumer groups provide exactly-once processing semantics
- `XADD`/`XREADGROUP` with ACK gives reliable delivery
- Sub-millisecond local latency
- Built-in persistence with AOF

### 2.2 Stream Topology

```
Stream Name                Producers              Consumers
─────────────────────────────────────────────────────────────────
trading:regime             Regime Detector         Signal Scout, Risk Guardian,
                                                   Strategy Geneticist,
                                                   Market Cartographer

trading:signals            Signal Scout            Risk Guardian, Strategy
                                                   Geneticist

trading:risk_decisions     Risk Guardian           Execution Sniper, Trade
                                                   Philosopher

trading:orders             Execution Sniper        Execution Tracker

trading:fills              Execution Tracker       Trade Philosopher,
                                                   Risk Guardian,
                                                   Market Cartographer

trading:positions          Execution Tracker       Risk Guardian,
                                                   Trade Philosopher,
                                                   Strategy Geneticist

trading:analytics          Trade Philosopher       Strategy Geneticist,
                                                   Regime Detector

trading:cartography        Market Cartographer     Regime Detector,
                                                   Signal Scout, Risk Guardian

trading:strategy_mutations Strategy Geneticist     Signal Scout

trading:health             ALL agents              Orchestrator (supervisor)
```

### 2.3 Message Envelope Format

Every message on the bus uses this envelope:

```python
@dataclass(frozen=True)
class MessageEnvelope:
    """Canonical message wrapper for all inter-agent communication."""
    msg_id: str              # ULID (time-sortable, globally unique)
    timestamp_ns: int        # Nanosecond epoch — monotonic
    source_agent: str        # e.g. "regime_detector"
    msg_type: str            # e.g. "regime_change", "signal", "veto"
    version: int             # Schema version for forward compatibility
    payload: dict            # Agent-specific payload
    trace_id: str            # For distributed tracing across agent chain
    priority: int            # 0=critical, 1=high, 2=normal, 3=low
```

**Serialized format:** MessagePack (not JSON) — 30-50% smaller, 5x faster parse.
**Fallback:** JSON for debugging via `redis-cli`.

### 2.4 Synchronous vs Async Patterns

| Pattern | Usage | Example |
|---------|-------|---------|
| **Async (default)** | Most inter-agent communication | Regime → Signal Scout: "regime changed, adapt" |
| **Sync with timeout** | Risk Guardian veto check | Sniper → Risk Guardian: "approve this order?" (50ms timeout) |
| **Fire-and-forget** | Health heartbeats, telemetry | All agents → `trading:health` every 5s |
| **Request-reply** | One-off queries | Philosopher → Cartographer: "what was SPY-ES correlation at T-1?" |

**Sync pattern implementation (Risk Guardian veto):**

```python
# In Execution Sniper (Python side)
async def request_risk_approval(order: Order, timeout_ms: int = 50) -> RiskDecision:
    """Synchronous call to Risk Guardian via Redis Streams with timeout."""
    reply_channel = f"trading:risk_reply:{uuid4().hex}"

    await redis.xadd("trading:risk_requests", {
        "order": msgpack.packb(order.to_dict()),
        "reply_to": reply_channel,
        "timeout_ms": timeout_ms,
    })

    # Block-wait on dedicated reply stream
    result = await redis.xread(
        {reply_channel: "0"},
        count=1,
        block=timeout_ms,
    )

    if not result:
        return RiskDecision.approved_with_warning(
            "Risk Guardian timeout — default APPROVE with reduced size"
        )

    return RiskDecision.from_msgpack(result[0][1][0][1])
```

### 2.5 Shared State Without Blocking

Agents never share memory. Instead, they use:

1. **Redis Hashes** for fast-read shared state:
   ```
   trading:state:positions    — current open positions (Execution Tracker writes)
   trading:state:regime       — current regime classification (Regime Detector writes)
   trading:state:portfolio    — portfolio-level metrics (Execution Tracker writes)
   ```

2. **Optimistic concurrency** via Redis `WATCH`/`MULTI`/`EXEC` for writes
3. **Read replicas** — any agent can read any state hash without coordination
4. **State change notifications** — writes to state hashes ALSO publish to corresponding streams

---

## 3. Agent Specifications

---

### 3.1 Regime Detector

> *"What kind of market are we in?"*

#### Role & Responsibility

Classifies the current market regime across multiple dimensions. This is the **first agent in the pipeline** — every other agent's behavior adapts based on regime classification. The Regime Detector does NOT predict future regimes; it characterizes the present.

#### Regime Dimensions

| Dimension | Possible Values | Detection Method |
|-----------|----------------|------------------|
| **Volatility** | `compressed`, `normal`, `elevated`, `extreme` | Realized vol percentile vs 252-day distribution |
| **Trend** | `strong_up`, `weak_up`, `range`, `weak_down`, `strong_down` | ADX + slope of 50/200 EMA alignment |
| **Correlation** | `decoupled`, `normal`, `correlated`, `crisis` | Avg cross-asset rolling correlation |
| **Liquidity** | `deep`, `normal`, `thin`, `stressed` | Bid-ask spread percentile + volume vs 20-day avg |
| **Microstructure** | `trending`, `mean_revert`, `choppy`, `breakout` | Hurst exponent + variance ratio test |

#### Input Data

| Source | Data | Refresh Rate |
|--------|------|-------------|
| Market data feed | OHLCV for 50+ instruments | 1s (via Rust normalizer) |
| Volatility surface | VIX term structure, realized vol by timeframe | 1min |
| Order book | Top-5 depth, trade flow | 100ms |
| Cross-asset | DXY, US10Y, SPX, Gold, BTC, Crude | 5s |
| Calendar | Economic events, FOMC, OPEX | Daily static |

#### Output Format

```python
@dataclass(frozen=True)
class RegimeReport:
    """Published to trading:regime stream."""
    timestamp: datetime
    regime_id: str                           # ULID
    volatility: str                          # "compressed" | "normal" | "elevated" | "extreme"
    trend: str                               # "strong_up" | "weak_up" | "range" | "weak_down" | "strong_down"
    correlation: str                         # "decoupled" | "normal" | "correlated" | "crisis"
    liquidity: str                           # "deep" | "normal" | "thin" | "stressed"
    microstructure: str                      # "trending" | "mean_revert" | "choppy" | "breakout"
    confidence: float                        # 0.0–1.0, aggregate confidence
    dimension_confidences: dict[str, float]  # Per-dimension confidence
    regime_label: str                        # Human-readable, e.g. "LOW_VOL_TRENDING_UP"
    previous_regime_label: str | None
    transition_detected: bool                # True if regime changed this cycle
    risk_multiplier: float                   # 0.25–2.0, suggested position sizing multiplier
    suggested_strategies: list[str]          # Strategy names that perform well in this regime
    explanation: str                         # LLM-generated natural language explanation (Tier 2)
    ttl_seconds: int                         # How long this classification is valid
```

#### Tools

| Tool | Tier | Purpose |
|------|------|---------|
| `rust_volatility_engine` | T0 | Realized vol, percentile calculations, Garman-Klass |
| `rust_regime_classifier` | T0 | Core statistical regime detection (HMM, threshold-based) |
| `ollama_qwen` | T2 | Generate human-readable regime explanation |
| `redis_state_reader` | T0 | Read current market state from shared Redis |

#### Model Tier

| Component | Tier | Model | Rationale |
|-----------|------|-------|-----------|
| Statistical classification | **T0 (Rust)** | Custom HMM + threshold engine | Pure math, <1ms latency |
| Confidence scoring | **T0 (Rust)** | Custom | Probability math |
| Explanation generation | **T2 (LLM)** | Qwen2.5-7B via Ollama | Human-readable summary, not latency-critical |

#### Implementation Language

```
rust_regime_engine/
├── src/
│   ├── lib.rs              # PyO3 exports
│   ├── hmm.rs              # Hidden Markov Model regime detection
│   ├── volatility.rs       # Garman-Klass, Parkinson, Yang-Zhang estimators
│   ├── trend.rs            # ADX, EMA slope, Hurst exponent
│   ├── correlation.rs      # Rolling correlation matrix
│   ├── liquidity.rs        # Spread analysis, volume profiling
│   └── microstructure.rs   # Variance ratio, order flow toxicity

regime_detector/
├── __init__.py
├── agent.py                # Main agent loop (Python)
├── config.py               # Regime thresholds and parameters
├── publisher.py            # Redis stream publisher
└── llm_explainer.py        # Tier 2 LLM explanation generator
```

**Split:** ~80% Rust (detection math), ~20% Python (orchestration + LLM).

#### Communication Protocol

```
PUBLISHES TO:  trading:regime
SUBSCRIBES TO: trading:cartography (cross-asset data),
               trading:analytics   (strategy performance by regime)
READS STATE:   trading:state:positions
```

**Publish frequency:** Every 5 seconds, OR immediately on regime transition.

#### Lifecycle

```python
class RegimeDetectorAgent:
    """Lifecycle: spawn → warm_up → run_loop → report → die"""

    async def spawn(self):
        """Initialize Rust engine, connect Redis, load historical regime data."""
        self.rust_engine = regime_engine.Realm()  # PyO3 binding
        self.redis = await aioredis.from_url(REDIS_URL)
        self.llm = OllamaClient(model="qwen2.5:7b")
        await self._load_warmup_data(days=30)  # Need 30 days for HMM calibration

    async def run_loop(self):
        """Main detection loop — runs until killed."""
        while not self.shutdown_event.is_set():
            try:
                market_snapshot = await self._get_market_snapshot()
                regime = self.rust_engine.classify_regime(market_snapshot)

                if regime.transition_detected:
                    explanation = await self.llm.explain_regime_change(
                        old=regime.previous_regime_label,
                        new=regime.regime_label,
                        factors=regime.dimension_confidences,
                    )
                    regime = regime.with_explanation(explanation)

                await self.publisher.publish(regime)

                # Update shared state
                await self.redis.hset("trading:state:regime", mapping=regime.to_state_dict())

            except Exception as e:
                await self.report_error(e)
                await asyncio.sleep(1)  # Back off on error

            await asyncio.sleep(5)  # Normal cadence

    async def die(self, reason: str):
        """Graceful shutdown — publish final regime, close connections."""
        await self.redis.hset("trading:state:regime", "status", "offline")
        await self.redis.xadd("trading:health", {
            "agent": "regime_detector", "status": "dying", "reason": reason
        })
        await self.redis.close()
```

#### Error Handling

| Error | Response |
|-------|----------|
| Market data stale (>30s) | Publish regime with `confidence: 0.0`, flag `data_stale: true` |
| Rust engine panic | Catch via PyO3, restart engine, log, continue with degraded confidence |
| Redis connection lost | Reconnect with exponential backoff (100ms → 5s max) |
| LLM timeout | Skip explanation, publish regime without `explanation` field |

#### Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Classification latency | <5ms (Rust) | 10ms |
| Full cycle including LLM | <2s | 5s |
| Memory | <128MB | 256MB |
| CPU | <5% single core | 10% |

---

### 3.2 Signal Scout

> *"Where are the edges right now?"*

#### Role & Responsibility

Scans the universe of instruments for actionable trading signals. Adapts signal generation parameters based on current regime. Does NOT decide whether to trade — only identifies opportunities with statistical edge. Each signal includes a raw confidence score that the Risk Guardian will independently validate.

#### Signal Types

| Category | Signals | Lookback |
|----------|---------|----------|
| **Mean Reversion** | Bollinger band violations, RSI extremes, Z-score on spread | 20–60 bars |
| **Momentum** | Breakout with volume confirmation, trend continuation patterns | 50–200 bars |
| **Volatility** | Vol compression → expansion transitions, term structure kinks | 30–90 bars |
| **Microstructure** | Order flow imbalance, VPIN spikes, Kyle's Lambda shifts | 100ms–5min |
| **Cross-asset** | Relative value divergences, correlation break-downs | 20–60 bars |

#### Input Data

| Source | Data | Refresh |
|--------|------|---------|
| Market data | OHLCV, order book, trade tape | 1s |
| Regime Detector | Current regime classification | On change |
| Strategy Geneticist | Active strategy parameters, mutation list | On change |
| Market Cartographer | Correlation matrix, regime-specific betas | 1min |
| Historical | Signal performance history by regime | 1hour |

#### Output Format

```python
@dataclass(frozen=True)
class TradingSignal:
    """Published to trading:signals stream."""
    signal_id: str              # ULID
    timestamp: datetime
    instrument: str             # e.g. "ES", "NQ", "BTC-USD", "AAPL"
    direction: str              # "long" | "short"
    signal_type: str            # "mean_reversion" | "momentum" | "volatility" | "microstructure" | "cross_asset"
    strategy_name: str          # Which strategy generated this
    entry_price: float          # Suggested entry
    stop_loss: float            # Suggested stop
    take_profit: list[float]    # Multiple TP levels [tp1, tp2, tp3]
    confidence: float           # 0.0–1.0 raw statistical confidence
    edge_estimate: float        # Expected value in R-multiples
    regime_compatibility: float # How well this signal fits current regime (0–1)
    urgency: str                # "immediate" (<1min), "standard" (<15min), "setup" (<2hr)
    timeframe: str              # "scalp" | "intraday" | "swing" | "position"
    invalidation: str           # Condition that kills this signal
    context: dict               # Strategy-specific metadata (indicator values, etc.)
    correlation_risk: float     # From Cartographer: how correlated to existing positions
    size_suggestion: float      # Base size suggestion (pre-Risk Guardian adjustment)
```

#### Tools

| Tool | Tier | Purpose |
|------|------|---------|
| `rust_indicator_suite` | T0 | All technical indicators (RSI, BB, ATR, VPIN, etc.) |
| `rust_pattern_detector` | T0 | Chart pattern recognition, candle patterns |
| `rust_orderflow_analyzer` | T0 | Trade tape analysis, order book imbalance |
| `rust_backtest_quick` | T0 | Fast Monte Carlo on signal edge |
| `ollama_qwen` | T2 | Regime-aware signal filtering heuristics |

#### Model Tier

| Component | Tier | Model | Rationale |
|-----------|------|-------|-----------|
| Indicator computation | **T0 (Rust)** | Custom | Sub-millisecond, deterministic |
| Edge estimation | **T0 (Rust)** | Monte Carlo | Statistical, no LLM needed |
| Regime-aware filtering | **T1 (Python)** | scikit-learn / XGBoost | Classification of signal quality by regime |
| Signal narrative | **T2 (LLM)** | Qwen2.5-7B | Optional human-readable rationale |

#### Implementation Language

```
rust_signal_engine/
├── src/
│   ├── lib.rs                # PyO3 exports
│   ├── indicators/           # Full indicator library
│   ├── patterns/             # Candlestick + chart patterns
│   ├── orderflow/            # Trade tape, VPIN, Kyle's Lambda
│   ├── edge_estimator.rs     # Monte Carlo edge calculator
│   └── universe_scanner.rs   # Parallel instrument scanner

signal_scout/
├── __init__.py
├── agent.py                  # Main agent loop
├── strategy_registry.py      # Maps strategy names → signal generation logic
├── regime_adapter.py         # Adjusts signal parameters per regime
├── ml_filter.py              # Tier 1 ML signal quality filter
└── publisher.py
```

**Split:** ~70% Rust (computation), ~30% Python (orchestration, ML filter, strategy registry).

#### Communication Protocol

```
PUBLISHES TO:  trading:signals
SUBSCRIBES TO: trading:regime (adapt signal generation),
               trading:strategy_mutations (new strategy params),
               trading:cartography (correlation data)
READS STATE:   trading:state:positions (avoid duplicate exposure)
```

**Publish frequency:** Continuous scan, publish signals as detected. Rate-limited to 50 signals/minute max (prevents signal flood).

#### Lifecycle

```python
class SignalScoutAgent:
    async def spawn(self):
        self.rust_scanner = signal_engine.UniverseScanner()  # PyO3
        self.indicator_suite = signal_engine.IndicatorSuite()
        self.ml_filter = SignalQualityModel.load("models/signal_filter_v1.pkl")
        self.strategy_registry = StrategyRegistry()
        self.current_regime = None

    async def run_loop(self):
        while not self.shutdown_event.is_set():
            # Check for regime updates
            regime_update = await self.try_read_stream("trading:regime", last_only=True)
            if regime_update:
                self.current_regime = regime_update
                self.strategy_registry.adapt_to_regime(regime_update)

            # Scan all instruments in parallel (Rust)
            instruments = self.universe.get_active_instruments()
            snapshots = await self._get_snapshots(instruments)
            raw_signals = self.rust_scanner.scan_all(snapshots, self.current_regime)

            # ML quality filter (Python)
            filtered = self.ml_filter.rank_and_filter(raw_signals, min_confidence=0.6)

            for signal in filtered:
                # Enrich with correlation data
                signal = await self._enrich_with_correlation(signal)
                await self.publisher.publish(signal)

            await asyncio.sleep(1)  # Scan cadence

    async def die(self, reason: str):
        """Publish final health status, flush any pending signals."""
        ...
```

#### Error Handling

| Error | Response |
|-------|----------|
| Instrument data missing | Skip instrument, log warning, continue with others |
| Indicator calculation overflow | Clamp values, flag signal as `degraded: true` |
| ML model unavailable | Fall back to pure threshold-based filtering |
| Signal flood (>50/min) | Drop lowest-confidence signals, publish `signal_flood_warning` |

#### Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Full universe scan (100 instruments) | <50ms (Rust) | 100ms |
| Signal-to-publish latency | <100ms | 250ms |
| Memory | <256MB | 512MB |
| CPU | <15% single core | 25% |

---

### 3.3 Risk Guardian

> *"Is this trade safe?"* — **VETO POWER**

#### Role & Responsibility

The **single most critical agent** in the system. Acts as the gatekeeper between signal generation and order execution. Has absolute VETO power — no trade executes without Risk Guardian approval. Evaluates every proposed trade against portfolio-level risk constraints, position limits, drawdown limits, and regime-appropriate risk parameters.

**Design philosophy:** Conservative by default. When uncertain, VETO. False negatives (missing a good trade) are acceptable; false positives (taking a bad trade) are not.

#### Risk Checks (Ordered by Severity)

| Priority | Check | VETO Condition |
|----------|-------|----------------|
| P0 | **Kill switch** | Daily P&L < -2% of capital → VETO ALL |
| P0 | **Max drawdown** | Drawdown from HWM > 5% → VETO ALL |
| P1 | **Position concentration** | Single instrument > 15% of capital → VETO |
| P1 | **Sector concentration** | Single sector > 30% of capital → VETO |
| P1 | **Correlation exposure** | New trade correlation to portfolio > 0.7 → VETO |
| P2 | **Regime compatibility** | Signal regime_compatibility < 0.4 → VETO |
| P2 | **Volatility scaling** | Instrument vol > 3x portfolio vol → REDUCE size |
| P2 | **Time-of-day** | Within 5min of major news → VETO or REDUCE |
| P3 | **Edge threshold** | Signal edge_estimate < 0.3R → VETO |
| P3 | **Maximum open positions** | > 10 concurrent positions → VETO |
| P3 | **Daily trade count** | > 30 trades/day → REDUCE frequency |

#### Input Data

| Source | Data |
|--------|------|
| Signal Scout | Proposed trading signal |
| Execution Tracker | Current positions, P&L, margin usage |
| Regime Detector | Current regime, risk multiplier |
| Market Cartographer | Correlation matrix, tail risk metrics |
| Static config | Hard limits (max drawdown, position limits, etc.) |

#### Output Format

```python
@dataclass(frozen=True)
class RiskDecision:
    """Published to trading:risk_decisions stream."""
    decision_id: str
    timestamp: datetime
    signal_id: str                      # Which signal this evaluates
    verdict: str                        # "approve" | "veto" | "reduce" | "modify"
    risk_score: float                   # 0.0 (safest) to 1.0 (maximum risk)
    checks_passed: list[str]            # Names of checks that passed
    checks_failed: list[str]            # Names of checks that failed
    adjusted_size: float | None         # If "reduce", the adjusted position size
    adjusted_stop: float | None         # If modified stop loss
    adjusted_tp: list[float] | None     # If modified take profit levels
    veto_reason: str | None             # Human-readable veto reason
    veto_category: str | None           # "kill_switch" | "concentration" | "regime" | etc.
    portfolio_context: dict             # Current portfolio state snapshot
    explanation: str                    # LLM-generated explanation (Tier 2)
    expires_at: datetime                # Decision expires if not executed within this time
```

#### Tools

| Tool | Tier | Purpose |
|------|------|---------|
| `rust_portfolio_calculator` | T0 | Position sizing, margin, portfolio Greeks |
| `rust_risk_engine` | T0 | VaR, CVaR, max drawdown, correlation checks |
| `rust_order_validator` | T0 | Pre-trade compliance checks |
| `ollama_deepseek_r1` | T3 | Complex risk scenario analysis (only for edge cases) |

#### Model Tier

| Component | Tier | Model | Rationale |
|-----------|------|-------|-----------|
| All quantitative checks | **T0 (Rust)** | Custom | Deterministic, auditable, <1ms |
| Edge case risk analysis | **T3 (LLM)** | DeepSeek-R1 | Complex multi-factor scenarios, rare events |
| Explanation generation | **T2 (LLM)** | Qwen2.5-7B | Human-readable decision explanation |

**Critical:** Tier 3 is ONLY used for explanation generation and rare edge-case analysis. The VETO decision itself is always Tier 0 (pure deterministic code). No LLM can VETO or APPROVE.

#### Implementation Language

```
rust_risk_engine/
├── src/
│   ├── lib.rs                  # PyO3 exports
│   ├── portfolio.rs            # Portfolio-level risk calculations
│   ├── position_sizer.rs       # Kelly criterion, vol-adjusted sizing
│   ├── drawdown.rs             # Max drawdown tracking, HWM
│   ├── concentration.rs        # Position/sector/correlation limits
│   ├── var.rs                  # VaR, CVaR, Monte Carlo
│   ├── regime_risk.rs          # Regime-adjusted risk parameters
│   ├── kill_switch.rs          # Hard circuit breakers
│   └── compliance.rs           # Pre-trade compliance rules

risk_guardian/
├── __init__.py
├── agent.py                    # Main agent loop (Python)
├── decision_engine.py          # Orchestrates Rust checks in sequence
├── config.py                   # Risk limits, thresholds
├── llm_advisor.py              # DeepSeek-R1 for edge cases
└── publisher.py
```

**Split:** ~85% Rust (all risk math), ~15% Python (orchestration, LLM calls).

#### Communication Protocol

```
PUBLISHES TO:  trading:risk_decisions
SUBSCRIBES TO: trading:signals  (evaluate incoming signals),
               trading:fills    (update position state),
               trading:regime   (adjust risk parameters),
               trading:cartography (correlation updates)
READS STATE:   trading:state:positions (current portfolio)
WRITES STATE:  trading:state:risk (current risk metrics, drawdown state)
```

**Critical pattern:** Risk Guardian runs a **synchronous request-reply** channel for time-critical vetoes. The Execution Sniper sends a direct `XADD` to `trading:risk_requests` and blocks on the reply stream with a 50ms timeout. If no reply arrives, the default is APPROVE with reduced size (fail-open with caution).

#### Lifecycle

```python
class RiskGuardianAgent:
    async def spawn(self):
        self.rust_risk = risk_engine.RiskEngine()  # PyO3
        self.rust_portfolio = risk_engine.PortfolioCalculator()
        self.kill_switch_armed = True
        self.daily_pnl = 0.0
        self.max_drawdown_pct = 0.0
        self.hwm = await self._load_hwm()

    async def run_loop(self):
        while not self.shutdown_event.is_set():
            # Process signal evaluation requests
            messages = await self.redis.xreadgroup(
                "risk_group", "risk_consumer",
                {"trading:signals": ">"},
                count=10, block=100
            )

            for stream, msgs in messages:
                for msg_id, data in msgs:
                    signal = TradingSignal.from_msgpack(data)
                    decision = await self.evaluate(signal)
                    await self.publish(decision)
                    await self.redis.xack("trading:signals", "risk_group", msg_id)

            # Process synchronous risk requests (from Execution Sniper)
            requests = await self.redis.xreadgroup(
                "risk_sync_group", "risk_sync_consumer",
                {"trading:risk_requests": ">"},
                count=5, block=50
            )

            for stream, msgs in requests:
                for msg_id, data in msgs:
                    order = Order.from_msgpack(data["order"])
                    decision = await self.evaluate_order(order)
                    await self.redis.xadd(data["reply_to"], decision.to_msgpack())
                    await self.redis.xack("trading:risk_requests", "risk_sync_group", msg_id)

            # Update shared risk state
            await self._update_risk_state()

    async def evaluate(self, signal: TradingSignal) -> RiskDecision:
        """Run all risk checks in priority order. Short-circuit on P0 failures."""
        # P0 checks (kill switch, max drawdown)
        if not self.rust_risk.check_kill_switch(self.daily_pnl, self.hwm):
            return RiskDecision.veto(signal, "kill_switch", "Daily P&L limit breached")

        if not self.rust_risk.check_max_drawdown(self.max_drawdown_pct):
            return RiskDecision.veto(signal, "max_drawdown", "Max drawdown from HWM exceeded")

        # P1 checks (concentration, correlation)
        portfolio = await self._get_portfolio_state()
        conc = self.rust_risk.check_concentration(signal, portfolio)
        if not conc.passed:
            return RiskDecision.veto(signal, "concentration", conc.reason)

        # P2 checks (regime, volatility)
        regime = await self._get_current_regime()
        regime_compat = self.rust_risk.check_regime_compatibility(signal, regime)
        if not regime_compat.passed:
            return RiskDecision.veto(signal, "regime", regime_compat.reason)

        # P3 checks (edge, limits)
        edge_check = self.rust_risk.check_edge_threshold(signal)
        if not edge_check.passed:
            return RiskDecision.veto(signal, "edge", edge_check.reason)

        # All checks passed — approve with possibly adjusted size
        adjusted_size = self.rust_portfolio.calculate_position_size(
            signal, portfolio, regime.risk_multiplier
        )

        return RiskDecision.approve(signal, adjusted_size=adjusted_size)

    async def die(self, reason: str):
        """NEVER die silently. Publish final risk state, alert orchestrator."""
        await self.redis.xadd("trading:health", {
            "agent": "risk_guardian", "status": "CRITICAL_SHUTDOWN", "reason": reason
        })
        # Freeze all trading by publishing a "VETO_ALL" signal
        await self.redis.xadd("trading:risk_decisions", {
            "verdict": "veto_all",
            "reason": f"Risk Guardian offline: {reason}",
            "ttl_seconds": 300,  # Auto-unfreeze after 5min if not restarted
        })
```

#### Error Handling

| Error | Response | Severity |
|-------|----------|----------|
| Redis connection lost | **IMMEDIATELY halt all trading** — publish VETO_ALL to all channels | CRITICAL |
| Rust engine panic | Catch, restart engine, VETO all during restart window | CRITICAL |
| Evaluation timeout (>50ms) | VETO the specific trade, not all trades | HIGH |
| State read failure | VETO — cannot evaluate without portfolio state | CRITICAL |
| LLM timeout | Skip explanation, decision is still deterministic | LOW |

**The Risk Guardian is the ONE agent that must NEVER fail silently.**

#### Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Decision latency (quant checks) | <2ms (Rust) | 5ms |
| Decision latency (with LLM explanation) | <500ms | 2s |
| Synchronous veto response time | <5ms | 50ms |
| Throughput | 1000 decisions/sec | 5000/sec |
| Memory | <128MB | 256MB |
| CPU | <10% single core | 20% |

---

### 3.4 Execution Sniper

> *"When and how to enter?"*

#### Role & Responsibility

Receives Risk-Approved signals and translates them into precise, executable orders. Handles order type selection, optimal entry timing, smart order routing, and execution quality monitoring. This is where the system meets the market.

#### Execution Strategies

| Strategy | When Used | Implementation |
|----------|-----------|----------------|
| **Immediate IOC** | High urgency, liquid market | Send IOC order immediately |
| **TWAP** | Standard urgency, slice over time | Time-weighted slices over 1-5min |
| **VWAP** | Large orders, thin market | Volume-weighted, track VWAP benchmark |
| **Aggressive limit** | Near support/resistance | Limit order at edge, chase with market if not filled |
| **Iceberg** | Very large orders | Show small size, replenish on fills |
| **Sniper** | Scalp entries | Wait for specific price level, instant IOC |

#### Input Data

| Source | Data |
|--------|------|
| Risk Guardian | Approved signal with adjusted size |
| Market data | Real-time order book, last trade, VWAP |
| Execution Tracker | Current fills, slippage stats |
| Regime Detector | Current regime (affects urgency/slicing) |

#### Output Format

```python
@dataclass(frozen=True)
class OrderCommand:
    """Published to trading:orders stream."""
    order_id: str               # ULID
    parent_signal_id: str       # Link back to original signal
    timestamp: datetime
    instrument: str
    side: str                   # "buy" | "sell"
    quantity: float             # In lots/contracts/shares
    order_type: str             # "market" | "limit" | "stop" | "stop_limit"
    limit_price: float | None
    stop_price: float | None
    time_in_force: str          # "IOC" | "GTC" | "DAY" | "GTX"
    execution_strategy: str     # "immediate" | "twap" | "vwap" | "sniper" | "iceberg"
    strategy_params: dict       # TWAP slice count, iceberg display size, etc.
    exchange: str | None        # Route to specific exchange if needed
    urgency: str                # From original signal
    max_slippage_bps: float     # Abort if slippage exceeds this
    risk_decision_id: str       # Link to Risk Guardian approval
    stop_loss_order: OrderCommand | None  # Attached stop loss
    take_profit_orders: list[OrderCommand] | None  # Attached TP levels
```

#### Tools

| Tool | Tier | Purpose |
|------|------|---------|
| `rust_order_router` | T0 | Order type selection, smart routing |
| `rust_execution_engine` | T0 | Order submission, fill tracking |
| `rust_slippage_analyzer` | T0 | Real-time slippage measurement |
| `rust_market_impact` | T0 | Estimate market impact of order |
| `pyo3_broker_adapter` | T0 | Exchange/broker API interface |

#### Model Tier

| Component | Tier | Model | Rationale |
|-----------|------|-------|-----------|
| Order routing logic | **T0 (Rust)** | Custom | Deterministic, auditable |
| Market impact estimation | **T0 (Rust)** | Almgren-Chriss model | Pure math |
| Optimal execution timing | **T0 (Rust)** | Custom | Latency-critical |
| **No LLM usage** | — | — | Execution must be deterministic and fast |

#### Implementation Language

```
rust_execution_engine/
├── src/
│   ├── lib.rs                  # PyO3 exports
│   ├── order_router.rs         # Smart order routing
│   ├── execution_strategies/
│   │   ├── mod.rs
│   │   ├── immediate.rs        # IOC market orders
│   │   ├── twap.rs             # Time-weighted average price
│   │   ├── vwap.rs             # Volume-weighted average price
│   │   ├── iceberg.rs          # Iceberg orders
│   │   └── sniper.rs           # Precision limit orders
│   ├── market_impact.rs        # Almgren-Chriss impact model
│   ├── slippage.rs             # Real-time slippage tracking
│   ├── order_manager.rs        # Order lifecycle management
│   └── broker_adapters/        # Exchange-specific adapters
│       ├── mod.rs
│       ├── ibkr.rs             # Interactive Brokers
│       ├── binance.rs          # Binance
│       └── simulated.rs        # Paper trading

execution_sniper/
├── __init__.py
├── agent.py                    # Main agent loop (Python)
├── config.py                   # Execution parameters
└── publisher.py
```

**Split:** ~95% Rust, ~5% Python (thin orchestration shell).

#### Communication Protocol

```
PUBLISHES TO:  trading:orders
SUBSCRIBES TO: trading:risk_decisions (approved signals to execute)
SENDS SYNC:    trading:risk_requests → trading:risk_reply:* (re-check before execution)
READS STATE:   trading:state:positions
```

#### Lifecycle

```python
class ExecutionSniperAgent:
    async def spawn(self):
        self.rust_engine = execution_engine.ExecutionEngine()  # PyO3
        self.rust_router = execution_engine.OrderRouter()
        self.broker = execution_engine.BrokerAdapter(config.broker)

    async def run_loop(self):
        while not self.shutdown_event.is_set():
            messages = await self.redis.xreadgroup(
                "sniper_group", "sniper_consumer",
                {"trading:risk_decisions": ">"},
                count=5, block=100
            )

            for stream, msgs in messages:
                for msg_id, data in msgs:
                    decision = RiskDecision.from_msgpack(data)

                    if decision.verdict == "veto":
                        await self.redis.xack("trading:risk_decisions", "sniper_group", msg_id)
                        continue

                    if decision.verdict == "veto_all":
                        await self._cancel_all_pending()
                        await self.redis.xack("trading:risk_decisions", "sniper_group", msg_id)
                        continue

                    # Final re-check with Risk Guardian (synchronous)
                    order = self.rust_router.build_order(decision)
                    final_check = await self._sync_risk_check(order, timeout_ms=50)

                    if final_check.approved:
                        result = await self.rust_engine.execute(order)
                        await self.redis.xadd("trading:orders", result.to_msgpack())

                    await self.redis.xack("trading:risk_decisions", "sniper_group", msg_id)

    async def die(self, reason: str):
        """Cancel all pending orders before dying."""
        await self._cancel_all_pending()
        await self.redis.xadd("trading:health", {
            "agent": "execution_sniper", "status": "dying", "reason": reason
        })
```

#### Error Handling

| Error | Response |
|-------|----------|
| Broker API down | Queue orders, retry with backoff, alert after 30s |
| Order rejected by exchange | Log, do NOT retry blindly, notify Risk Guardian |
| Slippage exceeds threshold | Cancel remaining slices, report partial fill |
| Timeout on sync risk check | Proceed with reduced size (fail-open with caution) |
| Partial fill on IOC | Report partial, do not chase unless strategy allows |

#### Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Signal-to-order latency | <5ms (Rust) | 10ms |
| Order-to-broker latency | <1ms (local) | 10ms (remote API) |
| TWAP slice timing accuracy | <50ms deviation | 100ms |
| Memory | <64MB | 128MB |

---

### 3.5 Execution Tracker

> *"Monitor and manage open positions"*

#### Role & Responsibility

Tracks all open positions in real-time. Manages stop losses, take profit levels, trailing stops, and position lifecycle. Provides the single source of truth for portfolio state. Calculates real-time P&L, margin usage, and position metrics.

#### Position Management Features

| Feature | Description |
|---------|-------------|
| **Stop loss management** | Move to breakeven after 1R profit, trail stops |
| **Take profit execution** | Scale out at multiple TP levels |
| **Trailing stops** | ATR-based, percentage-based, structure-based |
| **Position reconciliation** | Sync with broker positions every 30s |
| **Real-time P&L** | Mark-to-market every tick |
| **Margin monitoring** | Track margin usage, alert at 80% |

#### Input Data

| Source | Data |
|--------|------|
| Execution Sniper | Order fills, partial fills |
| Market data | Real-time prices for all held instruments |
| Risk Guardian | Risk parameters, stop/TP rules |
| Regime Detector | Regime-based position management rules |

#### Output Format

```python
@dataclass(frozen=True)
class PositionUpdate:
    """Published to trading:positions stream."""
    update_id: str
    timestamp: datetime
    position_id: str
    instrument: str
    side: str
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    realized_pnl: float
    holding_duration: timedelta
    current_stop: float
    current_tp: list[float]
    trailing_stop_active: bool
    risk_reward_current: float  # Current R-multiple
    margin_used: float
    update_type: str            # "fill" | "stop_update" | "tp_hit" | "trailing_update" | "close"

@dataclass(frozen=True)
class PortfolioState:
    """Published to trading:positions stream periodically."""
    timestamp: datetime
    total_positions: int
    long_positions: int
    short_positions: float
    total_unrealized_pnl: float
    total_realized_pnl_today: float
    total_margin_used: float
    margin_available: float
    portfolio_beta: float
    max_position_pct: float     # Largest single position as % of capital
    daily_trade_count: int
    positions: list[PositionUpdate]
```

#### Tools

| Tool | Tier | Purpose |
|------|------|---------|
| `rust_position_manager` | T0 | Position tracking, P&L calculation |
| `rust_pnl_engine` | T0 | Mark-to-market, realized/unrealized P&L |
| `rust_trailing_stop` | T0 | Trailing stop logic (ATR, %, structure) |
| `rust_reconciler` | T0 | Broker position reconciliation |
| `rust_margin_calculator` | T0 | Real-time margin tracking |

#### Model Tier

| Component | Tier | Model | Rationale |
|-----------|------|-------|-----------|
| **All components** | **T0 (Rust)** | Custom | Pure state management, no reasoning needed |

**No LLM usage.** This agent is pure computation and state management.

#### Implementation Language

```
rust_tracker_engine/
├── src/
│   ├── lib.rs                  # PyO3 exports
│   ├── position_manager.rs     # Position state machine
│   ├── pnl_engine.rs           # P&L calculations (realized, unrealized, fees)
│   ├── trailing_stop.rs        # Trailing stop algorithms
│   ├── margin.rs               # Margin tracking
│   ├── reconciler.rs           # Broker position sync
│   └── state_persistence.rs    # Position state to disk/Redis

execution_tracker/
├── __init__.py
├── agent.py                    # Main agent loop (Python)
├── config.py                   # Stop/TP rules, trailing parameters
└── publisher.py
```

**Split:** ~98% Rust, ~2% Python (thin orchestration only).

#### Communication Protocol

```
PUBLISHES TO:  trading:positions, trading:fills
SUBSCRIBES TO: trading:orders (new fills),
               trading:regime (adjust management rules)
WRITES STATE:  trading:state:positions (SINGLE SOURCE OF TRUTH)
```

#### Lifecycle

```python
class ExecutionTrackerAgent:
    async def spawn(self):
        self.rust_manager = tracker_engine.PositionManager()
        self.rust_pnl = tracker_engine.PnlEngine()
        await self._restore_positions_from_persistence()

    async def run_loop(self):
        while not self.shutdown_event.is_set():
            # Process new fills
            fills = await self.redis.xreadgroup(
                "tracker_group", "tracker_consumer",
                {"trading:orders": ">"},
                count=20, block=50
            )
            for fill in fills:
                self.rust_manager.process_fill(fill)

            # Update all positions with latest prices
            prices = await self._get_current_prices()
            updates = self.rust_manager.update_all_positions(prices)

            for update in updates:
                if update.update_type in ("tp_hit", "stop_hit", "close"):
                    # Execute the close
                    close_order = self.rust_manager.build_close_order(update)
                    await self.redis.xadd("trading:orders", close_order.to_msgpack())

                await self.publisher.publish(update)

            # Periodic portfolio state snapshot
            if self._should_publish_portfolio():
                portfolio = self.rust_manager.get_portfolio_state()
                await self.redis.hset(
                    "trading:state:positions",
                    mapping=portfolio.to_state_dict()
                )
                await self.publisher.publish_portfolio(portfolio)

            # Periodic reconciliation
            if self._should_reconcile():
                broker_positions = await self._fetch_broker_positions()
                diffs = self.rust_manager.reconcile(broker_positions)
                if diffs:
                    await self._alert_reconciliation_diff(diffs)

            await asyncio.sleep(100ms)  # Tick rate

    async def die(self, reason: str):
        """CRITICAL: Persist all position state before dying."""
        await self._persist_all_positions()
        await self.redis.xadd("trading:health", {
            "agent": "execution_tracker", "status": "dying", "reason": reason
        })
```

#### Error Handling

| Error | Response |
|-------|----------|
| Price feed stale | Use last known price, flag positions as `stale_price: true` |
| Broker reconciliation mismatch | Alert immediately, halt new trades until resolved |
| Position state corruption | Restore from last persisted snapshot |
| Trailing stop execution failure | Retry 3x, then alert for manual intervention |

#### Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Position update latency | <1ms (Rust) | 2ms |
| P&L calculation (100 positions) | <5ms | 10ms |
| Reconciliation cycle | <500ms | 2s |
| Memory | <128MB | 256MB |

---

### 3.6 Trade Philosopher

> *"Why did this trade win/lose?"*

#### Role & Responsibility

Post-trade analysis engine. Analyzes completed trades to extract lessons, identify patterns in wins/losses, detect behavioral biases, and generate actionable insights. This is the system's **learning loop** — without it, the system never improves.

#### Analysis Dimensions

| Dimension | What It Analyzes |
|-----------|-----------------|
| **Entry quality** | Was the entry at the right price? Did we get filled near signal price? |
| **Timing** | Was the trade taken at the right time in the regime cycle? |
| **Sizing** | Was the position size appropriate for the conviction level? |
| **Exit quality** | Did we exit at the right time? Was the stop/TP optimal? |
| **Risk/reward** | Actual R-multiple vs expected R-multiple |
| **Behavioral** | Revenge trading, overtrading, cutting winners short, letting losers run |
| **Regime context** | How did the regime affect this trade's outcome? |

#### Input Data

| Source | Data |
|--------|------|
| Execution Tracker | Completed trade details (entry, exit, P&L, duration) |
| Signal Scout (historical) | Original signal that triggered the trade |
| Risk Guardian (historical) | Risk decision that approved the trade |
| Market data (historical) | Price action during trade lifecycle |
| Regime Detector (historical) | Regime during trade |
| Market Cartographer | Correlation context during trade |

#### Output Format

```python
@dataclass(frozen=True)
class TradeAnalysis:
    """Published to trading:analytics stream."""
    analysis_id: str
    timestamp: datetime
    trade_id: str
    instrument: str
    direction: str
    entry_price: float
    exit_price: float
    realized_pnl: float
    r_multiple: float               # Actual R-multiple achieved
    expected_r_multiple: float      # What the signal predicted
    holding_duration: timedelta
    regime_during_trade: str

    # Quality scores (0–1)
    entry_quality: float
    exit_quality: float
    timing_quality: float
    sizing_quality: float

    # Classification
    outcome: str                    # "win" | "loss" | "scratch"
    win_type: str | None            # "edge_play" | "lucky" | "trend_riding" | "mean_revert"
    loss_type: str | None           # "bad_entry" | "stop_too_tight" | "regime_change" | "black_swan"

    # Insights
    lessons: list[str]              # 1-3 specific lessons
    pattern_tags: list[str]         # For pattern aggregation
    behavioral_flags: list[str]     # Bias detections
    suggested_improvements: list[str]

    # Narrative
    explanation: str                # LLM-generated trade narrative

    # For strategy evolution
    strategy_name: str
    strategy_params_snapshot: dict
    signal_snapshot: dict
```

#### Tools

| Tool | Tier | Purpose |
|------|------|---------|
| `rust_trade_analyzer` | T0 | Entry/exit quality calculations, R-multiple |
| `rust_pattern_aggregator` | T0 | Pattern detection across trade history |
| `ollama_deepseek_r1` | T3 | Trade narrative, lesson extraction, bias detection |
| `ollama_qwen` | T2 | Quick summaries, pattern tagging |

#### Model Tier

| Component | Tier | Model | Rationale |
|-----------|------|-------|-----------|
| Quantitative analysis | **T0 (Rust)** | Custom | R-multiples, slippage, timing metrics |
| Pattern aggregation | **T0 (Rust)** | Custom | Statistical pattern detection |
| Trade narrative | **T3 (LLM)** | DeepSeek-R1 | Complex reasoning about trade outcome |
| Bias detection | **T3 (LLM)** | DeepSeek-R1 | Behavioral pattern recognition |
| Quick summaries | **T2 (LLM)** | Qwen2.5-7B | Fast summaries for non-critical trades |

#### Implementation Language

```
rust_analytics_engine/
├── src/
│   ├── lib.rs                  # PyO3 exports
│   ├── trade_analyzer.rs       # Entry/exit quality, R-multiple calculations
│   ├── pattern_aggregator.rs   # Statistical pattern detection
│   ├── behavioral_detector.rs  # Quantitative bias detection
│   └── trade_store.rs          # Historical trade storage/querying

trade_philosopher/
├── __init__.py
├── agent.py                    # Main agent loop (Python)
├── analysis_pipeline.py        # Orchestrates quant → LLM analysis
├── llm_narrator.py             # DeepSeek-R1 trade narratives
├── bias_detector.py            # Behavioral analysis
└── publisher.py
```

**Split:** ~60% Rust (quantitative analysis), ~40% Python (LLM orchestration, narrative generation).

#### Communication Protocol

```
PUBLISHES TO:  trading:analytics
SUBSCRIBES TO: trading:fills (completed trades),
               trading:positions (position lifecycle events)
READS STATE:   trading:state:positions
QUERIES:       Historical signal/risk decision data via Redis or DuckDB
```

**Publish frequency:** On trade close. Batch analysis for multiple closes within 1 minute.

#### Lifecycle

```python
class TradePhilosopherAgent:
    async def spawn(self):
        self.rust_analyzer = analytics_engine.TradeAnalyzer()
        self.rust_patterns = analytics_engine.PatternAggregator()
        self.llm_narrator = DeepSeekClient(model="deepseek-r1")
        self.llm_quick = OllamaClient(model="qwen2.5:7b")
        self.trade_db = await self._load_trade_database()

    async def run_loop(self):
        while not self.shutdown_event.is_set():
            # Monitor for completed trades
            fills = await self.redis.xreadgroup(
                "philosopher_group", "philosopher_consumer",
                {"trading:fills": ">"},
                count=10, block=1000  # Longer block — analysis is not time-critical
            )

            for fill in fills:
                if fill.is_close:  # Position fully closed
                    analysis = await self.analyze_trade(fill)
                    await self.publisher.publish(analysis)

                    # Update pattern database
                    self.rust_patterns.ingest(analysis)

                    # Periodically generate pattern reports
                    if self._should_report_patterns():
                        report = await self._generate_pattern_report()
                        await self.publisher.publish_patterns(report)

            await asyncio.sleep(1)

    async def analyze_trade(self, fill) -> TradeAnalysis:
        """Two-phase analysis: quantitative (Rust) then narrative (LLM)."""
        # Phase 1: Quantitative (fast, deterministic)
        trade_data = await self._gather_trade_context(fill)
        quant = self.rust_analyzer.analyze(trade_data)

        # Phase 2: Narrative (slower, reasoning)
        if quant.r_multiple > 2.0 or quant.r_multiple < -1.0:
            # Significant trades get DeepSeek-R1 analysis
            narrative = await self.llm_narrator.analyze_trade(quant, trade_data)
        else:
            # Routine trades get quick Qwen summary
            narrative = await self.llm_quick.summarize_trade(quant)

        return TradeAnalysis(quantitative=quant, narrative=narrative)
```

#### Error Handling

| Error | Response |
|-------|----------|
| Trade context data missing | Analyze with available data, flag `incomplete_context: true` |
| LLM timeout | Use quantitative analysis only, skip narrative |
| Trade database corruption | Rebuild from stream history (slow but safe) |

#### Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Quantitative analysis latency | <10ms (Rust) | 25ms |
| Full analysis with LLM | <30s | 60s |
| Pattern report generation | <5s | 15s |
| Memory | <256MB | 512MB |

---

### 3.7 Strategy Geneticist

> *"Evolve and create new strategies"*

#### Role & Responsibility

The creative engine of the system. Uses genetic programming and LLM reasoning to evolve existing strategies and discover new ones. Operates on the meta-level: it doesn't trade, it designs the strategies that Signal Scout uses to find trades. Combines historical performance data with regime context to breed better strategies.

#### Evolution Mechanisms

| Mechanism | Description |
|-----------|-------------|
| **Parameter mutation** | Adjust existing strategy parameters (indicator periods, thresholds) |
| **Crossover** | Combine successful elements from two strategies |
| **Pruning** | Remove underperforming strategies from the active pool |
| **LLM synthesis** | Use LLM to propose entirely new strategy hypotheses |
| **Regime specialization** | Fork a general strategy into regime-specific variants |

#### Input Data

| Source | Data |
|--------|------|
| Trade Philosopher | Strategy performance analytics, patterns, lessons |
| Regime Detector | Current and historical regime data |
| Signal Scout | Current active strategy performance |
| Historical | Full backtest results for strategy universe |
| External | Academic papers, new indicators (via LLM) |

#### Output Format

```python
@dataclass(frozen=True)
class StrategyMutation:
    """Published to trading:strategy_mutations stream."""
    mutation_id: str
    timestamp: datetime
    mutation_type: str          # "parameter_change" | "crossover" | "new_strategy" | "pruning"
    parent_strategy: str | None # Original strategy being mutated
    parent_strategy_2: str | None  # Second parent for crossover
    new_strategy_name: str
    strategy_definition: dict   # Complete strategy spec
    parameters: dict            # All tunable parameters
    expected_regimes: list[str] # Regimes where this should perform
    backtest_results: dict      # Sharpe, win rate, max DD, etc.
    confidence: float           # How confident in this mutation
    rationale: str              # Why this mutation was proposed
    ab_test_plan: dict          # How to test this (paper trade params)

@dataclass(frozen=True)
class StrategyReport:
    """Periodic report on strategy pool health."""
    timestamp: datetime
    active_strategies: list[dict]   # Name, performance, regime fit
    retired_strategies: list[dict]  # Recently pruned
    pending_mutations: list[dict]   # Awaiting backtest
    pool_diversity_score: float     # 0–1, how diverse is the strategy pool
    recommended_actions: list[str]
```

#### Tools

| Tool | Tier | Purpose |
|------|------|---------|
| `rust_genetic_engine` | T0 | Genetic algorithm operations (mutation, crossover, selection) |
| `rust_backtest_engine` | T0 | Full backtest of candidate strategies |
| `rust_optimizer` | T0 | Parameter optimization (Bayesian, grid) |
| `ollama_deepseek_r1` | T3 | Strategy hypothesis generation, creative reasoning |
| `ollama_qwen` | T2 | Strategy description, parameter suggestions |

#### Model Tier

| Component | Tier | Model | Rationale |
|-----------|------|-------|-----------|
| Genetic operations | **T0 (Rust)** | Custom | Deterministic, reproducible |
| Backtesting | **T0 (Rust)** | Custom | Must be fast and accurate |
| Parameter optimization | **T0 (Rust)** | Bayesian optimizer | Math-heavy |
| Strategy synthesis | **T3 (LLM)** | DeepSeek-R1 | Creative reasoning about new approaches |
| Strategy evaluation | **T2 (LLM)** | Qwen2.5-7B | Quick assessment of strategy viability |

#### Implementation Language

```
rust_genetic_engine/
├── src/
│   ├── lib.rs                  # PyO3 exports
│   ├── genetic_ops.rs          # Mutation, crossover, selection operators
│   ├── backtest_engine.rs      # Full backtest framework
│   ├── optimizer.rs            # Bayesian parameter optimization
│   ├── strategy_dsl.rs         # Strategy definition language
│   ├── fitness.rs              # Multi-objective fitness function
│   └── population.rs           # Strategy population management

strategy_geneticist/
├── __init__.py
├── agent.py                    # Main agent loop (Python)
├── evolution_pipeline.py       # Orchestrates evolution cycle
├── llm_strategist.py           # DeepSeek-R1 strategy synthesis
├── strategy_library.py         # Strategy catalog management
├── backtest_runner.py          # Runs backtests via Rust engine
└── publisher.py
```

**Split:** ~70% Rust (genetic ops, backtesting), ~30% Python (LLM orchestration, strategy management).

#### Communication Protocol

```
PUBLISHES TO:  trading:strategy_mutations
SUBSCRIBES TO: trading:analytics (trade analysis results),
               trading:regime (regime context for strategy design)
READS STATE:   Strategy performance database (DuckDB or Redis)
```

**Evolution cycle:** Runs every 4 hours, or when significant pattern changes detected.

#### Lifecycle

```python
class StrategyGeneticistAgent:
    async def spawn(self):
        self.rust_genetic = genetic_engine.GeneticEngine()
        self.rust_backtest = genetic_engine.BacktestEngine()
        self.llm_strategist = DeepSeekClient(model="deepseek-r1")
        self.population = await self._load_strategy_population()

    async def run_loop(self):
        while not self.shutdown_event.is_set():
            # Check for new trade analysis insights
            analytics = await self.redis.xreadgroup(
                "geneticist_group", "geneticist_consumer",
                {"trading:analytics": ">"},
                count=20, block=5000
            )

            if analytics:
                # Ingest new performance data
                for analysis in analytics:
                    self.population.update_fitness(analysis)

                # Trigger evolution if enough new data
                if self._should_evolve():
                    await self.evolve()

            # Check regime changes for strategy adaptation
            regime = await self.try_read_stream("trading:regime", last_only=True)
            if regime and regime != self.last_regime:
                await self._adapt_strategies_to_regime(regime)

            await asyncio.sleep(10)

    async def evolve(self):
        """Full evolution cycle: evaluate → select → mutate → backtest → publish."""
        # 1. Evaluate current population
        fitness_scores = self.rust_genetic.evaluate_population(self.population)

        # 2. Select parents (tournament selection)
        parents = self.rust_genetic.select_parents(fitness_scores, n=10)

        # 3. Generate mutations
        mutations = []
        for parent_pair in parents:
            if random.random() < 0.3:
                # Crossover
                child = self.rust_genetic.crossover(parent_pair)
            else:
                # Mutation
                child = self.rust_genetic.mutate(parent_pair[0])

            mutations.append(child)

        # 4. LLM proposes new strategies (every 4th evolution)
        if self._evolution_count % 4 == 0:
            llm_strategies = await self.llm_strategist.propose_strategies(
                current_pool=self.population.summary,
                recent_lessons=await self._get_recent_lessons(),
                current_regime=await self._get_current_regime(),
            )
            mutations.extend(llm_strategies)

        # 5. Backtest all candidates
        results = self.rust_backtest.batch_backtest(mutations, lookback_days=90)

        # 6. Publish viable mutations
        for mutation, result in zip(mutations, results):
            if result.sharpe > 1.0 and result.max_drawdown < 0.15:
                await self.publisher.publish(StrategyMutation(
                    mutation_type="parameter_change",
                    new_strategy_name=mutation.name,
                    strategy_definition=mutation.to_dict(),
                    backtest_results=result.to_dict(),
                    # ...
                ))
```

#### Error Handling

| Error | Response |
|-------|----------|
| Backtest engine failure | Skip candidate, continue with remaining |
| LLM proposes invalid strategy | Validate structure before backtesting, reject invalid |
| Population degeneracy | Inject random mutations to maintain diversity |
| Backtest overfitting | Use walk-forward validation, penalize complexity |

#### Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Single backtest (90 days) | <5s (Rust) | 15s |
| Full evolution cycle | <5min | 15min |
| Strategy synthesis (LLM) | <30s | 60s |
| Memory | <512MB | 1GB |

---

### 3.8 Market Cartographer

> *"Map cross-asset correlations"*

#### Role & Responsibility

Maintains a real-time map of relationships between all instruments in the universe. Tracks correlations, cointegrations, lead-lag relationships, and regime-dependent betas. This data feeds into Risk Guardian (for concentration checks), Signal Scout (for relative value signals), and Regime Detector (for correlation regime classification).

#### Relationship Types

| Type | Description | Use Case |
|------|-------------|----------|
| **Pearson correlation** | Linear price correlation | Risk concentration |
| **Rolling correlation** | Time-varying correlation | Detect regime shifts |
| **Cointegration** | Long-run equilibrium | Pairs trading signals |
| **Lead-lag** | One instrument predicts another | Signal generation |
| **Beta** | Sensitivity to benchmark | Position sizing |
| **Tail correlation** | Correlation during extreme events | Risk management |
| **Volatility spillover** | Vol transmission between assets | Regime detection |

#### Input Data

| Source | Data |
|--------|------|
| Market data | Price history for all instruments (1min to daily) |
| Regime Detector | Current regime (correlation behavior varies by regime) |
| Execution Tracker | Current positions (focus on held instruments) |

#### Output Format

```python
@dataclass(frozen=True)
class CorrelationMatrix:
    """Published to trading:cartography stream."""
    matrix_id: str
    timestamp: datetime
    timeframe: str                      # "1min" | "5min" | "1hour" | "daily"
    instruments: list[str]
    correlation_matrix: list[list[float]]  # NxN correlation matrix
    eigenvalues: list[float]            # PCA eigenvalues for dimensionality
    regime_context: str                 # Which regime this was computed in
    staleness_seconds: int              # How old the data is

@dataclass(frozen=True)
class RelationshipMap:
    """Full relationship map published periodically."""
    timestamp: datetime
    correlations: dict[str, CorrelationMatrix]  # By timeframe
    cointegrated_pairs: list[dict]      # Engle-Granger test results
    lead_lag_relationships: list[dict]  # Granger causality results
    beta_matrix: dict[str, dict]        # instrument → {benchmark: beta}
    tail_correlations: dict[str, float] # Crisis-mode correlations
    volatility_spillover: dict[str, dict]  # Vol transmission graph
    regime_betas: dict[str, dict]       # Betas conditional on regime
    regime_correlations: dict[str, dict]  # Correlations conditional on regime
    anomalies: list[str]                # Detected correlation breakdowns
```

#### Tools

| Tool | Tier | Purpose |
|------|------|---------|
| `rust_correlation_engine` | T0 | Fast correlation matrix computation |
| `rust_cointegration` | T0 | Engle-Granger, Johansen tests |
| `rust_pca` | T0 | Principal component analysis |
| `rust_granger` | T0 | Granger causality tests |
| `ollama_qwen` | T2 | Anomaly explanation, relationship narratives |

#### Model Tier

| Component | Tier | Model | Rationale |
|-----------|------|-------|-----------|
| All statistical computations | **T0 (Rust)** | Custom | Pure linear algebra, sub-second |
| Anomaly explanation | **T2 (LLM)** | Qwen2.5-7B | "Why did ES-NQ correlation break down?" |

#### Implementation Language

```
rust_cartography_engine/
├── src/
│   ├── lib.rs                  # PyO3 exports
│   ├── correlation.rs          # Pearson, Spearman, rolling correlation
│   ├── cointegration.rs        # Engle-Granger, Johansen
│   ├── pca.rs                  # Principal component analysis
│   ├── granger.rs              # Granger causality
│   ├── beta.rs                 # OLS beta calculation
│   ├── tail_correlation.rs     # Copula-based tail dependence
│   ├── spillover.rs            # Volatility spillover (Diebold-Yilmaz)
│   └── anomaly_detector.rs     # Correlation regime break detection

market_cartographer/
├── __init__.py
├── agent.py                    # Main agent loop (Python)
├── cartographer.py             # Orchestrates full map generation
├── llm_explainer.py            # Qwen anomaly explanations
└── publisher.py
```

**Split:** ~90% Rust (all statistical computation), ~10% Python (orchestration, LLM).

#### Communication Protocol

```
PUBLISHES TO:  trading:cartography
SUBSCRIBES TO: trading:regime (adjust computation focus),
               trading:fills (new positions → prioritize their correlations)
WRITES STATE:  trading:state:correlations
```

**Computation schedule:**
- Rolling correlations: every 1 minute
- Cointegration tests: every 1 hour
- Granger causality: every 4 hours
- Full regime-conditional analysis: on regime change

#### Lifecycle

```python
class MarketCartographerAgent:
    async def spawn(self):
        self.rust_corr = cartography_engine.CorrelationEngine()
        self.rust_coint = cartography_engine.CointegrationEngine()
        self.rust_pca = cartography_engine.PcaEngine()
        self.llm = OllamaClient(model="qwen2.5:7b")
        self.universe = await self._load_instrument_universe()

    async def run_loop(self):
        while not self.shutdown_event.is_set():
            now = time.time()

            # Fast path: rolling correlations every 1min
            if now - self.last_corr_update > 60:
                prices = await self._get_price_matrix(timeframe="1min", lookback=60)
                corr = self.rust_corr.rolling_correlation(prices, window=30)
                await self.publisher.publish(corr)
                self.last_corr_update = now

            # Medium path: cointegration every 1hr
            if now - self.last_coint_update > 3600:
                prices = await self._get_price_matrix(timeframe="1hour", lookback=500)
                pairs = self.rust_coint.engle_granger_test(prices)
                await self._publish_pairs(pairs)
                self.last_coint_update = now

            # Slow path: full analysis on regime change
            regime = await self.try_read_stream("trading:regime", last_only=True)
            if regime and regime != self.last_regime:
                await self._full_reanalysis(regime)
                self.last_regime = regime

            # Detect anomalies
            anomalies = self._detect_correlation_anomalies()
            if anomalies:
                for anomaly in anomalies:
                    explanation = await self.llm.explain_anomaly(anomaly)
                    await self.publisher.publish_anomaly(anomaly, explanation)

            await asyncio.sleep(5)

    async def die(self, reason: str):
        """Publish final state."""
        await self.redis.xadd("trading:health", {
            "agent": "market_cartographer", "status": "dying", "reason": reason
        })
```

#### Error Handling

| Error | Response |
|-------|----------|
| Insufficient data for test | Skip test, report `insufficient_data`, continue |
| Singular correlation matrix | Use shrinkage estimator (Ledoit-Wolf) |
| Numerical instability | Clamp values, flag `numerical_warning: true` |
| LLM timeout | Skip explanation, publish raw anomaly data |

#### Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Correlation matrix (100x100) | <10ms (Rust) | 25ms |
| Cointegration test (50 pairs) | <1s (Rust) | 3s |
| Full reanalysis | <30s (Rust) | 60s |
| Memory | <256MB | 512MB |

---

## 4. Model Routing Strategy

### Free-Tier-First Model Assignment

| Agent | Component | Tier | Model | Provider | Cost | Fallback |
|-------|-----------|------|-------|----------|------|----------|
| **Regime Detector** | Explanation | T2 | Qwen2.5-7B | Ollama (local) | Free | Skip explanation |
| **Signal Scout** | Filtering | T1 | XGBoost | Local Python | Free | Rule-based |
| **Signal Scout** | Narrative | T2 | Qwen2.5-7B | Ollama (local) | Free | Skip narrative |
| **Risk Guardian** | Edge case analysis | T3 | DeepSeek-R1 | NVIDIA API (free) | Free | Conservative VETO |
| **Risk Guardian** | Explanation | T2 | Qwen2.5-7B | Ollama (local) | Free | Skip explanation |
| **Execution Sniper** | — | T0 | — | — | — | No LLM needed |
| **Execution Tracker** | — | T0 | — | — | — | No LLM needed |
| **Trade Philosopher** | Trade narrative | T3 | DeepSeek-R1 | NVIDIA API (free) | Free | Quant-only analysis |
| **Trade Philosopher** | Quick summaries | T2 | Qwen2.5-7B | Ollama (local) | Free | Skip summary |
| **Strategy Geneticist** | Strategy synthesis | T3 | DeepSeek-R1 | NVIDIA API (free) | Free | Parameter-only evolution |
| **Strategy Geneticist** | Evaluation | T2 | Qwen2.5-7B | Ollama (local) | Free | Backtest-only eval |
| **Market Cartographer** | Anomaly explanation | T2 | Qwen2.5-7B | Ollama (local) | Free | Raw anomaly data |

### Model Routing Implementation

```python
class ModelRouter:
    """Routes LLM requests to the cheapest available model that can handle the task."""

    TIERS = {
        "t2_local": {
            "provider": "ollama",
            "model": "qwen2.5:7b",
            "max_tokens": 2048,
            "timeout_s": 10,
            "cost": 0,
        },
        "t3_free_nvidia": {
            "provider": "nvidia_nim",
            "model": "deepseek-ai/deepseek-r1",
            "max_tokens": 4096,
            "timeout_s": 30,
            "cost": 0,
            "rate_limit": "100/min",
        },
        "t3_free_deepseek": {
            "provider": "deepseek_api",
            "model": "deepseek-reasoner",
            "max_tokens": 4096,
            "timeout_s": 30,
            "cost": 0,
            "rate_limit": "10/min",
        },
        "t3_fallback": {
            "provider": "ollama",
            "model": "qwen2.5:32b",
            "max_tokens": 4096,
            "timeout_s": 60,
            "cost": 0,
        },
    }

    async def route(self, task_type: str, prompt: str) -> str:
        """Route to cheapest available model for the task type."""
        if task_type in ("explanation", "summary", "tagging"):
            tier = "t2_local"
        elif task_type in ("analysis", "synthesis", "reasoning"):
            tier = self._pick_t3_tier()
        else:
            tier = "t2_local"

        model_config = self.TIERS[tier]
        try:
            return await self._call_model(model_config, prompt)
        except (TimeoutError, RateLimitError):
            # Cascade to fallback
            fallback = self.TIERS.get(f"{tier}_fallback", self.TIERS["t2_local"])
            return await self._call_model(fallback, prompt)

    def _pick_t3_tier(self) -> str:
        """Pick T3 model based on rate limit availability."""
        if self._rate_limit_available("t3_free_nvidia"):
            return "t3_free_nvidia"
        elif self._rate_limit_available("t3_free_deepseek"):
            return "t3_free_deepseek"
        else:
            return "t3_fallback"  # Larger local model
```

### Why This Routing

- **T0 (Rust):** Anything touching money, latency, or determinism. No exceptions.
- **T1 (Python ML):** Statistical models that need training data. Local, free, fast.
- **T2 (Qwen2.5-7B local):** Explanations, summaries, tagging. Runs on any GPU. Always free.
- **T3 (DeepSeek-R1):** Complex reasoning. Free via NVIDIA NIM API. Rate-limited but sufficient.

---

## 5. Risk Guardian VETO Protocol

### 5.1 The VETO Lifecycle

```
Signal Scout                    Risk Guardian              Execution Sniper
     │                               │                           │
     │──signal────────────────────►│                           │
     │                               │                           │
     │                          ┌────┴────┐                     │
     │                          │ P0 CHECK │                     │
     │                          │ (kill sw)│                     │
     │                          └────┬────┘                     │
     │                               │                          │
     │                          ┌────┴────┐                     │
     │                          │ P1 CHECK │                     │
     │                          │ (concent)│                     │
     │                          └────┬────┘                     │
     │                               │                          │
     │                          ┌────┴────┐                     │
     │                          │ P2 CHECK │                     │
     │                          │ (regime) │                     │
     │                          └────┬────┘                     │
     │                               │                          │
     │                          ┌────┴────┐                     │
     │                          │ P3 CHECK │                     │
     │                          │ (edge)   │                     │
     │                          └────┬────┘                     │
     │                               │                          │
     │                               │──decision──────────────►│
     │                               │                          │
     │                               │                     ┌───┴───┐
     │                               │                     │RE-CHECK│ ◄── Sync
     │                               │◄────────────────────│ (50ms) │
     │                               │                     └───┬───┘
     │                               │                          │
     │                               │──final_verdict─────────►│
     │                               │                          │
     │                               │                          │──execute──► market
```

### 5.2 VETO Rules

```python
class VetoProtocol:
    """Hard rules that cannot be overridden."""

    # Rule 1: Risk Guardian must be online for ANY trading
    GUARDIAN_REQUIRED = True

    # Rule 2: If Guardian is offline, ALL orders are auto-rejected
    GUARDIAN_OFFLINE_ACTION = "reject_all"

    # Rule 3: VETO is absolute — no agent can override
    VETO_OVERRIDABLE = False

    # Rule 4: Timeout on synchronous check = VETO (conservative)
    SYNC_TIMEOUT_ACTION = "veto_with_warning"

    # Rule 5: Maximum one active VETO_ALL at a time
    VETO_ALL_MAX_DURATION = timedelta(minutes=30)

    # Rule 6: VETO_ALL requires human intervention to clear
    VETO_ALL_CLEAR = "manual_only"

    # Rule 7: Kill switch triggers auto-VETO_ALL for rest of day
    KILL_SWITCH_COOLDOWN = timedelta(hours=24)
```

### 5.3 VETO Severity Levels

| Level | Name | Scope | Auto-Clear |
|-------|------|-------|------------|
| V1 | **Trade VETO** | Single trade rejected | N/A (trade skipped) |
| V2 | **Strategy VETO** | All trades from one strategy paused | 1 hour |
| V3 | **Instrument VETO** | All trades in one instrument paused | 4 hours |
| V4 | **Sector VETO** | All trades in one sector paused | 1 hour |
| V5 | **VETO ALL** | All trading halted | Manual only |

### 5.4 VETO State Machine

```
                    ┌──────────┐
          ┌────────►│ TRADING  │◄────────┐
          │         │  NORMAL  │         │
          │         └────┬─────┘         │
          │              │               │
          │         V1-V4 VETO           │
          │              │               │
          │         ┌────▼─────┐         │
          │         │ PARTIAL  │         │
          │         │  HALT    │─────────┘ (auto-clear)
          │         └────┬─────┘
          │              │
          │         V5 (kill switch)
          │              │
          │         ┌────▼─────┐
          │         │ FULL     │
          └─────────│  HALT    │
          (manual   └──────────┘
           clear)
```

---

## 6. Error Handling & Graceful Degradation

### 6.1 Agent Failure Matrix

| Failed Agent | Impact on System | Degradation Strategy |
|-------------|-----------------|---------------------|
| **Regime Detector** | Signal Scout, Risk Guardian use stale regime | Use last known regime for up to 1hr, then pause new trades |
| **Signal Scout** | No new trades | Existing positions continue managing, no new entries |
| **Risk Guardian** | **ALL TRADING HALTS** | Immediate VETO_ALL, notify human |
| **Execution Sniper** | Approved signals can't execute | Queue approved signals, alert if queue > 10 |
| **Execution Tracker** | Positions unmonitored | Risk Guardian detects via stale position state, triggers VETO_ALL |
| **Trade Philosopher** | No learning | System continues trading, just doesn't improve |
| **Strategy Geneticist** | No strategy evolution | Current strategies continue, no new ones created |
| **Market Cartographer** | Correlation data stale | Use last known correlations for up to 4hr |

### 6.2 Supervisor Architecture

```python
class AgentSupervisor:
    """Orchestrator that manages all agent lifecycles."""

    CRITICAL_AGENTS = ["risk_guardian", "execution_tracker"]
    IMPORTANT_AGENTS = ["regime_detector", "signal_scout", "execution_sniper"]
    OPTIONAL_AGENTS = ["trade_philosopher", "strategy_geneticist", "market_cartographer"]

    async def supervise(self):
        while True:
            for agent_name, agent in self.agents.items():
                health = await self._check_health(agent_name)

                if health.status == "dead":
                    if agent_name in self.CRITICAL_AGENTS:
                        # Critical agent died — halt everything
                        await self._emergency_halt(f"{agent_name} died: {health.reason}")
                        await self._restart_agent(agent_name, priority="critical")
                    elif agent_name in self.IMPORTANT_AGENTS:
                        # Important agent died — restart, continue with degradation
                        await self._restart_agent(agent_name, priority="high")
                        await self._notify_degradation(agent_name)
                    else:
                        # Optional agent died — restart when convenient
                        await self._restart_agent(agent_name, priority="low")

                elif health.status == "degraded":
                    await self._notify_degradation(agent_name)

            await asyncio.sleep(5)  # Health check cadence

    async def emergency_halt(self, reason: str):
        """Nuclear option: stop all trading."""
        await self.redis.xadd("trading:risk_decisions", {
            "verdict": "veto_all",
            "reason": f"EMERGENCY HALT: {reason}",
            "ttl_seconds": 86400,  # 24 hours
        })
        # Alert human
        await self._send_alert(
            priority="CRITICAL",
            message=f"Trading halted: {reason}",
        )
```

### 6.3 Circuit Breakers

```python
CIRCUIT_BREAKERS = {
    "daily_loss_limit": {
        "trigger": "daily_pnl < -0.02 * capital",
        "action": "veto_all",
        "cooldown": "24h",
        "clear": "manual",
    },
    "max_drawdown": {
        "trigger": "drawdown_from_hwm > 0.05",
        "action": "veto_all",
        "cooldown": "4h",
        "clear": "manual",
    },
    "rapid_loss": {
        "trigger": "pnl_change < -0.01 in 5min",
        "action": "reduce_all_sizes_50%",
        "cooldown": "1h",
        "clear": "auto",
    },
    "correlation_spike": {
        "trigger": "avg_correlation > 0.85",
        "action": "reduce_all_sizes_25%",
        "cooldown": "30min",
        "clear": "auto",
    },
    "agent_cascade": {
        "trigger": "3+ agents degraded simultaneously",
        "action": "veto_new_trades",
        "cooldown": "1h",
        "clear": "auto",
    },
}
```

---

## 7. Testing Strategy

### 7.1 Test Pyramid

```
                    ┌─────────┐
                    │ E2E     │  5 tests — full system, paper trading
                    │ Tests   │
                    ├─────────┤
                    │ Integr. │  20 tests — agent pairs, event bus
                    │ Tests   │
                    ├─────────┤
                    │ Agent   │  50 tests — individual agent behavior
                    │ Tests   │
                    ├─────────┤
                    │ Unit    │  500+ tests — Rust engines, Python logic
                    │ Tests   │
                    └─────────┘
```

### 7.2 Agent Isolation Testing

Every agent must be testable with synthetic inputs:

```python
class AgentTestHarness:
    """Test any agent in isolation with synthetic data."""

    def __init__(self, agent_class):
        self.agent = agent_class()
        self.fake_redis = FakeRedis()
        self.agent.redis = self.fake_redis

    async def inject_message(self, stream: str, data: dict):
        """Simulate a message arriving on a stream."""
        await self.fake_redis.xadd(stream, data)

    async def capture_output(self, stream: str, timeout: float = 5.0) -> list[dict]:
        """Capture messages published by the agent."""
        messages = await self.fake_redis.xread({stream: "0"}, block=int(timeout * 1000))
        return [msg for _, msgs in messages for _, msg in msgs]

    async def run_scenario(self, inputs: list[tuple[str, dict]]) -> list[dict]:
        """Run a test scenario: inject inputs, capture outputs."""
        outputs = []
        for stream, data in inputs:
            await self.inject_message(stream, data)
            # Give agent time to process
            await asyncio.sleep(0.1)
            # Capture any outputs
            for out_stream in self.agent.publishes_to:
                outputs.extend(await self.capture_output(out_stream, timeout=0.5))
        return outputs
```

### 7.3 Risk Guardian VETO Testing

```python
class TestRiskGuardianVeto:
    """Critical: every VETO condition must be tested."""

    async def test_kill_switch_triggers_veto_all(self):
        """When daily P&L < -2%, ALL trades must be vetoed."""
        harness = AgentTestHarness(RiskGuardianAgent)
        await harness.agent.set_daily_pnl(-0.021)

        result = await harness.run_scenario([
            ("trading:signals", sample_signal()),
        ])

        assert result[0]["verdict"] == "veto"
        assert result[0]["veto_category"] == "kill_switch"

    async def test_concentration_limit_vetoes(self):
        """When single instrument > 15%, new trade in that instrument is vetoed."""
        harness = AgentTestHarness(RiskGuardianAgent)
        await harness.agent.set_position("ES", quantity=100, pct_of_capital=0.16)

        result = await harness.run_scenario([
            ("trading:signals", sample_signal(instrument="ES", direction="long")),
        ])

        assert result[0]["verdict"] == "veto"
        assert result[0]["veto_category"] == "concentration"

    async def test_guardian_offline_halts_trading(self):
        """If Risk Guardian process dies, all trading must halt."""
        # This is tested at the supervisor level
        supervisor = AgentSupervisor()
        await supervisor.simulate_agent_death("risk_guardian")

        risk_state = await supervisor.get_risk_state()
        assert risk_state["status"] == "veto_all"
        assert risk_state["reason"].contains("Risk Guardian offline")
```

### 7.4 Rust Engine Testing

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_garman_klass_volatility() {
        let ohlcv = vec![
            Ohlcv { open: 100.0, high: 105.0, low: 98.0, close: 103.0, volume: 1000.0 },
            Ohlcv { open: 103.0, high: 107.0, low: 101.0, close: 106.0, volume: 1200.0 },
            // ... 30 bars
        ];
        let vol = garman_klass_volatility(&ohlcv);
        assert!(vol > 0.0 && vol < 1.0);
        assert!(!vol.is_nan());
    }

    #[test]
    fn test_position_sizer_kelly() {
        let sizer = PositionSizer::new(KellyCriterion::half_kelly());
        let size = sizer.calculate(
            win_rate: 0.55,
            avg_win: 1.5,  // R-multiples
            avg_loss: 1.0,
            capital: 100_000.0,
            max_risk_pct: 0.02,
        );
        assert!(size > 0.0);
        assert!(size <= 100_000.0 * 0.02);  // Never risk more than 2%
    }

    #[test]
    fn test_correlation_matrix_positive_definite() {
        let prices = generate_random_prices(10, 100);  // 10 instruments, 100 bars
        let corr = CorrelationMatrix::compute(&prices, 30);
        assert!(corr.is_positive_definite());
        assert_eq!(corr.dimension(), 10);
    }
}
```

---

## 8. Performance Budgets

### 8.1 End-to-End Latency Budget

```
Signal Detection          ████░░░░░░░░░░░░░░░░  50ms
Risk Evaluation           ██░░░░░░░░░░░░░░░░░░  5ms
Risk Re-check (sync)      ██░░░░░░░░░░░░░░░░░░  5ms
Order Generation          █░░░░░░░░░░░░░░░░░░░  2ms
Broker Submission         █░░░░░░░░░░░░░░░░░░░  1ms
────────────────────────────────────────────────
TOTAL (critical path):    ████████░░░░░░░░░░░░  ~63ms
```

### 8.2 Resource Budgets Per Agent

| Agent | CPU | Memory | Disk I/O | Network |
|-------|-----|--------|----------|---------|
| Regime Detector | 10% | 256MB | Low | Low |
| Signal Scout | 25% | 512MB | Low | Medium |
| Risk Guardian | 20% | 256MB | Low | Medium |
| Execution Sniper | 5% | 128MB | Low | High |
| Execution Tracker | 5% | 256MB | Medium | Medium |
| Trade Philosopher | 15% | 512MB | Medium | Low |
| Strategy Geneticist | 30% | 1GB | High | Low |
| Market Cartographer | 20% | 512MB | Low | Low |
| **TOTAL** | **130%** | **3.5GB** | — | — |

*Note: 130% CPU = requires multi-core. Minimum 4 cores recommended.*

### 8.3 Redis Stream Throughput

| Stream | Messages/sec (normal) | Messages/sec (stress) | Retention |
|--------|----------------------|----------------------|-----------|
| trading:regime | 0.2 | 1 | 24h |
| trading:signals | 5 | 50 | 7d |
| trading:risk_decisions | 5 | 50 | 7d |
| trading:orders | 5 | 50 | 30d |
| trading:fills | 5 | 50 | 30d |
| trading:positions | 10 | 100 | 7d |
| trading:analytics | 0.1 | 1 | 90d |
| trading:cartography | 0.02 | 0.5 | 7d |
| trading:health | 1.6 | 8 | 24h |

---

## 9. PyO3 Bridge Interface

### 9.1 Core Rust Library Exports

```rust
// lib.rs — Main PyO3 module
use pyo3::prelude::*;

#[pymodule]
fn trading_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Regime detection
    m.add_class::<regime::RegimeClassifier>()?;

    // Signal generation
    m.add_class::<signals::IndicatorSuite>()?;
    m.add_class::<signals::UniverseScanner>()?;
    m.add_class::<signals::PatternDetector>()?;

    // Risk management
    m.add_class::<risk::RiskEngine>()?;
    m.add_class::<risk::PortfolioCalculator>()?;
    m.add_class::<risk::PositionSizer>()?;
    m.add_class::<risk::KillSwitch>()?;

    // Execution
    m.add_class::<execution::OrderRouter>()?;
    m.add_class::<execution::ExecutionEngine>()?;
    m.add_class::<execution::SlippageAnalyzer>()?;

    // Position tracking
    m.add_class::<tracker::PositionManager>()?;
    m.add_class::<tracker::PnlEngine>()?;
    m.add_class::<tracker::TrailingStop>()?;

    // Analytics
    m.add_class::<analytics::TradeAnalyzer>()?;
    m.add_class::<analytics::PatternAggregator>()?;

    // Genetic evolution
    m.add_class::<genetic::GeneticEngine>()?;
    m.add_class::<genetic::BacktestEngine>()?;

    // Cartography
    m.add_class::<cartography::CorrelationEngine>()?;
    m.add_class::<cartography::CointegrationEngine>()?;
    m.add_class::<cartography::PcaEngine>()?;

    Ok(())
}
```

### 9.2 Python-Side Type Stubs

```python
# trading_engine.pyi — Type hints for IDE support
class RegimeClassifier:
    def classify(self, snapshot: MarketSnapshot) -> RegimeReport: ...

class RiskEngine:
    def check_kill_switch(self, daily_pnl: float, hwm: float) -> bool: ...
    def check_concentration(self, signal: dict, portfolio: dict) -> CheckResult: ...
    def check_regime_compatibility(self, signal: dict, regime: dict) -> CheckResult: ...
    def check_edge_threshold(self, signal: dict) -> CheckResult: ...

class PositionSizer:
    def calculate(
        self,
        signal: dict,
        portfolio: dict,
        risk_multiplier: float,
    ) -> float: ...

class OrderRouter:
    def build_order(self, risk_decision: dict) -> Order: ...
    def select_strategy(self, order: Order, market: dict) -> str: ...

class BacktestEngine:
    def run(
        self,
        strategy: dict,
        price_data: dict,
        start: str,
        end: str,
    ) -> BacktestResult: ...
```

### 9.3 Data Transfer Protocol

All data crossing the PyO3 boundary uses **PyDict** with string keys (no custom Python objects crossing into Rust). This avoids GIL contention and serialization overhead.

```python
# Pattern: Python → Rust
classifier = trading_engine.RegimeClassifier()
snapshot_dict = {
    "prices": prices_numpy_array,      # numpy arrays pass by reference
    "volumes": volumes_numpy_array,
    "timestamp": time.time_ns(),
}
result_dict = classifier.classify(snapshot_dict)  # Returns dict

# Pattern: Rust → Python
result = RegimeReport(**result_dict)  # Construct Python dataclass from dict
```

---

## 10. Deployment Topology

### 10.1 Process Layout

```
┌─────────────────────────────────────────────────────────────┐
│                      Docker Compose / K8s                    │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ redis:7     │  │ ollama      │  │ duckdb      │         │
│  │ (event bus  │  │ (local LLM) │  │ (analytics  │         │
│  │  + state)   │  │             │  │  store)     │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ regime      │  │ signal      │  │ risk        │         │
│  │ detector    │  │ scout       │  │ guardian    │  ◄ CRIT  │
│  │ (1 proc)    │  │ (1 proc)    │  │ (1 proc)    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ execution   │  │ execution   │  │ trade       │         │
│  │ sniper      │  │ tracker     │  │ philosopher │         │
│  │ (1 proc)    │  │ (1 proc)    │  │ (1 proc)    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ strategy    │  │ market      │  │ supervisor  │         │
│  │ geneticist  │  │ cartographer│  │ (orchestr.) │         │
│  │ (1 proc)    │  │ (1 proc)    │  │ (1 proc)    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                              │
│  ┌───────────────────────────────────────────────┐          │
│  │ Grafana + Prometheus (monitoring)              │          │
│  └───────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 Minimum Hardware

| Component | Specification |
|-----------|--------------|
| CPU | 4 cores (8 recommended) |
| RAM | 8GB (16GB recommended) |
| GPU | Optional — for Ollama with larger models |
| Disk | 50GB SSD |
| Network | Low-latency connection to broker/exchange |

### 10.3 Scaling Strategy

- **Horizontal:** Multiple Signal Scout instances per instrument group
- **Vertical:** Strategy Geneticist benefits from more CPU/RAM for backtesting
- **Risk Guardian:** ALWAYS single instance (no split-brain risk)

---

## Appendix A: Message Schema Registry

All message schemas are versioned and backward-compatible:

```python
SCHEMA_REGISTRY = {
    "regime_report": {
        1: RegimeReportV1,
        2: RegimeReportV2,  # Added dimension_confidences
    },
    "trading_signal": {
        1: TradingSignalV1,
    },
    "risk_decision": {
        1: RiskDecisionV1,
    },
    "order_command": {
        1: OrderCommandV1,
    },
    # ... etc
}
```

## Appendix B: Configuration Hierarchy

```
config/
├── defaults.toml           # System-wide defaults
├── risk_limits.toml        # Risk Guardian hard limits (NEVER auto-modified)
├── strategies/             # Strategy-specific configs
│   ├── mean_reversion.toml
│   ├── momentum.toml
│   └── volatility.toml
├── instruments/            # Per-instrument configs
│   ├── ES.toml
│   ├── NQ.toml
│   └── BTC.toml
└── environments/
    ├── paper.toml          # Paper trading overrides
    ├── staging.toml        # Staging overrides
    └── production.toml     # Production overrides (human-editable)
```

## Appendix C: Agent Startup Order

```
1. Redis (infrastructure)
2. Supervisor (orchestrator)
3. Market Cartographer (data foundation)
4. Regime Detector (needs cartography data)
5. Execution Tracker (position state must exist before Risk Guardian)
6. Risk Guardian (needs position state)
7. Signal Scout (needs regime + risk guardian online)
8. Execution Sniper (needs risk guardian online)
9. Trade Philosopher (optional, can start anytime)
10. Strategy Geneticist (optional, can start anytime)
```

**Hard dependency:** Signal Scout and Execution Sniper will NOT start until Risk Guardian confirms it is online and has loaded current portfolio state.

---

*End of specification. This document defines the complete architecture for institutional-grade autonomous trading with 8 specialized sub-agents, deterministic execution via Rust, intelligent reasoning via free-tier LLMs, and risk-first design with an absolute VETO protocol.*
