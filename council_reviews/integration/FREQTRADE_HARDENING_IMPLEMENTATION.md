# Freqtrade Exchange Hardening — TSAR Integration

**Council**: Freqtrade Exchange Hardening  
**Date**: 2026-07-30  
**Status**: IMPLEMENTED  
**Source**: `freqtrade/exchange/exchange.py`, `freqtrade/exchange/common.py`, `freqtrade/exchange/exchange_utils.py`

---

## Executive Summary

Extracted and integrated four exchange hardening patterns from Freqtrade into TSAR's ccxt-based exchange layer. These patterns address production reliability issues that Freqtrade has battle-tested across 15+ exchanges over years of live trading.

## Patterns Extracted & Integrated

### 1. Retry Logic — Quadratic Backoff

**Source**: `freqtrade/exchange/common.py` — `retrier()`, `retrier_async()`, `calculate_backoff()`

**Freqtrade Pattern**:
```python
def calculate_backoff(retrycount, max_retries):
    return (max_retries - retrycount) ** 2 + 1
```
Produces delays: retry4→2s, retry3→5s, retry2→10s, retry1→17s  
Default: 4 retries (5 total attempts), separate 5 retries for order fetches.

**TSAR Before**: Linear exponential backoff (`2^attempt`, capped at 10s/30s)

**TSAR After**: Quadratic backoff matching Freqtrade's formula. Applied to both rate-limit and network error retries.

**Files Modified**: `src/backends/python/ccxt_gateway.py`

**Changes**:
- Added `_calculate_backoff()` function using Freqtrade's `(max_retries - retrycount)^2 + 1` formula
- Updated `_retry_on_transient()` to use quadratic backoff instead of exponential
- Added `API_RETRY_COUNT = 4` and `API_FETCH_ORDER_RETRY_COUNT = 5` constants

---

### 2. Precision Handling — Decimal Place Enforcement

**Source**: `freqtrade/exchange/exchange_utils.py` — `amount_to_precision()`, `price_to_precision()`

**Freqtrade Pattern**:
- Uses ccxt's `decimal_to_precision()` with `TRUNCATE` mode for amounts
- Supports all three ccxt precision modes: `DECIMAL_PLACES`, `SIGNIFICANT_DIGITS`, `TICK_SIZE`
- Special handling for `ROUND_UP`/`ROUND_DOWN` in `TICK_SIZE` mode using `Decimal` arithmetic
- Gets precision values from `market['precision']['amount']` and `market['precision']['price']`

**TSAR Before**: No precision handling — raw float values sent to exchange, risking rejections.

**TSAR After**: Full precision enforcement at both gateway and execution engine layers.

**Files Modified**: `src/backends/python/ccxt_gateway.py`, `src/backends/python/ccxt_exec_engine.py`

**Changes**:
- Added `_amount_to_precision()` and `_price_to_precision()` standalone functions (gateway)
- Added `get_precision_amount()`, `get_precision_price()`, `amount_to_precision()`, `price_to_precision()` methods to `CcxtGateway`
- Added `precision_mode` property to `CcxtGateway`
- Added `_apply_precision()` method to `CcxtExecEngine` — auto-adjusts amount/price/stop_price before order placement
- Imported ccxt precision constants: `DECIMAL_PLACES`, `ROUND`, `ROUND_DOWN`, `ROUND_UP`, `SIGNIFICANT_DIGITS`, `TICK_SIZE`, `TRUNCATE`, `decimal_to_precision`

---

### 3. Rate Limiting — Layered Defense

**Source**: `freqtrade/exchange/common.py` — ccxt built-in + DDoS protection retry

**Freqtrade Pattern**:
- Relies on ccxt's built-in `enableRateLimit=True`
- Wraps all exchange calls in `retrier`/`retrier_async` decorators
- DDoS protection errors trigger quadratic backoff
- Special KuCoin 429 handling (avoids triggering backoff for known false positives)

**TSAR Before**: Basic sliding window counter (`_enforce_rate_limit`) + ccxt `enableRateLimit=True`

**TSAR After**: Same layered approach, but now with Freqtrade's quadratic backoff on rate limit errors (instead of exponential). The existing sliding window + ccxt built-in provides good defense-in-depth.

**Files Modified**: `src/backends/python/ccxt_gateway.py`

**Changes**:
- Rate limit retries now use `_calculate_backoff()` quadratic formula
- Better logging: distinguishes rate limit vs network errors in retry messages

---

### 4. Order Validation — Exchange Limits

**Source**: `freqtrade/exchange/exchange.py` — `get_min_pair_stake_amount()`, `_get_stake_amount_limit()`, `create_order()`

**Freqtrade Pattern**:
- Before placing any order, checks `market['limits']['amount']['min']` and `market['limits']['cost']['min']`
- Applies amount precision via `amount_to_precision(pair, amount)` before sending
- Applies price precision via `price_to_precision(pair, rate)` before sending
- Raises `InvalidOrderException` for insufficient amounts

**TSAR Before**: Basic validation (positive quantity, valid symbol format). No exchange limit checks. No precision adjustment.

**TSAR After**: Three-layer validation:

1. **Basic validation** (unchanged): quantity > 0, valid symbol, price required for limit orders
2. **Exchange limits** (new): min/max amount, min/max cost from market data
3. **Precision adjustment** (new): auto-truncate amount and round price before placement

**Files Modified**: `src/backends/python/ccxt_exec_engine.py`, `src/tools/execution.py`

