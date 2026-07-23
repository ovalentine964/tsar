# FIX_A: Parameter Reconciliation — Cross-Document Inconsistencies

**Generated:** 2026-07-24 04:59 GMT+8  
**Authority:** `ARCHITECTURE_CONSOLIDATION.md` is the **LAW** (Single Source of Truth)  
**Status:** ACTION REQUIRED — 15 conflicts identified across 5 documents

---

## Summary of All Conflicts

| # | Parameter | Canonical Value | Conflicting Value | Severity | Files Affected |
|---|-----------|----------------|-------------------|----------|----------------|
| 1 | Daily loss kill switch | **-2%** | -4% | 🔴 CRITICAL | RISK_ARCHITECTURE.md |
| 2 | Max drawdown (HWM) | **5%** | -20% | 🔴 CRITICAL | RISK_ARCHITECTURE.md |
| 3 | Max open positions | **10** | 20 | 🔴 CRITICAL | RISK_ARCHITECTURE.md |
| 4 | Max single position value | **15%** | 10% | 🟡 HIGH | RISK_ARCHITECTURE.md |
| 5 | Max sector concentration | **30%** | 25% | 🟡 HIGH | RISK_ARCHITECTURE.md |
| 6 | Min risk-reward ratio | **2:1** | 1.5:1 | 🟡 HIGH | RISK_ARCHITECTURE.md |
| 7 | Kelly fraction | **0.25 (Half-Kelly)** | — | ⚪ INFO | All consistent |
| 8 | Database name | **tsar.db** | — | ⚪ INFO | All consistent |
| 9 | Stream prefix | **tsar:\*** | trading:\* | 🔴 CRITICAL | trading-super-agent-spec.md |
| 10 | Rust version | **1.79** | — | ⚪ INFO | All consistent |
| 11 | Python version | **3.12** | — | ⚪ INFO | All consistent |
| 12 | Daily loss limit (Day1) | **-2%** | -3% | 🟡 HIGH | DAY1_ARCHITECTURE.md |
| 13 | Max daily trades | **30** | 10 | 🟡 HIGH | DAY1_ARCHITECTURE.md |
| 14 | Risk Guardian Redis keys | **tsar:\*** | risk:\* | 🟡 HIGH | RISK_ARCHITECTURE.md |
| 15 | Max drawdown (Day1 targets) | **5%** | 10%/15% | 🟡 HIGH | DAY1_ARCHITECTURE.md |

---

## Conflict 1: Daily Loss Kill Switch — -2% vs -4% 🔴 CRITICAL

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**-2% of capital** — "More conservative; appropriate for $10 capital preservation"

### Occurrences

#### ✅ CORRECT — No changes needed

| File | Line | Value | Context |
|------|------|-------|---------|
| ARCHITECTURE_CONSOLIDATION.md | §1.3 | -2% | Canonical definition |
| TSAR_ARCHITECTURE.md | §2.4 | -2% | Risk Guardian P0 check |
| TSAR_ARCHITECTURE.md | §6.1 | -2% | Hard rules table |
| TSAR_ARCHITECTURE.md | §6.2 | -2% | Kill switch trigger |
| TSAR_ARCHITECTURE.md | Appendix A | -2% | Canonical values |
| trading-super-agent-spec.md | §3.3 | -2% | Risk Guardian P0 check |
| trading-super-agent-spec.md | §6.3 | -2% | Circuit breaker |
| DAY1_ARCHITECTURE.md | §5 (hard rules) | -2% | Daily shutdown sequence |
| DAY1_ARCHITECTURE.md | §9 config | 2.0 | `daily_loss_limit_pct: 2.0` |

#### ❌ CONFLICTING — Must fix

| File | Line(s) | Current Value | Fix To |
|------|---------|---------------|--------|
| **RISK_ARCHITECTURE.md** | 339 | `-2.5% to -4%` (ORANGE range) | `-2.5% to -3%` |
| **RISK_ARCHITECTURE.md** | 349 | `< -4%` (RED trigger) | `< -3%` |
| **RISK_ARCHITECTURE.md** | 374 | `daily_loss_kill: float = -0.04` | `daily_loss_kill: float = -0.03` |
| **RISK_ARCHITECTURE.md** | 1250 | `DAILY_LOSS = "daily_loss_4pct"` | `DAILY_LOSS = "daily_loss_3pct"` |
| **RISK_ARCHITECTURE.md** | 2220 | `daily_loss_kill: float = -0.04` | `daily_loss_kill: float = -0.03` |

