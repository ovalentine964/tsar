"""TSAR — Lesson Archive.

Knowledge Store #5: Distilled wisdom from failures and successes.
FTS5 enables full-text search across all lessons.

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
class Lesson:
    lesson_id: str = field(default_factory=_ulid)
    trade_id: Optional[str] = None
    title: str = ""
    lesson_type: str = "INSIGHT"
    category: Optional[str] = None
    severity: str = "moderate"
    description: str = ""
    action_item: Optional[str] = None
    content: Optional[str] = None
    source_strategy_id: Optional[str] = None
    source_pattern_id: Optional[str] = None
    source_event: Optional[str] = None
    applicable_regimes: Optional[str] = None
    applicable_symbols: Optional[str] = None
    applicable_strategies: Optional[str] = None
    action_required: int = 0
    action_taken: Optional[str] = None
    action_status: str = "pending"
    applied: int = 0
    times_applied: int = 0
    times_violated: int = 0
    last_applied: Optional[str] = None
    last_violated: Optional[str] = None
    violation_impact: float = 0.0
    confidence: float = 0.8
    validated_count: int = 1
    discovered_by: Optional[str] = None
    discovered_at: str = field(default_factory=_utcnow_iso)
    tags: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    is_archived: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class LessonApplication:
    application_id: str = field(default_factory=_ulid)
    lesson_id: str = ""
    trade_id: Optional[str] = None
    strategy_name: Optional[str] = None
    context: str = ""
    parameter_changed: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    outcome: Optional[str] = None
    impact_measured: Optional[float] = None
    agent: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    applied_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class LessonViolation:
    violation_id: str = field(default_factory=_ulid)
    lesson_id: str = ""
    trade_id: str = ""
    violation_description: str = ""
    pnl_impact: Optional[float] = None
    reason_given: Optional[str] = None
    occurred_at: str = field(default_factory=_utcnow_iso)
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class LessonArchive:
    """CRUD for lessons, FTS5 search, application and violation tracking.

    Usage::

        archive = LessonArchive("/path/to/tsar.db")
        archive.insert_lesson(lesson)
        results = archive.search("stop loss premature exit")
        archive.record_violation(violation)
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

    # ── Lesson CRUD ──────────────────────────────────────────

    def insert_lesson(self, lesson: Lesson) -> str:
        d = lesson.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO lessons ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        logger.info("lesson_inserted", lesson_id=lesson.lesson_id, title=lesson.title)
        return lesson.lesson_id

    def get_lesson(self, lesson_id: str) -> Optional[Lesson]:
        sql = "SELECT * FROM lessons WHERE lesson_id = ?"
        with self._conn() as conn:
            row = conn.execute(sql, (lesson_id,)).fetchone()
        return Lesson(**dict(row)) if row else None

    def update_lesson(self, lesson_id: str, **fields: Any) -> bool:
        if not fields:
            return False
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["lesson_id"] = lesson_id
        sql = f"UPDATE lessons SET {sets} WHERE lesson_id = :lesson_id"
        with self._conn() as conn:
            cursor = conn.execute(sql, fields)
        if cursor.rowcount > 0:
            logger.info("lesson_updated", lesson_id=lesson_id, fields=list(fields.keys()))
            return True
        return False

    def list_lessons(
        self, lesson_type: Optional[str] = None, severity: Optional[str] = None,
        category: Optional[str] = None, source_strategy_id: Optional[str] = None,
        include_archived: bool = False, limit: int = 100, offset: int = 0
    ) -> list[Lesson]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_archived:
            clauses.append("is_archived = 0")
        if lesson_type:
            clauses.append("lesson_type = ?")
            params.append(lesson_type)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if source_strategy_id:
            clauses.append("source_strategy_id = ?")
            params.append(source_strategy_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM lessons {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Lesson(**dict(r)) for r in rows]

    def archive_lesson(self, lesson_id: str) -> bool:
        return self.update_lesson(lesson_id, is_archived=1)

    def get_critical_lessons(self, limit: int = 20) -> list[Lesson]:
        return self.list_lessons(severity="critical", include_archived=False, limit=limit)

    def get_most_violated(self, limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            SELECT l.*, COUNT(lv.violation_id) AS violation_count,
                   SUM(lv.pnl_impact) AS total_violation_impact
            FROM lessons l
            LEFT JOIN lesson_violations lv ON l.lesson_id = lv.lesson_id
            WHERE l.is_archived = 0 AND l.times_violated > 0
            GROUP BY l.lesson_id
            ORDER BY l.violation_impact DESC
            LIMIT ?
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_recent_lessons(self, days: int = 7, limit: int = 50) -> list[Lesson]:
        sql = """
            SELECT * FROM lessons
            WHERE discovered_at > datetime('now', '-' || ? || ' days') AND is_archived = 0
            ORDER BY severity, discovered_at DESC
            LIMIT ?
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (days, limit)).fetchall()
        return [Lesson(**dict(r)) for r in rows]

    # ── FTS5 search ──────────────────────────────────────────

    def search(
        self, query: str, severity: Optional[str] = None, lesson_type: Optional[str] = None,
        include_archived: bool = False, limit: int = 20
    ) -> list[dict[str, Any]]:
        fts_query = self._format_fts_query(query)
        extra_clauses: list[str] = []
        extra_params: list[Any] = []
        if not include_archived:
            extra_clauses.append("l.is_archived = 0")
        if severity:
            extra_clauses.append("l.severity = ?")
            extra_params.append(severity)
        if lesson_type:
            extra_clauses.append("l.lesson_type = ?")
            extra_params.append(lesson_type)
        extra_where = (" AND " + " AND ".join(extra_clauses)) if extra_clauses else ""
        sql = f"""
            SELECT l.*, fts.rank AS bm25_score
            FROM lessons_fts fts
            JOIN lessons l ON l.rowid = fts.rowid
            WHERE lessons_fts MATCH ?{extra_where}
            ORDER BY fts.rank
            LIMIT ?
        """
        params: list[Any] = [fts_query] + extra_params + [limit]
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _format_fts_query(query: str) -> str:
        clean = re.sub(r"[^\w\s]", "", query)
        terms = [t for t in clean.split() if len(t) > 2]
        if not terms:
            return '""'
        return " OR ".join(f'"{t}"' for t in terms)

    # ── Application tracking ─────────────────────────────────

    def record_application(self, app: LessonApplication) -> str:
        d = app.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO lesson_applications ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        update_sql = """
            UPDATE lessons
            SET times_applied = times_applied + 1, applied = 1, last_applied = ?
            WHERE lesson_id = ?
        """
        with self._conn() as conn:
            conn.execute(update_sql, (_utcnow_iso(), app.lesson_id))
        logger.info("lesson_applied", lesson_id=app.lesson_id, trade_id=app.trade_id)
        return app.application_id

    def get_applications(self, lesson_id: str, limit: int = 50) -> list[LessonApplication]:
        sql = "SELECT * FROM lesson_applications WHERE lesson_id = ? ORDER BY created_at DESC LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (lesson_id, limit)).fetchall()
        return [LessonApplication(**dict(r)) for r in rows]

    # ── Violation tracking ───────────────────────────────────

    def record_violation(self, violation: LessonViolation) -> str:
        d = violation.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO lesson_violations ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        pnl = violation.pnl_impact or 0.0
        update_sql = """
            UPDATE lessons
            SET times_violated = times_violated + 1, last_violated = ?,
                violation_impact = violation_impact + ?
            WHERE lesson_id = ?
        """
        with self._conn() as conn:
            conn.execute(update_sql, (_utcnow_iso(), pnl, violation.lesson_id))
        logger.warning("lesson_violated", lesson_id=violation.lesson_id, pnl_impact=pnl)
        return violation.violation_id

    def get_violations(self, lesson_id: str, limit: int = 50) -> list[LessonViolation]:
        sql = "SELECT * FROM lesson_violations WHERE lesson_id = ? ORDER BY created_at DESC LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (lesson_id, limit)).fetchall()
        return [LessonViolation(**dict(r)) for r in rows]

    def get_violation_summary(self, since: Optional[str] = None) -> list[dict[str, Any]]:
        clause = "AND lv.created_at >= ?" if since else ""
        sql = f"""
            SELECT l.lesson_id, l.title, l.severity,
                   COUNT(lv.violation_id) AS violation_count,
                   SUM(lv.pnl_impact) AS total_impact,
                   AVG(lv.pnl_impact) AS avg_impact
            FROM lessons l
            JOIN lesson_violations lv ON l.lesson_id = lv.lesson_id
            WHERE l.is_archived = 0 {clause}
            GROUP BY l.lesson_id
            ORDER BY total_impact DESC
        """
        params: tuple[Any, ...] = (since,) if since else ()
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── Aggregate queries ────────────────────────────────────

    def get_lesson_stats(self) -> dict[str, Any]:
        sql = """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_archived = 0 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN severity = 'critical' AND is_archived = 0 THEN 1 ELSE 0 END) AS critical,
                SUM(CASE WHEN times_applied > 0 THEN 1 ELSE 0 END) AS applied_count,
                SUM(CASE WHEN times_violated > 0 THEN 1 ELSE 0 END) AS violated_count,
                SUM(violation_impact) AS total_violation_impact,
                AVG(confidence) AS avg_confidence
            FROM lessons
        """
        with self._conn() as conn:
            row = conn.execute(sql).fetchone()
        return dict(row) if row else {}

    def get_type_distribution(self) -> list[dict[str, Any]]:
        sql = """
            SELECT lesson_type, severity, COUNT(*) AS count
            FROM lessons WHERE is_archived = 0
            GROUP BY lesson_type, severity
            ORDER BY lesson_type, severity
        """
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def decay_confidence(self, days: int = 30, min_confidence: float = 0.3) -> int:
        sql = """
            UPDATE lessons SET is_archived = 1
            WHERE is_archived = 0 AND severity != 'critical'
                AND times_applied = 0
                AND discovered_at < datetime('now', '-' || ? || ' days')
                AND confidence < ?
        """
        with self._conn() as conn:
            cursor = conn.execute(sql, (days, min_confidence))
        return cursor.rowcount
