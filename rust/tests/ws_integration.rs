//! Integration tests for the WebSocket manager.
//!
//! Tests the full lifecycle: connection creation, pool management,
//! message parsing, and reconnection policies.

use tsar_ws_manager::connection::{ConnectionState, WsConnection};
use tsar_ws_manager::pool::ConnectionPool;
use tsar_ws_manager::parser::parse_message;
use tsar_ws_manager::reconnect::{ReconnectPolicy, ReconnectState};

#[test]
fn test_connection_lifecycle() {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(async {
        let mut conn = WsConnection::new("wss://stream.binance.com:9443/ws/btcusdt@trade");

        assert_eq!(conn.state, ConnectionState::Disconnected);
        assert!(!conn.is_connected());

        conn.connect().await.unwrap();
        assert_eq!(conn.state, ConnectionState::Connected);
        assert!(conn.is_connected());

        conn.send(r#"{"method":"SUBSCRIBE","params":["btcusdt@trade"]}"#)
            .await
            .unwrap();
        assert_eq!(conn.messages_sent, 1);

        conn.disconnect().await.unwrap();
        assert_eq!(conn.state, ConnectionState::Closed);
        assert!(!conn.is_connected());
    });
}

#[test]
fn test_connection_send_without_connect_fails() {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(async {
        let mut conn = WsConnection::new("wss://example.com");
        let result = conn.send("hello").await;
        assert!(result.is_err());
    });
}

#[test]
fn test_pool_add_and_remove() {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(async {
        let mut pool = ConnectionPool::new(5);

        let c1 = WsConnection::new("wss://stream1.example.com");
        let c2 = WsConnection::new("wss://stream2.example.com");

        let id1 = pool.add(c1).unwrap();
        let id2 = pool.add(c2).unwrap();

        assert_eq!(pool.len(), 2);
        assert!(!pool.is_empty());

        pool.remove(&id1).await.unwrap();
        assert_eq!(pool.len(), 1);

        pool.remove(&id2).await.unwrap();
        assert!(pool.is_empty());
    });
}

#[test]
fn test_pool_capacity_limit() {
    let mut pool = ConnectionPool::new(2);

    pool.add(WsConnection::new("wss://a.example.com")).unwrap();
    pool.add(WsConnection::new("wss://b.example.com")).unwrap();

    let result = pool.add(WsConnection::new("wss://c.example.com"));
    assert!(result.is_err());
}

#[test]
fn test_pool_connect_all() {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(async {
        let mut pool = ConnectionPool::new(5);

        pool.add(WsConnection::new("wss://a.example.com")).unwrap();
        pool.add(WsConnection::new("wss://b.example.com")).unwrap();

        pool.connect_all().await.unwrap();

        // Both should now be connected (stub)
        assert_eq!(pool.unhealthy_connections().len(), 0);
    });
}

#[test]
fn test_message_parsing_stub() {
    let result = parse_message(r#"{"e":"trade","p":"50000"}"#, "binance");
    // Stub returns Unknown for all inputs
    assert!(matches!(
        result,
        tsar_ws_manager::parser::ParsedMessage::Unknown(_)
    ));
}

#[test]
fn test_reconnect_policy_exponential_backoff() {
    let policy = ReconnectPolicy {
        max_attempts: 5,
        initial_delay_ms: 100,
        max_delay_ms: 5000,
        backoff_multiplier: 2.0,
        jitter_factor: 0.0,
    };
    let mut state = ReconnectState::new(policy);

    // Attempt 0: 100ms
    assert_eq!(state.next_delay_ms(), 100);
    state.record_attempt();

    // Attempt 1: 200ms
    assert_eq!(state.next_delay_ms(), 200);
    state.record_attempt();

    // Attempt 2: 400ms
    assert_eq!(state.next_delay_ms(), 400);
    state.record_attempt();

    // Attempt 3: 800ms
    assert_eq!(state.next_delay_ms(), 800);
    state.record_attempt();

    // Attempt 4: 1600ms
    assert_eq!(state.next_delay_ms(), 1600);
    assert!(!state.record_attempt()); // exhausted
}

#[test]
fn test_reconnect_state_reset() {
    let policy = ReconnectPolicy::default();
    let mut state = ReconnectState::new(policy);

    state.record_attempt();
    state.record_attempt();
    assert_eq!(state.attempt, 2);

    state.reset();
    assert_eq!(state.attempt, 0);
    assert!(state.can_retry);
}
