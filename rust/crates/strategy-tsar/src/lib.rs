//! # strategy-tsar
//!
//! TSAR strategy components ported from Python to Rust for performance.
//!
//! This crate provides:
//! - **RSI computation** (Wilder's smoothing) — the hot path for indicator calculation
//! - **Candlestick pattern detection** — engulfing, pin bar, doji
//! - **Support/Resistance level mapping** — Asian range, order blocks, nearest level
//!
//! All functions are exposed to Python via PyO3 bindings as `strategy_tsar.*`.
//!
//! ## Python Usage
//!
//! ```python
//! import strategy_tsar
//!
//! # RSI
//! rsi_values = strategy_tsar.compute_rsi(closes, period=14)
//! divergence = strategy_tsar.detect_divergence(prices, rsi_values, lookback=30)
//!
//! # Candlestick patterns
//! pattern = strategy_tsar.detect_engulfing(o, h, l, c, prev_o, prev_c)
//! pin = strategy_tsar.detect_pin_bar(o, h, l, c, wick_threshold=0.6)
//!
//! # Levels
//! high, low = strategy_tsar.compute_asian_range(highs, lows, 0, 8)
//! blocks = strategy_tsar.detect_order_blocks(candles, lookback=5)
//! level = strategy_tsar.find_nearest_level(levels, price, "bid")
//! ```

pub mod candlestick;
pub mod level_mapper;
pub mod rsi;

use pyo3::prelude::*;
use pyo3::types::PyList;

// ═══════════════════════════════════════════════════════════════════════
// PyO3 MODULE REGISTRATION
// ═══════════════════════════════════════════════════════════════════════

/// The `strategy_tsar` Python extension module.
///
/// Exposes all TSAR strategy functions as a native Python module.
#[pymodule]
fn strategy_tsar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // ── RSI ───────────────────────────────────────────────────────
    m.add_function(wrap_pyfunction!(py_compute_rsi, m)?)?;
    m.add_function(wrap_pyfunction!(py_detect_divergence, m)?)?;

    // ── Candlestick Patterns ──────────────────────────────────────
    m.add_function(wrap_pyfunction!(py_detect_engulfing, m)?)?;
    m.add_function(wrap_pyfunction!(py_detect_pin_bar, m)?)?;
    m.add_function(wrap_pyfunction!(py_detect_doji, m)?)?;
    m.add_function(wrap_pyfunction!(py_detect_all_patterns, m)?)?;
    m.add_function(wrap_pyfunction!(py_batch_detect_patterns, m)?)?;

    // ── Level Mapper ──────────────────────────────────────────────
    m.add_function(wrap_pyfunction!(py_compute_asian_range, m)?)?;
    m.add_function(wrap_pyfunction!(py_detect_order_blocks, m)?)?;
    m.add_function(wrap_pyfunction!(py_find_nearest_level, m)?)?;

    // ── Utility ───────────────────────────────────────────────────
    m.add_function(wrap_pyfunction!(version, m)?)?;

    tracing::info!("strategy_tsar module initialized");
    Ok(())
}

/// Return the version string.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

// ═══════════════════════════════════════════════════════════════════════
// RSI BINDINGS
// ═══════════════════════════════════════════════════════════════════════

/// Compute RSI using Wilder's smoothing.
///
/// Args:
///     closes: List of closing prices (oldest first).
///     period: RSI period (default 14).
///
/// Returns:
///     List of RSI values (same length as closes, neutral 50.0 for warmup).
#[pyfunction]
#[pyo3(signature = (closes, period=14))]
fn py_compute_rsi(py: Python<'_>, closes: Vec<f64>, period: usize) -> PyResult<PyObject> {
    let result = rsi::compute_rsi(&closes, period);
    Ok(result.into_py(py))
}

/// Detect RSI divergence between price and RSI series.
///
/// Args:
///     prices: Closing prices (oldest first).
///     rsi_values: Corresponding RSI values.
///     lookback: Number of candles to scan.
///
/// Returns:
///     "bullish", "bearish", or None.
#[pyfunction]
#[pyo3(signature = (prices, rsi_values, lookback=30))]
fn py_detect_divergence(
    py: Python<'_>,
    prices: Vec<f64>,
    rsi_values: Vec<f64>,
    lookback: usize,
) -> PyResult<PyObject> {
    match rsi::detect_divergence(&prices, &rsi_values, lookback) {
        Some(rsi::DivergenceType::Bullish) => Ok("bullish".into_py(py)),
        Some(rsi::DivergenceType::Bearish) => Ok("bearish".into_py(py)),
        None => Ok(py.None()),
    }
}

