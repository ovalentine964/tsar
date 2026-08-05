# TSAR × TSAR Integration Analysis

**Date:** 2026-08-05  
**Strategy:** Valentine Money Printing Machine (TSAR)  
**Status:** ANALYSIS COMPLETE — Ready for Implementation Planning

---

## Executive Summary

TSAR is a **multi-layer discretionary-style institutional trading system** that follows a strict hierarchy: Fundamental Bias → Trend Direction → S/R Mapping → Price Retest → RSI Confirmation → Candlestick Confirmation → Execution → Trade Management.

TSAR already has **~70% of the infrastructure** needed to implement TSAR. The remaining 30% requires new session awareness logic, enhanced multi-timeframe trend analysis with MA crossovers, Asian session level mapping, order block detection, and a TSAR-specific orchestration pipeline.

**Integration Verdict: HIGHLY COMPATIBLE** — TSAR's layered confirmation system maps naturally onto TSAR's agent pipeline architecture.

---

## 1. TSAR Strategy Evaluation

### Strengths

| # | Strength | Why It Matters |
|---|----------|---------------|
| 1 | **Layered confirmation (7 layers)** | Each layer filters false signals. By the time you execute, probability is stacked heavily in your favor. This is how institutional desks operate. |
| 2 | **Fundamental bias first** | Starting with macro context prevents trading against the dominant force. Most retail strategies skip this entirely. |
| 3 | **Multi-timeframe alignment** | D1→H4→H1 hierarchy ensures you're trading with the macro trend, not against it. Reduces whipsaw losses. |
| 4 | **Session awareness** | Different sessions have different liquidity profiles. Trading London/NY overlap vs Asian session is a significant edge. |
| 5 | **Order block identification** | Order blocks (last opposing candle before BOS) represent institutional supply/demand zones. These are higher-quality S/R than arbitrary horizontal levels. |
| 6 | **RSI as confirmation (not trigger)** | Using RSI to confirm a retest at S/R, rather than as a standalone signal, is significantly more reliable. |
| 7 | **Candlestick confirmation** | Final visual confirmation before execution adds a discretionary layer that catches what pure rules miss. |
| 8 | **Defined process** | The step-by-step hierarchy removes emotional decision-making. Every trade follows the same checklist. |

### Weaknesses

| # | Weakness | Risk | Mitigation |
|---|----------|------|------------|
| 1 | **High signal rejection rate** | 7 layers of confirmation means 80-90% of potential setups get filtered out. Fewer trades = longer edge validation. | Run parallel across multiple pairs to increase trade frequency. |
| 2 | **Subjectivity in candlestick confirmation** | "Candlestick confirmation" is discretionary — different traders see different patterns. | Codify specific patterns (engulfing, pin bar, morning star) with quantitative rules. |
| 3 | **Order block subjectivity** | Identifying "last bearish candle before bullish BOS" requires defining BOS precisely. | Use swing high/low breaks with ATR-filtered minimum displacement. |
| 4 | **Session dependency** | Strategy is optimized for forex sessions (Kenyan time). Crypto is 24/7 — session dynamics differ. | Adapt session windows for crypto: use volume-weighted session periods instead of clock-based. |
| 5 | **Fundamental data latency** | Economic calendar data for crypto is sparse compared to forex. CPI, NFP don't directly move BTC. | Map crypto-specific fundamentals: BTC dominance, funding rates, exchange flows, whale activity. |
| 6 | **No explicit position sizing** | Strategy defines entries but not how much to risk per trade. | Layer TSAR's risk engine (Half-Kelly, max 2% per trade). |
| 7 | **Potential for over-fitting** | 7 parameters to tune = risk of curve-fitting to historical data. | Walk-forward validation, out-of-sample testing. |
| 8 | **Slow feedback loop** | Fewer trades = slower learning cycle for the flywheel. | Shadow account extracts rules even from rejected setups. |

### Overall Assessment: **8.5/10**

TSAR is a well-structured institutional-grade strategy. Its layered confirmation system is its greatest strength — each layer independently filters noise. The main risk is signal scarcity, which TSAR's multi-pair scanning and flywheel can mitigate.

---

## 2. TSAR Agent Mapping for TSAR

### TSAR Layer → TSAR Agent Mapping

```
TSAR LAYER                    TSAR AGENT(S)                    STATUS
─────────────────────────────────────────────────────────────────────────
1. Fundamental Bias      →    FundamentalScorer + NewsGatekeeper    ✅ EXISTS
2. Trend Direction       →    RegimeDetector + SignalScout          ✅ EXISTS (needs enhancement)
3. S/R Mapping           →    MarketCartographer + SignalScout       ✅ EXISTS (needs enhancement)
4. Price Retest          →    SignalScout (pullback logic)           ⚠️ PARTIAL
5. RSI Confirmation      →    SignalScout (RSI factor)               ✅ EXISTS
6. Candlestick Confirm   →    SignalScout + PatternRecognition       ✅ EXISTS (needs TSAR patterns)
7. Execution             →    ExecutionSniper + RiskGuardian         ✅ EXISTS
8. Trade Management      →    TradeManager                           ✅ EXISTS (needs trailing/partial)
```

