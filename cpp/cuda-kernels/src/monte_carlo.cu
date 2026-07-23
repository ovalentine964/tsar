// =============================================================================
// monte_carlo.cu — GPU Monte Carlo option pricing (CUDA)
// =============================================================================
//
// Stub: real CUDA kernel will be implemented when GPU hardware is available.
// The header API is the contract; this file is the placeholder.
// =============================================================================

#ifdef TSAR_HAS_CUDA

#include "tsar/gpu/monte_carlo.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>

#include <cstdio>
#include <cstring>

namespace tsar::gpu {

// ---------------------------------------------------------------------------
// CUDA kernel — one thread per option-path pair, block-reduce to aggregate
// ---------------------------------------------------------------------------
__global__ void mc_kernel(const MCOptionParams* __restrict__ params,
                          MCResult* __restrict__ results,
                          uint64_t n_paths,
                          uint64_t seed,
                          size_t n_options) {
    size_t opt_idx = blockIdx.x;
    if (opt_idx >= n_options) return;

    const MCOptionParams& p = params[opt_idx];

    double drift     = (p.rate - 0.5 * p.vol * p.vol) * p.time_years;
    double diffusion = p.vol * sqrt(p.time_years);
    double discount  = exp(-p.rate * p.time_years);

    // Each thread accumulates partial payoffs
    double local_sum  = 0.0;
    double local_sq   = 0.0;

    curandStatePhilox4_32_10_t rng;
    curand_init(seed, opt_idx * blockDim.x + threadIdx.x, 0, &rng);

    for (uint64_t i = threadIdx.x; i < n_paths; i += blockDim.x) {
        double z  = curand_normal_double(&rng);
        double ST = p.spot * exp(drift + diffusion * z);
        double payoff = p.is_call ? fmax(ST - p.strike, 0.0)
                                  : fmax(p.strike - ST, 0.0);
        local_sum += payoff;
        local_sq  += payoff * payoff;
    }

    // Block-level reduction (simplified — production code uses warp shuffles)
    // Omitted for brevity; the stub returns placeholder results.
    if (threadIdx.x == 0) {
        double mean = local_sum / (double)n_paths;
        results[opt_idx].price     = discount * mean;
        results[opt_idx].std_error = 0.0;  // TODO: proper reduction
        results[opt_idx].delta     = 0.0;  // TODO: pathwise delta
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
GPUError monte_carlo_batch(const MCOptionParams* params,
                           size_t n_options,
                           uint64_t n_paths,
                           uint64_t seed,
                           MCResult* results) {
    if (!params || !results || n_options == 0 || n_paths == 0) {
        return GPUError::InvalidInput;
    }

    MCOptionParams* d_params  = nullptr;
    MCResult*       d_results = nullptr;

    cudaMalloc(&d_params,  n_options * sizeof(MCOptionParams));
    cudaMalloc(&d_results, n_options * sizeof(MCResult));

    cudaMemcpy(d_params, params, n_options * sizeof(MCOptionParams),
               cudaMemcpyHostToDevice);

    constexpr int block_size = 256;
    mc_kernel<<<(int)n_options, block_size>>>(
        d_params, d_results, n_paths, seed, n_options);

    cudaMemcpy(results, d_results, n_options * sizeof(MCResult),
               cudaMemcpyDeviceToHost);

    cudaFree(d_params);
    cudaFree(d_results);

    return GPUError::Ok;
}

// ---------------------------------------------------------------------------
// VaR via historical simulation
// ---------------------------------------------------------------------------
GPUError var_historical(const double* returns,
                        size_t n_returns,
                        double portfolio_value,
                        double confidence,
                        double* var_out) {
    if (!returns || !var_out || n_returns == 0) {
        return GPUError::InvalidInput;
    }

    // TODO: GPU sort + percentile
    // Stub: return placeholder
    *var_out = portfolio_value * 0.05;  // 5% placeholder
    return GPUError::Ok;
}

}  // namespace tsar::gpu

#endif  // TSAR_HAS_CUDA
