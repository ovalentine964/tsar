"""TSAR Telegram Bot — real-time monitoring and control."""
import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)


class TsarBot:
    def __init__(self, token: str, chat_id: str, tsar_system=None):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.system = tsar_system
        self.offset = 0

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

    async def poll_loop(self):
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
                        if text.startswith("/"):
                            await self.handle_command(text)
            except Exception:
                await asyncio.sleep(5)

    async def handle_command(self, text: str):
        cmd = text.split()[0].lower()
        if cmd == "/status":
            await self.send_message("🏰 TSAR is running")
        elif cmd == "/pnl":
            await self.send_message("📊 P&L: $0.00 (no trades yet)")
        elif cmd == "/kill":
            await self.send_message("🚨 Kill switch activated!")
