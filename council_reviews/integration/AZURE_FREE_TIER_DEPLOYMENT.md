# TSAR — Azure Free Tier Deployment Plan

> **Council:** Azure Free Tier Integration
> **Date:** 2026-07-30
> **Status:** APPROVED — Ready for implementation
> **Target Cost:** $0/month (free tier) → ~$4.75/month (minimal paid)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Infrastructure Requirements Analysis](#2-infrastructure-requirements-analysis)
3. [Azure Free Tier Resource Mapping](#3-azure-free-tier-resource-mapping)
4. [Architecture Design](#4-architecture-design)
5. [Deployment Scripts](#5-deployment-scripts)
6. [Cost Estimate](#6-cost-estimate)
7. [Auto-Scaling Growth Path](#7-auto-scaling-growth-path)
8. [Monitoring Design](#8-monitoring-design)
9. [Operational Runbook](#9-operational-runbook)
10. [Risk Register](#10-risk-register)

---

## 1. Executive Summary

TSAR's infrastructure consists of a Python 3.12 FastAPI application, Redis for caching/event bus, SQLite for persistence, a Telegram bot for alerts, and optional local LLM inference. This plan maps each component to Azure's free tier, accepting one critical trade-off: **the 1GB RAM B1s VM cannot run the full stack simultaneously with Ollama**. The solution uses external LLM APIs (NVIDIA NIM, already configured in TSAR) instead of local Ollama, and compresses Redis usage to fit within Azure Cache for Redis's 25MB free tier.

**Result:** TSAR runs at **$0/month** for the first 12 months (Azure free tier period), then ~$4.75/month thereafter.

---

## 2. Infrastructure Requirements Analysis

### 2.1 Component Resource Profile

| Component | CPU | RAM | Storage | Network | Persistent? |
|---|---|---|---|---|---|
| FastAPI app (uvicorn) | 0.5 vCPU | 256–512MB | 100MB code | Inbound :8000 | No (stateless) |
| SQLite (aiosqlite) | Minimal | 50MB cache | 1–5GB data | Local only | **Yes** |
| Redis | 0.25 vCPU | 128–256MB | 100MB AOF | Local :6379 | **Yes** |
| Telegram bot | Minimal | 64MB | None | Outbound HTTPS | No |
| Ollama (LLM) | 2+ vCPU | 2–4GB | 2–8GB models | Local :11434 | **Yes** |
| Prometheus | 0.1 vCPU | 128MB | 1GB metrics | Local :9090 | Yes |
| Grafana | 0.1 vCPU | 128MB | 100MB | Inbound :3000 | Yes |

### 2.2 Total Requirements (Full Stack)

- **CPU:** ~3.1 vCPU minimum
- **RAM:** ~3.2–5.5 GB
- **Storage:** ~5–15 GB
- **Verdict:** Exceeds any single free tier resource. Must decompose.

### 2.3 Key Architectural Decisions

| Decision | Rationale |
|---|---|
| **Drop Ollama** | 4GB RAM requirement impossible on free tier. Use NVIDIA NIM API (already in TSAR) or Azure OpenAI free credits. |
| **Replace Prometheus+Grafana** | 256MB+ RAM for monitoring stack. Use Azure Application Insights (free tier: 5GB/month ingestion). |
| **Use Azure Cache for Redis** | 25MB free tier. TSAR's Redis usage (event bus + LLM cache + session state) fits if we configure `maxmemory-policy allkeys-lru` and keep data lean. |
| **SQLite on Azure Files** | Persist SQLite DB on Azure Blob Storage (5GB free) via periodic backup. SQLite stays local on VM for performance. |
| **Single B1s VM** | 750 hours/month free. One VM runs FastAPI + Telegram bot + lightweight cron. |

---

## 3. Azure Free Tier Resource Mapping

### 3.1 Resource Allocation Table

| TSAR Component | Azure Resource | Free Tier Limit | Utilization |
|---|---|---|---|
| **FastAPI + Telegram Bot** | Azure VM (B1s) | 750 hrs/month, 1 vCPU, 1GB RAM | ~60% RAM, ~30% CPU |
| **Redis Cache** | Azure Cache for Redis (Basic C0) | 25MB | ~20MB active data |
| **SQLite Database** | Azure Blob Storage | 5GB LRS | ~100MB–2GB |
| **Monitoring** | Application Insights | 5GB/month ingestion | ~500MB/month |
| **API Gateway** | Azure Functions (consumption) | 1M requests/month | Health checks, cron triggers |
| **Container Registry** | Docker Hub (free) | Unlimited public | TSAR Docker image |
| **Secrets** | Azure Key Vault | Free (limited ops) | API keys, tokens |

### 3.2 What's NOT Deployed on Free Tier

| Component | Reason | Alternative |
|---|---|---|
| Ollama LLM | 4GB+ RAM needed | NVIDIA NIM API (free tier: 1000 credits/month) |
| Grafana | 256MB RAM, separate service | Azure Application Insights dashboards |
| Prometheus | 128MB RAM, storage | Application Insights metrics |
| AKS (Kubernetes) | Overkill for single container | VM + Docker Compose |
| Azure SQL | SQLite is sufficient for $10 capital | Keep SQLite, backup to Blob |

---

## 4. Architecture Design

### 4.1 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Azure Free Tier                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Azure VM — B1s (1 vCPU, 1GB RAM)                  │   │
│  │  Ubuntu 22.04 LTS                                   │   │
│  │                                                     │   │
│  │  ┌──────────────┐  ┌──────────────┐                │   │
│  │  │  FastAPI      │  │  Telegram    │                │   │
│  │  │  (uvicorn)    │  │  Bot         │                │   │
│  │  │  :8000        │  │  (async)     │                │   │
│  │  └──────┬───────┘  └──────┬───────┘                │   │
│  │         │                  │                         │   │
│  │  ┌──────┴──────────────────┴───────┐                │   │
│  │  │  SQLite (local /data/tsar.db)   │                │   │
│  │  │  + Blob backup (cron)           │                │   │
│  │  └────────────────────────────────┘                │   │
│  │                                                     │   │
│  │  ┌────────────────────────────────┐                │   │
│  │  │  Azure Monitor Agent           │                │   │
│  │  │  (telemetry → App Insights)    │                │   │
│  │  └────────────────────────────────┘                │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           │ Redis protocol                  │
│                           ▼                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Azure Cache for Redis — Basic C0 (25MB)            │   │
│  │  • Event bus (pub/sub)                              │   │
│  │  • LLM response cache                              │   │
│  │  • Session state                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Azure Blob Storage (5GB LRS)                       │   │
│  │  • SQLite database backups                          │   │
│  │  • Trade logs archive                               │   │
│  │  • Model artifacts                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Azure Application Insights (5GB/month)             │   │
│  │  • Custom metrics from TSAR                         │   │
│  │  • Request tracing                                  │   │
│  │  • Exception tracking                               │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Azure Key Vault                                    │   │
│  │  • Exchange API keys                                │   │
│  │  • Telegram bot token                               │   │
│  │  • NVIDIA API key                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ HTTPS (outbound)
                           ▼
            ┌──────────────────────────────┐
            │  External APIs               │
            │  • Binance (exchange)        │
            │  • NVIDIA NIM (LLM)          │
            │  • Telegram API              │
            └──────────────────────────────┘
```

### 4.2 Data Flow

```
1. Telegram user → Telegram API → TSAR Bot (polling/webhook)
2. Bot → FastAPI internal routes → Agent orchestrator
3. Agent → Redis (cache/event bus) → Other agents (pub/sub)
4. Agent → SQLite (trade records, knowledge)
5. Agent → NVIDIA NIM API (LLM inference)
6. Agent → Binance API (market data, order execution)
7. All components → Application Insights (metrics, traces)
8. Cron → Azure Blob (SQLite backup every 6h)
```

### 4.3 Redis Strategy for 25MB Limit

TSAR's current Redis config allows 256MB. We must compress to 25MB:

```python
# Adapted TSAR Redis config for Azure Free Tier
REDIS_MAXMEMORY = "20mb"           # Leave 5MB headroom
REDIS_MAXMEMORY_POLICY = "allkeys-lru"  # Evict least-used keys
REDIS_SAVE = ""                     # Disable RDB snapshots (use AOF only)
REDIS_APPENDONLY = "yes"
REDIS_APPENDFSYNC = "everysec"
```

**Key changes to TSAR source:**
- LLM cache TTL: reduce from default to 1 hour (trading signals are time-sensitive)
- Event bus messages: auto-expire after 5 minutes
- Session state: compress with msgpack (already a dependency)
- Knowledge graph: keep on SQLite, not Redis

**Estimated Redis usage breakdown:**
| Data Type | Size | TTL |
|---|---|---|
| LLM cache | ~5MB | 1 hour |
| Event bus (pub/sub) | ~2MB | 5 minutes |
| Market data cache | ~8MB | 30 seconds |
| Session state | ~3MB | 24 hours |
| Misc counters | ~2MB | No expiry |
| **Total** | **~20MB** | — |

---

## 5. Deployment Scripts

### 5.1 Azure Resource Provisioning (Bicep)

```bicep
// ============================================================
// TSAR Azure Free Tier — Infrastructure as Code
// File: infra/main.bicep
// ============================================================

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Unique suffix for globally-unique resource names')
param uniqueSuffix string = uniqueString(resourceGroup().id)

@description('VM admin SSH public key')
@secure()
param adminSshKey string

@description('TSAR environment (production/staging)')
param environment string = 'production'

// ── Variables ────────────────────────────────────────────────
var vmName = 'tsar-vm'
var vnetName = 'tsar-vnet'
var subnetName = 'tsar-subnet'
var nsgName = 'tsar-nsg'
var redisName = 'tsar-redis-${uniqueSuffix}'
var storageAccountName = 'tsarstore${uniqueSuffix}'
var appInsightsName = 'tsar-insights'
var keyVaultName = 'tsar-kv-${uniqueSuffix}'

// ── Virtual Network ──────────────────────────────────────────
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.0.0.0/16'] }
    subnets: [
      {
        name: subnetName
        properties: {
          addressPrefix: '10.0.1.0/24'
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

// ── Network Security Group ───────────────────────────────────
resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: nsgName
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowSSH'
        properties: {
          priority: 100
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
      {
        name: 'AllowTSARAPI'
        properties: {
          priority: 200
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '8000'
        }
      }
    ]
  }
}

// ── Public IP ────────────────────────────────────────────────
resource publicIp 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: '${vmName}-pip'
  location: location
  sku: { name: 'Basic' }
  properties: {
    publicIPAllocationMethod: 'Dynamic'
  }
}

// ── NIC ──────────────────────────────────────────────────────
resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${vmName}-nic'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: { id: publicIp.id }
          subnet: { id: vnet.properties.subnets[0].id }
        }
      }
    ]
  }
}

// ── Virtual Machine (B1s — Free Tier) ───────────────────────
resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: vmName
  location: location
  properties: {
    hardwareProfile: { vmSize: 'Standard_B1s' }
    osProfile: {
      computerName: vmName
      adminUsername: 'tsar'
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/tsar/.ssh/authorized_keys'
              keyData: adminSshKey
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: { storageAccountType: 'Standard_LRS' }
        diskSizeGB: 30
      }
    }
    networkProfile: {
      networkInterfaces: [{ id: nic.id }]
    }
  }

  // ── Custom Script Extension: Install Docker + deploy TSAR ──
  resource installScript 'extensions' = {
    name: 'install-tsar'
    location: location
    properties: {
      type: 'CustomScript'
      typeHandlerVersion: '2.1'
      autoUpgradeMinorVersion: true
      settings: {
        commandToExecute: 'bash -c "curl -fsSL https://get.docker.com | sh && usermod -aG docker tsar"'
      }
    }
  }
}

// ── Azure Cache for Redis (Basic C0 — Free) ─────────────────
resource redis 'Microsoft.Cache/redis@2024-03-01' = {
  name: redisName
  location: location
  properties: {
    sku: {
      name: 'Basic'
      family: 'C'
      capacity: 0                    // C0 = 25MB
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisVersion: '6'
  }
}

// ── Storage Account (Blob — 5GB free) ────────────────────────
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }

  resource blobService 'blobServices' = {
    name: 'default'
    resource container 'containers' = {
      name: 'tsar-data'
    }
  }
}

// ── Application Insights (Free — 5GB/month) ─────────────────
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 90
    WorkspaceResourceId: logAnalytics.id
  }
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'tsar-logs'
  location: location
  properties: {
    sku: { name: 'Free' }           // Free: 500MB/day, 7-day retention
    retentionInDays: 7
  }
}

