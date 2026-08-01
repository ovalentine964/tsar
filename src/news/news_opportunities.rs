/// News-Driven Trading Opportunities
/// Institutional-grade opportunity detection from news events

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Opportunity type
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum OpportunityType {
    /// ETF approval → Buy BTC immediately
    ETFApproval,
    /// Major partnership → Buy token (verify first)
    Partnership,
    /// Protocol upgrade → Buy before, sell after
    ProtocolUpgrade,
    /// Whale accumulation → Follow smart money
    WhaleAccumulation,
    /// Extreme fear → Contrarian buy
    ContrarianBuy,
    /// Regulatory clarity → Long-term position
    RegulatoryClarity,
    /// Exchange hack → Short affected, long competitors
    ExchangeHack,
    /// Liquidation cascade → Buy the dip
    LiquidationCascade,
}

/// Opportunity signal
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OpportunitySignal {
    pub opportunity_type: OpportunityType,
    pub asset: String,
    pub confidence: f64,        // 0.0 to 1.0
    pub urgency: Urgency,
    pub entry_window: chrono::Duration,
    pub expected_move: f64,     // Expected % move
    pub risk_level: RiskLevel,
    pub position_size: f64,     // Recommended % of portfolio
    pub stop_loss: f64,         // Stop loss %
    pub take_profit: f64,       // Take profit %
    pub notes: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Urgency {
    Immediate,   // Act within minutes
    Short,       // Act within 1-4 hours
    Medium,      // Act within 24 hours
    Long,        // Act within 1 week
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum RiskLevel {
    Low,
    Medium,
    High,
    Extreme,
}

/// News opportunity detector
pub struct OpportunityDetector {
    fear_greed_threshold_low: u8,
    fear_greed_threshold_high: u8,
}

impl OpportunityDetector {
    pub fn new() -> Self {
        Self {
            fear_greed_threshold_low: 20,   // Extreme fear
            fear_greed_threshold_high: 80,  // Extreme greed
        }
    }
    
    /// Detect opportunities from news event
    pub fn detect(&self, event: &NewsEvent) -> Vec<OpportunitySignal> {
        let mut signals = Vec::new();
        
        match event.category {
            NewsCategory::ETFDecision => {
                signals.push(self.etf_opportunity(event));
            }
            NewsCategory::ExtremeFear => {
                signals.push(self.contrarian_opportunity(event));
            }
            NewsCategory::ExtremeGreed => {
                signals.push(self.greed_warning(event));
            }
            NewsCategory::WhaleMovement => {
                signals.push(self.whale_opportunity(event));
            }
            NewsCategory::ProtocolUpgrade => {
                signals.push(self.upgrade_opportunity(event));
            }
            NewsCategory::FlashCrash => {
                signals.push(self.flash_crash_opportunity(event));
            }
            NewsCategory::LiquidationCascade => {
                signals.push(self.liquidation_opportunity(event));
            }
            NewsCategory::ExchangeHack => {
                signals.push(self.exchange_hack_opportunity(event));
            }
            _ => {}
        }
        
        signals.into_iter().filter(|s| s.confidence > 0.5).collect()
    }
    
    /// ETF approval opportunity
    fn etf_opportunity(&self, event: &NewsEvent) -> OpportunitySignal {
        OpportunitySignal {
            opportunity_type: OpportunityType::ETFApproval,
            asset: "BTC".to_string(),
            confidence: 0.9,
            urgency: Urgency::Immediate,
            entry_window: chrono::Duration::hours(24),
            expected_move: 0.15,  // 15%
            risk_level: RiskLevel::Medium,
            position_size: 0.05,  // 5% of portfolio
            stop_loss: 0.05,      // 5% stop
            take_profit: 0.15,    // 15% target
            notes: "ETF approval → Immediate BTC momentum. Trade first 24h.".to_string(),
        }
    }
    
    /// Contrarian buy at extreme fear
    fn contrarian_opportunity(&self, event: &NewsEvent) -> OpportunitySignal {
        OpportunitySignal {
            opportunity_type: OpportunityType::ContrarianBuy,
            asset: event.affected_assets.first().cloned().unwrap_or("BTC".to_string()),
            confidence: 0.7,
            urgency: Urgency::Short,
            entry_window: chrono::Duration::hours(4),
            expected_move: 0.10,
            risk_level: RiskLevel::Medium,
            position_size: 0.03,
            stop_loss: 0.07,
            take_profit: 0.15,
            notes: "Fear & Greed < 20 → Contrarian buy. Be patient, scale in.".to_string(),
        }
    }
    
    /// Greed warning
    fn greed_warning(&self, event: &NewsEvent) -> OpportunitySignal {
        OpportunitySignal {
            opportunity_type: OpportunityType::ContrarianBuy,
            asset: event.affected_assets.first().cloned().unwrap_or("BTC".to_string()),
            confidence: 0.75,
            urgency: Urgency::Short,
            entry_window: chrono::Duration::hours(4),
            expected_move: -0.10,
            risk_level: RiskLevel::High,
            position_size: 0.0,
            stop_loss: 0.0,
            take_profit: 0.0,
            notes: "Fear & Greed > 80 → Reduce exposure. Consider shorts.".to_string(),
        }
    }
    
    /// Whale accumulation signal
    fn whale_opportunity(&self, event: &NewsEvent) -> OpportunitySignal {
        OpportunitySignal {
            opportunity_type: OpportunityType::WhaleAccumulation,
            asset: event.affected_assets.first().cloned().unwrap_or("BTC".to_string()),
            confidence: 0.65,
            urgency: Urgency::Medium,
            entry_window: chrono::Duration::hours(24),
            expected_move: 0.08,
            risk_level: RiskLevel::Medium,
            position_size: 0.02,
            stop_loss: 0.05,
            take_profit: 0.10,
            notes: "Whale accumulation detected → Follow smart money with caution.".to_string(),
        }
    }
    
    /// Protocol upgrade opportunity
    fn upgrade_opportunity(&self, event: &NewsEvent) -> OpportunitySignal {
        OpportunitySignal {
            opportunity_type: OpportunityType::ProtocolUpgrade,
            asset: event.affected_assets.first().cloned().unwrap_or("ETH".to_string()),
            confidence: 0.7,
            urgency: Urgency::Medium,
            entry_window: chrono::Duration::days(7),
            expected_move: 0.10,
            risk_level: RiskLevel::Medium,
            position_size: 0.03,
            stop_loss: 0.05,
            take_profit: 0.12,
            notes: "Protocol upgrade → Buy before, sell after. Historical pattern.".to_string(),
        }
    }
    
    /// Flash crash opportunity (buy the dip)
    fn flash_crash_opportunity(&self, event: &NewsEvent) -> OpportunitySignal {
        OpportunitySignal {
            opportunity_type: OpportunityType::LiquidationCascade,
            asset: event.affected_assets.first().cloned().unwrap_or("BTC".to_string()),
            confidence: 0.8,
            urgency: Urgency::Immediate,
            entry_window: chrono::Duration::hours(1),
            expected_move: 0.10,
            risk_level: RiskLevel::High,
            position_size: 0.02,  // Small position
            stop_loss: 0.03,      // Tight stop
            take_profit: 0.10,
            notes: "Flash crash → Wait for stabilization, then buy the dip.".to_string(),
        }
    }
    
    /// Liquidation cascade opportunity
    fn liquidation_opportunity(&self, event: &NewsEvent) -> OpportunitySignal {
        OpportunitySignal {
            opportunity_type: OpportunityType::LiquidationCascade,
            asset: event.affected_assets.first().cloned().unwrap_or("BTC".to_string()),
            confidence: 0.75,
            urgency: Urgency::Short,
            entry_window: chrono::Duration::hours(2),
            expected_move: 0.08,
            risk_level: RiskLevel::High,
            position_size: 0.02,
            stop_loss: 0.04,
            take_profit: 0.08,
            notes: "Liquidation cascade → Wait for dust, then buy recovery.".to_string(),
        }
    }
    
    /// Exchange hack opportunity
    fn exchange_hack_opportunity(&self, event: &NewsEvent) -> OpportunitySignal {
        OpportunitySignal {
            opportunity_type: OpportunityType::ExchangeHack,
            asset: event.affected_assets.first().cloned().unwrap_or("BTC".to_string()),
            confidence: 0.6,
            urgency: Urgency::Short,
            entry_window: chrono::Duration::hours(4),
            expected_move: -0.05,
            risk_level: RiskLevel::High,
            position_size: 0.0,
            stop_loss: 0.0,
            take_profit: 0.0,
            notes: "Exchange hack → Avoid affected exchange. Consider self-custody.".to_string(),
        }
    }
}

use super::blackout_periods::{NewsCategory, NewsEvent};
