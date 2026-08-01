# TSAR Telegram Integration & Automation Architecture

**Author:** Telegram Integration & Automation Council
**Date:** 2026-08-01
**Version:** 1.0
**Score:** 8.5/10

---

## Executive Summary

TSAR already has a sophisticated Telegram bot (`src/bot/bot.py`, `src/bot/commands.py`) with inline keyboard trade proposals, command handlers, and risk alerts. This document designs the **full integration layer** connecting Telegram to all TSAR subsystems — trading, risk, monitoring, knowledge, alerts, and automation — with API endpoints, message flows, and a notification engine that prevents spam while ensuring critical alerts always arrive.

**Key Strengths:** Existing bot handles trade proposal lifecycle (approve/reject/modify), has security whitelisting, and connects to real subsystems (KillSwitch, TradeMemory, KnowledgeTools, FlywheelHealth, RegimeStateStore).

**Key Gaps:** No notification aggregation engine, no quiet hours, no scheduled reports, no emergency flatten-all, limited webhook support, no rate limiting on commands.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TELEGRAM USER                               │
│                                                                     │
│   Commands ──→ ┌──────────────┐    ┌──────────────────────┐        │
│   Callbacks ──→│  TsarBot     │───→│  Command Router       │        │
│   Freeform ──→│  (polling/   │    │  (commands.py)        │        │
│                │   webhook)   │    └──────────┬─────────────┘        │
│                └──────┬───────┘               │                     │
│                       │                       ▼                     │
│   ◄────────────────── │ ───── ┌───────────────────────────────┐    │
│   Notifications       │       │      SUBSYSTEM ROUTERS         │    │
│   Alerts              │       │                                │    │
│   Reports             │       │  ┌──────────┐ ┌────────────┐  │    │
│                       │       │  │ Trading  │ │ Risk       │  │    │
│                       │       │  │ Router   │ │ Router     │  │    │
│                       │       │  └────┬─────┘ └─────┬──────┘  │    │
│                       │       │  ┌────┴─────┐ ┌─────┴──────┐  │    │
│                       │       │  │ Monitor  │ │ Knowledge  │  │    │
│                       │       │  │ Router   │ │ Router     │  │    │
│                       │       │  └──────────┘ └────────────┘  │    │
│                       │       └───────────────────────────────┘    │
│                       │                       │                     │
│                       │         ┌─────────────┴──────────────┐     │
│                       │         │    NOTIFICATION ENGINE      │     │
│                       │         │  ┌────────────────────────┐ │     │
│                       ├─────────│  │ Aggregator / Dedup     │ │     │
│                       │         │  │ Priority Queue         │ │     │
│                       │         │  │ Quiet Hours Filter     │ │     │
│                       │         │  │ Rate Limiter           │ │     │
│                       │         │  └────────────────────────┘ │     │
│                       │         └─────────────┬──────────────┘     │
│                       │                       │                     │
│                       │         ┌─────────────┴──────────────┐     │
│                       │         │     EVENT BUS (Redis)       │     │
│                       │         │  CloudEvents v1.0 streams   │     │
│                       │         └────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Trading Integration

### 1.1 Command → Subsystem Mapping

| Command | Handler | Subsystem | Response |
|---------|---------|-----------|----------|
| `/start` | `_handle_start()` | KillSwitch.deactivate() | Confirmation + Gated Recovery |
| `/stop` | `_handle_stop()` | KillSwitch.activate() | Confirmation required |
| `/positions` | `_handle_positions()` | TradeMemory.get_open_positions() | Position list |
| `/pnl` | `_handle_pnl()` | TradeMemory.get_trade_stats() | P&L summary |
| `/trade` | **NEW** | Manual trade flow | Trade proposal → approve/reject |
| `/close` | **NEW** | ExecutionEngine.close_position() | Close with confirmation |
| `/history` | **NEW** | TradeMemory.get_recent_trades() | Trade history |

### 1.2 Trade Proposal Flow (EXISTING — Enhanced)

