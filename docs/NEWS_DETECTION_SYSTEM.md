# TSAR News Detection & Classification System

**Version:** 1.0 — Institutional Grade  
**Role in Pipeline:** `SignalScout → [NEWS GATE] → SQF → RiskGuardian → ExecutionSniper`  
**Authority:** CRITICAL news = VETO all trades. No override. No exceptions.

---

## 1. Executive Summary

News is the **#1 gatekeeper** in TSAR's decision funnel. If news says "FAIL", no trade happens regardless of technicals, sentiment, or on-chain signals. This document defines the architecture for detecting, classifying, scoring, and acting on crypto news in real-time.

**Design Principle:** False negatives (missing a hack) are catastrophic. False positives (pausing on FUD) are recoverable. The system is biased toward caution.

---

## 2. Current State Analysis

### 2.1 What Exists in Repo

| Component | File | Status | Gap |
|-----------|------|--------|-----|
| **NewsAggregator** | `src/tools/news.py` | ✅ Functional | No classification, no velocity, no fake detection |
| **SentimentAgent** | `src/agents/sentiment_agent.py` | ✅ Functional | News sentiment = 35% weight only, no news-specific gating |
| **SocialSentimentAnalyzer** | `src/tools/sentiment.py` | ✅ Functional | Twitter via proxy only, no real-time stream |
| **FalseSignalDetector** | `src/agents/false_signal_detectors.py` | ✅ Functional | `detect_news_spike` exists but reactive, not proactive |
| **SignalQualityFilter** | `src/agents/signal_quality_filter.py` | ✅ Functional | Sentiment factor = 10% weight, no news classification |
| **RiskGuardian** | `src/agents/risk_guardian.py` | ✅ Functional | News blackout check exists but basic |
| **NotificationEngine** | `src/bot/notification_engine.py` | ✅ Functional | Priority system ready for CRITICAL news alerts |
| **EconomicCalendar** | `src/tools/economic_calendar.py` | ✅ Functional | Macro events tracked, not crypto-native news |

### 2.2 What's MISSING

| Gap | Severity | Impact |
|-----|----------|--------|
| **News Classification Engine** | 🔴 CRITICAL | No severity tiers → all news treated equally |
| **Velocity Detection** | 🔴 CRITICAL | No detection of news avalanche or silence |
| **Fake News / FUD Detector** | 🔴 CRITICAL | Single-source news can trigger false vetoes |
| **Real-Time Breaking News Feed** | 🟡 HIGH | 180s cache = 3min blind spot on hacks/exploits |
| **Twitter/X Real-Time Stream** | 🟡 HIGH | Using CryptoPanic proxy, not direct firehose |
| **On-Chain Alert Integration** | 🟡 HIGH | Whale alerts, contract exploits not fed to news gate |
| **Regulatory Feed** | 🟡 HIGH | SEC/CFTC filings not monitored |
| **Multi-Source Verification** | 🟠 MEDIUM | No cross-reference for CRITICAL claims |
| **News Decay Model** | 🟠 MEDIUM | No aging — 6h-old hack news same weight as fresh |

---

## 3. Architecture Design

### 3.1 System Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                    NEWS DETECTION SYSTEM                         │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │CryptoPanic│ │RSS Feeds │ │WebSocket │ │ On-Chain Alerts  │   │
│  │  (API)   │ │(3 feeds) │ │(future)  │ │ (Whale Alert)    │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───────┬──────────┘   │
│       │             │            │                │              │
│       └─────────────┴────────────┴────────────────┘              │
│                            │                                     │
│                    ┌───────▼────────┐                            │
│                    │  NewsCollector  │ ← Unified ingestion       │
│                    │  (60s poll)     │                            │
│                    └───────┬────────┘                            │
│                            │                                     │
│              ┌─────────────┼──────────────┐                     │
│              ▼             ▼              ▼                       │
│  ┌───────────────┐ ┌─────────────┐ ┌──────────────┐            │
│  │  Classifier   │ │  Velocity   │ │  Fake News   │            │
│  │  Engine       │ │  Detector   │ │  Detector    │            │
│  └───────┬───────┘ └──────┬──────┘ └──────┬───────┘            │
│          │                │               │                      │
│          └────────────────┴───────────────┘                     │
│                           │                                      │
│                  ┌────────▼────────┐                            │
│                  │  NewsGatekeeper  │ ← THE DECISION ENGINE      │
│                  │  (VETO POWER)    │                            │
│                  └────────┬────────┘                            │
│                           │                                      │
│              ┌────────────┼────────────┐                        │
│              ▼            ▼            ▼                         │
│  ┌──────────────┐ ┌────────────┐ ┌──────────────┐             │
│  │  Stream Bus  │ │ RiskGuard  │ │ Notification │             │
│  │  (sentiment) │ │  (veto)    │ │  (Telegram)  │             │
│  └──────────────┘ └────────────┘ └──────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 New Files to Create

