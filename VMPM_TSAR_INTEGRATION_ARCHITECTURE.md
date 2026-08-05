# VMPM × TSAR Integration Architecture
## The Super-Strategy: Combining Institutional-Grade VMPM with TSAR's Adaptive Intelligence

**Date:** 2026-08-05
**Status:** IMPLEMENTATION COMPLETE

---

## 1. COMPLETE ARCHITECTURE DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TSAR SUPER STRATEGY ARCHITECTURE                         │
│                    VMPM + Momentum + MeanReversion + Genetic Evolution      │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        DATA INGESTION LAYER                          │  │
│  │                                                                       │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐             │  │
│  │  │ Exchange │  │ Economic │  │ On-Chain │  │  News    │             │  │
│  │  │ OHLCV    │  │ Calendar │  │  Data    │  │  Feed    │             │  │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘             │  │
│  │       └──────────────┴──────────────┴──────────────┘                  │  │
│  └───────────────────────────────┬───────────────────────────────────────┘  │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                     ANALYSIS LAYER (Pre-Trade)                       │  │
│  │                                                                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │  │
│  │  │RegimeDetector│  │MarketCartog- │  │  Signal      │               │  │
│  │  │   (HMM)      │  │   rapher     │  │  Scout       │               │  │
│  │  │              │  │              │  │              │               │  │
│  │  │ STRONG_TREND │  │ S/R Levels   │  │ Stat. Edges  │               │  │
│  │  │ RANGING      │  │ Order Blocks │  │ Factor IC/IR │               │  │
│  │  │ HIGH_VOL     │  │ FVG Mapping  │  │              │               │  │
│  │  │ UNCERTAIN    │  │              │  │              │               │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │  │
│  │         │                 │                  │                        │  │
│  │         └─────────────────┼──────────────────┘                        │  │
│  │                           ▼                                           │  │
│  │  ┌────────────────────────────────────────────────────────────────┐  │  │
│  │  │              VMPM STRATEGY ROUTER (New Agent)                  │  │  │
│  │  │                                                                │  │  │
│  │  │  ┌─────────────────────────────────────────────────────────┐  │  │  │
│  │  │  │              REGIME → ROUTING TABLE                     │  │  │  │
│  │  │  │                                                         │  │  │  │
│  │  │  │  STRONG_TREND ──→ VMPM Trend (70%) + Momentum (30%)    │  │  │  │
│  │  │  │  RANGING      ──→ VMPM Reversion (60%) + MeanRev (40%) │  │  │  │
│  │  │  │  HIGH_VOL     ──→ VMPM (50%) + Momentum (50%) [½ size] │  │  │  │
│  │  │  │  UNCERTAIN    ──→ SKIP (no trading)                     │  │  │  │
│  │  │  └─────────────────────────┬───────────────────────────────┘  │  │  │
│  │  │                            ▼                                  │  │  │
│  │  │  ┌─────────────────────────────────────────────────────────┐  │  │  │
│  │  │  │           PARALLEL STRATEGY EXECUTION                   │  │  │  │
│  │  │  │                                                         │  │  │  │
│  │  │  │  ┌──────────────────────┐  ┌──────────────────────┐    │  │  │  │
│  │  │  │  │   VMPM PIPELINE      │  │   FALLBACK STRATEGY  │    │  │  │  │
│  │  │  │  │                      │  │                      │    │  │  │  │
│  │  │  │  │  1. News Gate        │  │  ┌────────────────┐  │    │  │  │  │
│  │  │  │  │  2. Trend Gate ──────┼──┼─→│ MomentumStrat  │  │    │  │  │  │
│  │  │  │  │  3. S/R Gate         │  │  │ EMA + MACD +   │  │    │  │  │  │
│  │  │  │  │  4. Retest Gate      │  │  │ ADX + Funding  │  │    │  │  │  │
│  │  │  │  │  5. RSI Gate ────────┼──┼─→│ OR             │  │    │  │  │  │
│  │  │  │  │  6. Candle Gate      │  │  │ MeanReversion  │  │    │  │  │  │
│  │  │  │  │  7. Execute Gate     │  │  │ RSI + S/R +    │  │    │  │  │  │
│  │  │  │  │                      │  │  │ Volume         │  │    │  │  │  │
│  │  │  │  │  Score: 0-100        │  │  └───────┬────────┘  │    │  │  │  │
│  │  │  │  └──────────┬───────────┘  └──────────┼───────────┘    │  │  │  │
│  │  │  │             │                         │                │  │  │  │
│  │  │  │             └────────────┬────────────┘                │  │  │  │
│  │  │  │                          ▼                             │  │  │  │
│  │  │  │  ┌──────────────────────────────────────────────────┐  │  │  │  │
│  │  │  │  │         REGIME-WEIGHTED SIGNAL BLENDER           │  │  │  │  │
│  │  │  │  │                                                  │  │  │  │  │
│  │  │  │  │  Combined = VMPM_score × W_vmpm                 │  │  │  │  │
│  │  │  │  │           + Fallback_score × W_fallback          │  │  │  │  │
│  │  │  │  │                                                  │  │  │  │  │
│  │  │  │  │  If directions conflict → SKIP                   │  │  │  │  │
│  │  │  │  │  If combined < threshold → SKIP                  │  │  │  │  │
│  │  │  │  └──────────────────────┬───────────────────────────┘  │  │  │  │
│  │  │  └─────────────────────────┼──────────────────────────────┘  │  │  │
│  │  └────────────────────────────┼──────────────────────────────────┘  │  │
│  └───────────────────────────────┼──────────────────────────────────────┘  │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        RISK LAYER                                     │  │
│  │                                                                       │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │                     RISK GUARDIAN                                 │ │  │
│  │  │                                                                  │ │  │
│  │  │  ✓ Kill switch not active         ✓ Stop-loss set & reasonable  │ │  │
│  │  │  ✓ Circuit breaker not RED        ✓ R:R ≥ 2.5:1 (VMPM min)     │ │  │
│  │  │  ✓ Position size ≤ 15% equity     ✓ Symbol cooldown clear       │ │  │
│  │  │  ✓ Daily P&L > -2%                ✓ No conflicting positions    │ │  │
│  │  │  ✓ Open positions < max           ✓ Signal score ≥ threshold    │ │  │
│  │  │                                                                  │ │  │
│  │  │  VETO LEVELS: NONE → SOFT → FIRM → HARD → NUCLEAR              │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────┬───────────────────────────────────────┘  │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      EXECUTION LAYER                                  │  │
│  │                                                                       │  │
│  │  ┌──────────────┐  ┌──────────────┐                                  │  │
│  │  │  Execution   │  │  Execution   │                                  │  │
│  │  │  Sniper      │  │  Tracker     │                                  │  │
│  │  │  (Entry)     │  │  (Monitoring)│                                  │  │
│  │  └──────┬───────┘  └──────┬───────┘                                  │  │
│  └─────────┼─────────────────┼───────────────────────────────────────────┘  │
│            └────────┬────────┘                                              │
│                     ▼                                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    FLYWHEEL (Learning Loop)                           │  │
│  │                                                                       │  │
│  │  Trade → Observe → Reflect → Extract → Adapt → Better Trade          │  │
│  │                                                                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │  │
│  │  │    Trade      │  │   Shadow     │  │   Strategy   │               │  │
│  │  │  Philosopher  │──│  Extractor   │──│  Geneticist  │               │  │
│  │  │  (Reflect)    │  │  (Patterns)  │  │  (Evolve)    │               │  │
│  │  └──────────────┘  └──────────────┘  └──────┬───────┘               │  │
│  │                                              │                        │  │
│  │         ┌────────────────────────────────────┘                        │  │
│  │         ▼                                                             │  │
│  │  ┌──────────────────────────────────────────────────────────────┐    │  │
│  │  │           GENOME EVOLUTION (VMPM + Router params)            │    │  │
│  │  │                                                              │    │  │
│  │  │  Evolves: MA periods, RSI thresholds, S/R proximity,        │    │  │
│  │  │           R:R ratios, session overlap mult, regime weights, │    │  │
│  │  │           confluence score threshold, position sizing        │    │  │
│  │  └──────────────────────────────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. INTEGRATION DESIGN: How VMPM Connects to Each TSAR Strategy

