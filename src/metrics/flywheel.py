"""
Flywheel Health Score — Measure TSAR's self-improvement loop effectiveness.

Composite score (0-1) answering "Is TSAR getting better?"

Weights:
  expectancy_trend:        0.15
  sharpe_trend:            0.15
  regime_accuracy:         0.10
  lesson_application_rate: 0.10
  lesson_violation_rate:   0.10
  knowledge_density:       0.10
  strategy_fitness:        0.10
  pattern_discovery_rate:  0.05
  execution_quality:       0.075
  risk_adjusted_return:    0.075

Classification:
  > 0.7: 🟢 Healthy
  0.4-0.7: 🟡 Stalling
  < 0.4: 🔴 Broken
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


FLYWHEEL_WEIGHTS = {
    "expectancy_trend": 0.15,
    "sharpe_trend": 0.15,
    "regime_accuracy": 0.10,
    "lesson_application_rate": 0.10,
    "lesson_violation_rate": 0.10,
    "knowledge_density": 0.10,
    "strategy_fitness": 0.10,
    "pattern_discovery_rate": 0.05,
    "execution_quality": 0.075,
    "risk_adjusted_return": 0.075,
}


class FlywheelHealthScore:
    """Compute and track the flywheel health score.

    The flywheel measures whether TSAR's self-improvement loop is working:
    trading -> analyzing -> learning -> improving -> trading better.

    Each component is a normalized score (0-1). The composite is a
    weighted sum classified as healthy/stalling/broken.

    Usage::

        flywheel = FlywheelHealthScore("data/flywheel.json")
        score = flywheel.compute({
            "expectancy_trend": 0.8,
            "sharpe_trend": 0.6,
            ...
        })
        flywheel.add_to_history(score)
        trend = flywheel.get_trend()
    """

    def __init__(self, persistence_path: str | Path | None = None) -> None:
        self._path = Path(persistence_path) if persistence_path else None
        self._history: list[dict[str, Any]] = []
        self._load()

    # ── Computation ──────────────────────────────────────────

    def compute(self, metrics: dict[str, float]) -> dict[str, Any]:
        """Compute flywheel health from component metrics.

        Args:
            metrics: Dict of metric_name -> normalized_score (0-1).
                     Missing metrics default to 0.5 (neutral).

        Returns:
            Dict with health_score, classification, emoji, component_scores,
            timestamp, and weighted_breakdown.
        """
        total = 0.0
        component_scores: dict[str, dict[str, float]] = {}
        missing_components: list[str] = []

        for metric_name, weight in FLYWHEEL_WEIGHTS.items():
            score = metrics.get(metric_name)
            if score is None:
                score = 0.5  # Default neutral
                missing_components.append(metric_name)
            # Clamp to [0, 1]
            score = max(0.0, min(1.0, score))
            weighted = score * weight
            total += weighted
            component_scores[metric_name] = {
                "score": round(score, 4),
                "weight": weight,
                "weighted": round(weighted, 4),
            }

        # Classification
        if total > 0.7:
            classification = "healthy"
            emoji = "🟢"
        elif total > 0.4:
            classification = "stalling"
            emoji = "🟡"
        else:
            classification = "broken"
            emoji = "🔴"

        result: dict[str, Any] = {
            "health_score": round(total, 4),
            "classification": classification,
            "emoji": emoji,
            "component_scores": component_scores,
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }

        if missing_components:
            result["missing_components"] = missing_components

        # Identify weakest components
        sorted_components = sorted(
            component_scores.items(),
            key=lambda x: x[1]["score"],
        )
        result["weakest"] = [
            {"name": name, "score": vals["score"]} for name, vals in sorted_components[:3]
        ]

        return result

    # ── History & Trend ──────────────────────────────────────

    def add_to_history(self, score_result: dict[str, Any]) -> None:
        """Add a computed score to the history.

        Args:
            score_result: Output from compute().
        """
        self._history.append(score_result)
        # Keep last 500 entries
        if len(self._history) > 500:
            self._history = self._history[-500:]
        self._save()

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent health score history."""
        return self._history[-limit:]

    def get_trend(self, window: int = 10) -> dict[str, Any]:
        """Compute the trend of the flywheel health score.

        Args:
            window: Number of recent entries to consider.

        Returns:
            Dict with current, average, trend direction, and component trends.
        """
        recent = self._history[-window:]
        if not recent:
            return {"current": 0.0, "average": 0.0, "direction": "unknown", "entries": 0}

        scores = [r["health_score"] for r in recent]
        current = scores[-1]
        avg = sum(scores) / len(scores)

        # Simple trend: compare first half average to second half
        mid = len(scores) // 2
        if mid > 0:
            first_half = sum(scores[:mid]) / mid
            second_half = sum(scores[mid:]) / (len(scores) - mid)
            if second_half > first_half + 0.02:
                direction = "improving"
            elif second_half < first_half - 0.02:
                direction = "declining"
            else:
                direction = "stable"
        else:
            direction = "insufficient_data"

        # Component trends
        component_trends: dict[str, float] = {}
        if len(recent) >= 2:
            first = recent[0].get("component_scores", {})
            last = recent[-1].get("component_scores", {})
            for comp_name in FLYWHEEL_WEIGHTS:
                f_score = first.get(comp_name, {}).get("score", 0.5)
                l_score = last.get(comp_name, {}).get("score", 0.5)
                component_trends[comp_name] = round(l_score - f_score, 4)

        return {
            "current": round(current, 4),
            "average": round(avg, 4),
            "direction": direction,
            "entries": len(recent),
            "component_trends": component_trends,
        }

    # ── Component Builders ───────────────────────────────────

    @staticmethod
    def compute_component_from_trades(
        pnl_history: list[float],
        sharpe_history: list[float] | None = None,
    ) -> dict[str, float]:
        """Compute flywheel components from trade history.

        Args:
            pnl_history: List of P&L values from recent trades.
            sharpe_history: List of rolling Sharpe values (optional).

        Returns:
            Dict of component scores (0-1) for expectancy_trend and sharpe_trend.
        """
        components: dict[str, float] = {}

        # Expectancy trend
        if len(pnl_history) >= 4:
            mid = len(pnl_history) // 2
            first_half = pnl_history[:mid]
            second_half = pnl_history[mid:]
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            if avg_second > avg_first:
                # Improving: map to 0.5-1.0
                improvement = (avg_second - avg_first) / max(abs(avg_first), 1.0)
                components["expectancy_trend"] = min(1.0, 0.5 + improvement)
            else:
                # Declining: map to 0.0-0.5
                decline = (avg_first - avg_second) / max(abs(avg_first), 1.0)
                components["expectancy_trend"] = max(0.0, 0.5 - decline)
        elif pnl_history:
            # Single half: positive = good
            avg = sum(pnl_history) / len(pnl_history)
            components["expectancy_trend"] = min(1.0, max(0.0, 0.5 + avg / 100))

        # Sharpe trend
        if sharpe_history and len(sharpe_history) >= 2:
            mid = len(sharpe_history) // 2
            first_half = sharpe_history[:mid]
            second_half = sharpe_history[mid:]
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            # Sharpe of 1.0+ is good, map to 0-1
            components["sharpe_trend"] = min(1.0, max(0.0, avg_second / 2.0))

        return components

    @staticmethod
    def compute_component_from_knowledge(
        lessons_applied: int,
        lessons_violated: int,
        total_lessons: int,
        patterns_discovered: int,
        total_patterns: int,
    ) -> dict[str, float]:
        """Compute knowledge-related flywheel components.

        Returns:
            Dict with lesson_application_rate, lesson_violation_rate,
            knowledge_density, pattern_discovery_rate.
        """
        components: dict[str, float] = {}

        # Lesson application rate
        if total_lessons > 0:
            components["lesson_application_rate"] = min(1.0, lessons_applied / total_lessons)

        # Lesson violation rate (lower is better, so invert)
        if total_lessons > 0:
            violation_rate = lessons_violated / total_lessons
            components["lesson_violation_rate"] = max(0.0, 1.0 - violation_rate * 2)

        # Knowledge density
        components["knowledge_density"] = min(1.0, total_lessons / 50.0)  # 50 lessons = full score

        # Pattern discovery rate
        components["pattern_discovery_rate"] = min(
            1.0, total_patterns / 20.0
        )  # 20 patterns = full score

        return components

    # ── Persistence ──────────────────────────────────────────

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump({"history": self._history[-500:]}, f, indent=2)

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            self._history = data.get("history", [])
            logger.info(f"Loaded flywheel history: {len(self._history)} entries")
        except Exception as e:
            logger.error(f"Failed to load flywheel history: {e}")


