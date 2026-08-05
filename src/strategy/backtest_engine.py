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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from datetime import datetime

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
        min_notional: Minimum order notional value (Binance: 10 USDT).
        min_quantity: Minimum order quantity in base asset.
        min_price_tick: Minimum price tick size.
        use_micro_mode: Enable $10 capital mode with realistic constraints.
    """

    initial_capital: float = 100_000.0
    position_size_pct: float = 0.10
    commission_bps: float = 10.0
    slippage_bps: float = 5.0
    risk_free_rate: float = 0.04
    trading_days_per_year: int = 365
    max_open_positions: int = 1
    min_notional: float = 10.0  # Binance minimum notional
    min_quantity: float = 0.00001  # Minimum base asset quantity
    min_price_tick: float = 0.01  # Minimum price increment
    use_micro_mode: bool = False  # $10 capital mode

    @classmethod
    def micro_mode(cls, capital: float = 10.0) -> BacktestConfig:
        """Create config for $10 micro-capital backtesting.

        Models realistic Binance constraints:
        - $10 starting capital
        - 100% position allocation (can't diversify with $10)
        - 0.1% taker fee (Binance spot)
        - 0.05% slippage estimate
        - $10 minimum notional enforcement
        """
        return cls(
            initial_capital=capital,
            position_size_pct=1.0,  # Full allocation with $10
            commission_bps=10.0,  # Binance 0.1% taker fee
            slippage_bps=5.0,  # Conservative slippage
            risk_free_rate=0.04,
            trading_days_per_year=365,
            max_open_positions=1,  # Only 1 position with $10
            min_notional=10.0,  # Binance minimum
            min_quantity=0.00001,
            min_price_tick=0.01,
            use_micro_mode=True,
        )


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
                    pos = self._open_position(entry_signal, bar, i, capital)
                    if pos is not None:
                        open_position = pos

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

        Provides OHLCV fields plus computed technical indicators:
        EMA(21/55), RSI(14), ADX(14), ATR(14), Bollinger Bands(20,2),
        MACD(12,26,9), volume ratio, and a rolling window of closes.
        """
        # Rolling window of closes (up to 100 bars back)
        lookback = min(index + 1, 100)
        recent_closes = [ohlcv[index - j].close for j in range(lookback - 1, -1, -1)]

        # Highs and lows for ATR/ADX computation
        recent_highs = [ohlcv[index - j].high for j in range(lookback - 1, -1, -1)]
        recent_lows = [ohlcv[index - j].low for j in range(lookback - 1, -1, -1)]
        recent_volumes = [ohlcv[index - j].volume for j in range(lookback - 1, -1, -1)]

        # ── Compute indicators ──
        ema_fast = self._ema(recent_closes, 21)
        ema_slow = self._ema(recent_closes, 55)
        rsi = self._rsi(recent_closes, 14)
        atr = self._atr(recent_highs, recent_lows, recent_closes, 14)
        adx = self._adx(recent_highs, recent_lows, recent_closes, 14)
        bb_upper, bb_middle, bb_lower = self._bollinger(recent_closes, 20, 2.0)
        macd_line, macd_signal, macd_histogram = self._macd(recent_closes)

        # Previous MACD histogram for crossover detection
        if index >= 1:
            prev_closes = [ohlcv[index - 1 - j].close for j in range(min(index, 100) - 1, -1, -1)]
            _, _, macd_histogram_prev = self._macd(prev_closes)
        else:
            macd_histogram_prev = 0.0

        # Volume ratio: current / 20-period average
        vol_window = recent_volumes[-20:] if len(recent_volumes) >= 20 else recent_volumes
        avg_volume = sum(vol_window) / len(vol_window) if vol_window else 1.0
        volume_ratio = bar.volume / avg_volume if avg_volume > 0 else 1.0

        return {
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "timestamp": bar.timestamp,
            "bar_index": index,
            "closes": recent_closes,
            "ohlcv_recent": ohlcv[max(0, index - 99) : index + 1],
            # Indicators
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi": rsi,
            "adx": adx,
            "atr": atr,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "macd_line": macd_line,
            "macd_signal": macd_signal,
            "macd_histogram": macd_histogram,
            "macd_histogram_prev": macd_histogram_prev,
            "volume_ratio": volume_ratio,
        }

    # ── Technical indicator helpers ──────────────────────────

    @staticmethod
    def _ema(data: list[float], period: int) -> float:
        """Compute Exponential Moving Average."""
        if len(data) < period:
            return data[-1] if data else 0.0
        k = 2.0 / (period + 1)
        ema = sum(data[:period]) / period  # SMA seed
        for val in data[period:]:
            ema = val * k + ema * (1 - k)
        return ema

    @staticmethod
    def _rsi(closes: list[float], period: int = 14) -> float:
        """Compute Relative Strength Index."""
        if len(closes) < period + 1:
            return 50.0  # neutral when insufficient data
        gains = []
        losses = []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
        # Use EMA-style smoothing (Wilder's method)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
        """Compute Average True Range."""
        if len(closes) < 2:
            return 0.0
        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)
        if not true_ranges:
            return 0.0
        # Wilder's smoothing
        atr_val = sum(true_ranges[:period]) / min(period, len(true_ranges))
        for tr in true_ranges[period:]:
            atr_val = (atr_val * (period - 1) + tr) / period
        return atr_val

    @staticmethod
    def _adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
        """Compute Average Directional Index."""
        if len(closes) < period + 2:
            return 0.0
        plus_dm_list = []
        minus_dm_list = []
        true_ranges = []
        for i in range(1, len(closes)):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]
            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)
        if len(true_ranges) < period:
            return 0.0
        # Wilder's smoothing for TR, +DM, -DM
        atr_val = sum(true_ranges[:period]) / period
        plus_dm_smooth = sum(plus_dm_list[:period]) / period
        minus_dm_smooth = sum(minus_dm_list[:period]) / period
        dx_values = []
        for i in range(period, len(true_ranges)):
            atr_val = (atr_val * (period - 1) + true_ranges[i]) / period
            plus_dm_smooth = (plus_dm_smooth * (period - 1) + plus_dm_list[i]) / period
            minus_dm_smooth = (minus_dm_smooth * (period - 1) + minus_dm_list[i]) / period
            if atr_val > 0:
                plus_di = 100.0 * plus_dm_smooth / atr_val
                minus_di = 100.0 * minus_dm_smooth / atr_val
            else:
                plus_di = 0.0
                minus_di = 0.0
            di_sum = plus_di + minus_di
            dx = abs(plus_di - minus_di) / di_sum * 100.0 if di_sum > 0 else 0.0
            dx_values.append(dx)
        if not dx_values:
            return 0.0
        # ADX = smoothed DX
        adx_val = sum(dx_values[:period]) / min(period, len(dx_values))
        for dx in dx_values[period:]:
            adx_val = (adx_val * (period - 1) + dx) / period
        return adx_val

    @staticmethod
    def _bollinger(
        closes: list[float], period: int = 20, num_std: float = 2.0
    ) -> tuple[float, float, float]:
        """Compute Bollinger Bands (upper, middle, lower)."""
        window = closes[-period:] if len(closes) >= period else closes
        if not window:
            return 0.0, 0.0, 0.0
        middle = sum(window) / len(window)
        variance = sum((x - middle) ** 2 for x in window) / len(window)
        std = variance**0.5
        return middle + num_std * std, middle, middle - num_std * std

    @staticmethod
    def _macd(
        closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[float, float, float]:
        """Compute MACD (line, signal, histogram)."""
        if len(closes) < slow:
            return 0.0, 0.0, 0.0

        def _ema_series(data: list[float], period: int) -> list[float]:
            k = 2.0 / (period + 1)
            ema_vals = [sum(data[:period]) / period]
            for val in data[period:]:
                ema_vals.append(val * k + ema_vals[-1] * (1 - k))
            return ema_vals

        ema_fast_series = _ema_series(closes, fast)
        ema_slow_series = _ema_series(closes, slow)
        # Align: slow EMA starts later
        offset = slow - fast
        macd_line_series = [
            ema_fast_series[offset + i] - ema_slow_series[i] for i in range(len(ema_slow_series))
        ]
        if len(macd_line_series) < signal:
            return macd_line_series[-1] if macd_line_series else 0.0, 0.0, 0.0
        signal_series = _ema_series(macd_line_series, signal)
        macd_line_val = macd_line_series[-1]
        signal_val = signal_series[-1]
        histogram_val = macd_line_val - signal_val
        return macd_line_val, signal_val, histogram_val

    # ── Signal scanning (SignalScout equivalent) ─────────────

    def scan_signals(
        self,
        ohlcv: list[OHLCV],
        start_index: int = 0,
    ) -> list[dict[str, Any]]:
        """Scan for basic trading signals across the OHLCV data.

        Provides a SignalScout-equivalent for backtest context.
        Detects:
          - RSI oversold (< 30) / overbought (> 70)
          - EMA(21) / EMA(55) crossover (bullish and bearish)

        Args:
            ohlcv: Full OHLCV history.
            start_index: Bar index to start scanning from.

        Returns:
            List of signal dicts with type, side, score, bar_index.
        """
        signals: list[dict[str, Any]] = []
        for i in range(max(start_index, 55), len(ohlcv)):
            data = self._build_bar_data(ohlcv[i], ohlcv, i)
            rsi = data["rsi"]
            ema_fast = data["ema_fast"]
            ema_slow = data["ema_slow"]

            # RSI oversold → buy signal
            if rsi < 30:
                signals.append(
                    {
                        "type": "rsi_oversold",
                        "side": "buy",
                        "score": min(1.0, (30 - rsi) / 15),
                        "bar_index": i,
                        "price": data["close"],
                        "rsi": rsi,
                    }
                )

            # RSI overbought → sell signal
            if rsi > 70:
                signals.append(
                    {
                        "type": "rsi_overbought",
                        "side": "sell",
                        "score": min(1.0, (rsi - 70) / 15),
                        "bar_index": i,
                        "price": data["close"],
                        "rsi": rsi,
                    }
                )

            # EMA crossover detection
            if i >= 56:
                prev_data = self._build_bar_data(ohlcv[i - 1], ohlcv, i - 1)
                prev_fast = prev_data["ema_fast"]
                prev_slow = prev_data["ema_slow"]

                # Bullish crossover: fast crosses above slow
                if prev_fast <= prev_slow and ema_fast > ema_slow:
                    spread = (ema_fast - ema_slow) / ema_slow if ema_slow > 0 else 0
                    signals.append(
                        {
                            "type": "ema_bullish_crossover",
                            "side": "buy",
                            "score": min(1.0, spread * 50),
                            "bar_index": i,
                            "price": data["close"],
                            "ema_fast": ema_fast,
                            "ema_slow": ema_slow,
                        }
                    )

                # Bearish crossover: fast crosses below slow
                if prev_fast >= prev_slow and ema_fast < ema_slow:
                    spread = (ema_slow - ema_fast) / ema_slow if ema_slow > 0 else 0
                    signals.append(
                        {
                            "type": "ema_bearish_crossover",
                            "side": "sell",
                            "score": min(1.0, spread * 50),
                            "bar_index": i,
                            "price": data["close"],
                            "ema_fast": ema_fast,
                            "ema_slow": ema_slow,
                        }
                    )

        return signals

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
    ) -> _OpenPosition | None:
        """Open a new position from a strategy signal.

        Returns None if the position doesn't meet minimum constraints
        (e.g., notional below $10 for Binance).
        """
        entry_price_raw = signal.get("entry_price", bar.close)
        side = signal.get("side", "buy")
        entry_price = self._apply_slippage(entry_price_raw, side, is_entry=True)

        # Position sizing
        position_notional = capital * self._config.position_size_pct
        quantity = position_notional / entry_price if entry_price > 0 else 0.0

        # ── Minimum constraints (Binance realistic) ──
        config = self._config

        # Round quantity to min_quantity precision
        if config.min_quantity > 0:
            quantity = max(
                config.min_quantity,
                round(quantity / config.min_quantity) * config.min_quantity,
            )

        # Round price to tick size
        if config.min_price_tick > 0:
            entry_price = round(entry_price / config.min_price_tick) * config.min_price_tick

        # Check minimum notional
        actual_notional = quantity * entry_price
        if actual_notional < config.min_notional:
            logger.debug(
                "Position skipped: notional %.2f below minimum %.2f (qty=%.8f @ %.2f)",
                actual_notional,
                config.min_notional,
                quantity,
                entry_price,
            )
            return None

        # Check we have enough capital
        if actual_notional > capital * 1.01:  # 1% tolerance
            logger.debug(
                "Position skipped: notional %.2f exceeds capital %.2f",
                actual_notional,
                capital,
            )
            return None

        commission = self._apply_commission(actual_notional)

        # In micro mode, also account for minimum commission
        if config.use_micro_mode:
            # Binance minimum commission is typically 0.00000001 of quote
            commission = max(commission, 0.001)  # Minimum ~$0.001 commission

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

        # Win/loss stats — strictly positive = win, strictly negative = loss,
        # zero PnL trades are breakeven (excluded from win/loss counts).
        winners = [p for p in pnl_values if p > 0]
        losers = [p for p in pnl_values if p < 0]
        total_trades = len(trades)
        winning_trades = len(winners)
        losing_trades = len(losers)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        avg_win = float(np.mean(winners)) if winners else 0.0
        avg_loss = float(np.mean(losers)) if losers else 0.0

        # Profit factor — cap at 1000.0 to avoid inf when no losing trades
        gross_profit = sum(winners) if winners else 0.0
        gross_loss = abs(sum(losers)) if losers else 0.0
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else (1000.0 if gross_profit > 0 else 0.0)
        )

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
                sortino_ratio = 1000.0 if np.mean(excess) > 0 else 0.0
        else:
            sortino_ratio = 0.0

        # Max drawdown
        max_dd, max_dd_duration = self._compute_max_drawdown(equity_curve)

        # Calmar ratio
        calmar_ratio = cagr / abs(max_dd) if max_dd != 0 else (1000.0 if cagr > 0 else 0.0)

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

    # ── Walk-Forward / Train-Test Split (H-002) ─────────────

    def run_train_test_split(
        self,
        ohlcv: list[OHLCV],
        train_ratio: float = 0.70,
    ) -> dict[str, Any]:
        """Run backtest with train/test split for overfitting detection.

        Splits data into train (first train_ratio%) and test (remaining).
        Returns both in-sample and out-of-sample results for comparison.

        Args:
            ohlcv: Full historical OHLCV data.
            train_ratio: Fraction of data for training (default 0.70).

        Returns:
            Dict with 'train_result', 'test_result', 'overfit_score',
            'is_overfit', and 'degradation_pct'.
        """
        if len(ohlcv) < 10:
            raise ValueError(f"Need at least 10 bars for train/test split, got {len(ohlcv)}")

        split_idx = int(len(ohlcv) * train_ratio)
        split_idx = max(split_idx, 5)  # At least 5 bars in train
        split_idx = min(split_idx, len(ohlcv) - 5)  # At least 5 bars in test

        train_data = ohlcv[:split_idx]
        test_data = ohlcv[split_idx:]

        logger.info(
            "Train/test split: %d train bars, %d test bars (%.0f/%.0f)",
            len(train_data),
            len(test_data),
            train_ratio * 100,
            (1 - train_ratio) * 100,
        )

        # Run on train
        train_result = self.run(train_data)

        # Run on test (same strategy, same config — no re-optimization)
        test_result = self.run(test_data)

        # Compute overfitting score
        train_sharpe = train_result.metrics.sharpe_ratio
        test_sharpe = test_result.metrics.sharpe_ratio

        if test_sharpe <= 0:
            overfit_score = float("inf") if train_sharpe > 0 else 1.0
        else:
            overfit_score = abs(train_sharpe) / abs(test_sharpe)

        is_overfit = overfit_score > 3.0  # Default threshold

        # Performance degradation
        if train_result.metrics.total_return != 0:
            degradation_pct = (
                (train_result.metrics.total_return - test_result.metrics.total_return)
                / abs(train_result.metrics.total_return)
                * 100
            )
        else:
            degradation_pct = 0.0

        logger.info(
            "Train/test results: train_sharpe=%.2f test_sharpe=%.2f "
            "overfit_score=%.2f is_overfit=%s degradation=%.1f%%",
            train_sharpe,
            test_sharpe,
            overfit_score,
            is_overfit,
            degradation_pct,
        )

        return {
            "train_result": train_result,
            "test_result": test_result,
            "train_sharpe": train_sharpe,
            "test_sharpe": test_sharpe,
            "overfit_score": round(overfit_score, 4),
            "is_overfit": is_overfit,
            "degradation_pct": round(degradation_pct, 2),
            "train_bars": len(train_data),
            "test_bars": len(test_data),
        }
