//! Flashbots bundle submission for Ethereum MEV protection.
//!
//! Submits transaction bundles directly to Flashbots relay,
//! bypassing the public mempool to prevent front-running.

use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::{debug, info, warn};

use crate::types::*;

/// Flashbots relay client for bundle submission.
pub struct FlashbotsClient {
    relay_url: String,
    http: Client,
    auth_signer: Option<String>,
}

#[derive(Serialize)]
struct FlashbotsSendBundleRequest {
    jsonrpc: String,
    id: u64,
    method: String,
    params: Vec<serde_json::Value>,
}

#[derive(Deserialize)]
struct FlashbotsResponse {
    result: Option<serde_json::Value>,
    error: Option<FlashbotsError>,
}

#[derive(Deserialize)]
struct FlashbotsError {
    code: i64,
    message: String,
}

impl FlashbotsClient {
    /// Create a new Flashbots client.
    ///
    /// # Arguments
    /// * `relay_url` - Flashbots relay URL (default: https://relay.flashbots.net)
    /// * `auth_signer` - Optional private key for Flashbots authentication
    pub fn new(relay_url: Option<&str>, auth_signer: Option<String>) -> Self {
        Self {
            relay_url: relay_url
                .unwrap_or("https://relay.flashbots.net")
                .to_string(),
            http: Client::new(),
            auth_signer,
        }
    }

    /// Submit a bundle of signed transactions to Flashbots.
    ///
    /// The bundle will be included in the target block if the miner
    /// accepts the bundle's payment.
    ///
    /// # Arguments
    /// * `request` - Bundle with signed transactions and target block
    pub async fn send_bundle(
        &self,
        request: &FlashbotsBundleRequest,
    ) -> Result<BundleResult, MevClientError> {
        let params = serde_json::json!([{
            "txs": request.signed_transactions,
            "blockNumber": format!("0x{:x}", request.target_block),
            "minTimestamp": request.min_timestamp.unwrap_or(0),
            "maxTimestamp": request.max_timestamp.unwrap_or(u64::MAX),
            "revertingTxHashes": request.reverting_tx_hashes,
        }]);

        let body = FlashbotsSendBundleRequest {
            jsonrpc: "2.0".to_string(),
            id: 1,
            method: "eth_sendBundle".to_string(),
            params: vec![params],
        };

        let resp = self
            .http
            .post(&self.relay_url)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| MevClientError::BundleSubmission(format!("Request failed: {e}")))?;

        let flash_resp: FlashbotsResponse = resp
            .json()
            .await
            .map_err(|e| MevClientError::BundleSubmission(format!("Response parse failed: {e}")))?;

        if let Some(err) = flash_resp.error {
            return Err(MevClientError::BundleSubmission(format!(
                "Flashbots error {}: {}",
                err.code, err.message
            )));
        }

        let bundle_hash = flash_resp
            .result
            .and_then(|r| r.get("bundleHash").cloned())
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .unwrap_or_else(|| "unknown".to_string());

        info!(
            bundle_hash = %bundle_hash,
            target_block = request.target_block,
            tx_count = request.signed_transactions.len(),
            "Flashbots bundle submitted"
        );

        Ok(BundleResult {
            bundle_hash,
            status: BundleStatus::Pending,
            tx_hashes: request.signed_transactions.clone(),
            block_number: Some(request.target_block),
            gas_used: None,
            effective_gas_price: None,
            submitted_at: chrono::Utc::now(),
        })
    }

    /// Check the status of a previously submitted bundle.
    pub async fn get_bundle_status(
        &self,
        bundle_hash: &str,
        block_number: u64,
    ) -> Result<BundleStatus, MevClientError> {
        let body = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "flashbots_getBundleStats",
            "params": [{
                "bundleHash": bundle_hash,
                "blockNumber": format!("0x{:x}", block_number),
            }]
        });

        let resp = self
            .http
            .post(&self.relay_url)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| MevClientError::Relay(format!("Status check failed: {e}")))?;

        let data: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| MevClientError::Relay(format!("Status parse failed: {e}")))?;

        // Check if bundle was seen by miners
        if let Some(result) = data.get("result") {
            if let Some(is_high_priority) = result.get("isHighPriority") {
                if is_high_priority.as_bool().unwrap_or(false) {
                    return Ok(BundleStatus::Included);
                }
            }
        }

        Ok(BundleStatus::Pending)
    }

    /// Simulate a bundle to check if it would be included.
    pub async fn simulate_bundle(
        &self,
        request: &FlashbotsBundleRequest,
        block_number: u64,
    ) -> Result<serde_json::Value, MevClientError> {
        let body = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "flashbots_simulateBundle",
            "params": [{
                "txs": request.signed_transactions,
                "blockNumber": format!("0x{:x}", block_number),
                "timestamp": request.max_timestamp.unwrap_or(0),
            }]
        });

        let resp = self
            .http
            .post(&self.relay_url)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| MevClientError::BundleSubmission(format!("Simulation failed: {e}")))?;

        let data: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| MevClientError::BundleSubmission(format!("Simulation parse failed: {e}")))?;

        debug!(block_number, "Bundle simulated");

        Ok(data)
    }
}
