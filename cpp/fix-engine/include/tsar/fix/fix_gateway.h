#pragma once
// =============================================================================
// tsar/fix/fix_gateway.h — Multi-session FIX gateway
// =============================================================================
//
// The FIXGateway manages multiple FIX sessions (one per venue).
// It provides a unified interface for order routing and session lifecycle.
// =============================================================================

#include "tsar/fix/fix_session.h"
#include "tsar/fix/types.h"

#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace tsar::fix {

// ---------------------------------------------------------------------------
// FIXGateway — manages one or more FIX sessions
// ---------------------------------------------------------------------------
class FIXGateway {
public:
    FIXGateway();
    ~FIXGateway();

    // Non-copyable, movable
    FIXGateway(const FIXGateway&)            = delete;
    FIXGateway& operator=(const FIXGateway&) = delete;
    FIXGateway(FIXGateway&&) noexcept;
    FIXGateway& operator=(FIXGateway&&) noexcept;

    // ── Session management ────────────────────────────────────────────────

    /// Add a new session.  Returns the session index.
    [[nodiscard]] Expected<size_t> add_session(const SessionConfig& config);

    /// Logon to a specific session by index.
    [[nodiscard]] Expected<void> logon_session(size_t index);

    /// Logon to all configured sessions.
    [[nodiscard]] Expected<void> logon_all();

    /// Logout a specific session.
    [[nodiscard]] Expected<void> logout_session(size_t index);

    /// Logout all sessions.
    void logout_all();

    // ── Order routing ─────────────────────────────────────────────────────

    /// Send an order to a specific session.
    [[nodiscard]] Expected<std::string> send_order(size_t session_index,
                                                    const OrderRequest& req);

    /// Cancel an order on a specific session.
    [[nodiscard]] Expected<void> cancel_order(size_t session_index,
                                               std::string_view orig_cl_order_id,
                                               std::string_view symbol,
                                               Side side);

    // ── Status ────────────────────────────────────────────────────────────

    /// Number of configured sessions.
    [[nodiscard]] size_t session_count() const noexcept;

    /// State of a specific session.
    [[nodiscard]] SessionState session_state(size_t index) const;

    /// True if at least one session is logged on.
    [[nodiscard]] bool any_connected() const noexcept;

    // ── Callbacks (applied to all sessions) ───────────────────────────────

    void on_execution_report(OnExecutionReport cb);
    void on_logout(OnLogout cb);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tsar::fix
