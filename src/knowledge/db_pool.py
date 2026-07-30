"""TSAR — SQLite Connection Pool.

Thread-safe SQLite connection pool with configurable size, WAL mode,
and health checking. Designed for the knowledge stores that use SQLite
(TradeMemory, FTS Search, Pattern Library, etc.).

Usage::

    pool = SQLitePool("data/tsar.db", pool_size=5)
    conn = pool.acquire()
    try:
        cursor = conn.execute("SELECT * FROM trade_records LIMIT 1")
    finally:
        pool.release(conn)

    # Context manager
    with pool.connection() as conn:
        conn.execute("SELECT * FROM trade_records LIMIT 1")

    # Configure via environment or config
    pool = SQLitePool.from_config({
        "db_path": "data/tsar.db",
        "pool_size": 5,
        "max_overflow": 3,
        "timeout": 10,
        "journal_mode": "WAL",
    })
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)


class SQLitePool:
    """Thread-safe SQLite connection pool.

    Maintains a pool of reusable SQLite connections with WAL mode,
    foreign keys, and busy timeout pre-configured. Supports configurable
    pool size and overflow connections.

    Args:
        db_path: Path to the SQLite database file.
        pool_size: Number of persistent connections in the pool.
        max_overflow: Additional connections allowed beyond pool_size.
        timeout: Connection timeout in seconds.
        journal_mode: SQLite journal mode (default "WAL").
        foreign_keys: Enable foreign key constraints.
        busy_timeout: SQLite busy timeout in milliseconds.
    """

    def __init__(
        self,
        db_path: str | Path,
        pool_size: int = 5,
        max_overflow: int = 3,
        timeout: float = 10.0,
        journal_mode: str = "WAL",
        foreign_keys: bool = True,
        busy_timeout: int = 5000,
    ) -> None:
        self._db_path = str(db_path)
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._timeout = timeout
        self._journal_mode = journal_mode
        self._foreign_keys = foreign_keys
        self._busy_timeout = busy_timeout

        # Ensure parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Pool state
        self._pool: list[sqlite3.Connection] = []
        self._in_use: set[sqlite3.Connection] = set()
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(pool_size + max_overflow)

        # Stats
        self._created = 0
        self._acquired = 0
        self._released = 0
        self._errors = 0

        # Pre-populate pool
        self._populate_pool()

        logger.info(
            "SQLitePool initialized: db=%s, pool_size=%d, max_overflow=%d",
            self._db_path,
            self._pool_size,
            self._max_overflow,
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> SQLitePool:
        """Create a pool from a configuration dict.

        Args:
            config: Dict with keys: db_path, pool_size, max_overflow,
                    timeout, journal_mode, foreign_keys, busy_timeout.

        Returns:
            SQLitePool instance.
        """
        return cls(
            db_path=config.get("db_path", "data/tsar.db"),
            pool_size=config.get("pool_size", 5),
            max_overflow=config.get("max_overflow", 3),
            timeout=config.get("timeout", 10.0),
            journal_mode=config.get("journal_mode", "WAL"),
            foreign_keys=config.get("foreign_keys", True),
            busy_timeout=config.get("busy_timeout", 5000),
        )

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with standard pragmas."""
        conn = sqlite3.connect(
            self._db_path,
            timeout=self._timeout,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        # Apply standard pragmas
        conn.execute(f"PRAGMA journal_mode={self._journal_mode}")
        if self._foreign_keys:
            conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={self._busy_timeout}")

        self._created += 1
        return conn

    def _populate_pool(self) -> None:
        """Pre-populate the pool with connections."""
        with self._lock:
            for _ in range(self._pool_size):
                try:
                    conn = self._create_connection()
                    self._pool.append(conn)
                except Exception as exc:
                    logger.error("Failed to create pool connection: %s", exc)
                    break

    def acquire(self) -> sqlite3.Connection:
        """Acquire a connection from the pool.

        Blocks up to ``timeout`` seconds if the pool is exhausted.

        Returns:
            A SQLite connection.

        Raises:
            TimeoutError: If no connection available within timeout.
        """
        acquired = self._semaphore.acquire(timeout=self._timeout)
        if not acquired:
            raise TimeoutError(
                f"Could not acquire connection within {self._timeout}s "
                f"(pool_size={self._pool_size}, in_use={len(self._in_use)})"
            )

        with self._lock:
            # Try to get an existing idle connection
            if self._pool:
                conn = self._pool.pop()
                # Verify connection is alive
                try:
                    conn.execute("SELECT 1")
                    self._in_use.add(conn)
                    self._acquired += 1
                    return conn
                except Exception:
                    # Dead connection, create a new one
                    try:
                        conn.close()
                    except Exception:
                        pass

            # Create a new connection (overflow)
            try:
                conn = self._create_connection()
                self._in_use.add(conn)
                self._acquired += 1
                return conn
            except Exception as exc:
                self._semaphore.release()
                self._errors += 1
                raise RuntimeError(f"Failed to create connection: {exc}") from exc

    def release(self, conn: sqlite3.Connection) -> None:
        """Release a connection back to the pool.

        Args:
            conn: The connection to release.
        """
        with self._lock:
            self._in_use.discard(conn)

            # Return to pool if below pool_size, otherwise close
            if len(self._pool) < self._pool_size:
                try:
                    conn.execute("SELECT 1")
                    self._pool.append(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
            else:
                try:
                    conn.close()
                except Exception:
                    pass

            self._released += 1
        self._semaphore.release()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for acquiring and releasing a connection.

        Usage::

            with pool.connection() as conn:
                conn.execute("SELECT * FROM trade_records")
        """
        conn = self.acquire()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.release(conn)

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for a transaction (explicit commit/rollback).

        Same as connection() but makes the transaction semantics explicit.

        Usage::

            with pool.transaction() as conn:
                conn.execute("INSERT INTO ...")
                conn.execute("UPDATE ...")
                # Auto-commits on success, rolls back on exception
        """
        conn = self.acquire()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.release(conn)

    def close_all(self) -> None:
        """Close all connections in the pool."""
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._pool.clear()

            for conn in list(self._in_use):
                try:
                    conn.close()
                except Exception:
                    pass
            self._in_use.clear()

        logger.info("SQLitePool closed all connections")

    def get_stats(self) -> dict[str, Any]:
        """Get pool statistics.

        Returns:
            Dict with pool_size, idle, in_use, created, acquired,
            released, errors, and total_capacity.
        """
        with self._lock:
            return {
                "db_path": self._db_path,
                "pool_size": self._pool_size,
                "max_overflow": self._max_overflow,
                "idle": len(self._pool),
                "in_use": len(self._in_use),
                "total_capacity": self._pool_size + self._max_overflow,
                "connections_created": self._created,
                "acquisitions": self._acquired,
                "releases": self._released,
                "errors": self._errors,
            }

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        try:
            self.close_all()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# Module-level pool management
# ═══════════════════════════════════════════════════════════════

_global_pools: dict[str, SQLitePool] = {}
_pool_lock = threading.Lock()


def get_pool(
    db_path: str = "data/tsar.db",
    pool_size: int = 5,
    max_overflow: int = 3,
    **kwargs: Any,
) -> SQLitePool:
    """Get or create a named connection pool (singleton per db_path).

    Args:
        db_path: Path to the SQLite database.
        pool_size: Pool size for new pools.
        max_overflow: Max overflow for new pools.
        **kwargs: Additional pool configuration.

    Returns:
        SQLitePool instance.
    """
    with _pool_lock:
        if db_path not in _global_pools:
            _global_pools[db_path] = SQLitePool(
                db_path=db_path,
                pool_size=pool_size,
                max_overflow=max_overflow,
                **kwargs,
            )
        return _global_pools[db_path]


def close_all_pools() -> None:
    """Close all global connection pools."""
    with _pool_lock:
        for pool in _global_pools.values():
            pool.close_all()
        _global_pools.clear()