**Changes to `ccxt_exec_engine.py`**:
- Enhanced `_validate_order()` to call `_validate_exchange_limits()` when markets are loaded
- Added `_validate_exchange_limits()` — checks min/max amount and cost from `market['limits']`
- Added `_apply_precision()` — creates new Order with precision-adjusted values
- `execute_order()` now calls `_apply_precision()` after validation, before placement

**Changes to `src/tools/execution.py`**:
- `_place_order()` now calls `gateway.validate_order_limits()` before building Order
- `_place_order()` applies `gateway.amount_to_precision()` and `gateway.price_to_precision()` before passing to engine

---

## Architecture: Defense in Depth

The hardening is applied at three layers:

```
┌─────────────────────────────────────────────────┐
│  Tool Layer (execution.py)                       │
│  - Pre-flight: validate_order_limits()           │
│  - Pre-flight: amount_to_precision()             │
│  - Pre-flight: price_to_precision()              │
├─────────────────────────────────────────────────┤
│  Engine Layer (ccxt_exec_engine.py)              │
│  - _validate_order(): basic params               │
│  - _validate_exchange_limits(): min/max checks   │
│  - _apply_precision(): decimal enforcement        │
├─────────────────────────────────────────────────┤
│  Gateway Layer (ccxt_gateway.py)                 │
│  - _retry_on_transient(): quadratic backoff      │
│  - _enforce_rate_limit(): sliding window          │
│  - ccxt enableRateLimit: built-in rate limiter   │
│  - amount_to_precision(): precision helpers       │
│  - price_to_precision(): precision helpers        │
│  - validate_order_limits(): limit checks          │
└─────────────────────────────────────────────────┘
```

Each layer catches different failure modes:
- **Tool layer**: Catches issues early with user-friendly error messages
- **Engine layer**: Catches issues at order construction time
- **Gateway layer**: Catches issues at API call time with retry

---

## New Public API

### CcxtGateway additions:

```python
# Precision
gateway.get_precision_amount(symbol: str) -> float | None
gateway.get_precision_price(symbol: str) -> float | None
gateway.precision_mode -> int | None
gateway.amount_to_precision(symbol: str, amount: float) -> float
gateway.price_to_precision(symbol: str, price: float, *, rounding_mode=ROUND) -> float

# Market limits
gateway.get_market_limits(symbol: str) -> dict[str, Any]
gateway.validate_order_limits(symbol: str, side: str, amount: float, price: float | None) -> tuple[bool, str]
```

### CcxtExecEngine additions:

```python
engine._validate_exchange_limits(order: Order) -> None  # raises ValueError
engine._apply_precision(order: Order) -> Order  # returns new Order
```

### Standalone functions (ccxt_gateway.py):

```python
_calculate_backoff(retrycount: int, max_retries: int) -> float
_amount_to_precision(amount: float, amount_precision: float | None, precision_mode: int | None) -> float
_price_to_precision(price: float, price_precision: float | None, precision_mode: int | None, *, rounding_mode=ROUND) -> float
```

---

## Testing Recommendations

### Unit Tests
1. **Backoff calculation**: Verify `_calculate_backoff(4, 4)` → 1, `_calculate_backoff(0, 4)` → 17
2. **Amount precision**: Test with DECIMAL_PLACES (2), SIGNIFICANT_DIGITS (4), TICK_SIZE (0.01)
3. **Price precision**: Test ROUND_UP/ROUND_DOWN for stoploss scenarios
4. **Order limits**: Mock market data with limits, verify rejection for below-min orders
5. **Precision adjustment**: Verify `_apply_precision()` creates correct Order

### Integration Tests (Binance Sandbox)
1. Place limit order with too many decimal places → verify auto-truncation
2. Place order below minimum cost → verify rejection with clear message
3. Trigger rate limit → verify quadratic backoff delays
4. Place order with exact minimum amount → verify acceptance

---

## Files Modified Summary

| File | Lines Changed | What |
|------|--------------|------|
| `src/backends/python/ccxt_gateway.py` | ~120 added | Retry backoff, precision functions, market limits, gateway methods |
| `src/backends/python/ccxt_exec_engine.py` | ~110 added | Exchange limit validation, precision application |
| `src/tools/execution.py` | ~25 added | Pre-flight limit checks and precision in `_place_order()` |

## Constants Added

| Constant | Value | Source |
|----------|-------|--------|
| `API_RETRY_COUNT` | 4 | `freqtrade/exchange/common.py` |
| `API_FETCH_ORDER_RETRY_COUNT` | 5 | `freqtrade/exchange/common.py` |

---

## What Was NOT Integrated (and Why)

1. **Dry-run order simulation**: TSAR has `PaperExecutionEngine` for this — separate concern
2. **Exchange-specific subclasses** (Binance, Bybit, etc.): TSAR uses ccxt directly; exchange-specific quirks handled by ccxt
3. **Contract size handling**: TSAR focuses on spot trading; futures contract conversion not needed yet
4. **Leverage preparation** (`_lev_prep`): Not applicable to current TSAR scope
5. **Stoploss on exchange**: TSAR already has bracket/OCO order support in `ccxt_exec_engine.py`

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Precision rounding changes order amounts | `_apply_precision()` logged at DEBUG; original values preserved in Order construction |
| Market data not loaded → limits not checked | Validation skipped gracefully when `self._markets_loaded` is False |
| Quadratic backoff too aggressive | Same formula used in production Freqtrade for years; max delay ~17s |
| TICK_SIZE precision edge cases | Uses Python `Decimal` arithmetic (same as Freqtrade) to avoid float errors |
