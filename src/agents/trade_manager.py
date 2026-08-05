"""
Trade Manager — Active position management agent.

Role: TRADE_MANAGE
No LLM — pure deterministic trade management logic.

Responsibilities:
  1. Monitor all open positions
  2. Execute trailing stop logic (multi-stage)
  3. Execute partial exit schedule
  4. Monitor regime changes → trigger exits
  5. Monitor news events → trigger exits
  6. Monitor time stops → trigger exits
  7. Move stops to break-even when 1:1 R:R reached
  8. Log all trade management actions

Subscribes to: trades, regime, news_events
Publishes to: trade_actions

Pipeline position:
  Signal Scout → Risk Guardian → Execution Sniper → TRADE MANAGER
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.agents.base import BaseAgent

if TYPE_CHECKING:
    from src.comms.events import CloudEvent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════


class TrailingStage(Enum):
    """Trailing stop stages."""

    INITIAL = "initial"  # ATR-based initial stop
    BREAKEVEN = "breakeven"  # Stop moved to break-even
    TRAILING = "trailing"  # Active trailing stop
    TIGHT_TRAIL = "tight_trail"  # Tightened trail after 2:1 R:R


class ExitReason(Enum):
    """Reasons for exiting a position."""

    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    TIME_STOP = "time_stop"
    REGIME_CHANGE = "regime_change"
    NEWS_EVENT = "news_event"
    STALE_TRADE = "stale_trade"
    MANUAL = "manual"
    PARTIAL_EXIT = "partial_exit"


@dataclass
class ManagedPosition:
    """A position being actively managed by the Trade Manager."""

    position_id: str
    symbol: str
    side: str  # "buy" or "sell"
    entry_price: float
    quantity: float
    remaining_quantity: float
    stop_loss: float
    take_profit: float
    atr: float
    entry_time: datetime
    strategy: str

    # Trailing stop state
    trailing_stage: TrailingStage = TrailingStage.INITIAL
    highest_price: float = 0.0  # For buy positions
    lowest_price: float = float("inf")  # For sell positions
    trailing_stop: float = 0.0

    # Partial exit tracking
    partial_exits_taken: int = 0
    total_partial_exits: int = 3  # Default: 40%, 30%, 30%
    partial_exit_levels: list[float] = field(default_factory=list)

    # Break-even tracking
    breakeven_triggered: bool = False

    # Time tracking
    last_price_move_time: datetime | None = None
    stale_alert_sent: bool = False

    # Risk-reward tracking
    risk_per_unit: float = 0.0
    realized_rr: float = 0.0

    def __post_init__(self):
        if self.risk_per_unit == 0:
            self.risk_per_unit = abs(self.entry_price - self.stop_loss)
        if self.highest_price == 0:
            self.highest_price = self.entry_price
        if self.lowest_price == float("inf"):
            self.lowest_price = self.entry_price
        if not self.partial_exit_levels:
            # Default partial exit at 1:1, 2:1, 3:1 R:R
            if self.side == "buy":
                self.partial_exit_levels = [
                    self.entry_price + self.risk_per_unit * 1.0,
                    self.entry_price + self.risk_per_unit * 2.0,
                    self.entry_price + self.risk_per_unit * 3.0,
                ]
            else:
                self.partial_exit_levels = [
                    self.entry_price - self.risk_per_unit * 1.0,
                    self.entry_price - self.risk_per_unit * 2.0,
                    self.entry_price - self.risk_per_unit * 3.0,
                ]


@dataclass
class TradeAction:
    """An action to take on a position."""

    position_id: str
    action: str  # "partial_exit", "update_stop", "close", "alert"
    quantity: float = 0.0
    new_stop: float = 0.0
    reason: ExitReason = ExitReason.MANUAL
    details: str = ""
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# SESSION TIMING
# ═══════════════════════════════════════════════════════════════════════


class SessionTiming:
    """Session-aware trading gates.

    Determines optimal trading windows based on time of day
    and day of week. Crypto markets are 24/7 but liquidity
    varies dramatically by session.
    """

    # Session windows (UTC hours)
    SESSIONS = {
        "asian": (0, 7),  # Low liquidity, wide spreads
        "london": (7, 16),  # High liquidity, institutional
        "new_york": (13, 22),  # Highest volume
        "overlap": (13, 16),  # London-NY overlap (BEST)
        "dead_zone": (22, 24),  # Session transition
    }

    # Session quality scores (0-1)
    SESSION_QUALITY = {
        "asian": 0.3,
        "london": 0.7,
        "new_york": 0.8,
        "overlap": 1.0,
        "dead_zone": 0.2,
    }

    # Day-of-week quality (0-1, Monday=0)
    DAY_QUALITY = {
        0: 0.6,  # Monday — choppy
        1: 1.0,  # Tuesday — best
        2: 0.9,  # Wednesday — good
        3: 0.9,  # Thursday — good
        4: 0.5,  # Friday — unpredictable
        5: 0.3,  # Saturday — low volume
        6: 0.3,  # Sunday — low volume
    }

    @classmethod
    def get_current_session(cls) -> str:
        """Get the current trading session name."""
        utc_hour = datetime.now(UTC).hour

        if 13 <= utc_hour < 16:
            return "overlap"
        elif 7 <= utc_hour < 13:
            return "london"
        elif 13 <= utc_hour < 22:
            return "new_york"
        elif 0 <= utc_hour < 7:
            return "asian"
        else:
            return "dead_zone"

    @classmethod
    def get_session_quality(cls) -> float:
        """Get quality score for current session (0-1)."""
        session = cls.get_current_session()
        day_quality = cls.DAY_QUALITY.get(datetime.now(UTC).weekday(), 0.5)
        session_quality = cls.SESSION_QUALITY.get(session, 0.5)
        return round(session_quality * day_quality, 2)

    @classmethod
    def is_entry_allowed(cls) -> tuple[bool, str]:
        """Check if entry is allowed in current session.

        Returns:
            Tuple of (allowed, reason).
        """
        session = cls.get_current_session()
        quality = cls.get_session_quality()

        if session == "dead_zone":
            return False, "Dead zone session (22:00-00:00 UTC) — low conviction"
        if session == "asian":
            return False, "Asian session (00:00-07:00 UTC) — low liquidity, wide spreads"
        if quality < 0.4:
            return False, f"Low session quality ({quality:.2f}) — poor day/time combination"

        return True, f"Session: {session}, quality: {quality:.2f}"

    @classmethod
    def should_close_for_weekend(cls) -> tuple[bool, str]:
        """Check if positions should be closed for weekend risk.

        Returns:
            Tuple of (should_close, reason).
        """
        now = datetime.now(UTC)
        weekday = now.weekday()
        utc_hour = now.hour

        # Friday after 20:00 UTC — close for weekend
        if weekday == 4 and utc_hour >= 20:
            return True, "Friday 20:00+ UTC — weekend risk, closing positions"

        # Friday after 16:00 UTC — no new entries
        if weekday == 4 and utc_hour >= 16:
            return True, "Friday 16:00+ UTC — no new entries, consider closing"

        return False, ""


# ═══════════════════════════════════════════════════════════════════════
# NEWS PROXIMITY
# ═══════════════════════════════════════════════════════════════════════


class NewsProximity:
    """News event proximity gates for trade management.

    Integrates with MarketCalendar to check upcoming events
    and enforce trading restrictions around high-impact news.
    """

    # Blackout windows before events (minutes)
    BLACKOUT_WINDOWS = {
        "critical": 120,  # 2 hours before critical events
        "high": 60,  # 1 hour before high-impact events
        "medium": 30,  # 30 minutes before medium events
        "low": 0,  # No blackout for low-impact events
    }

    # Post-event cooldown (minutes)
    POST_EVENT_COOLDOWN = {
        "critical": 15,
        "high": 10,
        "medium": 5,
        "low": 0,
    }

    @classmethod
    def check_news_blackout(
        cls,
        calendar_snapshot: Any | None,
    ) -> tuple[bool, str, float]:
        """Check if trading should be restricted due to upcoming news.

        Args:
            calendar_snapshot: CalendarSnapshot from MarketCalendar.

        Returns:
            Tuple of (is_blocked, reason, risk_multiplier).
        """
        if calendar_snapshot is None:
            return False, "No calendar data available", 1.0

        now = datetime.now(UTC)

        for event in calendar_snapshot.high_impact_events:
            if not event.date:
                continue

            try:
                event_dt = datetime.fromisoformat(event.date)
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue

            minutes_until = (event_dt - now).total_seconds() / 60

            # Skip past events
            if minutes_until < 0:
                continue

            impact = event.impact.lower()
            blackout_minutes = cls.BLACKOUT_WINDOWS.get(impact, 0)

            if minutes_until <= blackout_minutes:
                reason = (
                    f"Blackout: {event.event} ({impact}) in {minutes_until:.0f}min — no new entries"
                )
                risk_mult = 0.3 if impact == "critical" else 0.5
                return True, reason, risk_mult

        return False, "", 1.0

    @classmethod
    def should_exit_for_news(
        cls,
        calendar_snapshot: Any | None,
        position_rr: float,
    ) -> tuple[bool, str]:
        """Check if position should be closed before upcoming news.

        Args:
            calendar_snapshot: CalendarSnapshot from MarketCalendar.
            position_rr: Current R:R of the position.

        Returns:
            Tuple of (should_exit, reason).
        """
        if calendar_snapshot is None:
            return False, ""

        now = datetime.now(UTC)

        for event in calendar_snapshot.high_impact_events:
            if not event.date:
                continue

            try:
                event_dt = datetime.fromisoformat(event.date)
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue

            minutes_until = (event_dt - now).total_seconds() / 60

            if minutes_until < 0:
                continue

            impact = event.impact.lower()

            # Critical event within 30min: close if < 1:1 R:R
            if impact == "critical" and minutes_until <= 30 and position_rr < 1.0:
                return True, (
                    f"Critical event ({event.event}) in {minutes_until:.0f}min — "
                    f"closing low-R:R position"
                )

            # High event within 15min: move to break-even (handled by stop logic)
            # Don't close, just tighten

        return False, ""


# ═══════════════════════════════════════════════════════════════════════
# TRADE MANAGER AGENT
# ═══════════════════════════════════════════════════════════════════════


class TradeManager(BaseAgent):
    """Active position management — trailing stops, partial exits, time stops.

    The Trade Manager sits at the end of the trading pipeline and
    actively manages all open positions. It does NOT make entry
    decisions — only manages existing positions.

    Management actions:
    1. Trailing stop updates (multi-stage)
    2. Partial exits at predetermined levels
    3. Break-even stop triggers
    4. Time-based exits (stale trades)
    5. Regime-change exits
    6. News-event exits
    7. Weekend risk management
    """

    AGENT_NAME = "trade_manager"
    ROLE = "TRADE_MANAGE"

    PUBLISH_STREAM = "trade_actions"
    SUBSCRIBE_STREAMS = ["trades", "regime", "news_events"]

    # Default configuration
    DEFAULT_CONFIG = {
        # Trailing stop
        "trailing_enabled": True,
        "trailing_atr_multiplier": 1.0,
        "tight_trailing_atr_multiplier": 0.75,
        "trailing_trigger_rr": 1.5,  # Start trailing after 1.5:1 R:R
        "tight_trail_trigger_rr": 2.0,  # Tighten trail after 2:1 R:R
        # Break-even
        "breakeven_trigger_rr": 1.0,  # Move to BE after 1:1 R:R
        "breakeven_buffer_pct": 0.001,  # 0.1% above entry for fees
        # Partial exits
        "partial_exits_enabled": True,
        "partial_exit_schedule": [0.4, 0.3, 0.3],  # 40%, 30%, 30%
        "partial_exit_rr_levels": [1.0, 2.0, 3.0],
        # Time stops
        "time_stop_enabled": True,
        "time_stop_hours": {
            "mean_reversion": 4,
            "momentum": 24,
            "default": 8,
        },
        "stale_trade_hours": 4,
        "stale_trade_threshold_pct": 0.5,
        # Weekend management
        "weekend_close_enabled": True,
        "weekend_close_hour_utc": 20,  # Friday 20:00 UTC
        # Regime exits
        "regime_exit_enabled": True,
    }

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)

        # Merge config
        tm_config = config.get("trade_manager", {})
        self._config = {**self.DEFAULT_CONFIG, **tm_config}

        # Managed positions
        self._positions: dict[str, ManagedPosition] = {}

        # Current regime
        self._current_regime: str = "unknown"

        # Calendar reference (lazy)
        self._calendar = None

        # Execution engine reference (lazy)
        self._exec_engine = None

        # Cycle counter for periodic checks
        self._cycle_count = 0

    async def on_initialize(self) -> None:
        """Initialize execution engine and calendar."""
        from src.interfaces import get_execution_engine
        from src.tools.market_calendar import MarketCalendar

        self._exec_engine = get_execution_engine()
        self._calendar = MarketCalendar(config=self.config.get("market_calendar", {}))

        logger.info(
            "TradeManager initialized: trailing=%s, partial_exits=%s, "
            "time_stops=%s, regime_exits=%s",
            self._config["trailing_enabled"],
            self._config["partial_exits_enabled"],
            self._config["time_stop_enabled"],
            self._config["regime_exit_enabled"],
        )

    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        """Handle incoming events.

        - trades: New position to manage
        - regime: Regime change → check exits
        - news_events: Breaking news → check exits
        """
        if stream == "trades" and event.type == "tsar.trade.executed.v1":
            await self._register_position(event)

        elif stream == "regime" and event.type == "tsar.regime.changed.v1":
            new_regime = event.data.get("regime", "unknown")
            await self._handle_regime_change(new_regime)

        elif stream == "news_events" and event.type == "tsar.news.breaking.v1":
            await self._handle_breaking_news(event)

    async def run_cycle(self) -> None:
        """Main management cycle — check all positions.

        Runs every 30 seconds (configurable) and:
        1. Fetches current prices for all positions
        2. Checks trailing stop triggers
        3. Checks partial exit triggers
        4. Checks time stops
        5. Checks session/weekend rules
        6. Executes any required actions
        """
        self._cycle_count += 1

        if not self._positions:
            return

        # Get current prices
        prices = await self._fetch_current_prices()

        # Check each position
        actions: list[TradeAction] = []

        for _pos_id, pos in self._positions.items():
            current_price = prices.get(pos.symbol)
            if current_price is None:
                continue

            # Calculate current R:R
            current_rr = self._calculate_current_rr(pos, current_price)

            # Check each management rule
            pos_actions = []

            # 1. Trailing stop
            if self._config["trailing_enabled"]:
                trail_action = self._check_trailing_stop(pos, current_price, current_rr)
                if trail_action:
                    pos_actions.append(trail_action)

            # 2. Partial exits
            if self._config["partial_exits_enabled"]:
                partial_action = self._check_partial_exit(pos, current_price, current_rr)
                if partial_action:
                    pos_actions.append(partial_action)

            # 3. Time stop
            if self._config["time_stop_enabled"]:
                time_action = self._check_time_stop(pos, current_price)
                if time_action:
                    pos_actions.append(time_action)

            # 4. Stale trade detection
            stale_action = self._check_stale_trade(pos, current_price)
            if stale_action:
                pos_actions.append(stale_action)

            # 5. Weekend management
            if self._config["weekend_close_enabled"]:
                weekend_action = self._check_weekend_close(pos)
                if weekend_action:
                    pos_actions.append(weekend_action)

            # 6. Break-even trigger
            be_action = self._check_breakeven(pos, current_price, current_rr)
            if be_action:
                pos_actions.append(be_action)

            actions.extend(pos_actions)

        # Execute all actions
        for action in actions:
            await self._execute_action(action)

        # Update position tracking
        self._update_position_tracking(prices)

    # ── Position Registration ──────────────────────────────────────

    async def _register_position(self, event: CloudEvent) -> None:
        """Register a new position for active management."""
        data = event.data

        position_id = data.get("signal_id", data.get("entry_order_id", "unknown"))
        symbol = data["symbol"]
        side = data["side"]
        entry_price = data["entry_price"]
        quantity = data["quantity"]
        stop_loss = data["stop_loss"]
        take_profit = data["take_profit"]

        # Get ATR from metadata if available
        atr = data.get("metadata", {}).get("atr", abs(entry_price - stop_loss) / 1.5)

        position = ManagedPosition(
            position_id=position_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            remaining_quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr=atr,
            entry_time=datetime.now(UTC),
            strategy=data.get("strategy", "unknown"),
        )

        self._positions[position_id] = position

        logger.info(
            "📋 Registered position for management: %s %s %s entry=%.2f sl=%.2f tp=%.2f qty=%.6f",
            position_id,
            symbol,
            side,
            entry_price,
            stop_loss,
            take_profit,
            quantity,
        )

    # ── Trailing Stop Logic ────────────────────────────────────────

    def _check_trailing_stop(
        self,
        pos: ManagedPosition,
        current_price: float,
        current_rr: float,
    ) -> TradeAction | None:
        """Check and update trailing stop.

        Stages:
        1. INITIAL: ATR-based stop (set at entry)
        2. BREAKEVEN: Move to break-even after 1:1 R:R
        3. TRAILING: Trail at 1.0 × ATR after 1.5:1 R:R
        4. TIGHT_TRAIL: Trail at 0.75 × ATR after 2:1 R:R
        """
        if pos.side == "buy":
            # Update highest price seen
            if current_price > pos.highest_price:
                pos.highest_price = current_price
        else:
            # Update lowest price seen
            if current_price < pos.lowest_price:
                pos.lowest_price = current_price

        # Determine trailing stage based on R:R
        if current_rr >= self._config["tight_trail_trigger_rr"]:
            new_stage = TrailingStage.TIGHT_TRAIL
            atr_mult = self._config["tight_trailing_atr_multiplier"]
        elif current_rr >= self._config["trailing_trigger_rr"]:
            new_stage = TrailingStage.TRAILING
            atr_mult = self._config["trailing_atr_multiplier"]
        elif current_rr >= self._config["breakeven_trigger_rr"]:
            new_stage = TrailingStage.BREAKEVEN
            atr_mult = 0  # Break-even, no ATR trail
        else:
            return None  # Not yet profitable enough to trail

        # Calculate new trailing stop
        if pos.side == "buy":
            if new_stage == TrailingStage.BREAKEVEN:
                new_stop = pos.entry_price * (1 + self._config["breakeven_buffer_pct"])
            else:
                trail_stop = pos.highest_price - (pos.atr * atr_mult)
                new_stop = max(trail_stop, pos.entry_price)  # Never below entry
        else:
            if new_stage == TrailingStage.BREAKEVEN:
                new_stop = pos.entry_price * (1 - self._config["breakeven_buffer_pct"])
            else:
                trail_stop = pos.lowest_price + (pos.atr * atr_mult)
                new_stop = min(trail_stop, pos.entry_price)  # Never above entry

        # Only update if new stop is better (tighter) than current
        if pos.side == "buy":
            if new_stop <= pos.stop_loss:
                return None  # Current stop is already tighter
        else:
            if new_stop >= pos.stop_loss:
                return None

        # Check if stage changed (log transition)
        if new_stage != pos.trailing_stage:
            logger.info(
                "📊 %s: Trailing stage %s → %s (RR=%.2f, new_stop=%.2f)",
                pos.position_id,
                pos.trailing_stage.value,
                new_stage.value,
                current_rr,
                new_stop,
            )
            pos.trailing_stage = new_stage

        return TradeAction(
            position_id=pos.position_id,
            action="update_stop",
            new_stop=new_stop,
            reason=ExitReason.TRAILING_STOP,
            details=f"Trailing stage={new_stage.value}, RR={current_rr:.2f}",
            timestamp=datetime.now(UTC),
        )

    # ── Partial Exit Logic ─────────────────────────────────────────

    def _check_partial_exit(
        self,
        pos: ManagedPosition,
        current_price: float,
        current_rr: float,
    ) -> TradeAction | None:
        """Check if a partial exit should be taken.

        Schedule: 40% at 1:1, 30% at 2:1, 30% at 3:1 R:R
        """
        if pos.partial_exits_taken >= len(self._config["partial_exit_rr_levels"]):
            return None  # All partial exits taken

        # Check next exit level
        next_level_idx = pos.partial_exits_taken
        next_rr_level = self._config["partial_exit_rr_levels"][next_level_idx]
        exit_pct = self._config["partial_exit_schedule"][next_level_idx]

        if current_rr < next_rr_level:
            return None  # Not yet at exit level

        # Calculate exit quantity
        exit_quantity = pos.quantity * exit_pct
        # Don't exit more than remaining
        exit_quantity = min(
            exit_quantity,
            pos.remaining_quantity
            * exit_pct
            / (1 - sum(self._config["partial_exit_schedule"][: pos.partial_exits_taken])),
        )

        if exit_quantity <= 0:
            return None

        logger.info(
            "💰 %s: Partial exit #%d — %.1f%% at RR=%.2f (target=%.1f)",
            pos.position_id,
            pos.partial_exits_taken + 1,
            exit_pct * 100,
            current_rr,
            next_rr_level,
        )

        return TradeAction(
            position_id=pos.position_id,
            action="partial_exit",
            quantity=exit_quantity,
            reason=ExitReason.PARTIAL_EXIT,
            details=f"Partial exit #{pos.partial_exits_taken + 1}: {exit_pct * 100:.0f}% at {current_rr:.1f}R",
            timestamp=datetime.now(UTC),
        )

    # ── Break-Even Logic ───────────────────────────────────────────

    def _check_breakeven(
        self,
        pos: ManagedPosition,
        current_price: float,
        current_rr: float,
    ) -> TradeAction | None:
        """Check if stop should be moved to break-even."""
        if pos.breakeven_triggered:
            return None

        if current_rr < self._config["breakeven_trigger_rr"]:
            return None

        # Already handled by trailing stop logic if trailing is enabled
        if self._config["trailing_enabled"]:
            return None

        # Move to break-even
        if pos.side == "buy":
            new_stop = pos.entry_price * (1 + self._config["breakeven_buffer_pct"])
            if new_stop <= pos.stop_loss:
                return None
        else:
            new_stop = pos.entry_price * (1 - self._config["breakeven_buffer_pct"])
            if new_stop >= pos.stop_loss:
                return None

        pos.breakeven_triggered = True

        logger.info(
            "🔒 %s: Break-even stop triggered at RR=%.2f",
            pos.position_id,
            current_rr,
        )

        return TradeAction(
            position_id=pos.position_id,
            action="update_stop",
            new_stop=new_stop,
            reason=ExitReason.STOP_LOSS,
            details=f"Break-even triggered at {current_rr:.2f}R",
            timestamp=datetime.now(UTC),
        )

    # ── Time Stop Logic ────────────────────────────────────────────

    def _check_time_stop(
        self,
        pos: ManagedPosition,
        current_price: float,
    ) -> TradeAction | None:
        """Check if position should be closed due to time."""
        now = datetime.now(UTC)
        hours_held = (now - pos.entry_time).total_seconds() / 3600

        # Strategy-specific time stop
        strategy_hours = self._config["time_stop_hours"].get(
            pos.strategy,
            self._config["time_stop_hours"]["default"],
        )

        if hours_held >= strategy_hours:
            # Check if trade is profitable — don't time-stop winners
            if pos.side == "buy":
                pnl_pct = (current_price - pos.entry_price) / pos.entry_price
            else:
                pnl_pct = (pos.entry_price - current_price) / pos.entry_price

            if pnl_pct > 0.005:  # > 0.5% profit — let it run
                return None

            logger.info(
                "⏰ %s: Time stop after %.1fh (strategy=%s, pnl=%.2f%%)",
                pos.position_id,
                hours_held,
                pos.strategy,
                pnl_pct * 100,
            )

            return TradeAction(
                position_id=pos.position_id,
                action="close",
                reason=ExitReason.TIME_STOP,
                details=f"Time stop: {hours_held:.1f}h held, strategy={pos.strategy}",
                timestamp=now,
            )

        return None

    # ── Stale Trade Detection ──────────────────────────────────────

    def _check_stale_trade(
        self,
        pos: ManagedPosition,
        current_price: float,
    ) -> TradeAction | None:
        """Detect and close stale trades that aren't moving."""
        now = datetime.now(UTC)
        hours_held = (now - pos.entry_time).total_seconds() / 3600

        if hours_held < self._config["stale_trade_hours"]:
            return None

        # Check price movement
        if pos.side == "buy":
            move_pct = abs(current_price - pos.entry_price) / pos.entry_price
        else:
            move_pct = abs(pos.entry_price - current_price) / pos.entry_price

        if move_pct < self._config["stale_trade_threshold_pct"] / 100:
            logger.info(
                "💤 %s: Stale trade — %.1fh held, only %.2f%% move",
                pos.position_id,
                hours_held,
                move_pct * 100,
            )

            return TradeAction(
                position_id=pos.position_id,
                action="close",
                reason=ExitReason.STALE_TRADE,
                details=f"Stale: {hours_held:.1f}h, {move_pct * 100:.2f}% move",
                timestamp=now,
            )

        return None

    # ── Weekend Management ─────────────────────────────────────────

    def _check_weekend_close(self, pos: ManagedPosition) -> TradeAction | None:
        """Check if position should be closed for weekend risk."""
        should_close, reason = SessionTiming.should_close_for_weekend()

        if should_close:
            logger.info("📅 %s: Weekend close — %s", pos.position_id, reason)
            return TradeAction(
                position_id=pos.position_id,
                action="close",
                reason=ExitReason.TIME_STOP,
                details=reason,
                timestamp=datetime.now(UTC),
            )

        return None

    # ── Regime Change Handler ──────────────────────────────────────

    async def _handle_regime_change(self, new_regime: str) -> None:
        """Handle regime change — check all positions for exits."""
        if not self._config["regime_exit_enabled"]:
            return

        old_regime = self._current_regime
        self._current_regime = new_regime

        logger.info(
            "🔄 Regime change: %s → %s — checking all positions",
            old_regime,
            new_regime,
        )

        actions = []

        for _pos_id, pos in self._positions.items():
            action = self._evaluate_regime_exit(pos, old_regime, new_regime)
            if action:
                actions.append(action)

        for action in actions:
            await self._execute_action(action)

    def _evaluate_regime_exit(
        self,
        pos: ManagedPosition,
        old_regime: str,
        new_regime: str,
    ) -> TradeAction | None:
        """Evaluate if a position should be closed due to regime change."""

        # Trending → Ranging: Close momentum positions
        if old_regime == "trending" and new_regime == "ranging":
            if pos.strategy == "momentum":
                return TradeAction(
                    position_id=pos.position_id,
                    action="close",
                    reason=ExitReason.REGIME_CHANGE,
                    details=f"Regime: {old_regime}→{new_regime}, closing momentum position",
                    timestamp=datetime.now(UTC),
                )

        # Ranging → Trending: Close mean reversion positions
        if old_regime == "ranging" and new_regime == "trending":
            if pos.strategy == "mean_reversion":
                return TradeAction(
                    position_id=pos.position_id,
                    action="close",
                    reason=ExitReason.REGIME_CHANGE,
                    details=f"Regime: {old_regime}→{new_regime}, closing mean reversion position",
                    timestamp=datetime.now(UTC),
                )

        # Any → Crisis: Close ALL positions
        if new_regime == "crisis":
            return TradeAction(
                position_id=pos.position_id,
                action="close",
                reason=ExitReason.REGIME_CHANGE,
                details="Regime: crisis — closing all positions",
                timestamp=datetime.now(UTC),
            )

        # Any → High Volatility: Tighten stops
        if new_regime == "high_volatility":
            if pos.side == "buy":
                new_stop = pos.entry_price + (pos.atr * 0.75)
            else:
                new_stop = pos.entry_price - (pos.atr * 0.75)

            return TradeAction(
                position_id=pos.position_id,
                action="update_stop",
                new_stop=new_stop,
                reason=ExitReason.REGIME_CHANGE,
                details="Regime: high_volatility — tightening stop",
                timestamp=datetime.now(UTC),
            )

        return None

    # ── Breaking News Handler ──────────────────────────────────────

    async def _handle_breaking_news(self, event: CloudEvent) -> None:
        """Handle breaking news — check positions for exits."""
        sentiment = event.data.get("sentiment", 0)
        impact = event.data.get("impact", "low")

        if impact not in ("critical", "high"):
            return

        logger.warning(
            "📰 Breaking news (impact=%s, sentiment=%.2f) — checking positions",
            impact,
            sentiment,
        )

        actions = []
        for pos_id, _pos in self._positions.items():
            current_rr = 0  # Would need current price
            should_exit, reason = NewsProximity.should_exit_for_news(None, current_rr)
            if should_exit:
                actions.append(
                    TradeAction(
                        position_id=pos_id,
                        action="close",
                        reason=ExitReason.NEWS_EVENT,
                        details=reason,
                        timestamp=datetime.now(UTC),
                    )
                )

        for action in actions:
            await self._execute_action(action)

    # ── Action Execution ───────────────────────────────────────────

    async def _execute_action(self, action: TradeAction) -> None:
        """Execute a trade management action."""
        pos = self._positions.get(action.position_id)
        if not pos:
            logger.warning("Action for unknown position: %s", action.position_id)
            return

        logger.info(
            "🎯 Trade action: %s %s — %s (%s)",
            action.action.upper(),
            action.position_id,
            action.details,
            action.reason.value,
        )

        if action.action == "update_stop":
            # Update stop-loss order
            pos.stop_loss = action.new_stop
            if self._exec_engine:
                try:
                    # In production, modify the stop-loss order on exchange
                    # await self._exec_engine.modify_stop(action.position_id, action.new_stop)
                    pass
                except Exception:
                    logger.exception("Failed to update stop-loss")

        elif action.action == "partial_exit":
            # Execute partial exit
            pos.remaining_quantity -= action.quantity
            pos.partial_exits_taken += 1
            if self._exec_engine:
                try:
                    # In production, place a market order for the partial exit
                    # await self._exec_engine.execute_partial_exit(...)
                    pass
                except Exception:
                    logger.exception("Failed to execute partial exit")

        elif action.action == "close":
            # Close entire position
            if self._exec_engine:
                try:
                    # In production, close the position on exchange
                    # await self._exec_engine.close_position(...)
                    pass
                except Exception:
                    logger.exception("Failed to close position")
            # Remove from managed positions
            del self._positions[action.position_id]

        # Publish action event
        await self.publish_event(
            stream="trade_actions",
            event_type="tsar.trade.action.v1",
            data={
                "position_id": action.position_id,
                "action": action.action,
                "quantity": action.quantity,
                "new_stop": action.new_stop,
                "reason": action.reason.value,
                "details": action.details,
                "timestamp": (action.timestamp or datetime.now(UTC)).isoformat(),
            },
            priority=1,
            risk_level="LOW",
        )

    # ── Helpers ────────────────────────────────────────────────────

    async def _fetch_current_prices(self) -> dict[str, float]:
        """Fetch current prices for all managed positions."""
        prices = {}
        # In production, fetch from exchange gateway
        # For now, return empty — prices would come from the gateway
        return prices

    def _calculate_current_rr(
        self,
        pos: ManagedPosition,
        current_price: float,
    ) -> float:
        """Calculate current R:R for a position."""
        if pos.risk_per_unit == 0:
            return 0.0

        if pos.side == "buy":
            reward = current_price - pos.entry_price
        else:
            reward = pos.entry_price - current_price

        return reward / pos.risk_per_unit

    def _update_position_tracking(self, prices: dict[str, float]) -> None:
        """Update position tracking data."""
        now = datetime.now(UTC)

        for _pos_id, pos in self._positions.items():
            current_price = prices.get(pos.symbol)
            if current_price is None:
                continue

            # Update highest/lowest prices
            if pos.side == "buy":
                if current_price > pos.highest_price:
                    pos.highest_price = current_price
                    pos.last_price_move_time = now
            else:
                if current_price < pos.lowest_price:
                    pos.lowest_price = current_price
                    pos.last_price_move_time = now

    def get_managed_positions(self) -> dict[str, dict[str, Any]]:
        """Get summary of all managed positions."""
        summary = {}
        for pos_id, pos in self._positions.items():
            summary[pos_id] = {
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "remaining_quantity": pos.remaining_quantity,
                "stop_loss": pos.stop_loss,
                "trailing_stage": pos.trailing_stage.value,
                "partial_exits_taken": pos.partial_exits_taken,
                "breakeven_triggered": pos.breakeven_triggered,
                "hours_held": ((datetime.now(UTC) - pos.entry_time).total_seconds() / 3600),
            }
        return summary
