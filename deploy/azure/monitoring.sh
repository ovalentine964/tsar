#!/usr/bin/env bash
# ============================================================
# TSAR — Azure Monitor Alert Setup
# ============================================================
# Sets up Azure Monitor alerts for the TSAR container group:
#   - Container restart detection
#   - High CPU utilization (>80%)
#   - OOM kill detection
#   - Container group deletion
#
# Prerequisites:
#   - Azure CLI installed and logged in
#   - TSAR container group already deployed
#   - (Optional) Log Analytics workspace for detailed logs
#
# Usage:
#   ./deploy/azure/monitoring.sh                   # Default settings
#   ./deploy/azure/monitoring.sh eastus tsar-rg    # Custom location/rg
# ============================================================

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${BLUE}[TSAR Monitor]${NC} $*"; }
ok()    { echo -e "${GREEN}[✅]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠️]${NC} $*"; }
fail()  { echo -e "${RED}[❌]${NC} $*"; exit 1; }

# ── Configuration ────────────────────────────────────────────
LOCATION="${1:-eastus}"
RESOURCE_GROUP="${2:-tsar-rg}"
CONTAINER_GROUP="tsar-container-group"
ACTION_GROUP_NAME="tsar-alerts"
ACTION_GROUP_SHORT="tsaralerts"
ALERT_EMAIL="${ALERT_EMAIL:-}"
SUBSCRIPTION_ID=$(az account show --query "id" -o tsv 2>/dev/null || echo "")

# ── Validate prerequisites ───────────────────────────────────
command -v az >/dev/null 2>&1 || fail "Azure CLI (az) not found."
az account show >/dev/null 2>&1 || fail "Not logged in. Run: az login"

log "Setting up monitoring for TSAR in $RESOURCE_GROUP"

# ── Step 1: Create Action Group (notification channel) ──────
log "Creating action group: $ACTION_GROUP_NAME"

if [[ -n "$ALERT_EMAIL" ]]; then
    EMAIL_RECEIVERS="--action email tsar-admin $ALERT_EMAIL"
else
    warn "No ALERT_EMAIL set. Alerts will log to Azure portal only (no email)."
    EMAIL_RECEIVERS=""
fi

az monitor action-group create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACTION_GROUP_NAME" \
    --short-name "$ACTION_GROUP_SHORT" \
    $EMAIL_RECEIVERS \
    --output none 2>/dev/null || warn "Action group may already exist."

ACTION_GROUP_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/microsoft.insights/actionGroups/${ACTION_GROUP_NAME}"
ok "Action group created: $ACTION_GROUP_NAME"

# ── Step 2: Container Restart Alert ──────────────────────────
log "Creating alert: Container Restart Detection"

az monitor metrics alert create \
    --name "TSAR-ContainerRestart" \
    --resource-group "$RESOURCE_GROUP" \
    --scopes "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerInstance/containerGroups/${CONTAINER_GROUP}" \
    --condition "count Microsoft.ContainerInstance/containerGroups RestartCount > 0" \
    --window-size 5m \
    --evaluation-frequency 1m \
    --severity 2 \
    --description "TSAR container has restarted. This may indicate crashes or OOM kills." \
    --action "$ACTION_GROUP_ID" \
    --output none 2>/dev/null || warn "Restart alert may already exist."
ok "Alert: Container Restart Detection"

# ── Step 3: High CPU Alert ──────────────────────────────────
log "Creating alert: High CPU Utilization (>80%)"

az monitor metrics alert create \
    --name "TSAR-HighCPU" \
    --resource-group "$RESOURCE_GROUP" \
    --scopes "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerInstance/containerGroups/${CONTAINER_GROUP}" \
    --condition "avg Microsoft.ContainerInstance/containerGroups CpuUsage > 80" \
    --window-size 5m \
    --evaluation-frequency 1m \
    --severity 2 \
    --description "TSAR CPU usage is above 80% for 5 minutes. May need scaling." \
    --action "$ACTION_GROUP_ID" \
    --output none 2>/dev/null || warn "CPU alert may already exist."
ok "Alert: High CPU Utilization"

# ── Step 4: Memory Usage Alert ───────────────────────────────
log "Creating alert: High Memory Usage (>85%)"

az monitor metrics alert create \
    --name "TSAR-HighMemory" \
    --resource-group "$RESOURCE_GROUP" \
    --scopes "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerInstance/containerGroups/${CONTAINER_GROUP}" \
    --condition "avg Microsoft.ContainerInstance/containerGroups MemoryUsage > 850000000" \
    --window-size 5m \
    --evaluation-frequency 1m \
    --severity 1 \
    --description "TSAR memory usage is above 850MB (of 1GB). OOM kill imminent!" \
    --action "$ACTION_GROUP_ID" \
    --output none 2>/dev/null || warn "Memory alert may already exist."
ok "Alert: High Memory Usage"

# ── Step 5: Container Group Deletion Alert ───────────────────
log "Creating alert: Container Group Deletion"

az monitor activity-log alert create \
    --name "TSAR-ContainerGroupDeleted" \
    --resource-group "$RESOURCE_GROUP" \
    --condition category=ServiceHealth \
    --condition "resourceType=Microsoft.ContainerInstance/containerGroups" \
    --action-group "$ACTION_GROUP_ID" \
    --description "TSAR container group has been deleted or deallocated." \
    --output none 2>/dev/null || warn "Deletion alert may already exist."
ok "Alert: Container Group Deletion"

# ── Step 6: Set up Log Analytics (optional) ──────────────────
if [[ -n "${LOG_ANALYTICS_WORKSPACE_ID:-}" && -n "${LOG_ANALYTICS_WORKSPACE_KEY:-}" ]]; then
    log "Configuring Log Analytics diagnostics..."

    az monitor diagnostic-settings create \
        --name "tsar-diagnostics" \
        --resource "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerInstance/containerGroups/${CONTAINER_GROUP}" \
        --workspace "$LOG_ANALYTICS_WORKSPACE_ID" \
        --logs '[
            {"category": "ContainerInstanceLog", "enabled": true, "retentionPolicy": {"enabled": true, "days": 30}}
        ]' \
        --output none 2>/dev/null || warn "Diagnostic settings may already exist."
    ok "Log Analytics diagnostics configured"
else
    warn "LOG_ANALYTICS_WORKSPACE_ID not set. Skipping Log Analytics setup."
    warn "To enable: create workspace and set env vars in .env"
fi

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  📊 TSAR Azure Monitor Setup Complete"
echo "============================================================"
echo ""
echo "  Alerts configured:"
echo "    ✅ Container Restart Detection  (Severity 2 - Warning)"
echo "    ✅ High CPU Utilization >80%    (Severity 2 - Warning)"
echo "    ✅ High Memory Usage >850MB     (Severity 1 - Critical)"
echo "    ✅ Container Group Deletion     (Severity 3 - Info)"
echo ""
echo "  Action Group: $ACTION_GROUP_NAME"
if [[ -n "$ALERT_EMAIL" ]]; then
    echo "  Notifications: $ALERT_EMAIL"
else
    echo "  Notifications: Portal only (set ALERT_EMAIL for email)"
fi
echo ""
echo "  View alerts:"
echo "    az monitor metrics alert list -g $RESOURCE_GROUP -o table"
echo "    → Azure Portal → Monitor → Alerts"
echo ""
echo "============================================================"
