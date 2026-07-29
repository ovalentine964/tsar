"""TSAR — Unified FTS5 Semantic Memory Recall.

Searches across all 5 knowledge stores using SQLite FTS5 full-text indexes.
Provides ranked, cross-store results with relevance scoring.

Handles CJK, Thai, Arabic, Cyrillic via unicode61 tokenizer + tokenchars.
Treats underscores as token boundaries for snake_case terms.

Persistence: SQLite (WAL mode, tsar.db) — async via aiosqlite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

from src.utils.logging import get_logger

logger = get_logger(__name__)


# ── Store registry ──────────────────────────────────────────

# Maps store name → (fts_table, source_table, searchable_columns, id_column)
_STORE_REGISTRY: dict[str, dict[str, Any]] = {
    "trade_records": {
        "fts_table": "trade_records_fts",
        "source_table": "trade_records",
        "columns": ["thesis", "reflection", "notes"],
        "id_column": "trade_id",
        "label_columns": ["symbol", "thesis"],
    },
    "strategy_genomes": {
        "fts_table": "strategy_genomes_fts",
        "source_table": "strategy_genomes",
        "columns": ["name", "thesis", "strategy_type"],
        "id_column": "strategy_id",
        "label_columns": ["name", "thesis"],
    },
    "patterns": {
        "fts_table": "patterns_fts",
        "source_table": "patterns",
        "columns": ["pattern_name", "description", "tags"],
        "id_column": "pattern_id",
        "label_columns": ["pattern_name", "description"],
    },
    "lessons": {
        "fts_table": "lessons_fts",
        "source_table": "lessons",
        "columns": ["title", "description", "action_item", "content", "tags"],
        "id_column": "lesson_id",
        "label_columns": ["title", "description"],
    },
}

# All valid store names
VALID_STORES = frozenset(_STORE_REGISTRY.keys())


# ── Result dataclass ────────────────────────────────────────


@dataclass
class SearchResult:
    """A single search hit from any knowledge store."""

    store: str
    record_id: str
    score: float
    snippet: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "record_id": self.record_id,
            "score": self.score,
            "snippet": self.snippet,
            "data": self.data,
        }


# ── Query formatting ────────────────────────────────────────

# CJK Unified Ideographs + Extensions, Thai, Arabic, Cyrillic, etc.
_CJK_RANGES = (
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Extension A
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x2E80, 0x2EFF),    # CJK Radicals Supplement
    (0x3000, 0x303F),    # CJK Symbols and Punctuation
    (0x0E00, 0x0E7F),    # Thai
    (0x0600, 0x06FF),    # Arabic
    (0x0400, 0x04FF),    # Cyrillic
    (0x0370, 0x03FF),    # Greek
    (0x0500, 0x052F),    # Cyrillic Supplement
)


def _is_cjk_aware_char(ch: str) -> bool:
    """Check if a single character belongs to a CJK / non-Latin script."""
    if len(ch) != 1:
        return False
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _is_cjk_token(token: str) -> bool:
    """Check if a token consists entirely of CJK / non-Latin characters."""
    return all(_is_cjk_aware_char(ch) for ch in token) if token else False


def _has_cjk_chars(text: str) -> bool:
    """Check if text contains any CJK / non-Latin script characters."""
    return any(_is_cjk_aware_char(ch) for ch in text)


def _tokenize_for_fts(query: str) -> list[str]:
    """Tokenize a query into FTS5-compatible terms.

    Rules:
    - Split on whitespace and punctuation (except underscore)
    - Treat underscores as token boundaries (snake_case → separate terms)
    - For CJK/Thai/Arabic/Cyrillic characters, emit each character as a
      separate prefix token (FTS5 prefix search: char*)
    - Drop tokens shorter than 2 chars (except CJK singles)
    - Deduplicate while preserving order
    """
    # Step 1: Replace underscores with spaces (snake_case boundary)
    normalized = query.replace("_", " ")

    # Step 2: Extract Latin/alphanumeric tokens
    latin_tokens = re.findall(r"[a-zA-Z0-9]{2,}", normalized)

    # Step 3: Extract CJK/non-Latin characters individually for prefix search
    cjk_chars: list[str] = []
    for ch in normalized:
        if _is_cjk_aware_char(ch) and not ch.isspace():
            cjk_chars.append(ch)

    # Step 4: Deduplicate, preserving order
    seen: set[str] = set()
    tokens: list[str] = []
    for t in latin_tokens:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            tokens.append(tl)
    for ch in cjk_chars:
        if ch not in seen:
            seen.add(ch)
            tokens.append(ch)

    return tokens


def format_fts_query(query: str) -> str:
    """Convert a natural-language query into a valid FTS5 MATCH expression.

    Strategy: OR-match across all terms.  CJK characters use prefix matching
    (single char*) so they match multi-character CJK words in the index.

    Returns a string safe for ``WHERE fts MATCH ?``.
    """
    tokens = _tokenize_for_fts(query)
    if not tokens:
        return '""'  # matches nothing

    parts: list[str] = []
    for tok in tokens:
        if _is_cjk_token(tok):
            # Prefix match for CJK single characters
            parts.append(f'"{tok}"*')
        else:
            parts.append(f'"{tok}"')

    return " OR ".join(parts)


# ── Main class ──────────────────────────────────────────────


class MemoryRecall:
    """Unified FTS5 search across all TSAR knowledge stores.

    Usage::

        recall = MemoryRecall("/path/to/tsar.db")
        await recall.initialize()

        results = await recall.search("mean reversion BTC oversold")
        results = await recall.search("stop_loss", stores=["trade_records", "lessons"])
        results = await recall.search("趋势反转", stores=["patterns"])  # CJK

        await recall.close()
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    # ── Lifecycle ────────────────────────────────────────────

    async def initialize(self) -> None:
        """Open the database connection and verify FTS5 tables exist."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")

        # Verify FTS5 virtual tables exist; create if missing
        await self._ensure_fts_tables()

        logger.info("memory_recall_initialized", db_path=self._db_path)

    async def _ensure_fts_tables(self) -> None:
        """Create FTS5 virtual tables and triggers if they don't already exist.

        This is idempotent — safe to call on an existing database that was
        set up by the migration.  Also useful for test databases created from
        the migration SQL.

        G11 NOTE: Existing databases without FTS5 indexes will have them
        created on first ``initialize()`` call.  No separate migration step
        is required.  The CREATE VIRTUAL TABLE IF NOT EXISTS and
        CREATE TRIGGER IF NOT EXISTS clauses ensure this is safe to run
        repeatedly on databases that already have these tables.
        """
        assert self._db is not None

        for _store_name, cfg in _STORE_REGISTRY.items():
            fts = cfg["fts_table"]
            src = cfg["source_table"]
            cols = cfg["columns"]
            cols_sql = ", ".join(cols)

            # Check if FTS table exists
            row = await self._db.execute_fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (fts,),
            )
            if row:
                continue  # already exists (from migration)

            # Create FTS5 virtual table (content-synced)
            create_sql = (
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts} USING fts5("
                f"{cols_sql}, "
                f"content={src}, "
                f"content_rowid=rowid, "
                f"tokenize='porter unicode61 remove_diacritics 2'"
                f")"
            )
            await self._db.execute(create_sql)

            # Create sync triggers
            new_cols = ", ".join(f"new.{c}" for c in cols)
            old_cols = ", ".join(f"old.{c}" for c in cols)
            quoted_cols = ", ".join(cols)

            await self._db.execute(f"""
                CREATE TRIGGER IF NOT EXISTS trg_{fts}_insert
                AFTER INSERT ON {src} BEGIN
                    INSERT INTO {fts}(rowid, {quoted_cols})
                    VALUES (new.rowid, {new_cols});
                END
            """)
            await self._db.execute(f"""
                CREATE TRIGGER IF NOT EXISTS trg_{fts}_delete
                AFTER DELETE ON {src} BEGIN
                    INSERT INTO {fts}({fts}, rowid, {quoted_cols})
                    VALUES ('delete', old.rowid, {old_cols});
                END
            """)
            await self._db.execute(f"""
                CREATE TRIGGER IF NOT EXISTS trg_{fts}_update
                AFTER UPDATE ON {src} BEGIN
                    INSERT INTO {fts}({fts}, rowid, {quoted_cols})
                    VALUES ('delete', old.rowid, {old_cols});
                    INSERT INTO {fts}(rowid, {quoted_cols})
                    VALUES (new.rowid, {new_cols});
                END
            """)

            await self._db.commit()
            logger.info("fts_table_created", fts_table=fts, source=src)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> MemoryRecall:
        await self.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ── Search ───────────────────────────────────────────────

    async def search(
        self,
        query: str,
        stores: list[str] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Search across knowledge stores using FTS5.

        Args:
            query: Natural language query.  Supports CJK, snake_case, etc.
            stores: Restrict to these store names.  ``None`` = all stores.
            limit: Maximum results per store (total may be up to
                   ``limit * len(stores)`` before final merge-sort).

        Returns:
            List of ``SearchResult`` sorted by relevance (lowest BM25 rank
            first, i.e. best match first).
        """
        if not query or not query.strip():
            return []

        if self._db is None:
            raise RuntimeError("MemoryRecall not initialized. Call initialize() first.")

        fts_query = format_fts_query(query)
        if fts_query == '""':
            return []

        target_stores = self._resolve_stores(stores)

        all_results: list[SearchResult] = []
        for store_name in target_stores:
            results = await self._search_store(store_name, fts_query, limit, raw_query=query)
            all_results.extend(results)

        # Sort by score (BM25 rank — lower is better)
        all_results.sort(key=lambda r: r.score)
        return all_results

    async def _search_store(
        self,
        store_name: str,
        fts_query: str,
        limit: int,
        raw_query: str = "",
    ) -> list[SearchResult]:
        """Search a single store and return ranked results."""
        assert self._db is not None
        cfg = _STORE_REGISTRY[store_name]
        fts_table = cfg["fts_table"]
        src_table = cfg["source_table"]
        id_col = cfg["id_column"]
        cols = cfg["columns"]

        cols_sql = ", ".join(f"s.{c}" for c in cols)

        # Build snippet from first label column using FTS5 snippet()
        snippet_expr = f"snippet({fts_table}, 0, '<b>', '</b>', '…', 32)"

        sql = f"""
            SELECT
                s.{id_col} AS record_id,
                fts.rank AS bm25_score,
                {snippet_expr} AS snippet,
                {cols_sql}
            FROM {fts_table} fts
            JOIN {src_table} s ON s.rowid = fts.rowid
            WHERE {fts_table} MATCH ?
            ORDER BY fts.rank
            LIMIT ?
        """

        results: list[SearchResult] = []
        try:
            async with self._db.execute(sql, (fts_query, limit)) as cursor:
                async for row in cursor:
                    data = {col: row[col] for col in cols if row[col] is not None}
                    results.append(
                        SearchResult(
                            store=store_name,
                            record_id=row["record_id"],
                            score=row["bm25_score"],
                            snippet=row["snippet"] or "",
                            data=data,
                        )
                    )
        except Exception as exc:
            logger.warning(
                "fts_search_error",
                store=store_name,
                error=str(exc),
                query=fts_query,
            )

        # CJK fallback: unicode61 tokenizer stores CJK as one continuous token,
        # so FTS5 MATCH won't find substrings. Use LIKE as fallback.
        if not results and raw_query and _has_cjk_chars(raw_query):
            results = await self._like_search(store_name, raw_query, limit)

        return results

    async def _like_search(
        self,
        store_name: str,
        query: str,
        limit: int,
    ) -> list[SearchResult]:
        """Fallback LIKE search for CJK queries that FTS5 can't handle."""
        assert self._db is not None
        cfg = _STORE_REGISTRY[store_name]
        src_table = cfg["source_table"]
        id_col = cfg["id_column"]
        cols = cfg["columns"]

        like_conditions = " OR ".join(f"s.{c} LIKE ?" for c in cols)
        cols_sql = ", ".join(f"s.{c}" for c in cols)
        like_pattern = f"%{query}%"
        params = [like_pattern] * len(cols) + [limit]

        sql = f"""
            SELECT s.{id_col} AS record_id, 0.0 AS bm25_score, '' AS snippet, {cols_sql}
            FROM {src_table} s
            WHERE ({like_conditions})
            LIMIT ?
        """

        results: list[SearchResult] = []
        try:
            async with self._db.execute(sql, params) as cursor:
                async for row in cursor:
                    data = {col: row[col] for col in cols if row[col] is not None}
                    snippet = ""
                    for c in cols:
                        val = row[c]
                        if val and query in str(val):
                            idx = str(val).find(query)
                            start = max(0, idx - 20)
                            end = min(len(str(val)), idx + len(query) + 20)
                            snippet = "…" + str(val)[start:end] + "…"
                            break
                    results.append(
                        SearchResult(
                            store=store_name,
                            record_id=row["record_id"],
                            score=row["bm25_score"],
                            snippet=snippet,
                            data=data,
                        )
                    )
        except Exception as exc:
            logger.warning("like_search_error", store=store_name, error=str(exc))

        return results

    @staticmethod
    def _resolve_stores(stores: list[str] | None) -> list[str]:
        """Validate and resolve store names."""
        if stores is None:
            return list(VALID_STORES)
        resolved: list[str] = []
        for s in stores:
            if s in _STORE_REGISTRY:
                resolved.append(s)
            else:
                logger.warning("unknown_store_ignored", store=s)
        return resolved

    # ── Convenience methods ──────────────────────────────────

    async def search_trade_thesis(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Search only trade_records (thesis, reflection, notes)."""
        return await self.search(query, stores=["trade_records"], limit=limit)

    async def search_strategies(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Search only strategy_genomes (name, thesis, type)."""
        return await self.search(query, stores=["strategy_genomes"], limit=limit)

    async def search_patterns(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Search only patterns (name, description, tags)."""
        return await self.search(query, stores=["patterns"], limit=limit)

    async def search_lessons(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Search only lessons (title, description, action_item, content, tags)."""
        return await self.search(query, stores=["lessons"], limit=limit)

    # ── Index management ─────────────────────────────────────

    async def rebuild_index(self, store_name: str | None = None) -> int:
        """Rebuild FTS5 index(es) via INSERT INTO fts(fts) VALUES('rebuild').

        Useful after bulk inserts that bypassed triggers, or to recover from
        index corruption.

        Returns the number of stores rebuilt.
        """
        assert self._db is not None
        targets = self._resolve_stores([store_name] if store_name else None)
        count = 0
        for sn in targets:
            fts_table = _STORE_REGISTRY[sn]["fts_table"]
            try:
                await self._db.execute(
                    f"INSERT INTO {fts_table}({fts_table}) VALUES('rebuild')"
                )
                count += 1
                logger.info("fts_index_rebuilt", store=sn)
            except Exception as exc:
                logger.error("fts_rebuild_failed", store=sn, error=str(exc))
        await self._db.commit()
        return count

    async def get_index_stats(self) -> dict[str, Any]:
        """Return row counts for each FTS index and source table."""
        assert self._db is not None
        stats: dict[str, Any] = {}
        for sn, cfg in _STORE_REGISTRY.items():
            fts_table = cfg["fts_table"]
            src_table = cfg["source_table"]
            try:
                src_row = await self._db.execute_fetchall(
                    f"SELECT COUNT(*) AS cnt FROM {src_table}"
                )
                fts_row = await self._db.execute_fetchall(
                    f"SELECT COUNT(*) AS cnt FROM {fts_table}"
                )
                stats[sn] = {
                    "source_rows": src_row[0]["cnt"] if src_row else 0,
                    "fts_rows": fts_row[0]["cnt"] if fts_row else 0,
                }
            except Exception:
                stats[sn] = {"source_rows": -1, "fts_rows": -1, "error": True}
        return stats