### 2.1 VMPM + MomentumStrategy (Trending Markets)

**Concept:** VMPM provides *where* to trade (directional bias + S/R zones). Momentum provides *statistical confirmation* (EMA crossover + ADX strength).

```
VMPM says: "Price at support in uptrend — BUY zone at 1.0850"
Momentum says: "EMA(21) > EMA(55), ADX=32, MACD bullish — CONFIRMED"
Combined: High-probability trend continuation at institutional level
```

**Routing:** STRONG_TREND_UP/DOWN regime → VMPM 70% + Momentum 30%

**Why it works:**
- VMPM's multi-timeframe trend analysis (D1/H4/H1) with 50/200 MA aligns with Momentum's EMA(21)/EMA(55) crossover — they measure the same thing at different scales
- VMPM's order block detection identifies *where* institutions placed orders. Momentum's volume confirmation validates *that* institutions are active
- VMPM's session awareness adds timing intelligence that Momentum lacks

**Conflict resolution:**
- If VMPM says BUY but Momentum says SELL → SKIP (conflicting signals = danger)
- If both agree → Weighted blend: `combined = vmpm_score × 0.7 + momentum_score × 0.3`

### 2.2 VMPM + MeanReversionStrategy (Ranging Markets)

**Concept:** VMPM's order blocks are *institutional mean reversion zones*. MeanReversion's RSI extremes confirm the reversion setup.

