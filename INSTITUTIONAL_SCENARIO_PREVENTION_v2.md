# Institutional Scenario Prevention Council v2 — TSAR

**Institutional Scenario Prevention Council Report v2**
**Date:** 2026-08-01
**Score: 8/10**
**Scope:** 25 scenarios across 4 timeframes — Daily, Weekly, Monthly, Yearly

---

## Executive Summary

TSAR's superagent architecture — deterministic risk harness wrapping an LLM-powered intelligence layer with a self-improving flywheel — provides **multi-layered defense** against 25 institutional-grade failure scenarios organized by timeframe. The system's strength compounds across horizons: daily infrastructure resilience feeds weekly strategy robustness, which enables monthly portfolio integrity, which sustains yearly existential survival. The deterministic kill switch (zero LLM in critical path), dual-write state management, and 7-layer veto protocol form the backbone. Gaps exist primarily in cross-exchange failover, real-time model drift detection, and automated black swan response.

**Key architectural strengths:**
- Deterministic risk governance — zero LLM in kill path
- Dual-write kill switch (file primary, Redis secondary) with fail-safe defaults
- 12-agent superagent architecture with clear separation of concerns
- Self-improving flywheel: TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT
- HMM-based regime detection with rule-based fallback
- Smart order routing (TWAP/VWAP/iceberg) for institutional execution
- Phased recovery protocol after circuit breaker events
- Watchdog process survives main process death

**Key architectural gaps:**
- No cross-exchange failover mechanism
- Real-time model drift detection relies on periodic evaluation
- Black swan response is largely reactive/manual
- No MEV protection in CeFi execution path
- Edge competition/crowding detection absent

---

# DAILY SCENARIOS (7)

---

## D1. Flash Crash

**Timeframe:** Daily (minutes)
**Frequency:** 2-4× per year in crypto, but daily-level severity

### What happens (step by step)
1. Market is calm. BTC at $60,000
2. A large sell order ($50M+ notional) or cascading liquidations dump price
3. Price drops -10% in 2-5 minutes
4. Stop losses cascade: every stop between $60K and $54K triggers sequentially
5. Liquidations cascade: leveraged longs get liquidated, adding selling pressure
6. Exchange matching engine degrades under order flow volume
7. TSAR's stop at $58,800 fills at $55,000 (massive slippage)
8. Price recovers to $59,000 within 15 minutes — the stop was at the bottom

### What it costs
- **Money:** 2-10% slippage beyond stop level. A 2% stop becomes 7-12% loss
- **Time:** Recovery from emotional trauma: 24-72 hours of degraded decision-making
- **Energy:** Psychological: watching stop fill at 5× expected loss is traumatic

### Why it happens
- **Market inefficiency:** Liquidity vacuum — large orders consume all bids in a price range
- **Coordination failure:** Cascading liquidations create positive feedback loops
- **Information asymmetry:** Algorithms see order flow; retail sees only price

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **No Leverage (Day1)** | Leverage = 1.0x. No liquidation risk. TSAR's stop triggers but no forced liquidation |
| **2% Max Stop Loss** | Even with 5× slippage, 2% stop = 10% max loss. On $10 account with $1.50 position = $0.15 |
| **Cascade Detection** (`_detect_cascade()`) | Identifies flash crash conditions in real-time. HALTS new entries until volatility normalizes |
| **Smart Order Router** | During extreme volatility: switches to limit orders with max slippage bounds. Pauses if bound can't be met |
| **Spread Monitoring** | Flash crashes blow out spreads. Spread monitor detects and pauses execution |
| **Drawdown Monitor** | -2% daily loss → ORANGE (halt). -3% → RED (kill switch, flatten all) |
| **Kill Switch** | Nuclear option. All positions flattened, all orders cancelled |
| **Gated Recovery** | After halt: 10% → 25% → 50% → 100% over 24-72 hours |

**TSAR Blueprint Handling:** RiskGuardian is the first responder — its 7-layer veto protocol halts new entries before the cascade reaches TSAR's positions. ExecutionSniper's slippage monitor (>50 bps = ABORT) prevents market orders during the crash. The Watchdog ensures that even if the crash kills the main process (OOM from log storm), the kill switch fires via file-based heartbeat detection.

**Prevention confidence:** 80%

### Gap Analysis
| Capability | Status |
|---|---|
| No leverage protection | ✅ Strong |
| Cascade detection | ✅ Present |
| Smart routing during volatility | ✅ Strong |
| Extreme slippage (>10%) | ⚠️ Accepted risk — stop fills at market |
| Exchange overload handling | ⚠️ Partial — connection monitor detects outage, no queue/retry |

---

## D2. Stop Hunt

**Timeframe:** Daily (minutes to hours)
**Frequency:** Every major support/resistance level

### What happens (step by step)
1. Many traders have stops clustered at $58,000 (below obvious support)
2. Market makers see this liquidity via order flow data
3. Price is pushed to $57,900 — just below the stop cluster
4. Thousands of stops trigger simultaneously → cascade of selling
5. Market makers buy the cascade at $57,900 (cheap)
6. Price immediately reverses to $60,000+
7. Retail sold at the bottom. Institutions bought the bottom

### What it costs
- **Money:** Stopped out at worst possible price, then watch the trade work
- **Emotional:** "The market is rigged!" — erosion of trust in strategy
- **Time:** Wasted analysis on a trade that was directionally correct

### Why it happens
- **Information asymmetry:** Market makers see order flow; retail doesn't
- **Liquidity needs:** Large players need counterparties. Clustered stops provide them
- **Coordination failure:** Retail traders place stops at obvious levels (round numbers, support)

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **ATR-Based Stop Placement** | Stops at ATR-based distances, not obvious round numbers. Statistically distributed, not clustered |
| **Order Book Depth Analysis** (`get_orderbook_depth()`) | Walks 50 levels. Detects unusual depth (potential stop clusters) and avoids placing stops in same zone |
| **Spread Analysis** | Widening spread signals liquidity withdrawal — precursor to stop hunts. System widens stops or pauses |
| **Slippage Monitoring** | Stop triggered with >50 bps slippage = flagged as potential hunt. Logged for pattern learning |
| **Liquidation Cascade Detection** | `_detect_cascade()` identifies clustering liquidations (aftermath of hunt). System avoids entering immediately |
| **Smart Order Routing** | In low-liquidity moments: limit orders with slippage bounds instead of market orders |

**TSAR Blueprint Handling:** The Rust tick-processor (`tick-processor` crate) provides real-time spread monitoring at sub-second granularity. The `orderbook.rs` module walks the depth to detect stop clusters. RegimeDetector flags HIGH_VOLATILITY when hunt conditions emerge. SignalScout's multi-timeframe confluence requirement (4h/1h/15m agreement) means a 5-minute hunt spike on 15m doesn't pass the 4h filter.

**Prevention confidence:** 75%

### Gap Analysis
| Capability | Status |
|---|---|
| ATR-based (non-obvious) stops | ✅ Strong |
| Order book depth analysis | ✅ Present |
| Spread-based early warning | ✅ Present |
| Sophisticated institutional hunts | ⚠️ Accepted — market makers have structural advantage |
| Anti-spoofing detection | ❌ Gap (Level 3+ future) |

---

## D3. News-Driven Volatility

**Timeframe:** Daily (minutes)
**Frequency:** Multiple times per week (FOMC, CPI, exchange hacks, regulatory tweets)

### What happens (step by step)
1. Breaking news: "SEC sues Binance" / "FOMC rate decision" / "CPI surprise"
2. Market drops -8% in 10 minutes (or pumps +8%)
3. Spreads widen to 10-50× normal
4. Stop losses fill at terrible prices due to liquidity vacuum
5. Price reverses within 2 hours as news is digested
6. Trader locked in maximum loss at the bottom

### What it costs
- **Money:** Sold the bottom. Typical loss: 5-10% of account on panic execution
- **Time:** Hours of emotional recovery. Days of degraded decision-making
- **Energy:** Fight-or-flight response impairs rational thinking for 30-60 minutes per event

### Why it happens
- **Information asymmetry:** News algorithms react in milliseconds; humans react in minutes
- **Coordination failure:** No pre-planned exit plan means any bad news triggers panic
- **Market inefficiency:** Liquidity providers withdraw during uncertainty, causing spread blow-out

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Pre-set Stop Losses** | Stop placed BEFORE entry as exchange-side OCO. "We never have an unprotected position." News-driven exits are automatic, not emotional |
| **Economic Blackout** (`MacroAgent`) | Auto-blocks trading around FOMC, CPI, NFP events. TSAR knows the economic calendar |
| **Sentiment Agent** | Fear & Greed Index. Extreme fear (<25) = contrarian BUY signal, not sell. System does opposite of crowd |
| **Macro Agent** | Classifies macro regime (RISK-ON/RISK-OFF/TRANSITION/CRISIS). Pre-news regime means the drop is noise unless regime changes |
| **Slippage Monitor** | Slippage > 50 bps → ABORT AND ALERT. System may reject execution and wait for spreads to normalize |
| **Smart Order Router** | Detects wide spreads, avoids market orders. Uses limit orders with slippage bounds |
| **Kill Switch** | If total drawdown hits -2%, system halts. Even if news is catastrophic, TSAR exits cleanly |

**TSAR Blueprint Handling:** The `MacroAgent` maintains an economic calendar and pre-emptively tightens risk parameters 2 hours before major events. The `SentimentAgent` aggregates CryptoPanic news feeds and Fear & Greed Index. The `InformationAgent` monitors breaking news. Together, they classify whether a price move is "noise" or "regime change" before the RiskGuardian decides whether to halt or continue.

