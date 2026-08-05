"""
TSAR Interface Layer — Shared Types.

All dataclasses, enums, and type definitions used across the interface layer.
This is the SINGLE SOURCE OF TRUTH for data shapes exchanged between
agents and backends.

Every type is immutable by default (frozen=True) where practical.
All fields have full type hints and docstrings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════


class OrderSide(StrEnum):
    """Direction of an order."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Type of order to place on the exchange."""

    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"


class OrderStatus(StrEnum):
    """Lifecycle status of an order."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Timeframe(StrEnum):
    """OHLCV candle timeframes."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"


class ConnectionStatus(StrEnum):
    """Connection state for exchange gateways."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class TimeInForce(StrEnum):
    """Time-in-force policy for orders."""

    GTC = "gtc"  # Good Till Cancelled
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill
    GTX = "gtx"  # Good Till Crossing (post-only)


class VetoLevel(StrEnum):
    """Veto severity levels for risk decisions."""

    NONE = "NONE"  # No veto — trade approved
    SOFT = "SOFT"  # Advisory warning, trade proceeds
    FIRM = "FIRM"  # Trade blocked, can be overridden
    HARD = "HARD"  # Trade blocked, cannot override
    NUCLEAR = "NUCLEAR"  # Kill switch — halt all trading


class DrawdownLevel(StrEnum):
    """Drawdown circuit breaker levels."""

    GREEN = "GREEN"  # Drawdown < 2% — normal operation
    YELLOW = "YELLOW"  # Drawdown 2-3% — reduce position sizes
    ORANGE = "ORANGE"  # Drawdown 3-5% — no new entries
    RED = "RED"  # Drawdown > 5% — kill switch


# ═══════════════════════════════════════════════════════════════════════
# CORE MARKET DATA TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Price:
    """A single price tick with metadata.

    Used for real-time price updates and simple price queries.

    Attributes:
        symbol: Trading pair (e.g. "BTC/USDT").
        last: Last traded price.
        bid: Best bid price.
        ask: Best ask price.
        timestamp: Time of the price observation (UTC).
    """

    symbol: str
    last: float
    bid: float
    ask: float
    timestamp: datetime


@dataclass(frozen=True)
class OHLCV:
    """A single OHLCV candlestick bar.

    Represents open-high-low-close-volume data for one time period.

    Attributes:
        timestamp: Start time of the candle (UTC).
        open: Opening price.
        high: Highest price during the period.
        low: Lowest price during the period.
        close: Closing price.
        volume: Base asset volume traded during the period.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class OrderBookLevel:
    """A single price level in the order book.

    Attributes:
        price: Price at this level.
        quantity: Total quantity available at this price.
    """

    price: float
    quantity: float


@dataclass(frozen=True)
class OrderBook:
    """Order book snapshot with bid and ask sides.

    Attributes:
        symbol: Trading pair.
        bids: Bid levels sorted by price descending (highest first).
        asks: Ask levels sorted by price ascending (lowest first).
        timestamp: Time of the snapshot (UTC).
    """

    symbol: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    timestamp: datetime


@dataclass(frozen=True)
class Trade:
    """A single executed trade (fill) on the exchange.

    Represents one trade that occurred on the exchange's trade tape.

    Attributes:
        id: Exchange-assigned trade ID.
        symbol: Trading pair.
        side: Taker side — BUY if the taker bought, SELL if the taker sold.
        price: Execution price.
        quantity: Executed quantity.
        cost: Total cost (price * quantity).
        fee: Fee paid.
        fee_currency: Currency the fee was charged in.
        timestamp: Time of the trade (UTC).
    """

    id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    cost: float
    fee: float
    fee_currency: str
    timestamp: datetime


