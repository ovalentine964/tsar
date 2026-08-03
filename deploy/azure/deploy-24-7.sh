#!/usr/bin/env bash
# ============================================================
# TSAR — Azure 24/7 Free Tier Deployment
# ============================================================
# Provisions ALL Azure resources and deploys TSAR for 24/7
# operation within the Azure Free Tier (12 months, $0/month).
#
# What this script does:
#   1. Creates Resource Group
#   2. Creates Storage Account + File Shares (persistent data)
#   3. Builds Docker image
#   4. Pushes to Azure Container Registry (or uses Docker Hub)
#   5. Deploys to ACI with restartPolicy=Always
#   6. Configures health probes (auto-restart on failure)
#   7. Sets up Azure Monitor alerts (email notifications)
#   8. Verifies deployment and prints connection info
#
# Prerequisites:
#   - Azure CLI (az) installed and logged in
#   - Docker installed (for building)
#   - deploy/azure/.env.production configured with your API keys
#
# Usage:
#   ./deploy/azure/deploy-24-7.sh                    # Full deploy
#   ./deploy/azure/deploy-24-7.sh --skip-build       # Skip Docker build
#   ./deploy/azure/deploy-24-7.sh --teardown         # Delete everything
#   ./deploy/azure/deploy-24-7.sh --update           # Redeploy (keep data)
#   ./deploy/azure/deploy-24-7.sh --status           # Check status
#   ./deploy/azure/deploy-24-7.sh --logs             # Stream logs
#
# Cost: ~$0/month for first 12 months (Azure Free Tier)
#   ACI: 750 vCPU-hours + 500 GB-hours/month free
#   Storage: 5 GB LRS included in free tier
# ============================================================

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()   { echo -e "${BLUE}[TSAR 24/7]${NC} $*"; }
ok()    { echo -e "${GREEN}[✅]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠️]${NC} $*"; }
fail()  { echo -e "${RED}[❌]${NC} $*"; exit 1; }
step()  { echo -e "\n${CYAN}${BOLD}━━━ $* ━━━${NC}"; }

# ── Configuration ────────────────────────────────────────────
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-tsar-247-rg}"
LOCATION="${AZURE_LOCATION:-eastus}"
DNS_LABEL="${AZURE_DNS_LABEL:-tsar-app}"
CONTAINER_GROUP="tsar-247"
STORAGE_ACCOUNT="tsar247store$(echo "$RESOURCE_GROUP" | md5sum | head -c 6)"
SHARE_DATA="tsar-data"
SHARE_LOGS="tsar-logs"
IMAGE_NAME="tsar"
IMAGE_TAG="${TSAR_IMAGE_TAG:-latest}"
SKIP_BUILD=false
TEARDOWN=false
UPDATE_ONLY=false
STATUS_ONLY=false
LOGS_ONLY=false

# Parse args
for arg in "$@"; do
    case $arg in
        --skip-build)  SKIP_BUILD=true ;;
        --teardown)    TEARDOWN=true ;;
        --update)      UPDATE_ONLY=true ;;
        --status)      STATUS_ONLY=true ;;
        --logs)        LOGS_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-build   Skip Docker image build"
            echo "  --update       Redeploy container (keep persistent data)"
            echo "  --status       Show current deployment status"
            echo "  --logs         Stream container logs"
            echo "  --teardown     Delete ALL resources (data lost!)"
            echo "  -h, --help     Show this help"
            exit 0
            ;;
    esac
done

# ── Prerequisites ────────────────────────────────────────────
step "Checking Prerequisites"

command -v az >/dev/null 2>&1 || fail "Azure CLI not found. Install: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli"
az account show >/dev/null 2>&1 || fail "Not logged in. Run: az login"

SUBSCRIPTION_ID=$(az account show --query "id" -o tsv)
ACCOUNT_NAME=$(az account show --query "name" -o tsv)
ok "Logged in as: $ACCOUNT_NAME ($SUBSCRIPTION_ID)"

if [[ "$SKIP_BUILD" == "false" && "$TEARDOWN" == "false" && "$STATUS_ONLY" == "false" && "$LOGS_ONLY" == "false" ]]; then
    command -v docker >/dev/null 2>&1 || fail "Docker not found."
    ok "Docker found"
fi