```
SignalScout detects signal
       │
       ▼
RiskGuardian evaluates ──→ VETO? ──→ Send rejection notification
       │
       ▼ (approved)
TsarBot.propose_trade()
       │
       ▼
┌─────────────────────────────────┐
│  Telegram Message:              │
│  "TSAR wants to open a trade"   │
│  [✅Approve] [❌Reject] [📝Mod] │
│  [💬Discuss] [📊Details]        │
└──────────┬──────────────────────┘
           │
     User presses button
           │
     ┌─────┼─────┬─────┬─────┐
     ▼     ▼     ▼     ▼     ▼
  Approve Reject Modify Discuss Details
     │     │     │     │      │
     ▼     ▼     ▼     ▼      ▼
  Execute Log   Prompt Query  Show
  trade   reject input  knowledge indicators
     │            │     stores
     ▼            ▼
  Send report  Re-propose
  (after trade) with mods
```

### 1.3 Manual Trade Command (NEW)

```
/user_trade BTC/USDT LONG 65000 64000 68000
       │
       ▼
Validate parameters (symbol, side, prices)
       │
       ▼
Create TradeProposal with source="manual"
       │
       ▼
Route through RiskGuardian (mandatory)
       │
       ▼ (risk approved)
Present proposal with inline buttons
       │
       ▼ (user approves)
Execute via ExecutionSniper
```

### 1.4 Emergency Stop Flow (ENHANCED)

```
/stop
  │
  ▼
Confirmation prompt (existing)
  │
  ▼ (user confirms)
KillSwitch.activate()
  │
  ▼
┌─── ENHANCEMENT: Flatten All ───┐
│  For each open position:        │
│    ExecutionEngine.close(pos)   │
│    Log close reason="emergency" │
│    Update TradeMemory           │
│  Send confirmation with:        │
│    - Positions closed count     │
│    - Total P&L realized         │
│    - Kill switch status         │
└─────────────────────────────────┘
```

### 1.5 Trade Alerts (Event-Driven)

```python
# Event subscriptions on the EventBus
EVENT_MAP = {
    "tsar.signal.detected.v1":     "notify_signal_detected",
    "tsar.signal.approved.v1":     "notify_trade_executing",
    "tsar.trade.opened.v1":        "notify_trade_opened",
    "tsar.trade.closed.v1":        "notify_trade_closed",
    "tsar.trade.failed.v1":        "notify_trade_failed",
    "tsar.order.partial_fill.v1":  "notify_partial_fill",
}
```

---

## 2. Risk Integration

### 2.1 Risk Status Command

```
/risk (EXISTING)
  │
  ▼
Query: KillSwitch.is_active()
Query: TradeMemory.get_trade_stats() → max_drawdown
Query: TradeMemory.get_open_positions() → position count
Query: RiskGovernor.get_state() → daily loss, position limits
  │
  ▼
Format:
  🛡️ Risk State
  ━━━━━━━━━━━━━━
  📊 Drawdown: 1.2%
  🚦 Level: 🟢 GREEN
  📅 Daily P&L: +$45.20
  🔌 Kill switch: ✅ Inactive
  📂 Open positions: 3/5 (limit)
  ⚡ Leverage: 2.1x / 3.0x max
  🕐 Trading hours: 08:00-22:00 UTC
```

### 2.2 Risk Settings Adjustment (NEW)

```
/risk_set max_drawdown 5.0
       │
       ▼
┌─── Confirmation Required ───┐
│  ⚠️ RISK SETTING CHANGE     │
│                              │
│  Setting: max_drawdown       │
│  Current: 3.0%               │
│  New: 5.0%                   │
│                              │
│  [✅ Confirm] [❌ Cancel]    │
└──────────────────────────────┘
       │
       ▼ (confirmed)
RiskGovernor.update_setting(key, value)
Log change in audit trail
Send confirmation
```

**Critical settings requiring confirmation:**
- `max_drawdown` — Maximum portfolio drawdown
- `daily_loss_limit` — Daily loss ceiling
- `max_position_size` — Maximum single position size
- `max_leverage` — Maximum leverage
- `kill_switch_threshold` — Auto-kill drawdown level

**Settings changeable without confirmation:**
- `notification_level` — Alert verbosity
- `trading_hours` — Active trading window
- `position_sizing_mode` — Kelly/fixed/vol-target

### 2.3 Risk Alert Flow

