//! Configuration structures for the TSAR trading system.
//!
//! These structures map to the YAML configuration files used by TSAR.
//! They are deserialized via `serde` and exposed to Python via PyO3.

use serde::{Deserialize, Serialize};

/// Top-level TSAR configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TsarConfig {
    pub app: AppConfig,
    pub exchanges: ExchangesConfig,
    pub engine: EngineConfig,
    pub risk: RiskConfig,
}

/// Application-level settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub name: String,
    pub version: String,
    pub environment: String,
    pub debug: bool,
    pub timezone: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            name: "tsar".to_string(),
            version: "0.1.0".to_string(),
            environment: "development".to_string(),
            debug: true,
            timezone: "UTC".to_string(),
        }
    }
}

/// Exchange configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExchangesConfig {
    pub default: String,
    pub testnet: bool,
    pub rate_limit: u32,
}

impl Default for ExchangesConfig {
    fn default() -> Self {
        Self {
            default: "binance".to_string(),
            testnet: true,
            rate_limit: 1200,
        }
    }
}

/// Trading engine settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineConfig {
    pub mode: String,
    pub symbols: Vec<String>,
    pub timeframes: Vec<String>,
    pub max_open_positions: u32,
    pub order_timeout: u64,
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            mode: "paper".to_string(),
            symbols: vec!["BTC/USDT".to_string()],
            timeframes: vec![
                "1m".to_string(),
                "5m".to_string(),
                "15m".to_string(),
                "1h".to_string(),
            ],
            max_open_positions: 3,
            order_timeout: 30,
        }
    }
}

/// Risk management configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskConfig {
    pub max_position_size_pct: f64,
    pub max_daily_drawdown_pct: f64,
    pub max_total_drawdown_pct: f64,
    pub max_portfolio_exposure_pct: f64,
    pub max_correlation: f64,
    pub emergency_stop_loss_pct: f64,
    pub min_risk_reward_ratio: f64,
}

impl Default for RiskConfig {
    fn default() -> Self {
        Self {
            max_position_size_pct: 5.0,
            max_daily_drawdown_pct: 2.0,
            max_total_drawdown_pct: 10.0,
            max_portfolio_exposure_pct: 80.0,
            max_correlation: 0.7,
            emergency_stop_loss_pct: 5.0,
            min_risk_reward_ratio: 2.0,
        }
    }
}

impl TsarConfig {
    /// Load configuration from a JSON string (stub — returns defaults).
    pub fn from_json(_json: &str) -> Result<Self, serde_json::Error> {
        // Stub: return defaults. Real implementation will parse YAML/JSON.
        Ok(Self::default())
    }
}

impl Default for TsarConfig {
    fn default() -> Self {
        Self {
            app: AppConfig::default(),
            exchanges: ExchangesConfig::default(),
            engine: EngineConfig::default(),
            risk: RiskConfig::default(),
        }
    }
}
