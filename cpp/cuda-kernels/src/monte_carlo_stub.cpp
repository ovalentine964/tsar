// =============================================================================
// monte_carlo_stub.cpp — CPU stub for Monte Carlo when CUDA is unavailable
// =============================================================================
//
// Mirrors the CUDA kernel logic: antithetic variates, pathwise delta,
// proper standard error computation.
// =============================================================================

#ifndef TSAR_HAS_CUDA

#include "tsar/gpu/monte_carlo.h"

#include <algorithm>
#include <cmath>
#include <random>
#include <vector>

namespace tsar::gpu {

GPUError monte_carlo_batch(const MCOptionParams* params,
                           size_t n_options,
                           uint64_t n_paths,
                           uint64_t seed,
                           MCResult* results) {
    if (!params || !results || n_options == 0 || n_paths == 0) {
        return GPUError::InvalidInput;
    }

    std::mt19937_64 rng(seed);
    std::normal_distribution<double> normal(0.0, 1.0);

    for (size_t opt = 0; opt < n_options; ++opt) {
        const auto& p = params[opt];
        double vol2     = p.vol * p.vol;
        double sqrt_T   = std::sqrt(p.time_years);
        double drift    = (p.rate - 0.5 * vol2) * p.time_years;
        double diffusion = p.vol * sqrt_T;
        double discount  = std::exp(-p.rate * p.time_years);
        double S_inv     = 1.0 / p.spot;

        double sum_payoff = 0.0;
        double sum_sq     = 0.0;
        double sum_delta  = 0.0;

        for (uint64_t i = 0; i < n_paths; ++i) {
            double z = normal(rng);

            // Antithetic variates
            double ST1 = p.spot * std::exp(drift + diffusion * z);
            double ST2 = p.spot * std::exp(drift - diffusion * z);

            double payoff1 = p.is_call ? std::max(ST1 - p.strike, 0.0)
                                       : std::max(p.strike - ST1, 0.0);
            double payoff2 = p.is_call ? std::max(ST2 - p.strike, 0.0)
                                       : std::max(p.strike - ST2, 0.0);

            double avg_payoff = 0.5 * (payoff1 + payoff2);
            sum_payoff += avg_payoff;
            sum_sq     += avg_payoff * avg_payoff;

            // Pathwise delta
            if (p.is_call) {
                double d1 = (ST1 > p.strike) ? ST1 * S_inv : 0.0;
                double d2 = (ST2 > p.strike) ? ST2 * S_inv : 0.0;
                sum_delta += 0.5 * (d1 + d2);
            } else {
                double d1 = (ST1 < p.strike) ? -ST1 * S_inv : 0.0;
                double d2 = (ST2 < p.strike) ? -ST2 * S_inv : 0.0;
                sum_delta += 0.5 * (d1 + d2);
            }
        }

        double n = static_cast<double>(n_paths);
        double mean_payoff = sum_payoff / n;
        double var_payoff  = std::max((sum_sq / n) - (mean_payoff * mean_payoff), 0.0);

        results[opt].price     = discount * mean_payoff;
        results[opt].std_error = discount * std::sqrt(var_payoff / n);
        results[opt].delta     = discount * (sum_delta / n);
    }

    return GPUError::Ok;
}

GPUError var_historical(const double* returns,
                        size_t n_returns,
                        double portfolio_value,
                        double confidence,
                        double* var_out) {
    if (!returns || !var_out || n_returns == 0) return GPUError::InvalidInput;

    // Sort a copy of returns
    std::vector<double> sorted(returns, returns + n_returns);
    std::sort(sorted.begin(), sorted.end());

    // VaR = -percentile(1 - confidence) * portfolio_value
    size_t idx = static_cast<size_t>((1.0 - confidence) * n_returns);
    if (idx >= n_returns) idx = n_returns - 1;

    *var_out = -sorted[idx] * portfolio_value;
    if (*var_out < 0.0) *var_out = 0.0;

    return GPUError::Ok;
}

}  // namespace tsar::gpu

#endif  // !TSAR_HAS_CUDA