```
src/tools/news_classifier.py      — Classification engine
src/tools/news_velocity.py        — Velocity/spike detection
src/tools/news_verifier.py        — Multi-source verification & FUD detection
src/agents/news_gatekeeper.py     — Gatekeeper agent (THE veto power)
src/agents/news_monitor.py        — Real-time monitoring loop
tests/unit/tools/test_news_classifier.py
tests/unit/tools/test_news_velocity.py
tests/unit/tools/test_news_verifier.py
tests/unit/agents/test_news_gatekeeper.py
```

---

## 4. News Classification System

### 4.1 Severity Tiers

```python
class NewsSeverity(StrEnum):
    CRITICAL = "critical"   # VETO: Halt all trading immediately
    HIGH     = "high"       # BLOCK: Reject new entries, warn on existing
    MEDIUM   = "medium"     # ALERT: Include in SQF scoring, reduce size
    LOW      = "low"        # TRACK: Log only, no trading impact
```

### 4.2 Classification Rules

| Tier | Category | Examples | Action |
|------|----------|----------|--------|
| **CRITICAL** | Exchange Compromise | "Binance hacked", "FTX insolvent", "Hot wallet drained" | 🔴 VETO ALL — Kill switch |
| **CRITICAL** | Regulatory Ban | "China bans crypto", "SEC emergency order", "India bans" | 🔴 VETO ALL — Kill switch |
| **CRITICAL** | Stablecoin Depeg | "USDT breaks $0.95", "USDC depeg", "DAI loses peg" | 🔴 VETO ALL — Kill switch |
| **CRITICAL** | Major Exploit | "Ethereum bridge hacked $500M", "Smart contract drain" | 🔴 VETO ALL — Kill switch |
| **CRITICAL** | Protocol Death | "Luna/Terra collapse", "Genesis bankruptcy" | 🔴 VETO ALL — Kill switch |
| **HIGH** | ETF Decision | "SEC approves Bitcoin ETF", "ETF application denied" | 🟡 BLOCK NEW entries |
| **HIGH** | Major Partnership | "BlackRock partners with Coinbase", "Visa adopts USDC" | 🟡 BULLISH signal boost |
| **HIGH** | Protocol Upgrade | "Ethereum Shanghai upgrade live", "Bitcoin Taproot" | 🟡 Include in scoring |
| **HIGH** | Whale Movement | "Whale moves 50K BTC to exchange", "Satoshi wallet active" | 🟡 BLOCK + investigate |
| **HIGH** | Major Lawsuit | "SEC sues Binance", "Ripple wins case" | 🟡 BLOCK NEW entries |
| **MEDIUM** | Market Analysis | "BTC forming head and shoulders", "ETH undervalued" | 🟢 SQF weight boost |
| **MEDIUM** | Minor Partnership | "Coinbase lists new token", "Chainlink integrates" | 🟢 SQF weight boost |
| **MEDIUM** | Price Prediction | "Analyst predicts $100K BTC", "ETH to $5K" | 🟢 Log, no action |
| **LOW** | Educational | "What is DeFi?", "How to store crypto" | ⚪ Ignore |
| **LOW** | Opinion | "Why I'm bullish", "Market feels bearish" | ⚪ Ignore |
| **LOW** | Minor Update | "Wallet app update", "UI refresh" | ⚪ Ignore |

### 4.3 Classification Algorithm

```python
def classify_news(title: str, content: str, source: str) -> NewsClassification:
    """Two-pass classification: keyword match → LLM verification."""
    
    # Pass 1: Keyword-based (instant, deterministic)
    severity = keyword_classify(title, content)
    
    # Pass 2: LLM verification for CRITICAL only (prevents false vetoes)
    if severity == CRITICAL:
        severity = llm_verify_critical(title, content, source)
    
    return NewsClassification(severity=severity, ...)
```

### 4.4 Keyword Taxonomy

