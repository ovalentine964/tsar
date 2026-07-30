// =============================================================================
// tsar_cffi.cpp — C FFI implementation
// =============================================================================
//
// Bridges C ABI to the C++ PricingEngine, OptionPricer, and FIXGateway.
// All exceptions are caught at the boundary; errors are returned as int codes.
// =============================================================================

#include "tsar/cffi/tsar_cffi.h"

#include "tsar/pricing/option_pricer.h"
#include "tsar/pricing/pricing_engine.h"
#include "tsar/fix/fix_gateway.h"
#include "tsar/gpu/monte_carlo.h"
#include "tsar/gpu/portfolio_opt.h"

#include <algorithm>
#include <cstring>
#include <memory>
#include <new>
#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// Helper: map C++ error to C error code
// ---------------------------------------------------------------------------
static int to_c_code(tsar::pricing::PricingError e) {
    return static_cast<int>(e);
}

static int to_c_code(tsar::fix::FIXError e) {
    using FE = tsar::fix::FIXError;
    switch (e) {
        case FE::Ok:              return TSAR_OK;
        case FE::NotConnected:    return TSAR_ERR_NOT_CONNECTED;
        case FE::SessionNotFound: return TSAR_ERR_INDEX_OUT_OF_RANGE;
        case FE::SendFailed:      return TSAR_ERR_SEND_FAILED;
        case FE::InvalidMessage:  return TSAR_ERR_INVALID_MSG;
        case FE::LogonRejected:   return TSAR_ERR_LOGON_REJECTED;
        case FE::Timeout:         return TSAR_ERR_TIMEOUT;
        case FE::InvalidInput:    return TSAR_ERR_INVALID_INPUT;
        default:                  return TSAR_ERR_COMPUTATION;
    }
}

// ---------------------------------------------------------------------------
// Wrap opaque handles
// ---------------------------------------------------------------------------
struct PricingEngineHandle {
    std::unique_ptr<tsar::pricing::PricingEngine> engine;
};

struct OptionPricerHandle {
    std::unique_ptr<tsar::pricing::OptionPricer> pricer;
    PricingEngineHandle* owner;  // Non-owning back-reference
};

struct FIXGatewayHandle {
    std::unique_ptr<tsar::fix::FIXGateway> gateway;
};

// ===========================================================================
//  Pricing Engine
// ===========================================================================

TsarPricingEngine tsar_pricing_engine_new(void) {
    try {
        auto* h = new PricingEngineHandle();
        h->engine = std::make_unique<tsar::pricing::PricingEngine>();
        return static_cast<TsarPricingEngine>(h);
    } catch (const std::bad_alloc&) {
        return nullptr;
    }
}

void tsar_pricing_engine_free(TsarPricingEngine engine) {
    delete static_cast<PricingEngineHandle*>(engine);
}

int tsar_pricing_engine_init(TsarPricingEngine engine,
                              const TsarYieldPoint* curve,
                              size_t n_points) {
    if (!engine || !curve || n_points == 0) return TSAR_ERR_INVALID_INPUT;

    auto* h = static_cast<PricingEngineHandle*>(engine);

    std::vector<tsar::pricing::YieldPoint> pts(n_points);
    for (size_t i = 0; i < n_points; ++i) {
        pts[i] = {curve[i].tenor_years, curve[i].rate};
    }

    auto result = h->engine->init(pts);
    return result.has_value() ? TSAR_OK : to_c_code(result.error().code);
}

void tsar_pricing_engine_set_flat_vol(TsarPricingEngine engine, double vol) {
    if (!engine) return;
    static_cast<PricingEngineHandle*>(engine)->engine->set_flat_vol(vol);
}

int tsar_pricing_engine_discount(TsarPricingEngine engine,
                                  double t,
                                  double* df) {
    if (!engine || !df) return TSAR_ERR_INVALID_INPUT;

    auto result = static_cast<PricingEngineHandle*>(engine)->engine->discount(t);
    if (!result.has_value()) return to_c_code(result.error().code);
    *df = *result;
    return TSAR_OK;
}

int tsar_pricing_engine_forward_rate(TsarPricingEngine engine,
                                      double t1,
                                      double t2,
                                      double* fwd) {
    if (!engine || !fwd) return TSAR_ERR_INVALID_INPUT;

    auto result = static_cast<PricingEngineHandle*>(engine)
                      ->engine->forward_rate(t1, t2);
    if (!result.has_value()) return to_c_code(result.error().code);
    *fwd = *result;
    return TSAR_OK;
}

