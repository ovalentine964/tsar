//! OHLCV candle aggregation from raw tick data.
//!
//! Aggregates incoming ticks into OHLCV candles for multiple timeframes
//! (1s, 1m, 5m, 15m, 1h, 4h, 1d).

use std::collections::HashMap;

use chrono::{DateTime, Duration, Utc};
use tsar_core::types::{OHLCV, Tick};

/// Supported aggregation timeframes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Timeframe {
    /// 1 second
    S1,
    /// 1 minute
    M1,
    /// 5 minutes
    M5,
    /// 15 minutes
    M15,
    /// 1 hour
    H1,
    /// 4 hours
    H4,
    /// 1 day
    D1,
}

impl Timeframe {
    /// Return the duration for this timeframe.
    pub fn duration(&self) -> Duration {
        match self {
            Timeframe::S1 => Duration::seconds(1),
            Timeframe::M1 => Duration::minutes(1),
            Timeframe::M5 => Duration::minutes(5),
            Timeframe::M15 => Duration::minutes(15),
            Timeframe::H1 => Duration::hours(1),
            Timeframe::H4 => Duration::hours(4),
            Timeframe::D1 => Duration::days(1),
        }
    }

    /// Return the string representation (e.g., "1m", "5m", "1h").
    pub fn as_str(&self) -> &'static str {
        match self {
            Timeframe::S1 => "1s",
            Timeframe::M1 => "1m",
            Timeframe::M5 => "5m",
            Timeframe::M15 => "15m",
            Timeframe::H1 => "1h",
            Timeframe::H4 => "4h",
            Timeframe::D1 => "1d",
        }
    }
}

impl std::fmt::Display for Timeframe {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// Internal state for a candle being built from ticks.
#[derive(Debug, Clone)]
struct CandleBuilder {
    symbol: String,
    timeframe: Timeframe,
    open: f64,
    high: f64,
    low: f64,
    close: f64,
    volume: f64,
    period_start: DateTime<Utc>,
    tick_count: u64,
}

impl CandleBuilder {
    fn new(symbol: String, timeframe: Timeframe, tick: &Tick, period_start: DateTime<Utc>) -> Self {
        Self {
            symbol,
            timeframe,
            open: tick.price,
            high: tick.price,
            low: tick.price,
            close: tick.price,
            volume: tick.amount,
            period_start,
            tick_count: 1,
        }
    }

    fn update(&mut self, tick: &Tick) {
        self.high = self.high.max(tick.price);
        self.low = self.low.min(tick.price);
        self.close = tick.price;
        self.volume += tick.amount;
        self.tick_count += 1;
    }

    fn to_ohlcv(&self) -> OHLCV {
        OHLCV {
            symbol: self.symbol.clone(),
            timeframe: self.timeframe.to_string(),
            open: self.open,
            high: self.high,
            low: self.low,
            close: self.close,
            volume: self.volume,
            timestamp: self.period_start,
        }
    }
}

/// Aggregates raw ticks into OHLCV candles for multiple timeframes.
///
/// Each symbol/timeframe pair maintains its own candle builder.
/// Completed candles are returned when a new tick falls in a new period.
#[derive(Debug)]
pub struct OhlcvAggregator {
    /// Active candle builders keyed by (symbol, timeframe).
    builders: HashMap<(String, String), CandleBuilder>,
    /// Timeframes to aggregate.
    timeframes: Vec<Timeframe>,
    /// Completed candles ready for consumption.
    completed: Vec<OHLCV>,
}

impl OhlcvAggregator {
    /// Create a new aggregator for the given timeframes.
    pub fn new(timeframes: Vec<Timeframe>) -> Self {
        Self {
            builders: HashMap::new(),
            timeframes,
            completed: Vec::new(),
        }
    }

    /// Create an aggregator with default timeframes (1m, 5m, 15m, 1h).
    pub fn default_timeframes() -> Self {
        Self::new(vec![
            Timeframe::M1,
            Timeframe::M5,
            Timeframe::M15,
            Timeframe::H1,
        ])
    }