# ═══════════════════════════════════════════════════════════════════════
# ACCOUNT & POSITION TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Position:
    """An open position on the exchange.

    Attributes:
        symbol: Trading pair.
        side: Long (BUY) or short (SELL).
        quantity: Position size.
        entry_price: Average entry price.
        current_price: Current mark/last price.
        unrealized_pnl: Unrealized profit and loss.
        leverage: Position leverage multiplier.
        liquidation_price: Liquidation price (None if not leveraged).
        timestamp: Time of the position snapshot (UTC).
    """

    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    leverage: float = 1.0
    liquidation_price: float | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class Balance:
    """Account balance information.

    Attributes:
        total: Total balance (free + used).
        free: Available balance (not locked in orders/positions).
        used: Balance locked in orders/positions.
        currency: Base currency (default USDT).
        per_currency: Detailed per-currency breakdown.
            Keys are currency symbols, values are dicts with
            'total', 'free', 'used' floats.
    """

    total: float
    free: float
    used: float
    currency: str = "USDT"
    per_currency: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Order:
    """A trade order — either proposed or placed.

    Used by agents to describe an order they want to execute,
    and by the execution engine to report order state.

    Attributes:
        order_id: Exchange-assigned order ID (empty if not yet placed).
        symbol: Trading pair.
        side: Buy or sell.
        order_type: Market, limit, stop_market, stop_limit.
        quantity: Order quantity.
        price: Limit price (None for market orders).
        stop_price: Trigger price for stop orders.
        filled_quantity: Quantity already filled.
        status: Current order status.
        fee: Total fee paid so far.
        fee_currency: Currency the fee was charged in.
        timestamp: Time the order was created (UTC).
    """

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    filled_quantity: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    fee: float = 0.0
    fee_currency: str = ""
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OrderRequest:
    """A request to place an order on the exchange.

    Lightweight order specification used by agents to request execution.
    Unlike Order, this does not include exchange-assigned fields
    (order_id, filled_quantity, status, fees).

    Attributes:
        symbol: Trading pair (e.g. "BTC/USDT").
        side: Buy or sell.
        order_type: Market, limit, stop_market, stop_limit.
        quantity: Order quantity.
        price: Limit price (None for market orders).
        stop_price: Trigger price for stop orders.
        time_in_force: Time-in-force policy (default GTC).
    """

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.GTC


# ═══════════════════════════════════════════════════════════════════════
# EXECUTION TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Fill:
    """A single fill (partial or complete) of an order.

    Attributes:
        fill_id: Exchange-assigned fill ID.
        order_id: Parent order ID.
        symbol: Trading pair.
        side: Buy or sell.
        price: Fill price.
        quantity: Fill quantity.
        fee: Fee for this fill.
        fee_currency: Currency the fee was charged in.
        timestamp: Time of the fill (UTC).
    """

    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    fee: float
    fee_currency: str
    timestamp: datetime


