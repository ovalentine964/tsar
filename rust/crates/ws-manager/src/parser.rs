//! Message parsing for exchange WebSocket streams.
//!
//! Parses raw JSON messages from exchange WebSocket feeds into
//! typed TSAR data structures.
//!
//! Supports Binance spot/futures trade, depth, and kline streams.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tsar_core::types::{OrderBook, OrderBookEntry, OrderSide, Spread, Tick, Trade, OHLCV};

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
    /// A kline/candlestick update.
    Kline(OHLCV),
    /// A heartbeat/ping message.
    Heartbeat,
    /// An unrecognized message type.
    Unknown(String),
}

/// Parse a raw JSON string into a [`ParsedMessage`].
///
/// Dispatches to exchange-specific parsers based on the `exchange` parameter.
pub fn parse_message(raw: &str, exchange: &str) -> ParsedMessage {
    match exchange {
        "binance" => parse_binance_message(raw),
        _ => {
            tracing::warn!(exchange = exchange, "Unknown exchange, returning Unknown");
            ParsedMessage::Unknown(raw.to_string())
        }
    }
}

/// Parse a Binance WebSocket message.
///
/// Detects the message type from the JSON structure and dispatches
/// to the appropriate parser.
fn parse_binance_message(raw: &str) -> ParsedMessage {
    let value: serde_json::Value = match serde_json::from_str(raw) {
        Ok(v) => v,
        Err(_) => return ParsedMessage::Unknown(raw.to_string()),
    };

    // Check for subscription response or result messages
    if value.get("result").is_some() || value.get("id").is_some() {
        return ParsedMessage::Heartbeat;
    }

    // Check for error messages
    if let Some(code) = value.get("code") {
        tracing::warn!(code = ?code, msg = ?value.get("msg"), "Binance error message");
        return ParsedMessage::Unknown(raw.to_string());
    }

    // Detect stream type from the event field
    let event_type = value
        .get("e")
        .and_then(|v| v.as_str())
        .unwrap_or("");

    match event_type {
        "trade" => parse_binance_trade_json(&value)
            .map(ParsedMessage::Trade)
            .unwrap_or_else(|| ParsedMessage::Unknown(raw.to_string())),
        "aggTrade" => parse_binance_agg_trade_json(&value)
            .map(ParsedMessage::Trade)
            .unwrap_or_else(|| ParsedMessage::Unknown(raw.to_string())),
        "depthUpdate" => parse_binance_depth_update_json(&value)
            .map(ParsedMessage::OrderBookUpdate)
            .unwrap_or_else(|| ParsedMessage::Unknown(raw.to_string())),
        "kline" => parse_binance_kline_json(&value)
            .map(ParsedMessage::Kline)
            .unwrap_or_else(|| ParsedMessage::Unknown(raw.to_string())),
        "24hrTicker" => {
            // Extract spread info from 24hr ticker
            parse_binance_ticker_spread(&value)
                .map(ParsedMessage::Spread)
                .unwrap_or_else(|| ParsedMessage::Unknown(raw.to_string()))
        }
        _ => {
            tracing::trace!(event = event_type, "Unhandled Binance event type");
            ParsedMessage::Unknown(raw.to_string())
        }
    }
}

/// Parse a Binance `trade` event.
///
/// JSON format:
/// ```json
/// {
///   "e": "trade",
///   "s": "BTCUSDT",
///   "p": "50000.00",
///   "q": "0.1",
///   "T": 1234567890123,
///   "m": true
/// }
/// ```
fn parse_binance_trade_json(value: &serde_json::Value) -> Option<Trade> {
    let symbol = normalize_symbol(value.get("s")?.as_str()?);
    let price = value.get("p")?.as_str()?.parse::<f64>().ok()?;
    let amount = value.get("q")?.as_str()?.parse::<f64>().ok()?;
    let timestamp_ms = value.get("T")?.as_i64()?;
    let is_buyer_maker = value.get("m")?.as_bool().unwrap_or(false);

    let timestamp = DateTime::from_timestamp_millis(timestamp_ms)?;

    Some(Trade {
        id: value
            .get("t")
            .and_then(|v| v.as_i64())
            .map(|id| id.to_string())
            .unwrap_or_default(),
        symbol,
        price,
        amount,
        side: if is_buyer_maker {
            OrderSide::Sell
        } else {
            OrderSide::Buy
        },
        timestamp,
    })
}

/// Parse a Binance `aggTrade` event.
fn parse_binance_agg_trade_json(value: &serde_json::Value) -> Option<Trade> {
    let symbol = normalize_symbol(value.get("s")?.as_str()?);
    let price = value.get("p")?.as_str()?.parse::<f64>().ok()?;
    let amount = value.get("q")?.as_str()?.parse::<f64>().ok()?;
    let timestamp_ms = value.get("T")?.as_i64()?;
    let is_buyer_maker = value.get("m")?.as_bool().unwrap_or(false);

    let timestamp = DateTime::from_timestamp_millis(timestamp_ms)?;

    Some(Trade {
        id: value
            .get("a")
            .and_then(|v| v.as_i64())
            .map(|id| id.to_string())
            .unwrap_or_default(),
        symbol,
        price,
        amount,
        side: if is_buyer_maker {
            OrderSide::Sell
        } else {
            OrderSide::Buy
        },
        timestamp,
    })
}

