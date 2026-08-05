"""
VMPM Entry Pipeline — Full entry logic sequence.

Pipeline stages (in order):
  1. News Gate      — No high-impact news in blackout window
  2. Trend Align    — D1/H4/H1 MAs agree on direction
  3. S/R Proximity  — Price at a mapped S/R level
  4. Retest         — Price retests the level with rejection candle
  5. RSI Filter     — RSI supports direction (not overextended)
  6. Candlestick    — Reversal/continuation pattern present
  7. Execute        — All stages passed → generate signal

Each stage produces a score. The pipeline aggregates them into
a final score using configured weights. If any critical stage
fails, the pipeline short-circuits (no signal).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.strategy.vmpm.fundamental_analyzer import FundamentalBias, BiasDirection
from src.strategy.vmpm.trend_detector import TrendState, TrendDirection
from src.strategy.vmpm.level_mapper import (
    MappedLevels,
    SRLevel,
    LevelSide,
)

logger = logging.getLogger(__name__)


class PipelineStage(StrEnum):
    """Pipeline stages."""

    NEWS_GATE = "news_gate"
    TREND_ALIGN = "trend_align"
    SR_PROXIMITY = "sr_proximity"
    RETEST = "retest"
    RSI_FILTER = "rsi_filter"
    CANDLESTICK = "candlestick"
    EXECUTE = "execute"


class CandlePattern(StrEnum):
    """Recognized candlestick patterns."""

    BULLISH_ENGULFING = "bullish_engulfing"
    BEARISH_ENGULFING = "bearish_engulfing"
    BULLISH_PIN_BAR = "bullish_pin_bar"
    BEARISH_PIN_BAR = "bearish_pin_bar"
    MORNING_STAR = "morning_star"
    EVENING_STAR = "evening_star"
    INSIDE_BAR_BREAKOUT = "inside_bar_breakout"
    NONE = "none"


@dataclass(frozen=True)
class StageResult:
    """Result of a single pipeline stage."""

    stage: PipelineStage
    passed: bool
    score: float  # 0.0 – 1.0
    reasoning: str


@dataclass(frozen=True)
class PipelineResult:
    """Complete pipeline evaluation result."""

    passed: bool
    total_score: float
    side: str  # "buy" or "sell" or "none"
    stages: tuple[StageResult, ...]
    entry_price: float
    stop_loss: float
    take_profit: float
    nearest_level: SRLevel | None
    candle_pattern: CandlePattern
    session_score: float
    reasoning: str


class EntryPipeline:
    """Full VMPM entry pipeline.

    Evaluates all stages in sequence. Short-circuits on critical
    failures (news gate, trend alignment). Returns a PipelineResult
    with scores, levels, and trade parameters.

    Usage::

        pipeline = EntryPipeline(config)
        result = pipeline.evaluate(
            current_price=1.0850,
            fundamental_bias=bias,
            trend_state=trend,
            mapped_levels=levels,
            ohlcv=h1_bars,
            rsi=42.0,
            session_score=1.5,
        )
        if result.passed and result.total_score >= 0.70:
            # Valid signal — proceed to execution
    """

    # Pipeline stage weights (must sum to 1.0)
    _STAGE_WEIGHTS: dict[PipelineStage, float] = {
        PipelineStage.NEWS_GATE: 0.10,
        PipelineStage.TREND_ALIGN: 0.25,
        PipelineStage.SR_PROXIMITY: 0.20,
        PipelineStage.RETEST: 0.15,
        PipelineStage.RSI_FILTER: 0.15,
        PipelineStage.CANDLESTICK: 0.15,
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

        # Load weights from config entry_rules if available
        entry_rules = self._config.get("entry_rules", {})
        pipeline_stages = entry_rules.get("pipeline", [])
        if pipeline_stages:
            for stage_cfg in pipeline_stages:
                stage_name = stage_cfg.get("stage", "")
                weight = stage_cfg.get("weight")
                try:
                    stage = PipelineStage(stage_name)
                    if weight is not None:
                        self._STAGE_WEIGHTS[stage] = weight
                except ValueError:
                    pass

        self._min_score = entry_rules.get("min_signal_score", 0.70)

        # Technical params
        rsi_cfg = self._config.get("technical", {}).get("rsi", {})
        self._rsi_period = rsi_cfg.get("period", 14)
        self._rsi_oversold = rsi_cfg.get("oversold", 30)
        self._rsi_overbought = rsi_cfg.get("overbought", 70)
        self._rsi_long_range = rsi_cfg.get("long_range", [30, 55])
        self._rsi_short_range = rsi_cfg.get("short_range", [45, 70])

        # ATR params
        atr_cfg = self._config.get("technical", {}).get("atr", {})
        self._atr_buffer_mult = atr_cfg.get("period", 14)

        # Mutable params
        mutable = self._config.get("mutable_parameters", {})
        self._sr_proximity_pct = mutable.get("sr_proximity_pct", {}).get("current", 0.3)
        self._retest_candles = mutable.get("retest_candles", {}).get("current", 3)
        self._atr_buffer_mult = mutable.get("atr_buffer_mult", {}).get("current", 0.5)
        self._min_rr_ratio = mutable.get("min_rr_ratio", {}).get("current", 2.0)
        self._trailing_atr_mult = mutable.get("trailing_stop_atr_mult", {}).get("current", 1.5)

    def evaluate(
        self,
        current_price: float,
        fundamental_bias: FundamentalBias,
        trend_state: TrendState,
        mapped_levels: MappedLevels,
        ohlcv: list[dict[str, float]],
        rsi: float,
        atr: float,
        session_score: float = 1.0,
        volume_ratio: float = 1.0,
    ) -> PipelineResult:
        """Run the full VMPM entry pipeline.

        Args:
            current_price: Current market price.
            fundamental_bias: Output from FundamentalAnalyzer.
            trend_state: Output from TrendDetector.
            mapped_levels: Output from LevelMapper.
            ohlcv: Recent H1 OHLCV bars.
            rsi: Current RSI value.
            atr: Current ATR value.
            session_score: Session multiplier from SessionManager.
            volume_ratio: Volume / average volume.

        Returns:
            PipelineResult with pass/fail, scores, and trade params.
        """
        stages: list[StageResult] = []
        failed_critical = False

        # -- Stage 1: News Gate --
        news_result = self._stage_news_gate(fundamental_bias)
        stages.append(news_result)
        if not news_result.passed:
            failed_critical = True

        # -- Stage 2: Trend Alignment --
        trend_result = self._stage_trend_align(trend_state)
        stages.append(trend_result)
        if not trend_result.passed:
            failed_critical = True

        # Short-circuit on critical failures
        if failed_critical:
            return self._build_result(
                passed=False, stages=stages, side="none",
                current_price=current_price, atr=atr,
                session_score=session_score,
                reasoning="Pipeline failed at critical stage",
            )

        # Determine direction from trend
        side = "buy" if trend_state.direction == TrendDirection.BULLISH else "sell"

        # -- Stage 3: S/R Proximity --
        sr_result, nearest_level = self._stage_sr_proximity(
            current_price, mapped_levels, side
        )
        stages.append(sr_result)

        # -- Stage 4: Retest Confirmation --
        retest_result = self._stage_retest(
            ohlcv, current_price, nearest_level, side
        )
        stages.append(retest_result)

        # -- Stage 5: RSI Filter --
        rsi_result = self._stage_rsi_filter(rsi, side)
        stages.append(rsi_result)

        # -- Stage 6: Candlestick Pattern --
        candle_result, pattern = self._stage_candlestick(ohlcv, side)
        stages.append(candle_result)

        # -- Aggregate scores --
        total_score = self._aggregate_scores(stages)
        total_score *= session_score  # Apply session multiplier
        total_score = min(1.0, total_score)

        passed = (
            total_score >= self._min_score
            and all(s.passed for s in stages)
        )

        # -- Calculate trade parameters --
        entry_price = current_price
        stop_loss, take_profit = self._calculate_levels(
            current_price, atr, side, nearest_level
        )

        # Validate R:R
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        if risk > 0 and reward / risk < self._min_rr_ratio:
            passed = False
            stages = list(stages)
            stages.append(StageResult(
                stage=PipelineStage.EXECUTE,
                passed=False,
                score=0.0,
                reasoning=f"R:R {reward/risk:.2f} < {self._min_rr_ratio}",
            ))

        reasoning_parts = [s.reasoning for s in stages if s.passed]
        reasoning = " | ".join(reasoning_parts)

        return self._build_result(
            passed=passed, stages=stages, side=side if passed else "none",
            current_price=current_price, atr=atr,
            session_score=session_score,
            nearest_level=nearest_level,
            candle_pattern=pattern,
            stop_loss=stop_loss, take_profit=take_profit,
            reasoning=reasoning,
        )

    # -- Pipeline Stages --

    def _stage_news_gate(self, bias: FundamentalBias) -> StageResult:
        """Stage 1: News gate — no high-impact news in blackout window."""
        weight = self._STAGE_WEIGHTS[PipelineStage.NEWS_GATE]

        if bias.blackout_active:
            return StageResult(
                stage=PipelineStage.NEWS_GATE,
                passed=False,
                score=0.0,
                reasoning=f"BLOCKED: {bias.blackout_reason}",
            )

        score = (1.0 - bias.event_risk_score) * weight
        return StageResult(
            stage=PipelineStage.NEWS_GATE,
            passed=True,
            score=score,
            reasoning=f"news_clear (risk={bias.event_risk_score:.2f})",
        )

    def _stage_trend_align(self, trend: TrendState) -> StageResult:
        """Stage 2: Trend alignment across D1/H4/H1."""
        weight = self._STAGE_WEIGHTS[PipelineStage.TREND_ALIGN]

        if trend.direction == TrendDirection.NEUTRAL:
            return StageResult(
                stage=PipelineStage.TREND_ALIGN,
                passed=False,
                score=0.0,
                reasoning="REJECTED: trend neutral",
            )

        score = trend.confluence_score * weight
        if trend.aligned:
            score *= 1.1

        score = min(weight, score)

        return StageResult(
            stage=PipelineStage.TREND_ALIGN,
            passed=True,
            score=score,
            reasoning=f"trend={trend.direction.value} aligned={trend.aligned} conf={trend.confluence_score:.2f}",
        )

    def _stage_sr_proximity(
        self,
        price: float,
        levels: MappedLevels,
        side: str,
    ) -> tuple[StageResult, SRLevel | None]:
        """Stage 3: Price near a mapped S/R level."""
        weight = self._STAGE_WEIGHTS[PipelineStage.SR_PROXIMITY]

        if side == "buy":
            target_levels = levels.supports
        else:
            target_levels = levels.resistances

        nearest: SRLevel | None = None
        best_dist = float("inf")

        for level in target_levels:
            dist_pct = abs(price - level.price) / level.price * 100
            if dist_pct <= self._sr_proximity_pct and dist_pct < best_dist:
                best_dist = dist_pct
                nearest = level

        if nearest is None:
            return StageResult(
                stage=PipelineStage.SR_PROXIMITY,
                passed=False,
                score=0.0,
                reasoning=f"REJECTED: no {'support' if side == 'buy' else 'resistance'} within {self._sr_proximity_pct}%",
            ), None

        proximity_score = 1.0 - (best_dist / self._sr_proximity_pct)
        level_strength = nearest.strength
        score = (proximity_score * 0.6 + level_strength * 0.4) * weight

        return StageResult(
            stage=PipelineStage.SR_PROXIMITY,
            passed=True,
            score=score,
            reasoning=f"near {nearest.level_type.value} @ {nearest.price:.5f} (dist={best_dist:.3f}%)",
        ), nearest

    def _stage_retest(
        self,
        ohlcv: list[dict[str, float]],
        price: float,
        level: SRLevel | None,
        side: str,
    ) -> StageResult:
        """Stage 4: Retest confirmation — price retests level with rejection."""
        weight = self._STAGE_WEIGHTS[PipelineStage.RETEST]

        if level is None or len(ohlcv) < self._retest_candles:
            return StageResult(
                stage=PipelineStage.RETEST,
                passed=False,
                score=0.0,
                reasoning="REJECTED: insufficient data for retest",
            )

        recent = ohlcv[-self._retest_candles:]
        level_price = level.price
        zone_buffer = level_price * 0.001

        if side == "buy":
            touched = any(
                bar["low"] <= level_price + zone_buffer
                for bar in recent
            )
            rejected = ohlcv[-1]["close"] > level_price
            last = ohlcv[-1]
            body_low = min(last["open"], last["close"])
            wick_low = body_low - last["low"]
            candle_range = last["high"] - last["low"]
            has_wick = candle_range > 0 and wick_low / candle_range > 0.3
        else:
            touched = any(
                bar["high"] >= level_price - zone_buffer
                for bar in recent
            )
            rejected = ohlcv[-1]["close"] < level_price
            last = ohlcv[-1]
            body_high = max(last["open"], last["close"])
            wick_high = last["high"] - body_high
            candle_range = last["high"] - last["low"]
            has_wick = candle_range > 0 and wick_high / candle_range > 0.3

        if not touched:
            return StageResult(
                stage=PipelineStage.RETEST,
                passed=False,
                score=0.0,
                reasoning=f"REJECTED: no retest of {level.level_type.value}",
            )

        score = 0.0
        if touched:
            score += 0.4
        if rejected:
            score += 0.3
        if has_wick:
            score += 0.3

        score *= weight

        return StageResult(
            stage=PipelineStage.RETEST,
            passed=(touched and rejected),
            score=score,
            reasoning=f"retest={'yes' if touched else 'no'} reject={'yes' if rejected else 'no'} wick={'yes' if has_wick else 'no'}",
        )

    def _stage_rsi_filter(self, rsi: float, side: str) -> StageResult:
        """Stage 5: RSI filter — RSI supports direction, not overextended."""
        weight = self._STAGE_WEIGHTS[PipelineStage.RSI_FILTER]

        if side == "buy":
            rsi_min, rsi_max = self._rsi_long_range
            if rsi > self._rsi_overbought:
                return StageResult(
                    stage=PipelineStage.RSI_FILTER,
                    passed=False,
                    score=0.0,
                    reasoning=f"REJECTED: RSI {rsi:.1f} > {self._rsi_overbought} (overbought for long)",
                )
            if rsi_min <= rsi <= rsi_max:
                score = (1.0 - (rsi - rsi_min) / (rsi_max - rsi_min)) * weight
            elif rsi < rsi_min:
                score = weight
            else:
                score = weight * 0.3
        else:
            rsi_min, rsi_max = self._rsi_short_range
            if rsi < self._rsi_oversold:
                return StageResult(
                    stage=PipelineStage.RSI_FILTER,
                    passed=False,
                    score=0.0,
                    reasoning=f"REJECTED: RSI {rsi:.1f} < {self._rsi_oversold} (oversold for short)",
                )
            if rsi_min <= rsi <= rsi_max:
                score = ((rsi - rsi_min) / (rsi_max - rsi_min)) * weight
            elif rsi > rsi_max:
                score = weight
            else:
                score = weight * 0.3

        return StageResult(
            stage=PipelineStage.RSI_FILTER,
            passed=True,
            score=score,
            reasoning=f"RSI={rsi:.1f} ({side} range ok)",
        )

    def _stage_candlestick(
        self,
        ohlcv: list[dict[str, float]],
        side: str,
    ) -> tuple[StageResult, CandlePattern]:
        """Stage 6: Candlestick pattern recognition."""
        weight = self._STAGE_WEIGHTS[PipelineStage.CANDLESTICK]

        if len(ohlcv) < 3:
            return StageResult(
                stage=PipelineStage.CANDLESTICK,
                passed=False,
                score=0.0,
                reasoning="REJECTED: insufficient candles",
            ), CandlePattern.NONE

        pattern = CandlePattern.NONE
        confidence = 0.0

        if side == "buy":
            pattern, confidence = self._detect_bullish_patterns(ohlcv)
        else:
            pattern, confidence = self._detect_bearish_patterns(ohlcv)

        if pattern == CandlePattern.NONE:
            return StageResult(
                stage=PipelineStage.CANDLESTICK,
                passed=False,
                score=0.0,
                reasoning="REJECTED: no candlestick pattern",
            ), CandlePattern.NONE

        score = confidence * weight

        return StageResult(
            stage=PipelineStage.CANDLESTICK,
            passed=True,
            score=score,
            reasoning=f"pattern={pattern.value} conf={confidence:.2f}",
        ), pattern

    # -- Pattern Detection --

    def _detect_bullish_patterns(
        self, ohlcv: list[dict[str, float]]
    ) -> tuple[CandlePattern, float]:
        """Detect bullish candlestick patterns."""
        curr = ohlcv[-1]
        prev = ohlcv[-2]
        prev2 = ohlcv[-3] if len(ohlcv) >= 3 else None

        curr_body = abs(curr["close"] - curr["open"])
        prev_body = abs(prev["close"] - prev["open"])
        curr_range = curr["high"] - curr["low"]

        if curr_range == 0:
            return CandlePattern.NONE, 0.0

        # Bullish Engulfing
        is_prev_bearish = prev["close"] < prev["open"]
        is_curr_bullish = curr["close"] > curr["open"]
        if (is_prev_bearish and is_curr_bullish and
                curr_body > prev_body and
                curr["close"] > prev["open"] and
                curr["open"] < prev["close"]):
            return CandlePattern.BULLISH_ENGULFING, 0.85

        # Bullish Pin Bar
        body_low = min(curr["open"], curr["close"])
        lower_wick = body_low - curr["low"]
        upper_wick = curr["high"] - max(curr["open"], curr["close"])
        if (lower_wick > curr_body * 2 and
                upper_wick < curr_body * 0.5 and
                curr["close"] > curr["open"]):
            return CandlePattern.BULLISH_PIN_BAR, 0.75

        # Morning Star
        if prev2 is not None:
            prev2_body = abs(prev2["close"] - prev2["open"])
            is_prev2_bearish = prev2["close"] < prev2["open"]
            is_prev_small = prev_body < prev2_body * 0.3
            is_curr_bullish_ms = curr["close"] > curr["open"]

            if is_prev2_bearish and is_prev_small and is_curr_bullish_ms:
                mid_prev2 = (prev2["open"] + prev2["close"]) / 2
                if curr["close"] > mid_prev2:
                    return CandlePattern.MORNING_STAR, 0.80

        return CandlePattern.NONE, 0.0

    def _detect_bearish_patterns(
        self, ohlcv: list[dict[str, float]]
    ) -> tuple[CandlePattern, float]:
        """Detect bearish candlestick patterns."""
        curr = ohlcv[-1]
        prev = ohlcv[-2]
        prev2 = ohlcv[-3] if len(ohlcv) >= 3 else None

        curr_body = abs(curr["close"] - curr["open"])
        prev_body = abs(prev["close"] - prev["open"])
        curr_range = curr["high"] - curr["low"]

        if curr_range == 0:
            return CandlePattern.NONE, 0.0

        # Bearish Engulfing
        is_prev_bullish = prev["close"] > prev["open"]
        is_curr_bearish = curr["close"] < curr["open"]
        if (is_prev_bullish and is_curr_bearish and
                curr_body > prev_body and
                curr["close"] < prev["open"] and
                curr["open"] > prev["close"]):
            return CandlePattern.BEARISH_ENGULFING, 0.85

        # Bearish Pin Bar
        body_high = max(curr["open"], curr["close"])
        upper_wick = curr["high"] - body_high
        lower_wick = min(curr["open"], curr["close"]) - curr["low"]
        if (upper_wick > curr_body * 2 and
                lower_wick < curr_body * 0.5 and
                curr["close"] < curr["open"]):
            return CandlePattern.BEARISH_PIN_BAR, 0.75

        # Evening Star
        if prev2 is not None:
            prev2_body = abs(prev2["close"] - prev2["open"])
            is_prev2_bullish = prev2["close"] > prev2["open"]
            is_prev_small = prev_body < prev2_body * 0.3
            is_curr_bearish_es = curr["close"] < curr["open"]

            if is_prev2_bullish and is_prev_small and is_curr_bearish_es:
                mid_prev2 = (prev2["open"] + prev2["close"]) / 2
                if curr["close"] < mid_prev2:
                    return CandlePattern.EVENING_STAR, 0.80

        return CandlePattern.NONE, 0.0

    # -- Helpers --

    def _aggregate_scores(self, stages: list[StageResult]) -> float:
        """Aggregate stage scores into a total pipeline score."""
        total = sum(s.score for s in stages)
        max_possible = sum(self._STAGE_WEIGHTS.values())
        if max_possible > 0:
            return total / max_possible
        return 0.0

    def _calculate_levels(
        self,
        price: float,
        atr: float,
        side: str,
        level: SRLevel | None,
    ) -> tuple[float, float]:
        """Calculate stop-loss and take-profit levels."""
        if side == "buy":
            if level is not None:
                stop_loss = level.price - (atr * self._atr_buffer_mult)
            else:
                stop_loss = price - (atr * self._atr_buffer_mult * 2)
            stop_loss = min(stop_loss, price - (atr * 0.5))
            risk = price - stop_loss
            take_profit = price + (risk * self._min_rr_ratio)
        else:
            if level is not None:
                stop_loss = level.price + (atr * self._atr_buffer_mult)
            else:
                stop_loss = price + (atr * self._atr_buffer_mult * 2)
            stop_loss = max(stop_loss, price + (atr * 0.5))
            risk = stop_loss - price
            take_profit = price - (risk * self._min_rr_ratio)

        return round(stop_loss, 5), round(take_profit, 5)

    def _build_result(
        self,
        passed: bool,
        stages: list[StageResult],
        side: str,
        current_price: float,
        atr: float,
        session_score: float,
        reasoning: str,
        nearest_level: SRLevel | None = None,
        candle_pattern: CandlePattern = CandlePattern.NONE,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> PipelineResult:
        """Build a PipelineResult."""
        total_score = self._aggregate_scores(stages) * session_score
        total_score = min(1.0, total_score)

        return PipelineResult(
            passed=passed,
            total_score=total_score,
            side=side,
            stages=tuple(stages),
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            nearest_level=nearest_level,
            candle_pattern=candle_pattern,
            session_score=session_score,
            reasoning=reasoning,
        )
