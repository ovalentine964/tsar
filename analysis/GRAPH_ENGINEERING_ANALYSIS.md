# Graph Engineering Paper — TSAR Alignment Analysis

**Source:** "Graph Engineering: From Karpathy's Loop to Anthropic's Agent Infrastructure" (2026)
**Authors:** Independent synthesis of Karpathy (autoresearch, AgentHub) + Anthropic (Dynamic Workflows, Knowledge Graph Cookbook)

---

## Key Concepts That Apply to TSAR

### 1. The Ratchet Loop = TSAR's Flywheel

Karpathy's autoresearch loop:
```
LOOP FOREVER:
  1. Read current state
  2. Propose one motivated change
  3. Apply change
  4. Evaluate
  5. If improved: keep. Else: revert.
  6. Record result and continue without asking human.
```

**TSAR's flywheel IS this loop:**
```
TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE
```

The paper calls it a "ratchet" — only improvements stick. TSAR's Strategy Geneticist is the ratchet: propose mutation → backtest → if better, keep → if worse, revert.

**Key insight:** "Four conditions make the loop work: (1) output is verifiable, (2) action is reversible, (3) horizon is short, (4) environment is bounded."

TSAR satisfies all four:
- ✅ Verifiable: trade outcomes are measurable (Sharpe, win rate, drawdown)
- ✅ Reversible: genome mutations can be reverted
- ✅ Short horizon: 5-minute scan cycles
- ✅ Bounded: risk engine constrains the action space

### 2. program.md = TSAR's Strategy YAML

> "program.md is programming the program. In Software 3.0, context and prompts become a programmable interface."

**TSAR's equivalent:** `config/strategies/mean_reversion.yaml` and `config/strategies/momentum.yaml` are program.md — they define the mutable state (strategy parameters), the protected state (risk limits), the metric (Sharpe ratio), and the rules (entry/exit conditions).

### 3. Knowledge Graph as Shared Memory

> "The agent forgets. The graph does not."

**TSAR's 5 knowledge stores ARE a knowledge graph:**
- TradeMemory → nodes (trades) + edges (linked by symbol, strategy, regime)
- PatternLibrary → nodes (patterns) + edges (linked by success rate, conditions)
- LessonArchive → nodes (lessons) + edges (linked by trade_ids, categories)
- StrategyGenomes → nodes (genomes) + edges (parent/mutation lineage)
- RegimeState → nodes (regimes) + edges (transition probabilities)

**What's missing:** Provenance tracking. Every claim in TSAR's knowledge stores should have: source_trade_id, confidence, evaluation_rationale, and version history.

### 4. The DAG = Strategy Genome Evolution

> "The commit DAG answers: What changed? Which experiment is the parent? Which agent produced the change?"

**TSAR's Strategy Geneticist should use a DAG:**
- Each genome mutation is a commit node
- Parent links track lineage (which genome spawned this mutation)
- Metadata: backtest Sharpe, win rate, sample size, keep/revert decision
- `children(hash)` → what mutations were tried on this genome?
- `leaves()` → unexplored genome frontiers
- `lineage(hash)` → ancestry path to the original strategy

### 5. Five Workflow Patterns → TSAR's 10 Agents

| Pattern | TSAR Agent | How |
|---------|-----------|-----|
| **Chain** | Signal → Risk → Execute | Fixed sequence, each produces artifact for next |
| **Routing** | Regime Detector | Classifies market regime, routes to appropriate strategy |
| **Parallelization** | Signal Scout (multi-symbol) | Scan BTC, ETH, SOL simultaneously |
| **Orchestrator-Workers** | Orchestrator | Coordinates all 10 agents |
| **Evaluator-Optimizer** | Trade Philosopher + Strategy Geneticist | One reflects, one optimizes |

### 6. From Loop to Swarm (Staged Build Path)

The paper's staged build path maps to TSAR's phases:

| Stage | Timeline | TSAR Phase |
|-------|----------|------------|
| Reflective loop | Day 1 | ✅ Done (Trade Philosopher) |
| Tool use | Day 2 | ✅ Done (35 tools) |
| Planning | Week 1 | ⚠️ Partial (Orchestrator pipeline) |
| Multi-agent | Week 2 | ✅ Done (10 agents) |
| Persistent graph | Month 1 | ⚠️ Partial (5 stores, no FTS5 yet) |
| Swarm workflow | Month 2 | 🔜 Future (research swarm) |

### 7. Production Checklist → TSAR Audit

| Element | Question | TSAR Status |
|---------|----------|-------------|
| Objective | Is the task testable? | ✅ Trade outcomes are measurable |
| Metric | Distinguish improvement from activity? | ⚠️ Need better genome fitness metrics |
| Reversibility | Can updates be undone? | ✅ Kill switch, genome revert |
| Tool schema | Arguments typed? | ✅ Pydantic models everywhere |
| Artifact contract | What must workers return? | ⚠️ Need structured reflection format |
| Provenance | Every claim has source? | ❌ Missing — need to add |
| Resolution policy | Decisions reversible? | ✅ Git-like genome versioning |
| Budget | Limits explicit? | ✅ Risk engine enforces limits |
| Monitoring | Metrics tracked? | ⚠️ Prometheus exists, needs dashboards |
| Recovery | Resume from state? | ⚠️ Partial — need checkpoint/resume |

---

## The Three Steps (Applied to TSAR)

> "1. Vibe coding: the human expresses intent and the model writes.
> 2. Agentic engineering: the human specifies, orchestrates, verifies, and remains responsible for quality.
> 3. Graph engineering: agents share durable state through typed, queryable graphs of work and knowledge."

**TSAR is at Step 2 → transitioning to Step 3.**

The missing piece: typed, queryable graphs with provenance. The FTS5 search (Phase 1A) is the first step. The knowledge graph with provenance tracking is the next step.

---

## The Most Important Insight

> "The bottleneck is often not the next model call. It is the placement of memory and evaluation."

TSAR's architecture already places memory (5 knowledge stores) and evaluation (Risk Guardian, Trade Philosopher) at the center. The borrowings (FTS5 search, Shadow Account, backtest engine) complete the picture.

> "Every important output can be traced to an objective, a plan, an artifact, a source, a graph path, an evaluator decision, and a bounded execution record."

This should be TSAR's quality invariant. Every trade decision should be traceable to:
1. **Objective** — strategy genome that generated the signal
2. **Plan** — signal score, risk-reward ratio
3. **Artifact** — the actual trade record
4. **Source** — market data, pattern matches
5. **Graph path** — which patterns, lessons, and regimes led to this trade
6. **Evaluator decision** — Risk Guardian's 10-point checklist
7. **Execution record** — fill quality, slippage, latency

---

## What to Build (From This Paper)

1. **Provenance tracking** — every knowledge store entry gets: source_trade_id, confidence, evaluation_rationale, version
2. **Genome DAG** — Strategy Geneticist tracks mutation lineage as a DAG, not just current state
3. **Graph queries** — "which trades led to this pattern?" "which patterns led to this genome mutation?"
4. **Evaluation harness** — automated extraction quality scoring, like the paper's graph autoresearch

---

*"The path from loops to graphs is not a path from simplicity to complexity. It is a path from implicit state to explicit state, from volatile memory to durable memory, and from estimation to evidence."*
