//! # tsar-gas-optimizer
//!
//! Real-time gas tracking and L2 cost comparison for optimal transaction routing.
//!
//! Features:
//! - EIP-1559 base fee tracking and prediction
//! - Priority fee estimation based on mempool congestion
//! - Multi-chain gas price monitoring (ETH, Polygon, Arbitrum, Base, Optimism)
//! - L2 cost comparison for transaction routing
//! - Gas price percentile analysis
//!
//! ## Usage
//!
//! ```rust,no_run
//! use tsar_gas_optimizer::{GasOptimizer, GasConfig};
//!
//! # async fn example() -> Result<(), Box<dyn std::error::Error>> {
//! let config = GasConfig {
//!     eth_rpc_url: "https://eth-mainnet.g.alchemy.com/v2/KEY".to_string(),
//!     ..Default::default()
//! };
//! let optimizer = GasOptimizer::new(config);
//! let recommendation = optimizer.get_recommendation().await?;
//! # Ok(())
//! # }
//! ```

pub mod chains;
pub mod optimizer;
pub mod tracker;
pub mod types;

pub use optimizer::GasOptimizer;
pub use types::{ChainGasInfo, GasRecommendation, GasStrategy};
