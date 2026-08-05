//! # Candlestick Pattern Detection
//!
//! High-performance candlestick pattern recognition for the VMPM strategy.
//!
//! Replaces the Python `CandlestickPatterns` class with pure Rust implementations
//! that run 10-100x faster on large datasets (batch processing of thousands of candles).
//!
//! # Patterns Implemented
//!
//! - **Engulfing** (bullish/bearish) — one candle's body fully engulfs the previous
//! - **Pin Bar** (hammer/shooting star) — long wick with small body
//! - **Doji** — very small body relative to total range

/// Detected candlestick pattern.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Pattern {
    /// Bullish engulfing: bearish candle followed by larger bullish candle.
    BullishEngulfing,
    /// Bearish engulfing: bullish candle followed by larger bearish candle.
    BearishEngulfing,
    /// Hammer / bullish pin bar: long lower wick, small body at top.
    Hammer,
    /// Shooting star / bearish pin bar: long upper wick, small body at bottom.
    ShootingStar,
    /// Doji: very small body relative to total range.
    Doji,
}

/// Direction of the candle body.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CandleDirection {
    Bullish,
    Bearish,
}

/// Helper: compute body size (absolute difference between open and close).
#[inline]
fn body_size(o: f64, c: f64) -> f64 {
    (c - o).abs()
}

/// Helper: compute total range (high - low).
#[inline]
fn total_range(h: f64, l: f64) -> f64 {
    h - l
}

/// Helper: determine candle direction.
#[inline]
fn candle_direction(o: f64, c: f64) -> CandleDirection {
    if c >= o {
        CandleDirection::Bullish
    } else {
        CandleDirection::Bearish
    }
}

/// Detect engulfing pattern between current and previous candle.
///
/// A **bullish engulfing** occurs when:
/// - Previous candle is bearish (close < open)
/// - Current candle is bullish (close > open)
/// - Current body fully engulfs previous body (current open ≤ prev close AND current close ≥ prev open)
///
/// A **bearish engulfing** occurs when:
/// - Previous candle is bullish (close > open)
/// - Current candle is bearish (close < open)
/// - Current body fully engulfs previous body (current open ≥ prev close AND current close ≤ prev open)
///
/// # Arguments
/// * `o, h, l, c` — Current candle OHLC
/// * `prev_o, prev_c` — Previous candle open and close
///
/// # Returns
/// `Some(Pattern)` if engulfing detected, `None` otherwise.
pub fn detect_engulfing(
    o: f64,
    _h: f64,
    _l: f64,
    c: f64,
    prev_o: f64,
    prev_c: f64,
) -> Option<Pattern> {
    let prev_dir = candle_direction(prev_o, prev_c);
    let curr_dir = candle_direction(o, c);

    let prev_body_high = prev_o.max(prev_c);
    let prev_body_low = prev_o.min(prev_c);
    let curr_body_high = o.max(c);
    let curr_body_low = o.min(c);

    match (prev_dir, curr_dir) {
        // Bullish engulfing
        (CandleDirection::Bearish, CandleDirection::Bullish) => {
            if curr_body_low <= prev_body_low && curr_body_high >= prev_body_high {
                Some(Pattern::BullishEngulfing)
            } else {
                None
            }
        }
        // Bearish engulfing
        (CandleDirection::Bullish, CandleDirection::Bearish) => {
            if curr_body_high >= prev_body_high && curr_body_low <= prev_body_low {
                Some(Pattern::BearishEngulfing)
            } else {
                None
            }
        }
        _ => None,
    }
}

/// Detect pin bar pattern (hammer or shooting star).
///
/// A **hammer** (bullish pin bar) has:
/// - Long lower wick (≥ `wick_threshold` × total range)
/// - Small body in the upper portion of the candle
/// - Upper wick < body size
///
/// A **shooting star** (bearish pin bar) has:
/// - Long upper wick (≥ `wick_threshold` × total range)
/// - Small body in the lower portion of the candle
/// - Lower wick < body size
///
/// # Arguments
/// * `o, h, l, c` — Candle OHLC
/// * `wick_threshold` — Minimum ratio of dominant wick to total range (typically 0.6-0.7)
///
/// # Returns
/// `Some(Pattern::Hammer)` or `Some(Pattern::ShootingStar)`, or `None`.
pub fn detect_pin_bar(o: f64, h: f64, l: f64, c: f64, wick_threshold: f64) -> Option<Pattern> {
    let range = total_range(h, l);
    if range <= 0.0 {
        return None;
    }

    let body = body_size(o, c);
    let upper_wick = h - o.max(c);
    let lower_wick = o.min(c) - l;

    let upper_ratio = upper_wick / range;
    let lower_ratio = lower_wick / range;

    // Hammer: long lower wick
    if lower_ratio >= wick_threshold && upper_wick < body {
        return Some(Pattern::Hammer);
    }

    // Shooting star: long upper wick
    if upper_ratio >= wick_threshold && lower_wick < body {
        return Some(Pattern::ShootingStar);
    }

    None
}

