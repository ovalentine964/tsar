#pragma once
// =============================================================================
// tsar/pricing/pricing_engine.h — Generic pricing engine interface
// =============================================================================
//
// The PricingEngine owns a yield curve and volatility surface.
// It delegates specific pricing requests to model-specific pricers.
//
// All public methods return std::expected<T, Error> — no exceptions cross
// the API boundary.  This is critical for FFI safety.
// =============================================================================

#include "tsar/pricing/types.h"

#include <memory>
#include <span>
#include <vector>

namespace tsar::pricing {

// ---------------------------------------------------------------------------
// PricingEngine — owns yield curve, dispatches pricing
// ---------------------------------------------------------------------------
class PricingEngine {
public:
    /// Construct an uninitialised engine. Call init() before use.
    PricingEngine();
    ~PricingEngine();

    // Non-copyable, movable
    PricingEngine(const PricingEngine&)            = delete;
    PricingEngine& operator=(const PricingEngine&) = delete;
    PricingEngine(PricingEngine&&) noexcept;
    PricingEngine& operator=(PricingEngine&&) noexcept;

    // ── Lifecycle ─────────────────────────────────────────────────────────

    /// Initialise with a yield curve.  Rates are annualised, continuously
    /// compounded.  Tenors must be strictly increasing.
    [[nodiscard]]
    Expected<void> init(std::span<const YieldPoint> curve_points);

    /// True after a successful init().
    [[nodiscard]] bool is_initialised() const noexcept;

    // ── Yield curve ───────────────────────────────────────────────────────

    /// Discount factor for maturity t (years).
    [[nodiscard]] Expected<double> discount(double t) const;

    /// Forward rate between t1 and t2 (continuous compounding).
    [[nodiscard]] Expected<double> forward_rate(double t1, double t2) const;

    // ── Volatility ────────────────────────────────────────────────────────

    /// Set a flat implied-vol surface for quick prototyping.
    void set_flat_vol(double vol);

    /// Get interpolated implied vol for (strike, maturity).
    [[nodiscard]] Expected<double> implied_vol(double strike,
                                                double maturity) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tsar::pricing
