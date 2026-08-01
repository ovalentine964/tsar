//! Shared types for oracle client operations.

use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

/// Price observation from an oracle source.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PriceObservation {
    pub source: String,
    pub symbol: String,
    pub price_usd: f64,
    pub timestamp: DateTime<Utc>,
    pub confidence: f64,
    pub decimals: u8,
}

/// Aggregated price from multiple sources.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AggregatedPrice {
    pub symbol: String,
    pub price_usd: f64,
    pub median_price_usd: f64,
    pub mean_price_usd: f64,
    pub min_price_usd: f64,
    pub max_price_usd: f64,
    pub std_dev_usd: f64,
    pub source_count: usize,
    pub confidence: f64,
    pub observations: Vec<PriceObservation>,
    pub aggregated_at: DateTime<Utc>,
}

/// TWAP (Time-Weighted Average Price) result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TwapResult {
    pub symbol: String,
    pub twap: f64,
    pub window_secs: i64,
    pub observation_count: usize,
    pub oldest_price: f64,
    pub newest_price: f64,
}

/// Chainlink round data.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChainlinkRoundData {
    pub round_id: u64,
    pub answer: i128,
    pub started_at: u64,
    pub updated_at: u64,
    pub answered_in_round: u64,
    pub decimals: u8,
}

/// Price deviation detection result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PriceDeviation {
    pub symbol: String,
    pub source: String,
    pub deviating_price_usd: f64,
    pub median_price_usd: f64,
    pub deviation_bps: f64,
}

/// Chainlink feed configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChainlinkFeedConfig {
    pub symbol: String,
    pub feed_address: String,
    pub chain_id: u64,
    pub decimals: u8,
}

/// Error types for oracle client operations.
#[derive(Debug, thiserror::Error)]
pub enum OracleClientError {
    #[error("RPC error: {0}")]
    Rpc(String),

    #[error("Oracle data stale: {0}")]
    StaleData(String),

    #[error("Price deviation too high: {0}")]
    PriceDeviation(String),

    #[error("Insufficient data: {0}")]
    InsufficientData(String),

    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}
