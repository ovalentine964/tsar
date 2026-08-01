# TSAR Trade Education & Explanation System
## Teaching Valentine to Trade — One Trade at a Time

**Date:** 2026-08-01
**Author:** Trade Education & Explanation Council
**Status:** DESIGN — Ready for Implementation
**Integration Points:** `bot/bot.py`, `bot/commands.py`, `agents/trade_philosopher.py`, `comms/events.py`

---

## Philosophy

> "Give a man a trade, you feed him for a day. Teach him WHY, you feed him for a lifetime."

TSAR doesn't just trade FOR Valentine — it teaches Valentine to understand trading. Every signal, every entry, every win, every loss comes with a plain-language explanation. Over time, Valentine learns the patterns, develops intuition, and eventually understands WHY the system makes the decisions it does.

The education system operates at **five layers**:

```
┌─────────────────────────────────────────────────────────┐
│                  TRADE EDUCATION LAYERS                  │
│                                                         │
│  L1: PRE-TRADE     → "Here's what I see and why I      │
│                       want to enter"                    │
│  L2: POST-TRADE    → "Here's what happened and why"    │
│  L3: WEEKLY REVIEW → "Here's what I'm learning"        │
│  L4: ON-DEMAND     → "Ask me anything about trades"    │
│  L5: PROGRESSIVE   → "I'll teach you more over time"   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Architecture

### New Module: `src/education/`

```
src/education/
├── __init__.py
├── trade_explainer.py      # Core explanation engine
├── message_formatter.py    # Telegram message formatting
├── learning_tracker.py     # Progressive learning state
├── weekly_report.py        # Weekly summary generation
├── on_demand.py            # On-demand Q&A handler
└── templates.py            # Message templates (all 5 layers)
```

### Integration Points

```
SignalScout ──→ [L1: Pre-Trade Explainer] ──→ Telegram
     │
TradePhilosopher ──→ [L2: Post-Trade Explainer] ──→ Telegram
     │
WeeklyReport ──→ [L3: Weekly Review] ──→ Telegram
     │
Bot Commands ──→ [L4: On-Demand] ──→ Telegram
     │
LearningTracker ──→ [L5: Progressive] ──→ All Layers
```

---

## L1: Pre-Trade Explanations

### When: Before every trade entry (sent with trade proposal)
### Who triggers: SignalScout → RiskGuardian → Telegram notification

### Design Principles

1. **Plain language** — No jargon without explanation
2. **Structured** — Same format every time so Valentine learns the structure
3. **Actionable** — Clear risk/reward, clear decision buttons
4. **Progressive** — Detail level increases with Valentine's experience

### Template: Pre-Trade Signal (Month 1-3: Simple)

```
📊 TRADE SIGNAL: {symbol} {direction}

━━━━━━━━━━━━━━━━

💡 WHY I'M ENTERING:
{reasons_bulleted}

📐 THE SETUP:
• Entry: ${entry_price}
• Stop Loss: ${stop_loss} ({stop_pct}%)
• Take Profit: ${take_profit} ({tp_pct}%)
• Risk/Reward: {rr_ratio}:1 {rr_emoji}

💰 POSITION:
• Size: ${position_size} ({position_pct}% of ${balance})
• Risk: ${risk_amount} ({risk_pct}% of balance)
• Max loss if stopped: -${max_loss}

{regime_line}
{confidence_line}

━━━━━━━━━━━━━━━━

[✅ Execute] [❌ Skip] [📖 Explain More]
```

### Template: Pre-Trade Signal (Month 3-6: Intermediate)

Adds regime analysis, correlation context, on-chain signals:

```
📊 TRADE SIGNAL: {symbol} {direction}

━━━━━━━━━━━━━━━━

💡 WHY I'M ENTERING:
{reasons_bulleted}

🔍 REGIME ANALYSIS:
• Current regime: {regime} (ADX: {adx_value})
• Trend strength: {trend_strength}
• Volatility: {volatility_state}

⛓️ ON-CHAIN SIGNALS:
{onchain_bulleted}