**Prevention confidence:** 85%

### Gap Analysis
| Capability | Status |
|---|---|
| Pre-set stops handle exits | ✅ Strong |
| Economic calendar blackout | ✅ Present |
| Sentiment contrarian signal | ✅ Present |
| Genuinely regime-changing news | ⚠️ Slippage on gap-down can't be fully prevented |
| Sub-second news detection | ⚠️ Partial — LLM-based, not tick-level |

---

## D4. Spread Widening

**Timeframe:** Daily (hours)
**Frequency:** Every low-liquidity session (22:00-02:00 UTC, weekends)

### What happens (step by step)
1. Trader places a market buy during Asian session (low liquidity)
2. Bid-ask spread is $100 instead of usual $5
3. Market buy fills at $60,100 instead of $60,000 (instant -0.17% loss)
4. Price doesn't move, but trader is already underwater from spread
5. To break even, price needs to rise $100 just to cover the cost
6. Repeat 10 times: -1.7% bled to spread alone

### What it costs
- **Money:** 0.1-0.5% per trade in spread costs during illiquid hours
- **Time:** Invisible cost — trader thinks they lost on "the trade" when they lost on "the execution"
- **Energy:** None visible, but compounds into account death by a thousand cuts

### Why it happens
- **Market inefficiency:** Liquidity providers withdraw during low-volume hours
- **Information asymmetry:** Broker platforms show mid-price, not spread impact on execution
- **Coordination failure:** 24/7 market illusion — "always open" ≠ "always liquid"

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Spread Analysis** (`tick-processor/spread.rs`) | Real-time spread monitoring. Current > avg + 1σ → trading paused |
| **Time-Based Risk Rules** | Low-liquidity hours (22:00-02:00 UTC) restricted. Weekend trading reduced/halted |
| **Smart Order Router** | Detects thin order books. Uses TWAP/VWAP to avoid market impact. Iceberg for larger sizes |
| **Slippage Tracking** | Every fill measured: `slippage_bps = (actual - expected) / expected × 10,000`. >100 bps → flag and restrict future similar trades |
| **Liquidity Score** | Per-asset liquidity scoring. Low liquidity → 50%+ position size reduction |
| **Execution Engine Pre-Validation** | Checks exchange limits, min/max amounts, book depth BEFORE placing order. Too thin → rejected |

**TSAR Blueprint Handling:** The Rust `tick-processor` crate's `spread.rs` module computes real-time bid-ask spread with exponential smoothing. The `orderbook.rs` module scores liquidity depth. The `ExecutionSniper` agent queries these before every order. The `RiskGuardian` Check 4 (time rules) blocks trading during known low-liquidity windows.

**Prevention confidence:** 90%

### Gap Analysis
| Capability | Status |
|---|---|
| Real-time spread monitoring | ✅ Strong |
| Time-based restrictions | ✅ Strong |
| Smart routing in thin markets | ✅ Strong |
| Sudden liquidity withdrawal | ⚠️ Can happen faster than monitoring interval |
| Cross-exchange spread comparison | ❌ Gap |

---

## D5. Slippage

**Timeframe:** Daily (per trade)
**Frequency:** Every trade in thin markets

### What happens (step by step)
1. Order placed at $60,000 (limit or market)
2. Market buy fills at $60,060 (6 bps slippage)
3. Stop loss at $58,800 fills at $58,500 (30 bps slippage)
4. Take profit at $62,400 fills at $62,340 (6 bps slippage)
5. Total cost per round trip: 42 bps (0.42%) to slippage alone
6. On $10 account with $1.50 position: $0.006 per round trip

### What it costs
- **Money:** 0.05-0.5% per trade depending on market conditions
- **Time:** Invisible — compounds silently over hundreds of trades
- **Energy:** None visible, but turns profitable strategies into breakeven or losers

### Why it happens
- **Market inefficiency:** Order books are discrete, not continuous. Large orders walk the book
- **Information asymmetry:** HFT front-runs large orders
- **Latency:** Order reaches exchange after price moves

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Slippage Thresholds** | 10 bps → LOG WARNING. 50 bps → ABORT AND ALERT |
| **Smart Order Router** | Institutional execution: TWAP (time-sliced), VWAP (volume-weighted), Iceberg (hidden size) |
| **Market Impact Estimation** | Square-root model: `impact = coefficient × sqrt(order_size / avg_daily_volume)` |
| **Order Book Walk Simulation** | Walks the book to estimate average fill price vs mid-price before placing |
| **Size-Based Routing** | < $10k → direct. > $10k → SmartOrderRouter. > 1% of book → sliced execution |
| **Price Limit Support** | TWAP/VWAP slices skip if price moves beyond limit |

**TSAR Blueprint Handling:** The `SmartOrderRouter` (`src/tools/order_router.py`) implements three institutional strategies. The Rust `order-executor` crate provides sub-millisecond order slicing. The `ExecutionSniper` monitors fill quality per slice and aborts if cumulative slippage exceeds thresholds.

**Prevention confidence:** 85%

### Gap Analysis
| Capability | Status |
|---|---|
| TWAP/VWAP/Iceberg routing | ✅ Strong |
| Slippage monitoring and alerts | ✅ Strong |
| Market impact estimation | ✅ Strong |
| Predictive latency model | ⚠️ Gap — no exchange response time history |
| HFT front-running protection | ❌ Gap (MEV protection exists for DeFi only) |

---

## D6. API Rate Limits

**Timeframe:** Daily (minutes)
**Frequency:** During high-volatility periods when monitoring frequency increases

### What happens (step by step)
1. Market is volatile. TSAR's monitoring loops increase frequency
2. Exchange API rate limit hit (e.g., Binance: 1200 requests/minute)
3. API returns 429 Too Many Requests
4. Market data feeds go stale
5. Order status checks fail
6. Stop-loss status unknown — system can't verify protection
7. ConnectionMonitor may trigger kill switch after 3 consecutive failures

