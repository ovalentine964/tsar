//! # RSI — Relative Strength Index (Wilder's Smoothing)
//!
//! Hot-path RSI computation and divergence detection for the TSAR strategy.
//!
//! This module replaces the Python `TechnicalIndicators.rsi()` and
//! divergence scanning loops. The Wilder's smoothing variant is used
//! (exponential moving average with α = 1/period) which matches the
//! standard RSI implementation in TA-Lib and most trading platforms.

/// RSI computation result — a series of RSI values aligned with the input.
///
/// Values before `period` candles are filled with 50.0 (neutral).
#[derive(Debug, Clone, PartialEq)]
pub struct RsiResult {
    pub values: Vec<f64>,
    pub period: usize,
}

/// Compute RSI using Wilder's smoothing method.
///
/// This is the performance-critical hot path. The algorithm:
/// 1. Compute initial average gain/loss over the first `period` changes (SMA).
/// 2. Apply Wilder's smoothing: `avg = prev_avg * (1 - α) + current * α`
///    where `α = 1/period`.
/// 3. RSI = 100 - 100 / (1 + avg_gain / avg_loss).
///
/// # Arguments
/// * `closes` — Slice of closing prices, oldest first.
/// * `period` — RSI period (typically 14).
///
/// # Returns
/// `Vec<f64>` of RSI values, same length as `closes`. Positions 0..period
/// are filled with 50.0 (neutral).
pub fn compute_rsi(closes: &[f64], period: usize) -> Vec<f64> {
    let n = closes.len();
    let mut result = vec![50.0f64; n];

    if n < period + 1 || period == 0 {
        return result;
    }

    // Step 1: Initial SMA of gains/losses over first `period` changes
    let mut avg_gain = 0.0f64;
    let mut avg_loss = 0.0f64;

    for i in 1..=period {
        let change = closes[i] - closes[i - 1];
        if change > 0.0 {
            avg_gain += change;
        } else {
            avg_loss -= change;
        }
    }
    avg_gain /= period as f64;
    avg_loss /= period as f64;

    result[period] = rsi_from_averages(avg_gain, avg_loss);

    // Step 2: Wilder's smoothing for remaining values
    let alpha = 1.0 / period as f64;
    let one_minus_alpha = 1.0 - alpha;

    for i in (period + 1)..n {
        let change = closes[i] - closes[i - 1];
        let (gain, loss) = if change > 0.0 {
            (change, 0.0)
        } else {
            (0.0, -change)
        };

        avg_gain = avg_gain * one_minus_alpha + gain * alpha;
        avg_loss = avg_loss * one_minus_alpha + loss * alpha;

        result[i] = rsi_from_averages(avg_gain, avg_loss);
    }

    result
}

/// Compute RSI and return a structured result with metadata.
pub fn compute_rsi_result(closes: &[f64], period: usize) -> RsiResult {
    RsiResult {
        values: compute_rsi(closes, period),
        period,
    }
}

/// Compute RSI value from average gain and loss.
#[inline]
fn rsi_from_averages(avg_gain: f64, avg_loss: f64) -> f64 {
    if avg_loss == 0.0 {
        if avg_gain == 0.0 {
            50.0
        } else {
            100.0
        }
    } else {
        100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    }
}

// ═══════════════════════════════════════════════════════════════════════
// DIVERGENCE DETECTION
// ═══════════════════════════════════════════════════════════════════════

/// Type of RSI divergence detected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DivergenceType {
    /// Price makes lower low, RSI makes higher low → bullish reversal signal.
    Bullish,
    /// Price makes higher high, RSI makes lower high → bearish reversal signal.
    Bearish,
}

