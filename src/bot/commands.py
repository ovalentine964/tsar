"""
Bot Commands — Interactive Telegram command handlers.

Commands:
  /start       — Welcome + auto-setup if credentials missing
  /setup       — Re-run credential setup wizard
  /stop        — Emergency stop (kill switch)
  /status      — System status
  /config      — Show current configuration (masked credentials)
  /trade       — Start/stop trading
  /risk        — Show current risk settings
  /pnl         — P&L summary
  /positions   — Open positions
  /regime      — Current market regime
  /flywheel    — Flywheel health
  /performance — Detailed performance analysis
  /strategy    — Current strategy and genome
  /discuss     — Discuss a specific trade
  /why         — Why was a trade taken
  /ask         — Ask TSAR anything (handled in bot.py)
  /help        — Show available commands
  /cancel      — Cancel current operation

Each command queries real TSAR subsystems:
  - TradeMemory for trade data and stats
  - RiskEngine for risk state
  - KillSwitch for halt status
  - FlywheelHealth for self-improvement metrics
  - RegimeStateStore for current regime
  - StrategyGenomes for active strategies
  - PatternLibrary for active patterns
  - LessonArchive for recent lessons
"""

from __future__ import annotations

import json
import logging
import os
import secrets as _secrets

logger = logging.getLogger(__name__)


COMMANDS = {
    "/start": "Welcome + auto-setup",
    "/setup": "Re-run credential wizard",
    "/stop": "Emergency stop (kill switch)",
    "/status": "System status",
    "/config": "View configuration (masked)",
    "/trade": "Start/stop trading",
    "/risk": "Show risk settings",
    "/pnl": "P&L summary",
    "/positions": "Open positions",
    "/regime": "Current market regime",
    "/flywheel": "Flywheel health score",
    "/performance": "Detailed performance analysis",
    "/strategy": "Current strategy & genome",
    "/discuss": "Discuss a specific trade",
    "/why": "Why was a trade taken",
    "/ask": "Ask TSAR anything",
    "/cancel": "Cancel current operation",
    "/help": "Show available commands",
}

# Confirmation tokens for dangerous commands (in-memory, per-session)
_pending_confirmations: dict[str, str] = {}


def _get_db_path() -> str:
    """Get the database path from environment or config."""
    return os.environ.get("TSAR_DB_PATH", "./data/tsar.db")


async def handle_command(command: str, args: list[str]) -> str:
    """Handle a Telegram command.

    Routes commands to real TSAR subsystems and returns formatted
    HTML response.

    Args:
        command: Command string (e.g., "/status")
        args: Command arguments

    Returns:
        Formatted response text (HTML).
    """
    handlers = {
        "/status": _handle_status,
        "/stop": _handle_stop,
        "/start": _handle_start,
        "/config": _handle_config,
        "/trade": _handle_trade,
        "/risk": _handle_risk,
        "/pnl": _handle_pnl,
        "/positions": _handle_positions,
        "/regime": _handle_regime,
        "/flywheel": _handle_flywheel,
        "/performance": _handle_performance,
        "/strategy": _handle_strategy,
        "/discuss": _handle_discuss,
        "/why": _handle_why,
    }

    handler = handlers.get(command)
    if handler:
        return await handler(args)

    return f"Unknown command: {command}\n\nAvailable: {', '.join(COMMANDS.keys())}"


# ═══════════════════════════════════════════════════════════════════════
# SETUP & CONFIG COMMANDS
# ═══════════════════════════════════════════════════════════════════════


