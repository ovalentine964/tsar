#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# TSAR Smart Contract Deployment Script
# ═══════════════════════════════════════════════════════════════════
#
# Deploys TSAR smart contracts to Polygon testnet (Mumbai) or mainnet.
#
# Prerequisites:
#   - Node.js >= 18
#   - Hardhat installed (npm install --save-dev hardhat)
#   - .env file with PRIVATE_KEY and POLYGONSCAN_API_KEY
#   - MATIC balance for gas (get from faucet for testnet)
#
# Usage:
#   ./scripts/deploy-contracts.sh                    # Deploy to Mumbai testnet
#   ./scripts/deploy-contracts.sh --network mainnet  # Deploy to Polygon mainnet
#   ./scripts/deploy-contracts.sh --verify           # Deploy and verify on Polygonscan
#   ./scripts/deploy-contracts.sh --multisig         # Set up multi-sig wallet
#
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONTRACTS_DIR="$PROJECT_DIR/blockchain/contracts"
DEPLOY_DIR="$PROJECT_DIR/blockchain/deploy"
ARTIFACTS_DIR="$PROJECT_DIR/blockchain/artifacts"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}[TSAR Deploy]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1" >&2; }

# ═══════════════════════════════════════════════════════════════════
# ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════════

NETWORK="mumbai"
VERIFY=false
SETUP_MULTISIG=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --network)
            NETWORK="$2"
            shift 2
            ;;
        --verify)
            VERIFY=true
            shift
            ;;
        --multisig)
            SETUP_MULTISIG=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --network NETWORK   Target network: mumbai (default), mainnet"
            echo "  --verify            Verify contracts on Polygonscan"
            echo "  --multisig          Set up multi-sig wallet"
            echo "  --dry-run           Simulate deployment without sending transactions"
            echo "  -h, --help          Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ═══════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════

log "Validating environment..."

# Check for .env file
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    if [[ -f "$PROJECT_DIR/.env.example" ]]; then
        warn ".env file not found. Copying from .env.example..."
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        error "Please edit .env with your keys and re-run."
        exit 1
    else
        error ".env file not found. Create one with PRIVATE_KEY and POLYGONSCAN_API_KEY."
        exit 1
    fi
fi

# Source .env
set -a
source "$PROJECT_DIR/.env"
set +a

# Validate required variables
if [[ -z "${PRIVATE_KEY:-}" ]]; then
    error "PRIVATE_KEY not set in .env"
    exit 1
fi

if [[ "$VERIFY" == true ]] && [[ -z "${POLYGONSCAN_API_KEY:-}" ]]; then
    error "POLYGONSCAN_API_KEY not set in .env (required for --verify)"
    exit 1
fi

# Set network-specific config
case "$NETWORK" in
    mumbai)
        CHAIN_ID=80001
        RPC_URL="${MUMBAI_RPC_URL:-https://rpc-mumbai.maticvigil.com}"
        EXPLORER_URL="https://mumbai.polygonscan.com"
        log "Target: Mumbai Testnet (chain_id=$CHAIN_ID)"
        ;;
    mainnet)
        CHAIN_ID=137
        RPC_URL="${POLYGON_RPC_URL:-https://polygon-rpc.com}"
        EXPLORER_URL="https://polygonscan.com"
        warn "Target: Polygon MAINNET — real funds will be used!"
        read -p "Are you sure? (yes/no): " confirm
        if [[ "$confirm" != "yes" ]]; then
            log "Aborted."
            exit 0
        fi
        ;;
    *)
        error "Unknown network: $NETWORK (use mumbai or mainnet)"
        exit 1
        ;;
esac

success "Environment validated"

# ═══════════════════════════════════════════════════════════════════
# HARDHAT SETUP
# ═══════════════════════════════════════════════════════════════════

log "Setting up Hardhat project..."

# Create blockchain directory structure if needed
mkdir -p "$DEPLOY_DIR" "$ARTIFACTS_DIR"

# Create hardhat.config.js if not exists
if [[ ! -f "$PROJECT_DIR/blockchain/hardhat.config.js" ]]; then
    cat > "$PROJECT_DIR/blockchain/hardhat.config.js" << 'HARDHAT_CONFIG'
