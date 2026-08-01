//! PyO3 bridge for the MEV protection client.
//!
//! Exposes Flashbots bundle submission, Jito bundles, and
//! private mempool interaction to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_mev_client::flashbots::FlashbotsClient;
use tsar_mev_client::jito::JitoClient;
use tsar_mev_client::private_mempool::PrivateMempoolClient;
use tsar_mev_client::types::*;

/// Python-visible MEV protection client.
#[pyclass(name = "MevProtectionClient")]
pub struct PyMevProtectionClient {
    flashbots: FlashbotsClient,
    jito: JitoClient,
    private_mempool: PrivateMempoolClient,
}

#[pymethods]
impl PyMevProtectionClient {
    /// Create a new MEV protection client.
    ///
    /// Args:
    ///     flashbots_relay_url: Flashbots relay URL (default: https://relay.flashbots.net).
    ///     jito_block_engine_url: Jito block engine URL (default: https://mainnet.block-engine.jito.wtf).
    ///     flashbots_auth_key: Optional private key for Flashbots authentication.
    #[new]
    #[pyo3(signature = (flashbots_relay_url=None, jito_block_engine_url=None, flashbots_auth_key=None))]
    fn new(
        flashbots_relay_url: Option<&str>,
        jito_block_engine_url: Option<&str>,
        flashbots_auth_key: Option<String>,
    ) -> Self {
        Self {
            flashbots: FlashbotsClient::new(flashbots_relay_url, flashbots_auth_key),
            jito: JitoClient::new(jito_block_engine_url),
            private_mempool: PrivateMempoolClient::new(),
        }
    }

    /// Submit a Flashbots bundle on Ethereum.
    ///
    /// Args:
    ///     signed_transactions: List of hex-encoded signed transactions.
    ///     target_block: Target block number for inclusion.
    ///
    /// Returns a dict with bundle result.
    #[pyo3(signature = (signed_transactions, target_block))]
    fn send_flashbots_bundle(&self, signed_transactions: Vec<String>, target_block: u64) -> PyResult<PyObject> {
        let request = FlashbotsBundleRequest {
            signed_transactions,
            target_block,
            min_timestamp: None,
            max_timestamp: None,
            reverting_tx_hashes: vec![],
        };

        let result = RUNTIME.block_on(self.flashbots.send_bundle(&request))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| bundle_result_to_dict(py, &result))
    }

    /// Submit a Jito bundle on Solana.
    ///
    /// Args:
    ///     serialized_transactions: List of base58-encoded transactions.
    ///     tip_lamports: Tip amount in lamports for the Jito validator.
    ///
    /// Returns a dict with bundle result.
    #[pyo3(signature = (serialized_transactions, tip_lamports=10000))]
    fn send_jito_bundle(&self, serialized_transactions: Vec<String>, tip_lamports: u64) -> PyResult<PyObject> {
        let request = JitoBundleRequest {
            serialized_transactions,
            tip_lamports,
        };

        let result = RUNTIME.block_on(self.jito.send_bundle(&request))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| bundle_result_to_dict(py, &result))
    }

    /// Send a private transaction (bypass public mempool).
    ///
    /// Args:
    ///     signed_tx: Hex-encoded signed transaction.
    ///     chain_id: Chain ID (1 for Ethereum).
    ///
    /// Returns a dict with submission result.
    #[pyo3(signature = (signed_tx, chain_id=1))]
    fn send_private_transaction(&self, signed_tx: &str, chain_id: u64) -> PyResult<PyObject> {
        let tx = PrivateTransaction {
            signed_tx: signed_tx.to_string(),
            chain_id,
            max_block_number: None,
            preferences: None,
        };

        let result = RUNTIME.block_on(self.private_mempool.send_private_transaction(&tx))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| bundle_result_to_dict(py, &result))
    }

    /// Check Flashbots bundle status.
    ///
    /// Args:
    ///     bundle_hash: Bundle hash to check.
    ///     block_number: Target block number.
    fn get_flashbots_status(&self, bundle_hash: &str, block_number: u64) -> PyResult<String> {
        let status = RUNTIME.block_on(self.flashbots.get_bundle_status(bundle_hash, block_number))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Ok(status.to_string())
    }

    /// Check Jito bundle status.
    ///
    /// Args:
    ///     bundle_id: Bundle ID to check.
    fn get_jito_status(&self, bundle_id: &str) -> PyResult<String> {
        let status = RUNTIME.block_on(self.jito.get_bundle_status(bundle_id))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Ok(status.to_string())
    }

    fn __repr__(&self) -> String {
        "MevProtectionClient(flashbots+jito+private)".to_string()
    }
}

/// Convert a BundleResult to a Python dict.
fn bundle_result_to_dict(py: Python<'_>, result: &BundleResult) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("bundle_hash", &result.bundle_hash).unwrap();
    dict.set_item("status", result.status.to_string()).unwrap();
    dict.set_item("tx_hashes", &result.tx_hashes).unwrap();
    if let Some(block) = result.block_number {
        dict.set_item("block_number", block).unwrap();
    }
    if let Some(gas) = result.gas_used {
        dict.set_item("gas_used", gas).unwrap();
    }
    dict.set_item("submitted_at", result.submitted_at.to_rfc3339()).unwrap();
    Ok(dict.into())
}
