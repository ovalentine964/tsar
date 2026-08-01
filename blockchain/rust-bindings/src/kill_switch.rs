//! Kill Switch — On-chain trading halt enforcement.
//!
//! The kill switch is the single most critical piece of state.
//! If it says "halt", nothing trades. Period.
//!
//! INTEGRATION:
//!   - Python RiskGovernor reads kill switch state via this module
//!   - Off-chain: Python checks if trading allowed (fast path)
//!   - On-chain: Smart contract is authoritative (trust layer)
//!   - If on-chain says halt, off-chain CANNOT override

use ethers::prelude::*;
use ethers::providers::{Http, Provider};
use ethers::types::{Address, I256, U256};
use std::sync::Arc;

use super::BlockchainError;

// ═══════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════

/// Full kill switch status from on-chain query.
#[derive(Debug, Clone)]
pub struct KillSwitchStatus {
    /// Whether kill switch is active (trading halted)
    pub active: bool,
    /// Activation reason
    pub reason: String,
    /// When it was activated (unix timestamp)
    pub activated_at: u64,
    /// Current daily P&L in basis points
    pub daily_pnl_bps: i64,
    /// Circuit breaker level (0=GREEN, 1=YELLOW, 2=ORANGE, 3=RED)
    pub circuit_breaker_level: u8,
    /// Current drawdown in basis points
    pub drawdown_bps: i64,
}

// ═══════════════════════════════════════════════════════════════════
// CONTRACT ABI (minimal — only the functions we need)
// ═══════════════════════════════════════════════════════════════════

abigen!(
    TSARKillSwitch,
    r#"[
        function isTradingAllowed() external view returns (bool)
        function getStatus() external view returns (bool active, string reason, uint256 activatedAt, int256 dailyPnl, uint8 circuitLevel, int256 drawdownBps)
        function updateDailyPnl(int256 dailyPnlBps) external
        function updateEquity(uint256 equity) external
        function isActive() external view returns (bool)
        function dailyPnlBps() external view returns (int256)
        function circuitBreakerLevel() external view returns (uint8)
        event KillSwitchActivated(string reason, uint256 timestamp, int256 dailyPnlBps, uint8 circuitBreakerLevel)
        event KillSwitchDeactivated(uint256 timestamp, address deactivator)
        event DailyPnlUpdated(int256 dailyPnlBps, uint256 timestamp, bool thresholdBreached)
        event EquityUpdated(uint256 equity, uint256 highWaterMark, int256 drawdownBps, uint8 circuitBreakerLevel)
    ]"#
);

// ═══════════════════════════════════════════════════════════════════
// FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

/// Check if trading is allowed on-chain.
///
/// This is THE authoritative check. Returns false if kill switch is active.
/// Python RiskGovernor should check this before every trade.
pub async fn is_trading_allowed(
    provider: &Arc<Provider<Http>>,
    contract_address: Address,
) -> Result<bool, BlockchainError> {
    let contract = TSARKillSwitch::new(contract_address, provider.clone());

    contract
        .is_trading_allowed()
        .call()
        .await
        .map_err(|e| BlockchainError::ContractCall(e.to_string()))
}

/// Get full kill switch status from on-chain.
///
/// Returns all relevant state: active status, reason, daily P&L,
/// circuit breaker level, and drawdown.
pub async fn get_status(
    provider: &Arc<Provider<Http>>,
    contract_address: Address,
) -> Result<KillSwitchStatus, BlockchainError> {
    let contract = TSARKillSwitch::new(contract_address, provider.clone());

    let (active, reason, activated_at, daily_pnl, circuit_level, drawdown) =
        contract
            .get_status()
            .call()
            .await
            .map_err(|e| BlockchainError::ContractCall(e.to_string()))?;

    Ok(KillSwitchStatus {
        active,
        reason,
        activated_at: activated_at.as_u64(),
        daily_pnl_bps: daily_pnl.as_i64(),
        circuit_breaker_level: circuit_level,
        drawdown_bps: drawdown.as_i64(),
    })
}

/// Update daily P&L on-chain.
///
/// If daily loss exceeds -2% (threshold), kill switch activates AUTOMATICALLY.
/// This cannot be prevented by any code path — it's enforced by the smart contract.
pub async fn update_daily_pnl(
    provider: &Arc<Provider<Http>>,
    wallet: &LocalWallet,
    contract_address: Address,
    daily_pnl_bps: i64,
) -> Result<TransactionReceipt, BlockchainError> {
    let client = Arc::new(SignerMiddleware::new(provider.clone(), wallet.clone()));
    let contract = TSARKillSwitch::new(contract_address, client);

    let pnl = I256::from(daily_pnl_bps);

    let tx = contract
        .update_daily_pnl(pnl)
        .send()
        .await
        .map_err(|e| BlockchainError::Transaction(e.to_string()))?;

    tx.confirmations(1).await.map_err(|e| BlockchainError::Transaction(e.to_string()))?
        .ok_or_else(|| BlockchainError::Transaction("No receipt".to_string()))
}

/// Update equity on-chain.
///
/// Checks drawdown circuit breakers. If drawdown exceeds -15%,
/// kill switch activates automatically.
pub async fn update_equity(
    provider: &Arc<Provider<Http>>,
    wallet: &LocalWallet,
    contract_address: Address,
    equity: U256,
) -> Result<TransactionReceipt, BlockchainError> {
    let client = Arc::new(SignerMiddleware::new(provider.clone(), wallet.clone()));
    let contract = TSARKillSwitch::new(contract_address, client);

    let tx = contract
        .update_equity(equity)
        .send()
        .await
        .map_err(|e| BlockchainError::Transaction(e.to_string()))?;

    tx.confirmations(1).await.map_err(|e| BlockchainError::Transaction(e.to_string()))?
        .ok_or_else(|| BlockchainError::Transaction("No receipt".to_string()))
}