```
VMPM says: "Bearish order block at resistance 1.0920 — SELL zone"
MeanReversion says: "RSI=72 at resistance proximity — OVERBOUGHT"
Combined: Institutional supply zone + statistical oversold confirmation
```

**Routing:** RANGING regime → VMPM 60% + MeanReversion 40%

**Why it works:**
- VMPM's order blocks *are* the mean reversion zones — they represent where institutions placed large orders and price will likely revert
- MeanReversion's RSI(14) < 30 / > 70 provides the *timing* signal within VMPM's zone
- VMPM's Asian session high/low mapping identifies the daily range that MeanReversion trades against

**Conflict resolution:**
- VMPM identifies the zone, MeanReversion confirms the timing — they're complementary, not competing
- If VMPM says "at support" but RSI is 60 (not oversold) → Lower score, still valid if other VMPM layers pass

### 2.3 StrategyGeneticist → VMPM Parameter Evolution

**What gets evolved (VMPM genome parameters):**

| Parameter | Default | Range | Impact |
|-----------|---------|-------|--------|
| `ma_fast_period` | 50 | 20–100 | Trend detection sensitivity |
| `ma_slow_period` | 200 | 100–300 | Long-term trend filter |
| `rsi_oversold` | 30 | 20–40 | Buy signal threshold |
| `rsi_overbought` | 70 | 60–80 | Sell signal threshold |
| `sr_proximity_pct` | 0.3% | 0.1–1.0% | Zone width for S/R |
| `min_rr_ratio` | 2.5 | 2.0–4.0 | Minimum R:R for execution |
| `min_confluence_score` | 55 | 40–75 | Pipeline pass threshold |
| `session_overlap_mult` | 1.5 | 1.0–2.0 | Overlap session bonus |
| `stop_loss_atr_mult` | 1.5 | 1.0–3.0 | Stop loss width |
| `take_profit_atr_mult` | 4.0 | 2.5–6.0 | Take profit target |

**What gets evolved (Router parameters):**

