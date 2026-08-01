#!/usr/bin/env bash
# ============================================================
# TSAR — One-Command Build Script
# ============================================================
# Usage: ./scripts/build.sh [--version X.Y.Z] [--skip-docker] [--skip-tests]
#
# Steps: lint → typecheck → test → docker build → version tag
# ============================================================

set -euo pipefail

# --- Defaults ---
VERSION=""
SKIP_DOCKER=false
SKIP_TESTS=false
IMAGE_NAME="tsar"
IMAGE_TAG="latest"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}▶ $*${NC}"; }
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
fail() { echo -e "${RED}❌ $*${NC}" >&2; exit 1; }

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)      VERSION="$2"; shift 2 ;;
        --skip-docker)  SKIP_DOCKER=true; shift ;;
        --skip-tests)   SKIP_TESTS=true; shift ;;
        --image-name)   IMAGE_NAME="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--version X.Y.Z] [--skip-docker] [--skip-tests] [--image-name NAME]"
            exit 0
            ;;
        *) fail "Unknown option: $1" ;;
    esac
done

# --- Resolve project root ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# --- Derive version from pyproject.toml if not given ---
if [[ -z "$VERSION" ]]; then
    VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null || echo "0.0.0-dev")
fi

log "TSAR Build — version ${VERSION}"
echo ""

# ── Step 1: Lint ──────────────────────────────────────────────
log "Step 1/4: Linting (ruff)..."
ruff check src/ tests/ || fail "Ruff check failed"
ruff format --check src/ tests/ || fail "Ruff format check failed"
ok "Lint passed"

# ── Step 2: Typecheck ─────────────────────────────────────────
log "Step 2/4: Type checking (mypy)..."
mypy src/ || fail "Mypy failed"
ok "Type check passed"

# ── Step 3: Tests ─────────────────────────────────────────────
if [[ "$SKIP_TESTS" == "false" ]]; then
    log "Step 3/4: Running tests (pytest)..."
    python3 -m pytest tests/ -v --tb=short --cov=src --cov-report=term-missing || fail "Tests failed"
    ok "All tests passed"
else
    warn "Step 3/4: Tests skipped (--skip-tests)"
fi

# ── Step 4: Docker Build ─────────────────────────────────────
if [[ "$SKIP_DOCKER" == "false" ]]; then
    log "Step 4/4: Building Docker image..."
    docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" \
                 -t "${IMAGE_NAME}:${VERSION}" \
                 -f Dockerfile . || fail "Docker build failed"
    ok "Docker image built: ${IMAGE_NAME}:${IMAGE_TAG}, ${IMAGE_NAME}:${VERSION}"

    # Quick smoke test
    log "Verifying image..."
    docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" python -c "import src; print('✅ Import OK')" \
        || fail "Docker smoke test failed"
    ok "Image verified"
else
    warn "Step 4/4: Docker build skipped (--skip-docker)"
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            Build Complete — v${VERSION}${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Lint:       ✅  passed                              ║${NC}"
echo -e "${GREEN}║  Typecheck:  ✅  passed                              ║${NC}"
if [[ "$SKIP_TESTS" == "false" ]]; then
echo -e "${GREEN}║  Tests:      ✅  passed                              ║${NC}"
else
echo -e "${YELLOW}║  Tests:      ⏭️   skipped                             ║${NC}"
fi
if [[ "$SKIP_DOCKER" == "false" ]]; then
echo -e "${GREEN}║  Docker:     ✅  ${IMAGE_NAME}:${IMAGE_TAG}${NC}"
else
echo -e "${YELLOW}║  Docker:     ⏭️   skipped                             ║${NC}"
fi
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
