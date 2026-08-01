# TSAR — Architecture

## System Overview

TSAR is a self-improving autonomous trading system built on a layered architecture with abstract interfaces. The system compounds knowledge through every trade cycle, implementing Jensen's superagent blueprint — a single, deep, domain-specific agent that owns the entire vertical.

**Three pillars:**
- **Python brain** — agents, LLM orchestration, strategy, risk, news analysis
- **Rust muscles** — WebSocket, tick processing, order execution, MEV protection, gas optimization
- **Blockchain settlement** — on-chain kill switch, mandate, audit trail, governance

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TSAR SUPER AGENT                             │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    AGENT LAYER (12 agents)                    │  │
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
│  │  ┌────────────┐   ┌────────────┐   ┌─────────────────────┐   │  │
│  │  │  Macro     │   │  Information│  │  News Gatekeeper    │   │  │
│  │  │  Agent     │   │  Agent     │   │                     │   │  │
│  │  └────────────┘   └────────────┘   └─────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 OPENHARNESS AGENT LOOP                        │  │
│  │  LLM Stream → Tool Execute → Result Merge → Retry w/Backoff  │  │
│  │  Token counting · Cost tracking · Parallel execution          │  │
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
│  │   │ (Day 1)  │     │ (14 crates)    │ (Level 3)│             │  │
│  │   └──────────┘     └──────────┘     └──────────┘             │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 KNOWLEDGE LAYER (6 stores)                    │  │
│  │                                                               │  │
│  │  TradeMemory │ StrategyGenomes │ RegimeState                 │  │
│  │  PatternLibrary │ LessonArchive │ ChromaDB                   │  │
│  │  KnowledgeGraph │ FTS5 Search   │ RAG Blueprint              │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 BLOCKCHAIN RULES LAYER                        │  │
│  │                                                               │  │
│  │  Solidity: KillSwitch · Mandate · AuditTrail · Governance     │  │
│  │  Rust: EVM bindings · Position limits · Kill switch client     │  │
│  │  Python: Blockchain enforcer · Dual enforcement                │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 RISK & GOVERNANCE                             │  │
│  │                                                               │  │
│  │  KillSwitch │ MandateGate │ Watchdog │ GuardState            │  │
│  │  Governor │ Guards │ Drawdown │ PositionSizer                │  │
│  │  Scenario Prevention: FlashCrash · StopHunt · Whipsaw · ...   │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Agent Pipeline

### Signal → Risk → Execution

