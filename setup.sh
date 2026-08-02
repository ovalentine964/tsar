#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# TSAR — One-Command Setup
# Usage: curl -sSL https://raw.githubusercontent.com/ovalentine964/tsar/main/setup.sh | bash
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

TSAR_VERSION="0.2.2"
TSAR_DIR="${TSAR_DIR:-tsar}"
GITHUB_REPO="ovalentine964/tsar"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

print_banner() {
    echo -e "${CYAN}"
    cat << 'EOF'
    ████████╗███████╗ █████╗ ██████╗ 
    ╚══██╔══╝██╔════╝██╔══██╗██╔══██╗
       ██║   ███████╗███████║██████╔╝
       ██║   ╚════██║██╔══██║██╔══██╗
       ██║   ███████║██║  ██║██║  ██║
       ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
    Trading Super Agent for Returns
EOF
    echo -e "${NC}"
}

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }
info()  { echo -e "${BLUE}[→]${NC} $1"; }
step()  { echo -e "\n${BOLD}${CYAN}═══ $1 ═══${NC}"; }

# ── Check prerequisites ───────────────────────────────────────

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

check_prerequisites() {
    step "Checking prerequisites"
    
    local missing=()
    
    if check_command docker; then
        log "Docker found: $(docker --version | head -1)"
    else
        missing+=("docker")
    fi
    
    if check_command docker-compose || docker compose version &>/dev/null; then
        log "Docker Compose found"
    else
        missing+=("docker-compose")
    fi
    
    if check_command git; then
        log "Git found: $(git --version)"
    else
        missing+=("git")
    fi
    
    if check_command curl; then
        log "curl found"
    else
        missing+=("curl")
    fi
    
    if [ ${#missing[@]} -gt 0 ]; then
        err "Missing required tools: ${missing[*]}"
        echo ""
        echo "Install them first:"
        echo "  Docker:     https://docs.docker.com/get-docker/"
        echo "  Git:        https://git-scm.com/downloads"
        echo ""
        exit 1
    fi
    
    # Check Docker is running
    if ! docker info &>/dev/null; then
        err "Docker is not running. Start Docker and try again."
        exit 1
    fi
    log "Docker daemon is running"
}

# ── Clone or update repo ──────────────────────────────────────

clone_or_update() {
    step "Getting TSAR source"
    
    if [ -d "$TSAR_DIR" ]; then
        warn "Directory '$TSAR_DIR' exists, pulling latest..."
        cd "$TSAR_DIR"
        git pull --quiet
        log "Updated to latest"
    else
        info "Cloning repository..."
        git clone --quiet "https://github.com/$GITHUB_REPO.git" "$TSAR_DIR"
        cd "$TSAR_DIR"
        log "Cloned v$TSAR_VERSION"
    fi
}

# ── Generate .env ─────────────────────────────────────────────

generate_env() {
    step "Generating configuration"
    
    if [ -f .env ] && grep -q "TSAR_API_KEY" .env; then
        warn ".env already exists, keeping existing config"
        source .env 2>/dev/null || true
        return
    fi
    
    # Generate secrets
    local api_key
    local redis_pw
    api_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || openssl rand -base64 48 | tr -d '/+=' | head -c 64)
    redis_pw=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    
    cat > .env << EOF
# ═══════════════════════════════════════════════════════════════
# TSAR Configuration — Generated $(date -u +"%Y-%m-%d %H:%M UTC")
# ═══════════════════════════════════════════════════════════════

# ── Security ──────────────────────────────────────────────────
TSAR_API_KEY=$api_key
REDIS_PASSWORD=$redis_pw

# ── Exchange (Binance Testnet — free, no real money) ──────────
# Get keys: https://testnet.binance.vision/
EXCHANGE_API_KEY=
EXCHANGE_SECRET=

# ── LLM (NVIDIA NIM — free tier) ────────────────────────────
# Get key: https://build.nvidia.com/
NVIDIA_API_KEY=

# ── Telegram (optional — phone alerts) ───────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ── CORS (auto-filled after Azure deploy) ────────────────────
TSAR_CORS_ORIGINS=*

EOF
    
    log "Generated .env with secure secrets"
    info "API Key: ${api_key:0:16}..."
    info "Edit .env to add your exchange and LLM keys"
}

# ── Build Docker image ────────────────────────────────────────

build_image() {
    step "Building Docker image"
    
    info "This takes 2-5 minutes on first run..."
    
    docker build \
        --build-arg TSAR_RUST_BUILD=0 \
        -t tsar:latest \
        -t tsar:v$TSAR_VERSION \
        . 2>&1 | tail -5
    
    log "Docker image built: tsar:latest"
}

# ── Start services ────────────────────────────────────────────

start_services() {
    step "Starting TSAR"
    
    # Stop any existing containers
    docker compose down 2>/dev/null || true
    
    # Start
    docker compose up -d redis app 2>&1 | tail -3
    
    log "Services started"
    
    # Wait for health
    info "Waiting for health check..."
    local retries=30
    local count=0
    while [ $count -lt $retries ]; do
        if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
            log "TSAR is healthy!"
            break
        fi
        count=$((count + 1))
        sleep 2
    done
    
    if [ $count -eq $retries ]; then
        warn "Health check timed out — check logs: docker compose logs app"
    fi
}

# ── Print summary ─────────────────────────────────────────────

print_summary() {
    step "Setup Complete!"
    
    source .env 2>/dev/null || true
    
    echo -e ""
    echo -e "${GREEN}${BOLD}  🏰 TSAR is running!${NC}"
    echo -e ""
    echo -e "  ${CYAN}API:${NC}        http://localhost:8000"
    echo -e "  ${CYAN}Docs:${NC}       http://localhost:8000/docs"
    echo -e "  ${CYAN}Health:${NC}     http://localhost:8000/health"
    echo -e "  ${CYAN}API Key:${NC}    ${TSAR_API_KEY:0:24}..."
    echo -e ""
    echo -e "  ${YELLOW}Mode:${NC}       Paper trading (safe — no real money)"
    echo -e "  ${YELLOW}Logs:${NC}       docker compose logs -f app"
    echo -e "  ${YELLOW}Stop:${NC}       docker compose down"
    echo -e "  ${YELLOW}Restart:${NC}    docker compose restart"
    echo -e ""
    echo -e "  ${BOLD}Next steps:${NC}"
    echo -e "  1. Get Binance testnet keys: ${CYAN}https://testnet.binance.vision/${NC}"
    echo -e "  2. Get NVIDIA API key:       ${CYAN}https://build.nvidia.com/${NC}"
    echo -e "  3. Edit .env with your keys"
    echo -e "  4. Restart: docker compose restart"
    echo -e ""
    echo -e "  ${BOLD}Mobile app:${NC}"
    echo -e "  Download: ${CYAN}https://ovalentine964.github.io/tsar/${NC}"
    echo -e "  Set Base URL to: http://YOUR_IP:8000"
    echo -e "  Set API Key to:  ${TSAR_API_KEY:0:24}..."
    echo -e ""
    echo -e "  ${BOLD}Deploy to Azure:${NC}"
    echo -e "  ./scripts/deploy-azure.sh eastus"
    echo -e ""
}

# ── Main ──────────────────────────────────────────────────────

main() {
    print_banner
    check_prerequisites
    clone_or_update
    generate_env
    build_image
    start_services
    print_summary
}

main "$@"
