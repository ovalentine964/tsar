#!/usr/bin/env bash
# ============================================================
# TSAR — Free Tier Health Check & Monitoring
# ============================================================
# Lightweight monitoring for Azure free tier deployment.
# Checks: API health, SQLite access, LLM connectivity, trading mode.
#
# Usage:
#   ./deploy/azure/health-check.sh                    # Check local
#   ./deploy/azure/health-check.sh https://tsar-app.eastus.azurecontainer.io:8000
#   ./deploy/azure/health-check.sh --json              # JSON output
# ============================================================

set -euo pipefail

# ── Configuration ────────────────────────────────────────────
BASE_URL="${1:-http://localhost:8000}"
JSON_OUTPUT=false

for arg in "$@"; do
    [[ "$arg" == "--json" ]] && JSON_OUTPUT=true
done

# Strip trailing slash
BASE_URL="${BASE_URL%/}"

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✅ PASS${NC}  $*"; }
fail() { echo -e "  ${RED}❌ FAIL${NC}  $*"; FAILURES=$((FAILURES + 1)); }
warn() { echo -e "  ${YELLOW}⚠️  WARN${NC}  $*"; }

FAILURES=0
CHECKS=0
RESULTS=()

check() {
    CHECKS=$((CHECKS + 1))
}

# ── Check 1: API Health Endpoint ────────────────────────────
check
HEALTH_RESPONSE=$(curl -sf --max-time 10 "${BASE_URL}/health" 2>/dev/null) || HEALTH_RESPONSE=""
if [[ -n "$HEALTH_RESPONSE" ]]; then
    pass "API health endpoint responding"
    RESULTS+=("api_health:ok")
else
    fail "API health endpoint not responding at ${BASE_URL}/health"
    RESULTS+=("api_health:fail")
fi

# ── Check 2: API Detailed Health ────────────────────────────
check
DETAILED_HEALTH=$(curl -sf --max-time 10 "${BASE_URL}/health/ready" 2>/dev/null) || DETAILED_HEALTH=""
if [[ -n "$DETAILED_HEALTH" ]]; then
    pass "API readiness endpoint responding"
    RESULTS+=("api_ready:ok")

    # Parse database status from health response if JSON
    if echo "$DETAILED_HEALTH" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        DB_STATUS=$(echo "$DETAILED_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('database',{}).get('status','unknown'))" 2>/dev/null) || DB_STATUS="unknown"
        if [[ "$DB_STATUS" == "ok" || "$DB_STATUS" == "connected" || "$DB_STATUS" == "healthy" ]]; then
            pass "SQLite database accessible (status: $DB_STATUS)"
            RESULTS+=("database:ok")
        elif [[ "$DB_STATUS" == "unknown" ]]; then
            warn "Database status unknown (health response may not include it)"
            RESULTS+=("database:unknown")
        else
            fail "SQLite database issue (status: $DB_STATUS)"
            RESULTS+=("database:fail")
        fi
    else
        warn "Could not parse health response as JSON"
        RESULTS+=("database:unknown")
    fi
else
    fail "API readiness endpoint not responding"
    RESULTS+=("api_ready:fail")
fi

# ── Check 3: Paper Trading Mode ─────────────────────────────
check
# Try to detect paper mode from the health response
if echo "${DETAILED_HEALTH:-$HEALTH_RESPONSE}" | grep -qi "paper" 2>/dev/null; then
    pass "Paper trading mode is active"
    RESULTS+=("trading_mode:paper")
else
    # If we can't determine from health, just warn
    warn "Could not confirm paper trading mode (check TSAR_TRADING_MODE=paper in config)"
    RESULTS+=("trading_mode:unknown")
fi

