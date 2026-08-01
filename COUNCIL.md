# TSAR Council

## Governance Structure

**Founder:** Valentine Owuor — intervenes only on critical issues (capital, security, architecture pivots, go/no-go live trading)

**Co-Founder:** AI Orchestrator — coordinates council, breaks ties, escalates to founder on critical issues

## Council of 5

| # | Role | Member | Responsibility |
|---|------|--------|---------------|
| 1 | Co-Founder | AI Orchestrator | Overall coordination, tie-breaking, founder escalation |
| 2 | Chief Architect | TBD | Technical design, system architecture, integration integrity |
| 3 | Chief Risk Officer | TBD | Risk engine, safeguards, compliance, kill switches, safety |
| 4 | Chief Strategist | TBD | Trading strategy, market analysis, regime detection, alpha |
| 5 | Chief Engineer | TBD | Implementation feasibility, code quality, performance, deployment |

## Decision Protocol

```
Council reviews → Each member votes (APPROVE / CONDITIONAL / REJECT)
Majority (3/5) → Decision stands
Tie (2-2) → Co-Founder breaks tie
Critical issue → Escalate to Founder
```

## Escalation Triggers (to Founder)

- Capital allocation changes
- Architecture pivots (core design changes)
- Security incidents
- Go/no-go on live trading
- Risk limit changes affecting real money
- Any decision with >$100 financial impact

## Council Sessions

Each council session produces:
1. Individual assessments (per member)
2. Council verdict (APPROVED / CONDITIONAL PASS / REJECTED)
3. Action items with owners
4. Escalation list (if any)

---
*Council convened: 2026-07-24*
*Architecture approved: CONDITIONAL PASS (all 4 members)*
*Hybrid Rust + C++ approved: CONDITIONAL (C++ enters at Level 3+)*
*55 issues found and addressed by fixing team*

---

## Entry/Exit Optimization Council (2026-08-01)

**Mission:** Maximize win rate to 75%+ through disciplined entry, exit, and trade management

### Deliverables

| File | Description |
|------|-------------|
| `ENTRY_EXIT_OPTIMIZATION.md` | Full optimization design report (score: 7/10) |
| `src/agents/trade_manager.py` | New Trade Manager agent — trailing stops, partial exits, time stops, regime/news exits |
| `tests/unit/agents/test_trade_manager.py` | 38 tests — all passing |

### Modified Components

| File | Changes |
|------|---------|
| `src/agents/signal_scout.py` | Session timing gates, pullback detection, enhanced volume confirmation, news blackout |
| `src/agents/execution_sniper.py` | Limit order support (better fills) |
| `src/agents/risk_guardian.py` | Session timing, weekend risk, news blackout checks in risk evaluation |
| `src/strategy/mean_reversion.py` | Updated risk params: trailing stops, partial exits, limit orders |

### Key Design Decisions

1. **Trailing stops are multi-stage:** Initial → Break-even (1:1 R:R) → Trailing (1.5:1) → Tight trail (2:1)
2. **Partial exits at 40/30/30:** Lock profit at 1:1, 2:1, 3:1 R:R
3. **Session timing gates:** Block entries during Asian session, dead zone, and low-quality days
4. **News blackout:** No new entries within 2h of critical events
5. **Limit orders by default:** 0.1% better than market price
6. **All trade management is deterministic:** No LLM in the management loop

### Projected Impact

- Current win rate (estimated): 55-60%
- Projected win rate: 72-80% (base case: 75%)
- Effective R:R improvement: 2:1 → 2.5-3.5:1 (with partial exits + trailing)

### Priority Improvements (Ranked)

1. 🔴 Trailing stops (biggest impact on win rate)
2. 🔴 Partial exits (biggest impact on R:R)
3. 🟡 Session timing (easy win, significant impact)
4. 🟡 News blackout (already have MarketCalendar)
5. 🟢 Pullback entries (moderate impact)
6. 🟢 Regime exits (already have RegimeDetector)
