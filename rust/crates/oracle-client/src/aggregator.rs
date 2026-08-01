//! Price aggregation and TWAP computation.
//!
//! Aggregates price observations from multiple oracle sources using
//! median filtering and computes time-weighted average prices.

use chrono::{DateTime, Duration, Utc};
use std::collections::HashMap;
use tracing::{debug, info, warn};

use crate::types::*;

/// Configuration for the price aggregator.
#[derive(Debug, Clone)]
pub struct AggregatorConfig {
    /// Maximum acceptable deviation between sources in basis points.
    pub max_deviation_bps: f64,
    /// Minimum number of sources for aggregation.
    pub min_sources: usize,
    /// TWAP window size in seconds.
    pub default_twap_window_secs: i64,
}

impl Default for AggregatorConfig {
    fn default() -> Self {
        Self {
            max_deviation_bps: 500.0, // 5%
            min_sources: 1,
            default_twap_window_secs: 3600, // 1 hour
        }
    }
}

/// Multi-source price aggregator with TWAP support.
pub struct PriceAggregator {
    config: AggregatorConfig,
    /// Historical observations per symbol.
    observations: HashMap<String, Vec<PriceObservation>>,
    /// Latest aggregated prices.
    latest: HashMap<String, AggregatedPrice>,
}

impl PriceAggregator {
    /// Create a new price aggregator.
    pub fn new(config: AggregatorConfig) -> Self {
        Self {
            config,
            observations: HashMap::new(),
            latest: HashMap::new(),
        }
    }

    /// Add a price observation.
    pub fn add_observation(&mut self, obs: PriceObservation) {
        let entry = self.observations.entry(obs.symbol.clone()).or_default();
        entry.push(obs);

        // Prune old observations (keep last 1000 per symbol)
        if entry.len() > 1000 {
            entry.drain(0..entry.len() - 1000);
        }
    }

    /// Aggregate prices from all sources for a symbol.
    ///
    /// Uses median filtering to exclude outlier prices.
    pub fn aggregate(&mut self, symbol: &str) -> Option<AggregatedPrice> {
        let obs = self.observations.get(symbol)?;
        if obs.is_empty() {
            return None;
        }

        // Get recent observations (within last 5 minutes)
        let cutoff = Utc::now() - Duration::minutes(5);
        let recent: Vec<&PriceObservation> = obs
            .iter()
            .filter(|o| o.timestamp > cutoff)
            .collect();

        if recent.is_empty() {
            return None;
        }

        let mut prices: Vec<f64> = recent.iter().map(|o| o.price_usd).collect();
        prices.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

        let n = prices.len();
        let median = if n % 2 == 1 {
            prices[n / 2]
        } else {
            (prices[n / 2 - 1] + prices[n / 2]) / 2.0
        };

        let mean = prices.iter().sum::<f64>() / n as f64;
        let variance = prices.iter().map(|p| (p - mean).powi(2)).sum::<f64>() / n as f64;
        let std_dev = variance.sqrt();

        // Confidence based on source count and price spread
        let spread_bps = if median > 0.0 {
            (prices[n - 1] - prices[0]) / median * 10_000.0
        } else {
            0.0
        };
        let confidence = if spread_bps > self.config.max_deviation_bps {
            warn!(symbol, spread_bps, "Price spread exceeds threshold");
            0.5
        } else {
            (n as f64 / 3.0).min(1.0) * (1.0 - spread_bps / 10_000.0)
        };

        let aggregated = AggregatedPrice {
            symbol: symbol.to_string(),
            price_usd: median,
            median_price_usd: median,
            mean_price_usd: mean,
            min_price_usd: prices[0],
            max_price_usd: prices[n - 1],
            std_dev_usd: std_dev,
            source_count: n,
            confidence,
            observations: recent.into_iter().cloned().collect(),
            aggregated_at: Utc::now(),
        };

        self.latest.insert(symbol.to_string(), aggregated.clone());

        debug!(
            symbol,
            price = median,
            sources = n,
            spread_bps,
            "Price aggregated"
        );

        Some(aggregated)
    }

    /// Detect price deviations across sources.
    pub fn detect_deviations(&self, symbol: &str) -> Vec<PriceDeviation> {
        let obs = match self.observations.get(symbol) {
            Some(o) => o,
            None => return vec![],
        };

        let cutoff = Utc::now() - Duration::minutes(5);
        let recent: Vec<&PriceObservation> = obs
            .iter()
            .filter(|o| o.timestamp > cutoff)
            .collect();

        if recent.len() < 2 {
            return vec![];
        }

        let mut prices: Vec<f64> = recent.iter().map(|o| o.price_usd).collect();
        prices.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let median = prices[prices.len() / 2];

        let mut deviations = Vec::new();
        for obs in &recent {
            if median > 0.0 {
                let dev_bps = (obs.price_usd - median).abs() / median * 10_000.0;
                if dev_bps > self.config.max_deviation_bps {
                    deviations.push(PriceDeviation {
                        symbol: symbol.to_string(),
                        source: obs.source.clone(),
                        deviating_price_usd: obs.price_usd,
                        median_price_usd: median,
                        deviation_bps: dev_bps,
                    });
                }
            }
        }

        deviations
    }

    /// Compute TWAP (Time-Weighted Average Price) for a symbol.
    ///
    /// # Arguments
    /// * `symbol` - Token symbol
    /// * `window_secs` - Time window in seconds
    pub fn twap(&self, symbol: &str, window_secs: i64) -> Option<f64> {
        let obs = self.observations.get(symbol)?;
        if obs.is_empty() {
            return None;
        }

        let cutoff = Utc::now() - Duration::seconds(window_secs);
        let recent: Vec<&PriceObservation> = obs
            .iter()
            .filter(|o| o.timestamp > cutoff)
            .collect();

        if recent.is_empty() {
            return None;
        }

        // Sort by timestamp
        let mut sorted = recent;
        sorted.sort_by_key(|o| o.timestamp);

        // Time-weighted average: sum(price_i * dt_i) / sum(dt_i)
        let mut weighted_sum = 0.0;
        let mut total_weight = 0.0;

        for window in sorted.windows(2) {
            let dt = (window[1].timestamp - window[0].timestamp).num_seconds() as f64;
            let avg_price = (window[0].price_usd + window[1].price_usd) / 2.0;
            weighted_sum += avg_price * dt;
            total_weight += dt;
        }

        if total_weight <= 0.0 {
            // Single observation — just return its price
            return Some(sorted[0].price_usd);
        }

        Some(weighted_sum / total_weight)
    }

    /// Get the latest aggregated price for a symbol.
    pub fn latest_price(&self, symbol: &str) -> Option<&AggregatedPrice> {
        self.latest.get(symbol)
    }
}