// ═══════════════════════════════════════════════════════════════════════
// CANDLESTICK PATTERN BINDINGS
// ═══════════════════════════════════════════════════════════════════════

/// Detect engulfing pattern.
///
/// Args:
///     o, h, l, c: Current candle OHLC.
///     prev_o, prev_c: Previous candle open and close.
///
/// Returns:
///     "bullish_engulfing", "bearish_engulfing", or None.
#[pyfunction]
fn py_detect_engulfing(
    py: Python<'_>,
    o: f64,
    h: f64,
    l: f64,
    c: f64,
    prev_o: f64,
    prev_c: f64,
) -> PyResult<PyObject> {
    match candlestick::detect_engulfing(o, h, l, c, prev_o, prev_c) {
        Some(candlestick::Pattern::BullishEngulfing) => Ok("bullish_engulfing".into_py(py)),
        Some(candlestick::Pattern::BearishEngulfing) => Ok("bearish_engulfing".into_py(py)),
        _ => Ok(py.None()),
    }
}

/// Detect pin bar (hammer/shooting star).
///
/// Args:
///     o, h, l, c: Candle OHLC.
///     wick_threshold: Minimum wick-to-range ratio (default 0.6).
///
/// Returns:
///     "hammer", "shooting_star", or None.
#[pyfunction]
#[pyo3(signature = (o, h, l, c, wick_threshold=0.6))]
fn py_detect_pin_bar(
    py: Python<'_>,
    o: f64,
    h: f64,
    l: f64,
    c: f64,
    wick_threshold: f64,
) -> PyResult<PyObject> {
    match candlestick::detect_pin_bar(o, h, l, c, wick_threshold) {
        Some(candlestick::Pattern::Hammer) => Ok("hammer".into_py(py)),
        Some(candlestick::Pattern::ShootingStar) => Ok("shooting_star".into_py(py)),
        _ => Ok(py.None()),
    }
}

/// Detect doji pattern.
///
/// Args:
///     o, h, l, c: Candle OHLC.
///     body_threshold: Maximum body-to-range ratio (default 0.05).
///
/// Returns:
///     "doji" or None.
#[pyfunction]
#[pyo3(signature = (o, h, l, c, body_threshold=0.05))]
fn py_detect_doji(
    py: Python<'_>,
    o: f64,
    h: f64,
    l: f64,
    c: f64,
    body_threshold: f64,
) -> PyResult<PyObject> {
    match candlestick::detect_doji(o, h, l, c, body_threshold) {
        Some(candlestick::Pattern::Doji) => Ok("doji".into_py(py)),
        _ => Ok(py.None()),
    }
}

/// Detect all patterns for a single candle.
///
/// Args:
///     o, h, l, c: Current candle OHLC.
///     prev_o, prev_c: Previous candle open/close.
///     wick_threshold: Pin bar wick threshold (default 0.6).
///     body_threshold: Doji body threshold (default 0.05).
///
/// Returns:
///     List of pattern name strings.
#[pyfunction]
#[pyo3(signature = (o, h, l, c, prev_o, prev_c, wick_threshold=0.6, body_threshold=0.05))]
fn py_detect_all_patterns(
    py: Python<'_>,
    o: f64,
    h: f64,
    l: f64,
    c: f64,
    prev_o: f64,
    prev_c: f64,
    wick_threshold: f64,
    body_threshold: f64,
) -> PyResult<PyObject> {
    let patterns = candlestick::detect_all(
        o, h, l, c, prev_o, prev_c, wick_threshold, body_threshold,
    );

    let names: Vec<&str> = patterns
        .iter()
        .map(|p| match p {
            candlestick::Pattern::BullishEngulfing => "bullish_engulfing",
            candlestick::Pattern::BearishEngulfing => "bearish_engulfing",
            candlestick::Pattern::Hammer => "hammer",
            candlestick::Pattern::ShootingStar => "shooting_star",
            candlestick::Pattern::Doji => "doji",
        })
        .collect();

    Ok(names.into_py(py))
}

