"""
Persistent guard state — SQLite-backed with Redis cache layer.

PURPOSE:
  GuardState tracks behavioral guard counters (consecutive losses,
  wins, cooldowns). If this state is lost on restart, the guards
  are blind — revenge trading, greed, and FOMO protections reset.

PERSISTENCE ARCHITECTURE:
  ┌─────────────┐     ┌─────────────┐     ┌──────────────┐
  │  In-Memory   │ ◄── │    Redis     │ ◄── │   SQLite     │
  │  (fastest)   │     │  (cache)     │     │ (persistent) │
  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
         │                    │                    │
         └────────────────────┴────────────────────┘
              Write-through to all three layers

  Read path: memory → Redis → SQLite → default
  Write path: write to ALL three (memory, Redis, SQLite)

  SQLite is the SOURCE OF TRUTH — survives process restart,
  Redis failure, and memory loss.

SAFETY:
  - All reads return defaults if any layer fails
  - SQLite writes are atomic (WAL mode)
  - No LLM calls, no external API calls
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get(
    "TSAR_GUARD_STATE_DB", "./data/guard_state.db"
)


class GuardStatePersistence:
    """SQLite-backed persistent guard state with optional Redis cache.

    Stores all guard counters (losses, wins, cooldowns, timestamps)
    in SQLite so they survive process restarts.

    SCHEMA:
      guard_state table with key-value pairs:
        key TEXT PRIMARY KEY
        value TEXT (JSON-encoded)
        updated_at REAL (unix timestamp)

    USAGE:
      # Initialize with SQLite persistence
      state = GuardStatePersistence(db_path="./data/guard_state.db")

      # Record a loss (persists immediately)
      state.record_loss()

      # Check cooldown (reads from cache/SQLite)
      if state.is_on_cooldown():
          block_trade()

      # On startup, state is automatically loaded from SQLite
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        redis_client: Any | None = None,
        redis_prefix: str = "tsar:guard:",
    ) -> None:
        """Initialize persistent guard state.

        Args:
            db_path: Path to SQLite database file.
            redis_client: Optional Redis client for cache layer.
            redis_prefix: Redis key prefix for guard state.
        """
        self._db_path = Path(db_path)
        self._redis = redis_client
        self._redis_prefix = redis_prefix
        self._memory_cache: dict[str, Any] = {}
        self._conn: sqlite3.Connection | None = None

        # Ensure parent directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize SQLite
        self._init_db()

        # Load existing state into memory cache
        self._load_all_to_cache()

        logger.info(
            f"GuardStatePersistence initialized: db={self._db_path}, "
            f"redis={'yes' if redis_client else 'no'}, "
            f"cached_keys={len(self._memory_cache)}"
        )

    # ------------------------------------------------------------------
    # Public API — Counter operations
    # ------------------------------------------------------------------

    def get_consecutive_losses(self) -> int:
        """Get current consecutive loss count."""
        return int(self._get("consecutive_losses", 0))

    def record_loss(self) -> int:
        """Record a loss and update streak counters.

        Returns:
            New consecutive loss count.
        """
        count = self.get_consecutive_losses() + 1
        self._set("consecutive_losses", count)
        self._set("last_loss_time", time.time())
        # Reset win streak on loss
        self._set("consecutive_wins", 0)
        logger.debug(f"GuardState: recorded LOSS, streak={count}")
        return count

    def get_consecutive_wins(self) -> int:
        """Get current consecutive win count."""
        return int(self._get("consecutive_wins", 0))

    def record_win(self) -> int:
        """Record a win and update streak counters.

        Returns:
            New consecutive win count.
        """
        # Reset loss streak on win
        self._set("consecutive_losses", 0)
        count = self.get_consecutive_wins() + 1
        self._set("consecutive_wins", count)
        logger.debug(f"GuardState: recorded WIN, streak={count}")
        return count

    def is_on_cooldown(self) -> bool:
        """Check if currently in revenge-trading cooldown.

        Returns:
            True if cooldown is active (trading should be blocked).
        """
        cooldown_until = float(self._get("cooldown_until", 0))
        return time.time() < cooldown_until

    def get_cooldown_remaining_seconds(self) -> float:
        """Get remaining cooldown time in seconds.

        Returns:
            Seconds remaining, or 0.0 if not on cooldown.
        """
        cooldown_until = float(self._get("cooldown_until", 0))
        remaining = cooldown_until - time.time()
        return max(0.0, remaining)

    def set_cooldown(self, minutes: int = 60) -> None:
        """Activate a cooldown period.

        Args:
            minutes: Duration of the cooldown in minutes.
        """
        until = time.time() + (minutes * 60)
        self._set("cooldown_until", until)
        logger.info(f"GuardState: cooldown set for {minutes} minutes")

    def get_last_loss_time(self) -> float:
        """Get timestamp of the last loss.

        Returns:
            Unix timestamp of last loss, or 0.0 if no losses recorded.
        """
        return float(self._get("last_loss_time", 0))

    def get_trade_history(self) -> list[bool]:
        """Get recent trade outcome history.

        Returns:
            List of booleans (True=win, False=loss), most recent last.
            Limited to last 100 trades.
        """
        raw = self._get("trade_history", "[]")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        return raw if isinstance(raw, list) else []

    def append_trade_result(self, is_win: bool) -> None:
        """Append a trade result to history (kept to 100 entries).

        Args:
            is_win: True if the trade was profitable.
        """
        history = self.get_trade_history()
        history.append(is_win)
        # Keep only last 100
        if len(history) > 100:
            history = history[-100:]
        self._set("trade_history", json.dumps(history))

    def reset(self) -> None:
        """Reset ALL guard state (e.g., after recovery protocol).

        Clears all counters, cooldowns, and history.
        Persists the reset to all storage layers.
        """
        keys = [
            "consecutive_losses", "consecutive_wins",
            "cooldown_until", "last_loss_time", "trade_history",
        ]
        for key in keys:
            self._delete(key)

        self._memory_cache.clear()
        logger.warning("GuardState: ALL state reset")

    def get_snapshot(self) -> dict[str, Any]:
        """Get a full snapshot of guard state for debugging/monitoring.

        Returns:
            Dict with all guard state values.
        """
        return {
            "consecutive_losses": self.get_consecutive_losses(),
            "consecutive_wins": self.get_consecutive_wins(),
            "is_on_cooldown": self.is_on_cooldown(),
            "cooldown_remaining_seconds": self.get_cooldown_remaining_seconds(),
            "last_loss_time": self.get_last_loss_time(),
            "trade_history_length": len(self.get_trade_history()),
        }

    # ------------------------------------------------------------------
    # Internal — Storage operations
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Initialize SQLite database with WAL mode and schema."""
        try:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,  # autocommit
            )
            # WAL mode for better concurrent read performance
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")

            # Create schema
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS guard_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_guard_state_updated
                ON guard_state(updated_at)
            """)

            logger.debug(f"GuardState SQLite initialized: {self._db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize GuardState SQLite: {e}")
            self._conn = None

    def _load_all_to_cache(self) -> None:
        """Load all guard state from SQLite into memory cache."""
        if not self._conn:
            return

        try:
            cursor = self._conn.execute(
                "SELECT key, value FROM guard_state"
            )
            for key, value_str in cursor:
                try:
                    self._memory_cache[key] = json.loads(value_str)
                except (json.JSONDecodeError, TypeError):
                    self._memory_cache[key] = value_str
        except Exception as e:
            logger.error(f"Failed to load guard state from SQLite: {e}")

    def _get(self, key: str, default: Any = None) -> Any:
        """Read a value from the storage layers.

        Read path: memory → Redis → SQLite → default
        """
        # 1. Memory cache (fastest)
        if key in self._memory_cache:
            return self._memory_cache[key]

        # 2. Redis cache
        if self._redis:
            try:
                val = self._redis.get(f"{self._redis_prefix}{key}")
                if val is not None:
                    parsed = json.loads(val)
                    self._memory_cache[key] = parsed
                    return parsed
            except Exception:
                pass  # Redis failure — fall through to SQLite

        # 3. SQLite (source of truth)
        if self._conn:
            try:
                cursor = self._conn.execute(
                    "SELECT value FROM guard_state WHERE key = ?",
                    (key,),
                )
                row = cursor.fetchone()
                if row:
                    parsed = json.loads(row[0])
                    self._memory_cache[key] = parsed
                    return parsed
            except Exception as e:
                logger.error(f"GuardState SQLite read error for '{key}': {e}")

        return default

    def _set(self, key: str, value: Any) -> None:
        """Write a value to ALL storage layers (write-through)."""
        now = time.time()
        value_str = json.dumps(value)

        # 1. Memory cache
        self._memory_cache[key] = value

        # 2. SQLite (source of truth) — write first
        if self._conn:
            try:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO guard_state (key, value, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, value_str, now),
                )
            except Exception as e:
                logger.error(f"GuardState SQLite write error for '{key}': {e}")

        # 3. Redis cache (best effort)
        if self._redis:
            try:
                self._redis.setex(
                    f"{self._redis_prefix}{key}",
                    86400,  # 24h TTL for cache
                    value_str,
                )
            except Exception:
                pass  # Redis failure is non-fatal

    def _delete(self, key: str) -> None:
        """Delete a key from ALL storage layers."""
        # 1. Memory
        self._memory_cache.pop(key, None)

        # 2. SQLite
        if self._conn:
            try:
                self._conn.execute(
                    "DELETE FROM guard_state WHERE key = ?",
                    (key,),
                )
            except Exception as e:
                logger.error(f"GuardState SQLite delete error for '{key}': {e}")

        # 3. Redis
        if self._redis:
            try:
                self._redis.delete(f"{self._redis_prefix}{key}")
            except Exception:
                pass

    def close(self) -> None:
        """Close the SQLite connection gracefully."""
        if self._conn:
            try:
                self._conn.close()
                logger.debug("GuardState SQLite connection closed")
            except Exception:
                pass
            self._conn = None
