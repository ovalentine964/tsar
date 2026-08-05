"""
Signal Quality Filter — Multi-factor signal scoring and filtering.

The probability gate between SignalScout and RiskGuardian.
Every signal passes through 7-factor scoring before execution is considered.

Target: ≥75% win rate. $10 account. No room for garbage signals.

Architecture:
  SignalScout → [SQF] → RiskGuardian → ExecutionSniper

7 Factors:
  1. RSI Confirmation (0.15)
  2. S/R Proximity (0.20)
  3. Volume Confirmation (0.15)
  4. Trend Alignment / MTF (0.15)
  5. Regime Filter (0.15)
  6. Sentiment Alignment (0.10)
  7. On-Chain Confirmation (0.10)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from src.agents.adaptive_filter import AdaptiveFilter
from src.agents.base import BaseAgent
from src.agents.false_signal_detectors import (
    FalseSignalDetector,
)
from src.agents.signal_quality_db import SignalQualityDB

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FactorWeights:
    """Signal quality factor weights — must sum to 1.0."""

    rsi_confirmation: float = 0.15
    sr_proximity: float = 0.20
    volume_confirmation: float = 0.15
    trend_alignment: float = 0.15
    regime_filter: float = 0.15
    sentiment_alignment: float = 0.10
    onchain_confirmation: float = 0.10

    def validate(self) -> None:
        total = (
            self.rsi_confirmation
            + self.sr_proximity
            + self.volume_confirmation
            + self.trend_alignment
            + self.regime_filter
            + self.sentiment_alignment
            + self.onchain_confirmation
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Factor weights must sum to 1.0, got {total:.4f}")

    def as_dict(self) -> dict[str, float]:
        return {
            "rsi_confirmation": self.rsi_confirmation,
            "sr_proximity": self.sr_proximity,
            "volume_confirmation": self.volume_confirmation,
            "trend_alignment": self.trend_alignment,
            "regime_filter": self.regime_filter,
            "sentiment_alignment": self.sentiment_alignment,
            "onchain_confirmation": self.onchain_confirmation,
        }


class PositionTier(StrEnum):
    """Position sizing tier based on signal quality score."""

    NO_TRADE = "no_trade"
    SMALL = "small"  # 50% of normal
    NORMAL = "normal"  # 100%
    LARGE = "large"  # 150%


@dataclass(frozen=True)
class SQFConfig:
    """Signal Quality Filter configuration."""

    enabled: bool = True

    # Scoring weights
    weights: FactorWeights = FactorWeights()

    # Score thresholds
    no_trade_threshold: float = 0.60
    small_position_threshold: float = 0.70
    normal_position_threshold: float = 0.80

    # Confirmation requirements
    min_factors: int = 3
    min_factor_score: float = 0.3
    regime_must_be_favorable: bool = True
    volume_must_confirm: bool = True

    # Cold start (first N trades require extra confidence)
    cold_start_trades: int = 20
    cold_start_min_score: float = 0.65

    # $10 account protections
    max_concurrent_positions: int = 2
    max_spread_pct: float = 0.3
    min_rr_after_fees: float = 1.5
    taker_fee_pct: float = 0.1

    # Trading hour restrictions (UTC)
    low_liquidity_hours: tuple[int, ...] = (0, 1, 2, 3, 4)
    restrict_weekend_altcoins: bool = True


@dataclass(frozen=True)
class FactorScore:
    """Score for a single quality factor."""

    name: str
    score: float  # [0, 1]
    weight: float
    weighted: float  # score × weight
    reason: str = ""
    confirmed: bool = False  # score > min_factor_score


@dataclass(frozen=True)
class QualityAssessment:
    """Complete quality assessment of a signal."""

    signal_id: str
    symbol: str
    side: str

    # Factor scores
    factors: tuple[FactorScore, ...]
    composite_score: float
    factors_confirmed: int

    # Decision
    tier: PositionTier
    position_size_factor: float  # 0, 0.5, 1.0, or 1.5
    approved: bool

    # Rejection reasons (empty if approved)
    rejection_reasons: tuple[str, ...]

    # False signal flags
    false_signal_flags: tuple[str, ...]

    # Metadata
    regime: str = "unknown"
    adaptive_state: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""


# ═══════════════════════════════════════════════════════════════════════
# FACTOR SCORERS
# ═══════════════════════════════════════════════════════════════════════


class FactorScorer:
    """Computes individual factor scores for signal quality assessment.

    Each method takes market data and returns a score in [0, 1].
    All logic is deterministic — no LLM calls.
    """

    @staticmethod
    def score_rsi_confirmation(
        rsi: float,
        side: str,
        volume_ratio: float,
        params: dict[str, Any],
    ) -> tuple[float, str]:
        """Factor 1: RSI Confirmation with Volume.

        RSI oversold/overbought alone is weak. RSI + volume spike = strong.

        Returns (score, reason).
        """
        oversold = params.get("rsi_oversold", 30)
        overbought = params.get("rsi_overbought", 70)

        if side == "buy":
            # More oversold = higher base score
            if rsi >= oversold:
                return 0.0, f"RSI {rsi:.1f} not oversold (threshold {oversold})"
            rsi_extremity = (oversold - rsi) / oversold  # 0→1 as RSI goes 30→0
        else:
            if rsi <= overbought:
                return 0.0, f"RSI {rsi:.1f} not overbought (threshold {overbought})"
            rsi_extremity = (rsi - overbought) / (100 - overbought)

        # Volume multiplier: RSI signal without volume is weak
        if volume_ratio >= 1.5:
            vol_bonus = 1.0
        elif volume_ratio >= 1.2:
            vol_bonus = 0.7
        elif volume_ratio >= 1.0:
            vol_bonus = 0.4
        else:
            vol_bonus = 0.1  # RSI alone, no volume = very weak

        score = min(1.0, rsi_extremity * 0.6 + vol_bonus * 0.4)
        reason = (
            f"RSI={rsi:.1f} ({'oversold' if side == 'buy' else 'overbought'}), "
            f"vol_ratio={volume_ratio:.2f}, score={score:.3f}"
        )
        return score, reason

    @staticmethod
    def score_sr_proximity(
        current_price: float,
        nearest_level_price: float | None,
        nearest_level_strength: float,
        proximity_pct_threshold: float = 2.0,
    ) -> tuple[float, str]:
        """Factor 2: Support/Resistance Proximity.

        Closer to key level = higher score. Within 2% = full score.
        Linear decay to 0 at 5%.
        """
        if nearest_level_price is None or nearest_level_price <= 0:
            return 0.0, "No S/R level detected"

        proximity_pct = abs(current_price - nearest_level_price) / current_price * 100

        if proximity_pct <= proximity_pct_threshold:
            # Within threshold — score based on proximity and strength
            proximity_score = 1.0 - (proximity_pct / proximity_pct_threshold)
            score = proximity_score * 0.6 + nearest_level_strength * 0.4
        elif proximity_pct <= 5.0:
            # Linear decay from threshold to 5%
            decay = 1.0 - (proximity_pct - proximity_pct_threshold) / (
                5.0 - proximity_pct_threshold
            )
            score = decay * 0.3 * nearest_level_strength
        else:
            score = 0.0

        score = max(0.0, min(1.0, score))
        reason = (
            f"Nearest level={nearest_level_price:.2f}, "
            f"proximity={proximity_pct:.2f}%, strength={nearest_level_strength:.2f}"
        )
        return score, reason

    @staticmethod
    def score_volume_confirmation(
        current_volume: float,
        avg_volume: float,
    ) -> tuple[float, str]:
        """Factor 3: Volume Confirmation.

        Volume above average confirms price action.
        >1.5x = full score. <1.0x = zero score.
        """
        if avg_volume <= 0:
            return 0.0, "No volume data"

        ratio = current_volume / avg_volume

        if ratio >= 2.0:
            score = 1.0
        elif ratio >= 1.5:
            score = 0.8 + (ratio - 1.5) * 0.4  # 0.8→1.0
        elif ratio >= 1.2:
            score = 0.5 + (ratio - 1.2) * 1.0  # 0.5→0.8
        elif ratio >= 1.0:
            score = 0.2 + (ratio - 1.0) * 1.5  # 0.2→0.5
        elif ratio >= 0.5:
            score = ratio * 0.4  # 0→0.2
        else:
            score = 0.0

        score = max(0.0, min(1.0, score))
        reason = f"vol_ratio={ratio:.2f} ({current_volume:.0f}/{avg_volume:.0f})"
        return score, reason

    @staticmethod
    def score_trend_alignment(
        mtf_confluence: float,
        ema_aligned: bool,
        macd_aligned: bool,
    ) -> tuple[float, str]:
        """Factor 4: Trend Alignment (Multi-Timeframe).

        Combines MTF confluence with EMA and MACD alignment.
        """
        # MTF confluence is primary (0.5 weight)
        mtf_component = mtf_confluence * 0.5

        # EMA alignment (0.25 weight)
        ema_component = 0.25 if ema_aligned else 0.0

        # MACD alignment (0.25 weight)
        macd_component = 0.25 if macd_aligned else 0.0

        score = min(1.0, mtf_component + ema_component + macd_component)
        reason = (
            f"mtf_confluence={mtf_confluence:.3f}, "
            f"ema_aligned={ema_aligned}, macd_aligned={macd_aligned}"
        )
        return score, reason

    @staticmethod
    def score_regime_filter(
        regime: str,
        side: str,
    ) -> tuple[float, str]:
        """Factor 5: Regime Filter.

        Only trade in favorable regimes. Unfavorable = hard reject.
        """
        # Regime → score mapping
        regime_scores = {
            "trending_up": {"buy": 1.0, "sell": 0.2},
            "trending_down": {"buy": 0.2, "sell": 1.0},
            "ranging": {"buy": 0.7, "sell": 0.7},
            "volatile": {"buy": 0.3, "sell": 0.3},
            "quiet": {"buy": 0.5, "sell": 0.5},
            "breakout": {"buy": 0.6, "sell": 0.6},
            "reversal": {"buy": 0.4, "sell": 0.4},
        }

        side_key = side.lower()
        if regime in regime_scores:
            score = regime_scores[regime].get(side_key, 0.3)
        else:
            score = 0.3  # Unknown regime → neutral

        reason = f"regime={regime}, side={side}, score={score:.2f}"
        return score, reason

    @staticmethod
    def score_sentiment_alignment(
        fear_greed_index: int,
        news_sentiment: float,
        funding_rate: float,
        side: str,
    ) -> tuple[float, str]:
        """Factor 6: Sentiment Alignment.

        Fear & Greed + news + funding rate must confirm direction.
        """
        scores = []

        # Fear & Greed (0-100): <30 = fear, >70 = greed
        if side == "buy":
            # Buying in fear = good (contrarian)
            if fear_greed_index < 20:
                fg_score = 1.0  # Extreme fear = great buy opportunity
            elif fear_greed_index < 40:
                fg_score = 0.7
            elif fear_greed_index < 60:
                fg_score = 0.4  # Neutral
            else:
                fg_score = 0.1  # Greedy market = risky buy
        else:
            # Selling in greed = good
            if fear_greed_index > 80:
                fg_score = 1.0
            elif fear_greed_index > 60:
                fg_score = 0.7
            elif fear_greed_index > 40:
                fg_score = 0.4
            else:
                fg_score = 0.1
        scores.append(("fear_greed", fg_score, 0.4))

        # News sentiment [-1, +1]
        if side == "buy":
            # Slightly negative news = contrarian buy opportunity
            if news_sentiment < -0.3:
                news_score = 0.8
            elif news_sentiment < 0.1:
                news_score = 0.5
            elif news_sentiment < 0.5:
                news_score = 0.3
            else:
                news_score = 0.1  # Euphoric news = risky
        else:
            if news_sentiment > 0.3:
                news_score = 0.8
            elif news_sentiment > 0.1:
                news_score = 0.5
            elif news_sentiment > -0.1:
                news_score = 0.3
            else:
                news_score = 0.1
        scores.append(("news", news_score, 0.3))

        # Funding rate: positive = longs pay shorts (market is long)
        if side == "buy":
            # Negative funding = shorts dominant = good for buy
            if funding_rate < -0.01:
                fund_score = 0.8
            elif funding_rate < 0.01:
                fund_score = 0.5
            else:
                fund_score = 0.2
        else:
            if funding_rate > 0.01:
                fund_score = 0.8
            elif funding_rate > -0.01:
                fund_score = 0.5
            else:
                fund_score = 0.2
        scores.append(("funding", fund_score, 0.3))

        # Weighted composite
        composite = sum(s * w for _, s, w in scores)
        score = max(0.0, min(1.0, composite))
        reason = (
            f"fear_greed={fear_greed_index}, news_sent={news_sentiment:.2f}, "
            f"funding={funding_rate:.4f}, composite={score:.3f}"
        )
        return score, reason

    @staticmethod
    def score_onchain_confirmation(
        whale_direction: str,  # "accumulating", "distributing", "neutral"
        exchange_flow: str,  # "inflow", "outflow", "neutral"
        large_tx_count: int,
        side: str,
    ) -> tuple[float, str]:
        """Factor 7: On-Chain Confirmation.

        Whale activity and exchange flows must support trade direction.
        """
        score_parts = []

        # Whale direction
        if side == "buy":
            if whale_direction == "accumulating":
                score_parts.append(0.4)
            elif whale_direction == "neutral":
                score_parts.append(0.2)
            else:
                score_parts.append(0.0)  # Whales distributing = bad for buy
        else:
            if whale_direction == "distributing":
                score_parts.append(0.4)
            elif whale_direction == "neutral":
                score_parts.append(0.2)
            else:
                score_parts.append(0.0)

        # Exchange flow
        if side == "buy":
            if exchange_flow == "outflow":
                score_parts.append(0.35)  # Coins leaving exchange = bullish
            elif exchange_flow == "neutral":
                score_parts.append(0.15)
            else:
                score_parts.append(0.0)
        else:
            if exchange_flow == "inflow":
                score_parts.append(0.35)
            elif exchange_flow == "neutral":
                score_parts.append(0.15)
            else:
                score_parts.append(0.0)

        # Large transaction activity (whale tx count as proxy)
        if large_tx_count >= 10:
            score_parts.append(0.25)
        elif large_tx_count >= 5:
            score_parts.append(0.15)
        else:
            score_parts.append(0.05)

        score = max(0.0, min(1.0, sum(score_parts)))
        reason = (
            f"whale={whale_direction}, flow={exchange_flow}, "
            f"large_txs={large_tx_count}, score={score:.3f}"
        )
        return score, reason


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL QUALITY FILTER AGENT
# ═══════════════════════════════════════════════════════════════════════


class SignalQualityFilter(BaseAgent):
    """Multi-factor signal quality filter.

    The probability gate that ensures ONLY high-quality signals reach
    the RiskGuardian. Scores signals across 7 factors, detects false
    signals, tracks historical win rates, and adapts filters.

    Subscribes to: tsar:stream:signals (raw from SignalScout)
    Publishes to: tsar:stream:signals:filtered (enriched signals)
    """

    AGENT_NAME = "signal_quality_filter"
    ROLE = "TRADE_PREVIEW"

    PUBLISH_STREAM = "signals:filtered"
    SUBSCRIBE_STREAMS = ["signals", "regime", "sentiment"]

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)

        sqf_config = config.get("signal_quality", {})

        # Factor weights
        weights_config = sqf_config.get("weights", {})
        self._weights = FactorWeights(
            rsi_confirmation=weights_config.get("rsi_confirmation", 0.15),
            sr_proximity=weights_config.get("sr_proximity", 0.20),
            volume_confirmation=weights_config.get("volume_confirmation", 0.15),
            trend_alignment=weights_config.get("trend_alignment", 0.15),
            regime_filter=weights_config.get("regime_filter", 0.15),
            sentiment_alignment=weights_config.get("sentiment_alignment", 0.10),
            onchain_confirmation=weights_config.get("onchain_confirmation", 0.10),
        )
        self._weights.validate()

        # Thresholds
        self._no_trade_threshold = sqf_config.get("thresholds", {}).get("no_trade", 0.60)
        self._small_threshold = sqf_config.get("thresholds", {}).get("small_position", 0.70)
        self._normal_threshold = sqf_config.get("thresholds", {}).get("normal_position", 0.80)

        # Confirmation requirements
        conf = sqf_config.get("confirmation", {})
        self._min_factors = conf.get("min_factors", 3)
        self._min_factor_score = conf.get("min_factor_score", 0.3)
        self._regime_must_be_favorable = conf.get("regime_must_be_favorable", True)
        self._volume_must_confirm = conf.get("volume_must_confirm", True)

        # Cold start
        self._cold_start_trades = sqf_config.get("cold_start", {}).get("trades", 20)
        self._cold_start_min_score = sqf_config.get("cold_start", {}).get("min_score", 0.65)

        # $10 account protections
        acct = sqf_config.get("account_protections", {})
        self._max_concurrent = acct.get("max_concurrent_positions", 2)
        self._max_spread_pct = acct.get("max_spread_pct", 0.3)
        self._min_rr_after_fees = acct.get("min_rr_after_fees", 1.5)
        self._taker_fee_pct = acct.get("taker_fee_pct", 0.1)

        # Trading hour restrictions
        hours = sqf_config.get("trading_hours", {})
        self._low_liquidity_hours = tuple(hours.get("low_liquidity_utc", [0, 1, 2, 3, 4]))

        # Sub-components
        self._false_signal_detector = FalseSignalDetector(config)
        self._quality_db = SignalQualityDB(
            db_path=sqf_config.get("tracking", {}).get("db_path", "data/signal_quality.db")
        )
        self._adaptive_filter = AdaptiveFilter(config, self._quality_db)

        # State
        self._current_regime: str = "unknown"
        self._current_sentiment: dict[str, Any] = {}
        self._open_positions: int = 0
        self._total_signals_processed: int = 0

        # Engine references (lazy)
        self._gateway = None
        self._pricing_engine = None

        # External tool references (set during init or injected)
        self._sentiment_tools = None
        self._onchain_tools = None

        logger.info(
            "SignalQualityFilter initialized: weights=%s, thresholds=[%.2f, %.2f, %.2f]",
            self._weights.as_dict(),
            self._no_trade_threshold,
            self._small_threshold,
            self._normal_threshold,
        )

    async def on_initialize(self) -> None:
        """Initialize gateways, tools, and database."""
        from src.interfaces import get_exchange_gateway, get_pricing_engine

        self._gateway = get_exchange_gateway()
        self._pricing_engine = get_pricing_engine()

        # Initialize tools
        from src.tools.on_chain import OnChainTools
        from src.tools.sentiment import SentimentTools

        self._sentiment_tools = SentimentTools(config=self.config)
        self._onchain_tools = OnChainTools(config=self.config)

        # Initialize database
        await self._quality_db.initialize()

        # Load adaptive state
        await self._adaptive_filter.load_state()

        logger.info("SignalQualityFilter fully initialized")

    async def handle_event(self, stream: str, event: Any) -> None:
        """Handle incoming events.

        - signals: Score and filter incoming signals
        - regime: Update internal regime state
        - sentiment: Update sentiment cache
        """
        if stream == "regime":
            self._current_regime = event.data.get("regime", "unknown")
            logger.info("SQF: Regime updated to %s", self._current_regime)

        elif stream == "sentiment":
            self._current_sentiment = event.data
            logger.debug("SQF: Sentiment updated")

        elif stream == "signals":
            # This is the main path — score and filter the signal
            await self._process_signal(event.data)

    async def _process_signal(self, signal_data: dict[str, Any]) -> None:
        """Process a single signal through the quality filter.

        Full pipeline:
        1. Quick gates (regime, time, position count)
        2. Score all 7 factors
        3. Compute composite score
        4. Run false signal detection
        5. Apply adaptive filter adjustments
        6. Determine position tier
        7. Record outcome tracking
        8. Publish or reject
        """
        signal_id = signal_data.get("signal_id", "unknown")
        symbol = signal_data.get("symbol", "")
        side = signal_data.get("side", "")
        score = signal_data.get("score", 0)
        metadata = signal_data.get("metadata", {})

        self._total_signals_processed += 1
        logger.info(
            "SQF: Processing signal %s %s %s (raw_score=%.3f)",
            signal_id,
            symbol,
            side,
            score,
        )

        # ── GATE 1: Regime Check ────────────────────────────────
        if self._regime_must_be_favorable and self._current_regime == "volatile":
            await self._reject_signal(
                signal_data,
                ["Unfavorable regime: volatile"],
                regime=self._current_regime,
            )
            return

        # ── GATE: Position Count ────────────────────────────────
        if self._open_positions >= self._max_concurrent:
            await self._reject_signal(
                signal_data,
                [f"Max concurrent positions ({self._max_concurrent}) reached"],
                regime=self._current_regime,
            )
            return

        # ── GATE: Trading Hours ─────────────────────────────────
        from datetime import UTC as _UTC

        current_hour = datetime.now(_UTC).hour
        if current_hour in self._low_liquidity_hours:
            await self._reject_signal(
                signal_data,
                [f"Low-liquidity hour ({current_hour}:00 UTC)"],
                regime=self._current_regime,
            )
            return

        # ── Collect Market Data for Scoring ─────────────────────
        try:
            market_context = await self._gather_market_context(signal_data)
        except Exception as e:
            logger.warning("SQF: Failed to gather market context for %s: %s", symbol, e)
            await self._reject_signal(
                signal_data,
                [f"Market context unavailable: {e}"],
                regime=self._current_regime,
            )
            return

        # ── Score All 7 Factors ─────────────────────────────────
        factors = self._score_all_factors(signal_data, market_context)

        # ── Compute Composite Score ─────────────────────────────
        composite = sum(f.weighted for f in factors)
        composite = max(0.0, min(1.0, composite))
        confirmed_count = sum(1 for f in factors if f.confirmed)

        logger.info(
            "SQF: %s %s factors=%d/%d confirmed, composite=%.3f",
            symbol,
            side,
            confirmed_count,
            len(factors),
            composite,
        )

        # ── GATE 2: Minimum Factor Count ────────────────────────
        if confirmed_count < self._min_factors:
            reasons = [
                f"Only {confirmed_count}/{len(factors)} factors confirmed "
                f"(minimum {self._min_factors})"
            ]
            await self._reject_signal(signal_data, reasons, factors=factors, composite=composite)
            return

        # ── GATE 3: Conflict Detection ─────────────────────────
        scores = [f.score for f in factors]
        if min(scores) < 0.1 and max(scores) > 0.9:
            conflicting = [f.name for f in factors if f.score < 0.1 or f.score > 0.9]
            await self._reject_signal(
                signal_data,
                [f"Conflicting signals detected: {conflicting}"],
                factors=factors,
                composite=composite,
            )
            return

        # ── GATE 4: Volume-Price Confirmation ──────────────────
        if self._volume_must_confirm:
            vol_factor = next(f for f in factors if f.name == "volume_confirmation")
            if vol_factor.score < 0.2:
                price_move = metadata.get("price_change_pct", 0)
                if abs(price_move) > 1.0:
                    await self._reject_signal(
                        signal_data,
                        [f"Price moved {price_move:.1f}% but volume not confirmed"],
                        factors=factors,
                        composite=composite,
                    )
                    return

        # ── False Signal Detection ──────────────────────────────
        false_flags = self._false_signal_detector.detect_all(
            signal_data=signal_data,
            market_context=market_context,
        )
        if false_flags:
            critical_flags = [f for f in false_flags if f.severity == "critical"]
            if critical_flags:
                flag_names = [f.name for f in critical_flags]
                await self._reject_signal(
                    signal_data,
                    [f"False signal detected: {flag_names}"],
                    factors=factors,
                    composite=composite,
                    false_signal_flags=flag_names,
                )
                return

        # ── Cold Start Protection ───────────────────────────────
        total_trades = await self._quality_db.get_trade_count()
        effective_threshold = self._no_trade_threshold
        if total_trades < self._cold_start_trades:
            effective_threshold = max(effective_threshold, self._cold_start_min_score)
            logger.info(
                "SQF: Cold start (%d/%d trades), threshold raised to %.2f",
                total_trades,
                self._cold_start_trades,
                effective_threshold,
            )

        # ── Adaptive Filter Adjustment ──────────────────────────
        adaptive_state = await self._adaptive_filter.get_current_state()
        effective_threshold = max(effective_threshold, adaptive_state.min_score)
        effective_min_factors = max(self._min_factors, adaptive_state.min_factors)

        # Re-check with adaptive threshold
        if composite < effective_threshold:
            await self._reject_signal(
                signal_data,
                [f"Score {composite:.3f} below adaptive threshold {effective_threshold:.3f}"],
                factors=factors,
                composite=composite,
                adaptive_state=adaptive_state.__dict__,
            )
            return

        if confirmed_count < effective_min_factors:
            await self._reject_signal(
                signal_data,
                [
                    f"Only {confirmed_count} factors confirmed (adaptive minimum: {effective_min_factors})"
                ],
                factors=factors,
                composite=composite,
                adaptive_state=adaptive_state.__dict__,
            )
            return

        # ── GATE 5: Determine Position Tier ─────────────────────
        tier, size_factor = self._determine_tier(composite)

        # ── $10 Account: Spread Check ──────────────────────────
        spread_pct = market_context.get("spread_pct", 0)
        if spread_pct > self._max_spread_pct:
            await self._reject_signal(
                signal_data,
                [f"Spread {spread_pct:.2f}% exceeds maximum {self._max_spread_pct}%"],
                factors=factors,
                composite=composite,
            )
            return

        # ── $10 Account: R:R After Fees ────────────────────────
        entry = signal_data.get("entry_price", 0)
        sl = signal_data.get("stop_loss", 0)
        tp = signal_data.get("take_profit", 0)
        if entry > 0 and sl > 0 and tp > 0:
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            # Account for fees on both sides
            fee_cost = entry * (self._taker_fee_pct / 100) * 2
            effective_reward = reward - fee_cost
            if risk > 0:
                effective_rr = effective_reward / risk
                if effective_rr < self._min_rr_after_fees:
                    await self._reject_signal(
                        signal_data,
                        [f"R:R after fees {effective_rr:.2f} < minimum {self._min_rr_after_fees}"],
                        factors=factors,
                        composite=composite,
                    )
                    return

        # ── Build Quality Assessment ────────────────────────────
        assessment = QualityAssessment(
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            factors=factors,
            composite_score=composite,
            factors_confirmed=confirmed_count,
            tier=tier,
            position_size_factor=size_factor,
            approved=True,
            rejection_reasons=(),
            false_signal_flags=tuple(f.name for f in false_flags) if false_flags else (),
            regime=self._current_regime,
            adaptive_state=adaptive_state.__dict__,
            timestamp=datetime.now(UTC).isoformat(),
        )

        # ── Record for Tracking ─────────────────────────────────
        await self._quality_db.record_signal_assessment(assessment)

        # ── Enrich and Publish ──────────────────────────────────
        enriched = self._enrich_signal(signal_data, assessment)

        logger.info(
            "✅ SQF APPROVED: %s %s composite=%.3f tier=%s size_factor=%.1f",
            symbol,
            side,
            composite,
            tier.value,
            size_factor,
        )

        await self.publish_event(
            stream="signals:filtered",
            event_type="tsar.signal.quality_scored.v1",
            data=enriched,
            priority=1,
            risk_level="LOW",
        )

    def _score_all_factors(
        self,
        signal_data: dict[str, Any],
        market_context: dict[str, Any],
    ) -> tuple[FactorScore, ...]:
        """Score all 7 quality factors."""
        side = signal_data.get("side", "buy")
        metadata = signal_data.get("metadata", {})
        entry_price = signal_data.get("entry_price", 0)

        factors = []

        # Factor 1: RSI Confirmation
        rsi = metadata.get("rsi", 50)
        vol_ratio = market_context.get("volume_ratio", 1.0)
        f1_score, f1_reason = FactorScorer.score_rsi_confirmation(
            rsi,
            side,
            vol_ratio,
            self.config.get("strategies", {}).get("mean_reversion", {}).get("params", {}),
        )
        factors.append(
            FactorScore(
                name="rsi_confirmation",
                score=f1_score,
                weight=self._weights.rsi_confirmation,
                weighted=f1_score * self._weights.rsi_confirmation,
                reason=f1_reason,
                confirmed=f1_score > self._min_factor_score,
            )
        )

        # Factor 2: S/R Proximity
        nearest_support = market_context.get("nearest_support")
        nearest_resistance = market_context.get("nearest_resistance")
        if side == "buy" and nearest_support:
            level_price = nearest_support["price"]
            level_strength = nearest_support["strength"]
        elif side == "sell" and nearest_resistance:
            level_price = nearest_resistance["price"]
            level_strength = nearest_resistance["strength"]
        else:
            level_price = None
            level_strength = 0.0

        f2_score, f2_reason = FactorScorer.score_sr_proximity(
            entry_price,
            level_price,
            level_strength,
        )
        factors.append(
            FactorScore(
                name="sr_proximity",
                score=f2_score,
                weight=self._weights.sr_proximity,
                weighted=f2_score * self._weights.sr_proximity,
                reason=f2_reason,
                confirmed=f2_score > self._min_factor_score,
            )
        )

        # Factor 3: Volume Confirmation
        current_vol = market_context.get("current_volume", 0)
        avg_vol = market_context.get("avg_volume", 1)
        f3_score, f3_reason = FactorScorer.score_volume_confirmation(current_vol, avg_vol)
        factors.append(
            FactorScore(
                name="volume_confirmation",
                score=f3_score,
                weight=self._weights.volume_confirmation,
                weighted=f3_score * self._weights.volume_confirmation,
                reason=f3_reason,
                confirmed=f3_score > self._min_factor_score,
            )
        )

        # Factor 4: Trend Alignment
        mtf_confluence = market_context.get("mtf_confluence", 0.5)
        ema_aligned = market_context.get("ema_aligned", False)
        macd_aligned = market_context.get("macd_aligned", False)
        f4_score, f4_reason = FactorScorer.score_trend_alignment(
            mtf_confluence,
            ema_aligned,
            macd_aligned,
        )
        factors.append(
            FactorScore(
                name="trend_alignment",
                score=f4_score,
                weight=self._weights.trend_alignment,
                weighted=f4_score * self._weights.trend_alignment,
                reason=f4_reason,
                confirmed=f4_score > self._min_factor_score,
            )
        )

        # Factor 5: Regime Filter
        f5_score, f5_reason = FactorScorer.score_regime_filter(self._current_regime, side)
        factors.append(
            FactorScore(
                name="regime_filter",
                score=f5_score,
                weight=self._weights.regime_filter,
                weighted=f5_score * self._weights.regime_filter,
                reason=f5_reason,
                confirmed=f5_score > self._min_factor_score,
            )
        )

        # Factor 6: Sentiment Alignment
        fg_index = self._current_sentiment.get("fear_greed_index", 50)
        news_sent = self._current_sentiment.get("news_sentiment", 0.0)
        funding = self._current_sentiment.get("funding_rate", 0.0)
        f6_score, f6_reason = FactorScorer.score_sentiment_alignment(
            fg_index,
            news_sent,
            funding,
            side,
        )
        factors.append(
            FactorScore(
                name="sentiment_alignment",
                score=f6_score,
                weight=self._weights.sentiment_alignment,
                weighted=f6_score * self._weights.sentiment_alignment,
                reason=f6_reason,
                confirmed=f6_score > self._min_factor_score,
            )
        )

        # Factor 7: On-Chain Confirmation
        whale_dir = market_context.get("whale_direction", "neutral")
        exch_flow = market_context.get("exchange_flow", "neutral")
        large_txs = market_context.get("large_tx_count", 0)
        f7_score, f7_reason = FactorScorer.score_onchain_confirmation(
            whale_dir,
            exch_flow,
            large_txs,
            side,
        )
        factors.append(
            FactorScore(
                name="onchain_confirmation",
                score=f7_score,
                weight=self._weights.onchain_confirmation,
                weighted=f7_score * self._weights.onchain_confirmation,
                reason=f7_reason,
                confirmed=f7_score > self._min_factor_score,
            )
        )

        return tuple(factors)

    def _determine_tier(self, composite: float) -> tuple[PositionTier, float]:
        """Determine position tier from composite score."""
        if composite < self._no_trade_threshold:
            return PositionTier.NO_TRADE, 0.0
        elif composite < self._small_threshold:
            return PositionTier.SMALL, 0.5
        elif composite < self._normal_threshold:
            return PositionTier.NORMAL, 1.0
        else:
            return PositionTier.LARGE, 1.5

    def _enrich_signal(
        self,
        signal_data: dict[str, Any],
        assessment: QualityAssessment,
    ) -> dict[str, Any]:
        """Enrich original signal with quality assessment data."""
        enriched = dict(signal_data)
        enriched["quality"] = {
            "composite_score": assessment.composite_score,
            "tier": assessment.tier.value,
            "position_size_factor": assessment.position_size_factor,
            "factors_confirmed": assessment.factors_confirmed,
            "factor_breakdown": {
                f.name: {
                    "score": f.score,
                    "weighted": f.weighted,
                    "reason": f.reason,
                    "confirmed": f.confirmed,
                }
                for f in assessment.factors
            },
            "false_signal_flags": list(assessment.false_signal_flags),
            "regime": assessment.regime,
            "adaptive_state": assessment.adaptive_state,
            "filtered_at": assessment.timestamp,
        }
        # Override the signal score with quality composite
        enriched["original_score"] = enriched.get("score", 0)
        enriched["score"] = assessment.composite_score
        return enriched

    async def _reject_signal(
        self,
        signal_data: dict[str, Any],
        reasons: list[str],
        factors: tuple[FactorScore, ...] = (),
        composite: float = 0.0,
        false_signal_flags: list[str] | None = None,
        regime: str = "unknown",
        adaptive_state: dict[str, Any] | None = None,
    ) -> None:
        """Record and publish a signal rejection."""
        signal_id = signal_data.get("signal_id", "unknown")
        symbol = signal_data.get("symbol", "")
        side = signal_data.get("side", "")

        logger.warning(
            "❌ SQF REJECTED: %s %s %s — %s",
            signal_id,
            symbol,
            side,
            "; ".join(reasons),
        )

        # Record rejection for tracking
        assessment = QualityAssessment(
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            factors=factors,
            composite_score=composite,
            factors_confirmed=sum(1 for f in factors if f.confirmed),
            tier=PositionTier.NO_TRADE,
            position_size_factor=0.0,
            approved=False,
            rejection_reasons=tuple(reasons),
            false_signal_flags=tuple(false_signal_flags or []),
            regime=regime,
            adaptive_state=adaptive_state or {},
            timestamp=datetime.now(UTC).isoformat(),
        )
        await self._quality_db.record_signal_assessment(assessment)

        # Publish rejection event
        await self.publish_event(
            stream="signals:filtered",
            event_type="tsar.signal.quality_rejected.v1",
            data={
                "signal_id": signal_id,
                "symbol": symbol,
                "side": side,
                "reasons": reasons,
                "composite_score": composite,
                "false_signal_flags": false_signal_flags or [],
            },
            priority=0,
            risk_level="LOW",
        )

    async def record_trade_outcome(
        self,
        signal_id: str,
        pnl_pct: float,
        exit_price: float,
    ) -> None:
        """Record the outcome of a trade for win rate tracking.

        Called by the ExecutionTracker after a position is closed.
        Triggers adaptive filter evaluation.
        """
        win = pnl_pct > 0
        await self._quality_db.record_outcome(signal_id, pnl_pct, exit_price, win)

        # Check if we need to adapt filters
        await self._adaptive_filter.evaluate_and_adapt()

        logger.info(
            "SQF: Recorded outcome for %s: pnl=%.2f%%, win=%s",
            signal_id,
            pnl_pct,
            win,
        )

    async def _gather_market_context(
        self,
        signal_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Gather market data needed for factor scoring.

        Collects: volume ratios, S/R levels, MTF confluence,
        sentiment, on-chain data.
        """
        symbol = signal_data.get("symbol", "")
        metadata = signal_data.get("metadata", {})
        entry_price = signal_data.get("entry_price", 0)
        side = signal_data.get("side", "buy")

        context: dict[str, Any] = {}

        # Volume data
        volumes = metadata.get("volumes", [])
        if volumes and len(volumes) >= 20:
            context["current_volume"] = volumes[-1]
            context["avg_volume"] = sum(volumes[-20:]) / 20
            context["volume_ratio"] = (
                volumes[-1] / context["avg_volume"] if context["avg_volume"] > 0 else 1.0
            )
        else:
            context["current_volume"] = 0
            context["avg_volume"] = 1
            context["volume_ratio"] = 1.0

        # S/R levels from metadata
        sr_data = metadata.get("sr_levels", {})
        context["nearest_support"] = sr_data.get("nearest_support")
        context["nearest_resistance"] = sr_data.get("nearest_resistance")

        # MTF confluence
        context["mtf_confluence"] = metadata.get("mtf_confluence", 0.5)

        # EMA and MACD alignment
        ema_trend = metadata.get("ema_trend", 0)
        context["ema_aligned"] = (
            (
                (side == "buy" and entry_price > ema_trend)
                or (side == "sell" and entry_price < ema_trend)
            )
            if ema_trend > 0
            else False
        )

        macd_hist = metadata.get("macd_histogram", 0)
        context["macd_aligned"] = (side == "buy" and macd_hist > 0) or (
            side == "sell" and macd_hist < 0
        )

        # Spread (if available from orderbook)
        context["spread_pct"] = metadata.get("spread_pct", 0)

        # Price change percentage
        context["price_change_pct"] = metadata.get("price_change_pct", 0)

        # Sentiment data
        if self._current_sentiment:
            pass  # Already cached from sentiment stream

        # On-chain data (best effort)
        try:
            if self._onchain_tools:
                onchain = await self._onchain_tools.get_onchain_summary(symbol)
                context["whale_direction"] = onchain.get("whale_direction", "neutral")
                context["exchange_flow"] = onchain.get("exchange_flow", "neutral")
                context["large_tx_count"] = onchain.get("large_tx_count", 0)
            else:
                context["whale_direction"] = "neutral"
                context["exchange_flow"] = "neutral"
                context["large_tx_count"] = 0
        except Exception:
            context["whale_direction"] = "neutral"
            context["exchange_flow"] = "neutral"
            context["large_tx_count"] = 0

        return context
