/// Post-News Recovery Detection
/// Detect when it's safe to resume trading after major news events

use chrono::{DateTime, Utc, Duration};
use serde::{Deserialize, Serialize};

/// Recovery state after news event
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RecoveryState {
    /// News just hit, chaos
    InitialShock,
    /// Price still moving, high volatility
    Volatile,
    /// Price stabilizing, volatility decreasing
    Stabilizing,
    /// Recovery detected, safe to trade
    Recovered,
    /// New trend established
    TrendEstablished,
}

/// Recovery detection configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecoveryConfig {
    /// Volatility threshold to consider "stabilized" (e.g., 0.02 = 2%)
    pub volatility_threshold: f64,
    /// Price retracement required (e.g., 0.5 = 50% of crash)
    pub retracement_required: f64,
    /// Time to wait after regulatory news (hours)
    pub regulatory_digest_hours: i64,
    /// Time to trade momentum after ETF decision (hours)
    pub etf_momentum_hours: i64,
}

impl Default for RecoveryConfig {
    fn default() -> Self {
        Self {
            volatility_threshold: 0.02,    // 2%
            retracement_required: 0.5,     // 50%
            regulatory_digest_hours: 48,   // 48h
            etf_momentum_hours: 24,        // 24h
        }
    }
}

/// Recovery detector
pub struct RecoveryDetector {
    config: RecoveryConfig,
    price_history: Vec<(DateTime<Utc>, f64)>,
    crash_low: Option<f64>,
    crash_high: Option<f64>,
    event_timestamp: Option<DateTime<Utc>>,
    current_state: RecoveryState,
}

impl RecoveryDetector {
    pub fn new(config: RecoveryConfig) -> Self {
        Self {
            config,
            price_history: Vec::new(),
            crash_low: None,
            crash_high: None,
            event_timestamp: None,
            current_state: RecoveryState::InitialShock,
        }
    }
    
    /// Register a news event
    pub fn on_news_event(&mut self, timestamp: DateTime<Utc>, event_type: &str) {
        self.event_timestamp = Some(timestamp);
        self.current_state = RecoveryState::InitialShock;
        self.crash_low = None;
        self.crash_high = None;
        self.price_history.clear();
    }
    
    /// Update with new price data
    pub fn update_price(&mut self, timestamp: DateTime<Utc>, price: f64) {
        self.price_history.push((timestamp, price));
        
        // Track crash low/high
        match self.crash_low {
            None => self.crash_low = Some(price),
            Some(low) => {
                if price < low {
                    self.crash_low = Some(price);
                }
            }
        }
        
        match self.crash_high {
            None => self.crash_high = Some(price),
            Some(high) => {
                if price > high {
                    self.crash_high = Some(high);
                }
            }
        }
        
        self.evaluate_state();
    }
    
    /// Evaluate current recovery state
    fn evaluate_state(&mut self) {
        if self.price_history.len() < 10 {
            return;
        }
        
        let volatility = self.calculate_volatility();
        let retracement = self.calculate_retracement();
        
        match self.current_state {
            RecoveryState::InitialShock => {
                if volatility < self.config.volatility_threshold * 2.0 {
                    self.current_state = RecoveryState::Volatile;
                }
            }
            RecoveryState::Volatile => {
                if volatility < self.config.volatility_threshold {
                    self.current_state = RecoveryState::Stabilizing;
                }
            }
            RecoveryState::Stabilizing => {
                if retracement >= self.config.retracement_required {
                    self.current_state = RecoveryState::Recovered;
                }
            }
            RecoveryState::Recovered => {
                if self.is_trend_established() {
                    self.current_state = RecoveryState::TrendEstablished;
                }
            }
            _ => {}
        }
    }
    
    /// Calculate recent volatility
    fn calculate_volatility(&self) -> f64 {
        let recent: Vec<f64> = self.price_history
            .iter()
            .rev()
            .take(20)
            .map(|(_, p)| *p)
            .collect();
        
        if recent.len() < 2 {
            return 1.0; // High volatility if insufficient data
        }
        
        let returns: Vec<f64> = recent.windows(2)
            .map(|w| (w[0] - w[1]).abs() / w[1])
            .collect();
        
        returns.iter().sum::<f64>() / returns.len() as f64
    }
    
