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
from typing import Any

from src.agents.base import BaseAgent
from src.comms.event_bus import EventBus
from src.comms.events import (
    TSAR_RULE_VALIDATED,
    TSAR_SHADOW_EXTRACTED,
    TSAR_STRATEGY_PROPOSAL,
    CloudEvent,
)
from src.comms.publisher import EventPublisher
from src.comms.subscriber import EventSubscriber

# ── Domain Tools (Tools-to-Agents Wiring) ──────────────────────────
from src.tools.knowledge import KnowledgeTools
from src.tools.monitoring import PnLTracker, WinRateTracker, AlertGenerator

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

        # Flywheel orchestrator reference (for trade event forwarding)
        self._flywheel_orchestrator = None

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

        # Shadow extraction loop (initialized in on_initialize)
        self._shadow_extractor = None
        self._rule_validator = None
        self._genome_mutator = None
        self._last_shadow_extraction: float = 0

        # ── Domain Tools (Tools-to-Agents Wiring) ───────
        self._knowledge_tools: KnowledgeTools | None = None
        self._pnl_tracker: PnLTracker | None = None
        self._win_rate_tracker: WinRateTracker | None = None
        self._alert_generator: AlertGenerator | None = None

        # Event bus for flywheel
        self._event_bus = EventBus()
        self._trade_count = 0

        # Wire event bus to flywheel orchestrator for trade forwarding
        self._event_bus.subscribe("tsar.trade.executed", self._forward_to_flywheel)
        self._event_bus.subscribe("tsar.trade.recorded", self._forward_to_flywheel)

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
            "strategy_geneticist",
            "flywheel_orchestrator",
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
                # Track flywheel orchestrator reference for trade forwarding
                if agent_name == "flywheel_orchestrator":
                    self._flywheel_orchestrator = agent
            else:
                logger.warning("  ✗ Failed to create agent: %s", agent_name)

        # Register signal handlers for graceful shutdown
        self._register_signal_handlers()

        # Initialize domain tools for orchestrator-level monitoring
        await self._initialize_orchestrator_tools()

        # Initialize shadow extraction loop
        await self._initialize_shadow_loop()

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
        """Load agent classes into the registry.

        Includes StrategyGeneticist for the flywheel EXTRACT→ADAPT pipeline.
        """
        from src.agents.execution_sniper import ExecutionSniper
        from src.agents.flywheel_orchestrator import FlywheelOrchestrator
        from src.agents.risk_guardian import RiskGuardian
        from src.agents.signal_scout import SignalScout
        from src.agents.strategy_geneticist import StrategyGeneticist

        self.AGENT_REGISTRY = {
            "signal_scout": SignalScout,
            "risk_guardian": RiskGuardian,
            "execution_sniper": ExecutionSniper,
            "strategy_geneticist": StrategyGeneticist,
            "flywheel_orchestrator": FlywheelOrchestrator,
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

    async def _initialize_orchestrator_tools(self) -> None:
        """Initialize orchestrator-level domain tools.

        Sets up KnowledgeTools (for shadow extraction pipeline access),
        and monitoring tools (P&L, win rate, alerts) for system-wide visibility.
        """
        try:
            db_path = self.config.get("database", {}).get("db_path", "data/tsar.db")
            self._knowledge_tools = KnowledgeTools(db_path)
            logger.info("Orchestrator: KnowledgeTools initialized")
        except Exception as e:
            logger.warning("Orchestrator KnowledgeTools init failed: %s", e)

        try:
            self._pnl_tracker = PnLTracker()
            self._win_rate_tracker = WinRateTracker()
            self._alert_generator = AlertGenerator()
            logger.info("Orchestrator: monitoring tools initialized")
        except Exception as e:
            logger.warning("Orchestrator monitoring tools init failed: %s", e)

    async def _initialize_shadow_loop(self) -> None:
        """Initialize the shadow extraction → validation → mutation pipeline.

        Sets up ShadowExtractor, RuleValidator (with OHLCVProvider adapter),
        and GenomeMutator. Only activates if shadow_extractor is enabled in config.
        """
        shadow_config = self.config.get("shadow_extractor", {})
        if not shadow_config.get("enabled", False):
            logger.info("Shadow extraction loop: disabled")
            return

        try:
            from src.interfaces import get_exchange_gateway, get_llm_provider
            from src.knowledge.genome_mutator import GenomeMutator, MutatorConfig
            from src.knowledge.ohlcv_adapter import ExchangeGatewayOHLCVAdapter
            from src.knowledge.rule_validator import RuleValidator
            from src.knowledge.shadow_extractor import ShadowExtractor
            from src.knowledge.trade_memory import TradeMemory

            db_path = self.config.get("database", {}).get("db_path", "data/tsar.db")

            # TradeMemory for reading closed trades
            trade_memory = TradeMemory(db_path)

            # LLM provider for rule extraction
            llm_provider = get_llm_provider()
            self._shadow_extractor = ShadowExtractor(
                trade_memory=trade_memory,
                llm_provider=llm_provider,
            )

            # OHLCV adapter wrapping ExchangeGateway
            gateway = get_exchange_gateway()
            ohlcv_adapter = ExchangeGatewayOHLCVAdapter(gateway)
            self._rule_validator = RuleValidator(
                ohlcv_provider=ohlcv_adapter,
                db_path=db_path,
            )

            # Genome mutator for proposing strategy mutations
            from src.knowledge.strategy_genomes import StrategyGenomes
            genomes = StrategyGenomes(db_path)
            mutator_config = MutatorConfig(
                min_confidence=shadow_config.get("min_confidence", 0.6),
                min_sharpe=shadow_config.get("min_sharpe", 0.5),
                max_proposals_per_run=shadow_config.get("max_proposals", 5),
                allow_new_genomes=shadow_config.get("allow_new_genomes", False),
            )
            self._genome_mutator = GenomeMutator(
                strategy_genomes=genomes,
                config=mutator_config,
            )

            logger.info(
                "🔄 Shadow extraction loop initialized (interval=%dh, min_trades=%d)",
                shadow_config.get("cycle_interval_hours", 24),
                shadow_config.get("min_trades", 10),
            )

        except Exception as e:
            logger.error("Failed to initialize shadow loop: %s", e)
            self._shadow_extractor = None
            self._rule_validator = None
            self._genome_mutator = None

    async def _run_shadow_extraction(self) -> None:
        """Run the full shadow extraction → validation → mutation pipeline.

        Steps:
        1. Extract rules from closed trade history via ShadowExtractor
        2. Validate rules via RuleValidator (OHLCV backtest)
        3. Propose genome mutations via GenomeMutator
        4. Publish mutation proposals for Strategy Geneticist
        """
        logger.info("🔄 Starting shadow extraction cycle...")

        try:
            shadow_config = self.config.get("shadow_extractor", {})

            # Step 1: Extract rules from trade history
            extraction = await self._shadow_extractor.extract(
                min_trades=shadow_config.get("min_trades", 10),
                min_win_rate=shadow_config.get("min_win_rate", 0.55),
                lookback_days=shadow_config.get("lookback_days", 90),
            )
            if not extraction.rules:
                logger.info("Shadow extraction: no rules found")
                return

            logger.info(
                "Shadow extraction: %d rules from %d trades (%d winners)",
                len(extraction.rules), extraction.source_trade_count,
                extraction.winning_trade_count,
            )

            # Publish extraction event
            await self.publish_event(
                stream="commands",
                event_type=TSAR_SHADOW_EXTRACTED,
                data={
                    "rules": [r.to_dict() for r in extraction.rules],
                    "source_trade_count": extraction.source_trade_count,
                    "winning_trade_count": extraction.winning_trade_count,
                    "losing_trade_count": extraction.losing_trade_count,
                },
                priority=3,
                agent_role="ANALYSIS",
            )

            # Step 2: Validate rules via backtest
            timeframe = shadow_config.get("timeframe", "1h")
            lookback = shadow_config.get("lookback_candles", 500)
            validated = await self._rule_validator.validate_batch(
                extraction.rules,
                timeframe=timeframe,
                lookback_candles=lookback,
            )
            passed = [r for r in validated if r.validation_status == "passed"]
            logger.info(
                "Rule validation: %d/%d passed",
                len(passed), len(validated),
            )

            # Publish validation events
            for vr in validated:
                await self.publish_event(
                    stream="commands",
                    event_type=TSAR_RULE_VALIDATED,
                    data={
                        "rule_id": vr.rule_id,
                        "source_rule_id": vr.source_rule_id,
                        "status": vr.validation_status,
                        "sharpe": vr.sharpe,
                        "win_rate": vr.win_rate,
                        "profit_factor": vr.profit_factor,
                        "sample_size": vr.sample_size,
                    },
                    priority=3,
                    agent_role="ANALYSIS",
                )

            if not passed:
                return

            # Step 3: Propose genome mutations
            proposals = await self._genome_mutator.propose_mutations(passed)
            logger.info(
                "Genome mutations: %d proposals from %d validated rules",
                len(proposals), len(passed),
            )

            # Step 4: Publish proposals for Strategy Geneticist
            for proposal in proposals:
                await self.publish_event(
                    stream="strategy_proposals",
                    event_type=TSAR_STRATEGY_PROPOSAL,
                    data=proposal.to_dict(),
                    priority=2,
                    agent_role="ANALYSIS",
                )

            logger.info(
                "🔄 Shadow extraction cycle complete: "
                "%d rules → %d validated → %d proposals",
                len(extraction.rules), len(passed), len(proposals),
            )

        except Exception as e:
            logger.error("Shadow extraction cycle failed: %s", e)

    async def _forward_to_flywheel(self, data: dict[str, Any]) -> None:
        """Forward trade events to the FlywheelOrchestrator if registered.

        This connects the orchestrator's trade event bus to the
        flywheel's trade monitoring, enabling automatic flywheel
        activation after trade completions.
        """
        if self._flywheel_orchestrator and hasattr(self._flywheel_orchestrator, "_on_trade_executed"):
            try:
                await self._flywheel_orchestrator._on_trade_executed(data)
            except Exception as e:
                logger.warning("Failed to forward trade to flywheel: %s", e)

    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        """Handle events from subscribed streams.

        - health: Update agent health tracking
        - trades: Track trade execution results and forward to flywheel
        """
        if stream == "health" and event.type == "tsar.agent.heartbeat.v1":
            agent_id = event.data.get("agent_id", "unknown")
            self._agent_health[agent_id] = event.data
            self._last_health_check[agent_id] = time.time()

        elif stream == "trades":
            if event.type == "tsar.trade.executed.v1":
                self._trades_executed += 1
                self._trade_count += 1
                logger.info(
                    "📊 Trade executed: %s %s qty=%s price=%s slippage=%s bps",
                    event.data.get("symbol"),
                    event.data.get("side"),
                    event.data.get("quantity"),
                    event.data.get("entry_price"),
                    event.data.get("slippage_bps"),
                )

                # Flywheel: publish trade event to event bus
                # The FlywheelOrchestrator subscribes to these events
                await self._event_bus.publish("tsar.trade.executed", event.data)
                await self._event_bus.publish("tsar.trade.recorded", event.data)

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
        3. Run shadow extraction if interval elapsed
        4. Log pipeline status

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

        # ── Shadow Extraction Cycle ───────────────────────────────
        if self._shadow_extractor:
            shadow_interval = self.config.get("shadow_extractor", {}).get(
                "cycle_interval_hours", 24
            ) * 3600
            if now - self._last_shadow_extraction >= shadow_interval:
                self._last_shadow_extraction = now
                await self._run_shadow_extraction()

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