```python
CRITICAL_KEYWORDS = {
    "exchange_compromise": {
        "patterns": [
            r"hack(?:ed|ing)?", r"exploit(?:ed)?", r"drained?",
            r"stolen", r"breach(?:ed)?", r"compromised?",
            r"hot\s*wallet.*(?:drain|hack|stolen)",
            r"(?:binance|coinbase|kraken|okx|bybit).*(?:hack|exploit|breach)",
        ],
        "context_required": ["exchange", "wallet", "funds", "crypto", "bitcoin", "ethereum"],
    },
    "regulatory_ban": {
        "patterns": [
            r"(?:ban|bans|banned|prohibit|outlaw)(?:\s+crypto)?",
            r"emergency\s+(?:order|action)",
            r"SEC.*(?:sue|sues|lawsuit|charges|enforcement)",
            r"CFTC.*(?:sue|sues|lawsuit|charges)",
            r"(?:china|india|russia).*ban.*(?:crypto|bitcoin|mining)",
        ],
        "context_required": ["crypto", "bitcoin", "digital asset", "virtual currency", "exchange"],
    },
    "stablecoin_depeg": {
        "patterns": [
            r"(?:USDT|USDC|DAI|BUSD|TUSD).*(?:de-?peg|break|lose|below\s+\$0\.\d+)",
            r"stablecoin.*(?:crisis|fail|collapse|de-?peg)",
            r"(?:tether|circle).*(?:insolvency|bankruptcy|reserve|audit.*fail)",
        ],
        "context_required": ["stablecoin", "peg", "dollar", "reserve"],
    },
    "major_exploit": {
        "patterns": [
            r"(?:bridge|protocol|smart\s*contract).*(?:exploit|hack|drain|stolen)",
            r"\$[\d,]+[MBK]?.*(?:stolen|drained|exploited|hack)",
            r"(?:flash\s*loan|reentrancy|oracle\s*manipulation).*(?:attack|exploit)",
            r"(?:multisig|governance).*(?:attack|compromise|takeover)",
        ],
        "context_required": ["crypto", "defi", "protocol", "bridge", "token"],
    },
}

HIGH_KEYWORDS = {
    "etf_decision": {
        "patterns": [
            r"ETF.*(?:approv|deni|reject|delay|ruling|decision)",
            r"SEC.*ETF.*(?:approv|deni|pending)",
            r"(?:bitcoin|ethereum)\s+ETF",
        ],
    },
    "major_partnership": {
        "patterns": [
            r"(?:blackrock|fidelity|jpmorgan|goldman|visa|mastercard|paypal).*crypto",
            r"(?:institutional|wall\s*street|fortune\s*500).*(?:adopt|partner|invest)",
        ],
    },
    "whale_movement": {
        "patterns": [
            r"whale.*(?:mov|transfer|deposit|withdraw).*(?:\d[\d,]*\s*(?:BTC|ETH|BTC))",
            r"(?:satoshi|nakamoto).*wallet.*(?:active|mov|transfer)",
            r"(?:\d[\d,]*\s*(?:BTC|ETH)).*(?:exchange|binance|coinbase)",
        ],
    },
}
```

---

## 5. Sentiment Scoring System

### 5.1 Scoring Model

```python
@dataclass(frozen=True)
class NewsScore:
    """Complete scoring of a single news item."""
    severity: NewsSeverity          # Classification tier
    sentiment: float                # -1.0 to +1.0
    confidence: float               # 0.0 to 1.0
    relevance: float                # 0.0 to 1.0
    age_minutes: int                # How old the news is
    decayed_sentiment: float        # Sentiment after time decay
    source_reliability: float       # 0.0 to 1.0
    verified: bool                  # Multi-source confirmed
    is_breaking: bool               # Breaking news flag
```

### 5.2 Sentiment Derivation

| Signal | Sentiment | Confidence |
|--------|-----------|------------|
| Hack / Exploit / Drain | -1.0 | 0.95 |
| Regulatory Ban / Emergency Order | -1.0 | 0.90 |
| Stablecoin Depeg (< $0.97) | -0.9 | 0.90 |
| Major Lawsuit / Charges | -0.8 | 0.85 |
| ETF Denied / Rejected | -0.7 | 0.80 |
| Whale Moves to Exchange | -0.5 | 0.60 |
| Market Analysis (bearish) | -0.3 | 0.40 |
| Neutral News | 0.0 | 0.30 |
| Market Analysis (bullish) | +0.3 | 0.40 |
| Minor Partnership | +0.4 | 0.50 |
| Protocol Upgrade | +0.6 | 0.70 |
| ETF Approval | +0.9 | 0.90 |
| Major Institutional Adoption | +0.8 | 0.85 |

### 5.3 Time Decay Model

News becomes stale. A hack 6 hours ago is less relevant than one 6 minutes ago.

```python
def apply_decay(sentiment: float, age_minutes: int, severity: NewsSeverity) -> float:
    """Apply time decay to sentiment score.
    
    Decay rates by severity:
      CRITICAL: half-life = 24h (hack news stays relevant longer)
      HIGH:     half-life = 6h
      MEDIUM:   half-life = 2h
      LOW:      half-life = 30min
    """
    half_life_minutes = {
        CRITICAL: 1440,  # 24h
        HIGH: 360,       # 6h
        MEDIUM: 120,     # 2h
        LOW: 30,         # 30min
    }
    
    hl = half_life_minutes[severity]
    decay_factor = 0.5 ** (age_minutes / hl)
    return sentiment * decay_factor
```

### 5.4 Source Reliability Weights

