# Signal Quality & Filtering System — Design Document

> **Council:** Signal Quality & Filtering
> **Goal:** Ensure ONLY high-probability trades execute. Target ≥75% win rate.
> **Context:** Valentine starts with $10. Every trade matters. No room for garbage signals.

---

## Architecture Overview

The Signal Quality Filter (SQF) sits between the `SignalScout` and the `RiskGuardian` in the trading pipeline. It is the **probability gate** — every signal must pass through it before risk sizing or execution is even considered.

```
SignalScout → [SIGNAL QUALITY FILTER] → RiskGuardian → ExecutionSniper
                    ↑
          SentimentAgent, OnChainTools,
          RegimeDetector, StopHuntDetector
```

The SQF does NOT generate signals. It **scores, filters, and enriches** existing signals with multi-factor confirmation.

---

## 1. Multi-Factor Signal Scoring (7 Factors)

Each factor produces a score in [0, 1]. The composite signal quality score is a weighted sum.

| # | Factor | Weight | Data Source | Scoring Logic |
|---|--------|--------|-------------|---------------|
| 1 | **RSI Confirmation** | 0.15 | `TechnicalAnalysisTools` | RSI oversold + volume spike → high score. RSI alone without volume → low score. |
| 2 | **Support/Resistance Proximity** | 0.20 | `PricingEngine.detect_support_resistance()` | Within 2% of key level = 1.0. Linear decay to 0 at 5%. |
| 3 | **Volume Confirmation** | 0.15 | OHLCV volume data | Current vol / 20-period avg. >1.5x = 1.0. <1.0 = 0.0. |
| 4 | **Trend Alignment** | 0.15 | `MultiTimeframeAnalyzer` | All timeframes agree = 1.0. Two agree = 0.6. One = 0.3. None = 0.0. |
| 5 | **Regime Filter** | 0.15 | `RegimeDetector` | Favorable regime = 1.0. Neutral = 0.3. Unfavorable = 0.0 (auto-reject). |
| 6 | **Sentiment Alignment** | 0.10 | `SentimentAgent` | Fear/Greed confirms direction = 1.0. Neutral = 0.5. Contradicts = 0.0. |
| 7 | **On-Chain Confirmation** | 0.10 | `OnChainTools` | Whale activity supports trade = 1.0. Neutral = 0.5. Opposes = 0.0. |

**Composite Score** = Σ(factor_score × weight) ∈ [0, 1]

### Position Sizing Tiers

| Score Range | Action | Position Size |
|-------------|--------|---------------|
| < 0.60 | **NO TRADE** | 0 (signal rejected) |
| 0.60 – 0.70 | Small position | 50% of normal |
| 0.70 – 0.80 | Normal position | 100% |
| > 0.80 | Large position | 150% of normal |

### Critical Rules

- **Minimum 3/7 factors must score > 0.3** — if fewer than 3 factors confirm, reject regardless of composite score.
- **No conflicting signals** — if any factor scores < 0.1 while another scores > 0.9, flag as suspicious (potential manipulation).
- **Volume MUST confirm price action** — price movement without volume = suspect. Volume factor weight is non-negotiable.
- **Regime MUST be favorable** — unfavorable regime = hard reject, no exceptions.

---

## 2. Confirmation Requirements

### Gate Logic (Applied in Order)

```
GATE 1: Regime Check
  └─ Unfavorable regime → REJECT (no further computation)

GATE 2: Minimum Factor Count
  └─ < 3 factors with score > 0.3 → REJECT

GATE 3: Conflict Detection
  └─ Any factor < 0.1 AND any factor > 0.9 → REJECT (manipulation signal)

GATE 4: Volume-Price Confirmation
  └─ Price moved > 1% in last 4h AND volume < average → REJECT (fake move)

GATE 5: Composite Score Threshold
  └─ Score < 0.6 → REJECT
  └─ Score 0.6-0.7 → SMALL position
  └─ Score 0.7-0.8 → NORMAL position
  └─ Score > 0.8 → LARGE position
```

---

## 3. False Signal Detection

Four specific false-signal detectors, all deterministic:

### 3a. False Breakout Detector
- **Pattern:** Price breaks a key level (support/resistance) but volume doesn't confirm.
- **Detection:** Breakout candle volume < 1.2× average → flag as false breakout.
- **Action:** Reject signal, log for pattern library.

### 3b. Stop Hunt Detector
- **Pattern:** Price spikes through a level, triggers stop losses, then immediately reverses.
- **Detection:** Price reversal > 60% of spike within 3 candles → stop hunt.
- **Action:** Reject signal, add symbol to cooldown (10 min).
- **Integration:** Uses existing `src/risk/stop_hunt.py` `StopHuntDetector`.

### 3c. Low-Liquidity Trap Detector
- **Pattern:** Wide bid-ask spread + thin order book = price can gap violently.
- **Detection:** Spread > 0.5% OR order book depth < $10K within 2% of price.
- **Action:** Reject signal. $10 accounts can't afford slippage.

### 3d. News-Driven Spike Detector
- **Pattern:** Sudden price spike driven by news, will revert.
- **Detection:** Price moved > 3% in < 15 min AND sentiment spike is recent (< 30 min).
- **Action:** Reject signal, wait for reversion confirmation.

---

## 4. Historical Win Rate Tracking

A persistent tracking system that records outcomes and adapts filters.

### Tracked Dimensions

| Dimension | Purpose |
|-----------|---------|
| **Signal type** (RSI oversold, overbought, etc.) | Disable signal types < 65% win rate |
| **Symbol** | Flag underperforming pairs |
| **Regime** (trending, ranging, volatile) | Adjust regime filter weights |
| **Time of day** (UTC hours) | Identify optimal trading windows |
| **Factor combination** | Learn which factor combos work best |

