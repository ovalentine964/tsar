"""TSAR Notification Engine — Smart alert delivery for Telegram.

Provides:
- Priority-based delivery (CRITICAL bypasses quiet hours)
- Aggregation of similar events within time windows
- Quiet hours (no non-critical alerts during sleep)
- Rate limiting to prevent Telegram API abuse
- Deduplication of identical alerts within cooldown periods
- Scheduled report generation (daily/weekly/monthly)

Integrates with:
- EventBus (receives CloudEvents)
- TsarBot (sends formatted messages)
- All TSAR subsystems (via event subscriptions)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import time as dt_time
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Priority Levels
# ═══════════════════════════════════════════════════════════════════════


class Priority(IntEnum):
    """Notification priority levels. Lower number = higher priority."""

    CRITICAL = 0  # Always delivered, bypasses quiet hours and rate limits
    HIGH = 1  # Delivered immediately during active hours
    MEDIUM = 2  # Batched, delivered every 15 min
    LOW = 3  # Batched, delivered in daily digest


# ═══════════════════════════════════════════════════════════════════════
# Notification Request
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class Notification:
    """A notification to be delivered."""

    event_type: str
    priority: Priority
    message: str
    reply_markup: dict[str, Any] | None = None
    dedup_key: str | None = None
    aggregation_group: str | None = None
    created_at: float = field(default_factory=time.time)
    delivered: bool = False


# ═══════════════════════════════════════════════════════════════════════
# Rate Limiter
# ═══════════════════════════════════════════════════════════════════════


class RateLimiter:
    """Token bucket rate limiter for Telegram API.

    Conservative limits to avoid hitting Telegram's rate limits:
    - 0.5 messages/second sustained
    - 10 messages/minute
    - 60 messages/hour
    - Burst: 3 critical messages
    """

    def __init__(
        self,
        rate_per_second: float = 0.5,
        max_per_minute: int = 10,
        max_per_hour: int = 60,
        burst_size: int = 3,
    ) -> None:
        self._rate = rate_per_second
        self._max_per_minute = max_per_minute
        self._max_per_hour = max_per_hour
        self._burst_size = burst_size

        self._tokens = 1.0
        self._burst_tokens = float(burst_size)
        self._last_refill = time.time()

        # Tracking
        self._sent_minute: list[float] = []
        self._sent_hour: list[float] = []

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(1.0, self._tokens + elapsed * self._rate)
        self._burst_tokens = min(
            float(self._burst_size),
            self._burst_tokens + elapsed * self._rate,
        )
        self._last_refill = now

        # Clean old timestamps
        cutoff_minute = now - 60
        cutoff_hour = now - 3600
        self._sent_minute = [t for t in self._sent_minute if t > cutoff_minute]
        self._sent_hour = [t for t in self._sent_hour if t > cutoff_hour]

    def can_send(self, priority: Priority) -> bool:
        """Check if we can send a message at this priority."""
        self._refill()

        # Check hard limits
        if len(self._sent_minute) >= self._max_per_minute:
            return False
        if len(self._sent_hour) >= self._max_per_hour:
            return False

        # CRITICAL uses burst tokens
        if priority == Priority.CRITICAL:
            return self._burst_tokens >= 1.0

        # Others use regular tokens
        return self._tokens >= 1.0

    def consume(self, priority: Priority) -> None:
        """Consume a token after sending."""
        now = time.time()
        self._sent_minute.append(now)
        self._sent_hour.append(now)

        if priority == Priority.CRITICAL:
            self._burst_tokens = max(0, self._burst_tokens - 1.0)
        else:
            self._tokens = max(0, self._tokens - 1.0)


# ═══════════════════════════════════════════════════════════════════════
# Dedup Tracker
# ═══════════════════════════════════════════════════════════════════════


class DedupTracker:
    """Tracks recently sent notifications to prevent duplicates.

    Each event type has a cooldown period. If the same dedup_key
    is seen within the cooldown, the notification is suppressed.
    """

    DEFAULT_COOLDOWNS: dict[str, int] = {
        "trade_executed": 0,  # Never dedup trade alerts
        "trade_opened": 0,
        "trade_closed": 0,
        "risk_warning": 300,  # 5 min cooldown
        "risk_alert": 300,
        "connection_error": 600,  # 10 min cooldown
        "connection_lost": 600,
        "market_event": 1800,  # 30 min cooldown
        "market_volatility": 1800,
        "system_health": 3600,  # 1 hour cooldown
        "system_error": 300,
    }

    def __init__(self, custom_cooldowns: dict[str, int] | None = None) -> None:
        self._cooldowns = {**self.DEFAULT_COOLDOWNS}
        if custom_cooldowns:
            self._cooldowns.update(custom_cooldowns)
        self._sent: dict[str, float] = {}  # dedup_key → last_sent_time

    def is_duplicate(self, event_type: str, dedup_key: str) -> bool:
        """Check if this notification is a duplicate within cooldown."""
        cooldown = self._cooldowns.get(event_type, 60)
        if cooldown == 0:
            return False

        key = f"{event_type}:{dedup_key}"
        last_sent = self._sent.get(key, 0)
        return (time.time() - last_sent) < cooldown

    def record(self, event_type: str, dedup_key: str) -> None:
        """Record that a notification was sent."""
        key = f"{event_type}:{dedup_key}"
        self._sent[key] = time.time()

    def cleanup(self, max_age: int = 7200) -> None:
        """Remove entries older than max_age seconds."""
        cutoff = time.time() - max_age
        self._sent = {k: v for k, v in self._sent.items() if v > cutoff}


# ═══════════════════════════════════════════════════════════════════════
# Aggregation Buffer
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class AggregationWindow:
    """A buffer for aggregating similar notifications."""

    group: str
    priority: Priority
    window_seconds: int
    notifications: list[Notification] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) >= self.window_seconds

    def add(self, notification: Notification) -> None:
        self.notifications.append(notification)

    def flush(self) -> list[Notification]:
        """Return all buffered notifications and clear."""
        items = self.notifications[:]
        self.notifications.clear()
        self.created_at = time.time()
        return items


class Aggregator:
    """Aggregates similar notifications within time windows.

    - CRITICAL: No aggregation (immediate delivery)
    - HIGH: 5 second window
    - MEDIUM: 15 minute window
    - LOW: 24 hour window (daily digest)
    """

    WINDOWS: dict[Priority, int] = {
        Priority.CRITICAL: 0,
        Priority.HIGH: 5,
        Priority.MEDIUM: 900,
        Priority.LOW: 86400,
    }

    def __init__(self) -> None:
        self._windows: dict[str, AggregationWindow] = {}

    def add(self, notification: Notification) -> list[Notification] | None:
        """Add notification to aggregation buffer.

        Returns:
            List of notifications to flush immediately, or None if buffered.
        """
        priority = notification.priority

        # CRITICAL: no aggregation
        if priority == Priority.CRITICAL:
            return [notification]

        # HIGH with no aggregation group: send immediately
        if priority == Priority.HIGH and not notification.aggregation_group:
            return [notification]

        group = notification.aggregation_group or notification.event_type
        window_secs = self.WINDOWS.get(priority, 900)

        if group not in self._windows:
            self._windows[group] = AggregationWindow(
                group=group,
                priority=priority,
                window_seconds=window_secs,
            )

        window = self._windows[group]
        window.add(notification)

        # Check if window is expired
        if window.is_expired:
            return window.flush()

        return None

    def flush_expired(self) -> list[Notification]:
        """Flush all expired windows. Called periodically."""
        to_flush = []
        for group, window in list(self._windows.items()):
            if window.is_expired:
                to_flush.extend(window.flush())
                del self._windows[group]
        return to_flush

    def flush_group(self, group: str) -> list[Notification]:
        """Flush a specific aggregation group."""
        window = self._windows.pop(group, None)
        return window.flush() if window else []


# ═══════════════════════════════════════════════════════════════════════
# Quiet Hours
# ═══════════════════════════════════════════════════════════════════════


class QuietHours:
    """Manages quiet hours for notification delivery.

    During quiet hours, only CRITICAL notifications are delivered.
    Other notifications are queued and delivered as a morning digest.
    """

    def __init__(
        self,
        start: str = "23:00",
        end: str = "07:00",
        timezone: str = "UTC",
    ) -> None:
        self._start = self._parse_time(start)
        self._end = self._parse_time(end)
        self._queue: list[Notification] = []

    @staticmethod
    def _parse_time(time_str: str) -> dt_time:
        """Parse HH:MM string to time object."""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))

    def is_quiet(self, now: datetime | None = None) -> bool:
        """Check if current time is within quiet hours."""
        if now is None:
            now = datetime.now(UTC)
        current = now.time()

        if self._start <= self._end:
            # Same day range (e.g., 09:00-17:00)
            return self._start <= current <= self._end
        else:
            # Overnight range (e.g., 23:00-07:00)
            return current >= self._start or current <= self._end

    def should_deliver(self, priority: Priority, now: datetime | None = None) -> bool:
        """Check if a notification should be delivered now."""
        # CRITICAL always delivered
        if priority == Priority.CRITICAL:
            return True
        # Check quiet hours
        return not self.is_quiet(now)

    def queue(self, notification: Notification) -> None:
        """Queue a notification for morning delivery."""
        self._queue.append(notification)

    def flush_queue(self) -> list[Notification]:
        """Flush queued notifications (called when quiet hours end)."""
        items = self._queue[:]
        self._queue.clear()
        return items

    def queue_size(self) -> int:
        return len(self._queue)


# ═══════════════════════════════════════════════════════════════════════
# Event → Notification Mapping
# ═══════════════════════════════════════════════════════════════════════


# Maps EventBus event types to notification configuration
EVENT_NOTIFICATION_MAP: dict[str, dict[str, Any]] = {
    # Trade events — always delivered, never deduped
    "tsar.trade.opened.v1": {
        "priority": Priority.HIGH,
        "template": "trade_opened",
        "dedup_enabled": False,
    },
    "tsar.trade.closed.v1": {
        "priority": Priority.HIGH,
        "template": "trade_closed",
        "dedup_enabled": False,
    },
    "tsar.trade.failed.v1": {
        "priority": Priority.CRITICAL,
        "template": "trade_failed",
        "dedup_enabled": False,
    },
    "tsar.signal.approved.v1": {
        "priority": Priority.HIGH,
        "template": "trade_executing",
        "dedup_enabled": False,
    },
    # Risk events — level-based priority
    "tsar.risk.alert.v1": {
        "priority": Priority.HIGH,
        "template": "risk_alert",
        "dedup_enabled": True,
        "dedup_key_field": "type",
        "cooldown": 300,
    },
    "tsar.risk.kill_switch.v1": {
        "priority": Priority.CRITICAL,
        "template": "kill_switch",
        "dedup_enabled": False,
    },
    "tsar.risk.drawdown.v1": {
        "priority": Priority.HIGH,
        "template": "drawdown_warning",
        "dedup_enabled": True,
        "dedup_key_field": "level",
        "cooldown": 300,
    },
    # System events
    "tsar.system.connection.v1": {
        "priority": Priority.HIGH,
        "template": "connection_change",
        "dedup_enabled": True,
        "dedup_key_field": "status",
        "cooldown": 600,
    },
    "tsar.system.health.v1": {
        "priority": Priority.LOW,
        "template": "system_health",
        "dedup_enabled": True,
        "dedup_key_field": "status",
        "cooldown": 3600,
    },
    "tsar.system.error.v1": {
        "priority": Priority.CRITICAL,
        "template": "system_error",
        "dedup_enabled": True,
        "dedup_key_field": "error_type",
        "cooldown": 300,
    },
    # Knowledge events
    "tsar.flywheel.cycle.v1": {
        "priority": Priority.LOW,
        "template": "flywheel_cycle",
        "dedup_enabled": False,
        "aggregation_group": "flywheel",
    },
    "tsar.regime.change.v1": {
        "priority": Priority.MEDIUM,
        "template": "regime_change",
        "dedup_enabled": True,
        "dedup_key_field": "regime",
        "cooldown": 1800,
    },
    "tsar.milestone.v1": {
        "priority": Priority.MEDIUM,
        "template": "milestone",
        "dedup_enabled": False,
    },
    # Market events
    "tsar.market.volatility.v1": {
        "priority": Priority.MEDIUM,
        "template": "volatility_spike",
        "dedup_enabled": True,
        "dedup_key_field": "symbol",
        "cooldown": 1800,
    },
}


# ═══════════════════════════════════════════════════════════════════════
# Message Formatters
# ═══════════════════════════════════════════════════════════════════════


class MessageFormatter:
    """Formats notification data into Telegram-ready HTML messages."""

    @staticmethod
    def format_trade_opened(data: dict[str, Any]) -> str:
        symbol = data.get("symbol", "Unknown")
        side = data.get("side", "Unknown")
        entry = data.get("entry_price", 0)
        sl = data.get("stop_loss", 0)
        tp = data.get("take_profit", 0)
        strategy = data.get("strategy", "unknown")

        side_emoji = "🟢" if side.upper() == "BUY" else "🔴"
        side_label = "LONG" if side.upper() == "BUY" else "SHORT"

        return (
            f"{side_emoji} <b>Trade Opened: {symbol} {side_label}</b>\n\n"
            f"💰 Entry: ${entry:,.2f}\n"
            f"🎯 Target: ${tp:,.2f}\n"
            f"🛑 Stop: ${sl:,.2f}\n"
            f"📊 Strategy: {strategy}\n"
        )

    @staticmethod
    def format_trade_closed(data: dict[str, Any]) -> str:
        symbol = data.get("symbol", "Unknown")
        side = data.get("side", "Unknown")
        pnl = data.get("pnl", 0)
        pnl_pct = data.get("pnl_pct", 0)
        exit_reason = data.get("exit_reason", "unknown")
        duration = data.get("duration_str", "N/A")

        is_win = pnl >= 0
        emoji = "✅" if is_win else "❌"
        result = (
            f"+${pnl:.2f} (+{pnl_pct:.1f}%)" if is_win else f"-${abs(pnl):.2f} ({pnl_pct:.1f}%)"
        )
        side_label = "LONG" if side.upper() == "BUY" else "SHORT"

        return (
            f"{emoji} <b>Trade Closed: {symbol} {side_label}</b>\n\n"
            f"💰 Result: {result}\n"
            f"⏱️ Duration: {duration}\n"
            f"📤 Exit: {exit_reason}\n"
        )

    @staticmethod
    def format_trade_failed(data: dict[str, Any]) -> str:
        symbol = data.get("symbol", "Unknown")
        error = data.get("error", "Unknown error")
        return (
            f"🚨 <b>Trade Execution FAILED</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Error: {error}\n\n"
            f"<i>Check system logs for details.</i>"
        )

    @staticmethod
    def format_risk_alert(data: dict[str, Any]) -> str:
        level = data.get("level", "MEDIUM")
        message = data.get("message", "Risk alert")
        metric = data.get("metric", "")
        threshold = data.get("threshold", "")

        emoji_map = {"LOW": "🟡", "MEDIUM": "🟠", "HIGH": "🔴", "CRITICAL": "🚨"}
        emoji = emoji_map.get(level, "⚠️")

        lines = [f"{emoji} <b>RISK [{level}]</b>", message]
        if metric and threshold:
            lines.append(f"Current: {metric} / Limit: {threshold}")
        return "\n".join(lines)

    @staticmethod
    def format_kill_switch(data: dict[str, Any]) -> str:
        reason = data.get("reason", "manual")
        positions_closed = data.get("positions_closed", 0)
        total_pnl = data.get("total_pnl", 0)
        return (
            f"🚨 <b>KILL SWITCH ACTIVATED</b>\n\n"
            f"Reason: {reason}\n"
            f"Positions closed: {positions_closed}\n"
            f"Realized P&L: ${total_pnl:.2f}\n\n"
            f"Use /start to resume trading."
        )

    @staticmethod
    def format_connection_change(data: dict[str, Any]) -> str:
        status = data.get("status", "unknown")
        exchange = data.get("exchange", "exchange")
        if status == "connected":
            return f"🔌 <b>Connected to {exchange}</b>"
        elif status == "disconnected":
            return f"🔴 <b>Disconnected from {exchange}</b>\nAttempting reconnection..."
        elif status == "reconnecting":
            return f"🔄 <b>Reconnecting to {exchange}</b>..."
        return f"🔌 Connection status: {status}"

    @staticmethod
    def format_system_error(data: dict[str, Any]) -> str:
        error_type = data.get("error_type", "Unknown")
        message = data.get("message", "")
        component = data.get("component", "system")
        return (
            f"🚨 <b>System Error</b>\n\n"
            f"Component: {component}\n"
            f"Error: {error_type}\n"
            f"Message: {message}\n\n"
            f"<i>Check system logs for details.</i>"
        )

    @staticmethod
    def format_flywheel_cycle(data: dict[str, Any]) -> str:
        run_id = data.get("run_id", 0)
        rules = data.get("rules_extracted", 0)
        validated = data.get("rules_validated", 0)
        mutations = data.get("mutations_proposed", 0)
        applied = data.get("mutations_applied", 0)

        return (
            f"🔄 <b>Flywheel Cycle #{run_id}</b>\n\n"
            f"📝 Rules extracted: {rules}\n"
            f"✅ Rules validated: {validated}\n"
            f"🧬 Mutations: {mutations} proposed, {applied} applied\n"
        )

    @staticmethod
    def format_regime_change(data: dict[str, Any]) -> str:
        regime = data.get("regime", "unknown")
        confidence = data.get("confidence", 0)
        emoji_map = {
            "STRONG_TREND_UP": "🟢📈",
            "STRONG_TREND_DOWN": "🔴📉",
            "RANGING": "↔️",
            "HIGH_VOLATILITY": "🌊",
            "UNCERTAIN": "❓",
        }
        emoji = emoji_map.get(regime, "🔄")
        return (
            f"{emoji} <b>Regime Change</b>\n\nNew regime: {regime}\nConfidence: {confidence:.0%}\n"
        )

    @staticmethod
    def format_milestone(data: dict[str, Any]) -> str:
        milestone = data.get("milestone", "Achievement")
        detail = data.get("detail", "")
        return f"🎉 <b>Milestone: {milestone}</b>\n{detail}"

    @staticmethod
    def format_volatility_spike(data: dict[str, Any]) -> str:
        symbol = data.get("symbol", "Unknown")
        current_vol = data.get("current_volatility", 0)
        avg_vol = data.get("avg_volatility", 0)
        ratio = current_vol / avg_vol if avg_vol > 0 else 0
        return (
            f"🌊 <b>High Volatility: {symbol}</b>\n\n"
            f"Current: {current_vol:.2f}\n"
            f"Average: {avg_vol:.2f}\n"
            f"Ratio: {ratio:.1f}x normal\n"
        )

    @staticmethod
    def format_aggregated(notifications: list[Notification]) -> str:
        """Format multiple notifications into a single aggregated message."""
        if len(notifications) == 1:
            return notifications[0].message

        # Group by event type
        groups: dict[str, list[Notification]] = defaultdict(list)
        for n in notifications:
            groups[n.event_type].append(n)

        lines = [f"📋 <b>Aggregated Alerts ({len(notifications)})</b>", ""]

        for event_type, items in groups.items():
            if len(items) == 1:
                lines.append(items[0].message)
            else:
                lines.append(f"<b>{event_type} ({len(items)}):</b>")
                for item in items[:5]:
                    # Extract first line of message
                    first_line = item.message.split("\n")[0]
                    lines.append(f"• {first_line}")
                if len(items) > 5:
                    lines.append(f"  ... and {len(items) - 5} more")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_morning_digest(notifications: list[Notification]) -> str:
        """Format queued quiet-hours notifications as a morning digest."""
        if not notifications:
            return ""

        lines = [
            "📋 <b>Morning Digest</b>",
            f"<i>{len(notifications)} notifications during quiet hours</i>",
            "",
        ]

        # Group by priority
        by_priority: dict[int, list[Notification]] = defaultdict(list)
        for n in notifications:
            by_priority[n.priority].append(n)

        priority_labels = {0: "🚨 Critical", 1: "🔴 High", 2: "🟠 Medium", 3: "🟡 Low"}

        for priority in sorted(by_priority.keys()):
            items = by_priority[priority]
            lines.append(f"<b>{priority_labels.get(priority, 'Other')} ({len(items)}):</b>")
            for item in items[:3]:
                first_line = item.message.split("\n")[0]
                lines.append(f"• {first_line}")
            if len(items) > 3:
                lines.append(f"  ... and {len(items) - 3} more")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_daily_summary(data: dict[str, Any]) -> str:
        """Format a daily trading summary."""
        date = data.get("date", datetime.now(UTC).strftime("%Y-%m-%d"))
        pnl = data.get("total_pnl", 0)
        pnl_pct = data.get("pnl_pct", 0)
        trades = data.get("trade_count", 0)
        wins = data.get("wins", 0)
        losses = data.get("losses", 0)
        win_rate = data.get("win_rate", 0)
        profit_factor = data.get("profit_factor", 0)
        max_dd = data.get("max_drawdown", 0)
        regime = data.get("regime", "unknown")
        best_trade = data.get("best_trade", {})
        worst_trade = data.get("worst_trade", {})
        lessons = data.get("lessons", [])
        flywheel = data.get("flywheel", {})

        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        pnl_str = (
            f"+${pnl:.2f} (+{pnl_pct:.1f}%)" if pnl >= 0 else f"-${abs(pnl):.2f} ({pnl_pct:.1f}%)"
        )

        lines = [
            f"📊 <b>Daily Summary — {date}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"{pnl_emoji} P&L: {pnl_str}",
            f"📈 Trades: {trades} ({wins}W / {losses}L)",
            f"🎯 Win Rate: {win_rate:.1%}",
        ]

        if profit_factor and profit_factor != float("inf"):
            lines.append(f"⚖️ Profit Factor: {profit_factor:.2f}")
        elif profit_factor == float("inf"):
            lines.append("⚖️ Profit Factor: ∞")

        lines.append(f"📉 Max Drawdown: {max_dd:.2f}%")
        lines.append(f"🌊 Regime: {regime}")

        if best_trade:
            lines.append(
                f"\n🏆 Best: {best_trade.get('symbol', '?')} {best_trade.get('side', '?')} +${best_trade.get('pnl', 0):.2f}"
            )
        if worst_trade:
            lines.append(
                f"💀 Worst: {worst_trade.get('symbol', '?')} {worst_trade.get('side', '?')} -${abs(worst_trade.get('pnl', 0)):.2f}"
            )

        if lessons:
            lines.append("\n📝 Lessons:")
            for lesson in lessons[:3]:
                lines.append(f"• {lesson[:100]}")

        if flywheel:
            lines.append(
                f"\n🔄 Flywheel: {flywheel.get('rules_extracted', 0)} rules, {flywheel.get('mutations_applied', 0)} mutations"
            )

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Notification Engine
# ═══════════════════════════════════════════════════════════════════════


class NotificationEngine:
    """Smart notification delivery with aggregation, dedup, and quiet hours.

    Central hub that receives events from the EventBus and delivers
    formatted notifications to Telegram via TsarBot.

    Usage::

        engine = NotificationEngine(bot)
        await engine.start()

        # Subscribe to events
        engine.subscribe_to_events(event_bus)

        # Or send notifications directly
        await engine.notify("trade_opened", Priority.HIGH, data)
    """

    def __init__(
        self,
        bot: Any,  # TsarBot instance
        quiet_start: str = "23:00",
        quiet_end: str = "07:00",
    ) -> None:
        self._bot = bot
        self._rate_limiter = RateLimiter()
        self._dedup = DedupTracker()
        self._aggregator = Aggregator()
        self._quiet = QuietHours(quiet_start, quiet_end)
        self._formatter = MessageFormatter()

        # Queue for rate-limited messages
        self._queue: list[Notification] = []
        self._queue_task: asyncio.Task[None] | None = None

        # Periodic flush task
        self._flush_task: asyncio.Task[None] | None = None

        # Stats
        self._stats = {
            "sent": 0,
            "deduped": 0,
            "queued": 0,
            "rate_limited": 0,
            "quiet_blocked": 0,
        }

    async def start(self) -> None:
        """Start the notification engine background tasks."""
        self._queue_task = asyncio.create_task(self._queue_processor())
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info("NotificationEngine started")

    async def stop(self) -> None:
        """Stop background tasks."""
        if self._queue_task:
            self._queue_task.cancel()
        if self._flush_task:
            self._flush_task.cancel()
        logger.info("NotificationEngine stopped. Stats: %s", self._stats)

    def subscribe_to_events(self, event_bus: Any) -> None:
        """Subscribe to all configured event types on the EventBus."""
        for event_type, config in EVENT_NOTIFICATION_MAP.items():
            handler = self._make_event_handler(event_type, config)
            event_bus.subscribe(event_type, handler)
            logger.debug("Subscribed to %s", event_type)

    def _make_event_handler(self, event_type: str, config: dict[str, Any]) -> Any:
        """Create an async handler for an event type."""

        async def handler(data: dict[str, Any]) -> None:
            await self._process_event(event_type, config, data)

        return handler

    async def _process_event(
        self,
        event_type: str,
        config: dict[str, Any],
        data: dict[str, Any],
    ) -> None:
        """Process an incoming event and decide delivery."""
        priority = config.get("priority", Priority.MEDIUM)
        template = config.get("template", event_type)

        # Dedup check
        if config.get("dedup_enabled", False):
            dedup_key_field = config.get("dedup_key_field", "type")
            dedup_key = str(data.get(dedup_key_field, ""))
            if self._dedup.is_duplicate(event_type, dedup_key):
                self._stats["deduped"] += 1
                logger.debug("Deduped %s (key=%s)", event_type, dedup_key)
                return
            self._dedup.record(event_type, dedup_key)

        # Format message
        formatter = getattr(self._formatter, f"format_{template}", None)
        message = formatter(data) if formatter else f"<b>{event_type}</b>\n{data}"

        # Create notification
        notification = Notification(
            event_type=event_type,
            priority=priority,
            message=message,
            aggregation_group=config.get("aggregation_group"),
        )

        await self._deliver(notification)

    async def notify(
        self,
        event_type: str,
        priority: Priority,
        message: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """Send a notification directly (not via EventBus)."""
        notification = Notification(
            event_type=event_type,
            priority=priority,
            message=message,
            reply_markup=reply_markup,
        )
        await self._deliver(notification)

    async def _deliver(self, notification: Notification) -> None:
        """Deliver a notification through the pipeline.

        Pipeline: quiet hours → rate limit → aggregation → send
        """
        # Quiet hours check
        if not self._quiet.should_deliver(notification.priority):
            self._quiet.queue(notification)
            self._stats["quiet_blocked"] += 1
            logger.debug("Queued %s (quiet hours)", notification.event_type)
            return

        # Rate limit check
        if not self._rate_limiter.can_send(notification.priority):
            self._queue.append(notification)
            self._stats["rate_limited"] += 1
            logger.debug("Rate limited %s", notification.event_type)
            return

        # Aggregation check
        to_send = self._aggregator.add(notification)
        if to_send is None:
            # Buffered for aggregation
            self._stats["queued"] += 1
            return

        # Send all notifications
        for n in to_send:
            await self._send(n)

    async def _send(self, notification: Notification) -> None:
        """Send a single notification via the Telegram bot."""
        try:
            await self._bot.send_message(
                notification.message,
                reply_markup=notification.reply_markup,
            )
            self._rate_limiter.consume(notification.priority)
            notification.delivered = True
            self._stats["sent"] += 1
            logger.debug("Sent %s notification", notification.event_type)
        except Exception:
            logger.exception("Failed to send notification: %s", notification.event_type)

    async def _queue_processor(self) -> None:
        """Background task to process queued notifications."""
        while True:
            try:
                await asyncio.sleep(1)

                if not self._queue:
                    continue

                # Try to send queued messages
                still_queued = []
                for notification in self._queue:
                    if self._rate_limiter.can_send(notification.priority):
                        await self._send(notification)
                    else:
                        still_queued.append(notification)
                self._queue = still_queued

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Queue processor error")

    async def _periodic_flush(self) -> None:
        """Periodically flush expired aggregation windows and quiet hours."""
        while True:
            try:
                await asyncio.sleep(30)

                # Flush expired aggregation windows
                to_send = self._aggregator.flush_expired()
                for notification in to_send:
                    await self._send(notification)

                # Check if quiet hours ended → flush morning digest
                if not self._quiet.is_quiet() and self._quiet.queue_size() > 0:
                    queued = self._quiet.flush_queue()
                    if queued:
                        digest = self._formatter.format_morning_digest(queued)
                        await self._send(
                            Notification(
                                event_type="morning_digest",
                                priority=Priority.HIGH,
                                message=digest,
                            )
                        )

                # Cleanup dedup tracker
                self._dedup.cleanup()

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Periodic flush error")

    def get_stats(self) -> dict[str, int]:
        """Get notification engine statistics."""
        return {**self._stats}


# ═══════════════════════════════════════════════════════════════════════
# Scheduled Report Generator
# ═══════════════════════════════════════════════════════════════════════


class ReportScheduler:
    """Generates and delivers scheduled reports (daily/weekly/monthly).

    Integrates with TradeMemory, KnowledgeTools, and FlywheelHealth
    to produce comprehensive reports.
    """

    def __init__(self, notification_engine: NotificationEngine) -> None:
        self._engine = notification_engine
        self._formatter = MessageFormatter()
        self._running = False

    async def start(self) -> None:
        """Start the report scheduler."""
        self._running = True
        asyncio.create_task(self._daily_report_loop())
        asyncio.create_task(self._weekly_report_loop())
        logger.info("ReportScheduler started")

    async def stop(self) -> None:
        self._running = False

    async def _daily_report_loop(self) -> None:
        """Generate daily summary at 00:00 UTC."""
        while self._running:
            try:
                # Wait until midnight UTC
                now = datetime.now(UTC)
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if now >= tomorrow:
                    from datetime import timedelta

                    tomorrow += timedelta(days=1)
                wait_seconds = (tomorrow - now).total_seconds()
                await asyncio.sleep(wait_seconds)

                if not self._running:
                    return

                await self._generate_daily_report()

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Daily report error")
                await asyncio.sleep(60)

    async def _generate_daily_report(self) -> None:
        """Generate and send the daily summary report."""
        try:
            from src.knowledge.trade_memory import TradeMemory
            from src.metrics.flywheel import FlywheelHealth
            from src.tools.knowledge import KnowledgeTools

            db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
            trade_mem = TradeMemory(db_path)
            stats = trade_mem.get_trade_stats()
            kt = KnowledgeTools(db_path)

            # Get today's trades
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            recent_trades = trade_mem.get_recent_trades(days=1)

            # Find best/worst
            best = max(recent_trades, key=lambda t: t.get("pnl", 0)) if recent_trades else {}
            worst = min(recent_trades, key=lambda t: t.get("pnl", 0)) if recent_trades else {}

            # Recent lessons
            lessons = kt.get_recent_lessons(days=1, limit=3)
            lesson_texts = [l.get("content", "") for l in lessons]

            # Flywheel
            fh = FlywheelHealth()
            flywheel_result = fh.compute({})

            report_data = {
                "date": today,
                "total_pnl": stats.get("total_pnl", 0),
                "pnl_pct": stats.get("total_pnl", 0) / 10000 * 100,  # Assuming 10k base
                "trade_count": stats.get("trade_count", 0),
                "wins": int(stats.get("trade_count", 0) * stats.get("win_rate", 0)),
                "losses": int(stats.get("trade_count", 0) * (1 - stats.get("win_rate", 0))),
                "win_rate": stats.get("win_rate", 0),
                "profit_factor": stats.get("profit_factor", 0),
                "max_drawdown": stats.get("max_drawdown", 0),
                "regime": "unknown",
                "best_trade": best,
                "worst_trade": worst,
                "lessons": lesson_texts,
                "flywheel": flywheel_result,
            }

            # Get regime
            try:
                regime = kt.get_global_regime()
                if regime:
                    report_data["regime"] = regime.get("regime", "unknown")
            except Exception:
                pass

            message = self._formatter.format_daily_summary(report_data)
            await self._engine.notify(
                "daily_report",
                Priority.HIGH,
                message,
            )

            kt.close()

        except Exception:
            logger.exception("Failed to generate daily report")

    async def _weekly_report_loop(self) -> None:
        """Generate weekly report on Sundays at 00:00 UTC."""
        while self._running:
            try:
                now = datetime.now(UTC)
                # Wait until next Sunday
                days_until_sunday = (6 - now.weekday()) % 7
                if days_until_sunday == 0 and now.hour >= 0:
                    days_until_sunday = 7
                from datetime import timedelta

                next_sunday = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                    days=days_until_sunday
                )
                wait_seconds = (next_sunday - now).total_seconds()
                await asyncio.sleep(wait_seconds)

                if not self._running:
                    return

                # Weekly report uses same format as daily but with 7-day data
                await self._generate_daily_report()  # Reuse for now

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Weekly report error")
                await asyncio.sleep(60)
