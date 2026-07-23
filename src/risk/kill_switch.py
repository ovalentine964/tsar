"""
Kill Switch — Dual-write emergency halt (Redis + file).

The single most critical piece of state in the system.
Must be readable even if Redis is down.

Read path: Redis first → file fallback → FAIL-SAFE (active on error)
External kill: echo '{"active":true,"reason":"external"}' > $TSAR_KILL_SWITCH_PATH

Trigger conditions:
  - Daily loss ≥ -2% of capital
  - Max drawdown ≥ 5% from HWM
  - Exchange API auth failure
  - Manual trigger via Telegram /stop
  - External file write

Actions on activation:
  1. Write state to file (PRIMARY — survives Redis failure)
  2. Write state to Redis (SECONDARY)
  3. Cancel ALL open orders (via callback)
  4. Close ALL positions — market orders (via callback)
  5. Set system to HALTED state
  6. Send notification alerts (via callback)
  7. Log to immutable audit log

Deactivation requires manual trigger (Telegram /start).
After deactivation, Gated Recovery Protocol applies (see recovery config).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Configurable paths — env overrides config
KILL_SWITCH_FILE = os.environ.get("TSAR_KILL_SWITCH_PATH", "./data/kill_switch")
KILL_SWITCH_REDIS_KEY = "tsar:risk:kill_switch"


class KillSwitch:
    """Dual-write kill switch (Redis + file).

    Architecture:
      - File is PRIMARY (survives Redis failure, supports external kill)
      - Redis is SECONDARY (faster reads in healthy system)
      - Read path: Redis → file → FAIL-SAFE (assume active on error)
      - Write path: file first, then Redis (file is always authoritative)

    Supports optional callbacks for order cancellation, position
    flattening, and notifications.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        file_path: str | None = None,
        redis_key: str | None = None,
        on_activate: Callable[[str], Awaitable[None]] | None = None,
        on_deactivate: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the kill switch.

        Args:
            redis_client: Async Redis client (optional, can be None).
            file_path: Override file path (default: env or ./data/kill_switch).
            redis_key: Override Redis key (default: tsar:risk:kill_switch).
            on_activate: Async callback invoked on activation with reason.
            on_deactivate: Async callback invoked on deactivation.
        """
        self._redis = redis_client
        self._file_path = Path(file_path or KILL_SWITCH_FILE)
        self._redis_key = redis_key or KILL_SWITCH_REDIS_KEY
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate

        # Ensure parent directory exists
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def activate(self, reason: str = "manual") -> None:
        """Activate the kill switch — halt all trading immediately.

        Write order: file first (primary), then Redis (secondary).
        Invokes the on_activate callback after writes complete.

        Args:
            reason: Human-readable reason for activation (logged immutably).
        """
        payload = self._build_payload(True, reason)

        # 1. Write to file (PRIMARY — survives Redis failure)
        self._write_file(payload)
        logger.critical(f"KILL SWITCH ACTIVATED (file): {reason}")

        # 2. Write to Redis (SECONDARY)
        await self._write_redis(payload)

        # 3. Invoke activation callback (cancel orders, flatten, notify)
        if self._on_activate:
            try:
                await self._on_activate(reason)
            except Exception as e:
                logger.error(f"Kill switch activation callback failed: {e}")

    async def deactivate(self) -> None:
        """Deactivate the kill switch — resume trading.

        Clears state in both file and Redis.
        Requires manual trigger — this is intentional.

        After deactivation, the Gated Recovery Protocol applies:
        position sizes ramp up gradually (10% → 25% → 50% → 100%)
        over 24-72 hours depending on the circuit breaker level.
        """
        # 1. Remove file
        self._remove_file()

        # 2. Remove Redis key
        await self._remove_redis()

        logger.warning("KILL SWITCH DEACTIVATED — Gated Recovery Protocol engaged")

        # 3. Invoke deactivation callback
        if self._on_deactivate:
            try:
                await self._on_deactivate()
            except Exception as e:
                logger.error(f"Kill switch deactivation callback failed: {e}")

    async def is_active(self) -> bool:
        """Check if kill switch is currently active.

        Read path:
          1. Redis first (fast path in healthy system)
          2. File fallback (survives Redis failure)
          3. FAIL-SAFE: if both unreadable, assume ACTIVE

        Returns:
            True if kill switch is active (trading halted).
        """
        # Try Redis first
        redis_result = await self._read_redis()
        if redis_result is not None:
            return redis_result

        # Fallback to file
        file_result = self._read_file()
        if file_result is not None:
            return file_result

        # FAIL-SAFE: if we can't read either, assume active
        logger.error(
            "Kill switch state unreadable from both Redis and file — "
            "FAIL-SAFE: assuming ACTIVE"
        )
        return True

    async def get_status(self) -> dict[str, Any]:
        """Get full kill switch status including metadata.

        Returns:
            Dict with 'active', 'reason', 'activated_at', 'activated_at_human'.
        """
        # Try Redis first for full payload
        if self._redis:
            try:
                data = await self._redis.get(self._redis_key)
                if data:
                    return json.loads(data)
            except Exception:
                pass

        # Fallback to file
        if self._file_path.exists():
            try:
                return json.loads(self._file_path.read_text())
            except Exception:
                pass

        return {
            "active": True,  # FAIL-SAFE
            "reason": "unknown — state unreadable",
            "activated_at": 0,
            "activated_at_human": "UNKNOWN",
        }

    # ------------------------------------------------------------------
    # Internal: File operations
    # ------------------------------------------------------------------

    def _write_file(self, payload: dict[str, Any]) -> None:
        """Write kill switch state to file (primary store)."""
        try:
            self._file_path.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            logger.critical(f"FAILED to write kill switch file: {e}")
            # Try alternate location as last resort
            alt_path = Path("/tmp/tsar_kill_switch_emergency")
            try:
                alt_path.write_text(json.dumps(payload, indent=2))
                logger.critical(f"Emergency kill switch written to {alt_path}")
            except Exception as e2:
                logger.critical(f"EMERGENCY WRITE ALSO FAILED: {e2}")

    def _read_file(self) -> bool | None:
        """Read kill switch state from file. Returns None if unavailable."""
        if not self._file_path.exists():
            return None
        try:
            payload = json.loads(self._file_path.read_text())
            return payload.get("active", False)
        except Exception:
            # File exists but unreadable — FAIL-SAFE
            logger.error("Kill switch file exists but is unreadable — assuming ACTIVE")
            return True

    def _remove_file(self) -> None:
        """Remove the kill switch file."""
        try:
            if self._file_path.exists():
                self._file_path.unlink()
                logger.info(f"Kill switch file removed: {self._file_path}")
        except Exception as e:
            logger.error(f"Failed to remove kill switch file: {e}")

    # ------------------------------------------------------------------
    # Internal: Redis operations
    # ------------------------------------------------------------------

    async def _write_redis(self, payload: dict[str, Any]) -> None:
        """Write kill switch state to Redis (secondary store)."""
        if not self._redis:
            return
        try:
            await self._redis.set(self._redis_key, json.dumps(payload))
            logger.info("Kill switch written to Redis")
        except Exception as e:
            logger.error(f"Failed to write kill switch to Redis: {e}")

    async def _read_redis(self) -> bool | None:
        """Read kill switch state from Redis. Returns None if unavailable."""
        if not self._redis:
            return None
        try:
            data = await self._redis.get(self._redis_key)
            if data:
                payload = json.loads(data)
                return payload.get("active", False)
            return None
        except Exception:
            logger.warning("Redis unavailable for kill switch read")
            return None

    async def _remove_redis(self) -> None:
        """Remove the kill switch key from Redis."""
        if not self._redis:
            return
        try:
            await self._redis.delete(self._redis_key)
            logger.info("Kill switch removed from Redis")
        except Exception as e:
            logger.error(f"Failed to remove kill switch from Redis: {e}")

    # ------------------------------------------------------------------
    # Internal: Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_payload(active: bool, reason: str) -> dict[str, Any]:
        """Build the kill switch state payload."""
        return {
            "active": active,
            "reason": reason,
            "activated_at": time.time(),
            "activated_at_human": time.strftime(
                "%Y-%m-%d %H:%M:%S UTC", time.gmtime()
            ),
        }
