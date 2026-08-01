//! EIP-1559 gas estimation and fee calculation.
//!
//! Fetches current base fee from the network and computes optimal
//! maxFeePerGas and maxPriorityFeePerGas based on confirmation urgency.

use ethers::providers::{Http, Middleware, Provider};
use ethers::types::U256;
use std::str::FromStr;
use tracing::{debug, info};

use crate::types::{ChainConfig, EvmClientError, GasEstimate};

/// Gas estimator for EIP-1559 transactions.
pub struct GasEstimator {
    provider: Provider<Http>,
    eth_price_usd: f64,
}

impl GasEstimator {
    /// Create a new gas estimator.
    ///
    /// # Arguments
    /// * `rpc_url` - EVM RPC endpoint URL
    /// * `eth_price_usd` - Current ETH price in USD for cost estimation
    pub fn new(rpc_url: &str, eth_price_usd: f64) -> Result<Self, EvmClientError> {
        let provider = Provider::<Http>::try_from(rpc_url)
            .map_err(|e| EvmClientError::Rpc(format!("Failed to connect: {e}")))?;

        Ok(Self {
            provider,
            eth_price_usd,
        })
    }

    /// Estimate gas for a transaction with EIP-1559 fee parameters.
    ///
    /// Fetches the latest block to determine base fee, then applies
    /// a priority fee multiplier based on the desired speed tier.
    ///
    /// # Arguments
    /// * `to` - Recipient address
    /// * `data` - Calldata (hex-encoded, with 0x prefix)
    /// * `value_wei` - Value to send in wei
    /// * `speed` - "economy", "standard", "fast", or "aggressive"
    pub async fn estimate(
        &self,
        to: &str,
        data: &str,
        value_wei: &str,
        speed: &str,
    ) -> Result<GasEstimate, EvmClientError> {
        // Get latest block for base fee
        let block = self
            .provider
            .get_block(ethers::types::BlockNumber::Latest.into())
            .await
            .map_err(|e| EvmClientError::Rpc(format!("Block fetch failed: {e}")))?
            .ok_or_else(|| EvmClientError::Rpc("No latest block".to_string()))?;

        let base_fee = block
            .base_fee_per_gas
            .unwrap_or(U256::from(1_000_000_000u64)); // 1 gwei fallback

        let base_fee_gwei = base_fee.as_u128() as f64 / 1e9;

        // Priority fee based on speed tier
        let (priority_multiplier, est_blocks) = match speed {
            "economy" => (1.0, 10),
            "standard" => (1.2, 3),
            "fast" => (1.5, 1),
            "aggressive" => (2.0, 1),
            _ => (1.2, 3),
        };

        let base_priority_gwei = 1.5; // Base priority fee
        let priority_gwei = base_priority_gwei * priority_multiplier;

        // maxFeePerGas = baseFee * 2 + priorityFee (standard EIP-1559 formula)
        let max_fee_gwei = base_fee_gwei * 2.0 + priority_gwei;

        // Estimate gas limit via eth_estimateGas
        let gas_limit = self
            .estimate_gas_limit(to, data, value_wei)
            .await
            .unwrap_or(150_000); // Fallback gas limit

        // Calculate cost
        let cost_eth = (max_fee_gwei * gas_limit as f64) / 1e9;
        let cost_usd = cost_eth * self.eth_price_usd;

        debug!(
            base_fee_gwei,
            priority_gwei, max_fee_gwei, gas_limit, cost_eth, "Gas estimated"
        );

        Ok(GasEstimate {
            gas_limit,
            max_fee_per_gas_gwei: max_fee_gwei,
            max_priority_fee_gwei: priority_gwei,
            base_fee_gwei,
            estimated_cost_eth: cost_eth,
            estimated_cost_usd: cost_usd,
            eth_price_usd: self.eth_price_usd,
        })
    }

    /// Estimate gas limit for a transaction via eth_estimateGas.
    async fn estimate_gas_limit(
        &self,
        to: &str,
        data: &str,
        value_wei: &str,
    ) -> Result<u64, EvmClientError> {
        let to_addr: ethers::types::Address = to
            .parse()
            .map_err(|_| EvmClientError::InvalidAddress(to.to_string()))?;

        let value = U256::from_dec_str(value_wei).unwrap_or_else(|_| U256::zero());
        let calldata = hex::decode(data.strip_prefix("0x").unwrap_or(data))
            .map_err(|e| EvmClientError::AbiEncoding(format!("Invalid calldata: {e}")))?;

        let tx = ethers::types::TransactionRequest::new()
            .to(to_addr)
            .value(value)
            .data(calldata.into());

        let gas = self
            .provider
            .estimate_gas(&tx.into())
            .await
            .map_err(|e| EvmClientError::GasEstimation(format!("eth_estimateGas failed: {e}")))?;

        // Add 20% buffer
        Ok(gas.as_u64() * 120 / 100)
    }

    /// Get the current base fee from the latest block.
    pub async fn get_base_fee_gwei(&self) -> Result<f64, EvmClientError> {
        let block = self
            .provider
            .get_block(ethers::types::BlockNumber::Latest.into())
            .await
            .map_err(|e| EvmClientError::Rpc(format!("Block fetch failed: {e}")))?
            .ok_or_else(|| EvmClientError::Rpc("No latest block".to_string()))?;

        let base_fee = block
            .base_fee_per_gas
            .unwrap_or(U256::from(1_000_000_000u64));

        Ok(base_fee.as_u128() as f64 / 1e9)
    }

    /// Predict the next block's base fee using EIP-1559 algorithm.
    ///
    /// If the previous block was >50% full, base fee increases by up to 12.5%.
    /// If <50% full, it decreases by up to 12.5%.
    pub fn predict_next_base_fee(
        current_base_fee_gwei: f64,
        parent_gas_used: u64,
        parent_gas_limit: u64,
    ) -> f64 {
        let target = parent_gas_limit as f64 / 2.0;
        let used = parent_gas_used as f64;

        let delta = if used > target {
            // Increase base fee
            let ratio = (used - target) / target;
            current_base_fee_gwei * ratio.min(1.0) * 0.125
        } else {
            // Decrease base fee
            let ratio = (target - used) / target;
            -current_base_fee_gwei * ratio.min(1.0) * 0.125
        };

        (current_base_fee_gwei + delta).max(1.0) // Minimum 1 gwei
    }
}