/// Detect doji pattern.
///
/// A doji has a very small body relative to the total range.
///
/// # Arguments
/// * `o, h, l, c` — Candle OHLC
/// * `body_threshold` — Maximum ratio of body to total range to qualify as doji
///                      (typically 0.05-0.1, i.e. 5-10%)
///
/// # Returns
/// `Some(Pattern::Doji)` if body ≤ `body_threshold` × range, `None` otherwise.
pub fn detect_doji(o: f64, h: f64, l: f64, c: f64, body_threshold: f64) -> Option<Pattern> {
    let range = total_range(h, l);
    if range <= 0.0 {
        // Zero range candle — effectively a doji if open == close
        return if (o - c).abs() < 1e-10 {
            Some(Pattern::Doji)
        } else {
            None
        };
    }

    let body = body_size(o, c);
    if body / range <= body_threshold {
        Some(Pattern::Doji)
    } else {
        None
    }
}

/// Detect all patterns for a single candle (convenience function).
///
/// Returns a vector of all detected patterns for the current candle.
pub fn detect_all(
    o: f64,
    h: f64,
    l: f64,
    c: f64,
    prev_o: f64,
    prev_c: f64,
    wick_threshold: f64,
    body_threshold: f64,
) -> Vec<Pattern> {
    let mut patterns = Vec::new();

    if let Some(p) = detect_engulfing(o, h, l, c, prev_o, prev_c) {
        patterns.push(p);
    }
    if let Some(p) = detect_pin_bar(o, h, l, c, wick_threshold) {
        patterns.push(p);
    }
    if let Some(p) = detect_doji(o, h, l, c, body_threshold) {
        patterns.push(p);
    }

    patterns
}

/// Batch detect patterns across a series of candles.
///
/// Returns a vector of (index, pattern) pairs for all detected patterns.
pub fn batch_detect(
    candles: &[(f64, f64, f64, f64)], // (open, high, low, close)
    wick_threshold: f64,
    body_threshold: f64,
) -> Vec<(usize, Pattern)> {
    let mut results = Vec::new();

    for i in 1..candles.len() {
        let (o, h, l, c) = candles[i];
        let (prev_o, _prev_h, _prev_l, prev_c) = candles[i - 1];

        if let Some(p) = detect_engulfing(o, h, l, c, prev_o, prev_c) {
            results.push((i, p));
        }
        if let Some(p) = detect_pin_bar(o, h, l, c, wick_threshold) {
            results.push((i, p));
        }
        if let Some(p) = detect_doji(o, h, l, c, body_threshold) {
            results.push((i, p));
        }
    }

    results
}

