//! Connection pool for managing multiple WebSocket connections.
//!
//! Maintains a pool of [`WsConnection`] instances across multiple exchanges,
//! with lifecycle management and health monitoring.
//!
//! Supports subscribing to multiple Binance streams through a single
//! combined stream endpoint, or managing separate connections per stream.

use std::collections::HashMap;

use crate::connection::{ConnectionState, WsConnection};
use crate::reconnect::{ReconnectPolicy, ReconnectState};
use tsar_core::error::{TsarError, TsarResult};

/// Configuration for building a Binance combined stream URL.
#[derive(Debug, Clone)]
pub struct BinanceStreamConfig {
    /// Symbols to subscribe to (e.g., ["btcusdt", "ethusdt"]).
    pub symbols: Vec<String>,
    /// Stream types (e.g., ["trade", "depth@100ms", "kline_1m"]).
    pub streams: Vec<String>,
    /// Whether to use the combined stream endpoint.
    pub combined: bool,
    /// Whether to use testnet.
    pub testnet: bool,
}

impl BinanceStreamConfig {
    /// Build the WebSocket URL for this configuration.
    pub fn build_url(&self) -> String {
        let base = if self.testnet {
            "wss://testnet.binance.vision/ws"
        } else {
            "wss://stream.binance.com:9443/ws"
        };

        if self.combined {
            // Combined stream: /stream?streams=btcusdt@trade/ethusdt@trade
            let stream_names: Vec<String> = self
                .symbols
                .iter()
                .flat_map(|symbol| {
                    self.streams
                        .iter()
                        .map(move |stream| format!("{symbol}@{stream}"))
                })
                .collect();

            format!(
                "wss://{}{}",
                if self.testnet {
                    "testnet.binance.vision/stream?streams="
                } else {
                    "stream.binance.com:9443/stream?streams="
                },
                stream_names.join("/")
            )
        } else {
            base.to_string()
        }
    }
}

impl Default for BinanceStreamConfig {
    fn default() -> Self {
        Self {
            symbols: vec!["btcusdt".to_string()],
            streams: vec!["trade".to_string()],
            combined: true,
            testnet: false,
        }
    }
}

/// A pool of WebSocket connections to multiple exchange endpoints.
///
/// Manages connection lifecycle, health monitoring, and automatic
/// reconnection with configurable backoff policies.
#[derive(Debug)]
pub struct ConnectionPool {
    /// Active connections keyed by connection ID.
    connections: HashMap<uuid::Uuid, WsConnection>,
    /// Maximum number of concurrent connections.
    max_connections: usize,
    /// Reconnection policy applied to all connections.
    reconnect_policy: ReconnectPolicy,
    /// Per-connection reconnection state.
    reconnect_states: HashMap<uuid::Uuid, ReconnectState>,
}

impl ConnectionPool {
    /// Create a new connection pool with the given capacity limit.
    pub fn new(max_connections: usize) -> Self {
        Self {
            connections: HashMap::with_capacity(max_connections),
            max_connections,
            reconnect_policy: ReconnectPolicy::default(),
            reconnect_states: HashMap::new(),
        }
    }

    /// Create a new connection pool with a custom reconnection policy.
    pub fn with_policy(max_connections: usize, policy: ReconnectPolicy) -> Self {
        Self {
            connections: HashMap::with_capacity(max_connections),
            max_connections,
            reconnect_policy: policy,
            reconnect_states: HashMap::new(),
        }
    }

    /// Add a new connection to the pool.
    ///
    /// Returns an error if the pool is at capacity.
    pub fn add(&mut self, connection: WsConnection) -> TsarResult<uuid::Uuid> {
        if self.connections.len() >= self.max_connections {
            return Err(TsarError::Internal(format!(
                "Connection pool full ({}/{})",
                self.connections.len(),
                self.max_connections
            )));
        }
        let id = connection.id;
        self.connections.insert(id, connection);
        self.reconnect_states
            .insert(id, ReconnectState::new(self.reconnect_policy.clone()));
        tracing::info!(
            connection_id = %id,
            pool_size = self.connections.len(),
            "Connection added to pool"
        );
        Ok(id)
    }

