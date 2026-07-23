# DAY1 SIMPLIFIED MODE — Trading Super Agent

> **Build time:** 2–4 weeks | **Solo developer** | **$10 starting capital**
> **North Star:** Full institutional architecture (500KB+ specs). This is the v0.1 that actually ships.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    TRADING SUPER AGENT                   │
│                        (Day 1)                          │
│                                                         │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────────┐  │
│  │   SIGNAL    │──▶│    RISK     │──▶│  EXECUTION   │  │
│  │   AGENT     │   │   AGENT     │   │   AGENT      │  │
│  │             │   │             │   │              │  │
│  │ • Scan RSI  │   │ • Position  │   │ • Place order│  │
│  │ • Find S/R  │   │   sizing    │   │ • Track P&L  │  │
│  │ • Score     │   │ • Limits    │   │ • Stop-loss  │  │
│  └──────┬──────┘   └──────┬──────┘   └──────┬───────┘  │
│         │                 │                  │          │
│         ▼                 ▼                  ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              SHARED STATE (SQLite)              │    │
│  │         tsar.db — trades, strategies,        │    │
│  │                    lessons                      │    │
│  └─────────────────────────────────────────────────┘    │
│         │                 │                  │          │
│         ▼                 ▼                  ▼          │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  Ollama  │    │  DeepSeek-R1 │    │   Binance    │  │
│  │ (local)  │    │  (NIM free)  │    │  (ccxt)      │  │
│  └──────────┘    └──────────────┘    └──────────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │           TELEGRAM BOT (alerts + commands)      │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Data Flow:**
1. Signal Agent scans BTC/USDT every 5 minutes → finds RSI-based setups
2. Risk Agent evaluates: position size, daily P&L, max positions → approve/reject
3. Execution Agent places approved orders with stop-loss → tracks until close
4. Every trade is logged. Every outcome feeds the Learning Loop.
5. Telegram notifies you of every trade + daily summary.

---

## 2. Database Schema (Single SQLite DB)

File: `data/tsar.db`

```sql
-- ============================================
-- TRADES: Every order placed
-- ============================================
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT UNIQUE NOT NULL,          -- UUID
    symbol          TEXT NOT NULL,                 -- BTC/USDT
    side            TEXT NOT NULL,                 -- BUY or SELL
    entry_price     REAL,
    exit_price      REAL,
    quantity        REAL NOT NULL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN, CLOSED, CANCELLED
    pnl             REAL DEFAULT 0.0,
    pnl_pct         REAL DEFAULT 0.0,
    signal_score    REAL,                          -- Signal Agent confidence (0-1)
    risk_approved   INTEGER DEFAULT 0,            -- 1 = Risk Agent approved
    strategy        TEXT NOT NULL,                 -- 'mean_reversion'
    exchange_order_id TEXT,                        -- Binance order ID
    notes           TEXT,
    opened_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at       TIMESTAMP
);

-- ============================================
-- STRATEGIES: Track strategy performance
-- ============================================
CREATE TABLE IF NOT EXISTS strategies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,          -- 'mean_reversion_btc'
    description     TEXT,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    losing_trades   INTEGER DEFAULT 0,
    total_pnl       REAL DEFAULT 0.0,
    win_rate        REAL DEFAULT 0.0,
    avg_win         REAL DEFAULT 0.0,
    avg_loss        REAL DEFAULT 0.0,
    sharpe_ratio    REAL DEFAULT 0.0,
    max_drawdown    REAL DEFAULT 0.0,
    status          TEXT DEFAULT 'ACTIVE',         -- ACTIVE, PAUSED, RETIRED
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- LESSONS: The learning loop memory
-- ============================================
CREATE TABLE IF NOT EXISTS lessons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT,                          -- FK to trades.trade_id
    lesson_type     TEXT NOT NULL,                 -- 'WIN', 'LOSS', 'MISTAKE', 'INSIGHT'
    category        TEXT,                          -- 'ENTRY', 'EXIT', 'SIZING', 'TIMING'
    description     TEXT NOT NULL,                 -- What happened & what to learn
    action_item     TEXT,                          -- Concrete change to make
    applied         INTEGER DEFAULT 0,            -- 1 = incorporated into strategy
    confidence      REAL DEFAULT 0.5,             -- How confident in this lesson (0-1)
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- DAILY_SNAPSHOTS: End-of-day state
-- ============================================
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE UNIQUE NOT NULL,
    balance         REAL NOT NULL,
    equity          REAL NOT NULL,
    trades_today    INTEGER DEFAULT 0,
    pnl_today       REAL DEFAULT 0.0,
    win_rate_today  REAL DEFAULT 0.0,
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- INDEXES
-- ============================================
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at);
CREATE INDEX IF NOT EXISTS idx_lessons_trade ON lessons(trade_id);
CREATE INDEX IF NOT EXISTS idx_lessons_type ON lessons(lesson_type);
```