/// Parse a Binance `depthUpdate` event.
///
/// JSON format:
/// ```json
/// {
///   "e": "depthUpdate",
///   "s": "BTCUSDT",
///   "b": [["49900.00", "1.000"]],
///   "a": [["50000.00", "1.500"]],
///   "U": 100,
///   "u": 120
/// }
/// ```
fn parse_binance_depth_update_json(value: &serde_json::Value) -> Option<OrderBook> {
    let symbol = normalize_symbol(value.get("s")?.as_str()?);
    let timestamp = Utc::now();

    let bids = parse_price_levels(value.get("b")?)?;
    let asks = parse_price_levels(value.get("a")?)?;

    Some(OrderBook {
        symbol,
        bids,
        asks,
        timestamp,
    })
}

/// Parse Binance price level arrays `[[price_str, qty_str], ...]`.
fn parse_price_levels(value: &serde_json::Value) -> Option<Vec<OrderBookEntry>> {
    let array = value.as_array()?;
    let mut entries = Vec::with_capacity(array.len());

    for level in array {
        let level_arr = level.as_array()?;
        if level_arr.len() < 2 {
            continue;
        }
        let price = level_arr[0].as_str()?.parse::<f64>().ok()?;
        let amount = level_arr[1].as_str()?.parse::<f64>().ok()?;
        entries.push(OrderBookEntry { price, amount });
    }

    Some(entries)
}

/// Parse a Binance `kline` event.
///
/// JSON format:
/// ```json
/// {
///   "e": "kline",
///   "s": "BTCUSDT",
///   "k": {
///     "t": 1234567890000,
///     "T": 1234567949999,
///     "s": "BTCUSDT",
///     "i": "1m",
///     "o": "50000.00",
///     "h": "50100.00",
///     "l": "49900.00",
///     "c": "50050.00",
///     "v": "10.5",
///     "x": true
///   }
/// }
/// ```
fn parse_binance_kline_json(value: &serde_json::Value) -> Option<OHLCV> {
    let k = value.get("k")?;
    let symbol = normalize_symbol(k.get("s")?.as_str()?);
    let timeframe = k.get("i")?.as_str()?;
    let open = k.get("o")?.as_str()?.parse::<f64>().ok()?;
    let high = k.get("h")?.as_str()?.parse::<f64>().ok()?;
    let low = k.get("l")?.as_str()?.parse::<f64>().ok()?;
    let close = k.get("c")?.as_str()?.parse::<f64>().ok()?;
    let volume = k.get("v")?.as_str()?.parse::<f64>().ok()?;
    let timestamp_ms = k.get("t")?.as_i64()?;

    let timestamp = DateTime::from_timestamp_millis(timestamp_ms)?;

    Some(OHLCV {
        symbol,
        timeframe: timeframe.to_string(),
        open,
        high,
        low,
        close,
        volume,
        timestamp,
    })
}

/// Extract spread info from a 24hrTicker event.
fn parse_binance_ticker_spread(value: &serde_json::Value) -> Option<Spread> {
    let symbol = normalize_symbol(value.get("s")?.as_str()?);
    let bid = value.get("b")?.as_str()?.parse::<f64>().ok()?;
    let ask = value.get("a")?.as_str()?.parse::<f64>().ok()?;

    if bid <= 0.0 || ask <= 0.0 || ask < bid {
        return None;
    }

    let spread_abs = ask - bid;
    let mid = (bid + ask) / 2.0;
    let spread_bps = if mid > 0.0 {
        (spread_abs / mid) * 10_000.0
    } else {
        return None;
    };

    Some(Spread {
        symbol,
        bid,
        ask,
        spread_abs,
        spread_bps,
        timestamp: Utc::now(),
    })
}

/// Normalize Binance symbol format (e.g., "BTCUSDT" → "BTC/USDT").
fn normalize_symbol(raw: &str) -> String {
    // Common quote currencies to split on
    const QUOTE_SUFFIXES: &[&str] = &[
        "USDT", "BUSD", "USDC", "BTC", "ETH", "BNB", "TRY", "EUR", "GBP", "AUD", "DAI",
    ];

    for quote in QUOTE_SUFFIXES {
        if raw.ends_with(quote) && raw.len() > quote.len() {
            let base = &raw[..raw.len() - quote.len()];
            return format!("{base}/{quote}");
        }
    }

    raw.to_string()
}

/// Parse a raw Binance trade message (convenience function).
pub fn parse_binance_trade(raw: &str) -> Option<Trade> {
    let value: serde_json::Value = serde_json::from_str(raw).ok()?;
    parse_binance_trade_json(&value)
}

