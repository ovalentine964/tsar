"""
TSAR Prometheus Metrics Exporter.

Wires prometheus_client gauges and counters to TSAR components.
Designed for graceful degradation — if prometheus_client is not installed,
all operations become no-ops.

Usage::

    from src.metrics.prometheus_export import TSARMetrics

    metrics = TSARMetrics()
    metrics.record_trade(pnl=150.0, symbol="BTC/USDT")
    metrics.set_gauge("portfolio_heat", 0.35)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.info("prometheus_client not installed — metrics export disabled")


class _NoOpMetric:
    """No-op metric for when prometheus_client is unavailable."""

    def labels(self, *args: Any, **kwargs: Any) -> _NoOpMetric:
        return self

    def inc(self, amount: float = 1.0) -> None:
        pass

    def dec(self, amount: float = 1.0) -> None:
        pass

    def set(self, value: float) -> None:
        pass

    def observe(self, value: float) -> None:
        pass

    def time(self) -> Any:
        return self

    def __enter__(self) -> _NoOpMetric:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


_NOOP = _NoOpMetric()


class TSARMetrics:
    """Centralized Prometheus metrics for all TSAR components.

    All metric operations are safe to call even if prometheus_client
    is not installed (graceful degradation via no-op metrics).

    Metrics are organized by component:
    - Trading: trades, P&L, slippage, latency
    - Risk: drawdown, position heat, kill switch
    - Event bus: published, consumed, DLQ, errors
    - Backend: registry calls, fallback usage
    - Database: connection pool stats, query latency
    - LLM: token usage, latency
    """

    def __init__(self, registry: Any | None = None) -> None:
        if not PROMETHEUS_AVAILABLE:
            self._init_noop()
            return

        self._registry = registry or CollectorRegistry()
        self._init_trading_metrics()
        self._init_risk_metrics()
        self._init_event_bus_metrics()
        self._init_backend_metrics()
        self._init_db_metrics()
        self._init_system_metrics()
        logger.info("TSARMetrics initialized with prometheus_client")

    def _init_noop(self) -> None:
        """Initialize all metric attributes as no-ops."""
        # Trading
        self.trades_total = _NOOP
        self.trade_pnl = _NOOP
        self.trade_slippage_bps = _NOOP
        self.trade_latency_ms = _NOOP
        # Risk
        self.portfolio_drawdown = _NOOP
        self.portfolio_heat = _NOOP
        self.kill_switch_trips = _NOOP
        # Event bus
        self.events_published = _NOOP
        self.events_consumed = _NOOP
        self.events_dlq = _NOOP
        self.event_handler_errors = _NOOP
        # Backend
        self.backend_calls = _NOOP
        self.backend_fallbacks = _NOOP
        self.backend_errors = _NOOP
        # Database
        self.db_pool_size = _NOOP
        self.db_pool_checked_out = _NOOP
        self.db_query_duration = _NOOP
        self.db_connections_created = _NOOP
        # System
        self.llm_tokens_total = _NOOP
        self.llm_latency = _NOOP

    def _init_trading_metrics(self) -> None:
        """Trading performance metrics."""
        self.trades_total = Counter(
            "tsar_trades_total",
            "Total number of trades executed",
            ["symbol", "side", "strategy", "status"],
            registry=self._registry,
        )
        self.trade_pnl = Gauge(
            "tsar_trade_pnl",
            "Realized P&L per trade",
            ["symbol", "strategy"],
            registry=self._registry,
        )
        self.trade_slippage_bps = Histogram(
            "tsar_trade_slippage_bps",
            "Trade slippage in basis points",
            ["symbol"],
            buckets=[0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30, 50],
            registry=self._registry,
        )
        self.trade_latency_ms = Histogram(
            "tsar_trade_latency_ms",
            "Trade execution latency in milliseconds",
            ["exchange"],
            buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
            registry=self._registry,
        )

    def _init_risk_metrics(self) -> None:
        """Risk management metrics."""
        self.portfolio_drawdown = Gauge(
            "tsar_portfolio_drawdown_pct",
            "Current portfolio drawdown percentage",
            registry=self._registry,
        )
        self.portfolio_heat = Gauge(
            "tsar_portfolio_heat",
            "Current portfolio heat (risk exposure 0-1)",
            registry=self._registry,
        )
        self.kill_switch_trips = Counter(
            "tsar_kill_switch_trips_total",
            "Number of kill switch activations",
            ["reason"],
            registry=self._registry,
        )

    def _init_event_bus_metrics(self) -> None:
        """Event bus throughput metrics."""
        self.events_published = Counter(
            "tsar_events_published_total",
            "Total events published to bus",
            ["stream", "event_type"],
            registry=self._registry,
        )
        self.events_consumed = Counter(
            "tsar_events_consumed_total",
            "Total events consumed from bus",
            ["stream", "consumer_group"],
            registry=self._registry,
        )
        self.events_dlq = Counter(
            "tsar_events_dlq_total",
            "Events moved to dead letter queue",
            ["stream", "reason"],
            registry=self._registry,
        )
        self.event_handler_errors = Counter(
            "tsar_event_handler_errors_total",
            "Event handler errors",
            ["stream", "error_type"],
            registry=self._registry,
        )

    def _init_backend_metrics(self) -> None:
        """Backend registry metrics."""
        self.backend_calls = Counter(
            "tsar_backend_calls_total",
            "Backend method invocations",
            ["interface", "backend"],
            registry=self._registry,
        )
        self.backend_fallbacks = Counter(
            "tsar_backend_fallbacks_total",
            "Fallback backend activations",
            ["interface", "from_backend", "to_backend"],
            registry=self._registry,
        )
        self.backend_errors = Counter(
            "tsar_backend_errors_total",
            "Backend errors",
            ["interface", "backend", "error_type"],
            registry=self._registry,
        )

    def _init_db_metrics(self) -> None:
        """Database connection pool metrics."""
        self.db_pool_size = Gauge(
            "tsar_db_pool_size",
            "Current connection pool size",
            registry=self._registry,
        )
        self.db_pool_checked_out = Gauge(
            "tsar_db_pool_checked_out",
            "Connections currently checked out",
            registry=self._registry,
        )
        self.db_query_duration = Histogram(
            "tsar_db_query_duration_seconds",
            "Database query duration",
            ["operation"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            registry=self._registry,
        )
        self.db_connections_created = Counter(
            "tsar_db_connections_created_total",
            "Total database connections created",
            registry=self._registry,
        )

    def _init_system_metrics(self) -> None:
        """System-level metrics (LLM, etc.)."""
        self.llm_tokens_total = Counter(
            "tsar_llm_tokens_total",
            "Total LLM tokens consumed",
            ["provider", "model", "direction"],
            registry=self._registry,
        )
        self.llm_latency = Histogram(
            "tsar_llm_latency_seconds",
            "LLM request latency",
            ["provider"],
            buckets=[0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60],
            registry=self._registry,
        )

    # ── Convenience methods ──────────────────────────────────

    def record_trade(
        self,
        pnl: float,
        symbol: str = "",
        side: str = "buy",
        strategy: str = "",
        slippage_bps: float = 0.0,
        latency_ms: float = 0.0,
        exchange: str = "",
        status: str = "filled",
    ) -> None:
        """Record a completed trade across all relevant metrics."""
        self.trades_total.labels(symbol=symbol, side=side, strategy=strategy, status=status).inc()
        self.trade_pnl.labels(symbol=symbol, strategy=strategy).set(pnl)
        if slippage_bps > 0:
            self.trade_slippage_bps.labels(symbol=symbol).observe(slippage_bps)
        if latency_ms > 0:
            self.trade_latency_ms.labels(exchange=exchange).observe(latency_ms)

    def export(self) -> bytes:
        """Export all metrics in Prometheus text format.

        Returns:
            Prometheus exposition format bytes. Returns empty bytes if
            prometheus_client is not available.
        """
        if not PROMETHEUS_AVAILABLE:
            return b""
        return generate_latest(self._registry)

    def content_type(self) -> str:
        """Return the Prometheus content type header value."""
        if not PROMETHEUS_AVAILABLE:
            return "text/plain"
        return CONTENT_TYPE_LATEST


# Module-level singleton for easy access
_metrics: TSARMetrics | None = None


def get_metrics() -> TSARMetrics:
    """Get or create the module-level TSARMetrics singleton."""
    global _metrics
    if _metrics is None:
        _metrics = TSARMetrics()
    return _metrics