// ===========================================================================
//  Option Pricer
// ===========================================================================

TsarOptionPricer tsar_option_pricer_new(TsarPricingEngine engine) {
    if (!engine) return nullptr;
    auto* eh = static_cast<PricingEngineHandle*>(engine);
    try {
        auto* h = new OptionPricerHandle();
        h->pricer = std::make_unique<tsar::pricing::OptionPricer>(eh->engine.get());
        h->owner  = eh;
        return static_cast<TsarOptionPricer>(h);
    } catch (const std::bad_alloc&) {
        return nullptr;
    }
}

void tsar_option_pricer_free(TsarOptionPricer pricer) {
    delete static_cast<OptionPricerHandle*>(pricer);
}

// Helper: convert C spec to C++ spec
static tsar::pricing::OptionSpec to_cpp(const TsarOptionSpec* s) {
    return tsar::pricing::OptionSpec{
        .spot           = s->spot,
        .strike         = s->strike,
        .rate           = s->rate,
        .vol            = s->vol,
        .time           = s->time_years,
        .side           = s->is_call ? tsar::pricing::OptionSide::Call
                                     : tsar::pricing::OptionSide::Put,
        .style          = s->is_european ? tsar::pricing::OptionStyle::European
                                         : tsar::pricing::OptionStyle::American,
        .dividend_yield = s->dividend_yield,
    };
}

// Helper: fill C result from C++ result
static void fill_result(TsarOptionResult* out,
                         const tsar::pricing::OptionResult& in) {
    out->price = in.price;
    out->delta = in.greeks.delta;
    out->gamma = in.greeks.gamma;
    out->vega  = in.greeks.vega;
    out->theta = in.greeks.theta;
    out->rho   = in.greeks.rho;
}

int tsar_option_pricer_bs(TsarOptionPricer pricer,
                           const TsarOptionSpec* spec,
                           TsarOptionResult* result) {
    if (!pricer || !spec || !result) return TSAR_ERR_INVALID_INPUT;

    auto* h = static_cast<OptionPricerHandle*>(pricer);
    auto cpp_spec = to_cpp(spec);

    auto r = h->pricer->price_european_bs(cpp_spec);
    if (!r.has_value()) return to_c_code(r.error().code);

    fill_result(result, *r);
    return TSAR_OK;
}

int tsar_option_pricer_mc(TsarOptionPricer pricer,
                           const TsarOptionSpec* spec,
                           uint64_t n_paths,
                           uint64_t seed,
                           TsarOptionResult* result) {
    if (!pricer || !spec || !result) return TSAR_ERR_INVALID_INPUT;

    auto* h = static_cast<OptionPricerHandle*>(pricer);
    auto cpp_spec = to_cpp(spec);

    auto r = h->pricer->price_monte_carlo(cpp_spec, n_paths, seed);
    if (!r.has_value()) return to_c_code(r.error().code);

    fill_result(result, *r);
    return TSAR_OK;
}

int tsar_option_pricer_batch(TsarOptionPricer pricer,
                              const TsarOptionSpec* specs,
                              size_t n_specs,
                              TsarOptionResult* results) {
    if (!pricer || !specs || !results || n_specs == 0) return TSAR_ERR_INVALID_INPUT;

    auto* h = static_cast<OptionPricerHandle*>(pricer);

    std::vector<tsar::pricing::OptionSpec> cpp_specs;
    cpp_specs.reserve(n_specs);
    for (size_t i = 0; i < n_specs; ++i) {
        cpp_specs.push_back(to_cpp(&specs[i]));
    }

    auto r = h->pricer->price_batch(cpp_specs);
    if (!r.has_value()) return to_c_code(r.error().code);

    for (size_t i = 0; i < n_specs; ++i) {
        fill_result(&results[i], (*r)[i]);
    }
    return TSAR_OK;
}

int tsar_option_pricer_ivol(TsarOptionPricer pricer,
                             double market_price,
                             const TsarOptionSpec* spec,
                             double* ivol) {
    if (!pricer || !spec || !ivol) return TSAR_ERR_INVALID_INPUT;

    auto* h = static_cast<OptionPricerHandle*>(pricer);
    auto cpp_spec = to_cpp(spec);

    auto r = h->pricer->implied_vol_from_price(market_price, cpp_spec);
    if (!r.has_value()) return to_c_code(r.error().code);

    *ivol = *r;
    return TSAR_OK;
}

