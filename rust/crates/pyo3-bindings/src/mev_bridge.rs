//! PyO3 bridge for the MEV scanner.
//!
//! Exposes mempool scanning and sandwich detection to Python.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_mev_scanner::detector::{DetectorConfig, SandwichDetector};
use tsar_mev_scanner::mempool::{MempoolConfig, MempoolScanner};
use tsar_mev_scanner::types::{MEVRisk, MEVRiskLevel, PendingSwap, SandwichPattern};

/// Python-visible MEV scanner wrapping mempool scanner + sandwich detector.
#[pyclass(name = "MEVScanner")]
pub struct PyMEVScanner {
    config: MempoolConfig,
    scanner: Option<MempoolScanner>,
    detector: SandwichDetector,
}

#[pymethods]
impl PyMEVScanner {
    /// Create a new MEV scanner.
    ///
    /// Args:
    ///     ws_rpc_url: Ethereum WebSocket RPC endpoint.
    ///     http_rpc_url: Ethereum HTTP RPC endpoint.
    ///     max_pending: Maximum pending transactions to track.
    #[new]
    #[pyo3(signature = (ws_rpc_url="", http_rpc_url="", max_pending=10000))]
    fn new(ws_rpc_url: &str, http_rpc_url: &str, max_pending: usize) -> Self {
        let config = MempoolConfig {
            ws_rpc_url: ws_rpc_url.to_string(),
            http_rpc_url: http_rpc_url.to_string(),
            max_pending,
            target_routers: Vec::new(),
            min_swap_value_usd: 100.0,
        };

        Self {
            config,
            scanner: None,
            detector: SandwichDetector::new(DetectorConfig::default()),
        }
    }

    /// Start the mempool scanner.
    ///
    /// Returns the number of known routers being monitored.
    fn start(&mut self) -> PyResult<usize> {
        let mut scanner = MempoolScanner::new(self.config.clone());
        let _rx = scanner.start();
        let router_count = scanner.pending_count();
        self.scanner = Some(scanner);
        Ok(router_count)
    }

    /// Stop the mempool scanner.
    fn stop(&mut self) -> PyResult<()> {
        if let Some(ref mut scanner) = self.scanner {
            RUNTIME.block_on(scanner.stop());
        }
        self.scanner = None;
        Ok(())
    }

    /// Get the number of currently tracked pending swaps.
    fn pending_count(&self) -> usize {
        self.scanner
            .as_ref()
            .map(|s| s.pending_count())
            .unwrap_or(0)
    }

    /// Check for sandwich attack patterns involving a specific transaction.
    ///
    /// Returns a list of detected patterns as dicts.
    fn check_sandwich(&self, tx_hash: &str) -> Vec<PyObject> {
        if let Some(pattern) = self.detector.get_pattern(tx_hash) {
            Python::with_gil(|py| vec![sandwich_pattern_to_dict(py, &pattern)])
        } else {
            Vec::new()
        }
    }

    /// Get all detected sandwich patterns.
    fn detected_sandwiches(&self) -> Vec<PyObject> {
        let patterns = self.detector.detected_patterns();
        Python::with_gil(|py| patterns.iter().map(|p| sandwich_pattern_to_dict(py, p)).collect())
    }

    /// Assess MEV risk for a proposed swap (simplified).
    ///
    /// Args:
    ///     pair: Trading pair (e.g., "WETH/USDC").
    ///     amount: Swap amount in base token.
    ///
    /// Returns a dict with risk assessment.
    fn assess_risk(&self, pair: &str, amount: f64) -> PyObject {
        let risk_score = self.calculate_risk_score(pair, amount);
        let risk_level = MEVRiskLevel::from_score(risk_score);
        let sandwich_count = self.detector.detected_patterns().len();

        Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("pair", pair).unwrap();
            dict.set_item("amount", amount).unwrap();
            dict.set_item("risk_level", risk_level.to_string()).unwrap();
            dict.set_item("risk_score", risk_score).unwrap();
            dict.set_item("sandwich_detected", sandwich_count > 0).unwrap();
            dict.set_item("pending_arbitrageurs", Vec::<String>::new()).unwrap();
            dict.set_item("estimated_mev_loss_usd", amount * risk_score * 0.01).unwrap();
            dict.set_item("gas_priority_gwei", 2.0).unwrap();
            dict.into()
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "MEVScanner(pending={}, sandwiches={})",
            self.pending_count(),
            self.detector.detected_patterns().len()
        )
    }
}

impl PyMEVScanner {
    fn calculate_risk_score(&self, _pair: &str, amount: f64) -> f64 {
        // Simplified risk scoring
        let base_risk = if amount > 100.0 {
            0.7
        } else if amount > 10.0 {
            0.4
        } else {
            0.1
        };

        let sandwich_risk = if !self.detector.detected_patterns().is_empty() {
            0.3
        } else {
            0.0
        };

        (base_risk + sandwich_risk).min(1.0)
    }
}

/// Convert a SandwichPattern to a Python dict.
fn sandwich_pattern_to_dict(py: Python<'_>, pattern: &SandwichPattern) -> PyObject {
    let dict = PyDict::new(py);
    dict.set_item("victim_tx", &pattern.victim_tx).unwrap();
    dict.set_item("frontrun_tx", &pattern.frontrun_tx).unwrap();
    dict.set_item("backrun_tx", &pattern.backrun_tx).unwrap();
    dict.set_item("attacker", &pattern.attacker).unwrap();
    dict.set_item("token_pair", &pattern.token_pair).unwrap();
    dict.set_item("estimated_profit_usd", pattern.estimated_profit_usd).unwrap();
    dict.set_item("estimated_victim_loss_usd", pattern.estimated_victim_loss_usd).unwrap();
    dict.set_item("confidence", pattern.confidence).unwrap();
    dict.set_item("detected_at", pattern.detected_at.to_rfc3339()).unwrap();
    dict.into()
}