### New/Enhanced Components Needed

| Component | Type | Purpose |
|-----------|------|---------|
| **VMPSessionManager** | NEW tool | Session awareness (Sydney/Tokyo/London/NY windows, session-specific behavior) |
| **TSARTrendAnalyzer** | Enhancement to MultiTimeframeAnalyzer | 50 MA / 200 MA crossover + HH/HL/LH/LL structure on D1/H4/H1 |
| **VMPOrderBlockDetector** | NEW tool or Enhancement to PatternRecognition | Identify order blocks (last opposing candle before BOS) |
| **TSARAsianLevelMapper** | NEW tool or Enhancement to MarketCartographer | Track Asian session high/low as S/R levels |
| **TSARCandlestickValidator** | Enhancement to PatternRecognition | TSAR-specific candlestick patterns (engulfing, pin bar at S/R) |
| **TSAROrchestrator** | NEW agent or Enhancement to Orchestrator | Wire all TSAR layers in correct hierarchy |

---

## 3. Session Awareness Implementation

### 3.1 TSAR Session Windows (Kenyan Time → UTC)

TSAR uses Kenyan time (EAT, UTC+3). Converting to UTC:

| Session | Kenyan (EAT) | UTC | Characteristics |
|---------|-------------|-----|-----------------|
| Sydney | 00:00-08:00 | 21:00-05:00 | Low liquidity, range-bound |
| Tokyo | 02:00-11:00 | 23:00-08:00 | Moderate, JPY pairs active |
| London | 11:00-19:00 | 08:00-16:00 | High liquidity, trend initiation |
| New York | 16:00-24:00 | 13:00-21:00 | Highest volume, trend continuation |
| **London-NY Overlap** | **16:00-19:00** | **13:00-16:00** | **BEST WINDOW — Maximum liquidity** |

### 3.2 Crypto Adaptation

Crypto trades 24/7, but volume patterns still follow traditional sessions:

| Crypto Session | UTC | Volume Profile | TSAR Application |
|---------------|-----|---------------|------------------|
| Asia Session | 00:00-08:00 UTC | Low-Medium | Map Asian High/Low as S/R levels |
| London Session | 08:00-16:00 UTC | High | Primary trend trading window |
| US Session | 13:00-21:00 UTC | Highest | Best entries, highest conviction |
| Dead Zone | 21:00-00:00 UTC | Low | Avoid new entries |

### 3.3 Implementation in TSAR

**File:** `src/tools/session_manager.py` (NEW)

```python
"""
TSAR Session Manager — Track trading sessions and session-specific levels.

Tracks:
  - Current active session(s)
  - Asian session high/low (resets daily)
  - Session-specific liquidity profiles
  - Session transition alerts
  - Best entry windows per TSAR rules
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC, time as dt_time
from enum import Enum

class TradingSession(Enum):
    SYDNEY = "sydney"
    TOKYO = "tokyo"
    LONDON = "london"
    NEW_YORK = "new_york"
    DEAD_ZONE = "dead_zone"

@dataclass
class SessionState:
    current_session: TradingSession
    is_overlap: bool  # London-NY overlap = best window
    asian_high: float = 0.0
    asian_low: float = 0.0
    session_volume_profile: str = "normal"  # low, normal, high, extreme
    allows_new_entries: bool = True
    entry_conviction_multiplier: float = 1.0

class VMPSessionManager:
    """Session awareness for TSAR strategy."""
    
    # Session windows in UTC
    SESSIONS = {
        TradingSession.SYDNEY: (dt_time(21, 0), dt_time(5, 0)),
        TradingSession.TOKYO: (dt_time(23, 0), dt_time(8, 0)),
        TradingSession.LONDON: (dt_time(8, 0), dt_time(16, 0)),
        TradingSession.NEW_YORK: (dt_time(13, 0), dt_time(21, 0)),
    }
    
    # Entry conviction multipliers by session
    CONVICTION = {
        TradingSession.SYDNEY: 0.5,      # Low liquidity = low conviction
        TradingSession.TOKYO: 0.7,       # Moderate
        TradingSession.LONDON: 0.9,      # High
        TradingSession.NEW_YORK: 1.0,    # Highest
        TradingSession.DEAD_ZONE: 0.0,   # No entries
    }
    
    def get_state(self, symbol: str) -> SessionState:
        """Get current session state with Asian levels."""
        now = datetime.now(UTC).time()
        session = self._identify_session(now)
        is_overlap = self._is_london_ny_overlap(now)
        
        return SessionState(
            current_session=session,
            is_overlap=is_overlap,
            asian_high=self._get_asian_high(symbol),
            asian_low=self._get_asian_low(symbol),
            session_volume_profile=self._get_volume_profile(session),
            allows_new_entries=session != TradingSession.DEAD_ZONE,
            entry_conviction_multiplier=self.CONVICTION[session],
        )
    
    def update_asian_levels(self, symbol: str, high: float, low: float):
        """Update Asian session high/low (resets at 00:00 UTC)."""
        ...
    
    def is_best_entry_window(self) -> bool:
        """London-NY overlap: 13:00-16:00 UTC."""
        now = datetime.now(UTC).time()
        return dt_time(13, 0) <= now <= dt_time(16, 0)
```

