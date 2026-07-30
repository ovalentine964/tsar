"""TSAR — Shadow Extractor (Phase 1B + M-014 Post-Training Readiness).

Shadow Account Loop — Extract implicit trading rules from closed trade
history. Groups winning trades, analyzes patterns via LLM, and returns
structured TradingRule objects.

The flywheel step: TRADE → OBSERVE → REFLECT → **EXTRACT** → ADAPT → BETTER TRADE

═══════════════════════════════════════════════════════════════════════
POST-TRAINING APPROACH: LLM Rule-Extraction → Fine-Tuning Data (M-014)
═══════════════════════════════════════════════════════════════════════

TSAR uses a **rule-extraction pipeline** as its chosen method for
post-training readiness (current score: 3/10 → target: 7/10).

The approach:

1. **Extract** — ShadowExtractor analyzes closed trades via LLM to
   discover implicit if-then rules (conditions + actions).

2. **Validate** — RuleValidator (src/knowledge/rule_validator.py)
   applies statistical significance tests to filter spurious rules.

3. **Store** — Valid rules are persisted in the rule library with
   confidence scores, source trade IDs, and regime tags.

4. **Apply** — Rules feed back into the SignalScout as additional
   scoring factors, improving signal quality over time.

5. **Fine-Tune (Future)** — The structured (trade → rule) pairs serve
   as training data for supervised fine-tuning of smaller models:
   - Input: Trade context (indicators, regime, market state)
   - Output: Extracted rule (conditions, action, confidence)
   - This creates a distillation pipeline: large LLM extracts rules,
     small model learns to replicate the pattern matching.

Why rule-extraction over direct fine-tuning:
- Rules are interpretable and auditable
- Rules can be backtested before deployment
- Rules compose (multiple rules can be combined)
- Rules degrade gracefully (partial match still useful)
- Direct fine-tuning on trade data risks overfitting to noise

Current limitations (to reach 7/10):
- Rules are extracted per-group, not globally optimized
- No automated A/B testing of rule changes
- No reinforcement learning from rule performance feedback
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.llm.prompts import get_prompt, get_system_prompt
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.interfaces.llm_provider import LLMProvider
    from src.knowledge.trade_memory import TradeMemory, TradeRecord

logger = get_logger(__name__)


def _ulid() -> str:
    return uuid.uuid4().hex


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class TradingRule:
    """An if-then rule extracted from trade patterns.

    Represents an implicit trading rule discovered by analyzing
    winning (or losing) trades. The conditions are predicates that
    must be true for the action to trigger.
    """
    rule_id: str = field(default_factory=_ulid)
    conditions: list[dict[str, Any]] = field(default_factory=list)
    action: str = "buy"  # "buy" or "sell"
    confidence: float = 0.5
    source_trade_ids: list[str] = field(default_factory=list)
    symbol: str | None = None
    strategy_id: str | None = None
    regime: str | None = None
    description: str = ""
    rationale: str = ""
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ExtractionResult:
    """Result of a single extraction run."""
    result_id: str = field(default_factory=_ulid)
    rules: list[TradingRule] = field(default_factory=list)
    source_trade_count: int = 0
    winning_trade_count: int = 0
    losing_trade_count: int = 0
    extraction_method: str = "llm_pattern_analysis"
    model_used: str = ""
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rules"] = [r.to_dict() for r in self.rules]
        return d


# ═══════════════════════════════════════════════════════════════════════
# SHADOW EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════


class ShadowExtractor:
    """Extract implicit trading rules from closed trade history.

    Reads from TradeMemory, groups winning trades by symbol/strategy,
    analyzes patterns with LLM, and returns structured TradingRules.

    Usage::

        extractor = ShadowExtractor(trade_memory, llm_provider)
        result = await extractor.extract(min_trades=10)
        for rule in result.rules:
            print(rule.description)
    """

    def __init__(
        self,
        trade_memory: TradeMemory,
        llm_provider: LLMProvider,
    ) -> None:
        self._memory = trade_memory
        self._llm = llm_provider

    async def extract(
        self,
        symbol: str | None = None,
        strategy_id: str | None = None,
        min_trades: int = 5,
        min_win_rate: float = 0.55,
        lookback_days: int = 90,
    ) -> ExtractionResult:
        """Extract trading rules from recent closed trades.

        Args:
            symbol: Filter trades by symbol (None = all symbols).
            strategy_id: Filter trades by strategy (None = all strategies).
            min_trades: Minimum closed trades required for extraction.
            min_win_rate: Minimum win rate to consider a group "winning."
            lookback_days: How many days of history to analyze.

        Returns:
            ExtractionResult with extracted TradingRules.
        """
        # 1. Fetch closed trades
        since = None
        if lookback_days > 0:
            from datetime import timedelta
            since = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )

        closed_trades = self._memory.list_trades(
            symbol=symbol,
            strategy_id=strategy_id,
            status="CLOSED",
            since=since,
            limit=500,
        )

        if len(closed_trades) < min_trades:
            logger.info(
                "shadow_extract_insufficient_trades",
                closed_count=len(closed_trades),
                min_required=min_trades,
            )
            return ExtractionResult(source_trade_count=len(closed_trades))

        # 2. Split winners and losers
        winners = [t for t in closed_trades if t.realized_pnl > 0]
        losers = [t for t in closed_trades if t.realized_pnl <= 0]

        if len(winners) < min_trades:
            logger.info(
                "shadow_extract_insufficient_winners",
                winner_count=len(winners),
                min_required=min_trades,
            )
            return ExtractionResult(
                source_trade_count=len(closed_trades),
                winning_trade_count=len(winners),
                losing_trade_count=len(losers),
            )

        # 3. Group by symbol + strategy for pattern analysis
        groups = self._group_trades(winners)
        all_rules: list[TradingRule] = []

        for group_key, group_trades in groups.items():
            if len(group_trades) < 3:
                continue  # Need at least 3 trades to spot a pattern

            # 4. Build context for LLM (winners + losers for contrast)
            trade_summaries = self._summarize_trades(group_trades, losers)
            prompt = self._build_extraction_prompt(trade_summaries, group_key)

            # 5. Call LLM for rule extraction
            try:
                response = await self._llm.generate(
                    prompt=prompt,
                    system=get_system_prompt("t3_shadow_rule_extraction"),
                    json_mode=True,
                    temperature=0.3,
                )
                rules = self._parse_rules(response.content, group_trades)
                all_rules.extend(rules)
            except Exception as e:
                logger.error("shadow_extract_llm_error", group=group_key, error=str(e))
                continue

        # 6. Extract loss-weighted lessons from losing trades
        #    Losing trades carry heavier weight because they reveal
        #    what NOT to do — critical for genome mutation.
        loss_lessons = self._extract_loss_lessons(losers)
        for lesson_rule in loss_lessons:
            all_rules.append(lesson_rule)

        result = ExtractionResult(
            rules=all_rules,
            source_trade_count=len(closed_trades),
            winning_trade_count=len(winners),
            losing_trade_count=len(losers),
        )

        logger.info(
            "shadow_extraction_complete",
            rules_found=len(all_rules),
            trades_analyzed=len(closed_trades),
            loss_lessons=len(loss_lessons),
        )
        return result

    def _extract_loss_lessons(self, losers: list[TradeRecord]) -> list[TradingRule]:
        """Extract high-priority rules from losing trades.

        Losing trades are weighted more heavily because:
        1. Avoiding losses is more valuable than capturing wins
        2. Loss patterns often indicate systematic issues
        3. Loss lessons feed directly into risk parameter tuning

        Each losing trade's P&L severity determines the rule confidence:
        - Loss > 5% → confidence 0.9 (critical lesson)
        - Loss > 3% → confidence 0.8 (high importance)
        - Loss > 1% → confidence 0.7 (moderate)
        - Loss <= 1% → confidence 0.6 (minor)

        Args:
            losers: List of losing TradeRecords.

        Returns:
            List of TradingRules derived from loss patterns.
        """
        if not losers:
            return []

        loss_rules: list[TradingRule] = []

        # Group losers by symbol + strategy for pattern analysis
        groups: dict[str, list[TradeRecord]] = {}
        for trade in losers:
            key = f"{trade.symbol}|{trade.strategy_id}"
            groups.setdefault(key, []).append(trade)

        for group_key, group_trades in groups.items():
            if len(group_trades) < 2:
                continue

            # Compute loss severity weighting
            avg_loss_pct = abs(sum(t.realized_pnl_pct for t in group_trades) / len(group_trades))
            if avg_loss_pct > 5.0:
                base_confidence = 0.9
            elif avg_loss_pct > 3.0:
                base_confidence = 0.8
            elif avg_loss_pct > 1.0:
                base_confidence = 0.7
            else:
                base_confidence = 0.6

            # Build loss conditions from common patterns
            conditions = self._infer_loss_conditions(group_trades)
            if not conditions:
                continue

            symbol = group_trades[0].symbol
            strategy_id = group_trades[0].strategy_id
            source_ids = [t.trade_id for t in group_trades]

            # Create an AVOID rule (inverse of what caused losses)
            rule = TradingRule(
                conditions=conditions,
                action="avoid",  # Special action: avoid this setup
                confidence=base_confidence,
                source_trade_ids=source_ids,
                symbol=symbol,
                strategy_id=strategy_id,
                regime=group_trades[0].regime_at_entry,
                description=(
                    f"Loss pattern: {len(group_trades)} losing trades in "
                    f"{symbol} with avg loss {avg_loss_pct:.1f}%. "
                    f"Conditions suggest avoiding similar setups."
                ),
                rationale=(
                    f"Extracted from {len(group_trades)} losing trades. "
                    f"Loss-weighted confidence: {base_confidence:.2f} "
                    f"(avg_loss={avg_loss_pct:.1f}%, severity={'critical' if avg_loss_pct > 5 else 'high' if avg_loss_pct > 3 else 'moderate'})"
                ),
            )
            loss_rules.append(rule)

            logger.info(
                "loss_lesson_extracted",
                group=group_key,
                loss_count=len(group_trades),
                avg_loss_pct=round(avg_loss_pct, 2),
                confidence=base_confidence,
            )

        return loss_rules

    @staticmethod
    def _infer_loss_conditions(trades: list[TradeRecord]) -> list[dict[str, Any]]:
        """Infer common conditions from losing trades.

        Analyzes entry timing, regime, and signal characteristics
        to build conditions that identify similar loss-prone setups.
        """
        conditions: list[dict[str, Any]] = []

        # Check for regime patterns
        regimes = [t.regime_at_entry for t in trades if t.regime_at_entry]
        if regimes:
            most_common_regime = max(set(regimes), key=regimes.count)
            if regimes.count(most_common_regime) >= len(trades) * 0.6:
                conditions.append({
                    "type": "regime_match",
                    "value": most_common_regime,
                })

        # Check for signal score patterns
        scores = [t.signal_score for t in trades if t.signal_score is not None]
        if scores:
            avg_score = sum(scores) / len(scores)
            if avg_score < 0.4:
                conditions.append({"type": "signal_score_below", "value": 0.4})

        # Check for volatility regime
        vol_regimes = [t.volatility_regime for t in trades if t.volatility_regime]
        if vol_regimes:
            most_common_vol = max(set(vol_regimes), key=vol_regimes.count)
            if vol_regimes.count(most_common_vol) >= len(trades) * 0.6:
                conditions.append({
                    "type": "volatility_regime_match",
                    "value": most_common_vol,
                })

        # Check for holding period patterns
        holding_periods = [t.holding_period_hours for t in trades if t.holding_period_hours]
        if holding_periods:
            avg_hold = sum(holding_periods) / len(holding_periods)
            if avg_hold > 48:
                conditions.append({"type": "holding_period_above", "value": 48})

        return conditions

    def _group_trades(self, trades: list[TradeRecord]) -> dict[str, list[TradeRecord]]:
        """Group trades by (symbol, strategy_id) for pattern analysis."""
        groups: dict[str, list[TradeRecord]] = {}
        for trade in trades:
            key = f"{trade.symbol}|{trade.strategy_id}"
            groups.setdefault(key, []).append(trade)
        return groups

    def _summarize_trades(
        self, winners: list[TradeRecord], losers: list[TradeRecord]
    ) -> dict[str, Any]:
        """Create a structured summary of trade groups for the LLM."""
        def _trade_to_summary(t: TradeRecord) -> dict[str, Any]:
            return {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_pct": t.realized_pnl_pct,
                "holding_hours": t.holding_period_hours,
                "regime": t.regime_at_entry,
                "signal_score": t.signal_score,
                "thesis": t.thesis,
                "confidence": t.confidence,
                "outcome_grade": t.outcome_grade,
                "max_favorable_excursion": t.max_favorable_excursion,
                "max_adverse_excursion": t.max_adverse_excursion,
                "volatility_regime": t.volatility_regime,
                "vix_level": t.vix_level,
            }

        # Sample losers for contrast (limit to 10 to keep prompt manageable)
        loser_sample = losers[:10]

        return {
            "winners": [_trade_to_summary(t) for t in winners],
            "losers": [_trade_to_summary(t) for t in loser_sample],
            "winner_count": len(winners),
            "loser_count": len(losers),
            "avg_winner_pnl_pct": (
                sum(t.realized_pnl_pct for t in winners) / len(winners) if winners else 0
            ),
            "avg_loser_pnl_pct": (
                sum(t.realized_pnl_pct for t in losers) / len(losers) if losers else 0
            ),
        }

    def _build_extraction_prompt(
        self, trade_summaries: dict[str, Any], group_key: str
    ) -> str:
        """Build the LLM prompt for rule extraction."""
        return get_prompt(
            "t3_shadow_rule_extraction",
            group_key=group_key,
            trade_data=json.dumps(trade_summaries, indent=2, default=str),
        )

    def _parse_rules(
        self, llm_output: str, source_trades: list[TradeRecord]
    ) -> list[TradingRule]:
        """Parse LLM JSON output into TradingRule objects."""
        try:
            data = json.loads(llm_output)
        except json.JSONDecodeError:
            logger.warning("shadow_extract_json_parse_failed", output=llm_output[:200])
            return []

        # Handle both {"rules": [...]} and [...] formats
        if isinstance(data, dict):
            raw_rules = data.get("rules", [])
        elif isinstance(data, list):
            raw_rules = data
        else:
            return []

        source_ids = [t.trade_id for t in source_trades]
        symbol = source_trades[0].symbol if source_trades else None
        strategy_id = source_trades[0].strategy_id if source_trades else None

        rules: list[TradingRule] = []
        for raw in raw_rules[:5]:  # Cap at 5 rules per group
            try:
                rule = TradingRule(
                    conditions=raw.get("conditions", []),
                    action=raw.get("action", "buy"),
                    confidence=min(max(float(raw.get("confidence", 0.5)), 0.0), 1.0),
                    source_trade_ids=source_ids,
                    symbol=symbol,
                    strategy_id=strategy_id,
                    regime=raw.get("regime"),
                    description=raw.get("description", ""),
                    rationale=raw.get("rationale", ""),
                )
                # Basic validation: must have at least one condition
                if rule.conditions:
                    rules.append(rule)
                else:
                    logger.warning("shadow_extract_rule_no_conditions", raw=raw)
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("shadow_extract_rule_parse_error", error=str(e), raw=raw)
                continue

        return rules