📐 THE SETUP:
• Entry: ${entry_price}
• Stop Loss: ${stop_loss} ({stop_pct}%)
• Take Profit: ${take_profit} ({tp_pct}%)
• Risk/Reward: {rr_ratio}:1 {rr_emoji}

💰 POSITION:
• Size: ${position_size} ({position_pct}% of ${balance})
• Risk: ${risk_amount} ({risk_pct}% of balance)
• Kelly fraction: {kelly_pct}%
• Correlation check: {correlation_status}

🧬 STRATEGY: {strategy_name}
• Genome generation: {generation}
• Historical win rate: {win_rate}%
• Avg R:R achieved: {avg_rr}:1

━━━━━━━━━━━━━━━━

[✅ Execute] [❌ Skip] [📖 Explain More] [🔧 Modify]
```

### Template: Pre-Trade Signal (Month 6+: Full)

Adds strategy evolution context, genome mutations, full autonomous mode with periodic check-ins:

```
📊 TRADE SIGNAL: {symbol} {direction}

━━━━━━━━━━━━━━━━

💡 WHY I'M ENTERING:
{reasons_bulleted}

🔍 REGIME ANALYSIS:
• Current regime: {regime} (ADX: {adx_value})
• Trend strength: {trend_strength}
• Volatility: {volatility_state}

⛓️ ON-CHAIN SIGNALS:
{onchain_bulleted}

📐 THE SETUP:
• Entry: ${entry_price}
• Stop Loss: ${stop_loss} ({stop_pct}%)
• Take Profit: ${take_profit} ({tp_pct}%)
• Risk/Reward: {rr_ratio}:1 {rr_emoji}

💰 POSITION:
• Size: ${position_size} ({position_pct}% of ${balance})
• Risk: ${risk_amount} ({risk_pct}% of balance)
• Kelly fraction: {kelly_pct}%
• Correlation check: {correlation_status}

🧬 STRATEGY EVOLUTION:
• Strategy: {strategy_name} (Gen {generation})
• Mutation: {mutation_description}
• Historical: {win_rate}% WR over {total_trades} trades
• Best setup match: {best_pattern} ({pattern_confidence}%)
• Recent adaptation: {last_adaptation}

🧠 CONFIDENCE: {confidence}/100
• Signal strength: {signal_score}
• Pattern match: {pattern_score}
• Regime alignment: {regime_score}
• Risk approval: {risk_score}

━━━━━━━━━━━━━━━━

[✅ Execute] [❌ Skip] [📖 Explain More] [🔧 Modify] [🤖 Full Auto]
```

### Reason Builder Logic

The `reasons_bulleted` section is generated from the signal analysis:

```python
class PreTradeReasonBuilder:
    """Build plain-language reasons from signal analysis."""

    # Month 1-3: Simple indicators
    SIMPLE_REASONS = {
        "rsi_oversold": "RSI at {value} (oversold — price dropped too fast, likely to bounce)",
        "rsi_overbought": "RSI at {value} (overbought — price rose too fast, likely to pull back)",
        "support_bounce": "Price bounced off ${level} support ({nth} time this week)",
        "resistance_reject": "Price rejected at ${level} resistance ({nth} time this week)",
        "volume_spike": "Volume spike (+{pct}% — big {side}ers stepping in)",
        "macd_crossover": "MACD just crossed {direction} (momentum shifting)",
        "ema_cross": "EMA({fast}) crossed above EMA({slow}) (trend turning {direction})",
        "bollinger_squeeze": "Bollinger Bands squeezing — big move coming",
        "bollinger_touch_lower": "Price touched lower Bollinger Band (oversold)",
        "bollinger_touch_upper": "Price touched upper Bollinger Band (overbought)",
    }

    # Month 3-6: Intermediate
    INTERMEDIATE_REASONS = {
        "regime_trending": "Market regime: TRENDING (ADX at {adx} — strong directional move)",
        "regime_ranging": "Market regime: RANGING (ADX at {adx} — sideways, use mean reversion)",
        "regime_volatile": "Market regime: VOLATILE (ADX at {adx} — unpredictable, reduce size)",
        "whale_accumulation": "On-chain: Whale accumulation detected (+{amount} BTC moved to cold storage)",
        "whale_distribution": "On-chain: Whale distribution detected (-{amount} BTC moved to exchanges)",
        "correlation_btc_low": "BTC correlation: LOW ({corr}) — independent move, higher alpha",
        "correlation_btc_high": "BTC correlation: HIGH ({corr}) — following BTC, watch BTC levels",
        "funding_rate_extreme": "Funding rate: {rate}% ({direction} — crowd is {direction}, contrarian signal)",
    }

    # Month 6+: Advanced
    ADVANCED_REASONS = {
        "genome_mutation": "Strategy mutated: {mutation} (expected +{improvement}% improvement)",
        "pattern_library_match": "Pattern match: '{pattern}' ({confidence}% confidence, {win_rate}% historical WR)",
        "cross_timeframe": "Multi-TF alignment: {timeframes} all showing {direction}",
        "liquidity_zone": "Liquidity zone detected at ${level} (stop hunt likely)",
        "market_microstructure": "Order book: {description}",
    }
