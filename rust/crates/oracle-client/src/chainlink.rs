//! Chainlink price feed reading via ethers-rs contract calls.
//!
//! Reads on-chain Chainlink aggregator contracts to fetch price data
//! with round ID tracking and staleness detection.

use ethers::providers::{Http, Middleware, Provider};
use ethers::types::{Address, U256};
use std::str::FromStr;
use tracing::{debug, info, warn};

use crate::types::*;

/// Chainlink price feed reader.
pub struct ChainlinkClient {
    provider: Provider<Http>,
    max_staleness_secs: u64,
}

impl ChainlinkClient {
    /// Create a new Chainlink client.
    ///
    /// # Arguments
    /// * `rpc_url` - EVM RPC endpoint
    /// * `max_staleness_secs` - Maximum acceptable data age in seconds
    pub fn new(rpc_url: &str, max_staleness_secs: u64) -> Result<Self, OracleClientError> {
        let provider = Provider::<Http>::try_from(rpc_url)
            .map_err(|e| OracleClientError::Rpc(format!("Provider connect failed: {e}")))?;

        Ok(Self {
            provider,
            max_staleness_secs,
        })
    }

    /// Read the latest round data from a Chainlink aggregator.
    ///
    /// Calls `latestRoundData()` and `decimals()` on the aggregator contract.
    ///
    /// # Arguments
    /// * `feed_address` - Chainlink aggregator contract address
    /// * `symbol` - Token symbol for labeling
    pub async fn read_feed(
        &self,
        feed_address: &str,
        symbol: &str,
    ) -> Result<PriceObservation, OracleClientError> {
        let addr: Address = Address::from_str(feed_address)
            .map_err(|_| OracleClientError::Rpc(format!("Invalid feed address: {feed_address}")))?;

        // Call latestRoundData()
        let round_data = self.call_latest_round_data(addr).await?;

        // Call decimals()
        let decimals = self.call_decimals(addr).await.unwrap_or(8);

        // Convert answer to price
        let price = round_data.answer as f64 / 10f64.powi(decimals as i32);

        // Check staleness
        let now = chrono::Utc::now().timestamp() as u64;
        if now > round_data.updated_at {
            let age = now - round_data.updated_at;
            if age > self.max_staleness_secs {
                warn!(
                    symbol,
                    age_secs = age,
                    max_staleness = self.max_staleness_secs,
                    "Chainlink data is stale"
                );
                return Err(OracleClientError::StaleData(format!(
                    "{symbol} data is {age}s old (max: {}s)",
                    self.max_staleness_secs
                )));
            }
        }

        debug!(
            symbol,
            price,
            round_id = round_data.round_id,
            updated_at = round_data.updated_at,
            "Chainlink feed read"
        );

        Ok(PriceObservation {
            source: "chainlink".to_string(),
            symbol: symbol.to_string(),
            price_usd: price,
            timestamp: chrono::DateTime::from_timestamp(round_data.updated_at as i64, 0)
                .unwrap_or_else(chrono::Utc::now),
            confidence: 0.99,
            decimals,
        })
    }

    /// Call `latestRoundData()` on a Chainlink aggregator.
    async fn call_latest_round_data(
        &self,
        address: Address,
    ) -> Result<ChainlinkRoundData, OracleClientError> {
        // Encode function selector for latestRoundData()
        // Selector: 0xfeaf968c
        let data = hex::decode("feaf968c").unwrap();

        let tx = ethers::types::TransactionRequest::new()
            .to(address)
            .data(data.into());

        let result = self
            .provider
            .call(&tx.into(), None)
            .await
            .map_err(|e| OracleClientError::Rpc(format!("latestRoundData call failed: {e}")))?;

        // Decode: (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)
        if result.len() < 160 {
            return Err(OracleClientError::Rpc(
                "latestRoundData response too short".to_string(),
            ));
        }

        let round_id = u64::from_be_bytes(result[24..32].try_into().unwrap());
        let answer = i128::from_be_bytes(result[56..72].try_into().unwrap());
        let started_at = u64::from_be_bytes(result[96..104].try_into().unwrap());
        let updated_at = u64::from_be_bytes(result[128..136].try_into().unwrap());
        let answered_in_round = u64::from_be_bytes(result[152..160].try_into().unwrap());

        Ok(ChainlinkRoundData {
            round_id,
            answer,
            started_at,
            updated_at,
            answered_in_round,
            decimals: 8, // Will be overridden by caller
        })
    }

    /// Call `decimals()` on a Chainlink aggregator.
    async fn call_decimals(&self, address: Address) -> Result<u8, OracleClientError> {
        // Selector: 0x313ce567
        let data = hex::decode("313ce567").unwrap();

        let tx = ethers::types::TransactionRequest::new()
            .to(address)
            .data(data.into());

        let result = self
            .provider
            .call(&tx.into(), None)
            .await
            .map_err(|e| OracleClientError::Rpc(format!("decimals call failed: {e}")))?;

        if result.is_empty() {
            return Ok(8); // Default Chainlink decimals
        }

        Ok(result[result.len() - 1])
    }
}