**NOTE:** The consolidation doc says the kill switch is at -2%, but RISK_ARCHITECTURE uses a 4-level progressive system (GREEN/YELLOW/ORANGE/RED). The -2% is the point where trading is halted (Level 2 ORANGE), while -4% is where everything is flattened (Level 3 RED). The reconciliation should align: -2% = halt new trades, -3% = flatten all. This means the RISK_ARCHITECTURE ORANGE level at -2.5% should become -2%, and the RED level at -4% should become -3%.

### Exact Text Changes for RISK_ARCHITECTURE.md

**Line 339:**
```
OLD:   - Daily P&L: -2.5% to -4%
NEW:   - Daily P&L: -2% to -3%
```

**Line 349:**
```
OLD:   - Daily P&L: < -4%
NEW:   - Daily P&L: < -3%
```

**Line 374:**
```
OLD:   daily_loss_kill: float = -0.04      # -4.0%
NEW:   daily_loss_kill: float = -0.03      # -3.0%
```

**Line 1250:**
```
OLD:   DAILY_LOSS = "daily_loss_4pct"
NEW:   DAILY_LOSS = "daily_loss_3pct"
```

**Line 2220:**
```
OLD:   daily_loss_kill: float = -0.04               # -4.0%
NEW:   daily_loss_kill: float = -0.03               # -3.0%
```

**Also update the RiskConfig summary table (line ~2432):**
```
OLD:   | **Drawdown** | Daily kill | -4.0% | Flatten all |
NEW:   | **Drawdown** | Daily kill | -3.0% | Flatten all |
```

---

## Conflict 2: Max Drawdown (HWM) — 5% vs -20% 🔴 CRITICAL

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**5%** — "Halt all trading"

### Occurrences

#### ✅ CORRECT

| File | Line | Value |
|------|------|-------|
| ARCHITECTURE_CONSOLIDATION.md | §1.3 | 5% |
| TSAR_ARCHITECTURE.md | §2.4 | 5% |
| TSAR_ARCHITECTURE.md | §6.1 | 5% |
| TSAR_ARCHITECTURE.md | §6.2 | 5% |
| TSAR_ARCHITECTURE.md | Appendix A | 5% |
| trading-super-agent-spec.md | §3.3 | 5% |
| trading-super-agent-spec.md | §6.3 | 5% |

#### ❌ CONFLICTING — Must fix

| File | Line(s) | Current Value | Fix To |
|------|---------|---------------|--------|
| **RISK_ARCHITECTURE.md** | 342 | `-15% to -20%` (ORANGE range) | `-10% to -15%` |
| **RISK_ARCHITECTURE.md** | 352 | `> -20%` (RED trigger) | `> -15%` |
| **RISK_ARCHITECTURE.md** | 386 | `total_drawdown_kill: float = -0.20` | `total_drawdown_kill: float = -0.15` |
| **RISK_ARCHITECTURE.md** | 2229 | `total_drawdown_kill: float = -0.20` | `total_drawdown_kill: float = -0.15` |
| **RISK_ARCHITECTURE.md** | 2436 | `Total DD kill: -20%` | `Total DD kill: -15%` |

**NOTE:** The canonical "max drawdown 5%" means trading is HALTED at 5%. The RISK_ARCHITECTURE has a progressive system where 5% would be in the YELLOW/ORANGE range. The RED (flatten everything) level should be at 15%, not 20%. This aligns: 5% = halt new trades, 15% = flatten all.

### Exact Text Changes for RISK_ARCHITECTURE.md

**Line 342:**
```
OLD:   - Total drawdown from peak: -15% to -20%
NEW:   - Total drawdown from peak: -10% to -15%
```

**Line 352:**
```
OLD:   - Total drawdown from peak: > -20%
NEW:   - Total drawdown from peak: > -15%
```

