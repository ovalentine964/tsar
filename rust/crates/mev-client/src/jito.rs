//! Jito bundle submission for Solana MEV protection.
//!
//! Submits transaction bundles to Jito block engine for
//! MEV-protected execution on Solana.

use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::{debug, info, warn};

use crate::types::*;

/// Jito block engine client for bundle submission.
pub struct JitoClient {
    block_engine_url: String,
    http: Client,
}

#[derive(Serialize)]
struct JitoSendBundleRequest {
    jsonrpc: String,
    id: u64,
    method: String,
    params: Vec<serde_json::Value>,
}

#[derive(Deserialize)]
struct JitoResponse {
    result: Option<serde_json::Value>,
    error: Option<JitoError>,
}

#[derive(Deserialize)]
struct JitoError {
    code: i64,
    message: String,
}

impl JitoClient {
    /// Create a new Jito client.
    ///
    /// # Arguments
    /// * `block_engine_url` - Jito block engine URL
    pub fn new(block_engine_url: Option<&str>) -> Self {
        Self {
            block_engine_url: block_engine_url
                .unwrap_or("https://mainnet.block-engine.jito.wtf")
                .to_string(),
            http: Client::new(),
        }
    }

    /// Submit a bundle to Jito.
    ///
    /// The bundle includes serialized Solana transactions and a tip
    /// transaction to incentivize the Jito validator.
    ///
    /// # Arguments
    /// * `request` - Bundle with serialized transactions and tip
    pub async fn send_bundle(
        &self,
        request: &JitoBundleRequest,
    ) -> Result<BundleResult, MevClientError> {
        let url = format!("{}/api/v1/bundles", self.block_engine_url);

        let body = JitoSendBundleRequest {
            jsonrpc: "2.0".to_string(),
            id: 1,
            method: "sendBundle".to_string(),
            params: vec![serde_json::json!([request.serialized_transactions])],
        };

        let resp = self
            .http
            .post(&url)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| MevClientError::BundleSubmission(format!("Jito request failed: {e}")))?;

        let jito_resp: JitoResponse = resp
            .json()
            .await
            .map_err(|e| MevClientError::BundleSubmission(format!("Jito parse failed: {e}")))?;

        if let Some(err) = jito_resp.error {
            return Err(MevClientError::BundleSubmission(format!(
                "Jito error {}: {}",
                err.code, err.message
            )));
        }

        let bundle_id = jito_resp
            .result
            .and_then(|r| {
                if let Some(arr) = r.as_array() {
                    arr.first().and_then(|v| v.as_str().map(|s| s.to_string()))
                } else {
                    r.as_str().map(|s| s.to_string())
                }
            })
            .unwrap_or_else(|| "unknown".to_string());

        info!(
            bundle_id = %bundle_id,
            tx_count = request.serialized_transactions.len(),
            tip_lamports = request.tip_lamports,
            "Jito bundle submitted"
        );

        Ok(BundleResult {
            bundle_hash: bundle_id,
            status: BundleStatus::Pending,
            tx_hashes: request.serialized_transactions.clone(),
            block_number: None,
            gas_used: None,
            effective_gas_price: None,
            submitted_at: chrono::Utc::now(),
        })
    }

    /// Check the status of a Jito bundle.
    pub async fn get_bundle_status(
        &self,
        bundle_id: &str,
    ) -> Result<BundleStatus, MevClientError> {
        let url = format!("{}/api/v1/bundles", self.block_engine_url);

        let body = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBundleStatuses",
            "params": [[bundle_id]]
        });

        let resp = self
            .http
            .post(&url)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| MevClientError::Relay(format!("Jito status check failed: {e}")))?;

        let data: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| MevClientError::Relay(format!("Jito status parse failed: {e}")))?;

        if let Some(result) = data.get("result") {
            if let Some(statuses) = result.get("value").and_then(|v| v.as_array()) {
                if let Some(status) = statuses.first() {
                    let state = status
                        .get("confirmation_status")
                        .and_then(|v| v.as_str())
                        .unwrap_or("pending");

                    return match state {
                        "confirmed" | "finalized" => Ok(BundleStatus::Included),
                        "failed" => Ok(BundleStatus::Failed),
                        _ => Ok(BundleStatus::Pending),
                    };
                }
            }
        }

        Ok(BundleStatus::Pending)
    }
}