// ===========================================================================
//  FIX Gateway
// ===========================================================================

TsarFIXGateway tsar_fix_gateway_new(void) {
    try {
        auto* h = new FIXGatewayHandle();
        h->gateway = std::make_unique<tsar::fix::FIXGateway>();
        return static_cast<TsarFIXGateway>(h);
    } catch (const std::bad_alloc&) {
        return nullptr;
    }
}

void tsar_fix_gateway_free(TsarFIXGateway gw) {
    delete static_cast<FIXGatewayHandle*>(gw);
}

int tsar_fix_gateway_add_session(TsarFIXGateway gw,
                                  const char* sender_comp_id,
                                  const char* target_comp_id,
                                  const char* host,
                                  uint16_t port,
                                  size_t* index) {
    if (!gw || !sender_comp_id || !target_comp_id || !host || !index) {
        return TSAR_ERR_INVALID_INPUT;
    }

    auto* h = static_cast<FIXGatewayHandle*>(gw);
    tsar::fix::SessionConfig cfg{
        .sender_comp_id = sender_comp_id,
        .target_comp_id = target_comp_id,
        .host           = host,
        .port           = port,
    };

    auto r = h->gateway->add_session(cfg);
    if (!r.has_value()) return to_c_code(r.error().code);

    *index = *r;
    return TSAR_OK;
}

int tsar_fix_gateway_logon_session(TsarFIXGateway gw, size_t index) {
    if (!gw) return TSAR_ERR_INVALID_INPUT;
    auto r = static_cast<FIXGatewayHandle*>(gw)->gateway->logon_session(index);
    return r.has_value() ? TSAR_OK : to_c_code(r.error().code);
}

int tsar_fix_gateway_logon_all(TsarFIXGateway gw) {
    if (!gw) return TSAR_ERR_INVALID_INPUT;
    auto r = static_cast<FIXGatewayHandle*>(gw)->gateway->logon_all();
    return r.has_value() ? TSAR_OK : to_c_code(r.error().code);
}

int tsar_fix_gateway_logout_session(TsarFIXGateway gw, size_t index) {
    if (!gw) return TSAR_ERR_INVALID_INPUT;
    auto r = static_cast<FIXGatewayHandle*>(gw)->gateway->logout_session(index);
    return r.has_value() ? TSAR_OK : to_c_code(r.error().code);
}

void tsar_fix_gateway_logout_all(TsarFIXGateway gw) {
    if (!gw) return;
    static_cast<FIXGatewayHandle*>(gw)->gateway->logout_all();
}

int tsar_fix_gateway_send_order(TsarFIXGateway gw,
                                 size_t session_index,
                                 const char* symbol,
                                 int32_t side,
                                 int32_t order_type,
                                 double price,
                                 double qty,
                                 char* order_id_buf,
                                 size_t order_id_buf_len) {
    if (!gw || !symbol || !order_id_buf) return TSAR_ERR_INVALID_INPUT;

    tsar::fix::OrderRequest req{
        .cl_order_id = "",
        .symbol      = symbol,
        .side        = (side == 1) ? tsar::fix::Side::Buy : tsar::fix::Side::Sell,
        .type        = (order_type == 1) ? tsar::fix::OrderType::Market
                                         : tsar::fix::OrderType::Limit,
        .price       = price,
        .qty         = qty,
    };

    auto r = static_cast<FIXGatewayHandle*>(gw)->gateway
                 ->send_order(session_index, req);
    if (!r.has_value()) return to_c_code(r.error().code);

    std::strncpy(order_id_buf, r->c_str(), order_id_buf_len - 1);
    order_id_buf[order_id_buf_len - 1] = '\0';
    return TSAR_OK;
}

int tsar_fix_gateway_cancel_order(TsarFIXGateway gw,
                                   size_t session_index,
                                   const char* orig_order_id,
                                   const char* symbol,
                                   int32_t side) {
    if (!gw || !orig_order_id || !symbol) return TSAR_ERR_INVALID_INPUT;

    auto r = static_cast<FIXGatewayHandle*>(gw)->gateway->cancel_order(
        session_index,
        orig_order_id,
        symbol,
        (side == 1) ? tsar::fix::Side::Buy : tsar::fix::Side::Sell);

    return r.has_value() ? TSAR_OK : to_c_code(r.error().code);
}

