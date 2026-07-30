"""TSAR — LLM Output Evaluation Framework (H-006).

Tracks quality metrics for LLM-generated trading outputs:
- Signal accuracy: Did LLM-flagged signals match actual outcomes?
- Prediction quality: How well did LLM narratives align with trade results?
- Lesson relevance: Did extracted lessons improve subsequent performance?

All metrics are computed from TradeMemory history — no external dependencies.

NVIDIA Nemo Evaluator Integration (optional):
- Multi-dimensional evaluation: factual accuracy, risk awareness, actionability, coherence
- Structured scoring with configurable thresholds
- Graceful fallback to internal evaluator if Nemo unavailable
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.knowledge.trade_memory import TradeMemory

logger = logging.getLogger(__name__)

# ── Nemo Evaluator availability check ───────────────────────

try:
    # NVIDIA Nemo Evaluator Plugin
    from nemo_evaluator import NemoEvaluator
    NEMO_EVALUATOR_AVAILABLE = True
    logger.info("nemo_evaluator_available", msg="NVIDIA Nemo Evaluator enabled")
except ImportError:
    NEMO_EVALUATOR_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class SignalAccuracyMetrics:
    """Signal accuracy evaluation results.

    Attributes:
        total_signals: Total LLM-generated signals evaluated.
        profitable_signals: Signals that resulted in profitable trades.
        accuracy: Win rate of LLM signals (profitable / total).
        avg_score_winners: Average signal score for winning trades.
        avg_score_losers: Average signal score for losing trades.
        score_calibration: How well scores predict outcomes (higher = better).
    """
    total_signals: int = 0
    profitable_signals: int = 0
    accuracy: float = 0.0
    avg_score_winners: float = 0.0
    avg_score_losers: float = 0.0
    score_calibration: float = 0.0  # correlation between score and outcome


@dataclass
class PredictionQualityMetrics:
    """LLM narrative/analysis quality metrics.

    Attributes:
        narratives_evaluated: Number of trade narratives assessed.
        directional_accuracy: % of narratives where direction matched outcome.
        avg_confidence_alignment: How well LLM confidence matched actual results.
        bias_detection_rate: How often bias warnings preceded actual losses.
    """
    narratives_evaluated: int = 0
    directional_accuracy: float = 0.0
    avg_confidence_alignment: float = 0.0
    bias_detection_rate: float = 0.0


@dataclass
class LessonRelevanceMetrics:
    """Lesson extraction quality metrics.

    Attributes:
        lessons_extracted: Total lessons extracted by LLM.
        lessons_applied: Lessons that were subsequently applied.
        improvement_after_lesson: Win rate change after applying lessons.
        avg_rule_confidence: Average confidence of extracted rules.
    """
    lessons_extracted: int = 0
    lessons_applied: int = 0
    improvement_after_lesson: float = 0.0
    avg_rule_confidence: float = 0.0


@dataclass
class EvaluationReport:
    """Complete LLM evaluation report.

    Attributes:
        signal_accuracy: Signal-level accuracy metrics.
        prediction_quality: Narrative quality metrics.
        lesson_relevance: Lesson extraction metrics.
        overall_score: Composite quality score 0-1.
        evaluated_at: Timestamp of evaluation.
        lookback_days: Number of days of history analyzed.
    """
    signal_accuracy: SignalAccuracyMetrics = field(default_factory=SignalAccuracyMetrics)
    prediction_quality: PredictionQualityMetrics = field(default_factory=PredictionQualityMetrics)
    lesson_relevance: LessonRelevanceMetrics = field(default_factory=LessonRelevanceMetrics)
    overall_score: float = 0.0
    evaluated_at: str = ""
    lookback_days: int = 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_accuracy": {
                "total_signals": self.signal_accuracy.total_signals,
                "profitable_signals": self.signal_accuracy.profitable_signals,
                "accuracy": round(self.signal_accuracy.accuracy, 4),
                "avg_score_winners": round(self.signal_accuracy.avg_score_winners, 4),
                "avg_score_losers": round(self.signal_accuracy.avg_score_losers, 4),
                "score_calibration": round(self.signal_accuracy.score_calibration, 4),
            },
            "prediction_quality": {
                "narratives_evaluated": self.prediction_quality.narratives_evaluated,
                "directional_accuracy": round(self.prediction_quality.directional_accuracy, 4),
                "avg_confidence_alignment": round(self.prediction_quality.avg_confidence_alignment, 4),
                "bias_detection_rate": round(self.prediction_quality.bias_detection_rate, 4),
            },
            "lesson_relevance": {
                "lessons_extracted": self.lesson_relevance.lessons_extracted,
                "lessons_applied": self.lesson_relevance.lessons_applied,
                "improvement_after_lesson": round(self.lesson_relevance.improvement_after_lesson, 4),
                "avg_rule_confidence": round(self.lesson_relevance.avg_rule_confidence, 4),
            },
            "overall_score": round(self.overall_score, 4),
            "evaluated_at": self.evaluated_at,
            "lookback_days": self.lookback_days,
        }


# ═══════════════════════════════════════════════════════════════════════
# EVALUATOR
# ═══════════════════════════════════════════════════════════════════════


class LLMEvaluator:
    """Evaluate LLM output quality for trading signals.

    Pulls closed trades from TradeMemory and computes metrics
    on signal accuracy, prediction quality, and lesson relevance.

    Usage::

        evaluator = LLMEvaluator(trade_memory)
        report = evaluator.evaluate(lookback_days=30)
        print(f\"Overall LLM quality: {report.overall_score:.2f}\")
    """

    def __init__(self, trade_memory: TradeMemory) -> None:
        self._memory = trade_memory

    def evaluate(self, lookback_days: int = 30) -> EvaluationReport:
        """Run a full evaluation over recent trade history.

        Args:
            lookback_days: Number of days of history to analyze.

        Returns:
            EvaluationReport with all metrics.
        """
        from datetime import timedelta

        since = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

        closed_trades = self._memory.list_trades(
            status="CLOSED", since=since, limit=1000
        )

        signal_acc = self._evaluate_signal_accuracy(closed_trades)
        pred_quality = self._evaluate_prediction_quality(closed_trades)
        lesson_rel = self._evaluate_lesson_relevance(closed_trades)

        # Composite score: weighted average
        overall = (
            signal_acc.accuracy * 0.5
            + pred_quality.directional_accuracy * 0.3
            + lesson_rel.improvement_after_lesson * 0.2
        )

        report = EvaluationReport(
            signal_accuracy=signal_acc,
            prediction_quality=pred_quality,
            lesson_relevance=lesson_rel,
            overall_score=max(0.0, min(1.0, overall)),
            evaluated_at=datetime.now(UTC).isoformat(),
            lookback_days=lookback_days,
        )

        logger.info(
            "LLM evaluation complete: overall=%.3f, signal_acc=%.3f, "
            "pred_quality=%.3f, lesson_rel=%.3f (trades=%d)",
            report.overall_score,
            signal_acc.accuracy,
            pred_quality.directional_accuracy,
            lesson_rel.improvement_after_lesson,
            len(closed_trades),
        )
        return report

    def _evaluate_signal_accuracy(
        self, trades: list[Any]
    ) -> SignalAccuracyMetrics:
        """Evaluate signal accuracy from closed trade outcomes.

        Checks:
        - Win rate of signals
        - Score calibration (do higher-scored signals win more?)
        """
        if not trades:
            return SignalAccuracyMetrics()

        total = len(trades)
        winners = [t for t in trades if t.realized_pnl > 0]
        losers = [t for t in trades if t.realized_pnl <= 0]

        win_scores = [t.signal_score for t in winners if hasattr(t, "signal_score")]
        lose_scores = [t.signal_score for t in losers if hasattr(t, "signal_score")]

        avg_win = sum(win_scores) / len(win_scores) if win_scores else 0.0
        avg_lose = sum(lose_scores) / len(lose_scores) if lose_scores else 0.0

        # Score calibration: difference between avg winner score and avg loser score
        # Higher = scores are predictive
        calibration = avg_win - avg_lose

        return SignalAccuracyMetrics(
            total_signals=total,
            profitable_signals=len(winners),
            accuracy=len(winners) / total if total > 0 else 0.0,
            avg_score_winners=avg_win,
            avg_score_losers=avg_lose,
            score_calibration=max(0.0, min(1.0, calibration)),
        )

    def _evaluate_prediction_quality(
        self, trades: list[Any]
    ) -> PredictionQualityMetrics:
        """Evaluate narrative/prediction quality.

        Checks:
        - Directional accuracy: did the signal direction match the outcome?
        - Confidence alignment: did high-confidence signals perform better?
        """
        if not trades:
            return PredictionQualityMetrics()

        # Directional accuracy: BUY signals should have positive P&L
        correct_direction = 0
        total_with_direction = 0
        confidence_scores: list[float] = []
        outcome_scores: list[float] = []

        for trade in trades:
            if not hasattr(trade, "side") or not hasattr(trade, "realized_pnl"):
                continue
            total_with_direction += 1

            is_buy = trade.side.lower() == "buy"
            is_profitable = trade.realized_pnl > 0
            if (is_buy and is_profitable) or (not is_buy and not is_profitable):
                correct_direction += 1

            if hasattr(trade, "confidence") and trade.confidence is not None:
                confidence_scores.append(float(trade.confidence))
                outcome_scores.append(1.0 if is_profitable else 0.0)

        # Confidence-outcome alignment (simple correlation)
        alignment = 0.0
        if len(confidence_scores) >= 3:
            alignment = self._simple_correlation(confidence_scores, outcome_scores)

        return PredictionQualityMetrics(
            narratives_evaluated=total_with_direction,
            directional_accuracy=(
                correct_direction / total_with_direction
                if total_with_direction > 0
                else 0.0
            ),
            avg_confidence_alignment=max(0.0, alignment),
            bias_detection_rate=0.0,  # Requires bias warning tracking
        )

    def _evaluate_lesson_relevance(
        self, trades: list[Any]
    ) -> LessonRelevanceMetrics:
        """Evaluate lesson extraction and application quality.

        Checks:
        - Were lessons extracted from trades?
        - Did win rate improve after lessons were applied?
        """
        if not trades:
            return LessonRelevanceMetrics()

        # Count trades with thesis/lesson annotations
        lessons = [t for t in trades if hasattr(t, "thesis") and t.thesis]

        # Split into before/after median trade time for improvement check
        if len(trades) >= 10:
            sorted_trades = sorted(trades, key=lambda t: t.closed_at or "")
            mid = len(sorted_trades) // 2
            first_half_winrate = sum(
                1 for t in sorted_trades[:mid] if t.realized_pnl > 0
            ) / max(1, mid)
            second_half_winrate = sum(
                1 for t in sorted_trades[mid:] if t.realized_pnl > 0
            ) / max(1, len(sorted_trades) - mid)
            improvement = second_half_winrate - first_half_winrate
        else:
            improvement = 0.0

        # Average rule confidence from extracted rules
        avg_confidence = 0.0
        confidences = [
            t.confidence for t in trades
            if hasattr(t, "confidence") and t.confidence is not None
        ]
        if confidences:
            avg_confidence = sum(confidences) / len(confidences)

        return LessonRelevanceMetrics(
            lessons_extracted=len(lessons),
            lessons_applied=len(lessons),  # Simplified — all annotated trades
            improvement_after_lesson=improvement,
            avg_rule_confidence=avg_confidence,
        )

    @staticmethod
    def _simple_correlation(x: list[float], y: list[float]) -> float:
        """Compute Pearson correlation between two lists (no numpy dependency)."""
        n = min(len(x), len(y))
        if n < 2:
            return 0.0

        x, y = x[:n], y[:n]
        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        var_x = sum((xi - mean_x) ** 2 for xi in x)
        var_y = sum((yi - mean_y) ** 2 for yi in y)

        denom = (var_x * var_y) ** 0.5
        if denom == 0:
            return 0.0
        return cov / denom


# ═══════════════════════════════════════════════════════════════════════
# NEMO EVALUATOR INTEGRATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class NemoDimensionScore:
    """Score for a single evaluation dimension."""
    dimension: str = ""
    score: float = 0.0
    weight: float = 1.0
    rationale: str = ""


@dataclass
class NemoEvaluationResult:
    """Result of Nemo Evaluator assessment."""
    overall_score: float = 0.0
    dimension_scores: list[NemoDimensionScore] = field(default_factory=list)
    accepted: bool = True
    rejection_reason: str = ""
    method: str = "nemo_evaluator"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 4),
            "dimensions": [
                {"dimension": d.dimension, "score": round(d.score, 4),
                 "weight": d.weight, "rationale": d.rationale}
                for d in self.dimension_scores
            ],
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "method": self.method,
        }


class NemoTradeEvaluator:
    """Evaluate LLM trading outputs using NVIDIA Nemo Evaluator.

    Provides multi-dimensional evaluation:
    - Factual accuracy: Are claims supported by market data?
    - Risk awareness: Does output consider risk implications?
    - Actionability: Can the output be directly acted upon?
    - Coherence: Is the reasoning logical and consistent?

    Falls back to rule-based evaluation if Nemo unavailable.

    Usage::

        nemo = NemoTradeEvaluator(config)
        result = nemo.evaluate_llm_output(
            output_text="BTC is showing a bullish reversal...",
            context={"symbol": "BTC/USDT", "timeframe": "4h"},
        )
        if not result.accepted:
            print(f"Rejected: {result.rejection_reason}")
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._available = NEMO_EVALUATOR_AVAILABLE
        self._evaluator: Any = None
        self._fallback = self._config.get("fallback", "internal")

        # Load dimension config
        self._dimensions = self._config.get("dimensions", [
            {"name": "factual_accuracy", "weight": 0.25,
             "description": "Are claims supported by market data?"},
            {"name": "risk_awareness", "weight": 0.25,
             "description": "Does output consider risk implications?"},
            {"name": "actionability", "weight": 0.25,
             "description": "Can the output be directly acted upon?"},
            {"name": "coherence", "weight": 0.25,
             "description": "Is the reasoning logical and consistent?"},
        ])

        # Scoring thresholds
        scoring = self._config.get("scoring", {})
        self._min_acceptable = scoring.get("min_acceptable_score", 0.6)
        self._auto_reject = scoring.get("auto_reject_threshold", 0.3)

        # Initialize Nemo if available
        if self._available:
            try:
                self._evaluator = NemoEvaluator()
                logger.info("nemo_evaluator_initialized")
            except Exception as exc:
                logger.warning("nemo_evaluator_init_failed", error=str(exc))
                self._evaluator = None
                self._available = False

        if not self._available:
            logger.warning(
                "nemo_not_available",
                msg=f"Nemo Evaluator not installed. Using {self._fallback} fallback.",
            )

    @property
    def available(self) -> bool:
        return self._available and self._evaluator is not None

    def evaluate_llm_output(
        self,
        output_text: str,
        context: dict[str, Any] | None = None,
    ) -> NemoEvaluationResult:
        """Evaluate a single LLM output on all configured dimensions.

        Args:
            output_text: The LLM-generated text to evaluate.
            context: Trading context (symbol, timeframe, indicators, etc.).

        Returns:
            NemoEvaluationResult with scores and acceptance status.
        """
        if not output_text.strip():
            return NemoEvaluationResult(
                overall_score=0.0,
                accepted=False,
                rejection_reason="Empty output",
                method="empty_check",
            )

        if self.available:
            return self._nemo_evaluate(output_text, context)
        else:
            return self._rule_based_evaluate(output_text, context)

    def _nemo_evaluate(
        self,
        output_text: str,
        context: dict[str, Any] | None,
    ) -> NemoEvaluationResult:
        """Evaluate using Nemo Evaluator."""
        assert self._evaluator is not None

        try:
            # Build evaluation prompt
            context_str = json.dumps(context or {}, indent=2)
            eval_prompt = (
                f"Evaluate this trading analysis output. "
                f"Context: {context_str}\n\n"
                f"Output to evaluate:\n{output_text}\n\n"
                f"Score each dimension 0-1:"
            )

            dimension_scores = []
            total_weighted = 0.0
            total_weight = 0.0

            for dim in self._dimensions:
                name = dim["name"]
                weight = dim.get("weight", 0.25)

                # Nemo evaluates each dimension
                result = self._evaluator.evaluate(
                    input_text=eval_prompt,
                    dimension=name,
                )

                score = float(result.get("score", 0.5))
                rationale = result.get("rationale", "")

                dimension_scores.append(NemoDimensionScore(
                    dimension=name,
                    score=score,
                    weight=weight,
                    rationale=rationale,
                ))

                total_weighted += score * weight
                total_weight += weight

            overall = total_weighted / total_weight if total_weight > 0 else 0.0

            # Determine acceptance
            accepted = overall >= self._min_acceptable
            rejection_reason = ""
            if overall < self._auto_reject:
                accepted = False
                rejection_reason = (
                    f"Score {overall:.2f} below auto-reject threshold "
                    f"{self._auto_reject:.2f}"
                )
            elif not accepted:
                rejection_reason = (
                    f"Score {overall:.2f} below minimum acceptable "
                    f"{self._min_acceptable:.2f}"
                )

            return NemoEvaluationResult(
                overall_score=overall,
                dimension_scores=dimension_scores,
                accepted=accepted,
                rejection_reason=rejection_reason,
                method="nemo_evaluator",
                metadata={"gpu_accelerated": True},
            )

        except Exception as exc:
            logger.error("nemo_evaluation_error", error=str(exc))
            return self._rule_based_evaluate(output_text, context)

    def _rule_based_evaluate(
        self,
        output_text: str,
        context: dict[str, Any] | None,
    ) -> NemoEvaluationResult:
        """Fallback rule-based evaluation when Nemo unavailable."""
        text_lower = output_text.lower()
        dimension_scores = []

        # Factual accuracy: check for data references
        data_keywords = ["price", "volume", "rsi", "macd", "bollinger",
                        "support", "resistance", "pattern", "indicator"]
        data_refs = sum(1 for kw in data_keywords if kw in text_lower)
        factual_score = min(1.0, data_refs / 4.0)
        dimension_scores.append(NemoDimensionScore(
            dimension="factual_accuracy",
            score=factual_score,
            weight=0.25,
            rationale=f"Found {data_refs} data references",
        ))

        # Risk awareness: check for risk-related terms
        risk_keywords = ["risk", "stop loss", "stop-loss", "drawdown",
                        "volatility", "position size", "kelly", "hedge"]
        risk_refs = sum(1 for kw in risk_keywords if kw in text_lower)
        risk_score = min(1.0, risk_refs / 3.0)
        dimension_scores.append(NemoDimensionScore(
            dimension="risk_awareness",
            score=risk_score,
            weight=0.25,
            rationale=f"Found {risk_refs} risk references",
        ))

        # Actionability: check for action-oriented language
        action_keywords = ["buy", "sell", "entry", "exit", "target",
                          "take profit", "signal", "order", "execute"]
        action_refs = sum(1 for kw in action_keywords if kw in text_lower)
        action_score = min(1.0, action_refs / 3.0)
        dimension_scores.append(NemoDimensionScore(
            dimension="actionability",
            score=action_score,
            weight=0.25,
            rationale=f"Found {action_refs} action references",
        ))

        # Coherence: check for reasoning structure
        coherence_keywords = ["because", "therefore", "however",
                             "although", "if", "then", "analysis"]
        coherence_refs = sum(1 for kw in coherence_keywords if kw in text_lower)
        coherence_score = min(1.0, coherence_refs / 3.0)
        dimension_scores.append(NemoDimensionScore(
            dimension="coherence",
            score=coherence_score,
            weight=0.25,
            rationale=f"Found {coherence_refs} reasoning markers",
        ))

        # Weighted overall
        total = sum(d.score * d.weight for d in dimension_scores)
        total_weight = sum(d.weight for d in dimension_scores)
        overall = total / total_weight if total_weight > 0 else 0.0

        accepted = overall >= self._min_acceptable
        rejection_reason = ""
        if overall < self._auto_reject:
            accepted = False
            rejection_reason = f"Score {overall:.2f} below auto-reject threshold"
        elif not accepted:
            rejection_reason = f"Score {overall:.2f} below minimum acceptable"

        return NemoEvaluationResult(
            overall_score=overall,
            dimension_scores=dimension_scores,
            accepted=accepted,
            rejection_reason=rejection_reason,
            method="fallback_rule_based",
            metadata={"gpu_accelerated": False},
        )

    def status(self) -> dict[str, Any]:
        """Return evaluator status."""
        return {
            "available": self.available,
            "method": "nemo_evaluator" if self.available else f"fallback_{self._fallback}",
            "dimensions": len(self._dimensions),
            "min_acceptable_score": self._min_acceptable,
            "auto_reject_threshold": self._auto_reject,
        }
