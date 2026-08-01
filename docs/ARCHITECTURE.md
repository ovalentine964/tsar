# TSAR — Architecture

## System Overview

TSAR is a self-improving autonomous trading system built on a layered architecture with abstract interfaces. The system compounds knowledge through every trade cycle.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TSAR SUPER AGENT                             │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    AGENT LAYER                                │  │
│  │                                                               │  │
│  │  ┌────────────┐   ┌────────────┐   ┌─────────────────────┐   │  │
│  │  │  Signal    │──▶│    Risk    │──▶│  Execution          │   │  │
│  │  │  Scout     │   │  Guardian  │   │  Sniper             │   │  │
│  │  └────────────┘   └────────────┘   └─────────────────────┘   │  │
│  │        │                │                   │                 │  │
│  │        ▼                ▼                   ▼                 │  │
│  │  ┌────────────┐   ┌────────────┐   ┌─────────────────────┐   │  │
│  │  │  Flywheel  │   │  Sentiment │   │  Regime Detector    │   │  │
│  │  │  Orch.     │   │  Agent     │   │  (HMM)              │   │  │
│  │  └────────────┘   └────────────┘   └─────────────────────┘   │  │
│  │        │                │                   │                 │  │
│  │        ▼                ▼                   ▼                 │  │
│  │  ┌────────────┐   ┌────────────┐   ┌─────────────────────┐   │  │
│  │  │  Trade     │   │  Strategy  │   │  Market             │   │  │
│  │  │  Philosopher│  │  Geneticist│   │  Cartographer       │   │  │
│  │  └────────────┘   └────────────┘   └─────────────────────┘   │  │
│  │        │                │                   │                 │  │
│  │        ▼                ▼                   ▼                 │  │
│  │  ┌────────────┐   ┌────────────┐                             │  │
│  │  │  Macro     │   │  Execution │                             │  │
│  │  │  Agent     │   │  Tracker   │                             │  │
│  │  └────────────┘   └────────────┘                             │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    EVENT BUS (Redis)                          │  │
│  │  CloudEvents v1.0 pub/sub — async message passing            │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 INTERFACE LAYER (the contract)                │  │
│  │                                                               │  │
│  │  ExchangeGateway  │  PricingEngine   │  ExecutionEngine      │  │
│  │  RiskEngine       │  LLMProvider     │  BackendRegistry      │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 BACKEND LAYER (config-driven)                 │  │
│  │                                                               │  │
│  │   ┌──────────┐     ┌──────────┐     ┌──────────┐             │  │
│  │   │  Python  │     │   Rust   │     │   C++    │             │  │
│  │   │ (Day 1)  │     │ (Level 2)│     │ (Level 3)│             │  │
│  │   └──────────┘     └──────────┘     └──────────┘             │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 KNOWLEDGE LAYER                               │  │
│  │                                                               │  │
│  │  TradeMemory │ StrategyGenomes │ RegimeState                 │  │
│  │  PatternLibrary │ LessonArchive │ ChromaDB                   │  │
│  │  KnowledgeGraph │ FTS5 Search   │ RAG Blueprint              │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 RISK & GOVERNANCE                             │  │
│  │                                                               │  │
│  │  KillSwitch │ MandateGate │ Watchdog │ GuardState            │  │
│  │  Governor │ Guards │ Drawdown │ PositionSizer                │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Agent Pipeline

### Signal → Risk → Execution

```
Market Data
    │
    ▼
┌──────────────┐
│ SignalScout  │  Finds statistical edges via technical analysis,
│              │  sentiment aggregation, and pattern recognition
└──────┬───────┘
       │ signal (symbol, direction, confidence, factors)
       ▼
┌──────────────┐
│ RiskGuardian │  VETO power — deterministic checks:
│              │  • Mandate compliance
│              │  • Position sizing (Kelly criterion)
│              │  • Drawdown limits
│              │  • Behavioral guards
│              │  • Economic blackout calendar
└──────┬───────┘
       │ approved signal
       ▼
┌──────────────┐
│ Execution    │  Places and monitors orders:
│ Sniper       │  • Order routing
│              │  • Fill tracking
│              │  • Slippage monitoring
│              │  • Stop-loss / take-profit management
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Trade        │  Post-trade reflection:
│ Philosopher  │  • Outcome analysis
│              │  • Lesson extraction
│              │  • Pattern discovery
│              │  • Knowledge store updates
└──────────────┘
```

