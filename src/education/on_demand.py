"""
On-Demand Education
====================

Handles on-demand educational queries:
  /learn [topic]   — Learn about a trading concept
  /best            — Show best pattern
  /worst           — Show worst pattern
  /mistakes        — What am I doing wrong
  /quiz            — Test knowledge
  /progress        — Learning progress
  /explain [id]    — Full trade breakdown
"""

from __future__ import annotations

import random
from typing import Any

from src.education.message_formatter import TelegramFormatter as Fmt

# ═══════════════════════════════════════════════════════════════════════
# LEARNING TOPICS DATABASE
# ═══════════════════════════════════════════════════════════════════════

LEARNING_TOPICS: dict[str, dict[str, str]] = {
    "rsi": {
        "title": "RSI (Relative Strength Index)",
        "explanation": (
            "RSI measures how fast prices moved recently.\n\n"
            "• RSI above 70 = OVERBOUGHT (price rose too fast, may drop)\n"
            "• RSI below 30 = OVERSOLD (price dropped too fast, may bounce)\n"
            "• RSI at 50 = NEUTRAL (no strong direction)\n\n"
            "Think of it like a rubber band — stretch it too far and it snaps back."
        ),
        "how_tsar_uses_it": (
            "I look for RSI below 30 as a BUY signal (oversold bounce) "
            "and RSI above 70 as a SELL signal (overbought pullback). "
            "I combine it with support/resistance for higher accuracy."
        ),
        "real_example": (
            "BTC RSI hit 28 at $42,000 support.\n"
            "Entered LONG → price bounced to $43,200 → WIN +2.9%\n"
            "RSI + support = 73% win rate in my history."
        ),
        "when_works": "Best in ranging markets (ADX < 25). Works on all timeframes.",
        "when_fails": "In strong trends, RSI can stay oversold/overbought for hours. Don't fight the trend.",
        "key_takeaway": "RSI is a bounce signal, not a trend signal. Use it WITH support/resistance, never alone.",
    },
    "support": {
        "title": "Support & Resistance",
        "explanation": (
            "Support = a price level where buyers step in (floor)\n"
            "Resistance = a price level where sellers step in (ceiling)\n\n"
            "The more times a level is tested and holds, the stronger it is.\n"
            "When support BREAKS, it becomes resistance (and vice versa)."
        ),
        "how_tsar_uses_it": (
            "I identify support levels by finding price points where "
            "bounces happened 3+ times. I enter LONG near support with "
            "a tight stop just below. If support breaks, I exit immediately."
        ),
        "real_example": (
            "$42,000 was tested as support 5 times.\n"
            "Each bounce gave 1-3% profit. 4/5 trades won.\n"
            "The 5th time it broke → lost 1.2% but exited fast."
        ),
        "when_works": "In ranging markets with clear levels. Works best with volume confirmation.",
        "when_fails": "During news events or sudden volume spikes. Levels break without warning.",
        "key_takeaway": "Support levels are probabilistic, not certain. Always use a stop loss below support.",
    },
    "volume": {
        "title": "Volume Analysis",
        "explanation": (
            "Volume = how many units were traded in a period.\n\n"
            "• High volume + price up = strong buying (real move)\n"
            "• High volume + price down = strong selling (real move)\n"
            "• Low volume + price move = weak move (likely to reverse)\n\n"
            "Volume confirms whether a price move is REAL or FAKE."
        ),
        "how_tsar_uses_it": (
            "I check if volume is 50%+ above average when price hits "
            "support/resistance. High volume bounce = real. Low volume "
            "bounce = likely to fail. I skip low-volume setups."
        ),
        "real_example": (
            "BTC bounced off $42,000 with +150% volume → WIN\n"
            "BTC bounced off $41,800 with -20% volume → LOSS (fake bounce)"
        ),
        "when_works": "Always useful. Volume is the truth-teller of the market.",
        "when_fails": "In low-liquidity markets, volume can be misleading due to wash trading.",
        "key_takeaway": "No volume confirmation = no trade. Volume tells you if the move is real.",
    },
    "regime": {
        "title": "Market Regime",
        "explanation": (
            "Market regime = the current 'personality' of the market.\n\n"
            "• TRENDING: Price moves in one direction (ADX > 25)\n"
            "• RANGING: Price bounces between levels (ADX < 20)\n"
            "• VOLATILE: Price swings wildly (high ATR)\n\n"
            "Different strategies work in different regimes.\n"
            "Using the wrong strategy for the regime = losses."
        ),
        "how_tsar_uses_it": (
            "I detect regime using ADX and ATR, then select the right strategy:\n"
            "• TRENDING → trend-following (ride the wave)\n"
            "• RANGING → mean-reversion (buy dips, sell rips)\n"
            "• VOLATILE → reduce size or stay out"
        ),
        "real_example": (
            "Regime TRENDING → used trend strategy → WIN +3.2%\n"
            "Regime changed to VOLATILE → same strategy → LOSS -1.5%\n"
            "Lesson: Always check regime BEFORE entering."
        ),
        "when_works": "Regime detection is most reliable on 4H+ timeframes.",
        "when_fails": "Regime changes can happen mid-trade. Need to monitor and adapt.",
        "key_takeaway": "The right strategy in the wrong regime = a wrong trade. Match strategy to regime.",
    },
    "risk_reward": {
        "title": "Risk/Reward Ratio",
        "explanation": (
            "Risk/Reward (R:R) = how much you could gain vs how much you could lose.\n\n"
            "• R:R of 2:1 = risk $1 to make $2\n"
            "• R:R of 3:1 = risk $1 to make $3\n\n"
            "With a 2:1 R:R, you only need to win 33% of trades to break even!\n"
            "With a 3:1 R:R, you only need to win 25% of trades to break even!"
        ),
        "how_tsar_uses_it": (
            "I only take trades with R:R of 2:1 or better.\n"
            "This means even with a 40% win rate, I'm still profitable.\n"
            "I calculate R:R before entry and reject setups below 2:1."
        ),
        "real_example": (
            "Trade 1: Risk $0.10, Reward $0.29 (R:R 2.9:1) → WIN +$0.29\n"
            "Trade 2: Risk $0.10, Reward $0.20 (R:R 2.0:1) → LOSS -$0.10\n"
            "Net after 2 trades: +$0.19 (still profitable despite 50% WR!)"
        ),
        "when_works": "Always. R:R is the foundation of profitable trading.",
        "when_fails": "If stop loss is too tight, you get stopped out before the move happens.",
        "key_takeaway": "Never take a trade with R:R below 2:1. It's mathematically hard to win.",
    },
    "whale": {
        "title": "Whale Watching (On-Chain)",
        "explanation": (
            "Whales = wallets holding 1,000+ BTC.\n\n"
            "When whales move BTC to cold storage = ACCUMULATION (bullish)\n"
            "When whales move BTC to exchanges = DISTRIBUTION (bearish)\n\n"
            "Whales move BEFORE big price moves. Watching them = early signals."
        ),
        "how_tsar_uses_it": (
            "I monitor whale wallet movements as a confirmation signal.\n"
            "Whale accumulation + technical buy signal = higher confidence.\n"
            "Whale distribution + technical buy signal = skip the trade."
        ),
        "real_example": (
            "Whale moved 500 BTC to cold storage.\n"
            "Next day: BTC pumped 4%. Signal was 12 hours early.\n"
            "I use whale data as confirmation, not primary signal."
        ),
        "when_works": "Best as confirmation for technical signals. 12-48h lead time.",
        "when_fails": "Whales can be wrong too. Don't blindly follow whale movements.",
        "key_takeaway": "Whale data adds confidence to technical signals. Use it as a +1, not the main reason.",
    },
    "kill_switch": {
        "title": "Kill Switch",
        "explanation": (
            "Kill switch = automatic emergency stop when things go really wrong.\n\n"
            "Triggers when:\n"
            "• Daily loss exceeds 2% of balance\n"
            "• Hourly loss exceeds 1% of balance\n"
            "• 3 consecutive losses\n"
            "• Regime changes to VOLATILE mid-trade\n\n"
            "When triggered: ALL positions closed, trading paused, alert sent."
        ),
        "how_tsar_uses_it": (
            "The kill switch is my safety net. It's not a strategy — it's insurance.\n"
            "I check kill switch conditions BEFORE and DURING every trade.\n"
            "If kill switch triggers, I stop trading and analyze what went wrong."
        ),
        "real_example": (
            "3 consecutive losses → kill switch triggered.\n"
            "Paused trading for 4 hours.\n"
            "Analysis: regime had changed to VOLATILE, didn't adapt.\n"
            "Adjusted regime detection → resumed → 4 wins in a row."
        ),
        "when_works": "Always. Kill switch saves capital during bad streaks.",
        "when_fails": "If thresholds are too tight, it triggers on normal variance.",
        "key_takeaway": "The kill switch exists to protect your capital. Respect it. Don't override it.",
    },
    "macd": {
        "title": "MACD (Moving Average Convergence Divergence)",
        "explanation": (
            "MACD shows momentum by comparing two moving averages.\n\n"
            "• MACD line crosses ABOVE signal line = bullish momentum\n"
            "• MACD line crosses BELOW signal line = bearish momentum\n"
            "• Histogram growing = momentum increasing\n"
            "• Histogram shrinking = momentum fading"
        ),
        "how_tsar_uses_it": (
            "I use MACD crossovers as entry confirmation.\n"
            "A bullish crossover + RSI oversold = strong buy signal.\n"
            "I also watch the histogram for momentum shifts."
        ),
        "real_example": (
            "MACD crossed bullish + RSI at 29 → entered LONG\n"
            "Histogram kept growing → held the trade\n"
            "WIN +2.5% as momentum continued"
        ),
        "when_works": "Best on 4H and daily timeframes. Good for confirming trend changes.",
        "when_fails": "Lagging indicator — by the time it crosses, some of the move is already done.",
        "key_takeaway": "MACD confirms momentum, it doesn't predict it. Use with leading indicators like RSI.",
    },
    "bollinger": {
        "title": "Bollinger Bands",
        "explanation": (
            "Bollinger Bands show volatility and mean reversion zones.\n\n"
            "• Upper band = overbought zone (price extended upward)\n"
            "• Lower band = oversold zone (price extended downward)\n"
            "• Bands SQUEEZING = low volatility, big move coming\n"
            "• Bands EXPANDING = high volatility, trend in progress"
        ),
        "how_tsar_uses_it": (
            "I enter when price touches the lower band + RSI oversold.\n"
            "I exit when price reaches the upper band or middle line.\n"
            "Squeeze breakouts are my favorite setups."
        ),
        "real_example": (
            "Price touched lower BB + RSI at 25 + volume spike\n"
            "Entered LONG → price reverted to middle band\n"
            "WIN +1.8% on mean reversion"
        ),
        "when_works": "Best in ranging markets. Mean reversion is very reliable with BB.",
        "when_fails": "In strong trends, price can ride the band for extended periods.",
        "key_takeaway": "BB touch is not automatic buy/sell. Confirm with RSI and volume.",
    },
}

