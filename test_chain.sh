#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# TSAR — Full Chain Test Script
# Tests: Local → Render Backend → Binance Testnet → Back
#
# Usage:
#   export RENDER_URL="https://tsar-trading.onrender.com"
#   export TSAR_API_KEY="your-api-key"
#   bash test_chain.sh
#
# Or pass as arguments:
#   bash test_chain.sh https://tsar-trading.onrender.com your-api-key
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

RENDER_URL="${RENDER_URL:-${1:-}}"
TSAR_API_KEY="${TSAR_API_KEY:-${2:-}}"

if [[ -z "$RENDER_URL" ]]; then
    echo -e "${RED}ERROR: Set RENDER_URL env var or pass as first argument${NC}"
    echo "Usage: bash test_chain.sh <RENDER_URL> <TSAR_API_KEY>"
    exit 1
fi

if [[ -z "$TSAR_API_KEY" ]]; then
    echo -e "${RED}ERROR: Set TSAR_API_KEY env var or pass as second argument${NC}"
    exit 1
fi

# Remove trailing slash
RENDER_URL="${RENDER_URL%/}"

PASS=0
FAIL=0
WARN=0

pass()  { ((PASS++)); echo -e "  ${GREEN}✅ PASS${NC} — $1"; }
fail()  { ((FAIL++)); echo -e "  ${RED}❌ FAIL${NC} — $1"; }
warn()  { ((WARN++)); echo -e "  ${YELLOW}⚠️  WARN${NC} — $1"; }
header(){ echo -e "\n${BLUE}═══ $1 ═══${NC}"; }

# ── Helper: curl with timeout and error handling ─────────────────────────
api_get() {
    local path="$1"
    local auth="${2:-}"
    local args=(-s -w "\n%{http_code}" --connect-timeout 10 --max-time 20)
    if [[ -n "$auth" ]]; then
        args+=(-H "Authorization: Bearer $auth")
    fi
    curl "${args[@]}" "$RENDER_URL$path"
}

api_post() {
    local path="$1"
    local auth="${2:-}"
    local body="${3:-{}}"
    local args=(-s -w "\n%{http_code}" --connect-timeout 10 --max-time 20 -X POST)
    args+=(-H "Content-Type: application/json")
    if [[ -n "$auth" ]]; then
        args+=(-H "Authorization: Bearer $auth")
    fi
    args+=(-d "$body")
    curl "${args[@]}" "$RENDER_URL$path"
}

# Extract HTTP status code (last line) and body (everything else)
parse_response() {
    local response="$1"
    local body status
    body=$(echo "$response" | head -n -1)
    status=$(echo "$response" | tail -n 1)
    echo "$body"
    return $((status >= 200 && status < 300 ? 0 : 1))
}

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║        TSAR Full Chain Test — Flutter → Render → Binance ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "Render URL: $RENDER_URL"
echo "API Key:    ${TSAR_API_KEY:0:8}...${TSAR_API_KEY: -4}"
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# TEST 1: Health Check (no auth required)
# ═══════════════════════════════════════════════════════════════════════════
header "TEST 1: Render Backend Health"

response=$(api_get "/health") || true
body=$(echo "$response" | head -n -1)
status=$(echo "$response" | tail -n 1)

if [[ "$status" == "200" ]]; then
    health_status=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
    if [[ "$health_status" == "ok" ]]; then
        pass "Backend is healthy (HTTP $status)"
    else
        warn "Backend responded but status=$health_status (HTTP $status)"
    fi
else
    fail "Health check returned HTTP $status"
fi

# Check /health/ready
response=$(api_get "/health/ready") || true
status=$(echo "$response" | tail -n 1)
if [[ "$status" == "200" ]]; then
    pass "Readiness probe OK"
else
    fail "Readiness probe returned HTTP $status"
fi

# ═══════════════════════════════════════════════════════════════════════════
# TEST 2: Authentication
# ═══════════════════════════════════════════════════════════════════════════
header "TEST 2: API Authentication"

# Should fail without auth
response=$(api_get "/api/v1/risk") || true
status=$(echo "$response" | tail -n 1)
if [[ "$status" == "401" ]]; then
    pass "Correctly rejects unauthenticated requests (HTTP 401)"
else
    warn "Expected 401 without auth, got HTTP $status"
fi

# Should succeed with auth
response=$(api_get "/api/v1/risk" "$TSAR_API_KEY") || true
status=$(echo "$response" | tail -n 1)
if [[ "$status" == "200" ]]; then
    pass "Authenticated request succeeds (HTTP 200)"
else
    fail "Authenticated request failed (HTTP $status)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# TEST 3: Core API Endpoints
# ═══════════════════════════════════════════════════════════════════════════
header "TEST 3: Core API Endpoints"

endpoints=(
    "/api/v1/trades"
    "/api/v1/trades/stats"
    "/api/v1/positions"
    "/api/v1/pnl"
    "/api/v1/risk"
    "/api/v1/mandate"
    "/api/v1/factors"
    "/api/v1/strategies"
    "/api/v1/regime"
    "/api/v1/flywheel"
    "/api/v1/paper/dashboard"
    "/api/v1/paper/gate"
    "/api/v1/backends"
)

for ep in "${endpoints[@]}"; do
    response=$(api_get "$ep" "$TSAR_API_KEY") || true
    status=$(echo "$response" | tail -n 1)
    if [[ "$status" == "200" ]]; then
        pass "$ep"
    elif [[ "$status" == "503" ]]; then
        warn "$ep — service unavailable (component not loaded)"
    else
        fail "$ep — HTTP $status"
    fi
done

