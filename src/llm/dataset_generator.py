"""TSAR — Fine-Tuning Dataset Generator.

Reads closed trades from TradeMemory and lessons from LessonArchive,
generates instruction-response pairs for fine-tuning the trading LLM.

Output format per example:
  market_context → optimal_action → outcome → lesson

Generates multiple dataset types:
  - trade_decisions: Given market context, what's the optimal action?
  - lesson_applications: Given a situation, which lesson applies and why?
  - post_mortems: Given a trade outcome, what went right/wrong?
  - risk_assessment: Given market conditions, what's the risk profile?
  - strategy_selection: Given regime + conditions, which strategy fits?

Usage::

    from src.llm.dataset_generator import DatasetGenerator

    gen = DatasetGenerator("/path/to/tsar.db")
    dataset = gen.generate_all(max_examples=1000)
    gen.export_jsonl(dataset, "output/training_data.jsonl")
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.knowledge.lesson_archive import LessonArchive
from src.knowledge.trade_memory import TradeMemory
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DatasetType(StrEnum):
    """Types of training examples generated."""

    TRADE_DECISION = "trade_decision"
    LESSON_APPLICATION = "lesson_application"
    POST_MORTEM = "post_mortem"
    RISK_ASSESSMENT = "risk_assessment"
    STRATEGY_SELECTION = "strategy_selection"


@dataclass
class TrainingExample:
    """A single instruction-response pair for fine-tuning."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    dataset_type: str = ""
    instruction: str = ""
    input_context: str = ""
    output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    quality_score: float = 0.0  # 0.0-1.0, auto-assessed
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_alpaca(self) -> dict[str, str]:
        """Convert to Alpaca format for fine-tuning."""
        return {
            "instruction": self.instruction,
            "input": self.input_context,
            "output": self.output,
        }

    def to_chatml(self) -> dict[str, Any]:
        """Convert to ChatML format for fine-tuning."""
        messages = [{"role": "system", "content": self.metadata.get("system_prompt", "")}]
        messages.append({"role": "user", "content": f"{self.instruction}\n\n{self.input_context}"})
        messages.append({"role": "assistant", "content": self.output})
        return {"messages": messages}


