# Multi-Agent Trading Super Agent: Architectural Patterns Research Report

**Date:** 2026-07-24  
**Sources:** DeerFlow 2.0 (ByteDance), OpenClaw, Hermes (NousResearch), CrewAI, AutoGen, MetaGPT, LangGraph, and broader agent ecosystem

---

## Executive Summary

Three dominant agent frameworks have emerged in 2026 — **DeerFlow 2.0** (77K+ stars, ByteDance), **OpenClaw** (180K+ stars), and **Hermes** (190K+ stars, NousResearch) — each solving different aspects of the agent orchestration problem. For building an institutional-grade trading super agent from scratch, the key insight is: **no single framework has the answer, but each contains patterns that are directly transferable to trading**. This report identifies 30+ specific patterns, rates their trading relevance, and suggests implementation approaches.

---

## 1. DeerFlow 2.0 (ByteDance, MIT License)

**What it is:** An open-source "super agent harness" that orchestrates sub-agents, memory, and sandboxes. Ground-up rewrite of v1 (which was a deep research framework). Python backend + Node.js frontend. LangGraph-based orchestration.

### 1.1 Sandbox Architecture

**What it does:** DeerFlow provides isolated execution sandboxes for code execution, file operations, and tool calls. Supports Docker-based sandboxing with configurable security policies (sandbox mode, bash access, file-write tools). The `make setup` wizard lets you configure execution/safety preferences at install time.

**Why useful for trading:**
- Trade execution code must run in isolation — a buggy strategy should never corrupt the risk engine
- Backtesting sandboxes can run parallel strategy evaluations without interference
- Each sub-agent (signal generator, risk checker, executor) gets its own sandbox boundary
- Prevents a compromised data-fetching agent from accessing execution credentials

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```
- Use Docker containers with resource limits (CPU, memory, network) per agent role
- Implement a SandboxProvider interface with methods: create(), execute(), destroy()
- Network policies: signal agents get market data access, execution agents get broker API access, 
  nothing gets both
- Filesystem isolation: each sandbox gets its own volume, shared volumes are read-only
- Implement timeouts: any sandbox execution that exceeds N seconds gets killed
```

### 1.2 Sub-Agent Orchestration (LangGraph-based)

**What it does:** DeerFlow uses LangGraph for orchestrating sub-agents. Agents are organized in a directed graph where each node is an agent with specific capabilities. The orchestrator decomposes complex tasks, routes sub-tasks to appropriate agents, and aggregates results. Supports `subagents.max_total_per_run` caps.

**Why useful for trading:**
- Trading naturally decomposes into a DAG: Market Data → Signal Generation → Risk Assessment → Position Sizing → Execution → Post-Trade Analysis
- Each node can use a different model (fast model for signal scanning, powerful model for complex risk analysis)
- Parallel branches: multiple signal generators can run simultaneously, results converge at the risk gate
- Built-in caps prevent runaway agent spawning (critical when real money is at stake)

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```python
# Core orchestrator pattern
class TradingOrchestrator:
    def __init__(self, max_agents=10, max_depth=3):
        self.graph = DAG()
        self.agent_registry = {}
        self.max_agents = max_agents
    
    def add_node(self, name: str, agent: Agent, deps: list[str]):
        """Register an agent node with dependencies"""
        self.graph.add_node(name, agent)
        for dep in deps:
            self.graph.add_edge(dep, name)
    
    async def execute(self, context: TradingContext):
        """Execute the DAG in topological order, parallelizing where possible"""
        topo_order = self.graph.topological_sort()
        results = {}
        for batch in self.graph.parallel_batches(topo_order):
            # Execute independent agents in parallel
            batch_results = await asyncio.gather(*[
                self.agent_registry[name].run(context, results)
                for name in batch
            ])
            results.update(dict(zip(batch, batch_results)))
        return results

# Trading DAG definition
orchestrator = TradingOrchestrator()
orchestrator.add_node("data_ingest", DataAgent(), deps=[])
orchestrator.add_node("signal_momentum", MomentumSignalAgent(), deps=["data_ingest"])
orchestrator.add_node("signal_mean_revert", MeanRevertSignalAgent(), deps=["data_ingest"])
orchestrator.add_node("signal_sentiment", SentimentAgent(), deps=["data_ingest"])
orchestrator.add_node("risk_check", RiskAgent(), deps=["signal_momentum", "signal_mean_revert", "signal_sentiment"])
orchestrator.add_node("position_sizing", SizingAgent(), deps=["risk_check"])
orchestrator.add_node("execution", ExecutionAgent(), deps=["position_sizing"])
orchestrator.add_node("post_trade", AnalysisAgent(), deps=["execution"])
```

### 1.3 Skill System (DeerFlow Skills)

**What it does:** DeerFlow has a `.agent/skills/` directory and `skills/public/` directory. Skills are composable, reusable capabilities that agents can invoke. Skills are declared with metadata and can be tested (`tests/skills/`). The system supports Claude Code integration for skill development.

