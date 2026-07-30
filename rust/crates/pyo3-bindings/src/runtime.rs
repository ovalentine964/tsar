//! Shared tokio runtime for PyO3 bindings.
//!
//! Creates a single multi-threaded tokio runtime at module init time,
//! shared across all PyO3 bridge calls. This eliminates the anti-pattern
//! of creating a new `Runtime::new()` on every Python → Rust call,
//! which was causing:
//!   - Thread pool churn (new threads spawned/destroyed per call)
//!   - Event loop restart overhead (~1ms per call)
//!   - Connection state loss (async state doesn't survive across runtimes)
//!
//! The runtime is created once via `once_cell::sync::Lazy` and lives
//! for the entire process lifetime.

use once_cell::sync::Lazy;
use tokio::runtime::Runtime;

/// Shared multi-threaded tokio runtime.
///
/// Created once on first access. Uses 4 worker threads by default
/// (sufficient for WebSocket I/O + order execution + tick processing).
/// All async bridge methods should use `RUNTIME.block_on(...)` instead
/// of creating their own runtime.
pub static RUNTIME: Lazy<Runtime> = Lazy::new(|| {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(4)
        .enable_all()
        .thread_name("tsar-pyo3")
        .build()
        .expect("Failed to create shared tokio runtime for tsar-pyo3")
});
