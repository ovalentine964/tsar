"""
TSAR Metrics — Observability and improvement measurement.

Components:
  - Tracker:   Core metric tracking (Prometheus gauges/counters)
  - Dashboard: FastAPI metric endpoints
  - Flywheel:  Self-improvement health score computation
  - PrometheusExport: Centralized Prometheus metrics for all components
"""

from src.metrics.prometheus_export import TSARMetrics, get_metrics

__all__ = ["TSARMetrics", "get_metrics"]
