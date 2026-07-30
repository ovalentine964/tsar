//! # tsar-pyo3 (trading_rs)
//!
//! PyO3 Python bindings for the TSAR Rust performance layer.
//!
//! This crate exposes the Rust WebSocket manager, tick processor, and order
//! executor to Python as a native extension module named `trading_rs`.
//!
//! ## Architecture
//!
//! Uses a **single persistent tokio runtime** (via `runtime.rs`) shared across
//! all async operations, avoiding the anti-pattern of creating a new runtime
//! per method call.
//!
//! ## Python Usage
//!
//! ```python
//! import trading_rs
//!
//! # WebSocket manager
//! ws = trading_rs.WsManager()
//! ws.connect_all()
//!
//! # Tick processor
//! tp = trading_rs.TickProcessor(["1m", "5m", "15m", "1h"])
//!
//! # Order executor
//! executor = trading_rs.OrderExecutor()
//! ```

use pyo3::prelude::*;

mod compute;
mod order_bridge;
mod runtime;
mod tick_bridge;
mod ws_bridge;

/// The main Python module entry point.
///
/// Registers all Python classes and functions exposed by the Rust layer.
#[pymodule]
fn trading_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // ── WebSocket Manager ────────────────────────────────────────
    m.add_class::<ws_bridge::PyWsConnection>()?;
    m.add_class::<ws_bridge::PyWsManager>()?;

    // ── Tick Processor ───────────────────────────────────────────
    m.add_class::<tick_bridge::PyTickProcessor>()?;
    m.add_class::<tick_bridge::PySpreadCalculator>()?;
    m.add_class::<tick_bridge::PyRingBuffer>()?;
    m.add_class::<tick_bridge::PyVwapCalculator>()?;
    m.add_class::<tick_bridge::PyTickStats>()?;

    // ── Order Executor ───────────────────────────────────────────
    m.add_class::<order_bridge::PyOrderExecutor>()?;

    // ── Utility Functions ────────────────────────────────────────
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(ping, m)?)?;

    // ── Compute Functions (migrated from Python) ─────────────────
    m.add_function(wrap_pyfunction!(compute::correlation_matrix_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute::rolling_correlation_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute::monte_carlo_simulate_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute::slippage_stats_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute::garman_klass_vol_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute::garch_forecast_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute::batch_factors_py, m)?)?;

    tracing::info!("trading_rs module initialized");
    Ok(())
}

/// Return the version string of the trading_rs module.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Health check ping — returns "pong".
#[pyfunction]
fn ping() -> &'static str {
    "pong"
}