**Why useful for trading:**
- Trading skills are naturally modular: "fetch OHLCV data", "calculate RSI", "place limit order", "check portfolio exposure"
- Skills can be versioned — critical when a strategy change needs rollback
- Skill testing ensures a "place order" skill correctly handles partial fills, rejections, timeouts
- Skills can be shared across agents: the risk agent and signal agent both use "fetch price data" skill

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```python
from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class SkillMetadata:
    name: str
    version: str
    description: str
    required_permissions: list[str]  # e.g., ["market_data", "order_placement"]
    timeout_seconds: int
    retry_policy: str  # "none", "exponential_backoff", "fixed"

class TradingSkill(ABC):
    metadata: SkillMetadata
    
    @abstractmethod
    async def execute(self, params: dict, context: TradingContext) -> SkillResult:
        pass
    
    @abstractmethod
    def validate_params(self, params: dict) -> bool:
        pass

# Example skills
class FetchOHLCV(TradingSkill):
    metadata = SkillMetadata(
        name="fetch_ohlcv", version="1.2.0",
        description="Fetch OHLCV candle data",
        required_permissions=["market_data"],
        timeout_seconds=10, retry_policy="exponential_backoff"
    )

class PlaceLimitOrder(TradingSkill):
    metadata = SkillMetadata(
        name="place_limit_order", version="2.0.1",
        description="Place a limit order with risk checks",
        required_permissions=["order_placement"],
        timeout_seconds=5, retry_policy="none"  # Never retry orders blindly
    )
```

### 1.4 Context Engineering & Compaction

**What it does:** DeerFlow implements "Session Goals" and "Manual Context Compaction." Session goals define what a session is trying to accomplish. Context compaction reduces token usage by summarizing older conversation history while preserving key decisions and state.

**Why useful for trading:**
- Trading sessions have clear goals: "Scan for mean-reversion opportunities in crypto" or "Manage existing AAPL position"
- Context compaction is critical for cost control — a trading agent running 24/7 burns tokens fast
- Preserving key decisions ("we decided to reduce exposure by 30%") while discarding raw analysis saves context window
- Session goals prevent agent drift — the agent won't start researching unrelated topics mid-trading-session

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```python
class TradingSession:
    def __init__(self, goal: str, max_context_tokens: int = 8000):
        self.goal = goal
        self.max_context_tokens = max_context_tokens
        self.messages = []
        self.key_decisions = []  # Never compacted
        self.market_state = {}   # Current snapshot, always available
    
    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if self._token_count() > self.max_context_tokens:
            self.compact()
    
    def compact(self):
        """Summarize older messages, keep key decisions and recent context"""
        # Keep: last 5 messages verbatim, all key_decisions, market_state
        # Summarize: everything older into a "context_summary" message
        old_messages = self.messages[:-5]
        summary = self._summarize(old_messages)
        self.messages = [
            {"role": "system", "content": f"Previous context summary: {summary}"}
        ] + self.messages[-5:]
```

### 1.5 Model-Agnostic Design

**What it does:** DeerFlow supports any model via LangChain's ChatModel abstraction. Configured via `config.yaml` with provider classes: `langchain_openai:ChatOpenAI`, `deerflow.models.vllm_provider:VllmChatModel`, `deerflow.models.openai_codex_provider:CodexChatModel`, etc. Supports OpenRouter (200+ models), local vLLM, and CLI-backed providers.

**Why useful for trading:**
- Different trading tasks need different models: fast cheap model for signal scanning (thousands of tickers), powerful model for complex risk analysis
- Model costs matter at scale — routing 80% of queries to a cheap local model saves thousands/month
- Avoid vendor lock-in: if OpenAI raises prices, swap to a local Qwen3-32B without rewriting anything
- A/B testing models for signal quality becomes trivial

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```python
class ModelRouter:
    def __init__(self, config: dict):
        self.providers = {}
        self.routing_rules = {}
        for model_cfg in config["models"]:
            provider = self._create_provider(model_cfg)
            self.providers[model_cfg["name"]] = provider
    
    async def route(self, task_type: str, messages: list, **kwargs):
        """Route to the best model for this task type"""
        model_name = self.routing_rules.get(task_type, "default")
        provider = self.providers[model_name]
        return await provider.chat(messages, **kwargs)

# Config
# task_type "signal_scan" -> "qwen3-8b-local" (fast, cheap)
# task_type "risk_analysis" -> "gpt-4o" (powerful)
# task_type "execution_review" -> "claude-sonnet-4" (careful)
# task_type "post_trade_report" -> "qwen3-8b-local" (simple)
```

### 1.6 Scheduled Tasks

**What it does:** DeerFlow has built-in scheduled task support for recurring agent operations.

**Why useful for trading:**
- Pre-market scan at 8:30 AM ET every trading day
- End-of-day portfolio reconciliation
- Weekly strategy performance review
- Overnight risk limit recalculation

**Rating:** ⭐ MUST HAVE

**Implementation:** Standard cron-like scheduler with trading calendar awareness (skip holidays, handle early closes).

### 1.7 Long-Term Memory

**What it does:** DeerFlow implements long-term memory for maintaining context across sessions. Memory persists decisions, learnings, and state.

**Why useful for trading:**
- Remember that "AAPL tends to gap down after earnings even when beats expectations"
- Track strategy performance over time
- Remember market regime changes ("we're in a risk-off regime since March")
- Accumulate lessons from past trades

**Rating:** ⭐ MUST HAVE

---

## 2. OpenClaw (180K+ Stars)

