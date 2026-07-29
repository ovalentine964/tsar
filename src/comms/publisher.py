"""
EventPublisher — Publish CloudEvents to Redis Streams (or in-memory for Day1).

Agents use this to publish events to ``tsar:stream:*`` streams.
Supports both Redis Streams and an in-memory fallback for development/testing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from src.comms.events import CloudEvent, create_event, to_redis_fields

logger = logging.getLogger(__name__)


class EventPublisher:
    """Publish CloudEvents to event streams.

    Supports two backends:
    - **Redis Streams**: Uses ``redis.asyncio`` client for production.
    - **In-memory**: Uses an :class:`InMemoryBus` singleton for Day1/testing.

    Args:
        redis_client: An async Redis client instance (or None for in-memory).
        prefix: Stream key prefix (default ``"tsar:stream:"``).
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        prefix: str = "tsar:stream:",
    ) -> None:
        self._redis = redis_client
        self._prefix = prefix
        self._in_memory_bus: InMemoryBus | None = None

        if self._redis is None:
            self._in_memory_bus = _get_global_bus()
            logger.info("EventPublisher using in-memory bus")

    async def publish(
        self,
        stream: str,
        event_type: str,
        data: dict[str, Any],
        source: str = "tsar:agent:unknown",
        **kwargs: Any,
    ) -> str:
        """Publish an event to a stream.

        Args:
            stream: Stream name (e.g., ``"signals"``, ``"risk_decisions"``).
            event_type: CloudEvents type (e.g., ``"tsar.signal.detected.v1"``).
            data: Event payload.
            source: Event source identifier.
            **kwargs: Additional CloudEvents fields (priority, risk_level, etc.).

        Returns:
            Message ID (Redis stream ID or in-memory UUID).
        """
        event = create_event(source=source, event_type=event_type, data=data, **kwargs)

        if self._redis is not None:
            return await self._publish_redis(stream, event)
        else:
            return await self._publish_memory(stream, event)

    async def publish_event(self, stream: str, event: CloudEvent) -> str:
        """Publish a pre-built CloudEvent to a stream.

        Args:
            stream: Stream name.
            event: CloudEvent instance.

        Returns:
            Message ID.
        """
        if self._redis is not None:
            return await self._publish_redis(stream, event)
        else:
            return await self._publish_memory(stream, event)

    async def _publish_redis(self, stream: str, event: CloudEvent) -> str:
        """Publish to a Redis Stream."""
        fields = to_redis_fields(event)
        stream_key = f"{self._prefix}{stream}"
        assert self._redis is not None
        msg_id = await self._redis.xadd(stream_key, fields)
        logger.debug("Published %s to %s: %s", event.type, stream_key, msg_id)
        return str(msg_id)

    async def _publish_memory(self, stream: str, event: CloudEvent) -> str:
        """Publish to the in-memory bus."""
        assert self._in_memory_bus is not None
        msg_id = await self._in_memory_bus.publish(stream, event)
        logger.debug("Published %s to in-memory %s: %s", event.type, stream, msg_id)
        return msg_id


# ═══════════════════════════════════════════════════════════════════════
# In-Memory Bus (Day1 / testing)
# ═══════════════════════════════════════════════════════════════════════


class InMemoryBus:
    """In-memory event bus for Day1 development and testing.

    Stores events in per-stream lists and notifies waiting subscribers
    via asyncio Events.  Not suitable for production — no persistence,
    no consumer groups, no backpressure.
    """

    def __init__(self) -> None:
        self._streams: dict[str, list[CloudEvent]] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._id_counter: int = 0

    async def publish(self, stream: str, event: CloudEvent) -> str:
        """Publish an event to an in-memory stream.

        Args:
            stream: Stream name.
            event: CloudEvent to publish.

        Returns:
            Synthetic message ID.
        """
        async with self._lock:
            if stream not in self._streams:
                self._streams[stream] = []
                self._events[stream] = asyncio.Event()

            self._streams[stream].append(event)
            self._id_counter += 1
            msg_id = f"mem-{self._id_counter}"

            # Notify any waiting subscribers
            self._events[stream].set()
            self._events[stream].clear()

        return msg_id

    async def read(
        self,
        stream: str,
        after_index: int = -1,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[tuple[int, CloudEvent]]:
        """Read events from an in-memory stream.

        Args:
            stream: Stream name to read from.
            after_index: Read events after this index (-1 for all from start).
            count: Maximum number of events to return.
            block_ms: How long to wait for new events (0 = don't block).

        Returns:
            List of (index, CloudEvent) tuples.
        """
        # Ensure stream exists
        async with self._lock:
            if stream not in self._streams:
                self._streams[stream] = []
                self._events[stream] = asyncio.Event()

        # Wait for new data if requested
        if block_ms > 0:
            event = self._events.get(stream)
            if event:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(event.wait(), timeout=block_ms / 1000)

        # Read events
        async with self._lock:
            entries = self._streams.get(stream, [])
            start = after_index + 1
            results = [(i, entries[i]) for i in range(start, min(start + count, len(entries)))]
            return results

    def stream_length(self, stream: str) -> int:
        """Get the number of events in a stream."""
        return len(self._streams.get(stream, []))

    def clear(self) -> None:
        """Clear all streams (for testing)."""
        self._streams.clear()
        self._events.clear()
        self._id_counter = 0


# Global singleton for the in-memory bus
_global_bus: InMemoryBus | None = None


def _get_global_bus() -> InMemoryBus:
    """Get or create the global in-memory bus singleton."""
    global _global_bus
    if _global_bus is None:
        _global_bus = InMemoryBus()
    return _global_bus


def reset_global_bus() -> None:
    """Reset the global in-memory bus (for testing)."""
    global _global_bus
    if _global_bus is not None:
        _global_bus.clear()
    _global_bus = None
