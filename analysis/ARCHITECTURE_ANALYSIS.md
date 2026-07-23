# TSAR Architecture Comprehensive Analysis

**Date:** 2026-07-24  
**Scope:** All files in `docs/architecture/` (17 files) and `docs/reviews/` (3 files)  
**Total documents analyzed:** 20  
**Total specification volume:** ~800KB+

---

## Table of Contents

1. [Per-Document Analysis](#1-per-document-analysis)
2. [Architecture Completeness Assessment](#2-architecture-completeness-assessment)
3. [Dependency Map](#3-dependency-map)
4. [Day 1 Build Readiness](#4-day-1-build-readiness)
5. [Risk Register](#5-risk-register)
6. [Recommended Build Order](#6-recommended-build-order)

---

## 1. Per-Document Analysis

### 1.1 `ARCHITECTURE_COMPLETE.md`

**What it specifies:** Status summary of the entire architecture phase — 9 architecture agents delivered ~500KB+ of specs. Lists all deliverables (8 sub-agents, 5 knowledge stores, 35 tools, 131 files, Docker/CI/CD). Contains the gap resolution summary (5 critical gaps fixed, 8 contradictions resolved) and the Day1 architecture overview (3 agents, 10 tools, 1 DB, 1 strategy).

**Key design decisions:**
- Day1 simplification: 3 agents instead of 8, 10 tools instead of 35
- Forward demo trading on Binance testnet before live
- Free models only (Ollama Qwen2.5-7B + DeepSeek-R1 via NVIDIA NIM)
- Week-by-week 4-week build plan

**Dependencies on other docs:** References ARCHITECTURE_CONSOLIDATION.md, DAY1_ARCHITECTURE.md, all layer specs. Acts as the executive summary / index.

**Engineering implications:** Provides the high-level build plan. Engineers should use this as the entry point but drill into specific layer docs for implementation details.

**Gaps/ambiguities:** 
- References "131 files, full project structure" from TECH_STACK but doesn't enumerate them
- Week-by-week plan is high-level — no task-level granularity
- "Level 2/3/4" upgrade triggers are described qualitatively, not as measurable gates

---

### 1.2 `ARCHITECTURE_CONSOLIDATION.md`

**What it specifies:** The SINGLE SOURCE OF TRUTH for all canonical values. Resolves all contradictions between prior documents. Defines: stream prefix (`tsar:`), message format (MessagePack), database (1 unified `tsar.db`), risk limits (-2% daily loss, 10 max positions, Half-Kelly), ports (8000=FastAPI, 8001=Supervisor), tech versions (Rust 1.79, Python 3.12), tool permission roles (5-tier), and Celery removal.

**Key design decisions:**
- `tsar:` prefix for ALL Redis keys (not `trading:`)
- 1 unified SQLite DB with table prefixes (not 4 separate DBs)
- -2% daily loss kill switch (conservative for $10)
- 10 max open positions (not 20)
- Celery removed; Redis Streams replaces it
- FastAPI on port 8000, Supervisor on 8001

**Dependencies on other docs:** Supersedes conflicting values in ALL other docs. Every engineering file must reference this document for canonical values.

**Engineering implications:** All config files, Redis key references, database names, and port assignments must match these canonical values. Any code using `trading:*` prefixes or `trading.db` must be updated.

**Gaps/ambiguities:**
- Document update checklist (Section 4) lists what needs updating but doesn't confirm it was done
- Paper trading engine code is provided but marked as "implementation guidance" — unclear if this is spec or code
- Appendix B glossary is helpful but incomplete (missing several acronyms used in other docs)

---

### 1.3 `COMPLIANCE_LAYER.md`

**What it specifies:** Regulatory-grade compliance infrastructure across 4 implementation levels. Covers: immutable audit log (SHA-256 hash chain), trade reporting (daily/weekly/monthly), record keeping (7-year retention), position reconciliation (5-min frequency), counterparty risk monitoring (exchange health scoring), and compliance gate (pre-trade/post-trade checks).

**Key design decisions:**
- 3-layer audit trail: SQLite (queryable) → JSONL hash chain (immutable) → S3 object lock (true immutability)
- Position reconciliation every 5 minutes with 0.01% tolerance
- Counterparty risk scoring from 0-100 with graduated exposure limits
- Day1: file-based audit log; Level 3+: PostgreSQL + S3

**Dependencies on other docs:** References RISK_ARCHITECTURE.md for risk limits, DATA_ARCHITECTURE.md for trade schema, DEPLOYMENT.md for backup procedures.

**Engineering implications:** Day1 needs only basic file-based audit logging. Full compliance is Level 3+. The reconciliation pipeline needs exchange API integration. Counterparty risk monitoring needs periodic health checks.

**Gaps/ambiguities:**
- PostgreSQL mentioned for audit log storage but no PostgreSQL is in the tech stack (SQLite + Redis only)
- "Blockchain anchor" for timestamps is mentioned but no implementation spec
- Compliance gate code references `self.position_store`, `self.trading_engine` — undefined interfaces
- Record retention table says 7 years for trades but no cold storage migration procedure for SQLite

---

### 1.4 `DATA_ARCHITECTURE.md`

**What it specifies:** The complete data layer — 5 knowledge stores with full SQL schemas, Redis key design (80+ key patterns), FTS5 search configuration, vector embedding pipeline (ChromaDB), data compaction rules, backup/recovery strategy, and cross-cutting concerns (concurrency, learning loop, risk governor data access). This is the most detailed single document in the architecture.

**Key design decisions:**
- 5 knowledge stores: Trade Memory, Strategy Genomes, Pattern Library, Lesson Archive, Regime State
- SQLite WAL mode with 64MB cache, 256MB mmap
- Rust WAL buffer → Python compaction → SQLite (dual-language write path)
- ChromaDB for vector similarity search (optional for v1)
- FTS5 full-text search on lessons, trade theses, pattern descriptions
- Session memory: 3-layer architecture (hot < 2K tokens, warm < 8K, cold = DB queries)

**Dependencies on other docs:** Foundation for all agents — every agent reads/writes to these stores. References TECH_STACK for technology versions.

**Engineering implications:** This is the largest build effort. The 5 SQL schemas are complete and can be directly translated to migration scripts. The Redis key design is comprehensive (80+ patterns). The Rust WAL → Python compaction pipeline requires careful implementation. FTS5 indexes need trigger setup.

**Gaps/ambiguities:**
- **CRITICAL:** Specifies 4 separate SQLite databases (`trades.db`, `strategies.db`, `patterns.db`, `lessons.db`) — contradicts ARCHITECTURE_CONSOLIDATION.md which canonizes 1 unified `tsar.db`. The consolidation doc's table-prefix approach should be used.
- ChromaDB collection design is detailed but ChromaDB is marked optional for v1 — unclear which vector features to skip
- Rust WAL buffer implementation is described conceptually but no Rust code is provided
- Data compaction rules reference "weekly full VACUUM" but no cron/scheduler spec
- Backup strategy mentions S3/R2 but no cloud provider configuration

---

### 1.5 `DAY1_ARCHITECTURE.md`

**What it specifies:** The simplified, buildable-in-2-4-weeks version. 3 agents (Signal, Risk, Execution), 10 tools, 1 SQLite DB, 1 strategy (Mean Reversion on BTC/USDT), Telegram interface, Binance testnet integration. Complete with code samples for every component, project structure, requirements.txt, configuration, and week-by-week build plan.

**Key design decisions:**
- 3 agents only (not 8), each < 200 lines of Python
- 10 tools, each < 30 lines, thin wrappers around ccxt/pandas
- Mean Reversion strategy: RSI < 30 at support → buy, RSI > 70 at resistance → sell
- Risk: 5% max position, 2% risk per trade, -3% daily loss (NOTE: should be -2% per consolidation)
- Telegram bot with 8 commands: /start, /stop, /status, /pnl, /history, /lessons, /strategy_status, /risk
- ccxt sandbox mode for paper trading (simpler than custom PaperTradingEngine)

**Dependencies on other docs:** References ARCHITECTURE_CONSOLIDATION.md for canonical values. Self-contained — can be built without referencing other docs.

**Engineering implications:** This is the actual build spec for weeks 1-4. Every file in the project structure needs to be created. The code samples are implementation-ready. The requirements.txt lists 9 packages.

**Gaps/ambiguities:**
- Database name is `trading.db` but should be `tsar.db` per consolidation (minor fix)
- Daily loss limit is -3% but should be -2% per consolidation (minor fix)
- No `check_risk` tool implementation provided (only described)
- Learning loop (`learning_loop.py`) is described conceptually but no code provided
- No unit test specifications — just mentions "test everything end-to-end"
- Strategy performance targets (win rate > 55%, PF > 1.5) are stated but no measurement methodology

---

### 1.6 `DEPLOYMENT.md`

**What it specifies:** Full deployment and runtime architecture — Docker containers (5 services), CI/CD pipeline (GitHub Actions), Telegram bot integration (commands, approval flow, alerts), monitoring (Prometheus metrics, Grafana dashboards, alert rules), security (API key management, VPS hardening), kill switch architecture, backup/recovery, runtime configuration (hot-reload), and deployment procedures.

**Key design decisions:**
- 5 Docker containers: agent, executor, redis, bot, monitor
- GitHub Actions CI/CD with lint → test → build → deploy pipeline
- Prometheus metrics on port 9100 (agent) and 9101 (executor)
- Grafana dashboards: Trading Overview, System Health, Risk Monitor
- Kill switch: separate lightweight process, Redis-based flag, auto-flatten
- VPS hardening: UFW, fail2ban, SSH key-only, no root login
- 3-tier backup: hot (15 min), warm (daily), cold (weekly)

**Dependencies on other docs:** References TECH_STACK for container images, ARCHITECTURE_CONSOLIDATION.md for ports and config values.

**Engineering implications:** Docker Compose files are ready to use. CI/CD pipeline YAML is complete. Prometheus alert rules are defined. Kill switch implementation is production-quality. VPS hardening script is ready.

**Gaps/ambiguities:**
- Celery worker container is included but Celery was removed in consolidation — should be removed from docker-compose
- `DATABASE_PATH=/data/trading.db` should be `/data/tsar.db`
- No staging environment beyond single SSH deploy step
- Grafana dashboard JSON is a skeleton — not a complete dashboard
- Redis password management only in prod — dev has no auth
- No container resource limits defined for dev environment

---

### 1.7 `GAP_RESOLUTION.md`

**What it specifies:** Detailed resolution of all 21 gaps (12 critical + 9 important) identified in gap analyses. Each gap has: what was missing, how it's now implemented (with code), who owns it, and Day1 vs Full differentiation. Covers: backtesting engine, walk-forward validation, backup/recovery, strategy portfolio + allocation, VaR/stress testing, counterparty risk, data quality pipeline, strategy retirement gates, immutable audit log, sentiment analysis, economic calendar, multi-asset portfolio, and 9 important gaps.

**Key design decisions:**
- Backtesting: vectorbt library with fee-aware simulation
- Walk-forward: 70/15/15 train/val/test split, rolling monthly revalidation
- Strategy allocation: Risk Parity (default), Kelly-Based, Inverse Volatility
- VaR: Historical simulation, 95%/99% confidence
- Sentiment: Fear & Greed + CryptoPanic + LLM scoring
- Economic calendar: ForexFactory scraper + Redis cache

**Dependencies on other docs:** Cross-references ARCHITECTURE_CONSOLIDATION.md and DAY1_ARCHITECTURE.md. Each gap resolution references specific sections of the original architecture docs.

**Engineering implications:** Each gap resolution contains implementation code that can be directly used. The priority matrix (Section 4) defines build order. Day1 gaps are minimal (backup cron, benchmark tracking, notes field).

**Gaps/ambiguities:**
- Some code samples use undefined classes (e.g., `BacktestConfig`, `WalkForwardEngine`)
- "Level 2" and "Level 3" timelines are estimates, not gated on metrics
- Sentiment analysis relies on CryptoPanic free tier (100 req/day) — may be insufficient
- On-chain analytics code references CryptoQuant/Glassnode but free tiers are very limited

---

### 1.8 `GAP_RESOLUTION_MATRIX.md`

**What it specifies:** Complete tracking matrix of all 94 gaps across 6 categories (Coherence, Completeness, Scalability, Institutional, Super Agent, Institutional Coverage). Shows resolution status: 83 resolved, 11 deferred, 0 remaining. Maps each gap to its resolution location in TSAR_ARCHITECTURE.md.

**Key design decisions:**
- All gaps are either resolved or explicitly deferred with rationale
- 11 deferred items have documented revisit triggers
- Cross-reference table maps gap IDs to architecture sections

**Dependencies on other docs:** References TSAR_ARCHITECTURE.md as the canonical resolution document.

**Engineering implications:** This is the project backlog. The 11 deferred items should be tracked. The priority tiers (Tier 1 BLOCKING, Tier 2 PHASE 1, Tier 3 PHASE 2+) define implementation order.

**Gaps/ambiguities:**
- Some "resolved" items point to sections that contain spec but not implementation code
- Deferred items have "revisit when" triggers but no tracking mechanism
- No acceptance criteria for "resolved" — just presence of specification

---

### 1.9 `MARKET_ANALYSIS_LAYER.md`

**What it specifies:** The complete market analysis layer — 8 components: Macro Agent, Economic Calendar, Sentiment Analysis, On-Chain Analytics, Geopolitical Analysis, Cross-Asset Correlation, Order Flow Analysis, Seasonal Analysis. Each has full specification with data sources, scoring algorithms, implementation code, and Day1 vs Full comparison.

**Key design decisions:**
- Macro Agent: 5-indicator composite score (Fed stance 30%, inflation 20%, growth 20%, employment 15%, dollar 15%)
- Economic calendar: ForexFactory scraper, blackout rules for FOMC/CPI/NFP
- Sentiment: Fear & Greed (30%) + News LLM scoring (40%) + Social (30%)
- On-chain: 6 metrics (exchange flow, whale activity, MVRV, stablecoin supply, funding rates, network activity)
- Cross-asset: BTC↔DXY, BTC↔Gold, BTC↔VIX, BTC↔S&P correlations
- Order flow: Book imbalance, volume delta, CVD divergence
- Seasonal: Learned from trade history (not hardcoded)

**Dependencies on other docs:** Extends existing agents in trading-super-agent-spec.md. Adds streams to Redis topology. References RISK_ARCHITECTURE.md for blackout enforcement.

**Engineering implications:** Day1 gets only Fear & Greed + DXY direction (inline in Signal Agent). Level 2 adds Macro Agent + full sentiment + calendar. Level 3 adds on-chain + order flow + geopolitical. Each component has complete Python code.

**Gaps/ambiguities:**
- Data sources catalog lists 15+ free APIs but rate limits are tight (e.g., CryptoPanic 100/day)
- ForexFactory HTML scraping may break if they change their page structure
- On-chain metrics code references APIs that may require paid tiers for useful data
- Order flow analysis needs WebSocket — not available in Day1 REST-only architecture

---

### 1.10 `OPERATIONS_LAYER.md`

**What it specifies:** Operations layer covering backup/recovery, real-time monitoring, log aggregation, data quality pipeline, alerting, and deployment automation. Defines RTO/RPO targets, Prometheus metrics, Grafana dashboards, alert rules, structured logging format, and health check endpoints.

**Key design decisions:**
- 3-tier backup: hot (1 min portfolio state), warm (daily full), cold (weekly compressed)
- Prometheus metrics for trading, strategy, and system health
- Structured JSON logging with 4 severity levels
- Alert routing: CRITICAL → Telegram + SMS, WARNING → Telegram, INFO → Grafana
- Health check: `/health` (basic), `/health/ready` (readiness), `/health/detailed` (full)

**Dependencies on other docs:** References DEPLOYMENT.md for Docker setup, DATA_ARCHITECTURE.md for data pipeline.

**Engineering implications:** Prometheus metrics and alert rules are YAML-ready. Health check endpoints are Python-ready. Backup script is bash-ready. Day1 needs only basic logging + Telegram alerts.

**Gaps/ambiguities:**
- RTO targets (< 30s for crash, < 5 min for corruption) are ambitious for SQLite
- Log aggregation mentions Elasticsearch/Loki but these aren't in the tech stack
- Grafana dashboard JSON is a text description, not actual JSON
- No log rotation configuration for the file-based Day1 implementation

---

### 1.11 `PORTFOLIO_LAYER.md`

**What it specifies:** Multi-asset portfolio management — asset class definitions (crypto, forex, gold), portfolio manager, cross-asset correlation, exchange adapters (Binance + OANDA), rebalancing engine, performance attribution, benchmark comparison, and portfolio risk metrics (VaR, stress testing).

**Key design decisions:**
- Asset classes: Crypto (Binance), Forex (OANDA), Gold (OANDA)
- Rebalancing triggers: weekly schedule, 5% drift threshold, regime change, strategy change, drawdown
- Allocation methods: Risk Parity (default), Kelly, Inverse Volatility, Adaptive
- Performance attribution: by strategy, asset, asset class, regime, hour, day-of-week, exit reason
- Benchmark: Buy-and-hold BTC, alpha calculation, information ratio

**Dependencies on other docs:** References STRATEGY_LAYER.md for strategy allocation, RISK_ARCHITECTURE.md for risk limits, DATA_ARCHITECTURE.md for schemas.

**Engineering implications:** Day1 is BTC-only, so most of this is Level 3+. The OANDA adapter code is provided. The rebalancing engine is complex — needs careful testing. Attribution views are SQL-ready.

**Gaps/ambiguities:**
- OANDA adapter code uses `requests` (sync) but the rest of the system is async
- Rebalancing "approval" flow mentions Telegram but no implementation
- Portfolio risk metrics reference `ASSET_SPECS` dict that's defined in the same file but not imported
- No currency conversion logic for multi-currency portfolios

---

### 1.12 `RISK_ARCHITECTURE.md`

**What it specifies:** The complete Risk Governor — the most critical component. Covers: position sizing (Half-Kelly), drawdown circuit breakers (4 levels: Green/Yellow/Orange/Red), anti-behavioral guards (revenge, greed, FOMO, overconfidence), correlation monitoring, time-based risk rules (economic calendar, weekend, funding rate), kill switch (separate process), veto protocol (9-gate evaluation), check cadence, Redis state schema, and full Python implementation.

**Key design decisions:**
- Half-Kelly position sizing with 2% hard cap
- 4-level drawdown circuit breakers with progressive responses
- Anti-revenge: 3 consecutive losses → 60-min cooldown
- Anti-greed: 5+ win streak → 70% sizing
- Anti-FOMO: only registered setup types allowed
- Kill switch: separate process, Redis-based, auto-flatten
- Veto protocol: 9 gates, cheapest-first ordering, < 100ms total
- Configuration immutable at runtime (requires restart to change)

**Dependencies on other docs:** Foundation for all trading decisions. References DATA_ARCHITECTURE.md for Redis key design.

**Engineering implications:** This is the most important module to build correctly. The veto protocol code is implementation-ready. The Redis state schema is complete. The anti-behavioral guards are unique and valuable. The kill switch must be a separate process.

**Gaps/ambiguities:**
- Drawdown thresholds in this doc (-4% daily kill) conflict with consolidation (-2%) — consolidation wins
- Max positions 20 in this doc conflicts with consolidation (10) — consolidation wins
- Kelly calculation assumes historical win rate/avg win/avg loss — where do these come from initially?
- Correlation monitor needs 60 periods of returns data — cold start problem
- Economic calendar integration references `EconomicCalendar` class but no implementation

---

### 1.13 `STRATEGY_LAYER.md`

**What it specifies:** Complete strategy layer — backtesting engine (vectorbt), walk-forward validation (5-fold), strategy portfolio (registry, correlation tracking, signal aggregation), strategy allocation (Kelly, Risk Parity, Adaptive), strategy monitoring (real-time health), strategy retirement gates (7-gate system), and strategy research pipeline (hypothesis generation, statistical validation).

**Key design decisions:**
- Backtesting: vectorbt with fee/slippage models, walk-forward validation
- Strategy lifecycle: candidate → paper → live → paused → retired → dead
- Retirement gates: Rolling Sharpe, drawdown, win rate, loss streak, profit factor, losing days, regime mismatch
- Signal aggregation: allocation-weighted voting with conflict resolution
- Statistical validation: t-test, bootstrap Sharpe CI, binomial win rate test, runs test

**Dependencies on other docs:** References DATA_ARCHITECTURE.md for strategy genome schema, RISK_ARCHITECTURE.md for risk integration.

**Engineering implications:** Day1 has only 1 strategy (mean reversion), so portfolio/allocation/retirement are Level 2+. The backtesting engine is a significant build effort. The retirement gate system is well-specified and can be directly implemented.

**Gaps/ambiguities:**
- vectorbt is listed as dependency but no installation/config guidance
- Walk-forward optimization uses grid search — no Bayesian optimization spec
- Strategy Geneticist agent is referenced but genetic programming is over-engineered for v1
- `BaseStrategy.generate_signals()` returns `(entries, exits)` but Day1 strategy returns signal dicts — format mismatch

---

### 1.14 `TECH_STACK.md`

**What it specifies:** Complete technology stack — Python 3.12 + Rust 1.79 architecture, core components (Exchange Gateway, Strategy Engine, Risk Manager, Backtesting Engine, LLM Integration, Notification System), project structure (131 files), dependency manifests (pyproject.toml, Cargo.toml, requirements.txt), configuration system (YAML hierarchy), build/devops (Makefile, Docker Compose), model routing (free-tier first), logging/monitoring (structlog, Prometheus), and CI/CD.

**Key design decisions:**
- Python for orchestration, Rust for performance-critical paths
- PyO3 bridge for Python↔Rust interop
- SQLite + Redis + ChromaDB data stack
- LiteLLM for model routing with fallback chains
- structlog for structured JSON logging
- FastAPI for REST API, python-telegram-bot for Telegram

**Dependencies on other docs:** Foundation document — all other docs reference this for technology choices.

**Engineering implications:** The project structure (131 files) is the build checklist. The dependency manifests are ready to use. The Makefile provides all dev commands. The Docker Compose is ready for local development.

**Gaps/ambiguities:**
- Mentions Celery but ARCHITECTURE_CONSOLIDATION.md removes it — needs update
- Rust version 1.75 in Cargo.toml but 1.79 is canonical — needs update
- `requirements.txt` and `pyproject.toml` have overlapping but different dependency lists
- Model routing config references `qwen3:8b` but other docs say `qwen2.5:7b` — inconsistent
- 131 files is a lot for a solo developer — prioritization needed

---

### 1.15 `TSAR_ARCHITECTURE.md`

**What it specifies:** The CONSOLIDATED SINGLE SOURCE OF TRUTH (v2.0). Covers: system overview, agent registry (10 agents), communication protocol (Redis Streams), stream topology (13 streams), agent specifications (Signal Scout, Risk Guardian, Execution Sniper, Macro Agent, Regime Detector, Trade Philosopher, Strategy Geneticist, Market Cartographer, Execution Tracker, Orchestrator), tool registry (35 tools), knowledge stores (5 stores with schemas), layer specifications (8 layers), risk management (deterministic rules), paper trading mode, scaling strategy (Day1→Level 4), tech stack, deployment architecture, bootstrap sequence, and Telegram interface.

**Key design decisions:**
- This document supersedes all prior documents where conflicts exist
- 10 agents with clear Day1/Level2/Full progression
- 35 tools with permission matrix
- 5 knowledge stores with complete schemas
- 8 layers with coverage percentages
- Paper → Live transition criteria (100+ trades, Sharpe > 1.0, DD < 10%)
- 6-phase bootstrap sequence (15-25 min)

**Dependencies on other docs:** This is the canonical document. All others are subordinate.

**Engineering implications:** This is the primary reference for all engineering work. The agent specs are detailed enough to implement. The tool registry provides the complete API surface. The knowledge store schemas can be directly translated to SQL migrations.

**Gaps/ambiguities:**
- Agent specs include implementation code (Python class skeletons) — mixing spec and code
- Some tool specs reference Rust implementations that don't exist yet
- Bootstrap sequence timing (15-25 min) may be optimistic for first-time setup
- Telegram commands are listed but handler implementations are not specified
- "Level 2/3/4" specifications are outlines, not complete specs

---

### 1.16 `trading-super-agent-spec.md`

**What it specifies:** The original sub-agent specification — 8 agents (Regime Detector, Signal Scout, Risk Guardian, Execution Sniper, Execution Tracker, Trade Philosopher, Strategy Geneticist, Market Cartographer) with detailed specs including: role, input/output formats, tools (with tiers), model routing, implementation language (Rust/Python split), communication protocol, lifecycle, error handling, and performance requirements.

**Key design decisions:**
- Each agent has a clear Rust/Python split percentage
- Model tiers: T0 (Rust math), T1 (Python ML), T2 (Ollama LLM), T3 (DeepSeek-R1)
- Risk Guardian has absolute VETO power — no agent can override
- Risk Guardian is the ONE agent that must NEVER fail silently
- Agent startup order: Redis → Supervisor → Cartographer → Regime → Tracker → Risk → Signal → Sniper → Philosopher → Geneticist

**Dependencies on other docs:** References trading-super-agent-tools-spec.md for tool details. Superseded by TSAR_ARCHITECTURE.md for canonical values.

**Engineering implications:** The agent specs are the most detailed implementation guidance. Each agent has a complete directory structure, class skeleton, and communication protocol. The Rust/Python split percentages guide resource allocation.

**Gaps/ambiguities:**
- Stream prefixes use `trading:*` — must be updated to `tsar:stream:*`
- Some agents reference tools not in the tool registry
- Performance budgets are per-agent but no system-wide budget
- "PyO3 bridge" is referenced throughout but no PyO3 setup/config guidance

---

### 1.17 `trading-super-agent-tools-spec.md`

**What it specifies:** Complete tool and exchange connectivity specification — 35 tools across 6 categories (Exchange, Analysis, Data, Risk, Memory, Execution). Each tool has: schema (MCP-compatible JSON Schema), parameters, returns, permission level, approval policy, rate limit, timeout, implementation code, and error handling. Also covers: MCP tool server, permission system, tool sandboxing, approval gates, error handling matrix, rate limiting strategy, and performance requirements.

**Key design decisions:**
- BaseTool abstract class with standardized ToolResult return type
- MCP (Model Context Protocol) JSON-RPC server for tool discovery/invocation
- 5 permission levels: READ, ANALYSIS, TRADE_PREVIEW, TRADE_LIVE, ADMIN
- 4 approval policies: AUTO, CONFIRM, ALWAYS_CONFIRM, BLOCKED
- Circuit breaker pattern for exchange connections
- 2-second cache TTL for price data dedup

**Dependencies on other docs:** Companion to trading-super-agent-spec.md. References TECH_STACK for dependencies.

**Engineering implications:** This is the most implementation-ready document. Every tool has working Python code. The MCP server is complete. The exchange client manager with circuit breakers is production-quality. The permission system is well-designed.

**Gaps/ambiguities:**
- Rust tools (stream_prices, smart_order_router, twap_execute) have Rust code but no PyO3 binding setup
- Some tools reference `self._risk` or `self._clients` without initialization guidance
- Rate limiting strategy mentions "centralized rate limiter" but no implementation
- Tool count is 30+ in the spec but 35 in the registry — some tools are referenced but not fully specified

---

### 1.18 `reviews/ARCHITECTURE_REVIEW.md` (First Review)

**What it specifies:** Formal architectural review by Lead Architect. Verdict: CONDITIONAL PASS. Scores: Risk Management 9/10, Execution 8/10, Audit Trail 9/10, Governance 8/10, Monitoring 7/10, Data Integrity 7/10, Operational Resilience 6/10, Compliance 5/10. Overall: 7.4/10 "institutional-adjacent." Identifies 5 CRITICAL gaps, 8 HIGH gaps, 8 MEDIUM gaps, 3 LOW gaps. Lists 8 cross-document contradictions.

**Key findings:**
- 84% research-to-architecture traceability (21/25 items)
- Risk Governor is "genuinely institutional-grade"
- Operational complexity exceeds solo-developer capacity
- Several schema/naming inconsistencies between documents
- ChromaDB and genetic programming are over-engineered for $10

**Engineering implications:** The 5 critical gaps and 8 contradictions must be resolved before engineering. The review recommends creating a "Day 1 Simplified Mode" and unified tool registry.

---

### 1.19 `reviews/SECOND_ARCHITECTURE_REVIEW.md`

**What it specifies:** Second-pass review after gap fixes. Verdict: CONDITIONAL PASS with 2 minor items. All 5 critical gaps verified as RESOLVED. All 8 contradictions verified as RESOLVED. Day1 architecture assessed as buildable in 2-4 weeks. Super Agent DNA verified as preserved.

**Key findings:**
- Paper trading mode: "production-quality" specification
- Bootstrap process: "thorough" with cold-start fallback
- Exchange failover: "complete" with circuit breaker + backoff
- 2 minor issues: Day1 uses `trading.db` (should be `tsar.db`), Day1 uses -3% daily loss (should be -2%)

**Engineering implications:** Engineering can start. The 2 minor fixes are trivial (string/number changes).

---

### 1.20 `reviews/FINAL_ARCHITECTURE_REVIEW.md`

**What it specifies:** Final consolidation review. Verdict: CONDITIONAL PASS — Approved for Engineering. Quality scores: Coherence 9.0/10, Completeness 8.5/10, Scalability 8.5/10, Institutional 8.0/10, Super Agent 9.0/10, No Code 9.5/10. Overall: 8.75/10. Lists 11 explicitly deferred items with revisit triggers.

**Key findings:**
- All quality gates passed (8+ threshold on all categories)
- Risk management scored 9.5/10 — "ahead of 95% of trading systems"
- Knowledge architecture scored 9/10 — "core super agent differentiator"
- Operations layer weakest at 6.5/10
- Testing strategy not specified (5/10)
- Day1 is "fully specified and buildable"

**Engineering implications:** Engineering is approved. TSAR_ARCHITECTURE.md is the canonical reference. Prior docs should be archived. 11 deferred items should be tracked in backlog.

---

## 2. Architecture Completeness Assessment

### 2.1 Well-Defined Areas

| Area | Completeness | Quality | Notes |
|------|-------------|---------|-------|
| **Risk Management** | 95% | 9.5/10 | Exceptional. Half-Kelly, 4-level circuit breakers, anti-behavioral guards, kill switch, veto protocol. Deterministic, zero LLM. |
| **Agent Architecture** | 90% | 9/10 | 10 agents fully specified with I/O formats, tools, model tiers, communication protocols, error handling. |
| **Data Architecture** | 90% | 9/10 | 5 knowledge stores with complete SQL schemas, Redis key design (80+ patterns), FTS5, retention policies. |
| **Tool Specification** | 85% | 8.5/10 | 35 tools with MCP schemas, parameters, returns, permissions. Most have implementation code. |
| **Communication Protocol** | 90% | 9/10 | Redis Streams with `tsar:*` prefix, MessagePack format, MessageEnvelope, consumer groups. |
| **Knowledge Stores** | 90% | 9/10 | Trade Memory, Strategy Genomes, Pattern Library, Lesson Archive, Regime History — all with schemas and flow diagrams. |
| **Scaling Path** | 85% | 8.5/10 | Day1 → Level 4 progression is clear with specific triggers and migration procedures. |
| **Paper Trading** | 85% | 8.5/10 | Simulated engine with realistic slippage, testnet integration, mode switch criteria. |
| **Telegram Interface** | 80% | 8/10 | Commands defined, approval flow specified, alert types categorized. |

### 2.2 Partially Defined Areas

| Area | Completeness | Quality | What's Missing |
|------|-------------|---------|----------------|
| **Market Analysis** | 60% | 7/10 | Full spec exists but Day1 is only Fear & Greed + DXY. On-chain/order flow/geopolitical are Level 3+. |
| **Strategy Layer** | 65% | 7/10 | Backtesting, walk-forward, retirement gates are specified but Day1 has only 1 strategy with no backtesting. |
| **Portfolio Management** | 50% | 6.5/10 | Multi-asset, rebalancing, attribution are specified but all are Level 3+. Day1 is single-asset. |
| **Deployment** | 70% | 7.5/10 | Docker/CI-CD are complete but staging environment, canary deployments, and rollback procedures are thin. |

### 2.3 Missing/Weak Areas

| Area | Completeness | Quality | Impact |
|------|-------------|---------|--------|
| **Testing Strategy** | 20% | 5/10 | No test strategy document, no test data management, no integration test spec, no load testing spec. |
| **Operations Runbooks** | 30% | 5.5/10 | Backup/restore is specified but not tested. No incident response runbooks. No on-call procedures. |
| **Configuration Management** | 40% | 6/10 | YAML configs defined but no validation, versioning, or rollback procedures. |
| **Secret Management** | 30% | 5/10 | Only `.env` files. No secret rotation, no vault integration, no API key lifecycle management. |
| **Monitoring Dashboards** | 40% | 6/10 | Prometheus metrics defined but Grafana dashboards are text descriptions, not actual JSON. |
| **Integration Testing** | 15% | 4/10 | Agent-to-agent integration contracts are underspecified. No dead letter queue strategy. |

---

## 3. Dependency Map

### 3.1 Document Dependencies

```
TSAR_ARCHITECTURE.md (CANONICAL)
├── ARCHITECTURE_CONSOLIDATION.md (canonical values)
├── DAY1_ARCHITECTURE.md (build spec for weeks 1-4)
├── RISK_ARCHITECTURE.md (risk governor — most critical component)
├── DATA_ARCHITECTURE.md (data layer foundation)
├── STRATEGY_LAYER.md (strategy framework)
├── MARKET_ANALYSIS_LAYER.md (market context)
├── PORTFOLIO_LAYER.md (multi-asset management)
├── COMPLIANCE_LAYER.md (regulatory compliance)
├── OPERATIONS_LAYER.md (monitoring, backup, logging)
├── DEPLOYMENT.md (Docker, CI/CD, infrastructure)
├── TECH_STACK.md (technology choices)
├── trading-super-agent-spec.md (agent specifications)
├── trading-super-agent-tools-spec.md (tool specifications)
├── GAP_RESOLUTION.md (gap fixes)
├── GAP_RESOLUTION_MATRIX.md (gap tracking)
└── ARCHITECTURE_COMPLETE.md (status summary)
```

### 3.2 Component Dependencies (Build Order)

```
Phase 0: Infrastructure
├── Redis (required by all agents)
├── SQLite/tsar.db (required by all agents)
└── Telegram Bot (required for human interface)

Phase 1: Core Tools
├── Exchange Client Manager (required by all exchange tools)
├── get_price (required by Signal Agent)
├── get_ohlcv (required by Signal Agent)
├── get_balance (required by Risk Agent)
├── get_positions (required by Risk Agent, Execution Agent)
├── calculate_rsi (required by Signal Agent)
├── calculate_position_size (required by Risk Agent)
├── check_risk (required by Risk Agent)
├── place_order (required by Execution Agent)
├── cancel_order (required by Execution Agent)
└── log_trade (required by Execution Agent)

Phase 2: Core Agents
├── Risk Guardian (must be first — all trades depend on it)
├── Signal Scout (needs Risk Guardian online)
├── Execution Sniper (needs Risk Guardian approval)
└── Orchestrator (coordinates all agents)

Phase 3: Strategy & Learning
├── Mean Reversion strategy (first strategy)
├── Learning Loop (post-trade analysis)
└── Daily Report (Telegram summary)

Phase 4: Enhancement (Level 2+)
├── Macro Agent (market context)
├── Backtesting Engine (strategy validation)
├── Sentiment Analysis (signal enhancement)
├── Economic Calendar (blackout rules)
└── Walk-Forward Validation (overfit prevention)
```

### 3.3 Data Flow Dependencies

```
Market Data → Signal Agent → Risk Agent → Execution Agent → Exchange
     ↓              ↓             ↓              ↓              ↓
  Redis Cache    tsar.db      Redis State    tsar.db       Order Fills
     ↓                          (risk)           ↓
  All Agents                    ↓           Trade Philosopher
                          All Agents            ↓
                                           tsar.db (lessons)
                                                ↓
                                          Strategy Geneticist
                                                ↓
                                          Signal Agent (improved)
```

---

## 4. Day 1 Build Readiness

### 4.1 Can Engineering Start?

**YES** — with the following prerequisites completed:

| Prerequisite | Status | Effort | Blocking? |
|-------------|--------|--------|-----------|
| TSAR_ARCHITECTURE.md is canonical | ✅ Done | — | No |
| ARCHITECTURE_CONSOLIDATION.md provides canonical values | ✅ Done | — | No |
| All critical gaps resolved | ✅ Done | — | No |
| All contradictions resolved | ✅ Done | — | No |
| DAY1_ARCHITECTURE.md is buildable | ✅ Done | — | No |
| Fix Day1 `trading.db` → `tsar.db` | ⏳ Pending | 1 min | No |
| Fix Day1 `-3%` → `-2%` daily loss | ⏳ Pending | 1 min | No |
| Testing strategy defined | ❌ Missing | 2-4 hours | No (can defer) |
| Development environment set up | ⏳ Pending | 1-2 hours | Yes |

### 4.2 Day1 Build Checklist

| Component | Spec Complete? | Code Ready? | Buildable? | Effort |
|-----------|---------------|-------------|------------|--------|
| Project scaffold | ✅ | ✅ (TECH_STACK) | ✅ | Day 1 |
| SQLite schema | ✅ | ✅ (DAY1) | ✅ | Day 1-2 |
| 10 tools | ✅ | ✅ (DAY1) | ✅ | Day 2-4 |
| Exchange connection | ✅ | ✅ (DAY1) | ✅ | Day 3 |
| Signal Agent | ✅ | ✅ (DAY1) | ✅ | Day 5-6 |
| Risk Agent | ✅ | ✅ (DAY1) | ✅ | Day 5-6 |
| Execution Agent | ✅ | ✅ (DAY1) | ✅ | Day 7-8 |
| Orchestrator | ✅ | ✅ (DAY1) | ✅ | Day 8-9 |
| Telegram bot | ✅ | ✅ (DAY1) | ✅ | Day 9-10 |
| Mean Reversion strategy | ✅ | ✅ (DAY1) | ✅ | Day 10-12 |
| Learning loop | ⚠️ Conceptual | ❌ | ⚠️ | Day 13-15 |
| Daily report | ⚠️ Conceptual | ❌ | ⚠️ | Day 15-17 |
| Paper trading (ccxt sandbox) | ✅ | ✅ (DAY1) | ✅ | Day 3 |
| Unit tests | ❌ | ❌ | ❌ | Day 18-20 |

### 4.3 What's Blocking?

| Blocker | Severity | Resolution |
|---------|----------|------------|
| Development environment not set up | HIGH | Install Python 3.12, Redis, Ollama, create Binance testnet API keys, create Telegram bot |
| Testing strategy not defined | MEDIUM | Can defer — write tests alongside implementation |
| Learning loop code not provided | MEDIUM | Needs implementation — conceptual spec exists in DAY1_ARCHITECTURE.md |
| Daily report code not provided | LOW | Simple Telegram message formatting — can be written during build |

### 4.4 Estimated Timeline

| Week | Deliverable | Confidence |
|------|-------------|------------|
| 1 | Project scaffold, DB schema, 10 tools, Binance testnet connection, basic Telegram bot | HIGH |
| 2 | 3 agents (Signal, Risk, Execution), orchestrator loop, first paper trades | HIGH |
| 3 | Mean reversion strategy tuning, learning loop, trade logging | MEDIUM |
| 4 | Integration testing, daily reports, polish, documentation | MEDIUM |

**Total: 4 weeks for a competent Python developer working full-time.**

---

## 5. Risk Register

### 5.1 Architectural Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | **SQLite performance under load** | LOW | HIGH | WAL mode + single-writer is fine for Day1. Monitor write latency. Upgrade trigger: > 100 writes/sec. |
| R2 | **Redis single point of failure** | LOW | CRITICAL | AOF persistence enabled. State is reconstructable from tsar.db. Day1 is single-machine anyway. |
| R3 | **Exchange API rate limiting** | MEDIUM | MEDIUM | Circuit breaker pattern is specified. Rate limit tracking in ExchangeClientManager. Use testnet for Day1. |
| R4 | **LLM cost overrun** | LOW | LOW | Free-tier models only (Ollama local + NVIDIA NIM free). Budget: $0/month for Day1. |
| R5 | **Strategy overfitting** | MEDIUM | HIGH | Walk-forward validation is specified (Level 2). Day1 uses paper trading as proxy. Statistical validation spec exists. |
| R6 | **Operational complexity** | HIGH | HIGH | Day1 simplifies to 3 agents + 1 DB. Full 8-agent system is Level 3+. Solo dev should NOT attempt full architecture. |
| R7 | **Data feed staleness** | MEDIUM | MEDIUM | Data quality pipeline specified (Level 2). Day1 does basic None checks. Stale data → no trading. |
| R8 | **Kill switch failure** | LOW | CRITICAL | Separate process, Redis-based flag, auto-flatten. Must be tested before any live trading. |
| R9 | **Configuration drift** | MEDIUM | MEDIUM | ARCHITECTURE_CONSOLIDATION.md provides canonical values. No runtime config changes (immutable at startup). |
| R10 | **Testnet availability** | LOW | LOW | Binance testnet is generally available. Fallback: ccxt sandbox mode with any supported exchange. |

### 5.2 Business Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| B1 | **$10 capital too small for meaningful returns** | HIGH | LOW | Day1 goal is validation, not profit. Graduate to $100-500 after 50+ profitable live trades. |
| B2 | **Market regime change invalidates strategy** | MEDIUM | MEDIUM | Regime detection is specified. Mean reversion works in ranging markets. Strategy retirement gates catch decay. |
| B3 | **Solo developer burnout** | MEDIUM | HIGH | Day1 is 4 weeks. Full architecture is 12+ months. Pace accordingly. Use the upgrade path. |
| B4 | **Exchange counterparty risk** | LOW | HIGH | Counterparty monitoring is specified (Level 2). Day1 uses Binance testnet (no real money at risk). |

---

## 6. Recommended Build Order

### Phase 1: Foundation (Week 1)

**Goal:** Can query exchange, store data, send Telegram messages.

1. **Project scaffold** — Create directory structure from TECH_STACK.md, initialize git, set up venv
2. **Configuration** — Create `config/settings.py` with all canonical values from ARCHITECTURE_CONSOLIDATION.md
3. **Database** — Create `data/tsar.db` with Day1 schema (trades, strategies, lessons, daily_snapshots)
4. **Exchange tools** — Implement `get_price`, `get_ohlcv`, `get_balance`, `get_positions` using ccxt
5. **Telegram skeleton** — Basic bot that responds to /start and /status

### Phase 2: Core Agents (Week 2)

**Goal:** Can scan for signals, evaluate risk, place paper trades.

6. **Risk Agent** — Implement 6-rule checklist from DAY1_ARCHITECTURE.md. Must be deterministic, no LLM.
7. **Signal Agent** — Implement RSI + S/R scanning. Scoring breakdown: RSI 40%, S/R 30%, volume 15%, trend 15%.
8. **Execution Agent** — Implement order lifecycle: receive → place → monitor → close → notify.
9. **Orchestrator** — Implement signal → risk → execute loop with 5-minute scan interval.
10. **Remaining tools** — Implement `calculate_rsi`, `calculate_position_size`, `check_risk`, `place_order`, `cancel_order`, `log_trade`.

### Phase 3: Strategy & Trading (Week 3)

**Goal:** First paper trades on Binance testnet.

11. **Mean Reversion strategy** — Implement entry/exit rules from DAY1_ARCHITECTURE.md.
12. **Paper trading** — Configure ccxt sandbox mode. Verify fills, P&L calculation, stop-loss execution.
13. **Trade logging** — Every trade logged to `tsar.db` with full context.
14. **Telegram notifications** — Trade opened/closed alerts with formatted messages.
15. **Emergency stop** — Implement /stop command → cancel all orders, close all positions.

### Phase 4: Learning & Polish (Week 4)

**Goal:** Full paper trading system with learning loop.

16. **Learning loop** — Post-trade analysis: what went right/wrong, generate lessons.
17. **Daily report** — End-of-day summary via Telegram: P&L, trades, win rate.
18. **Weekly review** — Aggregate lessons, suggest parameter adjustments.
19. **Unit tests** — Test all tools, risk checks, agent logic.
20. **Documentation** — README, setup guide, configuration reference.

### Phase 5: Validation & Live Prep (Week 5+)

**Goal:** Ready for $10 live trading.

21. **Paper trade review** — Analyze 30+ paper trades. Check: win rate > 50%, PF > 1.2, DD < 15%.
22. **Kill switch testing** — Verify /stop works, verify daily loss halt works.
23. **Live preparation** — Get Binance live API keys (trade-only, no withdrawal), set up IP whitelist.
24. **First live trades** — Start with $10, monitor first 5 trades manually.
25. **Iterate** — Adjust strategy parameters based on lessons learned.

### Future Phases (Level 2+)

| Phase | Timeline | Key Additions |
|-------|----------|---------------|
| Level 2 | Months 2-3 | Macro Agent, backtesting engine, sentiment analysis, economic calendar, 2nd strategy |
| Level 3 | Months 4-6 | Full 10 agents, Rust execution layer, multi-asset, VaR, Grafana dashboards |
| Level 4 | Months 7-12 | Multi-exchange, genetic programming, Kubernetes, full institutional compliance |

---

## Appendix A: Document Size Summary

| Document | Size | Role |
|----------|------|------|
| trading-super-agent-tools-spec.md | ~137KB | Tool implementation specs |
| DATA_ARCHITECTURE.md | ~110KB | Data layer foundation |
| RISK_ARCHITECTURE.md | ~96KB | Risk governor (most critical) |
| trading-super-agent-spec.md | ~98KB | Agent specifications |
| MARKET_ANALYSIS_LAYER.md | ~102KB | Market analysis layer |
| TSAR_ARCHITECTURE.md | ~42KB | Canonical source of truth |
| STRATEGY_LAYER.md | ~80KB | Strategy framework |
| PORTFOLIO_LAYER.md | ~70KB | Portfolio management |
| TECH_STACK.md | ~67KB | Technology choices |
| GAP_RESOLUTION.md | ~65KB | Gap fixes |
| ARCHITECTURE_CONSOLIDATION.md | ~55KB | Canonical values |
| DAY1_ARCHITECTURE.md | ~45KB | Day1 build spec |
| DEPLOYMENT.md | ~50KB | Infrastructure |
| COMPLIANCE_LAYER.md | ~34KB | Compliance layer |
| OPERATIONS_LAYER.md | ~30KB | Operations layer |
| GAP_RESOLUTION_MATRIX.md | ~15KB | Gap tracking |
| ARCHITECTURE_COMPLETE.md | ~6KB | Status summary |
| FINAL_ARCHITECTURE_REVIEW.md | ~19KB | Final review verdict |
| SECOND_ARCHITECTURE_REVIEW.md | ~19KB | Second review |
| ARCHITECTURE_REVIEW.md | ~23KB | First review |

**Total: ~1.1MB+ of specification**

---

## Appendix B: Key Canonical Values Quick Reference

| Parameter | Canonical Value | Source |
|-----------|----------------|--------|
| Stream prefix | `tsar:stream:*` | ARCHITECTURE_CONSOLIDATION.md |
| Database file | `tsar.db` | ARCHITECTURE_CONSOLIDATION.md |
| Daily loss kill | -2% | ARCHITECTURE_CONSOLIDATION.md |
| Max drawdown | 5% from HWM | TSAR_ARCHITECTURE.md |
| Max positions | 10 (Day1: 3) | ARCHITECTURE_CONSOLIDATION.md |
| Kelly fraction | 0.25 (Half-Kelly) | RISK_ARCHITECTURE.md |
| Max correlation | 0.7 | ARCHITECTURE_CONSOLIDATION.md |
| Message format | MessagePack | ARCHITECTURE_CONSOLIDATION.md |
| Rust version | 1.79 | ARCHITECTURE_CONSOLIDATION.md |
| Python version | 3.12 | ARCHITECTURE_CONSOLIDATION.md |
| FastAPI port | 8000 | ARCHITECTURE_CONSOLIDATION.md |
| Supervisor port | 8001 | ARCHITECTURE_CONSOLIDATION.md |
| Redis port | 6379 | ARCHITECTURE_CONSOLIDATION.md |
| Tool permissions | READ/ANALYSIS/TRADE_PREVIEW/TRADE_EXECUTE/TRADE_ADMIN | ARCHITECTURE_CONSOLIDATION.md |

---

*Analysis completed: 2026-07-24*  
*Documents analyzed: 20 (17 architecture + 3 reviews)*  
*Total specification volume: ~1.1MB*
