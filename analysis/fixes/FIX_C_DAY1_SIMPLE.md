# FIX_C: DAY1 SIMPLIFIED — Solo Developer Edition

> **Scope:** 25 files, 0 Rust, 3 agents, 10 tools, 1 strategy, SQLite only
> **Timeline:** 4 weeks (20 working days)
> **Goal:** A paper-trading bot that actually ships

---

## 1. Architecture

```
┌──────────────────────────────────────────────────────┐
│                  TSAR Day1 Simple                     │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌──────────────┐   │
│  │  SIGNAL    │─▶│    RISK    │─▶│  EXECUTION   │   │
│  │  AGENT     │  │   AGENT    │  │   AGENT      │   │
│  └────────────┘  └────────────┘  └──────────────┘   │
│        │               │                │            │
│        ▼               ▼                ▼            │
│  ┌──────────────────────────────────────────────┐    │
│  │            SQLite (data/tsar.db)             │    │
│  └──────────────────────────────────────────────┘    │
│        │               │                │            │
│        ▼               ▼                ▼            │
│  ┌──────────┐   ┌───────────┐   ┌──────────────┐    │
│  │  Ollama  │   │ DeepSeek  │   │   Binance    │    │
│  │ (local)  │   │ (NIM API) │   │ (ccxt/test)  │    │
│  └──────────┘   └───────────┘   └──────────────┘    │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │        Telegram Bot (6 commands)             │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

**Data flow:** Signal scans BTC/USDT → Risk gates the trade → Execution places order → SQLite logs everything → Telegram notifies you.

---

## 2. File List (25 files)

```
tsar/
├── main.py                          # Entry point — starts orchestrator
├── requirements.txt                 # ≤20 Python packages
├── .env.example                     # API keys template
├── README.md                        # Setup guide
│
├── config/
│   └── default.yaml                 # All config in one file (exchange, risk, strategy, LLM, telegram)
│
├── data/
│   └── (tsar.db created at runtime) # SQLite database
│
├── db/
│   ├── schema.py                    # CREATE TABLE statements, init_db()
│   └── queries.py                   # All SQL queries as functions
│
├── tools/
│   ├── market.py                    # get_price, get_ohlcv, calculate_rsi, find_support_resistance
│   ├── order.py                     # place_order, cancel_order
│   ├── account.py                   # get_balance, get_positions
│   └── risk.py                      # calculate_position_size, check_risk
│
├── agents/
│   ├── signal_agent.py              # RSI + S/R scanning, scoring
│   ├── risk_agent.py                # Rule-based gatekeeper
│   └── execution_agent.py           # Order lifecycle, monitoring
│
├── llm/
│   └── router.py                    # 100-line LLM router (Ollama + DeepSeek direct calls)
│
├── strategy/
│   └── mean_reversion.py            # Entry/exit rules for BTC/USDT
│
├── core/
│   ├── orchestrator.py              # Main loop: scan → risk → execute → notify
│   └── daily_report.py              # End-of-day P&L summary
│
├── bot/
│   └── telegram_bot.py              # 6 commands + notification helpers
│
└── tests/
    ├── test_tools.py                # Unit tests for all tools
    ├── test_risk.py                 # Unit tests for risk checks
    └── test_strategy.py             # Unit tests for strategy logic
```

**Total: 25 files** (including requirements.txt, .env.example, README.md)

---

## 3. requirements.txt (17 packages)

```txt
# === Exchange ===
ccxt==4.4.50

# === Data ===
pandas==2.2.3
numpy==2.2.1

# === LLM ===
ollama==0.4.7              # Local Ollama client
openai==1.61.0             # DeepSeek via NVIDIA NIM (OpenAI-compatible)

# === Telegram ===
python-telegram-bot==21.10

# === Scheduling ===
apscheduler==3.11.0

# === Config ===
python-dotenv==1.1.0
pyyaml==6.0.2

# === Testing ===
pytest==8.3.4

