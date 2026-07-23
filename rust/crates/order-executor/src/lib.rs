//! # tsar-order-executor
//!
//! Low-latency order execution engine for placing, tracking, and managing
//! exchange orders.
//!
//! ## Modules
//!
//! - [`executor`] — Order placement and cancellation
//! - [`tracker`] — Order status tracking and lifecycle management
//! - [`types`] — Order-specific types and request/response structures

pub mod executor;
pub mod tracker;
pub mod types;

// Re-export primary public API
pub use executor::OrderExecutor;
pub use tracker::OrderTracker;
