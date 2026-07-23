# TSAR Trading Super Agent — Operations Layer Specification

> Version: 1.0 | Date: 2026-07-24 | Status: Design Complete

---

## 1. Overview

The Operations Layer ensures TSAR runs reliably, observably, and recoverably. It covers backup/recovery, real-time monitoring, log aggregation, data quality pipelines, alerting, and deployment automation.

**Current Coverage:** ~25% → Target: 100% across 4 implementation levels.

---

## 2. Implementation Levels

| Level | Scope | Timeline |
|-------|-------|----------|
| **Day 1** | Basic logging + Telegram alerts | Week 1 |
| **Level 2** | Structured logging + basic monitoring | Weeks 2–4 |
| **Level 3** | Full monitoring + backup + deployment automation | Months 2–3 |
| **Level 4** | Data quality pipeline + advanced alerting | Months 4–6 |

---

## 3. Backup & Recovery

### 3.1 What to Back Up

| Component | Data | Priority |
|-----------|------|----------|
| **Portfolio State** | Positions, PnL, balances, open orders | 🔴 Critical |
| **Configuration** | Strategy params, API keys (encrypted), risk limits | 🔴 Critical |
| **Trade History** | All executed trades, fills, cancellations | 🟡 High |
| **Market Data Cache** | OHLCV, orderbook snapshots, funding rates | 🟡 High |
| **ML Models** | Trained model weights, feature scalers | 🟡 High |
| **Audit Logs** | Immutable trade/decision logs | 🔴 Critical |
| **System State** | Process state, active connections, heartbeat | 🟢 Medium |

### 3.2 Backup Frequency

```
┌─────────────────────────────────────────────────────────┐
│  Backup Schedule                                        │
├─────────────────────┬───────────┬───────────────────────┤
│ Data Type           │ Frequency │ Retention             │
├─────────────────────┼───────────┼───────────────────────┤
│ Portfolio State     │ 1 min     │ 30 days               │
│ Configuration       │ On change │ 90 days (versioned)   │
│ Trade History       │ Real-time │ 7 years (regulatory)  │
│ Market Data Cache   │ 1 hour    │ 365 days              │
│ ML Models           │ On train  │ Last 10 versions      │
│ Audit Logs          │ Real-time │ 7 years (immutable)   │
│ System State        │ 5 min     │ 7 days                │
│ Full System Snapshot│ Daily     │ 30 days               │
└─────────────────────┴───────────┴───────────────────────┘
```

### 3.3 Storage Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Backup Storage Tiers                      │
├──────────────┬───────────────────────────────────────────────┤
│   Hot (S3)   │ Last 7 days — instant recovery               │
│              │ Portfolio state, configs, recent trades        │
├──────────────┼───────────────────────────────────────────────┤
│   Warm (S3-IA)│ 7–90 days — recovery in < 1 hour            │
│              │ Trade history, market data, ML models          │
├──────────────┼───────────────────────────────────────────────┤
│   Cold (Glacier)│ 90 days – 7 years — compliance archive    │
│              │ Audit logs, trade records, regulatory data     │
└──────────────┴───────────────────────────────────────────────┘
```

### 3.4 Recovery Procedures

#### 3.4.1 Recovery Time Objectives (RTO) & Recovery Point Objectives (RPO)

| Scenario | RTO | RPO | Procedure |
|----------|-----|-----|-----------|
| Single service crash | < 30s | 0 (in-memory) | Auto-restart via systemd/supervisor |
| Portfolio state corruption | < 5 min | 1 min | Restore from latest S3 snapshot |
| Full system failure | < 30 min | 5 min | Rebuild from IaC + restore backups |
| Market data gap | < 1 hour | 1 hour | Replay from exchange API |
| ML model corruption | < 15 min | N/A | Rollback to previous model version |
| Region outage | < 2 hours | 5 min | Failover to secondary region |

#### 3.4.2 Recovery Runbooks

**Runbook R1: Portfolio State Recovery**
```
1. Stop all trading engines (kill switch)
2. Identify latest valid portfolio snapshot from S3
3. Verify snapshot integrity (checksum)
4. Cross-reference with exchange API for current positions
5. Reconcile snapshot vs exchange (flag discrepancies)
6. If match: restore from snapshot
7. If mismatch: restore from exchange state + alert operator
8. Resume trading in paper mode for 5 min
9. If stable: resume live trading
```

**Runbook R2: Full System Recovery**
```
1. Provision new instance (Terraform/Ansible)
2. Deploy base system (Docker Compose / K8s)
3. Restore configuration from encrypted S3
4. Restore portfolio state (see R1)
5. Restore trade history database
6. Verify all API connections
7. Run health checks (all endpoints)
8. Resume in paper mode → live
```

---

## 4. Real-Time Monitoring

### 4.1 Prometheus Metrics

#### 4.1.1 Trading Metrics

```yaml
# Trade execution
tsar_trades_total{exchange, symbol, side, strategy}     # Counter: total trades
tsar_trade_latency_seconds{exchange, symbol}             # Histogram: order-to-fill
tsar_trade_pnl_usd{exchange, symbol, strategy}           # Gauge: realized PnL
tsar_trade_slippage_bps{exchange, symbol}                # Histogram: expected vs actual