// ═══════════════════════════════════════════════════════════════════════
// UNIT TESTS
// ═══════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    // ── Engulfing Tests ───────────────────────────────────────────

    #[test]
    fn test_bullish_engulfing() {
        // Prev: bearish candle (open=110, close=100)
        // Curr: bullish candle (open=95, close=115) — engulfs prev
        let result = detect_engulfing(95.0, 120.0, 90.0, 115.0, 110.0, 100.0);
        assert_eq!(result, Some(Pattern::BullishEngulfing));
    }

    #[test]
    fn test_bearish_engulfing() {
        // Prev: bullish candle (open=100, close=110)
        // Curr: bearish candle (open=115, close=95) — engulfs prev
        let result = detect_engulfing(115.0, 120.0, 90.0, 95.0, 100.0, 110.0);
        assert_eq!(result, Some(Pattern::BearishEngulfing));
    }

    #[test]
    fn test_no_engulfing_same_direction() {
        // Both bullish — no engulfing
        let result = detect_engulfing(100.0, 110.0, 99.0, 108.0, 95.0, 105.0);
        assert_eq!(result, None);
    }

    #[test]
    fn test_no_engulfing_partial() {
        // Current body doesn't fully engulf previous
        let result = detect_engulfing(102.0, 110.0, 100.0, 108.0, 110.0, 100.0);
        assert_eq!(result, None);
    }

    // ── Pin Bar Tests ─────────────────────────────────────────────

    #[test]
    fn test_hammer() {
        // Hammer: long lower wick, small body at top
        // o=95, h=100, l=80, c=98 → lower_wick=15, body=3, upper_wick=2
        // range=20, lower_ratio=15/20=0.75 ≥ 0.6, upper_wick=2 < body=3 ✓
        let result = detect_pin_bar(95.0, 100.0, 80.0, 98.0, 0.6);
        assert_eq!(result, Some(Pattern::Hammer));
    }

    #[test]
    fn test_shooting_star() {
        // Shooting star: long upper wick, small body at bottom
        // o=98, h=120, l=97, c=95 → upper_wick=22, body=3, lower_wick=2
        // range=23, upper_ratio=22/23=0.956 ≥ 0.6, lower_wick=2 < body=3 ✓
        let result = detect_pin_bar(98.0, 120.0, 97.0, 95.0, 0.6);
        assert_eq!(result, Some(Pattern::ShootingStar));
    }

    #[test]
    fn test_no_pin_bar_balanced() {
        // Balanced candle — neither wick dominant
        // o=100, h=110, l=90, c=105 → upper=5, lower=10, body=5
        // lower_ratio=10/20=0.5 < 0.6
        let result = detect_pin_bar(100.0, 110.0, 90.0, 105.0, 0.6);
        assert_eq!(result, None);
    }

    #[test]
    fn test_no_pin_bar_zero_range() {
        // Flat candle (h == l)
        let result = detect_pin_bar(100.0, 100.0, 100.0, 100.0, 0.6);
        assert_eq!(result, None);
    }

    // ── Doji Tests ────────────────────────────────────────────────

    #[test]
    fn test_doji() {
        // Tiny body relative to range
        // o=100, h=110, l=90, c=100.5 → body=0.5, range=20, ratio=0.025
        let result = detect_doji(100.0, 110.0, 90.0, 100.5, 0.05);
        assert_eq!(result, Some(Pattern::Doji));
    }

    #[test]
    fn test_no_doji_large_body() {
        // Large body
        // o=100, h=110, l=90, c=108 → body=8, range=20, ratio=0.4
        let result = detect_doji(100.0, 110.0, 90.0, 108.0, 0.05);
        assert_eq!(result, None);
    }

    #[test]
    fn test_doji_zero_range() {
        // Zero range — open == close
        let result = detect_doji(100.0, 100.0, 100.0, 100.0, 0.05);
        assert_eq!(result, Some(Pattern::Doji));
    }

    #[test]
    fn test_doji_zero_range_different_oc() {
        // Zero range but open != close (shouldn't happen in real data)
        let result = detect_doji(100.0, 100.0, 100.0, 101.0, 0.05);
        assert_eq!(result, None);
    }

    // ── Batch Detection ──────────────────────────────────────────

    #[test]
    fn test_batch_detect() {
        let candles = vec![
            (100.0, 105.0, 95.0, 102.0),   // 0: bullish
            (102.0, 108.0, 101.0, 107.0),   // 1: bullish
            (107.0, 109.0, 103.0, 104.0),   // 2: bearish
            (100.0, 110.0, 95.0, 108.0),    // 3: bullish engulfing
            (108.0, 115.0, 85.0, 107.0),    // 4: hammer (lower wick dominant)
        ];

        let results = batch_detect(&candles, 0.6, 0.05);

        // Index 3 should have engulfing
        let engulfing_at_3: Vec<_> = results.iter().filter(|(i, _)| *i == 3).collect();
        assert!(
            engulfing_at_3
                .iter()
                .any(|(_, p)| *p == Pattern::BullishEngulfing),
            "Expected BullishEngulfing at index 3, got: {:?}",
            results
        );
    }

    #[test]
    fn test_detect_all_multiple_patterns() {
        // A candle that is both a doji and could have pin bar characteristics
        // Very small body, long lower wick
        let results = detect_all(99.5, 100.0, 90.0, 99.8, 105.0, 104.0, 0.6, 0.05);
        // Should detect at least doji (tiny body)
        assert!(
            results.contains(&Pattern::Doji),
            "Expected Doji, got {:?}",
            results
        );
    }
}
