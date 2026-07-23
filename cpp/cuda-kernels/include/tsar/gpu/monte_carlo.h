#pragma once
// =============================================================================
// tsar/gpu/monte_carlo.h — GPU-accelerated Monte Carlo simulation
// =============================================================================
//
// Provides batch Monte Carlo pricing for European and exotic options.
// When CUDA is not available, falls back to a CPU stub that returns
// placeholder results so the system can link and test.
// =============================================================================

#include <cstdint>
#include <cstddef>

namespace tsar::gpu {

// ---------------------------------------------------------------------------
// Monte Carlo result — one per option in the batch
// ---------------------------------------------------------------------------
struct MCResult {
    double price{0.0};
    double std_error{0.0};
    double delta{0.0};
};

// ---------------------------------------------------------------------------
// Option parameters for batch MC
// ---------------------------------------------------------------------------
struct MCOptionParams {
    double spot;
    double strike;
    double rate;
    double vol;
    double time_years;
    int    is_call;  // 1 = call, 0 = put
};

// ---------------------------------------------------------------------------
// Error codes
// ---------------------------------------------------------------------------
enum class GPUError : int {
    Ok              =  0,
    InvalidInput    = -1,
    KernelLaunch    = -2,
    DeviceMemory    = -3,
    NotAvailable    = -4,
};

// ---------------------------------------------------------------------------
// Batch Monte Carlo pricing
// ---------------------------------------------------------------------------
/// Price a batch of European options using GPU Monte Carlo.
///
/// @param params      Array of option parameters (host memory).
/// @param n_options   Number of options.
/// @param n_paths     Simulation paths per option.
/// @param seed        RNG seed.
/// @param results     Pre-allocated output array (host memory).
/// @return            GPUError::Ok on success.
GPUError monte_carlo_batch(const MCOptionParams* params,
                           size_t n_options,
                           uint64_t n_paths,
                           uint64_t seed,
                           MCResult* results);

// ---------------------------------------------------------------------------
// VaR via historical simulation
// ---------------------------------------------------------------------------
/// Compute Value-at-Risk using GPU-accelerated historical simulation.
///
/// @param returns     Array of historical returns (host memory).
/// @param n_returns   Number of return observations.
/// @param portfolio_value  Current portfolio value.
/// @param confidence  Confidence level (e.g. 0.95 or 0.99).
/// @param var_out     Output: VaR estimate.
/// @return            GPUError::Ok on success.
GPUError var_historical(const double* returns,
                        size_t n_returns,
                        double portfolio_value,
                        double confidence,
                        double* var_out);

}  // namespace tsar::gpu
