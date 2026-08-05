"""
TSAR Strategy Router — Regime-aware strategy orchestration agent.

This agent sits between SignalScout and RiskGuardian in the TSAR pipeline.
It receives market data, detects the current regime, and routes to the
optimal strategy (TSAR, Momentum, MeanReversion, or a blended combination).

Architecture:
  Market Data → RegimeDetector → TSARStrategyRouter
    ├─ Trending  → TSAR trend mode + Momentum confirmation
    ├─ Ranging   → TSAR mean-reversion mode + MeanReversion confirmation
    ├─ Volatile  → Reduced sizing, TSAR with wider stops
    └─ Calm      → Normal TSAR execution

Signal blending:
  TSAR signal score (0-100) + Momentum/MeanReversion score (0-100)
  → Regime-weighted blend → Combined score → RiskGuardian

Subscribes to: tsar:stream:regime, tsar:stream:cartography
Publishes to:  tsar:stream:signals

Role: TRADE_PREVIEW
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.agents.base import BaseAgent
from src.strategy.genome import StrategyGenome
from src.strategy.mean_reversion import MeanReversionStrategy
from src.strategy.momentum import MomentumStrategy
from src.strategy.tsar_strategy.strategy import TSARStrategy

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# REGIME TYPES & ROUTING CONFIG
# ═══════════════════════════════════════════════════════════════════════


class MarketRegime(StrEnum):
    """Market regime classification."""

    STRONG_TREND_UP = "strong_trend_up"
    STRONG_TREND_DOWN = "strong_trend_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    UNCERTAIN = "uncertain"


class RoutingMode(StrEnum):
    """Strategy routing mode."""

    TSAR_TREND = "tsar_trend"
    TSAR_REVERSION = "tsar_reversion"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BLENDED = "blended"
    SKIP = "skip"


@dataclass
class RoutingDecision:
    """Output of the routing decision."""

    mode: RoutingMode
    primary_strategy: str
    secondary_strategy: str | None
    tsar_weight: float  # 0.0 – 1.0
    fallback_weight: float  # 0.0 – 1.0
    position_size_mult: float  # Regime-based sizing multiplier
    reasoning: str


@dataclass
class BlendedSignal:
    """A signal produced by blending TSAR with another strategy."""

    side: str
    score: float  # 0.0 – 1.0 (blended)
    tsar_score: float
    fallback_score: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    strategy: str
    routing_mode: str
    regime: str
    position_size_pct: float
    reasoning: str


# ═══════════════════════════════════════════════════════════════════════
# REGIME → ROUTING TABLE
# ═══════════════════════════════════════════════════════════════════════

# Default routing table: regime → (mode, tsar_weight, fallback_weight, sizing_mult)
_ROUTING_TABLE: dict[MarketRegime, tuple[RoutingMode, float, float, float]] = {
    MarketRegime.STRONG_TREND_UP: (RoutingMode.TSAR_TREND, 0.7, 0.3, 1.0),
    MarketRegime.STRONG_TREND_DOWN: (RoutingMode.TSAR_TREND, 0.7, 0.3, 1.0),
    MarketRegime.RANGING: (RoutingMode.TSAR_REVERSION, 0.6, 0.4, 0.8),
    MarketRegime.HIGH_VOLATILITY: (RoutingMode.BLENDED, 0.5, 0.5, 0.5),
    MarketRegime.UNCERTAIN: (RoutingMode.SKIP, 0.0, 0.0, 0.0),
}


# ═══════════════════════════════════════════════════════════════════════
# TSAR STRATEGY ROUTER AGENT
# ═══════════════════════════════════════════════════════════════════════


class TSARStrategyRouter(BaseAgent):
    """Regime-aware strategy router that orchestrates TSAR + legacy strategies.

    This agent:
    1. Receives market data and regime classification
    2. Routes to the optimal strategy combination based on regime
    3. Runs TSAR's 7-layer pipeline
    4. Optionally runs Momentum/MeanReversion for confirmation
    5. Blends signals with regime-weighted scoring
    6. Publishes the final signal to RiskGuardian

    The router implements the "super-strategy" concept: TSAR provides
    directional bias and institutional S/R zones, while Momentum/MeanReversion
    provide statistical confirmation. The regime determines the blend.
    """

    AGENT_NAME = "tsar_strategy_router"
    ROLE = "TRADE_PREVIEW"

    PUBLISH_STREAM = "signals"
    SUBSCRIBE_STREAMS = ["regime", "cartography"]

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)

        # Strategy instances (initialized in on_initialize)
        self._tsar: TSARStrategy | None = None
        self._momentum: MomentumStrategy | None = None
        self._mean_reversion: MeanReversionStrategy | None = None

        # Current regime state
        self._current_regime: MarketRegime = MarketRegime.UNCERTAIN
        self._regime_confidence: float = 0.0
        self._regime_data: dict[str, Any] = {}

        # Routing config (overridable from config/genome)
        self._routing_table = dict(_ROUTING_TABLE)
        self._min_combined_score = config.get("tsar_router", {}).get("min_combined_score", 0.55)
        self._require_tsar_pass = config.get("tsar_router", {}).get("require_tsar_pass", False)

        # Metrics
        self._signals_routed = 0
        self._signals_blended = 0
        self._signals_skipped = 0

    async def on_initialize(self) -> None:
        """Initialize strategy instances."""
        logger.info("🔀 TSARStrategyRouter initializing")

        # Load TSAR genome if available
        tsar_genome = None
        try:
            tsar_genome = StrategyGenome.from_yaml("config/strategies/tsar.yaml")
            logger.info("Loaded TSAR genome: %s", tsar_genome.name)
        except FileNotFoundError:
            logger.info("No TSAR genome YAML found — using defaults")

        self._tsar = TSARStrategy(genome=tsar_genome)

        # Load Momentum genome
        momentum_genome = None
        with contextlib.suppress(FileNotFoundError):
            momentum_genome = StrategyGenome.from_yaml("config/strategies/momentum.yaml")
        self._momentum = MomentumStrategy(genome=momentum_genome)

        # MeanReversion (no genome needed for Day1)
        self._mean_reversion = MeanReversionStrategy()

        logger.info(
            "TSARStrategyRouter ready: TSAR=%s, Momentum=%s, MeanReversion=%s",
            self._tsar is not None,
            self._momentum is not None,
            self._mean_reversion is not None,
        )

    async def handle_event(self, stream: str, event: Any) -> None:
        """Handle regime change events.

        Args:
            stream: Event stream name.
            event: CloudEvent with regime classification data.
        """
        if stream == "regime":
            data = event.data if hasattr(event, "data") else event
            regime_str = data.get("regime", "uncertain")
            try:
                self._current_regime = MarketRegime(regime_str)
            except ValueError:
                self._current_regime = MarketRegime.UNCERTAIN
            self._regime_confidence = data.get("confidence", 0.0)
            self._regime_data = data
            logger.info(
                "Regime updated: %s (confidence=%.2f)",
                self._current_regime.value,
                self._regime_confidence,
            )

    async def run_cycle(self) -> None:
        """Main router cycle — called by BaseAgent loop.

        In production, this agent is event-driven (subscribes to regime
        and cartography streams). The run_cycle handles periodic
        health checks and metrics logging.
        """
        # This agent is primarily event-driven via handle_event()
        # The run_cycle is used for periodic housekeeping
        pass

    # ═══════════════════════════════════════════════════════════════════════
    # CORE ROUTING LOGIC
    # ═══════════════════════════════════════════════════════════════════════

    def route_and_generate_signal(self, market_data: dict[str, Any]) -> dict[str, Any] | None:
        """Main entry point: route to optimal strategy and generate signal.

        This is the core method called by the Orchestrator or SignalScout
        to get a regime-aware, blended trading signal.

        Args:
            market_data: Full market data dict from exchange/analysis tools.

        Returns:
            Blended signal dict compatible with RiskGuardian, or None.
        """
        # Step 1: Determine routing based on current regime
        routing = self._make_routing_decision()

        if routing.mode == RoutingMode.SKIP:
            self._signals_skipped += 1
            logger.debug("Router: SKIP (regime=%s)", self._current_regime.value)
            return None

        # Step 2: Run TSAR pipeline
        tsar_signal = self._run_tsar(market_data)

        # Step 3: Run fallback strategy based on routing
        fallback_signal = self._run_fallback(market_data, routing)

        # Step 4: Blend signals
        blended = self._blend_signals(tsar_signal, fallback_signal, routing, market_data)

        if blended is None:
            self._signals_skipped += 1
            return None

        self._signals_routed += 1
        if blended.secondary_strategy:
            self._signals_blended += 1

        # Convert to TSAR signal format
        return blended.to_dict()

    def _make_routing_decision(self) -> RoutingDecision:
        """Determine routing based on current market regime.

        Uses the routing table to select strategy weights and sizing.
        Can be overridden by genome parameters for genetic optimization.
        """
        mode, tsar_w, fallback_w, sizing = self._routing_table.get(
            self._current_regime,
            (RoutingMode.SKIP, 0.0, 0.0, 0.0),
        )

        # Determine primary and secondary strategies
        if mode == RoutingMode.TSAR_TREND:
            primary = "tsar"
            secondary = "momentum"
        elif mode == RoutingMode.TSAR_REVERSION:
            primary = "tsar"
            secondary = "mean_reversion"
        elif mode == RoutingMode.MOMENTUM:
            primary = "momentum"
            secondary = "tsar"
        elif mode == RoutingMode.MEAN_REVERSION:
            primary = "mean_reversion"
            secondary = "tsar"
        elif mode == RoutingMode.BLENDED:
            primary = "tsar"
            secondary = "momentum"
        else:
            primary = ""
            secondary = None

        reasoning = (
            f"regime={self._current_regime.value} "
            f"conf={self._regime_confidence:.2f} "
            f"mode={mode.value} "
            f"tsar_w={tsar_w:.1f} fallback_w={fallback_w:.1f}"
        )

        return RoutingDecision(
            mode=mode,
            primary_strategy=primary,
            secondary_strategy=secondary,
            tsar_weight=tsar_w,
            fallback_weight=fallback_w,
            position_size_mult=sizing,
            reasoning=reasoning,
        )

    def _run_tsar(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Run TSAR strategy's entry pipeline."""
        if self._tsar is None:
            return None
        try:
            return self._tsar.check_entry(data)
        except Exception as e:
            logger.warning("TSAR check_entry failed: %s", e)
            return None

    def _run_fallback(
        self, data: dict[str, Any], routing: RoutingDecision
    ) -> dict[str, Any] | None:
        """Run the fallback strategy (Momentum or MeanReversion)."""
        strategy_name = routing.secondary_strategy
        if not strategy_name:
            return None

        try:
            if strategy_name == "momentum" and self._momentum is not None:
                return self._momentum.check_entry(data)
            elif strategy_name == "mean_reversion" and self._mean_reversion is not None:
                return self._mean_reversion.check_entry(data)
        except Exception as e:
            logger.warning("Fallback strategy %s failed: %s", strategy_name, e)

        return None

    def _blend_signals(
        self,
        tsar_signal: dict[str, Any] | None,
        fallback_signal: dict[str, Any] | None,
        routing: RoutingDecision,
        market_data: dict[str, Any],
    ) -> BlendedSignal | None:
        """Blend TSAR and fallback signals using regime-weighted scoring.

        Blending rules:
        - If only TSAR passes: use TSAR signal (scaled by tsar_weight)
        - If only fallback passes: use fallback signal (scaled by fallback_weight)
        - If both pass and agree on direction: weighted average
        - If both pass but disagree: skip (conflicting signals)
        - If neither passes: no signal
        """
        tsar_score = tsar_signal.get("score", 0.0) if tsar_signal else 0.0
        fallback_score = fallback_signal.get("score", 0.0) if fallback_signal else 0.0

        tsar_side = tsar_signal.get("side", "") if tsar_signal else ""
        fallback_side = fallback_signal.get("side", "") if fallback_signal else ""

        # Neither strategy produced a signal
        if not tsar_signal and not fallback_signal:
            return None

        # If require_tsar_pass is set, TSAR must pass
        if self._require_tsar_pass and not tsar_signal:
            return None

        # Single strategy signals
        if tsar_signal and not fallback_signal:
            return self._build_single_signal(tsar_signal, routing, "tsar_only", market_data)

        if fallback_signal and not tsar_signal:
            return self._build_single_signal(
                fallback_signal, routing, f"{routing.secondary_strategy}_only", market_data
            )

        # Both signals exist — check direction agreement
        if tsar_side != fallback_side:
            logger.debug(
                "Conflicting signals: TSAR=%s(%.2f) vs %s=%s(%.2f) — skipping",
                tsar_side,
                tsar_score,
                routing.secondary_strategy,
                fallback_side,
                fallback_score,
            )
            return None

        # Direction agrees — blend with regime weights
        combined_score = (
            tsar_score * routing.tsar_weight + fallback_score * routing.fallback_weight
        ) / (routing.tsar_weight + routing.fallback_weight)

        # Check minimum combined score
        if combined_score < self._min_combined_score:
            return None

        # Use TSAR's trade parameters (S/R levels are more precise)
        entry = tsar_signal.get("entry_price", 0.0) or fallback_signal.get("entry_price", 0.0)
        sl = tsar_signal.get("stop_loss", 0.0) or fallback_signal.get("stop_loss", 0.0)
        tp = tsar_signal.get("take_profit", 0.0) or fallback_signal.get("take_profit", 0.0)
        rr = tsar_signal.get("risk_reward", 0.0) or fallback_signal.get("risk_reward", 0.0)

        # Position sizing: base * regime multiplier
        base_pct = tsar_signal.get("position_size_pct", 2.0)
        position_pct = base_pct * routing.position_size_mult

        market_data.get("symbol", "?")

        return BlendedSignal(
            side=tsar_side,
            score=round(combined_score, 4),
            tsar_score=round(tsar_score, 4),
            fallback_score=round(fallback_score, 4),
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            risk_reward=rr,
            strategy="tsar_blend",
            routing_mode=routing.mode.value,
            regime=self._current_regime.value,
            position_size_pct=position_pct,
            reasoning=(
                f"blend: tsar={tsar_score:.2f}×{routing.tsar_weight:.1f} + "
                f"{routing.secondary_strategy}={fallback_score:.2f}×{routing.fallback_weight:.1f} "
                f"→ {combined_score:.2f} regime={self._current_regime.value}"
            ),
        )

    def _build_single_signal(
        self,
        signal: dict[str, Any],
        routing: RoutingDecision,
        label: str,
        market_data: dict[str, Any],
    ) -> BlendedSignal | None:
        """Build a BlendedSignal from a single strategy's output."""
        score = signal.get("score", 0.0)
        # Scale by the strategy's weight in the routing
        weight = routing.tsar_weight if "tsar" in label else routing.fallback_weight
        scaled_score = score * weight

        if scaled_score < self._min_combined_score:
            return None

        base_pct = signal.get("position_size_pct", 2.0)
        position_pct = base_pct * routing.position_size_mult

        return BlendedSignal(
            side=signal.get("side", "buy"),
            score=round(scaled_score, 4),
            tsar_score=round(score if "tsar" in label else 0.0, 4),
            fallback_score=round(score if "tsar" not in label else 0.0, 4),
            entry_price=signal.get("entry_price", 0.0),
            stop_loss=signal.get("stop_loss", 0.0),
            take_profit=signal.get("take_profit", 0.0),
            risk_reward=signal.get("risk_reward", 0.0),
            strategy=label,
            routing_mode=routing.mode.value,
            regime=self._current_regime.value,
            position_size_pct=position_pct,
            reasoning=f"single_{label} score={score:.2f}×{weight:.1f}={scaled_score:.2f}",
        )

    # ═══════════════════════════════════════════════════════════════════════
    # GENOME INTEGRATION (for StrategyGeneticist)
    # ═══════════════════════════════════════════════════════════════════════

    def update_routing_from_genome(self, genome: StrategyGenome) -> None:
        """Update routing parameters from an evolved genome.

        Called by StrategyGeneticist after genome mutation/crossover.
        Enables the geneticist to evolve TSAR's routing weights and
        regime-specific behavior.

        Args:
            genome: Evolved StrategyGenome with routing parameters.
        """
        params = genome.params

        # Update routing table weights from genome
        for regime_name in ("strong_trend_up", "strong_trend_down", "ranging", "high_volatility"):
            tsar_w_key = f"routing_{regime_name}_tsar_weight"
            sizing_key = f"routing_{regime_name}_sizing_mult"

            if tsar_w_key in params or sizing_key in params:
                try:
                    regime = MarketRegime(regime_name)
                except ValueError:
                    continue

                old_mode, old_tsar, old_fallback, old_sizing = self._routing_table[regime]
                new_tsar = params.get(tsar_w_key, old_tsar)
                new_sizing = params.get(sizing_key, old_sizing)
                new_fallback = 1.0 - new_tsar

                self._routing_table[regime] = (old_mode, new_tsar, new_fallback, new_sizing)

        # Update threshold
        if "min_combined_score" in params:
            self._min_combined_score = params["min_combined_score"]

        logger.info("TSARStrategyRouter updated from genome '%s'", genome.name)

    def get_routing_state(self) -> dict[str, Any]:
        """Get current routing state for monitoring/debugging."""
        return {
            "current_regime": self._current_regime.value,
            "regime_confidence": self._regime_confidence,
            "min_combined_score": self._min_combined_score,
            "signals_routed": self._signals_routed,
            "signals_blended": self._signals_blended,
            "signals_skipped": self._signals_skipped,
            "routing_table": {
                regime.value: {
                    "mode": mode.value,
                    "tsar_weight": vw,
                    "fallback_weight": fw,
                    "sizing_mult": sm,
                }
                for regime, (mode, vw, fw, sm) in self._routing_table.items()
            },
        }

    def get_health(self) -> dict[str, Any]:
        """Return health status including routing metrics."""
        health = super().get_health()
        health.update(
            {
                "current_regime": self._current_regime.value,
                "signals_routed": self._signals_routed,
                "signals_blended": self._signals_blended,
                "signals_skipped": self._signals_skipped,
            }
        )
        return health


# ═══════════════════════════════════════════════════════════════════════
# BLENDED SIGNAL SERIALIZATION
# ═══════════════════════════════════════════════════════════════════════


def _blended_to_dict(blended: BlendedSignal) -> dict[str, Any]:
    """Convert BlendedSignal to dict for event publishing."""
    return {
        "side": blended.side,
        "score": blended.score,
        "entry_price": blended.entry_price,
        "stop_loss": blended.stop_loss,
        "take_profit": blended.take_profit,
        "risk_reward": blended.risk_reward,
        "strategy": blended.strategy,
        "routing_mode": blended.routing_mode,
        "regime": blended.regime,
        "position_size_pct": blended.position_size_pct,
        "reasoning": blended.reasoning,
        "components": {
            "tsar_score": blended.tsar_score,
            "fallback_score": blended.fallback_score,
        },
    }


# Monkey-patch to_dict onto BlendedSignal
BlendedSignal.to_dict = _blended_to_dict  # type: ignore[attr-defined]
