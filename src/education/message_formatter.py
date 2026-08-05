"""
Telegram Message Formatter
===========================

Formats trade education messages for Telegram with HTML markup,
emoji, and structured layout.

All public methods return Telegram-safe HTML strings.
"""

from __future__ import annotations


class TelegramFormatter:
    """Format trade education messages for Telegram."""

    # ── Emoji Constants ───────────────────────────────────────────────
    WIN = "✅"
    LOSS = "❌"
    BREAKEVEN = "➖"
    CHART = "📊"
    BRAIN = "🧠"
    BOOK = "📖"
    TARGET = "🎯"
    WARNING = "⚠️"
    ROCKET = "🚀"
    GEAR = "🔧"
    CLOCK = "🕐"
    MONEY = "💰"
    LIGHTBULB = "💡"
    RULER = "📐"
    LINK = "⛓️"
    DNA = "🧬"
    UP = "📈"
    DOWN = "📉"

    @staticmethod
    def bold(text: str) -> str:
        return f"<b>{text}</b>"

    @staticmethod
    def code(text: str) -> str:
        return f"<code>{text}</code>"

    @staticmethod
    def separator() -> str:
        return "━━━━━━━━━━━━━━━━"

    @classmethod
    def section_header(cls, emoji: str, title: str) -> str:
        return f"\n{emoji} {cls.bold(title)}:"

    @classmethod
    def bullet(cls, text: str) -> str:
        return f"• {text}"

    @classmethod
    def bullet_list(cls, items: list[str]) -> str:
        return "\n".join(cls.bullet(item) for item in items)

    @classmethod
    def rr_emoji(cls, ratio: float) -> str:
        """Get emoji for risk/reward ratio."""
        if ratio >= 3.0:
            return "🔥"
        elif ratio >= 2.0:
            return "✅"
        elif ratio >= 1.5:
            return "⚠️"
        else:
            return "❌"

    @classmethod
    def format_price(cls, price: float) -> str:
        """Format price with appropriate precision."""
        if price >= 1000:
            return f"${price:,.2f}"
        elif price >= 1:
            return f"${price:.4f}"
        else:
            return f"${price:.6f}"

    @classmethod
    def format_pnl(cls, pnl: float, pnl_pct: float) -> str:
        """Format P&L with sign and emoji."""
        if pnl >= 0:
            return f"+${pnl:.2f} (+{pnl_pct:.1f}%)"
        else:
            return f"-${abs(pnl):.2f} ({pnl_pct:.1f}%)"

    @classmethod
    def format_equity_curve(cls, equity_points: list[float], width: int = 20) -> str:
        """Render a simple ASCII equity curve."""
        if not equity_points or len(equity_points) < 2:
            return "(not enough data)"

        min_val = min(equity_points)
        max_val = max(equity_points)
        val_range = max_val - min_val

        if val_range == 0:
            return "─" * width + " (flat)"

        lines = []
        # Show last `width` points
        points = equity_points[-width:]
        height = 5
        for row in range(height, -1, -1):
            threshold = min_val + (val_range * row / height)
            line = ""
            for p in points:
                if p >= threshold:
                    line += "█"
                else:
                    line += " "
            label = f"${threshold:.2f}"
            lines.append(f"{label:>8} |{line}")

        lines.append(" " * 9 + "+" + "─" * len(points))
        return "\n".join(lines)