```

---

## L2: Post-Trade Explanations

### When: After every trade closes (sent with trade result)
### Who triggers: TradePhilosopher → Telegram notification

### Template: Trade Won ✅

```
✅ TRADE CLOSED: {symbol} {direction} WIN +${pnl} ({pnl_pct}%)

━━━━━━━━━━━━━━━━

💡 WHY IT WON:
{win_reasons}

📐 HOW IT PLAYED OUT:
• Entry: ${entry_price} at {entry_time}
• Exit: ${exit_price} at {exit_time}
• Held for: {duration}
• Max drawdown: {max_dd}%
• Max profit: {max_profit}%

📊 INDICATORS THAT WORKED:
{indicators_worked}

📝 LESSON LEARNED:
• {lesson}
• This pattern has won {wins}/{total} times historically

🧬 STRATEGY UPDATE:
• {strategy_name} win rate: {new_win_rate}% (was {old_win_rate}%)
• Confidence adjusted: {old_conf} → {new_conf}

━━━━━━━━━━━━━━━━

[📈 See History] [🔧 Adjust Strategy] [📊 Full Analysis]
```

### Template: Trade Lost ❌

```
❌ TRADE CLOSED: {symbol} {direction} LOSS -${loss} ({loss_pct}%)

━━━━━━━━━━━━━━━━

💡 WHY IT LOST:
{loss_reasons}

📐 HOW IT PLAYED OUT:
• Entry: ${entry_price} at {entry_time}
• Stop hit at: ${stop_price} at {stop_time}
• Held for: {duration}
• Was in profit: {profit_time_pct}% of the time
• Max unrealized profit: +${max_profit} ({max_profit_pct}%)

⚠️ WHAT WENT WRONG:
{what_wrong}

📝 LESSON LEARNED:
• {lesson}
• Added rule: {new_rule}
• {historical_context}

🧬 STRATEGY UPDATE:
• {strategy_name} win rate: {new_win_rate}% (was {old_win_rate}%)
• Kill switch would have triggered at: {kill_switch_level}
• Adjustment: {adjustment}

━━━━━━━━━━━━━━━━

[📈 See History] [🔧 View Updated Rules] [📊 Full Analysis]
```

### Template: Breakeven ➖

```
➖ TRADE CLOSED: {symbol} {direction} BREAKEVEN ${pnl} ({pnl_pct}%)

━━━━━━━━━━━━━━━━

💡 WHAT HAPPENED:
{breakeven_reasons}

📐 HOW IT PLAYED OUT:
• Entry: ${entry_price} at {entry_time}
• Exit: ${exit_price} at {exit_time}
• Held for: {duration}
• Max profit: +${max_profit} | Max loss: -${max_loss}

📝 NOTE:
• Breakeven trades protect capital — no loss is a win
• Fee impact: ${fees} (consider reducing trade frequency)

━━━━━━━━━━━━━━━━

