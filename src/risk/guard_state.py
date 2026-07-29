"""Persistent guard state using Redis."""
import json
import time


class GuardState:
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.prefix = "tsar:guard:"
        self.local_cache = {}  # Fallback if no Redis

    def _get(self, key: str, default=None):
        if self.redis:
            val = self.redis.get(f"{self.prefix}{key}")
            return json.loads(val) if val else default
        return self.local_cache.get(key, default)

    def _set(self, key: str, value, ttl: int = 86400):
        if self.redis:
            self.redis.setex(f"{self.prefix}{key}", ttl, json.dumps(value))
        else:
            self.local_cache[key] = value

    def get_consecutive_losses(self) -> int:
        return self._get("consecutive_losses", 0)

    def record_loss(self):
        count = self.get_consecutive_losses() + 1
        self._set("consecutive_losses", count)
        self._set("last_loss_time", time.time())
        return count

    def record_win(self):
        self._set("consecutive_losses", 0)
        count = self._get("consecutive_wins", 0) + 1
        self._set("consecutive_wins", count)
        return count

    def is_on_cooldown(self) -> bool:
        cooldown_until = self._get("cooldown_until", 0)
        return time.time() < cooldown_until

    def set_cooldown(self, minutes: int = 60):
        self._set("cooldown_until", time.time() + (minutes * 60))

    def reset(self):
        for key in ["consecutive_losses", "consecutive_wins", "cooldown_until", "last_loss_time"]:
            if self.redis:
                self.redis.delete(f"{self.prefix}{key}")
            else:
                self.local_cache.pop(key, None)
