"""
CloudEvents v1.0 — Event envelope creation, validation, and serialization.

All inter-agent messages use the CloudEvents v1.0 spec:
  specversion: "1.0"
  id: ULID (globally unique, time-sortable)
  source: "tsar:agent:{name}"
  type: "tsar.{domain}.{action}.v1"
  time: RFC3339
  datacontenttype: "application/msgpack"

TSAR extensions: traceid, priority, risklevel, agentrole, tradingmode, schemaver
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import msgpack

# ═══════════════════════════════════════════════════════════════════════
# CloudEvent Dataclass
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CloudEvent:
    """A CloudEvents v1.0 envelope with TSAR extensions.

    Immutable dataclass representing a single event in the TSAR
    messaging system.  All fields map directly to the CloudEvents
    specification plus TSAR-specific extensions.

    Attributes:
        specversion: CloudEvents spec version (always "1.0").
        id: Globally unique event identifier (ULID).
        source: Event source (e.g. "tsar:agent:signal_scout").
        type: Event type (e.g. "tsar.signal.detected.v1").
        time: RFC3339 timestamp of the event.
        datacontenttype: Content type of the data payload.
        data: The event payload.
        traceid: W3C-compatible distributed trace ID.
        priority: 0=critical, 1=high, 2=normal, 3=low.
        risklevel: NONE|LOW|MEDIUM|HIGH|CRITICAL.
        agentrole: READ|ANALYSIS|TRADE_PREVIEW|TRADE_EXECUTE|TRADE_ADMIN.
        tradingmode: paper|live.
        schemaver: Payload schema version number.
    """

    # CloudEvents required attributes
    specversion: str = "1.0"
    id: str = ""
    source: str = ""
    type: str = ""
    time: str = ""
    datacontenttype: str = "application/msgpack"
    data: dict[str, Any] = field(default_factory=dict)

    # TSAR extensions
    traceid: str = ""
    priority: int = 2
    risklevel: str = "NONE"
    agentrole: str = "READ"
    tradingmode: str = "paper"
    schemaver: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (suitable for JSON/MessagePack encoding)."""
        return {
            "specversion": self.specversion,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time,
            "datacontenttype": self.datacontenttype,
            "data": self.data,
            "traceid": self.traceid,
            "priority": self.priority,
            "risklevel": self.risklevel,
            "agentrole": self.agentrole,
            "tradingmode": self.tradingmode,
            "schemaver": self.schemaver,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def to_msgpack(self) -> bytes:
        """Serialize to MessagePack bytes."""
        return msgpack.packb(self.to_dict(), use_bin_type=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CloudEvent:
        """Deserialize from a plain dict."""
        return cls(
            specversion=d.get("specversion", "1.0"),
            id=d.get("id", ""),
            source=d.get("source", ""),
            type=d.get("type", ""),
            time=d.get("time", ""),
            datacontenttype=d.get("datacontenttype", "application/msgpack"),
            data=d.get("data", {}),
            traceid=d.get("traceid", ""),
            priority=d.get("priority", 2),
            risklevel=d.get("risklevel", "NONE"),
            agentrole=d.get("agentrole", "READ"),
            tradingmode=d.get("tradingmode", "paper"),
            schemaver=d.get("schemaver", 1),
        )

    @classmethod
    def from_json(cls, s: str) -> CloudEvent:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(s))

    @classmethod
    def from_msgpack(cls, data: bytes) -> CloudEvent:
        """Deserialize from MessagePack bytes."""
        return cls.from_dict(msgpack.unpackb(data, raw=False))


# ═══════════════════════════════════════════════════════════════════════
# Factory function (backward-compatible with dict-based API)
# ═══════════════════════════════════════════════════════════════════════


def create_event(
    source: str,
    event_type: str,
    data: dict[str, Any],
    priority: int = 2,
    risk_level: str = "NONE",
    agent_role: str = "READ",
    trading_mode: str = "paper",
    trace_id: str | None = None,
    schema_version: int = 1,
) -> CloudEvent:
    """Create a CloudEvents v1.0 envelope.

    Args:
        source: Event source (e.g., "tsar:agent:signal_scout").
        event_type: Event type (e.g., "tsar.signal.detected.v1").
        data: Event payload.
        priority: 0=critical, 1=high, 2=normal, 3=low.
        risk_level: NONE|LOW|MEDIUM|HIGH|CRITICAL.
        agent_role: READ|ANALYSIS|TRADE_PREVIEW|TRADE_EXECUTE|TRADE_ADMIN.
        trading_mode: paper|live.
        trace_id: Distributed tracing ID (auto-generated if None).
        schema_version: Payload schema version.

    Returns:
        CloudEvent instance.
    """
    return CloudEvent(
        id=_generate_ulid(),
        source=source,
        type=event_type,
        time=datetime.now(UTC).isoformat(),
        data=data,
        traceid=trace_id or _generate_trace_id(),
        priority=priority,
        risklevel=risk_level,
        agentrole=agent_role,
        tradingmode=trading_mode,
        schemaver=schema_version,
    )


# ═══════════════════════════════════════════════════════════════════════
# Serialization helpers
# ═══════════════════════════════════════════════════════════════════════


def encode_event(event: CloudEvent | dict[str, Any]) -> bytes:
    """Encode a CloudEvent to MessagePack bytes for Redis.

    Args:
        event: CloudEvent instance or dict.

    Returns:
        MessagePack-encoded bytes.
    """
    if isinstance(event, CloudEvent):
        return event.to_msgpack()
    return msgpack.packb(event, use_bin_type=True)


def decode_event(data: bytes) -> CloudEvent:
    """Decode a MessagePack-encoded CloudEvent from Redis.

    Args:
        data: MessagePack bytes.

    Returns:
        CloudEvent instance.
    """
    return CloudEvent.from_msgpack(data)


# ═══════════════════════════════════════════════════════════════════════
# Redis Stream helpers
# ═══════════════════════════════════════════════════════════════════════


def to_redis_fields(event: CloudEvent | dict[str, Any]) -> dict[str, str]:
    """Convert a CloudEvent to Redis Stream fields (ce_ prefixed).

    Args:
        event: CloudEvent instance or dict.

    Returns:
        Dict of string key-value pairs for Redis XADD.
    """
    d = event.to_dict() if isinstance(event, CloudEvent) else event

    fields: dict[str, str] = {
        "ce_specversion": str(d["specversion"]),
        "ce_id": str(d["id"]),
        "ce_source": str(d["source"]),
        "ce_type": str(d["type"]),
        "ce_time": str(d["time"]),
        "ce_datacontenttype": str(d["datacontenttype"]),
        "ce_traceid": str(d.get("traceid", "")),
        "ce_priority": str(d.get("priority", 2)),
        "ce_risklevel": str(d.get("risklevel", "NONE")),
        "ce_agentrole": str(d.get("agentrole", "READ")),
        "ce_tradingmode": str(d.get("tradingmode", "paper")),
        "ce_schemaver": str(d.get("schemaver", 1)),
    }
    # Encode data payload as MessagePack hex
    fields["ce_data"] = msgpack.packb(d["data"], use_bin_type=True).hex()
    return fields


def from_redis_fields(fields: dict[str, bytes | str]) -> CloudEvent:
    """Parse Redis Stream fields back to a CloudEvent.

    Args:
        fields: Dict from Redis XREAD with ``ce_`` prefixed keys.

    Returns:
        CloudEvent instance.
    """
    def _str(v: bytes | str) -> str:
        return v.decode() if isinstance(v, bytes) else v

    data_hex = _str(fields.get("ce_data", ""))
    data: dict[str, Any] = {}
    if data_hex:
        data = msgpack.unpackb(bytes.fromhex(data_hex), raw=False)

    return CloudEvent(
        specversion=_str(fields.get("ce_specversion", "1.0")),
        id=_str(fields.get("ce_id", "")),
        source=_str(fields.get("ce_source", "")),
        type=_str(fields.get("ce_type", "")),
        time=_str(fields.get("ce_time", "")),
        datacontenttype=_str(fields.get("ce_datacontenttype", "application/msgpack")),
        data=data,
        traceid=_str(fields.get("ce_traceid", "")),
        priority=int(_str(fields.get("ce_priority", "2"))),
        risklevel=_str(fields.get("ce_risklevel", "NONE")),
        agentrole=_str(fields.get("ce_agentrole", "READ")),
        tradingmode=_str(fields.get("ce_tradingmode", "paper")),
        schemaver=int(_str(fields.get("ce_schemaver", "1"))),
    )


# ═══════════════════════════════════════════════════════════════════════
# ID generation
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# TSAR Event Type Constants
# ═══════════════════════════════════════════════════════════════════════

# Shadow Account Loop events
TSAR_SHADOW_EXTRACTED = "tsar.shadow.extracted.v1"
TSAR_RULE_VALIDATED = "tsar.rule.validated.v1"

# Strategy evolution events
TSAR_STRATEGY_PROPOSAL = "tsar.strategy.proposal.v1"

# Mandate lifecycle events
TSAR_MANDATE_COMMITTED = "tsar.mandate.committed.v1"
TSAR_MANDATE_REVOKED = "tsar.mandate.revoked.v1"

# Factor benchmarking events
TSAR_FACTOR_BENCHMARK = "tsar.factor.benchmark.v1"


def _generate_ulid() -> str:
    """Generate a ULID (Universally Unique Lexicographically Sortable Identifier).

    Uses 48-bit millisecond timestamp + 80-bit random component,
    encoded in Crockford Base32.
    """
    ts = int(time.time() * 1000)
    rand = uuid.uuid4().int & ((1 << 80) - 1)
    ulid_int = (ts << 80) | rand
    return _encode_base32(ulid_int)


def _generate_trace_id() -> str:
    """Generate a W3C-compatible trace ID (32 hex chars)."""
    return uuid.uuid4().hex


def _encode_base32(num: int) -> str:
    """Encode integer to Crockford Base32 (26 characters)."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    result: list[str] = []
    for _ in range(26):
        result.append(alphabet[num & 0x1F])
        num >>= 5
    return "".join(reversed(result))