// ── Key Vault (Free tier) ────────────────────────────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { name: 'standard', family: 'A' }
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enableRbacAuthorization: true
    networkAcls: {
      defaultAction: 'Allow'       // Restrict in production
    }
  }
}

// ── Outputs ──────────────────────────────────────────────────
output vmPublicIP string = publicIp.properties.ipAddress
output redisHostName string = redis.properties.hostName
output redisSslPort int = redis.properties.sslPort
output storageAccountName string = storageAccount.name
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output keyVaultUri string = keyVault.properties.vaultUri
```

### 5.2 Deployment Script

```bash
#!/bin/bash
# ============================================================
# TSAR Azure Free Tier — Deployment Script
# File: infra/deploy.sh
# ============================================================
set -euo pipefail

# ── Configuration ────────────────────────────────────────────
RESOURCE_GROUP="tsar-rg"
LOCATION="eastus"                      # Cheapest region
DEPLOYMENT_NAME="tsar-deploy-$(date +%Y%m%d%H%M%S)"
SSH_KEY_PATH="$HOME/.ssh/tsar_azure.pub"

# ── Pre-flight checks ────────────────────────────────────────
echo "🔍 Checking prerequisites..."
command -v az >/dev/null || { echo "❌ Azure CLI not found. Install: https://aka.ms/installazurecli"; exit 1; }
az account show >/dev/null 2>&1 || { echo "❌ Not logged in. Run: az login"; exit 1; }

