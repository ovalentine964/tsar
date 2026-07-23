// =============================================================================
// portfolio_opt.cu — GPU portfolio optimisation (CUDA)
// =============================================================================
//
// Stub: real CUDA kernel will be implemented when GPU hardware is available.
// =============================================================================

#ifdef TSAR_HAS_CUDA

#include "tsar/gpu/portfolio_opt.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <cstring>
#include <cmath>

namespace tsar::gpu {

// ---------------------------------------------------------------------------
// Mean-Variance kernel — gradient descent on the efficient frontier
// ---------------------------------------------------------------------------
__global__ void mv_kernel(const double* __restrict__ expected_returns,
                          const double* __restrict__ cov_matrix,
                          double* __restrict__ weights,
                          size_t n_assets,
                          double target_return,
                          double learning_rate,
                          int max_iter,
                          OptResult* result) {
    // Each thread handles one asset's weight update
    size_t i = threadIdx.x + blockIdx.x * blockDim.x;
    if (i >= n_assets) return;

    // Initialise equal weights
    weights[i] = 1.0 / (double)n_assets;

    // Stub: gradient descent loop omitted for brevity
    // Production version implements projected gradient descent with
    // constraints: Σw_i = 1, w_i ≥ 0, w'μ ≥ target_return

    if (i == 0) {
        result->portfolio_vol    = 0.0;
        result->portfolio_return = target_return;
        result->sharpe_ratio     = 0.0;
        result->iterations       = 0;
        result->converged        = 0;  // Not yet implemented
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
OptError mean_variance_opt(const double* expected_returns,
                           const double* cov_matrix,
                           size_t n_assets,
                           double target_return,
                           OptResult* result) {
    if (!expected_returns || !cov_matrix || !result || n_assets == 0) {
        return OptError::InvalidInput;
    }

    // TODO: allocate device memory, launch kernel, copy back
    // Stub: fill result with equal weights
    result->portfolio_vol    = 0.0;
    result->portfolio_return = target_return;
    result->sharpe_ratio     = 0.0;
    result->iterations       = 0;
    result->converged        = 0;

    return OptError::Ok;
}

OptError risk_parity(const double* volatilities,
                     const double* cov_matrix,
                     size_t n_assets,
                     OptResult* result) {
    if (!volatilities || !cov_matrix || !result || n_assets == 0) {
        return OptError::InvalidInput;
    }

    // TODO: iterative risk-budgeting kernel
    // Stub: inverse-volatility weights
    double inv_vol_sum = 0.0;
    for (size_t i = 0; i < n_assets; ++i) {
        inv_vol_sum += 1.0 / volatilities[i];
    }

    result->portfolio_vol    = 0.0;
    result->portfolio_return = 0.0;
    result->sharpe_ratio     = 0.0;
    result->iterations       = 0;
    result->converged        = 1;  // Simple formula, always "converges"

    return OptError::Ok;
}

}  // namespace tsar::gpu

#endif  // TSAR_HAS_CUDA
