"""
Correlation Breakdown Detector — Monitor inter-asset correlation shifts.

Cryptocurrency markets often exhibit high correlation (BTC/ETH moving together).
When correlations break down, it signals regime change and increased risk.

This module:
  1. Monitors BTC/ETH (and other pairs) correlation in real-time
  2. Detects when correlation drops below historical norms
  3. Alerts and reduces exposure when correlation breaks
  4. Tracks correlation regime changes over time
  5. Adjusts portfolio allocation when correlations shift

All logic is deterministic. No LLM calls. Thresholds from config/risk.yaml.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class CorrelationRegime(StrEnum):
    """Correlation regime classification."""

    HIGH_CORRELATION = "HIGH"  # Correlation > 0.7 — normal crypto behavior
    MODERATE_CORRELATION = "MOD"  # 0.4 - 0.7 — watch closely
    LOW_CORRELATION = "LOW"  # 0.2 - 0.4 — regime change warning
    DECORRELATED = "DECOUPLED"  # < 0.2 — major regime shift
    NEGATIVE = "NEGATIVE"  # < 0 — assets moving opposite


@dataclass(frozen=True)
class CorrelationConfig:
    """Immutable configuration for correlation monitoring."""

    # Correlation thresholds
    high_threshold: float = 0.7  # Above this = normal
    moderate_threshold: float = 0.4  # Below this = warning
    low_threshold: float = 0.2  # Below this = regime break
    negative_threshold: float = 0.0  # Below this = negative correlation

    # Calculation parameters
    lookback_periods: int = 50  # Rolling window for correlation calc
    min_periods: int = 20  # Minimum data points for valid calc

    # Alert thresholds
    correlation_drop_alert: float = 0.3  # Alert if drops by 0.3+ in short time
    alert_window_seconds: int = 3600  # Track drops over 1 hour

    # Exposure adjustment
    decorrelated_exposure_mult: float = 0.5  # 50% exposure when decorrelated
    negative_exposure_mult: float = 0.25  # 25% exposure when negative
    low_corr_exposure_mult: float = 0.75  # 75% exposure when low

    # Default monitored pairs
    default_pairs: tuple[tuple[str, str], ...] = (("BTC/USDT", "ETH/USDT"),)


@dataclass
class CorrelationDataPoint:
    """A single correlation observation."""

    correlation: float
    timestamp: float


@dataclass
class CorrelationRegimeChange:
    """Record of a correlation regime transition."""

    pair: tuple[str, str]
    from_regime: CorrelationRegime
    to_regime: CorrelationRegime
    correlation: float
    detected_at: float


@dataclass
class CorrelationMetrics:
    """Current correlation metrics for a pair."""

    pair: tuple[str, str]
    current_correlation: float
    regime: CorrelationRegime
    exposure_multiplier: float
    regime_changes_24h: int
    trend: str  # "rising", "falling", "stable"


class CorrelationBreakDetector:
    """Monitors inter-asset correlation and detects regime changes.

    Architecture:
      - Maintains rolling price windows for each monitored pair
      - Calculates Pearson correlation over configurable lookback
      - Classifies correlation regime (HIGH → MODERATE → LOW → DECOUPLED)
      - Triggers alerts and exposure reduction on regime breaks
      - Tracks regime change frequency for portfolio adjustment

    Integration:
      - Call `update(symbol, price)` on every price tick
      - Call `get_metrics(pair)` for current correlation state
      - Call `get_exposure_multiplier(pair)` for portfolio sizing
      - Call `get_regime(pair)` for current regime classification
    """

    def __init__(self, config: CorrelationConfig | None = None) -> None:
        self._config = config or CorrelationConfig()

        # Per-symbol price history: symbol → deque of (price, timestamp)
        self._price_history: dict[str, deque[tuple[float, float]]] = {}

        # Per-pair correlation history: (sym_a, sym_b) → deque of CorrelationDataPoint
        self._correlation_history: dict[tuple[str, str], deque[CorrelationDataPoint]] = {}

        # Per-pair current regime
        self._regimes: dict[tuple[str, str], CorrelationRegime] = {}

        # Per-pair regime change log
        self._regime_changes: dict[tuple[str, str], deque[CorrelationRegimeChange]] = {}

        # Monitored pairs
        self._monitored_pairs: list[tuple[str, str]] = list(self._config.default_pairs)

        logger.info(
            f"CorrelationBreakDetector initialized: "
            f"pairs={len(self._monitored_pairs)}, "
            f"lookback={self._config.lookback_periods}, "
            f"high_threshold={self._config.high_threshold}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_pair(self, symbol_a: str, symbol_b: str) -> None:
        """Add a pair to monitor.

        Args:
            symbol_a: First trading pair (e.g. "BTC/USDT").
            symbol_b: Second trading pair (e.g. "ETH/USDT").
        """
        pair = (symbol_a, symbol_b)
        if pair not in self._monitored_pairs:
            self._monitored_pairs.append(pair)
            logger.info(f"Now monitoring correlation: {symbol_a} / {symbol_b}")

    def update(self, symbol: str, price: float, timestamp: float | None = None) -> None:
        """Update with a new price for a symbol.

        Recalculates correlation for all pairs that include this symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            price: Current price.
            timestamp: Unix timestamp.
        """
        now = timestamp or time.time()

        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=self._config.lookback_periods * 2)

        self._price_history[symbol].append((price, now))

        # Recalculate correlations for pairs involving this symbol
        for pair in self._monitored_pairs:
            if symbol in pair:
                self._recalculate_correlation(pair, now)

    def get_correlation(self, pair: tuple[str, str]) -> float | None:
        """Get current correlation for a pair.

        Args:
            pair: Tuple of two symbol strings.

        Returns:
            Correlation coefficient (-1 to 1), or None if insufficient data.
        """
        history = self._correlation_history.get(pair)
        if not history:
            return None
        return history[-1].correlation if history else None

    def get_regime(self, pair: tuple[str, str]) -> CorrelationRegime:
        """Get current correlation regime for a pair.

        Args:
            pair: Tuple of two symbol strings.

        Returns:
            Current CorrelationRegime (HIGH if unknown).
        """
        return self._regimes.get(pair, CorrelationRegime.HIGH_CORRELATION)

    def get_exposure_multiplier(self, pair: tuple[str, str]) -> float:
        """Get portfolio exposure multiplier based on correlation regime.

        Args:
            pair: Tuple of two symbol strings.

        Returns:
            Multiplier 0.0-1.0 for position sizing.
        """
        regime = self.get_regime(pair)

        if regime == CorrelationRegime.NEGATIVE:
            return self._config.negative_exposure_mult
        if regime == CorrelationRegime.DECORRELATED:
            return self._config.decorrelated_exposure_mult
        if regime == CorrelationRegime.LOW_CORRELATION:
            return self._config.low_corr_exposure_mult
        return 1.0

    def get_metrics(self, pair: tuple[str, str]) -> CorrelationMetrics:
        """Get detailed correlation metrics for a pair.

        Args:
            pair: Tuple of two symbol strings.

        Returns:
            CorrelationMetrics with current values and context.
        """
        history = self._correlation_history.get(pair, deque())
        current_corr = history[-1].correlation if history else 0.0

        # Count regime changes in last 24h
        now = time.time()
        window_start = now - 86400
        changes = self._regime_changes.get(pair, deque())
        recent_changes = sum(1 for c in changes if c.detected_at >= window_start)

        # Calculate trend
        if len(history) >= 5:
            recent_5 = [h.correlation for h in list(history)[-5:]]
            older_5 = (
                [h.correlation for h in list(history)[-10:-5]] if len(history) >= 10 else recent_5
            )
            avg_recent = sum(recent_5) / len(recent_5)
            avg_older = sum(older_5) / len(older_5)
            diff = avg_recent - avg_older
            if diff > 0.05:
                trend = "rising"
            elif diff < -0.05:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "unknown"

        return CorrelationMetrics(
            pair=pair,
            current_correlation=current_corr,
            regime=self.get_regime(pair),
            exposure_multiplier=self.get_exposure_multiplier(pair),
            regime_changes_24h=recent_changes,
            trend=trend,
        )

    def get_all_regimes(self) -> dict[tuple[str, str], CorrelationRegime]:
        """Get current regime for all monitored pairs.

        Returns:
            Dict mapping pair tuples to their current CorrelationRegime.
        """
        return {pair: self.get_regime(pair) for pair in self._monitored_pairs}

    def reset(self, pair: tuple[str, str] | None = None) -> None:
        """Reset state for a specific pair or all pairs."""
        if pair:
            self._correlation_history.pop(pair, None)
            self._regimes.pop(pair, None)
            self._regime_changes.pop(pair, None)
        else:
            self._correlation_history.clear()
            self._regimes.clear()
            self._regime_changes.clear()
            self._price_history.clear()

    # ------------------------------------------------------------------
    # Internal: Correlation calculation
    # ------------------------------------------------------------------

    def _recalculate_correlation(self, pair: tuple[str, str], now: float) -> None:
        """Recalculate correlation for a pair and check for regime changes."""
        sym_a, sym_b = pair
        history_a = self._price_history.get(sym_a, deque())
        history_b = self._price_history.get(sym_b, deque())

        if len(history_a) < self._config.min_periods or len(history_b) < self._config.min_periods:
            return

        # Align prices by timestamp (use nearest within 5 seconds)
        aligned = self._align_prices(history_a, history_b)
        if len(aligned) < self._config.min_periods:
            return

        # Calculate returns
        returns_a = []
        returns_b = []
        for i in range(1, len(aligned)):
            pa_prev, pb_prev = aligned[i - 1]
            pa_curr, pb_curr = aligned[i]
            if pa_prev > 0 and pb_prev > 0:
                returns_a.append((pa_curr - pa_prev) / pa_prev)
                returns_b.append((pb_curr - pb_prev) / pb_prev)

        if len(returns_a) < self._config.min_periods:
            return

        # Calculate Pearson correlation
        correlation = self._pearson_correlation(returns_a, returns_b)

        # Store correlation data point
        if pair not in self._correlation_history:
            self._correlation_history[pair] = deque(maxlen=self._config.lookback_periods * 2)
        self._correlation_history[pair].append(
            CorrelationDataPoint(correlation=correlation, timestamp=now)
        )

        # Classify regime
        new_regime = self._classify_regime(correlation)
        old_regime = self._regimes.get(pair)

        if old_regime is None:
            self._regimes[pair] = new_regime
        elif new_regime != old_regime:
            self._handle_regime_change(pair, old_regime, new_regime, correlation, now)

    def _classify_regime(self, correlation: float) -> CorrelationRegime:
        """Classify correlation value into a regime."""
        cfg = self._config
        if correlation < cfg.negative_threshold:
            return CorrelationRegime.NEGATIVE
        if correlation < cfg.low_threshold:
            return CorrelationRegime.DECORRELATED
        if correlation < cfg.moderate_threshold:
            return CorrelationRegime.LOW_CORRELATION
        if correlation < cfg.high_threshold:
            return CorrelationRegime.MODERATE_CORRELATION
        return CorrelationRegime.HIGH_CORRELATION

    def _handle_regime_change(
        self,
        pair: tuple[str, str],
        old_regime: CorrelationRegime,
        new_regime: CorrelationRegime,
        correlation: float,
        now: float,
    ) -> None:
        """Handle a correlation regime transition."""
        self._regimes[pair] = new_regime

        change = CorrelationRegimeChange(
            pair=pair,
            from_regime=old_regime,
            to_regime=new_regime,
            correlation=correlation,
            detected_at=now,
        )

        if pair not in self._regime_changes:
            self._regime_changes[pair] = deque(maxlen=500)
        self._regime_changes[pair].append(change)

        # Determine severity
        severity_order = {
            CorrelationRegime.HIGH_CORRELATION: 0,
            CorrelationRegime.MODERATE_CORRELATION: 1,
            CorrelationRegime.LOW_CORRELATION: 2,
            CorrelationRegime.DECORRELATED: 3,
            CorrelationRegime.NEGATIVE: 4,
        }

        if severity_order.get(new_regime, 0) > severity_order.get(old_regime, 0):
            # Correlation degraded
            logger.warning(
                f"📉 Correlation regime change for {pair[0]}/{pair[1]}: "
                f"{old_regime.value} → {new_regime.value} "
                f"(r={correlation:.3f}). "
                f"Exposure multiplier: {self.get_exposure_multiplier(pair):.0%}"
            )
        else:
            # Correlation improved
            logger.info(
                f"📈 Correlation improved for {pair[0]}/{pair[1]}: "
                f"{old_regime.value} → {new_regime.value} "
                f"(r={correlation:.3f})"
            )

    @staticmethod
    def _align_prices(
        history_a: deque[tuple[float, float]],
        history_b: deque[tuple[float, float]],
        tolerance_seconds: float = 5.0,
    ) -> list[tuple[float, float]]:
        """Align two price series by timestamp.

        Uses nearest-neighbor matching within tolerance.

        Returns:
            List of (price_a, price_b) tuples aligned by time.
        """
        aligned = []
        idx_b = 0
        list_b = list(history_b)

        for price_a, ts_a in history_a:
            # Find nearest timestamp in B
            best_idx = idx_b
            best_diff = abs(list_b[idx_b][1] - ts_a) if idx_b < len(list_b) else float("inf")

            # Search forward
            for j in range(idx_b, min(idx_b + 5, len(list_b))):
                diff = abs(list_b[j][1] - ts_a)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = j

            if best_diff <= tolerance_seconds and best_idx < len(list_b):
                aligned.append((price_a, list_b[best_idx][0]))
                idx_b = best_idx

        return aligned

    @staticmethod
    def _pearson_correlation(x: list[float], y: list[float]) -> float:
        """Calculate Pearson correlation coefficient.

        Args:
            x: First data series.
            y: Second data series (same length as x).

        Returns:
            Correlation coefficient from -1.0 to 1.0.
        """
        n = min(len(x), len(y))
        if n < 2:
            return 0.0

        x = x[:n]
        y = y[:n]

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y, strict=True))
        var_x = sum((xi - mean_x) ** 2 for xi in x)
        var_y = sum((yi - mean_y) ** 2 for yi in y)

        denominator = (var_x * var_y) ** 0.5
        if denominator == 0:
            return 0.0

        return cov / denominator
