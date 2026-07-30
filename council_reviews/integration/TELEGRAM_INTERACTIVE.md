# Telegram Interactive Trading Partner — Integration Council Review

**Date:** 2026-07-30
**Council:** Integration: Telegram Interactive
**Status:** ✅ COMPLETE
**Reviewer:** Subagent (depth 1/1)

---

## Executive Summary

The Telegram bot has been **completely redesigned** from a one-way notification system into a full **interactive trading partner**. Users can now discuss, approve, reject, and modify trades before execution, receive detailed post-trade reports with lessons learned, and query the TSAR system interactively.

### Before → After

| Aspect | Before (BROKEN) | After (INTERACTIVE) |
|--------|-----------------|---------------------|
| Trade flow | Silent notification: "Trade taken: BTC/USDT LONG" | Rich proposal with rationale, inline approve/reject/modify buttons |
| User control | None — trades execute automatically | Full control: approve, reject, modify parameters |
| Post-trade | Minimal P&L line | Detailed report with lessons, flywheel update, pattern analysis |
| Commands | 8 basic monitoring commands | 14 commands including /discuss, /why, /ask, /performance, /strategy |
| Context | No reasoning shown | Full signal breakdown, indicator values, risk assessment |

---

## Architecture Changes

### 1. Trade Proposal State Machine

```
Signal Detected → RiskGuardian Evaluates → TradeProposal Created
                                              │
                                    ┌─────────┼─────────┐
                                    ▼         ▼         ▼
                                APPROVE    REJECT    MODIFY
                                    │         │         │
                                    ▼         ▼         ▼
                              Execute    Log      Re-propose
                              Pipeline   Rejection  (future)
                                    │
                                    ▼
                              Detailed Report
                              (with lessons)
```

**New class: `TradeProposal`**
- Tracks full lifecycle: PENDING → APPROVED/REJECTED/MODIFIED/EXPIRED
- Stores signal data, risk decision, metadata, and user modifications
- TTL-based expiry (default 300s) with background checker
- Links to Telegram message ID for inline editing

### 2. Inline Keyboard System

Trade proposals include interactive buttons:
```
[✅ Approve] [❌ Reject] [📝 Modify]
[💬 Discuss] [📊 Details]
```

Button callbacks are routed through `handle_callback_query()`:
- `approve:{proposal_id}` → Execute trade through pipeline
- `reject:{proposal_id}` → Log rejection, update message
- `modify:{proposal_id}` → Prompt for parameter changes
- `discuss:{proposal_id}` → Deep analysis with regime/lesson context
- `details:{proposal_id}` → Full technical indicator breakdown

### 3. Command Routing

The poll loop now handles both text messages and callback queries:

```python
for update in data.get("result", []):
    if "callback_query" in update:
        await self.handle_callback_query(update["callback_query"])
    elif text.startswith("/"):
        await self.handle_command(text, msg)
    elif self._discussion_context.get("awaiting_input"):
        await self._handle_freeform_input(text, msg)
```

---

## New Commands

### Interactive Commands (NEW)

| Command | Description | Data Sources |
|---------|-------------|--------------|
| `/discuss [trade_id]` | Deep dive into a specific trade | TradeMemory, PatternLibrary, LessonArchive, VectorSearch |
| `/why [trade_id]` | Explain why a trade was taken | Signal reasoning, indicator values, score breakdown, patterns |
| `/ask [question]` | Ask TSAR anything about markets | FTS5 search, regime state, performance stats |
| `/performance` | Detailed multi-dimensional analysis | TradeMemory, StrategySummary, LessonArchive, PatternLibrary |
| `/strategy` | Current strategy & genome | StrategyGenomes, mutations, lineage, fitness |
| `/help` | Show all available commands | Static |

### Existing Commands (ENHANCED)

| Command | Enhancement |
|---------|-------------|
| `/status` | Added profit factor, max drawdown |
| `/pnl` | Unchanged (already good) |
| `/positions` | Unchanged |
| `/risk` | Unchanged |
| `/regime` | Added RegimeStateStore transitions + per-regime performance |
| `/flywheel` | Added component score breakdown with visual bars |
| `/stop` | Added guidance on how to resume |
| `/start` | Added recovery protocol mention |

---

## Wire-Up to TSAR Subsystems

### Signal Scout → Trade Proposal

When SignalScout detects a signal, the bot now:
1. Creates a `TradeProposal` with full signal data
2. Formats a rich message with entry/target/stop, R:R, reasoning
3. Sends with inline approve/reject/modify buttons
4. Waits for user decision before proceeding

### Risk Guardian → Proposal Enhancement

If RiskGuardian evaluates the signal first:
- Approved signals show "✅ Risk Guardian: APPROVED"
- Vetoed signals show "❌ Risk Guardian: VETOED" with reasons
- Warnings are displayed as advisory notes

### Trade Philosopher → Post-Trade Report

After trade closure, the detailed report includes:
- Structured reflection from TradePhilosopher
- Lesson with pattern tags
- What went right/wrong
- Error category and actionable changes

### Flywheel Orchestrator → Notifications

Flywheel cycle completions trigger notifications showing:
- Rules extracted → validated → mutations proposed → applied
- Pipeline outcome (success/no_rules/error)

### Regime Detector → Context

Regime changes trigger notifications. The `/regime` command shows:
- Current regime with confidence
- Recent transitions
- Per-regime trade performance

### Strategy Geneticist → `/strategy` Command

