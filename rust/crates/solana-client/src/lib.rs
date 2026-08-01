//! # tsar-solana-client
//!
//! Solana blockchain client for Ed25519 transaction signing,
//! Jupiter swap building, and account data reading.
//!
//! ## Features
//!
//! - **Ed25519 transaction signing** via solana-sdk keypairs
//! - **Jupiter V6 swap transaction building**
//! - **Account data deserialization** (token accounts, programs)
//! - **Priority fee estimation** for fast confirmation
//! - **Compute unit budget management**

pub mod account;
pub mod client;
pub mod jupiter;
pub mod signer;
pub mod types;

pub use client::SolanaClient;
pub use signer::SolanaSigner;
pub use types::*;
