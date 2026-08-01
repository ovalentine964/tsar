//! PyO3 bridge for the gas optimizer.
//!
//! Exposes gas tracking, L2 comparison, and recommendations to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_gas_optimizer::chains::Chain;
use tsar_gas_optimizer::optimizer::{GasConfig, GasOptimizer};
use tsar_gas_optimizer::types::GasStrategy;

/// Python-visible gas optimizer.
#[pyclass(name = "GasOptimizer")]
pub struct PyGasOptimizer {
    optimizer: GasOptimizer,
}

#[pymethods]
impl PyGasOptimizer {
    /// Create a new gas optimizer.
    ///
    /// Args:
    ///     eth_rpc_url: Ethereum RPC URL for gas price queries.
    ///     eth_price_usd: Cached ETH price in USD.
    #[new]
    #[pyo3(signature = (eth_rpc_url="", eth_price_usd=2000.0))]
    fn new(eth_rpc_url: &str, eth_price_usd: f64) -> Self {
        let config = GasConfig {
            eth_rpc_url: eth_rpc_url.to_string(),
            eth_price_usd,
            ..Default::default()
        };
        Self {
            optimizer: GasOptimizer::new(config),
        }
    }

    /// Get a gas price recommendation.
    ///
    /// Args:
    ///     strategy: "economy", "standard", "fast", or "aggressive".
    ///
    /// Returns a dict with gas recommendation.
    #[pyo3(signature = (strategy="standard"))]
    fn get_recommendation(&self, strategy: &str) -> PyResult<PyObject> {
        let _ = parse_strategy(strategy)?;

        let result = RUNTIME.block_on(self.optimizer.get_recommendation())
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("strategy", result.strategy.to_string()).unwrap();
            dict.set_item("max_fee_gwei", result.max_fee_gwei).unwrap();
            dict.set_item("max_priority_fee_gwei", result.max_priority_fee_gwei).unwrap();
            dict.set_item("gas_price_gwei", result.gas_price_gwei).unwrap();
            dict.set_item("gas_limit", result.gas_limit).unwrap();
            dict.set_item("estimated_cost_eth", result.estimated_cost_eth).unwrap();
            dict.set_item("estimated_cost_usd", result.estimated_cost_usd).unwrap();
            dict.set_item("est_confirmation_secs", result.est_confirmation_secs).unwrap();
            dict.set_item("best_chain", &result.best_chain).unwrap();
            Ok(dict.into())
        })
    }

    /// Compare gas costs across L2 chains.
    ///
    /// Returns a list of dicts with chain comparisons.
    fn compare_chains(&self) -> PyResult<Vec<PyObject>> {
        let comparisons = RUNTIME.block_on(self.optimizer.compare_chains())
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;

        Python::with_gil(|py| {
            Ok(comparisons.iter().map(|c| {
                let dict = PyDict::new(py);
                dict.set_item("chain", &c.chain).unwrap();
                dict.set_item("chain_id", c.chain_id).unwrap();
                dict.set_item("swap_cost_usd", c.swap_cost_usd).unwrap();
                dict.set_item("swap_cost_native", c.swap_cost_native).unwrap();
                dict.set_item("native_token_price_usd", c.native_token_price_usd).unwrap();
                dict.set_item("est_confirmation_secs", c.est_confirmation_secs).unwrap();
                dict.set_item("is_eip1559", c.is_eip1559).unwrap();
                dict.set_item("security_level", c.security_level).unwrap();
                dict.into()
            }).collect())
        })
    }

    /// Get the gas price trend (positive = rising, negative = falling).
    fn trend(&self) -> f64 {
        self.optimizer.trend()
    }

    /// Predict the next block's base fee.
    fn predict_next_base_fee(&self) -> f64 {
        self.optimizer.predict_next_base_fee()
    }

    fn __repr__(&self) -> String {
        format!("GasOptimizer(trend={:.2})", self.optimizer.trend())
    }
}

fn parse_strategy(s: &str) -> PyResult<GasStrategy> {
    match s.to_lowercase().as_str() {
        "economy" => Ok(GasStrategy::Economy),
        "standard" => Ok(GasStrategy::Standard),
        "fast" => Ok(GasStrategy::Fast),
        "aggressive" => Ok(GasStrategy::Aggressive),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Invalid strategy: '{s}'. Use 'economy', 'standard', 'fast', or 'aggressive'"
        ))),
    }
}