    /// Feed a tick into the aggregator.
    ///
    /// Returns any candles that were completed by this tick.
    pub fn on_tick(&mut self, tick: &Tick) -> Vec<OHLCV> {
        let mut newly_completed = Vec::new();

        for &timeframe in &self.timeframes {
            let key = (tick.symbol.clone(), timeframe.to_string());
            let period_start = self.align_to_period(tick.timestamp, timeframe);

            if let Some(builder) = self.builders.get_mut(&key) {
                if builder.period_start == period_start {
                    // Same period — update existing candle
                    builder.update(tick);
                } else {
                    // New period — finalize current candle and start a new one
                    newly_completed.push(builder.to_ohlcv());
                    *builder =
                        CandleBuilder::new(tick.symbol.clone(), timeframe, tick, period_start);
                }
            } else {
                // First tick for this symbol/timeframe
                self.builders.insert(
                    key,
                    CandleBuilder::new(tick.symbol.clone(), timeframe, tick, period_start),
                );
            }
        }

        self.completed.extend(newly_completed.clone());
        newly_completed
    }

    /// Drain all completed candles.
    pub fn drain_completed(&mut self) -> Vec<OHLCV> {
        std::mem::take(&mut self.completed)
    }

    /// Get a snapshot of the current (in-progress) candle for a symbol/timeframe.
    pub fn current_candle(&self, symbol: &str, timeframe: Timeframe) -> Option<OHLCV> {
        let key = (symbol.to_string(), timeframe.to_string());
        self.builders.get(&key).map(|b| b.to_ohlcv())
    }

    /// Align a timestamp to the start of the period for the given timeframe.
    fn align_to_period(&self, timestamp: DateTime<Utc>, timeframe: Timeframe) -> DateTime<Utc> {
        let duration_secs = timeframe.duration().num_seconds();
        let ts_secs = timestamp.timestamp();
        let aligned = ts_secs - (ts_secs % duration_secs);
        DateTime::from_timestamp(aligned, 0).unwrap_or(timestamp)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_tick(symbol: &str, price: f64, amount: f64, ts: DateTime<Utc>) -> Tick {
        Tick {
            symbol: symbol.to_string(),
            price,
            amount,
            side: tsar_core::types::OrderSide::Buy,
            timestamp: ts,
        }
    }

    #[test]
    fn test_single_tick_creates_candle() {
        let mut agg = OhlcvAggregator::new(vec![Timeframe::M1]);
        let ts = Utc::now();
        let tick = make_tick("BTC/USDT", 50000.0, 0.1, ts);

        let completed = agg.on_tick(&tick);
        assert!(completed.is_empty()); // First tick, no completed candle yet

        let current = agg.current_candle("BTC/USDT", Timeframe::M1);
        assert!(current.is_some());
        let c = current.unwrap();
        assert_eq!(c.open, 50000.0);
        assert_eq!(c.close, 50000.0);
        assert_eq!(c.high, 50000.0);
        assert_eq!(c.low, 50000.0);
    }

    #[test]
    fn test_multiple_ticks_update_candle() {
        let mut agg = OhlcvAggregator::new(vec![Timeframe::M1]);
        let ts = Utc::now();

        agg.on_tick(&make_tick("BTC/USDT", 50000.0, 0.1, ts));
        agg.on_tick(&make_tick("BTC/USDT", 50100.0, 0.2, ts));
        agg.on_tick(&make_tick("BTC/USDT", 49900.0, 0.3, ts));

        let c = agg.current_candle("BTC/USDT", Timeframe::M1).unwrap();
        assert_eq!(c.open, 50000.0);
        assert_eq!(c.high, 50100.0);
        assert_eq!(c.low, 49900.0);
        assert_eq!(c.close, 49900.0);
        assert!((c.volume - 0.6).abs() < f64::EPSILON);
    }

    #[test]
    fn test_candle_completes_on_new_period() {
        let mut agg = OhlcvAggregator::new(vec![Timeframe::M1]);
        // Use a timestamp aligned to minute boundary
        let ts1 = DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
            .unwrap()
            .to_utc();
        let ts2 = DateTime::parse_from_rfc3339("2026-01-01T00:01:00Z")
            .unwrap()
            .to_utc();

        agg.on_tick(&make_tick("BTC/USDT", 50000.0, 0.1, ts1));
        let completed = agg.on_tick(&make_tick("BTC/USDT", 50100.0, 0.2, ts2));

        assert_eq!(completed.len(), 1);
        assert_eq!(completed[0].open, 50000.0);
        assert_eq!(completed[0].close, 50000.0);
    }
}