/// Batch detect patterns across a candle series.
///
/// Args:
///     candles: List of (open, high, low, close) tuples.
///     wick_threshold: Pin bar threshold (default 0.6).
///     body_threshold: Doji threshold (default 0.05).
///
/// Returns:
///     List of (index, pattern_name) tuples.
#[pyfunction]
#[pyo3(signature = (candles, wick_threshold=0.6, body_threshold=0.05))]
fn py_batch_detect_patterns(
    py: Python<'_>,
    candles: &Bound<'_, PyList>,
    wick_threshold: f64,
    body_threshold: f64,
) -> PyResult<PyObject> {
    let mut parsed: Vec<(f64, f64, f64, f64)> = Vec::with_capacity(candles.len());
    for item in candles.iter() {
        let tuple: (f64, f64, f64, f64) = item.extract()?;
        parsed.push(tuple);
    }

    let results = candlestick::batch_detect(&parsed, wick_threshold, body_threshold);

    let py_results: Vec<(usize, String)> = results
        .into_iter()
        .map(|(idx, p)| {
            let name = match p {
                candlestick::Pattern::BullishEngulfing => "bullish_engulfing",
                candlestick::Pattern::BearishEngulfing => "bearish_engulfing",
                candlestick::Pattern::Hammer => "hammer",
                candlestick::Pattern::ShootingStar => "shooting_star",
                candlestick::Pattern::Doji => "doji",
            };
            (idx, name.to_string())
        })
        .collect();

    Ok(py_results.into_py(py))
}

// ═══════════════════════════════════════════════════════════════════════
// LEVEL MAPPER BINDINGS
// ═══════════════════════════════════════════════════════════════════════

/// Compute Asian session range.
///
/// Args:
///     highs: List of candle highs.
///     lows: List of candle lows.
///     session_start: Index of session start.
///     session_end: Index of session end (exclusive).
///
/// Returns:
///     Tuple of (session_high, session_low).
#[pyfunction]
fn py_compute_asian_range(
    highs: Vec<f64>,
    lows: Vec<f64>,
    session_start: usize,
    session_end: usize,
) -> PyResult<(f64, f64)> {
    Ok(level_mapper::compute_asian_range(
        &highs,
        &lows,
        session_start,
        session_end,
    ))
}

/// Detect order blocks in a candle series.
///
/// Args:
///     candles: List of (open, high, low, close) tuples.
///     lookback: Number of candles to look back (default 5).
///
/// Returns:
///     List of dicts with keys: index, high, low, kind.
#[pyfunction]
#[pyo3(signature = (candles, lookback=5))]
fn py_detect_order_blocks(
    py: Python<'_>,
    candles: &Bound<'_, PyList>,
    lookback: usize,
) -> PyResult<PyObject> {
    let mut parsed: Vec<(f64, f64, f64, f64)> = Vec::with_capacity(candles.len());
    for item in candles.iter() {
        let tuple: (f64, f64, f64, f64) = item.extract()?;
        parsed.push(tuple);
    }

    let blocks = level_mapper::detect_order_blocks(&parsed, lookback);

    use pyo3::types::PyDict;
    let py_list = PyList::empty(py);
    for block in &blocks {
        let dict = PyDict::new(py);
        dict.set_item("index", block.index)?;
        dict.set_item("high", block.high)?;
        dict.set_item("low", block.low)?;
        dict.set_item(
            "kind",
            match block.kind {
                level_mapper::OrderBlockKind::Bullish => "bullish",
                level_mapper::OrderBlockKind::Bearish => "bearish",
            },
        )?;
        py_list.append(dict)?;
    }

    Ok(py_list.into())
}

/// Find the nearest support/resistance level.
///
/// Args:
///     levels: List of price levels.
///     price: Current price.
///     side: "bid" for support, "ask" for resistance.
///
/// Returns:
///     Nearest level price, or None.
#[pyfunction]
fn py_find_nearest_level(
    py: Python<'_>,
    levels: Vec<f64>,
    price: f64,
    side: &str,
) -> PyResult<PyObject> {
    let s = match side {
        "bid" => level_mapper::Side::Bid,
        "ask" => level_mapper::Side::Ask,
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "side must be 'bid' or 'ask'",
            ))
        }
    };

    match level_mapper::find_nearest_level(&levels, price, s) {
        Some(level) => Ok(level.into_py(py)),
        None => Ok(py.None()),
    }
}
