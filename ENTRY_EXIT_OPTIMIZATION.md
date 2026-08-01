# TSAR Entry/Exit Optimization System

**Date:** 2026-08-01
**Purpose:** Maximize win rate to 75%+ through disciplined entry, exit, and trade management
**Scope:** Signal Scout → Risk Guardian → Execution Sniper → Trade Manager (new)

---

## Entry/Exit Optimization Report
**Score: 7/10** (Current system has solid foundations but critical gaps in exit management)

### Current State Assessment

| Component | Status | Gap |
|-----------|--------|-----|
| Entry at S/R levels | ✅ Implemented | No pullback waiting logic |
| Volume confirmation | ✅ Implemented | Basic threshold only |
| ATR-based stops | ✅ Implemented | No trailing, no break-even |
| R:R enforcement | ✅ 2:1 minimum | No partial exits, no scaling |
| Multi-timeframe | ✅ Implemented | No session timing |
| Time-based exit | ⚠️ Partial | Only in mean_reversion (4h), not system-wide |
| Trailing stops | ❌ Missing | Critical gap |
| Partial exits | ❌ Missing | Critical gap |
| Session timing | ❌ Missing | Trades at any time |
| News-based exit | ❌ Missing | MarketCalendar exists but not wired to exits |
| Regime-change exit | ❌ Missing | RegimeDetector exists but not wired to exits |
| Break-even stop | ❌ Missing | After 1:1 R:R reached |
| Limit order entry | ❌ Missing | All entries are market orders |
| Pullback entry | ❌ Missing | Enters at current price, not pullback |

---

## 1. Entry Optimization Rules

### 1.1 Pullback Entry (NEW)
**Problem:** Current system enters at current price when RSI hits extreme. This often means entering at the worst price during a momentum move.

**Solution:** Wait for pullback confirmation before entering.

```
BUY Setup:
  1. RSI < 30 at support detected → MARK AS POTENTIAL ENTRY
  2. Wait for price to bounce off support (close > low by 0.3%+)
  3. Enter on the bounce candle close, not at the exact bottom
  4. This avoids "catching a falling knife"

SELL Setup:
  1. RSI > 70 at resistance detected → MARK AS POTENTIAL ENTRY
  2. Wait for price to reject from resistance (close < high by 0.3%+)
  3. Enter on the rejection candle close
```

### 1.2 Volume Confirmation (ENHANCED)
**Problem:** Current check is binary (volume > 1.5x avg). No progressive scoring.

**Solution:** Graduated volume scoring with confirmation window.

```
Volume Score Ladder:
  - < 0.8x avg: REJECT (no conviction)
  - 0.8-1.0x avg: 0.0 score (weak)
  - 1.0-1.5x avg: 0.3 score (moderate)
  - 1.5-2.0x avg: 0.6 score (good)
  - 2.0-3.0x avg: 0.8 score (strong)
  - > 3.0x avg: 1.0 score (institutional)

Confirmation: Volume must be above average for 2+ consecutive candles
```

### 1.3 Session-Aware Entry (NEW)
**Problem:** System enters trades during low-liquidity Asian session, getting poor fills and wide spreads.

**Solution:** Session timing gates.

```
ENTRY WINDOWS (UTC):
  ✅ London Open:     07:00-10:00 (high liquidity, trend starts)
  ✅ London-NY Overlap: 13:00-17:00 (BEST — highest liquidity)
  ✅ NY Session:      13:00-21:00 (high volume, clear trends)
  ⚠️ Asian Session:   00:00-07:00 (AVOID — low liquidity, wide spreads)
  ⚠️ Session Transition: 07:00-08:00, 21:00-00:00 (uncertain direction)

BEST DAYS:
  ✅ Tuesday-Thursday: Cleanest trends, highest win rates
  ⚠️ Monday: Choppy (weekend gap fills, position squaring)
  ⚠️ Friday: Unpredictable (weekend risk, position unwinding)
```

