"""
Dashboard — FastAPI metric endpoints for Grafana and monitoring.

Exposes metrics in Prometheus format and JSON for dashboards.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class Dashboard:
    """Metric dashboard endpoints."""

    def __init__(self, tracker: Any) -> None:
        self._tracker = tracker

    def get_trading_overview(self) -> dict[str, Any]:
        """Get trading overview metrics."""
        return self._tracker.get_all()

    def get_risk_state(self) -> dict[str, Any]:
        """Get current risk state."""
        return {}

    def get_system_health(self) -> dict[str, Any]:
        """Get system health metrics."""
        return {}
