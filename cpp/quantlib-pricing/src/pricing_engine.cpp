// =============================================================================
// pricing_engine.cpp — Stub implementation of the TSAR PricingEngine
// =============================================================================
//
// When TSAR_HAS_QUANTLIB is defined, QuantLib does the heavy lifting.
// Otherwise, this file provides a lightweight stub that satisfies the
// interface so the system can link and run tests without QuantLib installed.
// =============================================================================

#include "tsar/pricing/pricing_engine.h"

#include <algorithm>
#include <cmath>
#include <format>
#include <ranges>
#include <stdexcept>

namespace tsar::pricing {

// ---------------------------------------------------------------------------
// Private implementation
// ---------------------------------------------------------------------------
struct PricingEngine::Impl {
    bool                       initialised{false};
    std::vector<YieldPoint>    curve;       // sorted by tenor
    double                     flat_vol{0.20};  // 20 % default

    // ── Stub interpolation ────────────────────────────────────────────────
    [[nodiscard]]
    double interpolate_rate(double t) const {
        if (curve.empty()) return 0.05;          // 5 % fallback
        if (t <= curve.front().tenor_years) return curve.front().rate;
        if (t >= curve.back().tenor_years)  return curve.back().rate;

        // Simple linear interpolation (stub — QuantLib uses log-linear)
        auto hi = std::ranges::lower_bound(curve, t, {}, &YieldPoint::tenor_years);
        auto lo = std::prev(hi);
        double frac = (t - lo->tenor_years) / (hi->tenor_years - lo->tenor_years);
        return lo->rate + frac * (hi->rate - lo->rate);
    }
};

// ---------------------------------------------------------------------------
// Construction / destruction
// ---------------------------------------------------------------------------
PricingEngine::PricingEngine() : impl_(std::make_unique<Impl>()) {}
PricingEngine::~PricingEngine() = default;

PricingEngine::PricingEngine(PricingEngine&&) noexcept            = default;
PricingEngine& PricingEngine::operator=(PricingEngine&&) noexcept = default;

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
Expected<void> PricingEngine::init(std::span<const YieldPoint> curve_points) {
    if (curve_points.empty()) {
        return std::unexpected(Error{
            PricingError::InvalidInput, "Yield curve must not be empty"});
    }

    // Validate monotonic tenors
    for (size_t i = 1; i < curve_points.size(); ++i) {
        if (curve_points[i].tenor_years <= curve_points[i - 1].tenor_years) {
            return std::unexpected(Error{
                PricingError::InvalidInput,
                "Yield curve tenors must be strictly increasing"});
        }
    }

    impl_->curve.assign(curve_points.begin(), curve_points.end());
    impl_->initialised = true;
    return {};
}

bool PricingEngine::is_initialised() const noexcept {
    return impl_->initialised;
}

// ---------------------------------------------------------------------------
// Discount factor
// ---------------------------------------------------------------------------
Expected<double> PricingEngine::discount(double t) const {
    if (!impl_->initialised) {
        return std::unexpected(Error{
            PricingError::NotInitialized, "Engine not initialised"});
    }
    if (t < 0.0) {
        return std::unexpected(Error{
            PricingError::InvalidInput, "Tenor must be >= 0"});
    }
    double r = impl_->interpolate_rate(t);
    return std::exp(-r * t);
}

// ---------------------------------------------------------------------------
// Forward rate
// ---------------------------------------------------------------------------
Expected<double> PricingEngine::forward_rate(double t1, double t2) const {
    if (!impl_->initialised) {
        return std::unexpected(Error{
            PricingError::NotInitialized, "Engine not initialised"});
    }
    if (t1 >= t2) {
        return std::unexpected(Error{
            PricingError::InvalidInput, "t1 must be < t2"});
    }
    double r1 = impl_->interpolate_rate(t1);
    double r2 = impl_->interpolate_rate(t2);
    // Forward rate from the zero curve:  f = (r2*t2 - r1*t1) / (t2 - t1)
    return (r2 * t2 - r1 * t1) / (t2 - t1);
}

// ---------------------------------------------------------------------------
// Volatility
// ---------------------------------------------------------------------------
void PricingEngine::set_flat_vol(double vol) {
    impl_->flat_vol = vol;
}

Expected<double> PricingEngine::implied_vol(double /*strike*/,
                                             double /*maturity*/) const {
    // Stub: return flat vol.  QuantLib surface would interpolate here.
    return impl_->flat_vol;
}

}  // namespace tsar::pricing