# === Logging ===
structlog==24.4.0

# === Utilities ===
tenacity==8.5.1            # Retry logic for API calls
rich==13.9.4               # Pretty console output
```

**17 packages.** No Redis, no ChromaDB, no Celery, no LiteLLM, no TA-Lib, no vectorbt, no SQLAlchemy, no Pydantic, no FastAPI.

---

## 4. config/default.yaml

```yaml
# ============================================================
# TSAR Day1 — Single config file
# ============================================================

exchange:
  name: binance
  sandbox: true                    # ← TESTNET. Always start here.
  options:
    defaultType: spot
    adjustForTimeDifference: true

strategy:
  name: mean_reversion
  symbol: BTC/USDT
  timeframe: 1h
  rsi_period: 14
  rsi_oversold: 30
  rsi_overbought: 70
  sr_lookback: 48                  # Candles for S/R detection
  sr_proximity_pct: 0.5            # Within 0.5% of level
  volume_multiplier: 1.2           # Volume must be 1.2x average
  max_hold_hours: 24               # Force-close after 24h
  scan_interval_seconds: 300       # Check every 5 minutes

risk:
  max_position_pct: 5.0            # Max 5% of balance per trade
  risk_per_trade_pct: 2.0          # Risk 2% per trade
  daily_loss_limit_pct: 2.0        # Stop at -2% daily
  max_open_positions: 3
  min_risk_reward: 2.0             # Minimum 2:1 R:R
  cooldown_seconds: 1800           # 30 min per symbol
  max_trades_per_day: 10
  stop_loss_max_pct: 2.0           # SL within 2% of entry

llm:
  local:
    provider: ollama
    model: qwen2.5:7b
    base_url: http://localhost:11434
  reasoning:
    provider: deepseek
    model: deepseek-ai/deepseek-r1
    base_url: https://integrate.api.nvidia.com/v1
    max_tokens: 2048

telegram:
  commands:
    - start
    - stop
    - status
    - pnl
    - history
    - risk
```

---

## 5. LLM Router (≤100 lines)

The router is a single file (`llm/router.py`) that calls Ollama directly and DeepSeek via the OpenAI client. No abstraction layers.

```python
# llm/router.py — Day1 LLM Router
"""
Two providers. Direct calls. No base classes, no registries.
"""
import os
import yaml
import ollama
from openai import OpenAI

_config = None

def _load_config():
    global _config
    if _config is None:
        with open("config/default.yaml") as f:
            _config = yaml.safe_load(f)
    return _config

def _call_ollama(prompt: str, model: str = "qwen2.5:7b", **kwargs) -> str:
    """Call local Ollama."""
    resp = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": kwargs.get("temperature", 0.1)},
    )
    return resp["message"]["content"]

def _call_deepseek(prompt: str, model: str = "deepseek-ai/deepseek-r1", **kwargs) -> str:
    """Call DeepSeek via NVIDIA NIM (OpenAI-compatible endpoint)."""
    cfg = _load_config()["llm"]["reasoning"]
    client = OpenAI(
        base_url=cfg["base_url"],
        api_key=os.getenv("NVIDIA_NIM_API_KEY"),
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=cfg.get("max_tokens", 2048),
        temperature=kwargs.get("temperature", 0.1),
    )
    return resp.choices[0].message.content

def generate(task_type: str, prompt: str, **kwargs) -> str:
    """
    Route a prompt to the right provider.
    task_type: "analysis" → Ollama, "reasoning" → DeepSeek
    Falls back to the other provider on error.
    """
    primary, fallback = (_call_ollama, _call_deepseek) if task_type == "analysis" \
        else (_call_deepseek, _call_ollama)
    try:
        return primary(prompt, **kwargs)
    except Exception:
        try:
            return fallback(prompt, **kwargs)
        except Exception as e:
            return f"[LLM unavailable: {e}]"
