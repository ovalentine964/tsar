# Phase 3: Mandate-Gated Live Trading — Council Review

**Date:** 2026-07-27
**Author:** Engineering Subagent
**Status:** IMPLEMENTED — Ready for Council Sign-Off

---

## Executive Summary

Phase 3 introduces the **Mandate** — a human-committed authorization boundary that defines what the trading system is ALLOWED to trade. This is distinct from the Risk Guardian, which determines what is SAFE to trade. Together they form a dual-gate:

```
Signal → [MandateGate: "authorized?"] → [RiskGovernor: "safe?"] → Execution
```

**Key principle:** A trade can be safe (risk-approved) but unauthorized (mandate-blocked). The mandate is a HUMAN CONTRACT — no trade exceeds it regardless of risk assessment.

---

## What Was Built

### 1. `src/risk/mandate.py` — Mandate Core

**MandateRules** (Pydantic BaseModel):
- `allowed_symbols`: list of authorized trading pairs (e.g. `["BTC/USDT", "ETH/USDT"]`)
- `max_position_size_pct`: max position as fraction of equity (0.0–1.0)
- `max_daily_trades`: daily trade cap
- `max_leverage`: leverage ceiling
- `allowed_order_types`: permitted order types (market, limit, stop_market, stop_limit)
- `max_notional_per_trade`: notional cap per trade
- `allowed_sides`: permitted sides (restrict to `["buy"]` to disable shorting)

All fields validated by Pydantic: symbol format (`BASE/QUOTE`), enum membership, numeric bounds.

**MandateDecision**:
- `allowed: bool` — whether the order passes
- `reason: str` — human-readable summary
- `violations: list[str]` — specific rule breaches (e.g. `symbol_not_allowed`, `leverage_exceeded`)

**Mandate lifecycle**:
- `commit(user_id)` — human signs, mandate becomes ACTIVE (validates rules first)
- `revoke(user_id)` — deactivate, block all live trades
- `update(user_id, **changes)` — modify rules, auto re-commit, version increments
- `check_order(order)` / `check_signal(...)` — validate against rules

**Persistence**: YAML file (`config/mandate.yaml`), same pattern as `config/risk.yaml`.

**Validation on commit**: Cannot commit with empty symbols, zero position size, or zero daily trades.

### 2. `src/risk/mandate_gate.py` — Pipeline Gate

**MandateGate** wraps Mandate for pipeline integration:

- `check(signal, is_live, ...)` → `RiskDecision` — sync check, returns RiskDecision for pipeline compatibility
- `check_async(signal, ...)` → `RiskDecision` — async wrapper (delegates to thread pool)
- `check_order(order, is_live)` → `MandateDecision` — full order validation
- `get_status()` → dict — monitoring/health check endpoint

**Paper mode exemption**: When `is_live=False`, all mandate checks are bypassed. This allows:
- Backtesting without mandate constraints
- Paper trading with draft mandates
- Strategy development without committing to limits

**Gate behavior**:
- Uncommitted (DRAFT) mandate → blocks ALL live trades
- Revoked mandate → blocks ALL live trades
- Active mandate → enforces rules

### 3. `config/mandate.yaml` — Default Config

Template with all fields documented. Ships empty (`allowed_symbols: []`) — user MUST fill in and commit before live trading is possible. This is intentional: no accidental live trading.

### 4. `tests/unit/risk/test_mandate.py` — 67 Tests

| Test Class | Tests | Coverage |
|---|---|---|
| TestMandateRules | 7 | Pydantic validation (symbols, types, bounds) |
| TestMandateCreation | 3 | Initialization, state, repr |
| TestMandateCheckPass | 5 | Orders that should pass |
| TestMandateCheckFail | 6 | Symbol, type, side, notional violations |
| TestSignalCheck | 7 | Signal-level checks (leverage, daily trades) |
| TestMandateLifecycle | 8 | Commit/revoke/update, validation on commit |
| TestYAMLPersistence | 4 | Save/load, commit persistence, revoke persistence |
| TestPaperModeExemption | 4 | Paper bypasses all checks |
| TestMandateGateLive | 5 | Live mode enforcement |
| TestMandateGateAsync | 3 | Async interface |
| TestMandateGateStatus | 3 | Monitoring endpoint |
| TestMandateGateIntegration | 4 | Pipeline patterns with mock risk guardian |
| TestEdgeCases | 6 | Boundaries (none price, zero limits, reload) |

