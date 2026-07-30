//! PyO3 bridge for the WebSocket manager.
//!
//! Exposes [`WsConnection`] and [`ConnectionPool`] to Python.
//! All async operations use the shared global tokio runtime.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_ws_manager::connection::{ConnectionState, WsConnection};
use tsar_ws_manager::pool::{BinanceStreamConfig, ConnectionPool};
use tsar_ws_manager::reconnect::ReconnectPolicy;

/// Python-visible WebSocket connection wrapper.
#[pyclass(name = "WsConnection")]
pub struct PyWsConnection {
    inner: WsConnection,
}

#[pymethods]
impl PyWsConnection {
    /// Create a new WebSocket connection (not yet connected).
    #[new]
    fn new(url: &str) -> Self {
        Self {
            inner: WsConnection::new(url),
        }
    }

    /// Connect to the WebSocket endpoint.
    ///
    /// Uses the shared tokio runtime (no new runtime created).
    fn connect(&mut self) -> PyResult<()> {
        RUNTIME
            .block_on(self.inner.connect())
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Send a text message.
    fn send(&mut self, message: &str) -> PyResult<()> {
        RUNTIME
            .block_on(self.inner.send(message))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Receive the next message (non-blocking).
    ///
    /// Returns the message text, or None if no message is available.
    fn receive(&mut self) -> PyResult<Option<String>> {
        RUNTIME
            .block_on(self.inner.receive())
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Receive the next message, waiting up to `timeout_ms` milliseconds.
    ///
    /// Returns the message text, or None on timeout.
    #[pyo3(signature = (timeout_ms=1000))]
    fn receive_timeout(&mut self, timeout_ms: u64) -> PyResult<Option<String>> {
        let timeout = std::time::Duration::from_millis(timeout_ms);
        RUNTIME
            .block_on(self.inner.receive_timeout(timeout))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Disconnect from the WebSocket endpoint.
    fn disconnect(&mut self) -> PyResult<()> {
        RUNTIME
            .block_on(self.inner.disconnect())
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Returns True if the connection is active.
    fn is_connected(&self) -> bool {
        self.inner.is_connected()
    }

    /// Return the connection state as a string.
    fn state(&self) -> String {
        self.inner.state.to_string()
    }

    /// Return the connection ID as a string.
    fn id(&self) -> String {
        self.inner.id.to_string()
    }

    /// Return the target URL.
    fn url(&self) -> &str {
        &self.inner.url
    }

    /// Return the number of messages received.
    fn messages_received(&self) -> u64 {
        self.inner.messages_received
    }

    /// Return the number of messages sent.
    fn messages_sent(&self) -> u64 {
        self.inner.messages_sent
    }

    fn __repr__(&self) -> String {
        format!(
            "WsConnection(id={}, url='{}', state='{}')",
            self.inner.id, self.inner.url, self.inner.state
        )
    }
}

/// Python-visible WebSocket manager wrapping a connection pool.
///
/// Manages multiple WebSocket connections with health monitoring
/// and automatic reconnection.
#[pyclass(name = "WsManager")]
pub struct PyWsManager {
    pool: ConnectionPool,
}

#[pymethods]
impl PyWsManager {
    /// Create a new WebSocket manager with the given max connections.
    #[new]
    #[pyo3(signature = (max_connections=10))]
    fn new(max_connections: usize) -> Self {
        Self {
            pool: ConnectionPool::new(max_connections),
        }
    }

    /// Add a connection URL to the pool.
    ///
    /// Returns the connection ID as a string.
    fn add_connection(&mut self, url: &str) -> PyResult<String> {
        let conn = WsConnection::new(url);
        let id = self
            .pool
            .add(conn)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(id.to_string())
    }

    /// Create and add a Binance combined stream for the given symbols and streams.
    ///
    /// Example: `add_binance_stream(["btcusdt", "ethusdt"], ["trade", "kline_1m"])`
    #[pyo3(signature = (symbols, streams, testnet=false))]
    fn add_binance_stream(
        &mut self,
        symbols: Vec<String>,
        streams: Vec<String>,
        testnet: bool,
    ) -> PyResult<String> {
        let config = BinanceStreamConfig {
            symbols,
            streams,
            combined: true,
            testnet,
        };
        let url = config.build_url();
        let conn = WsConnection::new(&url);
        let id = self
            .pool
            .add(conn)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        tracing::info!(url = %url, connection_id = %id, "Added Binance stream");
        Ok(id.to_string())
    }

    /// Connect all disconnected connections in the pool.
    fn connect_all(&mut self) -> PyResult<()> {
        RUNTIME
            .block_on(self.pool.connect_all())
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Disconnect all connections in the pool.
    fn disconnect_all(&mut self) -> PyResult<()> {
        RUNTIME
            .block_on(self.pool.disconnect_all())
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Return the number of active connections.
    fn connection_count(&self) -> usize {
        self.pool.len()
    }

    /// Return the total number of messages received across all connections.
    fn total_messages_received(&self) -> u64 {
        self.pool.total_messages_received()
    }

    /// Return IDs of unhealthy connections as a list.
    fn unhealthy_connections(&self) -> Vec<String> {
        self.pool
            .unhealthy_connections()
            .iter()
            .map(|id| id.to_string())
            .collect()
    }

    /// Return all connection IDs.
    fn connection_ids(&self) -> Vec<String> {
        self.pool.connection_ids().iter().map(|id| id.to_string()).collect()
    }

    fn __repr__(&self) -> String {
        format!("WsManager(connections={})", self.pool.len())
    }
}
