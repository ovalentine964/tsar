// =============================================================================
// fix_session.cpp — Stub implementation of FIXSession
// =============================================================================
//
// When TSAR_HAS_QUICKFIX is defined, QuickFIX handles the real FIX protocol.
// Otherwise, this stub returns plausible placeholder values so the system
// can link, test, and run integration flows without QuickFIX installed.
// =============================================================================

#include "tsar/fix/fix_session.h"

#include <atomic>
#include <format>
#include <mutex>
#include <string>

namespace tsar::fix {

// ---------------------------------------------------------------------------
// Private implementation
// ---------------------------------------------------------------------------
struct FIXSession::Impl {
    SessionConfig    config;
    SessionState     state{SessionState::Disconnected};
    OnExecutionReport on_exec;
    OnLogout         on_logout;
    std::atomic<uint64_t> seq_num{1};
    std::mutex       mtx;

    std::string next_cl_order_id() {
        return std::format("TSAR-{}-{}",
                           config.sender_comp_id,
                           seq_num.fetch_add(1));
    }
};

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------
FIXSession::FIXSession(const SessionConfig& config)
    : impl_(std::make_unique<Impl>()) {
    impl_->config = config;
}

FIXSession::~FIXSession() {
    if (impl_ && impl_->state == SessionState::LoggedOn) {
        // Best-effort graceful shutdown
        impl_->state = SessionState::Disconnected;
    }
}

FIXSession::FIXSession(FIXSession&&) noexcept            = default;
FIXSession& FIXSession::operator=(FIXSession&&) noexcept = default;

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
Expected<void> FIXSession::logon() {
    if (impl_->state == SessionState::LoggedOn) {
        return {};  // Already logged on
    }

#ifdef TSAR_HAS_QUICKFIX
    // TODO: create quickfix::Session, send Logon (35=A)
    // quickfix::Session::sendToLogon();
    impl_->state = SessionState::LoggedOn;
    return {};
#else
    // Stub: transition directly to LoggedOn
    impl_->state = SessionState::LoggedOn;
    return {};
#endif
}

Expected<void> FIXSession::logout() {
    if (impl_->state == SessionState::Disconnected) {
        return {};
    }

#ifdef TSAR_HAS_QUICKFIX
    // TODO: send Logout (35=5), wait for ack, close socket
#else
    impl_->state = SessionState::Disconnected;
#endif

    if (impl_->on_logout) {
        impl_->on_logout("User-initiated logout");
    }
    return {};
}

SessionState FIXSession::state() const noexcept {
    return impl_->state;
}

// ---------------------------------------------------------------------------
// Outbound messages
// ---------------------------------------------------------------------------
Expected<std::string> FIXSession::send_order(const OrderRequest& req) {
    if (impl_->state != SessionState::LoggedOn) {
        return std::unexpected(Error{
            FIXError::NotConnected, "Session not logged on"});
    }

    if (req.qty <= 0.0) {
        return std::unexpected(Error{
            FIXError::InvalidInput, "Order quantity must be > 0"});
    }

    const std::string cl_id = req.cl_order_id.empty()
        ? impl_->next_cl_order_id()
        : req.cl_order_id;

#ifdef TSAR_HAS_QUICKFIX
    // TODO: build FIX::Message (35=D), populate tags, send via session
#else
    // Stub: echo back the client order ID as the "exchange" order ID
    // Simulate a fill callback
    if (impl_->on_exec) {
        OrderAck ack{
            .order_id    = cl_id,
            .cl_order_id = cl_id,
            .exec_type   = ExecType::New,
            .fill_price  = req.price,
            .fill_qty    = req.qty,
            .text        = "STUB: order accepted (no real exchange)",
        };
        impl_->on_exec(ack);
    }
#endif

    return cl_id;
}

Expected<void> FIXSession::cancel_order(std::string_view orig_cl_order_id,
                                          std::string_view /*symbol*/,
                                          Side /*side*/) {
    if (impl_->state != SessionState::LoggedOn) {
        return std::unexpected(Error{
            FIXError::NotConnected, "Session not logged on"});
    }

    if (orig_cl_order_id.empty()) {
        return std::unexpected(Error{
            FIXError::InvalidInput, "Original ClOrdID must not be empty"});
    }

#ifdef TSAR_HAS_QUICKFIX
    // TODO: build FIX::Message (35=F), send via session
#else
    // Stub: emit a cancelled execution report
    if (impl_->on_exec) {
        OrderAck ack{
            .order_id    = std::string(orig_cl_order_id),
            .cl_order_id = std::string(orig_cl_order_id),
            .exec_type   = ExecType::Cancelled,
            .text        = "STUB: order cancelled (no real exchange)",
        };
        impl_->on_exec(ack);
    }
#endif

    return {};
}

// ---------------------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------------------
void FIXSession::on_execution_report(OnExecutionReport cb) {
    std::lock_guard lk(impl_->mtx);
    impl_->on_exec = std::move(cb);
}

void FIXSession::on_logout(OnLogout cb) {
    std::lock_guard lk(impl_->mtx);
    impl_->on_logout = std::move(cb);
}

// ---------------------------------------------------------------------------
// Heartbeat
// ---------------------------------------------------------------------------
void FIXSession::process_heartbeat() {
    // Stub: no-op.  QuickFIX would handle Heartbeat (35=0) / TestRequest (35=1)
}

}  // namespace tsar::fix
