"""
Macro Agent — Macroeconomic regime analysis.

Role: ANALYSIS (Level 2+)
Model Tier: T0 (indicator computation) + T2 (news_sentiment) + T3 (risk_scenario)

Macro regime classification:
  RISK_ON: 1.0x position, LONG bias
  TRANSITION: 0.75x, NEUTRAL
  RISK_OFF: 0.50x, SHORT
  CRISIS: 0.25x, NONE

Data sources (all free): FRED, yfinance, Fear & Greed, CoinGecko, etc.

Subscribes to: tsar:stream:regime
Publishes to: tsar:stream:macro, tsar:stream:sentiment, tsar:stream:onchain
"""

import logging
from typing import Any

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class MacroAgent(BaseAgent):
    """Analyze macroeconomic environment and produce regime scores."""

    AGENT_NAME = "macro_agent"
    ROLE = "ANALYSIS"

    def __init__(self, config: dict[str, Any], trading_mode: str = "paper") -> None:
        super().__init__(config, trading_mode)

    async def run_cycle(self) -> None:
        """Analyze macro indicators and publish regime updates."""
        # Level 2+ implementation
        pass