# Generate SSH key if missing
if [ ! -f "$SSH_KEY_PATH" ]; then
    echo "🔑 Generating SSH key pair..."
    ssh-keygen -t ed25519 -f "${SSH_KEY_PATH%.pub}" -N "" -C "tsar-azure"
fi

# ── Create Resource Group ────────────────────────────────────
echo "📦 Creating resource group: $RESOURCE_GROUP"
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --tags project=tsar environment=production cost-target=free

# ── Deploy Bicep Template ────────────────────────────────────
echo "🚀 Deploying infrastructure..."
az deployment group create \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --template-file main.bicep \
    --parameters \
        adminSshKey="$(cat $SSH_KEY_PATH)" \
        environment=production

# ── Get Outputs ──────────────────────────────────────────────
VM_IP=$(az deployment group show \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query 'properties.outputs.vmPublicIP.value' -o tsv)

REDIS_HOST=$(az deployment group show \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query 'properties.outputs.redisHostName.value' -o tsv)

REDIS_KEY=$(az redis list-keys \
    --name "tsar-redis-$(az deployment group show \
        --name "$DEPLOYMENT_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query 'properties.outputs.redisHostName.value' -o tsv | cut -d. -f1)" \
    --resource-group "$RESOURCE_GROUP" \
    --query 'primaryKey' -o tsv)

APP_INSIGHTS_CONN=$(az deployment group show \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query 'properties.outputs.appInsightsConnectionString.value' -o tsv)

STORAGE_ACCOUNT=$(az deployment group show \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query 'properties.outputs.storageAccountName.value' -o tsv)

# ── Store secrets in Key Vault ───────────────────────────────
KV_NAME=$(az deployment group show \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query 'properties.outputs.keyVaultUri.value' -o tsv | sed 's|https://||;s|\.vault\.azure\.net/||')

echo "🔐 Storing secrets in Key Vault..."
az keyvault secret set --vault-name "$KV_NAME" --name "redis-password" --value "$REDIS_KEY" >/dev/null
az keyvault secret set --vault-name "$KV_NAME" --name "app-insights-connection" --value "$APP_INSIGHTS_CONN" >/dev/null

# ── Wait for VM to be ready ──────────────────────────────────
echo "⏳ Waiting for VM SSH to be ready..."
for i in $(seq 1 30); do
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 tsar@"$VM_IP" "echo ok" 2>/dev/null && break
    sleep 10
done

