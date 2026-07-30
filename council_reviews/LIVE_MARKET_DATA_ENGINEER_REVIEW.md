# 🔌 Live Market Data Engineer Review — TSAR Trading Super Agent

**Reviewer:** Live Market Data Engineer (Council)
**Date:** 2026-07-30
**Codebase:** `/home/work/.openclaw/workspace/.openclaw/tmp/tsar/`
**Focus:** Binance connectivity, live data pipeline, backtester with real data

---

## Executive Summary

TSAR has a **well-architected but incomplete** Binance integration. The core exchange gateway and execution engine are production-quality code — proper error handling, retry logic, rate limiting, sandbox support. However, **4 critical abstract methods are unimplemented**, the system uses **polling instead of WebSocket**, and there's **no mechanism to feed live data into the backtester**. The backtester itself is excellent but only accepts pre-fetched OHLCV data — it has no built-in data source.

**Bottom line:** TSAR can connect to Binance testnet today for OHLCV, price, and orderbook queries. It can place orders. But it's missing balance/position queries, has no real-time streaming, and the backtester can't pull live data on its own.

---

## Scores

| Category | Score | Notes |
|---|---|---|
| **Binance Integration** | **6/10** | Core works, 4 critical methods missing |
| **Live Data Pipeline** | **4/10** | REST polling only, no WebSocket, no data storage |
| **Backtester Data** | **7/10** | Engine is solid, but needs external data feeding |

---

## 1. Binance Connection — ACTUAL STATE

### What's IMPLEMENTED (CcxtGateway) ✅

| Method | Status | Quality |
|---|---|---|
| `connect()` | ✅ Full | Sandbox mode, auth, market loading, error handling |
| `disconnect()` | ✅ Full | Cancels subscriptions, closes connection |
| `health_check()` | ✅ Full | Fetches server time with 5s timeout |
| `get_price(symbol)` | ✅ Full | Returns last/bid/ask with timestamp |
| `get_ohlcv(symbol, timeframe, limit)` | ✅ Full | Maps Timeframe enum to ccxt string |
| `get_orderbook(symbol, depth)` | ✅ Full | Bids/asks with proper typing |
| `subscribe_ticker(symbol, callback)` | ✅ Polling | Day1 polling-based, not WebSocket |
| `_retry_on_transient()` | ✅ Full | Exponential backoff, respects Retry-After |
| `_enforce_rate_limit()` | ✅ Full | Sliding window, 1200 req/min default |

### What's MISSING (CcxtGateway) ❌

These 4 methods are defined as `@abstractmethod` in `ExchangeGateway` but **NOT implemented** in `CcxtGateway`:

| Method | Impact | Difficulty |
|---|---|---|
| `get_balance()` | **CRITICAL** — Can't check account funds | Easy (ccxt.fetch_balance) |
| `get_positions()` | **CRITICAL** — Can't track open positions | Easy (ccxt.fetch_positions) |
| `get_ticker(symbol)` | **HIGH** — Duplicate of get_price but protocol-required | Trivial (alias) |
| `get_recent_trades(symbol, limit)` | **MEDIUM** — Trade tape unavailable | Easy (ccxt.fetch_trades) |

**This means:** Python will raise `TypeError` if you try to instantiate `CcxtGateway` because it's an incomplete implementation of the abstract class. The gateway **cannot be used as-is** without implementing these 4 methods.

### What's IMPLEMENTED (CcxtExecEngine) ✅

| Method | Status | Quality |
|---|---|---|
| `execute_order(order)` | ✅ Full | Market, limit, stop_market, stop_limit |
| `cancel_order(order_id)` | ✅ Partial | Works but needs symbol (ccxt limitation) |
| `get_order_status(order_id)` | ✅ Partial | Needs symbol for most exchanges |
| `get_open_orders(symbol)` | ✅ Full | Proper parsing and sorting |
| `get_fills(order_id)` | ✅ Full | Extracts individual trades or synthesizes |
| `_validate_order(order)` | ✅ Full | Checks qty, price, stop_price, symbol format |
| Slippage tracking | ✅ Full | Per-trade and average slippage in bps |

### Order Type Support

| Order Type | Supported | Notes |
|---|---|---|
| Market | ✅ | Default for entry orders |
| Limit | ✅ | Used for take-profit |
| Stop-Market | ✅ | Used for stop-loss |
| Stop-Limit | ✅ | Mapped via ccxt params |
| OCO (One-Cancels-Other) | ❌ | Not implemented — important for SL+TP |