### 1.4 News Blackout (NEW)
**Problem:** System enters trades right before high-impact news, getting whipsawed.

**Solution:** News event proximity gate using MarketCalendar.

```
NEWS BLACKOUT RULES:
  - CRITICAL event within 2h: NO NEW ENTRIES
  - HIGH event within 1h: NO NEW ENTRIES
  - MEDIUM event within 30min: REDUCE SIZE by 50%
  - After news release: Wait 15min for dust to settle
```

### 1.5 Limit Order Entry (NEW)
**Problem:** All entries are market orders, getting poor fills during volatile moves.

**Solution:** Use limit orders at calculated entry levels.

```
LIMIT ORDER LOGIC:
  - BUY: Place limit at (current_price - 0.1%) for slight discount
  - SELL: Place limit at (current_price + 0.1%) for slight premium
  - If not filled within 5 minutes: Cancel and reassess
  - Fallback: Market order if signal score > 0.85 (high conviction)
```

---

## 2. Exit Optimization Rules

### 2.1 Trailing Stop System (NEW — Critical Gap)
**Problem:** Current system uses fixed stop-loss. Profits evaporate on reversals.

**Solution:** Multi-stage trailing stop.

```
TRAILING STOP STAGES:

Stage 1: Initial Stop (ATR-based)
  - BUY: stop = entry - (1.5 × ATR)
  - SELL: stop = entry + (1.5 × ATR)

Stage 2: Break-Even Stop (after 1:1 R:R reached)
  - Move stop to entry + fees (break-even)
  - This locks in zero loss on the trade

Stage 3: Trailing Stop (after 1.5:1 R:R reached)
  - Trail stop at 1.0 × ATR behind current price
  - Only move stop in profitable direction (never back)
  - Recalculate on each new candle close

Stage 4: Tight Trail (after 2:1 R:R reached)
  - Tighten trail to 0.75 × ATR behind current price
  - Lock in more profit as trade extends

STOP MOVEMENT RULES:
  ✅ Move stop closer to price (tighten)
  ✅ Move stop to break-even
  ❌ NEVER move stop further away from price
  ❌ NEVER remove stop-loss
```

### 2.2 Partial Exit System (NEW — Critical Gap)
**Problem:** Current system is all-or-nothing. Misses profit on extended moves.

**Solution:** Scale out at predetermined levels.

```
PARTIAL EXIT SCHEDULE:

Position: 100% at entry

Exit 1: 40% at 1:1 R:R (resistance level or ATR-based)
  - Locks in profit on nearly half the position
  - Reduces risk exposure immediately

Exit 2: 30% at 2:1 R:R (next resistance or ATR×2)
  - Takes profit on majority of remaining position
  - Already in "free trade" territory

Exit 3: 30% trailing stop (let it run)
  - Uses trailing stop from Section 2.1
  - Targets 3:1+ R:R on remaining position
  - This is where big wins come from

AFTER PARTIAL EXIT:
  - Move stop to break-even on remaining position
  - Update trailing stop calculations for remaining size
```

### 2.3 Time-Based Exit (ENHANCED)
**Problem:** Only mean_reversion has a 4h time stop. Other strategies have none.

**Solution:** Strategy-aware time stops.

```
TIME STOP RULES:

Mean Reversion:
  - Close after 4h if neither TP nor SL hit
  - Rationale: MR trades should resolve quickly

Momentum:
  - Close after 24h if trade hasn't moved 1% in profit
  - Rationale: Momentum needs follow-through

General:
  - Close after 8h if P&L is between -0.5% and +0.5%
  - Rationale: Stale trades tie up capital

STALE TRADE DETECTION:
  - If price hasn't moved > 0.3% in 2 hours: ALERT
  - If price hasn't moved > 0.5% in 4 hours: CLOSE
  - Capital is better deployed elsewhere
```

### 2.4 Regime-Change Exit (NEW)
**Problem:** RegimeDetector identifies regime changes but doesn't trigger exits.

