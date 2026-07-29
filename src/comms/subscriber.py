"""
EventSubscriber — Subscribe to event streams with callback-based processing.

Supports both Redis Streams with consumer groups and in-memory
subscription for Day1 development and testing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.comms.events import CloudEvent, from_redis_fields

logger = logging.getLogger(__name__)

# Type alias for event handler callbacks
EventHandler = Callable[[CloudEvent], Awaitable[None]]


class EventSubscriber:
    """Subscribe to event streams with callback-based processing.

    Supports two backends:
    - **Redis Streams**: Consumer groups with acknowledgment.
    - **In-memory**: Uses the shared :class:`InMemoryBus` for Day1/testing.

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
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

        if self._redis is None:
            from src.comms.publisher import _get_global_bus
            self._bus = _get_global_bus()
            logger.info("EventSubscriber using in-memory bus")
        else:
            self._bus = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
        callback: EventHandler,
        count: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Subscribe to a stream and process events with a callback.

        For Redis: Creates the consumer group if it doesn't exist, then
        enters a read loop calling ``callback`` for each event and
        acknowledging successful processing.

        For in-memory: Enters a polling loop reading from the in-memory bus.

        Args:
            stream: Stream name (e.g., ``"signals"``).
            group: Consumer group name.
            consumer: Consumer name within the group.
            callback: Async function to handle each event.
            count: Max messages per read batch.
            block_ms: Block timeout in milliseconds.
        """
        self._running = True

        if self._redis is not None:
            await self._subscribe_redis(stream, group, consumer, callback, count, block_ms)
        else:
            await self._subscribe_memory(stream, callback, count, block_ms)

    async def subscribe_background(
        self,
        stream: str,
        group: str,
        consumer: str,
        callback: EventHandler,
        count: int = 10,
        block_ms: int = 5000,
    ) -> asyncio.Task[None]:
        """Subscribe in a background task.

        Same as :meth:`subscribe` but runs in a background asyncio task,
        allowing the caller to continue.

        Args:
            stream: Stream name.
            group: Consumer group name.
            consumer: Consumer name.
            callback: Async event handler.
            count: Max messages per batch.
            block_ms: Block timeout.

        Returns:
            The asyncio Task running the subscription loop.
        """
        task = asyncio.create_task(
            self.subscribe(stream, group, consumer, callback, count, block_ms),
            name=f"subscriber-{stream}-{consumer}",
        )
        self._tasks.append(task)
        return task

    def stop(self) -> None:
        """Signal all subscription loops to stop."""
        self._running = False
        logger.info("EventSubscriber stop requested")

    async def stop_and_wait(self) -> None:
        """Stop all subscriptions and wait for tasks to complete."""
        self.stop()
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    # ------------------------------------------------------------------
    # Redis Streams backend
    # ------------------------------------------------------------------

    async def _subscribe_redis(
        self,
        stream: str,
        group: str,
        consumer: str,
        callback: EventHandler,
        count: int,
        block_ms: int,
    ) -> None:
        """Subscribe using Redis Streams consumer groups."""
        stream_key = f"{self._prefix}{stream}"

        # Create consumer group if it doesn't exist
        assert self._redis is not None
        try:
            await self._redis.xgroup_create(stream_key, group, id="0", mkstream=True)
            logger.info("Created consumer group %s on %s", group, stream_key)
        except Exception:
            pass  # Group already exists

        logger.info("Subscribing to %s as %s/%s", stream_key, group, consumer)

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

                        event = from_redis_fields(fields)
                        try:
                            await callback(event)
                            await self._redis.xack(stream_key, group, msg_id)
                        except Exception:
                            logger.exception(
                                "Error processing message %s from %s", msg_id, stream_key
                            )

            except asyncio.CancelledError:
                logger.info("Subscription cancelled for %s", stream_key)
                return
            except Exception:
                logger.exception("Error reading from %s", stream_key)
                await asyncio.sleep(1)  # Back off on error

    # ------------------------------------------------------------------
    # In-Memory backend
    # ------------------------------------------------------------------

    async def _subscribe_memory(
        self,
        stream: str,
        callback: EventHandler,
        count: int,
        block_ms: int,
    ) -> None:
        """Subscribe using the in-memory bus."""
        from src.comms.publisher import InMemoryBus

        assert isinstance(self._bus, InMemoryBus)
        read_index = -1

        logger.info("Subscribing to in-memory stream: %s", stream)

        while self._running:
            try:
                entries = await self._bus.read(
                    stream,
                    after_index=read_index,
                    count=count,
                    block_ms=block_ms,
                )

                for idx, event in entries:
                    if not self._running:
                        return

                    try:
                        await callback(event)
                        read_index = idx
                    except Exception:
                        logger.exception(
                            "Error processing in-memory event %d from %s", idx, stream
                        )

                # If no entries, yield to avoid busy-wait
                if not entries:
                    await asyncio.sleep(0.05)

            except asyncio.CancelledError:
                logger.info("In-memory subscription cancelled for %s", stream)
                return
            except Exception:
                logger.exception("Error reading from in-memory stream %s", stream)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Synchronous callback support (convenience)
    # ------------------------------------------------------------------

    @staticmethod
    def wrap_sync_callback(
        fn: Callable[[CloudEvent], None],
    ) -> EventHandler:
        """Wrap a synchronous callback as an async handler.

        Useful when the callback doesn't need to await anything.

        Args:
            fn: Synchronous function taking a CloudEvent.

        Returns:
            Async callable suitable for ``subscribe()``.
        """

        async def _async_wrapper(event: CloudEvent) -> None:
            fn(event)

        return _async_wrapper
