"""
Flywheel Orchestrator — Auto-triggers the TSAR self-improvement loop.

The flywheel: TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → **FINE-TUNE** → BETTER TRADE

This agent monitors trade completions and automatically kicks off:
  ShadowExtractor → RuleValidator → GenomeMutator → StrategyGeneticist
  → PostTrainingPipeline (LoRA fine-tuning from trade data)

It closes the loop so the system learns from every trade without manual
intervention. The post-training step is Jensen's vision realized:
"You can now also improve the AI model, the large language model,
inside the harness."

Subscribes to: trades (via EventBus)
Publishes to:  flywheel_events
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.agents.base import BaseAgent
from src.comms.events import CloudEvent

logger = logging.getLogger(__name__)


class FlywheelOrchestrator(BaseAgent):
    """Orchestrate the TSAR flywheel: extract → validate → mutate → evolve → fine-tune.

    Listens for trade completions on the EventBus and triggers the
    full learning pipeline automatically. Includes the post-training
    pipeline that fine-tunes the LLM from accumulated trade data.

    Attributes:
        AGENT_NAME: Unique agent identifier.
        ROLE: Agent role for CloudEvents metadata.
    """

    AGENT_NAME = "flywheel_orchestrator"
    ROLE = "ANALYSIS"

    PUBLISH_STREAM = "flywheel_events"
    SUBSCRIBE_STREAMS = ["trades", "fills"]

    # Flywheel tuning
    MIN_TRADES_FOR_EXTRACTION = 5
    COOLDOWN_SECONDS = 300  # 5 min between flywheel runs
    BATCH_SIZE = 10  # Run flywheel every N trades

    # Post-training tuning
    POST_TRAINING_BATCH_SIZE = 50  # Run post-training every N trades
    POST_TRAINING_COOLDOWN_S = 21600  # 6 hours between post-training runs

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)

        # Pipeline components (initialized in on_initialize)
        self._shadow_extractor = None
        self._rule_validator = None
        self._genome_mutator = None
        self._strategy_geneticist = None

        # Post-training pipeline (LoRA fine-tuning)
        self._post_training_pipeline = None
        self._last_post_training_run: float = 0
        self._post_training_runs = 0
        self._post_training_deployments = 0

        # Trade tracking
        self._trade_count = 0
        self._trades_since_flywheel = 0
        self._trades_since_post_training = 0
        self._last_flywheel_run: float = 0

        # Flywheel metrics
        self._flywheel_runs = 0
        self._total_rules_extracted = 0
        self._total_rules_validated = 0
        self._total_mutations_proposed = 0
        self._total_mutations_applied = 0

        # Flywheel lock to prevent concurrent runs
        self._flywheel_lock = asyncio.Lock()

    async def on_initialize(self) -> None:
        """Initialize the flywheel pipeline components."""
        logger.info("🔄 Flywheel Orchestrator initializing...")

        await self._init_pipeline_components()

        logger.info(
            "🔄 Flywheel Orchestrator ready: "
            "shadow=%s, validator=%s, mutator=%s, geneticist=%s, "
            "post_training=%s, batch_size=%d, cooldown=%ds",
            self._shadow_extractor is not None,
            self._rule_validator is not None,
            self._genome_mutator is not None,
            self._strategy_geneticist is not None,
            self._post_training_pipeline is not None,
            self.BATCH_SIZE,
            self.COOLDOWN_SECONDS,
        )

    async def _init_pipeline_components(self) -> None:
        """Initialize all flywheel pipeline components.

        Includes the standard EXTRACT→VALIDATE→MUTATE→EVOLVE pipeline
        plus the post-training pipeline (LoRA fine-tuning).
        """
        shadow_config = self.config.get("shadow_extractor", {})
        if not shadow_config.get("enabled", False):
            logger.info("Flywheel: shadow_extractor disabled in config")
            return

        try:
            from src.interfaces import get_exchange_gateway, get_llm_provider
            from src.knowledge.genome_mutator import GenomeMutator, MutatorConfig
            from src.knowledge.ohlcv_adapter import ExchangeGatewayOHLCVAdapter
            from src.knowledge.rule_validator import RuleValidator
            from src.knowledge.shadow_extractor import ShadowExtractor
            from src.knowledge.strategy_genomes import StrategyGenomes
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

            # Genome mutator
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

            # Strategy Geneticist (wire mutations back to strategy params)
            from src.agents.strategy_geneticist import StrategyGeneticist

            self._strategy_geneticist = StrategyGeneticist(
                config=self.config,
                trading_mode=self.trading_mode,
                ohlcv_provider=ohlcv_adapter,
            )

            # ── Post-Training Pipeline (LoRA fine-tuning) ─────
            # This is the missing piece: "improve the AI model inside the harness"
            post_training_cfg = self.config.get("post_training", {})
            if post_training_cfg.get("enabled", True):
                try:
                    from src.knowledge.lesson_archive import LessonArchive
                    from src.knowledge.pattern_library import PatternLibrary
                    from src.llm.post_training import PostTrainingPipeline

                    lesson_archive = LessonArchive(db_path)
                    pattern_library = PatternLibrary(db_path)

                    self._post_training_pipeline = PostTrainingPipeline(
                        trade_memory=trade_memory,
                        lesson_archive=lesson_archive,
                        pattern_library=pattern_library,
                        config=post_training_cfg,
                    )
                    logger.info("🔄 Post-training pipeline initialized")
                except Exception as pt_err:
                    logger.warning("Post-training pipeline init failed: %s", pt_err)
                    self._post_training_pipeline = None

            logger.info("🔄 Flywheel pipeline components initialized")

        except Exception as e:
            logger.error("Failed to initialize flywheel pipeline: %s", e)
            self._shadow_extractor = None
            self._rule_validator = None
            self._genome_mutator = None
            self._strategy_geneticist = None
            self._post_training_pipeline = None

    async def _on_trade_executed(self, data: dict[str, Any]) -> None:
        """Handle a trade execution event from the EventBus.

        Increments trade counters and triggers:
        - Flywheel (EXTRACT→VALIDATE→MUTATE→EVOLVE) every BATCH_SIZE trades
        - Post-training pipeline (GENERATE→TRAIN→EVALUATE→DEPLOY) every
          POST_TRAINING_BATCH_SIZE trades
        """
        self._trade_count += 1
        self._trades_since_flywheel += 1
        self._trades_since_post_training += 1

        logger.debug(
            "Flywheel: trade #%d recorded (since_flywheel=%d, since_post_training=%d)",
            self._trade_count,
            self._trades_since_flywheel,
            self._trades_since_post_training,
        )

        # Check if it's time to run the flywheel
        now = time.monotonic()
        cooldown_elapsed = (now - self._last_flywheel_run) >= self.COOLDOWN_SECONDS
        batch_ready = self._trades_since_flywheel >= self.BATCH_SIZE

        if batch_ready and cooldown_elapsed:
            # Run flywheel in background (don't block trade processing)
            asyncio.create_task(self._run_flywheel())

        # Check if it's time to run post-training
        pt_cooldown = (now - self._last_post_training_run) >= self.POST_TRAINING_COOLDOWN_S
        pt_batch_ready = self._trades_since_post_training >= self.POST_TRAINING_BATCH_SIZE

        if pt_batch_ready and pt_cooldown and self._post_training_pipeline:
            asyncio.create_task(self._run_post_training())

    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        """Handle events from subscribed streams (trades, fills).

        Routes trade execution events to the flywheel's trade handler.
        """
        if stream in ("trades", "fills") and event.type in (
            "tsar.trade.executed.v1",
            "tsar.trade.recorded.v1",
        ):
            await self._on_trade_executed(event.data)

    async def run_cycle(self) -> None:
        """Main flywheel orchestrator cycle.

        Monitors trade count and triggers flywheel on schedule.
        Also publishes health metrics and post-training status.
        """
        # The flywheel is event-driven via _on_trade_executed.
        # This cycle handles periodic health checks and metric logging.
        if self._flywheel_runs > 0 and self._flywheel_runs % 5 == 0:
            logger.info(
                "🔄 Flywheel health: runs=%d, rules_extracted=%d, "
                "rules_validated=%d, mutations_proposed=%d, mutations_applied=%d, "
                "post_training_runs=%d, post_training_deployments=%d, "
                "total_trades=%d",
                self._flywheel_runs,
                self._total_rules_extracted,
                self._total_rules_validated,
                self._total_mutations_proposed,
                self._total_mutations_applied,
                self._post_training_runs,
                self._post_training_deployments,
                self._trade_count,
            )

    async def _run_flywheel(self) -> None:
        """Execute the full flywheel pipeline.

        Pipeline: ShadowExtractor → RuleValidator → GenomeMutator → StrategyGeneticist

        This is the core of the self-improvement loop. Each step feeds
        into the next, and failures at any step are logged but don't
        crash the system.
        """
        async with self._flywheel_lock:
            self._last_flywheel_run = time.monotonic()
            self._trades_since_flywheel = 0
            self._flywheel_runs += 1

            run_id = self._flywheel_runs
            logger.info(
                "🔄 ═══ FLYWHEEL RUN #%d STARTING (trade_count=%d) ═══",
                run_id,
                self._trade_count,
            )

            try:
                await self._publish_flywheel_event(
                    "flywheel.cycle_started",
                    {
                        "run_id": run_id,
                        "trade_count": self._trade_count,
                    },
                )

                # ── Step 1: EXTRACT — ShadowExtractor ──────────
                rules = await self._step_extract(run_id)
                if not rules:
                    logger.info("🔄 Flywheel #%d: no rules extracted, cycle complete", run_id)
                    await self._publish_flywheel_event(
                        "flywheel.cycle_complete",
                        {
                            "run_id": run_id,
                            "outcome": "no_rules",
                        },
                    )
                    return

                # ── Step 2: VALIDATE — RuleValidator ───────────
                validated = await self._step_validate(run_id, rules)
                if not validated:
                    logger.info("🔄 Flywheel #%d: no rules validated, cycle complete", run_id)
                    await self._publish_flywheel_event(
                        "flywheel.cycle_complete",
                        {
                            "run_id": run_id,
                            "outcome": "no_validated_rules",
                        },
                    )
                    return

                # ── Step 3: MUTATE — GenomeMutator ─────────────
                proposals = await self._step_mutate(run_id, validated)

                # ── Step 4: EVOLVE — StrategyGeneticist ────────
                applied = await self._step_evolve(run_id, proposals)

                logger.info(
                    "🔄 ═══ FLYWHEEL RUN #%d COMPLETE: "
                    "%d rules → %d validated → %d proposals → %d applied ═══",
                    run_id,
                    len(rules),
                    len(validated),
                    len(proposals),
                    applied,
                )

                await self._publish_flywheel_event(
                    "flywheel.cycle_complete",
                    {
                        "run_id": run_id,
                        "rules_extracted": len(rules),
                        "rules_validated": len(validated),
                        "mutations_proposed": len(proposals),
                        "mutations_applied": applied,
                        "outcome": "success",
                    },
                )

                # ── Step 5: FINE-TUNE — PostTrainingPipeline ──
                # After the rule extraction cycle, check if it's time
                # to fine-tune the LLM from accumulated trade data.
                await self._maybe_run_post_training(run_id)

            except Exception as e:
                logger.error("🔄 Flywheel #%d failed: %s", run_id, e)
                await self._publish_flywheel_event(
                    "flywheel.cycle_error",
                    {
                        "run_id": run_id,
                        "error": str(e),
                    },
                )

    async def _step_extract(self, run_id: int) -> list[Any]:
        """Step 1: Extract rules from trade history via ShadowExtractor."""
        if not self._shadow_extractor:
            logger.warning("Flywheel #%d: ShadowExtractor not available", run_id)
            return []

        logger.info("🔄 Flywheel #%d — Step 1: EXTRACT", run_id)
        try:
            shadow_config = self.config.get("shadow_extractor", {})
            extraction = await self._shadow_extractor.extract(
                min_trades=shadow_config.get("min_trades", self.MIN_TRADES_FOR_EXTRACTION),
                min_win_rate=shadow_config.get("min_win_rate", 0.55),
                lookback_days=shadow_config.get("lookback_days", 90),
            )

            self._total_rules_extracted += len(extraction.rules)
            logger.info(
                "🔄 Flywheel #%d — EXTRACT: %d rules from %d trades (%d winners, %d losers)",
                run_id,
                len(extraction.rules),
                extraction.source_trade_count,
                extraction.winning_trade_count,
                extraction.losing_trade_count,
            )
            return extraction.rules

        except Exception as e:
            logger.error("Flywheel #%d extract step failed: %s", run_id, e)
            return []

    async def _step_validate(self, run_id: int, rules: list[Any]) -> list[Any]:
        """Step 2: Validate rules via RuleValidator (OHLCV backtest)."""
        if not self._rule_validator:
            logger.warning("Flywheel #%d: RuleValidator not available", run_id)
            return []

        logger.info("🔄 Flywheel #%d — Step 2: VALIDATE (%d rules)", run_id, len(rules))
        try:
            shadow_config = self.config.get("shadow_extractor", {})
            timeframe = shadow_config.get("timeframe", "1h")
            lookback = shadow_config.get("lookback_candles", 500)

            validated = await self._rule_validator.validate_batch(
                rules,
                timeframe=timeframe,
                lookback_candles=lookback,
            )
            passed = [r for r in validated if r.validation_status == "passed"]
            self._total_rules_validated += len(passed)

            logger.info(
                "🔄 Flywheel #%d — VALIDATE: %d/%d passed",
                run_id,
                len(passed),
                len(validated),
            )
            return passed

        except Exception as e:
            logger.error("Flywheel #%d validate step failed: %s", run_id, e)
            return []

    async def _step_mutate(self, run_id: int, validated_rules: list[Any]) -> list[Any]:
        """Step 3: Propose genome mutations via GenomeMutator."""
        if not self._genome_mutator:
            logger.warning("Flywheel #%d: GenomeMutator not available", run_id)
            return []

        logger.info(
            "🔄 Flywheel #%d — Step 3: MUTATE (%d validated rules)",
            run_id,
            len(validated_rules),
        )
        try:
            proposals = await self._genome_mutator.propose_mutations(validated_rules)
            self._total_mutations_proposed += len(proposals)

            logger.info(
                "🔄 Flywheel #%d — MUTATE: %d proposals",
                run_id,
                len(proposals),
            )
            return proposals

        except Exception as e:
            logger.error("Flywheel #%d mutate step failed: %s", run_id, e)
            return []

    async def _step_evolve(self, run_id: int, proposals: list[Any]) -> int:
        """Step 4: Apply mutations via StrategyGeneticist.

        The Geneticist evaluates each proposal and applies accepted ones
        to the strategy genomes.

        Returns:
            Number of mutations successfully applied.
        """
        if not self._strategy_geneticist:
            logger.warning("Flywheel #%d: StrategyGeneticist not available", run_id)
            return 0

        if not proposals:
            return 0

        logger.info(
            "🔄 Flywheel #%d — Step 4: EVOLVE (%d proposals)",
            run_id,
            len(proposals),
        )

        applied = 0
        for proposal in proposals:
            try:
                proposal_dict = proposal.to_dict() if hasattr(proposal, "to_dict") else proposal

                # Create a synthetic CloudEvent for the Geneticist
                event = CloudEvent(
                    source="tsar:agent:flywheel_orchestrator",
                    type="tsar.strategy.proposal.v1",
                    data=proposal_dict,
                )

                # Let the Geneticist evaluate and apply
                await self._strategy_geneticist.handle_event("strategy_proposals", event)
                applied += 1

                logger.info(
                    "🔄 Flywheel #%d — EVOLVE: proposal %s → sent to Geneticist",
                    run_id,
                    proposal_dict.get("proposal_id", "unknown"),
                )

            except Exception as e:
                logger.error(
                    "Flywheel #%d evolve step failed for proposal: %s",
                    run_id,
                    e,
                )

        self._total_mutations_applied += applied
        return applied

    # ── Post-Training Pipeline ─────────────────────────────────

    async def _run_post_training(self) -> None:
        """Execute the post-training pipeline.

        This is Jensen's "improve the AI model inside the harness" —
        the LLM learns from every trade, getting better over time.

        Pipeline: GENERATE dataset → TRAIN (LoRA) → EVALUATE → DEPLOY
        """
        if not self._post_training_pipeline:
            return

        self._last_post_training_run = time.monotonic()
        self._trades_since_post_training = 0
        self._post_training_runs += 1

        run_id = self._post_training_runs
        logger.info(
            "🧠 ═══ POST-TRAINING RUN #%d STARTING (trade_count=%d) ═══",
            run_id,
            self._trade_count,
        )

        try:
            await self._publish_flywheel_event(
                "post_training.started",
                {
                    "run_id": run_id,
                    "trade_count": self._trade_count,
                },
            )

            # Run the full pipeline in a thread (training is CPU/GPU intensive)
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                self._post_training_pipeline.run,
            )

            status = result.get("status", "unknown")
            if status == "deployed":
                self._post_training_deployments += 1
                logger.info(
                    "🧠 ═══ POST-TRAINING RUN #%d DEPLOYED: "
                    "improvement=%.1f%%, adapter=%s ═══",
                    run_id,
                    result.get("improvement_pct", 0),
                    result.get("adapter_path", "unknown"),
                )
            elif status == "rejected":
                logger.info(
                    "🧠 POST-TRAINING RUN #%d REJECTED: %s",
                    run_id,
                    result.get("reason", "insufficient improvement"),
                )
            elif status == "skipped":
                logger.info(
                    "🧠 POST-TRAINING RUN #%d SKIPPED: %s",
                    run_id,
                    result.get("reason", "insufficient data"),
                )
            else:
                logger.warning(
                    "🧠 POST-TRAINING RUN #%d status=%s: %s",
                    run_id,
                    status,
                    result.get("reason", ""),
                )

            await self._publish_flywheel_event(
                "post_training.complete",
                {
                    "run_id": run_id,
                    "status": status,
                    "improvement_pct": result.get("improvement_pct", 0),
                    "adapter_path": result.get("adapter_path", ""),
                    "reason": result.get("reason", ""),
                },
            )

        except Exception as e:
            logger.error("🧠 Post-training run #%d failed: %s", run_id, e)
            await self._publish_flywheel_event(
                "post_training.error",
                {
                    "run_id": run_id,
                    "error": str(e),
                },
            )

    async def _maybe_run_post_training(self, flywheel_run_id: int) -> None:
        """Check if post-training should run after a flywheel cycle.

        Post-training runs less frequently than the standard flywheel
        (every POST_TRAINING_BATCH_SIZE trades with cooldown).
        """
        if not self._post_training_pipeline:
            return

        now = time.monotonic()
        pt_cooldown = (now - self._last_post_training_run) >= self.POST_TRAINING_COOLDOWN_S
        pt_batch_ready = self._trades_since_post_training >= self.POST_TRAINING_BATCH_SIZE

        if pt_batch_ready and pt_cooldown:
            logger.info(
                "🧠 Post-training triggered after flywheel #%d "
                "(trades_since_pt=%d, cooldown_elapsed=%ds)",
                flywheel_run_id,
                self._trades_since_post_training,
                int(now - self._last_post_training_run),
            )
            asyncio.create_task(self._run_post_training())

    # ── Events & Health ────────────────────────────────────────

    async def _publish_flywheel_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish a flywheel lifecycle event."""
        try:
            await self.publish_event(
                stream="flywheel_events",
                event_type=event_type,
                data=data,
                priority=2,
            )
        except Exception:
            logger.debug("Flywheel event publish failed (non-critical)")

    def get_health(self) -> dict[str, Any]:
        """Get flywheel orchestrator health status."""
        base_health = super().get_health()

        # Post-training status
        post_training_status = None
        if self._post_training_pipeline:
            post_training_status = self._post_training_pipeline.get_status()

        base_health.update(
            {
                "flywheel": {
                    "runs": self._flywheel_runs,
                    "total_trades_processed": self._trade_count,
                    "trades_since_flywheel": self._trades_since_flywheel,
                    "total_rules_extracted": self._total_rules_extracted,
                    "total_rules_validated": self._total_rules_validated,
                    "total_mutations_proposed": self._total_mutations_proposed,
                    "total_mutations_applied": self._total_mutations_applied,
                    "pipeline_ready": all(
                        [
                            self._shadow_extractor,
                            self._rule_validator,
                            self._genome_mutator,
                            self._strategy_geneticist,
                        ]
                    ),
                    "batch_size": self.BATCH_SIZE,
                    "cooldown_s": self.COOLDOWN_SECONDS,
                },
                "post_training": {
                    "enabled": self._post_training_pipeline is not None,
                    "runs": self._post_training_runs,
                    "deployments": self._post_training_deployments,
                    "trades_since_post_training": self._trades_since_post_training,
                    "batch_size": self.POST_TRAINING_BATCH_SIZE,
                    "cooldown_s": self.POST_TRAINING_COOLDOWN_S,
                    "pipeline_status": post_training_status,
                },
            }
        )
        return base_health

    async def trigger_flywheel(self) -> None:
        """Manually trigger a flywheel run (for testing/debugging)."""
        logger.info("🔄 Manual flywheel trigger requested")
        asyncio.create_task(self._run_flywheel())

    async def trigger_post_training(self) -> None:
        """Manually trigger a post-training run (for testing/debugging)."""
        logger.info("🧠 Manual post-training trigger requested")
        asyncio.create_task(self._run_post_training())
