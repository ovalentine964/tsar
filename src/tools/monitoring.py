"""
TSAR Domain Tools — Monitoring Tools.

What the agent TRACKS and ALERTS on. Provides real-time visibility
into portfolio performance, risk state, and system health.

Tools:
  1. P&L Tracker        — Real-time unrealized/realized P&L per trade/day/week/month
  2. Win Rate Tracker   — Running win rate (last 30/50/100), by strategy/symbol/regime
  3. Equity Curve       — Real-time equity curve with drawdown visualization
  4. Risk State Monitor — Current risk level (GREEN/YELLOW/ORANGE/RED), circuit breaker status
  5. Alert Generator    — Trade fills, risk warnings, system health alerts (Telegram)

All tools are async and operate through the shared types from src.interfaces.types.
Integrates with GuardStatePersistence, DrawdownMonitor, KillSwitch, and EventBus.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from src.comms.event_bus import EventBus
    from src.risk.drawdown import DrawdownMonitor
    from src.risk.guard_state import GuardStatePersistence
    from src.risk.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TradeRecord:
    """A completed trade record for P&L and win-rate tracking.

    Attributes:
        trade_id: Unique trade identifier.
        symbol: Trading pair.
        side: Buy or sell.
        strategy: Strategy that generated the signal.
        regime: Market regime at time of trade.
        entry_price: Entry price.
        exit_price: Exit price.
        quantity: Trade quantity.
        realized_pnl: Realized P&L (positive = profit).
        realized_pnl_pct: P&L as percentage of entry notional.
        fees: Total fees paid.
        entry_time: When the position was opened.
        exit_time: When the position was closed.
    """

    trade_id: str
    symbol: str
    side: str  # "buy" | "sell"
    strategy: str = ""
    regime: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0
    fees: float = 0.0
    entry_time: datetime | None = None
    exit_time: datetime | None = None


@dataclass(frozen=True)
class OpenPosition:
    """An open position for unrealized P&L tracking.

    Attributes:
        symbol: Trading pair.
        side: Buy (long) or sell (short).
        quantity: Position size.
        entry_price: Average entry price.
        current_price: Current market price.
        unrealized_pnl: Unrealized P&L in quote currency.
        unrealized_pnl_pct: Unrealized P&L as percentage.
        strategy: Strategy that opened the position.
    """

    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    strategy: str = ""


@dataclass(frozen=True)
class PnLSnapshot:
    """Complete P&L snapshot.

    Attributes:
        unrealized_pnl: Total unrealized P&L across open positions.
        realized_pnl_today: Realized P&L for current day.
        realized_pnl_week: Realized P&L for current week (rolling 7d).
        realized_pnl_month: Realized P&L for current month (rolling 30d).
        realized_pnl_total: All-time realized P&L.
        total_pnl: Unrealized + realized (today).
        open_positions: Individual open position P&L breakdown.
        timestamp: When the snapshot was taken.
    """

    unrealized_pnl: float
    realized_pnl_today: float
    realized_pnl_week: float
    realized_pnl_month: float
    realized_pnl_total: float
    total_pnl: float
    open_positions: tuple[OpenPosition, ...]
    timestamp: datetime | None = None


@dataclass(frozen=True)
class WinRateSnapshot:
    """Win rate analysis across multiple windows and dimensions.

    Attributes:
        overall_win_rate: All-time win rate.
        win_rate_30: Win rate over last 30 trades.
        win_rate_50: Win rate over last 50 trades.
        win_rate_100: Win rate over last 100 trades.
        by_strategy: Win rate breakdown by strategy name.
        by_symbol: Win rate breakdown by trading pair.
        by_regime: Win rate breakdown by market regime.
        total_trades: Total number of completed trades.
        total_wins: Total winning trades.
        total_losses: Total losing trades.
        avg_win: Average winning trade P&L.
        avg_loss: Average losing trade P&L.
        profit_factor: Gross profit / gross loss.
        expectancy: Average P&L per trade.
        timestamp: When the snapshot was taken.
    """

    overall_win_rate: float
    win_rate_30: float
    win_rate_50: float
    win_rate_100: float
    by_strategy: dict[str, float]
    by_symbol: dict[str, float]
    by_regime: dict[str, float]
    total_trades: int
    total_wins: int
    total_losses: int
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    timestamp: datetime | None = None


@dataclass(frozen=True)
class EquityPoint:
    """A single point on the equity curve.

    Attributes:
        timestamp: When the equity was recorded.
        equity: Total portfolio value.
        high_water_mark: Peak equity up to this point.
        drawdown_pct: Current drawdown from HWM (negative or zero).
        daily_pnl: P&L for the day at this point.
    """

    timestamp: datetime
    equity: float
    high_water_mark: float
    drawdown_pct: float = 0.0
    daily_pnl: float = 0.0


@dataclass(frozen=True)
class EquityCurveSnapshot:
    """Equity curve with drawdown visualization data.

    Attributes:
        current_equity: Current total portfolio value.
        high_water_mark: All-time peak equity.
        current_drawdown_pct: Current drawdown from HWM.
        max_drawdown_pct: Maximum drawdown ever observed.
        equity_curve: Time-series equity data points.
        drawdown_periods: List of (start, end, depth) for significant drawdowns.
        daily_returns: Daily return percentages.
        sharpe_ratio: Annualized Sharpe ratio from daily returns.
        sortino_ratio: Annualized Sortino ratio (downside deviation only).
        calmar_ratio: Annualized return / max drawdown.
        timestamp: When the snapshot was taken.
    """

    current_equity: float
    high_water_mark: float
    current_drawdown_pct: float
    max_drawdown_pct: float
    equity_curve: tuple[EquityPoint, ...]
    drawdown_periods: tuple[tuple[datetime, datetime, float], ...]
    daily_returns: tuple[float, ...]
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    timestamp: datetime | None = None


@dataclass(frozen=True)
class RiskStateSnapshot:
    """Complete risk state with circuit breaker status.

    Attributes:
        risk_level: Current risk level (GREEN/YELLOW/ORANGE/RED).
        drawdown_pct: Current drawdown from high water mark.
        daily_pnl_pct: Today's P&L as percentage of equity.
        trading_allowed: Whether new trades are permitted.
        position_size_multiplier: Current position sizing factor.
        kill_switch_active: Whether the kill switch is engaged.
        kill_switch_reason: Reason for kill switch activation.
        consecutive_losses: Current consecutive loss streak.
        consecutive_wins: Current consecutive win streak.
        on_cooldown: Whether revenge-trading cooldown is active.
        cooldown_remaining_s: Seconds remaining in cooldown.
        recovery_active: Whether recovery protocol is running.
        recovery_level: Recovery level (orange/red).
        recovery_allocation: Current recovery allocation percentage.
        circuit_breaker_config: Threshold configuration.
        timestamp: When the snapshot was taken.
    """

    risk_level: str
    drawdown_pct: float
    daily_pnl_pct: float
    trading_allowed: bool
    position_size_multiplier: float
    kill_switch_active: bool
    kill_switch_reason: str
    consecutive_losses: int
    consecutive_wins: int
    on_cooldown: bool
    cooldown_remaining_s: float
    recovery_active: bool
    recovery_level: str
    recovery_allocation: float
    circuit_breaker_config: dict[str, Any]
    timestamp: datetime | None = None


class AlertSeverity(StrEnum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(StrEnum):
    """Alert categories."""

    TRADE_FILL = "trade_fill"
    RISK_WARNING = "risk_warning"
    CIRCUIT_BREAKER = "circuit_breaker"
    KILL_SWITCH = "kill_switch"
    SYSTEM_HEALTH = "system_health"
    DRAWDOWN = "drawdown"
    WIN_STREAK = "win_streak"
    LOSS_STREAK = "loss_streak"
    COOLDOWN = "cooldown"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class Alert:
    """A monitoring alert.

    Attributes:
        alert_id: Unique alert identifier.
        alert_type: Category of the alert.
        severity: INFO / WARNING / CRITICAL.
        title: Short alert title.
        message: Detailed alert message.
        data: Structured alert payload.
        timestamp: When the alert was generated.
    """

    alert_id: str
    alert_type: str
    severity: str
    title: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# TOOL 1: P&L TRACKER
# ═══════════════════════════════════════════════════════════════════════


class PnLTracker:
    """Real-time unrealized and realized P&L tracking.

    Tracks:
    - Unrealized P&L across all open positions (updated on tick)
    - Realized P&L per trade, aggregated by day/week/month
    - Fee-adjusted P&L for accurate net returns

    Thread-safe via internal locks. All state is in-memory with
    optional persistence to JSON.
    """

    def __init__(
        self,
        persistence_path: str | None = None,
        max_history: int = 10_000,
    ) -> None:
        self._persistence_path = persistence_path
        self._max_history = max_history

        # Open positions (symbol -> OpenPosition)
        self._open_positions: dict[str, OpenPosition] = {}

        # Completed trades (ring buffer)
        self._completed_trades: deque[TradeRecord] = deque(maxlen=max_history)

        # Daily realized P&L cache (date_str -> pnl)
        self._daily_pnl: dict[str, float] = defaultdict(float)

        # Running totals
        self._total_realized_pnl: float = 0.0
        self._total_fees: float = 0.0

        # Load persisted state
        self._load()

    def record_trade(self, trade: TradeRecord) -> None:
        """Record a completed (closed) trade.

        Args:
            trade: Completed trade with realized P&L.
        """
        self._completed_trades.append(trade)
        self._total_realized_pnl += trade.realized_pnl
        self._total_fees += trade.fees

        # Aggregate by day
        if trade.exit_time:
            day_key = trade.exit_time.strftime("%Y-%m-%d")
        else:
            day_key = datetime.now(UTC).strftime("%Y-%m-%d")
        self._daily_pnl[day_key] += trade.realized_pnl

        # Remove from open positions if present
        self._open_positions.pop(trade.symbol, None)

        logger.info(
            "PnLTracker: recorded trade %s %s pnl=%.2f (%.2f%%)",
            trade.symbol,
            trade.side,
            trade.realized_pnl,
            trade.realized_pnl_pct,
        )
        self._save()

    def update_position(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        strategy: str = "",
    ) -> OpenPosition:
        """Update or create an open position for unrealized P&L.

        Args:
            symbol: Trading pair.
            side: "buy" (long) or "sell" (short).
            quantity: Position size.
            entry_price: Average entry price.
            current_price: Current market price.
            strategy: Strategy name.

        Returns:
            The updated OpenPosition.
        """
        if side == "buy":
            unrealized = (current_price - entry_price) * quantity
        else:
            unrealized = (entry_price - current_price) * quantity

        notional = entry_price * quantity
        unrealized_pct = (unrealized / notional * 100) if notional > 0 else 0.0

        pos = OpenPosition(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=current_price,
            unrealized_pnl=round(unrealized, 4),
            unrealized_pnl_pct=round(unrealized_pct, 4),
            strategy=strategy,
        )
        self._open_positions[symbol] = pos
        return pos

    def remove_position(self, symbol: str) -> None:
        """Remove an open position (e.g., after full close)."""
        self._open_positions.pop(symbol, None)

    def get_snapshot(self) -> PnLSnapshot:
        """Get a complete P&L snapshot.

        Returns:
            PnLSnapshot with unrealized, realized (today/week/month/total),
            and per-position breakdown.
        """
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")

        # Unrealized P&L
        unrealized = sum(p.unrealized_pnl for p in self._open_positions.values())

        # Realized P&L by period
        realized_today = self._daily_pnl.get(today, 0.0)

        week_cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        month_cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        realized_week = sum(pnl for day, pnl in self._daily_pnl.items() if day >= week_cutoff)
        realized_month = sum(pnl for day, pnl in self._daily_pnl.items() if day >= month_cutoff)

        return PnLSnapshot(
            unrealized_pnl=round(unrealized, 4),
            realized_pnl_today=round(realized_today, 4),
            realized_pnl_week=round(realized_week, 4),
            realized_pnl_month=round(realized_month, 4),
            realized_pnl_total=round(self._total_realized_pnl, 4),
            total_pnl=round(unrealized + realized_today, 4),
            open_positions=tuple(self._open_positions.values()),
            timestamp=now,
        )

    def get_daily_pnl_series(self, days: int = 30) -> list[tuple[str, float]]:
        """Get daily realized P&L time series.

        Args:
            days: Number of days to look back.

        Returns:
            List of (date_str, pnl) tuples, sorted ascending.
        """
        now = datetime.now(UTC)
        result: list[tuple[str, float]] = []
        for i in range(days, -1, -1):
            day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            result.append((day, self._daily_pnl.get(day, 0.0)))
        return result

    def get_trades(
        self,
        limit: int = 100,
        strategy: str | None = None,
        symbol: str | None = None,
    ) -> list[TradeRecord]:
        """Get recent completed trades with optional filtering.

        Args:
            limit: Maximum trades to return.
            strategy: Filter by strategy name.
            symbol: Filter by symbol.

        Returns:
            List of TradeRecord, most recent first.
        """
        trades = list(reversed(self._completed_trades))
        if strategy:
            trades = [t for t in trades if t.strategy == strategy]
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]
        return trades[:limit]

    def _save(self) -> None:
        """Persist state to JSON file."""
        if not self._persistence_path:
            return
        from pathlib import Path

        path = Path(self._persistence_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            state = {
                "total_realized_pnl": self._total_realized_pnl,
                "total_fees": self._total_fees,
                "daily_pnl": dict(self._daily_pnl),
                "trades": [
                    {
                        "trade_id": t.trade_id,
                        "symbol": t.symbol,
                        "side": t.side,
                        "strategy": t.strategy,
                        "regime": t.regime,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "quantity": t.quantity,
                        "realized_pnl": t.realized_pnl,
                        "realized_pnl_pct": t.realized_pnl_pct,
                        "fees": t.fees,
                        "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                    }
                    for t in self._completed_trades
                ],
            }
            path.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.error("PnLTracker: failed to save state: %s", e)

    def _load(self) -> None:
        """Load persisted state from JSON file."""
        if not self._persistence_path:
            return
        from pathlib import Path

        path = Path(self._persistence_path)
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text())
            self._total_realized_pnl = state.get("total_realized_pnl", 0.0)
            self._total_fees = state.get("total_fees", 0.0)
            self._daily_pnl = defaultdict(float, state.get("daily_pnl", {}))
            for t in state.get("trades", []):
                self._completed_trades.append(
                    TradeRecord(
                        trade_id=t["trade_id"],
                        symbol=t["symbol"],
                        side=t["side"],
                        strategy=t.get("strategy", ""),
                        regime=t.get("regime", ""),
                        entry_price=t.get("entry_price", 0.0),
                        exit_price=t.get("exit_price", 0.0),
                        quantity=t.get("quantity", 0.0),
                        realized_pnl=t.get("realized_pnl", 0.0),
                        realized_pnl_pct=t.get("realized_pnl_pct", 0.0),
                        fees=t.get("fees", 0.0),
                        entry_time=_parse_dt(t.get("entry_time")),
                        exit_time=_parse_dt(t.get("exit_time")),
                    )
                )
            logger.info(
                "PnLTracker: loaded %d trades, total_pnl=%.2f",
                len(self._completed_trades),
                self._total_realized_pnl,
            )
        except Exception as e:
            logger.error("PnLTracker: failed to load state: %s", e)


# ═══════════════════════════════════════════════════════════════════════
# TOOL 2: WIN RATE TRACKER
# ═══════════════════════════════════════════════════════════════════════


class WinRateTracker:
    """Running win rate tracker with multi-dimensional breakdowns.

    Tracks:
    - Running win rate over last 30, 50, 100 trades
    - Win rate by strategy, symbol, and regime
    - Profit factor, expectancy, avg win/loss
    - Integrates with GuardStatePersistence for streak tracking

    All computations are O(n) over the trade history ring buffer.
    """

    def __init__(
        self,
        guard_state: GuardStatePersistence | None = None,
        max_history: int = 10_000,
    ) -> None:
        self._guard_state = guard_state
        self._max_history = max_history

        # Trade outcomes ring buffer: list of (is_win, pnl, strategy, symbol, regime)
        self._outcomes: deque[tuple[bool, float, str, str, str]] = deque(maxlen=max_history)

    def record_outcome(
        self,
        is_win: bool,
        pnl: float,
        strategy: str = "",
        symbol: str = "",
        regime: str = "",
    ) -> None:
        """Record a trade outcome.

        Args:
            is_win: Whether the trade was profitable.
            pnl: Realized P&L amount.
            strategy: Strategy name.
            symbol: Trading pair.
            regime: Market regime at time of trade.
        """
        self._outcomes.append((is_win, pnl, strategy, symbol, regime))

        # Sync with guard state if available
        if self._guard_state:
            if is_win:
                self._guard_state.record_win()
            else:
                self._guard_state.record_loss()
            self._guard_state.append_trade_result(is_win)

    def get_snapshot(self) -> WinRateSnapshot:
        """Get a complete win rate analysis snapshot.

        Returns:
            WinRateSnapshot with all metrics and breakdowns.
        """
        if not self._outcomes:
            return WinRateSnapshot(
                overall_win_rate=0.0,
                win_rate_30=0.0,
                win_rate_50=0.0,
                win_rate_100=0.0,
                by_strategy={},
                by_symbol={},
                by_regime={},
                total_trades=0,
                total_wins=0,
                total_losses=0,
                avg_win=0.0,
                avg_loss=0.0,
                profit_factor=0.0,
                expectancy=0.0,
                timestamp=datetime.now(UTC),
            )

        outcomes = list(self._outcomes)
        total = len(outcomes)
        wins = sum(1 for o in outcomes if o[0])
        losses = total - wins

        # Win rates by window
        def _win_rate_window(n: int) -> float:
            window = outcomes[-n:] if len(outcomes) >= n else outcomes
            if not window:
                return 0.0
            w = sum(1 for o in window if o[0])
            return round(w / len(window), 4)

        # Win/loss amounts
        win_pnls = [o[1] for o in outcomes if o[0]]
        loss_pnls = [abs(o[1]) for o in outcomes if not o[0]]

        avg_win = round(sum(win_pnls) / len(win_pnls), 4) if win_pnls else 0.0
        avg_loss = round(sum(loss_pnls) / len(loss_pnls), 4) if loss_pnls else 0.0
        gross_profit = sum(win_pnls)
        gross_loss = sum(loss_pnls)
        profit_factor = (
            round(gross_profit / gross_loss, 4)
            if gross_loss > 0
            else (float("inf") if gross_profit > 0 else 0.0)
        )
        total_pnl = sum(o[1] for o in outcomes)
        expectancy = round(total_pnl / total, 4) if total > 0 else 0.0

        # Breakdowns
        def _breakdown(idx: int) -> dict[str, float]:
            groups: dict[str, list[bool]] = defaultdict(list)
            for o in outcomes:
                key = o[idx]
                if key:
                    groups[key].append(o[0])
            return {k: round(sum(v) / len(v), 4) for k, v in groups.items() if v}

        return WinRateSnapshot(
            overall_win_rate=round(wins / total, 4) if total > 0 else 0.0,
            win_rate_30=_win_rate_window(30),
            win_rate_50=_win_rate_window(50),
            win_rate_100=_win_rate_window(100),
            by_strategy=_breakdown(2),  # strategy
            by_symbol=_breakdown(3),  # symbol
            by_regime=_breakdown(4),  # regime
            total_trades=total,
            total_wins=wins,
            total_losses=losses,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            expectancy=expectancy,
            timestamp=datetime.now(UTC),
        )

    def get_streak_info(self) -> dict[str, int]:
        """Get current win/loss streak information.

        Returns:
            Dict with 'consecutive_wins', 'consecutive_losses',
            'max_win_streak', 'max_loss_streak'.
        """
        if not self._outcomes:
            return {
                "consecutive_wins": 0,
                "consecutive_losses": 0,
                "max_win_streak": 0,
                "max_loss_streak": 0,
            }

        # Current streak (from most recent)
        outcomes = list(self._outcomes)
        current_streak_type = outcomes[-1][0]
        current_streak_len = 0
        for o in reversed(outcomes):
            if o[0] == current_streak_type:
                current_streak_len += 1
            else:
                break

        # Max streaks (full history)
        max_win = 0
        max_loss = 0
        cur_win = 0
        cur_loss = 0
        for o in outcomes:
            if o[0]:
                cur_win += 1
                cur_loss = 0
                max_win = max(max_win, cur_win)
            else:
                cur_loss += 1
                cur_win = 0
                max_loss = max(max_loss, cur_loss)

        return {
            "consecutive_wins": current_streak_len if current_streak_type else 0,
            "consecutive_losses": 0 if current_streak_type else current_streak_len,
            "max_win_streak": max_win,
            "max_loss_streak": max_loss,
        }


# ═══════════════════════════════════════════════════════════════════════
# TOOL 3: EQUITY CURVE
# ═══════════════════════════════════════════════════════════════════════


class EquityCurve:
    """Real-time equity curve with drawdown visualization.

    Tracks:
    - Equity time series (high-water mark, drawdown at each point)
    - Maximum drawdown and drawdown period detection
    - Daily returns for Sharpe/Sortino/Calmar ratio computation

    Uses a ring buffer to cap memory usage.
    """

    def __init__(
        self,
        initial_equity: float = 0.0,
        max_points: int = 50_000,
        risk_free_rate: float = 0.04,
    ) -> None:
        self._max_points = max_points
        self._risk_free_rate = risk_free_rate

        # Equity time series ring buffer
        self._equity_points: deque[EquityPoint] = deque(maxlen=max_points)

        # Tracking state
        self._high_water_mark: float = initial_equity
        self._max_drawdown_pct: float = 0.0
        self._peak_equity: float = initial_equity

        # Daily return tracking
        self._daily_equity: dict[str, float] = {}  # date -> last equity of day
        self._last_day: str = ""

        # Drawdown period tracking
        self._drawdown_start: datetime | None = None
        self._drawdown_periods: list[tuple[datetime, datetime, float]] = []

        # Initialize with starting equity if provided
        if initial_equity > 0:
            now = datetime.now(UTC)
            self._equity_points.append(
                EquityPoint(
                    timestamp=now,
                    equity=initial_equity,
                    high_water_mark=initial_equity,
                    drawdown_pct=0.0,
                )
            )

    def update(
        self,
        equity: float,
        daily_pnl: float = 0.0,
        timestamp: datetime | None = None,
    ) -> EquityPoint:
        """Record a new equity data point.

        Args:
            equity: Current total portfolio value.
            daily_pnl: P&L for the current day.
            timestamp: When the equity was observed (defaults to now).

        Returns:
            The new EquityPoint.
        """
        ts = timestamp or datetime.now(UTC)

        # Update HWM
        if equity > self._high_water_mark:
            self._high_water_mark = equity
            # Close any open drawdown period
            if self._drawdown_start is not None:
                self._drawdown_periods.append((self._drawdown_start, ts, self._max_drawdown_pct))
                self._drawdown_start = None
                self._max_drawdown_pct = 0.0

        # Drawdown from HWM
        dd_pct = 0.0
        if self._high_water_mark > 0:
            dd_pct = (equity - self._high_water_mark) / self._high_water_mark

        # Track max drawdown
        if dd_pct < self._max_drawdown_pct:
            self._max_drawdown_pct = dd_pct

        # Track drawdown periods
        if dd_pct < 0 and self._drawdown_start is None:
            self._drawdown_start = ts

        point = EquityPoint(
            timestamp=ts,
            equity=round(equity, 4),
            high_water_mark=round(self._high_water_mark, 4),
            drawdown_pct=round(dd_pct, 6),
            daily_pnl=round(daily_pnl, 4),
        )
        self._equity_points.append(point)

        # Daily return tracking
        day_key = ts.strftime("%Y-%m-%d")
        if day_key != self._last_day and self._last_day:
            prev_equity = self._daily_equity.get(self._last_day, 0)
            if prev_equity > 0:
                self._daily_equity[self._last_day] = prev_equity  # lock previous day
        self._daily_equity[day_key] = equity
        self._last_day = day_key

        return point

    def get_snapshot(
        self,
        lookback_days: int = 365,
    ) -> EquityCurveSnapshot:
        """Get equity curve snapshot with analytics.

        Args:
            lookback_days: Days of history to include in the curve.

        Returns:
            EquityCurveSnapshot with curve data, drawdowns, and ratios.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=lookback_days)

        # Filter points to lookback window
        curve_points = tuple(p for p in self._equity_points if p.timestamp >= cutoff)

        # Close any open drawdown period
        dd_periods = list(self._drawdown_periods)
        if self._drawdown_start is not None:
            current_dd = 0.0
            if curve_points:
                current_dd = curve_points[-1].drawdown_pct
            dd_periods.append((self._drawdown_start, now, current_dd))

        # Daily returns
        daily_returns = self._compute_daily_returns()

        # Performance ratios
        sharpe = self._compute_sharpe(daily_returns)
        sortino = self._compute_sortino(daily_returns)
        calmar = self._compute_calmar(daily_returns)

        # Current state
        current_equity = curve_points[-1].equity if curve_points else 0.0
        current_dd = curve_points[-1].drawdown_pct if curve_points else 0.0

        return EquityCurveSnapshot(
            current_equity=current_equity,
            high_water_mark=self._high_water_mark,
            current_drawdown_pct=round(current_dd, 6),
            max_drawdown_pct=round(self._max_drawdown_pct, 6),
            equity_curve=curve_points,
            drawdown_periods=tuple(dd_periods),
            daily_returns=tuple(daily_returns),
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            timestamp=now,
        )

    def get_current_drawdown(self) -> float:
        """Get current drawdown percentage (0 or negative)."""
        if not self._equity_points or self._high_water_mark <= 0:
            return 0.0
        latest = self._equity_points[-1].equity
        return round((latest - self._high_water_mark) / self._high_water_mark, 6)

    def _compute_daily_returns(self) -> list[float]:
        """Compute daily return percentages from equity snapshots."""
        sorted_days = sorted(self._daily_equity.items())
        if len(sorted_days) < 2:
            return []

        returns: list[float] = []
        for i in range(1, len(sorted_days)):
            prev_eq = sorted_days[i - 1][1]
            curr_eq = sorted_days[i][1]
            if prev_eq > 0:
                ret = (curr_eq - prev_eq) / prev_eq
                returns.append(round(ret, 6))
        return returns

    def _compute_sharpe(self, daily_returns: list[float]) -> float:
        """Annualized Sharpe ratio from daily returns."""
        if len(daily_returns) < 2:
            return 0.0
        arr = np.array(daily_returns)
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1))
        if std == 0:
            return 0.0
        daily_rf = self._risk_free_rate / 252
        return round((mean - daily_rf) / std * math.sqrt(252), 4)

    def _compute_sortino(self, daily_returns: list[float]) -> float:
        """Annualized Sortino ratio (downside deviation only)."""
        if len(daily_returns) < 2:
            return 0.0
        arr = np.array(daily_returns)
        mean = float(np.mean(arr))
        daily_rf = self._risk_free_rate / 252
        downside = arr[arr < daily_rf]
        if len(downside) == 0:
            return float("inf") if mean > daily_rf else 0.0
        downside_std = float(np.std(downside, ddof=1))
        if downside_std == 0:
            return 0.0
        return round((mean - daily_rf) / downside_std * math.sqrt(252), 4)

    def _compute_calmar(self, daily_returns: list[float]) -> float:
        """Calmar ratio: annualized return / |max drawdown|."""
        if not daily_returns or self._max_drawdown_pct >= 0:
            return 0.0
        annual_return = float(np.mean(daily_returns)) * 252
        return round(annual_return / abs(self._max_drawdown_pct), 4)


