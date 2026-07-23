//! # tsar-core
//!
//! Core shared types, error types, and configuration structures for the TSAR
//! (Trading Super Agent Regime) trading system.
//!
//! This crate provides the foundational types used across all TSAR Rust crates:
//! - [`types`] — Shared data types (Price, OHLCV, Order, Ticker, etc.)
//! - [`error`] — Unified error types using `thiserror`
//! - [`config`] — Configuration structures for exchanges, risk, and system settings

pub mod config;
pub mod error;
pub mod types;

// Re-export commonly used types at crate root
pub use config::TsarConfig;
pub use error::TsarError;
pub use types::{
    Candle, OrderBook, OrderBookEntry, OrderSide, OrderStatus, OrderType, Position, Price,
    Ticker, Trade, OHLCV,
};
