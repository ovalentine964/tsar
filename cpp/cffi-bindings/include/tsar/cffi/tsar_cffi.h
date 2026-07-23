#pragma once
// =============================================================================
// tsar/cffi/tsar_cffi.h — C ABI header for Rust/Python FFI
// =============================================================================
//
// This is the ONLY header that FFI consumers (Rust via extern "C", Python
// via ctypes/cffi) should include.  It exposes opaque handles and flat
// C functions — no C++ types, no exceptions, no templates.
//
// Convention:
//   - Return int: 0 = success, negative = error (see TSAR_ERR_* codes)
//   - Opaque handles: void* wrappers with typed aliases for clarity
//   - Strings: const char* (UTF-8), caller owns lifetime
//   - Arrays: pointer + length pairs
//   - Out-params: caller allocates, callee fills
// =============================================================================

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// ---------------------------------------------------------------------------
// Visibility
// ---------------------------------------------------------------------------
#ifdef _WIN32
  #define TSAR_API __declspec(dllexport)
#else
  #define TSAR_API __attribute__((visibility("default")))
#endif

// ---------------------------------------------------------------------------
// Error codes
// ---------------------------------------------------------------------------
#define TSAR_OK                    0
#define TSAR_ERR_INVALID_INPUT    -1
#define TSAR_ERR_COMPUTATION      -2
#define TSAR_ERR_UNSUPPORTED      -3
#define TSAR_ERR_CONVERGENCE      -4
#define TSAR_ERR_NOT_INITIALIZED  -5
#define TSAR_ERR_NOT_CONNECTED    -6
#define TSAR_ERR_SEND_FAILED      -7
#define TSAR_ERR_INVALID_MSG      -8
#define TSAR_ERR_LOGON_REJECTED   -9
#define TSAR_ERR_TIMEOUT         -10
#define TSAR_ERR_INDEX_OUT_OF_RANGE -11

// ---------------------------------------------------------------------------
// Opaque handles
// ---------------------------------------------------------------------------
typedef void* TsarPricingEngine;
typedef void* TsarOptionPricer;
typedef void* TsarFIXGateway;
typedef void* TsarFIXSession;

// ---------------------------------------------------------------------------
// Plain data structs (C-compatible, no padding surprises)
// ---------------------------------------------------------------------------
#pragma pack(push, 1)

typedef struct {
    double price;
    double delta;
    double gamma;
    double vega;
    double theta;
    double rho;
} TsarOptionResult;

typedef struct {
    double tenor_years;
    double rate;
} TsarYieldPoint;

typedef struct {
    double spot;
    double strike;
    double rate;
    double vol;
    double time_years;
    int32_t is_call;       // 1 = call, 0 = put
    int32_t is_european;   // 1 = european, 0 = american (stub)
    double dividend_yield;
} TsarOptionSpec;

typedef struct {
    double std_error;
} TsarMCResultExtra;

#pragma pack(pop)

// ===========================================================================
//  Pricing Engine
// ===========================================================================

/// Create a new PricingEngine.  Must be destroyed with tsar_pricing_engine_free().
TSAR_API TsarPricingEngine tsar_pricing_engine_new(void);

/// Destroy a PricingEngine.
TSAR_API void tsar_pricing_engine_free(TsarPricingEngine engine);

/// Initialise with a yield curve.  Returns TSAR_OK on success.
TSAR_API int tsar_pricing_engine_init(TsarPricingEngine engine,
                                       const TsarYieldPoint* curve,
                                       size_t n_points);

/// Set flat implied vol.
TSAR_API void tsar_pricing_engine_set_flat_vol(TsarPricingEngine engine,
                                                double vol);

/// Discount factor for maturity t.  *df filled on success.
TSAR_API int tsar_pricing_engine_discount(TsarPricingEngine engine,
                                           double t,
                                           double* df);

/// Forward rate between t1 and t2.  *fwd filled on success.
TSAR_API int tsar_pricing_engine_forward_rate(TsarPricingEngine engine,
                                               double t1,
                                               double t2,
                                               double* fwd);

// ===========================================================================
//  Option Pricer
// ===========================================================================

/// Create an OptionPricer backed by the given engine.
/// The engine must outlive the pricer.
TSAR_API TsarOptionPricer tsar_option_pricer_new(TsarPricingEngine engine);

/// Destroy an OptionPricer.
TSAR_API void tsar_option_pricer_free(TsarOptionPricer pricer);

/// Black-Scholes European option price + Greeks.
TSAR_API int tsar_option_pricer_bs(TsarOptionPricer pricer,
                                    const TsarOptionSpec* spec,
                                    TsarOptionResult* result);

/// Monte Carlo option price.  Returns TSAR_OK on success.
TSAR_API int tsar_option_pricer_mc(TsarOptionPricer pricer,
                                    const TsarOptionSpec* spec,
                                    uint64_t n_paths,
                                    uint64_t seed,
                                    TsarOptionResult* result);

/// Batch BS pricing.  results[] must have space for n_specs elements.
TSAR_API int tsar_option_pricer_batch(TsarOptionPricer pricer,
                                       const TsarOptionSpec* specs,
                                       size_t n_specs,
                                       TsarOptionResult* results);

/// Solve for implied vol given a market price.  *ivol filled on success.
TSAR_API int tsar_option_pricer_ivol(TsarOptionPricer pricer,
                                      double market_price,
                                      const TsarOptionSpec* spec,
                                      double* ivol);

// ===========================================================================
//  FIX Gateway
// ===========================================================================

/// Create a new FIXGateway.
TSAR_API TsarFIXGateway tsar_fix_gateway_new(void);

/// Destroy a FIXGateway (logs out all sessions first).
TSAR_API void tsar_fix_gateway_free(TsarFIXGateway gw);

/// Add a session.  Returns session index in *index on success.
TSAR_API int tsar_fix_gateway_add_session(TsarFIXGateway gw,
                                           const char* sender_comp_id,
                                           const char* target_comp_id,
                                           const char* host,
                                           uint16_t port,
                                           size_t* index);

/// Logon a specific session.
TSAR_API int tsar_fix_gateway_logon_session(TsarFIXGateway gw, size_t index);

/// Logon all sessions.
TSAR_API int tsar_fix_gateway_logon_all(TsarFIXGateway gw);

/// Logout a specific session.
TSAR_API int tsar_fix_gateway_logout_session(TsarFIXGateway gw, size_t index);

/// Logout all sessions.
TSAR_API void tsar_fix_gateway_logout_all(TsarFIXGateway gw);

/// Send a new order.  Order ID written to order_id_buf (caller allocs).
TSAR_API int tsar_fix_gateway_send_order(TsarFIXGateway gw,
                                          size_t session_index,
                                          const char* symbol,
                                          int32_t side,     // 1=buy, 2=sell
                                          int32_t order_type, // 1=market, 2=limit
                                          double price,
                                          double qty,
                                          char* order_id_buf,
                                          size_t order_id_buf_len);

/// Cancel an order.
TSAR_API int tsar_fix_gateway_cancel_order(TsarFIXGateway gw,
                                            size_t session_index,
                                            const char* orig_order_id,
                                            const char* symbol,
                                            int32_t side);

/// Number of sessions.
TSAR_API size_t tsar_fix_gateway_session_count(TsarFIXGateway gw);

/// 1 if at least one session is logged on, 0 otherwise.
TSAR_API int tsar_fix_gateway_any_connected(TsarFIXGateway gw);

#ifdef __cplusplus
}
#endif
