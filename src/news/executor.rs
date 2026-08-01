/// News-Aware Execution Engine
/// Orchestrates blackout periods, recovery detection, and opportunity execution

use chrono::{DateTime, Utc, Duration};
use serde::{Deserialize, Serialize};

/// Execution state
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ExecutionState {
    /// Normal trading
    Normal,
    /// In blackout period
    Blackout(BlackoutInfo),
    /// Waiting for recovery
    WaitingRecovery,
    /// Opportunity detected
    Opportunity(OpportunityInfo),
    /// Risk reduction mode
    RiskReduction,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BlackoutInfo {
    pub event: String,
    pub severity: NewsSeverity,
    pub ends_at: DateTime<Utc>,
    pub action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OpportunityInfo {
    pub opportunity_type: String,
    pub asset: String,
    pub confidence: f64,
    pub urgency: String,
}

/// Execution decision
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionDecision {
    pub action: TradeAction,
    pub position_size: f64,
    pub stop_loss: f64,
    pub take_profit: f64,
    pub leverage: f64,
    pub reason: String,
    pub state: ExecutionState,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum TradeAction {
    /// Enter new position
    Enter { side: Side, size: f64 },
    /// Exit existing position
    Exit { reason: String },
    /// Reduce position
    Reduce { percent: f64 },
    /// Hold current position
    Hold,
    /// Do nothing
    NoAction,
    /// Flatten all positions
    FlattenAll,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Side {
    Long,
    Short,
}

/// News-aware execution engine
pub struct NewsAwareExecutor {
    blackout_manager: BlackoutManager,
    recovery_detector: RecoveryDetector,
    opportunity_detector: OpportunityDetector,
    risk_manager: NewsRiskManager,
    calendar: NewsCalendar,
    current_state: ExecutionState,
}

impl NewsAwareExecutor {
    pub fn new(
        base_position_size: f64,
        base_stop_loss: f64,
        base_leverage: f64,
    ) -> Self {
        Self {
            blackout_manager: BlackoutManager::new(),
            recovery_detector: RecoveryDetector::new(RecoveryConfig::default()),
            opportunity_detector: OpportunityDetector::new(),
            risk_manager: NewsRiskManager::new(base_position_size, base_stop_loss, base_leverage),
            calendar: NewsCalendar::new(),
            current_state: ExecutionState::Normal,
        }
    }
    
    /// Process a tick — main execution loop
    pub fn tick(
        &mut self,
        now: DateTime<Utc>,
        current_price: f64,
        current_volatility: f64,
        fear_greed: u8,
    ) -> ExecutionDecision {
        // 1. Check blackout periods
        if let Some(event) = self.blackout_manager.is_in_blackout(now) {
            let action = self.blackout_manager.get_blackout_action(event);
            self.current_state = ExecutionState::Blackout(BlackoutInfo {
                event: format!("{:?}", event.category),
                severity: event.severity,
                ends_at: event.timestamp + event.blackout_after,
                action: format!("{:?}", action),
            });
            
            return self.blackout_decision(event, action);
        }
        
        // 2. Check recovery state
        if !self.recovery_detector.is_safe_to_trade() {
            self.current_state = ExecutionState::WaitingRecovery;
            return ExecutionDecision {
                action: TradeAction::NoAction,
                position_size: 0.0,
                stop_loss: 0.0,
                take_profit: 0.0,
                leverage: 1.0,
                reason: self.recovery_detector.get_recommendation(),
                state: self.current_state.clone(),
            };
        }
        
        // 3. Check for opportunities
        // (Opportunities are detected externally and passed in)
        
        // 4. Normal execution
        self.current_state = ExecutionState::Normal;
        ExecutionDecision {
            action: TradeAction::Hold,
            position_size: self.risk_manager.adjusted_position_size(&NewsSeverity::Low),
            stop_loss: self.risk_manager.adjusted_stop_loss(&NewsSeverity::Low),
            take_profit: 0.0,
            leverage: self.risk_manager.adjusted_leverage(&NewsSeverity::Low),
            reason: "Normal trading conditions.".to_string(),
            state: self.current_state.clone(),
        }
    }
    
    /// Generate decision during blackout
    fn blackout_decision(&self, event: &NewsEvent, action: &BlackoutAction) -> ExecutionDecision {
        match action {
            BlackoutAction::NoNewTrades => ExecutionDecision {
                action: TradeAction::Hold,
                position_size: 0.0,
                stop_loss: self.risk_manager.adjusted_stop_loss(&event.severity),
                take_profit: 0.0,
                leverage: 1.0,
                reason: format!("BLACKOUT: {:?} — No new trades.", event.category),
                state: self.current_state.clone(),
            },
            BlackoutAction::FlattenAll => ExecutionDecision {
                action: TradeAction::FlattenAll,
                position_size: 0.0,
                stop_loss: 0.0,
                take_profit: 0.0,
                leverage: 1.0,
                reason: format!("BLACKOUT: {:?} — Flatten all positions.", event.category),
                state: self.current_state.clone(),
            },
            BlackoutAction::ReduceSize(pct) => ExecutionDecision {
                action: TradeAction::Reduce { percent: *pct as f64 / 100.0 },
                position_size: self.risk_manager.adjusted_position_size(&event.severity),
                stop_loss: self.risk_manager.adjusted_stop_loss(&event.severity),
                take_profit: 0.0,
                leverage: self.risk_manager.adjusted_leverage(&event.severity),
                reason: format!("BLACKOUT: {:?} — Reduce size {}%.", event.category, pct),
                state: self.current_state.clone(),
            },
            BlackoutAction::IncreasePosition(pct) => ExecutionDecision {
                action: TradeAction::Enter {
                    side: Side::Long,
                    size: self.risk_manager.adjusted_position_size(&event.severity) * (1.0 + pct),
                },
                position_size: self.risk_manager.adjusted_position_size(&event.severity) * (1.0 + pct),
                stop_loss: self.risk_manager.adjusted_stop_loss(&event.severity),
                take_profit: 0.15,
                leverage: self.risk_manager.adjusted_leverage(&event.severity),
                reason: format!("OPPORTUNITY: {:?} — Increase position.", event.category),
                state: self.current_state.clone(),
            },
            BlackoutAction::TightenStops(multiplier) => ExecutionDecision {
                action: TradeAction::Hold,
                position_size: self.risk_manager.adjusted_position_size(&event.severity),
                stop_loss: self.risk_manager.adjusted_stop_loss(&event.severity) * multiplier,
                take_profit: 0.0,
                leverage: self.risk_manager.adjusted_leverage(&event.severity),
                reason: format!("BLACKOUT: {:?} — Tighten stops.", event.category),
                state: self.current_state.clone(),
            },
            BlackoutAction::MonitorOnly => ExecutionDecision {
                action: TradeAction::NoAction,
                position_size: 0.0,
                stop_loss: 0.0,
                take_profit: 0.0,
                leverage: 1.0,
                reason: format!("MONITOR: {:?} — Watch only.", event.category),
                state: self.current_state.clone(),
            },
        }
    }
    
    /// Process a news event
    pub fn on_news_event(&mut self, event: NewsEvent) {
        self.blackout_manager.add_event(event.clone());
        self.recovery_detector.on_news_event(event.timestamp, &format!("{:?}", event.category));
    }
    
    /// Update with new price data
    pub fn update_price(&mut self, timestamp: DateTime<Utc>, price: f64) {
        self.recovery_detector.update_price(timestamp, price);
    }
    
    /// Get current state
    pub fn get_state(&self) -> &ExecutionState {
        &self.current_state
    }
    
    /// Get upcoming events
    pub fn get_upcoming_events(&self, days: i64) -> Vec<&CalendarEvent> {
        self.calendar.get_upcoming(Utc::now().date_naive(), days)
    }
}

use super::blackout_periods::{BlackoutAction, BlackoutManager, NewsCategory, NewsEvent, NewsSeverity};
use super::calendar::{CalendarEvent, NewsCalendar};
use super::news_opportunities::OpportunityDetector;
use super::recovery_detection::{RecoveryConfig, RecoveryDetector};
use super::risk_management::NewsRiskManager;
