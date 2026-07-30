# Market Connectivity Team — Fix Summary

**Team:** Market Connectivity  
**Date:** 2026-07-30  
**Issues Addressed:** C-021, C-023, C-025, H-019, H-020, H-021

---

## C-021: OANDA/MT5 Does Not Exist

**File:** `README.md`

**Problem:** README listed OANDA/MT5 as active markets (Gold, Forex) despite no integration existing.

**Fix:**
- Removed OANDA/MT5 references from the Markets section
- Added a "Coming Soon" table with honest status markers (🚧 Planned)
- Included Binance Futures and Deribit as future roadmap items
- Added explicit note: "OANDA/MT5 integration is on the roadmap but not yet built"

---

## C-023 / H-019: No WebSocket Streaming

**File:** `src/backends/python/ccxt_gateway.py`

**Problem:** Only polling-based ticker updates (Day1). No real-time WebSocket streaming.

**Fix:**
- Added `aiohttp` WebSocket client for Binance streaming API
- New method: `subscribe_ticker_ws(symbol, callback)` — connects to `wss://stream.binance.com:9443/ws/<symbol>@ticker`
- Parses real-time JSON ticker messages (`c`=last, `b`=bid, `a`=ask)
- Automatic reconnection with exponential backoff (1s → 60s max)
- Heartbeat keep-alive (30s)
- Integrates with cache: each WS tick updates the Redis/in-memory cache
- Existing polling-based `subscribe_ticker()` preserved as fallback
- Proper cleanup: `_unsubscribe_ws_ticker()` cancels WS tasks on disconnect
- `disconnect()` now closes aiohttp session and all WS subscriptions

**Usage:**
```python
await gateway.subscribe_ticker_ws("BTC/USDT", my_callback)
```

---

## C-025: No Paper Execution Engine

**File:** `src/backends/python/paper_execution_engine.py` (NEW)

**Problem:** No paper trading engine. Testing required real exchange API calls.

**Fix — Full paper execution engine with:**
- Implements `ExecutionEngine` interface (same contract as `CcxtExecEngine`)
- **No real API calls** — all fills simulated locally against live price data from `ExchangeGateway`
- **Realistic fee simulation:** configurable fee rate (default 10 bps = 0.1%, matching Binance spot)
- **Slippage simulation:** random jitter ±50%, market orders get 1.5x base slippage, size impact scaling
- **Virtual portfolio tracking:** per-asset balance, position tracking with average entry price
- **Full order validation:** same checks as real engine (quantity, price, symbol format)
- **All order types:** market, limit, stop_market, stop_limit
- **Portfolio queries:** `balances`, `positions`, `total_equity`, `order_history`
- **Slippage analytics:** `avg_slippage_bps`, `slippage_history`

**Usage:**
```python
engine = PaperExecutionEngine(
    gateway=gateway,
    initial_balance=10_000.0,
    fee_rate_bps=10.0,  # 0.1%
    slippage_bps=2.0,
)
await engine.connect()
result = await engine.execute_order(order)
```

---

## H-020: No Market Data Caching

**File:** `src/backends/python/ccxt_gateway.py`

**Problem:** Every `get_price()`, `get_ohlcv()`, `get_orderbook()` call hit the exchange API directly.

**Fix:**
- New class: `MarketDataCache` — Redis-based cache with in-memory fallback
- **Redis integration:** uses `redis.asyncio` (aioredis) with JSON serialization
- **In-memory fallback:** if Redis unavailable, uses bounded dict (max 500 entries) with TTL expiry
- **Per-data-type TTL:**
  - Ticker/Price: 2 seconds (near real-time)
  - OHLCV: 30 seconds (candles change slowly)
  - Order Book: 5 seconds (moderate freshness)
- `get_price()` → checks cache first, updates cache on miss
- `get_ohlcv()` → checks cache first, updates cache on miss
- `get_orderbook()` → checks cache first, updates cache on miss
- Automatic stale entry pruning in memory cache
- Graceful degradation: cache failures never block market data retrieval

**Configuration:**
```yaml
redis_url: "redis://localhost:6379/0"  # default
```

---

## H-021: No OCO/Bracket Orders

**File:** `src/backends/python/ccxt_exec_engine.py`

**Problem:** No support for linked stop-loss + take-profit orders.

**Fix — Two new order types:**

### 1. Bracket Orders (`execute_bracket_order`)
- Places 3 linked orders: entry + stop-loss + take-profit
- Stop-loss is `STOP_MARKET`, take-profit is `LIMIT`
- Background monitor polls order status every 2 seconds
- When one exit fills → automatically cancels the other
- If entry or exit placement fails → rolls back all placed orders
- 24-hour monitor timeout with cleanup

### 2. OCO Orders (`execute_oco_order`)
- Uses Binance native OCO endpoint when available (`type=OCO`)
- Falls back to two linked limit orders + monitor if native OCO fails
- Same One-Cancels-Other semantics

### Supporting Infrastructure
- `BracketOrder` dataclass: tracks bracket_id, linked order IDs, status, prices
- `cancel_bracket_order(bracket_id)`: cancels all orders in a bracket, stops monitor
- `get_bracket_status(bracket_id)`: returns current BracketOrder state
- Instance tracking: `_bracket_orders` dict, `_bracket_monitor_tasks` dict

**Usage:**
```python
bracket = await exec_engine.execute_bracket_order(
    symbol="BTC/USDT",
    side=OrderSide.BUY,
    quantity=0.01,
    entry_price=65000.0,
    stop_loss_price=63000.0,
    take_profit_price=70000.0,
)
# Background monitor handles cancellation automatically

oco = await exec_engine.execute_oco_order(
    symbol="BTC/USDT",
    side=OrderSide.SELL,
    quantity=0.01,
    stop_loss_price=63000.0,
    take_profit_price=70000.0,
)
```

---

## Files Modified

| File | Changes |
|------|---------|
| `README.md` | Removed OANDA/MT5, added Coming Soon section |
| `src/backends/python/ccxt_gateway.py` | +WebSocket streaming (aiohttp), +Redis market data cache (MarketDataCache class) |
| `src/backends/python/ccxt_exec_engine.py` | +OCO/Bracket order support (BracketOrder, execute_bracket_order, execute_oco_order) |
| `src/backends/python/paper_execution_engine.py` | **NEW** — Full paper execution engine |

## Dependencies Added

| Package | Purpose |
|---------|---------|
| `aiohttp` | WebSocket client for Binance streaming |
| `redis[async]` (optional) | Market data cache backend |

## Testing Notes

- All files pass Python AST parsing (syntax verified)
- `MarketDataCache` gracefully degrades to in-memory when Redis is unavailable
- `PaperExecutionEngine` requires no external services (uses gateway for prices only)
- Bracket order monitor runs as background asyncio task with proper cancellation
- WebSocket reconnection uses exponential backoff to avoid hammering the exchange