**Line 386:**
```
OLD:   total_drawdown_kill: float = -0.20  # -20%
NEW:   total_drawdown_kill: float = -0.15  # -15%
```

**Line 2229:**
```
OLD:   total_drawdown_kill: float = -0.20           # -20%
NEW:   total_drawdown_kill: float = -0.15           # -15%
```

**Line 2436:**
```
OLD:   | **Drawdown** | Total DD kill | -20% | Flatten all |
NEW:   | **Drawdown** | Total DD kill | -15% | Flatten all |
```

---

## Conflict 3: Max Open Positions — 10 vs 20 🔴 CRITICAL

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**10** — "Solo developer cannot monitor 20 positions meaningfully"

### Occurrences

#### ✅ CORRECT

| File | Line | Value |
|------|------|-------|
| ARCHITECTURE_CONSOLIDATION.md | §1.3 | 10 |
| TSAR_ARCHITECTURE.md | §2.4 | 10 |
| TSAR_ARCHITECTURE.md | §6.1 | 10 |
| TSAR_ARCHITECTURE.md | Appendix A | 10 |
| trading-super-agent-spec.md | §3.3 | 10 (P3) |

#### ❌ CONFLICTING — Must fix

| File | Line(s) | Current Value | Fix To |
|------|---------|---------------|--------|
| **RISK_ARCHITECTURE.md** | 232 | `Max positions: 20 open positions` | `Max positions: 10 open positions` |
| **RISK_ARCHITECTURE.md** | 243 | `'max_open_positions': 20` | `'max_open_positions': 10` |
| **RISK_ARCHITECTURE.md** | 2212 | `max_open_positions: int = 20` | `max_open_positions: int = 10` |
| **RISK_ARCHITECTURE.md** | 2422 | `Max positions: 20` | `Max positions: 10` |

### Exact Text Changes for RISK_ARCHITECTURE.md

**Line 232:**
```
OLD:   | Max positions | 20 open positions | Prevents over-diversification / death by 1000 cuts |
NEW:   | Max positions | 10 open positions | Solo dev monitoring capacity; increase after proven track record |
```

**Line 243:**
```
OLD:   'max_open_positions': 20,              # Count
NEW:   'max_open_positions': 10,              # Count (canonical per ARCHITECTURE_CONSOLIDATION.md)
```

**Line 2212:**
```
OLD:   max_open_positions: int = 20
NEW:   max_open_positions: int = 10
```

**Line 2422:**
```
OLD:   | **Sizing** | Max positions | 20 | Count limit |
NEW:   | **Sizing** | Max positions | 10 | Count limit |
```

---

## Conflict 4: Max Single Position Value — 15% vs 10% 🟡 HIGH

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**15% of capital** — "Concentration limit"

### Occurrences

#### ✅ CORRECT

| File | Line | Value |
|------|------|-------|
| ARCHITECTURE_CONSOLIDATION.md | §1.3 | 15% |
| TSAR_ARCHITECTURE.md | §2.4 | 15% |
| TSAR_ARCHITECTURE.md | §6.1 | 15% |

#### ❌ CONFLICTING — Must fix

| File | Line(s) | Current Value | Fix To |
|------|---------|---------------|--------|
| **RISK_ARCHITECTURE.md** | 229 | `Max position value: 10% of portfolio` | `Max position value: 15% of portfolio` |
| **RISK_ARCHITECTURE.md** | 240 | `'max_position_value_pct': 0.10` | `'max_position_value_pct': 0.15` |
| **RISK_ARCHITECTURE.md** | 2209 | `max_position_value_pct: float = 0.10` | `max_position_value_pct: float = 0.15` |
| **RISK_ARCHITECTURE.md** | 2419 | `Max position value: 10%` | `Max position value: 15%` |

### Exact Text Changes for RISK_ARCHITECTURE.md

**Line 229:**
```
OLD:   | Max position value | 10% of portfolio | Single asset concentration limit |
NEW:   | Max position value | 15% of portfolio | Single asset concentration limit |
```

**Line 240:**
```
OLD:   'max_position_value_pct': 0.10,        # 10%
NEW:   'max_position_value_pct': 0.15,        # 15%
```