/// Parse a raw Binance depth update message (convenience function).
pub fn parse_binance_depth(raw: &str) -> Option<OrderBook> {
    let value: serde_json::Value = serde_json::from_str(raw).ok()?;
    parse_binance_depth_update_json(&value)
}

/// Parse a raw Binance kline message (convenience function).
pub fn parse_binance_kline(raw: &str) -> Option<OHLCV> {
    let value: serde_json::Value = serde_json::from_str(raw).ok()?;
    parse_binance_kline_json(&value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_trade() {
        let raw = r#"{
            "e": "trade",
            "s": "BTCUSDT",
            "p": "50000.00",
            "q": "0.1",
            "T": 1704067200000,
            "t": 12345,
            "m": true
        }"#;

        let result = parse_message(raw, "binance");
        match result {
            ParsedMessage::Trade(trade) => {
                assert_eq!(trade.symbol, "BTC/USDT");
                assert_eq!(trade.price, 50000.0);
                assert_eq!(trade.amount, 0.1);
                assert_eq!(trade.side, OrderSide::Sell); // buyer maker = sell
            }
            _ => panic!("Expected Trade, got {:?}", result),
        }
    }

    #[test]
    fn test_parse_agg_trade() {
        let raw = r#"{
            "e": "aggTrade",
            "s": "ETHUSDT",
            "p": "3000.50",
            "q": "2.5",
            "T": 1704067200000,
            "a": 99999,
            "m": false
        }"#;

        let result = parse_message(raw, "binance");
        match result {
            ParsedMessage::Trade(trade) => {
                assert_eq!(trade.symbol, "ETH/USDT");
                assert_eq!(trade.price, 3000.5);
                assert_eq!(trade.side, OrderSide::Buy);
            }
            _ => panic!("Expected Trade"),
        }
    }

    #[test]
    fn test_parse_depth_update() {
        let raw = r#"{
            "e": "depthUpdate",
            "s": "BTCUSDT",
            "b": [["49900.00", "1.000"], ["49800.00", "2.000"]],
            "a": [["50000.00", "1.500"], ["50100.00", "0.500"]],
            "U": 100,
            "u": 120
        }"#;

        let result = parse_message(raw, "binance");
        match result {
            ParsedMessage::OrderBookUpdate(ob) => {
                assert_eq!(ob.symbol, "BTC/USDT");
                assert_eq!(ob.bids.len(), 2);
                assert_eq!(ob.asks.len(), 2);
                assert_eq!(ob.bids[0].price, 49900.0);
                assert_eq!(ob.asks[0].price, 50000.0);
            }
            _ => panic!("Expected OrderBookUpdate"),
        }
    }

    #[test]
    fn test_parse_kline() {
        let raw = r#"{
            "e": "kline",
            "s": "BTCUSDT",
            "k": {
                "t": 1704067200000,
                "T": 1704067259999,
                "s": "BTCUSDT",
                "i": "1m",
                "o": "50000.00",
                "h": "50100.00",
                "l": "49900.00",
                "c": "50050.00",
                "v": "10.5",
                "x": true
            }
        }"#;

        let result = parse_message(raw, "binance");
        match result {
            ParsedMessage::Kline(ohlcv) => {
                assert_eq!(ohlcv.symbol, "BTC/USDT");
                assert_eq!(ohlcv.timeframe, "1m");
                assert_eq!(ohlcv.open, 50000.0);
                assert_eq!(ohlcv.high, 50100.0);
                assert_eq!(ohlcv.low, 49900.0);
                assert_eq!(ohlcv.close, 50050.0);
                assert_eq!(ohlcv.volume, 10.5);
            }
            _ => panic!("Expected Kline"),
        }
    }

    #[test]
    fn test_parse_unknown_exchange() {
        let result = parse_message(r#"{"key":"value"}"#, "kraken");
        assert!(matches!(result, ParsedMessage::Unknown(_)));
    }

    #[test]
    fn test_parse_invalid_json() {
        let result = parse_message("not json", "binance");
        assert!(matches!(result, ParsedMessage::Unknown(_)));
    }

    #[test]
    fn test_normalize_symbol() {
        assert_eq!(normalize_symbol("BTCUSDT"), "BTC/USDT");
        assert_eq!(normalize_symbol("ETHBTC"), "ETH/BTC");
        assert_eq!(normalize_symbol("SOLUSDT"), "SOL/USDT");
        assert_eq!(normalize_symbol("BNBBTC"), "BNB/BTC");
    }

    #[test]
    fn test_parse_ticker_spread() {
        let raw = r#"{
            "e": "24hrTicker",
            "s": "BTCUSDT",
            "b": "49900.00",
            "a": "50000.00"
        }"#;

        let result = parse_message(raw, "binance");
        match result {
            ParsedMessage::Spread(spread) => {
                assert_eq!(spread.symbol, "BTC/USDT");
                assert_eq!(spread.bid, 49900.0);
                assert_eq!(spread.ask, 50000.0);
                assert!(spread.spread_bps > 0.0);
            }
            _ => panic!("Expected Spread"),
        }
    }
}
