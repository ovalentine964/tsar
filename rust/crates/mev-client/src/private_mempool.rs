//! Private mempool interaction for MEV protection.
//!
//! Provides interfaces for submitting transactions to private mempools
//! (Flashbots Protect, MEV Blocker, etc.) to avoid front-running.

use reqwest::Client;
use tracing::{debug, info, warn};

use crate::types::*;

/// Private mempool client for MEV-protected transaction submission.
pub struct PrivateMempoolClient {
    http: Client,
    endpoints: Vec<PrivateEndpoint>,
}

/// A private mempool endpoint.
#[derive(Debug, Clone)]
struct PrivateEndpoint {
    name: String,
    url: String,
    chain_id: u64,
}

impl PrivateMempoolClient {
    /// Create a new private mempool client with default endpoints.
    pub fn new() -> Self {
        let endpoints = vec![
            PrivateEndpoint {
                name: "Flashbots Protect".to_string(),
                url: "https://protect.flashbots.net".to_string(),
                chain_id: 1,
            },
            PrivateEndpoint {
                name: "MEV Blocker".to_string(),
                url: "https://rpc.mevblocker.io".to_string(),
                chain_id: 1,
            },
        ];

        Self {
            http: Client::new(),
            endpoints,
        }
    }

    /// Submit a transaction to a private mempool.
    ///
    /// # Arguments
    /// * `tx` - Private transaction with signed raw bytes
    pub async fn send_private_transaction(
        &self,
        tx: &PrivateTransaction,
    ) -> Result<BundleResult, MevClientError> {
        // Find matching endpoint
        let endpoint = self
            .endpoints
            .iter()
            .find(|e| e.chain_id == tx.chain_id)
            .ok_or_else(|| {
                MevClientError::InvalidTransaction(format!(
                    "No private mempool for chain {}",
                    tx.chain_id
                ))
            })?;

        let body = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_sendRawTransaction",
            "params": [tx.signed_tx]
        });

        let resp = self
            .http
            .post(&endpoint.url)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| MevClientError::BundleSubmission(format!("Private tx failed: {e}")))?;

        let data: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| MevClientError::BundleSubmission(format!("Response parse failed: {e}")))?;

        let tx_hash = data
            .get("result")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();

        if let Some(err) = data.get("error") {
            return Err(MevClientError::BundleSubmission(format!(
                "Private mempool error: {}",
                err
            )));
        }

        info!(
            tx_hash = %tx_hash,
            endpoint = %endpoint.name,
            "Private transaction submitted"
        );

        Ok(BundleResult {
            bundle_hash: tx_hash.clone(),
            status: BundleStatus::Pending,
            tx_hashes: vec![tx_hash],
            block_number: None,
            gas_used: None,
            effective_gas_price: None,
            submitted_at: chrono::Utc::now(),
        })
    }

    /// Add a custom private mempool endpoint.
    pub fn add_endpoint(&mut self, name: &str, url: &str, chain_id: u64) {
        self.endpoints.push(PrivateEndpoint {
            name: name.to_string(),
            url: url.to_string(),
            chain_id,
        });
    }
}