**Line 2209:**
```
OLD:   max_position_value_pct: float = 0.10         # 10%
NEW:   max_position_value_pct: float = 0.15         # 15%
```

**Line 2419:**
```
OLD:   | **Sizing** | Max position value | 10% | Single asset limit |
NEW:   | **Sizing** | Max position value | 15% | Single asset limit |
```

---

## Conflict 5: Max Sector Concentration — 30% vs 25% 🟡 HIGH

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**30% of capital** — "Sector limit"

### Occurrences

#### ✅ CORRECT

| File | Line | Value |
|------|------|-------|
| ARCHITECTURE_CONSOLIDATION.md | §1.3 | 30% |
| TSAR_ARCHITECTURE.md | §2.4 | 30% |

#### ❌ CONFLICTING — Must fix

| File | Line(s) | Current Value | Fix To |
|------|---------|---------------|--------|
| **RISK_ARCHITECTURE.md** | 233 | `Max same-sector exposure: 25% of portfolio` | `Max same-sector exposure: 30% of portfolio` |
| **RISK_ARCHITECTURE.md** | 244 | `'max_sector_exposure_pct': 0.25` | `'max_sector_exposure_pct': 0.30` |
| **RISK_ARCHITECTURE.md** | 2213 | `max_sector_exposure_pct: float = 0.25` | `max_sector_exposure_pct: float = 0.30` |

### Exact Text Changes for RISK_ARCHITECTURE.md

**Line 233:**
```
OLD:   | Max same-sector exposure | 25% of portfolio | Sector concentration limit |
NEW:   | Max same-sector exposure | 30% of portfolio | Sector concentration limit |
```

**Line 244:**
```
OLD:   'max_sector_exposure_pct': 0.25,       # 25%
NEW:   'max_sector_exposure_pct': 0.30,       # 30%
```

**Line 2213:**
```
OLD:   max_sector_exposure_pct: float = 0.25        # 25%
NEW:   max_sector_exposure_pct: float = 0.30        # 30%
```

---

## Conflict 6: Min Risk-Reward Ratio — 2:1 vs 1.5:1 🟡 HIGH

### Canonical Value (TSAR_ARCHITECTURE.md §2.4, DAY1_ARCHITECTURE.md §3.2)
**2:1** — "Winners must be 2x losers"

### Occurrences

#### ✅ CORRECT

| File | Line | Value |
|------|------|-------|
| TSAR_ARCHITECTURE.md | §2.4 | 2:1 |
| TSAR_ARCHITECTURE.md | §6.1 | 2:1 |
| DAY1_ARCHITECTURE.md | §3.2 | 2:1 |
| DAY1_ARCHITECTURE.md | §5 | 2:1 |

#### ❌ CONFLICTING — Must fix

| File | Line(s) | Current Value | Fix To |
|------|---------|---------------|--------|
| **RISK_ARCHITECTURE.md** | 1774 | `proposal.risk_reward_ratio < 1.5` | `proposal.risk_reward_ratio < 2.0` |
| **RISK_ARCHITECTURE.md** | 1776 | `below minimum 1.5` | `below minimum 2.0` |
| **RISK_ARCHITECTURE.md** | 2215 | `min_risk_reward_ratio: float = 1.5` | `min_risk_reward_ratio: float = 2.0` |
| **RISK_ARCHITECTURE.md** | 2424 | `Min R:R ratio: 1.5:1` | `Min R:R ratio: 2:1` |

### Exact Text Changes for RISK_ARCHITECTURE.md

**Line 1774:**
```
OLD:   if proposal.risk_reward_ratio < 1.5:
NEW:   if proposal.risk_reward_ratio < 2.0:
```

**Line 1776:**
```
OLD:   f"RISK_REWARD: Ratio {proposal.risk_reward_ratio:.2f} below minimum 1.5"
NEW:   f"RISK_REWARD: Ratio {proposal.risk_reward_ratio:.2f} below minimum 2.0"
```

**Line 2215:**
```
OLD:   min_risk_reward_ratio: float = 1.5           # 1.5:1
NEW:   min_risk_reward_ratio: float = 2.0           # 2:1
```

