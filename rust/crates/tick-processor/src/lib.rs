//! # tsar-tick-processor
//!
//! High-performance tick processing engine for real-time market data.
//!
//! ## Modules
//!
//! - [`aggregator`] — OHLCV candle aggregation from raw ticks
//! - [`orderbook`] — Order book maintenance and update application
//! - [`spread`] — Bid-ask spread calculation and monitoring
//! - [`ring_buffer`] — Lock-free ring buffer for tick storage

pub mod aggregator;
pub mod orderbook;
pub mod ring_buffer;
pub mod spread;

// Re-export primary public API
pub use aggregator::OhlcvAggregator;
pub use orderbook::OrderBookManager;
pub use ring_buffer::RingBuffer;
pub use spread::SpreadCalculator;
