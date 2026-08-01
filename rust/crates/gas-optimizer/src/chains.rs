//! Multi-chain gas configuration and L2 comparison.

use serde::{Deserialize, Serialize};

/// Supported chains for gas optimization.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Chain {
    Ethereum,
    Polygon,
    Arbitrum,
    Base,
    Optimism,
    Solana,
}

impl Chain {
    pub fn name(&self) -> &'static str {
        match self {
            Self::Ethereum => "ethereum",
            Self::Polygon => "polygon",
            Self::Arbitrum => "arbitrum",
            Self::Base => "base",
            Self::Optimism => "optimism",
            Self::Solana => "solana",
        }
    }

    pub fn chain_id(&self) -> u64 {
        match self {
            Self::Ethereum => 1,
            Self::Polygon => 137,
            Self::Arbitrum => 42161,
            Self::Base => 8453,
            Self::Optimism => 10,
            Self::Solana => 0, // Not EVM
        }
    }

    pub fn is_eip1559(&self) -> bool {
        !matches!(self, Self::Solana)
    }

    pub fn native_token(&self) -> &'static str {
        match self {
            Self::Ethereum => "ETH",
            Self::Polygon => "MATIC",
            Self::Arbitrum => "ETH",
            Self::Base => "ETH",
            Self::Optimism => "ETH",
            Self::Solana => "SOL",
        }
    }

    pub fn typical_swap_gas(&self) -> u64 {
        match self {
            Self::Ethereum => 150_000,
            Self::Polygon => 150_000,
            Self::Arbitrum => 150_000,
            Self::Base => 150_000,
            Self::Optimism => 150_000,
            Self::Solana => 200_000, // Compute units
        }
    }

    /// Get the RPC URL environment variable name for this chain.
    pub fn rpc_env_var(&self) -> &'static str {
        match self {
            Self::Ethereum => "ETH_RPC_URL",
            Self::Polygon => "POLYGON_RPC_URL",
            Self::Arbitrum => "ARBITRUM_RPC_URL",
            Self::Base => "BASE_RPC_URL",
            Self::Optimism => "OPTIMISM_RPC_URL",
            Self::Solana => "SOLANA_RPC_URL",
        }
    }

    pub fn all() -> &'static [Chain] {
        &[
            Self::Ethereum,
            Self::Polygon,
            Self::Arbitrum,
            Self::Base,
            Self::Optimism,
        ]
    }
}

/// Chain-specific gas parameters.
#[derive(Debug, Clone)]
pub struct ChainConfig {
    pub chain: Chain,
    pub rpc_url: String,
    pub ws_url: Option<String>,
    pub native_token_price_usd: f64,
}
