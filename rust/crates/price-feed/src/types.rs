//! Price feed types — sources, aggregated prices, deviations.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Price data sources.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PriceSource {
    Chainlink,
    Pyth,
    CoinGecko,
    CoinMarketCap,
    UniswapV3,
    OneInch,
    Binance,
}

impl PriceSource {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Chainlink => "chainlink",
            Self::Pyth => "pyth",
            Self::CoinGecko => "coingecko",
            Self::CoinMarketCap => "coinmarketcap",
            Self::UniswapV3 => "uniswap_v3",
            Self::OneInch => "1inch",
            Self::Binance => "binance",
        }
    }

    /// Reliability score (higher = more trusted for pricing).
    pub fn reliability(&self) -> u8 {
        match self {
            Self::Chainlink => 10,
            Self::Pyth => 9,
            Self::Binance => 8,
            Self::UniswapV3 => 7,
            Self::CoinGecko => 6,
            Self::CoinMarketCap => 6,
            Self::OneInch => 5,
        }
    }
}

impl std::fmt::Display for PriceSource {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// A single price observation from a source.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PriceObservation {
    /// The source that provided this price.
    pub source: PriceSource,
    /// Token symbol (e.g., "ETH", "BTC").
    pub symbol: String,
    /// Price in USD.
    pub price_usd: f64,
    /// 24h volume in USD (if available).
    pub volume_24h_usd: Option<f64>,
    /// 24h price change percentage.
    pub change_24h_pct: Option<f64>,
    /// When the price was observed.
    pub observed_at: DateTime<Utc>,
    /// Maximum age before this price is considered stale (seconds).
    pub max_age_secs: u64,
}

/// Aggregated price from multiple sources.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AggregatedPrice {
    /// Token symbol.
    pub symbol: String,
    /// Aggregated (median) price in USD.
    pub price_usd: f64,
    /// Mean price across all sources.
    pub mean_price_usd: f64,
    /// Minimum price across sources.
    pub min_price_usd: f64,
    /// Maximum price across sources.
    pub max_price_usd: f64,
    /// Standard deviation of prices.
    pub std_dev_usd: f64,
    /// Number of sources that provided a price.
    pub source_count: usize,
    /// Individual observations.
    pub observations: Vec<PriceObservation>,
    /// Sources that failed or were stale.
    pub failed_sources: Vec<String>,
    /// Confidence score (0.0–1.0).
    pub confidence: f64,
    /// When the aggregation was computed.
    pub aggregated_at: DateTime<Utc>,
}

/// Price deviation alert.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PriceDeviation {
    /// Token symbol.
    pub symbol: String,
    /// Source with the deviating price.
    pub source: PriceSource,
    /// The deviating price.
    pub deviating_price_usd: f64,
    /// The median price from other sources.
    pub median_price_usd: f64,
    /// Deviation in basis points.
    pub deviation_bps: f64,
    /// When the deviation was detected.
    pub detected_at: DateTime<Utc>,
}

/// TWAP (Time-Weighted Average Price) entry.
#[derive(Debug, Clone)]
pub struct TwapEntry {
    pub price: f64,
    pub timestamp: DateTime<Utc>,
}
