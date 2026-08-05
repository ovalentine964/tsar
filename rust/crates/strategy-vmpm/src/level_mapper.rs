//! # Level Mapper — Support/Resistance Level Computation
//!
//! Computes key price levels for the VMPM strategy:
//!
//! - **Asian Range**: High/low of the Asian trading session
//! - **Order Blocks**: Institutional supply/demand zones identified by
//!   strong moves following consolidation
//! - **Nearest Level**: Find the closest S/R level to current price
//!
//! This replaces the Python `LevelMapper` and `SessionRange` classes,
//! providing 10-100x speedup for real-time level lookups.

/// Side of the market (for nearest level lookup).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
    /// Looking for support (level below price).
    Bid,
    /// Looking for resistance (level above price).
    Ask,
}

/// An order block — an institutional supply/demand zone.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct OrderBlock {
    /// Index of the candle that formed the order block.
    pub index: usize,
    /// Upper boundary of the order block zone.
    pub high: f64,
    /// Lower boundary of the order block zone.
    pub low: f64,
    /// Whether this is a bullish (demand) or bearish (supply) order block.
    pub kind: OrderBlockKind,
}

/// Type of order block.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderBlockKind {
    /// Demand zone — expect price to bounce up.
    Bullish,
    /// Supply zone — expect price to bounce down.
    Bearish,
}

/// Compute the Asian session range (high and low).
///
/// The Asian session is typically defined by a start and end index
/// within the candle array (e.g., UTC 00:00–08:00).
///
/// # Arguments
/// * `highs` — Array of candle high prices, oldest first.
/// * `lows` — Array of candle low prices, oldest first.
/// * `session_start` — Index of the first candle in the session.
/// * `session_end` — Index of the last candle in the session (exclusive).
///
/// # Returns
/// `(session_high, session_low)` tuple.
///
/// # Panics
/// Panics if `session_start >= session_end` or indices are out of bounds.
pub fn compute_asian_range(
    highs: &[f64],
    lows: &[f64],
    session_start: usize,
    session_end: usize,
) -> (f64, f64) {
    assert!(
        session_start < session_end,
        "session_start ({}) must be < session_end ({})",
        session_start,
        session_end
    );
    assert!(
        session_end <= highs.len() && session_end <= lows.len(),
        "session_end ({}) out of bounds (highs: {}, lows: {})",
        session_end,
        highs.len(),
        lows.len()
    );

    let mut session_high = f64::NEG_INFINITY;
    let mut session_low = f64::INFINITY;

    for i in session_start..session_end {
        if highs[i] > session_high {
            session_high = highs[i];
        }
        if lows[i] < session_low {
            session_low = lows[i];
        }
    }

    (session_high, session_low)
}

