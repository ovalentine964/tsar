"""
BaseAgent — Abstract base for all TSAR agents.

Provides common lifecycle (start/stop), health heartbeat, CloudEvents
publishing/subscribing, configuration loading, and structured logging.
All agents inherit from this.

Event Flow:
  SignalScout → [signal.detected] → RiskGuardian → [risk.approved/vetoed]
    → ExecutionSniper → [trade.executed] → TradePhilosopher

All events use CloudEvents v1.0 via the comms.publisher/subscriber layer.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from src.comms.events import CloudEvent, create_event
from src.comms.publisher import EventPublisher
from src.comms.subscriber import EventSubscriber, EventHandler

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all TSAR agents.

    Provides:
    - Lifecycle management (start/stop with graceful shutdown)
    - CloudEvents publishing via EventPublisher
    - CloudEvents subscribing via EventSubscriber
    - Structured logging for every decision
    - Health heartbeat
    - Configuration access

    Subclasses MUST override:
    - ``AGENT_NAME``: str — unique agent identifier
    - ``ROLE``: str — agent role (READ|ANALYSIS|TRADE_PREVIEW|TRADE_EXECUTE|TRADE_ADMIN)
    - ``run_cycle()``: async — main agent logic per cycle

    Attributes:
        AGENT_NAME: Unique agent name (e.g., "signal_scout").
        ROLE: Agent role for CloudEvents metadata.
    """

    # Subclasses MUST override these
    AGENT_NAME: str = "base"
    ROLE: str = "READ"  # READ | ANALYSIS | TRADE_PREVIEW | TRADE_EXECUTE | TRADE_ADMIN

    # Stream names — subclasses override for their specific streams
    PUBLISH_STREAM: str = ""
    SUBSCRIBE_STREAMS: list[str] = []

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        publisher: EventPublisher | None = None,
        subscriber: EventSubscriber | None = None,
    ) -> None:
        """Initialize the base agent.

        Args:
            config: Full TSAR configuration dict.
            trading_mode: "paper" or "live".
            publisher: EventPublisher instance (created if None).
            subscriber: EventSubscriber instance (created if None).
        """
        self.config = config
        self.trading_mode = trading_mode
        self.agent_id = f"{self.AGENT_NAME}:{uuid.uuid4().hex[:8]}"

        # Lifecycle state
        self._running = False
        self._task: asyncio.Task | None = None
        self._subscription_tasks: list[asyncio.Task] = []

        # Heartbeat tracking
        self._last_heartbeat = 0.0
        self._heartbeat_interval = config.get("agents", {}).get("heartbeat_interval_s", 10)

        # Event infrastructure
        self._publisher = publisher or EventPublisher()
        self._subscriber = subscriber or EventSubscriber()

        # Metrics
        self._events_published = 0
        self._events_received = 0
        self._errors_count = 0
        self._last_cycle_time = 0.0

    # ═══════════════════════════════════════════════════════════════
    # ABSTRACT METHODS
    # ═══════════════════════════════════════════════════════════════

    @abstractmethod
    async def run_cycle(self) -> None:
        """Execute one agent cycle. Subclasses implement their logic here.

        Called repeatedly by the main loop. Should complete within a
        reasonable time. Exceptions are caught and logged by the main loop.
        """

    async def on_initialize(self) -> None:
        """Hook called once after start, before the main loop begins.

        Override to perform async initialization (e.g., connect to exchange,
        load historical data, subscribe to streams).
        """

    async def on_shutdown(self) -> None:
        """Hook called once during graceful shutdown.

        Override to perform cleanup (e.g., close connections, flush buffers).
        """

    # ═══════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════

    async def start(self) -> None:
        """Start the agent's main loop and subscriptions.

        Performs:
        1. Calls on_initialize() for subclass setup
        2. Starts stream subscriptions for subscribed streams
        3. Starts the main run_cycle loop
        4. Sends initial heartbeat
        """
        self._running = True
        logger.info(
            "Starting agent: %s (role=%s, mode=%s)",
            self.agent_id, self.ROLE, self.trading_mode,
        )

        # Initialize
        await self.on_initialize()

        # Start stream subscriptions
        for stream in self.SUBSCRIBE_STREAMS:
            task = self._subscriber.subscribe_background(
                stream=stream,
                group=f"tsar:{self.AGENT_NAME}",
                consumer=self.agent_id,
                callback=self._make_event_handler(stream),
            )
            self._subscription_tasks.append(task)
            logger.info("  %s subscribed to stream: %s", self.agent_id, stream)

        # Start main loop
        self._task = asyncio.create_task(self._main_loop())
        logger.info("Agent %s started", self.agent_id)

    async def stop(self) -> None:
        """Stop the agent gracefully.

        Performs:
        1. Sets running flag to False
        2. Stops stream subscriptions
        3. Cancels main loop task
        4. Calls on_shutdown() for subclass cleanup
        """
        logger.info("Stopping agent: %s", self.agent_id)
        self._running = False

        # Stop subscriptions
        self._subscriber.stop()
        for task in self._subscription_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._subscription_tasks.clear()

        # Stop main loop
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Cleanup
        await self.on_shutdown()
        logger.info("Stopped agent: %s", self.agent_id)

    async def _main_loop(self) -> None:
        """Main agent loop — run cycles and send heartbeats."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                self._errors_count += 1
                logger.exception("Error in %s cycle", self.agent_id)
            finally:
                self._last_cycle_time = time.monotonic() - cycle_start
                await self._heartbeat()
                await asyncio.sleep(1)  # Prevent tight loop

    # ═══════════════════════════════════════════════════════════════
    # EVENT PUBLISHING
    # ═══════════════════════════════════════════════════════════════

    async def publish_event(
        self,
        stream: str,
        event_type: str,
        data: dict[str, Any],
        priority: int = 2,
        risk_level: str = "NONE",
        trace_id: str | None = None,
    ) -> str:
        """Publish a CloudEvents message to a Redis stream.

        Args:
            stream: Stream name (e.g., "signals", "risk_decisions").
            event_type: CloudEvents type (e.g., "tsar.signal.detected.v1").
            data: Event payload.
            priority: 0=critical, 1=high, 2=normal, 3=low.
            risk_level: NONE|LOW|MEDIUM|HIGH|CRITICAL.
            trace_id: Distributed tracing ID (auto-generated if None).

        Returns:
            Message ID from the publisher.
        """
        msg_id = await self._publisher.publish(
            stream=stream,
            event_type=event_type,
            data=data,
            source=f"tsar:agent:{self.AGENT_NAME}",
            priority=priority,
            risk_level=risk_level,
            agent_role=self.ROLE,
            trading_mode=self.trading_mode,
            trace_id=trace_id,
        )
        self._events_published += 1
        logger.debug(
            "[%s] Published %s to %s (msg_id=%s)",
            self.agent_id, event_type, stream, msg_id,
        )
        return msg_id

    # ═══════════════════════════════════════════════════════════════
    # EVENT SUBSCRIBING
    # ═══════════════════════════════════════════════════════════════

    def _make_event_handler(self, stream: str) -> EventHandler:
        """Create an event handler for a stream.

        Routes events to handle_event() with structured logging.

        Args:
            stream: The stream name being subscribed to.

        Returns:
            Async event handler callback.
        """
        async def handler(event: CloudEvent) -> None:
            self._events_received += 1
            logger.info(
                "[%s] Received event: %s from %s (stream=%s, trace=%s)",
                self.agent_id, event.type, event.source, stream, event.traceid,
            )
            try:
                await self.handle_event(stream, event)
            except Exception:
                self._errors_count += 1
                logger.exception(
                    "[%s] Error handling event %s", self.agent_id, event.type,
                )

        return handler

    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        """Handle an incoming event from a subscribed stream.

        Override in subclasses to process specific event types.
        Default implementation logs and discards.

        Args:
            stream: The stream the event arrived on.
            event: The CloudEvent to process.
        """
        logger.debug(
            "[%s] Unhandled event: %s (stream=%s)", self.agent_id, event.type, stream,
        )

    # ═══════════════════════════════════════════════════════════════
    # HEALTH & HEARTBEAT
    # ═══════════════════════════════════════════════════════════════

    async def _heartbeat(self) -> None:
        """Send heartbeat if interval has elapsed."""
        now = time.time()
        if now - self._last_heartbeat >= self._heartbeat_interval:
            self._last_heartbeat = now
            health = self.get_health()
            logger.debug("Heartbeat: %s health=%s", self.agent_id, health)
            try:
                await self.publish_event(
                    stream="health",
                    event_type="tsar.agent.heartbeat.v1",
                    data=health,
                    priority=3,  # Low priority
                )
            except Exception:
                logger.debug("Heartbeat publish failed (non-critical)")

    def get_health(self) -> dict[str, Any]:
        """Return current health status for monitoring.

        Returns:
            Dict with agent health metrics.
        """
        return {
            "agent_id": self.agent_id,
            "agent_name": self.AGENT_NAME,
            "role": self.ROLE,
            "running": self._running,
            "trading_mode": self.trading_mode,
            "events_published": self._events_published,
            "events_received": self._events_received,
            "errors": self._errors_count,
            "last_cycle_time_ms": round(self._last_cycle_time * 1000, 2),
            "timestamp": time.time(),
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.agent_id} role={self.ROLE}>"
