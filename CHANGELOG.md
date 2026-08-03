# Changelog

All notable changes to TSAR are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.3.0] — 2026-08-03

### Added
- **Azure Free Tier Deployment**: One-command deployment to Azure Container Instances ($0/month for first 12 months). Includes `deploy/azure/deploy-free-tier.sh`, `.env.free-tier` template, `FREE_TIER_GUIDE.md`, and `health-check.sh`.
- **TLS Termination**: Nginx reverse proxy with TLS support in `docker-compose.yml`. Self-signed cert generation script in `deploy/tls/`. Uvicorn TLS via `TSAR_SSL_CERTFILE`/`TSAR_SSL_KEYFILE` env vars.
- **App Icon**: Custom TSAR crown + circuit board icon. Android adaptive icon (API 26+) with vector foreground/background. Master SVG in `assets/tsar_icon.svg`. Full branding guide in `docs/BRANDING.md`.
- **Lightweight Vector Store**: Numpy-only vector store with 3-gram character hashing (`src/knowledge/lightweight_vector_store.py`). Drop-in replacement for ChromaDB — no external dependencies. Auto-fallback when ChromaDB unavailable.
- **Quantum-Inspired Annealing Optimizer**: Simulated quantum annealing method in `CuOptStrategyOptimizer`. Uses tunneling heuristics and thermal fluctuations for better global optimization. Always available (pure Python + numpy).
- **Agent Loop Integration**: `BaseAgent.init_agent_loop()` and `run_with_agent_loop()` methods for LLM-driven tool-calling agents via OpenHarness.
- **Secret Validation**: Refuses to start with weak/default secrets (H-010). Validates `TSAR_API_KEY`, `REDIS_PASSWORD`, exchange credentials.
- **Credential Setup Guide**: Three setup paths — Telegram bot `/setup`, manual `.env`, or Flutter mobile app.

### Changed
- **ChromaDB Store**: Now auto-falls back to `LightweightVectorStore` when ChromaDB unavailable.
- **Rust Backends**: `TSAR_RUST_BUILD=0` env var forces pure-Python fallback. Consistent across `__init__.py` and `defi_fallback.py`.
- **Docker Compose**: Full production stack now includes nginx TLS proxy with resource limits and security hardening.
- **Backend Registry**: Improved registration with better error handling.
- **LLM Router**: Enhanced model routing with fallback chains.
- **Risk Governor**: Additional guard conditions and improved logging.
- **CI/CD**: Updated workflow with Flutter APK build and Rust build steps.

### Fixed
- **CCXT Gateway**: Connection stability improvements and error handling.
- **CCXT Exec Engine**: Order execution reliability and retry logic.
- **DeFi Executor**: Fallback paths for missing dependencies.
- **OpenAI Provider**: Token counting and cost tracking fixes.
- **Blockchain Rules Enforcer**: Consistent force-python mode.

## [0.2.2] — 2026-08-01

### Added
- **News Gap Implementation**: 5 new intelligence sources — Whale Alert (large on-chain transfers), SEC/CFTC (regulatory filings), Exploit Alerts (security incidents), Twitter/X (influencer sentiment), Reddit/Discord (community sentiment). Total: 43 tools.
- **LLM News Verification**: All news signals pass through LLM verification before triggering trades. Source accuracy tracking over time.
- **On-Chain Rules**: Solidity smart contracts for trustless risk enforcement — TSARKillSwitch, TSARMandate, TSARAuditTrail, TSARGovernance, TSARPositionLimits. Dual enforcement model: off-chain (fast, Python) + on-chain (trustless, Solidity).
- **Rust EVM Bindings**: `rules-enforcer` crate with EVM client for on-chain kill switch, mandate verification, and position limits. Python bridge for blockchain enforcer.
- **Blockchain Deploy Script**: `scripts/deploy-contracts.sh` for smart contract deployment to testnets.
- **Production Dockerfile**: Multi-stage build with Rust compilation, optimized for production.
- **Docker Compose v2**: Full production stack — TSAR app, Redis, Prometheus, Grafana.
- **Azure Deploy Script**: `scripts/deploy-azure.sh` for Container Instances deployment.
- **.env.template**: Production environment template with all required variables.
- **OpenHarness Agent Loop**: Streaming tool-call cycle adapted for TSAR — LLM stream → tool execute → result merge → retry with backoff. Token counting, cost tracking, parallel tool execution.
- **Signal Quality System**: `config/signal_quality.yaml` with signal quality thresholds and filtering.
- **News Timing Execution Report**: Analysis of news impact timing and optimal execution windows.
- **Entry/Exit Optimization**: Entry and exit point optimization strategies.
- **Council Reports**: Blockchain for Rules (8.5/10), News Detection (7/10), Blockchain for Performance (3/10), Rust-Blockchain Bridge integration.

### Changed
- **CI/CD**: Updated GitHub Actions workflow with Rust build step.
- **Dockerfile**: Multi-stage build with Rust compilation support.
- **config/blockchain.yaml**: New configuration for blockchain rules, chain endpoints, contract addresses.

## [0.2.1] — 2026-08-01

