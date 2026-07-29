#!/bin/bash
set -e

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║         TSAR — Quick Start Setup                 ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Check .env
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✓ Created .env from .env.example"
        echo "⚠  EDIT .env AND FILL IN YOUR API KEYS BEFORE STARTING!"
        echo ""
        echo "Required keys:"
        echo "  1. EXCHANGE_API_KEY + EXCHANGE_SECRET (from Binance testnet)"
        echo "  2. NVIDIA_API_KEY (from build.nvidia.com — free)"
        echo ""
        echo "Optional:"
        echo "  3. TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (for phone alerts)"
        echo ""
        echo "After filling in .env, run: ./quickstart.sh"
        exit 1
    fi
fi

# Check if keys are filled
if grep -q "← FILL IN" .env 2>/dev/null; then
    echo "⚠  You have unfilled values in .env:"
    grep "← FILL IN" .env | sed 's/=.*/ ← PLEASE FILL IN/'
    echo ""
    echo "Edit .env and replace '← FILL IN' with your actual keys."
    exit 1
fi

echo "✓ .env configured"

# Start services
echo "Starting TSAR..."
docker-compose up -d

echo ""
echo "Waiting for services..."
sleep 5

# Check health
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ TSAR API is running at http://localhost:8000"
else
    echo "⏳ TSAR is still starting... wait 30 seconds and check http://localhost:8000/health"
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  TSAR is running!                                ║"
echo "║                                                  ║"
echo "║  API:     http://localhost:8000/docs              ║"
echo "║  Health:  http://localhost:8000/health            ║"
echo "║  Mobile:  Download APK from GitHub Releases      ║"
echo "║  Telegram: Send /status to your bot              ║"
echo "╚══════════════════════════════════════════════════╝"
