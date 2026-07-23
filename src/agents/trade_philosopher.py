"""
Trade Philosopher — Post-trade reflection and lesson extraction.

Role: ANALYSIS (Level 3+)
Model Tier: T2 (trade_summary) + T3 (trade_narrative for deep analysis)

Reflection cycle:
  1. Receive completed trade data
  2. Analyze what went right/wrong
  3. Extract actionable lessons
  4. Store in lesson archive
  5. Feed back to strategy evolution

Subscribes to: tsar:stream:fills, tsar:stream:positions, tsar:stream:risk_decisions
Publishes to: tsar:stream:analytics
"""

import logging
from typing import Any

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class TradePhilosopher(BaseAgent):
    """Reflect on completed trades and extract lessons."""

    AGENT_NAME = "trade_philosopher"
    ROLE = "ANALYSIS"

    def __init__(self, config: dict[str, Any], trading_mode: str = "paper") -> None:
        super().__init__(config, trading_mode)

    async def run_cycle(self) -> None:
        """Process completed trades and generate reflections."""
        # Level 3+ implementation
        pass

    async def reflect_on_trade(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Generate a reflection on a completed trade."""
        # Uses LLM with task_type="t2_trade_summary" or "t3_trade_narrative"
        return {}