size_t tsar_fix_gateway_session_count(TsarFIXGateway gw) {
    if (!gw) return 0;
    return static_cast<FIXGatewayHandle*>(gw)->gateway->session_count();
}

int tsar_fix_gateway_any_connected(TsarFIXGateway gw) {
    if (!gw) return 0;
    return static_cast<FIXGatewayHandle*>(gw)->gateway->any_connected() ? 1 : 0;
}

// ===========================================================================
//  GPU Monte Carlo + Portfolio Optimisation
// ===========================================================================

int tsar_gpu_monte_carlo_batch(const TsarMCOptionParams* params,
                                size_t n_options,
                                uint64_t n_paths,
                                uint64_t seed,
                                TsarMCResult* results) {
    if (!params || !results || n_options == 0 || n_paths == 0) {
        return TSAR_ERR_INVALID_INPUT;
    }

    // Convert C structs to C++ structs
    std::vector<tsar::gpu::MCOptionParams> cpp_params(n_options);
    for (size_t i = 0; i < n_options; ++i) {
        cpp_params[i] = {
            .spot        = params[i].spot,
            .strike      = params[i].strike,
            .rate        = params[i].rate,
            .vol         = params[i].vol,
            .time_years  = params[i].time_years,
            .is_call     = params[i].is_call,
        };
    }

    std::vector<tsar::gpu::MCResult> cpp_results(n_options);
    auto err = tsar::gpu::monte_carlo_batch(
        cpp_params.data(), n_options, n_paths, seed, cpp_results.data());

    if (err != tsar::gpu::GPUError::Ok) {
        return TSAR_ERR_COMPUTATION;
    }

    for (size_t i = 0; i < n_options; ++i) {
        results[i].price      = cpp_results[i].price;
        results[i].std_error  = cpp_results[i].std_error;
        results[i].delta      = cpp_results[i].delta;
    }
    return TSAR_OK;
}

int tsar_gpu_var_historical(const double* returns,
                             size_t n_returns,
                             double portfolio_value,
                             double confidence,
                             double* var_out) {
    if (!returns || !var_out || n_returns == 0) {
        return TSAR_ERR_INVALID_INPUT;
    }

    auto err = tsar::gpu::var_historical(
        returns, n_returns, portfolio_value, confidence, var_out);
    return (err == tsar::gpu::GPUError::Ok) ? TSAR_OK : TSAR_ERR_COMPUTATION;
}

int tsar_gpu_mean_variance_opt(const double* expected_returns,
                                const double* cov_matrix,
                                size_t n_assets,
                                double target_return,
                                double* weights_out,
                                TsarOptResult* result) {
    if (!expected_returns || !cov_matrix || !weights_out || !result || n_assets == 0) {
        return TSAR_ERR_INVALID_INPUT;
    }

    tsar::gpu::OptResult opt;
    opt.weights = weights_out;

    auto err = tsar::gpu::mean_variance_opt(
        expected_returns, cov_matrix, n_assets, target_return, &opt);

    if (err != tsar::gpu::OptError::Ok) {
        return TSAR_ERR_COMPUTATION;
    }

    result->portfolio_vol    = opt.portfolio_vol;
    result->portfolio_return = opt.portfolio_return;
    result->sharpe_ratio     = opt.sharpe_ratio;
    result->iterations       = opt.iterations;
    result->converged        = opt.converged;
    return TSAR_OK;
}

int tsar_gpu_risk_parity(const double* volatilities,
                          const double* cov_matrix,
                          size_t n_assets,
                          double* weights_out,
                          TsarOptResult* result) {
    if (!volatilities || !cov_matrix || !weights_out || !result || n_assets == 0) {
        return TSAR_ERR_INVALID_INPUT;
    }

    tsar::gpu::OptResult opt;
    opt.weights = weights_out;

    auto err = tsar::gpu::risk_parity(
        volatilities, cov_matrix, n_assets, &opt);

    if (err != tsar::gpu::OptError::Ok) {
        return TSAR_ERR_COMPUTATION;
    }

    result->portfolio_vol    = opt.portfolio_vol;
    result->portfolio_return = opt.portfolio_return;
    result->sharpe_ratio     = opt.sharpe_ratio;
    result->iterations       = opt.iterations;
    result->converged        = opt.converged;
    return TSAR_OK;
}