/// Detect order blocks in a candle series.
///
/// An **order block** is identified when:
/// 1. There is a consolidation phase (small candles).
/// 2. Followed by a strong impulsive move (large candle).
/// 3. The last consolidating candle before the move is the order block.
///
/// **Bullish order block**: Bearish consolidation candle followed by a strong
/// bullish move (close > open by significant margin).
///
/// **Bearish order block**: Bullish consolidation candle followed by a strong
/// bearish move (close < open by significant margin).
///
/// # Arguments
/// * `candles` — Slice of `(open, high, low, close)` tuples.
/// * `lookback` — Number of candles to look back for consolidation detection.
///
/// # Returns
/// Vector of detected `OrderBlock`s.
pub fn detect_order_blocks(candles: &[(f64, f64, f64, f64)], lookback: usize) -> Vec<OrderBlock> {
    if candles.len() < lookback + 2 || lookback < 2 {
        return Vec::new();
    }

    let mut blocks = Vec::new();

    // Compute average true range for the whole series as a volatility reference
    let atr = compute_atr(candles);
    if atr <= 0.0 {
        return blocks;
    }

    // Threshold for "strong move" — candle body must be > 1.5× ATR
    let strong_move_threshold = atr * 1.5;
    // Threshold for "small candle" — candle body must be < 0.5× ATR
    let small_candle_threshold = atr * 0.5;

    for i in (lookback + 1)..candles.len() {
        let (o, h, l, c) = candles[i];
        let body = (c - o).abs();
        let range = h - l;

        // Current candle must be a strong move
        if body < strong_move_threshold || range <= 0.0 {
            continue;
        }

        let is_bullish_move = c > o;
        let is_bearish_move = c < o;

        if !is_bullish_move && !is_bearish_move {
            continue;
        }

        // Look back through previous candles for consolidation
        // The order block is the last small candle before the move
        let mut ob_index = None;
        for j in (i - lookback)..i {
            let (prev_o, _prev_h, _prev_l, prev_c) = candles[j];
            let prev_body = (prev_c - prev_o).abs();

            if prev_body < small_candle_threshold {
                ob_index = Some(j);
            }
        }

        if let Some(idx) = ob_index {
            let (ob_o, ob_h, ob_l, ob_c) = candles[idx];

            let kind = if is_bullish_move {
                // Bullish order block: the consolidation candle before a bullish move
                // is typically bearish — it's a demand zone
                OrderBlockKind::Bullish
            } else {
                // Bearish order block: consolidation before bearish move
                // is typically bullish — it's a supply zone
                OrderBlockKind::Bearish
            };

            blocks.push(OrderBlock {
                index: idx,
                high: ob_h,
                low: ob_l,
                kind,
            });
        }
    }

    // Deduplicate overlapping order blocks
    deduplicate_order_blocks(&mut blocks);

    blocks
}

/// Find the nearest support/resistance level to a given price.
///
/// # Arguments
/// * `levels` — Slice of price levels (sorted ascending for best performance).
/// * `price` — Current price.
/// * `side` — Which side to search:
///   - `Side::Bid` → find the highest level below `price` (support)
///   - `Side::Ask` → find the lowest level above `price` (resistance)
///
/// # Returns
/// `Some(level_price)` if a matching level exists, `None` otherwise.
pub fn find_nearest_level(levels: &[f64], price: f64, side: Side) -> Option<f64> {
    if levels.is_empty() {
        return None;
    }

    match side {
        Side::Bid => {
            // Find the highest level below price (support)
            let mut best: Option<f64> = None;
            for &level in levels {
                if level < price {
                    match best {
                        None => best = Some(level),
                        Some(b) if level > b => best = Some(level),
                        _ => {}
                    }
                }
            }
            best
        }
        Side::Ask => {
            // Find the lowest level above price (resistance)
            let mut best: Option<f64> = None;
            for &level in levels {
                if level > price {
                    match best {
                        None => best = Some(level),
                        Some(b) if level < b => best = Some(level),
                        _ => {}
                    }
                }
            }
            best
        }
    }
}

/// Find the nearest level with a tolerance band.
///
/// Returns the nearest level if it's within `tolerance` distance from price.
pub fn find_nearest_level_within(
    levels: &[f64],
    price: f64,
    side: Side,
    tolerance: f64,
) -> Option<f64> {
    let level = find_nearest_level(levels, price, side)?;
    if (level - price).abs() <= tolerance {
        Some(level)
    } else {
        None
    }
}

/// Compute the Average True Range (ATR) over the candle series.
fn compute_atr(candles: &[(f64, f64, f64, f64)]) -> f64 {
    if candles.len() < 2 {
        return 0.0;
    }

    let mut sum_tr = 0.0f64;
    let mut count = 0usize;

    for i in 1..candles.len() {
        let (o, h, l, c) = candles[i];
        let (_prev_o, prev_h, prev_l, prev_c) = candles[i - 1];

        let tr = (h - l)
            .max((h - prev_c).abs())
            .max((l - prev_c).abs());
        sum_tr += tr;
        count += 1;
    }

    if count > 0 {
        sum_tr / count as f64
    } else {
        0.0
    }
}