---

## Architecture Decisions

### 1. Mandate ≠ Risk Engine

The mandate is deliberately separate from the risk engine:
- **Risk Guardian**: "Is this trade safe?" (drawdown, position sizing, stop-loss)
- **Mandate**: "Is this trade authorized?" (symbols, leverage, human commitment)

A trade can be safe but unauthorized (e.g., trading SOL/USDT when mandate only allows BTC/USDT).

### 2. Paper Mode Exemption

Paper mode (`is_live=False`) bypasses mandate entirely. This is critical for:
- Backtesting strategies across symbols not yet in the mandate
- Developing with draft mandates
- Avoiding chicken-and-egg: you need to test before committing

### 3. Pydantic for Validation

MandateRules uses Pydantic BaseModel for:
- Automatic type coercion and validation
- Field constraints (`ge`, `le`)
- Custom validators (symbol format, enum membership)
- Clean JSON/YAML serialization

### 4. Version Tracking

Every `update()` increments the version number. This provides an audit trail: "mandate v3 allowed X, v4 changed to Y."

### 5. HARD Veto Level

Mandate blocks use `VetoLevel.HARD` — the same level as input validation failures. This means mandate violations cannot be overridden (unlike FIRM vetoes which can be). A human must update the mandate to allow new trade types.

---

## Integration Guide

### Pipeline Integration

```python
from src.risk.mandate_gate import MandateGate
from src.risk.governor import RiskGovernor

mandate_gate = MandateGate(config_path="config/mandate.yaml")
risk_governor = RiskGovernor(config_path="config/risk.yaml")

async def evaluate_signal(signal, portfolio, is_live=True):
    # Layer 0: Mandate Gate (BEFORE risk)
    mandate_decision = mandate_gate.check(signal, is_live=is_live)
    if not mandate_decision.approved:
        return mandate_decision

    # Layers 1-7: Risk Guardian
    risk_decision = await risk_governor.check_risk(signal, portfolio)
    return risk_decision
```

### Mandate Setup Flow

```python
from src.risk.mandate import Mandate, MandateRules

mandate = Mandate(config_path="config/mandate.yaml")

# Configure rules
mandate.update(
    user_id="trader-001",
    allowed_symbols=["BTC/USDT", "ETH/USDT"],
    max_position_size_pct=0.15,
    max_daily_trades=10,
    max_leverage=3.0,
)

# Or commit directly with pre-set rules
mandate.commit("trader-001")
```

---

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Empty mandate blocks all live trading | Intentional — forces explicit authorization |
| User forgets to commit | Paper mode works without commitment |
| Mandate too restrictive | `update()` allows quick rule changes |
| YAML corruption | Pydantic validation catches malformed data on load |
| Async pipeline blocking | `check_async()` delegates to thread pool |

---

## Files Changed

| File | Action | Lines |
|---|---|---|
| `src/risk/mandate.py` | CREATED | ~600 |
| `src/risk/mandate_gate.py` | CREATED | ~200 |
| `config/mandate.yaml` | CREATED | ~50 |
| `tests/unit/risk/test_mandate.py` | CREATED | ~570 |
| `src/risk/__init__.py` | MODIFIED | +5 exports, +2 docstring lines |

---

## Test Results

```
67 passed in 0.57s
```

All existing tests continue to pass (no regressions).

---

## Recommendations for Council

1. **Approve**: The mandate system is complete, tested, and follows existing patterns.
2. **Next steps**: Wire MandateGate into the execution pipeline (Phase 3b).
3. **Future**: Consider mandate templates for common strategies (conservative, moderate, aggressive).
4. **Security**: Mandate commit/audit log could be extended to an immutable ledger for compliance.

---

*This review covers the implementation of Phase 3: Mandate-Gated Live Trading as specified in the TSAR architecture.*