# Order management
tsar_orders_open{exchange, symbol}                       # Gauge: open orders
tsar_orders_rejected_total{exchange, reason}             # Counter: rejected orders
tsar_orderbook_depth{exchange, symbol, side}             # Gauge: book depth

# Portfolio
tsar_portfolio_value_usd{exchange}                       # Gauge: total value
tsar_portfolio_pnl_unrealized_usd{exchange, symbol}      # Gauge: unrealized PnL
tsar_portfolio_margin_ratio{exchange}                    # Gauge: margin usage
tsar_portfolio_drawdown_pct                              # Gauge: current drawdown
tsar_portfolio_max_drawdown_pct                          # Gauge: max drawdown
```

#### 4.1.2 Strategy Metrics

```yaml
tsar_strategy_signals_total{strategy, signal_type}       # Counter: signals generated
tsar_strategy_position_size{strategy, symbol}            # Gauge: position sizes
tsar_strategy_hit_rate{strategy}                         # Gauge: win rate
tsar_strategy_sharpe_ratio{strategy}                     # Gauge: rolling Sharpe
tsar_strategy_regime{strategy, regime}                   # Gauge: detected market regime
```

#### 4.1.3 System Metrics

```yaml
# Infrastructure
tsar_system_cpu_usage_pct                                # Gauge
tsar_system_memory_usage_pct                             # Gauge
tsar_system_disk_usage_pct                               # Gauge
tsar_system_network_bytes{direction}                     # Counter

# API connectivity
tsar_api_latency_seconds{exchange, endpoint}             # Histogram
tsar_api_errors_total{exchange, endpoint, error_type}    # Counter
tsar_api_rate_limit_remaining{exchange}                  # Gauge
tsar_api_connection_status{exchange}                     # Gauge: 1=connected