**Solution:** Wire regime changes to position management.

```
REGIME EXIT RULES:

If regime shifts from TRENDING → RANGING:
  - Close all momentum positions
  - Keep mean reversion positions
  - Tighten stops on all remaining

If regime shifts from RANGING → TRENDING:
  - Close all mean reversion positions (they expect range)
  - Open momentum positions in trend direction
  - Widen stops slightly for trend trades

If regime shifts to HIGH_VOLATILITY:
  - Reduce all position sizes by 50%
  - Tighten all stops by 25%
  - No new entries until volatility subsides

If regime shifts to CRISIS:
  - Close ALL positions immediately
  - No new entries
  - Wait for regime stabilization
```

### 2.5 News-Based Exit (NEW)
**Problem:** MarketCalendar tracks events but doesn't trigger exits.

**Solution:** Pre-news exit protocol.

```
NEWS EXIT RULES:

30 minutes before CRITICAL event:
  - Close all positions with < 1:1 R:R unrealized
  - Tighten stops on profitable positions to break-even

15 minutes before HIGH event:
  - Move all stops to break-even
  - No new entries

During event:
  - Do NOT close positions (let stops work)
  - Spreads will be wide, execution poor

After event (15 min cooldown):
  - Reassess all positions
  - Re-enter if setup still valid
```

---

## 3. Stop Loss Optimization

### 3.1 ATR-Adaptive Stops (ENHANCED)
```
ATR MULTIPLIER BY VOLATILITY REGIME:

Low Volatility (ATR < 0.5% of price):
  - Stop = 1.0 × ATR (tighter stops, tighter ranges)

Normal Volatility (ATR 0.5-1.5% of price):
  - Stop = 1.5 × ATR (standard)

High Volatility (ATR 1.5-3.0% of price):
  - Stop = 2.0 × ATR (wider stops for noise)

Extreme Volatility (ATR > 3.0% of price):
  - Stop = 2.5 × ATR (very wide, or DON'T TRADE)
```

### 3.2 Structure-Based Stops (ENHANCED)
```
SUPPORT/RESISTANCE STOPS:

BUY: Stop below nearest support with buffer
  - Buffer = 0.1% below support (avoid stop hunts)
  - If support is > 2% away: Use ATR stop instead

SELL: Stop above nearest resistance with buffer
  - Buffer = 0.1% above resistance
  - If resistance is > 2% away: Use ATR stop instead

MULTIPLE SUPPORT LEVELS:
  - If multiple supports within 1%: Stop below lowest
  - If supports are spread out: Stop below nearest
```

### 3.3 Break-Even Stop (NEW)
```
BREAK-EVEN TRIGGER:
  - When unrealized P&L reaches 1:1 R:R
  - Move stop to entry price + estimated fees (0.1%)
  - This makes the trade "risk-free"

IMPLEMENTATION:
  - Monitor price on each candle close
  - If (current_price - entry_price) >= (entry_price - stop_loss):
    → Move stop to entry_price * 1.001 (for BUY)
    → Move stop to entry_price * 0.999 (for SELL)
```

---

## 4. R:R Ratio Optimization

### 4.1 Minimum R:R Enforcement
```
R:R TIERS:

Tier 1 (Minimum): 2:1
  - All trades MUST meet this
  - Risk Guardian already enforces this

Tier 2 (Preferred): 3:1
  - Signal score > 0.75 → Target 3:1
  - Use resistance-based TP if available

Tier 3 (High Conviction): 4:1+
  - Signal score > 0.85 AND multi-TF confluence > 0.8
  - Use scaled TP: 40% at 2:1, 30% at 3:1, 30% trailing

POSITION SIZING BY R:R:
  - 2:1 R:R → Full position size (2% risk)
  - 3:1 R:R → Full position size (2% risk)
  - 4:1+ R:R → 1.5x position size (3% risk) — higher conviction
```