| Parameter | Default | Range | Impact |
|-----------|---------|-------|--------|
| `routing_strong_trend_up_vmpm_weight` | 0.7 | 0.4–1.0 | VMPM weight in uptrends |
| `routing_ranging_vmpm_weight` | 0.6 | 0.3–0.9 | VMPM weight in ranges |
| `routing_high_volatility_sizing_mult` | 0.5 | 0.2–0.8 | Sizing in volatile markets |

**Flywheel cycle:**
```
Trade executed → TradePhilosopher reflects → ShadowExtractor finds patterns
→ RuleValidator confirms → StrategyGeneticist mutates VMPM genome
→ BacktestEngine validates → WalkForward checks overfitting
→ MonteCarlo confidence intervals → Apply to live VMPM
```

### 2.4 RegimeDetector → VMPM Mode Switching

```
┌─────────────────┬──────────────────┬─────────────────┬──────────────────┐
│    REGIME       │   VMPM MODE      │  FALLBACK       │  SIZING          │
├─────────────────┼──────────────────┼─────────────────┼──────────────────┤
│ STRONG_TREND_UP │ VMPM Trend (70%) │ Momentum (30%)  │ 1.0x (normal)    │
│ STRONG_TREND_DN │ VMPM Trend (70%) │ Momentum (30%)  │ 1.0x (normal)    │
│ RANGING         │ VMPM Reversion   │ MeanRev (40%)   │ 0.8x (reduced)   │
│                 │ (60%)            │                 │                  │
│ HIGH_VOLATILITY │ VMPM (50%)       │ Momentum (50%)  │ 0.5x (half)      │
│ UNCERTAIN       │ SKIP             │ SKIP            │ 0x (no trade)    │
└─────────────────┴──────────────────┴─────────────────┴──────────────────┘
```

### 2.5 Signal Scoring System

**VMPM confluence score (0–100):**
```
Score = Σ (layer_score × layer_weight) × 100

Layer weights:
  News Gate:        5%  (binary — pass/fail gate)
  Trend Gate:      25%  (multi-timeframe alignment)
  S/R Gate:        20%  (proximity to institutional level)
  Retest Gate:     15%  (confirmation of zone validity)
  RSI Gate:        15%  (momentum confirmation)
  Candle Gate:     10%  (price action pattern)
  Execute Gate:    10%  (R:R feasibility)
```

**Combined signal score (regime-weighted blend):**
```
If regime = STRONG_TREND:
  combined = vmpm_score × 0.7 + momentum_score × 0.3

If regime = RANGING:
  combined = vmpm_score × 0.6 + mean_reversion_score × 0.4

If regime = HIGH_VOLATILITY:
  combined = vmpm_score × 0.5 + momentum_score × 0.5
  position_size × 0.5

Threshold for execution: combined ≥ 0.55
```

---

## 3. DATA FLOW: Signal Through the System

```
Step 1: MarketCartographer fetches OHLCV (D1, H4, H1) + Asian session data
        ↓
Step 2: RegimeDetector classifies market regime (HMM)
        ↓
Step 3: VMPMStrategyRouter receives regime + market data
        ↓
Step 4: Router determines routing (e.g., VMPM 70% + Momentum 30%)
        ↓
Step 5a: VMPM runs 7-layer pipeline:
         News → Trend → S/R → Retest → RSI → Candle → Execute
         Output: VMPM signal (score 0-100, direction, S/R levels)
        ↓
Step 5b: Momentum/MeanReversion runs (parallel):
         Output: Fallback signal (score 0-1, direction, levels)
        ↓
Step 6: Router blends signals with regime weights
         If directions conflict → SKIP
         If combined < threshold → SKIP
        ↓
Step 7: Blended signal → RiskGuardian
         All 10 deterministic checks must pass
         VETO power (NONE/SOFT/FIRM/HARD/NUCLEAR)
        ↓
Step 8: ExecutionSniper places order
        ↓
Step 9: ExecutionTracker monitors position
        ↓
Step 10: TradePhilosopher reflects on outcome
         ↓
Step 11: FlywheelOrchestrator triggers:
         ShadowExtractor → RuleValidator → StrategyGeneticist
         ↓
Step 12: StrategyGeneticist evolves VMPM genome + Router parameters
         Backtest → WalkForward → MonteCarlo → Apply
         ↓
         CYCLE REPEATS (system gets smarter every trade)
```

