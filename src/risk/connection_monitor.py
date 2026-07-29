"""Connection monitor — kills trading if exchange is unreachable."""
import asyncio
import time


class ConnectionMonitor:
    def __init__(self, exchange_gateway, kill_switch, check_interval: int = 30):
        self.exchange = exchange_gateway
        self.kill_switch = kill_switch
        self.check_interval = check_interval
        self.consecutive_failures = 0
        self.max_failures = 3
        self.last_success = time.time()
        self.running = False

    async def start(self):
        self.running = True
        while self.running:
            try:
                await self.exchange.ping()
                self.consecutive_failures = 0
                self.last_success = time.time()
            except Exception as e:
                self.consecutive_failures += 1
                if self.consecutive_failures >= self.max_failures:
                    await self.kill_switch.activate(
                        reason=f"Connection lost: {self.consecutive_failures} consecutive failures"
                    )
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self.running = False
