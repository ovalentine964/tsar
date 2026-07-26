"""
Backtest Engine — Replay historical data through strategy rules.

Simulates trades by applying strategy entry/exit rules bar-by-bar
against historical OHLCV data. Computes performance metrics including
Sharpe ratio, win rate, profit factor, max drawdown, CAGR, and Calmar ratio.

Supports configurable commission and slippage models.

Usage::

    from src.strategy.backtest_engine import BacktestEngine, BacktestConfig
    from src.strategy.mean_reversion import MeanReversionStrategy

    engine = BacktestEngine(
        strategy=MeanReversionStrategy(),
        config=BacktestConfig(commission_bps=10, slippage_bps=5),
    )
    result = engine.run(ohlcv_data)
    print(result.metrics.sharpe_ratio)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from src.interfaces.types import OHLCV
from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BacktestConfig:
    """Configuration for a backtest run.

    Attributes:
        initial_capital: Starting capital in quote currency.
        position_size_pct: Fraction of capital to risk per trade (0.0-1.0).
        commission_bps: Commission in basis points per trade (one-way).
        slippage_bps: Slippage in basis points per trade (one-way).
        risk_free_rate: Annualized risk-free rate for Sharpe calculation.
        trading_days_per_year: Trading days per year for annualization.
        max_open_positions: Maximum concurrent open positions.
    """

    initial_capital: float = 100_000.0
    position_size_pct: float = 0.10
    commission_bps: float = 10.0
    slippage_bps: float = 5.0
    risk_free_rate: float = 0.04
    trading_days_per_year: int = 365
    max_open_positions: int = 1


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TradeRecord:
    """A completed round-trip trade from the backtest.

    Attributes:
        entry_time: Bar timestamp when position was opened.
        exit_time: Bar timestamp when position was closed.
        side: 'buy' (long) or 'sell' (short).
        entry_price: Price at entry (after slippage).
        exit_price: Price at exit (after slippage).
        quantity: Position size in base asset units.
        pnl: Realized profit/loss (net of commissions).
        pnl_pct: Return as a fraction of entry notional.
        commission_total: Total commissions paid (entry + exit).
        exit_reason: Why the position was closed.
    """

    entry_time: datetime
    exit_time: datetime
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    commission_total: float
    exit_reason: str


@dataclass(frozen=True)
class BacktestMetrics:
    """Computed performance metrics for a backtest.

    Attributes:
        total_return: Total return as a fraction (e.g. 0.15 = 15%).
        cagr: Compound Annual Growth Rate.
        sharpe_ratio: Annualized Sharpe ratio (excess return / volatility).
        sortino_ratio: Annualized Sortino ratio (downside deviation).
        calmar_ratio: CAGR / max drawdown.
        max_drawdown: Maximum peak-to-trough drawdown as a fraction.
        max_drawdown_duration: Longest drawdown duration in bars.
        win_rate: Fraction of winning trades.
        profit_factor: Gross profit / gross loss.
        avg_win: Average winning trade PnL.
        avg_loss: Average losing trade PnL.
        total_trades: Total number of completed trades.
        winning_trades: Number of winning trades.
        losing_trades: Number of losing trades.
        avg_trade_duration: Average trade duration in bars.
        expectancy: Expected value per trade (win_rate * avg_win - (1-win_rate) * abs(avg_loss)).
    """

    total_return: float
    cagr: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_trade_duration: float
    expectancy: float


@dataclass(frozen=True)
class BacktestResult:
    """Complete result of a backtest run.

    Attributes:
        trades: List of completed trades.
        metrics: Performance metrics.
        equity_curve: Portfolio equity at each bar.
        config: Backtest configuration used.
        strategy_name: Name of the strategy tested.
        start_time: Timestamp of first bar.
        end_time: Timestamp of last bar.
        bar_count: Total number of bars processed.
    """

    trades: tuple[TradeRecord, ...]
    metrics: BacktestMetrics
    equity_curve: tuple[float, ...]
    config: BacktestConfig
    strategy_name: str
    start_time: datetime
    end_time: datetime
    bar_count: int


# ═══════════════════════════════════════════════════════════════════════
# OPEN POSITION (internal tracking)
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class _OpenPosition:
    """Internal state for an open position during backtest simulation."""

    entry_time: datetime
    side: str  # 'buy' or 'sell'
    entry_price: float  # after slippage
    quantity: float
    commission_entry: float
    signal: dict[str, Any]
    bar_index: int  # bar number when opened


# ═══════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════════════


class BacktestEngine:
    """Replays historical OHLCV data through strategy rules to simulate trades.

    The engine iterates bar-by-bar, calling strategy.check_entry() to open
    positions and strategy.check_exit() to close them. Commission and slippage
    are applied at each fill.

    Args:
        strategy: The trading strategy to test.
        config: Backtest configuration (capital, fees, etc.).
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        config: BacktestConfig | None = None,
    ) -> None:
        self._strategy = strategy
        self._config = config or BacktestConfig()

    def run(self, ohlcv: list[OHLCV]) -> BacktestResult:
        """Run a backtest over historical OHLCV data.

        Args:
            ohlcv: List of OHLCV bars, oldest first. Must have at least 2 bars.

        Returns:
            BacktestResult with trades, metrics, and equity curve.

        Raises:
            ValueError: If ohlcv has fewer than 2 bars.
        """
        if len(ohlcv) < 2:
            raise ValueError(f"Need at least 2 OHLCV bars, got {len(ohlcv)}")

        config = self._config
        capital = config.initial_capital
        equity = capital
        equity_curve: list[float] = [equity]
        trades: list[TradeRecord] = []
        open_position: _OpenPosition | None = None

        for i in range(len(ohlcv)):
            bar = ohlcv[i]
            data = self._build_bar_data(bar, ohlcv, i)

            # ── Check exit first (if we have a position) ──
            if open_position is not None:
                exit_signal = self._check_exit(open_position, data)
                if exit_signal is not None:
                    trade = self._close_position(open_position, bar, exit_signal, capital)
                    trades.append(trade)
                    capital += trade.pnl
                    equity = capital
                    open_position = None

            # ── Check entry (only if no open position) ──
            if open_position is None and i < len(ohlcv) - 1:
                entry_signal = self._strategy.check_entry(data)
                if entry_signal is not None:
                    open_position = self._open_position(entry_signal, bar, i, capital)

            # ── Mark-to-market equity ──
            if open_position is not None:
                mtm_pnl = self._mark_to_market(open_position, bar.close)
                equity = capital + mtm_pnl
            else:
                equity = capital

            equity_curve.append(equity)

        # ── Force-close any remaining position at last bar ──
        if open_position is not None:
            last_bar = ohlcv[-1]
            exit_signal = {"reason": "end_of_data", "action": "close"}
            trade = self._close_position(open_position, last_bar, exit_signal, capital)
            trades.append(trade)
            capital += trade.pnl
            equity = capital
            equity_curve[-1] = equity

        # ── Compute metrics ──
        metrics = self._compute_metrics(trades, equity_curve)

        return BacktestResult(
            trades=tuple(trades),
            metrics=metrics,
            equity_curve=tuple(equity_curve),
            config=config,
            strategy_name=self._strategy.NAME,
            start_time=ohlcv[0].timestamp,
            end_time=ohlcv[-1].timestamp,
            bar_count=len(ohlcv),
        )

    # ── Private helpers ──────────────────────────────────────

    def _build_bar_data(
        self,
        bar: OHLCV,
        ohlcv: list[OHLCV],
        index: int,
    ) -> dict[str, Any]:
        """Build data dict for strategy entry/exit checks.

        Provides OHLCV fields plus a rolling window of recent closes
        for indicator calculations.
        """
        # Rolling window of closes (up to 100 bars back)
        lookback = min(index + 1, 100)
        recent_closes = [ohlcv[index - j].close for j in range(lookback - 1, -1, -1)]

        return {
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "timestamp": bar.timestamp,
            "bar_index": index,
            "closes": recent_closes,
            "ohlcv_recent": ohlcv[max(0, index - 99): index + 1],
        }

    def _apply_slippage(self, price: float, side: str, is_entry: bool) -> float:
        """Apply slippage to a price.

        Entry: buy pays more, sell receives less.
        Exit: buy-to-close receives less, sell-to-close pays more.
        """
        slippage_pct = self._config.slippage_bps / 10_000
        if (side == "buy" and is_entry) or (side == "sell" and not is_entry):
            return price * (1 + slippage_pct)
        else:
            return price * (1 - slippage_pct)

    def _apply_commission(self, notional: float) -> float:
        """Calculate commission for a trade."""
        return notional * (self._config.commission_bps / 10_000)

    def _open_position(
        self,
        signal: dict[str, Any],
        bar: OHLCV,
        bar_index: int,
        capital: float,
    ) -> _OpenPosition:
        """Open a new position from a strategy signal."""
        entry_price_raw = signal.get("entry_price", bar.close)
        side = signal.get("side", "buy")
        entry_price = self._apply_slippage(entry_price_raw, side, is_entry=True)

        # Position sizing
        position_notional = capital * self._config.position_size_pct
        quantity = position_notional / entry_price if entry_price > 0 else 0.0
        commission = self._apply_commission(position_notional)

        return _OpenPosition(
            entry_time=bar.timestamp,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            commission_entry=commission,
            signal=signal,
            bar_index=bar_index,
        )

    def _check_exit(
        self,
        position: _OpenPosition,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check exit conditions, including stop-loss and take-profit from signal."""
        # First check strategy exit rules
        pos_dict = {
            "entry_price": position.entry_price,
            "side": position.side,
            "entry_time": position.entry_time.isoformat(),
        }
        exit_signal = self._strategy.check_exit(pos_dict, data)
        if exit_signal is not None:
            return exit_signal

        # Check signal-level stop-loss and take-profit
        current_price = data.get("close", 0.0)
        sl = position.signal.get("stop_loss", 0.0)
        tp = position.signal.get("take_profit", 0.0)

        if position.side == "buy":
            if sl > 0 and current_price <= sl:
                return {"reason": "stop_loss", "action": "close"}
            if tp > 0 and current_price >= tp:
                return {"reason": "take_profit", "action": "close"}
        elif position.side == "sell":
            if sl > 0 and current_price >= sl:
                return {"reason": "stop_loss", "action": "close"}
            if tp > 0 and current_price <= tp:
                return {"reason": "take_profit", "action": "close"}

        return None

    def _close_position(
        self,
        position: _OpenPosition,
        bar: OHLCV,
        exit_signal: dict[str, Any],
        capital: float,
    ) -> TradeRecord:
        """Close a position and compute PnL."""
        exit_price_raw = bar.close
        exit_price = self._apply_slippage(exit_price_raw, position.side, is_entry=False)

        # PnL calculation
        if position.side == "buy":
            gross_pnl = (exit_price - position.entry_price) * position.quantity
        else:
            gross_pnl = (position.entry_price - exit_price) * position.quantity

        exit_notional = exit_price * position.quantity
        commission_exit = self._apply_commission(exit_notional)
        total_commission = position.commission_entry + commission_exit

        net_pnl = gross_pnl - total_commission
        entry_notional = position.entry_price * position.quantity
        pnl_pct = net_pnl / entry_notional if entry_notional > 0 else 0.0

        reason = exit_signal.get("reason", "unknown")

        return TradeRecord(
            entry_time=position.entry_time,
            exit_time=bar.timestamp,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            commission_total=total_commission,
            exit_reason=reason,
        )

    def _mark_to_market(self, position: _OpenPosition, current_price: float) -> float:
        """Calculate unrealized PnL for an open position."""
        if position.side == "buy":
            return (current_price - position.entry_price) * position.quantity
        else:
            return (position.entry_price - current_price) * position.quantity

    # ── Metrics computation ──────────────────────────────────

    def _compute_metrics(
        self,
        trades: list[TradeRecord],
        equity_curve: list[float],
    ) -> BacktestMetrics:
        """Compute all performance metrics from trade list and equity curve."""
        if not trades:
            return self._empty_metrics()

        config = self._config
        pnl_values = [t.pnl for t in trades]
        pnl_pcts = [t.pnl_pct for t in trades]

        # Win/loss stats
        winners = [p for p in pnl_values if p > 0]
        losers = [p for p in pnl_values if p <= 0]
        total_trades = len(trades)
        winning_trades = len(winners)
        losing_trades = len(losers)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        avg_win = float(np.mean(winners)) if winners else 0.0
        avg_loss = float(np.mean(losers)) if losers else 0.0

        # Profit factor
        gross_profit = sum(winners) if winners else 0.0
        gross_loss = abs(sum(losers)) if losers else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Expectancy
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * abs(avg_loss))

        # Total return
        initial = config.initial_capital
        final = equity_curve[-1] if equity_curve else initial
        total_return = (final - initial) / initial if initial > 0 else 0.0

        # CAGR
        n_bars = len(equity_curve) - 1
        if n_bars > 0 and final > 0 and initial > 0:
            years = n_bars / config.trading_days_per_year
            cagr = (final / initial) ** (1 / years) - 1 if years > 0 else 0.0
        else:
            cagr = 0.0

        # Returns series for Sharpe/Sortino
        eq = np.array(equity_curve, dtype=float)
        returns = np.diff(eq) / eq[:-1]
        returns = returns[np.isfinite(returns)]

        # Sharpe ratio (annualized)
        if len(returns) > 1 and np.std(returns) > 0:
            daily_rf = config.risk_free_rate / config.trading_days_per_year
            excess = returns - daily_rf
            sharpe_ratio = float(
                np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(config.trading_days_per_year)
            )
        else:
            sharpe_ratio = 0.0

        # Sortino ratio (annualized, downside deviation)
        if len(returns) > 1:
            daily_rf = config.risk_free_rate / config.trading_days_per_year
            excess = returns - daily_rf
            downside = excess[excess < 0]
            if len(downside) > 0:
                downside_dev = float(np.std(downside, ddof=1))
                if downside_dev > 0:
                    sortino_ratio = float(
                        np.mean(excess) / downside_dev * math.sqrt(config.trading_days_per_year)
                    )
                else:
                    sortino_ratio = 0.0
            else:
                sortino_ratio = float("inf") if np.mean(excess) > 0 else 0.0
        else:
            sortino_ratio = 0.0

        # Max drawdown
        max_dd, max_dd_duration = self._compute_max_drawdown(equity_curve)

        # Calmar ratio
        calmar_ratio = cagr / abs(max_dd) if max_dd != 0 else float("inf")

        # Average trade duration in bars
        durations = []
        for t in trades:
            delta = (t.exit_time - t.entry_time).total_seconds()
            # Convert to bar count approximation (assume uniform bars)
            durations.append(delta)
        avg_duration_bars = float(np.mean(durations)) / 3600 if durations else 0.0  # hours

        return BacktestMetrics(
            total_return=round(total_return, 6),
            cagr=round(cagr, 6),
            sharpe_ratio=round(sharpe_ratio, 4),
            sortino_ratio=round(sortino_ratio, 4),
            calmar_ratio=round(calmar_ratio, 4),
            max_drawdown=round(max_dd, 6),
            max_drawdown_duration=max_dd_duration,
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 4),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            avg_trade_duration=round(avg_duration_bars, 2),
            expectancy=round(expectancy, 2),
        )

    @staticmethod
    def _compute_max_drawdown(equity_curve: list[float]) -> tuple[float, int]:
        """Compute maximum drawdown and its duration in bars.

        Returns:
            (max_drawdown_fraction, max_drawdown_duration_bars)
        """
        if len(equity_curve) < 2:
            return 0.0, 0

        peak = equity_curve[0]
        max_dd = 0.0
        current_dd_start = 0
        max_dd_duration = 0
        in_drawdown = False
        dd_start_idx = 0

        for i, eq in enumerate(equity_curve):
            if eq >= peak:
                peak = eq
                if in_drawdown:
                    duration = i - dd_start_idx
                    max_dd_duration = max(max_dd_duration, duration)
                    in_drawdown = False
            else:
                dd = (peak - eq) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
                if not in_drawdown:
                    dd_start_idx = i
                    in_drawdown = True

        # Handle ongoing drawdown at end
        if in_drawdown:
            duration = len(equity_curve) - 1 - dd_start_idx
            max_dd_duration = max(max_dd_duration, duration)

        return max_dd, max_dd_duration

    @staticmethod
    def _empty_metrics() -> BacktestMetrics:
        """Return zeroed metrics when there are no trades."""
        return BacktestMetrics(
            total_return=0.0,
            cagr=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            calmar_ratio=0.0,
            max_drawdown=0.0,
            max_drawdown_duration=0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            avg_trade_duration=0.0,
            expectancy=0.0,
        )
