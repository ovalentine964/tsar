"""
Unit tests for Backtest Engine — Phase 2.

Tests:
  - BacktestEngine: basic backtest, trade counting, PnL, edge cases
  - WalkForwardValidator: train/test splits, overfitting detection
  - MonteCarloSimulator: confidence intervals, permutation robustness
  - Edge cases: no signals, all losing trades, single trade
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.interfaces.types import OHLCV
from src.strategy.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestMetrics,
    BacktestResult,
    TradeRecord,
)
from src.strategy.base import BaseStrategy
from src.strategy.monte_carlo import (
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloSimulator,
)
from src.strategy.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardValidator,
)


# ═══════════════════════════════════════════════════════════════════════
# TEST HELPERS
# ═══════════════════════════════════════════════════════════════════════


def make_ohlcv(
    n: int,
    base_price: float = 100.0,
    price_step: float = 1.0,
    start: datetime | None = None,
) -> list[OHLCV]:
    """Generate synthetic OHLCV data with a linear price trend.

    Args:
        n: Number of bars.
        base_price: Starting close price.
        price_step: Price change per bar.
        start: Starting timestamp.

    Returns:
        List of OHLCV bars with monotonically increasing closes.
    """
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    bars = []
    for i in range(n):
        close = base_price + i * price_step
        bars.append(OHLCV(
            timestamp=start + timedelta(hours=i),
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=1000.0 + i,
        ))
    return bars


class AlwaysBuyStrategy(BaseStrategy):
    """Test strategy that always signals buy on every bar."""

    NAME = "always_buy"
    VERSION = "1.0.0"

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        close = data.get("close", 0.0)
        return {
            "side": "buy",
            "score": 0.8,
            "entry_price": close,
            "stop_loss": close * 0.95,
            "take_profit": close * 1.05,
            "reasoning": "always buy",
        }

    def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        return None  # let stop/TP handle exits

    def get_risk_params(self) -> dict[str, Any]:
        return {"stop_loss_pct": 0.05, "take_profit_pct": 0.05}


class NeverSignalStrategy(BaseStrategy):
    """Test strategy that never generates any signals."""

    NAME = "never_signal"
    VERSION = "1.0.0"

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def get_risk_params(self) -> dict[str, Any]:
        return {}


class AlwaysLoseStrategy(BaseStrategy):
    """Test strategy that always buys then immediately exits at a loss."""

    NAME = "always_lose"
    VERSION = "1.0.0"
    _bar_count: int = 0

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        close = data.get("close", 0.0)
        # Signal every other bar
        bar_idx = data.get("bar_index", 0)
        if bar_idx % 2 == 0:
            return {
                "side": "buy",
                "score": 0.7,
                "entry_price": close,
                "stop_loss": close * 0.90,  # wide stop, won't trigger
                "take_profit": close * 1.10,  # wide TP, won't trigger
                "reasoning": "buy",
            }
        return None

    def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        # Exit immediately at a loss: sell at 2% below entry
        return {"reason": "forced_loss", "action": "close"}

    def get_risk_params(self) -> dict[str, Any]:
        return {}


class AlternatingStrategy(BaseStrategy):
    """Test strategy that alternates between buy and sell signals."""

    NAME = "alternating"
    VERSION = "1.0.0"

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        close = data.get("close", 0.0)
        bar_idx = data.get("bar_index", 0)
        if bar_idx % 4 == 0:
            return {
                "side": "buy",
                "score": 0.7,
                "entry_price": close,
                "stop_loss": close * 0.95,
                "take_profit": close * 1.10,
                "reasoning": "buy",
            }
        elif bar_idx % 4 == 2:
            return {
                "side": "sell",
                "score": 0.7,
                "entry_price": close,
                "stop_loss": close * 1.05,
                "take_profit": close * 0.90,
                "reasoning": "sell",
            }
        return None

    def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        # Exit after 1 bar
        return {"reason": "bar_exit", "action": "close"}

    def get_risk_params(self) -> dict[str, Any]:
        return {}


class OptimizableStrategy(BaseStrategy):
    """Strategy with configurable parameters for walk-forward testing."""

    NAME = "optimizable"
    VERSION = "1.0.0"

    def __init__(self, threshold: float = 0.5, multiplier: float = 1.0) -> None:
        self._threshold = threshold
        self._multiplier = multiplier

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        close = data.get("close", 0.0)
        bar_idx = data.get("bar_index", 0)
        # Only enter if bar index exceeds threshold
        if bar_idx > self._threshold * 10:
            return {
                "side": "buy",
                "score": 0.7,
                "entry_price": close,
                "stop_loss": close * (1 - 0.05 * self._multiplier),
                "take_profit": close * (1 + 0.05 * self._multiplier),
                "reasoning": f"threshold={self._threshold}",
            }
        return None

    def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def get_risk_params(self) -> dict[str, Any]:
        return {"threshold": self._threshold, "multiplier": self._multiplier}


# ═══════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestBacktestEngineBasic:
    """Core backtest engine functionality."""

    def test_backtest_returns_result(self):
        """Engine produces a valid BacktestResult."""
        ohlcv = make_ohlcv(100)
        engine = BacktestEngine(AlwaysBuyStrategy())
        result = engine.run(ohlcv)

        assert isinstance(result, BacktestResult)
        assert result.bar_count == 100
        assert result.strategy_name == "always_buy"
        assert len(result.equity_curve) == 101  # initial + one per bar

    def test_backtest_generates_trades(self):
        """AlwaysBuyStrategy generates trades."""
        ohlcv = make_ohlcv(100)
        engine = BacktestEngine(AlwaysBuyStrategy())
        result = engine.run(ohlcv)

        assert len(result.trades) > 0
        for trade in result.trades:
            assert isinstance(trade, TradeRecord)
            assert trade.quantity > 0
            assert trade.entry_price > 0

    def test_backtest_pnl_on_uptrend(self):
        """Buy strategy on uptrend data should be profitable."""
        ohlcv = make_ohlcv(100, base_price=100.0, price_step=2.0)
        engine = BacktestEngine(
            AlwaysBuyStrategy(),
            config=BacktestConfig(
                initial_capital=100_000.0,
                position_size_pct=0.10,
                commission_bps=0.0,  # no commission for clean test
                slippage_bps=0.0,
            ),
        )
        result = engine.run(ohlcv)

        # On a pure uptrend, total return should be positive
        assert result.metrics.total_return > 0

    def test_backtest_pnl_on_downtrend(self):
        """Buy strategy on downtrend data should lose money."""
        ohlcv = make_ohlcv(100, base_price=200.0, price_step=-1.0)
        engine = BacktestEngine(
            AlwaysBuyStrategy(),
            config=BacktestConfig(
                initial_capital=100_000.0,
                commission_bps=0.0,
                slippage_bps=0.0,
            ),
        )
        result = engine.run(ohlcv)

        # On a downtrend, buy-and-hold loses money
        assert result.metrics.total_return < 0

    def test_commission_reduces_returns(self):
        """Higher commission should reduce total returns."""
        ohlcv = make_ohlcv(50, base_price=100.0, price_step=1.0)

        result_no_fee = BacktestEngine(
            AlwaysBuyStrategy(),
            config=BacktestConfig(commission_bps=0.0, slippage_bps=0.0),
        ).run(ohlcv)

        result_high_fee = BacktestEngine(
            AlwaysBuyStrategy(),
            config=BacktestConfig(commission_bps=100.0, slippage_bps=0.0),
        ).run(ohlcv)

        assert result_no_fee.metrics.total_return > result_high_fee.metrics.total_return

    def test_slippage_reduces_returns(self):
        """Higher slippage should reduce total returns."""
        ohlcv = make_ohlcv(50, base_price=100.0, price_step=1.0)

        result_no_slip = BacktestEngine(
            AlwaysBuyStrategy(),
            config=BacktestConfig(commission_bps=0.0, slippage_bps=0.0),
        ).run(ohlcv)

        result_high_slip = BacktestEngine(
            AlwaysBuyStrategy(),
            config=BacktestConfig(commission_bps=0.0, slippage_bps=50.0),
        ).run(ohlcv)

        assert result_no_slip.metrics.total_return > result_high_slip.metrics.total_return

    def test_equity_curve_matches_trades(self):
        """Equity curve should reflect trade PnL."""
        ohlcv = make_ohlcv(50)
        engine = BacktestEngine(AlwaysBuyStrategy())
        result = engine.run(ohlcv)

        # Equity curve starts at initial capital
        assert result.equity_curve[0] == result.config.initial_capital
        # All equity values should be positive
        assert all(eq > 0 for eq in result.equity_curve)


class TestBacktestMetrics:
    """Verify computed metrics."""

    def test_metrics_type(self):
        ohlcv = make_ohlcv(50)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)
        assert isinstance(result.metrics, BacktestMetrics)

    def test_win_rate_range(self):
        ohlcv = make_ohlcv(100)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)
        assert 0.0 <= result.metrics.win_rate <= 1.0

    def test_profit_factor_positive(self):
        ohlcv = make_ohlcv(100, price_step=1.0)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)
        assert result.metrics.profit_factor >= 0.0

    def test_max_drawdown_range(self):
        ohlcv = make_ohlcv(100)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)
        assert 0.0 <= result.metrics.max_drawdown <= 1.0

    def test_total_trades_matches(self):
        ohlcv = make_ohlcv(50)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)
        assert result.metrics.total_trades == len(result.trades)

    def test_winning_plus_losing_equals_total(self):
        ohlcv = make_ohlcv(100)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)
        assert (
            result.metrics.winning_trades + result.metrics.losing_trades
            == result.metrics.total_trades
        )

    def test_sharpe_ratio_finite(self):
        ohlcv = make_ohlcv(100)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)
        assert math.isfinite(result.metrics.sharpe_ratio)

    def test_cagr_finite(self):
        ohlcv = make_ohlcv(100)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)
        assert math.isfinite(result.metrics.cagr)


class TestBacktestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_no_signals_no_trades(self):
        """Strategy that never signals produces no trades."""
        ohlcv = make_ohlcv(100)
        result = BacktestEngine(NeverSignalStrategy()).run(ohlcv)

        assert len(result.trades) == 0
        assert result.metrics.total_trades == 0
        assert result.metrics.total_return == 0.0

    def test_all_losing_trades(self):
        """Strategy forced to lose on every trade."""
        ohlcv = make_ohlcv(20, base_price=100.0, price_step=0.0)
        # Flat prices, strategy always exits immediately at a loss.
        # Commission ensures net PnL is negative even on flat prices.
        engine = BacktestEngine(
            AlwaysLoseStrategy(),
            config=BacktestConfig(
                commission_bps=10.0,
                slippage_bps=0.0,
            ),
        )
        result = engine.run(ohlcv)

        if len(result.trades) > 0:
            # All trades should be losses (commission eats into flat PnL)
            assert all(t.pnl < 0 for t in result.trades)
            assert result.metrics.win_rate == 0.0
            assert result.metrics.total_return < 0

    def test_single_bar_raises(self):
        """Backtest with fewer than 2 bars should raise."""
        ohlcv = make_ohlcv(1)
        with pytest.raises(ValueError, match="at least 2"):
            BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)

    def test_two_bar_backtest(self):
        """Minimal backtest with exactly 2 bars."""
        ohlcv = make_ohlcv(2, base_price=100.0, price_step=5.0)
        engine = BacktestEngine(AlwaysBuyStrategy())
        result = engine.run(ohlcv)

        assert result.bar_count == 2
        assert len(result.equity_curve) == 3

    def test_single_trade(self):
        """Backtest that produces exactly one trade."""
        # Strategy: signal on bar 0, exit on bar 1 via check_exit
        class OneTradeStrategy(BaseStrategy):
            NAME = "one_trade"
            VERSION = "1.0.0"
            _entered = False

            def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
                bar_idx = data.get("bar_index", 0)
                if bar_idx == 0 and not self._entered:
                    self._entered = True
                    close = data.get("close", 0.0)
                    return {
                        "side": "buy",
                        "score": 0.8,
                        "entry_price": close,
                        "stop_loss": close * 0.90,
                        "take_profit": close * 1.10,
                        "reasoning": "single trade",
                    }
                return None

            def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
                return None

            def get_risk_params(self) -> dict[str, Any]:
                return {}

        ohlcv = make_ohlcv(10, base_price=100.0, price_step=0.0)
        result = BacktestEngine(OneTradeStrategy()).run(ohlcv)

        # Only one entry signal on bar 0, exit at end_of_data
        assert len(result.trades) == 1
        assert result.trades[0].exit_reason == "end_of_data"

    def test_force_close_at_end(self):
        """Open positions are force-closed at end of data."""
        ohlcv = make_ohlcv(10)
        result = BacktestEngine(AlwaysBuyStrategy()).run(ohlcv)

        # Last trade should be closed at end
        if result.trades:
            last_trade = result.trades[-1]
            assert last_trade.exit_time == ohlcv[-1].timestamp


class TestBacktestStopLoss:
    """Stop-loss and take-profit triggering."""

    def test_stop_loss_triggers_on_downtrend(self):
        """Buy on high bar, price drops to stop-loss."""
        # Create data: price drops 10% over 20 bars
        ohlcv = make_ohlcv(20, base_price=100.0, price_step=-5.0)
        strategy = AlwaysBuyStrategy()
        engine = BacktestEngine(
            strategy,
            config=BacktestConfig(commission_bps=0.0, slippage_bps=0.0),
        )
        result = engine.run(ohlcv)

        # At least some trades should exit via stop_loss
        sl_trades = [t for t in result.trades if t.exit_reason == "stop_loss"]
        # With 5% drops per bar and 5% stop, most should hit stop
        assert len(sl_trades) > 0


class TestShortSelling:
    """Short selling support."""

    def test_short_on_downtrend_profitable(self):
        """Alternating strategy shorts on downtrend should have some profit."""
        ohlcv = make_ohlcv(40, base_price=200.0, price_step=-2.0)
        engine = BacktestEngine(
            AlternatingStrategy(),
            config=BacktestConfig(commission_bps=0.0, slippage_bps=0.0),
        )
        result = engine.run(ohlcv)

        # Should have both buy and sell trades
        buy_trades = [t for t in result.trades if t.side == "buy"]
        sell_trades = [t for t in result.trades if t.side == "sell"]
        assert len(buy_trades) > 0
        assert len(sell_trades) > 0


# ═══════════════════════════════════════════════════════════════════════
# WALK-FORWARD VALIDATOR TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestWalkForwardValidator:
    """Walk-forward validation tests."""

    def test_basic_walk_forward(self):
        """Validator produces a WalkForwardResult."""
        ohlcv = make_ohlcv(200, base_price=100.0, price_step=0.5)

        validator = WalkForwardValidator(
            strategy_factory=AlwaysBuyStrategy,
            config=WalkForwardConfig(
                n_windows=3,
                train_ratio=0.70,
                min_train_bars=30,
                min_test_bars=10,
            ),
        )
        result = validator.run(ohlcv)

        assert isinstance(result, WalkForwardResult)
        assert result.n_windows == 3
        assert len(result.windows) == 3

    def test_train_test_split_sizes(self):
        """Each window has proper train/test split."""
        ohlcv = make_ohlcv(300, base_price=100.0, price_step=0.5)

        validator = WalkForwardValidator(
            strategy_factory=AlwaysBuyStrategy,
            config=WalkForwardConfig(
                n_windows=5,
                train_ratio=0.70,
                min_train_bars=30,
                min_test_bars=10,
            ),
        )
        result = validator.run(ohlcv)

        for w in result.windows:
            train_size = w.train_end - w.train_start
            test_size = w.test_end - w.test_start
            assert train_size >= 30  # min_train_bars
            assert test_size >= 10   # min_test_bars
            # Train should be larger than test (70/30 split)
            assert train_size >= test_size

    def test_windows_are_sequential(self):
        """Train data comes before test data in each window."""
        ohlcv = make_ohlcv(200)

        validator = WalkForwardValidator(
            strategy_factory=AlwaysBuyStrategy,
            config=WalkForwardConfig(n_windows=3, min_train_bars=30, min_test_bars=10),
        )
        result = validator.run(ohlcv)

        for w in result.windows:
            assert w.train_end <= w.test_start
            assert w.train_start < w.train_end
            assert w.test_start < w.test_end

    def test_aggregate_metrics_exist(self):
        """Aggregate metrics are computed for both train and test."""
        ohlcv = make_ohlcv(200)

        validator = WalkForwardValidator(
            strategy_factory=AlwaysBuyStrategy,
            config=WalkForwardConfig(n_windows=3, min_train_bars=30, min_test_bars=10),
        )
        result = validator.run(ohlcv)

        assert isinstance(result.aggregate_train_metrics, BacktestMetrics)
        assert isinstance(result.aggregate_test_metrics, BacktestMetrics)

    def test_overfitting_detection(self):
        """Overfitting score is computed and is_overfit is set."""
        ohlcv = make_ohlcv(200)

        validator = WalkForwardValidator(
            strategy_factory=AlwaysBuyStrategy,
            config=WalkForwardConfig(
                n_windows=3,
                min_train_bars=30,
                min_test_bars=10,
                overfit_threshold=3.0,
            ),
        )
        result = validator.run(ohlcv)

        assert isinstance(result.overfitting_score, float)
        assert isinstance(result.is_overfit, bool)
        assert result.overfitting_score >= 0.0

    def test_consistency_score_range(self):
        """Consistency score is between 0 and 1."""
        ohlcv = make_ohlcv(200)

        validator = WalkForwardValidator(
            strategy_factory=AlwaysBuyStrategy,
            config=WalkForwardConfig(n_windows=3, min_train_bars=30, min_test_bars=10),
        )
        result = validator.run(ohlcv)

        assert 0.0 <= result.consistency_score <= 1.0

    def test_data_too_short_raises(self):
        """Walk-forward with too little data raises ValueError."""
        ohlcv = make_ohlcv(10)

        validator = WalkForwardValidator(
            strategy_factory=AlwaysBuyStrategy,
            config=WalkForwardConfig(n_windows=5, min_train_bars=30, min_test_bars=10),
        )
        with pytest.raises(ValueError, match="too short"):
            validator.run(ohlcv)

    def test_with_optimization(self):
        """Walk-forward with an optimizer function."""
        ohlcv = make_ohlcv(200)

        def mock_optimize(
            strategy: BaseStrategy,
            train_data: list[OHLCV],
            config: BacktestConfig,
        ) -> dict[str, Any]:
            return {"threshold": 0.3, "multiplier": 1.5}

        validator = WalkForwardValidator(
            strategy_factory=OptimizableStrategy,
            optimize_fn=mock_optimize,
            config=WalkForwardConfig(
                n_windows=3,
                min_train_bars=30,
                min_test_bars=10,
            ),
        )
        result = validator.run(ohlcv)

        # Check that optimized params were recorded
        for w in result.windows:
            assert w.train_params == {"threshold": 0.3, "multiplier": 1.5}

    def test_anchored_walk_forward(self):
        """Anchored mode: train always starts from beginning."""
        ohlcv = make_ohlcv(300)

        validator = WalkForwardValidator(
            strategy_factory=AlwaysBuyStrategy,
            config=WalkForwardConfig(
                n_windows=3,
                anchored=True,
                min_train_bars=30,
                min_test_bars=10,
            ),
        )
        result = validator.run(ohlcv)

        for w in result.windows:
            assert w.train_start == 0  # always from beginning


# ═══════════════════════════════════════════════════════════════════════
# MONTE CARLO SIMULATOR TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestMonteCarloSimulator:
    """Monte Carlo simulation tests."""

    def _make_backtest_result(self, n_trades: int = 20) -> BacktestResult:
        """Create a synthetic BacktestResult with known trades."""
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        trades = []
        for i in range(n_trades):
            pnl_pct = 0.02 if i % 3 != 0 else -0.01  # 2/3 winners, 1/3 losers
            trades.append(TradeRecord(
                entry_time=start + timedelta(hours=i * 10),
                exit_time=start + timedelta(hours=i * 10 + 5),
                side="buy",
                entry_price=100.0,
                exit_price=100.0 * (1 + pnl_pct),
                quantity=10.0,
                pnl=100.0 * pnl_pct * 10.0,
                pnl_pct=pnl_pct,
                commission_total=0.0,
                exit_reason="take_profit" if pnl_pct > 0 else "stop_loss",
            ))

        # Build equity curve
        capital = 100_000.0
        equity = [capital]
        for t in trades:
            capital += t.pnl
            equity.append(capital)

        return BacktestResult(
            trades=tuple(trades),
            metrics=BacktestMetrics(
                total_return=(equity[-1] - 100_000) / 100_000,
                cagr=0.15,
                sharpe_ratio=1.5,
                sortino_ratio=2.0,
                calmar_ratio=1.0,
                max_drawdown=0.10,
                max_drawdown_duration=5,
                win_rate=0.67,
                profit_factor=2.0,
                avg_win=200.0,
                avg_loss=-100.0,
                total_trades=n_trades,
                winning_trades=int(n_trades * 0.67),
                losing_trades=n_trades - int(n_trades * 0.67),
                avg_trade_duration=5.0,
                expectancy=100.0,
            ),
            equity_curve=tuple(equity),
            config=BacktestConfig(),
            strategy_name="test",
            start_time=start,
            end_time=start + timedelta(hours=n_trades * 10),
            bar_count=n_trades * 10,
        )

    def test_monte_carlo_produces_result(self):
        """MC simulation produces a valid MonteCarloResult."""
        bt_result = self._make_backtest_result(20)
        simulator = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=100, random_seed=42)
        )
        result = simulator.run(bt_result)

        assert isinstance(result, MonteCarloResult)
        assert result.n_simulations == 100
        assert result.n_trades == 20

    def test_distributions_have_all_metrics(self):
        """All expected metric distributions are computed."""
        bt_result = self._make_backtest_result(20)
        result = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=50, random_seed=42)
        ).run(bt_result)

        expected_metrics = {
            "total_return", "sharpe_ratio", "max_drawdown",
            "win_rate", "profit_factor", "calmar_ratio",
        }
        assert set(result.distributions.keys()) == expected_metrics
        assert set(result.confidence_intervals.keys()) == expected_metrics

    def test_percentile_distribution_fields(self):
        """PercentileDistribution has all required fields."""
        bt_result = self._make_backtest_result(20)
        result = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=50, random_seed=42)
        ).run(bt_result)

        for name, dist in result.distributions.items():
            assert dist.metric_name == name
            assert isinstance(dist.percentiles, dict)
            assert isinstance(dist.mean, float)
            assert isinstance(dist.std, float)
            assert isinstance(dist.original, float)

    def test_confidence_intervals_have_percentiles(self):
        """Confidence intervals contain configured percentile levels."""
        bt_result = self._make_backtest_result(20)
        config = MonteCarloConfig(
            n_simulations=50,
            confidence_levels=(5.0, 50.0, 95.0),
            random_seed=42,
        )
        result = MonteCarloSimulator(config=config).run(bt_result)

        for ci in result.confidence_intervals.values():
            assert set(ci.keys()) == {5.0, 50.0, 95.0}

    def test_percentiles_are_ordered(self):
        """Percentile values should be monotonically increasing."""
        bt_result = self._make_backtest_result(30)
        result = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=200, random_seed=42)
        ).run(bt_result)

        for name, dist in result.distributions.items():
            if name == "max_drawdown":
                continue  # drawdown can be 0 for many sims
            levels = sorted(dist.percentiles.keys())
            values = [dist.percentiles[l] for l in levels]
            # Allow some tolerance for floating point
            for i in range(1, len(values)):
                assert values[i] >= values[i - 1] - 1e-10, (
                    f"{name}: percentile {levels[i]}={values[i]} < "
                    f"percentile {levels[i-1]}={values[i-1]}"
                )

    def test_probability_of_profit(self):
        """P(profit) should be between 0 and 1."""
        bt_result = self._make_backtest_result(20)
        result = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=100, random_seed=42)
        ).run(bt_result)

        assert 0.0 <= result.probability_of_profit <= 1.0

    def test_probability_of_ruin(self):
        """P(ruin) should be between 0 and 1."""
        bt_result = self._make_backtest_result(20)
        result = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=100, random_seed=42)
        ).run(bt_result)

        assert 0.0 <= result.probability_of_ruin <= 1.0

    def test_original_value_preserved(self):
        """Each distribution records the original backtest value."""
        bt_result = self._make_backtest_result(20)
        result = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=50, random_seed=42)
        ).run(bt_result)

        assert result.distributions["total_return"].original == bt_result.metrics.total_return
        assert result.distributions["sharpe_ratio"].original == bt_result.metrics.sharpe_ratio
        assert result.distributions["win_rate"].original == bt_result.metrics.win_rate

    def test_reproducibility_with_seed(self):
        """Same seed produces identical results."""
        bt_result = self._make_backtest_result(20)

        r1 = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=50, random_seed=42)
        ).run(bt_result)
        r2 = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=50, random_seed=42)
        ).run(bt_result)

        for metric in r1.distributions:
            assert r1.distributions[metric].mean == r2.distributions[metric].mean
            assert r1.distributions[metric].std == r2.distributions[metric].std

    def test_no_trades_raises(self):
        """MC on empty backtest raises ValueError."""
        bt_result = BacktestResult(
            trades=(),
            metrics=BacktestMetrics(
                total_return=0.0, cagr=0.0, sharpe_ratio=0.0, sortino_ratio=0.0,
                calmar_ratio=0.0, max_drawdown=0.0, max_drawdown_duration=0,
                win_rate=0.0, profit_factor=0.0, avg_win=0.0, avg_loss=0.0,
                total_trades=0, winning_trades=0, losing_trades=0,
                avg_trade_duration=0.0, expectancy=0.0,
            ),
            equity_curve=(100_000.0,),
            config=BacktestConfig(),
            strategy_name="empty",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            bar_count=1,
        )

        with pytest.raises(ValueError, match="no trades"):
            MonteCarloSimulator().run(bt_result)

    def test_single_trade_mc(self):
        """MC with only one trade — all permutations are identical."""
        bt_result = self._make_backtest_result(1)
        result = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=50, random_seed=42)
        ).run(bt_result)

        # With 1 trade, all permutations produce the same result
        dist = result.distributions["total_return"]
        assert dist.std == 0.0 or dist.std < 1e-10
        assert dist.min_val == dist.max_val

    def test_confidence_intervals_dict(self):
        """Confidence intervals is a dict of dicts."""
        bt_result = self._make_backtest_result(20)
        result = MonteCarloSimulator(
            config=MonteCarloConfig(n_simulations=50, random_seed=42)
        ).run(bt_result)

        assert isinstance(result.confidence_intervals, dict)
        for key, ci in result.confidence_intervals.items():
            assert isinstance(ci, dict)
            for pct, val in ci.items():
                assert isinstance(pct, float)
                assert isinstance(val, float)


class TestMonteCarloIntegration:
    """Integration: MC on real backtest output."""

    def test_mc_on_backtest_result(self):
        """Run MC on output of a real backtest engine run."""
        # Use alternating strategy so we get both wins and losses
        # (avoids inf profit_factor from all-winners)
        ohlcv = make_ohlcv(100, base_price=100.0, price_step=0.5)
        bt_result = BacktestEngine(
            AlternatingStrategy(),
            config=BacktestConfig(commission_bps=10.0, slippage_bps=5.0),
        ).run(ohlcv)

        if len(bt_result.trades) > 0:
            mc_result = MonteCarloSimulator(
                config=MonteCarloConfig(n_simulations=100, random_seed=42)
            ).run(bt_result)

            assert mc_result.n_trades == len(bt_result.trades)
            assert mc_result.original_result is bt_result


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION: BACKTEST → WALK-FORWARD → MONTE CARLO
# ═══════════════════════════════════════════════════════════════════════


class TestFullPipeline:
    """End-to-end: backtest → walk-forward → Monte Carlo."""

    def test_full_pipeline(self):
        """Run the complete validation pipeline."""
        ohlcv = make_ohlcv(300, base_price=100.0, price_step=0.5)

        # Step 1: Walk-forward validation
        wf_validator = WalkForwardValidator(
            strategy_factory=AlternatingStrategy,
            config=WalkForwardConfig(
                n_windows=3,
                train_ratio=0.70,
                min_train_bars=30,
                min_test_bars=10,
            ),
        )
        wf_result = wf_validator.run(ohlcv)

        # Step 2: Monte Carlo on the aggregate test performance
        # Use the last window's test result for MC
        last_window = wf_result.windows[-1]
        if len(last_window.test_result.trades) > 0:
            mc_simulator = MonteCarloSimulator(
                config=MonteCarloConfig(n_simulations=100, random_seed=42)
            )
            mc_result = mc_simulator.run(last_window.test_result)

            assert mc_result.n_simulations == 100
            assert mc_result.probability_of_profit >= 0.0

        # Verify walk-forward results
        assert wf_result.n_windows == 3
        assert isinstance(wf_result.overfitting_score, float)
        assert isinstance(wf_result.consistency_score, float)
