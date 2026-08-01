//! Shared types for blockchain rules enforcement.

use ethers::types::{Address, U256};
use serde::{Deserialize, Serialize};

/// Request to check an order against the on-chain mandate.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderCheckRequest {
    /// Trading pair (e.g., "BTC/USDT")
    pub symbol: String,
    /// Order type: 0=MARKET, 1=LIMIT, 2=STOP_MARKET, 3=STOP_LIMIT
    pub order_type: u8,
    /// Side: 0=BUY, 1=SELL
    pub side: u8,
    /// Trade notional as basis points of equity
    pub notional_bps: u64,
    /// Requested leverage in basis points (300 = 3x)
    pub leverage_bps: u64,
    /// Current daily trade count
    pub daily_trade_count: u64,
}

/// Result of on-chain order check.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderCheckResult {
    /// Whether the order passes mandate checks
    pub allowed: bool,
    /// Human-readable reason (empty if allowed)
    pub reason: String,
}

/// Result of on-chain position limit check.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionCheckResult {
    /// Whether the position passes all limit checks
    pub passed: bool,
    /// Human-readable reason (empty if passed)
    pub reason: String,
}

/// Trade record for on-chain audit trail.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradeRecord {
    /// Trading pair
    pub symbol: String,
    /// Side: BUY/SELL
    pub side: String,
    /// Quantity
    pub quantity: f64,
    /// Price
    pub price: f64,
    /// Timestamp (unix)
    pub timestamp: u64,
    /// Trade ID (from exchange)
    pub trade_id: String,
}

/// Risk check record for on-chain audit trail.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskCheckRecord {
    /// Signal identifier
    pub signal_id: String,
    /// Result: PASS/FAIL/VETO
    pub result: RiskCheckResult,
    /// Enforcement action taken
    pub action: EnforcementAction,
    /// Human-readable reason
    pub reason: String,
}

/// Risk check result enum.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum RiskCheckResult {
    Pass,
    Fail,
    Veto,
}

/// Enforcement action enum.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum EnforcementAction {
    None,
    SizeReduced,
    TradeBlocked,
    KillSwitch,
    CircuitBreaker,
}

/// Rule enforcement record for on-chain audit trail.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleEnforcementRecord {
    /// Rule identifier
    pub rule_id: String,
    /// Associated trade ID (empty if not trade-specific)
    pub trade_id: String,
    /// Enforcement action taken
    pub action: EnforcementAction,
    /// Why this action was taken
    pub reason: String,
}