### 3.4 Integration Points

1. **Signal Scout** — Check `VMPSessionManager.get_state()` before generating signals. Multiply signal score by `entry_conviction_multiplier`.
2. **Risk Guardian** — Reduce position size during low-conviction sessions.
3. **Trade Manager** — Use session transitions as exit triggers (e.g., close positions entering dead zone).
4. **Asian Level Mapper** — Automatically track Asian session high/low as S/R levels for next session's retest signals.

---

## 4. Multi-Timeframe Trend Analysis Implementation

### 4.1 TSAR Trend Hierarchy

| Timeframe | Role | Analysis Method |
|-----------|------|----------------|
| **D1 (Daily)** | Macro bias | 50 MA / 200 MA crossover + HH/HL or LH/LL structure |
| **H4 (4-Hour)** | Structural trend | 50 MA / 200 MA + swing structure confirmation |
| **H1 (1-Hour)** | Execution timing | 50 MA / 200 MA + entry precision |

### 4.2 Trend Determination Rules

```
BULLISH TREND:
  1. D1: Price > 50 MA > 200 MA (golden cross active)
  2. D1: Series of Higher Highs (HH) and Higher Lows (HL)
  3. H4: Confirms D1 direction (HH/HL or price > 50 MA)
  4. H1: Aligned with H4 (for entry timing)

BEARISH TREND:
  1. D1: Price < 50 MA < 200 MA (death cross active)
  2. D1: Series of Lower Highs (LH) and Lower Lows (LL)
  3. H4: Confirms D1 direction (LH/LL or price < 50 MA)
  4. H1: Aligned with H4 (for entry timing)

NO TREND / RANGING:
  - 50 MA and 200 MA are intertwined
  - No clear HH/HL or LH/LL structure
  - TSAR says: DO NOT TRADE in ranging conditions
```

### 4.3 Implementation Enhancement

**Enhance:** `src/tools/multi_timeframe.py`

```python
class TSARTrendAnalyzer:
    """TSAR-specific multi-timeframe trend analysis."""
    
    def analyze_trend(self, symbol: str) -> TSARTrendResult:
        """
        Analyze trend across D1, H4, H1 using TSAR rules.
        
        Returns:
            TSARTrendResult with:
            - d1_trend: BULLISH | BEARISH | RANGING
            - h4_trend: BULLISH | BEARISH | RANGING
            - h1_trend: BULLISH | BEARISH | RANGING
            - alignment: bool (all 3 agree)
            - ma_cross: GOLDEN_CROSS | DEATH_CROSS | NONE
            - structure: HH_HL | LH_LL | MIXED
            - trade_direction: LONG | SHORT | NONE
        """
        d1 = self._analyze_timeframe(symbol, "1d")
        h4 = self._analyze_timeframe(symbol, "4h")
        h1 = self._analyze_timeframe(symbol, "1h")
        
        alignment = all(
            t in (Trend.BULLISH, Trend.BEARISH) 
            for t in [d1.trend, h4.trend, h1.trend]
        ) and d1.trend == h4.trend == h1.trend
        
        return TSARTrendResult(
            d1_trend=d1.trend,
            h4_trend=h4.trend,
            h1_trend=h1.trend,
            alignment=alignment,
            ma_cross=self._detect_ma_cross(d1),
            structure=self._detect_structure(d1),
            trade_direction=d1.trend if alignment else Trend.RANGING,
        )
    
    def _analyze_timeframe(self, symbol: str, tf: str) -> TimeframeTrend:
        """Analyze single timeframe using 50/200 MA + swing structure."""
        df = self.market_data.get_ohlcv(symbol, tf, limit=200)
        
        ma50 = df['close'].rolling(50).mean()
        ma200 = df['close'].rolling(200).mean()
        current_price = df['close'].iloc[-1]
        
        # MA relationship
        if current_price > ma50.iloc[-1] > ma200.iloc[-1]:
            ma_trend = Trend.BULLISH
        elif current_price < ma50.iloc[-1] < ma200.iloc[-1]:
            ma_trend = Trend.BEARISH
        else:
            ma_trend = Trend.RANGING
        
        # Swing structure (HH/HL or LH/LL)
        swings = self._find_swings(df)
        structure = self._classify_structure(swings)
        
        # Combine: MA trend + structure must agree
        if ma_trend == structure:
            return TimeframeTrend(trend=ma_trend, confidence=0.9)
        elif structure == Trend.RANGING:
            return TimeframeTrend(trend=Trend.RANGING, confidence=0.5)
        else:
            return TimeframeTrend(trend=ma_trend, confidence=0.6)
```

### 4.4 Swing Structure Detection

