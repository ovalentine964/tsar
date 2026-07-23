# TSAR — Trading Super Agent for Returns

> **Autonomous capital compounding under strict risk constraints.**

[![Architecture](https://img.shields.io/badge/Architecture-Complete-green?style=for-badge)]()
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-badge)]()
[![Status](https://img.shields.io/badge/Status-In%20Development-yellow?style=for-badge)]()

## What Is TSAR?

TSAR is a **self-improving market intelligence system** — not a trading bot. It finds statistical edges in liquid markets, sizes them correctly, executes them flawlessly, and gets measurably better at all three with every single trade.

**One job:** Autonomous capital compounding under strict risk constraints.

**The difference:** A trading bot is static code. TSAR is a living knowledge system. You can copy a bot's code. You cannot copy TSAR's knowledge.

## Architecture

```
Signal Agent → Risk Agent (VETO) → Execution Agent
     ↓              ↓                    ↓
  Finds edges   Approves/Rejects    Places orders
                    ↓
            Learning Loop
         (gets smarter every trade)
```

## The Flywheel

```
TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE
  ↑                                                │
  └────────────────────────────────────────────────┘
```

Every trade generates proprietary data. Every reflection improves the system. Every adaptation makes the next trade better.

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Brain | Python 3.12 | Agent orchestration, LLM, strategy, risk |
| Muscle | Rust | Data processing, WebSocket, execution |
| Bridge | PyO3 | Python ↔ Rust interop |
| Database | SQLite + FTS5 | Trade memory, lessons, patterns |
| Cache | Redis | Real-time state |
| Exchange | ccxt | 100+ exchanges |
| LLM | Ollama + DeepSeek-R1 | Free-tier reasoning |
| Interface | Telegram | Commands + alerts |

## Markets

- **Crypto:** Binance (BTC, ETH, SOL)
- **Gold:** OANDA via MT5 (XAU/USD)
- **Forex:** OANDA via MT5 (EUR/USD, GBP/USD)

## Day1 Build

- 3 agents (Signal → Risk → Execution)
- 10 tools
- 1 database (tsar.db)
- 1 strategy (Mean Reversion on BTC/USDT)
- Forward demo trading (Binance testnet, live data)
- Telegram bot (8 commands)
- Free models (Ollama + DeepSeek-R1)

## Project Structure

```
tsar/
├── docs/                    # Documentation
│   ├── research/           # 13 research reports
│   ├── architecture/       # 9 architecture specs
│   └── reviews/            # Lead Architect reviews
├── src/                    # Source code
│   ├── agents/            # Signal, Risk, Execution agents
│   ├── exchange/          # Binance, OANDA connectors
│   ├── strategy/          # Trading strategies
│   ├── risk/              # Risk governor
│   ├── learning/          # Learning loop
│   ├── data/              # Database, cache
│   ├── telegram/          # Telegram bot
│   └── rust/              # Rust performance layer
├── config/                 # Configuration files
├── tests/                  # Test suite
├── migrations/             # Database migrations
├── docker/                 # Docker setup
├── .github/                # CI/CD
├── pyproject.toml          # Python dependencies
├── Cargo.toml              # Rust dependencies
├── Makefile                # Common commands
└── README.md               # This file
```

## Documentation

- [Research Validation](docs/research/VALIDATION_COMPLETE.md) — 13 research agents
- [Architecture Complete](docs/architecture/ARCHITECTURE_COMPLETE.md) — 9 architecture agents
- [Day1 Architecture](docs/architecture/DAY1_ARCHITECTURE.md) — Buildable in 2-4 weeks
- [Gap Resolution](docs/architecture/ARCHITECTURE_CONSOLIDATION.md) — All gaps fixed
- [Lead Architect Review](docs/reviews/LEAD_ARCHITECT_REVIEW.md) — CONDITIONAL PASS

## Status

```
1. ✅ VALIDATE — COMPLETE (13 research agents)
2. ✅ ARCHITECT — COMPLETE (9 architecture agents + 2 lead reviews)
3. ⬜ ENGINEER — Ready to start
4. ⬜ REVIEW & TEST
5. ⬜ COMMIT TO GITHUB
```

## License

MIT

---

*Built by Valentine Owuor. Powered by AI. Designed for retail traders.*
