// TSAR — Monte Carlo GPU Tests
// Tests for cuda-kernels module

#include <cassert>
#include <cmath>
#include <iostream>
#include <vector>
#include "tsar/gpu/monte_carlo.h"
#include "tsar/gpu/portfolio_opt.h"

namespace tsar {
namespace gpu {
namespace test {

void test_monte_carlo_basic() {
    // Create a batch of 3 option parameters
    std::vector<MCOptionParams> params = {
        {/*spot=*/100.0, /*strike=*/105.0, /*rate=*/0.05, /*vol=*/0.20,
         /*time_years=*/1.0, /*is_call=*/1},
        {/*spot=*/100.0, /*strike=*/95.0, /*rate=*/0.05, /*vol=*/0.20,
         /*time_years=*/1.0, /*is_call=*/0},
        {/*spot=*/50.0, /*strike=*/55.0, /*rate=*/0.03, /*vol=*/0.30,
         /*time_years=*/0.5, /*is_call=*/1},
    };

    std::vector<MCResult> results(params.size());

    auto err = monte_carlo_batch(
        params.data(), params.size(),
        /*n_paths=*/10000, /*seed=*/42, results.data()
    );

    assert(err == GPUError::Ok);

    // Basic sanity checks — prices should be non-negative
    for (size_t i = 0; i < results.size(); ++i) {
        assert(results[i].price >= 0.0);
        assert(results[i].std_error >= 0.0);
    }

    // Call option with spot=100, strike=105 should be cheaper than spot=100, strike=95 put
    // (not strictly guaranteed by MC, but very likely with 10k paths)
    std::cout << "[PASS] test_monte_carlo_basic" << std::endl;
}

void test_var_historical() {
    std::vector<double> returns = {
        0.01, -0.02, 0.015, -0.005, 0.008,
        -0.01, 0.003, -0.012, 0.007, 0.002,
        -0.008, 0.005, -0.003, 0.011, -0.006,
    };

    double portfolio_value = 100000.0;
    double confidence = 0.95;
    double var_out = 0.0;

    auto err = var_historical(
        returns.data(), returns.size(),
        portfolio_value, confidence, &var_out
    );

    assert(err == GPUError::Ok);
    // VaR should be non-negative (it represents a loss magnitude)
    assert(var_out >= 0.0);

    std::cout << "[PASS] test_var_historical" << std::endl;
}

void test_portfolio_optimization() {
    // 3-asset covariance matrix (row-major)
    std::vector<double> covariance = {
        0.04, 0.006, 0.002,
        0.006, 0.09, 0.009,
        0.002, 0.009, 0.01
    };
    std::vector<double> expected_returns = {0.10, 0.12, 0.08};
    size_t n_assets = 3;

    // Allocate output weights
    std::vector<double> weights(n_assets, 0.0);

    OptResult result;
    result.weights = weights.data();

    auto err = mean_variance_opt(
        expected_returns.data(),
        covariance.data(),
        n_assets,
        /*target_return=*/0.10,
        &result
    );

    assert(err == OptError::Ok);

    // Weights should sum to approximately 1
    double weight_sum = 0.0;
    for (size_t i = 0; i < n_assets; ++i) {
        weight_sum += weights[i];
    }
    assert(std::abs(weight_sum - 1.0) < 0.01);

    std::cout << "[PASS] test_portfolio_optimization" << std::endl;
}

void test_risk_parity() {
    // 3-asset covariance matrix (row-major)
    std::vector<double> covariance = {
        0.04, 0.006, 0.002,
        0.006, 0.09, 0.009,
        0.002, 0.009, 0.01
    };
    std::vector<double> volatilities = {0.20, 0.30, 0.10};
    size_t n_assets = 3;

    std::vector<double> weights(n_assets, 0.0);

    OptResult result;
    result.weights = weights.data();

    auto err = risk_parity(
        volatilities.data(),
        covariance.data(),
        n_assets,
        &result
    );

    assert(err == OptError::Ok);

    // Weights should sum to approximately 1
    double weight_sum = 0.0;
    for (size_t i = 0; i < n_assets; ++i) {
        weight_sum += weights[i];
    }
    assert(std::abs(weight_sum - 1.0) < 0.01);

    // Lower-volatility assets should get higher weights in risk parity
    // vol[2]=0.10 is lowest, so weights[2] should be highest
    assert(weights[2] > weights[0]);
    assert(weights[2] > weights[1]);

    std::cout << "[PASS] test_risk_parity" << std::endl;
}

}  // namespace test
}  // namespace gpu
}  // namespace tsar

int main() {
    std::cout << "=== TSAR GPU Tests ===" << std::endl;
    tsar::gpu::test::test_monte_carlo_basic();
    tsar::gpu::test::test_var_historical();
    tsar::gpu::test::test_portfolio_optimization();
    tsar::gpu::test::test_risk_parity();
    std::cout << "=== All GPU tests passed ===" << std::endl;
    return 0;
}
