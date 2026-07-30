//! Tick-level VWAP (Volume-Weighted Average Price) calculator.
//!
//! Maintains a running VWAP from raw trade ticks, tracking
//! cumulative price×volume and volume for accurate computation.
//! Supports both session VWAP and time-windowed VWAP.

use chrono::{DateTime, Utc};
use tsar_core::types::Tick;

/// Running VWAP calculator for a single symbol.
///
/// Accumulates `price × volume` and `volume` to compute VWAP
/// in O(1) per tick. Supports session reset and time-windowed mode.
#[derive(Debug, Clone)]
pub struct VwapCalculator {
    /// Symbol being tracked.
    pub symbol: String,
    /// Cumulative price × volume.
    cumulative_pv: f64,
    /// Cumulative volume.
    cumulative_volume: f64,
    /// Number of ticks processed.
    tick_count: u64,
    /// Session start time (for session VWAP).
    session_start: Option<DateTime<Utc>>,
    /// Current VWAP value (cached).
    current_vwap: f64,
    /// Rolling window of ticks for time-windowed VWAP.
    window: Vec<TickWindowEntry>,
    /// Maximum window duration in seconds (0 = no window limit).
    window_secs: i64,
}

/// Compact entry for the rolling window.
#[derive(Debug, Clone)]
struct TickWindowEntry {
    pv: f64,
    volume: f64,
    timestamp: DateTime<Utc>,
}

impl VwapCalculator {
    /// Create a new VWAP calculator for a symbol.
    pub fn new(symbol: impl Into<String>) -> Self {
        Self {
            symbol: symbol.into(),
            cumulative_pv: 0.0,
            cumulative_volume: 0.0,
            tick_count: 0,
            session_start: None,
            current_vwap: 0.0,
            window: Vec::new(),
            window_secs: 0,
        }
    }

    /// Create a time-windowed VWAP calculator.
    ///
    /// The `window_secs` parameter defines how many seconds of
    /// ticks to include. Older ticks are evicted automatically.
    pub fn with_window(symbol: impl Into<String>, window_secs: i64) -> Self {
        Self {
            symbol: symbol.into(),
            cumulative_pv: 0.0,
            cumulative_volume: 0.0,
            tick_count: 0,
            session_start: None,
            current_vwap: 0.0,
            window: Vec::new(),
            window_secs,
        }
    }

    /// Feed a tick into the VWAP calculator.
    ///
    /// Returns the updated VWAP value.
    pub fn on_tick(&mut self, tick: &Tick) -> f64 {
        let pv = tick.price * tick.amount;

        self.cumulative_pv += pv;
        self.cumulative_volume += tick.amount;
        self.tick_count += 1;

        if self.session_start.is_none() {
            self.session_start = Some(tick.timestamp);
        }

        // If using a time window, store and evict old entries
        if self.window_secs > 0 {
            self.window.push(TickWindowEntry {
                pv,
                volume: tick.amount,
                timestamp: tick.timestamp,
            });
            self.evict_old_entries();
            // Recompute from window
            self.cumulative_pv = self.window.iter().map(|e| e.pv).sum();
            self.cumulative_volume = self.window.iter().map(|e| e.volume).sum();
        }

        self.current_vwap = if self.cumulative_volume > 0.0 {
            self.cumulative_pv / self.cumulative_volume
        } else {
            0.0
        };

        self.current_vwap
    }

    /// Get the current VWAP value.
    pub fn vwap(&self) -> f64 {
        self.current_vwap
    }

    /// Get the total volume accumulated.
    pub fn total_volume(&self) -> f64 {
        self.cumulative_volume
    }

    /// Get the number of ticks processed.
    pub fn tick_count(&self) -> u64 {
        self.tick_count
    }

    /// Reset the calculator for a new session.
    pub fn reset(&mut self) {
        self.cumulative_pv = 0.0;
        self.cumulative_volume = 0.0;
        self.tick_count = 0;
        self.session_start = None;
        self.current_vwap = 0.0;
        self.window.clear();
    }

    /// Get the session start time.
    pub fn session_start(&self) -> Option<DateTime<Utc>> {
        self.session_start
    }

    /// Evict entries older than the window duration.
    fn evict_old_entries(&mut self) {
        if self.window.is_empty() || self.window_secs == 0 {
            return;
        }

        let cutoff = self
            .window
            .last()
            .map(|e| e.timestamp - chrono::Duration::seconds(self.window_secs))
            .unwrap();

        // Find the first entry to keep
        let keep_from = self
            .window
            .iter()
            .position(|e| e.timestamp >= cutoff)
            .unwrap_or(self.window.len());

        if keep_from > 0 {
            self.window.drain(..keep_from);
        }
    }
}

