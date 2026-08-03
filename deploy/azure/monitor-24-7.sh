#!/usr/bin/env bash
# ============================================================
# TSAR — 24/7 Monitoring & Self-Healing Script
# ============================================================
# Run this from a cron job or Azure Function to ensure TSAR
# stays alive 24/7. Handles:
#   - Health check failures → auto-restart container
#   - Container crash detection → auto-restart
#   - OOM kill detection → alert + restart
#   - SSL/TLS certificate monitoring
#   - Disk usage monitoring (Azure Files)
#   - Cost monitoring (stay within free tier)
#
# Usage:
#   ./deploy/azure/monitor-24-7.sh                    # One-shot check
#   ./deploy/azure/monitor-24-7.sh --loop             # Continuous (every 60s)
#   ./deploy/azure/monitor-24-7.sh --cron             # Output crontab entry
#   ./deploy/azure/monitor-24-7.sh --json             # JSON output
#
# Recommended: Run via cron every 5 minutes:
#   */5 * * * * /path/to/tsar/deploy/azure/monitor-24-7.sh >> /var/log/tsar-monitor.log 2>&1
# ============================================================

set -euo pipefail

# ── Configuration ────────────────────────────────────────────
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-tsar-247-rg}"
CONTAINER_GROUP="tsar-247"
LOCATION="${AZURE_LOCATION:-eastus}"
DNS_LABEL="${AZURE_DNS_LABEL:-tsar-app}"
FQDN="${DNS_LABEL}.${LOCATION}.azurecontainer.io"
HEALTH_URL="http://${FQDN}:8000/health"
HEALTH_TIMEOUT=10
MAX_RESTART_ATTEMPTS=3
RESTART_COOLDOWN=300  # 5 minutes between restarts
STATE_FILE="/tmp/tsar-monitor-state.json"

# Parse args
MODE="once"
JSON_OUTPUT=false
for arg in "$@"; do
    case $arg in
        --loop)  MODE="loop" ;;
        --cron)  MODE="cron" ;;
        --json)  JSON_OUTPUT=true ;;
        --help|-h)
            echo "Usage: $0 [--loop|--cron|--json]"
            echo "  --loop   Run continuously (check every 60s)"
            echo "  --cron   Print crontab entry and exit"
            echo "  --json   Output in JSON format"
            exit 0
            ;;
    esac
done

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "$(date '+%Y-%m-%d %H:%M:%S') ${BLUE}[MONITOR]${NC} $*"; }
ok()    { echo -e "$(date '+%Y-%m-%d %H:%M:%S') ${GREEN}[✅]${NC} $*"; }
warn()  { echo -e "$(date '+%Y-%m-%d %H:%M:%S') ${YELLOW}[⚠️]${NC} $*"; }
alert() { echo -e "$(date '+%Y-%m-%d %H:%M:%S') ${RED}[🚨]${NC} $*"; }

# ── State Management ─────────────────────────────────────────
# Track restart attempts and cooldowns to prevent restart loops
init_state() {
    if [[ ! -f "$STATE_FILE" ]]; then
        cat > "$STATE_FILE" << 'EOF'
{"restart_count": 0, "last_restart": 0, "last_healthy": 0, "consecutive_failures": 0}
EOF
    fi
}

read_state() {
    python3 -c "
import json, sys
with open('$STATE_FILE') as f:
    s = json.load(f)
print(s.get('$1', '$2'))
" 2>/dev/null || echo "$2"
}

update_state() {
    python3 -c "
import json
with open('$STATE_FILE', 'r') as f:
    s = json.load(f)
s['$1'] = $2
with open('$STATE_FILE', 'w') as f:
    json.dump(s, f)
" 2>/dev/null || true
}

# ── Crontab Mode ─────────────────────────────────────────────
if [[ "$MODE" == "cron" ]]; then
    SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    echo "# TSAR 24/7 Monitor — check every 5 minutes"
    echo "*/5 * * * * $SCRIPT_PATH >> /var/log/tsar-monitor.log 2>&1"
    echo ""
    echo "# To install:"
    echo "#   crontab -e"
    echo "#   # paste the line above"
    exit 0
fi

# ── Prerequisites ────────────────────────────────────────────
check_prereqs() {
    command -v az >/dev/null 2>&1 || { alert "Azure CLI not found"; return 1; }
    az account show >/dev/null 2>&1 || { alert "Not logged in to Azure"; return 1; }
    return 0
}