### Supporting Agents

| Agent | Trigger | Action |
|-------|---------|--------|
| **FlywheelOrchestrator** | Post-trade | Chains OBSERVE → REFLECT → EXTRACT → ADAPT |
| **RegimeDetector** | Every cycle | HMM classification (trending, ranging, volatile, crash) |
| **SentimentAgent** | Every cycle | CryptoPanic + Fear & Greed aggregation |
| **StrategyGeneticist** | Periodic | Mutates strategy genomes based on performance |
| **MarketCartographer** | Periodic | Cross-asset correlation updates |
| **MacroAgent** | Daily | Economic calendar and event awareness |
| **ExecutionTracker** | Every trade | Fill quality and slippage analysis |

---

## EventBus Architecture

TSAR uses Redis-backed CloudEvents for async inter-agent communication.

```
┌─────────────┐                    ┌─────────────┐
│  Agent A     │ ──publish──▶      │  Redis Bus  │
│  (SignalScout)│                   │  (channels)  │
└─────────────┘                    └──────┬──────┘
                                          │
                            ┌─────────────┼─────────────┐
                            ▼             ▼             ▼
                     ┌──────────┐  ┌──────────┐  ┌──────────┐
                     │ Agent B  │  │ Agent C  │  │ Agent D  │
                     │(RiskGuard)│ │(ExecSnip)│ │(Philos.)  │
                     └──────────┘  └──────────┘  └──────────┘
```

**Event Types:**
- `tsar.signal.detected` — New trading signal found
- `tsar.signal.approved` — Risk guardian approved signal
- `tsar.signal.rejected` — Risk guardian vetoed signal
- `tsar.order.placed` — Order submitted to exchange
- `tsar.order.filled` — Order filled
- `tsar.trade.closed` — Trade completed with P&L
- `tsar.regime.changed` — Market regime transition
- `tsar.risk.alert` — Risk threshold breached
- `tsar.kill.activated` — Kill switch triggered

---

## Risk System

### Multi-Layer Protection

