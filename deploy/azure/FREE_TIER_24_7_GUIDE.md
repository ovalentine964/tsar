# TSAR — Azure Free Tier 24/7 Deployment Guide

## Executive Summary

TSAR runs 24/7 on Azure Container Instances (ACI) within the **Azure Free Tier** at **$0/month for 12 months**.

| Resource | Spec | Monthly Usage | Free Tier Limit | Status |
|----------|------|---------------|-----------------|--------|
| ACI vCPU | 1 vCPU | 744 hours | 750 hours | ✅ Fits |
| ACI RAM | 0.65 GB | 483 GB-hours | 500 GB-hours | ✅ Fits |
| Storage | <1 GB | Azure Files | 5 GB free | ✅ Fits |
| Public IP | Dynamic | Included | Included | ✅ Free |
| Outbound | <1 GB | Standard | 5 GB free | ✅ Fits |
| **Total** | | | | **$0/month** |

> **After 12 months**: ACI costs ~$30-40/month. Migrate to a VPS (Hetzner €4.50/mo, Oracle Cloud free ARM) or Azure App Service Basic B1 (~$13/mo).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Azure Container Instance (ACI)                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  TSAR Container (restartPolicy: Always)           │  │
│  │  ┌─────────────┐  ┌─────────────┐                │  │
│  │  │ FastAPI     │  │ 13 Agents   │                │  │
│  │  │ :8000       │  │ (async)     │                │  │
│  │  └──────┬──────┘  └──────┬──────┘                │  │
│  │         │                │                        │  │
│  │  ┌──────┴────────────────┴──────┐                │  │
│  │  │  SQLite (/app/data/tsar.db) │                │  │
│  │  │  (persistent via Azure Files)│                │  │
│  │  └─────────────────────────────┘                │  │
│  └───────────────────────────────────────────────────┘  │
│       ↕ Azure Files Volume Mounts                       │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ tsar-data    │  │ tsar-logs    │                     │
│  │ (File Share) │  │ (File Share) │                     │
│  └──────────────┘  └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
         ↕ Public IP (port 8000)
    ┌──────────┐
    │ APK /    │
    │ Browser  │
    └──────────┘
```

### Key Design Decisions

1. **No Redis** — SQLite-only mode. Saves 0.25 vCPU + 256 MB RAM.
2. **No Ollama** — Cloud LLMs only (NVIDIA NIM + DeepSeek). Saves ~1 GB RAM.
3. **No monitoring stack** — Prometheus/Grafana replaced by lightweight scripts.
4. **No Rust extensions** — Disabled to reduce image size and build time.
5. **restartPolicy: Always** — Not "OnFailure". Handles platform restarts.
6. **Azure Files persistence** — SQLite database survives container restarts.
7. **Memory: 0.65 GB** — Fits within 500 GB-hour/month free tier budget.

---

## Quick Start (5 Minutes)

### Prerequisites

```bash
# 1. Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# 2. Login
az login

# 3. Install Docker (if building locally)
# https://docs.docker.com/get-docker/
```

### Deploy

```bash
cd /path/to/tsar

# 1. Configure environment
cp deploy/azure/.env.production deploy/azure/.env.production.local
nano deploy/azure/.env.production.local
# Fill in: TSAR_API_KEY, EXCHANGE_API_KEY, EXCHANGE_SECRET, NVIDIA_API_KEY

# 2. Deploy (one command!)
chmod +x deploy/azure/deploy-24-7.sh
./deploy/azure/deploy-24-7.sh

# 3. Verify
curl http://tsar-app.eastus.azurecontainer.io:8000/health
```

### Set Up Monitoring (Recommended)

```bash
# Install the health monitor as a cron job
chmod +x deploy/azure/monitor-24-7.sh
deploy/azure/monitor-24-7.sh --cron  # Shows crontab entry