@dataclass(frozen=True)
class ExecutionResult:
    """Result of executing an order through the execution engine.

    Attributes:
        order_id: Exchange-assigned order ID.
        symbol: Trading pair.
        status: Final or current order status.
        filled_quantity: Total quantity filled.
        average_price: Volume-weighted average fill price.
        total_fee: Total fees paid.
        fills: List of individual fills.
        slippage_bps: Slippage in basis points (vs expected price).
        timestamp: Time of execution (UTC).
    """

    order_id: str
    symbol: str
    status: OrderStatus
    filled_quantity: float
    average_price: float
    total_fee: float
    fills: tuple[Fill, ...] = ()
    slippage_bps: float = 0.0
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# BRACKET / OCO ORDER TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class BracketOrder:
    """A linked bracket order: entry + stop-loss + take-profit.

    When one exit order fills, the other is automatically cancelled.

    Attributes:
        bracket_id: Unique bracket identifier.
        symbol: Trading pair.
        side: Direction of the entry order.
        quantity: Total position quantity.
        entry_order_id: Exchange order ID for the entry.
        stop_loss_order_id: Exchange order ID for the stop-loss.
        take_profit_order_id: Exchange order ID for the take-profit.
        stop_loss_price: Stop-loss trigger price.
        take_profit_price: Take-profit limit price.
        status: Current bracket status.
        timestamp: Time the bracket was created.
        linked_order_ids: All linked exchange order IDs.
    """

    bracket_id: str
    symbol: str
    side: OrderSide
    quantity: float
    entry_order_id: str = ""
    stop_loss_order_id: str = ""
    take_profit_order_id: str = ""
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    status: str = "pending"  # pending | active | closed | cancelled
    timestamp: datetime | None = None
    linked_order_ids: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL & RISK TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Signal:
    """A trading signal generated by the Signal Scout or a strategy.

    Attributes:
        signal_id: Unique signal identifier.
        symbol: Trading pair.
        side: Recommended direction (BUY or SELL).
        score: Signal confidence score (0.0 to 1.0).
        entry_price: Recommended entry price.
        stop_loss: Recommended stop-loss price.
        take_profit: Recommended take-profit price.
        strategy: Strategy name that generated this signal.
        reasoning: Human-readable explanation of the signal.
        metadata: Additional signal context (regime, indicators, etc.).
        timestamp: Time the signal was generated (UTC).
    """

    signal_id: str
    symbol: str
    side: OrderSide
    score: float
    entry_price: float
    stop_loss: float
    take_profit: float
    strategy: str
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None


@dataclass(frozen=True)
class RiskDecision:
    """Decision from the Risk Guardian on a proposed trade.

    Attributes:
        signal_id: The signal this decision applies to.
        approved: Whether the trade is approved.
        position_size: Recommended position size (0 if rejected).
        rejection_reasons: List of reasons for rejection (empty if approved).
        warnings: Non-blocking warnings.
        veto_level: Veto severity — "NONE", "SOFT", "FIRM", "HARD", "NUCLEAR".
        timestamp: Time of the decision (UTC).
    """

    signal_id: str
    approved: bool
    position_size: float = 0.0
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    veto_level: str = "NONE"
    timestamp: datetime | None = None


@dataclass(frozen=True)
class Portfolio:
    """Portfolio snapshot for risk calculations.

    Attributes:
        equity: Current total portfolio value.
        high_water_mark: Peak portfolio value.
        cash: Available cash (not in positions).
        positions: Currently open positions.
        daily_pnl: Today's realized P&L.
        daily_pnl_pct: Today's P&L as percentage of equity.
        open_position_count: Number of open positions.
    """

    equity: float
    high_water_mark: float
    cash: float
    positions: tuple[Position, ...] = ()
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    open_position_count: int = 0


@dataclass(frozen=True)
class DrawdownState:
    """Current drawdown and circuit breaker state.

    Attributes:
        current_drawdown_pct: Current drawdown from high water mark.
        high_water_mark: Peak portfolio value.
        current_equity: Current portfolio value.
        daily_pnl: Today's realized P&L.
        daily_pnl_pct: Today's P&L as percentage.
        circuit_breaker_level: "GREEN", "YELLOW", "ORANGE", or "RED".
        trading_allowed: Whether new trades are permitted.
        position_size_multiplier: Size adjustment (1.0 = normal, 0.5 = half, 0.0 = halted).
    """

    current_drawdown_pct: float
    high_water_mark: float
    current_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    circuit_breaker_level: str  # GREEN | YELLOW | ORANGE | RED
    trading_allowed: bool
    position_size_multiplier: float = 1.0


@dataclass(frozen=True)
class RiskCheckResult:
    """Result of a pre-trade risk check.

    Attributes:
        approved: Whether the trade passed all risk checks.
        veto_level: Veto severity if rejected (None if approved).
        reason: Human-readable summary of the decision.
        checks_passed: Names of checks that passed.
        checks_failed: Names of checks that failed with details.
    """

    approved: bool
    veto_level: VetoLevel | None = None
    reason: str = ""
    checks_passed: tuple[str, ...] = ()
    checks_failed: tuple[str, ...] = ()


