# TSAR Telegram Conversational Experience Design
## Full UX Flow for Valentine Cohusdex (Kenya, $10, Crypto-Only)

**Date:** 2026-08-01  
**Author:** Telegram UX & Conversational Design Council  
**Target User:** Valentine Cohusdex — Kenya-based, $10 starting capital, crypto only  
**Platform:** Telegram Bot (python-telegram-bot + inline keyboards)  
**Score:** See bottom

---

## Table of Contents

1. [First-Time Setup (Onboarding)](#1-first-time-setup-onboarding)
2. [Daily Interaction (Post-Setup)](#2-daily-interaction-post-setup)
3. [Command Design](#3-command-design)
4. [Conversational Intelligence](#4-conversational-intelligence)
5. [Message Templates](#5-message-templates)
6. [Error Handling & Edge Cases](#6-error-handling--edge-cases)
7. [Accessibility & Localization](#7-accessibility--localization)
8. [Scored Report](#8-scored-report)

---

## 1. First-Time Setup (Onboarding)

### Philosophy
- **Conversational, not command-driven.** The user talks to TSAR like a friend, not a terminal.
- **One thing at a time.** Never dump a wall of text. Each step is a single question.
- **Validate immediately.** Don't wait until step 4 to say "step 1 was wrong."
- **Allow escape hatches.** `/skip` for optional, `/cancel` anytime, `/back` to retry.
- **Celebrate progress.** Small wins at each step, big win at the end.

### Flow Diagram

```
User sends /start (or any first message)
    │
    ▼
┌─────────────────────────────────┐
│  WELCOME MESSAGE                │
│  Who TSAR is, what it does      │
│  "Ready? Let's get you set up." │
│  [Let's Go ⚡]  [Tell Me More]  │
└──────────────┬──────────────────┘
               │
    ┌──────────┴──────────┐
    ▼                     ▼
[Let's Go]          [Tell Me More]
    │                     │
    │                     ▼
    │              ┌──────────────┐
    │              │ DETAILED     │
    │              │ EXPLANATION  │
    │              │ + FAQ        │
    │              │ [Let's Go ⚡]│
    │              └──────┬───────┘
    │                     │
    └──────────┬──────────┘
               ▼
┌─────────────────────────────────┐
│  STEP 1/4: Exchange API Key     │
│  "Which exchange do you use?"   │
│  [Binance] [Bybit] [Other]     │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  STEP 2/4: Exchange API Secret  │
│  "Paste your API secret"        │
│  (auto-validates connection)    │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  STEP 3/4: Telegram Bot Token   │
│  "Paste your bot token from     │
│   @BotFather"                   │
│  [How?] [Skip — use TSAR's bot] │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  STEP 4/4: Trading Mode         │
│  "Start in paper mode (no real  │
│   money) or live?"              │
│  [Paper 📝] [Live 🔴]          │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  CELEBRATION                    │
│  "🚀 You're live!"              │
│  Summary of settings            │
│  First action suggestion        │
│  [Scan Now 🔍] [Explore 📊]    │
└─────────────────────────────────┘
```

### Step-by-Step Messages

#### Trigger: User sends `/start` or any first message

```
🤖 TSAR

Hey Valentine! I'm TSAR — your autonomous trading super agent.

I find trades, manage risk, and compound your capital. You stay in control. I do the heavy lifting.

Here's what makes me different:
• I learn from every trade (the flywheel never stops)
• Risk management is deterministic — no guessing
• You approve every trade before I execute
• Starting with $10? Perfect. I'm built for micro-capital.

Ready to set up? Takes about 2 minutes.

[Let's Go ⚡]  [Tell Me More ℹ️]
```

**Button: "Tell Me More"**
```
Here's the full picture:

🔍 Signal Scout — scans markets 24/7 for statistical edges
🛡️ Risk Guardian — checks every trade against 10 safety rules
🎯 Execution Sniper — places orders with precision
🧠 Trade Philosopher — learns from every outcome
🧬 Strategy Geneticist — evolves strategies over time

The flywheel: Trade → Observe → Reflect → Extract → Adapt → Better Trade

Your $10 compounds. My knowledge compounds. We grow together.

Starting capital: $10
Market: Crypto (BTC, ETH, SOL)
Mode: Paper trading first (no real money until you're ready)

[Let's Go ⚡]
```

---

#### STEP 1/4: Exchange Setup

```
Step 1 of 4 — Exchange Connection 🔗

Which exchange do you use?

[Binance 🟡]  [Bybit ⬛]  [Other 🔄]
```

**User taps "Binance"**
```
Great choice. Binance is solid for micro-capital.

I need two things from you:
1. API Key
2. API Secret

To get them:
1. Open Binance → Profile → API Management
2. Click "Create API" → Label it "TSAR"
3. Enable "Enable Spot Trading" only
4. Copy the API Key and paste it here

⚠️ Never share these with anyone else. I encrypt them before storing.

Paste your API Key:
```

**User pastes valid-looking key:**
```
✅ Got it. API Key saved securely.

Now paste your API Secret:
```

**User pastes invalid key (wrong format):**
```
❌ That doesn't look right. A Binance API key is usually 64 characters.

Double-check:
• Go to Binance → API Management
• Copy the key labeled "API Key" (not "Secret Key")

Try again:
```

**User types `/skip`:**
```
⏭️ Skipping exchange setup.

You can add your API keys later with /settings → Exchange.

For now, TSAR will run in paper mode with simulated trades.
```

**User types `/cancel`:**
```
🛑 Setup cancelled.

No worries! Resume anytime with /start.

Your progress is saved. I'll pick up where we left off.
```

---

#### STEP 2/4: API Secret + Connection Test

```
Step 2 of 4 — Verify Connection 🔐

Paste your Binance API Secret:
```

**User pastes secret:**
```
🔄 Testing connection...

⏳ Connecting to Binance...
```

**Success:**
```
✅ Connected! Your Binance account is linked.

Account balance: $10.00 USDT
Trading enabled: Spot
Permissions: Read + Trade (no withdrawal — safe)

Step 3 coming up...
```

**Failure (wrong secret):**
```
❌ Connection failed. The secret doesn't match the key.

This happens when:
• You copied the "Secret Key" instead of the API Secret
• The key was regenerated on Binance
• There's a typo (extra space at the end?)

Paste your API Secret again:
```

**Failure (IP restriction):**
```
❌ Connection blocked by Binance IP restriction.

Your API key has an IP whitelist. Add this server's IP:
`123.45.67.89`

To add it:
1. Binance → API Management → Edit API Key
2. Under "IP Access Restrictions" → "Restrict access to trusted IPs only"
3. Add the IP above
4. Save and paste your secret again

[Retry 🔄]  [Skip for now ⏭️]
```

---

#### STEP 3/4: Telegram Bot Token

```
Step 3 of 4 — Telegram Setup 📱

Do you have your own Telegram bot token?

[Yes, paste it]  [No, use TSAR's built-in bot]  [How do I get one?]
```

**User taps "How do I get one?"**
```
Easy! 30 seconds:

1. Open Telegram → search @BotFather
2. Send /newbot
3. Name it (e.g., "My TSAR Bot")
4. Copy the token (looks like: 123456:ABC-DEF...)
5. Paste it here

[Got it, paste now]  [Use built-in bot instead]
```

**User pastes token:**
```
🔄 Verifying bot token...
```

**Success:**
```
✅ Bot verified! "@my_tsar_bot" is ready.

I'll send all trade alerts and notifications through this bot.

Final step...
```

**Failure:**
```
❌ That token isn't valid. It should look like:
`123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

Check @BotFather → /mybots → select your bot → API Token

Try again:
```

---

#### STEP 4/4: Trading Mode

```
Step 4 of 4 — How should we start? 🎯

You have $10 to work with. I recommend starting in paper mode — 
practice with simulated trades, no real money at risk.

When you're confident, switch to live with one command.

[Paper Mode 📝]  [Live Mode 🔴]
```

**User taps "Paper Mode":**
```
Smart choice. Here's what paper mode does:

✅ Executes simulated trades based on real market data
✅ Tracks P&L as if it were real
✅ Builds your trade memory and lessons
✅ Zero risk — learn the system first

You can switch to live anytime with:
/settings → Trading Mode → Live

Let's go!
```

**User taps "Live Mode":**
```
⚠️ Live trading with real money.

Before we proceed, I need you to confirm:

• You understand trading involves risk of loss
• You're starting with $10 — money you can afford to lose
• TSAR uses a 2% risk-per-trade limit (max $0.20 per trade)
• The kill switch (/stop) halts everything instantly

[Yes, I understand — go live]  [Actually, paper mode first]
```

**User confirms live:**
```
✅ Live mode enabled.

Safety settings locked in:
• Risk per trade: 2% ($0.20)
• Max daily loss: -2% ($0.20) → auto-halt
• Kill switch: /stop anytime

You're in control. Let's grow this.
```

---

#### CELEBRATION

```
🚀 You're live, Valentine!

Here's your setup:
━━━━━━━━━━━━━━━━
🔗 Exchange: Binance
💰 Starting capital: $10.00
📊 Mode: Paper (simulated)
🛡️ Risk limit: 2% per trade
🎯 Markets: BTC/USDT, ETH/USDT

Your first move:

[Scan for Signals 🔍]  [View Dashboard 📊]
```

**User taps "Scan for Signals":**
```
🔍 Scanning markets...

Checking:
• BTC/USDT — RSI, MACD, volume patterns
• ETH/USDT — momentum, support/resistance

⏳ This takes about 30 seconds. I'll message you when I find something.

Meanwhile, here are some commands:
/status — your dashboard
/help — all commands
/ask — ask me anything
```

---

### Onboarding State Machine

```python
# State tracking per user
ONBOARDING_STATES = {
    "new": "WELCOME",
    "exchange_select": "EXCHANGE_SELECT",
    "api_key": "API_KEY_INPUT",
    "api_secret": "API_SECRET_INPUT",
    "connection_test": "CONNECTION_TEST",
    "telegram_token": "TELEGRAM_TOKEN_INPUT",
    "trading_mode": "TRADING_MODE_SELECT",
    "live_confirm": "LIVE_CONFIRMATION",
    "complete": "SETUP_COMPLETE",
}

# Resume logic: if user sends /start and state != "complete",
# pick up from last incomplete step.
```

---

## 2. Daily Interaction (Post-Setup)

### 2.1 Morning Briefing

**Trigger:** Sent automatically at 07:00 EAT (UTC+3, Kenya time)

```
☀️ Good morning, Valentine!

Here's your overnight summary:
━━━━━━━━━━━━━━━━
📈 Trades: 2 executed
💰 P&L: +$0.50 (+5.0%)
🎯 Win rate today: 100% (2/2)
🛡️ Risk: All limits healthy
🌊 Regime: RANGING (confidence: 72%)

Top trade:
• BTC/USDT LONG → +$0.35 (+3.5%)
  Entry: $67,420 → Exit: $67,655
  Strategy: mean_reversion

Flywheel update:
• 1 new lesson extracted
• Strategy genome fitness: 0.78 (+0.02)

[View Full Report 📊]  [Scan Now 🔍]
```

**If no trades overnight:**
```
☀️ Good morning, Valentine!

Quiet night — no trades executed.

📊 Market regime: HIGH_VOLATILITY (confidence: 85%)
💭 TSAR held back due to elevated volatility. Smart risk management.

Current balance: $10.50
Total P&L: +$0.50 (+5.0%)

[Scan Now 🔍]  [View Dashboard 📊]
```

**If losses overnight:**
```
☀️ Good morning, Valentine.

Overnight summary:
━━━━━━━━━━━━━━━━
📉 Trades: 1 executed
💰 P&L: -$0.15 (-1.5%)
🛡️ Risk: Within limits (daily: -1.5% / -2.0% cap)

What happened:
• ETH/USDT SHORT → -$0.15
  Unexpected momentum reversal. Stop-loss triggered.
  Lesson extracted: "Momentum exhaustion signals need volume confirmation"

Your risk management held. That's the system working.

[View Trade Details 📋]  [Check Risk State 🛡️]
```

---

### 2.2 Trade Alerts

**When a signal passes Risk Guardian:**

```
📈 Signal Detected

BTC/USDT LONG
━━━━━━━━━━━━━━━━
💰 Entry: $67,420
🎯 Target: $68,100 (+1.0%)
🛑 Stop: $67,050 (-0.55%)
📊 R:R = 1:1.8
📊 Score: 78/100
[███████░░░]

Why:
• RSI(14) = 28.3 (oversold)
• MACD bullish crossover on 1H
• Volume spike: 2.3x average
• Support zone: $67,000-$67,200

Risk: $0.20 (2% of portfolio)
Kelly: 0.25 (conservative)

Risk Guardian: ✅ APPROVED

[✅ Execute]  [❌ Pass]  [💬 Discuss]
```

**User taps "Execute":**
```
✅ Trade executed!

BTC/USDT LONG
• Entry: $67,420
• Size: 0.00015 BTC ($10.11)
• Stop: $67,050
• Target: $68,100

Monitoring... I'll update you on progress.

[View Position 📂]  [Set Alert 🔔]
```

**User taps "Pass":**
```
⏭️ Signal passed.

BTC/USDT LONG skipped. No trade taken.

I'll keep scanning. Next signal when ready.
```

**User taps "Discuss":**
```
💬 Let's talk about this BTC/USDT signal.

What's on your mind?

• Want me to explain the reasoning in more detail?
• Concerned about a specific aspect?
• Want to adjust entry/stop/target?

Type your question or pick one:
[Why RSI oversold?] [Show me the chart] [Adjust parameters]
```

---

### 2.3 Risk Alerts

**Approaching daily loss limit:**
```
⚠️ Risk Alert

Daily loss approaching -2% limit.

━━━━━━━━━━━━━━━━
Current: -1.5% (-$0.15)
Limit: -2.0% (-$0.20)
Remaining: -0.5% (-$0.05)
━━━━━━━━━━━━━━━━

Status: 🟡 YELLOW — New trades reduced to 50% size

If we hit -2%, TSAR will:
• Stop opening new trades
• Keep monitoring existing positions
• Resume tomorrow with fresh limits

Current open positions:
• ETH/USDT SHORT — -$0.12 (monitoring)

[View Risk State 🛡️]  [Adjust Limits ⚙️]
```

**Kill switch triggered:**
```
🛑 KILL SWITCH ACTIVATED

Daily loss hit -3%. All trading halted.

━━━━━━━━━━━━━━━━
• All open positions closed
• No new trades until manual resume
• Tomorrow's limits reset automatically
━━━━━━━━━━━━━━━━

This is the system protecting your capital. It's doing its job.

To resume early: /start confirm
Or wait until tomorrow — limits reset at midnight UTC.

[View Closed Positions 📋]  [Why Did This Happen? 🤔]
```

---

### 2.4 Milestone Celebrations

**Balance milestone:**
```
🎉 Milestone: $50 reached!

You started with $10. Now at $50.

━━━━━━━━━━━━━━━━
💰 Total return: +400%
📅 Days active: 47
🎯 Win rate: 62%
📈 Trades: 134
🧠 Lessons learned: 23
━━━━━━━━━━━━━━━━

You're in the top 22% of traders on TSAR.

The flywheel is compounding. Every trade makes the next one smarter.

What's next?
• /risk — tighten risk limits for larger capital
• /strategy — review which strategies got you here
• /history — see your best and worst trades

Keep going. 🚀
```

**Win streak:**
```
🔥 5 wins in a row!

Current streak: 5 trades, +$2.30

Anti-greed guard active: sizing capped at 70% base.
This prevents overconfidence from turning wins into losses.

Your system is working. Trust it.

[View Streak Details 📊]
```

**Flywheel milestone:**
```
🧬 Flywheel milestone: 100 lessons extracted!

Your trade memory now contains:
• 100 lessons from 312 trades
• 12 validated patterns
• 3 strategy genome mutations applied

The system is measurably smarter than when you started.
Signal accuracy: 54% → 61% (+7%)
Average R:R: 1:1.8 → 1:2.1 (+17%)

That's the flywheel working. Trade → Learn → Adapt → Better Trade.

[View Lessons 📚]  [View Patterns 🔍]
```

---

### 2.5 Proactive Check-Ins

**No trades in 3 days:**
```
👋 Hey Valentine! It's been 3 days since your last trade.

Markets have been active — I've been scanning but nothing met your quality threshold.

Want me to:
• Lower the minimum signal score (currently 0.6) to find more opportunities?
• Scan additional pairs (currently: BTC, ETH)?
• Explain what I've been seeing in the markets?

[Scan Now 🔍]  [Lower Threshold ⚡]  [Market Report 📊]
```

**Market regime change:**
```
🌊 Regime Change Detected

Market shifted: RANGING → STRONG_TREND_UP

━━━━━━━━━━━━━━━━
Previous: RANGING (confidence: 72%)
Current: STRONG_TREND_UP (confidence: 81%)
Trigger: BTC broke $68,000 resistance with volume
━━━━━━━━━━━━━━━━

What this means for you:
• Trend-following strategies now favored
• Mean reversion strategies temporarily paused
• Position sizes may increase (trend = higher confidence)

I've adjusted strategy weights automatically.

[View Strategy Changes 📊]  [Explain Regime 🌊]
```

---

## 3. Command Design

### Command Menu (registered with BotFather)

```
start - Start or resume TSAR setup
stop - Emergency stop (kill switch)
status - Your dashboard: balance, P&L, positions, risk
trade - Start/stop trading, view active strategies
risk - Risk settings and current state
history - Recent trades with outcomes
settings - Change configuration
help - Context-aware help
ask - Ask TSAR anything
```

### /status — Dashboard

```
🏰 TSAR Dashboard
━━━━━━━━━━━━━━━━

💰 Balance: $12.50
📈 Total P&L: +$2.50 (+25.0%)
📊 Today: +$0.50 (+5.0%)

📂 Open Positions: 2
• BTC/USDT LONG — +$0.30
• ETH/USDT SHORT — +$0.20

🛡️ Risk Level: 🟢 GREEN
• Daily loss: -0.5% / -2.0% cap
• Drawdown: -1.2% / -5.0% cap
• Kill switch: ✅ Off

🌊 Regime: RANGING (72%)
🧬 Flywheel: 0.78 (Healthy)
📊 Win Rate: 62% (134 trades)

[Trade 📈] [Risk 🛡️] [History 📋]
```

### /trade — Trading Control

**No arguments:**
```
📈 Trading Control
━━━━━━━━━━━━━━━━

Status: 🟢 ACTIVE
Mode: Paper
Strategy: mean_reversion

Active Strategies:
• mean_reversion (weight: 0.6)
• momentum_breakout (weight: 0.4)

Last signal: 2h ago (BTC/USDT — passed)
Next scan: ~15 minutes

[Start ▶️] [Stop ⏸️] [View Strategies 📊]
```

**With "stop" argument or button:**
```
⏸️ Trading paused.

No new signals will be executed.
Open positions continue to be monitored.

Resume with: /trade start
Or: [Resume ▶️]
```

### /risk — Risk State

```
🛡️ Risk State
━━━━━━━━━━━━━━━━

🚦 Level: 🟢 GREEN
📉 Daily P&L: -0.5% (limit: -2.0%)
📉 Max Drawdown: -1.2% (limit: -5.0%)
📂 Open Positions: 2/3
📊 Today's Trades: 4/30

Limits:
• Risk per trade: 2% ($0.25)
• Max position: 15% ($1.88)
• Stop-loss required: ✅
• Min R:R: 1:2.0

Anti-Behavioral Guards:
• Revenge guard: ✅ Inactive
• Greed guard: ✅ Inactive
• FOMO guard: ✅ Active (min score: 0.6)

[Adjust Limits ⚙️] [View History 📋]
```

### /history — Trade History

```
📋 Recent Trades (last 7 days)
━━━━━━━━━━━━━━━━

✅ BTC/USDT LONG — +$0.35 (3.5%)
   Entry: $67,420 → Exit: $67,655
   Strategy: mean_reversion | 2h ago

❌ ETH/USDT SHORT — -$0.15 (-1.5%)
   Entry: $3,520 → Exit: $3,573
   Strategy: momentum_breakout | 5h ago

✅ SOL/USDT LONG — +$0.22 (2.2%)
   Entry: $148.50 → Exit: $151.80
   Strategy: mean_reversion | 1d ago

━━━━━━━━━━━━━━━━
7-day: +$0.42 (+4.2%) | 8 trades | 62.5% WR

[Full History 📚] [By Strategy 📊] [Export 📤]
```

### /settings — Configuration

```
⚙️ Settings
━━━━━━━━━━━━━━━━

🔗 Exchange: Binance (connected)
💰 Capital: $10.00
📊 Mode: Paper
🎯 Strategy: mean_reversion
🛡️ Risk: 2% per trade
⏰ Timezone: Africa/Nairobi (UTC+3)
🔔 Alerts: All enabled

[Trading ⚙️] [Risk 🛡️] [Notifications 🔔] [Exchange 🔗]
```

**Sub-menu: Trading**
```
⚙️ Trading Settings
━━━━━━━━━━━━━━━━

📊 Mode: Paper
• Switch to live: requires confirmation

🎯 Active Strategies:
• mean_reversion (0.6) ✅
• momentum_breakout (0.4) ✅

📋 Pairs: BTC/USDT, ETH/USDT
• Add pair: type symbol (e.g., SOL/USDT)

⏰ Scan Frequency: Every 15 min
• Options: 5m, 15m, 30m, 1h

[Switch to Live 🔴] [Edit Strategies 📊] [Add Pair ➕]
```

### /help — Context-Aware Help

**General help:**
```
📖 TSAR Help
━━━━━━━━━━━━━━━━

Commands:
• /status — your dashboard
• /trade — start/stop trading
• /risk — risk settings
• /history — recent trades
• /settings — configuration
• /ask — ask me anything
• /stop — emergency stop

You can also just talk to me!
• "How am I doing?" → shows status
• "What's BTC doing?" → market check
• "Show me my best trade" → history
• "Why did ETH trade lose?" → analysis

What do you need help with?
[Trading 📈] [Risk 🛡️] [Settings ⚙️] [Ask a Question ❓]
```

**Context-aware (during onboarding):**
```
📖 Setup Help

You're on step 2 of 4 (API Secret).

Need help?
• /skip — skip this step (paper mode will be used)
• /cancel — exit setup (resume later with /start)
• /back — go to previous step

Common issues:
• "Where do I find my API secret?"
  → Binance → API Management → your key → show secret
• "Connection keeps failing"
  → Check IP whitelist in Binance API settings

[Show Detailed Guide 📚]
```

---

## 4. Conversational Intelligence

### 4.1 Natural Language Understanding

**Intent mapping:**

| User says | Intent | Response |
|-----------|--------|----------|
| "How am I doing?" | status | Show /status |
| "What's my balance?" | balance | Show balance |
| "Am I making money?" | pnl | Show P&L |
| "What's BTC doing?" | market_check | Show BTC price + regime |
| "Should I buy ETH?" | signal_request | Scan ETH for signals |
| "Why did I lose?" | loss_analysis | Show recent losses + lessons |
| "Show me my best trade" | best_trade | Show top P&L trade |
| "Stop trading" | stop | Activate kill switch |
| "Start trading" | start | Deactivate kill switch |
| "What's the risk?" | risk_state | Show /risk |
| "How does the flywheel work?" | explain_flywheel | Explain flywheel concept |
| "I'm scared" | emotional_support | Reassure + show risk limits |
| "Let's go!" | encouragement | Positive reinforcement + action |

**Implementation:**
```python
INTENT_PATTERNS = {
    "status": [
        r"how.*(doing|am i|going)",
        r"what.*my (balance|status|account)",
        r"dashboard",
        r"overview",
    ],
    "pnl": [
        r"(making|losing|made|lost).*money",
        r"(profit|loss|pnl|p&l)",
        r"how much.*(up|down|earned|lost)",
    ],
    "market_check": [
        r"what.*(btc|eth|sol|bitcoin|ethereum|solana).*doing",
        r"(price|market).*check",
        r"how.*market",
    ],
    "stop": [
        r"stop (trading|everything)",
        r"halt",
        r"kill switch",
        r"emergency stop",
        r"pause",
    ],
    "emotional_support": [
        r"(scared|worried|nervous|anxious|afraid)",
        r"(losing|lost).*money",
        r"this.*bad",
    ],
}
```

### 4.2 Typo Handling

```python
FUZZY_COMMANDS = {
    "staus": "/status",
    "stauts": "/status",
    "stats": "/status",
    "stat": "/status",
    "trad": "/trade",
    "trde": "/trade",
    "rsik": "/risk",
    "rik": "/risk",
    "hiostory": "/history",
    "hist": "/history",
    "settigns": "/settings",
    "setings": "/settings",
    "stting": "/settings",
    "hepl": "/help",
    "hlep": "/help",
}
```

**Response:**
```
Did you mean /status?

[Yes, show status ✅]  [No, I meant something else 🤔]
```

### 4.3 Proactive Check-Ins

**Schedule:**

| Trigger | Timing | Message |
|---------|--------|---------|
| Morning briefing | 07:00 EAT daily | Overnight summary |
| No trades | 3 days | "Want me to scan?" |
| Regime change | Real-time | "Market shifted to X" |
| Balance milestone | Real-time | "🎉 $X reached!" |
| Risk warning | Real-time | "Daily loss approaching limit" |
| Flywheel update | Weekly | "X lessons, Y patterns" |
| Strategy review | Monthly | "Here's how your strategies performed" |

### 4.4 Emotional Awareness

**After a loss:**
```
Tough trade. ETH/USDT didn't go our way.

But here's the thing:
• Your stop-loss worked perfectly (-$0.15, not -$0.50)
• You're still up this week: +$0.80 (+8%)
• One loss doesn't define your system

The lesson extracted:
"Volume confirmation needed for momentum exhaustion signals."

This makes the next trade smarter.

[View Trade Details 📋]  [Check Overall P&L 📊]
```

**After a win streak:**
```
🔥 You're on fire! 5 wins in a row.

But I'm going to be honest:
• Anti-greed guard is active (sizing at 70%)
• This is exactly when overconfidence sneaks in
• Trust the system, not the streak

Your risk management got you here. Don't abandon it now.

[View Risk State 🛡️]
```

**After a big loss:**
```
That was a rough one. -$0.80 on a single trade.

Let's be real:
• This hurts. It's okay to feel that.
• But your max loss was predefined: you knew the risk before entering
• The system worked — it cut the loss, didn't let it run to -$2.00

Current state:
• Portfolio: $9.20 (down from $10)
• Still within all risk limits
• 3 trades left today

Want to take a break? I can pause trading for a few hours.

[Pause Trading ⏸️] [Keep Going ▶️] [Talk About It 💬]
```

### 4.5 Context-Aware Responses

**If user asks "should I buy?" while kill switch is active:**
```
I can't trade right now — the kill switch is active.

This happened because daily loss hit -3%. It's a safety feature.

To resume: /start confirm
Or wait until tomorrow (limits reset at midnight UTC).

Your capital is protected. That's what matters.
```

**If user asks about a symbol not in their watchlist:**
```
I'm currently watching BTC/USDT and ETH/USDT.

Want me to add SOL/USDT to the watchlist?
I'll need to run a quick analysis first.

[Add SOL/USDT ➕]  [Keep Current Watchlist ✅]
```

---

## 5. Message Templates

### 5.1 Template Design Principles

1. **Mobile-first.** Max 400 characters per "block." Telegram truncates on small screens.
2. **Emoji as punctuation, not decoration.** One emoji per line max. Use for scanning, not spam.
3. **Grouped info.** Related data in one message, not 5 separate pings.
4. **Action buttons always visible.** User should never have to type when a button works.
5. **Consistent structure.** Every message follows: Header → Separator → Content → Actions.

### 5.2 Message Anatomy

```
[HEADER - bold, with emoji]
[SEPARATOR - ━━━━━━━━━━━━━━━━]
[CONTENT - structured data]
[ACTIONS - inline keyboard buttons]
```

### 5.3 Core Templates

#### Template: Trade Proposal

```python
TRADE_PROPOSAL_TEMPLATE = """
{side_emoji} <b>{symbol} {side_label}</b>
━━━━━━━━━━━━━━━━
💰 Entry: ${entry_price:,.2f}
🎯 Target: ${take_profit:,.2f} (+{pnl_pct:.1f}%)
🛑 Stop: ${stop_loss:,.2f} (-{loss_pct:.1f}%)
📊 R:R = 1:{rr:.1f}
📊 Score: {score}/100
{score_bar}

<b>Why:</b>
{reasoning_bullets}

<b>Risk:</b> ${risk_amount:.2f} ({risk_pct}% of portfolio)
Risk Guardian: {risk_status}

<i>Do you want to:</i>
"""
```

#### Template: Status Dashboard

```python
STATUS_TEMPLATE = """
🏰 <b>TSAR Dashboard</b>
━━━━━━━━━━━━━━━━

💰 Balance: ${balance:,.2f}
📈 Total P&L: {pnl_sign}${pnl:,.2f} ({pnl_pct:+.1f}%)
📊 Today: {today_sign}${today_pnl:,.2f} ({today_pct:+.1f}%)

📂 Open: {open_positions}/{max_positions}
🛡️ Risk: {risk_emoji} {risk_level}
🌊 Regime: {regime} ({regime_confidence:.0%})
📊 Win Rate: {win_rate:.0%} ({trade_count} trades)
"""
```

#### Template: Morning Briefing

```python
MORNING_TEMPLATE = """
{time_emoji} Good {time_of_day}, {name}!

{summary_header}
━━━━━━━━━━━━━━━━
📈 Trades: {trade_count} executed
💰 P&L: {pnl_sign}${pnl:,.2f} ({pnl_pct:+.1f}%)
🎯 Win rate: {win_rate:.0%} ({wins}/{total})
🛡️ Risk: {risk_status}
🌊 Regime: {regime} ({confidence:.0%})

{top_trade_section}

{flywheel_section}
"""
```

#### Template: Risk Alert

```python
RISK_ALERT_TEMPLATE = """
⚠️ <b>Risk Alert</b>
━━━━━━━━━━━━━━━━

{alert_message}

Current: {current_value} ({current_pct:.1f}%)
Limit: {limit_value} ({limit_pct:.1f}%)
Remaining: {remaining}

Status: {status_emoji} {status_label} — {action_description}
"""
```

#### Template: Milestone

```python
MILESTONE_TEMPLATE = """
🎉 <b>Milestone: {milestone_name}!</b>
━━━━━━━━━━━━━━━━

{milestone_details}

{context_message}
"""
```

### 5.4 Inline Keyboard Patterns

**Binary choice:**
```python
{"inline_keyboard": [[
    {"text": "✅ Yes", "callback_data": "yes:{context}"},
    {"text": "❌ No", "callback_data": "no:{context}"},
]]}
```

**Trade action:**
```python
{"inline_keyboard": [
    [
        {"text": "✅ Execute", "callback_data": "approve:{id}"},
        {"text": "❌ Pass", "callback_data": "reject:{id}"},
        {"text": "💬 Discuss", "callback_data": "discuss:{id}"},
    ],
]}
```

**Navigation:**
```python
{"inline_keyboard": [
    [
        {"text": "📊 Status", "callback_data": "cmd:status"},
        {"text": "📈 Trade", "callback_data": "cmd:trade"},
        {"text": "🛡️ Risk", "callback_data": "cmd:risk"},
    ],
    [
        {"text": "📋 History", "callback_data": "cmd:history"},
        {"text": "⚙️ Settings", "callback_data": "cmd:settings"},
        {"text": "❓ Help", "callback_data": "cmd:help"},
    ],
]}
```

---

## 6. Error Handling & Edge Cases

### 6.1 Setup Errors

| Error | Message | Action |
|-------|---------|--------|
| Invalid API key format | "That doesn't look right. A Binance API key is usually 64 characters." | Retry |
| Connection timeout | "Connection timed out. Binance might be slow. Try again?" | Retry / Skip |
| Wrong secret | "The secret doesn't match. Double-check you copied the right one." | Retry |
| IP restriction | "Your API key has an IP whitelist. Add this server's IP: X" | Show IP + Retry |
| Bot token invalid | "That token isn't valid. Check @BotFather → /mybots" | Retry |
| Bot token belongs to another bot | "That token belongs to a different bot. Use your TSAR bot's token." | Retry |

### 6.2 Runtime Errors

| Error | Message | Action |
|-------|---------|--------|
| Exchange API down | "⚠️ Binance API is temporarily unavailable. Monitoring paused. I'll retry in 5 minutes." | Auto-retry |
| Insufficient balance | "Not enough balance for this trade. Need $X, have $Y." | Skip signal |
| Network error | "Connection hiccup. Retrying..." | Auto-retry (3x) |
| Rate limit hit | "Too many requests. Cooling down for 60 seconds." | Auto-pause |
| Database error | "Internal issue. Trading paused as precaution." | Halt + notify |

### 6.3 User Input Errors

| Input | Response |
|-------|----------|
| Random text | "I'm not sure what you mean. Try /help for available commands, or just ask me a question!" |
| Commands from other bots | (Ignore silently) |
| Very long message (>4096 chars) | "That's a lot! Can you break it into smaller questions?" |
| Media (photos, files) | "I work with text! Send me a question or use a command." |
| Forwarded messages | "I can only process messages you send directly. What would you like to know?" |

---

## 7. Accessibility & Localization

### 7.1 Kenya-Specific Considerations

- **Timezone:** Africa/Nairobi (UTC+3) — all times displayed in EAT
- **Currency:** Show USD amounts (crypto is USD-denominated), optionally with KES equivalent
- **Mobile-first:** Kenya is predominantly mobile. Messages must be readable on small screens
- **Data costs:** Keep messages concise. Don't send unnecessary images or files
- **M-Pesa:** Future integration for deposits (not in scope now)

### 7.2 Language

- **Primary:** English (Kenyan English)
- **Tone:** Friendly, direct, encouraging. Not corporate. Not robotic.
- **Avoid:** Jargon without explanation. Always explain technical terms on first use.

### 7.3 Message Length Guidelines

| Message Type | Max Length | Reason |
|-------------|-----------|--------|
| Quick response | 200 chars | Instant readability |
| Status update | 400 chars | Scannable |
| Trade proposal | 600 chars | Needs detail |
| Morning briefing | 800 chars | Comprehensive |
| Help text | 1000 chars | Reference material |

---

## 8. Scored Report

## Telegram UX Report
**Score: 8.5/10**

### Setup Flow — 9/10
**Strengths:**
- Conversational, not command-driven — matches how people actually talk to bots
- Inline buttons eliminate typing friction
- Immediate validation catches errors before they compound
- `/skip` and `/cancel` provide escape hatches at every step
- Celebration at completion creates positive first impression
- Auto-detect Chat ID removes a common pain point

**Gaps:**
- No video/GIF tutorial for API key creation (visual learners)
- No multi-language support (Swahili for Kenya market)
- No "resume from where you left off" persistence documented (needs state machine implementation)
- Could add QR code scanning for API keys on mobile

### Daily Interaction — 9/10
**Strengths:**
- Morning briefing is comprehensive but scannable
- Trade alerts provide full rationale (not just "buy this")
- Risk alerts are progressive (warning → action → halt)
- Milestone celebrations create engagement loops
- Proactive check-ins prevent abandonment
- Emotional awareness after losses is human and genuine

**Gaps:**
- No weekend/off-hours behavior defined (crypto is 24/7 but user isn't)
- No "digest mode" for users who want less frequent updates
- Could add weekly/monthly summary reports
- No A/B testing framework for message effectiveness

### Command Design — 8/10
**Strengths:**
- Each command has a clear, single purpose
- Inline buttons reduce command memorization
- Context-aware help adapts to user state
- Navigation buttons at bottom of every message
- Commands map directly to TSAR subsystems (real data, not mockups)

**Gaps:**
- No command aliases (e.g., /p for /positions)
- No command history or autocomplete
- /settings sub-menus could be deeper (currently shallow)
- No "undo" for destructive actions beyond confirmation

### Conversational Intelligence — 8/10
**Strengths:**
- Natural language intent mapping covers common phrases
- Typo handling with fuzzy matching
- Proactive check-ins based on user behavior
- Emotional awareness with appropriate responses
- Context-aware responses (kill switch state, watchlist, etc.)

**Gaps:**
- No ML-based intent classification (regex patterns are brittle)
- No conversation memory across sessions
- No multi-turn context (each message is independent)
- No sentiment analysis on user messages
- Fuzzy matching is basic (could use edit distance / Levenshtein)

### Message Formatting — 9/10
**Strengths:**
- Consistent anatomy (header → separator → content → actions)
- Emoji used as punctuation, not decoration
- Mobile-first character limits
- HTML formatting for bold/italic/code
- Score bars and visual indicators
- Grouped related info (no message spam)

**Gaps:**
- No dark/light mode consideration
- No image/chart generation for visual learners
- No message threading for complex discussions
- Could add progress bars for multi-step processes

### Overall Assessment

The design is **production-ready** with minor gaps. The conversational flow is natural, the error handling is graceful, and the message formatting is mobile-optimized. The biggest wins are:

1. **Conversational onboarding** — no commands required during setup
2. **Emotional intelligence** — genuine responses to wins and losses
3. **Progressive risk alerts** — warning before action before halt
4. **Inline buttons everywhere** — zero friction for common actions
5. **Context-aware help** — adapts to user state

The biggest gaps are:
1. No ML-based NLU (regex won't scale)
2. No cross-session conversation memory
3. No visual/chart generation
4. No multi-language support

**For a v1 launch, 8.5/10 is excellent.** The gaps are v2 features.

---

*Designed for Valentine Cohusdex — Kenya, $10, crypto-only.*
*Built on TSAR's existing bot architecture (bot.py, commands.py, credentials.py).*
*Compatible with python-telegram-bot and inline keyboard API.*
