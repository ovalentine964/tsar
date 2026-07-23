#pragma once
// =============================================================================
// tsar/pricing/types.h — Core types for the TSAR pricing subsystem
// =============================================================================

#include <cstdint>
#include <expected>
#include <string>
#include <string_view>
#include <vector>

namespace tsar::pricing {

// ---------------------------------------------------------------------------
// Option side
// ---------------------------------------------------------------------------
enum class OptionSide : uint8_t {
    Call = 0,
    Put  = 1,
};

// ---------------------------------------------------------------------------
// Option style
// ---------------------------------------------------------------------------
enum class OptionStyle : uint8_t {
    European = 0,
    American = 1,
    Asian    = 2,
    Barrier  = 3,
};

// ---------------------------------------------------------------------------
// Greeks container
// ---------------------------------------------------------------------------
struct Greeks {
    double delta{0.0};   // ∂V/∂S
    double gamma{0.0};   // ∂²V/∂S²
    double vega{0.0};    // ∂V/∂σ
    double theta{0.0};   // ∂V/∂t
    double rho{0.0};     // ∂V/∂r
};

// ---------------------------------------------------------------------------
// Option pricing result
// ---------------------------------------------------------------------------
struct OptionResult {
    double price{0.0};
    Greeks greeks{};
};

// ---------------------------------------------------------------------------
// Yield-curve point
// ---------------------------------------------------------------------------
struct YieldPoint {
    double tenor_years{0.0};
    double rate{0.0};
};

// ---------------------------------------------------------------------------
// Error codes — returned across FFI boundaries as int
// ---------------------------------------------------------------------------
enum class PricingError : int {
    Ok                  =  0,
    InvalidInput        = -1,
    ComputationFailed   = -2,
    UnsupportedStyle    = -3,
    ConvergenceFailed   = -4,
    NotInitialized      = -5,
};

// ---------------------------------------------------------------------------
// Concept: anything that provides spot, strike, rate, vol, time
// ---------------------------------------------------------------------------
template<typename T>
concept OptionLike = requires(const T& o) {
    { o.spot }   -> std::convertible_to<double>;
    { o.strike } -> std::convertible_to<double>;
    { o.rate }   -> std::convertible_to<double>;
    { o.vol }    -> std::convertible_to<double>;
    { o.time }   -> std::convertible_to<double>;
    { o.side }   -> std::same_as<OptionSide>;
};

// ---------------------------------------------------------------------------
// Error type for std::expected return values
// ---------------------------------------------------------------------------
struct Error {
    PricingError code;
    std::string  message;
};

template<typename T>
using Expected = std::expected<T, Error>;

}  // namespace tsar::pricing
