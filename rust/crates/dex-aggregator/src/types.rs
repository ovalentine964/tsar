//! DEX aggregator types — quotes, sources, routes.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Supported DEX sources.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DexSource {
    UniswapV2,
    UniswapV3,
    SushiSwap,
    Curve,
    BalancerV2,
    OneInch,
    Jupiter,
}

impl DexSource {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::UniswapV2 => "uniswap_v2",
            Self::UniswapV3 => "uniswap_v3",
            Self::SushiSwap => "sushiswap",
            Self::Curve => "curve",
            Self::BalancerV2 => "balancer_v2",
            Self::OneInch => "1inch",
            Self::Jupiter => "jupiter",
        }
    }

    pub fn all_evm() -> &'static [DexSource] {
        &[
            Self::UniswapV2,
            Self::UniswapV3,
            Self::SushiSwap,
            Self::Curve,
            Self::BalancerV2,
            Self::OneInch,
        ]
    }
}

impl std::fmt::Display for DexSource {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// A quote from a DEX for a specific swap.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DexQuote {
    /// Which DEX provided this quote.
    pub source: DexSource,
    /// Chain name.
    pub chain: String,
    /// Token being sold.
    pub token_in: String,
    /// Token being bought.
    pub token_out: String,
    /// Amount of token_in.
    pub amount_in: f64,
    /// Expected amount of token_out.
    pub amount_out: f64,
    /// Price impact as a percentage.
    pub price_impact_pct: f64,
    /// Estimated gas cost in USD.
    pub gas_cost_usd: f64,
    /// Estimated gas units.
    pub gas_units: u64,
    /// Fee percentage charged by the DEX.
    pub fee_pct: f64,
    /// Net output after fees and gas (in USD).
    pub net_output_usd: f64,
    /// Route path (token addresses).
    pub route: Vec<String>,
    /// Quote validity deadline.
    pub valid_until: DateTime<Utc>,
    /// When the quote was fetched.
    pub fetched_at: DateTime<Utc>,
}

/// A swap route — may split across multiple DEXs.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SwapRoute {
    /// Total input amount.
    pub total_amount_in: f64,
    /// Expected total output.
    pub total_amount_out: f64,
    /// Route segments (splits).
    pub segments: Vec<RouteSegment>,
    /// Total gas cost in USD.
    pub total_gas_usd: f64,
    /// Total price impact.
    pub total_price_impact_pct: f64,
    /// Net output in USD (after gas and fees).
    pub net_output_usd: f64,
    /// How much better than the worst quote (USD).
    pub savings_vs_worst_usd: f64,
    /// How much better than the best single-source quote (USD).
    pub savings_vs_best_single_usd: f64,
}

/// A single segment of a split route.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RouteSegment {
    /// DEX to use.
    pub source: DexSource,
    /// Percentage of total input for this segment.
    pub input_pct: f64,
    /// Amount of token_in for this segment.
    pub amount_in: f64,
    /// Expected amount_out from this segment.
    pub amount_out: f64,
    /// Route path.
    pub path: Vec<String>,
}

/// Quote comparison result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuoteComparison {
    /// Best single-source quote.
    pub best_single: DexQuote,
    /// Worst single-source quote.
    pub worst_single: DexQuote,
    /// Optimal split route (if better than single source).
    pub optimal_route: Option<SwapRoute>,
    /// All quotes received.
    pub all_quotes: Vec<DexQuote>,
    /// Sources that failed to respond.
    pub failed_sources: Vec<String>,
    /// Total time to fetch all quotes (ms).
    pub fetch_time_ms: u64,
}
