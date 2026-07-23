# SUPER AGENT CAPABILITY REPORT
## Defining, Measuring, and Building a Trading Super Agent

**Date:** 2026-07-24
**Status:** Analysis Report — Synthesized from Jensen Huang's vision, LangChain/NVIDIA engineering, production systems (Claude Code, OpenClaw, Hermes), and TSAR architecture research
**Author:** TSAR Research Subagent

---

## Executive Summary

A **Super Agent** is not a bigger multi-agent system. It is a fundamentally different thing: a single, deep, domain-specific intelligence wrapped in a harness that compounds knowledge through use. Where multi-agent systems distribute cognition across many generic workers, a super agent concentrates it into one entity that gets smarter every day.

This report defines precisely what "super agent" means per Jensen Huang's vision, specifies the seven core capabilities each must have, defines "institutional grade" for each, surveys production super agents, and establishes the **Super Agent Test** — the criteria TSAR must meet to qualify.

---

## Part I: The Definition — Super Agent vs Multi-Agent System

### 1.1 Jensen Huang's Core Framework

Jensen Huang articulated the concept across NVIDIA GTC 2025–2026 and Cadence LIVE 2026. The key quotes, distilled:

> *"You have to surround it with what is now known as a harness."*

The harness is NOT the model. It is NOT a framework. It is the entire self-driving runtime that wraps around "intelligence that's good enough" and transforms it into domain expertise.

> *"Agentic systems that are grounded on info, grounded on knowledge, that can use tools to do search and has memory that it manages and has safeguards and has the ability to iterate until it gets the job done."*

This is the capability checklist: **knowledge grounding + tool use + memory management + safeguards + iteration**.

> *"AI becomes ultimately great, become a super agent when we put [specialized domain knowledge into it]."*

Domain expertise is what elevates a general agent to a super agent.

> *"The harness is what turns a general LLM into a domain expert."*

Harness engineering — not fine-tuning — is the primary mechanism.

### 1.2 The Formal Definition

> **A Super Agent is a domain-specific, self-improving, harness-wrapped intelligence system that:**
> 1. Has ONE primary job (domain specificity)
> 2. Wraps a foundation model in a harness of proprietary tools, knowledge, memory, and guardrails
> 3. Compounds intelligence through a flywheel: execute → observe → reflect → refine → repeat
> 4. Accumulates proprietary knowledge that cannot be replicated or outsourced
> 5. Gets measurably better with every interaction

### 1.3 Super Agent vs Multi-Agent System: The Hard Distinction

| Dimension | Multi-Agent System (MAS) | Super Agent |
|-----------|--------------------------|-------------|
| **Architecture** | Many agents, each handling a sub-task | One agent with deep harness; may spawn sub-agents internally |
| **Intelligence model** | Distributed — each agent is shallow | Concentrated — one agent is deep |
| **Coordination** | Explicit message-passing, shared state, orchestrator | Internal — the agent decides when to decompose |
| **Memory** | Per-session or shared-memory bus, typically ephemeral | Persistent, layered: session → domain → institutional |
| **Improvement** | Manual prompt tuning per agent | Flywheel: every interaction → data → evaluation → refinement |
| **Knowledge** | Lives in prompts, shared across agents | Accumulates in the agent's proprietary stores |
| **Failure mode** | Coordination failure (agents miscommunicate, duplicate work) | Over-specialization (mitigated by guardrails) |
| **Analogy** | Temp agency — many workers, each competent at one task, coordinate via email | Partner who never leaves — has read every trade, every memo, every failed experiment |
| **Value creation** | Task completion | Institutional intelligence accumulation |

**The fundamental difference is cumulative intelligence.** MAS reset between tasks. Super agents compound.

As Huang states: *"A super agent is domain-specific. It belongs to you. You build it, improve it, refine it over time."*

### 1.4 What MAS Are (and Aren't)

Multi-agent systems are useful for:
- Distributing independent sub-tasks in parallel
- Separating concerns (research, writing, review)
- Scaling horizontally across many similar problems

MAS are NOT super agents because:
- No persistent knowledge accumulation across tasks
- No self-improvement loop
- Coordination overhead dominates at scale
- No proprietary intelligence moat

