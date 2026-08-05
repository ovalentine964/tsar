"""
TSAR Domain Tools — Knowledge Graph.

Tool 9: Cross-store graph traversal for the TSAR knowledge system.

Enables complex queries across trades, strategies, patterns, lessons,
and regimes using recursive CTEs for efficient multi-hop traversal.

Relationships:
  - Trade → Strategy (uses_strategy)
  - Trade → Pattern (matched_pattern)
  - Trade → Lesson (learned_lesson)
  - Trade → Regime (in_regime)
  - Pattern → Pattern (co_occurrence, similar_to, etc.)

Usage::

    kg_tools = KnowledgeGraphTools("/path/to/tsar.db")

    # Find trades by regime + strategy
    trades = kg_tools.find_trades_by_regime_and_strategy(
        regime="trending_up", strategy_id="strat_001"
    )

    # Multi-hop traversal
    paths = kg_tools.traverse(
        start_type="regime", start_id="volatile",
        end_type="lesson", max_depth=4
    )

    # Get neighborhood of a node
    neighbors = kg_tools.get_neighbors("pattern", "pat_abc")

    stats = kg_tools.get_stats()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.knowledge.knowledge_graph import (
    GraphEdge,
    GraphNode,
    GraphPath,
    KnowledgeGraph,
)

logger = logging.getLogger(__name__)

__all__ = ["KnowledgeGraphTools"]


class KnowledgeGraphTools:
    """Cross-store knowledge graph traversal tools.

    Provides a unified interface to query relationships between
    trades, strategies, patterns, lessons, and regimes stored in
    the TSAR knowledge system.

    The underlying KnowledgeGraph uses recursive CTEs in SQLite for
    efficient multi-hop graph traversal.

    Attributes:
        graph: The underlying KnowledgeGraph instance.
    """

    description = (
        "Knowledge graph: cross-store traversal, Pattern→Regime→Strategy→Lesson "
        "relationships, neighborhood queries, path finding"
    )

    def __init__(self, db_path: str | Path = "tsar.db") -> None:
        """Initialize the knowledge graph tools.

        Args:
            db_path: Path to the SQLite database shared by all knowledge stores.
        """
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self.graph = KnowledgeGraph(self._db_path)
        logger.info("knowledge_graph_tools_init", db=self._db_path)

    # ── Direct cross-store queries ───────────────────────────

    def find_trades_by_regime_and_strategy(
        self,
        regime: str | None = None,
        strategy_id: str | None = None,
        symbol: str | None = None,
        status: str = "CLOSED",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find trades matching regime + strategy + symbol filters.

        Query path: trade_records → strategy_genomes (JOIN)

        Args:
            regime: Filter by regime at entry (e.g. "trending_up").
            strategy_id: Filter by strategy ID.
            symbol: Filter by trading pair.
            status: Trade status filter (default "CLOSED").
            limit: Maximum results.

        Returns:
            List of trade dicts with strategy info.
        """
        return self.graph.find_trades_by_regime_and_strategy(
            regime=regime,
            strategy_id=strategy_id,
            symbol=symbol,
            status=status,
            limit=limit,
        )

    def get_lessons_for_pattern(self, pattern_id: str) -> list[dict[str, Any]]:
        """Find all lessons from trades that matched a pattern.

        Query path: pattern → trade_patterns → trade_records → trade_lessons → lessons

        Args:
            pattern_id: The pattern to trace lessons from.

        Returns:
            List of lesson dicts with match scores.
        """
        return self.graph.get_lessons_for_pattern(pattern_id)

    def get_patterns_for_strategy(
        self,
        strategy_id: str,
        regime: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find patterns associated with a strategy's trades.

        Query path: strategy → trade_records → trade_patterns → patterns

        Args:
            strategy_id: The strategy to find patterns for.
            regime: Optional regime filter.

        Returns:
            List of pattern dicts with trade counts and match scores.
        """
        return self.graph.get_patterns_for_strategy(strategy_id, regime)

    def get_strategies_for_regime(self, regime: str) -> list[dict[str, Any]]:
        """Find strategies that performed well in a given regime.

        Query path: regime → trade_records → strategy_genomes

        Args:
            regime: The regime to evaluate strategies in.

        Returns:
            List of strategy dicts with PnL and win rate stats.
        """
        return self.graph.get_strategies_for_regime(regime)

    def get_regime_pattern_performance(
        self,
        regime: str,
        pattern_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find how patterns perform in a specific regime.

        Query path: regime → trade_records → trade_patterns → patterns

        Args:
            regime: The regime to analyze.
            pattern_id: Optional specific pattern to analyze.

        Returns:
            List of pattern performance dicts in the regime.
        """
        return self.graph.get_regime_pattern_performance(regime, pattern_id)

    # ── Graph traversal ──────────────────────────────────────

    def traverse(
        self,
        start_type: str,
        start_id: str,
        end_type: str | None = None,
        max_depth: int = 3,
        limit: int = 100,
        enrich: bool = False,
    ) -> list[dict[str, Any]]:
        """Traverse the knowledge graph from a starting node.

        Uses recursive CTE to walk across edges:
        - trade → strategy, pattern, lesson, regime
        - pattern → pattern (relationships)
        - strategy, lesson, regime → trade (reverse)

        Args:
            start_type: "trade", "strategy", "pattern", "lesson", or "regime"
            start_id: ID of the starting node.
            end_type: Optional filter for terminal node type.
            max_depth: Maximum hops (default 3).
            limit: Maximum paths to return.
            enrich: If True, enrich nodes with full data from source tables.

        Returns:
            List of path dicts with nodes and edges.
        """
        paths = self.graph.traverse(
            start_type=start_type,
            start_id=start_id,
            end_type=end_type,
            max_depth=max_depth,
            limit=limit,
        )

        if enrich:
            paths = [self.graph.enrich_path(p) for p in paths]

        return [p.to_dict() for p in paths]

    # ── Neighborhood queries ─────────────────────────────────

    def get_neighbors(
        self,
        node_type: str,
        node_id: str,
        relationship: str | None = None,
        limit: int = 50,
        enrich: bool = False,
    ) -> list[dict[str, Any]]:
        """Get immediate neighbors of a node.

        Args:
            node_type: "trade", "strategy", "pattern", "lesson", or "regime"
            node_id: ID of the node.
            relationship: Optional filter by relationship type.
            limit: Max neighbors to return.
            enrich: If True, enrich neighbor nodes with full data.

        Returns:
            List of neighbor node dicts.
        """
        neighbors = self.graph.get_neighbors(
            node_type=node_type,
            node_id=node_id,
            relationship=relationship,
            limit=limit,
        )

        if enrich:
            neighbors = [self.graph.enrich_node(n) for n in neighbors]

        return [n.to_dict() for n in neighbors]

    # ── Enrichment ───────────────────────────────────────────

    def enrich_node(self, node_type: str, node_id: str) -> dict[str, Any]:
        """Enrich a node with its full data from the source table.

        Args:
            node_type: "trade", "strategy", "pattern", or "lesson"
            node_id: ID of the node to enrich.

        Returns:
            Node dict with full data populated.
        """
        node = GraphNode(node_type=node_type, node_id=node_id)
        self.graph.enrich_node(node)
        return node.to_dict()

    def enrich_path(self, path: dict[str, Any]) -> dict[str, Any]:
        """Enrich all nodes in a path with their full data.

        Args:
            path: A path dict (as returned by traverse).

        Returns:
            Path dict with all nodes enriched.
        """
        graph_path = GraphPath(
            nodes=[GraphNode(**n) for n in path.get("nodes", [])],
            edges=[GraphEdge(**e) for e in path.get("edges", [])],
        )
        self.graph.enrich_path(graph_path)
        return graph_path.to_dict()

    # ── Graph statistics ─────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get knowledge graph statistics.

        Returns:
            Dict with node counts (trades, strategies, patterns, lessons,
            regimes) and edge counts (trade_pattern, trade_lesson,
            pattern_pattern).
        """
        return self.graph.get_graph_stats()

    # ── Higher-level graph queries ───────────────────────────

    def find_lesson_context(
        self,
        lesson_id: str,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Find the full context around a lesson: trades, patterns, regimes.

        Traverses backward from a lesson to find all related entities.

        Args:
            lesson_id: The lesson to find context for.
            max_depth: How many hops to traverse (default 2).

        Returns:
            Dict with lesson context: trades that led to it, patterns
            involved, regimes observed, strategies used.
        """
        paths = self.graph.traverse(
            start_type="lesson",
            start_id=lesson_id,
            max_depth=max_depth,
            limit=200,
        )

        # Aggregate related entities
        trades: dict[str, Any] = {}
        patterns: dict[str, Any] = {}
        strategies: dict[str, Any] = {}
        regimes: set[str] = set()

        for path in paths:
            for node in path.nodes:
                if node.node_type == "trade" and node.node_id not in trades:
                    self.graph.enrich_node(node)
                    trades[node.node_id] = node.data
                elif node.node_type == "pattern" and node.node_id not in patterns:
                    self.graph.enrich_node(node)
                    patterns[node.node_id] = node.data
                elif node.node_type == "strategy" and node.node_id not in strategies:
                    self.graph.enrich_node(node)
                    strategies[node.node_id] = node.data
                elif node.node_type == "regime":
                    regimes.add(node.node_id)

        return {
            "lesson_id": lesson_id,
            "related_trades": list(trades.values()),
            "related_patterns": list(patterns.values()),
            "related_strategies": list(strategies.values()),
            "regimes_observed": sorted(regimes),
            "path_count": len(paths),
        }

    def find_strategy_ecosystem(
        self,
        strategy_id: str,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Map the full ecosystem of a strategy: patterns, lessons, regimes.

        Args:
            strategy_id: The strategy to map.
            max_depth: How many hops to traverse (default 2).

        Returns:
            Dict with strategy ecosystem: patterns it trades, lessons
            learned, regimes it operates in, and trade count.
        """
        paths = self.graph.traverse(
            start_type="strategy",
            start_id=strategy_id,
            max_depth=max_depth,
            limit=200,
        )

        patterns: dict[str, Any] = {}
        lessons: dict[str, Any] = {}
        regimes: set[str] = set()
        trade_ids: set[str] = set()

        for path in paths:
            for node in path.nodes:
                if node.node_type == "trade":
                    trade_ids.add(node.node_id)
                elif node.node_type == "pattern" and node.node_id not in patterns:
                    self.graph.enrich_node(node)
                    patterns[node.node_id] = node.data
                elif node.node_type == "lesson" and node.node_id not in lessons:
                    self.graph.enrich_node(node)
                    lessons[node.node_id] = node.data
                elif node.node_type == "regime":
                    regimes.add(node.node_id)

        return {
            "strategy_id": strategy_id,
            "trade_count": len(trade_ids),
            "patterns_used": list(patterns.values()),
            "lessons_learned": list(lessons.values()),
            "regimes_traded": sorted(regimes),
            "path_count": len(paths),
        }

    def find_pattern_impact(
        self,
        pattern_id: str,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Analyze the impact of a pattern: trades, strategies, lessons, regimes.

        Args:
            pattern_id: The pattern to analyze.
            max_depth: How many hops to traverse (default 2).

        Returns:
            Dict with pattern impact analysis.
        """
        paths = self.graph.traverse(
            start_type="pattern",
            start_id=pattern_id,
            max_depth=max_depth,
            limit=200,
        )

        trades: dict[str, Any] = {}
        strategies: dict[str, Any] = {}
        lessons: dict[str, Any] = {}
        regimes: set[str] = set()

        for path in paths:
            for node in path.nodes:
                if node.node_type == "trade" and node.node_id not in trades:
                    self.graph.enrich_node(node)
                    trades[node.node_id] = node.data
                elif node.node_type == "strategy" and node.node_id not in strategies:
                    self.graph.enrich_node(node)
                    strategies[node.node_id] = node.data
                elif node.node_type == "lesson" and node.node_id not in lessons:
                    self.graph.enrich_node(node)
                    lessons[node.node_id] = node.data
                elif node.node_type == "regime":
                    regimes.add(node.node_id)

        # Compute pattern stats from trades
        total_pnl = sum(t.get("realized_pnl", 0) for t in trades.values())
        wins = sum(1 for t in trades.values() if t.get("realized_pnl", 0) > 0)

        return {
            "pattern_id": pattern_id,
            "trade_count": len(trades),
            "total_pnl": total_pnl,
            "win_rate": wins / len(trades) if trades else 0.0,
            "strategies_involved": list(strategies.values()),
            "lessons_generated": list(lessons.values()),
            "regimes_observed": sorted(regimes),
            "path_count": len(paths),
        }

    def find_regime_deep_dive(
        self,
        regime: str,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Deep dive into a regime: strategies, patterns, lessons, trades.

        Args:
            regime: The regime to analyze (e.g. "trending_up", "volatile").
            max_depth: How many hops to traverse (default 2).

        Returns:
            Dict with full regime analysis.
        """
        paths = self.graph.traverse(
            start_type="regime",
            start_id=regime,
            max_depth=max_depth,
            limit=200,
        )

        trades: dict[str, Any] = {}
        strategies: dict[str, Any] = {}
        patterns: dict[str, Any] = {}
        lessons: dict[str, Any] = {}

        for path in paths:
            for node in path.nodes:
                if node.node_type == "trade" and node.node_id not in trades:
                    self.graph.enrich_node(node)
                    trades[node.node_id] = node.data
                elif node.node_type == "strategy" and node.node_id not in strategies:
                    self.graph.enrich_node(node)
                    strategies[node.node_id] = node.data
                elif node.node_type == "pattern" and node.node_id not in patterns:
                    self.graph.enrich_node(node)
                    patterns[node.node_id] = node.data
                elif node.node_type == "lesson" and node.node_id not in lessons:
                    self.graph.enrich_node(node)
                    lessons[node.node_id] = node.data

        total_pnl = sum(t.get("realized_pnl", 0) for t in trades.values())
        wins = sum(1 for t in trades.values() if t.get("realized_pnl", 0) > 0)

        return {
            "regime": regime,
            "trade_count": len(trades),
            "total_pnl": total_pnl,
            "win_rate": wins / len(trades) if trades else 0.0,
            "strategies": list(strategies.values()),
            "patterns": list(patterns.values()),
            "lessons": list(lessons.values()),
            "path_count": len(paths),
        }
