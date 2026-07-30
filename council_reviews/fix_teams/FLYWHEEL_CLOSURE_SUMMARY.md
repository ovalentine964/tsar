# Flywheel Closure Team — Summary of Changes

**Team**: Flywheel Closure  
**Date**: 2026-07-30  
**Objective**: Wire up the TSAR flywheel so it actually closes: TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE

---

## Issues Addressed

### C-005: Flywheel Not Self-Activating ✅

**File created**: `src/agents/flywheel_orchestrator.py`

**What it does**:
- New `FlywheelOrchestrator` agent that auto-triggers after every trade completion
- Monitors trade events via the EventBus (`tsar.trade.executed`, `tsar.trade.recorded`)
- Runs the full pipeline every 10 trades (configurable via `BATCH_SIZE`) with a 5-minute cooldown
- Pipeline: **ShadowExtractor → RuleValidator → GenomeMutator → StrategyGeneticist**
- Each step is independently fault-tolerant — failures logged but don't crash the loop
- Publishes lifecycle events (`flywheel.cycle_started`, `flywheel.cycle_complete`, `flywheel.cycle_error`) for observability
- `trigger_flywheel()` method available for manual/debug runs
- Health metrics: `flywheel_runs`, `total_rules_extracted`, `total_rules_validated`, `total_mutations_proposed`, `total_mutations_applied`

**How it activates**:
1. Orchestrator receives `tsar.trade.executed.v1` event
2. Publishes to EventBus → FlywheelOrchestrator receives via `_on_trade_executed`
3. When batch threshold reached + cooldown elapsed → `_run_flywheel()` fires as background task
4. Full pipeline runs automatically — no human in the loop

---

### C-006: TradePhilosopher Unstructured Output ✅

**File modified**: `src/agents/trade_philosopher.py`

**What changed**:
- Added `TRADE_REFLECTION_SCHEMA` — JSON Schema definition enforcing structured output
- Required fields: `trade_id`, `outcome` (win|loss|breakeven), `lesson` (min 10 chars), `confidence` (0-1), `pattern_tags` (array, min 1)
- Optional fields: `what_went_right`, `what_went_wrong`, `error_category` (timing|sizing|regime|execution|none), `actionable_change`
- Added `REFLECTION_JSON_INSTRUCTIONS` — injected into every LLM prompt to enforce schema compliance
- Added `_validate_reflection()` — normalizes raw LLM output, infers missing fields, clamps values
- LLM calls now use `json_mode=True` with `temperature=0.3` for deterministic structured output
- JSON extraction handles both raw JSON and markdown code blocks
- Fallback reflections are schema-compliant (never returns unstructured text)
- `get_schema()` static method exposes the schema for external consumers

---

### C-007: Flywheel EXTRACT→ADAPT Gap ✅

**Files modified**: `src/agents/orchestrator.py`, `src/knowledge/genome_mutator.py`

**What changed in orchestrator.py**:
- `_load_agent_registry()` now includes `StrategyGeneticist` and `FlywheelOrchestrator`
- Default `enabled_agents` list now includes both new agents
- `FlywheelOrchestrator` reference tracked as `self._flywheel_orchestrator`
- EventBus wired to forward trade events to the FlywheelOrchestrator via `_forward_to_flywheel()`
- Removed the old inline shadow extraction code from `handle_event` — the FlywheelOrchestrator now owns this responsibility
- Clean separation: Orchestrator routes events, FlywheelOrchestrator runs the pipeline

**What changed in genome_mutator.py**:
- `_propose_for_rule()` now detects `action="avoid"` rules (from losing trades)
- New `_apply_loss_weighted_lesson()` method:
  - Computes loss weight from average loss severity (>5% → 1.5x, >3% → 1.3x, >1% → 1.15x)
  - Boosts proposal confidence for loss-derived rules
  - Records lessons in genome via `StrategyGenomes.apply_shadow_lesson()`
- Mutations now flow: ShadowExtractor → RuleValidator → GenomeMutator → StrategyGeneticist → genome update

---

### H-001: Shadow Account Learning Loop Unclear ✅

**Files modified**: `src/knowledge/shadow_extractor.py`, `src/knowledge/strategy_genomes.py`

**What changed in shadow_extractor.py**:
- New `_extract_loss_lessons()` method: extracts high-priority rules from losing trades
- Loss severity determines confidence: >5% loss → 0.9, >3% → 0.8, >1% → 0.7, ≤1% → 0.6
- New `_infer_loss_conditions()` method: analyzes common patterns in losing trades
  - Regime patterns (60%+ losers in same regime → flag it)
  - Signal score patterns (low scores → flag it)
  - Volatility regime patterns
  - Holding period patterns (held too long → flag it)
- Creates `action="avoid"` rules that represent anti-patterns to avoid
- Loss lessons appended to extraction results alongside winner-derived rules

**What changed in strategy_genomes.py**:
- New `apply_shadow_lesson()` method: wires lessons directly into genome mutation pipeline
  - `loss_weight` multiplier: loss-derived lessons get heavier weight (default 1.0, loss lessons up to 1.5x)
  - Effective confidence = base_confidence × loss_weight (clamped to 1.0)
  - Minimum effective confidence threshold: 0.4 (skips weak lessons)
- New `_build_tighter_exit_rules()` method: generates tighter stop-loss rules from loss patterns
  - >5% loss → 2% tight stop, >3% → 3% tight stop, >1% → 5% tight stop
  - Time-based exits for trades held too long
- Loss lessons produce `mutation_type="risk_tightening"` mutations (vs `"rule_addition"` for winners)

---

## Files Changed Summary

| File | Action | Issue |
|------|--------|-------|
| `src/agents/flywheel_orchestrator.py` | **Created** | C-005 |
| `src/agents/trade_philosopher.py` | Modified | C-006 |
| `src/agents/orchestrator.py` | Modified | C-007 |
| `src/knowledge/genome_mutator.py` | Modified | C-007, H-001 |
| `src/knowledge/shadow_extractor.py` | Modified | H-001 |
| `src/knowledge/strategy_genomes.py` | Modified | H-001 |

## The Flywheel Now Closes

```
TRADE (ExecutionSniper executes)
  ↓
OBSERVE (Orchestrator records trade, forwards to EventBus)
  ↓  [FlywheelOrchestrator monitors EventBus]
REFLECT (TradePhilosopher generates structured JSON reflections)
  ↓
EXTRACT (ShadowExtractor extracts rules from winners + loss-weighted lessons from losers)
  ↓
VALIDATE (RuleValidator backtests rules against OHLCV data)
  ↓
ADAPT (GenomeMutator proposes mutations, loss lessons get boosted confidence)
  ↓
BETTER TRADE (StrategyGeneticist evaluates proposals, applies to genomes)
  ↓  [cycle repeats automatically every 10 trades]
```

The flywheel is now **automatic, not manual**. It activates after every batch of trades, learns from both wins and losses (with losses weighted more heavily), and feeds improvements back into the strategy genome. Loss-derived lessons produce `risk_tightening` mutations that tighten stop-losses and add time-based exits — directly addressing the anti-patterns that caused losses.
