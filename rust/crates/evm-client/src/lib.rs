//! # tsar-evm-client
//!
//! EVM blockchain client for transaction signing, ABI encoding,
//! gas estimation, and DeFi protocol integration.
//!
//! ## Features
//!
//! - **Transaction signing** via ethers-rs local wallet
//! - **ABI encoding** for Uniswap V3, 1inch, and Chainlink contracts
//! - **EIP-1559 gas estimation** with base fee + priority fee calculation
//! - **Transaction submission** with confirmation tracking
//! - **Multi-chain support** (Ethereum, Arbitrum, Base, Polygon)

pub mod abi;
pub mod client;
pub mod gas;
pub mod signer;
pub mod types;

pub use client::EvmClient;
pub use signer::TransactionSigner;
pub use gas::GasEstimator;
pub use types::*;