```python
def _find_swings(self, df: pd.DataFrame, lookback: int = 5) -> list[SwingPoint]:
    """Find swing highs and swing lows."""
    swings = []
    for i in range(lookback, len(df) - lookback):
        # Swing high: higher than surrounding candles
        if df['high'].iloc[i] == df['high'].iloc[i-lookback:i+lookback+1].max():
            swings.append(SwingPoint(index=i, price=df['high'].iloc[i], type='high'))
        # Swing low: lower than surrounding candles
        if df['low'].iloc[i] == df['low'].iloc[i-lookback:i+lookback+1].min():
            swings.append(SwingPoint(index=i, price=df['low'].iloc[i], type='low'))
    return swings

def _classify_structure(self, swings: list[SwingPoint]) -> Trend:
    """Classify as HH/HL (bullish), LH/LL (bearish), or MIXED."""
    highs = [s for s in swings if s.type == 'high'][-4:]
    lows = [s for s in swings if s.type == 'low'][-4:]
    
    if len(highs) < 2 or len(lows) < 2:
        return Trend.RANGING
    
    higher_highs = highs[-1].price > highs[-2].price
    higher_lows = lows[-1].price > lows[-2].price
    lower_highs = highs[-1].price < highs[-2].price
    lower_lows = lows[-1].price < lows[-2].price
    
    if higher_highs and higher_lows:
        return Trend.BULLISH
    elif lower_highs and lower_lows:
        return Trend.BEARISH
    else:
        return Trend.RANGING
```

---

## 5. S/R Mapping Implementation

### 5.1 TSAR S/R Level Types

| Level Type | Description | TSAR Source |
|-----------|-------------|-------------|
| **Asian High/Low** | Session high/low during Asian hours | NEW — SessionManager |
| **Daily Levels** | Previous day's high/low/close | MarketCartographer (enhance) |
| **Weekly Levels** | Previous week's high/low/close | MarketCartographer (enhance) |
| **Monthly Levels** | Previous month's high/low/close | MarketCartographer (enhance) |
| **Yearly Levels** | Previous year's high/low/close | MarketCartographer (enhance) |
| **Order Blocks (Bullish)** | Last bearish candle before bullish BOS | NEW — OrderBlockDetector |
| **Order Blocks (Bearish)** | Last bullish candle before bearish BOS | NEW — OrderBlockDetector |

### 5.2 Order Block Detection Algorithm

```python
"""
ORDER BLOCK DETECTION (TSAR Definition):

Bullish Order Block:
  1. Identify a Break of Structure (BOS) upward
     - Price breaks above a previous swing high
  2. Find the LAST bearish (red) candle before the BOS
  3. That candle's range = bullish order block (demand zone)
  4. Expect price to retrace to this zone before continuing up

Bearish Order Block:
  1. Identify a Break of Structure (BOS) downward
     - Price breaks below a previous swing low
  2. Find the LAST bullish (green) candle before the BOS
  3. That candle's range = bearish order block (supply zone)
  4. Expect price to retrace to this zone before continuing down
"""

@dataclass
class OrderBlock:
    type: str  # "bullish" (demand) or "bearish" (supply)
    high: float
    low: float
    bos_level: float  # The level that was broken
    timestamp: datetime
    timeframe: str
    strength: float  # 0-1 based on volume and displacement
    tested: bool = False
    test_count: int = 0

class VMPOrderBlockDetector:
    """Detect TSAR-defined order blocks."""
    
    def detect(self, df: pd.DataFrame, timeframe: str) -> list[OrderBlock]:
        """Find all valid order blocks in the data."""
        blocks = []
        swings = self._find_swings(df)
        
        for i in range(2, len(swings)):
            # Check for BOS (Break of Structure)
            if self._is_bullish_bos(swings, i):
                # Find last bearish candle before BOS
                ob_candle = self._find_last_bearish_candle(
                    df, swings[i].index
                )
                if ob_candle:
                    blocks.append(OrderBlock(
                        type="bullish",
                        high=ob_candle['high'],
                        low=ob_candle['low'],
                        bos_level=swings[i].price,
                        timestamp=ob_candle.name,
                        timeframe=timeframe,
                        strength=self._calculate_strength(df, ob_candle),
                    ))
            
            elif self._is_bearish_bos(swings, i):
                ob_candle = self._find_last_bullish_candle(
                    df, swings[i].index
                )
                if ob_candle:
                    blocks.append(OrderBlock(
                        type="bearish",
                        high=ob_candle['high'],
                        low=ob_candle['low'],
                        bos_level=swings[i].price,
                        timestamp=ob_candle.name,
                        timeframe=timeframe,
                        strength=self._calculate_strength(df, ob_candle),
                    ))
        
        return blocks
```

### 5.3 S/R Level Scoring

```python
class TSARSRMapper:
    """Map and score all TSAR S/R levels."""
    
    def get_all_levels(self, symbol: str) -> list[SRLevel]:
        """Get all S/R levels with TSAR scoring."""
        levels = []
        
        # 1. Asian session levels (today)
        asian = self.session_manager.get_state(symbol)
        levels.append(SRLevel(
            price=asian.asian_high, type="resistance",
            source="asian_high", strength=0.7
        ))
        levels.append(SRLevel(
            price=asian.asian_low, type="support",
            source="asian_low", strength=0.7
        ))
        
        # 2. Daily/Weekly/Monthly/Yearly levels
        for period, strength in [("1d", 0.8), ("1w", 0.9), ("1M", 0.95), ("1y", 1.0)]:
            levels.extend(self._get_period_levels(symbol, period, strength))
        
        # 3. Order blocks
        for tf in ["1h", "4h", "1d"]:
            blocks = self.order_block_detector.detect(
                self.market_data.get_ohlcv(symbol, tf), tf
            )
            for block in blocks:
                levels.append(SRLevel(
                    price=(block.high + block.low) / 2,
                    type="support" if block.type == "bullish" else "resistance",
                    source=f"order_block_{tf}",
                    strength=block.strength,
                ))
        
        # 4. Cluster nearby levels (within 0.3%)
        levels = self._cluster_levels(levels, threshold_pct=0.3)
        
        return sorted(levels, key=lambda l: l.strength, reverse=True)
```