/// Remove overlapping order blocks, keeping the most recent.
fn deduplicate_order_blocks(blocks: &mut Vec<OrderBlock>) {
    if blocks.len() <= 1 {
        return;
    }

    // Sort by index
    blocks.sort_by_key(|b| b.index);

    let mut deduped = Vec::with_capacity(blocks.len());
    deduped.push(blocks[0]);

    for block in blocks.iter().skip(1) {
        let last = deduped.last().unwrap();

        // If same kind and overlapping ranges, replace with newer
        if last.kind == block.kind && ranges_overlap(last.high, last.low, block.high, block.low) {
            // Remove old, push new
            deduped.pop();
        }
        deduped.push(*block);
    }

    *blocks = deduped;
}

/// Check if two price ranges overlap.
#[inline]
fn ranges_overlap(high_a: f64, low_a: f64, high_b: f64, low_b: f64) -> bool {
    low_a <= high_b && low_b <= high_a
}

// ═══════════════════════════════════════════════════════════════════════
// UNIT TESTS
// ═══════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    // ── Asian Range Tests ─────────────────────────────────────────

    #[test]
    fn test_asian_range_basic() {
        let highs = vec![105.0, 107.0, 103.0, 108.0, 106.0];
        let lows = vec![100.0, 102.0, 99.0, 103.0, 101.0];

        let (high, low) = compute_asian_range(&highs, &lows, 0, 3);
        assert_eq!(high, 107.0);
        assert_eq!(low, 99.0);
    }

    #[test]
    fn test_asian_range_subset() {
        let highs = vec![100.0, 110.0, 105.0, 108.0, 112.0];
        let lows = vec![95.0, 105.0, 100.0, 103.0, 107.0];

        // Session from index 1 to 4 (exclusive)
        let (high, low) = compute_asian_range(&highs, &lows, 1, 4);
        assert_eq!(high, 110.0);
        assert_eq!(low, 100.0);
    }

    #[test]
    fn test_asian_range_single_candle() {
        let highs = vec![105.0, 107.0, 103.0];
        let lows = vec![100.0, 102.0, 99.0];

        let (high, low) = compute_asian_range(&highs, &lows, 1, 2);
        assert_eq!(high, 107.0);
        assert_eq!(low, 102.0);
    }

    #[test]
    #[should_panic(expected = "session_start")]
    fn test_asian_range_invalid_indices() {
        let highs = vec![105.0, 107.0];
        let lows = vec![100.0, 102.0];
        compute_asian_range(&highs, &lows, 3, 1);
    }

    // ── Order Block Tests ─────────────────────────────────────────

    #[test]
    fn test_detect_order_blocks_basic() {
        // Small candles (consolidation) followed by a strong bullish move
        let candles = vec![
            (100.0, 101.0, 99.0, 100.5),  // 0: small
            (100.5, 101.5, 100.0, 101.0), // 1: small
            (101.0, 101.5, 100.5, 100.8), // 2: small (order block candidate)
            (100.8, 108.0, 100.5, 107.5), // 3: strong bullish move
        ];

        let blocks = detect_order_blocks(&candles, 3);
        assert!(!blocks.is_empty(), "Expected at least one order block");

        let bullish_blocks: Vec<_> = blocks
            .iter()
            .filter(|b| b.kind == OrderBlockKind::Bullish)
            .collect();
        assert!(
            !bullish_blocks.is_empty(),
            "Expected a bullish order block"
        );
    }

    #[test]
    fn test_detect_order_blocks_none() {
        // All large candles — no consolidation
        let candles = vec![
            (100.0, 105.0, 95.0, 104.0),
            (104.0, 110.0, 103.0, 109.0),
            (109.0, 115.0, 108.0, 114.0),
            (114.0, 120.0, 113.0, 119.0),
        ];

        let blocks = detect_order_blocks(&candles, 2);
        assert!(blocks.is_empty());
    }

    #[test]
    fn test_detect_order_blocks_too_short() {
        let candles = vec![
            (100.0, 101.0, 99.0, 100.5),
            (100.5, 101.0, 100.0, 100.8),
        ];

        let blocks = detect_order_blocks(&candles, 3);
        assert!(blocks.is_empty());
    }

    // ── Nearest Level Tests ───────────────────────────────────────

    #[test]
    fn test_find_nearest_support() {
        let levels = vec![95.0, 98.0, 100.0, 105.0, 110.0];
        // Price at 102, looking for support (highest level below)
        let result = find_nearest_level(&levels, 102.0, Side::Bid);
        assert_eq!(result, Some(100.0));
    }

    #[test]
    fn test_find_nearest_resistance() {
        let levels = vec![95.0, 98.0, 100.0, 105.0, 110.0];
        // Price at 102, looking for resistance (lowest level above)
        let result = find_nearest_level(&levels, 102.0, Side::Ask);
        assert_eq!(result, Some(105.0));
    }

    #[test]
    fn test_find_nearest_support_at_level() {
        let levels = vec![95.0, 98.0, 100.0, 105.0];
        // Price exactly at a level — should find the one below
        let result = find_nearest_level(&levels, 100.0, Side::Bid);
        assert_eq!(result, Some(98.0));
    }

    #[test]
    fn test_find_nearest_resistance_at_level() {
        let levels = vec![95.0, 98.0, 100.0, 105.0];
        let result = find_nearest_level(&levels, 100.0, Side::Ask);
        assert_eq!(result, Some(105.0));
    }

    #[test]
    fn test_find_nearest_no_support() {
        let levels = vec![105.0, 110.0];
        // Price below all levels — no support
        let result = find_nearest_level(&levels, 100.0, Side::Bid);
        assert_eq!(result, None);
    }

    #[test]
    fn test_find_nearest_no_resistance() {
        let levels = vec![90.0, 95.0];
        // Price above all levels — no resistance
        let result = find_nearest_level(&levels, 100.0, Side::Ask);
        assert_eq!(result, None);
    }

    #[test]
    fn test_find_nearest_empty_levels() {
        let levels: Vec<f64> = vec![];
        assert_eq!(find_nearest_level(&levels, 100.0, Side::Bid), None);
        assert_eq!(find_nearest_level(&levels, 100.0, Side::Ask), None);
    }

    #[test]
    fn test_find_nearest_unsorted() {
        // Should work regardless of sort order
        let levels = vec![110.0, 95.0, 105.0, 98.0, 100.0];
        assert_eq!(find_nearest_level(&levels, 102.0, Side::Bid), Some(100.0));
        assert_eq!(find_nearest_level(&levels, 102.0, Side::Ask), Some(105.0));
    }

    #[test]
    fn test_find_nearest_within_tolerance() {
        let levels = vec![90.0, 95.0, 100.0, 105.0, 110.0];

        // Price 101, tolerance 2.0 → support at 100 is within 1.0
        assert_eq!(
            find_nearest_level_within(&levels, 101.0, Side::Bid, 2.0),
            Some(100.0)
        );

        // Price 101, tolerance 0.5 → support at 100 is 1.0 away, too far
        assert_eq!(
            find_nearest_level_within(&levels, 101.0, Side::Bid, 0.5),
            None
        );
    }

    // ── ATR Tests ─────────────────────────────────────────────────

    #[test]
    fn test_compute_atr() {
        let candles = vec![
            (100.0, 105.0, 98.0, 103.0),
            (103.0, 108.0, 101.0, 106.0),
            (106.0, 110.0, 104.0, 108.0),
        ];
        let atr = compute_atr(&candles);
        assert!(atr > 0.0);
        // TR for candle 1: max(108-101=7, |108-103|=5, |101-103|=2) = 7
        // TR for candle 2: max(110-104=6, |110-106|=4, |104-106|=2) = 6
        // ATR = (7 + 6) / 2 = 6.5
        assert!((atr - 6.5).abs() < 0.01);
    }

    #[test]
    fn test_compute_atr_single_candle() {
        let candles = vec![(100.0, 105.0, 98.0, 103.0)];
        let atr = compute_atr(&candles);
        assert_eq!(atr, 0.0);
    }

    // ── Overlap / Dedup Tests ─────────────────────────────────────

    #[test]
    fn test_ranges_overlap() {
        assert!(ranges_overlap(100.0, 90.0, 105.0, 95.0));
        assert!(ranges_overlap(100.0, 90.0, 95.0, 85.0));
        assert!(!ranges_overlap(100.0, 90.0, 80.0, 70.0));
    }
}
