"""
Harness Memory — OpenHarness persistent memory adapted for TSAR.

Adapts OpenHarness's MEMORY.md pattern:
  - Persistent memory across sessions (MEMORY.md)
  - Daily notes (memory/YYYY-MM-DD.md)
  - Context injection into agent loop
  - Semantic search over memory

TSAR-specific additions:
  - Context compression for long trading sessions
  - Trade outcome tracking in memory
  - Strategy lesson integration from TradeMemory
  - Regime-aware memory retrieval
  - Cost-aware context window management

Memory Hierarchy:
  ┌─────────────────────────────────────────────────┐
  │  MEMORY.md          — Long-term curated memory  │
  │  memory/YYYY-MM-DD  — Daily raw notes           │
  │  trade_memory.db    — SQLite trade records       │
  │  lesson_archive.db  — Distilled lessons          │
  │  context_cache      — Compressed active context  │
  └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.llm.token_counter import count_tokens

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryConfig:
    """Configuration for the harness memory system."""

    # Paths
    memory_file: str = "MEMORY.md"
    daily_dir: str = "memory"
    trade_db_path: str = "data/tsar.db"

    # Context window management
    max_context_tokens: int = 8000
    compression_target_tokens: int = 4000
    model: str = "deepseek-chat"

    # Memory retention
    max_daily_files: int = 30  # Keep last N daily files
    max_memory_entries: int = 200  # Max entries in MEMORY.md
    compress_after_hours: float = 4.0  # Compress context after this long

    # Trade memory integration
    include_recent_trades: int = 10
    include_lessons: bool = True
    include_regime_state: bool = True


@dataclass
class MemoryEntry:
    """A single memory entry."""

    timestamp: str
    category: str  # trade, lesson, observation, decision, strategy
    content: str
    importance: int = 5  # 1-10, higher = more important
    tags: list[str] = field(default_factory=list)
    trade_id: str | None = None

    def to_markdown(self) -> str:
        """Format as markdown for MEMORY.md."""
        tag_str = f" [{', '.join(self.tags)}]" if self.tags else ""
        trade_ref = f" (trade:{self.trade_id})" if self.trade_id else ""
        return f"- **[{self.category}]** {self.timestamp}{tag_str}{trade_ref}: {self.content}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "category": self.category,
            "content": self.content,
            "importance": self.importance,
            "tags": self.tags,
            "trade_id": self.trade_id,
        }


class HarnessMemory:
    """
    OpenHarness-compatible persistent memory adapted for TSAR.

    Provides:
      1. MEMORY.md — Curated long-term memory (read on session start)
      2. Daily notes — Raw session logs in memory/YYYY-MM-DD.md
      3. Context injection — Relevant memory for the agent loop
      4. Context compression — Summarize old context to fit window
      5. Trade memory bridge — Connect to TSAR's TradeMemory store
    """

    def __init__(
        self,
        config: MemoryConfig | None = None,
        workspace_dir: str = ".",
        llm_provider: Any = None,
    ) -> None:
        self._config = config or MemoryConfig()
        self._workspace = Path(workspace_dir)
        self._llm = llm_provider

        # Paths
        self._memory_path = self._workspace / self._config.memory_file
        self._daily_dir = self._workspace / self._config.daily_dir
        self._daily_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache
        self._long_term: list[MemoryEntry] = []
        self._session_context: list[dict[str, Any]] = []
        self._compressed_summary: str = ""
        self._last_compression: float = 0.0

        # Trade memory bridge (lazy-loaded)
        self._trade_memory: Any = None

    # ── Session Lifecycle ─────────────────────────────────────────

    async def on_session_start(self) -> None:
        """Called at the start of an agent session.

        Loads MEMORY.md, recent daily files, and trade context.
        """
        # Load long-term memory
        await self._load_long_term_memory()

        # Load recent daily context
        await self._load_recent_daily()

        logger.info(
            "Memory initialized: %d long-term entries, %d session context items",
            len(self._long_term),
            len(self._session_context),
        )

    async def on_session_end(self) -> None:
        """Called at the end of an agent session.

        Persists session notes to daily file.
        """
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        daily_path = self._daily_dir / f"{today}.md"

        # Append session notes
        lines = []
        for entry in self._session_context:
            if isinstance(entry, dict):
                content = entry.get("content", str(entry))
                lines.append(f"- {content}")

        if lines:
            with open(daily_path, "a", encoding="utf-8") as f:
                f.write(f"\n## Session {datetime.now(UTC).strftime('%H:%M')}\n")
                f.write("\n".join(lines))
                f.write("\n")

    # ── Context for Agent Loop ────────────────────────────────────

    async def get_context(self) -> str:
        """Get relevant context for the agent loop.

        Combines:
          1. Recent MEMORY.md entries
          2. Today's daily notes
          3. Recent trades (from TradeMemory)
          4. Current regime state
          5. Compressed summary of older context

        Returns:
            Formatted context string for system prompt injection.
        """
        parts = []

        # 1. Long-term memory (most important entries)
        important = sorted(
            self._long_term,
            key=lambda e: e.importance,
            reverse=True,
        )[:20]
        if important:
            parts.append("## Long-Term Memory")
            for entry in important:
                parts.append(entry.to_markdown())

        # 2. Compressed summary of older context
        if self._compressed_summary:
            parts.append(f"\n## Previous Session Summary\n{self._compressed_summary}")

        # 3. Recent trades
        if self._config.include_recent_trades:
            trades = await self._get_recent_trades()
            if trades:
                parts.append("\n## Recent Trades")
                for trade in trades:
                    parts.append(f"- {trade}")

        # 4. Current regime
        if self._config.include_regime_state:
            regime = await self._get_regime_state()
            if regime:
                parts.append(f"\n## Current Market Regime\n{regime}")

        # 5. Lessons
        if self._config.include_lessons:
            lessons = await self._get_recent_lessons()
            if lessons:
                parts.append("\n## Recent Lessons")
                for lesson in lessons:
                    parts.append(f"- {lesson}")

        context = "\n".join(parts)

        # Trim to max tokens
        tokens = count_tokens(context, model=self._config.model)
        if tokens > self._config.max_context_tokens:
            # Truncate from the start (keep most recent)
            lines = context.split("\n")
            while (
                count_tokens("\n".join(lines), model=self._config.model)
                > self._config.max_context_tokens
                and len(lines) > 5
            ):
                lines.pop(0)
            context = "\n".join(lines)

        return context

    # ── Memory Operations ─────────────────────────────────────────

    async def remember(
        self,
        content: str,
        category: str = "observation",
        importance: int = 5,
        tags: list[str] | None = None,
        trade_id: str | None = None,
    ) -> MemoryEntry:
        """Store a new memory entry.

        Args:
            content: The memory content.
            category: Category (trade, lesson, observation, decision, strategy).
            importance: Importance level 1-10.
            tags: Optional tags for categorization.
            trade_id: Optional associated trade ID.

        Returns:
            The created MemoryEntry.
        """
        entry = MemoryEntry(
            timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            category=category,
            content=content,
            importance=importance,
            tags=tags or [],
            trade_id=trade_id,
        )

        self._long_term.append(entry)

        # Also add to session context
        self._session_context.append(entry.to_dict())

        # Trim if too many entries
        if len(self._long_term) > self._config.max_memory_entries:
            # Keep most important entries
            self._long_term.sort(key=lambda e: e.importance, reverse=True)
            self._long_term = self._long_term[: self._config.max_memory_entries]

        logger.debug("Remembered: [%s] %s", category, content[:80])
        return entry

    async def remember_trade(
        self,
        trade_data: dict[str, Any],
        outcome: str = "pending",
        lesson: str = "",
    ) -> MemoryEntry:
        """Store a trade-related memory entry.

        Args:
            trade_data: Trade details (symbol, side, entry, etc.).
            outcome: Trade outcome (win, loss, breakeven, pending).
            lesson: Lesson learned from the trade.

        Returns:
            The created MemoryEntry.
        """
        symbol = trade_data.get("symbol", "UNKNOWN")
        side = trade_data.get("side", "?")
        entry_price = trade_data.get("entry_price", 0)
        trade_id = trade_data.get("trade_id")

        content = f"{side} {symbol} @ {entry_price} — {outcome}"
        if lesson:
            content += f" — Lesson: {lesson}"

        tags = [symbol.replace("/", ""), outcome]
        importance = 8 if outcome in ("win", "loss") else 5

        return await self.remember(
            content=content,
            category="trade",
            importance=importance,
            tags=tags,
            trade_id=trade_id,
        )

    async def remember_lesson(self, lesson: str, source: str = "reflection") -> MemoryEntry:
        """Store a lesson learned.

        Args:
            lesson: The lesson content.
            source: Where the lesson came from (reflection, analysis, etc.).

        Returns:
            The created MemoryEntry.
        """
        return await self.remember(
            content=lesson,
            category="lesson",
            importance=8,
            tags=[source],
        )

    # ── Context Compression ───────────────────────────────────────

    async def compress_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Compress message history to fit within context window.

        Strategy:
          1. Keep system messages and last N messages intact
          2. Summarize older messages using LLM
          3. Replace old messages with summary

        Args:
            messages: Current message history.

        Returns:
            Compressed messages, or None if compression not needed/possible.
        """
        if not self._llm:
            logger.warning("No LLM provider for compression")
            return None

        total_tokens = sum(
            count_tokens(m.get("content", ""), model=self._config.model) for m in messages
        )

        if total_tokens <= self._config.compression_target_tokens:
            return None

        # Split: keep system + recent, compress middle
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        keep_recent = 6  # Keep last 6 non-system messages
        to_compress = non_system[:-keep_recent]
        recent = non_system[-keep_recent:]

        if not to_compress:
            return None

        # Build compression prompt
        compress_text = "\n".join(
            f"[{m.get('role', '?')}] {m.get('content', '')[:200]}" for m in to_compress
        )

        try:
            summary_response = await self._llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize this trading conversation history concisely. "
                            "Focus on: decisions made, signals analyzed, trades executed, "
                            "lessons learned. Keep key data points. Max 500 words."
                        ),
                    },
                    {"role": "user", "content": compress_text},
                ],
                model=self._config.model,
                max_tokens=1000,
                temperature=0.1,
            )

            summary = summary_response.get("content", "")

            # Store summary for future reference
            self._compressed_summary = summary
            self._last_compression = time.time()

            # Rebuild messages
            compressed = (
                system_msgs
                + [
                    {"role": "system", "content": f"[Previous context summary]\n{summary}"},
                ]
                + recent
            )

            logger.info(
                "Compressed %d messages → summary + %d recent",
                len(to_compress),
                len(recent),
            )
            return compressed

        except Exception as e:
            logger.error("Context compression failed: %s", e)
            return None

    # ── TSAR Integration ──────────────────────────────────────────

    async def _get_recent_trades(self) -> list[str]:
        """Get recent trade summaries from TradeMemory."""
        try:
            if self._trade_memory is None:
                from src.knowledge.trade_memory import TradeMemory

                db_path = self._config.trade_db_path
                self._trade_memory = TradeMemory(db_path)

            trades = self._trade_memory.get_recent_trades(
                limit=self._config.include_recent_trades,
            )
            summaries = []
            for t in trades:
                symbol = getattr(t, "symbol", "?")
                side = getattr(t, "side", "?")
                pnl = getattr(t, "realized_pnl", 0)
                status = getattr(t, "status", "?")
                summaries.append(f"{side} {symbol} | P&L: {pnl:.2f} | {status}")
            return summaries
        except Exception as e:
            logger.debug("Could not load recent trades: %s", e)
            return []

    async def _get_regime_state(self) -> str:
        """Get current market regime from RegimeState store."""
        try:
            from src.knowledge.regime_state import RegimeState

            regime = RegimeState()
            state = regime.get_current()
            if state:
                return (
                    f"Regime: {state.get('regime', 'unknown')} "
                    f"(confidence: {state.get('confidence', 0):.0%})"
                )
        except Exception:
            pass
        return ""

    async def _get_recent_lessons(self) -> list[str]:
        """Get recent lessons from LessonArchive."""
        try:
            from src.knowledge.lesson_archive import LessonArchive

            archive = LessonArchive()
            lessons = archive.get_recent(limit=5)
            return [l.get("content", str(l)) for l in lessons]
        except Exception:
            return []

    # ── Persistence ───────────────────────────────────────────────

    async def _load_long_term_memory(self) -> None:
        """Load MEMORY.md into long-term memory."""
        if not self._memory_path.exists():
            return

        try:
            content = self._memory_path.read_text(encoding="utf-8")
            # Parse markdown entries
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("- **["):
                    # Parse: - **[category]** timestamp [tags]: content
                    entry = self._parse_memory_line(line)
                    if entry:
                        self._long_term.append(entry)
            logger.info("Loaded %d entries from MEMORY.md", len(self._long_term))
        except Exception as e:
            logger.error("Failed to load MEMORY.md: %s", e)

    async def _load_recent_daily(self) -> None:
        """Load today's and yesterday's daily files."""
        from datetime import timedelta

        now = datetime.now(UTC)
        for delta in [0, 1]:
            day = (now - timedelta(days=delta)).strftime("%Y-%m-%d")
            daily_path = self._daily_dir / f"{day}.md"
            if daily_path.exists():
                try:
                    content = daily_path.read_text(encoding="utf-8")
                    self._session_context.append(
                        {
                            "content": f"[{day} notes]\n{content[:2000]}",
                        }
                    )
                except Exception:
                    pass

    async def persist_long_term(self) -> None:
        """Write long-term memory to MEMORY.md."""
        lines = [
            "# TSAR Memory — Long-Term",
            "",
            f"_Last updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_",
            "",
        ]

        # Group by category
        by_category: dict[str, list[MemoryEntry]] = {}
        for entry in self._long_term:
            by_category.setdefault(entry.category, []).append(entry)

        for category, entries in sorted(by_category.items()):
            lines.append(f"## {category.title()}")
            lines.append("")
            for entry in sorted(entries, key=lambda e: e.timestamp, reverse=True):
                lines.append(entry.to_markdown())
            lines.append("")

        self._memory_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Persisted %d entries to MEMORY.md", len(self._long_term))

    def _parse_memory_line(self, line: str) -> MemoryEntry | None:
        """Parse a MEMORY.md line into a MemoryEntry."""
        import re

        pattern = (
            r"^- \*\*\[(\w+)\]\*\*\s+(\S+)(?:\s+\[([^\]]*)\])?(?:\s+\(trade:(\w+)\))?:\s+(.+)$"
        )
        match = re.match(pattern, line)
        if not match:
            return None
        return MemoryEntry(
            timestamp=match.group(2),
            category=match.group(1),
            content=match.group(5),
            tags=match.group(3).split(", ") if match.group(3) else [],
            trade_id=match.group(4),
        )
