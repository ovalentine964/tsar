# Trading Super Agent — Tech Stack & Architecture

> Institutional-grade, multi-language trading system with AI integration

## Table of Contents

- [Overview](#overview)
- [Architecture Diagram](#architecture-diagram)
- [Language Stack](#language-stack)
- [Core Components](#core-components)
- [Project Structure](#project-structure)
- [Dependency Manifests](#dependency-manifests)
- [Configuration System](#configuration-system)
- [Build & DevOps](#build--devops)
- [Model Routing](#model-routing)
- [Logging & Monitoring](#logging--monitoring)

---

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRADING SUPER AGENT                          │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ Strategy  │  │ Backtest │  │ Risk     │  │  Portfolio   │   │
│  │ Engine    │  │ Engine   │  │ Manager  │  │  Optimizer   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       │              │             │               │            │
│  ┌────┴──────────────┴─────────────┴───────────────┴───────┐   │
│  │              Python 3.12 — Orchestration Layer           │   │
│  │         (FastAPI · Celery · python-telegram-bot)         │   │
│  └────┬──────────────┬─────────────┬───────────────┬───────┘   │
│       │              │             │               │            │
│  ┌────┴─────┐  ┌─────┴────┐  ┌────┴─────┐  ┌─────┴──────┐    │
│  │ PyO3     │  │ SQLite   │  │ Redis    │  │ ChromaDB   │    │
│  │ Bridge   │  │ + FTS5   │  │ Cache    │  │ Vectors    │    │
│  └────┬─────┘  └──────────┘  └──────────┘  └────────────┘    │
│       │                                                        │
│  ┌────┴───────────────────────────────────────────────────┐   │
│  │              Rust — Performance Layer                    │   │
│  │    (tokio · tungstenite · serde · PyO3 bindings)       │   │
│  │                                                         │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │   │
│  │  │ WebSocket│  │ Tick     │  │ Order    │             │   │
│  │  │ Manager  │  │ Processor│  │ Executor │             │   │
│  │  └──────────┘  └──────────┘  └──────────┘             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              External Integrations                       │   │
│  │  ccxt · Binance · Bybit · OKX · Telegram · LLM APIs    │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Architecture Diagram

```
                    ┌─────────────────┐
                    │   Telegram Bot  │
                    │   (Commands &   │
                    │    Alerts)      │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │   FastAPI       │
                    │   REST + WS     │
                    │   (Port 8000)   │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
┌─────────┴─────────┐ ┌─────┴──────┐ ┌─────────┴─────────┐
│  Strategy Engine   │ │  Backtest  │ │  Risk Manager     │
│  (Python)          │ │  Engine    │ │  (Python)         │
│  - LLM signals     │ │  vectorbt  │ │  - Position sizing│
│  - Technical        │ │  pandas-ta │ │  - Drawdown ctrl  │
│  - Pattern recog    │ │            │ │  - Exposure limits│
└─────────┬──────────┘ └────────────┘ └─────────┬─────────┘
          │                                      │
          └──────────────┬───────────────────────┘
                         │
              ┌──────────┴──────────┐
              │   PyO3 Bridge       │
              │   (Zero-copy IPC)   │
              └──────────┬──────────┘
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
┌───┴──────────┐  ┌─────┴──────┐  ┌─────────┴────┐
│ WebSocket    │  │ Tick       │  │ Order        │
│ Manager      │  │ Processor  │  │ Executor     │
│ (Rust/tokio) │  │ (Rust)     │  │ (Rust)       │
└──────────────┘  └────────────┘  └──────────────┘
```

### Data Flow

```
Exchange WS ──→ Rust WS Manager ──→ Tick Processor ──→ Python Strategy
                    │                      │                    │
                    │                      ▼                    ▼
                    │              ┌──────────────┐    ┌──────────────┐
                    │              │  SQLite       │    │  Redis       │
                    │              │  (Ticks,      │    │  (State,     │
                    │              │   OHLCV,      │    │   Cache,     │
                    │              │   Orders)     │    │   Pub/Sub)   │
                    │              └──────────────┘    └──────────────┘
                    │                                         │
                    ▼                                         ▼
              ┌──────────────┐                      ┌──────────────┐
              │  Prometheus  │                      │  Telegram    │
              │  Metrics     │                      │  Alerts      │
              └──────────────┘                      └──────────────┘
```

---

## Language Stack

### Python 3.12 — Orchestration & Intelligence

| Role | Components |
|------|-----------|
| **Agent orchestration** | Main loop, strategy coordination, signal aggregation |
| **LLM integration** | LiteLLM, Ollama, prompt engineering, model routing |
| **Strategy logic** | Indicator computation, pattern recognition, signal generation |
| **Backtesting** | vectorbt, pandas-ta, historical simulation |
| **API server** | FastAPI REST + WebSocket endpoints |
| **Telegram bot** | Commands, alerts, interactive controls |
| **Data pipeline** | pandas, numpy, data transformation |

### Rust — Performance Layer

| Role | Components |
|------|-----------|
| **WebSocket handling** | tokio-tungstenite, concurrent connections, message parsing |
| **Tick processing** | OHLCV aggregation, order book updates, spread calculation |
| **Order execution** | Low-latency order placement, cancellation, status tracking |
| **Data structures** | Ring buffers, order books, tick arrays |
| **Serialization** | serde, zero-copy deserialization |

### PyO3 — Bridge Layer

| Role | Components |
|------|-----------|
| **Python→Rust** | Call Rust functions from Python with automatic type conversion |
| **Rust→Python** | Callback Python from Rust for strategy evaluation |
| **Zero-copy** | Share buffers between Python and Rust without copying |
| **GIL management** | Release GIL for CPU-intensive Rust operations |

### SQL — Data Persistence

| Role | Components |
|------|-----------|
| **Schema** | Tables for ticks, OHLCV, orders, positions, signals |
| **FTS5** | Full-text search on trade notes, news, analysis |
| **Migrations** | Schema versioning with embedded migration scripts |

### YAML — Configuration

| Role | Components |
|------|-----------|
| **Strategy defs** | Declarative strategy parameters and rules |
| **System config** | Database, cache, exchange, logging settings |
| **Model routing** | Which LLM for which task, fallback chains |
| **Alerts** | Threshold definitions, notification channels |

---

## Core Components

### 1. Exchange Gateway (Rust + Python)

```
┌─────────────────────────────────────────────┐
│              Exchange Gateway                │
│                                             │
│  Rust Layer:                                │
│  ├── WebSocket connections (tokio)          │
│  ├── Message parsing (serde_json)           │
│  ├── Order book maintenance                 │
│  └── Tick aggregation (1s/1m/5m/15m/1h)    │
│                                             │
│  Python Layer:                              │
│  ├── ccxt unified interface                 │
│  ├── REST API fallback                      │
│  ├── Rate limiting                          │
│  └── Exchange-specific adapters             │
└─────────────────────────────────────────────┘
```

### 2. Strategy Engine (Python)

```
┌─────────────────────────────────────────────┐
│              Strategy Engine                 │
│                                             │
│  ├── Technical indicators (pandas-ta)       │
│  ├── LLM signal analysis (LiteLLM)         │
│  ├── Pattern recognition (ChromaDB search)  │
│  ├── Multi-timeframe analysis               │
│  ├── Signal aggregation & scoring           │
│  └── Entry/exit decision logic              │
│                                             │
│  Strategies:                                │
│  ├── Trend following (MA crossovers)        │
│  ├── Mean reversion (Bollinger, RSI)        │
│  ├── Momentum (MACD, ADX)                   │
│  ├── Breakout (support/resistance)          │
│  └── LLM-enhanced (news + technical)        │
└─────────────────────────────────────────────┘
```

### 3. Risk Manager (Python)

```
┌─────────────────────────────────────────────┐
│              Risk Manager                    │
│                                             │
│  ├── Position sizing (Kelly criterion)      │
│  ├── Maximum drawdown control               │
│  ├── Per-trade risk limits                  │
│  ├── Portfolio exposure limits              │
│  ├── Correlation analysis                   │
│  ├── Volatility-adjusted sizing             │
│  └── Emergency stop-loss                    │
│                                             │
│  Rules (YAML-defined):                      │
│  ├── max_position_size: 5% of portfolio     │
│  ├── max_daily_drawdown: 2%                 │
│  ├── max_open_positions: 10                 │
│  ├── max_correlation: 0.7                   │
│  └── emergency_stop: -5% daily              │
└─────────────────────────────────────────────┘
```

### 4. Backtesting Engine (Python)

```
┌─────────────────────────────────────────────┐
│              Backtesting Engine              │
│                                             │
│  ├── vectorbt for fast simulation           │
│  ├── Historical data management             │
│  ├── Walk-forward optimization              │
│  ├── Monte Carlo simulation                 │
│  ├── Sharpe/Sortino/Calmar ratios           │
│  ├── Trade-level analysis                   │
│  └── Benchmark comparison                   │
│                                             │
│  Metrics:                                   │
│  ├── Total return, CAGR                     │
│  ├── Sharpe ratio, Sortino ratio            │
│  ├── Maximum drawdown                       │
│  ├── Win rate, profit factor                │
│  ├── Average trade duration                 │
│  └── Slippage & commission modeling         │
└─────────────────────────────────────────────┘
```

### 5. LLM Integration (Python)

```
┌─────────────────────────────────────────────┐
│              LLM Integration                │
│                                             │
│  LiteLLM Router:                            │
│  ├── Free tier management                   │
│  ├── Automatic fallbacks                    │
│  ├── Token counting & budget                │
│  └── Response caching (Redis)               │
│                                             │
│  Model Roles:                               │
│  ├── News analysis → Qwen3 8B (Ollama)     │
│  ├── Signal validation → Llama3 8B (local) │
│  ├── Trade journaling → GPT-3.5 free       │
│  ├── Pattern matching → Embeddings (local)  │
│  └── Complex reasoning → DeepSeek free      │
│                                             │
│  Tasks:                                     │
│  ├── Analyze news sentiment                 │
│  ├── Validate technical signals             │
│  ├── Generate trade rationale               │
│  ├── Summarize daily performance            │
│  └── Search similar historical patterns     │
└─────────────────────────────────────────────┘
```

### 6. Notification System (Python)

```
┌─────────────────────────────────────────────┐
│              Notification System             │
│                                             │
│  Telegram Bot:                              │
│  ├── /start, /stop — Control trading        │
│  ├── /status — Portfolio & P&L              │
│  ├── /positions — Open positions            │
│  ├── /signals — Recent signals              │
│  ├── /backtest — Run backtest               │
│  ├── /config — View/edit config             │
│  ├── /risk — Risk metrics                   │
│  └── /journal — Trade journal               │
│                                             │
│  Alerts:                                    │
│  ├── Trade execution notifications          │
│  ├── Risk threshold warnings                │
│  ├── Daily P&L summary                      │
│  ├── System health alerts                   │
│  └── LLM analysis results                   │
└─────────────────────────────────────────────┘
```

---

## Project Structure

```
trading-super-agent/
│
├── 📄 README.md                        # Project overview & quick start
├── 📄 TECH_STACK.md                    # This document
├── 📄 Makefile                         # Build & dev commands
├── 📄 pyproject.toml                   # Python project config & deps
├── 📄 Cargo.toml                       # Rust workspace config
├── 📄 requirements.txt                 # Quick Python deps (pip install -r)
├── 📄 docker-compose.yml               # Full stack orchestration
├── 📄 Dockerfile.python                # Python service image
├── 📄 Dockerfile.rust                  # Rust build image
├── 📄 .env.example                     # Environment variable template
├── 📄 .gitignore                       # Git ignore rules
├── 📄 .pre-commit-config.yaml          # Pre-commit hooks
├── 📄 rust-toolchain.toml              # Rust toolchain pinning
│
├── 📁 config/                          # Configuration files
│   ├── 📄 default.yaml                 # Default configuration
│   ├── 📄 development.yaml             # Dev overrides
│   ├── 📄 production.yaml              # Prod overrides
│   ├── 📄 strategies/                  # Strategy definitions
│   │   ├── 📄 trend_following.yaml
│   │   ├── 📄 mean_reversion.yaml
│   │   ├── 📄 momentum.yaml
│   │   └── 📄 breakout.yaml
│   ├── 📄 model_routing.yaml           # LLM model routing
│   ├── 📄 exchanges.yaml               # Exchange configurations
│   ├── 📄 risk.yaml                    # Risk management rules
│   ├── 📄 logging.yaml                 # Logging configuration
│   └── 📄 alerts.yaml                  # Alert thresholds
│
├── 📁 src/                             # Python source root
│   ├── 📄 __init__.py
│   ├── 📄 __main__.py                  # Entry point
│   │
│   ├── 📁 core/                        # Core business logic
│   │   ├── 📄 __init__.py
│   │   ├── 📄 engine.py                # Main trading engine
│   │   ├── 📄 events.py                # Event system (pub/sub)
│   │   ├── 📄 state.py                 # Global state management
│   │   └── 📄 types.py                 # Shared type definitions
│   │
│   ├── 📁 exchange/                    # Exchange integrations
│   │   ├── 📄 __init__.py
│   │   ├── 📄 base.py                  # Abstract exchange interface
│   │   ├── 📄 manager.py               # Multi-exchange manager
│   │   ├── 📄 adapters/                # Exchange-specific adapters
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 binance.py
│   │   │   ├── 📄 bybit.py
│   │   │   ├── 📄 okx.py
│   │   │   └── 📄 bitget.py
│   │   └── 📄 types.py                 # Exchange data types
│   │
│   ├── 📁 strategy/                    # Strategy implementations
│   │   ├── 📄 __init__.py
│   │   ├── 📄 base.py                  # Abstract strategy interface
│   │   ├── 📄 registry.py              # Strategy registry & loader
│   │   ├── 📄 signals.py               # Signal aggregation
│   │   ├── 📁 implementations/         # Concrete strategies
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 trend_following.py
│   │   │   ├── 📄 mean_reversion.py
│   │   │   ├── 📄 momentum.py
│   │   │   ├── 📄 breakout.py
│   │   │   └── 📄 llm_enhanced.py
│   │   └── 📁 indicators/              # Custom indicators
│   │       ├── 📄 __init__.py
│   │       ├── 📄 order_flow.py
│   │       ├── 📄 volume_profile.py
│   │       └── 📄 market_structure.py
│   │
│   ├── 📁 risk/                        # Risk management
│   │   ├── 📄 __init__.py
│   │   ├── 📄 manager.py               # Risk manager
│   │   ├── 📄 position_sizer.py        # Position sizing models
│   │   ├── 📄 drawdown.py              # Drawdown monitoring
│   │   └── 📄 exposure.py              # Portfolio exposure
│   │
│   ├── 📁 backtest/                    # Backtesting engine
│   │   ├── 📄 __init__.py
│   │   ├── 📄 engine.py                # Backtest runner
│   │   ├── 📄 data.py                  # Historical data management
│   │   ├── 📄 metrics.py               # Performance metrics
│   │   ├── 📄 optimizer.py             # Parameter optimization
│   │   └── 📄 report.py                # Report generation
│   │
│   ├── 📁 llm/                         # LLM integration
│   │   ├── 📄 __init__.py
│   │   ├── 📄 router.py                # Model routing & fallback
│   │   ├── 📄 prompts.py               # Prompt templates
│   │   ├── 📄 analysis.py              # News & sentiment analysis
│   │   ├── 📄 validator.py             # Signal validation
│   │   ├── 📄 journal.py               # Trade journaling
│   │   └── 📄 cache.py                 # Response caching
│   │
│   ├── 📁 data/                        # Data management
│   │   ├── 📄 __init__.py
│   │   ├── 📄 database.py              # SQLite connection & queries
│   │   ├── 📄 models.py                # SQLAlchemy/SQLModel models
│   │   ├── 📄 migrations.py            # Schema migrations
│   │   ├── 📄 vectorstore.py           # ChromaDB integration
│   │   └── 📄 cache.py                 # Redis cache layer
│   │
│   ├── 📁 api/                         # FastAPI application
│   │   ├── 📄 __init__.py
│   │   ├── 📄 app.py                   # FastAPI app factory
│   │   ├── 📄 dependencies.py          # Dependency injection
│   │   ├── 📁 routes/                  # API routes
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 health.py            # Health checks
│   │   │   ├── 📄 trading.py           # Trading endpoints
│   │   │   ├── 📄 portfolio.py         # Portfolio endpoints
│   │   │   ├── 📄 backtest.py          # Backtest endpoints
│   │   │   └── 📄 websocket.py         # WebSocket endpoints
│   │   └── 📁 middleware/              # Middleware
│   │       ├── 📄 __init__.py
│   │       ├── 📄 auth.py              # Authentication
│   │       ├── 📄 rate_limit.py        # Rate limiting
│   │       └── 📄 logging.py           # Request logging
│   │
│   ├── 📁 bot/                         # Telegram bot
│   │   ├── 📄 __init__.py
│   │   ├── 📄 bot.py                   # Bot setup & handlers
│   │   ├── 📁 commands/                # Bot commands
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 trading.py           # /start, /stop, /status
│   │   │   ├── 📄 portfolio.py         # /positions, /balance
│   │   │   ├── 📄 backtest.py          # /backtest, /optimize
│   │   │   ├── 📄 config.py            # /config, /set
│   │   │   └── 📄 journal.py           # /journal, /notes
│   │   └── 📁 formatters/              # Message formatting
│   │       ├── 📄 __init__.py
│   │       └── 📄 messages.py
│   │
│   ├── 📁 tasks/                       # Background tasks
│   │   ├── 📄 __init__.py
│   │   ├── 📄 celery_app.py            # Celery configuration
│   │   ├── 📄 data_sync.py             # Data synchronization
│   │   ├── 📄 report_gen.py            # Report generation
│   │   └── 📄 maintenance.py           # System maintenance
│   │
│   ├── 📁 monitoring/                  # Observability
│   │   ├── 📄 __init__.py
│   │   ├── 📄 metrics.py               # Prometheus metrics
│   │   ├── 📄 health.py                # Health checks
│   │   └── 📄 alerts.py                # Alert management
│   │
│   └── 📁 utils/                       # Shared utilities
│       ├── 📄 __init__.py
│       ├── 📄 config.py                # Config loader (YAML + env)
│       ├── 📄 logging.py               # Structured logging setup
│       ├── 📄 time.py                  # Timezone & time utilities
│       ├── 📄 math.py                  # Math helpers
│       └── 📄 decorators.py            # Utility decorators
│
├── 📁 rust/                            # Rust source root
│   ├── 📄 Cargo.toml                   # Rust workspace manifest
│   │
│   ├── 📁 crates/                      # Rust crates
│   │   ├── 📁 core/                    # Core Rust library
│   │   │   ├── 📄 Cargo.toml
│   │   │   └── 📁 src/
│   │   │       ├── 📄 lib.rs
│   │   │       ├── 📄 types.rs         # Shared data types
│   │   │       ├── 📄 error.rs         # Error types
│   │   │       └── 📄 config.rs        # Config structures
│   │   │
│   │   ├── 📁 ws-manager/              # WebSocket manager
│   │   │   ├── 📄 Cargo.toml
│   │   │   └── 📁 src/
│   │   │       ├── 📄 lib.rs
│   │   │       ├── 📄 connection.rs    # WS connection handling
│   │   │       ├── 📄 pool.rs          # Connection pool
│   │   │       ├── 📄 parser.rs        # Message parsing
│   │   │       └── 📄 reconnect.rs     # Auto-reconnection
│   │   │
│   │   ├── 📁 tick-processor/          # Tick processing
│   │   │   ├── 📄 Cargo.toml
│   │   │   └── 📁 src/
│   │   │       ├── 📄 lib.rs
│   │   │       ├── 📄 aggregator.rs    # OHLCV aggregation
│   │   │       ├── 📄 orderbook.rs     # Order book updates
│   │   │       ├── 📄 spread.rs        # Spread calculation
│   │   │       └── 📄 ring_buffer.rs   # Ring buffer for ticks
│   │   │
│   │   ├── 📁 order-executor/          # Order execution
│   │   │   ├── 📄 Cargo.toml
│   │   │   └── 📁 src/
│   │   │       ├── 📄 lib.rs
│   │   │       ├── 📄 executor.rs      # Order placement
│   │   │       ├── 📄 tracker.rs       # Order status tracking
│   │   │       └── 📄 types.rs         # Order types
│   │   │
│   │   └── 📁 pyo3-bindings/           # Python bindings
│   │       ├── 📄 Cargo.toml
│   │       └── 📁 src/
│   │           ├── 📄 lib.rs           # PyO3 module entry
│   │           ├── 📄 ws_bridge.rs     # WebSocket bridge
│   │           ├── 📄 tick_bridge.rs   # Tick processor bridge
│   │           └── 📄 order_bridge.rs  # Order executor bridge
│   │
│   └── 📁 tests/                       # Rust integration tests
│       ├── 📄 ws_integration.rs
│       ├── 📄 tick_processing.rs
│       └── 📄 order_execution.rs
│
├── 📁 tests/                           # Python tests
│   ├── 📄 conftest.py                  # Shared fixtures
│   ├── 📄 __init__.py
│   │
│   ├── 📁 unit/                        # Unit tests
│   │   ├── 📄 __init__.py
│   │   ├── 📁 core/
│   │   │   ├── 📄 test_engine.py
│   │   │   └── 📄 test_events.py
│   │   ├── 📁 strategy/
│   │   │   ├── 📄 test_signals.py
│   │   │   └── 📄 test_trend_following.py
│   │   ├── 📁 risk/
│   │   │   ├── 📄 test_position_sizer.py
│   │   │   └── 📄 test_drawdown.py
│   │   ├── 📁 data/
│   │   │   ├── 📄 test_database.py
│   │   │   └── 📄 test_vectorstore.py
│   │   └── 📁 llm/
│   │       ├── 📄 test_router.py
│   │       └── 📄 test_analysis.py
│   │
│   ├── 📁 integration/                 # Integration tests
│   │   ├── 📄 __init__.py
│   │   ├── 📄 test_exchange_flow.py
│   │   ├── 📄 test_strategy_pipeline.py
│   │   ├── 📄 test_rust_bridge.py
│   │   └── 📄 test_api_endpoints.py
│   │
│   ├── 📁 backtest/                    # Backtest validation
│   │   ├── 📄 __init__.py
│   │   ├── 📄 test_known_strategies.py
│   │   └── 📄 test_metrics.py
│   │
│   └── 📁 fixtures/                    # Test data
│       ├── 📄 sample_ohlcv.csv
│       ├── 📄 sample_trades.json
│       └── 📄 sample_config.yaml
│
├── 📁 scripts/                         # Utility scripts
│   ├── 📄 setup_dev.sh                 # Development environment setup
│   ├── 📄 build_rust.sh                # Build Rust with PyO3
│   ├── 📄 run_backtest.py              # CLI backtest runner
│   ├── 📄 fetch_data.py                # Historical data fetcher
│   ├── 📄 migrate_db.py                # Database migration runner
│   └── 📄 seed_data.py                 # Development data seeder
│
├── 📁 migrations/                      # Database migrations
│   ├── 📄 001_initial_schema.sql
│   ├── 📄 002_add_indexes.sql
│   └── 📄 003_add_fts5.sql
│
├── 📁 grafana/                         # Grafana dashboards
│   ├── 📄 dashboards/
│   │   ├── 📄 trading_overview.json
│   │   ├── 📄 risk_metrics.json
│   │   └── 📄 system_health.json
│   └── 📄 provisioning/
│       ├── 📄 datasources.yaml
│       └── 📄 dashboards.yaml
│
├── 📁 docs/                            # Documentation
│   ├── 📄 architecture.md              # Architecture deep-dive
│   ├── 📄 strategies.md                # Strategy documentation
│   ├── 📄 api_reference.md             # API documentation
│   ├── 📄 deployment.md                # Deployment guide
│   ├── 📄 development.md               # Development guide
│   └── 📄 rust_integration.md          # Rust/PyO3 guide
│
└── 📁 .github/                         # GitHub configuration
    ├── 📁 workflows/
    │   ├── 📄 ci.yml                   # CI pipeline
    │   ├── 📄 release.yml              # Release pipeline
    │   └── 📄 rust-build.yml           # Rust cross-compile
    ├── 📄 ISSUE_TEMPLATE/
    │   ├── 📄 bug_report.md
    │   └── 📄 feature_request.md
    └── 📄 PULL_REQUEST_TEMPLATE.md
```

---

## Dependency Manifests

### Python Dependencies (pyproject.toml)

```toml
[build-system]
requires = ["maturin>=1.5,<2.0"]
build-backend = "maturin"

[project]
name = "trading-super-agent"
version = "0.1.0"
description = "Institutional-grade AI trading system"
requires-python = ">=3.12"
license = {text = "MIT"}
authors = [
    {name = "Trading Super Agent Team"}
]

dependencies = [
    # === Core Runtime ===
    "pydantic>=2.6,<3.0",
    "pydantic-settings>=2.2,<3.0",
    "python-dotenv>=1.0,<2.0",

    # === Exchange & Data ===
    "ccxt>=4.2,<5.0",
    "pandas>=2.2,<3.0",
    "numpy>=1.26,<2.0",
    "pandas-ta>=0.3.14b1",

    # === Technical Analysis ===
    "TA-Lib>=0.4.28",

    # === Backtesting ===
    "vectorbt>=0.26,<1.0",

    # === Database ===
    "sqlalchemy>=2.0,<3.0",
    "sqlmodel>=0.0.16",
    "aiosqlite>=0.20,<1.0",

    # === Vector Database ===
    "chromadb>=0.4,<1.0",

    # === Cache ===
    "redis[hiredis]>=5.0,<6.0",

    # === API Server ===
    "fastapi>=0.110,<1.0",
    "uvicorn[standard]>=0.28,<1.0",
    "websockets>=12.0,<13.0",
    "httpx>=0.27,<1.0",

    # === LLM Integration ===
    "litellm>=1.30,<2.0",
    "openai>=1.12,<2.0",
    "tiktoken>=0.6,<1.0",

    # === Task Queue ===
    "celery[redis]>=5.3,<6.0",
    "arq>=0.26,<1.0",

    # === Telegram Bot ===
    "python-telegram-bot>=21.0,<22.0",

    # === Monitoring ===
    "prometheus-client>=0.20,<1.0",

    # === Logging ===
    "structlog>=24.1,<25.0",
    "python-json-logger>=2.0,<3.0",

    # === Configuration ===
    "pyyaml>=6.0,<7.0",
    "python-jose[cryptography]>=3.3,<4.0",

    # === Utilities ===
    "rich>=13.7,<14.0",
    "typer>=0.9,<1.0",
    "orjson>=3.9,<4.0",
    "aiofiles>=23.2,<24.0",
    "tenacity>=8.2,<9.0",
    "cachetools>=5.3,<6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9.0",
    "pytest-asyncio>=0.23,<1.0",
    "pytest-cov>=4.1,<5.0",
    "pytest-mock>=3.12,<4.0",
    "hypothesis>=6.98,<7.0",
    "ruff>=0.3,<1.0",
    "mypy>=1.9,<2.0",
    "pre-commit>=3.6,<4.0",
    "ipython>=8.22,<9.0",
    "ipdb>=0.13,<1.0",
]

docs = [
    "mkdocs>=1.5,<2.0",
    "mkdocs-material>=9.5,<10.0",
    "mkdocstrings[python]>=0.24,<1.0",
]

[project.scripts]
trading-agent = "src.__main__:main"
trading-api = "src.api.app:create_app"
trading-bot = "src.bot.bot:main"

[tool.maturin]
features = ["pyo3/extension-module"]
python-source = "."

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "A", "SIM", "TCH"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "slow: marks tests as slow",
    "integration: marks integration tests",
    "backtest: marks backtest tests",
]
```

### Rust Dependencies (Cargo.toml)

```toml
[workspace]
resolver = "2"
members = [
    "crates/core",
    "crates/ws-manager",
    "crates/tick-processor",
    "crates/order-executor",
    "crates/pyo3-bindings",
]

[workspace.package]
version = "0.1.0"
edition = "2021"
rust-version = "1.75"
license = "MIT"
repository = "https://github.com/your-org/trading-super-agent"

[workspace.dependencies]
# === Async Runtime ===
tokio = { version = "1.36", features = ["full"] }
tokio-stream = "0.1"

# === WebSocket ===
tungstenite = { version = "0.21", features = ["native-tls"] }
tokio-tungstenite = { version = "0.21", features = ["native-tls"] }

# === Serialization ===
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
serde_yaml = "0.9"

# === Error Handling ===
thiserror = "1.0"
anyhow = "1.0"

# === Logging ===
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json"] }

# === HTTP ===
reqwest = { version = "0.12", features = ["json", "rustls-tls"] }

# === Crypto ===
hmac = "0.12"
sha2 = "0.10"
hex = "0.4"

# === Time ===
chrono = { version = "0.4", features = ["serde"] }

# === PyO3 ===
pyo3 = { version = "0.21", features = ["extension-module"] }

# === Utils ===
uuid = { version = "1.8", features = ["v4", "serde"] }
dashmap = "5.5"
crossbeam-channel = "0.5"
parking_lot = "0.12"
```

### Individual Crate: ws-manager

```toml
[package]
name = "trading-ws-manager"
version.workspace = true
edition.workspace = true

[dependencies]
tokio = { workspace = true }
tokio-tungstenite = { workspace = true }
tungstenite = { workspace = true }
serde = { workspace = true }
serde_json = { workspace = true }
tracing = { workspace = true }
thiserror = { workspace = true }
dashmap = { workspace = true }
tokio-stream = { workspace = true }
```

### Individual Crate: tick-processor

```toml
[package]
name = "trading-tick-processor"
version.workspace = true
edition.workspace = true

[dependencies]
tokio = { workspace = true }
serde = { workspace = true }
serde_json = { workspace = true }
tracing = { workspace = true }
parking_lot = { workspace = true }
crossbeam-channel = { workspace = true }
```

### Individual Crate: pyo3-bindings

```toml
[package]
name = "trading-pyo3"
version.workspace = true
edition.workspace = true

[lib]
name = "trading_rs"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { workspace = true }
trading-ws-manager = { path = "../ws-manager" }
trading-tick-processor = { path = "../tick-processor" }
trading-order-executor = { path = "../order-executor" }
trading-core = { path = "../core" }
tokio = { workspace = true }
serde = { workspace = true }
serde_json = { workspace = true }
```

### requirements.txt (Quick Setup)

```
# Python 3.12+ required
# Install: pip install -r requirements.txt

# === Core ===
pydantic>=2.6,<3.0
pydantic-settings>=2.2,<3.0
python-dotenv>=1.0,<2.0

# === Exchange & Data ===
ccxt>=4.2,<5.0
pandas>=2.2,<3.0
numpy>=1.26,<2.0
pandas-ta>=0.3.14b1
TA-Lib>=0.4.28

# === Backtesting ===
vectorbt>=0.26,<1.0

# === Database ===
sqlalchemy>=2.0,<3.0
sqlmodel>=0.0.16
aiosqlite>=0.20,<1.0
chromadb>=0.4,<1.0

# === Cache ===
redis>=5.0,<6.0

# === API ===
fastapi>=0.110,<1.0
uvicorn[standard]>=0.28,<1.0
websockets>=12.0,<13.0
httpx>=0.27,<1.0

# === LLM ===
litellm>=1.30,<2.0
openai>=1.12,<2.0
tiktoken>=0.6,<1.0

# === Tasks ===
celery[redis]>=5.3,<6.0

# === Telegram ===
python-telegram-bot>=21.0,<22.0

# === Monitoring ===
prometheus-client>=0.20,<1.0

# === Logging ===
structlog>=24.1,<25.0
python-json-logger>=2.0,<3.0

# === Config ===
pyyaml>=6.0,<7.0

# === Utilities ===
rich>=13.7,<14.0
typer>=0.9,<1.0
orjson>=3.9,<4.0
tenacity>=8.2,<9.0
```

---

## Configuration System

### Configuration Hierarchy

```
Environment Variables (highest priority)
    ↓
config/production.yaml (or development.yaml)
    ↓
config/default.yaml (lowest priority)
```

### config/default.yaml

```yaml
# ============================================================
# Trading Super Agent — Default Configuration
# ============================================================
# Environment variables override these values.
# Format: TRADING_SECTION_KEY (double underscore for nesting)
# Example: TRADING_DATABASE__URL overrides database.url

# === Application ===
app:
  name: "trading-super-agent"
  version: "0.1.0"
  environment: "development"  # development | staging | production
  debug: true
  timezone: "UTC"

# === Database ===
database:
  url: "sqlite+aiosqlite:///./data/trading.db"
  echo: false
  pool_size: 5
  # FTS5 enabled for full-text search on trade notes
  fts5_enabled: true

# === Redis Cache ===
redis:
  url: "redis://localhost:6379/0"
  prefix: "trading:"
  default_ttl: 3600  # 1 hour
  max_connections: 10

# === Vector Database ===
vectorstore:
  provider: "chromadb"
  path: "./data/chromadb"
  collection_name: "trading_patterns"
  embedding_model: "all-MiniLM-L6-v2"

# === Exchanges ===
exchanges:
  default: "binance"
  testnet: true  # Always start with testnet
  rate_limit: 1200  # requests per minute
  exchanges:
    binance:
      enabled: true
      sandbox: true
      options:
        defaultType: "future"
    bybit:
      enabled: false
      sandbox: true
    okx:
      enabled: false
      sandbox: true

# === Trading Engine ===
engine:
  mode: "paper"  # paper | live
  symbols:
    - "BTC/USDT"
    - "ETH/USDT"
    - "SOL/USDT"
  timeframes:
    - "1m"
    - "5m"
    - "15m"
    - "1h"
    - "4h"
    - "1d"
  max_open_positions: 10
  order_timeout: 30  # seconds

# === Risk Management ===
risk:
  max_position_size_pct: 5.0      # % of portfolio per position
  max_daily_drawdown_pct: 2.0     # % daily drawdown limit
  max_total_drawdown_pct: 10.0    # % total drawdown limit
  max_portfolio_exposure_pct: 80.0 # % max capital deployed
  max_correlation: 0.7            # max correlation between positions
  emergency_stop_loss_pct: 5.0    # % loss triggers emergency stop
  min_risk_reward_ratio: 2.0      # minimum R:R for entry

# === Strategies ===
strategies:
  enabled:
    - "trend_following"
    - "momentum"
  config_dir: "config/strategies"
  signal_aggregation: "weighted_average"  # weighted_average | majority_vote | unanimous

# === LLM Configuration ===
llm:
  provider: "litellm"
  cache_responses: true
  cache_ttl: 86400  # 24 hours
  max_tokens: 4096
  temperature: 0.1
  models:
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
    complex: "deepseek/deepseek-chat"
    embeddings: "local/all-MiniLM-L6-v2"

# === API Server ===
api:
  host: "0.0.0.0"
  port: 8000
  workers: 1
  cors_origins: ["*"]
  auth:
    enabled: false
    secret_key: "${TRADING_API_SECRET_KEY}"
    algorithm: "HS256"
    token_expire_minutes: 1440  # 24 hours

# === Telegram Bot ===
telegram:
  enabled: true
  token: "${TRADING_TELEGRAM_TOKEN}"
  allowed_users: []  # empty = allow all
  polling_interval: 1.0  # seconds
  commands:
    - "start"
    - "stop"
    - "status"
    - "positions"
    - "signals"
    - "backtest"
    - "config"
    - "risk"
    - "journal"

# === Background Tasks ===
tasks:
  broker_url: "redis://localhost:6379/1"
  result_backend: "redis://localhost:6379/2"
  task_serializer: "json"
  timezone: "UTC"
  concurrency: 4

# === Monitoring ===
monitoring:
  prometheus:
    enabled: true
    port: 9090
    path: "/metrics"
  grafana:
    enabled: true
    port: 3000
    admin_password: "${TRADING_GRAFANA_PASSWORD}"

# === Logging ===
logging:
  level: "INFO"
  format: "json"  # json | console
  file: "./logs/trading.log"
  max_size_mb: 100
  backup_count: 5
  structlog:
    processors:
      - "structlog.processors.TimeStamper"
      - "structlog.processors.add_log_level"
      - "structlog.processors.StackInfoRenderer"
      - "structlog.dev.ConsoleRenderer"
```

### config/model_routing.yaml

```yaml
# ============================================================
# Model Routing Configuration
# ============================================================
# Maps tasks to specific models based on complexity and requirements.
# Free tier models are prioritized. Fallback chains ensure reliability.

routing:
  # --- News & Sentiment Analysis ---
  news_analysis:
    description: "Analyze news articles for market sentiment"
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
    max_tokens: 1024
    temperature: 0.1
    cache_ttl: 3600  # 1 hour — news is time-sensitive

  # --- Technical Signal Validation ---
  signal_validation:
    description: "Validate technical analysis signals with LLM reasoning"
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
    max_tokens: 512
    temperature: 0.0  # Deterministic for validation
    cache_ttl: 300  # 5 minutes

  # --- Trade Rationale Generation ---
  trade_journal:
    description: "Generate human-readable trade rationale"
    primary: "ollama/qwen3:8b"
    fallback: "deepseek/deepseek-chat"
    max_tokens: 2048
    temperature: 0.3
    cache_ttl: 0  # Never cache — always generate fresh

  # --- Pattern Recognition ---
  pattern_matching:
    description: "Find similar historical patterns"
    primary: "local/all-MiniLM-L6-v2"  # Embeddings only
    fallback: null
    use_vectorstore: true
    top_k: 10

  # --- Complex Reasoning ---
  complex_analysis:
    description: "Multi-factor analysis requiring deeper reasoning"
    primary: "deepseek/deepseek-chat"
    fallback: "ollama/qwen3:8b"
    max_tokens: 4096
    temperature: 0.2
    cache_ttl: 7200  # 2 hours

  # --- Daily Summary ---
  daily_summary:
    description: "End-of-day performance summary"
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
    max_tokens: 2048
    temperature: 0.3
    cache_ttl: 0

  # --- Risk Assessment ---
  risk_assessment:
    description: "Evaluate portfolio risk factors"
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
    max_tokens: 1024
    temperature: 0.0  # Deterministic for risk
    cache_ttl: 600  # 10 minutes

# Model budget (tokens per day, 0 = unlimited)
budget:
  daily_token_limit: 0  # Free models = unlimited
  track_usage: true
  alert_threshold_pct: 80
```

### config/exchanges.yaml

```yaml
# ============================================================
# Exchange Configuration
# ============================================================

exchanges:
  binance:
    name: "Binance"
    enabled: true
    sandbox: true
    api_key: "${TRADING_BINANCE_API_KEY}"
    api_secret: "${TRADING_BINANCE_API_SECRET}"
    options:
      defaultType: "future"
      adjustForTimeDifference: true
    rate_limit: 1200
    symbols:
      - "BTC/USDT"
      - "ETH/USDT"
      - "SOL/USDT"
      - "BNB/USDT"
    websocket:
      url: "wss://stream.binance.com:9443/ws"
      streams:
        - "{symbol}@trade"
        - "{symbol}@kline_{timeframe}"
        - "{symbol}@depth20@100ms"

  bybit:
    name: "Bybit"
    enabled: false
    sandbox: true
    api_key: "${TRADING_BYBIT_API_KEY}"
    api_secret: "${TRADING_BYBIT_API_SECRET}"
    options:
      defaultType: "linear"
    rate_limit: 600
    symbols:
      - "BTC/USDT"
      - "ETH/USDT"

  okx:
    name: "OKX"
    enabled: false
    sandbox: true
    api_key: "${TRADING_OKX_API_KEY}"
    api_secret: "${TRADING_OKX_API_SECRET}"
    passphrase: "${TRADING_OKX_PASSPHRASE}"
    options:
      defaultType: "swap"
    rate_limit: 600
```

### config/risk.yaml

```yaml
# ============================================================
# Risk Management Rules
# ============================================================

rules:
  # --- Position Sizing ---
  position_sizing:
    method: "kelly_criterion"  # fixed | kelly_criterion | volatility_adjusted
    kelly_fraction: 0.25       # Use quarter Kelly for safety
    max_position_pct: 5.0      # Never exceed 5% per position
    min_position_usd: 10.0     # Minimum position size

  # --- Drawdown Control ---
  drawdown:
    daily_max_pct: 2.0         # Stop trading if daily DD > 2%
    weekly_max_pct: 5.0        # Reduce size if weekly DD > 5%
    total_max_pct: 10.0        # Emergency stop if total DD > 10%
    recovery_mode: "reduce"    # reduce | stop | hedge

  # --- Exposure Limits ---
  exposure:
    max_portfolio_pct: 80.0    # Max 80% of capital at risk
    max_single_asset_pct: 20.0 # Max 20% in single asset
    max_sector_pct: 40.0       # Max 40% in same sector
    max_correlation: 0.7       # No highly correlated positions

  # --- Stop Loss ---
  stop_loss:
    default_pct: 2.0           # Default SL at 2%
    trailing_enabled: true
    trailing_activation_pct: 1.0  # Activate trailing after 1% profit
    trailing_callback_pct: 0.5    # Trail by 0.5%
    time_based_hours: 48       # Close if no movement in 48h

  # --- Take Profit ---
  take_profit:
    enabled: true
    levels:
      - { pct: 3.0, close_ratio: 0.33 }   # Close 33% at 3%
      - { pct: 5.0, close_ratio: 0.33 }   # Close 33% at 5%
      - { pct: 10.0, close_ratio: 0.34 }  # Close rest at 10%

  # --- Circuit Breakers ---
  circuit_breakers:
    consecutive_losses: 5      # Pause after 5 consecutive losses
    pause_duration_minutes: 60 # Pause for 1 hour
    max_trades_per_hour: 10    # Rate limit trades
    max_trades_per_day: 50     # Daily trade limit
    volatility_spike_pct: 5.0  # Pause on 5% volatility spike
```

### config/alerts.yaml

```yaml
# ============================================================
# Alert Configuration
# ============================================================

channels:
  telegram:
    enabled: true
    priority: "high"

alerts:
  trade_executed:
    channel: "telegram"
    priority: "high"
    template: "🔔 Trade: {side} {amount} {symbol} @ {price}"

  risk_warning:
    channel: "telegram"
    priority: "critical"
    template: "⚠️ Risk: {message}"

  daily_summary:
    channel: "telegram"
    priority: "medium"
    schedule: "0 0 * * *"  # Midnight UTC
    template: "📊 Daily: P&L {pnl}, Trades {count}, Win Rate {win_rate}%"

  system_error:
    channel: "telegram"
    priority: "critical"
    template: "🚨 Error: {error}"

  drawdown_warning:
    channel: "telegram"
    priority: "critical"
    threshold_pct: 1.5
    template: "📉 Drawdown: {current_pct}% (limit: {limit_pct}%)"

  connection_lost:
    channel: "telegram"
    priority: "high"
    template: "🔌 Connection lost: {exchange}"
```

---

## Build & DevOps

### Makefile

```makefile
# ============================================================
# Trading Super Agent — Makefile
# ============================================================

.PHONY: help install dev build test lint clean docker rust python

# Variables
PYTHON := python3.12
PIP := pip
CARGO := cargo
DOCKER := docker
DOCKER_COMPOSE := docker-compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# === Setup ===

install: rust-build python-install ## Full installation
	@echo "✅ Installation complete"

dev: install ## Setup development environment
	pre-commit install
	$(PYTHON) -m ipykernel install --user --name trading
	@echo "✅ Development environment ready"

python-install: ## Install Python dependencies
	$(PIP) install -e ".[dev]"

rust-build: ## Build Rust with PyO3 bindings
	cd rust && maturin develop --release
	@echo "✅ Rust bindings built"

rust-check: ## Check Rust code
	cd rust && cargo check --workspace
	cd rust && cargo clippy --workspace -- -D warnings

# === Development ===

run: ## Run the trading agent
	$(PYTHON) -m src

api: ## Run the API server
	uvicorn src.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000

bot: ## Run the Telegram bot
	$(PYTHON) -m src.bot.bot

worker: ## Run Celery worker
	celery -A src.tasks.celery_app worker --loglevel=info

# === Testing ===

test: ## Run all tests
	pytest tests/ -v --cov=src --cov-report=term-missing

test-unit: ## Run unit tests only
	pytest tests/unit/ -v

test-integration: ## Run integration tests
	pytest tests/integration/ -v -m integration

test-backtest: ## Run backtest validation
	pytest tests/backtest/ -v -m backtest

test-rust: ## Run Rust tests
	cd rust && cargo test --workspace

test-all: test test-rust ## Run all tests (Python + Rust)

# === Code Quality ===

lint: ## Run linters
	ruff check src/ tests/
	ruff format --check src/ tests/
	mypy src/

format: ## Format code
	ruff format src/ tests/
	ruff check --fix src/ tests/

# === Build ===

build: ## Build production image
	$(DOCKER_COMPOSE) build

build-rust-release: ## Build optimized Rust binary
	cd rust && cargo build --release

# === Docker ===

docker-up: ## Start all services
	$(DOCKER_COMPOSE) up -d

docker-down: ## Stop all services
	$(DOCKER_COMPOSE) down

docker-logs: ## View logs
	$(DOCKER_COMPOSE) logs -f

docker-clean: ## Clean Docker resources
	$(DOCKER_COMPOSE) down -v --remove-orphans

# === Data ===

db-migrate: ## Run database migrations
	$(PYTHON) scripts/migrate_db.py

db-seed: ## Seed development data
	$(PYTHON) scripts/seed_data.py

fetch-data: ## Fetch historical data
	$(PYTHON) scripts/fetch_data.py

# === Backtesting ===

backtest: ## Run backtest
	$(PYTHON) scripts/run_backtest.py

# === Cleanup ===

clean: ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	cd rust && cargo clean

clean-all: clean docker-clean ## Deep clean everything
	rm -rf data/ logs/ .mypy_cache/ .ruff_cache/
```

### Docker Compose (docker-compose.yml)

```yaml
version: "3.9"

services:
  # === Trading Agent ===
  trading-agent:
    build:
      context: .
      dockerfile: Dockerfile.python
    container_name: trading-agent
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ./logs:/app/logs
    depends_on:
      redis:
        condition: service_healthy
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # === API Server ===
  api-server:
    build:
      context: .
      dockerfile: Dockerfile.python
    container_name: trading-api
    restart: unless-stopped
    command: ["uvicorn", "src.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
    env_file: .env
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
    ports:
      - "8000:8000"
    depends_on:
      redis:
        condition: service_healthy

  # === Telegram Bot ===
  telegram-bot:
    build:
      context: .
      dockerfile: Dockerfile.python
    container_name: trading-bot
    restart: unless-stopped
    command: ["python", "-m", "src.bot.bot"]
    env_file: .env
    volumes:
      - ./config:/app/config:ro
    depends_on:
      redis:
        condition: service_healthy

  # === Celery Worker ===
  celery-worker:
    build:
      context: .
      dockerfile: Dockerfile.python
    container_name: trading-worker
    restart: unless-stopped
    command: ["celery", "-A", "src.tasks.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
    env_file: .env
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
    depends_on:
      redis:
        condition: service_healthy

  # === Redis ===
  redis:
    image: redis:7-alpine
    container_name: trading-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru

  # === Prometheus ===
  prometheus:
    image: prom/prometheus:latest
    container_name: trading-prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus

  # === Grafana ===
  grafana:
    image: grafana/grafana:latest
    container_name: trading-grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${TRADING_GRAFANA_PASSWORD:-admin}
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    depends_on:
      - prometheus

volumes:
  redis-data:
  prometheus-data:
  grafana-data:
```

### Dockerfile.python

```dockerfile
FROM python:3.12-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libta-lib0-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Rust bindings (pre-built in CI or built here)
COPY rust/ ./rust/
RUN pip install maturin && cd rust && maturin develop --release

# Application code
COPY src/ ./src/
COPY config/ ./config/
COPY migrations/ ./migrations/

# Create data dirs
RUN mkdir -p data logs

EXPOSE 8000

CMD ["python", "-m", "src"]
```

### .env.example

```bash
# ============================================================
# Trading Super Agent — Environment Variables
# ============================================================
# Copy to .env and fill in your values.
# NEVER commit .env to version control!

# === Application ===
TRADING_ENV=development
TRADING_DEBUG=true
TRADING_TIMEZONE=UTC

# === Database ===
TRADING_DATABASE__URL=sqlite+aiosqlite:///./data/trading.db

# === Redis ===
TRADING_REDIS__URL=redis://localhost:6379/0

# === API Server ===
TRADING_API_SECRET_KEY=change-me-to-a-random-string
TRADING_API_HOST=0.0.0.0
TRADING_API_PORT=8000

# === Telegram Bot ===
TRADING_TELEGRAM_TOKEN=your-telegram-bot-token-here
TRADING_TELEGRAM_ALLOWED_USERS=123456789,987654321

# === Exchange: Binance ===
TRADING_BINANCE_API_KEY=your-binance-api-key
TRADING_BINANCE_API_SECRET=your-binance-api-secret

# === Exchange: Bybit ===
TRADING_BYBIT_API_KEY=your-bybit-api-key
TRADING_BYBIT_API_SECRET=your-bybit-api-secret

# === Exchange: OKX ===
TRADING_OKX_API_KEY=your-okx-api-key
TRADING_OKX_API_SECRET=your-okx-api-secret
TRADING_OKX_PASSPHRASE=your-okx-passphrase

# === LLM (Optional — local models work without keys) ===
TRADING_DEEPSEEK_API_KEY=your-deepseek-api-key
TRADING_OPENAI_API_KEY=your-openai-api-key

# === Monitoring ===
TRADING_GRAFANA_PASSWORD=admin

# === NVIDIA API (Free Tier) ===
NVIDIA_API_KEY=your-nvidia-api-key
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
```

### .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
*.egg

# Virtual environments
.venv/
venv/
env/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Rust
rust/target/
rust/**/target/

# Data (never commit trading data)
data/
*.db
*.sqlite
*.sqlite3

# Logs
logs/
*.log

# Environment
.env
.env.local
.env.*.local

# Testing
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/

# Docker
docker-compose.override.yml

# OS
.DS_Store
Thumbs.db

# Secrets (safety net)
*.pem
*.key
*.cert
secrets/
```

---

## Model Routing

### Free Tier Strategy

```
┌────────────────────────────────────────────────────────────┐
│                    MODEL ROUTING                            │
│                                                            │
│  ┌─────────────────┐    ┌─────────────────┐               │
│  │  Ollama (Local)  │    │  NVIDIA Free    │               │
│  │  ─────────────── │    │  ─────────────  │               │
│  │  Qwen3 8B        │    │  Llama3 70B     │               │
│  │  Llama3 8B       │    │  Mistral 7B     │               │
│  │  Embeddings       │    │  DeepSeek       │               │
│  │                   │    │                  │               │
│  │  ✓ Unlimited     │    │  ✓ Free tier    │               │
│  │  ✓ Zero cost     │    │  ✓ Higher quality│               │
│  │  ✓ Low latency   │    │  ⚠ Rate limited │               │
│  └────────┬─────────┘    └────────┬────────┘               │
│           │                       │                        │
│           └───────────┬───────────┘                        │
│                       ▼                                    │
│              ┌─────────────────┐                           │
│              │  LiteLLM Router  │                           │
│              │  ────────────── │                           │
│              │  • Fallback chain│                           │
│              │  • Token budget  │                           │
│              │  • Response cache│                           │
│              │  • Rate limiting │                           │
│              └────────┬────────┘                           │
│                       ▼                                    │
│              ┌─────────────────┐                           │
│              │  Task Dispatcher │                           │
│              └─────────────────┘                           │
└────────────────────────────────────────────────────────────┘
```

### Task-to-Model Mapping

| Task | Primary Model | Fallback | Rationale |
|------|--------------|----------|-----------|
| News analysis | Qwen3 8B (local) | Llama3 8B (local) | Speed, no rate limits |
| Signal validation | Qwen3 8B (local) | Llama3 8B (local) | Deterministic, fast |
| Trade journal | Qwen3 8B (local) | DeepSeek (free) | Creative but fast |
| Pattern search | MiniLM-L6-v2 (local) | — | Embeddings only |
| Complex reasoning | DeepSeek (free) | Qwen3 8B (local) | Higher quality needed |
| Daily summary | Qwen3 8B (local) | Llama3 8B (local) | Speed, formatting |
| Risk assessment | Qwen3 8B (local) | Llama3 8B (local) | Deterministic |

---

## Logging & Monitoring

### Structured Logging

```python
# src/utils/logging.py — Key patterns

import structlog

# Processors chain
processors = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]

# Console renderer for development
if settings.logging.format == "console":
    processors.append(structlog.dev.ConsoleRenderer())
else:
    processors.append(structlog.processors.JSONRenderer())

structlog.configure(
    processors=processors,
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.logging.level)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
```

### Prometheus Metrics

```python
# src/monitoring/metrics.py — Key metrics

from prometheus_client import Counter, Gauge, Histogram

# Trading metrics
trades_total = Counter(
    "trading_trades_total",
    "Total number of trades",
    ["symbol", "side", "strategy", "status"]
)

portfolio_value = Gauge(
    "trading_portfolio_value_usd",
    "Current portfolio value in USD"
)

unrealized_pnl = Gauge(
    "trading_unrealized_pnl_usd",
    "Unrealized P&L in USD",
    ["symbol"]
)

trade_duration = Histogram(
    "trading_trade_duration_seconds",
    "Trade duration in seconds",
    buckets=[60, 300, 900, 1800, 3600, 7200, 14400, 28800, 86400]
)

# System metrics
ws_messages_total = Counter(
    "trading_ws_messages_total",
    "WebSocket messages received",
    ["exchange", "stream"]
)

ws_reconnections = Counter(
    "trading_ws_reconnections_total",
    "WebSocket reconnections",
    ["exchange"]
)

llm_requests_total = Counter(
    "trading_llm_requests_total",
    "LLM API requests",
    ["model", "task", "status"]
)

llm_latency = Histogram(
    "trading_llm_latency_seconds",
    "LLM request latency",
    ["model", "task"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

risk_drawdown = Gauge(
    "trading_risk_drawdown_pct",
    "Current drawdown percentage"
)
```

### Grafana Dashboards

```
Dashboard 1: Trading Overview
├── Portfolio Value (time series)
├── Daily P&L (bar chart)
├── Win Rate (gauge)
├── Open Positions (table)
├── Recent Trades (table)
└── Signal Activity (heatmap)

Dashboard 2: Risk Metrics
├── Drawdown (time series)
├── Position Sizes (pie chart)
├── Exposure by Asset (bar chart)
├── Correlation Matrix (heatmap)
├── Risk Limit Usage (gauges)
└── Circuit Breaker Status (status panel)

Dashboard 3: System Health
├── WebSocket Status (status indicators)
├── Message Rate (time series)
├── LLM Latency (histogram)
├── API Response Time (time series)
├── Error Rate (time series)
├── Redis Memory (gauge)
└── Database Size (time series)
```

---

## Database Schema

### migrations/001_initial_schema.sql

```sql
-- ============================================================
-- Trading Super Agent — Initial Schema
-- ============================================================

-- === Exchanges ===
CREATE TABLE IF NOT EXISTS exchanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT true,
    sandbox BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- === Symbols ===
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id INTEGER NOT NULL REFERENCES exchanges(id),
    symbol TEXT NOT NULL,
    base TEXT NOT NULL,
    quote TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exchange_id, symbol)
);

-- === OHLCV Candles ===
CREATE TABLE IF NOT EXISTS ohlcv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id),
    timeframe TEXT NOT NULL,  -- 1m, 5m, 15m, 1h, 4h, 1d
    timestamp TIMESTAMP NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol_id, timeframe, timestamp)
);

CREATE INDEX idx_ohlcv_symbol_tf_ts ON ohlcv(symbol_id, timeframe, timestamp DESC);

-- === Trades ===
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id INTEGER NOT NULL REFERENCES exchanges(id),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    type TEXT NOT NULL CHECK (type IN ('market', 'limit', 'stop', 'stop_limit')),
    amount REAL NOT NULL,
    price REAL NOT NULL,
    cost REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    fee_currency TEXT,
    order_id TEXT NOT NULL,
    strategy TEXT,
    signal_id INTEGER,
    status TEXT NOT NULL DEFAULT 'filled',
    pnl REAL,
    pnl_pct REAL,
    notes TEXT,
    metadata JSON,
    opened_at TIMESTAMP NOT NULL,
    closed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_strategy ON trades(strategy);
CREATE INDEX idx_trades_opened ON trades(opened_at DESC);
CREATE INDEX idx_trades_status ON trades(status);

-- === Positions ===
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id INTEGER NOT NULL REFERENCES exchanges(id),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    amount REAL NOT NULL,
    entry_price REAL NOT NULL,
    current_price REAL,
    unrealized_pnl REAL,
    stop_loss REAL,
    take_profit REAL,
    strategy TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'stopped')),
    opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    metadata JSON
);

CREATE INDEX idx_positions_symbol ON positions(symbol);
CREATE INDEX idx_positions_status ON positions(status);

-- === Signals ===
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short', 'neutral')),
    strength REAL NOT NULL CHECK (strength BETWEEN 0 AND 1),
    price_at_signal REAL NOT NULL,
    indicators JSON,
    llm_analysis TEXT,
    executed BOOLEAN NOT NULL DEFAULT false,
    trade_id INTEGER REFERENCES trades(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_signals_symbol ON signals(symbol);
CREATE INDEX idx_signals_strategy ON signals(strategy);
CREATE INDEX idx_signals_created ON signals(created_at DESC);

-- === Risk Events ===
CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message TEXT NOT NULL,
    metadata JSON,
    acknowledged BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_risk_events_type ON risk_events(event_type);
CREATE INDEX idx_risk_events_severity ON risk_events(severity);

-- === Performance Snapshots ===
CREATE TABLE IF NOT EXISTS performance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE,
    portfolio_value REAL NOT NULL,
    daily_pnl REAL NOT NULL,
    daily_pnl_pct REAL NOT NULL,
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    losing_trades INTEGER NOT NULL DEFAULT 0,
    max_drawdown_pct REAL,
    sharpe_ratio REAL,
    metadata JSON,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_perf_date ON performance_snapshots(date DESC);
```

### migrations/003_add_fts5.sql

```sql
-- Full-text search on trade notes and analysis
CREATE VIRTUAL TABLE IF NOT EXISTS trades_fts USING fts5(
    notes,
    content='trades',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS trades_ai AFTER INSERT ON trades BEGIN
    INSERT INTO trades_fts(rowid, notes) VALUES (new.id, new.notes);
END;

CREATE TRIGGER IF NOT EXISTS trades_ad AFTER DELETE ON trades BEGIN
    INSERT INTO trades_fts(trades_fts, rowid, notes) VALUES('delete', old.id, old.notes);
END;

CREATE TRIGGER IF NOT EXISTS trades_au AFTER UPDATE ON trades BEGIN
    INSERT INTO trades_fts(trades_fts, rowid, notes) VALUES('delete', old.id, old.notes);
    INSERT INTO trades_fts(rowid, notes) VALUES (new.id, new.notes);
END;
```

---

## CI/CD

### .github/workflows/ci.yml

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

env:
  PYTHON_VERSION: "3.12"
  RUST_VERSION: "1.75"

jobs:
  python-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install ruff mypy
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/
      - run: mypy src/

  python-test:
    runs-on: ubuntu-latest
    needs: python-lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit/ -v --cov=src --cov-report=xml
      - uses: codecov/codecov-action@v4

  rust-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          toolchain: ${{ env.RUST_VERSION }}
          components: clippy
      - run: cd rust && cargo check --workspace
      - run: cd rust && cargo clippy --workspace -- -D warnings
      - run: cd rust && cargo test --workspace

  rust-build:
    runs-on: ubuntu-latest
    needs: rust-check
    strategy:
      matrix:
        target:
          - x86_64-unknown-linux-gnu
          - aarch64-unknown-linux-gnu
          - x86_64-apple-darwin
          - aarch64-apple-darwin
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          targets: ${{ matrix.target }}
      - uses: PyO3/maturin-action@v1
        with:
          target: ${{ matrix.target }}
          args: --release --out dist -m rust/Cargo.toml
      - uses: actions/upload-artifact@v4
        with:
          name: wheels-${{ matrix.target }}
          path: dist/

  docker-build:
    runs-on: ubuntu-latest
    needs: [python-test, rust-check]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile.python
          push: false
          tags: trading-super-agent:test
```

---

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/your-org/trading-super-agent.git
cd trading-super-agent

# 2. Copy environment file
cp .env.example .env
# Edit .env with your API keys

# 3. Full installation
make install

# 4. Run database migrations
make db-migrate

# 5. Start services
make docker-up
# OR run individually:
make api      # API server on :8000
make bot      # Telegram bot
make worker   # Background tasks

# 6. Run tests
make test-all

# 7. Start trading (paper mode by default)
make run
```

---

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Python as primary | 3.12 | Best ecosystem for trading + AI, async improvements |
| Rust for performance | WebSocket, tick processing | 10-100x faster than Python for hot paths |
| PyO3 over cffi | Native Rust bindings | Type-safe, ergonomic, zero-copy where possible |
| SQLite over PostgreSQL | Single-node simplicity | No server needed, FTS5 built-in, sufficient for personal trading |
| Redis over in-memory | Shared state | Works across processes, pub/sub for events |
| ChromaDB over Pinecone | Local-first | Free, no cloud dependency, good enough for pattern search |
| LiteLLM over direct API | Model abstraction | Swap models without code changes, unified fallback |
| vectorbt over backtrader | Speed | Vectorized operations, 100x faster than loop-based |
| FastAPI over Flask | Async + OpenAPI | Native async, automatic docs, WebSocket support |
| YAML over TOML | Strategy definitions | Better for nested configs, human-readable |
| structlog over logging | Structured data | JSON output, context binding, search-friendly |
| Celery over asyncio tasks | Battle-tested | Reliable task execution, monitoring, retries |

---

*Last updated: 2026-07-24*