# ═══════════════════════════════════════════════════════════════════════
# TOOL 4: RISK STATE MONITOR
# ═══════════════════════════════════════════════════════════════════════


class RiskStateMonitor:
    """Aggregated risk state monitor with circuit breaker status.

    Combines data from:
    - DrawdownMonitor (circuit breaker level)
    - KillSwitch (emergency halt status)
    - GuardStatePersistence (behavioral guards, streaks)
    - RiskGovernor recovery protocol

    Provides a single snapshot of the complete risk posture.
    """

    def __init__(
        self,
        drawdown_monitor: DrawdownMonitor | None = None,
        kill_switch: KillSwitch | None = None,
        guard_state: GuardStatePersistence | None = None,
        risk_governor: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._drawdown_monitor = drawdown_monitor
        self._kill_switch = kill_switch
        self._guard_state = guard_state
        self._risk_governor = risk_governor
        self._config = config or {}

        # Default circuit breaker thresholds (from risk.yaml)
        self._cb_config = {
            "daily_loss_flatten": self._config.get("daily_loss_flatten", -0.02),
            "daily_loss_kill": self._config.get("daily_loss_kill", -0.03),
            "max_drawdown_halt": self._config.get("max_drawdown_halt", -0.05),
            "max_drawdown_flatten": self._config.get("max_drawdown_flatten", -0.15),
        }

    async def get_snapshot(
        self,
        equity: float = 0.0,
        high_water_mark: float = 0.0,
        daily_pnl: float = 0.0,
        positions: tuple = (),
    ) -> RiskStateSnapshot:
        """Get a complete risk state snapshot.

        Gathers data from all risk subsystems and produces a single
        unified view of the current risk posture.

        Args:
            equity: Current portfolio equity.
            high_water_mark: Peak portfolio equity.
            daily_pnl: Today's realized P&L.
            positions: Current open positions (for drawdown calc).

        Returns:
            RiskStateSnapshot with full risk status.
        """
        from src.interfaces.types import Portfolio

        # Build portfolio for drawdown evaluation
        daily_pnl_pct = (daily_pnl / equity) if equity > 0 else 0.0
        portfolio = Portfolio(
            equity=equity,
            high_water_mark=high_water_mark,
            cash=equity,  # simplified
            positions=positions,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            open_position_count=len(positions),
        )

        # Drawdown / circuit breaker
        risk_level = "GREEN"
        trading_allowed = True
        size_multiplier = 1.0
        drawdown_pct = 0.0

        if self._drawdown_monitor:
            dd_state = self._drawdown_monitor.evaluate(portfolio)
            risk_level = dd_state.circuit_breaker_level
            trading_allowed = dd_state.trading_allowed
            size_multiplier = dd_state.position_size_multiplier
            drawdown_pct = dd_state.current_drawdown_pct

        # Kill switch
        ks_active = False
        ks_reason = ""
        if self._kill_switch:
            ks_active = await self._kill_switch.is_active()
            if ks_active:
                status = await self._kill_switch.get_status()
                ks_reason = status.get("reason", "unknown")
                risk_level = "RED"
                trading_allowed = False

        # Behavioral guards
        consecutive_losses = 0
        consecutive_wins = 0
        on_cooldown = False
        cooldown_remaining = 0.0
        if self._guard_state:
            consecutive_losses = self._guard_state.get_consecutive_losses()
            consecutive_wins = self._guard_state.get_consecutive_wins()
            on_cooldown = self._guard_state.is_on_cooldown()
            cooldown_remaining = self._guard_state.get_cooldown_remaining_seconds()

        # Recovery protocol
        recovery_active = False
        recovery_level = ""
        recovery_allocation = 1.0
        if self._risk_governor:
            recovery_state = self._risk_governor.get_recovery_state()
            recovery_active = recovery_state.get("active", False)
            recovery_level = recovery_state.get("level", "")
            if recovery_active:
                recovery_allocation = self._risk_governor.get_recovery_allocation(recovery_level)

        return RiskStateSnapshot(
            risk_level=risk_level,
            drawdown_pct=round(drawdown_pct, 6),
            daily_pnl_pct=round(daily_pnl_pct, 6),
            trading_allowed=trading_allowed,
            position_size_multiplier=round(size_multiplier, 4),
            kill_switch_active=ks_active,
            kill_switch_reason=ks_reason,
            consecutive_losses=consecutive_losses,
            consecutive_wins=consecutive_wins,
            on_cooldown=on_cooldown,
            cooldown_remaining_s=round(cooldown_remaining, 1),
            recovery_active=recovery_active,
            recovery_level=recovery_level,
            recovery_allocation=round(recovery_allocation, 4),
            circuit_breaker_config=self._cb_config,
            timestamp=datetime.now(UTC),
        )


# ═══════════════════════════════════════════════════════════════════════
# TOOL 5: ALERT GENERATOR
# ═══════════════════════════════════════════════════════════════════════


class AlertGenerator:
    """Monitoring alert generator with Telegram notification support.

    Generates and dispatches alerts for:
    - Trade fills (entry/exit notifications)
    - Risk warnings (drawdown, streaks, cooldowns)
    - Circuit breaker transitions (GREEN→YELLOW→ORANGE→RED)
    - Kill switch activation/deactivation
    - System health events
    - Recovery protocol progress

    Alerts are published via EventBus and optionally sent as
    Telegram notifications.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        telegram_bot: Any | None = None,
        telegram_chat_id: str | None = None,
        alert_cooldown_s: float = 60.0,
    ) -> None:
        self._event_bus = event_bus
        self._telegram_bot = telegram_bot
        self._telegram_chat_id = telegram_chat_id
        self._alert_cooldown_s = alert_cooldown_s

        # Deduplication: last alert timestamp by (type, key)
        self._last_alert_time: dict[str, float] = {}

        # Alert history ring buffer
        self._alert_history: deque[Alert] = deque(maxlen=1000)

        # Counter for unique alert IDs
        self._alert_counter: int = 0

    async def emit_trade_fill(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        pnl: float,
        strategy: str = "",
    ) -> Alert | None:
        """Emit a trade fill alert.

        Args:
            trade_id: Trade identifier.
            symbol: Trading pair.
            side: Buy or sell.
            price: Fill price.
            quantity: Fill quantity.
            pnl: Realized P&L.
            strategy: Strategy name.

        Returns:
            The generated Alert, or None if suppressed by cooldown.
        """
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        title = f"Trade Fill: {symbol} {side.upper()}"
        message = (
            f"{pnl_emoji} {symbol} {side.upper()} @ {price:.4f}\n"
            f"Qty: {quantity:.6f} | P&L: {pnl:+.2f} USDT\n"
            f"Strategy: {strategy or 'N/A'}"
        )

        return await self._emit(
            alert_type=AlertType.TRADE_FILL,
            severity=AlertSeverity.INFO,
            title=title,
            message=message,
            key=f"fill:{trade_id}",
            data={
                "trade_id": trade_id,
                "symbol": symbol,
                "side": side,
                "price": price,
                "quantity": quantity,
                "pnl": pnl,
                "strategy": strategy,
            },
        )

    async def emit_risk_warning(
        self,
        warning_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> Alert | None:
        """Emit a risk warning alert.

        Args:
            warning_type: Sub-type of warning (e.g. "drawdown", "streak").
            message: Warning description.
            data: Additional structured data.

        Returns:
            The generated Alert, or None if suppressed.
        """
        return await self._emit(
            alert_type=AlertType.RISK_WARNING,
            severity=AlertSeverity.WARNING,
            title=f"⚠️ Risk Warning: {warning_type}",
            message=message,
            key=f"risk:{warning_type}",
            data=data or {},
        )

    async def emit_circuit_breaker(
        self,
        old_level: str,
        new_level: str,
        drawdown_pct: float,
        daily_pnl_pct: float,
    ) -> Alert | None:
        """Emit a circuit breaker level transition alert.

        Args:
            old_level: Previous risk level.
            new_level: New risk level.
            drawdown_pct: Current drawdown percentage.
            daily_pnl_pct: Today's P&L percentage.

        Returns:
            The generated Alert, or None if suppressed.
        """
        severity_map = {
            "GREEN": AlertSeverity.INFO,
            "YELLOW": AlertSeverity.WARNING,
            "ORANGE": AlertSeverity.WARNING,
            "RED": AlertSeverity.CRITICAL,
        }

        level_emoji = {
            "GREEN": "🟢",
            "YELLOW": "🟡",
            "ORANGE": "🟠",
            "RED": "🔴",
        }

        emoji = level_emoji.get(new_level, "⚪")
        severity = severity_map.get(new_level, AlertSeverity.WARNING)

        title = f"{emoji} Circuit Breaker: {old_level} → {new_level}"
        message = (
            f"Risk level changed: {old_level} → {new_level}\n"
            f"Drawdown: {drawdown_pct:.2%} | Daily P&L: {daily_pnl_pct:.2%}"
        )

        return await self._emit(
            alert_type=AlertType.CIRCUIT_BREAKER,
            severity=severity,
            title=title,
            message=message,
            key=f"cb:{new_level}",
            data={
                "old_level": old_level,
                "new_level": new_level,
                "drawdown_pct": drawdown_pct,
                "daily_pnl_pct": daily_pnl_pct,
            },
        )

    async def emit_kill_switch(
        self,
        active: bool,
        reason: str = "",
    ) -> Alert | None:
        """Emit a kill switch activation/deactivation alert.

        Args:
            active: Whether kill switch was activated (True) or deactivated (False).
            reason: Reason for activation.

        Returns:
            The generated Alert, or None if suppressed.
        """
        if active:
            title = "🔴 KILL SWITCH ACTIVATED"
            message = f"ALL TRADING HALTED\nReason: {reason}"
            severity = AlertSeverity.CRITICAL
        else:
            title = "🟢 Kill Switch Deactivated"
            message = "Trading resumed. Recovery protocol engaged."
            severity = AlertSeverity.WARNING

        return await self._emit(
            alert_type=AlertType.KILL_SWITCH,
            severity=severity,
            title=title,
            message=message,
            key="kill_switch",
            data={"active": active, "reason": reason},
        )

    async def emit_system_health(
        self,
        component: str,
        status: str,
        details: str = "",
    ) -> Alert | None:
        """Emit a system health alert.

        Args:
            component: System component name.
            status: Health status (healthy, degraded, down).
            details: Additional details.

        Returns:
            The generated Alert, or None if suppressed.
        """
        severity_map = {
            "healthy": AlertSeverity.INFO,
            "degraded": AlertSeverity.WARNING,
            "down": AlertSeverity.CRITICAL,
        }

        emoji_map = {
            "healthy": "✅",
            "degraded": "⚠️",
            "down": "🔴",
        }

        emoji = emoji_map.get(status, "❓")
        severity = severity_map.get(status, AlertSeverity.WARNING)

        title = f"{emoji} System: {component} — {status.upper()}"
        message = f"Component: {component}\nStatus: {status}"
        if details:
            message += f"\nDetails: {details}"

        return await self._emit(
            alert_type=AlertType.SYSTEM_HEALTH,
            severity=severity,
            title=title,
            message=message,
            key=f"health:{component}",
            data={"component": component, "status": status, "details": details},
        )

    async def emit_loss_streak(
        self,
        consecutive_losses: int,
        total_loss: float,
    ) -> Alert | None:
        """Emit a loss streak warning.

        Args:
            consecutive_losses: Current consecutive loss count.
            total_loss: Cumulative loss during streak.

        Returns:
            The generated Alert, or None if suppressed.
        """
        return await self._emit(
            alert_type=AlertType.LOSS_STREAK,
            severity=AlertSeverity.WARNING,
            title=f"🔴 Loss Streak: {consecutive_losses} consecutive losses",
            message=(
                f"Consecutive losses: {consecutive_losses}\nStreak loss: {total_loss:+.2f} USDT"
            ),
            key="loss_streak",
            data={
                "consecutive_losses": consecutive_losses,
                "total_loss": total_loss,
            },
        )

    async def emit_win_streak(
        self,
        consecutive_wins: int,
        total_profit: float,
    ) -> Alert | None:
        """Emit a win streak notification.

        Args:
            consecutive_wins: Current consecutive win count.
            total_profit: Cumulative profit during streak.

        Returns:
            The generated Alert, or None if suppressed.
        """
        return await self._emit(
            alert_type=AlertType.WIN_STREAK,
            severity=AlertSeverity.INFO,
            title=f"🟢 Win Streak: {consecutive_wins} consecutive wins",
            message=(
                f"Consecutive wins: {consecutive_wins}\nStreak profit: {total_profit:+.2f} USDT"
            ),
            key="win_streak",
            data={
                "consecutive_wins": consecutive_wins,
                "total_profit": total_profit,
            },
        )

    async def emit_cooldown(
        self,
        active: bool,
        remaining_seconds: float = 0.0,
    ) -> Alert | None:
        """Emit a cooldown status alert.

        Args:
            active: Whether cooldown was activated.
            remaining_seconds: Seconds remaining.

        Returns:
            The generated Alert, or None if suppressed.
        """
        if active:
            title = "⏱️ Cooldown Active"
            message = (
                f"Revenge-trading cooldown engaged.\n"
                f"Remaining: {remaining_seconds / 60:.0f} minutes"
            )
            severity = AlertSeverity.WARNING
        else:
            title = "✅ Cooldown Ended"
            message = "Cooldown period finished. Trading resumed."
            severity = AlertSeverity.INFO

        return await self._emit(
            alert_type=AlertType.COOLDOWN,
            severity=severity,
            title=title,
            message=message,
            key="cooldown",
            data={"active": active, "remaining_seconds": remaining_seconds},
        )

    async def emit_recovery(
        self,
        phase: int,
        total_phases: int,
        allocation_pct: float,
        level: str,
    ) -> Alert | None:
        """Emit a recovery protocol progress alert.

        Args:
            phase: Current phase number.
            total_phases: Total phases in recovery.
            allocation_pct: Current allocation percentage.
            level: Recovery level (orange/red).

        Returns:
            The generated Alert, or None if suppressed.
        """
        return await self._emit(
            alert_type=AlertType.RECOVERY,
            severity=AlertSeverity.INFO,
            title=f"🔄 Recovery Phase {phase}/{total_phases}",
            message=(
                f"Recovery [{level.upper()}] — Phase {phase}/{total_phases}\n"
                f"Allocation: {allocation_pct:.0%}"
            ),
            key=f"recovery:{phase}",
            data={
                "phase": phase,
                "total_phases": total_phases,
                "allocation_pct": allocation_pct,
                "level": level,
            },
        )

    def get_alert_history(
        self,
        limit: int = 50,
        severity: str | None = None,
        alert_type: str | None = None,
    ) -> list[Alert]:
        """Get recent alerts with optional filtering.

        Args:
            limit: Maximum alerts to return.
            severity: Filter by severity level.
            alert_type: Filter by alert type.

        Returns:
            List of Alert, most recent first.
        """
        alerts = list(reversed(self._alert_history))
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        return alerts[:limit]

    # ── Internal ─────────────────────────────────────────────────────

    async def _emit(
        self,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        key: str,
        data: dict[str, Any],
    ) -> Alert | None:
        """Emit an alert with deduplication, persistence, and notification."""
        # Deduplication check
        dedup_key = f"{alert_type}:{key}"
        now = time.time()
        last_time = self._last_alert_time.get(dedup_key, 0)
        if now - last_time < self._alert_cooldown_s:
            logger.debug("Alert suppressed (cooldown): %s", dedup_key)
            return None

        self._last_alert_time[dedup_key] = now

        # Build alert
        self._alert_counter += 1
        alert = Alert(
            alert_id=f"ALT-{self._alert_counter:06d}",
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            data=data,
            timestamp=datetime.now(UTC),
        )

        # Store in history
        self._alert_history.append(alert)

        # Log
        log_fn = {
            AlertSeverity.INFO: logger.info,
            AlertSeverity.WARNING: logger.warning,
            AlertSeverity.CRITICAL: logger.critical,
        }.get(severity, logger.info)
        log_fn("Alert [%s] %s: %s", severity, alert_type, title)

        # Publish to event bus
        if self._event_bus:
            try:
                await self._event_bus.publish(
                    "tsar.monitoring.alert.v1",
                    {
                        "alert_id": alert.alert_id,
                        "alert_type": alert_type,
                        "severity": severity,
                        "title": title,
                        "message": message,
                        "data": data,
                        "timestamp": alert.timestamp.isoformat() if alert.timestamp else "",
                    },
                )
            except Exception as e:
                logger.error("Failed to publish alert to event bus: %s", e)

        # Send Telegram notification
        if self._telegram_bot and self._telegram_chat_id:
            await self._send_telegram(alert)

        return alert

    async def _send_telegram(self, alert: Alert) -> None:
        """Send alert as Telegram notification.

        Uses the python-telegram-bot API if available.
        """
        try:
            severity_prefix = {
                AlertSeverity.INFO: "ℹ️",
                AlertSeverity.WARNING: "⚠️",
                AlertSeverity.CRITICAL: "🚨",
            }.get(alert.severity, "📢")

            text = f"{severity_prefix} *{alert.title}*\n\n{alert.message}"

            await self._telegram_bot.send_message(
                chat_id=self._telegram_chat_id,
                text=text,
                parse_mode="Markdown",
            )
            logger.debug("Telegram alert sent: %s", alert.alert_id)
        except Exception as e:
            logger.error("Failed to send Telegram alert: %s", e)


# ═══════════════════════════════════════════════════════════════════════
# UNIFIED MONITORING TOOLS CLASS
# ═══════════════════════════════════════════════════════════════════════


class MonitoringTools:
    """Unified monitoring tools facade.

    Aggregates all 5 monitoring tools behind a single interface
    that agents can use for real-time portfolio and risk monitoring.

    Tools:
      1. pnl       — P&L Tracker (unrealized + realized)
      2. win_rate   — Win Rate Tracker (multi-window + breakdowns)
      3. equity     — Equity Curve (time-series + drawdown visualization)
      4. risk_state — Risk State Monitor (circuit breakers + guards)
      5. alerts     — Alert Generator (Telegram + EventBus)

    Usage::

        tools = MonitoringTools(
            guard_state=guard_state,
            drawdown_monitor=drawdown_monitor,
            kill_switch=kill_switch,
            risk_governor=risk_governor,
            event_bus=event_bus,
        )

        # P&L
        tools.pnl.update_position("BTC/USDT", "buy", 0.1, 50000, 51000)
        pnl = tools.pnl.get_snapshot()

        # Win Rate
        tools.win_rate.record_outcome(True, 150.0, "momentum", "BTC/USDT", "trending")
        wr = tools.win_rate.get_snapshot()

        # Equity
        tools.equity.update(10500.0)
        eq = tools.equity.get_snapshot()

        # Risk State
        risk = await tools.risk_state.get_snapshot(equity=10500.0)

        # Alerts
        await tools.alerts.emit_trade_fill(...)
    """

    description = (
        "Monitoring tools: P&L tracking, win rate analysis, equity curve, "
        "risk state monitoring, and alert generation"
    )

    def __init__(
        self,
        guard_state: GuardStatePersistence | None = None,
        drawdown_monitor: DrawdownMonitor | None = None,
        kill_switch: KillSwitch | None = None,
        risk_governor: Any | None = None,
        event_bus: EventBus | None = None,
        telegram_bot: Any | None = None,
        telegram_chat_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config or {}
        persistence_path = cfg.get("persistence_path")

        # Initialize all 5 tools
        self.pnl = PnLTracker(
            persistence_path=f"{persistence_path}/pnl.json" if persistence_path else None,
        )
        self.win_rate = WinRateTracker(
            guard_state=guard_state,
        )
        self.equity = EquityCurve(
            initial_equity=cfg.get("initial_equity", 0.0),
        )
        self.risk_state = RiskStateMonitor(
            drawdown_monitor=drawdown_monitor,
            kill_switch=kill_switch,
            guard_state=guard_state,
            risk_governor=risk_governor,
            config=cfg,
        )
        self.alerts = AlertGenerator(
            event_bus=event_bus,
            telegram_bot=telegram_bot,
            telegram_chat_id=telegram_chat_id,
            alert_cooldown_s=cfg.get("alert_cooldown_s", 60.0),
        )

        # Wire cross-tool notifications
        self._drawdown_monitor = drawdown_monitor
        self._kill_switch = kill_switch
        self._last_risk_level: str = "GREEN"

        logger.info("MonitoringTools initialized with all 5 tools")

    async def on_trade_completed(
        self,
        trade: TradeRecord,
    ) -> None:
        """Handle a completed trade — update all relevant tools.

        This is the primary integration point. Call this after every
        trade close to update P&L, win rate, equity curve, and
        trigger any relevant alerts.

        Args:
            trade: Completed trade record.
        """
        # 1. P&L Tracker
        self.pnl.record_trade(trade)

        # 2. Win Rate Tracker
        is_win = trade.realized_pnl > 0
        self.win_rate.record_outcome(
            is_win=is_win,
            pnl=trade.realized_pnl,
            strategy=trade.strategy,
            symbol=trade.symbol,
            regime=trade.regime,
        )

        # 3. Alert: Trade fill
        await self.alerts.emit_trade_fill(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            side=trade.side,
            price=trade.exit_price,
            quantity=trade.quantity,
            pnl=trade.realized_pnl,
            strategy=trade.strategy,
        )

        # 4. Check for streak alerts
        streak = self.win_rate.get_streak_info()
        if streak["consecutive_losses"] >= 3:
            # Sum losses in current streak
            recent = list(self.win_rate._outcomes)
            streak_loss = sum(o[1] for o in reversed(recent) if not o[0])
            await self.alerts.emit_loss_streak(
                consecutive_losses=streak["consecutive_losses"],
                total_loss=streak_loss,
            )
        if streak["consecutive_wins"] >= 5:
            recent = list(self.win_rate._outcomes)
            streak_profit = sum(o[1] for o in reversed(recent) if o[0])
            await self.alerts.emit_win_streak(
                consecutive_wins=streak["consecutive_wins"],
                total_profit=streak_profit,
            )

    async def on_equity_update(
        self,
        equity: float,
        daily_pnl: float = 0.0,
        high_water_mark: float = 0.0,
    ) -> RiskStateSnapshot:
        """Handle an equity update — refresh equity curve and risk state.

        Call this periodically (e.g., every tick or every N seconds)
        to keep the equity curve and risk state current.

        Args:
            equity: Current portfolio equity.
            daily_pnl: Today's realized P&L.
            high_water_mark: Peak equity.

        Returns:
            The updated RiskStateSnapshot.
        """
        # Update equity curve
        self.equity.update(equity, daily_pnl)

        # Get risk state
        risk = await self.risk_state.get_snapshot(
            equity=equity,
            high_water_mark=high_water_mark or self.equity._high_water_mark,
            daily_pnl=daily_pnl,
        )

        # Check for circuit breaker transitions
        if risk.risk_level != self._last_risk_level:
            await self.alerts.emit_circuit_breaker(
                old_level=self._last_risk_level,
                new_level=risk.risk_level,
                drawdown_pct=risk.drawdown_pct,
                daily_pnl_pct=risk.daily_pnl_pct,
            )
            self._last_risk_level = risk.risk_level

        # Kill switch alert
        if risk.kill_switch_active:
            await self.alerts.emit_kill_switch(
                active=True,
                reason=risk.kill_switch_reason,
            )

        return risk

    def get_dashboard_summary(self) -> dict[str, Any]:
        """Get a summary of all monitoring data for dashboards.

        Returns:
            Dict with P&L, win rate, equity curve, and risk state summaries.
        """
        pnl = self.pnl.get_snapshot()
        wr = self.win_rate.get_snapshot()
        eq = self.equity.get_snapshot()

        return {
            "pnl": {
                "unrealized": pnl.unrealized_pnl,
                "realized_today": pnl.realized_pnl_today,
                "realized_week": pnl.realized_pnl_week,
                "realized_month": pnl.realized_pnl_month,
                "realized_total": pnl.realized_pnl_total,
                "total": pnl.total_pnl,
                "open_positions": len(pnl.open_positions),
            },
            "win_rate": {
                "overall": wr.overall_win_rate,
                "last_30": wr.win_rate_30,
                "last_50": wr.win_rate_50,
                "last_100": wr.win_rate_100,
                "profit_factor": wr.profit_factor,
                "expectancy": wr.expectancy,
                "total_trades": wr.total_trades,
            },
            "equity": {
                "current": eq.current_equity,
                "hwm": eq.high_water_mark,
                "drawdown_pct": eq.current_drawdown_pct,
                "max_drawdown_pct": eq.max_drawdown_pct,
                "sharpe": eq.sharpe_ratio,
                "sortino": eq.sortino_ratio,
                "calmar": eq.calmar_ratio,
            },
            "risk": {
                "level": self._last_risk_level,
                "streak": self.win_rate.get_streak_info(),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO datetime string, returning None on failure."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
