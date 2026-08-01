//! Price aggregator — median aggregation from multiple sources.

use std::collections::HashMap;

use chrono::Utc;
use tracing::{debug, info, warn};

use crate::types::{AggregatedPrice, PriceDeviation, PriceObservation, PriceSource};

/// Configuration for the price aggregator.
#[derive(Debug, Clone)]
pub struct AggregatorConfig {
    /// Minimum number of sources required for a valid aggregation.
    pub min_sources: usize,
    /// Maximum age (seconds) before a price is considered stale.
    pub max_age_secs: u64,
    /// Deviation threshold (basis points) to trigger an alert.
    pub deviation_alert_bps: f64,
    /// Sources to query.
    pub sources: Vec<PriceSource>,
}

impl Default for AggregatorConfig {
    fn default() -> Self {
        Self {
            min_sources: 2,
            max_age_secs: 60,
            deviation_alert_bps: 500.0, // 5%
            sources: vec![
                PriceSource::CoinGecko,
                PriceSource::Binance,
                PriceSource::CoinMarketCap,
            ],
        }
    }
}

/// Aggregates prices from multiple sources using median.
///
/// Median aggregation is resistant to outliers (e.g., a single
/// source reporting an incorrect price).
pub struct PriceAggregator {
    config: AggregatorConfig,
    /// Recent observations per symbol.
    observations: HashMap<String, Vec<PriceObservation>>,
    /// TWAP history per symbol.
    twap_history: HashMap<String, Vec<crate::types::TwapEntry>>,
}

impl PriceAggregator {
    /// Create a new price aggregator.
    pub fn new(config: AggregatorConfig) -> Self {
        Self {
            config,
            observations: HashMap::new(),
            twap_history: HashMap::new(),
        }
    }

    /// Add a price observation from a source.
    pub fn add_observation(&mut self, obs: PriceObservation) {
        let symbol = obs.symbol.clone();
        self.observations
            .entry(symbol.clone())
            .or_insert_with(Vec::new)
            .push(obs.clone());

        // Update TWAP history
        self.twap_history
            .entry(symbol)
            .or_insert_with(Vec::new)
            .push(crate::types::TwapEntry {
                price: obs.price_usd,
                timestamp: obs.observed_at,
            });
    }

    /// Compute the aggregated price for a symbol.
    ///
    /// Returns the median price with statistics, or None if insufficient data.
    pub fn aggregate(&self, symbol: &str) -> Option<AggregatedPrice> {
        let obs = self.observations.get(symbol)?;
        let now = Utc::now();

        // Filter out stale observations
        let valid: Vec<&PriceObservation> = obs
            .iter()
            .filter(|o| {
                let age = (now - o.observed_at).num_seconds() as u64;
                age <= self.config.max_age_secs
            })
            .collect();

        if valid.len() < self.config.min_sources {
            return None;
        }

        // Extract prices and compute statistics
        let mut prices: Vec<f64> = valid.iter().map(|o| o.price_usd).collect();
        prices.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

        let median = if prices.len() % 2 == 0 {
            (prices[prices.len() / 2 - 1] + prices[prices.len() / 2]) / 2.0
        } else {
            prices[prices.len() / 2]
        };

        let mean = prices.iter().sum::<f64>() / prices.len() as f64;
        let min = prices[0];
        let max = *prices.last().unwrap();

        let variance: f64 = prices.iter().map(|p| (p - mean).powi(2)).sum::<f64>() / prices.len() as f64;
        let std_dev = variance.sqrt();

        // Confidence based on source count and consistency
        let source_score = (valid.len() as f64 / self.config.sources.len() as f64).min(1.0);
        let consistency_score = if median > 0.0 {
            1.0 - (std_dev / median).min(1.0)
        } else {
            0.0
        };
        let confidence = (source_score * 0.4 + consistency_score * 0.6).min(1.0);

        Some(AggregatedPrice {
            symbol: symbol.to_string(),
            price_usd: median,
            mean_price_usd: mean,
            min_price_usd: min,
            max_price_usd: max,
            std_dev_usd: std_dev,
            source_count: valid.len(),
            observations: valid.into_iter().cloned().collect(),
            failed_sources: Vec::new(),
            confidence,
            aggregated_at: now,
        })
    }

    /// Detect price deviations across sources.
    ///
    /// Returns any sources that deviate significantly from the median.
    pub fn detect_deviations(&self, symbol: &str) -> Vec<PriceDeviation> {
        let mut deviations = Vec::new();

        if let Some(agg) = self.aggregate(symbol) {
            for obs in &agg.observations {
                let deviation_bps = if agg.price_usd > 0.0 {
                    ((obs.price_usd - agg.price_usd).abs() / agg.price_usd) * 10_000.0
                } else {
                    0.0
                };

                if deviation_bps > self.config.deviation_alert_bps {
                    deviations.push(PriceDeviation {
                        symbol: symbol.to_string(),
                        source: obs.source,
                        deviating_price_usd: obs.price_usd,
                        median_price_usd: agg.price_usd,
                        deviation_bps,
                        detected_at: Utc::now(),
                    });
                }
            }
        }

        deviations
    }

    /// Compute TWAP (Time-Weighted Average Price) over a time window.
    pub fn twap(&self, symbol: &str, window_secs: i64) -> Option<f64> {
        let history = self.twap_history.get(symbol)?;
        if history.is_empty() {
            return None;
        }

        let now = Utc::now();
        let cutoff = now - chrono::Duration::seconds(window_secs);

        let recent: Vec<&crate::types::TwapEntry> =
            history.iter().filter(|e| e.timestamp >= cutoff).collect();

        if recent.is_empty() {
            return None;
        }

        // Simple TWAP: average of prices weighted by time intervals
        let total_price: f64 = recent.iter().map(|e| e.price).sum();
        Some(total_price / recent.len() as f64)
    }

    /// Clean up old observations and TWAP history.
    pub fn cleanup(&mut self, max_age_secs: i64) {
        let cutoff = Utc::now() - chrono::Duration::seconds(max_age_secs);
        for obs in self.observations.values_mut() {
            obs.retain(|o| o.observed_at > cutoff);
        }
        for history in self.twap_history.values_mut() {
            history.retain(|e| e.timestamp > cutoff);
        }
    }
}