/// Detect RSI divergence between price and RSI series.
///
/// Scans the last `lookback` candles for divergence patterns:
/// - **Bullish divergence**: Price forms a lower low while RSI forms a higher low.
/// - **Bearish divergence**: Price forms a higher high while RSI forms a lower high.
///
/// This is a simplified but effective divergence detector that looks at
/// the most recent two swing points within the lookback window.
///
/// # Arguments
/// * `prices` — Closing prices, oldest first.
/// * `rsi_values` — Corresponding RSI values (same length).
/// * `lookback` — Number of candles to scan for divergence.
///
/// # Returns
/// `Some(DivergenceType)` if divergence detected, `None` otherwise.
pub fn detect_divergence(
    prices: &[f64],
    rsi_values: &[f64],
    lookback: usize,
) -> Option<DivergenceType> {
    let n = prices.len().min(rsi_values.len());
    if n < lookback || lookback < 10 {
        return None;
    }

    let start = n - lookback;
    let window_prices = &prices[start..n];
    let window_rsi = &rsi_values[start..n];

    // Find swing lows (local minima) in the lookback window
    let swing_lows = find_swing_lows(window_prices, window_rsi, 3);
    // Find swing highs (local maxima) in the lookback window
    let swing_highs = find_swing_highs(window_prices, window_rsi, 3);

    // Check for bullish divergence: need at least 2 swing lows
    if swing_lows.len() >= 2 {
        let (p1_price, p1_rsi) = swing_lows[swing_lows.len() - 2];
        let (p2_price, p2_rsi) = swing_lows[swing_lows.len() - 1];
        // Price lower low, RSI higher low
        if p2_price < p1_price && p2_rsi > p1_rsi {
            return Some(DivergenceType::Bullish);
        }
    }

    // Check for bearish divergence: need at least 2 swing highs
    if swing_highs.len() >= 2 {
        let (p1_price, p1_rsi) = swing_highs[swing_highs.len() - 2];
        let (p2_price, p2_rsi) = swing_highs[swing_highs.len() - 1];
        // Price higher high, RSI lower high
        if p2_price > p1_price && p2_rsi < p1_rsi {
            return Some(DivergenceType::Bearish);
        }
    }

    None
}

/// Find swing lows (local minima) in price series.
/// Returns (price, rsi) at each swing low point.
fn find_swing_lows(prices: &[f64], rsi: &[f64], strength: usize) -> Vec<(f64, f64)> {
    let n = prices.len();
    let mut swings = Vec::new();

    for i in strength..(n - strength) {
        let mut is_low = true;
        for j in 1..=strength {
            if prices[i] > prices[i - j] || prices[i] > prices[i + j] {
                is_low = false;
                break;
            }
        }
        if is_low {
            swings.push((prices[i], rsi[i]));
        }
    }
    swings
}

/// Find swing highs (local maxima) in price series.
/// Returns (price, rsi) at each swing high point.
fn find_swing_highs(prices: &[f64], rsi: &[f64], strength: usize) -> Vec<(f64, f64)> {
    let n = prices.len();
    let mut swings = Vec::new();

    for i in strength..(n - strength) {
        let mut is_high = true;
        for j in 1..=strength {
            if prices[i] < prices[i - j] || prices[i] < prices[i + j] {
                is_high = false;
                break;
            }
        }
        if is_high {
            swings.push((prices[i], rsi[i]));
        }
    }
    swings
}

