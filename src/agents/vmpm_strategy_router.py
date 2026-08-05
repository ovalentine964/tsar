"""
VMPM Strategy Router — Regime-aware strategy orchestration agent.

This agent sits between SignalScout and RiskGuardian in the TSAR pipeline.
It receives market data, detects the current regime, and routes to the
optimal strategy (VMPM, Momentum, MeanReversion, or a blended combination).

Architecture:
  Market Data → RegimeDetector → VMPMStrategyRouter
    ├─ Trending  → VMPM trend mode + Momentum confirmation
    ├─ Ranging   → VMPM mean-reversion mode + MeanReversion confirmation
    ├─ Volatile  → Reduced sizing, VMPM with wider stops
    └─ Calm      → Normal VMPM execution

Signal blending:
  VMPM signal score (0-100) + Momentum/MeanReversion score (0-100)
  → Regime-weighted blend → Combined score → RiskGuardian

Subscribes to: tsar:stream:regime, tsar:stream:cartography
Publishes to:  tsar:stream:signals

Role: TRADE_PREVIEW
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.agents.base import BaseAgent
from src.strategy.genome import StrategyGenome
from src.strategy.mean_reversion import MeanReversionStrategy
from src.strategy.momentum import MomentumStrategy
from src.strategy.vmpm.strategy import VMPMStrategy

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

    VMPM_TREND = "vmpm_trend"
    VMPM_REVERSION = "vmpm_reversion"
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
    vmpm_weight: float  # 0.0 – 1.0
    fallback_weight: float  # 0.0 – 1.0
    position_size_mult: float  # Regime-based sizing multiplier
    reasoning: str


@dataclass
class BlendedSignal:
    """A signal produced by blending VMPM with another strategy."""

    side: str
    score: float  # 0.0 – 1.0 (blended)
    vmpm_score: float
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

# Default routing table: regime → (mode, vmpm_weight, fallback_weight, sizing_mult)
_ROUTING_TABLE: dict[MarketRegime, tuple[RoutingMode, float, float, float]] = {
    MarketRegime.STRONG_TREND_UP:   (RoutingMode.VMPM_TREND,       0.7, 0.3, 1.0),
    MarketRegime.STRONG_TREND_DOWN: (RoutingMode.VMPM_TREND,       0.7, 0.3, 1.0),
    MarketRegime.RANGING:           (RoutingMode.VMPM_REVERSION,   0.6, 0.4, 0.8),
    MarketRegime.HIGH_VOLATILITY:   (RoutingMode.BLENDED,          0.5, 0.5, 0.5),
    MarketRegime.UNCERTAIN:         (RoutingMode.SKIP,             0.0, 0.0, 0.0),
}


# ═══════════════════════════════════════════════════════════════════════
# VMPM STRATEGY ROUTER AGENT
# ═══════════════════════════════════════════════════════════════════════


class VMPMStrategyRouter(BaseAgent):
    """Regime-aware strategy router that orchestrates VMPM + legacy strategies.

    This agent:
    1. Receives market data and regime classification
    2. Routes to the optimal strategy combination based on regime
    3. Runs VMPM's 7-layer pipeline
    4. Optionally runs Momentum/MeanReversion for confirmation
    5. Blends signals with regime-weighted scoring
    6. Publishes the final signal to RiskGuardian

    The router implements the "super-strategy" concept: VMPM provides
    directional bias and institutional S/R zones, while Momentum/MeanReversion
    provide statistical confirmation. The regime determines the blend.
    """

    AGENT_NAME = "vmpm_strategy_router"
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
        self._vmpm: VMPMStrategy | None = None
        self._momentum: MomentumStrategy | None = None
        self._mean_reversion: MeanReversionStrategy | None = None

        # Current regime state
        self._current_regime: MarketRegime = MarketRegime.UNCERTAIN
        self._regime_confidence: float = 0.0
        self._regime_data: dict[str, Any] = {}

        # Routing config (overridable from config/genome)
        self._routing_table = dict(_ROUTING_TABLE)
        self._min_combined_score = config.get("vmpm_router", {}).get("min_combined_score", 0.55)
        self._require_vmpm_pass = config.get("vmpm_router", {}).get("require_vmpm_pass", False)

        # Metrics
        self._signals_routed = 0
        self._signals_blended = 0
        self._signals_skipped = 0

    async def on_initialize(self) -> None:
        """Initialize strategy instances."""
        logger.info("🔀 VMPMStrategyRouter initializing")

        # Load VMPM genome if available
        vmpm_genome = None
        try:
            vmpm_genome = StrategyGenome.from_yaml("config/strategies/vmpm.yaml")
            logger.info("Loaded VMPM genome: %s", vmpm_genome.name)
        except FileNotFoundError:
            logger.info("No VMPM genome YAML found — using defaults")

        self._vmpm = VMPMStrategy(genome=vmpm_genome)

        # Load Momentum genome
        momentum_genome = None
        try:
            momentum_genome = StrategyGenome.from_yaml("config/strategies/momentum.yaml")
        except FileNotFoundError:
            pass
        self._momentum = MomentumStrategy(genome=momentum_genome)

        # MeanReversion (no genome needed for Day1)
        self._mean_reversion = MeanReversionStrategy()

        logger.info(
            "VMPMStrategyRouter ready: VMPM=%s, Momentum=%s, MeanReversion=%s",
            self._vmpm is not None,
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
                self._current_regime.value, self._regime_confidence,
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

    def route_and_generate_signal(
        self, market_data: dict[str, Any]
    ) -> dict[str, Any] | None:
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

        # Step 2: Run VMPM pipeline
        vmpm_signal = self._run_vmpm(market_data)

        # Step 3: Run fallback strategy based on routing
        fallback_signal = self._run_fallback(market_data, routing)

        # Step 4: Blend signals
        blended = self._blend_signals(vmpm_signal, fallback_signal, routing, market_data)

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
        mode, vmpm_w, fallback_w, sizing = self._routing_table.get(
            self._current_regime,
            (RoutingMode.SKIP, 0.0, 0.0, 0.0),
        )

        # Determine primary and secondary strategies
        if mode == RoutingMode.VMPM_TREND:
            primary = "vmpm"
            secondary = "momentum"
        elif mode == RoutingMode.VMPM_REVERSION:
            primary = "vmpm"
            secondary = "mean_reversion"
        elif mode == RoutingMode.MOMENTUM:
            primary = "momentum"
            secondary = "vmpm"
        elif mode == RoutingMode.MEAN_REVERSION:
            primary = "mean_reversion"
            secondary = "vmpm"
        elif mode == RoutingMode.BLENDED:
            primary = "vmpm"
            secondary = "momentum"
        else:
            primary = ""
            secondary = None

        reasoning = (
            f"regime={self._current_regime.value} "
            f"conf={self._regime_confidence:.2f} "
            f"mode={mode.value} "
            f"vmpm_w={vmpm_w:.1f} fallback_w={fallback_w:.1f}"
        )

        return RoutingDecision(
            mode=mode,
            primary_strategy=primary,
            secondary_strategy=secondary,
            vmpm_weight=vmpm_w,
            fallback_weight=fallback_w,
            position_size_mult=sizing,
            reasoning=reasoning,
        )

    def _run_vmpm(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Run VMPM strategy's entry pipeline."""
        if self._vmpm is None:
            return None
        try:
            return self._vmpm.check_entry(data)
        except Exception as e:
            logger.warning("VMPM check_entry failed: %s", e)
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
        vmpm_signal: dict[str, Any] | None,
        fallback_signal: dict[str, Any] | None,
        routing: RoutingDecision,
        market_data: dict[str, Any],
    ) -> BlendedSignal | None:
        """Blend VMPM and fallback signals using regime-weighted scoring.

        Blending rules:
        - If only VMPM passes: use VMPM signal (scaled by vmpm_weight)
        - If only fallback passes: use fallback signal (scaled by fallback_weight)
        - If both pass and agree on direction: weighted average
        - If both pass but disagree: skip (conflicting signals)
        - If neither passes: no signal
        """
        vmpm_score = vmpm_signal.get("score", 0.0) if vmpm_signal else 0.0
        fallback_score = fallback_signal.get("score", 0.0) if fallback_signal else 0.0

        vmpm_side = vmpm_signal.get("side", "") if vmpm_signal else ""
        fallback_side = fallback_signal.get("side", "") if fallback_signal else ""

        # Neither strategy produced a signal
        if not vmpm_signal and not fallback_signal:
            return None

        # If require_vmpm_pass is set, VMPM must pass
        if self._require_vmpm_pass and not vmpm_signal:
            return None

        # Single strategy signals
        if vmpm_signal and not fallback_signal:
            return self._build_single_signal(vmpm_signal, routing, "vmpm_only", market_data)

        if fallback_signal and not vmpm_signal:
            return self._build_single_signal(fallback_signal, routing, f"{routing.secondary_strategy}_only", market_data)

        # Both signals exist — check direction agreement
        if vmpm_side != fallback_side:
            logger.debug(
                "Conflicting signals: VMPM=%s(%.2f) vs %s=%s(%.2f) — skipping",
                vmpm_side, vmpm_score, routing.secondary_strategy, fallback_side, fallback_score,
            )
            return None

        # Direction agrees — blend with regime weights
        combined_score = (
            vmpm_score * routing.vmpm_weight +
            fallback_score * routing.fallback_weight
        ) / (routing.vmpm_weight + routing.fallback_weight)

        # Check minimum combined score
        if combined_score < self._min_combined_score:
            return None

        # Use VMPM's trade parameters (S/R levels are more precise)
        entry = vmpm_signal.get("entry_price", 0.0) or fallback_signal.get("entry_price", 0.0)
        sl = vmpm_signal.get("stop_loss", 0.0) or fallback_signal.get("stop_loss", 0.0)
        tp = vmpm_signal.get("take_profit", 0.0) or fallback_signal.get("take_profit", 0.0)
        rr = vmpm_signal.get("risk_reward", 0.0) or fallback_signal.get("risk_reward", 0.0)

        # Position sizing: base * regime multiplier
        base_pct = vmpm_signal.get("position_size_pct", 2.0)
        position_pct = base_pct * routing.position_size_mult

        symbol = market_data.get("symbol", "?")

        return BlendedSignal(
            side=vmpm_side,
            score=round(combined_score, 4),
            vmpm_score=round(vmpm_score, 4),
            fallback_score=round(fallback_score, 4),
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            risk_reward=rr,
            strategy="vmpm_blend",
            routing_mode=routing.mode.value,
            regime=self._current_regime.value,
            position_size_pct=position_pct,
            reasoning=(
                f"blend: vmpm={vmpm_score:.2f}×{routing.vmpm_weight:.1f} + "
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
        weight = routing.vmpm_weight if "vmpm" in label else routing.fallback_weight
        scaled_score = score * weight

        if scaled_score < self._min_combined_score:
            return None

        base_pct = signal.get("position_size_pct", 2.0)
        position_pct = base_pct * routing.position_size_mult

        return BlendedSignal(
            side=signal.get("side", "buy"),
            score=round(scaled_score, 4),
            vmpm_score=round(score if "vmpm" in label else 0.0, 4),
            fallback_score=round(score if "vmpm" not in label else 0.0, 4),
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
        Enables the geneticist to evolve VMPM's routing weights and
        regime-specific behavior.

        Args:
            genome: Evolved StrategyGenome with routing parameters.
        """
        params = genome.params

        # Update routing table weights from genome
        for regime_name in ("strong_trend_up", "strong_trend_down", "ranging", "high_volatility"):
            vmpm_w_key = f"routing_{regime_name}_vmpm_weight"
            sizing_key = f"routing_{regime_name}_sizing_mult"

            if vmpm_w_key in params or sizing_key in params:
                try:
                    regime = MarketRegime(regime_name)
                except ValueError:
                    continue

                old_mode, old_vmpm, old_fallback, old_sizing = self._routing_table[regime]
                new_vmpm = params.get(vmpm_w_key, old_vmpm)
                new_sizing = params.get(sizing_key, old_sizing)
                new_fallback = 1.0 - new_vmpm

                self._routing_table[regime] = (old_mode, new_vmpm, new_fallback, new_sizing)

        # Update threshold
        if "min_combined_score" in params:
            self._min_combined_score = params["min_combined_score"]

        logger.info("VMPMStrategyRouter updated from genome '%s'", genome.name)

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
                    "vmpm_weight": vw,
                    "fallback_weight": fw,
                    "sizing_mult": sm,
                }
                for regime, (mode, vw, fw, sm) in self._routing_table.items()
            },
        }

    def get_health(self) -> dict[str, Any]:
        """Return health status including routing metrics."""
        health = super().get_health()
        health.update({
            "current_regime": self._current_regime.value,
            "signals_routed": self._signals_routed,
            "signals_blended": self._signals_blended,
            "signals_skipped": self._signals_skipped,
        })
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
            "vmpm_score": blended.vmpm_score,
            "fallback_score": blended.fallback_score,
        },
    }


# Monkey-patch to_dict onto BlendedSignal
BlendedSignal.to_dict = _blended_to_dict  # type: ignore[attr-defined]
