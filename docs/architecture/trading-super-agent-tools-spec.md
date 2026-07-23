# TRADING SUPER AGENT — TOOLS & EXCHANGE CONNECTIVITY SPECIFICATION

**Version:** 1.0.0
**Date:** 2026-07-24
**Status:** Architecture Design
**Stack:** Python 3.11+ (ccxt, pandas-ta, TA-Lib) / Rust 1.78+ (execution, streaming)
**Companion:** [Trading Super Agent Blueprint v2.0](./trading-super-agent-blueprint.md)

---

## TABLE OF CONTENTS

1. [Architecture Overview](#1-architecture-overview)
2. [Common Tool Interface Standard](#2-common-tool-interface-standard)
3. [Exchange Tools](#3-exchange-tools)
4. [Technical Analysis Tools](#4-technical-analysis-tools)
5. [Data Tools](#5-data-tools)
6. [Risk Tools](#6-risk-tools)
7. [Memory Tools](#7-memory-tools)
8. [Execution Tools](#8-execution-tools)
9. [MCP Tool Registration Pattern](#9-mcp-tool-registration-pattern)
10. [Permission System](#10-permission-system)
11. [Tool Sandboxing](#11-tool-sandboxing)
12. [Approval Gates](#12-approval-gates)
13. [Error Handling & Retry Matrix](#13-error-handling--retry-matrix)
14. [Rate Limiting Strategy](#14-rate-limiting-strategy)
15. [Performance Requirements](#15-performance-requirements)
16. [Dependency Map](#16-dependency-map)

---

## 1. ARCHITECTURE OVERVIEW

### 1.1 Dual-Language Design Rationale

```
┌─────────────────────────────────────────────────────────────────────┐
│                     TRADING SUPER AGENT                             │
│                                                                     │
│  ┌──────────────────────┐     ┌──────────────────────────────────┐  │
│  │   PYTHON LAYER       │     │   RUST LAYER                      │  │
│  │                      │     │                                    │  │
│  │  • Exchange Tools    │     │  • Price Streaming (WebSocket)    │  │
│  │  • Technical Analysis│     │  • Order Book Streaming           │  │
│  │  • Risk Tools        │◄───►│  • Smart Order Router             │  │
│  │  • Memory Tools      │  FFI│  • TWAP/VWAP Execution            │  │
│  │  • News/Sentiment    │     │  • Slippage Calculator            │  │
│  │  • MCP Tool Server   │     │  • Fill Monitor                   │  │
│  │                      │     │                                    │  │
│  └──────────┬───────────┘     └──────────────┬───────────────────┘  │
│             │                                │                      │
│             ▼                                ▼                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    SHARED INTERFACES                         │   │
│  │  PyO3 bindings  │  gRPC (localhost)  │  Shared memory (mmap) │   │
│  └──────────────────────────────────────────────────────────────┘   │
│             │                                │                      │
│             ▼                                ▼                      │
│  ┌──────────────────┐          ┌─────────────────────────────────┐  │
│  │  SQLite (trades) │          │  Redis (state, cache, pubsub)   │  │
│  └──────────────────┘          └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Python** handles:
- Exchange API communication via ccxt (mature, 100+ exchanges)
- Technical indicator computation (pandas-ta, TA-Lib)
- Risk calculations (deterministic, auditable)
- Trade memory and search (SQLite FTS5)
- MCP tool server (JSON-RPC over stdio/SSE)
- News and sentiment fetching

**Rust** handles:
- Real-time WebSocket price/orderbook streaming (tokio-tungstenite)
- Smart order routing across venues
- TWAP/VWAP execution algorithms
- Slippage calculation (needs <1ms latency)
- Fill monitoring (high-frequency event processing)
- PyO3 bindings exposing Rust functions to Python

### 1.2 Inter-Layer Communication

| Method | Use Case | Latency | Direction |
|--------|----------|---------|-----------|
| **PyO3** | Python calling Rust functions directly | ~1μs | Python → Rust |
| **gRPC (localhost)** | Rust streaming service → Python consumer | ~100μs | Rust → Python |
| **Redis PubSub** | Cross-process event broadcasting | ~500μs | Bidirectional |
| **Shared Memory (mmap)** | Ultra-low-latency price cache | ~10ns | Rust writes, Python reads |

### 1.3 Directory Structure

```
trading-super-agent/
├── tools/
│   ├── __init__.py                    # Tool registry & discovery
│   ├── base.py                        # BaseTool abstract class
│   ├── registry.py                    # ToolRegistry singleton
│   ├── mcp_server.py                  # MCP JSON-RPC server
│   ├── mcp_schemas.py                 # JSON Schema definitions for MCP
│   │
│   ├── exchange/                      # Exchange Tools
│   │   ├── __init__.py
│   │   ├── client.py                  # ccxt client manager
│   │   ├── get_price.py
│   │   ├── get_ohlcv.py
│   │   ├── get_orderbook.py
│   │   ├── place_order.py
│   │   ├── cancel_order.py
│   │   ├── get_positions.py
│   │   ├── get_balance.py
│   │   └── get_funding_rate.py
│   │
│   ├── analysis/                      # Technical Analysis Tools
│   │   ├── __init__.py
│   │   ├── indicators.py              # Shared indicator engine
│   │   ├── calculate_rsi.py
│   │   ├── calculate_macd.py
│   │   ├── calculate_bollinger.py
│   │   ├── calculate_atr.py
│   │   ├── calculate_ema.py
│   │   ├── calculate_volume_profile.py
│   │   └── detect_patterns.py
│   │
│   ├── data/                          # Data Tools
│   │   ├── __init__.py
│   │   ├── stream_prices.py           # Delegates to Rust
│   │   ├── stream_orderbook.py        # Delegates to Rust
│   │   ├── fetch_news.py
│   │   ├── fetch_social_sentiment.py
│   │   ├── fetch_onchain_data.py
│   │   └── fetch_macro_calendar.py
│   │
│   ├── risk/                          # Risk Tools
│   │   ├── __init__.py
│   │   ├── check_position_limits.py
│   │   ├── calculate_position_size.py
│   │   ├── get_portfolio_exposure.py
│   │   ├── get_correlation_matrix.py
│   │   └── get_drawdown_stats.py
│   │
│   ├── memory/                        # Memory Tools
│   │   ├── __init__.py
│   │   ├── db.py                      # SQLite connection manager
│   │   ├── log_trade.py
│   │   ├── search_trades.py
│   │   ├── get_strategy_performance.py
│   │   ├── get_lesson.py
│   │   └── update_regime_state.py
│   │
│   └── execution/                     # Execution Tools (Rust-backed)
│       ├── __init__.py
│       ├── smart_order_router.py      # Python wrapper for Rust SOR
│       ├── calculate_slippage.py
│       ├── twap_execute.py
│       └── monitor_fills.py
│
├── rust/                              # Rust workspace
│   ├── Cargo.toml
│   ├── crates/
│   │   ├── streaming/                 # WebSocket streaming
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── price_stream.rs
│   │   │   │   ├── orderbook_stream.rs
│   │   │   │   ├── connection_pool.rs
│   │   │   │   └── shared_cache.rs    # mmap price cache
│   │   │   └── Cargo.toml
│   │   │
│   │   ├── execution/                 # Execution engine
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── smart_router.rs
│   │   │   │   ├── slippage.rs
│   │   │   │   ├── twap.rs
│   │   │   │   ├── fill_monitor.rs
│   │   │   │   └── venue.rs
│   │   │   └── Cargo.toml
│   │   │
│   │   └── pyo3_bindings/             # Python bindings
│   │       ├── src/
│   │       │   └── lib.rs
│   │       └── Cargo.toml
│   │
│   └── proto/                         # gRPC definitions
│       └── streaming.proto
│
├── config/
│   ├── exchanges.yaml                 # Exchange credentials & endpoints
│   ├── risk_limits.yaml               # Hard risk limits
│   ├── tool_permissions.yaml          # Agent → tool permission map
│   └── rate_limits.yaml               # Per-exchange rate limits
│
└── tests/
    ├── tools/
    │   ├── test_exchange_tools.py
    │   ├── test_analysis_tools.py
    │   ├── test_risk_tools.py
    │   └── test_memory_tools.py
    └── rust/
        ├── streaming_tests.rs
        └── execution_tests.rs
```

---

## 2. COMMON TOOL INTERFACE STANDARD

### 2.1 Base Tool Protocol

Every tool implements this abstract interface. Non-negotiable.

```python
# tools/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time
import asyncio


class ToolPermission(Enum):
    """Permission level required to invoke this tool."""
    READ = "read"              # Free to call, no side effects
    ANALYSIS = "analysis"      # Computation, no market impact
    TRADE_PREVIEW = "trade_preview"  # Simulated trade (paper mode)
    TRADE_LIVE = "trade_live"  # Real money — requires approval
    ADMIN = "admin"            # System configuration changes


class ApprovalPolicy(Enum):
    """Whether tool invocation requires human approval."""
    AUTO = "auto"              # Execute immediately
    CONFIRM = "confirm"        # Show preview, wait for human OK
    ALWAYS_CONFIRM = "always"  # Always require confirmation
    BLOCKED = "blocked"        # Tool disabled in current context


@dataclass
class ToolResult:
    """Standardized return type for all tools."""
    success: bool
    data: dict[str, Any] | list | None = None
    error: str | None = None
    error_code: str | None = None      # Machine-readable error
    metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    tool_name: str = ""
    timestamp: float = field(default_factory=time.time)
    cached: bool = False
    source: str = ""                   # "live", "cache", "fallback"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "error_code": self.error_code,
            "metadata": self.metadata,
            "latency_ms": self.latency_ms,
            "tool_name": self.tool_name,
            "timestamp": self.timestamp,
            "cached": self.cached,
            "source": self.source,
        }


@dataclass
class ToolSchema:
    """MCP-compatible tool schema."""
    name: str
    description: str
    parameters: dict[str, Any]          # JSON Schema
    returns: dict[str, Any]             # JSON Schema
    permission: ToolPermission
    approval: ApprovalPolicy
    rate_limit: str | None = None       # e.g., "1200/min", "5/sec"
    timeout_ms: int = 5000
    retryable: bool = True
    idempotent: bool = True
    tags: list[str] = field(default_factory=list)


class BaseTool(ABC):
    """
    Abstract base class for all trading tools.

    Lifecycle:
    1. __init__() — configure, no I/O
    2. initialize() — async, connect to exchanges/DBs
    3. execute() — the actual work
    4. health_check() — liveness probe
    5. shutdown() — cleanup connections
    """

    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's schema for MCP registration."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with validated parameters."""
        ...

    async def initialize(self) -> None:
        """One-time async initialization (connections, caches)."""
        pass

    async def health_check(self) -> bool:
        """Return True if tool is operational."""
        return True

    async def shutdown(self) -> None:
        """Graceful cleanup."""
        pass

    def _wrap_timing(self, func):
        """Decorator to measure execution latency."""
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = await func(*args, **kwargs)
            result.latency_ms = (time.perf_counter() - start) * 1000
            result.tool_name = self.schema().name
            return result
        return wrapper
```

### 2.2 Parameter Validation Pattern

Every tool validates parameters before execution. No exceptions.

```python
# tools/validators.py
from dataclasses import dataclass
import re

SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]+/[A-Z0-9]+(:[A-Z]+)?$')  # BTC/USDT, BTC/USDT:USDT
TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}


@dataclass
class ValidationError:
    field: str
    message: str
    value: Any


def validate_symbol(symbol: str) -> list[ValidationError]:
    errors = []
    if not symbol:
        errors.append(ValidationError("symbol", "Symbol is required", symbol))
    elif not SYMBOL_PATTERN.match(symbol):
        errors.append(ValidationError(
            "symbol",
            f"Invalid symbol format '{symbol}'. Expected: BASE/QUOTE or BASE/QUOTE:SETTLE",
            symbol
        ))
    return errors


def validate_timeframe(timeframe: str) -> list[ValidationError]:
    errors = []
    if timeframe not in TIMEFRAMES:
        errors.append(ValidationError(
            "timeframe",
            f"Invalid timeframe '{timeframe}'. Allowed: {sorted(TIMEFRAMES)}",
            timeframe
        ))
    return errors


def validate_positive_float(name: str, value: float, min_val: float = 0.0) -> list[ValidationError]:
    errors = []
    if value is None:
        errors.append(ValidationError(name, f"{name} is required", value))
    elif not isinstance(value, (int, float)):
        errors.append(ValidationError(name, f"{name} must be numeric", value))
    elif value < min_val:
        errors.append(ValidationError(name, f"{name} must be >= {min_val}", value))
    return errors
```

### 2.3 Standard Error Codes

All tools use the same error code namespace:

| Code | Category | Retryable | Description |
|------|----------|-----------|-------------|
| `VALIDATION_ERROR` | Client | No | Invalid parameters |
| `EXCHANGE_UNAVAILABLE` | Infra | Yes | Exchange API down |
| `EXCHANGE_RATE_LIMIT` | Infra | Yes (with backoff) | Hit rate limit |
| `EXCHANGE_AUTH` | Config | No | Bad API key/secret |
| `EXCHANGE_INSUFFICIENT_FUNDS` | Market | No | Not enough balance |
| `EXCHANGE_ORDER_REJECTED` | Market | No | Exchange rejected order |
| `EXCHANGE_SYMBOL_NOT_FOUND` | Config | No | Symbol doesn't exist |
| `TIMEOUT` | Infra | Yes | Operation timed out |
| `NETWORK_ERROR` | Infra | Yes | Connection failure |
| `DATA_STALE` | Data | Yes | Cache expired, no fresh data |
| `RISK_VIOLATION` | Risk | No | Would breach risk limits |
| `DB_ERROR` | Infra | Yes | Database operation failed |
| `INTERNAL_ERROR` | System | No | Unexpected failure |
| `PERMISSION_DENIED` | Auth | No | Agent lacks permission |
| `APPROVAL_REQUIRED` | Policy | No | Needs human approval |
| `CIRCUIT_BREAKER_OPEN` | Protection | Yes | Too many recent failures |

---

## 3. EXCHANGE TOOLS

### 3.1 Exchange Client Manager

Centralized ccxt client management. One client per exchange, shared across tools.

```python
# tools/exchange/client.py
import ccxt.async_support as ccxt
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExchangeConfig:
    exchange_id: str
    api_key: str
    api_secret: str
    passphrase: str | None = None
    sandbox: bool = True
    rate_limit_per_minute: int = 1200
    max_concurrent_requests: int = 10
    timeout_ms: int = 30000
    retry_count: int = 3
    retry_backoff_ms: int = 1000


@dataclass
class CircuitBreaker:
    """Simple circuit breaker for exchange connections."""
    failure_threshold: int = 5
    recovery_timeout_s: int = 60
    _failure_count: int = field(default=0, init=False)
    _last_failure: float = field(default=0.0, init=False)
    _state: str = field(default="closed", init=False)  # closed, open, half_open

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            logger.warning(f"Circuit breaker OPEN after {self._failure_count} failures")

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    def allow_request(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.time() - self._last_failure > self.recovery_timeout_s:
                self._state = "half_open"
                return True
            return False
        return True  # half_open: allow one probe


class ExchangeClientManager:
    """
    Manages ccxt exchange client instances.

    Features:
    - Lazy initialization per exchange
    - Connection pooling via ccxt built-in
    - Circuit breaker per exchange
    - Automatic rate limit tracking
    - Sandbox mode enforcement for testing
    """

    def __init__(self, config_path: str = "config/exchanges.yaml"):
        self._clients: dict[str, ccxt.Exchange] = {}
        self._configs: dict[str, ExchangeConfig] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._config_path = config_path

    async def initialize(self) -> None:
        """Load configs and create exchange clients."""
        with open(self._config_path) as f:
            raw = yaml.safe_load(f)

        for exch_id, exch_cfg in raw.get("exchanges", {}).items():
            config = ExchangeConfig(
                exchange_id=exch_id,
                api_key=exch_cfg["api_key"],
                api_secret=exch_cfg["api_secret"],
                passphrase=exch_cfg.get("passphrase"),
                sandbox=exch_cfg.get("sandbox", True),
                rate_limit_per_minute=exch_cfg.get("rate_limit_per_minute", 1200),
                max_concurrent_requests=exch_cfg.get("max_concurrent_requests", 10),
                timeout_ms=exch_cfg.get("timeout_ms", 30000),
            )
            self._configs[exch_id] = config
            self._breakers[exch_id] = CircuitBreaker()
            self._semaphores[exch_id] = asyncio.Semaphore(config.max_concurrent_requests)

    async def get_client(self, exchange_id: str) -> ccxt.Exchange:
        """Get or create an exchange client. Thread-safe."""
        if exchange_id not in self._clients:
            config = self._configs.get(exchange_id)
            if not config:
                raise ValueError(f"Unknown exchange: {exchange_id}")

            exchange_class = getattr(ccxt, exchange_id)
            client = exchange_class({
                "apiKey": config.api_key,
                "secret": config.api_secret,
                "password": config.passphrase,
                "sandbox": config.sandbox,
                "timeout": config.timeout_ms,
                "enableRateLimit": True,
                "rateLimit": 60000 / config.rate_limit_per_minute,
            })

            if config.sandbox:
                await client.set_sandbox_mode(True)

            self._clients[exchange_id] = client
            logger.info(f"Initialized {exchange_id} client (sandbox={config.sandbox})")

        return self._clients[exchange_id]

    def get_breaker(self, exchange_id: str) -> CircuitBreaker:
        return self._breakers[exchange_id]

    def get_semaphore(self, exchange_id: str) -> asyncio.Semaphore:
        return self._semaphores[exchange_id]

    async def shutdown(self) -> None:
        """Close all exchange connections."""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
```

---

### 3.2 Tool: `get_price`

**Purpose:** Fetch current price and 24h statistics for a symbol.

| Field | Value |
|-------|-------|
| **Name** | `get_price` |
| **Language** | Python (ccxt) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | Exchange-specific (typically 1200/min) |
| **Timeout** | 3000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default | Validation |
|------|------|----------|---------|------------|
| `symbol` | `string` | Yes | — | Matches `^[A-Z0-9]+/[A-Z0-9]+(:[A-Z]+)?$` |
| `exchange` | `string` | No | `"binance"` | Must be in configured exchanges |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "exchange": "binance",
    "price": 67234.50,
    "bid": 67234.00,
    "ask": 67235.00,
    "spread": 1.00,
    "spread_bps": 0.015,
    "high_24h": 68100.00,
    "low_24h": 66500.00,
    "open_24h": 67000.00,
    "change_24h": 234.50,
    "change_pct_24h": 0.35,
    "volume_24h": 15234.67,
    "quote_volume_24h": 1024567890.12,
    "timestamp": "2026-07-24T00:45:00.000Z"
  },
  "latency_ms": 45.2,
  "tool_name": "get_price",
  "cached": false,
  "source": "live"
}
```

**Error Cases:**

| Error | Code | Behavior |
|-------|------|----------|
| Symbol not found | `EXCHANGE_SYMBOL_NOT_FOUND` | Return error, no retry |
| Exchange down | `EXCHANGE_UNAVAILABLE` | Retry 3x with backoff, then fail |
| Rate limited | `EXCHANGE_RATE_LIMIT` | Respect `Retry-After`, then retry |
| Timeout | `TIMEOUT` | Retry 2x, then return stale cache if available |

**Implementation:**

```python
# tools/exchange/get_price.py
import time
from tools.base import BaseTool, ToolResult, ToolSchema, ToolPermission, ApprovalPolicy
from tools.validators import validate_symbol
from tools.exchange.client import ExchangeClientManager


class GetPriceTool(BaseTool):
    def __init__(self, client_manager: ExchangeClientManager):
        self._clients = client_manager
        self._cache: dict[str, tuple[float, dict]] = {}  # symbol -> (timestamp, data)
        self._cache_ttl_s = 2.0  # 2-second cache for dedup

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="get_price",
            description="Get current price, bid/ask spread, and 24h statistics for a trading pair.",
            parameters={
                "type": "object",
                "required": ["symbol"],
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Trading pair (e.g., BTC/USDT, ETH/USDT:USDT)",
                        "pattern": "^[A-Z0-9]+/[A-Z0-9]+(:[A-Z]+)?$"
                    },
                    "exchange": {
                        "type": "string",
                        "description": "Exchange to query",
                        "default": "binance"
                    }
                }
            },
            returns={
                "type": "object",
                "properties": {
                    "price": {"type": "number"},
                    "bid": {"type": "number"},
                    "ask": {"type": "number"},
                    "spread_bps": {"type": "number"},
                    "high_24h": {"type": "number"},
                    "low_24h": {"type": "number"},
                    "volume_24h": {"type": "number"},
                    "change_pct_24h": {"type": "number"}
                }
            },
            permission=ToolPermission.READ,
            approval=ApprovalPolicy.AUTO,
            rate_limit="1200/min",
            timeout_ms=3000,
            retryable=True,
            idempotent=True,
            tags=["exchange", "market_data", "price"]
        )

    async def execute(self, symbol: str, exchange: str = "binance") -> ToolResult:
        # Validate
        errors = validate_symbol(symbol)
        if errors:
            return ToolResult(
                success=False,
                error="; ".join(e.message for e in errors),
                error_code="VALIDATION_ERROR"
            )

        # Check cache
        cache_key = f"{exchange}:{symbol}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl_s:
                return ToolResult(success=True, data=data, cached=True, source="cache")

        # Check circuit breaker
        breaker = self._clients.get_breaker(exchange)
        if not breaker.allow_request():
            return ToolResult(
                success=False,
                error=f"Circuit breaker open for {exchange}",
                error_code="CIRCUIT_BREAKER_OPEN"
            )

        # Execute with semaphore + retry
        semaphore = self._clients.get_semaphore(exchange)
        async with semaphore:
            for attempt in range(3):
                try:
                    client = await self._clients.get_client(exchange)
                    ticker = await client.fetch_ticker(symbol)

                    data = {
                        "symbol": symbol,
                        "exchange": exchange,
                        "price": ticker["last"],
                        "bid": ticker["bid"],
                        "ask": ticker["ask"],
                        "spread": ticker["ask"] - ticker["bid"] if ticker["ask"] and ticker["bid"] else None,
                        "spread_bps": (
                            ((ticker["ask"] - ticker["bid"]) / ticker["last"]) * 10000
                            if ticker["ask"] and ticker["bid"] and ticker["last"]
                            else None
                        ),
                        "high_24h": ticker["high"],
                        "low_24h": ticker["low"],
                        "open_24h": ticker["open"],
                        "change_24h": ticker.get("change"),
                        "change_pct_24h": ticker.get("percentage"),
                        "volume_24h": ticker["baseVolume"],
                        "quote_volume_24h": ticker["quoteVolume"],
                        "timestamp": ticker["isoTimestamp"] or ticker["datetime"],
                    }

                    self._cache[cache_key] = (time.time(), data)
                    breaker.record_success()
                    return ToolResult(success=True, data=data, source="live")

                except Exception as e:
                    breaker.record_failure()
                    if attempt < 2:
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                    return ToolResult(
                        success=False,
                        error=str(e),
                        error_code=self._classify_error(e)
                    )

    def _classify_error(self, e: Exception) -> str:
        from ccxt import ExchangeNotAvailable, RateLimitExceeded, AuthenticationError
        if isinstance(e, RateLimitExceeded):
            return "EXCHANGE_RATE_LIMIT"
        if isinstance(e, ExchangeNotAvailable):
            return "EXCHANGE_UNAVAILABLE"
        if isinstance(e, AuthenticationError):
            return "EXCHANGE_AUTH"
        return "INTERNAL_ERROR"
```

---

### 3.3 Tool: `get_ohlcv`

**Purpose:** Fetch OHLCV (Open/High/Low/Close/Volume) candle data.

| Field | Value |
|-------|-------|
| **Name** | `get_ohlcv` |
| **Language** | Python (ccxt) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | Exchange-specific |
| **Timeout** | 5000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default | Validation |
|------|------|----------|---------|------------|
| `symbol` | `string` | Yes | — | Valid symbol format |
| `timeframe` | `string` | Yes | — | One of: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M |
| `limit` | `integer` | No | `100` | 1–1000 |
| `since` | `integer` | No | `None` | Unix timestamp ms |
| `exchange` | `string` | No | `"binance"` | Configured exchange |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "exchange": "binance",
    "candles": [
      {
        "timestamp": 1721780400000,
        "datetime": "2026-07-24T00:00:00.000Z",
        "open": 67100.00,
        "high": 67300.00,
        "low": 67050.00,
        "close": 67234.50,
        "volume": 312.45
      }
    ],
    "count": 100,
    "oldest": "2026-07-20T01:00:00.000Z",
    "newest": "2026-07-24T00:00:00.000Z"
  }
}
```

**Implementation:**

```python
# tools/exchange/get_ohlcv.py
class GetOHLCVTool(BaseTool):
    def __init__(self, client_manager: ExchangeClientManager):
        self._clients = client_manager

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="get_ohlcv",
            description="Fetch OHLCV (candlestick) data for a symbol. Returns open, high, low, close, volume for each candle.",
            parameters={
                "type": "object",
                "required": ["symbol", "timeframe"],
                "properties": {
                    "symbol": {"type": "string", "description": "Trading pair"},
                    "timeframe": {
                        "type": "string",
                        "enum": ["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"],
                        "description": "Candle timeframe"
                    },
                    "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 1000},
                    "since": {"type": "integer", "description": "Start time as Unix timestamp (ms)"},
                    "exchange": {"type": "string", "default": "binance"}
                }
            },
            returns={"type": "object"},
            permission=ToolPermission.READ,
            approval=ApprovalPolicy.AUTO,
            rate_limit="300/min",
            timeout_ms=5000,
            retryable=True,
            idempotent=True,
            tags=["exchange", "market_data", "ohlcv"]
        )

    async def execute(self, symbol: str, timeframe: str, limit: int = 100,
                      since: int | None = None, exchange: str = "binance") -> ToolResult:
        # Validate
        errors = validate_symbol(symbol) + validate_timeframe(timeframe)
        if errors:
            return ToolResult(success=False, error="; ".join(e.message for e in errors),
                              error_code="VALIDATION_ERROR")

        limit = max(1, min(1000, limit))

        breaker = self._clients.get_breaker(exchange)
        if not breaker.allow_request():
            return ToolResult(success=False, error=f"Circuit breaker open for {exchange}",
                              error_code="CIRCUIT_BREAKER_OPEN")

        semaphore = self._clients.get_semaphore(exchange)
        async with semaphore:
            for attempt in range(3):
                try:
                    client = await self._clients.get_client(exchange)
                    ohlcv = await client.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

                    candles = [
                        {
                            "timestamp": c[0],
                            "datetime": client.iso8601(c[0]),
                            "open": c[1],
                            "high": c[2],
                            "low": c[3],
                            "close": c[4],
                            "volume": c[5],
                        }
                        for c in ohlcv
                    ]

                    breaker.record_success()
                    return ToolResult(success=True, data={
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "exchange": exchange,
                        "candles": candles,
                        "count": len(candles),
                        "oldest": candles[0]["datetime"] if candles else None,
                        "newest": candles[-1]["datetime"] if candles else None,
                    })

                except Exception as e:
                    breaker.record_failure()
                    if attempt < 2:
                        await asyncio.sleep(1.0 * (attempt + 1))
                    else:
                        return ToolResult(success=False, error=str(e),
                                          error_code=self._classify_error(e))
```

---

### 3.4 Tool: `get_orderbook`

**Purpose:** Fetch the order book (bids/asks) at specified depth.

| Field | Value |
|-------|-------|
| **Name** | `get_orderbook` |
| **Language** | Python (ccxt) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | 300/min |
| **Timeout** | 3000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default | Validation |
|------|------|----------|---------|------------|
| `symbol` | `string` | Yes | — | Valid symbol |
| `depth` | `integer` | No | `20` | 1–500 |
| `exchange` | `string` | No | `"binance"` | Configured exchange |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "exchange": "binance",
    "bids": [[67234.00, 1.5], [67233.00, 2.3], ...],
    "asks": [[67235.00, 0.8], [67236.00, 1.2], ...],
    "bid_total": 125.6,
    "ask_total": 98.4,
    "bid_ask_ratio": 1.28,
    "spread": 1.00,
    "spread_bps": 0.015,
    "mid_price": 67234.50,
    "vwap_bid": 67230.12,
    "vwap_ask": 67238.45,
    "timestamp": "2026-07-24T00:45:00.000Z"
  }
}
```

**Error Cases:** Same as `get_price`.

---

### 3.5 Tool: `place_order`

⚠️ **REQUIRES HUMAN APPROVAL** when in live mode.

| Field | Value |
|-------|-------|
| **Name** | `place_order` |
| **Language** | Python (ccxt) |
| **Permission** | `TRADE_LIVE` (live) / `TRADE_PREVIEW` (paper) |
| **Approval** | `ALWAYS_CONFIRM` (live) / `AUTO` (paper) |
| **Rate Limit** | 100/min |
| **Timeout** | 10000ms |
| **Retryable** | **No** (never auto-retry orders) |
| **Idempotent** | **No** (creates new order each call) |

**Parameters:**

| Name | Type | Required | Default | Validation |
|------|------|----------|---------|------------|
| `symbol` | `string` | Yes | — | Valid symbol |
| `side` | `string` | Yes | — | `"buy"` or `"sell"` |
| `type` | `string` | Yes | — | `"market"`, `"limit"`, `"stop"`, `"stop_limit"` |
| `size` | `number` | Yes | — | > 0, meets exchange minimum |
| `price` | `number` | Conditional | — | Required for limit/stop_limit |
| `stop_price` | `number` | Conditional | — | Required for stop/stop_limit |
| `time_in_force` | `string` | No | `"GTC"` | `"GTC"`, `"IOC"`, `"FOK"`, `"PO"` |
| `reduce_only` | `boolean` | No | `false` | — |
| `post_only` | `boolean` | No | `false` | — |
| `client_order_id` | `string` | No | auto-generated | Unique per exchange |
| `exchange` | `string` | No | `"binance"` | — |
| `dry_run` | `boolean` | No | `false` | If true, validate but don't submit |

**Returns:**

```json
{
  "success": true,
  "data": {
    "order_id": "12345678",
    "client_order_id": "agent_v1_abc123",
    "symbol": "BTC/USDT",
    "side": "buy",
    "type": "limit",
    "price": 67000.00,
    "size": 0.01,
    "filled": 0.0,
    "remaining": 0.01,
    "status": "open",
    "fee": null,
    "exchange": "binance",
    "timestamp": "2026-07-24T00:45:00.000Z",
    "dry_run": false
  }
}
```

**Pre-Execution Checks (MUST pass before order submission):**

```
1. Parameter validation (symbol, side, type, size, price)
2. Symbol exists on exchange → fetch market info
3. Size meets exchange minimum/maximum
4. Size meets lot size / precision rules
5. Price meets tick size rules (limit orders)
6. Risk gate: check_position_limits() → must return APPROVE
7. Risk gate: calculate_position_size() → size must not exceed computed max
8. Balance check: sufficient margin/free balance
9. Duplicate check: no existing identical open order
10. Paper mode: if dry_run=true, simulate fill and return
```

**Implementation:**

```python
# tools/exchange/place_order.py
class PlaceOrderTool(BaseTool):
    def __init__(self, client_manager: ExchangeClientManager, risk_checker, mode: str = "paper"):
        self._clients = client_manager
        self._risk = risk_checker
        self._mode = mode  # "paper" or "live"

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="place_order",
            description="Place a trading order. In live mode, requires human approval. Supports market, limit, stop, and stop_limit orders.",
            parameters={
                "type": "object",
                "required": ["symbol", "side", "type", "size"],
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "type": {"type": "string", "enum": ["market", "limit", "stop", "stop_limit"]},
                    "size": {"type": "number", "exclusiveMinimum": 0},
                    "price": {"type": "number", "description": "Required for limit/stop_limit"},
                    "stop_price": {"type": "number", "description": "Required for stop/stop_limit"},
                    "time_in_force": {"type": "string", "enum": ["GTC","IOC","FOK","PO"], "default": "GTC"},
                    "reduce_only": {"type": "boolean", "default": False},
                    "post_only": {"type": "boolean", "default": False},
                    "client_order_id": {"type": "string"},
                    "exchange": {"type": "string", "default": "binance"},
                    "dry_run": {"type": "boolean", "default": False}
                }
            },
            returns={"type": "object"},
            permission=ToolPermission.TRADE_LIVE if "live" else ToolPermission.TRADE_PREVIEW,
            approval=ApprovalPolicy.ALWAYS_CONFIRM if "live" else ApprovalPolicy.AUTO,
            rate_limit="100/min",
            timeout_ms=10000,
            retryable=False,
            idempotent=False,
            tags=["exchange", "trading", "order"]
        )

    async def execute(self, **kwargs) -> ToolResult:
        # 1. Validate parameters
        # 2. Run risk checks
        risk_result = await self._risk.check_position_limits(kwargs)
        if not risk_result.approved:
            return ToolResult(
                success=False,
                error=f"Risk check failed: {risk_result.reason}",
                error_code="RISK_VIOLATION",
                metadata={"risk_result": risk_result.to_dict()}
            )

        # 3. If dry_run, simulate
        if kwargs.get("dry_run"):
            return await self._simulate_order(**kwargs)

        # 4. Submit to exchange
        # 5. Log to trade memory
        # ... implementation continues
```

---

### 3.6 Tool: `cancel_order`

| Field | Value |
|-------|-------|
| **Name** | `cancel_order` |
| **Language** | Python (ccxt) |
| **Permission** | `TRADE_LIVE` |
| **Approval** | `AUTO` (cancellation is safe) |
| **Rate Limit** | 100/min |
| **Timeout** | 5000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `order_id` | `string` | Yes | — |
| `symbol` | `string` | Yes | — |
| `exchange` | `string` | No | `"binance"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "order_id": "12345678",
    "symbol": "BTC/USDT",
    "status": "canceled",
    "filled_before_cancel": 0.005,
    "exchange": "binance"
  }
}
```

**Error Cases:**

| Error | Code | Behavior |
|-------|------|----------|
| Order not found | `EXCHANGE_ORDER_REJECTED` | Already filled or never existed |
| Order already filled | `EXCHANGE_ORDER_REJECTED` | Return filled status |

---

### 3.7 Tool: `get_positions`

| Field | Value |
|-------|-------|
| **Name** | `get_positions` |
| **Language** | Python (ccxt) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | 300/min |
| **Timeout** | 5000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `exchange` | `string` | No | `"binance"` |
| `symbols` | `list[string]` | No | `None` (all positions) |

**Returns:**

```json
{
  "success": true,
  "data": {
    "positions": [
      {
        "symbol": "BTC/USDT:USDT",
        "side": "long",
        "size": 0.01,
        "notional": 672.35,
        "entry_price": 67000.00,
        "mark_price": 67234.50,
        "liquidation_price": 60000.00,
        "leverage": 10,
        "margin": 67.24,
        "unrealized_pnl": 2.35,
        "unrealized_pnl_pct": 0.35,
        "funding_rate": 0.0001,
        "timestamp": "2026-07-24T00:45:00.000Z"
      }
    ],
    "total_notional": 672.35,
    "total_unrealized_pnl": 2.35,
    "count": 1
  }
}
```

---

### 3.8 Tool: `get_balance`

| Field | Value |
|-------|-------|
| **Name** | `get_balance` |
| **Language** | Python (ccxt) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | 300/min |
| **Timeout** | 5000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `exchange` | `string` | No | `"binance"` |
| `currency` | `string` | No | `None` (all currencies) |

**Returns:**

```json
{
  "success": true,
  "data": {
    "exchange": "binance",
    "balances": {
      "USDT": {
        "total": 1000.00,
        "free": 932.76,
        "used": 67.24
      },
      "BTC": {
        "total": 0.01,
        "free": 0.0,
        "used": 0.01
      }
    },
    "total_equity_usd": 1672.35,
    "available_margin_usd": 932.76,
    "margin_used_usd": 67.24,
    "margin_ratio": 0.04,
    "timestamp": "2026-07-24T00:45:00.000Z"
  }
}
```

---

### 3.9 Tool: `get_funding_rate`

| Field | Value |
|-------|-------|
| **Name** | `get_funding_rate` |
| **Language** | Python (ccxt) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | 300/min |
| **Timeout** | 3000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `exchange` | `string` | No | `"binance"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT:USDT",
    "exchange": "binance",
    "funding_rate": 0.0001,
    "funding_rate_annualized": 10.95,
    "next_funding_time": "2026-07-24T04:00:00.000Z",
    "funding_interval_hours": 8,
    "predicted_rate": 0.00012,
    "mark_price": 67234.50,
    "index_price": 67230.00,
    "timestamp": "2026-07-24T00:45:00.000Z"
  }
}
```

---

## 4. TECHNICAL ANALYSIS TOOLS

### 4.1 Shared Indicator Engine

All TA tools share a common data-fetching and caching layer:

```python
# tools/analysis/indicators.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Any
import time


class IndicatorEngine:
    """
    Shared engine for technical indicator computation.

    - Fetches OHLCV via GetOHLCVTool (reuses exchange client)
    - Caches DataFrames per symbol/timeframe (5s TTL)
    - Normalizes column names: open, high, low, close, volume
    - Handles insufficient data gracefully
    """

    def __init__(self, ohlcv_tool, cache_ttl_s: float = 5.0):
        self._ohlcv = ohlcv_tool
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self._cache_ttl = cache_ttl_s

    async def get_dataframe(self, symbol: str, timeframe: str,
                            limit: int = 200, exchange: str = "binance") -> pd.DataFrame:
        """Fetch OHLCV and return as pandas DataFrame."""
        cache_key = f"{exchange}:{symbol}:{timeframe}:{limit}"

        if cache_key in self._cache:
            ts, df = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return df

        result = await self._ohlcv.execute(
            symbol=symbol, timeframe=timeframe, limit=limit, exchange=exchange
        )

        if not result.success:
            raise RuntimeError(f"Failed to fetch OHLCV: {result.error}")

        df = pd.DataFrame(result.data["candles"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df = df[["open", "high", "low", "close", "volume"]].astype(float)

        self._cache[cache_key] = (time.time(), df)
        return df
```

---

### 4.2 Tool: `calculate_rsi`

| Field | Value |
|-------|-------|
| **Name** | `calculate_rsi` |
| **Language** | Python (pandas-ta) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Rate Limit** | None (compute only) |
| **Timeout** | 2000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default | Validation |
|------|------|----------|---------|------------|
| `symbol` | `string` | Yes | — | Valid symbol |
| `period` | `integer` | No | `14` | 2–200 |
| `timeframe` | `string` | No | `"1h"` | Valid timeframe |
| `exchange` | `string` | No | `"binance"` | — |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "period": 14,
    "rsi": 62.34,
    "rsi_prev": 58.21,
    "rsi_change": 4.13,
    "zone": "neutral",
    "overbought": false,
    "oversold": false,
    "divergence_bullish": false,
    "divergence_bearish": false,
    "history": [58.21, 55.67, 52.34, ...],
    "timestamp": "2026-07-24T00:00:00.000Z"
  }
}
```

**Zone Classification:**

| RSI Range | Zone | Signal |
|-----------|------|--------|
| 0–30 | Oversold | Potential reversal long |
| 30–45 | Weak | Bearish momentum fading |
| 45–55 | Neutral | No signal |
| 55–70 | Strong | Bullish momentum |
| 70–100 | Overbought | Potential reversal short |

**Implementation:**

```python
# tools/analysis/calculate_rsi.py
class CalculateRSITool(BaseTool):
    def __init__(self, engine: IndicatorEngine):
        self._engine = engine

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="calculate_rsi",
            description="Calculate Relative Strength Index (RSI) for a symbol. Returns current RSI value, zone classification, and divergence signals.",
            parameters={
                "type": "object",
                "required": ["symbol"],
                "properties": {
                    "symbol": {"type": "string"},
                    "period": {"type": "integer", "default": 14, "minimum": 2, "maximum": 200},
                    "timeframe": {"type": "string", "default": "1h"},
                    "exchange": {"type": "string", "default": "binance"}
                }
            },
            returns={"type": "object"},
            permission=ToolPermission.ANALYSIS,
            approval=ApprovalPolicy.AUTO,
            timeout_ms=2000,
            tags=["analysis", "indicator", "momentum"]
        )

    async def execute(self, symbol: str, period: int = 14,
                      timeframe: str = "1h", exchange: str = "binance") -> ToolResult:
        errors = validate_symbol(symbol) + validate_timeframe(timeframe)
        if errors:
            return ToolResult(success=False, error="; ".join(e.message for e in errors),
                              error_code="VALIDATION_ERROR")

        try:
            df = await self._engine.get_dataframe(symbol, timeframe, limit=max(period * 5, 100), exchange=exchange)

            if len(df) < period + 1:
                return ToolResult(
                    success=False,
                    error=f"Insufficient data: need {period + 1} candles, got {len(df)}",
                    error_code="DATA_STALE"
                )

            rsi_series = ta.rsi(df["close"], length=period)
            rsi_val = rsi_series.iloc[-1]
            rsi_prev = rsi_series.iloc[-2]

            # Zone classification
            if rsi_val >= 70:
                zone = "overbought"
            elif rsi_val <= 30:
                zone = "oversold"
            elif rsi_val >= 55:
                zone = "strong"
            elif rsi_val <= 45:
                zone = "weak"
            else:
                zone = "neutral"

            # Simple divergence detection (price vs RSI over last 14 periods)
            price_higher_high = df["close"].iloc[-1] > df["close"].iloc[-period]
            rsi_higher_high = rsi_val > rsi_series.iloc[-period]
            divergence_bearish = price_higher_high and not rsi_higher_high
            divergence_bullish = not price_higher_high and rsi_higher_high

            return ToolResult(success=True, data={
                "symbol": symbol,
                "timeframe": timeframe,
                "period": period,
                "rsi": round(rsi_val, 2),
                "rsi_prev": round(rsi_prev, 2),
                "rsi_change": round(rsi_val - rsi_prev, 2),
                "zone": zone,
                "overbought": rsi_val >= 70,
                "oversold": rsi_val <= 30,
                "divergence_bullish": divergence_bullish,
                "divergence_bearish": divergence_bearish,
                "history": [round(x, 2) for x in rsi_series.dropna().tail(14).tolist()],
                "timestamp": df.index[-1].isoformat(),
            })

        except Exception as e:
            return ToolResult(success=False, error=str(e), error_code="INTERNAL_ERROR")
```

---

### 4.3 Tool: `calculate_macd`

| Field | Value |
|-------|-------|
| **Name** | `calculate_macd` |
| **Language** | Python (pandas-ta) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 2000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `fast` | `integer` | No | `12` |
| `slow` | `integer` | No | `26` |
| `signal` | `integer` | No | `9` |
| `timeframe` | `string` | No | `"1h"` |
| `exchange` | `string` | No | `"binance"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "macd_line": 45.23,
    "signal_line": 38.67,
    "histogram": 6.56,
    "histogram_prev": 4.12,
    "histogram_increasing": true,
    "crossover": "bullish",
    "crossover_strength": "strong",
    "above_zero": true,
    "timestamp": "2026-07-24T00:00:00.000Z"
  }
}
```

**Crossover Detection Logic:**

```python
def _detect_crossover(self, macd: pd.Series, signal: pd.Series) -> tuple[str, str]:
    """Detect MACD/Signal crossover and strength."""
    curr_macd, prev_macd = macd.iloc[-1], macd.iloc[-2]
    curr_signal, prev_signal = signal.iloc[-1], signal.iloc[-2]

    # Bullish crossover: MACD crosses above signal
    if prev_macd <= prev_signal and curr_macd > curr_signal:
        strength = "strong" if abs(curr_macd - curr_signal) > abs(prev_macd - prev_signal) else "weak"
        return "bullish", strength

    # Bearish crossover: MACD crosses below signal
    if prev_macd >= prev_signal and curr_macd < curr_signal:
        strength = "strong" if abs(curr_macd - curr_signal) > abs(prev_macd - prev_signal) else "weak"
        return "bearish", strength

    # No crossover
    if curr_macd > curr_signal:
        return "above_signal", "neutral"
    return "below_signal", "neutral"
```

---

### 4.4 Tool: `calculate_bollinger`

| Field | Value |
|-------|-------|
| **Name** | `calculate_bollinger` |
| **Language** | Python (pandas-ta) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 2000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `period` | `integer` | No | `20` |
| `std_dev` | `number` | No | `2.0` |
| `timeframe` | `string` | No | `"1h"` |
| `exchange` | `string` | No | `"binance"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "period": 20,
    "std_dev": 2.0,
    "upper_band": 68500.00,
    "middle_band": 67234.50,
    "lower_band": 65969.00,
    "bandwidth": 3.76,
    "bandwidth_pct": 0.0376,
    "percent_b": 0.65,
    "price_position": "in_upper_half",
    "squeeze": false,
    "expanding": true,
    "upper_touch_count_20": 3,
    "lower_touch_count_20": 1,
    "timestamp": "2026-07-24T00:00:00.000Z"
  }
}
```

**Derived Metrics:**

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| `bandwidth` | `(upper - lower) / middle` | Volatility measure |
| `percent_b` | `(close - lower) / (upper - lower)` | Position within bands (0=lower, 1=upper) |
| `squeeze` | `bandwidth < 0.02` | Low volatility, breakout imminent |
| `expanding` | `bandwidth > bandwidth_prev` | Volatility increasing |

---

### 4.5 Tool: `calculate_atr`

| Field | Value |
|-------|-------|
| **Name** | `calculate_atr` |
| **Language** | Python (pandas-ta) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 2000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `period` | `integer` | No | `14` |
| `timeframe` | `string` | No | `"1h"` |
| `exchange` | `string` | No | `"binance"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "period": 14,
    "atr": 456.78,
    "atr_pct": 0.68,
    "atr_prev": 423.12,
    "atr_change_pct": 7.95,
    "volatility_state": "expanding",
    "atr_high": 512.34,
    "atr_low": 389.01,
    "atr_percentile": 72,
    "stop_distance_1x": 456.78,
    "stop_distance_1_5x": 685.17,
    "stop_distance_2x": 913.56,
    "timestamp": "2026-07-24T00:00:00.000Z"
  }
}
```

**Critical for risk management.** ATR is used by:
- `calculate_position_size()` → stop distance
- `place_order()` → automatic stop-loss placement
- Strategy genome → `stop_loss_atr_multiple`

---

### 4.6 Tool: `calculate_ema`

| Field | Value |
|-------|-------|
| **Name** | `calculate_ema` |
| **Language** | Python (pandas-ta) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 2000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `period` | `integer` | No | `21` |
| `timeframe` | `string` | No | `"1h"` |
| `exchange` | `string` | No | `"binance"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "period": 21,
    "ema": 67100.00,
    "ema_prev": 67050.00,
    "price_vs_ema": "above",
    "price_distance_pct": 0.20,
    "ema_slope": "rising",
    "ema_slope_pct": 0.074,
    "timestamp": "2026-07-24T00:00:00.000Z"
  }
}
```

---

### 4.7 Tool: `calculate_volume_profile`

| Field | Value |
|-------|-------|
| **Name** | `calculate_volume_profile` |
| **Language** | Python (pandas-ta) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 3000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `timeframe` | `string` | No | `"1h"` |
| `bins` | `integer` | No | `50` |
| `exchange` | `string` | No | `"binance"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "poc_price": 67200.00,
    "poc_volume": 1234.56,
    "value_area_high": 67800.00,
    "value_area_low": 66600.00,
    "value_area_volume_pct": 70,
    "high_volume_nodes": [
      {"price": 67200, "volume": 1234.56, "type": "poc"},
      {"price": 67500, "volume": 987.34, "type": "hvn"}
    ],
    "low_volume_nodes": [
      {"price": 66900, "volume": 123.45, "type": "lvn"},
      {"price": 67700, "volume": 156.78, "type": "lvn"}
    ],
    "timestamp": "2026-07-24T00:00:00.000Z"
  }
}
```

---

### 4.8 Tool: `detect_patterns`

| Field | Value |
|-------|-------|
| **Name** | `detect_patterns` |
| **Language** | Python (pandas-ta) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 3000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `timeframe` | `string` | No | `"1h"` |
| `exchange` | `string` | No | `"binance"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "patterns_detected": [
      {
        "pattern": "bullish_engulfing",
        "candle_index": -1,
        "confidence": 0.85,
        "direction": "bullish",
        "description": "Bullish engulfing pattern at current candle"
      },
      {
        "pattern": "hammer",
        "candle_index": -3,
        "confidence": 0.72,
        "direction": "bullish",
        "description": "Hammer pattern 3 candles ago"
      }
    ],
    "pattern_count": 2,
    "overall_bias": "bullish",
    "bias_confidence": 0.78,
    "timestamp": "2026-07-24T00:00:00.000Z"
  }
}
```

**Patterns Detected:**

| Category | Patterns |
|----------|----------|
| Single Candle | Hammer, Inverted Hammer, Doji, Shooting Star, Marubozu |
| Double Candle | Bullish/Bearish Engulfing, Piercing Line, Dark Cloud Cover, Harami |
| Triple Candle | Morning/Evening Star, Three White Soldiers, Three Black Crows |
| Continuation | Rising/Falling Three Methods, Separating Lines |

---

## 5. DATA TOOLS

### 5.1 Tool: `stream_prices`

| Field | Value |
|-------|-------|
| **Name** | `stream_prices` |
| **Language** | Rust (tokio-tungstenite) → Python (PyO3) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | N/A (persistent connection) |
| **Timeout** | Continuous (heartbeat every 30s) |
| **Retryable** | Yes (auto-reconnect) |
| **Idempotent** | Yes (subscribe/unsubscribe) |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbols` | `list[string]` | Yes | — |
| `exchange` | `string` | No | `"binance"` |
| `callback` | `string` | No | `"shared_memory"` |
| `depth` | `integer` | No | `1` |