```
Market Data + News + On-Chain
    │
    ▼
┌──────────────┐
│ SignalScout  │  Finds statistical edges via technical analysis,
│              │  sentiment aggregation, pattern recognition, and news signals
└──────┬───────┘
       │ signal (symbol, direction, confidence, factors, news_context)
       ▼
┌──────────────┐
│ RiskGuardian │  VETO power — deterministic checks:
│              │  • Mandate compliance
│              │  • Position sizing (Kelly criterion)
│              │  • Drawdown limits
│              │  • Behavioral guards
│              │  • Economic blackout calendar
│              │  • Scenario prevention (flash crash, stop hunt, whipsaw)
│              │  • News gate verification
└──────┬───────┘
       │ approved signal
       ▼
┌──────────────┐
│ Execution    │  Places and monitors orders:
│ Sniper       │  • Order routing (CEX + DEX)
│              │  • Fill tracking
│              │  • Slippage monitoring
│              │  • Stop-loss / take-profit management
│              │  • MEV protection (Rust mempool monitor)
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
| **InformationAgent** | Real-time | Multi-source news aggregation and impact scoring |
| **NewsGatekeeper** | Real-time | News signal gating with LLM verification |
| **ExecutionTracker** | Every trade | Fill quality and slippage analysis |

---

## OpenHarness Agent Loop

TSAR adapts the OpenHarness streaming tool-call pattern for its agent loop:

```
┌─────────────────────────────────────────────────────────┐
│                 Agent Loop                               │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐           │
│  │  LLM     │───▶│  Tool    │───▶│  Result  │           │
│  │  Stream   │    │  Execute │    │  Merge   │           │
│  └──────────┘    └──────────┘    └──────────┘           │
│       ▲                               │                  │
│       └───────────────────────────────┘                  │
│                                                          │
│  Features:                                               │
│  • Streaming LLM response with tool calls                │
│  • Parallel tool execution for independent calls         │
│  • API retry with exponential backoff                    │
│  • Token counting and cost tracking per turn             │
│  • Real-time data priority (market data = fast lane)     │
│  • Async execution for non-blocking operations           │
│  • RiskGovernor pre-trade hooks                          │
└─────────────────────────────────────────────────────────┘
```

43 registered tools across categories:
- **News Sources** (7): Whale Alert, SEC/CFTC, Exploits, Twitter, Reddit/Discord, CryptoPanic, Fear & Greed
- **DeFi** (6): DEX execution, Intent trading, Bridging, Settlement, Yield, Cross-chain
- **Analysis** (15): Technical, Fundamental, On-chain, Order flow, Volatility, Correlation, etc.
- **Risk** (8): Position sizing, Stop-loss, Take-profit, Fee calculator, etc.
- **Monitoring** (7): Portfolio, Market data, Execution quality, etc.

---

## News & Intelligence System

```
┌─────────────────────────────────────────────────────────────┐
│                    NEWS PIPELINE                             │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │ Whale     │  │ SEC/CFTC  │  │ Exploit   │               │
│  │ Alert     │  │ Feeds     │  │ Alerts    │               │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘               │
│        │              │              │                       │
│  ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐               │
│  │ Twitter/X │  │ Reddit/   │  │ Crypto    │               │
│  │ Monitor   │  │ Discord   │  │ Panic     │               │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘               │
│        │              │              │                       │
│        └──────────────┼──────────────┘                       │
│                       ▼                                      │
│              ┌────────────────┐                              │
│              │  News          │                              │
│              │  Classifier    │  4-tier classification       │
│              │                │  Velocity detection           │
│              │                │  Fake news detection          │
│              └───────┬────────┘                              │
│                      ▼                                       │
│              ┌────────────────┐                              │
│              │  LLM           │                              │
│              │  Verification  │  Verify claims against data  │
│              │                │  Source accuracy tracking     │
│              └───────┬────────┘                              │
│                      ▼                                       │
│              ┌────────────────┐                              │
│              │  News          │                              │
│              │  Gatekeeper    │  Gate signals to agents       │
│              └────────────────┘                              │
└─────────────────────────────────────────────────────────────┘
```

### News Sources

| Source | Data Type | Update Frequency |
|--------|-----------|-----------------|
| **Whale Alert** | Large on-chain transfers (> $1M) | Real-time |
| **SEC/CFTC** | Regulatory filings, enforcement actions | Hourly |
| **Exploit Alerts** | Security incidents, hacks, exploits | Real-time |
| **Twitter/X** | Crypto influencer sentiment | 5-min intervals |
| **Reddit/Discord** | Community sentiment shifts | 15-min intervals |
| **CryptoPanic** | Aggregated crypto news | Real-time |
| **Fear & Greed** | Market sentiment index | Daily |

### News Classification

4-tier classification system:
1. **Breaking** — Immediate market impact (exchange hack, regulatory action)
2. **Significant** — High probability of price movement (whale transfer, major listing)
3. **Informational** — Context for existing positions (analyst opinion, community sentiment)
4. **Noise** — Filtered out (spam, duplicate, unverified)

---

## Scenario Prevention

5 institutional-grade loss prevention modules:

```
┌─────────────────────────────────────────────────────────────┐
│                SCENARIO PREVENTION                           │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │
│  │ Flash Crash   │  │ Stop Hunt     │  │ Whipsaw       │   │
│  │ Detector      │  │ Detector      │  │ Detector      │   │
│  │               │  │               │  │               │   │
│  │ • Volume spike│  │ • Wick pattern│  │ • Rapid dir.  │   │
│  │ • Price drop  │  │ • Liquidity   │  │   changes     │   │
│  │ • Order book  │  │   sweep       │  │ • Low volume  │   │
│  │   imbalance   │  │ • Recovery    │  │   reversals   │   │
│  └───────────────┘  └───────────────┘  └───────────────┘   │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐                      │
│  │ Liquidity     │  │ Correlation   │                      │
│  │ Analyzer      │  │ Breaker       │                      │
│  │               │  │               │                      │
│  │ • Order book  │  │ • Cross-asset │                      │
│  │   depth       │  │   correlation │                      │
│  │ • Spread      │  │   divergence  │                      │
│  │   analysis    │  │ • Regime shift│                      │
│  │ • Slippage    │  │   detection   │                      │
│  │   estimation  │  │               │                      │
│  └───────────────┘  └───────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

