//! PyO3 bridge for the DEX aggregator.
//!
//! Exposes multi-DEX quote comparison and route finding to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_dex_aggregator::aggregator::{AggregatorConfig, DexAggregator};
use tsar_dex_aggregator::types::DexSource;

/// Python-visible DEX aggregator.
#[pyclass(name = "DexAggregator")]
pub struct PyDexAggregator {
    aggregator: DexAggregator,
}

#[pymethods]
impl PyDexAggregator {
    /// Create a new DEX aggregator.
    ///
    /// Args:
    ///     chain: Chain name (e.g., "ethereum", "solana").
    ///     rpc_url: RPC URL for the chain.
    ///     oneinch_api_key: Optional 1inch API key.
    #[new]
    #[pyo3(signature = (chain="ethereum", rpc_url="", oneinch_api_key=None))]
    fn new(chain: &str, rpc_url: &str, oneinch_api_key: Option<&str>) -> Self {
        let config = AggregatorConfig {
            chain: chain.to_string(),
            rpc_url: rpc_url.to_string(),
            oneinch_api_key: oneinch_api_key.map(|s| s.to_string()),
            ..Default::default()
        };
        Self {
            aggregator: DexAggregator::new(config),
        }
    }

    /// Get quotes from all configured DEX sources.
    ///
    /// Args:
    ///     token_in: Token being sold (address or symbol).
    ///     token_out: Token being bought (address or symbol).
    ///     amount_in: Amount of token_in.
    ///
    /// Returns a dict with the best quote and comparison data.
    fn get_quotes(&self, token_in: &str, token_out: &str, amount_in: f64) -> PyResult<PyObject> {
        let comparison = RUNTIME.block_on(
            self.aggregator.get_quotes(token_in, token_out, amount_in)
        ).map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);

            // Best single source
            let best = PyDict::new(py);
            best.set_item("source", comparison.best_single.source.to_string()).unwrap();
            best.set_item("amount_out", comparison.best_single.amount_out).unwrap();
            best.set_item("price_impact_pct", comparison.best_single.price_impact_pct).unwrap();
            best.set_item("gas_cost_usd", comparison.best_single.gas_cost_usd).unwrap();
            best.set_item("net_output_usd", comparison.best_single.net_output_usd).unwrap();
            dict.set_item("best_single", best).unwrap();

            // All quotes
            let quotes: Vec<PyObject> = comparison.all_quotes.iter().map(|q| {
                let qdict = PyDict::new(py);
                qdict.set_item("source", q.source.to_string()).unwrap();
                qdict.set_item("amount_out", q.amount_out).unwrap();
                qdict.set_item("price_impact_pct", q.price_impact_pct).unwrap();
                qdict.set_item("gas_cost_usd", q.gas_cost_usd).unwrap();
                qdict.set_item("net_output_usd", q.net_output_usd).unwrap();
                qdict.into()
            }).collect();
            dict.set_item("all_quotes", quotes).unwrap();

            // Optimal route
            if let Some(ref route) = comparison.optimal_route {
                let route_dict = PyDict::new(py);
                route_dict.set_item("total_amount_out", route.total_amount_out).unwrap();
                route_dict.set_item("total_gas_usd", route.total_gas_usd).unwrap();
                route_dict.set_item("savings_vs_best_single_usd", route.savings_vs_best_single_usd).unwrap();
                dict.set_item("optimal_route", route_dict).unwrap();
            }

            dict.set_item("failed_sources", &comparison.failed_sources).unwrap();
            dict.set_item("fetch_time_ms", comparison.fetch_time_ms).unwrap();

            Ok(dict.into())
        })
    }

    fn __repr__(&self) -> String {
        "DexAggregator".to_string()
    }
}