```python
SOURCE_RELIABILITY = {
    # Tier 1: Primary crypto news (most reliable)
    "CoinDesk": 0.90,
    "CoinTelegraph": 0.85,
    "Decrypt": 0.85,
    "The Block": 0.90,
    "Bloomberg Crypto": 0.95,
    "Reuters": 0.95,
    
    # Tier 2: Crypto-native
    "CryptoPanic": 0.70,  # Aggregator, quality varies
    "The Defiant": 0.75,
    "Blockworks": 0.80,
    
    # Tier 3: Social / Low reliability
    "Twitter/X": 0.40,
    "Reddit": 0.35,
    "Telegram": 0.25,
    "Unknown": 0.20,
}
```

---

## 6. News Velocity Detection

### 6.1 Velocity Metrics

```python
@dataclass(frozen=True)
class NewsVelocity:
    """News velocity metrics for a symbol."""
    articles_per_hour: float        # Rate of news publication
    sentiment_velocity: float       # Rate of sentiment change
    direction: str                  # "accelerating_positive", "accelerating_negative", "stable", "decelerating"
    avalanche_detected: bool        # 5+ articles in 1h, same direction
    silence_detected: bool          # No news for 24h during active market
    is_unusual: bool                # Velocity outside normal range
```

### 6.2 Velocity Thresholds

| Metric | Normal Range | Alert Threshold | Emergency Threshold |
|--------|-------------|-----------------|---------------------|
| Articles/hour | 2-10 | > 15 | > 25 |
| Sentiment shift/hour | ±0.1 | ±0.3 | ±0.5 |
| Source diversity | 3+ sources | < 2 sources | 1 source only |
| Time since last article | < 4h | > 12h | > 24h |

### 6.3 Avalanche Detection

```python
def detect_avalanche(items: list[NewsItem], window_minutes: int = 60) -> AvalancheSignal:
    """Detect rapid news accumulation.
    
    Triggers:
    - 5+ articles in window with same sentiment direction
    - 3+ articles from different sources about same event
    - Rapid sentiment shift (>0.3 in 30 minutes)
    
    Response:
    - Positive avalanche → Amplify bullish signal
    - Negative avalanche → EMERGENCY VETO
    """
    recent = [i for i in items if i.age_minutes < window_minutes]
    
    if len(recent) < 5:
        return AvalancheSignal(detected=False)
    
    bullish = sum(1 for i in recent if i.sentiment > 0.2)
    bearish = sum(1 for i in recent if i.sentiment < -0.2)
    
    if bearish >= 5:
        return AvalancheSignal(
            detected=True,
            direction="bearish",
            severity="emergency",
            action="VETO_ALL",
        )
    
    if bullish >= 5:
        return AvalancheSignal(
            detected=True,
            direction="bullish",
            severity="opportunity",
            action="AMPLIFY_SIGNAL",
        )
    
    return AvalancheSignal(detected=False)
```

---

## 7. Fake News & FUD Detection

### 7.1 Detection Strategies

```python
class FakeNewsDetector:
    """Detect manipulated, coordinated, or false news."""
    
    def verify(self, item: NewsItem, all_items: list[NewsItem]) -> VerificationResult:
        """Multi-layer verification."""
        
        checks = [
            self._check_multi_source(item, all_items),      # 2+ sources required for CRITICAL
            self._check_source_reliability(item),            # Weight by source tier
            self._check_coordinated_fud(item, all_items),    # Detect FUD campaigns
            self._check_pump_and_dump(item, all_items),      # Detect P&D signals
            self._check_historical_accuracy(item),           # Source track record
            self._check_headline_body_mismatch(item),        # Clickbait detection
        ]
        
        return VerificationResult(
            verified=all(c.passed for c in checks if c.required),
            confidence=sum(c.weight for c in checks if c.passed),
            flags=[c.flag for c in checks if not c.passed],
        )
```

### 7.2 Multi-Source Verification

```python
def _check_multi_source(self, item: NewsItem, all_items: list[NewsItem]) -> Check:
    """CRITICAL news must be confirmed by 2+ independent sources.
    
    Rule: If severity == CRITICAL and only 1 source → DOWNGRADE to HIGH
    until verified by a second source.
    """
    if item.severity != CRITICAL:
        return Check(passed=True, required=False)
    
    # Find articles about the same event from different sources
    same_event = [
        i for i in all_items
        if i.source != item.source
        and self._is_same_event(i.title, item.title)
    ]
    
    if len(same_event) >= 1:  # At least 1 other source
        return Check(passed=True, required=True)
    
    return Check(
        passed=False,
        required=True,
        flag="UNVERIFIED_CRITICAL",
        action="DOWNGRADE_TO_HIGH",
    )
```

### 7.3 Coordinated FUD Detection