@dataclass(frozen=True)
class PositionSizeResult:
    """Result of a position sizing calculation.

    Attributes:
        quantity: Recommended position quantity (base asset units).
        notional_value: Total notional value (quantity * entry_price).
        risk_amount: Dollar amount at risk.
        risk_pct: Risk as percentage of equity.
        method: Sizing method used (e.g. "half_kelly", "fixed").
        capped: Whether the size was capped by a limit.
        cap_reason: Reason for capping (empty if not capped).
    """

    quantity: float
    notional_value: float
    risk_amount: float
    risk_pct: float
    method: str = "half_kelly"
    capped: bool = False
    cap_reason: str = ""


# ═══════════════════════════════════════════════════════════════════════
# PRICING ENGINE RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MACDResult:
    """MACD indicator output.

    Attributes:
        macd_line: MACD line values (fast EMA - slow EMA).
        signal_line: Signal line values (EMA of MACD line).
        histogram: Histogram values (MACD - signal).
    """

    macd_line: tuple[float, ...]
    signal_line: tuple[float, ...]
    histogram: tuple[float, ...]


@dataclass(frozen=True)
class BollingerResult:
    """Bollinger Bands output.

    Attributes:
        upper: Upper band values.
        middle: Middle band (SMA) values.
        lower: Lower band values.
        bandwidth: Bandwidth values (upper - lower) / middle.
    """

    upper: tuple[float, ...]
    middle: tuple[float, ...]
    lower: tuple[float, ...]
    bandwidth: tuple[float, ...]


@dataclass(frozen=True)
class SRLevel:
    """A single support or resistance level.

    Attributes:
        price: The price level.
        strength: Strength of the level (0.0 to 1.0).
        level_type: "support" or "resistance".
        touches: Number of times price has touched this level.
    """

    price: float
    strength: float
    level_type: str  # "support" | "resistance"
    touches: int = 0


@dataclass(frozen=True)
class SRLevels:
    """Support and resistance levels detected from OHLCV data.

    Attributes:
        supports: List of support levels sorted by price ascending.
        resistances: List of resistance levels sorted by price ascending.
    """

    supports: tuple[SRLevel, ...] = ()
    resistances: tuple[SRLevel, ...] = ()


# ═══════════════════════════════════════════════════════════════════════
# LLM TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM provider.

    Attributes:
        content: Generated text content.
        model: Model identifier that generated the response.
        provider: Provider name (e.g. "ollama", "openai").
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the completion.
        total_tokens: Total tokens used.
        latency_ms: Response latency in milliseconds.
        finish_reason: Why generation stopped ("stop", "length", "error").
        metadata: Additional provider-specific metadata.
    """

    content: str
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = "stop"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMChunk:
    """A single chunk in a streaming LLM response.

    Attributes:
        content: Text content of this chunk.
        chunk_index: Sequential index of this chunk.
        finish_reason: Non-None when this is the final chunk.
        metadata: Additional provider-specific metadata.
    """

    content: str
    chunk_index: int = 0
    finish_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCapabilities:
    """Capabilities of an LLM model.

    Describes what a model can do, used by the ModelRouter
    to match task requirements to available models.

    Attributes:
        model: Model identifier.
        max_context_tokens: Maximum context window size.
        supports_streaming: Whether the model supports streaming.
        supports_function_calling: Whether the model supports function/tool calling.
        supports_json_mode: Whether the model can output structured JSON.
        supports_vision: Whether the model accepts image inputs.
        cost_per_1k_input_tokens: Cost per 1000 input tokens (USD).
        cost_per_1k_output_tokens: Cost per 1000 output tokens (USD).
        avg_latency_ms: Average response latency in milliseconds.
    """

    model: str
    max_context_tokens: int = 4096
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_json_mode: bool = False
    supports_vision: bool = False
    cost_per_1k_input_tokens: float = 0.0
    cost_per_1k_output_tokens: float = 0.0
    avg_latency_ms: float = 0.0
