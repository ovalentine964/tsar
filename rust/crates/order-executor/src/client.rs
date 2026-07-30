//! Binance REST API client for order management.
//!
//! Handles authentication (HMAC-SHA256 signing), request construction,
//! and response parsing for the Binance spot/futures API.

use std::collections::HashMap;

use chrono::Utc;
use hmac::{Hmac, Mac};
use reqwest::Client;
use sha2::Sha256;
use tsar_core::error::{TsarError, TsarResult};

type HmacSha256 = Hmac<Sha256>;

/// Binance API credentials.
#[derive(Debug, Clone)]
pub struct BinanceCredentials {
    pub api_key: String,
    pub api_secret: String,
}

/// Configuration for the Binance API client.
#[derive(Debug, Clone)]
pub struct BinanceConfig {
    /// REST API base URL.
    pub base_url: String,
    /// API credentials.
    pub credentials: BinanceCredentials,
    /// Request timeout in seconds.
    pub timeout_secs: u64,
}

impl BinanceConfig {
    /// Create config for Binance mainnet.
    pub fn mainnet(api_key: String, api_secret: String) -> Self {
        Self {
            base_url: "https://api.binance.com".to_string(),
            credentials: BinanceCredentials {
                api_key,
                api_secret,
            },
            timeout_secs: 10,
        }
    }

    /// Create config for Binance testnet.
    pub fn testnet(api_key: String, api_secret: String) -> Self {
        Self {
            base_url: "https://testnet.binance.vision".to_string(),
            credentials: BinanceCredentials {
                api_key,
                api_secret,
            },
            timeout_secs: 10,
        }
    }
}

/// Binance REST API client.
///
/// Provides authenticated HTTP requests for order placement,
/// cancellation, and status queries.
#[derive(Debug)]
pub struct BinanceClient {
    config: BinanceConfig,
    http: Client,
}

impl BinanceClient {
    /// Create a new Binance client.
    pub fn new(config: BinanceConfig) -> TsarResult<Self> {
        let http = Client::builder()
            .timeout(std::time::Duration::from_secs(config.timeout_secs))
            .build()
            .map_err(|e| TsarError::Internal(format!("HTTP client init failed: {e}")))?;

        Ok(Self { config, http })
    }

    /// Send a signed POST request to place an order.
    ///
    /// Returns the raw JSON response from Binance.
    pub async fn new_order(
        &self,
        symbol: &str,
        side: &str,
        order_type: &str,
        quantity: f64,
        price: Option<f64>,
        stop_price: Option<f64>,
        time_in_force: Option<&str>,
    ) -> TsarResult<serde_json::Value> {
        let mut params: HashMap<String, String> = HashMap::new();
        params.insert("symbol".to_string(), symbol.to_string());
        params.insert("side".to_string(), side.to_uppercase());
        params.insert("type".to_string(), order_type.to_uppercase());
        params.insert(
            "quantity".to_string(),
            format_quantity(symbol, quantity),
        );

        if let Some(p) = price {
            params.insert("price".to_string(), format_price(symbol, p));
            params.insert(
                "timeInForce".to_string(),
                time_in_force.unwrap_or("GTC").to_string(),
            );
        }

        if let Some(sp) = stop_price {
            params.insert("stopPrice".to_string(), format_price(symbol, sp));
        }

        self.signed_post("/api/v3/order", params).await
    }

    /// Cancel an order by symbol and exchange order ID.
    pub async fn cancel_order(
        &self,
        symbol: &str,
        exchange_order_id: &str,
    ) -> TsarResult<serde_json::Value> {
        let mut params: HashMap<String, String> = HashMap::new();
        params.insert("symbol".to_string(), symbol.to_string());
        params.insert("orderId".to_string(), exchange_order_id.to_string());

        self.signed_delete("/api/v3/order", params).await
    }

    /// Query order status by symbol and exchange order ID.
    pub async fn query_order(
        &self,
        symbol: &str,
        exchange_order_id: &str,
    ) -> TsarResult<serde_json::Value> {
        let mut params: HashMap<String, String> = HashMap::new();
        params.insert("symbol".to_string(), symbol.to_string());
        params.insert("orderId".to_string(), exchange_order_id.to_string());

        self.signed_get("/api/v3/order", params).await
    }

