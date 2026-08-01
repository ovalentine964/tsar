/// Pre-News & Post-News Blackout Periods
/// Institutional-grade news-aware execution

use chrono::{DateTime, Utc, Duration};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// News event severity levels
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum NewsSeverity {
    /// Market-moving, require full blackout
    Critical,
    /// Significant impact, reduce exposure
    High,
    /// Moderate impact, tighten stops
    Medium,
    /// Low impact, monitor only
    Low,
}

/// News event types
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum NewsCategory {
    // Macroeconomic
    FOMC,
    CPI,
    NFP,
    GDP,
    Unemployment,
    RetailSales,
    
    // Crypto-specific
    BitcoinHalving,
    TokenUnlock,
    ETFDecision,
    ProtocolUpgrade,
    WhaleMovement,
    
    // Regulatory
    SECDecision,
    RegulatoryAnnouncement,
    LegalRuling,
    
    // Market events
    FlashCrash,
    LiquidationCascade,
    ExchangeHack,
    
    // Sentiment
    ExtremeFear,
    ExtremeGreed,
}

/// A scheduled or detected news event
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewsEvent {
    pub id: String,
    pub category: NewsCategory,
    pub severity: NewsSeverity,
    pub timestamp: DateTime<Utc>,
    pub description: String,
    pub affected_assets: Vec<String>,
    pub blackout_before: Duration,
    pub blackout_after: Duration,
    pub is_active: bool,
}

/// Blackout period configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BlackoutConfig {
    pub category: NewsCategory,
    pub severity: NewsSeverity,
    pub before_minutes: i64,
    pub after_minutes: i64,
    pub action: BlackoutAction,
}

/// What to do during a blackout
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum BlackoutAction {
    /// No new trades, hold existing
    NoNewTrades,
    /// Flatten all positions
    FlattenAll,
    /// Reduce position size by percentage
    ReduceSize(u8),
    /// Tighten stop losses
    TightenStops(f64),
    /// Increase position (opportunity)
    IncreasePosition(f64),
    /// Monitor only
    MonitorOnly,
}

/// Blackout period manager
pub struct BlackoutManager {
    config: HashMap<NewsCategory, BlackoutConfig>,
    active_events: Vec<NewsEvent>,
}

impl BlackoutManager {
    pub fn new() -> Self {
        let mut config = HashMap::new();
        
        // FOMC: 2h before, 2h after — NO new trades
        config.insert(NewsCategory::FOMC, BlackoutConfig {
            category: NewsCategory::FOMC,
            severity: NewsSeverity::Critical,
            before_minutes: 120,
            after_minutes: 120,
            action: BlackoutAction::NoNewTrades,
        });
        
        // CPI: 1h before, 1h after — NO new trades
        config.insert(NewsCategory::CPI, BlackoutConfig {
            category: NewsCategory::CPI,
            severity: NewsSeverity::Critical,
            before_minutes: 60,
            after_minutes: 60,
            action: BlackoutAction::NoNewTrades,
        });
        
        // NFP: 30min before, 1h after — NO new trades
        config.insert(NewsCategory::NFP, BlackoutConfig {
            category: NewsCategory::NFP,
            severity: NewsSeverity::Critical,
            before_minutes: 30,
            after_minutes: 60,
            action: BlackoutAction::NoNewTrades,
        });
        
        // Bitcoin Halving: Increase BEFORE, ride momentum AFTER
        config.insert(NewsCategory::BitcoinHalving, BlackoutConfig {
            category: NewsCategory::BitcoinHalving,
            severity: NewsSeverity::High,
            before_minutes: 1440, // 24h before
            after_minutes: 4320, // 72h after
            action: BlackoutAction::IncreasePosition(0.5), // 50% increase
        });
        
        // Token Unlock: AVOID 24h before and after
        config.insert(NewsCategory::TokenUnlock, BlackoutConfig {
            category: NewsCategory::TokenUnlock,
            severity: NewsSeverity::High,
            before_minutes: 1440, // 24h
            after_minutes: 1440, // 24h
            action: BlackoutAction::FlattenAll,
        });
        
        // ETF Decision: Trade momentum first 24h
        config.insert(NewsCategory::ETFDecision, BlackoutConfig {
            category: NewsCategory::ETFDecision,
            severity: NewsSeverity::Critical,
            before_minutes: 60,
            after_minutes: 1440, // 24h
            action: BlackoutAction::IncreasePosition(0.3),
        });
        
        // Flash Crash: Flatten immediately
        config.insert(NewsCategory::FlashCrash, BlackoutConfig {
            category: NewsCategory::FlashCrash,
            severity: NewsSeverity::Critical,
            before_minutes: 0,
            after_minutes: 120,
            action: BlackoutAction::FlattenAll,
        });
        
        // Extreme Fear: Contrarian buy opportunity
        config.insert(NewsCategory::ExtremeFear, BlackoutConfig {
            category: NewsCategory::ExtremeFear,
            severity: NewsSeverity::High,
            before_minutes: 0,
            after_minutes: 240, // 4h
            action: BlackoutAction::IncreasePosition(0.2),
        });
        
        // Extreme Greed: Reduce exposure
        config.insert(NewsCategory::ExtremeGreed, BlackoutConfig {
            category: NewsCategory::ExtremeGreed,
            severity: NewsSeverity::High,
            before_minutes: 0,
            after_minutes: 240,
            action: BlackoutAction::ReduceSize(50),
        });
        
        Self {
            config,
            active_events: Vec::new(),
        }
    }
    
    /// Check if we're currently in a blackout period
    pub fn is_in_blackout(&self, now: DateTime<Utc>) -> Option<&NewsEvent> {
        for event in &self.active_events {
            if !event.is_active {
                continue;
            }
            
            let blackout_start = event.timestamp - event.blackout_before;
            let blackout_end = event.timestamp + event.blackout_after;
            
            if now >= blackout_start && now <= blackout_end {
                return Some(event);
            }
        }
        None
    }
    
    /// Get the action to take during blackout
    pub fn get_blackout_action(&self, event: &NewsEvent) -> &BlackoutAction {
        self.config
            .get(&event.category)
            .map(|c| &c.action)
            .unwrap_or(&BlackoutAction::MonitorOnly)
    }
    
    /// Add a new event
    pub fn add_event(&mut self, event: NewsEvent) {
        self.active_events.push(event);
    }
    
    /// Clean up expired events
    pub fn cleanup_expired(&mut self, now: DateTime<Utc>) {
        self.active_events.retain(|e| {
            let end = e.timestamp + e.blackout_after + Duration::hours(1);
            now < end
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_fomc_blackout() {
        let mut manager = BlackoutManager::new();
        let now = Utc::now();
        
        manager.add_event(NewsEvent {
            id: "fomc-2026-08".to_string(),
            category: NewsCategory::FOMC,
            severity: NewsSeverity::Critical,
            timestamp: now + Duration::hours(1), // 1h from now
            description: "FOMC Meeting".to_string(),
            affected_assets: vec!["BTC".to_string(), "ETH".to_string()],
            blackout_before: Duration::hours(2),
            blackout_after: Duration::hours(2),
            is_active: true,
        });
        
        // Should be in blackout (1h before event)
        assert!(manager.is_in_blackout(now).is_some());
    }
}