---

## 4. FILE MANIFEST

### New Files Created:

| File | Purpose |
|------|---------|
| `src/strategy/vmpm/entry_pipeline.py` | 7-layer confluence pipeline (News→Trend→S/R→Retest→RSI→Candle→Execute) |
| `src/strategy/vmpm/strategy.py` | VMPMStrategy class extending BaseStrategy |
| `src/agents/vmpm_strategy_router.py` | Regime-aware strategy router agent |
| `config/strategies/vmpm.yaml` | Updated with router parameters |

### Existing Files (already implemented):

| File | Purpose |
|------|---------|
| `src/strategy/vmpm/session_manager.py` | Session awareness (Sydney/Tokyo/London/NY) |
| `src/strategy/vmpm/fundamental_analyzer.py` | Economic calendar + bias scoring |
| `src/strategy/vmpm/trend_detector.py` | Multi-timeframe trend (D1/H4/H1, 50/200 MA, swing structure) |
| `src/strategy/vmpm/level_mapper.py` | S/R mapping (Asian H/L, Daily/Weekly/Monthly/Yearly, Order Blocks) |

---

## 5. HOW TO WIRE IT IN

### 5.1 Register VMPMStrategy in the Orchestrator

```python
# In src/agents/orchestrator.py → _load_agent_registry()
from src.strategy.vmpm.strategy import VMPMStrategy
from src.agents.vmpm_strategy_router import VMPMStrategyRouter

# Add to AGENT_REGISTRY
self.AGENT_REGISTRY["vmpm_strategy_router"] = VMPMStrategyRouter
```

### 5.2 Register VMPM in the StrategyRegistry

```python
# In SignalScout or wherever StrategyRegistry is initialized
from src.strategy.vmpm.strategy import VMPMStrategy
from src.strategy.genome import StrategyGenome

genome = StrategyGenome.from_yaml("config/strategies/vmpm.yaml")
vmpm = VMPMStrategy(genome=genome)
registry.register(vmpm)
```

### 5.3 Connect VMPMStrategyRouter to the Pipeline

```
Current:  SignalScout → RiskGuardian → ExecutionSniper
Updated:  SignalScout → VMPMStrategyRouter → RiskGuardian → ExecutionSniper
```

The router sits between signal generation and risk evaluation, adding regime-aware strategy blending.

### 5.4 Connect to Flywheel for Genome Evolution

```python
# In FlywheelOrchestrator → on_initialize()
# Add VMPM genome to the evolution pool
from src.strategy.genome import StrategyGenome
vmpm_genome = StrategyGenome.from_yaml("config/strategies/vmpm.yaml")
self._evolution_pool.append(vmpm_genome)
```

---

## 6. KEY DESIGN DECISIONS

1. **VMPM is a BaseStrategy, not a BaseAgent** — It plugs into the existing StrategyRegistry alongside MomentumStrategy and MeanReversionStrategy. This keeps the architecture clean.

2. **VMPMStrategyRouter IS a BaseAgent** — It subscribes to regime events and publishes signals, fitting TSAR's event-driven architecture.

3. **The router's routing table is genome-evolvable** — The StrategyGeneticist can evolve not just VMPM's parameters, but *how much* VMPM is weighted vs other strategies in each regime.

4. **VMPM provides the "where", others provide the "confirmation"** — VMPM's institutional S/R mapping (order blocks, Asian levels) is unique. Momentum/MeanReversion add statistical confirmation. The combination is stronger than either alone.

5. **Regime detection is the switchboard** — The HMM-based RegimeDetector determines which strategy combination to use. No human intervention needed.

6. **The flywheel closes the loop** — Every trade outcome feeds back into genome evolution. VMPM literally gets smarter from every trade.
