//! Account data reading for Solana.
//!
//! Provides helpers for reading and deserializing on-chain account data,
//! including SPL token accounts.

use solana_client::rpc_client::RpcClient;
use solana_sdk::pubkey::Pubkey;
use std::str::FromStr;
use tracing::{debug, info};

use crate::types::*;

/// Account data reader for Solana.
pub struct AccountReader {
    rpc: RpcClient,
}

impl AccountReader {
    /// Create a new account reader.
    ///
    /// # Arguments
    /// * `rpc_url` - Solana RPC endpoint URL
    pub fn new(rpc_url: &str) -> Self {
        Self {
            rpc: RpcClient::new_with_commitment(
                rpc_url.to_string(),
                solana_sdk::commitment_config::CommitmentConfig::confirmed(),
            ),
        }
    }

    /// Read an SPL token account and return its info.
    ///
    /// # Arguments
    /// * `token_account` - The token account address (base58)
    pub fn get_token_account(
        &self,
        token_account: &str,
    ) -> Result<TokenAccountInfo, SolanaClientError> {
        let pubkey = Pubkey::from_str(token_account)
            .map_err(|_| SolanaClientError::AccountNotFound(format!("Invalid pubkey: {token_account}")))?;

        let account = self
            .rpc
            .get_account(&pubkey)
            .map_err(|e| SolanaClientError::Rpc(format!("Account fetch failed: {e}")))?;

        // SPL Token account layout:
        //   0..32: mint
        //   32..64: owner
        //   64..72: amount (u64 LE)
        //   72: delegate option
        //   ...
        //   165: close authority option (account data should be 165 bytes)
        if account.data.len() < 72 {
            return Err(SolanaClientError::AccountNotFound(
                "Account data too short for token account".to_string(),
            ));
        }

        let mint = Pubkey::try_from(&account.data[0..32])
            .map_err(|_| SolanaClientError::Rpc("Invalid mint bytes".to_string()))?;
        let owner = Pubkey::try_from(&account.data[32..64])
            .map_err(|_| SolanaClientError::Rpc("Invalid owner bytes".to_string()))?;
        let amount = u64::from_le_bytes(account.data[64..72].try_into().unwrap());

        // Get mint decimals
        let decimals = self.get_mint_decimals(&mint.to_string()).unwrap_or(9);
        let ui_amount = amount as f64 / 10f64.powi(decimals as i32);

        debug!(
            mint = %mint,
            owner = %owner,
            amount,
            decimals,
            "Token account read"
        );

        Ok(TokenAccountInfo {
            mint: mint.to_string(),
            owner: owner.to_string(),
            amount,
            decimals,
            ui_amount,
        })
    }

    /// Get the decimals for an SPL token mint.
    pub fn get_mint_decimals(&self, mint: &str) -> Result<u8, SolanaClientError> {
        let pubkey = Pubkey::from_str(mint)
            .map_err(|_| SolanaClientError::AccountNotFound(format!("Invalid mint: {mint}")))?;

        let account = self
            .rpc
            .get_account(&pubkey)
            .map_err(|e| SolanaClientError::Rpc(format!("Mint fetch failed: {e}")))?;

        // Mint layout: 44 bytes, decimals at offset 44
        if account.data.len() < 45 {
            return Err(SolanaClientError::AccountNotFound(
                "Mint data too short".to_string(),
            ));
        }

        Ok(account.data[44])
    }

    /// Get all token accounts owned by a wallet.
    pub fn get_token_accounts_by_owner(
        &self,
        owner: &str,
    ) -> Result<Vec<TokenAccountInfo>, SolanaClientError> {
        let owner_pubkey = Pubkey::from_str(owner)
            .map_err(|_| SolanaClientError::AccountNotFound(format!("Invalid owner: {owner}")))?;

        let result = self
            .rpc
            .get_token_accounts_by_owner(
                &owner_pubkey,
                solana_client::rpc_request::TokenAccountsFilter::ProgramId(
                    spl_token::ID,
                ),
            )
            .map_err(|e| SolanaClientError::Rpc(format!("Token accounts fetch failed: {e}")))?;

        let mut accounts = Vec::new();
        for keyed_account in result {
            let data = &keyed_account.account.data;
            if data.len() >= 72 {
                let mint = Pubkey::try_from(&data[0..32]).unwrap_or_default();
                let amount = u64::from_le_bytes(data[64..72].try_into().unwrap());
                let decimals = self.get_mint_decimals(&mint.to_string()).unwrap_or(9);
                let ui_amount = amount as f64 / 10f64.powi(decimals as i32);

                accounts.push(TokenAccountInfo {
                    mint: mint.to_string(),
                    owner: owner.to_string(),
                    amount,
                    decimals,
                    ui_amount,
                });
            }
        }

        info!(owner = %owner, count = accounts.len(), "Token accounts loaded");

        Ok(accounts)
    }

    /// Get the SOL balance for a wallet.
    pub fn get_sol_balance(&self, pubkey_str: &str) -> Result<f64, SolanaClientError> {
        let pubkey = Pubkey::from_str(pubkey_str)
            .map_err(|_| SolanaClientError::AccountNotFound(format!("Invalid pubkey: {pubkey_str}")))?;

        let lamports = self
            .rpc
            .get_balance(&pubkey)
            .map_err(|e| SolanaClientError::Rpc(format!("Balance fetch failed: {e}")))?;

        Ok(lamports as f64 / 1e9)
    }
}
