"""TSAR — OHLCV Provider Adapter.

Adapter that wraps ExchangeGateway to satisfy the OHLCVProvider protocol
used by RuleValidator. Translates between the interface layer's OHLCV
types and the knowledge layer's OHLCVCandle types.

Bridge: ExchangeGateway.get_ohlcv() → OHLCVProvider.get_candles()
"""

from __future__ import annotations

from typing import Optional

from src.interfaces.exchange_gateway import ExchangeGateway
from src.interfaces.types import OHLCV, Timeframe
from src.knowledge.rule_validator import OHLCVCandle
from src.utils.logging import get_logger

logger = get_logger(__name__)

# String timeframe → Timeframe enum mapping
_TIMEFRAME_MAP: dict[str, Timeframe] = {
    "1m": Timeframe.M1,
    "5m": Timeframe.M5,
    "15m": Timeframe.M15,
    "30m": Timeframe.M30,
    "1h": Timeframe.H1,
    "4h": Timeframe.H4,
    "1d": Timeframe.D1,
    "1w": Timeframe.W1,
}


def _convert_candle(ohlcv: OHLCV) -> OHLCVCandle:
    """Convert an interface-layer OHLCV to a knowledge-layer OHLCVCandle."""
    return OHLCVCandle(
        timestamp=ohlcv.timestamp.isoformat() if hasattr(ohlcv.timestamp, "isoformat") else str(ohlcv.timestamp),
        open=ohlcv.open,
        high=ohlcv.high,
        low=ohlcv.low,
        close=ohlcv.close,
        volume=ohlcv.volume,
    )


class ExchangeGatewayOHLCVAdapter:
    """Adapter: ExchangeGateway → OHLCVProvider protocol.

    Wraps an ExchangeGateway instance and provides the get_candles()
    method expected by RuleValidator. Handles timeframe string-to-enum
    mapping and OHLCV-to-OHLCVCandle conversion.

    Usage::

        from src.interfaces import get_exchange_gateway
        from src.knowledge.ohlcv_adapter import ExchangeGatewayOHLCVAdapter

        gateway = get_exchange_gateway()
        adapter = ExchangeGatewayOHLCVAdapter(gateway)
        candles = await adapter.get_candles("BTC/USDT", "1h", limit=500)
    """

    def __init__(self, gateway: ExchangeGateway) -> None:
        self._gateway = gateway

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
        since: Optional[str] = None,
    ) -> list[OHLCVCandle]:
        """Fetch historical OHLCV candles from the exchange gateway.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            timeframe: Candle interval as string (e.g. "1h", "4h", "1d").
            limit: Number of candles to return.
            since: Unused — included for OHLCVProvider protocol compatibility.

        Returns:
            List of OHLCVCandle objects.

        Raises:
            ValueError: If timeframe string is not recognized.
            ConnectionError: If gateway is not connected.
        """
        tf = _TIMEFRAME_MAP.get(timeframe)
        if tf is None:
            raise ValueError(
                f"Unknown timeframe: {timeframe!r}. "
                f"Supported: {', '.join(sorted(_TIMEFRAME_MAP.keys()))}"
            )

        ohlcv_list: list[OHLCV] = await self._gateway.get_ohlcv(
            symbol=symbol,
            timeframe=tf,
            limit=limit,
        )

        candles = [_convert_candle(o) for o in ohlcv_list]

        logger.debug(
            "ohlcv_adapter_fetched",
            symbol=symbol,
            timeframe=timeframe,
            requested=limit,
            received=len(candles),
        )
        return candles
