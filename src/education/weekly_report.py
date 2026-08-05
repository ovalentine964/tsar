"""
Weekly Report Generator
========================

Generates weekly learning summaries for Valentine.
Analyzes patterns, tracks progress, and suggests improvements.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.education.message_formatter import TelegramFormatter as Fmt


class WeeklyReportGenerator:
    """Generate weekly learning summaries.

    Analyzes completed trades for the week and produces:
      - Performance summary (win rate, P&L, equity curve)
      - Pattern analysis (which setups work, which don't)
      - Learning insights and next week's plan
      - Strategy evolution status
    """

    def __init__(self, trade_memory: Any = None, lesson_archive: Any = None) -> None:
        self._trade_memory = trade_memory
        self._lesson_archive = lesson_archive

    def build_report(
        self,
        trades: list[dict[str, Any]],
        equity_points: list[float] | None = None,
        strategy_name: str = "unknown",
        genome_generation: int = 0,
    ) -> str:
        """Build the weekly report message.

        Args:
            trades: List of completed trades for the week.
            equity_points: Daily equity values for the week.
            strategy_name: Current active strategy name.
            genome_generation: Current genome generation.

        Returns:
            Telegram HTML formatted weekly report.
        """
        if not trades:
            return self._build_empty_report()

        lines: list[str] = []
        stats = self._calculate_stats(trades)
        pattern_stats = self._analyze_patterns(trades)

        # Header
        lines.append(f"{Fmt.BOOK} {Fmt.bold('WEEKLY LEARNING REPORT')}")
        lines.append(Fmt.separator())

        # Performance
        lines.append(self._build_performance_section(stats, trades))

        # Equity curve
        if equity_points and len(equity_points) >= 2:
            lines.append(Fmt.section_header(Fmt.UP, "EQUITY CURVE"))
            lines.append(Fmt.format_equity_curve(equity_points))

        # Patterns learned
        lines.append(self._build_patterns_section(pattern_stats))

        # Best and worst
        lines.append(self._build_best_worst_section(pattern_stats))

        # Next week's plan
        lines.append(self._build_plan_section(pattern_stats, stats))

        # Strategy evolution
        lines.append(self._build_strategy_section(strategy_name, genome_generation, stats))

        lines.append(Fmt.separator())
        lines.append("[📊 Full Report] [📈 Detailed Stats] [🔧 Adjust Settings] [📚 Learn More]")

        return "\n".join(lines)

    # ── Stats Calculation ─────────────────────────────────────────────

    def _calculate_stats(self, trades: list[dict]) -> dict[str, Any]:
        """Calculate weekly statistics."""
        wins = sum(1 for t in trades if self._get_outcome(t) == "win")
        losses = sum(1 for t in trades if self._get_outcome(t) == "loss")
        breakeven = sum(1 for t in trades if self._get_outcome(t) == "breakeven")
        total = len(trades)

        pnls = [t.get("pnl", 0) for t in trades]
        net_pnl = sum(pnls)
        total_balance = trades[-1].get("balance", 10.0) if trades else 10.0
        net_pnl_pct = (net_pnl / total_balance * 100) if total_balance > 0 else 0

        best_trade = max(trades, key=lambda t: t.get("pnl", 0))
        worst_trade = min(trades, key=lambda t: t.get("pnl", 0))

        # Average hold time
        durations = []
        for t in trades:
            dur = t.get("duration_minutes")
            if dur is not None:
                durations.append(dur)
        avg_hold = sum(durations) / len(durations) if durations else 0

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": (wins / total * 100) if total > 0 else 0,
            "net_pnl": net_pnl,
            "net_pnl_pct": net_pnl_pct,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "avg_hold_minutes": avg_hold,
        }

    def _analyze_patterns(self, trades: list[dict]) -> dict[str, dict]:
        """Group trades by pattern and calculate win rates."""
        pattern_stats: dict[str, dict] = defaultdict(
            lambda: {"wins": 0, "losses": 0, "pnl": 0, "trades": []}
        )

        for trade in trades:
            reflection = trade.get("reflection", {})
            if isinstance(reflection, str):
                import json

                try:
                    reflection = json.loads(reflection)
                except (json.JSONDecodeError, TypeError):
                    reflection = {}

            tags = reflection.get("pattern_tags", ["unknown"])
            outcome = self._get_outcome(trade)
            pnl = trade.get("pnl", 0)

            for tag in tags:
                pattern_stats[tag]["trades"].append(trade)
                if outcome == "win":
                    pattern_stats[tag]["wins"] += 1
                elif outcome == "loss":
                    pattern_stats[tag]["losses"] += 1
                pattern_stats[tag]["pnl"] += pnl

        # Calculate win rates (as percentage 0-100)
        for tag, stats in pattern_stats.items():
            total = stats["wins"] + stats["losses"]
            stats["win_rate"] = (stats["wins"] / total * 100) if total > 0 else 0

        return dict(pattern_stats)

    # ── Section Builders ──────────────────────────────────────────────

    def _build_performance_section(self, stats: dict, trades: list[dict]) -> str:
        """Build the performance summary section."""
        lines = [Fmt.section_header(Fmt.CHART, "PERFORMANCE")]

        lines.append(Fmt.bullet(f"Trades: {stats['total']}"))
        lines.append(
            Fmt.bullet(
                f"Wins: {stats['wins']} {Fmt.WIN} | "
                f"Losses: {stats['losses']} {Fmt.LOSS} | "
                f"Breakeven: {stats['breakeven']} {Fmt.BREAKEVEN}"
            )
        )
        lines.append(Fmt.bullet(f"Win rate: {stats['win_rate']:.0f}%"))
        lines.append(Fmt.bullet(f"Net P&L: ${stats['net_pnl']:.2f} ({stats['net_pnl_pct']:.1f}%)"))

        best = stats["best_trade"]
        worst = stats["worst_trade"]
        lines.append(Fmt.bullet(f"Best: {best.get('symbol', '?')} +${best.get('pnl', 0):.2f}"))
        lines.append(Fmt.bullet(f"Worst: {worst.get('symbol', '?')} ${worst.get('pnl', 0):.2f}"))

        if stats["avg_hold_minutes"] > 0:
            avg = stats["avg_hold_minutes"]
            if avg >= 60:
                lines.append(Fmt.bullet(f"Avg hold time: {avg / 60:.1f}h"))
            else:
                lines.append(Fmt.bullet(f"Avg hold time: {avg:.0f}m"))

        return "\n".join(lines)

    def _build_patterns_section(self, pattern_stats: dict) -> str:
        """Build the patterns learned section."""
        lines = [Fmt.section_header(Fmt.BRAIN, "PATTERNS I'M LEARNING")]

        if not pattern_stats:
            lines.append(Fmt.bullet("Not enough data yet — need more trades"))
            return "\n".join(lines)

        # Sort by trade count
        sorted_patterns = sorted(
            pattern_stats.items(),
            key=lambda x: x[1]["wins"] + x[1]["losses"],
            reverse=True,
        )

        for tag, stats in sorted_patterns[:5]:
            total = stats["wins"] + stats["losses"]
            if total < 1:
                continue
            wr = stats["win_rate"]
            if wr >= 0.7:
                emoji = "🔥"
            elif wr >= 0.5:
                emoji = "✅"
            elif wr >= 0.3:
                emoji = "⚠️"
            else:
                emoji = "❌"
            lines.append(
                Fmt.bullet(
                    f"{emoji} {tag}: {stats['wins']}/{total} wins ({wr:.0f}%)"
                    f" — net ${stats['pnl']:.2f}"
                )
            )

        return "\n".join(lines)

    def _build_best_worst_section(self, pattern_stats: dict) -> str:
        """Build what worked / what didn't sections."""
        lines: list[str] = []

        valid = {k: v for k, v in pattern_stats.items() if (v["wins"] + v["losses"]) >= 2}

        if valid:
            best = max(valid, key=lambda k: valid[k]["win_rate"])
            worst = min(valid, key=lambda k: valid[k]["win_rate"])

            lines.append(Fmt.section_header(Fmt.TARGET, "WHAT WORKED BEST"))
            bs = valid[best]
            lines.append(
                Fmt.bullet(
                    f"{best}: {bs['wins']}/{bs['wins'] + bs['losses']} wins "
                    f"({bs['win_rate']:.0f}%) — net ${bs['pnl']:.2f}"
                )
            )

            lines.append(Fmt.section_header(Fmt.WARNING, "WHAT DIDN'T WORK"))
            ws = valid[worst]
            lines.append(
                Fmt.bullet(
                    f"{worst}: {ws['wins']}/{ws['wins'] + ws['losses']} wins "
                    f"({ws['win_rate']:.0f}%) — net ${ws['pnl']:.2f}"
                )
            )
        else:
            lines.append(Fmt.section_header(Fmt.TARGET, "WHAT WORKED / DIDN'T"))
            lines.append(Fmt.bullet("Need at least 2 trades per pattern to compare"))

        return "\n".join(lines)

    def _build_plan_section(self, pattern_stats: dict, stats: dict) -> str:
        """Build next week's plan section."""
        lines = [Fmt.section_header(Fmt.BOOK, "NEXT WEEK'S PLAN")]

        valid = {k: v for k, v in pattern_stats.items() if (v["wins"] + v["losses"]) >= 2}

        if valid:
            best = max(valid, key=lambda k: valid[k]["win_rate"])
            worst = min(valid, key=lambda k: valid[k]["win_rate"])

            if valid[best]["win_rate"] >= 60:
                lines.append(Fmt.bullet(f"Focus on: {best} pattern (highest win rate)"))
            if valid[worst]["win_rate"] < 40:
                lines.append(Fmt.bullet(f"Avoid: {worst} pattern (needs rework)"))

        if stats["win_rate"] < 50:
            lines.append(Fmt.bullet("Tighten entry criteria — win rate below 50%"))
        if stats["net_pnl"] < 0:
            lines.append(Fmt.bullet("Review risk management — net P&L negative"))

        lines.append(Fmt.bullet("Continue learning and refining"))

        return "\n".join(lines)

    def _build_strategy_section(self, strategy_name: str, generation: int, stats: dict) -> str:
        """Build strategy evolution section."""
        lines = [Fmt.section_header(Fmt.DNA, "STRATEGY EVOLUTION")]

        lines.append(Fmt.bullet(f"Strategy: {strategy_name} (Gen {generation})"))
        lines.append(Fmt.bullet(f"This week's win rate: {stats['win_rate']:.0f}%"))

        if stats["win_rate"] >= 60:
            lines.append(Fmt.bullet("Strategy performing well — no mutations needed"))
        elif stats["win_rate"] >= 40:
            lines.append(Fmt.bullet("Strategy average — monitoring for mutation triggers"))
        else:
            lines.append(Fmt.bullet("Strategy underperforming — mutation recommended"))

        return "\n".join(lines)

    def _build_empty_report(self) -> str:
        """Build report when no trades were taken."""
        lines = [
            f"{Fmt.BOOK} {Fmt.bold('WEEKLY LEARNING REPORT')}",
            Fmt.separator(),
            "",
            "📊 No trades this week.",
            "",
            "This could mean:",
            "• Market conditions weren't favorable",
            "• No high-confidence signals detected",
            "• Kill switch was active",
            "",
            "No trade is better than a bad trade! 🎯",
            "",
            Fmt.separator(),
        ]
        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_outcome(trade: dict) -> str:
        """Extract outcome from trade data."""
        reflection = trade.get("reflection", {})
        if isinstance(reflection, str):
            import json

            try:
                reflection = json.loads(reflection)
            except (json.JSONDecodeError, TypeError):
                reflection = {}

        outcome = reflection.get("outcome", "")
        if outcome:
            return outcome

        # Infer from P&L
        pnl = trade.get("pnl", 0)
        if pnl > 0.001:
            return "win"
        elif pnl < -0.001:
            return "loss"
        return "breakeven"
