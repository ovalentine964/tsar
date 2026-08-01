---
name: risk
description: Risk management — position sizing, drawdown monitoring, behavioral guards, kill switch
tools: [risk_management, risk_state_monitor, drawdown_check, kill_switch, mandate_gate, pnl_tracker, win_rate_tracker]
requires_governance: false
---

# Risk Management Skill

## Purpose
Enforce deterministic risk controls across all trading operations. Zero LLM calls for risk decisions — all logic is rule-based and auditable.

## Instructions

### Pre-Trade Risk Check (7-Layer Veto Protocol)
Every proposed trade MUST pass all 7 layers:

1. **Kill Switch** — If active, HARD veto. No exceptions. No overrides.
2. **Input Validation** — Stop-loss present? Entry price valid? Symbol valid?
3. **Anti-FOMO** — Signal score ≥ 0.6 minimum threshold
4. **Time Rules** — Economic calendar blackouts (FOMC, CPI, NFP)
5. **Anti-Behavioral** — Revenge (3-loss cooldown), Greed (win streak cap), Overconfidence
6. **Drawdown Circuit Breaker** — GREEN/YELLOW/ORANGE/RED levels
7. **Position Limits** — Max positions, concentration, daily trade count

### Position Sizing
Use Half-Kelly criterion with fee adjustment:
```
kelly_fraction = 0.25 (conservative)
risk_per_trade = 2% of equity
max_single_position = 15% of equity

# Fee-adjusted sizing
effective_rr = rr_ratio - (2 × taker_fee)
adjusted_kelly = kelly × (effective_rr / rr_ratio)
```

### Drawdown Monitoring
Track portfolio drawdown in real-time:
- **GREEN** (< 2% daily loss): Normal trading
- **YELLOW** (2-3% daily loss): Position sizes reduced 50%
- **ORANGE** (3-5% daily loss): No new entries, flatten losers
- **RED** (> 5% daily loss): Kill switch activated, full halt

### Behavioral Guards
Deterministic guards against trading biases:

| Guard | Trigger | Action |
|-------|---------|--------|
| Anti-Revenge | 3 consecutive losses | 60-minute cooldown |
| Anti-Greed | 5+ win streak | 70% position sizing |
| Anti-FOMO | Score < 0.6 | Block signal |
| Anti-Overconfidence | 5+ win streak | 70% sizing (50% at 10+) |

### Recovery Protocol
After kill switch deactivation, phased re-entry:
- **RED level**: 5% → 10% → 25% → 50% → 100% (over ~10 days)
- **ORANGE level**: 10% → 25% → 50% → 100% (over ~5 days)

Each phase requires a gate condition (positive P&L, win rate > 40%, etc.)

## Tool Usage
```
risk_management     → Full 7-layer veto check
risk_state_monitor  → Current risk state dashboard
drawdown_check      → Drawdown circuit breaker level
kill_switch         → Emergency halt status/control
mandate_gate        → Human authorization check
pnl_tracker         → Realized/unrealized P&L
win_rate_tracker    → Win rate and streak tracking
```

## Audit Requirements
Every risk decision must be logged with:
- Timestamp
- Signal ID
- Layer that vetoed (if rejected)
- Position size calculated
- All warnings generated
- Guard state at time of check