**Returns (initial):**

```json
{
  "success": true,
  "data": {
    "stream_id": "stream_abc123",
    "status": "connected",
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "exchange": "binance",
    "ws_url": "wss://stream.binance.com:9443/ws",
    "message_rate": "~500ms per update"
  }
}
```

**Returns (per update via callback/shared memory):**

```json
{
  "symbol": "BTC/USDT",
  "price": 67234.50,
  "bid": 67234.00,
  "ask": 67235.00,
  "volume_1m": 12.34,
  "timestamp_us": 1721780400000000
}
```

**Rust Implementation (Rust Streaming Crate):**

```rust
// rust/crates/streaming/src/price_stream.rs
use tokio_tungstenite::{connect_async, tungstenite::Message};
use futures_util::{StreamExt, SinkExt};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::broadcast;
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PriceUpdate {
    pub symbol: String,
    pub price: f64,
    pub bid: f64,
    pub ask: f64,
    pub volume_1m: f64,
    pub timestamp_us: u64,
}

pub struct PriceStream {
    exchange: String,
    symbols: Vec<String>,
    tx: broadcast::Sender<PriceUpdate>,
    shared_cache: Arc<SharedPriceCache>,
}

impl PriceStream {
    pub fn new(
        exchange: String,
        symbols: Vec<String>,
        cache: Arc<SharedPriceCache>,
    ) -> Self {
        let (tx, _) = broadcast::channel(1024);
        Self { exchange, symbols, tx, shared_cache: cache }
    }

    pub async fn start(&self) -> Result<(), Box<dyn std::error::Error>> {
        let streams: Vec<String> = self.symbols.iter()
            .map(|s| format!("{}@ticker", s.replace("/", "").to_lowercase()))
            .collect();

        let url = format!(
            "wss://stream.binance.com:9443/stream?streams={}",
            streams.join("/")
        );

        loop {
            match connect_async(&url).await {
                Ok((ws_stream, _)) => {
                    let (_, mut read) = ws_stream.split();
                    while let Some(msg) = read.next().await {
                        match msg {
                            Ok(Message::Text(text)) => {
                                if let Some(update) = self.parse_binance_ticker(&text) {
                                    // Update shared memory cache (10ns latency)
                                    self.shared_cache.update(&update.symbol, &update);
                                    // Broadcast to subscribers
                                    let _ = self.tx.send(update);
                                }
                            }
                            Ok(Message::Ping(d)) => { /* auto-pong handled */ }
                            Err(e) => {
                                eprintln!("WS error: {}, reconnecting...", e);
                                break;
                            }
                            _ => {}
                        }
                    }
                }
                Err(e) => {
                    eprintln!("Connection failed: {}, retrying in 5s...", e);
                    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                }
            }
        }
    }

    fn parse_binance_ticker(&self, text: &str) -> Option<PriceUpdate> {
        // Parse Binance combined stream format
        serde_json::from_str::<serde_json::Value>(text).ok().and_then(|v| {
            let data = v.get("data")?;
            Some(PriceUpdate {
                symbol: data.get("s")?.as_str()?.to_string(),
                price: data.get("c")?.as_str()?.parse().ok()?,
                bid: data.get("b")?.as_str()?.parse().ok()?,
                ask: data.get("a")?.as_str()?.parse().ok()?,
                volume_1m: data.get("v")?.as_str()?.parse().ok()?,
                timestamp_us: std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .ok()?
                    .as_micros() as u64,
            })
        })
    }

    pub fn subscribe(&self) -> broadcast::Receiver<PriceUpdate> {
        self.tx.subscribe()
    }
}
```

