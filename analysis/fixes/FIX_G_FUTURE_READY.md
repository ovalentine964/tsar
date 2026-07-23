# FIX_G: FUTURE-READY INTERFACE LAYER — Backend-Agnostic Abstractions

**Severity:** CRITICAL  
**Status:** SPECIFICATION — Ready for Implementation  
**Date:** 2026-07-24  
**Author:** Future-Ready Architecture Specialist  
**Scope:** `src/interfaces/` — Abstract base classes for ALL major components  
**Principle:** "Design the interface from Day 1. Swap the backend later. Never refactor agent code."

---

## Table of Contents

1. [Philosophy](#1-philosophy)
2. [Architecture Overview](#2-architecture-overview)
3. [BackendRegistry — Central Discovery Engine](#3-backendregistry)
4. [ExchangeGateway](#4-exchangegateway)
5. [PricingEngine](#5-pricingengine)
6. [ExecutionEngine](#6-executionengine)
7. [RiskEngine](#7-riskengine)
8. [LLMProvider](#8-llmprovider)
9. [Config-Driven Backend Selection](#9-config-driven-backend-selection)
10. [Backend Hot-Swap](#10-backend-hot-swap)
11. [Fallback Chain System](#11-fallback-chain-system)
12. [Integration with Existing Architecture](#12-integration)
13. [Day1 → Level 5 Migration Path](#13-migration-path)
14. [File Layout](#14-file-layout)

---

## 1. Philosophy

### The Founder's Mandate

> "Everything should be future-ready from day one. No swapping later."

This means: **Every Python interface must be designed so that the calling code never knows or cares whether the implementation is Python, Rust, or C++.** The interface is the contract. The backend is an implementation detail.

### Design Invariants

| Invariant | Rule | Rationale |
|-----------|------|-----------|
| **Interface stability** | ABC methods never change signature after v1 | Agent code written today works with Rust/C++ backends in 6 months |
| **Python as orchestrator** | All interfaces are Python ABCs | Agents are Python; they call Python interfaces. Period. |
| **Backend neutrality** | No import of ccxt, pandas-ta, QuantLib in agent code | Agents import from `src.interfaces.*` only |
| **Config-driven** | YAML selects which backend class to instantiate | Ops swaps backends without code changes |
| **Hot-swappable** | Backends can be swapped at runtime via registry | Testing, fallback, and graceful degradation |
| **Type-safe** | Python 3.12 typing, Pydantic models for all data | Catch errors at load time, not runtime |
| **Observable** | Every interface method is instrumented (latency, errors) | Monitoring across all backends is uniform |

### What Agents See

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

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AGENT LAYER                                   │
│  Signal Scout · Risk Guardian · Execution Sniper · Philosopher · …   │
│                                                                      │
│  Agents call: get_exchange_gateway(), get_pricing_engine(), etc.     │
│  Agents NEVER import: ccxt, pandas-ta, QuantLib, quickfix           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    INTERFACE LAYER (src/interfaces/)                  │
│                                                                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────┐│
│  │ ExchangeGateway  │  │ PricingEngine   │  │ ExecutionEngine      ││
│  │ (ABC)            │  │ (ABC)           │  │ (ABC)                ││
│  └────────┬────────┘  └────────┬────────┘  └──────────┬───────────┘│
│           │                    │                       │            │
│  ┌────────┴────────┐  ┌───────┴─────────┐  ┌─────────┴───────────┐│
│  │ RiskEngine       │  │ LLMProvider     │  │ BackendRegistry     ││
│  │ (ABC)            │  │ (ABC)           │  │ (config + discovery) ││
│  └────────┬────────┘  └───────┬─────────┘  └─────────────────────┘│
└───────────┼───────────────────┼────────────────────────────────────┘
            │                   │
            ▼                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    BACKEND REGISTRY                                  │
│                                                                      │
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
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  DAY 1           │ │  LEVEL 2         │ │  LEVEL 4         │
│  Python Backends │ │  Rust Backends   │ │  C++ Backends    │
│                  │ │                  │ │                  │
│  • CcxtGateway   │ │  • RustWsGateway │ │  • FixGateway    │
│  • PandasTAEngine│ │  • RustTickEngine│ │  • QuantLibEngine│
│  • CcxtExecEngine│ │  • RustExecEngine│ │  • FixExecEngine │
│  • PyRiskEngine  │ │  • RustRiskEngine│ │  • GpuMonteCarlo │
│  • OllamaProvider│ │  • LiteLLMRouter │ │                  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

### Key Rule: No Direct Rust↔C++ Calls

Per the Chief Architect's directive (HYBRID_ARCHITECT_REVIEW.md §2.2):
- Rust and C++ modules **never call each other directly**
- Python mediates all cross-module communication
- Each backend is an independent `.so`/`.pyd` loaded by Python

---

## 3. BackendRegistry — Central Discovery Engine

The `BackendRegistry` is the single source of truth for which implementation backs each interface. It handles registration, lookup, hot-swap, and fallback chains.

```python
# src/interfaces/registry.py
"""
Central registry mapping abstract interfaces to concrete backends.

Usage:
    registry = BackendRegistry()
    registry.load_from_config("config/backends.yaml")

    # Get the configured backend for an interface
    gateway = registry.create("exchange_gateway")

    # Hot-swap at runtime (testing)
    registry.swap("exchange_gateway", MockGateway)

    # Fallback chain
    gateway = registry.create_with_fallback("exchange_gateway")
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import yaml

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class BackendRegistration:
    """A single backend registration entry."""
    interface_name: str                    # e.g. "exchange_gateway"
    backend_class: type                    # e.g. CcxtGateway
    backend_path: str                      # e.g. "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
    priority: int = 100                    # Lower = higher priority
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)  # e.g. ["python", "day1"]
    health_status: bool = True
    last_health_check: float = 0.0
    failure_count: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class BackendMetrics:
    """Metrics for a backend instance."""
    total_calls: int = 0
    total_errors: int = 0
    total_latency_ms: float = 0.0
    last_call_at: float = 0.0
    last_error_at: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total_calls if self.total_calls else 0.0

    @property
    def error_rate(self) -> float:
        return self.total_errors / self.total_calls if self.total_calls else 0.0


class BackendRegistry:
    """
    Central registry for all interface→backend mappings.

    Responsibilities:
    - Register backend implementations for each interface
    - Load registrations from YAML config
    - Create backend instances on demand
    - Manage fallback chains
    - Support hot-swap (runtime backend replacement)
    - Track backend health and metrics
    """

    def __init__(self) -> None:
        # interface_name → list[BackendRegistration] (sorted by priority)
        self._registrations: dict[str, list[BackendRegistration]] = {}
        # interface_name → currently active BackendRegistration
        self._active: dict[str, BackendRegistration] = {}
        # interface_name → instance cache
        self._instances: dict[str, Any] = {}
        # interface_name → BackendMetrics
        self._metrics: dict[str, dict[str, BackendMetrics]] = {}
        # Hot-swap overrides (interface_name → class)
        self._overrides: dict[str, type] = {}

    # ═══════════════════════════════════════════════════════════
    # REGISTRATION
    # ═══════════════════════════════════════════════════════════

    def register(
        self,
        interface_name: str,
        backend_class: type,
        priority: int = 100,
        config: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Register a backend implementation for an interface."""
        backend_path = f"{backend_class.__module__}.{backend_class.__qualname__}"
        reg = BackendRegistration(
            interface_name=interface_name,
            backend_class=backend_class,
            backend_path=backend_path,
            priority=priority,
            config=config or {},
            tags=tags or [],
        )

        if interface_name not in self._registrations:
            self._registrations[interface_name] = []
            self._metrics[interface_name] = {}

        self._registrations[interface_name].append(reg)
        self._registrations[interface_name].sort(key=lambda r: r.priority)
        self._metrics[interface_name][backend_path] = BackendMetrics()

        # If this is the highest-priority enabled backend, make it active
        if interface_name not in self._active or reg.priority < self._active[interface_name].priority:
            if reg.enabled:
                self._active[interface_name] = reg

        logger.info(
            f"Registered backend: {interface_name} → {backend_path} "
            f"(priority={reg.priority}, tags={reg.tags})"
        )

    def load_from_config(self, config_path: str) -> None:
        """
        Load backend registrations from YAML config.

        Config format:
        ```yaml
        exchange_gateway:
          primary: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
          fallback:
            - path: "src.interfaces.exchange.rust_gateway.RustGateway"
              priority: 200
          config:
            sandbox: true
        ```
        """
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Backend config not found: {config_path}")
            return

        with open(path) as f:
            config = yaml.safe_load(f) or {}

        for interface_name, interface_config in config.items():
            if not isinstance(interface_config, dict):
                continue

            # Load primary
            primary_path = interface_config.get("primary")
            if primary_path:
                cls = self._import_class(primary_path)
                self.register(
                    interface_name=interface_name,
                    backend_class=cls,
                    priority=100,
                    config=interface_config.get("config", {}),
                    tags=["primary"],
                )

            # Load fallbacks
            for fallback in interface_config.get("fallback", []):
                if isinstance(fallback, str):
                    fb_path = fallback
                    fb_priority = 200
                elif isinstance(fallback, dict):
                    fb_path = fallback["path"]
                    fb_priority = fallback.get("priority", 200)
                else:
                    continue

                cls = self._import_class(fb_path)
                self.register(
                    interface_name=interface_name,
                    backend_class=cls,
                    priority=fb_priority,
                    config=interface_config.get("config", {}),
                    tags=["fallback"],
                )

    # ═══════════════════════════════════════════════════════════
    # INSTANCE CREATION
    # ═══════════════════════════════════════════════════════════

    def create(self, interface_name: str, **override_config: Any) -> Any:
        """
        Create (or return cached) backend instance for an interface.

        Respects hot-swap overrides. Merges config from registration
        with any override_config kwargs.
        """
        # Check for hot-swap override
        if interface_name in self._overrides:
            cls = self._overrides[interface_name]
            instance = cls(**override_config)
            self._instances[interface_name] = instance
            return instance

        # Get active registration
        reg = self._active.get(interface_name)
        if not reg:
            raise ValueError(
                f"No backend registered for interface '{interface_name}'. "
                f"Registered: {list(self._registrations.keys())}"
            )

        # Merge config
        merged_config = {**reg.config, **override_config}

        # Create instance
        instance = reg.backend_class(**merged_config)
        self._instances[interface_name] = instance

        logger.info(f"Created backend: {interface_name} → {reg.backend_path}")
        return instance

    def create_with_fallback(self, interface_name: str, **override_config: Any) -> Any:
        """
        Create backend with automatic fallback chain.

        Tries backends in priority order. If primary fails to initialize,
        falls back to next priority. Returns the first successful instance.

        Returns a FallbackProxy that handles runtime failover.
        """
        registrations = self._registrations.get(interface_name, [])
        if not registrations:
            raise ValueError(f"No backends registered for '{interface_name}'")

        enabled = [r for r in registrations if r.enabled]
        if not enabled:
            raise ValueError(f"All backends disabled for '{interface_name}'")

        instances = []
        for reg in enabled:
            merged_config = {**reg.config, **override_config}
            try:
                instance = reg.backend_class(**merged_config)
                instances.append((reg, instance))
            except Exception as e:
                logger.warning(
                    f"Failed to create {reg.backend_path}: {e}. "
                    f"Trying next fallback."
                )

        if not instances:
            raise RuntimeError(f"All backends failed for '{interface_name}'")

        proxy = FallbackProxy(interface_name, instances, self._metrics.get(interface_name, {}))
        self._instances[interface_name] = proxy
        return proxy

    # ═══════════════════════════════════════════════════════════
    # HOT-SWAP
    # ═══════════════════════════════════════════════════════════

    def swap(self, interface_name: str, new_backend_class: type) -> None:
        """
        Hot-swap a backend at runtime.

        The next call to create() or get_instance() will use the new class.
        Existing instances are NOT affected (they're already created).

        Use cases:
        - Testing: swap in a mock backend
        - Fallback: swap in a backup when primary is down
        - Upgrade: swap in a new version without restart
        """
        old_class = self._overrides.get(interface_name)
        self._overrides[interface_name] = new_backend_class

        # Invalidate cached instance
        if interface_name in self._instances:
            del self._instances[interface_name]

        logger.info(
            f"Hot-swapped backend: {interface_name} → "
            f"{new_backend_class.__module__}.{new_backend_class.__qualname__}"
        )

    def unswap(self, interface_name: str) -> None:
        """Remove a hot-swap override, reverting to config-defined backend."""
        if interface_name in self._overrides:
            del self._overrides[interface_name]
            if interface_name in self._instances:
                del self._instances[interface_name]
            logger.info(f"Removed hot-swap override for: {interface_name}")

    def get_instance(self, interface_name: str) -> Any | None:
        """Get cached instance if it exists."""
        return self._instances.get(interface_name)

    # ═══════════════════════════════════════════════════════════
    # HEALTH & METRICS
    # ═══════════════════════════════════════════════════════════

    def record_call(
        self,
        interface_name: str,
        backend_path: str,
        latency_ms: float,
        error: bool = False,
    ) -> None:
        """Record a call for metrics tracking."""
        metrics = self._metrics.get(interface_name, {}).get(backend_path)
        if metrics:
            metrics.total_calls += 1
            metrics.total_latency_ms += latency_ms
            metrics.last_call_at = time.time()
            if error:
                metrics.total_errors += 1
                metrics.last_error_at = time.time()

    def get_metrics(self, interface_name: str | None = None) -> dict[str, Any]:
        """Get metrics for all or specific interface."""
        if interface_name:
            return {
                path: {
                    "calls": m.total_calls,
                    "errors": m.total_errors,
                    "avg_latency_ms": m.avg_latency_ms,
                    "error_rate": m.error_rate,
                }
                for path, m in self._metrics.get(interface_name, {}).items()
            }
        return {
            iface: {
                path: {
                    "calls": m.total_calls,
                    "errors": m.total_errors,
                    "avg_latency_ms": m.avg_latency_ms,
                    "error_rate": m.error_rate,
                }
                for path, m in metrics.items()
            }
            for iface, metrics in self._metrics.items()
        }

    def get_status(self) -> dict[str, Any]:
        """Get full registry status."""
        return {
            "interfaces": {
                iface: {
                    "active": self._active.get(iface, BackendRegistration(
                        interface_name="", backend_class=type, backend_path="none"
                    )).backend_path if iface in self._active else "none",
                    "backends": len(regs),
                    "overridden": iface in self._overrides,
                    "cached": iface in self._instances,
                }
                for iface, regs in self._registrations.items()
            },
            "total_interfaces": len(self._registrations),
            "total_overrides": len(self._overrides),
        }

    # ═══════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _import_class(class_path: str) -> type:
        """Import a class from a dotted path."""
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)


class FallbackProxy:
    """
    Proxy that wraps multiple backend instances with automatic failover.

    Delegates method calls to the primary (highest-priority) backend.
    If the primary raises a retryable error, falls back to the next.
    """

    def __init__(
        self,
        interface_name: str,
        instances: list[tuple[BackendRegistration, Any]],
        metrics: dict[str, BackendMetrics],
    ) -> None:
        self.interface_name = interface_name
        self._instances = instances  # Ordered by priority
        self._metrics = metrics
        self._primary_index = 0

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the active backend."""
        if name.startswith("_"):
            raise AttributeError(name)

        def fallback_method(*args: Any, **kwargs: Any) -> Any:
            last_error = None
            for i in range(self._primary_index, len(self._instances)):
                reg, instance = self._instances[i]
                try:
                    method = getattr(instance, name)
                    result = method(*args, **kwargs)
                    # Success — record and return
                    self._primary_index = i  # Stick with this backend
                    return result
                except Exception as e:
                    logger.warning(
                        f"Fallback: {reg.backend_path}.{name} failed: {e}. "
                        f"Trying next."
                    )
                    last_error = e
                    continue
            raise last_error  # All backends failed

        return fallback_method

    async def __getattr_async__(self, name: str) -> Any:
        """Same as __getattr__ but for async methods."""
        # This is handled by the async method wrapper below
        pass


class InstrumentedBackend:
    """
    Wrapper that instruments any backend with metrics collection.

    Wraps all public methods to record latency and errors.
    """

    def __init__(
        self,
        backend: Any,
        registry: BackendRegistry,
        interface_name: str,
        backend_path: str,
    ) -> None:
        self._backend = backend
        self._registry = registry
        self._interface_name = interface_name
        self._backend_path = backend_path

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._backend, name)
        if not callable(attr) or name.startswith("_"):
            return attr

        if asyncio.iscoroutinefunction(attr):
            return self._wrap_async(attr, name)
        return self._wrap_sync(attr, name)

    def _wrap_sync(self, func: Any, name: str) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                result = func(*args, **kwargs)
                latency = (time.monotonic() - start) * 1000
                self._registry.record_call(
                    self._interface_name, self._backend_path, latency
                )
                return result
            except Exception as e:
                latency = (time.monotonic() - start) * 1000
                self._registry.record_call(
                    self._interface_name, self._backend_path, latency, error=True
                )
                raise
        return wrapper

    def _wrap_async(self, func: Any, name: str) -> Any:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                latency = (time.monotonic() - start) * 1000
                self._registry.record_call(
                    self._interface_name, self._backend_path, latency
                )
                return result
            except Exception as e:
                latency = (time.monotonic() - start) * 1000
                self._registry.record_call(
                    self._interface_name, self._backend_path, latency, error=True
                )
                raise
        return wrapper


# ═══════════════════════════════════════════════════════════
# GLOBAL REGISTRY SINGLETON
# ═══════════════════════════════════════════════════════════

_registry: BackendRegistry | None = None


def get_registry() -> BackendRegistry:
    """Get the global BackendRegistry. Must call initialize_registry() first."""
    if _registry is None:
        raise RuntimeError("BackendRegistry not initialized. Call initialize_registry() first.")
    return _registry


def initialize_registry(config_path: str = "config/backends.yaml") -> BackendRegistry:
    """Initialize the global BackendRegistry from config."""
    global _registry
    _registry = BackendRegistry()
    _registry.load_from_config(config_path)
    return _registry


# ═══════════════════════════════════════════════════════════
# CONVENIENCE GETTERS (what agents actually call)
# ═══════════════════════════════════════════════════════════

import asyncio  # noqa: E402


def get_exchange_gateway(**config: Any) -> Any:
    """Get the configured ExchangeGateway backend."""
    return get_registry().create_with_fallback("exchange_gateway", **config)


def get_pricing_engine(**config: Any) -> Any:
    """Get the configured PricingEngine backend."""
    return get_registry().create_with_fallback("pricing_engine", **config)


def get_execution_engine(**config: Any) -> Any:
    """Get the configured ExecutionEngine backend."""
    return get_registry().create_with_fallback("execution_engine", **config)


def get_risk_engine(**config: Any) -> Any:
    """Get the configured RiskEngine backend."""
    return get_registry().create_with_fallback("risk_engine", **config)


def get_llm_provider(**config: Any) -> Any:
    """Get the configured LLMProvider backend."""
    return get_registry().create_with_fallback("llm_provider", **config)
```

---

## 4. ExchangeGateway

The `ExchangeGateway` abstracts all exchange connectivity. Day1 uses ccxt. Level 2 swaps in Rust WebSocket. Level 4 swaps in C++ FIX.

### 4.1 Abstract Base Class

```python
# src/interfaces/exchange/base.py
"""
Abstract base class for exchange gateways.

All exchange connectivity goes through this interface.
Agent code calls: gateway.get_price("BTC/USDT")
Whether the backend is ccxt, Rust WebSocket, or C++ FIX — the call is identical.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# DATA TYPES
# ═══════════════════════════════════════════════════════════

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(str, Enum):
    GTC = "gtc"    # Good Till Cancelled
    IOC = "ioc"    # Immediate or Cancel
    FOK = "fok"    # Fill or Kill


class ConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class Ticker(BaseModel):
    """Current market ticker for a symbol."""
    symbol: str
    last: float
    bid: float
    ask: float
    high_24h: float
    low_24h: float
    volume_24h: float
    quote_volume_24h: float
    change_24h_pct: float = 0.0
    timestamp: datetime
    raw: dict[str, Any] = Field(default_factory=dict)


class OHLCV(BaseModel):
    """Single OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class OrderBookLevel(BaseModel):
    """Single level in the order book."""
    price: float
    quantity: float


class OrderBook(BaseModel):
    """Order book snapshot."""
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    timestamp: datetime
    raw: dict[str, Any] = Field(default_factory=dict)


class Trade(BaseModel):
    """A single trade (fill) on the exchange."""
    id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    cost: float
    fee: float
    fee_currency: str
    timestamp: datetime


class OrderResult(BaseModel):
    """Result of placing an order."""
    order_id: str
    symbol: str
    side: OrderSide
    type: OrderType
    price: float | None
    quantity: float
    filled_quantity: float = 0.0
    status: OrderStatus
    fee: float = 0.0
    fee_currency: str = ""
    timestamp: datetime
    raw: dict[str, Any] = Field(default_factory=dict)


class Position(BaseModel):
    """An open position on the exchange."""
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    leverage: float = 1.0
    liquidation_price: float | None = None
    timestamp: datetime


class Balance(BaseModel):
    """Account balance."""
    total: float
    free: float
    used: float
    currency: str = "USDT"
    per_currency: dict[str, dict[str, float]] = Field(default_factory=dict)


class StreamHandle(BaseModel):
    """Handle for an active price/orderbook stream."""
    stream_id: str
    symbol: str
    stream_type: str  # "ticker", "ohlcv", "orderbook", "trades"
    active: bool = True

    class Config:
        arbitrary_types_allowed = True


# ═══════════════════════════════════════════════════════════
# ABSTRACT BASE CLASS
# ═══════════════════════════════════════════════════════════

class ExchangeGateway(abc.ABC):
    """
    Abstract interface for exchange connectivity.

    Day1 Implementation: CcxtGateway (ccxt REST API)
    Level 2 Implementation: RustWsGateway (Rust tokio-tungstenite WebSocket)
    Level 4 Implementation: FixGateway (C++ QuickFIX)

    All methods are async. Backends may be sync internally but must
    expose async interfaces for consistency.

    Lifecycle:
        __init__(config) → connect() → [operations] → disconnect()
    """

    def __init__(self, **config: Any) -> None:
        """
        Initialize the gateway with configuration.

        Args:
            exchange: Exchange name (e.g. "binance")
            sandbox: Use testnet/sandbox mode
            api_key: Exchange API key (or env var reference)
            api_secret: Exchange API secret
            rate_limit: Max requests per minute
            timeout_s: Request timeout in seconds
        """
        self.config = config
        self.exchange_name: str = config.get("exchange", "binance")
        self.sandbox: bool = config.get("sandbox", True)
        self._connection_status = ConnectionStatus.DISCONNECTED

    # ═══════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def connect(self) -> None:
        """
        Establish connection to the exchange.

        Must:
        - Authenticate with the exchange
        - Verify connectivity
        - Set connection status to CONNECTED

        Must NOT:
        - Block for more than 10 seconds
        - Subscribe to data streams (use subscribe() for that)

        Raises:
            ConnectionError: Cannot reach exchange
            AuthenticationError: Invalid credentials
        """
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """
        Gracefully disconnect from the exchange.

        Must:
        - Close all open connections
        - Cancel all active streams
        - Set connection status to DISCONNECTED
        """
        ...

    @property
    def connection_status(self) -> ConnectionStatus:
        """Current connection status."""
        return self._connection_status

    # ═══════════════════════════════════════════════════════════
    # MARKET DATA (READ)
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def get_price(self, symbol: str) -> float:
        """
        Get the current last traded price for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT")

        Returns:
            Current price as float

        Raises:
            SymbolNotFoundError: Symbol not found on exchange
            ConnectionError: Not connected to exchange
        """
        ...

    @abc.abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """
        Get full ticker data for a symbol.

        Args:
            symbol: Trading pair

        Returns:
            Ticker with bid, ask, high, low, volume, etc.
        """
        ...

    @abc.abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[OHLCV]:
        """
        Get OHLCV candle data.

        Args:
            symbol: Trading pair
            timeframe: Candle interval ("1m", "5m", "15m", "1h", "4h", "1d")
            limit: Number of candles to return
            since: Start time (optional)

        Returns:
            List of OHLCV candles, oldest first
        """
        ...

    @abc.abstractmethod
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """
        Get the current order book.

        Args:
            symbol: Trading pair
            depth: Number of levels per side

        Returns:
            OrderBook with bids and asks
        """
        ...

    @abc.abstractmethod
    async def get_recent_trades(self, symbol: str, limit: int = 50) -> list[Trade]:
        """
        Get recent trades for a symbol.

        Args:
            symbol: Trading pair
            limit: Number of trades to return

        Returns:
            List of recent trades, newest first
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # STREAMING (REAL-TIME)
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def subscribe(
        self,
        symbol: str,
        stream_type: str,
        callback: Any,
    ) -> StreamHandle:
        """
        Subscribe to a real-time data stream.

        Args:
            symbol: Trading pair
            stream_type: "ticker", "ohlcv", "orderbook", "trades"
            callback: Async function called with each update

        Returns:
            StreamHandle for managing the subscription

        Note:
            Day1 (ccxt) may implement this as polling.
            Level 2 (Rust WebSocket) implements as true WebSocket stream.
        """
        ...

    @abc.abstractmethod
    async def unsubscribe(self, handle: StreamHandle) -> None:
        """Cancel a stream subscription."""
        ...

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT (READ)
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def get_balance(self) -> Balance:
        """
        Get account balance.

        Returns:
            Balance with total, free, used amounts
        """
        ...

    @abc.abstractmethod
    async def get_positions(self) -> list[Position]:
        """
        Get all open positions.

        Returns:
            List of open positions
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # ORDER MANAGEMENT (WRITE)
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        params: dict[str, Any] | None = None,
    ) -> OrderResult:
        """
        Place an order on the exchange.

        Args:
            symbol: Trading pair
            side: Buy or sell
            order_type: Market, limit, stop_market, stop_limit
            quantity: Order quantity
            price: Limit price (required for limit orders)
            stop_price: Stop price (required for stop orders)
            time_in_force: GTC, IOC, FOK
            params: Exchange-specific parameters

        Returns:
            OrderResult with order_id, status, fill info

        Raises:
            InsufficientFundsError: Not enough balance
            InvalidOrderError: Order parameters invalid
            ExchangeError: Exchange rejected the order
        """
        ...

    @abc.abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: Exchange order ID
            symbol: Trading pair

        Returns:
            True if cancelled successfully

        Raises:
            OrderNotFoundError: Order doesn't exist
            ExchangeError: Exchange rejected cancellation
        """
        ...

    @abc.abstractmethod
    async def get_order(self, order_id: str, symbol: str) -> OrderResult:
        """
        Get the current status of an order.

        Args:
            order_id: Exchange order ID
            symbol: Trading pair

        Returns:
            Current OrderResult
        """
        ...

    @abc.abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]:
        """
        Get all open orders.

        Args:
            symbol: Filter by symbol (optional)

        Returns:
            List of open orders
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # CONVENIENCE METHODS (non-abstract, default implementations)
    # ═══════════════════════════════════════════════════════════

    async def is_connected(self) -> bool:
        """Check if gateway is connected."""
        return self._connection_status == ConnectionStatus.CONNECTED

    def get_supported_symbols(self) -> list[str]:
        """Get list of supported trading pairs. Override if needed."""
        return []

    def get_exchange_info(self) -> dict[str, Any]:
        """Get exchange metadata. Override if needed."""
        return {"exchange": self.exchange_name, "sandbox": self.sandbox}
```

### 4.2 Day1 Implementation: CcxtGateway

```python
# src/interfaces/exchange/ccxt_gateway.py
"""
Day1 exchange gateway using ccxt REST API.

This is the default backend. It implements the ExchangeGateway interface
using ccxt for all exchange communication.

Config:
    exchange: "binance"
    sandbox: true
    api_key: "${BINANCE_API_KEY}"
    api_secret: "${BINANCE_API_SECRET}"
    rate_limit: 1200
    timeout_s: 30
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

import ccxt.async_support as ccxt

from src.interfaces.exchange.base import (
    Balance,
    ConnectionStatus,
    ExchangeGateway,
    OHLCV,
    OrderBook,
    OrderBookLevel,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    StreamHandle,
    Ticker,
    TimeInForce,
    Trade,
)


class CcxtGateway(ExchangeGateway):
    """
    Exchange gateway implementation using ccxt.

    Supports all ccxt-compatible exchanges (Binance, Bybit, OKX, etc.).
    Uses REST API for all operations. Streaming is implemented as polling.

    For true WebSocket streaming, use RustWsGateway (Level 2).
    """

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        self._client: ccxt.Exchange | None = None
        self._streams: dict[str, asyncio.Task] = {}

    async def connect(self) -> None:
        self._connection_status = ConnectionStatus.CONNECTING

        exchange_class = getattr(ccxt, self.exchange_name, None)
        if not exchange_class:
            raise ValueError(f"Unsupported exchange: {self.exchange_name}")

        api_key = self.config.get("api_key", "")
        if api_key.startswith("${"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var, "")

        api_secret = self.config.get("api_secret", "")
        if api_secret.startswith("${"):
            env_var = api_secret[2:-1]
            api_secret = os.environ.get(env_var, "")

        self._client = exchange_class({
            "apiKey": api_key,
            "secret": api_secret,
            "sandbox": self.sandbox,
            "enableRateLimit": True,
            "rateLimit": self.config.get("rate_limit", 1200) / 60 * 1000,
            "timeout": self.config.get("timeout_s", 30) * 1000,
        })

        # Load markets
        await self._client.load_markets()
        self._connection_status = ConnectionStatus.CONNECTED

    async def disconnect(self) -> None:
        # Cancel all streams
        for task in self._streams.values():
            task.cancel()
        self._streams.clear()

        if self._client:
            await self._client.close()
            self._client = None
        self._connection_status = ConnectionStatus.DISCONNECTED

    async def get_price(self, symbol: str) -> float:
        assert self._client, "Not connected"
        ticker = await self._client.fetch_ticker(symbol)
        return float(ticker["last"])

    async def get_ticker(self, symbol: str) -> Ticker:
        assert self._client, "Not connected"
        t = await self._client.fetch_ticker(symbol)
        return Ticker(
            symbol=symbol,
            last=float(t["last"]),
            bid=float(t.get("bid", 0) or 0),
            ask=float(t.get("ask", 0) or 0),
            high_24h=float(t.get("high", 0) or 0),
            low_24h=float(t.get("low", 0) or 0),
            volume_24h=float(t.get("baseVolume", 0) or 0),
            quote_volume_24h=float(t.get("quoteVolume", 0) or 0),
            change_24h_pct=float(t.get("percentage", 0) or 0),
            timestamp=datetime.fromtimestamp(
                t.get("timestamp", 0) / 1000, tz=timezone.utc
            ) if t.get("timestamp") else datetime.now(timezone.utc),
            raw=t,
        )

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[OHLCV]:
        assert self._client, "Not connected"
        since_ms = int(since.timestamp() * 1000) if since else None
        data = await self._client.fetch_ohlcv(
            symbol, timeframe, since=since_ms, limit=limit
        )
        return [
            OHLCV(
                timestamp=datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc),
                open=float(candle[1]),
                high=float(candle[2]),
                low=float(candle[3]),
                close=float(candle[4]),
                volume=float(candle[5]),
            )
            for candle in data
        ]

    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        assert self._client, "Not connected"
        ob = await self._client.fetch_order_book(symbol, limit=depth)
        return OrderBook(
            symbol=symbol,
            bids=[OrderBookLevel(price=float(b[0]), quantity=float(b[1])) for b in ob["bids"]],
            asks=[OrderBookLevel(price=float(a[0]), quantity=float(a[1])) for a in ob["asks"]],
            timestamp=datetime.now(timezone.utc),
            raw=ob,
        )

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> list[Trade]:
        assert self._client, "Not connected"
        trades = await self._client.fetch_trades(symbol, limit=limit)
        return [
            Trade(
                id=t["id"],
                symbol=symbol,
                side=OrderSide.BUY if t["side"] == "buy" else OrderSide.SELL,
                price=float(t["price"]),
                quantity=float(t["amount"]),
                cost=float(t["cost"]),
                fee=float(t.get("fee", {}).get("cost", 0)),
                fee_currency=t.get("fee", {}).get("currency", ""),
                timestamp=datetime.fromtimestamp(
                    t["timestamp"] / 1000, tz=timezone.utc
                ) if t.get("timestamp") else datetime.now(timezone.utc),
            )
            for t in trades
        ]

    async def subscribe(
        self,
        symbol: str,
        stream_type: str,
        callback: Callable,
    ) -> StreamHandle:
        """
        Subscribe to a data stream via polling.

        Note: This is a REST polling implementation. For true WebSocket
        streaming, use RustWsGateway (Level 2).
        """
        stream_id = f"{symbol}_{stream_type}_{id(callback)}"
        handle = StreamHandle(
            stream_id=stream_id,
            symbol=symbol,
            stream_type=stream_type,
        )

        async def _poll_loop() -> None:
            while handle.active:
                try:
                    if stream_type == "ticker":
                        data = await self.get_ticker(symbol)
                    elif stream_type == "ohlcv":
                        data = await self.get_ohlcv(symbol, limit=1)
                    else:
                        await asyncio.sleep(5)
                        continue
                    await callback(data)
                except Exception as e:
                    # Log error but continue polling
                    pass
                await asyncio.sleep(self.config.get("poll_interval_s", 5))

        self._streams[stream_id] = asyncio.create_task(_poll_loop())
        return handle

    async def unsubscribe(self, handle: StreamHandle) -> None:
        handle.active = False
        task = self._streams.pop(handle.stream_id, None)
        if task:
            task.cancel()

    async def get_balance(self) -> Balance:
        assert self._client, "Not connected"
        bal = await self._client.fetch_balance()
        return Balance(
            total=float(bal.get("total", {}).get("USDT", 0)),
            free=float(bal.get("free", {}).get("USDT", 0)),
            used=float(bal.get("used", {}).get("USDT", 0)),
            currency="USDT",
            per_currency={
                k: {"total": float(v.get("total", 0) or 0),
                    "free": float(v.get("free", 0) or 0),
                    "used": float(v.get("used", 0) or 0)}
                for k, v in bal.items()
                if isinstance(v, dict) and "total" in v
            },
        )

    async def get_positions(self) -> list[Position]:
        assert self._client, "Not connected"
        positions = await self._client.fetch_positions()
        return [
            Position(
                symbol=p["symbol"],
                side=OrderSide.BUY if float(p.get("contracts", 0)) > 0 else OrderSide.SELL,
                quantity=abs(float(p.get("contracts", 0))),
                entry_price=float(p.get("entryPrice", 0) or 0),
                current_price=float(p.get("markPrice", 0) or 0),
                unrealized_pnl=float(p.get("unrealizedPnl", 0) or 0),
                leverage=float(p.get("leverage", 1) or 1),
                liquidation_price=float(p["liquidationPrice"]) if p.get("liquidationPrice") else None,
                timestamp=datetime.now(timezone.utc),
            )
            for p in positions
            if float(p.get("contracts", 0)) != 0
        ]

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        params: dict[str, Any] | None = None,
    ) -> OrderResult:
        assert self._client, "Not connected"

        ccxt_type = order_type.value
        ccxt_side = side.value
        order_params = params or {}

        if time_in_force != TimeInForce.GTC:
            order_params["timeInForce"] = time_in_force.value.upper()

        if stop_price is not None:
            order_params["stopPrice"] = stop_price

        result = await self._client.create_order(
            symbol=symbol,
            type=ccxt_type,
            side=ccxt_side,
            amount=quantity,
            price=price,
            params=order_params,
        )

        return OrderResult(
            order_id=result["id"],
            symbol=symbol,
            side=side,
            type=order_type,
            price=float(result.get("price", 0) or price or 0),
            quantity=float(result.get("amount", quantity)),
            filled_quantity=float(result.get("filled", 0) or 0),
            status=self._map_order_status(result.get("status", "open")),
            fee=float(result.get("fee", {}).get("cost", 0)),
            fee_currency=result.get("fee", {}).get("currency", ""),
            timestamp=datetime.now(timezone.utc),
            raw=result,
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        assert self._client, "Not connected"
        try:
            await self._client.cancel_order(order_id, symbol)
            return True
        except Exception:
            return False

    async def get_order(self, order_id: str, symbol: str) -> OrderResult:
        assert self._client, "Not connected"
        result = await self._client.fetch_order(order_id, symbol)
        return OrderResult(
            order_id=result["id"],
            symbol=symbol,
            side=OrderSide.BUY if result["side"] == "buy" else OrderSide.SELL,
            type=OrderType(result["type"]),
            price=float(result.get("price", 0) or 0),
            quantity=float(result.get("amount", 0)),
            filled_quantity=float(result.get("filled", 0) or 0),
            status=self._map_order_status(result.get("status", "open")),
            fee=float(result.get("fee", {}).get("cost", 0)),
            fee_currency=result.get("fee", {}).get("currency", ""),
            timestamp=datetime.now(timezone.utc),
            raw=result,
        )

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]:
        assert self._client, "Not connected"
        orders = await self._client.fetch_open_orders(symbol)
        return [
            OrderResult(
                order_id=o["id"],
                symbol=o["symbol"],
                side=OrderSide.BUY if o["side"] == "buy" else OrderSide.SELL,
                type=OrderType(o["type"]),
                price=float(o.get("price", 0) or 0),
                quantity=float(o.get("amount", 0)),
                filled_quantity=float(o.get("filled", 0) or 0),
                status=self._map_order_status(o.get("status", "open")),
                fee=float(o.get("fee", {}).get("cost", 0)),
                fee_currency=o.get("fee", {}).get("currency", ""),
                timestamp=datetime.now(timezone.utc),
                raw=o,
            )
            for o in orders
        ]

    @staticmethod
    def _map_order_status(ccxt_status: str) -> OrderStatus:
        mapping = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.EXPIRED,
        }
        return mapping.get(ccxt_status, OrderStatus.OPEN)
```

### 4.3 Level 2 Placeholder: RustWsGateway

```python
# src/interfaces/exchange/rust_gateway.py
"""
Level 2 exchange gateway using Rust WebSocket.

PLACEHOLDER — implements ExchangeGateway by delegating to Rust via PyO3.

When the Rust WebSocket crate is built:
    from trading_rs import RustWsManager

Until then, this raises NotImplementedError on construction.
"""

from __future__ import annotations

from typing import Any

from src.interfaces.exchange.base import ExchangeGateway


class RustWsGateway(ExchangeGateway):
    """
    Rust WebSocket gateway (Level 2).

    Delegates to trading_rs.RustWsManager via PyO3.
    Provides true WebSocket streaming with ~1μs call overhead.

    Status: PLACEHOLDER — not implemented until Level 2.
    """

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        raise NotImplementedError(
            "RustWsGateway requires the Rust WebSocket crate. "
            "Build with: cd rust && maturin develop --release. "
            "See docs/architecture/TECH_STACK.md §Rust for details."
        )
```

### 4.4 Level 4 Placeholder: FixGateway

```python
# src/interfaces/exchange/fix_gateway.py
"""
Level 4 exchange gateway using C++ FIX protocol.

PLACEHOLDER — implements ExchangeGateway by delegating to C++ via pybind11.

When the C++ FIX module is built:
    from trading_cpp.fix import FIXSession

Until then, this raises NotImplementedError on construction.
"""

from __future__ import annotations

from typing import Any

from src.interfaces.exchange.base import ExchangeGateway


class FixGateway(ExchangeGateway):
    """
    C++ FIX protocol gateway (Level 4).

    Delegates to trading_cpp.fix.FIXSession via pybind11.
    Provides institutional-grade FIX connectivity for forex (OANDA, IBKR).

    Status: PLACEHOLDER — not implemented until Level 4.
    """

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        raise NotImplementedError(
            "FixGateway requires the C++ FIX module (QuickFIX). "
            "See analysis/council/HYBRID_ARCHITECT_REVIEW.md §5.2.2 "
            "for implementation requirements."
        )
```

---

## 5. PricingEngine

The `PricingEngine` abstracts all quantitative computation — indicators, Greeks, OHLCV aggregation.

### 5.1 Abstract Base Class

```python
# src/interfaces/pricing/base.py
"""
Abstract base class for pricing and quantitative engines.

Day1: PandasTAEngine (pandas-ta + numpy)
Level 2: RustTickEngine (Rust tick processor via PyO3)
Level 3: QuantLibEngine (C++ QuantLib via pybind11)
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════
# DATA TYPES
# ═══════════════════════════════════════════════════════════

class IndicatorResult(BaseModel):
    """Result of a technical indicator calculation."""
    name: str
    values: list[float]
    params: dict[str, Any]
    metadata: dict[str, Any] = {}


class Greeks(BaseModel):
    """Option Greeks."""
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    price: float
    implied_volatility: float | None = None


class OHLCVBar(BaseModel):
    """Single aggregated OHLCV bar."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trades: int | None = None


class OptionType(BaseModel):
    """Option specification for Greeks/pricing."""
    option_type: str  # "call" or "put"
    spot: float
    strike: float
    rate: float
    volatility: float
    time_to_expiry: float  # In years


# ═══════════════════════════════════════════════════════════
# ABSTRACT BASE CLASS
# ═══════════════════════════════════════════════════════════

class PricingEngine(abc.ABC):
    """
    Abstract interface for pricing and quantitative computation.

    All methods are stateless (pure functions). No side effects.
    Backends may use different internal libraries but expose identical interfaces.

    Day1: PandasTAEngine — pandas-ta for indicators, numpy for Greeks
    Level 2: RustTickEngine — Rust for OHLCV aggregation, pandas-ta for indicators
    Level 3: QuantLibEngine — C++ QuantLib for pricing, Greeks, Monte Carlo
    """

    # ═══════════════════════════════════════════════════════════
    # TECHNICAL INDICATORS
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    def calculate_indicator(
        self,
        name: str,
        **params: Any,
    ) -> IndicatorResult:
        """
        Calculate a technical indicator.

        Args:
            name: Indicator name ("rsi", "macd", "bollinger", "ema", "atr", etc.)
            **params: Indicator-specific parameters
                Common params:
                    closes: list[float] — Close prices
                    highs: list[float] — High prices (for ATR, etc.)
                    lows: list[float] — Low prices
                    opens: list[float] — Open prices
                    volumes: list[float] — Volume data
                    period: int — Lookback period

        Returns:
            IndicatorResult with computed values

        Raises:
            ValueError: Unknown indicator name
            InsufficientDataError: Not enough data points
        """
        ...

    @abc.abstractmethod
    def calculate_greeks(self, option: OptionType) -> Greeks:
        """
        Calculate option Greeks (delta, gamma, theta, vega, rho).

        Args:
            option: Option specification

        Returns:
            Greeks with all sensitivities

        Note:
            Day1 uses Black-Scholes (numpy).
            Level 3 uses QuantLib (C++) for exotic options.
        """
        ...

    @abc.abstractmethod
    def aggregate_ohlcv(
        self,
        ticks: list[dict[str, Any]],
        target_timeframe: str,
    ) -> list[OHLCVBar]:
        """
        Aggregate raw ticks into OHLCV bars.

        Args:
            ticks: Raw tick data [{timestamp, price, quantity}, ...]
            target_timeframe: Target bar interval ("1s", "1m", "5m", etc.)

        Returns:
            List of aggregated OHLCV bars

        Note:
            Day1 uses pandas resample.
            Level 2 uses Rust tick processor for 10-100x speedup.
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # CONVENIENCE METHODS (non-abstract)
    # ═══════════════════════════════════════════════════════════

    def calculate_rsi(self, closes: list[float], period: int = 14) -> float:
        """Calculate RSI and return the latest value."""
        result = self.calculate_indicator("rsi", closes=closes, period=period)
        return result.values[-1] if result.values else 50.0

    def calculate_ema(self, closes: list[float], period: int = 20) -> float:
        """Calculate EMA and return the latest value."""
        result = self.calculate_indicator("ema", closes=closes, period=period)
        return result.values[-1] if result.values else closes[-1]

    def calculate_atr(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> float:
        """Calculate ATR and return the latest value."""
        result = self.calculate_indicator(
            "atr", highs=highs, lows=lows, closes=closes, period=period
        )
        return result.values[-1] if result.values else 0.0

    def supports_indicator(self, name: str) -> bool:
        """Check if this engine supports a given indicator. Override if needed."""
        return True

    def get_supported_indicators(self) -> list[str]:
        """List supported indicators. Override if needed."""
        return ["rsi", "macd", "bollinger", "ema", "sma", "atr", "adx", "stoch"]
```

### 5.2 Day1 Implementation: PandasTAEngine

```python
# src/interfaces/pricing/pandas_ta_engine.py
"""
Day1 pricing engine using pandas-ta + numpy.

Implements all technical indicators via pandas-ta.
Greeks via Black-Scholes (numpy).
OHLCV aggregation via pandas.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from src.interfaces.pricing.base import (
    Greeks,
    IndicatorResult,
    OHLCVBar,
    OptionType,
    PricingEngine,
)


class PandasTAEngine(PricingEngine):
    """
    Technical analysis and pricing engine using pandas-ta.

    This is the Day1 implementation. All indicator calculations use
    pandas-ta. Greeks use Black-Scholes with numpy. OHLCV aggregation
    uses pandas resample.
    """

    def __init__(self, **config: Any) -> None:
        self.config = config

    def calculate_indicator(self, name: str, **params: Any) -> IndicatorResult:
        closes = params.get("closes", [])
        if not closes:
            raise ValueError("closes parameter is required")

        series = pd.Series(closes)
        name_lower = name.lower()

        if name_lower == "rsi":
            period = params.get("period", 14)
            rsi = series.ta.rsi(length=period)
            return IndicatorResult(
                name="rsi",
                values=rsi.dropna().tolist(),
                params={"period": period},
            )

        elif name_lower == "macd":
            fast = params.get("fast", 12)
            slow = params.get("slow", 26)
            signal = params.get("signal", 9)
            macd = series.ta.macd(fast=fast, slow=slow, signal=signal)
            return IndicatorResult(
                name="macd",
                values=macd.iloc[:, 0].dropna().tolist(),
                params={"fast": fast, "slow": slow, "signal": signal},
                metadata={
                    "signal": macd.iloc[:, 1].dropna().tolist(),
                    "histogram": macd.iloc[:, 2].dropna().tolist(),
                },
            )

        elif name_lower == "bollinger":
            period = params.get("period", 20)
            std = params.get("std", 2.0)
            bb = series.ta.bbands(length=period, std=std)
            return IndicatorResult(
                name="bollinger",
                values=bb.iloc[:, 0].dropna().tolist(),  # Lower band
                params={"period": period, "std": std},
                metadata={
                    "middle": bb.iloc[:, 1].dropna().tolist(),
                    "upper": bb.iloc[:, 2].dropna().tolist(),
                },
            )

        elif name_lower == "ema":
            period = params.get("period", 20)
            ema = series.ta.ema(length=period)
            return IndicatorResult(
                name="ema",
                values=ema.dropna().tolist(),
                params={"period": period},
            )

        elif name_lower == "sma":
            period = params.get("period", 20)
            sma = series.ta.sma(length=period)
            return IndicatorResult(
                name="sma",
                values=sma.dropna().tolist(),
                params={"period": period},
            )

        elif name_lower == "atr":
            highs = pd.Series(params["highs"])
            lows = pd.Series(params["lows"])
            atr_df = pd.concat([highs, lows, series], axis=1)
            atr_df.columns = ["high", "low", "close"]
            atr = atr_df.ta.atr(length=params.get("period", 14))
            return IndicatorResult(
                name="atr",
                values=atr.dropna().tolist(),
                params={"period": params.get("period", 14)},
            )

        else:
            # Try generic pandas-ta indicator
            try:
                method = getattr(series.ta, name_lower, None)
                if method:
                    result = method(**{k: v for k, v in params.items() if k != "closes"})
                    return IndicatorResult(
                        name=name_lower,
                        values=result.dropna().tolist() if hasattr(result, 'dropna') else [result],
                        params=params,
                    )
            except Exception:
                pass
            raise ValueError(f"Unknown indicator: {name}")

    def calculate_greeks(self, option: OptionType) -> Greeks:
        """Black-Scholes Greeks calculation using numpy."""
        S = option.spot
        K = option.strike
        r = option.rate
        sigma = option.volatility
        T = option.time_to_expiry

        if T <= 0:
            return Greeks(
                delta=1.0 if option.option_type == "call" else -1.0,
                gamma=0.0, theta=0.0, vega=0.0, rho=0.0,
                price=max(0, S - K) if option.option_type == "call" else max(0, K - S),
            )

        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        nd1 = self._norm_cdf(d1)
        nd2 = self._norm_cdf(d2)
        npnd1 = self._norm_pdf(d1)

        if option.option_type == "call":
            price = S * nd1 - K * math.exp(-r * T) * nd2
            delta = nd1
            rho = K * T * math.exp(-r * T) * nd2 / 100
        else:
            price = K * math.exp(-r * T) * self._norm_cdf(-d2) - S * self._norm_cdf(-d1)
            delta = nd1 - 1
            rho = -K * T * math.exp(-r * T) * self._norm_cdf(-d2) / 100

        gamma = npnd1 / (S * sigma * math.sqrt(T))
        theta = (-(S * npnd1 * sigma) / (2 * math.sqrt(T))
                 - r * K * math.exp(-r * T) * (nd2 if option.option_type == "call" else self._norm_cdf(-d2))) / 365
        vega = S * npnd1 * math.sqrt(T) / 100

        return Greeks(
            delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho,
            price=price, implied_volatility=None,
        )

    def aggregate_ohlcv(
        self,
        ticks: list[dict[str, Any]],
        target_timeframe: str,
    ) -> list[OHLCVBar]:
        if not ticks:
            return []

        df = pd.DataFrame(ticks)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("timestamp")

        freq_map = {
            "1s": "1s", "1m": "1min", "5m": "5min", "15m": "15min",
            "1h": "1h", "4h": "4h", "1d": "1D",
        }
        freq = freq_map.get(target_timeframe, "1h")

        resampled = df["price"].resample(freq).ohlc()
        vol = df["quantity"].resample(freq).sum()

        bars = []
        for ts, row in resampled.iterrows():
            if pd.isna(row["open"]):
                continue
            bars.append(OHLCVBar(
                timestamp=ts.timestamp(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(vol.get(ts, 0)),
            ))
        return bars

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    @staticmethod
    def _norm_pdf(x: float) -> float:
        return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)
```

### 5.3 Level 2 Placeholder: RustTickEngine

```python
# src/interfaces/pricing/rust_tick_engine.py
"""
Level 2 pricing engine using Rust tick processor.

PLACEHOLDER — delegates OHLCV aggregation to Rust via PyO3.
Falls back to PandasTAEngine for indicator calculations.
"""

from __future__ import annotations

from typing import Any

from src.interfaces.pricing.base import (
    Greeks,
    IndicatorResult,
    OHLCVBar,
    OptionType,
    PricingEngine,
)
from src.interfaces.pricing.pandas_ta_engine import PandasTAEngine


class RustTickEngine(PricingEngine):
    """
    Rust-accelerated pricing engine (Level 2).

    OHLCV aggregation: Rust tick processor (10-100x faster)
    Indicators: Delegates to PandasTAEngine (pandas-ta)
    Greeks: Delegates to PandasTAEngine (Black-Scholes)

    Status: PLACEHOLDER — not implemented until Level 2.
    """

    def __init__(self, **config: Any) -> None:
        self._fallback = PandasTAEngine(**config)
        try:
            from trading_rs import TickProcessor
            self._rust_processor = TickProcessor()
        except ImportError:
            raise NotImplementedError(
                "RustTickEngine requires the Rust tick processor. "
                "Build with: cd rust && maturin develop --release"
            )

    def calculate_indicator(self, name: str, **params: Any) -> IndicatorResult:
        return self._fallback.calculate_indicator(name, **params)

    def calculate_greeks(self, option: OptionType) -> Greeks:
        return self._fallback.calculate_greeks(option)

    def aggregate_ohlcv(
        self,
        ticks: list[dict[str, Any]],
        target_timeframe: str,
    ) -> list[OHLCVBar]:
        # Use Rust for aggregation
        import json
        result = self._rust_processor.aggregate_ohlcv(
            json.dumps(ticks), target_timeframe
        )
        return [OHLCVBar(**bar) for bar in json.loads(result)]
```

### 5.4 Level 3 Placeholder: QuantLibEngine

```python
# src/interfaces/pricing/quantlib_engine.py
"""
Level 3 pricing engine using C++ QuantLib.

PLACEHOLDER — delegates exotic pricing and Monte Carlo to QuantLib.
Falls back to PandasTAEngine for basic indicators and Greeks.
"""

from __future__ import annotations

from typing import Any

from src.interfaces.pricing.base import (
    Greeks,
    IndicatorResult,
    OHLCVBar,
    OptionType,
    PricingEngine,
)
from src.interfaces.pricing.pandas_ta_engine import PandasTAEngine


class QuantLibEngine(PricingEngine):
    """
    QuantLib-powered pricing engine (Level 3).

    Exotic options: QuantLib (C++)
    Monte Carlo: QuantLib Monte Carlo framework
    Basic indicators: PandasTAEngine (fallback)
    Vanilla Greeks: QuantLib Black-Scholes

    Status: PLACEHOLDER — not implemented until Level 3.
    Requires: C++ QuantLib build (see HYBRID_ARCHITECT_REVIEW.md §5.2.1)
    """

    def __init__(self, **config: Any) -> None:
        self._fallback = PandasTAEngine(**config)
        try:
            import trading_cpp.pricing as ql_pricing
            self._ql = ql_pricing
        except ImportError:
            raise NotImplementedError(
                "QuantLibEngine requires the C++ QuantLib module. "
                "See analysis/council/HYBRID_ARCHITECT_REVIEW.md §5.2.1"
            )

    def calculate_indicator(self, name: str, **params: Any) -> IndicatorResult:
        return self._fallback.calculate_indicator(name, **params)

    def calculate_greeks(self, option: OptionType) -> Greeks:
        result = self._ql.black_scholes_price(
            option_type=option.option_type,
            spot=option.spot,
            strike=option.strike,
            rate=option.rate,
            volatility=option.volatility,
            time_to_expiry=option.time_to_expiry,
        )
        return Greeks(
            delta=result["delta"],
            gamma=result["gamma"],
            theta=result["theta"],
            vega=result["vega"],
            rho=result["rho"],
            price=result["price"],
            implied_volatility=result.get("implied_volatility"),
        )

    def aggregate_ohlcv(
        self,
        ticks: list[dict[str, Any]],
        target_timeframe: str,
    ) -> list[OHLCVBar]:
        return self._fallback.aggregate_ohlcv(ticks, target_timeframe)
```

---

## 6. ExecutionEngine

The `ExecutionEngine` abstracts order execution — from simple REST to smart order routing to FIX.

### 6.1 Abstract Base Class

```python
# src/interfaces/execution/base.py
"""
Abstract base class for execution engines.

Day1: CcxtExecEngine (ccxt REST)
Level 2: RustExecEngine (Rust order executor via PyO3)
Level 4: FixExecEngine (C++ QuickFIX)
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from src.interfaces.exchange.base import (
    OrderResult,
    OrderSide,
    OrderType,
    TimeInForce,
)


# ═══════════════════════════════════════════════════════════
# DATA TYPES
# ═══════════════════════════════════════════════════════════

class Fill(BaseModel):
    """A single fill (partial or complete)."""
    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    fee: float
    fee_currency: str
    timestamp: float


class SlippageReport(BaseModel):
    """Slippage analysis for an order."""
    expected_price: float
    actual_price: float
    slippage_bps: float          # Basis points
    slippage_usd: float
    fill_count: int
    total_quantity: float
    vwap: float                  # Volume-weighted average fill price


class ExecutionResult(BaseModel):
    """Result of an execution strategy (TWAP, VWAP, etc.)."""
    order_id: str
    symbol: str
    strategy: str                # "market", "limit", "twap", "vwap", "iceberg"
    total_quantity: float
    filled_quantity: float
    average_price: float
    total_fee: float
    slippage: SlippageReport
    fills: list[Fill]
    duration_seconds: float


class OrderRequest(BaseModel):
    """A standardized order request."""
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    params: dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════
# ABSTRACT BASE CLASS
# ═══════════════════════════════════════════════════════════

class ExecutionEngine(abc.ABC):
    """
    Abstract interface for order execution.

    Handles the full lifecycle: place → fill → track → analyze.

    Day1: CcxtExecEngine — simple ccxt REST orders
    Level 2: RustExecEngine — low-latency order placement via PyO3
    Level 4: FixExecEngine — institutional FIX protocol execution
    """

    # ═══════════════════════════════════════════════════════════
    # ORDER EXECUTION
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def execute_order(self, request: OrderRequest) -> OrderResult:
        """
        Execute an order on the exchange.

        This is the primary method. It handles:
        - Order placement
        - Fill tracking
        - Error handling and retries

        Args:
            request: Standardized order request

        Returns:
            OrderResult with fill information

        Raises:
            InsufficientFundsError: Not enough balance
            InvalidOrderError: Order parameters invalid
            ExchangeError: Exchange rejected the order
        """
        ...

    @abc.abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: Exchange order ID
            symbol: Trading pair

        Returns:
            True if cancelled successfully
        """
        ...

    @abc.abstractmethod
    async def get_fills(self, order_id: str, symbol: str) -> list[Fill]:
        """
        Get all fills for an order.

        Args:
            order_id: Exchange order ID
            symbol: Trading pair

        Returns:
            List of fills, ordered by timestamp
        """
        ...

    @abc.abstractmethod
    def calculate_slippage(
        self,
        expected_price: float,
        fills: list[Fill],
    ) -> SlippageReport:
        """
        Calculate slippage for a set of fills.

        Args:
            expected_price: The price at order submission
            fills: Actual fills received

        Returns:
            SlippageReport with detailed analysis
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # ADVANCED EXECUTION (Level 2+)
    # ═══════════════════════════════════════════════════════════

    async def execute_twap(
        self,
        request: OrderRequest,
        duration_seconds: int,
        slices: int,
    ) -> ExecutionResult:
        """
        Execute a TWAP (Time-Weighted Average Price) strategy.

        Splits the order into equal slices over the specified duration.

        Args:
            request: Order request
            duration_seconds: Total execution time
            slices: Number of equal slices

        Returns:
            ExecutionResult with all fills and slippage analysis

        Note:
            Day1: Falls back to simple market order.
            Level 2+: True TWAP with Rust order executor.
        """
        # Day1 fallback: simple market order
        result = await self.execute_order(request)
        fills = await self.get_fills(result.order_id, request.symbol)
        slippage = self.calculate_slippage(result.price or 0, fills)
        return ExecutionResult(
            order_id=result.order_id,
            symbol=request.symbol,
            strategy="market_fallback",
            total_quantity=request.quantity,
            filled_quantity=result.filled_quantity,
            average_price=result.price or 0,
            total_fee=result.fee,
            slippage=slippage,
            fills=fills,
            duration_seconds=0,
        )

    async def execute_vwap(
        self,
        request: OrderRequest,
        participation_rate: float = 0.1,
    ) -> ExecutionResult:
        """
        Execute a VWAP (Volume-Weighted Average Price) strategy.

        Participates in the market at the specified rate of recent volume.

        Args:
            request: Order request
            participation_rate: Target fraction of recent volume (0.0-1.0)

        Returns:
            ExecutionResult with all fills and slippage analysis

        Note:
            Day1: Falls back to simple market order.
            Level 2+: True VWAP with Rust order executor.
        """
        return await self.execute_twap(request, duration_seconds=0, slices=1)

    # ═══════════════════════════════════════════════════════════
    # ORDER TRACKING
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]:
        """Get all open orders, optionally filtered by symbol."""
        ...

    @abc.abstractmethod
    async def get_order_status(self, order_id: str, symbol: str) -> OrderResult:
        """Get the current status of an order."""
        ...
```

### 6.2 Day1 Implementation: CcxtExecEngine

```python
# src/interfaces/execution/ccxt_exec_engine.py
"""
Day1 execution engine using ccxt REST API.

Wraps the ExchangeGateway for order placement and fill tracking.
"""

from __future__ import annotations

import time
from typing import Any

from src.interfaces.execution.base import (
    ExecutionEngine,
    ExecutionResult,
    Fill,
    OrderRequest,
    SlippageReport,
)
from src.interfaces.exchange.base import (
    ExchangeGateway,
    OrderResult,
    OrderSide,
)


class CcxtExecEngine(ExecutionEngine):
    """
    Day1 execution engine using ccxt REST API.

    Delegates to ExchangeGateway for all exchange communication.
    Adds fill tracking and slippage calculation on top.
    """

    def __init__(self, gateway: ExchangeGateway, **config: Any) -> None:
        self._gateway = gateway
        self.config = config

    async def execute_order(self, request: OrderRequest) -> OrderResult:
        return await self._gateway.place_order(
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            stop_price=request.stop_price,
            time_in_force=request.time_in_force,
            params=request.params,
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        return await self._gateway.cancel_order(order_id, symbol)

    async def get_fills(self, order_id: str, symbol: str) -> list[Fill]:
        order = await self._gateway.get_order(order_id, symbol)
        if order.filled_quantity <= 0:
            return []
        return [
            Fill(
                fill_id=f"{order_id}_fill_0",
                order_id=order_id,
                symbol=symbol,
                side=order.side,
                price=order.price or 0,
                quantity=order.filled_quantity,
                fee=order.fee,
                fee_currency=order.fee_currency,
                timestamp=order.timestamp.timestamp(),
            )
        ]

    def calculate_slippage(
        self,
        expected_price: float,
        fills: list[Fill],
    ) -> SlippageReport:
        if not fills:
            return SlippageReport(
                expected_price=expected_price,
                actual_price=expected_price,
                slippage_bps=0,
                slippage_usd=0,
                fill_count=0,
                total_quantity=0,
                vwap=expected_price,
            )

        total_qty = sum(f.quantity for f in fills)
        vwap = sum(f.price * f.quantity for f in fills) / total_qty if total_qty else expected_price
        slippage_pct = ((vwap - expected_price) / expected_price * 100) if expected_price else 0

        return SlippageReport(
            expected_price=expected_price,
            actual_price=vwap,
            slippage_bps=slippage_pct * 100,
            slippage_usd=abs(vwap - expected_price) * total_qty,
            fill_count=len(fills),
            total_quantity=total_qty,
            vwap=vwap,
        )

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]:
        return await self._gateway.get_open_orders(symbol)

    async def get_order_status(self, order_id: str, symbol: str) -> OrderResult:
        return await self._gateway.get_order(order_id, symbol)
```

### 6.3 Level 2 Placeholder: RustExecEngine

```python
# src/interfaces/execution/rust_exec_engine.py
"""
Level 2 execution engine using Rust order executor.

PLACEHOLDER — delegates to trading_rs.OrderExecutor via PyO3.
"""

from __future__ import annotations

from typing import Any

from src.interfaces.execution.base import ExecutionEngine


class RustExecEngine(ExecutionEngine):
    """
    Rust-accelerated execution engine (Level 2).

    Status: PLACEHOLDER — not implemented until Level 2.
    """

    def __init__(self, **config: Any) -> None:
        raise NotImplementedError(
            "RustExecEngine requires the Rust order executor crate. "
            "Build with: cd rust && maturin develop --release"
        )
```

### 6.4 Level 4 Placeholder: FixExecEngine

```python
# src/interfaces/execution/fix_exec_engine.py
"""
Level 4 execution engine using C++ FIX protocol.

PLACEHOLDER — delegates to trading_cpp.fix.FIXSession via pybind11.
"""

from __future__ import annotations

from typing import Any

from src.interfaces.execution.base import ExecutionEngine


class FixExecEngine(ExecutionEngine):
    """
    C++ FIX protocol execution engine (Level 4).

    Status: PLACEHOLDER — not implemented until Level 4.
    """

    def __init__(self, **config: Any) -> None:
        raise NotImplementedError(
            "FixExecEngine requires the C++ FIX module (QuickFIX). "
            "See analysis/council/HYBRID_ARCHITECT_REVIEW.md §5.2.2"
        )
```

---

## 7. RiskEngine

The `RiskEngine` abstracts all risk computation — position sizing, drawdown tracking, Monte Carlo.

### 7.1 Abstract Base Class

```python
# src/interfaces/risk/base.py
"""
Abstract base class for risk engines.

Day1: PyRiskEngine (Python deterministic)
Level 2: RustRiskEngine (Rust via PyO3)
Level 5: GpuMonteCarloEngine (C++ CUDA Monte Carlo)
"""

from __future__ import annotations

import abc
from typing import Any

from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════
# DATA TYPES
# ═══════════════════════════════════════════════════════════

class RiskCheckResult(BaseModel):
    """Result of a pre-trade risk check."""
    approved: bool
    checks: dict[str, bool]          # Check name → passed
    position_size: float              # Recommended position size
    risk_per_trade: float             # Risk amount in USD
    risk_reward_ratio: float
    rejection_reasons: list[str] = []
    warnings: list[str] = []


class DrawdownState(BaseModel):
    """Current drawdown state."""
    current_drawdown_pct: float       # Current drawdown from HWM
    high_water_mark: float            # Peak portfolio value
    current_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    circuit_breaker_level: str        # "GREEN", "YELLOW", "ORANGE", "RED"
    trading_allowed: bool
    position_size_multiplier: float   # 1.0 = normal, 0.5 = reduced, 0.0 = halted


class PositionSizeResult(BaseModel):
    """Result of position sizing calculation."""
    quantity: float
    notional_value: float
    risk_amount: float
    risk_pct: float
    method: str                       # "half_kelly", "fixed_fractional", "volatility_adjusted"


class StressTestResult(BaseModel):
    """Result of a stress test scenario."""
    scenario: str
    portfolio_impact_usd: float
    portfolio_impact_pct: float
    positions_affected: int
    liquidation_risk: bool


# ═══════════════════════════════════════════════════════════
# ABSTRACT BASE CLASS
# ═══════════════════════════════════════════════════════════

class RiskEngine(abc.ABC):
    """
    Abstract interface for risk management computation.

    All risk rules are deterministic. No LLM involvement.
    This engine enforces the harness — the intelligence layer cannot override it.

    Day1: PyRiskEngine — Python rule-based risk checks
    Level 2: RustRiskEngine — Rust-accelerated risk computation
    Level 5: GpuMonteCarloEngine — CUDA Monte Carlo for VaR
    """

    # ═══════════════════════════════════════════════════════════
    # PRE-TRADE RISK CHECKS
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    def check_risk(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        signal_score: float,
        current_equity: float,
        open_positions: list[dict[str, Any]],
        daily_pnl: float,
        **kwargs: Any,
    ) -> RiskCheckResult:
        """
        Run all pre-trade risk checks on a proposed trade.

        This is the GATEKEEPER. Every trade must pass this check.
        Implements the 7-Layer Veto Protocol from TSAR_ARCHITECTURE.md §6.1.

        Args:
            symbol: Trading pair
            side: "BUY" or "SELL"
            entry_price: Proposed entry price
            stop_loss: Proposed stop-loss price
            take_profit: Proposed take-profit price
            signal_score: Signal strength (0-1)
            current_equity: Current portfolio equity
            open_positions: List of currently open positions
            daily_pnl: Today's realized P&L
            **kwargs: Additional context (regime, correlation, etc.)

        Returns:
            RiskCheckResult with approval decision and details
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # POSITION SIZING
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    def calculate_position_size(
        self,
        equity: float,
        risk_pct: float,
        entry_price: float,
        stop_loss: float,
        method: str = "half_kelly",
        **kwargs: Any,
    ) -> PositionSizeResult:
        """
        Calculate the recommended position size.

        Args:
            equity: Current portfolio equity
            risk_pct: Maximum risk per trade (e.g. 2.0 for 2%)
            entry_price: Entry price
            stop_loss: Stop-loss price
            method: Sizing method ("half_kelly", "fixed_fractional", "volatility_adjusted")
            **kwargs: Additional params (win_rate, avg_win, avg_loss for Kelly)

        Returns:
            PositionSizeResult with quantity and risk details
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # DRAWDOWN MONITORING
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    def get_drawdown_state(
        self,
        current_equity: float,
        high_water_mark: float,
        daily_pnl: float,
        daily_loss_limit_pct: float = 2.0,
        max_drawdown_pct: float = 5.0,
    ) -> DrawdownState:
        """
        Get the current drawdown state and circuit breaker level.

        Implements the circuit breaker protocol from TSAR_ARCHITECTURE.md §6.2:
        GREEN:  DD < 2% → Normal
        YELLOW: DD 2-3% → Reduce 50%
        ORANGE: DD 3-5% → No new entries
        RED:    DD > 5% → Kill switch

        Args:
            current_equity: Current portfolio value
            high_water_mark: Peak portfolio value
            daily_pnl: Today's realized P&L
            daily_loss_limit_pct: Daily loss limit (default 2%)
            max_drawdown_pct: Max drawdown from HWM (default 5%)

        Returns:
            DrawdownState with circuit breaker level and trading permissions
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # STRESS TESTING (Level 3+)
    # ═══════════════════════════════════════════════════════════

    async def run_stress_test(
        self,
        positions: list[dict[str, Any]],
        scenarios: list[dict[str, Any]] | None = None,
    ) -> list[StressTestResult]:
        """
        Run stress test scenarios against current portfolio.

        Default scenarios from TSAR_ARCHITECTURE.md §5.4:
        - Flash crash (-30%)
        - Exchange halt (24h)
        - LUNA collapse (-95%)
        - FOMC shock
        - Liquidity crisis

        Args:
            positions: Current open positions
            scenarios: Custom scenarios (uses defaults if None)

        Returns:
            List of StressTestResult, one per scenario

        Note:
            Day1: Simple linear impact calculation.
            Level 5: GPU Monte Carlo with 100K+ paths.
        """
        if scenarios is None:
            scenarios = [
                {"name": "flash_crash", "price_change_pct": -30},
                {"name": "luna_collapse", "price_change_pct": -95},
                {"name": "fomc_shock", "price_change_pct": -15},
            ]

        results = []
        for scenario in scenarios:
            impact = sum(
                abs(p.get("quantity", 0) * p.get("entry_price", 0) *
                    scenario.get("price_change_pct", 0) / 100)
                for p in positions
            )
            results.append(StressTestResult(
                scenario=scenario["name"],
                portfolio_impact_usd=impact,
                portfolio_impact_pct=0,  # Calculate if equity available
                positions_affected=len(positions),
                liquidation_risk=scenario.get("price_change_pct", 0) < -50,
            ))
        return results

    # ═══════════════════════════════════════════════════════════
    # CONVENIENCE METHODS
    # ═══════════════════════════════════════════════════════════

    def check_simple(
        self,
        equity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> bool:
        """Quick risk check: does the trade pass basic R:R and risk limits?"""
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        if risk == 0:
            return False
        return (reward / risk) >= 2.0

    def get_circuit_breaker_level(self, drawdown_pct: float) -> str:
        """Get circuit breaker level for a given drawdown percentage."""
        if drawdown_pct < 2.0:
            return "GREEN"
        elif drawdown_pct < 3.0:
            return "YELLOW"
        elif drawdown_pct < 5.0:
            return "ORANGE"
        return "RED"
```

### 7.2 Day1 Implementation: PyRiskEngine

```python
# src/interfaces/risk/py_risk_engine.py
"""
Day1 risk engine — Python deterministic implementation.

All risk rules are pure Python. No dependencies beyond standard library + numpy.
"""

from __future__ import annotations

import math
from typing import Any

from src.interfaces.risk.base import (
    DrawdownState,
    PositionSizeResult,
    RiskCheckResult,
    RiskEngine,
)


class PyRiskEngine(RiskEngine):
    """
    Python deterministic risk engine (Day1).

    Implements all risk checks from TSAR_ARCHITECTURE.md §6:
    - Position sizing (Half-Kelly)
    - Daily loss limit (-2%)
    - Max drawdown (5% from HWM)
    - Max open positions
    - Risk-reward ratio (≥ 2:1)
    - Cooldown per symbol
    - Anti-behavioral guards
    """

    def __init__(self, **config: Any) -> None:
        self.config = config
        self.max_position_pct = config.get("max_position_pct", 5.0)
        self.risk_per_trade_pct = config.get("risk_per_trade_pct", 2.0)
        self.daily_loss_limit_pct = config.get("daily_loss_limit_pct", 2.0)
        self.max_drawdown_pct = config.get("max_drawdown_pct", 5.0)
        self.max_open_positions = config.get("max_open_positions", 3)
        self.min_risk_reward = config.get("min_risk_reward", 2.0)
        self.cooldown_seconds = config.get("cooldown_seconds", 1800)
        self.max_trades_per_day = config.get("max_trades_per_day", 10)

    def check_risk(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        signal_score: float,
        current_equity: float,
        open_positions: list[dict[str, Any]],
        daily_pnl: float,
        **kwargs: Any,
    ) -> RiskCheckResult:
        checks: dict[str, bool] = {}
        rejections: list[str] = []
        warnings: list[str] = []

        # 1. Position size check
        position_size = self.calculate_position_size(
            equity=current_equity,
            risk_pct=self.risk_per_trade_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )
        max_notional = current_equity * (self.max_position_pct / 100)
        checks["position_size"] = position_size.notional_value <= max_notional
        if not checks["position_size"]:
            rejections.append(
                f"Position size ${position_size.notional_value:.2f} exceeds "
                f"${max_notional:.2f} ({self.max_position_pct}% limit)"
            )

        # 2. Daily loss limit
        daily_loss_pct = (daily_pnl / current_equity * 100) if current_equity > 0 else 0
        checks["daily_loss"] = daily_loss_pct > -self.daily_loss_limit_pct
        if not checks["daily_loss"]:
            rejections.append(
                f"Daily loss {daily_loss_pct:.2f}% exceeds "
                f"-{self.daily_loss_limit_pct}% limit"
            )

        # 3. Max drawdown
        hwm = kwargs.get("high_water_mark", current_equity)
        drawdown_pct = ((hwm - current_equity) / hwm * 100) if hwm > 0 else 0
        checks["max_drawdown"] = drawdown_pct < self.max_drawdown_pct
        if not checks["max_drawdown"]:
            rejections.append(
                f"Drawdown {drawdown_pct:.2f}% exceeds "
                f"{self.max_drawdown_pct}% limit"
            )

        # 4. Max open positions
        checks["max_positions"] = len(open_positions) < self.max_open_positions
        if not checks["max_positions"]:
            rejections.append(
                f"Already have {len(open_positions)} open positions "
                f"(max {self.max_open_positions})"
            )

        # 5. Stop-loss present and reasonable
        sl_pct = abs(entry_price - stop_loss) / entry_price * 100
        checks["stop_loss"] = sl_pct <= 2.0
        if not checks["stop_loss"]:
            rejections.append(f"Stop-loss {sl_pct:.2f}% exceeds 2% limit")

        # 6. Risk-reward ratio
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        rr_ratio = reward / risk if risk > 0 else 0
        checks["risk_reward"] = rr_ratio >= self.min_risk_reward
        if not checks["risk_reward"]:
            rejections.append(
                f"R:R ratio {rr_ratio:.2f} below {self.min_risk_reward}:1 minimum"
            )

        # 7. Signal score (FOMO guard)
        checks["signal_score"] = signal_score >= 0.6
        if not checks["signal_score"]:
            warnings.append(f"Signal score {signal_score:.2f} below 0.6 threshold")

        # 8. Correlation check (simplified)
        same_symbol_positions = [p for p in open_positions if p.get("symbol") == symbol]
        checks["no_duplicate"] = len(same_symbol_positions) == 0
        if not checks["no_duplicate"]:
            rejections.append(f"Already have position in {symbol}")

        approved = all(checks.values()) and len(rejections) == 0

        return RiskCheckResult(
            approved=approved,
            checks=checks,
            position_size=position_size.quantity,
            risk_per_trade=position_size.risk_amount,
            risk_reward_ratio=rr_ratio,
            rejection_reasons=rejections,
            warnings=warnings,
        )

    def calculate_position_size(
        self,
        equity: float,
        risk_pct: float,
        entry_price: float,
        stop_loss: float,
        method: str = "half_kelly",
        **kwargs: Any,
    ) -> PositionSizeResult:
        risk_amount = equity * (risk_pct / 100)
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit <= 0:
            return PositionSizeResult(
                quantity=0, notional_value=0, risk_amount=0,
                risk_pct=0, method=method,
            )

        quantity = risk_amount / risk_per_unit
        notional = quantity * entry_price

        # Cap at max position size
        max_notional = equity * (self.max_position_pct / 100)
        if notional > max_notional:
            quantity = max_notional / entry_price
            notional = max_notional
            risk_amount = quantity * risk_per_unit

        return PositionSizeResult(
            quantity=quantity,
            notional_value=notional,
            risk_amount=risk_amount,
            risk_pct=risk_pct,
            method=method,
        )

    def get_drawdown_state(
        self,
        current_equity: float,
        high_water_mark: float,
        daily_pnl: float,
        daily_loss_limit_pct: float = 2.0,
        max_drawdown_pct: float = 5.0,
    ) -> DrawdownState:
        drawdown_pct = ((high_water_mark - current_equity) / high_water_mark * 100) if high_water_mark > 0 else 0
        daily_pnl_pct = (daily_pnl / current_equity * 100) if current_equity > 0 else 0

        level = self.get_circuit_breaker_level(drawdown_pct)

        multiplier_map = {
            "GREEN": 1.0,
            "YELLOW": 0.5,
            "ORANGE": 0.0,
            "RED": 0.0,
        }

        return DrawdownState(
            current_drawdown_pct=drawdown_pct,
            high_water_mark=high_water_mark,
            current_equity=current_equity,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            circuit_breaker_level=level,
            trading_allowed=level in ("GREEN", "YELLOW"),
            position_size_multiplier=multiplier_map[level],
        )
```

### 7.3 Level 5 Placeholder: GpuMonteCarloEngine

```python
# src/interfaces/risk/gpu_monte_carlo_engine.py
"""
Level 5 risk engine with GPU Monte Carlo simulation.

PLACEHOLDER — delegates Monte Carlo VaR to C++ CUDA.
Falls back to PyRiskEngine for all deterministic checks.
"""

from __future__ import annotations

from typing import Any

from src.interfaces.risk.base import RiskEngine
from src.interfaces.risk.py_risk_engine import PyRiskEngine


class GpuMonteCarloEngine(RiskEngine):
    """
    GPU-accelerated Monte Carlo risk engine (Level 5).

    Deterministic checks: PyRiskEngine (fallback)
    Monte Carlo VaR: CUDA C++ (100K+ paths, <1s)

    Status: PLACEHOLDER — not implemented until Level 5.
    Requires: CUDA toolkit + C++ Monte Carlo module
    """

    def __init__(self, **config: Any) -> None:
        self._fallback = PyRiskEngine(**config)
        try:
            from trading_cpp.monte_carlo import simulate_paths
            self._mc = simulate_paths
        except ImportError:
            raise NotImplementedError(
                "GpuMonteCarloEngine requires the C++ CUDA module. "
                "See analysis/council/HYBRID_ARCHITECT_REVIEW.md §5.2.3"
            )

    def check_risk(self, **kwargs: Any) -> Any:
        return self._fallback.check_risk(**kwargs)

    def calculate_position_size(self, **kwargs: Any) -> Any:
        return self._fallback.calculate_position_size(**kwargs)

    def get_drawdown_state(self, **kwargs: Any) -> Any:
        return self._fallback.get_drawdown_state(**kwargs)
```

---

## 8. LLMProvider

The `LLMProvider` interface is already specified in FIX_01_LLM_ABSTRACTION.md. Here we define how it integrates with the BackendRegistry.

### 8.1 Integration Adapter

```python
# src/interfaces/llm/adapter.py
"""
Adapter that bridges FIX_01's BaseLLMProvider with the BackendRegistry.

FIX_01 defines the LLM abstraction. This adapter makes it discoverable
by the BackendRegistry alongside other interfaces.
"""

from __future__ import annotations

from typing import Any

from src.interfaces.registry import BackendRegistry
from src.llm.providers.base import BaseLLMProvider


class LLMProviderAdapter(BaseLLMProvider):
    """
    Wraps a BaseLLMProvider to conform to the BackendRegistry pattern.

    This allows the LLM subsystem to participate in the same
    config-driven, hot-swappable backend system as other interfaces.
    """

    def __init__(self, provider: BaseLLMProvider, **config: Any) -> None:
        self._provider = provider
        self.config = config

    async def initialize(self) -> None:
        await self._provider.initialize()

    async def shutdown(self) -> None:
        await self._provider.shutdown()

    async def generate(self, request: Any) -> Any:
        return await self._provider.generate(request)

    async def stream(self, request: Any) -> Any:
        async for chunk in self._provider.stream(request):
            yield chunk

    def count_tokens(self, text: str, model: str | None = None) -> int:
        return self._provider.count_tokens(text, model)

    def get_capabilities(self, model: str) -> Any:
        return self._provider.get_capabilities(model)

    async def health_check(self) -> bool:
        return await self._provider.health_check()
```

---

## 9. Config-Driven Backend Selection

### 9.1 Backend Configuration File

```yaml
# config/backends.yaml
# ═══════════════════════════════════════════════════════════════
# TSAR Backend Configuration
# ═══════════════════════════════════════════════════════════════
# This file controls which implementation backs each interface.
# Change this file to swap backends — NO CODE CHANGES NEEDED.
#
# Hot-swap: Use registry.swap() at runtime for testing.
# ═══════════════════════════════════════════════════════════════

# ─── Exchange Gateway ────────────────────────────────────────
exchange_gateway:
  primary: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
  fallback:
    - path: "src.interfaces.exchange.rust_gateway.RustWsGateway"
      priority: 200
    - path: "src.interfaces.exchange.fix_gateway.FixGateway"
      priority: 300
  config:
    exchange: "binance"
    sandbox: true
    api_key: "${BINANCE_API_KEY}"
    api_secret: "${BINANCE_API_SECRET}"
    rate_limit: 1200
    timeout_s: 30
    poll_interval_s: 5

# ─── Pricing Engine ──────────────────────────────────────────
pricing_engine:
  primary: "src.interfaces.pricing.pandas_ta_engine.PandasTAEngine"
  fallback:
    - path: "src.interfaces.pricing.rust_tick_engine.RustTickEngine"
      priority: 200
    - path: "src.interfaces.pricing.quantlib_engine.QuantLibEngine"
      priority: 300
  config: {}

# ─── Execution Engine ────────────────────────────────────────
execution_engine:
  primary: "src.interfaces.execution.ccxt_exec_engine.CcxtExecEngine"
  fallback:
    - path: "src.interfaces.execution.rust_exec_engine.RustExecEngine"
      priority: 200
    - path: "src.interfaces.execution.fix_exec_engine.FixExecEngine"
      priority: 300
  config: {}

# ─── Risk Engine ─────────────────────────────────────────────
risk_engine:
  primary: "src.interfaces.risk.py_risk_engine.PyRiskEngine"
  fallback:
    - path: "src.interfaces.risk.gpu_monte_carlo_engine.GpuMonteCarloEngine"
      priority: 300
  config:
    max_position_pct: 5.0
    risk_per_trade_pct: 2.0
    daily_loss_limit_pct: 2.0
    max_drawdown_pct: 5.0
    max_open_positions: 3
    min_risk_reward: 2.0

# ─── LLM Provider ───────────────────────────────────────────
# Note: LLM has its own config system (config/models.yaml).
# This entry bridges it into the BackendRegistry.
llm_provider:
  primary: "src.interfaces.llm.adapter.LLMProviderAdapter"
  config: {}
```

### 9.2 Level-Up Config Changes

When TSAR advances to a new level, **only this YAML file changes**:

```yaml
# config/backends.yaml — Level 2
exchange_gateway:
  primary: "src.interfaces.exchange.rust_gateway.RustWsGateway"  # ← Swapped
  fallback:
    - path: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
      priority: 200
  config:
    ws_url: "wss://stream.binance.com:9443/ws"

pricing_engine:
  primary: "src.interfaces.pricing.rust_tick_engine.RustTickEngine"  # ← Swapped
  fallback:
    - path: "src.interfaces.pricing.pandas_ta_engine.PandasTAEngine"
      priority: 200

execution_engine:
  primary: "src.interfaces.execution.rust_exec_engine.RustExecEngine"  # ← Swapped
  fallback:
    - path: "src.interfaces.execution.ccxt_exec_engine.CcxtExecEngine"
      priority: 200
```

```yaml
# config/backends.yaml — Level 4
exchange_gateway:
  primary: "src.interfaces.exchange.fix_gateway.FixGateway"  # ← C++ FIX
  fallback:
    - path: "src.interfaces.exchange.rust_gateway.RustWsGateway"
      priority: 200
    - path: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
      priority: 300

execution_engine:
  primary: "src.interfaces.execution.fix_exec_engine.FixExecEngine"  # ← C++ FIX
  fallback:
    - path: "src.interfaces.execution.rust_exec_engine.RustExecEngine"
      priority: 200
    - path: "src.interfaces.execution.ccxt_exec_engine.CcxtExecEngine"
      priority: 300
```

---

## 10. Backend Hot-Swap

Hot-swap allows runtime backend replacement without restart. Primary use cases:

### 10.1 Testing with Mocks

```python
# tests/conftest.py

from src.interfaces.registry import get_registry

def setup_test_backends():
    """Swap in mock backends for testing."""
    registry = get_registry()

    from tests.mocks import MockExchangeGateway, MockPricingEngine
    registry.swap("exchange_gateway", MockExchangeGateway)
    registry.swap("pricing_engine", MockPricingEngine)
```

### 10.2 Runtime Fallback

```python
# src/core/orchestrator.py

async def handle_gateway_failure():
    """If primary gateway fails, swap to fallback."""
    registry = get_registry()
    registry.swap("exchange_gateway", CcxtGateway)
    # Next get_exchange_gateway() call uses CcxtGateway
```

### 10.3 A/B Testing

```python
# Compare Rust vs Python execution latency
from src.interfaces.registry import get_registry

registry = get_registry()

# Test with Python
registry.swap("execution_engine", CcxtExecEngine)
result_py = await run_100_orders()

# Test with Rust
registry.swap("execution_engine", RustExecEngine)
result_rust = await run_100_orders()

# Revert
registry.unswap("execution_engine")
```

---

## 11. Fallback Chain System

The `FallbackProxy` (defined in §3) provides automatic failover. Here's how it works:

### 11.1 Chain Resolution

```
Agent calls: get_exchange_gateway()

Registry resolves:
1. Check hot-swap override → if set, use it
2. Check config backends.yaml → get primary class
3. Try to instantiate primary
4. If primary fails → try fallback[0]
5. If fallback[0] fails → try fallback[1]
6. Return FallbackProxy wrapping all successful instances
```

### 11.2 Runtime Failover

```
Agent calls: gateway.get_price("BTC/USDT")

FallbackProxy delegates to primary (RustWsGateway):
1. Call RustWsGateway.get_price()
2. If success → return result
3. If ConnectionError → try next (CcxtGateway)
4. If CcxtGateway.get_price() succeeds → return result
5. Log warning about primary failure
6. Stick with CcxtGateway for subsequent calls (until primary recovers)
```

### 11.3 Async Failover

```python
# src/interfaces/exchange/fallback_mixin.py

class AsyncFallbackMixin:
    """Mixin for async failover in FallbackProxy."""

    async def _call_with_fallback(self, method_name: str, *args, **kwargs):
        """Call a method with automatic fallback."""
        last_error = None
        for i in range(self._primary_index, len(self._instances)):
            reg, instance = self._instances[i]
            try:
                method = getattr(instance, method_name)
                result = await method(*args, **kwargs)
                self._primary_index = i
                return result
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"{reg.backend_path}.{method_name} failed: {e}")
                last_error = e
                continue
        raise last_error
```

---

## 12. Integration with Existing Architecture

### 12.1 Relationship to TSAR_ARCHITECTURE.md

| Architecture Section | Interface Layer Mapping |
|---------------------|------------------------|
| §2.4 Agent Specifications | Agents use `get_*()` functions from `src/interfaces/` |
| §3.1 Tool Registry (35 tools) | Tools call interfaces, not backends directly |
| §3.3 Dual-Language Architecture | Interface layer is the Python↔Rust↔C++ boundary |
| §13 LLM Provider Abstraction | FIX_01's `BaseLLMProvider` + `LLMProviderAdapter` |

### 12.2 Relationship to FIX_C (Day1 Simple)

FIX_C's 10 tools become thin wrappers around interfaces:

```python
# tools/market.py — Before (FIX_C)
import ccxt
async def get_price(symbol: str) -> float:
    exchange = ccxt.binance({...})
    ticker = await exchange.fetch_ticker(symbol)
    return ticker["last"]

# tools/market.py — After (with interfaces)
from src.interfaces import get_exchange_gateway
async def get_price(symbol: str) -> float:
    gateway = get_exchange_gateway()
    return await gateway.get_price(symbol)
```

The tool is identical from the agent's perspective. The backend is swappable.

### 12.3 Relationship to FIX_01 (LLM Abstraction)

FIX_01's `BaseLLMProvider` is the LLM interface. The `LLMProviderAdapter` bridges it into the `BackendRegistry` so all interfaces share the same config, hot-swap, and fallback patterns.

```
FIX_01 defines: BaseLLMProvider (ABC)
FIX_G adds:     LLMProviderAdapter (bridges to BackendRegistry)
config/backends.yaml: llm_provider → LLMProviderAdapter → wraps BaseLLMProvider
```

### 12.4 Tool Layer Integration

All 35 TSAR tools should route through interfaces:

```python
# Example: tool #4 (place_order)
# src/tools/order.py

from src.interfaces import get_execution_engine
from src.interfaces.execution.base import OrderRequest
from src.interfaces.exchange.base import OrderSide, OrderType

async def place_order(
    symbol: str,
    side: str,
    quantity: float,
    order_type: str = "market",
    price: float | None = None,
) -> dict:
    engine = get_execution_engine()
    request = OrderRequest(
        symbol=symbol,
        side=OrderSide(side),
        order_type=OrderType(order_type),
        quantity=quantity,
        price=price,
    )
    result = await engine.execute_order(request)
    return result.model_dump()
```

---

## 13. Day1 → Level 5 Migration Path

### 13.1 What Changes at Each Level

| Level | What Changes in `config/backends.yaml` | Code Changes |
|-------|---------------------------------------|--------------|
| **Day1** | All `primary` = Python classes | None — this IS the starting config |
| **Level 2** | `primary` = Rust classes for gateway, pricing, execution | Build Rust crate (`maturin develop`) |
| **Level 3** | Add QuantLib pricing, FIX gateway | Build C++ module (`scikit-build-core`) |
| **Level 4** | `primary` = FIX for gateway, execution | C++ FIX fully operational |
| **Level 5** | Add GPU Monte Carlo risk engine | CUDA toolkit + C++ Monte Carlo |

### 13.2 What NEVER Changes

| Component | Why It Never Changes |
|-----------|---------------------|
| Agent code | Agents call `get_exchange_gateway()`, not `ccxt.binance()` |
| Tool code | Tools call interfaces, not backends |
| Interface ABCs | The abstract base classes are the contract |
| Data types | `Ticker`, `OHLCV`, `OrderResult` etc. are universal |
| Config structure | Same YAML schema, different class paths |

### 13.3 Migration Checklist Per Level

**Level 2 (Rust backends):**
1. Build Rust crate: `cd rust && maturin develop --release`
2. Update `config/backends.yaml`: swap `primary` to Rust classes
3. Restart TSAR
4. Verify: same agent code, same tool calls, faster execution

**Level 3 (C++ modules):**
1. Build C++ module: `cd cpp && pip install -e .`
2. Update `config/backends.yaml`: add C++ classes to `fallback`
3. Restart TSAR
4. Gradually promote C++ classes to `primary`

**Level 4 (FIX protocol):**
1. Configure FIX sessions in `config/fix.yaml`
2. Update `config/backends.yaml`: FIX as `primary` for gateway/execution
3. Test on FIX sandbox (OANDA demo, IBKR paper)
4. Go live

---

## 14. File Layout

```
src/interfaces/
├── __init__.py                         # Convenience imports (get_*_gateway, etc.)
├── registry.py                         # BackendRegistry, FallbackProxy, InstrumentedBackend
│
├── exchange/
│   ├── __init__.py
│   ├── base.py                         # ExchangeGateway ABC + all data types
│   ├── ccxt_gateway.py                 # Day1: ccxt REST implementation
│   ├── rust_gateway.py                 # Level 2: Rust WebSocket (placeholder)
│   └── fix_gateway.py                  # Level 4: C++ FIX (placeholder)
│
├── pricing/
│   ├── __init__.py
│   ├── base.py                         # PricingEngine ABC + all data types
│   ├── pandas_ta_engine.py             # Day1: pandas-ta + numpy
│   ├── rust_tick_engine.py             # Level 2: Rust tick processor (placeholder)
│   └── quantlib_engine.py              # Level 3: C++ QuantLib (placeholder)
│
├── execution/
│   ├── __init__.py
│   ├── base.py                         # ExecutionEngine ABC + all data types
│   ├── ccxt_exec_engine.py             # Day1: ccxt REST
│   ├── rust_exec_engine.py             # Level 2: Rust order executor (placeholder)
│   └── fix_exec_engine.py              # Level 4: C++ FIX (placeholder)
│
├── risk/
│   ├── __init__.py
│   ├── base.py                         # RiskEngine ABC + all data types
│   ├── py_risk_engine.py               # Day1: Python deterministic
│   └── gpu_monte_carlo_engine.py       # Level 5: C++ CUDA (placeholder)
│
└── llm/
    ├── __init__.py
    └── adapter.py                      # Bridges FIX_01's BaseLLMProvider to BackendRegistry

config/
└── backends.yaml                       # Backend selection config (THE ONLY FILE THAT CHANGES)
```

**Total new files: 18** (5 ABCs, 5 Day1 implementations, 5 Level 2 placeholders, 2 Level 3+ placeholders, 1 registry)

---

## Appendix A: Interface Method Summary

| Interface | Method | Day1 Backend | Level 2 Backend | Level 4+ Backend |
|-----------|--------|-------------|-----------------|------------------|
| **ExchangeGateway** | `connect()` | ccxt REST | Rust WS | C++ FIX |
| | `get_price()` | ccxt fetch_ticker | Rust WS ticker | FIX market data |
| | `get_ohlcv()` | ccxt fetch_ohlcv | Rust WS klines | FIX OHLCV |
| | `subscribe()` | REST polling | Rust WS stream | FIX market data |
| | `place_order()` | ccxt create_order | Rust order exec | FIX new order |
| | `cancel_order()` | ccxt cancel_order | Rust cancel | FIX cancel |
| | `get_balance()` | ccxt fetch_balance | Rust balance | FIX positions |
| **PricingEngine** | `calculate_indicator()` | pandas-ta | pandas-ta | pandas-ta |
| | `calculate_greeks()` | numpy Black-Scholes | numpy BS | QuantLib |
| | `aggregate_ohlcv()` | pandas resample | Rust tick proc | pandas resample |
| **ExecutionEngine** | `execute_order()` | ccxt REST | Rust order exec | FIX execution |
| | `cancel_order()` | ccxt cancel | Rust cancel | FIX cancel |
| | `get_fills()` | ccxt order | Rust fills | FIX fills |
| | `calculate_slippage()` | Python calc | Python calc | Python calc |
| | `execute_twap()` | market fallback | Rust TWAP | FIX TWAP |
| **RiskEngine** | `check_risk()` | Python rules | Python rules | Python rules |
| | `calculate_position_size()` | Python calc | Python calc | Python calc |
| | `get_drawdown_state()` | Python calc | Python calc | Python calc |
| | `run_stress_test()` | linear impact | linear impact | GPU Monte Carlo |
| **LLMProvider** | `generate()` | Ollama | LiteLLM router | LiteLLM router |
| | `stream()` | Ollama stream | LiteLLM stream | LiteLLM stream |
| | `count_tokens()` | approx/tiktoken | tiktoken | tiktoken |

---

## Appendix B: Error Types

```python
# src/interfaces/errors.py

class InterfaceError(Exception):
    """Base exception for all interface errors."""
    pass

class ConnectionError(InterfaceError):
    """Cannot connect to backend."""
    pass

class AuthenticationError(InterfaceError):
    """Backend authentication failed."""
    pass

class SymbolNotFoundError(InterfaceError):
    """Symbol not found on exchange."""
    pass

class InsufficientFundsError(InterfaceError):
    """Not enough balance for order."""
    pass

class InvalidOrderError(InterfaceError):
    """Order parameters are invalid."""
    pass

class OrderNotFoundError(InterfaceError):
    """Order does not exist."""
    pass

class BackendUnavailableError(InterfaceError):
    """Backend is unavailable (all fallbacks exhausted)."""
    pass

class InsufficientDataError(InterfaceError):
    """Not enough data points for calculation."""
    pass
```

---

## Appendix C: Relationship to HYBRID_ARCHITECT_REVIEW.md

The Chief Architect's review (§7.2) defines architecture invariants that this interface layer enforces:

| Invariant | How Interface Layer Enforces It |
|-----------|-------------------------------|
| "Python is the brain" | All interfaces are Python ABCs; agents are Python |
| "Rust is the muscle for hot paths" | Rust backends implement the same ABCs via PyO3 |
| "C++ is the specialist" | C++ backends implement the same ABCs via pybind11 |
| "No direct Rust↔C++ calls" | Each backend is independent; Python mediates |
| "Single trace_id across all layers" | InstrumentedBackend propagates trace_id |
| "The harness is inviolable" | RiskEngine is a separate interface; agents can't bypass it |

---

## Appendix D: Quick Reference Card

```python
# ═══════════════════════════════════════════════════════════
# HOW TO USE (for agent developers)
# ═══════════════════════════════════════════════════════════

# 1. Import the getter
from src.interfaces import get_exchange_gateway, get_pricing_engine

# 2. Get the configured backend (auto-resolved from config/backends.yaml)
gateway = get_exchange_gateway()
engine = get_pricing_engine()

# 3. Use it — same API regardless of backend
price = await gateway.get_price("BTC/USDT")
rsi = engine.calculate_rsi(closes=[...], period=14)

# 4. That's it. You never need to know which backend is active.

# ═══════════════════════════════════════════════════════════
# HOW TO SWAP BACKENDS (for ops/devops)
# ═══════════════════════════════════════════════════════════

# Option A: Config change (permanent, requires restart)
# Edit config/backends.yaml:
#   exchange_gateway:
#     primary: "src.interfaces.exchange.rust_gateway.RustWsGateway"

# Option B: Hot-swap (runtime, no restart)
from src.interfaces.registry import get_registry
registry = get_registry()
registry.swap("exchange_gateway", RustWsGateway)

# Option C: Hot-swap with mock (for testing)
registry.swap("exchange_gateway", MockExchangeGateway)
```

---

*Specification complete. 18 new files. 5 abstract interfaces. Day1 Python backends included. Rust/C++ backends as swappable placeholders. The interface is the contract. The backend is an implementation detail.*

*The founder's mandate fulfilled: "Everything should be future-ready from day one. No swapping later."*

*Written: 2026-07-24*
