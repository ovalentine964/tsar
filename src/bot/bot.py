"""TSAR Telegram Bot — real-time monitoring and control.

Wired to real TSAR tools via commands.py:
  /status    → system health from monitoring tool
  /pnl       → P&L from monitoring tool (TradeMemory)
  /positions → positions from market_data (TradeMemory)
  /risk      → risk state from risk_management tool (KillSwitch + TradeMemory)
  /regime    → regime from regime_detector (TradeMemory)
  /flywheel  → flywheel health from flywheel_orchestrator (FlywheelHealth)
  /stop      → activate kill switch
  /start     → deactivate kill switch
"""

import asyncio
import logging
import os

import aiohttp

logger = logging.getLogger(__name__)


class TsarBot:
    def __init__(self, token: str, chat_id: str, tsar_system=None):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.system = tsar_system
        self.offset = 0

        # SECURITY (C-020): Build whitelist of authorized chat IDs.
        self._allowed_chat_ids: set[str] = {str(chat_id)}
        extra_ids = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        for cid in extra_ids.split(","):
            cid = cid.strip()
            if cid:
                self._allowed_chat_ids.add(cid)
        logger.info(
            "Telegram bot initialized with %d authorized chat ID(s)",
            len(self._allowed_chat_ids),
        )

    async def send_message(self, text: str):
        async with aiohttp.ClientSession() as session:
            await session.post(f"{self.base_url}/sendMessage", json={
                "chat_id": self.chat_id, "text": text, "parse_mode": "HTML"
            })

    async def send_trade_notification(self, trade: dict):
        emoji = "🟢" if trade.get("pnl", 0) >= 0 else "🔴"
        msg = f"{emoji} <b>Trade {trade['symbol']}</b>\n"
        msg += f"Side: {trade['side']} | P&L: ${trade.get('pnl', 0):.2f}\n"
        msg += f"Strategy: {trade.get('strategy', 'N/A')}"
        await self.send_message(msg)

    async def send_risk_alert(self, level: str, message: str):
        emoji = {"LOW": "🟡", "MEDIUM": "🟠", "HIGH": "🔴", "CRITICAL": "🚨"}.get(level, "⚠️")
        await self.send_message(f"{emoji} <b>RISK [{level}]</b>\n{message}")

    def _is_authorized(self, msg: dict) -> bool:
        """SECURITY (C-020): Check if the message sender is in the chat whitelist."""
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        return chat_id in self._allowed_chat_ids

    async def poll_loop(self):
        """Main polling loop — routes commands to commands.py handlers."""
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.get(f"{self.base_url}/getUpdates", params={
                        "offset": self.offset, "timeout": 30
                    })
                    data = await resp.json()
                    for update in data.get("result", []):
                        self.offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "")

                        # SECURITY (C-020): Reject commands from unauthorized chat IDs.
                        if not self._is_authorized(msg):
                            chat = msg.get("chat", {})
                            logger.warning(
                                "Unauthorized Telegram command from chat_id=%s user=%s",
                                chat.get("id"),
                                msg.get("from", {}).get("username", "unknown"),
                            )
                            continue

                        if text.startswith("/"):
                            await self.handle_command(text)
            except Exception:
                await asyncio.sleep(5)

    async def handle_command(self, text: str):
        """Route Telegram commands to commands.py handlers.

        Each command is handled by the real TSAR tools:
        - /status → system health from monitoring (KillSwitch + TradeMemory)
        - /pnl → P&L from monitoring tool (TradeMemory stats)
        - /positions → positions from market_data (TradeMemory open positions)
        - /risk → risk state from risk_management (KillSwitch + drawdown)
        - /regime → regime from regime_detector (TradeMemory regime perf)
        - /flywheel → flywheel health from flywheel_orchestrator (FlywheelHealth)
        - /stop → activate kill switch
        - /start → deactivate kill switch
        """
        from src.bot.commands import handle_command

        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        try:
            response = await handle_command(cmd, args)
            await self.send_message(response)
        except Exception as e:
            logger.error("Command %s failed: %s", cmd, e)
            await self.send_message(f"❌ Error executing {cmd}: {str(e)}")
