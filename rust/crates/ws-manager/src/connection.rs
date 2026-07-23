//! WebSocket connection handling.
//!
//! Manages a single WebSocket connection to an exchange endpoint,
//! including send/receive operations and connection state tracking.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tsar_core::error::TsarResult;

/// State of a WebSocket connection.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ConnectionState {
    /// Not yet connected.
    Disconnected,
    /// Connection handshake in progress.
    Connecting,
    /// Connected and ready to send/receive.
    Connected,
    /// Reconnection in progress.
    Reconnecting,
    /// Permanently closed (manual disconnect).
    Closed,
}

impl std::fmt::Display for ConnectionState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConnectionState::Disconnected => write!(f, "disconnected"),
            ConnectionState::Connecting => write!(f, "connecting"),
            ConnectionState::Connected => write!(f, "connected"),
            ConnectionState::Reconnecting => write!(f, "reconnecting"),
            ConnectionState::Closed => write!(f, "closed"),
        }
    }
}

/// A WebSocket connection to an exchange endpoint.
///
/// Wraps the underlying tokio-tungstenite connection and provides
/// typed send/receive operations.
#[derive(Debug)]
pub struct WsConnection {
    /// Unique connection identifier.
    pub id: uuid::Uuid,
    /// The WebSocket URL this connection targets.
    pub url: String,
    /// Current connection state.
    pub state: ConnectionState,
    /// When the connection was last established.
    pub connected_at: Option<DateTime<Utc>>,
    /// Number of messages received since last connect.
    pub messages_received: u64,
    /// Number of messages sent since last connect.
    pub messages_sent: u64,
}

impl WsConnection {
    /// Create a new connection instance (does not connect yet).
    pub fn new(url: impl Into<String>) -> Self {
        Self {
            id: uuid::Uuid::new_v4(),
            url: url.into(),
            state: ConnectionState::Disconnected,
            connected_at: None,
            messages_received: 0,
            messages_sent: 0,
        }
    }

    /// Establish the WebSocket connection.
    ///
    /// Stub: sets state to Connected. Real implementation uses tokio-tungstenite.
    pub async fn connect(&mut self) -> TsarResult<()> {
        self.state = ConnectionState::Connecting;
        // TODO: Real implementation — tokio_tungstenite::connect_async(&self.url)
        self.state = ConnectionState::Connected;
        self.connected_at = Some(Utc::now());
        tracing::info!(connection_id = %self.id, url = %self.url, "WebSocket connected (stub)");
        Ok(())
    }

    /// Send a text message over the WebSocket.
    ///
    /// Stub: increments counter. Real implementation sends via sink.
    pub async fn send(&mut self, message: &str) -> TsarResult<()> {
        if self.state != ConnectionState::Connected {
            return Err(tsar_core::error::TsarError::WebSocket(
                "Connection not established".to_string(),
            ));
        }
        self.messages_sent += 1;
        tracing::debug!(connection_id = %self.id, len = message.len(), "Message sent (stub)");
        Ok(())
    }

    /// Receive the next message from the WebSocket.
    ///
    /// Stub: returns None. Real implementation reads from stream.
    pub async fn receive(&mut self) -> TsarResult<Option<String>> {
        if self.state != ConnectionState::Connected {
            return Err(tsar_core::error::TsarError::WebSocket(
                "Connection not established".to_string(),
            ));
        }
        self.messages_received += 1;
        // TODO: Real implementation — read from tungstenite stream
        Ok(None)
    }

    /// Close the WebSocket connection gracefully.
    pub async fn disconnect(&mut self) -> TsarResult<()> {
        self.state = ConnectionState::Closed;
        tracing::info!(connection_id = %self.id, "WebSocket disconnected (stub)");
        Ok(())
    }

    /// Returns true if the connection is in the Connected state.
    pub fn is_connected(&self) -> bool {
        self.state == ConnectionState::Connected
    }
}
