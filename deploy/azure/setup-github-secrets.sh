#!/usr/bin/env bash
# ============================================================
# TSAR — Setup GitHub Secrets for Automated Deployment
# ============================================================
# Run this script to configure GitHub Actions secrets.
# Requires: GitHub CLI (gh) installed and authenticated
#
# Usage: ./deploy/azure/setup-github-secrets.sh
# ============================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${BLUE}[TSAR]${NC} $*"; }
ok()   { echo -e "${GREEN}[✅]${NC} $*"; }
warn() { echo -e "${YELLOW}[⚠️]${NC} $*"; }
fail() { echo -e "${RED}[❌]${NC} $*"; exit 1; }

echo -e "${BOLD}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   TSAR — GitHub Secrets Setup                    ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════╝${NC}"
echo ""

# Check gh CLI
if ! command -v gh &> /dev/null; then
    fail "GitHub CLI (gh) not installed. Install: https://cli.github.com"
fi

# Check repo
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null || echo "")
if [ -z "$REPO" ]; then
    fail "Not in a GitHub repo. Run this from the tsar directory."
fi
log "Repository: $REPO"

echo ""
echo -e "${BOLD}I'll ask for each credential. Paste when prompted.${NC}"
echo ""

# Azure credentials
read -p "🔑 Azure Client ID: " AZURE_CLIENT_ID
read -p "🔑 Azure Client Secret: " AZURE_CLIENT_SECRET
read -p "🔑 Azure Subscription ID: " AZURE_SUBSCRIPTION_ID
read -p "🔑 Azure Tenant ID: " AZURE_TENANT_ID

# Exchange credentials
echo ""
read -p "📊 Binance Testnet API Key: " EXCHANGE_API_KEY
read -p "📊 Binance Testnet Secret: " EXCHANGE_SECRET

# AI credentials
echo ""
read -p "🧠 NVIDIA NIM API Key: " NVIDIA_API_KEY
read -p "💡 DeepSeek API Key (press Enter to skip): " DEEPSEEK_API_KEY

# TSAR API
echo ""
TSAR_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
log "Generated TSAR API Key: ${TSAR_API_KEY:0:16}..."

# Set all secrets
echo ""
log "Setting GitHub secrets..."

gh secret set AZURE_CLIENT_ID --body "$AZURE_CLIENT_ID" && ok "AZURE_CLIENT_ID set"
gh secret set AZURE_CLIENT_SECRET --body "$AZURE_CLIENT_SECRET" && ok "AZURE_CLIENT_SECRET set"
gh secret set AZURE_SUBSCRIPTION_ID --body "$AZURE_SUBSCRIPTION_ID" && ok "AZURE_SUBSCRIPTION_ID set"
gh secret set AZURE_TENANT_ID --body "$AZURE_TENANT_ID" && ok "AZURE_TENANT_ID set"
gh secret set EXCHANGE_API_KEY --body "$EXCHANGE_API_KEY" && ok "EXCHANGE_API_KEY set"
gh secret set EXCHANGE_SECRET --body "$EXCHANGE_SECRET" && ok "EXCHANGE_SECRET set"
gh secret set NVIDIA_API_KEY --body "$NVIDIA_API_KEY" && ok "NVIDIA_API_KEY set"
gh secret set TSAR_API_KEY --body "$TSAR_API_KEY" && ok "TSAR_API_KEY set"

if [ -n "$DEEPSEEK_API_KEY" ]; then
    gh secret set DEEPSEEK_API_KEY --body "$DEEPSEEK_API_KEY" && ok "DEEPSEEK_API_KEY set"
else
    warn "DeepSeek API key skipped"
fi

echo ""
echo -e "${GREEN}${BOLD}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║   ✅ All secrets configured!                      ║${NC}"
echo -e "${GREEN}${BOLD}║                                                   ║${NC}"
echo -e "${GREEN}${BOLD}║   Push to main to trigger deployment:             ║${NC}"
echo -e "${GREEN}${BOLD}║   git push origin main                            ║${NC}"
echo -e "${GREEN}${BOLD}║                                                   ║${NC}"
echo -e "${GREEN}${BOLD}║   Or trigger manually:                            ║${NC}"
echo -e "${GREEN}${BOLD}║   gh workflow run deploy-azure.yml                ║${NC}"
echo -e "${GREEN}${BOLD}║                                                   ║${NC}"
echo -e "${GREEN}${BOLD}║   APK: Go to Actions → latest run → Artifacts     ║${NC}"
echo -e "${GREEN}${BOLD}╚═══════════════════════════════════════════════════╝${NC}"
