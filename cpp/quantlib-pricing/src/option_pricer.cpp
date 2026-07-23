// =============================================================================
// option_pricer.cpp — Stub implementation of the TSAR OptionPricer
// =============================================================================
//
// Provides Black-Scholes-Merton analytic pricing (always available) and a
// Monte Carlo stub that returns placeholder values unless QuantLib is linked.
// =============================================================================

#include "tsar/pricing/option_pricer.h"

#include <cmath>
#include <format>
#include <numbers>
#include <numeric>
#include <random>
#include <ranges>

namespace tsar::pricing {

// ---------------------------------------------------------------------------
// Standard normal CDF / PDF — self-contained, no external deps
// ---------------------------------------------------------------------------
namespace detail {

[[nodiscard]] inline double norm_cdf(double x) noexcept {
    return 0.5 * std::erfc(-x / std::numbers::sqrt2);
}

[[nodiscard]] inline double norm_pdf(double x) noexcept {
    constexpr double inv_sqrt_2pi = 0.3989422804014327;
    return inv_sqrt_2pi * std::exp(-0.5 * x * x);
}

}  // namespace detail

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------
OptionPricer::OptionPricer(PricingEngine* engine) : engine_(engine) {}
OptionPricer::~OptionPricer() = default;

// ---------------------------------------------------------------------------
// Black-Scholes closed-form (always available)
// ---------------------------------------------------------------------------
Expected<OptionResult>
OptionPricer::price_european_bs(const OptionSpec& spec) const {
    if (spec.spot <= 0.0 || spec.strike <= 0.0 || spec.vol <= 0.0 ||
        spec.time <= 0.0) {
        return std::unexpected(Error{
            PricingError::InvalidInput,
            "spot, strike, vol, time must be > 0"});
    }

    const double S     = spec.spot;
    const double K     = spec.strike;
    const double r     = spec.rate;
    const double q     = spec.dividend_yield;
    const double sigma = spec.vol;
    const double T     = spec.time;
    const double sqrt_T = std::sqrt(T);

    const double d1 = (std::log(S / K) + (r - q + 0.5 * sigma * sigma) * T)
                      / (sigma * sqrt_T);
    const double d2 = d1 - sigma * sqrt_T;

    const double Nd1 = detail::norm_cdf(d1);
    const double Nd2 = detail::norm_cdf(d2);
    const double nd1 = detail::norm_pdf(d1);

    const double eqT = std::exp(-q * T);
    const double erT = std::exp(-r * T);

    double price{0.0};
    Greeks greeks{};

    if (spec.side == OptionSide::Call) {
        price        = S * eqT * Nd1 - K * erT * Nd2;
        greeks.delta = eqT * Nd1;
        greeks.theta = (-S * eqT * nd1 * sigma / (2.0 * sqrt_T)
                        - r * K * erT * Nd2
                        + q * S * eqT * Nd1) / 365.0;
        greeks.rho   = K * T * erT * Nd2 / 100.0;
    } else {
        const double Nmd1 = detail::norm_cdf(-d1);
        const double Nmd2 = detail::norm_cdf(-d2);
        price        = K * erT * Nmd2 - S * eqT * Nmd1;
        greeks.delta = -eqT * Nmd1;
        greeks.theta = (-S * eqT * nd1 * sigma / (2.0 * sqrt_T)
                        + r * K * erT * Nmd2
                        - q * S * eqT * Nmd1) / 365.0;
        greeks.rho   = -K * T * erT * Nmd2 / 100.0;
    }

    greeks.gamma = eqT * nd1 / (S * sigma * sqrt_T);
    greeks.vega  = S * eqT * nd1 * sqrt_T / 100.0;

    return OptionResult{.price = price, .greeks = greeks};
}

// ---------------------------------------------------------------------------
// Monte Carlo — STUB unless TSAR_HAS_QUANTLIB
// ---------------------------------------------------------------------------
Expected<OptionResult>
OptionPricer::price_monte_carlo(const OptionSpec& spec,
                                 uint64_t num_paths,
                                 uint64_t seed) const {
    if (spec.spot <= 0.0 || spec.strike <= 0.0 || spec.vol <= 0.0 ||
        spec.time <= 0.0) {
        return std::unexpected(Error{
            PricingError::InvalidInput,
            "spot, strike, vol, time must be > 0"});
    }

#ifdef TSAR_HAS_QUANTLIB
    // TODO: delegate to QuantLib::McSimulation with the requested style
    (void)num_paths;
    (void)seed;
    return std::unexpected(Error{
        PricingError::UnsupportedStyle,
        "QuantLib Monte Carlo not yet wired — use BS for European"});
#else
    // Stub MC — geometric Brownian motion, European payoff
    const double S    = spec.spot;
    const double K    = spec.strike;
    const double r    = spec.rate;
    const double q    = spec.dividend_yield;
    const double vol  = spec.vol;
    const double T    = spec.time;
    const double dt   = T;
    const double drift     = (r - q - 0.5 * vol * vol) * dt;
    const double diffusion = vol * std::sqrt(dt);

    std::mt19937_64 rng(seed);
    std::normal_distribution<double> normal(0.0, 1.0);

    double payoff_sum = 0.0;
    double payoff_sq  = 0.0;

    for (uint64_t i = 0; i < num_paths; ++i) {
        double z      = normal(rng);
        double ST     = S * std::exp(drift + diffusion * z);
        double payoff = (spec.side == OptionSide::Call)
                            ? std::max(ST - K, 0.0)
                            : std::max(K - ST, 0.0);
        payoff_sum += payoff;
        payoff_sq  += payoff * payoff;
    }

    const double discount = std::exp(-r * T);
    const double mean     = payoff_sum / static_cast<double>(num_paths);
    const double price    = discount * mean;

    // Greeks are not computed in stub MC — fall back to BS
    auto bs_result = price_european_bs(spec);
    Greeks greeks  = bs_result.has_value() ? bs_result->greeks : Greeks{};

    return OptionResult{.price = price, .greeks = greeks};
#endif
}

// ---------------------------------------------------------------------------
// Batch pricing
// ---------------------------------------------------------------------------
Expected<std::vector<OptionResult>>
OptionPricer::price_batch(std::span<const OptionSpec> specs) const {
    std::vector<OptionResult> results;
    results.reserve(specs.size());

    for (const auto& spec : specs) {
        auto r = price_european_bs(spec);
        if (!r.has_value()) {
            return std::unexpected(r.error());
        }
        results.push_back(*r);
    }
    return results;
}

// ---------------------------------------------------------------------------
// Implied vol solver (Newton-Raphson)
// ---------------------------------------------------------------------------
Expected<double>
OptionPricer::implied_vol_from_price(double market_price,
                                      const OptionSpec& spec) const {
    if (market_price <= 0.0) {
        return std::unexpected(Error{
            PricingError::InvalidInput, "Market price must be > 0"});
    }

    // Intrinsic value floor
    const double intrinsic = (spec.side == OptionSide::Call)
        ? std::max(spec.spot - spec.strike, 0.0)
        : std::max(spec.strike - spec.spot, 0.0);

    if (market_price < intrinsic) {
        return std::unexpected(Error{
            PricingError::InvalidInput,
            "Market price below intrinsic value"});
    }

    // Newton-Raphson iteration
    constexpr int    max_iter = 100;
    constexpr double tol      = 1e-8;
    double vol = spec.vol > 0.0 ? spec.vol : 0.20;  // Initial guess

    for (int i = 0; i < max_iter; ++i) {
        OptionSpec iter_spec = spec;
        iter_spec.vol = vol;

        auto result = price_european_bs(iter_spec);
        if (!result.has_value()) {
            return std::unexpected(result.error());
        }

        double price_diff = result->price - market_price;
        if (std::abs(price_diff) < tol) {
            return vol;
        }

        double vega = result->greeks.vega * 100.0;  // vega was per 1%
        if (std::abs(vega) < 1e-12) {
            return std::unexpected(Error{
                PricingError::ConvergenceFailed,
                "Vega too small — Newton-Raphson stalled"});
        }

        vol -= price_diff / vega;
        vol  = std::max(vol, 1e-6);  // Keep vol positive
    }

    return std::unexpected(Error{
        PricingError::ConvergenceFailed,
        "Implied vol solver did not converge within 100 iterations"});
}

}  // namespace tsar::pricing
