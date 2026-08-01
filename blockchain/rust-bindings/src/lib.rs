//! TSAR Blockchain Rules Enforcement — Rust Bindings (ethers-rs)
//!
//! This crate provides Rust bindings for interacting with TSAR's on-chain
//! smart contracts. It bridges the gap between Python (brain) and
//! Solidity (trust layer).
//!
//! ARCHITECTURE:
//!   Python (off-chain) → PyO3 → Rust (this crate) → ethers-rs → Polygon
//!
//! DESIGN PRINCIPLES:
//!   - Off-chain: Python checks rules (fast path, ~0.1ms)
//!   - On-chain: Smart contract verifies enforcement (trust layer, ~2s)
//!   - Both must agree for a trade to proceed
//!   - On-chain has final authority (cannot be bypassed)

use ethers::prelude::*;
use ethers::providers::{Http, Provider};
use ethers::signers::{LocalWallet, Signer};
use ethers::types::{Address, U256};
use std::sync::Arc;
use thiserror::Error;

pub mod kill_switch;
pub mod mandate;
pub mod position_limits;
pub mod audit_trail;
pub mod types;

// ═══════════════════════════════════════════════════════════════════
// ERROR TYPES
// ═══════════════════════════════════════════════════════════════════

#[derive(Error, Debug)]
pub enum BlockchainError {
    #[error("Provider error: {0}")]
    Provider(String),

    #[error("Contract call failed: {0}")]
    ContractCall(String),

    #[error("Transaction failed: {0}")]
    Transaction(String),

    #[error("Kill switch is active — trading halted")]
    KillSwitchActive,

    #[error("Mandate violation: {0}")]
    MandateViolation(String),

    #[error("Position limit exceeded: {0}")]
    PositionLimitExceeded(String),

    #[error("Configuration error: {0}")]
    Config(String),

    #[error("Signing error: {0}")]
    Signing(String),
}

// ═══════════════════════════════════════════════════════════════════
// BLOCKCHAIN CLIENT
// ═══════════════════════════════════════════════════════════════════

/// Main client for interacting with TSAR's on-chain contracts.
///
/// This is the single entry point for all blockchain operations.
/// It manages the provider, wallet, and contract instances.
pub struct TSARBlockchainClient {
    /// Ethereum/Polygon provider
    provider: Arc<Provider<Http>>,

    /// Signing wallet (operator key)
    wallet: LocalWallet,

    /// Chain ID (137 = Polygon mainnet, 80001 = Mumbai testnet)
    chain_id: u64,

    /// Kill switch contract address
    kill_switch_address: Address,

    /// Mandate contract address
    mandate_address: Address,

    /// Position limits contract address
    position_limits_address: Address,

    /// Audit trail contract address
    audit_trail_address: Address,
}

impl TSARBlockchainClient {
    /// Create a new blockchain client.
    ///
    /// # Arguments
    /// * `rpc_url` - Polygon RPC endpoint (e.g., "https://polygon-rpc.com")
    /// * `private_key` - Operator wallet private key
    /// * `chain_id` - Chain ID (137 for mainnet, 80001 for testnet)
    /// * `contracts` - Contract addresses
    pub fn new(
        rpc_url: &str,
        private_key: &str,
        chain_id: u64,
        contracts: ContractAddresses,
    ) -> Result<Self, BlockchainError> {
        let provider = Provider::<Http>::try_from(rpc_url)
            .map_err(|e| BlockchainError::Provider(e.to_string()))?;

        let wallet: LocalWallet = private_key
            .parse()
            .map_err(|e| BlockchainError::Signing(e.to_string()))?
            .with_chain_id(chain_id);

        Ok(Self {
            provider: Arc::new(provider),
            wallet,
            chain_id,
            kill_switch_address: contracts.kill_switch,
            mandate_address: contracts.mandate,
            position_limits_address: contracts.position_limits,
            audit_trail_address: contracts.audit_trail,
        })
    }

    /// Check if trading is allowed (the PRIMARY check).
    ///
    /// This queries the on-chain kill switch. If it returns false,
    /// NO TRADE can proceed, regardless of what off-chain code says.
    pub async fn is_trading_allowed(&self) -> Result<bool, BlockchainError> {
        kill_switch::is_trading_allowed(
            &self.provider,
            self.kill_switch_address,
        )
        .await
    }

    /// Get full kill switch status for audit.
    pub async fn get_kill_switch_status(
        &self,
    ) -> Result<kill_switch::KillSwitchStatus, BlockchainError> {
        kill_switch::get_status(&self.provider, self.kill_switch_address).await
    }

    /// Update daily P&L on-chain (auto-triggers kill switch if breached).
    pub async fn update_daily_pnl(
        &self,
        daily_pnl_bps: i64,
    ) -> Result<TransactionReceipt, BlockchainError> {
        kill_switch::update_daily_pnl(
            &self.provider,
            &self.wallet,
            self.kill_switch_address,
            daily_pnl_bps,
        )
        .await
    }

    /// Update equity on-chain (checks drawdown circuit breakers).
    pub async fn update_equity(
        &self,
        equity: U256,
    ) -> Result<TransactionReceipt, BlockchainError> {
        kill_switch::update_equity(
            &self.provider,
            &self.wallet,
            self.kill_switch_address,
            equity,
        )
        .await
    }

    /// Check if an order complies with the on-chain mandate.
    pub async fn check_order(
        &self,
        order: &types::OrderCheckRequest,
    ) -> Result<types::OrderCheckResult, BlockchainError> {
        mandate::check_order(
            &self.provider,
            &self.wallet,
            self.mandate_address,
            order,
        )
        .await
    }

    /// Check if a position is within on-chain limits.
    pub async fn check_position_limit(
        &self,
        symbol: &str,
        sector: &str,
        notional: U256,
    ) -> Result<types::PositionCheckResult, BlockchainError> {
        position_limits::check_position_limit(
            &self.provider,
            &self.wallet,
            self.position_limits_address,
            symbol,
            sector,
            notional,
        )
        .await
    }

    /// Record a trade on-chain (immutable audit trail).
    pub async fn record_trade(
        &self,
        trade: &types::TradeRecord,
    ) -> Result<TransactionReceipt, BlockchainError> {
        audit_trail::record_trade(
            &self.provider,
            &self.wallet,
            self.audit_trail_address,
            trade,
        )
        .await
    }

    /// Log a risk check result on-chain.
    pub async fn log_risk_check(
        &self,
        check: &types::RiskCheckRecord,
    ) -> Result<TransactionReceipt, BlockchainError> {
        audit_trail::log_risk_check(
            &self.provider,
            &self.wallet,
            self.audit_trail_address,
            check,
        )
        .await
    }

    /// Log a rule enforcement action on-chain.
    pub async fn log_rule_enforcement(
        &self,
        enforcement: &types::RuleEnforcementRecord,
    ) -> Result<TransactionReceipt, BlockchainError> {
        audit_trail::log_rule_enforcement(
            &self.provider,
            &self.wallet,
            self.audit_trail_address,
            enforcement,
        )
        .await
    }
}

/// Contract addresses configuration.
#[derive(Debug, Clone)]
pub struct ContractAddresses {
    pub kill_switch: Address,
    pub mandate: Address,
    pub position_limits: Address,
    pub audit_trail: Address,
}