### Storage

SQLite database at `data/signal_quality.db`:

```sql
CREATE TABLE signal_outcomes (
    signal_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    score REAL NOT NULL,
    score_breakdown TEXT,  -- JSON
    regime TEXT,
    entry_price REAL,
    exit_price REAL,
    pnl_pct REAL,
    win BOOLEAN,
    signal_type TEXT,
    hour_utc INTEGER,
    factors_confirmed INTEGER,
    false_signal_flags TEXT,  -- JSON array of triggered flags
    timestamp TEXT NOT NULL,
    closed_at TEXT
);

CREATE INDEX idx_outcomes_symbol ON signal_outcomes(symbol);
CREATE INDEX idx_outcomes_signal_type ON signal_outcomes(signal_type);
CREATE INDEX idx_outcomes_regime ON signal_outcomes(regime);
CREATE INDEX idx_outcomes_timestamp ON signal_outcomes(timestamp);
```

### Win Rate Computation

Rolling window: last 50 trades per dimension. Minimum 10 trades before evaluation.

---

## 5. Adaptive Filtering

### Rules

| Condition | Action |
|-----------|--------|
| Win rate drops below 70% | Tighten: raise min_score to 0.65, require 4/7 factors |
| Win rate above 80% | Loosen slightly: lower min_score to 0.55, keep 3/7 factors |
| 3+ consecutive losses | Emergency tighten: raise min_score to 0.70, require 5/7 factors |
| 5+ consecutive wins | Maintain current filters (don't get greedy) |
| Specific signal type < 65% WR | Disable that signal type entirely |
| Specific symbol < 60% WR | Blacklist symbol for 24h |

### Adaptation Frequency

- Check win rate every 10 trades (not every trade — avoid overfitting).
- Emergency tighten triggers immediately on 3-loss streak.
- Loosening only after 20+ trades at current filter level.

### Safeguards

- Never loosen below score threshold 0.50 (absolute floor).
- Never reduce minimum factors below 2/7 (absolute floor).
- Adaptation is logged with full reasoning for audit trail.

---

## 6. Integration Points

### Inputs (Read From)
- `SignalScout` — raw signal with technical score
- `SentimentAgent` — fear/greed, news sentiment, funding rates
- `OnChainTools` — whale movements, exchange flows
- `RegimeDetector` — current market regime
- `StopHuntDetector` — stop hunt events
- `WhipsawDetector` — whipsaw state
- `MultiTimeframeAnalyzer` — cross-TF confluence

### Outputs (Publish To)
- `tsar:stream:signals:filtered` — enriched signal with quality score and position sizing
- `tsar:stream:quality_metrics` — real-time quality metrics for dashboard

### Event Types
- `tsar.signal.quality_scored.v1` — signal scored with all factors
- `tsar.signal.quality_rejected.v1` — signal rejected with reasons
- `tsar.signal.quality_adapted.v1` — filter parameters adapted

---

## 7. Configuration (signal_quality.yaml)

```yaml
signal_quality:
  enabled: true

  # Scoring weights (must sum to 1.0)
  weights:
    rsi_confirmation: 0.15
    sr_proximity: 0.20
    volume_confirmation: 0.15
    trend_alignment: 0.15
    regime_filter: 0.15
    sentiment_alignment: 0.10
    onchain_confirmation: 0.10

  # Thresholds
  thresholds:
    no_trade: 0.60
    small_position: 0.70
    normal_position: 0.80
    large_position: 0.80

  # Confirmation requirements
  confirmation:
    min_factors: 3
    min_factor_score: 0.3
    regime_must_be_favorable: true
    volume_must_confirm: true

  # False signal detection
  false_signals:
    false_breakout_volume_threshold: 1.2
    stop_hunt_reversal_pct: 0.60
    stop_hunt_recovery_candles: 3
    low_liquidity_spread_pct: 0.5
    news_spike_pct: 3.0
    news_spike_minutes: 15

  # Adaptive filtering
  adaptive:
    enabled: true
    check_interval_trades: 10
    tighten_below_wr: 0.70
    loosen_above_wr: 0.80
    loss_streak_emergency: 3
    win_streak_maintain: 5
    disable_signal_type_below_wr: 0.65
    blacklist_symbol_below_wr: 0.60
    blacklist_symbol_hours: 24
    absolute_min_score: 0.50
    absolute_min_factors: 2

  # Win rate tracking
  tracking:
    rolling_window: 50
    min_trades_for_eval: 10
    db_path: "data/signal_quality.db"
```

---

## 8. $10 Account Specific Protections

With only $10, every cent matters. Additional hard rules:

1. **Maximum 2 concurrent positions** — can't diversify with $10.
2. **Minimum score 0.65 for first 20 trades** — cold start requires extra confidence.
3. **No trades during low-liquidity hours** (UTC 0-4 on weekdays, all weekend for altcoins).
4. **Spread tax**: If spread > 0.3% of entry price, add to cost basis. Reject if effective R:R drops below 1.5.
5. **Commission awareness**: Factor in 0.1% taker fee on both sides. Minimum R:R must be 1.5 after fees.

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/agents/signal_quality_filter.py` | Main SQF agent — scoring, filtering, enrichment |
| `src/agents/signal_quality_db.py` | SQLite persistence for win rate tracking |
| `src/agents/false_signal_detectors.py` | Four false-signal detection algorithms |
| `src/agents/adaptive_filter.py` | Adaptive filter parameter adjustment |
| `tests/test_signal_quality.py` | Comprehensive test suite |
| `config/signal_quality.yaml` | Configuration file |