### 4.2 Fee-Adjusted R:R (ENHANCED)
```
NET R:R CALCULATION:
  gross_risk = |entry - stop|
  gross_reward = |tp - entry|
  total_fees = entry × fee_rate × 2  (entry + exit)
  net_reward = gross_reward - total_fees
  net_rr = net_reward / gross_risk

MINIMUM NET R:R: 1.5:1 (after fees)
  - If net_rr < 1.5: REJECT trade
  - This accounts for real trading costs
```

---

## 5. Session Timing Optimization

### 5.1 Session Map (Crypto — 24/7 Market)
```
SESSION SCHEDULE (UTC):

Asian Session:    00:00 - 07:00
  - Low liquidity, wide spreads
  - Avoid entries unless breakout confirmed
  - Best for: Range-bound scalps only

London Session:   07:00 - 16:00
  - High liquidity, institutional flow
  - Best for: Trend entries, breakout trades
  - Peak: 08:00 - 10:00 (London open momentum)

NY Session:       13:00 - 22:00
  - Highest volume, clearest trends
  - Best for: All strategies
  - Peak: 14:00 - 16:00 (NY open momentum)

London-NY Overlap: 13:00 - 16:00
  - BEST WINDOW: Highest liquidity, tightest spreads
  - Ideal for: All entries, especially momentum

Dead Zone:        22:00 - 00:00
  - Session transition, low conviction
  - Avoid new entries
```

### 5.2 Day-of-Week Optimization
```
BEST DAYS FOR TRADING:

Tuesday:    ✅ Best day — trends establish after Monday positioning
Wednesday:  ✅ Good — mid-week, no major distortions
Thursday:   ✅ Good — pre-Friday positioning

CAUTION DAYS:

Monday:     ⚠️ Choppy — weekend gap fills, position squaring
            → Reduce position size by 25%
            → Prefer mean reversion over momentum

Friday:     ⚠️ Unpredictable — weekend risk, position unwinding
            → Close all positions by 20:00 UTC
            → No new entries after 16:00 UTC
            → Weekend gaps can be 2-5% in crypto
```

---

## 6. Trade Management Rules

### 6.1 Active Monitoring Protocol
```
FIRST 30 MINUTES:
  - Monitor for immediate adverse moves
  - If price moves against by 0.5% in first 5 min: ALERT
  - If price moves against by 1.0% in first 15 min: CONSIDER EXIT
  - Don't panic — let the stop work

ONGOING MONITORING:
  - Check position every 30 minutes (automated)
  - Set alerts at: 50% of TP, 75% of TP, break-even trigger
  - Log all significant price movements
```

### 6.2 Non-Interference Rule
```
GOLDEN RULE: Set stop and target, then LET THEM WORK

DO:
  ✅ Move stop to break-even when triggered
  ✅ Take partial profits at predetermined levels
  ✅ Exit on regime change or news event

DON'T:
  ❌ Move stop further away ("it'll come back")
  ❌ Close early out of fear ("it might reverse")
  ❌ Add to losing positions ("averaging down")
  ❌ Remove stop-loss ("I'll watch it manually")
```

### 6.3 Pre-Trade Checklist
```
BEFORE EVERY ENTRY, VERIFY:

□ 1. Is this a valid session? (Not Asian, not dead zone)
□ 2. Is there news within 2h? (Check MarketCalendar)
□ 3. Is the regime favorable? (Check RegimeDetector)
□ 4. Is R:R ≥ 2:1 after fees? (Check FeeCalculator)
□ 5. Is stop-loss at structure? (Not arbitrary %)
□ 6. Is position size correct? (Half-Kelly, max 15%)
□ 7. Do I have an exit plan? (Partial exits, trailing stop)
□ 8. Is this a high-conviction setup? (Score > 0.7)

If ANY answer is NO → Do not enter.
```

---

## 7. Implementation Architecture

