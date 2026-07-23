"""
TSAR entry point.

Usage:
    python -m src              # Start the trading system
    python -m src --paper      # Paper trading mode (default)
    python -m src --live       # Live trading mode
    python -m src --api-only   # Start API server only
"""

import asyncio
import argparse
import sys

from src.utils.config import load_config
from src.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TSAR — Trading Super Agent Regime"
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        default=True,
        help="Run in paper trading mode (default)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live trading mode",
    )
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="Start API server without agents",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/default.yaml",
        help="Path to config file",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    setup_logging(config.get("logging", {}))

    trading_mode = "live" if args.live else "paper"
    print(f"🏰 TSAR v0.1.0 starting in {trading_mode} mode")

    if args.api_only:
        from src.api.app import create_app
        import uvicorn

        app = create_app(config)
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        from src.agents.orchestrator import Orchestrator

        orchestrator = Orchestrator(config=config, trading_mode=trading_mode)
        await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
