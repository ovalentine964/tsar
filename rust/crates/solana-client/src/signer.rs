//! Ed25519 transaction signing for Solana.
//!
//! Uses solana-sdk keypair for deterministic transaction signing
//! with Ed25519 signatures.

use solana_sdk::{
    pubkey::Pubkey,
    signature::{Keypair, Signature},
    signer::Signer,
    transaction::Transaction,
};
use std::str::FromStr;
use tracing::{debug, info};

use crate::types::SolanaClientError;

/// Solana transaction signer using Ed25519 keypairs.
pub struct SolanaSigner {
    keypair: Keypair,
}

impl SolanaSigner {
    /// Create a signer from a base58-encoded secret key.
    ///
    /// # Arguments
    /// * `secret_key` - Base58-encoded Ed25519 secret key (64 bytes)
    pub fn from_base58(secret_key: &str) -> Result<Self, SolanaClientError> {
        let bytes = bs58::decode(secret_key)
            .into_vec()
            .map_err(|e| SolanaClientError::InvalidKeypair(format!("Base58 decode failed: {e}")))?;

        let keypair = Keypair::from_bytes(&bytes)
            .map_err(|e| SolanaClientError::InvalidKeypair(format!("Invalid keypair bytes: {e}")))?;

        info!(pubkey = %keypair.pubkey(), "Solana signer initialized");

        Ok(Self { keypair })
    }

    /// Create a signer from raw bytes (64 bytes: 32 secret + 32 public).
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, SolanaClientError> {
        let keypair = Keypair::from_bytes(bytes)
            .map_err(|e| SolanaClientError::InvalidKeypair(format!("Invalid bytes: {e}")))?;

        Ok(Self { keypair })
    }

    /// Get the signer's public key as a base58 string.
    pub fn pubkey(&self) -> String {
        self.keypair.pubkey().to_string()
    }

    /// Get the signer's public key as a Pubkey.
    pub fn pubkey_bytes(&self) -> Pubkey {
        self.keypair.pubkey()
    }

    /// Sign a Solana transaction.
    ///
    /// Signs the transaction with the signer's keypair.
    /// The transaction must already have a recent blockhash set.
    pub fn sign_transaction(&self, tx: &mut Transaction) -> Result<Signature, SolanaClientError> {
        tx.try_sign(&[&self.keypair], tx.message.recent_blockhash)
            .map_err(|e| SolanaClientError::Signing(format!("Transaction signing failed: {e}")))?;

        let sig = tx.signatures[0];
        debug!(signature = %sig, "Transaction signed");

        Ok(sig)
    }

    /// Sign and serialize a transaction to base58.
    pub fn sign_and_serialize(&self, tx: &mut Transaction) -> Result<String, SolanaClientError> {
        self.sign_transaction(tx)?;

        let serialized = bincode::serialize(tx)
            .map_err(|e| SolanaClientError::Signing(format!("Serialization failed: {e}")))?;

        Ok(bs58::encode(serialized).into_string())
    }

    /// Sign a message (arbitrary bytes) with Ed25519.
    pub fn sign_message(&self, message: &[u8]) -> Signature {
        self.keypair.sign_message(message)
    }
}
