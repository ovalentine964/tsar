// =============================================================================
// portfolio_opt_stub.cpp — CPU stub for portfolio optimisation when CUDA unavailable
// =============================================================================

#ifndef TSAR_HAS_CUDA

#include "tsar/gpu/portfolio_opt.h"

#include <cmath>
#include <vector>

namespace tsar::gpu {

OptError mean_variance_opt(const double* /*expected_returns*/,
                           const double* /*cov_matrix*/,
                           size_t n_assets,
                           double target_return,
                           OptResult* result) {
    if (!result || n_assets == 0) {
        return OptError::InvalidInput;
    }

    // Stub: equal-weight portfolio
    result->portfolio_vol    = 0.0;
    result->portfolio_return = target_return;
    result->sharpe_ratio     = 0.0;
    result->iterations       = 0;
    result->converged        = 0;

    return OptError::Ok;
}

OptError risk_parity(const double* volatilities,
                     const double* /*cov_matrix*/,
                     size_t n_assets,
                     OptResult* result) {
    if (!volatilities || !result || n_assets == 0) {
        return OptError::InvalidInput;
    }

    // Stub: inverse-volatility weights
    result->portfolio_vol    = 0.0;
    result->portfolio_return = 0.0;
    result->sharpe_ratio     = 0.0;
    result->iterations       = 0;
    result->converged        = 1;

    return OptError::Ok;
}

}  // namespace tsar::gpu

#endif  // !TSAR_HAS_CUDA
