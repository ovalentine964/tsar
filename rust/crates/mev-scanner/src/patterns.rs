//! Additional MEV pattern detection — JIT liquidity, statistical arbitrage.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// JIT (Just-in-Time) liquidity attack pattern.
///
/// Attacker adds liquidity just before a large swap, captures fees,
/// then removes liquidity immediately after.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JITLiquidityPattern {
    /// Transaction adding liquidity.
    pub add_liq_tx: String,
    /// The victim swap transaction.
    pub victim_tx: String,
    /// Transaction removing liquidity.
    pub remove_liq_tx: String,
    /// Attacker address.
    pub attacker: String,
    /// Pool/token pair.
    pub token_pair: (String, String),
    /// Estimated profit in USD.
    pub estimated_profit_usd: f64,
    /// Confidence score (0.0–1.0).
    pub confidence: f64,
    /// When detected.
    pub detected_at: DateTime<Utc>,
}

/// Statistical arbitrage bot activity detection.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatArbActivity {
    /// Bot address.
    pub bot_address: String,
    /// Number of recent transactions.
    pub tx_count: u64,
    /// Average gas price used.
    pub avg_gas_gwei: f64,
    /// Tokens involved.
    pub tokens: Vec<String>,
    /// Estimated total profit.
    pub estimated_profit_usd: f64,
    /// Detection timestamp.
    pub detected_at: DateTime<Utc>,
}

/// JIT liquidity detector.
pub struct JITDetector {
    /// Minimum liquidity add (USD) to consider.
    min_liq_usd: f64,
    /// Maximum time between add and remove (seconds).
    max_window_secs: i64,
}

impl JITDetector {
    pub fn new(min_liq_usd: f64, max_window_secs: i64) -> Self {
        Self {
            min_liq_usd,
            max_window_secs,
        }
    }

    /// Check if a sequence of transactions forms a JIT liquidity pattern.
    ///
    /// Input: ordered list of transactions for the same pool.
    pub fn detect(&self, txs: &[PendingTxInfo]) -> Option<JITLiquidityPattern> {
        // Look for: add_liq → swap → remove_liq within window
        if txs.len() < 3 {
            return None;
        }

        for i in 0..txs.len() - 2 {
            let add = &txs[i];
            let victim = &txs[i + 1];
            let remove = &txs[i + 2];

            // Check pattern: add liquidity → swap → remove liquidity
            if add.is_liquidity_add
                && victim.is_swap
                && remove.is_liquidity_remove
                && add.sender == remove.sender
                && add.sender != victim.sender
            {
                let time_delta =
                    (remove.timestamp - add.timestamp).num_seconds();

                if time_delta <= self.max_window_secs {
                    let confidence = if time_delta < 5 { 0.9 } else { 0.7 };

                    return Some(JITLiquidityPattern {
                        add_liq_tx: add.tx_hash.clone(),
                        victim_tx: victim.tx_hash.clone(),
                        remove_liq_tx: remove.tx_hash.clone(),
                        attacker: add.sender.clone(),
                        token_pair: (add.token_a.clone(), add.token_b.clone()),
                        estimated_profit_usd: 0.0, // Requires price data
                        confidence,
                        detected_at: Utc::now(),
                    });
                }
            }
        }

        None
    }
}

/// Simplified pending transaction info for pattern detection.
#[derive(Debug, Clone)]
pub struct PendingTxInfo {
    pub tx_hash: String,
    pub sender: String,
    pub token_a: String,
    pub token_b: String,
    pub is_swap: bool,
    pub is_liquidity_add: bool,
    pub is_liquidity_remove: bool,
    pub gas_price_gwei: f64,
    pub timestamp: DateTime<Utc>,
}