```python
def _check_coordinated_fud(self, item: NewsItem, all_items: list[NewsItem]) -> Check:
    """Detect coordinated FUD campaigns.
    
    Signals:
    - 3+ articles with nearly identical titles from low-quality sources
    - Published within 30 minutes of each other
    - All negative sentiment
    - No Tier 1 source coverage
    """
    similar = [
        i for i in all_items
        if i.age_minutes < 30
        and i.sentiment < -0.3
        and self._title_similarity(i.title, item.title) > 0.7
    ]
    
    low_quality = [i for i in similar if SOURCE_RELIABILITY.get(i.source, 0.2) < 0.5]
    tier1 = [i for i in similar if SOURCE_RELIABILITY.get(i.source, 0.2) >= 0.85]
    
    if len(low_quality) >= 3 and len(tier1) == 0:
        return Check(
            passed=False,
            flag="COORDINATED_FUD",
            action="SUPPRESS",
        )
    
    return Check(passed=True)
```

### 7.4 Pump-and-Dump Detection

```python
def _check_pump_and_dump(self, item: NewsItem, all_items: list[NewsItem]) -> Check:
    """Detect pump-and-dump signals.
    
    Signals:
    - Sudden bullish hype with no substantive catalyst
    - Low-cap token mentioned with extreme claims ("100x", "moon")
    - Multiple sources with identical bullish language
    - No Tier 1 source coverage
    """
    if item.sentiment < 0.5:
        return Check(passed=True)
    
    hype_words = {"100x", "10x", "moon", "gem", "next bitcoin", "guaranteed", "risk-free"}
    has_hype = any(w in item.title.lower() for w in hype_words)
    
    if has_hype:
        tier1_coverage = any(
            SOURCE_RELIABILITY.get(i.source, 0) >= 0.85
            for i in all_items
            if self._is_same_event(i.title, item.title)
        )
        
        if not tier1_coverage:
            return Check(
                passed=False,
                flag="PUMP_AND_DUMP",
                action="SUPPRESS",
            )
    
    return Check(passed=True)
```

---

## 8. News Gatekeeper Agent

### 8.1 Architecture

```python
class NewsGatekeeper(BaseAgent):
    """The news gatekeeper — THE veto authority for news events.
    
    Subscribes to: tsar:stream:news (from NewsMonitor)
    Publishes to: tsar:stream:signals (veto events)
    
    Authority: Can veto ANY trade regardless of technicals.
    Override: Only admin manual override (live mode requires explicit ack).
    """
    
    AGENT_NAME = "news_gatekeeper"
    ROLE = "TRADE_ADMIN"
    PUBLISH_STREAM = "signals"
    SUBSCRIBE_STREAMS = ["news"]
    
    # State
    _active_vetoes: dict[str, VetoRecord]  # symbol → active veto
    _news_digest: NewsDigest               # Latest digest
    _velocity: NewsVelocity                # Latest velocity metrics
    
    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        if stream == "news":
            await self._evaluate_news(event.data)
    
    async def _evaluate_news(self, news_data: dict) -> None:
        """Core evaluation logic."""
        
        # 1. Classify all new items
        classifications = [classify(item) for item in news_data["items"]]
        
        # 2. Check for CRITICAL items
        critical = [c for c in classifications if c.severity == CRITICAL]
        if critical:
            await self._issue_emergency_veto(critical)
            return
        
        # 3. Check velocity
        velocity = compute_velocity(news_data["items"])
        if velocity.avalanche_detected and velocity.direction == "bearish":
            await self._issue_velocity_veto(velocity)
            return
        
        # 4. Check for HIGH items (block new entries)
        high = [c for c in classifications if c.severity == HIGH]
        if high:
            await self._issue_entry_block(high)
        
        # 5. Update sentiment stream with news scores
        await self._publish_news_sentiment(classifications)
```

### 8.2 Veto Levels

```python
class NewsVeto:
    """News-triggered veto with escalation."""
    
    EMERGENCY = "emergency"    # CRITICAL news → Kill switch, all symbols
    SYMBOL_BLOCK = "symbol"    # HIGH news → Block specific symbol
    ENTRY_BLOCK = "entry"      # HIGH news → Block new entries only
    ALERT = "alert"            # MEDIUM news → Warning, reduce size
    CLEAR = "clear"            # Veto expired or lifted
```

### 8.3 Veto Lifecycle

```
CRITICAL news detected
    → EMERGENCY VETO (all symbols, all directions)
    → Notification sent (Telegram, priority CRITICAL)
    → Timer starts (minimum 1h hold)
    → Monitor for "all clear" signals:
        - Price stabilized (±2% for 30min)
        - No new negative news for 1h
        - Tier 1 source publishes "situation contained"
    → Downgrade to SYMBOL_BLOCK → ENTRY_BLOCK → CLEAR
```

---

## 9. Real-Time News Monitoring

### 9.1 Polling Architecture

