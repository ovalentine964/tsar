# TSAR COUNCIL REVIEW — MASTER ISSUE TRACKER
## All gaps, issues, and recommendations from 17 council reviews
## Each issue will be assigned to a dedicated fixing team

**Date:** 2026-07-30
**Repo:** https://github.com/ovalentine964/tsar
**Starting Capital:** $10
**Status:** All 17 councils COMPLETE

---

### M-053: Telegram Bot Commands Return Hardcoded Data
- **Source:** Client Access Strategist
- **Severity:** HIGH
- **Description:** Most Telegram bot commands return hardcoded strings instead of real data. `/pnl` returns "No trades yet", `/positions` returns "No open positions", `/risk` returns hardcoded "GREEN", `/status` returns static "v0.1.0 — Running (paper mode)". Only `/kill` and `/flywheel` are wired to real systems.
- **Sector Application:** The Telegram bot is Valentine's primary $10-stage access method. If it shows stale data, he can't monitor the system effectively from his phone.
- **Fix Required:** Wire all Telegram commands to real data sources (TradeMemory, KillSwitch, etc.)
- **Assigned To:** [Pending assignment]

### M-050: Mobile App Missing Backtest UI
- **Source:** Client Access Strategist
- **Severity:** MEDIUM
- **Description:** Backtest API endpoint exists (/api/v1/backtest) but no corresponding screen in the Flutter app. Strategy comparison and backtest results can only be viewed via API docs.
- **Fix Required:** Add backtest results screen to Flutter app with equity curve and drawdown charts
- **Assigned To:** [Pending assignment]

### M-051: API Route Duplication
- **Source:** Client Access Strategist
- **Severity:** MEDIUM
- **Description:** app.py defines inline routes AND imports routes from routes/ directory. Both /health, /api/v1/trades, etc. could conflict. Route aliases (/api/dashboard → /) add more duplication.
- **Fix Required:** Consolidate routes — either use router pattern or inline, not both
- **Assigned To:** [Pending assignment]

### M-052: Mobile App Version Mismatch
- **Source:** Client Access Strategist
- **Severity:** LOW
- **Description:** settings_screen.dart shows version "1.0.0" while README and API report "0.5.0". Build date shows "2024.01" which is stale.
- **Fix Required:** Sync version strings across all clients
- **Assigned To:** [Pending assignment]

---

## COUNCIL REPORTS STATUS

| # | Council Member | Status | Score | Verdict |
|---|---|---|---|---|
| 1 | Chief Architect | ✅ Complete | 7.8/10 | CONDITIONAL PASS |
| 2 | Chief Strategist | ✅ Complete | 7.2/10 | CONDITIONAL PASS |
| 3 | Chief Engineer | ✅ Complete | 6.5/10 | CONDITIONAL PASS |
| 4 | Chief Risk Officer | ✅ Complete | 7.0/10 | CONDITIONAL PASS |
| 5 | Flywheel Engineer | ✅ Complete | 7.2/10 | CONDITIONAL PASS |
| 6 | Harness Engineer | ✅ Complete | 7.2/10 | CONDITIONAL PASS |
| 7 | Graph Engineer | ✅ Complete | 7.0/10 | CONDITIONAL PASS |
| 8 | LLM/AI Engineer | ✅ Complete | 7/10 | CONDITIONAL PASS |
| 9 | Security Officer | ✅ Complete | 5.5/10 | CONDITIONAL PASS |
| 10 | Research Analyst | ✅ Complete | 7.2/10 | CONDITIONAL PASS |
| 11 | Exchange & Market Strategist | ✅ Complete | 6.5/10 | CONDITIONAL PASS |
| 12 | Tech Stack Architect | ✅ Complete | 6.5/10 | CONDITIONAL PASS |
| 13 | AI Landscape Strategist | ✅ Complete | 7.5/10 | CONDITIONAL PASS |
| 14 | NVIDIA Platform Specialist | ✅ Complete | 8.5/10 | APPROVED |
| 15 | Live Market Data Engineer | ✅ Complete | 5.7/10 | CONDITIONAL PASS |
| 16 | Client Access Strategist | ✅ Complete | 7.5/10 | CONDITIONAL PASS |

---

## CRITICAL ISSUES (Block live trading)

### C-001: $10 Capital Architectural Incoherence
- **Source:** Chief Strategist
- **Severity:** CRITICAL
- **Description:** System designed for $100K+ but being deployed with $10. Exchange minimums ($5-10), fee dominance (0.2% round trip = 10% of risk budget), Kelly criterion produces positions below minimums.
- **Sector Application:** Binance minimum order is ~$5-10. With $10 capital, a single trade IS the entire portfolio. Fee drag makes micro-positions unprofitable.
- **Fix Required:** Implement micro-capital mode with fee-aware sizing, exchange minimum detection, and adjusted Kelly fraction
- **Assigned To:** [Pending assignment]

### C-002: Regime Detection Oversimplified
- **Source:** Chief Strategist
- **Severity:** CRITICAL
- **Description:** Rule-based regime detection using simple MA crossovers. No Hidden Markov Model, no volatility clustering, no statistical validation.
- **Sector Application:** Crypto markets have distinct regimes (trending, ranging, high-vol, liquidation cascades). Simple MA crossovers produce excessive false signals. Need proper statistical regime detection.
- **Fix Required:** Implement HMM or volatility-based regime detection with statistical validation
- **Assigned To:** [Pending assignment]