# ── Quick Status Check ───────────────────────────────────────
if [[ "$STATUS_ONLY" == "true" ]]; then
    step "Deployment Status"

    if ! az group show --name "$RESOURCE_GROUP" &>/dev/null; then
        warn "Resource group '$RESOURCE_GROUP' not found. No deployment exists."
        exit 0
    fi

    echo ""
    echo "Resource Group: $RESOURCE_GROUP"
    echo "Location:       $LOCATION"
    echo ""

    # Container state
    STATE=$(az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --query "instanceView.state" -o tsv 2>/dev/null || echo "not found")
    RESTARTS=$(az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --query "instanceView.restartCount" -o tsv 2>/dev/null || echo "0")
    FQDN=$(az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --query "ipAddress.fqdn" -o tsv 2>/dev/null || echo "n/a")
    IP=$(az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --query "ipAddress.ip" -o tsv 2>/dev/null || echo "n/a")

    echo "Container State: $STATE"
    echo "Restart Count:   $RESTARTS"
    echo "Public IP:       $IP"
    echo "FQDN:            $FQDN"
    echo ""

    # Health check
    if [[ "$FQDN" != "n/a" ]]; then
        HEALTH=$(curl -sf --max-time 5 "http://${FQDN}:8000/health" 2>/dev/null || echo "unreachable")
        echo "Health Response: $HEALTH"
    fi

    # Storage
    echo ""
    echo "Storage Shares:"
    az storage share list --account-name "$STORAGE_ACCOUNT" --output table 2>/dev/null || warn "Could not list storage shares"

    exit 0
fi

# ── Quick Logs ───────────────────────────────────────────────
if [[ "$LOGS_ONLY" == "true" ]]; then
    az container logs -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --follow
    exit 0
fi

# ── Teardown ─────────────────────────────────────────────────
if [[ "$TEARDOWN" == "true" ]]; then
    step "Tearing Down Deployment"
    warn "This will DELETE the resource group '$RESOURCE_GROUP' and ALL data."
    warn "SQLite database, logs, and all configuration will be LOST."
    read -p "Are you sure? Type 'yes' to confirm: " CONFIRM
    if [[ "$CONFIRM" == "yes" ]]; then
        az group delete --name "$RESOURCE_GROUP" --yes --no-wait
        ok "Resource group '$RESOURCE_GROUP' deletion initiated."
        echo "  Note: Deletion takes 1-2 minutes to complete."
    else
        log "Teardown cancelled."
    fi
    exit 0
fi

# ── Load Environment ─────────────────────────────────────────
step "Loading Environment"

ENV_FILE="deploy/azure/.env.production"
if [[ ! -f "$ENV_FILE" ]]; then
    ENV_FILE="deploy/azure/.env.free-tier"
fi
if [[ -f "$ENV_FILE" ]]; then
    # Source non-secret vars
    export $(grep -E '^[A-Z_]+=' "$ENV_FILE" | grep -v 'API_KEY\|SECRET\|PASSWORD\|TOKEN' | xargs) 2>/dev/null || true
    ok "Loaded config from $ENV_FILE"
else
    warn "No env file found — using defaults."
fi

# Load secrets for deployment
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE" 2>/dev/null || true
    set +a
fi

# Validate required secrets
MISSING=0
for VAR in TSAR_API_KEY EXCHANGE_API_KEY EXCHANGE_SECRET NVIDIA_API_KEY; do
    if [[ -z "${!VAR:-}" ]]; then
        warn "$VAR not set in $ENV_FILE"
        MISSING=$((MISSING + 1))
    fi
done
if [[ $MISSING -gt 0 ]]; then
    warn "$MISSING required variables missing. Edit $ENV_FILE before deployment."
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

# ══════════════════════════════════════════════════════════════
# STEP 1: Resource Group
# ══════════════════════════════════════════════════════════════
step "Step 1/7: Resource Group"

if az group show --name "$RESOURCE_GROUP" &>/dev/null; then
    ok "Resource group '$RESOURCE_GROUP' already exists."
else
    az group create \
        --name "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --tags project=tsar environment=production tier=free-247 \
        --output none
    ok "Created resource group: $RESOURCE_GROUP ($LOCATION)"
fi

# ══════════════════════════════════════════════════════════════
# STEP 2: Storage Account + File Shares
# ══════════════════════════════════════════════════════════════
step "Step 2/7: Storage Account + File Shares (persistent data)"

# Create storage account (must be globally unique, lowercase, 3-24 chars)
if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    ok "Storage account '$STORAGE_ACCOUNT' already exists."
else
    log "Creating storage account: $STORAGE_ACCOUNT"
    az storage account create \
        --name "$STORAGE_ACCOUNT" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku Standard_LRS \
        --kind StorageV2 \
        --access-tier Hot \
        --min-tls-version TLS1_2 \
        --tags project=tsar tier=free \
        --output none
    ok "Storage account created: $STORAGE_ACCOUNT"
fi

