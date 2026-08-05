"""TSAR — Complexity-Based Model Router & Cost Tracker.

Automatically selects the cheapest model that can handle the task:
  - Simple tasks → cheapest model (DeepSeek)
  - Complex analysis → mid-tier (Nemotron/MiniMax)
  - Critical decisions → best model available (DeepSeek R1)

Tracks cost per trade and calculates ROI: cost of AI vs profit.

Usage::

    from src.llm.complexity_router import ComplexityRouter, TaskComplexity

    router = ComplexityRouter(config_path="config/models.yaml")

    # Auto-select model for a task
    model = router.select_model(TaskComplexity.SIMPLE, "t2_signal_narrative")

    # Track cost for a trade
    router.record_trade_cost(trade_id="abc123", cost_usd=0.003, task_type="t2_signal_narrative")

    # Get ROI report
    roi = router.get_roi_report(trade_id="abc123")
    roi = router.get_roi_report(since="2025-01-01")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml

from src.utils.logging import get_logger

logger = get_logger(__name__)


class TaskComplexity(IntEnum):
    """Task complexity levels. Higher = more complex = needs better model."""

    TRIVIAL = 1    # Simple classification, yes/no decisions
    SIMPLE = 2     # Routine analysis, standard narratives
    MODERATE = 3   # Multi-factor analysis, regime explanations
    COMPLEX = 4    # Strategy synthesis, risk scenarios
    CRITICAL = 5   # Final trade decisions, portfolio rebalancing


@dataclass
class ModelTier:
    """A model tier with its capabilities and costs."""

    tier: int
    name: str
    model_path: str  # e.g. "deepseek/deepseek-reasoner"
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_context_tokens: int
    capabilities: list[str]
    speed_rating: str  # "fast", "medium", "slow"
    quality_rating: str  # "good", "great", "excellent"

    @property
    def provider(self) -> str:
        return self.model_path.split("/")[0]

    @property
    def model_name(self) -> str:
        return self.model_path.split("/", 1)[1] if "/" in self.model_path else self.model_path

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a request."""
        input_cost = (input_tokens / 1000) * self.cost_per_1k_input
        output_cost = (output_tokens / 1000) * self.cost_per_1k_output
        return input_cost + output_cost


@dataclass
class TradeCostRecord:
    """Cost record for a single trade's AI usage."""

    trade_id: str
    cost_usd: float
    task_type: str
    model_used: str
    complexity: int
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


@dataclass
class ROIReport:
    """ROI analysis: AI cost vs trade profit."""

    trade_id: str | None = None
    period: str | None = None
    total_ai_cost_usd: float = 0.0
    total_trade_pnl_usd: float = 0.0
    trade_count: int = 0
    roi_pct: float = 0.0
    cost_per_trade_usd: float = 0.0
    avg_pnl_per_trade_usd: float = 0.0
    profitable_trades: int = 0
    unprofitable_trades: int = 0
    cost_to_pnl_ratio: float = 0.0  # How many $ of AI cost per $ of profit
    breakdown_by_task: dict[str, float] = field(default_factory=dict)
    breakdown_by_model: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "period": self.period,
            "total_ai_cost_usd": round(self.total_ai_cost_usd, 6),
            "total_trade_pnl_usd": round(self.total_trade_pnl_usd, 4),
            "trade_count": self.trade_count,
            "roi_pct": round(self.roi_pct, 2),
            "cost_per_trade_usd": round(self.cost_per_trade_usd, 6),
            "avg_pnl_per_trade_usd": round(self.avg_pnl_per_trade_usd, 4),
            "profitable_trades": self.profitable_trades,
            "unprofitable_trades": self.unprofitable_trades,
            "cost_to_pnl_ratio": round(self.cost_to_pnl_ratio, 6),
            "breakdown_by_task": {k: round(v, 6) for k, v in self.breakdown_by_task.items()},
            "breakdown_by_model": {k: round(v, 6) for k, v in self.breakdown_by_model.items()},
        }


# ── Model tier definitions ───────────────────────────────────
# These match config/models.yaml. Kept as defaults; can be overridden.