# ═══════════════════════════════════════════════════════════════════════
# LEGACY COMPAT — FlywheelHealth (simple compute)
# ═══════════════════════════════════════════════════════════════════════


class FlywheelHealth:
    """Simple flywheel health computation (legacy API).

    For stateful tracking with history and trends, use FlywheelHealthScore.
    """

    def compute(self, metrics: dict[str, float]) -> dict[str, Any]:
        """Compute flywheel health from component metrics.

        Args:
            metrics: Dict of metric_name -> normalized_score (0-1)

        Returns:
            Dict with health_score, classification, component_scores
        """
        total = 0.0
        component_scores = {}

        for metric_name, weight in FLYWHEEL_WEIGHTS.items():
            score = metrics.get(metric_name, 0.5)  # Default neutral
            score = max(0.0, min(1.0, score))
            weighted = score * weight
            total += weighted
            component_scores[metric_name] = {"score": score, "weighted": weighted}

        if total > 0.7:
            classification = "healthy"
            emoji = "🟢"
        elif total > 0.4:
            classification = "stalling"
            emoji = "🟡"
        else:
            classification = "broken"
            emoji = "🔴"

        return {
            "health_score": round(total, 4),
            "classification": classification,
            "emoji": emoji,
            "component_scores": component_scores,
        }