```

**~50 lines.** Two functions, one router, fallback logic. No base classes, no registries, no cost tracking.

---

## 6. Database Schema (SQLite)

```sql
-- data/tsar.db — Auto-created by db/schema.py

CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT UNIQUE NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,              -- BUY / SELL
    entry_price     REAL,
    exit_price      REAL,
    quantity        REAL NOT NULL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN / CLOSED / CANCELLED
    pnl             REAL DEFAULT 0.0,
    pnl_pct         REAL DEFAULT 0.0,
    signal_score    REAL,
    risk_approved   INTEGER DEFAULT 0,
    strategy        TEXT NOT NULL,
    exchange_order_id TEXT,
    notes           TEXT,
    opened_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at       TIMESTAMP
);

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

CREATE TABLE IF NOT EXISTS lessons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT,
    lesson_type     TEXT NOT NULL,              -- WIN / LOSS / MISTAKE
    description     TEXT NOT NULL,
    action_item     TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_lessons_trade ON lessons(trade_id);
```

**3 tables. No FTS5, no vectors, no Redis.**

---

## 7. 10 Tools (thin ccxt wrappers)

| # | File | Function | What it does |
|---|------|----------|-------------|
| 1 | `tools/market.py` | `get_price(symbol)` | Returns current price via `ccxt.fetch_ticker` |
| 2 | `tools/market.py` | `get_ohlcv(symbol, timeframe, limit)` | Returns OHLCV DataFrame via `ccxt.fetch_ohlcv` |
| 3 | `tools/market.py` | `calculate_rsi(closes, period)` | Pure Python RSI calculation (no library needed) |
| 4 | `tools/market.py` | `find_support_resistance(df, lookback)` | Swing high/low detection for S/R levels |
| 5 | `tools/order.py` | `place_order(symbol, side, quantity, type, price)` | Places market/limit order via ccxt |
| 6 | `tools/order.py` | `cancel_order(order_id, symbol)` | Cancels open order via ccxt |
| 7 | `tools/account.py` | `get_balance()` | Returns total/free/used USDT balance |
| 8 | `tools/account.py` | `get_positions()` | Returns list of open positions |
| 9 | `tools/risk.py` | `calculate_position_size(balance, risk_pct, entry, stop_loss)` | Fixed-fractional position sizing |
| 10 | `tools/risk.py` | `check_risk(trade_proposal)` | Runs all 6 risk checks, returns approval |

All tools are plain Python functions. No classes, no decorators, no registries. Each is 10–30 lines.

---

## 8. 3 Agents (no sub-agents)

### Signal Agent (`agents/signal_agent.py`)
- Fetches 1H OHLCV via `tools/market.py`
- Calculates RSI(14) via `tools/market.py`
- Finds S/R levels via `tools/market.py`
- Scores signal 0–1 (RSI weight 40%, S/R proximity 30%, volume 15%, trend 15%)
- If score > 0.6, passes signal dict to Risk Agent
- Optionally asks LLM for nuanced analysis when score is ambiguous (0.5–0.7)

### Risk Agent (`agents/risk_agent.py`)
- Pure rule-based (no LLM). Deterministic.
- 6 checks: position size, daily loss, max open positions, stop-loss present, risk-reward ≥ 2:1, cooldown
- Returns `{approved: bool, checks: dict, position_size: float}`
- Calls `tools/risk.py` functions

### Execution Agent (`agents/execution_agent.py`)
- Places market order via `tools/order.py`
- Places stop-loss and take-profit orders
- Monitors open positions every 60 seconds
- Closes positions on SL/TP hit or 24h time limit
- Logs trade to SQLite via `db/queries.py`
- Sends Telegram notifications

---

## 9. Telegram Bot (6 commands)

| Command | Action |
|---------|--------|
| `/start` | Resume trading (after `/stop`) |
| `/stop` | Emergency stop — cancel all orders, close all positions, halt |
| `/status` | Show: balance, open positions, current price, system state |
| `/pnl` | Today's P&L: realized, unrealized, win rate |
| `/history` | Last 10 trades with entry/exit/P&L |
| `/risk` | Risk metrics: daily drawdown, open positions, exposure % |

All commands are handler functions in `bot/telegram_bot.py`. No command router classes, no decorators beyond `@app.command()`.

**Notification messages:**
- 🟢 Trade opened (symbol, side, entry, size, SL, TP, signal score)
- 🔴 Trade closed (P&L, duration, result, lesson)
- 🚨 Daily limit hit (trading halted)
- 📊 Daily summary (end-of-day report)

---

## 10. 4-Week Build Plan

### Week 1: Foundation (Day-by-Day)

| Day | Task | Deliverable | Done? |
|-----|------|-------------|-------|
| **D1** | Project scaffold: `main.py`, `requirements.txt`, `.env.example`, `README.md`, venv, git init | Runs `python main.py` → prints "ready" | □ |
| **D2** | Database: `db/schema.py` (CREATE TABLE + init_db), `db/queries.py` (CRUD functions) | `python -c "from db.schema import init_db; init_db()"` creates `data/tsar.db` | □ |
| **D3** | Market tools: `tools/market.py` — `get_price`, `get_ohlcv`, `calculate_rsi` | `python -c "from tools.market import get_price; print(get_price('BTC/USDT'))"` returns a number | □ |
| **D4** | S/R + Account: `find_support_resistance` in `tools/market.py`, `tools/account.py` | RSI + S/R work on historical data; `get_balance()` returns testnet balance | □ |
| **D5** | Order tools: `tools/order.py` — `place_order`, `cancel_order` | Place a tiny market order on testnet, then cancel it | □ |
| **D6** | Risk tools: `tools/risk.py` — `calculate_position_size`, `check_risk` | Risk checks pass/reject a test proposal correctly | □ |
| **D7** | Config: `config/default.yaml`, load config in Python, `.env` integration | All tools read config from YAML + env vars | □ |

### Week 2: Agents + Strategy

| Day | Task | Deliverable |
|-----|------|-------------|
| **D8** | Signal Agent: `agents/signal_agent.py` — scan, score, produce signal dict | Scans BTC/USDT, returns signal dict or None |
| **D9** | Risk Agent: `agents/risk_agent.py` — evaluate signal, return approval | Takes signal dict, returns approved/rejected with checks |
| **D10** | Execution Agent (partial): `agents/execution_agent.py` — place trade, log to DB | Places testnet order, writes to trades table |
| **D11** | Execution Agent (monitor): position monitoring, SL/TP checking, close trade | Monitors position, closes on SL/TP, calculates P&L |
| **D12** | Strategy: `strategy/mean_reversion.py` — entry/exit rules, S/R logic | Strategy module produces entry/exit signals with reasoning |
| **D13** | Orchestrator: `core/orchestrator.py` — signal → risk → execute loop | `python main.py` runs scan loop, no trades yet (dry run) |
| **D14** | Integration test: end-to-end signal → risk → execute on testnet | First paper trade placed and logged in SQLite |

### Week 3: Telegram + LLM

| Day | Task | Deliverable |
|-----|------|-------------|
| **D15** | Telegram bot: `bot/telegram_bot.py` — `/start`, `/stop`, `/status` | Bot responds to commands |
| **D16** | Telegram commands: `/pnl`, `/history`, `/risk` | All 6 commands work |
| **D17** | Telegram notifications: trade opened/closed, daily summary | Bot sends alerts on trade events |
| **D18** | LLM router: `llm/router.py` — Ollama + DeepSeek direct calls | `generate("analysis", "test prompt")` returns response |
| **D19** | LLM integration: Signal Agent uses LLM for ambiguous signals | Signal Agent asks LLM when score is 0.5–0.7 |
| **D20** | Daily report: `core/daily_report.py` — end-of-day summary | `/status` includes daily P&L summary |

### Week 4: Polish + Validation

| Week | Focus | Deliverable |
|------|-------|-------------|
| **W4-S1** | Tests: `tests/test_tools.py`, `tests/test_risk.py`, `tests/test_strategy.py` | All unit tests pass (`pytest tests/ -v`) |
| **W4-S2** | Bug fixes: run bot for 3+ days continuously, fix issues found | Bot runs 24h without crash |
| **W4-S3** | Logging + error handling: structured logging via structlog, graceful error recovery | Errors logged, bot doesn't crash on API failures |
| **W4-S4** | Documentation: update README.md with setup guide, config reference, command list | New user can set up and run in 30 minutes |

---

## 11. Success Criteria

### Must-Have (Day1 ship-blockers)

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | Bot starts and connects to Binance testnet | `python main.py` → "Connected to Binance testnet" |
| 2 | Signal Agent detects at least one setup per 24h | Check logs for "Signal found" entries |
| 3 | Risk Agent correctly rejects invalid trades | Unit tests pass for all 6 risk checks |
| 4 | Execution Agent places and tracks orders on testnet | trades table has ≥1 entry with status OPEN → CLOSED |
| 5 | All 6 Telegram commands respond | Send each command, get expected response |
| 6 | Emergency `/stop` works | Place order → `/stop` → all orders cancelled, positions closed |
| 7 | SQLite logs every trade with P&L | `SELECT * FROM trades` shows complete records |
| 8 | Daily report generates correctly | `/pnl` shows accurate daily P&L |
| 9 | No crashes for 24h continuous operation | Run overnight, check logs for exceptions |
| 10 | Unit tests pass | `pytest tests/ -v` → 0 failures |

### Nice-to-Have (post-Day1)

| # | Criterion |
|---|-----------|
| 1 | Win rate > 50% after 20+ paper trades |
| 2 | LLM analysis improves signal quality (measurable) |
| 3 | Daily report is useful for manual review |
| 4 | Code is clean enough for a Day30 refactor |

---

## 12. What's NOT in Day1

| Excluded | Why | When to add |
|----------|-----|-------------|
| Rust / PyO3 | Zero need at 5-min scan intervals | Day30+ (only if measured bottleneck) |
| Redis | SQLite handles <10K trades fine | Day30 (caching only) |
| ChromaDB | No vector search needed for 1 strategy | Level 3 |
| LiteLLM | 2 providers don't need an abstraction layer | Day30 (if adding 3+ providers) |
| Celery | APScheduler handles the scan loop | Day30 (if adding background tasks) |
| FastAPI / REST API | Telegram is enough for monitoring | Day30 |
| Docker | `python main.py` is fine for solo dev | Day30 |
| Prometheus / Grafana | Logs + Telegram are enough | Level 2 |
| Backtesting | Paper trading IS the backtest | Day30 (vectorbt standalone) |
| Multi-exchange | One exchange to learn | Level 2 |
| Multi-strategy | One strategy to validate | Day30 (add momentum) |
| WebSocket feeds | REST polling at 5-min intervals is fine | Level 2 |
| BaseLLMProvider abstraction | 2 providers, 1 file, ~50 lines | Level 2 (FIX_01) |
| CloudEvents | No inter-agent messaging bus needed | Level 2+ |
| Sub-agents | 3 agents is enough for Day1 | Level 2 |

---

## 13. Migration Path to Day30

After Day1 is running and generating paper trades:

1. **Add Redis** — LLM response cache only (not Streams)
2. **Add momentum strategy** — RSI + MACD trend following
3. **Add vectorbt backtesting** — standalone script, not integrated
4. **Improve Telegram** — add `/backtest` and `/config` commands
5. **Add structlog + basic Prometheus** — structured logging, 3-4 key metrics

Day30 spec to be defined after Day1 ships.

---

*This is the buildable spec. 25 files. 17 packages. 0 Rust. 4 weeks. Ship it.*
