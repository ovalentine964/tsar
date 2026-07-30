// =============================================================================
// test_cffi.cpp — Integration tests for the C FFI layer
// =============================================================================
//
// Tests the C ABI exposed by tsar_cffi.h — validates that Python/Rust
// consumers can correctly interact with the C++ engine through the FFI.
// =============================================================================

#include "tsar/cffi/tsar_cffi.h"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <format>
#include <cstring>
#include <string>

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

#define ASSERT_EQ(a, b)                                                        \
    do {                                                                       \
        if ((a) != (b)) {                                                      \
            throw std::runtime_error(                                          \
                std::format("ASSERT_EQ failed: {} vs {}", (int64_t)(a), (int64_t)(b))); \
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

// ---------------------------------------------------------------------------
// Tests: Pricing Engine C FFI
// ---------------------------------------------------------------------------
void test_pricing_engine_lifecycle() {
    TsarPricingEngine engine = tsar_pricing_engine_new();
    ASSERT_TRUE(engine != nullptr);
    tsar_pricing_engine_free(engine);
}

void test_pricing_engine_init_and_discount() {
    TsarPricingEngine engine = tsar_pricing_engine_new();

    TsarYieldPoint curve[] = {
        {0.25, 0.04}, {0.5, 0.042}, {1.0, 0.045}, {2.0, 0.048}, {5.0, 0.05}
    };

    int rc = tsar_pricing_engine_init(engine, curve, 5);
    ASSERT_EQ(rc, TSAR_OK);

    double df = 0.0;
    rc = tsar_pricing_engine_discount(engine, 1.0, &df);
    ASSERT_EQ(rc, TSAR_OK);
    ASSERT_NEAR(df, std::exp(-0.045), 1e-6);

    tsar_pricing_engine_free(engine);
}

void test_pricing_engine_forward_rate() {
    TsarPricingEngine engine = tsar_pricing_engine_new();

    TsarYieldPoint curve[] = {{1.0, 0.04}, {2.0, 0.05}};
    tsar_pricing_engine_init(engine, curve, 2);

    double fwd = 0.0;
    int rc = tsar_pricing_engine_forward_rate(engine, 1.0, 2.0, &fwd);
    ASSERT_EQ(rc, TSAR_OK);
    // f = (0.05*2 - 0.04*1) / (2-1) = 0.06
    ASSERT_NEAR(fwd, 0.06, 1e-10);

    tsar_pricing_engine_free(engine);
}

void test_pricing_engine_not_initialized() {
    TsarPricingEngine engine = tsar_pricing_engine_new();
    double df;
    int rc = tsar_pricing_engine_discount(engine, 1.0, &df);
    ASSERT_EQ(rc, TSAR_ERR_NOT_INITIALIZED);
    tsar_pricing_engine_free(engine);
}

void test_pricing_engine_null() {
    double df;
    ASSERT_EQ(tsar_pricing_engine_discount(nullptr, 1.0, &df), TSAR_ERR_INVALID_INPUT);
    ASSERT_EQ(tsar_pricing_engine_init(nullptr, nullptr, 0), TSAR_ERR_INVALID_INPUT);
}

// ---------------------------------------------------------------------------
// Tests: Option Pricer C FFI
// ---------------------------------------------------------------------------
void test_option_pricer_bs_call() {
    TsarPricingEngine engine = tsar_pricing_engine_new();
    TsarYieldPoint curve[] = {{1.0, 0.05}};
    tsar_pricing_engine_init(engine, curve, 1);

    TsarOptionPricer pricer = tsar_option_pricer_new(engine);
    ASSERT_TRUE(pricer != nullptr);

    TsarOptionSpec spec = {
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time_years = 1.0, .is_call = 1,
        .is_european = 1, .dividend_yield = 0.0
    };

    TsarOptionResult result;
    int rc = tsar_option_pricer_bs(pricer, &spec, &result);
    ASSERT_EQ(rc, TSAR_OK);
    ASSERT_NEAR(result.price, 10.45, 0.50);
    ASSERT_NEAR(result.delta, 0.63, 0.05);

    tsar_option_pricer_free(pricer);
    tsar_pricing_engine_free(engine);
}

void test_option_pricer_bs_put() {
    TsarPricingEngine engine = tsar_pricing_engine_new();
    TsarYieldPoint curve[] = {{1.0, 0.05}};
    tsar_pricing_engine_init(engine, curve, 1);

    TsarOptionPricer pricer = tsar_option_pricer_new(engine);

    TsarOptionSpec spec = {
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time_years = 1.0, .is_call = 0,
        .is_european = 1, .dividend_yield = 0.0
    };

    TsarOptionResult result;
    int rc = tsar_option_pricer_bs(pricer, &spec, &result);
    ASSERT_EQ(rc, TSAR_OK);

    // Put delta should be negative
    ASSERT_TRUE(result.delta < 0.0);
    // Gamma and vega should be positive
    ASSERT_TRUE(result.gamma > 0.0);
    ASSERT_TRUE(result.vega > 0.0);

    tsar_option_pricer_free(pricer);
    tsar_pricing_engine_free(engine);
}

void test_option_pricer_batch() {
    TsarPricingEngine engine = tsar_pricing_engine_new();
    TsarYieldPoint curve[] = {{1.0, 0.05}};
    tsar_pricing_engine_init(engine, curve, 1);

    TsarOptionPricer pricer = tsar_option_pricer_new(engine);

    TsarOptionSpec specs[3] = {
        {100.0, 90.0, 0.05, 0.20, 1.0, 1, 1, 0.0},
        {100.0, 100.0, 0.05, 0.20, 1.0, 1, 1, 0.0},
        {100.0, 110.0, 0.05, 0.20, 1.0, 1, 1, 0.0},
    };

    TsarOptionResult results[3];
    int rc = tsar_option_pricer_batch(pricer, specs, 3, results);
    ASSERT_EQ(rc, TSAR_OK);

    // Prices should be monotonically decreasing as strike increases
    ASSERT_TRUE(results[0].price > results[1].price);
    ASSERT_TRUE(results[1].price > results[2].price);

    tsar_option_pricer_free(pricer);
    tsar_pricing_engine_free(engine);
}

void test_option_pricer_implied_vol() {
    TsarPricingEngine engine = tsar_pricing_engine_new();
    TsarYieldPoint curve[] = {{1.0, 0.05}};
    tsar_pricing_engine_init(engine, curve, 1);

    TsarOptionPricer pricer = tsar_option_pricer_new(engine);

    // Price at known vol
    TsarOptionSpec spec = {
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.25, .time_years = 1.0, .is_call = 1,
        .is_european = 1, .dividend_yield = 0.0
    };
    TsarOptionResult priced;
    tsar_option_pricer_bs(pricer, &spec, &priced);

    // Solve back for implied vol
    TsarOptionSpec solver_spec = spec;
    solver_spec.vol = 0.20;  // Wrong initial guess
    double ivol = 0.0;
    int rc = tsar_option_pricer_ivol(pricer, priced.price, &solver_spec, &ivol);
    ASSERT_EQ(rc, TSAR_OK);
    ASSERT_NEAR(ivol, 0.25, 1e-6);

    tsar_option_pricer_free(pricer);
    tsar_pricing_engine_free(engine);
}

void test_option_pricer_mc() {
    TsarPricingEngine engine = tsar_pricing_engine_new();
    TsarYieldPoint curve[] = {{1.0, 0.05}};
    tsar_pricing_engine_init(engine, curve, 1);

    TsarOptionPricer pricer = tsar_option_pricer_new(engine);

    TsarOptionSpec spec = {
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time_years = 1.0, .is_call = 1,
        .is_european = 1, .dividend_yield = 0.0
    };

    TsarOptionResult result;
    int rc = tsar_option_pricer_mc(pricer, &spec, 100000, 42, &result);
    ASSERT_EQ(rc, TSAR_OK);

    // MC price should be close to BS price (~10.45)
    ASSERT_NEAR(result.price, 10.45, 1.0);

    tsar_option_pricer_free(pricer);
    tsar_pricing_engine_free(engine);
}

// ---------------------------------------------------------------------------
// Tests: FIX Gateway C FFI
// ---------------------------------------------------------------------------
void test_fix_gateway_lifecycle() {
    TsarFIXGateway gw = tsar_fix_gateway_new();
    ASSERT_TRUE(gw != nullptr);
    ASSERT_EQ(tsar_fix_gateway_session_count(gw), (size_t)0);
    ASSERT_EQ(tsar_fix_gateway_any_connected(gw), 0);
    tsar_fix_gateway_free(gw);
}

void test_fix_gateway_add_session() {
    TsarFIXGateway gw = tsar_fix_gateway_new();

    size_t index = 999;
    int rc = tsar_fix_gateway_add_session(gw, "SENDER", "TARGET",
                                           "127.0.0.1", 9876, &index);
    ASSERT_EQ(rc, TSAR_OK);
    ASSERT_EQ(index, (size_t)0);
    ASSERT_EQ(tsar_fix_gateway_session_count(gw), (size_t)1);

    tsar_fix_gateway_free(gw);
}

void test_fix_gateway_logon_and_send() {
    TsarFIXGateway gw = tsar_fix_gateway_new();

    size_t index;
    tsar_fix_gateway_add_session(gw, "SENDER", "TARGET",
                                  "127.0.0.1", 9876, &index);

    int rc = tsar_fix_gateway_logon_all(gw);
    ASSERT_EQ(rc, TSAR_OK);
    ASSERT_EQ(tsar_fix_gateway_any_connected(gw), 1);

    char order_id[64] = {};
    rc = tsar_fix_gateway_send_order(gw, index, "BTC/USDT",
                                      1,  // buy
                                      2,  // limit
                                      50000.0, 0.1,
                                      order_id, sizeof(order_id));
    ASSERT_EQ(rc, TSAR_OK);
    ASSERT_TRUE(std::strlen(order_id) > 0);

    tsar_fix_gateway_free(gw);
}

void test_fix_gateway_send_not_logged_on() {
    TsarFIXGateway gw = tsar_fix_gateway_new();

    size_t index;
    tsar_fix_gateway_add_session(gw, "S", "T", "127.0.0.1", 9876, &index);

    char order_id[64] = {};
    int rc = tsar_fix_gateway_send_order(gw, index, "X",
                                          1, 2, 100.0, 1.0,
                                          order_id, sizeof(order_id));
    ASSERT_EQ(rc, TSAR_ERR_NOT_CONNECTED);

    tsar_fix_gateway_free(gw);
}

void test_fix_gateway_cancel() {
    TsarFIXGateway gw = tsar_fix_gateway_new();

    size_t index;
    tsar_fix_gateway_add_session(gw, "S", "T", "127.0.0.1", 9876, &index);
    tsar_fix_gateway_logon_all(gw);

    int rc = tsar_fix_gateway_cancel_order(gw, index, "ORDER-001",
                                            "BTC/USDT", 1);
    ASSERT_EQ(rc, TSAR_OK);

    tsar_fix_gateway_free(gw);
}

void test_fix_gateway_null() {
    ASSERT_EQ(tsar_fix_gateway_session_count(nullptr), (size_t)0);
    ASSERT_EQ(tsar_fix_gateway_any_connected(nullptr), 0);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
int main() {
    std::printf("\n=== TSAR CFFI Integration Tests ===\n\n");

    // Pricing Engine
    TEST(pricing_engine_lifecycle);
    TEST(pricing_engine_init_and_discount);
    TEST(pricing_engine_forward_rate);
    TEST(pricing_engine_not_initialized);
    TEST(pricing_engine_null);

    // Option Pricer
    TEST(option_pricer_bs_call);
    TEST(option_pricer_bs_put);
    TEST(option_pricer_batch);
    TEST(option_pricer_implied_vol);
    TEST(option_pricer_mc);

    // FIX Gateway
    TEST(fix_gateway_lifecycle);
    TEST(fix_gateway_add_session);
    TEST(fix_gateway_logon_and_send);
    TEST(fix_gateway_send_not_logged_on);
    TEST(fix_gateway_cancel);
    TEST(fix_gateway_null);

    std::printf("\n%d/%d tests passed\n\n", tests_passed, tests_run);
    return (tests_passed == tests_run) ? 0 : 1;
}
