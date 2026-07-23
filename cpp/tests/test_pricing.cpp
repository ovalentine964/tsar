// =============================================================================
// test_pricing.cpp — Unit tests for PricingEngine + OptionPricer
// =============================================================================

#include "tsar/pricing/option_pricer.h"
#include "tsar/pricing/pricing_engine.h"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <format>
#include <span>
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
// Tests: PricingEngine
// ---------------------------------------------------------------------------
using namespace tsar::pricing;

void test_engine_init_empty_curve() {
    PricingEngine engine;
    auto r = engine.init({});
    ASSERT_FALSE(r.has_value());
    ASSERT_TRUE(r.error().code == PricingError::InvalidInput);
}

void test_engine_init_valid_curve() {
    PricingEngine engine;
    std::vector<YieldPoint> curve = {
        {0.25, 0.04}, {0.5, 0.042}, {1.0, 0.045}, {2.0, 0.048}, {5.0, 0.05}
    };
    auto r = engine.init(curve);
    ASSERT_TRUE(r.has_value());
    ASSERT_TRUE(engine.is_initialised());
}

void test_engine_discount_factor() {
    PricingEngine engine;
    std::vector<YieldPoint> curve = {{1.0, 0.05}};
    engine.init(curve);

    auto df = engine.discount(1.0);
    ASSERT_TRUE(df.has_value());
    // e^(-0.05 * 1) ≈ 0.9512
    ASSERT_NEAR(*df, std::exp(-0.05), 1e-10);
}

void test_engine_discount_before_init() {
    PricingEngine engine;
    auto df = engine.discount(1.0);
    ASSERT_FALSE(df.has_value());
    ASSERT_TRUE(df.error().code == PricingError::NotInitialized);
}

void test_engine_forward_rate() {
    PricingEngine engine;
    std::vector<YieldPoint> curve = {{1.0, 0.04}, {2.0, 0.05}};
    engine.init(curve);

    auto fwd = engine.forward_rate(1.0, 2.0);
    ASSERT_TRUE(fwd.has_value());
    // f = (0.05*2 - 0.04*1) / (2-1) = 0.06
    ASSERT_NEAR(*fwd, 0.06, 1e-10);
}

// ---------------------------------------------------------------------------
// Tests: OptionPricer (Black-Scholes)
// ---------------------------------------------------------------------------
void test_bs_call_at_the_money() {
    PricingEngine engine;
    std::vector<YieldPoint> curve = {{1.0, 0.05}};
    engine.init(curve);

    OptionPricer pricer(&engine);
    OptionSpec spec{
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time = 1.0, .side = OptionSide::Call,
    };

    auto r = pricer.price_european_bs(spec);
    ASSERT_TRUE(r.has_value());
    // ATM call with 20% vol, 1y, r=5% should be ~10.45
    ASSERT_NEAR(r->price, 10.45, 0.50);
    // Delta should be ~0.63
    ASSERT_NEAR(r->greeks.delta, 0.63, 0.05);
}

void test_bs_put_put_call_parity() {
    PricingEngine engine;
    std::vector<YieldPoint> curve = {{1.0, 0.05}};
    engine.init(curve);

    OptionPricer pricer(&engine);

    OptionSpec call_spec{
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time = 1.0, .side = OptionSide::Call,
    };
    OptionSpec put_spec = call_spec;
    put_spec.side = OptionSide::Put;

    auto call = pricer.price_european_bs(call_spec);
    auto put  = pricer.price_european_bs(put_spec);
    ASSERT_TRUE(call.has_value());
    ASSERT_TRUE(put.has_value());

    // Put-Call parity: C - P = S*e^(-qT) - K*e^(-rT)
    double parity = 100.0 - 100.0 * std::exp(-0.05);
    ASSERT_NEAR(call->price - put->price, parity, 1e-8);
}

void test_bs_invalid_spot() {
    PricingEngine engine;
    std::vector<YieldPoint> curve = {{1.0, 0.05}};
    engine.init(curve);

    OptionPricer pricer(&engine);
    OptionSpec spec{
        .spot = -1.0, .strike = 100.0, .rate = 0.05,
        .vol = 0.20, .time = 1.0, .side = OptionSide::Call,
    };

    auto r = pricer.price_european_bs(spec);
    ASSERT_FALSE(r.has_value());
    ASSERT_TRUE(r.error().code == PricingError::InvalidInput);
}

void test_implied_vol_roundtrip() {
    PricingEngine engine;
    std::vector<YieldPoint> curve = {{1.0, 0.05}};
    engine.init(curve);

    OptionPricer pricer(&engine);
    double true_vol = 0.25;
    OptionSpec spec{
        .spot = 100.0, .strike = 100.0, .rate = 0.05,
        .vol = true_vol, .time = 1.0, .side = OptionSide::Call,
    };

    auto priced = pricer.price_european_bs(spec);
    ASSERT_TRUE(priced.has_value());

    // Now solve back
    OptionSpec solver_spec = spec;
    solver_spec.vol = 0.20;  // Deliberate wrong initial guess
    auto iv = pricer.implied_vol_from_price(priced->price, solver_spec);
    ASSERT_TRUE(iv.has_value());
    ASSERT_NEAR(*iv, true_vol, 1e-6);
}

void test_batch_pricing() {
    PricingEngine engine;
    std::vector<YieldPoint> curve = {{1.0, 0.05}};
    engine.init(curve);

    OptionPricer pricer(&engine);

    std::vector<OptionSpec> specs(5);
    for (int i = 0; i < 5; ++i) {
        specs[i] = {
            .spot = 100.0, .strike = 90.0 + i * 5.0, .rate = 0.05,
            .vol = 0.20, .time = 1.0, .side = OptionSide::Call,
        };
    }

    auto results = pricer.price_batch(specs);
    ASSERT_TRUE(results.has_value());
    ASSERT_TRUE(results->size() == 5);

    // Verify prices are monotonically decreasing as strike increases
    for (size_t i = 1; i < results->size(); ++i) {
        ASSERT_TRUE((*results)[i].price <= (*results)[i - 1].price);
    }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
int main() {
    std::printf("\n=== TSAR Pricing Tests ===\n\n");

    // PricingEngine tests
    TEST(engine_init_empty_curve);
    TEST(engine_init_valid_curve);
    TEST(engine_discount_factor);
    TEST(engine_discount_before_init);
    TEST(engine_forward_rate);

    // OptionPricer tests
    TEST(bs_call_at_the_money);
    TEST(bs_put_put_call_parity);
    TEST(bs_invalid_spot);
    TEST(implied_vol_roundtrip);
    TEST(batch_pricing);

    std::printf("\n%d/%d tests passed\n\n", tests_passed, tests_run);
    return (tests_passed == tests_run) ? 0 : 1;
}