    /// Send a signed POST request.
    async fn signed_post(
        &self,
        path: &str,
        mut params: HashMap<String, String>,
    ) -> TsarResult<serde_json::Value> {
        let timestamp = Utc::now().timestamp_millis().to_string();
        params.insert("timestamp".to_string(), timestamp);
        params.insert("recvWindow".to_string(), "5000".to_string());

        let query_string = self.build_query_string(&params);
        let signature = self.sign(&query_string);
        params.insert("signature".to_string(), signature);

        let url = format!("{}{path}", self.config.base_url);
        let final_query = self.build_query_string(&params);

        tracing::debug!(url = %url, "POST signed request");

        let response = self
            .http
            .post(&url)
            .header("X-MBX-APIKEY", &self.config.credentials.api_key)
            .header("Content-Type", "application/x-www-form-urlencoded")
            .body(final_query)
            .send()
            .await
            .map_err(|e| TsarError::OrderError(format!("HTTP request failed: {e}")))?;

        self.handle_response(response).await
    }

    /// Send a signed GET request.
    async fn signed_get(
        &self,
        path: &str,
        mut params: HashMap<String, String>,
    ) -> TsarResult<serde_json::Value> {
        let timestamp = Utc::now().timestamp_millis().to_string();
        params.insert("timestamp".to_string(), timestamp);
        params.insert("recvWindow".to_string(), "5000".to_string());

        let query_string = self.build_query_string(&params);
        let signature = self.sign(&query_string);

        let url = format!(
            "{}{path}?{query_string}&signature={signature}",
            self.config.base_url
        );

        tracing::debug!(url = %format!("{}{path}", self.config.base_url), "GET signed request");

        let response = self
            .http
            .get(&url)
            .header("X-MBX-APIKEY", &self.config.credentials.api_key)
            .send()
            .await
            .map_err(|e| TsarError::OrderError(format!("HTTP request failed: {e}")))?;

        self.handle_response(response).await
    }

    /// Send a signed DELETE request.
    async fn signed_delete(
        &self,
        path: &str,
        mut params: HashMap<String, String>,
    ) -> TsarResult<serde_json::Value> {
        let timestamp = Utc::now().timestamp_millis().to_string();
        params.insert("timestamp".to_string(), timestamp);
        params.insert("recvWindow".to_string(), "5000".to_string());

        let query_string = self.build_query_string(&params);
        let signature = self.sign(&query_string);

        let url = format!(
            "{}{path}?{query_string}&signature={signature}",
            self.config.base_url
        );

        tracing::debug!(url = %format!("{}{path}", self.config.base_url), "DELETE signed request");

        let response = self
            .http
            .delete(&url)
            .header("X-MBX-APIKEY", &self.config.credentials.api_key)
            .send()
            .await
            .map_err(|e| TsarError::OrderError(format!("HTTP request failed: {e}")))?;

        self.handle_response(response).await
    }

    /// Handle an HTTP response, parsing JSON or returning errors.
    async fn handle_response(
        &self,
        response: reqwest::Response,
    ) -> TsarResult<serde_json::Value> {
        let status = response.status();
        let body = response
            .text()
            .await
            .map_err(|e| TsarError::OrderError(format!("Failed to read response: {e}")))?;

        if status.is_success() {
            serde_json::from_str(&body)
                .map_err(|e| TsarError::ParseError(format!("JSON parse error: {e}")))
        } else {
            // Parse Binance error format
            let error_msg = serde_json::from_str::<serde_json::Value>(&body)
                .ok()
                .and_then(|v| {
                    v.get("msg")
                        .and_then(|m| m.as_str())
                        .map(|s| s.to_string())
                })
                .unwrap_or(body);

            Err(TsarError::OrderError(format!(
                "Binance API error ({}): {}",
                status.as_u16(),
                error_msg
            )))
        }
    }