# Get storage key
STORAGE_KEY=$(az storage account keys list \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$STORAGE_ACCOUNT" \
    --query "[0].value" -o tsv)

# Create file shares
for SHARE in "$SHARE_DATA" "$SHARE_LOGS"; do
    if az storage share exists --name "$SHARE" --account-name "$STORAGE_ACCOUNT" --account-key "$STORAGE_KEY" --query "exists" -o tsv 2>/dev/null | grep -q "true"; then
        ok "File share '$SHARE' already exists."
    else
        log "Creating file share: $SHARE"
        az storage share create \
            --name "$SHARE" \
            --account-name "$STORAGE_ACCOUNT" \
            --account-key "$STORAGE_KEY" \
            --quota 1 \
            --output none
        ok "File share created: $SHARE (1 GB quota)"
    fi
done

# ══════════════════════════════════════════════════════════════
# STEP 3: Build Docker Image
# ══════════════════════════════════════════════════════════════
step "Step 3/7: Docker Image"

if [[ "$SKIP_BUILD" == "true" ]]; then
    warn "Skipping Docker build (--skip-build)"
else
    log "Building TSAR image (memory-optimized, no Rust)..."
    docker build \
        --build-arg TSAR_RUST_BUILD=0 \
        -f deploy/azure/Dockerfile.azure \
        -t "${IMAGE_NAME}:${IMAGE_TAG}" \
        . 2>&1 | tail -10
    ok "Docker image built: ${IMAGE_NAME}:${IMAGE_TAG}"
fi

# ══════════════════════════════════════════════════════════════
# STEP 4: Push Image to Registry
# ══════════════════════════════════════════════════════════════
step "Step 4/7: Image Registry"

# Option A: Azure Container Registry (preferred)
ACR_NAME="tsar247acr"
if az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null 2>&1; then
    ok "ACR '$ACR_NAME' exists."
else
    log "Creating Azure Container Registry: $ACR_NAME"
    az acr create \
        --name "$ACR_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --sku Basic \
        --admin-enabled true \
        --output none
    ok "ACR created: $ACR_NAME"
fi

ACR_SERVER="${ACR_NAME}.azurecr.io"
IMAGE_REF="${ACR_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"

log "Pushing image to ACR: $IMAGE_REF"
az acr login --name "$ACR_NAME"
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "$IMAGE_REF"
docker push "$IMAGE_REF"
ok "Image pushed to ACR: $IMAGE_REF"

# ══════════════════════════════════════════════════════════════
# STEP 5: Deploy to ACI
# ══════════════════════════════════════════════════════════════
step "Step 5/7: Deploy to Azure Container Instances"

# Delete existing container group if updating
if [[ "$UPDATE_ONLY" == "true" ]]; then
    if az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" &>/dev/null; then
        log "Deleting existing container group for update..."
        az container delete -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --yes --output none
        sleep 5
        ok "Old container group deleted."
    fi
fi

# Resolve the YAML template
RESOLVED_YAML="deploy/azure/container-group-24-7.resolved.yaml"
TSAR_CORS_ORIGINS="${TSAR_CORS_ORIGINS:-http://${DNS_LABEL}.${LOCATION}.azurecontainer.io:8000}"

# Read the template and resolve variables
TEMPLATE_FILE="deploy/azure/container-group-24-7.yaml"
if [[ ! -f "$TEMPLATE_FILE" ]]; then
    fail "Template not found: $TEMPLATE_FILE"
fi

# Use envsubst-style resolution
sed \
    -e "s|\${LOCATION}|${LOCATION}|g" \
    -e "s|\${CONTAINER_GROUP}|${CONTAINER_GROUP}|g" \
    -e "s|\${DNS_LABEL}|${DNS_LABEL}|g" \
    -e "s|\${STORAGE_ACCOUNT}|${STORAGE_ACCOUNT}|g" \
    -e "s|\${STORAGE_KEY}|${STORAGE_KEY}|g" \
    -e "s|\${IMAGE_REF}|${IMAGE_REF}|g" \
    -e "s|\${TSAR_CORS_ORIGINS}|${TSAR_CORS_ORIGINS}|g" \
    -e "s|\${TSAR_API_KEY}|${TSAR_API_KEY:-}|g" \
    -e "s|\${EXCHANGE_API_KEY}|${EXCHANGE_API_KEY:-}|g" \
    -e "s|\${EXCHANGE_SECRET}|${EXCHANGE_SECRET:-}|g" \
    -e "s|\${NVIDIA_API_KEY}|${NVIDIA_API_KEY:-}|g" \
    -e "s|\${DEEPSEEK_API_KEY}|${DEEPSEEK_API_KEY:-}|g" \
    -e "s|\${TELEGRAM_BOT_TOKEN}|${TELEGRAM_BOT_TOKEN:-}|g" \
    -e "s|\${TELEGRAM_CHAT_ID}|${TELEGRAM_CHAT_ID:-}|g" \
    "$TEMPLATE_FILE" > "$RESOLVED_YAML"

# Remove lines with empty optional secrets (ACI rejects empty secureEnvValues)
sed -i '/value: ""$/d' "$RESOLVED_YAML"
# Also remove the name line before empty values
sed -i '/name: DEEPSEEK_API_KEY/{N;/value: ""/d}' "$RESOLVED_YAML" 2>/dev/null || true
sed -i '/name: TELEGRAM_BOT_TOKEN/{N;/value: ""/d}' "$RESOLVED_YAML" 2>/dev/null || true
sed -i '/name: TELEGRAM_CHAT_ID/{N;/value: ""/d}' "$RESOLVED_YAML" 2>/dev/null || true

ok "Resolved YAML template"

log "Deploying container group: $CONTAINER_GROUP"
az container create \
    --resource-group "$RESOURCE_GROUP" \
    --file "$RESOLVED_YAML" \
    --output none

ok "Container group deployed: $CONTAINER_GROUP"

# Clean up resolved YAML (contains secrets)
rm -f "$RESOLVED_YAML"

# ══════════════════════════════════════════════════════════════
# STEP 6: Wait for Running State
# ══════════════════════════════════════════════════════════════
step "Step 6/7: Waiting for Container to Start"

for i in $(seq 1 60); do
    STATE=$(az container show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$CONTAINER_GROUP" \
        --query "instanceView.state" -o tsv 2>/dev/null || echo "Pending")
    if [[ "$STATE" == "Running" ]]; then
        ok "Container is running!"
        break
    fi
    echo -ne "  State: $STATE (attempt $i/60)\r"
    sleep 5
done

if [[ "$STATE" != "Running" ]]; then
    warn "Container not yet running. Checking events..."
    az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --query "instanceView.events" -o yaml 2>/dev/null
    fail "Container did not reach running state. Check: az container logs -g $RESOURCE_GROUP -n $CONTAINER_GROUP"
fi

# ══════════════════════════════════════════════════════════════
# STEP 7: Verify & Print Info
# ══════════════════════════════════════════════════════════════
step "Step 7/7: Verification"

PUBLIC_IP=$(az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --query "ipAddress.ip" -o tsv 2>/dev/null)
FQDN=$(az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --query "ipAddress.fqdn" -o tsv 2>/dev/null)
RESTART_POLICY=$(az container show -g "$RESOURCE_GROUP" -n "$CONTAINER_GROUP" --query "restartPolicy" -o tsv 2>/dev/null)

# Health check
log "Checking health endpoint..."
sleep 10
HEALTH=$(curl -sf --max-time 10 "http://${FQDN}:8000/health" 2>/dev/null || echo "waiting...")
if echo "$HEALTH" | grep -q '"ok"'; then
    ok "Health check passed!"
else
    warn "Health check pending (container may still be initializing): $HEALTH"
fi

echo ""
echo "============================================================"
echo "  🚀 TSAR 24/7 Free Tier Deployment Complete!"
echo "============================================================"
echo ""
echo "  📍 Endpoint:     http://${FQDN}:8000"
echo "  🌐 Public IP:    ${PUBLIC_IP}"
echo "  🏥 Health:       http://${FQDN}:8000/health"
echo "  📖 API Docs:     http://${FQDN}:8000/docs (dev mode only)"
echo ""
echo "  📦 Resources:"
echo "     Resource Group:  $RESOURCE_GROUP"
echo "     Container Group: $CONTAINER_GROUP"
echo "     Storage Account: $STORAGE_ACCOUNT"
echo "     Restart Policy:  $RESTART_POLICY"
echo "     Location:        $LOCATION"
echo ""
echo "  💰 Monthly Cost: ~\$0 (Azure Free Tier)"
echo "     ACI: 1 vCPU × 744h = 744/750 vCPU-hours"
echo "     RAM: 0.65 GB × 744h = 483/500 GB-hours"
echo "     Storage: <1 GB / 5 GB free"
echo ""
echo "  🔧 Management Commands:"
echo "     Status:  $0 --status"
echo "     Logs:    $0 --logs"
echo "     Update:  $0 --update"
echo "     Delete:  $0 --teardown"
echo ""
echo "  📱 APK Configuration:"
echo "     Set API base URL to: http://${FQDN}:8000"
echo "     Set API key to your TSAR_API_KEY"
echo ""
echo "============================================================"

# Set up monitoring alerts (optional, non-blocking)
if [[ -n "${ALERT_EMAIL:-}" ]]; then
    log "Setting up monitoring alerts for $ALERT_EMAIL..."
    bash deploy/azure/monitoring.sh "$LOCATION" "$RESOURCE_GROUP" 2>/dev/null || warn "Monitoring setup skipped (non-critical)"
fi