### What it costs
- **Money:** Blind period where positions are unprotected (stops exist on exchange but TSAR can't verify)
- **Time:** 1-5 minutes of degraded monitoring per incident
- **Energy:** System stress — cascading failures from rate limit hit

### Why it happens
- **Coordination failure:** Monitoring frequency scales with volatility, but rate limits are fixed
- **Market inefficiency:** Exchange rate limits don't scale with market activity
- **Information asymmetry:** TSAR doesn't know how close it is to the limit until it hits

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Connection Monitor** | Pings exchange every 30s. 3 consecutive failures → Kill Switch ACTIVATE |
| **ccxt Rate Limit Handling** | ccxt library has built-in rate limit awareness and backoff |
| **Watchdog Process** | Separate process monitors main heartbeat. If main process stalls (rate limit loop), Watchdog detects and halts |
| **Fail-Safe Defaults** | If can't verify stop-loss status, system assumes worst case (position unprotected) and activates kill switch |
| **Pre-placed Exchange-Side Stops** | Stops exist ON THE EXCHANGE, not in TSAR's memory. Even if TSAR can't check, stops still execute |
| **Position Recovery** | On startup/recovery: verifies ALL positions have active stops. Missing → auto-place at max_stop_loss_pct |

**TSAR Blueprint Handling:** The Rust `ws-manager` crate maintains persistent WebSocket connections that bypass REST rate limits for market data. The `connection.rs` module handles reconnection with exponential backoff. The `reconnect.rs` module manages connection pools. The `Watchdog` (`src/risk/watchdog.py`) operates as a separate process — if the main process stalls on rate limit loops, the Watchdog's heartbeat check fires after 30 seconds.

**Prevention confidence:** 85%

### Gap Analysis
| Capability | Status |
|---|---|
| WebSocket for market data | ✅ Strong (Rust ws-manager) |
| Connection monitoring | ✅ Strong |
| Watchdog survives process death | ✅ Strong |
| Exchange-side stops protect positions | ✅ Strong |
| Proactive rate limit tracking | ⚠️ Partial — reactive, not predictive |
| Multi-exchange failover on rate limit | ❌ Gap |

---

## D7. WebSocket Disconnection

**Timeframe:** Daily (minutes)
**Frequency:** Multiple times per day (exchange maintenance, network issues)

### What happens (step by step)
1. WebSocket connection to exchange drops silently
2. Market data feed goes stale — last known prices, not current
3. TSAR's signals are based on stale data
4. If a trade is placed on stale data: fills at wrong price
5. If a position is open: stop-loss status unknown
6. Reconnection may take 5-30 seconds depending on exchange

### What it costs
- **Money:** Stale data leads to bad fills. Unknown stop status = unprotected period
- **Time:** 5-30 seconds of blindness per disconnection
- **Energy:** System stress from reconnection storms during volatile markets

### Why it happens
- **Market infrastructure:** Exchange WebSocket servers have connection limits, maintenance windows
- **Network issues:** Packet loss, routing changes, DNS failures
- **Coordination failure:** Client-side connection management must handle server-side disconnects

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Rust WebSocket Manager** (`ws-manager` crate) | Persistent connections with automatic reconnection. `connection.rs` handles lifecycle, `reconnect.rs` manages exponential backoff |
| **Connection Pool** (`pool.rs`) | Multiple connections to handle failover. If primary drops, secondary takes over |
| **Message Parser** (`parser.rs`) | Validates message integrity. Detects stale/out-of-sequence data |
| **Connection Monitor** | 30-second ping cycle. 3 consecutive failures → Kill Switch |
| **Watchdog** | Separate process monitors main heartbeat. WebSocket death → heartbeat stale → Watchdog fires |
| **Pre-placed Exchange-Side Stops** | Stops execute at exchange level regardless of TSAR's connection state |

**TSAR Blueprint Handling:** The Rust `ws-manager` crate is the primary defense — built specifically for this scenario. It maintains a connection pool with health checks, automatic reconnection with backoff, and message integrity validation. The Python `ConnectionMonitor` provides a secondary check via REST ping. The `Watchdog` is the tertiary defense — if both WebSocket and REST fail, the Watchdog detects the stale heartbeat and fires the kill switch.

**Prevention confidence:** 90%

### Gap Analysis
| Capability | Status |
|---|---|
| Rust WebSocket manager | ✅ Strong |
| Connection pooling | ✅ Present |
| Message integrity validation | ✅ Present |
| Multi-exchange failover | ❌ Gap |
| Data staleness detection | ⚠️ Partial — relies on message sequencing |

---

# WEEKLY SCENARIOS (6)

---

## W1. Regime Change

**Timeframe:** Weekly (days)
**Frequency:** 2-4× per month in crypto

### What happens (step by step)
1. Market transitions from trending to ranging (or vice versa)
2. Momentum strategy entered during trend now faces choppy range
3. BTC-ETH correlation breaks — pairs trade thesis invalidates
4. ADX drops below 25 overnight
5. Strategy bleeds money on every false breakout for 3-5 days
6. By the time the regime change is obvious, -5% to -10% drawdown

### What it costs
- **Money:** 3-7 days of losses before strategy adapts. -5% to -10% drawdown typical
- **Time:** Days of bleeding before regime detection catches up
- **Energy:** Psychological — "the strategy stopped working" anxiety

### Why it happens
- **Market inefficiency:** Regime transitions are gradual, not discrete. No bell rings at the change
- **Information asymmetry:** Institutions detect regime change faster via order flow
- **Coordination failure:** Strategy parameters optimized for one regime fail in another

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **RegimeDetector** (`src/agents/regime_detector.py`) | HMM Classifier: 5-state Gaussian HMM on log returns, ATR, ADX, BB width. Retrains every 50 cycles |
| **Rule-Based Fallback** | ATR% > 3.0 → HIGH_VOLATILITY. ADX > 25 + DI+ > DI- → STRONG_TREND_UP. ADX ≤ 25 → RANGING |
| **CorrelationAnalyzer** (`src/tools/correlation.py`) | `detect_anomalies()`: z-score > 2.0 flags correlation breaks. `classify_regime()`: crisis/normal/decoupled/rotation |
| **Signal Adaptation** | SignalScout subscribes to `tsar:stream:regime`. Scoring weights shift per regime |
| **Strategy Retirement Gates** | Rolling Sharpe < 0.5 for 30 days → consider retirement. DD > 15% → PAUSE. DD > 20% → RETIRE |
| **GenomeMutator** | Proposes strategy parameter changes adapted to new regime. WalkForwardValidator (G7) tests |

**TSAR Blueprint Handling:** The `RegimeDetector` uses both HMM (probabilistic) and deterministic rules (ADX/ATR/BB) for dual detection. When regime changes, it publishes to `tsar:stream:regime`. The `SignalScout` adjusts scoring weights (trend-following vs mean-reversion). The `StrategyGeneticist` can retire underperforming strategies via genome status updates. The `FlywheelOrchestrator` triggers the adaptation loop: EXTRACT rules from recent losses → VALIDATE via backtest → MUTATE strategy parameters → EVOLVE via walk-forward.

**Prevention confidence:** 75%

### Gap Analysis
| Capability | Status |
|---|---|
| HMM + rule-based detection | ✅ Strong |
| Correlation break detection | ✅ Present |
| Automatic strategy switching | ⚠️ Partial — can retire, no real-time swap |
| Real-time regime-triggered position adjustment | ⚠️ Partial — metadata available, not wired to position sizer |
| Cross-asset correlation response | ❌ Gap — anomaly detected but no automated hedging |

---

## W2. Correlation Breakdown

**Timeframe:** Weekly (days)
**Frequency:** 1-2× per month during market structure shifts

### What happens (step by step)
1. BTC and ETH historically correlated at 0.85+
2. Market event causes correlation to drop to 0.3 (decoupling)
3. Pairs trade that was "hedged" is now unhedged
4. BTC drops -5% while ETH rises +3% — or vice versa
5. Both legs of the pairs trade lose simultaneously
6. What was "hedged" was actually double exposure

### What it costs
- **Money:** "Hedged" positions generate correlated losses. -5% to -15% on pairs trades
- **Time:** Days to recognize the correlation has broken
- **Energy:** False sense of security from "hedged" positions

### Why it happens
- **Market inefficiency:** Correlations are dynamic, not static. Historical correlation ≠ future correlation
- **Information asymmetry:** Institutions see flow rotation in real-time; retail uses lagging indicators
- **Coordination failure:** No real-time correlation monitoring in most systems

### How TSAR prevents it

| Component | Mechanism |
|-----------|---|
| **CorrelationAnalyzer** (`src/tools/correlation.py`) | Rolling correlation with z-score anomaly detection (>2.0 = flag). Engle-Granger cointegration testing |
| **MarketCartographer** (`src/agents/market_cartographer.py`) | Cross-asset correlation mapping. Real-time correlation matrix across portfolio |
| **Regime-Aware Correlation** | In HIGH_VOLATILITY regime, all crypto correlations spike toward 1.0. System reduces total crypto exposure |
| **Position Limits** | Max 3 concurrent positions. Combined correlated exposure capped at 20% of equity |
| **Symbol Cooldown** | 30-minute cooldown per symbol prevents rapid accumulation of correlated positions |

**TSAR Blueprint Handling:** The `MarketCartographer` agent maintains a real-time correlation map across all tracked assets. When `CorrelationAnalyzer.detect_anomalies()` flags a z-score > 2.0, the information propagates to `RiskGuardian` via the event bus. The risk engine can then reduce position sizes on correlated assets. The `RegimeDetector` classifies the correlation state (crisis/normal/decoupled/rotation) and adjusts portfolio-wide risk parameters.

**Prevention confidence:** 70%

### Gap Analysis
| Capability | Status |
|---|---|
| Rolling correlation monitoring | ✅ Present |
| Anomaly detection (z-score) | ✅ Present |
| Cointegration testing | ✅ Present |
| Automated hedging on break | ❌ Gap — detection only, no automated response |
| Intra-day correlation spikes | ⚠️ Historical data lags real-time stress |

---

## W3. Weekend Gap

**Timeframe:** Weekly (weekend)
**Frequency:** Every weekend (crypto markets continue but with reduced liquidity)

### What happens (step by step)
1. Friday 23:00: TSAR has open positions with stops on exchange
2. Weekend: liquidity drops 50-80%. Market makers reduce activity
3. Sunday: a large player dumps $20M notional in thin market
4. BTC gaps down -8% from Friday close
5. Stop at $58,800 fills at $54,500 (massive slippage in thin market)
6. Monday: price recovers to $59,000. Stop was at the weekend bottom

### What it costs
- **Money:** Weekend slippage amplifies stop-loss costs 3-5×
- **Time:** 48 hours of reduced monitoring capability
- **Energy:** Anxiety about unprotected weekend positions

### Why it happens
- **Market inefficiency:** Weekend liquidity is structurally lower — fewer market makers
- **Information asymmetry:** Large players exploit thin weekend markets
- **Coordination failure:** 24/7 markets ≠ 24/7 liquidity

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Time-Based Risk Rules** | Weekend trading reduced or halted. Position sizes reduced on Friday |
| **Spread Analysis** | Weekend spreads blow out. Spread monitor detects and pauses new entries |
| **Pre-placed Exchange-Side Stops** | Stops execute at exchange level regardless of TSAR's status. Protection exists even when TSAR "sleeps" |
| **Liquidity Score** | Weekend liquidity score → lower → smaller positions |
| **Kill Switch** | If weekend gap causes >2% daily loss, system halts on Monday startup via position recovery |
| **Position Recovery** | On Monday startup: verifies all positions have active stops. Re-places any missing |

**TSAR Blueprint Handling:** The `MacroAgent` maintains a market calendar that includes weekend awareness. The `RiskGuardian` Check 4 (time rules) restricts trading during known low-liquidity periods. The `PositionSizer` incorporates liquidity scores that degrade on weekends. The `PositionRecovery` module ensures that any stops that got filled over the weekend are detected and positions properly managed on system restart.

**Prevention confidence:** 75%

### Gap Analysis
| Capability | Status |
|---|---|
| Weekend-aware position sizing | ✅ Present |
| Exchange-side stops | ✅ Strong |
| Position recovery on restart | ✅ Strong |
| Weekend gap slippage | ⚠️ Accepted risk — stops fill at market |
| Weekend liquidity monitoring | ⚠️ Partial — spread-based, not order-book-depth-based |

---

## W4. Strategy Conflict

**Timeframe:** Weekly (days)
**Frequency:** When multiple strategies are active (future scaling)

### What happens (step by step)
1. Momentum strategy generates BUY signal on BTC (trend is up)
2. Mean-reversion strategy generates SELL signal on BTC (overbought)
3. Both signals pass individual scoring thresholds
4. If both execute: opposing positions on same asset = guaranteed loss (spread + fees)
5. If system oscillates: rapid buy-sell-buy-sell = fee bleed
6. Net result: conflicting strategies cancel each other out while paying fees

### What it costs
- **Money:** Opposing positions = spread + fees on both sides. Oscillation = compounded fee bleed
- **Time:** Wasted analysis cycles on conflicting signals
- **Energy:** System confusion — agents contradicting each other

### Why it happens
- **Coordination failure:** Multiple strategy agents without central coordination
- **Information asymmetry:** Each strategy sees its own signal but not the others'
- **Market inefficiency:** Different timeframes/frames generate conflicting but individually valid signals

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Single Signal Source** | SignalScout produces ONE signal per symbol per scan cycle. No conflicting signals from same source |
| **Sequential Risk Evaluation** | RiskGuardian evaluates sequentially. First HARD/NUCLEAR veto terminates. No ambiguity |
| **Symbol Cooldown** | 30-minute cooldown per symbol prevents rapid conflicting trades |
| **Conflicting Position Check** | RiskGuardian Check 8 blocks signals creating opposite positions on same symbol |
| **Orchestrator Coordination** | Event-driven flow: scan → signal → risk → execute → reflect. No concurrent evaluations |
| **MandateGate Pre-Filter** | Before risk evaluation, MandateGate checks authorization. Unauthorized trades blocked |

**TSAR Blueprint Handling:** The `Orchestrator` is the central coordinator — it manages agent lifecycle and ensures sequential event-driven flow. The `RiskGuardian` has absolute veto power (Check 8: conflicting positions). The `SignalScout` is the single source of signals, eliminating multi-source conflicts at the root. When `StrategyGeneticist` evaluates new strategy genomes, it tests them against existing strategies to detect conflict potential.

**Prevention confidence:** 95%

### Gap Analysis
| Capability | Status |
|---|---|
| Single signal source | ✅ Strong |
| Sequential evaluation | ✅ Strong |
| Conflicting position prevention | ✅ Strong |
| Multi-strategy orchestration (future) | ⚠️ Design gap for Level 2+ scaling |
| Agent disagreement resolution | ✅ Strong — RiskGuardian absolute veto |

---

## W5. Edge Decay

**Timeframe:** Weekly to Monthly (weeks)
**Frequency:** Continuous — all edges decay over time

### What happens (step by step)
1. Strategy has a documented edge: 55% win rate, 2:1 R:R over 200 trades
2. Market participants discover the same pattern
3. More capital competing for the same edge → edge gets arbitraged away
4. Win rate drops from 55% → 52% → 48% over 4-8 weeks
5. Strategy goes from profitable to breakeven to losing
6. By the time the decay is obvious, significant capital has been lost

### What it costs
- **Money:** Strategy bleeds from profitable to losing over weeks. -5% to -15% during decay period
- **Time:** Weeks of declining performance before retirement decision
- **Energy:** Psychological — "it was working before" attachment to decaying strategy

### Why it happens
- **Market efficiency:** Profitable strategies get crowded. Alpha is competed away
- **Information asymmetry:** Edge discovery is asymmetric — early adopters profit, latecomers lose
- **Coordination failure:** No monitoring of strategy crowding or competition

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Rolling Sharpe Monitoring** | Strategy retirement gates: Sharpe < 0.5 for 30 days → consider retirement |
| **Factor Benchmarking (G9)** | Periodic IC/IR benchmarks on factor library. Tracks factor decay over time |
| **WalkForwardValidator (G7)** | Rolling train/test windows. Detects when train performance >> test performance |
| **Monte Carlo Simulation (G8)** | 1,000 simulations per evaluation. Probability of ruin > 10% → REJECT |
| **Flywheel Learning** | Pattern Library stores pattern performance over time. Declining patterns get deprecated |
| **Strategy Retirement Gates** | Win rate < 40% over 50 trades → RETIRE. DD > 20% → RETIRE |
| **GenomeMutator** | Proposes parameter adjustments to adapt to changing market conditions |

**TSAR Blueprint Handling:** The `StrategyGeneticist` runs the full evaluation pipeline (BacktestEngine → WalkForwardValidator → MonteCarloSimulator → FactorBenchmarker) on a rolling basis. The `FlywheelOrchestrator` triggers this after every N trades. The `PatternLibrary` tracks pattern confidence with decay — patterns that fail get deprecated. The `LessonArchive` captures edge decay as a lesson type, so future strategies are pre-warned.

**Prevention confidence:** 75%

### Gap Analysis
| Capability | Status |
|---|---|
| Rolling performance monitoring | ✅ Strong |
| Overfitting detection | ✅ Strong |
| Factor decay tracking | ✅ Present |
| Strategy crowding detection | ❌ Gap — no monitoring of external competition |
| Automated strategy rotation | ⚠️ Partial — can retire, no auto-replacement |

---

## W6. Funding Rate Flip

**Timeframe:** Weekly (hours to days)
**Frequency:** 1-3× per month during trend extremes

### What happens (step by step)
1. BTC in strong uptrend. Funding rate is +0.1% per 8 hours (longs pay shorts)
2. TSAR holds a long position. Funding cost: 0.3%/day = 2.1%/week
3. Funding rate flips to -0.1% (shorts pay longs) during a pullback
4. TSAR's long position now earns funding, but the position is losing on price
5. Net: funding costs during the trend eat into profits; funding income during pullback doesn't compensate

### What it costs
- **Money:** Funding costs can consume 30-50% of a trend-following strategy's edge in persistent trends
- **Time:** Funding is invisible in P&L unless explicitly tracked
- **Energy:** Confusion — "the trade was right but I lost money"

### Why it happens
- **Market inefficiency:** Funding rates are a mechanism to balance perpetual futures, but they create drag on directional positions
- **Information asymmetry:** Sophisticated traders hedge funding via spot+futures; retail doesn't
- **Coordination failure:** Most systems don't incorporate funding into position management

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Fee-Aware Position Sizing** | Half-Kelly formula includes exchange fees. Funding rate is a variable fee |
| **MacroAgent Awareness** | Monitors funding rates as part of market context. Extreme funding = caution signal |
| **SentimentAgent** | Funding rate is a sentiment indicator. Extreme positive = crowded long = contrarian signal |
| **Strategy Parameters** | Strategy genomes can include funding rate thresholds for entry/exit decisions |
| **Cost Tracking** | Trade memory records all costs including funding. Flywheel learns funding impact over time |

**TSAR Blueprint Handling:** The `SentimentAgent` aggregates funding rates from CryptoPanic and direct exchange feeds. Extreme funding (>0.1%/8h) is treated as a contrarian signal — crowded longs are vulnerable to squeezes. The `MacroAgent` includes funding context in its regime classification. The `TradePhilosopher` records funding costs as part of trade outcomes, so the flywheel learns the true cost of holding positions during funding extremes.

**Prevention confidence:** 65%

### Gap Analysis
| Capability | Status |
|---|---|
| Funding rate monitoring | ✅ Present |
| Contrarian funding signal | ✅ Present |
| Funding-aware position sizing | ⚠️ Partial — included in fees but not explicit |
| Spot+futures funding hedge | ❌ Gap — no spot trading capability (Day1) |
| Automated funding-aware exits | ❌ Gap — no trigger for "close because funding is too expensive" |

---

# MONTHLY SCENARIOS (6)

---

## M1. Drawdown Streak

**Timeframe:** Monthly (weeks)
**Frequency:** 1-2× per year for any strategy

### What happens (step by step)
1. Strategy enters a losing streak: 8 losses in a row over 2 weeks
2. Each loss is small (-0.3% per trade on $10 = -$0.03)
3. Total drawdown: -2.4% over 14 days
4. Anti-revenge guard fires after 3 losses (60-min cooldown) but losses continue after cooldown
5. Drawdown circuit breaker: GREEN → YELLOW (2-3%) → position sizes halved
6. Recovery takes 3-4 weeks as strategy slowly recovers with reduced sizes

### What it costs
- **Money:** -2.4% drawdown. Recovery at reduced sizing takes 3-4 weeks
- **Time:** 4-6 weeks from drawdown start to full recovery
- **Energy:** Psychological — extended losing streaks erode confidence in the system

### Why it happens
- **Market regime:** Strategy may be in wrong regime (mean-reversion in trending market)
- **Statistical variance:** Even a 55% win rate has runs of 8+ losses (probability: ~0.5%)
- **Edge decay:** Strategy edge may be declining (see W5)

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Drawdown Monitor** | 4-level circuit breaker: GREEN(<2%) → YELLOW(2-3%, ×0.5) → ORANGE(3-5%, ×0.0) → RED(>5%, KILL) |
| **Daily P&L Halt** | -2% daily → ORANGE (halt new trades). -3% daily → RED (flatten all) |
| **Anti-Revenge Guard** | 3 consecutive losses → 60-min mandatory cooldown. Prevents compounding losses |
| **Gated Recovery** | After RED: position sizes 5% → 10% → 25% → 50% → 100% over 24-192 hours |
| **Strategy Retirement** | Rolling Sharpe < 0.5 for 30 days → consider retirement. DD > 20% → RETIRE |
| **Flywheel Adaptation** | FlywheelOrchestrator triggers after batch of losses. Extracts lessons, proposes mutations |

**TSAR Blueprint Handling:** The `DrawdownMonitor` (`src/risk/drawdown.py`) is the primary defense — it evaluates on every portfolio snapshot and determines the circuit breaker level. The `RiskGuardian` enforces the sizing multiplier (YELLOW = ×0.5, ORANGE = ×0.0). The `KillSwitch` activates on RED. The `FlywheelOrchestrator` detects the losing streak and triggers the adaptation loop: `ShadowExtractor` mines rules from the losses, `RuleValidator` backtests, `GenomeMutator` proposes parameter changes.

**Prevention confidence:** 90%

### Gap Analysis
| Capability | Status |
|---|---|
| Progressive circuit breaker | ✅ Strong |
| Daily P&L halt | ✅ Strong |
| Anti-revenge cooldown | ✅ Strong |
| Gated recovery protocol | ✅ Strong |
| Extended losing streak (10+ trades) | ⚠️ Circuit breaker catches at 2-3%, but losses accumulate within GREEN zone |

---

## M2. Model Drift

**Timeframe:** Monthly (weeks to months)
**Frequency:** Continuous — all models drift over time

### What happens (step by step)
1. LLM (DeepSeek-R1) was fine-tuned/trained on data up to 2025
2. Market structure evolves: new participants, new regulations, new instruments
3. LLM's pattern recognition becomes less accurate
4. Signal quality slowly degrades: 0.65 → 0.62 → 0.58 average score
5. Strategies based on LLM analysis underperform
6. By the time drift is detected, months of suboptimal signals

### What it costs
- **Money:** Suboptimal signals for weeks/months. -5% to -15% underperformance vs. baseline
- **Time:** Months to detect and retrain/replace the model
- **Energy:** Invisible degradation — system "works" but worse than before

### Why it happens
- **Information asymmetry:** Model training data is always historical; markets are always evolving
- **Coordination failure:** No real-time model performance monitoring
- **Market inefficiency:** Market microstructure changes (new order types, new participants) aren't in training data

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **LLM Evaluation Pipeline** (`src/llm/evaluation.py`) | Periodic model evaluation against known-good benchmarks |
| **WalkForwardValidator (G7)** | Rolling train/test windows detect when model performance degrades on recent data |
| **Factor Benchmarking (G9)** | IC/IR benchmarks track factor predictive power over time |
| **Pattern Library Confidence Decay** | Patterns lose confidence if not re-validated. Stale patterns get deprecated |
| **LLM Router** (`src/llm/router.py`) | Can swap models if primary degrades. Fallback chain: DeepSeek → Ollama → NVIDIA NIM |
| **Trade Philosopher** | Post-trade reflection tracks signal quality trends. Detects systematic degradation |
| **Flywheel Post-Training** | (Future) Trade data can post-train the model — domain-specific weight updates |

**TSAR Blueprint Handling:** The `LLM Router` provides model abstraction — if DeepSeek-R1 degrades, the system can swap to Ollama or NVIDIA NIM via config change. The `LLM Evaluation` pipeline benchmarks model performance periodically. The `FlywheelOrchestrator` generates proprietary data from trade outcomes that can (future) post-train the model. The `TradePhilosopher` tracks signal quality as a metric — declining average score triggers investigation.

**Prevention confidence:** 65%

### Gap Analysis
| Capability | Status |
|---|---|
| Model swap capability | ✅ Strong |
| Periodic evaluation | ✅ Present |
| Factor decay tracking | ✅ Present |
| Real-time per-trade drift detection | ❌ Gap — evaluation is periodic, not per-trade |
| Post-training on proprietary data | ❌ Gap — future capability |

---

## M3. Portfolio Correlation Collapse

**Timeframe:** Monthly (weeks)
**Frequency:** 1-2× per year during market crises

### What happens (step by step)
1. Portfolio has 3 positions: BTC long, ETH long, SOL long
2. Historical correlations: BTC-ETH 0.85, BTC-SOL 0.75, ETH-SOL 0.70
3. Market crisis: all correlations spike to 0.95+
4. What was "diversified" (3 positions) is actually 1 bet (crypto direction)
5. Market drops -10%: all 3 positions lose -10% simultaneously
6. Portfolio loss: -10% instead of the expected -6% (from "diversification")

### What it costs
- **Money:** Correlated losses exceed expected portfolio risk by 40-60%
- **Time:** Crisis lasts days to weeks. Portfolio is fully exposed throughout
- **Energy:** False sense of security from "diversified" portfolio

### Why it happens
- **Market inefficiency:** In crises, all risk assets correlate to 1.0. Diversification vanishes exactly when needed most
- **Information asymmetry:** Historical correlations understate crisis correlations
- **Coordination failure:** Portfolio construction based on normal-market correlations

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **MarketCartographer** | Cross-asset correlation mapping. Real-time correlation matrix across portfolio |
| **Regime-Aware Correlation** | In HIGH_VOLATILITY regime: all crypto correlations assumed → 1.0. Total crypto exposure auto-reduced |
| **Position Limits** | Max 3 positions (Day1). Even fully correlated, exposure capped at ~45% of equity |
| **CorrelationAnalyzer** | `detect_anomalies()` flags z-score > 2.0. `classify_regime()` labels crisis state |
| **Drawdown Monitor** | Correlated losses trigger circuit breaker. -2% → halt. Prevents further correlated exposure |
| **Cash Buffer** | 55% minimum cash (3 positions × 15% max = 45% max invested) |

**TSAR Blueprint Handling:** The `MarketCartographer` maintains a live correlation matrix. When `RegimeDetector` shifts to HIGH_VOLATILITY, the system assumes all crypto correlations → 1.0 and reduces total exposure. The `RiskGuardian` enforces the 45% maximum invested (3 × 15% positions). The `DrawdownMonitor` provides the final safety net — if correlated losses hit -2%, the system halts regardless of individual position health.

**Prevention confidence:** 75%

### Gap Analysis
| Capability | Status |
|---|---|
| Real-time correlation mapping | ✅ Present |
| Regime-aware correlation assumption | ✅ Present |
| Position limit enforcement | ✅ Strong |
| Crisis-specific hedging | ❌ Gap — no options/futures hedge capability (Day1) |
| Dynamic correlation-based position sizing | ⚠️ Partial — regime triggers reduction, but not per-pair |

---

## M4. Capital Allocation Failure

**Timeframe:** Monthly (weeks)
**Frequency:** Continuous risk

### What happens (step by step)
1. Capital concentrated in one strategy/asset class
2. Strategy/asset class enters drawdown
3. No other strategies to absorb the loss
4. Entire portfolio drawdown = strategy drawdown (no diversification benefit)
5. Capital that could be deployed to better opportunities is locked in losers
6. Opportunity cost compounds over weeks

### What it costs
- **Money:** 100% of drawdown is realized (no diversification buffer). Opportunity cost of locked capital
- **Time:** Weeks of capital locked in underperforming strategy
- **Energy:** Psychological — watching other opportunities while holding losers

### Why it happens
- **Coordination failure:** No portfolio-level allocation framework
- **Information asymmetry:** Can't compare opportunity cost across strategies without systematic tracking
- **Market inefficiency:** Capital allocation is a portfolio construction problem, not a signal problem

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Max 3 Positions (Day1)** | Prevents over-concentration in single strategy/asset |
| **15% Equity Cap per Position** | No single position can dominate the portfolio |
| **55% Minimum Cash** | Always has dry powder for new opportunities |
| **Half-Kelly Position Sizing** | Mathematically optimal allocation based on edge quality |
| **Strategy Retirement Gates** | Underperforming strategies get retired, freeing capital |
| **Flywheel Allocation** | (Future) Capital shifts toward strategies with better recent performance |

**TSAR Blueprint Handling:** The `PositionSizer` implements Half-Kelly with hard caps. The `RiskGuardian` enforces the 15% equity cap and 3-position limit. The `StrategyGeneticist` evaluates strategy performance and can retire underperforming genomes. The `cuopt_optimizer` (NVIDIA cuOpt) can optimize portfolio allocation across strategies (Level 2+).

**Prevention confidence:** 80%

### Gap Analysis
| Capability | Status |
|---|---|
| Position concentration limits | ✅ Strong |
| Kelly-optimal sizing | ✅ Strong |
| Cash buffer preservation | ✅ Strong |
| Multi-strategy capital allocation | ⚠️ Partial — single strategy (Day1) |
| Opportunity cost tracking | ❌ Gap — no cross-strategy comparison |

---

## M5. Knowledge Staleness

**Timeframe:** Monthly (months)
**Frequency:** Continuous — all knowledge decays

### What happens (step by step)
1. Pattern Library has 500 validated patterns from 2025 data
2. Market structure evolves: new instruments, new participants, new regulations
3. Patterns that worked in 2025 fail in 2026
4. System continues recommending stale patterns
5. Signal quality degrades because pattern matches are outdated
6. By the time staleness is detected, months of suboptimal signals

### What it costs
- **Money:** Stale patterns generate losing signals. -3% to -8% underperformance
- **Time:** Months of degraded signal quality before refresh
- **Energy:** Invisible — system "works" but uses outdated knowledge

### Why it happens
- **Information asymmetry:** Knowledge is always historical; markets always evolve
- **Coordination failure:** No systematic knowledge freshness monitoring
- **Market inefficiency:** Market structure changes aren't announced — they're discovered

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Pattern Library Confidence Decay** | Patterns lose confidence over time if not re-validated. Stale patterns auto-deprecate |
| **Lesson Archive** | Post-trade reflections capture what's changing. Evolving patterns get updated |
| **FTS5 Semantic Search** | Quality scoring ranks patterns by recency and relevance |
| **Knowledge Graph** | Entity relationships updated continuously. Stale connections pruned |
| **Flywheel Learning** | Every trade updates knowledge. New patterns replace stale ones |
| **Rule Validator** | Backtests extracted rules against current data. Rules that fail current data get rejected |

**TSAR Blueprint Handling:** The `PatternLibrary` has built-in confidence decay — patterns that aren't re-validated against recent data lose confidence scores. The `RuleValidator` backtests every extracted rule against current OHLCV data. The `FlywheelOrchestrator` continuously generates fresh knowledge from trade outcomes. The `KnowledgeGraph` maintains entity relationships that evolve with market structure.

**Prevention confidence:** 70%

### Gap Analysis
| Capability | Status |
|---|---|
| Pattern confidence decay | ✅ Present |
| Rule re-validation | ✅ Present |
| Continuous flywheel learning | ✅ Strong |
| Structured knowledge refresh schedule | ⚠️ Partial — triggered by trades, not time |
| External knowledge integration | ❌ Gap — no ingestion of external research/data |

---

## M6. Flywheel Degradation

**Timeframe:** Monthly (weeks to months)
**Frequency:** Continuous risk

### What happens (step by step)
1. Flywheel generates lessons from trade outcomes
2. Low trade volume → insufficient data for pattern extraction
3. Shadow extractor can't find statistically significant rules from 20 trades
4. Rule validator rejects rules with insufficient sample size
5. Genome mutator has no validated mutations to propose
6. Flywheel stalls — system stops improving

### What it costs
- **Money:** System doesn't improve. Edge that could be discovered stays hidden
- **Time:** Weeks of zero improvement. System is "alive" but not learning
- **Energy:** The flywheel's promise (compounding knowledge) goes unfulfilled

### Why it happens
- **Coordination failure:** Flywheel needs minimum data volume. Low-volume trading can't feed it
- **Information asymmetry:** Can't know what patterns exist without sufficient data
- **Market inefficiency:** Small accounts trade small, which means slow flywheel

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **FlywheelOrchestrator** | Configurable batch_size (default 10) and cooldown (5 min). Adapts to trade volume |
| **Shadow Account** | Shadow extractor runs on historical data too, not just live trades. Can learn from backtest data |
| **ChromaDB Vector Store** | Semantic similarity search finds related patterns even from sparse data |
| **Knowledge Graph** | Entity relationships provide structural knowledge that doesn't need high trade volume |
| **WalkForwardValidator** | Uses historical data for validation, not just live trades |
| **Factor Library** | Pre-loaded factors don't need live trade data. Provide baseline knowledge |

**TSAR Blueprint Handling:** The `FlywheelOrchestrator` is designed for variable trade volumes. The `ShadowExtractor` can analyze historical backtest data, not just live trades. The `ChromaDB` vector store enables semantic similarity — even sparse trade data can match against the broader pattern library. The `FactorLibrary` provides pre-loaded factors that work regardless of trade volume.

**Prevention confidence:** 70%

### Gap Analysis
| Capability | Status |
|---|---|
| Configurable batch size | ✅ Present |
| Historical data analysis | ✅ Present |
| Vector similarity search | ✅ Present |
| Minimum data threshold warnings | ⚠️ Partial — no explicit stall detection |
| Cold-start bootstrapping | ⚠️ Partial — factor library helps, but pattern library needs data |

---

# YEARLY SCENARIOS (6)

---

## Y1. Black Swan Event

**Timeframe:** Yearly (hours to days)
**Frequency:** 1-3× per decade (Mt. Gox, FTX, Terra/Luna, COVID crash)

### What happens (step by step)
1. Exchange hack (Mt. Gox, FTX) — funds frozen, exchange insolvent
2. OR: Regulatory ban (China 2021) — entire market segment declared illegal
3. OR: Stablecoin depeg (UST/Luna) — "stable" asset goes to zero
4. Market drops -30% to -80% in hours/days
5. All correlations → 1.0. All liquidity vanishes
6. Exchange goes offline. No way to exit positions
7. Funds on exchange may be permanently lost

### What it costs
- **Money:** Catastrophic. 30-100% of exchange-held capital. Permanent loss
- **Time:** Months to years of recovery (if recovery is possible)
- **Energy:** Existential threat to the entire trading operation

### Why it happens
- **Information asymmetry:** Black swans are, by definition, unpredictable in timing
- **Market infrastructure failure:** Exchange counterparty risk is structural
- **Coordination failure:** No individual can prevent systemic events

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Connection Monitor** | Exchange unreachable → Kill Switch in 90 seconds |
| **Watchdog Process** | Survives main process death. Fires kill switch via file-based heartbeat |
| **Kill Switch (dual-write)** | File-primary survives Redis failure. External kill via file write |
| **Pre-placed Exchange-Side Stops** | Stops execute at exchange level. Protection exists even if TSAR is offline |
| **Position Recovery** | On startup: verifies all positions have stops. Missing → auto-place |
| **MandateGate** | Can restrict trading to specific symbols. Can block all live trading instantly |
| **Manual Override** | Telegram /stop. External file write. Both bypass all logic |
| **Gated Recovery** | After halt: 5% → 10% → 25% → 50% → 100% over 24-192 hours |
| **Progressive Circuit Breaker** | GREEN → YELLOW → ORANGE → RED. Catches cascading losses before catastrophe |

**TSAR Blueprint Handling:** The `KillSwitch` is the nuclear option — dual-write (file + Redis), fail-safe defaults (assume active on error), external kill capability. The `Watchdog` survives main process death. The `MandateGate` can instantly restrict all trading. The `ConnectionMonitor` detects exchange outages within 90 seconds. The `MacroAgent` and `SentimentAgent` detect extreme negative events. The Telegram bot provides manual /stop for immediate human override.

**Prevention confidence:** 60%

### Gap Analysis
| Capability | Status |
|---|---|
| Exchange outage detection | ✅ Strong |
| Emergency halt mechanisms | ✅ Strong |
| External kill capability | ✅ Strong |
| Exchange counterparty risk | ❌ Gap — no multi-exchange fund distribution |
| Automated cross-exchange recovery | ❌ Gap — manual process |
| Stablecoin depeg detection | ⚠️ Partial — correlation anomaly can flag, no specific monitor |

---

## Y2. Regulatory Change

**Timeframe:** Yearly (months)
**Frequency:** Continuous — regulation is always evolving

### What happens (step by step)
1. Government announces new crypto regulation (KYC requirements, tax rules, ban on certain instruments)
2. Market participants react: some exit, some adapt
3. Market structure changes: liquidity shifts, new exchanges, old exchanges close
4. Strategies optimized for old structure underperform
5. Compliance requirements change what's tradeable
6. Entire system may need reconfiguration

### What it costs
- **Money:** Strategy underperformance during transition. Potential loss of access to markets
- **Time:** Weeks to months of adaptation
- **Energy:** Uncertainty — can't plan when rules are changing

### Why it happens
- **External force:** Regulation is exogenous — no market participant controls it
- **Information asymmetry:** Regulatory changes are often leaked or rumored before official
- **Coordination failure:** Individual traders can't influence regulatory process

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **MacroAgent** | Monitors economic/regulatory context. Classifies macro regime |
| **InformationAgent** | Monitors news feeds for regulatory announcements |
| **SentimentAgent** | Regulatory news shifts sentiment. Extreme negative = caution signal |
| **MandateGate** | Configurable mandate can restrict to specific exchanges, symbols, regions |
| **BackendRegistry** | Config-driven backend selection. Can swap exchanges if one becomes restricted |
| **Interface Layer** | Abstract interfaces mean exchange backend can change without rewriting strategy logic |
| **Manual Override** | MandateGate allows instant restriction of trading parameters via config |

**TSAR Blueprint Handling:** The `MacroAgent` maintains regulatory awareness. The `InformationAgent` monitors news feeds including regulatory announcements. The `MandateGate` (`src/risk/mandate_gate.py`) is the control point — it can instantly restrict trading to specific symbols, exchanges, or regions via `config/mandate.yaml`. The `BackendRegistry` allows swapping exchange backends without changing strategy code — if Binance becomes restricted, the system can switch to Kraken via config change.

**Prevention confidence:** 55%

### Gap Analysis
| Capability | Status |
|---|---|
| Regulatory news monitoring | ✅ Present |
| Configurable mandate restrictions | ✅ Strong |
| Exchange backend swapping | ✅ Strong |
| Automated compliance adaptation | ❌ Gap — requires manual mandate updates |
| Tax reporting integration | ❌ Gap — no automated tax calculation |

---

## Y3. Market Structure Shift

**Timeframe:** Yearly (months)
**Frequency:** 1-2× per decade (DeFi emergence, ETF approval, institutional adoption)

### What happens (step by step)
1. New market structure emerges (Bitcoin ETF, DeFi protocols, new layer-1 chains)
2. Liquidity migrates from old venues to new ones
3. Strategies optimized for old structure lose edge
4. New opportunities emerge but require new capabilities
5. Market correlations change as new participants enter
6. System built for old structure becomes obsolete

### What it costs
- **Money:** Opportunity cost of not adapting. Strategy underperformance during transition
- **Time:** Months of adaptation. May require significant system changes
- **Energy:** Existential — "is our entire approach outdated?"

### Why it happens
- **Market evolution:** Technology and regulation drive structural changes
- **Information asymmetry:** Early adopters of new structure profit; latecomers lose
- **Coordination failure:** Adapting to structural change requires coordinated system-wide updates

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Interface Layer** | Abstract interfaces (ExchangeGateway, PricingEngine, ExecutionEngine) decouple strategy from implementation |
| **BackendRegistry** | Config-driven backend selection. New venues added via config, not code |
| **DeFi Integration** | DEX execution (1inch, Jupiter), intent-based trading (CoW, UniswapX), cross-chain bridging |
| **StrategyGeneticist** | Can evolve strategy genomes to adapt to new market structure |
| **Factor Library** | Factors can be added/removed as market structure changes |
| **LLM Provider Abstraction** | Can swap LLMs as better models emerge for new market conditions |

**TSAR Blueprint Handling:** The interface layer is TSAR's strongest structural defense. The 5 abstract base classes (`ExchangeGateway`, `PricingEngine`, `ExecutionEngine`, `RiskEngine`, `LLMProvider`) mean that any backend can be swapped without changing strategy logic. The `BackendRegistry` is config-driven — adding a new exchange or DEX is a config change, not a code change. The DeFi integration (DexExecutor, IntentExecutor, BridgeClient) already provides multi-venue capability. The `StrategyGeneticist` can evolve strategies via genome mutation to adapt to new structures.

**Prevention confidence:** 70%

### Gap Analysis
| Capability | Status |
|---|---|
| Abstract interface layer | ✅ Strong |
| Config-driven backend swap | ✅ Strong |
| DeFi multi-venue | ✅ Present |
| Strategy genome evolution | ✅ Present |
| Proactive structure monitoring | ⚠️ Partial — reactive, not predictive |
| Legacy backend deprecation | ⚠️ No automated migration path |

---

## Y4. Exchange Failure

**Timeframe:** Yearly (days to permanent)
**Frequency:** 1-2× per decade (Mt. Gox, FTX, QuadrigaCX)

### What happens (step by step)
1. Exchange becomes insolvent, hacked, or shut down by regulators
2. All funds on the exchange are frozen or lost
3. Open positions can't be closed
4. Stop losses on the exchange are meaningless (exchange is gone)
5. Recovery takes months to years (if partial recovery is possible)
6. Capital permanently lost if exchange is fully insolvent

### What it costs
- **Money:** 100% of exchange-held capital at risk. Potentially permanent loss
- **Time:** Months to years of legal proceedings for partial recovery
- **Energy:** Existential — loss of trading capital + system trust

### Why it happens
- **Counterparty risk:** Exchanges are centralized entities with single points of failure
- **Information asymmetry:** Exchange solvency is opaque to users
- **Coordination failure:** Users can't verify exchange reserves in real-time

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **Connection Monitor** | Exchange unreachable → Kill Switch in 90 seconds. First sign of trouble |
| **Watchdog Process** | Detects exchange API failures. Fires kill switch independently |
| **MandateGate** | Can restrict to specific exchanges. Can mandate exchange diversification |
| **DeFi Integration** | On-chain execution via DEXs (1inch, Jupiter). Self-custody. No exchange counterparty risk |
| **WalletManager** | Encrypted wallet storage with Fernet encryption. Funds in self-custody wallets |
| **SettlementEngine** | Smart contract escrow with multi-sig support. Trustless settlement |
| **Interface Layer** | Can swap to backup exchange via config. Backend-agnostic strategy logic |

**TSAR Blueprint Handling:** TSAR's DeFi integration is the primary defense against exchange failure — on-chain execution via DEXs eliminates exchange counterparty risk entirely. The `WalletManager` keeps funds in self-custody. The `SettlementEngine` uses smart contract escrow. For CeFi, the `ConnectionMonitor` detects exchange issues within 90 seconds and fires the kill switch. The `MandateGate` can mandate exchange diversification. The interface layer allows swapping to a backup exchange via config.

**Prevention confidence:** 55%

### Gap Analysis
| Capability | Status |
|---|---|
| Exchange outage detection | ✅ Strong |
| DeFi self-custody alternative | ✅ Present |
| Multi-exchange failover | ❌ Gap — no automated failover |
| Exchange solvency monitoring | ❌ Gap — no proof-of-reserves checking |
| Automated fund withdrawal | ❌ Gap — manual process |

---

## Y5. Stablecoin Depeg

**Timeframe:** Yearly (hours to days)
**Frequency:** 1-3× per decade (UST/Luna, USDC Silicon Valley Bank)

### What happens (step by step)
1. Major stablecoin (USDT or USDC) breaks its $1.00 peg
2. Drops to $0.90, then $0.80, then potentially $0.10 (UST scenario)
3. All price pairs denominated in the depegged stablecoin are wrong
4. "BTC/USDT at $60,000" is actually "$60,000 × $0.80 = $48,000 real value"
5. Stop losses trigger at nominal prices but real losses are 20%+
6. Exchange liquidity evaporates as everyone tries to exit the stablecoin

### What it costs
- **Money:** 20-90% loss on stablecoin holdings. All USDT-denominated positions lose real value
- **Time:** Hours of chaos. Days to weeks of recovery
- **Energy:** Systemic — affects the entire crypto ecosystem

### Why it happens
- **Counterparty risk:** Stablecoins are backed by reserves that may not be fully transparent
- **Information asymmetry:** Reserve composition is opaque. Users trust but can't verify
- **Coordination failure:** Bank-run dynamics — everyone exits simultaneously

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **CorrelationAnalyzer** | Detects USDT/USDC breaking peg via correlation anomaly (z-score > 2.0) |
| **Price Feed Validation** | Cross-reference prices across multiple sources. Depeg shows as price divergence |
| **RegimeDetector** | Peg break → HIGH_VOLATILITY regime → all risk parameters tighten |
| **Kill Switch** | If depeg causes >2% loss, system halts. Nuclear option |
| **DeFi Integration** | Can trade on-chain with verifiable collateral. Self-custody reduces exchange stablecoin risk |
| **Multi-Stablecoin Awareness** | (Future) System can diversify stablecoin exposure across USDT, USDC, DAI |
| **Manual Override** | Telegram /stop for immediate human response to depeg event |

**TSAR Blueprint Handling:** The `CorrelationAnalyzer` can detect peg breaks by monitoring USDT/USDC price divergence from $1.00. The `RegimeDetector` shifts to HIGH_VOLATILITY when a depeg is detected. The `KillSwitch` activates if losses exceed thresholds. The DeFi integration provides an alternative — on-chain trading with verifiable collateral and self-custody. The `InformationAgent` and `SentimentAgent` monitor for depeg news.

**Prevention confidence:** 55%

### Gap Analysis
| Capability | Status |
|---|---|
| Price divergence detection | ✅ Present |
| Regime shift on depeg | ✅ Present |
| Emergency halt capability | ✅ Strong |
| Multi-stablecoin diversification | ❌ Gap — single stablecoin per exchange |
| Automated depeg response | ⚠️ Partial — detection exists, automated response is limited |
| DeFi verifiable collateral | ✅ Present |

---

## Y6. Halving Cycle

**Timeframe:** Yearly (months)
**Frequency:** Every ~4 years (2020, 2024, 2028)

### What happens (step by step)
1. Bitcoin halving reduces block reward by 50%
2. Supply shock: fewer new BTC entering market
3. Historical pattern: price rallies 12-18 months post-halving, then crashes 70-80%
4. Strategies optimized for the rally phase fail during the crash
5. Market correlations shift as halving effects propagate to altcoins
6. Post-crash: prolonged bear market (12-24 months) with different dynamics

### What it costs
- **Money:** If caught in post-halving crash: -50% to -80% on BTC positions. Altcoins worse
- **Time:** 12-24 months of bear market. Strategies optimized for bull market underperform
- **Energy:** Psychological — "it always recovers" hope during extended drawdown

### Why it happens
- **Supply mechanics:** Halving is a predictable supply shock, but market response timing is uncertain
- **Information asymmetry:** Everyone knows about the halving; the timing of the crash is the information edge
- **Coordination failure:** Crowd behavior amplifies both the rally and the crash

### How TSAR prevents it

| Component | Mechanism |
|-----------|-----------|
| **MacroAgent** | Halving-aware market context. Knows halving dates and historical patterns |
| **RegimeDetector** | Detects regime transitions during halving cycle (bull → distribution → bear) |
| **Strategy Retirement Gates** | Strategies that underperform during regime change get retired |
| **Drawdown Circuit Breaker** | Progressive protection during crash: GREEN → YELLOW → ORANGE → RED |
| **Kill Switch** | -3% daily or -5% drawdown → halt. Prevents catastrophic losses during crash |
| **Flywheel Adaptation** | System learns from each halving cycle. Pattern library captures halving-specific patterns |
| **SentimentAgent** | Extreme greed (>75) during halving rally = contrarian caution signal |
| **Factor Library** | Halving-specific factors (supply reduction rate, miner revenue, hash rate) can be added |

**TSAR Blueprint Handling:** The `MacroAgent` is halving-aware — it tracks halving dates and historical patterns. The `RegimeDetector` identifies the transition from bull to distribution to bear market. The `SentimentAgent` treats extreme greed as a contrarian signal during halving rallies. The `FlywheelOrchestrator` captures halving-specific patterns in the PatternLibrary. The `StrategyGeneticist` retires strategies that don't adapt to the new regime. The `DrawdownMonitor` and `KillSwitch` provide catastrophic loss protection during the crash phase.

**Prevention confidence:** 65%

### Gap Analysis
| Capability | Status |
|---|---|
| Halving-aware macro context | ✅ Present |
| Regime detection during transition | ✅ Present |
| Contrarian sentiment signal | ✅ Present |
| Bear market strategy rotation | ⚠️ Partial — can retire, no auto-rotation |
| Halving-specific factors | ⚠️ Partial — can be added, not pre-loaded |
| Prolonged bear market adaptation | ⚠️ System designed for active trading, may struggle in 12-month low-volatility bear |

---

# PREVENTION ARCHITECTURE

## Component → Scenario Coverage Matrix

| TSAR Component | D1 | D2 | D3 | D4 | D5 | D6 | D7 | W1 | W2 | W3 | W4 | W5 | W6 | M1 | M2 | M3 | M4 | M5 | M6 | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Kill Switch** | ✅ | | ✅ | | | ✅ | ✅ | | | ✅ | | | | ✅ | | ✅ | | | | ✅ | | | ✅ | ✅ | ✅ |
| **Drawdown Monitor** | ✅ | | | | | | | | | | | | | ✅ | | ✅ | | | | ✅ | | | | | ✅ |
| **Connection Monitor** | ✅ | | | | | ✅ | ✅ | | | | | | | | | | | | | ✅ | | | ✅ | | |
| **Watchdog** | ✅ | | | | | ✅ | ✅ | | | | | | | | | | | | | ✅ | | | ✅ | | |
| **RegimeDetector** | ✅ | | ✅ | | | | | ✅ | ✅ | | | ✅ | | | | ✅ | | | | | | ✅ | | | ✅ |
| **SentimentAgent** | | | ✅ | | | | | | | | | ✅ | ✅ | | | | | | | ✅ | | | | ✅ | ✅ |
| **MacroAgent** | | | ✅ | | | | | | | ✅ | | | ✅ | | | | | | | ✅ | ✅ | ✅ | | | ✅ |
| **Smart Order Router** | ✅ | ✅ | ✅ | ✅ | ✅ | | | | | | | | | | | | | | | | | | | | |
| **Spread Analysis** | ✅ | ✅ | ✅ | ✅ | | | | | | ✅ | | | | | | | | | | | | | | | |
| **SignalScout** | | | | | | | | ✅ | | | ✅ | ✅ | | | | | | ✅ | | | | | | | |
| **RiskGuardian** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | ✅ | ✅ | | ✅ | ✅ | ✅ |
| **PositionSizer** | | | | | ✅ | | | | | | | | ✅ | | | | ✅ | | | | | | | | |
| **Flywheel** | | | | | | | | ✅ | | | | ✅ | | ✅ | ✅ | | | ✅ | ✅ | | | | | | ✅ |
| **MandateGate** | | | | | | | | | | | ✅ | | | | | | | | | ✅ | ✅ | ✅ | ✅ | | |
| **BackendRegistry** | | | | | | | | | | | | | | | | | | | | | ✅ | ✅ | ✅ | | |
| **DeFi Integration** | | | | | | | | | | | | | | | | | | | | | | ✅ | ✅ | ✅ | |
| **PatternLibrary** | | ✅ | | | | | | ✅ | | | | ✅ | | | ✅ | | | ✅ | | | | | | | |
| **CorrelationAnalyzer** | | | | | | | | | ✅ | | | | | | | ✅ | | | | | | | | ✅ | |
| **Gated Recovery** | ✅ | | ✅ | | | | | | | | | | | ✅ | | | | | | ✅ | | | | | ✅ |
| **Anti-Behavioral Guards** | | | | | | | | | | | ✅ | | | ✅ | | | | | | | | | | | |

## Timeframe Defense Depth

| Timeframe | Scenarios | Avg Confidence | Strongest Defense | Weakest Defense |
|---|---|---|---|---|
| **Daily** (7) | Infrastructure failures | 84% | Kill switch + Watchdog | Stop hunt (75%) |
| **Weekly** (6) | Strategy/edge failures | 75% | Conflict prevention (95%) | Funding rate (65%) |
| **Monthly** (6) | Portfolio/knowledge decay | 75% | Drawdown circuit breaker (90%) | Model drift (65%) |
| **Yearly** (6) | Existential threats | 60% | Interface layer abstraction (70%) | Exchange failure (55%) |

## Superagent Blueprint Response Map

**How TSAR's superagent blueprint handles each timeframe:**

### Daily — Infrastructure Resilience
The Rust performance layer (`ws-manager`, `tick-processor`, `order-executor`) provides sub-second infrastructure resilience. The `ConnectionMonitor` + `Watchdog` + `KillSwitch` trio ensures that any infrastructure failure triggers automatic halt within 90 seconds. Pre-placed exchange-side stops provide protection even when TSAR is offline.

### Weekly — Strategy Robustness
The `FlywheelOrchestrator` drives continuous strategy improvement. The `RegimeDetector` adapts to market regime changes. The `StrategyGeneticist` evaluates and retires underperforming strategies. The `CorrelationAnalyzer` monitors for correlation breakdowns. The 7-layer veto protocol prevents strategy conflicts.

### Monthly — Portfolio Integrity
The `DrawdownMonitor` provides progressive circuit breaker protection. The `MarketCartographer` maintains portfolio-level correlation awareness. The `PositionSizer` enforces Kelly-optimal allocation. The knowledge stores (`PatternLibrary`, `LessonArchive`, `KnowledgeGraph`) maintain freshness through continuous flywheel learning.

### Yearly — Existential Survival
The interface layer provides abstraction that enables adaptation to structural market changes. The DeFi integration provides exchange-independent execution. The `MandateGate` provides instant regulatory response capability. The `BackendRegistry` enables venue diversification. The `KillSwitch` + `Watchdog` provide catastrophic event response.

---

## SCORING RATIONALE

### Why 8/10 (not higher)

| Deduction | Reason | Impact |
|---|---|---|
| -0.5 | Black swan response (Y1) is largely reactive/manual. No automated cross-exchange recovery | 60% confidence |
| -0.3 | Exchange failure (Y4) has no automated failover. Single exchange dependency | 55% confidence |
| -0.2 | Model drift (M2) relies on periodic evaluation, not real-time per-trade detection | 65% confidence |
| -0.2 | Stablecoin depeg (Y5) has detection but limited automated response | 55% confidence |
| -0.2 | Funding rate (W6) monitoring exists but no automated funding-aware exits | 65% confidence |
| -0.2 | Edge competition (W5) / strategy crowding detection absent | 75% confidence |
| -0.2 | Correlation break (W2) detection exists but no automated hedging response | 70% confidence |
| -0.2 | Stop hunt (D2) prevention inherently limited by market maker structural advantage | 75% confidence |

### Why not lower than 8

| Strength | Coverage |
|---|---|
| **25 scenarios analyzed** | 4 timeframes, comprehensive coverage |
| **Deterministic risk engine** | Zero LLM in critical path. Guards can't be "convinced" |
| **Dual-write kill switch** | File-primary survives Redis failure. Fail-safe defaults |
| **Watchdog survives process death** | Separate process monitors heartbeat. Fires kill switch independently |
| **Progressive circuit breakers** | GREEN → YELLOW → ORANGE → RED. Graduated response |
| **Gated recovery** | 5% → 10% → 25% → 50% → 100% over 24-192 hours |
| **Self-improving flywheel** | System gets better with every trade |
| **Interface layer abstraction** | Backend-agnostic. Adapts to structural changes |
| **DeFi self-custody** | Eliminates exchange counterparty risk |
| **Multi-layer defense per scenario** | No single point of failure for any scenario |

### Upgrade path to 9.0+

1. **Cross-exchange failover** (Priority 1): Automated fund distribution and failover to backup exchange
2. **Real-time model drift detection** (Priority 1): Per-trade Sharpe tracking with rolling window alerts
3. **Automated black swan response** (Priority 1): Wire sentiment/regime alerts to automatic position reduction
4. **Correlation break → position reduction** (Priority 2): When anomalies detected, auto-reduce exposure
5. **Edge competition detection** (Priority 2): Monitor order book patterns for strategy crowding
6. **Multi-stablecoin diversification** (Priority 2): Distribute stablecoin exposure across USDT/USDC/DAI
7. **Funding-aware exits** (Priority 2): Automated position closure when funding costs exceed threshold
8. **Exchange proof-of-reserves monitoring** (Priority 3): Track exchange solvency indicators
9. **Options-based tail risk hedging** (Priority 3): Defined-risk protection against black swans
10. **Anti-spoofing logic** (Priority 3): Detect fake walls in order book

---

## TSAR's Institutional Superpowers (Timeframe-Organized)

### Daily Superpowers
1. **Rust tick-processor** — sub-second spread monitoring and order book analysis
2. **Dual-write kill switch** — survives Redis failure, supports external kill, fails safe
3. **Watchdog process** — survives main process death. 30-second heartbeat detection
4. **Pre-placed exchange-side stops** — protection exists even when TSAR is offline

### Weekly Superpowers
5. **HMM regime detection** — probabilistic + deterministic dual detection
6. **7-layer veto protocol** — every signal passes through 7 sequential checks
7. **Symbol cooldown** — 30-minute per-symbol cooldown prevents rapid conflicting trades
8. **Flywheel adaptation** — TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT

### Monthly Superpowers
9. **Progressive circuit breakers** — GREEN → YELLOW → ORANGE → RED with sizing multipliers
10. **Gated recovery** — phased re-entry prevents post-halt tilt
11. **Kelly-optimal position sizing** — mathematically optimal, not emotionally driven
12. **Knowledge freshness** — pattern confidence decay + continuous flywheel learning

### Yearly Superpowers
13. **Interface layer abstraction** — backend-agnostic. Adapts to structural market changes
14. **DeFi self-custody** — eliminates exchange counterparty risk
15. **Config-driven backend swap** — new venue = config change, not code change
16. **Mandate-based authorization** — separates "can we trade?" from "should we trade?"

---

*Report prepared by the Institutional Scenario Prevention Council v2 for TSAR Superagent Architecture Review.*
*25 scenarios across 4 timeframes. Source files analyzed: 40+ Python/Rust modules across agents/, risk/, tools/, strategy/, knowledge/, rust/.*
