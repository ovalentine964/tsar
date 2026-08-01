//! # tsar-mev-client
//!
//! MEV protection client for Flashbots bundle submission on Ethereum
//! and Jito bundle submission on Solana.
//!
//! ## Features
//!
//! - **Flashbots bundle submission** via ethers-rs relay API
//! - **Jito bundle submission** via Solana SDK
//! - **Private mempool interaction** to avoid public mempool exposure
//! - **Bundle status tracking** and confirmation

pub mod flashbots;
pub mod jito;
pub mod private_mempool;
pub mod types;

pub use flashbots::FlashbotsClient;
pub use jito::JitoClient;
pub use types::*;
