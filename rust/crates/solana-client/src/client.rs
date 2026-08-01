//! Main Solana client combining signing, Jupiter swaps, and account reading.

use tracing::info;

use crate::account::AccountReader;
use crate::jupiter::JupiterClient;
use crate::signer::SolanaSigner;
use crate::types::*;

/// High-level Solana client for DeFi interactions.
pub struct SolanaClient {
    cluster: SolanaClusterConfig,
    signer: SolanaSigner,
    jupiter: JupiterClient,
    account_reader: AccountReader,
    sol_price_usd: f64,
}

impl SolanaClient {
    /// Create a new Solana client.
    ///
    /// # Arguments
    /// * `config` - Cluster configuration (RPC URL, etc.)
    /// * `secret_key` - Base58-encoded Ed25519 secret key
    /// * `sol_price_usd` - Current SOL price for fee estimation
    pub fn new(
        config: SolanaClusterConfig,
        secret_key: &str,
        sol_price_usd: f64,
    ) -> Result<Self, SolanaClientError> {
        let signer = SolanaSigner::from_base58(secret_key)?;
        let jupiter = JupiterClient::new(None);
        let account_reader = AccountReader::new(&config.rpc_url);

        info!(
            cluster = %config.name,
            pubkey = %signer.pubkey(),
            "Solana client initialized"
        );

        Ok(Self {
            cluster: config,
            signer,
            jupiter,
            account_reader,
            sol_price_usd,
        })
    }

    /// Get the signer's public key.
    pub fn pubkey(&self) -> String {
        self.signer.pubkey()
    }

    /// Build a Jupiter swap transaction.
    pub async fn build_swap(
        &self,
        input_mint: &str,
        output_mint: &str,
        amount: u64,
        slippage_bps: u16,
    ) -> Result<JupiterSwapResponse, SolanaClientError> {
        let request = JupiterSwapRequest {
            input_mint: input_mint.to_string(),
            output_mint: output_mint.to_string(),
            amount,
            slippage_bps,
            user_public_key: self.signer.pubkey(),
            wrap_unwrap_sol: true,
            priority_fee_lamports: Some(5000),
        };

        self.jupiter.build_swap(&request).await
    }

    /// Read a token account's info.
    pub fn get_token_account(&self, address: &str) -> Result<TokenAccountInfo, SolanaClientError> {
        self.account_reader.get_token_account(address)
    }

    /// Get all token accounts for the signer's wallet.
    pub fn get_my_token_accounts(&self) -> Result<Vec<TokenAccountInfo>, SolanaClientError> {
        self.account_reader.get_token_accounts_by_owner(&self.signer.pubkey())
    }

    /// Get SOL balance for the signer.
    pub fn get_balance(&self) -> Result<f64, SolanaClientError> {
        self.account_reader.get_sol_balance(&self.signer.pubkey())
    }

    /// Get a Jupiter quote (without building a full swap).
    pub async fn get_quote(
        &self,
        input_mint: &str,
        output_mint: &str,
        amount: u64,
        slippage_bps: u16,
    ) -> Result<serde_json::Value, SolanaClientError> {
        self.jupiter
            .get_quote(input_mint, output_mint, amount, slippage_bps)
            .await
    }
}
