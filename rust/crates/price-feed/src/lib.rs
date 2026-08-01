//! # tsar-price-feed
//!
//! Oracle price aggregation from multiple on-chain and off-chain sources.
//!
//! Aggregates prices from:
//! - Chainlink oracles (on-chain)
//! - Pyth Network (on-chain + off-chain)
//! - CoinGecko API (off-chain)
//! - CoinMarketCap API (off-chain)
//! - DEX spot prices (on-chain)
//!
//! Features:
//! - Multi-source median aggregation (outlier resistant)
//! - Stale price detection and fallback
//! - TWAP (Time-Weighted Average Price) computation
//! - Price deviation alerts

pub mod aggregator;
pub mod feed;
pub mod types;

pub use aggregator::PriceAggregator;
pub use feed::PriceFeed;
pub use types::{PriceSource, AggregatedPrice, PriceDeviation};
