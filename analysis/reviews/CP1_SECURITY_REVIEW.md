# TSAR Checkpoint 1 — Security Review

**Reviewer:** Security Chief (Subagent)
**Date:** 2026-07-24
**Scope:** `src/` (Python), `rust/` (Rust), `cpp/` (C++), `config/` (YAML)
**Severity Scale:** CRITICAL → HIGH → MEDIUM → LOW → INFO

---

## Executive Summary

TSAR's Checkpoint 1 foundation is **structurally sound** — no hardcoded secrets, no `eval`/`exec`/`pickle`, no `unsafe` Rust blocks, and smart pointer usage in C++. However, there are **3 critical** and **4 high** severity issues that must be resolved before any network-exposed deployment. The most dangerous: the API has **zero authentication**, meaning anyone who can reach port 8000 can activate the kill switch, resume trading, or read portfolio state.

**Findings: 3 Critical | 4 High | 5 Medium | 3 Low | 2 Info**

---

## CRITICAL

### C-1: API Endpoints Completely Unauthenticated

**File:** `src/api/routes/trading.py`, `src/api/routes/portfolio.py`
**Impact:** Anyone with network access can halt/resume trading, read positions/P&L

The kill switch and resume endpoints have no authentication whatsoever:

```python
@router.post("/kill-switch")
async def activate_kill_switch(reason: str = "manual"):
    # No auth check — anyone can call this
    ks = KillSwitch()
    await ks.activate(reason)
    return {"status": "activated", "reason": reason}

@router.post("/resume")
async def resume_trading():
    # No auth check — anyone can call this
    ks = KillSwitch()
    await ks.deactivate()
    return {"status": "resumed"}
```

The config defines `api_key: "${TSAR_API_KEY}"` but it is **never enforced** in middleware or route guards. All portfolio, trading, and risk endpoints are similarly exposed.

**Recommendation:** Implement API key authentication middleware before any deployment. At minimum, use FastAPI's `Depends` with an API key header check. The kill switch and resume endpoints should require a separate admin credential.

---

### C-2: CORS Wildcard with Credentials

**File:** `src/api/app.py:41-46`
**Impact:** Any website can make authenticated cross-origin requests to the API

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=api_config.get("cors_origins", ["*"]),
    allow_credentials=True,  # ← Dangerous with wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)
```

The config defaults to `cors_origins: ["*"]`. Combined with `allow_credentials=True`, this allows any malicious website to make credentialed cross-origin requests. While browsers technically block `*` with credentials, the FastAPI middleware may not enforce this correctly, and the intent is clearly permissive.

**Recommendation:** Set explicit allowed origins (e.g., `["http://localhost:3000"]`). Remove `allow_credentials=True` unless specifically needed. Never use wildcard with credentials.

---

### C-3: API Binds to All Interfaces

**File:** `config/default.yaml:67`, `src/__main__.py:61`
**Impact:** API accessible from any network interface, not just localhost

```yaml
api:
  host: "0.0.0.0"
  port: 8000
```

```python
uvicorn.run(app, host="0.0.0.0", port=8000)
```

The supervisor also binds to `0.0.0.0:8001`. Combined with C-1 (no auth), this means the trading system is fully exposed to the network.

**Recommendation:** Default to `127.0.0.1` for development. Only bind to `0.0.0.0` in production behind a reverse proxy with TLS and authentication.

---

## HIGH

### H-1: Kill Switch File in World-Readable /tmp

**File:** `src/risk/kill_switch.py:21`, `config/risk.yaml`
**Impact:** Any local user can activate/deactivate the kill switch

```python
KILL_SWITCH_FILE = "/tmp/tsar_kill_switch"
```

On most Linux systems, `/tmp` is world-readable and world-writable. Any local user or process can:
- `echo '{"active":true}' > /tmp/tsar_kill_switch` — halt trading
- `rm /tmp/tsar_kill_switch` — remove the kill switch protection

The system explicitly documents this as a feature ("External kill"), but it's a privilege escalation vector.

**Recommendation:** Use a path under the application's data directory with appropriate file permissions (e.g., `data/kill_switch` with `0600`). If external triggering is desired, use a Unix socket or authenticated Redis command instead.

---

### H-2: Empty String API Key Fallback

**File:** `src/backends/python/deepseek_provider.py:30`, `src/backends/python/openai_provider.py:30`
**Impact:** Empty API keys sent to providers, causing silent failures or leaked requests

```python
self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
```

If the environment variable is unset, the API key defaults to `""`. This will cause the OpenAI client to send requests with an empty auth header, which could:
- Trigger rate limiting or bans from the provider
- Cause confusing error messages
- Inadvertently send requests without authentication

**Recommendation:** Fail fast if the API key is not configured. Raise a clear error at initialization time rather than silently using an empty string.

---

### H-3: No Input Validation on API Parameters

**File:** `src/api/routes/trading.py:22`, `src/api/routes/portfolio.py`
**Impact:** Potential abuse via extreme parameter values

```python
@router.get("/trades")
async def get_trades(limit: int = 100, symbol: str | None = None):
    # No upper bound on limit — could request millions of records
    # No validation on symbol format
