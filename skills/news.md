---
name: news
description: News analysis — crypto news aggregation, sentiment analysis, whale monitoring, regulatory tracking
tools: [news, sentiment, whale_alert, regulatory_feeds, exploit_alerts, twitter_monitor, social_monitor, llm_news_verifier, source_accuracy_tracker, news_velocity]
requires_governance: false
---

# News Analysis Skill

## Purpose
Aggregate, verify, and analyze crypto news from multiple sources to detect market-moving events before they impact prices. The goal is information asymmetry — knowing what others don't.

## Instructions

### News Aggregation
Collect news from all available sources:
1. **CryptoPanic** — Aggregated crypto news with community voting
2. **Whale Alert** — Large on-chain transactions (>$1M)
3. **Regulatory Feeds** — SEC, CFTC, EU, UK regulatory announcements
4. **Exploit Alerts** — Smart contract exploits, hacks, rug pulls
5. **Twitter/X** — Key influencer posts, project announcements
6. **Social Channels** — Telegram, Discord community sentiment

### News Verification
Never act on unverified news:
1. Cross-reference across at least 2 independent sources
2. Check source accuracy score (from SourceAccuracyTracker)
3. Use LLM verification for suspicious claims
4. Check if news is stale (> 1 hour old = lower impact)
5. Verify against on-chain data when possible

### Sentiment Analysis
Quantify market sentiment:
1. Fear & Greed Index (extreme values = contrarian signals)
2. Social volume spikes (abnormal activity = attention)
3. Sentiment shift detection (bullish → bearish transitions)
4. Whale sentiment (large holder behavior)

### News Velocity
Track the speed of news propagation:
1. **Breaking** (< 5 min) — Highest impact, act quickly
2. **Emerging** (5-30 min) — High impact, verify first
3. **Established** (30-120 min) — Moderate impact, priced in
4. **Stale** (> 2 hours) — Low impact, likely priced in

### Impact Classification
Classify news by potential market impact:

| Impact | Examples | Action |
|--------|----------|--------|
| CRITICAL | Exchange hack, major exploit, BTC ETF decision | Immediate risk reduction |
| HIGH | Whale movement, regulatory action, protocol upgrade | Adjust positions |
| MEDIUM | Partnership announcement, listing, community vote | Monitor closely |
| LOW | Blog post, minor update, opinion piece | Log for reference |

### Economic Calendar
Track high-impact macro events:
- **FOMC** — Federal Reserve decisions (blackout: ±2 hours)
- **CPI** — Inflation data (blackout: ±1 hour)
- **NFP** — Employment data (blackout: ±1 hour)
- **GDP** — Economic growth data
- **BTC Options Expiry** — Large expiry = volatility

## News-Trade Integration
When news breaks during an active trade:
1. Assess if news affects the trade thesis
2. If CRITICAL: tighten stops or close immediately
3. If HIGH: reduce position size by 50%
4. If MEDIUM/LOW: monitor but don't react emotionally
5. NEVER add to a position based on news alone

## Tool Usage
```
news                    → Main news aggregator
sentiment               → Sentiment scoring and analysis
whale_alert             → Large transaction monitoring
regulatory_feeds        → SEC/CFTC/EU regulatory news
exploit_alerts          → Hack/exploit/rug pull alerts
twitter_monitor         → Key Twitter account monitoring
social_monitor          → Telegram/Discord community monitoring
llm_news_verifier       → LLM-based news verification
source_accuracy_tracker → Track source reliability over time
news_velocity           → News propagation speed tracking
```

## Source Accuracy Tracking
Maintain a reliability score per source:
- Correct predictions → increase score
- Incorrect/breaking news retracted → decrease score
- Sources below 40% accuracy are flagged as unreliable
- Prefer sources with > 70% accuracy for trading decisions