# Add to crontab:
crontab -e
# */5 * * * * /path/to/tsar/deploy/azure/monitor-24-7.sh >> /var/log/tsar-monitor.log 2>&1
```

---

## Detailed Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TSAR_API_KEY` | ✅ | — | API authentication key (min 16 chars) |
| `EXCHANGE_API_KEY` | ✅ | — | Binance testnet API key |
| `EXCHANGE_SECRET` | ✅ | — | Binance testnet secret |
| `NVIDIA_API_KEY` | ✅ | — | NVIDIA NIM API key (free) |
| `DEEPSEEK_API_KEY` | | — | DeepSeek fallback LLM |
| `TSAR_TRADING_MODE` | | `paper` | Always `paper` on free tier |
| `TSAR_CORS_ORIGINS` | | — | Comma-separated allowed origins |
| `TELEGRAM_BOT_TOKEN` | | — | Telegram bot for alerts |
| `TELEGRAM_CHAT_ID` | | — | Telegram chat for alerts |
| `ALERT_EMAIL` | | — | Email for Azure Monitor alerts |

### Generate API Key

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Get Binance Testnet Keys

1. Go to https://testnet.binance.vision/
2. Click "Generate HMAC_SHA256 Key"
3. Copy API Key and Secret

### Get NVIDIA NIM Key

1. Go to https://build.nvidia.com
2. Sign up (free)
3. Click "Get API Key"
4. Copy the key

---

## Monitoring & Self-Healing

### How TSAR Stays Alive 24/7

Three layers of protection:

| Layer | Mechanism | Trigger |
|-------|-----------|---------|
| **L1: Liveness Probe** | ACI HTTP probe to `/health` | 3 failures → ACI restarts container |
| **L2: restartPolicy** | `Always` | Any exit (crash, OOM, platform restart) |
| **L3: Monitor Script** | External cron job | Health check fails → `az container restart` |

### Liveness Probe Details

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 45    # Wait for Python startup
  periodSeconds: 30          # Check every 30 seconds
  failureThreshold: 3        # 3 failures = restart (90s)
  timeoutSeconds: 10         # 10s timeout per check
```

**What happens on failure:**
1. Health check fails at T+0s
2. Retry at T+30s — fails
3. Retry at T+60s — fails
4. ACI restarts container at T+90s
5. Container reinitializes (45s startup)
6. Health checks resume at T+135s

**Recovery time: ~2-3 minutes** from crash to healthy.

### Monitor Script

The `monitor-24-7.sh` script adds a second layer:

```bash
# One-shot check
./deploy/azure/monitor-24-7.sh

# Continuous monitoring (every 60s)
./deploy/azure/monitor-24-7.sh --loop

# JSON output (for dashboards)
./deploy/azure/monitor-24-7.sh --json
```

**Features:**
- Health endpoint check
- Container state verification
- Restart count tracking (crash loop detection)
- Response time monitoring
- Memory usage tracking
- Auto-restart on 3 consecutive failures
- Cooldown between restarts (5 min)
- Max restart attempts (3)
- Cost monitoring (free tier budget tracking)

### Azure Monitor Alerts (Optional)

```bash
# Set up email alerts for:
# - Container restarts
# - High CPU (>80%)
# - High memory (>850MB)
# - Container deletion
ALERT_EMAIL=you@example.com ./deploy/azure/monitoring.sh
```

---

## Data Persistence

### The Problem

ACI containers are **ephemeral** — data is lost on restart by default.

### The Solution

Azure Files volume mounts persist data across restarts:

```yaml
volumes:
  - name: tsar-data
    azureFile:
      shareName: tsar-data
      storageAccountName: tsar247store...
      storageAccountKey: ...

containers:
  - volumeMounts:
      - name: tsar-data
        mountPath: /app/data    # SQLite database lives here
      - name: tsar-logs
        mountPath: /app/logs    # Logs live here
