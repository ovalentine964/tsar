"""TSAR — Strategy Genomes.

Knowledge Store #2: Living, evolving strategy definitions with performance
stats per regime.  Genomes evolve through mutation and selection.

Persistence: SQLite (WAL mode, tsar.db)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Generator

logger = get_logger(__name__)


def _ulid() -> str:
    return uuid.uuid4().hex


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class StrategyGenome:
    strategy_id: str = field(default_factory=_ulid)
    name: str = ""
    parent_id: str | None = None
    version: int = 1
    thesis: str | None = None
    genome_yaml: str | None = None
    genome_hash: str | None = None
    asset_class: str = "crypto"
    symbols: str | None = None
    strategy_type: str | None = None
    entry_rules: str | None = None
    exit_rules: str | None = None
    risk_params: str | None = None
    status: str = "candidate"
    activated_at: str | None = None
    retired_at: str | None = None
    retirement_reason: str | None = None
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    rolling_sharpe_30d: float = 0.0
    win_rate: float = 0.0
    avg_holding_hours: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    regime_performance: str | None = None
    gates_passed: int = 0
    gates_evaluated_at: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    last_evolved: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @staticmethod
    def compute_hash(yaml_content: str) -> str:
        return hashlib.sha256(yaml_content.encode("utf-8")).hexdigest()


@dataclass
class StrategyPerformance:
    snapshot_id: str = field(default_factory=_ulid)
    strategy_id: str = ""
    period_start: str = ""
    period_end: str = ""
    total_return: float | None = None
    annualized_return: float | None = None
    excess_return: float | None = None
    volatility: float | None = None
    max_drawdown: float | None = None
    var_95: float | None = None
    cvar_95: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    sharpe_ratio: float | None = None
    avg_slippage_bps: float | None = None
    avg_latency_ms: float | None = None
    fill_rate: float | None = None
    total_trades: int | None = None
    winning_trades: int | None = None
    total_pnl: float | None = None
    win_rate: float | None = None
    regime_performance: str | None = None
    signal_accuracy: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class StrategyMutation:
    mutation_id: str = field(default_factory=_ulid)
    strategy_name: str = ""
    parent_id: str = ""
    child_id: str | None = None
    version_from: int = 1
    version_to: int = 2
    mutation_type: str = "param_tweak"
    change_description: str = ""
    mutation_detail: str | None = None
    rationale: str | None = None
    performance_before: str | None = None
    performance_after: str | None = None
    parent_fitness: float | None = None
    outcome: str = "pending"
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class StrategyGenomes:
    """CRUD for strategy genomes, performance tracking, and mutation history.

    Usage::

        sg = StrategyGenomes("/path/to/tsar.db")
        sg.insert_genome(genome)
        sg.record_mutation(mutation)
        live = sg.get_active_strategies()
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

    # ── Genome CRUD ──────────────────────────────────────────

    def insert_genome(self, genome: StrategyGenome) -> str:
        if genome.genome_yaml and not genome.genome_hash:
            genome.genome_hash = StrategyGenome.compute_hash(genome.genome_yaml)
        d = genome.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d)
        sql = f"INSERT INTO strategy_genomes ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        logger.info("genome_inserted", strategy_id=genome.strategy_id, name=genome.name)
        return genome.strategy_id

    def get_genome(self, strategy_id: str) -> StrategyGenome | None:
        sql = "SELECT * FROM strategy_genomes WHERE strategy_id = ?"
        with self._conn() as conn:
            row = conn.execute(sql, (strategy_id,)).fetchone()
        return StrategyGenome(**dict(row)) if row else None

    def get_genome_by_name(self, name: str) -> StrategyGenome | None:
        sql = "SELECT * FROM strategy_genomes WHERE name = ? ORDER BY version DESC LIMIT 1"
        with self._conn() as conn:
            row = conn.execute(sql, (name,)).fetchone()
        return StrategyGenome(**dict(row)) if row else None

    def update_genome(self, strategy_id: str, **fields: Any) -> bool:
        if not fields:
            return False
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["strategy_id"] = strategy_id
        sql = f"UPDATE strategy_genomes SET {sets} WHERE strategy_id = :strategy_id"
        with self._conn() as conn:
            cursor = conn.execute(sql, fields)
        if cursor.rowcount > 0:
            logger.info("genome_updated", strategy_id=strategy_id, fields=list(fields.keys()))
            return True
        return False

    def update_status(self, strategy_id: str, status: str, reason: str | None = None) -> bool:
        fields: dict[str, Any] = {"status": status}
        now = _utcnow_iso()
        if status == "live":
            fields["activated_at"] = now
        elif status in ("retired", "dead"):
            fields["retired_at"] = now
            if reason:
                fields["retirement_reason"] = reason
        return self.update_genome(strategy_id, **fields)

    def get_active_strategies(self) -> list[StrategyGenome]:
        sql = "SELECT * FROM strategy_genomes WHERE status IN ('live', 'paper') ORDER BY sharpe_ratio DESC"
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [StrategyGenome(**dict(r)) for r in rows]

    def list_genomes(
        self, status: str | None = None, strategy_type: str | None = None, limit: int = 100
    ) -> list[StrategyGenome]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if strategy_type:
            clauses.append("strategy_type = ?")
            params.append(strategy_type)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM strategy_genomes {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [StrategyGenome(**dict(r)) for r in rows]

    def get_lineage(self, strategy_id: str) -> list[dict[str, Any]]:
        sql = """
            WITH RECURSIVE lineage AS (
                SELECT strategy_id, parent_id, name, version, status, 0 AS depth
                FROM strategy_genomes WHERE strategy_id = ?
                UNION ALL
                SELECT sg.strategy_id, sg.parent_id, sg.name, sg.version, sg.status, l.depth + 1
                FROM strategy_genomes sg
                JOIN lineage l ON sg.parent_id = l.strategy_id
            )
            SELECT * FROM lineage ORDER BY depth
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (strategy_id,)).fetchall()
        return [dict(r) for r in rows]

    # ── Performance tracking ─────────────────────────────────

    def insert_performance(self, perf: StrategyPerformance) -> str:
        d = perf.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d)
        sql = f"INSERT INTO strategy_performance ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        return perf.snapshot_id

    def get_performance_history(
        self, strategy_id: str, limit: int = 100
    ) -> list[StrategyPerformance]:
        sql = "SELECT * FROM strategy_performance WHERE strategy_id = ? ORDER BY period_end DESC LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (strategy_id, limit)).fetchall()
        return [StrategyPerformance(**dict(r)) for r in rows]

    def update_genome_stats(
        self,
        strategy_id: str,
        total_trades: int,
        winning_trades: int,
        total_pnl: float,
        sharpe_ratio: float,
        max_drawdown: float,
        win_rate: float,
        profit_factor: float,
        rolling_sharpe_30d: float | None = None,
        consecutive_losses: int | None = None,
    ) -> bool:
        fields: dict[str, Any] = {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "total_pnl": total_pnl,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
        }
        if rolling_sharpe_30d is not None:
            fields["rolling_sharpe_30d"] = rolling_sharpe_30d
        if consecutive_losses is not None:
            fields["consecutive_losses"] = consecutive_losses
            genome = self.get_genome(strategy_id)
            if genome and consecutive_losses > genome.max_consecutive_losses:
                fields["max_consecutive_losses"] = consecutive_losses
        return self.update_genome(strategy_id, **fields)

    # ── Mutation history ─────────────────────────────────────

    def record_mutation(self, mutation: StrategyMutation) -> str:
        d = mutation.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d)
        sql = f"INSERT INTO strategy_mutations ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        logger.info(
            "mutation_recorded",
            mutation_id=mutation.mutation_id,
            strategy_name=mutation.strategy_name,
        )
        return mutation.mutation_id

    def get_mutations(
        self,
        strategy_name: str | None = None,
        parent_id: str | None = None,
        mutation_type: str | None = None,
        limit: int = 50,
    ) -> list[StrategyMutation]:
        clauses: list[str] = []
        params: list[Any] = []
        if strategy_name:
            clauses.append("strategy_name = ?")
            params.append(strategy_name)
        if parent_id:
            clauses.append("parent_id = ?")
            params.append(parent_id)
        if mutation_type:
            clauses.append("mutation_type = ?")
            params.append(mutation_type)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM strategy_mutations {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [StrategyMutation(**dict(r)) for r in rows]

    def get_mutation_effectiveness(self) -> list[dict[str, Any]]:
        sql = """
            SELECT
                m.mutation_type,
                COUNT(*) AS count,
                AVG(child.sharpe_ratio - parent.sharpe_ratio) AS avg_sharpe_improvement,
                AVG(child.win_rate - parent.win_rate) AS avg_win_rate_improvement
            FROM strategy_mutations m
            JOIN strategy_genomes parent ON m.parent_id = parent.strategy_id
            JOIN strategy_genomes child ON m.child_id = child.strategy_id
            WHERE m.child_id IS NOT NULL
            GROUP BY m.mutation_type
            ORDER BY avg_sharpe_improvement DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def evaluate_gates(
        self,
        strategy_id: str,
        min_trades: int = 30,
        min_win_rate: float = 0.45,
        max_consecutive_losses: int = 7,
        min_profit_factor: float = 1.2,
    ) -> dict[str, bool]:
        genome = self.get_genome(strategy_id)
        if genome is None:
            raise ValueError(f"Strategy {strategy_id} not found")
        results: dict[str, bool] = {
            "min_trades": genome.total_trades >= min_trades,
            "min_win_rate": genome.win_rate >= min_win_rate,
            "max_consecutive_losses": genome.max_consecutive_losses <= max_consecutive_losses,
            "min_profit_factor": genome.profit_factor >= min_profit_factor,
        }
        bitmask = 0
        for i, passed in enumerate(results.values()):
            if passed:
                bitmask |= 1 << i
        self.update_genome(strategy_id, gates_passed=bitmask, gates_evaluated_at=_utcnow_iso())
        logger.info("gates_evaluated", strategy_id=strategy_id, results=results)
        return results

    # ── Shadow lesson → genome mutation pipeline ─────────────

    def apply_shadow_lesson(
        self,
        strategy_id: str,
        lesson: dict[str, Any],
        loss_weight: float = 1.0,
    ) -> str | None:
        """Apply a shadow account lesson as a genome mutation.

        This wires shadow account lessons directly into the strategy
        genome mutation pipeline. Lessons from losing trades are
        weighted more heavily (loss_weight > 1.0) because avoiding
        losses is more valuable than capturing marginal wins.

        Args:
            strategy_id: Target genome to mutate.
            lesson: Lesson dict with keys:
                - rule (str): The lesson/rule content
                - conditions (list): Conditions that triggered losses
                - confidence (float): Lesson confidence (0-1)
                - source (str): 'shadow_winners' or 'shadow_losers'
                - loss_severity (float): Loss percentage (for weighting)
            loss_weight: Multiplier for loss-derived lessons.
                Default 1.0. Loss lessons use higher values.

        Returns:
            mutation_id if a mutation was recorded, None if skipped.
        """
        genome = self.get_genome(strategy_id)
        if genome is None:
            logger.warning("apply_shadow_lesson: genome %s not found", strategy_id)
            return None

        confidence = lesson.get("confidence", 0.5)
        source = lesson.get("source", "unknown")

        # Loss-weighted confidence: multiply by loss_weight for loser-derived lessons
        effective_confidence = min(1.0, confidence * loss_weight)

        # Only apply if effective confidence is high enough
        if effective_confidence < 0.4:
            logger.debug(
                "apply_shadow_lesson: skipping low-confidence lesson "
                "(genome=%s, confidence=%.2f, effective=%.2f)",
                strategy_id,
                confidence,
                effective_confidence,
            )
            return None

        # Build the mutation
        rule_text = lesson.get("rule", "")
        conditions = lesson.get("conditions", [])
        loss_severity = lesson.get("loss_severity", 0.0)

        change_description = (
            f"Shadow lesson [{source}]: {rule_text}. "
            f"Confidence: {effective_confidence:.2f} "
            f"(base={confidence:.2f}, weight={loss_weight:.1f})"
        )

        # Determine mutation type based on lesson source
        if source == "shadow_losers":
            mutation_type = "risk_tightening"
            # For loss lessons, tighten exit rules
            self._build_tighter_exit_rules(genome.exit_rules, conditions, loss_severity)
        else:
            mutation_type = "rule_addition"
            json.dumps(conditions, indent=2) if conditions else None

        mutation = StrategyMutation(
            strategy_name=genome.name,
            parent_id=genome.strategy_id,
            mutation_type=mutation_type,
            change_description=change_description,
            mutation_detail=json.dumps(lesson, default=str),
            rationale=lesson.get("rationale", rule_text),
            outcome="pending",
        )

        mutation_id = self.record_mutation(mutation)

        logger.info(
            "shadow_lesson_applied",
            genome_id=strategy_id,
            mutation_id=mutation_id,
            source=source,
            effective_confidence=round(effective_confidence, 3),
            loss_weight=loss_weight,
            mutation_type=mutation_type,
        )

        return mutation_id

    @staticmethod
    def _build_tighter_exit_rules(
        existing_exit: str | None,
        loss_conditions: list[dict[str, Any]],
        loss_severity: float,
    ) -> str:
        """Build tighter exit rules based on loss patterns.

        For losing trades, we add exit conditions that would have
        reduced losses. The tighter the loss, the more aggressive
        the exit rules.

        Args:
            existing_exit: Current exit rules JSON string.
            loss_conditions: Conditions from losing trades.
            loss_severity: Average loss percentage.

        Returns:
            JSON string with updated exit rules.
        """
        try:
            current = json.loads(existing_exit) if existing_exit else []
            if not isinstance(current, list):
                current = [current]
        except (json.JSONDecodeError, TypeError):
            current = []

        # Add tighter stop-loss conditions based on loss severity
        if loss_severity > 5.0:
            current.append({"type": "tight_stop", "max_loss_pct": 2.0})
        elif loss_severity > 3.0:
            current.append({"type": "tight_stop", "max_loss_pct": 3.0})
        elif loss_severity > 1.0:
            current.append({"type": "tight_stop", "max_loss_pct": 5.0})

        # Add time-based exit for trades that held too long
        for cond in loss_conditions:
            if cond.get("type") == "holding_period_above":
                current.append(
                    {
                        "type": "time_exit",
                        "max_hours": cond.get("value", 48),
                    }
                )

        return json.dumps(current, indent=2)
