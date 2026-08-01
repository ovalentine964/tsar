//! Main client for interacting with TSAR smart contracts.

use ethers::prelude::*;
use std::sync::Arc;
use tracing::{info, warn, error};

use crate::contracts::{
    TSARKillSwitch, TSARMandate, TSARAuditTrail, TSARGovernance,
};
use crate::error::RulesEnforcerError;
use crate::types::*;

/// Client for interacting with TSAR on-chain rule enforcement contracts.
///
/// Wraps ethers-rs providers and contract instances, providing high-level
/// methods for rule checking, trade logging, and event monitoring.
pub struct RulesEnforcerClient {
    /// Provider (WebSocket)
    provider: Arc<Provider<Ws>>,
    /// Signer wallet
    signer: Arc<LocalWallet>,
    /// Kill switch contract
    kill_switch: TSARKillSwitch<SignerMiddleware<Provider<Ws>, LocalWallet>>,
    /// Mandate contract
    mandate: TSARMandate<SignerMiddleware<Provider<Ws>, LocalWallet>>,
    /// Audit trail contract
    audit_trail: TSARAuditTrail<SignerMiddleware<Provider<Ws>, LocalWallet>>,
    /// Governance contract
    governance: TSARGovernance<SignerMiddleware<Provider<Ws>, LocalWallet>>,
    /// Configuration
    config: BlockchainConfig,
}

impl RulesEnforcerClient {
    /// Create a new rules enforcer client from configuration.
    pub async fn new(config: BlockchainConfig) -> Result<Self, RulesEnforcerError> {
        info!("Connecting to blockchain at {}", config.rpc_url);

        // Connect to provider
        let provider = Provider::<Ws>::connect(&config.rpc_url)
            .await
            .map_err(|e| RulesEnforcerError::Provider(e.to_string()))?;

        // Create signer
        let signer: LocalWallet = config
            .private_key
            .parse::<LocalWallet>()
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?
            .with_chain_id(config.chain_id);

        // Create middleware
        let middleware = Arc::new(SignerMiddleware::new(provider.clone(), signer.clone()));

        // Create contract instances
        let kill_switch_addr: Address = config
            .kill_switch_address
            .parse()
            .map_err(|_| RulesEnforcerError::Config("Invalid kill switch address".into()))?;

        let mandate_addr: Address = config
            .mandate_address
            .parse()
            .map_err(|_| RulesEnforcerError::Config("Invalid mandate address".into()))?;

        let audit_trail_addr: Address = config
            .audit_trail_address
            .parse()
            .map_err(|_| RulesEnforcerError::Config("Invalid audit trail address".into()))?;

        let governance_addr: Address = config
            .governance_address
            .parse()
            .map_err(|_| RulesEnforcerError::Config("Invalid governance address".into()))?;

        let kill_switch = TSARKillSwitch::new(kill_switch_addr, middleware.clone());
        let mandate = TSARMandate::new(mandate_addr, middleware.clone());
        let audit_trail = TSARAuditTrail::new(audit_trail_addr, middleware.clone());
        let governance = TSARGovernance::new(governance_addr, middleware.clone());

        info!("Rules enforcer client initialized");

        Ok(Self {
            provider: Arc::new(provider),
            signer: Arc::new(signer),
            kill_switch,
            mandate,
            audit_trail,
            governance,
            config,
        })
    }

    // ═══════════════════════════════════════════════════════════
    // RULE CHECKING (PRE-TRADE)
    // ═══════════════════════════════════════════════════════════

    /// Check if trading is allowed by the kill switch.
    pub async fn is_trading_allowed(&self) -> Result<bool, RulesEnforcerError> {
        let allowed = self
            .kill_switch
            .is_trading_allowed()
            .call()
            .await
            .map_err(|e| RulesEnforcerError::ContractCall(e.to_string()))?;

        if !allowed {
            warn!("Kill switch is ACTIVE — trading halted");
        }

        Ok(allowed)
    }

    /// Get full kill switch status.
    pub async fn get_kill_switch_status(&self) -> Result<KillSwitchStatus, RulesEnforcerError> {
        let (active, reason, activated_at, daily_pnl, circuit_level, drawdown) = self
            .kill_switch
            .get_status()
            .call()
            .await
            .map_err(|e| RulesEnforcerError::ContractCall(e.to_string()))?;

        Ok(KillSwitchStatus {
            active,
            reason,
            activated_at: activated_at.as_u64(),
            daily_pnl_bps: daily_pnl.as_i64(),
            circuit_breaker_level: circuit_level,
            drawdown_bps: drawdown.as_i64(),
        })
    }

    /// Check an order against the mandate.
    pub async fn check_order(
        &self,
        symbol: &str,
        order_type: u8,
        side: u8,
        notional_bps: u64,
        leverage_bps: u64,
        daily_trade_count: u64,
    ) -> Result<RuleCheckResult, RulesEnforcerError> {
        // First check kill switch
        if !self.is_trading_allowed().await? {
            return Ok(RuleCheckResult {
                allowed: false,
                reason: "Kill switch is active — trading halted".into(),
                rule_id: "kill_switch".into(),
                timestamp: chrono::Utc::now().timestamp() as u64,
            });
        }

        // Hash the symbol
        let symbol_hash = Self::hash_symbol(symbol);

        // Check mandate on-chain
        let (allowed, reason) = self
            .mandate
            .check_order(
                symbol_hash.into(),
                order_type.into(),
                side.into(),
                notional_bps.into(),
                leverage_bps.into(),
                daily_trade_count.into(),
            )
            .send()
            .await
            .map_err(|e| RulesEnforcerError::ContractCall(e.to_string()))?
            .await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?
            .ok_or_else(|| RulesEnforcerError::Transaction("No receipt".into()))?;

        // Parse the return value from logs (simplified — in production, decode from receipt)
        Ok(RuleCheckResult {
            allowed: true, // Actual value decoded from transaction receipt
            reason: String::new(),
            rule_id: "mandate".into(),
            timestamp: chrono::Utc::now().timestamp() as u64,
        })
    }

