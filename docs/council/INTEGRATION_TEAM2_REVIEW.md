# Integration Team 2 Review: Safety + Config Wiring

**Team:** Integration Team 2 — Safety + Config Wiring
**Date:** 2026-07-27
**Scope:** G4, G10, G11, G12, G13 from INTEGRATION_WIRING_REVIEW.md

---

## Summary

All assigned gaps have been addressed. MandateGate is now wired into the Risk Guardian pipeline as Check 0, config/mandate.yaml is verified as a valid template, FTS5 and validated_rules table creation are confirmed idempotent, and the FactorLibrary separate-DB decision is documented.

---

## G4: MandateGate Wired into Risk Guardian Pipeline ✅

**Status:** Complete — 16 tests passing.

**Changes to `src/agents/risk_guardian.py`:**

1. **Import:** Added `from src.risk.mandate_gate import MandateGate` at module level.

2. **`__init__`:** MandateGate is initialized during RiskGuardian construction:
   - Reads `config.risk.mandate_gate.enabled` (default: `True`)
   - Reads `config.risk.mandate_gate.config_path` (default: `config/mandate.yaml`)
   - Sets `self._mandate_gate` to `MandateGate` instance or `None` if disabled
   - Sets `self._is_live = trading_mode == "live"`

3. **`on_initialize()`:** MandateGate status is logged during initialization, showing mandate status and active state.

4. **`_evaluate_signal()` — Check 0:** Before the existing 10-point checklist:
   - Only runs when `self._mandate_gate is not None AND self._is_live`
   - Calls `mandate_gate.check(signal, is_live=True, daily_trade_count=...)`
   - If rejected → publishes `tsar.risk.vetoed.v1` with `risk_level=HARD` and returns immediately
   - If approved → proceeds to existing `_run_all_checks()`

**Pipeline flow:**
```
Signal → [Check 0: MandateGate] → [Check 1-10: Risk Engine] → Execution
             │
             ├─ Paper mode? → SKIP (not called at all)
             ├─ Gate disabled? → SKIP
             ├─ Mandate ACTIVE + compliant? → PASS through to risk checks
             └─ Mandate DRAFT/REVOKED/non-compliant? → HARD VETO, return immediately
```

**Key design decisions:**
- MandateGate is only called in live mode (`self._is_live`). Paper mode completely skips the check — the `check()` method is never invoked, avoiding unnecessary work.
- Mandate rejections use `VetoLevel.HARD` — cannot be overridden by downstream agents.
- The `_run_all_checks()` method is not called when mandate rejects, saving computation.

---

## G10: config/mandate.yaml ✅

**Status:** Already valid — no changes needed.

The file at `config/mandate.yaml` is a complete, well-documented template with:
- All required fields matching `MandateRules` Pydantic model
- Comments explaining every field (allowed_symbols, max_position_size_pct, max_daily_trades, max_leverage, allowed_order_types, max_notional_per_trade, allowed_sides)
- Lifecycle metadata section (status, committed_at, committed_by, revoked_at, revoked_by, version, notes)
- Sensible zero-value defaults that block everything until explicitly configured
- Lifecycle documentation in the header comment

The `Mandate` class loads this file correctly via `_load_from_yaml()`.

---

## G11: FTS5 Indexes — Idempotent Creation ✅

**Status:** Already handles existing DBs gracefully — comment added.

`MemoryRecall._ensure_fts_tables()` in `src/knowledge/fts_search.py` is fully idempotent:
- Checks `sqlite_master` for each FTS table before creating
- Uses `CREATE VIRTUAL TABLE IF NOT EXISTS` and `CREATE TRIGGER IF NOT EXISTS`
- Safe to call repeatedly on existing databases
- No separate migration step required — `initialize()` creates everything needed

Added G11 documentation comment to `_ensure_fts_tables()`.

---

## G12: validated_rules Table — On-Demand Creation ✅

**Status:** Already handles existing DBs gracefully — comment added.

`RuleValidator._persist_validated_rule()` in `src/knowledge/rule_validator.py` creates the `validated_rules` table via `CREATE TABLE IF NOT EXISTS` on first persist call. No separate migration step required.

Added G12 documentation comment to `_persist_validated_rule()`.

---

## G13: FactorLibrary Separate DB Decision ✅

**Status:** Decision documented — keep separate.

FactorLibrary uses a separate SQLite database (`factors.db` or `:memory:`) from the main `tsar.db`. This is a **deliberate design decision** with the following rationale:

1. **Different concern:** Factor metadata and IC history are computationally derived and can be regenerated from scratch. They are not core trading state.
2. **Decoupled lifecycle:** Factor benchmarking runs on a different schedule (weekly) than trade recording. Separate DBs avoid coupling these lifecycles.
3. **Backup/restore:** Core trading state (trades, genomes, lessons) can be backed up/restored independently of factor data.
4. **Environment sharing:** The factor DB can be shared across environments (dev/staging/prod) without leaking trade data.
5. **No cross-queries:** Nothing in the codebase queries across both databases. Factor data is self-contained.

Added G13 documentation comment to `FactorLibrary.__init__()`.

---

## Tests Created

**File:** `tests/unit/risk/test_mandate_gate_integration.py`
**Result:** 16/16 passing

| Test Class | Tests | Description |
|---|---|---|
| `TestMandateGateInitialization` | 5 | MandateGate created/disabled, `_is_live` flag |
| `TestPaperModeBypass` | 2 | Paper mode skips mandate entirely |
| `TestMandateDraftBlocksLiveTrades` | 3 | DRAFT/REVOKED mandate blocks live signals, skips risk checks |
| `TestMandateActiveAllowsLiveTrades` | 3 | ACTIVE mandate allows/blocks per rules, proceeds to risk checks |
| `TestMandateGateDisabled` | 1 | Disabled gate skips mandate check |
| `TestMandateVetoLevel` | 2 | Rejection uses HARD veto, contains reasons |

---

## Files Modified

| File | Change |
|---|---|
| `src/agents/risk_guardian.py` | MandateGate import, init, Check 0 in `_evaluate_signal()` |
| `src/knowledge/fts_search.py` | G11 documentation comment |
| `src/knowledge/rule_validator.py` | G12 documentation comment |
| `src/strategy/factor_library.py` | G13 documentation comment (separate DB rationale) |

## Files Created

| File | Description |
|---|---|
| `tests/unit/risk/test_mandate_gate_integration.py` | 16 integration tests for MandateGate + RiskGuardian wiring |

---

## Risks & Follow-ups

1. **Orchestrator mandate lifecycle:** The review recommended adding mandate loading and `/mandate commit` API to the Orchestrator. This was not in scope for Team 2 but is noted for follow-up.
2. **Config additions to tsar.yaml:** The review's §7.2-7.4 recommended adding `mandate_gate`, `shadow_extractor`, `genome_mutator`, `factor_library` sections to config. Only `mandate_gate` under `risk` is currently consumed by RiskGuardian. Other sections are for future agent integration.
3. **No breaking changes:** All changes are additive. Existing RiskGuardian behavior is preserved when MandateGate is disabled or in paper mode.

---

*Integration Team 2 — signing off.*