_DEFAULT_TIERS: list[ModelTier] = [
    ModelTier(
        tier=1,
        name="economy",
        model_path="deepseek/deepseek-reasoner",
        cost_per_1k_input=0.00055,
        cost_per_1k_output=0.00219,
        max_context_tokens=65536,
        capabilities=["text_generation", "reasoning", "json_mode"],
        speed_rating="medium",
        quality_rating="great",
    ),
    ModelTier(
        tier=2,
        name="standard",
        model_path="nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context_tokens=131072,
        capabilities=["text_generation", "reasoning", "json_mode"],
        speed_rating="medium",
        quality_rating="great",
    ),
    ModelTier(
        tier=3,
        name="premium",
        model_path="nvidia_nim/minimaxai/minimax-m3",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context_tokens=131072,
        capabilities=["text_generation", "reasoning", "json_mode", "vision"],
        speed_rating="medium",
        quality_rating="excellent",
    ),
    ModelTier(
        tier=4,
        name="frontier",
        model_path="nvidia_nim/deepseek-ai/deepseek-r1",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context_tokens=65536,
        capabilities=["text_generation", "reasoning"],
        speed_rating="slow",
        quality_rating="excellent",
    ),
    ModelTier(
        tier=5,
        name="budget",
        model_path="openai/gpt-4o-mini",
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        max_context_tokens=128000,
        capabilities=["text_generation", "json_mode"],
        speed_rating="fast",
        quality_rating="good",
    ),
]


# ── Task type → complexity mapping ───────────────────────────

_TASK_COMPLEXITY_MAP: dict[str, TaskComplexity] = {
    # Tier 1: Embeddings (trivial)
    "t1_pattern_embedding": TaskComplexity.TRIVIAL,

    # Tier 2: Routine tasks (simple)
    "t2_regime_explanation": TaskComplexity.SIMPLE,
    "t2_signal_narrative": TaskComplexity.SIMPLE,
    "t2_risk_explanation": TaskComplexity.SIMPLE,
    "t2_trade_summary": TaskComplexity.SIMPLE,
    "t2_news_sentiment": TaskComplexity.SIMPLE,
    "t2_daily_summary": TaskComplexity.MODERATE,
    "t2_anomaly_explanation": TaskComplexity.MODERATE,
    "t2_strategy_evaluation": TaskComplexity.MODERATE,

    # Tier 3: Complex reasoning
    "t3_trade_narrative": TaskComplexity.COMPLEX,
    "t3_strategy_synthesis": TaskComplexity.COMPLEX,
    "t3_risk_scenario": TaskComplexity.CRITICAL,
    "t3_bias_detection": TaskComplexity.COMPLEX,
}


