# Changelog

All notable changes to TSAR are documented here.

## [0.6.0] — 2026-07-30

### Added
- **NVIDIA Skills Integration**: 5 GPU-accelerated skills — cuFOLIO (portfolio optimization), cuOpt (multi-objective optimization), RAG Blueprint (enhanced retrieval), Nemo Evaluator (output quality), Nemotron Policy (risk policy generation)
- **Flywheel Orchestrator**: Auto-triggers the TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT loop
- **Sentiment Agent**: Aggregates sentiment from CryptoPanic API + Fear & Greed Index
- **ChromaDB Store**: Vector similarity search for semantic pattern matching
- **Knowledge Graph**: Cross-store graph traversal with recursive CTEs
- **RAG Blueprint Search**: NVIDIA-enhanced retrieval with semantic chunking and reranking
- **Paper Execution Engine**: Simulated order execution against live market data
- **cuFOLIO Backend**: GPU-accelerated Mean-CVaR portfolio optimization
- **cuOpt Optimizer**: Multi-objective strategy parameter optimization
- **ML Signal Scorer**: XGBoost/LightGBM hybrid signal scoring
- **LLM Evaluation Framework**: Signal accuracy and prediction quality tracking
- **Token Counter**: Accurate token counting with tiktoken (replaces heuristic)
- **Prometheus Exporter**: Full metrics export with graceful degradation
- **Watchdog**: External process health monitor for kill switch reliability
- **Nemotron Policy Generator**: AI-generated adaptive risk policies
- **DB Connection Pool**: Thread-safe SQLite connection pool with WAL mode
- **JWT Authentication**: API endpoints protected with token-based auth
- **CORS Fix**: Strict origin validation via `TSAR_CORS_ORIGINS`
- **Telegram Auth**: Chat ID verification for bot commands
- **Micro-capital Mode**: Adjusted risk parameters for accounts under $50
- **Fee-Aware Sizing**: Kelly calculation accounts for exchange fees
- **Phased Recovery**: Graduated re-entry after circuit breaker trips
- **Economic Blackout**: Auto-block trading around FOMC, CPI, NFP events
- **Grafana Dashboards**: Pre-built monitoring dashboards
- **Prometheus Config**: Scraping configuration for all TSAR metrics
- **Database Migrations**: Junction tables and temporal regime graph
- **Benchmark Script**: LLM performance benchmarking utility
- **config/nvidia_skills.yaml**: Centralized NVIDIA skills configuration

### Changed
- **17 council reviews** completed — 72 issues found and addressed
- **12 fix teams** executed across security, risk, strategy, AI, infrastructure, knowledge, market, and NVIDIA domains
- `config/models.yaml` updated with NVIDIA NIM provider and model definitions
- `config/risk.yaml` consolidated as single source of truth for all risk parameters
- `config/tsar.yaml` updated with current working defaults
- `.env.example` updated with all required variables (NVIDIA, CORS, Redis, TSAR API)
- `README.md` overhauled: NVIDIA skills section, updated architecture, removed OANDA/MT5 references
- Agent count updated from 10 to 12 (Flywheel Orchestrator, Sentiment Agent)
- Knowledge store count updated from 5 to 6 (ChromaDB added)
- LLM routing updated with NVIDIA NIM as primary for Tier 3 tasks
- Architecture diagram updated with new agents and components

### Fixed
- Security: JWT auth, CORS origin validation, Telegram chat ID verification
- Risk: Fee-aware Kelly sizing, micro-capital mode, phased recovery protocol
- Strategy: HMM regime detection hardening, multi-timeframe correlation
- AI: Sentiment pipeline, XGBoost scoring, hallucination mitigation
- Market: WebSocket streaming reliability, paper execution engine
- Infrastructure: CI/CD for all languages, Docker hardening, monitoring
- Knowledge: ChromaDB integration, graph traversal, temporal regime graph
- Kill Switch: Watchdog process, dual-write, stale-process detection

## [0.5.0] — 2026-07-27

### Added
- **Phase 1A — FTS5 Search**: Full-text search across all knowledge stores (trade memory, lessons, patterns, genomes) using SQLite FTS5
- **Phase 1B — Shadow Account**: Paper trading mirror that runs hypothetical trades alongside real ones and extracts lessons from counterfactual outcomes
- **Phase 2 — Backtest Engine**: Walk-forward validation, Monte Carlo simulation, and factor benchmarking for strategy evaluation
- **Phase 3 — Mandate Gate**: Human authorization boundary — live trading requires a committed mandate with explicit rules; paper mode is exempt
- **Phase 4 — Factor Library**: Alpha factor discovery and ranking with IC/IR scoring, category taxonomy, and strategy integration
- **Integration Wiring**: All components connected via CloudEvents pub/sub and FastAPI REST endpoints
- **Flutter Mobile App**: Cross-platform mobile app with dashboard, trade history, risk monitoring, factor browser, kill switch, and knowledge search (28+ API endpoints)
- **CI/CD**: GitHub Actions workflows for Python (lint/test) and Flutter (build APK)
- **GitHub Pages APK**: Pre-built Android APK available via GitHub Releases

### Changed
- Project structure reorganized: council reviews moved from `analysis/council/` to `docs/council/`
- `.gitignore` updated: `data/` directory, `*.db-shm`, `Vibe-Trading/`, Flutter `build/` added
- README updated with current status, mobile app section, component descriptions, and project structure

### Removed
- Stale `__pycache__/` directories cleaned from repository
- `.db-shm` and `.db-wal` files removed from tracking

## [0.4.0] — 2026-07-24

### Added
- Council of 5 governance structure (Co-Founder, Chief Architect, Chief Risk Officer, Chief Strategist, Chief Engineer)
- 4 council reviews: 55 issues found and addressed
- Hybrid architecture approval: Python Day 1, Rust Level 2, C++ Level 3+
- Engineering team plan with 5-member swarm design
- Integration team reviews (3 teams)

## [0.3.0] — 2026-07-23

### Added
- Super Agent validation: 8.8/10 score across 10 criteria
- Architecture v3.0.0: future-ready Python + Rust + C++ via abstract interfaces
- 5 abstract base classes (ExchangeGateway, PricingEngine, ExecutionEngine, RiskEngine, LLMProvider)
- BackendRegistry for config-driven backend selection
- 10-agent system design
- 5 knowledge stores
- CloudEvents messaging layer

## [0.2.0] — 2026-07-22

### Added
- 14 research reports analyzed
- Gap resolution matrix
- 7 fix specs (A through G): LLM abstraction, configurable models, CloudEvents, improvement measurement, resource limits, strategy hardening, future-ready architecture

## [0.1.0] — 2026-07-21

### Added
- Initial project structure
- Trading Super Agent blueprint
- Market analysis and feasibility research
- Architecture design and spec documents