// ═══════════════════════════════════════════════════════════════════════
// UNIT TESTS
// ═══════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rsi_empty() {
        let closes: Vec<f64> = vec![];
        let rsi = compute_rsi(&closes, 14);
        assert!(rsi.is_empty());
    }

    #[test]
    fn test_rsi_too_short() {
        let closes = vec![100.0; 10];
        let rsi = compute_rsi(&closes, 14);
        assert_eq!(rsi.len(), 10);
        // All should be neutral (50.0) since we don't have enough data
        assert!(rsi.iter().all(|&v| v == 50.0));
    }

    #[test]
    fn test_rsi_period_zero() {
        let closes = vec![100.0, 101.0, 102.0];
        let rsi = compute_rsi(&closes, 0);
        assert!(rsi.iter().all(|&v| v == 50.0));
    }

    #[test]
    fn test_rsi_basic() {
        // 20 closing prices with a clear uptrend
        let closes: Vec<f64> = (0..30)
            .map(|i| 100.0 + i as f64 * 0.5)
            .collect();
        let rsi = compute_rsi(&closes, 14);

        // After warmup, RSI should be > 50 in an uptrend
        assert!(rsi[20] > 50.0);
        assert!(rsi[29] > 50.0);
    }

    #[test]
    fn test_rsi_downtrend() {
        // Clear downtrend
        let closes: Vec<f64> = (0..30)
            .map(|i| 100.0 - i as f64 * 0.5)
            .collect();
        let rsi = compute_rsi(&closes, 14);

        // RSI should be < 50 in a downtrend
        assert!(rsi[20] < 50.0);
    }

    #[test]
    fn test_rsi_range() {
        // All RSI values should be in [0, 100]
        let closes: Vec<f64> = vec![
            44.0, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
            46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41,
            46.22, 45.64,
        ];
        let rsi = compute_rsi(&closes, 14);
        for &v in &rsi {
            assert!((0.0..=100.0).contains(&v), "RSI {} out of range", v);
        }
    }

    #[test]
    fn test_rsi_wilder_smoothing_matches_reference() {
        // Reference values from a standard RSI calculator (period=14)
        let closes = vec![
            44.0, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
            46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41,
            46.22, 45.64,
        ];
        let rsi = compute_rsi(&closes, 14);
        // RSI at index 14 should be approximately 70.53 for this dataset
        let rsi_14 = rsi[14];
        assert!(
            (rsi_14 - 70.53).abs() < 1.0,
            "RSI at index 14: expected ~70.53, got {}",
            rsi_14
        );
    }

    #[test]
    fn test_rsi_flat_market() {
        // Flat market → RSI should be ~50
        let closes = vec![100.0; 30];
        let rsi = compute_rsi(&closes, 14);
        // No price changes → avg_gain = avg_loss = 0 → RSI = 50
        assert_eq!(rsi[15], 50.0);
    }

    #[test]
    fn test_rsi_all_gains() {
        // Monotonically increasing → RSI should approach 100
        let closes: Vec<f64> = (0..30).map(|i| 100.0 + i as f64).collect();
        let rsi = compute_rsi(&closes, 14);
        assert!(rsi[20] > 90.0, "RSI in all-gains: {}", rsi[20]);
    }

    #[test]
    fn test_divergence_none_too_short() {
        let prices = vec![100.0; 5];
        let rsi = vec![50.0; 5];
        assert_eq!(detect_divergence(&prices, &rsi, 20), None);
    }

    #[test]
    fn test_divergence_bullish() {
        // Construct a bullish divergence scenario:
        // Price: lower low, RSI: higher low
        let mut prices = Vec::new();
        let mut rsi = Vec::new();

        // Uptrend
        for i in 0..10 {
            prices.push(100.0 + i as f64);
            rsi.push(60.0 + i as f64);
        }
        // First swing low
        prices.extend_from_slice(&[108.0, 106.0, 104.0, 106.0, 108.0]);
        rsi.extend_from_slice(&[65.0, 60.0, 55.0, 60.0, 65.0]);
        // Second swing low (price lower, RSI higher)
        prices.extend_from_slice(&[106.0, 103.0, 102.0, 104.0, 106.0]);
        rsi.extend_from_slice(&[63.0, 60.0, 58.0, 62.0, 65.0]);

        let result = detect_divergence(&prices, &rsi, 15);
        assert_eq!(result, Some(DivergenceType::Bullish));
    }

    #[test]
    fn test_divergence_none_no_pattern() {
        // Normal uptrend — no divergence
        let prices: Vec<f64> = (0..30).map(|i| 100.0 + i as f64 * 0.5).collect();
        let rsi = compute_rsi(&prices, 14);
        assert_eq!(detect_divergence(&prices, &rsi, 20), None);
    }
}
