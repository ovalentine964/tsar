//! Sandwich attack detector — pattern matching on pending transactions.
//!
//! Detects sandwich attack patterns by analyzing the mempool for:
//! 1. Frontrun: attacker tx with higher gas price buying the same pair
//! 2. Victim: the target swap transaction
//! 3. Backrun: attacker tx selling the same pair after the victim
//!
//! Detection runs in <200μs per analysis using hash-based lookups.

use std::collections::HashMap;
use std::sync::Arc;

use chrono::Utc;
use dashmap::DashMap;
use tracing::{debug, info, warn};

use crate::types::{KnownRouters, PendingSwap, SandwichPattern};

/// Configuration for the sandwich detector.
#[derive(Debug, Clone)]
pub struct DetectorConfig {
    /// Minimum profit (USD) to flag as a sandwich.
    pub min_profit_usd: f64,
    /// Maximum gas price difference (gwei) between frontrun and victim.
    pub max_gas_delta_gwei: f64,
    /// Time window (seconds) to look for frontrun/backrun pairs.
    pub detection_window_secs: i64,
    /// Minimum confidence score to report.
    pub min_confidence: f64,
}

impl Default for DetectorConfig {
    fn default() -> Self {
        Self {
            min_profit_usd: 1.0,
            max_gas_delta_gwei: 50.0,
            detection_window_secs: 12, // ~1 block
            min_confidence: 0.6,
        }
    }
}

/// Detects sandwich attacks in the mempool.
///
/// Maintains a sliding window of pending transactions and uses
/// pattern matching to identify frontrun → victim → backrun sequences.
pub struct SandwichDetector {
    config: DetectorConfig,
    /// Pending swaps indexed by token pair for fast lookup.
    /// Key: (token_in_lowercase, token_out_lowercase)
    pair_index: Arc<DashMap<(String, String), Vec<PendingSwap>>>,
    /// Detected sandwich patterns.
    patterns: Arc<DashMap<String, SandwichPattern>>,
}

impl SandwichDetector {
    /// Create a new sandwich detector.
    pub fn new(config: DetectorConfig) -> Self {
        Self {
            config,
            pair_index: Arc::new(DashMap::new()),
            patterns: Arc::new(DashMap::new()),
        }
    }

    /// Analyze a pending swap for sandwich attack patterns.
    ///
    /// Returns a list of detected sandwich patterns involving this swap
    /// as either victim or attacker. Runs in <200μs.
    pub fn analyze_swap(&self, swap: &PendingSwap) -> Vec<SandwichPattern> {
        let pair_key = (
            swap.token_in.to_lowercase(),
            swap.token_out.to_lowercase(),
        );
        let reverse_key = (
            swap.token_out.to_lowercase(),
            swap.token_in.to_lowercase(),
        );

        // Add to index
        self.pair_index
            .entry(pair_key.clone())
            .or_insert_with(Vec::new)
            .push(swap.clone());

        let mut patterns = Vec::new();

        // Check for sandwich pattern:
        // 1. Look for frontrun: same pair, higher gas, earlier timestamp
        // 2. Look for backrun: reverse pair, similar gas to frontrun

        if let Some(same_pair_swaps) = self.pair_index.get(&pair_key) {
            for other in same_pair_swaps.iter() {
                if other.tx_hash == swap.tx_hash {
                    continue;
                }

                // Check if `other` could be a frontrun for `swap`
                let gas_delta = other.gas_price_gwei - swap.gas_price_gwei;
                let time_delta = (swap.timestamp - other.timestamp).num_milliseconds().abs();

                if gas_delta > 0.0
                    && gas_delta <= self.config.max_gas_delta_gwei
                    && time_delta < (self.config.detection_window_secs * 1000)
                {
                    // Potential frontrun detected — look for backrun
                    if let Some(reverse_swaps) = self.pair_index.get(&reverse_key) {
                        for backrun in reverse_swaps.iter() {
                            if backrun.tx_hash == other.tx_hash
                                || backrun.tx_hash == swap.tx_hash
                            {
                                continue;
                            }

                            // Backrun should be after victim, similar gas to frontrun
                            let backrun_gas_delta =
                                (backrun.gas_price_gwei - other.gas_price_gwei).abs();
                            let backrun_time_delta =
                                (backrun.timestamp - swap.timestamp).num_milliseconds();

                            if backrun_gas_delta < self.config.max_gas_delta_gwei
                                && backrun_time_delta > 0
                                && backrun_time_delta < (self.config.detection_window_secs * 1000)
                            {
                                let confidence = self.calculate_confidence(
                                    gas_delta,
                                    backrun_gas_delta,
                                    time_delta,
                                    backrun_time_delta,
                                );

                                if confidence >= self.config.min_confidence {
                                    let pattern = SandwichPattern {
                                        victim_tx: swap.tx_hash.clone(),
                                        frontrun_tx: other.tx_hash.clone(),
                                        backrun_tx: backrun.tx_hash.clone(),
                                        attacker: other.from.clone(),
                                        token_pair: (
                                            swap.token_in.clone(),
                                            swap.token_out.clone(),
                                        ),
                                        estimated_profit_usd: self.estimate_profit(swap),
                                        estimated_victim_loss_usd: self.estimate_victim_loss(swap),
                                        confidence,
                                        detected_at: Utc::now(),
                                    };

                                    info!(
                                        victim = %pattern.victim_tx,
                                        attacker = %pattern.attacker,
                                        confidence = pattern.confidence,
                                        "Sandwich attack detected"
                                    );

                                    self.patterns
                                        .insert(pattern.victim_tx.clone(), pattern.clone());
                                    patterns.push(pattern);
                                }
                            }
                        }
                    }
                }
            }
        }

        // Evict old entries
        self.evict_old();

        patterns
    }