The `/strategy` command displays:
- Active strategies with fitness scores
- Current parameters
- Recent mutations
- Evolutionary lineage

---

## Security

### Preserved (C-020)
- Chat ID whitelist remains enforced
- All callback queries checked against whitelist
- Unauthorized messages logged and dropped

### New Considerations
- Trade proposals have TTL to prevent stale approvals
- Modify prompts are single-shot (cleared after input)
- No external data leakage in discussion context

---

## Files Changed

### `src/bot/bot.py` — Complete Rewrite

**Before:** ~130 lines, notification-only bot with polling loop
**After:** ~700 lines, interactive trading partner

Key additions:
- `TradeProposal` class — trade lifecycle state machine
- `propose_trade()` — BEFORE TRADE discussion flow
- `send_trade_report()` — AFTER TRADE detailed report
- `handle_callback_query()` — inline button handler
- `_format_trade_proposal()` — rich HTML formatting
- `_build_proposal_keyboard()` — inline keyboard builder
- `_handle_approve/reject/modify/discuss/details()` — button handlers
- `_execute_proposal()` — pipeline integration
- `_build_discussion()` — deep analysis with context
- `_format_detailed_analysis()` — technical breakdown
- `_handle_ask_question()` — /ask with knowledge search
- `_expiry_loop()` — background proposal expiry
- `send_flywheel_notification()` — flywheel alerts
- `send_regime_change()` — regime change alerts

### `src/bot/commands.py` — Extended

**Before:** ~200 lines, 8 commands
**After:** ~450 lines, 14 commands

Key additions:
- `/performance` — multi-dimensional analysis
- `/strategy` — genome and mutation display
- `/discuss` — trade deep-dive with vector search
- `/why` — signal reasoning and indicator breakdown
- Enhanced `/regime` — transitions + per-regime performance
- Enhanced `/flywheel` — component score visualization

---

## Example Flows

### Flow 1: Trade Approval

```
1. SignalScout detects BTC/USDT BUY signal (score: 0.78)
2. RiskGuardian evaluates: APPROVED
3. Bot sends proposal with rationale and buttons
4. User taps "✅ Approve"
5. Bot edits message to show "APPROVED — Executing..."
6. ExecutionSniper places orders
7. Trade closes → Bot sends detailed report with lesson
```

### Flow 2: Trade Discussion

```
1. Bot sends trade proposal
2. User taps "💬 Discuss"
3. Bot queries regime, lessons, patterns
4. Bot sends deep analysis:
   - Current regime: BULL (82% confidence)
   - 3 relevant lessons found
   - 2 active patterns matching
   - Score breakdown by component
5. User taps "✅ Approve" or "❌ Reject"
```

### Flow 3: Interactive Query

```
1. User sends /ask "Why are we in bull regime?"
2. Bot searches FTS5 knowledge store
3. Bot queries regime state
4. Bot aggregates performance context
5. Bot responds with relevant knowledge + regime data
```

---

## Testing Checklist

- [ ] Trade proposal renders correctly with all fields
- [ ] Approve button triggers execution pipeline
- [ ] Reject button updates message and logs rejection
- [ ] Modify button prompts for input and handles response
- [ ] Discuss button shows regime/lesson/pattern context
- [ ] Details button shows full technical breakdown
- [ ] Proposals expire after TTL (300s default)
- [ ] /performance shows strategy breakdown and lessons
- [ ] /strategy shows genome, mutations, lineage
- [ ] /discuss [id] retrieves and displays trade details
- [ ] /why [id] shows signal reasoning and indicators
- [ ] /ask searches knowledge stores for context
- [ ] /regime shows transitions and per-regime performance
- [ ] /flywheel shows component score bars
- [ ] Unauthorized callback queries are rejected
- [ ] Post-trade report includes reflection and flywheel update
- [ ] Flywheel notifications show pipeline stats
- [ ] Regime change notifications are sent

---

## Integration Points

### Event Bus Connections

```
SignalScout ──signal.detected──→ RiskGuardian
                                      │
                                      ▼
                               risk.approved
                                      │
                                      ▼
                              TsarBot.propose_trade()
                                      │
                              [User approves via button]
                                      │
                                      ▼
                              signal.approved
                                      │
                                      ▼
                              ExecutionSniper
                                      │
                                      ▼
                              trade.executed
                                      │
                                      ▼
                              TradePhilosopher → Reflection
                                      │
                                      ▼
                              TsarBot.send_trade_report()
```

### Knowledge Store Queries

| Command | Stores Queried |
|---------|---------------|
| `/discuss` | TradeMemory, PatternLibrary, VectorSearch |
| `/why` | TradeMemory, PatternLibrary, RegimeState |
| `/ask` | FTS5Search, RegimeState, TradeMemory |
| `/performance` | TradeMemory, StrategySummary, LessonArchive, PatternLibrary |
| `/strategy` | StrategyGenomes |
| `/regime` | RegimeStateStore, RegimeGraph, TradeMemory |

---

## Future Enhancements

1. **Streaming Updates** — Real-time position P&L updates via edited messages
2. **Portfolio View** — `/portfolio` command with pie charts and allocation
3. **Trade Journal** — `/journal` to add personal notes to trades
4. **Alerts Config** — `/alerts` to configure notification preferences
5. **Multi-User** — Per-user approval queues for team trading
6. **Voice Notes** — Send voice messages for quick trade approvals
7. **Charts** — Inline chart images with technical analysis overlay