async def _handle_config(_args: list[str]) -> str:
    """Show current configuration with masked credentials.

    Displays all configured credentials (masked), trading mode,
    and system version.
    """
    from src.bot.credentials import get_credential_status, has_credentials

    status = get_credential_status()

    lines = [
        "⚙️ <b>TSAR Configuration</b>",
        "━━━━━━━━━━━━━━━━",
        "",
    ]

    if not has_credentials():
        lines.append("⚠️ No credentials configured yet.")
        lines.append("Type /setup to configure.")
        return "\n".join(lines)

    lines.append("<b>Credentials:</b>")
    for _key, info in status.items():
        check = "✅" if info["configured"] else "❌"
        masked = info["masked"] if info["configured"] else "not set"
        lines.append(f"  {check} {info['label']}: <code>{masked}</code>")

    lines.append("")

    # Trading mode
    mode = os.environ.get("TSAR_TRADING_MODE", "paper")
    mode_emoji = "📝" if mode == "paper" else "💰"
    lines.append(f"{mode_emoji} Trading mode: <b>{mode}</b>")

    # DB path
    db_path = _get_db_path()
    lines.append(f"💾 Database: <code>{db_path}</code>")

    # Version
    lines.append("🏰 TSAR v0.1.0")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# MONITORING COMMANDS
# ═══════════════════════════════════════════════════════════════════════


async def _handle_status(_args: list[str]) -> str:
    """Build system status from real subsystems."""
    from src.bot.credentials import get_credential_status, has_credentials
    from src.knowledge.trade_memory import TradeMemory
    from src.risk.kill_switch import KillSwitch

    db_path = _get_db_path()
    ks = KillSwitch()
    ks_active = await ks.is_active()

    trade_mem = TradeMemory(db_path)
    trade_count = trade_mem.get_trade_count()
    open_positions = trade_mem.get_open_positions()
    stats = trade_mem.get_trade_stats()

    ks_status = "🛑 HALTED" if ks_active else "🟢 ACTIVE"
    mode = os.environ.get("TSAR_TRADING_MODE", "paper")

    # Credential status
    creds_ok = has_credentials()
    creds_emoji = "✅" if creds_ok else "⚠️"

    lines = [
        f"🏰 <b>TSAR v0.1.0 — {ks_status}</b>",
        "",
        f"{creds_emoji} Credentials: {'configured' if creds_ok else 'NOT CONFIGURED — /setup'}",
        f"📊 Mode: {mode}",
        f"📈 Total trades: {trade_count}",
        f"📂 Open positions: {len(open_positions)}",
        f"💰 Total P&L: {stats['total_pnl']:.2f} USDT",
        f"🎯 Win rate: {stats['win_rate']:.1%}",
    ]

    # Add profit factor if available
    pf = stats.get("profit_factor")
    if pf is not None and pf != float("inf"):
        lines.append(f"⚖️ Profit factor: {pf:.2f}")
    elif pf == float("inf"):
        lines.append("⚖️ Profit factor: ∞")

    # Add max drawdown
    max_dd = stats.get("max_drawdown", 0)
    if max_dd > 0:
        lines.append(f"📉 Max drawdown: {max_dd:.2f}%")

    # Exchange connection status
    creds = get_credential_status()
    exchange_configured = creds.get("EXCHANGE_API_KEY", {}).get("configured", False)
    lines.append(f"🔌 Exchange: {'connected' if exchange_configured else 'not configured'}")

    return "\n".join(lines)


async def _handle_stop(args: list[str]) -> str:
    """Activate kill switch — requires confirmation."""
    from src.risk.kill_switch import KillSwitch

    if args and args[0] == "confirm":
        token = _pending_confirmations.pop("/stop", None)
        if not token:
            return "⚠️ No pending /stop confirmation. Run /stop first."
        ks = KillSwitch()
        await ks.activate("telegram_command")
        return (
            "🛑 <b>KILL SWITCH ACTIVATED</b>\n\n"
            "All trading has been halted.\n"
            "Use /start to resume trading."
        )

    token = _secrets.token_hex(4)
    _pending_confirmations["/stop"] = token
    return (
        "⚠️ <b>Confirm Kill Switch</b>\n\n"
        "This will halt ALL trading immediately.\n"
        "To confirm, reply with:\n"
        "<code>/stop confirm</code>\n\n"
        "This confirmation expires after the next /stop request."
    )


