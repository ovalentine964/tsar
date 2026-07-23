"""
Metric Tracker — Core metric collection and baseline recording.

Tracks 10 core TSAR metrics:
  1. trade_count          — Total trades executed
  2. total_pnl            — Cumulative P&L
  3. win_rate             — Win rate (wins / total)
  4. sharpe_ratio         — Rolling Sharpe ratio
  5. max_drawdown         — Maximum drawdown percentage
  6. expectancy           — Average P&L per trade
  7. profit_factor        — Gross profit / gross loss
  8. avg_slippage_bps     — Average slippage in basis points
  9. signal_accuracy      — Signal hit rate (% of signals that reached TP)
  10. execution_latency_ms — Average execution latency

Supports baseline recording for improvement tracking.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CORE METRICS DEFINITION
# ═══════════════════════════════════════════════════════════════════════

CORE_METRICS = [
    "trade_count",
    "total_pnl",
    "win_rate",
    "sharpe_ratio",
    "max_drawdown",
    "expectancy",
    "profit_factor",
    "avg_slippage_bps",
    "signal_accuracy",
    "execution_latency_ms",
]


@dataclass
class MetricSnapshot:
    """A point-in-time snapshot of all core metrics."""

    timestamp: str = ""
    trade_count: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    avg_slippage_bps: float = 0.0
    signal_accuracy: float = 0.0
    execution_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "trade_count": self.trade_count,
            "total_pnl": self.total_pnl,
            "win_rate": self.win_rate,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "expectancy": self.expectancy,
            "profit_factor": self.profit_factor,
            "avg_slippage_bps": self.avg_slippage_bps,
            "signal_accuracy": self.signal_accuracy,
            "execution_latency_ms": self.execution_latency_ms,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MetricSnapshot:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ═══════════════════════════════════════════════════════════════════════
# IMPROVEMENT TRACKER
# ═══════════════════════════════════════════════════════════════════════


class ImprovementTracker:
    """Track, record, and compare TSAR's 10 core metrics.

    Supports:
    - Real-time metric updates from trade events
    - Baseline recording for improvement measurement
    - Snapshot history for trend analysis
    - Delta computation (current vs baseline)

    Usage::

        tracker = ImprovementTracker("data/metrics.json")
        tracker.record_trade(pnl=150.0, slippage_bps=3.0, latency_ms=45)
        tracker.record_baseline()
        snapshot = tracker.current_snapshot()
        delta = tracker.delta_vs_baseline()
    """

    def __init__(self, persistence_path: str | Path | None = None) -> None:
        self._path = Path(persistence_path) if persistence_path else None

        # Internal accumulators
        self._trade_count: int = 0
        self._wins: int = 0
        self._losses: int = 0
        self._total_pnl: float = 0.0
        self._gross_profit: float = 0.0
        self._gross_loss: float = 0.0
        self._pnl_history: list[float] = []
        self._slippage_history: list[float] = []
        self._latency_history: list[float] = []
        self._signal_count: int = 0
        self._signal_hits: int = 0  # signals that reached TP
        self._peak_equity: float = 0.0
        self._max_drawdown: float = 0.0
        self._current_equity: float = 0.0

        # Baseline and snapshots
        self._baseline: MetricSnapshot | None = None
        self._snapshots: list[MetricSnapshot] = []

        # Load persisted state
        self._load()

    # ── Trade Event Recording ────────────────────────────────

    def record_trade(
        self,
        pnl: float,
        slippage_bps: float = 0.0,
        latency_ms: float = 0.0,
        signal_hit: bool = False,
    ) -> None:
        """Record a completed trade.

        Args:
            pnl: Realized P&L for the trade.
            slippage_bps: Slippage in basis points.
            latency_ms: Execution latency in milliseconds.
            signal_hit: Whether the signal reached its take-profit target.
        """
        self._trade_count += 1
        self._total_pnl += pnl
        self._pnl_history.append(pnl)

        if pnl > 0:
            self._wins += 1
            self._gross_profit += pnl
        else:
            self._losses += 1
            self._gross_loss += abs(pnl)

        self._slippage_history.append(slippage_bps)
        self._latency_history.append(latency_ms)

        self._signal_count += 1
        if signal_hit:
            self._signal_hits += 1

        # Update equity and drawdown
        self._current_equity += pnl
        if self._current_equity > self._peak_equity:
            self._peak_equity = self._current_equity
        if self._peak_equity > 0:
            dd = (self._peak_equity - self._current_equity) / self._peak_equity
            self._max_drawdown = max(self._max_drawdown, dd)

        self._save()

    def record_signal(self, hit: bool) -> None:
        """Record a signal outcome without a trade (e.g. signal expired).

        Args:
            hit: Whether the signal reached its target.
        """
        self._signal_count += 1
        if hit:
            self._signal_hits += 1

    def set_equity(self, equity: float) -> None:
        """Set current equity for drawdown tracking.

        Args:
            equity: Current portfolio equity.
        """
        self._current_equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            dd = (self._peak_equity - equity) / self._peak_equity
            self._max_drawdown = max(self._max_drawdown, dd)

    # ── Metric Computation ───────────────────────────────────

    def current_snapshot(self) -> MetricSnapshot:
        """Compute current metric snapshot."""
        return MetricSnapshot(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            trade_count=self._trade_count,
            total_pnl=round(self._total_pnl, 2),
            win_rate=self._compute_win_rate(),
            sharpe_ratio=self._compute_sharpe(),
            max_drawdown=round(self._max_drawdown, 4),
            expectancy=self._compute_expectancy(),
            profit_factor=self._compute_profit_factor(),
            avg_slippage_bps=self._compute_avg(self._slippage_history),
            signal_accuracy=self._compute_signal_accuracy(),
            execution_latency_ms=self._compute_avg(self._latency_history),
        )

    def _compute_win_rate(self) -> float:
        if self._trade_count == 0:
            return 0.0
        return round(self._wins / self._trade_count, 4)

    def _compute_sharpe(self) -> float:
        """Compute annualized Sharpe ratio from P&L history."""
        if len(self._pnl_history) < 2:
            return 0.0
        mean_pnl = sum(self._pnl_history) / len(self._pnl_history)
        variance = sum((p - mean_pnl) ** 2 for p in self._pnl_history) / (len(self._pnl_history) - 1)
        std_pnl = variance ** 0.5
        if std_pnl == 0:
            return 0.0
        # Annualize assuming ~252 trading days, 4 trades/day
        daily_factor = (252 * 4) ** 0.5
        return round((mean_pnl / std_pnl) * daily_factor, 4)

    def _compute_expectancy(self) -> float:
        """Average P&L per trade."""
        if self._trade_count == 0:
            return 0.0
        return round(self._total_pnl / self._trade_count, 4)

    def _compute_profit_factor(self) -> float:
        """Gross profit / gross loss."""
        if self._gross_loss == 0:
            return float("inf") if self._gross_profit > 0 else 0.0
        return round(self._gross_profit / self._gross_loss, 4)

    def _compute_signal_accuracy(self) -> float:
        if self._signal_count == 0:
            return 0.0
        return round(self._signal_hits / self._signal_count, 4)

    @staticmethod
    def _compute_avg(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 4)

    # ── Baseline ─────────────────────────────────────────────

    def record_baseline(self) -> MetricSnapshot:
        """Record current metrics as the baseline for improvement tracking.

        Returns:
            The baseline MetricSnapshot.
        """
        self._baseline = self.current_snapshot()
        self._save()
        logger.info(f"Baseline recorded: {self._baseline.to_dict()}")
        return self._baseline

    def get_baseline(self) -> MetricSnapshot | None:
        """Get the recorded baseline snapshot."""
        return self._baseline

    def delta_vs_baseline(self) -> dict[str, Any] | None:
        """Compute delta between current metrics and baseline.

        Returns:
            Dict with metric deltas (positive = improvement) or None if no baseline.
        """
        if self._baseline is None:
            return None

        current = self.current_snapshot()
        baseline_dict = self._baseline.to_dict()
        current_dict = current.to_dict()

        deltas: dict[str, Any] = {}
        for metric in CORE_METRICS:
            base_val = baseline_dict.get(metric, 0)
            curr_val = current_dict.get(metric, 0)
            if isinstance(base_val, (int, float)) and isinstance(curr_val, (int, float)):
                delta = curr_val - base_val
                # For drawdown, lower is better
                if metric == "max_drawdown":
                    delta = -delta
                deltas[metric] = {
                    "baseline": base_val,
                    "current": curr_val,
                    "delta": round(delta, 6),
                }

        return deltas

    # ── Snapshots ────────────────────────────────────────────

    def take_snapshot(self) -> MetricSnapshot:
        """Take and store a metric snapshot."""
        snapshot = self.current_snapshot()
        self._snapshots.append(snapshot)
        # Keep last 1000 snapshots
        if len(self._snapshots) > 1000:
            self._snapshots = self._snapshots[-1000:]
        self._save()
        return snapshot

    def get_snapshots(self, limit: int = 100) -> list[MetricSnapshot]:
        """Get recent snapshots."""
        return self._snapshots[-limit:]

    # ── Prometheus Exposition ────────────────────────────────

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        snapshot = self.current_snapshot()
        lines: list[str] = []
        for metric in CORE_METRICS:
            value = getattr(snapshot, metric, 0)
            lines.append(f"# HELP tsar_{metric} TSAR {metric}")
            lines.append(f"# TYPE tsar_{metric} gauge")
            lines.append(f"tsar_{metric} {value}")
        return "\n".join(lines) + "\n"

    # ── Persistence ──────────────────────────────────────────

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "trade_count": self._trade_count,
            "wins": self._wins,
            "losses": self._losses,
            "total_pnl": self._total_pnl,
            "gross_profit": self._gross_profit,
            "gross_loss": self._gross_loss,
            "pnl_history": self._pnl_history[-500:],  # Keep last 500
            "slippage_history": self._slippage_history[-500:],
            "latency_history": self._latency_history[-500:],
            "signal_count": self._signal_count,
            "signal_hits": self._signal_hits,
            "peak_equity": self._peak_equity,
            "max_drawdown": self._max_drawdown,
            "current_equity": self._current_equity,
            "baseline": self._baseline.to_dict() if self._baseline else None,
            "snapshots": [s.to_dict() for s in self._snapshots[-100:]],
        }
        with open(self._path, "w") as f:
            json.dump(state, f, indent=2)

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            with open(self._path) as f:
                state = json.load(f)
            self._trade_count = state.get("trade_count", 0)
            self._wins = state.get("wins", 0)
            self._losses = state.get("losses", 0)
            self._total_pnl = state.get("total_pnl", 0.0)
            self._gross_profit = state.get("gross_profit", 0.0)
            self._gross_loss = state.get("gross_loss", 0.0)
            self._pnl_history = state.get("pnl_history", [])
            self._slippage_history = state.get("slippage_history", [])
            self._latency_history = state.get("latency_history", [])
            self._signal_count = state.get("signal_count", 0)
            self._signal_hits = state.get("signal_hits", 0)
            self._peak_equity = state.get("peak_equity", 0.0)
            self._max_drawdown = state.get("max_drawdown", 0.0)
            self._current_equity = state.get("current_equity", 0.0)
            if state.get("baseline"):
                self._baseline = MetricSnapshot.from_dict(state["baseline"])
            self._snapshots = [MetricSnapshot.from_dict(s) for s in state.get("snapshots", [])]
            logger.info(f"Loaded metrics: {self._trade_count} trades, baseline={'yes' if self._baseline else 'no'}")
        except Exception as e:
            logger.error(f"Failed to load metrics: {e}")


# ═══════════════════════════════════════════════════════════════════════
# LEGACY COMPAT — MetricTracker (simple counter/gauge API)
# ═══════════════════════════════════════════════════════════════════════


class MetricTracker:
    """Simple counter/gauge metric tracker (legacy API).

    For fine-grained Prometheus-style counters and gauges.
    For the 10 core TSAR metrics, use ImprovementTracker.
    """

    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}

    def increment(self, name: str, value: float = 1.0, **labels: Any) -> None:
        """Increment a counter metric."""
        key = self._make_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def set_gauge(self, name: str, value: float, **labels: Any) -> None:
        """Set a gauge metric."""
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def get_all(self) -> dict[str, Any]:
        """Get all metrics."""
        return {"counters": dict(self._counters), "gauges": dict(self._gauges)}

    def _make_key(self, name: str, labels: dict[str, Any]) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
