# TSAR QUALITY GATES — CHIEF RISK OFFICER MANDATE

**Version:** 1.0.0
**Date:** 2026-07-24
**Authority:** Chief Risk Officer, TSAR Council
**Status:** ACTIVE — MANDATORY for all engineering
**Reference:** TSAR Architecture v3.0.0 (`TSAR_ARCHITECTURE.md`)

---

## TABLE OF CONTENTS

1. [Risk-Specific Testing](#1-risk-specific-testing)
2. [Integration Safety](#2-integration-safety)
3. [Security Gates](#3-security-gates)
4. [Code Review Checklist](#4-code-review-checklist)
5. [Gate Enforcement](#5-gate-enforcement)
6. [Appendix: Test Matrix](#6-appendix-test-matrix)

---

## 1. RISK-SPECIFIC TESTING

> **The risk engine is the last line of defense. A bug here is existential.**

### 1.1 Coverage Requirement: 100% — No Exceptions

| Requirement | Target | Enforcement |
|---|---|---|
| Unit test line coverage | **100%** | `pytest --cov=src.risk --cov-fail-under=100` |
| Unit test branch coverage | **100%** | `pytest --cov-branch --cov-fail-under=100` |
| Every `RiskCheckResult` path tested | **100%** | Manual audit per PR |
| Every circuit breaker state tested | **100%** | See §1.3 |
| Every canonical value boundary tested | **100%** | See §1.5 |

**CI Enforcement:** Any PR that drops coverage below 100% on risk engine modules is **auto-blocked**. No merge. No exceptions.

**Scope:** All files under `src/risk/`, `src/interfaces/risk/`, and any module that imports from these.

### 1.2 Kill Switch Isolation Tests

The kill switch (§6.2, Architecture) is the single most critical piece of state. It must be testable in complete isolation — no Redis dependency, no exchange dependency, no network.

**Required Test Cases:**

| # | Test | Expected Behavior |
|---|------|-------------------|
| KS-01 | `activate()` writes to file `/tmp/tsar_kill_switch` | File exists, contains valid JSON with `{"active": true}` |
| KS-02 | `activate()` writes to Redis `tsar:risk:kill_switch` | Redis key set with TTL |
| KS-03 | `activate()` with Redis down | File still written, no exception raised, log CRITICAL |
| KS-04 | `activate()` with filesystem full | Redis still written, alert sent, log CRITICAL |
| KS-05 | `activate()` with both down | Exception raised, alert sent (Tier 3 watchdog takes over) |
| KS-06 | `is_active()` reads from file when Redis down | Returns `True` when file indicates active |
| KS-07 | `is_active()` reads from Redis when file missing | Returns Redis state |
| KS-08 | `is_active()` with both missing | Returns `True` (fail-safe: assume active) |
| KS-09 | `deactivate()` requires manual confirmation | Returns `False` without explicit confirmation token |
| KS-10 | External file write `echo '{"active":true}'` detected | Next `is_active()` returns `True` within 1 polling cycle |
| KS-11 | Kill switch activates during active order | All open orders cancelled, all positions flattened |
| KS-12 | Kill switch activates during position close | Close completes, no new orders accepted |
| KS-13 | Kill switch idempotency | Calling `activate()` 100 times produces same state as calling once |
| KS-14 | Kill switch persists across process restart | File survives, `is_active()` returns `True` after restart |

**Test Environment:**

```python
# tests/risk/test_kill_switch.py — MANDATORY STRUCTURE

class TestKillSwitchIsolation:
    """All tests run with mock Redis AND mock filesystem unless testing integration."""

    def test_ks01_file_write_on_activate(self, tmp_path, mock_redis):
        ...
    def test_ks02_redis_write_on_activate(self, tmp_path, mock_redis):
        ...
    def test_ks03_redis_down_file_still_written(self, tmp_path, redis_down):
        ...
    # ... all 14 cases
```

### 1.3 Circuit Breaker Transition Tests

Circuit breakers (§6.1, Architecture) have four states: GREEN → YELLOW → ORANGE → RED. Every transition, including edge cases, must be tested.

**Required Test Cases:**

| # | Test | Transition | Expected |
|---|------|-----------|----------|
| CB-01 | Drawdown crosses 2% threshold | GREEN → YELLOW | Position sizes reduced 50%, alert sent |
| CB-02 | Drawdown crosses 3% threshold | YELLOW → ORANGE | New trades blocked, existing allowed to close |
| CB-03 | Drawdown crosses 5% threshold | ORANGE → RED | Kill switch activated, all positions flattened |
| CB-04 | Drawdown recovers below 2% (gated recovery) | YELLOW → GREEN | Recovery follows §6.5 protocol, not instant |
| CB-05 | Drawdown at exactly 2.0% | GREEN → YELLOW | Boundary: enters YELLOW (≥ threshold) |
| CB-06 | Drawdown at exactly 3.0% | YELLOW → ORANGE | Boundary: enters ORANGE |
| CB-07 | Drawdown at exactly 5.0% | ORANGE → RED | Boundary: enters RED |
| CB-08 | Drawdown jumps from 1% to 6% | GREEN → RED | Skips YELLOW/ORANGE, goes direct to RED |
| CB-09 | Drawdown at 4.9% (just below RED) | ORANGE stays | Does NOT trigger RED |
| CB-10 | Recovery Phase 1 (10% size) — 24h elapsed, regime OK | ORANGE → Recovery P1 | Position size at 10% |
| CB-11 | Recovery Phase 1 — regime check fails | Stays ORANGE | No recovery, alert sent |
| CB-12 | Recovery Phase 2 — positive PnL required | P1 → P2 | 48h elapsed + positive PnL |
| CB-13 | Recovery Phase 2 — PnL negative | Stays P1 | No progression |
| CB-14 | Full recovery from ORANGE | P3 → FULL | win_rate > 40% verified |
| CB-15 | RED recovery Phase 1 requires manual OK | RED → P1 | Manual `/start` required |
| CB-16 | RED recovery without manual OK | Stays RED | No automatic recovery |
| CB-17 | RED full recovery requires Sharpe > 0 + report | P4 → FULL | Both conditions met |
| CB-18 | State persists across process restart | All states | Circuit breaker state in DB/Redis survives restart |
| CB-19 | Concurrent drawdown updates | Race condition | Single source of truth, no double-fire |
| CB-20 | Daily PnL reset at midnight UTC | GREEN reset | Daily loss counter resets, but HWM preserved |

**Edge Case Matrix:**

```
Drawdown Input → Expected State
───────────────────────────────
0.0%  → GREEN
1.9%  → GREEN
2.0%  → YELLOW
2.5%  → YELLOW
2.99% → YELLOW
3.0%  → ORANGE
4.5%  → ORANGE
4.99% → ORANGE
5.0%  → RED
10.0% → RED (no escalation beyond RED)
```

### 1.4 Anti-Behavioral Guard Tests

Anti-behavioral guards (§6.4, Architecture) prevent the system from exhibiting pathological trading behavior. These must be tested with realistic mock trade sequences.

**Required Test Cases:**

| # | Guard | Test Sequence | Expected |
|---|-------|--------------|----------|
| AB-01 | Revenge trading | 3 consecutive losses (L, L, L) | 60-minute cooldown activated |
| AB-02 | Revenge trading boundary | 2 losses then 1 win (L, L, W) | No cooldown (streak broken) |
| AB-03 | Revenge trading reset | 3 losses, cooldown expires | Trading resumes normally |
| AB-04 | Greed guard | Win → position size increase attempt | Size capped at base (0.25 fraction) |
| AB-05 | Greed guard | 5 wins, each requesting larger size | All capped at base size |
| AB-06 | FOMO guard | Signal score 0.55 (< 0.6 threshold) | Trade blocked |
| AB-07 | FOMO guard boundary | Signal score 0.60 | Trade allowed (≥ threshold) |
| AB-08 | FOMO guard | Signal score 0.0 | Trade blocked |
| AB-09 | Overconfidence | 5 consecutive wins, size increasing | Warning sent, size capped |
| AB-10 | Overconfidence boundary | 4 consecutive wins, size increasing | No warning (below threshold) |
| AB-11 | Overconfidence | 5 wins, base size (no increase) | No warning (no size increase) |
| AB-12 | Combined: revenge + greed | 3 losses then win with size increase | Cooldown THEN size cap on resume |
| AB-13 | Guard persistence | Guard state survives process restart | Cooldown timer preserved |
| AB-14 | Guard clock accuracy | Cooldown starts at loss timestamp, not check timestamp | 60 min from loss, not from detection |

**Mock Trade Sequence Factory:**

```python
# tests/risk/test_anti_behavioral.py — MANDATORY STRUCTURE

def make_trade(outcome: str, pnl: float, size_fraction: float = 0.25) -> MockTrade:
    """Create a mock trade for guard testing."""
    ...

class TestAntiBehavioralGuards:
    def test_ab01_revenge_trading_three_losses(self):
        trades = [make_trade("LOSS", -50), make_trade("LOSS", -30), make_trade("LOSS", -20)]
        guard = BehavioralGuard(trades)
        assert guard.check_cooldown().active is True
        assert guard.check_cooldown().duration_minutes == 60

    def test_ab04_greed_guard_size_cap(self):
        trades = [make_trade("WIN", 100, size_fraction=0.30)]
        guard = BehavioralGuard(trades)
        result = guard.check_size(trades[-1])
        assert result.adjusted_fraction == 0.25  # Capped
```

### 1.5 Parameter Validation Tests — Every Canonical Value

Every canonical value from Architecture §6.1 and Appendix A must have a test that validates the boundary. One test per parameter, per boundary direction.

**Required Test Cases:**

| # | Parameter | Canonical Value | Test: Below | Test: At | Test: Above |
|---|-----------|----------------|-------------|----------|-------------|
| PV-01 | Max position size | 15% of capital | Allowed | Allowed | **REJECTED** |
| PV-02 | Risk per trade | 2% of capital | Allowed | Allowed | **REDUCED** |
| PV-03 | Daily loss limit | -2% of capital | Trading OK | **KILL SWITCH** | **KILL SWITCH** |
| PV-04 | Max drawdown | 5% from HWM | Trading OK | **KILL SWITCH** | **KILL SWITCH** |
| PV-05 | Stop-loss required | Every trade | N/A | Present → OK | Missing → **REJECTED** |
| PV-06 | Max open positions (Day1) | 3 | Allowed | Allowed | **REJECTED** |
| PV-07 | Max open positions (Level2+) | 10 | Allowed | Allowed | **REJECTED** |
| PV-08 | Max single position | 15% of capital | Allowed | Allowed | **REJECTED** |
| PV-09 | Max sector concentration | 30% of capital | Allowed | Allowed | **REJECTED** |
| PV-10 | Kelly fraction | 0.25 (fixed) | N/A | Fixed | Any override **REJECTED** |
| PV-11 | Max correlation | 0.7 | Allowed | Allowed (0.7) | **REJECTED** (0.71) |
| PV-12 | Min risk-reward | 2:1 | **REJECTED** | Allowed | Allowed |
| PV-13 | Max daily trades | 30 | Allowed | Allowed | **REJECTED** |
| PV-14 | Cooldown period | 30 min | Within → **REJECTED** | At 30m → Allowed | After → Allowed |
| PV-15 | Stop-loss max distance | 2% from entry | Allowed | Allowed | **REJECTED** |
| PV-16 | Signal score minimum | 0.6 | **REJECTED** | Allowed | Allowed |

**Boundary Test Template:**

```python
@pytest.mark.parametrize("value,expected", [
    (0.14, "ALLOWED"),   # Below 15%
    (0.15, "ALLOWED"),   # At 15%
    (0.16, "REJECTED"),  # Above 15%
])
def test_pv01_max_position_size(value, expected, risk_engine):
    result = risk_engine.check_risk(
        symbol="BTC/USDT", side="LONG", entry_price=50000,
        stop_loss=49000, take_profit=52000, signal_score=0.7,
        current_equity=100, open_positions=[],
        daily_pnl=0, position_size_pct=value
    )
    assert result.approved == (expected == "ALLOWED")
```

### 1.6 Risk Engine Integration with Mock Exchange

All risk tests that touch exchange state must use a mock exchange gateway. No real API calls.

```python
# tests/risk/conftest.py

@pytest.fixture
def mock_exchange():
    """Mock ExchangeGateway returning deterministic data."""
    gateway = AsyncMock(spec=ExchangeGateway)
    gateway.get_balance.return_value = Balance(total=100.0, available=80.0)
    gateway.get_positions.return_value = []
    gateway.get_price.return_value = 50000.0
    return gateway
```

---

## 2. INTEGRATION SAFETY

> **Agents are only as safe as the pipeline that connects them.**

### 2.1 Signal → Risk → Execution Pipeline Test

The core trade lifecycle (Architecture Appendix C) must be tested end-to-end.

**Required Test Cases:**

| # | Test | Components | Expected |
|---|------|-----------|----------|
| INT-01 | Happy path: valid signal → approved → executed | Scout → Risk → Sniper | Signal approved, order placed, fills recorded |
| INT-02 | Rejected signal: risk limit breach | Scout → Risk → ✗ | Risk vetoes, no order placed, veto event published |
| INT-03 | Rejected signal: FOMO guard | Scout → Risk → ✗ | Signal score < 0.6, blocked |
| INT-04 | Signal with missing stop-loss | Scout → Risk → ✗ | Rejected, no order placed |
| INT-05 | Signal during kill switch active | Scout → Risk → ✗ | All signals rejected, kill switch event published |
| INT-06 | Signal during circuit breaker ORANGE | Scout → Risk → ✗ | New trades blocked |
| INT-07 | Execution failure → risk notification | Scout → Risk → Sniper (fail) | Risk Guardian notified, position state updated |
| INT-08 | Partial fill → risk update | Scout → Risk → Sniper (partial) | Risk state updated with partial position |
| INT-09 | Stop-loss placement after fill | Scout → Risk → Sniper → Exchange | Stop-loss order placed within 1 fill cycle |
| INT-10 | Take-profit placement after fill | Scout → Risk → Sniper → Exchange | TP order placed within 1 fill cycle |

**Pipeline Test Harness:**

```python
# tests/integration/test_pipeline.py

class TestSignalRiskExecutionPipeline:
    @pytest.fixture
    def pipeline(self, mock_exchange, mock_redis, tmp_path):
        """Wire up real Risk Guardian with mock exchange and in-memory streams."""
        kill_switch = DualWriteKillSwitch(redis=mock_redis, file_path=tmp_path / "kill")
        risk = PyRiskEngine(kill_switch=kill_switch, config=RiskLimits.from_canonical())
        scout = SignalScout(risk_engine=risk, exchange=mock_exchange)
        sniper = ExecutionSniper(risk_engine=risk, exchange=mock_exchange)
        return Pipeline(scout=scout, risk=risk, sniper=sniper)

    async def test_int01_happy_path(self, pipeline):
        signal = Signal(symbol="BTC/USDT", side="LONG", score=0.75,
                       entry_price=50000, stop_loss=49000, take_profit=52000)
        result = await pipeline.process(signal)
        assert result.status == "EXECUTED"
        assert result.order_id is not None
```

### 2.2 Kill Switch Propagation Test

When the kill switch activates, every component must respect it within one cycle.

| # | Test | Expected |
|---|------|----------|
| KS-P01 | Kill switch activates → Signal Scout stops publishing | No new signals within 1 cycle (5 min) |
| KS-P02 | Kill switch activates → Risk Guardian rejects all | All pending approvals vetoed |
| KS-P03 | Kill switch activates → Execution Sniper cancels all | All open orders cancelled |
| KS-P04 | Kill switch activates → Execution Sniper flattens | All positions closed via market order |
| KS-P05 | Kill switch activates → Orchestrator alert sent | Telegram alert within 30 seconds |
| KS-P06 | Kill switch activates → New signals during halt | All rejected with `tsar.risk.veto_all.v1` |
| KS-P07 | Kill switch → Process restart during halt | Kill switch still active after restart |
| KS-P08 | Kill switch → Manual resume | `/start` command clears kill switch, trading resumes |
| KS-P09 | Kill switch → Unauthorized resume attempt | Rejected without TRADE_ADMIN permission |
| KS-P10 | Kill switch propagation latency | All components halt within 10 seconds |

### 2.3 CloudEvents Message Flow Test

All inter-agent messages must conform to CloudEvents v1.0 (Architecture §5).

| # | Test | Expected |
|---|------|----------|
| CE-01 | Every event has required CloudEvents attributes | `specversion`, `id`, `source`, `type`, `time` present |
| CE-02 | `specversion` is always `"1.0"` | Enforced at publish time |
| CE-03 | `id` is ULID format | Time-sortable, globally unique |
| CE-04 | `source` matches `tsar:agent:{name}` pattern | URI format validated |
| CE-05 | `type` matches `tsar.{domain}.{action}.v1` pattern | Hierarchical naming enforced |
| CE-06 | `time` is RFC3339 with nanosecond precision | Validated at publish |
| CE-07 | `datacontenttype` is `application/msgpack` | Binary payload confirmed |
| CE-08 | TSAR extensions present | `traceid`, `priority`, `risklevel`, `agentrole`, `tradingmode`, `schemaver` |
| CE-09 | MessagePack deserialization roundtrip | Serialize → deserialize → compare |
| CE-10 | Redis Stream field naming | All fields prefixed with `ce_` |
| CE-11 | Event type registry completeness | All 25+ canonical event types have registered handlers |
| CE-12 | Unknown event type handling | Logged as warning, no crash |
| CE-13 | Malformed event handling | Rejected with error log, no crash |
| CE-14 | Event ordering in stream | ULID ensures time-ordering |
| CE-15 | Consumer group lag monitoring | Alert if consumer > 100 events behind |

**Event Type Coverage Matrix:**

```
Producer → Consumer → Event Type → Validated?
──────────────────────────────────────────────
Signal Scout → Risk Guardian → tsar.signal.detected.v1 → ☐
Risk Guardian → Execution Sniper → tsar.risk.decision.v1 → ☐
Risk Guardian → Execution Sniper → tsar.risk.veto.v1 → ☐
Risk Guardian → ALL → tsar.risk.veto_all.v1 → ☐
Risk Guardian → ALL → tsar.risk.kill_switch.v1 → ☐
Execution Sniper → Execution Tracker → tsar.order.placed.v1 → ☐
Execution Sniper → Execution Tracker → tsar.order.filled.v1 → ☐
Execution Sniper → Execution Tracker → tsar.order.cancelled.v1 → ☐
Execution Tracker → Trade Philosopher → tsar.fill.executed.v1 → ☐
Execution Tracker → Risk Guardian → tsar.position.updated.v1 → ☐
Trade Philosopher → Strategy Geneticist → tsar.analytics.trade_completed.v1 → ☐
Strategy Geneticist → Signal Scout → tsar.strategy.mutated.v1 → ☐
Macro Agent → Signal Scout → tsar.macro.regime_update.v1 → ☐
ALL → Orchestrator → tsar.health.heartbeat.v1 → ☐
```

### 2.4 Database Consistency Test

The trade memory system (Architecture §4.1) must remain consistent across all operations.

| # | Test | Expected |
|---|------|----------|
| DB-01 | Trade opened → DB record created | `trade_records` row exists with status `OPEN` |
| DB-02 | Trade filled → DB record updated | `entry_price`, `quantity`, `exchange_order_id` populated |
| DB-03 | Trade closed → DB record finalized | `exit_price`, `pnl`, `pnl_pct`, `closed_at` populated |
| DB-04 | Kill switch during trade → DB consistent | Trade status reflects actual state |
| DB-05 | Process crash during trade → DB recoverable | On restart, DB state matches exchange state |
| DB-06 | Concurrent trade writes → no corruption | SQLite WAL mode, single-writer |
| DB-07 | Trade ID uniqueness | `trade_id` is UNIQUE, no duplicates |
| DB-08 | Foreign key integrity | `lesson_applications.lesson_id` references valid lesson |
| DB-09 | FTS5 index sync | Lesson search returns correct results after insert |
| DB-10 | Backup during active trade | Backup captures consistent snapshot |
| DB-11 | Schema migration | New columns added without data loss |
| DB-12 | Audit log append-only | JSONL hash chain unbroken |

---

## 3. SECURITY GATES

> **No live capital until ALL gates pass. Period.**

### 3.1 Pre-Deployment Security Scan

| # | Gate | Tool | Threshold | Action on Fail |
|---|------|------|-----------|----------------|
| SEC-01 | Python dependency vulnerability scan | `safety check` | 0 critical, 0 high | **BLOCK deployment** |
| SEC-02 | Python static analysis | `bandit -r src/` | 0 high severity | **BLOCK deployment** |
| SEC-03 | Rust dependency audit | `cargo audit` | 0 critical, 0 high | **BLOCK deployment** |
| SEC-04 | Secrets scan | `trufflehog` or `gitleaks` | 0 secrets in repo | **BLOCK deployment** |
| SEC-05 | Docker image scan | `trivy` | 0 critical | **BLOCK deployment** |

**CI Pipeline Enforcement:**

```yaml
# .github/workflows/security.yml
security-gate:
  steps:
    - name: Safety check
      run: safety check --full-report
    - name: Bandit scan
      run: bandit -r src/ -ll -ii
    - name: Cargo audit
      run: cargo audit
    - name: Secrets scan
      run: trufflehog filesystem --directory=.
```

### 3.2 API Key Rotation Test

| # | Test | Expected |
|---|------|----------|
| KEY-01 | Rotate exchange API key → system continues | New key loaded from env, no restart needed (or graceful restart) |
| KEY-02 | Expired API key → graceful error | System enters safe mode, no trades, alert sent |
| KEY-03 | Invalid API key → no silent failure | Error logged, system halted, alert sent |
| KEY-04 | API key not in source code | `grep -r "api_key" src/` returns 0 results (env vars only) |
| KEY-05 | API key rotation during active position | Current position managed with old key until rotation completes |
| KEY-06 | Multiple key validation | All configured keys validated at startup |

### 3.3 Kill Switch Reliability Test — 100 Activations

The kill switch must be tested for reliability under stress. 100 rapid activations/deactivations without failure.

| # | Test | Expected |
|---|------|----------|
| KS-R01 | 100 rapid activate cycles | All 100 succeed, no race conditions |
| KS-R02 | 100 rapid activate → check cycles | `is_active()` returns correct state every time |
| KS-R03 | 100 activations with Redis intermittent | File fallback works every time |
| KS-R04 | 100 activations with file system slow | Redis primary works every time |
| KS-R05 | Activation latency p99 | < 100ms per activation |
| KS-R06 | Activation latency p99.9 | < 500ms per activation |
| KS-R07 | Memory leak after 1000 activations | RSS growth < 10MB |

**Test Script:**

```python
# tests/security/test_kill_switch_reliability.py

class TestKillSwitchReliability:
    def test_ksr01_100_rapid_cycles(self, kill_switch):
        for i in range(100):
            kill_switch.activate(reason=f"test_{i}")
            assert kill_switch.is_active() is True
            kill_switch.deactivate(token="test_token")
            assert kill_switch.is_active() is False

    def test_ksr05_activation_latency(self, kill_switch):
        latencies = []
        for i in range(100):
            start = time.monotonic()
            kill_switch.activate(reason=f"latency_test_{i}")
            latencies.append(time.monotonic() - start)
            kill_switch.deactivate(token="test_token")
        p99 = sorted(latencies)[98]
        assert p99 < 0.1, f"p99 latency {p99:.3f}s exceeds 100ms"
```

### 3.4 Stress Test — 1000 Trades in 1 Hour

The system must handle sustained high-throughput trading without degradation.

| # | Test | Expected |
|---|------|----------|
| ST-01 | 1000 trades processed in 1 hour | All trades recorded, no data loss |
| ST-02 | Risk engine throughput | > 1000 checks/second |
| ST-03 | Database write throughput | > 100 writes/second without corruption |
| ST-04 | Redis stream throughput | > 1000 events/second |
| ST-05 | Memory stability under load | RSS < 512MB throughout |
| ST-06 | CPU stability under load | < 80% sustained CPU |
| ST-07 | No event loss | All 1000 trades appear in all downstream streams |
| ST-08 | Kill switch under load | Activates within 1 second even during peak throughput |
| ST-09 | Circuit breaker under load | State transitions work correctly with rapid PnL changes |
| ST-10 | Graceful degradation | System slows down rather than crashes when overloaded |

**Stress Test Scenarios:**

```python
# tests/stress/test_throughput.py

class TestStressThousandTrades:
    async def test_st01_1000_trades_in_hour(self, pipeline):
        """Simulate 1000 trades with realistic timing."""
        trades = generate_trades(1000, interval_ms=3600)  # ~3.6s per trade
        results = await asyncio.gather(*[pipeline.process(t) for t in trades])
        assert all(r.status in ("EXECUTED", "REJECTED") for r in results)
        assert sum(1 for r in results if r.status == "EXECUTED") > 0

    async def test_st08_kill_switch_under_load(self, pipeline):
        """Kill switch activates during high throughput."""
        trades = generate_trades(1000, interval_ms=10)  # 10ms per trade
        # Activate kill switch at trade 500
        asyncio.create_task(delayed_kill_switch(pipeline.kill_switch, at_trade=500))
        results = await asyncio.gather(*[pipeline.process(t) for t in trades])
        # All trades after #500 should be rejected
        post_kill = results[500:]
        assert all(r.status == "REJECTED" for r in post_kill)
```

### 3.5 Negative Balance Protection Test

For leveraged products (Architecture §6.6), the system must prevent negative balances.

| # | Test | Expected |
|---|------|----------|
| NB-01 | Leverage within limit (forex major 20:1) | Trade allowed |
| NB-02 | Leverage exceeds limit | Trade rejected |
| NB-03 | Margin utilization at 59% | Trade allowed |
| NB-04 | Margin utilization at 60% | Trade rejected (cap) |
| NB-05 | Pre-liquidation buffer at 69% | Trade allowed |
| NB-06 | Pre-liquidation buffer at 70% of maintenance | Position reduced before exchange liquidation |
| NB-07 | Gap risk scenario — price gaps beyond stop | Loss capped at position value, no negative balance |
| NB-08 | Flash crash simulation (BTC -50%) | Kill switch fires, losses bounded |
| NB-09 | Overnight gap (forex) | Position sized for worst-case gap |
| NB-10 | Exchange auto-liquidation prevention | System acts before exchange does |

**Leverage Limits Matrix:**

```
Asset Class      Max Leverage    Gap Risk Multiplier
─────────────────────────────────────────────────────
forex_major      20:1            1.5x
forex_minor      10:1            2.0x
gold             10:1            1.5x
crypto_perp      3:1             2.0x
```

---

## 4. CODE REVIEW CHECKLIST

> **Every PR must pass ALL items. No exceptions. No "we'll fix it later."**

### 4.1 No Hardcoded Values

| # | Check | How to Verify |
|---|-------|---------------|
| CR-01 | No hardcoded numbers in risk engine | `grep -rn '[0-9]\+\.\?[0-9]*' src/risk/` — all must reference config |
| CR-02 | No hardcoded strings for stream names | All use `config.stream_prefix` + constant |
| CR-03 | No hardcoded API endpoints | All from `config/exchanges.yaml` or env vars |
| CR-04 | No hardcoded model names | All reference `task_type`, never model string (§8.1) |
| CR-05 | No hardcoded database paths | All from config |
| CR-06 | No hardcoded timeouts | All from `config/resource_limits.yaml` |
| CR-07 | All canonical values from Architecture §6.1 | Config file, not source code |

**Review Command:**

```bash
# Run before every PR review
grep -rn --include="*.py" -E '(0\.[0-9]+|[0-9]+\.[0-9]+)' src/risk/ | \
  grep -v 'config\|canonical\|constant\|LIMIT\|THRESHOLD' | \
  grep -v '#'  # Exclude comments
```

### 4.2 No LLM Calls in Risk Engine

**This is a hard architectural constraint.** The risk engine (Architecture §2.7) is deterministic. No LLM. No probability. No "it depends."

| # | Check | How to Verify |
|---|-------|---------------|
| CR-10 | No LLM imports in risk engine | `grep -rn 'ollama\|openai\|anthropic\|deepseek\|BaseLLMProvider' src/risk/` returns empty |
| CR-11 | No LLM imports in risk interfaces | `grep -rn 'ollama\|openai\|anthropic\|deepseek\|BaseLLMProvider' src/interfaces/risk/` returns empty |
| CR-12 | No `generate()` or `stream()` calls in risk | `grep -rn 'generate\|stream\|chat\|completion' src/risk/` — only non-LLM uses |
| CR-13 | Risk engine only uses T0 (math) tier | No task_type references in risk module |
| CR-14 | Risk decisions are deterministic | Same inputs → same outputs, always |

**CI Enforcement:**

```yaml
# .github/workflows/no-llm-in-risk.yml
check-no-llm-in-risk:
  steps:
    - name: Verify no LLM in risk engine
      run: |
        if grep -rn --include="*.py" \
          'ollama\|openai\|anthropic\|deepseek\|BaseLLMProvider\|LLMProvider' \
          src/risk/ src/interfaces/risk/; then
          echo "ERROR: LLM dependency found in risk engine!"
          exit 1
        fi
```

### 4.3 All Interfaces Properly Abstracted

| # | Check | How to Verify |
|---|-------|---------------|
| CR-20 | No direct `ccxt` import outside interfaces/ | `grep -rn 'import ccxt' src/` — only in `src/interfaces/exchange/` |
| CR-21 | No direct `pandas-ta` import outside interfaces/ | `grep -rn 'import pandas_ta' src/` — only in `src/interfaces/pricing/` |
| CR-22 | No direct `redis` import outside interfaces/ | `grep -rn 'import redis' src/` — only in `src/interfaces/` |
| CR-23 | All agents use `get_*()` getters | No direct `BackendRegistry.create()` in agent code |
| CR-24 | All backends implement ABC | Every backend has `class X(ABC):` parent |
| CR-25 | BackendRegistry is single source of truth | No hardcoded backend selection in agent code |
| CR-26 | New backends registered in `config/backends.yaml` | Config file updated before merge |

**Review Command:**

```bash
# Verify no direct backend imports in agent code
grep -rn --include="*.py" 'import ccxt\|import pandas_ta\|import redis' src/agents/
# Should return empty
```

### 4.4 Error Handling for Every External Call

| # | Check | How to Verify |
|---|-------|---------------|
| CR-30 | Every `await gateway.*` wrapped in try/except | Manual review + lint rule |
| CR-31 | Every `await engine.*` wrapped in try/except | Manual review + lint rule |
| CR-32 | Every Redis call has timeout | `redis.call(..., timeout=config.timeout)` |
| CR-33 | Every DB call has error handling | `sqlite3` exceptions caught |
| CR-34 | External API failures → safe state | No silent failures |
| CR-35 | Retry logic with exponential backoff | No infinite retries, max 3 attempts |
| CR-36 | Circuit breaker on external calls | Opens after 5 consecutive failures |
| CR-37 | Timeout on every external call | No unbounded waits |

**Review Template:**

```python
# Every external call must follow this pattern:
try:
    result = await gateway.get_price(symbol)
except ExchangeConnectionError as e:
    logger.error(f"Exchange connection failed: {e}", extra={"symbol": symbol})
    circuit_breaker.record_failure()
    raise SafeStateError("Cannot get price, entering safe state") from e
except ExchangeTimeoutError as e:
    logger.warning(f"Exchange timeout: {e}", extra={"symbol": symbol})
    raise SafeStateError("Exchange timeout, entering safe state") from e
except Exception as e:
    logger.critical(f"Unexpected exchange error: {e}", extra={"symbol": symbol})
    raise SafeStateError("Unexpected error, entering safe state") from e
```

### 4.5 Logging for Every Decision

| # | Check | How to Verify |
|---|-------|---------------|
| CR-40 | Every risk decision logged | `logger.info("risk_decision", ...)` with full context |
| CR-40a | Risk approval logged | Symbol, side, score, size, limits checked |
| CR-40b | Risk rejection logged | Symbol, side, reason, which limit breached |
| CR-40c | Kill switch activation logged | Timestamp, trigger reason, state before |
| CR-40d | Circuit breaker transition logged | From-state, to-state, drawdown value |
| CR-41 | Every order action logged | Place, fill, cancel, reject |
| CR-42 | Every anti-behavioral guard action logged | Which guard, what triggered, what action |
| CR-43 | Every LLM call logged | Task type, latency, tokens, cost |
| CR-44 | Every error logged | Full stack trace + context |
| CR-45 | Structured JSON logging | `{"timestamp": "...", "level": "...", "agent": "...", ...}` |
| CR-46 | Trace ID propagated | Every log entry includes `trace_id` from CloudEvents |
| CR-47 | No PII in logs | No API keys, no passwords, no private data |

**Log Level Guide:**

```
CRITICAL → Kill switch activation, system halt, data corruption
ERROR    → Order failures, exchange errors, risk limit breaches
WARNING  → Circuit breaker transitions, guard activations, retries
INFO     → Risk decisions, order actions, trade lifecycle events
DEBUG    → Indicator calculations, position size computations
```

### 4.6 Additional Review Checks

| # | Check | How to Verify |
|---|-------|---------------|
| CR-50 | Type hints on all public functions | `mypy --strict src/` passes |
| CR-51 | Docstrings on all public classes | `pydocstyle src/` passes |
| CR-52 | No `# type: ignore` without justification | Each must have a comment explaining why |
| CR-53 | No bare `except:` clauses | All exceptions are specific types |
| CR-54 | No `eval()` or `exec()` | Security risk |
| CR-55 | No global mutable state | All state in class instances or config |
| CR-56 | Async functions properly awaited | No fire-and-forget without logging |
| CR-57 | Resource cleanup in finally blocks | DB connections, file handles, etc. |
| CR-58 | Test file exists for every source file | 1:1 mapping enforced |
| CR-59 | No TODO/FIXME without tracking issue | Every TODO linked to GitHub issue |
| CR-60 | PR size < 500 lines | Break large changes into reviewable chunks |

---

## 5. GATE ENFORCEMENT

### 5.1 Gate Summary Matrix

| Gate Category | Phase | Blocking? | Owner |
|---|---|---|---|
| §1.1 Coverage (100%) | PR merge | **YES** | CI/CD |
| §1.2 Kill switch isolation | PR merge | **YES** | CI/CD |
| §1.3 Circuit breaker transitions | PR merge | **YES** | CI/CD |
| §1.4 Anti-behavioral guards | PR merge | **YES** | CI/CD |
| §1.5 Parameter validation | PR merge | **YES** | CI/CD |
| §2.1 Pipeline test | Pre-staging | **YES** | CI/CD |
| §2.2 Kill switch propagation | Pre-staging | **YES** | CI/CD |
| §2.3 CloudEvents flow | Pre-staging | **YES** | CI/CD |
| §2.4 Database consistency | Pre-staging | **YES** | CI/CD |
| §3.1 Security scan | Pre-deploy | **YES** | CI/CD |
| §3.2 API key rotation | Pre-deploy | **YES** | Manual + CI |
| §3.3 Kill switch 100x | Pre-deploy | **YES** | CI/CD |
| §3.4 Stress test (1000 trades) | Pre-deploy | **YES** | CI/CD |
| §3.5 Negative balance protection | Pre-deploy | **YES** | CI/CD |
| §4.x Code review checklist | Every PR | **YES** | Human reviewer |

### 5.2 Phase Gates

```
DEVELOPMENT → PR REVIEW → STAGING → SECURITY → DEPLOYMENT
     │            │           │          │           │
     │     §4 checklist   §2 integration  §3 security  §3 stress
     │     §1 unit tests   tests          scans        tests
     │            │           │          │           │
     ▼            ▼           ▼          ▼           ▼
   Code      Code Review   Integration  Security    Live
   Written   (human + CI)  (automated)  (automated) (manual OK)
```

**No live capital deployment until ALL gates pass.**

### 5.3 Gate Override Protocol

In exceptional circumstances, gates may be overridden with:

1. Written justification from the CRO
2. Risk assessment of the override
3. Time-bound expiration (max 48 hours)
4. Compensating controls documented
5. Post-override verification within 24 hours

**Overrides are logged to the immutable audit log.**

---

## 6. APPENDIX: TEST MATRIX

### 6.1 Complete Test Count by Category

| Category | Test Count | Coverage Target |
|---|---|---|
| §1.1 Risk engine unit tests | 100% line + branch | 100% |
| §1.2 Kill switch isolation | 14 tests | All failure modes |
| §1.3 Circuit breaker transitions | 20 tests | All state transitions |
| §1.4 Anti-behavioral guards | 14 tests | All guard types |
| §1.5 Parameter validation | 48 tests (16 params × 3 boundaries) | All canonical values |
| §2.1 Pipeline tests | 10 tests | Full lifecycle |
| §2.2 Kill switch propagation | 10 tests | All components |
| §2.3 CloudEvents flow | 15 tests | All event types |
| §2.4 Database consistency | 12 tests | All write paths |
| §3.1 Security scans | 5 scans | All dependencies |
| §3.2 API key rotation | 6 tests | All rotation scenarios |
| §3.3 Kill switch reliability | 7 tests | 100 activations |
| §3.4 Stress tests | 10 tests | 1000 trades/hour |
| §3.5 Negative balance | 10 tests | All leverage limits |
| **TOTAL** | **~181 tests + 5 scans** | |

### 6.2 Test Execution Schedule

| Test Suite | Frequency | Duration | Environment |
|---|---|---|---|
| Unit tests (§1.x) | Every commit | < 2 min | CI runner |
| Integration tests (§2.x) | Every PR | < 5 min | CI runner |
| Security scans (§3.1) | Every PR | < 3 min | CI runner |
| Kill switch reliability (§3.3) | Daily | < 1 min | CI runner |
| Stress tests (§3.4) | Weekly + pre-deploy | < 60 min | Dedicated runner |
| Negative balance (§3.5) | Pre-deploy | < 5 min | CI runner |
| Full regression | Pre-deploy | < 90 min | Staging environment |

### 6.3 Test Data Requirements

| Category | Data Needed |
|---|---|
| Circuit breaker | Historical drawdown sequences (2020, 2021, 2022 crashes) |
| Anti-behavioral | Mock trade sequences (win/loss patterns) |
| Parameter validation | Boundary values for every canonical parameter |
| Stress test | 1000 synthetic trades with realistic distribution |
| Negative balance | Historical flash crash price data |

---

## MANDATE

This document is **MANDATORY** for all TSAR engineering. No component goes live without passing every applicable gate. The risk engine is the last line of defense — its tests are non-negotiable.

**Signed: Chief Risk Officer, TSAR Council**
**Date: 2026-07-24**

---

*This document references TSAR Architecture v3.0.0 as the single source of truth.*
*All canonical values, stream names, and event types are defined in that document.*
