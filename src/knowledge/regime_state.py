"""TSAR — Regime State.

Knowledge Store #3: Real-time market regime probabilities and state.
Day1: dict-backed (in-process).  Level 2+: Redis-backed.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from src.utils.logging import get_logger

logger = get_logger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class RegimeState:
    probabilities: dict[str, float] = field(default_factory=dict)
    dominant_regime: str = "unknown"
    confidence: float = 0.0
    last_updated: str = field(default_factory=_utcnow_iso)
    model_version: str = ""
    lookback_hours: int = 72
    indicators: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegimeState:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RegimeTransition:
    timestamp: str = field(default_factory=_utcnow_iso)
    from_regime: str = ""
    to_regime: str = ""
    probability_shift: float = 0.0
    trigger: str = ""
    asset: str = "GLOBAL"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegimeTransition:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class _RegimeBackend(Protocol):
    def get_hash(self, key: str) -> dict[str, str]: ...
    def set_hash(self, key: str, mapping: dict[str, str]) -> None: ...
    def delete_key(self, key: str) -> None: ...
    def lpush_trim(self, key: str, value: str, max_len: int) -> None: ...
    def lrange(self, key: str, start: int, stop: int) -> list[str]: ...
    def keys(self, pattern: str) -> list[str]: ...


class _DictBackend:
    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._lists: dict[str, list[str]] = {}

    def get_hash(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    def set_hash(self, key: str, mapping: dict[str, str]) -> None:
        if key not in self._hashes:
            self._hashes[key] = {}
        self._hashes[key].update(mapping)

    def delete_key(self, key: str) -> None:
        self._hashes.pop(key, None)
        self._lists.pop(key, None)

    def lpush_trim(self, key: str, value: str, max_len: int) -> None:
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, value)
        self._lists[key] = self._lists[key][:max_len]

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        lst = self._lists.get(key, [])
        if stop == -1:
            stop = len(lst)
        return lst[start:stop]

    def keys(self, pattern: str) -> list[str]:
        import fnmatch
        all_keys = set(self._hashes.keys()) | set(self._lists.keys())
        return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]


class _RedisBackend:
    def __init__(self, redis_client: Any) -> None:
        self._r = redis_client

    def get_hash(self, key: str) -> dict[str, str]:
        raw = self._r.hgetall(key)
        return {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in raw.items()}

    def set_hash(self, key: str, mapping: dict[str, str]) -> None:
        if mapping:
            self._r.hset(key, mapping=mapping)

    def delete_key(self, key: str) -> None:
        self._r.delete(key)

    def lpush_trim(self, key: str, value: str, max_len: int) -> None:
        pipe = self._r.pipeline()
        pipe.lpush(key, value)
        pipe.ltrim(key, 0, max_len - 1)
        pipe.execute()

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        raw = self._r.lrange(key, start, stop)
        return [v.decode() if isinstance(v, bytes) else v for v in raw]

    def keys(self, pattern: str) -> list[str]:
        raw = self._r.keys(pattern)
        return [k.decode() if isinstance(k, bytes) else k for k in raw]


class RegimeStateStore:
    """Read/write current regime state, per-asset overrides, and transitions.

    Usage::

        store = RegimeStateStore()                       # Day1 (dict)
        store = RegimeStateStore(redis_client=redis)     # Level 2+
        store.update_global_regime(state)
        store.get_effective_regime("BTC/USDT")
    """

    _TRANSITION_MAX = 1000

    def __init__(self, redis_client: Any | None = None, prefix: str = "tsar:regime:") -> None:
        self._prefix = prefix
        self._backend: _RegimeBackend
        if redis_client is not None:
            self._backend = _RedisBackend(redis_client)
            logger.info("regime_backend", backend="redis")
        else:
            self._backend = _DictBackend()
            logger.info("regime_backend", backend="dict")

    def _key(self, *parts: str) -> str:
        return self._prefix + ":".join(parts)

    def update_global_regime(self, state: RegimeState) -> None:
        mapping = {
            **{k: str(v) for k, v in state.probabilities.items()},
            "dominant_regime": state.dominant_regime,
            "confidence": str(state.confidence),
            "last_updated": state.last_updated,
            "model_version": state.model_version,
            "lookback_hours": str(state.lookback_hours),
        }
        self._backend.set_hash(self._key("current"), mapping)
        logger.info("global_regime_updated", dominant=state.dominant_regime, confidence=state.confidence)

    def get_global_regime(self) -> RegimeState | None:
        raw = self._backend.get_hash(self._key("current"))
        if not raw:
            return None
        scalar_keys = {"dominant_regime", "confidence", "last_updated", "model_version", "lookback_hours"}
        probs: dict[str, float] = {}
        for k, v in raw.items():
            if k not in scalar_keys:
                with contextlib.suppress(ValueError, TypeError):
                    probs[k] = float(v)
        return RegimeState(
            probabilities=probs,
            dominant_regime=raw.get("dominant_regime", "unknown"),
            confidence=float(raw.get("confidence", 0)),
            last_updated=raw.get("last_updated", ""),
            model_version=raw.get("model_version", ""),
            lookback_hours=int(raw.get("lookback_hours", 72)),
        )

    def update_asset_regime(self, symbol: str, state: RegimeState) -> None:
        mapping = {
            "regime_probs": json.dumps(state.probabilities),
            "dominant_regime": state.dominant_regime,
            "confidence": str(state.confidence),
            "last_updated": state.last_updated,
        }
        self._backend.set_hash(self._key("asset", symbol), mapping)
        logger.debug("asset_regime_updated", symbol=symbol, dominant=state.dominant_regime)

    def get_asset_regime(self, symbol: str) -> RegimeState | None:
        raw = self._backend.get_hash(self._key("asset", symbol))
        if not raw:
            return None
        probs = json.loads(raw.get("regime_probs", "{}"))
        return RegimeState(
            probabilities=probs,
            dominant_regime=raw.get("dominant_regime", "unknown"),
            confidence=float(raw.get("confidence", 0)),
            last_updated=raw.get("last_updated", ""),
        )

    def get_effective_regime(self, symbol: str) -> RegimeState:
        asset = self.get_asset_regime(symbol)
        if asset is not None:
            return asset
        global_state = self.get_global_regime()
        if global_state is not None:
            return global_state
        return RegimeState()

    def delete_asset_regime(self, symbol: str) -> None:
        self._backend.delete_key(self._key("asset", symbol))

    def list_asset_regimes(self) -> list[str]:
        raw_keys = self._backend.keys(self._key("asset", "*"))
        prefix = self._key("asset", "")
        return [k.replace(prefix, "") for k in raw_keys]

    def record_transition(self, transition: RegimeTransition) -> None:
        payload = json.dumps(transition.to_dict())
        self._backend.lpush_trim(self._key("transitions"), payload, self._TRANSITION_MAX)
        logger.info("regime_transition", from_regime=transition.from_regime, to_regime=transition.to_regime)

    def get_recent_transitions(self, limit: int = 50) -> list[RegimeTransition]:
        raw = self._backend.lrange(self._key("transitions"), 0, limit - 1)
        return [RegimeTransition.from_dict(json.loads(r)) for r in raw]

    def update_indicators(self, indicators: dict[str, Any]) -> None:
        mapping = {k: json.dumps(v) if not isinstance(v, str) else str(v) for k, v in indicators.items()}
        self._backend.set_hash(self._key("indicators"), mapping)

    def get_indicators(self) -> dict[str, Any]:
        raw = self._backend.get_hash(self._key("indicators"))
        result: dict[str, Any] = {}
        for k, v in raw.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result

    def snapshot_to_dict(self) -> dict[str, Any]:
        global_state = self.get_global_regime()
        assets: dict[str, Any] = {}
        for sym in self.list_asset_regimes():
            asset_state = self.get_asset_regime(sym)
            if asset_state:
                assets[sym] = asset_state.to_dict()
        return {
            "global": global_state.to_dict() if global_state else None,
            "assets": assets,
            "indicators": self.get_indicators(),
            "snapshot_at": _utcnow_iso(),
        }
