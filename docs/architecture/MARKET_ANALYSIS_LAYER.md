# MARKET ANALYSIS LAYER — Full Specification

**Version:** 1.0.0
**Date:** 2026-07-24
**Status:** APPROVED — Part of TSAR Trading Super Agent Architecture
**Coverage:** Market Analysis layer from 15% → 85%
**Cross-references:** ARCHITECTURE_CONSOLIDATION.md, DAY1_ARCHITECTURE.md, GAP_RESOLUTION.md, trading-super-agent-spec.md

---

## Table of Contents

1. [Layer Overview](#1-layer-overview)
2. [Macro Agent — Full Specification](#2-macro-agent)
3. [Economic Calendar Integration](#3-economic-calendar-integration)
4. [Sentiment Analysis](#4-sentiment-analysis)
5. [On-Chain Analytics](#5-on-chain-analytics)
6. [Geopolitical Analysis](#6-geopolitical-analysis)
7. [Cross-Asset Correlation](#7-cross-asset-correlation)
8. [Order Flow Analysis](#8-order-flow-analysis)
9. [Seasonal Analysis](#9-seasonal-analysis)
10. [Architecture Integration Map](#10-architecture-integration-map)
11. [Day1 vs Full Implementation](#11-day1-vs-full-implementation)
12. [Data Source Catalog](#12-data-source-catalog)
13. [Database Schema Additions](#13-database-schema-additions)

---

## 1. Layer Overview

### 1.1 What Market Analysis Does

The Market Analysis layer provides **macro context, sentiment signals, and structural market data** that technical indicators alone cannot capture. It answers questions like:

- "Is the macro environment supportive of risk-on trades?"
- "Is the market in extreme fear or greed?"
- "Are whales accumulating or distributing?"
- "Is there a major economic event in the next hour that could cause a volatility spike?"
- "Are DXY and BTC still inversely correlated, or has the relationship broken down?"
- "Is geopolitical risk elevated, warranting reduced position sizes?"

### 1.2 Layer Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    MARKET ANALYSIS LAYER                                 │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │    MACRO     │  │  SENTIMENT   │  │  ON-CHAIN    │  │ GEOPOLIT-  │  │
│  │    AGENT     │  │  ANALYSIS    │  │  ANALYTICS   │  │  ICAL      │  │
│  │              │  │              │  │              │  │  ANALYSIS   │  │
│  │ • Fed policy │  │ • Fear/Greed │  │ • Whale moves│  │ • Wars     │  │
│  │ • Rates      │  │ • News NLP   │  │ • Exchange   │  │ • Sanctions│  │
│  │ • Inflation  │  │ • Social     │  │   flows      │  │ • Elections│  │
│  │ • GDP        │  │   sentiment  │  │ • DeFi TVL   │  │ • Trade    │  │
│  │ • Employment │  │              │  │ • MVRV, NVT  │  │   wars     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │
│         │                 │                 │                │         │
│         ▼                 ▼                 ▼                ▼         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              CROSS-ASSET CORRELATION ENGINE                     │   │
│  │                                                                 │   │
│  │  DXY ↔ BTC  │  DXY ↔ Gold  │  BTC ↔ ETH  │  VIX ↔ SPY       │   │
│  │  Bond yields │  Commodities │  Crypto-beta │  Sector rotation  │   │
│  └─────────────────────────────┬───────────────────────────────────┘   │
│                                │                                       │
│                                ▼                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │
│  │ ORDER FLOW   │  │  SEASONAL    │  │  ECONOMIC    │                 │
│  │ ANALYSIS     │  │  ANALYSIS    │  │  CALENDAR    │                 │
│  │              │  │              │  │              │                 │
│  │ • Book       │  │ • Hour/day   │  │ • NFP        │                 │
│  │   imbalance  │  │   patterns   │  │ • CPI        │                 │
│  │ • Trade flow │  │ • Monthly    │  │ • FOMC       │                 │
│  │ • Volume     │  │   seasonality│  │ • ECB/BOJ    │                 │
│  │   profile    │  │ • Holiday    │  │ • Blackout   │                 │
│  │              │  │   effects    │  │   rules      │                 │
│  └──────────────┘  └──────────────┘  └──────────────┘                 │
│                                                                         │
│  ALL OUTPUTS → Signal Agent (scoring), Risk Agent (filtering)           │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Signal Flow to Existing Architecture

```
Market Analysis Layer outputs → Signal Agent (adds context to signal scoring)
Market Analysis Layer outputs → Risk Agent (adds filtering/blackout rules)
Market Analysis Layer outputs → Regime Detector (macro regime classification)
Market Analysis Layer outputs → Strategy Geneticist (performance attribution)
```

---

## 2. Macro Agent — Full Specification {#2-macro-agent}

### 2.1 Role & Responsibility

The Macro Agent analyzes the **macroeconomic environment** and produces a **macro regime score** that influences position sizing, direction bias, and trade filtering across all strategies. It does NOT generate trade signals directly — it provides context that other agents use.

**Core questions it answers:**
1. Is the Fed hawkish or dovish? (rate direction bias)
2. Is inflation rising or falling? (real yield impact)
3. Is the economy expanding or contracting? (risk appetite)
4. Is employment strong or weakening? (consumer spending proxy)
5. What is the current macro regime? (risk-on, risk-off, transition)

### 2.2 Macro Regime Classification

| Regime | Characteristics | Market Impact | Position Adjustment |
|--------|----------------|---------------|---------------------|
| **RISK-ON** | Dovish Fed, falling inflation, strong GDP, low unemployment | Crypto up, DXY down, equities up | Full position size, long bias |
| **RISK-OFF** | Hawkish Fed, rising inflation, weakening GDP, rising unemployment | Crypto down, DXY up, equities down | 50% position size, short bias or no trades |
| **TRANSITION** | Mixed signals, policy pivot expected | Choppy, mean-reverting | 75% position size, tighter stops |
| **CRISIS** | Extreme events (war, pandemic, financial crisis) | All correlations → 1.0, liquidity dries up | Halt trading or 25% position size |

### 2.3 Data Sources

| Indicator | Source | API | Cost | Frequency |
|-----------|--------|-----|------|-----------|
| Federal Funds Rate | FRED (Federal Reserve) | `fredapi` | $0 | On FOMC decision |
| CPI (YoY, MoM) | Trading Economics | REST API | $0 (limited) | Monthly |
| GDP (quarterly) | Trading Economics | REST API | $0 (limited) | Quarterly |
| Non-Farm Payrolls | Trading Economics | REST API | $0 (limited) | Monthly |
| Unemployment Rate | FRED | `fredapi` | $0 | Monthly |
| 10Y Treasury Yield | Yahoo Finance | `yfinance` | $0 | Real-time |
| 2Y Treasury Yield | Yahoo Finance | `yfinance` | $0 | Real-time |
| DXY (Dollar Index) | Yahoo Finance | `yfinance` | $0 | Real-time |
| Fed Fund Futures | CME (via FRED) | `fredapi` | $0 | Daily |
| PCE (Fed's preferred inflation) | FRED | `fredapi` | $0 | Monthly |
| ISM Manufacturing PMI | Trading Economics | REST API | $0 (limited) | Monthly |
| Consumer Confidence | Trading Economics | REST API | $0 (limited) | Monthly |

### 2.4 Macro Score Computation

```python
class MacroAgent:
    """
    Computes a macro regime score from economic indicators.
    Output: MacroState published to tsar:stream:macro
    """

    # Weights for composite macro score
    INDICATOR_WEIGHTS = {
        "fed_stance":       0.30,  # Most important — drives everything
        "inflation_trend":  0.20,  # Determines real yields
        "growth_trend":     0.20,  # GDP, PMI
        "employment":       0.15,  # Labor market health
        "dollar_strength":  0.15,  # DXY trend
    }

    # Fed stance scoring: -1 (very hawkish) to +1 (very dovish)
    def _score_fed_stance(self) -> float:
        """Analyze Fed signals: rate direction, dot plot, FOMC minutes."""
        current_rate = self._get_fed_funds_rate()
        rate_change_6m = self._get_rate_change(months=6)
        fed_futures_implied = self._get_implied_rate_from_futures()
        dot_plot_median = self._get_dot_plot_median()

        # Rate direction signal
        if rate_change_6m < -0.25:
            direction_score = 0.8  # Cutting → dovish
        elif rate_change_6m > 0.25:
            direction_score = -0.8  # Hiking → hawkish
        else:
            direction_score = 0.0  # On hold

        # Market expectation vs actual
        expectation_gap = fed_futures_implied - current_rate
        if expectation_gap < -0.25:
            expectation_score = 0.5  # Market expects cuts
        elif expectation_gap > 0.25:
            expectation_score = -0.5  # Market expects hikes
        else:
            expectation_score = 0.0

        return (direction_score * 0.6 + expectation_score * 0.4)

    # Inflation scoring: -1 (deflation risk) to +1 (runaway inflation)
    def _score_inflation(self) -> float:
        """Analyze inflation trends: CPI, PCE, expectations."""
        cpi_yoy = self._get_latest_cpi()
        cpi_trend = self._get_cpi_trend(months=3)  # 3-month trend
        pce_yoy = self._get_latest_pce()
        breakeven_5y = self._get_tips_breakeven()  # Market inflation expectations

        # CPI relative to Fed target (2%)
        cpi_vs_target = cpi_yoy - 2.0

        # Trend direction
        if cpi_trend < -0.3:
            trend_score = -0.5  # Disinflation
        elif cpi_trend > 0.3:
            trend_score = 0.5  # Rising inflation
        else:
            trend_score = 0.0

        # Composite
        level_score = max(-1, min(1, cpi_vs_target / 3.0))  # Normalize
        return (level_score * 0.5 + trend_score * 0.3 +
                max(-1, min(1, (breakeven_5y - 2.0) / 2.0)) * 0.2)

    # Growth scoring: -1 (recession) to +1 (strong expansion)
    def _score_growth(self) -> float:
        """Analyze growth: GDP, PMI, consumer confidence."""
        gdp_growth = self._get_latest_gdp()  # Annualized quarterly
        ism_pmi = self._get_ism_pmi()
        consumer_conf = self._get_consumer_confidence()

        # GDP: negative = recession risk
        gdp_score = max(-1, min(1, gdp_growth / 4.0))  # Normalize around 4% potential

        # PMI: below 50 = contraction
        if ism_pmi < 45:
            pmi_score = -0.8
        elif ism_pmi < 50:
            pmi_score = -0.3
        elif ism_pmi > 55:
            pmi_score = 0.5
        else:
            pmi_score = 0.0

        return (gdp_score * 0.5 + pmi_score * 0.3 +
                max(-1, min(1, (consumer_conf - 80) / 40)) * 0.2)

    # Employment scoring: -1 (labor market collapse) to +1 (full employment)
    def _score_employment(self) -> float:
        """Analyze labor market: NFP, unemployment rate, initial claims."""
        unemployment = self._get_unemployment_rate()
        nfp_latest = self._get_latest_nfp()
        initial_claims = self._get_initial_claims()
        claims_trend = self._get_claims_trend(weeks=4)

        # Unemployment: below 4% = strong, above 5% = weakening
        unemp_score = max(-1, min(1, (4.5 - unemployment) / 2.0))

        # NFP: above 200K = strong, below 100K = weak
        nfp_score = max(-1, min(1, (nfp_latest - 150) / 150))

        # Claims trend: rising = bad
        if claims_trend > 0.1:
            claims_score = -0.5
        elif claims_trend < -0.1:
            claims_score = 0.3
        else:
            claims_score = 0.0

        return (unemp_score * 0.4 + nfp_score * 0.4 + claims_score * 0.2)

    # Dollar scoring: -1 (strong dollar) to +1 (weak dollar)
    def _score_dollar(self) -> float:
        """Analyze DXY trend and yield differentials."""
        dxy_current = self._get_dxy()
        dxy_sma50 = self._get_dxy_sma(50)
        dxy_sma200 = self._get_dxy_sma(200)
        yield_spread_10y2y = self._get_yield_spread()

        # DXY trend
        if dxy_current > dxy_sma50 > dxy_sma200:
            trend_score = -0.7  # Strong dollar (bearish for crypto)
        elif dxy_current < dxy_sma50 < dxy_sma200:
            trend_score = 0.7   # Weak dollar (bullish for crypto)
        else:
            trend_score = 0.0

        # Yield curve: inverted = recession risk, steep = growth
        if yield_spread_10y2y < -0.5:
            curve_score = -0.5  # Deeply inverted → recession risk
        elif yield_spread_10y2y > 1.0:
            curve_score = 0.3   # Steep → growth expectations
        else:
            curve_score = 0.0

        return trend_score * 0.7 + curve_score * 0.3

    def compute_macro_state(self) -> MacroState:
        """Compute the full macro state and regime."""
        fed = self._score_fed_stance()
        inflation = self._score_inflation()
        growth = self._score_growth()
        employment = self._score_employment()
        dollar = self._score_dollar()

        # Composite macro score: -1 (very bearish) to +1 (very bullish)
        composite = (
            fed * self.INDICATOR_WEIGHTS["fed_stance"] +
            (-inflation) * self.INDICATOR_WEIGHTS["inflation_trend"] +  # High inflation = bearish
            growth * self.INDICATOR_WEIGHTS["growth_trend"] +
            employment * self.INDICATOR_WEIGHTS["employment"] +
            (-dollar) * self.INDICATOR_WEIGHTS["dollar_strength"]  # Strong dollar = bearish for crypto
        )

        # Classify regime
        if composite > 0.3:
            regime = "RISK_ON"
        elif composite < -0.3:
            regime = "RISK_OFF"
        elif abs(composite) < 0.15:
            regime = "TRANSITION"
        else:
            regime = "MIXED"

        # Override: crisis detection
        if self._detect_crisis():
            regime = "CRISIS"

        return MacroState(
            composite_score=composite,
            regime=regime,
            components={
                "fed_stance": fed,
                "inflation": inflation,
                "growth": growth,
                "employment": employment,
                "dollar": dollar,
            },
            position_size_multiplier=self._regime_to_size_mult(regime),
            direction_bias=self._regime_to_bias(regime),
            timestamp=datetime.utcnow(),
        )

    def _regime_to_size_mult(self, regime: str) -> float:
        """Convert regime to position size multiplier."""
        return {
            "RISK_ON": 1.0,
            "TRANSITION": 0.75,
            "RISK_OFF": 0.50,
            "CRISIS": 0.25,
        }.get(regime, 0.50)

    def _regime_to_bias(self, regime: str) -> str:
        """Convert regime to directional bias."""
        return {
            "RISK_ON": "LONG",
            "TRANSITION": "NEUTRAL",
            "RISK_OFF": "SHORT",
            "CRISIS": "NONE",
        }.get(regime, "NEUTRAL")
```

### 2.5 Communication Protocol

```
PUBLISHES TO:  tsar:stream:macro
SUBSCRIBES TO: tsar:stream:regime (adjust macro focus by market regime)
WRITES STATE:  tsar:macro:state (Redis Hash — current macro state)
               tsar:macro:history (Redis Stream — macro state changes)
READS FROM:    FRED API, Trading Economics, Yahoo Finance
```

### 2.6 Model Tier

| Component | Tier | Model | Provider | Cost | Rationale |
|-----------|------|-------|----------|------|-----------|
| Indicator computation | T0 | Python/pandas | Local | $0 | Pure math |
| Macro narrative | T2 | Qwen2.5-7B | Ollama (local) | $0 | "Why is the Fed hawkish?" |
| Regime classification | T0 | Rule-based | Local | $0 | Deterministic |
| Crisis detection | T3 | DeepSeek-R1 | NVIDIA NIM (free) | $0 | Complex reasoning |

### 2.7 Output Format

```python
@dataclass(frozen=True)
class MacroState:
    """Published to tsar:stream:macro"""
    composite_score: float          # -1 (bearish) to +1 (bullish)
    regime: str                     # RISK_ON | RISK_OFF | TRANSITION | CRISIS
    components: dict[str, float]    # Individual indicator scores
    position_size_multiplier: float # 0.25 to 1.0
    direction_bias: str             # LONG | SHORT | NEUTRAL | NONE
    narrative: str | None           # LLM-generated explanation
    timestamp: datetime
    next_event: dict | None         # Next major macro event (date, type, impact)
```

### 2.8 Error Handling

| Error | Response |
|-------|----------|
| FRED API down | Use last known values for up to 24h, then flag stale |
| Trading Economics rate limited | Use FRED as fallback, reduce frequency |
| Stale data (>48h old) | Set regime to TRANSITION, flag data staleness |
| Conflicting signals | Default to TRANSITION regime, conservative sizing |

### 2.9 Performance Requirements

| Metric | Target | Max |
|--------|--------|-----|
| Macro score computation | <100ms | 500ms |
| Full state refresh | <5s | 15s |
| Memory | <128MB | 256MB |
| API calls per day | <500 | 1000 |

---

## 3. Economic Calendar Integration {#3-economic-calendar-integration}

### 3.1 Purpose

Automatically detect high-impact economic events and enforce **blackout rules** — periods where trading is paused or position sizes are reduced to avoid unpredictable volatility spikes.

### 3.2 Event Types & Impact Classification

| Event | Impact | Frequency | Typical Market Move | Blackout Window |
|-------|--------|-----------|---------------------|-----------------|
| **FOMC Rate Decision** | 🔴 CRITICAL | 8x/year | BTC ±3-8%, DXY ±1-2% | 60min before, 60min after |
| **FOMC Minutes** | 🟠 HIGH | 8x/year | BTC ±1-3% | 30min before, 30min after |
| **CPI (YoY)** | 🔴 CRITICAL | 12x/year | BTC ±2-5%, DXY ±0.5-1% | 30min before, 30min after |
| **Core CPI** | 🟠 HIGH | 12x/year | BTC ±1-3% | 30min before, 30min after |
| **Non-Farm Payrolls** | 🔴 CRITICAL | 12x/year | BTC ±2-4%, DXY ±0.5-1% | 30min before, 30min after |
| **ECB Rate Decision** | 🟠 HIGH | 8x/year | EUR/USD ±0.5-1% | 30min before, 30min after |
| **BOJ Rate Decision** | 🟠 HIGH | 8x/year | USD/JPY ±0.5-1%, BTC indirect | 30min before, 30min after |
| **GDP (Quarterly)** | 🟡 MEDIUM | 4x/year | BTC ±1-2% | 15min before, 15min after |
| **PCE (Fed's preferred)** | 🟠 HIGH | 12x/year | BTC ±1-3% | 30min before, 30min after |
| **ISM Manufacturing PMI** | 🟡 MEDIUM | 12x/year | BTC ±0.5-1% | 15min before, 15min after |
| **Initial Jobless Claims** | 🟢 LOW | Weekly | Minimal unless spike | None |
| **Consumer Confidence** | 🟢 LOW | Monthly | Minimal | None |
| **Retail Sales** | 🟡 MEDIUM | Monthly | BTC ±0.5-1% | 15min before, 15min after |

### 3.3 Data Sources

| Source | API | Cost | Coverage | Update Frequency |
|--------|-----|------|----------|------------------|
| **ForexFactory Calendar** | HTML scrape | $0 | All major events | Daily |
| **Trading Economics Calendar** | REST API | $0 (100 req/mo) | Global events | Real-time |
| **Investing.com Calendar** | HTML scrape | $0 | Comprehensive | Daily |
| **FRED Release Calendar** | `fredapi` | $0 | US economic data | Weekly |

**Primary:** ForexFactory (free, comprehensive, well-structured HTML)
**Fallback:** Trading Economics API (structured JSON, rate-limited)

### 3.4 Implementation

```python
class EconomicCalendar:
    """
    Fetches, caches, and enforces economic calendar blackout rules.
    Integrates with Risk Guardian for automatic trade filtering.
    """

    BLACKOUT_RULES = {
        # Event type: {before_min, after_min, size_reduction}
        "FOMC":           {"before_min": 60, "after_min": 60, "size_mult": 0.0},
        "FOMC_MINUTES":   {"before_min": 30, "after_min": 30, "size_mult": 0.5},
        "CPI":            {"before_min": 30, "after_min": 30, "size_mult": 0.0},
        "CORE_CPI":       {"before_min": 30, "after_min": 30, "size_mult": 0.5},
        "NFP":            {"before_min": 30, "after_min": 30, "size_mult": 0.0},
        "ECB":            {"before_min": 30, "after_min": 30, "size_mult": 0.5},
        "BOJ":            {"before_min": 30, "after_min": 30, "size_mult": 0.5},
        "GDP":            {"before_min": 15, "after_min": 15, "size_mult": 0.5},
        "PCE":            {"before_min": 30, "after_min": 30, "size_mult": 0.5},
        "ISM_MFG":        {"before_min": 15, "after_min": 15, "size_mult": 0.75},
        "RETAIL_SALES":   {"before_min": 15, "after_min": 15, "size_mult": 0.75},
    }

    def __init__(self, redis_client):
        self.redis = redis_client
        self.cache_key = "tsar:calendar:events"
        self.events: list[EconomicEvent] = []

    async def refresh(self):
        """Fetch calendar from ForexFactory and cache in Redis."""
        self.events = await self._fetch_forexfactory()
        self.redis.setex(self.cache_key, 86400, json.dumps(
            [e.to_dict() for e in self.events]
        ))
        return self.events

    async def _fetch_forexfactory(self) -> list[EconomicEvent]:
        """Parse ForexFactory calendar HTML."""
        import aiohttp
        from bs4 import BeautifulSoup

        url = "https://www.forexfactory.com/calendar?week=this"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')
        events = []
        for row in soup.select('tr.calendar__row'):
            event = self._parse_event_row(row)
            if event and event.impact in ['HIGH', 'CRITICAL']:
                events.append(event)
        return events

    def get_active_blackout(self) -> BlackoutState:
        """Check if current time falls within any blackout window."""
        now = datetime.utcnow()
        for event in self.events:
            if event.event_type not in self.BLACKOUT_RULES:
                continue

            rule = self.BLACKOUT_RULES[event.event_type]
            window_start = event.datetime - timedelta(minutes=rule["before_min"])
            window_end = event.datetime + timedelta(minutes=rule["after_min"])

            if window_start <= now <= window_end:
                return BlackoutState(
                    is_blackout=True,
                    event=event,
                    remaining_minutes=(window_end - now).total_seconds() / 60,
                    size_multiplier=rule["size_mult"],
                    reason=f"{event.event_type} blackout "
                           f"({rule['before_min']}min before, {rule['after_min']}min after)",
                )

        # Pre-event warning (1 hour before any HIGH+ event)
        upcoming = self._get_upcoming(hours=1)
        if upcoming:
            return BlackoutState(
                is_blackout=False,
                event=upcoming[0],
                remaining_minutes=(upcoming[0].datetime - now).total_seconds() / 60,
                size_multiplier=0.75,  # Reduce size before high-impact event
                reason=f"Upcoming {upcoming[0].event_type} in "
                       f"{(upcoming[0].datetime - now).total_seconds()/60:.0f} min",
            )

        return BlackoutState(is_blackout=False)

    def _get_upcoming(self, hours: int = 24) -> list[EconomicEvent]:
        """Get events within the next N hours."""
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours)
        return sorted(
            [e for e in self.events
             if now < e.datetime <= cutoff and e.impact in ['HIGH', 'CRITICAL']],
            key=lambda e: e.datetime
        )


@dataclass
class BlackoutState:
    is_blackout: bool
    event: EconomicEvent | None
    remaining_minutes: float
    size_multiplier: float  # 0.0 = no trades, 1.0 = normal
    reason: str


@dataclass
class EconomicEvent:
    event_type: str        # "FOMC", "CPI", "NFP", etc.
    datetime: datetime
    impact: str            # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    currency: str          # "USD", "EUR", "JPY"
    previous: float | None
    forecast: float | None
    actual: float | None   # Filled after release
    description: str
```

### 3.5 Integration with Risk Guardian

```python
# In Risk Guardian's evaluation checklist:
def evaluate_with_calendar(self, signal: Signal, calendar: EconomicCalendar) -> RiskDecision:
    blackout = calendar.get_active_blackout()

    if blackout.is_blackout and blackout.size_multiplier == 0.0:
        return RiskDecision(
            approved=False,
            reason=f"TRADE BLOCKED: {blackout.reason}",
            checks_passed="ECONOMIC_BLACKOUT",
        )

    if blackout.is_blackout and blackout.size_multiplier > 0:
        # Allow trade but reduce size
        signal.position_size *= blackout.size_multiplier
        signal.notes += f" [Size reduced: {blackout.reason}]"

    if not blackout.is_blackout and blackout.event:
        # Pre-event warning: reduce size
        signal.position_size *= blackout.size_multiplier
        signal.notes += f" [Pre-event caution: {blackout.reason}]"

    return self._standard_evaluation(signal)
```

### 3.6 Post-Release Analysis

After a major event is released, the Macro Agent:

1. Fetches the actual value (from Trading Economics or ForexFactory)
2. Compares actual vs forecast vs previous
3. Classifies the surprise: `BEAT`, `MISS`, `IN_LINE`
4. Updates macro state based on the surprise
5. Publishes event result to `tsar:stream:macro`

```python
def analyze_event_result(self, event: EconomicEvent) -> EventResult:
    """Analyze a released economic event."""
    if event.actual is None:
        return None

    surprise_pct = (event.actual - event.forecast) / abs(event.forecast) * 100

    if surprise_pct > 5:
        classification = "BEAT"
    elif surprise_pct < -5:
        classification = "MISS"
    else:
        classification = "IN_LINE"

    # Impact on macro score
    impact_map = {
        "NFP": lambda s: 0.3 if s == "BEAT" else (-0.3 if s == "MISS" else 0),
        "CPI": lambda s: -0.3 if s == "BEAT" else (0.3 if s == "MISS" else 0),  # High CPI = hawkish
        "GDP": lambda s: 0.2 if s == "BEAT" else (-0.2 if s == "MISS" else 0),
    }

    impact_fn = impact_map.get(event.event_type, lambda s: 0)
    score_adjustment = impact_fn(classification)

    return EventResult(
        event=event,
        surprise_pct=surprise_pct,
        classification=classification,
        macro_score_adjustment=score_adjustment,
    )
```

### 3.7 Day1 vs Full

| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Calendar source | Hardcoded FOMC/CPI/NFP dates (2026) | Live ForexFactory feed |
| Blackout enforcement | Manual (Signal Agent checks dates) | Automatic in Risk Guardian |
| Post-release analysis | None | Actual vs forecast comparison |
| Position adjustment | Binary (trade/don't trade) | Graduated (0%, 50%, 75%, 100%) |

---

## 4. Sentiment Analysis {#4-sentiment-analysis}

### 4.1 Purpose

Quantify market sentiment from multiple sources to provide a **contrarian signal** (extreme fear = buy opportunity, extreme greed = sell opportunity) and a **confidence filter** (high conviction when sentiment aligns with technicals).

### 4.2 Data Sources

| Source | Type | API | Cost | Latency | Coverage |
|--------|------|-----|------|---------|----------|
| **Alternative.me Fear & Greed Index** | Composite | REST | $0 | 15 min | Crypto overall |
| **CryptoPanic** | News aggregator | REST (free: 100 req/day) | $0 | Real-time | Crypto news |
| **Twitter/X (via Nitter)** | Social | Scrape | $0 | 15 min | Crypto Twitter |
| **Reddit (r/cryptocurrency)** | Social | PRAW (Reddit API) | $0 | 30 min | Reddit sentiment |
| **LunarCrush** | Social analytics | REST (free tier) | $0 | 15 min | Social volume + sentiment |
| **Google Trends** | Search interest | `pytrends` | $0 | Daily | Search volume for "bitcoin" |

### 4.3 Sentiment Score Components

```
COMPOSITE SENTIMENT SCORE (-1 to +1)
═════════════════════════════════════

Component 1: Fear & Greed Index (weight: 30%)
├── Source: Alternative.me
├── Raw: 0-100 (0=extreme fear, 100=extreme greed)
├── Normalized: -1 to +1
└── Logic: (value - 50) / 50

Component 2: News Sentiment (weight: 40%)
├── Source: CryptoPanic headlines
├── Method: LLM scoring (Ollama Qwen2.5-7B)
├── Score: -1 (bearish) to +1 (bullish)
└── Logic: Score last 10 headlines, take average

Component 3: Social Sentiment (weight: 30%)
├── Source: Twitter/X + Reddit
├── Method: Volume-weighted sentiment
├── Score: -1 (bearish) to +1 (bullish)
└── Logic: (positive_ratio - negative_ratio) * volume_factor
```

### 4.4 Implementation

```python
class SentimentAnalyzer:
    """Multi-source sentiment scoring for crypto markets."""

    WEIGHTS = {
        "fear_greed": 0.30,
        "news": 0.40,
        "social": 0.30,
    }

    def __init__(self, ollama_client, redis_client):
        self.ollama = ollama_client
        self.redis = redis_client

    async def get_composite_sentiment(self, symbol: str = "BTC") -> SentimentScore:
        """Get weighted sentiment from all sources."""
        components = {}

        # 1. Fear & Greed Index
        fg = await self._get_fear_greed()
        components["fear_greed"] = SentimentComponent(
            score=(fg["value"] - 50) / 50,
            weight=self.WEIGHTS["fear_greed"],
            raw_value=fg["value"],
            classification=fg["classification"],  # "Extreme Fear" to "Extreme Greed"
            source="alternative.me",
        )

        # 2. News Sentiment (LLM-scored)
        news_score = await self._score_news_sentiment(symbol)
        components["news"] = SentimentComponent(
            score=news_score,
            weight=self.WEIGHTS["news"],
            source="cryptopanic",
        )

        # 3. Social Sentiment
        social_score = await self._score_social_sentiment(symbol)
        components["social"] = SentimentComponent(
            score=social_score,
            weight=self.WEIGHTS["social"],
            source="twitter+reddit",
        )

        # Composite
        composite = sum(c.score * c.weight for c in components.values())

        # Contrarian signal: extreme readings are reversal signals
        contrarian_signal = self._compute_contrarian(composite)

        return SentimentScore(
            symbol=symbol,
            composite=composite,
            contrarian_signal=contrarian_signal,
            components=components,
            timestamp=datetime.utcnow(),
        )

    async def _get_fear_greed(self) -> dict:
        """Fetch Fear & Greed Index from Alternative.me."""
        import aiohttp
        url = "https://api.alternative.me/fng/?limit=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return {
                    "value": int(data["data"][0]["value"]),
                    "classification": data["data"][0]["value_classification"],
                }

    async def _score_news_sentiment(self, symbol: str) -> float:
        """Use Ollama to score CryptoPanic headlines."""
        headlines = await self._fetch_cryptopanic(symbol, limit=10)
        if not headlines:
            return 0.0

        prompt = f"""Score the sentiment of these crypto news headlines for {symbol}.
Return ONLY a number from -1.0 (extreme bearish) to +1.0 (extreme bullish).
Consider the overall tone, not individual words.

Headlines:
{chr(10).join(f'- {h.title}' for h in headlines)}

Score:"""

        response = await self.ollama.generate(prompt, model="qwen2.5:7b")
        try:
            return max(-1.0, min(1.0, float(response.strip())))
        except ValueError:
            return 0.0

    async def _score_social_sentiment(self, symbol: str) -> float:
        """Score social media sentiment from Twitter + Reddit."""
        # Twitter: scrape via Nitter or use LunarCrush API
        twitter_score = await self._get_twitter_sentiment(symbol)
        # Reddit: PRAW sentiment analysis
        reddit_score = await self._get_reddit_sentiment(symbol)

        # Weighted average (Twitter is faster-moving)
        if twitter_score is not None and reddit_score is not None:
            return twitter_score * 0.6 + reddit_score * 0.4
        elif twitter_score is not None:
            return twitter_score
        elif reddit_score is not None:
            return reddit_score
        return 0.0

    def _compute_contrarian(self, composite: float) -> float:
        """
        Contrarian signal: extreme sentiment readings suggest reversal.
        Returns: -1 (strong sell signal) to +1 (strong buy signal)
        """
        # Extreme fear (< -0.6) → buy signal
        if composite < -0.6:
            return 0.8  # Strong buy (contrarian)
        elif composite < -0.3:
            return 0.3  # Mild buy
        elif composite > 0.6:
            return -0.8  # Strong sell (contrarian)
        elif composite > 0.3:
            return -0.3  # Mild sell
        return 0.0  # No contrarian signal


@dataclass(frozen=True)
class SentimentScore:
    symbol: str
    composite: float              # -1 to +1
    contrarian_signal: float      # -1 to +1 (reversal signal)
    components: dict[str, SentimentComponent]
    timestamp: datetime

@dataclass(frozen=True)
class SentimentComponent:
    score: float
    weight: float
    source: str
    raw_value: float | None = None
    classification: str | None = None
```

### 4.5 Integration with Signal Agent

Sentiment feeds into Signal Agent scoring as a weighted factor:

```python
# In Signal Agent's scoring breakdown:
SCORING_WEIGHTS = {
    "rsi_extreme":        0.30,  # Technical: RSI
    "sr_proximity":       0.25,  # Technical: Support/Resistance
    "volume_confirmation": 0.10, # Technical: Volume
    "sentiment":          0.15,  # Market Analysis: Sentiment
    "macro_alignment":    0.10,  # Market Analysis: Macro regime
    "seasonal":           0.05,  # Market Analysis: Time patterns
    "order_flow":         0.05,  # Market Analysis: Order flow
}

def compute_signal_score(self, technical_score, sentiment: SentimentScore,
                         macro: MacroState, seasonal: SeasonalState) -> float:
    """Combine technical and market analysis scores."""
    # Sentiment alignment: if technical says buy and sentiment is bearish
    # (contrarian), boost the signal
    sentiment_factor = 0.0
    if sentiment.contrarian_signal != 0:
        # Contrarian: extreme fear + technical buy = stronger signal
        sentiment_factor = sentiment.contrarian_signal * 0.5
    else:
        # Trend following: sentiment aligns with technical direction
        sentiment_factor = sentiment.composite * 0.3

    return (
        technical_score * (self.SCORING_WEIGHTS["rsi_extreme"] +
                          self.SCORING_WEIGHTS["sr_proximity"] +
                          self.SCORING_WEIGHTS["volume_confirmation"]) +
        sentiment_factor * self.SCORING_WEIGHTS["sentiment"] +
        macro.composite_score * self.SCORING_WEIGHTS["macro_alignment"] +
        seasonal.score * self.SCORING_WEIGHTS["seasonal"]
    )
```

### 4.6 Day1 vs Full

| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Sources | Fear & Greed only | Fear & Greed + News + Social |
| Scoring | Rule-based (index value) | LLM-powered headline analysis |
| Weight in signal | 10% | 15% |
| Contrarian logic | Simple threshold | Multi-source contrarian scoring |
| Agent | Inline in Signal Agent | Dedicated Sentiment Agent (Level 3) |

---

## 5. On-Chain Analytics {#5-on-chain-analytics}

### 5.1 Purpose

Detect **smart money movements** (whales accumulating/distributing), **exchange flows** (coins moving to/from exchanges = sell/buy pressure), and **network health metrics** that predict price moves before they show up in technical indicators.

### 5.2 Key Metrics

| Metric | What It Measures | Signal | Source |
|--------|-----------------|--------|--------|
| **Exchange Net Flow** | Coins moving to/from exchanges | Negative = accumulation (bullish), Positive = distribution (bearish) | CryptoQuant / CoinGecko |
| **Whale Transactions** | Transfers > $1M | Whale buying = bullish, whale selling = bearish | Whale Alert / Blockchair |
| **MVRV Ratio** | Market Value / Realized Value | >3.5 = overvalued, <1.0 = undervalued | CoinMetrics (free tier) |
| **NVT Ratio** | Network Value / Transaction Volume | High NVT = overvalued relative to usage | CoinMetrics |
| **Active Addresses** | Daily unique addresses | Rising = network growth (bullish) | CoinGecko |
| **Exchange Reserves** | Total BTC on exchanges | Declining = accumulation (bullish) | CryptoQuant |
| **Stablecoin Supply** | USDT/USDC market cap | Rising = dry powder for buying | CoinGecko |
| **Miner Revenue** | Miner income | Declining = miner stress (potential sell pressure) | CoinMetrics |
| **DeFi TVL** | Total Value Locked | Rising = ecosystem health | DeFiLlama |
| **Funding Rates** | Perpetual futures funding | Positive = longs pay shorts (crowded long), Negative = crowded short | Binance / Coinglass |

### 5.3 Data Sources

| Source | API | Cost | Metrics | Rate Limit |
|--------|-----|------|---------|------------|
| **CoinGecko** | REST | $0 (free tier) | Price, volume, market cap, active addresses | 30 req/min |
| **CryptoQuant** | REST | $0 (limited) | Exchange flow, reserves | 10 req/day |
| **Whale Alert** | REST | $0 (free tier) | Large transactions | 10 req/min |
| **DeFiLlama** | REST | $0 | DeFi TVL, yields | Unlimited |
| **Alternative.me** | REST | $0 | Fear & Greed | Unlimited |
| **Blockchair** | REST | $0 (limited) | Blockchain stats | 30 req/min |
| **CoinMetrics** | REST | $0 (community) | MVRV, NVT, supply | 100 req/day |
| **Coinglass** | REST | $0 (limited) | Funding rates, open interest | 20 req/day |

### 5.4 On-Chain Score Computation

```python
class OnChainAnalyzer:
    """
    Computes on-chain health and whale activity scores.
    Output: OnChainState published to tsar:stream:onchain
    """

    METRIC_WEIGHTS = {
        "exchange_flow":     0.25,  # Most predictive short-term
        "whale_activity":    0.20,  # Smart money signal
        "mvrv":              0.15,  # Valuation
        "stablecoin_supply": 0.15,  # Dry powder
        "funding_rates":     0.15,  # Positioning
        "network_activity":  0.10,  # Fundamental health
    }

    async def compute_onchain_state(self, symbol: str = "BTC") -> OnChainState:
        """Compute composite on-chain state."""
        scores = {}

        # 1. Exchange Net Flow
        flow = await self._get_exchange_flow(symbol)
        scores["exchange_flow"] = OnChainMetric(
            name="Exchange Net Flow",
            value=flow,
            score=self._score_exchange_flow(flow),
            interpretation="Negative = accumulation (bullish)",
        )

        # 2. Whale Activity
        whale = await self._get_whale_activity(symbol)
        scores["whale_activity"] = OnChainMetric(
            name="Whale Activity",
            value=whale["net_direction"],
            score=self._score_whale_activity(whale),
            interpretation="Positive = whale buying (bullish)",
        )

        # 3. MVRV Ratio
        mvrv = await self._get_mvrv(symbol)
        scores["mvrv"] = OnChainMetric(
            name="MVRV Ratio",
            value=mvrv,
            score=self._score_mvrv(mvrv),
            interpretation="<1 = undervalued, >3.5 = overvalued",
        )

        # 4. Stablecoin Supply Change
        stablecoin_delta = await self._get_stablecoin_supply_change()
        scores["stablecoin_supply"] = OnChainMetric(
            name="Stablecoin Supply Change",
            value=stablecoin_delta,
            score=self._score_stablecoin(stablecoin_delta),
            interpretation="Rising = dry powder accumulating (bullish)",
        )

        # 5. Funding Rates
        funding = await self._get_funding_rate(symbol)
        scores["funding_rates"] = OnChainMetric(
            name="Funding Rate",
            value=funding,
            score=self._score_funding(funding),
            interpretation="High positive = crowded long (bearish signal)",
        )

        # 6. Network Activity
        active_addr = await self._get_active_addresses(symbol)
        scores["network_activity"] = OnChainMetric(
            name="Active Addresses",
            value=active_addr,
            score=self._score_network_activity(active_addr, symbol),
            interpretation="Rising = network health (bullish)",
        )

        # Composite score
        composite = sum(
            s.score * self.METRIC_WEIGHTS[name]
            for name, s in scores.items()
        )

        return OnChainState(
            symbol=symbol,
            composite_score=composite,
            metrics=scores,
            timestamp=datetime.utcnow(),
        )

    def _score_exchange_flow(self, flow: float) -> float:
        """Score exchange net flow. Negative = bullish (coins leaving exchanges)."""
        # flow in BTC: negative = outflow, positive = inflow
        if flow < -5000:    # Major outflow
            return 0.8
        elif flow < -1000:
            return 0.4
        elif flow > 5000:   # Major inflow
            return -0.8
        elif flow > 1000:
            return -0.4
        return 0.0

    def _score_whale_activity(self, whale: dict) -> float:
        """Score whale buying vs selling."""
        buy_volume = whale.get("buy_volume_usd", 0)
        sell_volume = whale.get("sell_volume_usd", 0)
        total = buy_volume + sell_volume
        if total == 0:
            return 0.0
        return (buy_volume - sell_volume) / total  # -1 to +1

    def _score_mvrv(self, mvrv: float) -> float:
        """Score MVRV ratio. <1 = undervalued, >3.5 = overvalued."""
        if mvrv < 1.0:
            return 0.8   # Very undervalued
        elif mvrv < 1.5:
            return 0.4
        elif mvrv > 3.5:
            return -0.8  # Very overvalued
        elif mvrv > 2.5:
            return -0.4
        return 0.0

    def _score_funding(self, funding: float) -> float:
        """Score funding rate. Positive = crowded long = bearish."""
        if funding > 0.05:    # 5% annualized = very crowded long
            return -0.7
        elif funding > 0.01:
            return -0.3
        elif funding < -0.05: # Crowded short
            return 0.7
        elif funding < -0.01:
            return 0.3
        return 0.0


@dataclass(frozen=True)
class OnChainState:
    symbol: str
    composite_score: float          # -1 to +1
    metrics: dict[str, OnChainMetric]
    timestamp: datetime

@dataclass(frozen=True)
class OnChainMetric:
    name: str
    value: float
    score: float
    interpretation: str
```

### 5.5 Whale Alert Integration

```python
class WhaleAlertTracker:
    """Track large transactions that signal smart money moves."""

    WHALE_THRESHOLD_USD = 1_000_000  # $1M+ transactions

    async def get_recent_whale_moves(self, symbol: str = "BTC") -> list[WhaleMove]:
        """Fetch recent whale transactions from Whale Alert API."""
        import aiohttp
        url = "https://api.whale-alert.io/v1/transactions"
        params = {
            "api_key": self.api_key,
            "min_value": self.WHALE_THRESHOLD_USD,
            "currency": symbol.lower(),
            "limit": 20,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()

        moves = []
        for tx in data.get("transactions", []):
            moves.append(WhaleMove(
                tx_hash=tx["hash"],
                symbol=symbol,
                amount_usd=tx["amount_usd"],
                from_type=tx["from"]["owner_type"],  # "exchange", "whale", "unknown"
                to_type=tx["to"]["owner_type"],
                timestamp=datetime.fromtimestamp(tx["timestamp"]),
            ))

        return moves

    def analyze_whale_moves(self, moves: list[WhaleMove]) -> WhaleSignal:
        """Interpret whale moves as bullish/bearish."""
        exchange_inflows = sum(m.amount_usd for m in moves
                              if m.to_type == "exchange")
        exchange_outflows = sum(m.amount_usd for m in moves
                               if m.from_type == "exchange")

        net_flow = exchange_outflows - exchange_inflows
        # Positive = coins leaving exchanges = bullish

        if net_flow > 10_000_000:
            signal = 0.7   # Strong accumulation
        elif net_flow > 2_000_000:
            signal = 0.3
        elif net_flow < -10_000_000:
            signal = -0.7  # Strong distribution
        elif net_flow < -2_000_000:
            signal = -0.3
        else:
            signal = 0.0

        return WhaleSignal(
            net_flow_usd=net_flow,
            signal=signal,
            total_moves=len(moves),
            total_volume_usd=sum(m.amount_usd for m in moves),
        )
```

### 5.6 Day1 vs Full

| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Metrics | Fear & Greed + Funding Rate only | Full suite (6+ metrics) |
| Data sources | CoinGecko + Alternative.me | CryptoQuant + Whale Alert + CoinMetrics + DeFiLlama |
| Whale tracking | None | Real-time whale alert integration |
| MVRV/NVT | None | Daily computation |
| DeFi metrics | None | TVL, yields, protocol flows |

---

## 6. Geopolitical Analysis {#6-geopolitical-analysis}

### 6.1 Purpose

Detect geopolitical events that can cause **sudden, correlated market dislocations** — wars, sanctions, elections, trade wars — and adjust risk posture accordingly.

### 6.2 Event Types & Market Impact

| Event Type | Historical Impact on BTC | Historical Impact on DXY | Response |
|------------|-------------------------|-------------------------|----------|
| **War/Military Conflict** | Short-term dump → recovery (safe haven narrative) | DXY up (flight to safety) | Reduce size 50%, widen stops |
| **Sanctions** | Depends on target (Russia sanctions → BTC pump as alternative) | Mixed | Reduce size 25% |
| **Elections** | Volatility spike, direction depends on outcome | Significant moves | Reduce size 50% around election day |
| **Trade Wars** | BTC down with risk assets initially | DXY up | Reduce size 25% |
| **Regulatory Crackdown** | BTC dumps (China ban 2021: -50%) | Minimal | Halt if targeted at crypto |
| **Debt Ceiling / Government Shutdown** | Risk-off initially | DXY mixed | Reduce size 50% |
| **Pandemic / Health Crisis** | Initial dump → recovery (stimulus narrative) | DXY initially up | Halt trading initially |

### 6.3 Detection Methods

| Method | Source | Cost | Coverage | Latency |
|--------|--------|------|----------|---------|
| **News API (GNews)** | REST | $0 (100 req/day) | Global news | Real-time |
| **RSS Feeds (Reuters, AP)** | RSS | $0 | Breaking news | Near real-time |
| **GDELT Project** | REST | $0 | Global event database | 15 min |
| **Twitter/X trending** | Scrape | $0 | Real-time events | 15 min |
| **LLM Classification** | Ollama | $0 (local) | Event severity scoring | On detection |

### 6.4 Implementation

```python
class GeopoliticalAnalyzer:
    """
    Monitors geopolitical events and adjusts risk posture.
    Not a signal generator — a risk filter.
    """

    # Event severity → response
    SEVERITY_RESPONSES = {
        "LOW":      {"size_mult": 1.0, "halt": False, "alert": False},
        "MEDIUM":   {"size_mult": 0.75, "halt": False, "alert": True},
        "HIGH":     {"size_mult": 0.50, "halt": False, "alert": True},
        "CRITICAL": {"size_mult": 0.25, "halt": True, "alert": True},
    }

    async def scan_for_events(self) -> list[GeoEvent]:
        """Scan news sources for geopolitical events."""
        events = []

        # Scan GDELT for high-impact events
        gdelt_events = await self._scan_gdelt()
        events.extend(gdelt_events)

        # Scan RSS feeds
        rss_events = await self._scan_rss_feeds()
        events.extend(rss_events)

        # LLM classification of severity
        for event in events:
            event.severity = await self._classify_severity(event)

        return [e for e in events if e.severity in ["MEDIUM", "HIGH", "CRITICAL"]]

    async def _classify_severity(self, event: GeoEvent) -> str:
        """Use LLM to classify event severity for markets."""
        prompt = f"""Classify the market impact severity of this geopolitical event.

Event: {event.title}
Description: {event.description}

Consider:
1. Direct impact on financial markets
2. Impact on USD strength
3. Impact on risk appetite
4. Duration of impact (temporary vs structural)

Respond with ONLY one word: LOW, MEDIUM, HIGH, or CRITICAL"""

        response = await self.ollama.generate(prompt, model="qwen2.5:7b")
        severity = response.strip().upper()
        return severity if severity in ["LOW", "MEDIUM", "HIGH", "CRITICAL"] else "MEDIUM"

    def get_current_risk_posture(self) -> GeoRiskPosture:
        """Get current geopolitical risk posture."""
        active_events = self._get_active_events(hours=48)

        if not active_events:
            return GeoRiskPosture(
                level="NORMAL",
                size_multiplier=1.0,
                events=[],
            )

        # Use the most severe event to determine posture
        max_severity = max(e.severity for e in active_events)
        response = self.SEVERITY_RESPONSES[max_severity]

        return GeoRiskPosture(
            level=max_severity,
            size_multiplier=response["size_mult"],
            halt_trading=response["halt"],
            events=active_events,
        )


@dataclass
class GeoEvent:
    title: str
    description: str
    event_type: str          # "war", "sanctions", "election", etc.
    severity: str            # LOW, MEDIUM, HIGH, CRITICAL
    affected_assets: list[str]  # ["BTC", "DXY", "Gold"]
    detected_at: datetime
    source: str

@dataclass
class GeoRiskPosture:
    level: str
    size_multiplier: float
    halt_trading: bool = False
    events: list[GeoEvent] = field(default_factory=list)
```

### 6.5 Day1 vs Full

| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Detection | None (manual monitoring) | Automated news scanning + LLM classification |
| Response | None | Automatic position size reduction |
| Coverage | None | War, sanctions, elections, trade wars, regulation |

---

## 7. Cross-Asset Correlation {#7-cross-asset-correlation}

### 7.1 Why Correlations Matter

Cross-asset correlations determine **portfolio risk** and **signal quality**:

- **DXY ↑ → BTC ↓** (historically): Strong dollar = crypto headwind
- **Gold ↑ → BTC ↑** (sometimes): Safe haven demand alignment
- **VIX ↑ → BTC ↓** (fear regime): Risk-off selling
- **Bond yields ↑ → BTC ↓** (rising rates): Opportunity cost of holding non-yielding assets
- **S&P 500 ↑ → BTC ↑** (risk-on): Correlated risk appetite
- **ETH/BTC ratio ↑** → alt-season (rotation within crypto)

When correlations break down, it signals **regime change** and requires strategy adjustment.

### 7.2 Key Correlations to Monitor

| Pair | Expected Direction | Use Case | Data Source |
|------|-------------------|----------|-------------|
| DXY ↔ BTC | Inverse (-0.5 to -0.7) | Dollar strength = BTC headwind | Yahoo Finance (DXY=F) |
| DXY ↔ Gold | Inverse (-0.3 to -0.6) | Dollar strength = gold headwind | Yahoo Finance (GC=F) |
| 10Y Yield ↔ BTC | Inverse (-0.3 to -0.5) | Rising yields = BTC headwind | Yahoo Finance (^TNX) |
| VIX ↔ BTC | Inverse (-0.4 to -0.6) | Fear = crypto selling | Yahoo Finance (^VIX) |
| S&P 500 ↔ BTC | Positive (0.3 to 0.6) | Risk appetite correlation | Yahoo Finance (^GSPC) |
| BTC ↔ ETH | Positive (0.8 to 0.95) | Crypto beta | CoinGecko |
| BTC ↔ Altcoins | Positive (0.6 to 0.9) | Alt-season timing | CoinGecko |
| Gold ↔ BTC | Variable (-0.2 to +0.3) | Safe haven competition | Yahoo Finance (GC=F) |
| Oil ↔ DXY | Inverse (-0.3 to -0.5) | Petrodollar dynamics | Yahoo Finance (CL=F) |

### 7.3 Implementation

```python
class CrossAssetCorrelationEngine:
    """
    Monitors cross-asset correlations and detects regime changes.
    Extends Market Cartographer's correlation engine with macro-asset pairs.
    """

    MACRO_PAIRS = [
        ("BTC-USD", "DX-Y.NYB"),     # BTC vs DXY
        ("BTC-USD", "^TNX"),          # BTC vs 10Y yield
        ("BTC-USD", "^VIX"),          # BTC vs VIX
        ("BTC-USD", "^GSPC"),         # BTC vs S&P 500
        ("BTC-USD", "GC=F"),          # BTC vs Gold
        ("DX-Y.NYB", "GC=F"),         # DXY vs Gold
        ("^VIX", "^GSPC"),            # VIX vs S&P
    ]

    def __init__(self, redis_client):
        self.redis = redis_client
        self.correlation_cache: dict[str, RollingCorrelation] = {}

    async def compute_correlations(self, window_days: int = 30) -> CorrelationMatrix:
        """Compute rolling correlations for all macro pairs."""
        import yfinance as yf

        # Fetch price data for all unique tickers
        tickers = set()
        for a, b in self.MACRO_PAIRS:
            tickers.add(a)
            tickers.add(b)

        prices = {}
        for ticker in tickers:
            data = yf.download(ticker, period=f"{window_days}d", interval="1d", progress=False)
            if not data.empty:
                prices[ticker] = data["Close"]

        # Compute pairwise correlations
        correlations = {}
        for pair_a, pair_b in self.MACRO_PAIRS:
            if pair_a in prices and pair_b in prices:
                # Align dates
                aligned = pd.DataFrame({
                    pair_a: prices[pair_a],
                    pair_b: prices[pair_b]
                }).dropna()

                if len(aligned) >= 20:
                    corr = aligned[pair_a].corr(aligned[pair_b])
                    key = f"{pair_a}_vs_{pair_b}"
                    correlations[key] = CorrelationPair(
                        asset_a=pair_a,
                        asset_b=pair_b,
                        correlation=corr,
                        window_days=window_days,
                        sample_size=len(aligned),
                    )

        # Detect anomalies
        anomalies = self._detect_anomalies(correlations)

        return CorrelationMatrix(
            pairs=correlations,
            anomalies=anomalies,
            regime=self._classify_correlation_regime(correlations),
            timestamp=datetime.utcnow(),
        )

    def _detect_anomalies(self, correlations: dict) -> list[CorrelationAnomaly]:
        """Detect when correlations deviate significantly from historical norms."""
        anomalies = []
        HISTORICAL_NORMS = {
            "BTC-USD_vs_DX-Y.NYB": -0.5,
            "BTC-USD_vs_^VIX": -0.45,
            "BTC-USD_vs_^GSPC": 0.45,
            "BTC-USD_vs_GC=F": 0.1,
        }

        for key, pair in correlations.items():
            if key in HISTORICAL_NORMS:
                expected = HISTORICAL_NORMS[key]
                deviation = abs(pair.correlation - expected)
                if deviation > 0.4:  # Significant deviation
                    anomalies.append(CorrelationAnomaly(
                        pair=key,
                        expected=expected,
                        actual=pair.correlation,
                        deviation=deviation,
                        interpretation=self._interpret_anomaly(key, pair.correlation, expected),
                    ))

        return anomalies

    def _interpret_anomaly(self, pair: str, actual: float, expected: float) -> str:
        """Generate human-readable interpretation of correlation anomaly."""
        if "BTC-USD_vs_DX-Y.NYB" in pair:
            if actual > 0:
                return "BTC and DXY moving together — UNUSUAL. Possible regime change or specific catalyst driving both."
            else:
                return "BTC-DXY correlation more negative than usual — dollar strength is a strong headwind."
        return f"Correlation ({actual:.2f}) deviates significantly from norm ({expected:.2f})"

    def _classify_correlation_regime(self, correlations: dict) -> str:
        """Classify the current correlation regime."""
        btc_dxy = correlations.get("BTC-USD_vs_DX-Y.NYB")
        btc_vix = correlations.get("BTC-USD_vs_^VIX")
        btc_spy = correlations.get("BTC-USD_vs_^GSPC")

        if not all([btc_dxy, btc_vix, btc_spy]):
            return "UNKNOWN"

        # Risk-on: BTC positively correlated with stocks, negatively with DXY/VIX
        if (btc_spy.correlation > 0.3 and btc_dxy.correlation < -0.3 and
            btc_vix.correlation < -0.3):
            return "RISK_ON"

        # Risk-off: BTC negatively correlated with stocks, positively with VIX
        if (btc_spy.correlation < -0.2 and btc_vix.correlation > 0.2):
            return "RISK_OFF"

        # Decoupled: BTC independent of traditional markets
        if (abs(btc_spy.correlation) < 0.2 and abs(btc_dxy.correlation) < 0.2):
            return "DECOUPLED"

        return "TRANSITION"


@dataclass(frozen=True)
class CorrelationMatrix:
    pairs: dict[str, CorrelationPair]
    anomalies: list[CorrelationAnomaly]
    regime: str
    timestamp: datetime

@dataclass(frozen=True)
class CorrelationPair:
    asset_a: str
    asset_b: str
    correlation: float
    window_days: int
    sample_size: int

@dataclass(frozen=True)
class CorrelationAnomaly:
    pair: str
    expected: float
    actual: float
    deviation: float
    interpretation: str
```

### 7.4 Integration with Market Cartographer

This module **extends** the existing Market Cartographer agent (defined in `trading-super-agent-spec.md` §3.8) by adding macro-asset pairs to its correlation universe:

```
Market Cartographer (existing):
  - BTC ↔ ETH, BTC ↔ BNB, etc. (crypto-internal)
  - Cointegration, PCA, Granger causality
  - Rust engine for speed

Cross-Asset Correlation (this module):
  - BTC ↔ DXY, BTC ↔ Gold, BTC ↔ VIX, etc. (macro-external)
  - Yahoo Finance for traditional assets
  - Python (yfinance) — less speed-critical, daily/hourly updates

Both publish to tsar:stream:cartography
```

### 7.5 Day1 vs Full

| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Pairs | BTC ↔ DXY only | Full macro pair universe (7+ pairs) |
| Frequency | Daily | Hourly (with regime change triggers) |
| Anomaly detection | None | Automated with LLM interpretation |
| Regime classification | None | RISK_ON / RISK_OFF / DECOUPLED / TRANSITION |

---

## 8. Order Flow Analysis {#8-order-flow-analysis}

### 8.1 Purpose

Detect **short-term supply/demand imbalances** from order book data and trade flow that predict the next 1-15 minutes of price action. This is the most granular, fastest-decaying signal in the Market Analysis layer.

### 8.2 Metrics

| Metric | What It Measures | Signal | Timeframe |
|--------|-----------------|--------|-----------|
| **Order Book Imbalance** | Bid vs ask volume at top 10 levels | Ratio > 1.5 = buy pressure, < 0.67 = sell pressure | 1-5 min |
| **Volume Delta** | Aggressive buys - aggressive sells | Positive = buying pressure, Negative = selling pressure | 1-5 min |
| **CVD (Cumulative Volume Delta)** | Running sum of volume delta | Divergence from price = potential reversal | 5-15 min |
| **Volume Profile** | Volume at each price level | High-volume node = support/resistance | Session-based |
| **Large Trade Detection** | Trades > X BTC | Institutional activity detection | Real-time |
| **Trade Size Distribution** | % of volume from large vs small trades | Whale vs retail activity | 5-15 min |
| **Bid-Ask Spread** | Spread width | Narrow = liquid, Wide = uncertain | Real-time |
| **Depth Imbalance** | Total bid depth vs ask depth | Skew = directional pressure | Real-time |

### 8.3 Data Source

| Source | API | Cost | Data | Latency |
|--------|-----|------|------|---------|
| **Binance WebSocket** | WS | $0 | Order book, trades | Real-time (<100ms) |
| **Binance REST** | REST | $0 | Order book snapshot | 1-3 sec |

### 8.4 Implementation

```python
class OrderFlowAnalyzer:
    """
    Analyzes order book and trade flow for short-term signals.
    Connects to Binance WebSocket for real-time data.
    """

    def __init__(self, ws_manager):
        self.ws = ws_manager
        self.order_book: OrderBook = OrderBook()
        self.trade_buffer: deque = deque(maxlen=10000)
        self.volume_profile: dict[float, float] = {}  # price → volume

    async def start(self, symbol: str = "BTCUSDT"):
        """Subscribe to order book and trade streams."""
        await self.ws.subscribe(f"{symbol.lower()}@depth10@100ms",
                               self._on_orderbook_update)
        await self.ws.subscribe(f"{symbol.lower()}@trade",
                               self._on_trade)

    def _on_orderbook_update(self, data: dict):
        """Process order book update."""
        self.order_book.update(data)
        self._compute_imbalance()

    def _on_trade(self, data: dict):
        """Process individual trade."""
        trade = Trade(
            price=float(data["p"]),
            quantity=float(data["q"]),
            side="BUY" if data["m"] else "SELL",  # m=true = buyer is maker = sell
            timestamp=data["T"],
        )
        self.trade_buffer.append(trade)
        self.volume_profile[round(trade.price, 1)] = \
            self.volume_profile.get(round(trade.price, 1), 0) + trade.quantity

    def get_order_flow_signal(self) -> OrderFlowSignal:
        """Compute current order flow signal."""
        # 1. Order Book Imbalance
        book_imbalance = self._compute_book_imbalance()

        # 2. Volume Delta (last 5 minutes)
        vol_delta = self._compute_volume_delta(minutes=5)

        # 3. CVD divergence
        cvd_divergence = self._detect_cvd_divergence()

        # 4. Large trade activity
        large_trades = self._detect_large_trades()

        # Composite score
        score = (
            book_imbalance.score * 0.35 +
            vol_delta.score * 0.35 +
            cvd_divergence.score * 0.20 +
            large_trades.score * 0.10
        )

        return OrderFlowSignal(
            score=score,
            book_imbalance=book_imbalance,
            volume_delta=vol_delta,
            cvd_divergence=cvd_divergence,
            large_trades=large_trades,
            timestamp=datetime.utcnow(),
        )

    def _compute_book_imbalance(self) -> BookImbalance:
        """Compute order book imbalance ratio."""
        bids = self.order_book.bids[:10]  # Top 10 levels
        asks = self.order_book.asks[:10]

        bid_volume = sum(qty for _, qty in bids)
        ask_volume = sum(qty for _, qty in asks)

        if ask_volume == 0:
            ratio = 10.0
        else:
            ratio = bid_volume / ask_volume

        # Score: ratio > 1.5 = bullish, < 0.67 = bearish
        if ratio > 2.0:
            score = 0.8
        elif ratio > 1.5:
            score = 0.4
        elif ratio < 0.5:
            score = -0.8
        elif ratio < 0.67:
            score = -0.4
        else:
            score = 0.0

        return BookImbalance(
            bid_volume=bid_volume,
            ask_volume=ask_volume,
            ratio=ratio,
            score=score,
        )

    def _compute_volume_delta(self, minutes: int = 5) -> VolumeDelta:
        """Compute net buying vs selling volume."""
        cutoff = time.time() * 1000 - minutes * 60 * 1000
        recent = [t for t in self.trade_buffer if t.timestamp > cutoff]

        buy_volume = sum(t.quantity for t in recent if t.side == "BUY")
        sell_volume = sum(t.quantity for t in recent if t.side == "SELL")
        net_delta = buy_volume - sell_volume

        total = buy_volume + sell_volume
        if total == 0:
            score = 0.0
        else:
            normalized = net_delta / total  # -1 to +1
            score = max(-1, min(1, normalized * 2))  # Amplify signal

        return VolumeDelta(
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            net_delta=net_delta,
            score=score,
            timeframe_min=minutes,
        )

    def _detect_cvd_divergence(self) -> CVDDivergence:
        """
        Detect divergence between CVD and price.
        Price up + CVD down = bearish divergence (distribution)
        Price down + CVD up = bullish divergence (accumulation)
        """
        # Compute CVD over last 15 minutes
        prices, cvd_values = self._compute_cvd_series(minutes=15)

        if len(prices) < 10:
            return CVDDivergence(detected=False, score=0.0)

        # Simple linear regression for trend
        price_trend = self._linear_trend(prices)
        cvd_trend = self._linear_trend(cvd_values)

        # Divergence detection
        if price_trend > 0.01 and cvd_trend < -0.01:
            return CVDDivergence(
                detected=True,
                type="BEARISH",
                score=-0.6,
                interpretation="Price rising but CVD falling — distribution pattern",
            )
        elif price_trend < -0.01 and cvd_trend > 0.01:
            return CVDDivergence(
                detected=True,
                type="BULLISH",
                score=0.6,
                interpretation="Price falling but CVD rising — accumulation pattern",
            )

        return CVDDivergence(detected=False, score=0.0)


@dataclass(frozen=True)
class OrderFlowSignal:
    score: float                   # -1 to +1
    book_imbalance: BookImbalance
    volume_delta: VolumeDelta
    cvd_divergence: CVDDivergence
    large_trades: LargeTradeSignal
    timestamp: datetime
```

### 8.5 Day1 vs Full

| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Metrics | Volume delta only | Full suite (book imbalance, CVD, volume profile) |
| Data source | REST polling (5-min) | WebSocket real-time |
| Latency | 5 minutes | <1 second |
| Signal weight | 5% of total score | 10% of total score |

---

## 9. Seasonal Analysis {#9-seasonal-analysis}

### 9.1 Purpose

Identify **time-based patterns** in market behavior that provide a statistical edge. Markets are not random — they exhibit recurring patterns based on time of day, day of week, month, and proximity to holidays.

### 9.2 Known Crypto Seasonal Patterns

| Pattern | Description | Statistical Basis | Source |
|---------|-------------|-------------------|--------|
| **US Session Premium** | BTC performs best during US market hours (13:30-21:00 UTC) | Higher volume, institutional participation | Historical data |
| **Asian Session Volatility** | Higher volatility during Asian hours (00:00-08:00 UTC) | Thinner order books | Historical data |
| **Monday Effect** | Monday often sets the weekly direction | Weekend news absorption | Historical data |
| **Friday Close** | Positions closed before weekend (reduced risk) | Institutional behavior | Historical data |
| **Month-End Rebalancing** | Last 2 days of month show unusual flows | Institutional rebalancing | Academic research |
| **Options Expiry** | BTC options expiry (last Friday of month) causes pinning | Max pain theory | Deribit data |
| **Quarter End** | End of quarter shows portfolio rebalancing flows | Institutional window dressing | Historical data |
| **Holiday Effect** | Lower volume around US holidays, higher volatility | Reduced liquidity | Historical data |
| **January Effect** | Historically strong January for crypto | New year allocation, tax-loss selling recovery | Historical data |
| **September Weakness** | Historically weak September for risk assets | "Sell in May" adage | Historical data |

### 9.3 Implementation

```python
class SeasonalAnalyzer:
    """
    Tracks and scores seasonal patterns in market behavior.
    Learns from historical trade performance by time dimensions.
    """

    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)
        self._ensure_tables()

    def _ensure_tables(self):
        """Create seasonal tracking tables."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS seasonal_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dimension TEXT NOT NULL,      -- 'hour', 'day_of_week', 'month'
                value INTEGER NOT NULL,       -- 0-23, 0-6, 1-12
                symbol TEXT NOT NULL,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0.0,
                avg_pnl REAL DEFAULT 0.0,
                win_rate REAL DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(dimension, value, symbol)
            )
        """)

    def record_trade_outcome(self, trade: Trade):
        """Record a trade outcome for seasonal analysis."""
        dt = trade.opened_at

        dimensions = [
            ("hour", dt.hour),
            ("day_of_week", dt.weekday()),
            ("month", dt.month),
            ("hour_day", dt.hour * 100 + dt.weekday()),  # Combined
        ]

        for dim, val in dimensions:
            self.db.execute("""
                INSERT INTO seasonal_performance (dimension, value, symbol, total_trades, winning_trades, total_pnl)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(dimension, value, symbol) DO UPDATE SET
                    total_trades = total_trades + 1,
                    winning_trades = winning_trades + ?,
                    total_pnl = total_pnl + ?,
                    avg_pnl = (total_pnl + ?) / (total_trades + 1),
                    win_rate = (winning_trades + ?) * 1.0 / (total_trades + 1),
                    last_updated = CURRENT_TIMESTAMP
            """, (dim, val, trade.symbol,
                  1 if trade.pnl > 0 else 0,
                  trade.pnl,
                  1 if trade.pnl > 0 else 0,
                  trade.pnl,
                  trade.pnl,
                  1 if trade.pnl > 0 else 0))

        self.db.commit()

    def get_seasonal_score(self, symbol: str = "BTC/USDT") -> SeasonalState:
        """Get seasonal score for current time."""
        now = datetime.utcnow()
        scores = {}

        # Hour-of-day score
        hour_score = self._get_dimension_score("hour", now.hour, symbol)
        scores["hour"] = hour_score

        # Day-of-week score
        dow_score = self._get_dimension_score("day_of_week", now.weekday(), symbol)
        scores["day_of_week"] = dow_score

        # Month score
        month_score = self._get_dimension_score("month", now.month, symbol)
        scores["month"] = month_score

        # Combined hour+day score (most granular)
        combined_key = now.hour * 100 + now.weekday()
        combined_score = self._get_dimension_score("hour_day", combined_key, symbol)
        scores["hour_day"] = combined_score

        # Weighted composite
        composite = (
            hour_score * 0.35 +
            dow_score * 0.25 +
            month_score * 0.15 +
            combined_score * 0.25
        )

        return SeasonalState(
            score=composite,
            components=scores,
            current_hour=now.hour,
            current_day=now.strftime("%A"),
            current_month=now.strftime("%B"),
            timestamp=now,
        )

    def _get_dimension_score(self, dimension: str, value: int, symbol: str) -> float:
        """Get seasonal score for a specific dimension value."""
        cursor = self.db.execute("""
            SELECT win_rate, total_trades, avg_pnl
            FROM seasonal_performance
            WHERE dimension = ? AND value = ? AND symbol = ?
        """, (dimension, value, symbol))

        row = cursor.fetchone()
        if not row or row[1] < 10:  # Need minimum sample size
            return 0.0

        win_rate, total_trades, avg_pnl = row

        # Score based on win rate deviation from 50%
        if win_rate > 0.60:
            score = 0.5
        elif win_rate > 0.55:
            score = 0.2
        elif win_rate < 0.40:
            score = -0.5
        elif win_rate < 0.45:
            score = -0.2
        else:
            score = 0.0

        # Adjust by sample size confidence
        confidence = min(1.0, total_trades / 50)  # Full confidence at 50+ trades
        return score * confidence

    def get_holiday_adjustment(self) -> float:
        """Check if we're near a major holiday and adjust."""
        from datetime import date
        today = date.today()

        HOLIDAYS = [
            (1, 1),    # New Year
            (7, 4),    # US Independence Day
            (12, 25),  # Christmas
            (12, 31),  # New Year's Eve
        ]

        for month, day in HOLIDAYS:
            holiday = date(today.year, month, day)
            days_until = (holiday - today).days

            if 0 <= days_until <= 2:
                return 0.5  # Reduce position size near holidays
            if -2 <= days_until < 0:
                return 0.75  # Slightly reduced right after holiday

        return 1.0  # Normal


@dataclass(frozen=True)
class SeasonalState:
    score: float                    # -1 to +1
    components: dict[str, float]
    current_hour: int
    current_day: str
    current_month: str
    timestamp: datetime
```

### 9.4 Learning from History

The seasonal analyzer **learns from actual trade outcomes** — it doesn't rely solely on published research. As the system trades, it builds its own seasonal edge database:

```
Week 1-4:  Default patterns from research (US session premium, etc.)
Month 2+:  System's own performance data takes over
Month 6+:  Highly specific patterns emerge (e.g., "BTC wins 72% of the time
           during US session on Tuesdays in risk-on regime")
```

### 9.5 Day1 vs Full

| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Patterns | None | Learned from trade history |
| Data | None | Built from first trade onward |
| Weight in signal | 0% | 5-10% |
| Holiday awareness | None | Automatic position size reduction |

---

## 10. Architecture Integration Map {#10-architecture-integration-map}

### 10.1 How Each Component Connects

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    MARKET ANALYSIS → EXISTING ARCHITECTURE               │
│                                                                         │
│  MARKET ANALYSIS LAYER              EXISTING AGENTS                     │
│  ════════════════════              ═══════════════                      │
│                                                                         │
│  ┌──────────────┐                  ┌──────────────────┐                 │
│  │ Macro Agent  │─────────────────▶│ Signal Agent     │                 │
│  │              │ macro_score,     │ • Macro alignment │                 │
│  │              │ regime, bias     │   score (10%)     │                 │
│  │              │                  │ • Direction bias  │                 │
│  │              │─────────────────▶│ Risk Agent        │                 │
│  │              │ position_size_   │ • Size multiplier │                 │
│  │              │ multiplier       │ • Regime filter   │                 │
│  │              │                  └──────────────────┘                 │
│  └──────────────┘                                                       │
│                                                                         │
│  ┌──────────────┐                  ┌──────────────────┐                 │
│  │ Sentiment    │─────────────────▶│ Signal Agent     │                 │
│  │ Analysis     │ sentiment_score, │ • Sentiment score │                 │
│  │              │ contrarian_signal│   (15%)           │                 │
│  └──────────────┘                  └──────────────────┘                 │
│                                                                         │
│  ┌──────────────┐                  ┌──────────────────┐                 │
│  │ On-Chain     │─────────────────▶│ Signal Agent     │                 │
│  │ Analytics    │ onchain_score,   │ • On-chain score  │                 │
│  │              │ whale_signals    │   (5%)            │                 │
│  └──────────────┘                  └──────────────────┘                 │
│                                                                         │
│  ┌──────────────┐                  ┌──────────────────┐                 │
│  │ Economic     │─────────────────▶│ Risk Agent       │                 │
│  │ Calendar     │ blackout_state,  │ • Blackout filter │                 │
│  │              │ event_schedule   │ • Size reduction  │                 │
│  └──────────────┘                  └──────────────────┘                 │
│                                                                         │
│  ┌──────────────┐                  ┌──────────────────┐                 │
│  │ Geopolitical │─────────────────▶│ Risk Agent       │                 │
│  │ Analysis     │ geo_risk_posture │ • Size multiplier │                 │
│  │              │                  │ • Halt trading    │                 │
│  └──────────────┘                  └──────────────────┘                 │
│                                                                         │
│  ┌──────────────┐                  ┌──────────────────┐                 │
│  │ Cross-Asset  │─────────────────▶│ Market           │                 │
│  │ Correlation  │ macro_pairs,     │ Cartographer     │                 │
│  │              │ anomalies        │ (extends existing)│                 │
│  └──────────────┘                  └──────────────────┘                 │
│                                                                         │
│  ┌──────────────┐                  ┌──────────────────┐                 │
│  │ Order Flow   │─────────────────▶│ Signal Agent     │                 │
│  │ Analysis     │ order_flow_score │ • OF score (5%)   │                 │
│  └──────────────┘                  └──────────────────┘                 │
│                                                                         │
│  ┌──────────────┐                  ┌──────────────────┐                 │
│  │ Seasonal     │─────────────────▶│ Signal Agent     │                 │
│  │ Analysis     │ seasonal_score   │ • Seasonal (5%)   │                 │
│  │              │                  └──────────────────┘                 │
│  └──────────────┘                                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 10.2 Signal Agent Scoring (Updated)

The Signal Agent's scoring breakdown with Market Analysis integration:

```python
SIGNAL_SCORING_WEIGHTS = {
    # Technical Analysis (existing)
    "rsi_extreme":         0.25,  # RSI oversold/overbought
    "sr_proximity":        0.20,  # Support/resistance proximity
    "volume_confirmation": 0.10,  # Volume spike confirmation

    # Market Analysis (new)
    "sentiment":           0.15,  # Fear & Greed + news sentiment
    "macro_alignment":     0.10,  # Macro regime alignment
    "on_chain":            0.05,  # On-chain metrics
    "order_flow":          0.05,  # Order book imbalance
    "seasonal":            0.05,  # Time-of-day/day-of-week patterns
    "cross_asset":         0.05,  # DXY/VIX alignment

    # Total: 1.00
}
```

### 10.3 Risk Agent Filtering (Updated)

The Risk Agent's evaluation checklist with Market Analysis additions:

```python
RISK_CHECKLIST = {
    # Existing checks
    "position_size":       True,   # Max 5% per trade
    "daily_loss":          True,   # -2% daily limit
    "max_positions":       True,   # Max 10 open
    "has_stop_loss":       True,   # Stop-loss required
    "risk_reward":         True,   # Min 2:1 R:R
    "cooldown":            True,   # 30 min per symbol

    # Market Analysis checks (new)
    "economic_blackout":   True,   # No trades during blackout windows
    "geo_risk":            True,   # Geopolitical risk check
    "macro_regime":        True,   # Macro regime alignment
    "sentiment_extreme":   True,   # Extreme sentiment warning
}
```

### 10.4 Redis Stream Extensions

New streams for Market Analysis data:

| Stream | Producer | Consumers | Payload |
|--------|----------|-----------|---------|
| `tsar:stream:macro` | Macro Agent | Signal, Risk, Regime | MacroState |
| `tsar:stream:sentiment` | Sentiment Analyzer | Signal, Risk | SentimentScore |
| `tsar:stream:onchain` | On-Chain Analyzer | Signal | OnChainState |
| `tsar:stream:calendar` | Economic Calendar | Risk | BlackoutState |
| `tsar:stream:geopolitical` | Geo Analyzer | Risk | GeoRiskPosture |
| `tsar:stream:orderflow` | Order Flow Analyzer | Signal | OrderFlowSignal |
| `tsar:stream:seasonal` | Seasonal Analyzer | Signal | SeasonalState |

### 10.5 Updated Bootstrap Sequence

Add Market Analysis warmup to the existing 6-phase bootstrap:

```
Phase 2: DATA ACQUISITION (10s - 5min)
  ├── Existing: OHLCV download, order book snapshots
  └── NEW: Economic calendar fetch (ForexFactory)
           Fear & Greed index fetch
           On-chain metrics fetch (CoinGecko)
           DXY/bond yield historical data (Yahoo Finance)
           Correlation matrix initial computation

Phase 3: MODEL CALIBRATION (5min - 15min)
  ├── Existing: HMM regime model, indicator baselines
  └── NEW: Seasonal patterns load from DB (if any history)
           Macro state initial computation
           Sentiment baseline

Phase 5: VALIDATION (20min - 25min)
  ├── Existing: System self-tests
  └── NEW: Verify all Market Analysis data sources reachable
           Test economic calendar blackout logic
           Validate correlation computation
```

---

## 11. Day1 vs Full Implementation {#11-day1-vs-full-implementation}

### 11.1 Day1: Baked into Signal Agent (Weeks 1-4)

For Day1, Market Analysis is **not a separate agent** — it's a lightweight module inside the Signal Agent that provides basic macro awareness.

```python
# agents/signal_agent.py — Day1 additions

class MarketAwareness:
    """Day1: Lightweight market analysis baked into Signal Agent."""

    # Hardcoded 2026 FOMC dates (replace with calendar API in Level 2)
    FOMC_DATES_2026 = [
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]

    NFP_DATES_2026 = [
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
        "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
        "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    ]

    def __init__(self):
        self.fear_greed_cache = None
        self.dxy_cache = None

    def check_blackout(self) -> tuple[bool, str]:
        """Check if we're near a major event."""
        now = datetime.utcnow()
        today = now.strftime("%Y-%m-%d")

        # FOMC: block trades on decision day
        if today in self.FOMC_DATES_2026:
            return True, "FOMC decision day — no trading"

        # NFP: block trades first Friday of month
        if today in self.NFP_DATES_2026:
            return True, "NFP release day — no trading"

        return False, ""

    async def get_fear_greed(self) -> int:
        """Get Fear & Greed Index (0-100)."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.alternative.me/fng/?limit=1") as resp:
                    data = await resp.json()
                    return int(data["data"][0]["value"])
        except Exception:
            return 50  # Neutral on error

    async def get_dxy_direction(self) -> str:
        """Get DXY trend direction."""
        import yfinance as yf
        try:
            dxy = yf.download("DX-Y.NYB", period="5d", interval="1d", progress=False)
            if len(dxy) < 2:
                return "NEUTRAL"
            sma3 = dxy["Close"].tail(3).mean()
            current = dxy["Close"].iloc[-1]
            if current > sma3 * 1.005:
                return "STRONG_UP"   # DXY rising = bearish for BTC
            elif current < sma3 * 0.995:
                return "STRONG_DOWN" # DXY falling = bullish for BTC
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    async def get_market_context(self) -> MarketContext:
        """Day1: Simple market context for signal scoring."""
        blackout, blackout_reason = self.check_blackout()
        fear_greed = await self.get_fear_greed()
        dxy = await self.get_dxy_direction()

        # Simple sentiment from Fear & Greed
        if fear_greed < 25:
            sentiment = "EXTREME_FEAR"
            sentiment_score = 0.5   # Contrarian buy signal
        elif fear_greed < 40:
            sentiment = "FEAR"
            sentiment_score = 0.2
        elif fear_greed > 75:
            sentiment = "EXTREME_GREED"
            sentiment_score = -0.5  # Contrarian sell signal
        elif fear_greed > 60:
            sentiment = "GREED"
            sentiment_score = -0.2
        else:
            sentiment = "NEUTRAL"
            sentiment_score = 0.0

        # DXY adjustment
        dxy_score = 0.0
        if dxy == "STRONG_DOWN":
            dxy_score = 0.3   # Weak dollar = bullish for BTC
        elif dxy == "STRONG_UP":
            dxy_score = -0.3  # Strong dollar = bearish for BTC

        return MarketContext(
            blackout=blackout,
            blackout_reason=blackout_reason,
            fear_greed=fear_greed,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            dxy_direction=dxy,
            dxy_score=dxy_score,
            composite_score=(sentiment_score + dxy_score) / 2,
        )

@dataclass
class MarketContext:
    blackout: bool
    blackout_reason: str
    fear_greed: int
    sentiment: str
    sentiment_score: float
    dxy_direction: str
    dxy_score: float
    composite_score: float
```

### 11.2 Level 2: Dedicated Macro Agent (Months 2-3)

| Component | Implementation | Effort |
|-----------|---------------|--------|
| Economic Calendar | ForexFactory scraper + Redis cache | 2 days |
| Macro Agent | FRED + Trading Economics integration | 3 days |
| Sentiment (full) | CryptoPanic + LLM scoring | 2 days |
| Cross-Asset | DXY + VIX + Gold + Bond yields | 2 days |
| On-Chain (basic) | CoinGecko + Fear & Greed + Funding | 2 days |

### 11.3 Level 3: Full Market Analysis (Months 4-6)

| Component | Implementation | Effort |
|-----------|---------------|--------|
| On-Chain (full) | CryptoQuant + Whale Alert + MVRV + NVT | 3 days |
| Order Flow | WebSocket order book + CVD + volume profile | 4 days |
| Geopolitical | News scanning + LLM classification | 2 days |
| Seasonal | Historical pattern learning from trades | 2 days |
| Sentiment Agent | Dedicated agent with social media | 3 days |

### 11.4 Coverage Progression

| Layer Component | Day1 | Level 2 | Level 3 | Full |
|----------------|------|---------|---------|------|
| Macro Agent | 10% | 60% | 90% | 100% |
| Economic Calendar | 15% | 70% | 90% | 100% |
| Sentiment | 20% | 60% | 85% | 100% |
| On-Chain | 5% | 30% | 75% | 100% |
| Geopolitical | 0% | 20% | 60% | 100% |
| Cross-Asset Correlation | 10% | 50% | 80% | 100% |
| Order Flow | 0% | 10% | 60% | 100% |
| Seasonal | 0% | 20% | 60% | 100% |
| **Layer Total** | **~15%** | **~45%** | **~75%** | **~100%** |

---

## 12. Data Source Catalog {#12-data-source-catalog}

### 12.1 Complete Free Data Sources

| Source | API Type | Cost | Rate Limit | Metrics | Used By |
|--------|----------|------|------------|---------|---------|
| **FRED** | REST (`fredapi`) | $0 | 120 req/min | Rates, GDP, employment, inflation | Macro Agent |
| **Yahoo Finance** | REST (`yfinance`) | $0 | ~2000 req/hr | DXY, VIX, bonds, equities, gold | Cross-Asset |
| **Alternative.me** | REST | $0 | Unlimited | Fear & Greed Index | Sentiment |
| **CoinGecko** | REST | $0 | 30 req/min | Price, volume, market cap, active addresses | On-Chain |
| **CryptoQuant** | REST | $0 (limited) | 10 req/day | Exchange flow, reserves | On-Chain |
| **Whale Alert** | REST | $0 (free tier) | 10 req/min | Large transactions | On-Chain |
| **DeFiLlama** | REST | $0 | Unlimited | DeFi TVL, yields | On-Chain |
| **CoinMetrics** | REST | $0 (community) | 100 req/day | MVRV, NVT, supply | On-Chain |
| **Coinglass** | REST | $0 (limited) | 20 req/day | Funding rates, open interest | On-Chain |
| **ForexFactory** | HTML scrape | $0 | Manual | Economic calendar | Calendar |
| **Trading Economics** | REST | $0 (limited) | 100 req/mo | Economic indicators | Macro Agent |
| **CryptoPanic** | REST | $0 | 100 req/day | Crypto news | Sentiment |
| **GNews** | REST | $0 | 100 req/day | Global news | Geopolitical |
| **GDELT** | REST | $0 | Unlimited | Global events | Geopolitical |
| **Binance** | WS + REST | $0 | 1200 req/min | Order book, trades, OHLCV | Order Flow |

### 12.2 API Keys Required

| Source | Key Required | How to Get |
|--------|-------------|------------|
| FRED | Yes (free) | https://fred.stlouisfed.org/docs/api/api_key.html |
| CoinGecko | No (free tier) | No key needed for basic endpoints |
| CryptoQuant | Yes (free tier) | https://cryptoquant.com/signup |
| Whale Alert | Yes (free tier) | https://whale-alert.io/developers |
| CoinMetrics | Yes (community) | https://coinmetrics.io/community/ |
| Coinglass | Yes (free tier) | https://www.coinglass.com/zh/pricing |
| CryptoPanic | Yes (free) | https://cryptopanic.com/developers/ |
| GNews | Yes (free) | https://gnews.io/ |
| Trading Economics | Yes (free tier) | https://tradingeconomics.com/api |

---

## 13. Database Schema Additions {#13-database-schema-additions}

### 13.1 Market Analysis Tables (add to `tsar.db`)

```sql
-- ═══════════════════════════════════════════════════════════════
-- MARKET ANALYSIS TABLES (prefix: market_)
-- ═══════════════════════════════════════════════════════════════

-- Macro state history
CREATE TABLE market_macro_states (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    composite_score REAL NOT NULL,
    regime          TEXT NOT NULL,          -- RISK_ON, RISK_OFF, TRANSITION, CRISIS
    fed_stance      REAL,
    inflation       REAL,
    growth          REAL,
    employment      REAL,
    dollar          REAL,
    narrative       TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_macro_created ON market_macro_states(created_at DESC);
CREATE INDEX idx_macro_regime ON market_macro_states(regime);

-- Sentiment history
CREATE TABLE market_sentiment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    composite       REAL NOT NULL,
    fear_greed      INTEGER,
    news_score      REAL,
    social_score    REAL,
    contrarian      REAL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sentiment_symbol ON market_sentiment(symbol, created_at DESC);

-- On-chain metrics
CREATE TABLE market_onchain (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    composite_score REAL NOT NULL,
    exchange_flow   REAL,
    whale_signal    REAL,
    mvrv            REAL,
    funding_rate    REAL,
    stablecoin_delta REAL,
    active_addresses INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_onchain_symbol ON market_onchain(symbol, created_at DESC);

-- Economic events
CREATE TABLE market_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT NOT NULL,          -- FOMC, CPI, NFP, etc.
    event_datetime  TIMESTAMP NOT NULL,
    impact          TEXT NOT NULL,          -- LOW, MEDIUM, HIGH, CRITICAL
    currency        TEXT,
    previous        REAL,
    forecast        REAL,
    actual          REAL,
    surprise_pct    REAL,
    classification  TEXT,                   -- BEAT, MISS, IN_LINE
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_events_type ON market_events(event_type);
CREATE INDEX idx_events_date ON market_events(event_datetime DESC);

-- Geopolitical events
CREATE TABLE market_geopolitical (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    event_type      TEXT NOT NULL,          -- war, sanctions, election, etc.
    severity        TEXT NOT NULL,          -- LOW, MEDIUM, HIGH, CRITICAL
    affected_assets TEXT,                   -- JSON array
    source          TEXT,
    detected_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TIMESTAMP
);
CREATE INDEX idx_geo_severity ON market_geopolitical(severity, detected_at DESC);

-- Correlation snapshots
CREATE TABLE market_correlations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pair            TEXT NOT NULL,          -- "BTC-USD_vs_DXY"
    correlation     REAL NOT NULL,
    window_days     INTEGER NOT NULL,
    regime          TEXT,                   -- RISK_ON, RISK_OFF, DECOUPLED
    anomaly         INTEGER DEFAULT 0,     -- 1 = significant deviation
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_corr_pair ON market_correlations(pair, created_at DESC);

-- Order flow snapshots (aggregated, not tick-level)
CREATE TABLE market_orderflow (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    book_imbalance  REAL,
    volume_delta    REAL,
    cvd_divergence  TEXT,                   -- BULLISH, BEARISH, NONE
    score           REAL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_of_symbol ON market_orderflow(symbol, created_at DESC);

-- Seasonal performance tracking
CREATE TABLE market_seasonal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension       TEXT NOT NULL,          -- hour, day_of_week, month
    value           INTEGER NOT NULL,
    symbol          TEXT NOT NULL,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    total_pnl       REAL DEFAULT 0.0,
    win_rate        REAL DEFAULT 0.0,
    last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dimension, value, symbol)
);
```

### 13.2 Redis State Keys

```
tsar:macro:state              # Hash — current macro state
tsar:macro:history            # Stream — macro state changes
tsar:sentiment:current        # Hash — current sentiment scores
tsar:onchain:current          # Hash — current on-chain metrics
tsar:calendar:events          # String (JSON) — cached calendar events
tsar:calendar:blackout        # Hash — current blackout state
tsar:geopolitical:posture     # Hash — current geo risk posture
tsar:correlation:current      # Hash — current correlation matrix
tsar:orderflow:{symbol}       # Hash — current order flow metrics
tsar:seasonal:current         # Hash — current seasonal scores
```

---

## Appendix A: Implementation Effort Summary

| Component | Day1 Effort | Level 2 Effort | Level 3 Effort | Total |
|-----------|-------------|----------------|----------------|-------|
| Macro Agent | 0.5 days | 3 days | 2 days | 5.5 days |
| Economic Calendar | 0.5 days | 2 days | 1 day | 3.5 days |
| Sentiment Analysis | 1 day | 2 days | 3 days | 6 days |
| On-Chain Analytics | 0.5 days | 2 days | 3 days | 5.5 days |
| Geopolitical | 0 days | 1 day | 2 days | 3 days |
| Cross-Asset Correlation | 0.5 days | 2 days | 1 day | 3.5 days |
| Order Flow | 0 days | 1 day | 4 days | 5 days |
| Seasonal Analysis | 0 days | 1 day | 2 days | 3 days |
| **Total** | **3 days** | **14 days** | **18 days** | **35 days** |

---

## Appendix B: Decision Log

| # | Decision | Alternatives Considered | Chosen | Rationale |
|---|----------|------------------------|--------|-----------|
| M1 | Macro Agent as separate agent | Inline in Signal Agent | Separate (Level 2+) | Complexity justifies separation; Signal Agent stays focused |
| M2 | Fear & Greed as Day1 sentiment | None | Yes | Free, no API key, single endpoint, highly predictive |
| M3 | ForexFactory for calendar | Trading Economics, Investing.com | ForexFactory primary | Free, comprehensive, well-structured |
| M4 | LLM for news sentiment scoring | VADER, TextBlob | LLM (Qwen2.5-7B) | Better context understanding, free via Ollama |
| M5 | CoinGecko for on-chain | CryptoQuant only | CoinGecko primary | More free-tier endpoints, no key needed for basics |
| M6 | yfinance for cross-asset | Alpha Vantage, Quandl | yfinance | Free, no key, covers all needed tickers |
| M7 | WebSocket for order flow | REST polling | WebSocket (Level 3), REST (Day1) | Real-time vs simplicity tradeoff |
| M8 | Learn seasonal from trades | Use published research only | Both (research default + learn) | System-specific patterns > generic patterns |
| M9 | Geopolitical via LLM classification | Rule-based keyword matching | LLM | Better context understanding, fewer false positives |
| M10 | Economic blackout = block trades | Reduce size only | Both (block for critical, reduce for high) | FOMC/CPI/NFP deserve full blackout |

---

*Market Analysis Layer specification complete. This document fills the 85% gap in the Market Analysis layer of the TSAR Trading Super Agent architecture.*

*Generated: 2026-07-24 02:13 GMT+8*