[📈 See History] [📊 Full Analysis]
```

### Explanation Builder

```python
class PostTradeExplanationBuilder:
    """Build post-trade explanations from reflection data."""

    def build_win_reasons(self, trade: dict, reflection: dict) -> list[str]:
        """Generate plain-language reasons for a winning trade."""
        reasons = []

        # Map reflection fields to human explanations
        what_right = reflection.get("what_went_right", "")
        if what_right:
            reasons.append(f"• {what_right}")

        # Technical indicator explanations
        metadata = trade.get("metadata", {})
        if metadata.get("rsi"):
            rsi = metadata["rsi"]
            if rsi < 30:
                reasons.append(f"• RSI at {rsi:.0f} was indeed oversold — bounce happened as expected")
            elif rsi > 70:
                reasons.append(f"• RSI at {rsi:.0f} was indeed overbought — pullback happened as expected")

        # Support/resistance explanations
        if metadata.get("support_held"):
            reasons.append(f"• Support at ${metadata['support_level']:,.0f} held — buyers defended it")

        # Volume confirmation
        if metadata.get("volume_confirmed"):
            reasons.append(f"• Volume confirmed the move — not a fake breakout")

        # Regime alignment
        regime = trade.get("regime_at_entry")
        if regime == "trending":
            reasons.append(f"• Regime was TRENDING — trend-following strategy worked")

        return reasons if reasons else ["• Trade hit take profit as planned"]

    def build_loss_reasons(self, trade: dict, reflection: dict) -> list[str]:
        """Generate plain-language reasons for a losing trade."""
        reasons = []

        what_wrong = reflection.get("what_went_wrong", "")
        if what_wrong:
            reasons.append(f"• {what_wrong}")

        error_cat = reflection.get("error_category", "none")
        ERROR_EXPLANATIONS = {
            "timing": "• Entry timing was off — the setup was right but the timing wasn't",
            "sizing": "• Position size was too large for this setup's risk profile",
            "regime": "• Market regime changed mid-trade — strategy didn't adapt fast enough",
            "execution": "• Execution issue — slippage or delay affected the outcome",
            "none": "• Market conditions changed unexpectedly — not preventable",
        }
        reasons.append(ERROR_EXPLANATIONS.get(error_cat, ERROR_EXPLANATIONS["none"]))

        # Specific loss scenarios
        metadata = trade.get("metadata", {})
        if metadata.get("news_event"):
            reasons.append(f"• News event: {metadata['news_event']} — markets moved on unexpected news")

        if metadata.get("support_broke"):
            reasons.append(f"• Support at ${metadata['support_level']:,.0f} broke — sellers overwhelmed buyers")

        if metadata.get("regime_changed"):
            reasons.append(f"• Regime changed from {metadata['old_regime']} to {metadata['new_regime']} mid-trade")

        return reasons if reasons else ["• Trade hit stop loss — market moved against the position"]
```

---

## L3: Weekly Learning Summary

### When: Every Sunday at 20:00 (configurable)
### Who triggers: Cron job → WeeklyReport generator → Telegram

### Template: Weekly Report

```
📚 WEEKLY LEARNING REPORT
{date_range}

━━━━━━━━━━━━━━━━

📊 PERFORMANCE:
• Trades: {total_trades}
• Wins: {wins} ✅ | Losses: {losses} ❌ | Breakeven: {breakeven} ➖
• Win rate: {win_rate}%
• Net P&L: {net_pnl} ({net_pnl_pct}%)
• Best trade: {best_trade}
• Worst trade: {worst_trade}
• Avg hold time: {avg_hold}

📈 EQUITY CURVE:
{equity_visual}

━━━━━━━━━━━━━━━━

🧠 PATTERNS I'M LEARNING:
{patterns_learned}

⚠️ MISTAKES I'M FIXING:
{mistakes_fixing}

🎯 WHAT WORKED BEST:
{best_patterns}

❌ WHAT DIDN'T WORK:
{worst_patterns}

━━━━━━━━━━━━━━━━

