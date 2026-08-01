"""
Liquidity Monitor — Real-time order book depth and spread monitoring.

Monitors market liquidity to prevent trading in thin/degraded conditions:

  1. Order book depth monitoring (bid/ask volume within X% of mid)
  2. Spread monitoring (bid-ask spread vs historical norms)
  3. Position size reduction when liquidity drops
  4. Entry pause when spread widens beyond threshold
  5. Liquidity anomaly detection and alerting

All logic is deterministic. No LLM calls. Thresholds from config/risk.yaml.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class LiquidityState(StrEnum):
    """Current liquidity condition."""

    NORMAL = "NORMAL"
    THIN = "THIN"           # Reduced depth, wider spreads
    DEGRADED = "DEGRADE"    # Significantly reduced liquidity
    CRITICAL = "CRITICAL"   # Dangerous — halt entries


@dataclass(frozen=True)
class LiquidityConfig:
    """Immutable configuration for liquidity monitoring."""

    # Depth thresholds
    min_depth_usd: float = 100_000.0     # Min $100k within 2% of mid
    depth_warning_usd: float = 200_000.0 # Warning below $200k
    depth_pct_from_mid: float = 0.02     # Measure depth within 2% of mid-price

    # Spread thresholds
    max_spread_bps: float = 50.0         # 50 bps max spread (0.5%)
    warning_spread_bps: float = 30.0     # 30 bps warning
    spread_lookback: int = 100           # Historical spread samples for baseline

    # Position size adjustments
    thin_liquidity_size_mult: float = 0.5   # 50% size in thin liquidity
    degraded_size_mult: float = 0.25        # 25% size in degraded
    critical_size_mult: float = 0.0         # Block in critical

    # Anomaly detection
    depth_drop_threshold_pct: float = 0.5  # 50% drop in depth = anomaly
    spread_spike_multiplier: float = 3.0   # 3x normal spread = anomaly
    anomaly_window_seconds: int = 60       # Track anomalies over 1 min


@dataclass
class OrderBookSnapshot:
    """Simplified order book snapshot for liquidity analysis."""

    symbol: str
    bid_depth_usd: float   # Total bid volume in USD within range
    ask_depth_usd: float   # Total ask volume in USD within range
    best_bid: float
    best_ask: float
    spread_bps: float
    timestamp: float


@dataclass
class LiquidityAnomaly:
    """A detected liquidity anomaly."""

    symbol: str
    anomaly_type: str  # "depth_drop", "spread_spike", "book_imbalance"
    severity: str      # "WARNING", "CRITICAL"
    details: str
    detected_at: float


@dataclass
class LiquidityMetrics:
    """Current liquidity metrics for a symbol."""

    symbol: str
    state: LiquidityState
    bid_depth_usd: float
    ask_depth_usd: float
    spread_bps: float
    spread_percentile: float  # Where current spread sits vs history (0-1)
    size_multiplier: float
    anomalies_24h: int


class LiquidityMonitor:
    """Monitors order book liquidity and adjusts trading accordingly.

    Architecture:
      - Maintains rolling history of depth and spread per symbol
      - Classifies liquidity state: NORMAL → THIN → DEGRADED → CRITICAL
      - Provides position size multipliers based on liquidity
      - Detects anomalies (sudden depth drops, spread spikes)
      - Alerts on liquidity degradation

    Integration:
      - Call `update(symbol, bid_depth, ask_depth, best_bid, best_ask)` on order book updates
      - Call `get_state(symbol)` for current classification
      - Call `get_size_multiplier(symbol)` for position sizing
      - Call `should_pause_entries(symbol)` for entry gating
    """

    def __init__(self, config: LiquidityConfig | None = None) -> None:
        self._config = config or LiquidityConfig()

        # Per-symbol order book history
        self._snapshots: dict[str, deque[OrderBookSnapshot]] = {}

        # Per-symbol spread baseline (rolling average)
        self._spread_history: dict[str, deque[float]] = {}

        # Per-symbol depth baseline
        self._depth_history: dict[str, deque[float]] = {}

        # Per-symbol state
        self._states: dict[str, LiquidityState] = {}

        # Per-symbol anomalies
        self._anomalies: dict[str, deque[LiquidityAnomaly]] = {}

        logger.info(
            f"LiquidityMonitor initialized: "
            f"min_depth=${self._config.min_depth_usd:,.0f}, "
            f"max_spread={self._config.max_spread_bps}bps"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        symbol: str,
        bid_depth_usd: float,
        ask_depth_usd: float,
        best_bid: float,
        best_ask: float,
        timestamp: float | None = None,
    ) -> LiquidityState:
        """Update with new order book data. Returns current liquidity state.

        Args:
            symbol: Trading pair.
            bid_depth_usd: Total bid depth in USD within configured range.
            ask_depth_usd: Total ask depth in USD within configured range.
            best_bid: Best bid price.
            best_ask: Best ask price.
            timestamp: Unix timestamp.

        Returns:
            Current LiquidityState for this symbol.
        """
        now = timestamp or time.time()

        # Calculate spread in basis points
        mid = (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 0
        spread_bps = ((best_ask - best_bid) / mid * 10_000) if mid > 0 else 0

        snapshot = OrderBookSnapshot(
            symbol=symbol,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            best_bid=best_bid,
            best_ask=best_ask,
            spread_bps=spread_bps,
            timestamp=now,
        )

        # Initialize if needed
        if symbol not in self._snapshots:
            self._snapshots[symbol] = deque(maxlen=1000)
            self._spread_history[symbol] = deque(
                maxlen=self._config.spread_lookback
            )
            self._depth_history[symbol] = deque(
                maxlen=self._config.spread_lookback
            )
            self._states[symbol] = LiquidityState.NORMAL
            self._anomalies[symbol] = deque(maxlen=1000)

        self._snapshots[symbol].append(snapshot)
        self._spread_history[symbol].append(spread_bps)
        self._depth_history[symbol].append(bid_depth_usd + ask_depth_usd)

        # Evaluate state
        state = self._evaluate(symbol, snapshot, now)
        self._states[symbol] = state
        return state

    def get_state(self, symbol: str) -> LiquidityState:
        """Get current liquidity state without updating.

        Args:
            symbol: Trading pair.

        Returns:
            Current LiquidityState (NORMAL if unknown).
        """
        return self._states.get(symbol, LiquidityState.NORMAL)

    def get_size_multiplier(self, symbol: str) -> float:
        """Get position size multiplier based on current liquidity.

        Args:
            symbol: Trading pair.

        Returns:
            Multiplier 0.0-1.0 (0.0 = block all entries).
        """
        state = self.get_state(symbol)

        if state == LiquidityState.CRITICAL:
            return self._config.critical_size_mult
        if state == LiquidityState.DEGRADED:
            return self._config.degraded_size_mult
        if state == LiquidityState.THIN:
            return self._config.thin_liquidity_size_mult
        return 1.0

    def should_pause_entries(self, symbol: str) -> bool:
        """Check if entries should be paused due to liquidity.

        Args:
            symbol: Trading pair.

        Returns:
            True if entries should be paused.
        """
        state = self.get_state(symbol)
        return state in (LiquidityState.DEGRADED, LiquidityState.CRITICAL)

    def get_metrics(self, symbol: str) -> LiquidityMetrics:
        """Get detailed liquidity metrics for a symbol.

        Args:
            symbol: Trading pair.

        Returns:
            LiquidityMetrics with current values and context.
        """
        snapshots = self._snapshots.get(symbol, deque())
        latest = snapshots[-1] if snapshots else None

        spread_history = self._spread_history.get(symbol, deque())
        current_spread = latest.spread_bps if latest else 0.0

        # Calculate spread percentile
        if spread_history and len(spread_history) > 1:
            sorted_spreads = sorted(spread_history)
            rank = sum(1 for s in sorted_spreads if s <= current_spread)
            spread_percentile = rank / len(sorted_spreads)
        else:
            spread_percentile = 0.5

        # Count recent anomalies
        now = time.time()
        anomalies = self._anomalies.get(symbol, deque())
        window_start = now - 86400  # 24h
        recent_anomalies = sum(1 for a in anomalies if a.detected_at >= window_start)

        return LiquidityMetrics(
            symbol=symbol,
            state=self.get_state(symbol),
            bid_depth_usd=latest.bid_depth_usd if latest else 0.0,
            ask_depth_usd=latest.ask_depth_usd if latest else 0.0,
            spread_bps=current_spread,
            spread_percentile=spread_percentile,
            size_multiplier=self.get_size_multiplier(symbol),
            anomalies_24h=recent_anomalies,
        )

    def get_recent_anomalies(
        self, symbol: str, hours: float = 24.0
    ) -> list[LiquidityAnomaly]:
        """Get recent liquidity anomalies for a symbol.

        Args:
            symbol: Trading pair.
            hours: Lookback period in hours.

        Returns:
            List of LiquidityAnomaly events.
        """
        now = time.time()
        window_start = now - hours * 3600
        anomalies = self._anomalies.get(symbol, deque())
        return [a for a in anomalies if a.detected_at >= window_start]

    def reset(self, symbol: str | None = None) -> None:
        """Reset state for a symbol or all symbols."""
        if symbol:
            self._snapshots.pop(symbol, None)
            self._spread_history.pop(symbol, None)
            self._depth_history.pop(symbol, None)
            self._states.pop(symbol, None)
            self._anomalies.pop(symbol, None)
        else:
            self._snapshots.clear()
            self._spread_history.clear()
            self._depth_history.clear()
            self._states.clear()
            self._anomalies.clear()

    # ------------------------------------------------------------------
    # Internal evaluation
    # ------------------------------------------------------------------

    def _evaluate(
        self, symbol: str, snapshot: OrderBookSnapshot, now: float
    ) -> LiquidityState:
        """Evaluate liquidity state from current snapshot and history."""
        total_depth = snapshot.bid_depth_usd + snapshot.ask_depth_usd

        # Check for anomalies first
        self._check_anomalies(symbol, snapshot, now)

        # Classify based on depth and spread
        depth_ok = total_depth >= self._config.min_depth_usd
        spread_ok = snapshot.spread_bps <= self._config.max_spread_bps

        if not depth_ok and not spread_ok:
            return LiquidityState.CRITICAL

        if not depth_ok or snapshot.spread_bps > self._config.max_spread_bps:
            return LiquidityState.DEGRADED

        if (
            total_depth < self._config.depth_warning_usd
            or snapshot.spread_bps > self._config.warning_spread_bps
        ):
            return LiquidityState.THIN

        return LiquidityState.NORMAL

    def _check_anomalies(
        self, symbol: str, snapshot: OrderBookSnapshot, now: float
    ) -> None:
        """Check for liquidity anomalies and record them."""
        depth_history = self._depth_history.get(symbol, deque())
        spread_history = self._spread_history.get(symbol, deque())

        total_depth = snapshot.bid_depth_usd + snapshot.ask_depth_usd

        # Depth drop anomaly
        if len(depth_history) >= 10:
            avg_depth = sum(list(depth_history)[-10:]) / 10
            if avg_depth > 0:
                depth_drop = (avg_depth - total_depth) / avg_depth
                if depth_drop >= self._config.depth_drop_threshold_pct:
                    anomaly = LiquidityAnomaly(
                        symbol=symbol,
                        anomaly_type="depth_drop",
                        severity="CRITICAL" if depth_drop > 0.8 else "WARNING",
                        details=f"Depth dropped {depth_drop:.0%} "
                        f"(from ${avg_depth:,.0f} to ${total_depth:,.0f})",
                        detected_at=now,
                    )
                    self._anomalies[symbol].append(anomaly)
                    logger.warning(f"Liquidity anomaly: {anomaly.details}")

        # Spread spike anomaly
        if len(spread_history) >= 10:
            avg_spread = sum(list(spread_history)[-10:]) / 10
            if avg_spread > 0:
                spread_ratio = snapshot.spread_bps / avg_spread
                if spread_ratio >= self._config.spread_spike_multiplier:
                    anomaly = LiquidityAnomaly(
                        symbol=symbol,
                        anomaly_type="spread_spike",
                        severity="WARNING",
                        details=f"Spread spiked {spread_ratio:.1f}x "
                        f"(from {avg_spread:.1f}bps to {snapshot.spread_bps:.1f}bps)",
                        detected_at=now,
                    )
                    self._anomalies[symbol].append(anomaly)
                    logger.warning(f"Liquidity anomaly: {anomaly.details}")

        # Book imbalance anomaly
        if snapshot.bid_depth_usd > 0 and snapshot.ask_depth_usd > 0:
            imbalance = abs(
                snapshot.bid_depth_usd - snapshot.ask_depth_usd
            ) / max(snapshot.bid_depth_usd, snapshot.ask_depth_usd)
            if imbalance > 0.8:
                heavier = (
                    "bid" if snapshot.bid_depth_usd > snapshot.ask_depth_usd else "ask"
                )
                anomaly = LiquidityAnomaly(
                    symbol=symbol,
                    anomaly_type="book_imbalance",
                    severity="WARNING",
                    details=f"Order book heavily imbalanced toward {heavier} "
                    f"({imbalance:.0%} imbalance)",
                    detected_at=now,
                )
                self._anomalies[symbol].append(anomaly)
