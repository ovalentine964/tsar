//! Integration tests for the tick processor.
//!
//! Tests OHLCV aggregation, order book management, spread calculation,
//! and ring buffer operations.

use chrono::{DateTime, Utc};
use tsar_core::types::{OrderBookEntry, OrderSide, Tick};
use tsar_tick_processor::aggregator::{OhlcvAggregator, Timeframe};
use tsar_tick_processor::orderbook::OrderBookManager;
use tsar_tick_processor::ring_buffer::RingBuffer;
use tsar_tick_processor::spread::SpreadCalculator;

fn make_tick(symbol: &str, price: f64, amount: f64, ts: DateTime<Utc>) -> Tick {
    Tick {
        symbol: symbol.to_string(),
        price,
        amount,
        side: OrderSide::Buy,
        timestamp: ts,
    }
}

// ── OHLCV Aggregation ────────────────────────────────────────────

#[test]
fn test_ohlcv_aggregation_basic() {
    let mut agg = OhlcvAggregator::new(vec![Timeframe::M1]);
    let ts = Utc::now();

    agg.on_tick(&make_tick("BTC/USDT", 50000.0, 0.1, ts));
    agg.on_tick(&make_tick("BTC/USDT", 50200.0, 0.2, ts));
    agg.on_tick(&make_tick("BTC/USDT", 49800.0, 0.3, ts));
    agg.on_tick(&make_tick("BTC/USDT", 50100.0, 0.4, ts));

    let candle = agg.current_candle("BTC/USDT", Timeframe::M1).unwrap();
    assert_eq!(candle.open, 50000.0);
    assert_eq!(candle.high, 50200.0);
    assert_eq!(candle.low, 49800.0);
    assert_eq!(candle.close, 50100.0);
    assert!((candle.volume - 1.0).abs() < f64::EPSILON);
}

#[test]
fn test_ohlcv_multi_symbol() {
    let mut agg = OhlcvAggregator::new(vec![Timeframe::M5]);
    let ts = Utc::now();

    agg.on_tick(&make_tick("BTC/USDT", 50000.0, 0.1, ts));
    agg.on_tick(&make_tick("ETH/USDT", 3000.0, 1.0, ts));

    assert!(agg.current_candle("BTC/USDT", Timeframe::M5).is_some());
    assert!(agg.current_candle("ETH/USDT", Timeframe::M5).is_some());
    assert!(agg.current_candle("SOL/USDT", Timeframe::M5).is_none());
}

#[test]
fn test_ohlcv_candle_completion_on_period_boundary() {
    let mut agg = OhlcvAggregator::new(vec![Timeframe::M1]);

    let ts1 = DateTime::parse_from_rfc3339("2026-01-01T00:00:30Z")
        .unwrap()
        .to_utc();
    let ts2 = DateTime::parse_from_rfc3339("2026-01-01T00:01:00Z")
        .unwrap()
        .to_utc();

    agg.on_tick(&make_tick("BTC/USDT", 50000.0, 0.1, ts1));
    let completed = agg.on_tick(&make_tick("BTC/USDT", 50100.0, 0.2, ts2));

    assert_eq!(completed.len(), 1);
    assert_eq!(completed[0].open, 50000.0);
    assert_eq!(completed[0].close, 50000.0); // Only the first tick in the candle
    assert_eq!(completed[0].timeframe, "1m");
}

// ── Order Book ───────────────────────────────────────────────────

#[test]
fn test_orderbook_full_workflow() {
    let mut ob = OrderBookManager::new("BTC/USDT");

    // Apply initial snapshot
    ob.apply_snapshot(
        vec![
            OrderBookEntry { price: 49900.0, amount: 1.0 },
            OrderBookEntry { price: 49800.0, amount: 2.0 },
            OrderBookEntry { price: 49700.0, amount: 3.0 },
        ],
        vec![
            OrderBookEntry { price: 50000.0, amount: 1.5 },
            OrderBookEntry { price: 50100.0, amount: 0.5 },
            OrderBookEntry { price: 50200.0, amount: 2.0 },
        ],
        1,
    );

    // Verify best prices
    let (bid, _) = ob.best_bid().unwrap();
    assert_eq!(bid, 49900.0);
    let (ask, _) = ob.best_ask().unwrap();
    assert_eq!(ask, 50000.0);

    // Mid price
    assert_eq!(ob.mid_price(), Some(49950.0));

    // Apply incremental update: new bid level, remove old ask level
    ob.apply_update(
        vec![OrderBookEntry { price: 49950.0, amount: 0.5 }],
        vec![OrderBookEntry { price: 50000.0, amount: 0.0 }], // remove
        2,
    );

    let (new_bid, _) = ob.best_bid().unwrap();
    assert_eq!(new_bid, 49950.0);
    let (new_ask, _) = ob.best_ask().unwrap();
    assert_eq!(new_ask, 50100.0); // 50000 was removed
}

// ── Spread Calculator ────────────────────────────────────────────

#[test]
fn test_spread_calculator_rolling_window() {
    let mut calc = SpreadCalculator::new("BTC/USDT", 5);

    calc.calculate(49900.0, 50000.0);
    calc.calculate(49950.0, 50050.0);
    calc.calculate(49980.0, 50020.0);

    let stats = calc.stats().unwrap();
    assert_eq!(stats.sample_count, 3);
    assert!(stats.min_bps > 0.0);
    assert!(stats.max_bps >= stats.min_bps);
    assert!(stats.avg_bps >= stats.min_bps);
    assert!(stats.avg_bps <= stats.max_bps);
}

#[test]
fn test_spread_calculator_window_overflow() {
    let mut calc = SpreadCalculator::new("BTC/USDT", 3);

    calc.calculate(49900.0, 50000.0);
    calc.calculate(49950.0, 50050.0);
    calc.calculate(49980.0, 50020.0);
    calc.calculate(49990.0, 50010.0); // should evict first sample

    assert_eq!(calc.sample_count(), 3);
}

// ── Ring Buffer ──────────────────────────────────────────────────

#[test]
fn test_ring_buffer_full_workflow() {
    let mut rb = RingBuffer::new(5);

    for i in 0..5 {
        rb.push(i as f64 * 100.0);
    }

    assert_eq!(rb.len(), 5);
    assert!(rb.is_full());
    assert_eq!(rb.to_vec(), vec![0.0, 100.0, 200.0, 300.0, 400.0]);

    // Push more — should overwrite oldest
    rb.push(500.0);
    rb.push(600.0);

    assert_eq!(rb.len(), 5);
    assert_eq!(rb.to_vec(), vec![200.0, 300.0, 400.0, 500.0, 600.0]);
    assert_eq!(rb.latest(), Some(&600.0));
}

#[test]
fn test_ring_buffer_access_by_index() {
    let mut rb = RingBuffer::new(3);
    rb.push(10.0);
    rb.push(20.0);
    rb.push(30.0);

    assert_eq!(rb.get(0), Some(&10.0)); // oldest
    assert_eq!(rb.get(1), Some(&20.0));
    assert_eq!(rb.get(2), Some(&30.0)); // newest
    assert_eq!(rb.get(3), None);
}

#[test]
fn test_ring_buffer_clear_and_reuse() {
    let mut rb = RingBuffer::new(3);
    rb.push(1.0);
    rb.push(2.0);
    rb.clear();

    assert!(rb.is_empty());
    assert_eq!(rb.len(), 0);

    rb.push(100.0);
    assert_eq!(rb.latest(), Some(&100.0));
}
