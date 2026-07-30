//! PyO3 bridge for the order executor.
//!
//! Exposes the order executor and its tracking capabilities to Python.
//! All async operations use the shared global tokio runtime.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::runtime::RUNTIME;
use tsar_order_executor::client::BinanceConfig;
use tsar_order_executor::executor::{ExecutionMode, OrderExecutor};
use tsar_order_executor::types::{OrderRequest, TimeInForce};
use tsar_core::types::{OrderSide, OrderStatus, OrderType};

/// Python-visible order executor.
///
/// Provides order placement, cancellation, and status tracking.
/// Supports both paper and live trading modes.
#[pyclass(name = "OrderExecutor")]
pub struct PyOrderExecutor {
    inner: OrderExecutor,
}

#[pymethods]
impl PyOrderExecutor {
    /// Create a new paper-trading order executor.
    #[new]
    #[pyo3(signature = (mode="paper", api_key=None, api_secret=None, testnet=true))]
    fn new(
        mode: &str,
        api_key: Option<String>,
        api_secret: Option<String>,
        testnet: bool,
    ) -> PyResult<Self> {
        let inner = match mode {
            "paper" => OrderExecutor::new(),
            "live" => {
                let key = api_key.ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err(
                        "api_key required for live mode",
                    )
                })?;
                let secret = api_secret.ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err(
                        "api_secret required for live mode",
                    )
                })?;
                let config = if testnet {
                    BinanceConfig::testnet(key, secret)
                } else {
                    BinanceConfig::mainnet(key, secret)
                };
                OrderExecutor::live(config).map_err(|e| {
                    pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
                })?
            }
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "Invalid mode: '{mode}'. Use 'paper' or 'live'"
                )));
            }
        };

        Ok(Self { inner })
    }

    /// Get the current execution mode.
    fn mode(&self) -> &str {
        match self.inner.mode() {
            ExecutionMode::Paper => "paper",
            ExecutionMode::Live => "live",
        }
    }

    /// Place a market order.
    ///
    /// Parameters:
    ///   - symbol: Trading pair (e.g., "BTC/USDT")
    ///   - side: "buy" or "sell"
    ///   - quantity: Amount to trade
    ///   - strategy: Optional strategy name for tracking
    ///
    /// Returns a dict with order details.
    #[pyo3(signature = (symbol, side, quantity, strategy=None))]
    fn place_market_order(
        &mut self,
        symbol: &str,
        side: &str,
        quantity: f64,
        strategy: Option<&str>,
    ) -> PyResult<PyObject> {
        let order_side = parse_side(side)?;
        let mut request = OrderRequest::market(symbol, order_side, quantity);
        request.strategy = strategy.map(|s| s.to_string());

        let result = RUNTIME
            .block_on(self.inner.place_order(&request))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| order_result_to_dict(py, &result))
    }

    /// Place a limit order.
    ///
    /// Parameters:
    ///   - symbol: Trading pair
    ///   - side: "buy" or "sell"
    ///   - quantity: Amount to trade
    ///   - price: Limit price
    ///   - strategy: Optional strategy name
    ///
    /// Returns a dict with order details.
    #[pyo3(signature = (symbol, side, quantity, price, strategy=None))]
    fn place_limit_order(
        &mut self,
        symbol: &str,
        side: &str,
        quantity: f64,
        price: f64,
        strategy: Option<&str>,
    ) -> PyResult<PyObject> {
        let order_side = parse_side(side)?;
        let mut request = OrderRequest::limit(symbol, order_side, quantity, price);
        request.strategy = strategy.map(|s| s.to_string());

        let result = RUNTIME
            .block_on(self.inner.place_order(&request))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| order_result_to_dict(py, &result))
    }

    /// Cancel an order by exchange order ID.
    ///
    /// Returns True if cancellation was successful.
    fn cancel_order(&mut self, order_id: &str, symbol: &str) -> PyResult<bool> {
        RUNTIME
            .block_on(self.inner.cancel_order(order_id, symbol))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Get the count of open orders, optionally filtered by symbol.
    #[pyo3(signature = (symbol=None))]
    fn open_order_count(&self, symbol: Option<&str>) -> usize {
        self.inner.get_open_orders(symbol).len()
    }

    /// Get the total number of tracked orders.
    fn total_orders(&self) -> usize {
        self.inner.tracker().len()
    }

    fn __repr__(&self) -> String {
        format!(
            "OrderExecutor(mode={}, open_orders={})",
            match self.inner.mode() {
                ExecutionMode::Paper => "paper",
                ExecutionMode::Live => "live",
            },
            self.inner.get_open_orders(None).len()
        )
    }
}

/// Parse a side string into an OrderSide.
fn parse_side(s: &str) -> PyResult<OrderSide> {
    match s.to_lowercase().as_str() {
        "buy" | "long" => Ok(OrderSide::Buy),
        "sell" | "short" => Ok(OrderSide::Sell),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Invalid side: '{s}'. Use 'buy' or 'sell'"
        ))),
    }
}

/// Convert an OrderResult to a Python dict.
fn order_result_to_dict(
    py: Python<'_>,
    result: &tsar_order_executor::types::OrderResult,
) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("id", result.id.to_string())?;
    dict.set_item("exchange_order_id", &result.exchange_order_id)?;
    dict.set_item("symbol", &result.symbol)?;
    dict.set_item("side", result.side.to_string())?;
    dict.set_item("order_type", result.order_type.to_string())?;
    dict.set_item("quantity", result.quantity)?;
    dict.set_item("filled_quantity", result.filled_quantity)?;
    dict.set_item("average_fill_price", result.average_fill_price)?;
    dict.set_item("price", result.price)?;
    dict.set_item("status", result.status.to_string())?;
    dict.set_item("fee", result.fee)?;
    dict.set_item("placed_at", result.placed_at.to_rfc3339())?;
    dict.set_item("updated_at", result.updated_at.to_rfc3339())?;
    Ok(dict.into())
}
