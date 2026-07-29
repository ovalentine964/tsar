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
        self.trade_memory = None
        self.lesson_archive = None
        self.llm_provider = None
        self.prompts = {}

    async def run_cycle(self) -> None:
        """Process completed trades and generate reflections."""
        if self.trade_memory is None or self.llm_provider is None:
            logger.debug("TradePhilosopher: trade_memory or llm_provider not set, skipping")
            return {"reflections": 0}

        closed = self.trade_memory.get_closed_trades(limit=10)
        if not closed:
            return {"reflections": 0}

        reflections = []
        for trade in closed:
            if trade.get("reflection"):
                continue  # Already reflected

            try:
                prompt = self.prompts.get("t3_trade_narrative", str(trade))
                response = await self.llm_provider.generate(prompt)

                reflection = response.text if response else "No reflection generated"
                self.trade_memory.update_trade(trade["id"], reflection=reflection)

                # Create lesson
                pnl_pct = trade.get("pnl_pct", 0)
                if pnl_pct < -5:
                    severity = "critical"
                elif pnl_pct < -3:
                    severity = "high"
                elif pnl_pct < 0:
                    severity = "moderate"
                else:
                    severity = "insight"

                if self.lesson_archive:
                    self.lesson_archive.add(
                        content=reflection,
                        category="trade_reflection",
                        severity=severity,
                        trade_id=trade["id"],
                    )
                reflections.append(trade["id"])

            except Exception as e:
                logger.error(f"Reflection failed for trade {trade.get('id')}: {e}")

        return {"reflections": len(reflections), "trade_ids": reflections}

    async def reflect_on_trade(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Generate a reflection on a completed trade."""
        if self.llm_provider is None:
            return {"reflection": "LLM provider not available"}

        try:
            prompt = self.prompts.get("t2_trade_summary", str(trade))
            response = await self.llm_provider.generate(prompt)
            return {"reflection": response.text if response else "No reflection generated"}
        except Exception as e:
            logger.error(f"Trade reflection failed: {e}")
            return {"reflection": f"Error: {e}"}