---

## 6. Fundamental Analysis Layer

### 6.1 TSAR Fundamental → Crypto Adaptation

TSAR's fundamental layer uses forex-centric data (CPI, NFP, GDP, central bank decisions). For crypto, we need to map equivalent drivers:

| TSAR Fundamental | Crypto Equivalent | TSAR Source |
|-----------------|-------------------|-------------|
| Central bank decisions | Fed rate decisions, FOMC minutes | EconomicCalendar (enhance) |
| CPI / Inflation | CPI data (impacts crypto via risk appetite) | EconomicCalendar ✅ |
| NFP / Employment | NFP data (impacts USD → impacts BTC) | EconomicCalendar ✅ |
| GDP | GDP releases | EconomicCalendar ✅ |
| Geopolitical events | Regulatory news, ETF decisions, hacks | NewsAggregator ✅ |
| — | BTC Dominance | NEW — on-chain metric |
| — | Funding Rates | NEW — derivatives metric |
| — | Exchange Net Flows | NEW — on-chain metric |
| — | Stablecoin Supply | NEW — on-chain metric |
| — | Whale Activity | NEW — on-chain metric |

### 6.2 Implementation

**Existing:** `src/tools/economic_calendar.py`, `src/tools/fundamental.py`, `src/agents/fundamental_scorer.py`

**Enhancement needed:**

```python
class TSARFundamentalLayer:
    """TSAR-specific fundamental bias determination."""
    
    def get_bias(self, symbol: str) -> FundamentalBias:
        """
        Determine fundamental bias for TSAR.
        
        Returns:
            FundamentalBias with:
            - direction: BULLISH | BEARISH | NEUTRAL
            - confidence: 0-1
            - factors: list of contributing factors
            - next_event: upcoming high-impact event
            - blackout_active: whether to avoid trading
        """
        scores = []
        
        # 1. Economic calendar (existing)
        econ = self.economic_calendar.get_upcoming_events(hours=48)
        high_impact = [e for e in econ if e.impact == "HIGH"]
        if high_impact:
            scores.append(self._score_economic_events(high_impact))
        
        # 2. News sentiment (existing)
        news = self.news_aggregator.get_digest(symbol)
        scores.append(self._score_news_sentiment(news))
        
        # 3. Crypto-specific metrics (NEW)
        btc_dom = self._get_btc_dominance()
        funding = self._get_funding_rate(symbol)
        flows = self._get_exchange_flows(symbol)
        
        scores.extend([
            self._score_btc_dominance(btc_dom),
            self._score_funding_rate(funding),
            self._score_exchange_flows(flows),
        ])
        
        # 4. Aggregate
        avg_score = np.mean([s.value for s in scores])
        
        return FundamentalBias(
            direction=self._score_to_direction(avg_score),
            confidence=abs(avg_score),
            factors=[s.description for s in scores],
            next_event=high_impact[0] if high_impact else None,
            blackout_active=self._is_blackout(econ),
        )
```

### 6.3 News Blackout Integration

```python
# From TSAR: "Check economic calendar before every trade"
# Already partially implemented in NewsGatekeeper, enhance for TSAR:

NEWS_BLACKOUT_RULES = {
    "CRITICAL": {"pre_buffer_hours": 2, "post_buffer_min": 30},
    "HIGH": {"pre_buffer_hours": 1, "post_buffer_min": 15},
    "MEDIUM": {"pre_buffer_minutes": 30, "post_buffer_min": 5},
}
```

---

## 7. Risk Management for TSAR

### 7.1 TSAR-Specific Risk Rules

| Rule | Parameter | Value | Rationale |
|------|-----------|-------|-----------|
| Risk per trade | `risk_per_trade_pct` | 1-2% | Standard for layered strategy |
| Max daily loss | `daily_loss_limit_pct` | 3% | TSAR has fewer trades, so losses cluster |
| Max drawdown | `max_drawdown_pct` | 8% | Wider than mean reversion (trend following) |
| Max open positions | `max_open_positions` | 2-3 | TSAR signals are rare, don't dilute |
| Min R:R | `min_risk_reward` | 2.5:1 | Higher than standard 2:1 (layered confirmation = higher win rate) |
| Session position sizing | Dynamic | 0.5x-1.0x | Reduce size in low-conviction sessions |
| News blackout | Hard gate | 0 entries | No trading 2h before CRITICAL events |
| Trend misalignment | Hard gate | 0 entries | No trading against D1 trend |

