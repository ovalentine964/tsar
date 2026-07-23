"""
ResourceEnforcer — Middleware enforcing per-tool resource limits.

Every tool invocation passes through the enforcer before execution.
Checks: memory, CPU, wall time, concurrent invocations, rate limits.

Includes a circuit breaker that trips when too many violations occur
in a time window, temporarily blocking the offending tool.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Any

from src.resources.profiles import get_limits, DEFAULT_LIMITS

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Per-tool circuit breaker.

    Trips (opens) when violation count exceeds threshold within the
    time window. After cooldown, enters half-open state allowing
    a single probe request.

    States:
        CLOSED  — Normal operation, violations counted.
        OPEN    — Tool blocked, all requests rejected.
        HALF_OPEN — One probe allowed; success closes, failure re-opens.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        window_seconds: float = 60.0,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds

        self.state: str = self.CLOSED
        self._failures: deque[float] = deque()
        self._opened_at: float = 0.0

    def record_failure(self) -> None:
        """Record a resource violation."""
        now = time.monotonic()
        self._failures.append(now)

        # Prune old failures outside the window
        cutoff = now - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

        if self.state == self.HALF_OPEN:
            # Probe failed — re-open
            self.state = self.OPEN
            self._opened_at = now
            logger.warning("Circuit breaker re-opened (probe failed)")
        elif len(self._failures) >= self.failure_threshold:
            self.state = self.OPEN
            self._opened_at = now
            logger.warning(
                f"Circuit breaker tripped: {len(self._failures)} failures "
                f"in {self.window_seconds}s"
            )

    def record_success(self) -> None:
        """Record a successful execution."""
        if self.state == self.HALF_OPEN:
            self.state = self.CLOSED
            self._failures.clear()
            logger.info("Circuit breaker closed (probe succeeded)")

    def allow_request(self) -> bool:
        """Check if a request is allowed through the breaker.

        Returns:
            True if request should proceed, False if blocked.
        """
        if self.state == self.CLOSED:
            return True

        if self.state == self.OPEN:
            now = time.monotonic()
            if now - self._opened_at >= self.cooldown_seconds:
                self.state = self.HALF_OPEN
                logger.info("Circuit breaker half-open (cooldown expired)")
                return True  # Allow probe
            return False

        if self.state == self.HALF_OPEN:
            return True  # Allow probe

        return True

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self.state = self.CLOSED
        self._failures.clear()
        self._opened_at = 0.0


class ResourceEnforcer:
    """Enforce resource limits on tool invocations.

    Features:
    - Per-tool category limits (from resource profiles)
    - Concurrent invocation limits
    - Wall time enforcement
    - Rate limiting (calls per minute)
    - Circuit breaker per tool (trips on repeated violations)
    - Context-aware limits (live trading vs backtesting)

    Usage::

        enforcer = ResourceEnforcer(context="live_trading")
        if await enforcer.pre_check("exchange", "place_order"):
            try:
                result = await execute_tool(...)
                await enforcer.post_execution("exchange", "place_order", elapsed_ms=45.0)
            except Exception:
                enforcer.record_violation("exchange", "place_order")
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        context: str = "paper_trading",
    ) -> None:
        self._config = config or {}
        self._context = context
        self._active: int = 0
        self._active_by_tool: dict[str, int] = defaultdict(int)

        # Rate limiting: tool -> deque of timestamps
        self._call_timestamps: dict[str, deque[float]] = defaultdict(lambda: deque())

        # Violation tracking
        self._violations: dict[str, int] = defaultdict(int)
        self._violation_details: list[dict[str, Any]] = []

        # Circuit breakers per tool
        self._breakers: dict[str, CircuitBreaker] = {}

        # Global limits
        self._max_concurrent = self._config.get("max_concurrent", DEFAULT_LIMITS["max_concurrent"])

    # ── Pre-Check ────────────────────────────────────────────

    async def pre_check(self, tool_category: str, tool_name: str = "") -> bool:
        """Check if tool invocation is allowed.

        Validates:
        1. Circuit breaker state
        2. Global concurrency limit
        3. Per-tool concurrency limit
        4. Rate limit (calls per minute)

        Args:
            tool_category: Tool category (exchange, analysis, risk, etc.)
            tool_name: Specific tool name for logging.

        Returns:
            True if allowed, False if resource limit exceeded.
        """
        full_name = f"{tool_category}:{tool_name}" if tool_name else tool_category

        # 1. Circuit breaker
        breaker = self._get_breaker(full_name)
        if not breaker.allow_request():
            logger.warning(f"Circuit breaker OPEN for {full_name}")
            self._record_violation(full_name, "circuit_breaker_open")
            return False

        # 2. Global concurrency
        if self._active >= self._max_concurrent:
            logger.warning(f"Global concurrent limit ({self._max_concurrent}) reached")
            self._record_violation(full_name, "global_concurrent_limit")
            return False

        # 3. Per-tool concurrency
        limits = get_limits(tool_category, self._context)
        tool_max_concurrent = limits.get("max_concurrent", self._max_concurrent)
        if self._active_by_tool[full_name] >= tool_max_concurrent:
            logger.warning(f"Tool concurrent limit ({tool_max_concurrent}) for {full_name}")
            self._record_violation(full_name, "tool_concurrent_limit")
            return False

        # 4. Rate limit
        max_calls_per_min = limits.get("max_calls_per_min", DEFAULT_LIMITS["max_calls_per_min"])
        if not self._check_rate_limit(full_name, max_calls_per_min):
            logger.warning(f"Rate limit ({max_calls_per_min}/min) for {full_name}")
            self._record_violation(full_name, "rate_limit")
            return False

        # All checks passed — record the invocation
        self._active += 1
        self._active_by_tool[full_name] += 1
        self._record_call(full_name)
        return True

    # ── Post-Execution ───────────────────────────────────────

    async def post_execution(
        self,
        tool_category: str,
        tool_name: str = "",
        elapsed_ms: float = 0.0,
        memory_mb: float = 0.0,
    ) -> None:
        """Record tool execution metrics and check for violations.

        Args:
            tool_category: Tool category.
            tool_name: Specific tool name.
            elapsed_ms: Wall time in milliseconds.
            memory_mb: Peak memory usage in megabytes.
        """
        full_name = f"{tool_category}:{tool_name}" if tool_name else tool_category

        # Decrement active counts
        self._active = max(0, self._active - 1)
        self._active_by_tool[full_name] = max(0, self._active_by_tool[full_name] - 1)

        limits = get_limits(tool_category, self._context)

        # Check wall time
        max_wall_ms = limits.get("max_wall_time_s", DEFAULT_LIMITS["max_wall_time_s"]) * 1000
        if elapsed_ms > max_wall_ms:
            logger.warning(
                f"Wall time violation: {full_name} took {elapsed_ms:.0f}ms "
                f"(max {max_wall_ms:.0f}ms)"
            )
            self._record_violation(full_name, "wall_time_exceeded", elapsed_ms=elapsed_ms)
            self._get_breaker(full_name).record_failure()
        else:
            self._get_breaker(full_name).record_success()

        # Check memory
        max_memory = limits.get("max_memory_mb", DEFAULT_LIMITS["max_memory_mb"])
        if memory_mb > max_memory:
            logger.warning(
                f"Memory violation: {full_name} used {memory_mb:.0f}MB "
                f"(max {max_memory:.0f}MB)"
            )
            self._record_violation(full_name, "memory_exceeded", memory_mb=memory_mb)

    # ── Manual Violation Recording ───────────────────────────

    def record_violation(self, tool_category: str, tool_name: str = "", reason: str = "unknown") -> None:
        """Manually record a violation (e.g. from catch blocks).

        Args:
            tool_category: Tool category.
            tool_name: Specific tool name.
            reason: Violation reason.
        """
        full_name = f"{tool_category}:{tool_name}" if tool_name else tool_category
        self._record_violation(full_name, reason)
        self._get_breaker(full_name).record_failure()

    # ── Rate Limiting ────────────────────────────────────────

    def _check_rate_limit(self, tool_name: str, max_per_minute: int) -> bool:
        """Check if tool is within its rate limit."""
        now = time.monotonic()
        timestamps = self._call_timestamps[tool_name]

        # Prune entries older than 60 seconds
        cutoff = now - 60.0
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        return len(timestamps) < max_per_minute

    def _record_call(self, tool_name: str) -> None:
        """Record a call timestamp for rate limiting."""
        self._call_timestamps[tool_name].append(time.monotonic())

    # ── Violation Tracking ───────────────────────────────────

    def _record_violation(
        self,
        tool_name: str,
        reason: str,
        elapsed_ms: float = 0.0,
        memory_mb: float = 0.0,
    ) -> None:
        """Record a resource violation."""
        self._violations[tool_name] += 1
        detail = {
            "tool": tool_name,
            "reason": reason,
            "timestamp": time.time(),
        }
        if elapsed_ms > 0:
            detail["elapsed_ms"] = elapsed_ms
        if memory_mb > 0:
            detail["memory_mb"] = memory_mb
        self._violation_details.append(detail)
        # Keep last 1000 details
        if len(self._violation_details) > 1000:
            self._violation_details = self._violation_details[-1000:]

    # ── Circuit Breaker ──────────────────────────────────────

    def _get_breaker(self, tool_name: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a tool."""
        if tool_name not in self._breakers:
            self._breakers[tool_name] = CircuitBreaker(
                failure_threshold=self._config.get("breaker_threshold", 5),
                window_seconds=self._config.get("breaker_window_s", 60.0),
                cooldown_seconds=self._config.get("breaker_cooldown_s", 30.0),
            )
        return self._breakers[tool_name]

    def get_breaker_state(self, tool_name: str) -> str:
        """Get the circuit breaker state for a tool."""
        return self._get_breaker(tool_name).state

    def reset_breaker(self, tool_name: str) -> None:
        """Manually reset a circuit breaker."""
        self._get_breaker(tool_name).reset()

    # ── Reporting ────────────────────────────────────────────

    def get_violations(self) -> dict[str, int]:
        """Get violation counts by tool."""
        return dict(self._violations)

    def get_violation_details(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent violation details."""
        return self._violation_details[-limit:]

    def get_active_count(self) -> int:
        """Get current active invocation count."""
        return self._active

    def get_status(self) -> dict[str, Any]:
        """Get full enforcer status."""
        breaker_states = {
            name: breaker.state for name, breaker in self._breakers.items()
        }
        return {
            "active_invocations": self._active,
            "max_concurrent": self._max_concurrent,
            "context": self._context,
            "total_violations": sum(self._violations.values()),
            "violations_by_tool": dict(self._violations),
            "circuit_breakers": breaker_states,
        }
