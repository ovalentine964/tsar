"""
Trade Philosopher — Post-trade reflection and lesson extraction.

Role: ANALYSIS (Level 3+)
Model Tier: T2 (trade_summary) + T3 (trade_narrative for deep analysis)

Reflection cycle:
  1. Receive completed trade data
  2. Analyze what went right/wrong
  3. Extract actionable lessons (structured JSON output)
  4. Store in lesson archive
  5. Feed back to strategy evolution

Subscribes to: tsar:stream:fills, tsar:stream:positions, tsar:stream:risk_decisions
Publishes to: tsar:stream:analytics
"""

import json
import logging
from typing import Any

from src.agents.base import BaseAgent

# ── Domain Tools (Tools-to-Agents Wiring) ──────────────────────────
from src.tools.knowledge import KnowledgeTools

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# STRUCTURED OUTPUT SCHEMA
# ═══════════════════════════════════════════════════════════════════════

TRADE_REFLECTION_SCHEMA = {
    "type": "object",
    "required": ["trade_id", "outcome", "lesson", "confidence", "pattern_tags"],
    "properties": {
        "trade_id": {
            "type": "string",
            "description": "The unique identifier of the trade being reflected on.",
        },
        "outcome": {
            "type": "string",
            "enum": ["win", "loss", "breakeven"],
            "description": "Categorized trade outcome.",
        },
        "lesson": {
            "type": "string",
            "minLength": 10,
            "description": "Actionable lesson extracted from this trade.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence in the lesson (0.0 to 1.0).",
        },
        "pattern_tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Tags identifying patterns (e.g. 'trend_following', 'oversold_bounce', 'regime_mismatch').",
        },
        "what_went_right": {
            "type": "string",
            "description": "What worked well in this trade.",
        },
        "what_went_wrong": {
            "type": "string",
            "description": "What didn't work or could be improved.",
        },
        "error_category": {
            "type": "string",
            "enum": ["timing", "sizing", "regime", "execution", "none"],
            "description": "Primary error category if applicable.",
        },
        "actionable_change": {
            "type": "string",
            "description": "Specific parameter or rule change recommended.",
        },
    },
}

REFLECTION_JSON_INSTRUCTIONS = """\
You MUST respond with a valid JSON object matching this schema:
{
  "trade_id": "<trade_id>",
  "outcome": "win" | "loss" | "breakeven",
  "lesson": "<actionable lesson, min 10 chars>",
  "confidence": <0.0 to 1.0>,
  "pattern_tags": ["<tag1>", "<tag2>"],
  "what_went_right": "<optional>",
  "what_went_wrong": "<optional>",
  "error_category": "timing" | "sizing" | "regime" | "execution" | "none",
  "actionable_change": "<optional specific change>"
}

Do NOT include any text outside the JSON object."""


def _validate_reflection(data: dict[str, Any], trade_id: str) -> dict[str, Any]:
    """Validate and normalize a reflection dict against the schema.

    Fills in defaults for missing optional fields and ensures
    required fields are present with correct types.

    Args:
        data: Raw parsed JSON from LLM output.
        trade_id: The trade ID (used as fallback if missing from output).

    Returns:
        Validated and normalized reflection dict.
    """
    validated: dict[str, Any] = {}

    # Required fields
    validated["trade_id"] = str(data.get("trade_id", trade_id))

    outcome = data.get("outcome", "unknown")
    if outcome not in ("win", "loss", "breakeven"):
        # Infer from context if possible
        if "win" in str(outcome).lower():
            outcome = "win"
        elif "loss" in str(outcome).lower() or "lose" in str(outcome).lower():
            outcome = "loss"
        else:
            outcome = "breakeven"
    validated["outcome"] = outcome

    lesson = data.get("lesson", "")
    if not lesson or len(str(lesson)) < 10:
        lesson = f"Trade {trade_id}: review needed — insufficient lesson content"
    validated["lesson"] = str(lesson)

    try:
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = 0.5
    validated["confidence"] = confidence

    pattern_tags = data.get("pattern_tags", [])
    if isinstance(pattern_tags, str):
        pattern_tags = [t.strip() for t in pattern_tags.split(",") if t.strip()]
    if not isinstance(pattern_tags, list) or len(pattern_tags) == 0:
        pattern_tags = ["unreviewed"]
    validated["pattern_tags"] = [str(t) for t in pattern_tags]

    # Optional fields (pass through if present)
    for opt_field in ("what_went_right", "what_went_wrong", "actionable_change"):
        val = data.get(opt_field)
        if val:
            validated[opt_field] = str(val)

    error_cat = data.get("error_category")
    if error_cat in ("timing", "sizing", "regime", "execution", "none"):
        validated["error_category"] = error_cat

    return validated


