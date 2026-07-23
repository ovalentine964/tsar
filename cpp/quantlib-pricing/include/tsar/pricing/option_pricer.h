#pragma once
// =============================================================================
// tsar/pricing/option_pricer.h — Option pricing via closed-form & Monte Carlo
// =============================================================================
//
// The OptionPricer is a stateless calculator that uses a PricingEngine for
// discounting / vol lookup.  Two modes:
//   1. Black-Scholes closed-form  (European, always available)
//   2. QuantLib Monte Carlo        (exotic styles, requires TSAR_HAS_QUANTLIB)
// =============================================================================

#include "tsar/pricing/pricing_engine.h"
#include "tsar/pricing/types.h"

#include <vector>

namespace tsar::pricing {

// ---------------------------------------------------------------------------
// Option contract specification
// ---------------------------------------------------------------------------
struct OptionSpec {
    double       spot{0.0};
    double       strike{0.0};
    double       rate{0.0};      // risk-free rate (override engine curve?)
    double       vol{0.0};       // implied vol (override engine flat vol?)
    double       time{0.0};      // time to expiry in years
    OptionSide   side{OptionSide::Call};
    OptionStyle  style{OptionStyle::European};
    double       dividend_yield{0.0};
};

// Verify the concept at compile-time
static_assert(OptionLike<OptionSpec>,
              "OptionSpec must satisfy the OptionLike concept");

// ---------------------------------------------------------------------------
// OptionPricer — main pricing facade
// ---------------------------------------------------------------------------
class OptionPricer {
public:
    explicit OptionPricer(PricingEngine* engine);
    ~OptionPricer();

    // ── Black-Scholes (always available) ──────────────────────────────────

    /// Analytic European option price + Greeks (Black-Scholes-Merton).
    [[nodiscard]]
    Expected<OptionResult> price_european_bs(const OptionSpec& spec) const;

    // ── Monte Carlo (stub unless TSAR_HAS_QUANTLIB) ───────────────────────

    /// Monte Carlo price for arbitrary option styles.
    /// @param num_paths   Number of simulation paths (default 100 000).
    /// @param seed        RNG seed for reproducibility.
    [[nodiscard]]
    Expected<OptionResult> price_monte_carlo(const OptionSpec& spec,
                                              uint64_t num_paths = 100'000,
                                              uint64_t seed      = 42) const;

    // ── Batch pricing ─────────────────────────────────────────────────────

    /// Price a vector of options.  Returns the same number of results or an
    /// error on the first failure.
    [[nodiscard]]
    Expected<std::vector<OptionResult>>
    price_batch(std::span<const OptionSpec> specs) const;

    // ── Implied vol solver ────────────────────────────────────────────────

    /// Given a market price, solve for implied vol (Newton-Raphson).
    [[nodiscard]]
    Expected<double> implied_vol_from_price(double market_price,
                                             const OptionSpec& spec) const;

private:
    PricingEngine* engine_;  // Non-owning; caller manages lifetime
};

}  // namespace tsar::pricing