# ── Deploy TSAR to VM ────────────────────────────────────────
echo "🐳 Deploying TSAR to VM..."
ssh -o StrictHostKeyChecking=no tsar@"$VM_IP" << REMOTE_SCRIPT
    # Clone TSAR
    git clone https://github.com/tsar-project/tsar.git ~/tsar
    cd ~/tsar

    # Create .env from template
    cat > .env << ENVFILE
# Azure Free Tier Configuration
REDIS_HOST=$REDIS_HOST
REDIS_PORT=6380
REDIS_PASSWORD=$REDIS_KEY
REDIS_SSL=true

APPINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_CONN

TSAR_API_PORT=8000
TSAR_TRADING_MODE=paper
TSAR_ENVIRONMENT=production

# User must fill these in:
EXCHANGE_API_KEY=
EXCHANGE_SECRET=
NVIDIA_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TSAR_API_KEY=
ENVFILE

    # Build and start (without Docker — save RAM on B1s)
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .

    # Start TSAR as systemd service
    sudo tee /etc/systemd/system/tsar.service << 'SERVICE'
[Unit]
Description=TSAR Trading Super Agent
After=network.target

[Service]
Type=simple
User=tsar
WorkingDirectory=/home/tsar/tsar
EnvironmentFile=/home/tsar/tsar/.env
ExecStart=/home/tsar/tsar/.venv/bin/python -m src
Restart=always
RestartSec=10
MemoryMax=700M
CPUQuota=80%

[Install]
WantedBy=multi-user.target
SERVICE

    sudo systemctl daemon-reload
    sudo systemctl enable tsar
    echo "✅ TSAR installed. Configure .env then: sudo systemctl start tsar"
REMOTE_SCRIPT

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ TSAR Azure Free Tier Deployment Complete"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  VM IP:       $VM_IP"
echo "  Redis Host:  $REDIS_HOST"
echo "  SSH:         ssh tsar@$VM_IP"
echo ""
echo "  Next steps:"
echo "  1. SSH into VM: ssh tsar@$VM_IP"
echo "  2. Edit ~/tsar/.env with your API keys"
echo "  3. Start TSAR: sudo systemctl start tsar"
echo "  4. Verify: curl http://$VM_IP:8000/health"
echo ""
```

### 5.3 Docker Compose Override for Azure

```yaml
# ============================================================
# TSAR — Azure Free Tier Docker Compose Override
# File: docker-compose.azure.yml
# ============================================================
# Usage: docker compose -f docker-compose.yml -f docker-compose.azure.yml up -d
#
# This override disables local Redis (uses Azure Cache for Redis)
# and removes monitoring stack (uses Application Insights instead).

services:
  redis:
    # Disable local Redis — use Azure Cache for Redis
    deploy:
      replicas: 0
    profiles:
      - disabled

  app:
    environment:
      - REDIS_HOST=${REDIS_HOST}
      - REDIS_PORT=${REDIS_PORT:-6380}
      - REDIS_PASSWORD=${REDIS_PASSWORD}
      - REDIS_SSL=true
      - APPINSIGHTS_CONNECTION_STRING=${APPINSIGHTS_CONNECTION_STRING}
      - TSAR_RESOURCE_PROFILE=free-tier
    deploy:
      resources:
        limits:
          cpus: "0.8"
          memory: 700M        # B1s has 1GB; leave room for OS
        reservations:
          cpus: "0.25"
          memory: 256M
    # Remove depends_on redis since we use Azure Cache
    depends_on: []

  prometheus:
    profiles:
      - disabled              # Use Application Insights instead

  grafana:
    profiles:
      - disabled              # Use Application Insights dashboards instead
```

### 5.4 SQLite Backup to Azure Blob (Cron Script)

```bash
#!/bin/bash
# ============================================================
# TSAR SQLite → Azure Blob Backup
# File: scripts/backup-sqlite.sh
# Run via cron: 0 */6 * * * /home/tsar/tsar/scripts/backup-sqlite.sh
# ============================================================
set -euo pipefail

DB_PATH="/home/tsar/tsar/data/tsar.db"
BACKUP_DIR="/tmp/tsar-backup"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT_NAME}"
CONTAINER="tsar-data"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="tsar_backup_${TIMESTAMP}.db"

# Create consistent backup using SQLite's backup command
mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_PATH" ".backup '${BACKUP_DIR}/${BACKUP_NAME}'"

# Compress
gzip "${BACKUP_DIR}/${BACKUP_NAME}"
BACKUP_FILE="${BACKUP_DIR}/${BACKUP_NAME}.gz"

# Upload to Azure Blob Storage
az storage blob upload \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "backups/${BACKUP_NAME}.gz" \
    --file "$BACKUP_FILE" \
    --auth-mode login \
    --overwrite

# Keep only last 10 backups in blob
BLOBS=$(az storage blob list \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --prefix "backups/tsar_backup_" \
    --query '[].name' -o tsv | sort | head -n -10)

for blob in $BLOBS; do
    az storage blob delete \
        --account-name "$STORAGE_ACCOUNT" \
        --container-name "$CONTAINER" \
        --name "$blob" \
        --auth-mode login
done

# Cleanup local
rm -f "$BACKUP_FILE"

echo "[$(date)] Backup completed: ${BACKUP_NAME}.gz"
```

### 5.5 TSAR Application Modifications for Azure

```python
# ============================================================
# TSAR Azure Integration Module
# File: src/utils/azure_config.py
# ============================================================
"""
Azure-specific configuration and integrations for free tier deployment.
Import conditionally — only active when TSAR_RESOURCE_PROFILE=free-tier.
"""

import os
from typing import Optional


