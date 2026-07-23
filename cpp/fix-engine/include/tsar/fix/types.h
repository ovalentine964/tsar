#pragma once
// =============================================================================
// tsar/fix/types.h — Core types for the TSAR FIX protocol layer
// =============================================================================

#include <cstdint>
#include <expected>
#include <string>
#include <string_view>

namespace tsar::fix {

// ---------------------------------------------------------------------------
// FIX message side
// ---------------------------------------------------------------------------
enum class Side : uint8_t {
    Buy  = 1,   // FIX Side '1'
    Sell = 2,   // FIX Side '2'
};

// ---------------------------------------------------------------------------
// FIX order type
// ---------------------------------------------------------------------------
enum class OrderType : uint8_t {
    Market     = 1,   // FIX OrdType '1'
    Limit      = 2,   // FIX OrdType '2'
    Stop       = 3,   // FIX OrdType '3'
    StopLimit  = 4,   // FIX OrdType '4'
};

// ---------------------------------------------------------------------------
// FIX time-in-force
// ---------------------------------------------------------------------------
enum class TimeInForce : uint8_t {
    Day          = 0,
    GTC          = 1,   // Good Till Cancel
    IOC          = 3,   // Immediate or Cancel
    FOK          = 4,   // Fill or Kill
};

// ---------------------------------------------------------------------------
// FIX execution type (ExecType, tag 150)
// ---------------------------------------------------------------------------
enum class ExecType : uint8_t {
    New        = 0,
    PartialFill = 1,
    Fill       = 2,
    DoneForDay = 3,
    Cancelled  = 4,
    Rejected   = 8,
};

// ---------------------------------------------------------------------------
// Session state
// ---------------------------------------------------------------------------
enum class SessionState : uint8_t {
    Disconnected = 0,
    Connecting   = 1,
    LogonSent    = 2,
    LoggedOn     = 3,
    LogoutSent   = 4,
    Error        = 5,
};

// ---------------------------------------------------------------------------
// FIX error codes
// ---------------------------------------------------------------------------
enum class FIXError : int {
    Ok                =  0,
    NotConnected      = -1,
    SessionNotFound   = -2,
    SendFailed        = -3,
    InvalidMessage    = -4,
    LogonRejected     = -5,
    Timeout           = -6,
    InvalidInput      = -7,
};

// ---------------------------------------------------------------------------
// Error wrapper
// ---------------------------------------------------------------------------
struct Error {
    FIXError     code;
    std::string  message;
};

template<typename T>
using Expected = std::expected<T, Error>;

// ---------------------------------------------------------------------------
// Order acknowledgement
// ---------------------------------------------------------------------------
struct OrderAck {
    std::string order_id;       // Exchange-assigned order ID
    std::string cl_order_id;    // Client order ID
    ExecType    exec_type{ExecType::New};
    double      fill_price{0.0};
    double      fill_qty{0.0};
    std::string text;           // Reject reason, if any
};

// ---------------------------------------------------------------------------
// Order request
// ---------------------------------------------------------------------------
struct OrderRequest {
    std::string  cl_order_id;
    std::string  symbol;
    Side         side{Side::Buy};
    OrderType    type{OrderType::Market};
    TimeInForce  tif{TimeInForce::GTC};
    double       price{0.0};
    double       qty{0.0};
};

}  // namespace tsar::fix
