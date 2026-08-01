//! Gas optimizer — recommends optimal gas settings and chain routing.

use chrono::Utc;
use tracing::{debug, info};

use crate::chains::{Chain, ChainConfig};
use crate::tracker::GasTracker;
use crate::types::{ChainGasInfo, GasRecommendation, GasStrategy, L2Comparison};

/// Configuration for the gas optimizer.
#[derive(Debug, Clone)]
pub struct GasConfig {
    /// Ethereum RPC URL for base fee tracking.
    pub eth_rpc_url: String,
    /// Additional chain RPC URLs.
    pub chain_configs: Vec<ChainConfig>,
    /// Default strategy.
    pub default_strategy: GasStrategy,
    /// ETH price in USD (cached, updated periodically).
    pub eth_price_usd: f64,
}

impl Default for GasConfig {
    fn default() -> Self {
        Self {
            eth_rpc_url: String::new(),
            chain_configs: Vec::new(),
            default_strategy: GasStrategy::Standard,
            eth_price_usd: 2000.0,
        }
    }
}

/// Gas optimizer — provides gas price recommendations and chain routing.
pub struct GasOptimizer {
    config: GasConfig,
    tracker: GasTracker,
}

impl GasOptimizer {
    /// Create a new gas optimizer.
    pub fn new(config: GasConfig) -> Self {
        Self {
            config,
            tracker: GasTracker::new(100),
        }
    }

    /// Get a gas price recommendation for the default chain (Ethereum).
    pub async fn get_recommendation(&self) -> Result<GasRecommendation, String> {
        let eth_info = self.fetch_chain_gas(Chain::Ethereum).await?;

        let strategy = self.config.default_strategy;
        let (max_fee, priority_fee, est_secs) = self.calculate_fees(&eth_info, strategy);

        let gas_limit = Chain::Ethereum.typical_swap_gas();
        let cost_eth = (max_fee * gas_limit as f64) / 1e9;
        let cost_usd = cost_eth * self.config.eth_price_usd;

        Ok(GasRecommendation {
            strategy,
            max_fee_gwei: max_fee,
            max_priority_fee_gwei: priority_fee,
            gas_price_gwei: max_fee,
            gas_limit,
            estimated_cost_eth: cost_eth,
            estimated_cost_usd: cost_usd,
            est_confirmation_secs: est_secs,
            best_chain: "ethereum".to_string(),
            chain_options: Vec::new(),
            generated_at: Utc::now(),
        })
    }

