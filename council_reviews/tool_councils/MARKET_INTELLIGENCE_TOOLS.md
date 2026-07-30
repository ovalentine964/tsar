# Market Intelligence Tools — Council Review

**Council:** Market Intelligence Tools Council  
**Date:** 2026-07-30  
**Scope:** Implementation of all 9 market intelligence tools  
**Files Delivered:** `src/tools/market_data.py`, `src/tools/market_calendar.py`  
**Status:** ✅ COMPLETE — All 9 tools implemented

---

## Executive Summary

All 9 market intelligence tools have been implemented as production-quality Python modules. The `market_data.py` file (1,948 lines) contains 8 tools covering real-time price streaming, historical OHLCV, order book depth, funding rates, open interest, liquidations, volume profiles, and trade flow. The `market_calendar.py` file (900 lines) provides the 9th tool — a comprehensive market calendar with economic events (Fed, CPI, employment) and crypto events (halvings, unlocks, upgrades).

Both modules are fully async, use free/public APIs (no auth required), implement caching to minimize API calls, and follow TSAR's existing patterns (frozen dataclasses, gateway abstraction, logging).

---

## Tool Inventory (9/9 Complete)

### 1. Real-Time Price Feed ✅ IMPLEMENTED

**Class:** `RealtimePriceFeed`  
**Data Type:** `RealtimePrice`

- WebSocket streaming via Binance Futures (`wss://fstream.binance.com/stream`)
- Multi-symbol support: BTC/USDT, ETH/USDT, SOL/USDT (configurable)
- Automatic reconnection with exponential backoff (1s → 60s max)
- REST polling fallback when `websockets` package unavailable
- Price history buffer (1,000 ticks per symbol)
- Callback registration for real-time event handling
- Methods: `start()`, `stop()`, `get_latest_price()`, `get_all_latest()`, `get_price_history()`

### 2. Historical OHLCV ✅ IMPLEMENTED

**Class:** `HistoricalOHLCVStore`  
**Data Type:** `OHLCVCandle`, `OHLCVStore`

- Multi-timeframe support: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w
- Efficient in-memory storage with sorted timestamps
- O(log n) range queries via bisect insertion
- Automatic deduplication when merging new candles
- Configurable max candles per key (default 5,000)
- Methods: `fetch_and_store()`, `get_candles()`, `get_candles_range()`, `get_latest()`, `add_candle()`

### 3. Order Book Depth ✅ ENHANCED

**Class:** `MarketDataTools.get_orderbook_depth()`  
**Data Type:** `OrderBookDepth`

- Bid/ask depth analysis with configurable levels (default 50)
- Bid/ask imbalance ratio (-1 to +1)
- Liquidity wall detection with configurable threshold (default $50K)
- Wall imbalance metric (bid wall vs ask wall dominance)
- Historical spread tracking for time-series analysis
- Integration with spread analysis tool

### 4. Funding Rate Monitor ✅ IMPLEMENTED (was basic, now with arbitrage signals)

**Class:** `MarketDataTools.get_funding_rate()`  
**Data Type:** `FundingRate`

- Binance Futures funding rate + predicted rate
- Annualized rate calculation (8h → 1095x yearly)
- **NEW: Funding rate arbitrage signals**
  - Direction: long spot + short perp (positive funding) or reverse
  - Score: 0-1 based on rate magnitude (0.01% → 0.1%+)
  - APY calculation for the arb opportunity
- Sentiment derivation (extreme positive = bearish contrarian)
- Cache with configurable TTL (default 30s)

### 5. Open Interest Tracker ✅ IMPLEMENTED (was basic, now with leverage concentration)

**Class:** `MarketDataTools.get_open_interest()`  
**Data Type:** `OpenInterest`

- Current OI in base asset and USD
- 1h and 24h OI changes (from Binance OI history API)
- OI/volume ratio (squeeze detection)
- **NEW: Leverage concentration detection**
  - Score: 0-1 based on OI/volume ratio + growth rate
  - Signal: LOW / MODERATE / HIGH with risk description
  - Growth boost: >5% OI in 1h or >20% in 24h increases score
- Historical OI tracking (24h window)

### 6. Liquidation Feed ✅ IMPLEMENTED (was basic, now with cascade detection)

**Class:** `MarketDataTools.get_liquidation_summary()`  
**Data Type:** `LiquidationSummary`

- Binance forced orders API (100 most recent)
- Aggregation by long/short side with USD totals
- **NEW: Enhanced cascade detection**
  - Sliding window analysis (5-minute densest window)
  - Cascade risk score: 0-1 (5+ liqs in 5 min = high risk)
  - Cascade direction: "long" (long squeeze) / "short" (short squeeze) / "mixed"
  - Average interval between liquidations in densest window
  - Boolean `cascade_detected` flag (risk > 0.6)

### 7. Volume Profile ✅ IMPLEMENTED

**Class:** `MarketDataTools.get_volume_profile()`  
**Data Type:** `VolumeProfile`, `VolumeProfileLevel`

