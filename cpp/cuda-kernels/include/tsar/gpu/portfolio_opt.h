#pragma once
// =============================================================================
// tsar/gpu/portfolio_opt.h — GPU-accelerated portfolio optimisation
// =============================================================================
//
// Mean-variance optimisation and risk-parity allocation using CUDA.
// Falls back to CPU stub when CUDA is not available.
// =============================================================================

#include <cstdint>
#include <cstddef>

namespace tsar::gpu {

// ---------------------------------------------------------------------------
// Optimisation result
// ---------------------------------------------------------------------------
struct OptResult {
    double* weights;       // Caller-allocated, length = n_assets. MUST be set before calling.
    double  portfolio_vol{0.0};
    double  portfolio_return{0.0};
    double  sharpe_ratio{0.0};
    int     iterations{0};
    int     converged{0};  // 1 = converged, 0 = max iterations
};

// ---------------------------------------------------------------------------
// Error codes
// ---------------------------------------------------------------------------
enum class OptError : int {
    Ok              =  0,
    InvalidInput    = -1,
    NotConverged    = -2,
    KernelLaunch    = -3,
    DeviceMemory    = -4,
    NotAvailable    = -5,
};

// ---------------------------------------------------------------------------
// Mean-Variance Optimisation (Markowitz)
// ---------------------------------------------------------------------------
/// Compute minimum-variance portfolio for given expected returns and
/// covariance matrix.
///
/// @param expected_returns  Array of expected returns (length n_assets).
/// @param cov_matrix        Row-major covariance matrix (n_assets × n_assets).
/// @param n_assets          Number of assets.
/// @param target_return     Target portfolio return (0 = min-variance).
/// @param result            Output weights and stats.
/// @return                  OptError::Ok on success.
OptError mean_variance_opt(const double* expected_returns,
                           const double* cov_matrix,
                           size_t n_assets,
                           double target_return,
                           OptResult* result);

// ---------------------------------------------------------------------------
// Risk-Parity Allocation
// ---------------------------------------------------------------------------
/// Compute risk-parity weights: each asset contributes equally to portfolio
/// risk.
///
/// @param volatilities  Array of asset volatilities (length n_assets).
/// @param cov_matrix    Row-major covariance matrix (n_assets × n_assets).
/// @param n_assets      Number of assets.
/// @param result        Output weights and stats.
/// @return              OptError::Ok on success.
OptError risk_parity(const double* volatilities,
                     const double* cov_matrix,
                     size_t n_assets,
                     OptResult* result);

}  // namespace tsar::gpu
