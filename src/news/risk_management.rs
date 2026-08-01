/// News-Aware Risk Management
/// Position sizing and stop loss adjustments during news events

use serde::{Deserialize, Serialize};

/// Risk adjustment based on news severity
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewsRiskAdjustment {
    pub position_size_multiplier: f64,  // 0.0 to 1.0
    pub stop_loss_multiplier: f64,      // Tighten stops
    pub max_leverage: f64,              // Reduce leverage
    pub should_flatten: bool,           // Exit all positions
    pub notes: String,
}

/// News risk manager
pub struct NewsRiskManager {
    base_position_size: f64,
    base_stop_loss: f64,
    base_leverage: f64,
}

impl NewsRiskManager {
    pub fn new(base_position_size: f64, base_stop_loss: f64, base_leverage: f64) -> Self {
        Self {
            base_position_size,
            base_stop_loss,
            base_leverage,
        }
    }
    
    /// Get risk adjustment for news severity
    pub fn get_adjustment(&self, severity: &NewsSeverity, in_blackout: bool) -> NewsRiskAdjustment {
        match severity {
            NewsSeverity::Critical => NewsRiskAdjustment {
                position_size_multiplier: 0.0,  // No new trades
                stop_loss_multiplier: 0.5,       // Tighten 50%
                max_leverage: 1.0,               // No leverage
                should_flatten: true,            // Flatten all
                notes: "CRITICAL news — Flatten all positions. No new trades.".to_string(),
            },
            NewsSeverity::High => NewsRiskAdjustment {
                position_size_multiplier: 0.5,  // Reduce 50%
                stop_loss_multiplier: 0.7,       // Tighten 30%
                max_leverage: 2.0,               // Max 2x
                should_flatten: false,
                notes: "HIGH impact news — Reduce size 50%, tighten stops.".to_string(),
            },
            NewsSeverity::Medium => NewsRiskAdjustment {
                position_size_multiplier: 0.75,
                stop_loss_multiplier: 0.85,
                max_leverage: 3.0,
                should_flatten: false,
                notes: "MEDIUM impact — Reduce size 25%, tighten stops slightly.".to_string(),
            },
            NewsSeverity::Low => NewsRiskAdjustment {
                position_size_multiplier: 1.0,
                stop_loss_multiplier: 1.0,
                max_leverage: 5.0,
                should_flatten: false,
                notes: "LOW impact — Normal trading. Monitor.".to_string(),
            },
        }
    }
    
    /// Calculate adjusted position size
    pub fn adjusted_position_size(&self, severity: &NewsSeverity) -> f64 {
        let adj = self.get_adjustment(severity, false);
        self.base_position_size * adj.position_size_multiplier
    }
    
    /// Calculate adjusted stop loss
    pub fn adjusted_stop_loss(&self, severity: &NewsSeverity) -> f64 {
        let adj = self.get_adjustment(severity, false);
        self.base_stop_loss * adj.stop_loss_multiplier
    }
    
    /// Calculate adjusted leverage
    pub fn adjusted_leverage(&self, severity: &NewsSeverity) -> f64 {
        let adj = self.get_adjustment(severity, false);
        self.base_leverage.min(adj.max_leverage)
    }
    
    /// Should we enter a new position?
    pub fn can_enter_position(&self, severity: &NewsSeverity) -> bool {
        let adj = self.get_adjustment(severity, false);
        !adj.should_flatten && adj.position_size_multiplier > 0.0
    }
}

/// Special risk scenarios
pub struct SpecialRiskScenarios;

impl SpecialRiskScenarios {
    /// FUD scenario — don't sell at bottom
    pub fn handle_fud(
        current_price: f64,
        entry_price: f64,
        stop_loss: f64,
    ) -> FudDecision {
        let unrealized_pnl = (current_price - entry_price) / entry_price;
        
        // If we're down significantly and it's FUD
        if unrealized_pnl < -0.15 {
            // Don't sell at bottom — wait for clarity
            FudDecision {
                action: FudAction::HoldAndWait,
                reason: "FUD detected, unrealized loss > 15%. Don't sell at bottom. Wait for clarity.".to_string(),
                wait_hours: 24,
            }
        } else if unrealized_pnl < -0.05 {
            FudDecision {
                action: FudAction::TightenStop,
                reason: "Moderate loss during FUD. Tighten stop but don't panic sell.".to_string(),
                wait_hours: 4,
            }
        } else {
            FudDecision {
                action: FudAction::NormalTrading,
                reason: "Position healthy despite FUD. Continue with plan.".to_string(),
                wait_hours: 0,
            }
        }
    }
    
    /// Uncertainty scenario — tighten stops
    pub fn handle_uncertainty(
        current_volatility: f64,
        normal_volatility: f64,
    ) -> UncertaintyDecision {
        let vol_ratio = current_volatility / normal_volatility;
        
        if vol_ratio > 3.0 {
            UncertaintyDecision {
                action: UncertaintyAction::Flatten,
                reason: "Volatility 3x+ normal. Flatten positions.".to_string(),
            }
        } else if vol_ratio > 2.0 {
            UncertaintyDecision {
                action: UncertaintyAction::ReduceAndTighten,
                reason: "Volatility 2x+ normal. Reduce size and tighten stops.".to_string(),
            }
        } else if vol_ratio > 1.5 {
            UncertaintyDecision {
                action: UncertaintyAction::TightenStops,
                reason: "Elevated volatility. Tighten stops.".to_string(),
            }
        } else {
            UncertaintyDecision {
                action: UncertaintyAction::Normal,
                reason: "Volatility normal. Continue.".to_string(),
            }
        }
    }
}

#[derive(Debug, Clone)]
pub struct FudDecision {
    pub action: FudAction,
    pub reason: String,
    pub wait_hours: i64,
}

#[derive(Debug, Clone)]
pub enum FudAction {
    HoldAndWait,
    TightenStop,
    NormalTrading,
}

#[derive(Debug, Clone)]
pub struct UncertaintyDecision {
    pub action: UncertaintyAction,
    pub reason: String,
}

#[derive(Debug, Clone)]
pub enum UncertaintyAction {
    Flatten,
    ReduceAndTighten,
    TightenStops,
    Normal,
}

use super::blackout_periods::NewsSeverity;
