//! # tsar-ws-manager
//!
//! WebSocket connection manager for exchange market data streams.
//!
//! Provides connection pooling, automatic reconnection, and message parsing
//! for real-time exchange data feeds (trades, order books, OHLCV candles).
//!
//! ## Modules
//!
//! - [`connection`] — Single WebSocket connection lifecycle (tokio-tungstenite)
//! - [`pool`] — Connection pool managing multiple exchange streams
//! - [`parser`] — Message parsing for Binance trade/depth/kline streams
//! - [`reconnect`] — Auto-reconnection with exponential backoff

pub mod connection;
pub mod parser;
pub mod pool;
pub mod reconnect;

// Re-export primary public API
pub use connection::WsConnection;
pub use parser::ParsedMessage;
pub use pool::{BinanceStreamConfig, ConnectionPool};
pub use reconnect::ReconnectPolicy;