```

The `limit` parameter has no upper bound. A caller could request `limit=999999999`, potentially causing memory exhaustion. The `symbol` parameter is passed directly to exchange queries without format validation.

**Recommendation:** Add `Query(gt=0, le=1000)` constraints on numeric parameters. Validate `symbol` against a whitelist of known trading pairs.

---

### H-4: No Rate Limiting on API

**File:** `src/api/app.py`
**Impact:** API vulnerable to brute force and denial of service

There is no rate limiting middleware on any endpoint. An attacker could:
- Brute force the (non-existent) authentication
- Flood the kill switch endpoint to toggle trading rapidly
- Exhaust server resources with rapid requests

**Recommendation:** Add rate limiting middleware (e.g., `slowapi` or a reverse proxy rate limiter). Especially critical for the kill switch and resume endpoints.

---

## MEDIUM

### M-1: Excessive `unwrap()` in Rust Production Code

**Files:** `rust/crates/pyo3-bindings/src/tick_bridge.rs` (30+ instances), `rust/crates/order-executor/src/tracker.rs:172`
**Impact:** Panics (crashes) on unexpected data in production

The PyO3 bridge code uses `.unwrap()` extensively for dict operations:

```rust
dict.set_item("symbol", &c.symbol).unwrap();
dict.set_item("open", c.open).unwrap();
// ... 30+ more unwrap() calls
```

While PyO3 dict operations are unlikely to fail, the tracker code has a more concerning pattern:

```rust
let eid = order.exchange_order_id.clone().unwrap();  // Panics if None
```

**Recommendation:** Use `?` operator or `.expect("descriptive message")` in production code. For PyO3 bindings, use the `?` operator with proper error propagation. Reserve `.unwrap()` for tests only.

---

### M-2: Broad Exception Swallowing

**Files:** Multiple files (15+ instances)
**Impact:** Errors silently ignored, making debugging difficult and masking security issues

```python
# src/agents/base.py:54
except Exception:
    pass

# src/comms/subscriber.py:46
except Exception:
    pass  # Group already exists

# src/backends/python/deepseek_provider.py:113
except Exception:
    return False  # health_check silently fails
```

The subscriber's `except Exception: pass` on consumer group creation is acceptable (idempotent), but the agent base class silently swallowing all exceptions is dangerous — it could mask authentication failures, network errors, or data corruption.

**Recommendation:** Log exceptions at minimum. Use specific exception types. Never `pass` on bare `except Exception` in production code.

---

### M-3: MessagePack Deserialization Without Schema Validation

**File:** `src/comms/events.py:69`
**Impact:** Malformed or malicious event data could cause downstream errors

```python
def decode_event(data: bytes) -> dict[str, Any]:
    return msgpack.unpackb(data, raw=False)
```

Events from Redis are deserialized without schema validation. If an attacker can write to Redis (or if data is corrupted), they could inject arbitrary data structures that downstream agents would process.

**Recommendation:** Validate deserialized events against the CloudEvents schema. Reject messages that don't match expected structure.

---

### M-4: Config Environment Variable Substitution Has No Validation

**File:** `config/default.yaml`, `config/models.yaml`
**Impact:** Missing env vars silently become literal strings

Config files use `${VAR}` syntax for secrets:

```yaml
api_key: "${DEEPSEEK_API_KEY}"
password: "${REDIS_PASSWORD}"
```

If these environment variables are not set, the literal string `${DEEPSEEK_API_KEY}` will be used as the API key. There is no validation that required variables are actually populated.

**Recommendation:** Add a startup validation step that checks all required environment variables are set. Fail fast with a clear error message listing missing vars.

---

### M-5: CFFI `strncpy` Without Null-Termination Guarantee

**File:** `cpp/cffi-bindings/src/tsar_cffi.cpp:322`
**Impact:** Potential buffer over-read if caller doesn't check

```cpp
std::strncpy(order_id_buf, r->c_str(), order_id_buf_len - 1);
```

While `strncpy` is bounded, if `order_id_buf_len` is 0, this writes to `order_id_buf[-1]` (underflow). Also, `strncpy` does not guarantee null-termination if the source is longer than the buffer.

**Recommendation:** Add explicit null-termination: `order_id_buf[order_id_buf_len - 1] = '\0';`. Validate `order_id_buf_len > 0` before the copy.

---

## LOW

### L-1: C++ `new` Without Exception Safety in CFFI

**File:** `cpp/cffi-bindings/src/tsar_cffi.cpp:55`
**Impact:** Memory leak on allocation failure (mitigated by catch)

```cpp
auto* h = new PricingEngineHandle();
h->engine = std::make_unique<tsar::pricing::PricingEngine>();
```

The `new` is wrapped in a `try/catch(std::bad_alloc&)` which returns `nullptr`. This is acceptable but could be improved with RAII.

**Recommendation:** Consider using `std::make_unique` for the handle itself, or at minimum document the ownership transfer contract.

---

### L-2: Supervisor Service Also Binds to 0.0.0.0

**File:** `config/default.yaml:73-74`
**Impact:** Supervisor endpoint exposed to network

```yaml
supervisor:
  host: "0.0.0.0"
  port: 8001