### 7.1 New Component: Trade Manager Agent
```
Pipeline Position:
  Signal Scout → Risk Guardian → Execution Sniper → TRADE MANAGER (NEW)

Trade Manager Responsibilities:
  - Monitor all open positions
  - Execute trailing stop logic
  - Execute partial exit schedule
  - Monitor regime changes → trigger exits
  - Monitor news events → trigger exits
  - Monitor time stops → trigger exits
  - Move stops to break-even
  - Log all trade management actions

Subscribes to: trades, regime, news, positions
Publishes to: trade_actions (exit, partial_exit, stop_update)
```

### 7.2 Integration Points
```
EXISTING COMPONENTS TO WIRE:

1. MarketCalendar → Trade Manager
   - Feed event proximity to position monitor
   - Trigger pre-news exits

2. RegimeDetector → Trade Manager
   - Feed regime changes to position monitor
   - Trigger regime-change exits

3. News Aggregator → Trade Manager
   - Feed breaking news sentiment
   - Trigger sentiment-based exits

4. StopLossCalculator → Trade Manager
   - Use for trailing stop calculations
   - Use for break-even calculations

5. TakeProfitCalculator → Trade Manager
   - Use for partial exit level calculations
   - Use for scaled TP management
```

---

## 8. Expected Impact

### Win Rate Projection
```
Current System (estimated): ~55-60% win rate

With Entry Optimization:
  + Pullback entries: +3-5% (better entry prices)
  + Session timing: +2-3% (better liquidity, fewer false signals)
  + News blackout: +2-3% (avoid whipsaws)
  + Volume confirmation: +1-2% (filter weak signals)

With Exit Optimization:
  + Trailing stops: +5-8% (capture more profit on winners)
  + Partial exits: +3-5% (lock in profits, reduce losers)
  + Time stops: +2-3% (free capital from stale trades)
  + Regime exits: +2-3% (close before regime reversals)

PROJECTED WIN RATE: 72-80%
  - Conservative estimate: 72%
  - Base case: 75%
  - Optimistic: 80%
```

### R:R Improvement
```
Current: Fixed 2:1 R:R (win 2%, lose 1%)

With Partial Exits + Trailing:
  - 40% of position exits at 1:1 (lock profit)
  - 30% of position exits at 2:1 (good profit)
  - 30% of position trails to 3:1+ (big wins)

EFFECTIVE R:R: 2.5:1 to 3.5:1
  - This means even at 60% win rate, system is profitable
  - At 75% win rate with 3:1 R:R → exceptional returns
```

---

## 9. Risk Considerations

### Over-Optimization Risk
- Too many filters = missed trades
- Balance: 75% win rate target, not 90%
- Accept that some losing trades are normal

### Execution Complexity
- More moving parts = more failure modes
- Mitigation: Deterministic logic, no LLM in trade management
- All trade management rules are hard-coded, not heuristic

### Market Regime Sensitivity
- Rules optimized for trending/ranging markets
- Crisis regime needs special handling (close all)
- Backtest across all regimes before deploying

---

## 10. Scoring Summary

| Category | Score | Notes |
|----------|-------|-------|
| Entry Rules | 7/10 | Solid S/R logic, needs pullback + session timing |
| Exit Rules | 5/10 | Critical gaps: no trailing, no partial exits |
| Stop Loss | 6/10 | ATR-based is good, needs trailing + break-even |
| R:R Optimization | 7/10 | 2:1 enforced, needs partial exits for scaling |
| Session Timing | 3/10 | Not implemented at all |
| Trade Management | 4/10 | Basic time stop only, needs full management |

**Overall Score: 7/10** — Strong foundation, critical gaps in exit management.

**Priority Improvements:**
1. 🔴 Trailing stops (biggest impact on win rate)
2. 🔴 Partial exits (biggest impact on R:R)
3. 🟡 Session timing (easy win, significant impact)
4. 🟡 News blackout (already have MarketCalendar)
5. 🟢 Pullback entries (nice to have, moderate impact)
6. 🟢 Regime exits (already have RegimeDetector)
