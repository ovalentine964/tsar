"""
Telegram Bot — Alert delivery and command interface.

Sends trade alerts, risk warnings, and daily summaries.
Responds to commands like /start, /stop, /status, /pnl.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TsarBot:
    """Telegram bot for TSAR alerts and control."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    async def send_alert(self, message: str, priority: str = "normal") -> None:
        """Send an alert message to Telegram."""
        logger.info(f"Alert [{priority}]: {message}")
        # TODO: implement Telegram API call

    async def send_trade_notification(self, trade: dict[str, Any]) -> None:
        """Send a trade execution notification."""
        msg = (
            f"{'🟢' if trade.get('side') == 'buy' else '🔴'} "
            f"{trade.get('side', '').upper()} {trade.get('symbol', '')}\n"
            f"Qty: {trade.get('quantity', 0)}\n"
            f"Price: {trade.get('price', 0)}"
        )
        await self.send_alert(msg)

    async def send_daily_summary(self, summary: dict[str, Any]) -> None:
        """Send end-of-day summary."""
        msg = (
            f"📊 Daily Summary\n"
            f"Trades: {summary.get('trade_count', 0)}\n"
            f"P&L: {summary.get('total_pnl', 0):.2f}\n"
            f"Win Rate: {summary.get('win_rate', 0):.1f}%"
        )
        await self.send_alert(msg)
