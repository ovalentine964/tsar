#!/usr/bin/env bash
# ============================================================
# TSAR — Azure Free Tier Deployment Script
# ============================================================
# Provisions and deploys TSAR to Azure Container Instances
# using the Azure Free Tier (1 vCPU, 1 GB RAM, $0 for 12mo).
#
# Prerequisites:
#   - Azure CLI installed: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
#   - Logged in: az login
#   - Docker installed (for building the image)
#
# Usage:
#   ./deploy/azure/deploy-free-tier.sh              # Full deploy
#   ./deploy/azure/deploy-free-tier.sh --skip-build  # Skip Docker build
#   ./deploy/azure/deploy-free-tier.sh --teardown    # Delete everything
#
# Cost: ~$0/month for first 12 months (Azure Free Tier)
# ============================================================

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log()   { echo -e "${BLUE}[TSAR Deploy]${NC} $*"; }
ok()    { echo -e "${GREEN}[✅]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠️]${NC} $*"; }
fail()  { echo -e "${RED}[❌]${NC} $*"; exit 1; }
step()  { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

# ── Configuration ────────────────────────────────────────────
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-tsar-free-rg}"
LOCATION="${AZURE_LOCATION:-eastus}"
DNS_LABEL="${AZURE_DNS_LABEL:-tsar-app}"
CONTAINER_GROUP="tsar-free-tier"
IMAGE_NAME="tsar"
IMAGE_TAG="${TSAR_IMAGE_TAG:-latest}"
SKIP_BUILD=false
TEARDOWN=false

# Parse args
for arg in "$@"; do
    case $arg in
        --skip-build)  SKIP_BUILD=true ;;
        --teardown)    TEARDOWN=true ;;
        --help|-h)
            echo "Usage: $0 [--skip-build] [--teardown]"
            echo "  --skip-build   Skip Docker image build"
            echo "  --teardown     Delete the resource group and all resources"
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

if [[ "$SKIP_BUILD" == "false" ]]; then
    command -v docker >/dev/null 2>&1 || fail "Docker not found. Install: https://docs.docker.com/get-docker/"
    ok "Docker found"
fi

# ── Teardown ─────────────────────────────────────────────────
if [[ "$TEARDOWN" == "true" ]]; then
    step "Tearing Down Deployment"
    warn "This will DELETE the resource group '$RESOURCE_GROUP' and ALL resources in it."
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        az group delete --name "$RESOURCE_GROUP" --yes --no-wait
        ok "Resource group '$RESOURCE_GROUP' deletion initiated."
    else
        log "Teardown cancelled."
    fi
    exit 0
fi

# ── Load Environment ─────────────────────────────────────────
step "Loading Environment"

ENV_FILE="deploy/azure/.env.free-tier"
if [[ -f "$ENV_FILE" ]]; then
    # Source non-secret vars only
    export $(grep -E '^[A-Z_]+=' "$ENV_FILE" | grep -v 'API_KEY\|SECRET\|PASSWORD' | xargs) 2>/dev/null || true
    ok "Loaded config from $ENV_FILE"
else
    warn "$ENV_FILE not found — using defaults."
fi

# Validate required secrets
if [[ -z "${EXCHANGE_API_KEY:-}" ]]; then
    warn "EXCHANGE_API_KEY not set. Edit $ENV_FILE before deployment."
fi
if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
    warn "NVIDIA_API_KEY not set. Edit $ENV_FILE before deployment."
fi
if [[ -z "${TSAR_API_KEY:-}" ]]; then
    warn "TSAR_API_KEY not set. Edit $ENV_FILE before deployment."
fi

# ── Step 1: Create Resource Group ───────────────────────────
step "Creating Resource Group"

if az group show --name "$RESOURCE_GROUP" &>/dev/null; then
    ok "Resource group '$RESOURCE_GROUP' already exists."
else
    az group create \
        --name "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --tags project=tsar environment=production tier=free \
        --output none
    ok "Resource group created: $RESOURCE_GROUP ($LOCATION)"
fi

# ── Step 2: Build Docker Image ──────────────────────────────
step "Building Docker Image"

if [[ "$SKIP_BUILD" == "true" ]]; then
    warn "Skipping Docker build (--skip-build)"
else
    log "Building TSAR image (Rust disabled, optimized for free tier)..."
    docker build \
        --build-arg TSAR_RUST_BUILD=0 \
        -f deploy/azure/Dockerfile.azure \
        -t "${IMAGE_NAME}:${IMAGE_TAG}" \
        . 2>&1 | tail -5
    ok "Docker image built: ${IMAGE_NAME}:${IMAGE_TAG}"
fi

# ── Step 3: Push to Azure Container Registry (optional) ─────
# For ACI, we can use a local image if we push to ACR, or use a public image.
# For simplicity, we'll use the Docker Hub approach or local ACR.

USE_ACR=false
if [[ -n "${TSAR_ACR_SERVER:-}" && -n "${TSAR_ACR_USERNAME:-}" && -n "${TSAR_ACR_PASSWORD:-}" ]]; then
    USE_ACR=true
    ACR_SERVER="$TSAR_ACR_SERVER"
    IMAGE_REF="${ACR_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
    log "Pushing to ACR: $ACR_SERVER"
    docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "$IMAGE_REF"
    docker push "$IMAGE_REF"
    ok "Image pushed to ACR: $IMAGE_REF"
