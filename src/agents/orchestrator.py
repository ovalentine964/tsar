"""
Orchestrator — Coordinates all TSAR agents and manages the trading pipeline.

Role: TRADE_ADMIN

Main loop (every 5 minutes):
  1. SCAN   — Trigger market scan via SignalScout
  2. SIGNAL — Process detected signals
  3. RISK   — Evaluate signals through RiskGuardian
  4. EXECUTE — Execute approved trades via ExecutionSniper
  5. REFLECT — Log results and update state

The Orchestrator is the conductor of the trading symphony.
It owns the lifecycle of all agents and ensures graceful shutdown.

Subscribes to: tsar:stream:health, tsar:stream:trades
Publishes to:  tsar:stream:commands
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any

from src.agents.base import BaseAgent
from src.comms.events import CloudEvent
from src.comms.publisher import EventPublisher
from src.comms.subscriber import EventSubscriber

logger = logging.getLogger(__name__)


class Orchestrator(BaseAgent):
    """Supervisor agent — coordinates all TSAR agents.

    Responsibilities:
    - Create and manage all agent lifecycles
    - Run the main trading loop: scan → signal → risk → execute → reflect
    - Monitor agent health via heartbeats
    - Route alerts to appropriate channels
    - Coordinate graceful shutdown
    - Manage paper/live mode switches
    """

    AGENT_NAME = "orchestrator"
    ROLE = "TRADE_ADMIN"

    PUBLISH_STREAM = "commands"
    SUBSCRIBE_STREAMS = ["health", "trades"]

    # Agent registry — maps agent names to their classes
    AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)

        # Agent management
        self._agents: dict[str, BaseAgent] = {}
        self._agent_health: dict[str, dict[str, Any]] = {}
        self._last_health_check: dict[str, float] = {}

        # Pipeline state
        self._scan_interval = config.get("agents", {}).get("orchestrator", {}).get(
            "scan_interval_s", 300
        )  # 5 minutes
        self._last_scan_time: float = 0
        self._pipeline_running = False

        # Metrics
        self._cycles_completed = 0
        self._signals_processed = 0
        self._trades_executed = 0
        self._trades_failed = 0

        # Graceful shutdown
        self._shutdown_event = asyncio.Event()

    async def on_initialize(self) -> None:
        """Initialize all agents and start the trading pipeline."""
        logger.info("🏰 TSAR Orchestrator initializing (mode=%s)", self.trading_mode)

        # Import agent classes (avoid circular imports)
        self._load_agent_registry()

        # Create and start enabled agents
        enabled_agents = self.config.get("agents", {}).get("enabled", [
            "signal_scout",
            "risk_guardian",
            "execution_sniper",
        ])

        # Shared pub/sub for all agents
        publisher = EventPublisher()
        subscriber = EventSubscriber()

        for agent_name in enabled_agents:
            agent = self._create_agent(agent_name, publisher, subscriber)
            if agent:
                self._agents[agent_name] = agent
                await agent.start()
                logger.info("  ✓ Started %s", agent_name)
            else:
                logger.warning("  ✗ Failed to create agent: %s", agent_name)

        # Register signal handlers for graceful shutdown
        self._register_signal_handlers()

        logger.info(
            "🏰 Orchestrator ready: %d agents active, scan interval=%ds",
            len(self._agents), self._scan_interval,
        )

    async def on_shutdown(self) -> None:
        """Stop all agents gracefully."""
        logger.info("🏰 Orchestrator shutting down...")

        # Stop all agents in reverse order
        agent_names = list(self._agents.keys())
        for name in reversed(agent_names):
            agent = self._agents[name]
            try:
                await agent.stop()
                logger.info("  ✓ Stopped %s", name)
            except Exception:
                logger.exception("  ✗ Error stopping %s", name)

        self._agents.clear()
        logger.info("🏰 Orchestrator shutdown complete")

    async def stop(self) -> None:
        """Signal shutdown and stop all agents."""
        self._shutdown_event.set()
        await super().stop()

    def _load_agent_registry(self) -> None:
        """Load agent classes into the registry."""
        from src.agents.execution_sniper import ExecutionSniper
        from src.agents.risk_guardian import RiskGuardian
        from src.agents.signal_scout import SignalScout

        self.AGENT_REGISTRY = {
            "signal_scout": SignalScout,
            "risk_guardian": RiskGuardian,
            "execution_sniper": ExecutionSniper,
        }

    def _create_agent(
        self,
        name: str,
        publisher: EventPublisher,
        subscriber: EventSubscriber,
    ) -> BaseAgent | None:
        """Create an agent by name.

        Args:
            name: Agent name from the registry.
            publisher: Shared EventPublisher.
            subscriber: Shared EventSubscriber.

        Returns:
            BaseAgent instance or None if unknown.
        """
        cls = self.AGENT_REGISTRY.get(name)
        if not cls:
            logger.warning("Unknown agent: %s", name)
            return None

        return cls(
            config=self.config,
            trading_mode=self.trading_mode,
            publisher=publisher,
            subscriber=subscriber,
        )

    def _register_signal_handlers(self) -> None:
        """Register OS signal handlers for graceful shutdown."""
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
            logger.info("Signal handlers registered (SIGINT, SIGTERM)")
        except NotImplementedError:
            logger.warning("Signal handlers not supported on this platform")

    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        """Handle events from subscribed streams.

        - health: Update agent health tracking
        - trades: Track trade execution results
        """
        if stream == "health" and event.type == "tsar.agent.heartbeat.v1":
            agent_id = event.data.get("agent_id", "unknown")
            self._agent_health[agent_id] = event.data
            self._last_health_check[agent_id] = time.time()

        elif stream == "trades":
            if event.type == "tsar.trade.executed.v1":
                self._trades_executed += 1
                logger.info(
                    "📊 Trade executed: %s %s qty=%s price=%s slippage=%s bps",
                    event.data.get("symbol"),
                    event.data.get("side"),
                    event.data.get("quantity"),
                    event.data.get("entry_price"),
                    event.data.get("slippage_bps"),
                )
            elif event.type == "tsar.trade.failed.v1":
                self._trades_failed += 1
                logger.warning(
                    "⚠️ Trade failed: %s %s — %s",
                    event.data.get("symbol"),
                    event.data.get("side"),
                    event.data.get("reason"),
                )

    async def run_cycle(self) -> None:
        """Main orchestrator cycle.

        The cycle:
        1. Check if it's time for a scan
        2. Monitor agent health
        3. Log pipeline status

        The actual trading pipeline is event-driven:
        - SignalScout detects signals → publishes signal.detected
        - RiskGuardian evaluates → publishes risk.approved/vetoed
        - ExecutionSniper executes → publishes trade.executed

        The Orchestrator monitors and coordinates.
        """
        now = time.monotonic()

        # ── Pipeline Status ───────────────────────────────────────
        if now - self._last_scan_time >= self._scan_interval:
            self._last_scan_time = now
            self._cycles_completed += 1
            await self._log_pipeline_status()

        # ── Health Monitoring ─────────────────────────────────────
        await self._check_agent_health()

    async def _check_agent_health(self) -> None:
        """Check health of all managed agents.

        Logs warnings for agents that haven't sent heartbeats recently.
        """
        now = time.time()
        heartbeat_timeout = self._heartbeat_interval * 3  # 3x heartbeat interval

        for name, agent in self._agents.items():
            agent_id = agent.agent_id
            last_check = self._last_health_check.get(agent_id, 0)

            if now - last_check > heartbeat_timeout:
                logger.warning(
                    "⚠️ Agent %s (%s) missed heartbeat (last=%.0fs ago)",
                    name, agent_id, now - last_check,
                )
            else:
                health = self._agent_health.get(agent_id, {})
                errors = health.get("errors", 0)
                if errors > 0:
                    logger.info(
                        "Agent %s: %d errors, last_cycle=%.1fms",
                        name, errors, health.get("last_cycle_time_ms", 0),
                    )

    async def _log_pipeline_status(self) -> None:
        """Log current pipeline status and metrics."""
        active_agents = len(self._agents)
        logger.info(
            "═══ Pipeline Status (cycle #%d) ═══\n"
            "  Active agents: %d\n"
            "  Signals processed: %d\n"
            "  Trades executed: %d\n"
            "  Trades failed: %d\n"
            "  Mode: %s",
            self._cycles_completed,
            active_agents,
            self._signals_processed,
            self._trades_executed,
            self._trades_failed,
            self.trading_mode,
        )

    def get_health(self) -> dict[str, Any]:
        """Get orchestrator and all agent health status.

        Returns:
            Comprehensive health status dict.
        """
        base_health = super().get_health()
        base_health.update({
            "agents": {
                name: agent.get_health()
                for name, agent in self._agents.items()
            },
            "pipeline": {
                "cycles_completed": self._cycles_completed,
                "signals_processed": self._signals_processed,
                "trades_executed": self._trades_executed,
                "trades_failed": self._trades_failed,
                "scan_interval_s": self._scan_interval,
            },
        })
        return base_health

    async def add_agent(self, name: str) -> bool:
        """Dynamically add and start an agent.

        Args:
            name: Agent name from the registry.

        Returns:
            True if agent was added successfully.
        """
        if name in self._agents:
            logger.warning("Agent %s already running", name)
            return False

        agent = self._create_agent(name, EventPublisher(), EventSubscriber())
        if not agent:
            return False

        self._agents[name] = agent
        await agent.start()
        logger.info("Added and started agent: %s", name)
        return True

    async def remove_agent(self, name: str) -> bool:
        """Stop and remove an agent.

        Args:
            name: Agent name to remove.

        Returns:
            True if agent was removed successfully.
        """
        agent = self._agents.pop(name, None)
        if not agent:
            logger.warning("Agent %s not found", name)
            return False

        await agent.stop()
        logger.info("Removed agent: %s", name)
        return True

    async def switch_mode(self, new_mode: str) -> None:
        """Switch trading mode (paper ↔ live).

        This requires stopping all agents and restarting them with
        the new mode.

        Args:
            new_mode: "paper" or "live".
        """
        if new_mode == self.trading_mode:
            logger.info("Already in %s mode", new_mode)
            return

        logger.info("Switching mode: %s → %s", self.trading_mode, new_mode)

        # Stop all agents
        for name in reversed(list(self._agents.keys())):
            await self._agents[name].stop()
        self._agents.clear()

        # Update mode
        self.trading_mode = new_mode

        # Restart agents with new mode
        await self.on_initialize()

        logger.info("Mode switch complete: now in %s mode", new_mode)
