//! Main EVM client combining signing, gas estimation, and transaction submission.

use ethers::providers::{Http, Middleware, Provider};
use ethers::types::{Address, TransactionReceipt as EthersReceipt, U256};
use tracing::{debug, info, warn};

use crate::gas::GasEstimator;
use crate::signer::TransactionSigner;
use crate::types::*;

/// High-level EVM client for DeFi interactions.
///
/// Combines transaction signing, gas estimation, and submission
/// into a single unified interface.
pub struct EvmClient {
    chain: ChainConfig,
    signer: TransactionSigner,
    gas_estimator: GasEstimator,
    provider: Provider<Http>,
}

impl EvmClient {
    /// Create a new EVM client.
    ///
    /// # Arguments
    /// * `config` - Chain configuration (RPC URL, chain ID, etc.)
    /// * `private_key` - Hex-encoded private key for signing
    /// * `eth_price_usd` - Current ETH price for gas cost estimation
    pub fn new(
        config: ChainConfig,
        private_key: &str,
        eth_price_usd: f64,
    ) -> Result<Self, EvmClientError> {
        let signer = TransactionSigner::new(private_key, config.chain_id)?;
        let gas_estimator = GasEstimator::new(&config.rpc_url, eth_price_usd)?;
        let provider = Provider::<Http>::try_from(&config.rpc_url)
            .map_err(|e| EvmClientError::Rpc(format!("Provider connect failed: {e}")))?;

        info!(
            chain = %config.name,
            chain_id = config.chain_id,
            address = %signer.address(),
            "EVM client initialized"
        );

        Ok(Self {
            chain: config,
            signer,
            gas_estimator,
            provider,
        })
    }

    /// Get the signer's address.
    pub fn address(&self) -> String {
        self.signer.address()
    }

    /// Estimate gas for a transaction.
    pub async fn estimate_gas(
        &self,
        to: &str,
        data: &str,
        value_wei: &str,
        speed: &str,
    ) -> Result<GasEstimate, EvmClientError> {
        self.gas_estimator.estimate(to, data, value_wei, speed).await
    }

    /// Sign and submit a transaction.
    ///
    /// Estimates gas, signs the transaction, submits it via RPC,
    /// and optionally waits for confirmation.
    ///
    /// # Arguments
    /// * `to` - Recipient address
    /// * `value_wei` - Value in wei
    /// * `data` - Calldata (hex, 0x-prefixed)
    /// * `speed` - Gas speed tier
    /// * `wait_for_confirmation` - Whether to wait for the receipt
    pub async fn send_transaction(
        &self,
        to: &str,
        value_wei: &str,
        data: &str,
        speed: &str,
        wait_for_confirmation: bool,
    ) -> Result<TransactionReceipt, EvmClientError> {
        // 1. Estimate gas
        let gas = self.gas_estimator.estimate(to, data, value_wei, speed).await?;

        // 2. Get nonce
        let address: Address = self
            .signer
            .address()
            .parse()
            .map_err(|_| EvmClientError::InvalidAddress(self.signer.address()))?;

        let nonce = self
            .provider
            .get_transaction_count(address, None)
            .await
            .map_err(|e| EvmClientError::Rpc(format!("Nonce fetch failed: {e}")))?;

        // 3. Build transaction
        let tx = TransactionRequest {
            to: to.to_string(),
            value: value_wei.to_string(),
            data: data.to_string(),
            chain_id: self.chain.chain_id,
            gas_limit: Some(gas.gas_limit),
            max_fee_per_gas: Some(format!("{}", gas.max_fee_per_gas_gwei * 1e9 as f64)),
            max_priority_fee_per_gas: Some(format!("{}", gas.max_priority_fee_gwei * 1e9 as f64)),
            nonce: Some(nonce.as_u64()),
        };

        // 4. Sign
        let signed = self.signer.sign_transaction(&tx).await?;

        // 5. Submit
        let tx_hash = self.submit_raw_transaction(&signed.raw_tx).await?;

        info!(tx_hash = %tx_hash, chain = %self.chain.name, "Transaction submitted");

        if !wait_for_confirmation {
            return Ok(TransactionReceipt {
                tx_hash,
                block_number: 0,
                block_hash: String::new(),
                gas_used: 0,
                effective_gas_price: String::new(),
                status: true,
                contract_address: None,
            });
        }

        // 6. Wait for receipt
        self.wait_for_receipt(&tx_hash).await
    }

    /// Submit a raw signed transaction to the network.
    async fn submit_raw_transaction(&self, raw_tx: &str) -> Result<String, EvmClientError> {
        let bytes = hex::decode(raw_tx.strip_prefix("0x").unwrap_or(raw_tx))
            .map_err(|e| EvmClientError::Rpc(format!("Invalid raw tx hex: {e}")))?;

        let tx_hash = self
            .provider
            .send_raw_transaction(bytes.into())
            .await
            .map_err(|e| EvmClientError::TransactionFailed(format!("Submit failed: {e}")))?;

        Ok(format!("{:?}", tx_hash))
    }

    /// Wait for a transaction receipt.
    async fn wait_for_receipt(&self, tx_hash: &str) -> Result<TransactionReceipt, EvmClientError> {
        let hash: ethers::types::H256 = tx_hash
            .parse()
            .map_err(|_| EvmClientError::InvalidAddress(format!("Invalid tx hash: {tx_hash}")))?;

        // Poll for receipt (simplified — production should use subscription)
        for _ in 0..60 {
            if let Some(receipt) = self
                .provider
                .get_transaction_receipt(hash)
                .await
                .map_err(|e| EvmClientError::Rpc(format!("Receipt fetch failed: {e}")))?
            {
                return Ok(TransactionReceipt {
                    tx_hash: format!("{:?}", receipt.transaction_hash),
                    block_number: receipt.block_number.unwrap_or_default().as_u64(),
                    block_hash: format!("{:?}", receipt.block_hash.unwrap_or_default()),
                    gas_used: receipt.gas_used.unwrap_or_default().as_u64(),
                    effective_gas_price: format!(
                        "{}",
                        receipt.effective_gas_price.unwrap_or_default()
                    ),
                    status: receipt.status.map(|s| s.as_u64() == 1).unwrap_or(true),
                    contract_address: receipt.contract_address.map(|a| format!("{a:?}")),
                });
            }

            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        }

        Err(EvmClientError::TransactionFailed(
            "Receipt timeout (120s)".to_string(),
        ))
    }
}