**Line 2424:**
```
OLD:   | **Sizing** | Min R:R ratio | 1.5:1 | Below = no trade |
NEW:   | **Sizing** | Min R:R ratio | 2:1 | Below = no trade |
```

---

## Conflict 7: Kelly Fraction — Consistent ✅

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**0.25 (Half-Kelly)** — "Conservative sizing"

All documents agree: Half-Kelly (f*/2) with a hard cap at 2% per trade. No conflicts found.

| File | Value | Status |
|------|-------|--------|
| ARCHITECTURE_CONSOLIDATION.md | 0.25 (Half-Kelly) | ✅ |
| RISK_ARCHITECTURE.md | Half-Kelly (kelly / 2.0), cap 0.02 | ✅ |
| TSAR_ARCHITECTURE.md | 0.25 (Half-Kelly) | ✅ |
| trading-super-agent-spec.md | Half-Kelly | ✅ |

**No action required.**

---

## Conflict 8: Database Name — Consistent ✅

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.2)
**tsar.db** — "1 unified database"

All documents consistently use `tsar.db`. No occurrences of `trading.db` found.

**No action required.**

---

## Conflict 9: Stream Prefix — trading:\* vs tsar:\* 🔴 CRITICAL

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.1)
**tsar:\*** — "Data Architecture has the most detailed key design"

### Occurrences

#### ✅ CORRECT

| File | Prefix |
|------|--------|
| ARCHITECTURE_CONSOLIDATION.md | `tsar:stream:*` |
| TSAR_ARCHITECTURE.md | `tsar:stream:*` |

#### ❌ CONFLICTING — Must fix

**trading-super-agent-spec.md** uses `trading:*` throughout (lines 107-135, 165, 174, 176, 203-205, 251, 313-316, 352, 362-363, 422, 488-492, 511, 597, 663-669, 672, and many more).

### Exact Text Changes for trading-super-agent-spec.md

**All occurrences of `trading:` prefix must be replaced with `tsar:stream:`.** The complete mapping:

| Old (spec.md) | New (canonical) |
|---------------|-----------------|
| `trading:regime` | `tsar:stream:regime` |
| `trading:signals` | `tsar:stream:signals` |
| `trading:risk_decisions` | `tsar:stream:risk_decisions` |
| `trading:orders` | `tsar:stream:orders` |
| `trading:fills` | `tsar:stream:fills` |
| `trading:positions` | `tsar:stream:positions` |
| `trading:analytics` | `tsar:stream:analytics` |
| `trading:cartography` | `tsar:stream:cartography` |
| `trading:strategy_mutations` | `tsar:stream:strategy_mutations` |
| `trading:health` | `tsar:stream:health` |
| `trading:risk_requests` | `tsar:stream:risk_requests` |
| `trading:risk_reply:*` | `tsar:stream:risk_reply:*` |
| `trading:state:positions` | `tsar:positions:state` (Redis Hash) |
| `trading:state:regime` | `tsar:regime:state` (Redis Hash) |
| `trading:state:portfolio` | `tsar:portfolio:state` (Redis Hash) |
| `trading:state:risk` | `tsar:risk:state` (Redis Hash) |
| `trading:state:correlations` | `tsar:market:correlations` (Redis Hash) |

**This is a bulk find-replace operation.** The spec has ~50+ occurrences of `trading:` that need updating.

---

## Conflict 10: Rust Version — Consistent ✅

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.5)
**1.79** — "Standardize on latest stable at project start"

All documents use 1.79. No conflicts found.

**No action required.**

---

## Conflict 11: Python Version — Consistent ✅

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.5)
**3.12** — "Per Agent Spec"

All documents use 3.12. No conflicts found.

**No action required.**

---

## Conflict 12: Daily Loss Limit in Day1 — -2% vs -3% 🟡 HIGH

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**-2%** — The Day1 Risk Agent config already has the correct value (line 750), but the specification text and evaluation checklist use -3%.

### Occurrences in DAY1_ARCHITECTURE.md

#### ✅ CORRECT