    /// Remove and disconnect a connection from the pool.
    pub async fn remove(&mut self, id: &uuid::Uuid) -> TsarResult<()> {
        if let Some(mut conn) = self.connections.remove(id) {
            self.reconnect_states.remove(id);
            conn.disconnect().await?;
            tracing::info!(
                connection_id = %id,
                pool_size = self.connections.len(),
                "Connection removed from pool"
            );
        }
        Ok(())
    }

    /// Get a reference to a connection by ID.
    pub fn get(&self, id: &uuid::Uuid) -> Option<&WsConnection> {
        self.connections.get(id)
    }

    /// Get a mutable reference to a connection by ID.
    pub fn get_mut(&mut self, id: &uuid::Uuid) -> Option<&mut WsConnection> {
        self.connections.get_mut(id)
    }

    /// Return the number of active connections in the pool.
    pub fn len(&self) -> usize {
        self.connections.len()
    }

    /// Returns true if the pool has no connections.
    pub fn is_empty(&self) -> bool {
        self.connections.is_empty()
    }

    /// Return IDs of all connections that are not in the Connected state.
    pub fn unhealthy_connections(&self) -> Vec<uuid::Uuid> {
        self.connections
            .iter()
            .filter(|(_, conn)| conn.state != ConnectionState::Connected)
            .map(|(id, _)| *id)
            .collect()
    }

    /// Return the total number of messages received across all connections.
    pub fn total_messages_received(&self) -> u64 {
        self.connections.values().map(|c| c.messages_received).sum()
    }

    /// Connect all disconnected connections in the pool.
    pub async fn connect_all(&mut self) -> TsarResult<()> {
        let ids: Vec<uuid::Uuid> = self
            .connections
            .iter()
            .filter(|(_, conn)| conn.state == ConnectionState::Disconnected)
            .map(|(id, _)| *id)
            .collect();

        for id in ids {
            if let Some(conn) = self.connections.get_mut(&id) {
                match conn.connect().await {
                    Ok(()) => {
                        // Reset reconnection state on successful connect
                        if let Some(state) = self.reconnect_states.get_mut(&id) {
                            state.reset();
                        }
                    }
                    Err(e) => {
                        tracing::error!(
                            connection_id = %id,
                            error = %e,
                            "Failed to connect"
                        );
                    }
                }
            }
        }
        Ok(())
    }

    /// Disconnect all connections in the pool.
    pub async fn disconnect_all(&mut self) -> TsarResult<()> {
        for conn in self.connections.values_mut() {
            if conn.state == ConnectionState::Connected {
                conn.disconnect().await?;
            }
        }
        Ok(())
    }

    /// Attempt to reconnect a specific connection with backoff.
    ///
    /// Returns `true` if reconnection was attempted, `false` if
    /// max attempts are exhausted.
    pub async fn reconnect(&mut self, id: &uuid::Uuid) -> TsarResult<bool> {
        let state = self.reconnect_states.get_mut(id).ok_or_else(|| {
            TsarError::Internal(format!("No reconnect state for connection {id}"))
        })?;

        if !state.can_retry {
            return Ok(false);
        }

        let delay_ms = state.next_delay_ms();
        tracing::info!(
            connection_id = %id,
            attempt = state.attempt,
            delay_ms = delay_ms,
            "Reconnecting with backoff"
        );

        // Apply backoff delay
        if delay_ms > 0 {
            tokio::time::sleep(std::time::Duration::from_millis(delay_ms)).await;
        }

        state.record_attempt();

        // Disconnect first if needed
        if let Some(conn) = self.connections.get_mut(id) {
            if conn.state == ConnectionState::Connected
                || conn.state == ConnectionState::Reconnecting
            {
                let _ = conn.disconnect().await;
            }
            conn.state = ConnectionState::Reconnecting;
        }

        // Attempt reconnect
        if let Some(conn) = self.connections.get_mut(id) {
            match conn.connect().await {
                Ok(()) => {
                    if let Some(state) = self.reconnect_states.get_mut(id) {
                        state.reset();
                    }
                    return Ok(true);
                }
                Err(e) => {
                    tracing::warn!(
                        connection_id = %id,
                        error = %e,
                        "Reconnect attempt failed"
                    );
                }
            }
        }

        Ok(self.reconnect_states.get(id).map_or(false, |s| s.can_retry))
    }

    /// Get all connection IDs.
    pub fn connection_ids(&self) -> Vec<uuid::Uuid> {
        self.connections.keys().copied().collect()
    }
}
