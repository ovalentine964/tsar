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
import os
import time

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


def _get_db_path() -> str:
    """Get the database path from environment or config."""
    return os.environ.get("TSAR_DB_PATH", "./data/tsar.db")


async def handle_command(command: str, args: list[str]) -> str:
    """Handle a Telegram command.

    Routes commands to real TSAR subsystems:
    - /status → system health, agent status, kill switch state
    - /pnl → real P&L from TradeMemory
    - /positions → real positions from TradeMemory
    - /risk → real risk state from RiskEngine + KillSwitch
    - /stop → activate kill switch
    - /start → deactivate kill switch
    - /regime → regime data from TradeMemory
    - /flywheel → flywheel health score

    Args:
        command: Command string (e.g., "/status")
        args: Command arguments

    Returns:
        Response text.
    """
    if command == "/status":
        return await _handle_status()

    elif command == "/stop":
        from src.risk.kill_switch import KillSwitch
        ks = KillSwitch()
        await ks.activate("telegram_command")
        return "🛑 KILL SWITCH ACTIVATED — All trading halted."

    elif command == "/pnl":
        return await _handle_pnl()

    elif command == "/positions":
        return await _handle_positions()

    elif command == "/risk":
        return await _handle_risk()

    elif command == "/flywheel":
        from src.metrics.flywheel import FlywheelHealth
        fh = FlywheelHealth()
        result = fh.compute({})
        return f"{result['emoji']} Flywheel: {result['health_score']:.2f} ({result['classification']})"

    elif command == "/start":
        from src.risk.kill_switch import KillSwitch
        ks = KillSwitch()
        await ks.deactivate()
        return "✅ Trading resumed — Gated Recovery Protocol engaged."

    elif command == "/regime":
        return await _handle_regime()

    else:
        return f"Unknown command: {command}. Available: {', '.join(COMMANDS.keys())}"


async def _handle_status() -> str:
    """Build system status from real subsystems."""
    from src.risk.kill_switch import KillSwitch
    from src.knowledge.trade_memory import TradeMemory

    db_path = _get_db_path()
    ks = KillSwitch()
    ks_active = await ks.is_active()

    trade_mem = TradeMemory(db_path)
    trade_count = trade_mem.get_trade_count()
    open_positions = trade_mem.get_open_positions()
    stats = trade_mem.get_trade_stats()

    ks_status = "🛑 HALTED" if ks_active else "🟢 ACTIVE"
    mode = "paper"  # TODO: read from config

    lines = [
        f"🏰 TSAR v0.1.0 — {ks_status}",
        f"📊 Mode: {mode}",
        f"📈 Total trades: {trade_count}",
        f"📂 Open positions: {len(open_positions)}",
        f"💰 Total P&L: {stats['total_pnl']:.2f} USDT",
        f"🎯 Win rate: {stats['win_rate']:.1%}",
    ]
    return "\n".join(lines)


async def _handle_pnl() -> str:
    """Get real P&L from TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = _get_db_path()
    trade_mem = TradeMemory(db_path)
    stats = trade_mem.get_trade_stats()

    if stats["trade_count"] == 0:
        return "📊 No trades yet."

    pf_str = f"{stats['profit_factor']:.2f}" if stats["profit_factor"] != float("inf") else "∞"

    lines = [
        "📊 P&L Summary",
        f"━━━━━━━━━━━━━━━━",
        f"💰 Total P&L: {stats['total_pnl']:.2f} USDT",
        f"🎯 Win rate: {stats['win_rate']:.1%}",
        f"📈 Avg win: {stats['avg_win']:.2f} USDT",
        f"📉 Avg loss: {stats['avg_loss']:.2f} USDT",
        f"⚖️ Profit factor: {pf_str}",
        f"📉 Max drawdown: {stats['max_drawdown']:.2f} USDT",
        f"🔢 Total trades: {stats['trade_count']}",
    ]
    return "\n".join(lines)


async def _handle_positions() -> str:
    """Get real positions from TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = _get_db_path()
    trade_mem = TradeMemory(db_path)
    positions = trade_mem.get_open_positions()

    if not positions:
        return "📭 No open positions."

    lines = [f"📂 Open Positions ({len(positions)})"]
    lines.append("━━━━━━━━━━━━━━━━")
    for pos in positions[:10]:  # Limit to 10 for readability
        side_emoji = "🟢" if pos.side == "buy" else "🔴"
        entry = pos.entry_price if pos.entry_price else 0
        lines.append(
            f"{side_emoji} {pos.symbol} | {pos.side.upper()} "
            f"| qty: {pos.position_size_after:.4f} "
            f"| entry: {entry:.2f}"
        )

    if len(positions) > 10:
        lines.append(f"... and {len(positions) - 10} more")

    return "\n".join(lines)


async def _handle_risk() -> str:
    """Get real risk state from KillSwitch and TradeMemory."""
    from src.risk.kill_switch import KillSwitch
    from src.knowledge.trade_memory import TradeMemory

    db_path = _get_db_path()
    ks = KillSwitch()
    ks_active = await ks.is_active()

    trade_mem = TradeMemory(db_path)
    stats = trade_mem.get_trade_stats()
    open_positions = trade_mem.get_open_positions()

    max_dd = stats.get("max_drawdown", 0.0)

    # Determine risk level
    if max_dd >= 5.0:
        level = "🔴 RED"
    elif max_dd >= 3.0:
        level = "🟠 ORANGE"
    elif max_dd >= 2.0:
        level = "🟡 YELLOW"
    else:
        level = "🟢 GREEN"

    ks_text = "🛑 ACTIVE" if ks_active else "✅ Inactive"

    lines = [
        "🛡️ Risk State",
        f"━━━━━━━━━━━━━━━━",
        f"📊 Drawdown: {max_dd:.2f}%",
        f"🚦 Level: {level}",
        f"🔌 Kill switch: {ks_text}",
        f"📂 Open positions: {len(open_positions)}",
    ]
    return "\n".join(lines)


async def _handle_regime() -> str:
    """Get regime data from TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = _get_db_path()
    trade_mem = TradeMemory(db_path)
    regime_perf = trade_mem.get_performance_by_regime()

    if not regime_perf:
        return "🌊 No regime data available yet."

    lines = ["🌊 Market Regime Performance"]
    lines.append("━━━━━━━━━━━━━━━━")
    for regime in regime_perf[:5]:
        name = regime.get("regime_at_entry", "unknown")
        pnl = regime.get("total_pnl", 0)
        wr = regime.get("win_rate", 0)
        count = regime.get("trade_count", 0)
        lines.append(f"• {name}: P&L {pnl:.2f} | WR {wr:.0%} | Trades {count}")

    return "\n".join(lines)