**What it is:** A gateway-first agent platform. The gateway is the durable, always-on component. The AI model is pluggable. Built in Node.js/TypeScript. Bet: the hard problem is routing and control.

### 2.1 Gateway Architecture

**What it does:** OpenClaw's gateway is a persistent Node.js process that sits between all input channels and the agent runtime. It handles session management, skill dispatch, hook execution, exec approval/security, multi-agent routing, and OGP federation. The gateway persists independently of the model — swap models and your sessions, hooks, skills, and channel integrations are untouched.

**Why useful for trading:**
- The gateway is the "risk firewall" — every trade signal must pass through it before reaching execution
- Gateway-level kill switch: stop all trading by disabling the gateway, no need to stop individual agents
- Session isolation: one strategy's context never bleeds into another
- Auditability: the gateway logs every message, every tool call, every decision
- Multi-channel access: monitor trading via Telegram while getting alerts on Discord

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```python
class TradingGateway:
    """Always-on process that mediates all agent interactions"""
    
    def __init__(self, config):
        self.channels = {}      # Telegram, Discord, WebSocket API, etc.
        self.sessions = {}      # Isolated per-strategy sessions
        self.hooks = []         # Pre/post execution hooks
        self.kill_switch = False
        self.audit_log = AuditLog()
    
    async def route_message(self, channel: str, message: dict):
        if self.kill_switch:
            return {"error": "Trading halted by kill switch"}
        
        session = self.get_or_create_session(channel, message)
        
        # Pre-execution hooks (risk checks, position limits, etc.)
        for hook in self.hooks:
            result = await hook.pre_execute(message, session)
            if result.blocked:
                self.audit_log.log_blocked(message, result.reason)
                return result
        
        # Route to appropriate agent
        response = await session.agent.run(message)
        
        # Post-execution hooks (logging, P&L update, alerting)
        for hook in self.hooks:
            await hook.post_execute(response, session)
        
        self.audit_log.log(message, response)
        return response
```

### 2.2 Session Management with Compaction

**What it does:** OpenClaw manages session persistence with per-agent memory indexes stored in SQLite. Sessions support compaction (summarizing old context to stay within token limits). Session state is persisted and can be resumed. Supports `session-manager.ts` for lifecycle management.

**Why useful for trading:**
- Each trading strategy gets its own session with isolated context
- Session compaction keeps costs manageable for 24/7 running strategies
- Session persistence means a strategy can resume after a restart without losing context
- Per-agent memory means the momentum strategy doesn't see mean-reversion strategy's context

**Rating:** ⭐ MUST HAVE

### 2.3 Tool Sandboxing & Approval System

**What it does:** OpenClaw has an exec approval system where certain commands require explicit user approval before execution. Tool policies control which tools are available, with before/after tool-call adapters. Host/sandbox edit tools provide isolation.

**Why useful for trading:**
- **This is the most critical trading pattern.** Every order placement should require approval (or at minimum, a risk gate check)
- Tool policies can enforce: "this agent can read market data but cannot place orders"
- Before-adapters: inject risk checks before any order execution
- After-adapters: update portfolio state after any trade
- Audit trail of every tool invocation

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```python
class ToolPolicy:
    """Controls what tools each agent can use and under what conditions"""
    
    def __init__(self):
        self.rules = {}
    
    def add_rule(self, agent_id: str, tool: str, policy: str, conditions: dict = None):
        self.rules[(agent_id, tool)] = {"policy": policy, "conditions": conditions}
    
    async def check(self, agent_id: str, tool: str, params: dict) -> Decision:
        rule = self.rules.get((agent_id, tool))
        if not rule:
            return Decision.BLOCKED  # Default deny
        
        if rule["policy"] == "allow":
            return Decision.ALLOWED
        elif rule["policy"] == "require_approval":
            return Decision.NEEDS_APPROVAL
        elif rule["policy"] == "conditional":
            # Check conditions (e.g., order size < max, position limit not exceeded)
            return Decision.ALLOWED if self._check_conditions(params, rule["conditions"]) else Decision.BLOCKED

# Example policies
policy = ToolPolicy()
policy.add_rule("signal_scanner", "fetch_ohlcv", "allow")
policy.add_rule("signal_scanner", "place_order", "blocked")  # Signal agents can NEVER place orders
policy.add_rule("execution_agent", "place_order", "conditional", {
    "max_order_value_usd": 50000,
    "max_position_pct": 0.05,
    "require_risk_approval": True
})
```

### 2.4 Multi-Agent Routing

**What it does:** OpenClaw supports routing messages to different agents based on context. The gateway resolves which agent handles which message. Supports sub-agent spawning for parallel workstreams.

**Why useful for trading:**
- Route "analyze AAPL earnings" to the fundamental analysis agent
- Route "what's the RSI on BTC" to the technical analysis agent
- Route "reduce my AAPL position by 50%" to the execution agent (with risk gate)
- Sub-agent spawning: "scan all S&P 500 for momentum signals" spawns 10 parallel sub-agents

**Rating:** ⭐ MUST HAVE

### 2.5 Hook System

**What it does:** OpenClaw has a hook system (`src/agents/agent-hooks/`) for intercepting agent behavior. Hooks can run before/after tool calls, during compaction, and at context assembly time.

