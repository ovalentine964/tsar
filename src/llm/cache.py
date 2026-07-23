"""
LLM Response Cache — Avoid redundant LLM calls.

Caches responses by (task_type, prompt_hash) with TTL.
Useful for repeated queries (e.g., regime explanation during same period).
"""

import hashlib
import logging
import time
from typing import Any

from src.interfaces.types import LLMResponse

logger = logging.getLogger(__name__)


class LLMCache:
    """Simple in-memory LLM response cache."""

    def __init__(self, ttl_seconds: int = 3600, max_size: int = 1000) -> None:
        self._cache: dict[str, tuple[float, LLMResponse]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size

    def get(self, task_type: str, prompt: str) -> LLMResponse | None:
        """Get cached response if available and not expired."""
        key = self._make_key(task_type, prompt)
        if key in self._cache:
            timestamp, response = self._cache[key]
            if time.time() - timestamp < self._ttl:
                logger.debug(f"Cache hit: {task_type}")
                return response
            else:
                del self._cache[key]
        return None

    def set(self, task_type: str, prompt: str, response: LLMResponse) -> None:
        """Cache a response."""
        if len(self._cache) >= self._max_size:
            # Evict oldest entry
            oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest_key]

        key = self._make_key(task_type, prompt)
        self._cache[key] = (time.time(), response)

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()

    def _make_key(self, task_type: str, prompt: str) -> str:
        """Create cache key from task_type and prompt hash."""
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return f"{task_type}:{prompt_hash}"
