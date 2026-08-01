//! PyO3 bindings for the rules enforcer.

use pyo3::prelude::*;
use pyo3::types::PyDict;
use tokio::runtime::Runtime;

use crate::client::RulesEnforcerClient;
use crate::types::*;

/// Python-accessible rules enforcer client.
#[pyclass(name = "RulesEnforcer")]
pub struct PyRulesEnforcer {
    client: Option<RulesEnforcerClient>,
    runtime: Runtime,
    config: BlockchainConfig,
}

#[pymethods]
impl PyRulesEnforcer {
    /// Create a new rules enforcer from config dict.
    #[new]
    fn new(config_dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let config = BlockchainConfig {
            rpc_url: config_dict
                .get_item("rpc_url")?
                .map(|v| v.extract::<String>())
                .transpose()?
                .unwrap_or_default(),
            chain_id: config_dict
                .get_item("chain_id")?
                .map(|v| v.extract::<u64>())
                .transpose()?
                .unwrap_or(80001),
            private_key: config_dict
                .get_item("private_key")?
                .map(|v| v.extract::<String>())
                .transpose()?
                .unwrap_or_default(),
            kill_switch_address: config_dict
                .get_item("kill_switch_address")?
                .map(|v| v.extract::<String>())
                .transpose()?
                .unwrap_or_default(),
            mandate_address: config_dict
                .get_item("mandate_address")?
                .map(|v| v.extract::<String>())
                .transpose()?
                .unwrap_or_default(),
            audit_trail_address: config_dict
                .get_item("audit_trail_address")?
                .map(|v| v.extract::<String>())
                .transpose()?
                .unwrap_or_default(),
            governance_address: config_dict
                .get_item("governance_address")?
                .map(|v| v.extract::<String>())
                .transpose()?
                .unwrap_or_default(),
            gas_price_gwei: config_dict
                .get_item("gas_price_gwei")?
                .map(|v| v.extract::<u64>())
                .transpose()?
                .unwrap_or(30),
            gas_limit: config_dict
                .get_item("gas_limit")?
                .map(|v| v.extract::<u64>())
                .transpose()?
                .unwrap_or(500_000),
        };

        let runtime = Runtime::new().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create runtime: {}", e))
        })?;

        Ok(Self {
            client: None,
            runtime,
            config,
        })
    }

    /// Connect to the blockchain and initialize contracts.
    fn connect(&mut self) -> PyResult<()> {
        let config = self.config.clone();
        let client = self.runtime.block_on(async {
            RulesEnforcerClient::new(config).await
        }).map_err(|e| {
            pyo3::exceptions::PyConnectionError::new_err(format!("Connection failed: {}", e))
        })?;

        self.client = Some(client);
        Ok(())
    }

    /// Check if trading is allowed by the kill switch.
    fn is_trading_allowed(&self) -> PyResult<bool> {
        let client = self.client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Not connected. Call connect() first.")
        })?;

        self.runtime.block_on(async {
            client.is_trading_allowed().await
        }).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Check failed: {}", e))
        })
    }

    /// Get kill switch status as a dict.
    fn get_kill_switch_status(&self, py: Python) -> PyResult<PyObject> {
        let client = self.client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Not connected")
        })?;

        let status = self.runtime.block_on(async {
            client.get_kill_switch_status().await
        }).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed: {}", e))
        })?;

        let dict = PyDict::new(py);
        dict.set_item("active", status.active)?;
        dict.set_item("reason", &status.reason)?;
        dict.set_item("activated_at", status.activated_at)?;
        dict.set_item("daily_pnl_bps", status.daily_pnl_bps)?;
        dict.set_item("circuit_breaker_level", status.circuit_breaker_level)?;
        dict.set_item("drawdown_bps", status.drawdown_bps)?;

        Ok(dict.into())
    }

    /// Log a trade on-chain.
    fn log_trade(
        &self,
        symbol: &str,
        side: u8,
        notional: u64,
        price: u64,
        quantity: u64,
        leverage_bps: u64,
        realized_pnl: i64,
        order_id: &str,
    ) -> PyResult<u64> {
        let client = self.client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Not connected")
        })?;

        let trade = TradeRecord {
            symbol_hash: RulesEnforcerClient::hash_symbol(symbol),
            side,
            notional,
            price,
            quantity,
            leverage_bps,
            realized_pnl,
            order_id: RulesEnforcerClient::hash_symbol(order_id),
        };

        self.runtime.block_on(async {
            client.log_trade(&trade).await
        }).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Log trade failed: {}", e))
        })
    }

    /// Log a rule check on-chain.
    fn log_rule_check(
        &self,
        rule_id: &str,
        symbol: &str,
        passed: bool,
        reason: &str,
    ) -> PyResult<()> {
        let client = self.client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Not connected")
        })?;

        self.runtime.block_on(async {
            client.log_rule_check(rule_id, symbol, passed, reason).await
        }).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Log rule check failed: {}", e))
        })
    }

    /// Log an enforcement action on-chain.
    fn log_enforcement_action(
        &self,
        action_type: u8,
        rule_id: &str,
        details: &str,
    ) -> PyResult<()> {
        let client = self.client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Not connected")
        })?;

        let action = match action_type {
            0 => EnforcementActionType::KillSwitch,
            1 => EnforcementActionType::MandateBlock,
            2 => EnforcementActionType::PositionLimit,
            3 => EnforcementActionType::LeverageBlock,
            _ => return Err(pyo3::exceptions::PyValueError::new_err("Invalid action type")),
        };

        self.runtime.block_on(async {
            client.log_enforcement_action(action, rule_id, details).await
        }).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Log enforcement failed: {}", e))
        })
    }

    /// Update daily P&L on the kill switch.
    fn update_daily_pnl(&self, pnl_bps: i64) -> PyResult<()> {
        let client = self.client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Not connected")
        })?;

        self.runtime.block_on(async {
            client.update_daily_pnl(pnl_bps).await
        }).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Update P&L failed: {}", e))
        })
    }

    /// Update equity on the kill switch.
    fn update_equity(&self, equity: u64) -> PyResult<()> {
        let client = self.client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Not connected")
        })?;

        self.runtime.block_on(async {
            client.update_equity(equity).await
        }).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Update equity failed: {}", e))
        })
    }

    /// Get signer address.
    fn signer_address(&self) -> PyResult<String> {
        let client = self.client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Not connected")
        })?;

        Ok(format!("{:?}", client.signer_address()))
    }

    /// Check if connected.
    fn is_connected(&self) -> bool {
        self.client.is_some()
    }
}