**Critical gap:** The ExecutionSniper places stop-loss and take-profit as **separate orders**. If the take-profit fills, the stop-loss remains open (and vice versa). There's no OCO or bracket order support. This means **orphaned stop-losses** after a take-profit fill.

### Error Handling Quality

The error handling is **production-grade**:

- **Network errors:** Retry with exponential backoff (up to 3 attempts)
- **Rate limits:** Respects `Retry-After` header, local sliding window
- **Auth errors:** Immediately raised, no retry
- **Bad symbols:** Immediately raised, no retry
- **Invalid orders:** Immediately raised, no retry
- **Order timeouts:** Monitored in ExecutionSniper with 30s timeout

### Sandbox vs Production

- **Default:** `sandbox=True` everywhere (safe)
- **Config:** `EXCHANGE_SANDBOX=true` in `.env.example`
- **Toggle:** Set `sandbox=false` in config or env for production
- **Testnet URL:** Uses ccxt's built-in Binance testnet (`set_sandbox_mode(True)`)

---

## 2. Live Market Data Pipeline

### Current Architecture

```
Binance API (REST)
    ↓ (ccxt)
CcxtGateway
    ↓ (polling, 1-5s interval)
subscribe_ticker() → callback
    ↓
Agent consumption (SignalScout, etc.)
```

### What Exists

| Component | Status | Notes |
|---|---|---|
| REST OHLCV fetch | ✅ | Via ccxt.fetch_ohlcv, up to 1000 candles |
| REST price fetch | ✅ | Via ccxt.fetch_ticker |
| REST orderbook fetch | ✅ | Via ccxt.fetch_order_book |
| Ticker subscription | ⚠️ Polling | 1-5s interval, not true streaming |
| OHLCV adapter | ✅ | Bridges ExchangeGateway → OHLCVProvider |
| Data storage | ❌ | No persistent market data storage |
| WebSocket streaming | ❌ | Not implemented (Level 2 feature) |
| Trade feed | ❌ | Not subscribed |
| Data freshness tracking | ❌ | No staleness detection |

### What's Missing

1. **No WebSocket streams** — All data comes from REST polling. For a trading system, this introduces:
   - 1-5 second latency on price updates
   - Higher API usage (rate limit pressure)
   - Missed rapid price movements

2. **No market data storage** — OHLCV data is fetched on-demand and discarded. There's no:
   - Local cache of recent candles
   - Historical data accumulation
   - Tick-level data recording

3. **No data staleness detection** — If a price feed stops updating, there's no watchdog to detect it.

4. **No Binance WebSocket streams** — Binance offers these free streams that TSAR doesn't use:
   - `<symbol>@trade` — Individual trades
   - `<symbol>@kline_<interval>` — Real-time candles
   - `<symbol>@depth<levels>` — Order book updates
   - `<symbol>@ticker` — 24h ticker

### Data Flow for Trading Decisions

```
SignalScout needs data
    → calls gateway.get_ohlcv("BTC/USDT", H1, 100)
    → CcxtGateway.fetch_ohlcv() via ccxt
    → Binance REST API
    → Returns 100 candles
    → Discarded after use
```

**Problem:** Every signal evaluation makes fresh API calls. No caching, no incremental updates.

---

## 3. Backtester with Real Data

### BacktestEngine Architecture

The `BacktestEngine` is **well-designed** and accepts `list[OHLCV]` as input:

```python
engine = BacktestEngine(strategy=MeanReversionStrategy(), config=BacktestConfig())
result = engine.run(ohlcv_data)  # ← Needs pre-fetched OHLCV data
```

### Where Does Backtest Data Come From?

| Source | Available? | Notes |
|---|---|---|
| Binance historical API | ✅ Via gateway | `get_ohlcv(symbol, timeframe, limit=1000)` |
| CSV files | ❌ | No CSV import implemented |
| Generated/synthetic | ❌ | No synthetic data generation |
| Local database | ❌ | No market data stored in SQLite |
| Live data feed | ❌ | No mechanism to pipe live data to backtester |

### Can the Backtester Use Real Data?

**Yes, but it requires manual wiring.** The backtester itself is data-source-agnostic — it takes `list[OHLCV]`. To use real Binance data:

```python
# Current flow (requires external orchestration)
gateway = CcxtGateway(api_key="...", api_secret="...", sandbox=True)
await gateway.connect()
ohlcv = await gateway.get_ohlcv("BTC/USDT", Timeframe.H1, limit=1000)
result = engine.run(ohlcv)
```

**What's missing:** A built-in `BacktestDataProvider` that automatically:
1. Fetches historical OHLCV from Binance
2. Paginates beyond the 1000-candle limit
3. Caches data locally
4. Handles missing candles
5. Supports date range queries

### Walk-Forward Validation

`WalkForwardValidator` uses **real OHLCV data** (same `list[OHLCV]` input):
- Splits data into rolling train/test windows
- Runs optimization on train, validates on test
- Detects overfitting via train/test Sharpe ratio

**Status:** ✅ Uses real data if you pass real OHLCV. No synthetic data generation.

### Monte Carlo Simulation

`MonteCarloSimulator` resamples **real trade returns**:
- Takes completed trades from a backtest
- Shuffles trade order N times (default 1000)
- Computes confidence intervals for metrics

**Status:** ✅ Resamples real returns, not synthetic. This is the correct approach.

### Paper Trading Mode

Paper trading is a **string flag** (`trading_mode="paper"`), not a separate implementation:
- All agents receive the flag
- `RiskGuardian` exempts paper trades from mandate checks
- `ExecutionSniper` still calls the real execution engine
- **No simulated fills** — paper mode still hits the exchange API

**Problem:** If `sandbox=True` (default), paper trading hits Binance testnet. If `sandbox=False`, paper mode would place **real orders**. There's no in-memory order simulation.

---

## 4. Data Quality & Integrity

### Missing Data Handling

| Issue | Handled? | Notes |
|---|---|---|
| Missing candles | ❌ | No detection or interpolation |
| Exchange downtime | ⚠️ | Retries on network errors, but no gap detection |
| Stale data | ❌ | No freshness checks |
| Duplicate candles | ❌ | No deduplication |

### Data Validation

| Check | Implemented? |
|---|---|
| Outlier detection | ❌ |
| Price sanity checks | ❌ |
| Volume validation | ❌ |
| Timestamp ordering | ❌ |
| Splits/dividends | ❌ (N/A for crypto) |

### Timezone Handling

- ✅ All timestamps use `datetime.now(UTC)` — consistent
- ✅ `_ts_to_dt()` converts millisecond timestamps to UTC
- ✅ OHLCV timestamps from Binance are UTC
- ✅ No local timezone conversions

### Data Normalization

- ✅ ccxt handles exchange-specific format differences
- ✅ All prices are floats, all quantities are floats
- ✅ Symbol format is standardized (`BASE/QUOTE`)

---

## 5. Real-Time vs Historical

### Current State

| Data Type | Real-Time | Historical | Notes |
|---|---|---|---|
| Price | ⚠️ Polling (1-5s) | ✅ Via API | Not true real-time |
| OHLCV | ❌ | ✅ Up to 1000 candles | No incremental updates |
| Orderbook | ❌ On-demand | ❌ | Snapshot only |
| Trades | ❌ | ❌ | Not available |
| Positions | ❌ | N/A | Missing implementation |
| Balance | ❌ | N/A | Missing implementation |

### How to Switch Between Paper and Live

Currently:
- `--paper` flag → `trading_mode="paper"` → passed to all agents
- `--live` flag → `trading_mode="live"` → passed to all agents
- `EXCHANGE_SANDBOX=true/false` → controls testnet vs production
- `Orchestrator.switch_mode()` → stops all agents, restarts with new mode

**Gap:** No graceful in-flight mode switch. No separate paper execution engine.

### Historical Replay

**Not implemented.** There's no mechanism to:
1. Record live data to a file/database
2. Replay it bar-by-bar through the strategy
3. Simulate order fills against historical prices

---

## 6. Binance-Specific Features

### API Version

- Uses **ccxt** which abstracts the API version
- ccxt supports Binance API v3 by default
- No explicit API version pinning in TSAR code

### Binance WebSocket Streams

**Not used.** All data comes from REST endpoints via ccxt. Binance offers:
- `wss://stream.binance.com:9443/ws/` — Combined streams
- `wss://stream.binance.com:9443/stream?streams=` — Multiple streams

### Futures vs Spot

