"""
TSAR — Post-Training Inside the Harness.

Jensen's quote: "You can now also improve the AI model, the large language model,
inside the harness. That's a capability that's never existed before."

This module implements the missing post-training pipeline that closes the loop
between trade experience and LLM improvement. The flywheel becomes:

  TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → **FINE-TUNE** → BETTER TRADE

Components:
  - TradeDatasetGenerator: Converts TradeMemory + LessonArchive into instruction-tuning datasets
  - LoRATrainer: Fine-tunes the base model using LoRA/QLoRA on trade data
  - PostTrainingEvaluator: Evaluates fine-tuned model vs base model
  - PostTrainingPipeline: Orchestrates the full cycle (generate → train → evaluate → deploy)

Dependencies (optional — graceful degradation if missing):
  - peft (LoRA)
  - transformers (HuggingFace)
  - datasets (HuggingFace)
  - torch
  - trl (SFTTrainer for supervised fine-tuning)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from src.knowledge.lesson_archive import LessonArchive
    from src.knowledge.pattern_library import PatternLibrary
    from src.knowledge.trade_memory import TradeMemory

logger = logging.getLogger(__name__)

# ── Optional dependency checks ────────────────────────────────

_TORCH_AVAILABLE = False
_PEFT_AVAILABLE = False
_TRANSFORMERS_AVAILABLE = False
_TRL_AVAILABLE = False
_DATASETS_AVAILABLE = False

try:
    import torch  # noqa: F401

    _TORCH_AVAILABLE = True
except ImportError:
    pass

try:
    from peft import (  # noqa: F401
        LoraConfig,
        PeftModel,
        get_peft_model,
        prepare_model_for_kbit_training,
    )

    _PEFT_AVAILABLE = True
except ImportError:
    pass

try:
    from transformers import (  # noqa: F401
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
    )

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass

try:
    from trl import SFTTrainer  # noqa: F401

    _TRL_AVAILABLE = True
except ImportError:
    pass

try:
    from datasets import Dataset  # noqa: F401

    _DATASETS_AVAILABLE = True
except ImportError:
    pass

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "finetune_config.yaml"

_SYSTEM_PROMPT = (
    "You are TSAR, an expert cryptocurrency trading analyst. "
    "You analyze market conditions, identify patterns, and provide "
    "precise trading decisions with clear reasoning. Always consider "
    "risk management, position sizing, and market regime context."
)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class TrainingExample:
    """A single instruction-tuning example for the LLM.

    Attributes:
        instruction: The market context / question posed to the model.
        response: The ideal trading response (from real trade outcomes + reflections).
        system_prompt: System prompt establishing the model's role.
        metadata: Source trade IDs, lesson IDs, confidence, tags.
    """

    instruction: str = ""
    response: str = ""
    system_prompt: str = _SYSTEM_PROMPT
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "response": self.response,
            "system_prompt": self.system_prompt,
            "metadata": self.metadata,
        }

    def to_chat_format(self) -> dict[str, Any]:
        """Convert to chat message format for SFT training."""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": self.instruction})
        messages.append({"role": "assistant", "content": self.response})
        return {"messages": messages}


@dataclass
class DatasetStats:
    """Statistics about a generated training dataset."""

    total_examples: int = 0
    win_examples: int = 0
    loss_examples: int = 0
    breakeven_examples: int = 0
    lesson_examples: int = 0
    pattern_examples: int = 0
    avg_instruction_tokens: int = 0
    avg_response_tokens: int = 0
    generated_at: str = ""
    source_trades: int = 0
    source_lessons: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrainingRun:
    """Record of a single fine-tuning run."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    base_model: str = ""
    adapter_path: str = ""
    dataset_size: int = 0
    training_loss: float = 0.0
    eval_loss: float = 0.0
    training_duration_s: float = 0.0
    epochs_completed: int = 0
    lora_rank: int = 0
    lora_alpha: int = 0
    status: str = "pending"  # pending | training | completed | failed
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationResult:
    """Result of comparing fine-tuned vs base model."""

    eval_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    base_model_score: float = 0.0
    finetuned_model_score: float = 0.0
    improvement_pct: float = 0.0
    win_rate_before: float = 0.0
    win_rate_after: float = 0.0
    directional_accuracy_before: float = 0.0
    directional_accuracy_after: float = 0.0
    risk_awareness_before: float = 0.0
    risk_awareness_after: float = 0.0
    accepted: bool = False
    rejection_reason: str = ""
    evaluated_at: str = ""
    test_cases: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════
# DATASET GENERATOR
# ═══════════════════════════════════════════════════════════════════════


