"""
TSAR Domain Tools — Backtesting Tools.

What the agent LEARNS FROM. Provides comprehensive strategy evaluation
infrastructure for crypto trading strategies.

Tools:
  1. Strategy Backtester     — Historical simulation with realistic fees/slippage
  2. Walk-Forward Validation — Rolling window train/test to detect overfitting
  3. Monte Carlo Simulation  — Bootstrap resampling for confidence intervals
  4. Performance Metrics     — Sharpe, Sortino, max drawdown, win rate, profit factor
  5. Factor Analysis         — IC, IR, factor exposure decomposition
  6. Regime-Conditional BT   — Performance broken down by market regime

All tools are deterministic — no LLM, no external calls.
Operates on numpy arrays and pandas DataFrames.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════


class MarketRegime(StrEnum):
    """Detected market regimes."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TradeRecord:
    """A single simulated trade from backtesting.

    Attributes:
        entry_time: Bar index or timestamp of entry.
        exit_time: Bar index or timestamp of exit.
        side: Trade direction — 'long' or 'short'.
        entry_price: Fill price at entry (after slippage).
        exit_price: Fill price at exit (after slippage).
        quantity: Position size in base asset.
        pnl: Realized profit/loss in quote currency.
        pnl_pct: Realized return as a fraction.
        fees_paid: Total fees paid (entry + exit).
        slippage_cost: Estimated slippage cost in quote currency.
    """

    entry_time: Any
    exit_time: Any
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fees_paid: float = 0.0
    slippage_cost: float = 0.0


@dataclass(frozen=True)
class BacktestResult:
    """Complete result from a strategy backtest.

    Attributes:
        trades: List of individual trade records.
        equity_curve: Portfolio equity at each bar.
        returns: Per-period returns.
        total_return: Total return as a fraction.
        annualized_return: Annualized return as a fraction.
        max_drawdown: Maximum drawdown as a fraction.
        sharpe_ratio: Annualized Sharpe ratio.
        sortino_ratio: Annualized Sortino ratio.
        win_rate: Fraction of winning trades.
        profit_factor: Gross profit / gross loss.
        total_trades: Number of completed trades.
        total_fees: Total fees paid across all trades.
        total_slippage: Total slippage cost.
        avg_trade_duration: Average bars per trade.
        longest_win_streak: Consecutive winning trades.
        longest_loss_streak: Consecutive losing trades.
        timestamp: When the backtest was run.
    """

    trades: list[TradeRecord]
    equity_curve: list[float]
    returns: list[float]
    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    avg_trade_duration: float = 0.0
    longest_win_streak: int = 0
    longest_loss_streak: int = 0
    timestamp: float | None = None


@dataclass(frozen=True)
class WalkForwardResult:
    """Walk-forward validation result.

    Attributes:
        in_sample_metrics: Performance metrics for each in-sample window.
        out_of_sample_metrics: Performance metrics for each out-of-sample window.
        combined_oos_equity: Stitched out-of-sample equity curve.
        combined_oos_return: Total return across all OOS windows.
        combined_oos_sharpe: Sharpe ratio of stitched OOS returns.
        combined_oos_max_drawdown: Max drawdown of stitched OOS returns.
        avg_is_sharpe: Average in-sample Sharpe.
        avg_oos_sharpe: Average out-of-sample Sharpe.
        oos_degradation: (IS_sharpe - OOS_sharpe) / IS_sharpe — overfitting indicator.
        num_folds: Number of walk-forward folds.
        stability_score: Consistency of OOS performance (0–1).
    """

    in_sample_metrics: list[dict[str, float]]
    out_of_sample_metrics: list[dict[str, float]]
    combined_oos_equity: list[float]
    combined_oos_return: float = 0.0
    combined_oos_sharpe: float = 0.0
    combined_oos_max_drawdown: float = 0.0
    avg_is_sharpe: float = 0.0
    avg_oos_sharpe: float = 0.0
    oos_degradation: float = 0.0
    num_folds: int = 0
    stability_score: float = 0.0


@dataclass(frozen=True)
class MonteCarloResult:
    """Monte Carlo simulation result.

    Attributes:
        median_equity: Median final equity across simulations.
        mean_equity: Mean final equity.
        p5_equity: 5th percentile final equity.
        p95_equity: 95th percentile final equity.
        p1_equity: 1st percentile final equity (worst case).
        p99_equity: 99th percentile final equity.
        median_max_drawdown: Median max drawdown across sims.
        p95_max_drawdown: 95th percentile max drawdown (worst drawdown).
        median_sharpe: Median Sharpe ratio.
        p5_sharpe: 5th percentile Sharpe.
        p95_sharpe: 95th percentile Sharpe.
        ruin_probability: Probability of losing >50% of capital.
        num_simulations: Number of bootstrap simulations.
        confidence_intervals: Full CI dict for key metrics.
    """

    median_equity: float = 0.0
    mean_equity: float = 0.0
    p5_equity: float = 0.0
    p95_equity: float = 0.0
    p1_equity: float = 0.0
    p99_equity: float = 0.0
    median_max_drawdown: float = 0.0
    p95_max_drawdown: float = 0.0
    median_sharpe: float = 0.0
    p5_sharpe: float = 0.0
    p95_sharpe: float = 0.0
    ruin_probability: float = 0.0
    num_simulations: int = 0
    confidence_intervals: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class PerformanceMetrics:
    """Comprehensive performance metrics for a strategy.

    Attributes:
        total_return: Total return fraction.
        annualized_return: Annualized return fraction.
        volatility: Annualized volatility.
        sharpe_ratio: Annualized Sharpe ratio.
        sortino_ratio: Annualized Sortino ratio.
        calmar_ratio: Annualized return / max drawdown.
        max_drawdown: Maximum drawdown fraction.
        max_drawdown_duration: Bars spent in max drawdown.
        win_rate: Fraction of positive-return periods.
        profit_factor: Gross profit / gross loss.
        avg_win: Average winning trade return.
        avg_loss: Average losing trade return.
        expectancy: Win_rate * avg_win - (1 - win_rate) * avg_loss.
        avg_holding_period: Average bars per trade.
        total_trades: Number of trades.
        payoff_ratio: avg_win / |avg_loss|.
        tail_ratio: p95_return / |p5_return|.
        skewness: Return distribution skewness.
        kurtosis: Return distribution excess kurtosis.
    """

    total_return: float = 0.0
    annualized_return: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    avg_holding_period: float = 0.0
    total_trades: int = 0
    payoff_ratio: float = 0.0
    tail_ratio: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0


