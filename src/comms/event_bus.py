"""TSAR Event Bus — CloudEvents with Redis Streams persistence and DLQ.

Upgraded from the simple in-process bus to support:
- Redis Streams persistence (via XADD/XREAD)
- Dead letter queue for events that fail processing
- In-memory fallback for development/testing (backward-compatible)
- Consumer group support for scalable event processing

Usage::

    # In-memory (Day1 / testing) — backward-compatible
    bus = EventBus()
    bus.subscribe("tsar.signal.detected.v1", my_handler)
    await bus.publish("tsar.signal.detected.v1", {"symbol": "BTC/USDT"})

    # Redis-backed (production)
    bus = EventBus(redis_client=redis)
    bus.subscribe("tsar.signal.detected.v1", my_handler, group="risk_agent")
    await bus.publish("tsar.signal.detected.v1", {"symbol": "BTC/USDT"})

    # Check DLQ
    dlq_events = await bus.get_dlq_events(limit=10)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from src.comms.events import CloudEvent, create_event, from_redis_fields, to_redis_fields

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DLQ Entry
# ═══════════════════════════════════════════════════════════════


class DLQEntry:
    """A dead-letter-queued event with failure metadata."""

    __slots__ = (
        "event_type",
        "data",
        "error",
        "error_type",
        "retry_count",
        "first_failed_at",
        "last_failed_at",
        "source",
    )

    def __init__(
        self,
        event_type: str,
        data: dict[str, Any],
        error: str,
        error_type: str = "UnknownError",
        retry_count: int = 0,
        source: str = "",
    ) -> None:
        self.event_type = event_type
        self.data = data
        self.error = error
        self.error_type = error_type
        self.retry_count = retry_count
        self.source = source
        now = datetime.now(UTC).isoformat()
        self.first_failed_at = now
        self.last_failed_at = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "data": self.data,
            "error": self.error,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
            "source": self.source,
            "first_failed_at": self.first_failed_at,
            "last_failed_at": self.last_failed_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DLQEntry:
        entry = cls(
            event_type=d.get("event_type", ""),
            data=d.get("data", {}),
            error=d.get("error", ""),
            error_type=d.get("error_type", "UnknownError"),
            retry_count=d.get("retry_count", 0),
            source=d.get("source", ""),
        )
        entry.first_failed_at = d.get("first_failed_at", entry.first_failed_at)
        entry.last_failed_at = d.get("last_failed_at", entry.last_failed_at)
        return entry


# ═══════════════════════════════════════════════════════════════
# EventBus (Unified: Redis Streams + In-Memory fallback)
# ═══════════════════════════════════════════════════════════════

# Max retries before moving to DLQ
_MAX_RETRIES = 3

# DLQ stream name
_DLQ_STREAM = "tsar:stream:dlq"

# In-memory DLQ max size
_DLQ_MAX_IN_MEMORY = 1000


class EventBus:
    """CloudEvents bus with Redis Streams persistence and dead letter queue.

    Backward-compatible: when no redis_client is provided, operates as
    a simple in-process event bus (original behavior).

    When redis_client is provided, events are persisted to Redis Streams
    and failed events are moved to a dead letter queue after max retries.

    Args:
        redis_client: Optional async Redis client for persistence.
        stream_prefix: Prefix for Redis stream keys.
        max_retries: Max retry attempts before DLQ.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        stream_prefix: str = "tsar:stream:",
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._redis = redis_client
        self._prefix = stream_prefix
        self._max_retries = max_retries
        self._handlers: dict[str, list[Any]] = defaultdict(list)

        # In-memory DLQ (used in both modes for fast access)
        self._dlq: list[DLQEntry] = []

        # Per-event retry counters (keyed by event id)
        self._retry_counts: dict[str, int] = {}

        # Running state for consumer loops
        self._running = False
        self._consumer_tasks: list[asyncio.Task[None]] = []

        if self._redis is not None:
            logger.info("EventBus initialized with Redis Streams persistence")
        else:
            logger.info("EventBus initialized with in-memory backend")

    # ── Subscribe ────────────────────────────────────────────

    def subscribe(self, event_type: str, handler: Any) -> None:
        """Subscribe a handler to an event type.

        Args:
            event_type: CloudEvents type string (e.g. "tsar.signal.detected.v1").
            handler: Sync or async callable that receives event data dict.
        """
        self._handlers[event_type].append(handler)

    # ── Publish ──────────────────────────────────────────────

    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        """Publish an event to the bus.

        Creates a CloudEvent envelope, persists to Redis (if available),
        and dispatches to in-process handlers.

        Args:
            event_type: CloudEvents type string.
            data: Event payload.

        Returns:
            Event ID (ULID or Redis stream ID).
        """
        event = create_event(
            source="tsar:event_bus",
            event_type=event_type,
            data=data,
        )

        event_id = event.id

        # Persist to Redis Streams if available
        if self._redis is not None:
            try:
                stream_key = f"{self._prefix}{event_type}"
                fields = to_redis_fields(event)
                redis_id = await self._redis.xadd(stream_key, fields)
                event_id = str(redis_id)
                logger.debug("Persisted event %s to Redis stream %s", event_id, stream_key)
            except Exception as exc:
                logger.error("Failed to persist event to Redis: %s", exc)
                # Fall through to in-memory dispatch even if persistence fails

        # Dispatch to in-process handlers
        await self._dispatch(event_type, data, event_id)

        return event_id

    # ── Dispatch ─────────────────────────────────────────────

    async def _dispatch(
        self,
        event_type: str,
        data: dict[str, Any],
        event_id: str,
    ) -> None:
        """Dispatch an event to all registered handlers with DLQ on failure."""
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
                # Reset retry count on success
                self._retry_counts.pop(event_id, None)
            except Exception as exc:
                await self._handle_failure(event_type, data, exc, event_id)

    async def _handle_failure(
        self,
        event_type: str,
        data: dict[str, Any],
        error: Exception,
        event_id: str,
    ) -> None:
        """Handle a failed event — retry or move to DLQ."""
        retry_count = self._retry_counts.get(event_id, 0) + 1
        self._retry_counts[event_id] = retry_count

        error_type = type(error).__name__
        error_msg = str(error)

        logger.warning(
            "Event handler error [%s] (attempt %d/%d): %s: %s",
            event_type,
            retry_count,
            self._max_retries,
            error_type,
            error_msg,
        )

        if retry_count >= self._max_retries:
            # Move to DLQ
            dlq_entry = DLQEntry(
                event_type=event_type,
                data=data,
                error=error_msg,
                error_type=error_type,
                retry_count=retry_count,
            )
            await self._add_to_dlq(dlq_entry)
            self._retry_counts.pop(event_id, None)
            logger.error(
                "Event moved to DLQ after %d retries: %s — %s: %s",
                retry_count,
                event_type,
                error_type,
                error_msg,
            )
        else:
            # Retry with exponential backoff
            backoff = min(2 ** retry_count, 30)
            logger.info("Retrying event %s in %ds", event_type, backoff)
            await asyncio.sleep(backoff)
            await self._dispatch(event_type, data, event_id)

    # ── Dead Letter Queue ────────────────────────────────────

    async def _add_to_dlq(self, entry: DLQEntry) -> None:
        """Add an event to the dead letter queue.

        Persists to Redis DLQ stream if available, always stores in-memory.
        """
        # In-memory DLQ
        self._dlq.append(entry)
        if len(self._dlq) > _DLQ_MAX_IN_MEMORY:
            self._dlq = self._dlq[-_DLQ_MAX_IN_MEMORY:]

        # Redis DLQ stream
        if self._redis is not None:
            try:
                fields = {
                    "event_type": entry.event_type,
                    "data": json.dumps(entry.data),
                    "error": entry.error,
                    "error_type": entry.error_type,
                    "retry_count": str(entry.retry_count),
                    "first_failed_at": entry.first_failed_at,
                    "last_failed_at": entry.last_failed_at,
                }
                await self._redis.xadd(_DLQ_STREAM, fields)
            except Exception as exc:
                logger.error("Failed to persist DLQ entry to Redis: %s", exc)

    async def get_dlq_events(self, limit: int = 50) -> list[DLQEntry]:
        """Retrieve events from the dead letter queue.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of DLQEntry objects, most recent first.
        """
        # Try Redis first
        if self._redis is not None:
            try:
                messages = await self._redis.xrevrange(
                    _DLQ_STREAM, count=limit
                )
                if messages:
                    entries = []
                    for _msg_id, fields in messages:
                        d = {
                            k.decode() if isinstance(k, bytes) else k:
                            v.decode() if isinstance(v, bytes) else v
                            for k, v in fields.items()
                        }
                        d["data"] = json.loads(d.get("data", "{}"))
                        d["retry_count"] = int(d.get("retry_count", 0))
                        entries.append(DLQEntry.from_dict(d))
                    return entries
            except Exception as exc:
                logger.warning("Failed to read DLQ from Redis: %s", exc)

        # Fallback to in-memory DLQ
        return list(reversed(self._dlq[-limit:]))

    async def retry_dlq_event(self, entry: DLQEntry) -> bool:
        """Retry a DLQ event by re-publishing it.

        Args:
            entry: The DLQEntry to retry.

        Returns:
            True if the retry succeeded, False otherwise.
        """
        try:
            await self._dispatch(entry.event_type, entry.data, str(uuid.uuid4()))
            logger.info("DLQ retry succeeded for %s", entry.event_type)
            return True
        except Exception as exc:
            logger.error("DLQ retry failed for %s: %s", entry.event_type, exc)
            return False

    def get_dlq_count(self) -> int:
        """Get the current in-memory DLQ count."""
        return len(self._dlq)

    # ── Consumer Group Support (Redis only) ──────────────────

    async def start_consumer_group(
        self,
        event_type: str,
        group: str,
        consumer: str,
        handler: Any,
        count: int = 10,
        block_ms: int = 5000,
    ) -> asyncio.Task[None]:
        """Start a background consumer group on a Redis stream.

        Only works when redis_client is provided. Falls back to
        in-process subscription otherwise.

        Args:
            event_type: Event type / stream name.
            group: Consumer group name.
            consumer: Consumer name within the group.
            handler: Async callback for each event.
            count: Max messages per batch.
            block_ms: Block timeout in ms.

        Returns:
            The background asyncio Task.
        """
        if self._redis is None:
            # Fallback: just subscribe in-process
            self.subscribe(event_type, handler)
            logger.info("In-memory consumer subscribed to %s", event_type)
            # Return a no-op task
            async def _noop() -> None:
                while True:
                    await asyncio.sleep(3600)
            return asyncio.create_task(_noop())

        task = asyncio.create_task(
            self._consume_redis_stream(
                event_type, group, consumer, handler, count, block_ms
            ),
            name=f"consumer-{event_type}-{consumer}",
        )
        self._consumer_tasks.append(task)
        return task

    async def _consume_redis_stream(
        self,
        event_type: str,
        group: str,
        consumer: str,
        handler: Any,
        count: int,
        block_ms: int,
    ) -> None:
        """Consume from a Redis stream with consumer group."""
        stream_key = f"{self._prefix}{event_type}"

        # Create consumer group
        try:
            await self._redis.xgroup_create(stream_key, group, id="0", mkstream=True)
        except Exception:
            pass  # Already exists

        self._running = True
        logger.info("Consumer %s/%s started on %s", group, consumer, stream_key)

        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    group,
                    consumer,
                    streams={stream_key: ">"},
                    count=count,
                    block=block_ms,
                )
                if not messages:
                    continue

                for _stream_name, entries in messages:
                    for msg_id, fields in entries:
                        if not self._running:
                            return

                        ce = from_redis_fields(fields)
                        try:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(ce.data if hasattr(ce, 'data') else fields)
                            else:
                                handler(ce.data if hasattr(ce, 'data') else fields)
                            await self._redis.xack(stream_key, group, msg_id)
                        except Exception as exc:
                            logger.warning(
                                "Consumer handler error [%s]: %s", event_type, exc
                            )
                            await self._handle_failure(
                                event_type,
                                ce.data if hasattr(ce, 'data') else {},
                                exc,
                                str(msg_id),
                            )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Consumer stream error: %s", exc)
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Stop all consumer loops."""
        self._running = False

    async def stop_and_wait(self) -> None:
        """Stop all consumers and wait for cleanup."""
        self.stop()
        for task in self._consumer_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._consumer_tasks.clear()


# ═══════════════════════════════════════════════════════════════
# Module-level singleton (backward-compatible)
# ═══════════════════════════════════════════════════════════════

bus = EventBus()