**Shared Memory Cache (mmap):**

```rust
// rust/crates/streaming/src/shared_cache.rs
use memmap2::MmapMut;
use std::sync::RwLock;
use std::collections::HashMap;

/// Lock-free shared memory price cache.
/// Python reads via mmap — zero-copy, ~10ns latency.
pub struct SharedPriceCache {
    mmap: RwLock<MmapMut>,
    offsets: HashMap<String, usize>,
}

#[repr(C, packed)]
struct PriceEntry {
    symbol: [u8; 16],    // Padded symbol
    price: f64,
    bid: f64,
    ask: f64,
    volume: f64,
    timestamp_us: u64,
    sequence: u64,       // Monotonic counter for consistency
}

impl SharedPriceCache {
    pub fn new(symbols: &[String]) -> Self {
        let size = symbols.len() * std::mem::size_of::<PriceEntry>();
        let mmap = MmapMut::map_anon(size).expect("Failed to create mmap");
        let offsets: HashMap<String, usize> = symbols.iter()
            .enumerate()
            .map(|(i, s)| (s.clone(), i * std::mem::size_of::<PriceEntry>()))
            .collect();
        Self { mmap: RwLock::new(mmap), offsets }
    }

    pub fn update(&self, symbol: &str, update: &PriceUpdate) {
        if let Some(&offset) = self.offsets.get(symbol) {
            let mut mmap = self.mmap.write().unwrap();
            let entry = unsafe {
                &mut *(mmap.as_mut_ptr().add(offset) as *mut PriceEntry)
            };
            entry.price = update.price;
            entry.bid = update.bid;
            entry.ask = update.ask;
            entry.volume = update.volume_1m;
            entry.timestamp_us = update.timestamp_us;
            entry.sequence += 1;
        }
    }

    pub fn read(&self, symbol: &str) -> Option<PriceEntry> {
        let offset = *self.offsets.get(symbol)?;
        let mmap = self.mmap.read().unwrap();
        let entry = unsafe {
            &*(mmap.as_ptr().add(offset) as *const PriceEntry)
        };
        Some(PriceEntry { ..*entry })
    }
}
```