### 7.2 TSAR Position Sizing

```python
def calculate_tsar_position_size(
    account_balance: float,
    signal: Signal,
    session_state: SessionState,
    trend_result: TSARTrendResult,
) -> float:
    """
    TSAR position sizing considers:
    1. Base risk (1-2% of account)
    2. Session conviction multiplier (0.5-1.0)
    3. Trend alignment bonus (1.0-1.2)
    4. S/R proximity bonus (1.0-1.1)
    """
    base_risk = account_balance * 0.02  # 2% base
    
    # Session adjustment
    session_adj = session_state.entry_conviction_multiplier
    
    # Trend alignment bonus
    trend_adj = 1.2 if trend_result.alignment else 0.8
    
    # S/R proximity bonus (closer to S/R = better entry = slightly larger)
    sr_adj = 1.1 if signal.sr_proximity_score > 0.8 else 1.0
    
    adjusted_risk = base_risk * session_adj * trend_adj * sr_adj
    
    # Cap at max position size
    max_position = account_balance * 0.15  # 15% max
    position_value = min(adjusted_risk / signal.stop_loss_pct, max_position)
    
    return position_value
```

### 7.3 TSAR Trade Management

```python
# TSAR-specific exit rules layered on top of existing TradeManager:

TSAR_EXIT_RULES = {
    # Trailing stop (from ENTRY_EXIT_OPTIMIZATION.md)
    "trailing_stop": {
        "initial": "1.5x ATR",
        "break_even_trigger": "1:1 R:R",
        "trail_trigger": "1.5:1 R:R",
        "trail_distance": "1.0x ATR",
        "tight_trail_trigger": "2:1 R:R",
        "tight_trail_distance": "0.75x ATR",
    },
    
    # Partial exits
    "partial_exits": [
        {"at_rr": 1.0, "size_pct": 40},  # 40% at 1:1
        {"at_rr": 2.0, "size_pct": 30},  # 30% at 2:1
        {"at_rr": None, "size_pct": 30}, # 30% trailing (no fixed target)
    ],
    
    # Time stop (TSAR trades should resolve within a session)
    "time_stop_hours": 12,  # Close if no resolution within 12h
    
    # Session exit
    "close_before_dead_zone": True,  # Close positions entering 21:00-00:00 UTC
}
```

---

## 8. Backtesting Approach for TSAR

### 8.1 Backtest Architecture

```
┌─────────────────────────────────────────────────────┐
│              TSAR BACKTEST ENGINE                     │
│                                                      │
│  1. Load historical OHLCV (D1, H4, H1)              │
│  2. Load historical economic calendar                │
│  3. For each candle (H1 resolution):                │
│     a. Check session → VMPSessionManager             │
│     b. Check trend → TSARTrendAnalyzer (D1/H4/H1)   │
│     c. Map S/R → TSARSRMapper (Asian, Daily, OBs)   │
│     d. Check retest → price at S/R zone?             │
│     e. Check RSI → RSI confirming at retest?         │
│     f. Check candlestick → pattern at S/R?           │
│     g. If all pass → simulate entry                  │
│     h. Manage trade → trailing, partial, time stop   │
│  4. Compute metrics: Sharpe, PF, Win%, MaxDD         │
│  5. Walk-forward validation (5 windows)              │
│  6. Monte Carlo simulation (1000 runs)               │
└─────────────────────────────────────────────────────┘
```

### 8.2 Key Backtest Metrics

| Metric | Target | Why |
|--------|--------|-----|
| Win Rate | ≥ 55% | Layered confirmation should yield high win rate |
| Profit Factor | ≥ 1.8 | Strong edge with good R:R |
| Sharpe Ratio | ≥ 1.5 | Risk-adjusted returns |
| Max Drawdown | < 10% | Acceptable for trend following |
| Avg R:R Realized | ≥ 2.0:1 | Partial exits + trailing should achieve this |
| Trades per Month | ≥ 8 | Enough for statistical significance |
| Consecutive Losses | ≤ 5 | Psychological resilience |

### 8.3 Walk-Forward Validation

```python
def walk_forward_tsar(
    strategy: TSARStrategy,
    data: pd.DataFrame,
    windows: int = 5,
) -> WalkForwardResult:
    """
    Walk-forward validation for TSAR.
    
    Window 1: Train on months 1-6, test on month 7
    Window 2: Train on months 2-7, test on month 8
    ...
    Window 5: Train on months 5-10, test on month 11
    
    Each window optimizes:
    - RSI thresholds (currently 30/70)
    - ATR multipliers for stops
    - Session conviction weights
    - S/R proximity thresholds
    
    Out-of-sample must maintain:
    - Win rate > 50%
    - Profit factor > 1.3
    - Sharpe > 1.0
    """
    results = []
    window_size = len(data) // (windows + 1)
    
    for i in range(windows):
        train_start = i * window_size
        train_end = train_start + window_size
        test_end = train_end + window_size // 2
        
        train_data = data.iloc[train_start:train_end]
        test_data = data.iloc[train_end:test_end]
        
        # Optimize on training data
        optimized_params = optimize_tsar_params(train_data)
        
        # Test on out-of-sample data
        result = run_tsar_backtest(test_data, optimized_params)
        results.append(result)
    
    return WalkForwardResult(results=results)
```