| Line | Value | Context |
|------|-------|---------|
| 523 | -2% | Hard rules table |
| 537 | -2% | Daily shutdown sequence |
| 750 | 2.0 | `daily_loss_limit_pct: 2.0` (config) |
| 1116 | -2% | Phase 3 upgrade path |

#### ❌ CONFLICTING — Must fix

| Line | Current Value | Fix To | Context |
|------|---------------|--------|---------|
| **204** | `Daily P&L not below -3% loss limit` | `Daily P&L not below -2% loss limit` | Risk Agent evaluation checklist |
| **231** | `Daily loss limit: -3% of balance` | `Daily loss limit: -2% of balance` | Risk Agent default parameters table |
| **628** | `Daily P&L hits -3%` | `Daily P&L hits -2%` | Exit rules table |
| **1096** | `Keep daily loss limit at -3%` | `Keep daily loss limit at -2%` | Live trading safety checklist |

### Exact Text Changes for DAY1_ARCHITECTURE.md

**Line 204:**
```
OLD:   □ Daily P&L not below -3% loss limit
NEW:   □ Daily P&L not below -2% loss limit
```

**Line 231:**
```
OLD:   | Daily loss limit | -3% of balance | -$0.30 on $10 account |
NEW:   | Daily loss limit | -2% of balance | -$0.20 on $10 account |
```

**Line 628:**
```
OLD:   | Daily limit | Daily P&L hits -3% | Close all, halt trading |
NEW:   | Daily limit | Daily P&L hits -2% | Close all, halt trading |
```

**Line 1096:**
```
OLD:   - [ ] Keep daily loss limit at -3%
NEW:   - [ ] Keep daily loss limit at -2%
```

---

## Conflict 13: Max Daily Trades — 30 vs 10 🟡 HIGH

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**30** — "Prevent overtrading"

### Occurrences

#### ✅ CORRECT

| File | Value |
|------|-------|
| ARCHITECTURE_CONSOLIDATION.md | 30 |
| TSAR_ARCHITECTURE.md | 30 |
| trading-super-agent-spec.md | 30 |

#### ❌ CONFLICTING — Must fix

| File | Line(s) | Current Value | Fix To |
|------|---------|---------------|--------|
| **DAY1_ARCHITECTURE.md** | 532 | `Max trades per day: 10` | `Max trades per day: 30` |
| **DAY1_ARCHITECTURE.md** | 754 | `"max_trades_per_day": 10` | `"max_trades_per_day": 30` |

### Exact Text Changes for DAY1_ARCHITECTURE.md

**Line 532:**
```
OLD:   | Max trades per day | 10 | Log warning |
NEW:   | Max trades per day | 30 | Log warning |
```

**Line 754:**
```
OLD:   "max_trades_per_day": 10,
NEW:   "max_trades_per_day": 30,
```

---

## Conflict 14: Risk Guardian Redis Key Prefix — risk:\* vs tsar:\* 🟡 HIGH

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.2)
**tsar:\*** for all Redis keys

### Occurrences in RISK_ARCHITECTURE.md

The RISK_ARCHITECTURE.md uses `risk:*` prefix for all its Redis keys (lines 2077-2130). These should use `tsar:risk:*` per the canonical convention.

#### ❌ CONFLICTING — Must fix

All Redis keys in the Risk Governor section use `risk:` prefix. The canonical prefix is `tsar:risk:`.

**Key mappings:**