def is_azure_free_tier() -> bool:
    """Check if running on Azure free tier profile."""
    return os.getenv("TSAR_RESOURCE_PROFILE") == "free-tier"


def get_redis_config() -> dict:
    """
    Return Redis connection config.
    Azure Cache for Redis uses SSL on port 6380.
    """
    if is_azure_free_tier():
        return {
            "host": os.getenv("REDIS_HOST", "localhost"),
            "port": int(os.getenv("REDIS_PORT", "6380")),
            "password": os.getenv("REDIS_PASSWORD", ""),
            "ssl": os.getenv("REDIS_SSL", "true").lower() == "true",
            "ssl_cert_reqs": None,
            "max_connections": 5,       # Conserve connections on C0
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
            "retry_on_timeout": True,
            "decode_responses": True,
        }
    return {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", "6379")),
        "password": os.getenv("REDIS_PASSWORD", ""),
        "ssl": False,
    }


def get_memory_limits() -> dict:
    """Return memory budget based on deployment profile."""
    if is_azure_free_tier():
        return {
            "llm_cache_max_mb": 5,
            "event_bus_max_mb": 2,
            "market_data_cache_mb": 8,
            "session_state_mb": 3,
            "total_redis_mb": 20,
            "app_heap_max_mb": 512,
        }
    return {
        "llm_cache_max_mb": 50,
        "event_bus_max_mb": 20,
        "market_data_cache_mb": 100,
        "session_state_mb": 30,
        "total_redis_mb": 256,
        "app_heap_max_mb": 2048,
    }


def get_llm_config() -> dict:
    """
    LLM configuration for Azure free tier.
    Disable Ollama (not enough RAM), use cloud APIs only.
    """
    if is_azure_free_tier():
        return {
            "providers": ["nvidia_nim", "openai", "deepseek"],
            "ollama_enabled": False,    # Not enough RAM on B1s
            "cache_ttl_seconds": 3600,  # 1 hour cache
            "max_tokens_per_request": 2048,
            "timeout_seconds": 30,
        }
    return {
        "providers": ["ollama", "nvidia_nim", "openai", "deepseek"],
        "ollama_enabled": True,
        "cache_ttl_seconds": 86400,
        "max_tokens_per_request": 4096,
        "timeout_seconds": 60,
    }


def configure_azure_app_insights():
    """Configure Application Insights telemetry if connection string is set."""
    conn_str = os.getenv("APPINSIGHTS_CONNECTION_STRING")
    if not conn_str:
        return None

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=conn_str)
        return conn_str
    except ImportError:
        # azure-monitor-opentelemetry not installed; skip
        return None
```

### 5.6 Systemd Service File

```ini
# ============================================================
# TSAR Systemd Service — Azure B1s Optimized
# File: deploy/tsar.service
# ============================================================
[Unit]
Description=TSAR — Trading Super Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tsar
Group=tsar
WorkingDirectory=/home/tsar/tsar
EnvironmentFile=/home/tsar/tsar/.env

# Use virtual environment
ExecStart=/home/tsar/tsar/.venv/bin/python -m src

# Restart policy
Restart=always
RestartSec=15
StartLimitIntervalSec=300
StartLimitBurst=5

# ── Resource Limits (B1s: 1 vCPU, 1GB RAM) ──
MemoryMax=700M                  # Leave 300MB for OS + buffers
MemoryHigh=600M                 # Soft limit — triggers GC pressure
CPUQuota=80%                    # Leave 20% for OS tasks
TasksMax=64                     # Limit process count

# ── Security Hardening ──
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/tsar/tsar/data /home/tsar/tsar/logs /tmp
PrivateTmp=yes

# ── Logging ──
StandardOutput=journal
StandardError=journal
SyslogIdentifier=tsar

[Install]
WantedBy=multi-user.target
```

### 5.7 Cloud-Init Script (Alternative to Custom Script Extension)

```yaml
# ============================================================
# TSAR Azure VM — Cloud-Init Bootstrap
# File: infra/cloud-init.yml
# ============================================================
# This runs automatically when the VM first boots.

#cloud-config
package_update: true
package_upgrade: true

packages:
  - python3.12
  - python3.12-venv
  - python3-pip
  - sqlite3
  - curl
  - git
  - jq
  - htop
  - iotop
  - azure-cli

# Create tsar user
users:
  - name: tsar
    groups: sudo, docker
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... tsar-azure

# Install Docker (lightweight — no Docker Compose plugin to save RAM)
runcmd:
  # Install Docker
  - curl -fsSL https://get.docker.com | sh
  - usermod -aG docker tsar

  # Install Azure CLI
  - curl -sL https://aka.ms/InstallAzureCLIDeb | bash

  # Set up swap (critical for 1GB RAM!)
  - fallocate -l 1G /swapfile
  - chmod 600 /swapfile
  - mkswap /swapfile
  - swapon /swapfile
  - echo '/swapfile none swap sw 0 0' >> /etc/fstab

  # Tune kernel for low-memory trading workload
  - sysctl -w vm.swappiness=10
  - sysctl -w vm.vfs_cache_pressure=50
  - echo 'vm.swappiness=10' >> /etc/sysctl.conf
  - echo 'vm.vfs_cache_pressure=50' >> /etc/sysctl.conf

  # Clone TSAR
  - su - tsar -c 'git clone https://github.com/tsar-project/tsar.git ~/tsar'

  # Create Python venv and install dependencies
  - su - tsar -c 'cd ~/tsar && python3.12 -m venv .venv && .venv/bin/pip install -e .'

  # Install systemd service
  - cp /home/tsar/tsar/deploy/tsar.service /etc/systemd/system/
  - systemctl daemon-reload
  - systemctl enable tsar

  # Set up backup cron
  - echo '0 */6 * * * tsar /home/tsar/tsar/scripts/backup-sqlite.sh >> /var/log/tsar-backup.log 2>&1' >> /etc/crontab

  # Signal completion
  - echo "TSAR bootstrap complete" > /var/log/tsar-bootstrap.done

