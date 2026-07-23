# GAP RESOLUTION — How Every Gap Is Filled

**Version:** 1.0.0
**Date:** 2026-07-24
**Status:** APPROVED — All 21 gaps resolved with implementation plans
**Cross-references:** ARCHITECTURE_CONSOLIDATION.md, DAY1_ARCHITECTURE.md

---

## Table of Contents

1. [Critical Gap Resolutions (12)](#1-critical-gap-resolutions)
2. [Important Gap Resolutions (9)](#2-important-gap-resolutions)
3. [Layer Coverage Improvements](#3-layer-coverage-improvements)
4. [Implementation Priority Matrix](#4-implementation-priority-matrix)

---

## 1. Critical Gap Resolutions

### Gap C1: Backtesting Engine

**What was missing:** No mechanism to test strategies against historical data before live deployment. Paper trading serves as a proxy but is slow (real-time) and non-reproducible.

**How it's now implemented:**

```
┌─────────────────────────────────────────────────────┐
│              BACKTESTING ENGINE                       │
│                                                      │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐    │
│  │ Data     │──▶│ Strategy │──▶│ Performance  │    │
│  │ Loader   │   │ Simulator│   │ Calculator   │    │
│  └──────────┘   └──────────┘   └──────────────┘    │
│       │              │               │              │
│       ▼              ▼               ▼              │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐    │
│  │ OHLCV    │   │ Fee/     │   │ Sharpe, PF,  │    │
│  │ History  │   │ Slippage │   │ MaxDD, Win%  │    │
│  │ (SQLite) │   │ Model    │   │              │    │
│  └──────────┘   └──────────┘   └──────────────┘    │
└─────────────────────────────────────────────────────┘
```

**Implementation:**
- Library: `vectorbt` (Python, fast vectorized backtesting)
- Fee model: Exchange-accurate (Binance 0.1% maker/taker)
- Slippage model: Configurable (zero, fixed, realistic with mean/std)
- Data source: SQLite historical OHLCV cache (90 days 1H, 252 days 1D)

**Python skeleton:**
```python
class BacktestEngine:
    """Fee-aware backtesting with walk-forward validation."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.fee_model = FeeModel(config.exchange_fees)
        self.slippage_model = SlippageModel(config.slippage_bps_mean,
                                             config.slippage_bps_std)

    def run(self, strategy: Strategy, data: pd.DataFrame,
            start: date, end: date) -> BacktestResult:
        """Run strategy over historical data."""
        signals = strategy.generate_signals(data.loc[start:end])
        fills = self._simulate_fills(signals, data)
        return self._calculate_metrics(fills, data)

    def walk_forward(self, strategy: Strategy, data: pd.DataFrame,
                     train_pct: float = 0.70,
                     val_pct: float = 0.15,
                     test_pct: float = 0.15) -> WalkForwardResult:
        """Walk-forward validation with train/val/test split."""
        n = len(data)
        train_end = int(n * train_pct)
        val_end = int(n * (train_pct + val_pct))

        # Train phase: optimize parameters
        train_data = data.iloc[:train_end]
        optimized_params = strategy.optimize(train_data)

        # Validation phase: confirm no overfitting
        val_data = data.iloc[train_end:val_end]
        val_result = self.run(strategy.with_params(optimized_params),
                              val_data, val_data.index[0], val_data.index[-1])

        # Test phase: final out-of-sample evaluation
        test_data = data.iloc[val_end:]
        test_result = self.run(strategy.with_params(optimized_params),
                               test_data, test_data.index[0], test_data.index[-1])

        return WalkForwardResult(
            train_result=self.run(strategy, train_data,
                                  train_data.index[0], train_data.index[-1]),
            val_result=val_result,
            test_result=test_result,
            is_valid=val_result.sharpe > 0.5 and test_result.sharpe > 0.3,
        )
```

**Who owns it:** Strategy Geneticist agent (full architecture), Signal Agent (Day1 — manual backtesting)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Backtesting | Paper trading only | vectorbt engine |
| Walk-forward | Manual (run paper 2 weeks) | Automated train/val/test |
| Fee model | Exchange-accurate | Exchange-accurate + slippage |
| Data | 90 days 1H | 1 year+ 1H, tick data |

---

### Gap C2: Walk-Forward Validation

**What was missing:** No systematic out-of-sample testing before deploying a strategy to live trading.

**How it's now implemented:**

```
WALK-FORWARD VALIDATION PIPELINE
═════════════════════════════════

┌──────────────────────────────────────────────────────────────┐
│  Historical Data (e.g., 365 days)                            │
│                                                              │
│  ┌──────────────┬──────────────┬──────────────┐             │
│  │   TRAIN      │  VALIDATION  │    TEST      │             │
│  │   (70%)      │   (15%)      │   (15%)      │             │
│  │              │              │              │             │
│  │ Optimize     │ Confirm no   │ Final        │             │
│  │ parameters   │ overfitting  │ evaluation   │             │
│  └──────────────┴──────────────┴──────────────┘             │
│                                                              │
│  VALIDATION GATES:                                           │
│  ✓ Val Sharpe > 0.5                                         │
│  ✓ Test Sharpe > 0.3                                        │
│  ✓ Test win rate > 45%                                      │
│  ✓ Test max drawdown < 15%                                  │
│  ✓ No parameter sensitivity > 50% (robustness check)        │
│                                                              │
│  IF ALL PASS → Strategy approved for paper trading           │
│  IF ANY FAIL → Strategy rejected, back to research           │
└──────────────────────────────────────────────────────────────┘
```

**Walk-forward rolling window (production):**
```
Rolling Walk-Forward (monthly):
─────────────────────────────
Month 1: Train [Day 1-21], Val [Day 22-27], Test [Day 28-30]
Month 2: Train [Day 31-51], Val [Day 52-57], Test [Day 58-60]
...

Each month:
1. Re-optimize on most recent training window
2. Validate on fresh out-of-sample data
3. If validation fails → pause strategy, alert human
4. If passes → continue live deployment
```

**Statistical significance requirement:**
```python
def validate_significance(trades: list, min_confidence: float = 0.95) -> bool:
    """Require statistical significance before deploying strategy."""
    if len(trades) < 30:
        return False  # Insufficient sample size

    returns = [t.pnl_pct for t in trades]
    t_stat, p_value = scipy.stats.ttest_1samp(returns, 0)
    return p_value < (1 - min_confidence)  # p < 0.05
```

**Who owns it:** Strategy Geneticist agent (automated), Signal Agent (Day1 — manual paper trading validation)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Method | Paper trading for 2+ weeks | Automated walk-forward engine |
| Sample size | 30+ paper trades | 100+ historical + paper |
| Statistical test | Win rate > 50% | t-test p < 0.05 |
| Frequency | Once (before live) | Monthly rolling revalidation |

---

### Gap C3: Backup/Recovery

**What was missing:** No disaster recovery. SQLite corruption = total loss of trade history and lessons.

**How it's now implemented:**

```
BACKUP & RECOVERY ARCHITECTURE
══════════════════════════════

┌─────────────────────────────────────────────────────┐
│                  BACKUP TIERS                        │
│                                                      │
│  Tier 1: HOT (every 15 min)                         │
│  ├─ SQLite WAL checkpoint                           │
│  ├─ Copy tsar.db → data/backups/hourly/             │
│  └─ Retention: 24 hours (96 copies)                 │
│                                                      │
│  Tier 2: WARM (daily at 00:00 UTC)                  │
│  ├─ Full tsar.db copy                               │
│  ├─ Redis RDB snapshot                              │
│  ├─ Config files backup                             │
│  └─ Retention: 30 days                              │
│                                                      │
│  Tier 3: COLD (weekly)                              │
│  ├─ Compressed tarball of entire data/ dir          │
│  ├─ Upload to cloud storage (S3/R2 compatible)      │
│  └─ Retention: 1 year                               │
│                                                      │
│  Recovery:                                           │
│  ├─ Automatic: If tsar.db fails integrity check     │
│  │   → restore from most recent Tier 1 backup       │
│  ├─ Manual: Restore from Tier 2 or Tier 3           │
│  └─ Verification: Restore to temp DB, verify schema │
└─────────────────────────────────────────────────────┘
```

**Implementation:**
```python
class BackupManager:
    """Automated backup with tiered retention."""

    def __init__(self, db_path: str, backup_dir: str):
        self.db_path = db_path
        self.backup_dir = backup_dir

    def hot_backup(self):
        """Tier 1: Copy SQLite file every 15 minutes."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dest = f"{self.backup_dir}/hourly/tsar_{timestamp}.db"
        # Use SQLite backup API (safe during writes)
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(dest)
        src.backup(dst)
        dst.close()
        src.close()
        self._prune_old(self.backup_dir + "/hourly", keep=96)

    def warm_backup(self):
        """Tier 2: Full backup daily."""
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        dest = f"{self.backup_dir}/daily/tsar_{timestamp}.db"
        shutil.copy2(self.db_path, dest)
        self._prune_old(self.backup_dir + "/daily", keep=30)

    def cold_backup(self):
        """Tier 3: Compressed weekly backup for off-site storage."""
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        dest = f"{self.backup_dir}/weekly/tsar_{timestamp}.tar.gz"
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(self.db_path, arcname="tsar.db")
        self._prune_old(self.backup_dir + "/weekly", keep=52)
        # Upload to cloud storage (S3/R2)
        self._upload_to_cloud(dest)

    def verify_backup(self, backup_path: str) -> bool:
        """Verify backup integrity by restoring to temp DB."""
        temp_path = backup_path + ".verify"
        try:
            shutil.copy2(backup_path, temp_path)
            conn = sqlite3.connect(temp_path)
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            return result[0] == "ok"
        finally:
            os.unlink(temp_path)
```

**Who owns it:** Orchestrator (cron job), Operations layer

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Hot backup | Every 15 min (cron) | Every 15 min (cron) |
| Warm backup | Daily (cron) | Daily (cron) |
| Cold backup | Weekly manual copy | Weekly auto-upload to S3 |
| Recovery | Manual restore | Auto-restore on integrity failure |
| Verification | Manual | Weekly auto-verify |

---

### Gap C4: Strategy Portfolio + Allocation

**What was missing:** No mechanism for running multiple strategies simultaneously or allocating capital between them.

**How it's now implemented:**

```
STRATEGY PORTFOLIO ARCHITECTURE
═══════════════════════════════

┌─────────────────────────────────────────────────────────┐
│              STRATEGY ALLOCATOR                          │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ Mean        │  │ Momentum    │  │ Breakout    │    │
│  │ Reversion   │  │ Trend       │  │             │    │
│  │ (40%)       │  │ (35%)       │  │ (25%)       │    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
│         │                │                │            │
│         ▼                ▼                ▼            │
│  ┌─────────────────────────────────────────────────┐    │
│  │         SHARED RISK BUDGET                      │    │
│  │  Total portfolio risk: 6% of capital            │    │
│  │  Per-strategy allocation: risk-parity weighted  │    │
│  │  Rebalance: weekly on rolling 30-day Sharpe     │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Allocation methods:**
1. **Risk Parity** (default): Each strategy contributes equal risk
2. **Kelly-Based**: Allocate proportional to edge (half-Kelly per strategy)
3. **Inverse Volatility**: Lower-vol strategies get more capital

**Implementation:**
```python
class StrategyAllocator:
    """Allocates capital across multiple strategies."""

    def __init__(self, method: str = "risk_parity"):
        self.method = method

    def allocate(self, strategies: list[Strategy],
                 total_capital: float) -> dict[str, float]:
        """Calculate capital allocation per strategy."""
        if self.method == "risk_parity":
            return self._risk_parity(strategies, total_capital)
        elif self.method == "kelly":
            return self._kelly_allocate(strategies, total_capital)
        elif self.method == "inverse_vol":
            return self._inverse_volatility(strategies, total_capital)

    def _risk_parity(self, strategies, total_capital):
        """Each strategy contributes equal portfolio risk."""
        vols = [s.rolling_volatility(30) for s in strategies]
        inv_vols = [1.0 / v if v > 0 else 0 for v in vols]
        total_inv = sum(inv_vols)
        return {s.name: total_capital * (iv / total_inv)
                for s, iv in zip(strategies, inv_vols)}

    def rebalance(self, strategies: list[Strategy],
                  current_allocations: dict[str, float]) -> dict[str, float]:
        """Weekly rebalance based on rolling performance."""
        target = self.allocate(strategies, sum(current_allocations.values()))
        drift = {s: abs(target[s] - current_allocations[s]) / current_allocations[s]
                 for s in target}
        # Only rebalance if drift > 10%
        if any(d > 0.10 for d in drift.values()):
            return target
        return current_allocations  # No rebalance needed
```

**Database schema addition:**
```sql
CREATE TABLE strategy_allocations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT NOT NULL,
    allocated_capital REAL NOT NULL,
    allocation_pct  REAL NOT NULL,
    method          TEXT NOT NULL,  -- 'risk_parity', 'kelly', 'inverse_vol'
    rebalance_date  TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE strategy_correlations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_a      TEXT NOT NULL,
    strategy_b      TEXT NOT NULL,
    correlation     REAL NOT NULL,
    window_days     INTEGER NOT NULL,
    calculated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

**Who owns it:** Strategy Geneticist agent

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Strategies | 1 (mean reversion) | 3-5 uncorrelated |
| Allocation | 100% to single strategy | Risk-parity or Kelly |
| Rebalancing | N/A | Weekly on rolling Sharpe |
| Correlation tracking | N/A | Strategy-level correlation matrix |

---

### Gap C5: VaR / Stress Testing

**What was missing:** No portfolio-level risk measurement. Trade-level risk is excellent, but no aggregate risk metrics.

**How it's now implemented:**

```
PORTFOLIO RISK MEASUREMENT
══════════════════════════

┌─────────────────────────────────────────────────────────┐
│              VaR & STRESS TESTING                        │
│                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────┐  │
│  │ Historical   │   │ Parametric   │   │ Stress     │  │
│  │ VaR (95/99%) │   │ VaR          │   │ Scenarios  │  │
│  └──────┬───────┘   └──────┬───────┘   └─────┬──────┘  │
│         │                  │                 │          │
│         ▼                  ▼                 ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │         PORTFOLIO RISK DASHBOARD                 │    │
│  │                                                  │    │
│  │  VaR 95%: -$0.45 (4.5% of capital)              │    │
│  │  VaR 99%: -$0.80 (8.0% of capital)              │    │
│  │  Max stress loss: -$3.50 (LUNA scenario)        │    │
│  │  Portfolio beta: 0.85                            │    │
│  │  Concentration risk: LOW                         │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Stress test scenarios:**
| Scenario | Description | Expected Impact |
|----------|-------------|-----------------|
| Flash Crash | -30% BTC in 1 hour | All longs hit stops |
| Exchange Halt | Exchange offline 24h | Can't close positions |
| LUNA Collapse | -95% in 3 days | Correlated altcoin dump |
| FOMC Shock | +3% rate hike | USD spike, crypto dump |
| Liquidity Crisis | Order book depth drops 90% | Massive slippage |

**Implementation:**
```python
class PortfolioRiskManager:
    """VaR and stress testing for portfolio-level risk."""

    def calculate_var(self, positions: list, confidence: float = 0.95,
                      horizon_days: int = 1) -> VaRResult:
        """Historical simulation VaR."""
        # Get historical returns for each position
        returns_matrix = self._get_returns_matrix(positions, lookback=252)
        # Calculate portfolio returns for each historical scenario
        portfolio_returns = returns_matrix @ self._position_weights(positions)
        # Sort and find percentile
        var_pct = np.percentile(portfolio_returns, (1 - confidence) * 100)
        var_dollar = var_pct * self._portfolio_value(positions)
        # Scale to horizon
        var_dollar *= np.sqrt(horizon_days)
        return VaRResult(
            var_pct=var_pct,
            var_dollar=var_dollar,
            confidence=confidence,
            horizon_days=horizon_days,
        )

    def stress_test(self, positions: list,
                    scenarios: list[StressScenario]) -> list[StressResult]:
        """Run portfolio through stress scenarios."""
        results = []
        for scenario in scenarios:
            # Apply scenario shocks to each position
            losses = []
            for pos in positions:
                shock = scenario.shocks.get(pos.asset_class, scenario.default_shock)
                loss = pos.notional * shock
                # Account for stop-loss
                if pos.stop_loss:
                    max_loss = pos.notional * (pos.entry_price - pos.stop_loss) / pos.entry_price
                    loss = max(loss, -max_loss)  # Stop-loss limits loss
                losses.append(loss)
            results.append(StressResult(
                scenario=scenario.name,
                total_loss=sum(losses),
                loss_pct=sum(losses) / self._portfolio_value(positions),
            ))
        return results
```

**Who owns it:** Risk Guardian agent (periodic check), Orchestrator (daily report)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| VaR | Position limits only | Historical + parametric VaR |
| Stress testing | Daily loss limit (-2%) | 5+ historical scenarios |
| Beta tracking | None | Rolling 30-day beta |
| Reporting | Telegram alert | Grafana dashboard + Telegram |

---

### Gap C6: Counterparty Risk Monitoring

**What was missing:** No exchange health monitoring. FTX taught the industry that exchange solvency is existential risk.

**How it's now implemented:**

```
COUNTERPARTY RISK MONITOR
═════════════════════════

┌─────────────────────────────────────────────────────────┐
│              EXCHANGE HEALTH MONITORING                   │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ API Health   │  │ Withdrawal   │  │ Proof-of-    │  │
│  │ Monitor      │  │ Processing   │  │ Reserves     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │          │
│         ▼                 ▼                 ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │         EXCHANGE RISK SCORE                      │    │
│  │                                                  │    │
│  │  Binance:  8.5/10  (GREEN)                      │    │
│  │  ├─ API uptime: 99.9%                           │    │
│  │  ├─ Withdrawal time: < 10 min                   │    │
│  │  └─ PoR verified: Yes                           │    │
│  │                                                  │    │
│  │  THRESHOLDS:                                     │    │
│  │  Score > 7.0: GREEN  → Normal trading           │    │
│  │  Score 4.0-7.0: YELLOW → Reduce exposure 50%    │    │
│  │  Score < 4.0: RED → Withdraw all, halt trading  │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Monitoring checks:**
| Check | Frequency | Alert Threshold |
|-------|-----------|-----------------|
| API response time | Every 5 min | > 2 seconds |
| API error rate | Every 5 min | > 5% of requests |
| Withdrawal processing | Every hour | > 30 minutes |
| Order fill rate | Per trade | < 95% fill rate |
| Proof-of-reserves | Daily | Unaudited or declining |

**Implementation:**
```python
class CounterpartyRiskMonitor:
    """Monitors exchange health and solvency indicators."""

    def __init__(self, exchanges: list[str]):
        self.exchanges = exchanges
        self.health_history: dict[str, deque] = {e: deque(maxlen=1000) for e in exchanges}

    async def check_exchange_health(self, exchange: str) -> ExchangeHealth:
        """Run all counterparty risk checks for an exchange."""
        checks = {}

        # API responsiveness
        start = time.time()
        try:
            await self._ping_exchange(exchange)
            checks['api_latency_ms'] = (time.time() - start) * 1000
            checks['api_healthy'] = True
        except Exception:
            checks['api_healthy'] = False
            checks['api_latency_ms'] = float('inf')

        # Withdrawal test (small amount)
        checks['withdrawal_healthy'] = await self._check_withdrawals(exchange)

        # Order book depth (liquidity proxy)
        depth = await self._check_orderbook_depth(exchange)
        checks['liquidity_score'] = depth

        # Calculate composite score
        score = self._calculate_score(checks)

        return ExchangeHealth(
            exchange=exchange,
            score=score,
            checks=checks,
            timestamp=datetime.utcnow(),
        )

    def _calculate_score(self, checks: dict) -> float:
        """Composite exchange health score (0-10)."""
        score = 10.0
        if not checks.get('api_healthy'):
            score -= 5.0
        if checks.get('api_latency_ms', 0) > 2000:
            score -= 2.0
        if not checks.get('withdrawal_healthy'):
            score -= 3.0
        if checks.get('liquidity_score', 1.0) < 0.5:
            score -= 2.0
        return max(0, score)
```

**Who owns it:** Risk Guardian agent (periodic check), Orchestrator (alert routing)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Exchange | 1 (Binance testnet) | 1-2 exchanges |
| Monitoring | None | API health + withdrawal checks |
| Diversification | Single exchange | Multi-exchange at scale |
| Alerting | None | Telegram + auto-reduce exposure |

---

### Gap C7: Data Quality Pipeline

**What was missing:** No validation of incoming market data. Bad data in = bad decisions out.

**How it's now implemented:**

```
DATA QUALITY PIPELINE
═════════════════════

Raw Data ──▶ Validation ──▶ Cleaning ──▶ Storage
   │             │             │           │
   │     ┌───────┴───────┐    │           │
   │     │ GAP DETECTION │    │           │
   │     │ ANOMALY DETECT│    │           │
   │     │ SCHEMA VALID  │    │           │
   │     └───────────────┘    │           │
   │                          │           │
   ▼                          ▼           ▼
Rejected                   Cleaned     Cached
(alert human)              data        in Redis
```

**Quality checks:**
| Check | Description | Action on Failure |
|-------|-------------|-------------------|
| Gap detection | Missing candles in time series | Log gap, fetch missing data |
| Price spike | > 5% move in single candle | Flag suspicious, don't auto-clean |
| Volume anomaly | > 10x average volume | Flag for review |
| Timestamp validation | Candles out of order | Reject and re-fetch |
| OHLC integrity | High < Low, Close outside H/L | Reject candle |
| Stale data | Latest candle > 2x expected age | Alert, re-fetch |

**Implementation:**
```python
class DataQualityPipeline:
    """Validates and cleans incoming market data."""

    def validate_ohlcv(self, df: pd.DataFrame, symbol: str,
                       timeframe: str) -> ValidationResult:
        """Run all quality checks on OHLCV data."""
        issues = []

        # Check 1: OHLC integrity
        bad_ohlc = (df['high'] < df['low']) | \
                   (df['close'] > df['high']) | \
                   (df['close'] < df['low'])
        if bad_ohlc.any():
            issues.append(QualityIssue("OHLC_INTEGRITY", bad_ohlc.sum()))

        # Check 2: Gap detection
        expected_interval = self._timeframe_to_seconds(timeframe)
        time_diffs = df['timestamp'].diff().dt.total_seconds()
        gaps = time_diffs[time_diffs > expected_interval * 1.5]
        if len(gaps) > 0:
            issues.append(QualityIssue("MISSING_CANDLES", len(gaps)))

        # Check 3: Price spike detection
        returns = df['close'].pct_change().abs()
        spikes = returns[returns > 0.05]  # >5% in one candle
        if len(spikes) > 0:
            issues.append(QualityIssue("PRICE_SPIKE", len(spikes)))

        # Check 4: Volume anomaly
        avg_volume = df['volume'].rolling(20).mean()
        volume_ratio = df['volume'] / avg_volume
        anomalies = volume_ratio[volume_ratio > 10]
        if len(anomalies) > 0:
            issues.append(QualityIssue("VOLUME_ANOMALY", len(anomalies)))

        # Check 5: Stale data
        latest = df['timestamp'].max()
        expected_latest = datetime.utcnow() - timedelta(seconds=expected_interval * 2)
        if latest < expected_latest:
            issues.append(QualityIssue("STALE_DATA", age_seconds=
                                       (datetime.utcnow() - latest).total_seconds()))

        return ValidationResult(
            is_valid=len([i for i in issues if i.severity == "CRITICAL"]) == 0,
            issues=issues,
            clean_data=self._clean(df, issues) if issues else df,
        )
```

**Who owns it:** Market Cartographer agent (data ingestion), Signal Agent (Day1 — inline validation)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Validation | Basic (check for None) | Full pipeline (6 checks) |
| Gap detection | None | Automatic with re-fetch |
| Spike detection | None | Flag + alert |
| Cleaning | None | Auto-clean + flag |

---

### Gap C8: Strategy Retirement Gates

**What was missing:** Strategies run forever regardless of performance degradation.

**How it's now implemented:**

```
STRATEGY RETIREMENT GATES
═════════════════════════

┌─────────────────────────────────────────────────────────┐
│              RETIREMENT EVALUATION                       │
│                                                         │
│  Gate 1: Rolling Sharpe (30-day)                        │
│  ├─ Sharpe < 0.5 for 30 days → RETIRE                  │
│  ├─ Sharpe 0.5-1.0 → WARNING (alert human)             │
│  └─ Sharpe > 1.0 → HEALTHY                             │
│                                                         │
│  Gate 2: Drawdown Check                                 │
│  ├─ Drawdown > 15% from strategy HWM → PAUSE           │
│  ├─ Drawdown > 20% → RETIRE                             │
│  └─ Drawdown < 10% → HEALTHY                           │
│                                                         │
│  Gate 3: Win Rate Decay                                 │
│  ├─ Win rate < 40% over 50 trades → RETIRE             │
│  ├─ Win rate declining > 10% from baseline → WARNING    │
│  └─ Win rate stable or improving → HEALTHY              │
│                                                         │
│  Gate 4: Regime Fitness                                  │
│  ├─ Strategy underperforming in current regime → PAUSE  │
│  └─ Strategy aligned with regime → HEALTHY              │
│                                                         │
│  ACTIONS:                                               │
│  ├─ WARNING: Telegram alert, log to strategy_performance│
│  ├─ PAUSE: Stop new signals, keep existing positions    │
│  ├─ RETIRE: Stop all, close positions, move to archive  │
│  └─ REVIEW: Flag for human decision                     │
└─────────────────────────────────────────────────────────┘
```

**Implementation:**
```python
class StrategyRetirementGate:
    """Evaluates strategy health and triggers retirement."""

    # Retirement thresholds
    SHARPE_MIN = 0.5
    SHARPE_WINDOW_DAYS = 30
    DRAWDOWN_PAUSE_PCT = 0.15
    DRAWDOWN_RETIRE_PCT = 0.20
    WIN_RATE_MIN = 0.40
    WIN_RATE_TRADE_MIN = 50

    def evaluate(self, strategy: Strategy) -> RetirementDecision:
        """Run all retirement gates."""
        checks = []

        # Gate 1: Rolling Sharpe
        sharpe = strategy.rolling_sharpe(days=self.SHARPE_WINDOW_DAYS)
        if sharpe < self.SHARPE_MIN:
            checks.append(RetirementCheck("SHARPE", sharpe, "RETIRE"))
        elif sharpe < 1.0:
            checks.append(RetirementCheck("SHARPE", sharpe, "WARNING"))

        # Gate 2: Drawdown
        dd = strategy.current_drawdown()
        if dd > self.DRAWDOWN_RETIRE_PCT:
            checks.append(RetirementCheck("DRAWDOWN", dd, "RETIRE"))
        elif dd > self.DRAWDOWN_PAUSE_PCT:
            checks.append(RetirementCheck("DRAWDOWN", dd, "PAUSE"))

        # Gate 3: Win rate decay
        if strategy.total_trades >= self.WIN_RATE_TRADE_MIN:
            recent_wr = strategy.win_rate_last_n(50)
            if recent_wr < self.WIN_RATE_MIN:
                checks.append(RetirementCheck("WIN_RATE", recent_wr, "RETIRE"))

        # Gate 4: Regime fitness
        current_regime = get_current_regime()
        regime_perf = strategy.performance_in_regime(current_regime)
        if regime_perf.sharpe < 0:
            checks.append(RetirementCheck("REGIME_FIT", regime_perf.sharpe, "PAUSE"))

        # Determine worst action
        action_priority = {"RETIRE": 3, "PAUSE": 2, "WARNING": 1, "HEALTHY": 0}
        worst = max(checks, key=lambda c: action_priority.get(c.action, 0))

        return RetirementDecision(
            strategy=strategy.name,
            action=worst.action if checks else "HEALTHY",
            checks=checks,
        )
```

**Who owns it:** Strategy Geneticist agent

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Monitoring | Daily report (manual) | Automated every 4 hours |
| Retirement | Manual /set strategy retired | Auto-retirement gates |
| Reinstatement | Manual | Auto-reinstate if conditions recover |
| Alerting | Telegram on retirement | Telegram + auto-close positions |

---

### Gap C9: Immutable Audit Log

**What was missing:** SQLite is mutable. Any process with DB access can alter trade history.

**How it's now implemented:**

```
IMMUTABLE AUDIT LOG
═══════════════════

┌─────────────────────────────────────────────────────────┐
│              TWO-LAYER AUDIT TRAIL                       │
│                                                         │
│  Layer 1: SQLite (mutable, queryable)                   │
│  ├─ trades_audit_log table                              │
│  ├─ Fast queries for dashboards                        │
│  └─ Can be modified (weakness)                         │
│                                                         │
│  Layer 2: Append-Only JSONL File (immutable)            │
│  ├─ data/audit/audit_YYYY-MM-DD.jsonl                  │
│  ├─ Each record: SHA-256 hash of previous record       │
│  ├─ Chain of custody (blockchain-lite)                 │
│  └─ Cannot modify without breaking hash chain          │
│                                                         │
│  Layer 3: Remote Copy (optional, Level 3+)              │
│  ├─ Stream to external logging service                 │
│  ├─ S3 bucket with versioning + object lock            │
│  └─ True immutability (can't delete from S3)           │
└─────────────────────────────────────────────────────────┘
```

**Implementation:**
```python
class ImmutableAuditLog:
    """Append-only audit log with hash chain integrity."""

    def __init__(self, log_dir: str = "data/audit"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.current_hash = self._load_last_hash()

    def log(self, event_type: str, data: dict, agent: str):
        """Append immutable audit record."""
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "agent": agent,
            "data": data,
            "previous_hash": self.current_hash,
            "sequence": self._next_sequence(),
        }
        # Calculate hash of this record (chain link)
        record_bytes = json.dumps(record, sort_keys=True).encode()
        record["hash"] = hashlib.sha256(record_bytes).hexdigest()
        self.current_hash = record["hash"]

        # Append to daily JSONL file
        log_file = f"{self.log_dir}/audit_{date.today().isoformat()}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    def verify_chain(self, log_file: str) -> bool:
        """Verify hash chain integrity."""
        previous_hash = None
        with open(log_file) as f:
            for line in f:
                record = json.loads(line)
                if previous_hash and record["previous_hash"] != previous_hash:
                    return False  # Chain broken
                # Verify hash
                check_record = {k: v for k, v in record.items() if k != "hash"}
                check_bytes = json.dumps(check_record, sort_keys=True).encode()
                expected_hash = hashlib.sha256(check_bytes).hexdigest()
                if record["hash"] != expected_hash:
                    return False  # Record tampered
                previous_hash = record["hash"]
        return True
```

**Audit event types:**
| Event | Data Captured |
|-------|--------------|
| TRADE_OPEN | Signal, risk checks, position details |
| TRADE_CLOSE | Exit reason, P&L, duration |
| RISK_DECISION | Check results, approval/veto reason |
| STRATEGY_MUTATION | Parameter changes, rationale |
| MODE_CHANGE | Paper→Live, Live→Paper, approvals |
| KILL_SWITCH | Trigger reason, positions closed |
| SYSTEM_EVENT | Start, stop, error, recovery |

**Who owns it:** All agents (write), Orchestrator (verification)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Logging | SQLite only (mutable) | SQLite + JSONL hash chain |
| Integrity | None | SHA-256 chain verification |
| Remote copy | None | S3 with object lock |
| Verification | None | Daily chain verification cron |

---

### Gap C10: Sentiment Analysis

**What was missing:** No sentiment input to any trading decision. Signal Scout uses only technical indicators.

**How it's now implemented:**

```
SENTIMENT ANALYSIS PIPELINE
═══════════════════════════

┌─────────────────────────────────────────────────────────┐
│              SENTIMENT DATA SOURCES                      │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ CryptoPanic  │  │ Fear & Greed │  │ Social Media │  │
│  │ News API     │  │ Index        │  │ (Twitter/X)  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │          │
│         ▼                 ▼                 ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │         SENTIMENT SCORER (Ollama LLM)           │    │
│  │                                                  │    │
│  │  News headlines → sentiment score (-1 to +1)    │    │
│  │  Fear/Greed → normalized score                  │    │
│  │  Social → volume + sentiment                    │    │
│  │                                                  │    │
│  │  Composite: weighted average                    │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Signal Scout: sentiment_score added as         │    │
│  │  weighted factor (15% of total signal score)    │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Data sources:**
| Source | API | Cost | Refresh |
|--------|-----|------|---------|
| CryptoPanic | Free tier (100 req/day) | $0 | Every 5 min |
| Fear & Greed | Alternative.me | $0 | Every 15 min |
| News sentiment | Ollama LLM scoring | $0 (local) | On new headlines |

**Implementation:**
```python
class SentimentAnalyzer:
    """Multi-source sentiment scoring for crypto assets."""

    def __init__(self, ollama_client):
        self.ollama = ollama_client
        self.fear_greed_cache = None
        self.news_cache = {}

    async def get_composite_sentiment(self, symbol: str) -> SentimentScore:
        """Get weighted sentiment from all sources."""
        scores = {}

        # Source 1: Fear & Greed Index (weight: 30%)
        fg = await self._get_fear_greed()
        scores['fear_greed'] = SentimentComponent(
            score=(fg.value - 50) / 50,  # Normalize to -1..+1
            weight=0.30,
            source="alternative.me",
        )

        # Source 2: News sentiment (weight: 50%)
        news = await self._get_news_sentiment(symbol)
        scores['news'] = SentimentComponent(
            score=news,
            weight=0.50,
            source="cryptopanic",
        )

        # Source 3: Social sentiment (weight: 20%)
        social = await self._get_social_sentiment(symbol)
        scores['social'] = SentimentComponent(
            score=social,
            weight=0.20,
            source="social",
        )

        # Composite weighted score
        composite = sum(s.score * s.weight for s in scores.values())

        return SentimentScore(
            symbol=symbol,
            composite=composite,  # -1 (extreme fear) to +1 (extreme greed)
            components=scores,
            timestamp=datetime.utcnow(),
        )

    async def _get_news_sentiment(self, symbol: str) -> float:
        """Use local Ollama to score news headlines."""
        headlines = await self._fetch_cryptopanic(symbol)
        if not headlines:
            return 0.0  # Neutral

        prompt = f"""Score the sentiment of these crypto news headlines for {symbol}.
Return ONLY a number from -1 (extreme bearish) to +1 (extreme bullish).

Headlines:
{chr(10).join(f'- {h}' for h in headlines[:10])}

Score:"""

        response = await self.ollama.generate(prompt)
        try:
            return max(-1, min(1, float(response.strip())))
        except ValueError:
            return 0.0
```

**Who owns it:** Signal Agent (Day1 — inline sentiment check), Sentiment Agent (full architecture)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Sources | Fear & Greed only | Fear & Greed + News + Social |
| Scoring | Rule-based (index value) | LLM-powered headline analysis |
| Weight in signal | 10% | 15% |
| Agent | Inline in Signal Agent | Dedicated Sentiment Agent |

---

### Gap C11: Economic Calendar Integration

**What was missing:** Risk Architecture defines blackout rules for NFP/CPI/FOMC but has no data source.

**How it's now implemented:**

```
ECONOMIC CALENDAR INTEGRATION
═════════════════════════════

┌─────────────────────────────────────────────────────────┐
│              CALENDAR DATA PIPELINE                      │
│                                                         │
│  ┌──────────────┐                                       │
│  │ ForexFactory │──▶ Parse HTML ──▶ Redis Cache         │
│  │ Calendar     │    (daily)      (tsar:calendar:*)     │
│  └──────────────┘                    │                 │
│                                      ▼                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Risk Guardian: TimeBasedRiskRules              │    │
│  │                                                  │    │
│  │  NFP:     Block trades 30min before/after       │    │
│  │  CPI:     Block trades 30min before/after       │    │
│  │  FOMC:    Block trades 60min before/after       │    │
│  │  ECB:     Block trades 30min before/after       │    │
│  │  BOJ:     Block trades 30min before/after       │    │
│  │                                                  │    │
│  │  Also: Reduce position size 50% for 24h         │    │
│  │  around HIGH impact events                      │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Implementation:**
```python
class EconomicCalendar:
    """Fetches and caches economic calendar events."""

    HIGH_IMPACT_EVENTS = ["NFP", "CPI", "FOMC", "ECB", "BOJ", "GDP"]

    BLACKOUT_RULES = {
        "NFP": {"before_min": 30, "after_min": 30},
        "CPI": {"before_min": 30, "after_min": 30},
        "FOMC": {"before_min": 60, "after_min": 60},
        "ECB": {"before_min": 30, "after_min": 30},
        "BOJ": {"before_min": 30, "after_min": 30},
    }

    def __init__(self, redis_client):
        self.redis = redis_client
        self.cache_key = "tsar:calendar:events"

    async def refresh(self):
        """Fetch calendar from ForexFactory and cache in Redis."""
        events = await self._fetch_forexfactory()
        # Cache for 24 hours
        self.redis.setex(self.cache_key, 86400, json.dumps(events))
        return events

    def is_blackout(self, symbol: str) -> tuple[bool, str | None]:
        """Check if current time is in a blackout window."""
        events = self._get_cached_events()
        now = datetime.utcnow()

        for event in events:
            if event['impact'] != 'HIGH':
                continue
            if event['event_type'] not in self.BLACKOUT_RULES:
                continue

            rule = self.BLACKOUT_RULES[event['event_type']]
            start = event['datetime'] - timedelta(minutes=rule['before_min'])
            end = event['datetime'] + timedelta(minutes=rule['after_min'])

            if start <= now <= end:
                return True, f"{event['event_type']} blackout ({rule['before_min']}min before)"

        return False, None
```

**Who owns it:** Risk Guardian agent (already has TimeBasedRiskRules, just needs data feed)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Calendar data | Hardcoded FOMC dates | Live ForexFactory feed |
| Blackout enforcement | None | Automatic trade blocking |
| Position reduction | None | 50% reduction near events |
| Asset relevance | N/A (crypto only) | Critical for forex/gold |

---

### Gap C12: Multi-Asset Portfolio

**What was missing:** TSAR is crypto-only. Institutional trading spans crypto, forex, gold, equities.

**How it's now implemented:**

```
MULTI-ASSET PORTFOLIO ARCHITECTURE
══════════════════════════════════

┌─────────────────────────────────────────────────────────┐
│              ASSET CLASS SUPPORT                         │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   CRYPTO     │  │   FOREX      │  │   COMMODITY  │  │
│  │              │  │              │  │              │  │
│  │ BTC/USDT     │  │ EUR/USD      │  │ XAU/USD      │  │
│  │ ETH/USDT     │  │ GBP/USD      │  │ (Gold)       │  │
│  │ BNB/USDT     │  │ USD/JPY      │  │              │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │          │
│         ▼                 ▼                 ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │         UNIFIED PORTFOLIO MANAGER                │    │
│  │                                                  │    │
│  │  Cross-asset correlation matrix                  │    │
│  │  Asset allocation: risk-parity                   │    │
│  │  Rebalance triggers: drift > 10%                 │    │
│  │  Max single asset class: 40%                     │    │
│  │  Min diversification: 2 asset classes            │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Exchange support:**
| Asset Class | Exchange | API | Day1 | Full |
|-------------|----------|-----|------|------|
| Crypto | Binance | ccxt | ✅ | ✅ |
| Forex | OANDA | ccxt / REST | ❌ | ✅ |
| Gold | OANDA | ccxt / REST | ❌ | ✅ |
| Equities | Alpaca | ccxt / REST | ❌ | v3 |

**Implementation:**
```python
class MultiAssetPortfolioManager:
    """Manages positions across multiple asset classes."""

    MAX_SINGLE_ASSET_CLASS_PCT = 0.40  # 40% max in any single asset class
    MIN_ASSET_CLASSES = 2

    def __init__(self, exchanges: dict[str, Exchange]):
        self.exchanges = exchanges  # {'crypto': binance, 'forex': oanda}
        self.positions: dict[str, Position] = {}

    def get_portfolio_summary(self) -> PortfolioSummary:
        """Unified view across all asset classes."""
        positions = []
        for asset_class, exchange in self.exchanges.items():
            positions.extend(self._get_positions(exchange, asset_class))

        return PortfolioSummary(
            total_value=sum(p.value_usd for p in positions),
            by_asset_class=self._group_by_class(positions),
            correlation_matrix=self._calculate_correlations(positions),
            diversification_score=self._diversification_score(positions),
        )

    def check_allocation(self, new_trade: TradeProposal) -> bool:
        """Check if new trade violates asset class concentration."""
        current = self.get_portfolio_summary()
        class_value = current.by_asset_class.get(new_trade.asset_class, 0)
        new_class_value = class_value + new_trade.notional
        new_total = current.total_value + new_trade.notional

        if new_class_value / new_total > self.MAX_SINGLE_ASSET_CLASS_PCT:
            return False  # Would exceed concentration limit
        return True
```

**Who owns it:** Portfolio Manager (new component), Market Cartographer (cross-asset analysis)

**Day1 vs Full:**
| Aspect | Day1 | Full Architecture |
|--------|------|-------------------|
| Asset classes | Crypto only | Crypto + Forex + Gold |
| Exchanges | Binance testnet | Binance + OANDA |
| Allocation | Single asset | Risk-parity across classes |
| Correlation | None | Cross-asset correlation matrix |

---

## 2. Important Gap Resolutions

### Gap I1: Cross-Asset Correlation Monitoring

**What was missing:** No live cross-asset correlation feeds (DXY, bonds, gold, equities).

**Resolution:** Market Cartographer agent provides real-time correlation matrix.
- Data sources: Yahoo Finance (equities, bonds, DXY), CoinGecko (crypto), OANDA (forex)
- Correlation window: Rolling 30-day
- Alert threshold: Correlation spike > 0.8 or breakdown < 0.3
- **Owner:** Market Cartographer agent
- **Day1:** Skip. **Level 2:** Add with live feeds.

### Gap I2: Seasonal Pattern Analysis

**What was missing:** No time-of-day, day-of-week, or monthly pattern awareness.

**Resolution:** Add seasonal scoring as a signal factor.
- Track performance by hour-of-day, day-of-week in `trade_records`
- Calculate seasonal edge: "BTC wins 65% of the time during US session"
- Weight in Signal Scout: 5% of total score
- **Owner:** Strategy Geneticist (analysis), Signal Scout (scoring)
- **Day1:** Skip. **Level 3:** Add.

### Gap I3: Performance Attribution

**What was missing:** No multi-dimensional P&L attribution (by strategy, asset, regime).

**Resolution:** Add attribution views to `tsar.db`.
```sql
CREATE VIEW pnl_by_strategy AS
SELECT strategy, COUNT(*) as trades, SUM(pnl) as total_pnl,
       AVG(pnl) as avg_pnl, SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)*1.0/COUNT(*) as win_rate
FROM trades WHERE status = 'CLOSED' GROUP BY strategy;

CREATE VIEW pnl_by_asset_class AS
SELECT asset_class, COUNT(*) as trades, SUM(pnl) as total_pnl
FROM trades WHERE status = 'CLOSED' GROUP BY asset_class;

CREATE VIEW pnl_by_regime AS
SELECT regime_at_entry, COUNT(*) as trades, SUM(pnl) as total_pnl
FROM trades WHERE status = 'CLOSED' GROUP BY regime_at_entry;
```
- **Owner:** Trade Philosopher agent
- **Day1:** Basic (strategy-level in daily report). **Level 2:** Full multi-dimensional.

### Gap I4: Real-Time Monitoring Dashboards

**What was missing:** No visual monitoring. Telegram alerts only.

**Resolution:** Prometheus metrics + Grafana dashboards.
- Metrics: trade_count, pnl, drawdown, open_positions, agent_health, latency
- Dashboards: Trading overview, Risk heatmap, Strategy comparison
- **Owner:** Operations layer
- **Day1:** Telegram only. **Level 2:** Add Grafana.

### Gap I5: Log Aggregation

**What was missing:** No centralized log storage. Logs scattered across files.

**Resolution:** Structured JSON logging + Loki/Promtail aggregation.
- Format: JSON with timestamp, level, agent, trace_id, message
- Storage: Local files (Day1), Loki (Level 2)
- Query: grep/jq (Day1), Grafana Explore (Level 2)
- **Owner:** All agents, Orchestrator
- **Day1:** File-based logging. **Level 2:** Add Loki.

### Gap I6: On-Chain Analytics

**What was missing:** No whale movement, exchange flow, or DeFi data.

**Resolution:** Integrate on-chain data as signal factor.
- Sources: Glassnode (free tier), CryptoQuant, Whale Alert
- Metrics: Exchange net flow, whale transactions, active addresses
- Weight in Signal Scout: 10% of total score
- **Owner:** Signal Agent (Day1), dedicated On-Chain Agent (Level 3)
- **Day1:** Skip. **Level 2:** Add exchange flow monitoring.

### Gap I7: Fund Flow Analysis

**What was missing:** No tracking of institutional money flow (ETF flows, fund allocations).

**Resolution:** Add fund flow data as macro context.
- Sources: CoinGlass (BTC ETF flows), FRED (fund flow data)
- Integration: Macro Agent incorporates into regime classification
- **Owner:** Macro Agent
- **Day1:** Skip. **Level 3:** Add.

### Gap I8: Trade Journal Automation

**What was missing:** No automated post-trade journal entry.

**Resolution:** Auto-generate journal entries from trade data + LLM analysis.
```python
class TradeJournal:
    def generate_entry(self, trade: Trade) -> JournalEntry:
        """Auto-generate journal entry from trade data."""
        prompt = f"""Analyze this trade and write a brief journal entry:
        Symbol: {trade.symbol}, Side: {trade.side}
        Entry: {trade.entry_price}, Exit: {trade.exit_price}
        P&L: {trade.pnl}, Duration: {trade.duration}
        Signal: {trade.signal_score}, Strategy: {trade.strategy}
        """
        analysis = self.llm.generate(prompt)
        return JournalEntry(trade_id=trade.id, analysis=analysis,
                           metrics=trade.to_dict())
```
- **Owner:** Trade Philosopher agent
- **Day1:** Manual notes field. **Level 2:** LLM-generated journal.

### Gap I9: Position Reconciliation

**What was missing:** No verification that internal position tracking matches exchange state.

**Resolution:** Periodic reconciliation check.
```python
class PositionReconciler:
    async def reconcile(self) -> ReconciliationResult:
        """Compare internal positions with exchange positions."""
        internal = self.db.get_open_positions()
        external = await self.exchange.get_positions()
        mismatches = self._find_mismatches(internal, external)
        if mismatches:
            logger.error(f"Position mismatch: {mismatches}")
            await self.alert(mismatches)
        return ReconciliationResult(matches=len(mismatches) == 0,
                                    mismatches=mismatches)
```
- **Owner:** Execution Tracker agent
- **Day1:** Skip. **Level 2:** Add hourly reconciliation.

---

## 3. Layer Coverage Improvements

### Before vs After Gap Resolution

| Layer | Before | After | Key Additions |
|-------|--------|-------|---------------|
| **Market Analysis** | 15% | 60% | Macro Agent, sentiment, on-chain, economic calendar |
| **Portfolio** | 15% | 50% | Multi-asset, allocation, rebalancing |
| **Operations** | 25% | 50% | Monitoring, backup, log aggregation, dashboards |
| **Compliance** | 30% | 50% | Immutable audit log, position reconciliation |
| **Strategy** | 30% | 65% | Backtesting, walk-forward, retirement, portfolio |
| **Risk** | 85% | 92% | VaR, stress testing, counterparty risk |
| **Data** | 35% | 55% | Data quality pipeline, on-chain, sentiment feeds |
| **Execution** | 40% | 45% | Position reconciliation |

### Full Architecture Agent Count: 4+ Agents

**Day1 (3 agents):**
```
Signal Agent → Risk Agent → Execution Agent
(includes macro awareness, sentiment, benchmark tracking)
```

**Level 2 (4 agents):**
```
Signal Agent ──▶ Risk Agent ──▶ Execution Agent
     ▲
Macro Agent (macro context, economic calendar, sentiment)
```

**Full Architecture (4+ agents):**
```
Macro Agent ─────────────────────────┐
  (economy, sentiment, on-chain)     │
                                     ▼
Signal Agent ──▶ Risk Agent ──▶ Execution Agent
  (technical     (VaR, stress   (orders,
   + sentiment    counterparty)  reconciliation)
   + on-chain)
```

---

## 4. Implementation Priority Matrix

### Phase 1: Day1 (Weeks 1-4)
| Gap | Resolution | Effort |
|-----|-----------|--------|
| Backup/recovery | Cron job copying tsar.db | 2 hours |
| Benchmark tracking | Compare vs buy-and-hold in daily report | 1 hour |
| Trade journal | Notes field in trade record | 30 min |
| Basic data validation | Check for None/empty in market data | 1 hour |

### Phase 2: Level 2 (Months 2-3)
| Gap | Resolution | Effort |
|-----|-----------|--------|
| Backtesting engine | vectorbt integration | 2-3 weeks |
| Walk-forward validation | Train/val/test pipeline | 1 week |
| Sentiment analysis | Fear & Greed + CryptoPanic | 1 week |
| Economic calendar | ForexFactory integration | 3-5 days |
| Strategy retirement | Rolling Sharpe + drawdown gates | 3-5 days |
| Immutable audit log | JSONL hash chain | 2-3 days |
| Data quality pipeline | OHLCV validation | 1 week |
| Counterparty risk | Exchange health monitoring | 1 week |
| Macro Agent | Dedicated agent for macro context | 1-2 weeks |
| Position reconciliation | Hourly exchange comparison | 2-3 days |

### Phase 3: Level 3 (Months 4-6)
| Gap | Resolution | Effort |
|-----|-----------|--------|
| VaR / stress testing | Historical simulation + scenarios | 1-2 weeks |
| Strategy portfolio + allocation | Risk-parity across strategies | 2 weeks |
| Multi-asset portfolio | Forex + gold support | 2-4 weeks |
| On-chain analytics | Glassnode + exchange flows | 1 week |
| Performance attribution | Multi-dimensional views | 3-5 days |
| Monitoring dashboards | Prometheus + Grafana | 1 week |
| Log aggregation | Structured logging + Loki | 3-5 days |

---

*Gap Resolution completed: 2026-07-24 02:09 GMT+8*
*21 gaps resolved — 12 critical + 9 important*
*All gaps have implementation specs, ownership, and Day1 vs Full differentiation*
