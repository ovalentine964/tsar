//! Shared data types for the TSAR trading system.
//!
//! These types represent the canonical data structures exchanged between
//! Rust components and exposed to Python via PyO3 bindings.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A price value with its associated symbol and timestamp.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Price {
    pub symbol: String,
    pub value: f64,
    pub timestamp: DateTime<Utc>,
}

/// OHLCV (Open, High, Low, Close, Volume) candle data.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OHLCV {
    pub symbol: String,
    pub timeframe: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
    pub timestamp: DateTime<Utc>,
}

/// A single candle — alias used by the tick processor aggregation pipeline.
pub type Candle = OHLCV;

/// Ticker snapshot for a trading pair.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ticker {
    pub symbol: String,
    pub bid: f64,
    pub ask: f64,
    pub last: f64,
    pub volume_24h: f64,
    pub change_24h_pct: f64,
    pub timestamp: DateTime<Utc>,
}

/// A single trade (fill) from the exchange stream.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trade {
    pub id: String,
    pub symbol: String,
    pub price: f64,
    pub amount: f64,
    pub side: OrderSide,
    pub timestamp: DateTime<Utc>,
}

/// Order book entry (price level).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderBookEntry {
    pub price: f64,
    pub amount: f64,
}

/// Full order book snapshot with bids and asks.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderBook {
    pub symbol: String,
    pub bids: Vec<OrderBookEntry>,
    pub asks: Vec<OrderBookEntry>,
    pub timestamp: DateTime<Utc>,
}

/// Order side — Buy or Sell.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OrderSide {
    Buy,
    Sell,
}

impl std::fmt::Display for OrderSide {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OrderSide::Buy => write!(f, "buy"),
            OrderSide::Sell => write!(f, "sell"),
        }
    }
}

/// Order type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OrderType {
    Market,
    Limit,
    StopLoss,
    StopLimit,
    TakeProfit,
}

impl std::fmt::Display for OrderType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OrderType::Market => write!(f, "market"),
            OrderType::Limit => write!(f, "limit"),
            OrderType::StopLoss => write!(f, "stop_loss"),
            OrderType::StopLimit => write!(f, "stop_limit"),
            OrderType::TakeProfit => write!(f, "take_profit"),
        }
    }
}

/// Order status lifecycle.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OrderStatus {
    Pending,
    Open,
    PartiallyFilled,
    Filled,
    Cancelled,
    Rejected,
    Expired,
}

impl std::fmt::Display for OrderStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OrderStatus::Pending => write!(f, "pending"),
            OrderStatus::Open => write!(f, "open"),
            OrderStatus::PartiallyFilled => write!(f, "partially_filled"),
            OrderStatus::Filled => write!(f, "filled"),
            OrderStatus::Cancelled => write!(f, "cancelled"),
            OrderStatus::Rejected => write!(f, "rejected"),
            OrderStatus::Expired => write!(f, "expired"),
        }
    }
}

/// A tracked order placed on an exchange.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub id: Uuid,
    pub exchange_order_id: Option<String>,
    pub symbol: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub quantity: f64,
    pub price: Option<f64>,
    pub stop_price: Option<f64>,
    pub filled_quantity: f64,
    pub average_fill_price: Option<f64>,
    pub status: OrderStatus,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// An open position on an exchange.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Position {
    pub symbol: String,
    pub side: OrderSide,
    pub quantity: f64,
    pub entry_price: f64,
    pub current_price: f64,
    pub unrealized_pnl: f64,
    pub stop_loss: Option<f64>,
    pub take_profit: Option<f64>,
    pub opened_at: DateTime<Utc>,
}

/// Spread between best bid and best ask.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Spread {
    pub symbol: String,
    pub bid: f64,
    pub ask: f64,
    pub spread_abs: f64,
    pub spread_bps: f64,
    pub timestamp: DateTime<Utc>,
}

/// A raw tick from the exchange WebSocket stream.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tick {
    pub symbol: String,
    pub price: f64,
    pub amount: f64,
    pub side: OrderSide,
    pub timestamp: DateTime<Utc>,
}
