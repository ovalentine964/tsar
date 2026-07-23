//! Unified error types for the TSAR Rust layer.
//!
//! All crates in the workspace use [`TsarError`] as their primary error type,
//! with domain-specific variants for each subsystem.

use thiserror::Error;

/// The top-level error type for all TSAR Rust operations.
#[derive(Error, Debug)]
pub enum TsarError {
    // ── WebSocket errors ──────────────────────────────────────────
    /// A WebSocket connection error occurred.
    #[error("WebSocket error: {0}")]
    WebSocket(String),

    /// Failed to connect to the WebSocket endpoint.
    #[error("WebSocket connection failed: {0}")]
    WebSocketConnect(String),

    /// The WebSocket connection was closed unexpectedly.
    #[error("WebSocket connection closed: {reason}")]
    WebSocketClosed { reason: String },

    /// Maximum reconnection attempts exceeded.
    #[error("Max reconnection attempts ({attempts}) exceeded for {url}")]
    ReconnectExhausted { attempts: u32, url: String },

    // ── Parsing errors ────────────────────────────────────────────
    /// Failed to parse a message from the exchange.
    #[error("Message parse error: {0}")]
    ParseError(String),

    /// JSON deserialization failed.
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    // ── Order errors ──────────────────────────────────────────────
    /// Order placement or management failed.
    #[error("Order error: {0}")]
    OrderError(String),

    /// The requested order was not found.
    #[error("Order not found: {order_id}")]
    OrderNotFound { order_id: String },

    /// The order parameters are invalid.
    #[error("Invalid order: {reason}")]
    InvalidOrder { reason: String },

    // ── Tick processing errors ────────────────────────────────────
    /// Tick processing or aggregation error.
    #[error("Tick processing error: {0}")]
    TickError(String),

    /// The ring buffer is full and cannot accept more data.
    #[error("Ring buffer full (capacity: {capacity})")]
    RingBufferFull { capacity: usize },

    // ── Configuration errors ──────────────────────────────────────
    /// Configuration loading or validation error.
    #[error("Configuration error: {0}")]
    ConfigError(String),

    // ── Generic ───────────────────────────────────────────────────
    /// An internal error that should not normally occur.
    #[error("Internal error: {0}")]
    Internal(String),

    /// A timeout occurred.
    #[error("Timeout after {0}ms")]
    Timeout(u64),
}

/// Convenience alias for Results using [`TsarError`].
pub type TsarResult<T> = Result<T, TsarError>;