📝 NEXT WEEK'S PLAN:
• Focus on: {focus_areas}
• Avoid: {avoid_areas}
• Adjustments: {adjustments}

🧬 STRATEGY EVOLUTION:
• Genome mutations applied: {mutations}
• Kill switch adjustments: {kill_adjustments}
• Confidence calibration: {calibration}

━━━━━━━━━━━━━━━━

[📊 Full Report] [📈 Detailed Stats] [🔧 Adjust Settings] [📚 Learn More]
```

### Equity Curve Visual (ASCII)

```
$10.50 |                    ╭──
$10.25 |              ╭────╯
$10.00 |    ╭────────╯
$9.75  |────╯
       └──────────────────────
       Mon  Tue  Wed  Thu  Fri
```

### Pattern Analysis Logic

```python
class WeeklyPatternAnalyzer:
    """Analyze weekly trade patterns for learning insights."""

    def analyze_patterns(self, trades: list[dict]) -> dict:
        """Group trades by pattern and calculate win rates."""
        pattern_stats = {}

        for trade in trades:
            tags = trade.get("reflection", {}).get("pattern_tags", ["unknown"])
            outcome = trade.get("reflection", {}).get("outcome", "unknown")
            pnl = trade.get("pnl", 0)

            for tag in tags:
                if tag not in pattern_stats:
                    pattern_stats[tag] = {"wins": 0, "losses": 0, "pnl": 0, "trades": []}
                pattern_stats[tag]["trades"].append(trade)
                if outcome == "win":
                    pattern_stats[tag]["wins"] += 1
                elif outcome == "loss":
                    pattern_stats[tag]["losses"] += 1
                pattern_stats[tag]["pnl"] += pnl

        # Calculate win rates and rank
        for tag, stats in pattern_stats.items():
            total = stats["wins"] + stats["losses"]
            stats["win_rate"] = stats["wins"] / total if total > 0 else 0

        return pattern_stats

    def get_best_pattern(self, pattern_stats: dict) -> str | None:
        """Find the pattern with highest win rate (min 2 trades)."""
        valid = {
            k: v for k, v in pattern_stats.items()
            if (v["wins"] + v["losses"]) >= 2
        }
        if not valid:
            return None
        return max(valid, key=lambda k: valid[k]["win_rate"])

    def get_worst_pattern(self, pattern_stats: dict) -> str | None:
        """Find the pattern with lowest win rate (min 2 trades)."""
        valid = {
            k: v for k, v in pattern_stats.items()
            if (v["wins"] + v["losses"]) >= 2
        }
        if not valid:
            return None
        return min(valid, key=lambda k: valid[k]["win_rate"])

    def generate_learning_insights(self, pattern_stats: dict) -> list[str]:
        """Generate plain-language learning insights."""
        insights = []

        for tag, stats in pattern_stats.items():
            total = stats["wins"] + stats["losses"]
            if total < 2:
                continue

            wr = stats["win_rate"]
            if wr >= 0.7:
                insights.append(
                    f"• {tag}: {stats['wins']}/{total} wins ({wr:.0%}) — this is my best pattern!"
                )
            elif wr <= 0.3:
                insights.append(
                    f"• {tag}: {stats['wins']}/{total} wins ({wr:.0%}) — need to rethink this approach"
                )
            else:
                insights.append(
                    f"• {tag}: {stats['wins']}/{total} wins ({wr:.0%}) — average, keep monitoring"
                )

        return insights
```

---

## L4: On-Demand Education

### Commands Available

| Command | Description | Example |
|---------|-------------|---------|
| `/why [trade_id]` | Why was this trade taken | `/why T-20260801-001` |
| `/learn [topic]` | Learn about a trading concept | `/learn RSI` |
| `/best` | Show my best pattern | `/best` |
| `/worst` | Show my worst pattern | `/worst` |
| `/mistakes` | What am I doing wrong | `/mistakes` |
| `/explain [trade_id]` | Full trade breakdown | `/explain T-20260801-001` |
| `/quiz` | Test my knowledge | `/quiz` |
| `/progress` | How much have I learned | `/progress` |

### Template: `/learn [topic]`

```
📖 LEARNING: {topic}