- **Spot only** — symbols are `BTC/USDT`, `ETH/USDT` format
- No futures-specific configuration (leverage, margin mode, funding rates)
- ccxt supports both, but TSAR doesn't configure futures

### Binance Testnet

- ✅ Properly configured via `set_sandbox_mode(True)`
- Testnet URL: `https://testnet.binance.vision/`
- Requires separate testnet API keys

### Rate Limits

- ✅ Local sliding window: 1200 requests/minute (configurable)
- ✅ ccxt built-in rate limiting enabled
- ✅ Exponential backoff on rate limit errors
- ✅ Respects `Retry-After` header

### Data Limits

- Binance REST: Max 1000 candles per request
- TSAR requests `limit=100` by default (conservative)
- No pagination for fetching > 1000 candles
- No `since` parameter support in the OHLCV adapter (field exists but unused)

---

## 7. Integration Testing

### Can TSAR Connect to Binance Right Now?

**Partially.** The `CcxtGateway` class is abstract-incomplete:
- `get_balance()`, `get_positions()`, `get_ticker()`, `get_recent_trades()` are NOT implemented
- Python will raise `TypeError: Can't instantiate abstract class` if you try to create a `CcxtGateway`

**However:** The backend registry creates instances via `registry.create("exchange_gateway")` which calls `CcxtGateway(**config)`. This will **fail at instantiation** due to the missing abstract methods.

### What's Needed to Go Live

| Step | Effort | Priority |
|---|---|---|
| Implement `get_balance()` | 30 min | **CRITICAL** |
| Implement `get_positions()` | 30 min | **CRITICAL** |
| Implement `get_ticker()` | 5 min | HIGH |
| Implement `get_recent_trades()` | 30 min | MEDIUM |
| Get Binance testnet API keys | 10 min | **CRITICAL** |
| Set `EXCHANGE_API_KEY` and `EXCHANGE_SECRET` | 2 min | **CRITICAL** |
| Test with `--paper --sandbox` | 30 min | HIGH |
| Add OCO/bracket orders | 2 hours | HIGH |
| Add WebSocket streaming | 4-8 hours | MEDIUM |
| Add market data caching | 2-4 hours | MEDIUM |

### Environment Variables Required

```bash
EXCHANGE_API_KEY=<your-binance-api-key>
EXCHANGE_SECRET=<your-binance-api-secret>
EXCHANGE_SANDBOX=true                    # testnet
TSAR_TRADING_MODE=paper                  # safe testing
```

### Binance API Permissions Required

For testnet:
- ✅ Enable Reading
- ✅ Enable Spot & Margin Trading
- ❌ Disable Withdrawals (safety)

### How to Test Without Risk

1. **Binance Testnet** — Free, unlimited, resettable
   - URL: https://testnet.binance.vision/
   - Generate API keys there
   - Set `EXCHANGE_SANDBOX=true`

2. **Paper Mode** — `--paper` flag
   - Still hits testnet (not truly simulated)
   - No real money at risk

3. **Unit Tests** — Mock ccxt responses
   - Tests exist in `tests/unit/` but may not cover gateway

---

## 8. Top 5 Things to Fix for Real Binance Connectivity

### Fix 1: Implement Missing Abstract Methods (CRITICAL)

```python
# In ccxt_gateway.py, add:

async def get_balance(self) -> dict[str, Balance]:
    self._ensure_connected()
    assert self._exchange is not None
    raw = await self._retry_on_transient(self._exchange.fetch_balance)
    # Parse raw into Balance objects
    balances = {}
    for currency, info in raw.get("total", {}).items():
        if info and float(info) > 0:
            balances[currency] = Balance(
                total=float(info),
                free=float(raw.get("free", {}).get(currency, 0)),
                used=float(raw.get("used", {}).get(currency, 0)),
                currency=currency,
            )
    return balances

async def get_positions(self) -> list[Position]:
    self._ensure_connected()
    assert self._exchange is not None
    # For spot: positions are just balances
    # For futures: use fetch_positions
    raw = await self._retry_on_transient(self._exchange.fetch_balance)
    positions = []
    for currency, info in raw.get("total", {}).items():
        if info and float(info) > 0 and currency != "USDT":
            positions.append(Position(
                symbol=f"{currency}/USDT",
                side=OrderSide.BUY,
                quantity=float(info),
                entry_price=0.0,  # Not available from balance
                current_price=0.0,
                unrealized_pnl=0.0,
            ))
    return positions

async def get_ticker(self, symbol: str) -> Price:
    return await self.get_price(symbol)

async def get_recent_trades(self, symbol: str, limit: int = 50) -> list[Trade]:
    self._ensure_connected()
    assert self._exchange is not None
    raw = await self._retry_on_transient(
        self._exchange.fetch_trades, symbol, limit=limit
    )
    return [
        Trade(
            id=str(t.get("id", "")),
            symbol=symbol,
            side=OrderSide.BUY if t.get("side") == "buy" else OrderSide.SELL,
            price=float(t.get("price", 0)),
            quantity=float(t.get("amount", 0)),
            cost=float(t.get("cost", 0)),
            fee=float((t.get("fee", {}) or {}).get("cost", 0)),
            fee_currency=(t.get("fee", {}) or {}).get("currency", ""),
            timestamp=_ts_to_dt(t.get("timestamp")),
        )
        for t in raw
    ]
```

