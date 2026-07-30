# TSAR Risk Hardening — Fix Team Summary

**Team:** Risk Hardening  
**Date:** 2026-07-30  
**Issues Fixed:** C-013, C-014, C-015, C-016, H-005, C-001

---

## C-013: Kill Switch Monitor No Watchdog ✅

**Problem:** If the main TSAR process dies (crash, OOM, unhandled exception), there was no mechanism to detect the failure and trigger the kill switch. Trading would continue with stale state.

**Solution:** Created `src/risk/watchdog.py` — an external watchdog process that monitors main process health via a heartbeat file.

**Implementation:**
- **Watchdog class** runs as a separate async task or process
- Main process writes `heartbeat.json` every ~1-2 seconds via `Watchdog.write_heartbeat()` (static method, no instance needed)
- Watchdog reads heartbeat file every 5 seconds (configurable)
- If heartbeat is stale > 30 seconds OR main process PID is dead → triggers kill switch
- **Stale threshold of 3** consecutive stale reads prevents false positives from filesystem hiccups
- **Startup grace period** (60s) prevents false triggers during initialization
- Watchdog writes its own "alive" marker file so external monitoring can verify it's running
- Emergency fallback: if KillSwitch.activate() fails, writes emergency kill switch file directly to `/tmp/tsar_kill_switch_emergency`

**Config added to `risk.yaml`:**
```yaml
kill_switch:
  watchdog:
    enabled: true
    check_interval_seconds: 5
    max_stale_seconds: 30
    stale_threshold: 3
    startup_grace_seconds: 60
    check_pid: true
```

**Files changed:**
- `src/risk/watchdog.py` (NEW — 320 lines)
- `config/risk.yaml` (added watchdog section)

---

## C-014: Guard State Doesn't Persist ✅

**Problem:** GuardState (revenge cooldown, greed cap, win/loss streaks) was stored in Redis or in-memory cache. If the process restarts, ALL behavioral guard state is lost — the system forgets it was on revenge cooldown, forgot win streaks, etc.

**Solution:** Rewrote `src/risk/guard_state.py` with SQLite-backed persistence. Updated `src/risk/guards.py` to integrate with persistent state.

**Implementation:**
- **Three-layer storage:** Memory cache → Redis (optional) → SQLite (source of truth)
- **Write-through:** All writes go to all three layers simultaneously
- **Read path:** Memory → Redis → SQLite → default (never crashes, always returns something)
- **SQLite WAL mode** for concurrent read performance
- **Atomic schema creation** — `CREATE TABLE IF NOT EXISTS`
- New methods: `get_cooldown_remaining_seconds()`, `append_trade_result()`, `get_snapshot()`, `close()`
- `AntiBehavioralGuards` updated to accept `persistent_state` parameter
- All guard checks (`_check_revenge`, `_check_greed`, `_check_overconfidence`) now read from persistent state when available
- `record_outcome()` writes to persistent state AND updates in-memory cache for immediate checks

**Files changed:**
- `src/risk/guard_state.py` (REWRITTEN — 280 lines)
- `src/risk/guards.py` (updated to integrate persistent state)

---

## C-015: Risk Parameter Inconsistencies ✅

**Problem:** Risk parameters existed in three places: risk.yaml, code defaults, and architecture docs. Code defaults didn't always match risk.yaml, creating drift.

**Solution:** Made `risk.yaml` the **single source of truth**. All code defaults now read from risk.yaml through the governor's config loading.

**Changes:**
- `RiskGovernor._build_sizer_config()` now reads ALL parameters from risk.yaml including fee and micro-capital sections
- `SizingConfig` dataclass expanded with all fee and micro-capital fields (with sensible defaults)
- `risk.yaml` expanded with new canonical sections: `fees`, `micro_capital`, `kill_switch.watchdog`
- Code defaults in dataclasses match risk.yaml values exactly (documented as "CODE DEFAULTS — risk.yaml overrides")

**Files changed:**
- `config/risk.yaml` (added fees, micro_capital, watchdog sections)
- `src/risk/position_sizer.py` (SizingConfig expanded)
- `src/risk/governor.py` (_build_sizer_config reads all params)

---

## C-016: Recovery Protocol Stubbed ✅

**Problem:** `get_recovery_allocation()` was hardcoded to return `1.0` (full size), meaning after a kill switch deactivation the system would immediately trade at full size — defeating the purpose of the circuit breaker.

**Solution:** Implemented full phased re-entry protocol in `RiskGovernor`.

**Implementation:**
- `get_recovery_allocation()` now implements time-based phased re-entry
- Recovery phases read from `risk.yaml` `recovery` section (or fallback defaults)
- **RED level recovery:** 5% → 10% → 25% → 50% → 100% over ~240 hours
- **ORANGE level recovery:** 10% → 25% → 50% → 100% over ~120 hours
- `start_recovery(level)` called automatically when kill switch is deactivated
- `get_recovery_state()` exposes recovery status for monitoring
- `deactivate_kill_switch()` now automatically starts recovery protocol
- `PositionRecovery.get_recovery_multiplier()` provides the multiplier for position sizing
- Phase advancement is time-based (automatic) with gate conditions defined in config

**Files changed:**
- `src/risk/governor.py` (recovery protocol implementation)
- `src/risk/position_recovery.py` (updated with recovery integration)

