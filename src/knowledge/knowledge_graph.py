"""TSAR — Knowledge Graph Traversal API.

Cross-store graph queries using recursive CTEs for efficient traversal
across trades, strategies, patterns, lessons, and regimes.

Enables queries like:
- "Find all trades in regime X with strategy Y that resulted in lesson Z"
- "What patterns co-occur with strategy S in regime R?"
- "Which lessons were learned from trades using pattern P?"

Persistence: SQLite (WAL mode, tsar.db)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Generator

logger = get_logger(__name__)


# ── Result dataclasses ──────────────────────────────────────


@dataclass
class GraphNode:
    """A node in the knowledge graph."""

    node_type: str  # trade, strategy, pattern, lesson, regime
    node_id: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "node_id": self.node_id,
            "data": self.data,
        }


@dataclass
class GraphEdge:
    """An edge (relationship) between two graph nodes."""

    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relationship: str  # uses_strategy, has_pattern, learned_lesson, in_regime, etc.
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "relationship": self.relationship,
            "weight": self.weight,
            "metadata": self.metadata,
        }


@dataclass
class GraphPath:
    """A path through the knowledge graph."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "length": len(self.edges),
        }


# ── Main class ──────────────────────────────────────────────


class KnowledgeGraph:
    """Cross-store graph traversal for the TSAR knowledge system.

    Uses recursive CTEs for efficient multi-hop queries in SQLite.

    Usage::

        kg = KnowledgeGraph("/path/to/tsar.db")

        # Find trades in a regime with a specific strategy
        paths = kg.find_trades_by_regime_and_strategy(
            regime="trending_up", strategy_id="strat_001"
        )

        # Find all lessons from trades that matched a pattern
        lessons = kg.get_lessons_for_pattern("pattern_abc")

        # Multi-hop: regime → trades → patterns → lessons
        result = kg.traverse(
            start_type="regime", start_id="volatile",
            end_type="lesson", max_depth=4
        )
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

    # ── Direct queries ───────────────────────────────────────

    def find_trades_by_regime_and_strategy(
        self,
        regime: str | None = None,
        strategy_id: str | None = None,
        symbol: str | None = None,
        status: str = "CLOSED",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find trades matching regime + strategy + symbol filters."""
        clauses: list[str] = ["t.is_deleted = 0"]
        params: list[Any] = []

        if regime:
            clauses.append("t.regime_at_entry = ?")
            params.append(regime)
        if strategy_id:
            clauses.append("t.strategy_id = ?")
            params.append(strategy_id)
        if symbol:
            clauses.append("t.symbol = ?")
            params.append(symbol)
        if status:
            clauses.append("t.status = ?")
            params.append(status)

        where = " AND ".join(clauses)
        sql = f"""
            SELECT t.trade_id, t.symbol, t.strategy_id, t.regime_at_entry,
                   t.realized_pnl, t.realized_pnl_pct, t.outcome_grade,
                   t.created_at, t.status,
                   sg.name AS strategy_name, sg.strategy_type
            FROM trade_records t
            LEFT JOIN strategy_genomes sg ON sg.strategy_id = t.strategy_id
            WHERE {where}
            ORDER BY t.created_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_lessons_for_pattern(self, pattern_id: str) -> list[dict[str, Any]]:
        """Find all lessons learned from trades that matched a pattern.

        Path: pattern → trade_patterns → trade_records → trade_lessons → lessons
        """
        sql = """
            SELECT DISTINCT l.lesson_id, l.title, l.lesson_type, l.severity,
                   l.description, l.confidence, l.times_applied, l.times_violated,
                   tp.match_score
            FROM trade_patterns tp
            JOIN trade_records t ON t.trade_id = tp.trade_id
            JOIN trade_lessons tl ON tl.trade_id = t.trade_id
            JOIN lessons l ON l.lesson_id = tl.lesson_id
            WHERE tp.pattern_id = ? AND t.is_deleted = 0 AND l.is_archived = 0
            ORDER BY l.severity, tp.match_score DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (pattern_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_patterns_for_strategy(
        self, strategy_id: str, regime: str | None = None
    ) -> list[dict[str, Any]]:
        """Find patterns associated with a strategy's trades.

        Path: strategy → trade_records → trade_patterns → patterns
        """
        regime_clause = "AND t.regime_at_entry = ?" if regime else ""
        params: list[Any] = [strategy_id]
        if regime:
            params.append(regime)

        sql = f"""
            SELECT p.pattern_id, p.pattern_name, p.pattern_type,
                   p.success_rate, p.confidence, p.expectancy,
                   COUNT(DISTINCT tp.trade_id) AS trade_count,
                   AVG(tp.match_score) AS avg_match_score
            FROM trade_records t
            JOIN trade_patterns tp ON tp.trade_id = t.trade_id
            JOIN patterns p ON p.pattern_id = tp.pattern_id
            WHERE t.strategy_id = ? AND t.is_deleted = 0 {regime_clause}
            GROUP BY p.pattern_id
            ORDER BY trade_count DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_strategies_for_regime(self, regime: str) -> list[dict[str, Any]]:
        """Find strategies that performed well in a given regime."""
        sql = """
            SELECT sg.strategy_id, sg.name, sg.strategy_type,
                   COUNT(t.trade_id) AS trade_count,
                   SUM(t.realized_pnl) AS total_pnl,
                   AVG(t.realized_pnl_pct) AS avg_pnl_pct,
                   AVG(CASE WHEN t.realized_pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
            FROM trade_records t
            JOIN strategy_genomes sg ON sg.strategy_id = t.strategy_id
            WHERE t.regime_at_entry = ? AND t.is_deleted = 0 AND t.status = 'CLOSED'
            GROUP BY sg.strategy_id
            ORDER BY total_pnl DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (regime,)).fetchall()
        return [dict(r) for r in rows]

    def get_regime_pattern_performance(
        self, regime: str, pattern_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Find how patterns perform in a specific regime."""
        pattern_clause = "AND tp.pattern_id = ?" if pattern_id else ""
        params: list[Any] = [regime]
        if pattern_id:
            params.append(pattern_id)

        sql = f"""
            SELECT p.pattern_id, p.pattern_name, p.pattern_type,
                   COUNT(DISTINCT t.trade_id) AS observation_count,
                   AVG(t.realized_pnl) AS avg_pnl,
                   AVG(CASE WHEN t.realized_pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
                   SUM(t.realized_pnl) AS total_pnl
            FROM trade_records t
            JOIN trade_patterns tp ON tp.trade_id = t.trade_id
            JOIN patterns p ON p.pattern_id = tp.pattern_id
            WHERE t.regime_at_entry = ? AND t.is_deleted = 0 {pattern_clause}
            GROUP BY p.pattern_id
            ORDER BY total_pnl DESC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── Recursive CTE traversal ──────────────────────────────

    def traverse(
        self,
        start_type: str,
        start_id: str,
        end_type: str | None = None,
        max_depth: int = 3,
        limit: int = 100,
    ) -> list[GraphPath]:
        """Traverse the knowledge graph from a starting node.

        Uses recursive CTE to walk across edges:
        - trade → strategy (via strategy_id)
        - trade → pattern (via trade_patterns junction)
        - trade → lesson (via trade_lessons junction)
        - trade → regime (via regime_at_entry)
        - pattern → pattern (via pattern_relationships)
        - lesson → trade (via trade_lessons junction, reverse)

        Args:
            start_type: "trade", "strategy", "pattern", "lesson", or "regime"
            start_id: ID of the starting node
            end_type: Optional filter for terminal node type
            max_depth: Maximum hops (default 3)
            limit: Maximum paths to return

        Returns:
            List of GraphPath objects representing traversed paths.
        """
        if start_type not in ("trade", "strategy", "pattern", "lesson", "regime"):
            raise ValueError(f"Invalid start_type: {start_type}")

        # Build adjacency edges as a CTE
        # Each edge is (source_type, source_id, target_type, target_id, relationship)
        edges_cte = self._build_edges_cte()

        # Recursive traversal CTE
        recursive_cte = f"""
            WITH RECURSIVE
            {edges_cte},
            -- Recursive walk
            traversal(node_type, node_id, path_nodes, path_edges, depth) AS (
                -- Anchor: starting node
                SELECT
                    '{start_type}' AS node_type,
                    '{start_id}' AS node_id,
                    json_array(json_object('type', '{start_type}', 'id', '{start_id}')) AS path_nodes,
                    json_array() AS path_edges,
                    0 AS depth

                UNION ALL

                -- Recursive: follow edges
                SELECT
                    e.target_type,
                    e.target_id,
                    json_insert(
                        t.path_nodes,
                        '$[#]',
                        json_object('type', e.target_type, 'id', e.target_id)
                    ),
                    json_insert(
                        t.path_edges,
                        '$[#]',
                        json_object(
                            'src_type', e.source_type,
                            'src_id', e.source_id,
                            'tgt_type', e.target_type,
                            'tgt_id', e.target_id,
                            'rel', e.relationship
                        )
                    ),
                    t.depth + 1
                FROM traversal t
                JOIN edges e ON e.source_type = t.node_type AND e.source_id = t.node_id
                WHERE t.depth < {max_depth}
                  -- Prevent cycles: check target not already in path
                  AND NOT EXISTS (
                      SELECT 1 FROM json_each(t.path_nodes) je
                      WHERE json_extract(je.value, '$.type') = e.target_type
                        AND json_extract(je.value, '$.id') = e.target_id
                  )
            )
            SELECT node_type, node_id, path_nodes, path_edges, depth
            FROM traversal
            WHERE depth > 0
        """

        if end_type:
            recursive_cte += f"\n              AND node_type = '{end_type}'"

        recursive_cte += f"\n            ORDER BY depth\n            LIMIT {limit}"

        with self._conn() as conn:
            try:
                rows = conn.execute(recursive_cte).fetchall()
            except Exception as exc:
                logger.error("graph_traversal_error", error=str(exc))
                return []

        paths: list[GraphPath] = []
        for row in rows:
            path = self._parse_graph_path(row)
            if path:
                paths.append(path)

        return paths

    def _build_edges_cte(self) -> str:
        """Build the edges CTE that defines all traversable relationships."""
        return """
            edges(source_type, source_id, target_type, target_id, relationship) AS (
                -- trade → strategy
                SELECT 'trade', t.trade_id, 'strategy', t.strategy_id, 'uses_strategy'
                FROM trade_records t
                WHERE t.is_deleted = 0 AND t.strategy_id IS NOT NULL

                UNION ALL

                -- trade → pattern (via junction)
                SELECT 'trade', tp.trade_id, 'pattern', tp.pattern_id, 'matched_pattern'
                FROM trade_patterns tp

                UNION ALL

                -- trade → lesson (via junction)
                SELECT 'trade', tl.trade_id, 'lesson', tl.lesson_id, 'learned_lesson'
                FROM trade_lessons tl

                UNION ALL

                -- trade → regime
                SELECT 'trade', t.trade_id, 'regime', t.regime_at_entry, 'in_regime'
                FROM trade_records t
                WHERE t.is_deleted = 0 AND t.regime_at_entry IS NOT NULL

                UNION ALL

                -- strategy → trade (reverse)
                SELECT 'strategy', t.strategy_id, 'trade', t.trade_id, 'executed_as'
                FROM trade_records t
                WHERE t.is_deleted = 0

                UNION ALL

                -- pattern → trade (reverse, via junction)
                SELECT 'pattern', tp.pattern_id, 'trade', tp.trade_id, 'observed_in'
                FROM trade_patterns tp

                UNION ALL

                -- lesson → trade (reverse, via junction)
                SELECT 'lesson', tl.lesson_id, 'trade', tl.trade_id, 'derived_from'
                FROM trade_lessons tl

                UNION ALL

                -- regime → trade (reverse)
                SELECT 'regime', t.regime_at_entry, 'trade', t.trade_id, 'contains_trade'
                FROM trade_records t
                WHERE t.is_deleted = 0 AND t.regime_at_entry IS NOT NULL

                UNION ALL

                -- pattern → pattern (relationships)
                SELECT 'pattern', pr.pattern_a_id, 'pattern', pr.pattern_b_id, pr.relationship
                FROM pattern_relationships pr

                UNION ALL

                -- pattern → pattern (reverse relationships)
                SELECT 'pattern', pr.pattern_b_id, 'pattern', pr.pattern_a_id, pr.relationship || '_reverse'
                FROM pattern_relationships pr
            )
        """

    def _parse_graph_path(self, row: Any) -> GraphPath | None:
        """Parse a CTE result row into a GraphPath."""
        try:
            import json

            nodes_raw = json.loads(row["path_nodes"]) if isinstance(row["path_nodes"], str) else row["path_nodes"]
            edges_raw = json.loads(row["path_edges"]) if isinstance(row["path_edges"], str) else row["path_edges"]

            nodes = [
                GraphNode(node_type=n["type"], node_id=n["id"])
                for n in nodes_raw
            ]

            edges = [
                GraphEdge(
                    source_type=e["src_type"],
                    source_id=e["src_id"],
                    target_type=e["tgt_type"],
                    target_id=e["tgt_id"],
                    relationship=e["rel"],
                )
                for e in edges_raw
            ]

            return GraphPath(nodes=nodes, edges=edges)
        except Exception as exc:
            logger.warning("graph_path_parse_error", error=str(exc))
            return None

    # ── Neighborhood queries ─────────────────────────────────

    def get_neighbors(
        self,
        node_type: str,
        node_id: str,
        relationship: str | None = None,
        limit: int = 50,
    ) -> list[GraphNode]:
        """Get immediate neighbors of a node.

        Args:
            node_type: "trade", "strategy", "pattern", "lesson", or "regime"
            node_id: ID of the node
            relationship: Optional filter by relationship type
            limit: Max neighbors to return

        Returns:
            List of neighboring GraphNodes.
        """
        edges_cte = self._build_edges_cte()
        rel_filter = f"AND e.relationship = '{relationship}'" if relationship else ""

        sql = f"""
            WITH {edges_cte}
            SELECT e.target_type, e.target_id, e.relationship
            FROM edges e
            WHERE e.source_type = ? AND e.source_id = ? {rel_filter}
            LIMIT ?
        """
        with self._conn() as conn:
            try:
                rows = conn.execute(sql, (node_type, node_id, limit)).fetchall()
            except Exception as exc:
                logger.error("neighbor_query_error", error=str(exc))
                return []

        return [
            GraphNode(node_type=r["target_type"], node_id=r["target_id"])
            for r in rows
        ]

    # ── Aggregate graph stats ────────────────────────────────

    def get_graph_stats(self) -> dict[str, Any]:
        """Return counts of nodes and edges in the knowledge graph."""
        stats: dict[str, Any] = {}
        with self._conn() as conn:
            for table, label in [
                ("trade_records", "trades"),
                ("strategy_genomes", "strategies"),
                ("patterns", "patterns"),
                ("lessons", "lessons"),
            ]:
                try:
                    row = conn.execute(
                        f"SELECT COUNT(*) AS cnt FROM {table} WHERE is_deleted = 0 OR is_archived = 0"
                    ).fetchone()
                    stats[label] = row["cnt"] if row else 0
                except Exception:
                    stats[label] = -1

            # Edge counts
            for table, label in [
                ("trade_patterns", "trade_pattern_edges"),
                ("trade_lessons", "trade_lesson_edges"),
                ("pattern_relationships", "pattern_pattern_edges"),
            ]:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
                    stats[label] = row["cnt"] if row else 0
                except Exception:
                    stats[label] = -1

            # Regime count (from trades)
            try:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT regime_at_entry) AS cnt FROM trade_records WHERE regime_at_entry IS NOT NULL AND is_deleted = 0"
                ).fetchone()
                stats["regimes"] = row["cnt"] if row else 0
            except Exception:
                stats["regimes"] = -1

        return stats

    # ── Enrichment ───────────────────────────────────────────

    def enrich_node(self, node: GraphNode) -> GraphNode:
        """Enrich a node with its full data from the source table."""
        table_map = {
            "trade": ("trade_records", "trade_id"),
            "strategy": ("strategy_genomes", "strategy_id"),
            "pattern": ("patterns", "pattern_id"),
            "lesson": ("lessons", "lesson_id"),
        }
        if node.node_type not in table_map:
            return node

        table, id_col = table_map[node.node_type]
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE {id_col} = ?", (node.node_id,)
            ).fetchone()
        if row:
            node.data = dict(row)
        return node

    def enrich_path(self, path: GraphPath) -> GraphPath:
        """Enrich all nodes in a path with their full data."""
        for node in path.nodes:
            self.enrich_node(node)
        return path
