//! Position Limits — On-chain position limit enforcement.
//!
//! Smart contract enforces max position size, max total exposure,
//! and concentration limits. Cannot be exceeded by any code path.

use ethers::prelude::*;
use ethers::providers::{Http, Provider};
use ethers::types::{Address, U256};
use std::sync::Arc;

use super::BlockchainError;

// ═══════════════════════════════════════════════════════════════════
// CONTRACT ABI
// ═══════════════════════════════════════════════════════════════════

abigen!(
    TSARPositionLimits,
    r#"[
        function checkPositionLimit(bytes32 symbolHash, bytes32 sectorHash, uint256 notionalValue) external returns (bool passed, string reason)
        function openPosition(bytes32 symbolHash, bytes32 sectorHash, uint256 notionalValue, uint256 entryPrice, uint256 quantity) external
        function closePosition(bytes32 symbolHash) external
        function updateEquity(uint256 equity) external
        function getExposureMetrics() external view returns (uint256 totalExp, uint256 totalExpBps, uint256 openCount, uint256 maxPositions)
        function getSectorExposure(bytes32 sectorHash) external view returns (uint256 exposure, uint256 exposureBps)
        function getPosition(bytes32 symbolHash) external view returns (tuple(bytes32 symbolHash, bytes32 sectorHash, uint256 notionalValue, uint256 entryPrice, uint256 quantity, uint256 openedAt, bool isOpen) info, uint256 positionBps)
        event PositionOpened(bytes32 indexed symbolHash, bytes32 indexed sectorHash, uint256 notionalValue, uint256 positionBps, uint256 timestamp)
        event PositionClosed(bytes32 indexed symbolHash, uint256 notionalValue, uint256 timestamp)
        event PositionLimitCheck(bytes32 indexed symbolHash, uint256 requestedNotionalBps, uint256 maxAllowedBps, bool passed, string reason)
    ]"#
);

// ═══════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════

/// Result of on-chain position limit check.
#[derive(Debug, Clone)]
pub struct PositionCheckResult {
    /// Whether the position passes all limit checks
    pub passed: bool,
    /// Human-readable reason (empty if passed)
    pub reason: String,
}

/// Exposure metrics from on-chain query.
#[derive(Debug, Clone)]
pub struct ExposureMetrics {
    /// Total notional exposure
    pub total_exposure: U256,
    /// Total exposure as bps of equity
    pub total_exposure_bps: u64,
    /// Number of open positions
    pub open_count: u64,
    /// Maximum allowed positions
    pub max_positions: u64,
}

// ═══════════════════════════════════════════════════════════════════
// FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

/// Check if a new position is within all on-chain limits.
///
/// This is THE enforcement function. Called before every trade.
/// Checks: single position (15%), total exposure (100%), sector concentration (30%).
pub async fn check_position_limit(
    provider: &Arc<Provider<Http>>,
    wallet: &LocalWallet,
    contract_address: Address,
    symbol: &str,
    sector: &str,
    notional: U256,
) -> Result<PositionCheckResult, BlockchainError> {
    let client = Arc::new(SignerMiddleware::new(provider.clone(), wallet.clone()));
    let contract = TSARPositionLimits::new(contract_address, client);

    // Hash symbol and sector
    let symbol_hash = ethers::utils::keccak256(symbol.as_bytes());
    let sector_hash = ethers::utils::keccak256(sector.as_bytes());

    let (passed, reason) = contract
        .check_position_limit(
            H256::from(symbol_hash),
            H256::from(sector_hash),
            notional,
        )
        .call()
        .await
        .map_err(|e| BlockchainError::ContractCall(e.to_string()))?;

    Ok(PositionCheckResult { passed, reason })
}

/// Record a position opening on-chain.
///
/// Called AFTER a trade is executed (not before).
pub async fn open_position(
    provider: &Arc<Provider<Http>>,
    wallet: &LocalWallet,
    contract_address: Address,
    symbol: &str,
    sector: &str,
    notional: U256,
    entry_price: U256,
    quantity: U256,
) -> Result<TransactionReceipt, BlockchainError> {
    let client = Arc::new(SignerMiddleware::new(provider.clone(), wallet.clone()));
    let contract = TSARPositionLimits::new(contract_address, client);

    let symbol_hash = ethers::utils::keccak256(symbol.as_bytes());
    let sector_hash = ethers::utils::keccak256(sector.as_bytes());

    let tx = contract
        .open_position(
            H256::from(symbol_hash),
            H256::from(sector_hash),
            notional,
            entry_price,
            quantity,
        )
        .send()
        .await
        .map_err(|e| BlockchainError::Transaction(e.to_string()))?;

    tx.confirmations(1)
        .await
        .map_err(|e| BlockchainError::Transaction(e.to_string()))?
        .ok_or_else(|| BlockchainError::Transaction("No receipt".to_string()))
}

/// Record a position closing on-chain.
pub async fn close_position(
    provider: &Arc<Provider<Http>>,
    wallet: &LocalWallet,
    contract_address: Address,
    symbol: &str,
) -> Result<TransactionReceipt, BlockchainError> {
    let client = Arc::new(SignerMiddleware::new(provider.clone(), wallet.clone()));
    let contract = TSARPositionLimits::new(contract_address, client);

    let symbol_hash = ethers::utils::keccak256(symbol.as_bytes());

    let tx = contract
        .close_position(H256::from(symbol_hash))
        .send()
        .await
        .map_err(|e| BlockchainError::Transaction(e.to_string()))?;

    tx.confirmations(1)
        .await
        .map_err(|e| BlockchainError::Transaction(e.to_string()))?
        .ok_or_else(|| BlockchainError::Transaction("No receipt".to_string()))
}

/// Get current exposure metrics from on-chain.
pub async fn get_exposure_metrics(
    provider: &Arc<Provider<Http>>,
    contract_address: Address,
) -> Result<ExposureMetrics, BlockchainError> {
    let contract = TSARPositionLimits::new(contract_address, provider.clone());

    let (total_exp, total_exp_bps, open_count, max_positions) = contract
        .get_exposure_metrics()
        .call()
        .await
        .map_err(|e| BlockchainError::ContractCall(e.to_string()))?;

    Ok(ExposureMetrics {
        total_exposure: total_exp,
        total_exposure_bps: total_exp_bps.as_u64(),
        open_count: open_count.as_u64(),
        max_positions: max_positions.as_u64(),
    })
}