class TradePhilosopher(BaseAgent):
    """Reflect on completed trades and extract structured lessons.

    All reflections are enforced against TRADE_REFLECTION_SCHEMA:
      - trade_id, outcome, lesson, confidence, pattern_tags (required)
      - what_went_right, what_went_wrong, error_category, actionable_change (optional)
    """

    AGENT_NAME = "trade_philosopher"
    ROLE = "ANALYSIS"

    def __init__(self, config: dict[str, Any], trading_mode: str = "paper") -> None:
        super().__init__(config, trading_mode)
        self.trade_memory = None
        self.lesson_archive = None
        self.llm_provider = None
        self.prompts = {}

        # ── Domain Tools (Tools-to-Agents Wiring) ───────
        self._knowledge_tools: KnowledgeTools | None = None
        self._db_path = config.get("database", {}).get("db_path", "data/tsar.db")

    async def on_initialize(self) -> None:
        """Initialize KnowledgeTools and wire trade_memory/lesson_archive."""
        try:
            self._knowledge_tools = KnowledgeTools(self._db_path)
            # Wire knowledge stores into the philosopher's references
            if self.trade_memory is None:
                self.trade_memory = self._knowledge_tools.trade_memory
            if self.lesson_archive is None:
                self.lesson_archive = self._knowledge_tools.lesson_archive
            logger.info(
                "TradePhilosopher initialized with KnowledgeTools: "
                "trade_memory=%s, lesson_archive=%s, pattern_library=%s",
                self.trade_memory is not None,
                self.lesson_archive is not None,
                self._knowledge_tools.pattern_library is not None,
            )
        except Exception as e:
            logger.warning("KnowledgeTools initialization failed: %s", e)

    async def run_cycle(self) -> dict[str, Any]:
        """Process completed trades and generate structured reflections.

        Each reflection is validated against TRADE_REFLECTION_SCHEMA
        before being stored.
        """
        if self.trade_memory is None or self.llm_provider is None:
            logger.debug("TradePhilosopher: trade_memory or llm_provider not set, skipping")
            return {"reflections": 0}

        closed = self.trade_memory.get_closed_trades(limit=10)
        if not closed:
            return {"reflections": 0}

        reflections = []
        for trade in closed:
            if trade.get("reflection"):
                continue  # Already reflected

            try:
                trade_id = trade.get("id", trade.get("trade_id", "unknown"))
                structured = await self._generate_structured_reflection(trade, trade_id)

                # Store the validated JSON as the reflection
                reflection_json = json.dumps(structured, default=str)
                self.trade_memory.update_trade(trade_id, reflection=reflection_json)

                # Create lesson with severity based on outcome
                pnl_pct = trade.get("pnl_pct", 0)
                if pnl_pct < -5:
                    severity = "critical"
                elif pnl_pct < -3:
                    severity = "high"
                elif pnl_pct < 0:
                    severity = "moderate"
                else:
                    severity = "insight"

                if self.lesson_archive:
                    self.lesson_archive.add(
                        content=structured["lesson"],
                        category="trade_reflection",
                        severity=severity,
                        trade_id=trade_id,
                    )

                # Match patterns via KnowledgeTools pattern_library
                if self._knowledge_tools and self._knowledge_tools.pattern_library:
                    try:
                        pattern_tags = structured.get("pattern_tags", [])
                        for tag in pattern_tags:
                            matched = self._knowledge_tools.pattern_library.match_pattern(
                                pattern_name=tag, min_confidence=0.5,
                            )
                            if matched:
                                logger.info(
                                    "TradePhilosopher: pattern '%s' matched %d library entries",
                                    tag, len(matched),
                                )
                    except Exception:
                        logger.debug("Pattern library matching failed", exc_info=True)

                reflections.append(trade_id)

            except Exception as e:
                logger.error("Reflection failed for trade %s: %s", trade.get("id"), e)

        return {"reflections": len(reflections), "trade_ids": reflections}

    async def _generate_structured_reflection(
        self, trade: dict[str, Any], trade_id: str
    ) -> dict[str, Any]:
        """Generate and validate a structured reflection for a trade.

        Uses the LLM with JSON schema enforcement, then validates
        the output against TRADE_REFLECTION_SCHEMA.

        Args:
            trade: Trade data dict.
            trade_id: Trade identifier.

        Returns:
            Validated reflection dict conforming to schema.
        """
        # Build prompt with schema instructions
        base_prompt = self.prompts.get("t3_trade_narrative", str(trade))
        prompt = (
            f"{base_prompt}\n\n"
            f"{REFLECTION_JSON_INSTRUCTIONS}\n\n"
            f"Trade ID: {trade_id}"
        )

        try:
            response = await self.llm_provider.generate(
                prompt=prompt,
                json_mode=True,
                temperature=0.3,
            )

            raw_text = response.text if response else "{}"

            # Parse JSON from LLM output
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                import re
                json_match = re.search(r"```(?:json)?\s*({.*?})\s*```", raw_text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(1))
                else:
                    logger.warning(
                        "TradePhilosopher: LLM output not valid JSON for trade %s, "
                        "using fallback",
                        trade_id,
                    )
                    parsed = {}

            # Validate against schema
            validated = _validate_reflection(parsed, trade_id)

            logger.info(
                "TradePhilosopher: structured reflection for trade %s: "
                "outcome=%s, confidence=%.2f, tags=%s",
                trade_id,
                validated["outcome"],
                validated["confidence"],
                validated["pattern_tags"],
            )
            return validated

        except Exception as e:
            logger.error("Structured reflection generation failed for %s: %s", trade_id, e)
            # Return a valid fallback reflection
            return _validate_reflection({}, trade_id)

    async def reflect_on_trade(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Generate a structured reflection on a completed trade.

        Returns a dict conforming to TRADE_REFLECTION_SCHEMA.
        """
        trade_id = trade.get("id", trade.get("trade_id", "unknown"))
        if self.llm_provider is None:
            return _validate_reflection({}, trade_id)

        try:
            return await self._generate_structured_reflection(trade, trade_id)
        except Exception as e:
            logger.error("Trade reflection failed: %s", e)
            return _validate_reflection({}, trade_id)

    @staticmethod
    def get_schema() -> dict[str, Any]:
        """Return the JSON schema for trade reflections."""
        return TRADE_REFLECTION_SCHEMA.copy()
