"""
TSAR Domain Tools — Smart Order Router.

Institutional-grade order execution strategies that minimize market
impact and optimize fill quality for large orders.

Tools:
  6. Smart Order Router  — Split large orders across time to reduce impact
  7. Iceberg Orders      — Hidden quantity orders with auto-refresh
  8. TWAP/VWAP Execution — Time/Volume-Weighted Average Price strategies

These tools sit above the ExecutionEngine — they decompose large orders
into child orders and manage the execution lifecycle. They use the
ExchangeGateway for market data (order book, volume profiles) to
make intelligent slicing decisions.

Usage:
    router = SmartOrderRouter(engine, gateway)

    # TWAP: execute 10 BTC over 1 hour in equal slices
    result = await router.twap_execute("BTC/USDT", "buy", 10.0, duration_s=3600)

    # Iceberg: show 0.5 BTC at a time, total 5 BTC
    result = await router.iceberg_execute("BTC/USDT", "buy", 5.0, visible_qty=0.5)

    # Smart routing: auto-decompose large order
    result = await router.smart_route("BTC/USDT", "buy", 10.0)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from src.interfaces.exchange_gateway import ExchangeGateway
    from src.interfaces.execution_engine import ExecutionEngine

from src.interfaces.types import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Timeframe,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ChildOrder:
    """A child order within a larger execution strategy.

    Attributes:
        child_id: Internal child order identifier.
        parent_id: Parent strategy ID.
        order_id: Exchange-assigned order ID (empty if not yet placed).
        symbol: Trading pair.
        side: Buy or sell.
        quantity: Child order quantity.
        price: Limit price (None for market).
        status: Current status — pending, placed, filled, failed, cancelled.
        filled_quantity: Quantity filled so far.
        average_price: Average fill price.
        slippage_bps: Slippage in basis points.
        placed_at: When the child was placed.
        filled_at: When the child was fully filled.
    """

    child_id: str
    parent_id: str
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float | None = None
    status: str = "pending"
    filled_quantity: float = 0.0
    average_price: float = 0.0
    slippage_bps: float = 0.0
    placed_at: datetime | None = None
    filled_at: datetime | None = None


@dataclass(frozen=True)
class ExecutionStrategyResult:
    """Result of a multi-child execution strategy.

    Attributes:
        strategy_id: Unique strategy identifier.
        strategy_type: Type of strategy (twap, vwap, iceberg, smart_route).
        symbol: Trading pair.
        side: Buy or sell.
        total_quantity: Total quantity requested.
        filled_quantity: Total quantity filled across all children.
        average_price: Volume-weighted average fill price.
        total_slippage_bps: Blended slippage across all children.
        total_fee: Total fees paid.
        num_children: Total number of child orders.
        num_filled: Number of fully filled children.
        num_failed: Number of failed children.
        duration_ms: Total execution time in milliseconds.
        children: List of child order details.
        market_impact_bps: Estimated market impact in basis points.
        completion_rate: Fill rate (0.0 to 1.0).
        timestamp: When the strategy completed.
    """

    strategy_id: str
    strategy_type: str
    symbol: str
    side: str
    total_quantity: float
    filled_quantity: float
    average_price: float
    total_slippage_bps: float
    total_fee: float
    num_children: int
    num_filled: int
    num_failed: int
    duration_ms: float
    children: tuple[ChildOrder, ...] = ()
    market_impact_bps: float = 0.0
    completion_rate: float = 0.0
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# SMART ORDER ROUTER
# ═══════════════════════════════════════════════════════════════════════


class SmartOrderRouter:
    """Smart order routing and execution strategies.

    Decomposes large orders into smaller child orders and executes
    them intelligently to minimize market impact and optimize fill
    quality. Supports TWAP, VWAP, iceberg, and adaptive routing.

    The router sits above the ExecutionEngine — it uses market data
    (order book depth, volume profiles, spread analysis) to make
    informed decisions about order sizing and timing.
    """

    description = (
        "Smart order routing: TWAP, VWAP, iceberg orders, and adaptive large order execution"
    )

    # Impact thresholds — order size as % of visible liquidity
    SMALL_ORDER_PCT = 0.01  # < 1% of book → simple execution
    MEDIUM_ORDER_PCT = 0.05  # 1-5% → moderate splitting
    LARGE_ORDER_PCT = 0.15  # 5-15% → aggressive splitting
    # > 15% → institutional-grade TWAP/VWAP required

    def __init__(
        self,
        engine: ExecutionEngine,
        gateway: ExchangeGateway,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._engine = engine
        self._gateway = gateway
        self._config = config or {}

        # Active strategies
        self._active_strategies: dict[str, ExecutionStrategyResult] = {}

        # Market impact model calibration
        self._impact_coefficient = self._config.get("impact_coefficient", 0.1)
        self._max_child_orders = self._config.get("max_child_orders", 50)
        self._default_slice_interval_s = self._config.get("slice_interval_s", 60)

    # ── 6. Smart Order Router ───────────────────────────────────────

    async def smart_route(
        self,
        symbol: str,
        side: str,
        quantity: float,
        urgency: str = "normal",
        max_impact_bps: float = 10.0,
    ) -> ExecutionStrategyResult:
        """Automatically route a large order using the best strategy.

        Analyzes order book depth and market conditions to choose
        between direct execution, TWAP, or VWAP. The goal is to
        minimize market impact while respecting the urgency level.

        Urgency levels:
        - "aggressive": Minimize time, accept higher impact
        - "normal": Balance speed and impact
        - "patient": Minimize impact, accept slower execution

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell".
            quantity: Total order quantity in base asset units.
            urgency: "aggressive", "normal", or "patient".
            max_impact_bps: Maximum acceptable market impact in bps.

        Returns:
            ExecutionStrategyResult with full execution details.
        """
        start_time = time.monotonic()
        strategy_id = f"SR-{uuid.uuid4().hex[:8]}"

        # Get order book to estimate impact
        try:
            book = await self._gateway.get_orderbook(symbol, depth=50)
        except Exception as exc:
            logger.warning("Failed to get orderbook for smart routing: %s", exc)
            # Fallback to direct execution
            return await self._direct_execute(strategy_id, symbol, side, quantity)

        # Estimate market impact
        impact_bps = self._estimate_market_impact(book, side, quantity)

        # Choose strategy based on impact and urgency
        if impact_bps < self.SMALL_ORDER_PCT * 10_000 or urgency == "aggressive":
            # Small order or urgent — execute directly
            result = await self._direct_execute(strategy_id, symbol, side, quantity)
        elif impact_bps < self.MEDIUM_ORDER_PCT * 10_000:
            # Medium order — moderate time slicing
            slice_count = max(3, int(impact_bps / 2))
            result = await self._sliced_execute(
                strategy_id,
                symbol,
                side,
                quantity,
                num_slices=slice_count,
                interval_s=self._default_slice_interval_s,
            )
        else:
            # Large order — use TWAP or VWAP
            if urgency == "patient":
                duration_s = self._config.get("patient_duration_s", 3600)
            else:
                duration_s = self._config.get("normal_duration_s", 1800)

            # Choose VWAP if we have volume data, TWAP otherwise
            try:
                result = await self.vwap_execute(
                    symbol,
                    side,
                    quantity,
                    duration_s=duration_s,
                    parent_id=strategy_id,
                )
            except Exception:
                result = await self.twap_execute(
                    symbol,
                    side,
                    quantity,
                    duration_s=duration_s,
                    parent_id=strategy_id,
                )

        # Update with actual impact
        actual_impact = self._compute_actual_impact(result, symbol)

        final_result = ExecutionStrategyResult(
            strategy_id=result.strategy_id,
            strategy_type=result.strategy_type,
            symbol=result.symbol,
            side=result.side,
            total_quantity=result.total_quantity,
            filled_quantity=result.filled_quantity,
            average_price=result.average_price,
            total_slippage_bps=result.total_slippage_bps,
            total_fee=result.total_fee,
            num_children=result.num_children,
            num_filled=result.num_filled,
            num_failed=result.num_failed,
            duration_ms=(time.monotonic() - start_time) * 1000,
            children=result.children,
            market_impact_bps=actual_impact,
            completion_rate=result.completion_rate,
            timestamp=_utcnow(),
        )

        self._active_strategies[strategy_id] = final_result
        return final_result

    # ── 7. Iceberg Orders ───────────────────────────────────────────

    async def iceberg_execute(
        self,
        symbol: str,
        side: str,
        total_quantity: float,
        visible_qty: float,
        price: float | None = None,
        max_children: int = 50,
        refresh_delay_s: float = 1.0,
    ) -> ExecutionStrategyResult:
        """Execute an iceberg order — show only a fraction of total size.

        Iceberg orders hide the true order size by placing small
        visible portions. When each child fills, the next slice is
        placed automatically. This prevents other market participants
        from detecting large order flow.

        The visible quantity determines how much is shown in the order
        book at any time. The total quantity is the full amount to
        execute across all slices.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell".
            total_quantity: Total quantity to execute.
            visible_qty: Quantity shown per child order.
            price: Limit price (None = market orders for each child).
            max_children: Maximum number of child orders.
            refresh_delay_s: Delay between child orders (seconds).

        Returns:
            ExecutionStrategyResult with all child fills.
        """
        start_time = time.monotonic()
        strategy_id = f"ICE-{uuid.uuid4().hex[:8]}"

        if visible_qty <= 0 or visible_qty > total_quantity:
            raise ValueError(
                f"visible_qty ({visible_qty}) must be > 0 and <= total_quantity ({total_quantity})"
            )

        children: list[ChildOrder] = []
        remaining = total_quantity
        filled_qty = 0.0
        total_cost = 0.0
        total_fee = 0.0
        num_filled = 0
        num_failed = 0

        while remaining > 0 and len(children) < max_children:
            slice_qty = min(visible_qty, remaining)
            child_id = f"{strategy_id}:child:{len(children)}"

            child = ChildOrder(
                child_id=child_id,
                parent_id=strategy_id,
                symbol=symbol,
                side=side,
                quantity=slice_qty,
                price=price,
                status="placing",
                placed_at=_utcnow(),
            )

            try:
                # Build and execute child order
                order = Order(
                    order_id="",
                    symbol=symbol,
                    side=OrderSide(side),
                    order_type=OrderType.LIMIT if price else OrderType.MARKET,
                    quantity=slice_qty,
                    price=price,
                )

                result = await self._engine.execute_order(order)

                filled = ChildOrder(
                    child_id=child_id,
                    parent_id=strategy_id,
                    order_id=result.order_id,
                    symbol=symbol,
                    side=side,
                    quantity=slice_qty,
                    price=price,
                    status="filled" if result.status == OrderStatus.FILLED else "partial",
                    filled_quantity=result.filled_quantity,
                    average_price=result.average_price,
                    slippage_bps=result.slippage_bps,
                    placed_at=child.placed_at,
                    filled_at=_utcnow(),
                )

                children.append(filled)
                filled_qty += result.filled_quantity
                total_cost += result.average_price * result.filled_quantity
                total_fee += result.total_fee

                if result.status == OrderStatus.FILLED:
                    num_filled += 1
                elif result.status == OrderStatus.PARTIALLY_FILLED:
                    # Partial fill — reduce remaining by what was filled
                    pass
                else:
                    num_failed += 1

                remaining = total_quantity - filled_qty

                # Delay before next child
                if remaining > 0 and refresh_delay_s > 0:
                    await asyncio.sleep(refresh_delay_s)

            except Exception as exc:
                logger.error("Iceberg child %s failed: %s", child_id, exc)
                failed_child = ChildOrder(
                    child_id=child_id,
                    parent_id=strategy_id,
                    symbol=symbol,
                    side=side,
                    quantity=slice_qty,
                    price=price,
                    status="failed",
                    placed_at=child.placed_at,
                )
                children.append(failed_child)
                num_failed += 1
                remaining -= slice_qty  # Count as consumed to avoid infinite loop

        avg_price = total_cost / filled_qty if filled_qty > 0 else 0.0
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExecutionStrategyResult(
            strategy_id=strategy_id,
            strategy_type="iceberg",
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            filled_quantity=round(filled_qty, 8),
            average_price=round(avg_price, 8),
            total_slippage_bps=round(
                float(np.mean([c.slippage_bps for c in children if c.slippage_bps != 0]))
                if children
                else 0.0,
                4,
            ),
            total_fee=round(total_fee, 8),
            num_children=len(children),
            num_filled=num_filled,
            num_failed=num_failed,
            duration_ms=round(duration_ms, 2),
            children=tuple(children),
            completion_rate=round(filled_qty / total_quantity, 4) if total_quantity > 0 else 0,
            timestamp=_utcnow(),
        )

    # ── 8. TWAP/VWAP Execution ─────────────────────────────────────

    async def twap_execute(
        self,
        symbol: str,
        side: str,
        total_quantity: float,
        duration_s: int = 1800,
        num_slices: int | None = None,
        price_limit: float | None = None,
        parent_id: str | None = None,
    ) -> ExecutionStrategyResult:
        """Execute using Time-Weighted Average Price strategy.

        Splits the order into equal-sized slices distributed evenly
        over the specified duration. Each slice executes at the
        market price at its scheduled time.

        TWAP is ideal when:
        - You want predictable execution timing
        - Volume patterns are unpredictable
        - You need a simple, auditable strategy

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell".
            total_quantity: Total quantity to execute.
            duration_s: Total execution duration in seconds.
            num_slices: Number of slices (auto-calculated if None).
            price_limit: Maximum price for buys / minimum for sells.
            parent_id: Parent strategy ID (for nested strategies).

        Returns:
            ExecutionStrategyResult with all slice fills.
        """
        start_time = time.monotonic()
        strategy_id = parent_id or f"TWAP-{uuid.uuid4().hex[:8]}"

        # Auto-calculate slices: aim for ~2% of visible liquidity per slice
        if num_slices is None:
            try:
                book = await self._gateway.get_orderbook(symbol, depth=20)
                if side == "buy":
                    visible = sum(l.price * l.quantity for l in book.asks[:10])
                else:
                    visible = sum(l.price * l.quantity for l in book.bids[:10])
                target_per_slice = visible * 0.02
                if target_per_slice > 0:
                    notional = total_quantity * (
                        book.asks[0].price if side == "buy" else book.bids[0].price
                    )
                    num_slices = max(
                        2, min(self._max_child_orders, int(notional / target_per_slice))
                    )
                else:
                    num_slices = max(2, min(self._max_child_orders, duration_s // 60))
            except Exception:
                num_slices = max(2, min(self._max_child_orders, duration_s // 60))

        slice_qty = total_quantity / num_slices
        interval_s = duration_s / num_slices

        children: list[ChildOrder] = []
        filled_qty = 0.0
        total_cost = 0.0
        total_fee = 0.0
        num_filled = 0
        num_failed = 0

        for i in range(num_slices):
            remaining = total_quantity - filled_qty
            if remaining <= 0:
                break

            current_slice = min(slice_qty, remaining)
            child_id = f"{strategy_id}:twap:{i}"
            schedule_time = start_time + (i * interval_s)

            # Wait until scheduled time
            now = time.monotonic()
            if schedule_time > now:
                await asyncio.sleep(schedule_time - now)

            # Get current price for limit check
            if price_limit is not None:
                try:
                    price = await self._gateway.get_price(symbol)
                    if side == "buy" and price.last > price_limit:
                        logger.info(
                            "TWAP slice %d skipped: price %.2f > limit %.2f",
                            i,
                            price.last,
                            price_limit,
                        )
                        children.append(
                            ChildOrder(
                                child_id=child_id,
                                parent_id=strategy_id,
                                symbol=symbol,
                                side=side,
                                quantity=current_slice,
                                price=price_limit,
                                status="skipped",
                                placed_at=_utcnow(),
                            )
                        )
                        continue
                    elif side == "sell" and price.last < price_limit:
                        logger.info(
                            "TWAP slice %d skipped: price %.2f < limit %.2f",
                            i,
                            price.last,
                            price_limit,
                        )
                        children.append(
                            ChildOrder(
                                child_id=child_id,
                                parent_id=strategy_id,
                                symbol=symbol,
                                side=side,
                                quantity=current_slice,
                                price=price_limit,
                                status="skipped",
                                placed_at=_utcnow(),
                            )
                        )
                        continue
                except Exception:
                    pass

            # Execute slice
            try:
                order = Order(
                    order_id="",
                    symbol=symbol,
                    side=OrderSide(side),
                    order_type=OrderType.MARKET,
                    quantity=current_slice,
                )

                result = await self._engine.execute_order(order)

                child = ChildOrder(
                    child_id=child_id,
                    parent_id=strategy_id,
                    order_id=result.order_id,
                    symbol=symbol,
                    side=side,
                    quantity=current_slice,
                    status="filled" if result.status == OrderStatus.FILLED else "partial",
                    filled_quantity=result.filled_quantity,
                    average_price=result.average_price,
                    slippage_bps=result.slippage_bps,
                    placed_at=_utcnow(),
                    filled_at=_utcnow(),
                )

                children.append(child)
                filled_qty += result.filled_quantity
                total_cost += result.average_price * result.filled_quantity
                total_fee += result.total_fee

                if result.status == OrderStatus.FILLED:
                    num_filled += 1
                else:
                    num_failed += 1

            except Exception as exc:
                logger.error("TWAP slice %d failed: %s", i, exc)
                children.append(
                    ChildOrder(
                        child_id=child_id,
                        parent_id=strategy_id,
                        symbol=symbol,
                        side=side,
                        quantity=current_slice,
                        status="failed",
                        placed_at=_utcnow(),
                    )
                )
                num_failed += 1

        avg_price = total_cost / filled_qty if filled_qty > 0 else 0.0
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExecutionStrategyResult(
            strategy_id=strategy_id,
            strategy_type="twap",
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            filled_quantity=round(filled_qty, 8),
            average_price=round(avg_price, 8),
            total_slippage_bps=round(
                float(np.mean([c.slippage_bps for c in children if c.slippage_bps != 0]))
                if children
                else 0.0,
                4,
            ),
            total_fee=round(total_fee, 8),
            num_children=len(children),
            num_filled=num_filled,
            num_failed=num_failed,
            duration_ms=round(duration_ms, 2),
            children=tuple(children),
            completion_rate=round(filled_qty / total_quantity, 4) if total_quantity > 0 else 0,
            timestamp=_utcnow(),
        )

    async def vwap_execute(
        self,
        symbol: str,
        side: str,
        total_quantity: float,
        duration_s: int = 1800,
        num_buckets: int = 20,
        price_limit: float | None = None,
        parent_id: str | None = None,
    ) -> ExecutionStrategyResult:
        """Execute using Volume-Weighted Average Price strategy.

        Distributes the order across time buckets proportional to
        historical volume. Higher-volume periods get larger slices,
        lower-volume periods get smaller slices. This ensures the
        execution tracks the market's VWAP closely.

        VWAP is ideal when:
        - You want to match the institutional benchmark
        - Volume patterns are predictable
        - Minimizing market impact is critical

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell".
            total_quantity: Total quantity to execute.
            duration_s: Total execution duration in seconds.
            num_buckets: Number of time buckets for volume distribution.
            price_limit: Maximum price for buys / minimum for sells.
            parent_id: Parent strategy ID (for nested strategies).

        Returns:
            ExecutionStrategyResult with all bucket fills.
        """
        start_time = time.monotonic()
        strategy_id = parent_id or f"VWAP-{uuid.uuid4().hex[:8]}"

        # Get volume profile to determine slice sizes
        volume_weights = await self._get_volume_weights(symbol, duration_s, num_buckets)

        bucket_interval_s = duration_s / num_buckets
        children: list[ChildOrder] = []
        filled_qty = 0.0
        total_cost = 0.0
        total_fee = 0.0
        num_filled = 0
        num_failed = 0

        for i, weight in enumerate(volume_weights):
            remaining = total_quantity - filled_qty
            if remaining <= 0:
                break

            # Volume-weighted slice size
            bucket_qty = total_quantity * weight
            bucket_qty = min(bucket_qty, remaining)
            if bucket_qty <= 0:
                continue

            child_id = f"{strategy_id}:vwap:{i}"
            schedule_time = start_time + (i * bucket_interval_s)

            # Wait until scheduled time
            now = time.monotonic()
            if schedule_time > now:
                await asyncio.sleep(schedule_time - now)

            # Price limit check
            if price_limit is not None:
                try:
                    price = await self._gateway.get_price(symbol)
                    if (
                        side == "buy"
                        and price.last > price_limit
                        or side == "sell"
                        and price.last < price_limit
                    ):
                        children.append(
                            ChildOrder(
                                child_id=child_id,
                                parent_id=strategy_id,
                                symbol=symbol,
                                side=side,
                                quantity=bucket_qty,
                                price=price_limit,
                                status="skipped",
                                placed_at=_utcnow(),
                            )
                        )
                        continue
                except Exception:
                    pass

            # Execute bucket
            try:
                order = Order(
                    order_id="",
                    symbol=symbol,
                    side=OrderSide(side),
                    order_type=OrderType.MARKET,
                    quantity=bucket_qty,
                )

                result = await self._engine.execute_order(order)

                child = ChildOrder(
                    child_id=child_id,
                    parent_id=strategy_id,
                    order_id=result.order_id,
                    symbol=symbol,
                    side=side,
                    quantity=bucket_qty,
                    status="filled" if result.status == OrderStatus.FILLED else "partial",
                    filled_quantity=result.filled_quantity,
                    average_price=result.average_price,
                    slippage_bps=result.slippage_bps,
                    placed_at=_utcnow(),
                    filled_at=_utcnow(),
                )

                children.append(child)
                filled_qty += result.filled_quantity
                total_cost += result.average_price * result.filled_quantity
                total_fee += result.total_fee

                if result.status == OrderStatus.FILLED:
                    num_filled += 1
                else:
                    num_failed += 1

            except Exception as exc:
                logger.error("VWAP bucket %d failed: %s", i, exc)
                children.append(
                    ChildOrder(
                        child_id=child_id,
                        parent_id=strategy_id,
                        symbol=symbol,
                        side=side,
                        quantity=bucket_qty,
                        status="failed",
                        placed_at=_utcnow(),
                    )
                )
                num_failed += 1

        avg_price = total_cost / filled_qty if filled_qty > 0 else 0.0
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExecutionStrategyResult(
            strategy_id=strategy_id,
            strategy_type="vwap",
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            filled_quantity=round(filled_qty, 8),
            average_price=round(avg_price, 8),
            total_slippage_bps=round(
                float(np.mean([c.slippage_bps for c in children if c.slippage_bps != 0]))
                if children
                else 0.0,
                4,
            ),
            total_fee=round(total_fee, 8),
            num_children=len(children),
            num_filled=num_filled,
            num_failed=num_failed,
            duration_ms=round(duration_ms, 2),
            children=tuple(children),
            completion_rate=round(filled_qty / total_quantity, 4) if total_quantity > 0 else 0,
            timestamp=_utcnow(),
        )

    # ── Internal Helpers ────────────────────────────────────────────

    def _estimate_market_impact(
        self,
        book: Any,
        side: str,
        quantity: float,
    ) -> float:
        """Estimate market impact of an order in basis points.

        Uses a square-root market impact model:
            impact = coefficient * sqrt(order_size / avg_daily_volume)

        For order book impact, walks the book to estimate the
        average fill price vs mid-price.

        Args:
            book: OrderBook snapshot.
            side: "buy" or "sell".
            quantity: Order quantity.

        Returns:
            Estimated impact in basis points.
        """
        if not book.bids or not book.asks:
            return 0.0

        mid_price = (book.bids[0].price + book.asks[0].price) / 2

        # Walk the book to simulate fill
        levels = book.asks if side == "buy" else book.bids

        remaining = quantity
        total_cost = 0.0

        for level in levels:
            fill_qty = min(remaining, level.quantity)
            total_cost += fill_qty * level.price
            remaining -= fill_qty
            if remaining <= 0:
                break

        if remaining > 0:
            # Not enough liquidity — significant impact
            filled = quantity - remaining
            avg_price = total_cost / filled if filled > 0 else mid_price
        else:
            avg_price = total_cost / quantity

        impact = abs(avg_price - mid_price) / mid_price * 10_000
        return impact

    def _compute_actual_impact(
        self,
        result: ExecutionStrategyResult,
        symbol: str,
    ) -> float:
        """Compute actual market impact from execution results.

        Compares the average fill price against the first child's
        price to measure price drift during execution.

        Args:
            result: Execution strategy result.
            symbol: Trading pair.

        Returns:
            Actual impact in basis points.
        """
        prices = [c.average_price for c in result.children if c.average_price > 0]
        if len(prices) < 2:
            return 0.0

        first_price = prices[0]
        last_price = prices[-1]
        float(np.mean(prices))

        # Drift from first to last
        drift = abs(last_price - first_price) / first_price * 10_000
        # Deviation from average
        deviation = abs(result.average_price - first_price) / first_price * 10_000

        return max(drift, deviation)

    async def _direct_execute(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
    ) -> ExecutionStrategyResult:
        """Execute a single order directly.

        Used for small orders where splitting is unnecessary.
        """
        start = time.monotonic()

        order = Order(
            order_id="",
            symbol=symbol,
            side=OrderSide(side),
            order_type=OrderType.MARKET,
            quantity=quantity,
        )

        result = await self._engine.execute_order(order)

        child = ChildOrder(
            child_id=f"{strategy_id}:direct:0",
            parent_id=strategy_id,
            order_id=result.order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            status="filled" if result.status == OrderStatus.FILLED else "partial",
            filled_quantity=result.filled_quantity,
            average_price=result.average_price,
            slippage_bps=result.slippage_bps,
            placed_at=_utcnow(),
            filled_at=_utcnow(),
        )

        return ExecutionStrategyResult(
            strategy_id=strategy_id,
            strategy_type="direct",
            symbol=symbol,
            side=side,
            total_quantity=quantity,
            filled_quantity=result.filled_quantity,
            average_price=result.average_price,
            total_slippage_bps=result.slippage_bps,
            total_fee=result.total_fee,
            num_children=1,
            num_filled=1 if result.status == OrderStatus.FILLED else 0,
            num_failed=0,
            duration_ms=(time.monotonic() - start) * 1000,
            children=(child,),
            completion_rate=round(result.filled_quantity / quantity, 4) if quantity > 0 else 0,
            timestamp=_utcnow(),
        )

    async def _sliced_execute(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        num_slices: int,
        interval_s: float,
    ) -> ExecutionStrategyResult:
        """Execute using simple time slicing (TWAP-like).

        A lighter version of TWAP for medium-sized orders.
        """
        start = time.monotonic()
        slice_qty = quantity / num_slices

        children: list[ChildOrder] = []
        filled_qty = 0.0
        total_cost = 0.0
        total_fee = 0.0

        for i in range(num_slices):
            remaining = quantity - filled_qty
            if remaining <= 0:
                break

            current_slice = min(slice_qty, remaining)
            child_id = f"{strategy_id}:slice:{i}"

            if i > 0:
                await asyncio.sleep(interval_s)

            try:
                order = Order(
                    order_id="",
                    symbol=symbol,
                    side=OrderSide(side),
                    order_type=OrderType.MARKET,
                    quantity=current_slice,
                )

                result = await self._engine.execute_order(order)

                child = ChildOrder(
                    child_id=child_id,
                    parent_id=strategy_id,
                    order_id=result.order_id,
                    symbol=symbol,
                    side=side,
                    quantity=current_slice,
                    status="filled" if result.status == OrderStatus.FILLED else "partial",
                    filled_quantity=result.filled_quantity,
                    average_price=result.average_price,
                    slippage_bps=result.slippage_bps,
                    placed_at=_utcnow(),
                    filled_at=_utcnow(),
                )

                children.append(child)
                filled_qty += result.filled_quantity
                total_cost += result.average_price * result.filled_quantity
                total_fee += result.total_fee

            except Exception as exc:
                logger.error("Slice %d failed: %s", i, exc)
                children.append(
                    ChildOrder(
                        child_id=child_id,
                        parent_id=strategy_id,
                        symbol=symbol,
                        side=side,
                        quantity=current_slice,
                        status="failed",
                        placed_at=_utcnow(),
                    )
                )

        avg_price = total_cost / filled_qty if filled_qty > 0 else 0.0

        return ExecutionStrategyResult(
            strategy_id=strategy_id,
            strategy_type="sliced",
            symbol=symbol,
            side=side,
            total_quantity=quantity,
            filled_quantity=round(filled_qty, 8),
            average_price=round(avg_price, 8),
            total_slippage_bps=round(
                float(np.mean([c.slippage_bps for c in children if c.slippage_bps != 0]))
                if children
                else 0.0,
                4,
            ),
            total_fee=round(total_fee, 8),
            num_children=len(children),
            num_filled=sum(1 for c in children if c.status == "filled"),
            num_failed=sum(1 for c in children if c.status == "failed"),
            duration_ms=(time.monotonic() - start) * 1000,
            children=tuple(children),
            completion_rate=round(filled_qty / quantity, 4) if quantity > 0 else 0,
            timestamp=_utcnow(),
        )

    async def _get_volume_weights(
        self,
        symbol: str,
        duration_s: int,
        num_buckets: int,
    ) -> list[float]:
        """Get volume distribution weights for VWAP execution.

        Fetches recent OHLCV data and computes the relative volume
        weight for each time bucket. Buckets with higher historical
        volume get proportionally larger order slices.

        Args:
            symbol: Trading pair.
            duration_s: Total execution duration.
            num_buckets: Number of time buckets.

        Returns:
            List of weights summing to 1.0.
        """
        try:
            # Get enough candles to cover the duration
            # Use 1m candles for fine granularity
            limit = min(500, max(num_buckets * 2, duration_s // 60))
            ohlcv = await self._gateway.get_ohlcv(symbol, Timeframe.M1, limit=limit)

            if not ohlcv:
                # Equal weight fallback
                return [1.0 / num_buckets] * num_buckets

            volumes = [c.volume for c in ohlcv]
            total_volume = sum(volumes)

            if total_volume <= 0:
                return [1.0 / num_buckets] * num_buckets

            # Group candles into buckets and sum volumes
            candles_per_bucket = max(1, len(volumes) // num_buckets)
            bucket_volumes = []
            for i in range(num_buckets):
                start_idx = i * candles_per_bucket
                end_idx = min(start_idx + candles_per_bucket, len(volumes))
                if start_idx >= len(volumes):
                    bucket_volumes.append(0.0)
                else:
                    bucket_volumes.append(sum(volumes[start_idx:end_idx]))

            # Normalize to weights
            total_bucket_vol = sum(bucket_volumes)
            if total_bucket_vol <= 0:
                return [1.0 / num_buckets] * num_buckets

            weights = [v / total_bucket_vol for v in bucket_volumes]

            # Smooth weights to avoid extreme concentrations
            # Apply exponential smoothing
            smoothed = []
            alpha = 0.3
            for i, w in enumerate(weights):
                if i == 0:
                    smoothed.append(w)
                else:
                    smoothed.append(alpha * w + (1 - alpha) * smoothed[-1])

            # Re-normalize
            total_smoothed = sum(smoothed)
            if total_smoothed > 0:
                smoothed = [w / total_smoothed for w in smoothed]

            return smoothed

        except Exception as exc:
            logger.warning("Failed to get volume weights: %s — using equal weights", exc)
            return [1.0 / num_buckets] * num_buckets

    def get_active_strategies(self) -> dict[str, ExecutionStrategyResult]:
        """Get all tracked execution strategies.

        Returns:
            Dict mapping strategy_id to ExecutionStrategyResult.
        """
        return dict(self._active_strategies)

    def get_strategy(self, strategy_id: str) -> ExecutionStrategyResult | None:
        """Get a specific execution strategy by ID.

        Args:
            strategy_id: Strategy identifier.

        Returns:
            ExecutionStrategyResult or None if not found.
        """
        return self._active_strategies.get(strategy_id)
