# 🚀 TSAR — Deploy Now Guide

## Quick Deploy (3 Steps)

### Step 1: Set Your Credentials

You need 3 keys. Paste them here or in the Telegram bot:

```
🔑 Binance Testnet API Key + Secret
   → Get free at: https://testnet.binance.vision/

🧠 NVIDIA NIM API Key  
   → Get free at: https://build.nvidia.com → Get API Key

💡 DeepSeek API Key (optional)
   → Get at: https://platform.deepseek.com
```

### Step 2: Deploy Backend to Azure

```bash
# Login to Azure
az login --service-principal \
  -u YOUR_CLIENT_ID \
  -p YOUR_CLIENT_SECRET \
  --tenant YOUR_TENANT_ID

# Configure
cp deploy/azure/.env.production .env
nano .env  # paste your credentials

# Deploy!
./deploy/azure/deploy-24-7.sh
```

### Step 3: Install APK on Phone

```bash
# APK location after build
mobile/build/app/outputs/flutter-apk/app-debug.apk

# Transfer to phone and install
# Then: Settings → API URL → http://tsar-app.eastus.azurecontainer.io:8000
```

---

## What You Get

| Component | Details |
|-----------|---------|
| **Backend** | Running 24/7 on Azure, $0/month |
| **APK** | Installable on your Android phone |
| **Telegram Bot** | /setup to configure credentials |
| **Paper Trading** | Live Binance data, no real money |
| **Self-healing** | Auto-restart on crash |

## After Deployment

1. Open TSAR app on phone
2. Go to Settings → set API URL
3. Paste credentials via Telegram bot or app
4. Start trading!

## Monitoring

```bash
# Check backend status
curl http://tsar-app.eastus.azurecontainer.io:8000/health

# View logs
az container logs -g tsar-247-rg -n tsar-247

# Monitor (auto-restart on failure)
./deploy/azure/monitor-24-7.sh
```