```python
class NewsMonitor(BaseAgent):
    """Real-time news monitoring loop.
    
    Polls all sources every 60 seconds during active trading.
    Publishes aggregated news to the stream bus.
    """
    
    AGENT_NAME = "news_monitor"
    ROLE = "ANALYSIS"
    PUBLISH_STREAM = "news"
    SUBSCRIBE_STREAMS: list[str] = []
    
    # Polling intervals
    ACTIVE_POLL_INTERVAL = 60      # 60s during trading hours
    IDLE_POLL_INTERVAL = 300       # 5min during idle
    BREAKING_POLL_INTERVAL = 15    # 15s when breaking news detected
    
    async def run_cycle(self) -> None:
        """Main monitoring loop."""
        
        # 1. Fetch from all sources
        items = await self._fetch_all_sources()
        
        # 2. Classify each item
        classified = [self._classify(item) for item in items]
        
        # 3. Detect velocity
        velocity = self._compute_velocity(classified)
        
        # 4. Verify CRITICAL items
        for item in classified:
            if item.severity == CRITICAL:
                item.verified = await self._verify_critical(item)
        
        # 5. Publish to stream
        await self.publish_event(
            stream="news",
            event_type="tsar.news.update.v1",
            data={
                "items": [asdict(i) for i in classified],
                "velocity": asdict(velocity),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        
        # 6. Adjust polling interval
        if velocity.is_unusual:
            self._next_poll = self.BREAKING_POLL_INTERVAL
        elif self._is_trading_hours():
            self._next_poll = self.ACTIVE_POLL_INTERVAL
        else:
            self._next_poll = self.IDLE_POLL_INTERVAL
```

### 9.2 Source Priority & Fallback

```python
SOURCES = [
    # Primary (always fetch)
    {"name": "CryptoPanic", "type": "api", "interval": 60, "priority": 1},
    {"name": "CoinDesk", "type": "rss", "interval": 120, "priority": 1},
    {"name": "CoinTelegraph", "type": "rss", "interval": 120, "priority": 1},
    
    # Secondary (fetch every 2nd cycle)
    {"name": "Decrypt", "type": "rss", "interval": 180, "priority": 2},
    
    # Future: WebSocket for breaking news
    # {"name": "CryptoPanic_WS", "type": "websocket", "priority": 0},
]
```

### 9.3 Missing Sources — Gap Analysis & Recommendations

| Source | Type | Priority | Implementation |
|--------|------|----------|----------------|
| **Twitter/X Firehose** | API/WebSocket | HIGH | Use Twitter API v2 filtered stream. Keywords: "hack", "exploit", "SEC", "ban". Cost: $100/mo (Basic plan). |
| **Whale Alert** | API | HIGH | `whale-alert.io` API. Free tier: 10 req/min. Detect large transfers to exchanges. |
| **SEC EDGAR RSS** | RSS | MEDIUM | Monitor RSS for 8-K, S-1 filings mentioning crypto. Free. |
| **CFTC Announcements** | RSS | MEDIUM | Monitor CFTC press releases. Free. |
| **DeFi Exploit Alerts** | Twitter/Bot | HIGH | Follow `@peckshield`, `@CertiK`, `@SlowMist_Team`. Use Twitter API or RSS bridge. |
| **On-Chain Alerts** | API | MEDIUM | Integrate with existing `src/tools/on_chain.py` for whale movements. |
| **Glassnode Alerts** | API | LOW | Glassnode has alert API. Free tier limited. |

---

## 10. Integration with Existing Systems

### 10.1 Signal Quality Filter Integration

```python
# In signal_quality_filter.py — Factor 6 enhancement

def score_sentiment_alignment(
    fear_greed_index: int,
    news_sentiment: float,
    news_severity: NewsSeverity,     # NEW
    news_verified: bool,             # NEW
    funding_rate: float,
    side: str,
) -> tuple[float, str]:
    """Enhanced sentiment alignment with news classification."""
    
    # CRITICAL news override — hard zero
    if news_severity == CRITICAL:
        return 0.0, "CRITICAL news active — sentiment override"
    
    # HIGH news penalty
    if news_severity == HIGH:
        base_score *= 0.3  # Severe penalty
    
    # Unverified negative news — reduced weight
    if not news_verified and news_sentiment < -0.3:
        news_score *= 0.5  # Halve unverified negative impact
```

### 10.2 Risk Guardian Integration

```python
# In risk_guardian.py — Enhanced news blackout check

async def _check_news_gate(self, signal: Signal) -> RiskDecision | None:
    """Check NewsGatekeeper for active vetoes."""
    
    veto = self._news_gatekeeper.get_active_veto(signal.symbol)
    
    if veto and veto.level == "emergency":
        return RiskDecision(
            approved=False,
            veto_level=VetoLevel.NUCLEAR,
            rejection_reasons=[f"NEWS_EMERGENCY: {veto.reason}"],
        )
    
    if veto and veto.level == "symbol_block":
        return RiskDecision(
            approved=False,
            veto_level=VetoLevel.HARD,
            rejection_reasons=[f"NEWS_BLOCK: {veto.reason}"],
        )
    
    return None  # No news veto
```

### 10.3 Sentiment Agent Enhancement