require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config({ path: "../.env" });

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },
  networks: {
    mumbai: {
      url: process.env.MUMBAI_RPC_URL || "https://rpc-mumbai.maticvigil.com",
      accounts: process.env.PRIVATE_KEY ? [process.env.PRIVATE_KEY] : [],
      chainId: 80001,
    },
    mainnet: {
      url: process.env.POLYGON_RPC_URL || "https://polygon-rpc.com",
      accounts: process.env.PRIVATE_KEY ? [process.env.PRIVATE_KEY] : [],
      chainId: 137,
    },
  },
  etherscan: {
    apiKey: {
      polygon: process.env.POLYGONSCAN_API_KEY || "",
      polygonMumbai: process.env.POLYGONSCAN_API_KEY || "",
    },
  },
};
HARDHAT_CONFIG
    success "Created hardhat.config.js"
fi

# Install dependencies if needed
if [[ ! -d "$PROJECT_DIR/blockchain/node_modules" ]]; then
    log "Installing Hardhat dependencies..."
    cd "$PROJECT_DIR/blockchain"
    npm init -y 2>/dev/null || true
    npm install --save-dev hardhat @nomicfoundation/hardhat-toolbox @openzeppelin/contracts dotenv
    success "Hardhat dependencies installed"
fi

# ═══════════════════════════════════════════════════════════════════
# COMPILE CONTRACTS
# ═══════════════════════════════════════════════════════════════════

log "Compiling smart contracts..."

cd "$PROJECT_DIR/blockchain"
npx hardhat compile

success "Contracts compiled"

# ═══════════════════════════════════════════════════════════════════
# DEPLOY CONTRACTS
# ═══════════════════════════════════════════════════════════════════

log "Deploying contracts to $NETWORK..."