else
    warn "No ACR configured. Using local Docker image."
    warn "For ACI deployment, you need ACR or a public registry."
    warn "Set TSAR_ACR_SERVER, TSAR_ACR_USERNAME, TSAR_ACR_PASSWORD in $ENV_FILE"
    warn ""
    warn "Alternatively, using a pre-built image from Docker Hub..."
    IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
fi

# ── Step 4: Deploy to Azure Container Instances ─────────────
step "Deploying to Azure Container Instances"

# Resolve the YAML template
RESOLVED_YAML="deploy/azure/container-group-free.resolved.yaml"
cat > "$RESOLVED_YAML" << YAML_EOF
apiVersion: "2021-10-01"
location: ${LOCATION}
name: ${CONTAINER_GROUP}
type: Microsoft.ContainerInstance/containerGroups

properties:
  osType: Linux
  restartPolicy: OnFailure

  ipAddress:
    type: Public
    ports:
      - port: 8000
        protocol: TCP
    dnsNameLabel: ${DNS_LABEL}

  containers:
    - name: tsar-app
      properties:
        image: ${IMAGE_REF}
        resources:
          requests:
            cpu: 1.0
            memoryInGb: 0.5
        ports:
          - port: 8000
            protocol: TCP
        environmentVariables:
          - name: TSAR_ENVIRONMENT
            value: production
          - name: TSAR_TRADING_MODE
            value: paper
          - name: TSAR_API_PORT
            value: "8000"
          - name: TSAR_DATABASE_BACKEND
            value: sqlite
          - name: TSAR_DATABASE_PATH
            value: /app/data/tsar.db
          - name: TSAR_REDIS_ENABLED
            value: "false"
          - name: TSAR_OLLAMA_ENABLED
            value: "false"
          - name: EXCHANGE_SANDBOX
            value: "true"
          - name: PYTHONUNBUFFERED
            value: "1"
          - name: MALLOC_ARENA_MAX
            value: "2"
        secureEnvironmentVariables:
          - name: EXCHANGE_API_KEY
            value: "${EXCHANGE_API_KEY:-}"
          - name: EXCHANGE_SECRET
            value: "${EXCHANGE_SECRET:-}"
          - name: NVIDIA_API_KEY
            value: "${NVIDIA_API_KEY:-}"
          - name: TSAR_API_KEY
            value: "${TSAR_API_KEY:-}"
          - name: DEEPSEEK_API_KEY
            value: "${DEEPSEEK_API_KEY:-}"
          - name: TELEGRAM_BOT_TOKEN
            value: "${TELEGRAM_BOT_TOKEN:-}"
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

  tags:
    project: tsar
    environment: production
    tier: free
YAML_EOF

log "Deploying container group: $CONTAINER_GROUP"
az container create \
    --resource-group "$RESOURCE_GROUP" \
    --file "$RESOLVED_YAML" \
    --output none

ok "Container group deployed: $CONTAINER_GROUP"

# ── Step 5: Wait for Running State ──────────────────────────
step "Waiting for Container to Start"

for i in $(seq 1 30); do
    STATE=$(az container show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$CONTAINER_GROUP" \
        --query "instanceView.state" -o tsv 2>/dev/null || echo "Pending")
    if [[ "$STATE" == "Running" ]]; then
        ok "Container is running!"
        break
    fi
    log "  State: $STATE (attempt $i/30)"
    sleep 10
done

if [[ "$STATE" != "Running" ]]; then
    fail "Container did not reach running state. Check logs: az container logs -g $RESOURCE_GROUP -n $CONTAINER_GROUP"
fi

# ── Step 6: Get Public URL ──────────────────────────────────
step "Getting Public URL"

PUBLIC_IP=$(az container show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_GROUP" \
    --query "ipAddress.ip" -o tsv 2>/dev/null)

FQDN=$(az container show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_GROUP" \
    --query "ipAddress.fqdn" -o tsv 2>/dev/null)

echo ""
echo "============================================================"
echo "  🚀 TSAR Free Tier Deployment Complete!"
echo "============================================================"
echo ""
echo "  Public IP:    http://${PUBLIC_IP}:8000"
echo "  FQDN:         http://${FQDN}:8000"
echo "  Health:       http://${FQDN}:8000/health"
echo "  API Docs:     http://${FQDN}:8000/docs"
echo ""
echo "  Resource Group:  $RESOURCE_GROUP"
echo "  Container Group: $CONTAINER_GROUP"
echo "  Location:        $LOCATION"
echo ""
echo "  Useful commands:"
echo "    View logs:     az container logs -g $RESOURCE_GROUP -n $CONTAINER_GROUP"
echo "    View state:    az container show -g $RESOURCE_GROUP -n $CONTAINER_GROUP --query instanceView"
echo "    Restart:       az container restart -g $RESOURCE_GROUP -n $CONTAINER_GROUP"
echo "    Stop:          az container stop -g $RESOURCE_GROUP -n $CONTAINER_GROUP"
echo "    Delete:        $0 --teardown"
echo ""
echo "  Monthly cost: ~\$0 (Azure Free Tier — 1 vCPU, 1 GB RAM)"
echo "============================================================"