### C-003: Stub Agents (Market Cartographer, Macro Agent)
- **Source:** Chief Strategist
- **Severity:** HIGH
- **Description:** Market Cartographer and Macro Agent have `run_cycle()` implementations that are `pass` — they do nothing.
- **Sector Application:** Cross-asset correlation (BTC↔ETH↔SOL↔Gold↔Forex) is critical for risk management. Macro context (Fed rates, DXY, risk sentiment) drives crypto markets.
- **Fix Required:** Implement functional Market Cartographer and Macro Agent
- **Assigned To:** [Pending assignment]

### C-004: Backtest Engine Uses $100K Default
- **Source:** Chief Strategist
- **Severity:** HIGH
- **Description:** Backtest engine defaults to $100K starting capital. No validation at $10 level.
- **Sector Application:** Backtesting at $10 with Binance fees produces completely different results than $100K. Fee impact, position sizing, and minimum order constraints dominate at micro-capital.
- **Fix Required:** Add $10 capital backtest mode with realistic fee modeling
- **Assigned To:** [Pending assignment]

### C-005: Flywheel Not Self-Activating
- **Source:** Flywheel Engineer
- **Severity:** CRITICAL
- **Description:** ShadowExtractor → RuleValidator → GenomeMutator → StrategyGeneticist pipeline exists but has no automatic orchestration. Someone has to manually trigger it.
- **Sector Application:** The flywheel's value is in continuous compounding. If it requires manual triggering, it won't compound during live trading when markets move 24/7.
- **Fix Required:** Build Flywheel Orchestrator that auto-triggers after every trade completion
- **Assigned To:** [Pending assignment]

### C-007: Flywheel EXTRACT→ADAPT Gap
- **Source:** Chief Architect
- **Severity:** CRITICAL
- **Description:** StrategyGeneticist exists in code but is NOT in the orchestrator's agent registry. Mutations are proposed but never applied. The flywheel doesn't close.
- **Sector Application:** Without the ADAPT stage, the system can't improve from trade data. The "self-improving" claim is broken.
- **Fix Required:** Register StrategyGeneticist in orchestrator and wire mutations back to strategy parameters
- **Assigned To:** [Pending assignment]

### C-008: get_trade_stats() Missing
- **Source:** Chief Engineer
- **Severity:** CRITICAL
- **Description:** `get_trade_stats()` method missing from `TradeMemory` class. Crashes 6 call sites across the codebase.
- **Sector Application:** Trade statistics (win rate, P&L, drawdown) are needed for strategy evaluation, risk management, and the flywheel. Without this, the system can't measure performance.
- **Fix Required:** Implement get_trade_stats() method in TradeMemory
- **Assigned To:** [Pending assignment]

### C-009: Zero API Authentication
- **Source:** Chief Engineer
- **Severity:** CRITICAL
- **Description:** FastAPI endpoints have no authentication. Kill switch and mandate endpoints are wide open.
- **Sector Application:** Anyone who finds the API URL can trigger the kill switch, authorize live trading, or access trade data. In production, this means anyone can hijack your trading system.
- **Fix Required:** Add API authentication (JWT or API key) to all endpoints
- **Assigned To:** [Pending assignment]

### C-010: Backend Swap Promise Broken
- **Source:** Chief Architect
- **Severity:** HIGH
- **Description:** `_register_defaults()` imports all Python backends at init time. Changing to Rust backend in YAML will crash.
- **Sector Application:** The "YAML config selects backend" promise is broken. Can't actually swap Python→Rust without code changes.
- **Fix Required:** Lazy-load backends on demand, not at init
- **Assigned To:** [Pending assignment]

### C-011: Rust Layer Entirely Stubbed
- **Source:** Chief Engineer
- **Severity:** HIGH
- **Description:** Rust crates (ws-manager, tick-processor, order-executor) are stub code. No actual performance benefit from Rust layer.
- **Sector Application:** The multi-language strategy (Python→Rust→C++) is aspirational, not real. For $10 capital this doesn't matter, but for scaling it does.
- **Fix Required:** Either implement Rust layer or remove it from architecture claims
- **Assigned To:** [Pending assignment]

### C-012: No Kill Switch Watchdog
- **Source:** Chief Architect
- **Severity:** HIGH
- **Description:** Three-tier watchdog architecture described in docs is NOT implemented. Single-process safety gap.
- **Sector Application:** If the main process crashes during a trade, there's no external watchdog to trigger the kill switch. Positions could be left orphaned.
- **Fix Required:** Implement external watchdog process that monitors main process health
- **Assigned To:** [Pending assignment]

### C-006: TradePhilosopher Unstructured Output
- **Source:** Flywheel Engineer
- **Severity:** HIGH
- **Description:** TradePhilosopher produces unstructured LLM text output instead of structured JSON schema. Makes downstream parsing unreliable.
- **Sector Application:** Lessons from trades need to be machine-readable to feed into strategy genome mutation. Free-text = garbage in, garbage out.
- **Fix Required:** Add JSON schema enforcement to TradePhilosopher output
- **Assigned To:** [Pending assignment]

