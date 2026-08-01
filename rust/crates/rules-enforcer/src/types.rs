//! Shared types for the rules enforcer.

use serde::{Deserialize, Serialize};

/// Result of an on-chain rule check.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleCheckResult {
    /// Whether the trade is allowed
    pub allowed: bool,
    /// Human-readable reason (empty if allowed)
    pub reason: String,
    /// Which rule was checked
    pub rule_id: String,
    /// Timestamp of the check
    pub timestamp: u64,
}

/// Kill switch status from on-chain.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KillSwitchStatus {
    /// Whether kill switch is active
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

/// Mandate status from on-chain.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MandateStatus {
    /// Mandate version
    pub version: u64,
    /// Mandate status (DRAFT, ACTIVE, REVOKED)
    pub status: String,
    /// Max position size in bps
    pub max_position_size_bps: u64,
    /// Max leverage in bps
    pub max_leverage_bps: u64,
    /// Max daily trades
    pub max_daily_trades: u64,
    /// Max total exposure in bps
    pub max_total_exposure_bps: u64,
    /// Whether short selling is allowed
    pub allow_short_selling: bool,
}

/// Trade record for on-chain logging.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradeRecord {
    /// Symbol hash (keccak256 of symbol string)
    pub symbol_hash: [u8; 32],
    /// Side: 0=BUY, 1=SELL
    pub side: u8,
    /// Notional value in wei
    pub notional: u64,
    /// Execution price (18 decimals)
    pub price: u64,
    /// Base asset quantity (18 decimals)
    pub quantity: u64,
    /// Leverage used in basis points
    pub leverage_bps: u64,
    /// Realized P&L in wei (negative = loss)
    pub realized_pnl: i64,
    /// Exchange order ID hash
    pub order_id: [u8; 32],
}

/// Circuit breaker levels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[repr(u8)]
pub enum CircuitBreakerLevel {
    Green = 0,
    Yellow = 1,
    Orange = 2,
    Red = 3,
}

/// Enforcement action types.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[repr(u8)]
pub enum EnforcementActionType {
    KillSwitch = 0,
    MandateBlock = 1,
    PositionLimit = 2,
    LeverageBlock = 3,
}

/// Blockchain configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BlockchainConfig {
    /// RPC endpoint URL (WebSocket)
    pub rpc_url: String,
    /// Chain ID (137 for Polygon mainnet, 80001 for Mumbai testnet)
    pub chain_id: u64,
    /// Private key for signing transactions (hex string, no 0x prefix)
    pub private_key: String,
    /// Kill switch contract address
    pub kill_switch_address: String,
    /// Mandate contract address
    pub mandate_address: String,
    /// Audit trail contract address
    pub audit_trail_address: String,
    /// Governance contract address
    pub governance_address: String,
    /// Gas price in gwei
    pub gas_price_gwei: u64,
    /// Gas limit for transactions
    pub gas_limit: u64,
}

impl Default for BlockchainConfig {
    fn default() -> Self {
        Self {
            rpc_url: "wss://polygon-mumbai.g.alchemy.com/v2/YOUR_KEY".to_string(),
            chain_id: 80001,
            private_key: String::new(),
            kill_switch_address: String::new(),
            mandate_address: String::new(),
            audit_trail_address: String::new(),
            governance_address: String::new(),
            gas_price_gwei: 30,
            gas_limit: 500_000,
        }
    }
}