# Alias mapping for common variations
TOPIC_ALIASES: dict[str, str] = {
    "relative strength index": "rsi",
    "relative strength": "rsi",
    "s&r": "support",
    "support and resistance": "support",
    "support/resistance": "support",
    "resistance": "support",
    "vol": "volume",
    "market regime": "regime",
    "r:r": "risk_reward",
    "risk-reward": "risk_reward",
    "risk reward": "risk_reward",
    "risk/reward": "risk_reward",
    "whale watching": "whale",
    "on-chain": "whale",
    "onchain": "whale",
    "kill switch": "kill_switch",
    "emergency stop": "kill_switch",
    "moving average convergence divergence": "macd",
    "bollinger bands": "bollinger",
    "bb": "bollinger",
    "bollinger band": "bollinger",
}


# ═══════════════════════════════════════════════════════════════════════
# QUIZ DATABASE
# ═══════════════════════════════════════════════════════════════════════

QUIZ_QUESTIONS: list[dict[str, Any]] = [
    {
        "topic": "rsi",
        "question": "RSI is at 25. What does this mean?",
        "options": [
            "A) Price is overbought — likely to drop",
            "B) Price is oversold — likely to bounce",
            "C) Price is neutral — no signal",
            "D) Price will definitely go up",
        ],
        "answer": "B",
        "explanation": "RSI below 30 = oversold. Price dropped too fast and is likely to bounce back. But it's not guaranteed — always confirm with other indicators!",
    },
    {
        "topic": "rsi",
        "question": "RSI is at 75 in a strong uptrend. Should you sell?",
        "options": [
            "A) Yes, RSI above 70 always means sell",
            "B) No, in strong trends RSI can stay overbought for a long time",
            "C) Yes, RSI is the only indicator that matters",
            "D) No, RSI doesn't work in trends",
        ],
        "answer": "B",
        "explanation": "In strong trends, RSI can stay overbought (above 70) for extended periods. RSI is a bounce signal in ranging markets, not a trend reversal signal.",
    },
    {
        "topic": "support",
        "question": "A support level has been tested 4 times and held each time. What's likely?",
        "options": [
            "A) It will definitely hold the 5th time",
            "B) Each test makes it stronger — guaranteed support",
            "C) It's probabilistic — likely to hold but could break",
            "D) Support levels don't work",
        ],
        "answer": "C",
        "explanation": "Support levels are probabilistic, not certain. More tests make them stronger, but they CAN break. Always use a stop loss below support!",
    },
    {
        "topic": "volume",
        "question": "Price bounces off support with LOW volume. Is this a good buy signal?",
        "options": [
            "A) Yes, a bounce is a bounce regardless of volume",
            "B) No, low volume bounces are often fake — skip it",
            "C) Volume doesn't matter for bounces",
            "D) Low volume means it's an even stronger signal",
        ],
        "answer": "B",
        "explanation": "Volume confirms whether a move is real. Low volume bounces are often fake and reverse quickly. Wait for high volume confirmation.",
    },
    {
        "topic": "regime",
        "question": "Market regime is VOLATILE. What should you do?",
        "options": [
            "A) Use trend-following strategy",
            "B) Use mean-reversion strategy",
            "C) Reduce position size or stay out",
            "D) Trade normally — regime doesn't matter",
        ],
        "answer": "C",
        "explanation": "In volatile regimes, price moves are unpredictable. Best to reduce position size or stay out entirely until regime stabilizes.",
    },
    {
        "topic": "risk_reward",
        "question": "You have a trade with R:R of 1.5:1 and 50% win rate. Are you profitable?",
        "options": [
            "A) Yes, 50% win rate is good",
            "B) No, with 1.5:1 R:R you need >40% WR to profit",
            "C) Yes, any positive R:R is profitable",
            "D) It depends on position size",
        ],
        "answer": "B",
        "explanation": "With R:R of 1.5:1, you need to win more than 40% of trades to break even. At 50% WR you ARE profitable, but barely. Aim for 2:1+ R:R for better margins.",
    },
    {
        "topic": "risk_reward",
        "question": "What R:R do you need to break even with a 33% win rate?",
        "options": [
            "A) 1:1",
            "B) 1.5:1",
            "C) 2:1",
            "D) 3:1",
        ],
        "answer": "C",
        "explanation": "With 33% WR, you win 1 out of 3 trades. If R:R is 2:1, you risk $1 three times (lose $2, win $2) = breakeven. That's why 2:1 is the minimum!",
    },
    {
        "topic": "whale",
        "question": "A whale moves 1000 BTC from an exchange to cold storage. What does this signal?",
        "options": [
            "A) Bearish — they're preparing to sell",
            "B) Bullish — they're accumulating (not selling)",
            "C) Neutral — doesn't mean anything",
            "D) It means the exchange is shutting down",
        ],
        "answer": "B",
        "explanation": "Moving BTC to cold storage = long-term holding = accumulation = bullish. Moving TO exchanges = preparing to sell = bearish.",
    },
    {
        "topic": "kill_switch",
        "question": "The kill switch triggers after 3 consecutive losses. What should you do?",
        "options": [
            "A) Override it and keep trading",
            "B) Stop, analyze what went wrong, then resume",
            "C) Double your position size to recover losses",
            "D) Switch to a different exchange",
        ],
        "answer": "B",
        "explanation": "The kill switch is a safety mechanism. When it triggers, stop trading, analyze the losses, identify the problem, fix it, THEN resume. Never override safety.",
    },
    {
        "topic": "macd",
        "question": "MACD histogram is shrinking while price makes new highs. What does this mean?",
        "options": [
            "A) Strong uptrend continuing",
            "B) Momentum is fading — potential reversal",
            "C) MACD is broken",
            "D) Buy more aggressively",
        ],
        "answer": "B",
        "explanation": "Shrinking histogram while price makes new highs = bearish divergence = momentum is fading. This often precedes a reversal or pullback.",
    },
    {
        "topic": "bollinger",
        "question": "Bollinger Bands are squeezing tightly. What's about to happen?",
        "options": [
            "A) Price will stay flat forever",
            "B) A big move is coming (direction unknown)",
            "C) Price will definitely go up",
            "D) The indicator is broken",
        ],
        "answer": "B",
        "explanation": "Squeezing bands = low volatility = energy building up. A big move is coming, but you don't know the direction yet. Wait for the breakout direction.",
    },
]


