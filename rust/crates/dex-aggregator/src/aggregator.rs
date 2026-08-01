//! DEX aggregator — parallel quote fetching and comparison.

use chrono::Utc;
use tokio::task::JoinSet;
use tracing::{debug, info, warn};

use crate::types::{DexQuote, DexSource, QuoteComparison, RouteSegment, SwapRoute};

/// Configuration for the DEX aggregator.
#[derive(Debug, Clone)]
pub struct AggregatorConfig {
    /// Chain to query (e.g., "ethereum", "arbitrum").
    pub chain: String,
    /// RPC URL for on-chain quote calls.
    pub rpc_url: String,
    /// 1inch API key (optional, for higher rate limits).
    pub oneinch_api_key: Option<String>,
    /// Jupiter API base URL.
    pub jupiter_url: String,
    /// Request timeout in seconds.
    pub timeout_secs: u64,
    /// Sources to query (empty = all available for the chain).
    pub sources: Vec<DexSource>,
}

impl Default for AggregatorConfig {
    fn default() -> Self {
        Self {
            chain: "ethereum".to_string(),
            rpc_url: String::new(),
            oneinch_api_key: None,
            jupiter_url: "https://quote-api.jup.ag/v6".to_string(),
            timeout_secs: 10,
            sources: Vec::new(),
        }
    }
}

/// DEX aggregator — fetches and compares quotes from multiple DEXs.
pub struct DexAggregator {
    config: AggregatorConfig,
    http: reqwest::Client,
}

impl DexAggregator {
    /// Create a new DEX aggregator.
    pub fn new(config: AggregatorConfig) -> Self {
        let http = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(config.timeout_secs))
            .build()
            .expect("Failed to create HTTP client");