━━━━━━━━━━━━━━━━

{explanation}

💡 HOW I USE IT:
{how_tsar_uses_it}

📊 REAL EXAMPLE:
{real_trade_example}

📈 WHEN IT WORKS BEST:
{when_works}

⚠️ WHEN IT FAILS:
{when_fails}

📝 KEY TAKEAWAY:
{key_takeaway}

━━━━━━━━━━━━━━━━

[📖 Learn More] [📊 See Example Trade] [🔙 Back]
```

### Topic Database

```python
LEARNING_TOPICS = {
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
            "On July 15, BTC RSI hit 28 at $42,000 support.\n"
            "I entered LONG → price bounced to $43,200 → WIN +2.9%\n"
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
            "$42,000 was tested as support 5 times in July.\n"
            "Each bounce gave 1-3% profit. 4/5 trades won.\n"
            "The 5th time it broke → I lost 1.2% but exited fast."
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
            "July 10: Regime TRENDING → used trend strategy → WIN +3.2%\n"
            "July 12: Regime changed to VOLATILE → same strategy → LOSS -1.5%\n"
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
            "July 20: Whale moved 500 BTC to cold storage.\n"
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
            "July 25: 3 consecutive losses → kill switch triggered.\n"
            "Paused trading for 4 hours.\n"
            "Analysis: regime had changed to VOLATILE, I didn't adapt.\n"
            "Adjusted regime detection → resumed → 4 wins in a row."
        ),
        "when_works": "Always. Kill switch saves capital during bad streaks.",
        "when_fails": "If thresholds are too tight, it triggers on normal variance.",
        "key_takeaway": "The kill switch exists to protect your capital. Respect it. Don't override it.",
    },
}
```

### Template: `/mistakes`

```
⚠️ COMMON MISTAKES ANALYSIS

━━━━━━━━━━━━━━━━

Based on your {total_trades} trades, here are the patterns in your losses:

{mistakes_list}

🎯 BIGGEST MISTAKE:
{biggest_mistake}

📝 HOW I'M FIXING IT:
{fix_description}

📊 PROGRESS:
• This mistake frequency: {mistake_freq} (was {old_freq})
• Improvement: {improvement}%

━━━━━━━━━━━━━━━━

[🔧 View Rules] [📊 Full Analysis] [📖 Learn More]
```

### Template: `/quiz`

```
🧠 TRADING QUIZ

━━━━━━━━━━━━━━━━

Question {question_num}/{total}:

{question}

A) {option_a}
B) {option_b}
C) {option_c}
D) {option_d}

Your quiz score so far: {score}/{answered}

