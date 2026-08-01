//! Shared types for EVM client operations.

use serde::{Deserialize, Serialize};

/// Chain configuration for an EVM-compatible network.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChainConfig {
    pub chain_id: u64,
    pub name: String,
    pub rpc_url: String,
    pub ws_url: Option<String>,
    pub explorer_url: Option<String>,
    pub native_token: String,
    pub is_eip1559: bool,
}

impl Default for ChainConfig {
    fn default() -> Self {
        Self {
            chain_id: 1,
            name: "ethereum".to_string(),
            rpc_url: "https://eth.llamarpc.com".to_string(),
            ws_url: None,
            explorer_url: Some("https://etherscan.io".to_string()),
            native_token: "ETH".to_string(),
            is_eip1559: true,
        }
    }
}

/// Transaction request with full EIP-1559 support.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransactionRequest {
    pub to: String,
    pub value: String,
    pub data: String,
    pub chain_id: u64,
    pub gas_limit: Option<u64>,
    pub max_fee_per_gas: Option<String>,
    pub max_priority_fee_per_gas: Option<String>,
    pub nonce: Option<u64>,
}

/// Signed transaction result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignedTransaction {
    pub raw_tx: String,
    pub tx_hash: String,
    pub chain_id: u64,
    pub nonce: u64,
}

/// Transaction receipt after confirmation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransactionReceipt {
    pub tx_hash: String,
    pub block_number: u64,
    pub block_hash: String,
    pub gas_used: u64,
    pub effective_gas_price: String,
    pub status: bool,
    pub contract_address: Option<String>,
}

/// Gas estimate result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GasEstimate {
    pub gas_limit: u64,
    pub max_fee_per_gas_gwei: f64,
    pub max_priority_fee_gwei: f64,
    pub base_fee_gwei: f64,
    pub estimated_cost_eth: f64,
    pub estimated_cost_usd: f64,
    pub eth_price_usd: f64,
}

/// Swap quote from a DEX.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SwapQuote {
    pub source: String,
    pub token_in: String,
    pub token_out: String,
    pub amount_in: String,
    pub amount_out: String,
    pub price_impact_pct: f64,
    pub gas_estimate: u64,
    pub calldata: String,
    pub router_address: String,
}

/// Supported DeFi protocols.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Protocol {
    UniswapV3,
    OneInch,
    Chainlink,
    Aave,
    Compound,
}

impl std::fmt::Display for Protocol {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Protocol::UniswapV3 => write!(f, "Uniswap V3"),
            Protocol::OneInch => write!(f, "1inch"),
            Protocol::Chainlink => write!(f, "Chainlink"),
            Protocol::Aave => write!(f, "Aave"),
            Protocol::Compound => write!(f, "Compound"),
        }
    }
}

/// Error types for EVM client operations.
#[derive(Debug, thiserror::Error)]
pub enum EvmClientError {
    #[error("RPC error: {0}")]
    Rpc(String),

    #[error("Signing error: {0}")]
    Signing(String),

    #[error("ABI encoding error: {0}")]
    AbiEncoding(String),

    #[error("Transaction failed: {0}")]
    TransactionFailed(String),

    #[error("Gas estimation failed: {0}")]
    GasEstimation(String),

    #[error("Invalid address: {0}")]
    InvalidAddress(String),

    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}
