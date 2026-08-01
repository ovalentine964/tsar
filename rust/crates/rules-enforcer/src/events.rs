//! Event monitoring and parsing for TSAR smart contracts.

use ethers::prelude::*;
use serde::{Deserialize, Serialize};
use tracing::{info, warn};

use crate::error::RulesEnforcerError;

/// Parsed event from TSAR contracts.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum TsarEvent {
    /// Kill switch was activated
    KillSwitchActivated {
        reason: String,
        timestamp: u64,
        daily_pnl_bps: i64,
        circuit_breaker_level: u8,
    },
    /// Kill switch was deactivated
    KillSwitchDeactivated {
        timestamp: u64,
        deactivator: String,
    },
    /// Daily P&L was updated
    DailyPnlUpdated {
        daily_pnl_bps: i64,
        timestamp: u64,
        threshold_breached: bool,
    },
    /// Equity was updated
    EquityUpdated {
        equity: u64,
        high_water_mark: u64,
        drawdown_bps: i64,
        circuit_breaker_level: u8,
    },
    /// Circuit breaker level changed
    CircuitBreakerChanged {
        old_level: u8,
        new_level: u8,
        timestamp: u64,
    },
    /// Trade was logged
    TradeLogged {
        trade_id: u64,
        symbol_hash: String,
        side: u8,
        notional: u64,
        price: u64,
        realized_pnl: i64,
        timestamp: u64,
    },
    /// Rule check was logged
    RuleCheckLogged {
        check_id: u64,
        rule_id: String,
        symbol_hash: String,
        passed: bool,
        reason: String,
        timestamp: u64,
    },
    /// Enforcement action was logged
    EnforcementActionLogged {
        action_id: u64,
        action_type: u8,
        rule_id: String,
        details: String,
        timestamp: u64,
    },
    /// Order was checked against mandate
    OrderChecked {
        symbol_hash: String,
        order_type: u64,
        allowed: bool,
        reason: String,
    },
    /// Mandate was committed
    MandateCommitted {
        version: u64,
        committed_by: String,
        timestamp: u64,
    },
    /// Governance proposal created
    ProposalCreated {
        proposal_id: u64,
        target: String,
        op_type: u8,
        description: String,
        proposer: String,
        timestamp: u64,
    },
    /// Governance proposal executed
    ProposalExecuted {
        proposal_id: u64,
        executor: String,
        timestamp: u64,
    },
    /// Emergency paused
    EmergencyPaused {
        by: String,
        timestamp: u64,
    },
    /// Unknown event
    Unknown {
        topic: String,
        data: String,
    },
}

/// Event topic hashes for quick matching.
pub mod topics {
    use ethers::prelude::*;

    /// keccak256("KillSwitchActivated(string,uint256,int256,uint8)")
    pub fn kill_switch_activated() -> H256 {
        "0x..."
            .parse()
            .unwrap_or_default()
    }

    /// keccak256("KillSwitchDeactivated(uint256,address)")
    pub fn kill_switch_deactivated() -> H256 {
        "0x..."
            .parse()
            .unwrap_or_default()
    }

    /// keccak256("TradeLogged(uint256,bytes32,uint8,uint256,uint256,int256,uint256)")
    pub fn trade_logged() -> H256 {
        "0x..."
            .parse()
            .unwrap_or_default()
    }

    /// keccak256("RuleCheckLogged(uint256,bytes32,bytes32,bool,string,uint256)")
    pub fn rule_check_logged() -> H256 {
        "0x..."
            .parse()
            .unwrap_or_default()
    }

    /// keccak256("EnforcementActionLogged(uint256,uint8,bytes32,string,uint256)")
    pub fn enforcement_action_logged() -> H256 {
        "0x..."
            .parse()
            .unwrap_or_default()
    }

    /// keccak256("OrderChecked(bytes32,uint256,bool,string)")
    pub fn order_checked() -> H256 {
        "0x..."
            .parse()
            .unwrap_or_default()
    }

    /// keccak256("EmergencyPaused(address,uint256)")
    pub fn emergency_paused() -> H256 {
        "0x..."
            .parse()
            .unwrap_or_default()
    }
}

/// Parse a raw log into a TsarEvent.
pub fn parse_event(log: &Log) -> TsarEvent {
    if log.topics.is_empty() {
        return TsarEvent::Unknown {
            topic: "none".into(),
            data: hex::encode(&log.data),
        };
    }

    let topic = log.topics[0];

    // Match against known event topics
    if topic == topics::emergency_paused() {
        TsarEvent::EmergencyPaused {
            by: format!("{:?}", log.topics.get(1).unwrap_or(&H256::zero())),
            timestamp: chrono::Utc::now().timestamp() as u64,
        }
    } else {
        TsarEvent::Unknown {
            topic: format!("{:?}", topic),
            data: hex::encode(&log.data),
        }
    }
}