class ComplexityRouter:
    """Route LLM calls based on task complexity with cost tracking.

    Args:
        config_path: Path to models.yaml (for cost data).
        tiers: Optional custom model tier list.
    """

    def __init__(
        self,
        config_path: str | None = None,
        tiers: list[ModelTier] | None = None,
    ) -> None:
        self._tiers = tiers or list(_DEFAULT_TIERS)
        self._tiers.sort(key=lambda t: t.tier)

        # Cost tracking
        self._trade_costs: list[TradeCostRecord] = []
        self._total_cost_usd: float = 0.0
        self._cost_by_task: dict[str, float] = {}
        self._cost_by_model: dict[str, float] = {}

        # Load cost overrides from config
        if config_path:
            self._load_config_costs(config_path)

        logger.info(
            "complexity_router_initialized",
            tier_count=len(self._tiers),
        )

    def _load_config_costs(self, config_path: str) -> None:
        """Load cost data from models.yaml to update tier costs."""
        try:
            path = Path(config_path)
            if not path.exists():
                return
            with open(path) as f:
                config = yaml.safe_load(f)
            models = config.get("models", {})
            for tier in self._tiers:
                model_cfg = models.get(tier.model_path, {})
                if model_cfg:
                    tier.cost_per_1k_input = model_cfg.get(
                        "cost_per_1k_input_tokens", tier.cost_per_1k_input
                    )
                    tier.cost_per_1k_output = model_cfg.get(
                        "cost_per_1k_output_tokens", tier.cost_per_1k_output
                    )
        except Exception as exc:
            logger.warning("config_cost_load_failed", error=str(exc))

    # ── Model selection ──────────────────────────────────────

    def select_model(
        self,
        complexity: TaskComplexity | int,
        task_type: str | None = None,
        budget_remaining_usd: float | None = None,
        prefer_speed: bool = False,
    ) -> ModelTier:
        """Select the cheapest model that can handle the complexity.

        Args:
            complexity: Task complexity level.
            task_type: Optional task type (auto-detects complexity if provided).
            budget_remaining_usd: If set, prefer cheaper models when budget is low.
            prefer_speed: If True, prefer faster models over cheaper ones.

        Returns:
            The selected ModelTier.
        """
        if task_type and isinstance(complexity, str):
            complexity = _TASK_COMPLEXITY_MAP.get(task_type, TaskComplexity.MODERATE)

        complexity = int(complexity)

        # Filter tiers that can handle this complexity
        # Tier mapping: complexity 1-2 → tier 1-2, complexity 3 → tier 2-3, etc.
        suitable: list[ModelTier] = []
        for tier in self._tiers:
            if self._tier_can_handle(tier, complexity):
                suitable.append(tier)

        if not suitable:
            # Fallback to highest tier
            suitable = [self._tiers[-1]]

        # Sort by cost (cheapest first) or speed
        if prefer_speed:
            speed_order = {"fast": 0, "medium": 1, "slow": 2}
            suitable.sort(key=lambda t: (speed_order.get(t.speed_rating, 1), t.cost_per_1k_input))
        else:
            suitable.sort(key=lambda t: t.cost_per_1k_input)

        # If budget is very low, prefer free models
        if budget_remaining_usd is not None and budget_remaining_usd < 0.01:
            free_models = [t for t in suitable if t.cost_per_1k_input == 0 and t.cost_per_1k_output == 0]
            if free_models:
                suitable = free_models

        selected = suitable[0]
        logger.debug(
            "model_selected",
            complexity=complexity,
            task_type=task_type,
            selected=selected.model_path,
            tier=selected.tier,
        )
        return selected

    def _tier_can_handle(self, tier: ModelTier, complexity: int) -> bool:
        """Check if a tier can handle the given complexity level."""
        # Map complexity to minimum tier required
        min_tier_map = {
            1: 1,  # TRIVIAL → any tier
            2: 1,  # SIMPLE → any tier
            3: 1,  # MODERATE → tier 1+ (all have reasoning)
            4: 2,  # COMPLEX → tier 2+
            5: 3,  # CRITICAL → tier 3+
        }
        min_tier = min_tier_map.get(complexity, 1)
        return tier.tier >= min_tier

    def get_task_complexity(self, task_type: str) -> TaskComplexity:
        """Get the complexity level for a task type.

        Args:
            task_type: The task type string.

        Returns:
            TaskComplexity level.
        """
        return _TASK_COMPLEXITY_MAP.get(task_type, TaskComplexity.MODERATE)

    # ── Cost tracking ────────────────────────────────────────

    def record_cost(
        self,
        cost_usd: float,
        task_type: str,
        model_used: str,
        trade_id: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record the cost of an LLM call.

        Args:
            cost_usd: Cost in USD.
            task_type: Task type that was executed.
            model_used: Model that was used.
            trade_id: Optional trade ID to associate cost with.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
        """
        self._total_cost_usd += cost_usd
        self._cost_by_task[task_type] = self._cost_by_task.get(task_type, 0.0) + cost_usd
        self._cost_by_model[model_used] = self._cost_by_model.get(model_used, 0.0) + cost_usd

        if trade_id:
            complexity = _TASK_COMPLEXITY_MAP.get(task_type, TaskComplexity.MODERATE)
            record = TradeCostRecord(
                trade_id=trade_id,
                cost_usd=cost_usd,
                task_type=task_type,
                model_used=model_used,
                complexity=int(complexity),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            self._trade_costs.append(record)

        logger.debug(
            "cost_recorded",
            cost_usd=cost_usd,
            task_type=task_type,
            model=model_used,
            trade_id=trade_id,
        )

    def record_trade_cost(
        self,
        trade_id: str,
        cost_usd: float,
        task_type: str,
        model_used: str = "",
    ) -> None:
        """Convenience method to record cost associated with a trade.

        Args:
            trade_id: Trade ID.
            cost_usd: Cost in USD.
            task_type: Task type that generated the cost.
            model_used: Model that was used.
        """
        self.record_cost(
            cost_usd=cost_usd,
            task_type=task_type,
            model_used=model_used,
            trade_id=trade_id,
        )

    # ── ROI calculation ──────────────────────────────────────

    def get_roi_report(
        self,
        trade_id: str | None = None,
        since: str | None = None,
        trade_pnl: float | None = None,
    ) -> ROIReport:
        """Calculate ROI: AI cost vs trade profit.

        Args:
            trade_id: Calculate ROI for a specific trade.
            since: Calculate ROI for trades after this date (ISO format).
            trade_pnl: Override P&L for single-trade ROI (otherwise uses 0).

        Returns:
            ROIReport with full analysis.
        """
        report = ROIReport(trade_id=trade_id)

        # Filter cost records
        if trade_id:
            records = [r for r in self._trade_costs if r.trade_id == trade_id]
            report.period = f"trade:{trade_id}"
        elif since:
            records = [r for r in self._trade_costs if r.timestamp >= since]
            report.period = f"since:{since}"
        else:
            records = list(self._trade_costs)
            report.period = "all_time"

        if not records:
            # Return empty report with current totals
            report.total_ai_cost_usd = self._total_cost_usd
            return report

        # Aggregate costs
        report.total_ai_cost_usd = sum(r.cost_usd for r in records)
        report.trade_count = len(set(r.trade_id for r in records))

        # P&L data
        if trade_pnl is not None:
            report.total_trade_pnl_usd = trade_pnl
            if trade_pnl > 0:
                report.profitable_trades = 1
            elif trade_pnl < 0:
                report.unprofitable_trades = 1
        else:
            report.total_trade_pnl_usd = 0.0  # Unknown without TradeMemory integration

        # Cost per trade
        if report.trade_count > 0:
            report.cost_per_trade_usd = report.total_ai_cost_usd / report.trade_count

        # ROI calculation
        if report.total_trade_pnl_usd > 0 and report.total_ai_cost_usd > 0:
            report.roi_pct = (
                (report.total_trade_pnl_usd - report.total_ai_cost_usd)
                / report.total_ai_cost_usd
                * 100
            )
            report.cost_to_pnl_ratio = report.total_ai_cost_usd / report.total_trade_pnl_usd
        elif report.total_ai_cost_usd > 0:
            report.roi_pct = -100.0  # All cost, no profit

        # Breakdown by task type
        for r in records:
            report.breakdown_by_task[r.task_type] = (
                report.breakdown_by_task.get(r.task_type, 0.0) + r.cost_usd
            )
            report.breakdown_by_model[r.model_used] = (
                report.breakdown_by_model.get(r.model_used, 0.0) + r.cost_usd
            )

        return report

    def get_cost_summary(self) -> dict[str, Any]:
        """Get a summary of all tracked costs.

        Returns:
            Dict with cost breakdowns and statistics.
        """
        return {
            "total_cost_usd": round(self._total_cost_usd, 6),
            "total_calls": len(self._trade_costs),
            "unique_trades": len(set(r.trade_id for r in self._trade_costs)),
            "by_task_type": {k: round(v, 6) for k, v in self._cost_by_task.items()},
            "by_model": {k: round(v, 6) for k, v in self._cost_by_model.items()},
            "avg_cost_per_call": (
                round(self._total_cost_usd / len(self._trade_costs), 6)
                if self._trade_costs
                else 0.0
            ),
        }

    def get_model_cost_estimate(
        self,
        task_type: str,
        estimated_input_tokens: int = 1000,
        estimated_output_tokens: int = 500,
    ) -> dict[str, dict[str, Any]]:
        """Estimate cost for a task across all model tiers.

        Args:
            task_type: Task type to estimate.
            estimated_input_tokens: Expected input tokens.
            estimated_output_tokens: Expected output tokens.

        Returns:
            Dict mapping model name to cost estimate.
        """
        complexity = _TASK_COMPLEXITY_MAP.get(task_type, TaskComplexity.MODERATE)
        estimates: dict[str, dict[str, Any]] = {}

        for tier in self._tiers:
            cost = tier.estimate_cost(estimated_input_tokens, estimated_output_tokens)
            can_handle = self._tier_can_handle(tier, int(complexity))
            estimates[tier.model_path] = {
                "tier": tier.name,
                "estimated_cost_usd": round(cost, 6),
                "can_handle_task": can_handle,
                "speed": tier.speed_rating,
                "quality": tier.quality_rating,
                "is_free": cost == 0.0,
            }

        return estimates

    # ── Integration with ModelRouter ─────────────────────────

    def enhance_task_type_routing(
        self,
        task_type: str,
        original_route: dict[str, Any],
        budget_remaining_usd: float | None = None,
    ) -> dict[str, Any]:
        """Enhance an existing route config with complexity-based model selection.

        Args:
            task_type: Task type.
            original_route: Original routing config from models.yaml.
            budget_remaining_usd: Remaining budget.

        Returns:
            Enhanced routing config.
        """
        complexity = self.get_task_complexity(task_type)
        selected = self.select_model(
            complexity=complexity,
            task_type=task_type,
            budget_remaining_usd=budget_remaining_usd,
        )

        enhanced = dict(original_route)

        # If the selected model is cheaper than the primary, consider using it
        primary_model = original_route.get("primary", "")
        primary_tier = next(
            (t for t in self._tiers if t.model_path == primary_model), None
        )

        if primary_tier and selected.cost_per_1k_input < primary_tier.cost_per_1k_input:
            # Downgrade primary to save money (keep original as fallback)
            enhanced["primary"] = selected.model_path
            fallbacks = original_route.get("fallback", [])
            if primary_model not in fallbacks:
                enhanced["fallback"] = [primary_model] + fallbacks
            enhanced["_cost_optimized"] = True
            logger.debug(
                "route_cost_optimized",
                task_type=task_type,
                original=primary_model,
                optimized=selected.model_path,
            )

        return enhanced

    # ── Stats ────────────────────────────────────────────────

    @property
    def total_cost(self) -> float:
        """Total tracked cost in USD."""
        return self._total_cost_usd

    @property
    def call_count(self) -> int:
        """Total number of tracked calls."""
        return len(self._trade_costs)

    @property
    def unique_trades(self) -> int:
        """Number of unique trades with costs."""
        return len(set(r.trade_id for r in self._trade_costs))