```python
# In sentiment_agent.py — Replace raw news sentiment with classified sentiment

async def _fetch_news_sentiment(self) -> tuple[float, int]:
    """Enhanced: Use classified news sentiment instead of raw CryptoPanic votes."""
    
    # Old: Simple vote aggregation
    # New: Weighted by severity, decayed by age, verified by source
    
    items = await self._news_aggregator.get_news_digest("BTC", limit=30)
    
    weighted_sentiment = 0.0
    total_weight = 0.0
    
    for item in items.items:
        classification = classify_news(item)
        
        # Weight by severity (CRITICAL = 10x weight)
        severity_weight = {
            CRITICAL: 10.0,
            HIGH: 3.0,
            MEDIUM: 1.0,
            LOW: 0.1,
        }[classification.severity]
        
        # Apply time decay
        decayed = apply_decay(
            item.sentiment,
            item.age_minutes,
            classification.severity,
        )
        
        # Apply source reliability
        reliability = SOURCE_RELIABILITY.get(item.source, 0.2)
        
        weight = severity_weight * reliability
        weighted_sentiment += decayed * weight
        total_weight += weight
    
    if total_weight > 0:
        return weighted_sentiment / total_weight, len(items.items)
    return 0.0, 0
```

---

## 11. Configuration

```yaml
# config/news_gatekeeper.yaml

news_gatekeeper:
  enabled: true
  
  # Polling
  poll_interval_s: 60
  breaking_poll_interval_s: 15
  idle_poll_interval_s: 300
  
  # Classification
  classification:
    # How long to cache classifications
    cache_ttl_s: 300
    # Require LLM verification for CRITICAL
    llm_verify_critical: true
    # LLM model for verification
    llm_model: "gpt-4o-mini"
    
  # Verification
  verification:
    # Min sources for CRITICAL to be acted on
    min_sources_critical: 2
    # Min sources for HIGH
    min_sources_high: 1
    # FUD detection threshold (similar articles)
    fud_threshold: 3
    # FUD time window (minutes)
    fud_window_minutes: 30
    
  # Velocity
  velocity:
    # Articles per hour to trigger avalanche
    avalanche_threshold: 5
    # Hours of silence to trigger alert
    silence_threshold_hours: 24
    # Sentiment shift per hour to trigger alert
    sentiment_shift_threshold: 0.3
    
  # Veto durations (minutes)
  veto_durations:
    emergency: 60       # Minimum 1h for CRITICAL
    symbol_block: 30    # 30min for HIGH
    entry_block: 15     # 15min for MEDIUM-HIGH
    
  # Source reliability overrides
  source_reliability:
    Bloomberg: 0.95
    Reuters: 0.95
    CoinDesk: 0.90
    The Block: 0.90
    CoinTelegraph: 0.85
    Decrypt: 0.85
    CryptoPanic: 0.70
    Twitter: 0.40
    Reddit: 0.35
    
  # Notification
  notification:
    # Push CRITICAL news to Telegram
    critical_push: true
    # Push HIGH news to Telegram
    high_push: true
    # Batch MEDIUM news
    medium_batch_interval_s: 900
```

---

## 12. Test Strategy

### 12.1 Unit Tests

```python
# tests/unit/tools/test_news_classifier.py

class TestNewsClassifier:
    def test_critical_hack_detected(self):
        title = "Binance Hot Wallet Drained of $500M in Bitcoin"
        result = classify_news(title, "", "CoinDesk")
        assert result.severity == CRITICAL
        assert result.sentiment < -0.8
    
    def test_fud_suppressed(self):
        """Coordinated FUD from low-quality sources should be suppressed."""
        items = [
            NewsItem("BTC DEAD SCAM COIN", "UnknownBlog", sentiment=-0.9),
            NewsItem("BITCOIN IS A SCAM", "RandomSite", sentiment=-0.9),
            NewsItem("BTC CRASHING TO ZERO", "CryptoFUD", sentiment=-0.9),
        ]
        for item in items:
            result = classify_news(item.title, "", item.source)
            # Should flag as potential FUD
            assert "COORDINATED_FUD" in result.flags
    
    def test_unverified_critical_downgraded(self):
        """CRITICAL from single low-quality source should downgrade."""
        title = "EXCHANGE HACKED $1B STOLEN"
        result = classify_news(title, "", "UnknownBlog")
        # Single source, low reliability → downgrade
        assert result.severity == HIGH  # Not CRITICAL
        assert "UNVERIFIED" in result.flags
    
    def test_velocity_avalanche_negative(self):
        """5+ negative articles in 1h should trigger avalanche."""
        items = [
            NewsItem(f"Negative news {i}", "Source", sentiment=-0.7,
                     published_at=datetime.now(UTC) - timedelta(minutes=i*10))
            for i in range(6)
        ]
        velocity = compute_velocity(items)
        assert velocity.avalanche_detected
        assert velocity.direction == "bearish"
```

### 12.2 Integration Tests

