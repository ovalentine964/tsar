//! Gas optimizer types — recommendations, chain info, strategies.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Gas price strategy levels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GasStrategy {
    /// Minimum cost, may take longer.
    Economy,
    /// Balanced cost vs speed.
    Standard,
    /// Faster confirmation, higher cost.
    Fast,
    /// Highest priority, for time-sensitive operations.
    Aggressive,
}

impl GasStrategy {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Economy => "economy",
            Self::Standard => "standard",
            Self::Fast => "fast",
            Self::Aggressive => "aggressive",
        }
    }
}

impl std::fmt::Display for GasStrategy {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// Gas price information for a specific chain.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChainGasInfo {
    /// Chain name (e.g., "ethereum", "polygon").
    pub chain: String,
    /// Chain ID.
    pub chain_id: u64,
    /// Current base fee in gwei (EIP-1559 chains).
    pub base_fee_gwei: Option<f64>,
    /// Legacy gas price in gwei.
    pub gas_price_gwei: f64,
    /// Recommended priority fee in gwei.
    pub priority_fee_gwei: f64,
    /// Estimated gas cost in USD for a standard swap (~150k gas).
    pub swap_cost_usd: f64,
    /// Estimated confirmation time in seconds.
    pub est_confirmation_secs: u64,
    /// Block utilization percentage (0–100).
    pub block_utilization_pct: f64,
    /// When this info was fetched.
    pub fetched_at: DateTime<Utc>,
}

/// Gas price recommendation for a transaction.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GasRecommendation {
    /// Recommended strategy.
    pub strategy: GasStrategy,
    /// Recommended max fee per gas (gwei, EIP-1559).
    pub max_fee_gwei: f64,
    /// Recommended max priority fee per gas (gwei).
    pub max_priority_fee_gwei: f64,
    /// Legacy gas price (gwei, for non-EIP-1559 chains).
    pub gas_price_gwei: f64,
    /// Estimated gas limit.
    pub gas_limit: u64,
    /// Estimated total cost in ETH.
    pub estimated_cost_eth: f64,
    /// Estimated total cost in USD.
    pub estimated_cost_usd: f64,
    /// Estimated confirmation time in seconds.
    pub est_confirmation_secs: u64,
    /// Best chain to use (if comparing L2s).
    pub best_chain: String,
    /// All chain comparisons.
    pub chain_options: Vec<ChainGasInfo>,
    /// When this recommendation was generated.
    pub generated_at: DateTime<Utc>,
}

/// L2 comparison result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct L2Comparison {
    /// Chain name.
    pub chain: String,
    /// Chain ID.
    pub chain_id: u64,
    /// Estimated swap cost in USD.
    pub swap_cost_usd: f64,
    /// Estimated swap cost in native token.
    pub swap_cost_native: f64,
    /// Native token price in USD.
    pub native_token_price_usd: f64,
    /// Estimated confirmation time.
    pub est_confirmation_secs: u64,
    /// Whether the chain is EIP-1559 compatible.
    pub is_eip1559: bool,
    /// Security level (1 = L1, 2 = L2 optimistic, 3 = L2 zk).
    pub security_level: u8,
}
