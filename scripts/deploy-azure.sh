#!/usr/bin/env bash
# ============================================================
# TSAR — Azure One-Command Deployment
# ============================================================
# Prerequisites:
#   - Azure CLI installed (az)
#   - Logged in: az login
#   - .env file configured (cp deploy/azure/.env.template .env)
#
# Usage:
#   ./scripts/deploy-azure.sh              # Deploy to default region (eastus)
#   ./scripts/deploy-azure.sh westeurope   # Deploy to specific region
#
# What it does:
#   1. Creates resource group
#   2. Creates Azure File Shares for data persistence
#   3. Creates ACI container group (TSAR + Redis)
#   4. Assigns public IP with DNS label
#   5. Runs health check after deployment
# ============================================================

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${BLUE}[TSAR]${NC} $*"; }
ok()    { echo -e "${GREEN}[✅]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠️]${NC} $*"; }
fail()  { echo -e "${RED}[❌]${NC} $*"; exit 1; }

# ── Configuration ────────────────────────────────────────────
LOCATION="${1:-eastus}"
RESOURCE_GROUP="tsar-rg"
CONTAINER_GROUP="tsar-container-group"
STORAGE_ACCOUNT="tsarstorage$(openssl rand -hex 4)"
FILE_SHARE_DATA="tsar-data"
FILE_SHARE_LOGS="tsar-logs"
DNS_LABEL="tsar-app-$(openssl rand -hex 4)"
IMAGE_TAG="${TSAR_IMAGE_TAG:-latest}"
ACR_SERVER="${TSAR_ACR_SERVER:-}"
ACR_USERNAME="${TSAR_ACR_USERNAME:-}"
ACR_PASSWORD="${TSAR_ACR_PASSWORD:-}"

# ── Load .env file ───────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"

if [[ -f "$ENV_FILE" ]]; then
    log "Loading environment from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
else
    warn ".env file not found at $ENV_FILE"
    warn "Copy deploy/azure/.env.template → .env and fill in values"
    warn "Continuing with defaults (secrets will be empty)..."
fi

# ── Validate required tools ──────────────────────────────────
command -v az >/dev/null 2>&1 || fail "Azure CLI (az) not found. Install: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"

# ── Check Azure login ────────────────────────────────────────
log "Checking Azure login..."
az account show >/dev/null 2>&1 || fail "Not logged in. Run: az login"
ACCOUNT_NAME=$(az account show --query "name" -o tsv)
ok "Logged in as: $ACCOUNT_NAME"

# ── Step 1: Create Resource Group ────────────────────────────
log "Creating resource group: $RESOURCE_GROUP in $LOCATION"
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --tags project=tsar environment=production \
    --output none
ok "Resource group created: $RESOURCE_GROUP"

# ── Step 2: Create Storage Account ──────────────────────────
log "Creating storage account: $STORAGE_ACCOUNT"
az storage account create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$STORAGE_ACCOUNT" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --min-tls-version TLS1_2 \
    --output none
ok "Storage account created: $STORAGE_ACCOUNT"