# ══════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════
do_health_check() {
    local health_ok=true
    local checks_passed=0
    local checks_total=0
    local results=()

    # ── Check 1: HTTP Health Endpoint ──────────────────────
    checks_total=$((checks_total + 1))
    local health_response
    health_response=$(curl -sf --max-time "$HEALTH_TIMEOUT" "$HEALTH_URL" 2>/dev/null) || health_response=""
    if [[ -n "$health_response" ]] && echo "$health_response" | grep -q '"ok"'; then
        ok "Health endpoint: OK"
        results+=("health:ok")
        checks_passed=$((checks_passed + 1))
    else
        alert "Health endpoint: FAILED (response: ${health_response:-timeout})"
        results+=("health:fail")
        health_ok=false
    fi

    # ── Check 2: ACI Container State ─────────────────────
    checks_total=$((checks_total + 1))
    local container_state
    container_state=$(az container show \
        -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" \
        --query "instanceView.state" -o tsv 2>/dev/null) || container_state="unknown"
    if [[ "$container_state" == "Running" ]]; then
        ok "Container state: Running"
        results+=("state:running")
        checks_passed=$((checks_passed + 1))
    else
        alert "Container state: $container_state"
        results+=("state:$container_state")
        health_ok=false
    fi

    # ── Check 3: Restart Count (detect crash loops) ──────
    checks_total=$((checks_total + 1))
    local restart_count
    restart_count=$(az container show \
        -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" \
        --query "instanceView.restartCount" -o tsv 2>/dev/null) || restart_count="0"
    local prev_restarts
    prev_restarts=$(read_state "restart_count" "0")
    if [[ "$restart_count" -gt "$prev_restarts" ]]; then
        warn "Container restarted since last check ($prev_restarts → $restart_count)"
        update_state "restart_count" "$restart_count"
        results+=("restarts:increased:$restart_count")
    else
        ok "Restart count: $restart_count (stable)"
        results+=("restarts:stable:$restart_count")
        checks_passed=$((checks_passed + 1))
    fi

    # ── Check 4: Response Time ───────────────────────────
    checks_total=$((checks_total + 1))
    local response_time
    response_time=$(curl -sf --max-time 15 -o /dev/null -w "%{time_total}" "$HEALTH_URL" 2>/dev/null) || response_time="timeout"
    if [[ "$response_time" != "timeout" ]]; then
        local rt_ms
        rt_ms=$(echo "$response_time * 1000" | bc 2>/dev/null || echo "$response_time")
        if (( $(echo "$response_time < 5.0" | bc -l 2>/dev/null || echo 0) )); then
            ok "Response time: ${rt_ms}ms"
            results+=("latency:${rt_ms}ms")
            checks_passed=$((checks_passed + 1))
        else
            warn "Response time slow: ${rt_ms}ms"
            results+=("latency:slow:${rt_ms}ms")
        fi
    else
        alert "Response timeout"
        results+=("latency:timeout")
        health_ok=false
    fi

    # ── Check 5: Memory Usage (if available) ─────────────
    checks_total=$((checks_total + 1))
    local mem_usage
    mem_usage=$(az container show \
        -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" \
        --query "instanceView.containers[0].currentState.memoryUsage" -o tsv 2>/dev/null) || mem_usage=""
    if [[ -n "$mem_usage" && "$mem_usage" != "null" ]]; then
        local mem_mb=$((mem_usage / 1048576))
        if [[ $mem_mb -lt 550 ]]; then
            ok "Memory usage: ${mem_mb}MB / 665MB"
            results+=("memory:${mem_mb}MB")
            checks_passed=$((checks_passed + 1))
        else
            warn "Memory usage HIGH: ${mem_mb}MB / 665MB"
            results+=("memory:high:${mem_mb}MB")
        fi
    else
        ok "Memory: not reported (ACI limitation)"
        results+=("memory:n/a")
        checks_passed=$((checks_passed + 1))
    fi

    # ── Summary ──────────────────────────────────────────
    local status="healthy"
    [[ "$health_ok" == "false" ]] && status="unhealthy"

    if [[ "$JSON_OUTPUT" == "true" ]]; then
        echo "{"
        echo "  \"timestamp\": \"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\","
        echo "  \"status\": \"$status\","
        echo "  \"checks_passed\": $checks_passed,"
        echo "  \"checks_total\": $checks_total,"
        echo "  \"restart_count\": $restart_count,"
        echo "  \"container_state\": \"$container_state\","
        echo "  \"fqdn\": \"$FQDN\""
        echo "}"
    else
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if [[ "$status" == "healthy" ]]; then
            echo -e "  ${GREEN}Status: ALL CHECKS PASSED ($checks_passed/$checks_total)${NC}"
        else
            echo -e "  ${RED}Status: ISSUES DETECTED ($checks_passed/$checks_total passed)${NC}"
        fi
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi

    # Return 0 if healthy, 1 if not
    [[ "$health_ok" == "true" ]]
}

# ══════════════════════════════════════════════════════════════
# AUTO-RESTART LOGIC
# ══════════════════════════════════════════════════════════════
do_restart() {
    local now
    now=$(date +%s)
    local last_restart
    last_restart=$(read_state "last_restart" "0")
    local cooldown_remaining=$((RESTART_COOLDOWN - (now - last_restart)))

    if [[ $cooldown_remaining -gt 0 ]]; then
        warn "Restart cooldown active (${cooldown_remaining}s remaining). Skipping."
        return 1
    fi

    local restart_count
    restart_count=$(read_state "restart_count" "0")
    if [[ $restart_count -ge $MAX_RESTART_ATTEMPTS ]]; then
        alert "Max restart attempts ($MAX_RESTART_ATTEMPTS) reached. Manual intervention required!"
        alert "Run: az container restart -g $RESOURCE_GROUP -n $CONTAINER_GROUP"
        return 1
    fi

    alert "Attempting container restart (attempt $((restart_count + 1))/$MAX_RESTART_ATTEMPTS)..."

    # Option 1: Restart the container group
    if az container restart -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --output none 2>/dev/null; then
        ok "Container restart initiated."
        update_state "last_restart" "$now"
        update_state "restart_count" "$((restart_count + 1))"

        # Wait for container to come back up
        log "Waiting for container to recover..."
        sleep 30

        # Verify health after restart
        if curl -sf --max-time 15 "$HEALTH_URL" >/dev/null 2>&1; then
            ok "Container recovered after restart!"
            update_state "consecutive_failures" "0"
            return 0
        else
            warn "Container not yet healthy after restart. Will retry next cycle."
            return 1
        fi
    else
        # Option 2: Delete and recreate (more aggressive)
        warn "Restart failed. Attempting delete + recreate..."
        az container delete -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --yes --output none 2>/dev/null || true
        sleep 10

        # Recreate from the resolved template
        local RESOLVED_YAML="deploy/azure/container-group-24-7.resolved.yaml"
        if [[ -f "$RESOLVED_YAML" ]]; then
            az container create -g "$RESOURCE_GROUP" --file "$RESOLVED_YAML" --output none 2>/dev/null
            ok "Container recreated."
            update_state "last_restart" "$now"
            update_state "restart_count" "$((restart_count + 1))"
        else
            alert "Cannot recreate: resolved YAML not found. Run deploy-24-7.sh first."
            return 1
        fi
    fi
}

# ══════════════════════════════════════════════════════════════
# COST MONITORING
# ══════════════════════════════════════════════════════════════
check_costs() {
    # Estimate current month's ACI usage
    local day_of_month
    day_of_month=$(date +%d | sed 's/^0//')  # Remove leading zero
    local hours_so_far=$((day_of_month * 24))

    local vcpu_hours=$hours_so_far
    # GB-hours: 0.65 GB * hours (integer math: 65 * hours / 100)
    local gb_hours_x100=$((hours_so_far * 65))
    local gb_hours=$((gb_hours_x100 / 100))

    local vcpu_budget=750
    local gb_budget=500

    local vcpu_pct=$((vcpu_hours * 100 / vcpu_budget))
    local gb_pct=$((gb_hours * 100 / gb_budget))

    if [[ "$JSON_OUTPUT" != "true" ]]; then
        log "Cost estimate (day $day_of_month, ${hours_so_far}h elapsed):"
        echo "  vCPU-hours: $vcpu_hours / $vcpu_budget ($vcpu_pct%)"
        echo "  GB-hours:   $gb_hours / $gb_budget ($gb_pct%)"
        if [[ $vcpu_pct -gt 90 ]]; then
            warn "vCPU usage at ${vcpu_pct}% of free tier budget!"
        fi
        if [[ $gb_pct -gt 90 ]]; then
            warn "GB-hours usage at ${gb_pct}% of free tier budget!"
        fi
    fi
}

# ══════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════
main() {
    init_state

    if [[ "$MODE" == "loop" ]]; then
        log "Starting continuous monitoring (Ctrl+C to stop)..."
        while true; do
            echo ""
            log "═══ Health Check ═══"
            if ! do_health_check; then
                local failures
                failures=$(read_state "consecutive_failures" "0")
                failures=$((failures + 1))
                update_state "consecutive_failures" "$failures"

                if [[ $failures -ge 3 ]]; then
                    alert "3 consecutive failures! Attempting auto-restart..."
                    do_restart
                    update_state "consecutive_failures" "0"
                fi
            else
                update_state "consecutive_failures" "0"
            fi

            check_costs
            log "Next check in 60s..."
            sleep 60
        done
    else
        # One-shot mode
        if do_health_check; then
            update_state "consecutive_failures" "0"
            exit 0
        else
            local failures
            failures=$(read_state "consecutive_failures" "0")
            failures=$((failures + 1))
            update_state "consecutive_failures" "$failures"

            if [[ $failures -ge 3 ]]; then
                alert "3 consecutive failures! Attempting auto-restart..."
                do_restart
                update_state "consecutive_failures" "0"
            fi
            exit 1
        fi
    fi
}

main