        Self { config, http }
    }

    /// Fetch quotes from all configured DEX sources in parallel.
    ///
    /// Returns a comparison with the best quote identified.
    pub async fn get_quotes(
        &self,
        token_in: &str,
        token_out: &str,
        amount_in: f64,
    ) -> Result<QuoteComparison, String> {
        let start = std::time::Instant::now();
        let sources = if self.config.sources.is_empty() {
            self.available_sources()
        } else {
            self.config.sources.clone()
        };

        let mut tasks = JoinSet::new();

        for source in sources {
            let http = self.http.clone();
            let chain = self.config.chain.clone();
            let rpc_url = self.config.rpc_url.clone();
            let token_in = token_in.to_string();
            let token_out = token_out.to_string();
            let oneinch_key = self.config.oneinch_api_key.clone();
            let jupiter_url = self.config.jupiter_url.clone();

            tasks.spawn(async move {
                Self::fetch_quote(
                    source,
                    &chain,
                    &rpc_url,
                    &token_in,
                    &token_out,
                    amount_in,
                    oneinch_key.as_deref(),
                    &jupiter_url,
                    &http,
                )
                .await
            });
        }

        let mut quotes = Vec::new();
        let mut failed = Vec::new();

        while let Some(result) = tasks.join_next().await {
            match result {
                Ok(Ok(quote)) => quotes.push(quote),
                Ok(Err((source, err))) => {
                    warn!(source = %source, error = %err, "Quote fetch failed");
                    failed.push(source);
                }
                Err(e) => {
                    warn!(error = %e, "Task join error");
                }
            }
        }

        let fetch_time_ms = start.elapsed().as_millis() as u64;

        if quotes.is_empty() {
            return Err(format!("All {} sources failed", sources.len()));
        }

        // Sort by net output (best first)
        quotes.sort_by(|a, b| {
            b.net_output_usd
                .partial_cmp(&a.net_output_usd)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let best_single = quotes.first().unwrap().clone();
        let worst_single = quotes.last().unwrap().clone();

        // Try to find an optimal split route
        let optimal_route = self.find_optimal_route(&quotes, amount_in);

        info!(
            token_in = %token_in,
            token_out = %token_out,
            amount_in = amount_in,
            best_source = %best_single.source,
            best_output = best_single.amount_out,
            quotes_received = quotes.len(),
            failed = failed.len(),
            fetch_time_ms = fetch_time_ms,
            "Quote comparison complete"
        );

        Ok(QuoteComparison {
            best_single,
            worst_single,
            optimal_route,
            all_quotes: quotes,
            failed_sources: failed,
            fetch_time_ms,
        })
    }

    /// Find an optimal split route across multiple DEXs.
    ///
    /// Uses a simple heuristic: split across the top 2-3 sources
    /// if the combined output exceeds the best single source.
    fn find_optimal_route(
        &self,
        quotes: &[DexQuote],
        total_amount_in: f64,
    ) -> Option<SwapRoute> {
        if quotes.len() < 2 {
            return None;
        }

        // Simple split: 70% to best, 30% to second best
        let best = &quotes[0];
        let second = &quotes[1];

        let split_1_amount = total_amount_in * 0.7;
        let split_2_amount = total_amount_in * 0.3;

        // Estimate output for each split (linear interpolation)
        let ratio_1 = best.amount_out / best.amount_in;
        let ratio_2 = second.amount_out / second.amount_in;

        let split_1_out = split_1_amount * ratio_1;
        let split_2_out = split_2_amount * ratio_2;
        let total_out = split_1_out + split_2_out;

        // Check if split is better than single source
        if total_out <= best.amount_out {
            return None;
        }

        let savings = total_out - best.amount_out;
        let gas_usd = best.gas_cost_usd + second.gas_cost_usd;

        Some(SwapRoute {
            total_amount_in,
            total_amount_out: total_out,
            segments: vec![
                RouteSegment {
                    source: best.source,
                    input_pct: 70.0,
                    amount_in: split_1_amount,
                    amount_out: split_1_out,
                    path: best.route.clone(),
                },
                RouteSegment {
                    source: second.source,
                    input_pct: 30.0,
                    amount_in: split_2_amount,
                    amount_out: split_2_out,
                    path: second.route.clone(),
                },
            ],
            total_gas_usd: gas_usd,
            total_price_impact_pct: best
                .price_impact_pct
                .max(second.price_impact_pct),
            net_output_usd: total_out * best.net_output_usd / best.amount_out
                - gas_usd,
            savings_vs_worst_usd: savings,
            savings_vs_best_single_usd: savings,
        })
    }

    /// Fetch a quote from a specific DEX source.
    async fn fetch_quote(
        source: DexSource,
        chain: &str,
        rpc_url: &str,
        token_in: &str,
        token_out: &str,
        amount_in: f64,
        oneinch_key: Option<&str>,
        jupiter_url: &str,
        http: &reqwest::Client,
    ) -> Result<DexQuote, (String, String)> {
        let now = Utc::now();

        match source {
            DexSource::OneInch => {
                Self::fetch_oneinch_quote(http, chain, token_in, token_out, amount_in, oneinch_key)
                    .await
            }
            DexSource::Jupiter => {
                Self::fetch_jupiter_quote(http, jupiter_url, token_in, token_out, amount_in).await
            }
            _ => {
                // For on-chain DEXs, use a simplified quote estimation
                // Production: call the actual router contract's quote function
                Err((
                    source.to_string(),
                    "On-chain quote not yet implemented".to_string(),
                ))
            }
        }
    }

    /// Fetch quote from 1inch Aggregation API.
    async fn fetch_oneinch_quote(
        http: &reqwest::Client,
        chain: &str,
        token_in: &str,
        token_out: &str,
        amount_in: f64,
        api_key: Option<&str>,
    ) -> Result<DexQuote, (String, String)> {
        let chain_id = match chain {
            "ethereum" => 1,
            "polygon" => 137,
            "arbitrum" => 42161,
            "base" => 8453,
            "optimism" => 10,
            _ => {
                return Err((
                    "1inch".to_string(),
                    format!("Unsupported chain: {chain}"),
                ))
            }
        };

        let url = format!(
            "https://api.1inch.dev/swap/v6.0/{}/quote?src={}&dst={}&amount={}",
            chain_id, token_in, token_out, amount_in
        );

        let mut req = http.get(&url);
        if let Some(key) = api_key {
            req = req.header("Authorization", format!("Bearer {key}"));
        }

        let resp: serde_json::Value = req
            .send()
            .await
            .map_err(|e| ("1inch".to_string(), format!("HTTP error: {e}")))?
            .json()
            .await
            .map_err(|e| ("1inch".to_string(), format!("JSON error: {e}")))?;

        let amount_out = resp
            .get("dstAmount")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok())
            .unwrap_or(0.0);

        Ok(DexQuote {
            source: DexSource::OneInch,
            chain: chain.to_string(),
            token_in: token_in.to_string(),
            token_out: token_out.to_string(),
            amount_in,
            amount_out,
            price_impact_pct: 0.0,
            gas_cost_usd: 5.0,
            gas_units: 150_000,
            fee_pct: 0.0,
            net_output_usd: amount_out * 1.0, // Needs token price
            route: Vec::new(),
            valid_until: Utc::now() + chrono::Duration::seconds(30),
            fetched_at: Utc::now(),
        })
    }

    /// Fetch quote from Jupiter API (Solana).
    async fn fetch_jupiter_quote(
        http: &reqwest::Client,
        base_url: &str,
        token_in: &str,
        token_out: &str,
        amount_in: f64,
    ) -> Result<DexQuote, (String, String)> {
        // Jupiter uses integer amounts (lamports/smallest unit)
        let amount_int = (amount_in * 1e9) as u64; // Assuming 9 decimals

        let url = format!(
            "{}/quote?inputMint={}&outputMint={}&amount={}",
            base_url, token_in, token_out, amount_int
        );

        let resp: serde_json::Value = http
            .get(&url)
            .send()
            .await
            .map_err(|e| ("jupiter".to_string(), format!("HTTP error: {e}")))?
            .json()
            .await
            .map_err(|e| ("jupiter".to_string(), format!("JSON error: {e}")))?;

        let amount_out = resp
            .get("outAmount")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok())
            .map(|v| v / 1e9)
            .unwrap_or(0.0);

        let price_impact = resp
            .get("priceImpactPct")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok())
            .unwrap_or(0.0);

        Ok(DexQuote {
            source: DexSource::Jupiter,
            chain: "solana".to_string(),
            token_in: token_in.to_string(),
            token_out: token_out.to_string(),
            amount_in,
            amount_out,
            price_impact_pct: price_impact,
            gas_cost_usd: 0.01, // Solana is cheap
            gas_units: 200_000,
            fee_pct: 0.0,
            net_output_usd: amount_out * 1.0,
            route: Vec::new(),
            valid_until: Utc::now() + chrono::Duration::seconds(30),
            fetched_at: Utc::now(),
        })
    }

    /// Get available sources for the configured chain.
    fn available_sources(&self) -> Vec<DexSource> {
        match self.config.chain.as_str() {
            "solana" => vec![DexSource::Jupiter],
            _ => DexSource::all_evm().to_vec(),
        }
    }
}
