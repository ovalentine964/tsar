"""
VMPM Level Mapper — Support/Resistance mapping with institutional levels.

Maps S/R from multiple sources:
  - Asian session high/low (daily range boundaries)
  - Daily/Weekly/Monthly/Yearly OHLC levels
  - Order blocks (institutional supply/demand zones)
  - Swing structure levels from TrendDetector

Each level has a type, strength score, and proximity check.
Levels are ranked by strength and proximity to current price.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class LevelType(StrEnum):
    """Types of support/resistance levels."""

    ORDER_BLOCK = "order_block"
    ASIAN_HIGH = "asian_high"
    ASIAN_LOW = "asian_low"
    DAILY_HIGH = "daily_high"
    DAILY_LOW = "daily_low"
    DAILY_OPEN = "daily_open"
    WEEKLY_HIGH = "weekly_high"
    WEEKLY_LOW = "weekly_low"
    WEEKLY_OPEN = "weekly_open"
    MONTHLY_HIGH = "monthly_high"
    MONTHLY_LOW = "monthly_low"
    YEARLY_OPEN = "yearly_open"
    YEARLY_HIGH = "yearly_high"
    YEARLY_LOW = "yearly_low"
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"


class LevelSide(StrEnum):
    """Whether a level acts as support or resistance."""

    SUPPORT = "support"
    RESISTANCE = "resistance"


@dataclass(frozen=True)
class SRLevel:
    """A single support/resistance level."""

    price: float
    level_type: LevelType
    side: LevelSide
    strength: float  # 0.0 – 1.0
    source: str  # Human-readable source description
    timeframe: str  # D1, H4, H1, etc.
    touches: int  # Number of times price has tested this level
    last_test_distance_pct: float  # Distance from last test (%)


@dataclass(frozen=True)
class OrderBlock:
    """An institutional order block (supply/demand zone)."""

    high: float
    low: float
    mid: float
    side: LevelSide  # Supply (resistance) or Demand (support)
    strength: float
    candle_index: int
    timeframe: str
    mitigated: bool  # True if price has returned and consumed the block


@dataclass(frozen=True)
class MappedLevels:
    """Complete S/R map for a trading pair."""

    levels: tuple[SRLevel, ...]
    order_blocks: tuple[OrderBlock, ...]
    supports: tuple[SRLevel, ...]
    resistances: tuple[SRLevel, ...]
    nearest_support: SRLevel | None
    nearest_resistance: SRLevel | None
    asian_high: float | None
    asian_low: float | None
    daily_open: float | None


class LevelMapper:
    """S/R level mapping engine for VMPM.

    Maps institutional-grade levels from multiple sources:
      - Asian session high/low
      - Daily/Weekly/Monthly/Yearly OHLC
      - Order blocks (supply/demand zones)
      - Swing structure levels

    Usage::

        mapper = LevelMapper(config)
        levels = mapper.map_levels(
            current_price=1.0850,
            d1_ohlcv=daily_bars,
            h4_ohlcv=h4_bars,
            h1_ohlcv=h1_bars,
            asian_high=1.0880,
            asian_low=1.0820,
        )
        if levels.nearest_support:
            # Price near support — potential long setup
    """

    def __init__(self, config: dict[str, Any] | None = None, *, genome: dict[str, Any] | None = None) -> None:
        self._config = config or genome or {}
        sr_config = self._config.get("sr_levels", {})

        self._asian_enabled = sr_config.get("asian_session", {}).get("enabled", True)
        self._daily_enabled = sr_config.get("daily_levels", {}).get("enabled", True)
        self._weekly_enabled = sr_config.get("weekly_levels", {}).get("enabled", True)
        self._monthly_enabled = sr_config.get("monthly_levels", {}).get("enabled", True)
        self._yearly_enabled = sr_config.get("yearly_levels", {}).get("enabled", True)
        self._ob_enabled = sr_config.get("order_blocks", {}).get("enabled", True)

        self._ob_min_body_pct = sr_config.get("order_blocks", {}).get("min_body_pct", 0.3)
        self._ob_lookback = sr_config.get("order_blocks", {}).get("lookback_candles", 100)
        self._ob_proximity_pct = sr_config.get("order_blocks", {}).get("proximity_pct", 0.3)

        # Level strength weights
        self._level_weights = sr_config.get("level_weights", {
            "order_block": 1.0,
            "asian_hl": 0.9,
            "daily_hl": 0.8,
            "weekly_hl": 0.7,
            "monthly_hl": 0.6,
            "yearly": 0.5,
        })

        # Mutable params
        mutable = self._config.get("mutable_parameters", {})
        self._proximity_pct = mutable.get("sr_proximity_pct", {}).get("current", 0.3)

    def map_levels(
        self,
        current_price: float,
        d1_ohlcv: list[dict[str, float]] | None = None,
        h4_ohlcv: list[dict[str, float]] | None = None,
        h1_ohlcv: list[dict[str, float]] | None = None,
        asian_high: float | None = None,
        asian_low: float | None = None,
        swing_highs: list[float] | None = None,
        swing_lows: list[float] | None = None,
    ) -> MappedLevels:
        """Map all S/R levels for a trading pair.

        Args:
            current_price: Current market price.
            d1_ohlcv: Daily OHLCV bars (list of dicts with 'open','high','low','close').
            h4_ohlcv: 4-hour OHLCV bars.
            h1_ohlcv: 1-hour OHLCV bars.
            asian_high: Asian session high price.
            asian_low: Asian session low price.
            swing_highs: Recent swing high prices.
            swing_lows: Recent swing low prices.

        Returns:
            MappedLevels with all detected levels.
        """
        levels: list[SRLevel] = []
        order_blocks: list[OrderBlock] = []

        # ── Asian session levels ──
        if self._asian_enabled:
            levels.extend(self._map_asian_levels(asian_high, asian_low, current_price))

        # ── Daily OHLC levels ──
        if self._daily_enabled and d1_ohlcv and len(d1_ohlcv) >= 2:
            levels.extend(self._map_period_levels(
                d1_ohlcv, "D1", current_price,
                include_open=True,
            ))

        # ── Weekly levels (from daily bars) ──
        if self._weekly_enabled and d1_ohlcv and len(d1_ohlcv) >= 5:
            levels.extend(self._map_weekly_from_daily(d1_ohlcv, current_price))

        # ── Monthly levels (from daily bars) ──
        if self._monthly_enabled and d1_ohlcv and len(d1_ohlcv) >= 20:
            levels.extend(self._map_monthly_from_daily(d1_ohlcv, current_price))

        # ── Yearly levels ──
        if self._yearly_enabled and d1_ohlcv and len(d1_ohlcv) >= 200:
            levels.extend(self._map_yearly_levels(d1_ohlcv, current_price))

        # ── Order blocks ──
        if self._ob_enabled:
            if h4_ohlcv and len(h4_ohlcv) >= 10:
                obs = self._detect_order_blocks(h4_ohlcv, "H4", current_price)
                order_blocks.extend(obs)
            if h1_ohlcv and len(h1_ohlcv) >= 20:
                obs = self._detect_order_blocks(h1_ohlcv, "H1", current_price)
                order_blocks.extend(obs)

            # Convert OBs to SRLevels
            for ob in order_blocks:
                if not ob.mitigated:
                    levels.append(SRLevel(
                        price=ob.mid,
                        level_type=LevelType.ORDER_BLOCK,
                        side=ob.side,
                        strength=ob.strength,
                        source=f"OB_{ob.timeframe}",
                        timeframe=ob.timeframe,
                        touches=0,
                        last_test_distance_pct=abs(current_price - ob.mid) / current_price * 100,
                    ))

        # ── Swing structure levels ──
        if swing_highs:
            for sh in swing_highs[-3:]:
                dist = abs(current_price - sh) / current_price * 100
                levels.append(SRLevel(
                    price=sh,
                    level_type=LevelType.SWING_HIGH,
                    side=LevelSide.RESISTANCE,
                    strength=0.6,
                    source="swing_structure",
                    timeframe="H1",
                    touches=1,
                    last_test_distance_pct=dist,
                ))

        if swing_lows:
            for sl in swing_lows[-3:]:
                dist = abs(current_price - sl) / current_price * 100
                levels.append(SRLevel(
                    price=sl,
                    level_type=LevelType.SWING_LOW,
                    side=LevelSide.SUPPORT,
                    strength=0.6,
                    source="swing_structure",
                    timeframe="H1",
                    touches=1,
                    last_test_distance_pct=dist,
                ))

        # ── Classify and sort ──
        supports = tuple(sorted(
            [l for l in levels if l.side == LevelSide.SUPPORT],
            key=lambda l: abs(l.price - current_price),
        ))
        resistances = tuple(sorted(
            [l for l in levels if l.side == LevelSide.RESISTANCE],
            key=lambda l: abs(l.price - current_price),
        ))

        nearest_sup = supports[0] if supports else None
        nearest_res = resistances[0] if resistances else None

        return MappedLevels(
            levels=tuple(levels),
            order_blocks=tuple(order_blocks),
            supports=supports,
            resistances=resistances,
            nearest_support=nearest_sup,
            nearest_resistance=nearest_res,
            asian_high=asian_high,
            asian_low=asian_low,
            daily_open=d1_ohlcv[-1]["open"] if d1_ohlcv else None,
        )

    def map_all(
        self,
        ohlc_h1: list | None = None,
        ohlc_d1: list | None = None,
        ohlc_w1: list | None = None,
        swing_points: list | None = None,
        current_price: float | None = None,
    ) -> MappedLevels:
        """Simplified mapping interface for EntryPipeline.

        Accepts list-of-lists OHLCV and auto-converts to the format
        expected by map_levels().
        """
        d1_data = self._to_dict_ohlcv(ohlc_d1) if ohlc_d1 else None
        h4_data = self._to_dict_ohlcv(ohlc_w1) if ohlc_w1 else None
        h1_data = self._to_dict_ohlcv(ohlc_h1) if ohlc_h1 else None

        # Extract swing highs/lows from swing points
        swing_highs: list[float] = []
        swing_lows: list[float] = []
        if swing_points:
            for sp in swing_points:
                if hasattr(sp, 'price'):
                    if hasattr(sp, 'swing_type'):
                        st = sp.swing_type
                        if hasattr(st, 'value'):
                            st_val = st.value
                        else:
                            st_val = str(st)
                        if 'high' in st_val.upper() or 'HH' in str(st).upper():
                            swing_highs.append(sp.price)
                        else:
                            swing_lows.append(sp.price)
                    else:
                        swing_highs.append(sp.price)

        # Determine current price
        price = current_price
        if price is None and h1_data:
            price = h1_data[-1].get("close", 0.0)
        if price is None and d1_data:
            price = d1_data[-1].get("close", 0.0)
        if price is None:
            price = 0.0

        return self.map_levels(
            current_price=price,
            d1_ohlcv=d1_data,
            h1_ohlcv=h1_data,
            swing_highs=swing_highs or None,
            swing_lows=swing_lows or None,
        )

    @staticmethod
    def _to_dict_ohlcv(data: list) -> list[dict[str, float]]:
        """Convert list-of-lists OHLCV to list-of-dicts format."""
        if not data:
            return []
        if isinstance(data[0], dict):
            return data  # Already dict format
        result = []
        for bar in data:
            if len(bar) >= 5:
                result.append({
                    "open": float(bar[0]),
                    "high": float(bar[1]),
                    "low": float(bar[2]),
                    "close": float(bar[3]),
                    "volume": float(bar[4]),
                })
            elif len(bar) >= 4:
                result.append({
                    "open": float(bar[0]),
                    "high": float(bar[1]),
                    "low": float(bar[2]),
                    "close": float(bar[3]),
                    "volume": 0.0,
                })
        return result

    def update_genome(self, new_genome: dict[str, Any]) -> None:
        """Update genome parameters (from StrategyGeneticist)."""
        mutable = new_genome.get("mutable_parameters", {})
        if "sr_proximity_pct" in mutable:
            self._proximity_pct = mutable["sr_proximity_pct"].get("current", self._proximity_pct)
        if "sr_proximity_pct" in new_genome:
            self._proximity_pct = new_genome["sr_proximity_pct"]
        if "order_block_lookback" in new_genome:
            self._ob_lookback = new_genome["order_block_lookback"]

    def is_near_level(
        self,
        price: float,
        levels: tuple[SRLevel, ...],
        threshold_pct: float | None = None,
    ) -> tuple[bool, SRLevel | None]:
        """Check if price is near any S/R level.

        Args:
            price: Current price.
            levels: Levels to check against.
            threshold_pct: Proximity threshold (%). Defaults to configured value.

        Returns:
            Tuple of (is_near, nearest_level).
        """
        threshold = threshold_pct or self._proximity_pct

        for level in levels:
            dist_pct = abs(price - level.price) / level.price * 100
            if dist_pct <= threshold:
                return True, level

        return False, None

    def get_level_score(
        self,
        price: float,
        level: SRLevel,
    ) -> float:
        """Score how significant a level is at the current price.

        Returns a score in [0, 1] based on:
          - Level strength
          - Proximity to price
          - Number of touches
          - Level type weight
        """
        # Proximity score (closer = higher)
        dist_pct = abs(price - level.price) / level.price * 100
        proximity_score = max(0.0, 1.0 - (dist_pct / self._proximity_pct))

        # Type weight
        type_key = self._level_type_weight_key(level.level_type)
        type_weight = self._level_weights.get(type_key, 0.5)

        # Touch score (more touches = stronger)
        touch_score = min(1.0, level.touches / 5.0)

        # Composite
        score = (
            proximity_score * 0.4 +
            level.strength * 0.3 +
            type_weight * 0.2 +
            touch_score * 0.1
        )

        return min(1.0, score)

    # ── Private mapping methods ──────────────────────────────────

    def _map_asian_levels(
        self,
        asian_high: float | None,
        asian_low: float | None,
        current_price: float,
    ) -> list[SRLevel]:
        """Map Asian session high/low as S/R levels."""
        levels: list[SRLevel] = []
        weight = self._level_weights.get("asian_hl", 0.9)

        if asian_high is not None:
            dist = abs(current_price - asian_high) / current_price * 100
            levels.append(SRLevel(
                price=asian_high,
                level_type=LevelType.ASIAN_HIGH,
                side=LevelSide.RESISTANCE,
                strength=weight,
                source="asian_session_high",
                timeframe="D1",
                touches=1,
                last_test_distance_pct=dist,
            ))

        if asian_low is not None:
            dist = abs(current_price - asian_low) / current_price * 100
            levels.append(SRLevel(
                price=asian_low,
                level_type=LevelType.ASIAN_LOW,
                side=LevelSide.SUPPORT,
                strength=weight,
                source="asian_session_low",
                timeframe="D1",
                touches=1,
                last_test_distance_pct=dist,
            ))

        return levels

    def _map_period_levels(
        self,
        ohlcv: list[dict[str, float]],
        timeframe: str,
        current_price: float,
        include_open: bool = True,
    ) -> list[SRLevel]:
        """Map high/low/open from the previous period's OHLCV."""
        if len(ohlcv) < 2:
            return []

        prev = ohlcv[-2]  # Previous bar
        weight = self._level_weights.get("daily_hl", 0.8)
        levels: list[SRLevel] = []

        # Previous high → resistance
        dist = abs(current_price - prev["high"]) / current_price * 100
        levels.append(SRLevel(
            price=prev["high"],
            level_type=LevelType.DAILY_HIGH,
            side=LevelSide.RESISTANCE,
            strength=weight,
            source=f"prev_{timeframe.lower()}_high",
            timeframe=timeframe,
            touches=1,
            last_test_distance_pct=dist,
        ))

        # Previous low → support
        dist = abs(current_price - prev["low"]) / current_price * 100
        levels.append(SRLevel(
            price=prev["low"],
            level_type=LevelType.DAILY_LOW,
            side=LevelSide.SUPPORT,
            strength=weight,
            source=f"prev_{timeframe.lower()}_low",
            timeframe=timeframe,
            touches=1,
            last_test_distance_pct=dist,
        ))

        # Open (can act as pivot)
        if include_open:
            dist = abs(current_price - prev["open"]) / current_price * 100
            side = LevelSide.SUPPORT if prev["open"] < current_price else LevelSide.RESISTANCE
            levels.append(SRLevel(
                price=prev["open"],
                level_type=LevelType.DAILY_OPEN,
                side=side,
                strength=weight * 0.8,
                source=f"prev_{timeframe.lower()}_open",
                timeframe=timeframe,
                touches=1,
                last_test_distance_pct=dist,
            ))

        return levels

    def _map_weekly_from_daily(
        self,
        d1_ohlcv: list[dict[str, float]],
        current_price: float,
    ) -> list[SRLevel]:
        """Map weekly levels from daily bars (last 5 trading days)."""
        weekly_bars = d1_ohlcv[-5:]
        if not weekly_bars:
            return []

        week_high = max(b["high"] for b in weekly_bars)
        week_low = min(b["low"] for b in weekly_bars)
        week_open = weekly_bars[0]["open"]

        weight = self._level_weights.get("weekly_hl", 0.7)
        levels: list[SRLevel] = []

        dist = abs(current_price - week_high) / current_price * 100
        levels.append(SRLevel(
            price=week_high, level_type=LevelType.WEEKLY_HIGH,
            side=LevelSide.RESISTANCE, strength=weight,
            source="weekly_high", timeframe="W1", touches=1,
            last_test_distance_pct=dist,
        ))

        dist = abs(current_price - week_low) / current_price * 100
        levels.append(SRLevel(
            price=week_low, level_type=LevelType.WEEKLY_LOW,
            side=LevelSide.SUPPORT, strength=weight,
            source="weekly_low", timeframe="W1", touches=1,
            last_test_distance_pct=dist,
        ))

        dist = abs(current_price - week_open) / current_price * 100
        side = LevelSide.SUPPORT if week_open < current_price else LevelSide.RESISTANCE
        levels.append(SRLevel(
            price=week_open, level_type=LevelType.WEEKLY_OPEN,
            side=side, strength=weight * 0.8,
            source="weekly_open", timeframe="W1", touches=1,
            last_test_distance_pct=dist,
        ))

        return levels

    def _map_monthly_from_daily(
        self,
        d1_ohlcv: list[dict[str, float]],
        current_price: float,
    ) -> list[SRLevel]:
        """Map monthly levels from daily bars (last ~22 trading days)."""
        monthly_bars = d1_ohlcv[-22:]
        if not monthly_bars:
            return []

        month_high = max(b["high"] for b in monthly_bars)
        month_low = min(b["low"] for b in monthly_bars)

        weight = self._level_weights.get("monthly_hl", 0.6)
        levels: list[SRLevel] = []

        dist = abs(current_price - month_high) / current_price * 100
        levels.append(SRLevel(
            price=month_high, level_type=LevelType.MONTHLY_HIGH,
            side=LevelSide.RESISTANCE, strength=weight,
            source="monthly_high", timeframe="MN", touches=1,
            last_test_distance_pct=dist,
        ))

        dist = abs(current_price - month_low) / current_price * 100
        levels.append(SRLevel(
            price=month_low, level_type=LevelType.MONTHLY_LOW,
            side=LevelSide.SUPPORT, strength=weight,
            source="monthly_low", timeframe="MN", touches=1,
            last_test_distance_pct=dist,
        ))

        return levels

    def _map_yearly_levels(
        self,
        d1_ohlcv: list[dict[str, float]],
        current_price: float,
    ) -> list[SRLevel]:
        """Map yearly levels from daily bars."""
        yearly_bars = d1_ohlcv[-252:]  # ~1 year of trading days
        if not yearly_bars:
            return []

        year_high = max(b["high"] for b in yearly_bars)
        year_low = min(b["low"] for b in yearly_bars)
        year_open = yearly_bars[0]["open"]

        weight = self._level_weights.get("yearly", 0.5)
        levels: list[SRLevel] = []

        dist = abs(current_price - year_open) / current_price * 100
        side = LevelSide.SUPPORT if year_open < current_price else LevelSide.RESISTANCE
        levels.append(SRLevel(
            price=year_open, level_type=LevelType.YEARLY_OPEN,
            side=side, strength=weight,
            source="yearly_open", timeframe="Y1", touches=1,
            last_test_distance_pct=dist,
        ))

        dist = abs(current_price - year_high) / current_price * 100
        levels.append(SRLevel(
            price=year_high, level_type=LevelType.YEARLY_HIGH,
            side=LevelSide.RESISTANCE, strength=weight,
            source="yearly_high", timeframe="Y1", touches=1,
            last_test_distance_pct=dist,
        ))

        dist = abs(current_price - year_low) / current_price * 100
        levels.append(SRLevel(
            price=year_low, level_type=LevelType.YEARLY_LOW,
            side=LevelSide.SUPPORT, strength=weight,
            source="yearly_low", timeframe="Y1", touches=1,
            last_test_distance_pct=dist,
        ))

        return levels

    def _detect_order_blocks(
        self,
        ohlcv: list[dict[str, float]],
        timeframe: str,
        current_price: float,
    ) -> list[OrderBlock]:
        """Detect order blocks (institutional supply/demand zones).

        An order block is the last opposing candle before a strong
        impulsive move. For a bullish OB:
          - Last bearish (red) candle before a strong bullish move
          - The zone is the high/low of that candle
        """
        if len(ohlcv) < 5:
            return []

        obs: list[OrderBlock] = []
        bars = ohlcv[-self._ob_lookback:] if len(ohlcv) > self._ob_lookback else ohlcv

        for i in range(1, len(bars) - 2):
            prev_bar = bars[i - 1]
            curr_bar = bars[i]
            next_bar = bars[i + 1]

            prev_body = abs(prev_bar["close"] - prev_bar["open"])
            prev_range = prev_bar["high"] - prev_bar["low"]
            curr_body = abs(curr_bar["close"] - curr_bar["open"])
            curr_range = curr_bar["high"] - curr_bar["low"]
            next_body = abs(next_bar["close"] - next_bar["open"])

            if prev_range == 0 or curr_range == 0:
                continue

            prev_body_pct = prev_body / prev_range
            curr_body_pct = curr_body / curr_range

            # ── Bullish OB (demand zone) ──
            # Previous candle is bearish, current/next is strongly bullish
            is_prev_bearish = prev_bar["close"] < prev_bar["open"]
            is_curr_bullish = curr_bar["close"] > curr_bar["open"]
            is_strong_move = curr_body_pct > self._ob_min_body_pct

            if is_prev_bearish and is_curr_bullish and is_strong_move:
                # Check if not mitigated (price hasn't returned to the zone)
                ob_high = prev_bar["high"]
                ob_low = prev_bar["low"]
                ob_mid = (ob_high + ob_low) / 2

                mitigated = any(
                    bar["low"] <= ob_mid
                    for bar in bars[i + 2:]
                )

                dist = abs(current_price - ob_mid) / current_price * 100
                strength = min(1.0, curr_body_pct + (0.2 if not mitigated else 0.0))

                obs.append(OrderBlock(
                    high=ob_high,
                    low=ob_low,
                    mid=ob_mid,
                    side=LevelSide.SUPPORT,
                    strength=strength,
                    candle_index=i,
                    timeframe=timeframe,
                    mitigated=mitigated,
                ))

            # ── Bearish OB (supply zone) ──
            is_prev_bullish = prev_bar["close"] > prev_bar["open"]
            is_curr_bearish = curr_bar["close"] < curr_bar["open"]

            if is_prev_bullish and is_curr_bearish and is_strong_move:
                ob_high = prev_bar["high"]
                ob_low = prev_bar["low"]
                ob_mid = (ob_high + ob_low) / 2

                mitigated = any(
                    bar["high"] >= ob_mid
                    for bar in bars[i + 2:]
                )

                dist = abs(current_price - ob_mid) / current_price * 100
                strength = min(1.0, curr_body_pct + (0.2 if not mitigated else 0.0))

                obs.append(OrderBlock(
                    high=ob_high,
                    low=ob_low,
                    mid=ob_mid,
                    side=LevelSide.RESISTANCE,
                    strength=strength,
                    candle_index=i,
                    timeframe=timeframe,
                    mitigated=mitigated,
                ))

        return obs

    def _level_type_weight_key(self, level_type: LevelType) -> str:
        """Map LevelType to the config weight key."""
        mapping = {
            LevelType.ORDER_BLOCK: "order_block",
            LevelType.ASIAN_HIGH: "asian_hl",
            LevelType.ASIAN_LOW: "asian_hl",
            LevelType.DAILY_HIGH: "daily_hl",
            LevelType.DAILY_LOW: "daily_hl",
            LevelType.DAILY_OPEN: "daily_hl",
            LevelType.WEEKLY_HIGH: "weekly_hl",
            LevelType.WEEKLY_LOW: "weekly_hl",
            LevelType.WEEKLY_OPEN: "weekly_hl",
            LevelType.MONTHLY_HIGH: "monthly_hl",
            LevelType.MONTHLY_LOW: "monthly_hl",
            LevelType.YEARLY_OPEN: "yearly",
            LevelType.YEARLY_HIGH: "yearly",
            LevelType.YEARLY_LOW: "yearly",
            LevelType.SWING_HIGH: "daily_hl",
            LevelType.SWING_LOW: "daily_hl",
        }
        return mapping.get(level_type, "daily_hl")
