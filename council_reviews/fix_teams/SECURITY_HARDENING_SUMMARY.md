# Security Hardening Summary

**Team:** Security Hardening  
**Date:** 2026-07-30  
**Issues Fixed:** C-009, C-019, C-020, H-009, H-010

---

## C-009: Zero API Authentication → FIXED

**File:** `src/api/app.py`

**Problem:** All API endpoints were publicly accessible with no authentication. Anyone could read trade data, trigger kill switches, commit mandates, and control the entire system.

**Solution:** Added Bearer token authentication via FastAPI's `HTTPBearer` security scheme.

- Created `require_api_key` dependency that validates `Authorization: Bearer <TSAR_API_KEY>` headers
- All endpoints now require a valid API key via `Depends(require_api_key)`
- **Health endpoints (`/health`, `/health/ready`, `/api/health`) are excluded** from auth to allow load balancer probes and monitoring
- Mobile app route aliases (`/api/dashboard`, `/api/trades`, etc.) also protected
- Returns `401 Unauthorized` with clear error messages for missing/invalid keys
- Logs failed authentication attempts with client IP

**Auth Flow:**
```
Client → Authorization: Bearer <TSAR_API_KEY> → API validates against env var → 200 or 401
```

---

## C-019: Wildcard CORS with Credentials → FIXED

**File:** `src/api/app.py`

**Problem:** CORS configured with `allow_origins=["*"]` + `allow_credentials=True`, which is a well-known vulnerability allowing any origin to make credentialed requests.

**Solution:**

- Replaced `allow_origins=["*"]` with origins loaded from `TSAR_CORS_ORIGINS` environment variable (comma-separated list)
- Only enables `allow_credentials=True` when specific origins are configured (never with wildcard)
- Restricted `allow_methods` to `GET, POST, PUT, DELETE` (not all methods)
- Restricted `allow_headers` to `Authorization, Content-Type` only
- Logs a warning when `TSAR_CORS_ORIGINS` is not set, denying all cross-origin requests by default (fail-closed)
- Updated `.env.example` with new `TSAR_CORS_ORIGINS` variable

---

## C-020: No Telegram Bot Authorization → FIXED

**Files:** `src/bot/bot.py`, `src/bot/commands.py`

**Problem:** The Telegram bot accepted commands from any chat ID. Anyone who discovered the bot token could issue commands like `/stop` (kill switch) or read system data.

**Solution:**

### `src/bot/bot.py`
- Added `_allowed_chat_ids` set built from `TELEGRAM_CHAT_ID` (primary) + `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated extras)
- Added `_is_authorized(msg)` method that checks message's `chat.id` against whitelist
- `poll_loop()` now silently rejects messages from unauthorized chat IDs with a warning log
- Unauthorized commands are dropped before reaching `handle_command()`

### `src/bot/commands.py`
- Added `is_chat_authorized(chat_id)` function for reusable authorization check
- `handle_command()` now accepts optional `chat_id` parameter
- Returns `"⛔ Unauthorized"` response for unauthorized chat IDs
- **Fail-closed**: If no `TELEGRAM_CHAT_ID` is configured, all commands are denied

---

## H-009: LLM Prompt Injection via Market Data → FIXED

**Files:** `src/llm/prompts.py`, `src/agents/signal_scout.py`

**Problem:** Market data (symbol names, headlines, trade details) is interpolated directly into LLM prompts. A compromised data feed could inject adversarial text to manipulate LLM behavior.

**Solution:**

### `src/llm/prompts.py` — Input Sanitization
Added three defense functions:

1. **`sanitize_field(value)`** — Sanitizes any value before prompt interpolation:
   - Truncates to 2000 chars (prevents token flooding)
   - Strips control characters
   - Detects 13 injection patterns (e.g., "ignore previous instructions", "you are now a", `<|im_start|>`, `[INST]`)
   - Neutralizes matched patterns with `[SANITIZED]` marker
   - Escapes markdown delimiter spoofing (```` ``` ````, `---`)

2. **`sanitize_dict(data)`** — Sanitizes all values in a dict for batch interpolation

3. **`validate_llm_output(text)`** — Post-LLM output validation:
   - Detects signs of successful injection (e.g., "I am now a", "my new instructions")
   - Rejects suspicious outputs with `[Output rejected: suspicious content detected]`
   - Truncates excessively long outputs (>5000 chars)

4. **`get_prompt()` updated** — Now calls `sanitize_dict()` on all kwargs before `template.format()`

### `src/agents/signal_scout.py` — Output Validation
- Imported `sanitize_field` from `src.llm.prompts`
- Sanitizes reasoning text before storing in signal: `" | ".join(sanitize_field(r) for r in reasoning_parts)`
- Validates symbol format with regex: must match `^[A-Z0-9/.-]{1,20}$` (rejects non-trading-pair strings)
- Rejects signals with invalid symbols before publishing

---

## H-010: Weak Default Secrets → FIXED

**Files:** `.env.example`, `src/__main__.py`

**Problem:** Default secrets like `tsar-secret-key-change-me` and `tsar_redis_2026` were hardcoded. Systems could (and likely would) run with these known values.

**Solution:**

### `.env.example`
- Removed all weak default values from secret fields
- `TSAR_API_KEY=` — now empty, with instructions to generate a strong key
- `REDIS_PASSWORD=` — now empty
- Added `TSAR_CORS_ORIGINS=` field for C-019
- Added inline guidance: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`

### `src/__main__.py` — Startup Validation
Added `_validate_secrets()` function called at the very start of `main()`:

- **TSAR_API_KEY**: Must be set, must not be a known weak value, must be ≥16 characters
- **REDIS_PASSWORD**: Checked against weak values if set
- **EXCHANGE_API_KEY / EXCHANGE_SECRET**: Checked against weak values if set
- Known weak values include: `tsar-secret-key-change-me`, `tsar_redis_2026`, `change-me`, `secret`, `password`, `123456`, `default`, `test`, `← FILL IN`
- **Refuses to start** (`SystemExit(1)`) with clear error messages if validation fails
- All errors collected and displayed together (not one at a time)

**Startup flow:**
```
main() → _validate_secrets() → FAIL? → SystemExit(1) with guidance
                             → PASS? → Continue normal startup
```

---

## Files Modified

| File | Issues | Changes |
|------|--------|---------|
| `src/api/app.py` | C-009, C-019 | JWT auth on all endpoints; CORS from env var |
| `src/api/routes/health.py` | — | No changes needed (health exempt from auth at app level) |
| `src/bot/bot.py` | C-020 | Chat ID whitelist, unauthorized message rejection |
| `src/bot/commands.py` | C-020 | Authorization check in handle_command() |
| `src/llm/prompts.py` | H-009 | sanitize_field(), sanitize_dict(), validate_llm_output() |
| `src/agents/signal_scout.py` | H-009 | Symbol validation, reasoning sanitization |
| `.env.example` | H-010 | Removed weak defaults, added generation guidance |
| `src/__main__.py` | H-010 | _validate_secrets() at startup, SystemExit on failure |

## Backward Compatibility

- All existing endpoints still function — they just require the API key header
- Health endpoints remain unauthenticated for monitoring
- Telegram bot still works for authorized chat IDs
- Systems using old `.env` with weak secrets will get a clear error on how to fix it

## New Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TSAR_API_KEY` | Yes | Bearer token for API auth (≥16 chars) |
| `TSAR_CORS_ORIGINS` | No | Comma-separated allowed origins |
| `TELEGRAM_ALLOWED_CHAT_IDS` | No | Additional authorized Telegram chat IDs |
