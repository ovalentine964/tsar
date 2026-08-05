"""
TSAR — Information Edge Agent (Anti-Loss: Information Asymmetry).

Breaks the information asymmetry that causes 78% of retail traders to lose.

Aggregates all positioning, order flow, and microstructure data into
actionable "information advantage" signals. When retail is wrong,
this agent identifies it. When institutions diverge from retail,
this agent flags it.

Subscribes to:
  - tsar:stream:sentiment (from SentimentAgent)
  - tsar:stream:regime (from RegimeDetector)
  - tsar:stream:on_chain (from on-chain tools)

Publishes to:
  - tsar:stream:information_edge

Core insight: Retail traders lose because they can't see what
institutions see. This agent gives them that vision.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.agents.base import BaseAgent
from src.tools.market_microstructure import (
    LiquidityHeatmap,
    MarketMicrostructureTools,
    OrderBookImbalance,
    SpreadAnalysis,
    TickAnalysis,
    VolumeProfile,
)
from src.tools.order_flow import (
    InstitutionalFlow,
    NetPositioning,
    OrderFlowTools,
    RetailPositioning,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class InformationEdgeSignal:
    """A signal derived from information asymmetry analysis.

    Attributes:
        asset: Asset symbol.
        signal_type: Type of signal (contrarian, institutional_divergence, etc.).
        direction: "long", "short", or "neutral".
        strength: Signal strength (0-1).
        confidence: Confidence in the signal (0-1).
        reasoning: Human-readable explanation.
        retail_positioning: What retail is doing.
        institutional_positioning: What institutions are doing.
        microstructure_bias: What order flow suggests.
        components: Number of data sources that contributed.
        timestamp: When the signal was generated.
    """

    asset: str
    signal_type: str
    direction: str
    strength: float
    confidence: float
    reasoning: str
    retail_positioning: str = "unknown"
    institutional_positioning: str = "unknown"
    microstructure_bias: str = "neutral"
    components: int = 0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "strength": self.strength,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "retail_positioning": self.retail_positioning,
            "institutional_positioning": self.institutional_positioning,
            "microstructure_bias": self.microstructure_bias,
            "components": self.components,
            "timestamp": self.timestamp,
        }


@dataclass
class InformationSnapshot:
    """Complete information asymmetry analysis for an asset.

    Attributes:
        asset: Asset symbol.
        net_positioning: Aggregate positioning analysis.
        institutional_flow: Institutional vs retail flow.
        retail_sentiment: Retail positioning data.
        spread_analysis: Bid-ask spread data.
        orderbook_imbalance: Buy/sell pressure.
        volume_profile: Volume-at-price analysis.
        liquidity_heatmap: Where the stops are.
        tick_analysis: Tick-level flow.
        contrarian_signal: Signal when retail is likely wrong.
        information_edge_signals: All generated signals.
        timestamp: When the snapshot was taken.
    """

    asset: str
    net_positioning: NetPositioning | None = None
    institutional_flow: InstitutionalFlow | None = None
    retail_sentiment: RetailPositioning | None = None
    spread_analysis: SpreadAnalysis | None = None
    orderbook_imbalance: OrderBookImbalance | None = None
    volume_profile: VolumeProfile | None = None
    liquidity_heatmap: LiquidityHeatmap | None = None
    tick_analysis: TickAnalysis | None = None
    contrarian_signal: InformationEdgeSignal | None = None
    information_edge_signals: list[InformationEdgeSignal] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "net_positioning": self._safe_dict(self.net_positioning),
            "institutional_flow": self._safe_dict(self.institutional_flow),
            "retail_sentiment": self._safe_dict(self.retail_sentiment),
            "spread_analysis": self._safe_dict(self.spread_analysis),
            "orderbook_imbalance": self._safe_dict(self.orderbook_imbalance),
            "volume_profile": self._safe_dict(self.volume_profile),
            "liquidity_heatmap": self._safe_dict(self.liquidity_heatmap),
            "tick_analysis": self._safe_dict(self.tick_analysis),
            "contrarian_signal": self.contrarian_signal.to_dict()
            if self.contrarian_signal
            else None,
            "information_edge_signals": [s.to_dict() for s in self.information_edge_signals],
            "timestamp": self.timestamp,
        }

    @staticmethod
    def _safe_dict(obj: Any) -> dict | None:
        if obj is None:
            return None
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return None


# ═══════════════════════════════════════════════════════════════════════
# INFORMATION EDGE AGENT
# ═══════════════════════════════════════════════════════════════════════


class InformationAgent(BaseAgent):
    """Information Edge Agent — breaks information asymmetry.

    This agent is the reason retail traders can compete with
    institutions. It aggregates COT reports, retail positioning,
    whale movements, order flow, and microstructure data into
    actionable signals.

    Key capabilities:
    - Identifies when retail is wrong (contrarian signals)
    - Detects institutional vs retail divergence
    - Reads order book pressure and microstructure
    - Maps liquidity zones where stops cluster
    - Provides tick-level flow analysis

    Subscribes to sentiment and regime streams for context.
    Publishes information edge signals.

    Attributes:
        AGENT_NAME: "information_agent"
        ROLE: "ANALYSIS"
    """

    AGENT_NAME = "information_agent"
    ROLE = "ANALYSIS"
    PUBLISH_STREAM = "information_edge"
    SUBSCRIBE_STREAMS = ["sentiment", "regime", "on_chain"]

    # Default assets to monitor
    DEFAULT_ASSETS = [
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "GOLD",
        "SP500",
    ]

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        publisher: Any | None = None,
        subscriber: Any | None = None,
        assets: list[str] | None = None,
    ) -> None:
        """Initialize the Information Agent.

        Args:
            config: TSAR configuration.
            trading_mode: "paper" or "live".
            publisher: Event publisher.
            subscriber: Event subscriber.
            assets: Assets to monitor (defaults to DEFAULT_ASSETS).
        """
        super().__init__(config, trading_mode, publisher, subscriber)

        self.assets = assets or self.DEFAULT_ASSETS
        self.order_flow = OrderFlowTools(cache_ttl=1800)
        self.microstructure = MarketMicrostructureTools(cache_ttl=60)

        # State tracking
        self._last_snapshot: dict[str, InformationSnapshot] = {}
        self._last_regime: str = "unknown"
        self._last_sentiment: dict[str, Any] = {}
        self._cycle_count: int = 0

    async def run_cycle(self) -> None:
        """Main agent cycle — analyze all assets for information edge.

        Runs every cycle to:
        1. Gather order flow data (COT, retail, whale)
        2. Analyze microstructure (spread, order book, volume)
        3. Generate contrarian signals when retail is wrong
        4. Detect institutional vs retail divergence
        5. Publish information edge signals
        """
        self._cycle_count += 1
        logger.info(
            "InformationAgent cycle #%d — analyzing %d assets",
            self._cycle_count,
            len(self.assets),
        )

        # Analyze all assets (with some concurrency control)
        semaphore = asyncio.Semaphore(3)

        async def analyze_with_limit(asset: str) -> InformationSnapshot:
            async with semaphore:
                return await self._analyze_asset(asset)

        snapshots = await asyncio.gather(
            *[analyze_with_limit(a) for a in self.assets],
            return_exceptions=True,
        )

        # Process results and publish signals
        signals: list[InformationEdgeSignal] = []
        for i, snap in enumerate(snapshots):
            asset = self.assets[i]
            if isinstance(snap, Exception):
                logger.warning("Analysis failed for %s: %s", asset, snap)
                continue

            self._last_snapshot[asset] = snap
            signals.extend(snap.information_edge_signals)

        # Publish the strongest signals
        if signals:
            signals.sort(key=lambda s: s.strength * s.confidence, reverse=True)
            top_signals = signals[:5]

            for signal in top_signals:
                await self.publish_event(
                    event_type="information_edge.signal",
                    data=signal.to_dict(),
                )

            logger.info(
                "Published %d information edge signals (from %d total)",
                len(top_signals),
                len(signals),
            )

        # Publish summary
        await self._publish_summary(signals)

    async def _analyze_asset(self, asset: str) -> InformationSnapshot:
        """Perform comprehensive information asymmetry analysis for an asset.

        Args:
            asset: Asset symbol.

        Returns:
            InformationSnapshot with all analysis results.
        """
        snapshot = InformationSnapshot(
            asset=asset,
            timestamp=datetime.now(UTC).isoformat(),
        )

        # Gather all data concurrently
        results = await asyncio.gather(
            self.order_flow.get_net_positioning(asset),
            self.order_flow.classify_institutional_flow(asset),
            self.order_flow.get_retail_positioning(asset),
            self.microstructure.analyze_spread(self._to_pair(asset)),
            self.microstructure.detect_orderbook_imbalance(self._to_pair(asset)),
            self.microstructure.compute_volume_profile(self._to_pair(asset)),
            self.microstructure.generate_liquidity_heatmap(self._to_pair(asset)),
            self.microstructure.analyze_ticks(self._to_pair(asset)),
            return_exceptions=True,
        )

        # Unpack results (graceful on failures)
        names = [
            "net_positioning",
            "institutional_flow",
            "retail_sentiment",
            "spread",
            "orderbook",
            "volume_profile",
            "liquidity",
            "ticks",
        ]
        for name, result in zip(names, results, strict=False):
            if isinstance(result, Exception):
                logger.debug("%s failed for %s: %s", name, asset, result)
                continue
            setattr(snapshot, name if name != "spread" else "spread_analysis", result)

        # Fix attribute names
        if not isinstance(results[3], Exception):
            snapshot.spread_analysis = results[3]
        if not isinstance(results[4], Exception):
            snapshot.orderbook_imbalance = results[4]
        if not isinstance(results[5], Exception):
            snapshot.volume_profile = results[5]
        if not isinstance(results[6], Exception):
            snapshot.liquidity_heatmap = results[6]
        if not isinstance(results[7], Exception):
            snapshot.tick_analysis = results[7]

        # Generate signals
        snapshot.information_edge_signals = self._generate_signals(snapshot)
        snapshot.contrarian_signal = self._generate_contrarian_signal(snapshot)

        return snapshot

    def _generate_signals(self, snapshot: InformationSnapshot) -> list[InformationEdgeSignal]:
        """Generate information edge signals from a snapshot.

        Args:
            snapshot: Complete analysis snapshot.

        Returns:
            List of generated signals.
        """
        signals: list[InformationEdgeSignal] = []
        asset = snapshot.asset
        now = datetime.now(UTC).isoformat()

        # ─────────────────────────────────────────────────────────────
        # Signal 1: Institutional-Retail Divergence
        # ─────────────────────────────────────────────────────────────
        if snapshot.institutional_flow and snapshot.institutional_flow.divergence:
            flow = snapshot.institutional_flow
            signals.append(
                InformationEdgeSignal(
                    asset=asset,
                    signal_type="institutional_divergence",
                    direction=flow.smart_money_signal,
                    strength=flow.confidence,
                    confidence=flow.confidence,
                    reasoning=(
                        f"Institutions are {flow.institutional_bias} while retail is "
                        f"{flow.retail_bias}. Follow smart money."
                    ),
                    retail_positioning=flow.retail_bias,
                    institutional_positioning=flow.institutional_bias,
                    components=flow.components,
                    timestamp=now,
                )
            )

        # ─────────────────────────────────────────────────────────────
        # Signal 2: Retail Is Wrong (Contrarian)
        # ─────────────────────────────────────────────────────────────
        if snapshot.retail_sentiment:
            retail = snapshot.retail_sentiment
            if retail.crowd_wrong_probability > 0.5:
                # Retail is likely wrong — fade them
                direction = "short" if retail.sentiment_bias == "bullish" else "long"
                signals.append(
                    InformationEdgeSignal(
                        asset=asset,
                        signal_type="contrarian_retail",
                        direction=direction,
                        strength=retail.crowd_wrong_probability,
                        confidence=retail.crowd_wrong_probability * 0.8,
                        reasoning=(
                            f"Retail is {retail.long_pct:.0f}% long / {retail.short_pct:.0f}% short. "
                            f"At this extreme, retail is wrong {retail.crowd_wrong_probability:.0%} "
                            f"of the time. Fade the crowd."
                        ),
                        retail_positioning=f"{retail.long_pct:.0f}% long",
                        components=1,
                        timestamp=now,
                    )
                )

        # ─────────────────────────────────────────────────────────────
        # Signal 3: Order Book Pressure
        # ─────────────────────────────────────────────────────────────
        if snapshot.orderbook_imbalance:
            ob = snapshot.orderbook_imbalance
            if ob.pressure_strength > 0.5:
                direction = "long" if ob.pressure == "buy_pressure" else "short"
                signals.append(
                    InformationEdgeSignal(
                        asset=asset,
                        signal_type="orderbook_pressure",
                        direction=direction,
                        strength=ob.pressure_strength,
                        confidence=ob.pressure_strength * 0.7,
                        reasoning=(
                            f"Order book shows {ob.pressure} with ratio {ob.imbalance_ratio:.2f}. "
                            f"Bid wall: {ob.bid_wall:.0f}, Ask wall: {ob.ask_wall:.0f}."
                        ),
                        microstructure_bias=ob.pressure,
                        components=1,
                        timestamp=now,
                    )
                )

        # ─────────────────────────────────────────────────────────────
        # Signal 4: Tick-Level Flow
        # ─────────────────────────────────────────────────────────────
        if snapshot.tick_analysis:
            ticks = snapshot.tick_analysis
            if ticks.micro_trend != "neutral":
                signals.append(
                    InformationEdgeSignal(
                        asset=asset,
                        signal_type="tick_flow",
                        direction=ticks.micro_trend,
                        strength=min(abs(ticks.taker_buy_ratio - 0.5) * 2, 1.0),
                        confidence=0.5,
                        reasoning=(
                            f"Tick analysis: {ticks.micro_trend} micro-trend. "
                            f"Taker buy ratio: {ticks.taker_buy_ratio:.2f}. "
                            f"Large trade pct: {ticks.large_trade_pct:.1f}%."
                        ),
                        microstructure_bias=ticks.micro_trend,
                        components=1,
                        timestamp=now,
                    )
                )

        # ─────────────────────────────────────────────────────────────
        # Signal 5: Volume Profile (POC Magnet)
        # ─────────────────────────────────────────────────────────────
        if snapshot.volume_profile and snapshot.spread_analysis:
            vp = snapshot.volume_profile
            sp = snapshot.spread_analysis
            if sp.mid_price > 0 and vp.poc_price > 0:
                distance_pct = (sp.mid_price - vp.poc_price) / vp.poc_price * 100
                if abs(distance_pct) > 1.0:
                    direction = "short" if distance_pct > 0 else "long"
                    signals.append(
                        InformationEdgeSignal(
                            asset=asset,
                            signal_type="poc_magnet",
                            direction=direction,
                            strength=min(abs(distance_pct) / 5.0, 0.8),
                            confidence=0.5,
                            reasoning=(
                                f"Price ({sp.mid_price:.2f}) is {abs(distance_pct):.1f}% "
                                f"{'above' if distance_pct > 0 else 'below'} the POC ({vp.poc_price:.2f}). "
                                f"Volume profile suggests price is drawn to POC."
                            ),
                            components=1,
                            timestamp=now,
                        )
                    )

        # ─────────────────────────────────────────────────────────────
        # Signal 6: Composite Net Positioning
        # ─────────────────────────────────────────────────────────────
        if snapshot.net_positioning:
            net = snapshot.net_positioning
            if net.signal_strength > 0.4:
                signals.append(
                    InformationEdgeSignal(
                        asset=asset,
                        signal_type="composite_positioning",
                        direction=net.composite_signal,
                        strength=net.signal_strength,
                        confidence=net.signal_strength * 0.85,
                        reasoning=(
                            f"Composite positioning: {net.composite_signal} "
                            f"(strength: {net.signal_strength:.2f}). "
                            f"COT: {net.cot_signal}, Retail: {net.retail_signal}, "
                            f"Whale: {net.whale_signal}, Derivatives: {net.derivatives_signal}."
                        ),
                        retail_positioning=net.retail_signal,
                        institutional_positioning=net.cot_signal,
                        components=4,
                        timestamp=now,
                    )
                )

        return signals

    def _generate_contrarian_signal(
        self, snapshot: InformationSnapshot
    ) -> InformationEdgeSignal | None:
        """Generate the strongest contrarian signal.

        Contrarian signals are the most valuable — they identify
        when the crowd is wrong and position against them.

        Args:
            snapshot: Complete analysis snapshot.

        Returns:
            The strongest contrarian signal, or None.
        """
        contrarian_signals = [
            s
            for s in snapshot.information_edge_signals
            if s.signal_type in ("contrarian_retail", "institutional_divergence")
        ]

        if not contrarian_signals:
            return None

        # Return the strongest
        return max(contrarian_signals, key=lambda s: s.strength * s.confidence)

    def _to_pair(self, asset: str) -> str:
        """Convert asset name to trading pair format.

        "BTC/USDT" → "BTC/USDT", "GOLD" → "GOLD/USDT", "SP500" → "SP500/USDT"
        """
        if "/" in asset:
            return asset
        return f"{asset}/USDT"

    async def _publish_summary(self, signals: list[InformationEdgeSignal]) -> None:
        """Publish a summary of all information edge signals."""
        if not signals:
            return

        # Group by signal type
        by_type: dict[str, list[InformationEdgeSignal]] = {}
        for s in signals:
            by_type.setdefault(s.signal_type, []).append(s)

        summary = {
            "total_signals": len(signals),
            "by_type": {t: len(s) for t, s in by_type.items()},
            "strongest_signal": max(
                (s.to_dict() for s in signals),
                key=lambda d: d["strength"] * d["confidence"],
                default=None,
            ),
            "assets_analyzed": len(self._last_snapshot),
            "cycle": self._cycle_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        await self.publish_event(
            event_type="information_edge.summary",
            data=summary,
        )

    # ─────────────────────────────────────────────────────────────────
    # Event Handling
    # ─────────────────────────────────────────────────────────────────

    async def on_sentiment_event(self, event: Any) -> None:
        """Handle incoming sentiment events.

        Updates internal state with sentiment data from SentimentAgent.
        """
        try:
            data = event.data if hasattr(event, "data") else event
            if isinstance(data, dict):
                self._last_sentiment = data
                logger.debug("Updated sentiment state: %s", data.get("composite_score"))
        except Exception as e:
            logger.debug("Failed to process sentiment event: %s", e)

    async def on_regime_event(self, event: Any) -> None:
        """Handle incoming regime events.

        Updates internal state with regime data from RegimeDetector.
        """
        try:
            data = event.data if hasattr(event, "data") else event
            if isinstance(data, dict):
                self._last_regime = data.get("regime", "unknown")
                logger.debug("Updated regime state: %s", self._last_regime)
        except Exception as e:
            logger.debug("Failed to process regime event: %s", e)

    async def on_on_chain_event(self, event: Any) -> None:
        """Handle incoming on-chain events.

        Updates internal state with on-chain data for whale detection.
        """
        try:
            data = event.data if hasattr(event, "data") else event
            logger.debug("Received on-chain event: %s", type(data))
        except Exception as e:
            logger.debug("Failed to process on-chain event: %s", e)

    # ─────────────────────────────────────────────────────────────────
    # Public API for direct queries
    # ─────────────────────────────────────────────────────────────────

    async def get_asset_analysis(self, asset: str) -> InformationSnapshot:
        """Get full information asymmetry analysis for a single asset.

        Can be called directly by other agents or the API layer.

        Args:
            asset: Asset symbol.

        Returns:
            Complete InformationSnapshot.
        """
        return await self._analyze_asset(asset)

    async def get_contrarian_signals(self) -> list[InformationEdgeSignal]:
        """Get all active contrarian signals across all assets.

        Returns:
            List of contrarian signals, sorted by strength.
        """
        all_signals: list[InformationEdgeSignal] = []
        for snap in self._last_snapshot.values():
            if snap.contrarian_signal:
                all_signals.append(snap.contrarian_signal)

        all_signals.sort(key=lambda s: s.strength * s.confidence, reverse=True)
        return all_signals

    async def get_information_edge_summary(self) -> dict[str, Any]:
        """Get a summary of the current information edge.

        Returns:
            Dict with summary of all information asymmetry analysis.
        """
        all_signals: list[InformationEdgeSignal] = []
        for snap in self._last_snapshot.values():
            all_signals.extend(snap.information_edge_signals)

        return {
            "assets_analyzed": len(self._last_snapshot),
            "total_signals": len(all_signals),
            "contrarian_signals": len(
                [s for s in all_signals if s.signal_type.startswith("contrarian")]
            ),
            "divergence_signals": len(
                [s for s in all_signals if s.signal_type == "institutional_divergence"]
            ),
            "current_regime": self._last_regime,
            "cycle_count": self._cycle_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.order_flow.close()
        await self.microstructure.close()
