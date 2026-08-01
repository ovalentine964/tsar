# Changelog

All notable changes to TSAR are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

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