---

### 5.2 Tool: `stream_orderbook`

| Field | Value |
|-------|-------|
| **Name** | `stream_orderbook` |
| **Language** | Rust → Python (PyO3) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Timeout** | Continuous |
| **Retryable** | Yes (auto-reconnect) |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbols` | `list[string]` | Yes | — |
| `depth` | `integer` | No | `20` |
| `speed` | `string` | No | `"100ms"` |
| `exchange` | `string` | No | `"binance"` |

**Returns (per update):**

```json
{
  "symbol": "BTC/USDT",
  "bids": [[67234.00, 1.5], [67233.00, 2.3], ...],
  "asks": [[67235.00, 0.8], [67236.00, 1.2], ...],
  "bid_total": 125.6,
  "ask_total": 98.4,
  "spread_bps": 0.015,
  "sequence": 12345678,
  "timestamp_us": 1721780400000000
}
```

---

### 5.3 Tool: `fetch_news`

| Field | Value |
|-------|-------|
| **Name** | `fetch_news` |
| **Language** | Python |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | 100/min |
| **Timeout** | 10000ms |
| **Retryable** | Yes |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbols` | `list[string]` | No | `None` |
| `sources` | `list[string]` | No | `["all"]` |
| `limit` | `integer` | No | `20` |
| `hours_back` | `integer` | No | `24` |

**Sources:**

| Source | Rate Limit | Coverage |
|--------|------------|----------|
| CryptoPanic API | 100/min | Crypto news aggregator |
| CoinDesk RSS | N/A | Major crypto news |
| The Block RSS | N/A | Institutional crypto |
| Bloomberg RSS | N/A | Macro/financial |
| Twitter Lists | 300/15min | KOL sentiment |

**Returns:**

```json
{
  "success": true,
  "data": {
    "articles": [
      {
        "title": "Bitcoin ETF sees record inflows",
        "source": "CoinDesk",
        "url": "https://...",
        "published": "2026-07-24T00:30:00Z",
        "sentiment": 0.72,
        "sentiment_label": "positive",
        "relevance": 0.95,
        "symbols": ["BTC/USDT"],
        "summary": "Spot Bitcoin ETFs recorded $1.2B in net inflows..."
      }
    ],
    "count": 15,
    "overall_sentiment": 0.65,
    "sources_queried": ["cryptopanic", "coindesk", "theblock"]
  }
}
```

---

### 5.4 Tool: `fetch_social_sentiment`

