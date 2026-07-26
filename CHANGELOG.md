# Changelog

All notable changes to TSAR are documented here.

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
