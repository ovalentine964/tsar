"""
TSAR Interface — PricingEngine Abstract Base Class.

Abstracts all quantitative computation — technical indicators, pattern
detection, and OHLCV analysis. All methods are stateless (pure functions).

All methods are async to support both sync backends (via run_in_executor)
and native async backends (Rust via PyO3, QuantLib via async FFI).

Day1: PandasTAEngine (pandas-ta + numpy) — sync internally, wrapped as async
Level 2: RustTickEngine (Rust tick processor via PyO3) — native async
Level 3: QuantLibEngine (C++ QuantLib via pybind11) — native async
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.interfaces.types import (
        OHLCV,
        BollingerResult,
        MACDResult,
        SRLevels,
    )


class PricingEngine(abc.ABC):
    """Abstract interface for pricing and quantitative computation.

    All methods are async — backends that are natively sync (like pandas-ta)
    should use ``asyncio.get_event_loop().run_in_executor()`` internally
    to avoid blocking the event loop.

    All methods are stateless — no side effects, no exchange calls.
    Backends may use different internal libraries (pandas-ta, Rust, QuantLib)
    but expose identical interfaces.

    Day1: PandasTAEngine — pandas-ta for indicators, numpy for math.
    Level 2: RustTickEngine — Rust OHLCV aggregation (10-100x faster).
    Level 3: QuantLibEngine — C++ QuantLib for exotic options.
    """

    # ═══════════════════════════════════════════════════════════════
    # TECHNICAL INDICATORS
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def calculate_rsi(self, closes: list[float], period: int = 14) -> float:
        """Calculate Relative Strength Index (RSI).

        Measures the magnitude of recent price changes to evaluate
        overbought or oversold conditions.

        Args:
            closes: List of closing prices, oldest first.
            period: Lookback period (default 14).

        Returns:
            Latest RSI value (0-100). Returns 50.0 if insufficient data.

        Raises:
            ValueError: If closes is empty or period < 1.
        """
        ...

    @abc.abstractmethod
    async def calculate_macd(
        self,
        closes: list[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> MACDResult:
        """Calculate MACD (Moving Average Convergence Divergence).

        Trend-following momentum indicator showing the relationship
        between two moving averages of prices.

        Args:
            closes: List of closing prices, oldest first.
            fast: Fast EMA period (default 12).
            slow: Slow EMA period (default 26).
            signal: Signal line EMA period (default 9).

        Returns:
            MACDResult with macd_line, signal_line, and histogram tuples.

        Raises:
            ValueError: If closes is empty or period parameters are invalid.
        """
        ...

    @abc.abstractmethod
    async def calculate_bollinger(
        self,
        closes: list[float],
        period: int = 20,
        std_dev: float = 2.0,
    ) -> BollingerResult:
        """Calculate Bollinger Bands.

        Volatility bands placed above and below a moving average,
        set at a specified number of standard deviations.

        Args:
            closes: List of closing prices, oldest first.
            period: SMA lookback period (default 20).
            std_dev: Number of standard deviations for bands (default 2.0).

        Returns:
            BollingerResult with upper, middle, lower, and bandwidth tuples.

        Raises:
            ValueError: If closes is empty or period < 1.
        """
        ...

    @abc.abstractmethod
    async def calculate_atr(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> float:
        """Calculate Average True Range (ATR).

        Measures market volatility by decomposing the entire range of
        price movement for each period.

        Args:
            highs: List of high prices, oldest first.
            lows: List of low prices, oldest first.
            closes: List of closing prices, oldest first.
            period: Lookback period (default 14).

        Returns:
            Latest ATR value. Returns 0.0 if insufficient data.

        Raises:
            ValueError: If price lists are empty, have different lengths,
                or period < 1.
        """
        ...

    @abc.abstractmethod
    async def calculate_ema(self, data: list[float], period: int = 20) -> list[float]:
        """Calculate Exponential Moving Average (EMA).

        A type of moving average that places a greater weight and
        significance on the most recent data points.

        Args:
            data: List of values, oldest first.
            period: EMA lookback period (default 20).

        Returns:
            List of EMA values (shorter than input by period-1 elements).

        Raises:
            ValueError: If data is empty or period < 1.
        """
        ...

    @abc.abstractmethod
    async def detect_support_resistance(
        self,
        ohlcv: list[OHLCV],
    ) -> SRLevels:
        """Detect support and resistance levels from OHLCV data.

        Analyzes price action to identify key price levels where
        buying or selling pressure has historically concentrated.

        Args:
            ohlcv: List of OHLCV candles, oldest first.

        Returns:
            SRLevels with supports and resistances as SRLevel tuples.

        Raises:
            ValueError: If ohlcv is empty.
        """
        ...
