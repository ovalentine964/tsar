"""TSAR — Regime State with Temporal Graph.

Knowledge Store #3: Real-time market regime probabilities, state,
and temporal regime transition graph with Markov transition probabilities.

Models: "regime A → regime B with probability P in time T"

Day1: dict-backed (in-process).  Level 2+: Redis-backed.
"""

from __future__ import annotations

import contextlib
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Generator

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


# ══════════════════════════════════════════════════════════════
# TEMPORAL REGIME GRAPH
# ══════════════════════════════════════════════════════════════


@dataclass
class RegimeTransitionEdge:
    """A single edge in the regime transition graph.

    Models: from_regime → to_regime with probability P, observed in time T.
    """
    from_regime: str = ""
    to_regime: str = ""
    probability: float = 0.0          # P(to | from) — conditional probability
    observation_count: int = 0        # number of times this transition was observed
    avg_duration_hours: float = 0.0   # average time spent in from_regime before transition
    min_duration_hours: float = 0.0
    max_duration_hours: float = 0.0
    last_observed: str = ""
    asset: str = "GLOBAL"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegimeTransitionEdge:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RegimeGraphSnapshot:
    """A point-in-time snapshot of the regime transition graph."""
    edges: list[RegimeTransitionEdge] = field(default_factory=list)
    regimes: list[str] = field(default_factory=list)
    total_observations: int = 0
    computed_at: str = field(default_factory=_utcnow_iso)
    asset: str = "GLOBAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "edges": [e.to_dict() for e in self.edges],
            "regimes": self.regimes,
            "total_observations": self.total_observations,
            "computed_at": self.computed_at,
            "asset": self.asset,
        }

    def get_transition_matrix(self) -> dict[str, dict[str, float]]:
        """Return the transition probability matrix as nested dict."""
        matrix: dict[str, dict[str, float]] = {}
        for edge in self.edges:
            if edge.from_regime not in matrix:
                matrix[edge.from_regime] = {}
            matrix[edge.from_regime][edge.to_regime] = edge.probability
        return matrix

    def steady_state(self, iterations: int = 100) -> dict[str, float]:
        """Compute steady-state distribution via power iteration.

        Returns the long-run probability of being in each regime.
        """
        if not self.regimes:
            return {}
        n = len(self.regimes)
        matrix = self.get_transition_matrix()

        # Initialize uniform distribution
        dist = {r: 1.0 / n for r in self.regimes}

        for _ in range(iterations):
            new_dist: dict[str, float] = {}
            for r in self.regimes:
                prob = 0.0
                for src in self.regimes:
                    prob += dist.get(src, 0.0) * matrix.get(src, {}).get(r, 0.0)
                new_dist[r] = prob
            dist = new_dist

        # Normalize
        total = sum(dist.values())
        if total > 0:
            dist = {k: v / total for k, v in dist.items()}
        return dist