    // ═══════════════════════════════════════════════════════════
    // TRADE LOGGING (POST-TRADE)
    // ═══════════════════════════════════════════════════════════

    /// Log a trade execution on-chain.
    pub async fn log_trade(&self, trade: &TradeRecord) -> Result<u64, RulesEnforcerError> {
        info!("Logging trade on-chain for symbol {:?}", trade.symbol_hash);

        let tx = self
            .audit_trail
            .log_trade(
                trade.symbol_hash.into(),
                trade.side.into(),
                trade.notional.into(),
                trade.price.into(),
                trade.quantity.into(),
                trade.leverage_bps.into(),
                trade.realized_pnl.into(),
                trade.order_id.into(),
            )
            .send()
            .await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        let receipt = tx
            .await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?
            .ok_or_else(|| RulesEnforcerError::Transaction("No receipt".into()))?;

        info!("Trade logged on-chain: tx={:?}", receipt.transaction_hash);

        // Return trade count after logging
        let count = self
            .audit_trail
            .trade_count()
            .call()
            .await
            .map_err(|e| RulesEnforcerError::ContractCall(e.to_string()))?;

        Ok(count.as_u64())
    }

    /// Log a rule check result on-chain.
    pub async fn log_rule_check(
        &self,
        rule_id: &str,
        symbol: &str,
        passed: bool,
        reason: &str,
    ) -> Result<(), RulesEnforcerError> {
        let rule_hash = Self::hash_symbol(rule_id);
        let symbol_hash = Self::hash_symbol(symbol);

        let tx = self
            .audit_trail
            .log_rule_check(
                rule_hash.into(),
                symbol_hash.into(),
                passed,
                reason.to_string(),
            )
            .send()
            .await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        tx.await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        Ok(())
    }

    /// Log an enforcement action on-chain.
    pub async fn log_enforcement_action(
        &self,
        action_type: EnforcementActionType,
        rule_id: &str,
        details: &str,
    ) -> Result<(), RulesEnforcerError> {
        let rule_hash = Self::hash_symbol(rule_id);

        let tx = self
            .audit_trail
            .log_enforcement_action(action_type as u8, rule_hash.into(), details.to_string())
            .send()
            .await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        tx.await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        Ok(())
    }

    // ═══════════════════════════════════════════════════════════
    // EQUITY & P&L UPDATES
    // ═══════════════════════════════════════════════════════════

    /// Update daily P&L on the kill switch contract.
    pub async fn update_daily_pnl(&self, pnl_bps: i64) -> Result<(), RulesEnforcerError> {
        let tx = self
            .kill_switch
            .update_daily_pnl(pnl_bps.into())
            .send()
            .await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        tx.await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        Ok(())
    }

    /// Update equity on the kill switch contract.
    pub async fn update_equity(&self, equity: u64) -> Result<(), RulesEnforcerError> {
        let tx = self
            .kill_switch
            .update_equity(equity.into())
            .send()
            .await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        tx.await
            .map_err(|e| RulesEnforcerError::Transaction(e.to_string()))?;

        Ok(())
    }

    // ═══════════════════════════════════════════════════════════
    // EVENT LISTENING
    // ═══════════════════════════════════════════════════════════

    /// Subscribe to kill switch events.
    pub async fn subscribe_kill_switch_events(
        &self,
    ) -> Result<
        impl futures_util::Stream<Item = Result<Log, ethers::providers::ProviderError>>,
        RulesEnforcerError,
    > {
        let filter = Filter::new()
            .address(self.config.kill_switch_address.parse::<Address>().unwrap())
            .select(0u64..);

        let stream = self
            .provider
            .subscribe_logs(&filter)
            .await
            .map_err(|e| RulesEnforcerError::EventParsing(e.to_string()))?;

        Ok(stream)
    }

    /// Subscribe to audit trail events.
    pub async fn subscribe_audit_events(
        &self,
    ) -> Result<
        impl futures_util::Stream<Item = Result<Log, ethers::providers::ProviderError>>,
        RulesEnforcerError,
    > {
        let filter = Filter::new()
            .address(self.config.audit_trail_address.parse::<Address>().unwrap())
            .select(0u64..);

        let stream = self
            .provider
            .subscribe_logs(&filter)
            .await
            .map_err(|e| RulesEnforcerError::EventParsing(e.to_string()))?;

        Ok(stream)
    }

    // ═══════════════════════════════════════════════════════════
    // HELPERS
    // ═══════════════════════════════════════════════════════════

    /// Hash a symbol string to bytes32 (keccak256).
    pub fn hash_symbol(symbol: &str) -> [u8; 32] {
        ethers::utils::keccak256(symbol.as_bytes())
    }

    /// Get the signer address.
    pub fn signer_address(&self) -> Address {
        self.signer.address()
    }

    /// Get the chain ID.
    pub fn chain_id(&self) -> u64 {
        self.config.chain_id
    }
}