### 8.4 Data Requirements

| Data | Source | History Needed |
|------|--------|---------------|
| OHLCV (1h, 4h, 1d) | Binance/CoinGecko | 2+ years |
| Economic calendar | Investing.com API | 2+ years |
| News archives | CryptoPanic/NewsAPI | 1+ year |
| Funding rates | Binance/Bybit | 2+ years |
| BTC dominance | CoinGecko | 2+ years |

---

## 9. Best Currency Pairs for TSAR

### 9.1 TSAR Pair Selection Criteria

TSAR works best on pairs with:
1. **High liquidity** — tight spreads, reliable fills
2. **Clear trends** — respects MA structure
3. **Session-driven behavior** — responds to London/NY volume
4. **Technical respect** — honors S/R levels and order blocks

### 9.2 Recommended Pairs

| Tier | Pairs | Why |
|------|-------|-----|
| **Tier 1 (Primary)** | BTC/USDT, ETH/USDT | Highest liquidity, cleanest trends, best S/R respect |
| **Tier 2 (Secondary)** | SOL/USDT, BNB/USDT | Good liquidity, trending behavior, institutional interest |
| **Tier 3 (Forex Cross)** | EUR/USD, GBP/USD, USD/JPY | Original TSAR targets — forex pairs with session dynamics |
| **Tier 4 (Commodity)** | XAU/USD (Gold) | Strong trends, respects S/R, session-driven |

### 9.3 Pair-Specific Adjustments

| Pair | ATR Adjustment | Session Weight | Notes |
|------|---------------|----------------|-------|
| BTC/USDT | Standard | Full | Best for TSAR in crypto |
| ETH/USDT | 0.9x | Full | Follows BTC, slightly tighter |
| SOL/USDT | 1.2x | 0.9x | Higher volatility, reduce size |
| EUR/USD | Standard | Full | Original TSAR target |
| XAU/USD | 0.8x | Full | Strong trends, tight ranges |

---

## 10. How the Flywheel Improves TSAR Over Time

### 10.1 TSAR Flywheel Cycle

```
TRADE (TSAR layered execution)
    │
    ▼
OBSERVE (Track which layers confirmed/denied)
    │
    ▼
REFLECT (Trade Philosopher analyzes TSAR-specific outcomes)
    │
    ▼
EXTRACT (Shadow Account extracts TSAR rules)
    │
    ├── "Asian session retests have 72% win rate"
    ├── "Order blocks on H4 have highest strength"
    ├── "RSI 25/75 works better than 30/70 for BTC"
    ├── "London-NY overlap entries have 2.1x avg R:R"
    ├── "Bearish order blocks tested 3+ times break 80% of the time"
    │
    ▼
ADAPT (Strategy Geneticist mutates TSAR parameters)
    │
    ▼
BETTER TRADE (Improved TSAR with validated parameters)
```

### 10.2 What the Flywheel Learns for TSAR

| Learning Area | Initial State | After 100 Trades | After 500 Trades |
|--------------|---------------|-------------------|-------------------|
| RSI thresholds | 30/70 (default) | 28/72 (optimized) | 26/74 (pair-specific) |
| Session weights | Uniform | London 1.2x, Asian 0.5x | Granular per-pair session weights |
| Order block validity | All OBs | H4 OBs preferred | OB + volume filter |
| S/R proximity | 0.5% zone | 0.3% zone (tighter) | Dynamic zone based on ATR |
| Trend MA periods | 50/200 | 50/200 (validated) | Pair-specific (e.g., 21/100 for SOL) |
| Candlestick patterns | All engulfing | Only at S/R confluence | Pattern + volume + session filter |
| Best trading days | Tue-Thu | Tue-Thu (validated) | Tuesday 1.3x weight |
| Optimal R:R | 2.5:1 | 3:1 for trend, 2:1 for range | Dynamic R:R by regime |

### 10.3 TSAR Genome Representation

```python
@dataclass
class TSARGenome:
    """TSAR strategy genome for the Strategy Geneticist."""
    
    # RSI parameters
    rsi_oversold: float = 30.0      # Mutable
    rsi_overbought: float = 70.0    # Mutable
    
    # Trend parameters
    fast_ma_period: int = 50        # Mutable (21-100)
    slow_ma_period: int = 200       # Mutable (100-300)
    swing_lookback: int = 5         # Mutable (3-10)
    
    # S/R parameters
    sr_zone_pct: float = 0.5        # Mutable (0.2-1.0)
    ob_min_strength: float = 0.5    # Mutable (0.3-0.8)
    ob_max_tests: int = 3           # Mutable (1-5)
    
    # Session parameters
    session_weights: dict = field(default_factory=lambda: {
        "sydney": 0.5, "tokyo": 0.7,
        "london": 1.0, "new_york": 1.0,
    })
    
    # Risk parameters
    atr_multiplier_sl: float = 1.5  # Mutable (1.0-2.5)
    min_rr_ratio: float = 2.5       # Mutable (2.0-4.0)
    
    # Exit parameters
    trailing_trigger_rr: float = 1.5  # Mutable (1.0-2.0)
    trailing_atr_mult: float = 1.0    # Mutable (0.5-1.5)
    time_stop_hours: int = 12         # Mutable (4-24)
```