```

### What's Persisted

| Path | Content | Survives Restart? |
|------|---------|-------------------|
| `/app/data/tsar.db` | SQLite database (trades, patterns, lessons) | ✅ Yes |
| `/app/data/backups/` | Database backups | ✅ Yes |
| `/app/logs/tsar.log` | Application logs | ✅ Yes |
| `/tmp/` | Temporary files | ❌ No |

### Backup Strategy

```bash
# Manual backup (download SQLite database)
az storage file download \
    --account-name tsar247store... \
    --share-name tsar-data \
    --path tsar.db \
    --dest ./tsar-backup.db

# Automated backup (add to cron)
# The deploy script creates a 1 GB file share — enough for months of data
```

---

## Resource Analysis: Will It Fit in 1 GB?

### Memory Budget (0.65 GB = 665 MB)

| Component | Estimated RAM | Notes |
|-----------|--------------|-------|
| OS/Container overhead | ~100 MB | Linux kernel, container runtime |
| Python 3.12 runtime | ~30 MB | Base interpreter |
| FastAPI + Uvicorn | ~40 MB | Web framework |
| CCXT (exchange) | ~30 MB | REST client |
| 13 Agents (idle) | ~60 MB | ~5 MB each, mostly async |
| SQLite (aiosqlite) | ~15 MB | Lightweight, file-based |
| Pydantic models | ~20 MB | Data validation |
| Pandas + NumPy | ~80 MB | Data processing |
| Other deps | ~40 MB | httpx, structlog, etc. |
| **Total estimated** | **~415 MB** | |
| **Available** | **665 MB** | |
| **Headroom** | **~250 MB** | 37% free |

### CPU Budget (1.0 vCPU)

| Component | CPU Usage | Notes |
|-----------|-----------|-------|
| Idle (most of the time) | ~5% | Agents sleep between cycles |
| Trading cycle (every 5 min) | ~30-50% | 30s burst |
| LLM API calls | ~10% | Mostly I/O wait |
| Average | ~10-15% | Well within 1 vCPU |

### Optimization Flags Already Applied

```bash
MALLOC_ARENA_MAX=2          # Reduces glibc memory fragmentation
PYTHONMALLOC=malloc         # Standard allocator (not debug)
PYTHONDONTWRITEBYTECODE=1   # No .pyc files
PYTHONUNBUFFERED=1          # Immediate stdout flush
```

### If Memory Runs Tight

1. Reduce agent count (comment out unused agents in `__main__.py`)
2. Set `TSAR_TRADING_SYMBOLS=BTC/USDT` (single symbol)
3. Reduce `MALLOC_ARENA_MAX=1`
4. Add swap file in container (see below)

---

## Networking

### How APK Connects to Backend

```
APK → http://tsar-app.eastus.azurecontainer.io:8000/api/v1/...
                                    ↓
                          Azure Container Instance
                                    ↓
                          FastAPI (port 8000)
```

### TLS Options

**Option 1: HTTP Only (Simplest)**
- APK connects via `http://` on port 8000
- No TLS termination needed
- Suitable for testing/development

**Option 2: Azure Front Door (Production)**
- Free tier includes Azure Front Door (basic)
- TLS termination at the edge
- Custom domain support
- DDoS protection

**Option 3: Cloudflare Tunnel (Free)**
```bash
# In the container, run cloudflared
# Free TLS + custom domain
```

### CORS Configuration

After deployment, update CORS to allow your APK:

```bash
# Get your container FQDN
FQDN=$(az container show -g tsar-247-rg -n tsar-247 --query "ipAddress.fqdn" -o tsv)

# Update CORS (requires container restart)
# Edit .env.production.local:
TSAR_CORS_ORIGINS=http://${FQDN}:8000,https://yourdomain.com
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check events
az container show -g tsar-247-rg -n tsar-247 --query "instanceView.events" -o yaml

# Check logs
az container logs -g tsar-247-rg -n tsar-247

# Common causes:
# 1. Missing TSAR_API_KEY → secret validation fails
# 2. Image pull failure → check ACR credentials
# 3. OOM → reduce memory usage
```

### Container Keeps Restarting (Crash Loop)