# ── Check 4: LLM Provider Reachability ──────────────────────
check
# Quick check if NVIDIA NIM endpoint is reachable (not a full API call)
NVIDIA_REACHABLE=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "https://integrate.api.nvidia.com/v1/models" 2>/dev/null) || NVIDIA_REACHABLE="000"
if [[ "$NVIDIA_REACHABLE" == "200" || "$NVIDIA_REACHABLE" == "401" ]]; then
    pass "NVIDIA NIM endpoint reachable (HTTP $NVIDIA_REACHABLE)"
    RESULTS+=("llm_nvidia:reachable")
elif [[ "$NVIDIA_REACHABLE" == "000" ]]; then
    fail "NVIDIA NIM endpoint unreachable (network issue)"
    RESULTS+=("llm_nvidia:unreachable")
else
    warn "NVIDIA NIM endpoint returned HTTP $NVIDIA_REACHABLE"
    RESULTS+=("llm_nvidia:warn")
fi

# ── Check 5: Response Time ──────────────────────────────────
check
RESPONSE_TIME=$(curl -sf --max-time 10 -o /dev/null -w "%{time_total}" "${BASE_URL}/health" 2>/dev/null) || RESPONSE_TIME="timeout"
if [[ "$RESPONSE_TIME" != "timeout" ]]; then
    RT_MS=$(echo "$RESPONSE_TIME * 1000" | bc 2>/dev/null || echo "$RESPONSE_TIME")
    if (( $(echo "$RESPONSE_TIME < 2.0" | bc -l 2>/dev/null || echo 0) )); then
        pass "Response time: ${RT_MS}ms"
        RESULTS+=("response_time:${RT_MS}ms")
    else
        warn "Response time slow: ${RT_MS}ms"
        RESULTS+=("response_time:slow:${RT_MS}ms")
    fi
else
    fail "Response timeout (>10s)"
    RESULTS+=("response_time:timeout")
fi

# ── Check 6: ACI Container State (if az CLI available) ──────
check
if command -v az &>/dev/null && az account show &>/dev/null 2>&1; then
    RG="${AZURE_RESOURCE_GROUP:-tsar-free-rg}"
    CG="tsar-free-tier"
    CONTAINER_STATE=$(az container show \
        --resource-group "$RG" \
        --name "$CG" \
        --query "instanceView.state" -o tsv 2>/dev/null) || CONTAINER_STATE="unknown"
    if [[ "$CONTAINER_STATE" == "Running" ]]; then
        pass "Azure container state: Running"
        RESULTS+=("aci_state:running")
    elif [[ "$CONTAINER_STATE" == "unknown" ]]; then
        warn "Could not query Azure container state (check az CLI login)"
        RESULTS+=("aci_state:unknown")
    else
        fail "Azure container state: $CONTAINER_STATE"
        RESULTS+=("aci_state:$CONTAINER_STATE")
    fi
else
    warn "Azure CLI not available or not logged in — skipping ACI state check"
    RESULTS+=("aci_state:skipped")
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "============================================================"
if [[ $FAILURES -eq 0 ]]; then
    echo -e "  ${GREEN}All $CHECKS checks passed!${NC}"
else
    echo -e "  ${YELLOW}$FAILURES/$CHECKS checks failed${NC}"
fi
echo "  Target: $BASE_URL"
echo "  Time:   $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"

# ── JSON Output ──────────────────────────────────────────────
if [[ "$JSON_OUTPUT" == "true" ]]; then
    echo ""
    echo "{"
    echo "  \"timestamp\": \"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\","
    echo "  \"target\": \"$BASE_URL\","
    echo "  \"checks_total\": $CHECKS,"
    echo "  \"checks_failed\": $FAILURES,"
    echo "  \"results\": {"
    for i in "${!RESULTS[@]}"; do
        KEY="${RESULTS[$i]%%:*}"
        VAL="${RESULTS[$i]#*:}"
        COMMA=","
        [[ $i -eq $((${#RESULTS[@]} - 1)) ]] && COMMA=""
        echo "    \"$KEY\": \"$VAL\"$COMMA"
    done
    echo "  }"
    echo "}"
fi

exit $FAILURES