```
Risk subsystem detects issue
       │
       ▼
EventBus.publish("tsar.risk.alert.v1", {
    "level": "HIGH",
    "type": "drawdown_warning",
    "message": "Drawdown at 4.2%, approaching 5% limit",
    "metric": 4.2,
    "threshold": 5.0
})
       │
       ▼
NotificationEngine.receive(event)
       │
       ▼
Priority check: HIGH → immediate delivery
       │
       ▼
Format + send to Telegram:
  🔴 RISK [HIGH]
  Drawdown at 4.2%, approaching 5% limit
  Current: 4.2% / Limit: 5.0%
  [🛑 Emergency Stop] [📊 Details]
```

### 2.4 Risk Alert Types

| Alert | Level | Trigger | Auto-Action |
|-------|-------|---------|-------------|
| Drawdown warning | HIGH | DD > 3% | None |
| Drawdown critical | CRITICAL | DD > 5% | Kill switch auto-activate |
| Daily loss limit | HIGH | Daily loss > limit | Block new trades |
| Position limit | MEDIUM | Positions = max | Block new trades |
| Leverage warning | HIGH | Leverage > 80% max | Reduce suggestion |
| Connection lost | CRITICAL | Exchange disconnect | Kill switch + flatten |
| API rate limit | MEDIUM | 429 errors | Pause 60s |

---

## 3. Monitoring Integration

### 3.1 Dashboard Command (NEW)

```
/dashboard
       │
       ▼
Aggregate from multiple subsystems:
  - TradeMemory.get_trade_stats()
  - FlywheelHealth.compute()
  - RegimeStateStore.get_global_regime()
  - StrategyGenomes.get_active()
  - KillSwitch.is_active()
       │
       ▼
Format:
  🏰 TSAR Dashboard
  ━━━━━━━━━━━━━━━━━
  Status: 🟢 ACTIVE | Mode: paper

  💰 P&L Today: +$127.50 (+1.27%)
  📊 Win Rate: 68% (19/28)
  ⚖️ Profit Factor: 2.14
  📉 Max Drawdown: 2.1%
  📈 Sharpe Ratio: 1.82

  🌊 Regime: STRONG_TREND_UP (78%)
  🧬 Active Strategy: momentum_v3 (fitness: 0.84)
  🔄 Flywheel: 0.72 (Healthy)

  📂 Open: 3 positions
  BTC/USDT LONG +$45.20
  ETH/USDT SHORT -$12.30
  SOL/USDT LONG +$89.10
```

### 3.2 Performance Metrics Commands

| Command | Metrics | Source |
|---------|---------|--------|
| `/pnl` | Total P&L, avg win/loss, max DD | TradeMemory |
| `/performance` | Win rate, profit factor, by-strategy | TradeMemory + KnowledgeTools |
| `/sharpe` | Sharpe, Sortino, Calmar ratios | TradeMemory (computed) |
| `/streaks` | Win/loss streaks, max consecutive | TradeMemory |
| `/regime_perf` | P&L by regime, regime transitions | TradeMemory + RegimeStateStore |

### 3.3 Portfolio Breakdown (NEW)

```
/portfolio
       │
       ▼
  📂 Portfolio Breakdown
  ━━━━━━━━━━━━━━━━━━━━━

  By Asset:
  • BTC: 45% ($4,500) — 2 positions
  • ETH: 30% ($3,000) — 1 position
  • SOL: 25% ($2,500) — 1 position

  By Direction:
  • LONG: 70% ($7,000) — 3 positions
  • SHORT: 30% ($3,000) — 1 position

  By Strategy:
  • momentum_v3: 60% — 3 trades
  • mean_revert_v1: 40% — 1 trade

  Exposure: $10,000 / $50,000 (20%)
  Leverage: 1.5x / 3.0x max
```

---

## 4. Knowledge System Integration

### 4.1 Query Flow (EXISTING /ask — Enhanced)