    /// Compare gas costs across all supported L2 chains.
    pub async fn compare_chains(&self) -> Result<Vec<L2Comparison>, String> {
        let mut comparisons = Vec::new();

        for &chain in Chain::all() {
            let info = match self.fetch_chain_gas(chain).await {
                Ok(info) => info,
                Err(e) => {
                    debug!(chain = chain.name(), error = %e, "Failed to fetch gas info");
                    continue;
                }
            };

            let gas_limit = chain.typical_swap_gas();
            let cost_native = (info.gas_price_gwei * gas_limit as f64) / 1e9;
            let native_price = self.get_native_price(chain);
            let cost_usd = cost_native * native_price;

            comparisons.push(L2Comparison {
                chain: chain.name().to_string(),
                chain_id: chain.chain_id(),
                swap_cost_usd: cost_usd,
                swap_cost_native: cost_native,
                native_token_price_usd: native_price,
                est_confirmation_secs: info.est_confirmation_secs,
                is_eip1559: chain.is_eip1559(),
                security_level: match chain {
                    Chain::Ethereum => 1,
                    Chain::Arbitrum | Chain::Optimism => 2,
                    Chain::Base => 2,
                    Chain::Polygon => 2,
                    Chain::Solana => 1,
                },
            });
        }

        // Sort by cost (cheapest first)
        comparisons.sort_by(|a, b| {
            a.swap_cost_usd
                .partial_cmp(&b.swap_cost_usd)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        Ok(comparisons)
    }

    /// Record a gas price sample for trend analysis.
    pub fn record_sample(&mut self, info: &ChainGasInfo) {
        self.tracker.record(info);
    }

    /// Get the current gas trend (positive = rising, negative = falling).
    pub fn trend(&self) -> f64 {
        self.tracker.trend()
    }

    /// Predict the next block's base fee.
    pub fn predict_next_base_fee(&self) -> f64 {
        self.tracker.predict_next_base_fee()
    }

    /// Calculate recommended fees based on strategy.
    fn calculate_fees(
        &self,
        info: &ChainGasInfo,
        strategy: GasStrategy,
    ) -> (f64, f64, u64) {
        let base = info.base_fee_gwei.unwrap_or(info.gas_price_gwei);
        let priority = info.priority_fee_gwei;

        let (fee_mult, priority_mult, est_secs) = match strategy {
            GasStrategy::Economy => (1.0, 0.8, 120),
            GasStrategy::Standard => (1.1, 1.0, 30),
            GasStrategy::Fast => (1.25, 1.5, 15),
            GasStrategy::Aggressive => (1.5, 2.5, 6),
        };

        let max_fee = base * fee_mult + priority * priority_mult;
        let priority_fee = priority * priority_mult;

        (max_fee, priority_fee, est_secs)
    }

    /// Fetch gas info for a specific chain.
    async fn fetch_chain_gas(&self, chain: Chain) -> Result<ChainGasInfo, String> {
        let rpc_url = self.get_rpc_url(chain);

        // Use reqwest to call eth_gasPrice and eth_getBlockByNumber
        let client = reqwest::Client::new();

        // Get gas price
        let gas_price_body = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_gasPrice",
            "params": []
        });

        let gas_price_resp: serde_json::Value = client
            .post(&rpc_url)
            .json(&gas_price_body)
            .send()
            .await
            .map_err(|e| format!("RPC error: {e}"))?
            .json()
            .await
            .map_err(|e| format!("JSON parse error: {e}"))?;

        let gas_price_wei = gas_price_resp
            .get("result")
            .and_then(|v| v.as_str())
            .and_then(|s| u128::from_str_radix(s.trim_start_matches("0x"), 16).ok())
            .unwrap_or(0);
        let gas_price_gwei = gas_price_wei as f64 / 1e9;

        // Get latest block for base fee
        let block_body = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "eth_getBlockByNumber",
            "params": ["latest", false]
        });

        let block_resp: serde_json::Value = client
            .post(&rpc_url)
            .json(&block_body)
            .send()
            .await
            .map_err(|e| format!("RPC error: {e}"))?
            .json()
            .await
            .map_err(|e| format!("JSON parse error: {e}"))?;

        let base_fee = block_resp
            .get("result")
            .and_then(|r| r.get("baseFeePerGas"))
            .and_then(|v| v.as_str())
            .and_then(|s| u128::from_str_radix(s.trim_start_matches("0x"), 16).ok())
            .map(|v| v as f64 / 1e9);

        let gas_limit = chain.typical_swap_gas();
        let native_price = self.get_native_price(chain);
        let cost_eth = (gas_price_gwei * gas_limit as f64) / 1e9;
        let cost_usd = cost_eth * native_price;

        Ok(ChainGasInfo {
            chain: chain.name().to_string(),
            chain_id: chain.chain_id(),
            base_fee_gwei: base_fee,
            gas_price_gwei,
            priority_fee_gwei: base_fee.map(|b| gas_price_gwei - b).unwrap_or(1.0).max(0.1),
            swap_cost_usd: cost_usd,
            est_confirmation_secs: 12,
            block_utilization_pct: 50.0,
            fetched_at: Utc::now(),
        })
    }

    fn get_rpc_url(&self, chain: Chain) -> &str {
        match chain {
            Chain::Ethereum => &self.config.eth_rpc_url,
            _ => self
                .config
                .chain_configs
                .iter()
                .find(|c| c.chain == chain)
                .map(|c| &c.rpc_url)
                .unwrap_or(&self.config.eth_rpc_url),
        }
    }

    fn get_native_price(&self, chain: Chain) -> f64 {
        match chain {
            Chain::Ethereum | Chain::Arbitrum | Chain::Base | Chain::Optimism => {
                self.config.eth_price_usd
            }
            Chain::Polygon => 0.8, // MATIC price — should be cached
            Chain::Solana => 100.0, // SOL price — should be cached
        }
    }
}
