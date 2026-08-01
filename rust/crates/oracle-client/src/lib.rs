//! # tsar-oracle-client
//!
//! Oracle client for reading price feeds from Chainlink and Pyth,
//! with price aggregation and TWAP computation.
//!
//! ## Features
//!
//! - **Chainlink price feed reading** via ethers-rs contract calls
//! - **Pyth price feed reading** via pyth-sdk-solana
//! - **Multi-source price aggregation** with median filtering
//! - **TWAP computation** over configurable time windows
//! - **Staleness detection** for oracle data freshness

pub mod chainlink;
pub mod pyth;
pub mod aggregator;
pub mod types;

pub use aggregator::PriceAggregator;
pub use chainlink::ChainlinkClient;
pub use types::*;
