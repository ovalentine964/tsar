//! Order-specific types and request/response structures.
//!
//! Defines the request and result types for order operations,
//! extending the base types from `tsar-core`.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use tsar_core::types::{OrderSide, OrderStatus, OrderType};

/// A request to place a new order.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderRequest {
    /// Unique request identifier.
    pub id: Uuid,
    /// Trading pair (e.g., "BTC/USDT").
    pub symbol: String,
    /// Buy or sell.
    pub side: OrderSide,
    /// Order type (market, limit, etc.).
    pub order_type: OrderType,
    /// Quantity to trade.
    pub quantity: f64,
    /// Limit price (required for limit orders).
    pub price: Option<f64>,
    /// Stop price (required for stop orders).
    pub stop_price: Option<f64>,
    /// Time in force.
    pub time_in_force: TimeInForce,
    /// Strategy name that generated this order.
    pub strategy: Option<String>,
    /// Signal score that triggered this order.
    pub signal_score: Option<f64>,
    /// When the request was created.
    pub created_at: DateTime<Utc>,
}

impl OrderRequest {
    /// Create a new market order request.
    pub fn market(symbol: impl Into<String>, side: OrderSide, quantity: f64) -> Self {
        Self {
            id: Uuid::new_v4(),
            symbol: symbol.into(),
            side,
            order_type: OrderType::Market,
            quantity,
            price: None,
            stop_price: None,
            time_in_force: TimeInForce::Ioc,
            strategy: None,
            signal_score: None,
            created_at: Utc::now(),
        }
    }

    /// Create a new limit order request.
    pub fn limit(
        symbol: impl Into<String>,
        side: OrderSide,
        quantity: f64,
        price: f64,
    ) -> Self {
        Self {
            id: Uuid::new_v4(),
            symbol: symbol.into(),
            side,
            order_type: OrderType::Limit,
            quantity,
            price: Some(price),
            stop_price: None,
            time_in_force: TimeInForce::Gtc,
            strategy: None,
            signal_score: None,
            created_at: Utc::now(),
        }
    }
}

/// Time-in-force options for orders.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum TimeInForce {
    /// Good Till Cancelled.
    Gtc,
    /// Immediate Or Cancel.
    Ioc,
    /// Fill Or Kill.
    Fok,
    /// Good Till Crossing (post-only).
    Gtx,
}

impl std::fmt::Display for TimeInForce {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TimeInForce::Gtc => write!(f, "GTC"),
            TimeInForce::Ioc => write!(f, "IOC"),
            TimeInForce::Fok => write!(f, "FOK"),
            TimeInForce::Gtx => write!(f, "GTX"),
        }
    }
}

/// Result of an order placement or status query.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderResult {
    /// Internal order ID.
    pub id: Uuid,
    /// Exchange-assigned order ID.
    pub exchange_order_id: String,
    /// Trading pair.
    pub symbol: String,
    /// Order side.
    pub side: OrderSide,
    /// Order type.
    pub order_type: OrderType,
    /// Requested quantity.
    pub quantity: f64,
    /// Filled quantity so far.
    pub filled_quantity: f64,
    /// Average fill price.
    pub average_fill_price: Option<f64>,
    /// Limit price.
    pub price: Option<f64>,
    /// Current order status.
    pub status: OrderStatus,
    /// Total fees paid.
    pub fee: f64,
    /// Fee currency.
    pub fee_currency: Option<String>,
    /// When the order was placed on the exchange.
    pub placed_at: DateTime<Utc>,
    /// When the order was last updated.
    pub updated_at: DateTime<Utc>,
}

/// A single fill (partial or full) on an order.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fill {
    /// Exchange-assigned fill ID.
    pub id: String,
    /// Associated order ID.
    pub order_id: String,
    /// Trading pair.
    pub symbol: String,
    /// Fill price.
    pub price: f64,
    /// Fill quantity.
    pub quantity: f64,
    /// Fee paid on this fill.
    pub fee: f64,
    /// Fee currency.
    pub fee_currency: String,
    /// Whether this was a maker or taker fill.
    pub is_maker: bool,
    /// When the fill occurred.
    pub timestamp: DateTime<Utc>,
}

/// Execution report for TWAP/VWAP algorithms.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionReport {
    /// Original request.
    pub request_id: Uuid,
    /// Child orders placed.
    pub child_orders: Vec<OrderResult>,
    /// Total filled quantity.
    pub total_filled: f64,
    /// Volume-weighted average price.
    pub vwap: f64,
    /// Total fees paid.
    pub total_fees: f64,
    /// Slippage in basis points vs. arrival price.
    pub slippage_bps: f64,
    /// Execution duration.
    pub duration_ms: u64,
    /// When execution completed.
    pub completed_at: DateTime<Utc>,
}