```
User: "Why did you enter BTC at 45000?"
       │
       ▼
Parse intent → knowledge_query
       │
       ▼
┌─── Context Aggregation ────────────────────┐
│                                             │
│  1. TradeMemory.search("BTC 45000")         │
│     → Find matching trade record            │
│                                             │
│  2. KnowledgeTools.get_trade(trade_id)      │
│     → Full trade details + reasoning        │
│                                             │
│  3. LessonArchive.search("BTC entry")       │
│     → Related lessons                       │
│                                             │
│  4. PatternLibrary.get_active_patterns()    │
│     → Patterns active at entry time         │
│                                             │
│  5. RegimeStateStore.get_regime_at(timestamp)│
│     → Market regime at entry                │
│                                             │
│  6. StrategyGenomes.get_active()            │
│     → Strategy parameters used              │
│                                             │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
Format response:
  ❓ Why BTC LONG at $45,000?
  ━━━━━━━━━━━━━━━━━━━━━━━━━━

  📅 Trade: 2026-07-28 14:30 UTC
  📊 Strategy: momentum_v3

  Reasoning:
  • RSI(14) = 32 (oversold bounce)
  • Price at EMA(50) support
  • Volume spike 2.3x average
  • Bullish engulfing on 4H
  • Multi-TF confluence score: 0.82

  Regime: STRONG_TREND_UP (78%)
  Pattern: "oversold_reversal" (confidence: 74%)

  Similar past trades:
  • #127 BTC LONG +2.1% (same pattern)
  • #89 BTC LONG +3.4% (same regime)
```

### 4.2 Knowledge Commands

| Command | Query | Source |
|---------|-------|--------|
| `/ask [question]` | Freeform Q&A | All knowledge stores |
| `/why [trade_id]` | Trade reasoning | TradeMemory + KnowledgeTools |
| `/lessons` | Recent lessons | LessonArchive |
| `/patterns` | Active patterns | PatternLibrary |
| `/search [query]` | Full-text search | FTS index |
| `/flywheel` | Flywheel health | FlywheelHealth |

### 4.3 Flywheel Status (EXISTING — Enhanced)

```
/flywheel
       │
       ▼
  🔄 Flywheel Health: 0.72 (Healthy)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Components:
  • Learning: [████████░░] 0.82
  • Adaptation: [███████░░░] 0.71
  • Memory: [█████████░] 0.91
  • Exploration: [██████░░░░] 0.63

  Recent Cycles:
  • #47: 3 rules extracted, 1 mutation applied
  • #46: 5 rules extracted, 2 mutations applied
  • #45: 2 rules extracted, 0 mutations (no improvement)

  Genome Evolution:
  momentum_v3 → Gen 12 (fitness: 0.84, ↑0.03)
```

---

## 5. Alert & Notification System

### 5.1 Notification Engine (NEW COMPONENT)

```python
class NotificationEngine:
    """Smart notification delivery with aggregation, dedup, and quiet hours.

    Architecture:
    - Receives events from EventBus subscribers
    - Aggregates similar events within a time window
    - Applies priority-based delivery (CRITICAL = immediate, LOW = batched)
    - Enforces quiet hours (no non-critical alerts during sleep)
    - Rate limits to prevent Telegram API abuse
    - Deduplicates identical alerts within a cooldown period
    """

    # Priority levels
    CRITICAL = 0  # Always delivered, bypasses quiet hours
    HIGH = 1      # Delivered immediately during active hours
    MEDIUM = 2    # Batched, delivered every 15 min
    LOW = 3       # Batched, delivered in daily digest

    # Aggregation windows (seconds)
    AGGREGATION_WINDOWS = {
        CRITICAL: 0,      # No aggregation
        HIGH: 5,           # 5 second window
        MEDIUM: 900,       # 15 minute window
        LOW: 86400,        # 24 hour window (daily digest)
    }

    # Quiet hours (user configurable)
    quiet_start: str = "23:00"  # UTC
    quiet_end: str = "07:00"    # UTC

    # Rate limits
    max_messages_per_minute: int = 10
    max_messages_per_hour: int = 60

    # Dedup cooldown (seconds)
    dedup_cooldown: dict[str, int] = {
        "trade_executed": 0,       # Never dedup trade alerts
        "risk_warning": 300,       # 5 min cooldown
        "connection_error": 600,   # 10 min cooldown
        "market_event": 1800,      # 30 min cooldown
        "system_health": 3600,     # 1 hour cooldown
    }
```

### 5.2 Notification Types & Priority