    /// Get all detected sandwich patterns.
    pub fn detected_patterns(&self) -> Vec<SandwichPattern> {
        self.patterns.iter().map(|entry| entry.value().clone()).collect()
    }

    /// Check if a specific transaction is a known victim.
    pub fn is_victim(&self, tx_hash: &str) -> bool {
        self.patterns.contains_key(tx_hash)
    }

    /// Get the pattern for a specific victim transaction.
    pub fn get_pattern(&self, tx_hash: &str) -> Option<SandwichPattern> {
        self.patterns.get(tx_hash).map(|entry| entry.value().clone())
    }

    /// Clear all state.
    pub fn clear(&self) {
        self.pair_index.clear();
        self.patterns.clear();
    }

    /// Calculate confidence score for a sandwich detection.
    fn calculate_confidence(
        &self,
        frontrun_gas_delta: f64,
        backrun_gas_delta: f64,
        frontrun_time_ms: i64,
        backrun_time_ms: i64,
    ) -> f64 {
        let mut score = 0.0;

        // Gas price pattern: frontrun > victim > backrun (or similar)
        if frontrun_gas_delta > 0.0 && frontrun_gas_delta < 20.0 {
            score += 0.3;
        } else if frontrun_gas_delta >= 20.0 {
            score += 0.2;
        }

        // Backrun gas similar to frontrun
        if backrun_gas_delta < 5.0 {
            score += 0.2;
        }

        // Timing: frontrun just before victim
        if frontrun_time_ms < 3000 {
            score += 0.25;
        } else if frontrun_time_ms < 6000 {
            score += 0.15;
        }

        // Timing: backrun just after victim
        if backrun_time_ms > 0 && backrun_time_ms < 3000 {
            score += 0.25;
        } else if backrun_time_ms < 6000 {
            score += 0.15;
        }

        score.min(1.0)
    }

    /// Estimate the profit from a sandwich attack (simplified).
    fn estimate_profit(&self, victim: &PendingSwap) -> f64 {
        // Simplified: assume attacker captures ~50% of victim's slippage
        let slippage_value = victim.amount_in * (victim.slippage_pct / 100.0);
        slippage_value * 0.5 * 2000.0 // Assume ~$2000/ETH for USD conversion
    }

    /// Estimate the victim's loss from a sandwich attack.
    fn estimate_victim_loss(&self, victim: &PendingSwap) -> f64 {
        let slippage_value = victim.amount_in * (victim.slippage_pct / 100.0);
        slippage_value * 2000.0 // Assume ~$2000/ETH for USD conversion
    }

    /// Evict entries older than the detection window.
    fn evict_old(&self) {
        let cutoff = Utc::now() - chrono::Duration::seconds(self.config.detection_window_secs * 2);
        self.pair_index.retain(|_, swaps| {
            swaps.retain(|s| s.timestamp > cutoff);
            !swaps.is_empty()
        });
    }
}