@dataclass(frozen=True)
class FactorExposure:
    """Single factor's exposure and contribution.

    Attributes:
        factor_name: Name of the factor.
        beta: Regression coefficient (exposure).
        t_stat: T-statistic of the beta.
        p_value: P-value of the beta.
        r_squared: R² contribution of this factor.
        partial_correlation: Partial correlation with returns.
    """

    factor_name: str
    beta: float = 0.0
    t_stat: float = 0.0
    p_value: float = 1.0
    r_squared: float = 0.0
    partial_correlation: float = 0.0


@dataclass(frozen=True)
class FactorAnalysisResult:
    """Factor analysis result.

    Attributes:
        ic: Information Coefficient (Spearman rank correlation of factor vs returns).
        ic_mean: Mean IC across rolling windows.
        ic_std: Standard deviation of IC.
        ir: Information Ratio (IC_mean / IC_std).
        ic_series: Rolling IC values.
        factor_exposures: Exposure to each factor.
        alpha: Strategy alpha (intercept).
        alpha_t_stat: T-statistic of alpha.
        r_squared: Overall model R².
        factor_names: Names of factors analyzed.
    """

    ic: float = 0.0
    ic_mean: float = 0.0
    ic_std: float = 0.0
    ir: float = 0.0
    ic_series: list[float] = field(default_factory=list)
    factor_exposures: list[FactorExposure] = field(default_factory=list)
    alpha: float = 0.0
    alpha_t_stat: float = 0.0
    r_squared: float = 0.0
    factor_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegimePerformance:
    """Performance metrics within a single regime.

    Attributes:
        regime: The market regime.
        total_return: Total return fraction during regime.
        annualized_return: Annualized return.
        sharpe_ratio: Sharpe ratio during regime.
        sortino_ratio: Sortino ratio during regime.
        max_drawdown: Max drawdown during regime.
        win_rate: Win rate during regime.
        profit_factor: Profit factor during regime.
        total_trades: Number of trades during regime.
        total_bars: Number of bars in this regime.
        avg_bar_return: Average per-bar return.
        volatility: Annualized volatility during regime.
        pct_of_total_time: Fraction of total time in this regime.
    """

    regime: str
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    total_bars: int = 0
    avg_bar_return: float = 0.0
    volatility: float = 0.0
    pct_of_total_time: float = 0.0


@dataclass(frozen=True)
class RegimeConditionalBacktestResult:
    """Regime-conditional backtest result.

    Attributes:
        regime_performance: Performance metrics per regime.
        regime_transitions: Count of transitions between regimes.
        regime_sequence: Ordered list of detected regimes.
        best_regime: Regime with highest Sharpe.
        worst_regime: Regime with lowest Sharpe.
        regime_adaptability: How much returns vary across regimes (0–1).
        total_bars: Total bars analyzed.
        regime_detection_method: Method used for regime detection.
    """

    regime_performance: dict[str, RegimePerformance]
    regime_transitions: dict[str, dict[str, int]]
    regime_sequence: list[str]
    best_regime: str = ""
    worst_regime: str = ""
    regime_adaptability: float = 0.0
    total_bars: int = 0
    regime_detection_method: str = "hmm"


# ═══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════


def _compute_sharpe(
    returns: np.ndarray, risk_free_rate: float = 0.0, periods_per_year: int = 365
) -> float:
    """Annualized Sharpe ratio from a return series."""
    if len(returns) < 2:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period
    std = float(np.std(excess, ddof=1))
    if std == 0:
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(periods_per_year))


def _compute_sortino(
    returns: np.ndarray, risk_free_rate: float = 0.0, periods_per_year: int = 365
) -> float:
    """Annualized Sortino ratio from a return series."""
    if len(returns) < 2:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf") if np.mean(excess) > 0 else 0.0
    downside_dev = float(np.std(downside, ddof=1))
    if downside_dev == 0:
        return float("inf") if np.mean(excess) > 0 else 0.0
    return float(np.mean(excess) / downside_dev * math.sqrt(periods_per_year))


def _compute_max_drawdown(equity: np.ndarray) -> float:
    """Maximum drawdown from an equity curve."""
    if len(equity) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / np.where(peak > 0, peak, 1.0)
    return float(np.max(dd))


def _compute_max_drawdown_duration(equity: np.ndarray) -> int:
    """Longest drawdown duration in bars."""
    if len(equity) < 2:
        return 0
    peak = np.maximum.accumulate(equity)
    in_dd = equity < peak
    max_dur = 0
    current_dur = 0
    for dd_flag in in_dd:
        if dd_flag:
            current_dur += 1
            max_dur = max(max_dur, current_dur)
        else:
            current_dur = 0
    return max_dur


def _apply_slippage(price: float, side: str, slippage_bps: float) -> float:
    """Apply slippage to a fill price."""
    slip = price * slippage_bps / 10_000
    if side == "long":
        return price + slip  # Buy higher
    return price - slip  # Sell lower


def _compute_fees(notional: float, fee_rate: float) -> float:
    """Compute trading fees for a notional value."""
    return notional * fee_rate


def _streak_count(wins: list[bool]) -> tuple[int, int]:
    """Compute longest win and loss streaks."""
    longest_win = 0
    longest_loss = 0
    current_win = 0
    current_loss = 0
    for w in wins:
        if w:
            current_win += 1
            current_loss = 0
            longest_win = max(longest_win, current_win)
        else:
            current_loss += 1
            current_win = 0
            longest_loss = max(longest_loss, current_loss)
    return longest_win, longest_loss


# ═══════════════════════════════════════════════════════════════════════
# BACKTESTING TOOLS
# ═══════════════════════════════════════════════════════════════════════