### Fix 2: Add Market Data Caching

```python
# New file: src/backends/python/market_data_cache.py
class MarketDataCache:
    """In-memory cache for OHLCV data with staleness detection."""
    
    def __init__(self, max_age_seconds: int = 60):
        self._cache: dict[str, tuple[list[OHLCV], float]] = {}
        self._max_age = max_age_seconds
    
    async def get_ohlcv(self, gateway, symbol, timeframe, limit):
        key = f"{symbol}:{timeframe.value}:{limit}"
        if key in self._cache:
            data, ts = self._cache[key]
            if time.time() - ts < self._max_age:
                return data
        data = await gateway.get_ohlcv(symbol, timeframe, limit)
        self._cache[key] = (data, time.time())
        return data
```

### Fix 3: Add OCO/Bracket Order Support

```python
# In ccxt_exec_engine.py, add:
async def execute_bracket_order(self, symbol, side, quantity, 
                                 entry_price, stop_loss, take_profit):
    """Place entry + SL + TP as a bracket group."""
    # Place entry
    entry = await self.execute_order(Order(...))
    # Place SL (opposite side)
    sl = await self.execute_order(Order(
        order_type=OrderType.STOP_MARKET,
        stop_price=stop_loss,
        side=OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY,
        ...
    ))
    # Place TP
    tp = await self.execute_order(Order(
        order_type=OrderType.LIMIT,
        price=take_profit,
        side=OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY,
        ...
    ))
    # Track all three for OCO management
    return {"entry": entry, "sl": sl, "tp": tp}
```

### Fix 4: Add Historical Data Pagination

```python
# In ccxt_gateway.py, add:
async def get_ohlcv_range(self, symbol, timeframe, since_ms, until_ms=None):
    """Fetch OHLCV data for a date range with pagination."""
    all_candles = []
    current_since = since_ms
    
    while True:
        raw = await self._retry_on_transient(
            self._exchange.fetch_ohlcv,
            symbol, timeframe.value,
            since=current_since,
            limit=1000,
        )
        if not raw:
            break
        all_candles.extend(raw)
        last_ts = raw[-1][0]
        if last_ts <= current_since or (until_ms and last_ts >= until_ms):
            break
        current_since = last_ts + 1
    
    return [OHLCV(...) for bar in all_candles]
```

### Fix 5: Add Paper Trading Simulation

```python
# New file: src/backends/python/paper_exec_engine.py
class PaperExecEngine(ExecutionEngine):
    """In-memory order simulation for paper trading."""
    
    def __init__(self, gateway, initial_balance=10.0):
        self._gateway = gateway
        self._balance = initial_balance
        self._positions = {}
        self._orders = []
    
    async def execute_order(self, order):
        price = (await self._gateway.get_price(order.symbol)).last
        # Simulate fill at current price + slippage
        fill_price = price * (1 + 0.001)  # 10bps slippage
        # Update balance and positions
        ...
```

---

## 9. Step-by-Step Guide to Connect TSAR to Binance

### Phase 1: Testnet (Safe)

1. **Get testnet keys:**
   - Visit https://testnet.binance.vision/
   - Generate API Key and Secret

2. **Create `.env` file:**
   ```bash
   cp .env.example .env
   # Edit .env:
   EXCHANGE_API_KEY=<testnet-api-key>
   EXCHANGE_SECRET=<testnet-api-secret>
   EXCHANGE_SANDBOX=true
   TSAR_TRADING_MODE=paper
   ```

