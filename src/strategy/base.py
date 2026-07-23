"""
Base Strategy — Abstract base class for all trading strategies.

Every strategy defines entry rules, exit rules, and risk parameters.
Strategies are registered in the StrategyRegistry and scored by Signal Scout.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    NAME: str = "base"
    VERSION: str = "1.0.0"

    @abstractmethod
    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Check if entry conditions are met.

        Args:
            data: Market data (ohlcv, indicators, sentiment, etc.)

        Returns:
            Signal dict with score, entry_price, stop_loss, take_profit, or None.
        """

    @abstractmethod
    def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        """Check if exit conditions are met.

        Args:
            position: Current position data
            data: Current market data

        Returns:
            Exit signal dict or None.
        """

    @abstractmethod
    def get_risk_params(self) -> dict[str, Any]:
        """Get risk parameters for this strategy."""