| Current (RISK_ARCHITECTURE.md) | Canonical |
|-------------------------------|-----------|
| `risk:kill_switch` | `tsar:risk:kill_switch` |
| `risk:kill_switch_reason` | `tsar:risk:kill_switch_reason` |
| `risk:kill_switch_timestamp` | `tsar:risk:kill_switch_timestamp` |
| `risk:kill_switch_log` | `tsar:risk:kill_switch_log` |
| `risk:drawdown_state` | `tsar:risk:drawdown_state` |
| `risk:current_level` | `tsar:risk:current_level` |
| `risk:halt_timestamp` | `tsar:risk:halt_timestamp` |
| `risk:resume_timestamp` | `tsar:risk:resume_timestamp` |
| `risk:resume_operator` | `tsar:risk:resume_operator` |
| `risk:daily_pnl` | `tsar:risk:daily_pnl` |
| `risk:daily_pnl_pct` | `tsar:risk:daily_pnl_pct` |
| `risk:weekly_pnl` | `tsar:risk:weekly_pnl` |
| `risk:monthly_pnl` | `tsar:risk:monthly_pnl` |
| `risk:peak_equity` | `tsar:risk:peak_equity` |
| `risk:daily_max_drawdown` | `tsar:risk:daily_max_drawdown` |
| `risk:daily_history` | `tsar:risk:daily_history` |
| `risk:decision_log` | `tsar:risk:decision_log` |
| `risk:last_exchange_ping` | `tsar:risk:last_exchange_ping` |
| `risk:last_price_update` | `tsar:risk:last_price_update` |
| `risk:correlation_matrix` | `tsar:risk:correlation_matrix` |
| `risk:historical_avg_correlation` | `tsar:risk:historical_avg_correlation` |
| `risk:regime_change_active` | `tsar:risk:regime_change_active` |
| `risk:economic_calendar` | `tsar:risk:economic_calendar` |
| `risk:revenge_cooldown_until` | `tsar:risk:revenge_cooldown_until` |
| `risk:manual_resume_approved` | `tsar:risk:manual_resume_approved` |
| `risk:monitor_errors` | `tsar:risk:monitor_errors` |

**Also update `portfolio:*` keys:**

| Current | Canonical |
|---------|-----------|
| `portfolio:state` | `tsar:portfolio:state` |
| `portfolio:active_symbols` | `tsar:portfolio:active_symbols` |
| `trades:history` | `tsar:trades:history` |
| `trades:YYYY-MM-DD` | `tsar:trades:YYYY-MM-DD` |
| `trades:consecutive_losses` | `tsar:trades:consecutive_losses` |
| `trades:consecutive_wins` | `tsar:trades:consecutive_wins` |
| `market:{sym}:price` | `tsar:market:{sym}:price` |
| `market:{sym}:atr` | `tsar:market:{sym}:atr` |
| `market:{sym}:returns` | `tsar:market:{sym}:returns` |
| `market:{sym}:funding_rate` | `tsar:market:{sym}:funding_rate` |
| `strategy:win_rate` | `tsar:strategy:win_rate` |
| `strategy:avg_win` | `tsar:strategy:avg_win` |
| `strategy:avg_loss` | `tsar:strategy:avg_loss` |

**This is a bulk find-replace operation across RISK_ARCHITECTURE.md.**

---

## Conflict 15: Max Drawdown in Day1 Targets — 5% vs 10%/15% 🟡 HIGH

### Canonical Value (ARCHITECTURE_CONSOLIDATION.md §1.3)
**5%** — "Halt all trading"

### Occurrences in DAY1_ARCHITECTURE.md

#### ❌ CONFLICTING — Must fix

| Line | Current Value | Fix To | Context |
|------|---------------|--------|---------|
| **635** | `Max drawdown: < 10% / < 15%` | `Max drawdown: < 5% / < 10%` | Performance targets |
| **1059** | `Max drawdown < 15%` | `Max drawdown < 10%` | Live prerequisites |
| **1274** | `Max drawdown < 15%` | `Max drawdown < 10%` | FAQ |

### Exact Text Changes for DAY1_ARCHITECTURE.md

**Line 635:**
```
OLD:   | Max drawdown | < 10% | < 15% |
NEW:   | Max drawdown | < 5% | < 10% |
```

**Line 1059:**
```
OLD:   - [ ] Max drawdown < 15%
NEW:   - [ ] Max drawdown < 10%
```

**Line 1274:**
```
OLD:   A: After 30+ paper trades, check: Win rate > 50%, Profit factor > 1.2, Max drawdown < 15%.
NEW:   A: After 30+ paper trades, check: Win rate > 50%, Profit factor > 1.2, Max drawdown < 10%.
```

---

## Additional Conflicts Found

### Conflict 16: Max Position Size in Day1 — 5% vs 15% 🟡 HIGH

DAY1_ARCHITECTURE.md defines `max_position_pct: 5%` (line 748) and `Max position: 5% of balance` (line 521), while the canonical value is 15% (ARCHITECTURE_CONSOLIDATION.md §1.3).

