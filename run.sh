#!/usr/bin/env bash
# TSAR — Trading Super Agent Regime
# Quick start script

set -e

cd "$(dirname "$0")"

echo "🏰 TSAR — Trading Super Agent Regime"
echo "====================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    exit 1
fi

# Check dependencies
echo "📦 Checking dependencies..."
python3 -c "import pydantic, yaml, aiosqlite" 2>/dev/null || {
    echo "Installing dependencies..."
    pip install pydantic pyyaml aiosqlite -q
}

# Create directories
mkdir -p data logs

# Parse command
case "${1:-dashboard}" in
    paper|start)
        echo "🚀 Starting paper trading..."
        python3 -m src --paper --config config/tsar.yaml --host 0.0.0.0 --port ${2:-8000}
        ;;
    live)
        echo "⚠️  Starting LIVE trading..."
        echo "   Make sure config/mandate.yaml is configured!"
        python3 -m src --live --config config/tsar.yaml --host 0.0.0.0 --port ${2:-8000}
        ;;
    api)
        echo "🌐 Starting API server..."
        python3 -m src --api-only --config config/tsar.yaml --host 0.0.0.0 --port ${2:-8000}
        ;;
    dashboard|status)
        python3 -m src --dashboard --config config/tsar.yaml
        ;;
    test)
        echo "🧪 Running tests..."
        python3 -m pytest tests/ -q --tb=short
        ;;
    *)
        echo "Usage: ./run.sh [command]"
        echo ""
        echo "Commands:"
        echo "  paper     — Start paper trading + API (default)"
        echo "  live      — Start live trading (requires mandate)"
        echo "  api       — API server only"
        echo "  dashboard — Show system status"
        echo "  test      — Run test suite"
        echo ""
        ;;
esac
