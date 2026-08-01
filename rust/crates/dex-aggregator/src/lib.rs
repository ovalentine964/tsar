//! # tsar-dex-aggregator
//!
//! Multi-DEX quote comparison and optimal route finding for DeFi swaps.
//!
//! Aggregates quotes from multiple DEX sources:
//! - Uniswap V2/V3 (Ethereum, Arbitrum, Base, Polygon)
//! - SushiSwap
//! - Curve Finance
//! - Balancer V2
//! - 1inch Aggregation API
//! - Jupiter (Solana)
//!
//! Features:
//! - Parallel quote fetching from all sources
//! - Price impact calculation
//! - Optimal route splitting for large orders
//! - Slippage-aware quote comparison

pub mod aggregator;
pub mod routes;
pub mod types;

pub use aggregator::DexAggregator;
pub use types::{DexQuote, DexSource, SwapRoute};