# Data pipeline
tsar_data_feed_lag_seconds{exchange, symbol}             # Gauge: feed delay
tsar_data_feed_gaps_total{exchange, symbol}              # Counter: detected gaps
tsar_data_pipeline_queue_depth                           # Gauge: pending messages
```

### 4.2 Grafana Dashboards

#### Dashboard 1: Trading Overview
```
┌─────────────────────────────────────────────────────────────────┐
│  TSAR Trading Overview                                          │
├─────────────────────────┬───────────────────────────────────────┤
│ Portfolio Value (USD)   │ Daily PnL Chart                       │
│ $1,234,567 ▲2.3%       │ [████████░░] +$28,400                 │
├─────────────────────────┼───────────────────────────────────────┤
│ Open Positions          │ Recent Trades (table)                 │
│ BTC-LONG: 0.5 @ $68k   │ BUY  0.1 BTC @ $68,100  -2s ago      │
│ ETH-SHORT: 2.0 @ $3.8k │ SELL 0.5 ETH @ $3,820   -15s ago     │
├─────────────────────────┼───────────────────────────────────────┤
│ Active Strategies       │ Signal Feed                           │
│ momentum: RUNNING       │ RSI(14) = 72 → SELL signal            │
│ mean_rev: RUNNING       │ MACD cross on ETH/USDT               │
│ arb: PAUSED             │                                       │
└─────────────────────────┴───────────────────────────────────────┘
```

#### Dashboard 2: System Health
```
┌─────────────────────────────────────────────────────────────────┐
│  System Health                                                  │
├─────────────────────────┬───────────────────────────────────────┤
│ API Latency (p99)       │ Error Rate (5m window)                │
│ Binance: 45ms           │ Binance: 0.01% ✓                      │
│ OKX: 62ms               │ OKX: 0.03% ✓                          │
│ Bybit: 38ms             │ Bybit: 0.00% ✓                        │
├─────────────────────────┼───────────────────────────────────────┤
│ CPU / Memory / Disk     │ Data Feed Health                      │
│ CPU: 34% ██░░░░░░░░     │ BTC/USDT: 12ms lag ✓                  │
│ Mem: 67% ██████░░░░     │ ETH/USDT: 18ms lag ✓                  │
│ Dsk: 23% ██░░░░░░░░     │ SOL/USDT: GAP DETECTED ⚠              │
├─────────────────────────┼───────────────────────────────────────┤
│ Uptime: 99.97%          │ Last Restart: 3d ago                  │
│ Processes: 12/12 UP     │ Queue Depth: 47 messages              │
└─────────────────────────┴───────────────────────────────────────┘
```

#### Dashboard 3: Risk Monitor
```
┌─────────────────────────────────────────────────────────────────┐
│  Risk Monitor                                                   │
├─────────────────────────┬───────────────────────────────────────┤
│ Max Drawdown            │ Margin Usage by Exchange              │
│ Current: -2.1%          │ Binance: 45% ████████░░               │
│ Limit: -10.0%           │ OKX: 32% ██████░░░░                   │
│ Status: OK ✓            │ Bybit: 28% █████░░░░░                 │
├─────────────────────────┼───────────────────────────────────────┤
│ Position Concentration  │ Correlation Matrix (heatmap)          │
│ BTC: 35% ███████░░░     │ [BTC ETH SOL AVAX ...]               │
│ ETH: 25% █████░░░░░     │ BTC  1.00  0.82  0.45  0.38          │
│ SOL: 15% ███░░░░░░░     │ ETH  0.82  1.00  0.51  0.42          │
│ Other: 25%              │ SOL  0.45  0.51  1.00  0.67          │
└─────────────────────────┴───────────────────────────────────────┘
```

### 4.3 Alert Rules (Prometheus AlertManager)

```yaml
groups:
  - name: tsar_trading_alerts
    rules:
      # CRITICAL — Immediate action required
      - alert: TradingHalted
        expr: tsar_trading_active == 0
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "Trading engine stopped"

      - alert: ExchangeDisconnected
        expr: tsar_api_connection_status == 0
        for: 30s
        labels: { severity: critical }
        annotations:
          summary: "Lost connection to {{ $labels.exchange }}"

      - alert: MarginCallWarning
        expr: tsar_portfolio_margin_ratio > 0.8
        for: 0s
        labels: { severity: critical }
        annotations:
          summary: "Margin ratio {{ $value }} on {{ $labels.exchange }}"

      - alert: MaxDrawdownBreach
        expr: tsar_portfolio_drawdown_pct > 10
        for: 0s
        labels: { severity: critical }
        annotations:
          summary: "Drawdown {{ $value }}% exceeds 10% limit"

      # WARNING — Investigate soon
      - alert: HighTradeLatency
        expr: histogram_quantile(0.99, tsar_trade_latency_seconds) > 5
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "p99 trade latency {{ $value }}s on {{ $labels.exchange }}"

      - alert: ElevatedErrorRate
        expr: rate(tsar_api_errors_total[5m]) > 0.05
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "Error rate {{ $value }} on {{ $labels.exchange }}"

      - alert: DataFeedGap
        expr: increase(tsar_data_feed_gaps_total[1h]) > 3
        for: 0s
        labels: { severity: warning }
        annotations:
          summary: "{{ $value }} data gaps on {{ $labels.symbol }}"

      - alert: HighSlippage
        expr: histogram_quantile(0.95, tsar_trade_slippage_bps) > 10
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "p95 slippage {{ $value }}bps on {{ $labels.symbol }}"

      # INFO — Track and review
      - alert: UnusualVolume
        expr: tsar_trade_volume_usd_1h > 3 * avg_over_time(tsar_trade_volume_usd_1h[7d])
        for: 0s
        labels: { severity: info }
        annotations:
          summary: "Unusual volume spike on {{ $labels.symbol }}"