    /// Build a sorted query string from parameters.
    fn build_query_string(&self, params: &HashMap<String, String>) -> String {
        let mut pairs: Vec<(&str, &str)> = params
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_str()))
            .collect();
        pairs.sort_by_key(|(k, _)| *k);
        pairs
            .iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join("&")
    }

    /// Sign a query string with HMAC-SHA256.
    fn sign(&self, query_string: &str) -> String {
        let mut mac = HmacSha256::new_from_slice(
            self.config.credentials.api_secret.as_bytes(),
        )
        .expect("HMAC can take key of any size");
        mac.update(query_string.as_bytes());
        hex::encode(mac.finalize().into_bytes())
    }
}

/// Format a quantity with appropriate precision for a symbol.
fn format_quantity(symbol: &str, qty: f64) -> String {
    // Default precision; real implementation would read from exchange info
    let precision = symbol_quantity_precision(symbol);
    format!("{qty:.precision$}")
}

/// Format a price with appropriate precision for a symbol.
fn format_price(symbol: &str, price: f64) -> String {
    let precision = symbol_price_precision(symbol);
    format!("{price:.precision$}")
}

/// Get quantity precision for common Binance pairs.
fn symbol_quantity_precision(symbol: &str) -> usize {
    match symbol.to_uppercase().as_str() {
        s if s.starts_with("BTC") => 5,
        s if s.starts_with("ETH") => 4,
        s if s.starts_with("SOL") => 2,
        s if s.starts_with("BNB") => 3,
        _ => 3,
    }
}

/// Get price precision for common Binance pairs.
fn symbol_price_precision(symbol: &str) -> usize {
    match symbol.to_uppercase().as_str() {
        s if s.starts_with("BTC") => 2,
        s if s.starts_with("ETH") => 2,
        s if s.starts_with("SOL") => 2,
        _ => 2,
    }
}

/// Parse a Binance order response into our types.
pub fn parse_order_response(value: &serde_json::Value) -> Option<(&str, &str, &str, f64, f64)> {
    let symbol = value.get("symbol")?.as_str()?;
    let side = value.get("side")?.as_str()?;
    let status = value.get("status")?.as_str()?;
    let qty = value
        .get("origQty")
        .and_then(|v| v.as_str())
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.0);
    let filled = value
        .get("executedQty")
        .and_then(|v| v.as_str())
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.0);
    Some((symbol, side, status, qty, filled))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sign_deterministic() {
        let config = BinanceConfig {
            base_url: "https://api.binance.com".to_string(),
            credentials: BinanceCredentials {
                api_key: "test".to_string(),
                api_secret: "secret".to_string(),
            },
            timeout_secs: 10,
        };
        let client = BinanceClient::new(config).unwrap();

        let sig1 = client.sign("symbol=BTCUSDT&side=BUY&type=MARKET&quantity=0.1&timestamp=123");
        let sig2 = client.sign("symbol=BTCUSDT&side=BUY&type=MARKET&quantity=0.1&timestamp=123");
        assert_eq!(sig1, sig2);
    }

    #[test]
    fn test_format_quantity() {
        assert_eq!(format_quantity("BTCUSDT", 0.123456789), "0.12346");
        assert_eq!(format_quantity("ETHUSDT", 1.23456789), "1.2346");
        assert_eq!(format_quantity("SOLUSDT", 10.5), "10.50");
    }

    #[test]
    fn test_format_price() {
        assert_eq!(format_price("BTCUSDT", 50000.123), "50000.12");
        assert_eq!(format_price("ETHUSDT", 3000.456), "3000.46");
    }

    #[test]
    fn test_build_query_string() {
        let config = BinanceConfig {
            base_url: "https://api.binance.com".to_string(),
            credentials: BinanceCredentials {
                api_key: "test".to_string(),
                api_secret: "secret".to_string(),
            },
            timeout_secs: 10,
        };
        let client = BinanceClient::new(config).unwrap();

        let mut params = HashMap::new();
        params.insert("symbol".to_string(), "BTCUSDT".to_string());
        params.insert("side".to_string(), "BUY".to_string());

        let qs = client.build_query_string(&params);
        assert!(qs.contains("side=BUY"));
        assert!(qs.contains("symbol=BTCUSDT"));
    }
}
