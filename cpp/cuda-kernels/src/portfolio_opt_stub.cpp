// =============================================================================
// portfolio_opt_stub.cpp — CPU stub for portfolio optimisation when CUDA unavailable
// =============================================================================
//
// Implements:
//   - Risk-parity: inverse-volatility weighting (closed-form approximation)
//   - Mean-variance: equal-weight stub with correct normalization
//
// Production version uses GPU gradient descent; this stub ensures the
// system can link and test without CUDA.
// =============================================================================

#ifndef TSAR_HAS_CUDA

#include "tsar/gpu/portfolio_opt.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <vector>

namespace tsar::gpu {

// ---------------------------------------------------------------------------
// Mean-Variance Optimisation (stub: equal-weight)
// ---------------------------------------------------------------------------
OptError mean_variance_opt(const double* /*expected_returns*/,
                           const double* /*cov_matrix*/,
                           size_t n_assets,
                           double target_return,
                           OptResult* result) {
    if (!result || n_assets == 0) {
        return OptError::InvalidInput;
    }

    // Stub: equal-weight portfolio
    double w = 1.0 / static_cast<double>(n_assets);
    for (size_t i = 0; i < n_assets; ++i) {
        result->weights[i] = w;
    }

    result->portfolio_vol    = 0.0;  // TODO: compute from cov_matrix
    result->portfolio_return = target_return;
    result->sharpe_ratio     = 0.0;
    result->iterations       = 0;
    result->converged        = 0;  // Stub: not actually optimized

    return OptError::Ok;
}

// ---------------------------------------------------------------------------
// Risk-Parity Allocation (inverse-volatility weighting)
// ---------------------------------------------------------------------------
OptError risk_parity(const double* volatilities,
                     const double* /*cov_matrix*/,
                     size_t n_assets,
                     OptResult* result) {
    if (!volatilities || !result || n_assets == 0) {
        return OptError::InvalidInput;
    }

    // Validate: all volatilities must be positive
    for (size_t i = 0; i < n_assets; ++i) {
        if (volatilities[i] <= 0.0) {
            return OptError::InvalidInput;
        }
    }

    // Inverse-volatility weights: w_i = (1/σ_i) / Σ(1/σ_j)
    // This is the closed-form risk-parity solution for uncorrelated assets.
    // With correlation, iterative optimization is needed (GPU kernel).
    double inv_vol_sum = 0.0;
    for (size_t i = 0; i < n_assets; ++i) {
        inv_vol_sum += 1.0 / volatilities[i];
    }

    for (size_t i = 0; i < n_assets; ++i) {
        result->weights[i] = (1.0 / volatilities[i]) / inv_vol_sum;
    }

    // Compute portfolio volatility (approximate: assumes diagonal cov)
    // σ_p = sqrt(Σ w_i^2 * σ_i^2) for uncorrelated case
    double port_var = 0.0;
    for (size_t i = 0; i < n_assets; ++i) {
        double wivol = result->weights[i] * volatilities[i];
        port_var += wivol * wivol;
    }
    result->portfolio_vol    = std::sqrt(port_var);
    result->portfolio_return = 0.0;  // Requires expected returns
    result->sharpe_ratio     = 0.0;
    result->iterations       = 1;    // Closed-form, one "iteration"
    result->converged        = 1;    // Always converges

    return OptError::Ok;
}

}  // namespace tsar::gpu

#endif  // !TSAR_HAS_CUDA