**Why SQLite?** Zero config, single file, handles 10K+ trades easily. Upgrade to PostgreSQL when you hit 100K trades/day (you won't for a long time).

---

## 3. Agent Specifications (3 Agents)

### 3.1 Signal Agent — `agents/signal_agent.py`

**Purpose:** Scan BTC/USDT for mean reversion setups. Score each setup 0–1.

**Cycle:** Every 5 minutes (configurable)

**Logic:**
```
1. Fetch 1H OHLCV (last 100 candles)
2. Calculate RSI(14)
3. Identify support/resistance levels (swing highs/lows)
4. Score setup:
   - RSI < 30 AND price near support (within 0.5%) → BUY signal (score: 0.7–1.0)
   - RSI > 70 AND price near resistance (within 0.5%) → SELL signal (score: 0.7–1.0)
   - Otherwise → NO SIGNAL (score: 0.0)
5. If score > 0.6 → pass to Risk Agent
```

**Scoring Breakdown:**
| Factor | Weight | Max Score |
|--------|--------|-----------|
| RSI extreme | 40% | 0.4 |
| S/R proximity | 30% | 0.3 |
| Volume confirmation | 15% | 0.15 |
| Trend alignment | 15% | 0.15 |
| **Total** | **100%** | **1.0** |

**Model Usage:**
- RSI/S/R calculation: Pure Python (no model needed)
- Setup scoring: Local Ollama (Qwen2.5-7B) for nuanced analysis
- Complex regime detection: DeepSeek-R1 via NIM API (only when signal is ambiguous, score 0.5–0.7)

**Output:**
```python
{
    "signal": "BUY",
    "symbol": "BTC/USDT",
    "score": 0.82,
    "entry_price": 65420.00,
    "stop_loss": 64800.00,
    "take_profit": 66660.00,
    "reasoning": "RSI=28.4 at support level 65400. Volume spike confirms.",
    "timestamp": "2026-07-24T01:00:00Z"
}
```

---

### 3.2 Risk Agent — `agents/risk_agent.py`

**Purpose:** Gatekeeper. Approves or rejects every trade signal.

**Evaluation Checklist (ALL must pass):**
```
□ Position size ≤ 5% of account balance
□ Daily P&L not below -3% loss limit
□ Open positions < 3
□ Stop-loss is set and reasonable (≤ 2% from entry)
□ Risk-reward ratio ≥ 2:1
□ Not trading same symbol within cooldown (30 min)
□ No conflicting positions (can't be long AND short on same pair)
```

**Position Sizing Formula:**
```python
def calculate_position_size(balance, risk_pct, entry_price, stop_loss_price):
    """
    Fixed fractional: risk X% of balance per trade.
    """
    risk_amount = balance * (risk_pct / 100)  # e.g., $10 * 2% = $0.20
    price_risk = abs(entry_price - stop_loss_price)
    if price_risk == 0:
        return 0
    quantity = risk_amount / price_risk
    return round(quantity, 6)
```

**Default Risk Parameters:**
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max position size | 5% of balance | $0.50 on $10 account |
| Risk per trade | 2% of balance | $0.20 on $10 account |
| Daily loss limit | -3% of balance | -$0.30 on $10 account |
| Max open positions | 3 | Concentration vs diversification |
| Stop-loss max distance | 2% from entry | Tight stops for small account |
| Min risk-reward | 2:1 | Winners must be 2x losers |
| Cooldown per symbol | 30 minutes | Avoid overtrading |

**Model Usage:** None. Pure rule-based. This is intentional — risk management must be deterministic, not probabilistic.

**Output:**
```python
{
    "approved": True,
    "position_size": 0.000764,  # BTC
    "risk_amount": 0.20,        # USD at risk
    "checks_passed": 7/7,
    "notes": "All checks passed. R:R = 2.0:1"
}
```

---

### 3.3 Execution Agent — `agents/execution_agent.py`

**Purpose:** Place orders, manage stop-losses, track positions, close trades.

**Lifecycle of a Trade:**
```
1. RECEIVE approved signal from Risk Agent
2. PLACE market/limit order on Binance (testnet or live)
3. PLACE stop-loss order immediately after fill
4. PLACE take-profit order (OCO or separate limit)
5. MONITOR position every 1 minute:
   - Check if stop-loss hit → close, log lesson
   - Check if take-profit hit → close, log lesson
   - Check if trailing stop should update (v2 feature)
6. CLOSE position → calculate P&L → log to DB
7. NOTIFY via Telegram
```

**Order Types (Day1):**
- Market orders only (simpler, guaranteed fill)
- Stop-loss: Stop-market order on exchange
- Take-profit: Limit order on exchange

**Model Usage:** None. Pure execution logic. Speed and reliability matter, not intelligence.

**Telegram Notifications:**
```
🟢 TRADE OPENED
Symbol: BTC/USDT
Side: BUY
Entry: $65,420.00
Size: 0.000764 BTC ($50.00)
Stop: $64,800.00 (-0.95%)
Target: $66,660.00 (+1.89%)
Risk: $0.20 (2% of $10)

📊 Signal Score: 0.82
💡 RSI=28.4 at support, volume confirming
```

```
🔴 TRADE CLOSED
Symbol: BTC/USDT
P&L: +$0.38 (+0.76%)
Duration: 2h 14m
Result: ✅ WIN
Balance: $10.38

📝 Lesson: RSI bounce at support worked well. Volume was 1.8x average.
```

---

## 4. Tool Specifications (10 Tools)

All tools live in `tools/` and are plain Python functions. Each tool is a thin wrapper around ccxt or pandas.

### 4.1 `get_price(symbol: str) -> float`

```python
# tools/market_tools.py
import ccxt

def get_price(symbol: str = "BTC/USDT") -> float:
    """Get current ticker price."""
    exchange = ccxt.binance(config.exchange)
    ticker = exchange.fetch_ticker(symbol)
    return ticker['last']
```

### 4.2 `get_ohlcv(symbol, timeframe, limit) -> DataFrame`

```python
def get_ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 100) -> pd.DataFrame:
    """Fetch OHLCV candle data. Returns DataFrame with columns: timestamp, open, high, low, close, volume."""
    exchange = ccxt.binance(config.exchange)
    bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df
```

### 4.3 `place_order(symbol, side, quantity, order_type, price=None) -> dict`

```python
def place_order(symbol: str, side: str, quantity: float, 
                order_type: str = "market", price: float = None) -> dict:
    """Place an order. Returns order details including exchange_order_id."""
    exchange = ccxt.binance(config.exchange)
    if order_type == "market":
        order = exchange.create_order(symbol, 'market', side.lower(), quantity)
    elif order_type == "limit":
        order = exchange.create_order(symbol, 'limit', side.lower(), quantity, price)
    return {
        "exchange_order_id": order['id'],
        "symbol": order['symbol'],
        "side": order['side'],
        "price": order.get('average', order.get('price')),
        "quantity": order['amount'],
        "status": order['status'],
        "fee": order.get('fee', {})
    }
```

### 4.4 `cancel_order(order_id, symbol) -> bool`

```python
def cancel_order(order_id: str, symbol: str = "BTC/USDT") -> bool:
    """Cancel an open order."""
    exchange = ccxt.binance(config.exchange)
    try:
        exchange.cancel_order(order_id, symbol)
        return True
    except Exception as e:
        logger.error(f"Cancel failed: {e}")
        return False
```

### 4.5 `get_positions() -> list`

```python
def get_positions() -> list:
    """Get all open positions from exchange."""
    exchange = ccxt.binance(config.exchange)
    balance = exchange.fetch_balance()
    positions = []
    for currency, amount in balance['total'].items():
        if amount and amount > 0 and currency not in ['USDT', 'USD']:
            positions.append({
                "symbol": f"{currency}/USDT",
                "quantity": amount,
                "value_usd": amount * get_price(f"{currency}/USDT")
            })
    return positions
```

### 4.6 `get_balance() -> dict`

```python
def get_balance() -> dict:
    """Get account balance."""
    exchange = ccxt.binance(config.exchange)
    bal = exchange.fetch_balance()
    return {
        "total_usd": bal['total'].get('USDT', 0),
        "free_usd": bal['free'].get('USDT', 0),
        "used_usd": bal['used'].get('USDT', 0),
        "positions": get_positions()
    }
```

### 4.7 `calculate_rsi(closes: list, period: int = 14) -> float`

```python
def calculate_rsi(closes: list, period: int = 14) -> float:
    """Calculate RSI from a list of closing prices."""
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)
```

### 4.8 `calculate_position_size(balance, risk_pct, entry, stop_loss) -> float`

```python
def calculate_position_size(balance: float, risk_pct: float, 
                            entry_price: float, stop_loss_price: float) -> float:
    """Calculate position size based on fixed-fractional risk model."""
    risk_amount = balance * (risk_pct / 100)
    price_risk = abs(entry_price - stop_loss_price)
    if price_risk == 0:
        return 0.0
    quantity = risk_amount / price_risk
    return round(quantity, 6)
```

### 4.9 `log_trade(trade_data: dict) -> str`

```python
def log_trade(trade_data: dict) -> str:
    """Insert a trade record into the database. Returns trade_id."""
    import sqlite3, uuid
    trade_id = str(uuid.uuid4())
    conn = sqlite3.connect('data/tsar.db')
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trades (trade_id, symbol, side, entry_price, quantity, 
                           stop_loss, take_profit, signal_score, strategy, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (trade_id, trade_data['symbol'], trade_data['side'], 
          trade_data['entry_price'], trade_data['quantity'],
          trade_data['stop_loss'], trade_data['take_profit'],
          trade_data.get('signal_score'), trade_data.get('strategy', 'mean_reversion'),
          trade_data.get('notes')))
    conn.commit()
    conn.close()
    return trade_id
```

### 4.10 `check_risk(trade_proposal: dict) -> dict`

```python
def check_risk(trade_proposal: dict) -> dict:
    """Run all risk checks on a proposed trade. Returns approval decision."""
    conn = sqlite3.connect('data/tsar.db')
    balance = get_balance()['total_usd']
    checks = {}
    
    # Check 1: Position size limit
    trade_value = trade_proposal['quantity'] * trade_proposal['entry_price']
    checks['position_size'] = trade_value <= balance * 0.05
    
    # Check 2: Daily loss limit
    today = datetime.now().date()
    cursor = conn.execute(
        "SELECT SUM(pnl) FROM trades WHERE date(closed_at) = ?", (today,)
    )
    daily_pnl = cursor.fetchone()[0] or 0
    checks['daily_loss'] = daily_pnl > -(balance * 0.03)
    
    # Check 3: Max open positions
    cursor = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
    open_count = cursor.fetchone()[0]
    checks['max_positions'] = open_count < 3
    
    # Check 4: Stop-loss present
    checks['has_stop_loss'] = trade_proposal.get('stop_loss') is not None
    
    # Check 5: Risk-reward ratio
    risk = abs(trade_proposal['entry_price'] - trade_proposal['stop_loss'])
    reward = abs(trade_proposal['take_profit'] - trade_proposal['entry_price'])
    checks['risk_reward'] = (reward / risk) >= 2.0 if risk > 0 else False
    
    # Check 6: Cooldown (no same-symbol trade within 30 min)
    cursor = conn.execute(
        "SELECT MAX(opened_at) FROM trades WHERE symbol = ? AND status IN ('OPEN','CLOSED')",
        (trade_proposal['symbol'],)
    )
    last_trade = cursor.fetchone()[0]
    if last_trade:
        elapsed = (datetime.now() - datetime.fromisoformat(last_trade)).seconds
        checks['cooldown'] = elapsed > 1800
    else:
        checks['cooldown'] = True
    
    conn.close()
    
    approved = all(checks.values())
    return {
        "approved": approved,
        "checks": checks,
        "checks_passed": f"{sum(checks.values())}/{len(checks)}"
    }
```

---

## 5. Risk Rules (Basic)

### Hard Rules (NEVER violate)
| Rule | Value | Action on Violation |
|------|-------|---------------------|
| Max position | 5% of balance | Reject trade |
| Risk per trade | 2% of balance | Reduce size |
| Daily loss limit | -2% of balance | Stop trading for the day |
| Stop-loss required | Every trade | Reject if missing |
| Max open positions | 3 | Wait for close |
| Min R:R ratio | 2:1 | Reject trade |

### Soft Rules (Log & learn)
| Rule | Value | Action on Violation |
|------|-------|---------------------|
| Cooldown per symbol | 30 min | Log warning, still reject |
| Max trades per day | 10 | Log warning |
| Avoid trading during news | 5 min before/after | Log warning (v2: auto-detect) |

### Daily Shutdown Sequence
```
IF daily_pnl <= -2% of balance:
    1. Cancel all open orders
    2. Close all positions (market orders)
    3. Send Telegram alert: "🚨 DAILY LIMIT HIT. Trading halted."
    4. Log to lessons table
    5. Resume tomorrow at market open
```

### Emergency Kill Switch
```
Telegram command: /stop
→ Immediately:
    1. Cancel all orders
    2. Close all positions
    3. Set system to HALTED state
    4. Require /start to resume
```

---

## 6. Strategy: Mean Reversion on BTC/USDT

### Entry Rules (LONG)
```
WHEN ALL conditions are true:
    1. RSI(14) on 1H chart < 30
    2. Price is within 0.5% of a support level (last 48H swing low)
    3. Current volume > 1.2x 20-period average volume
    4. No open SHORT position on BTC/USDT

THEN:
    → Generate BUY signal
    → Entry: current market price
    → Stop-loss: 0.5% below support level
    → Take-profit: 2x the risk distance above entry
```

### Entry Rules (SHORT)
```
WHEN ALL conditions are true:
    1. RSI(14) on 1H chart > 70
    2. Price is within 0.5% of a resistance level (last 48H swing high)
    3. Current volume > 1.2x 20-period average volume
    4. No open LONG position on BTC/USDT

THEN:
    → Generate SELL signal
    → Entry: current market price
    → Stop-loss: 0.5% above resistance level
    → Take-profit: 2x the risk distance below entry
```

### Support/Resistance Detection (Simplified)
```python
def find_support_resistance(df: pd.DataFrame, lookback: int = 48) -> dict:
    """
    Find S/R levels using swing highs and lows.
    lookback: number of candles to look back (48 = 48 hours on 1H chart)
    """
    recent = df.tail(lookback)
    
    # Swing lows (support): candle where low is lower than neighbors
    supports = []
    for i in range(2, len(recent) - 2):
        if (recent.iloc[i]['low'] < recent.iloc[i-1]['low'] and
            recent.iloc[i]['low'] < recent.iloc[i-2]['low'] and
            recent.iloc[i]['low'] < recent.iloc[i+1]['low'] and
            recent.iloc[i]['low'] < recent.iloc[i+2]['low']):
            supports.append(recent.iloc[i]['low'])
    
    # Swing highs (resistance): candle where high is higher than neighbors
    resistances = []
    for i in range(2, len(recent) - 2):
        if (recent.iloc[i]['high'] > recent.iloc[i-1]['high'] and
            recent.iloc[i]['high'] > recent.iloc[i-2]['high'] and
            recent.iloc[i]['high'] > recent.iloc[i+1]['high'] and
            recent.iloc[i]['high'] > recent.iloc[i+2]['high']):
            resistances.append(recent.iloc[i]['high'])
    
    return {
        "supports": sorted(supports)[-3:],      # Top 3 most recent
        "resistances": sorted(resistances)[-3:]  # Top 3 most recent
    }
```

### Exit Rules
| Exit Type | Condition | Action |
|-----------|-----------|--------|
| Stop-loss hit | Price crosses stop | Market close, log loss |
| Take-profit hit | Price crosses target | Market close, log win |
| Time-based | Position open > 24 hours | Close at market, log as neutral |
| Daily limit | Daily P&L hits -3% | Close all, halt trading |

### Performance Targets (Paper Trading Phase)
| Metric | Target | Acceptable |
|--------|--------|------------|
| Win rate | > 55% | > 50% |
| Profit factor | > 1.5 | > 1.2 |
| Max drawdown | < 10% | < 15% |
| Avg R:R realized | > 1.8:1 | > 1.5:1 |
| Trades per week | 5–15 | 3–20 |

---

## 7. Project Structure

```
trading-super-agent/
├── config/
│   ├── settings.py          # All configuration (exchange, risk, strategy)
│   └── .env                 # API keys (NEVER commit)
├── agents/
│   ├── __init__.py
│   ├── signal_agent.py      # Scans for setups
│   ├── risk_agent.py        # Approves/rejects trades
│   └── execution_agent.py   # Places & manages orders
├── tools/
│   ├── __init__.py
│   ├── market_tools.py      # get_price, get_ohlcv, calculate_rsi
│   ├── order_tools.py       # place_order, cancel_order
│   ├── account_tools.py     # get_positions, get_balance
│   ├── risk_tools.py        # calculate_position_size, check_risk
│   └── db_tools.py          # log_trade
├── strategies/
│   ├── __init__.py
│   └── mean_reversion.py    # The first strategy
├── data/
│   └── tsar.db              # SQLite database (auto-created)
├── notifications/
│   ├── __init__.py
│   └── telegram_bot.py      # Telegram alerts & commands
├── core/
│   ├── __init__.py
│   ├── orchestrator.py      # Main loop: signal → risk → execute
│   ├── learning_loop.py     # Post-trade analysis & lesson logging
│   └── daily_report.py      # End-of-day summary
├── tests/
│   ├── test_tools.py
│   ├── test_risk.py
│   └── test_strategy.py
├── main.py                  # Entry point
├── requirements.txt
├── .env.example
└── README.md
```

**Total files to write: ~20 files. Manageable in 2–4 weeks.**

---

## 8. Requirements

```txt
# requirements.txt

# Exchange connectivity
ccxt==4.4.50

# Data & computation
pandas==2.2.3
numpy==2.2.1

# LLM integration
ollama==0.4.7              # Local model (Qwen2.5-7B)
openai==1.61.0             # For DeepSeek-R1 via NVIDIA NIM (OpenAI-compatible)

# Notifications
python-telegram-bot==21.10

# Scheduling
apscheduler==3.11.0

# Environment
python-dotenv==1.1.0

# Testing
pytest==8.3.4

# Optional: plotting (for local analysis)
matplotlib==3.10.1
```

---

## 9. Configuration

```python
# config/settings.py
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================
# EXCHANGE
# ============================================
EXCHANGE_CONFIG = {
    "name": "binance",
    "api_key": os.getenv("BINANCE_API_KEY"),
    "secret": os.getenv("BINANCE_SECRET"),
    "sandbox": True,  # ← START WITH TESTNET. Set False for live.
    "options": {
        "defaultType": "spot",
        "adjustForTimeDifference": True,
    }
}

# ============================================
# RISK PARAMETERS
# ============================================
RISK_CONFIG = {
    "max_position_pct": 5.0,      # Max 5% of balance per trade
    "risk_per_trade_pct": 2.0,    # Risk 2% of balance per trade
    "daily_loss_limit_pct": 2.0,  # Stop trading at -2% daily (canonical per ARCHITECTURE_CONSOLIDATION.md)
    "max_open_positions": 3,
    "min_risk_reward": 2.0,       # Minimum 2:1 R:R
    "cooldown_seconds": 1800,     # 30 min cooldown per symbol
    "max_trades_per_day": 10,
    "stop_loss_max_pct": 2.0,     # Stop-loss within 2% of entry
}

# ============================================
# STRATEGY
# ============================================
STRATEGY_CONFIG = {
    "name": "mean_reversion",
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "sr_lookback": 48,           # Candles to look back for S/R
    "sr_proximity_pct": 0.5,     # Within 0.5% of level
    "volume_multiplier": 1.2,    # Volume must be 1.2x average
    "max_hold_hours": 24,        # Close after 24h regardless
    "scan_interval_seconds": 300, # Check every 5 minutes
}

# ============================================
# MODELS
# ============================================
MODEL_CONFIG = {
    "local": {
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "base_url": "http://localhost:11434",
    },
    "reasoning": {
        "provider": "nvidia_nim",
        "model": "deepseek-ai/deepseek-r1",
        "api_key": os.getenv("NVIDIA_NIM_API_KEY"),
        "base_url": "https://integrate.api.nvidia.com/v1",
        "max_tokens": 2048,
    }
}

# ============================================
# TELEGRAM
# ============================================
TELEGRAM_CONFIG = {
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
    "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
    "commands": {
        "/status": "Show current positions and balance",
        "/stop": "Emergency stop — close all positions",
        "/start": "Resume trading after stop",
        "/pnl": "Show today's P&L",
        "/history": "Show last 10 trades",
        "/lessons": "Show recent lessons learned",
    }
}

# ============================================
# DATABASE
# ============================================
DB_PATH = "data/tsar.db"
```

---

## 10. Main Orchestrator

```python
# core/orchestrator.py
"""
The brain. Runs the signal → risk → execute loop.
"""
import time
import logging
from agents.signal_agent import SignalAgent
from agents.risk_agent import RiskAgent
from agents.execution_agent import ExecutionAgent
from notifications.telegram_bot import TelegramBot
from config.settings import STRATEGY_CONFIG, RISK_CONFIG

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self):
        self.signal_agent = SignalAgent()
        self.risk_agent = RiskAgent()
        self.execution_agent = ExecutionAgent()
        self.telegram = TelegramBot()
        self.running = False
    
    def run_cycle(self):
        """One complete scan cycle."""
        try:
            # Step 1: Signal Agent scans
            signal = self.signal_agent.scan()
            if not signal:
                logger.debug("No signal found this cycle.")
                return
            
            logger.info(f"Signal: {signal['signal']} {signal['symbol']} "
                       f"score={signal['score']:.2f}")
            
            # Step 2: Risk Agent evaluates
            approval = self.risk_agent.evaluate(signal)
            if not approval['approved']:
                logger.info(f"Risk rejected: {approval['checks_passed']}")
                return
            
            logger.info(f"Risk approved: {approval['checks_passed']}")
            
            # Step 3: Execution Agent places trade
            trade = self.execution_agent.execute(signal, approval)
            
            # Step 4: Notify
            self.telegram.notify_trade_opened(trade, signal)
            
            logger.info(f"Trade placed: {trade['trade_id']}")
            
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            self.telegram.notify_error(str(e))
    
    def run(self):
        """Main loop."""
        self.running = True
        self.telegram.notify_system("🚀 Trading Super Agent started (Paper Mode)")
        
        while self.running:
            self.run_cycle()
            
            # Check open positions for exits
            self.execution_agent.monitor_positions()
            
            # Sleep until next scan
            time.sleep(STRATEGY_CONFIG['scan_interval_seconds'])
    
    def stop(self):
        """Emergency stop."""
        self.running = False
        self.execution_agent.close_all_positions()
        self.telegram.notify_system("🛑 Trading stopped by user")
```

```python
# main.py
"""
Entry point. Run this to start the bot.
"""
import logging
from core.orchestrator import Orchestrator
from config.settings import EXCHANGE_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('data/trading.log'),
        logging.StreamHandler()
    ]
)

def main():
    logger = logging.getLogger(__name__)
    
    # Verify testnet mode
    if EXCHANGE_CONFIG.get('sandbox'):
        logger.info("⚠️  Running in TESTNET (paper trading) mode")
    else:
        logger.warning("🔴 Running in LIVE mode — real money at risk!")
        confirm = input("Type 'CONFIRM LIVE' to proceed: ")
        if confirm != "CONFIRM LIVE":
            logger.info("Aborted.")
            return
    
    orchestrator = Orchestrator()
    
    try:
        orchestrator.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        orchestrator.stop()

if __name__ == "__main__":
    main()
```

---

## 11. How to Run

### Step 1: Setup (30 minutes)

```bash
# Clone / create project
mkdir trading-super-agent && cd trading-super-agent

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Setup Ollama (local LLM)
# Install: https://ollama.ai
ollama pull qwen2.5:7b

# Create .env file
cp .env.example .env
# Edit .env with your keys
```

### Step 2: Get API Keys (15 minutes)

```bash
# 1. Binance TESTNET
#    → https://testnet.binance.vision/
#    → Generate API key + secret
#    → Put in .env

# 2. Telegram Bot
#    → Message @BotFather on Telegram
#    → /newbot → follow prompts
#    → Copy bot token to .env
#    → Send a message to your bot, then:
#    → https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
#    → Find your chat_id, put in .env

# 3. NVIDIA NIM (free tier, for DeepSeek-R1)
#    → https://build.nvidia.com/
#    → Sign up → get API key
#    → Put in .env
```

### Step 3: `.env.example`

```bash
# .env.example — copy to .env and fill in your values

# Binance Testnet
BINANCE_API_KEY=your_testnet_api_key
BINANCE_SECRET=your_testnet_secret

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# NVIDIA NIM (optional, for complex reasoning)
NVIDIA_NIM_API_KEY=your_nvidia_key

# Trading mode
TRADING_MODE=paper  # paper or live
```

### Step 4: Test (30 minutes)

```bash
# Run unit tests
pytest tests/ -v

# Run a single scan cycle (dry run)
python -c "
from agents.signal_agent import SignalAgent
sa = SignalAgent()
signal = sa.scan()
print(f'Signal: {signal}')
"

# Check balance on testnet
python -c "
from tools.account_tools import get_balance
print(get_balance())
"
```

### Step 5: Run (Paper Trading)

```bash
# Start the bot
python main.py

# You should see:
# ⚠️  Running in TESTNET (paper trading) mode
# 🚀 Trading Super Agent started (Paper Mode)
# [INFO] Scanning BTC/USDT...
```

### Step 6: Monitor via Telegram

Commands available:
- `/status` — Current positions, balance
- `/pnl` — Today's P&L
- `/history` — Last 10 trades
- `/stop` — Emergency stop
- `/start` — Resume
- `/lessons` — Recent learnings

---

## 12. How to Switch to Live Trading

### Prerequisites (Don't skip ANY)
- [ ] Paper trading for ≥ 2 weeks
- [ ] ≥ 30 trades logged
- [ ] Win rate > 50%
- [ ] Profit factor > 1.2
- [ ] Max drawdown < 15%
- [ ] All Telegram commands working
- [ ] Emergency stop tested
- [ ] Daily reports reviewing fine

### Switch Steps

```bash
# 1. Get Binance LIVE API keys
#    → https://www.binance.com/en/my/settings/api-management
#    → Create key with ONLY "Enable Spot & Margin Trading"
#    → DO NOT enable withdrawals

# 2. Update .env
BINANCE_API_KEY=your_live_api_key
BINANCE_SECRET=your_live_secret

# 3. Update config/settings.py
EXCHANGE_CONFIG = {
    ...
    "sandbox": False,  # ← CHANGE THIS
}

# 4. Start with MINIMUM capital
#    → Transfer exactly $10 to Binance spot wallet
#    → This is your max risk

# 5. Run with confirmation
python main.py
# Type 'CONFIRM LIVE' when prompted
```

### Live Trading Safety Checklist
- [ ] Withdrawal permissions DISABLED on API key
- [ ] IP whitelist enabled (your IP only)
- [ ] Start with $10 only
- [ ] Monitor first 5 trades manually
- [ ] Keep daily loss limit at -3%
- [ ] Review lessons after every trade
- [ ] Graduate to larger capital only after 50+ live trades

---

## 13. Upgrade Path

### Phase 1: Foundation (Weeks 1–2) ← YOU ARE HERE
- 3 agents, 10 tools, 1 strategy, paper trading
- Goal: Get it running, place first paper trades

### Phase 2: Learning Loop (Weeks 3–4)
- Add post-trade analysis to `learning_loop.py`
- LLM reviews each trade, generates lessons
- Lessons feed back into strategy parameters
- Goal: 30+ paper trades, validate learning loop

### Phase 3: First Live Trades (Weeks 5–6)
- Switch to live with $10
- Tight risk limits (1% per trade, -2% daily)
- Manual review of every trade
- Goal: 10+ live trades, prove it works with real money

### Phase 4: Second Strategy (Weeks 7–8)
- Add Momentum strategy (RSI + MACD trend following)
- Multi-strategy signal scoring
- Goal: Compare strategy performance

### Phase 5: Scale (Weeks 9–12)
- Increase capital to $50–100
- Add more pairs (ETH/USDT)
- Move to VPS for 24/7 operation
- Goal: Consistent daily returns

### Phase 6: Institutional Path (Months 4+)
- Add remaining agents (up to 8)
- Add remaining tools (up to 35)
- Multi-exchange support
- Multi-market (forex, gold)
- Full backtesting framework
- Dashboard + analytics
- Goal: Replace the simplified components one by one

### Component Upgrade Triggers
| Component | Upgrade When |
|-----------|-------------|
| SQLite → PostgreSQL | > 100K trades or need concurrent access |
| 3 → 5 agents | 3 agents proven, need specialized analysis |
| 5 → 8 agents | Need market-making, arbitrage agents |
| 10 → 20 tools | Need advanced order types, multiple timeframes |
| 20 → 35 tools | Need options, futures, cross-exchange |
| Laptop → VPS | Need 24/7 uptime |
| Telegram → + Dashboard | Need visual analytics |
| Basic risk → Full risk | Capital > $1,000 |
| Mean reversion → + Momentum | MR strategy validated |
| BTC only → + ETH | BTC strategy validated |
| Spot → + Futures | Spot strategy validated |
| Crypto → + Forex | Crypto strategy validated |

---

## 14. Learning Loop (The Super Agent DNA)

This is what separates a trading bot from a Super Agent. Every trade teaches it something.

### Post-Trade Analysis Flow
```
Trade closes
    ↓
Log outcome to DB (win/loss, P&L, duration)
    ↓
LLM analyzes the trade:
    - What went right?
    - What went wrong?
    - What would I do differently?
    ↓
Generate lesson entry in `lessons` table
    ↓
Weekly review: aggregate lessons → update strategy parameters
```

### Lesson Categories
| Category | Example |
|----------|---------|
| ENTRY | "RSI was 29 but price hadn't reached support. Wait for both." |
| EXIT | "Exited at take-profit but price continued. Consider trailing stop." |
| SIZING | "Position was too small to matter. Increase to 3% risk." |
| TIMING | "Trade during Asian session had low volume. Prefer US session." |
| REGIME | "Mean reversion fails in trending markets. Add regime filter." |

### How Lessons Feed Back
```python
# Weekly strategy parameter adjustment
def adjust_strategy_from_lessons():
    """Read recent lessons, suggest parameter changes."""
    lessons = get_recent_lessons(days=7)
    
    prompt = f"""
    You are a trading strategy analyst. Based on these lessons from the past week,
    suggest concrete parameter adjustments for our mean reversion strategy.
    
    Current parameters:
    - RSI oversold: {rsi_oversold}
    - RSI overbought: {rsi_overbought}
    - S/R proximity: {sr_proximity}%
    - Volume multiplier: {volume_mult}x
    
    Lessons:
    {format_lessons(lessons)}
    
    Suggest specific parameter changes with reasoning.
    """
    
    # Use local Ollama for this analysis
    suggestions = query_ollama(prompt)
    return suggestions
```

---

## 15. What NOT to Build on Day 1

Things that tempt you but will slow you down:

| Don't Build | Why | Build Instead |
|-------------|-----|---------------|
| Custom charting | Use exchange UI | Focus on the bot |
| Backtesting engine | Paper trading IS your backtest | Log everything, analyze after |
| Web dashboard | Telegram is enough | Dashboard in Phase 4 |
| Multi-exchange | One is enough to learn | Add in Phase 5 |
| Multi-timeframe | 1H is enough for mean reversion | Add when needed |
| Machine learning | Rules work fine for now | Add when you have data |
| WebSocket feeds | REST polling is fine for 5-min | Add when speed matters |
| Options/futures | Spot is simpler | Add when spot is profitable |
| Custom indicators | RSI + S/R is enough | Add one at a time |
| Auto-rebalancing | Manual is fine for $10 | Automate at $100+ |

---

## 16. Estimated Build Timeline

| Week | Tasks | Deliverable |
|------|-------|-------------|
| **1** | Project setup, DB schema, 10 tools, Binance testnet connection | Can query price & balance |
| **2** | 3 agents, orchestrator loop, Telegram bot | Can scan & notify (no trades yet) |
| **3** | Mean reversion strategy, first paper trades, logging | First paper trades placed |
| **4** | Learning loop, daily reports, polish, bug fixes | Full paper trading system running |
| **5+** | Paper trade review, live prep, first real trades | $10 live trading begins |

### Daily Breakdown (Week 1)
```
Day 1: Project scaffold, venv, .env, requirements.txt
Day 2: DB schema, sqlite setup, db_tools.py
Day 3: market_tools.py (get_price, get_ohlcv, calculate_rsi)
Day 4: account_tools.py (get_balance, get_positions)
Day 5: order_tools.py (place_order, cancel_order), test on testnet
Day 6: risk_tools.py (calculate_position_size, check_risk)
Day 7: Buffer day — test everything end-to-end
```

---

## Appendix A: FAQ

**Q: Can I really start with $10?**
A: Yes. Binance minimum order is $10 notional. With $10 balance and 5% position sizing, each trade is $0.50. That's tiny but real. The point is to prove the system works, not to get rich.

**Q: Why not start with more money?**
A: Because you WILL have bugs. You WILL make mistakes. Better to learn with $10 than $1,000. Graduate to more capital after 50+ profitable live trades.

**Q: Do I need a GPU for the local LLM?**
A: No. Qwen2.5-7B runs on CPU (slower but fine for 5-minute intervals). If you have a GPU, great. If not, the NIM free API handles the complex reasoning.

**Q: What if Binance testnet is down?**
A: Use ccxt's sandbox mode with any supported exchange's testnet. Or mock the exchange for pure logic testing.

**Q: How do I know if the strategy works?**
A: After 30+ paper trades, check: Win rate > 50%, Profit factor > 1.2, Max drawdown < 15%. If all pass, try live with $10. If any fail, adjust parameters using lessons learned.

---

*This document is the Day 1 blueprint. Build it, ship it, learn from it. The full institutional architecture is the destination — this is the first step.*