**Why useful for trading:**
- Pre-trade hook: verify risk limits before any order
- Post-trade hook: update portfolio state, send alerts
- Compaction hook: ensure key trading decisions are never compacted away
- Context assembly hook: always inject current portfolio state and market hours

**Rating:** ⭐ MUST HAVE

### 2.6 Channel Adapters

**What it does:** OpenClaw has pluggable channel adapters for Telegram, Discord, Slack, WhatsApp, Signal, etc. Each adapter handles authentication, inbound message parsing, access control, and outbound message formatting.

**Why useful for trading:**
- Get trade alerts on Telegram while monitoring via Discord
- Accept trade commands from multiple channels with authentication
- Different channels for different purposes: Telegram for alerts, Discord for strategy discussion, API for automated signals

**Rating:** 🔷 NICE TO HAVE (for v1, single channel is fine)

### 2.7 Memory Architecture (File-Based + SQLite Index)

**What it does:** OpenClaw stores memory in human-editable Markdown files (`MEMORY.md`, `memory/YYYY-MM-DD.md`). Files are indexed into SQLite with FTS5 keyword search + optional vector embeddings. Three memory backends: Builtin (SQLite), QMD (local sidecar with reranking), Honcho (plugin).

**Why useful for trading:**
- Human-editable memory means a trader can directly modify what the agent "knows"
- Daily memory files create a natural trade journal
- FTS5 search: "find all trades where I used mean-reversion strategy in crypto"
- Vector embeddings: semantic search for similar market conditions

