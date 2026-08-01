//! MEV scanner types — risk assessment, pending swaps, sandwich patterns.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// MEV risk severity levels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MEVRiskLevel {
    Low,
    Medium,
    High,
    Critical,
}

impl MEVRiskLevel {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::Medium => "medium",
            Self::High => "high",
            Self::Critical => "critical",
        }
    }

    /// Create from a numeric score (0.0–1.0).
    pub fn from_score(score: f64) -> Self {
        if score >= 0.8 {
            Self::Critical
        } else if score >= 0.5 {
            Self::High
        } else if score >= 0.2 {
            Self::Medium
        } else {
            Self::Low
        }
    }
}

impl std::fmt::Display for MEVRiskLevel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// A pending swap detected in the mempool.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PendingSwap {
    /// Transaction hash.
    pub tx_hash: String,
    /// Sender address.
    pub from: String,
    /// DEX router contract.
    pub router: String,
    /// Token being sold.
    pub token_in: String,
    /// Token being bought.
    pub token_out: String,
    /// Amount of token_in (in token units, not wei).
    pub amount_in: f64,
    /// Minimum output amount.
    pub amount_out_min: f64,
    /// Gas price in gwei.
    pub gas_price_gwei: f64,
    /// Max priority fee (EIP-1559) in gwei.
    pub max_priority_fee_gwei: Option<f64>,
    /// Block number when detected.
    pub block_number: u64,
    /// Timestamp when observed.
    pub timestamp: DateTime<Utc>,
    /// Detected slippage tolerance (%).
    pub slippage_pct: f64,
}

/// A detected sandwich attack pattern.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandwichPattern {
    /// The victim swap transaction.
    pub victim_tx: String,
    /// The frontrun transaction hash.
    pub frontrun_tx: String,
    /// The backrun transaction hash.
    pub backrun_tx: String,
    /// Address of the attacker.
    pub attacker: String,
    /// Token pair being sandwiched.
    pub token_pair: (String, String),
    /// Estimated profit in USD.
    pub estimated_profit_usd: f64,
    /// Estimated loss to victim in USD.
    pub estimated_victim_loss_usd: f64,
    /// Confidence score (0.0–1.0).
    pub confidence: f64,
    /// When the pattern was detected.
    pub detected_at: DateTime<Utc>,
}

/// Full MEV risk assessment for a proposed swap.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MEVRisk {
    /// Trading pair.
    pub pair: String,
    /// Swap amount in base token.
    pub amount: f64,
    /// Risk level.
    pub risk_level: MEVRiskLevel,
    /// Numeric risk score (0.0–1.0).
    pub risk_score: f64,
    /// Whether a sandwich pattern is currently pending.
    pub sandwich_detected: bool,
    /// Detected sandwich patterns (if any).
    pub sandwich_patterns: Vec<SandwichPattern>,
    /// Addresses of detected arbitrage bots in the mempool.
    pub pending_arbitrageurs: Vec<String>,
    /// Recommended submission method.
    pub recommended_method: String,
    /// Estimated MEV loss if unprotected (USD).
    pub estimated_mev_loss_usd: f64,
    /// Recommended gas priority fee (gwei).
    pub gas_priority_gwei: f64,
    /// Human-readable explanation.
    pub details: String,
    /// When the assessment was computed.
    pub assessed_at: DateTime<Utc>,
}

/// Known DEX router addresses for pattern matching.
pub struct KnownRouters;

impl KnownRouters {
    pub const UNISWAP_V2: &'static str = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d";
    pub const UNISWAP_V3: &'static str = "0xe592427a0aece92de3edee1f18e0157c05861564";
    pub const SUSHISWAP: &'static str = "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f";
    pub const CURVE: &'static str = "0x99a58482bd75cbab83b27ec03ca68ff489b5788f";
    pub const BALANCER_V2: &'static str = "0xba12222222228d8ba445958a75a0704d566bf2c8";

    /// Check if an address is a known DEX router.
    pub fn is_known_router(address: &str) -> bool {
        let addr = address.to_lowercase();
        matches!(
            addr.as_str(),
            Self::UNISWAP_V2
                | Self::UNISWAP_V3
                | Self::SUSHISWAP
                | Self::CURVE
                | Self::BALANCER_V2
        )
    }

    /// Get all known router addresses (lowercase).
    pub fn all() -> &'static [&'static str] {
        &[
            Self::UNISWAP_V2,
            Self::UNISWAP_V3,
            Self::SUSHISWAP,
            Self::CURVE,
            Self::BALANCER_V2,
        ]
    }
}

/// Known MEV bot addresses (common on Ethereum mainnet).
pub struct KnownBots;

impl KnownBots {
    /// Check if an address is a known MEV bot.
    /// This is a simplified set — production should use a dynamic registry.
    pub fn is_known_bot(address: &str) -> bool {
        // Placeholder — in production, load from a config file or on-chain registry
        let _ = address;
        false
    }
}
