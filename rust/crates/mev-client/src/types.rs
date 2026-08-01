//! Shared types for MEV client operations.

use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

/// MEV bundle submission result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BundleResult {
    pub bundle_hash: String,
    pub status: BundleStatus,
    pub tx_hashes: Vec<String>,
    pub block_number: Option<u64>,
    pub gas_used: Option<u64>,
    pub effective_gas_price: Option<String>,
    pub submitted_at: DateTime<Utc>,
}

/// Bundle status.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum BundleStatus {
    Pending,
    Included,
    Failed,
    Expired,
}

impl std::fmt::Display for BundleStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BundleStatus::Pending => write!(f, "pending"),
            BundleStatus::Included => write!(f, "included"),
            BundleStatus::Failed => write!(f, "failed"),
            BundleStatus::Expired => write!(f, "expired"),
        }
    }
}

/// Flashbots bundle request.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FlashbotsBundleRequest {
    pub signed_transactions: Vec<String>,
    pub target_block: u64,
    pub min_timestamp: Option<u64>,
    pub max_timestamp: Option<u64>,
    pub reverting_tx_hashes: Vec<String>,
}

/// Jito bundle request.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JitoBundleRequest {
    pub serialized_transactions: Vec<String>,
    pub tip_lamports: u64,
}

/// Private transaction parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PrivateTransaction {
    pub signed_tx: String,
    pub chain_id: u64,
    pub max_block_number: Option<u64>,
    pub preferences: Option<TransactionPreferences>,
}

/// Transaction execution preferences.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransactionPreferences {
    pub fast_execution: bool,
    pub backrunnable: bool,
    pub frontrunnable: bool,
    pub max_slippage_bps: u16,
}

/// MEV protection configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MevProtectionConfig {
    pub use_flashbots: bool,
    pub use_jito: bool,
    pub use_private_mempool: bool,
    pub flashbots_relay_url: String,
    pub jito_block_engine_url: String,
    pub max_priority_fee_gwei: f64,
    pub solana_tip_lamports: u64,
}

impl Default for MevProtectionConfig {
    fn default() -> Self {
        Self {
            use_flashbots: true,
            use_jito: true,
            use_private_mempool: true,
            flashbots_relay_url: "https://relay.flashbots.net".to_string(),
            jito_block_engine_url: "https://mainnet.block-engine.jito.wtf".to_string(),
            max_priority_fee_gwei: 3.0,
            solana_tip_lamports: 10_000,
        }
    }
}

/// Error types for MEV client operations.
#[derive(Debug, thiserror::Error)]
pub enum MevClientError {
    #[error("Bundle submission failed: {0}")]
    BundleSubmission(String),

    #[error("Bundle expired: {0}")]
    BundleExpired(String),

    #[error("Invalid transaction: {0}")]
    InvalidTransaction(String),

    #[error("Relay error: {0}")]
    Relay(String),

    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}
