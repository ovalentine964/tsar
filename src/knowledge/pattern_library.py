"""TSAR — Pattern Library.

Knowledge Store #4: Discovered market patterns with occurrence counts,
success rates, and statistical validation.

Persistence: SQLite (WAL mode, tsar.db)
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)


def _ulid() -> str:
    return uuid.uuid4().hex


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class Pattern:
    pattern_id: str = field(default_factory=_ulid)
    pattern_name: str = ""
    pattern_type: str = "setup"
    description: str = ""
    conditions: str = "{}"
    sample_size: int = 0
    success_rate: Optional[float] = None
    avg_return: Optional[float] = None
    avg_pnl_impact: Optional[float] = None
    avg_duration_hours: Optional[float] = None
    risk_reward: Optional[float] = None
    expectancy: Optional[float] = None
    sharpe_contribution: Optional[float] = None
    confidence: float = 0.5
    last_validated: Optional[str] = None
    last_seen: Optional[str] = None
    decay_rate: float = 0.01
    min_sample_size: int = 10
    example_trade_ids: Optional[str] = None
    chart_embedding_id: Optional[str] = None
    status: str = "candidate"
    discovered_by: Optional[str] = None
    discovered_at: str = field(default_factory=_utcnow_iso)
    tags: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PatternObservation:
    observation_id: str = field(default_factory=_ulid)
    pattern_id: str = ""
    trade_id: Optional[str] = None
    symbol: str = ""
    observed_at: str = field(default_factory=_utcnow_iso)
    timeframe: Optional[str] = None
    price_at_trigger: Optional[float] = None
    regime_at_trigger: Optional[str] = None
    volatility_at_trigger: Optional[float] = None
    volume_at_trigger: Optional[float] = None
    outcome: Optional[str] = None
    pnl_impact: Optional[float] = None
    return_pct: Optional[float] = None
    duration_hours: Optional[float] = None
    max_adverse: Optional[float] = None
    max_favorable: Optional[float] = None
    embedding_id: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PatternRelationship:
    relationship_id: str = field(default_factory=_ulid)
    pattern_a_id: str = ""
    pattern_b_id: str = ""
    relationship: str = "co_occurs"
    strength: Optional[float] = None
    sample_size: Optional[int] = None
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class PatternLibrary:
    """CRUD for patterns, statistical validation, and pattern relationships.

    Usage::

        lib = PatternLibrary("/path/to/tsar.db")
        lib.insert_pattern(pattern)
        lib.record_observation(obs)
        lib.validate_pattern(pattern_id)
    """

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

    # ── Pattern CRUD ─────────────────────────────────────────

    def insert_pattern(self, pattern: Pattern) -> str:
        d = pattern.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO patterns ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        logger.info("pattern_inserted", pattern_id=pattern.pattern_id, name=pattern.pattern_name)
        return pattern.pattern_id

    def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        sql = "SELECT * FROM patterns WHERE pattern_id = ?"
        with self._conn() as conn:
            row = conn.execute(sql, (pattern_id,)).fetchone()
        return Pattern(**dict(row)) if row else None

    def update_pattern(self, pattern_id: str, **fields: Any) -> bool:
        if not fields:
            return False
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["pattern_id"] = pattern_id
        sql = f"UPDATE patterns SET {sets} WHERE pattern_id = :pattern_id"
        with self._conn() as conn:
            cursor = conn.execute(sql, fields)
        if cursor.rowcount > 0:
            logger.info("pattern_updated", pattern_id=pattern_id, fields=list(fields.keys()))
            return True
        return False

    def list_patterns(
        self, pattern_type: Optional[str] = None, status: Optional[str] = None,
        min_confidence: float = 0.0, limit: int = 100
    ) -> list[Pattern]:
        clauses: list[str] = ["confidence >= ?"]
        params: list[Any] = [min_confidence]
        if pattern_type:
            clauses.append("pattern_type = ?")
            params.append(pattern_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses)
        sql = f"SELECT * FROM patterns {where} ORDER BY confidence DESC, expectancy DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Pattern(**dict(r)) for r in rows]

    def get_active_patterns(self) -> list[Pattern]:
        return self.list_patterns(status="active")

    # ── FTS5 search ──────────────────────────────────────────

    def search_patterns(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        clean = re.sub(r"[^\w\s]", "", query)
        terms = [t for t in clean.split() if len(t) > 2]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{t}"' for t in terms)
        sql = """
            SELECT p.*, rank AS bm25_score
            FROM patterns_fts fts
            JOIN patterns p ON p.rowid = fts.rowid
            WHERE patterns_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (fts_query, limit)).fetchall()
        return [dict(r) for r in rows]

    # ── Observations ─────────────────────────────────────────

    def record_observation(self, obs: PatternObservation) -> str:
        d = obs.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO pattern_observations ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        self._update_pattern_stats(obs.pattern_id)
        return obs.observation_id

    def get_observations(
        self, pattern_id: str, outcome: Optional[str] = None, limit: int = 200
    ) -> list[PatternObservation]:
        clauses = ["pattern_id = ?"]
        params: list[Any] = [pattern_id]
        if outcome:
            clauses.append("outcome = ?")
            params.append(outcome)
        where = " AND ".join(clauses)
        sql = f"SELECT * FROM pattern_observations WHERE {where} ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [PatternObservation(**dict(r)) for r in rows]

    def _update_pattern_stats(self, pattern_id: str) -> None:
        sql = """
            SELECT
                COUNT(*) AS sample_size,
                AVG(CASE WHEN outcome = 'win' THEN 1.0 ELSE 0.0 END) AS success_rate,
                AVG(pnl_impact) AS avg_pnl_impact,
                MAX(observed_at) AS last_seen
            FROM pattern_observations
            WHERE pattern_id = ? AND outcome IS NOT NULL AND outcome != 'pending'
        """
        with self._conn() as conn:
            row = conn.execute(sql, (pattern_id,)).fetchone()
        if row and row["sample_size"] and row["sample_size"] > 0:
            self.update_pattern(
                pattern_id,
                sample_size=row["sample_size"],
                success_rate=row["success_rate"],
                avg_pnl_impact=row["avg_pnl_impact"],
                last_seen=row["last_seen"],
            )

    # ── Statistical validation ───────────────────────────────

    def validate_pattern(
        self, pattern_id: str, min_sample_size: Optional[int] = None, min_confidence: float = 0.7
    ) -> dict[str, Any]:
        pattern = self.get_pattern(pattern_id)
        if pattern is None:
            raise ValueError(f"Pattern {pattern_id} not found")
        effective_min = min_sample_size or pattern.min_sample_size
        self._update_pattern_stats(pattern_id)
        pattern = self.get_pattern(pattern_id)
        assert pattern is not None
        result: dict[str, Any] = {
            "pattern_id": pattern_id,
            "sample_size": pattern.sample_size,
            "success_rate": pattern.success_rate,
            "confidence": pattern.confidence,
            "meets_sample_size": pattern.sample_size >= effective_min,
            "meets_confidence": (pattern.confidence or 0) >= min_confidence,
        }
        passed = result["meets_sample_size"] and result["meets_confidence"]
        result["passed"] = passed
        if passed and pattern.status == "candidate":
            self.update_pattern(pattern_id, status="active", last_validated=_utcnow_iso())
            result["new_status"] = "active"
            logger.info("pattern_validated", pattern_id=pattern_id)
        return result

    def decay_confidence(self, days: int = 30) -> int:
        sql = """
            UPDATE patterns
            SET confidence = MAX(0, confidence - decay_rate * ?)
            WHERE last_validated < datetime('now', '-' || ? || ' days')
                AND status = 'active'
        """
        with self._conn() as conn:
            cursor = conn.execute(sql, (days, days))
        return cursor.rowcount

    def deprecate_stale(self, min_confidence: float = 0.3) -> int:
        sql = "UPDATE patterns SET status = 'deprecated' WHERE confidence < ? AND status = 'active'"
        with self._conn() as conn:
            cursor = conn.execute(sql, (min_confidence,))
        return cursor.rowcount

    # ── Pattern relationships ────────────────────────────────

    def insert_relationship(self, rel: PatternRelationship) -> str:
        d = rel.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO pattern_relationships ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        return rel.relationship_id

    def get_relationships(self, pattern_id: str, direction: str = "both") -> list[PatternRelationship]:
        if direction == "outgoing":
            sql = "SELECT * FROM pattern_relationships WHERE pattern_a_id = ?"
        elif direction == "incoming":
            sql = "SELECT * FROM pattern_relationships WHERE pattern_b_id = ?"
        else:
            sql = "SELECT * FROM pattern_relationships WHERE pattern_a_id = ? OR pattern_b_id = ?"
            with self._conn() as conn:
                rows = conn.execute(sql, (pattern_id, pattern_id)).fetchall()
            return [PatternRelationship(**dict(r)) for r in rows]
        with self._conn() as conn:
            rows = conn.execute(sql, (pattern_id,)).fetchall()
        return [PatternRelationship(**dict(r)) for r in rows]

    def get_co_occurring_patterns(self, pattern_id: str, min_strength: float = 0.5) -> list[dict[str, Any]]:
        sql = """
            SELECT
                CASE WHEN pr.pattern_a_id = ? THEN pr.pattern_b_id ELSE pr.pattern_a_id END AS related_pattern_id,
                pr.relationship, pr.strength, pr.sample_size,
                p.pattern_name, p.pattern_type, p.confidence
            FROM pattern_relationships pr
            JOIN patterns p ON p.pattern_id = CASE
                WHEN pr.pattern_a_id = ? THEN pr.pattern_b_id ELSE pr.pattern_a_id END
            WHERE (pr.pattern_a_id = ? OR pr.pattern_b_id = ?) AND pr.strength >= ?
            ORDER BY pr.strength DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (pattern_id, pattern_id, pattern_id, pattern_id, min_strength)).fetchall()
        return [dict(r) for r in rows]

    def get_top_patterns(self, limit: int = 10, metric: str = "expectancy") -> list[Pattern]:
        allowed = {"expectancy", "confidence", "success_rate", "sample_size", "avg_pnl_impact"}
        if metric not in allowed:
            raise ValueError(f"metric must be one of {allowed}")
        sql = f"SELECT * FROM patterns WHERE status = 'active' ORDER BY {metric} DESC NULLS LAST LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [Pattern(**dict(r)) for r in rows]