```
┌─────────────────────────────────────────────────────────┐
│                    RISK GOVERNANCE                       │
│                                                         │
│  Layer 1: MANDATE GATE                                  │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Human authorization boundary                     │    │
│  │ • status: DRAFT | ACTIVE | SUSPENDED            │    │
│  │ • Symbol whitelist, max position, daily limits   │    │
│  │ • Paper mode exempt                              │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Layer 2: GOVERNOR                                      │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Pre-trade deterministic checks                   │    │
│  │ • Daily loss limit (2%)                          │    │
│  │ • Max drawdown (5%)                              │    │
│  │ • Max open positions (3)                         │    │
│  │ • Min risk/reward ratio (2:1)                    │    │
│  │ • Fee-aware Kelly position sizing                │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Layer 3: GUARDS                                        │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Anti-behavioral protection                       │    │
│  │ • Revenge trading guard                          │    │
│  │ • Greed guard (excessive position scaling)       │    │
│  │ • FOMO guard (chasing momentum)                  │    │
│  │ • Overconfidence guard (winning streak hubris)   │    │
│  │ • Economic blackout (FOMC, CPI, NFP)             │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Layer 4: KILL SWITCH                                   │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Emergency halt — dual-write persistence          │    │
│  │ • File + Redis dual-write                        │    │
│  │ • Watchdog heartbeat monitoring                  │    │
│  │ • Auto-cancel orders + flatten positions         │    │
│  │ • Manual /resume required to reactivate          │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## DeFi Integration

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DEFI LAYER                                │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │
│  │ WalletManager │  │  DexExecutor  │  │ IntentExecutor│   │
│  │               │  │               │  │               │   │
│  │ • Fernet enc. │  │ • 1inch (EVM) │  │ • CoW Protocol│   │
│  │ • Multi-chain │  │ • Jupiter     │  │ • UniswapX    │   │
│  │ • Key rotation│  │   (Solana)    │  │ • 1inch Fusion│   │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘   │
│          │                  │                   │           │
│  ┌───────┴───────┐  ┌───────┴───────┐  ┌───────┴───────┐   │
│  │ SettlementEng. │  │ L2Optimizer   │  │ BridgeClient  │   │
│  │               │  │               │  │               │   │
│  │ • Escrow      │  │ • Gas compare │  │ • Wormhole    │   │
│  │ • Multi-sig   │  │ • Batch TX    │  │ • LayerZero   │   │
│  │ • Settlement  │  │ • Chain select│  │ • Axelar      │   │
│  └───────────────┘  └───────────────┘  └───────────────┘   │
│                                                             │
│  Supported Chains:                                          │
│  Ethereum │ Polygon │ Arbitrum │ Base │ Solana              │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Testnet-first** — All DeFi operations default to testnets (Sepolia, Solana devnet)
2. **Encrypted wallets** — Private keys encrypted with Fernet at rest
3. **MEV protection** — Private mempool submission, sandwich detection
4. **Slippage control** — Configurable tolerance, automatic deadline extension
5. **Graceful degradation** — DeFi components optional; CEX trading unaffected

---

## Telegram Bot Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  TELEGRAM BOT                             │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Message      │  │ Command      │  │ Notification │   │
│  │ Classifier   │  │ Handler      │  │ Engine       │   │
│  │              │  │              │  │              │   │
│  │ • Intent     │  │ • /status    │  │ • Trade      │   │
│  │   detection  │  │ • /discuss   │  │   alerts     │   │
│  │ • Context    │  │ • /why       │  │ • Risk       │   │
│  │   routing    │  │ • /perf      │  │   warnings   │   │
│  └──────┬───────┘  └──────────────┘  └──────────────┘   │
│         │                                                │
│  ┌──────┴───────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Conversation │  │ Credentials  │  │ Security     │   │
│  │ State Machine│  │ Manager      │  │ Audit        │   │
│  │              │  │              │  │              │   │
│  │ • Setup      │  │ • Fernet enc │  │ • Chat ID    │   │
│  │   wizard     │  │ • Never      │  │   verify     │   │
│  │ • Trade      │  │   echoed     │  │ • Audit log  │   │
│  │   proposals  │  │ • Key rotate │  │ • Rate limit │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
│                                                          │
│  Inline Keyboard Flow:                                   │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐              │
│  │ Proposal │──▶│ Approve │──▶│ Execute │              │
│  │   sent   │   │ Reject  │   │ Report  │              │
│  │          │   │ Modify  │   │         │              │
│  └─────────┘    └─────────┘    └─────────┘              │
└──────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Trade Lifecycle

```
1. Market data arrives (WebSocket or REST poll)
2. SignalScout evaluates technical indicators + sentiment
3. Signal published to EventBus: tsar.signal.detected
4. RiskGuardian receives signal, runs deterministic checks
5. If approved: tsar.signal.approved → ExecutionSniper
6. If rejected: tsar.signal.rejected → logged to TradeMemory
7. ExecutionSniper places order via ExecutionEngine
8. Order fills reported: tsar.order.filled
9. TradePhilosopher analyzes outcome, extracts lessons
10. FlywheelOrchestrator triggers: OBSERVE → REFLECT → EXTRACT → ADAPT
11. Knowledge stores updated (lessons, patterns, genomes)
12. StrategyGeneticist may mutate strategy based on results
```

### Knowledge Compounding

```
Trade Outcome ──▶ Lesson Extraction ──▶ Lesson Archive
     │                                       │
     ▼                                       ▼
Pattern Discovery ──▶ Pattern Library   Strategy Update
     │                                       │
     ▼                                       ▼
Regime Correlation ──▶ Regime State     Genome Mutation
     │                                       │
     └───────────────────────────────────────┘
                        │
                        ▼
              BETTER NEXT TRADE
```

---

## Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Python first** | Python 3.12 as Day 1 backend | Fastest iteration, richest ecosystem (ccxt, pandas, FastAPI) |
| **Abstract interfaces** | 5 base classes | Backend swaps without agent code changes |
| **SQLite + FTS5** | Single-file database | Zero-config, embedded, excellent for single-user trading |
| **Redis** | Event bus + cache | Fast pub/sub, TTL support, proven at scale |
| **CloudEvents** | Event protocol | Standard spec, vendor-neutral, good tooling |
| **Docker Compose** | Orchestration | Reproducible, simple, single-command deployment |
| **PyO3 + C FFI** | Rust/C++ bridge | Zero-copy interop, type-safe bindings |
| **Fernet encryption** | Wallet key storage | Symmetric encryption, simple, auditable |
