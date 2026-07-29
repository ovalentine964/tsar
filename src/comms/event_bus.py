"""Simple in-process CloudEvents bus."""
from collections import defaultdict
import asyncio


class EventBus:
    def __init__(self):
        self._handlers = defaultdict(list)

    def subscribe(self, event_type: str, handler):
        self._handlers[event_type].append(handler)

    async def publish(self, event_type: str, data: dict):
        for handler in self._handlers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                print(f"Event handler error [{event_type}]: {e}")


bus = EventBus()
