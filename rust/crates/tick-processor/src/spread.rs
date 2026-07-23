//! Bid-ask spread calculation and monitoring.
//!
//! Computes real-time spreads from order book state and tracks
//! spread statistics over time.

use chrono::{DateTime, Utc};
use tsar_core::types::Spread;

/// Statistics for spread over a rolling window.
#[derive(Debug, Clone)]
pub struct SpreadStats {
    pub symbol: String,
    pub current_bps: f64,
    pub min_bps: f64,
    pub max_bps: f64,
    pub avg_bps: f64,
    pub sample_count: u64,
}

/// Calculates and tracks bid-ask spreads for trading pairs.
#[derive(Debug)]
pub struct SpreadCalculator {
    /// Rolling window of recent spread samples (in bps).
    samples: Vec<f64>,
    /// Maximum number of samples to retain.
    max_samples: usize,
    /// Symbol being tracked.
    symbol: String,
}

impl SpreadCalculator {
    /// Create a new spread calculator for a symbol.
    pub fn new(symbol: impl Into<String>, max_samples: usize) -> Self {
        Self {
            symbol: symbol.into(),
            samples: Vec::with_capacity(max_samples),
            max_samples,
        }
    }

    /// Calculate spread from the best bid and ask prices.
    ///
    /// Returns a [`Spread`] and records the sample.
    pub fn calculate(&mut self, bid: f64, ask: f64) -> Option<Spread> {
        if bid <= 0.0 || ask <= 0.0 || ask < bid {
            return None;
        }

        let spread_abs = ask - bid;
        let mid = (bid + ask) / 2.0;
        let spread_bps = if mid > 0.0 {
            (spread_abs / mid) * 10_000.0
        } else {
            return None;
        };

        // Record sample
        if self.samples.len() >= self.max_samples {
            self.samples.remove(0);
        }
        self.samples.push(spread_bps);

        Some(Spread {
            symbol: self.symbol.clone(),
            bid,
            ask,
            spread_abs,
            spread_bps,
            timestamp: Utc::now(),
        })
    }

    /// Get spread statistics from the rolling window.
    pub fn stats(&self) -> Option<SpreadStats> {
        if self.samples.is_empty() {
            return None;
        }

        let min = self.samples.iter().cloned().fold(f64::INFINITY, f64::min);
        let max = self.samples.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let sum: f64 = self.samples.iter().sum();
        let avg = sum / self.samples.len() as f64;
        let current = *self.samples.last().unwrap_or(&0.0);

        Some(SpreadStats {
            symbol: self.symbol.clone(),
            current_bps: current,
            min_bps: min,
            max_bps: max,
            avg_bps: avg,
            sample_count: self.samples.len() as u64,
        })
    }

    /// Clear all samples.
    pub fn reset(&mut self) {
        self.samples.clear();
    }

    /// Number of samples collected.
    pub fn sample_count(&self) -> usize {
        self.samples.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spread_calculation() {
        let mut calc = SpreadCalculator::new("BTC/USDT", 100);
        let spread = calc.calculate(49900.0, 50000.0).unwrap();

        assert_eq!(spread.symbol, "BTC/USDT");
        assert_eq!(spread.bid, 49900.0);
        assert_eq!(spread.ask, 50000.0);
        assert!((spread.spread_abs - 100.0).abs() < f64::EPSILON);
        assert!((spread.spread_bps - 20.02).abs() < 0.1); // ~20 bps
    }

    #[test]
    fn test_invalid_spread_returns_none() {
        let mut calc = SpreadCalculator::new("BTC/USDT", 100);
        assert!(calc.calculate(50000.0, 49900.0).is_none()); // ask < bid
        assert!(calc.calculate(0.0, 50000.0).is_none()); // zero bid
    }

    #[test]
    fn test_spread_stats() {
        let mut calc = SpreadCalculator::new("BTC/USDT", 100);
        calc.calculate(49900.0, 50000.0);
        calc.calculate(49950.0, 50050.0);
        calc.calculate(49980.0, 50020.0);

        let stats = calc.stats().unwrap();
        assert_eq!(stats.sample_count, 3);
        assert!(stats.min_bps > 0.0);
        assert!(stats.max_bps >= stats.min_bps);
    }
}
