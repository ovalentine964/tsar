# FIX-03: CloudEvents Migration — Standard Messaging Protocol

**Fix ID:** FIX-03  
**Severity:** MEDIUM (architecture improvement, not a bug)  
**Gap:** No standard messaging protocol — proprietary MessageEnvelope limits interoperability  
**Status:** SPECIFICATION — Ready for Implementation  
**Date:** 2026-07-24  
**Author:** Messaging Protocol Specialist  

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [CloudEvents Mapping](#2-cloudevents-mapping)
3. [CloudEventsEnvelope Class](#3-cloudeventsenvelope-class)
4. [Migration Path](#4-migration-path)
5. [Redis Streams Integration](#5-redis-streams-integration)
6. [Impact Analysis](#6-impact-analysis)
7. [Testing Strategy](#7-testing-strategy)
8. [Rollback Procedures](#8-rollback-procedures)

---

## 1. Problem Statement

### 1.1 Current State

TSAR uses a proprietary `MessageEnvelope` format for all inter-agent communication:

```python
@dataclass(frozen=True)
class MessageEnvelope:
    msg_id: str              # ULID
    timestamp_ns: int        # Nanosecond epoch
    source_agent: str        # e.g. "regime_detector"
    msg_type: str            # e.g. "regime_change", "signal", "veto"
    version: int             # Schema version
    payload: dict            # Agent-specific payload
    trace_id: str            # Distributed tracing
    priority: int            # 0=critical, 1=high, 2=normal, 3=low
```

**Serialization:** MessagePack (binary), JSON fallback for debugging.

### 1.2 Problems with Proprietary Format

| Problem | Impact |
|---------|--------|
| No industry standard | Cannot integrate with external monitoring, observability tools |
| Custom serialization | Must maintain custom encode/decode logic |
| No metadata standard | Extensions (trace_id, priority) are ad-hoc fields |
| Vendor lock-in | Switching message brokers requires rewriting envelope logic |
| No schema registry | CloudEvents has established schema registry patterns |
| Limited tooling | CloudEvents has SDKs in 10+ languages, CLI tools, CNCF ecosystem |

### 1.3 Goal

Migrate to [CloudEvents v1.0](https://cloudevents.io/) specification while:
- Preserving ALL trading-specific functionality (priority, risk_level, trace_id)
- Maintaining MessagePack binary efficiency for the performance path
- Ensuring zero-downtime migration with rollback capability
- Keeping backward compatibility during transition

---

## 2. CloudEvents Mapping

### 2.1 Attribute Mapping: MessageEnvelope → CloudEvents

| MessageEnvelope Field | CloudEvents Attribute | Mapping Rule |
|----------------------|----------------------|--------------|
| `msg_id` | `id` | Direct: ULID preserved as-is |
| `timestamp_ns` | `time` | Convert: nanosecond epoch → ISO 8601 (`2026-07-24T04:30:00.123456789Z`) |
| `source_agent` | `source` | Transform: `"regime_detector"` → `"tsar:agent:regime_detector"` |
| `msg_type` | `type` | Transform: `"regime_change"` → `"tsar.regime.change"` |
| `version` | (removed) | Absorbed into `type` suffix (e.g., `tsar.signal.detected.v1`) |
| `payload` | `data` | Serialize: MessagePack binary (performance) or JSON (debug) |
| `trace_id` | Extension: `traceid` | Custom extension attribute |
| `priority` | Extension: `priority` | Custom extension attribute |
| *(new)* | `specversion` | Always `"1.0"` |
| *(new)* | `datacontenttype` | `"application/cloudevents+msgpack"` or `"application/json"` |

### 2.2 CloudEvents Required Attributes

```python
# Required CloudEvents attributes for TSAR
{
    "specversion": "1.0",                          # CloudEvents spec version
    "id": "01JZ8XQZKJ5N7YR3V4M9P2W6T8",           # ULID (from msg_id)
    "source": "tsar:agent:signal_scout",            # Agent identifier
    "type": "tsar.signal.detected",                 # Event type
    "time": "2026-07-24T04:30:00.123456789Z",      # ISO 8601 with nanoseconds
    "datacontenttype": "application/msgpack",       # Binary payload
}
```

### 2.3 CloudEvents Extension Attributes

| Extension | Type | Description | Values |
|-----------|------|-------------|--------|
| `traceid` | string | Distributed trace ID (W3C Trace Context compatible) | UUID or hex string |
| `priority` | integer | Message priority | `0`=critical, `1`=high, `2`=normal, `3`=low |
| `risklevel` | string | Risk classification | `NONE`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `agentrole` | string | Agent permission role | `READ`, `ANALYSIS`, `TRADE_PREVIEW`, `TRADE_EXECUTE`, `TRADE_ADMIN` |
| `tradingmode` | string | Current trading mode | `paper`, `live` |
| `schemaver` | integer | Payload schema version | Integer, monotonically increasing |

### 2.4 Event Type Taxonomy

Every TSAR message type maps to a hierarchical CloudEvents `type`:

```
tsar.{domain}.{action}[.{qualifier}]

Domains:
  regime       — Market regime events
  signal       — Trading signals
  risk         — Risk decisions
  order        — Order lifecycle
  fill         — Fill events
  position     — Position updates
  analytics    — Trade analysis
  strategy     — Strategy evolution
  cartography  — Cross-asset data
  health       — Agent health
  system       — System lifecycle
```

**Complete type mapping:**

| Old `msg_type` | CloudEvents `type` |
|---------------|-------------------|
| `regime_change` | `tsar.regime.changed` |
| `regime_update` | `tsar.regime.updated` |
| `signal` | `tsar.signal.detected` |
| `signal_expired` | `tsar.signal.expired` |
| `risk_decision` | `tsar.risk.decision` |
| `veto` | `tsar.risk.veto` |
| `veto_all` | `tsar.risk.veto_all` |
| `order_placed` | `tsar.order.placed` |
| `order_filled` | `tsar.order.filled` |
| `order_cancelled` | `tsar.order.cancelled` |
| `order_rejected` | `tsar.order.rejected` |
| `fill` | `tsar.fill.executed` |
| `partial_fill` | `tsar.fill.partial` |
| `position_update` | `tsar.position.updated` |
| `position_closed` | `tsar.position.closed` |
| `portfolio_snapshot` | `tsar.position.snapshot` |
| `trade_analysis` | `tsar.analytics.trade_completed` |
| `pattern_report` | `tsar.analytics.pattern_report` |
| `strategy_mutation` | `tsar.strategy.mutated` |
| `strategy_retired` | `tsar.strategy.retired` |
| `correlation_update` | `tsar.cartography.correlation_updated` |
| `cointegration_test` | `tsar.cartography.cointegration_result` |
| `anomaly` | `tsar.cartography.anomaly_detected` |
| `heartbeat` | `tsar.health.heartbeat` |
| `agent_error` | `tsar.health.error` |
| `agent_shutdown` | `tsar.health.shutdown` |
| `bootstrap_complete` | `tsar.system.bootstrap_complete` |
| `mode_change` | `tsar.system.mode_changed` |

### 2.5 Example: Full CloudEvents Message

**Original MessageEnvelope:**
```python
MessageEnvelope(
    msg_id="01JZ8XQZKJ5N7YR3V4M9P2W6T8",
    timestamp_ns=1753337400123456789,
    source_agent="signal_scout",
    msg_type="signal",
    version=1,
    payload={
        "signal_id": "01JZ8XQZKJ5N7YR3V4M9P2W6T9",
        "instrument": "BTC/USDT",
        "direction": "long",
        "confidence": 0.85,
        "entry_price": 68500.0,
        "stop_loss": 67800.0,
        "take_profit": [69500.0, 70200.0],
    },
    trace_id="abc123def456",
    priority=1,
)
```

**Equivalent CloudEvents (JSON transport):**
```json
{
    "specversion": "1.0",
    "id": "01JZ8XQZKJ5N7YR3V4M9P2W6T8",
    "source": "tsar:agent:signal_scout",
    "type": "tsar.signal.detected",
    "time": "2026-07-24T04:30:00.123456789Z",
    "datacontenttype": "application/json",
    "traceid": "abc123def456",
    "priority": 1,
    "risklevel": "NONE",
    "agentrole": "TRADE_PREVIEW",
    "tradingmode": "paper",
    "schemaver": 1,
    "data": {
        "signal_id": "01JZ8XQZKJ5N7YR3V4M9P2W6T9",
        "instrument": "BTC/USDT",
        "direction": "long",
        "confidence": 0.85,
        "entry_price": 68500.0,
        "stop_loss": 67800.0,
        "take_profit": [69500.0, 70200.0]
    }
}
```

**Equivalent CloudEvents (MessagePack transport — performance path):**
```
Binary envelope: CloudEvents attributes as MessagePack map
Binary data:     Payload as MessagePack bytes
Content-Type:    application/msgpack
```

### 2.6 Source URI Design

The `source` attribute uses URI-formatted agent identifiers:

```
tsar:agent:{agent_id}

Examples:
  tsar:agent:regime_detector
  tsar:agent:signal_scout
  tsar:agent:risk_guardian
  tsar:agent:execution_sniper
  tsar:agent:execution_tracker
  tsar:agent:trade_philosopher
  tsar:agent:strategy_geneticist
  tsar:agent:market_cartographer
  tsar:agent:orchestrator
```

**Why `tsar:agent:` prefix?**
- Globally unique within CloudEvents ecosystem
- Clearly identifies TSAR system origin
- Compatible with CloudEvents `source` URI requirements
- Extensible: `tsar:system:`, `tsar:tool:` for non-agent sources

---

## 3. CloudEventsEnvelope Class

### 3.1 Core Implementation

```python
"""
tsar/messaging/cloudevents_envelope.py

CloudEvents v1.0 compliant envelope for TSAR inter-agent communication.
Replaces proprietary MessageEnvelope with industry-standard format.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

import msgpack
import ulid


# ═══════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════

CLOUDEVENTS_SPEC_VERSION = "1.0"
TSAR_SOURCE_PREFIX = "tsar:agent:"
TSAR_TYPE_PREFIX = "tsar."

# Content types
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_MSGPACK = "application/msgpack"

# Media types for Redis storage
MEDIA_TYPE_BINARY = "application/cloudevents+msgpack"
MEDIA_TYPE_JSON = "application/cloudevents+json"


class Priority(IntEnum):
    """Message priority levels (lower = higher priority)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class RiskLevel:
    """Risk classification for trading events."""
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ═══════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════

class CloudEventsValidationError(Exception):
    """Raised when a CloudEvents envelope fails validation."""
    pass


def validate_cloudevents_attributes(attrs: dict[str, Any]) -> None:
    """Validate required CloudEvents attributes per spec v1.0."""
    # Required attributes
    required = {"specversion", "id", "source", "type"}
    missing = required - set(attrs.keys())
    if missing:
        raise CloudEventsValidationError(
            f"Missing required CloudEvents attributes: {missing}"
        )

    # specversion must be "1.0"
    if attrs["specversion"] != CLOUDEVENTS_SPEC_VERSION:
        raise CloudEventsValidationError(
            f"Unsupported specversion: {attrs['specversion']}. "
            f"Must be '{CLOUDEVENTS_SPEC_VERSION}'"
        )

    # type must start with tsar prefix
    if not attrs["type"].startswith(TSAR_TYPE_PREFIX):
        raise CloudEventsValidationError(
            f"Event type must start with '{TSAR_TYPE_PREFIX}': {attrs['type']}"
        )

    # source must start with tsar:agent: prefix
    if not attrs["source"].startswith(TSAR_SOURCE_PREFIX):
        raise CloudEventsValidationError(
            f"Source must start with '{TSAR_SOURCE_PREFIX}': {attrs['source']}"
        )

    # time must be ISO 8601 if present
    if "time" in attrs and attrs["time"] is not None:
        try:
            datetime.fromisoformat(attrs["time"].replace("Z", "+00:00"))
        except ValueError as e:
            raise CloudEventsValidationError(f"Invalid time format: {e}")

    # priority must be 0-3 if present
    if "priority" in attrs:
        p = attrs["priority"]
        if not isinstance(p, int) or p < 0 or p > 3:
            raise CloudEventsValidationError(
                f"Priority must be 0-3: {p}"
            )


# ═══════════════════════════════════════════════════════════════════
# CLOUD EVENTS ENVELOPE
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CloudEventsEnvelope:
    """
    CloudEvents v1.0 compliant envelope for TSAR.

    Replaces MessageEnvelope with industry-standard format while
    preserving all trading-specific functionality.

    Attributes follow CloudEvents spec:
    - Required: specversion, id, source, type
    - Optional: time, datacontenttype, subject
    - Extensions: traceid, priority, risklevel, agentrole, tradingmode, schemaver
    """

    # ── Required CloudEvents attributes ──
    specversion: str = CLOUDEVENTS_SPEC_VERSION
    id: str = ""                          # ULID
    source: str = ""                      # "tsar:agent:{agent_id}"
    type: str = ""                        # "tsar.{domain}.{action}"

    # ── Optional CloudEvents attributes ──
    time: str | None = None               # ISO 8601
    datacontenttype: str = CONTENT_TYPE_MSGPACK
    subject: str | None = None            # Optional subject reference

    # ── Extension attributes ──
    traceid: str = ""                     # Distributed trace ID
    priority: int = Priority.NORMAL       # 0=critical, 1=high, 2=normal, 3=low
    risklevel: str = RiskLevel.NONE       # Risk classification
    agentrole: str = "READ"               # Agent permission role
    tradingmode: str = "paper"            # paper | live
    schemaver: int = 1                    # Payload schema version

    # ── Data payload ──
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Auto-generate id and time if not provided."""
        if not self.id:
            object.__setattr__(self, "id", str(ulid.new()))
        if not self.time:
            object.__setattr__(
                self, "time",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )

    # ── Serialization ──

    def to_dict(self) -> dict[str, Any]:
        """Serialize to CloudEvents JSON format."""
        attrs = {
            "specversion": self.specversion,
            "id": self.id,
            "source": self.source,
            "type": self.type,
        }

        # Optional attributes (only include if set)
        if self.time:
            attrs["time"] = self.time
        if self.datacontenttype:
            attrs["datacontenttype"] = self.datacontenttype
        if self.subject:
            attrs["subject"] = self.subject

        # Extensions
        attrs["traceid"] = self.traceid
        attrs["priority"] = self.priority
        attrs["risklevel"] = self.risklevel
        attrs["agentrole"] = self.agentrole
        attrs["tradingmode"] = self.tradingmode
        attrs["schemaver"] = self.schemaver

        # Data
        attrs["data"] = self.data

        return attrs

    def to_json(self) -> str:
        """Serialize to JSON string (debug/human-readable path)."""
        return json.dumps(self.to_dict(), default=str)

    def to_msgpack(self) -> bytes:
        """
        Serialize to MessagePack (performance path).

        CloudEvents attributes are encoded as a MessagePack map.
        The 'data' field is encoded as nested MessagePack bytes.
        """
        envelope = {
            "specversion": self.specversion,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time,
            "datacontenttype": self.datacontenttype,
            "traceid": self.traceid,
            "priority": self.priority,
            "risklevel": self.risklevel,
            "agentrole": self.agentrole,
            "tradingmode": self.tradingmode,
            "schemaver": self.schemaver,
            "data": self.data,
        }
        if self.subject:
            envelope["subject"] = self.subject

        return msgpack.packb(envelope, use_bin_type=True)

    def to_redis_fields(self) -> dict[str, bytes]:
        """
        Serialize for Redis Streams XADD.

        Redis Streams require string key-value pairs.
        CloudEvents attributes become top-level fields.
        Data payload is MessagePack-encoded as a single field.
        """
        fields = {
            "ce_specversion": self.specversion.encode(),
            "ce_id": self.id.encode(),
            "ce_source": self.source.encode(),
            "ce_type": self.type.encode(),
            "ce_time": (self.time or "").encode(),
            "ce_datacontenttype": self.datacontenttype.encode(),
            "ce_traceid": self.traceid.encode(),
            "ce_priority": str(self.priority).encode(),
            "ce_risklevel": self.risklevel.encode(),
            "ce_agentrole": self.agentrole.encode(),
            "ce_tradingmode": self.tradingmode.encode(),
            "ce_schemaver": str(self.schemaver).encode(),
            "ce_data": msgpack.packb(self.data, use_bin_type=True),
        }
        if self.subject:
            fields["ce_subject"] = self.subject.encode()
        return fields

    # ── Deserialization ──

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CloudEventsEnvelope:
        """Deserialize from CloudEvents JSON dict."""
        validate_cloudevents_attributes(d)

        return cls(
            specversion=d["specversion"],
            id=d["id"],
            source=d["source"],
            type=d["type"],
            time=d.get("time"),
            datacontenttype=d.get("datacontenttype", CONTENT_TYPE_MSGPACK),
            subject=d.get("subject"),
            traceid=d.get("traceid", ""),
            priority=d.get("priority", Priority.NORMAL),
            risklevel=d.get("risklevel", RiskLevel.NONE),
            agentrole=d.get("agentrole", "READ"),
            tradingmode=d.get("tradingmode", "paper"),
            schemaver=d.get("schemaver", 1),
            data=d.get("data", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> CloudEventsEnvelope:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_msgpack(cls, raw: bytes) -> CloudEventsEnvelope:
        """Deserialize from MessagePack bytes."""
        d = msgpack.unpackb(raw, raw=False)
        return cls.from_dict(d)

    @classmethod
    def from_redis_fields(cls, fields: dict[bytes, bytes]) -> CloudEventsEnvelope:
        """Deserialize from Redis Streams XREAD fields."""
        def _get(key: str, default: str = "") -> str:
            v = fields.get(key.encode())
            return v.decode() if v else default

        def _get_int(key: str, default: int = 0) -> int:
            v = fields.get(key.encode())
            return int(v.decode()) if v else default

        data_raw = fields.get(b"ce_data")
        data = msgpack.unpackb(data_raw, raw=False) if data_raw else {}

        return cls(
            specversion=_get("ce_specversion", CLOUDEVENTS_SPEC_VERSION),
            id=_get("ce_id"),
            source=_get("ce_source"),
            type=_get("ce_type"),
            time=_get("ce_time") or None,
            datacontenttype=_get("ce_datacontenttype", CONTENT_TYPE_MSGPACK),
            subject=_get("ce_subject") or None,
            traceid=_get("ce_traceid"),
            priority=_get_int("ce_priority", Priority.NORMAL),
            risklevel=_get("ce_risklevel", RiskLevel.NONE),
            agentrole=_get("ce_agentrole", "READ"),
            tradingmode=_get("ce_tradingmode", "paper"),
            schemaver=_get_int("ce_schemaver", 1),
            data=data,
        )

    # ── Factory methods ──

    @classmethod
    def create(
        cls,
        source_agent: str,
        event_type: str,
        data: dict[str, Any],
        trace_id: str = "",
        priority: int = Priority.NORMAL,
        risk_level: str = RiskLevel.NONE,
        agent_role: str = "READ",
        trading_mode: str = "paper",
        schema_version: int = 1,
    ) -> CloudEventsEnvelope:
        """
        Factory method for creating TSAR CloudEvents.

        Args:
            source_agent: Agent name (e.g., "signal_scout")
            event_type: Event type suffix (e.g., "signal.detected")
            data: Payload data
            trace_id: Distributed trace ID
            priority: Message priority (0-3)
            risk_level: Risk classification
            agent_role: Agent permission role
            trading_mode: Current trading mode
            schema_version: Payload schema version
        """
        return cls(
            id=str(ulid.new()),
            source=f"{TSAR_SOURCE_PREFIX}{source_agent}",
            type=f"{TSAR_TYPE_PREFIX}{event_type}",
            time=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            datacontenttype=CONTENT_TYPE_MSGPACK,
            traceid=trace_id,
            priority=priority,
            risklevel=risk_level,
            agentrole=agent_role,
            tradingmode=trading_mode,
            schemaver=schema_version,
            data=data,
        )

    # ── Utility ──

    @property
    def agent_id(self) -> str:
        """Extract agent ID from source."""
        if self.source.startswith(TSAR_SOURCE_PREFIX):
            return self.source[len(TSAR_SOURCE_PREFIX):]
        return self.source

    @property
    def event_domain(self) -> str:
        """Extract domain from type (e.g., 'signal' from 'tsar.signal.detected')."""
        parts = self.type.split(".")
        return parts[1] if len(parts) > 1 else ""

    @property
    def event_action(self) -> str:
        """Extract action from type (e.g., 'detected' from 'tsar.signal.detected')."""
        parts = self.type.split(".")
        return parts[2] if len(parts) > 2 else ""

    @property
    def timestamp_ns(self) -> int:
        """Convert ISO 8601 time to nanosecond epoch."""
        if not self.time:
            return 0
        dt = datetime.fromisoformat(self.time.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1_000_000_000)

    @property
    def is_critical(self) -> bool:
        return self.priority == Priority.CRITICAL

    @property
    def is_risk_event(self) -> bool:
        return self.risklevel in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def __str__(self) -> str:
        return (
            f"CloudEvents(type={self.type}, source={self.source}, "
            f"id={self.id}, priority={self.priority})"
        )


# ═══════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY: MessageEnvelope ↔ CloudEvents
# ═══════════════════════════════════════════════════════════════════

# Mapping from legacy msg_type to CloudEvents type
MSG_TYPE_MAP: dict[str, str] = {
    "regime_change": "tsar.regime.changed",
    "regime_update": "tsar.regime.updated",
    "signal": "tsar.signal.detected",
    "signal_expired": "tsar.signal.expired",
    "risk_decision": "tsar.risk.decision",
    "veto": "tsar.risk.veto",
    "veto_all": "tsar.risk.veto_all",
    "order_placed": "tsar.order.placed",
    "order_filled": "tsar.order.filled",
    "order_cancelled": "tsar.order.cancelled",
    "order_rejected": "tsar.order.rejected",
    "fill": "tsar.fill.executed",
    "partial_fill": "tsar.fill.partial",
    "position_update": "tsar.position.updated",
    "position_closed": "tsar.position.closed",
    "portfolio_snapshot": "tsar.position.snapshot",
    "trade_analysis": "tsar.analytics.trade_completed",
    "pattern_report": "tsar.analytics.pattern_report",
    "strategy_mutation": "tsar.strategy.mutated",
    "strategy_retired": "tsar.strategy.retired",
    "correlation_update": "tsar.cartography.correlation_updated",
    "cointegration_test": "tsar.cartography.cointegration_result",
    "anomaly": "tsar.cartography.anomaly_detected",
    "heartbeat": "tsar.health.heartbeat",
    "agent_error": "tsar.health.error",
    "agent_shutdown": "tsar.health.shutdown",
    "bootstrap_complete": "tsar.system.bootstrap_complete",
    "mode_change": "tsar.system.mode_changed",
}

# Reverse mapping
CLOUDEVENTS_TYPE_MAP: dict[str, str] = {v: k for k, v in MSG_TYPE_MAP.items()}


def nanoseconds_to_iso8601(ns: int) -> str:
    """Convert nanosecond epoch to ISO 8601 string."""
    seconds = ns / 1_000_000_000
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    # Format with nanosecond precision
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    nanos = ns % 1_000_000_000
    return f"{base}.{nanos:09d}Z"


def iso8601_to_nanoseconds(iso_str: str) -> int:
    """Convert ISO 8601 string to nanosecond epoch."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    seconds = int(dt.timestamp())
    # Extract sub-second precision from string
    if "." in iso_str:
        frac = iso_str.split(".")[1].rstrip("Z").rstrip("+")
        nanos = int(frac.ljust(9, "0")[:9])
    else:
        nanos = 0
    return seconds * 1_000_000_000 + nanos


def legacy_to_cloudevents(
    msg_id: str,
    timestamp_ns: int,
    source_agent: str,
    msg_type: str,
    version: int,
    payload: dict,
    trace_id: str = "",
    priority: int = Priority.NORMAL,
) -> CloudEventsEnvelope:
    """Convert legacy MessageEnvelope fields to CloudEventsEnvelope."""
    ce_type = MSG_TYPE_MAP.get(msg_type, f"tsar.unknown.{msg_type}")

    return CloudEventsEnvelope(
        id=msg_id,
        source=f"{TSAR_SOURCE_PREFIX}{source_agent}",
        type=ce_type,
        time=nanoseconds_to_iso8601(timestamp_ns),
        datacontenttype=CONTENT_TYPE_MSGPACK,
        traceid=trace_id,
        priority=priority,
        schemaver=version,
        data=payload,
    )


def cloudevents_to_legacy(envelope: CloudEventsEnvelope) -> dict:
    """Convert CloudEventsEnvelope back to legacy MessageEnvelope dict."""
    legacy_type = CLOUDEVENTS_TYPE_MAP.get(envelope.type, envelope.type)

    return {
        "msg_id": envelope.id,
        "timestamp_ns": envelope.timestamp_ns,
        "source_agent": envelope.agent_id,
        "msg_type": legacy_type,
        "version": envelope.schemaver,
        "payload": envelope.data,
        "trace_id": envelope.traceid,
        "priority": envelope.priority,
    }
```

### 3.2 Publisher Abstraction

```python
"""
tsar/messaging/publisher.py

Dual-mode publisher that handles both legacy and CloudEvents formats
during migration.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import redis.asyncio as aioredis

from .cloudevents_envelope import (
    CloudEventsEnvelope,
    Priority,
    RiskLevel,
    legacy_to_cloudevents,
)

logger = logging.getLogger(__name__)


class PublishMode(Enum):
    """Publisher output format mode."""
    LEGACY = "legacy"           # MessageEnvelope only (Phase 1 start)
    DUAL = "dual"               # Both formats (Phase 1)
    CLOUDEVENTS = "cloudevents" # CloudEvents only (Phase 3)


class DualModePublisher:
    """
    Publisher that emits messages in legacy, dual, or CloudEvents mode.

    During migration, agents can switch modes without code changes
    in their business logic.
    """

    def __init__(self, redis: aioredis.Redis, mode: PublishMode = PublishMode.LEGACY):
        self.redis = redis
        self.mode = mode

    async def publish(
        self,
        stream: str,
        source_agent: str,
        event_type: str,
        data: dict[str, Any],
        trace_id: str = "",
        priority: int = Priority.NORMAL,
        risk_level: str = RiskLevel.NONE,
        agent_role: str = "READ",
        trading_mode: str = "paper",
        schema_version: int = 1,
        msg_id: str = "",
        timestamp_ns: int = 0,
    ) -> str:
        """
        Publish a message to a Redis stream.

        Returns the message ID.
        """
        if self.mode == PublishMode.LEGACY:
            return await self._publish_legacy(
                stream, source_agent, event_type, data,
                trace_id, priority, msg_id, timestamp_ns,
            )
        elif self.mode == PublishMode.DUAL:
            # Publish CloudEvents to primary stream
            ce_id = await self._publish_cloudevents(
                stream, source_agent, event_type, data,
                trace_id, priority, risk_level, agent_role,
                trading_mode, schema_version,
            )
            # Also publish legacy to compat stream
            await self._publish_legacy(
                f"{stream}:legacy", source_agent, event_type, data,
                trace_id, priority, msg_id, timestamp_ns,
            )
            return ce_id
        else:  # CLOUDEVENTS
            return await self._publish_cloudevents(
                stream, source_agent, event_type, data,
                trace_id, priority, risk_level, agent_role,
                trading_mode, schema_version,
            )

    async def _publish_cloudevents(
        self,
        stream: str,
        source_agent: str,
        event_type: str,
        data: dict,
        trace_id: str,
        priority: int,
        risk_level: str,
        agent_role: str,
        trading_mode: str,
        schema_version: int,
    ) -> str:
        """Publish in CloudEvents format."""
        envelope = CloudEventsEnvelope.create(
            source_agent=source_agent,
            event_type=event_type,
            data=data,
            trace_id=trace_id,
            priority=priority,
            risk_level=risk_level,
            agent_role=agent_role,
            trading_mode=trading_mode,
            schema_version=schema_version,
        )

        fields = envelope.to_redis_fields()
        msg_id = await self.redis.xadd(stream, fields)

        logger.debug(
            f"Published CloudEvents to {stream}: "
            f"type={envelope.type}, id={envelope.id}"
        )
        return envelope.id

    async def _publish_legacy(
        self,
        stream: str,
        source_agent: str,
        event_type: str,
        data: dict,
        trace_id: str,
        priority: int,
        msg_id: str,
        timestamp_ns: int,
    ) -> str:
        """Publish in legacy MessageEnvelope format."""
        import msgpack
        import time as _time
        import ulid

        _id = msg_id or str(ulid.new())
        _ts = timestamp_ns or _time.time_ns()

        fields = {
            "msg_id": _id.encode(),
            "timestamp_ns": str(_ts).encode(),
            "source_agent": source_agent.encode(),
            "msg_type": event_type.encode(),
            "version": b"1",
            "payload": msgpack.packb(data, use_bin_type=True),
            "trace_id": trace_id.encode(),
            "priority": str(priority).encode(),
        }

        result = await self.redis.xadd(stream, fields)
        logger.debug(f"Published legacy to {stream}: type={event_type}, id={_id}")
        return _id
```

### 3.3 Consumer Abstraction

```python
"""
tsar/messaging/consumer.py

Dual-mode consumer that accepts both legacy and CloudEvents formats.
"""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as aioredis

from .cloudevents_envelope import (
    CloudEventsEnvelope,
    cloudevents_to_legacy,
    legacy_to_cloudevents,
)

logger = logging.getLogger(__name__)


class DualModeConsumer:
    """
    Consumer that reads from Redis Streams and handles both
    legacy MessageEnvelope and CloudEvents formats.

    Automatically detects format based on field presence.
    """

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    def detect_format(self, fields: dict[bytes, bytes]) -> str:
        """Detect whether a message is CloudEvents or legacy format."""
        if b"ce_specversion" in fields:
            return "cloudevents"
        elif b"msg_id" in fields:
            return "legacy"
        else:
            logger.warning("Unknown message format, attempting legacy parse")
            return "legacy"

    def parse_message(
        self, fields: dict[bytes, bytes]
    ) -> CloudEventsEnvelope:
        """
        Parse a Redis Stream message into a CloudEventsEnvelope.

        Accepts both formats and normalizes to CloudEvents.
        """
        fmt = self.detect_format(fields)

        if fmt == "cloudevents":
            return CloudEventsEnvelope.from_redis_fields(fields)
        else:
            return self._parse_legacy(fields)

    def _parse_legacy(self, fields: dict[bytes, bytes]) -> CloudEventsEnvelope:
        """Parse legacy MessageEnvelope format into CloudEvents."""
        def _get(key: str) -> str:
            v = fields.get(key.encode())
            return v.decode() if v else ""

        import msgpack
        payload_raw = fields.get(b"payload")
        payload = msgpack.unpackb(payload_raw, raw=False) if payload_raw else {}

        return legacy_to_cloudevents(
            msg_id=_get("msg_id"),
            timestamp_ns=int(_get("timestamp_ns") or "0"),
            source_agent=_get("source_agent"),
            msg_type=_get("msg_type"),
            version=int(_get("version") or "1"),
            payload=payload,
            trace_id=_get("trace_id"),
            priority=int(_get("priority") or "2"),
        )

    async def read(
        self,
        streams: dict[str, str],
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[tuple[str, str, CloudEventsEnvelope]]:
        """
        Read messages from Redis Streams.

        Returns list of (stream_name, message_id, envelope).
        """
        results = await self.redis.xread(
            streams, count=count, block=block_ms
        )

        messages = []
        for stream_name, entries in results:
            stream = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
            for msg_id, fields in entries:
                mid = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                try:
                    envelope = self.parse_message(fields)
                    messages.append((stream, mid, envelope))
                except Exception as e:
                    logger.error(
                        f"Failed to parse message {mid} from {stream}: {e}"
                    )

        return messages

    async def readgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[tuple[str, str, CloudEventsEnvelope]]:
        """
        Read messages from Redis Streams using consumer groups.

        Returns list of (stream_name, message_id, envelope).
        """
        results = await self.redis.xreadgroup(
            group, consumer, streams, count=count, block=block_ms
        )

        messages = []
        for stream_name, entries in results:
            stream = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
            for msg_id, fields in entries:
                mid = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                try:
                    envelope = self.parse_message(fields)
                    messages.append((stream, mid, envelope))
                except Exception as e:
                    logger.error(
                        f"Failed to parse message {mid} from {stream}: {e}"
                    )

        return messages
```

---

## 4. Migration Path

### 4.1 Three-Phase Migration

```
Phase 1: DUAL MODE          Phase 2: CE PRIMARY         Phase 3: CE ONLY
(Weeks 1-2)                 (Weeks 3-4)                 (Week 5+)

┌──────────────┐            ┌──────────────┐            ┌──────────────┐
│  Agents emit │            │  Agents emit │            │  Agents emit │
│  BOTH formats│            │  CE primary  │            │  CE only     │
│  to streams  │            │  legacy fallback           │  to streams  │
└──────┬───────┘            └──────┬───────┘            └──────┬───────┘
       │                           │                           │
  ┌────▼────┐                 ┌────▼────┐                 ┌────▼────┐
  │ Primary │                 │ Primary │                 │ Primary │
  │ stream  │                 │ stream  │                 │ stream  │
  │ (CE)    │                 │ (CE)    │                 │ (CE)    │
  ├─────────┤                 ├─────────┤                 ├─────────┤
  │ Legacy  │                 │ Legacy  │                 │         │
  │ compat  │                 │ compat  │                 │         │
  │ stream  │                 │ (read   │                 │         │
  └─────────┘                 │  only)  │                 └─────────┘
                              └─────────┘

Consumer:                     Consumer:                   Consumer:
Accepts both                  Accepts both,               CE only
                              prefers CE
```

### 4.2 Phase 1: Dual Mode (Weeks 1-2)

**Goal:** All agents emit both formats; consumers accept both.

**Configuration:**
```python
# config/messaging.toml
[messaging]
mode = "dual"                         # "legacy" | "dual" | "cloudevents"
ce_primary_stream = true              # CloudEvents goes to main stream
legacy_compat_stream = true           # Legacy goes to {stream}:legacy
consumer_accept_both = true           # Consumer parses both formats
```

**Changes per agent:**
1. Replace `MessageEnvelope` construction with `DualModePublisher.publish()`
2. Replace stream reads with `DualModeConsumer.read()` / `readgroup()`
3. Add `PublishMode.DUAL` to publisher initialization

**Validation:**
- All existing tests pass with dual-mode consumer
- New CloudEvents format tests pass
- Legacy compat streams are populated
- No performance regression (<5% latency increase)

**Rollback:** Set `mode = "legacy"` in config. Restart agents.

### 4.3 Phase 2: CloudEvents Primary (Weeks 3-4)

**Goal:** CloudEvents is primary format. Legacy fallback for consumers only.

**Changes:**
1. Change `PublishMode.DUAL` → `PublishMode.CLOUDEVENTS` in publishers
2. Keep `DualModeConsumer` accepting both formats (grace period)
3. Stop writing to `:legacy` compat streams
4. Monitor for any consumer parsing failures

**Validation:**
- All messages on primary streams are CloudEvents format
- Consumers still process correctly
- Legacy compat streams drain and become empty

**Rollback:** Revert to `PublishMode.DUAL`. Compat streams repopulate.

### 4.4 Phase 3: CloudEvents Only (Week 5+)

**Goal:** Remove all legacy code paths.

**Changes:**
1. Remove `DualModePublisher` → use `CloudEventsPublisher` directly
2. Remove legacy parsing from `DualModeConsumer` → `CloudEventsConsumer`
3. Remove `legacy_to_cloudevents()` / `cloudevents_to_legacy()` converters
4. Remove `MSG_TYPE_MAP` / `CLOUDEVENTS_TYPE_MAP` compatibility tables
5. Update all agent code to use `CloudEventsEnvelope.create()` directly
6. Remove `:legacy` compat stream cleanup jobs

**Validation:**
- All tests pass without legacy code paths
- Zero legacy format messages in streams
- Performance benchmarks meet or exceed pre-migration baselines

### 4.5 Migration Timeline

```
Week 1:  ┃ Phase 1 Start
         ┃ ├─ Deploy dual-mode publisher/consumer libraries
         ┃ ├─ Update Regime Detector + Signal Scout (non-critical agents first)
         ┃ ├─ Verify dual-format output
         ┃ └─ Monitor for issues
Week 2:  ┃ Phase 1 Continue
         ┃ ├─ Update Risk Guardian + Execution Sniper (critical path)
         ┃ ├─ Update remaining agents
         ┃ ├─ Full regression test suite
         ┃ └─ Performance benchmarks
Week 3:  ┃ Phase 2 Start
         ┃ ├─ Switch publishers to CloudEvents primary
         ┃ ├─ Legacy compat streams stop receiving new writes
         ┃ ├─ Monitor consumer error rates
         ┃ └─ Alert on any legacy format on primary streams
Week 4:  ┃ Phase 2 Continue
         ┃ ├─ Verify all consumers handle CE format
         ┃ ├─ Drain legacy compat streams
         ┃ ├─ Update documentation
         ┃ └─ Prepare Phase 3
Week 5:  ┃ Phase 3 Start
         ┃ ├─ Remove legacy code paths
         ┃ ├─ Clean up compat streams
         ┃ ├─ Final regression tests
         ┃ └─ Update architecture docs
Week 6:  ┃ Phase 3 Complete
         ┃ ├─ Legacy format fully removed
         ┃ ├─ CloudEvents-only operation verified
         ┃ └─ Close FIX-03
```

### 4.6 Rollback Procedures

| Phase | Rollback Trigger | Rollback Action | Recovery Time |
|-------|-----------------|-----------------|---------------|
| 1 | >1% message parse errors | Set `mode = "legacy"` | <5 min (config change) |
| 1 | Performance regression >10% | Set `mode = "legacy"` | <5 min |
| 2 | Consumer failures on CE format | Revert to `PublishMode.DUAL` | <10 min (deploy) |
| 2 | Data loss detected | Revert to Phase 1 dual mode | <10 min |
| 3 | Legacy code needed | Git revert to Phase 2 branch | <30 min (deploy) |

**Rollback command:**
```bash
# Phase 1 rollback
kubectl set env deployment/tsar-agents MESSAGING_MODE=legacy

# Phase 2 rollback
kubectl set image deployment/tsar-agents tsar-agents=tsar:phase1-dual

# Phase 3 rollback
git revert HEAD && make deploy
```

---

## 5. Redis Streams Integration

### 5.1 CloudEvents Serialization in Redis Streams

CloudEvents attributes map to Redis Stream fields with `ce_` prefix:

```
Redis Stream Field    →  CloudEvents Attribute
──────────────────────────────────────────────
ce_specversion        →  specversion
ce_id                 →  id
ce_source             →  source
ce_type               →  type
ce_time               →  time
ce_datacontenttype    →  datacontenttype
ce_subject            →  subject (optional)
ce_traceid            →  traceid (extension)
ce_priority           →  priority (extension)
ce_risklevel          →  risklevel (extension)
ce_agentrole          →  agentrole (extension)
ce_tradingmode        →  tradingmode (extension)
ce_schemaver          →  schemaver (extension)
ce_data               →  data (MessagePack-encoded)
```

**Why `ce_` prefix?**
- Avoids collision with any custom fields
- Clear identification of CloudEvents attributes
- Allows gradual migration (old fields coexist during Phase 1)

### 5.2 Redis Stream Commands

**XADD (Publish):**
```
XADD tsar:stream:signals * \
  ce_specversion "1.0" \
  ce_id "01JZ8XQZKJ5N7YR3V4M9P2W6T8" \
  ce_source "tsar:agent:signal_scout" \
  ce_type "tsar.signal.detected" \
  ce_time "2026-07-24T04:30:00.123456789Z" \
  ce_datacontenttype "application/msgpack" \
  ce_traceid "abc123def456" \
  ce_priority "1" \
  ce_risklevel "NONE" \
  ce_agentrole "TRADE_PREVIEW" \
  ce_tradingmode "paper" \
  ce_schemaver "1" \
  ce_data <msgpack-bytes>
```

**XREADGROUP (Consume):**
```
XREADGROUP GROUP signal_consumers consumer_1 \
  COUNT 10 BLOCK 1000 \
  STREAMS tsar:stream:signals >
```

### 5.3 Consumer Group Compatibility

Consumer groups work identically with CloudEvents. The `ce_`-prefixed fields are transparent to Redis — it treats them as regular hash fields.

**No changes needed to:**
- Consumer group creation (`XGROUP CREATE`)
- Message acknowledgment (`XACK`)
- Pending entry management (`XPENDING`, `XCLAIM`)
- Stream trimming (`XTRIM`)

**Consumer group naming convention (unchanged):**
```
{agent_name}_group       — Per-agent consumer group
{agent_name}_consumer    — Consumer name within group

Examples:
  signal_scout_group / signal_scout_consumer
  risk_guardian_group / risk_guardian_consumer
```

### 5.4 Stream Key Naming

Stream keys follow existing canonical convention with CloudEvents awareness:

```
Primary streams (CloudEvents):
  tsar:stream:{event_domain}         — e.g., tsar:stream:signals

Legacy compat streams (Phase 1 only):
  tsar:stream:{event_domain}:legacy  — e.g., tsar:stream:signals:legacy

CloudEvents metadata stream (new):
  tsar:stream:_cloudevents_meta      — Schema registry, type catalog
```

**Complete stream topology with CloudEvents types:**

```
Stream Name                        CloudEvents Types Published
──────────────────────────────────────────────────────────────────────
tsar:stream:regime                 tsar.regime.changed, tsar.regime.updated
tsar:stream:signals                tsar.signal.detected, tsar.signal.expired
tsar:stream:risk_decisions         tsar.risk.decision, tsar.risk.veto,
                                   tsar.risk.veto_all
tsar:stream:orders                 tsar.order.placed, tsar.order.filled,
                                   tsar.order.cancelled, tsar.order.rejected
tsar:stream:fills                  tsar.fill.executed, tsar.fill.partial
tsar:stream:positions              tsar.position.updated, tsar.position.closed,
                                   tsar.position.snapshot
tsar:stream:analytics              tsar.analytics.trade_completed,
                                   tsar.analytics.pattern_report
tsar:stream:cartography            tsar.cartography.correlation_updated,
                                   tsar.cartography.cointegration_result,
                                   tsar.cartography.anomaly_detected
tsar:stream:strategy_mutations     tsar.strategy.mutated, tsar.strategy.retired
tsar:stream:health                 tsar.health.heartbeat, tsar.health.error,
                                   tsar.health.shutdown
tsar:stream:macro                  tsar.macro.regime_update
tsar:stream:sentiment              tsar.macro.sentiment_update
tsar:stream:onchain                tsar.macro.onchain_update
tsar:stream:risk_requests          tsar.risk.approval_request
tsar:stream:risk_reply:{agent}     tsar.risk.approval_response
```

### 5.5 Redis Stream Retention

No changes to existing retention policies:

| Stream | Retention | Max Length |
|--------|-----------|------------|
| `tsar:stream:regime` | 24h | 10,000 |
| `tsar:stream:signals` | 7d | 100,000 |
| `tsar:stream:risk_decisions` | 7d | 100,000 |
| `tsar:stream:orders` | 30d | 500,000 |
| `tsar:stream:fills` | 30d | 500,000 |
| `tsar:stream:positions` | 7d | 100,000 |
| `tsar:stream:analytics` | 90d | 50,000 |
| `tsar:stream:cartography` | 7d | 50,000 |
| `tsar:stream:health` | 24h | 10,000 |

### 5.6 Performance Impact

| Metric | Legacy (MessagePack) | CloudEvents (Redis fields) | Delta |
|--------|---------------------|---------------------------|-------|
| XADD latency | ~0.1ms | ~0.12ms | +20μs |
| Message size (avg) | ~200 bytes | ~350 bytes | +75% |
| XREAD parse time | ~0.05ms | ~0.08ms | +30μs |
| Throughput (msg/sec) | ~50,000 | ~45,000 | -10% |

**Notes:**
- The +75% message size increase is due to attribute name repetition in Redis fields
- For TSAR's actual throughput (~50 msg/sec normal, ~500 msg/sec stress), impact is negligible
- MessagePack `data` field preserves binary efficiency for payload
- The `ce_` prefix adds ~100 bytes overhead per message

**Optimization:** For high-throughput streams, consider binary CloudEvents format:
```
# Binary content mode: CloudEvents metadata in Redis fields,
# data as raw MessagePack bytes (not double-encoded)
ce_datacontenttype: "application/msgpack"
ce_data: <raw-msgpack-bytes>  # Not base64-encoded
```

---

## 6. Impact Analysis

### 6.1 Component Impact Matrix

| Component | Creates Messages | Consumes Messages | Changes Required | Effort (days) |
|-----------|:---:|:---:|---|---|
| **Regime Detector** | ✅ | ✅ (cartography, analytics) | Publisher + Consumer migration | 2 |
| **Signal Scout** | ✅ | ✅ (regime, strategy_mutations, cartography) | Publisher + Consumer migration | 2 |
| **Risk Guardian** | ✅ | ✅ (signals, fills, regime, cartography, risk_requests) | Publisher + Consumer + sync reply migration | 3 |
| **Execution Sniper** | ✅ | ✅ (risk_decisions) | Publisher + Consumer + sync request migration | 3 |
| **Execution Tracker** | ✅ (positions, fills) | ✅ (orders) | Publisher + Consumer migration | 2 |
| **Trade Philosopher** | ✅ | ✅ (fills, positions) | Publisher + Consumer migration | 2 |
| **Strategy Geneticist** | ✅ | ✅ (analytics, regime, fills) | Publisher + Consumer migration | 2 |
| **Market Cartographer** | ✅ | ✅ (regime, fills) | Publisher + Consumer migration | 2 |
| **Orchestrator** | ✅ (alerts) | ✅ (health) | Publisher + Consumer migration | 1 |
| **Macro Agent** | ✅ | ✅ (regime) | Publisher + Consumer migration | 1 |
| **Telegram Bot** | ❌ | ✅ (positions, pnl, risk) | Consumer migration only | 1 |
| **FastAPI** | ❌ | ✅ (reads Redis state) | No changes (reads state, not streams) | 0 |
| **Supervisor** | ✅ (health commands) | ✅ (health) | Publisher + Consumer migration | 1 |
| **Shared library** | — | — | New `tsar/messaging/` package | 5 |
| **Tests** | — | — | Update all message fixtures | 3 |
| **Documentation** | — | — | Update architecture docs | 2 |
| **TOTAL** | | | | **30 days** |

### 6.2 Per-Component Change Details

#### Regime Detector
```python
# BEFORE (legacy)
await self.redis.xadd("tsar:stream:regime", {
    "msg_id": str(ulid.new()),
    "timestamp_ns": str(time.time_ns()),
    "source_agent": "regime_detector",
    "msg_type": "regime_change",
    "payload": msgpack.packb(regime.to_dict()),
    ...
})

# AFTER (CloudEvents)
await self.publisher.publish(
    stream="tsar:stream:regime",
    source_agent="regime_detector",
    event_type="regime.changed",
    data=regime.to_dict(),
    priority=Priority.HIGH,
)
```

**Changes:**
- `publisher.py`: Replace manual `XADD` with `DualModePublisher`
- `agent.py`: Replace stream reads with `DualModeConsumer`
- `llm_explainer.py`: No changes (doesn't handle messages)

#### Signal Scout
```python
# AFTER
await self.publisher.publish(
    stream="tsar:stream:signals",
    source_agent="signal_scout",
    event_type="signal.detected",
    data=signal.to_dict(),
    trace_id=signal.trace_id,
    priority=Priority.HIGH,
    risk_level=RiskLevel.NONE,
    agent_role="TRADE_PREVIEW",
)
```

**Changes:**
- `publisher.py`: Replace with dual-mode publisher
- `agent.py`: Update stream reads for regime, strategy_mutations, cartography
- `strategy_registry.py`: No changes
- `regime_adapter.py`: No changes (receives parsed envelopes)

#### Risk Guardian (CRITICAL PATH)
```python
# Sync request-reply pattern must be preserved
# BEFORE
await self.redis.xadd("tsar:stream:risk_requests", {
    "order": msgpack.packb(order.to_dict()),
    "reply_to": reply_channel,
    "timeout_ms": str(timeout_ms),
})

# AFTER (CloudEvents)
envelope = CloudEventsEnvelope.create(
    source_agent="execution_sniper",
    event_type="risk.approval_request",
    data={"order": order.to_dict(), "reply_to": reply_channel},
    priority=Priority.CRITICAL,
    risk_level=RiskLevel.HIGH,
    agent_role="TRADE_EXECUTE",
)
await self.redis.xadd("tsar:stream:risk_requests", envelope.to_redis_fields())
```

**Changes:**
- `publisher.py`: Replace with dual-mode publisher (including sync reply)
- `agent.py`: Update all stream reads (signals, fills, regime, cartography, risk_requests)
- `decision_engine.py`: No changes (receives parsed envelopes)
- `config.py`: No changes
- `llm_advisor.py`: No changes
- **Special handling:** Sync reply stream must also use CloudEvents format

#### Execution Sniper (CRITICAL PATH)
**Changes:**
- `publisher.py`: CloudEvents for orders stream
- `agent.py`: CloudEvents for risk_decisions read, risk_requests write, risk_reply read
- `config.py`: No changes

#### Execution Tracker
**Changes:**
- `publisher.py`: CloudEvents for positions and fills streams
- `agent.py`: CloudEvents for orders stream read
- No changes to Rust engines (PyO3 boundary)

#### Trade Philosopher
**Changes:**
- `publisher.py`: CloudEvents for analytics stream
- `agent.py`: CloudEvents for fills and positions stream reads
- `analysis_pipeline.py`: No changes
- `llm_narrator.py`: No changes

#### Strategy Geneticist
**Changes:**
- `publisher.py`: CloudEvents for strategy_mutations stream
- `agent.py`: CloudEvents for analytics, regime, fills stream reads
- `evolution_pipeline.py`: No changes
- `llm_strategist.py`: No changes

#### Market Cartographer
**Changes:**
- `publisher.py`: CloudEvents for cartography stream
- `agent.py`: CloudEvents for regime and fills stream reads
- No changes to Rust engines

#### Orchestrator
**Changes:**
- `publisher.py`: CloudEvents for system alerts
- `agent.py`: CloudEvents for health stream reads
- Minimal effort

#### Macro Agent
**Changes:**
- `publisher.py`: CloudEvents for macro, sentiment, onchain streams
- `agent.py`: CloudEvents for regime stream reads

#### Telegram Bot
**Changes:**
- Update stream reads to use `DualModeConsumer`
- No publishing changes

#### FastAPI
**No changes.** FastAPI reads Redis state hashes, not streams.

### 6.3 Shared Library Changes

New package: `tsar/messaging/`

```
tsar/messaging/
├── __init__.py                    # Public API exports
├── cloudevents_envelope.py        # CloudEventsEnvelope class
├── publisher.py                   # DualModePublisher
├── consumer.py                    # DualModeConsumer
├── types.py                       # Priority, RiskLevel, event type constants
├── validation.py                  # CloudEvents validation
├── compat.py                      # Legacy ↔ CloudEvents converters (Phase 1-2)
└── tests/
    ├── test_envelope.py           # Envelope serialization tests
    ├── test_publisher.py          # Publisher mode tests
    ├── test_consumer.py           # Consumer format detection tests
    ├── test_compat.py             # Legacy compatibility tests
    └── test_integration.py        # Redis integration tests
```

### 6.4 Effort Summary

| Category | Days | Notes |
|----------|------|-------|
| Shared library | 5 | Core envelope, publisher, consumer |
| Agent migration (8 agents) | 16 | 2 days each (3 for critical path agents) |
| Infrastructure agents | 3 | Orchestrator, Macro, Telegram |
| Test updates | 3 | Fixtures, integration, regression |
| Documentation | 2 | Architecture docs, migration guide |
| Buffer | 3 | Unexpected issues |
| **TOTAL** | **32** | ~6 weeks at 1 engineer |

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# tests/messaging/test_envelope.py

class TestCloudEventsEnvelope:

    def test_create_minimal(self):
        """Envelope with required fields only."""
        env = CloudEventsEnvelope.create(
            source_agent="test_agent",
            event_type="test.event",
            data={"key": "value"},
        )
        assert env.specversion == "1.0"
        assert env.source == "tsar:agent:test_agent"
        assert env.type == "tsar.test.event"
        assert env.data == {"key": "value"}

    def test_roundtrip_json(self):
        """JSON serialization roundtrip."""
        env = CloudEventsEnvelope.create(
            source_agent="signal_scout",
            event_type="signal.detected",
            data={"instrument": "BTC/USDT", "confidence": 0.85},
            trace_id="abc123",
            priority=Priority.HIGH,
        )
        json_str = env.to_json()
        restored = CloudEventsEnvelope.from_json(json_str)
        assert restored.id == env.id
        assert restored.type == env.type
        assert restored.data["instrument"] == "BTC/USDT"

    def test_roundtrip_msgpack(self):
        """MessagePack serialization roundtrip."""
        env = CloudEventsEnvelope.create(
            source_agent="risk_guardian",
            event_type="risk.veto",
            data={"reason": "daily_loss_limit"},
            priority=Priority.CRITICAL,
        )
        raw = env.to_msgpack()
        restored = CloudEventsEnvelope.from_msgpack(raw)
        assert restored.id == env.id
        assert restored.priority == Priority.CRITICAL

    def test_roundtrip_redis_fields(self):
        """Redis Streams field serialization roundtrip."""
        env = CloudEventsEnvelope.create(
            source_agent="execution_sniper",
            event_type="order.placed",
            data={"order_id": "ORD-001", "symbol": "BTC/USDT"},
        )
        fields = env.to_redis_fields()
        restored = CloudEventsEnvelope.from_redis_fields(fields)
        assert restored.id == env.id
        assert restored.data["order_id"] == "ORD-001"

    def test_validation_rejects_missing_required(self):
        """Missing required attributes raises error."""
        with pytest.raises(CloudEventsValidationError):
            CloudEventsEnvelope.from_dict({"type": "tsar.test.event"})

    def test_validation_rejects_bad_type_prefix(self):
        """Type must start with 'tsar.'."""
        with pytest.raises(CloudEventsValidationError):
            CloudEventsEnvelope.from_dict({
                "specversion": "1.0",
                "id": "test",
                "source": "tsar:agent:test",
                "type": "invalid.type",
            })

    def test_validation_rejects_bad_source_prefix(self):
        """Source must start with 'tsar:agent:'."""
        with pytest.raises(CloudEventsValidationError):
            CloudEventsEnvelope.from_dict({
                "specversion": "1.0",
                "id": "test",
                "source": "invalid_source",
                "type": "tsar.test.event",
            })

    def test_legacy_to_cloudevents_conversion(self):
        """Legacy MessageEnvelope converts to CloudEvents."""
        env = legacy_to_cloudevents(
            msg_id="01JZ8XQZKJ5N7YR3V4M9P2W6T8",
            timestamp_ns=1753337400123456789,
            source_agent="signal_scout",
            msg_type="signal",
            version=1,
            payload={"instrument": "BTC/USDT"},
            trace_id="abc123",
            priority=1,
        )
        assert env.type == "tsar.signal.detected"
        assert env.source == "tsar:agent:signal_scout"
        assert env.agent_id == "signal_scout"

    def test_cloudevents_to_legacy_conversion(self):
        """CloudEvents converts back to legacy format."""
        env = CloudEventsEnvelope.create(
            source_agent="risk_guardian",
            event_type="risk.veto",
            data={"reason": "test"},
        )
        legacy = cloudevents_to_legacy(env)
        assert legacy["source_agent"] == "risk_guardian"
        assert legacy["msg_type"] == "veto"

    def test_timestamp_ns_conversion(self):
        """ISO 8601 ↔ nanosecond epoch conversion is lossless."""
        ns = 1753337400123456789
        iso = nanoseconds_to_iso8601(ns)
        restored = iso8601_to_nanoseconds(iso)
        assert restored == ns
```

### 7.2 Integration Tests

```python
# tests/messaging/test_integration.py

class TestRedisIntegration:

    async def test_publish_and_consume_cloudevents(self, redis_client):
        """Publish CloudEvents, consume and verify."""
        publisher = DualModePublisher(redis_client, PublishMode.CLOUDEVENTS)
        consumer = DualModeConsumer(redis_client)

        # Publish
        await publisher.publish(
            stream="tsar:stream:test",
            source_agent="test_agent",
            event_type="test.event",
            data={"key": "value"},
        )

        # Consume
        messages = await consumer.read(
            {"tsar:stream:test": "0"},
            count=1,
            block_ms=1000,
        )

        assert len(messages) == 1
        _, _, envelope = messages[0]
        assert envelope.type == "tsar.test.event"
        assert envelope.data["key"] == "value"

    async def test_dual_mode_both_formats(self, redis_client):
        """Dual mode publishes to both streams."""
        publisher = DualModePublisher(redis_client, PublishMode.DUAL)

        await publisher.publish(
            stream="tsar:stream:test",
            source_agent="test_agent",
            event_type="test.event",
            data={"key": "value"},
        )

        # Check primary stream has CloudEvents format
        ce_messages = await redis_client.xread(
            {"tsar:stream:test": "0"}, count=1
        )
        assert b"ce_specversion" in ce_messages[0][1][0][1]

        # Check legacy compat stream has legacy format
        legacy_messages = await redis_client.xread(
            {"tsar:stream:test:legacy": "0"}, count=1
        )
        assert b"msg_id" in legacy_messages[0][1][0][1]

    async def test_consumer_auto_detects_format(self, redis_client):
        """Consumer handles both formats transparently."""
        consumer = DualModeConsumer(redis_client)

        # Manually insert legacy format
        await redis_client.xadd("tsar:stream:test", {
            "msg_id": "test-001",
            "timestamp_ns": "1234567890",
            "source_agent": "test_agent",
            "msg_type": "signal",
            "version": "1",
            "payload": msgpack.packb({"instrument": "BTC"}),
            "trace_id": "",
            "priority": "2",
        })

        # Consumer should parse it
        messages = await consumer.read(
            {"tsar:stream:test": "0"}, count=1, block_ms=1000
        )
        assert len(messages) == 1
        _, _, envelope = messages[0]
        assert envelope.type == "tsar.signal.detected"  # Mapped
        assert envelope.data["instrument"] == "BTC"

    async def test_consumer_group_compatibility(self, redis_client):
        """Consumer groups work with CloudEvents format."""
        publisher = DualModePublisher(redis_client, PublishMode.CLOUDEVENTS)
        consumer = DualModeConsumer(redis_client)

        # Create consumer group
        try:
            await redis_client.xgroup_create(
                "tsar:stream:ce_test", "test_group", id="0", mkstream=True
            )
        except Exception:
            pass  # Group may already exist

        # Publish messages
        for i in range(5):
            await publisher.publish(
                stream="tsar:stream:ce_test",
                source_agent="test_agent",
                event_type="test.event",
                data={"index": i},
            )

        # Consume via group
        messages = await consumer.readgroup(
            group="test_group",
            consumer="consumer_1",
            streams={"tsar:stream:ce_test": ">"},
            count=5,
            block_ms=1000,
        )

        assert len(messages) == 5
        for _, _, envelope in messages:
            assert envelope.type == "tsar.test.event"

        # Acknowledge
        for _, msg_id, _ in messages:
            await redis_client.xack(
                "tsar:stream:ce_test", "test_group", msg_id
            )
```

### 7.3 Migration Regression Tests

```python
# tests/migration/test_regression.py

class TestMigrationRegression:

    async def test_all_message_types_roundtrip(self):
        """Every legacy message type converts to CloudEvents and back."""
        for legacy_type, ce_type in MSG_TYPE_MAP.items():
            env = legacy_to_cloudevents(
                msg_id=str(ulid.new()),
                timestamp_ns=time.time_ns(),
                source_agent="test_agent",
                msg_type=legacy_type,
                version=1,
                payload={"test": True},
            )
            assert env.type == ce_type, f"Type mismatch for {legacy_type}"

            legacy = cloudevents_to_legacy(env)
            assert legacy["msg_type"] == legacy_type

    async def test_priority_preserved_through_migration(self):
        """Priority values survive legacy → CE → legacy conversion."""
        for p in range(4):
            env = legacy_to_cloudevents(
                msg_id="test", timestamp_ns=0,
                source_agent="test", msg_type="signal",
                version=1, payload={}, priority=p,
            )
            legacy = cloudevents_to_legacy(env)
            assert legacy["priority"] == p

    async def test_trace_id_preserved(self):
        """Trace IDs survive format conversion."""
        trace_id = "abc123def456789"
        env = legacy_to_cloudevents(
            msg_id="test", timestamp_ns=0,
            source_agent="test", msg_type="signal",
            version=1, payload={}, trace_id=trace_id,
        )
        assert env.traceid == trace_id
        legacy = cloudevents_to_legacy(env)
        assert legacy["trace_id"] == trace_id
```

---

## 8. Rollback Procedures

### 8.1 Emergency Rollback (Phase 1)

```bash
#!/bin/bash
# rollback_phase1.sh — Revert to legacy-only mode

# 1. Update configuration
kubectl set env deployment/tsar-agents MESSAGING_MODE=legacy

# 2. Restart all agents (rolling restart)
kubectl rollout restart deployment/tsar-agents

# 3. Verify legacy format on streams
redis-cli XREVRANGE tsar:stream:signals + - COUNT 1

# 4. Clean up legacy compat streams
redis-cli DEL tsar:stream:signals:legacy
redis-cli DEL tsar:stream:risk_decisions:legacy
# ... etc for all streams

echo "Rollback to legacy mode complete"
```

### 8.2 Emergency Rollback (Phase 2)

```bash
#!/bin/bash
# rollback_phase2.sh — Revert to dual mode

# 1. Update image to Phase 1 build
kubectl set image deployment/tsar-agents \
  tsar-agents=tsar:v0.x-dual-mode

# 2. Restart
kubectl rollout restart deployment/tsar-agents

# 3. Verify dual output
redis-cli XREVRANGE tsar:stream:signals + - COUNT 1
# Should see ce_* fields

redis-cli XREVRANGE tsar:stream:signals:legacy + - COUNT 1
# Should see msg_id fields

echo "Rollback to dual mode complete"
```

### 8.3 Data Integrity Verification

```python
# scripts/verify_migration.py
"""Run after each phase to verify data integrity."""

async def verify_stream_integrity(stream_name: str, expected_format: str):
    """Verify all messages in a stream are in the expected format."""
    redis = aioredis.from_url("redis://localhost:6379")
    consumer = DualModeConsumer(redis)

    messages = await consumer.read({stream_name: "0"}, count=100, block_ms=100)
    legacy_count = 0
    ce_count = 0

    for _, _, envelope in messages:
        # Check if we can roundtrip
        raw = envelope.to_msgpack()
        restored = CloudEventsEnvelope.from_msgpack(raw)
        assert restored.id == envelope.id, f"Roundtrip failed for {envelope.id}"

        if envelope.specversion == "1.0":
            ce_count += 1
        else:
            legacy_count += 1

    print(f"Stream: {stream_name}")
    print(f"  CloudEvents: {ce_count}")
    print(f"  Legacy: {legacy_count}")

    if expected_format == "cloudevents":
        assert legacy_count == 0, f"Found {legacy_count} legacy messages in CE-only stream"
    elif expected_format == "dual":
        assert ce_count > 0, "No CloudEvents messages found"

    print("  ✅ PASSED")
```

---

## Appendix A: CloudEvents Spec Compliance Checklist

| Requirement | Status | Notes |
|-------------|--------|-------|
| `specversion` required | ✅ | Always `"1.0"` |
| `id` required | ✅ | ULID, globally unique |
| `source` required | ✅ | `tsar:agent:{agent_id}` URI format |
| `type` required | ✅ | `tsar.{domain}.{action}` hierarchical |
| `time` optional | ✅ | ISO 8601 with nanosecond precision |
| `datacontenttype` optional | ✅ | `application/msgpack` or `application/json` |
| `subject` optional | ✅ | Available, not required |
| Extension attributes | ✅ | traceid, priority, risklevel, agentrole, tradingmode, schemaver |
| Binary content mode | ✅ | MessagePack payload in `data` field |
| JSON content mode | ✅ | JSON payload in `data` field |
| Attribute naming | ✅ | Lowercase, no reserved words used |
| Type validation | ✅ | Hierarchical, `tsar.` prefix enforced |
| Source validation | ✅ | URI format, `tsar:agent:` prefix enforced |

## Appendix B: Message Type Registry

Complete mapping from legacy to CloudEvents for reference:

| Legacy `msg_type` | CloudEvents `type` | Domain | Stream |
|-------------------|-------------------|--------|--------|
| `regime_change` | `tsar.regime.changed` | regime | `tsar:stream:regime` |
| `regime_update` | `tsar.regime.updated` | regime | `tsar:stream:regime` |
| `signal` | `tsar.signal.detected` | signal | `tsar:stream:signals` |
| `signal_expired` | `tsar.signal.expired` | signal | `tsar:stream:signals` |
| `risk_decision` | `tsar.risk.decision` | risk | `tsar:stream:risk_decisions` |
| `veto` | `tsar.risk.veto` | risk | `tsar:stream:risk_decisions` |
| `veto_all` | `tsar.risk.veto_all` | risk | `tsar:stream:risk_decisions` |
| `order_placed` | `tsar.order.placed` | order | `tsar:stream:orders` |
| `order_filled` | `tsar.order.filled` | order | `tsar:stream:orders` |
| `order_cancelled` | `tsar.order.cancelled` | order | `tsar:stream:orders` |
| `order_rejected` | `tsar.order.rejected` | order | `tsar:stream:orders` |
| `fill` | `tsar.fill.executed` | fill | `tsar:stream:fills` |
| `partial_fill` | `tsar.fill.partial` | fill | `tsar:stream:fills` |
| `position_update` | `tsar.position.updated` | position | `tsar:stream:positions` |
| `position_closed` | `tsar.position.closed` | position | `tsar:stream:positions` |
| `portfolio_snapshot` | `tsar.position.snapshot` | position | `tsar:stream:positions` |
| `trade_analysis` | `tsar.analytics.trade_completed` | analytics | `tsar:stream:analytics` |
| `pattern_report` | `tsar.analytics.pattern_report` | analytics | `tsar:stream:analytics` |
| `strategy_mutation` | `tsar.strategy.mutated` | strategy | `tsar:stream:strategy_mutations` |
| `strategy_retired` | `tsar.strategy.retired` | strategy | `tsar:stream:strategy_mutations` |
| `correlation_update` | `tsar.cartography.correlation_updated` | cartography | `tsar:stream:cartography` |
| `cointegration_test` | `tsar.cartography.cointegration_result` | cartography | `tsar:stream:cartography` |
| `anomaly` | `tsar.cartography.anomaly_detected` | cartography | `tsar:stream:cartography` |
| `heartbeat` | `tsar.health.heartbeat` | health | `tsar:stream:health` |
| `agent_error` | `tsar.health.error` | health | `tsar:stream:health` |
| `agent_shutdown` | `tsar.health.shutdown` | health | `tsar:stream:health` |
| `bootstrap_complete` | `tsar.system.bootstrap_complete` | system | `tsar:stream:health` |
| `mode_change` | `tsar.system.mode_changed` | system | `tsar:stream:health` |

## Appendix C: References

| Resource | URL |
|----------|-----|
| CloudEvents Spec v1.0 | https://cloudevents.io/ |
| CloudEvents GitHub | https://github.com/cloudevents/spec |
| CloudEvents SDK Python | https://github.com/cloudevents/sdk-python |
| ULID Spec | https://github.com/ulid/spec |
| MessagePack | https://msgpack.org/ |
| Redis Streams | https://redis.io/docs/data-types/streams/ |

---

*FIX-03 specification completed: 2026-07-24 04:30 GMT+8*
*Migration preserves all trading-specific functionality while adopting industry-standard CloudEvents.*