class DatasetGenerator:
    """Generate fine-tuning datasets from TradeMemory and LessonArchive.

    Args:
        db_path: Path to the SQLite database.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._trade_memory = TradeMemory(db_path)
        self._lesson_archive = LessonArchive(db_path)
        logger.info("dataset_generator_initialized", db_path=db_path)

    # ── Main generation methods ──────────────────────────────

    def generate_all(
        self,
        max_examples: int = 1000,
        min_quality: float = 0.3,
        dataset_types: list[DatasetType] | None = None,
    ) -> list[TrainingExample]:
        """Generate all dataset types.

        Args:
            max_examples: Maximum total examples to generate.
            min_quality: Minimum quality score to include.
            dataset_types: Specific types to generate (None = all).

        Returns:
            List of TrainingExample objects, sorted by quality.
        """
        if dataset_types is None:
            dataset_types = list(DatasetType)

        all_examples: list[TrainingExample] = []
        per_type_limit = max(1, max_examples // len(dataset_types))

        for dtype in dataset_types:
            try:
                if dtype == DatasetType.TRADE_DECISION:
                    examples = self._generate_trade_decisions(per_type_limit)
                elif dtype == DatasetType.LESSON_APPLICATION:
                    examples = self._generate_lesson_applications(per_type_limit)
                elif dtype == DatasetType.POST_MORTEM:
                    examples = self._generate_post_mortems(per_type_limit)
                elif dtype == DatasetType.RISK_ASSESSMENT:
                    examples = self._generate_risk_assessments(per_type_limit)
                elif dtype == DatasetType.STRATEGY_SELECTION:
                    examples = self._generate_strategy_selections(per_type_limit)
                else:
                    continue

                all_examples.extend(examples)
                logger.info(
                    "generated_examples",
                    dataset_type=dtype.value,
                    count=len(examples),
                )
            except Exception as exc:
                logger.error(
                    "generation_failed",
                    dataset_type=dtype.value,
                    error=str(exc),
                )

        # Filter by quality and sort
        filtered = [e for e in all_examples if e.quality_score >= min_quality]
        filtered.sort(key=lambda e: e.quality_score, reverse=True)

        result = filtered[:max_examples]
        logger.info(
            "dataset_generation_complete",
            total_generated=len(all_examples),
            after_filter=len(filtered),
            returned=len(result),
        )
        return result

    # ── Trade Decision examples ──────────────────────────────

    def _generate_trade_decisions(self, limit: int) -> list[TrainingExample]:
        """Generate: Given market context → what's the optimal action?

        Uses closed trades with clear outcomes (strong win or loss).
        """
        examples: list[TrainingExample] = []
        trades = self._trade_memory.list_trades(status="CLOSED", limit=limit * 2)

        for trade in trades:
            if not trade.thesis or not trade.entry_price:
                continue

            # Build market context
            context = self._build_market_context(trade)

            # Determine optimal action from outcome
            if trade.realized_pnl > 0:
                action = self._describe_winning_action(trade)
                outcome_desc = f"Profitable: +{trade.realized_pnl_pct:.2f}%"
            elif trade.realized_pnl < 0:
                action = self._describe_losing_action(trade)
                outcome_desc = f"Loss: {trade.realized_pnl_pct:.2f}%"
            else:
                continue  # Skip breakeven

            # Get linked lessons
            linked_lessons = self._trade_memory.get_trade_lessons(trade.trade_id)
            lesson_text = self._format_lessons(linked_lessons)

            # Build instruction-response pair
            instruction = (
                f"Analyze the following market conditions for {trade.symbol} and determine "
                f"the optimal trading action. Consider the {trade.regime_at_entry or 'unknown'} "
                f"regime, current indicators, and risk/reward profile."
            )

            output = (
                f"## Analysis\n\n"
                f"**Action:** {action}\n\n"
                f"**Thesis:** {trade.thesis}\n\n"
                f"**Outcome:** {outcome_desc}\n\n"
            )
            if trade.reflection:
                output += f"**Reflection:** {trade.reflection}\n\n"
            if lesson_text:
                output += f"**Lessons Learned:**\n{lesson_text}\n\n"
            if trade.lessons:
                output += f"**Key Takeaway:** {trade.lessons}\n"

            quality = self._score_trade_quality(trade)

            examples.append(
                TrainingExample(
                    dataset_type=DatasetType.TRADE_DECISION.value,
                    instruction=instruction,
                    input_context=context,
                    output=output,
                    quality_score=quality,
                    metadata={
                        "trade_id": trade.trade_id,
                        "symbol": trade.symbol,
                        "strategy_id": trade.strategy_id,
                        "pnl": trade.realized_pnl,
                        "pnl_pct": trade.realized_pnl_pct,
                        "regime": trade.regime_at_entry,
                        "system_prompt": self._get_system_prompt("trade_analyst"),
                    },
                )
            )

            if len(examples) >= limit:
                break

        return examples

    # ── Lesson Application examples ──────────────────────────

    def _generate_lesson_applications(self, limit: int) -> list[TrainingExample]:
        """Generate: Given a trading situation → which lesson applies and why?

        Uses lessons with high violation impact or high application count.
        """
        examples: list[TrainingExample] = []

        # Get most impactful lessons
        violated = self._lesson_archive.get_most_violated(limit=limit)
        critical = self._lesson_archive.get_critical_lessons(limit=limit)
        recent = self._lesson_archive.get_recent_lessons(days=30, limit=limit)

        # Combine and deduplicate
        seen_ids: set[str] = set()
        all_lessons = []
        for lesson in violated + critical + recent:
            lid = lesson.get("lesson_id") or lesson.lesson_id
            if lid not in seen_ids:
                seen_ids.add(lid)
                all_lessons.append(lesson)

        for lesson_data in all_lessons[:limit]:
            # Normalize lesson access (dict from queries vs dataclass)
            if isinstance(lesson_data, dict):
                lid = lesson_data.get("lesson_id", "")
                title = lesson_data.get("title", "")
                description = lesson_data.get("description", "")
                action_item = lesson_data.get("action_item", "")
                lesson_type = lesson_data.get("lesson_type", "INSIGHT")
                severity = lesson_data.get("severity", "moderate")
                category = lesson_data.get("category", "")
                applicable_regimes = lesson_data.get("applicable_regimes", "")
                applicable_symbols = lesson_data.get("applicable_symbols", "")
                violation_impact = lesson_data.get("violation_impact", 0.0)
                times_applied = lesson_data.get("times_applied", 0)
                times_violated = lesson_data.get("times_violated", 0)
                confidence = lesson_data.get("confidence", 0.5)
            else:
                lid = lesson_data.lesson_id
                title = lesson_data.title
                description = lesson_data.description
                action_item = lesson_data.action_item or ""
                lesson_type = lesson_data.lesson_type
                severity = lesson_data.severity
                category = lesson_data.category or ""
                applicable_regimes = lesson_data.applicable_regimes or ""
                applicable_symbols = lesson_data.applicable_symbols or ""
                violation_impact = lesson_data.violation_impact
                times_applied = lesson_data.times_applied
                times_violated = lesson_data.times_violated
                confidence = lesson_data.confidence

            # Build a contextual scenario
            scenario = self._build_lesson_scenario(
                title, description, applicable_regimes, applicable_symbols, category
            )

            instruction = (
                f"You are reviewing a trading situation. A past lesson titled "
                f"'{title}' was discovered ({lesson_type}, severity: {severity}). "
                f"Evaluate whether this lesson applies to the current scenario and "
                f"what action should be taken."
            )

            output = f"## Lesson Analysis\n\n"
            output += f"**Lesson:** {title}\n"
            output += f"**Type:** {lesson_type} | **Severity:** {severity}\n\n"
            output += f"**Description:** {description}\n\n"
            if action_item:
                output += f"**Recommended Action:** {action_item}\n\n"
            output += f"**Application History:**\n"
            output += f"- Applied {times_applied} times successfully\n"
            output += f"- Violated {times_violated} times"
            if violation_impact:
                output += f" (total impact: ${violation_impact:.2f})"
            output += f"\n- Confidence: {confidence:.0%}\n\n"
            if applicable_regimes:
                output += f"**Best in regimes:** {applicable_regimes}\n"
            if applicable_symbols:
                output += f"**Applies to:** {applicable_symbols}\n"

            # Quality: higher for lessons with more real-world data
            quality = min(1.0, 0.3 + (times_applied + times_violated) * 0.05 + confidence * 0.3)

            examples.append(
                TrainingExample(
                    dataset_type=DatasetType.LESSON_APPLICATION.value,
                    instruction=instruction,
                    input_context=scenario,
                    output=output,
                    quality_score=quality,
                    metadata={
                        "lesson_id": lid,
                        "lesson_type": lesson_type,
                        "severity": severity,
                        "system_prompt": self._get_system_prompt("lesson_advisor"),
                    },
                )
            )

        return examples

    # ── Post-Mortem examples ─────────────────────────────────

    def _generate_post_mortems(self, limit: int) -> list[TrainingExample]:
        """Generate: Given a trade outcome → what went right/wrong?

        Uses trades with reflections, journal entries, and linked lessons.
        """
        examples: list[TrainingExample] = []
        trades = self._trade_memory.list_trades(status="CLOSED", limit=limit * 3)

        # Prefer trades with rich post-trade data
        enriched = []
        for trade in trades:
            score = 0.0
            if trade.reflection:
                score += 2.0
            if trade.lessons:
                score += 1.5
            if trade.outcome_grade:
                score += 1.0
            if trade.execution_grade:
                score += 0.5
            if trade.max_drawdown_during:
                score += 0.3
            if trade.max_favorable_excursion:
                score += 0.3
            journal = self._trade_memory.get_journal_entries(trade.trade_id)
            if journal:
                score += 1.5
            linked = self._trade_memory.get_trade_lessons(trade.trade_id)
            if linked:
                score += 1.0
            enriched.append((score, trade, journal))

        enriched.sort(key=lambda x: x[0], reverse=True)

        for score, trade, journal_entries in enriched[:limit]:
            if score < 1.0:
                continue

            context = self._build_trade_outcome_context(trade)

            instruction = (
                f"Perform a detailed post-mortem analysis of this {trade.symbol} trade. "
                f"The trade was {'profitable' if trade.realized_pnl > 0 else 'a loss'} "
                f"({trade.realized_pnl_pct:+.2f}%). Identify what went right, what went wrong, "
                f"and actionable improvements."
            )

            # Build structured post-mortem
            output = "## Post-Mortem Analysis\n\n"
            output += f"**Trade:** {trade.symbol} {trade.side.upper()} | "
            output += f"**Strategy:** {trade.strategy_id}\n"
            output += f"**Result:** {trade.realized_pnl_pct:+.2f}% (${trade.realized_pnl:+.2f})\n"
            output += f"**Holding Period:** {trade.holding_period_hours or 'N/A'}h\n\n"

            if trade.outcome_grade:
                output += f"**Outcome Grade:** {trade.outcome_grade}\n"
            if trade.execution_grade:
                output += f"**Execution Grade:** {trade.execution_grade}\n\n"

            if trade.reflection:
                output += f"### Reflection\n{trade.reflection}\n\n"

            if trade.lessons:
                output += f"### Lessons\n{trade.lessons}\n\n"

            if trade.max_drawdown_during or trade.max_favorable_excursion:
                output += "### Excursion Data\n"
                if trade.max_drawdown_during:
                    output += f"- Max Drawdown: {trade.max_drawdown_during:.2f}%\n"
                if trade.max_favorable_excursion:
                    output += f"- Max Favorable Excursion: {trade.max_favorable_excursion:.2f}%\n"
                if trade.max_adverse_excursion:
                    output += f"- Max Adverse Excursion: {trade.max_adverse_excursion:.2f}%\n"
                output += "\n"

            if journal_entries:
                output += "### Journal Notes\n"
                for entry in journal_entries[:3]:
                    output += f"- [{entry.entry_type}] {entry.content}\n"
                    if entry.cognitive_biases:
                        output += f"  Biases detected: {entry.cognitive_biases}\n"
                output += "\n"

            linked_lessons = self._trade_memory.get_trade_lessons(trade.trade_id)
            if linked_lessons:
                output += "### Related Lessons\n"
                for lesson in linked_lessons[:5]:
                    output += f"- {lesson.get('title', 'N/A')}: {lesson.get('description', '')[:100]}\n"

            # Quality based on richness of post-trade data
            quality = min(1.0, score / 6.0)

            examples.append(
                TrainingExample(
                    dataset_type=DatasetType.POST_MORTEM.value,
                    instruction=instruction,
                    input_context=context,
                    output=output,
                    quality_score=quality,
                    metadata={
                        "trade_id": trade.trade_id,
                        "symbol": trade.symbol,
                        "pnl": trade.realized_pnl,
                        "has_journal": len(journal_entries) > 0,
                        "system_prompt": self._get_system_prompt("post_mortem_analyst"),
                    },
                )
            )

        return examples

    # ── Risk Assessment examples ─────────────────────────────

    def _generate_risk_assessments(self, limit: int) -> list[TrainingExample]:
        """Generate: Given market conditions → what's the risk profile?

        Uses regime-specific performance data and high-drawdown trades.
        """
        examples: list[TrainingExample] = []

        # Get performance by regime
        regime_perf = self._trade_memory.get_performance_by_regime()
        trade_stats = self._trade_memory.get_trade_stats()

        # Generate per-regime assessments
        for regime_data in regime_perf[:limit]:
            regime = regime_data.get("regime_at_entry", "unknown")
            trade_count = regime_data.get("trade_count", 0)
            total_pnl = regime_data.get("total_pnl", 0.0)
            avg_pnl = regime_data.get("avg_pnl_pct", 0.0)
            win_rate = regime_data.get("win_rate", 0.0)

            if trade_count < 3:
                continue

            # Find trades in this regime for context
            regime_trades = self._trade_memory.list_trades(limit=50)
            regime_trades = [t for t in regime_trades if t.regime_at_entry == regime]

            # Build risk context
            context = f"## Market Regime: {regime.upper()}\n\n"
            context += f"**Historical Performance ({trade_count} trades):**\n"
            context += f"- Win Rate: {win_rate:.1%}\n"
            context += f"- Average P&L: {avg_pnl:+.2f}%\n"
            context += f"- Total P&L: ${total_pnl:+.2f}\n\n"

            if regime_trades:
                # Add sample indicators from recent trades
                t = regime_trades[0]
                context += "**Current Market Snapshot:**\n"
                if t.vix_level:
                    context += f"- VIX: {t.vix_level}\n"
                if t.volatility_regime:
                    context += f"- Volatility Regime: {t.volatility_regime}\n"
                if t.market_breadth:
                    context += f"- Market Breadth: {t.market_breadth}\n"
                if t.liquidity_score:
                    context += f"- Liquidity Score: {t.liquidity_score}\n"

            instruction = (
                f"Assess the risk profile for trading in the '{regime}' market regime. "
                f"Based on historical performance and current conditions, recommend "
                f"position sizing, risk parameters, and any regime-specific adjustments."
            )

            # Get lessons for this regime
            regime_lessons = self._lesson_archive.get_lessons_for_regime(regime)

            output = "## Risk Assessment\n\n"
            output += f"**Regime:** {regime}\n"
            output += f"**Risk Level:** "
            if win_rate >= 0.6 and avg_pnl > 0:
                output += "MODERATE — Historical edge exists\n"
            elif win_rate >= 0.45:
                output += "ELEVATED — Mixed results, proceed with caution\n"
            else:
                output += "HIGH — Poor historical performance, reduce exposure\n"

            output += f"\n### Sizing Recommendation\n"
            if win_rate >= 0.6:
                output += f"- Standard position size (100% of base allocation)\n"
                output += f"- Risk per trade: 2% of capital\n"
            elif win_rate >= 0.45:
                output += f"- Reduced position size (70% of base allocation)\n"
                output += f"- Risk per trade: 1.5% of capital\n"
            else:
                output += f"- Minimal position size (40% of base allocation)\n"
                output += f"- Risk per trade: 1% of capital\n"

            if regime_lessons:
                output += f"\n### Regime-Specific Lessons ({len(regime_lessons)} total)\n"
                for lesson in regime_lessons[:3]:
                    output += f"- **{lesson.title}** ({lesson.severity}): {lesson.description[:120]}\n"

            quality = min(1.0, 0.4 + trade_count * 0.02 + win_rate * 0.3)

            examples.append(
                TrainingExample(
                    dataset_type=DatasetType.RISK_ASSESSMENT.value,
                    instruction=instruction,
                    input_context=context,
                    output=output,
                    quality_score=quality,
                    metadata={
                        "regime": regime,
                        "trade_count": trade_count,
                        "win_rate": win_rate,
                        "system_prompt": self._get_system_prompt("risk_analyst"),
                    },
                )
            )

        # Add global risk assessment
        if trade_stats.get("trade_count", 0) >= 10:
            context = "## Global Portfolio Statistics\n\n"
            context += f"- Total Trades: {trade_stats['trade_count']}\n"
            context += f"- Win Rate: {trade_stats['win_rate']:.1%}\n"
            context += f"- Total P&L: ${trade_stats['total_pnl']:+.2f}\n"
            context += f"- Avg Win: ${trade_stats['avg_win']:+.2f}\n"
            context += f"- Avg Loss: ${trade_stats['avg_loss']:+.2f}\n"
            context += f"- Profit Factor: {trade_stats['profit_factor']:.2f}\n"
            context += f"- Max Drawdown: ${trade_stats['max_drawdown']:.2f}\n"

            instruction = (
                "Based on the global portfolio statistics, provide a comprehensive "
                "risk assessment. Evaluate the overall health of the trading system, "
                "identify areas of concern, and recommend adjustments."
            )

            pf = trade_stats["profit_factor"]
            wr = trade_stats["win_rate"]
            output = "## Global Risk Assessment\n\n"
            if pf >= 2.0 and wr >= 0.55:
                output += "**Status: HEALTHY** — System shows strong edge\n"
                output += "Recommendation: Maintain current parameters, consider gradual scaling.\n"
            elif pf >= 1.5 and wr >= 0.45:
                output += "**Status: STABLE** — Positive expectancy but room for improvement\n"
                output += "Recommendation: Review losing trades for patterns, tighten exits.\n"
            elif pf >= 1.0:
                output += "**Status: MARGINAL** — Barely profitable, high risk of degradation\n"
                output += "Recommendation: Reduce position sizes, review strategy allocation.\n"
            else:
                output += "**Status: NEGATIVE EXPECTANCY** — System is losing money\n"
                output += "Recommendation: Halt trading, review all strategies, consider paper mode.\n"

            examples.append(
                TrainingExample(
                    dataset_type=DatasetType.RISK_ASSESSMENT.value,
                    instruction=instruction,
                    input_context=context,
                    output=output,
                    quality_score=0.8,
                    metadata={
                        "scope": "global",
                        "trade_count": trade_stats["trade_count"],
                        "system_prompt": self._get_system_prompt("risk_analyst"),
                    },
                )
            )

        return examples

    # ── Strategy Selection examples ──────────────────────────

    def _generate_strategy_selections(self, limit: int) -> list[TrainingExample]:
        """Generate: Given regime + conditions → which strategy fits?

        Uses strategy performance summaries and regime data.
        """
        examples: list[TrainingExample] = []

        strategy_summary = self._trade_memory.get_strategy_summary()
        regime_perf = self._trade_memory.get_performance_by_regime()

        if not strategy_summary:
            return examples

        # Cross-strategy × regime analysis
        for regime_data in regime_perf[:5]:
            regime = regime_data.get("regime_at_entry", "unknown")

            # Build context with all strategies' performance in this regime
            context = f"## Market Regime: {regime.upper()}\n\n"
            context += "### Strategy Performance in this Regime\n\n"

            strategy_scores: list[tuple[str, float, dict]] = []
            for strat in strategy_summary:
                sid = strat["strategy_id"]
                # Get trades for this strategy in this regime
                trades = self._trade_memory.list_trades(strategy_id=sid, limit=100)
                regime_trades = [t for t in trades if t.regime_at_entry == regime]
                if len(regime_trades) < 2:
                    continue

                regime_pnl = sum(t.realized_pnl for t in regime_trades)
                regime_wins = sum(1 for t in regime_trades if t.realized_pnl > 0)
                regime_wr = regime_wins / len(regime_trades) if regime_trades else 0.0

                context += f"**{sid}:**\n"
                context += f"  - Trades: {len(regime_trades)}, Win Rate: {regime_wr:.1%}, "
                context += f"P&L: ${regime_pnl:+.2f}\n\n"

                strategy_scores.append((sid, regime_pnl, strat))

            if not strategy_scores:
                continue

            strategy_scores.sort(key=lambda x: x[1], reverse=True)
            best = strategy_scores[0]

            instruction = (
                f"Given the '{regime}' market regime, recommend the optimal trading "
                f"strategy. Consider each strategy's historical performance in this "
                f"regime, risk characteristics, and current market conditions."
            )

            output = "## Strategy Recommendation\n\n"
            output += f"**Recommended Strategy:** {best[0]}\n"
            output += f"**Reason:** Best historical performance in {regime} regime "
            output += f"(${best[1]:+.2f} total P&L)\n\n"
            output += "### Ranking\n\n"
            for i, (sid, pnl, _) in enumerate(strategy_scores, 1):
                emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
                output += f"{emoji} {i}. {sid} — ${pnl:+.2f}\n"

            output += f"\n### Allocation Suggestion\n"
            if len(strategy_scores) >= 2:
                top_pnl = strategy_scores[0][1]
                total_positive = sum(max(0, s[1]) for s in strategy_scores)
                if total_positive > 0:
                    top_pct = max(0, top_pnl) / total_positive * 100
                    output += f"- {best[0]}: {min(top_pct, 70):.0f}% of allocation\n"
                    for sid, pnl, _ in strategy_scores[1:]:
                        if pnl > 0 and total_positive > 0:
                            pct = max(0, pnl) / total_positive * 100
                            output += f"- {sid}: {min(pct, 30):.0f}% of allocation\n"
                else:
                    output += "- All strategies negative — consider reducing exposure\n"

            quality = min(1.0, 0.3 + len(strategy_scores) * 0.15 + (1 if best[1] > 0 else 0) * 0.3)

            examples.append(
                TrainingExample(
                    dataset_type=DatasetType.STRATEGY_SELECTION.value,
                    instruction=instruction,
                    input_context=context,
                    output=output,
                    quality_score=quality,
                    metadata={
                        "regime": regime,
                        "recommended_strategy": best[0],
                        "strategy_count": len(strategy_scores),
                        "system_prompt": self._get_system_prompt("strategy_advisor"),
                    },
                )
            )

        return examples

    # ── Context builders ─────────────────────────────────────

    def _build_market_context(self, trade: Any) -> str:
        """Build a rich market context string from trade data."""
        ctx = f"## Market Context: {trade.symbol}\n\n"
        ctx += f"**Asset Class:** {trade.asset_class}\n"
        ctx += f"**Exchange:** {trade.exchange or 'N/A'}\n"
        ctx += f"**Strategy:** {trade.strategy_id}\n\n"

        ctx += "### Technical Indicators\n"
        if trade.entry_price:
            ctx += f"- Entry Price: {trade.entry_price}\n"
        if trade.exit_price:
            ctx += f"- Exit Price: {trade.exit_price}\n"
        if trade.stop_price:
            ctx += f"- Stop Loss: {trade.stop_price}\n"
        if trade.limit_price:
            ctx += f"- Take Profit: {trade.limit_price}\n"
        if trade.risk_reward_ratio:
            ctx += f"- Risk/Reward Ratio: {trade.risk_reward_ratio:.2f}\n"
        if trade.confidence:
            ctx += f"- Confidence: {trade.confidence:.0%}\n"

        ctx += "\n### Market Conditions\n"
        if trade.regime_at_entry:
            ctx += f"- Regime: {trade.regime_at_entry}\n"
        if trade.vix_level:
            ctx += f"- VIX: {trade.vix_level}\n"
        if trade.volatility_regime:
            ctx += f"- Volatility: {trade.volatility_regime}\n"
        if trade.market_breadth:
            ctx += f"- Market Breadth: {trade.market_breadth}\n"
        if trade.sector_momentum:
            ctx += f"- Sector Momentum: {trade.sector_momentum}\n"
        if trade.liquidity_score:
            ctx += f"- Liquidity Score: {trade.liquidity_score}\n"

        ctx += "\n### Signal Details\n"
        ctx += f"- Signal Type: {trade.signal_type}\n"
        if trade.signal_score:
            ctx += f"- Signal Score: {trade.signal_score:.2f}\n"
        if trade.signal_source:
            ctx += f"- Signal Source: {trade.signal_source}\n"
        if trade.expected_return:
            ctx += f"- Expected Return: {trade.expected_return:.2f}%\n"
        if trade.expected_risk:
            ctx += f"- Expected Risk: {trade.expected_risk:.2f}%\n"

        if trade.key_levels:
            ctx += f"\n### Key Levels\n{trade.key_levels}\n"

        return ctx

    def _build_trade_outcome_context(self, trade: Any) -> str:
        """Build context focused on trade outcome for post-mortems."""
        ctx = self._build_market_context(trade)
        ctx += "\n### Outcome Metrics\n"
        ctx += f"- Realized P&L: ${trade.realized_pnl:+.2f} ({trade.realized_pnl_pct:+.2f}%)\n"
        ctx += f"- Status: {trade.status}\n"
        if trade.holding_period_hours:
            ctx += f"- Holding Period: {trade.holding_period_hours:.1f}h\n"
        if trade.slippage_bps:
            ctx += f"- Slippage: {trade.slippage_bps:.1f} bps\n"
        if trade.commission:
            ctx += f"- Commission: ${trade.commission:.4f}\n"
        if trade.latency_ms:
            ctx += f"- Execution Latency: {trade.latency_ms}ms\n"
        return ctx

    def _build_lesson_scenario(
        self,
        title: str,
        description: str,
        regimes: str,
        symbols: str,
        category: str,
    ) -> str:
        """Build a scenario context for lesson application examples."""
        scenario = "## Trading Scenario\n\n"
        scenario += f"A situation has arisen that may be related to a known trading lesson.\n\n"
        scenario += f"**Relevant Context:**\n"
        if category:
            scenario += f"- Category: {category}\n"
        if regimes:
            scenario += f"- Applicable Regimes: {regimes}\n"
        if symbols:
            scenario += f"- Applicable Symbols: {symbols}\n"
        scenario += f"\n**Situation Description:** {description}\n"
        return scenario

    # ── Helper methods ───────────────────────────────────────

    def _describe_winning_action(self, trade: Any) -> str:
        """Describe the action taken on a winning trade."""
        parts = [f"{trade.side.upper()} {trade.symbol}"]
        if trade.entry_price:
            parts.append(f"at {trade.entry_price}")
        if trade.exit_price:
            parts.append(f"exit at {trade.exit_price}")
        if trade.stop_price:
            parts.append(f"SL: {trade.stop_price}")
        return " ".join(parts)

    def _describe_losing_action(self, trade: Any) -> str:
        """Describe the action taken on a losing trade."""
        parts = [f"{trade.side.upper()} {trade.symbol}"]
        if trade.entry_price:
            parts.append(f"at {trade.entry_price}")
        if trade.exit_price:
            parts.append(f"stopped at {trade.exit_price}")
        return " ".join(parts)

    def _format_lessons(self, lessons: list[dict[str, Any]]) -> str:
        """Format linked lessons into a readable string."""
        if not lessons:
            return ""
        lines = []
        for lesson in lessons[:5]:
            title = lesson.get("title", "N/A")
            desc = lesson.get("description", "")[:150]
            lines.append(f"- **{title}**: {desc}")
        return "\n".join(lines)

    def _score_trade_quality(self, trade: Any) -> float:
        """Score the quality of a trade for training data (0.0-1.0)."""
        score = 0.0
        # Rich data = higher quality
        if trade.thesis:
            score += 0.15
        if trade.reflection:
            score += 0.20
        if trade.lessons:
            score += 0.15
        if trade.outcome_grade:
            score += 0.10
        if trade.execution_grade:
            score += 0.05
        if trade.regime_at_entry:
            score += 0.05
        if trade.vix_level:
            score += 0.05
        if trade.key_levels:
            score += 0.05
        if trade.risk_reward_ratio:
            score += 0.05
        # Clear outcomes are more useful
        if abs(trade.realized_pnl_pct) > 1.0:
            score += 0.10
        if trade.max_drawdown_during:
            score += 0.05
        return min(1.0, score)

    # ── Export methods ───────────────────────────────────────

    def export_jsonl(
        self,
        examples: list[TrainingExample],
        output_path: str,
        format: str = "alpaca",
    ) -> Path:
        """Export dataset to JSONL file.

        Args:
            examples: List of training examples.
            output_path: Path to output file.
            format: Output format — "alpaca", "chatml", or "raw".

        Returns:
            Path to the exported file.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            for example in examples:
                if format == "alpaca":
                    record = example.to_alpaca()
                elif format == "chatml":
                    record = example.to_chatml()
                else:
                    record = example.to_dict()
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        logger.info(
            "dataset_exported",
            path=str(path),
            count=len(examples),
            format=format,
        )
        return path

    def export_splits(
        self,
        examples: list[TrainingExample],
        output_dir: str,
        train_pct: float = 0.8,
        val_pct: float = 0.1,
        test_pct: float = 0.1,
        format: str = "alpaca",
    ) -> dict[str, Path]:
        """Export dataset with train/validation/test splits.

        Args:
            examples: List of training examples.
            output_dir: Directory for output files.
            train_pct: Percentage for training set.
            val_pct: Percentage for validation set.
            test_pct: Percentage for test set.
            format: Output format.

        Returns:
            Dict mapping split name to file path.
        """
        import random

        # Shuffle and split
        shuffled = list(examples)
        random.shuffle(shuffled)

        n = len(shuffled)
        train_end = int(n * train_pct)
        val_end = train_end + int(n * val_pct)

        splits = {
            "train": shuffled[:train_end],
            "validation": shuffled[train_end:val_end],
            "test": shuffled[val_end:],
        }

        paths: dict[str, Path] = {}
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for split_name, split_data in splits.items():
            if split_data:
                path = out_dir / f"{split_name}.jsonl"
                self.export_jsonl(split_data, str(path), format=format)
                paths[split_name] = path

        logger.info(
            "dataset_splits_exported",
            output_dir=output_dir,
            train=len(splits["train"]),
            validation=len(splits["validation"]),
            test=len(splits["test"]),
        )
        return paths

    def get_dataset_stats(self, examples: list[TrainingExample]) -> dict[str, Any]:
        """Get statistics about the generated dataset.

        Args:
            examples: List of training examples.

        Returns:
            Dict with dataset statistics.
        """
        type_counts: dict[str, int] = {}
        quality_scores: list[float] = []

        for ex in examples:
            type_counts[ex.dataset_type] = type_counts.get(ex.dataset_type, 0) + 1
            quality_scores.append(ex.quality_score)

        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

        return {
            "total_examples": len(examples),
            "by_type": type_counts,
            "avg_quality_score": round(avg_quality, 3),
            "min_quality_score": round(min(quality_scores), 3) if quality_scores else 0.0,
            "max_quality_score": round(max(quality_scores), 3) if quality_scores else 0.0,
        }

    # ── System prompts ───────────────────────────────────────

    @staticmethod
    def _get_system_prompt(role: str) -> str:
        """Get system prompt for a given role."""
        prompts = {
            "trade_analyst": (
                "You are TSAR's trade analyst — an expert in crypto and forex trading. "
                "Analyze market conditions with precision, considering technical indicators, "
                "market regime, macro factors, and risk/reward profiles. "
                "Provide clear, actionable trading recommendations backed by data."
            ),
            "lesson_advisor": (
                "You are TSAR's lesson advisor — a trading coach that learns from past mistakes. "
                "When presented with a trading situation, match it to relevant historical lessons "
                "and explain how past experience should guide current decisions. "
                "Be specific about what to do and what to avoid."
            ),
            "post_mortem_analyst": (
                "You are TSAR's post-mortem analyst — a forensic expert on trade outcomes. "
                "Dissect every trade to identify what went right, what went wrong, and why. "
                "Focus on execution quality, thesis validity, risk management adherence, "
                "and cognitive biases. Provide actionable improvements."
            ),
            "risk_analyst": (
                "You are TSAR's risk analyst — a quantitative risk management expert. "
                "Assess market conditions, regime characteristics, and portfolio statistics "
                "to provide precise risk recommendations. Always quantify your advice "
                "with specific position sizes, stop levels, and exposure limits."
            ),
            "strategy_advisor": (
                "You are TSAR's strategy advisor — an expert in algorithmic trading strategies. "
                "Evaluate market regimes and recommend optimal strategy allocation. "
                "Consider each strategy's strengths, weaknesses, and historical performance "
                "in similar conditions. Quantify allocations and explain your reasoning."
            ),
        }
        return prompts.get(role, prompts["trade_analyst"])