---

## H-005: $10 Capital Makes Risk Controls Inoperable ✅

**Problem:** With $10 capital, standard risk controls produce position sizes too small for exchange minimums. A 2% risk on $10 = $0.20 risk, which at BTC prices produces quantities below Binance's minimum order size.

**Solution:** Implemented micro-capital mode with adjusted parameters.

**Implementation:**
- `PositionSizer.calculate()` detects when equity < $50 (configurable threshold)
- **Micro-capital mode adjustments:**
  - Kelly fraction: 0.25 → 0.40 (more aggressive — absolute risk is already tiny)
  - Risk per trade: 2% → 5% (allows meaningful position sizes)
  - Max single position: 15% → 30%
- **Minimum notional enforcement:** If calculated notional < $5 (Binance minimum), attempts to increase quantity to meet minimum while staying within risk cap
- **Minimum quantity step enforcement:** Rounds quantity to valid exchange increments
- If meeting minimum would exceed risk cap → returns zero result with clear explanation
- Greed and overconfidence guards relaxed at micro scale (irrelevant at $10)
- Revenge and FOMO guards remain active (still relevant at any scale)

**Config in `risk.yaml`:**
```yaml
micro_capital:
  enabled: true
  threshold_usd: 50.0
  kelly_fraction: 0.40
  risk_per_trade_pct: 0.05
  max_single_position_pct: 0.30
  min_notional_usd: 5.0
  min_quantity_step: 0.00001
  relax_guards:
    anti_greed: true
    anti_overconfidence: true
    anti_revenge: false
    anti_fomo: false
```

**Edge cases tested (conceptually):**
- $5 equity: Micro mode active, 5% risk = $0.25, tries to meet $5 minimum
- $10 equity: Micro mode active, 5% risk = $0.50, Kelly at 40%
- $50 equity: Standard mode, 2% risk = $1.00
- $100 equity: Standard mode, 2% risk = $2.00

**Files changed:**
- `src/risk/position_sizer.py` (micro-capital mode)
- `config/risk.yaml` (micro_capital section)

---

## C-001: $10 Capital Architectural Incoherence ✅

**Problem:** Position sizing didn't account for exchange fees. Binance charges 0.1% maker/taker, which on a round-trip trade reduces the effective risk-reward ratio. For small accounts, fees can make otherwise profitable trades unprofitable.

**Solution:** Added fee-aware position sizing to the Kelly calculation.

**Implementation:**
- **Fee-adjusted Kelly:** Reduces the Kelly edge by the ratio of round-trip fees to risk-per-unit
  - `adjusted_kelly = base_kelly * max(0, 1 - (2 * entry_price * fee_pct / risk_per_unit))`
- **Net R:R check:** After calculating position size, verifies the net risk-reward ratio (after fees) meets minimum threshold (1.5:1 configurable)
  - If net R:R after fees < minimum → trade rejected (zero result)
- **Round-trip fee calculation:** `2 * notional * taker_fee_pct` (entry + exit, worst-case taker fees)
- Fee parameters are configurable in `risk.yaml` under `fees:` section
- Fee adjustment is conservative — assumes taker fees both ways (worst case)

**Config in `risk.yaml`:**
```yaml
fees:
  maker_fee_pct: 0.001        # 0.1% Binance default
  taker_fee_pct: 0.001        # 0.1% Binance default
  min_rr_ratio_after_fees: 1.5
  fee_adjusted_kelly: true
```

**Example impact:**
- Trade with 2:1 R:R, entry at $100, stop at $98 (2% risk)
- Round-trip fee: 2 * $100 * 0.001 = $0.20
- Net reward: $4.00 - $0.20 = $3.80
- Net R:R: 3.80/2.00 = 1.90:1 (still above 1.5 minimum ✓)
- Kelly edge reduced by ~5% due to fees

**Files changed:**
- `src/risk/position_sizer.py` (fee-aware Kelly + net R:R check)
- `config/risk.yaml` (fees section)

---

## Summary of All Files Changed

| File | Change Type | Issues |
|------|------------|--------|
| `src/risk/watchdog.py` | NEW | C-013 |
| `src/risk/guard_state.py` | REWRITTEN | C-014 |
| `src/risk/guards.py` | MODIFIED | C-014 |
| `src/risk/position_sizer.py` | REWRITTEN | C-015, H-005, C-001 |
| `src/risk/governor.py` | MODIFIED | C-015, C-016 |
| `src/risk/position_recovery.py` | REWRITTEN | C-016 |
| `src/risk/__init__.py` | MODIFIED | C-013, C-014 |
| `config/risk.yaml` | MODIFIED | C-013, C-015, H-005, C-001 |

## Safety Guarantees

- **Zero LLM calls** in any risk code — all decisions are deterministic
- **Zero external API calls** except Redis (optional) for kill switch state
- **Fail-safe defaults** — if config is missing, conservative defaults apply
- **Write-through persistence** — guard state survives process restarts
- **Atomic file writes** — no partial state corruption
- **Fee-aware sizing** rejects trades with insufficient R:R after fees
- **Micro-capital mode** ensures exchange minimums are met or trade is rejected
- **Recovery protocol** prevents full-size trading immediately after kill switch
