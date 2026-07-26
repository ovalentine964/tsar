"""
TSAR Factor Library — Factor Management & Persistence.

FactorLibrary manages factor registration, metadata, IC history, and decay
tracking. It delegates pure computation to factors.py functions.

Features:
  - Register/retrieve factors by name, category, or universe
  - Compute factor values from OHLCV DataFrames
  - Persist factor metadata, IC history, and decay to SQLite
  - Support custom factor registration

Usage:
    lib = FactorLibrary("factors.db")
    values = lib.compute("rsi", ohlcv_df)
    momentum_factors = lib.get_factors_by_category("momentum")
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.strategy.factors import FACTOR_REGISTRY

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FactorMeta:
    """Metadata for a registered factor."""

    name: str
    description: str
    category: str  # momentum | mean_reversion | volatility | volume | trend | pattern
    default_params: dict[str, Any]
    universe: list[str]
    custom: bool = False


@dataclass
class ICRecord:
    """A single Information Coefficient observation."""

    factor_name: str
    timestamp: str
    ic_value: float
    forward_period: int
    symbol: str = ""


# ═══════════════════════════════════════════════════════════════════════
# FACTOR LIBRARY
# ═══════════════════════════════════════════════════════════════════════


class FactorLibrary:
    """Manages a library of quantitative trading factors.

    Combines an in-memory registry of compute functions with SQLite
    persistence for factor metadata, IC history, and decay tracking.
    """

    VALID_CATEGORIES = {"momentum", "mean_reversion", "volatility", "volume", "trend", "pattern"}

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Initialize the factor library.

        G13 NOTE: FactorLibrary intentionally uses a separate SQLite database
        (factors.db) from the main tsar.db.  This is a deliberate design
        decision — factors are a different concern from trade records,
        strategy genomes, and lessons.  The factor DB contains only
        factor metadata and IC history, which are computationally derived
        and can be regenerated from scratch.  Keeping them separate avoids
        coupling the factor benchmarking lifecycle to the core trading DB,
        simplifies backup/restore of the trading state, and allows the
        factor DB to be shared across environments without leaking trade data.

        Args:
            db_path: Path to SQLite database, or ":memory:" for in-memory.
        """
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row

        # In-memory registry: name -> compute function
        self._functions: dict[str, Callable[..., pd.Series]] = {}

        # In-memory metadata cache
        self._meta: dict[str, FactorMeta] = {}

        # Bootstrap: load built-in factors from FACTOR_REGISTRY
        self._init_db()
        self._load_builtin_factors()

    # ── Lifecycle ────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS factors (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                default_params TEXT NOT NULL DEFAULT '{}',
                universe TEXT NOT NULL DEFAULT '[]',
                custom INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS ic_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                ic_value REAL NOT NULL,
                forward_period INTEGER NOT NULL DEFAULT 1,
                symbol TEXT DEFAULT '',
                FOREIGN KEY (factor_name) REFERENCES factors(name)
            );

            CREATE INDEX IF NOT EXISTS idx_ic_factor ON ic_history(factor_name);
            CREATE INDEX IF NOT EXISTS idx_ic_timestamp ON ic_history(timestamp);
        """)
        self._conn.commit()

    def _load_builtin_factors(self) -> None:
        """Register all built-in factors from FACTOR_REGISTRY."""
        for name, entry in FACTOR_REGISTRY.items():
            meta = FactorMeta(
                name=name,
                description=str(entry["description"]),
                category=str(entry["category"]),
                default_params=dict(entry.get("default_params", {})),  # type: ignore[arg-type]
                universe=list(entry.get("universe", [])),  # type: ignore[arg-type]
                custom=False,
            )
            self._functions[name] = entry["func"]  # type: ignore[assignment]
            self._meta[name] = meta
            self._upsert_factor_db(meta)

    def _upsert_factor_db(self, meta: FactorMeta) -> None:
        """Insert or update factor metadata in SQLite."""
        self._conn.execute(
            """INSERT OR REPLACE INTO factors (name, description, category, default_params, universe, custom)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                meta.name,
                meta.description,
                meta.category,
                json.dumps(meta.default_params),
                json.dumps(meta.universe),
                int(meta.custom),
            ),
        )
        self._conn.commit()

    # ── Registration ─────────────────────────────────────────

    def register(
        self,
        name: str,
        func: Callable[..., pd.Series],
        category: str,
        description: str = "",
        default_params: dict[str, Any] | None = None,
        universe: list[str] | None = None,
    ) -> None:
        """Register a custom factor.

        Args:
            name: Unique factor name.
            func: Compute function (df, **kwargs) -> pd.Series.
            category: Factor category.
            description: Human-readable description.
            default_params: Default parameters for the factor.
            universe: Asset classes this factor applies to.

        Raises:
            ValueError: If category is invalid.
        """
        if category not in self.VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. Must be one of {self.VALID_CATEGORIES}"
            )

        meta = FactorMeta(
            name=name,
            description=description or f"Custom factor: {name}",
            category=category,
            default_params=default_params or {},
            universe=universe or ["crypto", "equity"],
            custom=True,
        )
        self._functions[name] = func
        self._meta[name] = meta
        self._upsert_factor_db(meta)
        logger.info("Registered custom factor: %s [%s]", name, category)

    # ── Retrieval ────────────────────────────────────────────

    def get_factor_meta(self, name: str) -> FactorMeta | None:
        """Get metadata for a factor by name."""
        return self._meta.get(name)

    def get_factors_by_category(self, category: str) -> list[FactorMeta]:
        """Get all factors in a category."""
        return [m for m in self._meta.values() if m.category == category]

    def get_factors_by_universe(self, symbol_type: str) -> list[FactorMeta]:
        """Get all factors applicable to a given asset class."""
        return [m for m in self._meta.values() if symbol_type in m.universe]

    def list_factors(self) -> list[FactorMeta]:
        """List all registered factors."""
        return list(self._meta.values())

    def get_categories(self) -> dict[str, int]:
        """Get factor counts by category."""
        counts: dict[str, int] = {}
        for m in self._meta.values():
            counts[m.category] = counts.get(m.category, 0) + 1
        return counts

    # ── Computation ──────────────────────────────────────────

    def compute(
        self,
        factor_name: str,
        ohlcv_data: pd.DataFrame,
        **override_params: Any,
    ) -> pd.Series:
        """Compute a factor's values from OHLCV data.

        Args:
            factor_name: Name of the factor to compute.
            ohlcv_data: DataFrame with columns [open, high, low, close, volume].
            **override_params: Override default parameters.

        Returns:
            pd.Series of factor values aligned to ohlcv_data index.

        Raises:
            KeyError: If factor_name is not registered.
        """
        if factor_name not in self._functions:
            raise KeyError(
                f"Factor '{factor_name}' not registered. "
                f"Available: {list(self._functions.keys())}"
            )

        # Merge default params with overrides
        meta = self._meta[factor_name]
        params = {**meta.default_params, **override_params}

        func = self._functions[factor_name]
        return func(ohlcv_data, **params)

    def compute_all(
        self,
        ohlcv_data: pd.DataFrame,
        category: str | None = None,
        **override_params: Any,
    ) -> pd.DataFrame:
        """Compute all factors (or a category) and return as DataFrame.

        Args:
            ohlcv_data: OHLCV DataFrame.
            category: If set, only compute factors in this category.
            **override_params: Override params for all factors.

        Returns:
            DataFrame with one column per factor.
        """
        targets = self.get_factors_by_category(category) if category else self.list_factors()
        results: dict[str, pd.Series] = {}
        for meta in targets:
            try:
                results[meta.name] = self.compute(meta.name, ohlcv_data, **override_params)
            except Exception as e:
                logger.warning("Failed to compute factor %s: %s", meta.name, e)
                results[meta.name] = pd.Series(dtype=float, index=ohlcv_data.index)
        return pd.DataFrame(results)

    # ── IC History Persistence ───────────────────────────────

    def record_ic(
        self,
        factor_name: str,
        timestamp: str,
        ic_value: float,
        forward_period: int = 1,
        symbol: str = "",
    ) -> None:
        """Record an IC observation for a factor.

        Args:
            factor_name: Factor name.
            timestamp: ISO timestamp of the observation.
            ic_value: Computed IC value.
            forward_period: Forward return period used.
            symbol: Symbol this IC was computed on.
        """
        self._conn.execute(
            """INSERT INTO ic_history (factor_name, timestamp, ic_value, forward_period, symbol)
               VALUES (?, ?, ?, ?, ?)""",
            (factor_name, timestamp, ic_value, forward_period, symbol),
        )
        self._conn.commit()

    def get_ic_history(
        self,
        factor_name: str,
        limit: int = 1000,
    ) -> list[ICRecord]:
        """Retrieve IC history for a factor.

        Args:
            factor_name: Factor name.
            limit: Max records to return.

        Returns:
            List of ICRecord instances.
        """
        rows = self._conn.execute(
            """SELECT factor_name, timestamp, ic_value, forward_period, symbol
               FROM ic_history WHERE factor_name = ? ORDER BY timestamp DESC LIMIT ?""",
            (factor_name, limit),
        ).fetchall()
        return [
            ICRecord(
                factor_name=r["factor_name"],
                timestamp=r["timestamp"],
                ic_value=r["ic_value"],
                forward_period=r["forward_period"],
                symbol=r["symbol"],
            )
            for r in rows
        ]

    def get_all_ic_records(self, limit: int = 10000) -> list[ICRecord]:
        """Retrieve all IC records across all factors."""
        rows = self._conn.execute(
            """SELECT factor_name, timestamp, ic_value, forward_period, symbol
               FROM ic_history ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            ICRecord(
                factor_name=r["factor_name"],
                timestamp=r["timestamp"],
                ic_value=r["ic_value"],
                forward_period=r["forward_period"],
                symbol=r["symbol"],
            )
            for r in rows
        ]
