//! # tsar-rules-enforcer
//!
//! On-chain rule enforcement for TSAR via ethers-rs.
//!
//! This crate provides:
//! - Contract interaction with TSAR smart contracts (KillSwitch, Mandate, AuditTrail, Governance)
//! - Transaction signing and submission
//! - Event listening for rule enforcement
//! - PyO3 bindings for Python integration
//!
//! ## Architecture
//!
//! ```text
//! ┌──────────────┐     ┌───────────────────┐     ┌──────────────────┐
//! │ Python Layer │────▶│ Rust Rules Enforcer│────▶│ Polygon (EVM)    │
//! │ (backends/)  │◀────│ (this crate)       │◀────│ Smart Contracts  │
//! └──────────────┘     └───────────────────┘     └──────────────────┘
//! ```
//!
//! ## Contracts
//!
//! - `TSARKillSwitch` — Auto-halt on daily loss breach
//! - `TSARMandate` — Allowed symbols, leverage, position limits
//! - `TSARAuditTrail` — Immutable trade and rule enforcement logging
//! - `TSARGovernance` — Multi-sig + timelock admin

pub mod client;
pub mod contracts;
pub mod error;
pub mod events;
pub mod types;

#[cfg(feature = "python-bindings")]
pub mod pybridge;

pub use client::RulesEnforcerClient;
pub use error::RulesEnforcerError;
pub use types::*;