### C-013: Kill Switch Monitor No Watchdog
- **Source:** Chief Risk Officer
- **Severity:** CRITICAL
- **Description:** If AutoKillDetector process crashes, there's no fallback. FIX_D spec defines three-tier watchdog but it's not implemented.
- **Sector Application:** In 24/7 crypto markets, if the kill switch monitor dies during a flash crash, positions are unprotected. Total loss possible.
- **Fix Required:** Implement three-tier watchdog (process monitor → system watchdog → exchange-level stop)
- **Assigned To:** [Pending assignment]

### C-017: No Hallucination Mitigation for Trading Signals
- **Source:** LLM/AI Engineer
- **Severity:** CRITICAL
- **Description:** No RAG grounding, no output validation for LLM-generated trading signals. Signal Scout can generate plausible but wrong statistical claims.
- **Sector Application:** Lopez-Lira & Tang (2023) show LLMs are good for reflection but unreliable for signal generation without grounding. One hallucinated signal = real money lost.
- **Fix Required:** Add deterministic signal validation layer and RAG grounding for Signal Scout
- **Assigned To:** [Pending assignment]

### C-019: Wildcard CORS with Credentials
- **Source:** Security Officer
- **Severity:** CRITICAL
- **Description:** `allow_origins=["*"]` with `allow_credentials=True`. Any website can make authenticated requests to TSAR API.
- **Sector Application:** If TSAR is exposed to the network, any malicious website can trigger kill switch, authorize live trading, or access trade data via the user's browser.
- **Fix Required:** Restrict CORS to specific origins, remove allow_credentials with wildcard
- **Assigned To:** [Pending assignment]

### C-020: No Telegram Bot Authorization
- **Source:** Security Officer
- **Severity:** CRITICAL
- **Description:** Any Telegram user can send commands to the bot including `/stop` and trade authorization. No user ID whitelist.
- **Sector Application:** Anyone who discovers the bot can stop the system, authorize live trading, or access account info.
- **Fix Required:** Add Telegram user ID whitelist for authorized commands
- **Assigned To:** [Pending assignment]

