# FIX D — Risk Hardening: Critical & High-Severity Gap Remediation

**Version:** 1.0.0
**Date:** 2026-07-24
**Status:** Specification — Ready for Implementation
**Priority:** P0 — Must complete before live capital deployment
**Owner:** Risk Hardening Specialist
**Source:** Chief Risk Officer Review (CHIEF_RISK_OFFICER_REVIEW.md)
**Canonical Reference:** ARCHITECTURE_CONSOLIDATION.md §1.3

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [CRITICAL #1: Redis SPOF — File-Based Kill Switch Fallback](#2-critical-1-redis-spof--file-based-kill-switch-fallback)
3. [CRITICAL #2: Parameter Inconsistency — Canonical Value Reconciliation](#3-critical-2-parameter-inconsistency--canonical-value-reconciliation)
4. [CRITICAL #3: Kill Switch Monitor Watchdog](#4-critical-3-kill-switch-monitor-watchdog)
5. [HIGH #4: Kelly Fraction Standardization](#5-high-4-kelly-fraction-standardization)
6. [HIGH #5: Recovery Protocol — Regime/Performance Validation](#6-high-5-recovery-protocol--regimeperformance-validation)
7. [HIGH #6: Negative Balance Protection (OANDA Forex)](#7-high-6-negative-balance-protection-oanda-forex)
8. [HIGH #7: Stress Testing Specification](#8-high-7-stress-testing-specification)
9. [HIGH #8: Day-1 Resource Limits (Process-Level)](#9-high-8-day-1-resource-limits-process-level)
10. [Integration Map](#10-integration-map)
11. [Implementation Sequencing](#11-implementation-sequencing)

---

## 1. Executive Summary

The Chief Risk Officer identified **3 critical** and **5 high-severity** gaps in the TSAR risk architecture. This document provides complete remediation specifications for all 8 issues.

| # | Issue | Severity | Effort | Status |
|---|-------|----------|--------|--------|
| C1 | Redis SPOF for kill switch | CRITICAL | 2 days | Specified below |
| C2 | Parameter inconsistency across documents | CRITICAL | 1 day | Specified below |
| C3 | Kill switch monitor watchdog | CRITICAL | 1 day | Specified below |
| H4 | Kelly fraction inconsistency | HIGH | 0.5 days | Specified below |
| H5 | Recovery protocol lacks validation | HIGH | 1 day | Specified below |
| H6 | No negative balance protection (forex) | HIGH | 1 day | Specified below |
| H7 | No stress testing specification | HIGH | 2 days | Specified below |
| H8 | Day-1 resource limits not implemented | HIGH | 1 day | Specified below |

**Total estimated effort: 8.5 days (2 weeks with buffer)**

---

## 2. CRITICAL #1: Redis SPOF — File-Based Kill Switch Fallback

### 2.1 Problem

**Reference:** RISK_ARCHITECTURE.md §7 (Kill Switch), §10 (Redis State Schema)
**CRO Finding:** C2 — "Redis Single Point of Failure"

The entire kill switch system depends on Redis:

```
risk:kill_switch        → 'ACTIVE' / None
risk:kill_switch_reason → reason string
risk:kill_switch_timestamp → ISO timestamp
```

If Redis goes down during a volatile market:
1. Kill switch flag is unreadable → main process cannot check if trading is halted
2. Risk Governor cannot read portfolio state → all drawdown calculations fail
3. The system's behavior depends on fail-open vs fail-closed design

**Worst case:** Redis crashes + leveraged positions open = unlimited loss until manual intervention.

### 2.2 Solution: Dual-Write Kill Switch with File-Based Fallback

Design principle: **Kill switch state must survive Redis failure.** Write kill switch state to both Redis AND a local file. Read from file if Redis is unreachable.

```python
# risk_governor/kill_switch_persistence.py
"""
Dual-write kill switch persistence: Redis + file-based fallback.

The kill switch flag is the single most critical piece of state in the system.
It MUST be readable even if Redis is down. Solution: write to both Redis
and a local file atomically. Read from file if Redis is unreachable.

File location: /tmp/tsar_kill_switch (configurable)
Format: JSON with atomic write (write to .tmp, then rename)
Permissions: 0644 (world-readable — anyone can check if trading is halted)
"""

import json
import os
import time
import logging
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default path — overridable via config
KILL_SWITCH_FILE = os.environ.get(
    'TSAR_KILL_SWITCH_FILE',
    '/tmp/tsar_kill_switch'
)

KILL_SWITCH_FILE_TMP = KILL_SWITCH_FILE + '.tmp'


@dataclass
class KillSwitchState:
    """Kill switch state persisted to both Redis and file."""
    active: bool
    reason: str
    timestamp: str          # ISO 8601
    trigger: str            # KillSwitchTrigger value
    source: str             # 'redis' or 'file'
    redis_healthy: bool     # Whether Redis was reachable on last read

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, data: str) -> 'KillSwitchState':
        return cls(**json.loads(data))

    @classmethod
    def inactive(cls) -> 'KillSwitchState':
        return cls(
            active=False,
            reason="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            trigger="",
            source="none",
            redis_healthy=True,
        )


class DualWriteKillSwitch:
    """
    Kill switch with dual-write persistence (Redis + file).

    Write path:
        1. Write to file (atomic rename) — always succeeds
        2. Write to Redis — may fail (acceptable, file is authoritative)

    Read path:
        1. Try Redis first (faster, more authoritative)
        2. If Redis fails, read from file
        3. If both fail, assume KILL SWITCH ACTIVE (fail-safe)

    The file is the ultimate source of truth because:
    - It survives Redis crashes
    - It survives Redis restarts
    - It survives network partitions
    - It can be written by external processes (manual kill)
    - It can be read by any process on the host
    """

    REDIS_KEY = 'risk:kill_switch'
    REDIS_REASON_KEY = 'risk:kill_switch_reason'
    REDIS_TIMESTAMP_KEY = 'risk:kill_switch_timestamp'
    REDIS_TRIGGER_KEY = 'risk:kill_switch_trigger'

    def __init__(
        self,
        redis_client,
        file_path: str = KILL_SWITCH_FILE,
        redis_timeout_seconds: float = 2.0,
    ):
        self.redis = redis_client
        self.file_path = Path(file_path)
        self.redis_timeout = redis_timeout_seconds
        self._redis_healthy = True
        self._last_redis_check = 0.0

    def activate(
        self,
        trigger: str,
        reason: str,
        exchange_client=None,
        notifier=None,
    ) -> KillSwitchState:
        """
        Activate the kill switch. Dual-write to file + Redis.

        File write is PRIMARY (always succeeds).
        Redis write is SECONDARY (best-effort).
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        state = KillSwitchState(
            active=True,
            reason=reason,
            timestamp=timestamp,
            trigger=trigger,
            source='dual_write',
            redis_healthy=self._redis_healthy,
        )

        # 1. Write to file FIRST (atomic — this is the safety net)
        self._write_file(state)
        logger.critical(f"KILL SWITCH ACTIVATED (file): {trigger} — {reason}")

        # 2. Write to Redis (best-effort)
        self._write_redis(state)

        # 3. Execute kill actions (cancel orders, flatten positions)
        if exchange_client:
            self._execute_kill_actions(exchange_client)

        # 4. Notify
        if notifier:
            notifier.send_emergency(
                f"🚨 KILL SWITCH ACTIVATED 🚨\n"
                f"Trigger: {trigger}\n"
                f"Reason: {reason}\n"
                f"Time: {timestamp}\n"
                f"File: {self.file_path}\n"
                f"Redis: {'healthy' if self._redis_healthy else 'UNREACHABLE'}"
            )

        return state

    def deactivate(self, operator_id: str, reason: str) -> KillSwitchState:
        """
        Deactivate the kill switch. Requires human authorization.

        Only clears if both file and Redis are written successfully.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        state = KillSwitchState(
            active=False,
            reason=f"Deactivated by {operator_id}: {reason}",
            timestamp=timestamp,
            trigger="manual_deactivate",
            source='dual_write',
            redis_healthy=self._redis_healthy,
        )

        # Write to both
        self._write_file(state)
        self._write_redis(state)

        logger.info(f"Kill switch deactivated by {operator_id}: {reason}")
        return state

    def is_active(self) -> bool:
        """
        Check if kill switch is active.

        Read order:
        1. Try Redis (fast path)
        2. If Redis fails, read from file
        3. If both fail, return TRUE (fail-safe: assume killed)
        """
        # Try Redis first
        try:
            result = self.redis.get(self.REDIS_KEY)
            self._redis_healthy = True
            self._last_redis_check = time.time()
            if result == 'ACTIVE':
                return True
            elif result is None:
                # Key doesn't exist in Redis — check file as backup
                # (someone might have written to file directly)
                return self._read_file_active()
            else:
                return False
        except Exception as e:
            self._redis_healthy = False
            logger.warning(f"Redis unreachable for kill switch check: {e}")
            # Fall through to file check

        # Redis failed — read from file
        return self._read_file_active()

    def get_state(self) -> KillSwitchState:
        """Get full kill switch state (for monitoring/dashboard)."""
        # Try Redis
        try:
            pipe = self.redis.pipeline()
            pipe.get(self.REDIS_KEY)
            pipe.get(self.REDIS_REASON_KEY)
            pipe.get(self.REDIS_TIMESTAMP_KEY)
            pipe.get(self.REDIS_TRIGGER_KEY)
            results = pipe.execute()

            self._redis_healthy = True
            return KillSwitchState(
                active=results[0] == 'ACTIVE',
                reason=results[1] or "",
                timestamp=results[2] or "",
                trigger=results[3] or "",
                source='redis',
                redis_healthy=True,
            )
        except Exception as e:
            self._redis_healthy = False
            logger.warning(f"Redis unreachable for state read: {e}")

        # Fall back to file
        return self._read_file_state()

    def _write_file(self, state: KillSwitchState) -> None:
        """Atomic file write: write to .tmp, then rename."""
        try:
            # Ensure parent directory exists
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file
            tmp_path = self.file_path.with_suffix('.tmp')
            tmp_path.write_text(state.to_json())
            tmp_path.chmod(0o644)  # World-readable

            # Atomic rename
            tmp_path.rename(self.file_path)
            logger.debug(f"Kill switch state written to {self.file_path}")
        except Exception as e:
            logger.critical(f"FAILED TO WRITE KILL SWITCH FILE: {e}")
            # This is a critical failure — the file is our safety net
            # Try alternative locations
            self._write_file_fallback(state)

    def _write_file_fallback(self, state: KillSwitchState) -> None:
        """Fallback file locations if primary fails."""
        fallback_paths = [
            Path('/tmp/tsar_kill_switch'),
            Path.home() / '.tsar' / 'kill_switch',
            Path('/var/run/tsar_kill_switch'),
        ]
        for path in fallback_paths:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(state.to_json())
                path.chmod(0o644)
                logger.warning(f"Kill switch written to fallback: {path}")
                return
            except Exception:
                continue
        logger.critical("ALL KILL SWITCH FILE LOCATIONS FAILED — state is in-memory only!")

    def _write_redis(self, state: KillSwitchState) -> None:
        """Write to Redis (best-effort)."""
        try:
            pipe = self.redis.pipeline()
            if state.active:
                pipe.set(self.REDIS_KEY, 'ACTIVE')
                pipe.set(self.REDIS_REASON_KEY, state.reason)
                pipe.set(self.REDIS_TIMESTAMP_KEY, state.timestamp)
                pipe.set(self.REDIS_TRIGGER_KEY, state.trigger)
            else:
                pipe.delete(self.REDIS_KEY)
                pipe.delete(self.REDIS_REASON_KEY)
                pipe.delete(self.REDIS_TIMESTAMP_KEY)
                pipe.delete(self.REDIS_TRIGGER_KEY)
            pipe.execute()
            self._redis_healthy = True
        except Exception as e:
            self._redis_healthy = False
            logger.warning(f"Redis write failed (file is authoritative): {e}")

    def _read_file_active(self) -> bool:
        """Read kill switch state from file."""
        try:
            if not self.file_path.exists():
                # No file = no kill switch active
                return False
            content = self.file_path.read_text()
            state = KillSwitchState.from_json(content)
            return state.active
        except Exception as e:
            logger.error(f"Failed to read kill switch file: {e}")
            # FAIL-SAFE: If we can't read the file, assume kill switch is ACTIVE
            return True

    def _read_file_state(self) -> KillSwitchState:
        """Read full state from file."""
        try:
            if not self.file_path.exists():
                return KillSwitchState.inactive()
            content = self.file_path.read_text()
            state = KillSwitchState.from_json(content)
            state.source = 'file'
            state.redis_healthy = False
            return state
        except Exception as e:
            logger.error(f"Failed to read kill switch file: {e}")
            # Fail-safe: assume active
            return KillSwitchState(
                active=True,
                reason=f"File read failed: {e}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                trigger="file_read_failure",
                source='fail_safe',
                redis_healthy=False,
            )

    def _execute_kill_actions(self, exchange_client) -> None:
        """Execute kill switch actions: cancel orders, flatten positions."""
        try:
            open_orders = exchange_client.get_open_orders()
            for order in open_orders:
                try:
                    exchange_client.cancel_order(order['id'], order['symbol'])
                except Exception as e:
                    logger.error(f"Failed to cancel order {order['id']}: {e}")
        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")

        try:
            positions = exchange_client.get_positions()
            for pos in positions:
                if abs(pos['size']) > 0:
                    try:
                        side = 'SELL' if pos['side'] == 'LONG' else 'BUY'
                        exchange_client.create_market_order(
                            symbol=pos['symbol'],
                            side=side,
                            size=abs(pos['size']),
                            reduce_only=True,
                        )
                    except Exception as e:
                        logger.error(f"Failed to flatten {pos['symbol']}: {e}")
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")


class ExternalKillTrigger:
    """
    Allows external processes to trigger the kill switch via file.

    Usage: Write a JSON file to the kill switch path with active=true.
    The monitor process will pick it up within 5 seconds.

    Example manual kill:
        echo '{"active": true, "reason": "Manual kill", ...}' > /tmp/tsar_kill_switch
    """

    @staticmethod
    def manual_kill(reason: str = "Manual operator kill") -> None:
        """Write kill switch file directly (no Redis needed)."""
        state = KillSwitchState(
            active=True,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trigger="external_manual",
            source='external',
            redis_healthy=False,
        )
        path = Path(KILL_SWITCH_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(state.to_json())
        tmp.chmod(0o644)
        tmp.rename(path)
        print(f"Kill switch activated: {path}")

    @staticmethod
    def is_active() -> bool:
        """Quick check without Redis — read file only."""
        path = Path(KILL_SWITCH_FILE)
        if not path.exists():
            return False
        try:
            state = KillSwitchState.from_json(path.read_text())
            return state.active
        except Exception:
            return True  # Fail-safe
```

### 2.3 Dead Man's Switch (Heartbeat-Based)

In addition to file fallback, add a heartbeat pattern: Risk Governor writes a heartbeat every 5 seconds. If the kill monitor doesn't see the heartbeat for 15 seconds, it activates the kill switch.

```python
# risk_governor/dead_mans_switch.py
"""
Dead Man's Switch: heartbeat-based liveness detection.

If the Risk Governor process crashes or hangs, the kill switch
monitor detects the missing heartbeat and activates the kill switch.

This covers:
- Risk Governor process crash
- Risk Governor infinite loop / hang
- Network partition between Risk Governor and Redis
- Risk Governor OOM kill
"""

import time
import json
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DeadMansSwitch:
    """
    Heartbeat-based liveness detection for the Risk Governor.

    Writer (Risk Governor): calls `heartbeat()` every 5 seconds.
    Reader (Kill Monitor): calls `check()` every 5 seconds.
    If heartbeat is stale for > `timeout_seconds`, activate kill switch.
    """

    REDIS_KEY = 'risk:governor_heartbeat'
    DEFAULT_TIMEOUT = 15.0  # seconds

    def __init__(self, redis_client, timeout_seconds: float = DEFAULT_TIMEOUT):
        self.redis = redis_client
        self.timeout = timeout_seconds
        self._last_write = 0.0

    def heartbeat(self) -> None:
        """Write heartbeat. Call from Risk Governor main loop."""
        now = time.time()
        payload = json.dumps({
            'timestamp': now,
            'iso': datetime.now(timezone.utc).isoformat(),
            'pid': os.getpid(),
        })
        try:
            self.redis.set(self.REDIS_KEY, payload, ex=int(self.timeout * 3))
            self._last_write = now
        except Exception as e:
            logger.error(f"Failed to write heartbeat: {e}")

    def is_alive(self) -> bool:
        """Check if Risk Governor is alive."""
        try:
            data = self.redis.get(self.REDIS_KEY)
            if not data:
                return False
            heartbeat = json.loads(data)
            age = time.time() - heartbeat['timestamp']
            return age < self.timeout
        except Exception:
            # Redis unreachable — can't determine liveness
            # Return False to trigger fail-safe kill
            return False

    def check_and_kill_if_stale(self, kill_switch) -> bool:
        """
        Check heartbeat. If stale, activate kill switch.
        Returns True if kill switch was activated.
        """
        if self.is_alive():
            return False

        logger.critical(
            f"DEAD MAN'S SWITCH: Risk Governor heartbeat stale "
            f"(>{self.timeout}s). Activating kill switch."
        )
        kill_switch.activate(
            trigger="dead_mans_switch",
            reason=f"Risk Governor heartbeat missing for >{self.timeout}s. "
                   f"Process may be crashed or hung.",
        )
        return True


class HeartbeatWriter:
    """
    Background thread that writes heartbeats for the Risk Governor.

    Starts a daemon thread that writes heartbeat every `interval` seconds.
    Automatically stops when the main process exits.
    """

    def __init__(self, dead_mans_switch: DeadMansSwitch, interval: float = 5.0):
        self.dms = dead_mans_switch
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Start the heartbeat writer thread."""
        self._thread.start()
        logger.info(f"Heartbeat writer started (interval={self.interval}s)")

    def stop(self) -> None:
        """Stop the heartbeat writer."""
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.dms.heartbeat()
            except Exception as e:
                logger.error(f"Heartbeat write failed: {e}")
            self._stop.wait(self.interval)
```

### 2.4 Integration Points

| Component | Integration |
|-----------|-------------|
| `KillSwitch` class in RISK_ARCHITECTURE.md §7.2 | Replace with `DualWriteKillSwitch` |
| `AutoKillDetector` in RISK_ARCHITECTURE.md §7.2 | Add `DeadMansSwitch.check_and_kill_if_stale()` call |
| Risk Governor main loop | Add `HeartbeatWriter.start()` at init |
| Monitor process (§7.2) | Check file-based kill switch state alongside Redis |
| Manual kill CLI | Use `ExternalKillTrigger.manual_kill()` |

### 2.5 File-Based Kill Switch Protocol

```
┌─────────────────────────────────────────────────────────────┐
│              KILL SWITCH DUAL-WRITE ARCHITECTURE             │
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                  │
│  │  TRIGGER      │         │  TRIGGER      │                 │
│  │  (Automatic)  │         │  (Manual/CLI) │                 │
│  └──────┬───────┘         └──────┬───────┘                  │
│         │                        │                           │
│         ▼                        ▼                           │
│  ┌─────────────────────────────────────────────┐            │
│  │        DualWriteKillSwitch.activate()        │            │
│  │                                              │            │
│  │  1. Write /tmp/tsar_kill_switch (PRIMARY)    │            │
│  │  2. Write Redis risk:kill_switch (SECONDARY) │            │
│  │  3. Execute kill actions                     │            │
│  │  4. Send notifications                       │            │
│  └──────────────────────┬──────────────────────┘            │
│                         │                                    │
│         ┌───────────────┼───────────────┐                   │
│         ▼               ▼               ▼                   │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │ Main Proc  │  │ Kill Mon   │  │ Ext Process│            │
│  │ Check file │  │ Check file │  │ Check file │            │
│  │ if Redis   │  │ if Redis   │  │ (manual)   │            │
│  │ fails      │  │ fails      │  │            │            │
│  └────────────┘  └────────────┘  └────────────┘            │
│                                                              │
│  ┌─────────────────────────────────────────────┐            │
│  │        Dead Man's Switch (Heartbeat)         │            │
│  │                                              │            │
│  │  Risk Governor → writes heartbeat every 5s   │            │
│  │  Kill Monitor  → checks heartbeat every 5s   │            │
│  │  If stale > 15s → activate kill switch       │            │
│  └─────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

### 2.6 Effort Estimate

| Task | Effort |
|------|--------|
| `DualWriteKillSwitch` implementation | 4 hours |
| `DeadMansSwitch` + `HeartbeatWriter` | 3 hours |
| Integration with existing `KillSwitch` class | 2 hours |
| `ExternalKillTrigger` CLI tool | 1 hour |
| Unit tests (Redis down, file fallback, fail-safe) | 3 hours |
| Integration test (kill Redis mid-trade) | 2 hours |
| **Total** | **~15 hours (2 days)** |

---

## 3. CRITICAL #2: Parameter Inconsistency — Canonical Value Reconciliation

### 3.1 Problem

**Reference:** CRO Review §1 "CRITICAL ISSUE #1: Cross-Document Parameter Inconsistency"
**Also:** ARCHITECTURE_CONSOLIDATION.md §1.3, Contradictions §3-4

Risk parameters differ across documents. The canonical source (ARCHITECTURE_CONSOLIDATION.md) defines specific values, but RISK_ARCHITECTURE.md uses different (more permissive) values.

### 3.2 Full Reconciliation Table

Every value below marked ❌ must be updated in RISK_ARCHITECTURE.md.

| Parameter | RISK_ARCHITECTURE.md (Current) | CANONICAL (ARCHITECTURE_CONSOLIDATION.md) | Status | Action |
|-----------|-------------------------------|------------------------------------------|--------|--------|
| Daily loss kill | -4% | **-2%** | ❌ WRONG | Update §3.1, §11.2 |
| Weekly loss kill | -8% | (not specified) | ⚠️ DERIVE | Set to -4% (2x daily) |
| Monthly loss kill | -15% | (not specified) | ⚠️ DERIVE | Set to -8% (4x daily) |
| Total drawdown kill | -20% | **-5%** | ❌ WRONG | Update §3.1, §11.2 |
| Max open positions | 20 | **10** (Day1: 3) | ❌ WRONG | Update §2.2, §11.2 |
| Max position value | 10% | **15%** | ❌ WRONG | Update §2.2, §11.2 |
| Kelly fraction | Half-Kelly (kelly/2) dynamic | **0.25 fixed** | ❌ WRONG | Update §2.1, §11.2 |
| Min R:R ratio | 1.5:1 | **2:1** | ❌ WRONG | Update §8.1 Gate 9 |
| Max sector concentration | 25% | **30%** | ❌ WRONG | Update §2.2 |
| Max daily trades | (not specified) | **30** | ⚠️ MISSING | Add to §2.2 |
| Daily loss warn | -1.5% | (not specified) | ✅ OK | Keep |
| Daily loss halt | -2.5% | (not specified) | ⚠️ TIGHT | Set to -1.5% (between warn -1% and kill -2%) |

### 3.3 Canonical Drawdown Thresholds (Reconciled)

Based on ARCHITECTURE_CONSOLIDATION.md canonical values, the circuit breaker thresholds must be:

```python
# risk_governor/config.py — CANONICAL VALUES
# Source: ARCHITECTURE_CONSOLIDATION.md §1.3
# These are the ONLY valid values. All other documents must reference these.

@dataclass(frozen=True)
class RiskConfig:
    """Immutable risk configuration. CANONICAL VALUES."""

    # === POSITION SIZING (CANONICAL) ===
    max_risk_per_trade_pct: float = 0.02         # 2% — unchanged
    max_position_value_pct: float = 0.15         # 15% — was 10%, now 15%
    max_gross_exposure_pct: float = 1.50         # 150% — unchanged
    max_net_exposure_pct: float = 1.00           # 100% — unchanged
    max_open_positions: int = 10                 # 10 — was 20, now 10 (Day1: 3)
    max_open_positions_day1: int = 3             # Day-1 limit
    max_sector_exposure_pct: float = 0.30        # 30% — was 25%, now 30%
    min_conviction: float = 0.60                 # 60% — unchanged
    min_risk_reward_ratio: float = 2.0           # 2:1 — was 1.5, now 2:1
    max_daily_trades: int = 30                   # 30 — was missing
    kelly_fraction: float = 0.25                 # 0.25 FIXED — was dynamic kelly/2

    # === DRAWDOWN (CANONICAL) ===
    # Kill switch thresholds — from ARCHITECTURE_CONSOLIDATION.md
    daily_loss_kill: float = -0.02               # -2% — was -4%, now -2%
    total_drawdown_kill: float = -0.05           # -5% — was -20%, now -5%

    # Halt thresholds (between warn and kill)
    daily_loss_halt: float = -0.015              # -1.5% — was -2.5%
    weekly_loss_halt: float = -0.03              # -3% — derived
    monthly_loss_halt: float = -0.05             # -5% — derived
    total_drawdown_halt: float = -0.035          # -3.5% — between warn and kill

    # Warn thresholds
    daily_loss_warn: float = -0.01               # -1% — was -1.5%
    weekly_loss_warn: float = -0.02              # -2% — derived
    monthly_loss_warn: float = -0.03             # -3% — derived
    total_drawdown_warn: float = -0.02           # -2% — derived

    # Kill thresholds (weekly/monthly derived from daily)
    weekly_loss_kill: float = -0.04              # -4% — 2x daily kill
    monthly_loss_kill: float = -0.08             # -8% — 4x daily kill

    # === ANTI-BEHAVIORAL (unchanged) ===
    consecutive_losses_cooldown: int = 3
    consecutive_losses_cooldown_minutes: int = 60
    extended_losses_threshold: int = 5
    extended_cooldown_minutes: int = 240
    max_daily_losses: int = 6
    win_streak_threshold: int = 5
    win_streak_reduction: float = 0.7
    extended_win_streak: int = 8
    extended_win_reduction: float = 0.5
    max_conviction_multiplier: float = 1.5
    max_high_conviction_positions: int = 3

    # === CORRELATION (unchanged) ===
    high_correlation_threshold: float = 0.7
    regime_change_threshold: float = 0.85
    max_correlated_exposure_pct: float = 0.30
    correlation_window: int = 60

    # === TIME RULES (unchanged) ===
    weekend_close_hour_utc: int = 20
    weekend_reduce_hour_utc: int = 16
    weekend_reduction_factor: float = 0.5
    funding_rate_threshold: float = 0.01
    funding_rate_reduce_at: float = 0.005

    # === KILL SWITCH (unchanged) ===
    rapid_move_threshold_pct: float = 0.05
    max_consecutive_errors: int = 3
    data_feed_timeout_seconds: int = 30
```

### 3.4 Reconciled Circuit Breaker Table

```
CIRCUIT BREAKER LEVELS (CANONICAL):

Level 0: GREEN (Normal)
  - Daily P&L:   > -1%
  - Weekly P&L:  > -2%
  - Monthly P&L: > -3%
  - Total DD:    > -2%
  → Full trading allowed

Level 1: YELLOW (Caution)
  - Daily P&L:   -1% to -1.5%
  - Weekly P&L:  -2% to -3%
  - Monthly P&L: -3% to -5%
  - Total DD:    -2% to -3.5%
  → Reduce position sizes by 50%
  → Alert sent to operator

Level 2: ORANGE (Danger)
  - Daily P&L:   -1.5% to -2%
  - Weekly P&L:  -3% to -4%
  - Monthly P&L: -5% to -8%
  - Total DD:    -3.5% to -5%
  → Halt all new trades
  → Reduce existing positions by 50%
  → Manual review required to resume

Level 3: RED (Emergency)
  - Daily P&L:   < -2%              ← CANONICAL KILL SWITCH
  - Weekly P&L:  < -4%
  - Monthly P&L: < -8%
  - Total DD:    > -5%              ← CANONICAL KILL SWITCH
  → FLATTEN ALL POSITIONS immediately
  → Kill switch activated
  → Trading halted until manual reset
```

### 3.5 Flagged Wrong References

Every reference below in RISK_ARCHITECTURE.md must be updated:

| Section | Current Text | Corrected Text |
|---------|-------------|----------------|
| §3.1 `DrawdownThresholds` `daily_loss_kill` | `-0.04` | `-0.02` |
| §3.1 `DrawdownThresholds` `total_drawdown_kill` | `-0.20` | `-0.05` |
| §3.1 `DrawdownThresholds` `daily_loss_halt` | `-0.025` | `-0.015` |
| §3.1 `DrawdownThresholds` `total_drawdown_halt` | `-0.15` | `-0.035` |
| §3.1 `DrawdownThresholds` `daily_loss_warn` | `-0.015` | `-0.01` |
| §3.1 `DrawdownThresholds` `total_drawdown_warn` | `-0.10` | `-0.02` |
| §2.2 `POSITION_LIMITS` `max_position_value_pct` | `0.10` | `0.15` |
| §2.2 `POSITION_LIMITS` `max_open_positions` | `20` | `10` |
| §2.2 `POSITION_LIMITS` `max_sector_exposure_pct` | `0.25` | `0.30` |
| §2.1 `kelly_fraction` return | `min(half_kelly, 0.02)` | `min(0.25, 0.02)` |
| §8.1 Gate 9 `risk_reward_ratio` check | `< 1.5` | `< 2.0` |
| §11.2 `RiskConfig` all matching fields | (various) | (see §3.3 above) |
| Summary table at end | (various) | (see §3.3 above) |

### 3.6 Effort Estimate

| Task | Effort |
|------|--------|
| Update RISK_ARCHITECTURE.md with canonical values | 3 hours |
| Update all code blocks in RISK_ARCHITECTURE.md | 2 hours |
| Cross-reference audit of all other docs | 2 hours |
| Update config.py with frozen canonical values | 1 hour |
| **Total** | **~8 hours (1 day)** |

---

## 4. CRITICAL #3: Kill Switch Monitor Watchdog

### 4.1 Problem

**Reference:** CRO Review §2 "HIGH ISSUE #1: Monitor-the-Monitor Gap"

The `AutoKillDetector` runs as a separate process and checks every 5 seconds. But nothing monitors the `AutoKillDetector` itself. If it crashes:

- No automatic kill switch on drawdown RED
- No exchange connectivity monitoring
- No data feed staleness detection
- No rapid market move detection

### 4.2 Solution: Three-Tier Watchdog Architecture

```
Tier 1: Risk Governor (main process)
  → Heartbeat every 5s to Redis
  → Monitored by Tier 2

Tier 2: Kill Switch Monitor (AutoKillDetector)
  → Checks risk conditions every 5s
  → Heartbeat every 5s to Redis
  → Monitored by Tier 3

Tier 3: Watchdog Process (systemd / supervisor)
  → Checks Tier 1 and Tier 2 heartbeats every 10s
  → If either is stale > 15s → activate kill switch via FILE
  → Lowest-level process — runs as systemd service
  → Cannot be killed by the agent process
```

### 4.3 Watchdog Implementation

```python
# monitor/watchdog.py
"""
Tier 3 Watchdog: monitors the monitors.

This process is the last line of defense. It:
1. Checks Risk Governor heartbeat (Tier 1)
2. Checks Kill Switch Monitor heartbeat (Tier 2)
3. If either is stale, activates kill switch via FILE (not Redis)
4. Runs as a systemd service — cannot be killed by the agent

The watchdog NEVER uses Redis for its own state. It reads
heartbeats from Redis, but its kill action writes to the
file-based kill switch (§2).
"""

import json
import time
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s WATCHDOG %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/tsar/watchdog.log'),
    ]
)
logger = logging.getLogger(__name__)


class Watchdog:
    """
    Tier 3 watchdog process.

    Monitors:
    - Risk Governor heartbeat (risk:governor_heartbeat)
    - Kill Switch Monitor heartbeat (risk:monitor_heartbeat)

    Actions:
    - If Risk Governor stale > 15s → activate kill switch via file
    - If Kill Monitor stale > 15s → activate kill switch via file
    - If Redis unreachable → activate kill switch via file

    This is the ONLY process that can kill the system when Redis is down.
    """

    GOVERNOR_HEARTBEAT_KEY = 'risk:governor_heartbeat'
    MONITOR_HEARTBEAT_KEY = 'risk:monitor_heartbeat'
    GOVERNOR_TIMEOUT = 15.0     # seconds
    MONITOR_TIMEOUT = 15.0      # seconds
    CHECK_INTERVAL = 10.0       # seconds
    KILL_SWITCH_FILE = '/tmp/tsar_kill_switch'
    WATCHDOG_OWN_HEARTBEAT = '/tmp/tsar_watchdog_heartbeat'

    def __init__(self, redis_url: str = 'redis://localhost:6379'):
        self.redis_url = redis_url
        self.redis_client = None
        self._running = True
        self._kill_count = 0

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def run(self) -> None:
        """Main watchdog loop."""
        logger.info("Watchdog starting...")
        self._connect_redis()

        while self._running:
            try:
                self._check_cycle()
                self._write_own_heartbeat()
            except Exception as e:
                logger.error(f"Watchdog cycle error: {e}")
                # On any unhandled error, activate kill switch
                self._activate_kill("watchdog_error", f"Watchdog error: {e}")

            time.sleep(self.CHECK_INTERVAL)

        logger.info("Watchdog stopped")

    def _check_cycle(self) -> None:
        """Single check cycle."""
        # 1. Check Redis connectivity
        redis_ok = self._check_redis()
        if not redis_ok:
            logger.warning("Redis unreachable — checking file-based kill switch")
            # If Redis is down, check if kill switch is already active via file
            if not self._is_file_kill_active():
                self._activate_kill(
                    "redis_unreachable",
                    "Redis is unreachable. Cannot monitor Risk Governor or Kill Monitor. "
                    "Activating kill switch as precaution."
                )
            return

        # 2. Check Risk Governor heartbeat
        governor_alive = self._check_heartbeat(
            self.GOVERNOR_HEARTBEAT_KEY,
            self.GOVERNOR_TIMEOUT,
            "Risk Governor"
        )
        if not governor_alive:
            self._activate_kill(
                "governor_stale",
                f"Risk Governor heartbeat missing for >{self.GOVERNOR_TIMEOUT}s"
            )
            return

        # 3. Check Kill Switch Monitor heartbeat
        monitor_alive = self._check_heartbeat(
            self.MONITOR_HEARTBEAT_KEY,
            self.MONITOR_TIMEOUT,
            "Kill Monitor"
        )
        if not monitor_alive:
            self._activate_kill(
                "monitor_stale",
                f"Kill Switch Monitor heartbeat missing for >{self.MONITOR_TIMEOUT}s"
            )
            return

        logger.debug("All heartbeats healthy")

    def _check_redis(self) -> bool:
        """Check Redis connectivity."""
        try:
            if self.redis_client is None:
                self._connect_redis()
            self.redis_client.ping()
            return True
        except Exception:
            self.redis_client = None
            return False

    def _connect_redis(self) -> None:
        """Connect to Redis with retry."""
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
            self.redis_client.ping()
            logger.info(f"Connected to Redis: {self.redis_url}")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            self.redis_client = None

    def _check_heartbeat(self, key: str, timeout: float, name: str) -> bool:
        """Check if a heartbeat is fresh."""
        try:
            data = self.redis_client.get(key)
            if not data:
                logger.warning(f"{name} heartbeat key missing: {key}")
                return False

            heartbeat = json.loads(data)
            age = time.time() - heartbeat.get('timestamp', 0)
            if age > timeout:
                logger.warning(f"{name} heartbeat stale: {age:.1f}s > {timeout}s")
                return False

            return True
        except Exception as e:
            logger.error(f"Failed to check {name} heartbeat: {e}")
            return False

    def _activate_kill(self, trigger: str, reason: str) -> None:
        """Activate kill switch via FILE (not Redis — Redis may be down)."""
        self._kill_count += 1
        timestamp = datetime.now(timezone.utc).isoformat()

        state = {
            'active': True,
            'reason': reason,
            'timestamp': timestamp,
            'trigger': trigger,
            'source': 'watchdog',
            'kill_count': self._kill_count,
        }

        try:
            path = Path(self.KILL_SWITCH_FILE)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(state, indent=2))
            tmp.chmod(0o644)
            tmp.rename(path)
            logger.critical(
                f"KILL SWITCH ACTIVATED BY WATCHDOG: {trigger} — {reason}"
            )
        except Exception as e:
            logger.critical(f"FAILED TO WRITE KILL SWITCH FILE: {e}")

        # Also try Redis (best-effort)
        try:
            if self.redis_client:
                self.redis_client.set('risk:kill_switch', 'ACTIVE')
                self.redis_client.set('risk:kill_switch_reason', reason)
                self.redis_client.set('risk:kill_switch_timestamp', timestamp)
        except Exception:
            pass

    def _is_file_kill_active(self) -> bool:
        """Check if kill switch is already active via file."""
        try:
            path = Path(self.KILL_SWITCH_FILE)
            if not path.exists():
                return False
            state = json.loads(path.read_text())
            return state.get('active', False)
        except Exception:
            return True  # Fail-safe

    def _write_own_heartbeat(self) -> None:
        """Write watchdog's own heartbeat (for external monitoring)."""
        try:
            path = Path(self.WATCHDOG_OWN_HEARTBEAT)
            path.write_text(json.dumps({
                'timestamp': time.time(),
                'iso': datetime.now(timezone.utc).isoformat(),
                'kill_count': self._kill_count,
            }))
        except Exception:
            pass

    def _handle_signal(self, signum, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self._running = False


if __name__ == '__main__':
    import os
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    watchdog = Watchdog(redis_url=redis_url)
    watchdog.run()
```

### 4.4 systemd Service Definition

```ini
# /etc/systemd/system/tsar-watchdog.service
# Tier 3 watchdog — highest priority, cannot be killed by agent

[Unit]
Description=TSAR Watchdog — Tier 3 Kill Switch Monitor
After=network.target redis.service
Wants=redis.service
# Ensure watchdog starts before the agent
Before=tsar-agent.service

[Service]
Type=simple
User=tsar
Group=tsar
ExecStart=/opt/tsar/venv/bin/python -m monitor.watchdog
Restart=always
RestartSec=5
# Watchdog must have its own watchdog (systemd watchdog)
WatchdogSec=30
NotifyAccess=main

# Resource limits for watchdog itself
MemoryMax=64M
CPUQuota=10%

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/tmp /var/log/tsar
PrivateTmp=no  # Need access to /tmp/tsar_kill_switch

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=tsar-watchdog

[Install]
WantedBy=multi-user.target
```

### 4.5 Three-Tier Monitoring Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                 THREE-TIER WATCHDOG ARCHITECTURE                 │
│                                                                  │
│  Tier 1: Risk Governor (main agent process)                     │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  • Evaluates trades (deterministic)                   │       │
│  │  • Writes heartbeat every 5s → risk:governor_heartbeat│       │
│  │  • Can activate kill switch                           │       │
│  └──────────────────────────┬───────────────────────────┘       │
│                             │ heartbeat                          │
│                             ▼                                    │
│  Tier 2: Kill Switch Monitor (AutoKillDetector)                 │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  • Checks risk conditions every 5s                    │       │
│  │  • Checks Tier 1 heartbeat                            │       │
│  │  • Writes own heartbeat every 5s → risk:monitor_*     │       │
│  │  • Can activate kill switch                           │       │
│  └──────────────────────────┬───────────────────────────┘       │
│                             │ heartbeat                          │
│                             ▼                                    │
│  Tier 3: Watchdog (systemd service)                             │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  • Checks Tier 1 + Tier 2 heartbeats every 10s       │       │
│  │  • If EITHER stale > 15s → kill via FILE              │       │
│  │  • If Redis unreachable → kill via FILE               │       │
│  │  • Runs as systemd service (cannot be killed by agent)│       │
│  │  • Writes to /tmp/tsar_kill_switch directly            │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                  │
│  FAILURE MODES:                                                  │
│  ┌─────────────────────────┬───────────────────────────────┐    │
│  │ Failure                 │ Detection Time → Action        │    │
│  ├─────────────────────────┼───────────────────────────────┤    │
│  │ Governor crash          │ 15s → Tier 2 or 3 kills       │    │
│  │ Monitor crash           │ 15s → Tier 3 kills            │    │
│  │ Both crash              │ 15s → Tier 3 kills via file    │    │
│  │ Redis down              │ 2s → Tier 3 kills via file     │    │
│  │ All three down          │ Manual (file is still there)   │    │
│  │ Watchdog crash          │ systemd restarts in 5s         │    │
│  │ Network partition       │ 15s → Tier 3 kills via file    │    │
│  └─────────────────────────┴───────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 4.6 Effort Estimate

| Task | Effort |
|------|--------|
| Watchdog process implementation | 4 hours |
| systemd service definition | 1 hour |
| Integration testing (kill Tier 1, verify Tier 2/3) | 3 hours |
| Integration testing (kill Redis, verify Tier 3) | 2 hours |
| Documentation | 1 hour |
| **Total** | **~11 hours (1.5 days)** |

---

## 5. HIGH #4: Kelly Fraction Standardization

### 5.1 Problem

**Reference:** CRO Review §4 "HIGH ISSUE #2: Kelly Fraction Inconsistency"

| Document | Value | Interpretation |
|----------|-------|---------------|
| RISK_ARCHITECTURE.md §2.1 | `kelly / 2.0` (dynamic) | Half-Kelly of computed value |
| TSAR_ARCHITECTURE.md | `0.25` (fixed) | Claims "Half-Kelly" but is actually Quarter-Kelly if full Kelly = 0.5 |
| ARCHITECTURE_CONSOLIDATION.md §1.3 | `0.25 (Half-Kelly)` | Canonical — fixed 0.25 |

The dynamic approach (`kelly/2`) adapts to actual edge but produces different values depending on win rate/odds. The fixed approach (`0.25`) is simpler and more conservative.

### 5.2 Solution: Standardize on Fixed 0.25 (Canonical)

**Decision:** Use fixed `kelly_fraction = 0.25` as specified in ARCHITECTURE_CONSOLIDATION.md.

**Rationale:**
- Canonical document specifies 0.25
- More conservative (doesn't increase with better stats)
- Simpler to reason about and audit
- The 2% hard cap still applies on top

**Clarification:** 0.25 is the **fraction of capital to risk per trade**, not the Kelly formula output. It's a fixed position sizing parameter, not a dynamic Kelly calculation. The name "Half-Kelly" is a misnomer in the canonical docs — it should be called "Fixed Fractional (0.25)" or "Quarter-Kelly" for clarity.

### 5.3 Updated Implementation

```python
# risk_governor/position_sizing.py — CORRECTED

def calculate_kelly_risk_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> float:
    """
    Calculate the risk fraction for position sizing.

    CANONICAL VALUE: 0.25 (fixed, from ARCHITECTURE_CONSOLIDATION.md §1.3)

    This is NOT a dynamic Kelly calculation. It's a fixed fractional
    parameter that determines what fraction of capital to risk per trade.

    The 2% hard cap is applied on top of this.

    Note: The Kelly formula is still computed for informational purposes
    (displayed in trade logs) but does NOT affect the sizing decision.
    """
    # Compute Kelly for logging/display only
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        kelly_info = 0.0
    else:
        p = win_rate
        q = 1.0 - p
        b = abs(avg_win / avg_loss)
        kelly_info = (p * b - q) / b
        if kelly_info < 0:
            kelly_info = 0.0

    # CANONICAL: Fixed 0.25 fraction
    CANONICAL_KELLY_FRACTION = 0.25

    # Hard cap: never risk more than 2% of capital per trade
    MAX_RISK_PER_TRADE = 0.02

    # Return the minimum of canonical fraction and hard cap
    return min(CANONICAL_KELLY_FRACTION, MAX_RISK_PER_TRADE), kelly_info
```

### 5.4 All Kelly References to Update

| Location | Current | Updated |
|----------|---------|---------|
| RISK_ARCHITECTURE.md §2.1 `kelly_fraction()` | `half_kelly = kelly / 2.0` | Return fixed `0.25`, keep Kelly calc for info |
| RISK_ARCHITECTURE.md §2.1 `calculate_position_size()` | Uses dynamic Kelly | Use fixed 0.25 |
| RISK_ARCHITECTURE.md §11.2 `RiskConfig` | (not present) | Add `kelly_fraction: float = 0.25` |
| ARCHITECTURE_CONSOLIDATION.md §1.3 | `0.25 (Half-Kelly)` | Add note: "Fixed fraction, not dynamic Kelly/2" |
| Summary table at end of RISK_ARCHITECTURE.md | "Half-Kelly" | "Fixed 0.25" |

### 5.5 Effort Estimate

| Task | Effort |
|------|--------|
| Update position sizing code | 1 hour |
| Update all document references | 1 hour |
| Update config.py | 0.5 hours |
| **Total** | **~2.5 hours (0.5 days)** |

---

## 6. HIGH #5: Recovery Protocol — Regime/Performance Validation

### 6.1 Problem

**Reference:** CRO Review §5 "HIGH ISSUE #3: Recovery Protocol Gaps"

Current recovery protocol (RISK_ARCHITECTURE.md §3.2):
- YELLOW: Auto-resume after 30 min cooldown at 50% sizing
- ORANGE: Manual approval, resume at 25% for 72h
- RED: Manual approval + incident report, resume at 10% for 168h

**Gaps:**
1. No validation that the cause of drawdown is resolved
2. No gradual ramp-up (jumps from 0% to 10%)
3. No performance validation during reduced-sizing period

### 6.2 Solution: Gated Recovery Protocol

```python
# risk_governor/recovery.py
"""
Gated recovery protocol with regime and performance validation.

Recovery from circuit breaker events requires passing through
validation gates before trading can resume at full size.

Gates:
1. Time gate — minimum cooldown period
2. Regime gate — market regime must be favorable
3. Performance gate — must be profitable during reduced period
4. Manual gate — human approval for ORANGE/RED
5. Gradual ramp-up — progressive sizing increase
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from enum import IntEnum

logger = logging.getLogger(__name__)


class RecoveryPhase(IntEnum):
    """Recovery phases with progressive sizing."""
    HALTED = 0          # No trading
    PHASE_1 = 1         # 5% sizing (micro positions)
    PHASE_2 = 2         # 10% sizing
    PHASE_3 = 3         # 25% sizing
    PHASE_4 = 4         # 50% sizing
    FULL = 5            # 100% sizing (recovered)


@dataclass
class RecoveryGate:
    """A single recovery gate that must pass."""
    name: str
    passed: bool
    reason: str
    checked_at: str


@dataclass
class RecoveryState:
    """Current recovery state."""
    risk_level: int                 # Original circuit breaker level
    phase: RecoveryPhase
    phase_started: str              # ISO timestamp
    gates: list[dict]               # Gate results
    sizing_multiplier: float        # Current sizing multiplier
    can_trade: bool
    next_gate_check: str            # When to re-evaluate
    total_recovery_pnl: float       # P&L since recovery started
    total_recovery_trades: int      # Trades since recovery started
    recovery_win_rate: float        # Win rate during recovery


class GatedRecoveryProtocol:
    """
    Recovery protocol with validation gates.

    Recovery phases for each risk level:

    YELLOW (Level 1):
        Phase 1: 50% sizing for 4h → requires no gates (auto)
        Full: Resume normal

    ORANGE (Level 2):
        Phase 1: 10% sizing for 24h → gate: regime check
        Phase 2: 25% sizing for 48h → gate: positive P&L
        Phase 3: 50% sizing for 48h → gate: win rate > 40%
        Full: Resume normal

    RED (Level 3):
        Phase 1: 5% sizing for 24h → gate: regime check + manual approval
        Phase 2: 10% sizing for 48h → gate: positive P&L
        Phase 3: 25% sizing for 72h → gate: win rate > 40%
        Phase 4: 50% sizing for 72h → gate: Sharpe > 0
        Full: Resume normal (with incident report review)
    """

    # Phase definitions per risk level
    RECOVERY_PHASES = {
        1: [  # YELLOW
            {'phase': RecoveryPhase.PHASE_4, 'duration_hours': 4,
             'sizing': 0.50, 'gates': []},
            {'phase': RecoveryPhase.FULL, 'duration_hours': 0,
             'sizing': 1.0, 'gates': []},
        ],
        2: [  # ORANGE
            {'phase': RecoveryPhase.PHASE_2, 'duration_hours': 24,
             'sizing': 0.10, 'gates': ['regime_check']},
            {'phase': RecoveryPhase.PHASE_3, 'duration_hours': 48,
             'sizing': 0.25, 'gates': ['positive_pnl']},
            {'phase': RecoveryPhase.PHASE_4, 'duration_hours': 48,
             'sizing': 0.50, 'gates': ['win_rate_above_40']},
            {'phase': RecoveryPhase.FULL, 'duration_hours': 0,
             'sizing': 1.0, 'gates': []},
        ],
        3: [  # RED
            {'phase': RecoveryPhase.PHASE_1, 'duration_hours': 24,
             'sizing': 0.05, 'gates': ['regime_check', 'manual_approval']},
            {'phase': RecoveryPhase.PHASE_2, 'duration_hours': 48,
             'sizing': 0.10, 'gates': ['positive_pnl']},
            {'phase': RecoveryPhase.PHASE_3, 'duration_hours': 72,
             'sizing': 0.25, 'gates': ['win_rate_above_40']},
            {'phase': RecoveryPhase.PHASE_4, 'duration_hours': 72,
             'sizing': 0.50, 'gates': ['sharpe_above_zero']},
            {'phase': RecoveryPhase.FULL, 'duration_hours': 0,
             'sizing': 1.0, 'gates': ['incident_report_reviewed']},
        ],
    }

    def __init__(self, redis_client):
        self.redis = redis_client

    def start_recovery(self, risk_level: int) -> RecoveryState:
        """
        Start recovery after a circuit breaker event.
        Called when the operator approves recovery (or auto-resume for YELLOW).
        """
        phases = self.RECOVERY_PHASES.get(risk_level, [])
        if not phases:
            raise ValueError(f"Invalid risk level: {risk_level}")

        first_phase = phases[0]
        now = datetime.now(timezone.utc)

        state = RecoveryState(
            risk_level=risk_level,
            phase=first_phase['phase'],
            phase_started=now.isoformat(),
            gates=[],
            sizing_multiplier=first_phase['sizing'],
            can_trade=True,
            next_gate_check=(now + timedelta(hours=first_phase['duration_hours'])).isoformat(),
            total_recovery_pnl=0.0,
            total_recovery_trades=0,
            recovery_win_rate=0.0,
        )

        # Persist to Redis
        self._save_state(state)
        logger.info(
            f"Recovery started for level {risk_level}: "
            f"Phase {state.phase}, sizing {state.sizing_multiplier:.0%}"
        )

        return state

    def check_recovery_progress(self) -> RecoveryState:
        """
        Check if recovery can advance to the next phase.
        Called periodically (every 5 minutes during recovery).
        """
        state = self._load_state()
        if not state or state.phase == RecoveryPhase.FULL:
            return state

        now = datetime.now(timezone.utc)
        next_check = datetime.fromisoformat(state.next_gate_check)

        if now < next_check:
            return state  # Not time to check yet

        # Get the current phase definition
        phases = self.RECOVERY_PHASES[state.risk_level]
        current_phase_def = None
        next_phase_def = None

        for i, p in enumerate(phases):
            if p['phase'] == state.phase:
                current_phase_def = p
                if i + 1 < len(phases):
                    next_phase_def = phases[i + 1]
                break

        if not current_phase_def or not next_phase_def:
            return state

        # Check gates for current phase
        gates_passed = self._check_gates(
            current_phase_def['gates'], state
        )

        if gates_passed:
            # Advance to next phase
            state.phase = next_phase_def['phase']
            state.phase_started = now.isoformat()
            state.sizing_multiplier = next_phase_def['sizing']
            state.next_gate_check = (
                now + timedelta(hours=next_phase_def['duration_hours'])
            ).isoformat()

            logger.info(
                f"Recovery advanced to Phase {state.phase}: "
                f"sizing {state.sizing_multiplier:.0%}"
            )

            if state.phase == RecoveryPhase.FULL:
                state.can_trade = True
                logger.info("Recovery COMPLETE — full trading resumed")
        else:
            # Stay in current phase, check again later
            state.next_gate_check = (
                now + timedelta(hours=1)  # Re-check in 1 hour
            ).isoformat()
            logger.info(f"Recovery gates not passed, re-checking in 1h")

        self._save_state(state)
        return state

    def _check_gates(self, gate_names: list[str], state: RecoveryState) -> bool:
        """Check all required gates for phase advancement."""
        for gate_name in gate_names:
            gate_fn = self.GATE_FUNCTIONS.get(gate_name)
            if not gate_fn:
                logger.error(f"Unknown gate: {gate_name}")
                return False

            passed, reason = gate_fn(self, state)
            logger.info(f"Gate '{gate_name}': {'PASSED' if passed else 'FAILED'} — {reason}")

            if not passed:
                return False

        return True

    # ── Gate implementations ──

    def _gate_regime_check(self, state: RecoveryState) -> tuple[bool, str]:
        """
        Gate: Market regime must be favorable.
        Checks if the regime has changed from when the drawdown occurred.
        """
        current_regime = self.redis.get('trading:state:regime:current')
        drawdown_regime = self.redis.get('risk:drawdown_regime')

        if not current_regime:
            return False, "No regime data available"

        # If regime changed from the drawdown regime, it's favorable
        # (the conditions that caused the loss may have changed)
        if drawdown_regime and current_regime != drawdown_regime:
            return True, f"Regime changed: {drawdown_regime} → {current_regime}"

        # If same regime but it's TRENDING_UP, also favorable
        if current_regime == 'TRENDING_UP':
            return True, "Favorable trending regime"

        return False, f"Regime unchanged ({current_regime}), may still be unfavorable"

    def _gate_positive_pnl(self, state: RecoveryState) -> tuple[bool, str]:
        """
        Gate: Must have positive P&L during recovery period.
        """
        pnl = state.total_recovery_pnl
        if pnl > 0:
            return True, f"Recovery P&L positive: ${pnl:.2f}"
        return False, f"Recovery P&L negative: ${pnl:.2f}"

    def _gate_win_rate_above_40(self, state: RecoveryState) -> tuple[bool, str]:
        """
        Gate: Win rate during recovery must be above 40%.
        Requires minimum 5 trades for statistical significance.
        """
        if state.total_recovery_trades < 5:
            return False, f"Need 5+ trades for gate (have {state.total_recovery_trades})"

        if state.recovery_win_rate >= 0.40:
            return True, f"Win rate {state.recovery_win_rate:.0%} >= 40%"
        return False, f"Win rate {state.recovery_win_rate:.0%} < 40%"

    def _gate_sharpe_above_zero(self, state: RecoveryState) -> tuple[bool, str]:
        """
        Gate: Sharpe ratio during recovery must be positive.
        """
        sharpe = self._calculate_recovery_sharpe()
        if sharpe > 0:
            return True, f"Recovery Sharpe: {sharpe:.2f}"
        return False, f"Recovery Sharpe: {sharpe:.2f} (must be > 0)"

    def _gate_manual_approval(self, state: RecoveryState) -> tuple[bool, str]:
        """
        Gate: Requires explicit operator approval.
        """
        approved = self.redis.get('risk:recovery_manual_approved')
        if approved:
            operator = self.redis.get('risk:recovery_approver') or 'unknown'
            return True, f"Approved by {operator}"
        return False, "Waiting for operator approval"

    def _gate_incident_report_reviewed(self, state: RecoveryState) -> tuple[bool, str]:
        """
        Gate: Incident report must be reviewed and signed off.
        """
        reviewed = self.redis.get('risk:incident_report_reviewed')
        if reviewed:
            return True, "Incident report reviewed"
        return False, "Incident report not yet reviewed"

    def _calculate_recovery_sharpe(self) -> float:
        """Calculate Sharpe ratio from recovery period trades."""
        raw = self.redis.lrange('risk:recovery_trades', 0, -1)
        if len(raw) < 5:
            return -1.0

        import numpy as np
        returns = [json.loads(t)['pnl_pct'] for t in raw]
        if np.std(returns) == 0:
            return 0.0
        return np.mean(returns) / np.std(returns) * np.sqrt(252)

    # Gate function registry
    GATE_FUNCTIONS = {
        'regime_check': _gate_regime_check,
        'positive_pnl': _gate_positive_pnl,
        'win_rate_above_40': _gate_win_rate_above_40,
        'sharpe_above_zero': _gate_sharpe_above_zero,
        'manual_approval': _gate_manual_approval,
        'incident_report_reviewed': _gate_incident_report_reviewed,
    }

    def _save_state(self, state: RecoveryState) -> None:
        """Persist recovery state to Redis."""
        from dataclasses import asdict
        self.redis.set(
            'risk:recovery_state',
            json.dumps(asdict(state), default=str)
        )

    def _load_state(self) -> RecoveryState | None:
        """Load recovery state from Redis."""
        data = self.redis.get('risk:recovery_state')
        if not data:
            return None
        d = json.loads(data)
        d['phase'] = RecoveryPhase(d['phase'])
        return RecoveryState(**d)
```

### 6.3 Recovery Phase Diagram

```
ORANGE Recovery:
  ──────────────────────────────────────────────────────────────
  Phase 1 (10%)    Phase 2 (25%)    Phase 3 (50%)    FULL (100%)
  ├──── 24h ───────├──── 48h ───────├──── 48h ───────┤
  │ regime_check   │ positive_pnl   │ win_rate>40%   │
  └────────────────┴────────────────┴────────────────┘

RED Recovery:
  ──────────────────────────────────────────────────────────────────────
  Phase 1 (5%)     Phase 2 (10%)    Phase 3 (25%)    Phase 4 (50%)    FULL
  ├──── 24h ───────├──── 48h ───────├──── 72h ───────├──── 72h ───────┤
  │ regime_check   │ positive_pnl   │ win_rate>40%   │ sharpe>0       │
  │ + manual_ok    │                │                │ + report_ok    │
  └────────────────┴────────────────┴────────────────┴────────────────┘
```

### 6.4 Effort Estimate

| Task | Effort |
|------|--------|
| `GatedRecoveryProtocol` implementation | 4 hours |
| Gate function implementations | 3 hours |
| Integration with `DrawdownCircuitBreaker` | 2 hours |
| Unit tests | 2 hours |
| **Total** | **~11 hours (1.5 days)** |

---

## 7. HIGH #6: Negative Balance Protection (OANDA Forex)

### 7.1 Problem

**Reference:** CRO Review §6 "HIGH ISSUE #4: Can the System Lose More Than Deposited?"

The architecture supports leveraged products via OANDA (forex, gold). With leverage:
- Stop-losses can gap in flash crashes
- 150% gross exposure × -30% market move = -45% portfolio loss
- Exchange auto-liquidation may not trigger before negative balance
- OANDA offers up to 50:1 leverage on major forex pairs

**Current gap:** No explicit negative balance protection in the architecture.

### 7.2 Solution: Multi-Layer Negative Balance Protection

```python
# risk_governor/negative_balance.py
"""
Negative balance protection for leveraged products.

Prevents the account from going negative on leveraged positions
(forex, futures, CFDs). Multiple layers of protection:

1. Position-level: Max loss per position with gap risk
2. Portfolio-level: Max total loss with correlation
3. Exchange-level: Pre-liquidation buffer
4. Emergency: Automatic position reduction before margin call
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LeverageLimits:
    """Leverage-specific risk limits."""

    # Maximum leverage by asset class
    MAX_LEVERAGE = {
        'forex_major': 20,       # 20:1 (conservative vs OANDA's 50:1)
        'forex_minor': 10,       # 10:1
        'forex_exotic': 5,       # 5:1
        'gold': 10,              # 10:1
        'crypto_perp': 3,        # 3:1 (conservative)
        'equity': 1,             # No leverage (spot only)
    }

    # Gap risk multiplier: assume worst-case slippage beyond stop
    GAP_RISK_MULTIPLIER = {
        'forex_major': 1.5,      # 50% gap beyond stop
        'forex_minor': 2.0,      # 100% gap
        'forex_exotic': 3.0,     # 200% gap
        'gold': 1.5,             # 50% gap
        'crypto_perp': 2.0,      # 100% gap (flash crashes)
        'equity': 1.2,           # 20% gap
    }

    # Margin call buffer: close positions before exchange margin call
    MARGIN_CALL_BUFFER_PCT = 0.20  # Close when margin usage hits 80%

    # Maximum account utilization (margin used / equity)
    MAX_MARGIN_UTILIZATION = 0.60  # Never use more than 60% of margin

    # Pre-liquidation threshold (as % of maintenance margin)
    PRE_LIQUIDATION_BUFFER_PCT = 0.30  # Act at 70% of maintenance margin


class NegativeBalanceProtection:
    """
    Multi-layer negative balance protection for leveraged products.

    Layer 1: Position sizing accounts for gap risk
    Layer 2: Portfolio-level max loss limit
    Layer 3: Margin utilization monitoring
    Layer 4: Emergency reduction before margin call
    """

    def __init__(self, redis_client, config: LeverageLimits = None):
        self.redis = redis_client
        self.config = config or LeverageLimits()

    def check_position_size_with_gap_risk(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_price: float,
        quantity: float,
        asset_class: str,
        account_equity: float,
    ) -> tuple[bool, float, str]:
        """
        Layer 1: Validate position size accounts for gap risk.

        Even with a stop-loss, the actual exit may be worse than the stop
        price in a fast market. This check ensures the worst-case loss
        (including gap) doesn't exceed acceptable limits.

        Returns:
            (approved, adjusted_quantity, reason)
        """
        # Get gap risk multiplier for asset class
        gap_mult = self.config.GAP_RISK_MULTIPLIER.get(asset_class, 2.0)

        # Calculate worst-case loss per unit
        stop_distance = abs(entry_price - stop_price)
        worst_case_distance = stop_distance * gap_mult
        worst_case_loss_per_unit = worst_case_distance

        # Total worst-case loss
        total_worst_case_loss = worst_case_loss_per_unit * quantity

        # Maximum acceptable loss per position: 2% of equity (hard cap)
        max_loss_per_position = account_equity * 0.02

        if total_worst_case_loss > max_loss_per_position:
            # Reduce quantity to fit within limit
            adjusted_qty = int(max_loss_per_position / worst_case_loss_per_unit)
            return False, adjusted_qty, (
                f"GAP RISK: Worst-case loss ${total_worst_case_loss:.2f} "
                f"(with {gap_mult}x gap) exceeds 2% limit ${max_loss_per_position:.2f}. "
                f"Reduced qty from {quantity} to {adjusted_qty}."
            )

        return True, quantity, "Gap risk check passed"

    def check_portfolio_max_loss(self, positions: list[dict]) -> tuple[bool, str]:
        """
        Layer 2: Calculate maximum portfolio loss including correlated gaps.

        Sums worst-case loss across all positions, accounting for:
        - Gap risk per asset class
        - Correlation (correlated positions may all gap simultaneously)
        """
        total_worst_case = 0.0

        for pos in positions:
            asset_class = pos.get('asset_class', 'equity')
            gap_mult = self.config.GAP_RISK_MULTIPLIER.get(asset_class, 2.0)
            stop_dist = abs(pos['entry_price'] - pos['stop_price'])
            worst_case = stop_dist * gap_mult * abs(pos['quantity'])
            total_worst_case += worst_case

        # Get account equity
        equity = float(self.redis.get('portfolio:equity') or 0)
        if equity <= 0:
            return False, "Cannot determine account equity"

        max_portfolio_loss = equity * 0.05  # 5% max portfolio loss (canonical)

        if total_worst_case > max_portfolio_loss:
            return False, (
                f"PORTFOLIO MAX LOSS: Worst-case ${total_worst_case:.2f} "
                f"exceeds 5% limit ${max_portfolio_loss:.2f}. "
                f"Reduce positions."
            )

        return True, (
            f"Portfolio worst-case loss: ${total_worst_case:.2f} "
            f"({total_worst_case/equity:.1%} of equity)"
        )

    def check_margin_utilization(
        self,
        margin_used: float,
        equity: float,
    ) -> tuple[bool, str]:
        """
        Layer 3: Monitor margin utilization.

        If margin usage exceeds 60% of equity, halt new positions
        and start reducing existing ones.
        """
        if equity <= 0:
            return False, "Zero or negative equity"

        utilization = margin_used / equity

        if utilization > self.config.MAX_MARGIN_UTILIZATION:
            return False, (
                f"MARGIN LIMIT: Utilization {utilization:.0%} exceeds "
                f"{self.config.MAX_MARGIN_UTILIZATION:.0%} limit. "
                f"Margin used: ${margin_used:.2f}, Equity: ${equity:.2f}. "
                f"Halt new positions and reduce existing."
            )

        return True, f"Margin utilization: {utilization:.0%}"

    def check_pre_liquidation(
        self,
        margin_used: float,
        maintenance_margin: float,
        equity: float,
    ) -> tuple[bool, str]:
        """
        Layer 4: Emergency reduction before exchange auto-liquidation.

        OANDA and other brokers auto-liquidate when margin drops below
        maintenance margin. This check triggers reduction BEFORE that point.
        """
        if maintenance_margin <= 0:
            return True, "No maintenance margin (spot)"

        margin_ratio = margin_used / maintenance_margin
        threshold = 1.0 - self.config.PRE_LIQUIDATION_BUFFER_PCT

        if margin_ratio > threshold:
            return False, (
                f"PRE-LIQUIDATION: Margin ratio {margin_ratio:.2f} approaching "
                f"maintenance margin. Reducing positions to stay above "
                f"{self.config.PRE_LIQUIDATION_BUFFER_PCT:.0%} buffer."
            )

        return True, f"Margin ratio: {margin_ratio:.2f}"

    def calculate_max_position_size_for_leverage(
        self,
        account_equity: float,
        entry_price: float,
        stop_price: float,
        asset_class: str,
        leverage_available: float,
    ) -> float:
        """
        Calculate maximum position size that respects both:
        1. Our risk limits (2% per trade)
        2. Leverage limits (asset class maximum)
        3. Gap risk (worst-case scenario)
        """
        # Our risk limit
        max_risk_amount = account_equity * 0.02  # 2% canonical
        stop_distance = abs(entry_price - stop_price)
        gap_mult = self.config.GAP_RISK_MULTIPLIER.get(asset_class, 2.0)
        worst_case_per_unit = stop_distance * gap_mult

        risk_based_qty = max_risk_amount / worst_case_per_unit if worst_case_per_unit > 0 else 0

        # Leverage limit
        max_leverage = self.config.MAX_LEVERAGE.get(asset_class, 1)
        effective_leverage = min(leverage_available, max_leverage)
        max_position_value = account_equity * effective_leverage
        leverage_based_qty = max_position_value / entry_price if entry_price > 0 else 0

        # Take the minimum
        return min(risk_based_qty, leverage_based_qty)
```

### 7.3 OANDA-Specific Integration

```python
# risk_governor/oanda_protection.py
"""
OANDA-specific negative balance protection.

OANDA offers up to 50:1 leverage on major forex pairs.
Our limits are more conservative (20:1 max).
"""

class OANDANegativeBalanceProtection:
    """OANDA-specific protections."""

    # OANDA margin call level (platform default)
    OANDA_MARGIN_CLOSEOUT_LEVEL = 0.50  # 50% of margin used

    # Our safety buffer above OANDA's level
    OUR_SAFETY_LEVEL = 0.35  # Act at 35% margin usage (15% buffer)

    @staticmethod
    def check_oanda_margin(
        margin_used: float,
        nav: float,  # Net Asset Value (OANDA term for equity)
    ) -> tuple[bool, str]:
        """
        Check margin level against OANDA's closeout threshold.

        OANDA closes all positions when margin rate drops below 50%.
        We act at 35% to have a safety buffer.
        """
        if nav <= 0:
            return False, "NAV is zero or negative"

        margin_rate = margin_used / nav

        if margin_rate > OANDANegativeBalanceProtection.OUR_SAFETY_LEVEL:
            return False, (
                f"OANDA MARGIN WARNING: Margin rate {margin_rate:.0%} "
                f"> safety level {OANDANegativeBalanceProtection.OUR_SAFETY_LEVEL:.0%}. "
                f"OANDA auto-closeout at {OANDANegativeBalanceProtection.OANDA_MARGIN_CLOSEOUT_LEVEL:.0%}. "
                f"Reducing positions immediately."
            )

        return True, f"OANDA margin rate: {margin_rate:.0%}"
```

### 7.4 Integration Points

| Component | Integration |
|-----------|-------------|
| RISK_ARCHITECTURE.md §2.1 `calculate_position_size()` | Add gap risk check before final sizing |
| RISK_ARCHITECTURE.md §2.2 `check_position_limits()` | Add margin utilization check |
| Periodic check (§9.4) | Add margin monitoring every 60s |
| Kill switch triggers (§7.2) | Add margin call proximity trigger |
| Veto Protocol Gate 8 | Add negative balance check |

### 7.5 Effort Estimate

| Task | Effort |
|------|--------|
| `NegativeBalanceProtection` implementation | 3 hours |
| OANDA-specific integration | 2 hours |
| Integration with position sizing | 2 hours |
| Margin monitoring in periodic check | 1 hour |
| Unit tests | 2 hours |
| **Total** | **~10 hours (1.5 days)** |

---

## 8. HIGH #7: Stress Testing Specification

### 8.1 Problem

**Reference:** CRO Review §6 "MEDIUM ISSUE #5: No Stress Testing Specification"

The architecture mentions VaR and stress testing but defers to Level 2+. For Day-1, there should be at minimum:
- Backtest of the risk engine against historical crash events
- Maximum historical drawdown calculation
- A "break the system" test

### 8.2 Stress Testing Specification

```python
# tests/stress/test_risk_engine_stress.py
"""
Stress test specification for the TSAR Risk Engine.

Tests the risk engine against historical crash scenarios and
synthetic extreme events to verify:
1. Kill switch activates at correct thresholds
2. Circuit breakers trigger at correct levels
3. Position sizing reduces appropriately
4. Negative balance protection works
5. Recovery protocol functions correctly

Historical scenarios:
- March 2020 COVID crash (BTC -50%, equities -34%)
- May 2021 crypto crash (BTC -53% in 7 days)
- November 2022 FTX collapse (BTC -25%, SOL -60%)
- January 2015 CHF flash crash (EUR/CHF -30% in minutes)
- March 2023 SVB collapse (banking sector -20%)
"""

import pytest
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Generator


@dataclass
class StressScenario:
    """A historical or synthetic stress scenario."""
    name: str
    description: str
    asset_moves: dict[str, float]    # symbol → % move
    duration_hours: float            # How fast the move happened
    gap_factor: float                # Stop-loss gap beyond trigger
    expected_kill_switch: bool       # Should kill switch fire?
    expected_circuit_breaker: int    # Expected risk level (0-3)


# ── Historical Scenarios ──

SCENARIOS = [
    StressScenario(
        name="march_2020_covid",
        description="COVID crash: BTC -50% in 24h, equities -34% in 4 weeks",
        asset_moves={
            'BTC/USD': -0.50,
            'ETH/USD': -0.55,
            'AAPL': -0.25,
            'SPY': -0.34,
        },
        duration_hours=24,
        gap_factor=1.3,  # 30% gap beyond stop
        expected_kill_switch=True,
        expected_circuit_breaker=3,  # RED
    ),
    StressScenario(
        name="may_2021_crypto_crash",
        description="May 2021: BTC -53% from ATH in 7 days, Elon tweets + China ban",
        asset_moves={
            'BTC/USD': -0.53,
            'ETH/USD': -0.60,
            'DOGE/USD': -0.70,
            'SOL/USD': -0.65,
        },
        duration_hours=168,  # 7 days
        gap_factor=1.5,
        expected_kill_switch=True,
        expected_circuit_breaker=3,
    ),
    StressScenario(
        name="nov_2022_ftx",
        description="FTX collapse: BTC -25%, SOL -60%, contagion across crypto",
        asset_moves={
            'BTC/USD': -0.25,
            'SOL/USD': -0.60,
            'ETH/USD': -0.30,
            'FTT/USD': -0.95,
        },
        duration_hours=72,
        gap_factor=2.0,  # Extreme gap risk during exchange collapse
        expected_kill_switch=True,
        expected_circuit_breaker=3,
    ),
    StressScenario(
        name="jan_2015_chf",
        description="CHF flash crash: EUR/CHF -30% in minutes, many brokers insolvent",
        asset_moves={
            'EUR/CHF': -0.30,
            'USD/CHF': -0.25,
        },
        duration_hours=0.1,  # Minutes
        gap_factor=3.0,  # Extreme gap — stops were meaningless
        expected_kill_switch=True,
        expected_circuit_breaker=3,
    ),
    StressScenario(
        name="march_2023_svb",
        description="SVB collapse: banking sector -20%, flight to safety",
        asset_moves={
            'XLF': -0.20,
            'AAPL': -0.05,
            'BTC/USD': +0.15,  # Flight to crypto
            'GLD': +0.05,
        },
        duration_hours=48,
        gap_factor=1.2,
        expected_kill_switch=False,  # Diversified portfolio survives
        expected_circuit_breaker=2,  # ORANGE at most
    ),
    StressScenario(
        name="correlation_spike",
        description="All correlations go to 1.0 — systematic risk-off event",
        asset_moves={
            'BTC/USD': -0.20,
            'ETH/USD': -0.20,
            'SOL/USD': -0.20,
            'AAPL': -0.15,
            'SPY': -0.15,
            'GLD': -0.10,  # Even gold drops
        },
        duration_hours=4,
        gap_factor=1.5,
        expected_kill_switch=True,
        expected_circuit_breaker=3,
    ),
]


class RiskEngineStressTest:
    """
    Stress test harness for the Risk Engine.

    Simulates historical scenarios against the risk engine to verify
    correct behavior.
    """

    def __init__(self, risk_config, redis_client):
        self.config = risk_config
        self.redis = redis_client

    def run_scenario(self, scenario: StressScenario, portfolio: dict) -> dict:
        """
        Run a single stress scenario against the risk engine.

        Args:
            scenario: The stress scenario to simulate
            portfolio: Initial portfolio state

        Returns:
            Results dict with:
            - kill_switch_activated: bool
            - max_drawdown: float
            - final_portfolio_value: float
            - positions_at_end: int
            - circuit_breaker_level: int
            - time_to_kill_switch: float (hours)
            - survived: bool
        """
        from risk_governor.kill_switch import KillSwitch
        from risk_governor.drawdown import DrawdownCircuitBreaker
        from risk_governor.position_sizing import calculate_position_size

        results = {
            'scenario': scenario.name,
            'kill_switch_activated': False,
            'max_drawdown': 0.0,
            'initial_portfolio_value': portfolio['portfolio_value'],
            'final_portfolio_value': portfolio['portfolio_value'],
            'positions_at_end': len(portfolio.get('positions', [])),
            'circuit_breaker_level': 0,
            'time_to_kill_switch': None,
            'survived': True,
            'violations': [],
        }

        # Simulate the price moves
        current_value = portfolio['portfolio_value']
        peak_value = current_value
        positions = portfolio.get('positions', [])

        # Apply moves progressively
        steps = max(1, int(scenario.duration_hours / 0.5))  # 30-min steps
        for step in range(steps):
            progress = (step + 1) / steps

            for pos in positions:
                symbol = pos['symbol']
                if symbol not in scenario.asset_moves:
                    continue

                move = scenario.asset_moves[symbol] * progress
                position_pnl = pos['value'] * move
                current_value += position_pnl

            # Track drawdown
            peak_value = max(peak_value, current_value)
            drawdown = (current_value - peak_value) / peak_value
            results['max_drawdown'] = min(results['max_drawdown'], drawdown)

            # Check circuit breaker
            if drawdown <= self.config.daily_loss_kill:
                results['circuit_breaker_level'] = 3
                results['kill_switch_activated'] = True
                results['time_to_kill_switch'] = scenario.duration_hours * progress
                results['final_portfolio_value'] = current_value
                break
            elif drawdown <= self.config.daily_loss_halt:
                results['circuit_breaker_level'] = max(results['circuit_breaker_level'], 2)
            elif drawdown <= self.config.daily_loss_warn:
                results['circuit_breaker_level'] = max(results['circuit_breaker_level'], 1)

        results['final_portfolio_value'] = current_value
        results['survived'] = current_value > 0

        return results

    def run_all_scenarios(self, portfolio: dict) -> list[dict]:
        """Run all stress scenarios and return results."""
        results = []
        for scenario in SCENARIOS:
            result = self.run_scenario(scenario, portfolio)
            results.append(result)
        return results

    def generate_report(self, results: list[dict]) -> str:
        """Generate a human-readable stress test report."""
        report = ["=" * 60]
        report.append("TSAR RISK ENGINE STRESS TEST REPORT")
        report.append("=" * 60)
        report.append("")

        passed = 0
        failed = 0

        for r in results:
            scenario = next(s for s in SCENARIOS if s.name == r['scenario'])
            status = "✅ PASS" if r['survived'] else "❌ FAIL"
            kill = "🔴 YES" if r['kill_switch_activated'] else "🟢 NO"

            if r['kill_switch_activated'] == scenario.expected_kill_switch:
                passed += 1
            else:
                failed += 1

            report.append(f"Scenario: {scenario.name}")
            report.append(f"  Description: {scenario.description}")
            report.append(f"  Status: {status}")
            report.append(f"  Kill Switch: {kill}")
            report.append(f"  Max Drawdown: {r['max_drawdown']:.1%}")
            report.append(f"  Circuit Breaker Level: {r['circuit_breaker_level']}")
            report.append(f"  Final Value: ${r['final_portfolio_value']:,.2f}")
            if r['time_to_kill_switch']:
                report.append(f"  Time to Kill: {r['time_to_kill_switch']:.1f}h")
            report.append("")

        report.append("=" * 60)
        report.append(f"TOTAL: {passed} passed, {failed} failed out of {len(results)}")
        report.append("=" * 60)

        return "\n".join(report)
```

### 8.3 Day-1 Stress Test Checklist

Before live capital deployment, the following must pass:

| # | Test | Expected Result | Priority |
|---|------|----------------|----------|
| 1 | **Kill switch threshold test** | Kill switch fires at exactly -2% daily loss | P0 |
| 2 | **Total drawdown test** | Kill switch fires at exactly -5% from HWM | P0 |
| 3 | **Flash crash simulation** | Positions flattened within 5s of trigger | P0 |
| 4 | **Redis failure during position** | Kill switch activates via file fallback | P0 |
| 5 | **Watchdog Tier 3 test** | Watchdog detects stale Tier 1/2 heartbeats | P0 |
| 6 | **Gap risk test** | Position sizing accounts for worst-case gaps | P1 |
| 7 | **Correlation spike test** | All-correlated scenario triggers regime change | P1 |
| 8 | **Recovery protocol test** | Gated recovery requires positive P&L to advance | P1 |
| 9 | **Margin utilization test** | New positions rejected at 60% margin usage | P1 |
| 10 | **Manual kill test** | File-based manual kill works without Redis | P0 |
| 11 | **Maximum loss audit** | Worst-case loss calculated and documented | P0 |
| 12 | **Historical backtest** | Risk engine against March 2020, May 2021 data | P1 |

### 8.4 Effort Estimate

| Task | Effort |
|------|--------|
| Stress scenario definitions | 2 hours |
| `RiskEngineStressTest` harness | 4 hours |
| Historical data preparation | 3 hours |
| Running all 12 tests | 3 hours |
| Report generation and documentation | 2 hours |
| **Total** | **~14 hours (2 days)** |

---

## 9. HIGH #8: Day-1 Resource Limits (Process-Level)

### 9.1 Problem

**Reference:** FIX_05 (Resource Limits), CRO Review §7 "MEDIUM ISSUE #6"

FIX_05 specifies a comprehensive resource limit system with Docker, Prometheus, and cAdvisor integration. But for Day-1 (no Docker, running as a bare Python process), there are no resource limits at all.

### 9.2 Solution: Process-Level Resource Limits (No Docker Required)

Use Python's `resource` module and `psutil` for process-level enforcement without Docker.

```python
# risk_governor/process_limits.py
"""
Day-1 process-level resource limits.

No Docker required. Uses Python's built-in `resource` module
and `psutil` for process-level enforcement.

This is a simplified version of FIX_05 for Day-1 deployment.
It provides:
- Memory limits (per-process RSS)
- CPU time limits (per-check)
- Wall-clock timeouts (per-operation)
- File descriptor limits
- No network tracking (requires exchange client integration)

For full resource limits (Docker, Prometheus, circuit breakers),
see FIX_05.
"""

import os
import signal
import time
import logging
import resource
import threading
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class ProcessResourceLimits:
    """
    Process-level resource limits for Day-1 deployment.

    Sets hard limits on the Python process itself using
    the `resource` module (POSIX only).
    """

    # ── Memory ──
    MAX_RSS_MB = 512  # Maximum resident set size

    # ── CPU ──
    MAX_CPU_SECONDS = 60  # Maximum CPU time per check

    # ── File descriptors ──
    MAX_OPEN_FILES = 256  # Maximum open file descriptors

    # ── Wall-clock timeouts per operation ──
    TIMEOUTS = {
        'risk_check': 1.0,          # Risk Governor check (must be fast)
        'position_sizing': 0.5,     # Position sizing calculation
        'drawdown_check': 0.5,      # Drawdown evaluation
        'correlation_check': 2.0,   # Correlation matrix (can be slow)
        'exchange_order': 15.0,     # Exchange order placement
        'exchange_query': 10.0,     # Exchange data query
        'redis_operation': 2.0,     # Redis read/write
        'kill_switch': 0.1,         # Kill switch check (must be instant)
    }

    @classmethod
    def apply_process_limits(cls) -> None:
        """
        Apply hard resource limits to the current process.
        Call once at startup.
        """
        # Memory limit (RSS)
        max_rss_bytes = cls.MAX_RSS_MB * 1024 * 1024
        try:
            resource.setrlimit(
                resource.RLIMIT_AS,
                (max_rss_bytes, max_rss_bytes)
            )
            logger.info(f"Process RSS limit set to {cls.MAX_RSS_MB}MB")
        except (ValueError, resource.error) as e:
            logger.warning(f"Could not set RSS limit: {e}")

        # CPU time limit
        try:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (cls.MAX_CPU_SECONDS, cls.MAX_CPU_SECONDS)
            )
            logger.info(f"Process CPU limit set to {cls.MAX_CPU_SECONDS}s")
        except (ValueError, resource.error) as e:
            logger.warning(f"Could not set CPU limit: {e}")

        # File descriptor limit
        try:
            resource.setrlimit(
                resource.RLIMIT_NOFILE,
                (cls.MAX_OPEN_FILES, cls.MAX_OPEN_FILES)
            )
            logger.info(f"File descriptor limit set to {cls.MAX_OPEN_FILES}")
        except (ValueError, resource.error) as e:
            logger.warning(f"Could not set FD limit: {e}")

        # Core dump disabled (security)
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, resource.error):
            pass

    @classmethod
    @contextmanager
    def timeout(cls, operation: str, timeout_seconds: float = None):
        """
        Context manager for wall-clock timeout on an operation.

        Usage:
            with ProcessResourceLimits.timeout('risk_check'):
                result = do_risk_check()

        Raises TimeoutError if operation exceeds the limit.
        """
        if timeout_seconds is None:
            timeout_seconds = cls.TIMEOUTS.get(operation, 10.0)

        # Use signal-based timeout (Unix only)
        def timeout_handler(signum, frame):
            raise TimeoutError(
                f"Operation '{operation}' exceeded {timeout_seconds}s timeout"
            )

        # Set the alarm
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)

        try:
            yield
        finally:
            # Cancel the alarm
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)


class MemoryMonitor:
    """
    Lightweight memory monitor for Day-1.

    Checks process memory usage and warns if approaching limits.
    Runs as a background thread.
    """

    CHECK_INTERVAL = 30  # seconds
    WARN_THRESHOLD_MB = 400  # Warn at 400MB (limit is 512MB)
    CRITICAL_THRESHOLD_MB = 480  # Critical at 480MB

    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            import psutil
            process = psutil.Process(os.getpid())
        except ImportError:
            logger.warning("psutil not available, memory monitoring disabled")
            return

        while not self._stop.is_set():
            try:
                mem_mb = process.memory_info().rss / (1024 * 1024)

                if mem_mb > self.CRITICAL_THRESHOLD_MB:
                    logger.critical(
                        f"MEMORY CRITICAL: {mem_mb:.0f}MB "
                        f"(limit: {ProcessResourceLimits.MAX_RSS_MB}MB)"
                    )
                elif mem_mb > self.WARN_THRESHOLD_MB:
                    logger.warning(
                        f"Memory warning: {mem_mb:.0f}MB "
                        f"(limit: {ProcessResourceLimits.MAX_RSS_MB}MB)"
                    )
            except Exception:
                pass

            self._stop.wait(self.CHECK_INTERVAL)


class TimeoutWrapper:
    """
    Decorator/wrapper for adding timeouts to functions.

    Usage:
        @TimeoutWrapper(timeout=1.0)
        def my_function():
            ...

        # Or:
        result = TimeoutWrapper.run_with_timeout(my_function, timeout=1.0)
    """

    def __init__(self, timeout: float, operation: str = "generic"):
        self.timeout = timeout
        self.operation = operation

    def __call__(self, func):
        def wrapper(*args, **kwargs):
            with ProcessResourceLimits.timeout(self.operation, self.timeout):
                return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    @staticmethod
    def run_with_timeout(func, timeout: float, *args, **kwargs):
        """Run a function with a timeout."""
        with ProcessResourceLimits.timeout("generic", timeout):
            return func(*args, **kwargs)
```

### 9.3 Day-1 Resource Limit Summary

| Resource | Limit | Enforcement |
|----------|-------|-------------|
| Process RSS memory | 512MB | `resource.RLIMIT_AS` |
| CPU time | 60s total | `resource.RLIMIT_CPU` |
| Open file descriptors | 256 | `resource.RLIMIT_NOFILE` |
| Risk check timeout | 1.0s | `signal.SIGALRM` |
| Position sizing timeout | 0.5s | `signal.SIGALRM` |
| Kill switch check timeout | 0.1s | `signal.SIGALRM` |
| Exchange order timeout | 15.0s | `signal.SIGALRM` |
| Redis operation timeout | 2.0s | `signal.SIGALRM` |
| Memory monitoring | 30s interval | Background thread |

### 9.4 Integration with Risk Governor

```python
# In Risk Governor startup:

from risk_governor.process_limits import (
    ProcessResourceLimits,
    MemoryMonitor,
)

def start_risk_governor():
    # Apply hard process limits
    ProcessResourceLimits.apply_process_limits()

    # Start memory monitor
    monitor = MemoryMonitor()
    monitor.start()

    # Risk checks use timeouts
    with ProcessResourceLimits.timeout('risk_check', 1.0):
        result = evaluate_trade(proposal)
```

### 9.5 Effort Estimate

| Task | Effort |
|------|--------|
| `ProcessResourceLimits` implementation | 2 hours |
| `MemoryMonitor` implementation | 1 hour |
| Integration with Risk Governor | 2 hours |
| Testing (verify limits work) | 2 hours |
| Documentation | 1 hour |
| **Total** | **~8 hours (1 day)** |

---

## 10. Integration Map

### 10.1 Where Each Fix Integrates

```
┌─────────────────────────────────────────────────────────────────┐
│              RISK HARDENING INTEGRATION MAP                      │
│                                                                  │
│  RISK_ARCHITECTURE.md                                           │
│  ├── §2.1 Position Sizing ← FIX #4 (Kelly 0.25)               │
│  ├── §2.2 Position Limits ← FIX #2 (canonical values)          │
│  ├── §3.1 Drawdown Thresholds ← FIX #2 (canonical values)      │
│  ├── §3.2 Recovery Protocol ← FIX #5 (gated recovery)          │
│  ├── §7.2 Kill Switch ← FIX #1 (dual-write + file fallback)   │
│  ├── §8.1 Veto Protocol ← FIX #2 (R:R 2:1), FIX #6 (margin)  │
│  ├── §9.4 Periodic Check ← FIX #6 (margin monitoring)          │
│  └── §11.2 Config ← FIX #2 (all canonical values)              │
│                                                                  │
│  NEW FILES                                                       │
│  ├── risk_governor/kill_switch_persistence.py ← FIX #1          │
│  ├── risk_governor/dead_mans_switch.py ← FIX #1                 │
│  ├── risk_governor/recovery.py ← FIX #5                         │
│  ├── risk_governor/negative_balance.py ← FIX #6                 │
│  ├── risk_governor/process_limits.py ← FIX #8                   │
│  ├── monitor/watchdog.py ← FIX #3                               │
│  └── tests/stress/test_risk_engine_stress.py ← FIX #7           │
│                                                                  │
│  SYSTEMD SERVICES                                                │
│  └── tsar-watchdog.service ← FIX #3                             │
│                                                                  │
│  ARCHITECTURE_CONSOLIDATION.md                                   │
│  └── §1.3 Risk Limits ← Source of truth for FIX #2              │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Dependency Graph

```
FIX #1 (Redis SPOF)         ← No dependencies, start first
FIX #2 (Parameters)         ← No dependencies, start first
FIX #3 (Watchdog)           ← Depends on FIX #1 (uses DualWriteKillSwitch)
FIX #4 (Kelly)              ← No dependencies
FIX #5 (Recovery)           ← Depends on FIX #2 (uses canonical thresholds)
FIX #6 (Negative Balance)   ← Depends on FIX #2 (uses canonical limits)
FIX #7 (Stress Test)        ← Depends on FIX #1, #2, #3, #4, #5, #6
FIX #8 (Day-1 Resources)    ← No dependencies
```

---

## 11. Implementation Sequencing

### 11.1 Recommended Order

```
Week 1 (Days 1-5):
├── Day 1: FIX #2 (Parameter Reconciliation) — unblocks everything
├── Day 1: FIX #4 (Kelly Standardization) — quick, standalone
├── Day 2: FIX #1 (Redis SPOF / File Fallback) — critical safety
├── Day 3: FIX #3 (Watchdog Process) — depends on #1
├── Day 4: FIX #8 (Day-1 Resource Limits) — standalone
└── Day 5: FIX #6 (Negative Balance Protection) — standalone

Week 2 (Days 6-8):
├── Day 6: FIX #5 (Recovery Protocol) — depends on #2
├── Day 7-8: FIX #7 (Stress Testing) — depends on all above
└── Buffer: Integration testing, documentation review
```

### 11.2 Effort Summary

| Fix | Days | Priority | Dependencies |
|-----|------|----------|-------------|
| #2 Parameter Reconciliation | 1 | CRITICAL | None |
| #4 Kelly Standardization | 0.5 | HIGH | None |
| #1 Redis SPOF Fallback | 2 | CRITICAL | None |
| #3 Watchdog Process | 1.5 | CRITICAL | #1 |
| #8 Day-1 Resources | 1 | HIGH | None |
| #6 Negative Balance | 1.5 | HIGH | #2 |
| #5 Recovery Protocol | 1.5 | HIGH | #2 |
| #7 Stress Testing | 2 | HIGH | All above |
| **TOTAL** | **~11 days** | | |

With parallel work: **~8.5 working days (2 weeks with buffer)**

---

*Specification completed: 2026-07-24 04:59 GMT+8*
*Source: Chief Risk Officer Review — 3 critical + 5 high-severity gap remediation*
*Status: Ready for implementation*
