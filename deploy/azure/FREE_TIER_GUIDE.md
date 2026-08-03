# TSAR — Azure Free Tier Deployment Guide

Deploy TSAR to Azure for **$0/month** using the Azure Free Tier (first 12 months).

## What You Get

| Resource | Spec | Monthly Cost |
|----------|------|-------------|
| Azure Container Instance | 1 vCPU, 1 GB RAM | **$0** (750h/mo free) |
| Public IP | Basic dynamic | **$0** (included) |
| Container storage | 5 GB local | **$0** (included) |
| **Total** | | **$0/month** |

> **Note:** Azure Free Tier gives you 750 hours/month of ACI B1s — enough for a single container running 24/7 (744h).

## Prerequisites

1. **Azure account** with an active subscription
   - [Create free account](https://azure.microsoft.com/en-us/free/)
   - You need **Contributor** role on the subscription

2. **Azure CLI** installed
   ```bash
   # macOS
   brew install azure-cli

   # Linux (Debian/Ubuntu)
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

   # Windows
   winget install Microsoft.AzureCLI
   ```

3. **Docker** installed (for building the image)
   - [Get Docker](https://docs.docker.com/get-docker/)

4. **API Keys** (have these ready):
   - `EXCHANGE_API_KEY` / `EXCHANGE_SECRET` — [Binance Testnet](https://testnet.binance.vision/)
   - `NVIDIA_API_KEY` — [NVIDIA NIM (free)](https://build.nvidia.com)
   - `TSAR_API_KEY` — Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`

## Step-by-Step Deployment

### 1. Login to Azure

```bash
az login
```

### 2. Configure Environment

```bash
cd /path/to/tsar

# Copy the free-tier env template
cp deploy/azure/.env.free-tier .env

# Edit with your API keys
nano .env  # or your preferred editor
```

Fill in the **REQUIRED** fields:
- `EXCHANGE_API_KEY`
- `EXCHANGE_SECRET`
- `NVIDIA_API_KEY`
- `TSAR_API_KEY`

### 3. Deploy

```bash
# Full deploy (builds Docker image + provisions Azure + deploys)
./deploy/azure/deploy-free-tier.sh
```

This script will:
1. ✅ Create a Resource Group (`tsar-free-rg`)
2. ✅ Build the Docker image (Rust disabled, 512MB limit)
3. ✅ Deploy to Azure Container Instances
4. ✅ Configure health checks and networking
5. ✅ Print the public URL

### 4. Verify Deployment

```bash
# Check if it's running
curl https://tsar-app.eastus.azurecontainer.io:8000/health

# Run the health check script
./deploy/azure/health-check.sh https://tsar-app.eastus.azurecontainer.io:8000

# View container logs
az container logs -g tsar-free-rg -n tsar-free-tier
```

Expected health response:
```json
{"status": "ok", "trading_mode": "paper"}
```

## Useful Commands

### View Logs

```bash
# Stream logs
az container logs -g tsar-free-rg -n tsar-free-tier --follow

# Dump logs
az container logs -g tsar-free-rg -n tsar-free-tier > tsar-logs.txt
```

### Container Management

```bash
# Check container state
az container show -g tsar-free-rg -n tsar-free-tier --query instanceView.state

# Restart container
az container restart -g tsar-free-rg -n tsar-free-tier

# Stop container (stops billing)
az container stop -g tsar-free-rg -n tsar-free-tier

# Start container
az container start -g tsar-free-rg -n tsar-free-tier
```

### Update Deployment

```bash
# Rebuild and redeploy
docker build --build-arg TSAR_RUST_BUILD=0 -f deploy/azure/Dockerfile.azure -t tsar:latest .
./deploy/azure/deploy-free-tier.sh
```

### Tear Down

```bash
# Delete everything (stops all costs)
./deploy/azure/deploy-free-tier.sh --teardown
```

## API Endpoints

Once deployed, the following endpoints are available:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check (no auth) |
| `/health/ready` | GET | Readiness probe (checks DB) |
| `/health/detailed` | GET | Detailed system status |
| `/docs` | GET | Interactive API documentation |
| `/api/v1/*` | Various | Trading API (requires `TSAR_API_KEY`) |

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EXCHANGE_API_KEY` | ✅ | — | Binance API key |
| `EXCHANGE_SECRET` | ✅ | — | Binance API secret |
| `NVIDIA_API_KEY` | ✅ | — | NVIDIA NIM API key |
| `TSAR_API_KEY` | ✅ | — | API authentication key |
| `TSAR_TRADING_MODE` | | `paper` | `paper` or `live` |
| `TSAR_API_PORT` | | `8000` | API server port |
| `TSAR_DATABASE_BACKEND` | | `sqlite` | Database type |
| `TSAR_REDIS_ENABLED` | | `false` | Redis (disabled on free tier) |
| `TSAR_OLLAMA_ENABLED` | | `false` | Ollama (disabled on free tier) |
| `EXCHANGE_SANDBOX` | | `true` | Binance testnet mode |
| `DEEPSEEK_API_KEY` | | — | DeepSeek fallback LLM |

### What's Disabled on Free Tier

- **Redis** — Uses SQLite instead (no caching layer)
- **Ollama** — Uses cloud LLMs only (NVIDIA NIM + DeepSeek)
- **Prometheus/Grafana** — No monitoring stack
- **Rust extensions** — Disabled to reduce build time and image size

## Troubleshooting

### Container won't start

```bash
# Check container events
az container show -g tsar-free-rg -n tsar-free-tier --query instanceView.events

# Check logs for errors
az container logs -g tsar-free-rg -n tsar-free-tier 2>&1 | grep -i error
```

### Health check fails

```bash
# Check if the port is accessible
curl -v http://tsar-app.eastus.azurecontainer.io:8000/health

# Check container is running
az container show -g tsar-free-rg -n tsar-free-tier --query instanceView.state
```

### Out of memory

The free tier gives 1 GB RAM. If the container OOMs:
- Reduce `MALLOC_ARENA_MAX=2` (already set)
- Reduce Python threads
- Check for memory leaks in logs

### Costs exceeding $0

- Ensure you're using the **free tier** SKU (B1s equivalent)
- Check: `az consumption usage list --top 5`
- ACI free tier: 750 hours/month of Linux containers

## Cost Breakdown

| Item | Free Tier Allowance | TSAR Usage | Cost |
|------|-------------------|------------|------|
| Container (1 vCPU, 1 GB) | 750 hrs/month | ~744 hrs/month | **$0** |
| Public IP (dynamic) | Included | 1 IP | **$0** |
| Outbound data | 5 GB/month | <1 GB | **$0** |
| Storage | Included | <1 GB | **$0** |
| **Total** | | | **$0/month** |

> After 12 months, ACI costs ~$30-40/month. Consider switching to Azure App Service (free tier) or a VPS at that point.

## Security Notes

- All secrets are passed via `secureEnvironmentVariables` (not baked into the image)
- The container runs as a non-root user (`tsar:1000`)
- CORS is disabled by default (set `TSAR_CORS_ORIGINS` to allow access)
- Paper trading mode prevents real money operations
- Binance sandbox mode ensures testnet-only trading

## File Reference

```
deploy/azure/
├── deploy-free-tier.sh      # Main deployment script
├── .env.free-tier           # Environment template
├── Dockerfile.azure         # Optimized Dockerfile
├── container-group.yaml     # Full ACI YAML (with Redis)
├── health-check.sh          # Health monitoring script
├── monitoring.sh            # Azure Monitor alert setup
└── FREE_TIER_GUIDE.md       # This file
```
