#!/bin/bash
# ============================================================
# TSAR Render Monitor — Check running instance health
# ============================================================
# Usage:
#   export TSAR_BASE_URL=https://tsar-api.onrender.com
#   export TSAR_API_KEY=your-api-key
#   ./monitor_render.sh
# ============================================================

set -e

BASE_URL="${TSAR_BASE_URL:-http://localhost:8000}"
API_KEY="${TSAR_API_KEY:-}"
DURATION_MIN="${1:-10}"
INTERVAL=30

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         TSAR Render Monitor                                 ║"
echo "║         Monitoring: ${BASE_URL}                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ -z "$API_KEY" ]; then
    echo -e "${RED}ERROR: TSAR_API_KEY not set${NC}"
    exit 1
fi

START_TIME=$(date +%s)
END_TIME=$((START_TIME + DURATION_MIN * 60))
CYCLE=0

while [ $(date +%s) -lt $END_TIME ]; do
    CYCLE=$((CYCLE + 1))
    ELAPSED=$(( ($(date +%s) - START_TIME) / 60 ))

    echo -e "${BLUE}━━━ [${ELAPSED}min] Check #${CYCLE} ━━━${NC}"

    # Health check (no auth)
    HEALTH=$(curl -s "${BASE_URL}/health" 2>/dev/null || echo '{"error":"unreachable"}')
    STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','error'))" 2>/dev/null || echo "error")

    if [ "$STATUS" = "ok" ]; then
        echo -e "  ${GREEN}✓${C.END} Health: ok"
    else
        echo -e "  ${RED}✗${NC} Health: $STATUS"
    fi

    # Dashboard (auth required)
    DASHBOARD=$(curl -s -H "Authorization: Bearer ${API_KEY}" "${BASE_URL}/" 2>/dev/null || echo '{}')
    TRADES=$(echo "$DASHBOARD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('trades',{}).get('total',0))" 2>/dev/null || echo "?")
    KS=$(echo "$DASHBOARD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('kill_switch',{}).get('active','?'))" 2>/dev/null || echo "?")

    echo -e "  ${CYAN}ℹ${NC} Trades: $TRADES | Kill switch: $KS"

    # Risk
    RISK=$(curl -s -H "Authorization: Bearer ${API_KEY}" "${BASE_URL}/api/v1/risk" 2>/dev/null || echo '{}')
    LEVEL=$(echo "$RISK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('level','?'))" 2>/dev/null || echo "?")
    POSITIONS=$(echo "$RISK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('open_positions',0))" 2>/dev/null || echo "?")

    echo -e "  ${CYAN}ℹ${NC} Risk: $LEVEL | Positions: $POSITIONS"

    # Trade stats
    STATS=$(curl -s -H "Authorization: Bearer ${API_KEY}" "${BASE_URL}/api/v1/trades/stats" 2>/dev/null || echo '{}')
    TOTAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total',json.load(open('/dev/stdin')).get('trade_count',0)))" 2>/dev/null || echo "?")
    WINRATE=$(echo "$STATS" | python3 -c "import sys,json; print(f\"{json.load(sys.stdin).get('win_rate',0):.1f}\")" 2>/dev/null || echo "?")
    PNL=$(echo "$STATS" | python3 -c "import sys,json; print(f\"{json.load(sys.stdin).get('total_pnl',0):.2f}\")" 2>/dev/null || echo "?")

    echo -e "  ${CYAN}ℹ${NC} Stats: $TOTAL trades | Win rate: ${WINRATE}% | P&L: \$$PNL"

    echo ""

    if [ $(date +%s) -lt $END_TIME ]; then
        sleep $INTERVAL
    fi
done

echo -e "${GREEN}Monitoring complete — ${DURATION_MIN} minutes elapsed.${NC}"
