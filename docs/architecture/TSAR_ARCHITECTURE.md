# TSAR — TRADING SUPER AGENT REGIME
## CANONICAL ARCHITECTURE — SINGLE SOURCE OF TRUTH

**Version:** 3.0.0
**Date:** 2026-07-24
**Authority:** This document is the CANONICAL architecture. All engineering references this document. Where any prior document conflicts, this document wins.
**Status:** FINAL — Approved for Engineering
**Languages:** Python 3.12 + Rust 1.79 + C++ (Level 4+)

---

## TABLE OF CONTENTS

1. [System Overview](#1-system-overview)
2. [The Interface Layer](#2-the-interface-layer)
3. [Agent Architecture](#3-agent-architecture)
4. [Knowledge Stores](#4-knowledge-stores)
5. [Communication Protocol (CloudEvents)](#5-communication-protocol-cloudevents)
6. [Risk Architecture (Hardened)](#6-risk-architecture-hardened)
7. [Strategy Architecture](#7-strategy-architecture)
8. [LLM Architecture (Model-Agnostic)](#8-llm-architecture-model-agnostic)
9. [Improvement Measurement](#9-improvement-measurement)
10. [Resource Management](#10-resource-management)
11. [Deployment Architecture](#11-deployment-architecture)
12. [Scaling Path (Day1 → Level 5)](#12-scaling-path-day1--level-5)

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
| **Proprietary Knowledge** | 5 knowledge stores that compound over time |
| **Learning Loop** | TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT cycle |
| **Flywheel** | Every trade generates data → insights → better strategies → better trades |
| **Harness** | Risk, execution, and monitoring are deterministic subsystems the intelligence layer cannot override |

### 1.3 Architectural Principles

| Principle | Implementation |
|-----------|---------------|
| **Interface-first** | 5 abstract base classes define all contracts. Agents never import concrete backends. |
| **Config-driven** | `config/backends.yaml` selects implementations. `config/models.yaml` selects LLM models. |
| **Python orchestrates** | All interfaces are Python ABCs. Rust/C++ backends are loaded via PyO3/pybind11. |
| **No direct Rust↔C++** | Python mediates all cross-module communication. |
| **CloudEvents standard** | All inter-agent messages use CNCF CloudEvents v1.0. |
| **Model-agnostic LLM** | Zero model names in source code. All routing via task_type. |
| **Observable** | Every interface method instrumented. Every LLM call tracked. |
| **Fail-safe** | Kill switch survives Redis failure. Watchdog monitors the monitors. |

### 1.4 Capital & Scaling Path

| Stage | Capital | Agents | Strategies | Markets | Backend |
|-------|---------|--------|------------|---------|---------|
| **Day1** | $10 | 3 | 1 (Mean Reversion) | BTC/USDT | Python (ccxt) |
| **Level 2** | $10-100 | 4 | 2 (MR + Momentum) | BTC, ETH | + Rust WebSocket |
| **Level 3** | $100-1K | 10 | 3-5 | Crypto + Forex | + Rust tick engine |
| **Level 4** | $1K-10K | 10 | 5+ | Multi-asset | + C++ FIX/QuantLib |
| **Level 5** | $10K+ | 10 | 5+ | Multi-asset | + GPU Monte Carlo |

### 1.5 Institutional Grade (8-Layer Coverage)

| Layer | Day1 | Full | Target |
|-------|------|------|--------|
| 1. Market Analysis | 15% | 85% | 90%+ |
| 2. Strategy & Portfolio | 30% | 75% | 85%+ |
| 3. Execution | 40% | 80% | 90%+ |
| 4. Risk Management | 85% | 95% | 95%+ |
| 5. Data Infrastructure | 35% | 70% | 80%+ |
| 6. Operations | 25% | 65% | 80%+ |
| 7. Compliance | 30% | 60% | 80%+ |
| 8. Portfolio Management | 15% | 55% | 75%+ |

### 1.6 Tech Stack

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | **3.12** | Primary language, orchestration |
| Rust | **1.79** | Execution engine, streaming, tick processing |
| C++ | — | FIX protocol, QuantLib (Level 4+) |
| SQLite | 3.40+ | Primary database (`tsar.db`) |
| Redis | 7.0+ | State, cache, streams |
| Node.js | 22 LTS | OpenClaw gateway |

**Key Python Dependencies:** ccxt, pandas, pandas-ta, numpy, ollama, openai, anthropic, redis, pydantic, vectorbt (Level 2+)

**Key Rust Dependencies:** tokio, tokio-tungstenite, pyo3, serde, tonic

---

## 2. THE INTERFACE LAYER

### 2.1 Philosophy

> "Design the interface from Day 1. Swap the backend later. Never refactor agent code."

Every Python interface is designed so calling code never knows whether the implementation is Python, Rust, or C++. The interface is the contract. The backend is an implementation detail.

### 2.2 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AGENT LAYER                                   │
│  Signal Scout · Risk Guardian · Execution Sniper · Philosopher · …   │
│  Agents call: get_exchange_gateway(), get_pricing_engine(), etc.     │
│  Agents NEVER import: ccxt, pandas-ta, QuantLib, quickfix           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    INTERFACE LAYER (src/interfaces/)                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────┐│
│  │ ExchangeGateway  │  │ PricingEngine   │  │ ExecutionEngine      ││
│  │ (ABC)            │  │ (ABC)           │  │ (ABC)                ││
│  └────────┬────────┘  └────────┬────────┘  └──────────┬───────────┘│
│  ┌────────┴────────┐  ┌───────┴─────────┐  ┌─────────┴───────────┐│
│  │ RiskEngine       │  │ LLMProvider     │  │ BackendRegistry     ││
│  │ (ABC)            │  │ (ABC)           │  │ (config + discovery) ││
│  └────────┬────────┘  └───────┬─────────┘  └─────────────────────┘│
└───────────┼───────────────────┼────────────────────────────────────┘
            │                   │
            ▼                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    BACKEND REGISTRY                                  │
│  config/backends.yaml                                                │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │ exchange_gateway:                                               ││
│  │   primary: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"  ││
│  │   fallback: ["src.interfaces.exchange.rust_gateway.RustGateway"]││
│  │ pricing_engine:                                                 ││
│  │   primary: "src.interfaces.pricing.pandas_ta_engine.PandasTA"  ││
│  │   fallback: ["src.interfaces.pricing.rust_tick_engine.RustTick"]││
│  └─────────────────────────────────────────────────────────────────┘│
└──────────────────────────────┬──────────────────────────────────────┘
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  DAY 1           │ │  LEVEL 2         │ │  LEVEL 4         │
│  Python Backends │ │  Rust Backends   │ │  C++ Backends    │
│  • CcxtGateway   │ │  • RustWsGateway │ │  • FixGateway    │
│  • PandasTAEngine│ │  • RustTickEngine│ │  • QuantLibEngine│
│  • CcxtExecEngine│ │  • RustExecEngine│ │  • FixExecEngine │
│  • PyRiskEngine  │ │  • RustRiskEngine│ │  • GpuMonteCarlo │
│  • OllamaProvider│ │  • LiteLLMRouter │ │                  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

### 2.3 BackendRegistry — Central Discovery Engine

The `BackendRegistry` is the single source of truth for which implementation backs each interface.

```python
# src/interfaces/registry.py — Key API

class BackendRegistry:
    def register(self, interface_name, backend_class, priority=100, config=None, tags=None): ...
    def load_from_config(self, config_path): ...
    def create(self, interface_name, **override_config): ...
    def create_with_fallback(self, interface_name, **override_config): ...
    def swap(self, interface_name, new_backend_class): ...  # Hot-swap at runtime
    def unswap(self, interface_name): ...
    def record_call(self, interface_name, backend_path, latency_ms, error=False): ...
    def get_metrics(self, interface_name=None): ...
    def get_status(self): ...

# Convenience getters — what agents actually call
def get_exchange_gateway(**config) -> ExchangeGateway: ...
def get_pricing_engine(**config) -> PricingEngine: ...
def get_execution_engine(**config) -> ExecutionEngine: ...
def get_risk_engine(**config) -> RiskEngine: ...
def get_llm_provider(**config) -> LLMProvider: ...
```

**Config format (`config/backends.yaml`):**
```yaml
exchange_gateway:
  primary: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
  fallback:
    - path: "src.interfaces.exchange.rust_gateway.RustGateway"
      priority: 200
  config:
    sandbox: true
pricing_engine:
  primary: "src.interfaces.pricing.pandas_ta_engine.PandasTA"
  fallback:
    - path: "src.interfaces.pricing.rust_tick_engine.RustTick"
      priority: 200
```

**FallbackProxy:** Wraps multiple backend instances with automatic failover. If primary raises a retryable error, falls back to next priority.

**InstrumentedBackend:** Wraps any backend with metrics collection — latency, errors, call counts.

### 2.4 ExchangeGateway (ABC)

Abstracts all exchange connectivity. Day1 uses ccxt. Level 2 swaps in Rust WebSocket. Level 4 swaps in C++ FIX.

```python
class ExchangeGateway(ABC):
    # Lifecycle
    async def connect(self): ...
    async def disconnect(self): ...
    @property
    def connection_status(self) -> ConnectionStatus: ...

    # Market Data (Read)
    async def get_price(self, symbol: str) -> float: ...
    async def get_ticker(self, symbol: str) -> Ticker: ...
    async def get_ohlcv(self, symbol, timeframe="1h", limit=100, since=None) -> list[OHLCV]: ...
    async def get_orderbook(self, symbol, depth=20) -> OrderBook: ...
    async def get_recent_trades(self, symbol, limit=50) -> list[Trade]: ...

    # Streaming (Real-time)
    async def subscribe(self, symbol, stream_type, callback) -> StreamHandle: ...
    async def unsubscribe(self, handle): ...

    # Account (Read)
    async def get_balance(self) -> Balance: ...
    async def get_positions(self) -> list[Position]: ...

    # Order Management (Write)
    async def place_order(self, symbol, side, order_type, quantity, price=None, ...) -> OrderResult: ...
    async def cancel_order(self, order_id, symbol) -> bool: ...
    async def get_order(self, order_id, symbol) -> OrderResult: ...
    async def get_open_orders(self, symbol=None) -> list[OrderResult]: ...
```

**Data Types:** `Ticker`, `OHLCV`, `OrderBook`, `Trade`, `OrderResult`, `Position`, `Balance`, `StreamHandle`, `OrderSide`, `OrderType`, `OrderStatus`, `TimeInForce`, `ConnectionStatus`

**Day1 Implementation:** `CcxtGateway` — ccxt REST API with polling-based streaming.
**Level 2 Placeholder:** `RustWsGateway` — Rust tokio-tungstenite WebSocket via PyO3.
**Level 4 Placeholder:** `FixGateway` — C++ QuickFIX via pybind11.

### 2.5 PricingEngine (ABC)

Abstracts all quantitative computation — indicators, Greeks, OHLCV aggregation.

```python
class PricingEngine(ABC):
    def calculate_indicator(self, name: str, **params) -> IndicatorResult: ...
    def calculate_greeks(self, option: OptionType) -> Greeks: ...
    def aggregate_ohlcv(self, ticks, target_timeframe) -> list[OHLCVBar]: ...
    # Convenience methods (non-abstract)
    def calculate_rsi(self, closes, period=14) -> float: ...
    def calculate_ema(self, closes, period=20) -> float: ...
    def calculate_atr(self, highs, lows, closes, period=14) -> float: ...
```

**Day1:** `PandasTAEngine` — pandas-ta + numpy.
**Level 2:** `RustTickEngine` — Rust OHLCV aggregation (10-100x faster), pandas-ta for indicators.
**Level 3:** `QuantLibEngine` — C++ QuantLib for exotic options and Monte Carlo.

### 2.6 ExecutionEngine (ABC)

Abstracts order execution — from simple REST to smart order routing to FIX.

```python
class ExecutionEngine(ABC):
    async def execute_order(self, request: OrderRequest) -> OrderResult: ...
    async def cancel_order(self, order_id, symbol) -> bool: ...
    async def get_fills(self, order_id, symbol) -> list[Fill]: ...
    def calculate_slippage(self, expected_price, fills) -> SlippageReport: ...
    # Advanced (Level 2+) — with Day1 fallbacks
    async def execute_twap(self, request, duration_seconds, slices) -> ExecutionResult: ...
    async def execute_vwap(self, request, participation_rate=0.1) -> ExecutionResult: ...
    async def get_open_orders(self, symbol=None) -> list[OrderResult]: ...
    async def get_order_status(self, order_id, symbol) -> OrderResult: ...
```

**Day1:** `CcxtExecEngine` — delegates to ExchangeGateway.
**Level 2:** `RustExecEngine` — Rust order executor via PyO3.
**Level 4:** `FixExecEngine` — C++ QuickFIX.

### 2.7 RiskEngine (ABC)

Abstracts all risk computation — position sizing, drawdown tracking, Monte Carlo. All risk rules are deterministic. No LLM involvement.

```python
class RiskEngine(ABC):
    def check_risk(self, symbol, side, entry_price, stop_loss, take_profit,
                   signal_score, current_equity, open_positions, daily_pnl, **kwargs) -> RiskCheckResult: ...
    def calculate_position_size(self, equity, risk_pct, entry_price, stop_loss,
                                method="half_kelly", **kwargs) -> PositionSizeResult: ...
    def get_drawdown_state(self, current_equity, high_water_mark, daily_pnl,
                           daily_loss_limit_pct=2.0, max_drawdown_pct=5.0) -> DrawdownState: ...
    # Level 3+
    async def run_stress_test(self, positions, scenarios=None) -> list[StressTestResult]: ...
```

**Day1:** `PyRiskEngine` — Python deterministic rule-based.
**Level 2:** `RustRiskEngine` — Rust-accelerated via PyO3.
**Level 5:** `GpuMonteCarloEngine` — CUDA Monte Carlo for VaR.

### 2.8 LLMProvider (ABC)

Abstracts all LLM calls. No direct provider SDK calls anywhere in the codebase. See [§8 LLM Architecture](#8-llm-architecture-model-agnostic) for full specification.

```python
class BaseLLMProvider(ABC):
    async def initialize(self): ...
    async def shutdown(self): ...
    async def generate(self, request: LLMRequest) -> LLMResponse: ...
    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]: ...
    def count_tokens(self, text, model=None) -> int: ...
    def get_capabilities(self, model) -> ModelCapabilities: ...
    async def health_check(self) -> bool: ...
```

**Implementations:** `OllamaProvider`, `OpenAIProvider`, `AnthropicProvider`, `DeepSeekProvider`

### 2.9 What Agents See

```python
# Agent code — NOW and FOREVER
from src.interfaces import get_exchange_gateway, get_pricing_engine

gateway = get_exchange_gateway()      # Returns the configured backend
price = await gateway.get_price("BTC/USDT")   # Same call whether Python, Rust, or C++

engine = get_pricing_engine()
rsi = engine.calculate_indicator("rsi", closes=closes, period=14)
```

Agents **never** know if `gateway` is `ccxt` (Day1), a Rust WebSocket client (Level 2), or a C++ FIX engine (Level 4). The interface is identical.

---

## 3. AGENT ARCHITECTURE

### 3.1 Agent Registry (Canonical)

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

### 3.2 Agent Communication Protocol

**Transport:** Redis Streams
**Prefix:** `tsar:stream:*` (canonical)
**Format:** CloudEvents v1.0 envelope with MessagePack binary payload (see §5)

### 3.3 Stream Topology

```
Stream Name                    CloudEvents Types               Producers           Consumers
──────────────────────────────────────────────────────────────────────────────────────────────
tsar:stream:regime             tsar.regime.changed,            Regime Detector     Signal Scout, Risk Guardian,
                               tsar.regime.updated                                 Strategy Geneticist,
                                                                                   Market Cartographer

tsar:stream:signals            tsar.signal.detected,           Signal Scout        Risk Guardian, Strategy
                               tsar.signal.expired                                 Geneticist

tsar:stream:risk_decisions     tsar.risk.decision,             Risk Guardian       Execution Sniper, Trade
                               tsar.risk.veto,                                     Philosopher
                               tsar.risk.veto_all

tsar:stream:orders             tsar.order.placed,              Execution Sniper    Execution Tracker
                               tsar.order.filled,
                               tsar.order.cancelled

tsar:stream:fills              tsar.fill.executed,             Execution Tracker   Trade Philosopher,
                               tsar.fill.partial                                   Risk Guardian,
                                                                                   Market Cartographer

tsar:stream:positions          tsar.position.updated,          Execution Tracker   Risk Guardian,
                               tsar.position.closed,                               Trade Philosopher,
                               tsar.position.snapshot                              Strategy Geneticist

tsar:stream:analytics          tsar.analytics.trade_completed, Trade Philosopher   Strategy Geneticist,
                               tsar.analytics.pattern_report                       Regime Detector

tsar:stream:cartography        tsar.cartography.correlation_updated, Market        Regime Detector,
                               tsar.cartography.anomaly_detected    Cartographer   Signal Scout, Risk Guardian

tsar:stream:strategy_mutations tsar.strategy.mutated,          Strategy Geneticist Signal Scout
                               tsar.strategy.retired

tsar:stream:health             tsar.health.heartbeat,          ALL agents          Orchestrator
                               tsar.health.error,
                               tsar.health.shutdown

tsar:stream:macro              tsar.macro.regime_update        Macro Agent         Signal Scout, Risk Guardian,
                                                                                   Regime Detector

tsar:stream:sentiment          tsar.macro.sentiment_update     Macro Agent         Signal Scout, Risk Guardian

tsar:stream:onchain            tsar.macro.onchain_update       Macro Agent         Signal Scout

tsar:stream:risk_requests      tsar.risk.approval_request      Execution Sniper    Risk Guardian
tsar:stream:risk_reply:*       tsar.risk.approval_response     Risk Guardian       Execution Sniper
```

### 3.4 Agent Specifications

#### Agent 1: Signal Scout

**Purpose:** Scan markets for mean reversion setups. Score each setup 0-1.
**Cycle:** Every 5 minutes (configurable)
**Model Tier:** T0 (math) + T2 (task: `t2_signal_narrative`) + T3 (task: `t3_risk_scenario` for ambiguous)

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

**Output:** `Signal` with signal, symbol, score (0-1), entry_price, stop_loss, take_profit, reasoning, sentiment_score, macro_alignment, timestamp.

**Subscribes to:** `tsar:stream:regime`, `tsar:stream:strategy_mutations`, `tsar:stream:cartography`
**Publishes to:** `tsar:stream:signals`

#### Agent 2: Risk Guardian

**Purpose:** Gatekeeper. Approves or rejects every trade signal. Pure rule-based — no LLM. Deterministic.

**Evaluation Checklist (ALL must pass):**
1. Position size ≤ 5% of account balance (Day1) / 15% (Level 2+)
2. Daily P&L not below -2% loss limit (**CANONICAL**)
3. Open positions < 10 (**CANONICAL**, Day1: 3)
4. Stop-loss is set and reasonable (≤ 2% from entry)
5. Risk-reward ratio ≥ 2:1
6. Not trading same symbol within cooldown (30 min)
7. No conflicting positions
8. Economic calendar blackout check
9. Geopolitical risk check
10. Macro regime alignment check

**Position Sizing:** Fixed 0.25 fraction, hard-capped at 2% per trade.

**Risk Limits (Canonical):**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Daily loss kill switch | **-2%** of capital | Conservative for $10 |
| Max drawdown (HWM) | **5%** | Halt all trading |
| Max open positions | **10** (Day1: 3) | Solo dev monitoring capacity |
| Max single position | **15%** of capital | Concentration limit |
| Max sector concentration | **30%** of capital | Sector limit |
| Max correlation | **0.7** | New trade correlation to portfolio |
| Kelly fraction | **0.25** (fixed) | Conservative sizing |
| Max daily trades | **30** | Prevent overtrading |
| Min risk-reward | **2:1** | Winners must be 2x losers |

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

**Kill Switch:** Dual-write to Redis + file (`/tmp/tsar_kill_switch`). File is primary safety net — survives Redis failure. See §6.2.

**Subscribes to:** `tsar:stream:signals`, `tsar:stream:fills`, `tsar:stream:positions`, `tsar:stream:macro`, `tsar:stream:cartography`
**Publishes to:** `tsar:stream:risk_decisions`, `tsar:stream:risk_reply:*`

#### Agent 3: Execution Sniper

**Purpose:** Place orders, manage stop-losses, track positions, close trades.
**Model Tier:** None. Pure execution logic.

**Order Lifecycle:**
1. RECEIVE approved signal from Risk Guardian
2. VALIDATE order parameters
3. PLACE market/limit order via `ExecutionEngine`
4. PLACE stop-loss order immediately after fill
5. PLACE take-profit order
6. MONITOR position every 1 minute
7. CLOSE position → calculate P&L → log to DB
8. NOTIFY via Telegram

**Subscribes to:** `tsar:stream:risk_decisions`
**Publishes to:** `tsar:stream:orders`, `tsar:stream:risk_requests`

#### Agent 4: Macro Agent (Level 2+)

**Purpose:** Analyze macroeconomic environment. Produce macro regime score.
**Model Tier:** T0 (indicator computation) + T2 (task: `t2_news_sentiment`) + T3 (task: `t3_risk_scenario` for crisis)

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

**Subscribes to:** `tsar:stream:regime`
**Publishes to:** `tsar:stream:macro`, `tsar:stream:sentiment`, `tsar:stream:onchain`

#### Agent 5: Regime Detector (Level 3+)

**Purpose:** Classify market regime using Hidden Markov Model.
**Model Tier:** T0 (HMM math) + T1 (scikit-learn)

**Regime States:** Trending Up, Trending Down, Ranging, Volatile, Breakout

**Subscribes to:** `tsar:stream:cartography`
**Publishes to:** `tsar:stream:regime`

#### Agent 6: Trade Philosopher (Level 3+)

**Purpose:** Post-trade reflection. Generate lessons. Feed learning loop.
**Model Tier:** T2 (task: `t2_trade_summary` for routine) + T3 (task: `t3_trade_narrative` for deep analysis)

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
**Model Tier:** T0 (backtesting math) + T2 (task: `t2_strategy_evaluation`) + T3 (task: `t3_strategy_synthesis`)

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

### 3.5 Tools (35 Canonical)

| # | Tool | Category | Owner Agent | Day1 |
|---|------|----------|-------------|------|
| 1 | `get_price` | Exchange | Signal Scout | ✅ |
| 2 | `get_ohlcv` | Exchange | Signal Scout | ✅ |
| 3 | `get_orderbook` | Exchange | Signal Scout | — |
| 4 | `place_order` | Exchange | Execution Sniper | ✅ |
| 5 | `cancel_order` | Exchange | Execution Sniper | ✅ |
| 6 | `get_positions` | Exchange | Execution Sniper | ✅ |
| 7 | `get_balance` | Exchange | Execution Sniper | ✅ |
| 8 | `get_funding_rate` | Exchange | Risk Guardian | — |
| 9 | `calculate_rsi` | Analysis | Signal Scout | ✅ |
| 10 | `calculate_macd` | Analysis | Signal Scout | — |
| 11 | `calculate_bollinger` | Analysis | Signal Scout | — |
| 12 | `calculate_atr` | Analysis | Signal Scout | — |
| 13 | `calculate_ema` | Analysis | Signal Scout | — |
| 14 | `calculate_volume_profile` | Analysis | Signal Scout | — |
| 15 | `detect_patterns` | Analysis | Signal Scout | — |
| 16 | `stream_prices` | Data | Orchestrator | — |
| 17 | `stream_orderbook` | Data | Orchestrator | — |
| 18 | `fetch_news` | Data | Macro Agent | — |
| 19 | `fetch_social_sentiment` | Data | Macro Agent | — |
| 20 | `fetch_onchain_data` | Data | Macro Agent | — |
| 21 | `fetch_macro_calendar` | Data | Macro Agent | — |
| 22 | `check_position_limits` | Risk | Risk Guardian | ✅ |
| 23 | `calculate_position_size` | Risk | Risk Guardian | ✅ |
| 24 | `get_portfolio_exposure` | Risk | Risk Guardian | — |
| 25 | `get_correlation_matrix` | Risk | Market Cartographer | — |
| 26 | `get_drawdown_stats` | Risk | Risk Guardian | — |
| 27 | `log_trade` | Memory | Execution Sniper | ✅ |
| 28 | `search_trades` | Memory | Trade Philosopher | — |
| 29 | `get_strategy_performance` | Memory | Strategy Geneticist | — |
| 30 | `get_lesson` | Memory | Trade Philosopher | — |
| 31 | `update_regime_state` | Memory | Regime Detector | — |
| 32 | `smart_order_router` | Execution | Execution Sniper | — |
| 33 | `calculate_slippage` | Execution | Execution Tracker | — |
| 34 | `twap_execute` | Execution | Execution Sniper | — |
| 35 | `monitor_fills` | Execution | Execution Tracker | — |

**Tool Permission Matrix:**

| Role | Exchange | Analysis | Data | Risk | Memory | Execution |
|------|----------|----------|------|------|--------|-----------|
| **READ** | get_price, get_balance, get_positions | All | All | get_drawdown_stats | search_trades, get_lesson | calculate_slippage |
| **ANALYSIS** | READ + get_ohlcv, get_orderbook | All | All | All READ | All | calculate_slippage |
| **TRADE_PREVIEW** | ANALYSIS + (no writes) | All | All | All | All | calculate_slippage |
| **TRADE_EXECUTE** | All | All | All | All | All | All |
| **TRADE_ADMIN** | All | All | All | All | All | All |

### 3.6 Dual-Language Architecture

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

## 4. KNOWLEDGE STORES

### 4.1 Store 1: Trade Memory (`trade_*` tables in tsar.db)

**Purpose:** Every trade — entry, exit, context, outcome, reflection — stored permanently.

**Schema:**
```
trade_records:
  id: INTEGER PRIMARY KEY
  trade_id: TEXT UNIQUE NOT NULL
  symbol: TEXT NOT NULL
  side: TEXT NOT NULL
  entry_price: REAL
  exit_price: REAL
  quantity: REAL NOT NULL
  stop_loss: REAL NOT NULL
  take_profit: REAL NOT NULL
  status: TEXT DEFAULT 'OPEN'
  pnl: REAL DEFAULT 0.0
  pnl_pct: REAL DEFAULT 0.0
  signal_score: REAL
  strategy: TEXT NOT NULL
  exchange_order_id: TEXT
  trading_mode: TEXT DEFAULT 'paper'
  regime_at_entry: TEXT
  max_favorable_excursion: REAL
  max_adverse_excursion: REAL
  slippage_bps: REAL
  commission: REAL
  notes: TEXT
  opened_at: TIMESTAMP
  closed_at: TIMESTAMP
```

**Retention:** Permanent (7+ years)

### 4.2 Store 2: Strategy Genomes (`strategy_*` tables in tsar.db)

**Purpose:** Living, evolving strategy definitions with performance stats per regime.

**Schema:**
```
strategy_genomes:
  id, name (UNIQUE), version, thesis, entry_rules (JSON),
  exit_rules (JSON), risk_params (JSON), regime_performance (JSON),
  status (ACTIVE|PAUSED|RETIRED), created_at, last_evolved

strategy_performance:
  id, strategy_name, total_trades, winning_trades, total_pnl,
  win_rate, sharpe_ratio, max_drawdown, rolling_sharpe_30d, last_updated

strategy_mutations:
  id, strategy_name, version_from, version_to, change_description,
  rationale, performance_before (JSON), performance_after (JSON), created_at
```

### 4.3 Store 3: Pattern Library (`pattern_*` tables in tsar.db)

**Purpose:** Discovered market patterns with occurrence counts and success rates.

**Schema:**
```
patterns:
  id, pattern_type (candlestick|structural|regime), description,
  conditions (JSON), occurrences, success_rate, avg_pnl_impact,
  confidence, discovered_at, last_seen

pattern_observations:
  id, pattern_id (FK), trade_id (FK), outcome (WIN|LOSS), pnl_impact

pattern_relationships:
  id, pattern_a_id, pattern_b_id, relationship (co-occurs|precedes|contradicts), strength
```

### 4.4 Store 4: Lesson Archive (`lesson_*` tables in tsar.db)

**Purpose:** Extracted lessons from trade outcomes. Searchable via FTS5.

**Schema:**
```
lessons:
  id, trade_id (FK), lesson_type (WIN|LOSS|MISTAKE|INSIGHT),
  category (ENTRY|EXIT|SIZING|TIMING|REGIME), description,
  action_item, applied (0|1), confidence, created_at

lesson_applications:
  id, lesson_id (FK), strategy_name, parameter_changed,
  old_value, new_value, impact_measured, applied_at

lesson_violations:
  id, lesson_id (FK), trade_id (FK), violation_description, occurred_at
```

**FTS5 Index:** `lessons_fts` on description, action_item

### 4.5 Store 5: Regime History (`regime_history` table in tsar.db)

**Purpose:** Historical regime classifications for backtesting and analysis.

**Schema:**
```
regime_history:
  snapshot_id (PK), snapshot_date, regime_probs (JSON),
  dominant_regime, confidence, indicators (JSON), created_at
```

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

## 5. COMMUNICATION PROTOCOL (CLOUDEVENTS)

### 5.1 Standard

All inter-agent messages use **CloudEvents v1.0** (CNCF standard) as the envelope format. This replaces the proprietary `MessageEnvelope` with an industry-standard format while preserving all trading-specific functionality.

### 5.2 Envelope Format

```
CloudEvent:
  specversion: "1.0"              # CloudEvents version
  id: ULID                        # Globally unique, time-sortable
  source: "tsar:agent:{name}"     # Event source (URI format)
  type: "tsar.{domain}.{action}.v1"  # Hierarchical event type
  time: RFC3339                   # Event timestamp (nanosecond precision)
  datacontenttype: "application/msgpack"  # Binary payload
  data: dict                      # Event payload (MessagePack encoded)

  # TSAR Extension Attributes
  traceid: string                 # Distributed tracing (W3C compatible)
  priority: int                   # 0=critical, 1=high, 2=normal, 3=low
  risklevel: string               # NONE|LOW|MEDIUM|HIGH|CRITICAL
  agentrole: string               # READ|ANALYSIS|TRADE_PREVIEW|TRADE_EXECUTE|TRADE_ADMIN
  tradingmode: string             # paper|live
  schemaver: int                  # Payload schema version
```

### 5.3 Canonical Event Types

| Domain | Event Types |
|--------|-------------|
| Regime | `tsar.regime.changed.v1`, `tsar.regime.updated.v1` |
| Signal | `tsar.signal.detected.v1`, `tsar.signal.validated.v1`, `tsar.signal.expired.v1` |
| Risk | `tsar.risk.decision.v1`, `tsar.risk.veto.v1`, `tsar.risk.veto_all.v1`, `tsar.risk.kill_switch.v1` |
| Order | `tsar.order.placed.v1`, `tsar.order.filled.v1`, `tsar.order.cancelled.v1`, `tsar.order.rejected.v1` |
| Fill | `tsar.fill.executed.v1`, `tsar.fill.partial.v1` |
| Position | `tsar.position.opened.v1`, `tsar.position.closed.v1`, `tsar.position.snapshot.v1` |
| Analytics | `tsar.analytics.trade_completed.v1`, `tsar.analytics.lesson_created.v1`, `tsar.analytics.pattern_report.v1` |
| Strategy | `tsar.strategy.mutated.v1`, `tsar.strategy.retired.v1` |
| Cartography | `tsar.cartography.correlation_updated.v1`, `tsar.cartography.anomaly_detected.v1` |
| Health | `tsar.health.heartbeat.v1`, `tsar.health.error.v1`, `tsar.health.shutdown.v1` |
| System | `tsar.system.bootstrap_complete.v1`, `tsar.system.mode_changed.v1` |
| Macro | `tsar.macro.regime_update.v1`, `tsar.macro.sentiment_update.v1`, `tsar.macro.onchain_update.v1` |

### 5.4 Serialization

- **Wire format:** MessagePack (binary, 30-50% smaller than JSON)
- **Debug format:** JSON (via `redis-cli`)
- **Transport:** Redis Streams with `ce_` prefixed fields

### 5.5 Redis Streams Integration

CloudEvents attributes map to Redis Stream fields with `ce_` prefix:

```
ce_specversion, ce_id, ce_source, ce_type, ce_time,
ce_datacontenttype, ce_traceid, ce_priority, ce_risklevel,
ce_agentrole, ce_tradingmode, ce_schemaver, ce_data (MessagePack)
```

### 5.6 Migration Path

Three-phase migration from legacy `MessageEnvelope`:
1. **Phase 1 (Weeks 1-2):** Dual mode — both formats published
2. **Phase 2 (Weeks 3-4):** CloudEvents primary, legacy read-only
3. **Phase 3 (Week 5+):** CloudEvents only, legacy code removed

---

## 6. RISK ARCHITECTURE (HARDENED)

### 6.1 Hard Rules (NEVER Violate)

| Rule | Value | Action on Violation |
|------|-------|---------------------|
| Max position | 15% of balance | Reject trade |
| Risk per trade | 2% of balance | Reduce size |
| Daily loss limit | -2% of balance | Stop trading for the day |
| Max drawdown | 5% from HWM | Halt ALL trading |
| Stop-loss required | Every trade | Reject if missing |
| Max open positions | 10 (Day1: 3) | Wait for close |
| Min R:R ratio | 2:1 | Reject trade |
| Max correlation | 0.7 to portfolio | Reject trade |
| Max daily trades | 30 | Wait for tomorrow |

### 6.2 Kill Switch Protocol — Dual-Write with File Fallback

**The kill switch is the single most critical piece of state in the system.** It must be readable even if Redis is down.

**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│              KILL SWITCH DUAL-WRITE ARCHITECTURE             │
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                  │
│  │  TRIGGER      │         │  TRIGGER      │                 │
│  │  (Automatic)  │         │  (Manual/CLI) │                 │
│  └──────┬───────┘         └──────┬───────┘                  │
│         │                        │                           │
│         ▼                        ▼                           │
│  ┌─────────────────────────────────────────────┐            │
│  │        DualWriteKillSwitch.activate()        │            │
│  │  1. Write /tmp/tsar_kill_switch (PRIMARY)    │            │
│  │  2. Write Redis tsar:risk:kill_switch (SECONDARY)        │
│  │  3. Execute kill actions (cancel orders, flatten)         │
│  │  4. Send notifications                                    │
│  └─────────────────────────────────────────────┘            │
│                                                              │
│  Read path: Redis first → File fallback → FAIL-SAFE (active)│
│  External kill: echo '{"active":true,...}' > /tmp/tsar_kill_switch│
└─────────────────────────────────────────────────────────────┘
```

**Trigger Conditions:**
- Daily loss ≥ -2% of capital
- Max drawdown ≥ 5% from HWM
- Exchange API auth failure
- Manual trigger via Telegram `/stop`
- External file write

**Kill Switch Actions:**
1. Cancel ALL open orders
2. Close ALL positions (market orders)
3. Set system to HALTED state
4. Send Telegram alert
5. Log to immutable audit log
6. Require manual `/start` to resume

### 6.3 Three-Tier Watchdog Architecture

```
Tier 1: Risk Governor (main process)
  → Heartbeat every 5s to Redis
  → Monitored by Tier 2

Tier 2: Kill Switch Monitor (AutoKillDetector)
  → Checks risk conditions every 5s
  → Heartbeat every 5s to Redis
  → Monitored by Tier 3

Tier 3: Watchdog Process (systemd service)
  → Checks Tier 1 and Tier 2 heartbeats every 10s
  → If either stale > 15s → activate kill switch via FILE
  → Cannot be killed by the agent process
  → If Redis unreachable → activate kill switch via file
```

**Failure Modes:**
| Failure | Detection Time → Action |
|---------|------------------------|
| Governor crash | 15s → Tier 2 or 3 kills |
| Monitor crash | 15s → Tier 3 kills |
| Both crash | 15s → Tier 3 kills via file |
| Redis down | 2s → Tier 3 kills via file |
| All three down | Manual (file is still there) |
| Watchdog crash | systemd restarts in 5s |

### 6.4 Anti-Behavioral Guards

| Guard | Detection | Action |
|-------|-----------|--------|
| Revenge trading | 3 consecutive losses | 60-min cooldown |
| Greed | Position size increase after wins | Cap at base size |
| FOMO | Signal score < 0.6, still trying to trade | Block |
| Overconfidence | 5+ consecutive wins, increasing size | Warn + cap |

### 6.5 Gated Recovery Protocol

Recovery from circuit breaker events requires passing through validation gates:

**ORANGE Recovery:**
```
Phase 1 (10%)    Phase 2 (25%)    Phase 3 (50%)    FULL (100%)
├──── 24h ───────├──── 48h ───────├──── 48h ───────┤
│ regime_check   │ positive_pnl   │ win_rate>40%   │
```

**RED Recovery:**
```
Phase 1 (5%)     Phase 2 (10%)    Phase 3 (25%)    Phase 4 (50%)    FULL
├──── 24h ───────├──── 48h ───────├──── 72h ───────├──── 72h ───────┤
│ regime_check   │ positive_pnl   │ win_rate>40%   │ sharpe>0       │
│ + manual_ok    │                │                │ + report_ok    │
```

### 6.6 Negative Balance Protection (Leveraged Products)

For forex/futures with leverage:
- **Max leverage by asset class:** forex_major 20:1, forex_minor 10:1, gold 10:1, crypto_perp 3:1
- **Gap risk multiplier:** Accounts for worst-case slippage beyond stop-loss
- **Margin utilization cap:** Never use more than 60% of available margin
- **Pre-liquidation buffer:** Act at 70% of maintenance margin (before exchange auto-liquidation)

### 6.7 Stress Testing (Pre-Deployment)

Historical scenarios that must pass before live capital:

| # | Scenario | Expected |
|---|----------|----------|
| 1 | March 2020 COVID crash (BTC -50%) | Kill switch fires |
| 2 | May 2021 crypto crash (BTC -53%) | Kill switch fires |
| 3 | Nov 2022 FTX collapse (BTC -25%) | Kill switch fires |
| 4 | Jan 2015 CHF flash crash (EUR/CHF -30%) | Kill switch fires |
| 5 | Correlation spike (all assets -20%) | Kill switch fires |
| 6 | Redis failure during position | Kill switch via file |
| 7 | Watchdog Tier 3 stale heartbeat | Kill switch via file |

### 6.8 VaR (Level 3+)

- Method: Historical simulation
- Confidence: 95% and 99%
- Horizon: 1-day
- Stress scenarios: Flash crash (-30%), Exchange halt (24h), LUNA collapse (-95%), FOMC shock, Liquidity crisis

### 6.9 Counterparty Risk (Level 2+)

- Exchange health score: API latency, error rate, withdrawal processing
- Proof-of-reserves verification: Monthly
- Exposure limits: Max 50% per exchange, min 2 exchanges at scale

---

## 7. STRATEGY ARCHITECTURE

### 7.1 Day1 Strategy: Mean Reversion

**Thesis:** BTC mean-reverts after RSI extremes. Buy oversold, sell overbought.

**Entry Rules:**
- RSI(14) < 30 (oversold)
- Price within 2% of support level
- Volume > 1.5x 20-period average
- Fear & Greed Index < 30
- Signal score ≥ 0.6

**Exit Rules:**
- Take profit: RSI > 70 OR +2% from entry
- Stop loss: -1% from entry (hard)
- Time stop: Close after 4 hours if neither TP nor SL hit

### 7.2 Level 2 Strategy: Momentum + Funding Rates

**Thesis:** Capture trend continuation when funding rates signal directional bias.

**Entry Rules:**
- EMA(21) > EMA(55) for longs (reverse for shorts)
- Funding rate negative for longs (positive for shorts)
- ADX > 25 (trending)
- Volume confirmation
- Signal score ≥ 0.65

**Exit Rules:**
- Trailing stop: 1.5x ATR
- Take profit: 3x ATR from entry
- Stop loss: 1x ATR from entry
- Funding rate flip: Close if funding rate reverses sign

### 7.3 Strategy Portfolio Allocation

- Methods: Risk Parity (default), Kelly-Based, Inverse Volatility
- Rebalance trigger: Drift > 10% from target
- Rebalance frequency: Weekly on rolling 30-day Sharpe
- Max single strategy: 50% of capital
- Min strategies for diversification: 2

### 7.4 Backtesting Engine (Level 2+)

- Library: vectorbt (Python, vectorized)
- Fee model: Exchange-accurate (Binance 0.1% maker/taker)
- Slippage model: Configurable (zero, fixed, realistic with mean 3bps, std 2bps)
- Walk-forward: Train 70% / Validation 15% / Test 15%
- Statistical significance: t-test p < 0.05 required

### 7.5 Strategy Evolution Pipeline

```
Trade Philosopher discovers patterns
        │
        ▼
Strategy Geneticist proposes mutations
        │
        ▼
Backtest on historical data (walk-forward)
        │
        ├── PASS → Deploy to paper trading
        │              │
        │              ▼
        │         30+ paper trades with Sharpe > 1.0
        │              │
        │              ├── PASS → Deploy to live (at 25% size)
        │              └── FAIL → Retire mutation
        │
        └── FAIL → Archive, try different mutation
```

---

## 8. LLM ARCHITECTURE (MODEL-AGNOSTIC)

### 8.1 Design Principles

| Principle | Rule | Rationale |
|-----------|------|-----------|
| **Zero model names in code** | Code references task_type only | Swap models without code changes |
| **Single config source** | `config/models.yaml` defines everything | Ops changes models, not engineers |
| **Capability-aware** | Models declare what they can do | Router selects models matching task requirements |
| **Fail-safe** | Every call has a fallback chain | System degrades gracefully |
| **Observable** | Every LLM call tracked (latency, tokens, cost) | Budget enforcement |

### 8.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT LAYER                                 │
│  Agents call: router.generate(task_type="t2_news_sentiment")     │
│  Agents NEVER reference model names                              │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  ModelRouter                                                     │
│  route(task_type, context) → (provider, model_spec)              │
│  • Task-to-model mapping (config-driven)                         │
│  • Fallback chain with circuit breaker                           │
│  • Cost tracking per model                                       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  ModelRegistry                                                   │
│  • Provider instances and their models                           │
│  • Fallback chains per task type                                 │
│  • Circuit breakers per provider                                 │
│  • Cost tracker                                                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  BaseLLMProvider (abstract)                                      │
│  generate() / stream() / count_tokens() / health_check()         │
└──────┬────────────┬────────────┬────────────┬──────────────────┘
       │            │            │            │
   ┌───▼──┐    ┌───▼───┐   ┌───▼────┐   ┌───▼──────────┐
   │Ollama│    │OpenAI │   │Anthropic│  │DeepSeek      │
   └──────┘    └───────┘   └────────┘   └──────────────┘
```

### 8.3 Task-Type Routing

No model names in agent code. Agents call `router.generate(task_type="trade_narrative", prompt=...)`.

**Task Types (Canonical):**

| Task Type | Tier | Description | Primary Model | Fallback Chain |
|-----------|------|-------------|---------------|----------------|
| `t2_regime_explanation` | T2 | Human-readable regime explanation | `ollama/qwen2.5:7b` | `ollama/llama3.1:8b` |
| `t2_signal_narrative` | T2 | Signal rationale for logging | `ollama/qwen2.5:7b` | `ollama/llama3.1:8b` |
| `t2_risk_explanation` | T2 | Explain risk decision | `ollama/qwen2.5:7b` | `ollama/llama3.1:8b` |
| `t2_trade_summary` | T2 | Quick trade summary | `ollama/qwen2.5:7b` | `ollama/llama3.1:8b` |
| `t2_news_sentiment` | T2 | Score news for sentiment | `ollama/qwen2.5:7b` | `ollama/llama3.1:8b` |
| `t2_daily_summary` | T2 | End-of-day summary | `ollama/qwen2.5:7b` | `ollama/llama3.1:8b` |
| `t2_anomaly_explanation` | T2 | Explain correlation anomalies | `ollama/qwen2.5:7b` | `ollama/llama3.1:8b` |
| `t3_trade_narrative` | T3 | Deep trade analysis | `deepseek/deepseek-reasoner` | `nvidia_nim/deepseek-r1` → `ollama/qwen2.5:32b` |
| `t3_strategy_synthesis` | T3 | Strategy hypothesis generation | `deepseek/deepseek-reasoner` | `nvidia_nim/deepseek-r1` → `ollama/qwen2.5:32b` |
| `t3_risk_scenario` | T3 | Complex risk scenario analysis | `deepseek/deepseek-reasoner` | `nvidia_nim/deepseek-r1` → `ollama/qwen2.5:7b` |
| `t3_bias_detection` | T3 | Detect behavioral biases | `deepseek/deepseek-reasoner` | `nvidia_nim/deepseek-r1` → `ollama/qwen2.5:32b` |
| `t1_pattern_embedding` | T1 | Pattern similarity search | `ollama/all-minilm-l6-v2` | (none — local only) |

### 8.4 Configuration (`config/models.yaml`)

All model names, providers, routing, fallback chains, and budgets defined in a single YAML file. **No model names in Python source code.**

```yaml
providers:
  ollama:
    base_url: "http://localhost:11434"
    timeout_s: 30
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
    base_url: "https://api.deepseek.com"
  nvidia_nim:
    api_key: "${NVIDIA_API_KEY}"
    base_url: "https://integrate.api.nvidia.com/v1"

models:
  ollama/qwen2.5:7b:
    display_name: "Qwen 2.5 7B (Local)"
    capabilities: [text_generation, streaming, tool_use, json_mode]
    max_context_tokens: 32768
    cost_per_1k_input_tokens: 0.0
  deepseek/deepseek-reasoner:
    display_name: "DeepSeek Reasoner"
    capabilities: [text_generation, streaming, tool_use, reasoning]
    max_context_tokens: 65536
    cost_per_1k_input_tokens: 0.00055

routing:
  t3_trade_narrative:
    primary: "deepseek/deepseek-reasoner"
    fallback: ["nvidia_nim/deepseek-ai/deepseek-r1", "ollama/qwen2.5:32b"]
    params: { max_tokens: 4096, temperature: 0.3 }

budget:
  daily_limit_usd: 0.0
  monthly_limit_usd: 0.0
```

### 8.5 Circuit Breaker & Cost Tracking

- **Per-provider circuit breaker:** Opens after 5 consecutive failures, recovers after 60s
- **Cost tracker:** Daily/monthly budget enforcement
- **Prometheus metrics:** `tsar_llm_requests_total`, `tsar_llm_latency_seconds`, `tsar_llm_cost_usd_total`

---

## 9. IMPROVEMENT MEASUREMENT

### 9.1 Purpose

Prove the system is getting better with every trade. Baseline metrics recorded after first 30 trades, daily snapshots track trends.

### 9.2 Core Metrics

| # | Metric | Tier | Description | Target Direction |
|---|--------|------|-------------|-----------------|
| 1 | `expectancy_trend` | Performance | 30-day rolling avg PnL per trade | ↑ Increasing |
| 2 | `sharpe_trend` | Performance | 30-day rolling annualized Sharpe | ↑ Increasing |
| 3 | `regime_accuracy` | Intelligence | How often regime detection matches reality | ↑ Increasing |
| 4 | `lesson_application_rate` | Intelligence | % of trades where lessons were applied | ↑ Increasing |
| 5 | `lesson_violation_rate` | Intelligence | % of trades violating known lessons | ↓ Decreasing |
| 6 | `knowledge_density` | Intelligence | New facts (patterns + lessons) per trade | ↑ Growing |
| 7 | `strategy_fitness` | Evolution | Rolling 30-day Sharpe per strategy genome | ↑ Increasing |
| 8 | `pattern_discovery_rate` | Evolution | New validated patterns per week | ↑ Growing |
| 9 | `execution_quality` | Performance | Average slippage in basis points | ↓ Decreasing |
| 10 | `risk_adjusted_return` | Performance | Return per unit of max drawdown | ↑ Increasing |

### 9.3 Baseline Recording

After 30 trades, record baseline metrics with mean, std_dev, and 95% confidence interval. All future improvement measured against this baseline using Welch's t-test (p < 0.05 required for significance).

### 9.4 Flywheel Health Score

Composite score (0-1) answering "Is TSAR's self-improvement loop working?"

```
flywheel_health = Σ(normalized_score[metric] × weight[metric])

Weights:
  expectancy_trend:           0.15
  sharpe_trend:               0.15
  regime_accuracy:            0.10
  lesson_application_rate:    0.10
  lesson_violation_rate:      0.10
  knowledge_density:          0.10
  strategy_fitness:           0.10
  pattern_discovery_rate:     0.05
  execution_quality:          0.075
  risk_adjusted_return:       0.075
```

**Classification:**
| Score | Meaning | Action |
|-------|---------|--------|
| > 0.7 | 🟢 Healthy | Continue monitoring |
| 0.4-0.7 | 🟡 Stalling | Investigate deteriorating factors |
| < 0.4 | 🔴 Broken | Pause live trading, audit subsystems |

### 9.5 SQL Schema

```sql
CREATE TABLE improvement_baselines (
    metric_name TEXT PRIMARY KEY, value REAL, std_dev REAL,
    ci_lower REAL, ci_upper REAL, sample_size INTEGER,
    recorded_at TEXT, raw_values_json TEXT
);

CREATE TABLE improvement_snapshots (
    snapshot_id INTEGER PRIMARY KEY, metric_name TEXT, value REAL,
    trend TEXT, trend_slope REAL, baseline_value REAL,
    delta_from_baseline REAL, p_value REAL, is_significant INTEGER,
    verdict TEXT, computed_at TEXT,
    UNIQUE(metric_name, computed_at)
);

CREATE TABLE flywheel_health_history (
    id INTEGER PRIMARY KEY, health_score REAL, classification TEXT,
    component_scores_json TEXT, recommendation TEXT, computed_at TEXT
);
```

### 9.6 Prometheus Metrics

- `tsar_improvement_{metric_name}` — Gauge for each metric value
- `tsar_improvement_{metric_name}_trend` — Gauge: 1=improving, 0=stable, -1=declining
- `tsar_flywheel_health_score` — Composite health gauge
- `tsar_improvement_alerts_total{severity, metric}` — Counter for alerts

### 9.7 Alert Rules

- **CRITICAL:** Flywheel health < 0.4 for 24h, Sharpe < -0.5 for 3d, violation rate > 20% for 1d
- **WARNING:** Flywheel health < 0.7 for 7d, expectancy negative for 7d, lesson rate < 30% for 14d

---

## 10. RESOURCE MANAGEMENT

### 10.1 Enforcement Architecture

Every tool invocation passes through `ResourceEnforcer` before execution:

```
ToolRegistry.call_tool()
       │
       ▼
┌────────────────────────┐
│   ResourceEnforcer     │
│  1. Pre-check:         │
│     - Resolve limits   │
│     - Check capacity   │
│     - Circuit breaker  │
│  2. Execute with       │
│     monitoring:        │
│     - Wall-clock timer │
│     - Memory watcher   │
│     - CPU watcher      │
│  3. Post-execution:    │
│     - Log consumption  │
│     - Update metrics   │
└───────────┬────────────┘
            ▼
   tool.execute(**kwargs)
```

### 10.2 Resource Limits

| Limit | Default | Rationale |
|-------|---------|----------|
| Max memory per tool | 256MB | Prevent runaway allocations |
| Max wall time | 30s | Prevent hung tools |
| Max concurrent | 10 | Prevent resource exhaustion |
| Max calls/min | 1200 | Match exchange rate limits |
| Max CPU seconds | 10s | Prevent CPU starvation |
| Max network requests | 100 | Prevent API abuse |

### 10.3 Per-Tool Profiles

| Tool Category | Memory | CPU | Wall Time | Network |
|---------------|--------|-----|-----------|---------|
| Exchange (get_price, etc.) | 128MB | 5s | 15s | 10 |
| Analysis (calculate_rsi, etc.) | 256MB | 10s | 30s | 100 |
| Risk (check_position_limits) | 128MB | 5s | 15s | 0 |
| Heavy compute (correlation) | 512MB | 30s | 60s | 100 |
| Execution (smart_order_router) | 256MB | 15s | 30s | 200 |

### 10.4 Context-Aware Limits

| Context | Adjustment | Rationale |
|---------|-----------|----------|
| `paper_trading` | Standard limits | No real money at risk |
| `live_trading` | **Tighter** timeouts (-30%) | Fail fast in live |
| `backtesting` | **Looser** memory (+100%), CPU (+200%) | Batch processing |
| `analysis_only` | Standard limits | Default mode |

### 10.5 Circuit Breaker (Resource-Aware)

Opens after N consecutive resource violations. Exponential backoff on repeated opens.

```
CLOSED → (3 violations) → OPEN → (60s) → HALF_OPEN → (probe succeeds) → CLOSED
                                      → (probe fails) → OPEN (2x timeout)
```

### 10.6 Violation Handling

| Violations | Action |
|-----------|--------|
| 1-2 | Log warning |
| 3-4 | Log error, alert |
| 5+ | Circuit breaker: disable tool |

### 10.7 Process-Level Limits (Day1)

For Day1 without Docker:
- Process RSS: 512MB via `resource.RLIMIT_AS`
- CPU time: 60s via `resource.RLIMIT_CPU`
- File descriptors: 256 via `resource.RLIMIT_NOFILE`
- Per-operation timeouts via `signal.SIGALRM`
- Memory monitoring via background thread (30s interval)

### 10.8 Prometheus Metrics

- `tsar_tool_resource_memory_mb{tool_name}` — Peak memory per tool
- `tsar_tool_resource_wall_time_seconds{tool_name}` — Wall time per tool
- `tsar_tool_resource_violations_total{tool_name, violation_type}` — Violation counter
- `tsar_tool_resource_kills_total{tool_name, kill_reason}` — Kill counter
- `tsar_tool_circuit_breaker_state{tool_name}` — Circuit breaker state
- `tsar_tool_active_invocations` — Concurrent invocations

---

## 11. DEPLOYMENT ARCHITECTURE

### 11.1 Day1 Deployment

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
├── config/
│   ├── backends.yaml          # Interface layer config
│   ├── models.yaml            # LLM model config
│   ├── resource_limits.yaml   # Tool resource limits
│   ├── exchanges.yaml
│   └── risk_limits.yaml
└── /tmp/tsar_kill_switch      # File-based kill switch
```

### 11.2 Full Deployment

```
VPS or Cloud Instance
├── Docker Compose / Kubernetes
│   ├── tsar-agents (4+ containers)
│   ├── redis:7.0 (with AOF)
│   ├── prometheus
│   ├── grafana
│   ├── loki (log aggregation)
│   ├── cadvisor (container monitoring)
│   ├── nginx (reverse proxy)
│   └── tsar-watchdog (systemd service)
├── CI/CD: GitHub Actions
│   ├── Lint + Type check
│   ├── Unit tests
│   ├── Integration tests
│   ├── Stress tests (FIX_D scenarios)
│   ├── Docker build
│   └── Canary deploy (5% → 100%)
└── Monitoring
    ├── Prometheus metrics
    ├── Grafana dashboards
    └── Telegram alerts
```

### 11.3 FastAPI Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/health` | GET | None | System health |
| `/positions` | GET | API Key | Current positions |
| `/pnl` | GET | API Key | P&L summary |
| `/risk` | GET | API Key | Risk state |
| `/improvement` | GET | API Key | Improvement metrics |
| `/flywheel` | GET | API Key | Flywheel health score |
| `/kill-switch` | POST | TRADE_ADMIN | Emergency halt |
| `/resume` | POST | TRADE_ADMIN | Resume trading |
| `/strategies` | GET | API Key | Strategy performance |
| `/regime` | GET | API Key | Current regime |
| `/trades` | GET | API Key | Trade history |
| `/backends` | GET | API Key | Backend registry status |

### 11.4 Infrastructure Ports

| Service | Port | Protocol |
|---------|------|----------|
| Redis | 6379 | TCP |
| FastAPI | **8000** | HTTP |
| Agent Supervisor | **8001** | HTTP |
| Prometheus | 9090 | HTTP |
| Grafana | 3000 | HTTP |
| Ollama | 11434 | HTTP |
| cAdvisor | 8080 | HTTP |

### 11.5 Backup (3-Tier)

| Tier | Frequency | Retention | Storage |
|------|-----------|-----------|---------|
| Hot | Every 15 min | 24 hours | Local (SQLite backup API) |
| Warm | Daily 00:00 UTC | 30 days | Local + cloud |
| Cold | Weekly | 1 year | Cloud (S3/R2) |

### 11.6 Monitoring

- **Prometheus metrics:** trade_count, pnl, drawdown, latency, error_rate, agent_health, improvement metrics, LLM metrics, resource metrics
- **Grafana dashboards:** Trading Overview, System Health, Risk Monitor, Improvement Tracking, Resource Usage
- **Alert routing:** CRITICAL → Telegram + SMS, WARNING → Telegram, INFO → Grafana

### 11.7 Structured Logging

- Format: JSON with timestamp, level, agent, trace_id, message
- Rotation: Daily
- Retention: 30 days hot, 90 days warm, 7 years cold

### 11.8 Compliance — Immutable Audit Log

- Layer 1: SQLite (mutable, queryable)
- Layer 2: Append-only JSONL with SHA-256 hash chain
- Layer 3: Remote copy with object lock (S3 versioning)

**Audit Event Types:**
```
trade.decision, trade.order_placed, trade.order_filled, trade.order_cancel,
risk.limit_hit, risk.kill_switch, system.startup, system.shutdown,
system.config_change, data.feed_gap, data.anomaly, recon.mismatch
```

---

## 12. SCALING PATH (DAY1 → LEVEL 5)

### 12.1 Day1 → Level 2

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
11. Add Momentum + Funding Rates strategy
12. Swap `CcxtGateway` → `RustWsGateway` (via config change)

### 12.2 Level 2 → Level 3

**What Changes:**
1. Add Regime Detector, Trade Philosopher, Strategy Geneticist, Market Cartographer, Execution Tracker (5 more agents)
2. Add VaR / stress testing
3. Add strategy portfolio + allocation
4. Add multi-asset support (forex, gold)
5. Add Prometheus + Grafana monitoring
6. Add structured logging + Loki
7. Add on-chain analytics (full suite)
8. Add improvement measurement framework
9. Swap `PandasTAEngine` → `RustTickEngine` (via config change)

### 12.3 Level 3 → Level 4

**What Changes:**
1. Multi-exchange execution
2. Advanced execution algorithms (TWAP, VWAP via Rust)
3. Full compliance layer
4. Performance attribution
5. Portfolio rebalancing
6. Kubernetes deployment
7. Swap `CcxtExecEngine` → `RustExecEngine` → `FixExecEngine` (via config)
8. Add C++ QuantLib pricing engine
9. Add OANDA forex gateway

### 12.4 Level 4 → Level 5

**What Changes:**
1. GPU Monte Carlo for VaR (CUDA)
2. Institutional-grade execution (FIX 4.4)
3. Full regulatory compliance
4. Multi-strategy portfolio optimization
5. Cross-asset arbitrage
6. Real-time risk dashboards

### 12.5 Component Upgrade Triggers

| Component | Upgrade When |
|-----------|-------------|
| SQLite → PostgreSQL | > 100K trades or need concurrent access |
| 3 → 4 agents | 3 agents proven, need macro specialization |
| 10 → 20 tools | Need advanced order types, multiple timeframes |
| Laptop → VPS | Need 24/7 uptime |
| Telegram → + Dashboard | Need visual analytics |
| Basic risk → Full risk | Capital > $1,000 |
| Python backend → Rust | Need < 1ms latency |
| Rust backend → C++ FIX | Need institutional connectivity |

### 12.6 Backend Swap Process (Zero Code Changes)

```yaml
# config/backends.yaml — change primary, done.
exchange_gateway:
  primary: "src.interfaces.exchange.rust_gateway.RustGateway"  # was CcxtGateway
  fallback:
    - path: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
      priority: 200
```

Restart. All agents automatically use the new backend. No agent code changes.

---

## APPENDIX A: CANONICAL VALUES REFERENCE

| Parameter | Canonical Value | Source |
|-----------|----------------|--------|
| Stream prefix | `tsar:stream:*` | This document |
| Database file | `tsar.db` | This document |
| Daily loss limit | **-2%** | This document §6.1 |
| Max drawdown | **5%** from HWM | This document §6.1 |
| Max positions | **10** (Day1: 3) | This document §6.1 |
| Max single position | **15%** of capital | This document §6.1 |
| Max sector concentration | **30%** of capital | This document §6.1 |
| Kelly fraction | **0.25** (fixed) | This document §6.1 |
| Max correlation | **0.7** | This document §6.1 |
| Min risk-reward | **2:1** | This document §6.1 |
| Max daily trades | **30** | This document §6.1 |
| Message format | CloudEvents v1.0 | This document §5 |
| Wire serialization | MessagePack | This document §5.4 |
| LLM provider | BaseLLMProvider ABC | This document §8 |
| Model config | `config/models.yaml` | This document §8.4 |
| Backend config | `config/backends.yaml` | This document §2.3 |
| Resource config | `config/resource_limits.yaml` | This document §10 |
| Improvement baseline | After 30 trades | This document §9.3 |
| Tool resource guard | ResourceEnforcer + ResourceGuard | This document §10 |
| Kill switch persistence | Dual-write (Redis + file) | This document §6.2 |
| Watchdog | Three-tier (Governor + Monitor + Watchdog) | This document §6.3 |
| Rust version | 1.79 | This document §1.6 |
| Python version | 3.12 | This document §1.6 |
| FastAPI port | 8000 | This document §11.4 |
| Supervisor port | 8001 | This document §11.4 |
| Redis port | 6379 | This document §11.4 |

---

## APPENDIX B: GLOSSARY

| Term | Definition |
|------|-----------|
| **TSAR** | Trading Super Agent Regime |
| **ABC** | Abstract Base Class — the interface contract |
| **BackendRegistry** | Central discovery engine mapping interfaces to implementations |
| **CloudEvents** | CNCF standard for event envelope format (v1.0) |
| **VETO_ALL** | Emergency halt: all trading stopped until manual clearance |
| **Kill switch** | Automatic VETO_ALL triggered when daily loss exceeds -2% |
| **Dual-write** | Kill switch writes to both Redis AND file for resilience |
| **Watchdog** | Tier 3 process that monitors the monitors via systemd |
| **HMM** | Hidden Markov Model — regime detection |
| **Half-Kelly** | Fixed 0.25 fraction for position sizing |
| **HWM** | High Water Mark — peak portfolio value |
| **Paper mode** | Simulated execution; no real money at risk |
| **Live mode** | Real exchange execution; real money at risk |
| **Bootstrap** | First-start data acquisition and model calibration |
| **Flywheel** | Self-reinforcing cycle: trade → learn → improve → trade better |
| **Flywheel Health** | Composite score (0-1) measuring self-improvement loop effectiveness |
| **Harness** | Deterministic subsystems (risk, execution) that intelligence cannot override |
| **Regime** | Market state classification (trending, ranging, volatile, breakout) |
| **Task type** | LLM routing key (e.g., `t3_trade_narrative`) — code never uses model names |
| **Hot-swap** | Runtime backend replacement via `BackendRegistry.swap()` |
| **ResourceEnforcer** | Middleware enforcing per-tool memory, CPU, time limits |

---

## APPENDIX C: DATA FLOWS

### Trade Lifecycle

```
Signal Scout → tsar:stream:signals → Risk Guardian → tsar:stream:risk_decisions
→ Execution Sniper → tsar:stream:orders → Execution Tracker → tsar:stream:fills
→ Trade Philosopher → tsar:stream:analytics → Strategy Geneticist
→ tsar:stream:strategy_mutations → Signal Scout (improved)
```

### Risk Decision Flow

```
Execution Sniper → tsar:stream:risk_requests → Risk Guardian
→ tsar:stream:risk_reply:{sniper_id} → Execution Sniper
```

### Knowledge Accumulation

```
Trade Memory → Trade Philosopher → Lesson Archive → Strategy Geneticist
Pattern Library → Signal Scout (better scoring)
Regime History → Strategy Geneticist (regime-aware backtesting)
```

---

*This document is the SINGLE SOURCE OF TRUTH for the TSAR Trading Super Agent architecture.*
*All engineering must reference this document. Where prior documents conflict, this document wins.*

*Consolidated: 2026-07-24 05:29 GMT+8*
*Version 3.0.0 — Future-ready interface layer, CloudEvents, model-agnostic LLM, hardened risk, improvement measurement, resource management*
