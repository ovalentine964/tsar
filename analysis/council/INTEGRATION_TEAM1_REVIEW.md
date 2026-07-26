# Integration Team 1: Shadow Loop Wiring — Review

**Team:** Integration Team 1 — Shadow Loop Wiring
**Date:** 2026-07-27
**Status:** ✅ COMPLETE
**Gaps Addressed:** G1, G2, G3, G14, G15

---

## Summary

Wired the Shadow Account extraction loop into the existing TSAR architecture. The full flywheel path — `ShadowExtractor → RuleValidator → GenomeMutator → StrategyGeneticist` — is now connected with event-driven communication via CloudEvents.

---

## Changes Made

### 1. G14/G15: New CloudEvents Event Types (`src/comms/events.py`)

Added 6 new event type constants:

```python
TSAR_SHADOW_EXTRACTED  = "tsar.shadow.extracted.v1"
TSAR_RULE_VALIDATED    = "tsar.rule.validated.v1"
TSAR_STRATEGY_PROPOSAL = "tsar.strategy.proposal.v1"
TSAR_MANDATE_COMMITTED = "tsar.mandate.committed.v1"
TSAR_MANDATE_REVOKED   = "tsar.mandate.revoked.v1"
TSAR_FACTOR_BENCHMARK  = "tsar.factor.benchmark.v1"
```

**Rationale:** Constants prevent string drift across agents. All publishers and consumers now reference the same constant.

### 2. G2: OHLCVProvider Adapter (`src/knowledge/ohlcv_adapter.py`) — NEW FILE

Created `ExchangeGatewayOHLCVAdapter` that bridges the interface layer to the knowledge layer:

- **Wraps:** `ExchangeGateway.get_ohlcv(symbol, Timeframe, limit)`
- **Provides:** `get_candles(symbol, timeframe_str, limit, since) → list[OHLCVCandle]`
- **Handles:** String-to-`Timeframe` enum mapping for all 8 timeframes (1m through 1w)
- **Converts:** `OHLCV` dataclass → `OHLCVCandle` dataclass (timestamp ISO formatting)

The adapter satisfies the `OHLCVProvider` Protocol used by `RuleValidator`.

### 3. G1: ShadowExtractor Orchestrator Integration (`src/agents/orchestrator.py`)

**New fields in `__init__`:**
- `self._shadow_extractor` — ShadowExtractor instance
- `self._rule_validator` — RuleValidator instance
- `self._genome_mutator` — GenomeMutator instance
- `self._last_shadow_extraction` — monotonic timestamp for interval tracking

**New method `_initialize_shadow_loop()`:**
- Called at end of `on_initialize()`
- Reads `shadow_extractor` config section
- Lazily imports and creates: `TradeMemory`, `ShadowExtractor`, `ExchangeGatewayOHLCVAdapter`, `RuleValidator`, `StrategyGenomes`, `GenomeMutator`
- Gracefully degrades to no-op if config says `enabled: false` or if initialization fails

**Updated `run_cycle()`:**
- After health monitoring, checks if shadow extraction interval has elapsed
- Default interval: 24 hours (configurable via `shadow_extractor.cycle_interval_hours`)
- Calls `_run_shadow_extraction()` when due

**New method `_run_shadow_extraction()`:**
Full pipeline execution:
1. **Extract:** `ShadowExtractor.extract()` → `ExtractionResult` with `TradingRule` objects
2. **Publish:** `TSAR_SHADOW_EXTRACTED` event on `commands` stream
3. **Validate:** `RuleValidator.validate_batch()` → `ValidatedRule` objects
4. **Publish:** `TSAR_RULE_VALIDATED` events for each validated rule
5. **Mutate:** `GenomeMutator.propose_mutations()` → `MutationProposal` objects
6. **Publish:** `TSAR_STRATEGY_PROPOSAL` events on `strategy_proposals` stream

All steps are wrapped in try/except — failures are logged, never crash the orchestrator.

### 4. G3: GenomeMutator → StrategyGeneticist Connection (`src/agents/strategy_geneticist.py`)

The StrategyGeneticist was already substantially implemented (by another integration team) with:
- `SUBSCRIBE_STREAMS = ["analytics", "regime", "fills", "strategy_proposals"]`
- `handle_event()` routing for `strategy_proposals` stream
- `_evaluate_proposal()` method with confidence gating
- Full backtest/walk-forward/Monte Carlo evaluation pipeline
- Factor benchmarking (G9)

