//! PyO3 bridge for the Oracle client.
//!
//! Exposes Chainlink price feeds, Pyth price feeds, price aggregation,
//! and TWAP computation to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_oracle_client::aggregator::{AggregatorConfig, PriceAggregator};
use tsar_oracle_client::chainlink::ChainlinkClient;
use tsar_oracle_client::pyth::PythClient;
use tsar_oracle_client::types::*;

/// Python-visible Oracle client for price feed reading.
#[pyclass(name = "OracleClient")]
pub struct PyOracleClient {
    chainlink: Option<ChainlinkClient>,
    pyth: PythClient,
    aggregator: PriceAggregator,
}

#[pymethods]
impl PyOracleClient {
    /// Create a new Oracle client.
    ///
    /// Args:
    ///     eth_rpc_url: Ethereum RPC URL for Chainlink feeds.
    ///     max_staleness_secs: Maximum acceptable data age (default: 3600).
    #[new]
    #[pyo3(signature = (eth_rpc_url="", max_staleness_secs=3600))]
    fn new(eth_rpc_url: &str, max_staleness_secs: u64) -> Self {
        let chainlink = if !eth_rpc_url.is_empty() {
            ChainlinkClient::new(eth_rpc_url, max_staleness_secs).ok()
        } else {
            None
        };

        Self {
            chainlink,
            pyth: PythClient::new(None),
            aggregator: PriceAggregator::new(AggregatorConfig::default()),
        }
    }

    /// Read a Chainlink price feed.
    ///
    /// Args:
    ///     feed_address: Chainlink aggregator contract address.
    ///     symbol: Token symbol for labeling.
    ///
    /// Returns a dict with price observation data.
    fn read_chainlink(&mut self, feed_address: &str, symbol: &str) -> PyResult<PyObject> {
        let chainlink = self.chainlink.as_ref()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Chainlink not configured (no RPC URL)"))?;

        let obs = RUNTIME.block_on(chainlink.read_feed(feed_address, symbol))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        self.aggregator.add_observation(obs.clone());

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("source", &obs.source).unwrap();
            dict.set_item("symbol", &obs.symbol).unwrap();
            dict.set_item("price_usd", obs.price_usd).unwrap();
            dict.set_item("confidence", obs.confidence).unwrap();
            dict.set_item("timestamp", obs.timestamp.to_rfc3339()).unwrap();
            Ok(dict.into())
        })
    }

    /// Read a Pyth price feed.
    ///
    /// Args:
    ///     price_id: Pyth price feed ID (hex).
    ///     symbol: Token symbol for labeling.
    ///
    /// Returns a dict with price observation data.
    fn read_pyth(&mut self, price_id: &str, symbol: &str) -> PyResult<PyObject> {
        let obs = RUNTIME.block_on(self.pyth.read_price(price_id, symbol))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        self.aggregator.add_observation(obs.clone());

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("source", &obs.source).unwrap();
            dict.set_item("symbol", &obs.symbol).unwrap();
            dict.set_item("price_usd", obs.price_usd).unwrap();
            dict.set_item("confidence", obs.confidence).unwrap();
            dict.set_item("timestamp", obs.timestamp.to_rfc3339()).unwrap();
            Ok(dict.into())
        })
    }

    /// Get aggregated price from all sources.
    ///
    /// Args:
    ///     symbol: Token symbol.
    ///
    /// Returns a dict with aggregated price data.
    fn get_aggregated_price(&mut self, symbol: &str) -> PyResult<PyObject> {
        let aggregated = self.aggregator.aggregate(symbol)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Insufficient data for aggregation"))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("symbol", &aggregated.symbol).unwrap();
            dict.set_item("price_usd", aggregated.price_usd).unwrap();
            dict.set_item("median_price_usd", aggregated.median_price_usd).unwrap();
            dict.set_item("mean_price_usd", aggregated.mean_price_usd).unwrap();
            dict.set_item("min_price_usd", aggregated.min_price_usd).unwrap();
            dict.set_item("max_price_usd", aggregated.max_price_usd).unwrap();
            dict.set_item("std_dev_usd", aggregated.std_dev_usd).unwrap();
            dict.set_item("source_count", aggregated.source_count).unwrap();
            dict.set_item("confidence", aggregated.confidence).unwrap();
            dict.set_item("aggregated_at", aggregated.aggregated_at.to_rfc3339()).unwrap();
            Ok(dict.into())
        })
    }

    /// Compute TWAP for a symbol.
    ///
    /// Args:
    ///     symbol: Token symbol.
    ///     window_secs: Time window in seconds.
    ///
    /// Returns the TWAP or None.
    fn twap(&self, symbol: &str, window_secs: i64) -> Option<f64> {
        self.aggregator.twap(symbol, window_secs)
    }

    /// Detect price deviations across sources.
    ///
    /// Args:
    ///     symbol: Token symbol.
    ///
    /// Returns a list of deviations.
    fn detect_deviations(&self, symbol: &str) -> Vec<PyObject> {
        let deviations = self.aggregator.detect_deviations(symbol);
        Python::with_gil(|py| {
            deviations.iter().map(|d| {
                let dict = PyDict::new(py);
                dict.set_item("symbol", &d.symbol).unwrap();
                dict.set_item("source", &d.source).unwrap();
                dict.set_item("deviating_price_usd", d.deviating_price_usd).unwrap();
                dict.set_item("median_price_usd", d.median_price_usd).unwrap();
                dict.set_item("deviation_bps", d.deviation_bps).unwrap();
                dict.into()
            }).collect()
        })
    }

    fn __repr__(&self) -> String {
        let cl = if self.chainlink.is_some() { "chainlink+pyth" } else { "pyth-only" };
        format!("OracleClient({})", cl)
    }
}