| Field | Value |
|-------|-------|
| **Name** | `fetch_social_sentiment` |
| **Language** | Python |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | 60/min |
| **Timeout** | 10000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `sources` | `list[string]` | No | `["twitter", "reddit"]` |
| `hours_back` | `integer` | No | `24` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT",
    "overall_sentiment": 0.68,
    "sentiment_label": "bullish",
    "fear_greed_index": 72,
    "fear_greed_label": "greed",
    "sources": {
      "twitter": {
        "sentiment": 0.72,
        "volume": 15234,
        "trending": true,
        "top_topics": ["ETF inflows", "halving", "institutional"]
      },
      "reddit": {
        "sentiment": 0.65,
        "volume": 3456,
        "subreddits": ["r/bitcoin", "r/cryptocurrency"]
      }
    },
    "whale_alerts": [
      {"type": "exchange_outflow", "amount_btc": 500, "exchange": "Coinbase"}
    ],
    "timestamp": "2026-07-24T00:45:00Z"
  }
}
```

---

### 5.5 Tool: `fetch_onchain_data`

| Field | Value |
|-------|-------|
| **Name** | `fetch_onchain_data` |
| **Language** | Python |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | 60/min |
| **Timeout** | 15000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `chain` | `string` | Yes | — |
| `metric` | `string` | Yes | — |
| `period` | `string` | No | `"24h"` |

**Supported Chains:** `bitcoin`, `ethereum`, `solana`, `bsc`

**Metrics:**

| Metric | Description | Source |
|--------|-------------|--------|
| `exchange_inflow` | Coins flowing to exchanges | Glassnode/OnChainMonkey |
| `exchange_outflow` | Coins leaving exchanges | Glassnode |
| `active_addresses` | Unique active addresses | Glassnode |
| `transaction_volume` | On-chain transfer volume | Glassnode |
| `nupl` | Net Unrealized Profit/Loss | Glassnode |
| `sopr` | Spent Output Profit Ratio | Glassnode |
| `exchange_reserves` | Total exchange holdings | CryptoQuant |
| `miner_revenue` | Miner revenue in USD | Glassnode |
| `hash_rate` | Network hash rate | Blockchain.com |
| `tvl` | Total Value Locked (DeFi) | DeFiLlama |

**Returns:**

```json
{
  "success": true,
  "data": {
    "chain": "bitcoin",
    "metric": "exchange_outflow",
    "value": 15234.56,
    "unit": "BTC",
    "change_24h": 12.5,
    "change_pct": 8.9,
    "percentile_90d": 85,
    "signal": "bullish",
    "description": "Large outflows from exchanges suggest accumulation",
    "timestamp": "2026-07-24T00:45:00Z"
  }
}
```

---

### 5.6 Tool: `fetch_macro_calendar`

| Field | Value |
|-------|-------|
| **Name** | `fetch_macro_calendar` |
| **Language** | Python |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Rate Limit** | 30/min |
| **Timeout** | 10000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `days_ahead` | `integer` | No | `7` |
| `impact` | `string` | No | `"high"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "events": [
      {
        "date": "2026-07-25",
        "time": "12:30 UTC",
        "event": "US GDP (Q2 Preliminary)",
        "impact": "high",
        "previous": "2.8%",
        "forecast": "2.5%",
        "currency": "USD",
        "crypto_impact": "high",
        "crypto_direction": "uncertain"
      },
      {
        "date": "2026-07-26",
        "time": "18:00 UTC",
        "event": "FOMC Rate Decision",
        "impact": "high",
        "previous": "5.25%",
        "forecast": "5.00%",
        "currency": "USD",
        "crypto_impact": "very_high",
        "crypto_direction": "bullish_if_cut"
      }
    ],
    "high_impact_count": 2,
    "next_event_in_hours": 36
  }
}
```

---

## 6. RISK TOOLS

All risk tools are **deterministic** — same inputs always produce same outputs. This is critical for auditing and reproducibility.

### 6.1 Tool: `check_position_limits`

| Field | Value |
|-------|-------|
| **Name** | `check_position_limits` |
| **Language** | Python |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 500ms |
| **Retryable** | No |
| **Idempotent** | Yes |

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `proposed_trade` | `object` | Yes | Trade to validate |

```json
{
  "proposed_trade": {
    "symbol": "BTC/USDT",
    "side": "buy",
    "size": 0.01,
    "price": 67000.00,
    "strategy": "momentum_breakout"
  }
}
```

**Returns:**

```json
{
  "success": true,
  "data": {
    "approved": true,
    "checks": [
      {"name": "max_position_size", "passed": true, "detail": "0.01 < max 0.05 BTC"},
      {"name": "max_portfolio_exposure", "passed": true, "detail": "67% < max 80%"},
      {"name": "max_correlated_exposure", "passed": true, "detail": "45% < max 60%"},
      {"name": "max_drawdown_check", "passed": true, "detail": "Current DD 3.2% < max 10%"},
      {"name": "max_concurrent_positions", "passed": true, "detail": "3 < max 5"},
      {"name": "daily_loss_limit", "passed": true, "detail": "Daily P&L: +2.3%"},
      {"name": "strategy_allowed", "passed": true, "detail": "Strategy active in current regime"},
      {"name": "exchange_balance", "passed": true, "detail": "Sufficient margin: $932.76 free"}
    ],
    "violations": [],
    "warnings": [],
    "reason": "All checks passed"
  }
}
```

**Risk Limits (from `config/risk_limits.yaml`):**

```yaml
risk_limits:
  # Position-level
  max_position_size_pct: 5.0       # Max 5% of equity per position
  max_position_notional: 5000.0    # Max $5000 notional

  # Portfolio-level
  max_portfolio_exposure_pct: 80.0  # Max 80% of equity deployed
  max_correlated_exposure_pct: 60.0 # Max 60% in correlated assets
  max_concurrent_positions: 5       # Max 5 open positions
  max_same_direction: 3             # Max 3 positions same side

  # Loss limits
  max_drawdown_pct: 10.0           # Kill switch at 10% drawdown
  daily_loss_limit_pct: 3.0        # Stop trading after 3% daily loss
  weekly_loss_limit_pct: 5.0       # Stop trading after 5% weekly loss

  # Strategy-level
  max_strategy_allocation_pct: 30.0 # Max 30% per strategy

  # Execution
  max_slippage_bps: 50             # Reject if expected slippage > 50bps
  min_liquidity_ratio: 10.0        # Order size < 1/10th of orderbook depth
```

---

### 6.2 Tool: `calculate_position_size`

| Field | Value |
|-------|-------|
| **Name** | `calculate_position_size` |
| **Language** | Python |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 500ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `equity` | `number` | No | Current balance |
| `risk_pct` | `number` | No | `1.0` |
| `stop_distance` | `number` | Yes | — |
| `entry_price` | `number` | Yes | — |
| `method` | `string` | No | `"fixed_risk"` |

**Sizing Methods:**

| Method | Formula | Use Case |
|--------|---------|----------|
| `fixed_risk` | `size = (equity × risk_pct) / stop_distance` | Standard |
| `kelly` | `size = equity × kelly_fraction` | Optimal growth |
| `volatility` | `size = (equity × target_vol) / (ATR × √time)` | Vol targeting |
| `equal_weight` | `size = equity / max_positions / price` | Diversified |

**Returns:**

```json
{
  "success": true,
  "data": {
    "method": "fixed_risk",
    "equity": 1000.00,
    "risk_pct": 1.0,
    "risk_amount": 10.00,
    "stop_distance": 456.78,
    "entry_price": 67000.00,
    "position_size_base": 0.0219,
    "position_size_quote": 1467.30,
    "notional": 1467.30,
    "leverage_required": 1.47,
    "max_loss": 10.00,
    "risk_reward_at_tp_2x": 2.0,
    "adjusted_for_limits": true,
    "limit_reason": "Capped at max_position_size_pct (5% = $50)"
  }
}
```

---

### 6.3 Tool: `get_portfolio_exposure`

| Field | Value |
|-------|-------|
| **Name** | `get_portfolio_exposure` |
| **Language** | Python |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Timeout** | 2000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `exchange` | `string` | No | `None` (all exchanges) |

**Returns:**

```json
{
  "success": true,
  "data": {
    "total_equity": 1000.00,
    "total_deployed": 672.35,
    "available_margin": 327.65,
    "deployment_pct": 67.24,
    "positions": [
      {
        "symbol": "BTC/USDT:USDT",
        "side": "long",
        "notional": 672.35,
        "equity_pct": 67.24,
        "unrealized_pnl": 2.35,
        "unrealized_pnl_pct": 0.35
      }
    ],
    "exposure_by_asset": {
      "BTC": 672.35,
      "ETH": 0,
      "SOL": 0
    },
    "exposure_by_direction": {
      "long": 672.35,
      "short": 0
    },
    "exposure_by_exchange": {
      "binance": 672.35
    },
    "margin_utilization_pct": 4.02,
    "timestamp": "2026-07-24T00:45:00Z"
  }
}
```

---

### 6.4 Tool: `get_correlation_matrix`

| Field | Value |
|-------|-------|
| **Name** | `get_correlation_matrix` |
| **Language** | Python (pandas) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 5000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbols` | `list[string]` | No | Current positions |
| `period` | `integer` | No | `30` (days) |
| `timeframe` | `string` | No | `"1d"` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "correlation_matrix": {
      "BTC/USDT": {"BTC/USDT": 1.0, "ETH/USDT": 0.87, "SOL/USDT": 0.72},
      "ETH/USDT": {"BTC/USDT": 0.87, "ETH/USDT": 1.0, "SOL/USDT": 0.81},
      "SOL/USDT": {"BTC/USDT": 0.72, "ETH/USDT": 0.81, "SOL/USDT": 1.0}
    },
    "avg_correlation": 0.80,
    "max_correlation_pair": ["BTC/USDT", "ETH/USDT"],
    "max_correlation": 0.87,
    "portfolio_diversification_score": 0.20,
    "highly_correlated_pairs": [
      {"pair": ["BTC/USDT", "ETH/USDT"], "correlation": 0.87, "warning": true}
    ],
    "period_days": 30,
    "data_points": 30
  }
}
```

---

### 6.5 Tool: `get_drawdown_stats`

| Field | Value |
|-------|-------|
| **Name** | `get_drawdown_stats` |
| **Language** | Python |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Timeout** | 2000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `period_days` | `integer` | No | `30` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "current_drawdown_pct": 3.2,
    "current_drawdown_abs": 32.00,
    "peak_equity": 1000.00,
    "current_equity": 968.00,
    "max_drawdown_pct": 5.8,
    "max_drawdown_date": "2026-07-15",
    "max_drawdown_duration_hours": 72,
    "current_drawdown_duration_hours": 24,
    "recovery_needed_pct": 3.31,
    "daily_pnl": [
      {"date": "2026-07-23", "pnl_pct": -0.5},
      {"date": "2026-07-22", "pnl_pct": 1.2}
    ],
    "win_rate_7d": 0.62,
    "win_rate_30d": 0.58,
    "sharpe_ratio_30d": 1.45,
    "sortino_ratio_30d": 2.1,
    "calmar_ratio_30d": 3.2,
    "profit_factor_30d": 1.8,
    "status": "normal",
    "alert_level": "none"
  }
}
```

**Alert Levels:**

| Level | Drawdown | Action |
|-------|----------|--------|
| `none` | < 5% | Normal operation |
| `warning` | 5–7% | Log warning, reduce position sizes by 50% |
| `critical` | 7–10% | Stop new trades, notify human |
| `kill_switch` | > 10% | Close ALL positions, halt all trading |

---

## 7. MEMORY TOOLS

### 7.1 Database Schema

```sql
-- trades.db — Main trade memory
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL,
    asset           TEXT NOT NULL,
    direction       TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    strategy_name   TEXT NOT NULL,
    signal_confidence REAL,
    regime_at_entry TEXT,
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    position_size   REAL NOT NULL,
    stop_loss       REAL,
    take_profit     REAL,
    pnl_absolute    REAL,
    pnl_percent     REAL,
    hold_duration   INTEGER,
    max_favorable   REAL,
    max_adverse     REAL,
    slippage        REAL,
    fees            REAL,
    exit_reason     TEXT,
    was_correct     BOOLEAN,
    market_context  JSON,
    regime_context  JSON,
    catalyst        TEXT,
    reflection      TEXT,
    lesson          TEXT,
    error_category  TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trades_strategy ON trades(strategy_name);
CREATE INDEX idx_trades_regime ON trades(regime_at_entry);
CREATE INDEX idx_trades_asset ON trades(asset);
CREATE INDEX idx_trades_time ON trades(timestamp);

-- FTS5 for full-text search
CREATE VIRTUAL TABLE trades_fts USING fts5(
    asset, strategy_name, catalyst, reflection, lesson, error_category,
    content='trades', content_rowid='id'
);

-- Trigger to keep FTS in sync
CREATE TRIGGER trades_ai AFTER INSERT ON trades BEGIN
    INSERT INTO trades_fts(rowid, asset, strategy_name, catalyst, reflection, lesson, error_category)
    VALUES (new.id, new.asset, new.strategy_name, new.catalyst, new.reflection, new.lesson, new.error_category);
END;

-- lessons.db — Extracted lessons
CREATE TABLE lessons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern         TEXT NOT NULL,
    lesson          TEXT NOT NULL,
    confidence      REAL NOT NULL,
    source_trade_ids JSON,
    times_applied   INTEGER DEFAULT 0,
    times_helped    INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE lessons_fts USING fts5(
    pattern, lesson, content='lessons', content_rowid='id'
);
```

---

### 7.2 Tool: `log_trade`

| Field | Value |
|-------|-------|
| **Name** | `log_trade` |
| **Language** | Python (SQLite) |
| **Permission** | `TRADE_PREVIEW` |
| **Approval** | `AUTO` |
| **Timeout** | 1000ms |
| **Retryable** | Yes |
| **Idempotent** | No |

**Parameters:**

| Name | Type | Required |
|------|------|----------|
| `trade_data` | `object` | Yes |

**Returns:**

```json
{
  "success": true,
  "data": {
    "trade_id": 1234,
    "logged": true,
    "strategy": "momentum_breakout",
    "asset": "BTC/USDT",
    "direction": "long"
  }
}
```

---

### 7.3 Tool: `search_trades`

| Field | Value |
|-------|-------|
| **Name** | `search_trades` |
| **Language** | Python (SQLite FTS5) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Timeout** | 2000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `query` | `string` | Yes | — |
| `limit` | `integer` | No | `20` |
| `filters` | `object` | No | `{}` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "trades": [
      {
        "id": 1234,
        "timestamp": "2026-07-23T14:30:00Z",
        "asset": "BTC/USDT",
        "direction": "long",
        "strategy": "momentum_breakout",
        "pnl_percent": 2.3,
        "was_correct": true,
        "lesson": "Breakout with volume confirmation works well in trending regimes",
        "relevance": 0.95
      }
    ],
    "total": 1,
    "query": "breakout volume trending"
  }
}
```

---

### 7.4 Tool: `get_strategy_performance`

| Field | Value |
|-------|-------|
| **Name** | `get_strategy_performance` |
| **Language** | Python |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Timeout** | 2000ms |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `strategy_id` | `string` | Yes | — |
| `period_days` | `integer` | No | `30` |

**Returns:**

```json
{
  "success": true,
  "data": {
    "strategy_id": "momentum_breakout",
    "period_days": 30,
    "total_trades": 47,
    "winning_trades": 28,
    "losing_trades": 19,
    "win_rate": 0.596,
    "avg_win_pct": 2.34,
    "avg_loss_pct": 1.12,
    "expectancy": 0.94,
    "profit_factor": 1.87,
    "max_drawdown_pct": 3.2,
    "sharpe_ratio": 1.67,
    "avg_hold_hours": 6.4,
    "best_trade_pct": 5.67,
    "worst_trade_pct": -2.34,
    "by_regime": {
      "trending_up": {"trades": 23, "win_rate": 0.65, "expectancy": 1.2},
      "volatile": {"trades": 12, "win_rate": 0.58, "expectancy": 0.8},
      "ranging": {"trades": 12, "win_rate": 0.50, "expectancy": 0.1}
    },
    "by_asset": {
      "BTC/USDT": {"trades": 25, "win_rate": 0.64, "expectancy": 1.1},
      "ETH/USDT": {"trades": 22, "win_rate": 0.55, "expectancy": 0.7}
    }
  }
}
```

---

### 7.5 Tool: `get_lesson`

| Field | Value |
|-------|-------|
| **Name** | `get_lesson` |
| **Language** | Python (SQLite FTS5) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Timeout** | 1000ms |

**Parameters:**

| Name | Type | Required |
|------|------|----------|
| `pattern` | `string` | Yes |
| `limit` | `integer` | No (default: 5) |

**Returns:**

```json
{
  "success": true,
  "data": {
    "lessons": [
      {
        "pattern": "breakout volume trending",
        "lesson": "Breakouts with >1.5x average volume in trending regimes have 68% win rate. Without volume, drops to 41%.",
        "confidence": 0.89,
        "source_trades": [1234, 1256, 1289],
        "times_applied": 23,
        "times_helped": 18
      }
    ]
  }
}
```

---

### 7.6 Tool: `update_regime_state`

| Field | Value |
|-------|-------|
| **Name** | `update_regime_state` |
| **Language** | Python (Redis) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 500ms |

**Parameters:**

| Name | Type | Required |
|------|------|----------|
| `regime` | `object` | Yes |

**Returns:**

```json
{
  "success": true,
  "data": {
    "previous_regime": "ranging",
    "new_regime": "trending_up",
    "confidence": 0.82,
    "updated_at": "2026-07-24T00:45:00Z",
    "persisted_to": ["redis", "regime_state.json"]
  }
}
```

---

## 8. EXECUTION TOOLS

All execution tools are backed by Rust for performance-critical paths.

### 8.1 Tool: `smart_order_router`

| Field | Value |
|-------|-------|
| **Name** | `smart_order_router` |
| **Language** | Rust (PyO3) |
| **Permission** | `TRADE_LIVE` |
| **Approval** | `ALWAYS_CONFIRM` |
| **Rate Limit** | 50/min |
| **Timeout** | 15000ms |
| **Retryable** | **No** |
| **Idempotent** | **No** |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `side` | `string` | Yes | — |
| `size` | `number` | Yes | — |
| `order_type` | `string` | No | `"market"` |
| `venues` | `list[string]` | No | All configured |
| `max_slippage_bps` | `number` | No | `50` |
| `urgency` | `string` | No | `"normal"` |

**Routing Algorithm:**

```
1. Fetch orderbook from all venues
2. Simulate fill on each venue
3. Calculate total cost per venue (price + fees + slippage)
4. If single venue has enough depth:
   → Route to cheapest venue
