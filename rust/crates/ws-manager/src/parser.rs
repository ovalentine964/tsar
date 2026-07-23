//! Message parsing for exchange WebSocket streams.
//!
//! Parses raw JSON messages from exchange WebSocket feeds into
//! typed TSAR data structures.

use serde::{Deserialize, Serialize};
use tsar_core::types::{OrderBook, Spread, Tick, Trade};

/// A parsed message from an exchange WebSocket stream.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ParsedMessage {
    /// A single trade execution.
    Trade(Trade),
    /// An order book update.
    OrderBookUpdate(OrderBook),
    /// A spread measurement.
    Spread(Spread),
    /// A raw tick from the stream.
    Tick(Tick),
    /// A heartbeat/ping message.
    Heartbeat,
    /// An unrecognized message type.
    Unknown(String),
}

/// Parse a raw JSON string into a [`ParsedMessage`].
///
/// Stub: returns `Unknown` for all inputs. Real implementation will
/// detect the exchange format and parse accordingly.
pub fn parse_message(raw: &str, exchange: &str) -> ParsedMessage {
    tracing::trace!(exchange = exchange, len = raw.len(), "Parsing message (stub)");
    // TODO: Real implementation — detect exchange, parse JSON, map to types
    match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(_value) => ParsedMessage::Unknown(raw.to_string()),
        Err(_) => ParsedMessage::Unknown(raw.to_string()),
    }
}

/// Parse a Binance trade stream message.
///
/// Stub: returns None. Real implementation parses the `@trade` stream format.
pub fn parse_binance_trade(_raw: &str) -> Option<Trade> {
    // TODO: Real implementation
    None
}

/// Parse a Binance order book depth update.
///
/// Stub: returns None. Real implementation parses the `@depth` stream format.
pub fn parse_binance_depth(_raw: &str) -> Option<OrderBook> {
    // TODO: Real implementation
    None
}

/// Parse a Binance kline (candlestick) stream message.
///
/// Stub: returns None. Real implementation parses the `@kline` stream format.
pub fn parse_binance_kline(_raw: &str) -> Option<tsar_core::types::OHLCV> {
    // TODO: Real implementation
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_unknown_message() {
        let result = parse_message("not json", "binance");
        assert!(matches!(result, ParsedMessage::Unknown(_)));
    }

    #[test]
    fn test_parse_valid_json_unknown() {
        let result = parse_message(r#"{"key":"value"}"#, "binance");
        assert!(matches!(result, ParsedMessage::Unknown(_)));
    }
}