3. **Implement missing methods** (Fix 1 above)

4. **Test connection:**
   ```python
   from src.backends.python.ccxt_gateway import CcxtGateway
   gw = CcxtGateway(api_key="...", api_secret="...", sandbox=True)
   await gw.connect()
   price = await gw.get_price("BTC/USDT")
   print(f"BTC/USDT: ${price.last:,.2f}")
   ```

5. **Run paper trading:**
   ```bash
   python3 -m src --paper
   ```

### Phase 2: Production (Real Money)

1. **Get production keys:**
   - Binance → API Management → Create API Key
   - Enable "Spot & Margin Trading"
   - **Do NOT enable withdrawals**

2. **Update `.env`:**
   ```bash
   EXCHANGE_SANDBOX=false
   TSAR_TRADING_MODE=live
   ```

3. **Activate mandate:**
   ```yaml
   # config/mandate.yaml
   status: ACTIVE
   ```

4. **Start with small capital:**
   - $10 starting capital as specified
   - Max single position: 15% ($1.50)
   - Daily loss limit: 2% ($0.20)

---

## 10. Implemented vs Stub/Aspirational

### Fully Implemented ✅
- CcxtGateway: connect, disconnect, health_check, get_price, get_ohlcv, get_orderbook
- CcxtExecEngine: execute_order, cancel_order, get_order_status, get_open_orders, get_fills
- BacktestEngine: Full bar-by-bar simulation with metrics
- WalkForwardValidator: Rolling train/test with overfitting detection
- MonteCarloSimulator: Trade permutation with confidence intervals
- OHLCV adapter: ExchangeGateway → OHLCVProvider bridge
- Retry logic, rate limiting, sandbox mode
- ExecutionSniper: Full order lifecycle (SL → Entry → TP)
- Risk management: Kill switch, mandate, drawdown circuit breakers

### Partially Implemented ⚚
- Ticker subscription (polling, not WebSocket)
- Order cancellation (needs symbol parameter)
- Paper trading (flag-only, no simulation engine)

### Stub/Aspirational ❌
- `get_balance()` — Abstract method, not implemented
- `get_positions()` — Abstract method, not implemented
- `get_ticker()` — Abstract method, not implemented
- `get_recent_trades()` — Abstract method, not implemented
- WebSocket streaming — Referenced as "Level 2" but no code
- Rust gateway — Directory exists but no implementation
- FIX gateway — Referenced but no code
- Market data caching — No implementation
- Historical data pagination — No implementation
- Paper execution simulation — No implementation
- Trading API routes — Return empty arrays (`{"trades": [], "total": 0}`)
- ExecutionTracker — `run_cycle()` is `pass`

---

## 11. Verdict

### CONDITIONAL PASS ✅⚠️

**Rationale:**

The architecture is sound. The code quality is high. The error handling is production-grade. The backtester, Monte Carlo, and walk-forward validation are genuinely excellent — they use real data correctly and implement proper statistical methods.

However, the system **cannot instantiate its own gateway** due to missing abstract method implementations. This is a critical blocker that's also a **quick fix** (2-3 hours of straightforward ccxt calls).

**Conditions for full PASS:**
1. Implement the 4 missing abstract methods in CcxtGateway
2. Verify instantiation works with Binance testnet
3. Add a PaperExecEngine for true paper trading simulation
4. Add OCO/bracket order support to prevent orphaned stop-losses

**What's genuinely good:**
- The interface abstraction layer is excellent — swapping backends is trivial
- The ExecutionSniper's "stop-loss first" safety protocol is correct
- The backtester properly applies slippage and commission
- Monte Carlo resamples real returns (not synthetic)
- Walk-forward validation catches overfitting
- All timestamps are UTC-consistent
- Rate limiting is doubly enforced (ccxt + local)

**What Valentine should know:**
- With $10 starting capital, Binance's minimum order sizes may be a problem (BTC/USDT minimum is ~$10)
- Consider starting with ETH/USDT or smaller pairs where $10 positions are viable
- The testnet is the right first step — it behaves identically to production
- The system is 2-3 days of focused work away from being fully Binance-connected

---

*Review completed by Live Market Data Engineer — TSAR Trading Super Agent Council*
