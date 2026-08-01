//! Real-time gas price tracker — monitors base fee and priority fee trends.

use std::collections::VecDeque;

use chrono::{DateTime, Utc};

use crate::types::ChainGasInfo;

/// Tracks gas price history for trend analysis.
pub struct GasTracker {
    /// Rolling window of gas price samples.
    history: VecDeque<GasSample>,
    /// Maximum samples to retain.
    max_samples: usize,
}

#[derive(Debug, Clone)]
struct GasSample {
    base_fee_gwei: f64,
    priority_fee_gwei: f64,
    gas_price_gwei: f64,
    block_number: u64,
    timestamp: DateTime<Utc>,
}

impl GasTracker {
    pub fn new(max_samples: usize) -> Self {
        Self {
            history: VecDeque::with_capacity(max_samples),
            max_samples,
        }
    }

    /// Record a new gas price sample.
    pub fn record(&mut self, info: &ChainGasInfo) {
        if self.history.len() >= self.max_samples {
            self.history.pop_front();
        }
        self.history.push_back(GasSample {
            base_fee_gwei: info.base_fee_gwei.unwrap_or(0.0),
            priority_fee_gwei: info.priority_fee_gwei,
            gas_price_gwei: info.gas_price_gwei,
            block_number: 0,
            timestamp: info.fetched_at,
        });
    }

    /// Get the average base fee over the history window.
    pub fn avg_base_fee(&self) -> f64 {
        if self.history.is_empty() {
            return 0.0;
        }
        let sum: f64 = self.history.iter().map(|s| s.base_fee_gwei).sum();
        sum / self.history.len() as f64
    }

    /// Get the average priority fee over the history window.
    pub fn avg_priority_fee(&self) -> f64 {
        if self.history.is_empty() {
            return 0.0;
        }
        let sum: f64 = self.history.iter().map(|s| s.priority_fee_gwei).sum();
        sum / self.history.len() as f64
    }

    /// Get the minimum base fee in the history window.
    pub fn min_base_fee(&self) -> f64 {
        self.history
            .iter()
            .map(|s| s.base_fee_gwei)
            .fold(f64::INFINITY, f64::min)
    }

    /// Get the maximum base fee in the history window.
    pub fn max_base_fee(&self) -> f64 {
        self.history
            .iter()
            .map(|s| s.base_fee_gwei)
            .fold(f64::NEG_INFINITY, f64::max)
    }

    /// Get the trend direction: positive = rising, negative = falling.
    pub fn trend(&self) -> f64 {
        if self.history.len() < 2 {
            return 0.0;
        }
        let recent: f64 = self
            .history
            .iter()
            .rev()
            .take(5)
            .map(|s| s.base_fee_gwei)
            .sum::<f64>()
            / 5.0_f64.min(self.history.len() as f64);
        let older: f64 = self
            .history
            .iter()
            .take(5)
            .map(|s| s.base_fee_gwei)
            .sum::<f64>()
            / 5.0_f64.min(self.history.len() as f64);
        recent - older
    }

    /// Get the current (latest) base fee.
    pub fn current_base_fee(&self) -> f64 {
        self.history
            .back()
            .map(|s| s.base_fee_gwei)
            .unwrap_or(0.0)
    }

    /// Get the number of samples recorded.
    pub fn sample_count(&self) -> usize {
        self.history.len()
    }

    /// Predict the base fee for the next block based on trend.
    pub fn predict_next_base_fee(&self) -> f64 {
        let current = self.current_base_fee();
        let trend = self.trend();
        // EIP-1559 adjusts by max 12.5% per block
        let max_change = current * 0.125;
        let predicted = current + trend.clamp(-max_change, max_change);
        predicted.max(0.0)
    }
}
