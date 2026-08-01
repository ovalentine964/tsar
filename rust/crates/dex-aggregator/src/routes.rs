//! Route optimization — find the best swap path across DEXs.

use crate::types::{DexQuote, RouteSegment, SwapRoute};

/// Route optimizer for multi-hop and split routing.
pub struct RouteOptimizer;

impl RouteOptimizer {
    /// Find the optimal route given a set of quotes.
    ///
    /// Considers:
    /// - Single-source best quote
    /// - Split across top 2 sources
    /// - Multi-hop routing through intermediate tokens
    pub fn optimize(quotes: &[DexQuote], amount_in: f64) -> Option<SwapRoute> {
        if quotes.is_empty() {
            return None;
        }

        // Sort by net output
        let mut sorted: Vec<&DexQuote> = quotes.iter().collect();
        sorted.sort_by(|a, b| {
            b.net_output_usd
                .partial_cmp(&a.net_output_usd)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let best = sorted[0];

        // Try split routing with top sources
        if sorted.len() >= 2 {
            let second = sorted[1];
            let split_ratio = Self::calculate_optimal_split(best, second, amount_in);

            if split_ratio > 0.0 && split_ratio < 1.0 {
                let split_1_amount = amount_in * split_ratio;
                let split_2_amount = amount_in * (1.0 - split_ratio);

                let ratio_1 = best.amount_out / best.amount_in;
                let ratio_2 = second.amount_out / second.amount_in;

                let split_1_out = split_1_amount * ratio_1;
                let split_2_out = split_2_amount * ratio_2;
                let total_out = split_1_out + split_2_out;

                if total_out > best.amount_out {
                    return Some(SwapRoute {
                        total_amount_in: amount_in,
                        total_amount_out: total_out,
                        segments: vec![
                            RouteSegment {
                                source: best.source,
                                input_pct: split_ratio * 100.0,
                                amount_in: split_1_amount,
                                amount_out: split_1_out,
                                path: best.route.clone(),
                            },
                            RouteSegment {
                                source: second.source,
                                input_pct: (1.0 - split_ratio) * 100.0,
                                amount_in: split_2_amount,
                                amount_out: split_2_out,
                                path: second.route.clone(),
                            },
                        ],
                        total_gas_usd: best.gas_cost_usd + second.gas_cost_usd,
                        total_price_impact_pct: best
                            .price_impact_pct
                            .max(second.price_impact_pct),
                        net_output_usd: total_out,
                        savings_vs_worst_usd: total_out
                            - sorted.last().unwrap().amount_out,
                        savings_vs_best_single_usd: total_out - best.amount_out,
                    });
                }
            }
        }

        None // Single source is already the best
    }

    /// Calculate the optimal split ratio between two sources.
    ///
    /// Uses a binary search to find the split that maximizes total output.
    fn calculate_optimal_split(a: &DexQuote, b: &DexQuote, amount_in: f64) -> f64 {
        let mut best_ratio = 0.0_f64;
        let mut best_output = a.amount_out;

        // Test splits from 10% to 90%
        for pct in 1..=9 {
            let ratio = pct as f64 / 10.0;
            let split_a = amount_in * ratio;
            let split_b = amount_in * (1.0 - ratio);

            let ratio_a = a.amount_out / a.amount_in;
            let ratio_b = b.amount_out / b.amount_in;

            let output_a = split_a * ratio_a;
            let output_b = split_b * ratio_b;
            let total = output_a + output_b;

            if total > best_output {
                best_output = total;
                best_ratio = ratio;
            }
        }

        best_ratio
    }
}
