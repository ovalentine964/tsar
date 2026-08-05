# TSAR TSAR Deployment Checklist — $10 Binance Paper Trading

**Target:** Render.com (starter plan)  
**Strategy:** TSAR (Valentine Money Printing Machine)  
**Mode:** Paper trading on Binance testnet  
**Budget:** $10 capital, ~$7/mo hosting  

---

## Pre-Deployment

- [ ] **Binance Testnet API Key**
  - Go to https://testnet.binance.vision
  - Generate API Key + Secret
  - Save securely — will be set in Render env vars

- [ ] **NVIDIA NIM API Key**
  - Go to https://build.nvidia.com
  - Create free account → Get API Key
  - Free tier: sufficient for TSAR's LLM calls

- [ ] **Generate TSAR_API_KEY**
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
  - Save this — TSAR refuses to start without a valid key

- [ ] **Verify Dockerfile.trading** exists and starts full system
  ```bash
  grep "CMD" Dockerfile.trading
  # Should show: CMD ["python", "-m", "src", "--paper", ...]
  # NOT: CMD ["python", "-m", "uvicorn", ...]
  ```

- [ ] **Verify TSAR strategy is registered**
  ```bash
  grep -r "TSARStrategy" src/strategy/__init__.py
  # Should show import statement
  ```

---

## Deployment Steps

### Option A: Render Blueprint (recommended)

1. Push repo to GitHub (if not already)
2. Go to Render Dashboard → New → Blueprint
3. Connect GitHub repo — Render reads `render.yaml`
4. Set environment variables in the Render UI:
   - `EXCHANGE_API_KEY` → Binance testnet key
   - `EXCHANGE_SECRET` → Binance testnet secret
   - `NVIDIA_API_KEY` → NVIDIA NIM key
   - `TSAR_API_KEY` → Generated key from above
5. Click **Apply** — Render builds and deploys

### Option B: Manual Docker Service

1. Go to Render Dashboard → New → Web Service
2. Connect GitHub repo
3. Set:
   - **Runtime:** Docker
   - **Dockerfile Path:** `./Dockerfile.trading`
   - **Region:** Oregon
   - **Plan:** Starter ($7/mo)
4. Add all env vars from `.env.render`
5. Add disk:
   - **Name:** tsar-data
   - **Mount Path:** /app/data
   - **Size:** 1 GB
6. Set health check path: `/health`
7. Deploy

---

## Post-Deployment Verification

- [ ] **Health check passes**
  - Visit `https://tsar-trading.onrender.com/health`
  - Should return 200 OK

- [ ] **System is running in paper mode**
  - Check logs for: `🏰 TSAR v0.2.0 — PAPER MODE`
  - Check logs for: `📝 Paper execution engine: balance=$10.00`

- [ ] **TSAR strategy is active**
  - Check logs for: `TSARStrategy` initialization
  - Check logs for: `TSAR_STATUS=ACTIVE`

- [ ] **All 13 agents started**
  - Check logs for: `✅ Created 13 agents`
  - Agents: orchestrator, signal_scout, risk_guardian, execution_sniper, execution_tracker, flywheel_orchestrator, information_agent, market_cartographer, regime_detector, macro_agent, sentiment_agent, trade_philosopher, strategy_geneticist

- [ ] **Watchdog is running**
  - Check logs for: `✅ Watchdog started`

- [ ] **No secret validation errors**
  - If you see `SECURITY VALIDATION FAILED` → check API keys

---

## Monitoring

- **Logs:** Render Dashboard → Service → Logs
- **Health:** `https://tsar-trading.onrender.com/health`
- **API Docs:** `https://tsar-trading.onrender.com/docs`

### Key Log Patterns to Watch

| Pattern | Meaning |
|---------|---------|
| `🏰 TSAR v0.2.0 — PAPER MODE` | System started correctly |
| `✅ Created 13 agents` | All agents initialized |
| `📝 Paper execution engine` | Paper trading active |
| `🔄 Cycle` | Trading loop running |
| `🔴 KILL SWITCH` | Emergency stop triggered |
| `SECURITY VALIDATION FAILED` | Bad/missing API key |

---

## Resource Usage (Starter Plan)

| Resource | Limit | TSAR Usage |
|----------|-------|------------|
| CPU | 0.5 CPU | ~0.3 CPU (paper mode) |
| RAM | 512 MB | ~300-400 MB |
| Disk | 1 GB | ~50 MB (SQLite + logs) |
| Cost | $7/mo | Within $10 budget |

**Total monthly cost:** $7 hosting + $10 trading capital = $17

---

## Troubleshooting

### System won't start
1. Check logs for `SECURITY VALIDATION FAILED` → set all required keys
2. Check logs for `ModuleNotFoundError` → build failed, check Dockerfile
3. Ensure `Dockerfile.trading` exists (not just `Dockerfile`)

### No trades executing
1. Verify `TSAR_TRADING_MODE=paper` (not `live`)
2. Check `EXCHANGE_SANDBOX=true` for testnet
3. TSAR requires 7-layer confirmation — trades are infrequent by design
4. Check if kill switch is active: look for `🔴 KILL SWITCH`

### High memory usage
1. Redis and Ollama are disabled by default — shouldn't be an issue
2. If OOM: reduce `TSAR_MAX_OPEN_POSITIONS` to 2

### Want to go live (real money)
1. **DO NOT** change `TSAR_TRADING_MODE` to `live` without:
   - Completing the paper trading mandate (see `config/mandate.yaml`)
   - Understanding the kill switch and risk limits
   - Setting real Binance API keys (not testnet)
   - Changing `EXCHANGE_SANDBOX=false`
2. Review `CRYPTO_TRADING_READINESS_REPORT.md` first

---

## File Reference

| File | Purpose |
|------|---------|
| `render.yaml` | Render deployment blueprint |
| `.env.render` | Env var template for Render |
| `Dockerfile.trading` | Trading system Docker image |
| `config/strategies/tsar.yaml` | TSAR strategy genome |
| `config/tsar.yaml` | Main TSAR configuration |
| `src/strategy/tsar/` | TSAR strategy implementation |
| `src/agents/tsar_strategy_router.py` | Regime-aware TSAR router |
