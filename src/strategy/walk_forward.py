"""
Walk-Forward Validator — Rolling window out-of-sample testing.

Splits historical data into N rolling train/test windows, runs
optimization on train, validates on test. Detects overfitting by
comparing train vs test performance.

Usage::

    from src.strategy.walk_forward import WalkForwardValidator, WalkForwardConfig

    validator = WalkForwardValidator(
        strategy_factory=lambda params: MyStrategy(**params),
        optimize_fn=my_optimization_fn,
        config=WalkForwardConfig(n_windows=5, train_ratio=0.7),
    )
    result = validator.run(ohlcv_data)
    print(result.overfitting_score)
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.interfaces.types import OHLCV
from src.strategy.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestMetrics,
    BacktestResult,
)
from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class WalkForwardConfig:
    """Configuration for walk-forward validation.

    Attributes:
        n_windows: Number of rolling train/test windows.
        train_ratio: Fraction of each window used for training (0.0-1.0).
        anchored: If True, train window always starts from the beginning
            (expanding window). If False, train window slides (rolling).
        min_train_bars: Minimum bars required in a training window.
        min_test_bars: Minimum bars required in a test window.
        overfit_threshold: Train/test Sharpe ratio threshold for overfitting
            flag. If train_sharpe / test_sharpe > this, flag overfitting.
        backtest_config: Config for individual backtest runs.
    """

    n_windows: int = 5
    train_ratio: float = 0.70
    anchored: bool = False
    min_train_bars: int = 50
    min_test_bars: int = 20
    overfit_threshold: float = 1.75
    backtest_config: BacktestConfig = field(default_factory=BacktestConfig)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class WindowResult:
    """Result for a single train/test window.

    Attributes:
        window_index: Zero-based window index.
        train_start: First bar index of training data.
        train_end: Last bar index of training data (exclusive).
        test_start: First bar index of test data.
        test_end: Last bar index of test data (exclusive).
        train_result: BacktestResult on training data.
        test_result: BacktestResult on test data.
        train_params: Parameters used for this window (from optimization).
    """

    window_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_result: BacktestResult
    test_result: BacktestResult
    train_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WalkForwardResult:
    """Complete walk-forward validation result.

    Attributes:
        windows: Per-window train/test results.
        aggregate_train_metrics: Aggregated training metrics across windows.
        aggregate_test_metrics: Aggregated test metrics across windows.
        overfitting_score: Ratio of train Sharpe to test Sharpe (> threshold = overfit).
        is_overfit: Whether overfitting was detected.
        consistency_score: Fraction of windows where test Sharpe > 0.
        n_windows: Number of windows processed.
    """

    windows: tuple[WindowResult, ...]
    aggregate_train_metrics: BacktestMetrics
    aggregate_test_metrics: BacktestMetrics
    overfitting_score: float
    is_overfit: bool
    consistency_score: float
    n_windows: int


# ═══════════════════════════════════════════════════════════════════════
# TYPE ALIASES
# ═══════════════════════════════════════════════════════════════════════

# Strategy factory: takes optional params dict, returns a strategy instance
StrategyFactory = Callable[..., BaseStrategy]

# Optimizer: takes (strategy, train_data, config) -> optimized params dict
OptimizeFn = Callable[[BaseStrategy, list[OHLCV], BacktestConfig], dict[str, Any]]


# ═══════════════════════════════════════════════════════════════════════
# WALK-FORWARD VALIDATOR
# ═══════════════════════════════════════════════════════════════════════


class WalkForwardValidator:
    """Splits historical data into rolling train/test windows and validates.

    Each window:
    1. Runs optimization on training data (via optimize_fn or default)
    2. Validates optimized parameters on test data
    3. Records per-window metrics

    Overfitting is detected when training performance significantly
    exceeds test performance (controlled by overfit_threshold).

    Args:
        strategy_factory: Callable that creates strategy instances.
            Can accept keyword arguments for parameter optimization.
        optimize_fn: Optional function to optimize strategy parameters.
            If None, uses the strategy as-is (no optimization).
        config: Walk-forward configuration.
    """

    def __init__(
        self,
        strategy_factory: StrategyFactory,
        optimize_fn: OptimizeFn | None = None,
        config: WalkForwardConfig | None = None,
    ) -> None:
        self._strategy_factory = strategy_factory
        self._optimize_fn = optimize_fn
        self._config = config or WalkForwardConfig()

    def run(self, ohlcv: list[OHLCV]) -> WalkForwardResult:
        """Run walk-forward validation over historical data.

        Args:
            ohlcv: Historical OHLCV bars, oldest first.

        Returns:
            WalkForwardResult with per-window results and aggregate stats.

        Raises:
            ValueError: If data is too short for configured windows.
        """
        config = self._config
        n_windows = config.n_windows
        total_bars = len(ohlcv)

        # Compute window boundaries
        windows = self._compute_windows(total_bars)

        if not windows:
            raise ValueError(
                f"Data too short ({total_bars} bars) for {n_windows} windows "
                f"(need at least {config.min_train_bars + config.min_test_bars} bars)"
            )

        # Run each window
        window_results: list[WindowResult] = []
        for idx, (train_start, train_end, test_start, test_end) in enumerate(windows):
            train_data = ohlcv[train_start:train_end]
            test_data = ohlcv[test_start:test_end]

            # Create strategy and optimize on train
            strategy = self._strategy_factory()
            optimized_params: dict[str, Any] = {}

            if self._optimize_fn is not None:
                optimized_params = self._optimize_fn(strategy, train_data, config.backtest_config)
                # Recreate strategy with optimized params if possible
                try:
                    strategy = self._strategy_factory(**optimized_params)
                except TypeError:
                    logger.warning(
                        "Strategy factory doesn't accept optimized params, using defaults"
                    )

            # Backtest on train
            train_engine = BacktestEngine(strategy, config.backtest_config)
            train_result = train_engine.run(train_data)

            # Backtest on test (same strategy, no re-optimization)
            test_engine = BacktestEngine(strategy, config.backtest_config)
            test_result = test_engine.run(test_data)

            window_results.append(
                WindowResult(
                    window_index=idx,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_result=train_result,
                    test_result=test_result,
                    train_params=optimized_params,
                )
            )

            logger.info(
                f"Window {idx + 1}/{len(windows)}: "
                f"train_sharpe={train_result.metrics.sharpe_ratio:.2f}, "
                f"test_sharpe={test_result.metrics.sharpe_ratio:.2f}"
            )

        # Aggregate metrics
        agg_train = self._aggregate_metrics([w.train_result.metrics for w in window_results])
        agg_test = self._aggregate_metrics([w.test_result.metrics for w in window_results])

        # Overfitting detection
        overfit_score = self._compute_overfit_score(window_results)
        is_overfit = overfit_score > config.overfit_threshold

        # Consistency: fraction of windows with positive test Sharpe
        positive_test = sum(1 for w in window_results if w.test_result.metrics.sharpe_ratio > 0)
        consistency = positive_test / len(window_results) if window_results else 0.0

        if is_overfit:
            logger.warning(
                f"OVERFITTING DETECTED: train/test Sharpe ratio = {overfit_score:.2f} "
                f"(threshold: {config.overfit_threshold})"
            )

        return WalkForwardResult(
            windows=tuple(window_results),
            aggregate_train_metrics=agg_train,
            aggregate_test_metrics=agg_test,
            overfitting_score=round(overfit_score, 4),
            is_overfit=is_overfit,
            consistency_score=round(consistency, 4),
            n_windows=len(window_results),
        )

    # ── Private helpers ──────────────────────────────────────

    def _compute_windows(
        self,
        total_bars: int,
    ) -> list[tuple[int, int, int, int]]:
        """Compute train/test index boundaries for each window.

        Returns:
            List of (train_start, train_end, test_start, test_end) tuples.
        """
        config = self._config
        n = config.n_windows
        min_train = config.min_train_bars
        min_test = config.min_test_bars

        # Minimum data per window
        min_window = min_train + min_test

        if total_bars < min_window:
            return []

        # For non-anchored (rolling): divide data into overlapping windows
        # Each window slides forward by (total_bars - window_size) / (n - 1) bars
        if config.anchored:
            # Anchored: train always starts at 0, test slides forward
            usable_bars = total_bars
            test_size = max(min_test, usable_bars // (n + 1))
            windows: list[tuple[int, int, int, int]] = []
            for i in range(n):
                train_start = 0
                test_start_idx = min_train + i * test_size
                test_end_idx = min(test_start_idx + test_size, total_bars)
                train_end_idx = test_start_idx

                if train_end_idx - train_start < min_train:
                    continue
                if test_end_idx - test_start_idx < min_test:
                    continue

                windows.append((train_start, train_end_idx, test_start_idx, test_end_idx))
            return windows
        else:
            # Rolling: each window is a fixed-size slice that slides forward
            window_size = max(min_window, total_bars // n)
            step = max(1, (total_bars - window_size) // max(1, n - 1))

            windows = []
            for i in range(n):
                start = i * step
                end = min(start + window_size, total_bars)
                if end - start < min_window:
                    break

                split = start + int((end - start) * config.train_ratio)
                split = max(split, start + min_train)
                split = min(split, end - min_test)

                if split - start < min_train or end - split < min_test:
                    continue

                windows.append((start, split, split, end))

            return windows

    @staticmethod
    def _aggregate_metrics(metrics_list: list[BacktestMetrics]) -> BacktestMetrics:
        """Aggregate metrics across windows by averaging."""
        if not metrics_list:
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

        len(metrics_list)

        def _avg(key: str) -> float:
            vals = [getattr(m, key) for m in metrics_list]
            finite_vals = [v for v in vals if math.isfinite(v)]
            return float(np.mean(finite_vals)) if finite_vals else 0.0

        return BacktestMetrics(
            total_return=round(_avg("total_return"), 6),
            cagr=round(_avg("cagr"), 6),
            sharpe_ratio=round(_avg("sharpe_ratio"), 4),
            sortino_ratio=round(_avg("sortino_ratio"), 4),
            calmar_ratio=round(_avg("calmar_ratio"), 4),
            max_drawdown=round(max(m.max_drawdown for m in metrics_list), 6),
            max_drawdown_duration=max(m.max_drawdown_duration for m in metrics_list),
            win_rate=round(_avg("win_rate"), 4),
            profit_factor=round(_avg("profit_factor"), 4),
            avg_win=round(_avg("avg_win"), 2),
            avg_loss=round(_avg("avg_loss"), 2),
            total_trades=sum(m.total_trades for m in metrics_list),
            winning_trades=sum(m.winning_trades for m in metrics_list),
            losing_trades=sum(m.losing_trades for m in metrics_list),
            avg_trade_duration=round(_avg("avg_trade_duration"), 2),
            expectancy=round(_avg("expectancy"), 2),
        )

    @staticmethod
    def _compute_overfit_score(windows: list[WindowResult]) -> float:
        """Compute overfitting score as ratio of train Sharpe to test Sharpe.

        Uses median Sharpe across windows to be robust to outliers.
        """
        train_sharpes = [w.train_result.metrics.sharpe_ratio for w in windows]
        test_sharpes = [w.test_result.metrics.sharpe_ratio for w in windows]

        median_train = float(np.median(train_sharpes))
        median_test = float(np.median(test_sharpes))

        if median_test <= 0:
            # If test is negative or zero, overfitting is extreme
            return float("inf") if median_train > 0 else 1.0

        return abs(median_train) / abs(median_test)