# Get storage key
STORAGE_KEY=$(az storage account keys list \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$STORAGE_ACCOUNT" \
    --query "[0].value" -o tsv)

# ── Step 3: Create File Shares ──────────────────────────────
log "Creating file shares..."
az storage share create \
    --name "$FILE_SHARE_DATA" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --quota 5 \
    --output none

az storage share create \
    --name "$FILE_SHARE_LOGS" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --quota 5 \
    --output none
ok "File shares created: $FILE_SHARE_DATA, $FILE_SHARE_LOGS"

# ── Step 4: Build Container Group YAML ──────────────────────
log "Generating container group configuration..."
YAML_PATH="${PROJECT_ROOT}/deploy/azure/container-group.resolved.yaml"

# Resolve image reference
if [[ -n "$ACR_SERVER" ]]; then
    IMAGE_REF="${ACR_SERVER}/tsar:${IMAGE_TAG}"
else
    # Default to Docker Hub public image
    IMAGE_REF="tsar:${IMAGE_TAG}"
fi

cat > "$YAML_PATH" <<YAML
apiVersion: "2021-10-01"
location: ${LOCATION}
name: ${CONTAINER_GROUP}
type: Microsoft.ContainerInstance/containerGroups
properties:
  priority: Spot
  spotProfile:
    evictionPolicy: Deallocate
    billing:
      price: -1
  osType: Linux
  restartPolicy: OnFailure
  ipAddress:
    type: Public
    ports:
      - port: 8000
        protocol: TCP
    dnsNameLabel: ${DNS_LABEL}
  volumes:
    - name: tsar-data
      azureFile:
        shareName: ${FILE_SHARE_DATA}
        storageAccountName: ${STORAGE_ACCOUNT}
        storageAccountKey: ${STORAGE_KEY}
    - name: tsar-logs
      azureFile:
        shareName: ${FILE_SHARE_LOGS}
        storageAccountName: ${STORAGE_ACCOUNT}
        storageAccountKey: ${STORAGE_KEY}
  containers:
    - name: tsar-app
      properties:
        image: ${IMAGE_REF}
        resources:
          requests:
            cpu: 0.75
            memoryInGb: 0.6
        ports:
          - port: 8000
            protocol: TCP
        environmentVariables:
          - name: TSAR_ENVIRONMENT
            value: production
          - name: TSAR_TRADING_MODE
            value: ${TSAR_TRADING_MODE:-paper}
          - name: TSAR_API_PORT
            value: "8000"
          - name: PYTHONUNBUFFERED
            value: "1"
          - name: REDIS_HOST
            value: localhost
          - name: REDIS_PORT
            value: "6379"
          - name: TSAR_CORS_ORIGINS
            value: "${TSAR_CORS_ORIGINS:-}"
          - name: REDIS_PASSWORD
            secureValue: "${REDIS_PASSWORD:-tsar_redis_$(openssl rand -hex 8)}"
          - name: EXCHANGE_API_KEY
            secureValue: "${EXCHANGE_API_KEY:-}"
          - name: EXCHANGE_SECRET
            secureValue: "${EXCHANGE_SECRET:-}"
          - name: NVIDIA_API_KEY
            secureValue: "${NVIDIA_API_KEY:-}"
          - name: TSAR_API_KEY
            secureValue: "${TSAR_API_KEY:-}"
        volumeMounts:
          - name: tsar-data
            mountPath: /app/data
          - name: tsar-logs
            mountPath: /app/logs
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 30
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 10
          failureThreshold: 3
    - name: tsar-redis
      properties:
        image: redis:7-alpine
        resources:
          requests:
            cpu: 0.25
            memoryInGb: 0.4
        command:
          - redis-server
          - --appendonly
          - "yes"
          - --maxmemory
          - 256mb
          - --maxmemory-policy
          - allkeys-lru
          - --requirepass
          - "${REDIS_PASSWORD:-tsar_redis_$(openssl rand -hex 8)}"
        livenessProbe:
          exec:
            command:
              - redis-cli
              - -a
              - "${REDIS_PASSWORD:-}"
              - ping
          initialDelaySeconds: 5
          periodSeconds: 10
          failureThreshold: 3
        volumeMounts:
          - name: tsar-data
            mountPath: /data
            subPath: redis
  tags:
    project: tsar
    environment: production
YAML

# ── Step 5: Deploy Container Group ──────────────────────────
log "Deploying container group: $CONTAINER_GROUP"
az container create \
    --resource-group "$RESOURCE_GROUP" \
    --file "$YAML_PATH" \
    --output none
ok "Container group deployed: $CONTAINER_GROUP"

# ── Step 6: Get Public IP ───────────────────────────────────
log "Waiting for public IP assignment..."
sleep 10

PUBLIC_IP=$(az container show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_GROUP" \
    --query "ipAddress.ip" -o tsv 2>/dev/null || echo "")

FQDN=$(az container show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_GROUP" \
    --query "ipAddress.fqdn" -o tsv 2>/dev/null || echo "")

if [[ -n "$PUBLIC_IP" ]]; then
    ok "Public IP: $PUBLIC_IP"
    ok "FQDN: $FQDN"
    ok "API endpoint: http://${FQDN}:8000"
else
    warn "Public IP not yet available. Check with:"
    warn "  az container show -g $RESOURCE_GROUP -n $CONTAINER_GROUP --query ipAddress"
fi

# ── Step 7: Health Check ────────────────────────────────────
log "Running health check (waiting for containers to start)..."
MAX_RETRIES=12
RETRY_INTERVAL=10

for i in $(seq 1 $MAX_RETRIES); do
    CONTAINER_STATE=$(az container show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$CONTAINER_GROUP" \
        --query "containers[0].instanceView.currentState.state" -o tsv 2>/dev/null || echo "Unknown")

    log "Attempt $i/$MAX_RETRIES — Container state: $CONTAINER_STATE"

    if [[ "$CONTAINER_STATE" == "Running" ]]; then
        # Try HTTP health check
        if curl -sf --max-time 5 "http://${FQDN}:8000/health" >/dev/null 2>&1; then
            ok "Health check passed! TSAR is running."
            break
        fi
    fi

    if [[ $i -eq $MAX_RETRIES ]]; then
        warn "Health check did not pass within timeout."
        warn "Container may still be starting. Check logs:"
        warn "  az container logs -g $RESOURCE_GROUP -n $CONTAINER_GROUP -c tsar-app"
    fi

    sleep $RETRY_INTERVAL
done

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  🚀 TSAR Azure Deployment Complete"
echo "============================================================"
echo ""
echo "  Resource Group:  $RESOURCE_GROUP"
echo "  Container Group: $CONTAINER_GROUP"
echo "  Location:        $LOCATION"
echo "  Storage Account: $STORAGE_ACCOUNT"
echo "  API Endpoint:    http://${FQDN}:8000"
echo "  API Health:      http://${FQDN}:8000/health"
echo ""
echo "  Useul commands:"
echo "    az container logs -g $RESOURCE_GROUP -n $CONTAINER_GROUP -c tsar-app"
echo "    az container logs -g $RESOURCE_GROUP -n $CONTAINER_GROUP -c tsar-redis"
echo "    az container exec -g $RESOURCE_GROUP -n $CONTAINER_GROUP -c tsar-app --exec-command /bin/bash"
echo "    az container delete -g $RESOURCE_GROUP -n $CONTAINER_GROUP --yes"
echo ""
echo "============================================================"

# Clean up resolved YAML (contains secrets)
rm -f "$YAML_PATH"
