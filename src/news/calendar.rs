/// News Calendar Integration
/// Pre-loaded economic & crypto events, regulatory deadlines

use chrono::{DateTime, Utc, NaiveDate, Datelike};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Calendar event
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalendarEvent {
    pub id: String,
    pub name: String,
    pub category: NewsCategory,
    pub severity: NewsSeverity,
    pub date: NaiveDate,
    pub time_utc: Option<String>,  // e.g., "18:00"
    pub affected_assets: Vec<String>,
    pub description: String,
    pub is_recurring: bool,
    pub recurrence: Option<Recurrence>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Recurrence {
    Monthly,
    Quarterly,
    Biannually,
    Annually,
    Custom(String),
}

/// News calendar
pub struct NewsCalendar {
    events: BTreeMap<NaiveDate, Vec<CalendarEvent>>,
}

impl NewsCalendar {
    pub fn new() -> Self {
        let mut calendar = Self {
            events: BTreeMap::new(),
        };
        calendar.load_preloaded_events();
        calendar
    }
    
    /// Load pre-loaded economic events
    fn load_preloaded_events(&mut self) {
        // 2026 Economic Calendar (key dates)
        self.add_fomc_dates();
        self.add_cpi_dates();
        self.add_nfp_dates();
        self.add_crypto_events();
    }
    
    /// FOMC meeting dates 2026
    fn add_fomc_dates(&mut self) {
        let fomc_dates = vec![
            "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
            "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
        ];
        
        for date_str in fomc_dates {
            if let Ok(date) = NaiveDate::parse_from_str(date_str, "%Y-%m-%d") {
                self.add_event(CalendarEvent {
                    id: format!("fomc-{}", date),
                    name: "FOMC Meeting".to_string(),
                    category: NewsCategory::FOMC,
                    severity: NewsSeverity::Critical,
                    date,
                    time_utc: Some("18:00".to_string()),
                    affected_assets: vec!["BTC".to_string(), "ETH".to_string(), "SOL".to_string()],
                    description: "Federal Reserve interest rate decision".to_string(),
                    is_recurring: true,
                    recurrence: Some(Recurrence::Biannually),
                });
            }
        }
    }
    
    /// CPI release dates 2026
    fn add_cpi_dates(&mut self) {
        let cpi_dates = vec![
            "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10",
            "2026-05-13", "2026-06-10", "2026-07-14", "2026-08-12",
            "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
        ];
        
        for date_str in cpi_dates {
            if let Ok(date) = NaiveDate::parse_from_str(date_str, "%Y-%m-%d") {
                self.add_event(CalendarEvent {
                    id: format!("cpi-{}", date),
                    name: "CPI Release".to_string(),
                    category: NewsCategory::CPI,
                    severity: NewsSeverity::Critical,
                    date,
                    time_utc: Some("12:30".to_string()),
                    affected_assets: vec!["BTC".to_string(), "ETH".to_string()],
                    description: "Consumer Price Index inflation data".to_string(),
                    is_recurring: true,
                    recurrence: Some(Recurrence::Monthly),
                });
            }
        }
    }
    
    /// NFP release dates 2026
    fn add_nfp_dates(&mut self) {
        let nfp_dates = vec![
            "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
            "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
            "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
        ];
        
        for date_str in nfp_dates {
            if let Ok(date) = NaiveDate::parse_from_str(date_str, "%Y-%m-%d") {
                self.add_event(CalendarEvent {
                    id: format!("nfp-{}", date),
                    name: "Non-Farm Payrolls".to_string(),
                    category: NewsCategory::NFP,
                    severity: NewsSeverity::Critical,
                    date,
                    time_utc: Some("12:30".to_string()),
                    affected_assets: vec!["BTC".to_string(), "ETH".to_string()],
                    description: "US employment data".to_string(),
                    is_recurring: true,
                    recurrence: Some(Recurrence::Monthly),
                });
            }
        }
    }
    
    /// Crypto-specific events
    fn add_crypto_events(&mut self) {
        // Bitcoin halving (approximate next: 2028)
        self.add_event(CalendarEvent {
            id: "btc-halving-2028".to_string(),
            name: "Bitcoin Halving".to_string(),
            category: NewsCategory::BitcoinHalving,
            severity: NewsSeverity::High,
            date: NaiveDate::from_ymd_opt(2028, 4, 1).unwrap(),
            time_utc: None,
            affected_assets: vec!["BTC".to_string()],
            description: "Bitcoin block reward halving".to_string(),
            is_recurring: true,
            recurrence: Some(Recurrence::Custom("Every ~4 years".to_string())),
        });
        
        // Token unlock example (dynamic, loaded from API)
        // These would be loaded from external data sources
    }
    
    /// Add an event to the calendar
    pub fn add_event(&mut self, event: CalendarEvent) {
        self.events
            .entry(event.date)
            .or_insert_with(Vec::new)
            .push(event);
    }
    
    /// Get events for a specific date
    pub fn get_events(&self, date: NaiveDate) -> Vec<&CalendarEvent> {
        self.events
            .get(&date)
            .map(|events| events.iter().collect())
            .unwrap_or_default()
    }
    
    /// Get upcoming events within N days
    pub fn get_upcoming(&self, from: NaiveDate, days: i64) -> Vec<&CalendarEvent> {
        let end = from + chrono::Duration::days(days);
        self.events
            .range(from..=end)
            .flat_map(|(_, events)| events.iter())
            .collect()
    }
    
    /// Check if date has critical events
    pub fn has_critical_event(&self, date: NaiveDate) -> bool {
        self.events
            .get(&date)
            .map(|events| events.iter().any(|e| e.severity == NewsSeverity::Critical))
            .unwrap_or(false)
    }
    
    /// Load token unlock data (from external API)
    pub fn load_token_unlocks(&mut self, unlocks: Vec<TokenUnlock>) {
        for unlock in unlocks {
            self.add_event(CalendarEvent {
                id: format!("unlock-{}-{}", unlock.token, unlock.date),
                name: format!("{} Token Unlock", unlock.token),
                category: NewsCategory::TokenUnlock,
                severity: NewsSeverity::High,
                date: unlock.date,
                time_utc: None,
                affected_assets: vec![unlock.token],
                description: format!("{} tokens unlocking: ${:.0}M", unlock.token, unlock.value_usd / 1_000_000.0),
                is_recurring: false,
                recurrence: None,
            });
        }
    }
}

/// Token unlock data
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenUnlock {
    pub token: String,
    pub date: NaiveDate,
    pub amount: f64,
    pub value_usd: f64,
    pub percent_of_supply: f64,
}

/// Regulatory deadline tracker
pub struct RegulatoryTracker {
    deadlines: Vec<RegulatoryDeadline>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegulatoryDeadline {
    pub id: String,
    pub name: String,
    pub date: NaiveDate,
    pub description: String,
    pub affected_assets: Vec<String>,
    pub expected_impact: NewsSeverity,
}

impl RegulatoryTracker {
    pub fn new() -> Self {
        let mut tracker = Self {
            deadlines: Vec::new(),
        };
        tracker.load_known_deadlines();
        tracker
    }
    
    fn load_known_deadlines(&mut self) {
        // SEC deadlines, regulatory decisions, etc.
        // These would be loaded from external sources
    }
    
    pub fn add_deadline(&mut self, deadline: RegulatoryDeadline) {
        self.deadlines.push(deadline);
    }
    
    pub fn get_upcoming(&self, from: NaiveDate, days: i64) -> Vec<&RegulatoryDeadline> {
        let end = from + chrono::Duration::days(days);
        self.deadlines
            .iter()
            .filter(|d| d.date >= from && d.date <= end)
            .collect()
    }
}

use super::blackout_periods::{NewsCategory, NewsSeverity};