| Event Type | Priority | Aggregation | Quiet Hours | Format |
|------------|----------|-------------|-------------|--------|
| `trade.opened` | HIGH | None | Bypass | ✅ Trade opened: BTC LONG |
| `trade.closed` | HIGH | None | Bypass | ✅/❌ Trade closed: +$45 |
| `trade.failed` | CRITICAL | None | Bypass | ❌ Trade execution failed |
| `risk.alert` | CRITICAL/HIGH | 5s window | Bypass | 🔴 RISK [HIGH] ... |
| `risk.drawdown_critical` | CRITICAL | None | Bypass | 🚨 KILL SWITCH AUTO-ACTIVATED |
| `connection.lost` | CRITICAL | None | Bypass | 🔌 Exchange disconnected |
| `regime.change` | MEDIUM | 15 min | Respect | 🌊 Regime changed to ... |
| `flywheel.cycle` | LOW | Daily | Respect | 🔄 Flywheel digest |
| `milestone` | MEDIUM | None | Respect | 🎉 100th trade! Win rate 68% |
| `system.health` | LOW | Hourly | Respect | ⚙️ System health: OK |
| `market.volatility` | MEDIUM | 30 min | Respect | 🌊 High volatility detected |

### 5.3 Aggregation Flow

```
Multiple events arrive within window
       │
       ▼
┌─── Aggregator ──────────────────────┐
│                                      │
│  event_buffer[type] = [e1, e2, e3]  │
│                                      │
│  After window expires:               │
│                                      │
│  IF count == 1:                      │
│    Send single notification          │
│  IF count > 1:                       │
│    Send aggregated:                  │
│    "3 trades closed: +$45, -$12, +$89"│
│                                      │
└──────────────────────────────────────┘
```

### 5.4 Quiet Hours

```
Current time: 01:30 UTC (within quiet hours 23:00-07:00)
       │
       ▼
Event arrives: regime.change (MEDIUM priority)
       │
       ▼
Check: priority < CRITICAL? YES
Check: within quiet hours? YES
       │
       ▼
Action: Queue for morning digest
       │
       ▼
At 07:00 UTC, send digest:
  📋 Morning Digest (23:00-07:00)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • 🌊 Regime changed to RANGING
  • 📊 2 trades closed: +$45, -$12
  • ⚙️ System health: OK
```

### 5.5 Rate Limiting

```python
class RateLimiter:
    """Token bucket rate limiter for Telegram API.

    Telegram limits: 30 messages/sec to different chats,
    1 message/sec to same chat. We use conservative limits.
    """

    # Per-chat limits (more restrictive than Telegram's global limits)
    messages_per_second: float = 0.5   # 1 message every 2 seconds
    messages_per_minute: int = 10
    messages_per_hour: int = 60

    # Burst allowance for CRITICAL alerts
    burst_size: int = 3  # Can burst 3 critical messages

    async def can_send(self, priority: int) -> bool:
        """Check if we can send a message at this priority."""
        if priority == 0:  # CRITICAL always allowed (burst)
            return self._burst_tokens > 0
        return self._tokens > 0

    async def consume(self, priority: int) -> None:
        """Consume a token after sending."""
        if priority == 0:
            self._burst_tokens -= 1
        else:
            self._tokens -= 1
```

---

## 6. Automation Rules

### 6.1 Scheduled Reports (NEW)

| Report | Schedule | Content | Delivery |
|--------|----------|---------|----------|
| Daily Summary | 00:00 UTC | P&L, trades, win rate, regime | Auto |
| Weekly Report | Sunday 00:00 | Full performance, strategy review, lessons | Auto |
| Monthly Review | 1st of month | Comprehensive analysis, genome evolution | Auto |
| Morning Brief | 08:00 UTC | Overnight events, regime, open positions | Auto |

**Daily Summary Format:**
```
📊 Daily Summary — 2026-08-01
━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 P&L: +$127.50 (+1.27%)
📈 Trades: 8 (5W / 3L)
🎯 Win Rate: 62.5%
⚖️ Profit Factor: 2.14

🌊 Regime: STRONG_TREND_UP → RANGING
🧬 Strategy: momentum_v3 performed best

Top Trade: BTC LONG +$89.10
Worst Trade: ETH LONG -$23.40

📝 Lessons:
• Oversold reversal pattern worked 3/3 times
• Avoid entries during low-volume hours

🔄 Flywheel: 2 rules extracted, 1 mutation applied
```

### 6.2 Auto-Response Rules (NEW)