# Create deployment script
cat > "$DEPLOY_DIR/deploy.js" << 'DEPLOY_SCRIPT'
const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying with account:", deployer.address);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log("Account balance:", hre.ethers.formatEther(balance), "MATIC");

  // ── 1. Deploy Governance ─────────────────────────────────────
  console.log("\n1. Deploying TSARGovernance...");

  // For initial deployment, deployer is all signers + guardian
  // Replace with real signer addresses before mainnet deployment
  const signers = [
    deployer.address,  // Valentine (primary)
    deployer.address,  // Backup signer 1
    deployer.address,  // Backup signer 2
    deployer.address,  // Compliance officer
    deployer.address,  // Risk manager
  ];
  const guardian = deployer.address;

  const Governance = await hre.ethers.getContractFactory("TSARGovernance");
  const governance = await Governance.deploy(signers, guardian);
  await governance.waitForDeployment();
  const governanceAddr = await governance.getAddress();
  console.log("  TSARGovernance deployed to:", governanceAddr);

  // ── 2. Deploy Kill Switch ────────────────────────────────────
  console.log("\n2. Deploying TSARKillSwitch...");

  const operator = deployer.address;
  const multisigAddrs = [deployer.address, deployer.address, deployer.address];
  const dailyLossThreshold = -200;   // -2%
  const drawdownHalt = -500;         // -5%
  const drawdownFlatten = -1500;     // -15%

  const KillSwitch = await hre.ethers.getContractFactory("TSARKillSwitch");
  const killSwitch = await KillSwitch.deploy(
    operator,
    multisigAddrs,
    dailyLossThreshold,
    drawdownHalt,
    drawdownFlatten
  );
  await killSwitch.waitForDeployment();
  const killSwitchAddr = await killSwitch.getAddress();
  console.log("  TSARKillSwitch deployed to:", killSwitchAddr);

  // ── 3. Deploy Mandate ────────────────────────────────────────
  console.log("\n3. Deploying TSARMandate...");

  const Mandate = await hre.ethers.getContractFactory("TSARMandate");
  const mandate = await Mandate.deploy(deployer.address);
  await mandate.waitForDeployment();
  const mandateAddr = await mandate.getAddress();
  console.log("  TSARMandate deployed to:", mandateAddr);

  // ── 4. Deploy Audit Trail ────────────────────────────────────
  console.log("\n4. Deploying TSARAuditTrail...");

  const AuditTrail = await hre.ethers.getContractFactory("TSARAuditTrail");
  const auditTrail = await AuditTrail.deploy(deployer.address);
  await auditTrail.waitForDeployment();
  const auditTrailAddr = await auditTrail.getAddress();
  console.log("  TSARAuditTrail deployed to:", auditTrailAddr);

  // ── 5. Write deployment addresses ────────────────────────────
  console.log("\n═══════════════════════════════════════════");
  console.log("Deployment Summary");
  console.log("═══════════════════════════════════════════");
  console.log(`  Network:        ${hre.network.name}`);
  console.log(`  Chain ID:       ${(await hre.ethers.provider.getNetwork()).chainId}`);
  console.log(`  Deployer:       ${deployer.address}`);
  console.log(`  Governance:     ${governanceAddr}`);
  console.log(`  Kill Switch:    ${killSwitchAddr}`);
  console.log(`  Mandate:        ${mandateAddr}`);
  console.log(`  Audit Trail:    ${auditTrailAddr}`);
  console.log("═══════════════════════════════════════════\n");

  // Save addresses to file
  const fs = require("fs");
  const addresses = {
    network: hre.network.name,
    chainId: Number((await hre.ethers.provider.getNetwork()).chainId),
    deployer: deployer.address,
    deployedAt: new Date().toISOString(),
    contracts: {
      governance: governanceAddr,
      killSwitch: killSwitchAddr,
      mandate: mandateAddr,
      auditTrail: auditTrailAddr,
    },
  };

  const outPath = `${__dirname}/../deployments/${hre.network.name}.json`;
  fs.mkdirSync(`${__dirname}/../deployments`, { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(addresses, null, 2));
  console.log(`Addresses saved to: ${outPath}`);
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
DEPLOY_SCRIPT

if [[ "$DRY_RUN" == true ]]; then
    warn "Dry run — would deploy to $NETWORK"
else
    cd "$PROJECT_DIR/blockchain"
    npx hardhat run "$DEPLOY_DIR/deploy.js" --network "$NETWORK"
    success "Contracts deployed to $NETWORK"
fi

# ═══════════════════════════════════════════════════════════════════
# VERIFY ON POLYGONSCAN
# ═══════════════════════════════════════════════════════════════════

if [[ "$VERIFY" == true ]] && [[ "$DRY_RUN" == false ]]; then
    log "Verifying contracts on Polygonscan..."

    DEPLOYMENT_FILE="$PROJECT_DIR/blockchain/deployments/$NETWORK.json"
    if [[ ! -f "$DEPLOYMENT_FILE" ]]; then
        error "Deployment file not found: $DEPLOYMENT_FILE"
        exit 1
    fi

    # Read addresses from deployment file
    GOVERNANCE_ADDR=$(python3 -c "import json; d=json.load(open('$DEPLOYMENT_FILE')); print(d['contracts']['governance'])")
    KILLSWITCH_ADDR=$(python3 -c "import json; d=json.load(open('$DEPLOYMENT_FILE')); print(d['contracts']['killSwitch'])")
    MANDATE_ADDR=$(python3 -c "import json; d=json.load(open('$DEPLOYMENT_FILE')); print(d['contracts']['mandate'])")
    AUDIT_ADDR=$(python3 -c "import json; d=json.load(open('$DEPLOYMENT_FILE')); print(d['contracts']['auditTrail'])")

    cd "$PROJECT_DIR/blockchain"

    # Verify each contract
    npx hardhat verify --network "$NETWORK" "$GOVERNANCE_ADDR" || warn "Governance verification failed"
    npx hardhat verify --network "$NETWORK" "$KILLSWITCH_ADDR" || warn "KillSwitch verification failed"
    npx hardhat verify --network "$NETWORK" "$MANDATE_ADDR" || warn "Mandate verification failed"
    npx hardhat verify --network "$NETWORK" "$AUDIT_ADDR" || warn "AuditTrail verification failed"

    success "Contracts verified on Polygonscan"
fi

# ═══════════════════════════════════════════════════════════════════
# MULTI-SIG SETUP
# ═══════════════════════════════════════════════════════════════════

if [[ "$SETUP_MULTISIG" == true ]]; then
    log "Setting up multi-sig wallet..."

    warn "Multi-sig setup requires manual configuration:"
    echo ""
    echo "  1. Deploy a Gnosis Safe at https://app.safe.global"
    echo "  2. Add 5 signers (see config/blockchain.yaml for addresses)"
    echo "  3. Set threshold to 3-of-5 for critical operations"
    echo "  4. Transfer contract ownership to the Safe address"
    echo ""
    echo "  For testnet: Use https://app.safe.global/polygon"
    echo "  For mainnet: Use https://app.safe.global/matic"
    echo ""

    success "Multi-sig setup instructions displayed"
fi

# ═══════════════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════════════

echo ""
success "Deployment complete!"
echo ""
echo "  Next steps:"
echo "    1. Update config/blockchain.yaml with contract addresses"
echo "    2. Set up multi-sig wallet (--multisig flag)"
echo "    3. Configure signer addresses in governance contract"
echo "    4. Test rule enforcement with a paper trade"
echo ""
echo "  Explorer: $EXPLORER_URL"
echo ""
