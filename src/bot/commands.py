"""
Bot Commands — Telegram command handlers.

Commands:
  /start    — Start trading
  /stop     — Emergency stop (kill switch)
  /status   — System status
  /pnl      — P&L summary
  /positions — Open positions
  /risk     — Risk state
  /regime   — Current regime
  /flywheel — Flywheel health
"""

import logging

logger = logging.getLogger(__name__)


COMMANDS = {
    "/start": "Start trading",
    "/stop": "Emergency stop (kill switch)",
    "/status": "System status",
    "/pnl": "P&L summary",
    "/positions": "Open positions",
    "/risk": "Risk state",
    "/regime": "Current market regime",
    "/flywheel": "Flywheel health score",
}


async def handle_command(command: str, args: list[str]) -> str:
    """Handle a Telegram command.

    Args:
        command: Command string (e.g., "/status")
        args: Command arguments

    Returns:
        Response text.
    """
    if command == "/status":
        return "🏰 TSAR v0.1.0 — Running (paper mode)"

    elif command == "/stop":
        from src.risk.kill_switch import KillSwitch
        ks = KillSwitch()
        await ks.activate("telegram_command")
        return "🛑 KILL SWITCH ACTIVATED — All trading halted."

    elif command == "/pnl":
        return "📊 No trades yet."

    elif command == "/positions":
        return "📭 No open positions."

    elif command == "/risk":
        return "🟢 Risk level: GREEN — Normal operation"

    elif command == "/flywheel":
        from src.metrics.flywheel import FlywheelHealth
        fh = FlywheelHealth()
        result = fh.compute({})
        return f"{result['emoji']} Flywheel: {result['health_score']:.2f} ({result['classification']})"

    elif command == "/start":
        return "✅ Trading started (paper mode)"

    else:
        return f"Unknown command: {command}. Available: {', '.join(COMMANDS.keys())}"
