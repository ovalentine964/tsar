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
class StrategyGenome:
    strategy_id: str = field(default_factory=_ulid)
    name: str = ""
    parent_id: Optional[str] = None
    version: int = 1
    thesis: Optional[str] = None
    genome_yaml: Optional[str] = None
    genome_hash: Optional[str] = None
    asset_class: str = "crypto"
    symbols: Optional[str] = None
    strategy_type: Optional[str] = None
    entry_rules: Optional[str] = None
    exit_rules: Optional[str] = None
    risk_params: Optional[str] = None
    status: str = "candidate"
    activated_at: Optional[str] = None
    retired_at: Optional[str] = None
    retirement_reason: Optional[str] = None
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
    regime_performance: Optional[str] = None
    gates_passed: int = 0
    gates_evaluated_at: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    last_evolved: Optional[str] = None

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
    total_return: Optional[float] = None
    annualized_return: Optional[float] = None
    excess_return: Optional[float] = None
    volatility: Optional[float] = None
    max_drawdown: Optional[float] = None
    var_95: Optional[float] = None
    cvar_95: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    avg_slippage_bps: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    fill_rate: Optional[float] = None
    total_trades: Optional[int] = None
    winning_trades: Optional[int] = None
    total_pnl: Optional[float] = None
    win_rate: Optional[float] = None
    regime_performance: Optional[str] = None
    signal_accuracy: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class StrategyMutation:
    mutation_id: str = field(default_factory=_ulid)
    strategy_name: str = ""
    parent_id: str = ""
    child_id: Optional[str] = None
    version_from: int = 1
    version_to: int = 2
    mutation_type: str = "param_tweak"
    change_description: str = ""
    mutation_detail: Optional[str] = None
    rationale: Optional[str] = None
    performance_before: Optional[str] = None
    performance_after: Optional[str] = None
    parent_fitness: Optional[float] = None
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
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO strategy_genomes ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        logger.info("genome_inserted", strategy_id=genome.strategy_id, name=genome.name)
        return genome.strategy_id

    def get_genome(self, strategy_id: str) -> Optional[StrategyGenome]:
        sql = "SELECT * FROM strategy_genomes WHERE strategy_id = ?"
        with self._conn() as conn:
            row = conn.execute(sql, (strategy_id,)).fetchone()
        return StrategyGenome(**dict(row)) if row else None

    def get_genome_by_name(self, name: str) -> Optional[StrategyGenome]:
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

    def update_status(self, strategy_id: str, status: str, reason: Optional[str] = None) -> bool:
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
        self, status: Optional[str] = None, strategy_type: Optional[str] = None, limit: int = 100
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
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO strategy_performance ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        return perf.snapshot_id

    def get_performance_history(self, strategy_id: str, limit: int = 100) -> list[StrategyPerformance]:
        sql = "SELECT * FROM strategy_performance WHERE strategy_id = ? ORDER BY period_end DESC LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (strategy_id, limit)).fetchall()
        return [StrategyPerformance(**dict(r)) for r in rows]

    def update_genome_stats(
        self, strategy_id: str, total_trades: int, winning_trades: int,
        total_pnl: float, sharpe_ratio: float, max_drawdown: float,
        win_rate: float, profit_factor: float,
        rolling_sharpe_30d: Optional[float] = None, consecutive_losses: Optional[int] = None,
    ) -> bool:
        fields: dict[str, Any] = {
            "total_trades": total_trades, "winning_trades": winning_trades,
            "total_pnl": total_pnl, "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown, "win_rate": win_rate, "profit_factor": profit_factor,
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
        placeholders = ", ".join(f":{k}" for k in d.keys())
        sql = f"INSERT INTO strategy_mutations ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, d)
        logger.info("mutation_recorded", mutation_id=mutation.mutation_id, strategy_name=mutation.strategy_name)
        return mutation.mutation_id

    def get_mutations(
        self, strategy_name: Optional[str] = None, parent_id: Optional[str] = None,
        mutation_type: Optional[str] = None, limit: int = 50
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
        self, strategy_id: str, min_trades: int = 30, min_win_rate: float = 0.45,
        max_consecutive_losses: int = 7, min_profit_factor: float = 1.2
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