```

---

## 5. Log Aggregation

### 5.1 Structured Logging Format

All TSAR components emit JSON structured logs:

```json
{
  "timestamp": "2026-07-24T02:13:00.123Z",
  "level": "INFO",
  "service": "trade-engine",
  "component": "order-manager",
  "trace_id": "abc-123-def-456",
  "span_id": "span-789",
  "event": "order_placed",
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "side": "buy",
  "quantity": 0.1,
  "price": 68100.50,
  "order_type": "limit",
  "strategy": "momentum_v2",
  "latency_ms": 45,
  "message": "Limit buy order placed on Binance"
}
```

### 5.2 Log Levels

| Level | Usage |
|-------|-------|
| `ERROR` | System failures, exchange errors, data corruption |
| `WARN` | Degraded performance, retry attempts, unusual conditions |
| `INFO` | Trade executions, strategy decisions, state changes |
| `DEBUG` | Detailed execution flow, API request/response bodies |
| `TRACE` | Full orderbook snapshots, raw market data (dev only) |

### 5.3 Log Storage Pipeline

```
┌─────────────┐    ┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│ TSAR Apps   │───▶│  Filebeat   │───▶│ Elasticsearch│───▶│   Kibana    │
│ (JSON logs) │    │  /Fluentd   │    │   Cluster    │    │  Dashboard  │
└─────────────┘    └─────────────┘    └──────────────┘    └─────────────┘
                                            │
                                            ▼
                                    ┌──────────────┐
                                    │  S3 Archive   │
                                    │  (long-term)  │
                                    └──────────────┘
```

### 5.4 Day 1 Implementation (Basic)

```python
# Simple file-based + Telegram alert logging
import logging
import json
from datetime import datetime

class TSARLogger:
    def __init__(self, service: str, telegram_bot=None):
        self.service = service
        self.telegram = telegram_bot
        self.logger = logging.getLogger(service)
        handler = logging.FileHandler(f'logs/{service}.jsonl')
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def log(self, level: str, event: str, **kwargs):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "service": self.service,
            "event": event,
            **kwargs
        }
        self.logger.log(getattr(logging, level), json.dumps(entry))

        # Telegram alerts for errors
        if level in ("ERROR", "CRITICAL") and self.telegram:
            self.telegram.send_message(
                f"🚨 [{level}] {self.service}: {event}\n"
                + "\n".join(f"  {k}: {v}" for k, v in kwargs.items())
            )
