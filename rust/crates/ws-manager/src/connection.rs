//! WebSocket connection handling.
//!
//! Manages a single WebSocket connection to an exchange endpoint,
//! including send/receive operations and connection state tracking.

use chrono::{DateTime, Utc};
use futures_util::stream::{SplitSink, SplitStream};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message as TungsteniteMessage;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream};
use tsar_core::error::{TsarError, TsarResult};

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

type WsSink = SplitSink<WebSocketStream<MaybeTlsStream<TcpStream>>, TungsteniteMessage>;
type WsStream = SplitStream<WebSocketStream<MaybeTlsStream<TcpStream>>>;

/// A WebSocket connection to an exchange endpoint.
///
/// Uses tokio-tungstenite for the actual WebSocket protocol.
/// The connection is split into a write half (controlled via `send`)
/// and a read half that feeds messages through an async channel.
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
    /// Write half of the WebSocket (sends messages to the exchange).
    write_half: Option<WsSink>,
    /// Channel receiver for incoming messages from the read task.
    rx: Option<mpsc::Receiver<String>>,
    /// Handle to the background read task for cleanup.
    read_task: Option<tokio::task::JoinHandle<()>>,
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
            write_half: None,
            rx: None,
            read_task: None,
        }
    }

    /// Establish the WebSocket connection.
    ///
    /// Connects to the URL, splits the stream, and spawns a background
    /// read task that forwards messages through an async channel.
    pub async fn connect(&mut self) -> TsarResult<()> {
        self.state = ConnectionState::Connecting;
        tracing::info!(connection_id = %self.id, url = %self.url, "Connecting WebSocket");

        let (ws_stream, _response) =
            tokio_tungstenite::connect_async(&self.url)
                .await
                .map_err(|e| TsarError::WebSocketConnect(format!("{e}")))?;

        let (write, read) = ws_stream.split();

        // Channel for read task → connection consumer
        let (tx, rx) = mpsc::channel::<String>(1024);

        // Spawn background read task
        let conn_id = self.id;
        let read_task = tokio::spawn(async move {
            Self::read_loop(conn_id, read, tx).await;
        });

        self.write_half = Some(write);
        self.rx = Some(rx);
        self.read_task = Some(read_task);
        self.state = ConnectionState::Connected;
        self.connected_at = Some(Utc::now());
        self.messages_received = 0;
        self.messages_sent = 0;

        tracing::info!(connection_id = %self.id, "WebSocket connected");
        Ok(())
    }

    /// Background read loop — reads from the WebSocket stream and
    /// forwards text messages through the channel.
    async fn read_loop(
        conn_id: uuid::Uuid,
        mut read: WsStream,
        tx: mpsc::Sender<String>,
    ) {
        while let Some(msg_result) = read.next().await {
            match msg_result {
                Ok(TungsteniteMessage::Text(text)) => {
                    if tx.send(text.to_string()).await.is_err() {
                        tracing::debug!(
                            connection_id = %conn_id,
                            "Read task: receiver dropped, stopping"
                        );
                        break;
                    }
                }
                Ok(TungsteniteMessage::Ping(data)) => {
                    tracing::trace!(
                        connection_id = %conn_id,
                        len = data.len(),
                        "Received ping"
                    );
                    // Pong is handled automatically by tungstenite
                }
                Ok(TungsteniteMessage::Pong(_)) => {
                    tracing::trace!(connection_id = %conn_id, "Received pong");
                }
                Ok(TungsteniteMessage::Close(frame)) => {
                    let reason = frame
                        .map(|f| f.to_string())
                        .unwrap_or_else(|| "no reason".to_string());
                    tracing::warn!(
                        connection_id = %conn_id,
                        reason = %reason,
                        "WebSocket closed by remote"
                    );
                    break;
                }
                Ok(TungsteniteMessage::Binary(_)) => {
                    tracing::trace!(connection_id = %conn_id, "Ignoring binary message");
                }
                Ok(TungsteniteMessage::Frame(_)) => {
                    // Raw frames are not expected in client mode
                }
                Err(e) => {
                    tracing::error!(
                        connection_id = %conn_id,
                        error = %e,
                        "WebSocket read error"
                    );
                    break;
                }
            }
        }
        tracing::debug!(connection_id = %conn_id, "Read task exiting");
    }

    /// Send a text message over the WebSocket.
    pub async fn send(&mut self, message: &str) -> TsarResult<()> {
        if self.state != ConnectionState::Connected {
            return Err(TsarError::WebSocket(
                "Connection not established".to_string(),
            ));
        }

        let write = self
            .write_half
            .as_mut()
            .ok_or_else(|| TsarError::WebSocket("Write half not available".to_string()))?;

        write
            .send(TungsteniteMessage::Text(message.to_string().into()))
            .await
            .map_err(|e| TsarError::WebSocket(format!("Send failed: {e}")))?;

        self.messages_sent += 1;
        tracing::debug!(connection_id = %self.id, len = message.len(), "Message sent");
        Ok(())
    }

    /// Receive the next message from the WebSocket (non-blocking poll).
    ///
    /// Returns `Ok(Some(text))` if a message is available,
    /// `Ok(None)` if no message is ready yet.
    pub async fn receive(&mut self) -> TsarResult<Option<String>> {
        if self.state != ConnectionState::Connected {
            return Err(TsarError::WebSocket(
                "Connection not established".to_string(),
            ));
        }

        let rx = self
            .rx
            .as_mut()
            .ok_or_else(|| TsarError::WebSocket("Receive channel not available".to_string()))?;

        match rx.try_recv() {
            Ok(text) => {
                self.messages_received += 1;
                Ok(Some(text))
            }
            Err(mpsc::error::TryRecvError::Empty) => Ok(None),
            Err(mpsc::error::TryRecvError::Disconnected) => {
                self.state = ConnectionState::Disconnected;
                Err(TsarError::WebSocketClosed {
                    reason: "Read task disconnected".to_string(),
                })
            }
        }
    }

    /// Receive the next message, waiting up to `timeout` for one to arrive.
    ///
    /// Returns `Ok(Some(text))` if a message arrived, `Ok(None)` on timeout.
    pub async fn receive_timeout(
        &mut self,
        timeout: std::time::Duration,
    ) -> TsarResult<Option<String>> {
        if self.state != ConnectionState::Connected {
            return Err(TsarError::WebSocket(
                "Connection not established".to_string(),
            ));
        }

        let rx = self
            .rx
            .as_mut()
            .ok_or_else(|| TsarError::WebSocket("Receive channel not available".to_string()))?;

        match tokio::time::timeout(timeout, rx.recv()).await {
            Ok(Some(text)) => {
                self.messages_received += 1;
                Ok(Some(text))
            }
            Ok(None) => {
                // Channel closed
                self.state = ConnectionState::Disconnected;
                Err(TsarError::WebSocketClosed {
                    reason: "Read task disconnected".to_string(),
                })
            }
            Err(_) => Ok(None), // Timeout
        }
    }

    /// Close the WebSocket connection gracefully.
    pub async fn disconnect(&mut self) -> TsarResult<()> {
        self.state = ConnectionState::Closed;

        // Close the write half (sends close frame)
        if let Some(mut write) = self.write_half.take() {
            let _ = write.close().await;
        }

        // Abort the read task
        if let Some(task) = self.read_task.take() {
            task.abort();
        }

        self.rx = None;

        tracing::info!(connection_id = %self.id, "WebSocket disconnected");
        Ok(())
    }

    /// Returns true if the connection is in the Connected state.
    pub fn is_connected(&self) -> bool {
        self.state == ConnectionState::Connected
    }
}