Each detector runs pre-trade checks and can **veto** trades during dangerous conditions.

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
│  │ • 50 trades + 7 days + 75% win rate gate         │    │
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
│  Layer 4: SCENARIO PREVENTION                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Institutional-grade pattern detection            │    │
│  │ • Flash crash detection                          │    │
│  │ • Stop hunt detection                            │    │
│  │ • Whipsaw detection                              │    │
│  │ • Liquidity analysis                             │    │
│  │ • Correlation break detection                    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Layer 5: KILL SWITCH                                   │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Emergency halt — dual-write persistence          │    │
│  │ • File + Redis dual-write                        │    │
│  │ • Watchdog heartbeat monitoring                  │    │
│  │ • Auto-cancel orders + flatten positions         │    │
│  │ • On-chain kill switch (blockchain backup)       │    │
│  │ • Manual /resume required to reactivate          │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Layer 6: BLOCKCHAIN RULES                              │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Trustless on-chain enforcement                   │    │
│  │ • On-chain kill switch state                     │    │
│  │ • Mandate verification on-chain                  │    │
│  │ • Immutable audit trail                          │    │
│  │ • Multi-sig governance                           │    │
│  │ • Position limits enforcement                    │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Dual Enforcement Model

Risk rules are enforced in two layers simultaneously:

1. **Off-chain (fast)** — Python/Rust checks in milliseconds. Catches 99% of violations instantly.
2. **On-chain (trustless)** — Solidity smart contracts for immutable, auditable enforcement. Provides trustless backup and regulatory compliance.

```
Trade Signal
    │
    ├──▶ Off-chain check (Python/Rust) ──▶ REJECT (fast, <1ms)
    │
    └──▶ On-chain check (Solidity)    ──▶ REJECT (trustless, ~12s)
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
│  Rust Performance Layer:                                    │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │
│  │ MEV Scanner   │  │ Gas Optimizer │  │ DEX Aggregator│   │
│  │               │  │               │  │               │   │
│  │ • Mempool     │  │ • Multi-chain │  │ • Cross-DEX   │   │
│  │   monitoring  │  │   gas compare │  │   routing     │   │
│  │ • Sandwich    │  │ • Fee         │  │ • Best price  │   │
│  │   detection   │  │   estimation  │  │   discovery   │   │
│  └───────────────┘  └───────────────┘  └───────────────┘   │
│                                                             │
│  Supported Chains:                                          │
│  Ethereum │ Polygon │ Arbitrum │ Base │ Solana              │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Testnet-first** — All DeFi operations default to testnets (Sepolia, Solana devnet)
2. **Encrypted wallets** — Private keys encrypted with Fernet at rest
3. **MEV protection** — Private mempool submission, sandwich detection (Rust)
4. **Slippage control** — Configurable tolerance, automatic deadline extension
5. **Graceful degradation** — DeFi components optional; CEX trading unaffected
6. **Dual enforcement** — Off-chain + on-chain risk checks

---

## Blockchain Rules

### Smart Contracts

```
┌─────────────────────────────────────────────────────────────┐
│                BLOCKCHAIN RULES                              │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │
│  │ TSARKillSwitch│  │ TSARMandate   │  │ TSARAuditTrail│   │
│  │               │  │               │  │               │   │
│  │ • Emergency   │  │ • Authorization│ │ • Immutable   │   │
│  │   halt state  │  │   boundary    │  │   trade log   │   │
│  │ • On-chain    │  │ • Status      │  │ • Event       │   │
│  │   persistence │  │   management  │  │   indexing    │   │
│  └───────────────┘  └───────────────┘  └───────────────┘   │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐                      │
│  │ TSARGovernance│  │ TSARPosition  │                      │
│  │               │  │ Limits        │                      │
│  │ • Multi-sig   │  │               │                      │
│  │   decisions   │  │ • Max pos.    │                      │
│  │ • Proposal    │  │   per symbol  │                      │
│  │   voting      │  │ • Daily limit │                      │
│  └───────────────┘  └───────────────┘                      │
│                                                             │
│  Rust EVM Bindings:                                         │
│  ┌───────────────┐  ┌───────────────┐                      │
│  │ rules-enforcer│  │ kill_switch   │                      │
│  │               │  │               │                      │
│  │ • Contract    │  │ • State query │                      │
│  │   interaction │  │ • Emergency   │                      │
│  │ • TX signing  │  │   trigger     │                      │
│  └───────────────┘  └───────────────┘                      │
│                                                             │
│  Python Bridge:                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ blockchain_enforcer.py                               │    │
│  │ • Dual enforcement (off-chain + on-chain)            │    │
│  │ • Contract state caching                             │    │
│  │ • Transaction submission                             │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Deployment

