// =============================================================================
// monte_carlo_stub.cpp — CPU stub for Monte Carlo when CUDA is unavailable
// =============================================================================

#ifndef TSAR_HAS_CUDA

#include "tsar/gpu/monte_carlo.h"

#include <cmath>
#include <random>

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
        double drift     = (p.rate - 0.5 * p.vol * p.vol) * p.time_years;
        double diffusion = p.vol * std::sqrt(p.time_years);
        double discount  = std::exp(-p.rate * p.time_years);

        double sum  = 0.0;
        double sq   = 0.0;

        for (uint64_t i = 0; i < n_paths; ++i) {
            double z     = normal(rng);
            double ST    = p.spot * std::exp(drift + diffusion * z);
            double payoff = p.is_call ? std::max(ST - p.strike, 0.0)
                                      : std::max(p.strike - ST, 0.0);
            sum += payoff;
            sq  += payoff * payoff;
        }

        double mean = sum / static_cast<double>(n_paths);
        results[opt].price     = discount * mean;
        results[opt].std_error = 0.0;
        results[opt].delta     = 0.0;
    }

    return GPUError::Ok;
}

GPUError var_historical(const double* /*returns*/,
                        size_t /*n_returns*/,
                        double portfolio_value,
                        double /*confidence*/,
                        double* var_out) {
    if (!var_out) return GPUError::InvalidInput;
    // Stub: 5% placeholder
    *var_out = portfolio_value * 0.05;
    return GPUError::Ok;
}

}  // namespace tsar::gpu

#endif  // !TSAR_HAS_CUDA