async def _handle_start(args: list[str]) -> str:
    """Deactivate kill switch — requires confirmation."""
    from src.risk.kill_switch import KillSwitch

    if args and args[0] == "confirm":
        token = _pending_confirmations.pop("/start", None)
        if not token:
            return "⚠️ No pending /start confirmation. Run /start first."
        ks = KillSwitch()
        await ks.deactivate()
        return (
            "✅ <b>Trading resumed</b>\n\n"
            "Gated Recovery Protocol engaged.\n"
            "TSAR will resume scanning for signals."
        )

    token = _secrets.token_hex(4)
    _pending_confirmations["/start"] = token
    return (
        "⚠️ <b>Confirm Resume Trading</b>\n\n"
        "This will deactivate the kill switch and resume live trading.\n"
        "To confirm, reply with:\n"
        "<code>/start confirm</code>\n\n"
        "This confirmation expires after the next /start request."
    )


async def _handle_trade(args: list[str]) -> str:
    """Start or stop trading.

    /trade         — Show trading status
    /trade start   — Start trading (same as /start confirm)
    /trade stop    — Stop trading (same as /stop)
    """
    from src.risk.kill_switch import KillSwitch

    ks = KillSwitch()
    ks_active = await ks.is_active()

    if not args:
        # Show current trading status
        status = "🛑 HALTED" if ks_active else "🟢 ACTIVE"
        mode = os.environ.get("TSAR_TRADING_MODE", "paper")
        lines = [
            f"📊 <b>Trading Status: {status}</b>",
            "",
            f"Mode: {mode}",
            "",
            "Commands:",
            "• /trade start — Resume trading",
            "• /trade stop — Halt trading",
        ]
        return "\n".join(lines)

    action = args[0].lower()

    if action == "start":
        if not ks_active:
            return "✅ Trading is already active."
        ks = KillSwitch()
        await ks.deactivate()
        return (
            "✅ <b>Trading started</b>\n\n"
            "TSAR is now scanning for signals.\n"
            "Use /trade stop or /stop to halt."
        )

    elif action == "stop":
        if ks_active:
            return "🛑 Trading is already halted."
        ks = KillSwitch()
        await ks.activate("telegram_command")
        return (
            "🛑 <b>Trading stopped</b>\n\nAll trading has been halted.\nUse /trade start to resume."
        )

    return (
        "❓ Unknown action. Usage:\n"
        "• /trade — Show status\n"
        "• /trade start — Start trading\n"
        "• /trade stop — Stop trading"
    )


async def _handle_pnl(_args: list[str]) -> str:
    """Get real P&L from TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = _get_db_path()
    trade_mem = TradeMemory(db_path)
    stats = trade_mem.get_trade_stats()

    if stats["trade_count"] == 0:
        return "📊 No trades yet."

    pf_str = f"{stats['profit_factor']:.2f}" if stats["profit_factor"] != float("inf") else "∞"

    lines = [
        "📊 <b>P&L Summary</b>",
        "━━━━━━━━━━━━━━━━",
        f"💰 Total P&L: {stats['total_pnl']:.2f} USDT",
        f"🎯 Win rate: {stats['win_rate']:.1%}",
        f"📈 Avg win: {stats['avg_win']:.2f} USDT",
        f"📉 Avg loss: {stats['avg_loss']:.2f} USDT",
        f"⚖️ Profit factor: {pf_str}",
        f"📉 Max drawdown: {stats['max_drawdown']:.2f} USDT",
        f"🔢 Total trades: {stats['trade_count']}",
    ]
    return "\n".join(lines)


async def _handle_positions(_args: list[str]) -> str:
    """Get real positions from TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory

    db_path = _get_db_path()
    trade_mem = TradeMemory(db_path)
    positions = trade_mem.get_open_positions()

    if not positions:
        return "📭 No open positions."

    lines = [f"📂 <b>Open Positions ({len(positions)})</b>"]
    lines.append("━━━━━━━━━━━━━━━━")
    for pos in positions[:10]:
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


