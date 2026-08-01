//! PyO3 bridge for the Solana client.
//!
//! Exposes Ed25519 signing, Jupiter swaps, and account reading to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_solana_client::account::AccountReader;
use tsar_solana_client::client::SolanaClient;
use tsar_solana_client::jupiter::JupiterClient;
use tsar_solana_client::signer::SolanaSigner;
use tsar_solana_client::types::*;

/// Python-visible Solana client for blockchain interactions.
#[pyclass(name = "SolanaClient")]
pub struct PySolanaClient {
    client: Option<SolanaClient>,
    rpc_url: String,
    secret_key: String,
    sol_price_usd: f64,
}

#[pymethods]
impl PySolanaClient {
    /// Create a new Solana client.
    ///
    /// Args:
    ///     rpc_url: Solana RPC endpoint URL.
    ///     secret_key: Base58-encoded Ed25519 secret key.
    ///     sol_price_usd: Current SOL price for fee estimation.
    #[new]
    #[pyo3(signature = (rpc_url, secret_key, sol_price_usd=150.0))]
    fn new(rpc_url: &str, secret_key: &str, sol_price_usd: f64) -> Self {
        Self {
            client: None,
            rpc_url: rpc_url.to_string(),
            secret_key: secret_key.to_string(),
            sol_price_usd,
        }
    }

    /// Initialize the Solana client connection.
    fn connect(&mut self) -> PyResult<()> {
        let config = SolanaClusterConfig {
            rpc_url: self.rpc_url.clone(),
            ..Default::default()
        };

        let client = SolanaClient::new(config, &self.secret_key, self.sol_price_usd)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        self.client = Some(client);
        Ok(())
    }

    /// Get the signer's public key.
    fn pubkey(&self) -> PyResult<String> {
        self.client
            .as_ref()
            .map(|c| c.pubkey())
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))
    }

    /// Build a Jupiter swap transaction.
    ///
    /// Args:
    ///     input_mint: Input token mint address.
    ///     output_mint: Output token mint address.
    ///     amount: Input amount in smallest unit (lamports for SOL).
    ///     slippage_bps: Slippage tolerance in basis points.
    ///
    /// Returns a dict with swap transaction data.
    #[pyo3(signature = (input_mint, output_mint, amount, slippage_bps=50))]
    fn build_swap(&self, input_mint: &str, output_mint: &str, amount: u64, slippage_bps: u16) -> PyResult<PyObject> {
        let client = self.client.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))?;

        let resp = RUNTIME.block_on(client.build_swap(input_mint, output_mint, amount, slippage_bps))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("swap_transaction", &resp.swap_transaction).unwrap();
            dict.set_item("last_valid_block_height", resp.last_valid_block_height).unwrap();
            dict.set_item("prioritization_fee_lamports", resp.prioritization_fee_lamports).unwrap();
            Ok(dict.into())
        })
    }

    /// Get a Jupiter quote without building a full swap.
    ///
    /// Args:
    ///     input_mint: Input token mint.
    ///     output_mint: Output token mint.
    ///     amount: Amount in smallest unit.
    ///     slippage_bps: Slippage in basis points.
    #[pyo3(signature = (input_mint, output_mint, amount, slippage_bps=50))]
    fn get_quote(&self, input_mint: &str, output_mint: &str, amount: u64, slippage_bps: u16) -> PyResult<PyObject> {
        let client = self.client.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))?;

        let quote = RUNTIME.block_on(client.get_quote(input_mint, output_mint, amount, slippage_bps))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            // Convert serde_json::Value to PyObject
            let json_str = serde_json::to_string(&quote).unwrap_or_default();
            let module = py.import("json").unwrap();
            let obj = module.call_method1("loads", (json_str,)).unwrap();
            Ok(obj.into())
        })
    }

    /// Read a token account's info.
    ///
    /// Args:
    ///     token_account: Token account address (base58).
    fn get_token_account(&self, token_account: &str) -> PyResult<PyObject> {
        let client = self.client.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))?;

        // Use account reader directly
        let reader = AccountReader::new(&self.rpc_url);
        let info = reader.get_token_account(token_account)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("mint", &info.mint).unwrap();
            dict.set_item("owner", &info.owner).unwrap();
            dict.set_item("amount", info.amount).unwrap();
            dict.set_item("decimals", info.decimals).unwrap();
            dict.set_item("ui_amount", info.ui_amount).unwrap();
            Ok(dict.into())
        })
    }

    /// Get all token accounts for the signer's wallet.
    fn get_my_token_accounts(&self) -> PyResult<Vec<PyObject>> {
        let client = self.client.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))?;

        let accounts = client.get_my_token_accounts()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            Ok(accounts.iter().map(|info| {
                let dict = PyDict::new(py);
                dict.set_item("mint", &info.mint).unwrap();
                dict.set_item("owner", &info.owner).unwrap();
                dict.set_item("amount", info.amount).unwrap();
                dict.set_item("decimals", info.decimals).unwrap();
                dict.set_item("ui_amount", info.ui_amount).unwrap();
                dict.into()
            }).collect())
        })
    }

    /// Get SOL balance for the signer.
    fn get_balance(&self) -> PyResult<f64> {
        let client = self.client.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))?;

        client.get_balance()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    fn __repr__(&self) -> String {
        let connected = if self.client.is_some() { "connected" } else { "disconnected" };
        format!("SolanaClient({})", connected)
    }
}