```python
# tests/integration/test_news_gatekeeper_integration.py

class TestNewsGatekeeperIntegration:
    async def test_critical_news_blocks_trade(self, news_gatekeeper, risk_guardian):
        """CRITICAL news should block all trades via RiskGuardian."""
        
        # Inject critical news event
        await news_gatekeeper._evaluate_news({
            "items": [make_critical_news("Exchange hack detected")]
        })
        
        # Try to execute a trade
        signal = make_test_signal()
        decision = await risk_guardian._evaluate_signal(signal)
        
        assert not decision.approved
        assert "NEWS_EMERGENCY" in decision.rejection_reasons[0]
    
    async def test_veto_expires_after_duration(self, news_gatekeeper):
        """Veto should expire after configured duration."""
        
        await news_gatekeeper._issue_emergency_veto([make_critical_classification()])
        assert news_gatekeeper.has_active_veto("BTC")
        
        # Fast-forward past veto duration
        await advance_time(minutes=61)
        
        assert not news_gatekeeper.has_active_veto("BTC")
```

---

## 13. Scored Report

## News Detection Report

**Score: 7/10**

### Source Coverage: 6/10
- ✅ CryptoPanic API (votes-based sentiment)
- ✅ CoinDesk RSS
- ✅ CoinTelegraph RSS
- ✅ Decrypt RSS
- ❌ Twitter/X real-time stream (proxy only via CryptoPanic)
- ❌ Whale Alert API (not integrated)
- ❌ SEC/CFTC regulatory feeds
- ❌ On-chain exploit alerts (PeckShield, CertiK)
- ❌ WebSocket for breaking news (polling only)
- **Gap:** 5 of 9 recommended sources missing. Real-time capability limited to 60s polling.

### Classification System: 8/10
- ✅ 4-tier severity system (CRITICAL/HIGH/MEDIUM/LOW)
- ✅ Keyword-based classification with regex patterns
- ✅ Context-aware (requires crypto context for relevance)
- ✅ Covers all major categories (hack, ban, depeg, exploit, ETF, whale)
- ⚠️ LLM verification for CRITICAL (planned, not implemented)
- **Gap:** No LLM verification layer yet. Pure keyword matching risks false positives.

### Sentiment Scoring: 7/10
- ✅ -1.0 to +1.0 range
- ✅ Multi-factor (votes, keywords, source)
- ✅ Source reliability weighting
- ✅ Time decay model designed
- ⚠️ Decay model not implemented in current code
- ⚠️ Headline-only analysis (no full article parsing)
- **Gap:** Current implementation uses simple keyword matching. Decay model is designed but not wired.

### Velocity Detection: 5/10
- ✅ Architecture designed
- ✅ Avalanche detection defined (5+ articles/1h)
- ✅ Silence detection defined (24h no news)
- ✅ Sentiment velocity concept
- ❌ Not implemented
- ❌ No historical baseline for "normal" velocity
- **Gap:** Entirely designed but not coded. Critical for detecting flash crashes and pump events.

### Fake News Detection: 6/10
- ✅ Multi-source verification designed (2+ sources for CRITICAL)
- ✅ Coordinated FUD detection designed
- ✅ Pump-and-dump detection designed
- ✅ Source reliability tiers defined
- ⚠️ Title similarity matching (basic implementation)
- ❌ No historical accuracy tracking per source
- ❌ No headline/body mismatch detection
- **Gap:** Detection logic designed but not fully implemented. Missing historical accuracy database.

### Real-Time Monitoring: 7/10
- ✅ 60s polling during active trading
- ✅ Adaptive polling (15s during breaking news)
- ✅ Integration with NotificationEngine for CRITICAL alerts
- ✅ Event bus architecture (stream:news)
- ✅ Integration with RiskGuardian veto system
- ⚠️ No WebSocket support (polling only)
- ⚠️ Cache TTL of 180s in current NewsAggregator
- **Gap:** Polling-based (not push). 60s-180s blind spot on breaking events.

### Overall Assessment

The TSAR news detection system has a **solid architectural foundation** with 4 source integrations, basic sentiment scoring, and integration points into the SQF and RiskGuardian. However, it lacks the **institutional-grade classification engine**, **velocity detection**, and **fake news filtering** that would make it bulletproof. The existing `NewsAggregator` is a good data layer but needs a **classification + verification + velocity** layer on top.

**Priority improvements:**
1. 🔴 Implement `NewsClassifier` with keyword taxonomy + LLM verification
2. 🔴 Implement `NewsGatekeeper` agent with veto authority
3. 🔴 Implement velocity detection (avalanche + silence)
4. 🟡 Add Whale Alert API integration
5. 🟡 Add multi-source verification for CRITICAL news
6. 🟡 Reduce cache TTL from 180s to 60s
7. 🟢 Add Twitter/X filtered stream for real-time alerts
8. 🟢 Add SEC/CFTC regulatory RSS feeds
