# Core Wiring Team — Fix Summary

## Changes Made

### C-008: `get_trade_stats()` in TradeMemory ✅
**File:** `src/knowledge/trade_memory.py`

Implemented `get_trade_stats()` method and helper `_compute_max_drawdown()`:

- **`get_trade_stats(strategy_id, since)`** — Queries closed trades and computes:
  - `win_rate` — fraction of winning trades
  - `total_pnl` — sum of all realized P&L
  - `avg_win` — average P&L of winning trades
  - `avg_loss` — average P&L of losing trades
  - `profit_factor` — gross_profit / gross_loss (∞ if no losses)
  - `max_drawdown` — peak-to-trough from cumulative P&L curve
  - `trade_count` — total closed trades

- **`_compute_max_drawdown(strategy_id, since)`** — Walks the cumulative P&L series chronologically, tracking peak and max drawdown.

Both methods support optional `strategy_id` and `since` filters.

---

### C-024: CcxtGateway Missing Abstract Methods ✅
**File:** `src/backends/python/ccxt_gateway.py`

Implemented all 4 missing abstract methods from `ExchangeGateway`:

- **`get_balance()`** — Calls `exchange.fetch_balance()`, builds `Balance` objects with per-currency breakdown.
- **`get_positions()`** — Calls `exchange.fetch_positions()`, maps ccxt position data to `Position` dataclass (handles long/short side, leverage, liquidation price).
- **`get_ticker(symbol)`** — Delegates to `get_price(symbol)` (alias as specified in interface).
- **`get_recent_trades(symbol, limit)`** — Calls `exchange.fetch_trades()`, maps to `Trade` dataclass with side, price, quantity, fee info.

Added required imports: `Balance`, `OrderSide`, `Position`, `Trade`.

---

### C-022: `cancel_order()` Symbol=None Bug ✅
**File:** `src/backends/python/ccxt_exec_engine.py`

Fixed `cancel_order(order_id)` which was calling `exchange.cancel_order(order_id, symbol=None)`:

- Changed signature to `cancel_order(order_id, symbol=None)` to accept optional symbol.
- When `symbol` is None, attempts to discover it via `exchange.fetch_order()`.
- If symbol cannot be determined, logs warning and returns `False` instead of crashing.
- Passes discovered symbol to `exchange.cancel_order(order_id, symbol=symbol)`.

Also added `cancel_order(order_id, symbol)` to `CcxtGateway` with proper symbol requirement.

---

### C-026: API Routes Return Empty Arrays ✅
**Files:** `src/api/routes/trading.py`, `src/api/routes/portfolio.py`

Wired all API routes to real data sources:

**trading.py:**
- `GET /trades` → Queries `TradeMemory.list_trades()`, returns trade dicts + total count
- `GET /strategies` → Queries `TradeMemory.get_strategy_summary()`, returns per-strategy stats

**portfolio.py:**
- `GET /positions` → Queries `TradeMemory.get_open_positions()`, returns position details
- `GET /pnl` → Queries `TradeMemory.get_trade_stats()`, returns full P&L breakdown
- `GET /risk` → Combines `KillSwitch.is_active()` + `TradeMemory.get_trade_stats()` for drawdown/level
- `GET /improvement` → Returns strategy summaries + regime performance from TradeMemory
- `GET /regime` → Queries `TradeMemory.get_performance_by_regime()` for dominant regime

---

### C-027: `ExecutionTracker.run_cycle()` is pass ✅
**File:** `src/agents/execution_tracker.py`

Implemented full `run_cycle()` with 3 sub-tasks (runs every 5 minutes):

1. **`_reconcile_positions()`** — Fetches exchange positions via gateway + local positions from TradeMemory, compares per-symbol quantities, publishes `tsar.position.mismatch.v1` event on any discrepancy.

2. **`_analyze_fill_quality()`** — Reviews last 20 closed trades for:
   - Slippage > 50 bps → CRITICAL alert logged + tracked
   - Slippage > 10 bps → WARNING logged
   - Latency > 5000ms → WARNING logged
   - Maintains fill quality log (last 100 entries)

3. **`_check_stale_orders()`** — Flags OPEN trades that have been open > 1 hour.

---

### M-053: Telegram Bot Commands Wired to Real Systems ✅
**File:** `src/bot/commands.py`

Replaced all hardcoded responses with real subsystem calls:

- **`/status`** → Queries `KillSwitch.is_active()`, `TradeMemory.get_trade_count()`, `get_open_positions()`, `get_trade_stats()` for live system status.
- **`/pnl`** → Calls `TradeMemory.get_trade_stats()`, formats full P&L breakdown (win rate, avg win/loss, profit factor, max drawdown).
- **`/positions`** → Calls `TradeMemory.get_open_positions()`, lists up to 10 positions with side, quantity, entry price.
- **`/risk`** → Combines `KillSwitch.is_active()` + drawdown stats to show risk level (GREEN/YELLOW/ORANGE/RED).
- **`/start`** → Calls `KillSwitch.deactivate()` instead of just returning text.
- **`/regime`** → Queries `TradeMemory.get_performance_by_regime()` for regime performance data.

Added helper functions: `_handle_status()`, `_handle_pnl()`, `_handle_positions()`, `_handle_risk()`, `_handle_regime()`.

---

## Files Modified

| File | Issues Fixed |
|------|-------------|
| `src/knowledge/trade_memory.py` | C-008 |
| `src/backends/python/ccxt_gateway.py` | C-024, C-022 |
| `src/backends/python/ccxt_exec_engine.py` | C-022 |
| `src/api/routes/trading.py` | C-026 |
| `src/api/routes/portfolio.py` | C-026 |
| `src/agents/execution_tracker.py` | C-027 |
| `src/bot/commands.py` | M-053 |

## Design Decisions

1. **Minimal changes** — Each fix targets the specific issue without refactoring surrounding code.
2. **Existing patterns preserved** — All new code follows the project's async patterns, logging conventions, and dataclass usage.
3. **Error handling** — All new methods have try/except with graceful fallbacks (empty lists, zero values, warning logs).
4. **No breaking changes** — All existing method signatures and return types are preserved.
5. **Database path** — API routes and bot commands use `TSAR_DB_PATH` env var with `./data/tsar.db` default, matching existing config patterns.
