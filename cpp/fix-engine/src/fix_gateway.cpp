// =============================================================================
// fix_gateway.cpp — Stub implementation of FIXGateway
// =============================================================================

#include "tsar/fix/fix_gateway.h"

#include <algorithm>
#include <format>
#include <stdexcept>
#include <vector>

namespace tsar::fix {

// ---------------------------------------------------------------------------
// Private implementation
// ---------------------------------------------------------------------------
struct FIXGateway::Impl {
    std::vector<std::unique_ptr<FIXSession>> sessions;
    OnExecutionReport on_exec;
    OnLogout          on_logout;

    void validate_index(size_t index) const {
        if (index >= sessions.size()) {
            throw std::out_of_range(
                std::format("Session index {} out of range [0, {})",
                            index, sessions.size()));
        }
    }
};

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------
FIXGateway::FIXGateway() : impl_(std::make_unique<Impl>()) {}
FIXGateway::~FIXGateway() { logout_all(); }

FIXGateway::FIXGateway(FIXGateway&&) noexcept            = default;
FIXGateway& FIXGateway::operator=(FIXGateway&&) noexcept = default;

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------
Expected<size_t> FIXGateway::add_session(const SessionConfig& config) {
    if (config.sender_comp_id.empty() || config.target_comp_id.empty()) {
        return std::unexpected(Error{
            FIXError::InvalidInput,
            "sender_comp_id and target_comp_id must not be empty"});
    }

    auto session = std::make_unique<FIXSession>(config);

    // Wire up callbacks
    if (impl_->on_exec) {
        session->on_execution_report(impl_->on_exec);
    }
    if (impl_->on_logout) {
        session->on_logout(impl_->on_logout);
    }

    size_t idx = impl_->sessions.size();
    impl_->sessions.push_back(std::move(session));
    return idx;
}

Expected<void> FIXGateway::logon_session(size_t index) {
    try {
        impl_->validate_index(index);
    } catch (const std::out_of_range& e) {
        return std::unexpected(Error{FIXError::SessionNotFound, e.what()});
    }
    return impl_->sessions[index]->logon();
}

Expected<void> FIXGateway::logon_all() {
    for (auto& session : impl_->sessions) {
        auto r = session->logon();
        if (!r.has_value()) {
            return r;
        }
    }
    return {};
}

Expected<void> FIXGateway::logout_session(size_t index) {
    try {
        impl_->validate_index(index);
    } catch (const std::out_of_range& e) {
        return std::unexpected(Error{FIXError::SessionNotFound, e.what()});
    }
    return impl_->sessions[index]->logout();
}

void FIXGateway::logout_all() {
    for (auto& session : impl_->sessions) {
        (void)session->logout();  // Best-effort
    }
}

// ---------------------------------------------------------------------------
// Order routing
// ---------------------------------------------------------------------------
Expected<std::string> FIXGateway::send_order(size_t index,
                                               const OrderRequest& req) {
    try {
        impl_->validate_index(index);
    } catch (const std::out_of_range& e) {
        return std::unexpected(Error{FIXError::SessionNotFound, e.what()});
    }
    return impl_->sessions[index]->send_order(req);
}

Expected<void> FIXGateway::cancel_order(size_t index,
                                          std::string_view orig_cl_order_id,
                                          std::string_view symbol,
                                          Side side) {
    try {
        impl_->validate_index(index);
    } catch (const std::out_of_range& e) {
        return std::unexpected(Error{FIXError::SessionNotFound, e.what()});
    }
    return impl_->sessions[index]->cancel_order(orig_cl_order_id, symbol, side);
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------
size_t FIXGateway::session_count() const noexcept {
    return impl_->sessions.size();
}

SessionState FIXGateway::session_state(size_t index) const {
    impl_->validate_index(index);
    return impl_->sessions[index]->state();
}

bool FIXGateway::any_connected() const noexcept {
    return std::ranges::any_of(impl_->sessions, [](const auto& s) {
        return s->state() == SessionState::LoggedOn;
    });
}

// ---------------------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------------------
void FIXGateway::on_execution_report(OnExecutionReport cb) {
    impl_->on_exec = std::move(cb);
    // Propagate to existing sessions
    for (auto& s : impl_->sessions) {
        s->on_execution_report(impl_->on_exec);
    }
}

void FIXGateway::on_logout(OnLogout cb) {
    impl_->on_logout = std::move(cb);
    for (auto& s : impl_->sessions) {
        s->on_logout(impl_->on_logout);
    }
}

}  // namespace tsar::fix