5. If no single venue has enough:
   → Split order across venues weighted by:
     - Depth available at each level
     - Fee structure
     - Historical fill quality
6. Validate total slippage < max_slippage_bps
7. Execute splits simultaneously
8. Monitor fills, reconcile
```

**Returns:**

```json
{
  "success": true,
  "data": {
    "order_id": "sor_abc123",
    "splits": [
      {"venue": "binance", "size": 0.007, "expected_price": 67234.50, "expected_slippage_bps": 5},
      {"venue": "okx", "size": 0.003, "expected_price": 67235.00, "expected_slippage_bps": 8}
    ],
    "total_size": 0.01,
    "expected_vwap": 67234.65,
    "expected_total_slippage_bps": 6,
    "expected_fees": 0.067,
    "expected_total_cost": 672.35,
    "urgency": "normal",
    "status": "pending_fill"
  }
}
```

---

### 8.2 Tool: `calculate_slippage`

| Field | Value |
|-------|-------|
| **Name** | `calculate_slippage` |
| **Language** | Rust (PyO3) |
| **Permission** | `ANALYSIS` |
| **Approval** | `AUTO` |
| **Timeout** | 1000ms |

**Parameters:**

| Name | Type | Required |
|------|------|----------|
| `order` | `object` | Yes |
| `orderbook` | `object` | Yes |

**Returns:**

```json
{
  "success": true,
  "data": {
    "expected_slippage_bps": 5.2,
    "expected_fill_price": 67238.00,
    "expected_vwap": 67237.50,
    "market_impact_bps": 2.1,
    "book_depth_consumed_pct": 8.5,
    "levels_crossed": 3,
    "warning": null,
    "recommendation": "size_ok"
  }
}
```

**Rust Implementation:**

```rust
// rust/crates/execution/src/slippage.rs
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct OrderRequest {
    pub symbol: String,
    pub side: String,  // "buy" | "sell"
    pub size: f64,
    pub order_type: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct OrderBookLevel {
    pub price: f64,
    pub size: f64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SlippageResult {
    pub expected_slippage_bps: f64,
    pub expected_fill_price: f64,
    pub expected_vwap: f64,
    pub market_impact_bps: f64,
    pub book_depth_consumed_pct: f64,
    pub levels_crossed: u32,
    pub warning: Option<String>,
    pub recommendation: String,
}

pub fn calculate_slippage(
    order: &OrderRequest,
    bids: &[OrderBookLevel],
    asks: &[OrderBookLevel],
) -> SlippageResult {
    let (levels, total_depth) = if order.side == "buy" {
        (asks, asks.iter().map(|l| l.size).sum::<f64>())
    } else {
        (bids, bids.iter().map(|l| l.size).sum::<f64>())
    };

    let mut remaining = order.size;
    let mut total_cost = 0.0;
    let mut levels_crossed = 0u32;

    for level in levels {
        if remaining <= 0.0 { break; }
        let fill = remaining.min(level.size);
        total_cost += fill * level.price;
        remaining -= fill;
        levels_crossed += 1;
    }

    let filled = order.size - remaining;
    let vwap = if filled > 0.0 { total_cost / filled } else { 0.0 };

    let best_price = if order.side == "buy" {
        asks.first().map(|l| l.price).unwrap_or(0.0)
    } else {
        bids.first().map(|l| l.price).unwrap_or(0.0)
    };

    let slippage_bps = if best_price > 0.0 {
        ((vwap - best_price).abs() / best_price) * 10000.0
    } else {
        0.0
    };

    let depth_consumed = if total_depth > 0.0 {
        (order.size / total_depth) * 100.0
    } else {
        100.0
    };

    // Market impact model (simplified Almgren-Chriss)
    let impact_bps = slippage_bps * 0.4;  // ~40% of total slippage is impact

    let (warning, recommendation) = if slippage_bps > 50.0 {
        (Some("High slippage expected".to_string()), "reduce_size".to_string())
    } else if depth_consumed > 50.0 {
        (Some("Order consumes >50% of visible book".to_string()), "split_order".to_string())
    } else if remaining > 0.0 {
        (Some("Insufficient book depth for full fill".to_string()), "partial_fill_expected".to_string())
    } else {
        (None, "size_ok".to_string())
    };

    SlippageResult {
        expected_slippage_bps: slippage_bps,
        expected_fill_price: vwap,
        expected_vwap: vwap,
        market_impact_bps: impact_bps,
        book_depth_consumed_pct: depth_consumed,
        levels_crossed,
        warning,
        recommendation,
    }
}
```

---

### 8.3 Tool: `twap_execute`

| Field | Value |
|-------|-------|
| **Name** | `twap_execute` |
| **Language** | Rust (PyO3) |
| **Permission** | `TRADE_LIVE` |
| **Approval** | `ALWAYS_CONFIRM` |
| **Timeout** | Duration of TWAP (max 3600000ms) |
| **Retryable** | No |

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `symbol` | `string` | Yes | — |
| `side` | `string` | Yes | — |
| `total_size` | `number` | Yes | — |
| `duration_seconds` | `integer` | Yes | — |
| `num_slices` | `integer` | No | `10` |
| `max_slippage_bps` | `number` | No | `30` |
| `exchange` | `string` | No | `"binance"` |

**Returns (initial):**

```json
{
  "success": true,
  "data": {
    "twap_id": "twap_abc123",
    "status": "running",
    "symbol": "BTC/USDT",
    "side": "buy",
    "total_size": 0.01,
    "slice_size": 0.001,
    "num_slices": 10,
    "interval_seconds": 60,
    "duration_seconds": 600,
    "started_at": "2026-07-24T00:45:00Z",
    "estimated_completion": "2026-07-24T00:55:00Z",
    "slices_completed": 0,
    "avg_fill_price": null,
    "total_filled": 0
  }
}
```

---

### 8.4 Tool: `monitor_fills`

| Field | Value |
|-------|-------|
| **Name** | `monitor_fills` |
| **Language** | Rust (PyO3) |
| **Permission** | `READ` |
| **Approval** | `AUTO` |
| **Timeout** | 5000ms |

**Parameters:**

| Name | Type | Required |
|------|------|----------|
| `order_id` | `string` | Yes |
| `exchange` | `string` | No |

**Returns:**

```json
{
  "success": true,
  "data": {
    "order_id": "12345678",
    "status": "partially_filled",
    "size": 0.01,
    "filled": 0.007,
    "remaining": 0.003,
    "avg_fill_price": 67236.00,
    "fills": [
      {"price": 67235.00, "size": 0.005, "timestamp": "2026-07-24T00:45:01Z", "fee": 0.003},
      {"price": 67237.50, "size": 0.002, "timestamp": "2026-07-24T00:45:02Z", "fee": 0.001}
    ],
    "total_fees": 0.004,
    "slippage_bps": 2.1,
    "elapsed_ms": 1500
  }
}
```

---

## 9. MCP TOOL REGISTRATION PATTERN

### 9.1 MCP Server Architecture

The Trading Super Agent exposes its tools via the **Model Context Protocol (MCP)**, allowing any MCP-compatible LLM agent to discover and invoke tools.

```
┌──────────────────────────────────────────────────────┐
│                  MCP SERVER                           │
│                                                      │
│  Transport: stdio (local) or SSE (remote)            │
│  Protocol: JSON-RPC 2.0                              │
│                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ tools/list  │  │ tools/call   │  │ ping       │  │
│  │ (discovery) │  │ (execution)  │  │ (health)   │  │
│  └──────┬──────┘  └──────┬───────┘  └────────────┘  │
│         │                │                           │
│         ▼                ▼                           │
│  ┌──────────────────────────────────────────────┐    │
│  │           ToolRegistry                        │    │
│  │                                               │    │
│  │  exchange/*  analysis/*  data/*  risk/*       │    │
│  │  memory/*    execution/*                      │    │
│  │                                               │    │
│  │  ┌─────────────────────────────────────────┐  │    │
│  │  │         Permission Filter                │  │    │
│  │  │  Check: agent role → tool permission     │  │    │
│  │  │  Check: approval policy                  │  │    │
│  │  └─────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### 9.2 MCP Tool Schema (JSON Schema)

Each tool registers with MCP using this schema format:

```json
{
  "name": "calculate_rsi",
  "description": "Calculate Relative Strength Index (RSI) for a symbol. Returns current RSI value, zone classification, and divergence signals.",
  "inputSchema": {
    "type": "object",
    "required": ["symbol"],
    "properties": {
      "symbol": {
        "type": "string",
        "description": "Trading pair (e.g., BTC/USDT)",
        "pattern": "^[A-Z0-9]+/[A-Z0-9]+(:[A-Z]+)?$"
      },
      "period": {
        "type": "integer",
        "description": "RSI period",
        "default": 14,
        "minimum": 2,
        "maximum": 200
      },
      "timeframe": {
        "type": "string",
        "description": "Candle timeframe",
        "default": "1h",
        "enum": ["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"]
      },
      "exchange": {
        "type": "string",
        "description": "Exchange to query",
        "default": "binance"
      }
    },
    "additionalProperties": false
  },
  "annotations": {
    "readOnlyHint": true,
    "openWorldHint": false,
    "permission": "analysis",
    "approval": "auto",
    "rateLimit": null,
    "timeoutMs": 2000,
    "retryable": true,
    "idempotent": true,
    "tags": ["analysis", "indicator", "momentum"]
  }
}
```

### 9.3 MCP Server Implementation

```python
# tools/mcp_server.py
import json
import sys
import asyncio
from typing import Any
from tools.registry import ToolRegistry
from tools.base import ToolPermission, ApprovalPolicy


class MCPServer:
    """
    MCP-compatible JSON-RPC 2.0 server.

    Supports:
    - tools/list: Discover all registered tools
    - tools/call: Execute a tool with parameters
    - ping: Health check

    Transports:
    - stdio: For local OpenClaw integration
    - SSE: For remote agent access (future)
    """

    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    async def handle_request(self, request: dict) -> dict:
        """Handle a single JSON-RPC 2.0 request."""
        method = request.get("method")
        params = request.get("params", {})
        req_id = request.get("id")

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "trading-super-agent",
                        "version": "1.0.0"
                    }
                }
            elif method == "tools/list":
                result = await self._list_tools()
            elif method == "tools/call":
                result = await self._call_tool(params)
            elif method == "ping":
                result = {}
            else:
                return self._error(req_id, -32601, f"Method not found: {method}")

            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        except Exception as e:
            return self._error(req_id, -32603, str(e))

    async def _list_tools(self) -> dict:
        """Return all registered tools in MCP format."""
        tools = []
        for name, tool in self._registry.all():
            schema = tool.schema()
            tools.append({
                "name": schema.name,
                "description": schema.description,
                "inputSchema": schema.parameters,
                "annotations": {
                    "readOnlyHint": schema.permission == ToolPermission.READ,
                    "openWorldHint": False,
                    "permission": schema.permission.value,
                    "approval": schema.approval.value,
                    "rateLimit": schema.rate_limit,
                    "timeoutMs": schema.timeout_ms,
                    "retryable": schema.retryable,
                    "idempotent": schema.idempotent,
                    "tags": schema.tags,
                }
            })
        return {"tools": tools}

    async def _call_tool(self, params: dict) -> dict:
        """Execute a tool and return the result."""
        name = params.get("name")
        arguments = params.get("arguments", {})

        tool = self._registry.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        # Permission check
        schema = tool.schema()
        if schema.approval == ApprovalPolicy.ALWAYS_CONFIRM:
            # Return approval request — don't execute yet
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "approval_required": True,
                        "tool": name,
                        "arguments": arguments,
                        "message": f"This tool requires human approval: {schema.description}"
                    })
                }],
                "isError": False
            }

        # Execute
        result = await tool.execute(**arguments)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps(result.to_dict())
            }],
            "isError": not result.success
        }

    def _error(self, req_id, code, message):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message}
        }

    async def run_stdio(self):
        """Run MCP server over stdio (stdin/stdout)."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            request = json.loads(line)
            response = await self.handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
```

### 9.4 Tool Registry

```python
# tools/registry.py
from typing import Any
from tools.base import BaseTool


class ToolRegistry:
    """
    Central registry for all tools.
    Supports registration, discovery, health checking, and graceful shutdown.
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._initialized = False

    def register(self, tool: BaseTool) -> None:
        """Register a tool. Must be called before initialize()."""
        name = tool.schema().name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all(self) -> list[tuple[str, BaseTool]]:
        return list(self._tools.items())

    def by_tag(self, tag: str) -> list[BaseTool]:
        return [t for _, t in self._tools.items() if tag in t.schema().tags]

    def by_permission(self, permission) -> list[BaseTool]:
        return [t for _, t in self._tools.items() if t.schema().permission == permission]

    async def initialize_all(self) -> None:
        """Initialize all registered tools."""
        for name, tool in self._tools.items():
            await tool.initialize()
        self._initialized = True

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all tools."""
        results = {}
        for name, tool in self._tools.items():
            try:
                results[name] = await tool.health_check()
            except Exception:
                results[name] = False
        return results

    async def shutdown_all(self) -> None:
        """Gracefully shut down all tools."""
        for name, tool in self._tools.items():
            try:
                await tool.shutdown()
            except Exception:
                pass  # Best effort cleanup
```

### 9.5 Full Registration Example

```python
# tools/__init__.py — bootstrap all tools
from tools.registry import ToolRegistry
from tools.exchange.client import ExchangeClientManager
from tools.exchange.get_price import GetPriceTool
from tools.exchange.get_ohlcv import GetOHLCVTool
from tools.exchange.get_orderbook import GetOrderbookTool
from tools.exchange.place_order import PlaceOrderTool
from tools.exchange.cancel_order import CancelOrderTool
from tools.exchange.get_positions import GetPositionsTool
from tools.exchange.get_balance import GetBalanceTool
from tools.exchange.get_funding_rate import GetFundingRateTool
from tools.analysis.indicators import IndicatorEngine
from tools.analysis.calculate_rsi import CalculateRSITool
from tools.analysis.calculate_macd import CalculateMACDTool
from tools.analysis.calculate_bollinger import CalculateBollingerTool
from tools.analysis.calculate_atr import CalculateATRTool
from tools.analysis.calculate_ema import CalculateEMATool
from tools.analysis.calculate_volume_profile import CalculateVolumeProfileTool
from tools.analysis.detect_patterns import DetectPatternsTool
from tools.risk.check_position_limits import CheckPositionLimitsTool
from tools.risk.calculate_position_size import CalculatePositionSizeTool
from tools.risk.get_portfolio_exposure import GetPortfolioExposureTool
from tools.risk.get_correlation_matrix import GetCorrelationMatrixTool
from tools.risk.get_drawdown_stats import GetDrawdownStatsTool
from tools.memory.db import TradeDatabase
from tools.memory.log_trade import LogTradeTool
from tools.memory.search_trades import SearchTradesTool
from tools.memory.get_strategy_performance import GetStrategyPerformanceTool
from tools.memory.get_lesson import GetLessonTool
from tools.memory.update_regime_state import UpdateRegimeStateTool


def create_registry(mode: str = "paper") -> ToolRegistry:
    """Create and populate the tool registry."""
    registry = ToolRegistry()

    # Shared dependencies
    client_manager = ExchangeClientManager()
    trade_db = TradeDatabase("data/trades.db")
    risk_checker = CheckPositionLimitsTool(trade_db)

    # Exchange Tools (8)
    registry.register(GetPriceTool(client_manager))
    registry.register(GetOHLCVTool(client_manager))
    registry.register(GetOrderbookTool(client_manager))
    registry.register(PlaceOrderTool(client_manager, risk_checker, mode))
    registry.register(CancelOrderTool(client_manager))
    registry.register(GetPositionsTool(client_manager))
    registry.register(GetBalanceTool(client_manager))
    registry.register(GetFundingRateTool(client_manager))

    # Analysis Tools (7)
    ohlcv_tool = registry.get("get_ohlcv")
    indicator_engine = IndicatorEngine(ohlcv_tool)
    registry.register(CalculateRSITool(indicator_engine))
    registry.register(CalculateMACDTool(indicator_engine))
    registry.register(CalculateBollingerTool(indicator_engine))
    registry.register(CalculateATRTool(indicator_engine))
    registry.register(CalculateEMATool(indicator_engine))
    registry.register(CalculateVolumeProfileTool(indicator_engine))
    registry.register(DetectPatternsTool(indicator_engine))

    # Data Tools (6) — Rust-backed tools would be registered here
    # registry.register(StreamPricesTool(...))
    # registry.register(StreamOrderbookTool(...))
    # registry.register(FetchNewsTool(...))
    # registry.register(FetchSocialSentimentTool(...))
    # registry.register(FetchOnchainDataTool(...))
    # registry.register(FetchMacroCalendarTool(...))

    # Risk Tools (5)
    registry.register(risk_checker)
    registry.register(CalculatePositionSizeTool())
    registry.register(GetPortfolioExposureTool(client_manager))
    registry.register(GetCorrelationMatrixTool(ohlcv_tool))
    registry.register(GetDrawdownStatsTool(trade_db))

    # Memory Tools (5)
    registry.register(LogTradeTool(trade_db))
    registry.register(SearchTradesTool(trade_db))
    registry.register(GetStrategyPerformanceTool(trade_db))
    registry.register(GetLessonTool(trade_db))
    registry.register(UpdateRegimeStateTool())

    # Execution Tools (4) — Rust-backed
    # registry.register(SmartOrderRouterTool(...))
    # registry.register(CalculateSlippageTool(...))
    # registry.register(TwapExecuteTool(...))
    # registry.register(MonitorFillsTool(...))

    return registry
```

---

## 10. PERMISSION SYSTEM

### 10.1 Agent Role Definitions

| Role | Description | Tools Accessible |
|------|-------------|------------------|
| `observer` | Read-only market data | `READ`, `ANALYSIS` |
| `analyst` | Full analysis suite | `READ`, `ANALYSIS` |
| `paper_trader` | Paper trading (simulated) | `READ`, `ANALYSIS`, `TRADE_PREVIEW` |
| `live_trader` | Live trading (real money) | All except `ADMIN` |
| `admin` | System configuration | All |

### 10.2 Permission Matrix

```yaml
# config/tool_permissions.yaml
roles:
  observer:
    allowed_permissions: [read, analysis]
    description: "Read-only access to market data and analysis tools"
    agents: ["sentiment_agent", "news_agent"]

  analyst:
    allowed_permissions: [read, analysis]
    description: "Full analysis capabilities, no trading"
    agents: ["technical_agent", "fundamental_agent"]

  paper_trader:
    allowed_permissions: [read, analysis, trade_preview]
    description: "Paper trading with simulated execution"
    agents: ["paper_portfolio_manager"]

  live_trader:
    allowed_permissions: [read, analysis, trade_preview, trade_live]
    description: "Live trading with real money"
    agents: ["portfolio_manager"]
    requires_2fa: true

  admin:
    allowed_permissions: [read, analysis, trade_preview, trade_live, admin]
    description: "Full system access"
    agents: ["system_admin"]
    requires_2fa: true
    requires_ip_whitelist: true

# Per-tool overrides
tool_overrides:
  place_order:
    # Extra approval required for orders > $1000
    conditional_approval:
      - condition: "order.notional > 1000"
        approval: "always_confirm"
        reason: "Large order requires manual approval"

  smart_order_router:
    # SOR always requires approval regardless of role
    approval: "always_confirm"

  # Emergency kill switch — always available to all roles
  cancel_order:
    permission: "read"  # Anyone can cancel
    approval: "auto"

# Rate limits per role
rate_limits:
  observer:
    get_price: "1200/min"
    get_ohlcv: "300/min"
  analyst:
    calculate_rsi: "unlimited"
  live_trader:
    place_order: "100/min"
```

### 10.3 Permission Enforcement

```python
# tools/permissions.py
import yaml
from tools.base import ToolPermission


class PermissionChecker:
    def __init__(self, config_path: str = "config/tool_permissions.yaml"):
        with open(config_path) as f:
            self._config = yaml.safe_load(f)
        self._role_map = {}
        for role, cfg in self._config["roles"].items():
            for agent in cfg["agents"]:
                self._role_map[agent] = role

    def check(self, agent_id: str, tool_permission: ToolPermission) -> bool:
        """Check if an agent has permission to use a tool."""
        role = self._role_map.get(agent_id)
        if not role:
            return False

        role_config = self._config["roles"][role]
        allowed = [ToolPermission(p) for p in role_config["allowed_permissions"]]
        return tool_permission in allowed

    def get_role(self, agent_id: str) -> str | None:
        return self._role_map.get(agent_id)
```

---

## 11. TOOL SANDBOXING

### 11.1 Isolation Strategy

```
┌──────────────────────────────────────────────────────┐
│                 TOOL SANDBOXING                       │
│                                                       │
│  Level 1: Process Isolation                           │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Each agent runs in its own asyncio task         │  │
│  │ Tools are shared but stateless                  │  │
│  │ Database connections are per-agent              │  │
│  └─────────────────────────────────────────────────┘  │
│                                                       │
│  Level 2: State Isolation                             │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Each agent has its own context dict             │  │
│  │ Cannot read another agent's context             │  │
│  │ Shared caches (Redis) are read-only per agent   │  │
│  └─────────────────────────────────────────────────┘  │
│                                                       │
│  Level 3: Resource Isolation                          │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Per-agent rate limiters                         │  │
│  │ Per-agent connection pools                      │  │
│  │ Per-agent memory budgets                        │  │
│  └─────────────────────────────────────────────────┘  │
│                                                       │
│  Level 4: Execution Isolation                         │
│  ┌─────────────────────────────────────────────────┐  │
│  │ No agent can modify another agent's config      │  │
│  │ No agent can read another agent's trade history │  │
│  │   (without explicit permission)                 │  │
│  │ Trade tools require explicit approval gate      │  │
│  └─────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### 11.2 Agent Context

```python
# tools/context.py
from dataclasses import dataclass, field
from typing import Any
import asyncio


@dataclass
class AgentContext:
    """Isolated context for a single agent."""
    agent_id: str
    role: str
    session_id: str
    permissions: set[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Per-agent rate limiters
    rate_limiters: dict[str, Any] = field(default_factory=dict)

    # Per-agent execution history (for auditing)
    execution_log: list[dict] = field(default_factory=list)

    def log_execution(self, tool_name: str, params: dict, result: dict):
        """Log tool execution for audit trail."""
        import time
        self.execution_log.append({
            "tool": tool_name,
            "params": params,
            "result_success": result.get("success"),
            "timestamp": time.time(),
        })
```

### 11.3 Sandboxed Tool Execution

```python
# tools/sandbox.py
import asyncio
import signal
from tools.base import BaseTool, ToolResult
from tools.context import AgentContext
from tools.permissions import PermissionChecker


class SandboxedExecutor:
    """
    Executes tools in a sandboxed environment.

    Guarantees:
    1. Permission check before execution
    2. Timeout enforcement
    3. Memory limit monitoring
    4. Execution logging
    5. Error isolation (one tool failure ≠ agent failure)
    """

    def __init__(self, permission_checker: PermissionChecker):
        self._permissions = permission_checker

    async def execute(
        self,
        tool: BaseTool,
        context: AgentContext,
        **kwargs
    ) -> ToolResult:
        """Execute a tool with full sandboxing."""

        # 1. Permission check
        schema = tool.schema()
        if not self._permissions.check(context.agent_id, schema.permission):
            return ToolResult(
                success=False,
                error=f"Agent '{context.agent_id}' lacks permission '{schema.permission.value}'",
                error_code="PERMISSION_DENIED"
            )

        # 2. Execute with timeout
        try:
            result = await asyncio.wait_for(
                tool.execute(**kwargs),
                timeout=schema.timeout_ms / 1000
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Tool '{schema.name}' timed out after {schema.timeout_ms}ms",
                error_code="TIMEOUT"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Tool '{schema.name}' failed: {str(e)}",
                error_code="INTERNAL_ERROR"
            )

        # 3. Log execution
        context.log_execution(schema.name, kwargs, result.to_dict())

        return result
```

---

## 12. APPROVAL GATES

### 12.1 Approval Flow

```
Agent calls tool
       │
       ▼
┌──────────────┐     ┌──────────────┐
│ Permission    │────►│ Approval     │
│ Check         │     │ Policy Check │
└──────────────┘     └──────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         ┌────────┐   ┌──────────┐  ┌──────────┐
         │  AUTO  │   │ CONFIRM  │  │ BLOCKED  │
         │        │   │          │  │          │
         │ Execute│   │ Show     │  │ Return   │
         │ now    │   │ preview, │  │ error    │
         │        │   │ wait for │  │          │
         │        │   │ human OK │  │          │
         └────────┘   └──────────┘  └──────────┘
```

### 12.2 Tools Requiring Approval

| Tool | Approval | Trigger | Human Action |
|------|----------|---------|--------------|
| `place_order` | `ALWAYS_CONFIRM` | Any live order | Review order details, approve/reject |
| `smart_order_router` | `ALWAYS_CONFIRM` | Any SOR execution | Review routing plan, approve/reject |
| `twap_execute` | `ALWAYS_CONFIRM` | Any TWAP | Review slice plan, approve/reject |
| `cancel_order` | `AUTO` | — | — |
| `get_*` (read) | `AUTO` | — | — |
| `calculate_*` | `AUTO` | — | — |
| `log_trade` | `AUTO` | — | — |

### 12.3 Approval Request Format

```json
{
  "type": "approval_request",
  "id": "approval_abc123",
  "tool": "place_order",
  "agent": "portfolio_manager",
  "timestamp": "2026-07-24T00:45:00Z",
  "arguments": {
    "symbol": "BTC/USDT",
    "side": "buy",
    "type": "limit",
    "size": 0.01,
    "price": 67000.00
  },
  "preview": {
    "notional_value": "670.00 USDT",
    "estimated_fees": "0.67 USDT",
    "max_loss": "10.00 USDT (1% of equity)",
    "risk_check": "PASSED (8/8 checks)",
    "current_exposure_after": "72.4%",
    "expected_slippage": "3.2 bps"
  },
  "risk_assessment": {
    "position_size_pct": 6.7,
    "within_limits": true,
    "warnings": []
  },
  "timeout_seconds": 300,
  "auto_reject_after_timeout": true
}
```

### 12.4 Approval Implementation

```python
# tools/approval.py
import asyncio
import uuid
from dataclasses import dataclass
from typing import Callable, Awaitable
from tools.base import ToolResult


@dataclass
class ApprovalRequest:
    id: str
    tool_name: str
    agent_id: str
    arguments: dict
    preview: dict
    timeout_seconds: int = 300
    future: asyncio.Future = None

    def __post_init__(self):
        self.future = asyncio.get_event_loop().create_future()


class ApprovalGate:
    """
    Manages human approval for sensitive tool invocations.

    Supports:
    - Telegram inline buttons for mobile approval
    - CLI approval for local development
    - Auto-reject after timeout
    - Batch approval for similar orders
    """

    def __init__(self, notify_callback: Callable[[ApprovalRequest], Awaitable[None]]):
        self._notify = notify_callback
        self._pending: dict[str, ApprovalRequest] = {}

    async def request_approval(
        self,
        tool_name: str,
        agent_id: str,
        arguments: dict,
        preview: dict,
        timeout_seconds: int = 300
    ) -> ToolResult:
        """Request human approval. Blocks until approved/rejected/timeout."""

        request = ApprovalRequest(
            id=f"approval_{uuid.uuid4().hex[:8]}",
            tool_name=tool_name,
            agent_id=agent_id,
            arguments=arguments,
            preview=preview,
            timeout_seconds=timeout_seconds,
        )

        self._pending[request.id] = request

        # Notify human (Telegram, Slack, etc.)
        await self._notify(request)

        # Wait for approval or timeout
        try:
            approved = await asyncio.wait_for(
                request.future,
                timeout=timeout_seconds
            )

            if approved:
                return ToolResult(
                    success=True,
                    data={"approved": True, "approval_id": request.id}
                )
            else:
                return ToolResult(
                    success=False,
                    error="Order rejected by human",
                    error_code="APPROVAL_REJECTED",
                    metadata={"approval_id": request.id}
                )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Approval timed out after {timeout_seconds}s",
                error_code="APPROVAL_TIMEOUT",
                metadata={"approval_id": request.id}
            )
        finally:
            self._pending.pop(request.id, None)

    def approve(self, approval_id: str) -> bool:
        """Called when human approves via Telegram/CLI."""
        request = self._pending.get(approval_id)
        if request and not request.future.done():
            request.future.set_result(True)
            return True
        return False

    def reject(self, approval_id: str) -> bool:
        """Called when human rejects via Telegram/CLI."""
        request = self._pending.get(approval_id)
        if request and not request.future.done():
            request.future.set_result(False)
            return True
        return False
```

---

## 13. ERROR HANDLING & RETRY MATRIX

### 13.1 Retry Strategy

```python
# tools/retry.py
import asyncio
import random
from dataclasses import dataclass
from typing import Callable, Awaitable, Type


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ms: float = 1000
    max_delay_ms: float = 30000
    backoff_factor: float = 2.0
    jitter: bool = True
    retryable_errors: set[str] = None

    def __post_init__(self):
        if self.retryable_errors is None:
            self.retryable_errors = {
                "EXCHANGE_UNAVAILABLE",
                "EXCHANGE_RATE_LIMIT",
                "TIMEOUT",
                "NETWORK_ERROR",
                "DB_ERROR",
                "CIRCUIT_BREAKER_OPEN",
            }


# Pre-defined retry policies per tool category
RETRY_POLICIES = {
    "exchange/read": RetryPolicy(max_attempts=3, base_delay_ms=1000),
    "exchange/write": RetryPolicy(max_attempts=0),  # Never retry orders
    "analysis": RetryPolicy(max_attempts=2, base_delay_ms=500),
    "data": RetryPolicy(max_attempts=3, base_delay_ms=2000),
    "risk": RetryPolicy(max_attempts=0),  # Deterministic, no retry needed
    "memory": RetryPolicy(max_attempts=2, base_delay_ms=500),
    "execution": RetryPolicy(max_attempts=0),  # Never retry execution
}


async def with_retry(
    func: Callable[..., Awaitable],
    policy: RetryPolicy,
    *args, **kwargs
):
    """Execute a function with retry logic."""
    last_error = None

    for attempt in range(policy.max_attempts + 1):
        try:
            result = await func(*args, **kwargs)

            # Check if result indicates a retryable error
            if hasattr(result, 'error_code') and result.error_code:
                if result.error_code in policy.retryable_errors and attempt < policy.max_attempts:
                    delay = policy.base_delay_ms * (policy.backoff_factor ** attempt)
                    if policy.jitter:
                        delay *= (0.5 + random.random())
                    delay = min(delay, policy.max_delay_ms)
                    await asyncio.sleep(delay / 1000)
                    continue

            return result

        except Exception as e:
            last_error = e
            if attempt < policy.max_attempts:
                delay = policy.base_delay_ms * (policy.backoff_factor ** attempt)
                if policy.jitter:
                    delay *= (0.5 + random.random())
                delay = min(delay, policy.max_delay_ms)
                await asyncio.sleep(delay / 1000)

    raise last_error
```

### 13.2 Error Classification Rules

| Error Type | Examples | Retry? | Backoff | Alert? |
|------------|----------|--------|---------|--------|
| **Rate Limit** | HTTP 429, `RateLimitExceeded` | Yes | Respect `Retry-After` header | No (expected) |
| **Exchange Down** | HTTP 503, `ExchangeNotAvailable` | Yes | Exponential, 1–30s | Yes (after 3 failures) |
| **Auth Failure** | HTTP 401, `AuthenticationError` | **No** | — | **Yes (immediate)** |
| **Order Rejected** | `InvalidOrder`, `InsufficientFunds` | **No** | — | Yes |
| **Timeout** | `RequestTimeout` | Yes | 2x per attempt | Yes (after 2 failures) |
| **Network** | `ConnectionError`, DNS failure | Yes | Exponential, 1–30s | Yes (after 3 failures) |
| **Data Stale** | Cache expired, no fresh data | Yes (refetch) | 0s (immediate) | No |
| **Risk Violation** | Position limit, drawdown limit | **No** | — | **Yes (immediate)** |
| **Internal** | Unexpected exceptions | **No** | — | **Yes (immediate)** |

### 13.3 Circuit Breaker Configuration

```python
CIRCUIT_BREAKER_CONFIG = {
    "exchange": {
        "failure_threshold": 5,      # Open after 5 consecutive failures
        "recovery_timeout_s": 60,    # Try again after 60s
        "half_open_max_calls": 1,    # One probe call in half-open
    },
    "data_service": {
        "failure_threshold": 3,
        "recovery_timeout_s": 30,
        "half_open_max_calls": 1,
    },
    "database": {
        "failure_threshold": 3,
        "recovery_timeout_s": 10,
        "half_open_max_calls": 1,
    }
}
```

---

## 14. RATE LIMITING STRATEGY

### 14.1 Exchange Rate Limits

| Exchange | Public Endpoints | Private Endpoints | WebSocket |
|----------|-----------------|-------------------|-----------|
| Binance | 1200/min | 1200/min | 5 msgs/sec per stream |
| OKX | 20/2s | 20/2s | 10 msgs/sec |
| Bybit | 120/min | 60/min | 10 msgs/sec |
| Coinbase | 10/sec | 10/sec | 8 msgs/sec |

### 14.2 Rate Limiter Implementation

```python
# tools/rate_limiter.py
import asyncio
import time
from collections import deque


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter.

    Supports:
    - Per-exchange limits
    - Per-tool limits
    - Per-agent limits
    - Burst allowances
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """
        Acquire a rate limit slot.
        Returns delay in seconds to wait (0 if no wait needed).
        """
        async with self._lock:
            now = time.time()
            cutoff = now - self._window

            # Remove expired entries
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

            if len(self._timestamps) >= self._max:
                # Need to wait
                oldest = self._timestamps[0]
                wait = oldest + self._window - now
                return max(0, wait)

            self._timestamps.append(now)
            return 0

    async def wait_and_acquire(self) -> None:
        """Wait if necessary, then acquire a slot."""
        delay = await self.acquire()
        if delay > 0:
            await asyncio.sleep(delay)
            await self.acquire()


# Pre-configured rate limiters per exchange
EXCHANGE_LIMITERS = {
    "binance": {
        "public": SlidingWindowRateLimiter(1200, 60),
        "private": SlidingWindowRateLimiter(1200, 60),
    },
    "okx": {
        "public": SlidingWindowRateLimiter(20, 2),
        "private": SlidingWindowRateLimiter(20, 2),
    },
    "bybit": {
        "public": SlidingWindowRateLimiter(120, 60),
        "private": SlidingWindowRateLimiter(60, 60),
    },
}
```

### 14.3 Tool-Level Rate Limits

| Tool Category | Limit | Window | Notes |
|---------------|-------|--------|-------|
| `get_price` | Exchange-specific | 1 min | Cached for 2s |
| `get_ohlcv` | 300/min | 1 min | Cached for 5s |
| `place_order` | 100/min | 1 min | Hard limit |
| `calculate_*` | Unlimited | — | Compute only |
| `stream_*` | 1 connection/symbol | — | Persistent |
| `fetch_news` | 100/min | 1 min | External API limit |
| `fetch_social` | 60/min | 1 min | External API limit |

---

## 15. PERFORMANCE REQUIREMENTS

### 15.1 Latency Budgets

| Tool | Target (p50) | Target (p99) | Max Acceptable |
|------|-------------|-------------|----------------|
| `get_price` | <50ms | <200ms | 3000ms |
| `get_ohlcv` | <100ms | <500ms | 5000ms |
| `get_orderbook` | <50ms | <200ms | 3000ms |
| `calculate_rsi` | <10ms | <50ms | 2000ms |
| `calculate_macd` | <10ms | <50ms | 2000ms |
| `calculate_bollinger` | <10ms | <50ms | 2000ms |
| `calculate_atr` | <5ms | <20ms | 2000ms |
| `calculate_ema` | <5ms | <20ms | 2000ms |
| `place_order` | <200ms | <1000ms | 10000ms |
| `cancel_order` | <100ms | <500ms | 5000ms |
| `stream_prices` (read) | <1ms | <5ms | — |
| `stream_orderbook` (read) | <1ms | <5ms | — |
| `calculate_slippage` | <1ms | <5ms | 1000ms |
| `check_position_limits` | <5ms | <20ms | 500ms |
| `log_trade` | <10ms | <50ms | 1000ms |
| `search_trades` | <50ms | <200ms | 2000ms |

### 15.2 Throughput Requirements

| Operation | Target | Notes |
|-----------|--------|-------|
| Price updates processed | 1000/sec | All symbols combined |
| Order book updates | 500/sec | Per symbol |
| Indicator calculations | 100/sec | Batch capable |
| Trade logs written | 50/sec | SQLite with WAL mode |
| FTS searches | 20/sec | Concurrent |

### 15.3 Resource Budgets

| Resource | Limit | Notes |
|----------|-------|-------|
| Python memory | 512MB | Per process |
| Rust memory | 256MB | Streaming service |
| SQLite DB size | 1GB | Auto-archive older trades |
| Redis memory | 128MB | Cache + pubsub |
| WebSocket connections | 10 | Per exchange |
| File descriptors | 256 | Per process |
| CPU cores | 2 | Python + Rust combined |

---

## 16. DEPENDENCY MAP

### 16.1 Python Dependencies

```
# requirements.txt
ccxt==4.4.20              # Exchange connectivity
pandas==2.2.3             # Data manipulation
pandas-ta==0.3.14b1       # Technical indicators
numpy==2.0.2              # Numerical computing
aiosqlite==0.20.0         # Async SQLite
redis[hiredis]==5.2.1     # Redis client
pyyaml==6.0.2             # Config parsing
httpx==0.28.1             # Async HTTP
mcp==1.0.0                # MCP SDK
pydantic==2.10.3          # Data validation
structlog==24.4.0         # Structured logging
prometheus-client==0.21.1 # Metrics
```

### 16.2 Rust Dependencies

```toml
# Cargo.toml
[workspace]
members = ["crates/streaming", "crates/execution", "crates/pyo3_bindings"]

[workspace.dependencies]
tokio = { version = "1.40", features = ["full"] }
tokio-tungstenite = { version = "0.24", features = ["native-tls"] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
pyo3 = { version = "0.22", features = ["extension-module"] }
tonic = "0.12"           # gRPC
prost = "0.13"           # Protobuf
memmap2 = "0.9"          # Shared memory
tracing = "0.1"          # Structured logging
```

### 16.3 System Dependencies

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ | Tool runtime |
| Rust | 1.78+ | Performance-critical code |
| SQLite | 3.45+ | Trade memory (FTS5) |
| Redis | 7.0+ | State, cache, pubsub |
| TA-Lib | 0.4.32+ | Technical analysis (optional, pandas-ta fallback) |

---

## APPENDIX A: TOOL QUICK REFERENCE

| # | Tool | Lang | Permission | Approval | Timeout | Retryable |
|---|------|------|------------|----------|---------|-----------|
| 1 | `get_price` | Python | READ | AUTO | 3s | Yes |
| 2 | `get_ohlcv` | Python | READ | AUTO | 5s | Yes |
| 3 | `get_orderbook` | Python | READ | AUTO | 3s | Yes |
| 4 | `place_order` | Python | TRADE_LIVE | ALWAYS_CONFIRM | 10s | **No** |
| 5 | `cancel_order` | Python | TRADE_LIVE | AUTO | 5s | Yes |
| 6 | `get_positions` | Python | READ | AUTO | 5s | Yes |
| 7 | `get_balance` | Python | READ | AUTO | 5s | Yes |
| 8 | `get_funding_rate` | Python | READ | AUTO | 3s | Yes |
| 9 | `calculate_rsi` | Python | ANALYSIS | AUTO | 2s | Yes |
| 10 | `calculate_macd` | Python | ANALYSIS | AUTO | 2s | Yes |
| 11 | `calculate_bollinger` | Python | ANALYSIS | AUTO | 2s | Yes |
| 12 | `calculate_atr` | Python | ANALYSIS | AUTO | 2s | Yes |
| 13 | `calculate_ema` | Python | ANALYSIS | AUTO | 2s | Yes |
| 14 | `calculate_volume_profile` | Python | ANALYSIS | AUTO | 3s | Yes |
| 15 | `detect_patterns` | Python | ANALYSIS | AUTO | 3s | Yes |
| 16 | `stream_prices` | Rust | READ | AUTO | Continuous | Yes |
| 17 | `stream_orderbook` | Rust | READ | AUTO | Continuous | Yes |
| 18 | `fetch_news` | Python | READ | AUTO | 10s | Yes |
| 19 | `fetch_social_sentiment` | Python | READ | AUTO | 10s | Yes |
| 20 | `fetch_onchain_data` | Python | READ | AUTO | 15s | Yes |
| 21 | `fetch_macro_calendar` | Python | READ | AUTO | 10s | Yes |
| 22 | `check_position_limits` | Python | ANALYSIS | AUTO | 500ms | No |
| 23 | `calculate_position_size` | Python | ANALYSIS | AUTO | 500ms | No |
| 24 | `get_portfolio_exposure` | Python | READ | AUTO | 2s | Yes |
| 25 | `get_correlation_matrix` | Python | ANALYSIS | AUTO | 5s | Yes |
| 26 | `get_drawdown_stats` | Python | READ | AUTO | 2s | Yes |
| 27 | `log_trade` | Python | TRADE_PREVIEW | AUTO | 1s | Yes |
| 28 | `search_trades` | Python | READ | AUTO | 2s | Yes |
| 29 | `get_strategy_performance` | Python | READ | AUTO | 2s | Yes |
| 30 | `get_lesson` | Python | READ | AUTO | 1s | Yes |
| 31 | `update_regime_state` | Python | ANALYSIS | AUTO | 500ms | Yes |
| 32 | `smart_order_router` | Rust | TRADE_LIVE | ALWAYS_CONFIRM | 15s | **No** |
| 33 | `calculate_slippage` | Rust | ANALYSIS | AUTO | 1s | Yes |
| 34 | `twap_execute` | Rust | TRADE_LIVE | ALWAYS_CONFIRM | 1hr | **No** |
| 35 | `monitor_fills` | Rust | READ | AUTO | 5s | Yes |

**Total: 35 tools** — 24 Python, 5 Rust-backed, 6 Python/Rust hybrid (Rust streaming, Python interface)

---

## APPENDIX B: TOOL COUNT BY CATEGORY

| Category | Count | Language Mix |
|----------|-------|-------------|
| Exchange | 8 | Python (ccxt) |
| Technical Analysis | 7 | Python (pandas-ta) |
| Data | 6 | 2 Rust (streaming), 4 Python |
| Risk | 5 | Python (deterministic) |
| Memory | 5 | Python (SQLite + Redis) |
| Execution | 4 | 4 Rust (PyO3) |
| **Total** | **35** | **24 Python, 11 Rust** |

---

## APPENDIX C: CRITICAL PATH LATENCY

**Decision-to-execution latency budget (for a signal):**

```
Signal detected
  → calculate_position_size()    0.5ms
  → check_position_limits()      5ms
  → get_price() [cached]         1ms
  → calculate_slippage()          1ms
  → [APPROVAL GATE]              ~30s (human in loop) or 0s (paper)
  → place_order()                200ms
  → log_trade()                  10ms
  → monitor_fills()              ongoing
  
Total (paper mode):     ~218ms
Total (live, no human): ~218ms
Total (live, human):    ~30.2s
```

---

*End of Tools & Exchange Connectivity Specification v1.0.0*
*Companion document: [Trading Super Agent Blueprint v2.0](./trading-super-agent-blueprint.md)*