### Added
- **Scenario Prevention**: 5 new modules for institutional-grade loss prevention — Flash Crash Detector, Stop Hunt Detector, Whipsaw Detector, Liquidity Analyzer, Correlation Breaker.
- **Paper Trading Gate**: 75% win rate requirement before live trading. Gate requires: 50 trades + 7 days + 75% win rate. Paper engine fully wired with 0 balance fix.
- **Rust Crates (4 new)**: `mev-scanner` (mempool monitoring, sandwich detection), `gas-optimizer` (multi-chain gas comparison), `dex-aggregator` (cross-DEX route optimization), `price-feed` (aggregated price feed with staleness detection). Total: 14 crates.
- **PyO3 Bridge**: Rust ↔ Python bridge files for seamless interop between performance layer and agent brain.
- **Trade Education Module**: `src/education/` — structured trade education content and learning paths.
- **DeFi Fallback**: Python fallback for Rust compilation — system works without Rust toolchain.
- **Config Updates**: `config/risk.yaml` with scenario prevention parameters, `config/default.yaml` with new risk settings, `config/mandate.yaml` with win rate gate.

### Changed
- **Mandate Gate**: Now requires 75% win rate (previously: 30 profitable trades). Stricter but more reliable.
- **Rust Cargo.toml**: Added 4 new crate workspaces.
- **Risk Parameters**: Updated `risk.yaml` with scenario prevention thresholds.

### Fixed
- **Paper Trading Engine**: Engine properly wired, zero balance initialization.
- **DeFi Backend**: Graceful degradation when Rust compilation unavailable.

## [0.2.0] — 2026-08-01

### Added
- **Full Superagent Wiring**: All 10 agents connected to shared resources (knowledge stores, engines, event bus, kill switch) via the orchestrator
- **DeFi Integration**: Complete on-chain execution layer — DEX execution (1inch + Jupiter), intent-based trading (CoW Protocol, UniswapX, 1inch Fusion), cross-chain bridging (Wormhole, LayerZero, Axelar), L2 gas optimization, smart contract settlement, encrypted wallet management
- **Anti-Loss System**: Multi-layer loss prevention — position recovery, leverage guard, connection monitor, anti-behavioral guards (revenge, greed, FOMO, overconfidence), economic blackout calendar
- **Telegram Interactive Bot**: Full trading partner with conversational setup wizard, inline keyboard trade proposals (approve/reject/modify), post-trade reports, market discussion commands (`/discuss`, `/why`, `/performance`, `/regime`, `/flywheel`, `/ask`), encrypted credential storage, message classifier, notification engine
- **Telegram Security Architecture**: Chat ID verification, security audit logging, Fernet-encrypted credential storage
- **Deployment Scripts**: Azure Container Instances deployment with spot instances, monitoring setup, environment templates
- **CI/CD**: GitHub Actions workflows for Python linting/testing, Flutter build, APK generation
- **Grafana Dashboards**: Pre-built monitoring dashboards with alerting rules
- **Database Migrations**: Junction tables and temporal regime graph schemas

### Changed
- **pyproject.toml**: Version bumped to 0.2.0; added `defi` optional dependencies (web3, solana, solders, cryptography, eth-account)
- **README.md**: Complete rewrite — professional project description, architecture overview, quick start guide, contributing guidelines, badge indicators
- **INSTALL.md**: Complete rewrite — prerequisites, step-by-step installation, environment variables documentation, troubleshooting section
- **config/default.yaml**: Added DeFi configuration section (testnet, wallet, slippage, RPC endpoints), watchdog configuration
- **.env.example**: Documented all required and optional variables with generation commands

### Fixed
- Agent resource wiring — all agents now receive shared knowledge stores, engines, and event bus references at startup
- Kill switch callback wiring — cancel_orders and flatten_positions callbacks properly connected to execution engine

## [0.1.0] — 2026-07-30

### Added
- **Core System**: 12 agents, 6 knowledge stores, abstract interface layer, backend registry
- **NVIDIA Skills**: cuFOLIO, cuOpt, RAG Blueprint, Nemo Evaluator, Nemotron Policy
- **Flywheel Orchestrator**: Self-improvement loop automation
- **Sentiment Agent**: CryptoPanic + Fear & Greed aggregation
- **ChromaDB Store**: Vector similarity search
- **Knowledge Graph**: Cross-store graph traversal with recursive CTEs
- **Paper Execution Engine**: Simulated order execution against live data
- **ML Signal Scorer**: XGBoost/LightGBM hybrid scoring
- **Watchdog**: External process health monitor
- **JWT Authentication**: API endpoint protection
- **Micro-capital Mode**: Risk parameters for accounts under $50
- **Fee-Aware Sizing**: Kelly criterion with exchange fee awareness
- **Phased Recovery**: Graduated re-entry after circuit breaker
- **Economic Blackout**: Auto-block trading around FOMC, CPI, NFP
- **Factor Library**: IC/IR scoring, category taxonomy, 28 factors
- **Backtest Engine**: Walk-forward, Monte Carlo, factor benchmarking
- **Mandate Gate**: Human authorization boundary for live trading
- **FTS5 Search**: Full-text search across all knowledge stores
- **Shadow Account**: Paper trading mirror with lesson extraction
- **Flutter Mobile App**: Dashboard, trades, risk, factors, kill switch, knowledge search
- **Prometheus + Grafana**: Metrics export and monitoring dashboards
- **17 Council Reviews**: Architecture, security, strategy, and quality reviews

## [0.0.1] — 2026-07-21

### Added
- Initial project structure
- Trading Super Agent blueprint
- Market analysis and feasibility research
- Architecture design documents
