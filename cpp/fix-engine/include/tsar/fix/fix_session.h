#pragma once
// =============================================================================
// tsar/fix/fix_session.h — FIX session management
// =============================================================================
//
// Wraps a single FIX session (one connection to one exchange/broker).
// Handles logon, heartbeat, logout, and message framing.
// When QuickFIX is not linked, this is a stub that returns placeholder data.
// =============================================================================

#include "tsar/fix/types.h"

#include <functional>
#include <memory>
#include <string>

namespace tsar::fix {

// ---------------------------------------------------------------------------
// Callback types for inbound FIX messages
// ---------------------------------------------------------------------------
using OnExecutionReport = std::function<void(const OrderAck&)>;
using OnLogout          = std::function<void(const std::string& reason)>;

// ---------------------------------------------------------------------------
// FIX session configuration
// ---------------------------------------------------------------------------
struct SessionConfig {
    std::string sender_comp_id;
    std::string target_comp_id;
    std::string host;
    uint16_t    port{0};
    std::string heartbeat_interval_s{"30"};
    bool        reset_on_logon{false};
};

// ---------------------------------------------------------------------------
// FIXSession — one logical FIX connection
// ---------------------------------------------------------------------------
class FIXSession {
public:
    explicit FIXSession(const SessionConfig& config);
    ~FIXSession();

    // Non-copyable, movable
    FIXSession(const FIXSession&)            = delete;
    FIXSession& operator=(const FIXSession&) = delete;
    FIXSession(FIXSession&&) noexcept;
    FIXSession& operator=(FIXSession&&) noexcept;

    // ── Lifecycle ─────────────────────────────────────────────────────────

    /// Open TCP connection and send Logon (35=A).
    [[nodiscard]] Expected<void> logon();

    /// Send Logout (35=5) and close TCP connection.
    [[nodiscard]] Expected<void> logout();

    /// Current session state.
    [[nodiscard]] SessionState state() const noexcept;

    // ── Outbound messages ─────────────────────────────────────────────────

    /// Send a NewOrderSingle (35=D).
    [[nodiscard]] Expected<std::string> send_order(const OrderRequest& req);

    /// Send OrderCancelRequest (35=F).
    [[nodiscard]] Expected<void> cancel_order(std::string_view orig_cl_order_id,
                                               std::string_view symbol,
                                               Side side);

    // ── Callbacks ─────────────────────────────────────────────────────────

    void on_execution_report(OnExecutionReport cb);
    void on_logout(OnLogout cb);

    // ── Heartbeat ─────────────────────────────────────────────────────────

    /// Process inbound heartbeat / test-request. Called by the gateway loop.
    void process_heartbeat();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tsar::fix