class OnDemandEducation:
    """Handle on-demand educational queries."""

    def __init__(self, trade_memory: Any = None, pattern_library: Any = None) -> None:
        self._trade_memory = trade_memory
        self._pattern_library = pattern_library

    # ── /learn [topic] ────────────────────────────────────────────────

    def learn_topic(self, topic: str) -> str:
        """Generate a learning message for a trading topic."""
        # Resolve aliases
        topic_key = topic.lower().strip()
        topic_key = TOPIC_ALIASES.get(topic_key, topic_key)

        if topic_key not in LEARNING_TOPICS:
            available = ", ".join(sorted(LEARNING_TOPICS.keys()))
            return (
                f"❓ Topic '{topic}' not found.\n\n"
                f"Available topics:\n{available}\n\n"
                f"Usage: /learn RSI"
            )

        t = LEARNING_TOPICS[topic_key]
        title = t["title"]
        lines = [
            f"{Fmt.BOOK} {Fmt.bold(f'LEARNING: {title}')}",
            Fmt.separator(),
            "",
            t["explanation"],
            "",
            Fmt.section_header(Fmt.LIGHTBULB, "HOW I USE IT"),
            t["how_tsar_uses_it"],
            "",
            Fmt.section_header(Fmt.CHART, "REAL EXAMPLE"),
            t["real_example"],
            "",
            Fmt.section_header(Fmt.TARGET, "WHEN IT WORKS BEST"),
            t["when_works"],
            "",
            Fmt.section_header(Fmt.WARNING, "WHEN IT FAILS"),
            t["when_fails"],
            "",
            Fmt.section_header(Fmt.BOOK, "KEY TAKEAWAY"),
            t["key_takeaway"],
            "",
            Fmt.separator(),
            "[📖 Learn More] [📊 See Example Trade] [🔙 Back]",
        ]
        return "\n".join(lines)

    def list_topics(self) -> str:
        """List all available learning topics."""
        lines = [
            f"{Fmt.BOOK} {Fmt.bold('AVAILABLE TOPICS')}",
            Fmt.separator(),
            "",
        ]
        for key, topic in LEARNING_TOPICS.items():
            lines.append(f"• /learn {key} — {topic['title']}")
        lines.append("")
        lines.append(Fmt.separator())
        lines.append("Usage: /learn [topic]")
        return "\n".join(lines)

    # ── /best ─────────────────────────────────────────────────────────

    def best_pattern(self, trades: list[dict]) -> str:
        """Show the best performing pattern."""
        pattern_stats = self._calc_pattern_stats(trades)

        if not pattern_stats:
            return "📊 Not enough data yet. Need at least 2 trades to identify patterns."

        # Find best pattern (min 2 trades)
        valid = {
            k: v
            for k, v in pattern_stats.items()
            if (v["wins"] + v["losses"]) >= 2 and v["win_rate"] >= 0.5
        }

        if not valid:
            return "📊 No patterns with 2+ trades and 50%+ win rate yet."

        best = max(valid, key=lambda k: valid[k]["win_rate"])
        stats = valid[best]
        total = stats["wins"] + stats["losses"]

        lines = [
            f"{Fmt.TARGET} {Fmt.bold('YOUR BEST PATTERN')}",
            Fmt.separator(),
            "",
            f"🔥 {Fmt.bold(best)}",
            f"• Win rate: {stats['win_rate']:.0f}% ({stats['wins']}/{total} trades)",
            f"• Net P&L: ${stats['pnl']:.2f}",
            f"• Avg P&L per trade: ${stats['pnl'] / total:.2f}",
            "",
            f"{Fmt.section_header(Fmt.LIGHTBULB, 'WHY IT WORKS')}",
        ]

        # Add insight based on pattern
        if "rsi" in best.lower() and "support" in best.lower():
            lines.append(Fmt.bullet("RSI + Support = high probability bounce setup"))
            lines.append(Fmt.bullet("Oversold at known support level = strong buying pressure"))
        elif "trend" in best.lower():
            lines.append(Fmt.bullet("Trend-following works well in trending regimes"))
            lines.append(Fmt.bullet("Letting winners run maximizes R:R"))
        else:
            lines.append(Fmt.bullet("This pattern has been consistently profitable"))
            lines.append(Fmt.bullet("Keep focusing on this setup"))

        lines.extend(["", Fmt.separator(), "[📊 Full Analysis] [🔧 Adjust Strategy]"])
        return "\n".join(lines)

    # ── /worst ────────────────────────────────────────────────────────

    def worst_pattern(self, trades: list[dict]) -> str:
        """Show the worst performing pattern."""
        pattern_stats = self._calc_pattern_stats(trades)

        if not pattern_stats:
            return "📊 Not enough data yet. Need at least 2 trades to identify patterns."

        valid = {k: v for k, v in pattern_stats.items() if (v["wins"] + v["losses"]) >= 2}

        if not valid:
            return "📊 No patterns with 2+ trades yet."

        worst = min(valid, key=lambda k: valid[k]["win_rate"])
        stats = valid[worst]
        total = stats["wins"] + stats["losses"]

        lines = [
            f"{Fmt.WARNING} {Fmt.bold('PATTERN NEEDING WORK')}",
            Fmt.separator(),
            "",
            f"❌ {Fmt.bold(worst)}",
            f"• Win rate: {stats['win_rate']:.0f}% ({stats['wins']}/{total} trades)",
            f"• Net P&L: ${stats['pnl']:.2f}",
            "",
            f"{Fmt.section_header(Fmt.LIGHTBULB, 'WHAT TO DO')}",
            Fmt.bullet("Review these trades for common mistakes"),
            Fmt.bullet("Consider reducing size on this pattern"),
            Fmt.bullet("Check if regime matches this strategy"),
            "",
            Fmt.separator(),
            "[📊 Full Analysis] [🔧 View Rules] [📖 Learn More]",
        ]
        return "\n".join(lines)

    # ── /mistakes ─────────────────────────────────────────────────────

    def mistakes_analysis(self, trades: list[dict]) -> str:
        """Analyze common mistakes across losing trades."""
        losses = [t for t in trades if self._get_outcome(t) == "loss"]
        if not losses:
            return "🎉 No losing trades to analyze! Keep it up!"

        # Count error categories
        error_counts: dict[str, int] = {}
        for trade in losses:
            reflection = self._get_reflection(trade)
            cat = reflection.get("error_category", "none")
            if cat != "none":
                error_counts[cat] = error_counts.get(cat, 0) + 1

        lines = [
            f"{Fmt.WARNING} {Fmt.bold('COMMON MISTAKES ANALYSIS')}",
            Fmt.separator(),
            "",
            f"Based on {len(losses)} losing trades:",
            "",
        ]

        ERROR_EXPLANATIONS = {
            "timing": "Entry timing was off",
            "sizing": "Position size too large",
            "regime": "Market regime changed mid-trade",
            "execution": "Execution issue (slippage/delay)",
        }

        if error_counts:
            sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
            for cat, count in sorted_errors:
                pct = count / len(losses) * 100
                explanation = ERROR_EXPLANATIONS.get(cat, cat)
                lines.append(Fmt.bullet(f"{cat}: {count}x ({pct:.0f}%) — {explanation}"))
        else:
            lines.append(Fmt.bullet("No specific error categories identified yet"))

        lines.extend(
            [
                "",
                f"{Fmt.section_header(Fmt.TARGET, 'HOW TO IMPROVE')}",
                Fmt.bullet("Review each loss with /explain [trade_id]"),
                Fmt.bullet("Check if the regime matched your strategy"),
                Fmt.bullet("Ensure R:R was at least 2:1"),
                "",
                Fmt.separator(),
                "[📊 Full Analysis] [🔧 View Rules] [📖 Learn More]",
            ]
        )
        return "\n".join(lines)

    # ── /quiz ─────────────────────────────────────────────────────────

    def get_quiz_question(self, topic: str | None = None) -> dict[str, Any] | None:
        """Get a random quiz question, optionally filtered by topic."""
        pool = QUIZ_QUESTIONS
        if topic:
            topic_key = topic.lower().strip()
            topic_key = TOPIC_ALIASES.get(topic_key, topic_key)
            pool = [q for q in QUIZ_QUESTIONS if q["topic"] == topic_key]

        if not pool:
            return None
        return random.choice(pool)

    def format_quiz_question(self, question: dict, num: int, total: int, score: int) -> str:
        """Format a quiz question for Telegram."""
        lines = [
            f"{Fmt.BRAIN} {Fmt.bold('TRADING QUIZ')}",
            Fmt.separator(),
            "",
            f"Question {num}/{total}:",
            "",
            question["question"],
            "",
        ]
        for option in question["options"]:
            lines.append(option)

        lines.extend(
            [
                "",
                f"Your score: {score}/{num - 1}",
                "",
                Fmt.separator(),
                "[A] [B] [C] [D] [Skip]",
            ]
        )
        return "\n".join(lines)

    def check_quiz_answer(self, question: dict, answer: str) -> tuple[bool, str]:
        """Check a quiz answer. Returns (correct, explanation)."""
        answer = answer.upper().strip()
        correct = answer == question["answer"]
        explanation = question["explanation"]

        if correct:
            result = f"✅ Correct! {explanation}"
        else:
            result = f"❌ Wrong! The answer is {question['answer']}.\n\n{explanation}"

        return correct, result

    # ── Helpers ───────────────────────────────────────────────────────

    def _calc_pattern_stats(self, trades: list[dict]) -> dict[str, dict]:
        """Calculate pattern statistics from trade list."""
        from collections import defaultdict

        stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})

        for trade in trades:
            reflection = self._get_reflection(trade)
            tags = reflection.get("pattern_tags", ["unknown"])
            outcome = self._get_outcome(trade)
            pnl = trade.get("pnl", 0)

            for tag in tags:
                if outcome == "win":
                    stats[tag]["wins"] += 1
                elif outcome == "loss":
                    stats[tag]["losses"] += 1
                stats[tag]["pnl"] += pnl

        for tag, s in stats.items():
            total = s["wins"] + s["losses"]
            s["win_rate"] = s["wins"] / total if total > 0 else 0

        return dict(stats)

    @staticmethod
    def _get_reflection(trade: dict) -> dict:
        """Extract reflection dict from trade."""
        import json

        reflection = trade.get("reflection", {})
        if isinstance(reflection, str):
            try:
                reflection = json.loads(reflection)
            except (json.JSONDecodeError, TypeError):
                reflection = {}
        return reflection

    @staticmethod
    def _get_outcome(trade: dict) -> str:
        """Extract outcome from trade."""
        import json

        reflection = trade.get("reflection", {})
        if isinstance(reflection, str):
            try:
                reflection = json.loads(reflection)
            except (json.JSONDecodeError, TypeError):
                reflection = {}

        outcome = reflection.get("outcome", "")
        if outcome:
            return outcome

        pnl = trade.get("pnl", 0)
        if pnl > 0.001:
            return "win"
        elif pnl < -0.001:
            return "loss"
        return "breakeven"
