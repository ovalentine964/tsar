//! Shared types for Solana client operations.

use serde::{Deserialize, Serialize};

/// Solana cluster configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SolanaClusterConfig {
    pub name: String,
    pub rpc_url: String,
    pub ws_url: Option<String>,
    pub commitment: String,
}

impl Default for SolanaClusterConfig {
    fn default() -> Self {
        Self {
            name: "mainnet-beta".to_string(),
            rpc_url: "https://api.mainnet-beta.solana.com".to_string(),
            ws_url: None,
            commitment: "confirmed".to_string(),
        }
    }
}

/// Jupiter swap request parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JupiterSwapRequest {
    pub input_mint: String,
    pub output_mint: String,
    pub amount: u64,
    pub slippage_bps: u16,
    pub user_public_key: String,
    pub wrap_unwrap_sol: bool,
    pub priority_fee_lamports: Option<u64>,
}

/// Jupiter swap response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JupiterSwapResponse {
    pub swap_transaction: String,
    pub last_valid_block_height: u64,
    pub prioritization_fee_lamports: u64,
}

/// Token account info.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenAccountInfo {
    pub mint: String,
    pub owner: String,
    pub amount: u64,
    pub decimals: u8,
    pub ui_amount: f64,
}

/// Solana transaction result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SolanaTransactionResult {
    pub signature: String,
    pub slot: u64,
    pub err: Option<String>,
    pub fee_lamports: u64,
    pub compute_units_consumed: u64,
}

/// Priority fee estimate.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PriorityFeeEstimate {
    pub micro_lamports_per_cu: u64,
    pub total_lamports: u64,
    pub total_sol: f64,
    pub total_usd: f64,
    pub sol_price_usd: f64,
}

/// Error types for Solana client operations.
#[derive(Debug, thiserror::Error)]
pub enum SolanaClientError {
    #[error("RPC error: {0}")]
    Rpc(String),

    #[error("Signing error: {0}")]
    Signing(String),

    #[error("Transaction failed: {0}")]
    TransactionFailed(String),

    #[error("Account not found: {0}")]
    AccountNotFound(String),

    #[error("Invalid keypair: {0}")]
    InvalidKeypair(String),

    #[error("Jupiter API error: {0}")]
    JupiterApi(String),

    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}
