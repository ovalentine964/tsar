//! # tsar-mev-scanner
//!
//! Sub-millisecond mempool scanning and sandwich attack detection.
//!
//! Designed for DeFi MEV protection with <1ms latency targets:
//! - Real-time mempool transaction monitoring via WebSocket
//! - Sandwich attack pattern detection (frontrun + backrun)
//! - Just-in-Time (JIT) liquidity attack detection
//! - Statistical arbitrage bot identification
//! - MEV risk scoring for pending swaps
//!
//! ## Architecture
//!
//! Uses lock-free data structures (DashMap) and bloom filters for
//! O(1) address lookups. The mempool scanner runs on a dedicated
//! tokio task with pinned CPU affinity (when available).
//!
//! ## Latency Targets
//!
//! - Transaction parsing: <50μs
//! - Sandwich detection: <200μs
//! - Full risk assessment: <1ms

pub mod detector;
pub mod mempool;
pub mod patterns;
pub mod types;

pub use detector::SandwichDetector;
pub use mempool::MempoolScanner;
pub use types::{MEVRisk, MEVRiskLevel, PendingSwap, SandwichPattern};
