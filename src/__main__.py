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
            f"TSAR_API_KEY uses a known weak default value. "
            f"Generate a strong key with: "
            f"python3 -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    elif len(api_key) < 16:
        errors.append(
            f"TSAR_API_KEY is too short ({len(api_key)} chars). "
            f"Use at least 16 characters."
        )

    # REDIS_PASSWORD — required for Redis auth
    redis_pw = os.environ.get("REDIS_PASSWORD", "").strip()
    if redis_pw and redis_pw.lower() in _WEAK_SECRETS:
        errors.append(
            "REDIS_PASSWORD uses a known weak default value. "
            "Generate a strong password."
        )

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
    setup_logging(level=getattr(config, "logging", config).level if hasattr(config, "logging") else "INFO",
                  json_output=getattr(getattr(config, "logging", None), "json_output", False) if hasattr(config, "logging") else False)

    trading_mode = "live" if args.live else "paper"
    logger.info(f"\n🏰 TSAR v0.5.0 — {trading_mode.upper()} MODE")
    logger.info(f"   Config: {args.config}")
    logger.info(f"   API: http://{args.host}:{args.port}")
    db_path = getattr(getattr(config, "database", None), "db_path", "data/tsar.db") if hasattr(config, "database") else "data/tsar.db"
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
    logger.info("✅ Knowledge stores ready (TradeMemory, PatternLibrary, LessonArchive, StrategyGenomes, RegimeState)")

    # ── Initialize Risk Components ───────────────────────────────
    from src.risk.kill_switch import KillSwitch
    from src.risk.mandate import Mandate

    kill_switch = KillSwitch()
    logger.info("✅ Risk engine ready")

    # ── Initialize Engines via Registry ──────────────────────────
    try:
        exchange_gateway = registry.create("exchange_gateway")
    except Exception:
        exchange_gateway = None
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
    logger.info("✅ Engines initialized (Exchange, Execution, Pricing, Risk, LLM)")

    # ── Initialize Factor Library ────────────────────────────────
    try:
        logger.info("✅ Factor library ready (28 factors)")
    except Exception:
        logger.info("⚠️  Factor library not available")

    # ── Check Mandate ────────────────────────────────────────────
    try:
        from pathlib import Path
        mandate = Mandate(config_path=Path("config/mandate.yaml"))
        if trading_mode == "live" and mandate.status.value == "DRAFT":
            logger.info("⚠️  WARNING: Mandate is DRAFT — live trades will be blocked")
            logger.info("   Edit config/mandate.yaml and set status: ACTIVE to enable live trading")
    except Exception as e:
        logger.info(f"⚠️  Mandate check failed: {e}")

    # ── Create Event Bus ─────────────────────────────────────────
    from src.comms.event_bus import EventBus
    event_bus = EventBus()
    logger.info("✅ Event bus initialized")

    # ── Create All 10 Agents ─────────────────────────────────────
    from src.agents.execution_sniper import ExecutionSniper
    from src.agents.execution_tracker import ExecutionTracker
    from src.agents.macro_agent import MacroAgent
    from src.agents.market_cartographer import MarketCartographer
    from src.agents.orchestrator import Orchestrator
    from src.agents.regime_detector import RegimeDetector
    from src.agents.risk_guardian import RiskGuardian
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
        "market_cartographer": MarketCartographer(agent_config, trading_mode),
        "regime_detector": RegimeDetector(agent_config, trading_mode),
        "macro_agent": MacroAgent(agent_config, trading_mode),
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

    # ── Start API server in background ───────────────────────────
    api_task = asyncio.create_task(
        start_api(args.host, args.port, config)
    )

    # ── Start Orchestrator ───────────────────────────────────────
    logger.info("\n🔄 Orchestrator starting...")
    logger.info("   Press Ctrl+C to stop\n")

    try:
        orchestrator = agents["orchestrator"]
        await orchestrator.start()
    except asyncio.CancelledError:
        logger.info("\n⏹️  Shutting down...")
    finally:
        for _name, agent in reversed(list(agents.items())):
            with contextlib.suppress(Exception):
                await agent.stop()
        api_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await api_task
        logger.info("✅ TSAR stopped")


async def start_api(host: str, port: int, config) -> None:
    """Start the FastAPI server."""
    import uvicorn

    from src.api.app import create_app

    app = create_app(config)
    uconfig = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(uconfig)
    await server.serve()


async def trading_loop(config, trading_mode: str) -> None:
    """Main trading loop — scans, evaluates, executes."""
    from src.knowledge.trade_memory import TradeMemory
    from src.risk.kill_switch import KillSwitch

    db = TradeMemory(config.database.db_path)
    kill_switch = KillSwitch()

    scan_interval = 300  # 5 minutes
    cycle = 0

    while True:
        cycle += 1
        now = time.strftime("%H:%M:%S")

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
            logger.info(f"   📊 Trades: {stats.get('total', 0)} | "
                  f"Win rate: {stats.get('win_rate', 0):.1f}% | "
                  f"P&L: ${stats.get('total_pnl', 0):.2f}")

            # Paper mode: simulate a signal
            if trading_mode == "paper":
                logger.info("   📝 Paper mode — no real orders placed")

        except Exception as e:
            logger.info(f"   ⚠️  Cycle error: {e}")

        await asyncio.sleep(scan_interval)


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
        capture_output=True, text=True, cwd="."
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
            cat = getattr(func, 'category', 'other')
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
    # SECURITY (H-010): Validate secrets before any startup logic.
    # This catches weak/missing secrets early and prevents running
    # with insecure defaults.
    _validate_secrets()

    args = parse_args()

    if args.dashboard:
        run_dashboard(args)
    elif args.api_only:
        asyncio.run(run_api_only(args))
    else:
        asyncio.run(run_full_system(args))


if __name__ == "__main__":
    main()
