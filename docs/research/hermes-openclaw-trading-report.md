# Hermes + OpenClaw: Features for Institutional-Grade Multi-Agent Trading System

**Date:** 2026-07-24
**Status:** Research Report — Code-Level Recommendations

---

## Table of Contents

1. [Hermes Agent — What It Is](#1-hermes-agent)
2. [OpenClaw — What It Is](#2-openclaw)
3. [Your Superagent Project — Analysis](#3-superagent-analysis)
4. [Features Directly Applicable to Trading](#4-trading-applicable-features)
5. [What Can Be Forked/Ported/Adapted](#5-fork-port-adapt)
6. [Recommended Trading Super Agent Architecture](#6-architecture)

---

## 1. Hermes Agent — What It Is {#1-hermes-agent}

**Repo:** `NousResearch/hermes-agent`
**Tagline:** "The agent that grows with you"
**Language:** Python (Node.js for gateway/UI)
**License:** MIT

### What It Is

Hermes Agent is NousResearch's open-source self-improving AI agent framework. It is a **fork/evolution of OpenClaw** (the repo includes `hermes claw migrate` for OpenClaw migration), but adds a fundamentally different philosophy: **the agent learns and improves autonomously over time**.

### Agent Framework

Hermes is NOT built on LangChain/CrewAI/AutoGen. It's a **custom agentic loop** with:
- A **Gateway** (Node.js WebSocket server) that acts as the control plane
- An **Agent Runtime** (Python) that runs the LLM reasoning loop
- **Tool dispatch** via a tool registry (MCP-compatible + built-in)
- **Session management** with context assembly and compaction

### Key Capabilities

| Capability | Details |
|---|---|
| **Self-Improving Learning Loop** | Agent creates skills from experience, improves them during use, nudges itself to persist knowledge |
| **Autonomous Skill Creation** | After complex tasks, agent auto-generates reusable skill files (SKILL.md format, agentskills.io compatible) |
| **Skill Self-Improvement** | Skills get patched (not rewritten) when better approaches are discovered |
| **Memory Curation Nudges** | Periodic self-prompting to review interactions and persist important info |
| **FTS5 Session Search** | Full-text search across all past conversations with LLM summarization |
| **Honcho Dialectic User Modeling** | Builds deepening model of the user across sessions |
| **Kanban Task Board** | Durable multi-agent task board with worker lanes and crash recovery |
| **Sub-agent Spawning** | Isolated subagents for parallel workstreams, push-based completion |
| **Cron Scheduler** | Built-in scheduled automations with delivery to any platform |
| **6 Terminal Backends** | Local, Docker, SSH, Singularity, Modal, Daytona (serverless) |
| **Batch Trajectory Generation** | Research-ready: generate training data for next-gen tool-calling models |
| **Multi-Channel** | Telegram, Discord, Slack, WhatsApp, Signal, CLI from single gateway |

### Multi-Agent Orchestration

Hermes uses a **hierarchical delegation model**:
- Main agent can `spawn` isolated subagents with their own context
- Subagents run in parallel with push-based completion (results auto-announce)
- Python scripts can call tools via RPC, collapsing multi-step pipelines
- The Kanban board provides durable task queuing with worker lanes
- **No explicit "crew" or "graph" abstraction** — orchestration is emergent from spawn + memory

---

## 2. OpenClaw — What It Is {#2-openclaw}

**Repo:** `openclaw` (180K+ GitHub stars as of Feb 2026)
**Creator:** Peter Steinberger
**Language:** TypeScript (Node.js 22+)
**License:** Open source

### What It Is

OpenClaw is an **operating system for AI agents** — not a chatbot wrapper. It treats AI as an infrastructure problem: sessions, memory, tool sandboxing, access control, and orchestration. The LLM provides intelligence; OpenClaw provides the execution environment.

### Architecture (Hub-and-Spoke)

```
┌─────────────────────────────────────────────┐
│              GATEWAY (Control Plane)         │
│  WebSocket server on 127.0.0.1:18789        │
│  ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│  │ Channel  │ │  Agent   │ │   Control   │ │
│  │ Adapters │ │ Runtime  │ │  Plane API  │ │
│  └──────────┘ └──────────┘ └─────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│  │  Cron    │ │ Heartbeat│ │   Plugin    │ │
│  │Scheduler │ │  System  │ │   Loader    │ │
│  └──────────┘ └──────────┘ └─────────────┘ │
└──────────────────┬──────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
┌────────┐  ┌──────────┐  ┌──────────┐
│Channel │  │  Agent   │  │  Local   │
│Adapters│  │ Runtime  │  │Execution │
│(20+)   │  │(LLM Loop)│  │(Sandbox) │
└────────┘  └──────────┘  └──────────┘
```

### Core Components

1. **Channel Adapters** — Normalized interface for 20+ messaging platforms (WhatsApp, Telegram, Discord, Slack, Signal, iMessage, Teams, etc.)
2. **Gateway Control Plane** — Single WebSocket server, source of truth for all routing, auth, session management
3. **Agent Runtime** — `runEmbeddedPiAgent`: resolves auth, selects model, runs attempt loop with failover, tool dispatch
4. **Plugin System** — Discovery-based hot-loading: channel plugins, memory plugins, tool plugins, provider plugins
5. **Memory System** — Workspace files (AGENTS.md, MEMORY.md, daily notes) + FTS5 session search + vector embeddings
6. **Sub-agent Spawning** — `sessions_yield` pattern: spawn child agents, yield, results auto-announce
7. **Tool Sandboxing** — Session-based security boundaries, exec allowlists, tool policy precedence
8. **Cron + Webhooks** — Scheduled actions and external triggers
9. **Canvas (A2UI)** — Agent-to-UI rendering for rich outputs

### Agent Capabilities

- **Multi-Agent Routing** — Multiple named agents with different models, tools, permissions
- **Session Tools (Agent-to-Agent)** — Direct inter-agent communication via session resolution
- **Context Assembly** — Workspace files → session history → memory search → tool results, all assembled per-turn
- **System Prompt Architecture** — Layered: AGENTS.md + SOUL.md + USER.md + skills + tool descriptions
- **Progressive Memory Disclosure** — Skills loaded in tiers to minimize token cost

---

## 3. Your Superagent Project — Analysis {#3-superagent-analysis}

**Repo:** `ovalentine964/superagent` (fork of `NousResearch/hermes-agent`)
**Deployed:** https://superagent-zzgx.onrender.com/health

### What You Built

Your project is a **Python-native multi-agent system** that extracts and recombines key patterns from both Hermes and OpenClaw. It's NOT a full fork of either codebase — it's a **clean-room reimplementation** of the best parts in Python.

### Architecture

```
QUEEN (Orchestrator) — routes intents to swarms
    ├── Market Intelligence Swarm
    ├── Information Network Swarm
    └── Coordination Engine Swarm
         │
         ▼
    Unified Memory (SQLite FTS5 + ChromaDB)
         │
         ▼
    Learning Loop (Reflection + Skill Creation)
```

### What's Actually Implemented (Code-Level)

**`superagent/main.py`** — Full boot sequence:
1. Database init (SQLite)
2. Tool Registry with auto-discovery
3. Unified Memory Store (workspace files + FTS5 + Redis cache)
4. Knowledge Base (ChromaDB vectors)
5. Learning Engine (skill creation, improvement, memory curation)
6. Queen Orchestrator (intent routing + swarm dispatch)
7. Telegram Handler
8. FastAPI server (OpenAI-compatible `/v1/chat/completions`)

**`superagent/agents/queen.py`** — Working orchestrator:
- LLM-based intent classification (semantic routing)
- Keyword fallback classifier
- Parallel dispatch to swarms (`dispatch_parallel`)
- SwarmType enum: MARKET, INFO, COORD
- TaskPriority enum: LOW, MEDIUM, HIGH, CRITICAL

**`superagent/memory/learning.py`** — Hermes-compatible learning engine:
- `Skill` dataclass with success_rate tracking
- `create_skill()` — auto-generates SKILL.md files (agentskills.io format)
- `improve_skill()` — patch-based skill updates
- `curate_memory()` — LLM-powered memory nudge (reviews recent interactions)
- `LearningEvent` tracking

**`superagent/memory/store.py`** — Unified memory:
- Workspace memory (MEMORY.md, daily notes, USER.md, AGENTS.md)
- FTS5 session search with Redis caching
- Message storage with session tracking

**`superagent/config.yaml`** — Production-ready config:
- LLM via LiteLLM (multi-provider)
- ChromaDB for vectors
- Redis for caching
- Cron scheduling
- Rate limiting
- Sandbox exec

### What's Reusable

| Component | Reusability | Notes |
|---|---|---|
| Queen Orchestrator pattern | ✅ HIGH | Intent → swarm routing is exactly what trading needs |
| Learning Engine | ✅ HIGH | Skill creation + improvement + memory curation |
| Unified Memory Store | ✅ HIGH | FTS5 + workspace + Redis cache layer |
| Tool Registry | ✅ HIGH | Auto-discovery, modular registration |
| Agent Hierarchy (3-tier) | ✅ HIGH | Queen → Swarm Leaders → Workers |
| Config System | ✅ MEDIUM | Good structure, needs trading-specific additions |
| Telegram Handler | ✅ MEDIUM | Working, just needs trading commands |
| `superagent_main.py` | ⚠️ LOW | Just an echo bot placeholder — the real code is in `superagent/` |

---

## 4. Features Directly Applicable to Trading {#4-trading-applicable-features}

### 4.1 Agent Communication Patterns

**From OpenClaw:**
- **Sub-agent spawning with push-based completion** — Perfect for parallel trade analysis. Spawn a technical analysis agent and a sentiment agent simultaneously; results auto-announce when done.
- **Session-based agent-to-agent communication** — Agents can message each other through session resolution. Critical for risk management agent vetoing a trade signal agent.
- **Multi-agent routing** — Named agents with different models, tools, permissions. Use a fast/cheap model for data collection, expensive model for trade decisions.

**From Hermes:**
- **Kanban task board with worker lanes** — Durable trade order queue with crash recovery. If the agent crashes mid-analysis, the task persists.
- **Subagent model override** — Workers can use cheaper models. Data fetchers use GPT-4o-mini, decision makers use Claude Opus.

**Trading Application:**
```python
# Queen routes "Analyze BTC/USD" to market swarm
# Market swarm spawns parallel workers:
#   - Technical analysis worker (cheap model, chart tools)
#   - Sentiment analysis worker (cheap model, news tools)
#   - Risk assessment worker (expensive model, portfolio tools)
# Results aggregate → Queen makes trade decision
# Risk agent can VETO before execution
```

### 4.2 Tool Use and API Integration

**From OpenClaw:**
- **Plugin system with hot-loading** — Add new exchange connectors without restarting
- **MCP protocol support** — Standard tool interface for exchange APIs, data providers
- **Tool sandboxing** — Exec allowlists prevent runaway trading scripts
- **Tool policy precedence** — Different agents get different tool access (data agents can't execute trades)

**From Hermes:**
- **70+ built-in tools** — web_search, web_fetch, exec, browser, file operations
- **Nous Tool Gateway** — Cloud-hosted tools (Firecrawl for scraping, Browser Use for web automation)
- **Tool Gateway per-backend** — Mix and match tool providers

**Trading Application:**
```
Tools to build as MCP servers:
├── exchange_connector (Binance, Bybit, OANDA APIs)
├── market_data (price feeds, order books, OHLCV)
├── technical_analysis (TA-Lib, pandas-ta wrappers)
├── portfolio_manager (positions, P&L, exposure)
├── risk_manager (position sizing, stop-loss, max drawdown)
├── news_sentiment (scraping + NLP)
├── order_executor (order placement, modification, cancellation)
└── alert_system (Telegram/Discord notifications)
```

### 4.3 Memory and Context Management

**From OpenClaw:**
- **Workspace-based memory** — AGENTS.md (agent rules), SOUL.md (personality), USER.md (preferences), MEMORY.md (long-term)
- **Session state and compaction** — Automatic context window management
- **Memory search with embeddings** — Semantic search across all past interactions
- **Progressive disclosure** — Load only relevant skills/context per turn

**From Hermes:**
- **FTS5 session search** — Full-text search across all past conversations
- **Honcho dialectic user modeling** — Builds deepening understanding of user's risk tolerance, preferred pairs, trading style
- **Memory curation nudges** — Agent periodically reviews trades and persists lessons learned

**Trading Application:**
```
Memory layers for trading:
├── MEMORY.md → Trading rules, max drawdown limits, blacklisted pairs
├── USER.md → Risk tolerance, preferred timeframes, capital allocation
├── memory/YYYY-MM-DD.md → Daily trade log, P&L, lessons learned
├── sessions.db → Full trade history searchable by FTS5
├── ChromaDB → Semantic search: "find all trades where I lost money on ETH"
└── skills/ → Learned patterns: "how I successfully traded the NFP release"
```

### 4.4 Self-Improvement Loops

**From Hermes (this is the killer feature):**

1. **Autonomous Skill Creation** — After a complex trade sequence, the agent auto-creates a skill file documenting the strategy
2. **Skill Self-Improvement** — When a better entry/exit is discovered, the skill gets patched
3. **Memory Curation** — Periodic review of trade history, persisting patterns and lessons
4. **Reflection Cycles** — Daily review of what worked, what didn't, and why

**Trading Application:**
```
After a successful swing trade on EUR/USD:
1. Agent creates skill: "skills/usd-swing-trades/SKILL.md"
   - Documents entry conditions (RSI oversold + support bounce)
   - Documents exit conditions (resistance + overbought)
   - Records position sizing rationale
   
2. Next time similar conditions appear:
   - Agent loads the skill into context
   - Applies learned pattern
   - If outcome is better → patches the skill
   - If outcome is worse → adds counter-example

3. Weekly reflection:
   - Reviews all trades from memory/YYYY-MM-DD.md
   - Updates MEMORY.md with weekly P&L and lessons
   - Prunes underperforming skills
```

### 4.5 Risk Management

**From OpenClaw:**
- **Tool sandboxing** — Prevent agents from executing dangerous commands
- **Exec allowlists** — Control which tools each agent can access
- **Session-based security boundaries** — Isolate agent permissions
- **Access control** — Allowlists for who can trigger trades

**From Hermes:**
- **Write approval gates** — Optional human approval for memory writes (analogous to trade execution approval)
- **Sub-agent isolation** — Workers can't affect each other's state

**Trading Application:**
```
Risk management layers:
1. Tool policy: Only "execution" agent can call order_executor
2. Position limits: Hard-coded max position size per trade
3. Drawdown circuit breaker: If daily loss > 2%, halt all trading
4. Human approval gate: Trades > $X require Telegram confirmation
5. Veto agent: Dedicated risk agent reviews every trade signal
6. Audit trail: Every decision logged to FTS5 for post-mortem
```

---

## 5. What Can Be Forked/Ported/Adapted {#5-fork-port-adapt}

### 5.1 Directly Fork (Copy As-Is)

| Component | Source | Why |
|---|---|---|
| **Learning Engine** | `superagent/memory/learning.py` | Complete, working, Hermes-compatible. Just add trading-specific skill categories. |
| **Unified Memory Store** | `superagent/memory/store.py` | FTS5 + workspace + Redis. Perfect for trade journaling. |
| **Skill format (SKILL.md)** | Hermes agentskills.io standard | Universal skill format. Trading strategies become portable skills. |
| **Config structure** | `superagent/config.yaml` | Well-organized YAML with env var substitution. |
| **Tool Registry** | `superagent/tools/registry.py` | Auto-discovery pattern. Add exchange tools. |

### 5.2 Port and Adapt (Modify for Trading)

| Component | Source | Adaptation Needed |
|---|---|---|
| **Queen Orchestrator** | `superagent/agents/queen.py` | Replace swarm types: MARKET→Analysis, INFO→Sentiment, COORD→Execution. Add risk veto. |
| **Agent Hierarchy** | `superagent/ARCHITECTURE.md` | Add Risk Agent as 4th swarm with VETO power. Add Execution Agent. |
| **Memory Curation** | `superagent/memory/learning.py` | Change nudge prompt to review trades, persist P&L, detect patterns. |
| **Gateway/Channels** | OpenClaw gateway (Node.js) | Use as-is for Telegram alerts. Add trading-specific slash commands. |
| **Cron Scheduler** | OpenClaw cron | Schedule market scans, daily P&L reports, weekly reflections. |

### 5.3 Build New (No Existing Code)

| Component | What to Build | Inspiration |
|---|---|---|
| **Exchange Connectors** | Binance/Bybit/OANDA API wrappers as MCP tools | OpenClaw tool plugin pattern |
| **Technical Analysis Engine** | TA-Lib/pandas-ta wrapper with LLM interpretation | New |
| **Order Management System** | Position tracking, order lifecycle, fill management | New |
| **Risk Engine** | Position sizing, drawdown limits, correlation checks | New |
| **Backtesting Framework** | Historical simulation using learned skills | New |
| **Portfolio Tracker** | Multi-asset P&L, exposure monitoring | New |

### 5.4 Code-Level Porting Guide

**Step 1: Set up the base**
```bash
# Fork your superagent repo
git clone https://github.com/ovalentine964/superagent.git trading-superagent
cd trading-superagent

# The Python code in superagent/ is your foundation
# Keep: memory/, agents/, tools/, gateway/, config.yaml
# Add: trading-specific modules
```

**Step 2: Add trading tools as MCP servers**
```python
# superagent/tools/exchange_tools.py
# Follow the pattern in superagent/tools/market_tools.py

def register(registry):
    registry.register_tool(
        name="get_price",
        description="Get current price for a trading pair",
        parameters={"symbol": "string", "exchange": "string"},
        handler=get_price_handler,
    )
    registry.register_tool(
        name="place_order",
        description="Place a limit/market order",
        parameters={"symbol": "string", "side": "string", "size": "number", ...},
        handler=place_order_handler,
    )
```

**Step 3: Extend the Queen for trading**
```python
# In queen.py, add SwarmType.EXECUTION and SwarmType.RISK
class SwarmType(str, Enum):
    ANALYSIS = "analysis"      # Technical + fundamental
    SENTIMENT = "sentiment"    # News + social + on-chain
    EXECUTION = "execution"    # Order management
    RISK = "risk"              # Risk assessment + veto

# Add veto logic to dispatch():
async def dispatch(self, task, context=None):
    # ... existing routing ...
    
    # Risk veto: every trade signal goes through risk swarm
    if routing.get("requires_execution"):
        risk_result = await self._swarms[SwarmType.RISK].run(
            f"Assess risk for: {subtask}", context
        )
        if risk_result.metadata.get("veto"):
            return AgentResult(content="TRADE VETOED by risk agent")
    
    # Execute
    result = await swarm.run(subtask, context)
    return result
```

**Step 4: Add trading skills**
```markdown
# workspace/skills/rsi-oversold-bounce/SKILL.md
---
name: rsi-oversold-bounce
description: "Buy when RSI < 30 at key support with volume confirmation"
metadata:
  superagent:
    category: trading-strategy
    agent_id: learning-engine
---

# RSI Oversold Bounce Strategy

## Entry Conditions
- RSI(14) < 30 on 4H timeframe
- Price at or near identified support level
- Volume spike > 1.5x 20-period average
- No major news events in next 2 hours

## Exit Conditions
- Take profit: 2:1 risk-reward ratio
- Stop loss: Below support level by 0.5%
- Time stop: Close if no movement in 24 hours

## Risk Rules
- Max position: 2% of portfolio
- Max concurrent: 3 positions
- No trading during NFP/CPI releases
```

---

## 6. Recommended Trading Super Agent Architecture {#6-architecture}

### 6.1 The Trading Super Agent Stack

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TRADING SUPER AGENT GATEWAY                       │
│  Based on: OpenClaw Gateway (Node.js) + Python Agent Runtime        │
│                                                                      │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────────┐ │
│  │  Telegram   │ │  Discord   │ │   Web UI   │ │  REST/WebSocket  │ │
│  │  Commands   │ │  Alerts    │ │ Dashboard  │ │  API (algo feed) │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────────┘ │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                      │
│  │   Cron     │ │  Heartbeat │ │  Learning  │                      │
│  │ (Scans,    │ │ (Health    │ │  Engine    │                      │
│  │  Reports)  │ │  Checks)   │ │ (Skills++) │                      │
│  └────────────┘ └────────────┘ └────────────┘                      │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │  👑 QUEEN    │ │  📋 KANBAN   │ │  🔌 TOOL     │
    │  Orchestrator│ │  Trade Queue │ │  GATEWAY     │
    │  (Router +   │ │  (Durable,   │ │  (MCP +      │
    │   Veto Gate) │ │   Crash-safe)│ │   Exchange)  │
    └──────┬───────┘ └──────────────┘ └──────────────┘
           │
     ┌─────┼─────┬─────────┬─────────┐
     ▼     ▼     ▼         ▼         ▼
  ┌─────┐┌─────┐┌─────┐┌────────┐┌────────┐
  │ 📊  ││ 🧠  ││ ⚡  ││  🛡️   ││  📰    │
  │TECH ││QUANT││EXEC ││  RISK  ││SENTI-  │
  │ANAL ││ANAL ││AGENT││ AGENT  ││MENT    │
  └──┬──┘└──┬──┘└──┬──┘└───┬────┘└───┬────┘
     │      │      │       │         │
     ▼      ▼      ▼       ▼         ▼
  ┌────────────────────────────────────────┐
  │         WORKER AGENTS (Leaf)           │
  │  - Data fetchers (cheap models)        │
  │  - Pattern matchers (specialized)      │
  │  - Report generators                   │
  └────────────────────────────────────────┘
           │
           ▼
  ┌────────────────────────────────────────────────────────────────┐
  │                 MEMORY & KNOWLEDGE LAYER                        │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
  │  │ Trade    │ │ Session  │ │ Vector   │ │ Trading Skills   │ │
  │  │ Journal  │ │ Search   │ │ DB (RAG) │ │ (Learned         │ │
  │  │ (FTS5)   │ │ (FTS5)   │ │          │ │  Strategies)     │ │
  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘ │
  └────────────────────────────────────────────────────────────────┘
```

### 6.2 Agent Definitions

```yaml
agents:
  queen:
    role: orchestrator
    model: anthropic/claude-sonnet-4-20250514  # Best reasoning for routing
    can_spawn: true
    max_spawn_depth: 3
    responsibilities:
      - Route market queries to analysis swarm
      - Route trade signals through risk veto
      - Aggregate multi-swarm results
      - Trigger learning cycles

  analysis_swarm:
    role: swarm-leader
    model: openai/gpt-4o
    workers:
      technical_analyst:
        model: openai/gpt-4o-mini  # Cheap for data crunching
        tools: [market_data, ta_engine, chart_generator]
      fundamental_analyst:
        model: openai/gpt-4o-mini
        tools: [web_search, web_fetch, economic_calendar]
      quant_analyst:
        model: anthropic/claude-sonnet-4-20250514  # Needs strong math
        tools: [backtester, portfolio_optimizer, correlation_engine]

  sentiment_swarm:
    role: swarm-leader
    model: openai/gpt-4o
    workers:
      news_scanner:
        model: openai/gpt-4o-mini
        tools: [web_search, web_fetch, rss_reader]
      social_sentiment:
        model: openai/gpt-4o-mini
        tools: [twitter_api, reddit_api, telegram_scraper]
      onchain_analyst:
        model: openai/gpt-4o-mini
        tools: [etherscan_api, defi_pulse, whale_tracker]

  execution_agent:
    role: executor
    model: anthropic/claude-sonnet-4-20250514  # Must be reliable
    tools: [order_executor, position_manager, exchange_connector]
    constraints:
      - max_position_size: 5%
      - require_risk_approval: true
      - supported_exchanges: [binance, bybit, oanda]

  risk_agent:
    role: risk_manager
    model: anthropic/claude-sonnet-4-20250514
    tools: [portfolio_analyzer, drawdown_monitor, correlation_checker]
    has_veto: true  # Can block any trade
    constraints:
      - max_daily_loss: 2%
      - max_drawdown: 10%
      - max_correlated_positions: 3
      - max_leverage: 3x
```

### 6.3 Trade Flow (End-to-End)

```
1. SIGNAL GENERATION
   User: "Analyze BTC/USD for a swing trade"
   → Queen routes to Analysis Swarm + Sentiment Swarm (parallel)

2. ANALYSIS (parallel)
   Technical Analyst: "RSI oversold at 28, price at $62K support, 
                       MACD bullish divergence on 4H"
   Sentiment Analyst: "Fear & Greed at 22 (extreme fear), 
                       whale wallets accumulating, 
                       negative news cycle bottoming"
   → Results aggregate to Queen

3. RISK ASSESSMENT (mandatory gate)
   Risk Agent: "Current BTC exposure: 0%. Portfolio drawdown: -0.5%. 
                No correlated positions. Approved for 2% allocation."
   → VETO or APPROVE

4. EXECUTION
   Execution Agent: Places limit buy at $62,100 with:
   - Stop loss: $60,500 (-2.6%)
   - Take profit: $65,500 (+5.5%)
   - Position size: 2% of portfolio
   
5. MONITORING
   Heartbeat checks position every 30min
   Alerts via Telegram on fill, stop hit, or TP reached

6. POST-TRADE LEARNING
   Learning Engine: Reviews trade outcome
   → Creates/updates skill: "BTC support bounce strategy"
   → Writes to memory/YYYY-MM-DD.md trade journal
   → Updates MEMORY.md with weekly performance summary
```

### 6.4 Key Technical Decisions

| Decision | Recommendation | Why |
|---|---|---|
| **Language** | Python (agent runtime) + Node.js (gateway) | Python for trading libs (pandas, TA-Lib). Node.js for OpenClaw gateway. |
| **LLM Provider** | LiteLLM (multi-provider) | Already in your superagent. Switch models per agent. |
| **Database** | SQLite FTS5 + ChromaDB + Redis | Your existing stack. Proven, lightweight, sufficient. |
| **Exchange APIs** | ccxt library | Unified interface for 100+ exchanges. Wrap as MCP tools. |
| **Technical Analysis** | pandas-ta + TA-Lib | Industry standard. Wrap as tool functions. |
| **Backtesting** | Backtrader or vectorbt | Test learned skills against historical data. |
| **Deployment** | Docker + VPS (Hetzner/DO) | Self-hosted, low latency. $5-20/month. |
| **Alerts** | Telegram (already working) | Your superagent already has this. |
| **Skill Format** | agentskills.io (SKILL.md) | Hermes standard. Portable, version-controlled. |

### 6.5 What NOT to Build (Use Existing)

| Need | Use This Instead |
|---|---|
| Exchange connectivity | ccxt library (don't write raw API calls) |
| Order management | ccxt + your execution agent (don't build from scratch) |
| Chart generation | matplotlib + mplfinance (don't build custom) |
| News scraping | Firecrawl via Hermes Tool Gateway (don't write scrapers) |
| LLM calls | LiteLLM (already in your superagent) |
| Message routing | OpenClaw gateway (already battle-tested) |
| Memory/search | Your UnifiedMemoryStore (already working) |

### 6.6 Implementation Priority

```
Phase 1 (Week 1-2): Foundation
├── Fork superagent repo
├── Add ccxt-based exchange tools
├── Add pandas-ta technical analysis tool
├── Define trading agent hierarchy in config.yaml
└── Test basic "analyze → decide → alert" flow

Phase 2 (Week 3-4): Risk & Execution
├── Build risk agent with veto logic
├── Build execution agent with order management
├── Add position tracking to memory store
├── Implement drawdown circuit breaker
└── Add human approval gate for live trades

Phase 3 (Week 5-6): Learning & Polish
├── Adapt learning engine for trade-specific skills
├── Add backtesting framework
├── Build Telegram command interface (/analyze, /positions, /pnl)
├── Add daily P&L reporting via cron
└── Implement weekly reflection cycle

Phase 4 (Week 7+): Live Trading
├── Paper trading with real data
├── Graduated position sizing (start small)
├── Performance monitoring dashboard
├── Skill pruning (remove underperforming strategies)
└── Continuous improvement loop
```

---

## Summary

**Hermes** gives you the brain: self-improving learning loops, autonomous skill creation, memory curation, and the Kanban task board. These are the features that make a trading agent *get better over time*.

**OpenClaw** gives you the skeleton: gateway, channel adapters, session management, tool sandboxing, sub-agent spawning, and cron scheduling. These are the infrastructure features that make a trading agent *reliable and observable*.

**Your Superagent** already combines the best of both in Python. The Queen orchestrator, learning engine, unified memory store, and tool registry are directly reusable. The main gap is trading-specific tooling (exchange connectors, TA engine, risk management, order execution).

The recommended path: **fork your superagent, add ccxt + pandas-ta as tools, implement the 5-agent hierarchy (Analysis, Sentiment, Execution, Risk, Queen), and let the Hermes learning loop optimize strategies over time.**

