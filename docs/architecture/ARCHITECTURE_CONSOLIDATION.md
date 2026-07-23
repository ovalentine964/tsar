# ARCHITECTURE CONSOLIDATION — Single Source of Truth

**Version:** 1.0.0  
**Date:** 2026-07-24  
**Authority:** This document supersedes all conflicting values in individual architecture specs.  
**Status:** APPROVED — All engineering must reference these canonical values.

---

## Table of Contents

1. [Consolidated Spec Values (Quick Reference)](#1-consolidated-spec-values)
2. [Critical Gap Resolutions](#2-critical-gap-resolutions)
   - 2.1 [Paper Trading Mode](#21-paper-trading-mode)
   - 2.2 [Stream Prefix Unification](#22-stream-prefix-unification)
   - 2.3 [SQLite Database Architecture](#23-sqlite-database-architecture)
   - 2.4 [Strategy Warmup/Bootstrap](#24-strategy-warmupbootstrap)
   - 2.5 [Exchange Failover](#25-exchange-failover)
3. [Contradiction Resolutions](#3-contradiction-resolutions)
4. [Document Update Checklist](#4-document-update-checklist)

---

## 1. Consolidated Spec Values

> **These are the CANONICAL values. Every document, code comment, and config file must use these.**

### 1.1 Communication

| Parameter | Canonical Value | Rationale |
|-----------|----------------|-----------|
| **Stream prefix** | `tsar:` | Data Architecture has the most detailed key design; `tsar:` is already defined there with full key taxonomy |
| **Message format** | MessagePack (binary), JSON fallback for debugging | 30-50% smaller, 5x faster parse than JSON |
| **Message envelope** | `MessageEnvelope` with ULID, timestamp_ns, trace_id, priority | Defined in Agent Spec §2.3 |

### 1.2 Storage

| Parameter | Canonical Value | Rationale |
|-----------|----------------|-----------|
| **SQLite databases** | **1 unified database**: `tsar.db` | Solo developer with $10 — operational simplicity trumps theoretical separation |
| **DB mode** | WAL, page_size=4096, mmap=256MB | Per Data Architecture spec |
| **Schema separation** | Table prefixes: `trade_*`, `strategy_*`, `pattern_*`, `lesson_*` | Logical separation within single DB |
| **Redis** | Single instance, `tsar:*` key prefix | Per Data Architecture §12 |
| **ChromaDB** | **Optional** — skip for v1, add when portfolio > $1,000 | Over-engineered for $10 capital; SQLite FTS5 sufficient |

### 1.3 Risk Limits

| Parameter | Canonical Value | Source | Rationale |
|-----------|----------------|--------|-----------|
| **Daily loss kill switch** | **-2%** of capital | Agent Spec (P0) | More conservative; appropriate for $10 capital preservation |
| **Max drawdown (HWM)** | 5% | Agent Spec | Halt all trading |
| **Max open positions** | **10** | Agent Spec (P3) | Solo developer cannot monitor 20 positions meaningfully |
| **Max single position** | 15% of capital | Agent Spec (P1) | Concentration limit |
| **Max sector concentration** | 30% of capital | Agent Spec (P1) | Sector limit |
| **Max correlation** | 0.7 | Agent Spec (P1) | New trade correlation to portfolio |
| **Kelly fraction** | 0.25 (Half-Kelly) | Risk Architecture | Conservative sizing |
| **Max daily trades** | 30 | Agent Spec (P3) | Prevent overtrading |

### 1.4 Ports

| Service | Port | Protocol |
|---------|------|----------|
| **Redis** | 6379 | TCP |
| **FastAPI (REST API)** | **8000** | HTTP |
| **Agent Supervisor** | **8001** | HTTP (health/metrics) |
| **Prometheus** | 9090 | HTTP |
| **Grafana** | 3000 | HTTP |
| **Ollama** | 11434 | HTTP |
| **ChromaDB** (when enabled) | 8529 | HTTP |

> **Port 8000 is assigned to FastAPI.** The agent supervisor health endpoint uses port 8001.

### 1.5 Technology Versions

| Component | Canonical Version | Notes |
|-----------|------------------|-------|
| **Rust** | **1.79** (stable) | Standardize on latest stable at project start |
| **Python** | **3.12** | Per Agent Spec |
| **SQLite** | 3.40+ | Required for FTS5, WAL mode |
| **Redis** | 7.0+ | Hash field TTL, stream consumer groups |
| **Node.js** | 22 LTS | For OpenClaw gateway |

### 1.6 Agent Tool Permissions

| Role | Permissions | Agents |
|------|-------------|--------|
| **TRADE_ADMIN** | Full control: approve/veto, modify risk limits, start/stop agents | Risk Guardian, Orchestrator |
| **TRADE_EXECUTE** | Place/cancel orders, read positions | Execution Sniper, Execution Tracker |
| **TRADE_PREVIEW** | Generate signals, read market data, read positions (no writes) | Signal Scout, Regime Detector |
| **ANALYSIS** | Read all data, write to analytics/patterns/lessons stores | Trade Philosopher, Strategy Geneticist, Market Cartographer |
| **READ** | Read-only access to all non-sensitive data | Monitoring, health checks |

### 1.7 Celery/FastAPI Integration

| Component | Decision | Rationale |
|-----------|----------|-----------|
| **FastAPI** | **KEEP** — REST API for human-facing endpoints | Telegram bot webhook, manual overrides, dashboard queries |
| **Celery** | **REMOVE** — not needed | Redis Streams already provide async task queuing with consumer groups; Celery adds unnecessary complexity |

**FastAPI endpoints:**
- `GET /health` — System health status
- `GET /positions` — Current open positions
- `GET /pnl` — P&L summary (daily/weekly/monthly)
- `GET /risk` — Current risk state and limits
- `POST /kill-switch` — Emergency halt (requires TRADE_ADMIN)
- `POST /resume` — Resume trading (requires TRADE_ADMIN)
- `GET /strategies` — Strategy performance overview
- `GET /regime` — Current regime classification
- `GET /trades` — Trade history with pagination

---

## 2. Critical Gap Resolutions

### 2.1 Paper Trading Mode

#### Overview

Paper trading is **mandatory** before any live deployment. The system boots in paper mode by default. All risk rules, position tracking, and P&L calculations apply identically in paper and live modes. The only difference is the order execution backend.

#### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PAPER TRADING ARCHITECTURE                    │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ Signal Scout │───►│ Risk         │───►│ Execution    │       │
│  │              │    │ Guardian     │    │ Sniper       │       │
│  └──────────────┘    └──────────────┘    └──────┬───────┘       │
│                                                  │               │
│                              ┌───────────────────┤               │
│                              │                   │               │
│                    ┌─────────▼──────┐   ┌───────▼────────┐      │
│                    │ PAPER ENGINE   │   │ LIVE ENGINE     │      │
│                    │ (Simulated)    │   │ (Exchange API)  │      │
│                    │                │   │                 │      │
│                    │ • Testnet API  │   │ • Binance Main  │      │
│                    │ • Sim fills    │   │ • Real orders   │      │
│                    │ • Paper P&L    │   │ • Real P&L      │      │
│                    └────────────────┘   └────────────────┘      │
│                              │                   │               │
│                              └───────┬───────────┘               │
│                                      │                           │
│                              ┌───────▼───────┐                   │
│                              │ SAME SCHEMA   │                   │
│                              │ tsar.db       │                   │
│                              │ (trades table │                   │
│                              │  has mode col)│                   │
│                              └───────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

#### Configuration

```yaml
# config/environments/paper.toml
[trading]
mode = "paper"                    # "paper" | "live"
paper_initial_capital = 10000.0   # Starting paper balance (USD)

[trading.paper]
# Simulated exchange behavior
fill_latency_ms = 50              # Simulated fill latency
slippage_model = "realistic"      # "zero" | "fixed" | "realistic"
slippage_bps_mean = 3.0           # Mean slippage in basis points
slippage_bps_std = 2.0            # Std dev of slippage
fee_model = "exchange_accurate"   # Use actual exchange fee schedules
partial_fill_probability = 0.1    # 10% chance of partial fills
reject_probability = 0.01         # 1% chance of order rejection

# Data sources for paper mode
market_data_source = "testnet"    # "testnet" | "live_feed"
# testnet: uses exchange testnet APIs (Binance testnet)
# live_feed: uses live market data but simulated execution

[trading.paper.testnet]
binance_testnet_url = "https://testnet.binance.vision"
binance_testnet_ws = "wss://testnet.binance.vision/ws"
oanda_practice_url = "https://api-fxpractice.oanda.com"

# config/environments/live.toml
[trading]
mode = "live"
```

#### Database Schema Addition

```sql
-- Add to trades table in tsar.db
ALTER TABLE trades ADD COLUMN trading_mode TEXT NOT NULL DEFAULT 'paper'
    CHECK(trading_mode IN ('paper', 'live'));

-- Paper P&L tracking view
CREATE VIEW paper_pnl AS
SELECT
    date(created_at) as trade_date,
    COUNT(*) as trade_count,
    SUM(realized_pnl) as total_pnl,
    AVG(realized_pnl) as avg_pnl,
    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
    SUM(commission) as total_fees,
    SUM(slippage_bps * quantity * fill_price / 10000) as estimated_slippage_cost
FROM trades
WHERE trading_mode = 'paper' AND is_deleted = 0
GROUP BY date(created_at);

-- Live P&L tracking view
CREATE VIEW live_pnl AS
SELECT
    date(created_at) as trade_date,
    COUNT(*) as trade_count,
    SUM(realized_pnl) as total_pnl,
    AVG(realized_pnl) as avg_pnl,
    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
    SUM(commission) as total_fees
FROM trades
WHERE trading_mode = 'live' AND is_deleted = 0
GROUP BY date(created_at);

-- Combined dashboard view
CREATE VIEW pnl_summary AS
SELECT
    trading_mode,
    date(created_at) as trade_date,
    COUNT(*) as trades,
    SUM(realized_pnl) as pnl,
    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
FROM trades
WHERE is_deleted = 0
GROUP BY trading_mode, date(created_at);
```

#### Paper Engine Implementation

```python
class PaperTradingEngine:
    """Simulated exchange for paper trading."""

    def __init__(self, config: PaperConfig):
        self.config = config
        self.capital = config.paper_initial_capital
        self.positions: dict[str, PaperPosition] = {}
        self.fill_history: list[PaperFill] = []

    async def submit_order(self, order: OrderCommand) -> FillResult:
        """Simulate order execution with realistic behavior."""
        # Simulate latency
        await asyncio.sleep(self.config.fill_latency_ms / 1000)

        # Get current market price
        market_price = await self._get_market_price(order.instrument)

        # Simulate slippage
        slippage_bps = self._simulate_slippage()
        if order.side == "buy":
            fill_price = market_price * (1 + slippage_bps / 10000)
        else:
            fill_price = market_price * (1 - slippage_bps / 10000)

        # Simulate partial fills
        fill_quantity = order.quantity
        if random.random() < self.config.partial_fill_probability:
            fill_quantity = order.quantity * random.uniform(0.3, 0.9)

        # Simulate rejection
        if random.random() < self.config.reject_probability:
            return FillResult.rejected("Simulated exchange rejection")

        # Calculate fees
        fees = self._calculate_fees(order, fill_quantity, fill_price)

        # Update paper position
        self._update_position(order, fill_quantity, fill_price)

        # Record fill
        fill = PaperFill(
            order_id=order.order_id,
            instrument=order.instrument,
            side=order.side,
            quantity=fill_quantity,
            fill_price=fill_price,
            fees=fees,
            slippage_bps=slippage_bps,
            timestamp=datetime.utcnow(),
            trading_mode="paper",
        )
        self.fill_history.append(fill)

        return FillResult.filled(fill)

    def _simulate_slippage(self) -> float:
        """Generate realistic slippage from configured distribution."""
        return max(0, random.gauss(
            self.config.slippage_bps_mean,
            self.config.slippage_bps_std
        ))

    def _calculate_fees(self, order, quantity, price) -> float:
        """Calculate exchange-accurate fees."""
        notional = quantity * price
        # Binance spot: 0.1% maker/taker
        return notional * 0.001

    def get_paper_pnl(self) -> PaperPnlSummary:
        """Calculate paper trading P&L summary."""
        realized = sum(f.pnl for f in self.fill_history if f.is_close)
        unrealized = sum(
            self._calc_unrealized(p) for p in self.positions.values()
        )
        total_fees = sum(f.fees for f in self.fill_history)
        return PaperPnlSummary(
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            total_fees=total_fees,
            net_pnl=realized + unrealized - total_fees,
            trade_count=len(self.fill_history),
            win_rate=self._calc_win_rate(),
        )
```

#### Mode Switching

```python
class TradingModeManager:
    """Manages switching between paper and live modes."""

    def __init__(self, config_path: str):
        self.config = load_config(config_path)
        self.mode = self.config.trading.mode

    def get_execution_engine(self) -> ExecutionEngine:
        """Return the appropriate execution engine based on mode."""
        if self.mode == "paper":
            return PaperTradingEngine(self.config.trading.paper)
        elif self.mode == "live":
            return LiveTradingEngine(self.config.trading.live)
        else:
            raise ValueError(f"Unknown trading mode: {self.mode}")

    def can_switch_to_live(self) -> tuple[bool, list[str]]:
        """Check if system meets requirements to switch to live mode."""
        checks = []
        passed = True

        # Check 1: Minimum paper trades
        paper_trades = self._count_paper_trades()
        if paper_trades < 100:
            checks.append(f"Need {100 - paper_trades} more paper trades (have {paper_trades})")
            passed = False

        # Check 2: Paper Sharpe ratio
        paper_sharpe = self._calc_paper_sharpe()
        if paper_sharpe < 1.0:
            checks.append(f"Paper Sharpe ratio {paper_sharpe:.2f} < 1.0 minimum")
            passed = False

        # Check 3: Paper max drawdown
        paper_max_dd = self._calc_paper_max_drawdown()
        if paper_max_dd > 0.10:
            checks.append(f"Paper max drawdown {paper_max_dd:.1%} > 10% limit")
            passed = False

        # Check 4: All critical agents healthy
        unhealthy = self._check_agent_health()
        if unhealthy:
            checks.append(f"Unhealthy agents: {', '.join(unhealthy)}")
            passed = False

        # Check 5: Risk limits configured
        if not self._risk_limits_configured():
            checks.append("Risk limits not fully configured")
            passed = False

        return passed, checks

    async def switch_to_live(self, human_approval: bool = False) -> bool:
        """Switch from paper to live mode with safety checks."""
        if not human_approval:
            raise RuntimeError("Live mode requires explicit human approval")

        can_switch, reasons = self.can_switch_to_live()
        if not can_switch:
            logger.error(f"Cannot switch to live: {reasons}")
            return False

        # Persist mode change
        self.mode = "live"
        self._save_mode("live")

        # Alert all agents
        await self._broadcast_mode_change("live")

        logger.info("Switched to LIVE trading mode")
        return True
```

#### Paper Trading Validation Criteria

Before switching to live, the system must demonstrate:

| Metric | Minimum | Target | Measurement |
|--------|---------|--------|-------------|
| Paper trades completed | 100 | 500 | Total count in paper mode |
| Sharpe ratio | > 1.0 | > 2.0 | Rolling 30-day |
| Max drawdown | < 10% | < 5% | From paper HWM |
| Win rate | > 50% | > 55% | All paper trades |
| Profit factor | > 1.2 | > 2.0 | Gross profit / gross loss |
| Avg slippage accuracy | Within 50% of simulated | Within 20% | Compare simulated vs testnet actual |
| System uptime | > 99% | > 99.9% | Over paper trading period |
| Kill switch tested | Yes | — | Manual trigger and auto-trigger verified |

---

### 2.2 Stream Prefix Unification

#### Decision: `tsar:` for ALL Redis keys and streams

**Rationale:** The Data Architecture document (`DATA_ARCHITECTURE.md`) contains the most comprehensive and detailed key design (§12, ~80 key patterns). The Agent Spec uses `trading:*` in its stream topology section but is less detailed. Adopting `tsar:` minimizes total changes — we update one document (Agent Spec) instead of the entire Data Architecture.

#### Canonical Stream Names

| Old Name (Agent Spec) | Canonical Name (this doc) |
|------------------------|--------------------------|
| `trading:regime` | `tsar:stream:regime` |
| `trading:signals` | `tsar:stream:signals` |
| `trading:risk_decisions` | `tsar:stream:risk_decisions` |
| `trading:orders` | `tsar:stream:orders` |
| `trading:fills` | `tsar:stream:fills` |
| `trading:positions` | `tsar:stream:positions` |
| `trading:analytics` | `tsar:stream:analytics` |
| `trading:cartography` | `tsar:stream:cartography` |
| `trading:strategy_mutations` | `tsar:stream:strategy_mutations` |
| `trading:health` | `tsar:stream:health` |
| `trading:risk_requests` | `tsar:stream:risk_requests` |
| `trading:risk_reply:*` | `tsar:stream:risk_reply:*` |

#### Canonical Key Naming Convention

```
tsar:{domain}:{entity}:{identifier}:{field}

Domains:
  stream     — Redis Streams (inter-agent communication)
  regime     — Market regime state (Redis Hashes)
  positions  — Current positions
  pnl        — Profit/loss tracking
  risk       — Risk limits and state
  market     — Market data cache
  strategy   — Strategy state
  signals    — Signal queue
  agents     — Agent coordination
  system     — System metadata
```

#### Complete Stream Topology (Updated)

```
Stream Name                    Producers              Consumers
─────────────────────────────────────────────────────────────────────
tsar:stream:regime             Regime Detector         Signal Scout, Risk Guardian,
                                                       Strategy Geneticist,
                                                       Market Cartographer

tsar:stream:signals            Signal Scout            Risk Guardian, Strategy
                                                       Geneticist

tsar:stream:risk_decisions     Risk Guardian           Execution Sniper, Trade
                                                       Philosopher

tsar:stream:orders             Execution Sniper        Execution Tracker

tsar:stream:fills              Execution Tracker       Trade Philosopher,
                                                       Risk Guardian,
                                                       Market Cartographer

tsar:stream:positions          Execution Tracker       Risk Guardian,
                                                       Trade Philosopher,
                                                       Strategy Geneticist

tsar:stream:analytics          Trade Philosopher       Strategy Geneticist,
                                                       Regime Detector

tsar:stream:cartography        Market Cartographer     Regime Detector,
                                                       Signal Scout, Risk Guardian

tsar:stream:strategy_mutations Strategy Geneticist     Signal Scout

tsar:stream:health             ALL agents              Orchestrator (supervisor)

tsar:stream:risk_requests      Execution Sniper        Risk Guardian
tsar:stream:risk_reply:*       Risk Guardian           Execution Sniper
```

#### Redis State Keys (Unchanged from Data Architecture)

All `tsar:regime:*`, `tsar:positions:*`, `tsar:pnl:*`, `tsar:risk:*`, `tsar:market:*`, `tsar:strategy:*`, `tsar:signals:*`, `tsar:agents:*`, `tsar:system:*` keys remain as defined in `DATA_ARCHITECTURE.md` §12.

---

### 2.3 SQLite Database Architecture

#### Decision: 1 Unified Database (`tsar.db`)

**Rationale:**

| Factor | 4 Separate DBs | 1 Unified DB |
|--------|---------------|--------------|
| Operational complexity | 4x backup, 4x integrity checks, 4x connection pools | Single backup, single check, single connection |
| Cross-store queries | Requires ATTACH or Python joins | Direct SQL joins |
| Transaction integrity | No cross-DB transactions | ACID across all stores |
| Solo developer burden | High — must manage 4 files | Low — one file to rule them all |
| Performance | Slightly better isolation (separate WAL) | Negligible difference at our scale |
| Schema separation | Physical | Logical (table prefixes) |

**For a solo developer with $10 starting capital, simplicity wins.**

#### Unified Schema Structure

```sql
-- tsar.db — Single unified database
-- All tables use prefixes for logical separation

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;          -- 64MB cache
PRAGMA mmap_size = 268435456;        -- 256MB mmap
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ═══════════════════════════════════════════════════════════════
-- TRADE TABLES (prefix: trade_)
-- Source: DATA_ARCHITECTURE.md §2
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE trade_records (
    -- (full schema from DATA_ARCHITECTURE.md §2.2 trades table)
    -- Plus: trading_mode TEXT NOT NULL DEFAULT 'paper'
    ...
);

CREATE TABLE trade_snapshots (...);    -- From §2.2
CREATE TABLE trade_journal (...);      -- From §2.2
CREATE TABLE trades_audit_log (...);   -- From §2.2

-- ═══════════════════════════════════════════════════════════════
-- STRATEGY TABLES (prefix: strategy_)
-- Source: DATA_ARCHITECTURE.md §3
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE strategy_genomes (...);   -- From §3.3
CREATE TABLE strategy_performance (...);
CREATE TABLE strategy_mutations (...);

-- ═══════════════════════════════════════════════════════════════
-- PATTERN TABLES (prefix: pattern_)
-- Source: DATA_ARCHITECTURE.md §5
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE patterns (...);           -- From §5.2
CREATE TABLE pattern_observations (...);
CREATE TABLE pattern_relationships (...);

-- ═══════════════════════════════════════════════════════════════
-- LESSON TABLES (prefix: lesson_)
-- Source: DATA_ARCHITECTURE.md §6
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE lessons (...);            -- From §6.2
CREATE TABLE lesson_applications (...);
CREATE TABLE lesson_violations (...);

-- ═══════════════════════════════════════════════════════════════
-- FTS5 INDEXES
-- ═══════════════════════════════════════════════════════════════

CREATE VIRTUAL TABLE lessons_fts USING fts5(...);      -- From §6.2
CREATE VIRTUAL TABLE trade_thesis_fts USING fts5(...); -- From §9.1
CREATE VIRTUAL TABLE pattern_desc_fts USING fts5(...); -- From §9.1
CREATE VIRTUAL TABLE strategy_text_fts USING fts5(...);-- From §9.1

-- ═══════════════════════════════════════════════════════════════
-- REGIME HISTORY (snapshot from Redis)
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE regime_history (
    snapshot_id     TEXT PRIMARY KEY,
    snapshot_date   TEXT NOT NULL,
    regime_probs    TEXT NOT NULL,       -- JSON
    dominant_regime TEXT,
    confidence      REAL,
    indicators      TEXT,                -- JSON
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_regime_date ON regime_history(snapshot_date DESC);

-- ═══════════════════════════════════════════════════════════════
-- POSITION SNAPSHOTS (periodic from Redis)
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE position_snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    snapshot_date   TEXT NOT NULL,
    positions_json  TEXT NOT NULL,       -- JSON of all positions
    portfolio_metrics TEXT,              -- JSON of aggregate metrics
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_pos_snap_date ON position_snapshots(snapshot_date DESC);
```

#### Updated File Layout

```
trading-agent/
├── data/
│   ├── tsar.db                        # SINGLE unified database
│   ├── tsar.db-wal                    # WAL file (auto-managed)
│   ├── tsar.db-shm                    # Shared memory file (auto-managed)
│   ├── chromadb/                      # Vector store (optional, v2+)
│   └── backups/
│       ├── hourly/
│       ├── daily/
│       └── weekly/
├── ...
```

#### Migration Note

If the system ever needs to split databases (e.g., at institutional scale), the table prefix convention makes this straightforward: `ATTACH` a new DB and `ALTER TABLE ... RENAME` or `INSERT INTO ... SELECT`.

---

### 2.4 Strategy Warmup/Bootstrap

#### Problem

The system needs historical data and calibrated models before it can generate valid signals. Without a bootstrap process, the first N trades would be uninformed guesses.

#### Bootstrap Sequence

```
SYSTEM BOOTSTRAP SEQUENCE
═════════════════════════

Phase 1: INFRASTRUCTURE (0-10 seconds)
──────────────────────────────────────
1. Start Redis
2. Start Supervisor
3. Initialize tsar.db (run migrations)
4. Verify disk space, memory, network

Phase 2: DATA ACQUISITION (10s - 5min)
──────────────────────────────────────
5. Download historical OHLCV data
   ├─ Binance: 90 days of 1m/5m/15m/1h/4h/1d candles
   ├─ Yahoo Finance: 2 years of daily data (backup source)
   └─ Store in tsar:market:{symbol}:ohlcv:* (Redis) + tsar.db
6. Download order book snapshots (latest)
7. Fetch economic calendar (next 30 days)

Phase 3: MODEL CALIBRATION (5min - 15min)
─────────────────────────────────────────
8. Calibrate HMM regime model
   ├─ Load 90 days of 1h OHLCV
   ├─ Train HMM on volatility, trend, correlation features
   ├─ Validate on last 30 days (walk-forward)
   └─ Expected time: 2-5 minutes
9. Calculate indicator baselines
   ├─ ATR(14), RSI(14), Bollinger Bands for all instruments
   ├─ Rolling correlations (30-day window)
   └─ Expected time: 30-60 seconds
10. Load strategy genomes from YAML files
    ├─ Validate all genome schemas
    ├─ Check performance gates against historical data
    └─ Expected time: 10-30 seconds

Phase 4: STATE RECONSTRUCTION (15min - 20min)
─────────────────────────────────────────────
11. Rebuild Redis state from tsar.db
    ├─ Regime state → run HMM classification on latest data
    ├─ Position state → query open positions from trade_records
    ├─ P&L state → recalculate from trade history
    ├─ Risk state → recalculate limits from capital + drawdown
    └─ Expected time: 1-2 minutes
12. Run FTS5 index integrity check
13. Verify ChromaDB collections (if enabled)

Phase 5: VALIDATION (20min - 25min)
───────────────────────────────────
14. Run system self-tests
    ├─ Redis connectivity and stream operations
    ├─ tsar.db read/write and integrity check
    ├─ Risk Guardian: load and verify all limits
    ├─ Signal Scout: dry-run scan (no publishing)
    ├─ Execution Engine: verify broker connectivity (paper or live)
    └─ Expected time: 2-3 minutes
15. Publish bootstrap_complete to tsar:stream:health

Phase 6: WARM-UP TRADING (25min - ongoing)
──────────────────────────────────────────
16. Start agents in dependency order (per Agent Spec Appendix C)
17. Risk Guardian starts in VETO_ALL mode until validation passes
18. First regime classification published
19. Signal Scout begins scanning (signals queued, not executed)
20. After first Risk Guardian approval → trading begins
```

#### Warmup Duration by Component

| Component | Warmup Time | Data Required | Can Trade During? |
|-----------|-------------|---------------|-------------------|
| **HMM Regime Model** | 2-5 min | 90 days 1h OHLCV | No — regime must be classified first |
| **Technical Indicators** | 30-60 sec | 200 bars per instrument | No — indicators need lookback |
| **Strategy Genomes** | 10-30 sec | YAML files + validation | No — strategies must be loaded |
| **Signal Scout** | 1 min | Regime + indicators ready | No — needs regime context |
| **Risk Guardian** | 10 sec | Redis state reconstructed | No — must load limits first |
| **Execution Engine** | 5 sec | Broker API connectivity test | No — must verify connectivity |
| **Market Cartographer** | 5-10 min | 30 days 1min OHLCV | Can start with stale correlations |
| **Trade Philosopher** | N/A | No warmup needed | Can analyze from first trade |
| **Strategy Geneticist** | N/A | No warmup needed | Can evolve from first analysis |
| **TOTAL** | **~15-25 min** | — | **No trading until Phase 6** |

#### Minimum Data Requirements

| Data Type | Minimum | Optimal | Source |
|-----------|---------|---------|--------|
| OHLCV (1h) | 90 days | 252 days (1 year) | Binance API |
| OHLCV (1d) | 252 days | 756 days (3 years) | Yahoo Finance |
| Order book | Latest snapshot | Real-time WebSocket | Binance WebSocket |
| Economic calendar | Next 7 days | Next 30 days | Free API (TradingView) |
| Correlation matrix | 30 days | 90 days | Computed from OHLCV |
| Historical regime | 90 days | 252 days | Computed from OHLCV |

#### Bootstrap Data Download Script

```python
class BootstrapDataDownloader:
    """Downloads historical data needed for system warmup."""

    INSTRUMENTS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT",  # Crypto
        "AAPL", "MSFT", "NVDA", "TSLA",   # US Equities
        "SPY", "QQQ", "IWM",              # ETFs
    ]

    async def download_all(self) -> BootstrapResult:
        """Download all required historical data."""
        results = {}

        for symbol in self.INSTRUMENTS:
            # 1h candles — 90 days for HMM
            ohlcv_1h = await self._download_binance(
                symbol=symbol,
                interval="1h",
                days=90,
            )

            # 1d candles — 252 days for longer-term indicators
            ohlcv_1d = await self._download_yahoo(
                symbol=symbol,
                days=252,
            )

            # Store in Redis (hot) and SQLite (durable)
            await self._store_to_redis(symbol, ohlcv_1h, "1h")
            await self._store_to_redis(symbol, ohlcv_1d, "1d")
            await self._store_to_sqlite(symbol, ohlcv_1h, "1h")
            await self._store_to_sqlite(symbol, ohlcv_1d, "1d")

            results[symbol] = {
                "1h_bars": len(ohlcv_1h),
                "1d_bars": len(ohlcv_1d),
            }

            # Rate limiting
            await asyncio.sleep(0.5)

        return BootstrapResult(
            instruments=len(self.INSTRUMENTS),
            data_points=sum(r["1h_bars"] + r["1d_bars"] for r in results.values()),
            details=results,
        )
```

#### Cold Start Behavior

If the system starts with **no historical data** (first-ever boot):

1. **Download phase runs automatically** — blocks trading until complete
2. **HMM uses simplified threshold-based classification** until 90 days of data accumulates
3. **Strategies start in "paper" status** regardless of config — must pass gates before live
4. **Risk Guardian uses conservative defaults** (half the normal limits) for first 48 hours
5. **Signal Scout generates signals but queues them** — doesn't publish until regime is classified

If historical data exists (restart after prior run):

1. **Redis state is loaded from AOF/RDB** — near-instant
2. **Stale data check** — if latest OHLCV > 1 hour old, download gap
3. **HMM recalibrates** only if regime model version changed
4. **Trading resumes** within 2-5 minutes

---

### 2.5 Exchange Failover

#### Failure Modes and Responses

| Failure | Severity | Response | Timeout |
|---------|----------|----------|---------|
| **REST API timeout** | Medium | Retry with exponential backoff | 3 retries, 1s/2s/4s |
| **REST API 429 (rate limit)** | Medium | Respect `Retry-After` header, queue orders | Per header |
| **REST API 5xx** | High | Retry 3x, then switch to backup exchange | 3 retries, 2s/4s/8s |
| **WebSocket disconnect** | High | Auto-reconnect with backoff, resync state | 5 retries, 1s/2s/4s/8s/16s |
| **WebSocket stale data** | Medium | Detect via heartbeat timeout (10s), reconnect | 10s detection |
| **Exchange maintenance** | High | Switch to backup exchange, alert human | Immediate |
| **Exchange API key revoked** | Critical | Halt all trading, alert human | Immediate |
| **Order rejection (insufficient balance)** | High | Log, reduce position size, retry once | Immediate |
| **Order stuck (no fill, no reject)** | Medium | Cancel after 30s, retry with market order | 30s |

#### Reconnection Strategy

```python
class ExchangeConnection:
    """Manages exchange connection with automatic failover."""

    MAX_RETRIES = 5
    BASE_DELAY_MS = 1000
    MAX_DELAY_MS = 30000
    BACKOFF_MULTIPLIER = 2.0

    def __init__(self, primary: ExchangeConfig, backup: ExchangeConfig | None = None):
        self.primary = primary
        self.backup = backup
        self.active = primary
        self.retry_count = 0
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,  # seconds
        )

    async def execute_with_failover(self, operation: str, *args, **kwargs):
        """Execute exchange operation with automatic failover."""
        # Check circuit breaker
        if self.circuit_breaker.is_open:
            if self.backup:
                logger.warning(f"Circuit breaker open on {self.active.name}, switching to backup")
                self.active = self.backup
                self.circuit_breaker.reset()
            else:
                raise ExchangeUnavailableError(f"{self.active.name} circuit breaker open, no backup")

        for attempt in range(self.MAX_RETRIES):
            try:
                result = await self._execute(self.active, operation, *args, **kwargs)
                self.circuit_breaker.record_success()
                self.retry_count = 0
                return result

            except RateLimitError as e:
                # Respect rate limit
                delay = e.retry_after or self._backoff_delay(attempt)
                logger.warning(f"Rate limited on {self.active.name}, waiting {delay}s")
                await asyncio.sleep(delay)

            except ExchangeError as e:
                self.circuit_breaker.record_failure()

                if e.is_server_error:  # 5xx
                    delay = self._backoff_delay(attempt)
                    logger.warning(f"Server error on {self.active.name} (attempt {attempt + 1}), "
                                   f"retrying in {delay}s")
                    await asyncio.sleep(delay)

                    # After 3 failures, try backup
                    if attempt >= 2 and self.backup:
                        logger.info(f"Switching to backup exchange: {self.backup.name}")
                        self.active = self.backup
                        continue

                elif e.is_auth_error:  # 401/403
                    # Cannot recover — halt trading
                    raise ExchangeAuthError(f"Authentication failed on {self.active.name}")

                else:
                    raise

            except ConnectionError:
                self.circuit_breaker.record_failure()
                delay = self._backoff_delay(attempt)
                logger.warning(f"Connection error on {self.active.name} (attempt {attempt + 1}), "
                               f"retrying in {delay}s")
                await asyncio.sleep(delay)

                if attempt >= 2 and self.backup:
                    logger.info(f"Switching to backup exchange: {self.backup.name}")
                    self.active = self.backup

        raise ExchangeUnavailableError(
            f"All {self.MAX_RETRIES} attempts failed on {self.active.name}"
        )

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter."""
        delay = self.BASE_DELAY_MS * (self.BACKOFF_MULTIPLIER ** attempt)
        delay = min(delay, self.MAX_DELAY_MS)
        # Add jitter (±25%)
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return (delay + jitter) / 1000
```

#### WebSocket Reconnection

```python
class WebSocketManager:
    """Manages WebSocket connections with auto-reconnect."""

    HEARTBEAT_TIMEOUT_S = 10
    MAX_RECONNECT_ATTEMPTS = 10

    async def connect(self, url: str, on_message: Callable):
        """Connect with automatic reconnection."""
        self.url = url
        self.on_message = on_message
        self.reconnect_count = 0

        while self.reconnect_count < self.MAX_RECONNECT_ATTEMPTS:
            try:
                async with websockets.connect(url) as ws:
                    self.ws = ws
                    self.reconnect_count = 0  # Reset on successful connect
                    logger.info(f"WebSocket connected to {url}")

                    # Start heartbeat monitor
                    heartbeat_task = asyncio.create_task(self._monitor_heartbeat())

                    try:
                        async for message in ws:
                            self.last_message_time = time.time()
                            await self.on_message(message)
                    finally:
                        heartbeat_task.cancel()

            except websockets.ConnectionClosed as e:
                self.reconnect_count += 1
                delay = min(2 ** self.reconnect_count, 30)
                logger.warning(f"WebSocket closed (code={e.code}), "
                               f"reconnecting in {delay}s (attempt {self.reconnect_count})")
                await asyncio.sleep(delay)

            except Exception as e:
                self.reconnect_count += 1
                delay = min(2 ** self.reconnect_count, 30)
                logger.error(f"WebSocket error: {e}, reconnecting in {delay}s")
                await asyncio.sleep(delay)

        raise ConnectionError(f"WebSocket reconnection failed after {self.MAX_RECONNECT_ATTEMPTS} attempts")

    async def _monitor_heartbeat(self):
        """Detect stale WebSocket connections."""
        while True:
            await asyncio.sleep(self.HEARTBEAT_TIMEOUT_S)
            if time.time() - self.last_message_time > self.HEARTBEAT_TIMEOUT_S:
                logger.warning("WebSocket heartbeat timeout — forcing reconnect")
                await self.ws.close()
                return
```

#### Failover Behavior by Exchange

| Primary | Backup | Failover Type | Notes |
|---------|--------|---------------|-------|
| Binance Spot | Binance Testnet | Same-exchange, testnet | Paper mode fallback |
| Binance Spot | None (v1) | Halt trading | Solo dev, single exchange |
| Binance Spot | Bybit (v2) | Cross-exchange | Requires position migration |
| Binance Futures | Binance Spot | Same-exchange, different product | Reduce leverage |

#### When to HALT vs RETRY

| Condition | Action | Rationale |
|-----------|--------|-----------|
| API timeout, first attempt | **RETRY** | Transient failure |
| API timeout, 3rd attempt | **RETRY with backoff** | Persistent but possibly temporary |
| API timeout, 5th attempt | **HALT** if no backup, **FAILOVER** if backup exists | Exhausted retries |
| 429 Rate Limit | **RETRY** after `Retry-After` | Expected behavior |
| 500 Server Error | **RETRY** 3x, then **FAILOVER** | Server-side issue |
| 401 Auth Error | **HALT immediately** | Cannot recover |
| WebSocket disconnect | **RECONNECT** up to 10x | Transient |
| WebSocket stale (10s) | **RECONNECT** | Dead connection |
| Exchange maintenance announced | **FAILOVER** proactively | Planned downtime |
| All exchanges down | **HALT all trading** | No execution possible |

---

## 3. Contradiction Resolutions

### Contradiction 1: Stream Prefixes

| Document | Value |
|----------|-------|
| Agent Spec (trading-super-agent-spec.md) | `trading:*` |
| Data Architecture (DATA_ARCHITECTURE.md) | `tsar:*` |

**✅ Resolution: `tsar:*`** — See §2.2 for full rationale and mapping.

---

### Contradiction 2: SQLite Database Count

| Document | Value |
|----------|-------|
| Data Architecture (DATA_ARCHITECTURE.md) | 4 separate DBs: `trades.db`, `strategies.db`, `patterns.db`, `lessons.db` |
| Deployment spec | 1 unified DB: `trading.db` |

**✅ Resolution: 1 unified DB: `tsar.db`** — See §2.3 for full rationale and schema.

---

### Contradiction 3: Daily Loss Kill Threshold

| Document | Value |
|----------|-------|
| Agent Spec (Risk Guardian P0 check) | -2% of capital |
| Risk Architecture (DrawdownThresholds) | -4% of capital |

**✅ Resolution: -2%** — More conservative, appropriate for $10 capital preservation. The -4% value was likely from an institutional context with larger capital. With $10, a -4% loss ($0.40) is meaningless in absolute terms but the discipline matters. Use -2% as the hard kill switch.

**Updated Risk Guardian P0 check:**
```python
# Kill switch: daily P&L < -2% of starting capital
KILL_SWITCH_DAILY_LOSS_PCT = 0.02  # -2%
# For $10 capital: halt if daily loss > $0.20
```

---

### Contradiction 4: Maximum Open Positions

| Document | Value |
|----------|-------|
| Agent Spec (Risk Guardian P3) | 10 |
| Risk Architecture (POSITION_LIMITS) | 20 |

**✅ Resolution: 10** — Solo developer cannot meaningfully monitor 20 concurrent positions. At $10 capital, even 10 positions means $1 average per position. Start conservative; increase to 20 only after 6 months of live trading with proven position management.

**Updated Risk Guardian P3 check:**
```python
MAX_OPEN_POSITIONS = 10
# Increase to 20 only after:
# - 6 months live trading
# - Proven automated stop/TP management
# - Portfolio > $1,000
```

---

### Contradiction 5: Port Allocation

| Document | Value |
|----------|-------|
| Deployment spec | Port 8000 for agent |
| TECH_STACK | Port 8000 for FastAPI |

**✅ Resolution: See §1.4 port table.**
- **Port 8000** → FastAPI (REST API)
- **Port 8001** → Agent Supervisor (health/metrics)
- **Port 6379** → Redis
- **Port 9090** → Prometheus
- **Port 3000** → Grafana
- **Port 11434** → Ollama

---

### Contradiction 6: Rust Version

| Document | Value |
|----------|-------|
| Tools Spec | Rust 1.78 |
| Deployment / TECH_STACK | Rust 1.79 |

**✅ Resolution: Rust 1.79** — Use the newer version. Pin to `1.79.0` in `rust-toolchain.toml` for reproducibility.

```toml
# rust-toolchain.toml
[toolchain]
channel = "1.79.0"
components = ["rustfmt", "clippy"]
targets = ["x86_64-unknown-linux-gnu"]
```

---

### Contradiction 7: Celery/FastAPI Integration

| Document | Value |
|----------|-------|
| TECH_STACK | Mentions Celery + FastAPI |
| All other docs | No reference to Celery or FastAPI |

**✅ Resolution: FastAPI YES, Celery NO.** — See §1.7 for rationale and endpoint list. Redis Streams replaces Celery for async task processing.

---

### Contradiction 8: Tool Permission Roles

| Document | Value |
|----------|-------|
| Agent Spec | READ/ANALYSIS/TRADE_PREVIEW/TRADE_ADMIN |
| Risk Architecture | References permission levels but doesn't specify |

**✅ Resolution: See §1.6 for canonical role definitions.**

| Role | Can Read | Can Analyze | Can Preview | Can Execute | Can Admin |
|------|----------|-------------|-------------|-------------|-----------|
| **READ** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **ANALYSIS** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **TRADE_PREVIEW** | ✅ | ✅ | ✅ | ❌ | ❌ |
| **TRADE_EXECUTE** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **TRADE_ADMIN** | ✅ | ✅ | ✅ | ✅ | ✅ |

**Agent role assignments:**

| Agent | Role |
|-------|------|
| Regime Detector | ANALYSIS |
| Signal Scout | TRADE_PREVIEW |
| Risk Guardian | TRADE_ADMIN |
| Execution Sniper | TRADE_EXECUTE |
| Execution Tracker | TRADE_EXECUTE |
| Trade Philosopher | ANALYSIS |
| Strategy Geneticist | ANALYSIS |
| Market Cartographer | ANALYSIS |
| Orchestrator/Supervisor | TRADE_ADMIN |
| Telegram Bot (human interface) | TRADE_ADMIN |

---

## 4. Document Update Checklist

The following documents must be updated to reflect these canonical values:

| Document | Updates Required |
|----------|-----------------|
| `trading-super-agent-spec.md` | Replace all `trading:*` → `tsar:stream:*`; update port references; update max positions to 10 |
| `DATA_ARCHITECTURE.md` | Update to single `tsar.db`; add `trading_mode` column; update file layout |
| `TECH_STACK.md` | Remove Celery; assign FastAPI to port 8000; Rust 1.79 |
| `DEPLOYMENT.md` | Update port allocations; single DB file; remove Celery references |
| `RISK_ARCHITECTURE.md` | Daily loss → -2%; max positions → 10 |
| `TOOLS_SPEC.md` | Rust 1.79; unified tool names |
| All agent implementation files | Use `tsar:stream:*` stream names |

---

## Appendix A: Decision Log

| # | Decision | Alternatives Considered | Chosen | Rationale |
|---|----------|------------------------|--------|-----------|
| D1 | Paper trading via simulated engine + testnet | Mock-only, testnet-only | Simulated engine with testnet data feed | Most realistic; testnet for exchange behavior, simulated for deterministic testing |
| D2 | Stream prefix `tsar:` | `trading:` | `tsar:` | Data Architecture has 80+ key definitions using `tsar:`; less total changes |
| D3 | 1 unified SQLite DB | 4 separate DBs | 1 unified | Solo dev simplicity; table prefixes for logical separation; ACID across stores |
| D4 | Daily loss kill at -2% | -4% | -2% | Conservative for $10 capital; -4% is meaningless at this scale |
| D5 | Max 10 positions | 20 | 10 | Solo dev monitoring capacity; increase after proven track record |
| D6 | Remove Celery | Keep Celery | Remove | Redis Streams already provides consumer groups; Celery adds unnecessary complexity |
| D7 | Rust 1.79 | 1.78 | 1.79 | Newer stable version; pin for reproducibility |
| D8 | Exponential backoff for failover | Fixed delay, circuit breaker only | Exponential backoff + circuit breaker | Standard pattern; circuit breaker prevents thundering herd |

---

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **tsar** | Trading Super Agent Regime — the system prefix for all Redis keys and the unified database |
| **VETO_ALL** | Emergency halt: all trading stopped until manual clearance |
| **Kill switch** | Automatic VETO_ALL triggered when daily loss exceeds -2% |
| **HMM** | Hidden Markov Model — used for regime detection |
| **Paper mode** | Trading mode using simulated execution; no real money at risk |
| **Live mode** | Trading mode using real exchange execution; real money at risk |
| **Bootstrap** | First-start data acquisition and model calibration process |
| **Circuit breaker** | Pattern that prevents repeated calls to a failing service |
| **Half-Kelly** | Position sizing using half the Kelly criterion optimal fraction |

---

*Consolidation completed: 2026-07-24 01:09 GMT+8*  
*This document is the SINGLE SOURCE OF TRUTH for all engineering decisions.*
