//! Pyth price feed reading.
//!
//! Reads price data from the Pyth Network oracle via HTTP API.

use reqwest::Client;
use serde::Deserialize;
use tracing::{debug, info, warn};

use crate::types::*;

/// Pyth price feed reader.
pub struct PythClient {
    base_url: String,
    http: Client,
}

#[derive(Debug, Deserialize)]
struct PythPriceResponse {
    #[serde(rename = "parsed")]
    parsed: Vec<PythParsedPrice>,
}

#[derive(Debug, Deserialize)]
struct PythParsedPrice {
    #[serde(rename = "id")]
    id: String,
    #[serde(rename = "price")]
    price: PythPriceData,
}

#[derive(Debug, Deserialize)]
struct PythPriceData {
    price: String,
    conf: String,
    expo: i32,
    publish_time: u64,
}

impl PythClient {
    /// Create a new Pyth client.
    ///
    /// # Arguments
    /// * `base_url` - Pyth API base URL (default: https://hermes.pyth.network)
    pub fn new(base_url: Option<&str>) -> Self {
        Self {
            base_url: base_url
                .unwrap_or("https://hermes.pyth.network")
                .to_string(),
            http: Client::new(),
        }
    }

    /// Read a price from Pyth by price feed ID.
    ///
    /// # Arguments
    /// * `price_id` - Pyth price feed ID (hex, with or without 0x prefix)
    /// * `symbol` - Token symbol for labeling
    pub async fn read_price(
        &self,
        price_id: &str,
        symbol: &str,
    ) -> Result<PriceObservation, OracleClientError> {
        let url = format!("{}/api/latest_vaas", self.base_url);
        let clean_id = price_id.strip_prefix("0x").unwrap_or(price_id);

        let resp = self
            .http
            .get(&url)
            .query(&[("ids[]", clean_id)])
            .send()
            .await
            .map_err(|e| OracleClientError::Rpc(format!("Pyth API request failed: {e}")))?;

        // The latest_vaas endpoint returns base64-encoded VAAs
        // For price data, we use the /api/updates/price/latest endpoint instead
        let url2 = format!("{}/api/updates/price/latest", self.base_url);
        let resp2 = self
            .http
            .get(&url2)
            .query(&[("ids[]", clean_id)])
            .send()
            .await
            .map_err(|e| OracleClientError::Rpc(format!("Pyth price API failed: {e}")))?;

        let data: serde_json::Value = resp2
            .json()
            .await
            .map_err(|e| OracleClientError::Serialization(e))?;

        // Parse the Pyth response
        let parsed = data
            .get("parsed")
            .and_then(|p| p.as_array())
            .ok_or_else(|| OracleClientError::Rpc("Invalid Pyth response format".to_string()))?;

        if parsed.is_empty() {
            return Err(OracleClientError::InsufficientData(format!(
                "No price data for {symbol}"
            )));
        }

        let price_entry = &parsed[0];
        let price_data = price_entry
            .get("price")
            .ok_or_else(|| OracleClientError::Rpc("Missing price field".to_string()))?;

        let price_str = price_data
            .get("price")
            .and_then(|v| v.as_str())
            .unwrap_or("0");
        let conf_str = price_data
            .get("conf")
            .and_then(|v| v.as_str())
            .unwrap_or("0");
        let expo = price_data
            .get("expo")
            .and_then(|v| v.as_i64())
            .unwrap_or(-8) as i32;
        let publish_time = price_data
            .get("publish_time")
            .and_then(|v| v.as_u64())
            .unwrap_or(0);

        let price_raw: f64 = price_str.parse().unwrap_or(0.0);
        let conf_raw: f64 = conf_str.parse().unwrap_or(0.0);
        let price = price_raw * 10f64.powi(expo);
        let conf = conf_raw * 10f64.powi(expo);

        // Confidence as percentage of price (lower conf = higher confidence)
        let confidence = if price > 0.0 {
            1.0 - (conf / price).min(1.0)
        } else {
            0.0
        };

        debug!(
            symbol,
            price,
            confidence,
            publish_time,
            "Pyth price read"
        );

        Ok(PriceObservation {
            source: "pyth".to_string(),
            symbol: symbol.to_string(),
            price_usd: price,
            timestamp: chrono::DateTime::from_timestamp(publish_time as i64, 0)
                .unwrap_or_else(chrono::Utc::now),
            confidence,
            decimals: (-expo) as u8,
        })
    }

    /// Read prices for multiple symbols in a single request.
    pub async fn read_prices_batch(
        &self,
        feeds: &[(&str, &str)], // (price_id, symbol) pairs
    ) -> Vec<Result<PriceObservation, OracleClientError>> {
        let ids: Vec<&str> = feeds.iter().map(|(id, _)| *id).collect();

        let url = format!("{}/api/updates/price/latest", self.base_url);
        let resp = self
            .http
            .get(&url)
            .query(&ids.iter().map(|id| ("ids[]", *id)).collect::<Vec<_>>())
            .send()
            .await;

        match resp {
            Ok(r) => {
                let data: serde_json::Value = r.json().await.unwrap_or_default;
                let parsed = data.get("parsed").and_then(|p| p.as_array()).unwrap_or(&vec![]);

                feeds
                    .iter()
                    .enumerate()
                    .map(|(i, (_, symbol))| {
                        if i < parsed.len() {
                            let entry = &parsed[i];
                            let price_data = entry.get("price").unwrap_or(&serde_json::Value::Null);
                            let price_str = price_data.get("price").and_then(|v| v.as_str()).unwrap_or("0");
                            let expo = price_data.get("expo").and_then(|v| v.as_i64()).unwrap_or(-8) as i32;
                            let publish_time = price_data.get("publish_time").and_then(|v| v.as_u64()).unwrap_or(0);

                            let price: f64 = price_str.parse().unwrap_or(0.0) * 10f64.powi(expo);

                            Ok(PriceObservation {
                                source: "pyth".to_string(),
                                symbol: symbol.to_string(),
                                price_usd: price,
                                timestamp: chrono::DateTime::from_timestamp(publish_time as i64, 0)
                                    .unwrap_or_else(chrono::Utc::now),
                                confidence: 0.95,
                                decimals: (-expo) as u8,
                            })
                        } else {
                            Err(OracleClientError::InsufficientData(format!("No data for {symbol}")))
                        }
                    })
                    .collect()
            }
            Err(e) => {
                let err = Err(OracleClientError::Rpc(format!("Batch fetch failed: {e}")));
                feeds.iter().map(|_| err.clone()).collect()
            }
        }
    }
}