class BacktestingTools:
    """TSAR backtesting tools — strategy evaluation and learning.

    Provides 6 tools for comprehensive strategy analysis:
    1. Strategy Backtester — Historical simulation with realistic costs
    2. Walk-Forward Validation — Rolling train/test for overfitting detection
    3. Monte Carlo Simulation — Bootstrap resampling with confidence intervals
    4. Performance Metrics — Full suite of risk/return metrics
    5. Factor Analysis — IC, IR, factor exposure decomposition
    6. Regime-Conditional Backtest — Performance by market regime
    """

    description = (
        "Backtesting: strategy simulation, walk-forward validation, "
        "Monte Carlo, performance metrics, factor analysis, regime-conditional"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    # ──────────────────────────────────────────────────────────────────
    # 1. Strategy Backtester
    # ──────────────────────────────────────────────────────────────────

    def run_backtest(
        self,
        ohlcv: pd.DataFrame,
        signals: pd.Series,
        initial_capital: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage_bps: float = 5.0,
        position_size_pct: float = 1.0,
        risk_free_rate: float = 0.0,
        trading_days_per_year: int = 365,
    ) -> BacktestResult:
        """Run a historical strategy backtest with realistic costs.

        Simulates trade execution on OHLCV data given a signal series.
        Positive signal = long, negative = short, zero = flat.
        Signals are interpreted on the NEXT bar's open (no look-ahead).

        Args:
            ohlcv: DataFrame with columns [open, high, low, close, volume].
                Index should be datetime-like or integer.
            signals: Series of signal values aligned with ohlcv index.
                Positive → long, negative → short, magnitude → conviction.
                Clamped to [-1, 1]. Signal at bar i is executed at bar i+1.
            initial_capital: Starting capital in quote currency.
            fee_rate: Trading fee as a fraction (0.001 = 10 bps).
            slippage_bps: Slippage in basis points per trade.
            position_size_pct: Position size as fraction of capital (0–1).
            risk_free_rate: Annualized risk-free rate for Sharpe calculation.
            trading_days_per_year: Trading days per year for annualization.

        Returns:
            BacktestResult with full trade log, equity curve, and metrics.

        Raises:
            ValueError: If ohlcv and signals have different lengths.
        """
        if len(ohlcv) != len(signals):
            raise ValueError(f"ohlcv ({len(ohlcv)}) and signals ({len(signals)}) length mismatch")

        n = len(ohlcv)
        if n < 2:
            return BacktestResult(
                trades=[],
                equity_curve=[initial_capital],
                returns=[],
                timestamp=pd.Timestamp.now().timestamp(),
            )

        opens = ohlcv["open"].values.astype(float)
        closes = ohlcv["close"].values.astype(float)

        # Clamp signals to [-1, 1]
        sig = signals.values.astype(float)
        sig = np.clip(sig, -1.0, 1.0)

        # ── Simulate ──────────────────────────────────────────────
        capital = initial_capital
        position = 0.0  # Current position in base asset
        current_side = 0  # +1 long, -1 short, 0 flat
        entry_price = 0.0
        entry_time = None
        entry_fees = 0.0
        entry_slip = 0.0

        equity_curve = [initial_capital]
        returns = []
        trades: list[TradeRecord] = []
        total_fees = 0.0
        total_slippage = 0.0

        for i in range(1, n):
            target_side = 1 if sig[i - 1] > 0 else (-1 if sig[i - 1] < 0 else 0)
            exec_price = opens[i]

            # Close existing position if direction changes or goes flat
            if current_side != 0 and (target_side != current_side or target_side == 0):
                exit_price = _apply_slippage(
                    exec_price, "short" if current_side == 1 else "long", slippage_bps
                )
                exit_notional = abs(position) * exit_price
                exit_fee = _compute_fees(exit_notional, fee_rate)
                exit_slip = abs(exit_price - exec_price) * abs(position)

                if current_side == 1:
                    pnl = (exit_price - entry_price) * abs(position) - entry_fees - exit_fee
                else:
                    pnl = (entry_price - exit_price) * abs(position) - entry_fees - exit_fee

                pnl_pct = (
                    pnl / (entry_price * abs(position))
                    if entry_price > 0 and abs(position) > 0
                    else 0.0
                )
                capital += pnl + entry_fees + exit_fee  # Return capital + pnl minus fees
                total_fees += entry_fees + exit_fee
                total_slippage += entry_slip + exit_slip

                trades.append(
                    TradeRecord(
                        entry_time=entry_time,
                        exit_time=i,
                        side="long" if current_side == 1 else "short",
                        entry_price=entry_price,
                        exit_price=exit_price,
                        quantity=abs(position),
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        fees_paid=entry_fees + exit_fee,
                        slippage_cost=entry_slip + exit_slip,
                    )
                )

                position = 0.0
                current_side = 0

            # Open new position if signal says so
            if target_side != 0 and current_side == 0:
                alloc = capital * position_size_pct
                entry_fill = _apply_slippage(
                    exec_price, "long" if target_side == 1 else "short", slippage_bps
                )
                position = alloc / entry_fill if entry_fill > 0 else 0.0
                entry_fee = _compute_fees(alloc, fee_rate)
                entry_slip = abs(entry_fill - exec_price) * position

                entry_price = entry_fill
                entry_time = i
                entry_fees = entry_fee
                current_side = target_side
                capital -= alloc  # Capital deployed into position

            # Mark-to-market equity
            if current_side != 0 and position > 0:
                mtm = capital + position * closes[i]
                if current_side == -1:
                    # Short: capital + (entry_value - current_value + capital_deployed)
                    mtm = capital + position * (2 * entry_price - closes[i])
                equity_curve.append(mtm)
            else:
                equity_curve.append(capital)

            # Period return
            prev_eq = equity_curve[-2]
            ret = (equity_curve[-1] - prev_eq) / prev_eq if prev_eq > 0 else 0.0
            returns.append(ret)

        # Close any remaining position at last close
        if current_side != 0 and position > 0:
            last_close = closes[-1]
            exit_price = _apply_slippage(
                last_close, "short" if current_side == 1 else "long", slippage_bps
            )
            exit_fee = _compute_fees(abs(position) * exit_price, fee_rate)
            exit_slip = abs(exit_price - last_close) * abs(position)

            if current_side == 1:
                pnl = (exit_price - entry_price) * position - entry_fees - exit_fee
            else:
                pnl = (entry_price - exit_price) * position - entry_fees - exit_fee

            pnl_pct = pnl / (entry_price * position) if entry_price > 0 and position > 0 else 0.0
            capital += pnl + entry_fees + exit_fee
            total_fees += entry_fees + exit_fee
            total_slippage += entry_slip + exit_slip

            trades.append(
                TradeRecord(
                    entry_time=entry_time,
                    exit_time=n - 1,
                    side="long" if current_side == 1 else "short",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=position,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    fees_paid=entry_fees + exit_fee,
                    slippage_cost=entry_slip + exit_slip,
                )
            )
            equity_curve[-1] = capital

        # ── Compute metrics ───────────────────────────────────────
        eq = np.array(equity_curve, dtype=float)
        ret_arr = np.array(returns, dtype=float) if returns else np.array([0.0])

        total_ret = (eq[-1] - eq[0]) / eq[0] if eq[0] > 0 else 0.0
        years = len(ret_arr) / trading_days_per_year
        ann_ret = ((1 + total_ret) ** (1 / years) - 1) if years > 0 else 0.0

        win_streak, loss_streak = _streak_count([t.pnl > 0 for t in trades])
        avg_duration = np.mean([t.exit_time - t.entry_time for t in trades]) if trades else 0.0

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            returns=list(ret_arr),
            total_return=round(total_ret * 100, 4),
            annualized_return=round(ann_ret * 100, 4),
            max_drawdown=round(_compute_max_drawdown(eq) * 100, 4),
            sharpe_ratio=round(_compute_sharpe(ret_arr, risk_free_rate, trading_days_per_year), 4),
            sortino_ratio=round(_compute_sortino(ret_arr, risk_free_rate, trading_days_per_year), 4)
            if _compute_sortino(ret_arr, risk_free_rate, trading_days_per_year) != float("inf")
            else 999.99,
            win_rate=round(sum(1 for t in trades if t.pnl > 0) / len(trades) * 100, 2)
            if trades
            else 0.0,
            profit_factor=round(
                sum(t.pnl for t in trades if t.pnl > 0)
                / abs(sum(t.pnl for t in trades if t.pnl < 0)),
                2,
            )
            if any(t.pnl < 0 for t in trades)
            else 999.99,
            total_trades=len(trades),
            total_fees=round(total_fees, 4),
            total_slippage=round(total_slippage, 4),
            avg_trade_duration=round(float(avg_duration), 2),
            longest_win_streak=win_streak,
            longest_loss_streak=loss_streak,
            timestamp=pd.Timestamp.now().timestamp(),
        )

    # ──────────────────────────────────────────────────────────────────
    # 2. Walk-Forward Validation
    # ──────────────────────────────────────────────────────────────────

    def walk_forward_validate(
        self,
        ohlcv: pd.DataFrame,
        signal_func: Any,
        in_sample_pct: float = 0.7,
        n_splits: int = 5,
        initial_capital: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage_bps: float = 5.0,
        position_size_pct: float = 1.0,
        risk_free_rate: float = 0.0,
        trading_days_per_year: int = 365,
    ) -> WalkForwardResult:
        """Walk-forward validation with rolling train/test windows.

        Splits data into n_splits rolling windows. For each window,
        the first in_sample_pct is used for training (parameter optimization)
        and the remainder for out-of-sample testing. This detects overfitting
        by comparing in-sample vs out-of-sample performance.

        Args:
            ohlcv: Full OHLCV DataFrame.
            signal_func: Callable(ohlcv_subset) -> signals_series.
                Given a subset of OHLCV data, returns signal Series.
            in_sample_pct: Fraction of each window used for in-sample.
            n_splits: Number of walk-forward folds.
            initial_capital: Starting capital per fold.
            fee_rate: Trading fee fraction.
            slippage_bps: Slippage in basis points.
            position_size_pct: Position size fraction.
            risk_free_rate: Annualized risk-free rate.
            trading_days_per_year: Trading days per year.

        Returns:
            WalkForwardResult with per-fold and combined OOS metrics.
        """
        n = len(ohlcv)
        if n < 10 or n_splits < 2:
            return WalkForwardResult(
                in_sample_metrics=[],
                out_of_sample_metrics=[],
                combined_oos_equity=[initial_capital],
                num_folds=0,
            )

        # Calculate window sizes
        window_size = n // n_splits
        is_size = int(window_size * in_sample_pct)
        oos_size = window_size - is_size

        if is_size < 5 or oos_size < 3:
            return WalkForwardResult(
                in_sample_metrics=[],
                out_of_sample_metrics=[],
                combined_oos_equity=[initial_capital],
                num_folds=0,
            )

        is_metrics_list: list[dict[str, float]] = []
        oos_metrics_list: list[dict[str, float]] = []
        combined_oos_equity = [initial_capital]
        combined_oos_returns: list[float] = []

        for fold in range(n_splits):
            start = fold * window_size
            is_end = start + is_size
            oos_end = min(is_end + oos_size, n)

            if oos_end <= is_end:
                continue

            # In-sample
            is_data = ohlcv.iloc[start:is_end].reset_index(drop=True)
            is_signals = signal_func(is_data)
            is_result = self.run_backtest(
                is_data,
                is_signals,
                initial_capital,
                fee_rate,
                slippage_bps,
                position_size_pct,
                risk_free_rate,
                trading_days_per_year,
            )
            is_metrics_list.append(
                {
                    "total_return": is_result.total_return,
                    "sharpe_ratio": is_result.sharpe_ratio,
                    "max_drawdown": is_result.max_drawdown,
                    "win_rate": is_result.win_rate,
                    "total_trades": float(is_result.total_trades),
                }
            )

            # Out-of-sample
            oos_data = ohlcv.iloc[is_end:oos_end].reset_index(drop=True)
            oos_signals = signal_func(oos_data)
            oos_result = self.run_backtest(
                oos_data,
                oos_signals,
                initial_capital,
                fee_rate,
                slippage_bps,
                position_size_pct,
                risk_free_rate,
                trading_days_per_year,
            )
            oos_metrics_list.append(
                {
                    "total_return": oos_result.total_return,
                    "sharpe_ratio": oos_result.sharpe_ratio,
                    "max_drawdown": oos_result.max_drawdown,
                    "win_rate": oos_result.win_rate,
                    "total_trades": float(oos_result.total_trades),
                }
            )

            # Stitch OOS equity
            scale = (
                combined_oos_equity[-1] / oos_result.equity_curve[0]
                if oos_result.equity_curve[0] > 0
                else 1.0
            )
            for eq_val in oos_result.equity_curve[1:]:
                combined_oos_equity.append(eq_val * scale)
            combined_oos_returns.extend(oos_result.returns)

        # Compute combined metrics
        oos_eq = np.array(combined_oos_equity, dtype=float)
        oos_ret = (
            np.array(combined_oos_returns, dtype=float) if combined_oos_returns else np.array([0.0])
        )

        oos_total = (oos_eq[-1] - oos_eq[0]) / oos_eq[0] if oos_eq[0] > 0 else 0.0
        oos_sharpe = _compute_sharpe(oos_ret)
        oos_mdd = _compute_max_drawdown(oos_eq)

        avg_is_sharpe = (
            float(np.mean([m["sharpe_ratio"] for m in is_metrics_list])) if is_metrics_list else 0.0
        )
        avg_oos_sharpe = (
            float(np.mean([m["sharpe_ratio"] for m in oos_metrics_list]))
            if oos_metrics_list
            else 0.0
        )
        degradation = (
            (avg_is_sharpe - avg_oos_sharpe) / abs(avg_is_sharpe) if avg_is_sharpe != 0 else 0.0
        )

        # Stability score: inverse CV of OOS returns across folds
        oos_fold_returns = [m["total_return"] for m in oos_metrics_list]
        if len(oos_fold_returns) > 1 and np.std(oos_fold_returns) > 0:
            cv = (
                abs(np.std(oos_fold_returns) / np.mean(oos_fold_returns))
                if np.mean(oos_fold_returns) != 0
                else 999.0
            )
            stability = max(0.0, 1.0 - cv)
        else:
            stability = 0.0

        return WalkForwardResult(
            in_sample_metrics=is_metrics_list,
            out_of_sample_metrics=oos_metrics_list,
            combined_oos_equity=combined_oos_equity,
            combined_oos_return=round(oos_total * 100, 4),
            combined_oos_sharpe=round(oos_sharpe, 4),
            combined_oos_max_drawdown=round(oos_mdd * 100, 4),
            avg_is_sharpe=round(avg_is_sharpe, 4),
            avg_oos_sharpe=round(avg_oos_sharpe, 4),
            oos_degradation=round(degradation * 100, 2),
            num_folds=len(oos_metrics_list),
            stability_score=round(stability, 4),
        )

    # ──────────────────────────────────────────────────────────────────
    # 3. Monte Carlo Simulation
    # ──────────────────────────────────────────────────────────────────

    def monte_carlo_simulation(
        self,
        returns: list[float] | np.ndarray,
        num_simulations: int = 10_000,
        simulation_length: int | None = None,
        initial_capital: float = 10_000.0,
        risk_free_rate: float = 0.0,
        trading_days_per_year: int = 365,
        seed: int | None = None,
    ) -> MonteCarloResult:
        """Monte Carlo simulation via bootstrap resampling of returns.

        Randomly resamples historical returns (with replacement) to build
        thousands of simulated equity paths. Provides confidence intervals
        for key metrics and estimates ruin probability.

        Args:
            returns: Historical return series (fractions, not percentages).
            num_simulations: Number of bootstrap simulations.
            simulation_length: Length of each simulation in bars.
                Defaults to len(returns).
            initial_capital: Starting capital.
            risk_free_rate: Annualized risk-free rate.
            trading_days_per_year: Trading days per year.
            seed: Random seed for reproducibility.

        Returns:
            MonteCarloResult with confidence intervals for key metrics.
        """
        ret_arr = np.array(returns, dtype=float)
        ret_arr = ret_arr[np.isfinite(ret_arr)]

        if len(ret_arr) < 5:
            return MonteCarloResult(num_simulations=0)

        sim_len = simulation_length or len(ret_arr)
        rng = np.random.default_rng(seed)

        final_equities = np.zeros(num_simulations)
        max_drawdowns = np.zeros(num_simulations)
        sharpes = np.zeros(num_simulations)

        for i in range(num_simulations):
            sampled = rng.choice(ret_arr, size=sim_len, replace=True)
            equity = initial_capital * np.cumprod(1 + sampled)
            final_equities[i] = equity[-1]
            max_drawdowns[i] = _compute_max_drawdown(equity)
            sharpes[i] = _compute_sharpe(sampled, risk_free_rate, trading_days_per_year)

        # Ruin probability: losing > 50% of capital
        ruin_prob = float(np.mean(final_equities < initial_capital * 0.5))

        # Confidence intervals
        pcts = [1, 5, 25, 50, 75, 95, 99]
        ci_equity = {f"p{p}": float(np.percentile(final_equities, p)) for p in pcts}
        ci_drawdown = {f"p{p}": float(np.percentile(max_drawdowns, p)) for p in pcts}
        ci_sharpe = {f"p{p}": float(np.percentile(sharpes, p)) for p in pcts}

        return MonteCarloResult(
            median_equity=round(float(np.median(final_equities)), 2),
            mean_equity=round(float(np.mean(final_equities)), 2),
            p5_equity=round(float(np.percentile(final_equities, 5)), 2),
            p95_equity=round(float(np.percentile(final_equities, 95)), 2),
            p1_equity=round(float(np.percentile(final_equities, 1)), 2),
            p99_equity=round(float(np.percentile(final_equities, 99)), 2),
            median_max_drawdown=round(float(np.median(max_drawdowns)) * 100, 4),
            p95_max_drawdown=round(float(np.percentile(max_drawdowns, 95)) * 100, 4),
            median_sharpe=round(float(np.median(sharpes)), 4),
            p5_sharpe=round(float(np.percentile(sharpes, 5)), 4),
            p95_sharpe=round(float(np.percentile(sharpes, 95)), 4),
            ruin_probability=round(ruin_prob * 100, 4),
            num_simulations=num_simulations,
            confidence_intervals={
                "equity": ci_equity,
                "max_drawdown": ci_drawdown,
                "sharpe_ratio": ci_sharpe,
            },
        )

    # ──────────────────────────────────────────────────────────────────
    # 4. Performance Metrics
    # ──────────────────────────────────────────────────────────────────

    def compute_performance_metrics(
        self,
        returns: list[float] | np.ndarray,
        risk_free_rate: float = 0.0,
        trading_days_per_year: int = 365,
        trade_durations: list[float] | None = None,
    ) -> PerformanceMetrics:
        """Compute comprehensive performance metrics from a return series.

        Goes beyond simple Sharpe/Sortino to include tail risk, distribution
        shape, and trade-level statistics.

        Args:
            returns: Per-period return series (fractions).
            risk_free_rate: Annualized risk-free rate.
            trading_days_per_year: Trading days per year.
            trade_durations: Optional list of trade durations in bars.

        Returns:
            PerformanceMetrics with all computed metrics.
        """
        ret_arr = np.array(returns, dtype=float)
        ret_arr = ret_arr[np.isfinite(ret_arr)]

        if len(ret_arr) < 2:
            return PerformanceMetrics()

        # Build equity curve
        equity = np.cumprod(1 + ret_arr)

        # Basic metrics
        total_ret = float(equity[-1] - 1)
        years = len(ret_arr) / trading_days_per_year
        ann_ret = ((1 + total_ret) ** (1 / years) - 1) if years > 0 else 0.0
        vol = float(np.std(ret_arr, ddof=1)) * math.sqrt(trading_days_per_year)
        mdd = _compute_max_drawdown(equity)
        mdd_dur = _compute_max_drawdown_duration(equity)
        sharpe = _compute_sharpe(ret_arr, risk_free_rate, trading_days_per_year)
        sortino = _compute_sortino(ret_arr, risk_free_rate, trading_days_per_year)
        calmar = ann_ret / mdd if mdd > 0 else float("inf")

        # Win/loss analysis
        wins = ret_arr[ret_arr > 0]
        losses = ret_arr[ret_arr < 0]
        win_rate = len(wins) / len(ret_arr) if len(ret_arr) > 0 else 0.0
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = abs(float(np.mean(losses))) if len(losses) > 0 else 0.0
        gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
        gross_loss = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
        payoff = avg_win / avg_loss if avg_loss > 0 else float("inf")

        # Tail analysis
        p95 = float(np.percentile(ret_arr, 95))
        p5 = abs(float(np.percentile(ret_arr, 5)))
        tail_ratio = p95 / p5 if p5 > 0 else float("inf")

        # Distribution shape
        from scipy import stats as sp_stats

        skew = float(sp_stats.skew(ret_arr))
        kurt = float(sp_stats.kurtosis(ret_arr))

        # Trade duration
        avg_dur = float(np.mean(trade_durations)) if trade_durations else 0.0

        # Count trades from return sign changes
        signs = np.sign(ret_arr)
        trade_count = int(np.sum(signs[1:] != signs[:-1])) + 1 if len(signs) > 0 else 0

        return PerformanceMetrics(
            total_return=round(total_ret * 100, 4),
            annualized_return=round(ann_ret * 100, 4),
            volatility=round(vol * 100, 4),
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=round(sortino, 4) if sortino != float("inf") else 999.99,
            calmar_ratio=round(calmar, 4) if calmar != float("inf") else 999.99,
            max_drawdown=round(mdd * 100, 4),
            max_drawdown_duration=mdd_dur,
            win_rate=round(win_rate * 100, 4),
            profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else 999.99,
            avg_win=round(avg_win * 100, 6),
            avg_loss=round(avg_loss * 100, 6),
            expectancy=round(expectancy * 100, 6),
            avg_holding_period=round(avg_dur, 2),
            total_trades=trade_count,
            payoff_ratio=round(payoff, 4) if payoff != float("inf") else 999.99,
            tail_ratio=round(tail_ratio, 4) if tail_ratio != float("inf") else 999.99,
            skewness=round(skew, 4),
            kurtosis=round(kurt, 4),
        )

    # ──────────────────────────────────────────────────────────────────
    # 5. Factor Analysis
    # ──────────────────────────────────────────────────────────────────

    def analyze_factors(
        self,
        strategy_returns: list[float] | np.ndarray,
        factor_returns: dict[str, list[float] | np.ndarray],
        rolling_window: int = 20,
        risk_free_rate: float = 0.0,
        trading_days_per_year: int = 365,
    ) -> FactorAnalysisResult:
        """Factor analysis — decompose strategy returns by factor exposure.

        Computes Information Coefficient (IC), Information Ratio (IR),
        and multi-factor regression to understand what drives strategy returns.

        Args:
            strategy_returns: Strategy's per-period return series.
            factor_returns: Dict of factor_name -> return series.
                E.g., {"BTC": btc_returns, "market_cap": size_returns,
                       "momentum": mom_returns, "volatility": vol_returns}.
            rolling_window: Window size for rolling IC calculation.
            risk_free_rate: Annualized risk-free rate.
            trading_days_per_year: Trading days per year.

        Returns:
            FactorAnalysisResult with IC, IR, exposures, and alpha.
        """
        strat = np.array(strategy_returns, dtype=float)
        strat = strat[np.isfinite(strat)]

        factor_names = tuple(factor_returns.keys())
        n_factors = len(factor_names)

        if len(strat) < 5 or n_factors == 0:
            return FactorAnalysisResult(factor_names=factor_names)

        # Align and clean factor data
        min_len = len(strat)
        factor_matrix = []
        for name in factor_names:
            f = np.array(factor_returns[name], dtype=float)[:min_len]
            min_len = min(min_len, len(f))
            factor_matrix.append(f)

        strat = strat[:min_len]
        factor_matrix = [f[:min_len] for f in factor_matrix]
        F = np.column_stack(factor_matrix)

        # Remove rows with NaN/Inf
        mask = np.isfinite(strat) & np.all(np.isfinite(F), axis=1)
        strat = strat[mask]
        F = F[mask]

        if len(strat) < max(5, n_factors + 1):
            return FactorAnalysisResult(factor_names=factor_names)

        # ── Rolling IC (Spearman rank correlation) ────────────────
        from scipy import stats as sp_stats

        ic_series: list[float] = []
        for i in range(rolling_window, len(strat)):
            window_strat = strat[i - rolling_window : i]
            # IC is typically computed vs a composite factor
            # Here we use the first factor as the primary signal
            window_factor = F[i - rolling_window : i, 0]
            if np.std(window_strat) > 0 and np.std(window_factor) > 0:
                corr, _ = sp_stats.spearmanr(window_factor, window_strat)
                ic_series.append(float(corr))
            else:
                ic_series.append(0.0)

        ic_arr = np.array(ic_series) if ic_series else np.array([0.0])
        ic_mean = float(np.mean(ic_arr))
        ic_std = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 0.0
        ir = ic_mean / ic_std if ic_std > 0 else 0.0

        # ── Multi-factor regression ───────────────────────────────
        # OLS: strategy_return = alpha + beta1*f1 + beta2*f2 + ... + epsilon
        from numpy.linalg import lstsq

        # Add intercept
        X = np.column_stack([np.ones(len(strat)), F])
        try:
            coeffs, residuals, rank, sv = lstsq(X, strat, rcond=None)
        except np.linalg.LinAlgError:
            coeffs = np.zeros(n_factors + 1)

        alpha = float(coeffs[0])
        betas = coeffs[1:]

        # Compute standard errors and t-stats
        y_hat = X @ coeffs
        resid = strat - y_hat
        mse = (
            float(np.sum(resid**2) / (len(strat) - n_factors - 1))
            if len(strat) > n_factors + 1
            else 0.0
        )
        try:
            cov_matrix = mse * np.linalg.inv(X.T @ X)
            se = np.sqrt(np.diag(cov_matrix))
        except np.linalg.LinAlgError:
            se = np.zeros(n_factors + 1)

        alpha_t = alpha / se[0] if se[0] > 0 else 0.0

        # R²
        ss_res = float(np.sum(resid**2))
        ss_tot = float(np.sum((strat - np.mean(strat)) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # Per-factor exposures
        exposures = []
        for j, name in enumerate(factor_names):
            beta_j = float(betas[j])
            t_stat_j = float(betas[j] / se[j + 1]) if se[j + 1] > 0 else 0.0
            # P-value approximation from t-stat
            p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat_j), df=max(1, len(strat) - n_factors - 1)))
            # Partial correlation
            # Simple approximation: correlation of residualized factor with residualized returns
            if np.std(F[:, j]) > 0:
                r_factor, _ = sp_stats.pearsonr(F[:, j], strat)
                partial_corr = float(r_factor)
            else:
                partial_corr = 0.0

            # R² contribution (drop-one)
            X_drop = np.column_stack([np.ones(len(strat)), np.delete(F, j, axis=1)])
            try:
                c_drop, _, _, _ = lstsq(X_drop, strat, rcond=None)
                y_drop = X_drop @ c_drop
                ss_res_drop = float(np.sum((strat - y_drop) ** 2))
                r2_drop = 1 - ss_res_drop / ss_tot if ss_tot > 0 else 0.0
                r2_contribution = r_squared - r2_drop
            except Exception:
                r2_contribution = 0.0

            exposures.append(
                FactorExposure(
                    factor_name=name,
                    beta=round(beta_j, 6),
                    t_stat=round(t_stat_j, 4),
                    p_value=round(float(p_val), 6),
                    r_squared=round(max(0, r2_contribution), 6),
                    partial_correlation=round(partial_corr, 6),
                )
            )

        return FactorAnalysisResult(
            ic=round(float(sp_stats.spearmanr(F[:, 0], strat)[0]), 6)
            if np.std(F[:, 0]) > 0
            else 0.0,
            ic_mean=round(ic_mean, 6),
            ic_std=round(ic_std, 6),
            ir=round(ir, 6),
            ic_series=[round(x, 6) for x in ic_series],
            factor_exposures=exposures,
            alpha=round(alpha * trading_days_per_year * 100, 6),  # Annualized alpha %
            alpha_t_stat=round(float(alpha_t), 4),
            r_squared=round(r_squared, 6),
            factor_names=factor_names,
        )

    # ──────────────────────────────────────────────────────────────────
    # 6. Regime-Conditional Backtest
    # ──────────────────────────────────────────────────────────────────

    def regime_conditional_backtest(
        self,
        ohlcv: pd.DataFrame,
        strategy_returns: list[float] | np.ndarray,
        regime_method: str = "rule_based",
        lookback: int = 20,
        vol_lookback: int = 20,
        trend_threshold: float = 0.02,
        vol_high_percentile: float = 75.0,
        vol_low_percentile: float = 25.0,
        risk_free_rate: float = 0.0,
        trading_days_per_year: int = 365,
    ) -> RegimeConditionalBacktestResult:
        """Regime-conditional backtest — performance broken down by market regime.

        Answers: "How does this strategy perform in trending vs ranging markets?"

        Detects market regimes using one of two methods:
        - 'rule_based': Uses ADX-like trend strength + volatility percentile
        - 'hmm': Hidden Markov Model (2-state: calm vs volatile)

        Then computes full performance metrics for each regime segment.

        Args:
            ohlcv: OHLCV DataFrame.
            strategy_returns: Per-period strategy return series.
            regime_method: 'rule_based' or 'hmm'.
            lookback: Lookback period for trend detection.
            vol_lookback: Lookback period for volatility calculation.
            trend_threshold: Threshold for trend detection (fractional return).
            vol_high_percentile: Percentile above which vol is "high".
            vol_low_percentile: Percentile below which vol is "low".
            risk_free_rate: Annualized risk-free rate.
            trading_days_per_year: Trading days per year.

        Returns:
            RegimeConditionalBacktestResult with per-regime performance.
        """
        ret_arr = np.array(strategy_returns, dtype=float)
        n = min(len(ohlcv), len(ret_arr))

        if n < lookback + 5:
            return RegimeConditionalBacktestResult(
                regime_performance={},
                regime_transitions={},
                regime_sequence=[],
                total_bars=0,
            )

        ohlcv = ohlcv.iloc[:n].reset_index(drop=True)
        ret_arr = ret_arr[:n]
        closes = ohlcv["close"].values.astype(float)

        # ── Detect regimes ────────────────────────────────────────
        regimes = self._detect_regimes(
            closes,
            ret_arr,
            regime_method,
            lookback,
            vol_lookback,
            trend_threshold,
            vol_high_percentile,
            vol_low_percentile,
        )

        # ── Compute per-regime metrics ────────────────────────────
        regime_perf: dict[str, RegimePerformance] = {}
        regime_transitions: dict[str, dict[str, int]] = {}
        unique_regimes = list(set(regimes))

        for regime in unique_regimes:
            mask = np.array([r == regime for r in regimes])
            regime_returns = ret_arr[mask]

            if len(regime_returns) < 2:
                regime_perf[regime] = RegimePerformance(
                    regime=regime,
                    total_bars=int(np.sum(mask)),
                    pct_of_total_time=round(float(np.sum(mask)) / n * 100, 2),
                )
                continue

            eq = np.cumprod(1 + regime_returns)
            total_ret = float(eq[-1] - 1)
            years = len(regime_returns) / trading_days_per_year
            ann_ret = ((1 + total_ret) ** (1 / years) - 1) if years > 0 else 0.0
            vol = float(np.std(regime_returns, ddof=1)) * math.sqrt(trading_days_per_year)
            sharpe = _compute_sharpe(regime_returns, risk_free_rate, trading_days_per_year)
            sortino = _compute_sortino(regime_returns, risk_free_rate, trading_days_per_year)
            mdd = _compute_max_drawdown(eq)

            wins = regime_returns[regime_returns > 0]
            losses = regime_returns[regime_returns < 0]
            wr = len(wins) / len(regime_returns) if len(regime_returns) > 0 else 0.0
            gp = float(np.sum(wins)) if len(wins) > 0 else 0.0
            gl = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
            pf = gp / gl if gl > 0 else float("inf")

            # Count trades in this regime (sign changes)
            signs = np.sign(regime_returns)
            trades = int(np.sum(signs[1:] != signs[:-1])) + 1 if len(signs) > 0 else 0

            regime_perf[regime] = RegimePerformance(
                regime=regime,
                total_return=round(total_ret * 100, 4),
                annualized_return=round(ann_ret * 100, 4),
                sharpe_ratio=round(sharpe, 4),
                sortino_ratio=round(sortino, 4) if sortino != float("inf") else 999.99,
                max_drawdown=round(mdd * 100, 4),
                win_rate=round(wr * 100, 2),
                profit_factor=round(pf, 4) if pf != float("inf") else 999.99,
                total_trades=trades,
                total_bars=int(np.sum(mask)),
                avg_bar_return=round(float(np.mean(regime_returns)) * 100, 6),
                volatility=round(vol * 100, 4),
                pct_of_total_time=round(float(np.sum(mask)) / n * 100, 2),
            )

        # ── Regime transitions ────────────────────────────────────
        for r in unique_regimes:
            regime_transitions[r] = {}
        for i in range(1, len(regimes)):
            prev, curr = regimes[i - 1], regimes[i]
            if prev != curr:
                regime_transitions[prev][curr] = regime_transitions[prev].get(curr, 0) + 1

        # ── Best/worst regime by Sharpe ───────────────────────────
        valid_regimes = {k: v for k, v in regime_perf.items() if v.total_bars > 1}
        best = (
            max(valid_regimes, key=lambda k: valid_regimes[k].sharpe_ratio) if valid_regimes else ""
        )
        worst = (
            min(valid_regimes, key=lambda k: valid_regimes[k].sharpe_ratio) if valid_regimes else ""
        )

        # ── Regime adaptability: how much Sharpe varies across regimes ──
        sharpes = [v.sharpe_ratio for v in valid_regimes.values()]
        if len(sharpes) > 1 and np.std(sharpes) > 0:
            adaptability = min(1.0, float(np.std(sharpes) / (abs(np.mean(sharpes)) + 1e-10)))
        else:
            adaptability = 0.0

        return RegimeConditionalBacktestResult(
            regime_performance=regime_perf,
            regime_transitions=regime_transitions,
            regime_sequence=regimes,
            best_regime=best,
            worst_regime=worst,
            regime_adaptability=round(adaptability, 4),
            total_bars=n,
            regime_detection_method=regime_method,
        )

    def _detect_regimes(
        self,
        closes: np.ndarray,
        returns: np.ndarray,
        method: str,
        lookback: int,
        vol_lookback: int,
        trend_threshold: float,
        vol_high_pct: float,
        vol_low_pct: float,
    ) -> list[str]:
        """Detect market regimes from price data.

        Args:
            closes: Close price array.
            returns: Return array.
            method: 'rule_based' or 'hmm'.
            lookback: Trend lookback.
            vol_lookback: Volatility lookback.
            trend_threshold: Trend detection threshold.
            vol_high_pct: High volatility percentile.
            vol_low_pct: Low volatility percentile.

        Returns:
            List of regime labels per bar.
        """
        n = len(closes)
        regimes = [MarketRegime.RANGING.value] * n

        if method == "hmm":
            return self._detect_regimes_hmm(returns, n)

        # Rule-based regime detection
        # 1. Compute rolling trend strength (normalized return over lookback)
        # 2. Compute rolling volatility
        # 3. Classify into regimes

        for i in range(lookback, n):
            # Trend: cumulative return over lookback
            lookback_ret = (closes[i] - closes[i - lookback]) / closes[i - lookback]

            # Volatility: rolling std of returns
            vol_window = returns[max(0, i - vol_lookback) : i]
            current_vol = float(np.std(vol_window, ddof=1)) if len(vol_window) > 1 else 0.0

            # Compute volatility percentiles using expanding window
            if i >= vol_lookback * 2:
                hist_vol = []
                for j in range(vol_lookback, i):
                    w = returns[max(0, j - vol_lookback) : j]
                    if len(w) > 1:
                        hist_vol.append(float(np.std(w, ddof=1)))
                if hist_vol:
                    vol_high = np.percentile(hist_vol, vol_high_pct)
                    vol_low = np.percentile(hist_vol, vol_low_pct)
                else:
                    vol_high = current_vol * 1.5
                    vol_low = current_vol * 0.5
            else:
                vol_high = current_vol * 1.5
                vol_low = current_vol * 0.5

            # Classify
            is_trending_up = lookback_ret > trend_threshold
            is_trending_down = lookback_ret < -trend_threshold
            is_high_vol = current_vol > vol_high
            is_low_vol = current_vol < vol_low

            if is_high_vol:
                regimes[i] = MarketRegime.HIGH_VOLATILITY.value
            elif is_trending_up:
                regimes[i] = MarketRegime.TRENDING_UP.value
            elif is_trending_down:
                regimes[i] = MarketRegime.TRENDING_DOWN.value
            elif is_low_vol:
                regimes[i] = MarketRegime.LOW_VOLATILITY.value
            else:
                regimes[i] = MarketRegime.RANGING.value

        return regimes

    def _detect_regimes_hmm(self, returns: np.ndarray, n: int) -> list[str]:
        """Detect regimes using a simple 2-state Gaussian HMM.

        Falls back to rule-based if hmmlearn is not available.
        """
        try:
            from hmmlearn.hmm import GaussianHMM

            X = returns.reshape(-1, 1)
            model = GaussianHMM(
                n_components=2,
                covariance_type="full",
                n_iter=100,
                random_state=42,
                tol=1e-4,
            )
            model.fit(X)
            states = model.predict(X)

            # Label states by mean return
            means = model.means_.flatten()
            low_vol_state = np.argmin(model.covars_.flatten())
            1 - low_vol_state

            regime_map = {}
            for state_idx in range(2):
                mean_ret = means[state_idx]
                if state_idx == low_vol_state:
                    if mean_ret > 0:
                        regime_map[state_idx] = MarketRegime.TRENDING_UP.value
                    elif mean_ret < 0:
                        regime_map[state_idx] = MarketRegime.TRENDING_DOWN.value
                    else:
                        regime_map[state_idx] = MarketRegime.RANGING.value
                else:
                    regime_map[state_idx] = MarketRegime.HIGH_VOLATILITY.value

            return [regime_map.get(s, MarketRegime.RANGING.value) for s in states]

        except ImportError:
            logger.info("hmmlearn not available, falling back to rule-based regime detection")
            # Fall back to simple rule-based
            regimes = [MarketRegime.RANGING.value] * n
            lookback = 20
            for i in range(lookback, n):
                ret = returns[i - lookback : i].sum()
                vol = float(np.std(returns[max(0, i - lookback) : i], ddof=1))
                if ret > 0.05:
                    regimes[i] = MarketRegime.TRENDING_UP.value
                elif ret < -0.05:
                    regimes[i] = MarketRegime.TRENDING_DOWN.value
                elif vol > np.percentile(returns, 75):
                    regimes[i] = MarketRegime.HIGH_VOLATILITY.value
            return regimes