**Rating:** 🔷 NICE TO HAVE (simpler than Hermes' learning loop but still useful)

---

## 3. Hermes (NousResearch, ~190K Stars)

**What it is:** A self-improving personal AI agent runtime. Built in Python by Nous Research. Bet: the hard problem is memory and self-improvement. The only major agent with a closed learning loop.

### 3.1 Closed Learning Loop

**What it does:** Hermes' central abstraction is the "learning loop" — an agent that gets more capable the longer it runs. It creates skills from experience, improves them during use, nudges itself to persist knowledge, and builds a deepening model of the user across sessions. Every 15 turns, the agent is nudged to consider creating a skill from what it's learned.

**Why useful for trading:**
- **This is the single most valuable pattern for trading.** After 100 trades, the agent should know that "BTC tends to dump on CPI print days" — without being told
- Strategy evolution: if a momentum strategy keeps losing on choppy days, the agent should learn to add a regime filter
- Self-improving execution: the agent learns that "market orders on low-liquidity alts have 2% slippage" and switches to limit orders
- Automatic skill creation: after successfully backtesting a strategy, the agent creates a reusable "backtest strategy" skill

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```python
class TradingLearningLoop:
    def __init__(self):
        self.trade_journal = []
        self.learned_patterns = []
        self.skills = {}
        self.nudge_interval = 50  # Every 50 trades, reflect
    
    async def record_trade(self, trade: Trade, outcome: TradeOutcome):
        self.trade_journal.append({"trade": trade, "outcome": outcome, "timestamp": now()})
        
        if len(self.trade_journal) % self.nudge_interval == 0:
            await self.reflect_and_learn()
    
    async def reflect_and_learn(self):
        """Analyze recent trades and extract learnings"""
        recent = self.trade_journal[-self.nudge_interval:]
        
        # Ask the LLM to analyze patterns
        analysis = await self.llm.chat([
            {"role": "system", "content": "Analyze these trades and identify patterns, "
             "mistakes, and opportunities for improvement. Create skills if applicable."},
            {"role": "user", "content": self._format_trades(recent)}
        ])
        
        # Extract learnings
        learnings = self._parse_learnings(analysis)
        for learning in learnings:
            if learning.type == "pattern":
                self.learned_patterns.append(learning)
            elif learning.type == "skill":
                self.skills[learning.name] = learning.code
            elif learning.type == "rule":
                self.add_trading_rule(learning.rule)
    
    def get_context_for_decision(self, market_state: dict) -> str:
        """Inject learned patterns into decision context"""
        relevant_patterns = self._find_relevant_patterns(market_state)
        return "\n".join(f"- {p.description}" for p in relevant_patterns)
```

### 3.2 Autonomous Skill Creation

**What it does:** After completing complex tasks, Hermes nudges itself to create reusable skills. Skills are stored as `SKILL.md` files with metadata, instructions, and examples. Skills self-improve during use — if a skill fails, the agent updates it.

**Why useful for trading:**
- After manually calculating position size three times, the agent creates a "position sizing" skill
- After successfully identifying a head-and-shoulders pattern, it creates a "chart pattern recognition" skill
- Skills improve: if the "mean reversion entry" skill has a 40% win rate, the agent adds filters until it improves
- Portable: skills can be shared between trading agents

**Rating:** ⭐ MUST HAVE

### 3.3 Bounded Memory with Forced Prioritization

**What it does:** Hermes enforces hard character limits on memory (2,200 chars for agent memory, 1,375 for user profile). When memory is full, the agent must consolidate or replace entries. This forces the agent to be deliberate about what it keeps.

**Why useful for trading:**
- Prevents "memory bloat" — a trading agent accumulating thousands of minor observations
- Forces the agent to prioritize: "AAPL has a 70% win rate on earnings plays" survives; "I checked AAPL price at 3pm" doesn't
- Keeps the system prompt focused on what matters for current decisions
- Hard budget = predictable token costs

**Rating:** ⭐ MUST HAVE

**Implementation from scratch:**
```python
class BoundedMemory:
    def __init__(self, max_chars: int = 2200):
        self.max_chars = max_chars
        self.entries = []
    
    def add(self, entry: str):
        self.entries.append(entry)
        if self.total_chars() > self.max_chars:
            self.consolidate()
    
    def consolidate(self):
        """Use LLM to consolidate entries, keeping the most important ones"""
        prompt = f"""You have {self.max_chars} characters of memory space.
Current entries: {self.entries}
Keep only the most important trading-relevant information.
Discard redundant, outdated, or low-value entries.
Output the consolidated memory."""
        self.entries = [self.llm.chat(prompt)]
```

### 3.4 FTS5 Cross-Session Search with LLM Summarization

**What it does:** Hermes stores all session history in SQLite with FTS5 full-text search. The `session_search` tool searches across all past conversations and returns LLM-summarized results.

**Why useful for trading:**
- "Find all times I traded during FOMC announcements" → get summarized lessons
- "What happened last time BTC broke below its 200-day MA?" → instant recall
- Strategy backtesting: search for similar market conditions in past sessions
- Pattern matching: "when did I see this exact setup before?"

**Rating:** ⭐ MUST HAVE

### 3.5 Multiple Sandbox Backends

**What it does:** Hermes supports 5 execution backends: local, Docker, SSH, Singularity, Modal. Serverless options (Daytona, Modal) hibernate when idle.

**Why useful for trading:**
- Local: for development and testing
- Docker: for production strategy execution with isolation
- SSH: for running on a low-latency VPS near the exchange
- Modal/Daytona: for burst backtesting (spin up 100 containers, run backtests, shut down)

**Rating:** 🔷 NICE TO HAVE

### 3.6 Subagent Spawning

**What it does:** Hermes can spawn isolated subagents for parallel workstreams. Programmatic tool calling via `execute_code` collapses multi-step pipelines into single inference calls.

**Why useful for trading:**
- "Scan all 500 S&P stocks for RSI < 30" → spawn 50 sub-agents, each scanning 10 stocks
- Parallel backtesting: test 20 strategy variations simultaneously
- Each subagent is isolated — one crashing doesn't affect others

**Rating:** ⭐ MUST HAVE

### 3.7 Atropos RL Integration

**What it does:** Hermes integrates with Atropos RL environments for reinforcement learning. Supports batch trajectory generation and RL training. The `rl_training_tool.py` and `batch_runner.py` enable training models on agent trajectories.

**Why useful for trading:**
- Train a model on your actual trading decisions and outcomes
- RL reward = portfolio return (with risk penalties)
- Generate training data from successful trading sessions
- Continuously improve the trading model based on real market feedback

**Rating:** 🔷 NICE TO HAVE (advanced, for later phases)

---

## 4. Other Emerging Systems

### 4.1 CrewAI — Role-Based Agent Teams

**What it does:** CrewAI organizes agents into "crews" with defined roles (e.g., Researcher, Writer, Editor). Each agent has a role, goal, and backstory. Tasks are assigned to agents based on their roles. Supports sequential and parallel task execution.

**Trading patterns worth extracting:**

| Pattern | Description | Trading Value | Rating |
|---------|-------------|---------------|--------|
| Role-based agents | Define agents by their trading role (Analyst, Risk Manager, Executor, Journalist) | Natural mapping to trading desk structure | ⭐ MUST HAVE |
| Task delegation | Agents delegate tasks they can't handle to other agents | Signal agent delegates "verify news impact" to sentiment agent | ⭐ MUST HAVE |
| Sequential workflows | Tasks execute in order with output flowing forward | Data → Signal → Risk → Size → Execute pipeline | ⭐ MUST HAVE |
| Crew memory | Shared memory within a crew | All agents in a strategy share current position state | 🔷 NICE TO HAVE |

**Implementation:**
```python
class TradingCrew:
    def __init__(self):
        self.agents = {
            "analyst": AnalystAgent(),
            "risk_manager": RiskManagerAgent(),
            "executor": ExecutorAgent(),
            "journalist": JournalistAgent()  # Writes trade reports
        }
    
    async def run_pipeline(self, market_data):
        # Sequential: Analyst → Risk → Executor → Journalist
        signals = await self.agents["analyst"].analyze(market_data)
        approved = await self.agents["risk_manager"].review(signals)
        trades = await self.agents["executor"].execute(approved)
        report = await self.agents["journalist"].document(trades)
        return report
```

### 4.2 AutoGen (Microsoft) — Conversation-Based Multi-Agent

**What it does:** AutoGen uses conversation between agents as the coordination mechanism. Agents "talk" to each other to solve problems. Supports human-in-the-loop, code execution, and nested conversations.

**Trading patterns worth extracting:**

| Pattern | Description | Trading Value | Rating |
|---------|-------------|---------------|--------|
| Agent conversation | Agents negotiate through dialogue | Bull agent and Bear agent debate before trade decision | 🔷 NICE TO HAVE |
| Human-in-the-loop | Human can intervene at any point in the conversation | Trader approves/rejects proposed trades | ⭐ MUST HAVE |
| Nested conversations | Sub-conversations for complex sub-tasks | Risk assessment spawns a sub-conversation for volatility analysis | 🔷 NICE TO HAVE |
| Code execution in conversation | Agents can write and execute code during conversation | Agent writes custom indicator code on the fly | 🔷 NICE TO HAVE |

### 4.3 MetaGPT — Software Company Metaphor

**What it does:** MetaGPT models agents as a software company: Product Manager, Architect, Engineer, QA. Uses Standardized Operating Procedures (SOPs) to structure workflows. Outputs structured artifacts (PRDs, design docs, code).

**Trading patterns worth extracting:**

| Pattern | Description | Trading Value | Rating |
|---------|-------------|---------------|--------|
| SOPs for workflows | Standardized procedures for each stage | Trading SOP: signal must pass checklist before execution | ⭐ MUST HAVE |
| Structured artifacts | Each agent produces well-defined output formats | Signal report format, risk assessment template, trade ticket | ⭐ MUST HAVE |
| Role specialization | Deep specialization per role | Separate agents for equities, crypto, forex, options | 🔷 NICE TO HAVE |
| Quality gates | QA agent reviews all outputs before proceeding | Review agent checks every trade signal for consistency | ⭐ MUST HAVE |

### 4.4 LangGraph — Graph-Based Orchestration

**What it does:** LangGraph (LangChain) provides a framework for building agent workflows as state graphs. Nodes are functions/agents, edges are transitions. Supports cycles, conditional branching, human-in-the-loop, and persistence.

**Trading patterns worth extracting:**

| Pattern | Description | Trading Value | Rating |
|---------|-------------|---------------|--------|
| State graphs | Model trading workflow as a state machine | Clear states: SCANNING → SIGNAL_GENERATED → RISK_CHECK → EXECUTING → FILLED | ⭐ MUST HAVE |
| Conditional branching | Different paths based on conditions | If volatility > threshold → use conservative sizing; else → normal | ⭐ MUST HAVE |
| Cycles | Loops in the graph | Retry loop: if order rejected, adjust price and retry (max 3 times) | ⭐ MUST HAVE |
| Checkpointing | Save and restore graph state | Resume trading after crash from last checkpoint | ⭐ MUST HAVE |
| Human-in-the-loop | Pause graph execution for human input | Pause before large orders for manual approval | ⭐ MUST HAVE |

**Implementation:**
```python
from enum import Enum

class TradingState(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    SIGNAL_GENERATED = "signal_generated"
    RISK_CHECK = "risk_check"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    SIZING = "sizing"
    EXECUTING = "executing"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    POST_TRADE = "post_trade"

class TradingStateMachine:
    def __init__(self):
        self.transitions = {
            (TradingState.IDLE, "market_data"): TradingState.SCANNING,
            (TradingState.SCANNING, "signal_found"): TradingState.SIGNAL_GENERATED,
            (TradingState.SIGNAL_GENERATED, "submit"): TradingState.RISK_CHECK,
            (TradingState.RISK_CHECK, "approved"): TradingState.RISK_APPROVED,
            (TradingState.RISK_CHECK, "rejected"): TradingState.RISK_REJECTED,
            (TradingState.RISK_APPROVED, "size_calculated"): TradingState.SIZING,
            (TradingState.SIZING, "execute"): TradingState.EXECUTING,
            (TradingState.EXECUTING, "filled"): TradingState.FILLED,
            (TradingState.EXECUTING, "partial"): TradingState.PARTIALLY_FILLED,
            (TradingState.EXECUTING, "rejected"): TradingState.REJECTED,
            (TradingState.REJECTED, "retry"): TradingState.EXECUTING,  # Cycle!
            (TradingState.FILLED, "log"): TradingState.POST_TRADE,
            (TradingState.POST_TRADE, "complete"): TradingState.IDLE,
        }
        self.state = TradingState.IDLE
        self.checkpoints = []
    
    def transition(self, event: str):
        key = (self.state, event)
        if key in self.transitions:
            old_state = self.state
            self.state = self.transitions[key]
            self.checkpoints.append({"from": old_state, "to": self.state, "time": now()})
```

### 4.5 Custom Loop Systems — Self-Improving Patterns

**What's emerging in the ecosystem:**

#### 4.5.1 Reflection Cycles
**What it does:** After each major action, the agent reflects on the outcome and adjusts. "I expected AAPL to go up based on earnings, but it went down. What did I miss? The market was in a risk-off regime."

**Trading value:** Prevents repeating mistakes. ⭐ MUST HAVE

#### 4.5.2 Strategy Evolution via Genetic Algorithms
**What it does:** Generate N strategy variants, backtest them, keep the top performers, mutate and cross-breed, repeat.

**Trading value:** Automated strategy discovery. 🔷 NICE TO HAVE

#### 4.5.3 Market Regime Detection & Adaptation
**What it does:** Agent detects regime changes (trending → ranging → volatile) and switches strategy accordingly.

**Trading value:** Critical for survival. ⭐ MUST HAVE

```python
class RegimeDetector:
    REGIMES = ["trending_up", "trending_down", "ranging", "high_volatility", "low_volatility"]
    
    async def detect(self, market_data: pd.DataFrame) -> str:
        # Use multiple indicators
        atr = self._calculate_atr(market_data)
        adx = self._calculate_adx(market_data)
        hurst = self._calculate_hurst(market_data)
        
        # Ask LLM to synthesize
        prompt = f"""Given these market indicators:
        - ATR (normalized): {atr:.2f}
        - ADX: {adx:.2f}  
        - Hurst exponent: {hurst:.2f}
        - Recent price action: {self._summarize_price(market_data)}
        
        What market regime are we in? Choose from: {self.REGIMES}"""
        
        return await self.llm.chat(prompt)
```

#### 4.5.4 Multi-Timeframe Synthesis
**What it does:** Agent analyzes multiple timeframes (1m, 5m, 1h, 4h, 1D) and synthesizes a coherent view.

**Trading value:** Reduces false signals. ⭐ MUST HAVE

---

## 5. Cross-Cutting Patterns: Loop Systems & Self-Improvement

### 5.1 The Trading-Specific Learning Loop

Combining the best of Hermes' learning loop with trading-specific needs:

```
┌─────────────────────────────────────────────────────────────┐
│                    TRADING LEARNING LOOP                      │
│                                                               │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌────────┐ │
│  │ Observe  │───▶│  Decide  │───▶│  Execute │───▶│Reflect │ │
│  │  Market  │    │  Signal  │    │   Trade  │    │& Learn │ │
│  └──────────┘    └──────────┘    └──────────┘    └────────┘ │
│       ▲                                              │       │
│       │              ┌──────────┐                    │       │
│       │              │  Memory  │◀───────────────────┘       │
│       │              │  Update  │                            │
│       │              └──────────┘                            │
│       │                    │                                 │
│       └────────────────────┘                                 │
│         (informed by learned patterns)                       │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Self-Improving Strategy Patterns

| Pattern | Description | Implementation | Rating |
|---------|-------------|----------------|--------|
| **Trade Journal Auto-Summary** | After each trade, auto-generate a structured journal entry with entry/exit reasons, outcome, lessons | Hermes-style periodic nudge, summarize every 10 trades | ⭐ MUST HAVE |
| **Win Rate Tracking by Setup** | Track win rate per strategy/setup type, auto-deprecate low performers | SQLite schema with strategy_id, win_count, loss_count | ⭐ MUST HAVE |
| **Parameter Auto-Tuning** | Adjust strategy parameters based on recent performance (e.g., tighten stops if recent drawdown) | Bounded optimization with hard limits | 🔷 NICE TO HAVE |
| **Strategy Retirement** | Automatically retire strategies that underperform for N consecutive periods | State machine: ACTIVE → PROBATION → RETIRED | ⭐ MUST HAVE |
| **Cross-Session Pattern Memory** | Remember patterns across sessions: "Every time CPI comes in hot, crypto dumps for 2 hours" | FTS5 indexed pattern database | ⭐ MUST HAVE |
| **Regime-Strategy Mapping** | Learn which strategies work in which regimes | Decision tree: regime → best strategy set | ⭐ MUST HAVE |

### 5.3 Reflection Cycle Implementation

```python
class TradingReflectionCycle:
    """Runs after each trading session or on a schedule"""
    
    async def daily_reflection(self, today_trades: list[Trade]):
        # 1. Performance analysis
        stats = self._calculate_stats(today_trades)
        
        # 2. Pattern detection
        patterns = await self.llm.chat(f"""
        Analyze today's {len(today_trades)} trades.
        Win rate: {stats.win_rate:.1%}
        P&L: ${stats.pnl:.2f}
        Max drawdown: ${stats.max_drawdown:.2f}
        
        Identify:
        1. What worked and why
        2. What failed and why
        3. Any market patterns you noticed
        4. Suggested adjustments for tomorrow
        """)
        
        # 3. Update memory
        self.memory.add(f"Daily reflection {today()}: {patterns}")
        
        # 4. Update strategy parameters if needed
        if stats.win_rate < 0.4 and stats.trade_count > 10:
            await self.suggest_parameter_adjustment(stats)
        
        # 5. Create/update skills if novel pattern found
        if patterns.has_novel_insight:
            await self.create_skill_from_insight(patterns.novel_insight)
```

---

## 6. Priority Implementation Roadmap

### Phase 1: Foundation (Weeks 1-4) — MUST HAVE Patterns

1. **Gateway Architecture** (from OpenClaw)
   - Risk firewall, kill switch, audit logging
   - Session isolation per strategy

2. **State Machine Orchestration** (from LangGraph)
   - Trading workflow as a state graph
   - Checkpointing for crash recovery
   - Conditional branching for risk decisions

3. **Tool Policy & Approval System** (from OpenClaw)
   - Default-deny for all execution tools
   - Risk gate before every order
   - Per-agent permission scoping

4. **Skill System** (from DeerFlow)
   - Modular, versioned trading skills
   - Skill testing framework

5. **Bounded Memory** (from Hermes)
   - Hard memory limits with forced consolidation
   - Daily trade journal files

### Phase 2: Intelligence (Weeks 5-8) — MUST HAVE Patterns

6. **Learning Loop** (from Hermes)
   - Record all trades with outcomes
   - Periodic reflection and pattern extraction
   - Autonomous skill creation from successful patterns

7. **FTS5 Search** (from Hermes)
   - Index all trading sessions and decisions
   - Cross-session pattern recall

8. **Market Regime Detection**
   - Multi-indicator regime classification
   - Strategy-regime mapping

9. **Context Compaction** (from DeerFlow)
   - Token-efficient context management
   - Key decision preservation during compaction

10. **Model Routing** (from DeerFlow)
    - Task-appropriate model selection
    - Cost optimization

### Phase 3: Scale (Weeks 9-12) — NICE TO HAVE Patterns

11. **Sub-Agent Spawning** (from OpenClaw + Hermes)
    - Parallel signal scanning
    - Isolated backtesting

12. **Multi-Channel Alerts** (from OpenClaw)
    - Telegram for alerts, Discord for discussion, API for automation

13. **RL Training Loop** (from Hermes Atropos)
    - Train models on trading trajectories
    - Continuous improvement via reinforcement learning

14. **Strategy Evolution Engine**
    - Genetic algorithm for strategy discovery
    - Automated backtesting pipeline

15. **Cross-Agent Conversation** (from AutoGen)
    - Bull/Bear debate before trades
    - Multi-perspective analysis

---

## 7. Architecture Summary: The Trading Super Agent

```
┌──────────────────────────────────────────────────────────────────┐
│                     TRADING GATEWAY (from OpenClaw)               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ Telegram │  │ Discord  │  │   API    │  │   Web Dashboard  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘ │
│       └──────────────┴─────────────┴─────────────────┘           │
│                          │                                        │
│  ┌───────────────────────┴────────────────────────────────────┐  │
│  │              Session Manager & Router                       │  │
│  │  • Kill Switch  • Audit Log  • Access Control              │  │
│  └───────────────────────┬────────────────────────────────────┘  │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│                   ORCHESTRATOR (from LangGraph)                   │
│  ┌───────────────────────┴────────────────────────────────────┐  │
│  │                 State Machine / DAG                         │  │
│  │  IDLE → SCANNING → SIGNAL → RISK → SIZING → EXEC → LOG   │  │
│  └───────────────────────┬────────────────────────────────────┘  │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│                    AGENT LAYER (from DeerFlow)                    │
│                                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │  Data    │ │  Signal  │ │  Risk    │ │Execution │            │
│  │  Agent   │ │  Agents  │ │  Agent   │ │  Agent   │            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Sentiment│ │  Regime  │ │ Sizing   │ │ Journal  │            │
│  │  Agent   │ │ Detector │ │  Agent   │ │  Agent   │            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│                   SKILL LAYER (from DeerFlow + Hermes)            │
│                                                                   │
│  Skills: fetch_ohlcv | calculate_rsi | place_order | backtest   │
│          check_exposure | detect_regime | size_position          │
│                                                                   │
│  Auto-created: pattern_X_entry | earnings_play | gap_fill        │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│                   MEMORY & LEARNING (from Hermes)                 │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Bounded      │  │ FTS5 Session │  │ Learning Loop        │   │
│  │ Memory       │  │ Search       │  │ • Trade journal      │   │
│  │ (MEMORY.md)  │  │ (SQLite)     │  │ • Pattern extraction │   │
│  └──────────────┘  └──────────────┘  │ • Skill creation     │   │
│                                       │ • Strategy evolution │   │
│                                       └──────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│                 SANDBOX LAYER (from DeerFlow + Hermes)            │
│                                                                   │
│  Docker containers per agent role with:                           │
│  • Network isolation (data ≠ execution ≠ analysis)               │
│  • Resource limits (CPU, memory, time)                            │
│  • Filesystem isolation                                           │
│  • Tool approval gates                                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 8. Key Takeaways

1. **Gateway-first is non-negotiable for trading.** The gateway is your risk firewall, audit log, and kill switch. Steal OpenClaw's architecture wholesale.

2. **The learning loop is the single biggest differentiator.** Hermes' pattern of autonomous skill creation and self-improvement is exactly what separates a static trading bot from a super agent that gets better over time.

3. **Tool policy is your safety net.** OpenClaw's default-deny, approval-required, conditional-access pattern for tools must be the foundation of any trading system that touches real money.

4. **State machines > free-form agents.** Trading workflows are inherently stateful. LangGraph's state graph pattern with checkpointing is the right abstraction.

5. **Bounded memory prevents hallucination drift.** Hermes' hard memory limits force the agent to remember what matters and forget what doesn't — critical when the agent is making financial decisions.

6. **Skills are the compositional unit.** Both DeerFlow and Hermes converge on skills as the fundamental building block. Trading skills should be versioned, tested, and auditable.

7. **Model routing saves money and improves quality.** Not every decision needs GPT-4o. Route simple tasks to fast/cheap models, complex analysis to powerful ones.

8. **Don't fork — implement from scratch.** These frameworks solve general problems. Trading has specific constraints (latency, safety, auditability) that require purpose-built implementations informed by these patterns.

---

*Report generated from research on DeerFlow 2.0, OpenClaw, Hermes Agent, CrewAI, AutoGen, MetaGPT, LangGraph, and broader agent ecosystem patterns as of July 2026.*