final_message: "TSAR VM ready. Configure ~/tsar/.env and run: sudo systemctl start tsar"
```

---

## 6. Cost Estimate

### 6.1 Free Tier Period (First 12 Months)

| Resource | Free Allowance | TSAR Usage | Monthly Cost |
|---|---|---|---|
| Azure VM B1s | 750 hrs/month | 744 hrs (24/7) | **$0.00** |
| Azure Cache for Redis C0 | 25MB | 20MB | **$0.00** |
| Azure Blob Storage | 5GB | ~200MB | **$0.00** |
| Application Insights | 5GB/month | ~500MB | **$0.00** |
| Azure Key Vault | Free ops | ~100 ops/month | **$0.00** |
| Log Analytics | 500MB/day | ~200MB/day | **$0.00** |
| Azure Functions | 1M requests | ~4K requests | **$0.00** |
| Outbound data | 5GB/month | ~2GB | **$0.00** |
| **TOTAL** | | | **$0.00/month** |

### 6.2 Post-Free-Tier (After 12 Months)

| Resource | Monthly Cost | Notes |
|---|---|---|
| Azure VM B1s | $4.75 | Spot pricing; ~$7.59 regular |
| Azure Cache for Redis C0 | $0.00 | Still free (25MB tier) |
| Azure Blob Storage | $0.00 | <5GB stays free |
| Application Insights | $0.00 | <5GB stays free |
| Outbound bandwidth | ~$0.18 | 2GB × $0.087/GB |
| **TOTAL** | **~$4.93/month** | |

### 6.3 NVIDIA NIM API Costs

The NVIDIA NIM API (TSAR's primary LLM) offers free credits:
- Free tier: 1,000 API credits/month
- Each inference call: ~1–5 credits depending on model
- Estimated: 200–1,000 calls/month on free tier
- If exceeded: ~$0.001–0.01 per call

**At $10 starting capital, LLM costs are negligible.**

### 6.4 Total Infrastructure Cost Summary

| Period | Monthly Cost | Annual Cost |
|---|---|---|
| Months 1–12 (free tier) | $0.00 | $0.00 |
| Month 13+ | ~$4.93 | ~$59.16 |
| With NVIDIA NIM overages | ~$5.50 | ~$66.00 |

**Infrastructure cost as % of $10 capital: 0% during free tier.**

---

## 7. Auto-Scaling Growth Path

### 7.1 Scaling Triggers

| Capital Level | Infrastructure Tier | Monthly Cost | Key Changes |
|---|---|---|---|
| **$10 – $500** | Azure Free Tier (B1s) | $0 | Current plan |
| **$500 – $5,000** | B2s + Standard Redis | ~$25 | 2 vCPU, 4GB RAM; enable Ollama |
| **$5,000 – $50,000** | B2s + PostgreSQL + Ollama | ~$75 | Replace SQLite with Azure SQL; GPU inference |
| **$50,000+** | AKS + Premium Redis + GPU | ~$200+ | Kubernetes; multi-region; dedicated GPU |

### 7.2 Phase 1 → Phase 2 Migration Script

```bash
#!/bin/bash
# ============================================================
# TSAR Scale-Up: B1s → B2s (when capital > $500)
# File: scripts/scale-up.sh
# ============================================================
set -euo pipefail

RESOURCE_GROUP="tsar-rg"
VM_NAME="tsar-vm"

echo "📈 Scaling TSAR VM from B1s to B2s..."

# Deallocate VM (required for resize)
az vm deallocate --resource-group "$RESOURCE_GROUP" --name "$VM_NAME"

# Resize to B2s (2 vCPU, 4GB RAM)
az vm resize \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --size "Standard_B2s"

# Start VM
az vm start --resource-group "$RESOURCE_GROUP" --name "$VM_NAME"

# Upgrade Redis to Standard C1 (1GB)
echo "📈 Upgrading Redis to Standard C1..."
az redis update \
    --resource-group "$RESOURCE_GROUP" \
    --name "tsar-redis-*" \
    --sku Standard \
    --vm-size C1

echo "✅ Scale-up complete!"
echo "   VM: B2s (2 vCPU, 4GB RAM)"
echo "   Redis: Standard C1 (1GB)"
echo "   Estimated cost: ~\$25/month"
echo ""
echo "   Next: Edit .env and enable Ollama:"
echo "   TSAR_OLLAMA_ENABLED=true"
```

### 7.3 Phase 2 → Phase 3: SQLite → Azure SQL Migration

```python
# ============================================================
# TSAR Database Migration: SQLite → Azure SQL
# File: scripts/migrate-to-azure-sql.py
# ============================================================
"""
When capital exceeds $5,000, migrate from SQLite to Azure SQL
for better concurrent access, automated backups, and geo-replication.
"""

import asyncio
import sqlite3
import os