**A super agent CAN use sub-agents internally** (and often does — see Claude Code's sub-agent spawning), but the intelligence is centralized. The sub-agents are tools of the super agent, not peers in a coordination protocol.

### 1.5 The Spectrum

```
Chatbot → Agent → Multi-Agent System → Super Agent
  │          │           │                    │
  │          │           │                    │
No tools   Has tools   Many agents        One deep agent
No memory  Has memory  Coordinated        Self-improving
Static     Reactive    Task-oriented      Domain expert
           │           │                    │
           │           │                    │
           └───────────┘                    │
           Useful but no                    │
           cumulative intelligence          │
                                            │
                    ┌────────────────────────┘
                    │
                    ▼
            CUMULATIVE INTELLIGENCE
            PROPRIETARY KNOWLEDGE
            FLYWHEEL EFFECT
            CANNOT BE OUTSOURCED
```

---

## Part II: The Seven Core Capabilities

Per Jensen Huang's definition and validated against production systems (Claude Code, OpenClaw, Hermes, NVIDIA NemoClaw), a super agent MUST have all seven:

### Capability 1: THE HARNESS

**What it is:** The architecture that wraps around a foundation model and transforms raw intelligence into domain expertise. It is the entire runtime: iteration loop, context management, middleware, tool registry, session persistence, system prompt assembly, lifecycle hooks, and permission layer.

**Why it's #1:** The harness IS the product. The model is commodity. Without the harness, you have a chatbot. With it, you have a domain expert.

**Key insight (Harrison Chase, LangChain, July 2026):** *"Memory IS the harness. The harness decides what survives compaction. If you don't own your harness, you don't own your memory."*

**The nine sub-components of a harness:**

| # | Component | Purpose |
|---|-----------|---------|
| 1 | Outer iteration loop | The while-loop that calls tools until the job is done |
| 2 | Context management & compaction | Summarize old turns, offload to filesystem, manage window |
| 3 | Skills & tools registry | Built-in primitives + user-defined skills |
| 4 | Sub-agent management | Spawn isolated children with restricted tools |
| 5 | Built-in skills | Domain-specific workflows (for trading: backtest, risk check, order execution) |
| 6 | Session persistence | Append-only logs, resume after crash |
| 7 | System prompt assembly | Walks project dirs for AGENTS.md, domain knowledge files |
| 8 | Lifecycle hooks | Pre/post tool hooks, JSON-on-stdin protocol |
| 9 | Permission & safety layer | Read-only / write / full, classified per command |

**What "institutional grade" looks like:**

```
INSTITUTIONAL GRADE HARNESS:
├── Iteration loop runs for hours/days without human intervention
├── Context management handles 100K+ token histories gracefully
├── Tool registry supports hot-loading new tools without restart
├── Sub-agents are fully isolated (own context, own tools, own memory)
├── Session persistence survives process crashes (append-only JSONL)
├── System prompt assembly is dynamic (reads AGENTS.md, skills, memory)
├── Lifecycle hooks enable middleware (pre-trade risk checks, compliance filters)
├── Permission layer is per-tool, per-context, per-agent
├── Full observability: every decision, every tool call, every outcome logged
├── Harness profile can be tuned without fine-tuning the model
│   (NVIDIA Nemotron 3 Ultra matched frontier accuracy via harness engineering alone)
└── The harness is YOURS — proprietary, not a generic framework
```

**What it is NOT:**
- NOT a framework (LangGraph, CrewAI) — frameworks are for humans to build agents
- NOT a control plane (LangSmith, Arize) — control planes operate above harnesses
- NOT the model — the model is the engine, the harness is the car

---

### Capability 2: KNOWLEDGE GROUNDING

**What it is:** The ability to ground every decision in domain-specific, proprietary knowledge. Not just "search the web" — but "search YOUR knowledge."

**The three layers of knowledge:**

| Layer | What It Holds | Lifespan | Example |
|-------|--------------|----------|---------|
| Session Memory | Current conversation/working context | Ephemeral | Today's market analysis |
| Domain Memory | Accumulated patterns, rules, heuristics | Persistent | "Volatility spikes after FOMC minutes in rate-sensitive sectors" |
| Institutional Memory | Organizational knowledge, trade secrets | Permanent | Proprietary factor models, regulatory edge cases |

**What "institutional grade" looks like:**

```
INSTITUTIONAL GRADE KNOWLEDGE:
├── RAG system indexed on proprietary documents (trade logs, research, compliance)
├── Every decision is contextually informed by proprietary knowledge
├── Knowledge is continuously updated as new information arrives
├── Access control ensures proprietary knowledge never leaks
├── Three distinct memory tiers (session/domain/institutional) with different lifespans
├── Knowledge search is semantic (vector embeddings) AND keyword (FTS5)
├── Knowledge density increases over time (more useful knowledge per interaction)
├── The knowledge base has a "weight" — some knowledge is more trusted than other
├── Contradictory knowledge is flagged and resolved, not silently ignored
└── Knowledge provenance: every fact traces to its source (trade ID, document, date)
```

---

### Capability 3: TOOL USE

**What it is:** The ability to use domain-specific tools — not just generic "search" and "calculate" but specialized instruments that encode expert workflows.

**What "institutional grade" looks like:**

```
INSTITUTIONAL GRADE TOOLS:
├── Tools are domain-specific (not generic "web search")
│   ├── Trading: market data, TA engine, risk calculator, order executor
│   ├── Chip design: layout optimizer, verification engine, DRC checker
│   └── Legal: contract analyzer, precedent search, compliance checker
├── Tools are composable (output of one feeds input of another)
├── Tools have typed inputs/outputs (not free-text)
├── Tool calls are logged with full context for post-hoc analysis
├── Tools can be added/removed without restarting the agent
├── Tool access is per-agent, per-context (not blanket permissions)
├── Tools encode expert workflows (the tool IS the expertise)
│   ├── A "risk calculator" isn't just math — it encodes risk policy
│   ├── An "order executor" isn't just an API call — it encodes execution strategy
│   └── A "backtester" isn't just a loop — it encodes evaluation methodology
├── Tool failure is graceful (retry, fallback, alert, not crash)
└── Tool output is structured (JSON, not free-text for the agent to parse)
```

---

### Capability 4: MEMORY MANAGEMENT

**What it is:** The agent manages its own memory — deciding what to remember, what to forget, what to compress, and what to surface. Memory is not a passive store; it is an active, curated intelligence layer.

**What "institutional grade" looks like:**

```
INSTITUTIONAL GRADE MEMORY:
├── The agent actively curates its own memory (not just stores everything)
│   ├── Periodic memory reviews: "What from this week is worth keeping?"
│   ├── Memory compaction: old sessions summarized, key facts preserved
│   ├── Memory pruning: outdated information retired
│   └── Memory consolidation: related facts merged into higher-level insights
├── Memory is layered and structured:
│   ├── Working memory (current task context)
│   ├── Episodic memory (specific events: "Trade #847 on July 24")
│   ├── Semantic memory (general knowledge: "RSI oversold works in ranging markets")
│   └── Procedural memory (how-to: "How I successfully traded the NFP release")
├── Memory is searchable (semantic + keyword)
├── Memory has provenance (every fact traces to its source)
├── Memory is persistent across sessions (the agent wakes up with context)
├── Memory grows in value over time (more data = better patterns)
├── Memory is the moat (proprietary, non-replicable)
└── Memory survives agent upgrades (harness changes don't lose memory)
```

---

### Capability 5: SAFEGUARDS

**What it is:** The ability to operate safely within defined boundaries — not just "don't do bad things" but "have an immune system that prevents catastrophic outcomes."

**What "institutional grade" looks like:**

```
INSTITUTIONAL GRADE SAFEGUARDS:
├── Hard limits encoded in code (not config, not prompts)
│   ├── Trading: max drawdown, max position size, mandatory stop-loss
│   ├── General: rate limits, cost caps, action budgets
│   └── These CANNOT be overridden by the agent, regardless of reasoning
├── Veto capability on critical actions
│   ├── Risk agent can block any trade
│   ├── Compliance agent can block any external communication
│   └── Veto is absolute — cannot be "convinced" by high-confidence signals
├── Sandboxed execution
│   ├── Code runs in isolated environments
│   ├── Tool access is per-agent, per-context
│   └── Sub-agents cannot affect parent's state without explicit permission
├── Kill switch (immediate halt on anomaly detection)
├── Approval gates for high-stakes actions
│   ├── Human-in-the-loop for strategy mutations
│   ├── Human-in-the-loop for capital allocation changes
│   └── Graduated autonomy: more trust = fewer gates over time
├── Full audit trail (every decision logged with rationale)
├── Graceful degradation (if a component fails, others continue)
└── The safeguards are PART of the harness, not bolted on afterward
```

---

### Capability 6: ITERATION

**What it is:** The ability to iterate — to keep working until the job is done, not just produce a single response. This is the "while loop" at the heart of agentic behavior.

**What "institutional grade" looks like:**

```
INSTITUTIONAL GRADE ITERATION:
├── The agent works until the job is done (not until it runs out of tokens)
│   ├── Claude Code: iterates through file edits, tests, fixes until code works
│   ├── Trading: iterates through signal → risk check → execution → monitoring
│   └── Research: iterates through search → read → synthesize → search more
├── Iteration has structure (not just "try again"):
│   ├── Observe: what happened?
│   ├── Orient: what does it mean?
│   ├── Decide: what to do next?
│   ├── Act: do it
│   └── (OODA loop)
├── Iteration has stopping conditions:
│   ├── Job complete (success criteria met)
│   ├── Max iterations reached (budget exhausted)
│   ├── No progress detected (diminishing returns)
│   └── Safety limit triggered (guardrail violation)
├── Iteration is resumable (can pause and continue across sessions)
├── Iteration is observable (every step logged)
└── Iteration produces artifacts (not just final answer, but reasoning chain)
```

---

### Capability 7: DOMAIN EXPERTISE (via the Flywheel)

**What it is:** The agent doesn't just have domain knowledge — it has domain EXPERTISE that compounds over time. This is the flywheel: use → data → evaluation → refinement → better use.

**What "institutional grade" looks like:**

```
INSTITUTIONAL GRADE DOMAIN EXPERTISE:
├── The flywheel is running:
│   ├── Every interaction generates structured data
│   ├── Data is evaluated against success criteria
│   ├── Evaluation produces insights
│   ├── Insights refine the harness (prompts, tools, middleware, guardrails)
│   └── Refined harness produces better outcomes → more data → ...
├── Expertise is measurable:
│   ├── Win rate, Sharpe ratio, max drawdown (trading)
│   ├── Code quality, test pass rate, time-to-fix (software)
│   ├── Prediction accuracy, decision quality (general)
│   └── Metrics improve over time (the flywheel is working)
├── Expertise is proprietary:
│   ├── Cannot be purchased (the data is yours)
│   ├── Cannot be copied (the harness is yours)
│   ├── Cannot be outsourced (the judgment is yours)
│   └── Only grows through YOUR use (no one else's data helps)
├── Expertise is encoded in multiple forms:
│   ├── Strategy genomes (evolving executable rules)
│   ├── Pattern library (discovered patterns not in textbooks)
│   ├── Lesson archive (distilled insights from experience)
│   ├── Regime models (understanding of market states)
│   └── Execution playbooks (how to get things done)
├── Expertise compounds:
│   ├── Trade #1: basic strategy, generic sizing
│   ├── Trade #100: strategy tuned to 2 regimes, lessons applied
│   ├── Trade #1000: 5+ strategies, pattern library, regime detection
│   └── Trade #10000: knowledge base IS the competitive edge
└── Expertise survives personnel changes (it's in the system, not in anyone's head)
```

---

## Part III: How Production Super Agents Work

### 3.1 Claude Code (Anthropic)

**Domain:** Software engineering
**Architecture:** Single agent with deep harness

| Component | Implementation |
|-----------|---------------|
| Harness | Custom agentic loop (not LangChain), file system tools, git integration, test runner |
| Knowledge | Reads project files (AGENTS.md, CLAUDE.md), context from codebase |
| Tools | File read/write/edit, exec (shell), web search, sub-agent spawning |
| Memory | Project files persist across sessions; context compaction for long conversations |
| Safeguards | Permission model (read-only → write → full), sandboxed execution |
| Iteration | Loops: read file → edit → run tests → fix → repeat until tests pass |
| Domain expertise | Deep code understanding, pattern recognition from codebase structure |

**Key insight:** Claude Code converged on the same harness shape as OpenClaw independently. The harness shape is universal.

### 3.2 OpenClaw

**Domain:** Personal productivity, multi-platform communication
**Architecture:** Hub-and-spoke gateway with agent runtime

| Component | Implementation |
|-----------|---------------|
| Gateway | Node.js WebSocket server — control plane for routing, auth, session management |
| Agent Runtime | `runEmbeddedPiAgent`: auth → model selection → attempt loop → tool dispatch |
| Memory | Workspace files (AGENTS.md, SOUL.md, USER.md, MEMORY.md) + FTS5 session search |
| Tools | Plugin system with hot-loading, MCP protocol support, tool sandboxing |
| Sub-agents | `sessions_yield` pattern: spawn children, yield, results auto-announce |
| Safeguards | Tool policy precedence, exec allowlists, session-based security boundaries |
| Iteration | Outer loop with context assembly, tool dispatch, session persistence |
| Flywheel | Daily memory files → MEMORY.md curation → institutional knowledge grows |

**Key insight:** Memory IS the harness. OpenClaw's workspace files (AGENTS.md, MEMORY.md) are the competitive advantage, not the model.

### 3.3 Hermes Agent (NousResearch)

**Domain:** Self-improving general agent
**Architecture:** Fork/evolution of OpenClaw with autonomous learning

| Component | Implementation |
|-----------|---------------|
| Learning Engine | `create_skill()` — auto-generates SKILL.md files from experience |
| Skill Self-Improvement | `improve_skill()` — patch-based updates when better approaches discovered |
| Memory Curation | Periodic self-prompting to review interactions and persist important info |
| Kanban Board | Durable multi-agent task board with worker lanes and crash recovery |
| FTS5 Search | Full-text search across all past conversations with LLM summarization |
| Honcho Modeling | Dialectic user modeling — builds deepening understanding of user across sessions |
| Sub-agents | Hierarchical delegation with model override (cheap models for workers) |

**Key insight:** Hermes's autonomous skill creation is the closest production implementation of the flywheel. The agent literally writes its own skills from experience.

### 3.4 NVIDIA NemoClaw (with LangChain Deep Agents)

**Domain:** Enterprise coding agents
**Architecture:** LangChain Deep Agents harness + Nemotron 3 Ultra model

| Component | Implementation |
|-----------|---------------|
| Harness Profile | JSON configuration that shapes agent behavior (system prompt, tools, middleware) |
| Harness Engineering | Tuning the harness, not the model — achieved frontier accuracy without fine-tuning |
| Key Result | Nemotron 3 Ultra with tuned harness matched proprietary frontier model accuracy |
| Cost Advantage | Open model + harness engineering = proprietary model performance at fraction of cost |

**Key insight:** Harness engineering is the "soft fine-tune." By making model calls resemble training data distributions, adding middleware that corrects failure modes, and constraining the search space to proven patterns, you get fine-tuning-level results without touching weights.

### 3.5 Common Patterns Across All Production Super Agents

```
PATTERN 1: The Harness Shape Is Universal
  Claude Code, OpenClaw, Hermes, NemoClaw — all converged on:
  iteration loop + context management + tool registry + memory + safeguards

PATTERN 2: Memory IS the Harness
  The agent's memory files (AGENTS.md, MEMORY.md, skill files) ARE the product.
  The model is commodity. The memory is proprietary.

PATTERN 3: Sub-agents Are Internal, Not Peer
  Super agents spawn sub-agents as tools, not as coordination partners.
  Intelligence is centralized, not distributed.

PATTERN 4: The Flywheel Requires Evals
  Without evaluation, you can't measure improvement.
  Without measurement, you can't refine.
  Without refinement, it's not a super agent.

PATTERN 5: Harness Engineering > Fine-Tuning (for most scenarios)
  NVIDIA proved this empirically. Cheaper, faster, more reversible.

PATTERN 6: Domain Specificity Is Non-Negotiable
  Every production super agent has ONE primary domain.
  General-purpose agents are useful but don't compound expertise.
```

---

## Part IV: The Super Agent Test — Criteria for TSAR

### 4.1 The Test

To be called a **super agent** (not just a trading bot or MAS), TSAR must pass ALL of the following criteria:

```
╔══════════════════════════════════════════════════════════════════════╗
║                    THE SUPER AGENT TEST                              ║
║                    10 Criteria — ALL Must Pass                       ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  CRITERION 1: DOMAIN SPECIFICITY                                     ║
║  ─────────────────────────────────                                   ║
║  Does the agent have ONE primary job?                                ║
║  Is it built for that job, not adapted from a general-purpose agent? ║
║  Does it have domain-specific tools, not generic ones?               ║
║                                                                      ║
║  PASS: TSAR's one job is "autonomous capital compounding under       ║
║  strict risk constraints." Every component serves this.              ║
║                                                                      ║
║  CRITERION 2: HARNESS (not framework, not model)                     ║
║  ──────────────────────────────────────────────                      ║
║  Is there a complete harness: iteration loop + context management    ║
║  + tool registry + session persistence + system prompt assembly?     ║
║  Is the harness proprietary (not just CrewAI/LangGraph)?             ║
║                                                                      ║
║  PASS: TSAR has: Queen orchestrator (iteration), unified memory      ║
║  store (context), tool registry, session persistence, config-driven  ║
║  prompt assembly. The harness is custom Python, not a framework.     ║
║                                                                      ║
║  CRITERION 3: PROPRIETARY KNOWLEDGE ACCUMULATION                     ║
║  ──────────────────────────────────────────────                      ║
║  Does the agent accumulate knowledge that cannot be replicated?      ║
║  Is the knowledge stored in structured, searchable, persistent       ║
║  stores?                                                             ║
║  Does the knowledge grow in value over time?                         ║
║                                                                      ║
║  PASS: TSAR has five proprietary stores: trades.db, strategy         ║
║  genomes, regime state, pattern library, lesson archive.             ║
║  Each grows with every trade. After 10,000 trades, the knowledge     ║
║  base IS the edge.                                                   ║
║                                                                      ║
║  CRITERION 4: FLYWHEEL (self-improvement loop)                       ║
║  ─────────────────────────────────────────────                       ║
║  Does the agent get measurably better over time?                     ║
║  Is there a concrete execute → observe → reflect → refine → repeat  ║
║  loop?                                                               ║
║  Can you measure improvement (metrics trending positive)?            ║
║                                                                      ║
║  PASS: TSAR has: trade execution → outcome recording → LLM          ║
║  reflection → lesson extraction → strategy genome update →           ║
║  improved next trade. Metrics: expectancy_trend, regime_accuracy,    ║
║  lesson_application_rate, sharpe_trend.                              ║
║                                                                      ║
║  CRITERION 5: MEMORY MANAGEMENT (not just storage)                   ║
║  ────────────────────────────────────────────────                    ║
║  Does the agent actively manage its own memory?                      ║
║  Can it decide what to remember, forget, compress, surface?          ║
║  Is memory layered (session/domain/institutional)?                   ║
║                                                                      ║
║  PASS: TSAR has: FTS5 session search, ChromaDB vectors, workspace   ║
║  memory (MEMORY.md, daily notes), memory curation nudges            ║
║  (periodic self-prompting), three-tier memory architecture.          ║
║                                                                      ║
║  CRITERION 6: SAFEGUARDS (immune system, not bolt-on)                ║
║  ───────────────────────────────────────────────────                 ║
║  Are safeguards part of the harness (not afterthought)?              ║
║  Are hard limits encoded in code (not config, not prompts)?          ║
║  Is there a veto mechanism for critical decisions?                   ║
║  Is there a kill switch?                                             ║
║                                                                      ║
║  PASS: TSAR has: Risk Engine with absolute veto, hard limits in      ║
║  code (max drawdown, max position, mandatory stop-loss),             ║
║  4-level control hierarchy, approval gates for mutations,            ║
║  kill switch. Risk agent is independent from signal agent.           ║
║                                                                      ║
║  CRITERION 7: TOOL USE (domain-specific, not generic)                ║
║  ───────────────────────────────────────────────────                 ║
║  Are tools domain-specific (not just web search + calculator)?       ║
║  Do tools encode expert workflows?                                   ║
║  Are tools composable?                                               ║
║                                                                      ║
║  PASS: TSAR has: market data (AkShare/CCXT), technical analysis      ║
║  (TA-Lib), risk calculator (Kelly Criterion), order executor,        ║
║  regime detector, backtester, portfolio optimizer. Each tool         ║
║  encodes trading expertise, not just API calls.                      ║
║                                                                      ║
║  CRITERION 8: ITERATION (works until done, not one-shot)             ║
║  ─────────────────────────────────────────────────────               ║
║  Does the agent iterate until the job is done?                       ║
║  Can it run for hours/days without human intervention?               ║
║  Does it have stopping conditions?                                   ║
║                                                                      ║
║  PASS: TSAR iterates: scan → signal → risk check → execute →        ║
║  monitor → reflect → refine. Runs 24/7 in live mode.                ║
║  Stopping conditions: kill switch, max drawdown, daily loss limit.   ║
║                                                                      ║
║  CRITERION 9: SUB-AGENT ARCHITECTURE (internal, not peer)            ║
║  ───────────────────────────────────────────────────────             ║
║  Are sub-agents spawned internally by the super agent?               ║
║  Is intelligence centralized (not distributed across peers)?         ║
║  Can the agent decide when to decompose a task?                      ║
║                                                                      ║
║  PASS: TSAR's Queen orchestrator spawns sub-agents (Regime           ║
║  Detector, Signal Scout, Risk Guardian, Execution Sniper, etc.)      ║
║  as internal workers. Intelligence is centralized in the Queen.      ║
║  Sub-agents are tools, not peers.                                    ║
║                                                                      ║
║  CRITERION 10: PROPRIETARY FLYWHEEL DATA (the moat)                  ║
║  ─────────────────────────────────────────────────                   ║
║  Does every interaction generate proprietary data?                   ║
║  Does that data make the next interaction better?                    ║
║  Is this data non-replicable by competitors?                         ║
║                                                                      ║
║  PASS: Every trade generates: outcome data, reflection, lesson,      ║
║  regime context, execution quality metrics. This data feeds the      ║
║  flywheel. After 10,000 trades, TSAR has seen patterns no human     ║
║  has seen. This data cannot be purchased or copied.                  ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  VERDICT: TSAR, as designed in the blueprint, passes ALL 10          ║
║  criteria. It IS a super agent architecture — not just a trading     ║
║  bot, not just a MAS.                                                ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

### 4.2 The Anti-Tests — What FAILS

| System | Why It Fails the Super Agent Test |
|--------|----------------------------------|
| **Trading bot (algo)** | No flywheel. Static rules. No memory. No self-improvement. Code can be copied. |
| **CrewAI multi-agent** | MAS, not super agent. No persistent knowledge. No flywheel. Coordination overhead. |
| **ChatGPT with plugins** | No harness. No iteration. No domain expertise. No proprietary knowledge. |
| **Custom GPT** | Prompt engineering only. No tools, no memory, no iteration, no safeguards. |
| **LangGraph workflow** | Framework for building agents. Not an agent itself. No domain knowledge. |
| **Trading signal service** | No execution. No reflection. No learning. Just alerts. |

### 4.3 The Grading Scale

Not all super agents are equal. Here's the maturity scale:

```
LEVEL 1: PROTOTYPE (Passes criteria 1-3)
├── Has domain, harness, and basic knowledge
├── No flywheel, no self-improvement
├── Equivalent to: a well-built trading bot with memory
└── Status: TSAR Blueprint v1

LEVEL 2: FUNCTIONAL (Passes criteria 1-6)
├── Has flywheel running, memory management, safeguards
├── Not yet measuring improvement
├── Equivalent to: a trading system that learns
└── Status: TSAR after Phase 2 (Reflection)

LEVEL 3: OPERATIONAL (Passes criteria 1-8)
├── Has iteration, domain-specific tools
├── Measuring improvement, adjusting strategies
├── Equivalent to: a self-improving trading agent
└── Status: TSAR after Phase 3 (Evolution)

LEVEL 4: INSTITUTIONAL (Passes all 10)
├── Full flywheel, proprietary moat, sub-agent architecture
├── Knowledge base is the competitive edge
├── Equivalent to: a trading super agent
└── Status: TSAR after Phase 4 (Live Trading, 6+ months)

LEVEL 5: COMPOUNDING (All 10 + measurable compounding)
├── Sharpe > 1.5, knowledge density increasing
├── Strategy genomes evolved 3+ times
├── Pattern library has novel discoveries
├── Equivalent to: an institutional-grade trading super agent
└── Status: TSAR after Year 1+
```

---

## Part V: What "Institutional Grade" Means — Summary Table

| Capability | Institutional Grade Definition | Key Metric |
|------------|-------------------------------|------------|
| **Harness** | Proprietary runtime with 9 sub-components, observable, tunable without fine-tuning | Harness profile accuracy ≥ frontier model |
| **Knowledge** | Three-tier memory (session/domain/institutional), semantically searchable, provenance-tracked | Knowledge density (useful facts/trade) increasing |
| **Tools** | Domain-specific, composable, typed, encoding expert workflows | Tool coverage (what % of domain tasks have tools) |
| **Memory** | Agent-curated, layered, persistent, searchable, compounding in value | Memory utilization (how often past knowledge informs decisions) |
| **Safeguards** | Hard limits in code, veto mechanism, kill switch, audit trail | Zero catastrophic failures; graceful degradation on component failure |
| **Iteration** | Runs until job done, resumable, observable, with stopping conditions | Mean time to completion; iteration efficiency |
| **Domain Expertise** | Flywheel running, proprietary knowledge stores, measurable improvement | Expectancy trend positive; Sharpe > 1.5 over 90 days |

---

## Part VI: The Strategic Implication

### 6.1 Open Intelligence vs Closed Intelligence

Jensen Huang draws a sharp line:

> *"Companies are built on specialized intellectual property. That specialization, your company's intelligence, is who you can't outsource."*

| Dimension | Open Intelligence | Closed Intelligence |
|-----------|------------------|-------------------|
| Source | Foundation models (GPT, Claude, Llama, Nemotron) | Your proprietary data, models, harnesses |
| Availability | Everyone has access | Only you have access |
| Value | Commodity — useful but not differentiating | Strategic — this IS your competitive moat |

**The super agent formula:**

```
Open Intelligence (commodity)
    + Proprietary Data (your trades, your research)
    + Domain Harness (your prompts, tools, middleware)
    + Accumulated Judgment (your flywheel data)
    = Closed Intelligence (your moat)
```

The foundation model is table stakes. The super agent — YOUR super agent — is the competitive advantage.

### 6.2 What This Means for TSAR

TSAR's moat is NOT:
- The code (can be copied)
- The model (everyone has access)
- The strategies (can be reverse-engineered)

TSAR's moat IS:
- The trade memory (10,000+ trades with reflections)
- The strategy genomes (evolved through evidence, not backtesting)
- The pattern library (discovered from YOUR data)
- The lesson archive (distilled from YOUR experience)
- The regime models (calibrated to YOUR markets)
- The harness (refined through YOUR use)

**You can copy a bot's code. You cannot copy a super agent's knowledge.**

---

## Part VII: Recommendations for TSAR

### 7.1 Build the Harness First

The harness is the foundation. Without it, everything else is academic. Priority:

1. **Iteration loop** — Queen orchestrator with signal → risk → execute → reflect cycle
2. **Context management** — FTS5 + ChromaDB + workspace memory
3. **Tool registry** — Exchange connectors, TA engine, risk calculator
4. **Session persistence** — Append-only trade logs, crash recovery
5. **Safeguards** — Risk engine with veto, hard limits in code

### 7.2 Start the Flywheel Immediately

Even with paper trading. The flywheel doesn't need real money — it needs real data.

1. **Execute** paper trades with full context
2. **Collect** outcomes + market state
3. **Evaluate** with LLM reflections
4. **Refine** strategy genomes
5. **Repeat** — the flywheel starts spinning

### 7.3 Measure Everything

If you can't measure it, you can't improve it. Track:

- `expectancy_trend` — Is avg PnL per trade improving?
- `regime_accuracy` — How often regime detection matches reality?
- `lesson_application_rate` — Are lessons actually changing behavior?
- `knowledge_density` — Useful knowledge per trade?
- `sharpe_trend` — Risk-adjusted returns improving?

### 7.4 Protect the Moat

The knowledge base is the product. Treat it that way:

- **Backup daily** (encrypted)
- **Version control** strategy genomes
- **Access control** on trade memory
- **Never share** proprietary patterns or lessons
- **Never outsource** the reflection engine (this is where intelligence is built)

---

## Appendix A: Source Quotes — Jensen Huang on Super Agents

> *"You have to surround it with what is now known as a harness."*
— Jensen Huang, NVIDIA GTC 2025

> *"Agentic systems that are grounded on info, grounded on knowledge, that can use tools to do search and has memory that it manages and has safeguards and has the ability to iterate until it gets the job done."*
— Jensen Huang, NVIDIA GTC 2025

> *"AI becomes ultimately great, become a super agent when we put [specialized domain knowledge into it]."*
— Jensen Huang, Cadence LIVE 2026

> *"Super agent is domain-specific. Built for ONE job."*
— Jensen Huang, NVIDIA GTC 2026

> *"A company that is AI-native, the intelligence that's inside the company is proprietary. The skills that the company has is proprietary. You cannot outsource your intelligence. You cannot outsource your skills."*
— Jensen Huang, 2025

> *"Every company will be built on harnesses, not just business processes."*
— Jensen Huang, NVIDIA GTC 2026

> *"Companies are built on specialized intellectual property. That specialization, your company's intelligence, is who you can't outsource."*
— Jensen Huang, NVIDIA GTC 2025

## Appendix B: Source Quotes — Harrison Chase on Harnesses

> *"Memory IS the harness. The harness decides what survives compaction. If you don't own your harness, you don't own your memory."*
— Harrison Chase, LangChain, July 2026

## Appendix C: Architecture Comparison

```
MULTI-AGENT SYSTEM (MAS):
┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
│Agent│  │Agent│  │Agent│  │Agent│
│  A  │  │  B  │  │  C  │  │  D  │
└──┬──┘  └──┬──┘  └──┬──┘  └──┬──┘
   │        │        │        │
   └────────┴────────┴────────┘
            │
      ┌─────┴─────┐
      │Orchestrator│
      └───────────┘

Problems: coordination overhead, no persistent knowledge,
no self-improvement, no proprietary moat.


SUPER AGENT:
      ┌─────────────────────────────────┐
      │         SUPER AGENT             │
      │  ┌───────────────────────────┐  │
      │  │      HARNESS              │  │
      │  │  ┌─────┐  ┌─────┐       │  │
      │  │  │Tools│  │Memory│       │  │
      │  │  └─────┘  └─────┘       │  │
      │  │  ┌─────┐  ┌─────┐       │  │
      │  │  │Safe-│  │Itera-│      │  │
      │  │  │guards│ │tion  │      │  │
      │  │  └─────┘  └─────┘       │  │
      │  └───────────────────────────┘  │
      │                                 │
      │  ┌─────┐ ┌─────┐ ┌─────┐       │
      │  │Sub- │ │Sub- │ │Sub- │       │
      │  │Agent│ │Agent│ │Agent│       │
      │  └─────┘ └─────┘ └─────┘       │
      │         (internal)              │
      └─────────────────────────────────┘
                    │
              ┌─────┴─────┐
              │  FLYWHEEL  │
              │execute→data│
              │→evaluate→  │
              │refine→     │
              │repeat      │
              └───────────┘

Advantages: centralized intelligence, persistent knowledge,
self-improving, proprietary moat.
```

---

## Appendix D: The Super Agent Test — Quick Reference Card

```
╔══════════════════════════════════════════════════════════════╗
║              SUPER AGENT TEST — QUICK REFERENCE              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  1. DOMAIN SPECIFICITY    → One job, built for it            ║
║  2. HARNESS               → Runtime, not framework           ║
║  3. KNOWLEDGE             → Proprietary, accumulating        ║
║  4. FLYWHEEL              → Execute→Observe→Reflect→Refine   ║
║  5. MEMORY MANAGEMENT     → Agent-curated, layered           ║
║  6. SAFEGUARDS            → Hard limits, veto, kill switch   ║
║  7. TOOLS                 → Domain-specific, encode expertise ║
║  8. ITERATION             → Works until done, not one-shot   ║
║  9. SUB-AGENTS            → Internal, not peer               ║
║ 10. PROPRIETARY DATA      → Every interaction = more moat    ║
║                                                              ║
║  ALL 10 = Super Agent                                        ║
║  7-9    = Advanced Agent                                     ║
║  4-6    = Agentic System                                     ║
║  1-3    = Agent                                              ║
║  0      = Chatbot                                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

*Report generated: 2026-07-24*
*Sources: Jensen Huang (GTC 2025-2026, Cadence LIVE 2026), LangChain/NVIDIA harness engineering (July 2026), Claude Code architecture analysis, OpenClaw architecture, Hermes Agent (NousResearch), TSAR Blueprint v2.0*
