// =============================================================================
// test_monte_carlo.cpp — Unit tests for GPU Monte Carlo + Portfolio Opt stubs
// =============================================================================

#include "tsar/gpu/monte_carlo.h"
#include "tsar/gpu/portfolio_opt.h"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <format>
#include <numeric>
#include <vector>

// ---------------------------------------------------------------------------
// Test helper
// ---------------------------------------------------------------------------
static int tests_run    = 0;
static int tests_passed = 0;

#define TEST(name)                                                             \
    do {                                                                       \
        ++tests_run;                                                           \
        std::printf("  %-50s ", #name);                                        \
        try {                                                                  \
            test_##name();                                                     \
            ++tests_passed;                                                    \
            std::printf("✅\n");                                                \
        } catch (const std::exception& e) {                                    \
            std::printf("❌ %s\n", e.what());                                   \
        }                                                                      \
    } while (0)

#define ASSERT_NEAR(a, b, tol)                                                 \
    do {                                                                       \
        if (std::abs((a) - (b)) > (tol)) {                                     \
            throw std::runtime_error(                                          \
                std::format("ASSERT_NEAR failed: {} vs {} (tol {})", a, b, tol)); \
        }                                                                      \
    } while (0)

#define ASSERT_TRUE(expr)                                                      \
    do {                                                                       \
        if (!(expr)) throw std::runtime_error("ASSERT_TRUE: " #expr);          \
    } while (0)

#define ASSERT_FALSE(expr)                                                     \
    do {                                                                       \
        if ((expr)) throw std::runtime_error("ASSERT_FALSE: " #expr);           \
    } while (0)

// ---------------------------------------------------------------------------
// Tests: Monte Carlo batch pricing
// ---------------------------------------------------------------------------
using namespace tsar::gpu;

void test_mc_batch_basic() {
    std::vector<MCOptionParams> params = {
        {/*spot=*/100.0, /*strike=*/105.0, /*rate=*/0.05, /*vol=*/0.20,
         /*time_years=*/1.0, /*is_call=*/1},
        {/*spot=*/100.0, /*strike=*/95.0, /*rate=*/0.05, /*vol=*/0.20,
         /*time_years=*/1.0, /*is_call=*/0},
        {/*spot=*/50.0, /*strike=*/55.0, /*rate=*/0.03, /*vol=*/0.30,
         /*time_years=*/0.5, /*is_call=*/1},
    };

    std::vector<MCResult> results(params.size());
    auto err = monte_carlo_batch(params.data(), params.size(),
                                 10000, 42, results.data());
    ASSERT_TRUE(err == GPUError::Ok);

    // All prices should be non-negative
    for (size_t i = 0; i < results.size(); ++i) {
        ASSERT_TRUE(results[i].price >= 0.0);
    }
}

void test_mc_standard_error() {
    // Standard error should decrease with more paths
    MCOptionParams param = {
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time_years = 1.0, .is_call = 1
    };

    MCResult r1, r2;
    monte_carlo_batch(&param, 1, 1000,  42, &r1);
    monte_carlo_batch(&param, 1, 100000, 42, &r2);

    // Standard error should be smaller with more paths
    ASSERT_TRUE(r2.std_error < r1.std_error);
}

void test_mc_delta_range() {
    // Call delta should be in [0, 1], put delta in [-1, 0]
    MCOptionParams call_param = {
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time_years = 1.0, .is_call = 1
    };
    MCOptionParams put_param = call_param;
    put_param.is_call = 0;

    MCResult call_result, put_result;
    monte_carlo_batch(&call_param, 1, 50000, 42, &call_result);
    monte_carlo_batch(&put_param,  1, 50000, 42, &put_result);

    // ATM call delta ≈ 0.6, ATM put delta ≈ -0.4
    ASSERT_TRUE(call_result.delta > 0.0 && call_result.delta < 1.0);
    ASSERT_TRUE(put_result.delta < 0.0 && put_result.delta > -1.0);
}

void test_mc_null_params() {
    MCResult r;
    ASSERT_TRUE(monte_carlo_batch(nullptr, 1, 100, 42, &r) == GPUError::InvalidInput);
    ASSERT_TRUE(monte_carlo_batch(nullptr, 0, 100, 42, &r) == GPUError::InvalidInput);
}

void test_mc_zero_paths() {
    MCOptionParams param = {
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time_years = 1.0, .is_call = 1
    };
    MCResult r;
    ASSERT_TRUE(monte_carlo_batch(&param, 1, 0, 42, &r) == GPUError::InvalidInput);
}

// ---------------------------------------------------------------------------
// Tests: VaR historical simulation
// ---------------------------------------------------------------------------
void test_var_historical_basic() {
    std::vector<double> returns = {
        0.01, -0.02, 0.015, -0.005, 0.008,
        -0.01, 0.003, -0.012, 0.007, 0.002,
        -0.008, 0.005, -0.003, 0.011, -0.006,
    };

    double portfolio_value = 100000.0;
    double var_out = 0.0;

    auto err = var_historical(returns.data(), returns.size(),
                              portfolio_value, 0.95, &var_out);
    ASSERT_TRUE(err == GPUError::Ok);
    ASSERT_TRUE(var_out >= 0.0);
    // VaR should be non-trivial (not zero)
    ASSERT_TRUE(var_out > 0.0);
}

void test_var_historical_null() {
    double var_out;
    ASSERT_TRUE(var_historical(nullptr, 10, 100000, 0.95, &var_out) == GPUError::InvalidInput);
}

// ---------------------------------------------------------------------------
// Tests: Portfolio optimization (stub mode)
// ---------------------------------------------------------------------------
void test_risk_parity_basic() {
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

    auto err = risk_parity(volatilities.data(), covariance.data(),
                           n_assets, &result);
    ASSERT_TRUE(err == OptError::Ok);

    // Weights should sum to ~1
    double sum = std::accumulate(weights.begin(), weights.end(), 0.0);
    ASSERT_NEAR(sum, 1.0, 0.01);

    // Lower-volatility assets get higher weights
    ASSERT_TRUE(weights[2] > weights[0]);  // vol=0.10 > vol=0.20
    ASSERT_TRUE(weights[2] > weights[1]);  // vol=0.10 > vol=0.30
    ASSERT_TRUE(weights[0] > weights[1]);  // vol=0.20 > vol=0.30
}

void test_risk_parity_equal_vols() {
    // If all vols are equal, weights should be equal
    std::vector<double> covariance = {
        0.04, 0.0, 0.0,
        0.0, 0.04, 0.0,
        0.0, 0.0, 0.04
    };
    std::vector<double> volatilities = {0.20, 0.20, 0.20};
    size_t n_assets = 3;

    std::vector<double> weights(n_assets, 0.0);
    OptResult result;
    result.weights = weights.data();

    risk_parity(volatilities.data(), covariance.data(), n_assets, &result);

    for (size_t i = 0; i < n_assets; ++i) {
        ASSERT_NEAR(weights[i], 1.0 / 3.0, 0.001);
    }
}

void test_risk_parity_invalid_vol() {
    std::vector<double> cov = {0.04, 0.0, 0.0, 0.04};
    std::vector<double> vols = {0.20, -0.10};  // Negative vol
    std::vector<double> weights(2, 0.0);
    OptResult result;
    result.weights = weights.data();

    ASSERT_TRUE(risk_parity(vols.data(), cov.data(), 2, &result) == OptError::InvalidInput);
}

void test_mean_variance_stub() {
    std::vector<double> expected_returns = {0.10, 0.12, 0.08};
    std::vector<double> covariance = {
        0.04, 0.006, 0.002,
        0.006, 0.09, 0.009,
        0.002, 0.009, 0.01
    };
    std::vector<double> weights(3, 0.0);
    OptResult result;
    result.weights = weights.data();

    auto err = mean_variance_opt(expected_returns.data(), covariance.data(),
                                 3, 0.10, &result);
    ASSERT_TRUE(err == OptError::Ok);

    // Stub returns equal weights
    double sum = std::accumulate(weights.begin(), weights.end(), 0.0);
    ASSERT_NEAR(sum, 1.0, 0.01);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
int main() {
    std::printf("\n=== TSAR GPU / Monte Carlo Tests ===\n\n");

    // Monte Carlo
    TEST(mc_batch_basic);
    TEST(mc_standard_error);
    TEST(mc_delta_range);
    TEST(mc_null_params);
    TEST(mc_zero_paths);

    // VaR
    TEST(var_historical_basic);
    TEST(var_historical_null);

    // Portfolio opt
    TEST(risk_parity_basic);
    TEST(risk_parity_equal_vols);
    TEST(risk_parity_invalid_vol);
    TEST(mean_variance_stub);

    std::printf("\n%d/%d tests passed\n\n", tests_passed, tests_run);
    return (tests_passed == tests_run) ? 0 : 1;
}