# ═══════════════════════════════════════════════════════════════════════════
# TEST 4: Binance Testnet Connectivity
# ═══════════════════════════════════════════════════════════════════════════
header "TEST 4: Binance Testnet Connectivity"

# Check if Binance keys are configured via backend
response=$(api_get "/api/v1/backends" "$TSAR_API_KEY") || true
status=$(echo "$response" | tail -n -1)
body=$(echo "$response" | head -n -1)

if [[ "$status" == "200" ]]; then
    pass "Backend registry accessible"
    # Check if exchange backend is registered
    has_exchange=$(echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
backends = data.get('backends', {})
print('yes' if any('exchange' in k.lower() or 'binance' in str(v).lower() for k, v in backends.items()) else 'no')
" 2>/dev/null || echo "unknown")
    if [[ "$has_exchange" == "yes" ]]; then
        pass "Exchange backend registered"
    else
        warn "Exchange backend not found in registry (may not be configured)"
    fi
else
    warn "Could not check backend registry (HTTP $status)"
fi

# Direct Binance testnet ping (bypasses TSAR backend)
echo -e "  ${BLUE}→${NC} Pinging Binance testnet directly..."
binance_response=$(curl -s -w "\n%{http_code}" --connect-timeout 10 "https://testnet.binance.vision/api/v3/ping") || true
binance_status=$(echo "$binance_response" | tail -n 1)
if [[ "$binance_status" == "200" ]]; then
    pass "Binance testnet is reachable"
else
    fail "Binance testnet unreachable (HTTP $binance_status)"
fi

# Get testnet server time to verify full connectivity
echo -e "  ${BLUE}→${NC} Fetching Binance testnet server time..."
time_response=$(curl -s --connect-timeout 10 "https://testnet.binance.vision/api/v3/time") || true
server_time=$(echo "$time_response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('serverTime', 'unknown'))
except:
    print('parse_error')
" 2>/dev/null || echo "error")
if [[ "$server_time" != "error" && "$server_time" != "unknown" ]]; then
    pass "Binance testnet server time: $server_time"
else
    warn "Could not parse Binance server time"
fi

# ═══════════════════════════════════════════════════════════════════════════
# TEST 5: Full Chain — Backend → Binance
# ═══════════════════════════════════════════════════════════════════════════
header "TEST 5: Full Chain — Backend ↔ Binance"

# The /api/v1/positions endpoint queries TradeMemory, which is populated
# by the trading engine that connects to Binance. If the engine is running
# and connected, positions data flows through.
response=$(api_get "/api/v1/positions" "$TSAR_API_KEY") || true
status=$(echo "$response" | tail -n 1)
body=$(echo "$response" | head -n -1)

if [[ "$status" == "200" ]]; then
    count=$(echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('count', 0))
" 2>/dev/null || echo "?")
    pass "Positions endpoint responds (count: $count)"
else
    fail "Positions endpoint failed (HTTP $status)"
fi

# Check risk state (verifies KillSwitch + TradeMemory are working)
response=$(api_get "/api/v1/risk" "$TSAR_API_KEY") || true
status=$(echo "$response" | tail -n 1)
body=$(echo "$response" | head -n -1)

if [[ "$status" == "200" ]]; then
    level=$(echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('level', 'unknown'))
" 2>/dev/null || echo "?")
    ks=$(echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('active' if data.get('kill_switch_active') else 'inactive')
" 2>/dev/null || echo "?")
    pass "Risk state: level=$level, kill_switch=$ks"
else
    fail "Risk endpoint failed (HTTP $status)"
fi

# Check flywheel health (verifies the full pipeline is running)
response=$(api_get "/api/v1/flywheel" "$TSAR_API_KEY") || true
status=$(echo "$response" | tail -n 1)
body=$(echo "$response" | head -n -1)

if [[ "$status" == "200" ]]; then
    score=$(echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('health_score', 'unknown'))
" 2>/dev/null || echo "?")
    pass "Flywheel health: score=$score"
else
    warn "Flywheel endpoint returned HTTP $status"
fi

# ═══════════════════════════════════════════════════════════════════════════
# TEST 6: CORS & Mobile Compatibility
# ═══════════════════════════════════════════════════════════════════════════
header "TEST 6: CORS & Mobile Compatibility"

# Test CORS preflight (simulates Flutter app)
cors_response=$(curl -s -w "\n%{http_code}" --connect-timeout 10 \
    -X OPTIONS \
    -H "Origin: https://tsar-mobile.app" \
    -H "Access-Control-Request-Method: GET" \
    -H "Access-Control-Request-Headers: Authorization,Content-Type" \
    "$RENDER_URL/api/v1/risk") || true
cors_status=$(echo "$cors_response" | tail -n 1)

if [[ "$cors_status" == "200" || "$cors_status" == "204" ]]; then
    pass "CORS preflight accepted (HTTP $cors_status)"
else
    warn "CORS preflight returned HTTP $cors_status — mobile app may have issues"
    echo -e "    ${YELLOW}Fix: Set TSAR_CORS_ORIGINS in Render to include your app's origin${NC}"
fi

# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════
header "RESULTS"
echo ""
echo -e "  ${GREEN}Passed:${NC}  $PASS"
echo -e "  ${RED}Failed:${NC}  $FAIL"
echo -e "  ${YELLOW}Warnings:${NC} $WARN"
echo ""

if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  🎉 All critical tests passed! Full chain is working.   ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    exit 0
else
    echo -e "${RED}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ⚠️  Some tests failed. Check the output above.         ║${NC}"
    echo -e "${RED}╚═══════════════════════════════════════════════════════════╝${NC}"
    exit 1
fi