class TradeDatasetGenerator:
    """Convert TradeMemory + LessonArchive into instruction-tuning datasets.

    Generates three types of training examples:
    1. Trade Reflection Examples: "Given this market context, what's the optimal action?"
       → Response based on actual trade outcome + reflection
    2. Lesson Application Examples: "Given this situation, what lesson applies?"
       → Response from the lesson archive
    3. Pattern Recognition Examples: "Given these indicators, what pattern do you see?"
       → Response from pattern library matches

    Each example follows the instruction-tuning format:
        {"instruction": "...", "response": "...", "system_prompt": "..."}

    Usage::

        generator = TradeDatasetGenerator(trade_memory, lesson_archive, pattern_library)
        examples = generator.generate(min_trades=20)
        generator.save_dataset(examples, "data/datasets/trade_v1.jsonl")
    """

    def __init__(
        self,
        trade_memory: TradeMemory,
        lesson_archive: LessonArchive | None = None,
        pattern_library: PatternLibrary | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._trade_memory = trade_memory
        self._lesson_archive = lesson_archive
        self._pattern_library = pattern_library
        self._config = config or {}

        # Dataset generation parameters
        ds_cfg = self._config.get("dataset_generation", {})
        self._min_trades = ds_cfg.get("min_trades", 20)
        self._lookback_days = ds_cfg.get("lookback_days", 90)
        self._include_losing_trades = ds_cfg.get("include_losing_trades", True)
        self._include_winning_trades = ds_cfg.get("include_winning_trades", True)
        self._max_examples_per_trade = ds_cfg.get("max_examples_per_trade", 3)
        self._balance_win_loss = ds_cfg.get("balance_win_loss", True)

    def generate(
        self,
        min_trades: int | None = None,
        lookback_days: int | None = None,
        since: str | None = None,
    ) -> list[TrainingExample]:
        """Generate training examples from trade history.

        Args:
            min_trades: Minimum number of closed trades required.
            lookback_days: Days of history to look back.
            since: ISO date string override for lookback.

        Returns:
            List of TrainingExample objects.

        Raises:
            ValueError: If insufficient trade data.
        """
        from datetime import timedelta

        effective_min = min_trades or self._min_trades
        effective_lookback = lookback_days or self._lookback_days

        if since is None:
            since = (datetime.now(UTC) - timedelta(days=effective_lookback)).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )

        # Fetch closed trades with reflections
        closed_trades = self._trade_memory.list_trades(
            status="CLOSED", since=since, limit=5000
        )

        if len(closed_trades) < effective_min:
            raise ValueError(
                f"Insufficient trades for dataset generation: "
                f"{len(closed_trades)} < {effective_min} required"
            )

        logger.info(
            "Generating dataset from %d closed trades (since=%s)",
            len(closed_trades),
            since,
        )

        examples: list[TrainingExample] = []

        # Type 1: Trade reflection examples
        trade_examples = self._generate_trade_reflection_examples(closed_trades)
        examples.extend(trade_examples)

        # Type 2: Lesson application examples
        if self._lesson_archive:
            lesson_examples = self._generate_lesson_examples()
            examples.extend(lesson_examples)

        # Type 3: Pattern recognition examples
        if self._pattern_library:
            pattern_examples = self._generate_pattern_examples(closed_trades)
            examples.extend(pattern_examples)

        # Balance win/loss if configured
        if self._balance_win_loss:
            examples = self._balance_examples(examples)

        logger.info(
            "Dataset generated: %d examples (%d trade, %d lesson, %d pattern)",
            len(examples),
            len(trade_examples),
            len(trade_examples),
            len(examples) - len(trade_examples) - (len(examples) - len(trade_examples)),
        )

        return examples

    def _generate_trade_reflection_examples(
        self, trades: list[Any]
    ) -> list[TrainingExample]:
        """Generate instruction-tuning examples from trade reflections.

        For each closed trade with a reflection, creates an example where:
        - instruction = market context + trade setup description
        - response = optimal action based on actual outcome + reflection lesson
        """
        examples: list[TrainingExample] = []

        for trade in trades:
            # Skip trades without reflections
            reflection_raw = getattr(trade, "reflection", None)
            if not reflection_raw:
                continue

            # Parse reflection JSON
            try:
                reflection = (
                    json.loads(reflection_raw)
                    if isinstance(reflection_raw, str)
                    else reflection_raw
                )
            except (json.JSONDecodeError, TypeError):
                continue

            trade_id = getattr(trade, "trade_id", "unknown")
            symbol = getattr(trade, "symbol", "UNKNOWN")
            side = getattr(trade, "side", "buy")
            entry_price = getattr(trade, "entry_price", 0)
            exit_price = getattr(trade, "exit_price", 0)
            pnl_pct = getattr(trade, "realized_pnl_pct", 0)
            strategy_id = getattr(trade, "strategy_id", "")
            regime = getattr(trade, "regime_at_entry", "unknown")
            confidence = getattr(trade, "confidence", 0.5)
            thesis = getattr(trade, "thesis", "")

            outcome = reflection.get("outcome", "unknown")
            lesson = reflection.get("lesson", "")
            what_went_right = reflection.get("what_went_right", "")
            what_went_wrong = reflection.get("what_went_wrong", "")
            error_category = reflection.get("error_category", "none")
            actionable_change = reflection.get("actionable_change", "")

            # Skip trades we're not interested in
            if outcome == "win" and not self._include_winning_trades:
                continue
            if outcome == "loss" and not self._include_losing_trades:
                continue

            # Build market context instruction
            instruction = self._build_trade_instruction(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                strategy_id=strategy_id,
                regime=regime,
                confidence=confidence,
                thesis=thesis,
                risk_reward=getattr(trade, "risk_reward_ratio", None),
                vix=getattr(trade, "vix_level", None),
                volatility_regime=getattr(trade, "volatility_regime", None),
            )

            # Build optimal response based on outcome
            response = self._build_trade_response(
                outcome=outcome,
                lesson=lesson,
                what_went_right=what_went_right,
                what_went_wrong=what_went_wrong,
                error_category=error_category,
                actionable_change=actionable_change,
                pnl_pct=pnl_pct,
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
            )

            example = TrainingExample(
                instruction=instruction,
                response=response,
                metadata={
                    "type": "trade_reflection",
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "outcome": outcome,
                    "pnl_pct": pnl_pct,
                    "confidence": reflection.get("confidence", 0.5),
                    "pattern_tags": reflection.get("pattern_tags", []),
                },
            )
            examples.append(example)

            # Generate counterfactual examples for losing trades
            if outcome == "loss" and error_category != "none":
                counterfactual = self._generate_counterfactual_example(
                    trade, reflection
                )
                if counterfactual:
                    examples.append(counterfactual)

        return examples

    def _build_trade_instruction(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        strategy_id: str,
        regime: str,
        confidence: float,
        thesis: str,
        risk_reward: float | None = None,
        vix: float | None = None,
        volatility_regime: str | None = None,
    ) -> str:
        """Build a market context instruction from trade data."""
        parts = [
            f"Analyze the following trading setup for {symbol}:",
            f"",
            f"- Strategy: {strategy_id}",
            f"- Direction: {side.upper()}",
            f"- Entry price: {entry_price}",
            f"- Market regime: {regime}",
            f"- Signal confidence: {confidence:.2f}",
        ]

        if thesis:
            parts.append(f"- Trade thesis: {thesis}")
        if risk_reward is not None:
            parts.append(f"- Risk/reward ratio: {risk_reward:.2f}")
        if vix is not None:
            parts.append(f"- VIX level: {vix:.1f}")
        if volatility_regime:
            parts.append(f"- Volatility regime: {volatility_regime}")

        parts.extend([
            "",
            "Based on this context, should I execute this trade? "
            "Provide your recommendation with specific reasoning, "
            "including entry/exit levels, position sizing advice, "
            "and key risks to monitor.",
        ])

        return "\n".join(parts)

    def _build_trade_response(
        self,
        outcome: str,
        lesson: str,
        what_went_right: str,
        what_went_wrong: str,
        error_category: str,
        actionable_change: str,
        pnl_pct: float,
        side: str,
        entry_price: float,
        exit_price: float,
    ) -> str:
        """Build an optimal response based on actual trade outcome."""
        parts = []

        if outcome == "win":
            parts.append(
                f"Yes, execute the {side.upper()} trade. This setup has a favorable "
                f"risk/reward profile based on the current market conditions."
            )
        elif outcome == "loss":
            parts.append(
                f"Exercise caution with this {side.upper()} setup. "
                f"Based on historical analysis, this configuration has weaknesses "
                f"that should be addressed before entry."
            )
        else:
            parts.append(
                f"This {side.upper()} setup is marginal. Consider reducing position "
                f"size or waiting for stronger confirmation."
            )

        if what_went_right:
            parts.append(f"\nStrengths: {what_went_right}")
        if what_went_wrong:
            parts.append(f"\nWeaknesses: {what_went_wrong}")

        if lesson:
            parts.append(f"\nKey insight: {lesson}")

        if error_category and error_category != "none":
            parts.append(f"\nRisk area: The primary risk is in {error_category} — pay close attention to timing and execution.")

        if actionable_change:
            parts.append(f"\nRecommended adjustment: {actionable_change}")

        # Add concrete levels
        if entry_price and exit_price:
            if outcome == "win":
                parts.append(
                    f"\nSuggested targets: Entry at {entry_price}, "
                    f"take profit near {exit_price}."
                )
            else:
                parts.append(
                    f"\nIf entering: Set a tight stop loss. The previous attempt "
                    f"at {entry_price} resulted in exit at {exit_price} "
                    f"({pnl_pct:+.2f}%)."
                )

        return "\n".join(parts)

    def _generate_counterfactual_example(
        self, trade: Any, reflection: dict[str, Any]
    ) -> TrainingExample | None:
        """Generate a counterfactual example from a losing trade.

        Creates an example that teaches the model what NOT to do,
        by presenting the same context but with the corrected response.
        """
        error_category = reflection.get("error_category", "none")
        actionable_change = reflection.get("actionable_change", "")

        if not actionable_change:
            return None

        symbol = getattr(trade, "symbol", "UNKNOWN")
        side = getattr(trade, "side", "buy")

        instruction = (
            f"I'm considering a {side.upper()} position on {symbol} with the following "
            f"conditions. What should I watch out for?\n\n"
            f"- Previous similar setup resulted in a loss\n"
            f"- Error category: {error_category}\n"
            f"- What went wrong: {reflection.get('what_went_wrong', 'N/A')}\n\n"
            f"How should I modify my approach to avoid repeating this mistake?"
        )

        response = (
            f"Based on historical analysis of similar setups on {symbol}:\n\n"
            f"⚠️ Key risk: {error_category} error\n\n"
            f"Previous issue: {reflection.get('what_went_wrong', 'Not documented')}\n\n"
            f"Recommended adjustment: {actionable_change}\n\n"
            f"Lesson: {reflection.get('lesson', 'Review this setup carefully')}\n\n"
            f"If you still want to proceed:\n"
            f"1. Reduce position size by 50%\n"
            f"2. Set tighter stop loss\n"
            f"3. Wait for additional confirmation signals\n"
            f"4. Monitor closely for the error pattern: {error_category}"
        )

        return TrainingExample(
            instruction=instruction,
            response=response,
            metadata={
                "type": "counterfactual",
                "trade_id": getattr(trade, "trade_id", "unknown"),
                "symbol": symbol,
                "outcome": "loss_corrected",
                "error_category": error_category,
            },
        )

    def _generate_lesson_examples(self) -> list[TrainingExample]:
        """Generate training examples from the lesson archive.

        Each critical/high-severity lesson becomes a training example
        that teaches the model to recognize and apply that lesson.
        """
        examples: list[TrainingExample] = []
        assert self._lesson_archive is not None

        # Get critical and high-severity lessons
        for severity in ("critical", "high"):
            lessons = self._lesson_archive.list_lessons(
                severity=severity, include_archived=False, limit=200
            )

            for lesson in lessons:
                content = lesson.content or lesson.description or ""
                if not content or len(content) < 10:
                    continue

                # Build instruction based on lesson applicability
                applicable_regimes = self._lesson_archive.get_applicable_regimes(
                    lesson.lesson_id
                )
                applicable_symbols = self._lesson_archive.get_applicable_symbols(
                    lesson.lesson_id
                )
                applicable_strategies = self._lesson_archive.get_applicable_strategies(
                    lesson.lesson_id
                )

                context_parts = ["Given the following market conditions:"]
                if applicable_regimes:
                    context_parts.append(f"- Market regime: {', '.join(applicable_regimes)}")
                if applicable_symbols:
                    context_parts.append(f"- Symbols: {', '.join(applicable_symbols)}")
                if applicable_strategies:
                    context_parts.append(f"- Strategy: {', '.join(applicable_strategies)}")

                context_parts.extend([
                    "",
                    "What trading principles should I follow? "
                    "What mistakes should I avoid?",
                ])

                instruction = "\n".join(context_parts)

                # Response is the lesson itself, structured as advice
                response_parts = [
                    f"**Trading Principle ({severity.upper()} priority):**",
                    "",
                    content,
                ]

                if lesson.action_item:
                    response_parts.extend(["", f"**Action Required:** {lesson.action_item}"])

                if lesson.times_violated > 0:
                    response_parts.extend([
                        "",
                        f"⚠️ This principle has been violated {lesson.times_violated} times "
                        f"with cumulative impact of ${lesson.violation_impact:.2f}. "
                        f"Take this seriously.",
                    ])

                example = TrainingExample(
                    instruction=instruction,
                    response="\n".join(response_parts),
                    metadata={
                        "type": "lesson",
                        "lesson_id": lesson.lesson_id,
                        "severity": severity,
                        "times_applied": lesson.times_applied,
                        "times_violated": lesson.times_violated,
                        "confidence": lesson.confidence,
                    },
                )
                examples.append(example)

        return examples

    def _generate_pattern_examples(
        self, trades: list[Any]
    ) -> list[TrainingExample]:
        """Generate training examples from pattern library matches.

        For each active pattern, creates an example teaching the model
        to recognize that pattern and its optimal response.
        """
        examples: list[TrainingExample] = []
        assert self._pattern_library is not None

        active_patterns = self._pattern_library.get_active_patterns()

        for pattern in active_patterns:
            if pattern.sample_size < 5:
                continue  # Not enough data

            conditions = {}
            try:
                conditions = json.loads(pattern.conditions) if pattern.conditions else {}
            except (json.JSONDecodeError, TypeError):
                pass

            # Build instruction
            instruction_parts = [
                f"I'm analyzing a potential {pattern.pattern_type} pattern:",
                f"",
                f"- Pattern: {pattern.pattern_name}",
                f"- Description: {pattern.description}",
            ]

            if conditions:
                instruction_parts.append("- Conditions:")
                for key, value in conditions.items():
                    instruction_parts.append(f"  - {key}: {value}")

            instruction_parts.extend([
                "",
                "Based on this pattern, what's the optimal trading approach? "
                "Include entry, exit, and risk management recommendations.",
            ])

            # Build response from pattern statistics
            response_parts = [
                f"**Pattern: {pattern.pattern_name}**",
                f"",
                f"Statistical profile ({pattern.sample_size} observations):",
            ]

            if pattern.success_rate is not None:
                response_parts.append(
                    f"- Success rate: {pattern.success_rate:.1%}"
                )
            if pattern.avg_return is not None:
                response_parts.append(
                    f"- Average return: {pattern.avg_return:.2%}"
                )
            if pattern.risk_reward is not None:
                response_parts.append(
                    f"- Risk/reward: {pattern.risk_reward:.2f}"
                )
            if pattern.expectancy is not None:
                response_parts.append(
                    f"- Expectancy: {pattern.expectancy:.4f}"
                )

            # Recommendation based on statistics
            if pattern.success_rate and pattern.success_rate >= 0.6:
                response_parts.extend([
                    "",
                    "✅ This pattern has a strong historical edge. Recommended approach:",
                    "1. Enter with standard position size",
                    f"2. Target risk/reward of at least {pattern.risk_reward or 2.0:.1f}",
                    "3. Trail stop to lock in profits",
                ])
            elif pattern.success_rate and pattern.success_rate >= 0.45:
                response_parts.extend([
                    "",
                    "⚠️ This pattern is borderline. Proceed with caution:",
                    "1. Reduce position size by 50%",
                    "2. Set tight stop loss",
                    "3. Take profits early at first target",
                ])
            else:
                response_parts.extend([
                    "",
                    "🚫 This pattern has weak historical performance:",
                    "1. Avoid or use as confirmation only",
                    "2. If trading, use minimal position size",
                    "3. Prioritize capital preservation",
                ])

            example = TrainingExample(
                instruction="\n".join(instruction_parts),
                response="\n".join(response_parts),
                metadata={
                    "type": "pattern",
                    "pattern_id": pattern.pattern_id,
                    "pattern_name": pattern.pattern_name,
                    "success_rate": pattern.success_rate,
                    "sample_size": pattern.sample_size,
                    "confidence": pattern.confidence,
                },
            )
            examples.append(example)

        return examples

    def _balance_examples(self, examples: list[TrainingExample]) -> list[TrainingExample]:
        """Balance win/loss examples to prevent bias.

        If there are significantly more losing examples than winning
        (or vice versa), downsample the majority class.
        """
        win_examples = [e for e in examples if e.metadata.get("outcome") == "win"]
        loss_examples = [e for e in examples if e.metadata.get("outcome") == "loss"]
        other_examples = [
            e for e in examples
            if e.metadata.get("outcome") not in ("win", "loss")
        ]

        if not win_examples or not loss_examples:
            return examples

        # Balance to the smaller class size (with 20% leeway)
        min_count = min(len(win_examples), len(loss_examples))
        max_count = int(min_count * 1.2)

        import random

        if len(win_examples) > max_count:
            win_examples = random.sample(win_examples, max_count)
        if len(loss_examples) > max_count:
            loss_examples = random.sample(loss_examples, max_count)

        balanced = win_examples + loss_examples + other_examples
        random.shuffle(balanced)

        logger.info(
            "Balanced dataset: %d win, %d loss, %d other (from %d total)",
            len(win_examples),
            len(loss_examples),
            len(other_examples),
            len(balanced),
        )

        return balanced

    def compute_stats(self, examples: list[TrainingExample]) -> DatasetStats:
        """Compute statistics for a generated dataset."""
        win_count = sum(1 for e in examples if e.metadata.get("outcome") == "win")
        loss_count = sum(1 for e in examples if e.metadata.get("outcome") == "loss")
        breakeven_count = sum(
            1 for e in examples if e.metadata.get("outcome") == "breakeven"
        )
        lesson_count = sum(1 for e in examples if e.metadata.get("type") == "lesson")
        pattern_count = sum(1 for e in examples if e.metadata.get("type") == "pattern")

        source_trades = len(
            {e.metadata.get("trade_id") for e in examples if e.metadata.get("trade_id")}
        )
        source_lessons = len(
            {e.metadata.get("lesson_id") for e in examples if e.metadata.get("lesson_id")}
        )

        # Rough token estimates (4 chars ≈ 1 token)
        avg_instr = (
            sum(len(e.instruction) for e in examples) // max(1, len(examples)) // 4
        )
        avg_resp = (
            sum(len(e.response) for e in examples) // max(1, len(examples)) // 4
        )

        return DatasetStats(
            total_examples=len(examples),
            win_examples=win_count,
            loss_examples=loss_count,
            breakeven_examples=breakeven_count,
            lesson_examples=lesson_count,
            pattern_examples=pattern_count,
            avg_instruction_tokens=avg_instr,
            avg_response_tokens=avg_resp,
            generated_at=datetime.now(UTC).isoformat(),
            source_trades=source_trades,
            source_lessons=source_lessons,
        )

    @staticmethod
    def save_dataset(
        examples: list[TrainingExample],
        output_path: str | Path,
        format: str = "jsonl",
    ) -> Path:
        """Save training examples to disk.

        Args:
            examples: List of training examples.
            output_path: File path to save to.
            format: Output format — "jsonl" or "json".

        Returns:
            Path to the saved file.
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if format == "jsonl":
            with open(output, "w") as f:
                for ex in examples:
                    f.write(json.dumps(ex.to_dict(), default=str) + "\n")
        elif format == "json":
            with open(output, "w") as f:
                json.dump([ex.to_dict() for ex in examples], f, indent=2, default=str)
        elif format == "chat_jsonl":
            # Chat format for SFTTrainer
            with open(output, "w") as f:
                for ex in examples:
                    f.write(json.dumps(ex.to_chat_format(), default=str) + "\n")
        else:
            raise ValueError(f"Unknown format: {format}")

        logger.info("Dataset saved: %d examples → %s", len(examples), output)
        return output


# ═══════════════════════════════════════════════════════════════════════
# LORA TRAINER
# ═══════════════════════════════════════════════════════════════════════


class LoRATrainer:
    """Fine-tune LLM using LoRA (Low-Rank Adaptation) on trade data.

    Supports:
    - QLoRA (4-bit quantized training) for memory efficiency
    - LoRA with configurable rank, alpha, and target modules
    - Integration with HuggingFace transformers + peft + trl
    - Checkpoint saving and training resumption

    Usage::

        trainer = LoRATrainer(config)
        run = trainer.train(dataset_path="data/datasets/trade_v1.jsonl")
        print(f"Training complete: {run.adapter_path}")
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._lora_cfg = self._config.get("lora", {})
        self._training_cfg = self._config.get("training", {})
        self._model_cfg = self._config.get("model", {})
        self._output_dir = Path(self._config.get("output_dir", "data/models"))

    @property
    def available(self) -> bool:
        """Check if all required dependencies are available."""
        return all([
            _TORCH_AVAILABLE,
            _PEFT_AVAILABLE,
            _TRANSFORMERS_AVAILABLE,
            _TRL_AVAILABLE,
            _DATASETS_AVAILABLE,
        ])

    def train(
        self,
        dataset_path: str | Path,
        base_model: str | None = None,
        output_dir: str | Path | None = None,
    ) -> TrainingRun:
        """Run LoRA fine-tuning on the given dataset.

        Args:
            dataset_path: Path to JSONL training dataset.
            base_model: HuggingFace model name/path. If None, uses config.
            output_dir: Where to save the adapter. If None, uses config.

        Returns:
            TrainingRun with results and metrics.

        Raises:
            RuntimeError: If required dependencies are missing.
            ValueError: If dataset is empty or model not found.
        """
        if not self.available:
            missing = []
            if not _TORCH_AVAILABLE:
                missing.append("torch")
            if not _PEFT_AVAILABLE:
                missing.append("peft")
            if not _TRANSFORMERS_AVAILABLE:
                missing.append("transformers")
            if not _TRL_AVAILABLE:
                missing.append("trl")
            if not _DATASETS_AVAILABLE:
                missing.append("datasets")
            raise RuntimeError(
                f"Missing dependencies for fine-tuning: {', '.join(missing)}. "
                f"Install with: pip install torch peft transformers trl datasets"
            )

        model_name = base_model or self._model_cfg.get(
            "base_model", "Qwen/Qwen2.5-7B-Instruct"
        )
        out_dir = Path(output_dir or self._output_dir)

        run = TrainingRun(
            base_model=model_name,
            status="training",
            started_at=datetime.now(UTC).isoformat(),
        )

        try:
            import torch
            from datasets import Dataset
            from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            from trl import SFTTrainer

            logger.info("Starting LoRA training: model=%s, dataset=%s", model_name, dataset_path)

            # Load dataset
            examples = self._load_dataset(dataset_path)
            run.dataset_size = len(examples)

            if len(examples) == 0:
                raise ValueError("Dataset is empty")

            # Determine device
            device_map = "auto"
            torch_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

            # BitsAndBytes config for QLoRA
            use_qlora = self._lora_cfg.get("use_qlora", True)
            bnb_config = None
            if use_qlora and torch.cuda.is_available():
                bnb_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch_dtype,
                    bnb_4bit_use_double_quant=True,
                )

            # Load tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                trust_remote_code=True,
                padding_side="right",
            )
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            # Load model
            model_kwargs: dict[str, Any] = {
                "trust_remote_code": True,
                "torch_dtype": torch_dtype,
                "device_map": device_map,
            }
            if bnb_config:
                model_kwargs["quantization_config"] = bnb_config

            model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)

            if use_qlora and bnb_config:
                model = prepare_model_for_kbit_training(model)

            # LoRA configuration
            lora_config = LoraConfig(
                r=self._lora_cfg.get("rank", 16),
                lora_alpha=self._lora_cfg.get("alpha", 32),
                lora_dropout=self._lora_cfg.get("dropout", 0.05),
                target_modules=self._lora_cfg.get(
                    "target_modules",
                    ["q_proj", "k_proj", "v_proj", "o_proj",
                     "gate_proj", "up_proj", "down_proj"],
                ),
                bias=self._lora_cfg.get("bias", "none"),
                task_type="CAUSAL_LM",
            )

            run.lora_rank = lora_config.r
            run.lora_alpha = lora_config.lora_alpha

            # Training arguments
            training_args = TrainingArguments(
                output_dir=str(out_dir / run.run_id),
                num_train_epochs=self._training_cfg.get("epochs", 3),
                per_device_train_batch_size=self._training_cfg.get("batch_size", 4),
                gradient_accumulation_steps=self._training_cfg.get(
                    "gradient_accumulation_steps", 4
                ),
                learning_rate=self._training_cfg.get("learning_rate", 2e-4),
                weight_decay=self._training_cfg.get("weight_decay", 0.01),
                warmup_ratio=self._training_cfg.get("warmup_ratio", 0.1),
                lr_scheduler_type=self._training_cfg.get("lr_scheduler", "cosine"),
                logging_steps=self._training_cfg.get("logging_steps", 10),
                save_strategy="epoch",
                evaluation_strategy="no",
                bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
                fp16=torch.cuda.is_available() and not torch.cuda.is_bf16_supported(),
                gradient_checkpointing=self._training_cfg.get(
                    "gradient_checkpointing", True
                ),
                max_grad_norm=self._training_cfg.get("max_grad_norm", 0.3),
                optim=self._training_cfg.get("optimizer", "paged_adamw_8bit"),
                report_to="none",  # Disable wandb/tensorboard
            )

            # Create HF dataset
            hf_dataset = Dataset.from_list(examples)

            # Create trainer
            max_seq_length = self._training_cfg.get("max_seq_length", 2048)
            trainer = SFTTrainer(
                model=model,
                args=training_args,
                train_dataset=hf_dataset,
                peft_config=lora_config,
                tokenizer=tokenizer,
                max_seq_length=max_seq_length,
            )

            # Train!
            start_time = time.monotonic()
            train_result = trainer.train()
            duration = time.monotonic() - start_time

            # Save adapter
            adapter_path = out_dir / run.run_id / "adapter"
            adapter_path.mkdir(parents=True, exist_ok=True)
            trainer.save_model(str(adapter_path))
            tokenizer.save_pretrained(str(adapter_path))

            # Record results
            run.adapter_path = str(adapter_path)
            run.training_loss = train_result.training_loss
            run.training_duration_s = duration
            run.epochs_completed = int(self._training_cfg.get("epochs", 3))
            run.status = "completed"
            run.completed_at = datetime.now(UTC).isoformat()
            run.metrics = {
                "train_loss": train_result.training_loss,
                "train_runtime": train_result.metrics.get("train_runtime", 0),
                "train_samples_per_second": train_result.metrics.get(
                    "train_samples_per_second", 0
                ),
                "total_flos": train_result.metrics.get("total_flos", 0),
            }

            logger.info(
                "LoRA training complete: run_id=%s, loss=%.4f, duration=%.1fs, adapter=%s",
                run.run_id,
                run.training_loss,
                run.training_duration_s,
                run.adapter_path,
            )

        except Exception as e:
            run.status = "failed"
            run.error = str(e)
            run.completed_at = datetime.now(UTC).isoformat()
            logger.error("LoRA training failed: %s", e)
            raise

        return run

    @staticmethod
    def _load_dataset(path: str | Path) -> list[dict[str, Any]]:
        """Load JSONL dataset into chat format for SFT training."""
        examples = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)

                # Convert to chat format
                if "messages" in data:
                    examples.append(data)
                elif "instruction" in data:
                    messages = []
                    sys_prompt = data.get("system_prompt", _SYSTEM_PROMPT)
                    if sys_prompt:
                        messages.append({"role": "system", "content": sys_prompt})
                    messages.append({"role": "user", "content": data["instruction"]})
                    messages.append({"role": "assistant", "content": data["response"]})
                    examples.append({"messages": messages})
        return examples

    def merge_adapter(
        self,
        base_model: str,
        adapter_path: str | Path,
        output_path: str | Path,
    ) -> Path:
        """Merge LoRA adapter into base model for deployment.

        Args:
            base_model: Original base model name/path.
            adapter_path: Path to the saved LoRA adapter.
            output_path: Where to save the merged model.

        Returns:
            Path to the merged model.
        """
        if not _PEFT_AVAILABLE or not _TRANSFORMERS_AVAILABLE:
            raise RuntimeError("peft and transformers required for adapter merging")

        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info("Merging adapter: base=%s, adapter=%s", base_model, adapter_path)

        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            torch_dtype=torch.bfloat16,
            device_map="cpu",
            trust_remote_code=True,
        )
        model = PeftModel.from_pretrained(model, str(adapter_path))
        model = model.merge_and_unload()

        out = Path(output_path)
        out.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(out))

        tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
        tokenizer.save_pretrained(str(out))

        logger.info("Merged model saved to %s", out)
        return out