```

### 5.5 Retention Policy

```
Hot (Elasticsearch):   30 days  — full-text searchable
Warm (S3-IA):          90 days  — queryable via Athena
Cold (S3 Glacier):     7 years  — compliance archive
```

---

## 6. Data Quality Pipeline

### 6.1 Gap Detection

```python
class DataQualityPipeline:
    """Detects gaps, anomalies, and cleans market data."""

    def detect_gaps(self, series: pd.DataFrame, expected_interval: str) -> list[Gap]:
        """
        Compare timestamps against expected interval.
        Returns list of Gap objects with start, end, duration.
        """
        expected = pd.Timedelta(expected_interval)
        diffs = series.index.to_series().diff()
        gaps = diffs[diffs > expected * 1.5]  # 50% tolerance
        return [Gap(start=gaps.index[i] - expected, end=gaps.index[i],
                    duration=diffs.iloc[i]) for i in range(len(gaps))]

    def fill_gaps(self, series: pd.DataFrame, gaps: list[Gap],
                  method: str = "exchange_replay") -> pd.DataFrame:
        """
        Fill gaps by:
        1. exchange_replay — Re-fetch from exchange API (preferred)
        2. interpolation — Linear interpolation (last resort)
        3. forward_fill — Use last known value (avoid for prices)
        """
        if method == "exchange_replay":
            for gap in gaps:
                missing = self.exchange.fetch_ohlcv(
                    symbol=self.symbol,
                    since=gap.start,
                    limit=int(gap.duration / self.interval)
                )
                series = pd.concat([series, missing]).sort_index()
        return series
```

### 6.2 Anomaly Detection

```python
class AnomalyDetector:
    """Detects data anomalies in market data feeds."""

    def detect(self, series: pd.DataFrame) -> list[Anomaly]:
        anomalies = []

        # 1. Price spikes (>5σ from rolling mean)
        rolling_mean = series['close'].rolling(100).mean()
        rolling_std = series['close'].rolling(100).std()
        z_scores = (series['close'] - rolling_mean) / rolling_std
        spikes = series[abs(z_scores) > 5]
        for idx in spikes.index:
            anomalies.append(Anomaly(type='price_spike', index=idx,
                                      severity='high', z_score=z_scores[idx]))

        # 2. Volume anomalies (>10x median)
        median_vol = series['volume'].rolling(1000).median()
        vol_ratio = series['volume'] / median_vol
        vol_anomalies = series[vol_ratio > 10]
        for idx in vol_anomalies.index:
            anomalies.append(Anomaly(type='volume_spike', index=idx,
                                      severity='medium', ratio=vol_ratio[idx]))

        # 3. Stale data (same price for N consecutive bars)
        price_changes = series['close'].diff().abs()
        stale = series[price_changes == 0]
        stale_runs = (stale.groupby((stale.index.to_series().diff() > pd.Timedelta('1min')).cumsum()))
        for _, group in stale_runs:
            if len(group) > 10:  # >10 identical bars
                anomalies.append(Anomaly(type='stale_data', start=group.index[0],
                                          end=group.index[-1], severity='medium'))

        # 4. Negative/zero prices
        bad_prices = series[series['close'] <= 0]
        for idx in bad_prices.index:
            anomalies.append(Anomaly(type='invalid_price', index=idx, severity='critical'))

        return anomalies
```

### 6.3 Cleaning Pipeline

```
Raw Data → Validation → Gap Detection → Anomaly Detection → Cleaning → Store
                │              │               │                │
                ▼              ▼               ▼                ▼
          Schema check    Flag gaps      Flag anomalies    Fill/remove
          Type check      Log gaps       Alert if critical  Interpolate
          Range check     Auto-fill      Quarantine bad     Validate result
```

---

## 7. Alerting

### 7.1 Alert Routing

```
┌─────────────────────────────────────────────────────────────────┐
│                    Alert Routing Matrix                          │
├──────────┬──────────────────────────────────────────────────────┤
│ CRITICAL │ Telegram (immediate) + SMS (if no ack in 2min)      │
│          │ + PagerDuty (if no ack in 5min)                      │
│          │ Examples: Exchange disconnect, margin call, kill      │
├──────────┼──────────────────────────────────────────────────────┤
│ WARNING  │ Telegram (batched, every 5min)                       │
│          │ Examples: High latency, elevated errors, data gaps    │
├──────────┼──────────────────────────────────────────────────────┤
│ INFO     │ Grafana dashboard only (no push)                     │
│          │ Examples: Volume spikes, strategy regime changes      │
└──────────┴──────────────────────────────────────────────────────┘
```

### 7.2 Day 1 Telegram Alerts

```python
import asyncio
from telegram import Bot

