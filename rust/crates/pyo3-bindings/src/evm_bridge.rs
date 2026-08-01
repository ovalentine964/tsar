//! PyO3 bridge for the EVM client.
//!
//! Exposes transaction signing, ABI encoding, gas estimation, and
//! EVM client operations to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_evm_client::abi;
use tsar_evm_client::client::EvmClient;
use tsar_evm_client::gas::GasEstimator;
use tsar_evm_client::signer::TransactionSigner;
use tsar_evm_client::types::*;

/// Python-visible EVM client for blockchain interactions.
#[pyclass(name = "EvmClient")]
pub struct PyEvmClient {
    client: Option<EvmClient>,
    rpc_url: String,
    chain_id: u64,
    private_key: String,
    eth_price_usd: f64,
}

#[pymethods]
impl PyEvmClient {
    /// Create a new EVM client.
    ///
    /// Args:
    ///     rpc_url: EVM RPC endpoint URL.
    ///     private_key: Hex-encoded private key for signing.
    ///     chain_id: EIP-155 chain ID (default: 1 for Ethereum).
    ///     eth_price_usd: Current ETH price for gas estimation.
    #[new]
    #[pyo3(signature = (rpc_url, private_key, chain_id=1, eth_price_usd=2000.0))]
    fn new(rpc_url: &str, private_key: &str, chain_id: u64, eth_price_usd: f64) -> Self {
        Self {
            client: None,
            rpc_url: rpc_url.to_string(),
            chain_id,
            private_key: private_key.to_string(),
            eth_price_usd,
        }
    }

    /// Initialize the EVM client connection.
    fn connect(&mut self) -> PyResult<()> {
        let config = ChainConfig {
            chain_id: self.chain_id,
            name: format!("chain-{}", self.chain_id),
            rpc_url: self.rpc_url.clone(),
            ..Default::default()
        };

        let client = EvmClient::new(config, &self.private_key, self.eth_price_usd)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        self.client = Some(client);
        Ok(())
    }

    /// Get the signer's Ethereum address.
    fn address(&self) -> PyResult<String> {
        self.client
            .as_ref()
            .map(|c| c.address())
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))
    }

    /// Estimate gas for a transaction.
    ///
    /// Args:
    ///     to: Recipient address.
    ///     data: Calldata (hex string).
    ///     value_wei: Value in wei.
    ///     speed: Speed tier ("economy", "standard", "fast", "aggressive").
    ///
    /// Returns a dict with gas estimate details.
    #[pyo3(signature = (to, data="", value_wei="0", speed="standard"))]
    fn estimate_gas(&self, to: &str, data: &str, value_wei: &str, speed: &str) -> PyResult<PyObject> {
        let client = self.client.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))?;

        let estimate = RUNTIME.block_on(client.estimate_gas(to, data, value_wei, speed))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("gas_limit", estimate.gas_limit).unwrap();
            dict.set_item("max_fee_per_gas_gwei", estimate.max_fee_per_gas_gwei).unwrap();
            dict.set_item("max_priority_fee_gwei", estimate.max_priority_fee_gwei).unwrap();
            dict.set_item("base_fee_gwei", estimate.base_fee_gwei).unwrap();
            dict.set_item("estimated_cost_eth", estimate.estimated_cost_eth).unwrap();
            dict.set_item("estimated_cost_usd", estimate.estimated_cost_usd).unwrap();
            Ok(dict.into())
        })
    }

    /// Sign a transaction and return the raw signed bytes.
    ///
    /// Args:
    ///     to: Recipient address.
    ///     value_wei: Value in wei.
    ///     data: Calldata (hex string).
    ///
    /// Returns a dict with raw_tx and tx_hash.
    #[pyo3(signature = (to, value_wei="0", data=""))]
    fn sign_transaction(&self, to: &str, value_wei: &str, data: &str) -> PyResult<PyObject> {
        let client = self.client.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))?;

        let tx = TransactionRequest {
            to: to.to_string(),
            value: value_wei.to_string(),
            data: data.to_string(),
            chain_id: self.chain_id,
            gas_limit: Some(150_000),
            max_fee_per_gas: None,
            max_priority_fee_per_gas: None,
            nonce: None,
        };

        // Create a temporary signer for signing
        let signer = TransactionSigner::new(&self.private_key, self.chain_id)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        let signed = RUNTIME.block_on(signer.sign_transaction(&tx))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("raw_tx", &signed.raw_tx).unwrap();
            dict.set_item("tx_hash", &signed.tx_hash).unwrap();
            dict.set_item("chain_id", signed.chain_id).unwrap();
            dict.set_item("nonce", signed.nonce).unwrap();
            Ok(dict.into())
        })
    }

    /// Send a transaction (sign + submit + optionally wait for confirmation).
    ///
    /// Args:
    ///     to: Recipient address.
    ///     value_wei: Value in wei.
    ///     data: Calldata (hex string).
    ///     speed: Gas speed tier.
    ///     wait: Whether to wait for confirmation.
    ///
    /// Returns a dict with transaction receipt details.
    #[pyo3(signature = (to, value_wei="0", data="", speed="standard", wait=false))]
    fn send_transaction(&self, to: &str, value_wei: &str, data: &str, speed: &str, wait: bool) -> PyResult<PyObject> {
        let client = self.client.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Client not connected"))?;

        let receipt = RUNTIME.block_on(client.send_transaction(to, value_wei, data, speed, wait))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("tx_hash", &receipt.tx_hash).unwrap();
            dict.set_item("block_number", receipt.block_number).unwrap();
            dict.set_item("gas_used", receipt.gas_used).unwrap();
            dict.set_item("status", receipt.status).unwrap();
            if let Some(ref addr) = receipt.contract_address {
                dict.set_item("contract_address", addr).unwrap();
            }
            Ok(dict.into())
        })
    }

    fn __repr__(&self) -> String {
        let connected = if self.client.is_some() { "connected" } else { "disconnected" };
        format!("EvmClient(chain_id={}, {})", self.chain_id, connected)
    }
}

/// Encode a Uniswap V3 exactInputSingle swap call.
#[pyfunction]
pub fn encode_uniswap_v3_swap_py(
    token_in: &str,
    token_out: &str,
    fee: u32,
    recipient: &str,
    deadline: u64,
    amount_in: &str,
    amount_out_minimum: &str,
) -> PyResult<String> {
    let encoded = abi::encode_uniswap_v3_exact_input_single(
        token_in, token_out, fee, recipient, deadline,
        amount_in, amount_out_minimum, "0",
    )
    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    Ok(format!("0x{}", hex::encode(encoded)))
}

/// Encode a Chainlink latestRoundData call.
#[pyfunction]
pub fn encode_chainlink_round_data_py() -> String {
    let encoded = abi::encode_chainlink_latest_round_data();
    format!("0x{}", hex::encode(encoded))
}