### 10.4 Post-Training Potential

After 500+ trades, TSAR can:
1. **Fine-tune DeepSeek-R1** on TSAR trade decision data (prompt → decision → outcome)
2. **Build a TSAR-specific pattern classifier** from candlestick + S/R + session data
3. **Create a TSAR signal quality predictor** that estimates win probability before entry
4. **Develop pair-specific TSAR variants** optimized per asset

---

## 11. Implementation Roadmap

### Phase 1: Core TSAR Infrastructure (Weeks 1-2)
- [ ] `VMPSessionManager` — session tracking, Asian levels
- [ ] `TSARTrendAnalyzer` — 50/200 MA + swing structure on D1/H4/H1
- [ ] `VMPOrderBlockDetector` — order block identification
- [ ] `TSARSRMapper` — unified S/R with all level types

### Phase 2: Signal Pipeline (Weeks 3-4)
- [ ] `TSARFundamentalLayer` — fundamental bias (crypto-adapted)
- [ ] `TSARCandlestickValidator` — pattern confirmation at S/R
- [ ] TSAR signal scoring (7-layer confirmation)
- [ ] Integration with existing Signal Scout pipeline

### Phase 3: Execution & Management (Weeks 5-6)
- [ ] TSAR-specific position sizing
- [ ] Trailing stop system (4-stage)
- [ ] Partial exit system (40/30/30)
- [ ] Session-aware trade management

### Phase 4: Backtesting & Validation (Weeks 7-8)
- [ ] TSAR backtest engine
- [ ] Walk-forward validation (5 windows)
- [ ] Monte Carlo simulation
- [ ] Parameter optimization

### Phase 5: Flywheel Integration (Weeks 9-10)
- [ ] TSAR genome representation
- [ ] Shadow Account TSAR rule extraction
- [ ] Strategy Geneticist TSAR mutations
- [ ] Live paper trading with flywheel feedback

---

## 12. TSAR Pipeline Architecture (Final)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     TSAR PIPELINE IN TSAR                                │
│                                                                          │
│  ┌─────────────┐                                                         │
│  │ FUNDAMENTAL │  Economic calendar, news, crypto metrics                │
│  │ BIAS LAYER  │  → BULLISH / BEARISH / NEUTRAL                         │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │   TREND     │  D1 (50/200 MA + HH/HL) → H4 → H1                     │
│  │   LAYER     │  → LONG / SHORT / NO TREND                             │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │  SESSION    │  Current session, Asian levels, conviction              │
│  │  GATE       │  → ALLOW / REDUCE / BLOCK                               │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │  S/R MAPPING│  Asian H/L, Daily/Weekly/Monthly, Order Blocks          │
│  │             │  → SUPPORT ZONE / RESISTANCE ZONE                       │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │   RETEST    │  Price approaching S/R zone?                            │
│  │   DETECTOR  │  → ZONE TOUCHED / NOT YET                               │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │    RSI      │  RSI oversold at support? RSI overbought at resistance? │
│  │ CONFIRMATION│  → CONFIRMED / DENIED                                   │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │ CANDLESTICK │  Engulfing, pin bar, morning/evening star at S/R?      │
│  │ CONFIRMATION│  → CONFIRMED / DENIED                                   │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │
│  │    RISK     │───→│  EXECUTION  │───→│    TRADE    │                  │
│  │  GUARDIAN   │    │   SNIPER    │    │   MANAGER   │                  │
│  │ 10-pt check │    │  Entry fill │    │ Trail/Partial│                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    FLYWHEEL (Continuous)                          │   │
│  │  Trade → Observe → Reflect → Extract → Adapt → Better TSAR      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 13. Council Review Summary

| Criterion | Score | Verdict |
|-----------|-------|---------|
| Strategy Soundness | 8.5/10 | APPROVED — Layered confirmation is institutional-grade |
| TSAR Compatibility | 9/10 | APPROVED — 70% infrastructure exists, 30% well-scoped |
| Risk Management | 8/10 | APPROVED — Needs TSAR-specific sizing rules |
| Backtest Feasibility | 8.5/10 | APPROVED — Clear rules, deterministic enough to backtest |
| Flywheel Potential | 9/10 | APPROVED — Many mutable parameters for optimization |
| Implementation Effort | 7.5/10 | CONDITIONAL — 8-10 weeks for full implementation |

**Overall: CONDITIONAL PASS — 8.4/10**

**Conditions:**
1. Must backtest 2+ years of data before live trading
2. Must pass walk-forward validation (5 windows, OOS win rate > 50%)
3. Must run 50+ paper trades before real capital
4. Candlestick confirmation must be codified (not purely discretionary)

---

*"The layered confirmation system is the strategy's greatest strength. Each layer independently filters noise. By execution, probability is stacked 7 layers deep."*

*Analysis complete. TSAR is ready for TSAR integration.*