class TelegramAlerter:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id

    async def send_alert(self, severity: str, title: str, details: dict):
        emoji = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}[severity]
        msg = (
            f"{emoji} **{severity}: {title}**\n"
            f"Time: {datetime.utcnow().isoformat()}Z\n"
            + "\n".join(f"`{k}`: `{v}`" for k, v in details.items())
        )
        await self.bot.send_message(chat_id=self.chat_id, text=msg,
                                     parse_mode='Markdown')

    async def send_kill_switch_alert(self, reason: str):
        await self.send_alert("CRITICAL", "KILL SWITCH ACTIVATED",
                               {"reason": reason, "action": "All trading halted"})
```

---

## 8. Deployment

### 8.1 Deployment Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    Deployment Pipeline                           │
│                                                                 │
│  Code Push → Tests → Build → Canary (5%) → Monitor → Full      │
│      │        │       │          │             │         │       │
│      ▼        ▼       ▼          ▼             ▼         ▼       │
│    Git CI   Pytest  Docker    Route 5%    Check KPIs   Route    │
│    Lint     Backtest Image    traffic     for 30min    100%     │
│    Type     Simulate                                             │
│    check                                                          │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Rollback Procedure

```
1. Detect issue (automated KPI check or manual)
2. Route canary traffic back to stable version (< 30s)
3. Stop canary instances
4. Investigate root cause
5. Fix and re-deploy through pipeline
```

### 8.3 Day 1 Deployment

```bash
#!/bin/bash
# Simple deployment with rollback capability
set -e

VERSION=$1
BACKUP_VERSION=$(cat /opt/tsar/current_version.txt)

echo "Deploying TSAR v${VERSION}..."

# Backup current state
docker save tsar:${BACKUP_VERSION} -o /opt/tsar/backups/tsar_${BACKUP_VERSION}.tar
cp -r /opt/tsar/config /opt/tsar/backups/config_${BACKUP_VERSION}

# Deploy new version
docker pull tsar:${VERSION}
docker-compose down
docker-compose up -d

# Health check
sleep 10
if curl -sf http://localhost:8080/health; then
    echo "${VERSION}" > /opt/tsar/current_version.txt
    echo "✅ Deployment successful"
else
    echo "❌ Health check failed, rolling back..."
    docker-compose down
    docker load -i /opt/tsar/backups/tsar_${BACKUP_VERSION}.tar
    docker-compose up -d
    echo "⚠️ Rolled back to v${BACKUP_VERSION}"
fi
```

---

## 9. Health Check Endpoints

```python
@app.get("/health")
async def health():
    """Basic liveness check."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/health/ready")
async def readiness():
    """Readiness check — can we accept traffic?"""
    checks = {
        "database": check_db_connection(),
        "exchange_binance": check_exchange("binance"),
        "exchange_okx": check_exchange("okx"),
        "redis": check_redis(),
        "market_data_feed": check_data_feed(),
    }
    all_ok = all(checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}

@app.get("/health/detailed")
async def detailed_health():
    """Detailed health for monitoring (requires auth)."""
    return {
        "status": "ok",
        "uptime_seconds": get_uptime(),
        "version": get_version(),
        "exchanges": get_exchange_status(),
        "strategies": get_strategy_status(),
        "system": {
            "cpu_pct": get_cpu_usage(),
            "memory_pct": get_memory_usage(),
            "disk_pct": get_disk_usage(),
        },
        "data_feeds": get_feed_status(),
    }
```

---

## 10. Day 1 Quick Start Checklist

```
☐ Set up structured JSON logging (file-based)
☐ Configure Telegram bot for ERROR/CRITICAL alerts
☐ Implement /health endpoint
☐ Create basic backup script (portfolio state + config → S3)
☐ Set up systemd service with auto-restart
☐ Create Grafana dashboard (manual metrics via Prometheus client)
☐ Document recovery runbook (print + digital copy)
☐ Test: kill process → verify auto-restart
☐ Test: corrupt state file → verify backup restore
```