**Key fix applied:** The Orchestrator was publishing `TSAR_STRATEGY_PROPOSAL` events to the `commands` stream, but the StrategyGeneticist subscribes to `strategy_proposals`. Fixed the publish target to `stream="strategy_proposals"` so events actually reach the consumer.

---

## Event Flow (After Wiring)

```
Orchestrator.run_cycle()
  │
  ├─ _run_shadow_extraction()
  │   │
  │   ├─ ShadowExtractor.extract()
  │   │   └─ reads TradeMemory → LLM → TradingRule[]
  │   │
  │   ├─ publish TSAR_SHADOW_EXTRACTED → commands stream
  │   │
  │   ├─ RuleValidator.validate_batch()
  │   │   └─ ExchangeGatewayOHLCVAdapter.get_candles() → OHLCVCandle[]
  │   │   └─ replay rules → ValidatedRule[]
  │   │
  │   ├─ publish TSAR_RULE_VALIDATED (×N) → commands stream
  │   │
  │   ├─ GenomeMutator.propose_mutations()
  │   │   └─ filters by quality thresholds → MutationProposal[]
  │   │
  │   └─ publish TSAR_STRATEGY_PROPOSAL (×N) → strategy_proposals stream
  │
  └─ StrategyGeneticist.handle_event(strategy_proposals)
      │
      └─ _evaluate_proposal()
          ├─ confidence gate (≥0.5)
          ├─ optional: full backtest + walk-forward + Monte Carlo
          ├─ accept → update_genome() + publish tsar.strategy.mutated.v1
          └─ reject → log
```

---

## Tests

### `tests/unit/agents/test_orchestrator_shadow.py` — 11 tests ✅

| Test | What it verifies |
|---|---|
| `test_shadow_loop_disabled` | No components when `enabled=False` |
| `test_shadow_loop_enabled` | All 3 components created when `enabled=True` |
| `test_shadow_loop_init_failure_graceful` | Degrades to None on init failure |
| `test_run_cycle_triggers_shadow_extraction` | Periodic trigger when interval elapsed |
| `test_run_cycle_skips_shadow_when_not_elapsed` | No trigger before interval |
| `test_run_cycle_skips_shadow_when_no_extractor` | No-op when extractor is None |
| `test_run_shadow_extraction_full_pipeline` | Full extract→validate→mutate→publish flow |
| `test_run_shadow_extraction_no_rules` | Early exit when no rules extracted |
| `test_run_shadow_extraction_no_passed_rules` | Skip mutation when no rules pass validation |
| `test_run_shadow_extraction_handles_exceptions` | Exceptions caught, not raised |
| `test_proposals_published_to_strategy_proposals_stream` | Correct stream targeting |

### `tests/unit/knowledge/test_ohlcv_adapter.py` — 21 tests ✅

| Category | Tests |
|---|---|
| Timeframe mapping | 12 tests: coverage, types, all 8 specific mappings |
| Basic adapter | 3 tests: return type, param passing, defaults |
| OHLCV→OHLCVCandle conversion | 4 tests: value preservation, timestamp ISO, empty list |
| Error handling | 3 tests: invalid timeframe, supported list, gateway errors |
| Scale | 2 tests: 500-candle batch, all timeframes |

---

## Config Requirements

The shadow loop activates when `shadow_extractor.enabled: true` in `config/tsar.yaml`:

```yaml
shadow_extractor:
  enabled: true
  cycle_interval_hours: 24
  min_trades: 10
  min_win_rate: 0.55
  lookback_days: 90
  timeframe: "1h"
  lookback_candles: 500
  min_confidence: 0.6
  min_sharpe: 0.5
  max_proposals: 5
  allow_new_genomes: false
```

---

## Remaining Gaps (Not In Scope)

| Gap | Status | Notes |
|---|---|---|
| G4 | ❌ Not in scope | MandateGate → RiskGuardian wiring (separate team) |
| G5 | ❌ Not in scope | FactorLibrary → SignalScout wiring |
| G6–G9 | ✅ Already done | StrategyGeneticist already has backtest/WF/MC/factor pipeline |
| G10 | ❌ Not in scope | `config/mandate.yaml` creation |
| G11–G13 | ❌ Not in scope | DB migrations, FTS verification |

---

## Risk Assessment

- **No circular imports** — all new imports are lazy (inside methods)
- **No breaking changes** — all modifications are additive
- **Graceful degradation** — shadow loop is a no-op when disabled or on failure
- **Stream routing verified** — proposals flow to `strategy_proposals`, not `commands`
- **All 32 new tests pass** (11 orchestrator + 21 adapter)