    /// Calculate price retracement from crash
    fn calculate_retracement(&self) -> f64 {
        let (low, high) = match (self.crash_low, self.crash_high) {
            (Some(l), Some(h)) => (l, h),
            _ => return 0.0,
        };
        
        let current = self.price_history.last().map(|(_, p)| *p).unwrap_or(low);
        
        if high == low {
            return 1.0;
        }
        
        (current - low) / (high - low)
    }
    
    /// Check if a new trend is established
    fn is_trend_established(&self) -> bool {
        if self.price_history.len() < 50 {
            return false;
        }
        
        let recent_20: Vec<f64> = self.price_history
            .iter()
            .rev()
            .take(20)
            .map(|(_, p)| *p)
            .collect();
        
        let older_20: Vec<f64> = self.price_history
            .iter()
            .rev()
            .skip(20)
            .take(20)
            .map(|(_, p)| *p)
            .collect();
        
        let recent_avg = recent_20.iter().sum::<f64>() / recent_20.len() as f64;
        let older_avg = older_20.iter().sum::<f64>() / older_20.len() as f64;
        
        // 5% difference indicates trend
        (recent_avg - older_avg).abs() / older_avg > 0.05
    }
    
    /// Get current recovery state
    pub fn get_state(&self) -> &RecoveryState {
        &self.current_state
    }
    
    /// Check if safe to resume trading
    pub fn is_safe_to_trade(&self) -> bool {
        matches!(
            self.current_state,
            RecoveryState::Recovered | RecoveryState::TrendEstablished
        )
    }
    
    /// Get recommended action
    pub fn get_recommendation(&self) -> String {
        match self.current_state {
            RecoveryState::InitialShock => "DO NOT TRADE — Market in chaos. Wait.".to_string(),
            RecoveryState::Volatile => "HIGH RISK — Volatility elevated. Reduce size if trading.".to_string(),
            RecoveryState::Stabilizing => "CAUTION — Price stabilizing. Small positions only.".to_string(),
            RecoveryState::Recovered => "READY — Recovery detected. Resume normal trading.".to_string(),
            RecoveryState::TrendEstablished => "OPPORTUNITY — New trend established. Trade the trend.".to_string(),
        }
    }
}

/// Specialized recovery detectors for different event types
pub struct FlashCrashRecovery {
    detector: RecoveryDetector,
}

impl FlashCrashRecovery {
    pub fn new() -> Self {
        Self {
            detector: RecoveryDetector::new(RecoveryConfig {
                volatility_threshold: 0.03,  // 3% — higher tolerance for flash crashes
                retracement_required: 0.5,   // 50% retracement required
                regulatory_digest_hours: 0,
                etf_momentum_hours: 0,
            }),
        }
    }
    
    /// Wait for price to retrace 50%+ of crash
    pub fn wait_for_recovery(&mut self, prices: &[(DateTime<Utc>, f64)]) -> bool {
        for (ts, price) in prices {
            self.detector.update_price(*ts, *price);
        }
        self.detector.is_safe_to_trade()
    }
}

pub struct RegulatoryRecovery {
    detector: RecoveryDetector,
    event_time: Option<DateTime<Utc>>,
}

impl RegulatoryRecovery {
    pub fn new() -> Self {
        Self {
            detector: RecoveryDetector::new(RecoveryConfig {
                volatility_threshold: 0.015,
                retracement_required: 0.3,
                regulatory_digest_hours: 48,
                etf_momentum_hours: 0,
            }),
            event_time: None,
        }
    }
    
    /// Wait 24-48h for market to digest regulatory news
    pub fn wait_for_digest(&mut self, now: DateTime<Utc>) -> bool {
        match self.event_time {
            Some(event) => {
                let elapsed = now - event;
                elapsed > Duration::hours(48)
            }
            None => false,
        }
    }
}

pub struct ETFDecisionHandler {
    momentum_window: Duration,
}

impl ETFDecisionHandler {
    pub fn new() -> Self {
        Self {
            momentum_window: Duration::hours(24),
        }
    }
    
    /// Trade momentum in first 24h after ETF decision
    pub fn should_trade_momentum(&self, decision_time: DateTime<Utc>, now: DateTime<Utc>) -> bool {
        now - decision_time < self.momentum_window
    }
}