@dataclass
class RegimePathProbability:
    """Probability of a specific regime sequence."""
    path: list[str] = field(default_factory=list)
    probability: float = 0.0
    avg_duration_hours: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TemporalRegimeGraph:
    """Temporal regime transition graph with Markov transition probabilities.

    Models regime transitions as a weighted directed graph where:
    - Nodes = market regimes (trending_up, ranging, volatile, etc.)
    - Edges = transitions with probability P and time T
    - Supports: transition queries, path probabilities, steady-state analysis

    Persistence: SQLite (WAL mode, tsar.db)

    Usage::

        graph = TemporalRegimeGraph("/path/to/tsar.db")

        # Record observed transitions
        graph.record_observation(from_regime="ranging", to_regime="trending_up",
                                 duration_hours=4.5)

        # Query transition probabilities
        edges = graph.get_transitions_from("ranging")
        # → [{to_regime: "trending_up", probability: 0.35, avg_duration: 6.2}, ...]

        # Get full graph snapshot
        snapshot = graph.compute_snapshot()
        steady = snapshot.steady_state()
    """

    _MIN_OBSERVATIONS = 3  # minimum observations to include an edge

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Observation recording ────────────────────────────────

    def record_observation(
        self,
        from_regime: str,
        to_regime: str,
        duration_hours: float = 0.0,
        asset: str = "GLOBAL",
        timestamp: str | None = None,
    ) -> None:
        """Record a single regime transition observation.

        Each observation is stored in regime_transitions and the
        aggregated transition graph is updated.
        """
        ts = timestamp or _utcnow_iso()
        with self._conn() as conn:
            # Insert raw observation
            conn.execute("""
                INSERT INTO regime_transitions
                    (from_regime, to_regime, duration_hours, asset, observed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (from_regime, to_regime, duration_hours, asset, ts))

        # Update aggregated graph
        self._rebuild_edge(from_regime, to_regime, asset)

    def _rebuild_edge(self, from_regime: str, to_regime: str, asset: str) -> None:
        """Recompute aggregated edge statistics from raw observations."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) AS obs_count,
                    AVG(duration_hours) AS avg_dur,
                    MIN(duration_hours) AS min_dur,
                    MAX(duration_hours) AS max_dur,
                    MAX(observed_at) AS last_obs
                FROM regime_transitions
                WHERE from_regime = ? AND to_regime = ? AND asset = ?
            """, (from_regime, to_regime, asset)).fetchone()

            if not row:
                return

            # Total transitions from this regime (for probability calculation)
            total_row = conn.execute("""
                SELECT COUNT(*) AS total
                FROM regime_transitions
                WHERE from_regime = ? AND asset = ?
            """, (from_regime, asset)).fetchone()

            total = total_row["total"] if total_row else 1
            prob = row["obs_count"] / total if total > 0 else 0.0

            # Upsert aggregated edge
            conn.execute("""
                INSERT INTO regime_transition_edges
                    (from_regime, to_regime, probability, observation_count,
                     avg_duration_hours, min_duration_hours, max_duration_hours,
                     last_observed, asset)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(from_regime, to_regime, asset) DO UPDATE SET
                    probability = excluded.probability,
                    observation_count = excluded.observation_count,
                    avg_duration_hours = excluded.avg_duration_hours,
                    min_duration_hours = excluded.min_duration_hours,
                    max_duration_hours = excluded.max_duration_hours,
                    last_observed = excluded.last_observed
            """, (
                from_regime, to_regime, prob, row["obs_count"],
                row["avg_dur"] or 0.0, row["min_dur"] or 0.0,
                row["max_dur"] or 0.0, row["last_obs"] or "", asset,
            ))

    # ── Transition queries ───────────────────────────────────

    def get_transitions_from(
        self, from_regime: str, asset: str = "GLOBAL"
    ) -> list[RegimeTransitionEdge]:
        """Get all possible transitions from a regime with probabilities."""
        sql = """
            SELECT * FROM regime_transition_edges
            WHERE from_regime = ? AND asset = ?
            ORDER BY probability DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (from_regime, asset)).fetchall()
        return [RegimeTransitionEdge(**dict(r)) for r in rows]

    def get_transitions_to(
        self, to_regime: str, asset: str = "GLOBAL"
    ) -> list[RegimeTransitionEdge]:
        """Get all transitions that lead to a regime."""
        sql = """
            SELECT * FROM regime_transition_edges
            WHERE to_regime = ? AND asset = ?
            ORDER BY probability DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (to_regime, asset)).fetchall()
        return [RegimeTransitionEdge(**dict(r)) for r in rows]

    def get_transition_probability(
        self, from_regime: str, to_regime: str, asset: str = "GLOBAL"
    ) -> float | None:
        """Get the probability of a specific transition."""
        sql = """
            SELECT probability FROM regime_transition_edges
            WHERE from_regime = ? AND to_regime = ? AND asset = ?
        """
        with self._conn() as conn:
            row = conn.execute(sql, (from_regime, to_regime, asset)).fetchone()
        return row["probability"] if row else None

    def get_most_likely_transition(
        self, from_regime: str, asset: str = "GLOBAL"
    ) -> RegimeTransitionEdge | None:
        """Get the most likely next regime from the current one."""
        transitions = self.get_transitions_from(from_regime, asset)
        return transitions[0] if transitions else None

    # ── Path probability ─────────────────────────────────────

    def compute_path_probability(
        self, path: list[str], asset: str = "GLOBAL"
    ) -> RegimePathProbability:
        """Compute the probability of a specific regime sequence.

        P(path) = P(r1→r2) * P(r2→r3) * ... * P(rn-1→rn)

        Args:
            path: Ordered list of regime names.
            asset: Asset filter.

        Returns:
            RegimePathProbability with the computed probability.
        """
        if len(path) < 2:
            return RegimePathProbability(path=path, probability=1.0)

        prob = 1.0
        total_dur = 0.0
        count = 0
        for i in range(len(path) - 1):
            edge_prob = self.get_transition_probability(path[i], path[i + 1], asset)
            if edge_prob is None:
                return RegimePathProbability(path=path, probability=0.0)
            prob *= edge_prob

            # Get duration info
            transitions = self.get_transitions_from(path[i], asset)
            for t in transitions:
                if t.to_regime == path[i + 1]:
                    total_dur += t.avg_duration_hours
                    count += 1
                    break

        avg_dur = total_dur / count if count > 0 else 0.0
        return RegimePathProbability(
            path=path,
            probability=prob,
            avg_duration_hours=avg_dur,
        )

    # ── Graph snapshot ───────────────────────────────────────

    def compute_snapshot(self, asset: str = "GLOBAL") -> RegimeGraphSnapshot:
        """Compute a full snapshot of the regime transition graph."""
        sql = """
            SELECT * FROM regime_transition_edges
            WHERE asset = ?
            ORDER BY from_regime, probability DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (asset,)).fetchall()

        edges = [RegimeTransitionEdge(**dict(r)) for r in rows]
        regimes = sorted(set(e.from_regime for e in edges) | set(e.to_regime for e in edges))
        total = sum(e.observation_count for e in edges)

        return RegimeGraphSnapshot(
            edges=edges,
            regimes=regimes,
            total_observations=total,
            asset=asset,
        )

    def get_all_assets(self) -> list[str]:
        """Get all assets with recorded transitions."""
        sql = "SELECT DISTINCT asset FROM regime_transitions ORDER BY asset"
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [r["asset"] for r in rows]

    # ── Analysis helpers ─────────────────────────────────────

    def get_regime_durations(
        self, regime: str, asset: str = "GLOBAL"
    ) -> dict[str, float]:
        """Get duration statistics for time spent in a regime."""
        sql = """
            SELECT
                AVG(duration_hours) AS avg_duration,
                MIN(duration_hours) AS min_duration,
                MAX(duration_hours) AS max_duration,
                COUNT(*) AS observation_count
            FROM regime_transitions
            WHERE from_regime = ? AND asset = ?
        """
        with self._conn() as conn:
            row = conn.execute(sql, (regime, asset)).fetchone()
        if not row:
            return {"avg_duration": 0, "min_duration": 0, "max_duration": 0, "count": 0}
        return {
            "avg_duration": row["avg_duration"] or 0,
            "min_duration": row["min_duration"] or 0,
            "max_duration": row["max_duration"] or 0,
            "count": row["observation_count"],
        }

    def predict_regime(
        self, current_regime: str, horizon_hours: float = 24.0, asset: str = "GLOBAL"
    ) -> dict[str, float]:
        """Predict regime probabilities after horizon_hours.

        Uses the transition matrix raised to the power of (horizon / avg_duration)
        to estimate the distribution after the given time horizon.
        """
        snapshot = self.compute_snapshot(asset)
        if not snapshot.edges:
            return {current_regime: 1.0}

        # Estimate number of transition steps
        durations = self.get_regime_durations(current_regime, asset)
        avg_dur = durations.get("avg_duration", 24.0) or 24.0
        steps = max(1, int(horizon_hours / avg_dur))

        # Power iteration for 'steps' transitions
        regimes = snapshot.regimes
        matrix = snapshot.get_transition_matrix()
        dist = {r: 1.0 if r == current_regime else 0.0 for r in regimes}

        for _ in range(steps):
            new_dist: dict[str, float] = {}
            for r in regimes:
                prob = 0.0
                for src in regimes:
                    prob += dist.get(src, 0.0) * matrix.get(src, {}).get(r, 0.0)
                new_dist[r] = prob
            dist = new_dist

        return dist

    # ── Graph stats ──────────────────────────────────────────

    def get_graph_stats(self) -> dict[str, Any]:
        """Return summary statistics for the regime graph."""
        with self._conn() as conn:
            obs_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM regime_transitions"
            ).fetchone()
            edge_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM regime_transition_edges"
            ).fetchone()
            regime_row = conn.execute(
                "SELECT COUNT(DISTINCT from_regime) AS cnt FROM regime_transition_edges"
            ).fetchone()
        return {
            "total_observations": obs_row["cnt"] if obs_row else 0,
            "total_edges": edge_row["cnt"] if edge_row else 0,
            "total_regimes": regime_row["cnt"] if regime_row else 0,
        }
