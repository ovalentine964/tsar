"""
VMPM Entry Pipeline — Full 7-layer entry logic sequence.

Pipeline: News → Trend → S/R → Retest → RSI → Candlestick → Execute

Each layer produces a score 0.0 – 1.0. The final signal score is
a weighted combination of all layers. Only signals above the minimum
threshold are passed to RiskGuardian for execution.

Layer Weights (genome-tunable):
  - News/Fundamental:    0.10
  - Trend Direction:     0.25
  - S/R Mapping:         0.20
  - Price Retest:        0.15
  - RSI Confirmation:    0.15
  - Candlestick:         0.15
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.strategy.vmpm.candlestick_confirmer import CandlestickConfirmer, CandleResult
from src.strategy.vmpm.fundamental_analyzer import FundamentalAnalyzer, FundamentalBias
from src.strategy.vmpm.level_mapper import LevelMapper, MappedLevels, SRLevel
from src.strategy.vmpm.rsi_filter import RSIFilter, RSIResult
from src.strategy.vmpm.session_manager import SessionInfo, SessionManager
from src.strategy.vmpm.trend_detector import TrendDetector, TrendState

logger = logging.getLogger(__name__)


class PipelineStage(StrEnum):
    """Pipeline exit stage."""

    NEWS_GATE = "news_gate"
    TREND_GATE = "trend_gate"
    SR_GATE = "sr_gate"
    RETEST_GATE = "retest_gate"
    RSI_GATE = "rsi_gate"
    CANDLE_GATE = "candle_gate"
    EXECUTE = "execute"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PipelineResult:
    """Result of the full 7-layer entry pipeline."""

    stage_reached: PipelineStage
    passed: bool
    direction: str  # "buy", "sell", "none"
    entry_price: float
    stop_loss: float
    take_profit: float
    signal_score: float  # 0.0 – 1.0 weighted combination
    session: SessionInfo
    trend: TrendState
    levels: MappedLevels
    rsi: RSIResult
    candle: CandleResult
    fundamental: FundamentalBias
    layer_scores: dict[str, float]
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_reached": self.stage_reached.value,
            "passed": self.passed,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "signal_score": round(self.signal_score, 4),
            "session": self.session.to_dict() if hasattr(self.session, "to_dict") else str(self.session),
            "trend": self.trend.to_dict() if hasattr(self.trend, "to_dict") else str(self.trend),
            "rsi": self.rsi.to_dict(),
            "candle": self.candle.to_dict(),
            "fundamental": self.fundamental.value if hasattr(self.fundamental, "value") else str(self.fundamental),
            "layer_scores": {k: round(v, 3) for k, v in self.layer_scores.items()},
            "rejection_reason": self.rejection_reason,
        }


class EntryPipeline:
    """Full 7-layer entry pipeline for VMPM.

    Orchestrates: News → Trend → S/R → Retest → RSI → Candlestick → Execute

    Each layer acts as a gate. If a critical gate fails, the pipeline
    short-circuits and rejects the signal early.
    """

    DEFAULT_GENOME = {
        # Layer weights (must sum to 1.0)
        "weight_news": 0.10,
        "weight_trend": 0.25,
        "weight_sr": 0.20,
        "weight_retest": 0.15,
        "weight_rsi": 0.15,
        "weight_candle": 0.15,
        # Gate thresholds (minimum score to pass each layer)
        "min_trend_score": 0.3,
        "min_sr_score": 0.2,
        "min_retest_score": 0.3,
        "min_rsi_score": 0.2,
        "min_candle_score": 0.2,
        "min_total_score": 0.55,
        # Retest parameters
        "retest_atr_mult": 0.5,
        "retest_max_distance_pips": 50,
        # R:R
        "min_rr_ratio": 2.0,
        "default_rr_ratio": 2.5,
    }

    def __init__(
        self,
        genome: dict[str, Any] | None = None,
        session_manager: SessionManager | None = None,
        fundamental_analyzer: FundamentalAnalyzer | None = None,
        trend_detector: TrendDetector | None = None,
        level_mapper: LevelMapper | None = None,
        rsi_filter: RSIFilter | None = None,
        candlestick_confirmer: CandlestickConfirmer | None = None,
    ) -> None:
        self.genome = {**self.DEFAULT_GENOME, **(genome or {})}
        self.session_mgr = session_manager or SessionManager()
        self.fundamental = fundamental_analyzer or FundamentalAnalyzer()
        self.trend = trend_detector or TrendDetector()
        self.levels = level_mapper or LevelMapper()
        self.rsi = rsi_filter or RSIFilter()
        self.candlestick = candlestick_confirmer or CandlestickConfirmer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        symbol: str,
        ohlcv_by_tf: dict[str, list[list[float]]],
        closes: list[float],
        news_data: dict[str, Any] | None = None,
        key_levels: list[float] | None = None,
    ) -> PipelineResult:
        """Run the full 7-layer entry pipeline.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT")
            ohlcv_by_tf: OHLCV data keyed by timeframe ("D1", "H4", "H1")
            closes: H1 close prices (most recent)
            news_data: Optional news/fundamental data
            key_levels: Pre-computed S/R levels (optional, will compute if None)

        Returns:
            PipelineResult with signal or rejection.
        """
        layer_scores: dict[str, float] = {}
        current_price = closes[-1] if closes else 0.0

        # ── Layer 1: News / Fundamental ────────────────────────────────
        session = self.session_mgr.current_session()
        fundamental_bias = self.fundamental.analyze(news_data) if news_data else FundamentalBias.NEUTRAL

        if fundamental_bias == FundamentalBias.BEARISH_BIAS and news_data and news_data.get("high_impact_near"):
            return self._reject(
                PipelineStage.NEWS_GATE, current_price, session,
                "High-impact bearish news imminent",
            )

        news_score = self._score_fundamental(fundamental_bias)
        layer_scores["news"] = news_score

        # ── Layer 2: Trend Direction ───────────────────────────────────
        d1_closes = self._get_closes(ohlcv_by_tf, "D1", closes)
        h4_closes = self._get_closes(ohlcv_by_tf, "H4", closes)
        h1_closes = self._get_closes(ohlcv_by_tf, "H1", closes)

        trend_state = self.trend.analyze(d1_closes, h4_closes, h1_closes)

        if trend_state.direction.value == "neutral" and trend_state.strength < 0.3:
            return self._reject(
                PipelineStage.TREND_GATE, current_price, session,
                "No clear trend direction",
            )

        trend_score = trend_state.strength if trend_state.direction.value != "neutral" else 0.0
        if trend_state.alignment:
            trend_score = min(1.0, trend_score + 0.2)
        layer_scores["trend"] = trend_score

        # ── Layer 3: S/R Mapping ──────────────────────────────────────
        h1_ohlcv = ohlcv_by_tf.get("H1", [])
        sr_levels = self.levels.map_all(
            ohlc_h1=h1_ohlcv,
            ohlc_d1=ohlcv_by_tf.get("D1", []),
            ohlc_w1=ohlcv_by_tf.get("W1", []),
            swing_points=trend_state.swing_points if hasattr(trend_state, "swing_points") else [],
        )

        # Find nearest support and resistance
        nearest_support = self._find_nearest_level(sr_levels.supports, current_price, side="below")
        nearest_resistance = self._find_nearest_level(sr_levels.resistances, current_price, side="above")

        sr_score = self._score_sr_levels(sr_levels, current_price, trend_state)
        layer_scores["sr"] = sr_score

        if sr_score < self.genome["min_sr_score"]:
            return self._reject(
                PipelineStage.SR_GATE, current_price, session,
                "No strong S/R levels near price",
            )

        # ── Layer 4: Price Retest ─────────────────────────────────────
        direction, retest_score = self._check_retest(
            current_price, nearest_support, nearest_resistance, trend_state, h1_closes,
        )

        if retest_score < self.genome["min_retest_score"]:
            return self._reject(
                PipelineStage.RETEST_GATE, current_price, session,
                "Price not at a retest zone",
            )
        layer_scores["retest"] = retest_score

        # ── Layer 5: RSI Confirmation ─────────────────────────────────
        direction_hint = trend_state.direction.value
        rsi_result = self.rsi.analyze(closes, direction_hint)

        if rsi_result.score < self.genome["min_rsi_score"]:
            return self._reject(
                PipelineStage.RSI_GATE, current_price, session,
                f"RSI not confirming: {rsi_result.signal.value}",
            )
        layer_scores["rsi"] = rsi_result.score

        # ── Layer 6: Candlestick Confirmation ─────────────────────────
        all_levels = [l.price for l in sr_levels.supports + sr_levels.resistances]
        candle_result = self.candlestick.analyze(h1_ohlcv[-10:], all_levels, direction_hint)

        if candle_result.score < self.genome["min_candle_score"]:
            return self._reject(
                PipelineStage.CANDLE_GATE, current_price, session,
                f"No confirming candlestick pattern: {candle_result.pattern.value}",
            )
        layer_scores["candle"] = candle_result.score

        # ── Layer 7: Compute Final Score & Levels ─────────────────────
        total_score = self._compute_total_score(layer_scores)

        if total_score < self.genome["min_total_score"]:
            return self._reject(
                PipelineStage.CANDLE_GATE, current_price, session,
                f"Total score {total_score:.2f} below threshold {self.genome['min_total_score']}",
            )

        # Compute entry, SL, TP
        entry = current_price
        if direction == "buy":
            stop_loss = nearest_support.price * 0.998 if nearest_support else entry * 0.97
            risk = entry - stop_loss
            take_profit = entry + risk * self.genome["default_rr_ratio"]
        else:
            stop_loss = nearest_resistance.price * 1.002 if nearest_resistance else entry * 1.03
            risk = stop_loss - entry
            take_profit = entry - risk * self.genome["default_rr_ratio"]

        logger.info(
            "VMPM SIGNAL: %s %s @ %.2f SL=%.2f TP=%.2f score=%.3f",
            direction.upper(), symbol, entry, stop_loss, take_profit, total_score,
        )

        return PipelineResult(
            stage_reached=PipelineStage.EXECUTE,
            passed=True,
            direction=direction,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            signal_score=total_score,
            session=session,
            trend=trend_state,
            levels=sr_levels,
            rsi=rsi_result,
            candle=candle_result,
            fundamental=fundamental_bias,
            layer_scores=layer_scores,
        )

    def update_genome(self, new_genome: dict[str, Any]) -> None:
        """Update genome parameters (from StrategyGeneticist)."""
        self.genome.update(new_genome)
        # Propagate to sub-components
        self.rsi.update_genome(new_genome)
        self.candlestick.update_genome(new_genome)
        self.trend.update_genome(new_genome)
        self.levels.update_genome(new_genome)
        logger.info("Entry pipeline genome updated")

    # ------------------------------------------------------------------
    # Internal Scoring
    # ------------------------------------------------------------------

    def _score_fundamental(self, bias: FundamentalBias) -> float:
        """Score fundamental bias layer."""
        scores = {
            FundamentalBias.BULLISH_BIAS: 0.8,
            FundamentalBias.BEARISH_BIAS: 0.8,
            FundamentalBias.NEUTRAL: 0.5,
        }
        return scores.get(bias, 0.5)

    def _score_sr_levels(
        self, levels: MappedLevels, price: float, trend: TrendState,
    ) -> float:
        """Score S/R level quality."""
        if not levels.supports and not levels.resistances:
            return 0.0

        # Count strong levels near price
        strong_near = 0
        for level in levels.supports + levels.resistances:
            if abs(level.price - price) / price < 0.02:  # Within 2%
                if level.strength >= 0.7:
                    strong_near += 1

        # Multiple strong levels near price = confluence
        if strong_near >= 3:
            return 1.0
        elif strong_near >= 2:
            return 0.7
        elif strong_near >= 1:
            return 0.4
        return 0.2

    def _check_retest(
        self,
        price: float,
        nearest_support: SRLevel | None,
        nearest_resistance: SRLevel | None,
        trend: TrendState,
        closes: list[float],
    ) -> tuple[str, float]:
        """Check if price is retesting a key level."""
        if not nearest_support and not nearest_resistance:
            return "none", 0.0

        # Calculate ATR for proximity threshold
        atr = self._calculate_atr(closes, period=14)
        threshold = atr * self.genome["retest_atr_mult"]

        # Buy setup: bullish trend + price near support
        if trend.direction.value == "bullish" and nearest_support:
            distance = abs(price - nearest_support.price)
            if distance <= threshold:
                # Score based on level strength and proximity
                proximity_score = 1.0 - (distance / threshold)
                level_score = nearest_support.strength
                return "buy", (proximity_score + level_score) / 2

        # Sell setup: bearish trend + price near resistance
        if trend.direction.value == "bearish" and nearest_resistance:
            distance = abs(price - nearest_resistance.price)
            if distance <= threshold:
                proximity_score = 1.0 - (distance / threshold)
                level_score = nearest_resistance.strength
                return "sell", (proximity_score + level_score) / 2

        return "none", 0.0

    def _compute_total_score(self, layer_scores: dict[str, float]) -> float:
        """Compute weighted total score from all layers."""
        w = self.genome
        total = (
            layer_scores.get("news", 0.5) * w["weight_news"]
            + layer_scores.get("trend", 0.0) * w["weight_trend"]
            + layer_scores.get("sr", 0.0) * w["weight_sr"]
            + layer_scores.get("retest", 0.0) * w["weight_retest"]
            + layer_scores.get("rsi", 0.0) * w["weight_rsi"]
            + layer_scores.get("candle", 0.0) * w["weight_candle"]
        )
        return min(1.0, total)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_nearest_level(
        self, levels: list[SRLevel], price: float, side: str,
    ) -> SRLevel | None:
        """Find nearest level above or below price."""
        if not levels:
            return None

        if side == "below":
            candidates = [l for l in levels if l.price <= price]
        else:
            candidates = [l for l in levels if l.price >= price]

        if not candidates:
            return None

        return min(candidates, key=lambda l: abs(l.price - price))

    @staticmethod
    def _get_closes(
        ohlcv_by_tf: dict[str, list[list[float]]], tf: str, fallback: list[float],
    ) -> list[float]:
        """Extract closes for a timeframe, falling back to H1."""
        data = ohlcv_by_tf.get(tf, [])
        if data:
            return [c[3] for c in data]  # close is index 3
        return fallback

    @staticmethod
    def _calculate_atr(closes: list[float], period: int = 14) -> float:
        """Simple ATR approximation from closes."""
        if len(closes) < period + 1:
            return 0.0
        changes = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        return sum(changes[-period:]) / period

    def _reject(
        self,
        stage: PipelineStage,
        price: float,
        session: SessionInfo,
        reason: str,
    ) -> PipelineResult:
        """Create a rejection result."""
        logger.debug("VMPM rejected at %s: %s", stage.value, reason)
        return PipelineResult(
            stage_reached=stage,
            passed=False,
            direction="none",
            entry_price=price,
            stop_loss=0.0,
            take_profit=0.0,
            signal_score=0.0,
            session=session,
            trend=TrendState(
                direction="neutral", alignment=False, strength=0.0,
                timeframes={}, swing_points=[],
            ),
            levels=MappedLevels(supports=[], resistances=[], metadata={}),
            rsi=RSIResult(
                value=50.0, state="neutral", signal="neutral",
                prev_value=50.0, crossing_up=False, crossing_down=False,
                divergence=None, score=0.0,
            ),
            candle=CandleResult(
                pattern="none", direction="neutral", score=0.0,
                at_key_level=False, body_ratio=0.0, wick_ratio=0.0,
            ),
            fundamental=FundamentalBias.NEUTRAL,
            layer_scores={},
            rejection_reason=reason,
        )