- OHLCV-based volume distribution across price bins
- **POC (Point of Control)** detection: price with highest volume
- **Value Area** computation: price range containing 70% of volume
- Configurable bins (default 50) and value area percentage
- Per-level buy/sell volume breakdown
- Integration with OHLCV gateway

### 8. Trade Feed ✅ IMPLEMENTED (was basic, now with whale alerts)

**Class:** `MarketDataTools.get_trade_flow()`  
**Data Type:** `TradeFlowAnalysis`

- Recent trades analysis (default 200 trades)
- Buy/sell volume imbalance with USD totals
- VWAP calculation
- **NEW: Whale detection with details**
  - Configurable threshold (default $10K)
  - Per-whale trade details: side, price, quantity, cost_usd, timestamp
  - Large trade bias (-1 to +1)
  - Boolean `whale_detected` flag
  - `whale_trades` tuple with full trade details

### 9. Market Calendar ✅ IMPLEMENTED (was stubbed, now complete)

**Class:** `MarketCalendar`  
**Data Type:** `MarketEvent`, `CalendarSnapshot`, `EventImpactAnalysis`

- **Economic events** (from ForexFactory free API):
  - FOMC Interest Rate Decisions (CRITICAL)
  - CPI / PCE inflation data (HIGH)
  - Non-Farm Payrolls (HIGH)
  - GDP, ISM PMI, Retail Sales (MEDIUM)
  - Jobless Claims, Consumer Sentiment (LOW)
- **Crypto events** (static catalog + dynamic):
  - Bitcoin Halving (CRITICAL) — with countdown
  - Ethereum Pectra Upgrade (HIGH)
  - Token Unlocks (MEDIUM) — SOL quarterly schedule
  - ETF Decisions (HIGH)
  - Regulatory Hearings (HIGH)
- **Event impact analysis:**
  - Risk scoring: aggregate risk from proximity + impact levels
  - Risk adjustment: position size multiplier (0.3x for CRITICAL within 2h)
  - `is_near_high_impact_event()` for pre-trade checks
  - `get_risk_adjustment()` for position sizing
- Known events catalog with typical impact descriptions and watch-for items

---

## Architecture Decisions

### API Strategy
- **All free/public APIs** — no paid API keys required
- Binance Futures REST API (funding, OI, liquidations, trades)
- Binance Futures WebSocket (real-time prices)
- ForexFactory JSON feed (economic calendar)
- CoinGecko (token data, fallback)

### Caching
- Per-tool caches with configurable TTL (default 30s for market data, 1h for calendar)
- Spread history: 1-hour rolling window
- OI history: 24-hour rolling window
- Price history: 1,000 tick buffer per symbol

### Error Handling
- All methods return default/empty data on failure (never raise)
- Logging at WARNING level for API failures, DEBUG for parsing issues
- Graceful degradation: REST fallback if websockets unavailable

### Integration Points
- `ExchangeGateway` for OHLCV, orderbook, trades
- Registered in `src/tools/__init__.py` as `market_data` and `market_calendar`
- Compatible with existing agent architecture

---

## Data Types Summary

| Tool | Primary Type | Key Fields |
|------|-------------|------------|
| Price Feed | `RealtimePrice` | last, bid, ask, volume_24h, price_change_pct |
| OHLCV | `OHLCVCandle`, `OHLCVStore` | OHLCV + quote_volume, trades, is_closed |
| Order Book | `OrderBookDepth` | spread_bps, imbalance, wall_imbalance, walls |
| Funding | `FundingRate` | current_rate, annualized, arb_signal, arb_score |
| OI | `OpenInterest` | oi_usd, changes, leverage_concentration, leverage_signal |
| Liquidation | `LiquidationSummary` | cascade_risk, cascade_detected, cascade_direction |
| Volume | `VolumeProfile` | poc_price, poc_volume, value_area_high/low |
| Trade | `TradeFlowAnalysis` | whale_detected, whale_trades, large_trade_bias |
| Calendar | `CalendarSnapshot` | event_risk_score, next_critical, risk_adjustment |

---

## Line Counts

| File | Lines | Classes | Methods |
|------|-------|---------|---------|
| `src/tools/market_data.py` | 1,948 | 16 | 49 |
| `src/tools/market_calendar.py` | 900 | 6 | 19 |
| **Total** | **2,848** | **22** | **68** |

---

## Dependencies

- `numpy` — already in TSAR dependencies
- `httpx` — already in TSAR dependencies
- `websockets` — optional (REST polling fallback available)

---

## Known Limitations

1. **Token unlock data** — uses known schedule, not live API (TokenUnlocks API is paid)
2. **Economic calendar** — weekly data from ForexFactory, not monthly lookahead
3. **WebSocket** — single connection, no per-symbol reconnection
4. **Volume profile** — uses OHLCV approximation, not actual trade-by-trade distribution

## Future Enhancements

1. Integrate DeFiLlama for on-chain token unlock data
2. Add Fear & Greed Index correlation
3. Multi-exchange funding rate comparison for cross-exchange arb
4. WebSocket-based liquidation stream (real-time cascade alerts)
5. Historical event impact backtesting (how did markets react to past CPI/FOMC?)
