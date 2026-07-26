"""Tests for ExchangeGatewayOHLCVAdapter.

Verifies G2: The adapter correctly wraps ExchangeGateway.get_ohlcv()
and returns OHLCV objects convertible to OHLCVCandle for RuleValidator.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.interfaces.types import OHLCV, Timeframe
from src.knowledge.ohlcv_adapter import ExchangeGatewayOHLCVAdapter, _TIMEFRAME_MAP
from src.knowledge.rule_validator import OHLCVCandle


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _make_ohlcv(n: int = 10, base_price: float = 50000.0) -> list[OHLCV]:
    """Create n sample OHLCV candles."""
    candles = []
    ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(n):
        price = base_price + i * 100
        candles.append(OHLCV(
            timestamp=ts,
            open=price - 50,
            high=price + 100,
            low=price - 100,
            close=price,
            volume=1000.0 + i * 10,
        ))
    return candles


def _mock_gateway(ohlcv_data: list[OHLCV] | None = None) -> AsyncMock:
    """Create a mock ExchangeGateway that returns given OHLCV data."""
    gw = AsyncMock()
    data = ohlcv_data if ohlcv_data is not None else _make_ohlcv()
    gw.get_ohlcv = AsyncMock(return_value=data)
    return gw


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Timeframe Mapping
# ═══════════════════════════════════════════════════════════════════════


def test_timeframe_map_covers_all_enum_values():
    """Every Timeframe enum value should have a string mapping."""
    for tf in Timeframe:
        assert tf.value in _TIMEFRAME_MAP, f"Missing mapping for {tf.value}"


def test_timeframe_map_values_are_timeframe_enums():
    """All mapped values should be Timeframe enum instances."""
    for key, val in _TIMEFRAME_MAP.items():
        assert isinstance(val, Timeframe), f"{key} maps to {type(val)}, not Timeframe"


@pytest.mark.parametrize("tf_str,expected_enum", [
    ("1m", Timeframe.M1),
    ("5m", Timeframe.M5),
    ("15m", Timeframe.M15),
    ("30m", Timeframe.M30),
    ("1h", Timeframe.H1),
    ("4h", Timeframe.H4),
    ("1d", Timeframe.D1),
    ("1w", Timeframe.W1),
])
def test_timeframe_map_specific(tf_str: str, expected_enum: Timeframe):
    """Each timeframe string maps to the correct enum."""
    assert _TIMEFRAME_MAP[tf_str] == expected_enum


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Basic Adapter Functionality
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_candles_returns_ohlcv_candle_list():
    """Adapter should return a list of OHLCV objects."""
    gw = _mock_gateway(_make_ohlcv(5))
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    candles = await adapter.get_candles("BTC/USDT", "1h", limit=5)

    assert len(candles) == 5
    assert all(isinstance(c, OHLCVCandle) for c in candles)


@pytest.mark.asyncio
async def test_get_candles_passes_correct_params():
    """Adapter should translate string timeframe and pass params to gateway."""
    gw = _mock_gateway()
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    await adapter.get_candles("ETH/USDT", "4h", limit=200)

    gw.get_ohlcv.assert_called_once_with(
        symbol="ETH/USDT",
        timeframe=Timeframe.H4,
        limit=200,
    )


@pytest.mark.asyncio
async def test_get_candles_default_params():
    """Default timeframe='1h' and limit=500."""
    gw = _mock_gateway()
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    await adapter.get_candles("BTC/USDT")

    gw.get_ohlcv.assert_called_once_with(
        symbol="BTC/USDT",
        timeframe=Timeframe.H1,
        limit=500,
    )


# ═══════════════════════════════════════════════════════════════════════
# TESTS: OHLCV → OHLCVCandle Conversion
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_candle_conversion_preserves_values():
    """OHLCV fields should be preserved in OHLCVCandle."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    ohlcv_data = [OHLCV(
        timestamp=ts,
        open=49000.0,
        high=51000.0,
        low=48500.0,
        close=50500.0,
        volume=12345.67,
    )]
    gw = _mock_gateway(ohlcv_data)
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    candles = await adapter.get_candles("BTC/USDT", "1h", limit=1)

    assert len(candles) == 1
    c = candles[0]
    assert c.open == 49000.0
    assert c.high == 51000.0
    assert c.low == 48500.0
    assert c.close == 50500.0
    assert c.volume == 12345.67


@pytest.mark.asyncio
async def test_candle_conversion_timestamp_isoformat():
    """Timestamp should be converted to ISO format string."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    ohlcv_data = [OHLCV(
        timestamp=ts,
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=1000.0,
    )]
    gw = _mock_gateway(ohlcv_data)
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    candles = await adapter.get_candles("BTC/USDT", "1h", limit=1)

    assert candles[0].timestamp == "2025-06-15T10:30:00+00:00"


@pytest.mark.asyncio
async def test_candle_conversion_empty_list():
    """Empty gateway response should return empty list."""
    gw = _mock_gateway([])
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    candles = await adapter.get_candles("BTC/USDT", "1h", limit=100)

    assert candles == []


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Error Handling
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_invalid_timeframe_raises_value_error():
    """Unknown timeframe string should raise ValueError."""
    gw = _mock_gateway()
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    with pytest.raises(ValueError, match="Unknown timeframe"):
        await adapter.get_candles("BTC/USDT", "invalid_tf")


@pytest.mark.asyncio
async def test_invalid_timeframe_mentions_supported():
    """ValueError message should list supported timeframes."""
    gw = _mock_gateway()
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    with pytest.raises(ValueError, match="Supported:"):
        await adapter.get_candles("BTC/USDT", "2h")


@pytest.mark.asyncio
async def test_gateway_exception_propagates():
    """Exceptions from gateway should propagate."""
    gw = AsyncMock()
    gw.get_ohlcv = AsyncMock(side_effect=ConnectionError("not connected"))
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    with pytest.raises(ConnectionError):
        await adapter.get_candles("BTC/USDT", "1h")


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Multiple Candles
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_large_batch_conversion():
    """Converting 500 candles should work without issues."""
    data = _make_ohlcv(500)
    gw = _mock_gateway(data)
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    candles = await adapter.get_candles("BTC/USDT", "1h", limit=500)

    assert len(candles) == 500
    # Spot check first and last
    assert candles[0].open == 50000.0 - 50
    assert candles[-1].close == 50000.0 + 499 * 100


@pytest.mark.asyncio
async def test_all_timeframe_strings_work():
    """All supported timeframe strings should pass through without error."""
    gw = _mock_gateway(_make_ohlcv(3))
    adapter = ExchangeGatewayOHLCVAdapter(gw)

    for tf_str in _TIMEFRAME_MAP:
        gw.get_ohlcv.reset_mock()
        candles = await adapter.get_candles("BTC/USDT", tf_str, limit=3)
        assert len(candles) == 3
        gw.get_ohlcv.assert_called_once()