# Migration script outline — run once during upgrade
MIGRATION_STEPS = [
    "1. Create Azure SQL Database (Basic tier: ~$5/month)",
    "2. Run schema migration (001_initial_schema.sql adapted for T-SQL)",
    "3. Copy data from SQLite → Azure SQL via Python script",
    "4. Update TSAR config: DATABASE_URL=mssql+pyodbc://...",
    "5. Verify data integrity",
    "6. Switch TSAR to Azure SQL backend",
    "7. Keep SQLite as read-only backup for 30 days",
]
```

### 7.4 Scaling Decision Tree

```
                    ┌─────────────────┐
                    │  Current Capital │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         < $500         $500-$5K        > $5K
              │              │              │
     ┌────────┴────┐  ┌─────┴─────┐  ┌────┴─────┐
     │ Azure Free  │  │  B2s VM   │  │ B2s +    │
     │ Tier (B1s)  │  │  Standard │  │ Azure SQL│
     │ $0/month    │  │  Redis    │  │ + GPU    │
     └─────────────┘  │ ~$25/mo   │  │ ~$75/mo  │
                      └───────────┘  └──────────┘
```

---

## 8. Monitoring Design

### 8.1 Application Insights Integration

Replace Prometheus + Grafana with Azure Application Insights:

```python
# ============================================================
# TSAR Application Insights Integration
# File: src/metrics/azure_monitor.py
# ============================================================
"""
Lightweight Application Insights integration for TSAR.
Uses OpenTelemetry SDK for distributed tracing and custom metrics.
"""

import os
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AzureMonitor:
    """Minimal Application Insights client for TSAR metrics."""

    def __init__(self):
        self.connection_string = os.getenv("APPINSIGHTS_CONNECTION_STRING")
        self.enabled = bool(self.connection_string)
        self._client = None

        if self.enabled:
            try:
                from azure.monitor.opentelemetry import configure_azure_monitor
                configure_azure_monitor(connection_string=self.connection_string)
                logger.info("Application Insights connected")
            except ImportError:
                logger.warning("azure-monitor-opentelemetry not installed; monitoring disabled")
                self.enabled = False

    def track_trade(self, symbol: str, side: str, quantity: float, price: float):
        """Track a trade execution."""
        if not self.enabled:
            return
        from azure.monitor.opentelemetry import get_tracer
        tracer = get_tracer("tsar.trading")
        with tracer.start_as_current_span("trade_execution") as span:
            span.set_attribute("trade.symbol", symbol)
            span.set_attribute("trade.side", side)
            span.set_attribute("trade.quantity", quantity)
            span.set_attribute("trade.price", price)

    def track_metric(self, name: str, value: float, properties: Optional[dict] = None):
        """Track a custom metric."""
        if not self.enabled:
            return
        # Use OpenTelemetry metrics API
        from opentelemetry import metrics
        meter = metrics.get_meter("tsar")
        counter = meter.create_counter(name)
        counter.add(value, properties or {})

    def track_exception(self, exc: Exception, properties: Optional[dict] = None):
        """Track an exception."""
        if not self.enabled:
            return
        logger.error(f"Tracked exception: {exc}", extra=properties or {})
        # Application Insights auto-collects exceptions via OpenTelemetry

    def track_event(self, name: str, properties: Optional[dict] = None):
        """Track a custom event (e.g., regime change, risk alert)."""
        if not self.enabled:
            return
        logger.info(f"Event: {name}", extra=properties or {})
```

### 8.2 Key Metrics Dashboard (Application Insights KQL Queries)

```kql
// ============================================================
// TSAR Monitoring Queries — Application Insights
// ============================================================

// 1. Trade Execution Rate (last 24h)
customEvents
| where name == "trade_execution"
| where timestamp > ago(24h)
| summarize trades=count() by bin(timestamp, 1h)
| render timechart

// 2. Portfolio Value Over Time
customMetrics
| where name == "portfolio_value"
| where timestamp > ago(7d)
| render timechart

// 3. LLM API Latency
dependencies
| where target contains "nvidia" or target contains "openai"
| where timestamp > ago(24h)
| summarize avg_latency=avg(duration), p95_latency=percentile(duration, 95)
    by bin(timestamp, 1h)
| render timechart

// 4. Risk Alerts
customEvents
| where name == "risk_alert"
| where timestamp > ago(7d)
| project timestamp, severity=tostring(customDimensions.severity),
          message=tostring(customDimensions.message)
| order by timestamp desc

// 5. Redis Hit Rate
customMetrics
| where name == "redis_cache_hit_rate"
| where timestamp > ago(24h)
| render timechart

// 6. Error Rate
exceptions
| where timestamp > ago(24h)
| summarize errors=count() by type, bin(timestamp, 1h)
| render timechart

// 7. Memory Usage (VM)
performanceCounters
| where name == "Available MBytes"
| where timestamp > ago(24h)
| render timechart
```

### 8.3 Alert Rules

```bash
# ============================================================
# Azure Monitor Alert Setup
# ============================================================

# Alert: VM CPU > 90% for 5 minutes
az monitor metrics alert create \
    --name "tsar-high-cpu" \
    --resource-group tsar-rg \
    --scopes /subscriptions/{sub}/resourceGroups/tsar-rg/providers/Microsoft.Compute/virtualMachines/tsar-vm \
    --condition "avg Percentage CPU > 90" \
    --window-size 5m \
    --evaluation-frequency 1m \
    --severity 2 \
    --action-group tsar-alerts

# Alert: VM Memory < 100MB available
az monitor metrics alert create \
    --name "tsar-low-memory" \
    --resource-group tsar-rg \
    --scopes /subscriptions/{sub}/resourceGroups/tsar-rg/providers/Microsoft.Compute/virtualMachines/tsar-vm \
    --condition "avg Available Memory Bytes < 104857600" \
    --window-size 5m \
    --evaluation-frequency 1m \
    --severity 1

