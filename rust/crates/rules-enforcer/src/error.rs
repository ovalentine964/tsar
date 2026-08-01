//! Error types for the rules enforcer.

use thiserror::Error;

/// Errors that can occur in the rules enforcer.
#[derive(Error, Debug)]
pub enum RulesEnforcerError {
    /// Ethereum provider error
    #[error("Provider error: {0}")]
    Provider(String),

    /// Contract call error
    #[error("Contract call error: {0}")]
    ContractCall(String),

    /// Transaction error
    #[error("Transaction error: {0}")]
    Transaction(String),

    /// ABI encoding/decoding error
    #[error("ABI error: {0}")]
    Abi(String),

    /// Configuration error
    #[error("Configuration error: {0}")]
    Config(String),

    /// Kill switch is active — trading halted
    #[error("Kill switch active: {reason}")]
    KillSwitchActive { reason: String },

    /// Mandate check failed
    #[error("Mandate check failed: {reason}")]
    MandateCheckFailed { reason: String },

    /// Transaction reverted on-chain
    #[error("Transaction reverted: {reason}")]
    TransactionReverted { reason: String },

    /// Event parsing error
    #[error("Event parsing error: {0}")]
    EventParsing(String),

    /// Serialization error
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    /// Generic error
    #[error("{0}")]
    Other(String),
}

impl From<ethers::providers::ProviderError> for RulesEnforcerError {
    fn from(e: ethers::providers::ProviderError) -> Self {
        RulesEnforcerError::Provider(e.to_string())
    }
}

impl From<ethers::contract::ContractError<ethers::providers::Provider<ethers::providers::Ws>>>
    for RulesEnforcerError
{
    fn from(
        e: ethers::contract::ContractError<ethers::providers::Provider<ethers::providers::Ws>>,
    ) -> Self {
        RulesEnforcerError::ContractCall(e.to_string())
    }
}

impl From<ethers::signers::WalletError> for RulesEnforcerError {
    fn from(e: ethers::signers::WalletError) -> Self {
        RulesEnforcerError::Transaction(e.to_string())
    }
}