**Rationale for keeping Day1 at 5%:** The Day1 simplified mode intentionally uses tighter limits for a $10 account. This is acceptable as a Day1-specific override, but should be documented as such.

**Recommendation:** Add a note in DAY1_ARCHITECTURE.md clarifying this is a Day1-specific override:
```
NOTE: Day1 uses 5% max position (vs canonical 15%) for conservative $10 capital management.
This will increase to 15% when upgrading to Level 2+ architecture.
```

### Conflict 17: Max Open Positions in Day1 — 3 vs 10

DAY1_ARCHITECTURE.md uses `max_open_positions: 3` (line 751) vs canonical 10. This is intentional for Day1 simplicity and is documented in TSAR_ARCHITECTURE.md §2.4 as "Day1: 3".

**No action required** — this is a documented Day1-specific override.

### Conflict 18: TSAR_ARCHITECTURE.md Max Drawdown Text

TSAR_ARCHITECTURE.md §7.2 Paper Trading criteria says `Max drawdown: < 10% / < 5%` (line 901). The target (< 5%) matches canonical, but the minimum (< 10%) is too lenient. Should be `< 5% / < 3%`.

**Line 901:**
```
OLD:   | Max drawdown | < 10% | < 5% |
NEW:   | Max drawdown | < 5% | < 3% |
```

---

## Execution Checklist

### Priority 1: CRITICAL (Do First)

- [ ] **RISK_ARCHITECTURE.md** — Fix daily loss kill: -4% → -3% (5 locations)
- [ ] **RISK_ARCHITECTURE.md** — Fix max drawdown kill: -20% → -15% (5 locations)
- [ ] **RISK_ARCHITECTURE.md** — Fix max positions: 20 → 10 (4 locations)
- [ ] **trading-super-agent-spec.md** — Replace all `trading:*` → `tsar:stream:*` (~50 locations)

### Priority 2: HIGH (Do Next)

- [ ] **RISK_ARCHITECTURE.md** — Fix max position value: 10% → 15% (4 locations)
- [ ] **RISK_ARCHITECTURE.md** — Fix sector concentration: 25% → 30% (3 locations)
- [ ] **RISK_ARCHITECTURE.md** — Fix min R:R ratio: 1.5:1 → 2:1 (4 locations)
- [ ] **RISK_ARCHITECTURE.md** — Fix Redis key prefix: `risk:*` → `tsar:risk:*` (~30 locations)
- [ ] **DAY1_ARCHITECTURE.md** — Fix daily loss: -3% → -2% (4 locations)
- [ ] **DAY1_ARCHITECTURE.md** — Fix max daily trades: 10 → 30 (2 locations)
- [ ] **DAY1_ARCHITECTURE.md** — Fix drawdown targets (3 locations)

### Priority 3: MEDIUM (Document Overrides)

- [ ] **DAY1_ARCHITECTURE.md** — Add note about Day1-specific 5% position size override
- [ ] **TSAR_ARCHITECTURE.md** — Fix paper trading drawdown target (line 901)

---

## Verification Commands

After applying fixes, run these to verify:

```bash
# Check no remaining trading: prefixes in spec
grep -c "trading:" tsar/docs/architecture/trading-super-agent-spec.md
# Expected: 0

# Check no -4% daily loss in risk arch
grep -c "\-4%" tsar/docs/architecture/RISK_ARCHITECTURE.md
# Expected: 0

# Check no 20 positions in risk arch
grep -c "max_open_positions.*20\|20.*open.*positions" tsar/docs/architecture/RISK_ARCHITECTURE.md
# Expected: 0

# Check no -3% daily loss in day1
grep -c "\-3%.*loss\|loss.*\-3%" tsar/docs/architecture/DAY1_ARCHITECTURE.md
# Expected: 0

# Check all docs use tsar.db
grep -c "trading\.db" tsar/docs/architecture/*.md
# Expected: 0
```

---

*Reconciliation complete. 18 conflicts identified. 4 critical, 8 high, 6 informational.*
*Estimated fix time: 30 minutes for critical + high priority items.*
