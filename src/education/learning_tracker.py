"""
Learning Tracker
=================

Tracks Valentine's learning progress and adjusts explanation depth.
Progressive learning system with 4 levels.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# LEARNING LEVELS
# ═══════════════════════════════════════════════════════════════════════

LEARNING_LEVELS: dict[int, dict[str, Any]] = {
    1: {
        "name": "Beginner",
        "month_range": (1, 3),
        "description": "Learning the basics — indicators and simple patterns",
        "topics": ["rsi", "support", "resistance", "volume", "risk_reward"],
        "explanation_depth": "simple",
        "auto_trade": False,
        "show_regime": False,
        "show_onchain": False,
        "show_genome": False,
    },
    2: {
        "name": "Intermediate",
        "month_range": (3, 6),
        "description": "Adding regime analysis and on-chain signals",
        "topics": [
            "regime",
            "correlation",
            "whale",
            "funding_rate",
            "kill_switch",
            "macd",
            "bollinger",
        ],
        "explanation_depth": "intermediate",
        "auto_trade": False,
        "show_regime": True,
        "show_onchain": True,
        "show_genome": False,
    },
    3: {
        "name": "Advanced",
        "month_range": (6, 12),
        "description": "Strategy evolution and genome mutations",
        "topics": ["genome", "mutation", "strategy_evolution", "microstructure"],
        "explanation_depth": "full",
        "auto_trade": True,
        "show_regime": True,
        "show_onchain": True,
        "show_genome": True,
    },
    4: {
        "name": "Autonomous",
        "month_range": (12, None),
        "description": "Full autonomous trading with periodic reports",
        "topics": [],
        "explanation_depth": "summary",
        "auto_trade": True,
        "show_regime": True,
        "show_onchain": True,
        "show_genome": True,
    },
}

# All topics across all levels
ALL_TOPICS = []
for level_data in LEARNING_LEVELS.values():
    ALL_TOPICS.extend(level_data["topics"])
ALL_TOPICS = list(dict.fromkeys(ALL_TOPICS))  # dedupe, preserve order


class LearningTracker:
    """Track Valentine's learning progress and adjust explanation depth.

    Stores progress in SQLite with tables for:
      - learning_state: current level, start date, etc.
      - topic_progress: per-topic learned/mastered status
      - quiz_scores: quiz attempt history
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create tables if they don't exist."""
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS learning_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                start_date TEXT NOT NULL,
                current_level INTEGER NOT NULL DEFAULT 1,
                last_update TEXT NOT NULL,
                trades_analyzed INTEGER NOT NULL DEFAULT 0,
                CONSTRAINT single_row CHECK (id = 1)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS topic_progress (
                topic TEXT PRIMARY KEY,
                learned INTEGER NOT NULL DEFAULT 0,
                mastered INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT,
                last_seen TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS quiz_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        self._conn.commit()

        # Ensure state row exists
        cur.execute("SELECT COUNT(*) FROM learning_state")
        if cur.fetchone()[0] == 0:
            now = datetime.now(UTC).isoformat()
            cur.execute(
                "INSERT INTO learning_state (start_date, current_level, last_update) VALUES (?, 1, ?)",
                (now, now),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Level Management ──────────────────────────────────────────────

    def get_current_level(self) -> int:
        """Determine current learning level based on time and mastery."""
        if not self._conn:
            self.initialize()

        cur = self._conn.cursor()
        cur.execute("SELECT start_date, current_level FROM learning_state WHERE id = 1")
        row = cur.fetchone()
        if not row:
            return 1

        start = datetime.fromisoformat(row["start_date"])
        now = datetime.now(UTC)
        months_elapsed = (now - start).days / 30.0

        # Check mastery-based advancement
        mastery = self.get_mastery_status()
        mastered_count = sum(1 for m in mastery.values() if m.get("mastered"))

        # Level 1 → 2: 3 months OR mastered 3+ basic topics
        if row["current_level"] == 1:
            basic_topics = LEARNING_LEVELS[1]["topics"]
            basic_mastered = sum(1 for t in basic_topics if mastery.get(t, {}).get("mastered"))
            if months_elapsed >= 3 or basic_mastered >= 3:
                self._set_level(2)
                return 2
            return 1

        # Level 2 → 3: 6 months OR mastered 4+ intermediate topics
        if row["current_level"] == 2:
            inter_topics = LEARNING_LEVELS[2]["topics"]
            inter_mastered = sum(1 for t in inter_topics if mastery.get(t, {}).get("mastered"))
            if months_elapsed >= 6 or inter_mastered >= 4:
                self._set_level(3)
                return 3
            return 2

        # Level 3 → 4: 12 months OR mastered all topics
        if row["current_level"] == 3:
            if months_elapsed >= 12 or mastered_count >= len(ALL_TOPICS) - 2:
                self._set_level(4)
                return 4
            return 3

        return row["current_level"]

    def _set_level(self, level: int) -> None:
        """Update the current level."""
        cur = self._conn.cursor()
        now = datetime.now(UTC).isoformat()
        cur.execute(
            "UPDATE learning_state SET current_level = ?, last_update = ? WHERE id = 1",
            (level, now),
        )
        self._conn.commit()
        logger.info("Learning level updated to %d (%s)", level, LEARNING_LEVELS[level]["name"])

    # ── Feature Flags ─────────────────────────────────────────────────

    def get_explanation_depth(self) -> str:
        """Get current explanation depth setting."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["explanation_depth"]

    def should_show_regime(self) -> bool:
        """Whether to include regime analysis in explanations."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["show_regime"]

    def should_show_onchain(self) -> bool:
        """Whether to include on-chain signals in explanations."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["show_onchain"]

    def should_show_genome(self) -> bool:
        """Whether to include genome/strategy evolution in explanations."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["show_genome"]

    def is_auto_trade_enabled(self) -> bool:
        """Whether autonomous trading is enabled."""
        level = self.get_current_level()
        return LEARNING_LEVELS[level]["auto_trade"]

    # ── Topic Tracking ────────────────────────────────────────────────

    def record_topic_learned(self, topic: str) -> None:
        """Mark a topic as learned."""
        if not self._conn:
            self.initialize()

        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO topic_progress (topic, learned, mastered, first_seen, last_seen)
            VALUES (?, 1, 0, ?, ?)
            ON CONFLICT(topic) DO UPDATE SET
                learned = 1,
                last_seen = ?
            """,
            (topic, now, now, now),
        )
        self._conn.commit()

    def record_quiz_score(self, topic: str, score: int, total: int) -> None:
        """Record a quiz score and check for topic mastery."""
        if not self._conn:
            self.initialize()

        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()

        # Record the score
        cur.execute(
            "INSERT INTO quiz_scores (topic, score, total, timestamp) VALUES (?, ?, ?, ?)",
            (topic, score, total, now),
        )

        # Check mastery: 80%+ on last 3 quizzes for this topic
        cur.execute(
            "SELECT score, total FROM quiz_scores WHERE topic = ? ORDER BY id DESC LIMIT 3",
            (topic,),
        )
        recent = cur.fetchall()
        if len(recent) >= 3:
            avg_pct = sum(r["score"] / r["total"] for r in recent) / 3
            if avg_pct >= 0.8:
                cur.execute(
                    """
                    INSERT INTO topic_progress (topic, learned, mastered, first_seen, last_seen)
                    VALUES (?, 1, 1, ?, ?)
                    ON CONFLICT(topic) DO UPDATE SET mastered = 1, last_seen = ?
                    """,
                    (topic, now, now, now),
                )
                logger.info("Topic '%s' mastered! Quiz avg: %.0f%%", topic, avg_pct * 100)

        self._conn.commit()

    def get_mastery_status(self) -> dict[str, dict[str, Any]]:
        """Get mastery status for all topics."""
        if not self._conn:
            self.initialize()

        cur = self._conn.cursor()
        status: dict[str, dict[str, Any]] = {}

        # Get topic progress
        cur.execute("SELECT * FROM topic_progress")
        for row in cur.fetchall():
            status[row["topic"]] = {
                "learned": bool(row["learned"]),
                "mastered": bool(row["mastered"]),
            }

        # Get quiz averages
        cur.execute("""
            SELECT topic, AVG(CAST(score AS REAL) / total) as avg_pct
            FROM quiz_scores
            GROUP BY topic
        """)
        for row in cur.fetchall():
            if row["topic"] in status:
                status[row["topic"]]["quiz_avg"] = row["avg_pct"]
            else:
                status[row["topic"]] = {
                    "learned": False,
                    "mastered": False,
                    "quiz_avg": row["avg_pct"],
                }

        # Fill in missing topics
        for topic in ALL_TOPICS:
            if topic not in status:
                status[topic] = {"learned": False, "mastered": False, "quiz_avg": 0.0}

        return status

    # ── Progress Report ───────────────────────────────────────────────

    def get_progress_report(self) -> dict[str, Any]:
        """Generate a progress report."""
        level = self.get_current_level()
        level_info = LEARNING_LEVELS[level]
        mastery = self.get_mastery_status()

        learned_count = sum(1 for m in mastery.values() if m.get("learned"))
        mastered_count = sum(1 for m in mastery.values() if m.get("mastered"))

        # Get start date
        cur = self._conn.cursor()
        cur.execute("SELECT start_date FROM learning_state WHERE id = 1")
        row = cur.fetchone()
        start_date = row["start_date"] if row else "unknown"

        # Quiz stats
        cur.execute("SELECT AVG(CAST(score AS REAL) / total) FROM quiz_scores")
        avg_quiz = cur.fetchone()[0] or 0

        # Best and worst topics
        quiz_by_topic: dict[str, list[float]] = {}
        cur.execute("SELECT topic, score, total FROM quiz_scores ORDER BY id DESC")
        for r in cur.fetchall():
            t = r["topic"]
            if t not in quiz_by_topic:
                quiz_by_topic[t] = []
            quiz_by_topic[t].append(r["score"] / r["total"])

        best_topic = (
            max(quiz_by_topic, key=lambda t: sum(quiz_by_topic[t]) / len(quiz_by_topic[t]))
            if quiz_by_topic
            else None
        )
        worst_topic = (
            min(quiz_by_topic, key=lambda t: sum(quiz_by_topic[t]) / len(quiz_by_topic[t]))
            if quiz_by_topic
            else None
        )

        return {
            "level": level,
            "level_name": level_info["name"],
            "description": level_info["description"],
            "start_date": start_date,
            "topics_learned": learned_count,
            "topics_mastered": mastered_count,
            "total_topics": len(ALL_TOPICS),
            "mastery": mastery,
            "avg_quiz_score": avg_quiz,
            "best_topic": best_topic,
            "worst_topic": worst_topic,
            "auto_trade_enabled": level_info["auto_trade"],
        }

    def increment_trades_analyzed(self) -> None:
        """Increment the trades analyzed counter."""
        if not self._conn:
            self.initialize()
        cur = self._conn.cursor()
        now = datetime.now(UTC).isoformat()
        cur.execute(
            "UPDATE learning_state SET trades_analyzed = trades_analyzed + 1, last_update = ? WHERE id = 1",
            (now,),
        )
        self._conn.commit()