/// Tick-level statistics for a symbol.
///
/// Tracks trade count, volume, price range, and spread from raw ticks.
#[derive(Debug, Clone)]
pub struct TickStats {
    /// Symbol being tracked.
    pub symbol: String,
    /// Total number of trades.
    pub trade_count: u64,
    /// Total volume traded.
    pub total_volume: f64,
    /// Highest price seen.
    pub high: f64,
    /// Lowest price seen.
    pub low: f64,
    /// Last trade price.
    pub last_price: f64,
    /// VWAP.
    pub vwap: f64,
    /// Price of the first trade.
    pub open: f64,
    /// Average trade size.
    pub avg_trade_size: f64,
    /// Largest single trade.
    pub max_trade_size: f64,
    /// Timestamp of last update.
    pub last_update: Option<DateTime<Utc>>,
}

impl TickStats {
    /// Create new empty tick stats for a symbol.
    pub fn new(symbol: impl Into<String>) -> Self {
        Self {
            symbol: symbol.into(),
            trade_count: 0,
            total_volume: 0.0,
            high: f64::NEG_INFINITY,
            low: f64::INFINITY,
            last_price: 0.0,
            vwap: 0.0,
            open: 0.0,
            avg_trade_size: 0.0,
            max_trade_size: 0.0,
            last_update: None,
        }
    }

    /// Update stats with a new tick.
    pub fn on_tick(&mut self, tick: &Tick) {
        if self.trade_count == 0 {
            self.open = tick.price;
        }

        self.trade_count += 1;
        self.total_volume += tick.amount;
        self.high = self.high.max(tick.price);
        self.low = self.low.min(tick.price);
        self.last_price = tick.price;
        self.max_trade_size = self.max_trade_size.max(tick.amount);
        self.avg_trade_size = self.total_volume / self.trade_count as f64;
        self.last_update = Some(tick.timestamp);

        // VWAP
        self.vwap = if self.total_volume > 0.0 {
            // Approximation: we need running PV; use incremental update
            // This is a simplification — for exact VWAP, use VwapCalculator
            self.vwap * (self.total_volume - tick.amount) / self.total_volume
                + tick.price * tick.amount / self.total_volume
        } else {
            tick.price
        };
    }

    /// Reset all stats.
    pub fn reset(&mut self) {
        self.trade_count = 0;
        self.total_volume = 0.0;
        self.high = f64::NEG_INFINITY;
        self.low = f64::INFINITY;
        self.last_price = 0.0;
        self.vwap = 0.0;
        self.open = 0.0;
        self.avg_trade_size = 0.0;
        self.max_trade_size = 0.0;
        self.last_update = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tsar_core::types::OrderSide;

    fn make_tick(symbol: &str, price: f64, amount: f64) -> Tick {
        Tick {
            symbol: symbol.to_string(),
            price,
            amount,
            side: OrderSide::Buy,
            timestamp: Utc::now(),
        }
    }

    #[test]
    fn test_vwap_single_tick() {
        let mut calc = VwapCalculator::new("BTC/USDT");
        let tick = make_tick("BTC/USDT", 50000.0, 1.0);
        let vwap = calc.on_tick(&tick);
        assert!((vwap - 50000.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_vwap_multiple_ticks() {
        let mut calc = VwapCalculator::new("BTC/USDT");

        // Tick 1: price=100, volume=10 → PV=1000
        calc.on_tick(&make_tick("BTC/USDT", 100.0, 10.0));
        // Tick 2: price=200, volume=10 → PV=2000
        calc.on_tick(&make_tick("BTC/USDT", 200.0, 10.0));

        // VWAP = (1000 + 2000) / (10 + 10) = 150
        assert!((calc.vwap() - 150.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_vwap_weighted() {
        let mut calc = VwapCalculator::new("BTC/USDT");

        // Heavier volume at lower price should pull VWAP down
        calc.on_tick(&make_tick("BTC/USDT", 100.0, 100.0));
        calc.on_tick(&make_tick("BTC/USDT", 200.0, 10.0));

        // VWAP = (100*100 + 200*10) / 110 = 12000/110 ≈ 109.09
        let expected = 12000.0 / 110.0;
        assert!((calc.vwap() - expected).abs() < 0.01);
    }

    #[test]
    fn test_vwap_reset() {
        let mut calc = VwapCalculator::new("BTC/USDT");
        calc.on_tick(&make_tick("BTC/USDT", 50000.0, 1.0));
        assert_eq!(calc.tick_count(), 1);

        calc.reset();
        assert_eq!(calc.tick_count(), 0);
        assert_eq!(calc.vwap(), 0.0);
    }

    #[test]
    fn test_tick_stats_basic() {
        let mut stats = TickStats::new("BTC/USDT");

        stats.on_tick(&make_tick("BTC/USDT", 50000.0, 0.5));
        stats.on_tick(&make_tick("BTC/USDT", 50100.0, 0.3));
        stats.on_tick(&make_tick("BTC/USDT", 49900.0, 0.2));

        assert_eq!(stats.trade_count, 3);
        assert!((stats.total_volume - 1.0).abs() < f64::EPSILON);
        assert_eq!(stats.high, 50100.0);
        assert_eq!(stats.low, 49900.0);
        assert_eq!(stats.last_price, 49900.0);
        assert_eq!(stats.open, 50000.0);
        assert_eq!(stats.max_trade_size, 0.5);
    }
}