```bash
# Check restart count
az container show -g tsar-247-rg -n tsar-247 --query "instanceView.restartCount"

# Check logs for errors
az container logs -g tsar-247-rg -n tsar-247 2>&1 | grep -i "error\|fatal\|oom"

# Common causes:
# 1. OOM kill → check memory usage
# 2. Secret validation → check TSAR_API_KEY
# 3. Database locked → check SQLite file on Azure Files
```

### Health Check Fails

```bash
# Test manually
curl -v http://tsar-app.eastus.azurecontainer.io:8000/health

# Check if port is accessible
nc -zv tsar-app.eastus.azurecontainer.io 8000

# Check container is running
az container show -g tsar-247-rg -n tsar-247 --query "instanceView.state"
```

### Data Lost After Restart

```bash
# Check if Azure Files is mounted
az container show -g tsar-247-rg -n tsar-247 --query "containers[0].volumeMounts"

# Check file share exists
az storage share exists --name tsar-data --account-name tsar247store...
```

### Costs Exceeding $0

```bash
# Check current usage
az consumption usage list --top 10 --output table

# Verify free tier eligibility
# ACI Linux: 750 vCPU-hours + 500 GB-hours/month
# Your usage: 1 vCPU × 744h = 744 vCPU-hours (within limit)
#             0.65 GB × 744h = 483 GB-hours (within limit)
```

---

## Management Commands

```bash
# Status
./deploy/azure/deploy-24-7.sh --status

# View logs
./deploy/azure/deploy-24-7.sh --logs
# Or directly:
az container logs -g tsar-247-rg -n tsar-247 --follow

# Restart
az container restart -g tsar-247-rg -n tsar-247

# Stop (saves money, stops billing)
az container stop -g tsar-247-rg -n tsar-247

# Start
az container start -g tsar-247-rg -n tsar-247

# Update (redeploy with new image, keep data)
./deploy/azure/deploy-24-7.sh --update

# Delete everything (data lost!)
./deploy/azure/deploy-24-7.sh --teardown
```

---

## Migration Plan: After 12 Months

When the free tier expires, migrate to one of these:

| Option | Cost | Pros | Cons |
|--------|------|------|------|
| **Hetzner CX22** | €4.50/mo | 2 vCPU, 4 GB RAM, 40 GB SSD | Manual setup |
| **Oracle Cloud ARM** | $0 forever | 4 OCPU, 24 GB RAM | Always out of stock |
| **Azure B1s** | ~$13/mo | Same infra, no migration | Costs money |
| **Railway** | $5/mo | Easy deploy | Less control |
| **Fly.io** | ~$2/mo | Cheapest, good DX | Limited RAM |

**Recommended**: Hetzner CX22 or Oracle Cloud (if available). Docker Compose works on any VPS.

---

## File Reference

```
deploy/azure/
├── deploy-24-7.sh              # Main deploy script (use this!)
├── container-group-24-7.yaml   # ACI config optimized for 24/7
├── monitor-24-7.sh             # Monitoring & auto-restart
├── .env.production             # Production env template
├── FREE_TIER_24_7_GUIDE.md     # This file
│
├── deploy-free-tier.sh         # Original deploy script (legacy)
├── container-group.yaml        # Original ACI config (with Redis)
├── Dockerfile.azure            # Azure-optimized Dockerfile
├── .env.free-tier              # Free tier env (legacy)
├── .env.template               # Full env template
├── health-check.sh             # Health check utility
├── monitoring.sh               # Azure Monitor alert setup
└── FREE_TIER_GUIDE.md          # Original guide
```

---

## Security Notes

- All secrets passed via `secureEnvironmentVariables` (not baked into image)
- Container runs as non-root user (`tsar:1000`)
- Paper trading mode prevents real money operations
- Binance sandbox mode ensures testnet-only
- API key required for all non-health endpoints
- CORS restricts cross-origin access
- Storage account uses TLS 1.2 minimum
- Secrets file (`.env.production.local`) should never be committed to git
