"""
Post-Trade Explainer
=====================

Builds plain-language explanations for completed trades.
Integrates with TradePhilosopher's reflection data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.education.message_formatter import TelegramFormatter as Fmt


class PostTradeExplainer:
    """Build post-trade explanations from reflection data.

    Generates Telegram-formatted messages that explain:
      - WHY the trade won or lost
      - HOW it played out (timeline, drawdown, profit)
      - LESSON learned and rule changes
      - STRATEGY update (win rate, confidence)
    """

    # ── Error Category Explanations ───────────────────────────────────
    ERROR_EXPLANATIONS: dict[str, str] = {
        "timing": "Entry timing was off — the setup was right but the timing wasn't",
        "sizing": "Position size was too large for this setup's risk profile",
        "regime": "Market regime changed mid-trade — strategy didn't adapt fast enough",
        "execution": "Execution issue — slippage or delay affected the outcome",
        "none": "Market conditions changed unexpectedly — not preventable",
    }

    # ── Public API ────────────────────────────────────────────────────

    def build_message(
        self,
        trade: dict[str, Any],
        reflection: dict[str, Any],
        old_win_rate: float | None = None,
        new_win_rate: float | None = None,
    ) -> str:
        """Build the full post-trade explanation message.

        Args:
            trade: Completed trade data from TradeMemory.
            reflection: Structured reflection from TradePhilosopher.
            old_win_rate: Strategy win rate before this trade.
            new_win_rate: Strategy win rate after this trade.

        Returns:
            Telegram HTML formatted message.
        """
        outcome = reflection.get("outcome", "unknown")
        pnl = trade.get("pnl", 0)
        pnl_pct = trade.get("pnl_pct", 0)

        if outcome == "win":
            return self._build_win_message(trade, reflection, old_win_rate, new_win_rate)
        elif outcome == "loss":
            return self._build_loss_message(trade, reflection, old_win_rate, new_win_rate)
        else:
            return self._build_breakeven_message(trade, reflection)

    # ── Win Message ───────────────────────────────────────────────────

    def _build_win_message(
        self,
        trade: dict[str, Any],
        reflection: dict[str, Any],
        old_wr: float | None,
        new_wr: float | None,
    ) -> str:
        lines: list[str] = []
        symbol = trade.get("symbol", "???")
        direction = trade.get("side", "LONG").upper()
        pnl = trade.get("pnl", 0)
        pnl_pct = trade.get("pnl_pct", 0)

        # Header
        lines.append(
            f"{Fmt.WIN} {Fmt.bold(f'TRADE CLOSED: {symbol} {direction} WIN')}"
            f" +${pnl:.2f} (+{pnl_pct:.1f}%)"
        )
        lines.append(Fmt.separator())

        # Why it won
        lines.append(Fmt.section_header(Fmt.LIGHTBULB, "WHY IT WON"))
        win_reasons = self._build_win_reasons(trade, reflection)
        for reason in win_reasons:
            lines.append(Fmt.bullet(reason))

        # How it played out
        lines.append(self._build_timeline(trade))

        # Indicators that worked
        indicators = self._build_indicators_worked(trade)
        if indicators:
            lines.append(Fmt.section_header(Fmt.CHART, "INDICATORS THAT WORKED"))
            for ind in indicators:
                lines.append(Fmt.bullet(ind))

        # Lesson
        lines.append(Fmt.section_header(Fmt.BOOK, "LESSON LEARNED"))
        lesson = reflection.get("lesson", "Review this trade for patterns")
        lines.append(Fmt.bullet(lesson))
        pattern_tags = reflection.get("pattern_tags", [])
        if pattern_tags:
            lines.append(Fmt.bullet(f"Pattern tags: {', '.join(pattern_tags)}"))

        # Strategy update
        if old_wr is not None and new_wr is not None:
            lines.append(Fmt.section_header(Fmt.DNA, "STRATEGY UPDATE"))
            strategy = trade.get("strategy", "unknown")
            lines.append(Fmt.bullet(f"{strategy} win rate: {new_wr:.0f}% (was {old_wr:.0f}%)"))

        lines.append(Fmt.separator())
        lines.append("[📈 See History] [🔧 Adjust Strategy] [📊 Full Analysis]")

        return "\n".join(lines)

    # ── Loss Message ──────────────────────────────────────────────────

    def _build_loss_message(
        self,
        trade: dict[str, Any],
        reflection: dict[str, Any],
        old_wr: float | None,
        new_wr: float | None,
    ) -> str:
        lines: list[str] = []
        symbol = trade.get("symbol", "???")
        direction = trade.get("side", "LONG").upper()
        pnl = trade.get("pnl", 0)
        pnl_pct = trade.get("pnl_pct", 0)

        # Header
        lines.append(
            f"{Fmt.LOSS} {Fmt.bold(f'TRADE CLOSED: {symbol} {direction} LOSS')}"
            f" -${abs(pnl):.2f} ({pnl_pct:.1f}%)"
        )
        lines.append(Fmt.separator())

        # Why it lost
        lines.append(Fmt.section_header(Fmt.LIGHTBULB, "WHY IT LOST"))
        loss_reasons = self._build_loss_reasons(trade, reflection)
        for reason in loss_reasons:
            lines.append(Fmt.bullet(reason))

        # How it played out
        lines.append(self._build_timeline(trade))

        # What went wrong
        lines.append(Fmt.section_header(Fmt.WARNING, "WHAT WENT WRONG"))
        what_wrong = reflection.get("what_went_wrong", "")
        if what_wrong:
            lines.append(Fmt.bullet(what_wrong))
        error_cat = reflection.get("error_category", "none")
        lines.append(Fmt.bullet(self.ERROR_EXPLANATIONS.get(error_cat, self.ERROR_EXPLANATIONS["none"])))

        # Lesson
        lines.append(Fmt.section_header(Fmt.BOOK, "LESSON LEARNED"))
        lesson = reflection.get("lesson", "Review this trade for patterns")
        lines.append(Fmt.bullet(lesson))

        actionable = reflection.get("actionable_change")
        if actionable:
            lines.append(Fmt.bullet(f"New rule: {actionable}"))

        # Strategy update
        if old_wr is not None and new_wr is not None:
            lines.append(Fmt.section_header(Fmt.DNA, "STRATEGY UPDATE"))
            strategy = trade.get("strategy", "unknown")
            lines.append(Fmt.bullet(f"{strategy} win rate: {new_wr:.0f}% (was {old_wr:.0f}%)"))

        lines.append(Fmt.separator())
        lines.append("[📈 See History] [🔧 View Updated Rules] [📊 Full Analysis]")

        return "\n".join(lines)

    # ── Breakeven Message ─────────────────────────────────────────────

    def _build_breakeven_message(
        self, trade: dict[str, Any], reflection: dict[str, Any]
    ) -> str:
        lines: list[str] = []
        symbol = trade.get("symbol", "???")
        direction = trade.get("side", "LONG").upper()
        pnl = trade.get("pnl", 0)
        pnl_pct = trade.get("pnl_pct", 0)

        lines.append(
            f"{Fmt.BREAKEVEN} {Fmt.bold(f'TRADE CLOSED: {symbol} {direction} BREAKEVEN')}"
            f" ${pnl:.2f} ({pnl_pct:.1f}%)"
        )
        lines.append(Fmt.separator())

        lines.append(Fmt.section_header(Fmt.LIGHTBULB, "WHAT HAPPENED"))
        lines.append(Fmt.bullet("Trade closed near entry — no significant gain or loss"))
        lines.append(Fmt.bullet("Breakeven trades protect capital — no loss is a win"))

        # Fees
        fees = trade.get("fees", 0)
        if fees > 0:
            lines.append(Fmt.bullet(f"Fee impact: ${fees:.4f}"))

        lines.append(Fmt.separator())
        lines.append("[📈 See History] [📊 Full Analysis]")

        return "\n".join(lines)

    # ── Internal Builders ─────────────────────────────────────────────

    def _build_win_reasons(self, trade: dict, reflection: dict) -> list[str]:
        """Generate plain-language reasons for a winning trade."""
        reasons: list[str] = []

        what_right = reflection.get("what_went_right", "")
        if what_right:
            reasons.append(what_right)

        metadata = trade.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        # Technical indicators
        rsi = metadata.get("rsi")
        if rsi is not None:
            if rsi < 30:
                reasons.append(f"RSI at {rsi:.0f} was indeed oversold — bounce happened as expected")
            elif rsi > 70:
                reasons.append(f"RSI at {rsi:.0f} was indeed overbought — pullback happened as expected")

        # Support held
        if metadata.get("support_held"):
            level = Fmt.format_price(metadata.get("support_level", 0))
            reasons.append(f"Support at {level} held — buyers defended it")

        # Volume confirmed
        if metadata.get("volume_confirmed"):
            reasons.append("Volume confirmed the move — not a fake breakout")

        # Regime alignment
        regime = trade.get("regime_at_entry")
        if regime == "trending":
            reasons.append("Regime was TRENDING — trend-following strategy worked")

        return reasons if reasons else ["Trade hit take profit as planned"]

    def _build_loss_reasons(self, trade: dict, reflection: dict) -> list[str]:
        """Generate plain-language reasons for a losing trade."""
        reasons: list[str] = []

        what_wrong = reflection.get("what_went_wrong", "")
        if what_wrong:
            reasons.append(what_wrong)

        metadata = trade.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        # Specific loss scenarios
        if metadata.get("news_event"):
            reasons.append(f"News event: {metadata['news_event']} — markets moved on unexpected news")

        if metadata.get("support_broke"):
            level = Fmt.format_price(metadata.get("support_level", 0))
            reasons.append(f"Support at {level} broke — sellers overwhelmed buyers")

        if metadata.get("regime_changed"):
            old_r = metadata.get("old_regime", "?")
            new_r = metadata.get("new_regime", "?")
            reasons.append(f"Regime changed from {old_r} to {new_r} mid-trade")

        # Error category
        error_cat = reflection.get("error_category", "none")
        if error_cat != "none" and not reasons:
            reasons.append(self.ERROR_EXPLANATIONS.get(error_cat, ""))

        return reasons if reasons else ["Trade hit stop loss — market moved against the position"]

    def _build_timeline(self, trade: dict) -> str:
        """Build the 'how it played out' timeline."""
        lines = [Fmt.section_header(Fmt.RULER, "HOW IT PLAYED OUT")]

        entry = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        entry_time = trade.get("entry_time", "unknown")
        exit_time = trade.get("exit_time", "unknown")
        max_dd = trade.get("max_drawdown_pct", 0)
        max_profit = trade.get("max_profit_pct", 0)

        lines.append(Fmt.bullet(f"Entry: {Fmt.format_price(entry)} at {entry_time}"))
        lines.append(Fmt.bullet(f"Exit: {Fmt.format_price(exit_price)} at {exit_time}"))

        duration = trade.get("duration")
        if duration:
            lines.append(Fmt.bullet(f"Held for: {duration}"))

        if max_dd:
            lines.append(Fmt.bullet(f"Max drawdown: {max_dd:.1f}%"))
        if max_profit:
            lines.append(Fmt.bullet(f"Max unrealized profit: +{max_profit:.1f}%"))

        return "\n".join(lines)

    def _build_indicators_worked(self, trade: dict) -> list[str]:
        """List indicators that contributed to the trade."""
        worked: list[str] = []
        metadata = trade.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        if metadata.get("rsi") is not None:
            worked.append(f"RSI at {metadata['rsi']:.0f}")
        if metadata.get("support_held"):
            worked.append(f"Support at {Fmt.format_price(metadata.get('support_level', 0))}")
        if metadata.get("volume_confirmed"):
            worked.append("Volume confirmation")
        if metadata.get("regime") == "trending":
            worked.append("Regime alignment (TRENDING)")

        return worked
