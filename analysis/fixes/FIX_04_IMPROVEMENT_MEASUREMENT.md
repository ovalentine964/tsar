# FIX 04: Improvement Measurement Framework

> **Gap:** No improvement measurement framework — can't prove the system is getting better.  
> **Severity:** HIGH — Without measurement, the "self-improving" claim is unverifiable.  
> **Owner:** Observability Specialist  
> **Date:** 2026-07-24  
> **Status:** Design Complete — Ready for Implementation  
> **Fixes:** `tsar/analysis/fixes/FIX_04_IMPROVEMENT_MEASUREMENT.md`

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Improvement Metrics Framework](#2-improvement-metrics-framework)
3. [Baseline System](#3-baseline-system)
4. [ImprovementDashboard Class](#4-improvementdashboard-class)
5. [Prometheus Metrics Integration](#5-prometheus-metrics-integration)
6. [Flywheel Health Score](#6-flywheel-health-score)
7. [SQL Schema Additions](#7-sql-schema-additions)
8. [Grafana Dashboard JSON](#8-grafana-dashboard-json)
9. [Alert Rules](#9-alert-rules)
10. [Integration Points](#10-integration-points)
11. [Implementation Roadmap](#11-implementation-roadmap)

---

## 1. Problem Statement

### 1.1 The Core Issue

TSAR's architecture defines a self-improving flywheel: **TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → TRADE BETTER**. But there is no framework to measure whether this flywheel is actually accelerating. Without measurement:

- We cannot prove the system is getting smarter over time
- We cannot detect when the flywheel is stalling or broken
- We cannot distinguish real improvement from random noise
- We cannot trigger interventions when improvement plateaus
- We cannot attribute improvement to specific subsystems (patterns, lessons, strategy mutations)

### 1.2 What "Improvement" Means

Improvement is **not** just higher P&L. P&L is influenced by market conditions, luck, and regime. True improvement means the system makes **better decisions** given the same market conditions. This requires measuring:

1. **Decision quality** — Are trades getting better on a risk-adjusted basis?
2. **Knowledge accumulation** — Is the system learning from every trade?
3. **Knowledge application** — Is accumulated knowledge being used in decisions?
4. **Adaptation speed** — How quickly does the system adapt to regime changes?
5. **Pattern discovery** — Is the system finding new, actionable patterns?
6. **Strategy evolution** — Are mutations leading to fitter strategies?

### 1.3 Success Criteria

| Criterion | Metric | Target |
|-----------|--------|--------|
| Can prove improvement over time | Sharpe trend slope > 0 over 90 days | Statistically significant (p < 0.05) |
| Can detect stalling | Alert within 7 days of plateau | Flywheel health < 0.4 for 7 days |
| Can attribute improvement | Know which subsystem drove gains | Per-subsystem contribution tracking |
| Can trigger intervention | Automated alerts on decline | Telegram + Grafana within 5 min |

---

## 2. Improvement Metrics Framework

### 2.1 Overview

Ten core metrics organized into three tiers:

| Tier | Focus | Metrics |
|------|-------|---------|
| **Performance** | Is the system making money? | expectancy_trend, sharpe_trend, risk_adjusted_return |
| **Intelligence** | Is the system getting smarter? | regime_accuracy, lesson_application_rate, lesson_violation_rate, knowledge_density |
| **Evolution** | Is the system adapting? | strategy_fitness, pattern_discovery_rate, execution_quality |

### 2.2 Metric Definitions

#### Metric 1: `expectancy_trend` (Performance)

**Definition:** 30-day rolling average PnL per trade, measured in basis points of account equity.

**Formula:**
```
expectancy_trend = Σ(realized_pnl_pct) / N  [over trailing 30 days]
```

**Data Source:** `trades.db → trades table`  
**Field:** `realized_pnl_pct`, filtered by `closed_at >= now() - 30d` and `status = 'CLOSED'`  
**Update Frequency:** After every trade close  
**Baseline:** First 30 trades' average expectancy  

**Interpretation:**
| Value | Meaning |
|-------|---------|
| > 0.5% per trade | Excellent — system has a strong edge |
| 0.1% - 0.5% | Good — edge exists but thin |
| 0% - 0.1% | Marginal — edge is negligible |
| < 0% | Losing — system is destroying value |

**Trend Detection:** Linear regression on daily expectancy values over 30 days. Slope > 0 = improving, slope < 0 = declining, |slope| < 0.001 = stable.

**SQL Computation:**
```sql
-- Daily expectancy for trend analysis
SELECT 
    date(closed_at) as trade_date,
    AVG(realized_pnl_pct) as daily_expectancy,
    COUNT(*) as trade_count
FROM trades
WHERE status = 'CLOSED' 
    AND is_deleted = 0
    AND closed_at >= datetime('now', '-30 days')
GROUP BY date(closed_at)
ORDER BY trade_date;
```

---

#### Metric 2: `sharpe_trend` (Performance)

**Definition:** 30-day rolling annualized Sharpe ratio of trade returns.

**Formula:**
```
sharpe_trend = (mean(daily_returns) / std(daily_returns)) * sqrt(252)
```

**Data Source:** `trades.db → trades table`  
**Field:** `realized_pnl_pct`, grouped by `date(closed_at)`  
**Update Frequency:** Daily (after market close)  
**Baseline:** Sharpe from first 30 trades  

**Interpretation:**
| Value | Meaning |
|-------|---------|
| > 2.0 | Exceptional |
| 1.0 - 2.0 | Good — institutional grade |
| 0.5 - 1.0 | Acceptable |
| 0 - 0.5 | Marginal |
| < 0 | Negative — losing money on risk-adjusted basis |

**SQL Computation:**
```sql
-- Daily returns for Sharpe calculation
WITH daily_returns AS (
    SELECT 
        date(closed_at) as trade_date,
        SUM(realized_pnl_pct) as daily_return
    FROM trades
    WHERE status = 'CLOSED' AND is_deleted = 0
        AND closed_at >= datetime('now', '-30 days')
    GROUP BY date(closed_at)
)
SELECT 
    AVG(daily_return) as mean_return,
    AVG(daily_return) * 252 as annualized_return,
    -- Sharpe calculated in Python from these daily returns
    COUNT(*) as trading_days
FROM daily_returns;
```

---

#### Metric 3: `regime_accuracy` (Intelligence)

**Definition:** How often the regime detector's classification matches the actual market behavior in hindsight.

**Formula:**
```
regime_accuracy = correct_classifications / total_classifications [over 30 days]
```

**Correct classification:** If regime = "trending_bull" and the market was indeed trending up over the next 24 hours (price increased > 1% with positive momentum), it's correct.

**Data Source:** `tsar.db → regime_history table` (predicted regime) + `trades.db → trades table` (actual price movement)  
**Update Frequency:** Daily (retroactive check of yesterday's classification)  
**Baseline:** Random accuracy (e.g., 20% for 5 regime states)

**SQL Computation:**
```sql
-- Compare regime predictions vs actual price movement
WITH regime_with_outcome AS (
    SELECT 
        rh.snapshot_date,
        rh.dominant_regime,
        rh.confidence,
        -- 24h forward return after regime classification
        (SELECT (close - open) / open * 100 
         FROM market_data md 
         WHERE md.symbol = 'BTC/USDT' AND md.timeframe = '1h'
         AND md.timestamp >= rh.snapshot_date
         ORDER BY md.timestamp LIMIT 24) as forward_return_24h
    FROM regime_history rh
    WHERE rh.snapshot_date >= datetime('now', '-30 days')
)
SELECT 
    dominant_regime,
    COUNT(*) as total,
    SUM(CASE 
        WHEN dominant_regime LIKE '%bull%' AND forward_return_24h > 1.0 THEN 1
        WHEN dominant_regime LIKE '%bear%' AND forward_return_24h < -1.0 THEN 1
        WHEN dominant_regime = 'ranging' AND ABS(forward_return_24h) < 1.0 THEN 1
        ELSE 0
    END) as correct,
    AVG(confidence) as avg_confidence
FROM regime_with_outcome
GROUP BY dominant_regime;
```

---

#### Metric 4: `lesson_application_rate` (Intelligence)

**Definition:** Percentage of trades where at least one lesson was referenced or applied in the decision.

**Formula:**
```
lesson_application_rate = trades_with_lessons_applied / total_trades [over 30 days]
```

**Data Source:** `lessons.db → lesson_applications table` (joined with `trades.db → trades`)  
**Update Frequency:** After each trade reflection  
**Baseline:** 0% (no lessons exist at start) — target: > 60% after 100 trades

**SQL Computation:**
```sql
-- Lesson application rate
SELECT 
    COUNT(DISTINCT la.trade_id) * 1.0 / COUNT(DISTINCT t.trade_id) as application_rate,
    COUNT(DISTINCT la.trade_id) as trades_with_lessons,
    COUNT(DISTINCT t.trade_id) as total_trades
FROM trades t
LEFT JOIN lesson_applications la ON t.trade_id = la.trade_id
WHERE t.status = 'CLOSED'
    AND t.closed_at >= datetime('now', '-30 days')
    AND t.is_deleted = 0;
```

---

#### Metric 5: `lesson_violation_rate` (Intelligence)

**Definition:** Percentage of trades that violated a known lesson (trading against accumulated wisdom).

**Formula:**
```
lesson_violation_rate = trades_with_violations / total_trades [over 30 days]
```

**Data Source:** `lessons.db → lesson_violations table`  
**Update Frequency:** After each trade reflection  
**Baseline:** N/A at start (no lessons to violate) — target: < 5% after 100 trades

**Interpretation:**
| Value | Meaning |
|-------|---------|
| 0% | Perfect compliance — all lessons applied |
| 0-5% | Good — occasional lapses |
| 5-15% | Concerning — lessons are being ignored |
| > 15% | Critical — the learning loop is broken |

**SQL Computation:**
```sql
-- Lesson violation rate
SELECT 
    COUNT(DISTINCT lv.trade_id) * 1.0 / COUNT(DISTINCT t.trade_id) as violation_rate,
    COUNT(DISTINCT lv.trade_id) as trades_with_violations,
    SUM(lv.pnl_impact) as total_violation_impact
FROM trades t
LEFT JOIN lesson_violations lv ON t.trade_id = lv.trade_id
WHERE t.status = 'CLOSED'
    AND t.closed_at >= datetime('now', '-30 days')
    AND t.is_deleted = 0;
```

---

#### Metric 6: `knowledge_density` (Intelligence)

**Definition:** Number of useful facts (patterns + lessons + validated insights) accumulated per trade.

**Formula:**
```
knowledge_density = (new_patterns + new_lessons + reinforced_lessons) / total_trades [over 30 days]
```

**Data Source:** `patterns.db → patterns` + `lessons.db → lessons`  
**Update Frequency:** Weekly (after pattern discovery runs)  
**Baseline:** 0 at start — target: > 0.3 (one new insight every 3 trades)

**SQL Computation:**
```sql
-- Knowledge density
WITH recent_knowledge AS (
    SELECT COUNT(*) as new_lessons
    FROM lessons
    WHERE discovered_at >= datetime('now', '-30 days')
    UNION ALL
    SELECT COUNT(*) as new_patterns
    FROM patterns
    WHERE discovered_at >= datetime('now', '-30 days')
),
recent_trades AS (
    SELECT COUNT(*) as trade_count
    FROM trades
    WHERE status = 'CLOSED'
        AND closed_at >= datetime('now', '-30 days')
        AND is_deleted = 0
)
SELECT 
    (SELECT new_lessons FROM recent_knowledge LIMIT 1) +
    (SELECT * FROM recent_knowledge LIMIT 1 OFFSET 1) as total_new_knowledge,
    (SELECT trade_count FROM recent_trades) as trades,
    ((SELECT new_lessons FROM recent_knowledge LIMIT 1) +
     (SELECT * FROM recent_knowledge LIMIT 1 OFFSET 1)) * 1.0 /
    MAX(1, (SELECT trade_count FROM recent_trades)) as knowledge_density;
```

---

#### Metric 7: `strategy_fitness` (Evolution)

**Definition:** Rolling 30-day Sharpe ratio per strategy genome, tracking fitness across generations.

**Formula:**
```
strategy_fitness[strategy_id] = sharpe_30d(strategy_id)
```

**Data Source:** `strategies.db → strategy_performance` + `trades.db → trades`  
**Update Frequency:** Daily  
**Baseline:** Each strategy's initial Sharpe after 30 trades  

**Evolution Tracking:**
```
fitness_improvement = current_child_sharpe - parent_sharpe_at_mutation
```

This directly measures whether mutations are producing fitter offspring.

**SQL Computation:**
```sql
-- Strategy fitness with lineage
SELECT 
    sg.strategy_id,
    sg.name,
    sg.version,
    sg.parent_id,
    sg.sharpe_ratio as current_sharpe,
    parent_sg.sharpe_ratio as parent_sharpe,
    sg.sharpe_ratio - COALESCE(parent_sg.sharpe_ratio, 0) as fitness_delta
FROM strategy_genomes sg
LEFT JOIN strategy_genomes parent_sg ON sg.parent_id = parent_sg.strategy_id
WHERE sg.status IN ('live', 'paper')
ORDER BY sg.sharpe_ratio DESC;
```

---

#### Metric 8: `pattern_discovery_rate` (Evolution)

**Definition:** Number of new validated patterns discovered per week.

**Formula:**
```
pattern_discovery_rate = new_patterns_with_confidence_gt_0.7 / weeks_elapsed
```

**Data Source:** `patterns.db → patterns`  
**Update Frequency:** Weekly  
**Baseline:** 0 at start — target: > 2 new validated patterns per week after 100 trades

**SQL Computation:**
```sql
-- Pattern discovery rate (weekly)
SELECT 
    strftime('%Y-%W', discovered_at) as week,
    COUNT(*) as new_patterns,
    SUM(CASE WHEN confidence >= 0.7 THEN 1 ELSE 0 END) as validated_patterns,
    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_patterns
FROM patterns
WHERE discovered_at >= datetime('now', '-90 days')
GROUP BY strftime('%Y-%W', discovered_at)
ORDER BY week DESC;
```

---

#### Metric 9: `execution_quality` (Performance)

**Definition:** Average slippage in basis points versus expected fill price, measured over 30 days.

**Formula:**
```
execution_quality = -1 * avg(slippage_bps) [negative because lower slippage = better]
```

**Data Source:** `trades.db → trades table`  
**Field:** `slippage_bps`  
**Update Frequency:** After every trade  
**Baseline:** Mean slippage from first 30 trades  

**Interpretation:**
| Value | Meaning |
|-------|---------|
| < 3 bps | Excellent execution |
| 3-10 bps | Good — within expected range |
| 10-20 bps | Degraded — check exchange connectivity |
| > 20 bps | Poor — execution subsystem needs investigation |

**SQL Computation:**
```sql
-- Execution quality trend
SELECT 
    date(closed_at) as trade_date,
    AVG(slippage_bps) as avg_slippage,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY slippage_bps) as p95_slippage,
    COUNT(*) as trade_count
FROM trades
WHERE status = 'CLOSED' 
    AND slippage_bps IS NOT NULL
    AND closed_at >= datetime('now', '-30 days')
GROUP BY date(closed_at)
ORDER BY trade_date;
```

---

#### Metric 10: `risk_adjusted_return` (Performance)

**Definition:** Return per unit of risk taken, measured as return / max_drawdown (Calmar-like ratio).

**Formula:**
```
risk_adjusted_return = total_return_pct / max_drawdown_pct [over 30 days]
```

**Data Source:** `trades.db → trades` + portfolio equity curve  
**Update Frequency:** Daily  
**Baseline:** Ratio from first 30 trades  

**SQL Computation:**
```sql
-- Risk-adjusted return (Calmar ratio approximation)
WITH period_stats AS (
    SELECT 
        SUM(realized_pnl_pct) as total_return,
        -- Max drawdown computed in Python from equity curve
        COUNT(*) as trade_count
    FROM trades
    WHERE status = 'CLOSED' 
        AND is_deleted = 0
        AND closed_at >= datetime('now', '-30 days')
)
SELECT 
    total_return,
    trade_count,
    total_return / MAX(1.0, /* max_drawdown_pct from Python */) as risk_adjusted_return
FROM period_stats;
```

---

### 2.3 Metric Summary Table

| # | Metric | Tier | Source Table | Update Freq | Window | Direction |
|---|--------|------|-------------|-------------|--------|-----------|
| 1 | expectancy_trend | Performance | trades | Per trade | 30d rolling | Higher = better |
| 2 | sharpe_trend | Performance | trades | Daily | 30d rolling | Higher = better |
| 3 | regime_accuracy | Intelligence | regime_history + trades | Daily | 30d rolling | Higher = better |
| 4 | lesson_application_rate | Intelligence | lesson_applications + trades | Per trade | 30d rolling | Higher = better |
| 5 | lesson_violation_rate | Intelligence | lesson_violations + trades | Per trade | 30d rolling | Lower = better |
| 6 | knowledge_density | Intelligence | lessons + patterns | Weekly | 30d rolling | Higher = better |
| 7 | strategy_fitness | Evolution | strategy_genomes + trades | Daily | 30d rolling | Higher = better |
| 8 | pattern_discovery_rate | Evolution | patterns | Weekly | 90d window | Higher = better |
| 9 | execution_quality | Performance | trades | Per trade | 30d rolling | Lower slippage = better |
| 10 | risk_adjusted_return | Performance | trades + equity curve | Daily | 30d rolling | Higher = better |

---

## 3. Baseline System

### 3.1 Purpose

Baselines establish "where we started." Without baselines, we cannot measure improvement. The baseline system records metric snapshots from the first 30 trades and uses statistical testing to determine whether subsequent changes represent real improvement or random noise.

### 3.2 Baseline Recording

Baselines are recorded after the first **30 closed trades** (the minimum sample for statistical validity). Each metric is recorded with its mean, standard deviation, and 95% confidence interval.

```python
# improvement/baseline.py

import numpy as np
from scipy import stats
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class MetricBaseline:
    """Baseline snapshot for a single metric."""
    metric_name: str
    value: float                    # Mean value from baseline period
    std_dev: float                  # Standard deviation
    ci_lower: float                 # 95% CI lower bound
    ci_upper: float                 # 95% CI upper bound
    sample_size: int                # Number of observations
    recorded_at: str                # ISO timestamp
    baseline_period_start: str      # First trade date
    baseline_period_end: str        # Last trade date (of first 30 trades)
    raw_values: list[float]         # Individual observations for later re-testing


class BaselineRecorder:
    """
    Records metric baselines from the first 30 trades.
    Provides statistical significance testing for improvement claims.
    """

    BASELINE_SAMPLE_SIZE = 30  # Minimum trades for valid baseline

    def __init__(self, db_connection):
        self.db = db_connection

    def record_baselines(self) -> dict[str, MetricBaseline]:
        """
        Compute and record baselines for all 10 metrics.
        Only runs once (when baseline_sample_size trades exist).
        """
        # Check if baselines already exist
        existing = self.db.execute(
            "SELECT COUNT(*) FROM improvement_baselines"
        ).fetchone()[0]
        if existing > 0:
            return self._load_baselines()

        # Get first 30 trades
        trades = self.db.execute("""
            SELECT * FROM trades
            WHERE status = 'CLOSED' AND is_deleted = 0
            ORDER BY closed_at ASC
            LIMIT ?
        """, (self.BASELINE_SAMPLE_SIZE,)).fetchall()

        if len(trades) < self.BASELINE_SAMPLE_SIZE:
            return {}  # Not enough trades yet

        baselines = {}

        # 1. Expectancy trend
        pnl_values = [t['realized_pnl_pct'] for t in trades if t['realized_pnl_pct'] is not None]
        baselines['expectancy_trend'] = self._record_baseline(
            'expectancy_trend', pnl_values
        )

        # 2. Sharpe trend (daily returns)
        daily_returns = self._aggregate_daily_returns(trades)
        sharpe_values = [r for r in daily_returns]
        baselines['sharpe_trend'] = self._record_baseline(
            'sharpe_trend', sharpe_values,
            transform=lambda x: np.mean(x) / max(np.std(x), 1e-8) * np.sqrt(252)
        )

        # 3. Regime accuracy
        regime_values = self._compute_regime_accuracy_batch(trades)
        baselines['regime_accuracy'] = self._record_baseline(
            'regime_accuracy', regime_values
        )

        # 4. Lesson application rate
        app_values = self._compute_lesson_app_rate_batch(trades)
        baselines['lesson_application_rate'] = self._record_baseline(
            'lesson_application_rate', app_values
        )

        # 5. Lesson violation rate
        violation_values = self._compute_lesson_violation_batch(trades)
        baselines['lesson_violation_rate'] = self._record_baseline(
            'lesson_violation_rate', violation_values
        )

        # 6. Knowledge density
        kd_values = [0.0] * len(trades)  # No knowledge at start
        baselines['knowledge_density'] = self._record_baseline(
            'knowledge_density', kd_values
        )

        # 7. Strategy fitness (per strategy)
        fitness_values = self._compute_strategy_fitness_batch(trades)
        baselines['strategy_fitness'] = self._record_baseline(
            'strategy_fitness', fitness_values
        )

        # 8. Pattern discovery rate
        baselines['pattern_discovery_rate'] = self._record_baseline(
            'pattern_discovery_rate', [0.0]  # No patterns at start
        )

        # 9. Execution quality
        slippage_values = [t['slippage_bps'] for t in trades if t['slippage_bps'] is not None]
        baselines['execution_quality'] = self._record_baseline(
            'execution_quality', slippage_values
        )

        # 10. Risk-adjusted return
        rar_values = self._compute_risk_adjusted_returns(trades)
        baselines['risk_adjusted_return'] = self._record_baseline(
            'risk_adjusted_return', rar_values
        )

        # Persist all baselines
        self._persist_baselines(baselines)

        return baselines

    def _record_baseline(
        self,
        metric_name: str,
        values: list[float],
        transform=None
    ) -> MetricBaseline:
        """Compute baseline statistics for a metric."""
        if transform:
            # For Sharpe-like metrics, compute from the raw series
            value = transform(values)
            std_dev = 0.0  # Single-point estimate
            ci_lower = value
            ci_upper = value
        else:
            arr = np.array(values, dtype=float)
            arr = arr[~np.isnan(arr)]
            if len(arr) == 0:
                return MetricBaseline(
                    metric_name=metric_name,
                    value=0.0, std_dev=0.0,
                    ci_lower=0.0, ci_upper=0.0,
                    sample_size=0,
                    recorded_at=datetime.utcnow().isoformat() + 'Z',
                    baseline_period_start='', baseline_period_end='',
                    raw_values=[]
                )

            value = float(np.mean(arr))
            std_dev = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

            # 95% confidence interval
            if len(arr) > 1:
                se = std_dev / np.sqrt(len(arr))
                t_crit = stats.t.ppf(0.975, df=len(arr) - 1)
                ci_lower = value - t_crit * se
                ci_upper = value + t_crit * se
            else:
                ci_lower = value
                ci_upper = value

        now = datetime.utcnow().isoformat() + 'Z'
        return MetricBaseline(
            metric_name=metric_name,
            value=value,
            std_dev=std_dev,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            sample_size=len(values),
            recorded_at=now,
            baseline_period_start='',
            baseline_period_end='',
            raw_values=values
        )

    def _persist_baselines(self, baselines: dict[str, MetricBaseline]):
        """Write baselines to improvement_baselines table."""
        for name, b in baselines.items():
            self.db.execute("""
                INSERT OR REPLACE INTO improvement_baselines
                (metric_name, value, std_dev, ci_lower, ci_upper,
                 sample_size, recorded_at, baseline_period_start,
                 baseline_period_end, raw_values_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                b.metric_name, b.value, b.std_dev,
                b.ci_lower, b.ci_upper, b.sample_size,
                b.recorded_at, b.baseline_period_start,
                b.baseline_period_end,
                __import__('json').dumps(b.raw_values)
            ))
        self.db.commit()

    def _load_baselines(self) -> dict[str, MetricBaseline]:
        """Load existing baselines from database."""
        rows = self.db.execute(
            "SELECT * FROM improvement_baselines"
        ).fetchall()
        baselines = {}
        for row in rows:
            baselines[row['metric_name']] = MetricBaseline(
                metric_name=row['metric_name'],
                value=row['value'],
                std_dev=row['std_dev'],
                ci_lower=row['ci_lower'],
                ci_upper=row['ci_upper'],
                sample_size=row['sample_size'],
                recorded_at=row['recorded_at'],
                baseline_period_start=row['baseline_period_start'],
                baseline_period_end=row['baseline_period_end'],
                raw_values=__import__('json').loads(row['raw_values_json'])
            )
        return baselines

    # ── Helper methods (stubs — implement against actual DB) ──

    def _aggregate_daily_returns(self, trades):
        """Aggregate trades into daily returns."""
        from collections import defaultdict
        daily = defaultdict(float)
        for t in trades:
            if t['closed_at'] and t['realized_pnl_pct']:
                day = t['closed_at'][:10]
                daily[day] += t['realized_pnl_pct']
        return list(daily.values())

    def _compute_regime_accuracy_batch(self, trades):
        """Compute regime accuracy per trade."""
        # Stub: requires regime_history join
        return [0.5] * len(trades)

    def _compute_lesson_app_rate_batch(self, trades):
        """Compute lesson application rate per trade."""
        return [0.0] * len(trades)

    def _compute_lesson_violation_batch(self, trades):
        """Compute lesson violation rate per trade."""
        return [0.0] * len(trades)

    def _compute_strategy_fitness_batch(self, trades):
        """Compute strategy fitness per trade."""
        from collections import defaultdict
        strategy_pnl = defaultdict(list)
        for t in trades:
            if t['strategy'] and t['realized_pnl_pct']:
                strategy_pnl[t['strategy']].append(t['realized_pnl_pct'])
        fitnesses = []
        for pnl_list in strategy_pnl.values():
            if len(pnl_list) > 1:
                arr = np.array(pnl_list)
                sharpe = np.mean(arr) / max(np.std(arr), 1e-8) * np.sqrt(252)
                fitnesses.append(sharpe)
        return fitnesses if fitnesses else [0.0]

    def _compute_risk_adjusted_returns(self, trades):
        """Compute risk-adjusted return values."""
        pnl_values = [t['realized_pnl_pct'] for t in trades if t['realized_pnl_pct']]
        if not pnl_values:
            return [0.0]
        cumulative = np.cumsum(pnl_values)
        peak = np.maximum.accumulate(cumulative)
        drawdowns = (peak - cumulative) / np.where(peak > 0, peak, 1)
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 1.0
        total_return = float(np.sum(pnl_values))
        rar = total_return / max(max_dd * 100, 0.01)
        return [rar]
```

### 3.3 Statistical Significance Testing

To claim "the system is improving," we must reject the null hypothesis that performance hasn't changed. We use two tests:

**Test 1: Welch's t-test (two-sample)**
Compares baseline period metrics against current period metrics.

```python
# improvement/significance.py

import numpy as np
from scipy import stats
from dataclasses import dataclass

@dataclass
class SignificanceResult:
    metric_name: str
    baseline_mean: float
    current_mean: float
    improvement: float          # current - baseline
    improvement_pct: float      # (current - baseline) / |baseline| * 100
    t_statistic: float
    p_value: float
    significant: bool           # p < 0.05
    confidence_interval: tuple  # 95% CI of the difference
    verdict: str                # 'IMPROVED' | 'DECLINED' | 'UNCHANGED'


class SignificanceTester:
    """
    Tests whether metric changes are statistically significant.
    Guards against false positives from random noise.
    """

    ALPHA = 0.05  # 95% confidence level

    def test_improvement(
        self,
        metric_name: str,
        baseline_values: list[float],
        current_values: list[float],
        higher_is_better: bool = True
    ) -> SignificanceResult:
        """
        Test whether current values are significantly different from baseline.

        Args:
            metric_name: Name of the metric
            baseline_values: Metric values from baseline period
            current_values: Metric values from current period
            higher_is_better: False for metrics like violation_rate, slippage

        Returns:
            SignificanceResult with statistical test outcomes
        """
        baseline_arr = np.array(baseline_values, dtype=float)
        current_arr = np.array(current_values, dtype=float)

        # Remove NaN
        baseline_arr = baseline_arr[~np.isnan(baseline_arr)]
        current_arr = current_arr[~np.isnan(current_arr)]

        if len(baseline_arr) < 5 or len(current_arr) < 5:
            return SignificanceResult(
                metric_name=metric_name,
                baseline_mean=float(np.mean(baseline_arr)) if len(baseline_arr) > 0 else 0,
                current_mean=float(np.mean(current_arr)) if len(current_arr) > 0 else 0,
                improvement=0, improvement_pct=0,
                t_statistic=0, p_value=1.0,
                significant=False,
                confidence_interval=(0, 0),
                verdict='INSUFFICIENT_DATA'
            )

        baseline_mean = float(np.mean(baseline_arr))
        current_mean = float(np.mean(current_arr))
        improvement = current_mean - baseline_mean

        # Direction-aware improvement percentage
        if abs(baseline_mean) > 1e-10:
            improvement_pct = (improvement / abs(baseline_mean)) * 100
        else:
            improvement_pct = float('inf') if improvement != 0 else 0.0

        # Welch's t-test (unequal variance)
        t_stat, p_value = stats.ttest_ind(
            current_arr, baseline_arr,
            equal_var=False
        )

        # Confidence interval for the difference
        se_diff = np.sqrt(
            np.var(current_arr, ddof=1) / len(current_arr) +
            np.var(baseline_arr, ddof=1) / len(baseline_arr)
        )
        df = min(len(current_arr), len(baseline_arr)) - 1
        t_crit = stats.t.ppf(0.975, df=max(df, 1))
        ci_lower = improvement - t_crit * se_diff
        ci_upper = improvement + t_crit * se_diff

        # Determine verdict
        if p_value < self.ALPHA:
            if higher_is_better:
                verdict = 'IMPROVED' if improvement > 0 else 'DECLINED'
            else:
                verdict = 'IMPROVED' if improvement < 0 else 'DECLINED'
        else:
            verdict = 'UNCHANGED'

        return SignificanceResult(
            metric_name=metric_name,
            baseline_mean=baseline_mean,
            current_mean=current_mean,
            improvement=improvement,
            improvement_pct=improvement_pct,
            t_statistic=float(t_stat),
            p_value=float(p_value),
            significant=p_value < self.ALPHA,
            confidence_interval=(float(ci_lower), float(ci_upper)),
            verdict=verdict
        )

    def test_all_metrics(
        self,
        baselines: dict,
        current_snapshots: dict
    ) -> dict[str, SignificanceResult]:
        """
        Run significance tests for all 10 metrics.

        Args:
            baselines: Dict of metric_name -> MetricBaseline
            current_snapshots: Dict of metric_name -> list of current values

        Returns:
            Dict of metric_name -> SignificanceResult
        """
        # Direction: True = higher is better, False = lower is better
        DIRECTION = {
            'expectancy_trend': True,
            'sharpe_trend': True,
            'regime_accuracy': True,
            'lesson_application_rate': True,
            'lesson_violation_rate': False,  # Lower is better
            'knowledge_density': True,
            'strategy_fitness': True,
            'pattern_discovery_rate': True,
            'execution_quality': False,  # Lower slippage is better
            'risk_adjusted_return': True,
        }

        results = {}
        for metric_name in baselines:
            if metric_name in current_snapshots:
                results[metric_name] = self.test_improvement(
                    metric_name=metric_name,
                    baseline_values=baselines[metric_name].raw_values,
                    current_values=current_snapshots[metric_name],
                    higher_is_better=DIRECTION.get(metric_name, True)
                )
        return results
```

### 3.4 Confidence Intervals

Every metric is reported with a 95% confidence interval. This prevents overreacting to noise.

**Reporting format:**
```
sharpe_trend: 1.42 [95% CI: 1.18, 1.66]  (baseline: 0.85, p=0.003, IMPROVED ✓)
```

**Decision rule:** Only declare "improvement" when the confidence interval of the current value **does not overlap** with the baseline confidence interval AND p < 0.05.

---

## 4. ImprovementDashboard Class

### 4.1 Architecture

```python
# improvement/dashboard.py

import sqlite3
import time
import json
import numpy as np
from scipy import stats
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable
from enum import Enum

# ── Enumerations ──────────────────────────────────────────────

class TrendDirection(Enum):
    IMPROVING = "improving"
    DECLINING = "declining"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ── Data Classes ──────────────────────────────────────────────

@dataclass
class MetricSnapshot:
    """Point-in-time snapshot of a single metric."""
    metric_name: str
    value: float
    std_dev: float
    ci_lower: float
    ci_upper: float
    sample_size: int
    trend: TrendDirection
    trend_slope: float
    trend_r_squared: float
    baseline_value: float
    delta_from_baseline: float
    pct_change_from_baseline: float
    p_value_vs_baseline: float
    is_significant: bool
    verdict: str  # 'IMPROVED' | 'DECLINED' | 'UNCHANGED' | 'INSUFFICIENT_DATA'
    computed_at: str


@dataclass
class FlywheelHealthReport:
    """Composite flywheel health assessment."""
    health_score: float             # 0.0 - 1.0
    classification: str             # 'healthy' | 'stalling' | 'broken'
    component_scores: dict          # metric_name -> normalized score
    contributing_factors: list      # What's driving the score
    deteriorating_factors: list     # What's dragging the score
    recommendation: str             # What to do about it
    computed_at: str


@dataclass
class ImprovementAlert:
    """An alert about a significant change in improvement metrics."""
    severity: AlertSeverity
    metric_name: str
    message: str
    current_value: float
    baseline_value: float
    p_value: float
    triggered_at: str


# ── Main Dashboard Class ──────────────────────────────────────

class ImprovementDashboard:
    """
    Real-time improvement measurement dashboard for TSAR.

    Computes all 10 improvement metrics, detects trends,
    runs statistical significance tests, and generates alerts.

    Usage:
        dashboard = ImprovementDashboard(db_path='data/tsar.db')
        snapshot = dashboard.compute_all_metrics()
        health = dashboard.compute_flywheel_health()
        alerts = dashboard.check_alerts()
        report = dashboard.generate_weekly_report()
    """

    # Metric direction: True = higher is better
    METRIC_DIRECTION = {
        'expectancy_trend': True,
        'sharpe_trend': True,
        'regime_accuracy': True,
        'lesson_application_rate': True,
        'lesson_violation_rate': False,
        'knowledge_density': True,
        'strategy_fitness': True,
        'pattern_discovery_rate': True,
        'execution_quality': False,
        'risk_adjusted_return': True,
    }

    # Flywheel health weights (must sum to 1.0)
    HEALTH_WEIGHTS = {
        'expectancy_trend': 0.15,
        'sharpe_trend': 0.15,
        'regime_accuracy': 0.10,
        'lesson_application_rate': 0.10,
        'lesson_violation_rate': 0.10,
        'knowledge_density': 0.10,
        'strategy_fitness': 0.10,
        'pattern_discovery_rate': 0.05,
        'execution_quality': 0.075,
        'risk_adjusted_return': 0.075,
    }

    # Alert thresholds
    ALERT_THRESHOLDS = {
        'sharpe_decline': {'severity': AlertSeverity.WARNING, 'threshold': -0.3},
        'sharpe_critical': {'severity': AlertSeverity.CRITICAL, 'threshold': -0.5},
        'violation_rate_high': {'severity': AlertSeverity.WARNING, 'threshold': 0.10},
        'violation_rate_critical': {'severity': AlertSeverity.CRITICAL, 'threshold': 0.20},
        'expectancy_negative': {'severity': AlertSeverity.WARNING, 'threshold': 0},
        'flywheel_stalling': {'severity': AlertSeverity.WARNING, 'threshold': 0.4},
        'flywheel_broken': {'severity': AlertSeverity.CRITICAL, 'threshold': 0.2},
        'lesson_rate_low': {'severity': AlertSeverity.WARNING, 'threshold': 0.3},
        'slippage_high': {'severity': AlertSeverity.WARNING, 'threshold': 15},
    }

    def __init__(
        self,
        db_path: str = 'data/tsar.db',
        redis_client=None,
        prometheus_registry=None,
        alert_callback: Optional[Callable] = None
    ):
        """
        Args:
            db_path: Path to tsar.db
            redis_client: Redis client for real-time state
            prometheus_registry: Prometheus registry for metrics export
            alert_callback: Async callback for sending alerts (e.g., Telegram)
        """
        self.db_path = db_path
        self.redis = redis_client
        self.prometheus = prometheus_registry
        self.alert_callback = alert_callback
        self._snapshots: dict[str, MetricSnapshot] = {}
        self._health_report: Optional[FlywheelHealthReport] = None

    def _get_db(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ── Core Metric Computation ────────────────────────────────

    def compute_all_metrics(self, window_days: int = 30) -> dict[str, MetricSnapshot]:
        """
        Compute all 10 improvement metrics and their trends.

        Args:
            window_days: Rolling window for metric computation

        Returns:
            Dict of metric_name -> MetricSnapshot
        """
        db = self._get_db()
        snapshots = {}

        try:
            # Load baselines
            baselines = self._load_baselines(db)

            # Compute each metric
            snapshots['expectancy_trend'] = self._compute_expectancy(db, window_days, baselines)
            snapshots['sharpe_trend'] = self._compute_sharpe(db, window_days, baselines)
            snapshots['regime_accuracy'] = self._compute_regime_accuracy(db, window_days, baselines)
            snapshots['lesson_application_rate'] = self._compute_lesson_app_rate(db, window_days, baselines)
            snapshots['lesson_violation_rate'] = self._compute_lesson_violation_rate(db, window_days, baselines)
            snapshots['knowledge_density'] = self._compute_knowledge_density(db, window_days, baselines)
            snapshots['strategy_fitness'] = self._compute_strategy_fitness(db, window_days, baselines)
            snapshots['pattern_discovery_rate'] = self._compute_pattern_discovery_rate(db, window_days, baselines)
            snapshots['execution_quality'] = self._compute_execution_quality(db, window_days, baselines)
            snapshots['risk_adjusted_return'] = self._compute_risk_adjusted_return(db, window_days, baselines)

            self._snapshots = snapshots

            # Persist daily snapshot
            self._persist_snapshot(db, snapshots)

            # Update Prometheus gauges
            self._update_prometheus(snapshots)

        finally:
            db.close()

        return snapshots

    def _compute_expectancy(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute expectancy_trend: rolling avg PnL per trade."""
        rows = db.execute("""
            SELECT date(closed_at) as trade_date,
                   AVG(realized_pnl_pct) as daily_avg,
                   COUNT(*) as n
            FROM trades
            WHERE status = 'CLOSED' AND is_deleted = 0
                AND closed_at >= datetime('now', ? || ' days')
            GROUP BY date(closed_at)
            ORDER BY trade_date
        """, (f'-{window_days}',)).fetchall()

        values = [r['daily_avg'] for r in rows if r['daily_avg'] is not None]
        return self._build_snapshot(
            'expectancy_trend', values, baselines,
            higher_is_better=True
        )

    def _compute_sharpe(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute sharpe_trend: 30-day rolling Sharpe ratio."""
        rows = db.execute("""
            SELECT date(closed_at) as trade_date,
                   SUM(realized_pnl_pct) as daily_return
            FROM trades
            WHERE status = 'CLOSED' AND is_deleted = 0
                AND closed_at >= datetime('now', ? || ' days')
            GROUP BY date(closed_at)
            ORDER BY trade_date
        """, (f'-{window_days}',)).fetchall()

        daily_returns = [r['daily_return'] for r in rows if r['daily_return'] is not None]

        if len(daily_returns) < 2:
            return self._build_snapshot('sharpe_trend', [], baselines, higher_is_better=True)

        arr = np.array(daily_returns)
        sharpe = float(np.mean(arr) / max(np.std(arr, ddof=1), 1e-8) * np.sqrt(252))

        # For Sharpe, we track the daily returns but report the composite Sharpe
        snapshot = self._build_snapshot('sharpe_trend', daily_returns, baselines, higher_is_better=True)
        # Override the value with the actual Sharpe ratio
        snapshot.value = sharpe
        return snapshot

    def _compute_regime_accuracy(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute regime_accuracy: how often regime detection matches reality."""
        rows = db.execute("""
            SELECT rh.snapshot_date, rh.dominant_regime, rh.confidence
            FROM regime_history rh
            WHERE rh.snapshot_date >= datetime('now', ? || ' days')
            ORDER BY rh.snapshot_date
        """, (f'-{window_days}',)).fetchall()

        # For each regime classification, check if the market moved as predicted
        accuracies = []
        for row in rows:
            regime = row['dominant_regime']
            # Look up actual price movement in the next 24h
            price_row = db.execute("""
                SELECT 
                    (SELECT close FROM market_data 
                     WHERE symbol = 'BTC/USDT' AND timeframe = '1h'
                     AND timestamp >= ? ORDER BY timestamp LIMIT 1) as price_start,
                    (SELECT close FROM market_data 
                     WHERE symbol = 'BTC/USDT' AND timeframe = '1h'
                     AND timestamp >= ? ORDER BY timestamp LIMIT 24) as price_end
            """, (row['snapshot_date'], row['snapshot_date'])).fetchone()

            if price_row and price_row['price_start'] and price_row['price_end']:
                ret = (price_row['price_end'] - price_row['price_start']) / price_row['price_start'] * 100
                correct = 0
                if 'bull' in regime and ret > 1.0:
                    correct = 1
                elif 'bear' in regime and ret < -1.0:
                    correct = 1
                elif regime == 'ranging' and abs(ret) < 1.0:
                    correct = 1
                accuracies.append(correct)

        return self._build_snapshot(
            'regime_accuracy', accuracies, baselines,
            higher_is_better=True
        )

    def _compute_lesson_app_rate(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute lesson_application_rate."""
        rows = db.execute("""
            SELECT date(t.closed_at) as trade_date,
                   COUNT(DISTINCT la.trade_id) * 1.0 / COUNT(DISTINCT t.trade_id) as rate
            FROM trades t
            LEFT JOIN lesson_applications la ON t.trade_id = la.trade_id
            WHERE t.status = 'CLOSED' AND t.is_deleted = 0
                AND t.closed_at >= datetime('now', ? || ' days')
            GROUP BY date(t.closed_at)
            HAVING COUNT(DISTINCT t.trade_id) > 0
            ORDER BY trade_date
        """, (f'-{window_days}',)).fetchall()

        values = [r['rate'] for r in rows if r['rate'] is not None]
        return self._build_snapshot(
            'lesson_application_rate', values, baselines,
            higher_is_better=True
        )

    def _compute_lesson_violation_rate(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute lesson_violation_rate."""
        rows = db.execute("""
            SELECT date(t.closed_at) as trade_date,
                   COUNT(DISTINCT lv.trade_id) * 1.0 / COUNT(DISTINCT t.trade_id) as rate
            FROM trades t
            LEFT JOIN lesson_violations lv ON t.trade_id = lv.trade_id
            WHERE t.status = 'CLOSED' AND t.is_deleted = 0
                AND t.closed_at >= datetime('now', ? || ' days')
            GROUP BY date(t.closed_at)
            HAVING COUNT(DISTINCT t.trade_id) > 0
            ORDER BY trade_date
        """, (f'-{window_days}',)).fetchall()

        values = [r['rate'] for r in rows if r['rate'] is not None]
        return self._build_snapshot(
            'lesson_violation_rate', values, baselines,
            higher_is_better=False
        )

    def _compute_knowledge_density(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute knowledge_density: new facts per trade."""
        trade_count = db.execute("""
            SELECT COUNT(*) as n FROM trades
            WHERE status = 'CLOSED' AND is_deleted = 0
                AND closed_at >= datetime('now', ? || ' days')
        """, (f'-{window_days}',)).fetchone()['n']

        lesson_count = db.execute("""
            SELECT COUNT(*) as n FROM lessons
            WHERE discovered_at >= datetime('now', ? || ' days')
        """, (f'-{window_days}',)).fetchone()['n']

        pattern_count = db.execute("""
            SELECT COUNT(*) as n FROM patterns
            WHERE discovered_at >= datetime('now', ? || ' days')
        """, (f'-{window_days}',)).fetchone()['n']

        total_knowledge = lesson_count + pattern_count
        density = total_knowledge / max(trade_count, 1)

        return self._build_snapshot(
            'knowledge_density', [density], baselines,
            higher_is_better=True
        )

    def _compute_strategy_fitness(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute strategy_fitness: rolling Sharpe per strategy genome."""
        rows = db.execute("""
            SELECT sg.strategy_id, sg.name, sg.sharpe_ratio
            FROM strategy_genomes sg
            WHERE sg.status IN ('live', 'paper')
        """).fetchall()

        sharpes = [r['sharpe_ratio'] for r in rows if r['sharpe_ratio'] is not None]
        return self._build_snapshot(
            'strategy_fitness', sharpes, baselines,
            higher_is_better=True
        )

    def _compute_pattern_discovery_rate(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute pattern_discovery_rate: new patterns per week."""
        weeks = max(window_days / 7, 1)
        count = db.execute("""
            SELECT COUNT(*) as n FROM patterns
            WHERE discovered_at >= datetime('now', ? || ' days')
                AND confidence >= 0.7
        """, (f'-{window_days}',)).fetchone()['n']

        rate = count / weeks
        return self._build_snapshot(
            'pattern_discovery_rate', [rate], baselines,
            higher_is_better=True
        )

    def _compute_execution_quality(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute execution_quality: average slippage (lower is better)."""
        rows = db.execute("""
            SELECT date(closed_at) as trade_date,
                   AVG(slippage_bps) as avg_slip
            FROM trades
            WHERE status = 'CLOSED' AND is_deleted = 0
                AND slippage_bps IS NOT NULL
                AND closed_at >= datetime('now', ? || ' days')
            GROUP BY date(closed_at)
            ORDER BY trade_date
        """, (f'-{window_days}',)).fetchall()

        values = [r['avg_slip'] for r in rows if r['avg_slip'] is not None]
        return self._build_snapshot(
            'execution_quality', values, baselines,
            higher_is_better=False
        )

    def _compute_risk_adjusted_return(self, db, window_days, baselines) -> MetricSnapshot:
        """Compute risk_adjusted_return: return / max_drawdown."""
        rows = db.execute("""
            SELECT realized_pnl_pct FROM trades
            WHERE status = 'CLOSED' AND is_deleted = 0
                AND closed_at >= datetime('now', ? || ' days')
            ORDER BY closed_at
        """, (f'-{window_days}',)).fetchall()

        pnl_values = [r['realized_pnl_pct'] for r in rows if r['realized_pnl_pct'] is not None]
        if not pnl_values:
            return self._build_snapshot('risk_adjusted_return', [], baselines, higher_is_better=True)

        cumulative = np.cumsum(pnl_values)
        peak = np.maximum.accumulate(cumulative)
        drawdowns = (peak - cumulative) / np.where(peak > 0, peak, 1)
        max_dd = float(np.max(drawdowns)) * 100 if len(drawdowns) > 0 else 1.0
        total_return = float(np.sum(pnl_values))
        rar = total_return / max(max_dd, 0.01)

        return self._build_snapshot(
            'risk_adjusted_return', [rar], baselines,
            higher_is_better=True
        )

    # ── Trend Detection ────────────────────────────────────────

    def _detect_trend(self, values: list[float]) -> tuple[TrendDirection, float, float]:
        """
        Detect trend direction using linear regression.

        Returns:
            (direction, slope, r_squared)
        """
        if len(values) < 3:
            return TrendDirection.INSUFFICIENT_DATA, 0.0, 0.0

        x = np.arange(len(values), dtype=float)
        y = np.array(values, dtype=float)

        # Remove NaN
        mask = ~np.isnan(y)
        x, y = x[mask], y[mask]
        if len(y) < 3:
            return TrendDirection.INSUFFICIENT_DATA, 0.0, 0.0

        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
        r_squared = r_value ** 2

        # Classify trend
        if p_value > 0.1:
            # Not statistically significant — call it stable
            direction = TrendDirection.STABLE
        elif abs(slope) < 1e-6:
            direction = TrendDirection.STABLE
        elif slope > 0:
            direction = TrendDirection.IMPROVING
        else:
            direction = TrendDirection.DECLINING

        return direction, float(slope), float(r_squared)

    # ── Snapshot Builder ───────────────────────────────────────

    def _build_snapshot(
        self,
        metric_name: str,
        values: list[float],
        baselines: dict,
        higher_is_better: bool
    ) -> MetricSnapshot:
        """Build a MetricSnapshot from raw values."""
        now = datetime.utcnow().isoformat() + 'Z'

        if not values:
            return MetricSnapshot(
                metric_name=metric_name,
                value=0.0, std_dev=0.0,
                ci_lower=0.0, ci_upper=0.0,
                sample_size=0,
                trend=TrendDirection.INSUFFICIENT_DATA,
                trend_slope=0.0, trend_r_squared=0.0,
                baseline_value=0.0,
                delta_from_baseline=0.0, pct_change_from_baseline=0.0,
                p_value_vs_baseline=1.0, is_significant=False,
                verdict='INSUFFICIENT_DATA',
                computed_at=now
            )

        arr = np.array(values, dtype=float)
        arr = arr[~np.isnan(arr)]

        value = float(np.mean(arr))
        std_dev = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

        # Confidence interval
        if len(arr) > 1:
            se = std_dev / np.sqrt(len(arr))
            t_crit = stats.t.ppf(0.975, df=len(arr) - 1)
            ci_lower = value - t_crit * se
            ci_upper = value + t_crit * se
        else:
            ci_lower = value
            ci_upper = value

        # Trend
        trend_dir, trend_slope, trend_r2 = self._detect_trend(values)

        # Baseline comparison
        baseline = baselines.get(metric_name)
        baseline_value = baseline.value if baseline else 0.0
        delta = value - baseline_value
        pct_change = (delta / abs(baseline_value) * 100) if abs(baseline_value) > 1e-10 else 0.0

        # Statistical significance vs baseline
        if baseline and baseline.raw_values and len(baseline.raw_values) > 1 and len(arr) > 1:
            t_stat, p_value = stats.ttest_ind(arr, np.array(baseline.raw_values), equal_var=False)
            p_value = float(p_value)
        else:
            p_value = 1.0

        is_significant = p_value < 0.05

        # Verdict
        if len(arr) < 5:
            verdict = 'INSUFFICIENT_DATA'
        elif not is_significant:
            verdict = 'UNCHANGED'
        else:
            if higher_is_better:
                verdict = 'IMPROVED' if delta > 0 else 'DECLINED'
            else:
                verdict = 'IMPROVED' if delta < 0 else 'DECLINED'

        return MetricSnapshot(
            metric_name=metric_name,
            value=value,
            std_dev=std_dev,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            sample_size=len(arr),
            trend=trend_dir,
            trend_slope=trend_slope,
            trend_r_squared=trend_r2,
            baseline_value=baseline_value,
            delta_from_baseline=delta,
            pct_change_from_baseline=pct_change,
            p_value_vs_baseline=p_value,
            is_significant=is_significant,
            verdict=verdict,
            computed_at=now
        )

    # ── Flywheel Health ────────────────────────────────────────

    def compute_flywheel_health(self) -> FlywheelHealthReport:
        """
        Compute composite flywheel health score.
        See Section 6 for full specification.
        """
        if not self._snapshots:
            self.compute_all_metrics()

        component_scores = {}
        contributing = []
        deteriorating = []

        for metric_name, weight in self.HEALTH_WEIGHTS.items():
            snapshot = self._snapshots.get(metric_name)
            if not snapshot:
                component_scores[metric_name] = 0.5  # Neutral if no data
                continue

            # Normalize metric to 0-1 score
            score = self._normalize_metric_score(metric_name, snapshot)
            component_scores[metric_name] = score

            if score >= 0.7:
                contributing.append(f"{metric_name}: {snapshot.value:.3f} ({snapshot.verdict})")
            elif score <= 0.3:
                deteriorating.append(f"{metric_name}: {snapshot.value:.3f} ({snapshot.verdict})")

        # Weighted average
        health_score = sum(
            component_scores.get(m, 0.5) * w
            for m, w in self.HEALTH_WEIGHTS.items()
        )

        # Classification
        if health_score >= 0.7:
            classification = 'healthy'
            recommendation = "Flywheel is operating well. Continue monitoring."
        elif health_score >= 0.4:
            classification = 'stalling'
            recommendation = (
                "Flywheel is stalling. Review deteriorating factors: "
                + ', '.join(deteriorating[:3])
                + ". Consider: running pattern discovery, reviewing lesson violations, "
                + "checking regime detector accuracy."
            )
        else:
            classification = 'broken'
            recommendation = (
                "CRITICAL: Flywheel is broken. Immediate intervention required. "
                "Deteriorating: " + ', '.join(deteriorating)
                + ". Actions: pause live trading, audit all subsystems, "
                + "review last 50 trades for systematic errors."
            )

        self._health_report = FlywheelHealthReport(
            health_score=health_score,
            classification=classification,
            component_scores=component_scores,
            contributing_factors=contributing,
            deteriorating_factors=deteriorating,
            recommendation=recommendation,
            computed_at=datetime.utcnow().isoformat() + 'Z'
        )

        # Persist health score
        db = self._get_db()
        try:
            db.execute("""
                INSERT INTO flywheel_health_history
                (health_score, classification, component_scores_json,
                 recommendation, computed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                health_score, classification,
                json.dumps(component_scores),
                recommendation,
                self._health_report.computed_at
            ))
            db.commit()
        finally:
            db.close()

        return self._health_report

    def _normalize_metric_score(self, metric_name: str, snapshot: MetricSnapshot) -> float:
        """
        Normalize a metric value to a 0-1 score for health computation.

        Uses sigmoid-like mapping centered on baseline:
        - At baseline: score = 0.5
        - 2x improvement: score ≈ 0.85
        - 2x decline: score ≈ 0.15
        """
        if snapshot.sample_size == 0:
            return 0.5  # Neutral

        higher_is_better = self.METRIC_DIRECTION.get(metric_name, True)

        # Use the delta from baseline as the improvement signal
        if abs(snapshot.baseline_value) > 1e-10:
            ratio = snapshot.value / snapshot.baseline_value
        else:
            # If baseline is 0, use absolute value
            ratio = 1.0 + snapshot.value * 10  # Scale small values

        if not higher_is_better:
            # Invert: for metrics where lower is better
            ratio = 2.0 - ratio  # 0.5x becomes 1.5, 2x becomes 0

        # Sigmoid normalization: score = 1 / (1 + exp(-k*(ratio - 1)))
        # k controls sensitivity. k=3 means ratio of 2 gives score ~0.95
        k = 3.0
        score = 1.0 / (1.0 + np.exp(-k * (ratio - 1.0)))

        # Blend with trend direction
        trend_bonus = 0.0
        if snapshot.trend == TrendDirection.IMPROVING:
            trend_bonus = 0.1
        elif snapshot.trend == TrendDirection.DECLINING:
            trend_bonus = -0.1

        # Blend with significance
        sig_bonus = 0.0
        if snapshot.is_significant and snapshot.verdict == 'IMPROVED':
            sig_bonus = 0.05
        elif snapshot.is_significant and snapshot.verdict == 'DECLINED':
            sig_bonus = -0.05

        final_score = np.clip(score + trend_bonus + sig_bonus, 0.0, 1.0)
        return float(final_score)

    # ── Alert System ───────────────────────────────────────────

    def check_alerts(self) -> list[ImprovementAlert]:
        """
        Check all metrics against alert thresholds.
        Returns list of triggered alerts.
        """
        alerts = []
        now = datetime.utcnow().isoformat() + 'Z'

        for metric_name, snapshot in self._snapshots.items():
            # Sharpe decline alert
            if metric_name == 'sharpe_trend':
                if snapshot.value < self.ALERT_THRESHOLDS['sharpe_critical']['threshold']:
                    alerts.append(ImprovementAlert(
                        severity=AlertSeverity.CRITICAL,
                        metric_name=metric_name,
                        message=f"Sharpe ratio critically low: {snapshot.value:.2f}",
                        current_value=snapshot.value,
                        baseline_value=snapshot.baseline_value,
                        p_value=snapshot.p_value_vs_baseline,
                        triggered_at=now
                    ))
                elif snapshot.value < self.ALERT_THRESHOLDS['sharpe_decline']['threshold']:
                    alerts.append(ImprovementAlert(
                        severity=AlertSeverity.WARNING,
                        metric_name=metric_name,
                        message=f"Sharpe ratio declining: {snapshot.value:.2f}",
                        current_value=snapshot.value,
                        baseline_value=snapshot.baseline_value,
                        p_value=snapshot.p_value_vs_baseline,
                        triggered_at=now
                    ))

            # Violation rate alert
            if metric_name == 'lesson_violation_rate':
                if snapshot.value > self.ALERT_THRESHOLDS['violation_rate_critical']['threshold']:
                    alerts.append(ImprovementAlert(
                        severity=AlertSeverity.CRITICAL,
                        metric_name=metric_name,
                        message=f"Lesson violation rate critically high: {snapshot.value:.1%}",
                        current_value=snapshot.value,
                        baseline_value=snapshot.baseline_value,
                        p_value=snapshot.p_value_vs_baseline,
                        triggered_at=now
                    ))
                elif snapshot.value > self.ALERT_THRESHOLDS['violation_rate_high']['threshold']:
                    alerts.append(ImprovementAlert(
                        severity=AlertSeverity.WARNING,
                        metric_name=metric_name,
                        message=f"Lesson violation rate elevated: {snapshot.value:.1%}",
                        current_value=snapshot.value,
                        baseline_value=snapshot.baseline_value,
                        p_value=snapshot.p_value_vs_baseline,
                        triggered_at=now
                    ))

            # Expectancy negative alert
            if metric_name == 'expectancy_trend':
                if snapshot.value < self.ALERT_THRESHOLDS['expectancy_negative']['threshold']:
                    alerts.append(ImprovementAlert(
                        severity=AlertSeverity.WARNING,
                        metric_name=metric_name,
                        message=f"Expectancy is negative: {snapshot.value:.4f}%",
                        current_value=snapshot.value,
                        baseline_value=snapshot.baseline_value,
                        p_value=snapshot.p_value_vs_baseline,
                        triggered_at=now
                    ))

            # Slippage alert
            if metric_name == 'execution_quality':
                if snapshot.value > self.ALERT_THRESHOLDS['slippage_high']['threshold']:
                    alerts.append(ImprovementAlert(
                        severity=AlertSeverity.WARNING,
                        metric_name=metric_name,
                        message=f"Average slippage elevated: {snapshot.value:.1f} bps",
                        current_value=snapshot.value,
                        baseline_value=snapshot.baseline_value,
                        p_value=snapshot.p_value_vs_baseline,
                        triggered_at=now
                    ))

            # Declining trend alert (any metric)
            if snapshot.trend == TrendDirection.DECLINING and snapshot.is_significant:
                alerts.append(ImprovementAlert(
                    severity=AlertSeverity.WARNING,
                    metric_name=metric_name,
                    message=(
                        f"{metric_name} shows significant declining trend "
                        f"(slope={snapshot.trend_slope:.6f}, p={snapshot.p_value_vs_baseline:.4f})"
                    ),
                    current_value=snapshot.value,
                    baseline_value=snapshot.baseline_value,
                    p_value=snapshot.p_value_vs_baseline,
                    triggered_at=now
                ))

        # Flywheel health alert
        if self._health_report:
            if self._health_report.health_score < self.ALERT_THRESHOLDS['flywheel_broken']['threshold']:
                alerts.append(ImprovementAlert(
                    severity=AlertSeverity.CRITICAL,
                    metric_name='flywheel_health',
                    message=(
                        f"Flywheel health CRITICAL: {self._health_report.health_score:.2f}. "
                        f"{self._health_report.recommendation}"
                    ),
                    current_value=self._health_report.health_score,
                    baseline_value=0.7,
                    p_value=0.0,
                    triggered_at=now
                ))
            elif self._health_report.health_score < self.ALERT_THRESHOLDS['flywheel_stalling']['threshold']:
                alerts.append(ImprovementAlert(
                    severity=AlertSeverity.WARNING,
                    metric_name='flywheel_health',
                    message=(
                        f"Flywheel health stalling: {self._health_report.health_score:.2f}. "
                        f"{self._health_report.recommendation}"
                    ),
                    current_value=self._health_report.health_score,
                    baseline_value=0.7,
                    p_value=0.0,
                    triggered_at=now
                ))

        # Send alerts via callback
        if alerts and self.alert_callback:
            for alert in alerts:
                self.alert_callback(alert)

        return alerts

    # ── Report Generation ──────────────────────────────────────

    def generate_weekly_report(self) -> str:
        """Generate a formatted weekly improvement report."""
        if not self._snapshots:
            self.compute_all_metrics()
        if not self._health_report:
            self.compute_flywheel_health()

        h = self._health_report
        lines = [
            "📊 TSAR Improvement Report — Weekly",
            "━" * 50,
            f"🏥 Flywheel Health: {h.health_score:.2f} [{h.classification.upper()}]",
            "",
            "── Performance Metrics ──",
        ]

        for m in ['expectancy_trend', 'sharpe_trend', 'execution_quality', 'risk_adjusted_return']:
            s = self._snapshots.get(m)
            if s:
                icon = '✅' if s.verdict == 'IMPROVED' else '❌' if s.verdict == 'DECLINED' else '➖'
                lines.append(
                    f"  {icon} {m}: {s.value:.4f} "
                    f"[baseline: {s.baseline_value:.4f}, Δ{s.pct_change_from_baseline:+.1f}%] "
                    f"trend={s.trend.value}"
                )

        lines.append("")
        lines.append("── Intelligence Metrics ──")
        for m in ['regime_accuracy', 'lesson_application_rate', 'lesson_violation_rate', 'knowledge_density']:
            s = self._snapshots.get(m)
            if s:
                icon = '✅' if s.verdict == 'IMPROVED' else '❌' if s.verdict == 'DECLINED' else '➖'
                lines.append(
                    f"  {icon} {m}: {s.value:.4f} "
                    f"[baseline: {s.baseline_value:.4f}] "
                    f"trend={s.trend.value}"
                )

        lines.append("")
        lines.append("── Evolution Metrics ──")
        for m in ['strategy_fitness', 'pattern_discovery_rate']:
            s = self._snapshots.get(m)
            if s:
                icon = '✅' if s.verdict == 'IMPROVED' else '❌' if s.verdict == 'DECLINED' else '➖'
                lines.append(
                    f"  {icon} {m}: {s.value:.4f} "
                    f"[baseline: {s.baseline_value:.4f}] "
                    f"trend={s.trend.value}"
                )

        lines.append("")
        lines.append(f"── Contributing Factors ──")
        for f in h.contributing_factors[:5]:
            lines.append(f"  ✅ {f}")

        lines.append("")
        lines.append(f"── Deteriorating Factors ──")
        for f in h.deteriorating_factors[:5]:
            lines.append(f"  ⚠️  {f}")

        lines.append("")
        lines.append(f"── Recommendation ──")
        lines.append(f"  {h.recommendation}")
        lines.append("━" * 50)

        return '\n'.join(lines)

    def generate_monthly_report(self) -> str:
        """Generate a monthly improvement report with deeper analysis."""
        # Same structure as weekly but with:
        # - 90-day trends instead of 30-day
        # - Per-strategy fitness evolution
        # - Pattern discovery timeline
        # - Lesson violation P&L impact
        # - Mutation effectiveness analysis
        weekly = self.generate_weekly_report()

        # Add monthly-specific sections
        db = self._get_db()
        try:
            # Mutation effectiveness
            mutations = db.execute("""
                SELECT 
                    m.mutation_type,
                    COUNT(*) as count,
                    AVG(child.sharpe_ratio - parent.sharpe_ratio) as avg_sharpe_delta
                FROM strategy_mutations m
                JOIN strategy_genomes parent ON m.parent_id = parent.strategy_id
                JOIN strategy_genomes child ON m.child_id = child.strategy_id
                WHERE m.created_at >= datetime('now', '-30 days')
                GROUP BY m.mutation_type
            """).fetchall()

            monthly_extra = [
                "",
                "── Mutation Effectiveness (30-day) ──",
            ]
            for row in mutations:
                delta = row['avg_sharpe_delta'] or 0
                icon = '✅' if delta > 0 else '❌'
                monthly_extra.append(
                    f"  {icon} {row['mutation_type']}: "
                    f"{row['count']} mutations, avg Sharpe Δ = {delta:+.3f}"
                )

            # Lesson violation P&L impact
            violation_impact = db.execute("""
                SELECT SUM(pnl_impact) as total_impact
                FROM lesson_violations
                WHERE created_at >= datetime('now', '-30 days')
            """).fetchone()

            monthly_extra.extend([
                "",
                f"── Lesson Violation P&L Impact ──",
                f"  Total cost of ignoring lessons: ${violation_impact['total_impact'] or 0:+.2f}",
            ])

        finally:
            db.close()

        return weekly + '\n'.join(monthly_extra)

    # ── Internal Helpers ───────────────────────────────────────

    def _load_baselines(self, db) -> dict:
        """Load baselines from database."""
        rows = db.execute("SELECT * FROM improvement_baselines").fetchall()
        from improvement.baseline import MetricBaseline
        baselines = {}
        for row in rows:
            baselines[row['metric_name']] = MetricBaseline(
                metric_name=row['metric_name'],
                value=row['value'],
                std_dev=row['std_dev'],
                ci_lower=row['ci_lower'],
                ci_upper=row['ci_upper'],
                sample_size=row['sample_size'],
                recorded_at=row['recorded_at'],
                baseline_period_start=row['baseline_period_start'],
                baseline_period_end=row['baseline_period_end'],
                raw_values=json.loads(row['raw_values_json'])
            )
        return baselines

    def _persist_snapshot(self, db, snapshots: dict):
        """Persist daily metric snapshot to improvement_snapshots."""
        now = datetime.utcnow().isoformat() + 'Z'
        for name, s in snapshots.items():
            db.execute("""
                INSERT INTO improvement_snapshots
                (metric_name, value, std_dev, ci_lower, ci_upper,
                 sample_size, trend, trend_slope, baseline_value,
                 delta_from_baseline, p_value, is_significant,
                 verdict, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s.metric_name, s.value, s.std_dev,
                s.ci_lower, s.ci_upper, s.sample_size,
                s.trend.value, s.trend_slope,
                s.baseline_value, s.delta_from_baseline,
                s.p_value_vs_baseline, 1 if s.is_significant else 0,
                s.verdict, now
            ))
        db.commit()

    def _update_prometheus(self, snapshots: dict):
        """Update Prometheus gauge metrics."""
        if not self.prometheus:
            return
        for name, s in snapshots.items():
            gauge = self.prometheus.get(f'tsar_improvement_{name}')
            if gauge:
                gauge.set(s.value)

            trend_gauge = self.prometheus.get(f'tsar_improvement_{name}_trend')
            if trend_gauge:
                trend_map = {
                    TrendDirection.IMPROVING: 1,
                    TrendDirection.STABLE: 0,
                    TrendDirection.DECLINING: -1,
                    TrendDirection.INSUFFICIENT_DATA: -999,
                }
                trend_gauge.set(trend_map.get(s.trend, -999))
```

---

## 5. Prometheus Metrics Integration

### 5.1 Metric Definitions

```yaml
# ── Improvement Metrics (Gauges) ──────────────────────────────

# Core metric values
tsar_improvement_expectancy_trend:
  type: Gauge
  help: "30-day rolling average PnL per trade (%)"
  labels: []

tsar_improvement_sharpe_trend:
  type: Gauge
  help: "30-day rolling annualized Sharpe ratio"
  labels: []

tsar_improvement_regime_accuracy:
  type: Gauge
  help: "Regime detection accuracy (0-1)"
  labels: []

tsar_improvement_lesson_application_rate:
  type: Gauge
  help: "Percentage of trades with lessons applied (0-1)"
  labels: []

tsar_improvement_lesson_violation_rate:
  type: Gauge
  help: "Percentage of trades violating known lessons (0-1)"
  labels: []

tsar_improvement_knowledge_density:
  type: Gauge
  help: "New facts (patterns + lessons) per trade"
  labels: []

tsar_improvement_strategy_fitness:
  type: Gauge
  help: "Average rolling Sharpe across strategy genomes"
  labels: []

tsar_improvement_pattern_discovery_rate:
  type: Gauge
  help: "New validated patterns per week"
  labels: []

tsar_improvement_execution_quality:
  type: Gauge
  help: "Average slippage in basis points (lower = better)"
  labels: []

tsar_improvement_risk_adjusted_return:
  type: Gauge
  help: "Return per unit of max drawdown"
  labels: []

# ── Trend Direction (Gauges: 1=improving, 0=stable, -1=declining) ──

tsar_improvement_expectancy_trend_trend:
  type: Gauge
  help: "Expectancy trend direction (1=improving, 0=stable, -1=declining)"
  labels: []

tsar_improvement_sharpe_trend_trend:
  type: Gauge
  help: "Sharpe trend direction"
  labels: []

tsar_improvement_regime_accuracy_trend:
  type: Gauge
  help: "Regime accuracy trend direction"
  labels: []

tsar_improvement_lesson_application_rate_trend:
  type: Gauge
  help: "Lesson application rate trend direction"
  labels: []

tsar_improvement_lesson_violation_rate_trend:
  type: Gauge
  help: "Lesson violation rate trend direction"
  labels: []

tsar_improvement_knowledge_density_trend:
  type: Gauge
  help: "Knowledge density trend direction"
  labels: []

tsar_improvement_strategy_fitness_trend:
  type: Gauge
  help: "Strategy fitness trend direction"
  labels: []

tsar_improvement_pattern_discovery_rate_trend:
  type: Gauge
  help: "Pattern discovery rate trend direction"
  labels: []

tsar_improvement_execution_quality_trend:
  type: Gauge
  help: "Execution quality trend direction"
  labels: []

tsar_improvement_risk_adjusted_return_trend:
  type: Gauge
  help: "Risk-adjusted return trend direction"
  labels: []

# ── Flywheel Health (Composite) ───────────────────────────────

tsar_flywheel_health_score:
  type: Gauge
  help: "Composite flywheel health score (0-1)"
  labels: []

tsar_flywheel_health_classification:
  type: Gauge
  help: "Flywheel health classification (2=healthy, 1=stalling, 0=broken)"
  labels: []

# ── Baseline Delta (Change from baseline) ─────────────────────

tsar_improvement_delta_from_baseline{metric}:
  type: Gauge
  help: "Delta from baseline for each metric"
  labels: ["metric"]

# ── Statistical Significance ──────────────────────────────────

tsar_improvement_p_value{metric}:
  type: Gauge
  help: "P-value of metric vs baseline"
  labels: ["metric"]

tsar_improvement_is_significant{metric}:
  type: Gauge
  help: "1 if metric change is statistically significant"
  labels: ["metric"]

# ── Counters ──────────────────────────────────────────────────

tsar_improvement_alerts_total{severity, metric}:
  type: Counter
  help: "Total improvement alerts fired"
  labels: ["severity", "metric"]

tsar_improvement_snapshots_total:
  type: Counter
  help: "Total daily snapshots recorded"
  labels: []
```

### 5.2 Prometheus Registration Code

```python
# improvement/prometheus_export.py

from prometheus_client import Gauge, Counter, CollectorRegistry

class ImprovementPrometheusExporter:
    """
    Exports improvement metrics to Prometheus.
    """

    def __init__(self, registry: CollectorRegistry = None):
        self.registry = registry or CollectorRegistry()
        self._gauges = {}
        self._counters = {}
        self._register_metrics()

    def _register_metrics(self):
        """Register all improvement metrics with Prometheus."""
        metric_names = [
            'expectancy_trend', 'sharpe_trend', 'regime_accuracy',
            'lesson_application_rate', 'lesson_violation_rate',
            'knowledge_density', 'strategy_fitness',
            'pattern_discovery_rate', 'execution_quality',
            'risk_adjusted_return'
        ]

        for name in metric_names:
            # Value gauge
            self._gauges[f'tsar_improvement_{name}'] = Gauge(
                f'tsar_improvement_{name}',
                f'Improvement metric: {name}',
                registry=self.registry
            )
            # Trend gauge
            self._gauges[f'tsar_improvement_{name}_trend'] = Gauge(
                f'tsar_improvement_{name}_trend',
                f'Trend direction for {name} (1=improving, 0=stable, -1=declining)',
                registry=self.registry
            )

        # Flywheel health
        self._gauges['tsar_flywheel_health_score'] = Gauge(
            'tsar_flywheel_health_score',
            'Composite flywheel health score (0-1)',
            registry=self.registry
        )
        self._gauges['tsar_flywheel_health_classification'] = Gauge(
            'tsar_flywheel_health_classification',
            'Flywheel health (2=healthy, 1=stalling, 0=broken)',
            registry=self.registry
        )

        # Counters
        self._counters['tsar_improvement_alerts_total'] = Counter(
            'tsar_improvement_alerts_total',
            'Total improvement alerts',
            ['severity', 'metric'],
            registry=self.registry
        )
        self._counters['tsar_improvement_snapshots_total'] = Counter(
            'tsar_improvement_snapshots_total',
            'Total improvement snapshots recorded',
            registry=self.registry
        )

    def get(self, metric_name: str):
        """Get a Prometheus gauge by name."""
        return self._gauges.get(metric_name)

    def update_from_dashboard(self, dashboard: 'ImprovementDashboard'):
        """Update all Prometheus metrics from dashboard state."""
        for name, snapshot in dashboard._snapshots.items():
            gauge = self._gauges.get(f'tsar_improvement_{name}')
            if gauge:
                gauge.set(snapshot.value)

            trend_gauge = self._gauges.get(f'tsar_improvement_{name}_trend')
            if trend_gauge:
                trend_map = {
                    'improving': 1, 'stable': 0,
                    'declining': -1, 'insufficient_data': -999
                }
                trend_gauge.set(trend_map.get(snapshot.trend.value, -999))

        # Flywheel health
        if dashboard._health_report:
            self._gauges['tsar_flywheel_health_score'].set(
                dashboard._health_report.health_score
            )
            class_map = {'healthy': 2, 'stalling': 1, 'broken': 0}
            self._gauges['tsar_flywheel_health_classification'].set(
                class_map.get(dashboard._health_report.classification, -1)
            )

        self._counters['tsar_improvement_snapshots_total'].inc()
```

---

## 6. Flywheel Health Score

### 6.1 Definition

The Flywheel Health Score is a **single composite number (0-1)** that answers: "Is TSAR's self-improvement loop working?"

### 6.2 Formula

```
flywheel_health = Σ(normalized_score[metric] × weight[metric])

Where weights are:
  expectancy_trend:           0.15  (Performance — is the edge real?)
  sharpe_trend:               0.15  (Performance — risk-adjusted quality)
  regime_accuracy:            0.10  (Intelligence — does the system understand markets?)
  lesson_application_rate:    0.10  (Intelligence — is knowledge being used?)
  lesson_violation_rate:      0.10  (Intelligence — are mistakes being repeated?)
  knowledge_density:          0.10  (Intelligence — is knowledge accumulating?)
  strategy_fitness:           0.10  (Evolution — are strategies improving?)
  pattern_discovery_rate:     0.05  (Evolution — is the system finding new edges?)
  execution_quality:          0.075 (Performance — is execution degrading?)
  risk_adjusted_return:       0.075 (Performance — return per unit risk)
```

### 6.3 Normalization

Each metric is normalized to 0-1 using a sigmoid function centered on the baseline:

```python
def normalize_metric(value, baseline, higher_is_better):
    """
    Normalize metric to 0-1 score.

    - At baseline: score = 0.5
    - 2x improvement: score ≈ 0.85
    - 2x decline: score ≈ 0.15
    - 3x improvement: score ≈ 0.95
    - 3x decline: score ≈ 0.05
    """
    if abs(baseline) > 1e-10:
        ratio = value / baseline
    else:
        ratio = 1.0 + value * 10

    if not higher_is_better:
        ratio = 2.0 - ratio

    k = 3.0  # Sensitivity parameter
    score = 1.0 / (1.0 + exp(-k * (ratio - 1.0)))

    return clamp(score, 0.0, 1.0)
```

### 6.4 Classification

| Score Range | Classification | Meaning | Action |
|-------------|---------------|---------|--------|
| **> 0.7** | 🟢 **Healthy** | Flywheel is accelerating. Improvement is real and compounding. | Continue monitoring. Celebrate wins. |
| **0.4 - 0.7** | 🟡 **Stalling** | Flywheel is slowing. Some subsystems are underperforming. | Investigate deteriorating factors. Run diagnostics. |
| **< 0.4** | 🔴 **Broken** | Flywheel has stopped or reversed. The system is NOT improving. | Pause live trading. Audit all subsystems. Human review required. |

### 6.5 Intervention Triggers

| Trigger | Condition | Action |
|---------|-----------|--------|
| **Flywheel Broken** | health < 0.4 for **any** single snapshot | Telegram CRITICAL alert |
| **Sustained Stall** | health < 0.4 for **7 consecutive days** | Pause new trades, investigate |
| **Rapid Decline** | health drops > 0.2 in 7 days | Telegram WARNING, review recent changes |
| **Subsystem Failure** | Any single metric at 0 for 7 days | Targeted diagnostic for that subsystem |
| **Plateau Detection** | health between 0.4-0.6 for 30 days | Consider: new strategy, new data sources, parameter reset |

### 6.6 Flywheel Health Trend Tracking

```sql
-- Track health score over time for trend analysis
SELECT 
    computed_at,
    health_score,
    classification,
    LAG(health_score, 7) OVER (ORDER BY computed_at) as health_7d_ago,
    health_score - LAG(health_score, 7) OVER (ORDER BY computed_at) as health_delta_7d
FROM flywheel_health_history
ORDER BY computed_at DESC
LIMIT 30;
```

---

## 7. SQL Schema Additions

### 7.1 improvement_baselines

Stores the baseline measurements from the first 30 trades. Written once, read frequently.

```sql
-- ============================================================
-- IMPROVEMENT BASELINES
-- Recorded once after the first 30 trades.
-- ============================================================

CREATE TABLE IF NOT EXISTS improvement_baselines (
    metric_name         TEXT PRIMARY KEY,          -- e.g. 'expectancy_trend'
    value               REAL NOT NULL,             -- Mean value from baseline period
    std_dev             REAL NOT NULL DEFAULT 0.0, -- Standard deviation
    ci_lower            REAL NOT NULL DEFAULT 0.0, -- 95% CI lower bound
    ci_upper            REAL NOT NULL DEFAULT 0.0, -- 95% CI upper bound
    sample_size         INTEGER NOT NULL,          -- Number of observations
    recorded_at         TEXT NOT NULL,              -- ISO8601 UTC
    baseline_period_start TEXT,                     -- First trade date
    baseline_period_end   TEXT,                     -- Last trade date (of first 30)
    raw_values_json     TEXT NOT NULL,              -- JSON array of individual values

    -- Metadata
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Index for quick lookup
CREATE INDEX IF NOT EXISTS idx_baselines_metric ON improvement_baselines(metric_name);
```

### 7.2 improvement_snapshots

Daily snapshots of all 10 metrics. One row per metric per day.

```sql
-- ============================================================
-- IMPROVEMENT SNAPSHOTS (daily)
-- One row per metric per day.
-- ============================================================

CREATE TABLE IF NOT EXISTS improvement_snapshots (
    snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name         TEXT NOT NULL,              -- e.g. 'expectancy_trend'
    value               REAL NOT NULL,              -- Current value
    std_dev             REAL NOT NULL DEFAULT 0.0,
    ci_lower            REAL NOT NULL DEFAULT 0.0,
    ci_upper            REAL NOT NULL DEFAULT 0.0,
    sample_size         INTEGER NOT NULL DEFAULT 0,

    -- Trend
    trend               TEXT NOT NULL DEFAULT 'insufficient_data',
                        CHECK(trend IN ('improving','declining','stable','insufficient_data')),
    trend_slope         REAL DEFAULT 0.0,           -- Linear regression slope
    trend_r_squared     REAL DEFAULT 0.0,           -- R² of trend fit

    -- Baseline comparison
    baseline_value      REAL DEFAULT 0.0,           -- Baseline mean
    delta_from_baseline REAL DEFAULT 0.0,           -- current - baseline
    pct_change          REAL DEFAULT 0.0,           -- % change from baseline

    -- Statistical significance
    p_value             REAL DEFAULT 1.0,           -- Welch's t-test p-value
    is_significant      INTEGER DEFAULT 0,          -- 1 if p < 0.05
    verdict             TEXT DEFAULT 'UNCHANGED'
                        CHECK(verdict IN ('IMPROVED','DECLINED','UNCHANGED','INSUFFICIENT_DATA')),

    -- Metadata
    computed_at         TEXT NOT NULL,              -- ISO8601 UTC

    UNIQUE(metric_name, computed_at)
);

-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_snapshots_metric ON improvement_snapshots(metric_name, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON improvement_snapshots(computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_verdict ON improvement_snapshots(verdict, computed_at DESC);

-- Composite index for trend analysis
CREATE INDEX IF NOT EXISTS idx_snapshots_metric_trend
    ON improvement_snapshots(metric_name, trend, computed_at DESC);
```

### 7.3 flywheel_health_history

Tracks the composite flywheel health score over time.

```sql
-- ============================================================
-- FLYWHEEL HEALTH HISTORY
-- One row per health computation (typically daily).
-- ============================================================

CREATE TABLE IF NOT EXISTS flywheel_health_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    health_score        REAL NOT NULL CHECK(health_score BETWEEN 0.0 AND 1.0),
    classification      TEXT NOT NULL CHECK(classification IN ('healthy','stalling','broken')),

    -- Component breakdown
    component_scores_json TEXT NOT NULL,            -- JSON: {metric: score}

    -- Context
    recommendation      TEXT,                       -- What to do about it
    contributing_factors TEXT,                       -- JSON array of positive factors
    deteriorating_factors TEXT,                      -- JSON array of negative factors

    -- Metadata
    computed_at         TEXT NOT NULL,              -- ISO8601 UTC

    UNIQUE(computed_at)
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_health_date ON flywheel_health_history(computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_class ON flywheel_health_history(classification, computed_at DESC);

-- Index for "broken for N days" queries
CREATE INDEX IF NOT EXISTS idx_health_score_window
    ON flywheel_health_history(computed_at, health_score);
```

### 7.4 Query Patterns

```sql
-- ── Pattern 1: Current improvement status ──
-- Get the latest snapshot for each metric
SELECT s.*
FROM improvement_snapshots s
INNER JOIN (
    SELECT metric_name, MAX(computed_at) as latest
    FROM improvement_snapshots
    GROUP BY metric_name
) latest ON s.metric_name = latest.metric_name AND s.computed_at = latest.latest
ORDER BY s.metric_name;

-- ── Pattern 2: Sharpe trend over 90 days ──
SELECT computed_at, value, trend, p_value, verdict
FROM improvement_snapshots
WHERE metric_name = 'sharpe_trend'
    AND computed_at >= datetime('now', '-90 days')
ORDER BY computed_at;

-- ── Pattern 3: Flywheel health trend ──
SELECT 
    computed_at,
    health_score,
    classification,
    health_score - LAG(health_score) OVER (ORDER BY computed_at) as daily_change,
    health_score - LAG(health_score, 7) OVER (ORDER BY computed_at) as weekly_change
FROM flywheel_health_history
ORDER BY computed_at DESC
LIMIT 30;

-- ── Pattern 4: Sustained stall detection ──
-- Find periods where health was < 0.4 for 7+ consecutive days
WITH consecutive AS (
    SELECT 
        computed_at,
        health_score,
        classification,
        SUM(CASE WHEN health_score >= 0.4 THEN 1 ELSE 0 END) 
            OVER (ORDER BY computed_at) as group_id
    FROM flywheel_health_history
)
SELECT MIN(computed_at) as stall_start, MAX(computed_at) as stall_end,
       COUNT(*) as days_stalled, AVG(health_score) as avg_health
FROM consecutive
WHERE health_score < 0.4
GROUP BY group_id
HAVING COUNT(*) >= 7;

-- ── Pattern 5: Metrics that improved significantly ──
SELECT metric_name, value, baseline_value, 
       delta_from_baseline, p_value, verdict
FROM improvement_snapshots
WHERE is_significant = 1 AND verdict = 'IMPROVED'
    AND computed_at = (SELECT MAX(computed_at) FROM improvement_snapshots)
ORDER BY delta_from_baseline DESC;

-- ── Pattern 6: Metrics that declined significantly ──
SELECT metric_name, value, baseline_value,
       delta_from_baseline, p_value, verdict
FROM improvement_snapshots
WHERE is_significant = 1 AND verdict = 'DECLINED'
    AND computed_at = (SELECT MAX(computed_at) FROM improvement_snapshots)
ORDER BY delta_from_baseline ASC;

-- ── Pattern 7: Strategy fitness evolution (mutation lineage) ──
SELECT 
    sg.name, sg.version,
    sg.sharpe_ratio as current_sharpe,
    parent_sg.sharpe_ratio as parent_sharpe,
    sg.sharpe_ratio - COALESCE(parent_sg.sharpe_ratio, 0) as fitness_delta,
    sm.mutation_type, sm.mutation_reason
FROM strategy_genomes sg
LEFT JOIN strategy_genomes parent_sg ON sg.parent_id = parent_sg.strategy_id
LEFT JOIN strategy_mutations sm ON sm.child_id = sg.strategy_id
WHERE sg.status IN ('live', 'paper')
ORDER BY sg.sharpe_ratio DESC;

-- ── Pattern 8: Lesson violation impact ──
SELECT 
    l.title, l.lesson_type,
    l.times_violated,
    l.violation_impact as total_pnl_impact,
    l.times_applied,
    l.confidence
FROM lessons l
WHERE l.times_violated > 0
ORDER BY l.violation_impact ASC  -- Worst impact first (most negative)
LIMIT 20;

-- ── Pattern 9: Knowledge density trend ──
WITH weekly_stats AS (
    SELECT 
        strftime('%Y-%W', computed_at) as week,
        AVG(value) as avg_density
    FROM improvement_snapshots
    WHERE metric_name = 'knowledge_density'
        AND computed_at >= datetime('now', '-90 days')
    GROUP BY strftime('%Y-%W', computed_at)
)
SELECT week, avg_density,
       avg_density - LAG(avg_density) OVER (ORDER BY week) as weekly_change
FROM weekly_stats
ORDER BY week DESC;
```

---

## 8. Grafana Dashboard JSON

### 8.1 Dashboard: TSAR Improvement Tracking

```json
{
  "dashboard": {
    "title": "TSAR — Improvement Tracking",
    "tags": ["tsar", "improvement", "flywheel"],
    "timezone": "browser",
    "refresh": "1h",
    "time": {
      "from": "now-90d",
      "to": "now"
    },
    "panels": [
      {
        "id": 1,
        "title": "🏥 Flywheel Health Score",
        "type": "gauge",
        "gridPos": {"h": 6, "w": 8, "x": 0, "y": 0},
        "targets": [
          {
            "expr": "tsar_flywheel_health_score",
            "legendFormat": "Health Score"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "min": 0,
            "max": 1,
            "thresholds": {
              "steps": [
                {"value": 0, "color": "red"},
                {"value": 0.4, "color": "yellow"},
                {"value": 0.7, "color": "green"}
              ]
            }
          }
        }
      },
      {
        "id": 2,
        "title": "📈 Flywheel Health Trend (90d)",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 16, "x": 8, "y": 0},
        "targets": [
          {
            "expr": "tsar_flywheel_health_score",
            "legendFormat": "Health Score"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "custom": {
              "drawStyle": "line",
              "lineWidth": 2,
              "fillOpacity": 10
            },
            "thresholds": {
              "steps": [
                {"value": 0, "color": "red"},
                {"value": 0.4, "color": "yellow"},
                {"value": 0.7, "color": "green"}
              ]
            }
          }
        }
      },
      {
        "id": 3,
        "title": "🎯 Performance Metrics",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 6},
        "targets": [
          {
            "expr": "tsar_improvement_expectancy_trend",
            "legendFormat": "Expectancy (%)"
          },
          {
            "expr": "tsar_improvement_sharpe_trend",
            "legendFormat": "Sharpe Ratio"
          },
          {
            "expr": "tsar_improvement_risk_adjusted_return",
            "legendFormat": "Risk-Adj Return"
          }
        ]
      },
      {
        "id": 4,
        "title": "🧠 Intelligence Metrics",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 6},
        "targets": [
          {
            "expr": "tsar_improvement_regime_accuracy",
            "legendFormat": "Regime Accuracy"
          },
          {
            "expr": "tsar_improvement_lesson_application_rate",
            "legendFormat": "Lesson App Rate"
          },
          {
            "expr": "1 - tsar_improvement_lesson_violation_rate",
            "legendFormat": "Lesson Compliance"
          },
          {
            "expr": "tsar_improvement_knowledge_density",
            "legendFormat": "Knowledge Density"
          }
        ]
      },
      {
        "id": 5,
        "title": "🧬 Evolution Metrics",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 14},
        "targets": [
          {
            "expr": "tsar_improvement_strategy_fitness",
            "legendFormat": "Strategy Fitness (avg Sharpe)"
          },
          {
            "expr": "tsar_improvement_pattern_discovery_rate",
            "legendFormat": "Pattern Discovery (per week)"
          }
        ]
      },
      {
        "id": 6,
        "title": "⚡ Execution Quality",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 14},
        "targets": [
          {
            "expr": "tsar_improvement_execution_quality",
            "legendFormat": "Avg Slippage (bps)"
          }
        ]
      },
      {
        "id": 7,
        "title": "📊 Metric Trends (Current vs Baseline)",
        "type": "table",
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": 22},
        "targets": [
          {
            "expr": "tsar_improvement_expectancy_trend",
            "legendFormat": "Expectancy",
            "instant": true
          },
          {
            "expr": "tsar_improvement_sharpe_trend",
            "legendFormat": "Sharpe",
            "instant": true
          },
          {
            "expr": "tsar_improvement_regime_accuracy",
            "legendFormat": "Regime Accuracy",
            "instant": true
          },
          {
            "expr": "tsar_improvement_lesson_application_rate",
            "legendFormat": "Lesson App Rate",
            "instant": true
          },
          {
            "expr": "tsar_improvement_lesson_violation_rate",
            "legendFormat": "Violation Rate",
            "instant": true
          },
          {
            "expr": "tsar_improvement_knowledge_density",
            "legendFormat": "Knowledge Density",
            "instant": true
          },
          {
            "expr": "tsar_improvement_strategy_fitness",
            "legendFormat": "Strategy Fitness",
            "instant": true
          },
          {
            "expr": "tsar_improvement_pattern_discovery_rate",
            "legendFormat": "Pattern Discovery",
            "instant": true
          },
          {
            "expr": "tsar_improvement_execution_quality",
            "legendFormat": "Execution Quality",
            "instant": true
          },
          {
            "expr": "tsar_improvement_risk_adjusted_return",
            "legendFormat": "Risk-Adj Return",
            "instant": true
          }
        ]
      },
      {
        "id": 8,
        "title": "🚨 Improvement Alerts (24h)",
        "type": "stat",
        "gridPos": {"h": 4, "w": 8, "x": 0, "y": 32},
        "targets": [
          {
            "expr": "increase(tsar_improvement_alerts_total{severity=\"critical\"}[24h])",
            "legendFormat": "Critical"
          },
          {
            "expr": "increase(tsar_improvement_alerts_total{severity=\"warning\"}[24h])",
            "legendFormat": "Warning"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "thresholds": {
              "steps": [
                {"value": 0, "color": "green"},
                {"value": 1, "color": "yellow"},
                {"value": 3, "color": "red"}
              ]
            }
          }
        }
      }
    ]
  }
}
```

---

## 9. Alert Rules

### 9.1 Prometheus AlertManager Rules

```yaml
groups:
  - name: tsar_improvement_alerts
    rules:
      # ── CRITICAL ──────────────────────────────────────────────

      - alert: FlywheelBroken
        expr: tsar_flywheel_health_score < 0.4
        for: 1d
        labels:
          severity: critical
        annotations:
          summary: "TSAR flywheel health is BROKEN (score={{ $value }})"
          description: >
            The composite flywheel health score has been below 0.4 for 24 hours.
            This means the self-improvement loop is not working.
            Immediate human review required.
          runbook: "Check /improvement/dashboard for details. Review deteriorating factors."

      - alert: FlywheelBroken7Days
        expr: avg_over_time(tsar_flywheel_health_score[7d]) < 0.4
        for: 0s
        labels:
          severity: critical
        annotations:
          summary: "TSAR flywheel health < 0.4 for 7 consecutive days"
          description: >
            The flywheel has been stalled/broken for a full week.
            Pause live trading and run full diagnostic.
          runbook: "1. Pause trading 2. Review all 10 metrics 3. Check recent strategy mutations 4. Audit lesson violations"

      - alert: SharpeCriticalDecline
        expr: tsar_improvement_sharpe_trend < -0.5
        for: 3d
        labels:
          severity: critical
        annotations:
          summary: "Sharpe ratio critically negative: {{ $value }}"

      - alert: LessonViolationRateCritical
        expr: tsar_improvement_lesson_violation_rate > 0.20
        for: 1d
        labels:
          severity: critical
        annotations:
          summary: "Lesson violation rate critically high: {{ $value }}"
          description: >
            Over 20% of trades are violating known lessons.
            The system is not applying its accumulated knowledge.

      # ── WARNING ───────────────────────────────────────────────

      - alert: FlywheelStalling
        expr: tsar_flywheel_health_score < 0.7
        for: 7d
        labels:
          severity: warning
        annotations:
          summary: "TSAR flywheel health stalling (score={{ $value }})"

      - alert: ExpectancyDecline
        expr: tsar_improvement_expectancy_trend < 0
        for: 7d
        labels:
          severity: warning
        annotations:
          summary: "Trade expectancy is negative over 30 days: {{ $value }}%"

      - alert: SharpeDecline
        expr: tsar_improvement_sharpe_trend < 0.3
        for: 7d
        labels:
          severity: warning
        annotations:
          summary: "Sharpe ratio declining: {{ $value }}"

      - alert: LessonApplicationRateLow
        expr: tsar_improvement_lesson_application_rate < 0.3
        for: 14d
        labels:
          severity: warning
        annotations:
          summary: "Lesson application rate below 30%: {{ $value }}"

      - alert: ExecutionQualityDegraded
        expr: tsar_improvement_execution_quality > 15
        for: 3d
        labels:
          severity: warning
        annotations:
          summary: "Average slippage elevated: {{ $value }}bps"

      - alert: KnowledgeDensityFlat
        expr: tsar_improvement_knowledge_density_trend == 0
        for: 30d
        labels:
          severity: warning
        annotations:
          summary: "Knowledge density has been flat for 30 days"

      - alert: PatternDiscoveryStalled
        expr: tsar_improvement_pattern_discovery_rate == 0
        for: 14d
        labels:
          severity: warning
        annotations:
          summary: "No new patterns discovered in 14 days"

      # ── INFO ──────────────────────────────────────────────────

      - alert: SignificantImprovement
        expr: tsar_improvement_is_significant == 1
        for: 0s
        labels:
          severity: info
        annotations:
          summary: "{{ $labels.metric }} shows statistically significant improvement"

      - alert: NewBaselineRecorded
        expr: increase(tsar_improvement_snapshots_total[1h]) > 0
        for: 0s
        labels:
          severity: info
        annotations:
          summary: "New improvement snapshot recorded"
```

---

## 10. Integration Points

### 10.1 Data Flow

```
                    IMPROVEMENT MEASUREMENT DATA FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  trades.db   │     │  lessons.db  │     │  patterns.db     │
│  (trades,    │     │  (lessons,   │     │  (patterns,      │
│   pnl,       │     │   violations,│     │   observations)  │
│   slippage)  │     │   apps)      │     │                  │
└──────┬───────┘     └──────┬───────┘     └────────┬─────────┘
       │                    │                       │
       └────────────────────┼───────────────────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │  ImprovementDashboard│
                 │  (Python)            │
                 │                      │
                 │  • compute_all_metrics│
                 │  • detect trends     │
                 │  • significance tests│
                 │  • flywheel health   │
                 │  • check alerts      │
                 └──────┬───────────────┘
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
   ┌──────────────┐ ┌────────┐ ┌──────────────┐
   │ improvement_ │ │Promethe│ │  Telegram    │
   │ snapshots    │ │us      │ │  Alerts      │
   │ (SQLite)     │ │Gauges  │ │              │
   └──────────────┘ └────────┘ └──────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   Grafana    │
                     │  Dashboard   │
                     └──────────────┘
```

### 10.2 Integration with Existing Agents

| Agent | Integration | How |
|-------|-------------|-----|
| **Trade Philosopher** | Feeds lesson_application_rate, lesson_violation_rate | After reflection, records whether lessons were applied/violated |
| **Strategy Geneticist** | Feeds strategy_fitness, pattern_discovery_rate | After mutation, records fitness delta; after pattern discovery, increments counter |
| **Execution Sniper** | Feeds execution_quality | Records slippage per trade |
| **Regime Detector** | Feeds regime_accuracy | Regime classifications are compared against actual price movement |
| **Risk Guardian** | Reads flywheel_health | Can pause trading if health < 0.4 |
| **Orchestrator** | Reads all metrics, routes alerts | Sends Telegram alerts on critical changes |
| **Signal Scout** | Reads lesson_violation_rate | Can weight signal scoring by lesson compliance |

### 10.3 Scheduling

| Task | Frequency | When | Component |
|------|-----------|------|-----------|
| Compute all metrics | Every hour | On the hour | ImprovementDashboard.compute_all_metrics() |
| Compute flywheel health | Every hour | After metrics | ImprovementDashboard.compute_flywheel_health() |
| Check alerts | Every hour | After health | ImprovementDashboard.check_alerts() |
| Record baselines | Once | After 30 trades | BaselineRecorder.record_baselines() |
| Generate weekly report | Weekly | Sunday 04:00 UTC | ImprovementDashboard.generate_weekly_report() |
| Generate monthly report | Monthly | 1st of month 05:00 UTC | ImprovementDashboard.generate_monthly_report() |
| Update Prometheus | Every hour | After metrics | ImprovementPrometheusExporter.update_from_dashboard() |

---

## 11. Implementation Roadmap

### Phase 1: Foundation (Week 1)

```
☐ Create SQL tables (improvement_baselines, improvement_snapshots, flywheel_health_history)
☐ Implement BaselineRecorder class
☐ Implement SignificanceTester class
☐ Implement ImprovementDashboard.compute_all_metrics() for first 3 metrics:
    - expectancy_trend
    - sharpe_trend
    - execution_quality
☐ Write unit tests for statistical significance
☐ Integration test: record baseline → compute metrics → verify snapshot persisted
```

### Phase 2: Full Metrics (Week 2)

```
☐ Implement remaining 7 metric computations
☐ Implement trend detection (linear regression)
☐ Implement flywheel health score computation
☐ Implement alert checking
☐ Implement weekly/monthly report generation
☐ Integration test: full dashboard cycle
```

### Phase 3: Prometheus + Grafana (Week 3)

```
☐ Implement ImprovementPrometheusExporter
☐ Register all Prometheus metrics
☐ Create Grafana dashboard JSON (import)
☐ Configure Prometheus alert rules
☐ Test alert routing to Telegram
☐ Integration test: metric → Prometheus → Grafana → alert
```

### Phase 4: Agent Integration (Week 4)

```
☐ Integrate with Trade Philosopher (lesson application/violation tracking)
☐ Integrate with Strategy Geneticist (strategy fitness tracking)
☐ Integrate with Execution Sniper (slippage tracking)
☐ Integrate with Regime Detector (regime accuracy tracking)
☐ Integrate with Orchestrator (alert routing)
☐ End-to-end test: trade → reflection → metric update → alert
```

### Phase 5: Validation (Week 5)

```
☐ Run dashboard against historical trade data (if available)
☐ Verify statistical significance tests against known outcomes
☐ Validate flywheel health classification logic
☐ Load test: 1000 trades, verify computation < 5 seconds
☐ Documentation: update architecture docs with improvement measurement references
```

---

## Appendix A: Metric Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Fewer than 30 trades total | Return 'INSUFFICIENT_DATA' for all metrics, don't record baseline |
| Zero trades in 30-day window | Return last known values, flag as stale |
| Metric value = 0 (baseline) | Use absolute value scaling instead of ratio |
| Negative Sharpe (baseline) | Invert normalization: improvement = moving toward 0 |
| Infinite profit factor | Cap at 100.0 for normalization |
| Single strategy in portfolio | strategy_fitness = that strategy's Sharpe |
| No lessons exist | lesson_application_rate = 0, lesson_violation_rate = 0 |
| No patterns exist | pattern_discovery_rate = 0 |
| All trades in one day | Use per-trade values instead of daily aggregation |
| Database locked (WAL contention) | Retry with exponential backoff (max 3 retries) |

---

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Baseline** | Metric values from the first 30 trades, used as the "starting point" for improvement measurement |
| **Flywheel Health** | Composite score (0-1) measuring whether TSAR's self-improvement loop is working |
| **Significance** | Statistical confidence that a metric change is real, not random noise (p < 0.05) |
| **Trend Direction** | Linear regression classification: improving (slope > 0), declining (slope < 0), stable (not significant) |
| **Knowledge Density** | Rate of new useful facts (patterns + lessons) accumulated per trade |
| **Strategy Fitness** | Rolling Sharpe ratio of a strategy genome, used to measure evolution effectiveness |
| **Lesson Compliance** | Inverse of violation_rate — percentage of trades that follow known lessons |

---

*End of FIX_04: Improvement Measurement Framework*
