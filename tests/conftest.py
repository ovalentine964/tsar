"""
TSAR Test Suite — Shared Fixtures.

Provides mock exchange gateway, pricing engine, execution engine,
and sample data for all test modules.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.interfaces.types import (
    Balance,
    BollingerResult,
    DrawdownLevel,
    MACDResult,
    OHLCV,
    OrderBook,
    OrderBookLevel,
    OrderSide,
    OrderType,
    OrderStatus,
    Portfolio,
    Position,
    Price,
    SRLevel,
    SRLevels,
    Signal,
    Trade,
    Timeframe,
    ExecutionResult,
    Fill,
    Order,
)


# ═══════════════════════════════════════════════════════════════════════
# TIMESTAMPS
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def now() -> datetime:
    """Current UTC timestamp."""
    return datetime.now(timezone.utc)


@pytest.fixture
def fixed_ts() -> datetime:
    """Fixed timestamp for deterministic tests."""
    return datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════
# SAMPLE MARKET DATA
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_price(fixed_ts: datetime) -> Price:
    """Sample BTC/USDT price."""
    return Price(
        symbol="BTC/USDT",
        last=50000.0,
        bid=49999.0,
        ask=50001.0,
        timestamp=fixed_ts,
    )


@pytest.fixture
def sample_ohlcv(fixed_ts: datetime) -> list[OHLCV]:
    """100-sample OHLCV data with a downtrend then uptrend (mean reversion pattern)."""
    from datetime import timedelta

    candles: list[OHLCV] = []
    base_price = 50000.0
    for i in range(100):
        # Create a V-shaped price pattern
        if i < 50:
            close = base_price - (50 - i) * 20  # Downtrend
        else:
            close = base_price - (i - 50) * 20 + 2000  # Uptrend from low

        high = close + 100
        low = close - 100
        opn = close - 50
        volume = 1000.0 + i * 10

        candles.append(OHLCV(
            timestamp=fixed_ts + timedelta(hours=i),
            open=opn,
            high=high,
            low=low,
            close=close,
            volume=volume,
        ))
    return candles


@pytest.fixture
def sample_closes(sample_ohlcv: list[OHLCV]) -> list[float]:
    """Close prices from sample OHLCV."""
    return [c.close for c in sample_ohlcv]


@pytest.fixture
def sample_highs(sample_ohlcv: list[OHLCV]) -> list[float]:
    """High prices from sample OHLCV."""
    return [c.high for c in sample_ohlcv]


@pytest.fixture
def sample_lows(sample_ohlcv: list[OHLCV]) -> list[float]:
    """Low prices from sample OHLCV."""
    return [c.low for c in sample_ohlcv]


@pytest.fixture
def sample_volumes(sample_ohlcv: list[OHLCV]) -> list[float]:
    """Volumes from sample OHLCV."""
    return [c.volume for c in sample_ohlcv]


# ═══════════════════════════════════════════════════════════════════════
# SAMPLE ACCOUNT DATA
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_balance() -> Balance:
    """Sample account balance."""
    return Balance(
        total=100000.0,
        free=80000.0,
        used=20000.0,
        currency="USDT",
    )


@pytest.fixture
def sample_position(fixed_ts: datetime) -> Position:
    """Sample open BTC/USDT long position."""
    return Position(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=0.1,
        entry_price=50000.0,
        current_price=50500.0,
        unrealized_pnl=50.0,
        leverage=1.0,
        timestamp=fixed_ts,
    )


@pytest.fixture
def sample_positions(sample_position: Position) -> tuple[Position, ...]:
    """Tuple of sample positions."""
    return (sample_position,)


# ═══════════════════════════════════════════════════════════════════════
# SAMPLE PORTFOLIOS (various risk states)
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def portfolio_green() -> Portfolio:
    """Healthy portfolio — GREEN drawdown state."""
    return Portfolio(
        equity=100000.0,
        high_water_mark=100000.0,
        cash=90000.0,
        positions=(),
        daily_pnl=500.0,
        daily_pnl_pct=0.005,
        open_position_count=0,
    )


@pytest.fixture
def portfolio_yellow() -> Portfolio:
    """Portfolio in YELLOW drawdown (2-3%)."""
    return Portfolio(
        equity=97500.0,
        high_water_mark=100000.0,
        cash=97500.0,
        positions=(),
        daily_pnl=-500.0,
        daily_pnl_pct=-0.005,
        open_position_count=0,
    )


@pytest.fixture
def portfolio_orange() -> Portfolio:
    """Portfolio in ORANGE drawdown (3-5%)."""
    return Portfolio(
        equity=96000.0,
        high_water_mark=100000.0,
        cash=96000.0,
        positions=(),
        daily_pnl=-1500.0,
        daily_pnl_pct=-0.015,
        open_position_count=0,
    )


@pytest.fixture
def portfolio_red() -> Portfolio:
    """Portfolio in RED drawdown (>5%)."""
    return Portfolio(
        equity=94000.0,
        high_water_mark=100000.0,
        cash=94000.0,
        positions=(),
        daily_pnl=-3000.0,
        daily_pnl_pct=-0.03,
        open_position_count=0,
    )


@pytest.fixture
def portfolio_full() -> Portfolio:
    """Portfolio at max open positions."""
    positions = tuple(
        Position(
            symbol=f"COIN{i}/USDT",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=100.0,
            current_price=100.0,
            unrealized_pnl=0.0,
        )
        for i in range(10)
    )
    return Portfolio(
        equity=100000.0,
        high_water_mark=100000.0,
        cash=80000.0,
        positions=positions,
        open_position_count=10,
    )


# ═══════════════════════════════════════════════════════════════════════
# SAMPLE SIGNALS
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def buy_signal(fixed_ts: datetime) -> Signal:
    """Valid BUY signal."""
    return Signal(
        signal_id="sig-test-001",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        score=0.75,
        entry_price=50000.0,
        stop_loss=49500.0,
        take_profit=51000.0,
        strategy="mean_reversion",
        reasoning="RSI=25 oversold near support",
        metadata={},
        timestamp=fixed_ts,
    )


@pytest.fixture
def sell_signal(fixed_ts: datetime) -> Signal:
    """Valid SELL signal."""
    return Signal(
        signal_id="sig-test-002",
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        score=0.70,
        entry_price=50000.0,
        stop_loss=50500.0,
        take_profit=49000.0,
        strategy="mean_reversion",
        reasoning="RSI=75 overbought near resistance",
        metadata={},
        timestamp=fixed_ts,
    )


@pytest.fixture
def weak_signal(fixed_ts: datetime) -> Signal:
    """Signal with low score (anti-FOMO trigger)."""
    return Signal(
        signal_id="sig-test-003",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        score=0.3,
        entry_price=50000.0,
        stop_loss=49500.0,
        take_profit=51000.0,
        strategy="mean_reversion",
        reasoning="Weak setup",
        metadata={},
        timestamp=fixed_ts,
    )


@pytest.fixture
def signal_no_stoploss(fixed_ts: datetime) -> Signal:
    """Signal without stop-loss."""
    return Signal(
        signal_id="sig-test-004",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        score=0.8,
        entry_price=50000.0,
        stop_loss=0.0,
        take_profit=51000.0,
        strategy="mean_reversion",
        reasoning="No SL",
        metadata={},
        timestamp=fixed_ts,
    )


@pytest.fixture
def signal_bad_rr(fixed_ts: datetime) -> Signal:
    """Signal with poor risk:reward ratio."""
    return Signal(
        signal_id="sig-test-005",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        score=0.8,
        entry_price=50000.0,
        stop_loss=49500.0,   # risk = 500
        take_profit=50600.0, # reward = 600 → R:R = 1.2:1
        strategy="mean_reversion",
        reasoning="Poor R:R",
        metadata={},
        timestamp=fixed_ts,
    )


# ═══════════════════════════════════════════════════════════════════════
# SAMPLE TRADES & ORDERS
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_trade(fixed_ts: datetime) -> Trade:
    """Sample executed trade."""
    return Trade(
        id="trade-001",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        price=50000.0,
        quantity=0.1,
        cost=5000.0,
        fee=5.0,
        fee_currency="USDT",
        timestamp=fixed_ts,
    )


@pytest.fixture
def sample_order(fixed_ts: datetime) -> Order:
    """Sample order."""
    return Order(
        order_id="ord-001",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=0.1,
        price=50000.0,
        status=OrderStatus.OPEN,
        timestamp=fixed_ts,
    )


# ═══════════════════════════════════════════════════════════════════════
# MOCK ENGINES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_gateway() -> AsyncMock:
    """Mock exchange gateway."""
    gw = AsyncMock()
    gw.connect = AsyncMock()
    gw.disconnect = AsyncMock()
    gw.health_check = AsyncMock(return_value=True)
    gw.get_price = AsyncMock(return_value=Price(
        symbol="BTC/USDT", last=50000.0, bid=49999.0, ask=50001.0,
        timestamp=datetime.now(timezone.utc),
    ))
    gw.get_balance = AsyncMock(return_value={
        "USDT": Balance(total=100000.0, free=80000.0, used=20000.0),
    })
    gw.get_positions = AsyncMock(return_value=[])
    return gw


@pytest.fixture
def mock_pricing_engine() -> MagicMock:
    """Mock pricing engine with realistic defaults."""
    engine = MagicMock()
    engine.calculate_rsi = MagicMock(return_value=25.0)
    engine.calculate_macd = MagicMock(return_value=MACDResult(
        macd_line=(-100.0, -80.0, -60.0),
        signal_line=(-90.0, -85.0, -80.0),
        histogram=(-10.0, 5.0, 20.0),
    ))
    engine.calculate_bollinger = MagicMock(return_value=BollingerResult(
        upper=(51000.0, 51000.0, 51000.0),
        middle=(50000.0, 50000.0, 50000.0),
        lower=(49000.0, 49000.0, 49000.0),
        bandwidth=(0.04, 0.04, 0.04),
    ))
    engine.calculate_atr = MagicMock(return_value=500.0)
    engine.calculate_ema = MagicMock(return_value=[49800.0, 49900.0, 50000.0])
    engine.detect_support_resistance = MagicMock(return_value=SRLevels(
        supports=(
            SRLevel(price=49000.0, strength=0.8, level_type="support", touches=3),
            SRLevel(price=48000.0, strength=0.6, level_type="support", touches=2),
        ),
        resistances=(
            SRLevel(price=51000.0, strength=0.8, level_type="resistance", touches=3),
            SRLevel(price=52000.0, strength=0.6, level_type="resistance", touches=2),
        ),
    ))
    return engine


@pytest.fixture
def mock_execution_engine() -> AsyncMock:
    """Mock execution engine."""
    engine = AsyncMock()
    engine.execute_order = AsyncMock(return_value=ExecutionResult(
        order_id="ord-001",
        symbol="BTC/USDT",
        status=OrderStatus.FILLED,
        filled_quantity=0.1,
        average_price=50000.0,
        total_fee=5.0,
        fills=(Fill(
            fill_id="fill-001",
            order_id="ord-001",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            price=50000.0,
            quantity=0.1,
            fee=5.0,
            fee_currency="USDT",
            timestamp=datetime.now(timezone.utc),
        ),),
        slippage_bps=0.5,
    ))
    engine.cancel_order = AsyncMock(return_value=True)
    engine.get_order_status = AsyncMock(return_value=OrderStatus.FILLED)
    engine.get_open_orders = AsyncMock(return_value=[])
    return engine


# ═══════════════════════════════════════════════════════════════════════
# RISK CONFIG
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def default_risk_config() -> dict[str, Any]:
    """Default risk configuration matching risk.yaml defaults."""
    return {
        "max_open_positions": 10,
        "max_single_position_pct": 0.15,
        "max_stop_loss_pct": 0.02,
        "stop_loss_required": True,
        "min_rr_ratio": 2.0,
        "max_daily_trades": 30,
        "anti_fomo_min_signal_score": 0.6,
        "kelly_fraction": 0.25,
        "risk_per_trade_pct": 0.02,
        "daily_loss_flatten": -0.02,
        "daily_loss_kill": -0.03,
        "max_drawdown_halt": -0.05,
        "max_drawdown_flatten": -0.15,
        "anti_revenge_cooldown_minutes": 60,
        "anti_revenge_loss_streak": 3,
        "anti_greed_sizing_factor": 0.7,
        "anti_greed_win_streak": 5,
        "anti_overconfidence_win_streak": 5,
    }