```python
AUTO_RESPONSE_RULES = {
    # Pattern → Response template
    "status": {
        "patterns": ["status", "how are you", "what's up"],
        "handler": "_handle_status",
        "cooldown": 60,  # Don't auto-respond more than once per minute
    },
    "pnl": {
        "patterns": ["pnl", "profit", "how much", "making money"],
        "handler": "_handle_pnl",
        "cooldown": 60,
    },
    "positions": {
        "patterns": ["positions", "open trades", "what's open"],
        "handler": "_handle_positions",
        "cooldown": 60,
    },
}
```

### 6.3 Smart Notification Aggregation (NEW)

```python
class SmartAggregator:
    """Intelligent notification aggregation.

    Rules:
    1. Trade alerts: Never aggregate (each trade is important)
    2. Risk alerts: Aggregate similar within 5 seconds
    3. Regime changes: Aggregate within 15 minutes
    4. System health: Aggregate within 1 hour
    5. Flywheel: Always aggregate into daily digest

    Special rules:
    - If multiple risk alerts of same type, send summary:
      "3 position limit warnings: BTC, ETH, SOL"
    - If trade + risk alert for same trade, combine:
      "Trade opened BTC LONG — ⚠️ approaching position limit"
    """
```

### 6.4 Notification Lifecycle

```
Event from EventBus
       │
       ▼
NotificationEngine.receive(event)
       │
       ▼
┌─── Processing Pipeline ────────────────────┐
│                                             │
│  1. DEDUP CHECK                             │
│     → Same event type within cooldown?      │
│     → YES: Skip (log as deduped)            │
│                                             │
│  2. PRIORITY CLASSIFICATION                 │
│     → Map event type to priority level      │
│                                             │
│  3. QUIET HOURS CHECK                       │
│     → CRITICAL: Always deliver              │
│     → Others: Queue if in quiet hours       │
│                                             │
│  4. RATE LIMIT CHECK                        │
│     → Can we send now?                      │
│     → NO: Queue with retry                  │
│                                             │
│  5. AGGREGATION CHECK                       │
│     → Should we batch with other events?    │
│     → YES: Add to aggregation buffer        │
│     → NO: Format and send immediately       │
│                                             │
│  6. FORMAT MESSAGE                          │
│     → Apply template for event type         │
│     → Add inline buttons if applicable      │
│                                             │
│  7. SEND via TsarBot.send_message()         │
│                                             │
└─────────────────────────────────────────────┘
```

---

## 7. API Endpoints (Internal)

### 7.1 Telegram → TSAR (Commands)

These are the internal endpoints the bot routes commands to:

```
# Trading
POST /api/v1/trading/start          → KillSwitch.deactivate()
POST /api/v1/trading/stop           → KillSwitch.activate()
POST /api/v1/trading/execute        → ExecutionSniper.execute()
POST /api/v1/trading/close/{id}     → ExecutionSniper.close_position()
GET  /api/v1/trading/positions      → TradeMemory.get_open_positions()
GET  /api/v1/trading/history        → TradeMemory.get_recent_trades()

# Risk
GET  /api/v1/risk/state             → RiskGovernor.get_state()
POST /api/v1/risk/settings          → RiskGovernor.update_setting()
GET  /api/v1/risk/limits            → RiskGovernor.get_limits()

# Monitoring
GET  /api/v1/monitor/pnl            → TradeMemory.get_trade_stats()
GET  /api/v1/monitor/performance    → Aggregated performance metrics
GET  /api/v1/monitor/regime         → RegimeStateStore.get_global_regime()
GET  /api/v1/monitor/flywheel       → FlywheelHealth.compute()

# Knowledge
GET  /api/v1/knowledge/search       → KnowledgeTools.search()
GET  /api/v1/knowledge/trade/{id}   → KnowledgeTools.get_trade()
GET  /api/v1/knowledge/lessons      → LessonArchive.get_recent()
GET  /api/v1/knowledge/patterns     → PatternLibrary.get_active()
```

### 7.2 TSAR → Telegram (Notifications)

Events published on the EventBus that trigger Telegram notifications:

```
# Trade events
tsar.signal.detected.v1     → Notify: signal found (if in proposal mode)
tsar.signal.approved.v1     → Notify: trade executing
tsar.trade.opened.v1        → Notify: position opened
tsar.trade.closed.v1        → Notify: position closed + P&L
tsar.trade.failed.v1        → ALERT: execution failed (CRITICAL)

# Risk events
tsar.risk.alert.v1          → ALERT: risk warning (level-based)
tsar.risk.kill_switch.v1    → ALERT: kill switch activated (CRITICAL)
tsar.risk.drawdown.v1       → ALERT: drawdown warning (HIGH)

# System events
tsar.system.connection.v1   → ALERT: connection status change
tsar.system.health.v1       → Notify: health check results
tsar.system.error.v1        → ALERT: system error (CRITICAL)

# Knowledge events
tsar.flywheel.cycle.v1      → Notify: flywheel cycle complete
tsar.regime.change.v1       → Notify: regime transition
tsar.milestone.v1           → Notify: achievement unlocked

# Market events
tsar.market.volatility.v1   → Notify: volatility spike
tsar.market.regime.v1       → Notify: market regime change
```

---

## 8. Security Considerations

### 8.1 Existing Security (GOOD)

- Chat ID whitelist (`_allowed_chat_ids`)
- Confirmation tokens for dangerous commands (/stop, /start)
- Environment-based configuration

### 8.2 Enhancements Needed

| Enhancement | Priority | Description |
|-------------|----------|-------------|
| Command rate limiting | HIGH | Prevent command spam (max 10/min) |
| Confirmation expiry | HIGH | Tokens expire after 5 minutes |
| Audit logging | MEDIUM | Log all commands with timestamps |
| 2FA for critical ops | MEDIUM | TOTP for /stop, risk changes |
| Session management | LOW | Track active sessions |

### 8.3 Command Authorization Matrix

| Command | Auth Level | Confirmation | Rate Limit |
|---------|-----------|--------------|------------|
| `/status` | Basic | No | 10/min |
| `/pnl` | Basic | No | 10/min |
| `/positions` | Basic | No | 10/min |
| `/risk` | Basic | No | 10/min |
| `/trade` | Elevated | Yes (inline) | 5/min |
| `/close` | Elevated | Yes (inline) | 5/min |
| `/stop` | Critical | Yes (text) | 1/min |
| `/start` | Critical | Yes (text) | 1/min |
| `/risk_set` | Critical | Yes (inline) | 3/min |

---

## 9. Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Implement NotificationEngine with priority queue
- [ ] Add quiet hours support
- [ ] Add rate limiter
- [ ] Enhance /stop to flatten all positions
- [ ] Add command rate limiting

### Phase 2: Monitoring (Week 3-4)
- [ ] Implement /dashboard command
- [ ] Implement /portfolio command
- [ ] Add scheduled daily summary
- [ ] Add Sharpe/Sortino ratio calculations
- [ ] Enhance /performance with more metrics

### Phase 3: Knowledge (Week 5-6)
- [ ] Enhance /ask with multi-store context
- [ ] Add /lessons and /search commands
- [ ] Improve /flywheel with genome details
- [ ] Add trade similarity search

### Phase 4: Automation (Week 7-8)
- [ ] Implement weekly/monthly reports
- [ ] Add smart notification aggregation
- [ ] Add auto-response rules
- [ ] Implement milestone notifications
- [ ] Add morning brief

---

## 10. Score Justration

| Category | Score | Notes |
|----------|-------|-------|
| Trading Integration | 9/10 | Excellent existing bot with trade proposal lifecycle. Missing manual trade command and close position. |
| Risk Integration | 8/10 | Good risk commands. Missing settings adjustment and flatten-all on emergency stop. |
| Monitoring Integration | 7/10 | Basic commands exist. Missing dashboard, portfolio breakdown, Sharpe ratio. |
| Knowledge System | 8/10 | /ask, /why, /discuss exist. Could be enhanced with better context aggregation. |
| Alert System | 6/10 | Basic alerts exist. Missing aggregation, quiet hours, rate limiting, dedup. |
| Automation | 5/10 | No scheduled reports, no auto-response, no smart aggregation. |
| Security | 8/10 | Good whitelist and confirmation. Missing rate limiting and audit logging. |

**Overall: 8.5/10** — Strong foundation with the existing bot. The main gaps are in the notification engine (aggregation, quiet hours, rate limiting) and automation (scheduled reports, smart notifications). The trading and risk integrations are nearly complete and well-designed.
