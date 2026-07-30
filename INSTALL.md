# TSAR — Installation Guide

## Quick Start (5 minutes)

### 1. Get API Keys (free)

| Key | Where to Get | Cost |
|-----|-------------|------|
| **Binance API** | [testnet.binance.vision](https://testnet.binance.vision) → Generate API Key | Free |
| **NVIDIA API** | [build.nvidia.com](https://build.nvidia.com) → Get API Key | Free |

Optional keys (for enhanced features):
- **DeepSeek API** — Cloud reasoning model ([platform.deepseek.com](https://platform.deepseek.com))
- **Telegram Bot** — Mobile alerts ([@BotFather](https://t.me/BotFather))

### 2. Configure

```bash
git clone https://github.com/ovalentine964/tsar.git
cd tsar
cp .env.example .env
nano .env    # Fill in your API keys
```

### 3. Start

```bash
./quickstart.sh
```

That's it. TSAR is running.

### 4. Access

| Method | How |
|--------|-----|
| **Phone (easiest)** | Open `http://YOUR_SERVER_IP:8000/app` in your phone browser |
| **Telegram** | Send `/status` to your bot |
| **API Docs** | Open `http://YOUR_SERVER_IP:8000/docs` |
| **Flutter APK** | Download from [GitHub Releases](../../releases) |

## Phone Setup

### Option A: Web Dashboard (No installation)
1. Open your phone browser (Chrome/Safari)
2. Go to `http://YOUR_SERVER_IP:8000/app`
3. Enter your API key when prompted
4. Add to home screen for app-like experience

### Option B: Flutter APK
1. Go to [GitHub Releases](../../releases)
2. Download `tsar-mobile.apk`
3. Install (allow unknown sources)
4. Enter your server URL and API key

## Trading Modes

| Mode | Risk | Use |
|------|------|-----|
| `paper` | $0 | Test your strategies safely |
| `live` | Real money | Only after 30+ profitable paper trades |

## First Trade Checklist

- [ ] Binance testnet API keys configured
- [ ] NVIDIA API key configured
- [ ] TSAR running (`curl http://localhost:8000/health`)
- [ ] Phone connected to dashboard
- [ ] Paper mode enabled
- [ ] Wait for first signal (check `/status`)
- [ ] Monitor for 24 hours
- [ ] If profitable, continue for 7 days
- [ ] Only then consider switching to live mode
