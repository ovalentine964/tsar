//! Transaction signing with ethers-rs local wallet.
//!
//! Supports EIP-1559 transactions with proper chain ID replay protection.

use ethers::core::types::{TransactionRequest as EthersTxRequest, H160, U256};
use ethers::signers::{LocalWallet, Signer};
use tracing::{debug, info};

use crate::types::{ChainConfig, EvmClientError, SignedTransaction, TransactionRequest};

/// Transaction signer using a local private key.
///
/// Wraps ethers-rs `LocalWallet` for deterministic transaction signing
/// with EIP-155 replay protection.
pub struct TransactionSigner {
    wallet: LocalWallet,
    chain_id: u64,
}

impl TransactionSigner {
    /// Create a new signer from a hex-encoded private key.
    ///
    /// # Arguments
    /// * `private_key` - Hex-encoded private key (with or without 0x prefix)
    /// * `chain_id` - EIP-155 chain ID for replay protection
    pub fn new(private_key: &str, chain_id: u64) -> Result<Self, EvmClientError> {
        let key = private_key.strip_prefix("0x").unwrap_or(private_key);
        let wallet: LocalWallet = key
            .parse::<LocalWallet>()
            .map_err(|e| EvmClientError::Signing(format!("Invalid private key: {e}")))?
            .with_chain_id(chain_id);

        info!(
            address = ?wallet.address(),
            chain_id,
            "Transaction signer initialized"
        );

        Ok(Self { wallet, chain_id })
    }

    /// Get the signer's Ethereum address.
    pub fn address(&self) -> String {
        format!("{:?}", self.wallet.address())
    }

    /// Sign a transaction request and return the raw signed bytes.
    ///
    /// # Arguments
    /// * `tx` - Transaction request with recipient, value, data, and gas params
    pub async fn sign_transaction(
        &self,
        tx: &TransactionRequest,
    ) -> Result<SignedTransaction, EvmClientError> {
        let to: H160 = tx
            .to
            .parse()
            .map_err(|_| EvmClientError::InvalidAddress(tx.to.clone()))?;

        let value = U256::from_dec_str(&tx.value)
            .unwrap_or_else(|_| U256::zero());

        let data = hex::decode(tx.data.strip_prefix("0x").unwrap_or(&tx.data))
            .map_err(|e| EvmClientError::AbiEncoding(format!("Invalid calldata: {e}")))?;

        let mut ethers_tx = EthersTxRequest::new()
            .to(to)
            .value(value)
            .data(data.into())
            .chain_id(tx.chain_id);

        if let Some(gas_limit) = tx.gas_limit {
            ethers_tx = ethers_tx.gas(gas_limit);
        }

        if let Some(ref max_fee) = tx.max_fee_per_gas {
            let fee = U256::from_dec_str(max_fee)
                .map_err(|e| EvmClientError::GasEstimation(format!("Invalid max_fee: {e}")))?;
            ethers_tx = ethers_tx.gas_price(fee);
        }

        let nonce = tx.nonce.unwrap_or(0);
        ethers_tx = ethers_tx.nonce(nonce);

        let signature = self
            .wallet
            .sign_transaction(&ethers_tx.clone().into())
            .await
            .map_err(|e| EvmClientError::Signing(format!("Signing failed: {e}")))?;

        let raw_tx = ethers_tx.rlp_signed(&signature);
        let raw_tx_hex = format!("0x{}", hex::encode(raw_tx.as_ref()));

        let tx_hash = format!("{:?}", ethers_tx.hash(&signature));

        debug!(tx_hash = %tx_hash, "Transaction signed");

        Ok(SignedTransaction {
            raw_tx: raw_tx_hex,
            tx_hash,
            chain_id: self.chain_id,
            nonce,
        })
    }

    /// Sign an EIP-1559 transaction with typed fee parameters.
    pub async fn sign_eip1559(
        &self,
        to: &str,
        value_wei: &str,
        data: &[u8],
        max_fee_per_gas: U256,
        max_priority_fee: U256,
        gas_limit: u64,
        nonce: u64,
    ) -> Result<SignedTransaction, EvmClientError> {
        use ethers::core::types::transaction::eip2718::TypedTransaction;
        use ethers::core::types::Eip1559TransactionRequest;

        let to_addr: H160 = to
            .parse()
            .map_err(|_| EvmClientError::InvalidAddress(to.to_string()))?;

        let value = U256::from_dec_str(value_wei).unwrap_or_else(|_| U256::zero());

        let eip1559_tx = Eip1559TransactionRequest::new()
            .to(to_addr)
            .value(value)
            .data(data.to_vec())
            .chain_id(self.chain_id)
            .gas(gas_limit)
            .max_fee_per_gas(max_fee_per_gas)
            .max_priority_fee_per_gas(max_priority_fee)
            .nonce(nonce);

        let typed_tx: TypedTransaction = eip1559_tx.into();

        let signature = self
            .wallet
            .sign_transaction(&typed_tx)
            .await
            .map_err(|e| EvmClientError::Signing(format!("EIP-1559 signing failed: {e}")))?;

        let raw_tx = typed_tx.rlp_signed(&signature);
        let raw_tx_hex = format!("0x{}", hex::encode(raw_tx.as_ref()));
        let tx_hash = format!("{:?}", typed_tx.hash(&signature));

        debug!(tx_hash = %tx_hash, "EIP-1559 transaction signed");

        Ok(SignedTransaction {
            raw_tx: raw_tx_hex,
            tx_hash,
            chain_id: self.chain_id,
            nonce,
        })
    }
}