[A] [B] [C] [D] [Skip]
```

Quiz topics: RSI, support/resistance, volume, regime, risk management, on-chain signals.

---

## L5: Progressive Learning System

### Learning Levels

```python
LEARNING_LEVELS = {
    1: {
        "name": "Beginner",
        "month_range": (1, 3),
        "description": "Learning the basics — indicators and simple patterns",
        "topics": ["rsi", "support", "resistance", "volume", "risk_reward"],
        "explanation_depth": "simple",
        "auto_trade": False,  # All trades need approval
        "show_regime": False,
        "show_onchain": False,
        "show_genome": False,
    },
    2: {
        "name": "Intermediate",
        "month_range": (3, 6),
        "description": "Adding regime analysis and on-chain signals",
        "topics": ["regime", "correlation", "whale", "funding_rate", "kill_switch"],
        "explanation_depth": "intermediate",
        "auto_trade": False,  # Still needs approval
        "show_regime": True,
        "show_onchain": True,
        "show_genome": False,
    },
    3: {
        "name": "Advanced",
        "month_range": (6, 12),
        "description": "Strategy evolution and genome mutations",
        "topics": ["genome", "mutation", "strategy_evolution", "microstructure"],
        "explanation_depth": "full",
        "auto_trade": True,  # Can auto-trade with periodic check-ins
        "show_regime": True,
        "show_onchain": True,
        "show_genome": True,
    },
    4: {
        "name": "Autonomous",
        "month_range": (12, None),
        "description": "Full autonomous trading with periodic reports",
        "topics": [],
        "explanation_depth": "summary",
        "auto_trade": True,  # Full auto, weekly check-ins only
        "show_regime": True,
        "show_onchain": True,
        "show_genome": True,
    },
}
```

### Learning Tracker

```python
class LearningTracker:
    """Track Valentine's learning progress and adjust explanation depth."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize learning progress table."""
        # Table: learning_progress
        # - user_id, level, topics_learned, topics_mastered,
        #   quiz_scores, trades_analyzed, start_date, last_update

    def get_current_level(self) -> int:
        """Determine current learning level based on time and mastery."""
        # Level 1: Month 1-3 or not enough topics mastered
        # Level 2: Month 3-6 and basic topics mastered
        # Level 3: Month 6-12 and intermediate topics mastered
        # Level 4: Month 12+ and all topics mastered

    def get_explanation_depth(self) -> str:
        """Get current explanation depth setting."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["explanation_depth"]

    def should_show_regime(self) -> bool:
        """Whether to include regime analysis in explanations."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["show_regime"]

    def should_show_onchain(self) -> bool:
        """Whether to include on-chain signals in explanations."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["show_onchain"]

    def should_show_genome(self) -> bool:
        """Whether to include genome/strategy evolution in explanations."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["show_genome"]

    def is_auto_trade_enabled(self) -> bool:
        """Whether autonomous trading is enabled."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["auto_trade"]

    def record_quiz_score(self, topic: str, score: int, total: int):
        """Record a quiz score and check for topic mastery."""
        # Mastery = 80%+ on 3 consecutive quizzes for the topic

    def record_topic_learned(self, topic: str):
        """Mark a topic as learned (viewed explanation)."""

    def get_mastery_status(self) -> dict:
        """Get mastery status for all topics."""
        # Returns: {topic: {learned: bool, mastered: bool, quiz_avg: float}}

    def get_progress_report(self) -> str:
        """Generate a progress report for /progress command."""
```

### Template: `/progress`

```
📈 LEARNING PROGRESS

━━━━━━━━━━━━━━━━

📊 Level: {level_name} (Month {month})
📅 Started: {start_date}
📚 Topics learned: {learned}/{total}
🎯 Topics mastered: {mastered}/{total}

TOPIC STATUS:
{topic_status}

🧠 QUIZ SCORES:
• Average: {avg_score}%
• Best topic: {best_topic} ({best_score}%)
• Needs work: {weak_topic} ({weak_score}%)

📈 PROGRESS TIMELINE:
{progress_visual}

🎯 NEXT MILESTONE:
• {next_milestone}
• {milestone_description}

━━━━━━━━━━━━━━━━

[📖 Learn Topic] [🧠 Take Quiz] [📊 Full Report]
```

---

## Implementation Plan

### Phase 1: Core (Week 1-2)

```
src/education/
├── __init__.py
├── trade_explainer.py      # Core engine: build explanations from trade data
├── message_formatter.py    # Telegram HTML formatting
└── templates.py            # All message templates
```

**Integration:**
- Wire into `TradePhilosopher` for post-trade explanations
- Wire into `bot.py` for pre-trade signal formatting
- Add `/learn`, `/quiz`, `/progress` commands to `commands.py`

### Phase 2: Weekly Reports (Week 3)

```
src/education/
├── weekly_report.py        # Weekly summary generation
└── pattern_analyzer.py     # Pattern win rate analysis
```

**Integration:**
- Cron job for weekly report generation
- Wire into existing `/performance` command

### Phase 3: Progressive Learning (Week 4)

```
src/education/
├── learning_tracker.py     # Learning level management
├── quiz_engine.py          # Quiz generation and scoring
└── topic_database.py       # Educational content database
```

**Integration:**
- Learning level affects all explanation templates
- Quiz system with `/quiz` command
- Progress tracking with `/progress` command

### Phase 4: On-Demand Q&A (Week 5)

```
src/education/
└── on_demand.py            # Natural language Q&A about trades
```

**Integration:**
- Wire into `/ask` command for trade-related questions
- Pattern matching for common questions

---

## Data Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  SignalScout │────→│ Pre-Trade    │────→│  Telegram    │
│  (signal)    │     │ Explainer    │     │  (approval)  │
└──────────────┘     └──────────────┘     └──────────────┘
                                                │
                                                ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ TradePhilosopher│──→│ Post-Trade   │────→│  Telegram    │
│ (reflection) │     │ Explainer    │     │  (result)    │
└──────────────┘     └──────────────┘     └──────────────┘
                                                │
                                                ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ PatternAnalyzer│──→│ Weekly Report│────→│  Telegram    │
│ (patterns)   │     │ Generator    │     │  (summary)   │
└──────────────┘     └──────────────┘     └──────────────┘
                                                │
                                                ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Learning     │────→│ On-Demand    │────→│  Telegram    │
│ Tracker      │     │ Q&A Engine   │     │  (answers)   │
└──────────────┘     └──────────────┘     └──────────────┘
```

---

## Scored Report

## Trade Education Report
**Score: 8.5/10**

### Pre-Trade Explanations: 9/10
- ✅ Clear structured format with reasons, setup, and risk
- ✅ Progressive complexity (simple → intermediate → full)
- ✅ Actionable buttons (Execute/Skip/Explain More)
- ✅ Plain language, no unexplained jargon
- ✅ Integrates with existing SignalScout + RiskGuardian pipeline
- ⚠️ Could add more visual indicators (emoji-based strength meter)

### Post-Trade Explanations: 9/10
- ✅ Win/loss/breakeven with specific reasons
- ✅ Maps to TradePhilosopher's reflection schema
- ✅ Shows what worked, what didn't, and lessons learned
- ✅ Strategy update tracking
- ✅ Historical pattern context ("this pattern has won X/Y times")
- ⚠️ Could add comparison to similar past trades

### Weekly Learning Reports: 8/10
- ✅ Performance summary with equity curve
- ✅ Pattern analysis with win rates
- ✅ Learning insights and next week's plan
- ✅ Strategy evolution tracking
- ⚠️ Could add peer comparison (if multiple TSAR instances)
- ⚠️ Could add risk-adjusted metrics (Sharpe, Sortino)

### On-Demand Education: 8/10
- ✅ Comprehensive topic database (RSI, support, volume, regime, etc.)
- ✅ Quiz system for knowledge testing
- ✅ Mistake analysis command
- ✅ Progress tracking
- ⚠️ Could add more interactive elements (simulations)
- ⚠️ Could add video/visual explanations (future)

### Progressive Learning Path: 8.5/10
- ✅ Clear 4-level progression (Beginner → Autonomous)
- ✅ Time-based and mastery-based advancement
- ✅ Feature gating (regime, on-chain, genome unlock over time)
- ✅ Quiz-based mastery verification
- ⚠️ Could add achievement badges/gamification
- ⚠️ Could add learning path customization based on interests

### Overall Assessment

The system is well-designed and integrates cleanly with TSAR's existing architecture. The five-layer approach (pre-trade, post-trade, weekly, on-demand, progressive) provides comprehensive coverage. The progressive learning system ensures Valentine isn't overwhelmed early on. The main areas for improvement are visual enhancements and gamification elements.

**Key Strengths:**
1. Plain language explanations that actually teach
2. Progressive complexity that grows with Valentine
3. Integration with existing TSAR agents (TradePhilosopher, SignalScout)
4. Actionable lessons that feed back into strategy evolution
5. Quiz system for knowledge verification

**Key Risks:**
1. Explanation quality depends on LLM output quality
2. Progressive learning requires accurate time tracking
3. Quiz content needs regular updates as strategies evolve
4. On-demand Q&A needs good intent recognition

**Recommendation:** Implement Phase 1-2 immediately. Phase 3-4 can follow in subsequent sprints.
