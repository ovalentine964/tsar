//! Jupiter V6 swap transaction building.
//!
//! Interfaces with the Jupiter Aggregator API to build optimized
//! swap transactions on Solana.

use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::{debug, info, warn};

use crate::types::*;

/// Jupiter API client for swap routing and transaction building.
pub struct JupiterClient {
    base_url: String,
    http: Client,
}

impl JupiterClient {
    /// Create a new Jupiter client.
    ///
    /// # Arguments
    /// * `base_url` - Jupiter API base URL (default: https://quote-api.jup.ag/v6)
    pub fn new(base_url: Option<&str>) -> Self {
        Self {
            base_url: base_url
                .unwrap_or("https://quote-api.jup.ag/v6")
                .to_string(),
            http: Client::new(),
        }
    }

    /// Get a swap quote from Jupiter.
    ///
    /// # Arguments
    /// * `input_mint` - Input token mint address
    /// * `output_mint` - Output token mint address
    /// * `amount` - Input amount in smallest unit (lamports for SOL)
    /// * `slippage_bps` - Slippage tolerance in basis points
    pub async fn get_quote(
        &self,
        input_mint: &str,
        output_mint: &str,
        amount: u64,
        slippage_bps: u16,
    ) -> Result<serde_json::Value, SolanaClientError> {
        let url = format!("{}/quote", self.base_url);

        let resp = self
            .http
            .get(&url)
            .query(&[
                ("inputMint", input_mint),
                ("outputMint", output_mint),
                ("amount", &amount.to_string()),
                ("slippageBps", &slippage_bps.to_string()),
            ])
            .send()
            .await
            .map_err(|e| SolanaClientError::JupiterApi(format!("Quote request failed: {e}")))?;

        let data: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| SolanaClientError::JupiterApi(format!("Quote parse failed: {e}")))?;

        if let Some(error) = data.get("error") {
            return Err(SolanaClientError::JupiterApi(format!(
                "Jupiter error: {error}"
            )));
        }

        debug!(
            input = input_mint,
            output = output_mint,
            amount,
            "Jupiter quote received"
        );

        Ok(data)
    }

    /// Build a swap transaction via Jupiter.
    ///
    /// Returns the serialized transaction ready for signing.
    ///
    /// # Arguments
    /// * `request` - Swap parameters including input/output mints, amount, and slippage
    pub async fn build_swap(
        &self,
        request: &JupiterSwapRequest,
    ) -> Result<JupiterSwapResponse, SolanaClientError> {
        let url = format!("{}/swap", self.base_url);

        // First get a quote
        let quote = self
            .get_quote(
                &request.input_mint,
                &request.output_mint,
                request.amount,
                request.slippage_bps,
            )
            .await?;

        // Build swap transaction
        let mut body = serde_json::json!({
            "quoteResponse": quote,
            "userPublicKey": request.user_public_key,
            "wrapAndUnwrapSol": request.wrap_unwrap_sol,
            "computeUnitPriceMicroLamports": request.priority_fee_lamports.unwrap_or(1000),
        });

        let resp = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .map_err(|e| SolanaClientError::JupiterApi(format!("Swap build failed: {e}")))?;

        let data: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| SolanaClientError::JupiterApi(format!("Swap parse failed: {e}")))?;

        if let Some(error) = data.get("error") {
            return Err(SolanaClientError::JupiterApi(format!(
                "Jupiter swap error: {error}"
            )));
        }

        let swap_tx = data["swapTransaction"]
            .as_str()
            .ok_or_else(|| {
                SolanaClientError::JupiterApi("Missing swapTransaction in response".to_string())
            })?
            .to_string();

        let last_valid = data["lastValidBlockHeight"]
            .as_u64()
            .unwrap_or(0);

        let priority_fee = data["prioritizationFeeLamports"]
            .as_u64()
            .unwrap_or(0);

        info!(
            input = %request.input_mint,
            output = %request.output_mint,
            "Jupiter swap transaction built"
        );

        Ok(JupiterSwapResponse {
            swap_transaction: swap_tx,
            last_valid_block_height: last_valid,
            prioritization_fee_lamports: priority_fee,
        })
    }
}
