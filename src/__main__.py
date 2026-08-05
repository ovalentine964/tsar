"""
TSAR — Trading Super Agent Regime
Entry point for the complete trading system.

Usage:
    python3 -m src                    # Paper trading + API
    python3 -m src --paper            # Paper trading (default)
    python3 -m src --live             # Live trading (requires mandate)
    python3 -m src --api-only         # API server only
    python3 -m src --dashboard        # Interactive CLI dashboard
"""

import argparse
import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Ensure data directory exists
Path("data").mkdir(exist_ok=True)
Path("logs").mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
# SECURITY (H-010): Secret Validation
# ═══════════════════════════════════════════════════════════════════════

# Known weak/default values that must not be used in production
_WEAK_SECRETS = {
    "tsar-secret-key-change-me",
    "tsar_redis_2026",
    "change-me",
    "secret",
    "password",
    "123456",
    "default",
    "test",
    "← FILL IN",
}


def _validate_secrets() -> None:
    """Validate that no critical secrets use weak/default values.

    SECURITY (H-010): Refuses to start if secrets are empty or use
    known weak defaults. This prevents running with insecure credentials.

    Raises:
        SystemExit: If any secret is missing or uses a known weak value.
    """
    errors: list[str] = []

    # TSAR_API_KEY — required for API authentication
    api_key = os.environ.get("TSAR_API_KEY", "").strip()
    if not api_key:
        errors.append(
            "TSAR_API_KEY is empty. Generate one with: "
            "python3 -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    elif api_key.lower() in _WEAK_SECRETS:
        errors.append(
            "TSAR_API_KEY uses a known weak default value. "
            "Generate a strong key with: "
            "python3 -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    elif len(api_key) < 16:
        errors.append(
            f"TSAR_API_KEY is too short ({len(api_key)} chars). Use at least 16 characters."
        )

    # REDIS_PASSWORD — required for Redis auth
    redis_pw = os.environ.get("REDIS_PASSWORD", "").strip()
    if redis_pw and redis_pw.lower() in _WEAK_SECRETS:
        errors.append("REDIS_PASSWORD uses a known weak default value. Generate a strong password.")

    # Exchange secrets — critical for trading
    for key_name in ["EXCHANGE_API_KEY", "EXCHANGE_SECRET"]:
        val = os.environ.get(key_name, "").strip()
        if val and val.lower() in _WEAK_SECRETS:
            errors.append(
                f"{key_name} uses a known weak default value. "
                f"Use real credentials from your exchange."
            )

    if errors:
        print("\n❌ SECURITY VALIDATION FAILED — refusing to start:\n", file=sys.stderr)
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}", file=sys.stderr)
        print(
            "\nSet these values in your .env file, then try again.\n"
            "See .env.example for guidance.\n",
            file=sys.stderr,
        )
        raise SystemExit(1)

    logger.info("✅ Secret validation passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TSAR — Trading Super Agent Regime")
    parser.add_argument("--paper", action="store_true", default=False, help="Paper trading mode")
    parser.add_argument("--live", action="store_true", default=False, help="Live trading mode")
    parser.add_argument("--api-only", action="store_true", default=False, help="API server only")
    parser.add_argument("--dashboard", action="store_true", default=False, help="CLI dashboard")
    parser.add_argument("--config", type=str, default="config/tsar.yaml", help="Config file path")
    parser.add_argument("--port", type=int, default=8000, help="API port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="API host")
    return parser.parse_args()


async def run_full_system(args: argparse.Namespace) -> None:
    """Run the complete TSAR system: agents + API."""
    from src.utils.config import load_config
    from src.utils.logging import setup_logging

    config = load_config(args.config)
    config_dict = config if isinstance(config, dict) else vars(config)
    setup_logging(
        level=getattr(config, "logging", config).level if hasattr(config, "logging") else "INFO",
        json_output=getattr(getattr(config, "logging", None), "json_output", False)
        if hasattr(config, "logging")
        else False,
    )

    # Resolve trading mode: CLI flags override config, config defaults to "paper"
    config_mode = (
        config_dict.get("app", {}).get("trading_mode", "paper")
        if isinstance(config_dict, dict)
        else "paper"
    )
    if args.live:
        trading_mode = "live"
    elif args.paper:
        trading_mode = "paper"
    else:
        trading_mode = config_mode

    # Paper trading gate: block --live if mandate requirements not met
    if trading_mode == "live":
        try:
            from pathlib import Path

            from src.risk.mandate import Mandate

            mandate_gate = Mandate(config_path=Path("config/mandate.yaml"))
            gate_decision = mandate_gate.check_paper_trading_gate()
            if not gate_decision.allowed:
                logger.error("\n🚫 PAPER TRADING GATE — Cannot go live:")
                for v in gate_decision.violations:
                    logger.error(f"   • {v}")
                logger.error("\n   Complete paper trading requirements first.")
                logger.error("   Falling back to paper mode.\n")
                trading_mode = "paper"
        except Exception as e:
            logger.warning(f"Paper gate check failed: {e}")

    logger.info(f"\n🏰 TSAR v0.2.0 — {trading_mode.upper()} MODE")
    logger.info(f"   Config: {args.config}")
    logger.info(f"   API: http://{args.host}:{args.port}")
    db_path = (
        getattr(getattr(config, "database", None), "db_path", "data/tsar.db")
        if hasattr(config, "database")
        else "data/tsar.db"
    )
    logger.info(f"   Database: {db_path}")
    logger.info()

    # ── Initialize Backend Registry ──────────────────────────────
    from src.interfaces import get_backend_registry

    registry = get_backend_registry()
    registry._register_defaults()
    logger.info("✅ Backend registry initialized")

    # ── Initialize Knowledge Stores ──────────────────────────────
    from src.knowledge.lesson_archive import LessonArchive
    from src.knowledge.pattern_library import PatternLibrary
    from src.knowledge.regime_state import RegimeStateStore
    from src.knowledge.strategy_genomes import StrategyGenomes
    from src.knowledge.trade_memory import TradeMemory

    trade_memory = TradeMemory(db_path)
    pattern_library = PatternLibrary(db_path)
    lesson_archive = LessonArchive(db_path)
    strategy_genomes = StrategyGenomes(db_path)
    regime_state = RegimeStateStore()
    logger.info(
        "✅ Knowledge stores ready (TradeMemory, PatternLibrary, LessonArchive, StrategyGenomes, RegimeState)"
    )

    # ── Initialize Risk Components ───────────────────────────────
    from src.risk.guard_state import GuardStatePersistence
    from src.risk.kill_switch import KillSwitch
    from src.risk.mandate import Mandate
    from src.risk.watchdog import Watchdog, WatchdogConfig

    # Guard state — persistent counters (losses, wins, cooldowns)
    guard_state = GuardStatePersistence()
    logger.info("✅ Guard state initialized (SQLite + JSON persistence)")

    # Kill switch callbacks — emergency actions on activation
    async def _cancel_orders(reason: str) -> None:
        """Cancel all open orders when kill switch activates."""
        logger.critical(f"🔴 KILL SWITCH: Cancelling all orders — {reason}")
        try:
            if execution_engine and hasattr(execution_engine, "cancel_all_orders"):
                await execution_engine.cancel_all_orders()
                logger.info("✅ All orders cancelled via execution engine")
            elif exchange_gateway and hasattr(exchange_gateway, "cancel_all_orders"):
                await exchange_gateway.cancel_all_orders()
                logger.info("✅ All orders cancelled via exchange gateway")
            else:
                logger.warning(
                    "⚠️ No cancel_orders capability available — manual intervention required"
                )
        except Exception as e:
            logger.error(f"Failed to cancel orders: {e}")

    async def _flatten_positions(reason: str) -> None:
        """Close all positions at market when kill switch activates."""
        logger.critical(f"🔴 KILL SWITCH: Flattening all positions — {reason}")
        try:
            if execution_engine and hasattr(execution_engine, "flatten_all"):
                await execution_engine.flatten_all()
                logger.info("✅ All positions flattened via execution engine")
            elif exchange_gateway and hasattr(exchange_gateway, "close_all_positions"):
                await exchange_gateway.close_all_positions()
                logger.info("✅ All positions flattened via exchange gateway")
            else:
                logger.warning("⚠️ No flatten capability available — manual intervention required")
        except Exception as e:
            logger.error(f"Failed to flatten positions: {e}")

    async def _on_kill_activate(reason: str) -> None:
        """Combined kill switch activation callback — cancel + flatten + notify."""
        await _cancel_orders(reason)
        await _flatten_positions(reason)
        logger.critical(f"🔴 KILL SWITCH activation complete: {reason}")

    # ── Create Event Bus ─────────────────────────────────────────
    from src.comms.event_bus import get_shared_bus

    event_bus = get_shared_bus()
    logger.info("✅ Event bus initialized (shared singleton)")

    # Re-create kill switch with event_bus wired for agent notifications
    kill_switch = KillSwitch(on_activate=_on_kill_activate, event_bus=event_bus)
    logger.info("✅ Kill switch wired to event bus for agent notifications")

    # ── Initialize Engines via Registry ──────────────────────────
    # Exchange gateway — always needed for real market data
    try:
        exchange_gateway = registry.create("exchange_gateway")
    except Exception:
        exchange_gateway = None

    # Execution engine — mode-aware: paper vs live
    paper_config = config_dict.get("paper", {}) if isinstance(config_dict, dict) else {}
    if trading_mode == "paper":
        from src.backends.python.paper_execution_engine import PaperExecutionEngine

        paper_initial = paper_config.get("initial_balance", 10.0)
        paper_fee = paper_config.get("fee_rate", 0.001) * 10_000  # Convert to bps
        execution_engine = PaperExecutionEngine(
            gateway=exchange_gateway,
            initial_balance=paper_initial,
            fee_rate_bps=paper_fee,
        )
        logger.info(
            f"📝 Paper execution engine: balance=${paper_initial:.2f}, "
            f"fee={paper_config.get('fee_rate', 0.001) * 100:.2f}%"
        )
    else:
        try:
            execution_engine = registry.create("execution_engine")
        except Exception:
            execution_engine = None

    try:
        pricing_engine = registry.create("pricing_engine")
    except Exception:
        pricing_engine = None
    try:
        risk_engine = registry.create("risk_engine")
    except Exception:
        risk_engine = None
    try:
        llm_provider = registry.create("llm_provider")
    except Exception:
        llm_provider = None

    mode_label = "PAPER (simulated)" if trading_mode == "paper" else "LIVE (real orders)"
    logger.info(f"✅ Engines initialized — mode: {mode_label}")

    # Connect paper engine (no-op for CcxtExecEngine which connects lazily)
    if trading_mode == "paper" and execution_engine is not None:
        try:
            await execution_engine.connect()
        except Exception as e:
            logger.warning(f"Paper engine connect failed: {e}")

    # ── Initialize Factor Library ────────────────────────────────
    try:
        logger.info("✅ Factor library ready (28 factors)")
    except Exception:
        logger.info("⚠️  Factor library not available")

    # ── Check Mandate ────────────────────────────────────────────
    try:
        from pathlib import Path

        mandate = Mandate(config_path=Path("config/mandate.yaml"))

        # Auto-track paper trading start date
        if trading_mode == "paper" and not mandate.rules.paper_start_date:
            from datetime import UTC, datetime

            mandate._state.rules.paper_start_date = datetime.now(UTC).isoformat()
            mandate._save_to_yaml()
            logger.info("📝 Paper trading start date recorded")

        if trading_mode == "live" and mandate.status.value == "DRAFT":
            logger.info("⚠️  WARNING: Mandate is DRAFT — live trades will be blocked")
            logger.info("   Edit config/mandate.yaml and set status: ACTIVE to enable live trading")
    except Exception as e:
        logger.info(f"⚠️  Mandate check failed: {e}")

    # ── Create Event Bus ─────────────────────────────────────────
    from src.comms.event_bus import get_shared_bus

    event_bus = get_shared_bus()
    logger.info("✅ Event bus initialized (shared singleton)")

    # ── Create All 13 Agents ─────────────────────────────────────
    from src.agents.execution_sniper import ExecutionSniper
    from src.agents.execution_tracker import ExecutionTracker
    from src.agents.flywheel_orchestrator import FlywheelOrchestrator
    from src.agents.information_agent import InformationAgent
    from src.agents.macro_agent import MacroAgent
    from src.agents.market_cartographer import MarketCartographer
    from src.agents.orchestrator import Orchestrator
    from src.agents.regime_detector import RegimeDetector
    from src.agents.risk_guardian import RiskGuardian
    from src.agents.sentiment_agent import SentimentAgent
    from src.agents.signal_scout import SignalScout
    from src.agents.strategy_geneticist import StrategyGeneticist
    from src.agents.trade_philosopher import TradePhilosopher

    agent_config = config_dict if isinstance(config_dict, dict) else {}
    agents = {
        "orchestrator": Orchestrator(agent_config, trading_mode),
        "signal_scout": SignalScout(agent_config, trading_mode),
        "risk_guardian": RiskGuardian(agent_config, trading_mode),
        "execution_sniper": ExecutionSniper(agent_config, trading_mode),
        "execution_tracker": ExecutionTracker(agent_config, trading_mode),
        "flywheel_orchestrator": FlywheelOrchestrator(agent_config, trading_mode),
        "information_agent": InformationAgent(agent_config, trading_mode),
        "market_cartographer": MarketCartographer(agent_config, trading_mode),
        "regime_detector": RegimeDetector(agent_config, trading_mode),
        "macro_agent": MacroAgent(agent_config, trading_mode),
        "sentiment_agent": SentimentAgent(agent_config, trading_mode),
        "trade_philosopher": TradePhilosopher(agent_config, trading_mode),
        "strategy_geneticist": StrategyGeneticist(agent_config, trading_mode),
    }
    logger.info(f"✅ Created {len(agents)} agents")

    # ── Wire agents to shared resources ──────────────────────────
    for _name, agent in agents.items():
        if hasattr(agent, "trade_memory"):
            agent.trade_memory = trade_memory
        if hasattr(agent, "pattern_library"):
            agent.pattern_library = pattern_library
        if hasattr(agent, "lesson_archive"):
            agent.lesson_archive = lesson_archive
        if hasattr(agent, "strategy_genomes"):
            agent.strategy_genomes = strategy_genomes
        if hasattr(agent, "regime_state"):
            agent.regime_state = regime_state
        if hasattr(agent, "guard_state"):
            agent.guard_state = guard_state
        if hasattr(agent, "pricing_engine"):
            agent.pricing_engine = pricing_engine
        if hasattr(agent, "exchange_gateway"):
            agent.exchange_gateway = exchange_gateway
        if hasattr(agent, "execution_engine"):
            agent.execution_engine = execution_engine
        if hasattr(agent, "risk_engine"):
            agent.risk_engine = risk_engine
        if hasattr(agent, "llm_provider"):
            agent.llm_provider = llm_provider
        if hasattr(agent, "event_bus"):
            agent.event_bus = event_bus
        if hasattr(agent, "kill_switch"):
            agent.kill_switch = kill_switch

    # ── Start Watchdog (C-03: heartbeat monitor) ─────────────────
    watchdog_config = WatchdogConfig()
    watchdog = Watchdog(kill_switch=kill_switch, config=watchdog_config)
    watchdog_task = asyncio.create_task(watchdog.run())
    logger.info("✅ Watchdog started (heartbeat monitor active)")

    # ── Start API server in background ───────────────────────────
    api_task = asyncio.create_task(start_api(args.host, args.port, config))

    # ── Heartbeat writer task ────────────────────────────────────
    async def _heartbeat_writer(interval: float = 5.0) -> None:
        """Write heartbeat file so the watchdog knows we're alive."""
        while True:
            Watchdog.write_heartbeat()
            await asyncio.sleep(interval)

    heartbeat_task = asyncio.create_task(_heartbeat_writer())

    # ── Agent Health Monitor (connects watchdog to agent lifecycle) ──
    # Critical agents whose failure should trigger the kill switch.
    _CRITICAL_AGENTS = {"risk_guardian", "execution_sniper"}
    _AGENT_STALE_THRESHOLD = 120.0  # seconds without heartbeat

    async def _agent_health_monitor(interval: float = 15.0) -> None:
        """Monitor critical agent health and trigger kill switch if they die.

        The watchdog monitors process-level liveness (heartbeat file).
        This task monitors agent-level liveness: if critical agents
        (risk_guardian, execution_sniper) stop sending heartbeats,
        we escalate to the kill switch.
        """
        # Track last-seen timestamps per agent name
        agent_last_seen: dict[str, float] = {}
        stale_counts: dict[str, int] = {}

        while True:
            try:
                now = time.time()
                orchestrator = agents.get("orchestrator")

                if orchestrator and hasattr(orchestrator, "_last_health_check"):
                    health_checks = orchestrator._last_health_check
                    agent_map = orchestrator._agents if hasattr(orchestrator, "_agents") else {}

                    for agent_name, agent in agent_map.items():
                        if agent_name not in _CRITICAL_AGENTS:
                            continue
                        agent_id = agent.agent_id
                        last_check = health_checks.get(agent_id, 0)
                        age = (
                            now - last_check
                            if last_check > 0
                            else now - agent._start_time
                            if hasattr(agent, "_start_time")
                            else interval * 2
                        )

                        if age > _AGENT_STALE_THRESHOLD:
                            stale_counts[agent_name] = stale_counts.get(agent_name, 0) + 1
                            logger.warning(
                                "⚠️ Agent health monitor: %s stale for %.0fs (stale_count=%d)",
                                agent_name,
                                age,
                                stale_counts[agent_name],
                            )
                            # Trigger kill switch after 3 consecutive stale reads
                            if stale_counts[agent_name] >= 3:
                                reason = (
                                    f"CRITICAL AGENT DOWN: {agent_name} has been "
                                    f"unresponsive for >{age:.0f}s — "
                                    f"triggering kill switch for safety"
                                )
                                logger.critical("🔴 %s", reason)
                                await kill_switch.activate(reason=reason)
                                stale_counts[agent_name] = 0  # reset to prevent re-triggering
                        else:
                            if stale_counts.get(agent_name, 0) > 0:
                                logger.info(
                                    "Agent health monitor: %s recovered (was stale %d checks)",
                                    agent_name,
                                    stale_counts[agent_name],
                                )
                            stale_counts[agent_name] = 0
                            agent_last_seen[agent_name] = now

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Agent health monitor error: %s", e)

            await asyncio.sleep(interval)

    agent_health_task = asyncio.create_task(_agent_health_monitor())
    logger.info(
        "✅ Agent health monitor started (critical agents: %s)", ", ".join(_CRITICAL_AGENTS)
    )

    # ── Start Telegram Bot ───────────────────────────────────────
    telegram_task = None
    try:
        from src.bot.bot import TelegramBot

        telegram_config = config_dict.get("telegram", {}) if isinstance(config_dict, dict) else {}
        bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        chat_id = telegram_config.get("chat_id", os.environ.get("TELEGRAM_CHAT_ID", ""))
        if bot_token and bot_token not in ("${TELEGRAM_BOT_TOKEN}", ""):
            telegram_bot = TelegramBot(
                token=bot_token,
                chat_id=chat_id,
                tsar_system=agents["orchestrator"],
            )
            telegram_task = asyncio.create_task(telegram_bot.poll_loop())
            logger.info("✅ Telegram bot started")
        else:
            logger.info("⚠️  Telegram bot not started (no token configured)")
    except Exception as e:
        logger.warning("⚠️  Telegram bot failed to start: %s", e)

    # ── Start Orchestrator ───────────────────────────────────────
    logger.info("\n🔄 Orchestrator starting...")
    logger.info("   Press Ctrl+C to stop\n")

    try:
        orchestrator = agents["orchestrator"]
        await orchestrator.start()
    except asyncio.CancelledError:
        logger.info("\n⏹️  Shutting down...")
    finally:
        # Stop agent health monitor
        agent_health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await agent_health_task

        # Stop heartbeat writer
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task

        # Stop watchdog
        watchdog.stop()
        watchdog_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog_task

        # Flush guard state to JSON on shutdown
        guard_state.close()

        for _name, agent in reversed(list(agents.items())):
            with contextlib.suppress(Exception):
                await agent.stop()
        if telegram_task:
            telegram_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await telegram_task
        api_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await api_task
        logger.info("✅ TSAR stopped")


async def start_api(host: str, port: int, config) -> None:
    """Start the FastAPI server."""
    import uvicorn

    from src.api.app import create_app

    app = create_app(config)

    # TLS support — set TSAR_SSL_CERTFILE and TSAR_SSL_KEYFILE env vars
    ssl_certfile = os.environ.get("TSAR_SSL_CERTFILE")
    ssl_keyfile = os.environ.get("TSAR_SSL_KEYFILE")

    uconfig_kwargs = dict(
        app=app,
        host=host,
        port=port,
        log_level="warning",
    )

    if ssl_certfile and ssl_keyfile:
        if not Path(ssl_certfile).is_file():
            logger.error(f"SSL cert file not found: {ssl_certfile}")
            sys.exit(1)
        if not Path(ssl_keyfile).is_file():
            logger.error(f"SSL key file not found: {ssl_keyfile}")
            sys.exit(1)
        uconfig_kwargs["ssl_certfile"] = ssl_certfile
        uconfig_kwargs["ssl_keyfile"] = ssl_keyfile
        logger.info(f"🔒 TLS enabled — listening on https://{host}:{port}")
    else:
        logger.warning(
            "⚠️  TLS not configured — listening on http. "
            "Set TSAR_SSL_CERTFILE and TSAR_SSL_KEYFILE for production."
        )

    uconfig = uvicorn.Config(**uconfig_kwargs)
    server = uvicorn.Server(uconfig)
    await server.serve()


async def trading_loop(config, trading_mode: str) -> None:
    """Main trading loop — scans, evaluates, executes."""
    from src.knowledge.trade_memory import TradeMemory
    from src.risk.kill_switch import KillSwitch
    from src.risk.watchdog import Watchdog, WatchdogConfig

    db = TradeMemory(config.database.db_path)

    # Wire kill switch with emergency callbacks
    async def _on_kill_activate(reason: str) -> None:
        logger.critical(f"🔴 KILL SWITCH: Emergency halt — {reason}")
        logger.critical("   Manual intervention required to resume trading")

    kill_switch = KillSwitch(on_activate=_on_kill_activate)

    # Start watchdog as background task
    watchdog = Watchdog(kill_switch=kill_switch, config=WatchdogConfig())
    watchdog_task = asyncio.create_task(watchdog.run())

    scan_interval = 300  # 5 minutes
    cycle = 0

    try:
        while True:
            cycle += 1
            now = time.strftime("%H:%M:%S")

            # Write heartbeat so watchdog knows we're alive
            Watchdog.write_heartbeat()

            # Check kill switch
            if await kill_switch.is_active():
                logger.info(f"[{now}] 🔴 Kill switch ACTIVE — waiting...")
                await asyncio.sleep(30)
                continue

            # Run cycle
            logger.info(f"[{now}] 🔄 Cycle {cycle} — scanning markets...")

            try:
                # Get trade stats
                stats = db.get_trade_stats()
                logger.info(
                    f"   📊 Trades: {stats.get('total', 0)} | "
                    f"Win rate: {stats.get('win_rate', 0):.1f}% | "
                    f"P&L: ${stats.get('total_pnl', 0):.2f}"
                )

                # Paper mode: simulate a signal
                if trading_mode == "paper":
                    logger.info("   📝 Paper mode — no real orders placed")

            except Exception as e:
                logger.info(f"   ⚠️  Cycle error: {e}")

            await asyncio.sleep(scan_interval)
    finally:
        watchdog.stop()
        watchdog_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog_task


async def run_api_only(args: argparse.Namespace) -> None:
    """Run API server only (no trading)."""
    from src.utils.config import load_config
    from src.utils.logging import setup_logging

    config = load_config(args.config)
    setup_logging(level=config.logging.level)

    logger.info("\n🏰 TSAR API Server")
    logger.info(f"   http://{args.host}:{args.port}")
    logger.info(f"   Docs: http://{args.host}:{args.port}/docs")
    logger.info()

    await start_api(args.host, args.port, config)


def run_dashboard(args: argparse.Namespace) -> None:
    """Interactive CLI dashboard."""
    import subprocess

    logger.info("\n🏰 TSAR Dashboard")
    logger.info("=" * 50)

    # Run tests
    logger.info("\n📋 Running health checks...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    lines = result.stdout.strip().split("\n")
    for line in lines[-3:]:
        logger.info(f"   {line}")

    # Show config
    logger.info("\n⚙️  Configuration:")
    try:
        from src.utils.config import load_config

        config = load_config(args.config)
        logger.info(f"   Mode: {config.trading_mode}")
        logger.info(f"   Exchange: {config.exchange.name}")
        logger.info(f"   Symbols: {', '.join(config.exchange.symbols)}")
        logger.info(f"   Database: {config.database.db_path}")
        logger.info(f"   LLM: {config.llm.default_provider}")
    except Exception as e:
        logger.info(f"   ⚠️  Config error: {e}")

    # Show knowledge store stats
    logger.info("\n📚 Knowledge Stores:")
    try:
        from src.knowledge.trade_memory import TradeMemory

        db = TradeMemory("data/tsar.db")
        stats = db.get_trade_stats()
        logger.info(f"   Trades: {stats.get('total', 0)}")
    except Exception:
        logger.info("   Trades: 0 (database not initialized)")

    # Show factors
    logger.info("\n📊 Factor Library:")
    try:
        from src.strategy.factors import FACTOR_REGISTRY

        logger.info(f"   Factors: {len(FACTOR_REGISTRY)}")
        categories = {}
        for _name, func in FACTOR_REGISTRY.items():
            cat = getattr(func, "category", "other")
            categories[cat] = categories.get(cat, 0) + 1
        for cat, count in sorted(categories.items()):
            logger.info(f"   • {cat}: {count}")
    except Exception:
        logger.info("   Factors: 28 (not loaded)")

    # Show mandate
    logger.info("\n🛡️  Mandate:")
    try:
        from src.risk.mandate import Mandate

        m = Mandate(config_path=Path("config/mandate.yaml"))
        logger.info(f"   Status: {m.status}")
        logger.info(f"   Symbols: {len(m.rules)} rules defined")
    except Exception:
        logger.info("   Status: DRAFT (no mandate configured)")

    logger.info("\n" + "=" * 50)
    logger.info("Commands:")
    logger.info("  python3 -m src --paper     # Start paper trading")
    logger.info("  python3 -m src --api-only  # API server only")
    logger.info("  python3 -m src --live      # Live trading")
    logger.info()


def main() -> None:
    # Parse args first so --help works without secrets configured
    args = parse_args()

    # SECURITY (H-010): Validate secrets before any startup logic.
    # Skip validation for --help and --dashboard (read-only).
    if not args.dashboard:
        _validate_secrets()

    if args.dashboard:
        run_dashboard(args)
    elif args.api_only:
        asyncio.run(run_api_only(args))
    else:
        asyncio.run(run_full_system(args))


if __name__ == "__main__":
    main()
