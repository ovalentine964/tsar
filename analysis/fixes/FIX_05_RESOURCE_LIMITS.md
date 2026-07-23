# FIX 05 — Tool Resource Limit Enforcement System

**Version:** 1.0.0  
**Date:** 2026-07-24  
**Status:** Specification  
**Priority:** P0 — Critical Gap  
**Owner:** Resource Management Specialist  

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [ResourceLimit Class](#2-resourcelimit-class)
3. [ToolResourcePolicy](#3-toolresourcepolicy)
4. [ResourceEnforcer Middleware](#4-resourceenforcer-middleware)
5. [Global Execution Timeout](#5-global-execution-timeout)
6. [Circuit Breaker Integration](#6-circuit-breaker-integration)
7. [Docker Resource Limits Alignment](#7-docker-resource-limits-alignment)
8. [Prometheus Metrics](#8-prometheus-metrics)
9. [YAML Configuration Schema](#9-yaml-configuration-schema)
10. [Integration with Existing Architecture](#10-integration-with-existing-architecture)
11. [Implementation Checklist](#11-implementation-checklist)

---

## 1. Problem Statement

The TSAR tool architecture (see `trading-super-agent-tools-spec.md`) defines **20+ tools** with varying resource profiles — from lightweight price lookups to CPU-intensive backtesting. Currently:

- **No per-invocation resource limits** — a runaway `calculate_correlation_matrix` can consume unbounded memory
- **No wall-clock enforcement** — tools reference `timeout_ms` in their schema but nothing enforces it at the system level
- **No resource-based circuit breaking** — the existing `CircuitBreaker` in `client.py` only tracks exchange API failures, not resource exhaustion
- **Docker limits exist** (DEPLOYMENT.md §2) but are container-level, not per-tool-invocation
- **A single misbehaving tool can starve the entire agent** — especially dangerous in live trading where the Risk Guardian must remain operational

This specification defines a complete resource limit enforcement layer that sits between the `ToolRegistry` and actual tool execution.

---

## 2. ResourceLimit Class

### 2.1 Data Model

```python
# tools/resources/limits.py
"""
Resource limits for tool invocations.

Each tool invocation gets a ResourceLimit that defines the maximum
resources it may consume. Violations trigger immediate termination.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResourceScope(Enum):
    """Scope at which the limit applies."""
    PER_INVOCATION = "per_invocation"   # Single tool call
    PER_MINUTE = "per_minute"           # Rolling 60s window
    PER_HOUR = "per_hour"               # Rolling 3600s window
    CONCURRENT = "concurrent"           # Max parallel invocations


@dataclass(frozen=True)
class ResourceLimit:
    """
    Immutable resource limit definition for a single tool invocation.

    All limits are hard ceilings. Exceeding any limit triggers the
    kill sequence defined in ResourceEnforcer.
    """

    # ── Memory ──
    max_memory_mb: int = 256
    """Maximum RSS memory (MB) this invocation may use.
    Measured via cgroups v2 memory.current or psutil.Process.memory_info().rss.
    Default 256MB — safe for TA indicator computation on 1000 candles."""

    # ── CPU ──
    max_cpu_seconds: float = 10.0
    """Maximum CPU time (seconds) this invocation may consume.
    Wall-clock waiting (network I/O, sleep) does NOT count.
    Measured via cgroups v2 cpuacct.usage or psutil.Process.cpu_times().
    Default 10s — generous for pandas-ta computation."""

    # ── Wall Clock ──
    max_wall_time_seconds: float = 30.0
    """Maximum wall-clock time (seconds) from invocation start to completion.
    Includes all I/O waits. This is the ultimate deadline.
    Default 30s — matches the global timeout from DEPLOYMENT.md."""

    # ── Network ──
    max_network_requests: int = 100
    """Maximum number of outbound HTTP/WS requests this invocation may make.
    Tracked via a thread-local counter incremented by the exchange client.
    Default 100 — enough for a single exchange fetch with retries."""

    # ── File I/O ──
    max_file_size_mb: int = 50
    """Maximum size (MB) of any single file this invocation may write.
    Applies to SQLite writes, log files, temp files.
    Default 50MB — accommodates large OHLCV cache writes."""

    # ── Output ──
    max_output_size_mb: int = 10
    """Maximum size (MB) of the ToolResult payload (serialized).
    Prevents tools from returning unbounded data structures.
    Default 10MB — accommodates large orderbook snapshots."""

    # ── Metadata ──
    scope: ResourceScope = ResourceScope.PER_INVOCATION
    """Which scope this limit applies to."""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def __post_init__(self):
        # Validate non-negative
        for f in dataclasses.fields(self):
            if f.name in ("scope",):
                continue
            val = getattr(self, f.name)
            if val < 0:
                raise ValueError(f"ResourceLimit.{f.name} must be >= 0, got {val}")


# ── Pre-defined limit profiles ──

LIMIT_CONSERVATIVE = ResourceLimit(
    max_memory_mb=128,
    max_cpu_seconds=5.0,
    max_wall_time_seconds=15.0,
    max_network_requests=10,
    max_file_size_mb=10,
    max_output_size_mb=2,
)

LIMIT_STANDARD = ResourceLimit(
    max_memory_mb=256,
    max_cpu_seconds=10.0,
    max_wall_time_seconds=30.0,
    max_network_requests=100,
    max_file_size_mb=50,
    max_output_size_mb=10,
)

LIMIT_EXPANSIVE = ResourceLimit(
    max_memory_mb=512,
    max_cpu_seconds=30.0,
    max_wall_time_seconds=120.0,
    max_network_requests=500,
    max_file_size_mb=200,
    max_output_size_mb=50,
)

LIMIT_HEAVY = ResourceLimit(
    max_memory_mb=1024,
    max_cpu_seconds=60.0,
    max_wall_time_seconds=300.0,
    max_network_requests=1000,
    max_file_size_mb=500,
    max_output_size_mb=100,
)
```

### 2.2 Limit Rationale by Tool Category

| Tool Category | Profile | max_memory_mb | max_cpu_seconds | max_wall_time_seconds | Rationale |
|---|---|---|---|---|---|
| **Exchange** (`get_price`, `get_balance`, etc.) | Conservative | 128 | 5 | 15 | Network I/O bound, minimal compute |
| **TA Indicators** (`calculate_rsi`, `macd`, etc.) | Standard | 256 | 10 | 30 | pandas-ta on ≤1000 candles |
| **Data** (`fetch_news`, `fetch_onchain`) | Standard | 256 | 10 | 30 | Network I/O + JSON parsing |
| **Risk** (`check_position_limits`, etc.) | Conservative | 128 | 5 | 15 | Deterministic, must be fast |
| **Memory** (`search_trades`, `log_trade`) | Conservative | 128 | 5 | 15 | SQLite operations |
| **Execution** (`smart_order_router`, `twap`) | Standard | 256 | 10 | 30 | Multi-venue coordination |
| **Volume Profile** (`calculate_volume_profile`) | Expansive | 512 | 30 | 60 | Heavy numpy computation |
| **Correlation Matrix** (`get_correlation_matrix`) | Expansive | 512 | 30 | 60 | NxN matrix computation |
| **Pattern Detection** (`detect_patterns`) | Standard | 256 | 15 | 45 | Multiple indicator passes |
| **Stream** (`stream_prices`, `stream_orderbook`) | Special | 256 | — | Continuous | Long-running, see §5.3 |

---

## 3. ToolResourcePolicy

### 3.1 Policy Class

```python
# tools/resources/policy.py
"""
Per-tool resource policy with context-aware overrides.

Resolution order:
1. Context-specific override (e.g., "live_trading" → "place_order")
2. Tool-specific override (e.g., "place_order")
3. Category default (e.g., "exchange")
4. Global default (LIMIT_STANDARD)
"""

from __future__ import annotations

import logging
from typing import Any

from .limits import (
    ResourceLimit,
    LIMIT_CONSERVATIVE,
    LIMIT_STANDARD,
    LIMIT_EXPANSIVE,
    LIMIT_HEAVY,
)

logger = logging.getLogger(__name__)


class TradingContext:
    """Trading context identifiers for context-aware limits."""
    PAPER = "paper_trading"
    LIVE = "live_trading"
    BACKTEST = "backtesting"
    ANALYSIS_ONLY = "analysis_only"


class ToolResourcePolicy:
    """
    Resolves resource limits for a given tool invocation.

    The policy maintains three layers of overrides:
    1. category_defaults — broad tool categories (exchange, analysis, etc.)
    2. tool_overrides    — specific tool names
    3. context_overrides — (context, tool_name) pairs

    Lookup order: context_overrides → tool_overrides → category_defaults → global_default
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._global_default: ResourceLimit = LIMIT_STANDARD
        self._category_defaults: dict[str, ResourceLimit] = {
            "exchange": LIMIT_CONSERVATIVE,
            "analysis": LIMIT_STANDARD,
            "data": LIMIT_STANDARD,
            "risk": LIMIT_CONSERVATIVE,
            "memory": LIMIT_CONSERVATIVE,
            "execution": LIMIT_STANDARD,
        }
        self._tool_overrides: dict[str, ResourceLimit] = {
            # ── Heavy compute tools ──
            "calculate_volume_profile": LIMIT_EXPANSIVE,
            "get_correlation_matrix": LIMIT_EXPANSIVE,
            "detect_patterns": ResourceLimit(
                max_memory_mb=256, max_cpu_seconds=15.0,
                max_wall_time_seconds=45.0, max_network_requests=100,
                max_file_size_mb=50, max_output_size_mb=10,
            ),

            # ── Execution tools (more network, more time) ──
            "smart_order_router": ResourceLimit(
                max_memory_mb=256, max_cpu_seconds=15.0,
                max_wall_time_seconds=30.0, max_network_requests=200,
                max_file_size_mb=50, max_output_size_mb=10,
            ),
            "twap_execute": ResourceLimit(
                max_memory_mb=256, max_cpu_seconds=60.0,
                max_wall_time_seconds=3600.0, max_network_requests=1000,
                max_file_size_mb=50, max_output_size_mb=10,
            ),

            # ── Exchange tools with higher latency tolerance ──
            "fetch_news": ResourceLimit(
                max_memory_mb=256, max_cpu_seconds=10.0,
                max_wall_time_seconds=15.0, max_network_requests=50,
                max_file_size_mb=50, max_output_size_mb=10,
            ),
            "fetch_social_sentiment": ResourceLimit(
                max_memory_mb=256, max_cpu_seconds=10.0,
                max_wall_time_seconds=15.0, max_network_requests=50,
                max_file_size_mb=50, max_output_size_mb=10,
            ),
            "fetch_onchain_data": ResourceLimit(
                max_memory_mb=256, max_cpu_seconds=15.0,
                max_wall_time_seconds=20.0, max_network_requests=50,
                max_file_size_mb=50, max_output_size_mb=10,
            ),
        }
        self._context_overrides: dict[tuple[str, str], ResourceLimit] = {}

        # Apply config overrides if provided
        if config:
            self._apply_config(config)

    def get_limit(self, tool_name: str, context: str = TradingContext.ANALYSIS_ONLY) -> ResourceLimit:
        """
        Resolve the effective resource limit for a tool invocation.

        Args:
            tool_name: The tool's registered name (e.g., "get_price")
            context: Trading context (e.g., TradingContext.LIVE)

        Returns:
            The effective ResourceLimit to enforce.
        """
        # 1. Context-specific override (highest priority)
        ctx_key = (context, tool_name)
        if ctx_key in self._context_overrides:
            limit = self._context_overrides[ctx_key]
            logger.debug(f"Using context override for {tool_name} in {context}")
            return limit

        # 2. Tool-specific override
        if tool_name in self._tool_overrides:
            limit = self._tool_overrides[tool_name]
            logger.debug(f"Using tool override for {tool_name}")
            return limit

        # 3. Category default (infer from tool name prefix)
        category = self._infer_category(tool_name)
        if category in self._category_defaults:
            limit = self._category_defaults[category]
            logger.debug(f"Using category default '{category}' for {tool_name}")
            return limit

        # 4. Global default
        logger.debug(f"Using global default for {tool_name}")
        return self._global_default

    def set_context_override(
        self, context: str, tool_name: str, limit: ResourceLimit
    ) -> None:
        """Register a context-specific override."""
        self._context_overrides[(context, tool_name)] = limit
        logger.info(f"Set context override: {context}/{tool_name} → {limit}")

    def set_tool_override(self, tool_name: str, limit: ResourceLimit) -> None:
        """Register a tool-specific override."""
        self._tool_overrides[tool_name] = limit
        logger.info(f"Set tool override: {tool_name} → {limit}")

    def set_category_default(self, category: str, limit: ResourceLimit) -> None:
        """Register a category default."""
        self._category_defaults[category] = limit
        logger.info(f"Set category default: {category} → {limit}")

    @staticmethod
    def _infer_category(tool_name: str) -> str:
        """Infer tool category from tool name prefix."""
        prefixes = {
            "get_price": "exchange",
            "get_ohlcv": "exchange",
            "get_orderbook": "exchange",
            "place_order": "exchange",
            "cancel_order": "exchange",
            "get_positions": "exchange",
            "get_balance": "exchange",
            "get_funding_rate": "exchange",
            "calculate_": "analysis",
            "detect_": "analysis",
            "fetch_": "data",
            "stream_": "data",
            "check_": "risk",
            "get_portfolio": "risk",
            "get_correlation": "risk",
            "get_drawdown": "risk",
            "log_trade": "memory",
            "search_trades": "memory",
            "get_strategy": "memory",
            "get_lesson": "memory",
            "update_regime": "memory",
            "smart_order": "execution",
            "twap_": "execution",
            "monitor_fills": "execution",
        }
        for prefix, category in prefixes.items():
            if tool_name.startswith(prefix):
                return category
        return "unknown"

    def _apply_config(self, config: dict[str, Any]) -> None:
        """Apply configuration overrides from YAML config."""
        # Global defaults
        if "global_default" in config:
            self._global_default = ResourceLimit(**config["global_default"])

        # Category defaults
        for cat, params in config.get("category_defaults", {}).items():
            self._category_defaults[cat] = ResourceLimit(**params)

        # Tool overrides
        for tool, params in config.get("tool_overrides", {}).items():
            self._tool_overrides[tool] = ResourceLimit(**params)

        # Context overrides
        for ctx_tool, params in config.get("context_overrides", {}).items():
            # Key format: "context:tool_name"
            parts = ctx_tool.split(":", 1)
            if len(parts) == 2:
                self._context_overrides[tuple(parts)] = ResourceLimit(**params)

    def summary(self) -> dict[str, Any]:
        """Return a summary of all configured limits for debugging."""
        return {
            "global_default": self._global_default.to_dict(),
            "category_defaults": {
                k: v.to_dict() for k, v in self._category_defaults.items()
            },
            "tool_overrides": {
                k: v.to_dict() for k, v in self._tool_overrides.items()
            },
            "context_overrides": {
                f"{k[0]}:{k[1]}": v.to_dict()
                for k, v in self._context_overrides.items()
            },
        }
```

### 3.2 Per-Context Limits

Context-aware limits tighten or loosen resources based on trading mode:

| Context | Adjustment | Rationale |
|---|---|---|
| `paper_trading` | Standard limits | No real money at risk, normal experimentation |
| `live_trading` | **Tighter** timeouts (-30%), same memory | Fail fast in live; don't block risk checks |
| `backtesting` | **Looser** memory (+100%), CPU (+200%) | Batch processing, no real-time pressure |
| `analysis_only` | Standard limits | Default mode, no execution tools active |

```python
# Context-specific overrides applied during policy initialization

# Live trading: tighter timeouts, fail fast
LIVE_OVERRIDES = {
    "get_price": ResourceLimit(
        max_memory_mb=128, max_cpu_seconds=3.0,
        max_wall_time_seconds=10.0, max_network_requests=10,
        max_file_size_mb=10, max_output_size_mb=2,
    ),
    "place_order": ResourceLimit(
        max_memory_mb=256, max_cpu_seconds=5.0,
        max_wall_time_seconds=15.0, max_network_requests=50,
        max_file_size_mb=50, max_output_size_mb=10,
    ),
    "check_position_limits": ResourceLimit(
        max_memory_mb=128, max_cpu_seconds=2.0,
        max_wall_time_seconds=5.0, max_network_requests=0,
        max_file_size_mb=10, max_output_size_mb=2,
    ),
}

# Backtesting: generous resources for batch computation
BACKTEST_OVERRIDES = {
    "calculate_volume_profile": ResourceLimit(
        max_memory_mb=1024, max_cpu_seconds=60.0,
        max_wall_time_seconds=120.0, max_network_requests=100,
        max_file_size_mb=200, max_output_size_mb=50,
    ),
    "get_correlation_matrix": ResourceLimit(
        max_memory_mb=1024, max_cpu_seconds=60.0,
        max_wall_time_seconds=120.0, max_network_requests=100,
        max_file_size_mb=200, max_output_size_mb=50,
    ),
}
```

---

## 4. ResourceEnforcer Middleware

### 4.1 Architecture

The `ResourceEnforcer` sits between the `ToolRegistry` and the actual tool execution. It wraps every `tool.execute()` call with pre/during/post enforcement.

```
┌─────────────────────────────────────────────────────────────┐
│                    ToolRegistry.call_tool()                   │
│                           │                                  │
│                           ▼                                  │
│              ┌────────────────────────┐                      │
│              │   ResourceEnforcer     │                      │
│              │                        │                      │
│              │  1. Pre-check:         │                      │
│              │     - Resolve limits   │                      │
│              │     - Check system     │                      │
│              │       capacity         │                      │
│              │     - Check concurrent │                      │
│              │       invocations      │                      │
│              │                        │                      │
│              │  2. Execute with       │                      │
│              │     monitoring:        │                      │
│              │     - Wall-clock timer │                      │
│              │     - Memory watcher   │                      │
│              │     - CPU watcher      │                      │
│              │     - Network counter  │                      │
│              │                        │                      │
│              │  3. Post-execution:    │                      │
│              │     - Log consumption  │                      │
│              │     - Update metrics   │                      │
│              │     - Update circuit   │                      │
│              │       breaker          │                      │
│              └───────────┬────────────┘                      │
│                          │                                   │
│                          ▼                                   │
│                 tool.execute(**kwargs)                        │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Implementation

```python
# tools/resources/enforcer.py
"""
Resource enforcement middleware for tool invocations.

Enforces memory, CPU, wall-time, network, file I/O, and output size limits.
Provides pre-execution checks, in-flight monitoring, and post-execution logging.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

import psutil

from .limits import ResourceLimit, ResourceScope
from .policy import ToolResourcePolicy, TradingContext
from .metrics import ResourceMetrics

logger = logging.getLogger(__name__)


@dataclass
class ResourceUsage:
    """Measured resource consumption for a single tool invocation."""
    tool_name: str
    invocation_id: str
    context: str
    wall_time_seconds: float = 0.0
    cpu_time_seconds: float = 0.0
    peak_memory_mb: float = 0.0
    network_requests: int = 0
    files_written_bytes: int = 0
    output_size_bytes: int = 0
    limit: ResourceLimit | None = None
    violations: list[str] = field(default_factory=list)
    killed: bool = False
    kill_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "invocation_id": self.invocation_id,
            "context": self.context,
            "wall_time_seconds": round(self.wall_time_seconds, 3),
            "cpu_time_seconds": round(self.cpu_time_seconds, 3),
            "peak_memory_mb": round(self.peak_memory_mb, 1),
            "network_requests": self.network_requests,
            "files_written_bytes": self.files_written_bytes,
            "output_size_bytes": self.output_size_bytes,
            "violations": self.violations,
            "killed": self.killed,
            "kill_reason": self.kill_reason,
        }


class ResourceViolationError(Exception):
    """Raised when a tool invocation exceeds its resource limits."""
    def __init__(self, violations: list[str], usage: ResourceUsage):
        self.violations = violations
        self.usage = usage
        super().__init__(f"Resource violations: {'; '.join(violations)}")


class ResourceEnforcer:
    """
    Middleware that enforces resource limits on tool invocations.

    Features:
    - Pre-execution capacity checks
    - In-flight wall-clock timeout (SIGKILL after grace period)
    - Memory monitoring via psutil / cgroups v2
    - CPU time tracking
    - Network request counting (via exchange client integration)
    - Post-execution resource logging
    - Prometheus metrics emission
    """

    # Grace period after timeout warning before SIGKILL
    GRACE_PERIOD_SECONDS = 5.0

    # How often to poll resource usage during execution (ms)
    MONITOR_INTERVAL_MS = 500

    # Memory check overhead tolerance — don't kill if we're within 5% of limit
    MEMORY_TOLERANCE_PCT = 0.05

    def __init__(
        self,
        policy: ToolResourcePolicy,
        metrics: ResourceMetrics | None = None,
    ):
        self._policy = policy
        self._metrics = metrics or ResourceMetrics()
        self._active_invocations: dict[str, ResourceUsage] = {}
        self._concurrent_semaphore = asyncio.Semaphore(10)  # max 10 concurrent
        self._network_counter: dict[str, int] = {}  # invocation_id → count

        # Detect cgroups v2 availability
        self._cgroups_v2 = os.path.exists("/sys/fs/cgroup/memory.current")
        if self._cgroups_v2:
            logger.info("ResourceEnforcer: Using cgroups v2 for memory monitoring")
        else:
            logger.info("ResourceEnforcer: Using psutil for memory monitoring (cgroups v2 not available)")

    async def enforce(
        self,
        tool_name: str,
        execute_fn: Callable,
        kwargs: dict[str, Any],
        context: str = TradingContext.ANALYSIS_ONLY,
        invocation_id: str = "",
    ) -> Any:
        """
        Wrap a tool execution with resource enforcement.

        Args:
            tool_name: Registered tool name
            execute_fn: The tool's execute() coroutine
            kwargs: Arguments to pass to execute_fn
            context: Trading context for limit resolution
            invocation_id: Unique ID for this invocation (auto-generated if empty)

        Returns:
            The ToolResult from the wrapped execution

        Raises:
            ResourceViolationError: If limits are exceeded
        """
        if not invocation_id:
            invocation_id = f"{tool_name}_{int(time.time() * 1000)}"

        limit = self._policy.get_limit(tool_name, context)
        usage = ResourceUsage(
            tool_name=tool_name,
            invocation_id=invocation_id,
            context=context,
            limit=limit,
        )

        # ── Pre-execution checks ──
        await self._pre_check(tool_name, limit, invocation_id)

        # ── Execute with monitoring ──
        try:
            result = await self._execute_with_monitoring(
                tool_name, execute_fn, kwargs, limit, usage
            )
            return result
        except ResourceViolationError:
            raise
        except Exception:
            raise  # Re-raise non-resource errors
        finally:
            # ── Post-execution logging ──
            await self._post_execution(usage)

    async def _pre_check(
        self, tool_name: str, limit: ResourceLimit, invocation_id: str
    ) -> None:
        """Pre-execution resource availability checks."""
        # Check concurrent invocation limit
        if len(self._active_invocations) >= 10:
            # Reject if too many concurrent invocations
            raise ResourceViolationError(
                [f"Too many concurrent invocations: {len(self._active_invocations)}/10"],
                ResourceUsage(
                    tool_name=tool_name,
                    invocation_id=invocation_id,
                    context="pre_check",
                ),
            )

        # Check available system memory
        mem = psutil.virtual_memory()
        available_mb = mem.available / (1024 * 1024)
        if available_mb < limit.max_memory_mb:
            raise ResourceViolationError(
                [f"Insufficient system memory: {available_mb:.0f}MB available, "
                 f"{limit.max_memory_mb}MB required"],
                ResourceUsage(
                    tool_name=tool_name,
                    invocation_id=invocation_id,
                    context="pre_check",
                ),
            )

        logger.debug(
            f"Pre-check passed for {tool_name} ({invocation_id}): "
            f"memory={available_mb:.0f}MB available, "
            f"concurrent={len(self._active_invocations)}/10"
        )

    async def _execute_with_monitoring(
        self,
        tool_name: str,
        execute_fn: Callable,
        kwargs: dict[str, Any],
        limit: ResourceLimit,
        usage: ResourceUsage,
    ) -> Any:
        """Execute the tool with in-flight resource monitoring."""
        process = psutil.Process(os.getpid())
        start_time = time.monotonic()
        start_cpu = process.cpu_times()
        start_rss = process.memory_info().rss

        self._active_invocations[usage.invocation_id] = usage
        self._network_counter[usage.invocation_id] = 0

        # Create monitoring task
        monitor_task = asyncio.create_task(
            self._monitor_loop(process, limit, usage, start_time)
        )

        # Create wall-clock timeout task
        timeout_task = asyncio.create_task(
            self._wall_clock_timeout(tool_name, limit, usage, start_time)
        )

        try:
            # Execute the tool
            result = await execute_fn(**kwargs)

            # Cancel monitoring tasks (execution completed normally)
            monitor_task.cancel()
            timeout_task.cancel()

            # Record final measurements
            elapsed = time.monotonic() - start_time
            cpu_times = process.cpu_times()
            cpu_used = (cpu_times.user - start_cpu.user) + (cpu_times.system - start_cpu.system)
            peak_rss = process.memory_info().rss

            usage.wall_time_seconds = elapsed
            usage.cpu_time_seconds = cpu_used
            usage.peak_memory_mb = max(
                (peak_rss - start_rss) / (1024 * 1024),
                0.0
            )
            usage.network_requests = self._network_counter.get(usage.invocation_id, 0)

            # Check output size
            if hasattr(result, 'to_dict'):
                import json
                output_bytes = len(json.dumps(result.to_dict()).encode('utf-8'))
                usage.output_size_bytes = output_bytes

            # Validate final resource consumption
            violations = self._check_violations(usage, limit)
            if violations:
                usage.violations = violations
                raise ResourceViolationError(violations, usage)

            return result

        except asyncio.CancelledError:
            # Timeout or monitor killed us
            raise
        finally:
            self._active_invocations.pop(usage.invocation_id, None)
            self._network_counter.pop(usage.invocation_id, None)
            monitor_task.cancel()
            timeout_task.cancel()

    async def _monitor_loop(
        self,
        process: psutil.Process,
        limit: ResourceLimit,
        usage: ResourceUsage,
        start_time: float,
    ) -> None:
        """Periodically check resource consumption during execution."""
        try:
            while True:
                await asyncio.sleep(self.MONITOR_INTERVAL_MS / 1000.0)

                elapsed = time.monotonic() - start_time

                # ── Memory check ──
                rss = process.memory_info().rss
                mem_mb = rss / (1024 * 1024)
                if mem_mb > usage.peak_memory_mb:
                    usage.peak_memory_mb = mem_mb

                mem_limit = limit.max_memory_mb
                if mem_mb > mem_limit * (1 + self.MEMORY_TOLERANCE_PCT):
                    usage.violations.append(
                        f"Memory limit exceeded: {mem_mb:.1f}MB > {mem_limit}MB"
                    )
                    usage.killed = True
                    usage.kill_reason = "memory_limit"
                    logger.error(
                        f"RESOURCE KILL: {usage.tool_name} ({usage.invocation_id}) "
                        f"exceeded memory limit: {mem_mb:.1f}MB > {mem_limit}MB"
                    )
                    raise ResourceViolationError(usage.violations, usage)

                # ── CPU check ──
                cpu_times = process.cpu_times()
                cpu_used = (cpu_times.user + cpu_times.system)
                if cpu_used > limit.max_cpu_seconds:
                    usage.violations.append(
                        f"CPU time limit exceeded: {cpu_used:.1f}s > {limit.max_cpu_seconds}s"
                    )
                    usage.killed = True
                    usage.kill_reason = "cpu_limit"
                    logger.error(
                        f"RESOURCE KILL: {usage.tool_name} ({usage.invocation_id}) "
                        f"exceeded CPU limit: {cpu_used:.1f}s > {limit.max_cpu_seconds}s"
                    )
                    raise ResourceViolationError(usage.violations, usage)

                # ── Network check ──
                net_count = self._network_counter.get(usage.invocation_id, 0)
                if net_count > limit.max_network_requests:
                    usage.violations.append(
                        f"Network request limit exceeded: {net_count} > {limit.max_network_requests}"
                    )
                    usage.killed = True
                    usage.kill_reason = "network_limit"
                    raise ResourceViolationError(usage.violations, usage)

        except asyncio.CancelledError:
            pass  # Normal — execution completed

    async def _wall_clock_timeout(
        self,
        tool_name: str,
        limit: ResourceLimit,
        usage: ResourceUsage,
        start_time: float,
    ) -> None:
        """Wall-clock timeout with escalation."""
        warn_at = limit.max_wall_time_seconds * 0.8
        kill_at = limit.max_wall_time_seconds

        # Wait until 80% of timeout
        await asyncio.sleep(warn_at)

        elapsed = time.monotonic() - start_time
        if elapsed >= kill_at:
            # Already past limit (shouldn't happen, but safe check)
            usage.violations.append(f"Wall time limit exceeded: {elapsed:.1f}s > {kill_at}s")
            usage.killed = True
            usage.kill_reason = "wall_time_limit"
            raise ResourceViolationError(usage.violations, usage)

        # Warn at 80%
        remaining = kill_at - elapsed
        logger.warning(
            f"RESOURCE WARNING: {tool_name} ({usage.invocation_id}) "
            f"at 80% of wall time limit ({elapsed:.1f}s / {kill_at}s). "
            f"Remaining: {remaining:.1f}s"
        )

        # Wait for the remaining 20%
        await asyncio.sleep(remaining)

        # Grace period
        final_elapsed = time.monotonic() - start_time
        usage.violations.append(
            f"Wall time limit exceeded: {final_elapsed:.1f}s > {kill_at}s"
        )
        usage.killed = True
        usage.kill_reason = "wall_time_limit"
        usage.wall_time_seconds = final_elapsed

        logger.error(
            f"RESOURCE KILL: {tool_name} ({usage.invocation_id}) "
            f"exceeded wall time limit: {final_elapsed:.1f}s > {kill_at}s"
        )
        raise ResourceViolationError(usage.violations, usage)

    def _check_violations(
        self, usage: ResourceUsage, limit: ResourceLimit
    ) -> list[str]:
        """Check all resource limits against measured usage."""
        violations = []

        if usage.wall_time_seconds > limit.max_wall_time_seconds:
            violations.append(
                f"Wall time: {usage.wall_time_seconds:.1f}s > {limit.max_wall_time_seconds}s"
            )

        if usage.cpu_time_seconds > limit.max_cpu_seconds:
            violations.append(
                f"CPU time: {usage.cpu_time_seconds:.1f}s > {limit.max_cpu_seconds}s"
            )

        if usage.peak_memory_mb > limit.max_memory_mb * (1 + self.MEMORY_TOLERANCE_PCT):
            violations.append(
                f"Memory: {usage.peak_memory_mb:.1f}MB > {limit.max_memory_mb}MB"
            )

        if usage.network_requests > limit.max_network_requests:
            violations.append(
                f"Network: {usage.network_requests} > {limit.max_network_requests}"
            )

        max_output_bytes = limit.max_output_size_mb * 1024 * 1024
        if usage.output_size_bytes > max_output_bytes:
            violations.append(
                f"Output size: {usage.output_size_bytes / 1024 / 1024:.1f}MB "
                f"> {limit.max_output_size_mb}MB"
            )

        return violations

    async def _post_execution(self, usage: ResourceUsage) -> None:
        """Log resource consumption and update metrics."""
        # Log
        if usage.violations:
            logger.warning(
                f"Resource violations for {usage.tool_name} ({usage.invocation_id}): "
                f"{'; '.join(usage.violations)}"
            )
        else:
            logger.debug(
                f"Resource usage for {usage.tool_name}: "
                f"wall={usage.wall_time_seconds:.2f}s, "
                f"cpu={usage.cpu_time_seconds:.2f}s, "
                f"mem={usage.peak_memory_mb:.1f}MB, "
                f"net={usage.network_requests}"
            )

        # Update Prometheus metrics
        self._metrics.record_usage(usage)

    def increment_network_counter(self, invocation_id: str) -> None:
        """Called by exchange client to track network requests per invocation."""
        if invocation_id in self._network_counter:
            self._network_counter[invocation_id] += 1

    def get_active_count(self) -> int:
        """Number of currently active monitored invocations."""
        return len(self._active_invocations)

    def get_active_invocations(self) -> dict[str, dict]:
        """Snapshot of all active invocations for debugging."""
        return {
            k: v.to_dict() for k, v in self._active_invocations.items()
        }
```

### 4.3 Integration with BaseTool

The enforcer wraps tool execution transparently via the `ToolRegistry`:

```python
# tools/registry.py (updated)

class ToolRegistry:
    """Central registry with resource enforcement."""

    def __init__(self, enforcer: ResourceEnforcer | None = None):
        self._tools: dict[str, BaseTool] = {}
        self._enforcer = enforcer

    def register(self, tool: BaseTool) -> None:
        name = tool.schema().name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    async def call_tool(
        self,
        name: str,
        context: str = TradingContext.ANALYSIS_ONLY,
        **kwargs
    ) -> ToolResult:
        """Execute a tool with optional resource enforcement."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {name}",
                error_code="VALIDATION_ERROR",
            )

        if self._enforcer:
            try:
                return await self._enforcer.enforce(
                    tool_name=name,
                    execute_fn=tool.execute,
                    kwargs=kwargs,
                    context=context,
                )
            except ResourceViolationError as e:
                return ToolResult(
                    success=False,
                    error=f"Resource limit exceeded: {'; '.join(e.violations)}",
                    error_code="RESOURCE_LIMIT_EXCEEDED",
                    metadata={"resource_usage": e.usage.to_dict()},
                )
        else:
            return await tool.execute(**kwargs)
```

### 4.4 Network Request Tracking

The exchange client manager must track network requests per invocation:

```python
# tools/exchange/client.py (updated — add invocation tracking)

class ExchangeClientManager:
    """Manages exchange clients with resource-aware request counting."""

    def __init__(self, config_path: str = "config/exchanges.yaml",
                 enforcer: ResourceEnforcer | None = None):
        self._clients: dict[str, ccxt.Exchange] = {}
        self._configs: dict[str, ExchangeConfig] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._config_path = config_path
        self._enforcer = enforcer
        # Thread-local storage for current invocation ID
        self._current_invocation_id: str = ""

    def set_invocation_id(self, invocation_id: str) -> None:
        """Set the current invocation ID for network tracking."""
        self._current_invocation_id = invocation_id

    def _track_request(self) -> None:
        """Increment network request counter for current invocation."""
        if self._enforcer and self._current_invocation_id:
            self._enforcer.increment_network_counter(self._current_invocation_id)

    async def get_client(self, exchange_id: str) -> ccxt.Exchange:
        """Get or create an exchange client."""
        if exchange_id not in self._clients:
            # ... existing initialization code ...
            pass

        # Track the network request
        self._track_request()

        return self._clients[exchange_id]
```

---

## 5. Global Execution Timeout

### 5.1 Timeout Architecture

The global execution timeout is a **safety net** that operates independently of per-tool limits. It ensures no tool invocation can block the agent indefinitely.

```
Timeline for a tool call with 30s default timeout:

0s                                              30s
│────────────────────────────────────────────────│
│                                                │
│  Normal execution window                       │
│                                                │
├──────────────── 24s (80%) ────────────────────┤
│  ⚠️ WARNING emitted                            │
│                                                │
├─────────────────────────────── 30s (100%) ────┤
│  🔴 ResourceViolationError raised              │
│                                                │
├─────────────────────────────── 35s (grace) ───┤
│  ☠️ SIGKILL (if still running)                 │
```

### 5.2 Timeout Configuration

```python
# tools/resources/timeout.py
"""
Global execution timeout with escalation.

This is separate from ResourceEnforcer's wall-clock timeout —
it provides a second layer of defense and handles streaming/
long-running tools differently.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Default timeouts per tool category (seconds)
DEFAULT_TIMEOUTS = {
    # Exchange tools
    "get_price": 5.0,
    "get_ohlcv": 8.0,
    "get_orderbook": 5.0,
    "place_order": 15.0,
    "cancel_order": 8.0,
    "get_positions": 8.0,
    "get_balance": 8.0,
    "get_funding_rate": 5.0,

    # Analysis tools
    "calculate_rsi": 3.0,
    "calculate_macd": 3.0,
    "calculate_bollinger": 3.0,
    "calculate_atr": 3.0,
    "calculate_ema": 3.0,
    "calculate_volume_profile": 5.0,
    "detect_patterns": 5.0,

    # Data tools
    "fetch_news": 15.0,
    "fetch_social_sentiment": 15.0,
    "fetch_onchain_data": 20.0,
    "fetch_macro_calendar": 15.0,

    # Risk tools
    "check_position_limits": 2.0,
    "calculate_position_size": 2.0,
    "get_portfolio_exposure": 3.0,
    "get_correlation_matrix": 8.0,
    "get_drawdown_stats": 3.0,

    # Memory tools
    "log_trade": 2.0,
    "search_trades": 3.0,
    "get_strategy_performance": 3.0,
    "get_lesson": 2.0,
    "update_regime_state": 1.0,

    # Execution tools
    "smart_order_router": 20.0,
    "calculate_slippage": 2.0,
    "twap_execute": 3600.0,  # Long-running — special handling
    "monitor_fills": 8.0,
}

# Global default timeout for tools not listed above
GLOBAL_DEFAULT_TIMEOUT = 30.0


class ExecutionTimeout:
    """
    Manages per-tool execution timeouts with escalation.

    Timeout levels:
    1. Warning at 80% of timeout
    2. Kill at 100% of timeout (raise exception)
    3. SIGKILL at 100% + grace period (force stop)
    """

    WARNING_THRESHOLD = 0.8  # 80%
    GRACE_PERIOD_SECONDS = 5.0

    def __init__(
        self,
        tool_timeouts: dict[str, float] | None = None,
        global_default: float = GLOBAL_DEFAULT_TIMEOUT,
    ):
        self._timeouts = {**DEFAULT_TIMEOUTS, **(tool_timeouts or {})}
        self._global_default = global_default

    def get_timeout(self, tool_name: str) -> float:
        """Get the timeout for a specific tool."""
        return self._timeouts.get(tool_name, self._global_default)

    async def execute_with_timeout(
        self,
        tool_name: str,
        execute_fn: Callable,
        kwargs: dict[str, Any],
    ) -> Any:
        """Execute a tool with timeout enforcement."""
        timeout = self.get_timeout(tool_name)
        warn_at = timeout * self.WARNING_THRESHOLD

        # Create the execution task
        execution_task = asyncio.create_task(execute_fn(**kwargs))

        # Create the warning timer
        async def warn_timer():
            await asyncio.sleep(warn_at)
            if not execution_task.done():
                logger.warning(
                    f"TIMEOUT WARNING: {tool_name} at {warn_at:.0f}s "
                    f"({self.WARNING_THRESHOLD:.0%} of {timeout:.0f}s limit)"
                )

        warn_task = asyncio.create_task(warn_timer())

        try:
            # Wait for execution with timeout
            result = await asyncio.wait_for(execution_task, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            logger.error(
                f"TIMEOUT KILL: {tool_name} exceeded {timeout:.0f}s timeout"
            )

            # Attempt graceful cancellation
            execution_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(execution_task),
                    timeout=self.GRACE_PERIOD_SECONDS,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

            raise ResourceViolationError(
                [f"Execution timeout: {timeout:.0f}s exceeded"],
                ResourceUsage(
                    tool_name=tool_name,
                    invocation_id=f"timeout_{tool_name}",
                    context="timeout",
                    wall_time_seconds=timeout,
                    killed=True,
                    kill_reason="execution_timeout",
                ),
            )

        finally:
            warn_task.cancel()


class StreamingTimeout:
    """
    Special timeout handling for long-running streaming tools.

    Streaming tools (stream_prices, stream_orderbook) don't have a
    wall-clock timeout. Instead, they have:
    - Heartbeat timeout: if no message received in N seconds, reconnect
    - Maximum lifetime: if running for > N hours, restart
    """

    HEARTBEAT_TIMEOUT_SECONDS = 30.0
    MAX_LIFETIME_HOURS = 24.0
    MAX_RECONNECT_ATTEMPTS = 10

    def __init__(
        self,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT_SECONDS,
        max_lifetime_hours: float = MAX_LIFETIME_HOURS,
    ):
        self._heartbeat_timeout = heartbeat_timeout
        self._max_lifetime_hours = max_lifetime_hours
```

### 5.3 Long-Running Tool Handling

Streaming tools (`stream_prices`, `stream_orderbook`) are exempt from wall-clock timeouts but have their own safety mechanisms:

| Control | Value | Behavior |
|---|---|---|
| Heartbeat timeout | 30s | If no message received, force reconnect |
| Maximum lifetime | 24h | Restart stream after 24h to prevent leaks |
| Max reconnect attempts | 10 | Halt stream after 10 consecutive failures |
| Memory ceiling | 256MB | Stream buffer cannot exceed this |
| CPU ceiling | N/A | WebSocket I/O bound, no CPU concern |

---

## 6. Circuit Breaker Integration

### 6.1 Resource-Aware Circuit Breaker

Extends the existing `CircuitBreaker` in `client.py` to track resource violations:

```python
# tools/resources/circuit_breaker.py
"""
Resource-aware circuit breaker.

Tracks resource violations separately from API failures.
Opens after N consecutive resource violations to prevent
a misconfigured or runaway tool from consuming all resources.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"         # Normal operation
    OPEN = "open"             # Rejecting requests
    HALF_OPEN = "half_open"   # Testing recovery


@dataclass
class ResourceCircuitBreaker:
    """
    Circuit breaker that trips on resource violations.

    States:
    - CLOSED: Normal operation, all limits apply normally
    - OPEN: Tool is blocked after N consecutive violations
    - HALF_OPEN: Allow one probe with reduced limits

    Transition:
    - CLOSED → OPEN: After `failure_threshold` consecutive violations
    - OPEN → HALF_OPEN: After `recovery_timeout_s` seconds
    - HALF_OPEN → CLOSED: Probe succeeds
    - HALF_OPEN → OPEN: Probe fails (back to OPEN with longer timeout)
    """

    tool_name: str
    failure_threshold: int = 3
    recovery_timeout_s: float = 60.0
    max_recovery_timeout_s: float = 3600.0  # Cap at 1 hour
    backoff_multiplier: float = 2.0

    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _total_failures: int = field(default=0, init=False)
    _total_successes: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _current_recovery_timeout: float = field(default=0.0, init=False)
    _opened_at: float = field(default=0.0, init=False)

    def record_resource_violation(self) -> None:
        """Record a resource limit violation."""
        self._consecutive_failures += 1
        self._total_failures += 1
        self._last_failure_time = time.time()

        if self._consecutive_failures >= self.failure_threshold:
            self._open_circuit()

    def record_success(self) -> None:
        """Record a successful execution."""
        self._consecutive_failures = 0
        self._total_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            self._close_circuit()

    def allow_request(self) -> bool:
        """Check if a request should be allowed."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._opened_at
            if elapsed >= self._current_recovery_timeout:
                self._transition_to_half_open()
                return True  # Allow one probe
            return False

        if self._state == CircuitState.HALF_OPEN:
            return True  # Allow one probe

        return False

    def get_state(self) -> dict:
        """Get current circuit breaker state for monitoring."""
        return {
            "tool_name": self.tool_name,
            "state": self._state.value,
            "consecutive_failures": self._consecutive_failures,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "recovery_timeout_s": self._current_recovery_timeout,
            "time_until_half_open": max(
                0,
                self._current_recovery_timeout - (time.time() - self._opened_at)
            ) if self._state == CircuitState.OPEN else 0,
        }

    def _open_circuit(self) -> None:
        """Transition to OPEN state."""
        self._state = CircuitState.OPEN
        self._opened_at = time.time()

        # Exponential backoff on repeated opens
        if self._current_recovery_timeout == 0:
            self._current_recovery_timeout = self.recovery_timeout_s
        else:
            self._current_recovery_timeout = min(
                self._current_recovery_timeout * self.backoff_multiplier,
                self.max_recovery_timeout_s,
            )

        logger.warning(
            f"Circuit breaker OPEN for {self.tool_name}: "
            f"{self._consecutive_failures} consecutive violations. "
            f"Recovery in {self._current_recovery_timeout:.0f}s"
        )

    def _close_circuit(self) -> None:
        """Transition to CLOSED state (normal operation)."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._current_recovery_timeout = self.recovery_timeout_s  # Reset backoff
        logger.info(f"Circuit breaker CLOSED for {self.tool_name}: recovered")

    def _transition_to_half_open(self) -> None:
        """Transition to HALF_OPEN state (probe mode)."""
        self._state = CircuitState.HALF_OPEN
        logger.info(
            f"Circuit breaker HALF_OPEN for {self.tool_name}: "
            f"allowing probe request"
        )


class ResourceCircuitBreakerManager:
    """Manages circuit breakers for all tools."""

    def __init__(self):
        self._breakers: dict[str, ResourceCircuitBreaker] = {}

    def get_breaker(self, tool_name: str) -> ResourceCircuitBreaker:
        """Get or create a circuit breaker for a tool."""
        if tool_name not in self._breakers:
            self._breakers[tool_name] = ResourceCircuitBreaker(tool_name=tool_name)
        return self._breakers[tool_name]

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool invocation is allowed by circuit breaker."""
        breaker = self._breakers.get(tool_name)
        if breaker is None:
            return True  # No breaker = always allowed
        return breaker.allow_request()

    def get_all_states(self) -> dict[str, dict]:
        """Get state of all circuit breakers for monitoring."""
        return {
            name: breaker.get_state()
            for name, breaker in self._breakers.items()
        }

    def reset(self, tool_name: str) -> None:
        """Manually reset a circuit breaker (for admin use)."""
        if tool_name in self._breakers:
            self._breakers[tool_name]._close_circuit()
            logger.info(f"Manually reset circuit breaker for {tool_name}")
```

### 6.2 Integration with ResourceEnforcer

```python
# In ResourceEnforcer.__init__:
self._circuit_breakers = ResourceCircuitBreakerManager()

# In ResourceEnforcer._pre_check (add after existing checks):
if not self._circuit_breakers.is_allowed(tool_name):
    raise ResourceViolationError(
        [f"Circuit breaker open for {tool_name} — too many recent resource violations"],
        ResourceUsage(
            tool_name=tool_name,
            invocation_id=invocation_id,
            context="circuit_breaker",
        ),
    )

# In ResourceEnforcer._post_execution (add):
breaker = self._circuit_breakers.get_breaker(usage.tool_name)
if usage.violations:
    breaker.record_resource_violation()
else:
    breaker.record_success()
```

### 6.3 Circuit Breaker State Diagram

```
                    ┌──────────┐
         ┌─────────│  CLOSED  │◄─────────────────┐
         │         └────┬─────┘                   │
         │              │                         │
         │    N consecutive                       │
         │    resource violations                 │
         │              │                         │
         │              ▼                         │
         │         ┌──────────┐             Probe succeeds
         │         │   OPEN   │──────────────────┘
         │         └────┬─────┘     (HALF_OPEN → CLOSED)
         │              │
         │    recovery_timeout
         │    elapses     │
         │              ▼
         │         ┌──────────┐
         └────────►│HALF_OPEN │
           Probe   └──────────┘
           fails
           (back to OPEN
            with 2x timeout)
```

---

## 7. Docker Resource Limits Alignment

### 7.1 Container-Level vs Tool-Level Limits

Docker provides **container-level** resource isolation. The ResourceEnforcer provides **tool-level** enforcement within the Python agent container. These are complementary layers:

```
┌─────────────────────────────────────────────────────────┐
│                   Docker Container: agent                 │
│                    (1.0 CPU, 1GB RAM)                     │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │              ResourceEnforcer                       │  │
│  │                                                     │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐         │  │
│  │  │ get_price│  │calculate │  │  place   │         │  │
│  │  │ (256MB,  │  │ _rsi     │  │  _order  │         │  │
│  │  │  10s CPU)│  │(256MB,   │  │(256MB,   │         │  │
│  │  └──────────┘  │ 10s CPU) │  │ 10s CPU) │         │  │
│  │                └──────────┘  └──────────┘         │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Tool limits are a SUBSET of container limits            │
│  Container limit is the absolute ceiling                 │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Updated docker-compose.prod.yml

The `agent` container resource limits must account for the overhead of the ResourceEnforcer itself plus the sum of concurrent tool invocations:

```yaml
# docker/docker-compose.prod.yml (agent service — updated)

services:
  agent:
    image: ghcr.io/${GITHUB_REPO}/agent:${IMAGE_TAG:-latest}
    volumes:
      - trading-data:/data
      - ./config.prod.yaml:/app/config/config.yaml:ro
    environment:
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379
      - DATABASE_PATH=/data/tsar.db
      - ENV=production
      - LOG_LEVEL=INFO
      - RESOURCE_LIMITS_ENABLED=true
      - RESOURCE_MAX_CONCURRENT=10
    env_file:
      - .env.production
    networks:
      - internal
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 1G        # Container ceiling
        reservations:
          cpus: "0.5"
          memory: 512M
    # Per-container cgroup constraints (alternative to deploy.resources)
    # These are enforced by the kernel, not Docker
    pids_limit: 200           # Max processes/threads
    read_only: false          # Need write for SQLite, logs
    tmpfs:
      - /tmp:size=100M        # Limit temp file usage
    restart: always
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

### 7.3 Per-Container Tool Isolation (Future: v2)

For maximum isolation, individual tools can run in separate micro-containers:

```yaml
# docker/docker-compose.tools.yml (future — for high-risk tools)

services:
  tool-backtest:
    image: ghcr.io/${GITHUB_REPO}/tool-runner:${IMAGE_TAG:-latest}
    command: ["python", "-m", "tools.runner", "--tool", "backtest_engine"]
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2G
    read_only: true
    networks:
      - internal

  tool-correlation:
    image: ghcr.io/${GITHUB_REPO}/tool-runner:${IMAGE_TAG:-latest}
    command: ["python", "-m", "tools.runner", "--tool", "get_correlation_matrix"]
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 1G
    read_only: true
    networks:
      - internal
```

### 7.4 cAdvisor Integration

Deploy cAdvisor alongside Prometheus for container-level resource monitoring:

```yaml
# Add to docker-compose.prod.yml:

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.49.1
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    ports:
      - "127.0.0.1:8080:8080"
    networks:
      - internal
    deploy:
      resources:
        limits:
          cpus: "0.1"
          memory: 128M
    restart: always
```

```yaml
# monitoring/prometheus.yml (add cAdvisor scrape)

  - job_name: "cadvisor"
    static_configs:
      - targets: ["cadvisor:8080"]
    scrape_interval: 15s

# monitoring/alert_rules.yml (add container alerts)

  - name: container_alerts
    rules:
      - alert: ContainerMemoryHigh
        expr: container_memory_usage_bytes{container="agent"} / container_spec_memory_limit_bytes > 0.85
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Agent container memory above 85%"

      - alert: ContainerOOMKill
        expr: increase(container_oom_events_total{container="agent"}[5m]) > 0
        for: 0s
        labels:
          severity: critical
        annotations:
          summary: "Agent container was OOM killed"
```

---

## 8. Prometheus Metrics

### 8.1 Metrics Definitions

```python
# tools/resources/metrics.py
"""
Prometheus metrics for resource usage tracking.

All metrics follow the naming convention:
  tsar_tool_resource_{metric_name}
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:
    from .enforcer import ResourceUsage

logger = logging.getLogger(__name__)


# ── Gauges: Current resource usage per tool ──

TOOL_RESOURCE_MEMORY_MB = Gauge(
    "tsar_tool_resource_memory_mb",
    "Peak memory usage (MB) of the last tool invocation",
    ["tool_name"],
)

TOOL_RESOURCE_CPU_SECONDS = Gauge(
    "tsar_tool_resource_cpu_seconds",
    "CPU time (seconds) of the last tool invocation",
    ["tool_name"],
)

TOOL_RESOURCE_WALL_TIME_SECONDS = Gauge(
    "tsar_tool_resource_wall_time_seconds",
    "Wall-clock time (seconds) of the last tool invocation",
    ["tool_name"],
)

TOOL_RESOURCE_NETWORK_REQUESTS = Gauge(
    "tsar_tool_resource_network_requests",
    "Network requests made by the last tool invocation",
    ["tool_name"],
)

TOOL_RESOURCE_OUTPUT_SIZE_BYTES = Gauge(
    "tsar_tool_resource_output_size_bytes",
    "Output payload size (bytes) of the last tool invocation",
    ["tool_name"],
)

# ── Counters: Violations and kills ──

TOOL_RESOURCE_VIOLATIONS = Counter(
    "tsar_tool_resource_violations_total",
    "Total resource limit violations",
    ["tool_name", "violation_type"],
    # violation_type: memory, cpu, wall_time, network, output_size
)

TOOL_RESOURCE_KILLS = Counter(
    "tsar_tool_resource_kills_total",
    "Total tool invocations killed for exceeding limits",
    ["tool_name", "kill_reason"],
    # kill_reason: memory_limit, cpu_limit, wall_time_limit, network_limit, execution_timeout
)

# ── Histograms: Distribution of resource usage ──

TOOL_RESOURCE_WALL_TIME_HISTOGRAM = Histogram(
    "tsar_tool_resource_wall_time_distribution_seconds",
    "Distribution of wall-clock execution times",
    ["tool_name"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0],
)

TOOL_RESOURCE_MEMORY_HISTOGRAM = Histogram(
    "tsar_tool_resource_memory_distribution_mb",
    "Distribution of memory usage",
    ["tool_name"],
    buckets=[1, 5, 10, 25, 50, 100, 256, 512, 1024],
)

# ── Circuit Breaker metrics ──

TOOL_CIRCUIT_BREAKER_STATE = Gauge(
    "tsar_tool_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)",
    ["tool_name"],
)

TOOL_CIRCUIT_BREAKER_FAILURES = Counter(
    "tsar_tool_circuit_breaker_failures_total",
    "Total circuit breaker failures (consecutive violations)",
    ["tool_name"],
)

# ── Concurrency metrics ──

TOOL_ACTIVE_INVOCATIONS = Gauge(
    "tsar_tool_active_invocations",
    "Number of currently active tool invocations",
)


class ResourceMetrics:
    """Records resource usage to Prometheus metrics."""

    def record_usage(self, usage: ResourceUsage) -> None:
        """Record resource usage from a completed invocation."""
        tool = usage.tool_name

        # Update gauges
        TOOL_RESOURCE_MEMORY_MB.labels(tool_name=tool).set(usage.peak_memory_mb)
        TOOL_RESOURCE_CPU_SECONDS.labels(tool_name=tool).set(usage.cpu_time_seconds)
        TOOL_RESOURCE_WALL_TIME_SECONDS.labels(tool_name=tool).set(usage.wall_time_seconds)
        TOOL_RESOURCE_NETWORK_REQUESTS.labels(tool_name=tool).set(usage.network_requests)
        TOOL_RESOURCE_OUTPUT_SIZE_BYTES.labels(tool_name=tool).set(usage.output_size_bytes)

        # Update histograms
        TOOL_RESOURCE_WALL_TIME_HISTOGRAM.labels(tool_name=tool).observe(usage.wall_time_seconds)
        TOOL_RESOURCE_MEMORY_HISTOGRAM.labels(tool_name=tool).observe(usage.peak_memory_mb)

        # Record violations
        for violation in usage.violations:
            vtype = self._classify_violation(violation)
            TOOL_RESOURCE_VIOLATIONS.labels(
                tool_name=tool, violation_type=vtype
            ).inc()

        # Record kills
        if usage.killed:
            TOOL_RESOURCE_KILLS.labels(
                tool_name=tool, kill_reason=usage.kill_reason
            ).inc()

    def record_circuit_breaker_state(self, tool_name: str, state: str) -> None:
        """Update circuit breaker state metric."""
        state_map = {"closed": 0, "open": 1, "half_open": 2}
        TOOL_CIRCUIT_BREAKER_STATE.labels(tool_name=tool_name).set(
            state_map.get(state, -1)
        )

    def set_active_invocations(self, count: int) -> None:
        """Update active invocation count."""
        TOOL_ACTIVE_INVOCATIONS.set(count)

    @staticmethod
    def _classify_violation(violation_msg: str) -> str:
        """Classify a violation message into a type."""
        msg = violation_msg.lower()
        if "memory" in msg:
            return "memory"
        if "cpu" in msg:
            return "cpu"
        if "wall time" in msg or "timeout" in msg:
            return "wall_time"
        if "network" in msg:
            return "network"
        if "output" in msg:
            return "output_size"
        return "unknown"
```

### 8.2 Grafana Dashboard Panels

Add these panels to the existing Grafana dashboard (`monitoring/grafana-dashboard.json`):

```json
{
  "panels": [
    {
      "title": "Tool Resource Usage — Memory (MB)",
      "type": "timeseries",
      "targets": [
        {"expr": "tsar_tool_resource_memory_mb", "legendFormat": "{{tool_name}}"}
      ],
      "fieldConfig": {
        "defaults": {
          "thresholds": {
            "steps": [
              {"value": 0, "color": "green"},
              {"value": 256, "color": "yellow"},
              {"value": 512, "color": "red"}
            ]
          }
        }
      }
    },
    {
      "title": "Tool Resource Violations",
      "type": "stat",
      "targets": [
        {"expr": "sum(increase(tsar_tool_resource_violations_total[1h]))", "legendFormat": "Violations/hour"}
      ]
    },
    {
      "title": "Tool Resource Kills",
      "type": "stat",
      "targets": [
        {"expr": "sum(increase(tsar_tool_resource_kills_total[1h]))", "legendFormat": "Kills/hour"}
      ],
      "fieldConfig": {
        "defaults": {
          "thresholds": {
            "steps": [
              {"value": 0, "color": "green"},
              {"value": 1, "color": "red"}
            ]
          }
        }
      }
    },
    {
      "title": "Tool Execution Time Distribution (P95)",
      "type": "timeseries",
      "targets": [
        {"expr": "histogram_quantile(0.95, rate(tsar_tool_resource_wall_time_distribution_seconds_bucket[5m]))", "legendFormat": "{{tool_name}} P95"}
      ]
    },
    {
      "title": "Circuit Breaker States",
      "type": "table",
      "targets": [
        {"expr": "tsar_tool_circuit_breaker_state", "legendFormat": "{{tool_name}}"}
      ]
    },
    {
      "title": "Active Tool Invocations",
      "type": "gauge",
      "targets": [
        {"expr": "tsar_tool_active_invocations"}
      ],
      "fieldConfig": {
        "defaults": {
          "max": 10,
          "thresholds": {
            "steps": [
              {"value": 0, "color": "green"},
              {"value": 7, "color": "yellow"},
              {"value": 9, "color": "red"}
            ]
          }
        }
      }
    }
  ]
}
```

### 8.3 Alert Rules for Resource Limits

```yaml
# monitoring/alert_rules.yml (add to existing groups)

  - name: resource_alerts
    rules:
      - alert: ToolResourceViolationSpike
        expr: sum(increase(tsar_tool_resource_violations_total[5m])) > 5
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Resource violations spiking: {{ $value }} in 5 minutes"
          description: "Multiple tools exceeding resource limits. Check for misconfiguration."

      - alert: ToolResourceKill
        expr: increase(tsar_tool_resource_kills_total[5m]) > 0
        for: 0s
        labels:
          severity: critical
        annotations:
          summary: "Tool invocation killed for exceeding resource limits"
          description: "{{ $labels.tool_name }} killed (reason: {{ $labels.kill_reason }})"

      - alert: ToolCircuitBreakerOpen
        expr: tsar_tool_circuit_breaker_state == 1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Circuit breaker OPEN for {{ $labels.tool_name }}"
          description: "Tool is blocked due to repeated resource violations."

      - alert: HighConcurrentInvocations
        expr: tsar_tool_active_invocations > 8
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High concurrent tool invocations: {{ $value }}/10"
```

---

## 9. YAML Configuration Schema

### 9.1 Resource Limits Config File

```yaml
# config/resource_limits.yaml
# Resource limits configuration for TSAR tool invocations.
#
# This file is loaded by ToolResourcePolicy at startup.
# Changes require container restart (not hot-reloadable).

# ── Global defaults ──
# Applied to any tool that doesn't have a specific override.
global_default:
  max_memory_mb: 256
  max_cpu_seconds: 10.0
  max_wall_time_seconds: 30.0
  max_network_requests: 100
  max_file_size_mb: 50
  max_output_size_mb: 10

# ── Category defaults ──
# Applied to tools by category (inferred from tool name prefix).
category_defaults:
  exchange:
    max_memory_mb: 128
    max_cpu_seconds: 5.0
    max_wall_time_seconds: 15.0
    max_network_requests: 10
    max_file_size_mb: 10
    max_output_size_mb: 2
  analysis:
    max_memory_mb: 256
    max_cpu_seconds: 10.0
    max_wall_time_seconds: 30.0
    max_network_requests: 100
    max_file_size_mb: 50
    max_output_size_mb: 10
  data:
    max_memory_mb: 256
    max_cpu_seconds: 10.0
    max_wall_time_seconds: 30.0
    max_network_requests: 100
    max_file_size_mb: 50
    max_output_size_mb: 10
  risk:
    max_memory_mb: 128
    max_cpu_seconds: 5.0
    max_wall_time_seconds: 15.0
    max_network_requests: 0
    max_file_size_mb: 10
    max_output_size_mb: 2
  memory:
    max_memory_mb: 128
    max_cpu_seconds: 5.0
    max_wall_time_seconds: 15.0
    max_network_requests: 0
    max_file_size_mb: 10
    max_output_size_mb: 2
  execution:
    max_memory_mb: 256
    max_cpu_seconds: 15.0
    max_wall_time_seconds: 30.0
    max_network_requests: 200
    max_file_size_mb: 50
    max_output_size_mb: 10

# ── Per-tool overrides ──
# Specific limits for individual tools. Overrides category defaults.
tool_overrides:
  # Heavy compute tools
  calculate_volume_profile:
    max_memory_mb: 512
    max_cpu_seconds: 30.0
    max_wall_time_seconds: 60.0
    max_network_requests: 100
    max_file_size_mb: 50
    max_output_size_mb: 10

  get_correlation_matrix:
    max_memory_mb: 512
    max_cpu_seconds: 30.0
    max_wall_time_seconds: 60.0
    max_network_requests: 100
    max_file_size_mb: 50
    max_output_size_mb: 10

  detect_patterns:
    max_memory_mb: 256
    max_cpu_seconds: 15.0
    max_wall_time_seconds: 45.0
    max_network_requests: 100
    max_file_size_mb: 50
    max_output_size_mb: 10

  # Execution tools
  smart_order_router:
    max_memory_mb: 256
    max_cpu_seconds: 15.0
    max_wall_time_seconds: 30.0
    max_network_requests: 200
    max_file_size_mb: 50
    max_output_size_mb: 10

  twap_execute:
    max_memory_mb: 256
    max_cpu_seconds: 60.0
    max_wall_time_seconds: 3600.0
    max_network_requests: 1000
    max_file_size_mb: 50
    max_output_size_mb: 10

  # External data tools (higher latency tolerance)
  fetch_news:
    max_memory_mb: 256
    max_cpu_seconds: 10.0
    max_wall_time_seconds: 15.0
    max_network_requests: 50
    max_file_size_mb: 50
    max_output_size_mb: 10

  fetch_social_sentiment:
    max_memory_mb: 256
    max_cpu_seconds: 10.0
    max_wall_time_seconds: 15.0
    max_network_requests: 50
    max_file_size_mb: 50
    max_output_size_mb: 10

  fetch_onchain_data:
    max_memory_mb: 256
    max_cpu_seconds: 15.0
    max_wall_time_seconds: 20.0
    max_network_requests: 50
    max_file_size_mb: 50
    max_output_size_mb: 10

# ── Context-specific overrides ──
# Format: "context:tool_name" → limits
# These are the HIGHEST priority overrides.
context_overrides:
  # Live trading: tighter timeouts, fail fast
  "live_trading:get_price":
    max_memory_mb: 128
    max_cpu_seconds: 3.0
    max_wall_time_seconds: 10.0
    max_network_requests: 10
    max_file_size_mb: 10
    max_output_size_mb: 2

  "live_trading:place_order":
    max_memory_mb: 256
    max_cpu_seconds: 5.0
    max_wall_time_seconds: 15.0
    max_network_requests: 50
    max_file_size_mb: 50
    max_output_size_mb: 10

  "live_trading:check_position_limits":
    max_memory_mb: 128
    max_cpu_seconds: 2.0
    max_wall_time_seconds: 5.0
    max_network_requests: 0
    max_file_size_mb: 10
    max_output_size_mb: 2

  # Backtesting: generous resources for batch processing
  "backtesting:calculate_volume_profile":
    max_memory_mb: 1024
    max_cpu_seconds: 60.0
    max_wall_time_seconds: 120.0
    max_network_requests: 100
    max_file_size_mb: 200
    max_output_size_mb: 50

  "backtesting:get_correlation_matrix":
    max_memory_mb: 1024
    max_cpu_seconds: 60.0
    max_wall_time_seconds: 120.0
    max_network_requests: 100
    max_file_size_mb: 200
    max_output_size_mb: 50

# ── Enforcement settings ──
enforcement:
  enabled: true
  max_concurrent_invocations: 10
  monitor_interval_ms: 500
  grace_period_seconds: 5.0
  memory_tolerance_pct: 0.05   # 5% tolerance before killing

# ── Circuit breaker settings ──
circuit_breaker:
  failure_threshold: 3          # Open after 3 consecutive violations
  recovery_timeout_s: 60.0      # Wait 60s before half-open
  max_recovery_timeout_s: 3600.0
  backoff_multiplier: 2.0

# ── Execution timeout overrides ──
# These override the DEFAULT_TIMEOUTS in timeout.py
execution_timeouts:
  global_default: 30.0
  overrides:
    get_price: 5.0
    get_ohlcv: 8.0
    get_orderbook: 5.0
    place_order: 15.0
    cancel_order: 8.0
    get_positions: 8.0
    get_balance: 8.0
    get_funding_rate: 5.0
    calculate_rsi: 3.0
    calculate_macd: 3.0
    calculate_bollinger: 3.0
    calculate_atr: 3.0
    calculate_ema: 3.0
    calculate_volume_profile: 5.0
    detect_patterns: 5.0
    fetch_news: 15.0
    fetch_social_sentiment: 15.0
    fetch_onchain_data: 20.0
    fetch_macro_calendar: 15.0
    check_position_limits: 2.0
    calculate_position_size: 2.0
    get_portfolio_exposure: 3.0
    get_correlation_matrix: 8.0
    get_drawdown_stats: 3.0
    log_trade: 2.0
    search_trades: 3.0
    get_strategy_performance: 3.0
    get_lesson: 2.0
    update_regime_state: 1.0
    smart_order_router: 20.0
    calculate_slippage: 2.0
    twap_execute: 3600.0
    monitor_fills: 8.0
```

### 9.2 Config Schema Validation

```python
# tools/resources/config_schema.py
"""
Validation schema for resource_limits.yaml.
Uses jsonschema for validation at startup.
"""

RESOURCE_LIMITS_SCHEMA = {
    "type": "object",
    "required": ["global_default"],
    "properties": {
        "global_default": {"$ref": "#/definitions/resource_limit"},
        "category_defaults": {
            "type": "object",
            "additionalProperties": {"$ref": "#/definitions/resource_limit"},
        },
        "tool_overrides": {
            "type": "object",
            "additionalProperties": {"$ref": "#/definitions/resource_limit"},
        },
        "context_overrides": {
            "type": "object",
            "additionalProperties": {"$ref": "#/definitions/resource_limit"},
        },
        "enforcement": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "max_concurrent_invocations": {"type": "integer", "minimum": 1, "maximum": 100},
                "monitor_interval_ms": {"type": "integer", "minimum": 100, "maximum": 5000},
                "grace_period_seconds": {"type": "number", "minimum": 1, "maximum": 60},
                "memory_tolerance_pct": {"type": "number", "minimum": 0, "maximum": 0.5},
            },
        },
        "circuit_breaker": {
            "type": "object",
            "properties": {
                "failure_threshold": {"type": "integer", "minimum": 1, "maximum": 100},
                "recovery_timeout_s": {"type": "number", "minimum": 1},
                "max_recovery_timeout_s": {"type": "number", "minimum": 1},
                "backoff_multiplier": {"type": "number", "minimum": 1, "maximum": 10},
            },
        },
        "execution_timeouts": {
            "type": "object",
            "properties": {
                "global_default": {"type": "number", "minimum": 0.1},
                "overrides": {
                    "type": "object",
                    "additionalProperties": {"type": "number", "minimum": 0.1},
                },
            },
        },
    },
    "definitions": {
        "resource_limit": {
            "type": "object",
            "properties": {
                "max_memory_mb": {"type": "integer", "minimum": 1, "maximum": 8192},
                "max_cpu_seconds": {"type": "number", "minimum": 0.1, "maximum": 7200},
                "max_wall_time_seconds": {"type": "number", "minimum": 0.1, "maximum": 86400},
                "max_network_requests": {"type": "integer", "minimum": 0, "maximum": 100000},
                "max_file_size_mb": {"type": "integer", "minimum": 0, "maximum": 10240},
                "max_output_size_mb": {"type": "integer", "minimum": 0, "maximum": 1024},
            },
            "additionalProperties": False,
        },
    },
}
```

---

## 10. Integration with Existing Architecture

### 10.1 Alignment with Architecture Consolidation

This specification aligns with the canonical values from `ARCHITECTURE_CONSOLIDATION.md`:

| Consolidation Decision | Resource Limit Alignment |
|---|---|
| **Risk Guardian P0: -2% kill switch** | Risk tools get conservative limits (128MB, 5s CPU) to ensure they always respond fast |
| **Max 10 open positions** | `max_concurrent_invocations=10` matches position count — each position check can run in parallel |
| **Single tsar.db** | File I/O limits apply to SQLite writes; `max_file_size_mb=50` for memory tools |
| **Redis tsar:* prefix** | Network limits count Redis operations as network requests |
| **Docker 1GB RAM for agent** | Tool limits sum to well under 1GB (max 10 × 256MB = 2.56GB theoretical, but concurrent limit of 10 + memory pre-check prevents this) |
| **Port 8000 for FastAPI** | Resource metrics exposed on port 9100 (Prometheus scrape) |

### 10.2 Alignment with Tool Spec

| Tool Spec Value | Resource Limit Mapping |
|---|---|
| `ToolSchema.timeout_ms` | Maps to `max_wall_time_seconds` (converted: `timeout_ms / 1000`) |
| `ToolPermission` levels | Higher permission → tighter resource limits (live trading = fail fast) |
| `ApprovalPolicy.ALWAYS_CONFIRM` | Approval wait time excluded from resource timeout |
| `CircuitBreaker` in `client.py` | Complemented by `ResourceCircuitBreaker` (API failures vs resource failures tracked separately) |
| `BaseTool.execute()` return type | `ToolResult.metadata["resource_usage"]` appended by enforcer |

### 10.3 Initialization Flow

```python
# tools/resources/__init__.py
"""
Resource management package initialization.

Called during agent startup (tools/__init__.py or main.py).
"""

from .limits import ResourceLimit, LIMIT_CONSERVATIVE, LIMIT_STANDARD, LIMIT_EXPANSIVE, LIMIT_HEAVY
from .policy import ToolResourcePolicy, TradingContext
from .enforcer import ResourceEnforcer, ResourceViolationError, ResourceUsage
from .circuit_breaker import ResourceCircuitBreaker, ResourceCircuitBreakerManager
from .timeout import ExecutionTimeout, StreamingTimeout
from .metrics import ResourceMetrics
from .config_schema import RESOURCE_LIMITS_SCHEMA


def create_enforcer(config_path: str = "config/resource_limits.yaml") -> ResourceEnforcer:
    """
    Factory function to create a fully configured ResourceEnforcer.

    Called once at agent startup. The returned enforcer is injected
    into the ToolRegistry.
    """
    import yaml
    from jsonschema import validate, ValidationError

    # Load config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Validate config
    try:
        validate(instance=config, schema=RESOURCE_LIMITS_SCHEMA)
    except ValidationError as e:
        raise ValueError(f"Invalid resource_limits.yaml: {e.message}")

    # Create components
    metrics = ResourceMetrics()
    policy = ToolResourcePolicy(config=config)
    enforcer = ResourceEnforcer(policy=policy, metrics=metrics)

    # Log summary
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"ResourceEnforcer initialized with config from {config_path}")
    logger.debug(f"Policy summary: {policy.summary()}")

    return enforcer
```

### 10.4 File Structure

```
tools/
├── resources/
│   ├── __init__.py           # Package init, create_enforcer() factory
│   ├── limits.py             # ResourceLimit dataclass, pre-defined profiles
│   ├── policy.py             # ToolResourcePolicy, TradingContext
│   ├── enforcer.py           # ResourceEnforcer middleware
│   ├── circuit_breaker.py    # ResourceCircuitBreaker
│   ├── timeout.py            # ExecutionTimeout, StreamingTimeout
│   ├── metrics.py            # Prometheus metrics definitions
│   └── config_schema.py      # JSON Schema for config validation
├── base.py                   # BaseTool (unchanged)
├── registry.py               # ToolRegistry (updated: enforcer integration)
├── exchange/
│   └── client.py             # ExchangeClientManager (updated: network tracking)
└── ...

config/
├── resource_limits.yaml      # Resource limits configuration
└── ...

monitoring/
├── alert_rules.yml           # (updated: resource_alerts group)
└── grafana-dashboard.json    # (updated: resource panels)
```

---

## 11. Implementation Checklist

### Phase 1: Core (Week 1)

- [ ] Create `tools/resources/` package structure
- [ ] Implement `ResourceLimit` dataclass with validation
- [ ] Implement `ToolResourcePolicy` with config loading
- [ ] Implement `ResourceEnforcer` with pre/during/post enforcement
- [ ] Add wall-clock timeout with 80% warning escalation
- [ ] Write unit tests for all resource limit classes
- [ ] Write integration test: tool invocation → enforcer → kill on limit

### Phase 2: Integration (Week 2)

- [ ] Update `ToolRegistry.call_tool()` to use enforcer
- [ ] Update `ExchangeClientManager` with network request tracking
- [ ] Implement `ResourceCircuitBreaker` and manager
- [ ] Create `config/resource_limits.yaml` with all tool limits
- [ ] Add `ResourceViolationError` to standard error codes in `tools-spec.md`
- [ ] Write integration test: circuit breaker opens after N violations

### Phase 3: Monitoring (Week 3)

- [ ] Implement `ResourceMetrics` with all Prometheus gauges/counters/histograms
- [ ] Update `monitoring/alert_rules.yml` with resource alerts
- [ ] Update Grafana dashboard with resource panels
- [ ] Deploy cAdvisor in docker-compose.prod.yml
- [ ] Verify metrics appear in Prometheus/Grafana

### Phase 4: Hardening (Week 4)

- [ ] Stress test: simulate 10 concurrent tool invocations
- [ ] Stress test: simulate memory spike → verify kill
- [ ] Stress test: simulate circuit breaker cascade
- [ ] Document operational runbook (how to reset circuit breakers, adjust limits)
- [ ] Review all limits against actual tool profiling data
- [ ] Final review: alignment with ARCHITECTURE_CONSOLIDATION.md

---

## Appendix A: Error Code Addition

Add to the standard error codes in `trading-super-agent-tools-spec.md`:

| Code | Category | Retryable | Description |
|---|---|---|---|
| `RESOURCE_LIMIT_EXCEEDED` | Resource | No | Tool invocation exceeded resource limits |
| `RESOURCE_CIRCUIT_BREAKER_OPEN` | Resource | Yes (after cooldown) | Circuit breaker open due to repeated violations |
| `RESOURCE_TIMEOUT` | Resource | No | Execution timeout exceeded |
| `RESOURCE_INSUFFICIENT_MEMORY` | Resource | Yes (when memory frees) | System memory too low for invocation |

## Appendix B: Limit Tuning Guide

When adding a new tool, determine its resource limits by:

1. **Profile in dev** — Run the tool with typical inputs, measure memory/CPU/time
2. **Apply 2x safety margin** — Set limit to 2× the observed peak
3. **Set conservative timeout** — Use 3× the typical execution time
4. **Monitor in staging** — Watch Grafana for the first 48 hours
5. **Tighten if stable** — If never above 50% of limit, consider reducing
6. **Document rationale** — Add a comment in `resource_limits.yaml` explaining the choice

---

*Specification completed: 2026-07-24 04:30 GMT+8*  
*Supersedes: No prior resource limit specification existed.*
