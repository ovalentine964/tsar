# TSAR — Deployment Guide

## Deployment Options

| Method | Complexity | Cost | Best For |
|--------|-----------|------|----------|
| **Docker Compose** | Low | Free (local) | Development, personal use |
| **Azure Container Instances** | Medium | ~$0/month (free tier) | Always-on, cloud deployment |
| **Local Install** | Low | Free | Development, testing |

---

## Docker Deployment (Recommended)

### Prerequisites

- Docker 24.0+
- Docker Compose 2.20+

### Quick Start

```bash
# Clone and configure
git clone https://github.com/ovalentine964/tsar.git && cd tsar
cp .env.example .env
nano .env    # Fill in your API keys

# Build and start
make docker-build
make docker-up

# Verify
curl http://localhost:8000/health
```

### Services

| Container | Port | Purpose |
|-----------|------|---------|
| `tsar-app` | 8000 | Trading system + API |
| `tsar-redis` | 6379 | State cache, event bus |

### Optional Monitoring

```bash
docker compose --profile monitoring up -d
```

| Container | Port | Purpose |
|-----------|------|---------|
| `tsar-prometheus` | 9090 | Metrics collection |
| `tsar-grafana` | 3000 | Dashboards (admin/tsar_grafana) |

### Common Commands

```bash
# View logs
make docker-logs

# Restart services
make docker-restart

# Stop services
make docker-down

# Rebuild after code changes
make docker-build && make docker-restart

# Run tests in container
docker compose exec app python -m pytest tests/ -v

# Database backup
make db-backup
```

### Resource Limits

| Container | CPU | Memory |
|-----------|-----|--------|
| tsar-app | 2.0 cores | 1 GB |
| tsar-redis | 1.0 core | 512 MB |
| prometheus | 0.5 core | 512 MB |
| grafana | 0.5 core | 256 MB |

---

## Azure Container Instances

Deploy TSAR to Azure with spot instances for cost savings.

### Prerequisites

- Azure CLI (`az`) installed and authenticated
- Azure Container Registry (ACR) or public image
- Azure Storage Account for persistent data

### Step 1: Create Resource Group

```bash
az group create \
  --name tsar-rg \
  --location eastus
```

### Step 2: Create Storage Shares

```bash
# Create storage account
az storage account create \
  --name tsarstorage \
  --resource-group tsar-rg \
  --location eastus \
  --sku Standard_LRS

# Get storage key
STORAGE_KEY=$(az storage account keys list \
  --resource-group tsar-rg \
  --account-name tsarstorage \
  --query '[0].value' -o tsv)

# Create file shares
az storage share create \
  --name tsar-data \
  --account-name tsarstorage \
  --account-key $STORAGE_KEY

az storage share create \
  --name tsar-logs \
  --account-name tsarstorage \
  --account-key $STORAGE_KEY
```

### Step 3: Push Docker Image to ACR

```bash
# Create ACR
az acr create \
  --resource-group tsar-rg \
  --name tsarregistry \
  --sku Basic

# Login and push
az acr login --name tsarregistry
docker tag tsar:latest tsarregistry.azurecr.io/tsar:latest
docker push tsarregistry.azurecr.io/tsar:latest
```

### Step 4: Deploy Container Group

Edit `deploy/azure/container-group.yaml` to set your secrets, then:

```bash
az container create \
  --resource-group tsar-rg \
  --file deploy/azure/container-group.yaml \
  --location eastus
```

### Step 5: Verify

```bash
# Get public IP
az container show \
  --resource-group tsar-rg \
  --name tsar-container-group \
  --query ipAddress.ip -o tsv

# Check health
curl http://<IP>:8000/health
```

### Monitoring

```bash
# View logs
az container logs \
  --resource-group tsar-rg \
  --name tsar-container-group

# Check container status
az container show \
  --resource-group tsar-rg \
  --name tsar-container-group \
  --query instanceView.state
```

### Cost Optimization

- **Spot instances**: Up to 70% cheaper than on-demand (configured by default)
- **Deallocate on eviction**: Preserves disk state when spot capacity is reclaimed
- **Resource limits**: 1 vCPU + 1 GB RAM total (fits free tier reservations)

---

## Local Install

For development or when Docker is not available.

### Prerequisites

- Python 3.12+
- Redis 7.0+ (install via package manager or Docker)
- SQLite 3.35+ (included with Python)

### Install

```bash
# Clone
git clone https://github.com/ovalentine964/tsar.git && cd tsar

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"

# Configure
cp .env.example .env
nano .env

# Initialize database
make migrate

# Run tests
make test

# Start
python3 -m src --paper
```

### Redis (if not using Docker)

```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl start redis

# Set password
redis-cli CONFIG SET requirepass "your_redis_password"
```

---

## Environment Setup

### Generating Secrets

```bash
# TSAR_API_KEY (48 chars, URL-safe)
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# REDIS_PASSWORD (32 chars, URL-safe)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# TSAR_WALLET_MASTER_KEY (for DeFi wallet encryption)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Firewall Rules

| Port | Protocol | Purpose |
|------|----------|---------|
| 8000 | TCP | TSAR API + Web Dashboard |
| 6379 | TCP | Redis (internal only — do NOT expose) |
| 9090 | TCP | Prometheus (optional, internal) |
| 3000 | TCP | Grafana (optional, internal) |

**Important**: Only port 8000 should be exposed externally. Redis, Prometheus, and Grafana should be internal-only.

### SSL/TLS (Production)

For production deployments, use a reverse proxy (nginx, Caddy, or cloud load balancer) with TLS termination:

```nginx
server {
    listen 443 ssl;
    server_name tsar.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/tsar.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tsar.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## Backup & Recovery

### Database Backup

```bash
# Manual backup
make db-backup

# Automated (via config/default.yaml)
# Hot backup: every 15 minutes, retained 24 hours
# Warm backup: daily at midnight, retained 30 days
# Cold backup: weekly on Sunday, retained 365 days
```

### Redis Backup

```bash
# Trigger Redis BGSAVE
docker compose exec redis redis-cli -a $REDIS_PASSWORD BGSAVE

# Copy RDB file
docker compose cp tsar-redis:/data/dump.rdb ./backups/
```

### Restore

```bash
# Stop services
make docker-down

# Restore database
cp backups/tsar_YYYYMMDD_HHMMSS.db data/tsar.db

# Restore Redis
docker compose cp backups/dump.rdb tsar-redis:/data/dump.rdb

# Start services
make docker-up
```

---

## Health Checks

```bash
# API health
curl http://localhost:8000/health

# Redis health
docker compose exec redis redis-cli -a $REDIS_PASSWORD ping

# Container health
docker compose ps

# Detailed status
curl -H "Authorization: Bearer $TSAR_API_KEY" http://localhost:8000/api/status
```