```

Same issue as C-3 but for the supervisor service.

**Recommendation:** Bind to `127.0.0.1` by default.

---

### L-3: `.env.example` Contains Placeholder Values

**File:** `.env.example`
**Impact:** Low — file is a template, not actual secrets

The `.env.example` file contains placeholder values like `your_binance_api_key_here`. This is expected and correct. The `.gitignore` properly excludes `.env` files.

**Status:** Acceptable. No action needed.

---

## INFO

### I-1: Positive Findings — No Dangerous Patterns

The following security checks **passed**:

| Check | Result |
|-------|--------|
| Hardcoded API keys/tokens | ✅ None found — all use env vars |
| `eval()` / `exec()` / `pickle` | ✅ None found |
| Shell injection (`os.system`, `shell=True`) | ✅ None found |
| Rust `unsafe` blocks | ✅ None found |
| SQL injection | ✅ Parameterized queries used throughout |
| `.env` committed | ✅ Only `.env.example` (correct) |
| `.gitignore` coverage | ✅ Covers `.env`, secrets, build artifacts |
| C++ raw pointer ownership | ✅ Smart pointers (`unique_ptr`) used throughout |
| C++ buffer overflow (strcpy, sprintf) | ✅ None found — uses `strncpy` |

### I-2: Dependency Notes

**Python (`pyproject.toml`):**
- `ccxt>=4.0` — Exchange library, well-maintained, no known critical CVEs at time of review
- `fastapi>=0.110` — Good security track record
- `redis>=5.0` — Standard client, no known issues
- `openai>=1.12` — Official client, acceptable
- `msgpack>=1.0` — Well-tested serialization

**Rust (`Cargo.toml`):**
- `tokio-tungstenite 0.21` with `native-tls` — Uses system TLS, acceptable
- All deps are well-known crates with good maintenance

**No known critical vulnerabilities in declared dependency versions at time of review.** Run `cargo audit` and `pip-audit` as part of CI.

---

## Summary Table

| ID | Severity | Title | File(s) |
|----|----------|-------|---------|
| C-1 | 🔴 CRITICAL | API endpoints unauthenticated | `src/api/routes/` |
| C-2 | 🔴 CRITICAL | CORS wildcard + credentials | `src/api/app.py` |
| C-3 | 🔴 CRITICAL | API binds to 0.0.0.0 | `config/default.yaml`, `src/__main__.py` |
| H-1 | 🟠 HIGH | Kill switch in world-readable /tmp | `src/risk/kill_switch.py` |
| H-2 | 🟠 HIGH | Empty string API key fallback | `src/backends/python/deepseek_provider.py` |
| H-3 | 🟠 HIGH | No input validation on API params | `src/api/routes/` |
| H-4 | 🟠 HIGH | No rate limiting | `src/api/app.py` |
| M-1 | 🟡 MEDIUM | Excessive unwrap() in Rust | `rust/crates/pyo3-bindings/` |
| M-2 | 🟡 MEDIUM | Broad exception swallowing | Multiple files |
| M-3 | 🟡 MEDIUM | No schema validation on events | `src/comms/events.py` |
| M-4 | 🟡 MEDIUM | No env var validation at startup | `config/` |
| M-5 | 🟡 MEDIUM | CFFI strncpy edge case | `cpp/cffi-bindings/src/tsar_cffi.cpp` |
| L-1 | 🔵 LOW | CFFI new without RAII | `cpp/cffi-bindings/src/tsar_cffi.cpp` |
| L-2 | 🔵 LOW | Supervisor binds to 0.0.0.0 | `config/default.yaml` |
| L-3 | 🔵 LOW | .env.example placeholder values | `.env.example` |

---

## Recommended Priority

**Before any network deployment (blocking):**
1. C-1: Add API authentication
2. C-2: Fix CORS configuration
3. C-3: Bind to localhost by default

**Before live trading (high priority):**
4. H-1: Relocate kill switch file
5. H-2: Fail on missing API keys
6. H-3: Add input validation
7. H-4: Add rate limiting

**Before production hardening:**
8. M-1 through M-5: Address medium findings
9. Run `cargo audit` and `pip-audit` in CI