### C-018: $10 Capital Microstructure Breaks Kelly
- **Source:** Research Analyst
- **Severity:** CRITICAL
- **Description:** Kelly sizing is meaningless at $10. Transaction costs dominate (O'Hara 1995, Harris 2003). Exchange minimums ($5-10) make risk controls inoperable.
- **Sector Application:** At $10, a single trade IS the entire portfolio. Kelly suggests $0.20/trade, exchange minimum is $5. The math doesn't work.
- **Fix Required:** Acknowledge $10 as proof-of-concept scale, implement micro-capital mode with fee-aware sizing
- **Assigned To:** [Pending assignment]

### C-014: Guard State Doesn't Persist
- **Source:** Chief Risk Officer
- **Severity:** CRITICAL
- **Description:** In-memory `GuardState` (revenge cooldown, greed cap, FOMO filter) resets on process restart, bypassing all anti-behavioral protections.
- **Sector Application:** System restart after a crash loses all behavioral state. Could immediately revenge-trade after 3 losses.
- **Fix Required:** Persist guard state to SQLite/Redis on every state change
- **Assigned To:** [Pending assignment]

### C-015: Risk Parameter Inconsistencies
- **Source:** Chief Risk Officer
- **Severity:** HIGH
- **Description:** Three different sources have three different risk limits: risk.yaml (15% DD, 3% daily), code defaults (5% DD, 2% daily), architecture docs (20% DD, 4% daily).
- **Sector Application:** Which values actually apply to real money? If code defaults win, the system is tighter than config suggests. If config wins, code may not enforce them.
- **Fix Required:** Single source of truth for risk parameters, reconcile all three sources
- **Assigned To:** [Pending assignment]

### C-016: Recovery Protocol Stubbed
- **Source:** Chief Risk Officer
- **Severity:** HIGH
- **Description:** `get_recovery_allocation()` returns 1.0 (full size) after kill switch deactivation, defeating the phased re-entry design (5%→10%→25%→50%→100%).
- **Sector Application:** After a kill switch event, the system should gradually re-enter with small positions. Full-size re-entry = doubling down after a loss.
- **Fix Required:** Implement phased recovery allocation as designed
- **Assigned To:** [Pending assignment]

---

## HIGH ISSUES (Fix before live trading)

### H-001: Shadow Account Learning Loop Unclear
- **Source:** Chief Strategist
- **Severity:** HIGH
- **Description:** Shadow account extracts lessons but unclear how lessons feed back into strategy genome mutation and risk parameter adjustment.
- **Sector Application:** The flywheel's value is in learning from losses. If shadow account doesn't feed back into strategy evolution, the system doesn't improve.
- **Fix Required:** Wire shadow account lessons directly into strategy genome mutation pipeline
- **Assigned To:** [Pending assignment]

### H-002: Backtest Overfitting Risk
- **Source:** Chief Strategist
- **Severity:** HIGH
- **Description:** No cross-validation or out-of-sample testing mentioned. Walk-forward exists but implementation not validated.
- **Sector Application:** Financial backtesting is notorious for overfitting. Strategies that backtest well often fail live. Need proper out-of-sample validation.
- **Fix Required:** Implement cross-validation and out-of-sample testing
- **Assigned To:** [Pending assignment]

### H-003: LLM Dependency for Signal Generation
- **Source:** Chief Strategist
- **Severity:** HIGH
- **Description:** Signal Scout uses LLM for statistical reasoning. If LLM hallucinates, bad signals propagate through risk → execution.
- **Sector Application:** LLMs can generate plausible but wrong statistical claims. In trading, one bad signal = real money lost. Need deterministic validation layer.
- **Fix Required:** Add deterministic signal validation layer that checks LLM output before it reaches Risk Guardian
- **Assigned To:** [Pending assignment]

### H-004: DeepSeek-R1 Volatility
- **Source:** Chief Strategist
- **Severity:** HIGH
- **Description:** DeepSeek-R1 API may have downtime or rate limits. No fallback if API unavailable.
- **Sector Application:** Markets don't wait for API recovery. If DeepSeek is down during a volatility event, the system can't generate signals or manage positions.
- **Fix Required:** Implement local model fallback (Ollama) and graceful degradation
- **Assigned To:** [Pending assignment]

### H-006: No LLM Output Evaluation Framework
- **Source:** LLM/AI Engineer
- **Severity:** HIGH
- **Description:** No A/B testing, no quality metrics for LLM outputs. Can't measure if prompts are improving or degrading.
- **Sector Application:** Without eval framework, can't validate if DeepSeek-R1 is "good enough" for trading decisions. Need benchmarks.
- **Fix Required:** Implement LLM evaluation framework with trading-specific benchmarks
- **Assigned To:** [Pending assignment]

### H-007: Regime Detection Needs HMM
- **Source:** Research Analyst
- **Severity:** HIGH
- **Description:** Rule-based regime classifier needs Hidden Markov Model (Hamilton 1989, Ang & Bekaert 2002). Current MA crossover approach produces excessive false signals.
- **Sector Application:** Crypto markets have distinct regimes (trending, ranging, high-vol, liquidation cascades). HMM is the gold standard for regime detection.
- **Fix Required:** Implement HMM-based regime detection with statistical validation
- **Assigned To:** [Pending assignment]

### H-009: LLM Prompt Injection via Market Data
- **Source:** Security Officer
- **Severity:** HIGH
- **Description:** Market data and trade theses are injected raw into LLM prompts without sanitization. Malicious market data could manipulate LLM outputs.
- **Sector Application:** If a coordinated pump-and-dump generates specific market patterns, the LLM might be influenced to generate buy signals. Prompt injection via price action.
- **Fix Required:** Sanitize market data before LLM injection, add output validation
- **Assigned To:** [Pending assignment]

### H-010: Weak Default Secrets
- **Source:** Security Officer
- **Severity:** HIGH
- **Description:** Predictable Redis password and API key defaults in .env.example. If deployed without changing defaults, system is exposed.
- **Sector Application:** Default credentials = open door. Anyone scanning for TSAR instances can take control.
- **Fix Required:** Generate random secrets on first run, refuse to start with default secrets
- **Assigned To:** [Pending assignment]

### C-021: OANDA/MT5 Connectivity Does Not Exist
- **Source:** Exchange & Market Strategist
- **Severity:** HIGH
- **Description:** Zero Python files reference OANDA/MT5/MetaTrader. The README's "Markets" section listing OANDA/MT5 is purely aspirational documentation. No backend code exists.
- **Sector Application:** The system claims to support Gold and Forex but has zero implementation. This misleads users about capabilities.
- **Fix Required:** Either implement OANDA/MT5 backend or remove from README until built
- **Assigned To:** [Pending assignment]

### C-022: CcxtGateway Missing Critical Methods
- **Source:** Exchange & Market Strategist
- **Severity:** HIGH
- **Description:** `get_balance()`, `get_positions()`, `get_recent_trades()` are declared in abstract interface but NOT implemented in CcxtGateway. `cancel_order()` will fail because it passes `symbol=None`.
- **Sector Application:** Without balance and position queries, the system can't manage portfolio state. Without cancel_order, it can't cancel failed orders.
- **Fix Required:** Implement missing abstract methods in CcxtGateway
- **Assigned To:** [Pending assignment]

### C-023: No WebSocket Streaming
- **Source:** Exchange & Market Strategist
- **Severity:** MEDIUM
- **Description:** Binance connection uses REST polling at ~5s intervals instead of WebSocket streaming.
- **Sector Application:** 5-second polling misses rapid price movements. In crypto, prices can move 2-5% in seconds during liquidation cascades.
- **Fix Required:** Add WebSocket streaming for real-time price data
- **Assigned To:** [Pending assignment]

### H-011: No Sentiment Pipeline
- **Source:** AI Landscape Strategist
- **Severity:** HIGH
- **Description:** `t2_news_sentiment` exists in routing but no actual data feeds. CryptoPanic, Fear & Greed Index, funding rates — all free APIs, none integrated.
- **Sector Application:** Crypto markets are heavily sentiment-driven. Missing sentiment = missing 50% of the signal. Free data sources not being used is a massive missed opportunity.
- **Fix Required:** Integrate CryptoPanic API, Fear & Greed Index, and funding rates as sentiment signals
- **Assigned To:** [Pending assignment]

### H-012: No ML/RL Optimization
- **Source:** AI Landscape Strategist
- **Severity:** HIGH
- **Description:** Zero XGBoost/LightGBM for signal scoring, no parameter optimization, no reinforcement learning for strategy tuning.
- **Sector Application:** Modern quant funds use ML for signal combination and parameter optimization. TSAR relies entirely on LLM reasoning — missing the statistical ML layer.
- **Fix Required:** Add XGBoost/LightGBM signal scoring layer and basic parameter optimization
- **Assigned To:** [Pending assignment]

### H-013: No Multimodal Analysis
- **Source:** AI Landscape Strategist
- **Severity:** MEDIUM
- **Description:** Text-only models missing chart vision (Gemini 2.5 Pro can analyze charts), on-chain data, social signals.
- **Sector Application:** Chart pattern recognition, on-chain whale tracking, social media sentiment — all accessible via multimodal AI. TSAR is blind to these.
- **Fix Required:** Add chart vision analysis and on-chain data feeds
- **Assigned To:** [Pending assignment]

### C-024: CcxtGateway Cannot Be Instantiated
- **Source:** Live Market Data Engineer
- **Severity:** CRITICAL
- **Description:** `CcxtGateway` is missing `get_balance()`, `get_positions()`, `get_ticker()`, `get_recent_trades()` implementations from the abstract `ExchangeGateway` class. Python will raise `TypeError` at runtime.
- **Sector Application:** The system literally cannot connect to Binance. The gateway that's supposed to be the bridge to the exchange doesn't work.
- **Fix Required:** Implement all 4 missing abstract methods in CcxtGateway
- **Assigned To:** [Pending assignment]

### C-025: No Paper Execution Engine
- **Source:** Live Market Data Engineer
- **Severity:** HIGH
- **Description:** Paper trading mode hits real Binance API. There's no simulated execution engine — orders actually get placed even in "paper" mode.
- **Sector Application:** Can't test the system without risking real money. Paper trading should simulate fills, not hit the exchange.
- **Fix Required:** Implement paper execution engine that simulates fills against live data
- **Assigned To:** [Pending assignment]

### C-026: Trading API Routes Return Empty Arrays
- **Source:** Live Market Data Engineer
- **Severity:** HIGH
- **Description:** Trading API endpoints return empty arrays instead of actual data.
- **Sector Application:** Dashboard shows nothing. Mobile app shows nothing. The system appears broken even if it's working.
- **Fix Required:** Wire API routes to actual data sources
- **Assigned To:** [Pending assignment]

### C-027: ExecutionTracker.run_cycle() is pass
- **Source:** Live Market Data Engineer
- **Severity:** HIGH
- **Description:** ExecutionTracker's `run_cycle()` is empty. Fill quality and slippage analysis not implemented.
- **Sector Application:** Can't measure execution quality. Can't optimize order placement over time.
- **Fix Required:** Implement ExecutionTracker with fill quality and slippage analysis
- **Assigned To:** [Pending assignment]

### H-019: No WebSocket Streaming
- **Source:** Live Market Data Engineer
- **Severity:** HIGH
- **Description:** Binance connection uses REST polling only. No WebSocket streaming for real-time price data.
- **Sector Application:** 5-second polling misses rapid price movements. In crypto, prices can move 2-5% in seconds.
- **Fix Required:** Implement WebSocket streaming for real-time data
- **Assigned To:** [Pending assignment]

### H-020: No Market Data Caching
- **Source:** Live Market Data Engineer
- **Severity:** MEDIUM
- **Description:** No caching layer for market data. Every request hits the exchange API.
- **Sector Application:** Wastes API rate limits. Can't backtest with cached data. Performance degrades under load.
- **Fix Required:** Implement Redis-based market data cache
- **Assigned To:** [Pending assignment]

### H-021: No OCO/Bracket Orders
- **Source:** Live Market Data Engineer
- **Severity:** MEDIUM
- **Description:** No OCO (One-Cancels-Other) or bracket order support. Stop-loss and take-profit can't be linked.
- **Sector Application:** If take-profit fills but stop-loss doesn't cancel, you could end up with an opposite position.
- **Fix Required:** Implement OCO order support
- **Assigned To:** [Pending assignment]

### H-014: Rust External-Facing Components Are Stubs
- **Source:** Tech Stack Architect
- **Severity:** HIGH
- **Description:** Rust hot-path modules (OHLCV aggregator, order book manager) are genuinely implemented, BUT every external-facing component (WebSocket connection, message parsing, order execution) is a stub.
- **Sector Application:** The Rust layer can process data fast but can't actually connect to exchanges or execute orders. It's a fast engine with no wheels.
- **Fix Required:** Implement WebSocket connection and order execution in Rust, or document that these stay in Python
- **Assigned To:** [Pending assignment]

### H-015: PyO3 Runtime Anti-Pattern
- **Source:** Tech Stack Architect
- **Severity:** HIGH
- **Description:** PyO3 bridge creates a new `tokio::runtime::Runtime` per call. This is a performance anti-pattern that negates Rust's speed advantages.
- **Sector Application:** Every Rust call from Python pays the overhead of creating a new async runtime. For high-frequency calls (tick processing), this kills performance.
- **Fix Required:** Create a single persistent tokio runtime, share across calls
- **Assigned To:** [Pending assignment]

### H-016: CI Only Covers Python
- **Source:** Tech Stack Architect
- **Severity:** MEDIUM
- **Description:** GitHub Actions CI only builds and tests Python. Rust and C++ are not compiled or tested in CI.
- **Sector Application:** Rust stubs could break silently. C++ changes aren't validated. The multi-language strategy has no safety net.
- **Fix Required:** Add Rust and C++ build/test stages to CI pipeline
- **Assigned To:** [Pending assignment]

### H-017: Docker Compose Dev-Grade Only
- **Source:** Tech Stack Architect
- **Severity:** MEDIUM
- **Description:** Docker Compose is configured for development, not production. No health checks, no restart policies, no resource limits.
- **Sector Application:** Production deployment needs health checks, auto-restart, resource limits, log rotation.
- **Fix Required:** Harden Docker Compose for production deployment
- **Assigned To:** [Pending assignment]

### H-018: Monitoring Not Wired
- **Source:** Tech Stack Architect
- **Severity:** MEDIUM
- **Description:** Prometheus metrics and Grafana dashboards are defined but not actually wired to the application.
- **Sector Application:** Can't monitor system health, trade performance, or risk metrics in production.
- **Fix Required:** Wire Prometheus metrics collection and Grafana dashboards
- **Assigned To:** [Pending assignment]

### H-008: Factor Library Conflates Indicators with Factors
- **Source:** Research Analyst
- **Severity:** HIGH
- **Description:** Factor library conflates technical indicators (RSI, MACD) with academic risk factors (Fama-French). No IC decay tracking.
- **Sector Application:** Academic factors have decades of validation. Technical indicators are heuristics. Mixing them inflates perceived alpha.
- **Fix Required:** Separate technical indicators from risk factors, add IC decay tracking
- **Assigned To:** [Pending assignment]

### H-005: $10 Capital Makes Risk Controls Inoperable
- **Source:** Chief Risk Officer
- **Severity:** HIGH
- **Description:** Kelly criterion suggests $0.20/trade, but exchange minimum is $5-10. System will either reject everything or take 50-100x intended risk.
- **Sector Application:** At $10, the entire capital is one position. Risk controls designed for $100K+ don't apply. Need micro-capital risk mode.
- **Fix Required:** Implement micro-capital risk mode with adjusted Kelly fraction and exchange minimum awareness
- **Assigned To:** [Pending assignment]

---

## MEDIUM ISSUES (Fix before scaling)

### M-007: BackendRegistry Fallback Chain Dead Code
- **Source:** Harness Engineer
- **Severity:** HIGH
- **Description:** BackendRegistry stores fallback backends but never executes them. The fallback chain is dead code.
- **Sector Application:** If a backend fails (e.g., Rust backend crashes), there's no automatic fallback to Python. The system should degrade gracefully.
- **Fix Required:** Implement fallback execution logic in BackendRegistry
- **Assigned To:** [Pending assignment]

### M-008: Event Bus No Persistence/DLQ
- **Source:** Harness Engineer
- **Severity:** HIGH
- **Description:** CloudEvents bus is in-memory only. No persistence, no dead letter queue, no replay. Race conditions possible.
- **Sector Application:** If the system restarts during a trade, all in-flight events are lost. No way to replay missed events. Critical for 24/7 crypto trading.
- **Fix Required:** Add Redis Streams persistence and dead letter queue
- **Assigned To:** [Pending assignment]

### M-009: No Database Connection Pooling
- **Source:** Harness Engineer
- **Severity:** MEDIUM
- **Description:** Every DB operation opens/closes a new SQLite connection. No connection pooling.
- **Sector Application:** With 10 agents making frequent DB calls, this creates unnecessary overhead. Not critical at $10 but becomes a bottleneck at scale.
- **Fix Required:** Implement SQLite connection pooling (or switch to aiosqlite with pooling)
- **Assigned To:** [Pending assignment]

### M-010: PricingEngine Sync vs Async Inconsistency
- **Source:** Harness Engineer
- **Severity:** MEDIUM
- **Description:** PricingEngine interface is synchronous while other interfaces are async. Inconsistent design.
- **Sector Application:** Sync pricing calls block the event loop during high-frequency price updates. Need async pricing for production.
- **Fix Required:** Convert PricingEngine to async interface
- **Assigned To:** [Pending assignment]
### M-001: Paper Trading Phase Not Mandatory
- **Source:** Chief Strategist
- **Severity:** MEDIUM
- **Description:** Paper trading exists but isn't a mandatory gate before live trading.
- **Sector Application:** Trading systems must prove themselves in paper before risking real capital. Especially at $10 where one bad trade = significant loss.
- **Fix Required:** Make paper trading mandatory gate with minimum trade count and win rate requirements
- **Assigned To:** [Pending assignment]

### M-002: Strategy Genome Diversity Pressure
- **Source:** Chief Strategist
- **Severity:** MEDIUM
- **Description:** Need diversity pressure to prevent convergence to local optima.
- **Sector Application:** Strategy geneticist needs to maintain diverse strategy population to adapt to regime changes. Convergence = fragility.
- **Fix Required:** Add diversity pressure to genome mutation algorithm
- **Assigned To:** [Pending assignment]

### M-003: Cross-Asset Correlation Missing
- **Source:** Chief Strategist
- **Severity:** MEDIUM
- **Description:** Market Cartographer (cross-asset correlation) not implemented.
- **Sector Application:** BTC drives all crypto. DXY drives BTC. Fed decisions drive everything. Without cross-asset correlation, risk management is blind.
- **Fix Required:** Implement Market Cartographer with BTC↔ETH↔SOL correlation + DXY/US10Y correlation
- **Assigned To:** [Pending assignment]

### M-004: Liquidity Modeling Missing
- **Source:** Chief Strategist
- **Severity:** MEDIUM
- **Description:** No modeling of order book depth, slippage on market orders, liquidity regime.
- **Sector Application:** At $10, liquidity isn't a concern. But as capital grows, liquidity becomes critical. Need to build this in early.
- **Fix Required:** Add basic liquidity modeling (order book depth, slippage estimation)
- **Assigned To:** [Pending assignment]

### M-005: Multi-Timeframe Analysis Missing
- **Source:** Chief Strategist
- **Severity:** MEDIUM
- **Description:** Single timeframe analysis only.
- **Sector Application:** Professional traders use multi-timeframe analysis (1h for trend, 15m for entry, 4h for context). Single timeframe = incomplete picture.
- **Fix Required:** Add multi-timeframe signal confluence
- **Assigned To:** [Pending assignment]

### M-006: FTS5 Search Limitations
- **Source:** Chief Strategist
- **Severity:** MEDIUM
- **Description:** FTS5 keyword search misses semantic similarity.
- **Sector Application:** "BTC dropped 10% on liquidation cascade" won't match "BTC flash crash due to leveraged unwind" without semantic search.
- **Fix Required:** Enhance FTS5 with ChromaDB vector similarity for semantic pattern matching
- **Assigned To:** [Pending assignment]

### M-011: Token Counting Approximate
- **Source:** LLM/AI Engineer
- **Severity:** MEDIUM
- **Description:** Token counting uses `len(text) // 4` heuristic with 20-30% error. Cost tracking is inaccurate.
- **Sector Application:** At $10 capital, every API call costs money. Inaccurate token counting means inaccurate cost tracking.
- **Fix Required:** Use tiktoken or actual tokenizer for accurate counting
- **Assigned To:** [Pending assignment]

### M-012: Prompts Not Optimized for Token Efficiency
- **Source:** LLM/AI Engineer
- **Severity:** MEDIUM
- **Description:** System prompts are 3x too verbose, max_tokens too high. Wastes tokens on every call.
- **Sector Application:** At DeepSeek-R1 prices ($0.14/M), verbose prompts are still wasteful. At scale, this adds up.
- **Fix Required:** Compress prompts, set appropriate max_tokens per task type
- **Assigned To:** [Pending assignment]

### M-013: No Multiple-Testing Correction for Factors
- **Source:** Research Analyst
- **Severity:** MEDIUM
- **Description:** No multiple-testing correction for 23 factors (Harvey et al. 2016, Bailey & López de Prado 2014). Risk of false discovery.
- **Sector Application:** With 23 factors, some will appear significant by chance. Need Bonferroni or FDR correction.
- **Fix Required:** Implement Deflated Sharpe Ratio and multiple-testing correction
- **Assigned To:** [Pending assignment]

### M-014: LLM Post-Training Readiness 3/10
- **Source:** LLM/AI Engineer
- **Severity:** MEDIUM
- **Description:** Data collection is complete but no fine-tuning pipeline exists. ShadowExtractor's rule extraction is a clever alternative but not true post-training.
- **Sector Application:** Jensen's "post-training inside the harness" is the breakthrough. Without fine-tuning pipeline, this is aspirational.
- **Fix Required:** Build basic fine-tuning pipeline or document rule-extraction as the chosen approach
- **Assigned To:** [Pending assignment]

### M-015: JSON-in-Column Anti-Pattern
- **Source:** Graph Engineer
- **Severity:** MEDIUM
- **Description:** pattern_matches and lessons stored as JSON strings in SQLite columns. Can't JOIN, can't query across, can't index.
- **Sector Application:** Pattern matching requires scanning JSON blobs instead of indexed queries. Performance degrades as pattern library grows.
- **Fix Required:** Normalize JSON columns to junction tables
- **Assigned To:** [Pending assignment]

### M-016: No Cross-Store Graph Traversal API
- **Source:** Graph Engineer
- **Severity:** MEDIUM
- **Description:** No API to traverse relationships across knowledge stores (e.g., "find all trades in regime X with strategy Y that resulted in lesson Z").
- **Sector Application:** Cross-store queries are essential for pattern discovery and strategy evolution. Without this, each store is an island.
- **Fix Required:** Build KnowledgeGraph traversal API
- **Assigned To:** [Pending assignment]

### M-017: No Temporal Graph Modeling
- **Source:** Graph Engineer
- **Severity:** MEDIUM
- **Description:** Regime transitions stored as flat list, not temporal graph. Can't model "regime A → regime B with probability P in time T".
- **Sector Application:** Regime transitions are temporal by nature. Flat storage misses transition probabilities and timing patterns.
- **Fix Required:** Implement temporal regime graph with transition probabilities
- **Assigned To:** [Pending assignment]

### M-018: ChromaDB Integration Not Implemented
- **Source:** Graph Engineer
- **Severity:** MEDIUM
- **Description:** ChromaDB vector store is designed but not actually wired. Semantic pattern search not functional.
- **Sector Application:** FTS5 keyword search misses semantic similarity. ChromaDB would enable "find patterns similar to current market condition" queries.
- **Fix Required:** Wire ChromaDB integration for semantic pattern matching
- **Assigned To:** [Pending assignment]

---

## LOW ISSUES (Future improvements)

### L-001: Execution Tracker (Fill Quality Analysis)
- **Source:** Chief Strategist
- **Severity:** LOW
- **Description:** Execution Tracker exists but not prioritized.
- **Sector Application:** Fill quality analysis helps optimize execution over time. Not critical at $10 but important at scale.
- **Fix Required:** Implement basic fill quality tracking
- **Assigned To:** [Pending assignment]

### L-002: Open Weights Viability
- **Source:** Chief Strategist
- **Severity:** LOW
- **Description:** Open weights models at 86% of frontier. Viable for research, needs validation for production.
- **Sector Application:** DeepSeek-R1 at $0.14/M tokens is 100x cheaper than Opus. If performance is sufficient, this enables extensive backtesting.
- **Fix Required:** Benchmark DeepSeek-R1 vs Opus on TSAR-specific trading tasks
- **Assigned To:** [Pending assignment]

---

## RECOMMENDATIONS BY PHASE

### Phase 0: Micro-Capital Foundation (Week 1-2)
1. [ ] Implement micro-capital mode (fee-aware sizing, exchange minimums)
2. [ ] Implement HMM regime detection
3. [ ] Implement Market Cartographer (cross-asset correlation)
4. [ ] Implement Macro Agent (Fed context, DXY, risk sentiment)
5. [ ] Add deterministic signal validation layer
6. [ ] Make paper trading mandatory gate

### Phase 1: Paper Trading Validation (Week 3-6)
7. [ ] Run 30-day paper trading with $10 simulated capital
8. [ ] Validate all strategies at $10 level
9. [ ] Wire shadow account into strategy genome mutation
10. [ ] Implement out-of-sample backtest validation

### Phase 2: First Live Capital (Week 7+)
11. [ ] Deploy with $10 real capital
12. [ ] Monitor for 30 days before scaling
13. [ ] Scale to $50 → $100 → $500 as performance validates

---

## STRATEGIC RECOMMENDATIONS

### Market Strategy (from Exchange & Market Strategist)
- **CRYPTO-ONLY until $10K capital** — Gold minimum trade on OANDA is 1 oz (~$3,300), impossible at $10. Forex micro-lots need ~$20+ margin.
- **Add Gold/Forex at $1K-$10K** — when capital permits meaningful positions
- **Binance is the right exchange** — $5-10 minimums, 0.1% fees, high liquidity

### Compounding Reality
- **1% daily is NOT sustainable** — academic consensus: 0.3-0.5%/day for top systems
- **At 0.3%/day:** $10 → $1B in ~11 years
- **The hardest phase is $10 → $10K** — most systems die here
- **TSAR's knowledge flywheel is its competitive advantage** — the flywheel compounds over time

### NVIDIA Integration (from NVIDIA Platform Specialist)
**Adopt NOW ($0 cost):**
- Expand NIM model catalog (add Nemotron 3 Ultra 550B, NV-Embed-v2)
- Promote NIM DeepSeek R1 to primary for t3_* tasks
- Apply to NVIDIA Inception program (free cloud credits)
- Download TensorRT-LLM container for benchmarking
- Evaluate Nemotron Nano 4B for edge inference

**Adopt at Scale:**
- CUDA Kernels ($5K+) — 100x faster Monte Carlo
- RAPIDS cuDF/cuML ($10K+) — 50x faster backtesting
- DGX Spark ($10K+, ~$3K) — 128GB unified memory, runs 200B models locally
- Post-Training with NeMo ($50K+) — fine-tune on proprietary trade data
- Triton Inference Server ($100K+) — multi-model GPU serving

**Hardware Roadmap:** None needed at $10-$100 (NIM free tier), RTX 4060 at $1K, RTX 4090 at $10K, DGX Spark at $15K+

**Warning:** Keep NVIDIA as a backend choice, not an architectural dependency. TSAR's interface layer is the moat.

### AI Landscape (from AI Landscape Strategist)
**Adopt NOW:**
- Sentiment pipeline (CryptoPanic, Fear & Greed, funding rates — all free)
- On-chain data feeds (whale tracking, DEX analytics)
- XGBoost/LightGBM signal scoring layer
- Financial RAG for knowledge grounding
- Chart analysis via vision model (Gemini 2.5 Pro)

**Prepare for Future:**
- Model fine-tuning pipeline
- Multi-asset expansion
- Adversarial robustness
- Regulatory compliance
- Real-time model updates

**Competitive Advantage:** No existing trading bot (Freqtrade, 3Commas, Pionex, Hummingbot) has a learning loop or LLM integration. TSAR's flywheel is genuinely unique.

---

*Tracker updated with findings from 11 of 14 councils.*
*Each issue will be assigned to a dedicated fixing team after all councils report.*
