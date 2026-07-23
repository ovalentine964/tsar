// =============================================================================
// test_fix.cpp — Unit tests for FIXSession + FIXGateway
// =============================================================================

#include "tsar/fix/fix_gateway.h"
#include "tsar/fix/fix_session.h"
#include "tsar/fix/types.h"

#include <cassert>
#include <cstdio>
#include <format>
#include <string>

// ---------------------------------------------------------------------------
// Test helper
// ---------------------------------------------------------------------------
static int tests_run    = 0;
static int tests_passed = 0;

#define TEST(name)                                                             \
    do {                                                                       \
        ++tests_run;                                                           \
        std::printf("  %-50s ", #name);                                        \
        try {                                                                  \
            test_##name();                                                     \
            ++tests_passed;                                                    \
            std::printf("✅\n");                                                \
        } catch (const std::exception& e) {                                    \
            std::printf("❌ %s\n", e.what());                                   \
        }                                                                      \
    } while (0)

#define ASSERT_TRUE(expr)                                                      \
    do {                                                                       \
        if (!(expr)) throw std::runtime_error("ASSERT_TRUE: " #expr);          \
    } while (0)

#define ASSERT_FALSE(expr)                                                     \
    do {                                                                       \
        if ((expr)) throw std::runtime_error("ASSERT_FALSE: " #expr);           \
    } while (0)

// ---------------------------------------------------------------------------
// Tests: FIXSession
// ---------------------------------------------------------------------------
using namespace tsar::fix;

void test_session_starts_disconnected() {
    SessionConfig cfg{"SENDER", "TARGET", "127.0.0.1", 9876};
    FIXSession session(cfg);
    ASSERT_TRUE(session.state() == SessionState::Disconnected);
}

void test_session_logon_stub() {
    SessionConfig cfg{"SENDER", "TARGET", "127.0.0.1", 9876};
    FIXSession session(cfg);

    auto r = session.logon();
    ASSERT_TRUE(r.has_value());
    ASSERT_TRUE(session.state() == SessionState::LoggedOn);
}

void test_session_logout_stub() {
    SessionConfig cfg{"SENDER", "TARGET", "127.0.0.1", 9876};
    FIXSession session(cfg);
    session.logon();

    auto r = session.logout();
    ASSERT_TRUE(r.has_value());
    ASSERT_TRUE(session.state() == SessionState::Disconnected);
}

void test_session_send_order_not_logged_on() {
    SessionConfig cfg{"SENDER", "TARGET", "127.0.0.1", 9876};
    FIXSession session(cfg);

    OrderRequest req{.symbol = "BTC/USDT", .qty = 1.0};
    auto r = session.send_order(req);
    ASSERT_FALSE(r.has_value());
    ASSERT_TRUE(r.error().code == FIXError::NotConnected);
}

void test_session_send_order_stub() {
    SessionConfig cfg{"SENDER", "TARGET", "127.0.0.1", 9876};
    FIXSession session(cfg);
    session.logon();

    bool callback_fired = false;
    session.on_execution_report([&](const OrderAck& ack) {
        callback_fired = true;
        ASSERT_TRUE(ack.exec_type == ExecType::New);
    });

    OrderRequest req{
        .cl_order_id = "TEST-001",
        .symbol      = "BTC/USDT",
        .side        = Side::Buy,
        .type        = OrderType::Limit,
        .price       = 50000.0,
        .qty         = 0.1,
    };

    auto r = session.send_order(req);
    ASSERT_TRUE(r.has_value());
    ASSERT_TRUE(callback_fired);
}

void test_session_cancel_order_stub() {
    SessionConfig cfg{"SENDER", "TARGET", "127.0.0.1", 9876};
    FIXSession session(cfg);
    session.logon();

    bool cancel_received = false;
    session.on_execution_report([&](const OrderAck& ack) {
        if (ack.exec_type == ExecType::Cancelled) {
            cancel_received = true;
        }
    });

    auto r = session.cancel_order("TEST-001", "BTC/USDT", Side::Buy);
    ASSERT_TRUE(r.has_value());
    ASSERT_TRUE(cancel_received);
}

void test_session_cancel_order_empty_id() {
    SessionConfig cfg{"SENDER", "TARGET", "127.0.0.1", 9876};
    FIXSession session(cfg);
    session.logon();

    auto r = session.cancel_order("", "BTC/USDT", Side::Buy);
    ASSERT_FALSE(r.has_value());
    ASSERT_TRUE(r.error().code == FIXError::InvalidInput);
}

// ---------------------------------------------------------------------------
// Tests: FIXGateway
// ---------------------------------------------------------------------------
void test_gateway_no_sessions() {
    FIXGateway gw;
    ASSERT_TRUE(gw.session_count() == 0);
    ASSERT_FALSE(gw.any_connected());
}

void test_gateway_add_session() {
    FIXGateway gw;
    SessionConfig cfg{"SENDER", "TARGET", "127.0.0.1", 9876};

    auto r = gw.add_session(cfg);
    ASSERT_TRUE(r.has_value());
    ASSERT_TRUE(gw.session_count() == 1);
}

void test_gateway_add_session_empty_ids() {
    FIXGateway gw;
    SessionConfig cfg{"", "", "127.0.0.1", 9876};

    auto r = gw.add_session(cfg);
    ASSERT_FALSE(r.has_value());
}

void test_gateway_logon_all() {
    FIXGateway gw;
    gw.add_session({"S1", "T1", "127.0.0.1", 9876});
    gw.add_session({"S2", "T2", "127.0.0.1", 9877});

    auto r = gw.logon_all();
    ASSERT_TRUE(r.has_value());
    ASSERT_TRUE(gw.any_connected());
}

void test_gateway_send_order() {
    FIXGateway gw;
    gw.add_session({"S1", "T1", "127.0.0.1", 9876});
    gw.logon_all();

    OrderRequest req{
        .symbol = "ETH/USDT",
        .side   = Side::Sell,
        .type   = OrderType::Market,
        .qty    = 1.0,
    };

    char buf[64] = {};
    auto r = gw.send_order(0, req);
    ASSERT_TRUE(r.has_value());
}

void test_gateway_send_order_out_of_range() {
    FIXGateway gw;
    gw.add_session({"S1", "T1", "127.0.0.1", 9876});
    gw.logon_all();

    OrderRequest req{.symbol = "X", .qty = 1.0};
    auto r = gw.send_order(99, req);
    ASSERT_FALSE(r.has_value());
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
int main() {
    std::printf("\n=== TSAR FIX Tests ===\n\n");

    // Session tests
    TEST(session_starts_disconnected);
    TEST(session_logon_stub);
    TEST(session_logout_stub);
    TEST(session_send_order_not_logged_on);
    TEST(session_send_order_stub);
    TEST(session_cancel_order_stub);
    TEST(session_cancel_order_empty_id);

    // Gateway tests
    TEST(gateway_no_sessions);
    TEST(gateway_add_session);
    TEST(gateway_add_session_empty_ids);
    TEST(gateway_logon_all);
    TEST(gateway_send_order);
    TEST(gateway_send_order_out_of_range);

    std::printf("\n%d/%d tests passed\n\n", tests_passed, tests_run);
    return (tests_passed == tests_run) ? 0 : 1;
}