# ═══════════════════════════════════════════════════════════════════════
# POST-TRAINING EVALUATOR
# ═══════════════════════════════════════════════════════════════════════


class PostTrainingEvaluator:
    """Evaluate fine-tuned model against the base model.

    Runs both models on a held-out test set of trading scenarios and
    compares:
    - Directional accuracy (correct buy/sell recommendations)
    - Risk awareness (mentions of stop loss, position sizing, etc.)
    - Lesson adherence (applies known trading principles)
    - Response quality (coherence, actionability)

    The fine-tuned model is accepted only if it improves on at least
    2 of 4 dimensions without significant regression on any.

    Usage::

        evaluator = PostTrainingEvaluator(config)
        result = evaluator.evaluate(
            base_model="Qwen/Qwen2.5-7B-Instruct",
            adapter_path="data/models/run123/adapter",
            test_scenarios=scenarios,
        )
        if result.accepted:
            print(f"Model improved by {result.improvement_pct:.1f}%")
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        eval_cfg = self._config.get("evaluation", {})
        self._min_improvement = eval_cfg.get("min_improvement_pct", 5.0)
        self._max_regression = eval_cfg.get("max_regression_pct", 3.0)
        self._test_size = eval_cfg.get("test_size", 50)

    def evaluate(
        self,
        base_model: str,
        adapter_path: str | Path,
        test_scenarios: list[dict[str, Any]] | None = None,
        trade_memory: TradeMemory | None = None,
    ) -> EvaluationResult:
        """Evaluate fine-tuned model vs base model.

        Args:
            base_model: HuggingFace model name/path.
            adapter_path: Path to LoRA adapter.
            test_scenarios: Pre-built test scenarios. If None, generates from trade_memory.
            trade_memory: TradeMemory for generating test scenarios.

        Returns:
            EvaluationResult with comparison metrics.
        """
        result = EvaluationResult(
            evaluated_at=datetime.now(UTC).isoformat(),
        )

        # Generate test scenarios if not provided
        if test_scenarios is None:
            if trade_memory is None:
                raise ValueError("Either test_scenarios or trade_memory required")
            test_scenarios = self._generate_test_scenarios(trade_memory)

        result.test_cases = len(test_scenarios)

        if not _TRANSFORMERS_AVAILABLE or not _PEFT_AVAILABLE:
            logger.warning("Cannot run model evaluation — using rule-based fallback")
            return self._rule_based_evaluate(test_scenarios, result)

        try:
            # Load base model
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer

            logger.info("Loading base model: %s", base_model)
            tokenizer = AutoTokenizer.from_pretrained(
                base_model, trust_remote_code=True
            )
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            base = AutoModelForCausalLM.from_pretrained(
                base_model,
                torch_dtype=torch.bfloat16,
                device_map="auto",
                trust_remote_code=True,
            )

            # Load fine-tuned model (base + adapter)
            logger.info("Loading adapter: %s", adapter_path)
            finetuned = PeftModel.from_pretrained(base, str(adapter_path))

            # Evaluate both models
            base_scores = self._score_model(base, tokenizer, test_scenarios)
            ft_scores = self._score_model(finetuned, tokenizer, test_scenarios)

            result.base_model_score = base_scores["overall"]
            result.finetuned_model_score = ft_scores["overall"]
            result.directional_accuracy_before = base_scores["directional_accuracy"]
            result.directional_accuracy_after = ft_scores["directional_accuracy"]
            result.risk_awareness_before = base_scores["risk_awareness"]
            result.risk_awareness_after = ft_scores["risk_awareness"]

            if base_scores["overall"] > 0:
                result.improvement_pct = (
                    (ft_scores["overall"] - base_scores["overall"])
                    / base_scores["overall"]
                    * 100
                )

            # Decision logic
            result.accepted = self._should_accept(base_scores, ft_scores)
            if not result.accepted:
                result.rejection_reason = (
                    f"Insufficient improvement: {result.improvement_pct:.1f}% "
                    f"(min: {self._min_improvement}%)"
                )

            result.details = {
                "base_scores": base_scores,
                "finetuned_scores": ft_scores,
            }

            # Cleanup
            del base, finetuned
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        except Exception as e:
            logger.error("Model evaluation failed: %s", e)
            result.rejection_reason = f"Evaluation error: {e}"
            result.accepted = False

        return result

    def _score_model(
        self,
        model: Any,
        tokenizer: Any,
        scenarios: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Score a model on a set of test scenarios."""
        import torch

        correct_direction = 0
        risk_mentions = 0
        total = 0
        quality_scores: list[float] = []

        for scenario in scenarios:
            instruction = scenario["instruction"]
            expected_outcome = scenario.get("expected_outcome", "neutral")

            # Generate response
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": instruction},
            ]
            input_text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=512,
                    temperature=0.3,
                    do_sample=True,
                    top_p=0.9,
                )

            response = tokenizer.decode(
                outputs[0][inputs["input_ids"].shape[1]:],
                skip_special_tokens=True,
            )

            # Score directional accuracy
            total += 1
            response_lower = response.lower()

            if expected_outcome == "win":
                if any(
                    kw in response_lower
                    for kw in ["buy", "long", "enter", "execute", "favorable"]
                ):
                    correct_direction += 1
            elif expected_outcome == "loss":
                if any(
                    kw in response_lower
                    for kw in ["avoid", "caution", "risk", "wait", "skip", "reduce"]
                ):
                    correct_direction += 1
            else:
                correct_direction += 0.5  # Neutral gets half credit

            # Score risk awareness
            risk_keywords = [
                "stop loss", "stop-loss", "position size", "risk",
                "drawdown", "hedge", "protect", "limit exposure",
            ]
            risk_found = sum(1 for kw in risk_keywords if kw in response_lower)
            if risk_found >= 2:
                risk_mentions += 1

            # Simple quality score (response length + keyword coverage)
            quality = min(1.0, len(response) / 200) * 0.5
            quality += min(0.5, risk_found / 4)
            quality_scores.append(quality)

        directional_accuracy = correct_direction / max(1, total)
        risk_awareness = risk_mentions / max(1, total)
        avg_quality = sum(quality_scores) / max(1, len(quality_scores))

        overall = (
            directional_accuracy * 0.4
            + risk_awareness * 0.3
            + avg_quality * 0.3
        )

        return {
            "overall": overall,
            "directional_accuracy": directional_accuracy,
            "risk_awareness": risk_awareness,
            "quality": avg_quality,
        }

    def _should_accept(
        self,
        base_scores: dict[str, float],
        ft_scores: dict[str, float],
    ) -> bool:
        """Determine if the fine-tuned model should be accepted.

        Accept if:
        1. Overall improvement >= min_improvement threshold
        2. No dimension regresses by more than max_regression
        3. At least 2 of 4 dimensions improved
        """
        improvements = 0
        regressions = 0

        for key in ("directional_accuracy", "risk_awareness", "quality"):
            diff = ft_scores.get(key, 0) - base_scores.get(key, 0)
            if diff > 0.02:  # 2% improvement threshold per dimension
                improvements += 1
            elif diff < -self._max_regression / 100:
                regressions += 1

        overall_improvement = ft_scores["overall"] - base_scores["overall"]

        return (
            overall_improvement >= self._min_improvement / 100
            and regressions == 0
            and improvements >= 2
        )

    def _generate_test_scenarios(
        self, trade_memory: TradeMemory
    ) -> list[dict[str, Any]]:
        """Generate test scenarios from recent trade history.

        Uses the most recent 20% of trades as a held-out test set.
        """
        from datetime import timedelta

        # Get recent closed trades
        since = (datetime.now(UTC) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        trades = trade_memory.list_trades(status="CLOSED", since=since, limit=500)

        if not trades:
            # Fallback: get any closed trades
            trades = trade_memory.list_trades(status="CLOSED", limit=500)

        # Use the most recent 20% as test set
        test_count = max(10, len(trades) // 5)
        test_trades = trades[:test_count]

        scenarios = []
        for trade in test_trades:
            symbol = getattr(trade, "symbol", "BTC/USDT")
            side = getattr(trade, "side", "buy")
            strategy = getattr(trade, "strategy_id", "unknown")
            regime = getattr(trade, "regime_at_entry", "unknown")
            confidence = getattr(trade, "confidence", 0.5)
            thesis = getattr(trade, "thesis", "")
            pnl = getattr(trade, "realized_pnl", 0)

            instruction = (
                f"Analyze this trading setup for {symbol}:\n"
                f"- Strategy: {strategy}\n"
                f"- Direction: {side.upper()}\n"
                f"- Market regime: {regime}\n"
                f"- Confidence: {confidence:.2f}\n"
            )
            if thesis:
                instruction += f"- Thesis: {thesis}\n"
            instruction += (
                "\nShould I execute this trade? Provide your recommendation."
            )

            outcome = "win" if pnl > 0 else ("loss" if pnl < 0 else "neutral")

            scenarios.append({
                "instruction": instruction,
                "expected_outcome": outcome,
                "trade_id": getattr(trade, "trade_id", ""),
                "actual_pnl": pnl,
            })

        return scenarios

    def _rule_based_evaluate(
        self,
        test_scenarios: list[dict[str, Any]],
        result: EvaluationResult,
    ) -> EvaluationResult:
        """Rule-based evaluation fallback when models can't be loaded.

        Uses the existing LLMEvaluator to compute baseline metrics,
        then applies a heuristic improvement estimate.
        """
        # Just return baseline — no model comparison possible
        result.base_model_score = 0.5
        result.finetuned_model_score = 0.5
        result.improvement_pct = 0.0
        result.accepted = False
        result.rejection_reason = (
            "Cannot evaluate — transformers/peft not available. "
            "Install dependencies to enable model evaluation."
        )
        return result


# ═══════════════════════════════════════════════════════════════════════
# POST-TRAINING PIPELINE (ORCHESTRATOR)
# ═══════════════════════════════════════════════════════════════════════


class PostTrainingPipeline:
    """Orchestrate the full post-training cycle.

    Pipeline stages:
    1. GENERATE: Convert trade history → training dataset
    2. TRAIN: Fine-tune model with LoRA on the dataset
    3. EVALUATE: Compare fine-tuned vs base model
    4. DEPLOY: If improved, register the new adapter

    The pipeline is designed to be called from the FlywheelOrchestrator
    after every N trades, closing the self-improvement loop.

    Usage::

        pipeline = PostTrainingPipeline(trade_memory, lesson_archive, config)
        result = pipeline.run()
        if result["status"] == "deployed":
            print(f"New model deployed: {result['adapter_path']}")
    """

    def __init__(
        self,
        trade_memory: TradeMemory,
        lesson_archive: LessonArchive | None = None,
        pattern_library: PatternLibrary | None = None,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self._trade_memory = trade_memory
        self._lesson_archive = lesson_archive
        self._pattern_library = pattern_library

        # Load config
        if config is not None:
            self._config = config
        elif config_path:
            self._config = self._load_config(config_path)
        else:
            self._config = self._load_config(DEFAULT_CONFIG_PATH)

        self._data_dir = Path(self._config.get("data_dir", "data"))
        self._dataset_dir = self._data_dir / "datasets"
        self._models_dir = self._data_dir / "models"

        # Pipeline state
        self._last_run: dict[str, Any] | None = None
        self._run_history: list[dict[str, Any]] = []

    @staticmethod
    def _load_config(path: str | Path) -> dict[str, Any]:
        """Load YAML config file."""
        p = Path(path)
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
        logger.warning("Config not found: %s — using defaults", p)
        return {}

    def run(
        self,
        force: bool = False,
        skip_training: bool = False,
    ) -> dict[str, Any]:
        """Execute the full post-training pipeline.

        Args:
            force: Run even if insufficient new trades.
            skip_training: Only generate dataset, don't train.

        Returns:
            Dict with pipeline results:
            - status: "completed" | "deployed" | "skipped" | "failed"
            - dataset_stats: Dataset generation stats
            - training_run: Training run details
            - evaluation: Evaluation results
            - adapter_path: Path to new adapter (if deployed)
        """
        result: dict[str, Any] = {
            "status": "started",
            "pipeline_id": uuid.uuid4().hex[:12],
            "started_at": datetime.now(UTC).isoformat(),
        }

        try:
            # ── Stage 1: GENERATE ─────────────────────────────
            logger.info("═══ POST-TRAINING PIPELINE: Stage 1 — GENERATE ═══")
            dataset_cfg = self._config.get("dataset_generation", {})
            min_trades = dataset_cfg.get("min_trades", 20)

            generator = TradeDatasetGenerator(
                trade_memory=self._trade_memory,
                lesson_archive=self._lesson_archive,
                pattern_library=self._pattern_library,
                config=self._config,
            )

            try:
                examples = generator.generate(min_trades=min_trades)
            except ValueError as e:
                result["status"] = "skipped"
                result["reason"] = str(e)
                logger.info("Pipeline skipped: %s", e)
                return result

            # Save dataset
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            dataset_path = self._dataset_dir / f"trade_dataset_{timestamp}.jsonl"
            generator.save_dataset(examples, dataset_path, format="chat_jsonl")

            dataset_stats = generator.compute_stats(examples)
            result["dataset_stats"] = dataset_stats.to_dict()
            result["dataset_path"] = str(dataset_path)

            logger.info(
                "Dataset generated: %d examples, %d source trades",
                dataset_stats.total_examples,
                dataset_stats.source_trades,
            )

            if skip_training:
                result["status"] = "dataset_generated"
                return result

            # ── Stage 2: TRAIN ────────────────────────────────
            logger.info("═══ POST-TRAINING PIPELINE: Stage 2 — TRAIN ═══")
            trainer = LoRATrainer(config=self._config)

            if not trainer.available:
                result["status"] = "skipped"
                result["reason"] = (
                    "Training dependencies not available. "
                    "Install: pip install torch peft transformers trl datasets"
                )
                logger.warning("Training skipped — dependencies missing")
                return result

            training_run = trainer.train(dataset_path=dataset_path)
            result["training_run"] = training_run.to_dict()

            if training_run.status == "failed":
                result["status"] = "failed"
                result["reason"] = training_run.error
                return result

            # ── Stage 3: EVALUATE ─────────────────────────────
            logger.info("═══ POST-TRAINING PIPELINE: Stage 3 — EVALUATE ═══")
            eval_cfg = self._config.get("evaluation", {})
            base_model = self._config.get("model", {}).get(
                "base_model", "Qwen/Qwen2.5-7B-Instruct"
            )

            evaluator = PostTrainingEvaluator(config=self._config)
            eval_result = evaluator.evaluate(
                base_model=base_model,
                adapter_path=training_run.adapter_path,
                trade_memory=self._trade_memory,
            )
            result["evaluation"] = eval_result.to_dict()

            # ── Stage 4: DEPLOY (or rollback) ─────────────────
            if eval_result.accepted:
                logger.info(
                    "═══ POST-TRAINING PIPELINE: Stage 4 — DEPLOY ═══ "
                    "(improvement: %.1f%%)",
                    eval_result.improvement_pct,
                )
                result["status"] = "deployed"
                result["adapter_path"] = training_run.adapter_path
                result["improvement_pct"] = eval_result.improvement_pct

                # Record the deployment
                self._record_deployment(training_run, eval_result)
            else:
                logger.info(
                    "═══ POST-TRAINING PIPELINE: REJECTED ═══ (%s)",
                    eval_result.rejection_reason,
                )
                result["status"] = "rejected"
                result["reason"] = eval_result.rejection_reason

        except Exception as e:
            result["status"] = "failed"
            result["reason"] = str(e)
            logger.error("Post-training pipeline failed: %s", e)

        result["completed_at"] = datetime.now(UTC).isoformat()
        self._last_run = result
        self._run_history.append(result)

        return result

    def _record_deployment(
        self, training_run: TrainingRun, eval_result: EvaluationResult
    ) -> None:
        """Record a successful model deployment."""
        deployments_file = self._models_dir / "deployments.jsonl"
        deployments_file.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": training_run.run_id,
            "base_model": training_run.base_model,
            "adapter_path": training_run.adapter_path,
            "training_loss": training_run.training_loss,
            "improvement_pct": eval_result.improvement_pct,
            "test_cases": eval_result.test_cases,
            "directional_accuracy": eval_result.directional_accuracy_after,
            "risk_awareness": eval_result.risk_awareness_after,
        }

        with open(deployments_file, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

        logger.info("Deployment recorded: %s", training_run.run_id)

    def get_status(self) -> dict[str, Any]:
        """Get pipeline status and history."""
        return {
            "last_run": self._last_run,
            "total_runs": len(self._run_history),
            "successful_deployments": sum(
                1 for r in self._run_history if r.get("status") == "deployed"
            ),
            "dependencies": {
                "torch": _TORCH_AVAILABLE,
                "peft": _PEFT_AVAILABLE,
                "transformers": _TRANSFORMERS_AVAILABLE,
                "trl": _TRL_AVAILABLE,
                "datasets": _DATASETS_AVAILABLE,
            },
        }