# Alert: Redis memory > 20MB (close to 25MB limit)
az monitor metrics alert create \
    --name "tsar-redis-memory-high" \
    --resource-group tsar-rg \
    --scopes /subscriptions/{sub}/resourceGroups/tsar-rg/providers/Microsoft.Cache/redis/tsar-redis-* \
    --condition "avg used_memory > 20971520" \
    --window-size 5m \
    --evaluation-frequency 1m \
    --severity 2

# Alert: Application exceptions spike
az monitor metrics alert create \
    --name "tsar-exception-spike" \
    --resource-group tsar-rg \
    --condition "count exceptions > 10" \
    --window-size 15m \
    --severity 3
```

### 8.4 Telegram Alert Integration (Built into TSAR)

TSAR already has a Telegram bot. Use it for monitoring alerts:

```python
# ============================================================
# TSAR Alert → Telegram (existing bot)
# File: src/metrics/alerts.py
# ============================================================
"""
Route critical alerts through the existing Telegram bot.
No additional infrastructure needed.
"""

import asyncio
import os
from datetime import datetime

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def send_alert(message: str, severity: str = "warning"):
    """Send alert to Telegram if configured."""
    if not TELEGRAM_CHAT_ID:
        return

    emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "📢")
    timestamp = datetime.utcnow().strftime("%H:%M UTC")
    formatted = f"{emoji} **TSAR Alert** [{severity.upper()}]\n{timestamp}\n\n{message}"

    # Use existing bot infrastructure
    from src.bot.bot import send_message
    await send_message(TELEGRAM_CHAT_ID, formatted)
```

---

## 9. Operational Runbook

### 9.1 Day 1 Checklist

```bash
# ── Step 1: Deploy infrastructure ──
cd infra/
./deploy.sh

# ── Step 2: SSH into VM ──
ssh tsar@<VM_IP>

# ── Step 3: Configure secrets ──
cd ~/tsar
nano .env
# Fill in: EXCHANGE_API_KEY, EXCHANGE_SECRET, NVIDIA_API_KEY,
#          TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TSAR_API_KEY

# ── Step 4: Start TSAR ──
sudo systemctl start tsar
sudo systemctl status tsar

# ── Step 5: Verify ──
curl http://localhost:8000/health
curl http://localhost:8000/metrics

# ── Step 6: Test Telegram bot ──
# Send /status to your Telegram bot

# ── Step 7: Verify monitoring ──
# Check Application Insights in Azure Portal
```

### 9.2 Daily Operations

```bash
# Check TSAR status
sudo systemctl status tsar

# View logs (last 100 lines)
journalctl -u tsar -n 100 --no-pager

# Check memory usage
free -h

# Check disk usage
df -h

# Check Redis connection
redis-cli -h <REDIS_HOST> -p 6380 --tls -a <PASSWORD> ping

# Restart TSAR
sudo systemctl restart tsar
```

### 9.3 Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| OOM killed | Memory exceeded 700MB | Check for memory leaks; restart service |
| Redis connection refused | Azure Redis SSL mismatch | Verify `REDIS_SSL=true`, port 6380 |
| Slow LLM responses | NVIDIA API rate limit | Check API credits; add caching |
| SQLite locked | Concurrent write contention | Ensure WAL mode; check aiosqlite config |
| High swap usage | Insufficient RAM | Scale up to B2s ($4.75/month) |
| Telegram bot not responding | Token expired or webhook issue | Regenerate token via BotFather |

---

## 10. Risk Register

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| B1s OOM during multi-agent burst | High | Medium | systemd MemoryMax=700M; graceful degradation |
| Azure Redis 25MB exceeded | Medium | Low | LRU eviction; aggressive TTLs; monitor usage |
| SQLite corruption | High | Low | 6-hour backups to Blob; WAL mode; `PRAGMA integrity_check` |
| Free tier expires (12 months) | Medium | Certain | Scale to B2s (~$5/month); plan capital growth |
| NVIDIA NIM free credits exhausted | Low | Low | Fallback to DeepSeek API (cheaper) |
| Azure region outage | High | Very Low | Blob backup enables recovery in any region |
| Exchange API rate limit | Medium | Medium | Cache market data in Redis; respect rate limits |

---

## Appendix A: Azure Free Tier Quick Reference

| Resource | Free Period | Limit |
|---|---|---|
| Virtual Machines (B1s) | 12 months | 750 hrs/month |
| Azure Cache for Redis (C0) | Always free | 25MB |
| Blob Storage | Always free | 5GB LRS |
| Application Insights | Always free | 5GB/month |
| Log Analytics | Always free | 500MB/day |
| Key Vault | Always free | Standard operations |
| Azure Functions | Always free | 1M requests/month |
| Bandwidth | Always free | 5GB outbound/month |
| Azure SQL (Basic) | Always free | 250GB (preview) |

## Appendix B: File Structure

```
tsar/
├── infra/
│   ├── main.bicep              # Azure infrastructure definition
│   ├── deploy.sh               # Deployment automation
│   ├── cloud-init.yml          # VM bootstrap script
│   └── parameters.json         # Bicep parameters
├── deploy/
│   └── tsar.service            # systemd service file
├── docker-compose.azure.yml    # Azure-specific overrides
├── scripts/
│   ├── backup-sqlite.sh        # SQLite → Blob backup
│   └── scale-up.sh             # B1s → B2s migration
└── src/
    └── utils/
        └── azure_config.py     # Azure-specific config
```

---

*Document prepared by the Azure Free Tier Integration Council.*
*Total estimated cost for $10 starting capital: **$0.00/month** for 12 months.*