```bash
# Compile contracts
cd blockchain/contracts && forge build

# Deploy to Sepolia testnet
./scripts/deploy-contracts.sh --network sepolia

# Verify on Etherscan
forge verify-contract <address> TSARKillSwitch --chain sepolia
```

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

### Commands

| Command | Description |
|---------|-------------|
| `/status` | Portfolio overview and active positions |
| `/discuss` | Discuss a specific market or asset |
| `/why` | Explain the reasoning behind the last trade |
| `/performance` | Performance metrics and statistics |
| `/regime` | Current market regime classification |
| `/flywheel` | Flywheel improvement status |
| `/ask` | Free-form question to the agent |
| `/kill` | Emergency kill switch (requires confirmation) |
| `/resume` | Resume trading after kill switch |

---

## Data Flow

### Trade Lifecycle

```
1. Market data arrives (WebSocket or REST poll)
2. SignalScout evaluates technical indicators + sentiment + news
3. Signal published to EventBus: tsar.signal.detected
4. RiskGuardian receives signal, runs deterministic checks:
   a. Mandate compliance
   b. Position sizing (Kelly criterion)
   c. Drawdown limits
   d. Behavioral guards
   e. Economic blackout calendar
   f. Scenario prevention (flash crash, stop hunt, whipsaw, liquidity, correlation)
   g. News gate verification
5. If approved: tsar.signal.approved → ExecutionSniper
6. If rejected: tsar.signal.rejected → logged to TradeMemory
7. ExecutionSniper places order via ExecutionEngine
8. MEV protection: Rust mempool monitor checks for sandwich attacks
9. Order fills reported: tsar.order.filled
10. TradePhilosopher analyzes outcome, extracts lessons
11. FlywheelOrchestrator triggers: OBSERVE → REFLECT → EXTRACT → ADAPT
12. Knowledge stores updated (lessons, patterns, genomes)
13. StrategyGeneticist may mutate strategy based on results
14. On-chain audit trail updated (if blockchain enabled)
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
| **Rust for performance** | 14 crates for hot paths | Zero-copy interop via PyO3, sub-ms tick processing |
| **Solidity for rules** | On-chain risk enforcement | Trustless, immutable, auditable |
| **Abstract interfaces** | 5 base classes | Backend swaps without agent code changes |
| **SQLite + FTS5** | Single-file database | Zero-config, embedded, excellent for single-user trading |
| **Redis** | Event bus + cache | Fast pub/sub, TTL support, proven at scale |
| **CloudEvents** | Event protocol | Standard spec, vendor-neutral, good tooling |
| **OpenHarness** | Agent loop pattern | Streaming tool-call cycle, parallel execution |
| **Docker Compose** | Orchestration | Reproducible, simple, single-command deployment |
| **PyO3 + C FFI** | Rust/C++ bridge | Zero-copy interop, type-safe bindings |
| **Fernet encryption** | Wallet key storage | Symmetric encryption, simple, auditable |
| **Dual enforcement** | Off-chain + on-chain | Fast checks + trustless backup |