async def _handle_risk(_args: list[str]) -> str:
    """Get real risk state from KillSwitch and TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory
    from src.risk.kill_switch import KillSwitch

    db_path = _get_db_path()
    ks = KillSwitch()
    ks_active = await ks.is_active()

    trade_mem = TradeMemory(db_path)
    stats = trade_mem.get_trade_stats()
    open_positions = trade_mem.get_open_positions()

    max_dd = stats.get("max_drawdown", 0.0)

    if max_dd >= 5.0:
        level = "🔴 RED"
    elif max_dd >= 3.0:
        level = "🟠 ORANGE"
    elif max_dd >= 2.0:
        level = "🟡 YELLOW"
    else:
        level = "🟢 GREEN"

    ks_text = "🛑 ACTIVE" if ks_active else "✅ Inactive"

    # Risk parameters from config
    risk_per_trade = os.environ.get("TSAR_RISK_PER_TRADE", "2.0")
    max_positions = os.environ.get("TSAR_MAX_POSITIONS", "5")
    max_leverage = os.environ.get("TSAR_MAX_LEVERAGE", "3")

    lines = [
        "🛡️ <b>Risk State</b>",
        "━━━━━━━━━━━━━━━━",
        f"📊 Drawdown: {max_dd:.2f}%",
        f"🚦 Level: {level}",
        f"🔌 Kill switch: {ks_text}",
        f"📂 Open positions: {len(open_positions)}",
        "",
        "<b>Risk Parameters:</b>",
        f"• Risk per trade: {risk_per_trade}%",
        f"• Max positions: {max_positions}",
        f"• Max leverage: {max_leverage}x",
    ]
    return "\n".join(lines)


async def _handle_regime(_args: list[str]) -> str:
    """Get regime data from RegimeStateStore and TradeMemory."""
    from src.knowledge.trade_memory import TradeMemory
    from src.tools.knowledge import KnowledgeTools

    db_path = _get_db_path()

    lines = ["🌊 <b>Market Regime</b>", "━━━━━━━━━━━━━━━━"]

    # Current regime from RegimeStateStore
    try:
        kt = KnowledgeTools(db_path)
        regime = kt.get_global_regime()
        if regime:
            regime_name = regime.get("regime", "unknown")
            confidence = regime.get("confidence", 0)
            emoji_map = {
                "STRONG_TREND_UP": "🟢📈",
                "STRONG_TREND_DOWN": "🔴📉",
                "RANGING": "↔️",
                "HIGH_VOLATILITY": "🌊",
                "UNCERTAIN": "❓",
            }
            emoji = emoji_map.get(regime_name, "🔄")
            lines.append(f"{emoji} Current: {regime_name}")
            lines.append(f"📊 Confidence: {confidence:.0%}")

            # Regime transitions
            transitions = kt.get_recent_transitions(limit=3)
            if transitions:
                lines.append("")
                lines.append("<b>Recent Transitions:</b>")
                for t in transitions:
                    lines.append(
                        f"• {t.get('from_regime', '?')} → {t.get('to_regime', '?')} "
                        f"({t.get('timestamp', '')[:16]})"
                    )
        else:
            lines.append("No regime data available yet.")

        kt.close()
    except Exception:
        lines.append("(Regime store unavailable)")

    # Regime performance from TradeMemory
    try:
        trade_mem = TradeMemory(db_path)
        regime_perf = trade_mem.get_performance_by_regime()

        if regime_perf:
            lines.append("")
            lines.append("<b>Performance by Regime:</b>")
            for regime in regime_perf[:5]:
                name = regime.get("regime_at_entry", "unknown")
                pnl = regime.get("total_pnl", 0)
                wr = regime.get("win_rate", 0)
                count = regime.get("trade_count", 0)
                pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(f"• {name}: {pnl_emoji} P&L {pnl:.2f} | WR {wr:.0%} | Trades {count}")
    except Exception:
        pass

    return "\n".join(lines)


async def _handle_flywheel(_args: list[str]) -> str:
    """Get flywheel health from FlywheelHealthScore."""
    from src.metrics.flywheel import FlywheelHealth

    fh = FlywheelHealth()
    result = fh.compute({})

    lines = [
        f"{result['emoji']} <b>Flywheel Health</b>",
        "━━━━━━━━━━━━━━━━",
        f"Score: {result['health_score']:.2f} ({result['classification']})",
        "",
        "<b>Components:</b>",
    ]

    for name, vals in result.get("component_scores", {}).items():
        score = vals.get("score", 0)
        bar_len = int(score * 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        lines.append(f"• {name}: <code>[{bar}]</code> {score:.2f}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# ANALYSIS COMMANDS
# ═══════════════════════════════════════════════════════════════════════


async def _handle_performance(_args: list[str]) -> str:
    """Detailed performance analysis across multiple dimensions.

    Shows: overall stats, per-strategy breakdown, recent trades,
    regime performance, and pattern effectiveness.
    """
    from src.knowledge.trade_memory import TradeMemory
    from src.tools.knowledge import KnowledgeTools

    db_path = _get_db_path()
    trade_mem = TradeMemory(db_path)
    stats = trade_mem.get_trade_stats()

    if stats["trade_count"] == 0:
        return "📊 No trades yet. Performance will appear after your first trade."

    lines = [
        "📊 <b>Performance Analysis</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "<b>Overall:</b>",
        f"• Total P&L: {stats['total_pnl']:.2f} USDT",
        f"• Win rate: {stats['win_rate']:.1%}",
        f"• Trades: {stats['trade_count']}",
        f"• Avg win: {stats['avg_win']:.2f} | Avg loss: {stats['avg_loss']:.2f}",
    ]

    pf = stats.get("profit_factor")
    if pf is not None:
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        lines.append(f"• Profit factor: {pf_str}")

    # Per-strategy breakdown
    try:
        kt = KnowledgeTools(db_path)
        strategy_summary = kt.get_strategy_summary()
        if strategy_summary:
            lines.append("")
            lines.append("<b>By Strategy:</b>")
            for s in strategy_summary[:5]:
                name = s.get("strategy_id", "unknown")
                pnl = s.get("total_pnl", 0)
                wr = s.get("win_rate", 0)
                count = s.get("trade_count", 0)
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(f"• {name}: {emoji} {pnl:.2f} USDT | WR {wr:.0%} | {count} trades")

        # Recent lessons
        lessons = kt.get_recent_lessons(days=7, limit=3)
        if lessons:
            lines.append("")
            lines.append("<b>Recent Lessons:</b>")
            for lesson in lessons:
                severity = lesson.get("severity", "info")
                sev_emoji = {"critical": "🔴", "high": "🟠", "moderate": "🟡"}.get(severity, "💡")
                lines.append(f"• {sev_emoji} {lesson.get('content', '')[:100]}")

        # Active patterns
        patterns = kt.get_active_patterns()
        if patterns:
            lines.append("")
            lines.append(f"<b>Active Patterns ({len(patterns)}):</b>")
            for p in patterns[:5]:
                name = p.get("name", "unknown")
                conf = p.get("confidence", 0)
                exp = p.get("expectancy", 0)
                lines.append(f"• {name}: conf={conf:.0%}, expectancy={exp:.2f}")

        kt.close()
    except Exception:
        logger.debug("Performance analysis extras failed", exc_info=True)

    return "\n".join(lines)


async def _handle_strategy(_args: list[str]) -> str:
    """Show current strategy and genome details.

    Displays: active strategies, current parameters, recent mutations,
    and strategy fitness metrics.
    """
    from src.tools.knowledge import KnowledgeTools

    db_path = _get_db_path()

    lines = ["🧬 <b>Strategy & Genome</b>", "━━━━━━━━━━━━━━━━"]

    try:
        kt = KnowledgeTools(db_path)

        # Active strategies
        strategies = kt.get_active_strategies()
        if strategies:
            for strat in strategies[:3]:
                name = strat.get("name", strat.get("strategy_id", "unknown"))
                fitness = strat.get("fitness_score", 0)
                lines.append(f"\n<b>{name}</b>")
                lines.append(f"• Fitness: {fitness:.2f}")

                # Parameters
                params = strat.get("params", {})
                if params:
                    lines.append("• Parameters:")
                    for k, v in list(params.items())[:8]:
                        lines.append(f"  — {k}: {v}")

                # Recent mutations
                sid = strat.get("strategy_id", "")
                if sid:
                    mutations = kt.get_mutations(sid, limit=3)
                    if mutations:
                        lines.append("• Recent mutations:")
                        for m in mutations:
                            desc = m.get("description", m.get("mutation_type", "unknown"))
                            lines.append(f"  — {desc}")
        else:
            lines.append("No active strategies found.")

        # Genome lineage
        if strategies:
            sid = strategies[0].get("strategy_id", "")
            if sid:
                lineage = kt.get_lineage(sid)
                if lineage and len(lineage) > 1:
                    lines.append(f"\n<b>Lineage ({len(lineage)} generations):</b>")
                    for gen in lineage[-3:]:
                        lines.append(
                            f"• Gen {gen.get('generation', '?')}: "
                            f"fitness={gen.get('fitness', 0):.2f}"
                        )

        kt.close()
    except Exception:
        logger.debug("Strategy query failed", exc_info=True)
        lines.append("(Strategy data unavailable)")

    return "\n".join(lines)


async def _handle_discuss(args: list[str]) -> str:
    """Discuss a specific trade by trade_id.

    Shows: trade details, reasoning, lessons, and similar past trades.
    """
    if not args:
        return (
            "💬 <b>Trade Discussion</b>\n\n"
            "Usage: /discuss [trade_id]\n\n"
            "Get the trade ID from /positions or /pnl."
        )

    trade_id = args[0]
    from src.tools.knowledge import KnowledgeTools

    db_path = _get_db_path()

    lines = [f"💬 <b>Trade Discussion: {trade_id}</b>", "━━━━━━━━━━━━━━━━"]

    try:
        kt = KnowledgeTools(db_path)

        # Get trade details
        trade = kt.get_trade(trade_id)
        if not trade:
            return f"❌ Trade {trade_id} not found."

        symbol = trade.get("symbol", "?")
        side = trade.get("side", "?")
        entry = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        pnl = trade.get("pnl", 0)
        pnl_pct = trade.get("pnl_pct", 0)

        emoji = "🟢" if pnl >= 0 else "🔴"
        side_label = "LONG" if side.upper() == "BUY" else "SHORT"

        lines.append(f"\n{emoji} <b>{symbol} {side_label}</b>")
        lines.append(f"• Entry: ${entry:,.2f} → Exit: ${exit_price:,.2f}")
        lines.append(f"• P&L: {pnl:.2f} USDT ({pnl_pct:.1f}%)")
        lines.append(f"• Strategy: {trade.get('strategy', 'N/A')}")
        lines.append(f"• Regime: {trade.get('regime_at_entry', 'N/A')}")

        # Reasoning
        reasoning = trade.get("reasoning", "")
        if reasoning:
            lines.append("\n<b>Reasoning:</b>")
            lines.append(f"• {reasoning}")

        # Reflection / Lesson
        reflection = trade.get("reflection")
        if reflection:
            if isinstance(reflection, str):
                try:
                    reflection = json.loads(reflection)
                except (json.JSONDecodeError, TypeError):
                    reflection = {"lesson": reflection}

            lines.append("\n<b>Lesson:</b>")
            lines.append(f"• {reflection.get('lesson', 'N/A')}")

            outcome = reflection.get("outcome", "")
            if outcome:
                lines.append(f"• Outcome: {outcome}")

            what_right = reflection.get("what_went_right")
            if what_right:
                lines.append(f"• ✅ {what_right}")

            what_wrong = reflection.get("what_went_wrong")
            if what_wrong:
                lines.append(f"• ❌ {what_wrong}")

            actionable = reflection.get("actionable_change")
            if actionable:
                lines.append(f"• 📝 Recommended: {actionable}")

        # Similar trades (vector search)
        try:
            query = f"{symbol} {side_label} {trade.get('strategy', '')}"
            similar = kt.vector_search_trades(query, limit=3)
            if similar:
                lines.append("\n<b>Similar Past Trades:</b>")
                for s in similar:
                    s_id = s.get("trade_id", "?")
                    s_score = s.get("score", 0)
                    lines.append(f"• {s_id} (similarity: {s_score:.2f})")
        except Exception:
            pass

        kt.close()
    except Exception:
        logger.debug("Trade discussion failed", exc_info=True)
        lines.append("(Failed to load trade data)")

    return "\n".join(lines)


async def _handle_why(args: list[str]) -> str:
    """Explain why a specific trade was taken.

    Shows: signal reasoning, indicator values, risk assessment,
    and matching patterns/lessons.
    """
    if not args:
        return (
            "❓ <b>Why This Trade?</b>\n\n"
            "Usage: /why [trade_id]\n\n"
            "Get the trade ID from /positions or /pnl."
        )

    trade_id = args[0]
    from src.tools.knowledge import KnowledgeTools

    db_path = _get_db_path()

    lines = [f"❓ <b>Why: Trade {trade_id}</b>", "━━━━━━━━━━━━━━━━"]

    try:
        kt = KnowledgeTools(db_path)

        trade = kt.get_trade(trade_id)
        if not trade:
            return f"❌ Trade {trade_id} not found."

        symbol = trade.get("symbol", "?")
        side = trade.get("side", "?")
        strategy = trade.get("strategy", "unknown")
        reasoning = trade.get("reasoning", "")
        metadata = trade.get("metadata", {})

        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        lines.append(f"\n<b>Symbol:</b> {symbol} | <b>Side:</b> {side}")
        lines.append(f"<b>Strategy:</b> {strategy}")

        # Signal reasoning
        if reasoning:
            lines.append("\n<b>Signal Reasoning:</b>")
            for part in reasoning.split("|"):
                part = part.strip()
                if part:
                    lines.append(f"• {part}")

        # Technical indicators at time of trade
        if metadata:
            lines.append("\n<b>Indicators at Entry:</b>")
            indicator_keys = [
                ("rsi", "RSI"),
                ("atr", "ATR"),
                ("macd_histogram", "MACD hist"),
                ("bb_upper", "BB upper"),
                ("bb_lower", "BB lower"),
                ("ema_trend", "EMA(50)"),
                ("volatility_regime", "Volatility"),
            ]
            for key, label in indicator_keys:
                val = metadata.get(key)
                if val is not None:
                    if isinstance(val, float):
                        lines.append(f"• {label}: {val:.2f}")
                    else:
                        lines.append(f"• {label}: {val}")

            # Score breakdown
            breakdown = metadata.get("score_breakdown", {})
            if breakdown:
                lines.append("\n<b>Signal Score:</b>")
                for comp, score in breakdown.items():
                    lines.append(f"• {comp}: {score:.3f}")

            # Patterns
            patterns = metadata.get("patterns_detected", [])
            if patterns:
                lines.append("\n<b>Patterns Detected:</b>")
                for p in patterns:
                    lines.append(f"• {p}")

        # Matching patterns from library
        try:
            patterns = kt.get_active_patterns()
            if patterns:
                lines.append("\n<b>Pattern Library Matches:</b>")
                for p in patterns[:3]:
                    name = p.get("name", "unknown")
                    conf = p.get("confidence", 0)
                    win_rate = p.get("win_rate", 0)
                    lines.append(f"• {name}: conf={conf:.0%}, win_rate={win_rate:.0%}")
        except Exception:
            pass

        # Regime at entry
        regime = trade.get("regime_at_entry")
        if regime:
            lines.append(f"\n<b>Regime at Entry:</b> {regime}")

        kt.close()
    except Exception:
        logger.debug("Why query failed", exc_info=True)
        lines.append("(Failed to load trade data)")

    return "\n".join(lines)
